"""Prompt template for the iterative glossary extraction step.

Paired with ``../models/extract_glossary_model.py``.

Structured output carries the response shape. This text only frames the task,
languages, and behavior that JSON field descriptions cannot replace.
"""

from typing import Any

PROMPT = """\
You are building a translator's glossary for a {source_language} fiction \
manuscript that will be translated into {target_language}. Each pass you read \
one window of text plus the glossary accumulated so far.

Find every surface form an English-only reader would need a stable decision on: \
proper names, invented or world-specific vocabulary, culturally loaded labels, \
and ordinary words used in a specialized in-world sense. Skip generic \
description and vocabulary used in its everyday meaning.

Answer with only what this window adds or changes: genuinely new material, \
new surface forms that belong to existing rows, merges when two rows are the \
same entity, or substantive corrections when new evidence updates how \
something should be read. Leave unchanged material out of your answer.

{first_pass_note}\
## Canonical forms

Prefer the form the manuscript settles on as the usual reference, even when \
the first occurrence was longer (for example a titled introduction vs the \
short name used afterward).

## Deduping

If a spelling, epithet, or nickname in this window clearly belongs with \
something already in the table, attach it there instead of opening a \
duplicate. Read each whole row, not only the main heading.

When two rows are the same entity, merge them and keep the steadier heading \
as the survivor.

## Substantive updates only

Revise an existing row only when this window changes meaning or translation \
strategy; skip cosmetic tweaks.

## English for monolingual readers

The glossary steers English that reads naturally to someone who does not read \
the source language. Descriptive placenames and faction-style labels usually \
carry meaning first: convey image or role in English rather than freezing \
opaque source-language strings, except in the rare cases where the story \
clearly demands that exact surface on the English page.

Running English should normally avoid source-language-specific letters; keep \
diacritics and exact spellings in the source-side forms the table already uses \
for reference.

When the source register is archaic, folkloric, or slangy, let compatible \
texture show in English where it fits the narrative voice.

Titles of songs, chapters, and in-world works should read like credible English \
titles with the same emotional cue, not word heaps only insiders decode.

When related word families appear (shared roots across roles or processes), \
line English glosses up so the kinship stays visible, and tighten earlier rows \
if a later window reveals a link you missed.

When several English directions are all defensible, pick one default you would \
ship, park the other strong options alongside it, and say briefly how they \
differ for whoever reviews.

## Working notes

The block labeled for your next pass is private working memory — not the \
glossary, not a message to the user. Use it for concrete, forward-looking \
reminders (spellings to watch, ambiguity to resolve, threads to reconcile \
before the run ends). If nothing deserves to survive, leave it empty. Carry \
forward only what still matters, edited short; drop solved threads.

Do not use it to restate rows already in the table, to log progress, or to \
comment on the novel's quality.

---

## Pass {window_number} of {total_windows}

### Current glossary ({n_entries} entries)

{glossary_table}

### Notepad from previous pass

{notepad}

### Source text

{window_text}
"""


FIRST_PASS_NOTE = """\
This is the first window: the table is empty, so choose generous canonical \
anchors; later passes can refine. Your scratch block for the next pass starts \
empty — jot anything pass two should remember.

Bias toward English an English-only reader can parse; reserve untranslated \
source surface on the English page only for the rare cases where the story \
truly demands it.

"""


def render_glossary_table(entries: list[Any]) -> str:
    """Render compact glossary entries as a tabular block for the prompt.

    Format keeps the model's attention on the fields that matter for
    dedup decisions (canonical form + variants + type) without burning
    tokens on fully-formatted reasoning.
    """
    if not entries:
        return "(empty — no entries yet)"

    lines = ["id | canonical_form | variants | type | suggestion | alts | meaning"]
    for e in entries:
        variants = ", ".join(e.variants) if e.variants else "—"
        alts = getattr(e, "alternative_targets", None) or []
        alts_cell = ", ".join(alts[:4]) if alts else "—"
        if len(alts_cell) > 72:
            alts_cell = alts_cell[:69] + "…"
        lines.append(
            f"{e.id} | {e.canonical_form} | {variants} | {e.term_type} | "
            f"{e.translation_suggestion} | {alts_cell} | {e.meaning}"
        )
    return "\n".join(lines)


def render_notepad(notes: list[str]) -> str:
    """Render the notepad from the previous pass (one bullet per line)."""
    if not notes:
        return "(empty)"
    return "\n".join(f"- {line}" for line in notes)
