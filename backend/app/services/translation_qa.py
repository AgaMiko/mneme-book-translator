"""Deterministic checks on translated text.

Two kinds:

- **Style metrics** (port of ``translations/zaplataczka/style_metrics.py``):
  share of narration sentences starting with She/He, ellipses and em dashes
  per 1,000 words, stock-phrase hits. Targets come from the polish brief.
  These are measured, not enforced: the polish prompt receives them, and the
  UI shows them per chapter.
- **Hard checks** that point at a translation error: leftover source-language
  letters, Polish dialogue dashes at the start of a paragraph, markdown escape
  backslashes, author placeholders that went missing.

Pure functions; no database access.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

# Polish-brief targets.
SHE_HE_MAX_PCT = 15.0
ELLIPSES_MAX_PER_1K = 3.0
DASHES_MAX_PER_1K = 6.0

STOCK_PHRASES: tuple[str, ...] = (
    r"the weight of",
    r"\ba beat\b",
    r"ghost of a smile",
    r"a flicker of",
    r"couldn't help but",
    r"something shifted",
    r"didn't know (?:she|he) was holding",
    r"let out a breath (?:she|he)",
    r"a wave of",
    r"for a heartbeat",
    r"\bsuddenly\b",
)

# Letters that should not appear in English output, per source language.
SOURCE_LETTERS: dict[str, str] = {
    "pl": "ąćęłńóśźżĄĆĘŁŃÓŚŹŻ",
}

PLACEHOLDER_PATTERNS: tuple[str, ...] = (r"x{4,}", r"\[x+\]")

_QUOTED = re.compile(r'"[^"\n]*"|\u201c[^\u201d\n]*\u201d')
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?\u2026])\s+")
_SHE_HE_OPENER = re.compile(r"^[*_\s]*(She|He)\b")


@dataclass(slots=True)
class StyleMetrics:
    words: int = 0
    narration_sentences: int = 0
    she_he_openers: int = 0
    ellipses: int = 0
    em_dashes: int = 0
    stock: dict[str, int] = field(default_factory=dict)

    @property
    def she_he_pct(self) -> float:
        return round(100 * self.she_he_openers / max(1, self.narration_sentences), 1)

    @property
    def ellipses_per_1k(self) -> float:
        return round(1000 * self.ellipses / max(1, self.words), 1)

    @property
    def dashes_per_1k(self) -> float:
        return round(1000 * self.em_dashes / max(1, self.words), 1)

    @property
    def stock_total(self) -> int:
        return sum(self.stock.values())

    def merge(self, other: StyleMetrics) -> StyleMetrics:
        stock = dict(self.stock)
        for k, v in other.stock.items():
            stock[k] = stock.get(k, 0) + v
        return StyleMetrics(
            words=self.words + other.words,
            narration_sentences=self.narration_sentences + other.narration_sentences,
            she_he_openers=self.she_he_openers + other.she_he_openers,
            ellipses=self.ellipses + other.ellipses,
            em_dashes=self.em_dashes + other.em_dashes,
            stock=stock,
        )

    def over_target(self) -> list[str]:
        """Human-readable list of metrics that miss the polish targets."""
        out: list[str] = []
        if self.she_he_pct > SHE_HE_MAX_PCT:
            out.append(
                f"narration sentences starting with She/He: {self.she_he_pct}% "
                f"(target ≤ {SHE_HE_MAX_PCT:g}%)"
            )
        if self.ellipses_per_1k > ELLIPSES_MAX_PER_1K:
            out.append(
                f"ellipses: {self.ellipses_per_1k} per 1,000 words "
                f"(target ≤ {ELLIPSES_MAX_PER_1K:g})"
            )
        if self.dashes_per_1k > DASHES_MAX_PER_1K:
            out.append(
                f"em dashes: {self.dashes_per_1k} per 1,000 words (target ≤ {DASHES_MAX_PER_1K:g})"
            )
        for phrase, n in self.stock.items():
            out.append(f"stock phrase /{phrase}/ appears {n} times (target 0)")
        return out

    def to_json(self) -> dict[str, Any]:
        d = asdict(self)
        d.update(
            she_he_pct=self.she_he_pct,
            ellipses_per_1k=self.ellipses_per_1k,
            dashes_per_1k=self.dashes_per_1k,
            stock_total=self.stock_total,
        )
        return d

    @classmethod
    def from_json(cls, d: dict[str, Any]) -> StyleMetrics:
        return cls(
            words=int(d.get("words", 0)),
            narration_sentences=int(d.get("narration_sentences", 0)),
            she_he_openers=int(d.get("she_he_openers", 0)),
            ellipses=int(d.get("ellipses", 0)),
            em_dashes=int(d.get("em_dashes", 0)),
            stock=dict(d.get("stock") or {}),
        )


def sentences_to_fix(
    paragraphs: list[tuple[str, str]], metrics: StyleMetrics, *, limit: int = 30
) -> list[str]:
    """Concrete sentences behind each missed target, as ``[id] sentence``.

    Giving the polish model the exact sentences works better than giving it
    only the numbers: a small model otherwise returns the text unchanged.
    """
    want_she_he = metrics.she_he_pct > SHE_HE_MAX_PCT
    want_ellipses = metrics.ellipses_per_1k > ELLIPSES_MAX_PER_1K
    want_dashes = metrics.dashes_per_1k > DASHES_MAX_PER_1K
    out: list[str] = []
    for pid, text in paragraphs:
        narration = _QUOTED.sub(" ", text)
        for sentence in _SENTENCE_SPLIT.split(narration):
            s = " ".join(sentence.split())
            if len(s.split()) <= 2:
                continue
            reasons = []
            if want_she_he and _SHE_HE_OPENER.match(s):
                reasons.append("She/He opener")
            if want_ellipses and ("\u2026" in s or "..." in s):
                reasons.append("ellipsis in narration")
            if want_dashes and "\u2014" in s:
                reasons.append("em dash")
            if any(re.search(p, s, re.IGNORECASE) for p in STOCK_PHRASES):
                reasons.append("stock phrase")
            if reasons:
                out.append(f"[{pid}] ({', '.join(reasons)}) {s}")
            if len(out) >= limit:
                return out
    return out


def style_metrics(paragraphs: list[str]) -> StyleMetrics:
    m = StyleMetrics()
    for text in paragraphs:
        m.words += len(text.split())
        m.ellipses += text.count("\u2026") + text.count("...")
        m.em_dashes += text.count("\u2014")
        narration = _QUOTED.sub(" ", text)
        for sentence in _SENTENCE_SPLIT.split(narration):
            if len(sentence.split()) <= 2:
                continue
            m.narration_sentences += 1
            if _SHE_HE_OPENER.match(sentence):
                m.she_he_openers += 1
        for phrase in STOCK_PHRASES:
            n = len(re.findall(phrase, text, re.IGNORECASE))
            if n:
                m.stock[phrase] = m.stock.get(phrase, 0) + n
    return m


@dataclass(slots=True)
class QaIssue:
    check: str
    paragraph_id: str
    detail: str

    def to_json(self) -> dict[str, str]:
        return {"check": self.check, "paragraph_id": self.paragraph_id, "detail": self.detail}


def hard_checks(
    *,
    source: list[tuple[str, str]],
    target: list[tuple[str, str]],
    source_language: str,
    allowed_words: set[str] | None = None,
) -> list[QaIssue]:
    """Checks on paragraph-aligned ``(paragraph_id, text)`` pairs.

    ``allowed_words`` are words that may keep source letters (names the
    glossary keeps in the original, e.g. "Elżka").
    """
    issues: list[QaIssue] = []
    letters = SOURCE_LETTERS.get(source_language, "")
    letter_re = re.compile(f"[{re.escape(letters)}]") if letters else None
    allowed = {w.lower() for w in (allowed_words or set())}
    source_by_id = dict(source)

    for pid, text in target:
        if letter_re is not None:
            bad = sorted(
                {
                    w.strip(".,;:!?\"'()[]*\u2018\u2019\u201c\u201d\u2014\u2026")
                    for w in text.split()
                    if letter_re.search(w)
                }
            )
            bad = [w for w in bad if w and w.lower() not in allowed]
            if bad:
                issues.append(
                    QaIssue("source_letters", pid, "Source-language words left: " + ", ".join(bad))
                )
        if re.match(r"^\s*[\u2013\u2014-]\s", text):
            issues.append(
                QaIssue(
                    "dialogue_dash", pid, "Paragraph starts with a dash; dialogue should be quoted."
                )
            )
        if re.search(r"\\[!.*_#\[\]()-]", text):
            issues.append(QaIssue("escape_backslash", pid, "Markdown escape backslash left in."))
        src = source_by_id.get(pid, "")
        for pat in PLACEHOLDER_PATTERNS:
            want = len(re.findall(pat, src))
            got = len(re.findall(pat, text))
            if want != got:
                issues.append(
                    QaIssue(
                        "placeholder",
                        pid,
                        f"Author placeholder /{pat}/ appears {want} times in the source, {got} times here.",
                    )
                )
    return issues
