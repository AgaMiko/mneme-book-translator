"""Prompt template for building voice profiles from all of a character's lines.

Paired with ``../models/build_voice_profile_model.py``.

The guidance on the two voice fields is carried over from the window
prompt (``extract_voices_prompt.py``, removed in the voice-redesign
cleanup); what changes is the input: every line of the character at
once, with chapter and addressee, instead of one window at a time.
"""

PROMPT = """\
You are building a translator's reference for character voices in a \
{source_language} fiction manuscript that will be translated into \
{target_language}. Below are ALL the spoken lines of {who} in the \
book, in book order. Each line is the full paragraph, so the \
narration around the speech (who it is said to, how it is said) is \
there too.

For each character, write how they REALLY sound in {source_language}, \
how that voice should be rendered in {target_language}, and pick \
reference passages for the translator.

**Do not translate anything.** Both voice fields and every feature are \
written in {target_language}; quoted markers stay in {source_language}.

## Read the whole book's lines first

You see every line, so describe the voice across the book, not one \
scene. A feature that shows up once is a moment, not a voice; prefer \
features you can show in several lines, in different chapters. If the \
voice changes over the book, or with particular people, say so in \
register_shifts.

## features — the evidence

List the concrete features of how this character speaks. Each one cites \
the line numbers that show it (one to five). **Every feature must be \
visible in the lines you cite**; the system drops line numbers that \
are not this character's. Do not project features from role, \
profession, class or what the character "should" sound like. A teacher \
who speaks with a village accent has a village voice.

Look for:
- emphatic particles, modal markers, sentence-final tags;
- deliberate non-standard spelling (eye-dialect) and non-standard \
grammar (a foreigner's broken cases, a child's syntax, dropped \
articles, tense confusion);
- signature speech patterns: tic phrases, hesitation markers, \
stutters, fragments, run-ons, repetitions;
- code-switching to other languages and what it signals;
- stable sociolect by class, era, region, profession — both the \
lexicon AND the cognitive/syntactic tendency (the scientist hedges, \
the peasant is concrete, the soldier terse, the courtier indirect);
- address forms (formal/informal pronouns, titles, diminutives);
- register shifts with particular people or situations.

Specific beats abstract: a marker named and quoted from the lines \
beats "rural and informal".

## Thoughts

{thoughts_note}

## source_voice_observation — what the character is REALLY doing

The observation summarises the features for a translator who will read \
it before every scene the character speaks in. Name the markers \
concretely; no adjectives without markers ("speaks rurally"), no \
stereotypes ("sounds like a peasant"). Keep it to what a translator \
needs; the line evidence stays in features.

## target_voice_strategy — translation guidance

This is translation guidance, not a generation prompt. The translator \
has the source line in front of them and needs one answer, repeated \
for every line of this character: *"when I see X in source, what is my \
move in target, and what is the obvious wrong move?"*

For each observed feature, write a **when-you-see-X-do-Y** rule with a \
move:
- **MIRROR** (carry directly): non-standard grammar, verbal tics, \
signature phrases, stutters, fragmentation, repetition, \
code-switching. The realisation may shift (case or agreement errors in \
the source → article or preposition errors in English) but the \
brokenness carries over. \
Keep foreign phrases verbatim and unglossed unless the original glossed.
- **RECAST** (substitute a {target_language} equivalent): \
source-specific particles and honorifics, lexical archaism, regional \
vocabulary. Stable sociolect splits: recast the lexicon, mirror the \
cognitive/syntactic tendency.
- **WATCH** (name a trap): anachronisms, wrong-region accents, stagey \
foreign accents, inline glosses, softening a sharp tone, expanding \
clipped imperatives, modern slang.

Eye-dialect is a per-character call: mirror with sparse equivalent \
eye-dialect for in-language regional/class accents (the Hardy/Eliot/ \
Twain/Scott tradition, one or two marks per sentence); recast for a \
foreign speaker's accent (use grammar errors, not phonetic \
stage-accents). Name the {target_language} register to reach for, \
specifically. Give address-form mappings the translator applies every \
time (a title or formal pronoun → 'sir'? the name?).

The test: could a translator who has not read the source produce \
consistent, specific output from this strategy alone? The author will \
review and refine it; give them something concrete to react to.

## reference_passages

Pick the number of passages given in each character's heading. Each passage is a range of this character's lines \
from ONE scene (first_line to last_line; the same number for a single \
line). The system includes everything between them, so other \
speakers' replies come along; keep a range to a short exchange. Pick \
passages that show the voice fully and differ from each other: \
different addressees, moods or registers. Say in `why` what each one \
shows.

## Output

One profile per character below, in the order given, with the \
character's code and canonical name copied from its heading. Keep every \
string direct; no preamble.

---

{characters_section}
"""

THOUGHTS_NOTE_NONE = "No thoughts are listed; describe the spoken voice only."

THOUGHTS_NOTE = """\
Some characters also have **thoughts** (inner speech, remembered lines), \
listed separately after their spoken lines. Describe the voice from the \
spoken lines. Use the thoughts only to note, in one sentence of the \
observation, where the inner voice differs in a way the translator \
should keep. Do not cite thought lines as evidence for spoken features."""
