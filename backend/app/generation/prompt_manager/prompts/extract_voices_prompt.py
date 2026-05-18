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

from typing import Any

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

{first_pass_note}{speaker_scope_note}{regeneration_note}\
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
- Does the character use deliberate non-standard grammar that the \
author has put there on purpose? (Missing articles or prepositions, \
wrong cases or genders, foreign syntax from a non-native speaker, \
child grammar, broken concord, tense confusion.) Name the specific \
errors and what they mark.
- Does the character have signature speech patterns — a tic phrase, \
a hesitation marker, a stutter, a habit of fragments, a habit of \
run-on, repetitions? Name them.
- Does the character drop phrases from other languages? (French in \
pre-war gentry, Latin in scholarly or medical speech, German in \
interwar military, English or Russian in modern émigré dialogue.) \
Name the language, the kinds of phrases, and what the switching \
signals — education, exile, class, professional jargon, affectation.
- Does the character speak in a stable sociolect — class, era, region, \
or profession as identity? Note BOTH the lexicon (peasant words, \
Latinate vocabulary, military jargon, courtly forms) AND the \
cognitive/syntactic tendency: a scientist hedges and reaches for \
abstraction; a peasant uses concrete verbs and folk syntax; a \
soldier is terse and imperative; a courtier is elaborate and \
indirect.
- Does the character use particular address forms? (Formal vs. \
informal pronouns, titles, diminutives.) Name them.
- Does the register shift in different situations on top of the \
stable sociolect? Name the shifts and what triggers them.

DO write things like:
- "Uses the -że emphatic particle (Łapaćże, lepiejże, raczejże). \
Archaic-rural vocabulary (chłop, chałupa, dziad, dziewka — peasant \
register, not modern Polish). Source author renders pronunciation \
through deliberate misspellings (tile for tyle, dzjewko for dziewko, \
ogjer for ogier). Uses formal pan address to masters even while \
delivering folk wisdom."
- "Drops Polish case endings on nouns (jadę do dom instead of domu), \
substitutes nominative for accusative, occasional Russian lexical \
slips (давай, харашо). Marks her as a Russian-born émigré — the \
errors are systematic and consistent with a Slavic L1 speaker of \
Polish, not random."
- "Repeats 'rozumie pan?' as a verbal tic at the end of nearly every \
assertion, fragments sentences when agitated (verb-only clauses), \
stutters on plosives under stress (k-k-konieczne)."
- "Stable scientific sociolect — hedged assertions ('wydaje się', \
'można przypuszczać'), Latinate vocabulary (akumulacja, sublimacja, \
dyssolucja), long subordinate clauses with passive constructions, \
abstract nouns where lay speakers would use verbs. Drops Latin tags \
from his medical training ('primum non nocere', 'in vivo', 'sine qua \
non') and occasional French phrases ('eh bien', 'tant pis') as \
natural pre-war gentry code-switching, not affectation."

DON'T write things like:
- "Speaks rurally and informally." (Vague — names no markers.)
- "Old-fashioned, colloquial." (Adjectives, no observation.)
- "Sounds like a peasant." (Stereotype, not observation.)
- "Formal academic register; rhetorical questions; philosophical framing." \
(Hallucinated — projected from the character's role as a teacher \
without quoting any dialogue showing it. A teacher who speaks with a \
village accent has a village voice. Read the dialogue, do not \
read the role.)

**Grounding rule.** Every feature you name must be tied to an actual \
quoted or near-quoted phrase from THIS window's dialogue. Do not \
infer features from the character's role, profession, name, social \
position, or what kind of person they "should" sound like. If you \
cannot point at a specific source phrase as evidence, do not name \
the feature — write a notepad note (``unresolved_question`` or \
``pattern_to_watch``) and wait for evidence in a later window.

The test: could a translator who hasn't read the source identify the \
specific markers to track AND find each one in this window's \
dialogue? If not, the observation isn't grounded enough.

### target_voice_strategy — translation guidance for this character

**This field is translation guidance, not a generation prompt.** The \
translator already has the source line in front of them. They do not \
need instructions for writing fresh {target_language} prose. They \
need answers to one question, repeated for every line of this \
character's dialogue: *"when I see X in source, what's my move in \
target — and what's the obvious wrong move I should avoid?"*

Every entry must be keyed to a feature visible in the source. \
"Render in a crisp, haughty register" tells the translator nothing \
they can act on. "When you see her rhetorical questions, preserve \
them verbatim — never flatten to a declarative or insert hedges \
('I think', 'perhaps')" tells them what to do the moment they hit \
the next rhetorical question.

Be concrete:

- For each observation feature, write a **when-you-see-X-do-Y** \
rule, with **mirror** (carry directly into {target_language}), \
**recast** (substitute a {target_language} equivalent of the same \
effect), or **watch** (a trap to avoid) as the move. Grammar errors, \
verbal tics, signature phrases, stutters, fragmentation rhythm, \
code-switching — usually mirror. Lexical archaism, eye-dialect, \
source-specific particles — usually recast. Stable sociolect splits: \
recast the lexicon, mirror the cognitive/syntactic tendency.
- Name the {target_language} register the translator should reach \
for when handling this character's lines. Be specific (not "rural" \
but "Hardy/Eliot 19th-century English country-servant"). This is \
the only generation-flavoured directive the field needs — the rest \
is source-keyed.
- For each mirrored feature, name what to *look for* in source and \
what to *produce* in target. "When source drops Polish case endings \
on nouns, drop English articles instead — English has no cases, so \
the brokenness ports as article/preposition errors." "When source \
inserts French ('eh bien'), keep the French verbatim in target — do \
not translate or gloss." "When source has a signature filler \
('rozumie pan?'), translate it directly and keep its sentence-final \
position."
- For each recast feature, name the source trigger and the target \
substitution. "When source uses the -że emphatic particle, render \
as 'would ye' or 'mind ye' — literal carry-over reads as gibberish."
- **Eye-dialect is per-character, not categorical.** *Mirror* when \
the source eye-dialect marks a regional or class accent within the \
speech community (Polish villager → English country-servant; \
English literary tradition has Hardy, Eliot, Twain, Scott to draw \
on). Use sparse English eye-dialect of equivalent density — dropped \
terminal -g ("lookin'", "cookin'"), "'tis" for it is, "arf" for \
half, occasional ''ee' for he — one or two marks per sentence, not \
phonetic transcription on every word. *Recast* when the source \
eye-dialect renders a foreign speaker's accent (Russian L1 in \
Polish, French L1 in English); phonetic stage-accents ("vere is ze") \
are tired English clichés — use grammar errors and code-switching \
instead. State the call explicitly in the strategy.
- Address-form mappings: source 'pan/pani' → 'sir/madam'? 'my lord'? \
Just the name? Specify the rule the translator applies on every \
occurrence.
- **Watch-for** entries — name the obvious wrong moves. \
Anachronisms, wrong-region accents (y'all, tha'/thee), stagey \
foreign accents (vere is ze), inline glosses for code-switched \
phrases (the original didn't gloss), softening her tone where the \
source is sharp, expanding clipped imperatives ("Idź." → "You should \
go"), modern slang, contemporary academic tics ("I would argue", \
"positionality"). Make the trap concrete — what the translator \
might be tempted to do, and why it's wrong here.
- One register marker per target sentence is usually enough — \
piling higher reads as parody. Flag this in the strategy when the \
character's voice is dense in source and easy to over-render in \
target.

DO write things like:
- "Reach for 19th-century English country-servant register \
(Hardy/Eliot/Scott — eye-dialect is the literary tradition here, not \
'ye olde' parody). When his line uses the -że particle, render with \
'would ye' or 'mind ye'. When his line has deliberate misspellings \
(tile, dzjewko, ogjer), MIRROR with sparse English eye-dialect of \
equivalent density: drop terminal -g ('lookin'', 'cookin''), use \
''tis' for it is, 'arf' for half, occasional ''ee' for he — one or \
two marks per sentence, never phonetic transcription on every word. \
Add register-marked vocabulary alongside ('wench', 'reckon', \
'afore'). When he addresses a master with 'pan', render as 'sir' \
(preserve master/servant). When he uses folk-mythological terms \
('licho'), prefer keeping the source term italicised on first use \
and glossing in narrative; recast to 'the blight' or 'the rot' only \
where the lore weight is incidental. Watch for: y'all/ain't (too \
American for the period), modern slang, dense phonetic transcription \
(eye-dialect should mark the accent, not become a reading barrier), \
overly polished grammar (his syntax is folk, not schooled)."
- "When her line drops a Polish case ending or fronts an object \
Slavic-style, render the brokenness in English as a Russian L1 \
speaker actually breaks English: drop articles consistently \
(random is unconvincing), use bare or wrong prepositions ('go on \
store'), confuse he/she pronouns under stress. When she reaches for \
a Russian word in source ('давай'), keep the Russian verbatim in \
target. Watch for: invented fake Slavic spellings or 'vere is ze' \
stage-Russian — the grammar errors are the voice, the accent is not \
for the English reader to phonetically reconstruct."
- "When his line contains a French phrase ('eh bien', 'tant pis') \
or a Latin tag ('primum non nocere', 'in vivo'), keep it verbatim \
and unglossed — the original reader felt the switch, the English \
reader should too. When his line uses Polish hedges ('wydaje się', \
'można przypuszczać'), reach for English equivalents ('one might \
suppose', 'it appears that', 'so far as can be told') — never \
collapse to a flat assertion. When he uses long subordinate Polish \
clauses with passives, mirror the structure in English; do not chop \
into short modern sentences for readability. Recast Polish-specific \
scientific vocabulary to interwar English scientific register (not \
modern academic). Watch for: inline glosses for French/Latin (the \
original didn't gloss), and contemporary academic tics ('I would \
argue', 'positionality')."

DON'T write things like:
- "Render in a crisp, haughty, articulate English register." \
(Generation prompt, not translation guidance — names a target \
register without telling the translator what to look for in source \
or what to do when they see it.)
- "Translate naturally with rural feel." (Vague.)
- "Use folksy English." (No markers named, no source triggers.)
- "Make him sound uneducated." (Patronizing, no craft direction, \
not keyed to the source.)
- "Mirror her use of rhetorical questions to belittle others." \
(Names a feature but no triggered rule — what does the translator \
do when they hit one? "Preserve verbatim, do not flatten to \
declarative" is the rule.)

The test: could a translator who hasn't read the source produce \
consistent, specific output from this strategy alone? If not, the \
strategy isn't specific enough.

The author will review your strategies. Your job is a strong starting \
point, not a final answer. The author may refine markers, change the \
target register entirely, or add avoidances based on their own ear. \
Write strategies that give them something concrete to react to.

## How the two fields relate

Observation describes what's happening in source. Strategy is read \
by the translator while they're translating, line by line, and tells \
them what to do when they see each observed feature. For every \
observed feature, the strategy entry pairs a **source trigger** \
("when you see X in this character's line…") with a **move**: \
**mirror** (carry directly into {target_language}), **recast** \
(substitute a {target_language} equivalent of the same effect), or \
**watch** (a trap to avoid).

Coherence test: every observation feature should appear in strategy \
as a source-keyed rule. Every strategy entry should trigger on \
something the translator can see in the source line in front of \
them — never on an abstract directive about target register alone.

Default moves, by feature type:

- Non-standard grammar, verbal tics, signature phrases, stutters, \
fragmentation, repetition rhythms — **mirror**. These features ARE \
the character. The realisation often shifts (Polish case errors → \
English article/preposition errors, since English has no cases) but \
the brokenness carries over. Do not "clean up" a foreigner's \
grammar, a child's syntax, or a stutter — the voice dies with it.
- Code-switching / foreign-language insertions — **mirror**. Keep \
the French in French, the Latin in Latin. The multilingual texture \
*is* the voice. Inline gloss only when the original itself glossed \
(rare); otherwise trust the {target_language} reader to feel the \
switch the way the source reader did.
- Stable sociolect (scientist, peasant, soldier, courtier) — \
**split**. Recast the lexicon (English equivalents of the period, \
class, and profession). Mirror the cognitive/syntactic tendency: a \
hedger hedges in {target_language}; a peasant stays concrete in \
{target_language}; a soldier stays terse; a courtier stays \
elaborate. The shape of thought is not regional vocabulary — it \
carries directly.
- Source-specific particles and honorifics with no target equivalent \
— **recast**. Literal carry-over reads as gibberish. The "-że" \
particle becomes "would ye" or "mind ye".
- Lexical archaism / regional vocabulary — **recast**. Render through \
{target_language} period-and-class equivalents (peasant Polish → \
19th-century English country-servant lexicon; gentry Polish → \
period English drawing-room register).
- Eye-dialect spelling — **per-character call, not categorical**. \
*Mirror* for in-language regional/class accents (Polish villager → \
English country-servant) using sparse equivalent eye-dialect; the \
literary precedent is Hardy/Eliot/Twain/Scott, not 'ye olde' parody. \
*Recast* for foreign-speaker accents (Russian L1 in Polish), where \
phonetic English stage-accents ("vere is ze") are tired clichés — \
use grammar errors instead. Make the call in the strategy.

When the rule of thumb pulls the wrong way, name it explicitly in \
the strategy. The author's review uses these calls.

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

SPEAKER_SCOPE_NOTE = """\
The glossary list below is limited to characters Pass 1 identified as \
speaking in **this window** (quoted lines with evidence). Profile only \
those characters — do not add operations for anyone not listed.

"""

REGENERATION_NOTE = """\
**Targeted regeneration.** Rebuild this character's voice profile from \
scratch using only the dialogue in this window. The profile fields were \
cleared and the candidate pool is empty — treat this like a fresh profile \
for this character: write full source_voice_observation and \
target_voice_strategy and seed initial_candidates from this window's \
evidence. Later windows in this regeneration pass will extend and add \
candidates as usual.

"""


def render_voice_profiles_table(profiles: list[Any]) -> str:
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


def render_glossary_characters_table(characters: list[Any]) -> str:
    """Render the glossary character list — all available targets for
    voice operations. canonical_name copied verbatim into the
    cross-checked ``canonical_name`` field on every operation."""
    if not characters:
        return "(empty — no characters in the glossary; voice extraction cannot proceed)"

    lines = ["glossary_entry_id | canonical_name | variants | has_voice_profile"]
    for c in characters:
        variants = ", ".join(c.variants) if c.variants else "—"
        lines.append(
            f"{c.glossary_entry_id} | {c.canonical_name} | {variants} | {c.has_voice_profile}"
        )
    return "\n".join(lines)


def render_notepad(notes: list[Any]) -> str:
    if not notes:
        return "(empty)"
    return "\n".join(f"- [{n.category}] {n.content}" for n in notes)
