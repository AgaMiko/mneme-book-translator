"""Prompt template for the iterative voice-extraction step.

Paired with ``../models/extract_voices_model.py``.

What this prompt is for
-----------------------
Voice extraction is the FIRST of three chains. It produces:

- source_voice_observation per character (target language, names what
  the character is REALLY doing in the source language)
- target_voice_strategy per character (target language, names how to
  render that voice in target-language equivalents)
- a pool of candidate passages per character (capped at 8)

It does NOT translate. Translation runs as a separate later chain
with the full accepted glossary in context.
"""

PROMPT = """\
You are building a translator's reference for character voices in a \
{source_language} fiction manuscript that will be translated into \
{target_language}. Your job, across many passes, is to capture how \
each speaking character REALLY sounds in {source_language}, design \
how that voice should be rendered in {target_language}, and flag \
representative passages of their dialogue worth keeping for \
translation later.

You see one window of text per pass and the voice profiles built so \
far. You return a *delta* — operations that create profiles, extend \
their voice fields, add candidate passages, or replace weaker \
candidates with stronger ones. You do not regenerate state.

This pass produces voice metadata only. **Do not translate anything.** \
Translation runs as a separate later step with the full accepted \
glossary in context. Your work here is in {target_language} for both \
voice fields, and in {source_language} for the candidate passage \
source texts (verbatim from source).

Keep every string field short and direct. Rambling JSON gets \
truncated by the API and breaks the run.

## Two non-negotiables

The system checks both. Operations that violate them are dropped.

**(1) The two voice fields are written in {target_language}, never \
{source_language}.** They DESCRIBE features of {source_language} \
dialogue, but they're written *in* {target_language}.

**(2) Every operation includes both an ID and the matching \
``canonical_name`` exactly as it appears in the lists below.** The \
system cross-checks them. If you put one character's voice traits \
under another character's ID, the operation is dropped.

{first_pass_note}\
## The two voice fields, and what each one does

A character's voice is captured in two fields. They have different \
jobs and the model should think about them separately.

### source_voice_observation — what the character is REALLY doing

This field names the specific linguistic features the source-language \
author is using to mark this character's voice. It is OBSERVATION, \
not description. Be concrete:

- Does the character use particular emphatic particles, modal markers, \
or sentence-final tags? Name them.
- Does the source text use deliberate non-standard spelling to mark \
the character's pronunciation? Name examples.
- Does the character use lexical choices that signal class, era, or \
region? (Archaic vocabulary, peasant words, courtly forms, military \
jargon.) Name the specific words or word-types.
- Does the character use particular address forms? (Formal vs. \
informal pronouns, titles, diminutives.) Name them.
- Does the register shift in different situations? Name the shifts \
and what triggers them.

DO write things like:
- "Uses the -że emphatic particle (Łapaćże, lepiejże, raczejże). \
Archaic-rural vocabulary (chłop, chałupa, dziad, dziewka — peasant \
register, not modern Polish). Source author renders pronunciation \
through deliberate misspellings (tile for tyle, dzjewko for dziewko, \
ogjer for ogier). Uses formal pan address to masters even while \
delivering folk wisdom."

DON'T write things like:
- "Speaks rurally and informally." (Vague — names no markers.)
- "Old-fashioned, colloquial." (Adjectives, no observation.)
- "Sounds like a peasant." (Stereotype, not observation.)

The test: could a translator who hasn't read the source identify the \
specific markers to track? If not, the observation isn't specific \
enough.

### target_voice_strategy — how to render in {target_language}

This field names how the translator should construct an equivalent \
voice in {target_language}. It is a CRAFT DECISION about which \
target-language register to use, with specific markers named, and \
specific things to avoid.

Be concrete:

- What target-language register is the equivalent? Name it specifically \
(not "rural" but e.g. "Hardy/Eliot 19th-century English country-servant").
- What target-language markers should the translator use? Name actual \
words, contractions, grammatical patterns. (For English country-servant: \
"ye, afore, reckon, mind ye, would ye for emphatic imperatives, \
occasional dropped articles.")
- How should source-language address forms map? (Polish pan/pani → \
sir/madam? "my lord"? Just the name?)
- What should the translator AVOID? (Anachronisms, wrong-region \
accents, stagey eye-dialect, modern slang, words that would feel \
out of place in this register.)
- One marker per sentence is usually enough — pile too high and the \
voice reads as parody. Note this explicitly when relevant.

DO write things like:
- "Render in archaic-rural English of the 19th-century country-servant \
type. Markers to use: 'ye' for informal you, 'afore' for before, \
'reckon' for think, 'mind ye' for emphatic imperatives, 'would ye' as \
the equivalent of the -że particle, 'tis for it is, occasional dropped \
articles. Polish pan address → 'sir' (preserve the master/servant \
register). Avoid: y'all, ain't (too American), heavy eye-dialect like \
'tha'/'thee' (too theatrical), modern slang. One marker per sentence; \
don't pile up."

DON'T write things like:
- "Translate naturally with rural feel." (Vague.)
- "Use folksy English." (No markers named.)
- "Make him sound uneducated." (Patronizing, no craft direction.)

The test: could a translator who hasn't read the source produce \
consistent, specific output from this strategy alone? If not, the \
strategy isn't specific enough.

The author will review your strategies. Your job is a strong starting \
point, not a final answer. The author may refine markers, change the \
target register entirely, or add avoidances based on their own ear. \
Write strategies that give them something concrete to react to.

## How the two fields relate

Observation describes what's happening. Strategy decides what to do \
about it. They should be coherent — strategy markers should map to \
observation features. If observation names "the -że emphatic \
particle," strategy should name a target-language equivalent ("would \
ye" or "mind ye"). If observation names "deliberate misspellings as \
eye-dialect," strategy should decide whether to mirror that in target \
(usually no — most modern target-language readers find heavy \
eye-dialect distracting; the equivalent register effect is achieved \
through vocabulary choices instead).

## When to use which operation

- **Create a new profile** when a character speaks for the first time \
AND ``has_voice_profile`` is False. Includes BOTH voice fields and \
one or more starting candidate passages.

- **Extend an existing profile** when this window adds NEW evidence \
that meaningfully changes observation, strategy, or both. Provide \
only the field(s) actually changing; ``None`` means "no change." \
Most passes will not extend — observation should stabilize after a \
few windows of evidence, and strategy should change less often than \
observation.

- **Add a candidate** when this window contains a passage worth \
keeping in the pool, AND the pool has fewer than 8 entries, AND the \
passage shows something the existing candidates don't.

- **Replace a candidate** when the pool is full (8 entries) AND this \
window contains a passage that's meaningfully better than one of \
the existing candidates.

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

## Who can have a profile

Only characters in the **glossary character list** below. Never \
invent IDs. If a speaker appears who isn't in the glossary, do not \
create a profile — write a notepad note instead.

## Candidate passages

A candidate passage is a representative moment of a character's voice \
worth keeping for translation later. Selection (a separate later \
step) will pick the final 1-4 passages from this pool.

A good candidate:

- **Shows voice fully** — 3-5 sentences where you can hear the \
character.
- **Is self-contained** — makes sense without unstated context.
- **Has voice-distinguishing features** — register, address \
conventions, the specific markers named in the observation.
- **Is verbatim from the source** — do not paraphrase.

The ``why_representative`` field is critical. Selection later uses it \
to compare candidates. Be specific:

- Good: "shows the diminutive shift toward Mira"
- Good: "rare moment of dropped facade with Stein"
- Bad: "good passage" / "shows his voice"

When deciding whether to add or replace a candidate, ask: **does this \
passage show something the existing pool doesn't?** Look at the \
``candidate_reasons`` list in the compact profile. If your new \
passage duplicates a reason already there, do not add it.

If a window shows the character at the same display the pool already \
captures, do nothing. Most windows will not produce candidate \
operations.

## The notepad

Private working memory across passes. Use for:

- Speakers in this window not in the glossary character list \
(``unresolved_question``).
- Voice drift across windows worth checking (``consistency_concern``).
- Patterns to confirm later (``pattern_to_watch``).

Capped at 1 note per pass. Carry forward what's still useful; drop \
what's resolved. Return empty if nothing's worth carrying.

Do NOT use the notepad for:
- Restating things already in voice profiles.
- Tracking overall progress.
- Commentary on manuscript quality.

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
character with a glossary entry needs a fresh profile, including \
source_voice_observation, target_voice_strategy, AND one or more \
starting candidate passages. Establish from the dialogue you can see; \
later passes will refine. The notepad starts empty too.

"""


def render_voice_profiles_table(profiles: list) -> str:
    """Render compact voice profiles for the prompt.

    Each profile gets a multi-line block with both voice fields, the
    candidate pool size, and the candidate reasons (not the passage
    texts themselves — those are too long for prompt context).
    """
    if not profiles:
        return "(empty — no voice profiles yet)"

    blocks: list[str] = []
    for p in profiles:
        reasons_block = (
            "\n".join(f"    - {r}" for r in p.candidate_reasons)
            if p.candidate_reasons
            else "    (none)"
        )
        blocks.append(
            f"- id: {p.id}\n"
            f"  glossary_entry_id: {p.glossary_entry_id}\n"
            f"  canonical_name: {p.canonical_name}\n"
            f"  last_observed_window: {p.last_observed_window}\n"
            f"  source_voice_observation: {p.source_voice_observation}\n"
            f"  target_voice_strategy: {p.target_voice_strategy}\n"
            f"  candidate_count: {p.candidate_count} / 8\n"
            f"  candidate_reasons:\n{reasons_block}"
        )
    return "\n\n".join(blocks)


def render_glossary_characters_table(characters: list) -> str:
    """Render the glossary character list — all available targets for
    voice operations. canonical_name copied verbatim into the
    cross-checked ``canonical_name`` field on every operation."""
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
    if not notes:
        return "(empty)"
    return "\n".join(f"- [{n.category}] {n.content}" for n in notes)
