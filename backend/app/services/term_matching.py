"""Find glossary terms in source paragraphs, including Polish case forms.

Used by the Translation tab to highlight terms: the server returns, for each
source paragraph, the character spans of glossary terms found in it. The
browser then looks for each term's English target in the translation and
warns when it is missing.

Matching a word against a term word (both folded: lower case, no
diacritics):

- equal to the term or to one of its case-form variants, or
- shares a stem (see ``_stem_rule``): Mira matches Miro and Mirze, Einard
  matches Einardzie, splot matches splocie, Pył matches Pyłem; "splątany"
  does not match splot, "Radość" does not match Rada, and "zapadła" (fell)
  does not match Zapaść.
- If the term starts with a capital letter (names, lore terms), the word in
  the text must too, so "Rada" (the Council) does not match "radość".

Multi-word terms match word by word. Pure functions plus a small cache.
"""

from __future__ import annotations

import os
import re
import unicodedata
from dataclasses import dataclass, field

_WORD = re.compile(r"\w+", re.UNICODE)


def fold(text: str) -> str:
    """Lower case without diacritics (ł has no decomposition, so map it by hand)."""
    decomposed = unicodedata.normalize("NFKD", text.lower().replace("ł", "l"))
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def is_form_of(canonical: str, variant: str) -> bool:
    """True when ``variant`` looks like a case form or spelling of ``canonical``.

    Glossary extraction stores more than inflections in ``variants``: aliases,
    descriptions and sometimes a different name altogether ("Vynmor" under
    "Naelori", "adept" under "Elantria"). Only forms that share each word's
    stem pass: same number of words, and every word pair shares a prefix of
    at least 3 letters and of all but the last 3 letters of the shorter word
    (Miro/Mira, Einardzie/Einard, Hanna/Hania, Pyłu/Pyłem).
    """
    a_words, b_words = fold(canonical).split(), fold(variant).split()
    if not a_words or len(a_words) != len(b_words) or a_words == b_words:
        return False
    for a, b in zip(a_words, b_words, strict=True):
        common = len(os.path.commonprefix([a, b]))
        if common < max(3, min(len(a), len(b)) - 3):
            return False
    return True


def is_same_term(a: str, b: str) -> bool:
    """True when ``a`` and ``b`` are the same term, possibly in another case or number.

    Stricter than ``is_form_of``: word by word, the longer word may only add
    a short ending to the shorter one (the rule used to find terms in the
    text), so "Strategii Obronnych" matches "Strategie Obronne" and "Wysoki
    Ród" matches "Wysokie Rody", while "Sysjusz" does not match "system" and
    "Cień" does not match "cieplak". Used to carry an author's decision over
    to a pending term, where a false match would be costly.
    """
    a_words, b_words = fold(a).split(), fold(b).split()
    if not a_words or len(a_words) != len(b_words):
        return False
    for x, y in zip(a_words, b_words, strict=True):
        shorter, longer = sorted((x, y), key=len)
        if not _stem_match(shorter, longer):
            return False
    return True


# (shared prefix needed, letters the text word may add) by term-word length.
# Short words are strict: "Rada" must not match "Radość".
def _stem_rule(length: int) -> tuple[int, int]:
    if length <= 3:
        return length, 3  # Pył -> Pyłem
    if length == 4:
        return 3, 1  # Mira -> Miro, Mirze; Rada -> Radą, not Radość
    if length == 5:
        return 4, 3  # splot -> splocie, sploty
    # Einard -> Einardzie, Elantria -> Elantrię; not Zapaść -> "zapadła" (fell).
    return length - 1, 4


def _stem_match(term_word: str, text_word: str) -> bool:
    if text_word == term_word:
        return True
    need, extra = _stem_rule(len(term_word))
    if len(text_word) > len(term_word) + extra:
        return False
    return len(os.path.commonprefix([term_word, text_word])) >= need


@dataclass(slots=True)
class Term:
    id: str
    words: list[str]  # folded words of the canonical form
    variants: list[list[str]] = field(default_factory=list)  # folded case-form variants
    capitalised: bool = False


@dataclass(slots=True)
class TermIndex:
    """Terms indexed by the first 3 folded letters of their first word."""

    by_prefix: dict[str, list[Term]] = field(default_factory=dict)

    @classmethod
    def build(cls, terms: list[tuple[str, str, list[str]]]) -> TermIndex:
        """``terms`` is ``[(id, canonical_form, variants)]``."""
        index = cls()
        for term_id, canonical, variants in terms:
            words = fold(canonical).split()
            if not words or len(words[0]) < 3:
                continue
            term = Term(
                id=term_id,
                words=words,
                variants=[fold(v).split() for v in variants if is_form_of(canonical, v)],
                capitalised=canonical[:1].isupper(),
            )
            index.by_prefix.setdefault(words[0][:3], []).append(term)
        # Longer terms first, so "Dar Widzenia Pyłu" wins over "Dar Widzenia".
        for terms_list in index.by_prefix.values():
            terms_list.sort(key=lambda t: -len(t.words))
        return index


def _matches_at(term: Term, tokens: list[re.Match[str]], i: int, folded: list[str]) -> bool:
    n = len(term.words)
    if i + n > len(tokens):
        return False
    if term.capitalised and not tokens[i].group(0)[:1].isupper():
        return False
    window = folded[i : i + n]
    if window == term.words or window in term.variants:
        return True
    return all(_stem_match(tw, w) for tw, w in zip(term.words, window, strict=True))


def find_terms(text: str, index: TermIndex) -> list[tuple[str, int, int]]:
    """``[(term_id, start, end)]`` for every term occurrence, without overlaps."""
    tokens = list(_WORD.finditer(text))
    folded = [fold(t.group(0)) for t in tokens]
    out: list[tuple[str, int, int]] = []
    i = 0
    while i < len(tokens):
        hit: Term | None = None
        for term in index.by_prefix.get(folded[i][:3], []):
            if _matches_at(term, tokens, i, folded):
                hit = term
                break
        if hit is None:
            i += 1
            continue
        last = tokens[i + len(hit.words) - 1]
        out.append((hit.id, tokens[i].start(), last.end()))
        i += len(hit.words)
    return out
