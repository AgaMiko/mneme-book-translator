"""Prompt template for the iterative voice-extraction step.

Paired with ``../models/extract_voices_model.py``.

The schema (``VoiceUpdate``) owns shape, types, and field-level
constraints. This template carries:

- task framing (what voice extraction is for and how iteration works)
- the "constraints not content" rule (the core behavioral instruction)
- reference passage selection and translation criteria
- the notepad contract
- the conditional first-pass note
"""

PROMPT = """\
You are building a translator's reference for character voices in a \
{source_language} fiction manuscript that will be translated into \
{target_language}. Your job, across many passes, is to capture how each \
speaking character sounds, AND to produce a representative reference \
translation passage per character — so the translator can preserve voice \
consistency across the whole book and has a known-good calibration \
sample for each speaker.

You see one window of text per pass and the voice profiles built so far. \
You return a *delta* — operations that create profiles, extend their \
summaries, or replace their reference passages with better ones. You do \
not regenerate state.

Keep every string field short and direct. Rambling JSON gets truncated \
by the API and breaks the run.

{first_pass_note}\
## The core rule: describe voice as constraint, not content

Your job is to describe *how* a character sounds in a way the translator \
can use to shape their work — not to provide example phrases for the \
translator to copy. Models given lists of "this character says X" \
over-apply those phrases, salting the translation with words the source \
text does not actually contain in each scene.

So:

- DO: "Speaks in clipped urgent military commands, softening to a \
conspiratorial tone when discussing illness. Uses diminutives toward \
Mira in moments of intimacy or condescension."
- DON'T: "Says 'Spokojnie spokojnie!' as a calming phrase, calls Mira \
'kwiatuszku'."

The first describes the voice. The second tells the translator what to \
write — and the translator will write it whether the source contains it \
or not. The source text is the only place vocabulary lives; your \
profile carries the constraints that shape how that vocabulary is \
translated.

This rule applies to ``voice_summary`` and to your ``reasoning`` notes \
across all operations.

## What counts as dialogue evidence

A character earns voice operations only when this window shows them \
*speaking*:

- Quoted direct speech ("...") attributable to the character.
- Indirect speech tagged with a speaking verb, only if the indirect \
content reveals voice characteristics.
- First-person internal monologue, if the narrative POV is theirs.

NOT evidence:
- Description of speech without quoted content ("she spoke gently").
- Description of the character that doesn't reveal voice.
- A character being mentioned but not speaking.

A profile for a character who hasn't actually spoken is worse than no \
profile.

## Who can have a profile

Only characters in the **glossary character list** provided below. The \
``glossary_entry_id`` on every operation must come from that list — \
never invent IDs.

If you observe a speaker in this window who is NOT in the glossary list, \
do not create a profile. Instead, write a note in the notepad describing \
the missing character. The glossary will catch up on a later run; voice \
profile creation can wait.

## When to create vs. extend vs. replace the reference

- **Create** a new profile when a character speaks for the first time in \
the manuscript AND has no existing profile (``has_voice_profile`` is \
False on the glossary character list). The new profile includes BOTH \
voice_summary AND a reference passage drawn from this window.

- **Extend** an existing profile when this window adds NEW evidence \
that meaningfully changes how the voice should be described. Replace \
the voice_summary entirely with one that integrates the new observation. \
If you cannot point to specific new evidence, do NOT extend — leave the \
existing summary alone. Most passes will not extend.

- **Replace the reference passage** when this window contains a passage \
that is *meaningfully better* than the stored one — for example, the \
stored passage was a single short line and this window has a fuller \
exchange that shows register and address strategy together. Cosmetic \
improvement is not enough. If the stored passage is adequate, leave it \
alone. Most passes will not replace anything.

## Reference passage: selection criteria

For each new profile (and occasionally for replacements), pick 3-4 \
consecutive sentences of this character's dialogue from this window's \
source text. Verbatim — do not paraphrase or edit the source.

A good reference passage:

- **Shows voice fully** — three or four sentences where you can hear \
the character. Not one short line.
- **Is self-contained** — makes sense without unstated context.
- **Is representative** — not the character's most extreme moment. If \
the character is normally clipped and this is one sobbing scene, that \
scene is NOT the reference. Pick what shows them at their typical mode.
- **Includes voice-distinguishing features** — a diminutive, a register \
shift, a recurring construction the translator must preserve.

## Reference passage: translation

Translate those exact sentences into {target_language}. The translation \
should:

- Preserve the voice characteristics described in the voice_summary.
- Not insert phrases that aren't in the source. (If the source doesn't \
say "easy now," your translation doesn't say "easy now.")
The translation should read as if it were originally written in {target_language}.
A native {target_language} reader should not be able to tell from your translation that the source was {source_language} — no calqued idioms, no Polish sentence rhythms, no Latinate word choices where the English author would use Anglo-Saxon.

This translation will be reviewed by the author. The author's accepted \
or edited version becomes the canonical calibration sample for the rest \
of the translation pipeline. Do your best work here.

## The notepad

The notepad is your private working memory across passes. Use it for:

- Speakers in this window who aren't in the glossary character list \
(``unresolved_question``).
- Characters whose voice may have drifted across windows in a way \
worth checking (``consistency_concern``).
- Patterns to confirm in later windows (``pattern_to_watch``).

The notepad is **capped at 1 note per pass**. Each pass receives the \
previous note (if any) and chooses what to write for the next one. \
Carry forward what's still useful; drop what's been resolved. Return \
an empty notepad if nothing is worth carrying forward.

Do NOT use the notepad to:
- Restate things already in the voice profiles.
- Track overall progress.
- Comment on the manuscript's quality.

---

## Pass {window_number} of {total_windows}

### Glossary characters ({n_characters} entries)

{glossary_characters_table}

### Current voice profiles ({n_profiles} profiles)

{voice_profiles_table}

### Notepad from previous pass

{notepad}

### Source text

{window_text}
"""


FIRST_PASS_NOTE = """\
This is the first window. No voice profiles exist yet — every speaking \
character with a glossary entry needs a fresh profile, including a \
voice_summary AND a reference passage with translation. Establish from \
the dialogue you can see; later passes will refine. The notepad starts \
empty too; write down anything worth carrying forward to pass 2.

"""


def render_voice_profiles_table(profiles: list) -> str:
    """Render compact voice profiles for the prompt.

    Each profile gets two lines: a header with id / name / last window,
    then the voice_summary indented, then the reference_passage_source
    indented. The table format we used for glossary doesn't fit voice
    because the summary and passage are too long for a single row —
    a multi-line block reads better and uses less horizontal space.
    """
    if not profiles:
        return "(empty — no voice profiles yet)"

    blocks: list[str] = []
    for p in profiles:
        blocks.append(
            f"- id: {p.id}\n"
            f"  glossary_entry_id: {p.glossary_entry_id}\n"
            f"  canonical_name: {p.canonical_name}\n"
            f"  last_observed_window: {p.last_observed_window}\n"
            f"  voice_summary: {p.voice_summary}\n"
            f"  reference_passage_source: {p.reference_passage_source}"
        )
    return "\n\n".join(blocks)


def render_glossary_characters_table(characters: list) -> str:
    """Render the glossary character list — every character available
    as a target for voice operations.

    Format: glossary_entry_id | canonical_name | variants | has_voice_profile

    The ``has_voice_profile`` flag is critical: it tells the model
    whether to expect a "create" operation (False) or an "extend / replace
    reference" operation (True) for any character whose dialogue appears.
    """
    if not characters:
        return "(empty — no characters in the glossary; voice extraction cannot proceed)"

    lines = ["glossary_entry_id | canonical_name | variants | has_voice_profile"]
    for c in characters:
        variants = ", ".join(c.variants) if c.variants else "—"
        lines.append(
            f"{c.glossary_entry_id} | {c.canonical_name} | {variants} | "
            f"{c.has_voice_profile}"
        )
    return "\n".join(lines)


def render_notepad(notes: list) -> str:
    """Render the previous pass's notepad."""
    if not notes:
        return "(empty)"
    return "\n".join(f"- [{n.category}] {n.content}" for n in notes)
