"""Prompt template for the speaker-attribution step (Pass 1).

Paired with ``../models/identify_speakers_model.py``.

What this prompt is for
-----------------------
Pass 1 of the voice pipeline. One LLM call per chunk of a chapter (about
2,500 words). The chunk is shown in full; the paragraphs that may hold
dialogue are numbered. The model says, for each numbered line, what kind
of line it is, who says it and to whom.

Voice profiling, translation and new-character discovery are not in
scope here.
"""

from typing import Any

PROMPT = """\
You are attributing dialogue in a {source_language} fiction manuscript. \
The text below is one part of a chapter. Paragraphs that may hold \
dialogue are numbered L1, L2, … For every numbered line, say what kind \
of line it is, who says it, and who it is said to.

You are not building voice profiles and not translating. A later step \
uses your answers to collect each character's lines.

## Rules

1. **Return one entry for every numbered line, in order.** Do not skip \
lines and do not invent line numbers.
2. **Speakers and addressees come only from the character list.** Give \
the code (C3) and the canonical name, both copied from the list. The \
system checks that they match and drops the speaker if they don't. If \
the speaker is not in the list, or you cannot tell who it is, leave \
speaker_code and speaker_name null.
3. **kind**
   - speech: said aloud.
   - thought: inner speech, or a line the character remembers or imagines.
   - not_dialogue: a title, sign, letter or document being read, a quoted \
word inside narration, or narration that only looks like dialogue. No \
speaker.
4. **confidence**
   - clear: a speech tag (a verb of saying with a name) or the narration \
in or next to the line names the speaker.
   - inferred: no tag; you worked it out from turn order, the addressee or \
the scene.
5. **mixed**: true only when two different characters speak inside one \
numbered line.

## How dialogue is written here

Dialogue may be set off by dashes (a line starts with a dash, and \
narration inside it is set off by more dashes) or by quotation marks \
(narration sits around the quoted speech). The narration part usually \
names the speaker. In a two-person exchange without tags, speakers \
alternate; check that against the content before relying on it. A \
pronoun, or a verb form that shows gender, narrows the speaker. Names \
in the line itself are usually the addressee, not the speaker.

The addressee is the character the line is said to. Leave it null for \
a group, for no one in particular, or when unclear.

## Output

Write `scene` first: one or two sentences on who is present and who \
talks to whom. Then the `lines` list. Keep everything short; no \
explanations per line.

---

## Characters ({n_characters})

{characters_table}

## Before this part (context only, already attributed)

{context}

## Text ({chapter_label}, part {chunk_number} of {total_chunks})

{chunk_text}
"""


def render_characters_table(characters: list[Any]) -> str:
    if not characters:
        return "(empty)"
    rows = ["code | canonical_name | variants"]
    for c in characters:
        variants = ", ".join(c.variants) if c.variants else "—"
        rows.append(f"{c.code} | {c.canonical_name} | {variants}")
    return "\n".join(rows)
