"""Prompt template for the glossary review step.

Paired with ``../models/review_glossary_model.py``.

The rules below describe the author's own past decisions on a fully
reviewed glossary (178 accepted, 59 removed): which kinds of terms they
keep and which they remove. Frequency is deliberately not a rule: many
accepted terms appear once or not at all.
"""

from __future__ import annotations

from dataclasses import dataclass

PROMPT = """\
You are reviewing a translator's glossary for a {source_language} novel that \
will be translated into {target_language}. An earlier pass proposed the terms \
below. Decide each pending term the way this author would: accept it, reject \
it, or merge it into another term. The author will check your decisions later.

## What the glossary is for

A term belongs in the glossary when the translation needs one fixed decision \
for it, so it reads the same every time it appears.

## Accept

- Names of people, places, organizations, factions and creatures.
- Invented words and coinages.
- Titles of in-world books, songs and works, and quoted sayings, prayers or \
mottos, even when they appear only once.
- Words used in a special in-world sense, and named concepts where several \
English renderings would be possible and consistency matters.

## Reject

- Everyday words whose English is simply the dictionary word and needs no \
decision (miecz → sword, sztylet → dagger, medyk → medic, alchemik → \
alchemist, wzrok → sight, mrok → darkness, golenie → shaving).
- Descriptive phrases and sensory descriptions that are not names \
(smak rdzy i miodu, swąd spalenizny, drewniane miecze).
- Ordinary objects, foods and actions.
- Generic ranks and roles used as common nouns (Generał).

## Merge

Merge only when two rows refer to the same person, place or thing: another \
name, an epithet, a short form, or the same term in another grammatical \
form. Similar meaning is not enough; two different things stay separate. \
Prefer merging into an accepted term. Never merge into a removed term: if a \
pending term is the same as a removed one, reject it.

## Use the author's past decisions

The tables of accepted and removed terms show what this author keeps and \
removes. When a pending term is like one of them, decide the same way. The \
author is not always consistent; follow the usual pattern.

## Confidence

The author checks low-confidence decisions first, so use low whenever a \
careful reader could decide the other way. That includes: titles of \
in-world books (the author kept most and removed some); named abilities, \
techniques and symbols that read like descriptions; everyday words that \
might carry a special in-world sense; and merges between a name and an \
epithet. Expect about one decision in four to be low.

## Also check

- Variants that do not belong to the term (another character's nickname, an \
unrelated word): list them in wrong_variants.
- An English target that is clearly wrong: give the better one in \
better_target. Leave it null otherwise; the author makes translation choices.

Write the reasoning in plain English, one sentence, for the author to read.

---

## Pending terms to decide ({n_pending})

Each row: id | term | type | variants | proposed English | meaning | \
occurrences in the book, followed by passages where it appears.

{pending_block}

## Accepted terms ({n_accepted})

id | term | type | English | meaning

{accepted_block}

## Terms the author removed ({n_removed})

term | type | proposed English that was removed

{removed_block}
"""


@dataclass(frozen=True, slots=True)
class PromptTerm:
    """One row of a prompt table."""

    id: str
    canonical_form: str
    term_type: str
    target: str
    meaning: str
    variants: tuple[str, ...] = ()
    occurrences: int = 0
    passages: tuple[str, ...] = ()


def _short(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def render_pending(terms: list[PromptTerm]) -> str:
    blocks = []
    for t in terms:
        variants = ", ".join(t.variants) or "—"
        lines = [
            f"{t.id} | {t.canonical_form} | {t.term_type} | {variants} | {t.target} | "
            f"{_short(t.meaning, 240)} | {t.occurrences}"
        ]
        lines += [f"    > {p}" for p in t.passages] or ["    > (no passage found)"]
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def render_accepted(terms: list[PromptTerm]) -> str:
    if not terms:
        return "(none yet)"
    return "\n".join(
        f"{t.id} | {t.canonical_form} | {t.term_type} | {t.target} | {_short(t.meaning, 90)}"
        for t in terms
    )


def render_removed(terms: list[PromptTerm]) -> str:
    if not terms:
        return "(none yet)"
    return "\n".join(f"{t.canonical_form} | {t.term_type} | {t.target}" for t in terms)
