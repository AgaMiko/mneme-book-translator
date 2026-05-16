"""Prompt template for the speaker-identification step (Pass 1).

Paired with ``../models/identify_speakers_model.py``.

What this prompt is for
-----------------------
Pass 1 of the voice pipeline. One LLM call per manuscript window. Its
single job: list which glossary characters have at least one quoted
speaking line in the window, with verbatim evidence per claim.

Output is a closed-set assignment (every speaker comes from the
glossary character list passed in) plus a small notepad for
cross-window state. Pass 2 (voice extraction) consumes the speaker
map; later, translation does too.

This prompt is intentionally narrow. Voice profiling, translation,
and new-character discovery are explicitly NOT in scope here.
"""

PROMPT = """\
You are running the first pass of a translator's reference pipeline \
for a {source_language} fiction manuscript. Your single job in this \
pass: identify which characters from the glossary list below have at \
least one **quoted speaking line** in the window of source text \
shown.

You are NOT building voice profiles, NOT translating, NOT discovering \
new characters. Voice profiling runs in a later pass and uses your \
output as input. Translation runs later still.

Keep every string field short and direct. Rambling JSON gets \
truncated by the API and breaks the run.

## Two non-negotiables

The system checks both. Entries that violate them are dropped.

**(1) Every speaker must include ``glossary_entry_id`` and the \
matching ``canonical_name``, both copied verbatim from the list \
below.** The system cross-checks them; if you put one character's \
ID with another character's name, the entry is dropped.

**(2) Every speaker must include ``quoted_evidence``: 5-15 words \
copied verbatim from this window's source text — a phrase from \
inside the character's quoted line.** The system checks that the \
phrase appears in the window text; entries whose evidence isn't \
found are dropped.

If neither condition can be satisfied for a character you suspect \
might be speaking, do not include them in ``speakers``. Use the \
notepad.

## One entry per character per window

List each glossary character **at most once** in ``speakers`` for this \
window. If they have several quoted lines, pick the single best \
``quoted_evidence`` phrase (the clearest attribution). Do not emit \
duplicate rows for the same ``glossary_entry_id``.

## What counts as speaking

Include a character only when this window contains a line you can \
attribute to them through quoted direct speech ("…" or equivalent \
quotation marks). Quoted lines come with attribution cues:

- A speaking-verb tag near the line ("powiedział X", "rzekł Y", \
"szepnęła Z", "krzyknął Z").
- An addressee or scene context that identifies the speaker by \
elimination.
- First-person internal monologue, if the narrative POV is theirs.

Do NOT include:

- Characters merely mentioned in narration without quoted speech.
- Characters described as speaking without quoted content ("they \
spoke of the war").
- Characters whose quoted lines you cannot confidently attribute.
- Characters whose quoted lines you cannot quote a verbatim phrase \
of (the evidence rule above forces this).

## Eligible speakers

Only glossary characters from the list below. Never invent IDs or \
names. If a quoted speaker appears who isn't in the glossary, write \
a notepad note (``unresolved_speaker``) — they may be added to the \
glossary later, but Pass 1 does not create entries.

## Reasoning before structure

Each speaker entry begins with a one-sentence ``reasoning`` field — \
which line in this window is theirs, what attribution cue identifies \
them. Write that *first* (it's the first field on the schema for a \
reason: the model commits to evidence before committing to an ID). \
Then fill ``glossary_entry_id``, ``canonical_name``, and \
``quoted_evidence`` from the line you just identified.

If your reasoning ends with "I'm not sure which character", do not \
emit the speaker entry. Notepad it.

## The notepad

Private working memory across passes. At most one note per pass. \
Categories:

- ``unresolved_speaker`` — someone speaks here but isn't in the \
glossary list.
- ``ambiguous_attribution`` — a quoted line couldn't be confidently \
attributed to any glossary character.
- ``pattern_to_watch`` — a recurring attribution pattern worth \
tracking across windows.

Carry forward what's still useful from the previous pass; drop what's \
resolved. Empty if nothing's worth carrying.

Do NOT use the notepad for:

- Restating things already in the speakers list.
- Tracking overall progress.
- Commentary on manuscript quality.

---

## Pass {window_number} of {total_windows}

### Glossary characters ({n_characters} entries)

{glossary_characters_table}

### Notepad from previous pass

{notepad}

### Source text

{window_text}
"""


def render_glossary_characters_table(characters: list) -> str:
    """Render the glossary character list — closed set of eligible speakers."""
    if not characters:
        return "(empty — no characters in the glossary; Pass 1 cannot proceed)"

    lines = ["glossary_entry_id | canonical_name | variants"]
    for c in characters:
        variants = ", ".join(c.variants) if c.variants else "—"
        lines.append(f"{c.glossary_entry_id} | {c.canonical_name} | {variants}")
    return "\n".join(lines)


def render_notepad(notes: list) -> str:
    if not notes:
        return "(empty)"
    return "\n".join(f"- [{n.category}] {n.content}" for n in notes)
