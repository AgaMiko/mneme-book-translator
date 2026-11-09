"""Prompt template for per-passage literary translation.

Paired with ``../models/translate_passage_model.py``.

What changed in this revision
-----------------------------
The prompt now reads BOTH voice fields produced by extraction:

- ``source_voice_observation`` — what the character is doing in the
  source language. Names specific markers the translator should
  recognize and preserve.
- ``target_voice_strategy`` — how to render that voice in the target
  language. Names specific markers to use, and things to avoid.

The strategy is the primary directive. It tells the translator-LLM
which target-language register to construct and how. The observation
provides context — it explains *why* the strategy is what it is, and
helps the translator-LLM track which source features the strategy is
addressing.

Anti-Polglish guidance is unchanged from the previous revision — five
named patterns plus the "nothing inserted" rule. These now apply WITHIN
the chosen target register: if the strategy says "archaic-rural English,"
the anti-Polglish patterns should be applied with that register's
vocabulary and idioms in mind.
"""

from typing import Any

PROMPT = """\
You are translating a single passage of {source_language} dialogue \
into {target_language} for a fiction manuscript. The translation will \
become a calibration sample for the rest of the book — a known-good \
reference the translator-LLM downstream will read alongside the \
voice fields when translating other passages.

Your goal: a translation that does for {target_language} what the \
source author did for {source_language} — render the character's \
voice with the same craft, in the equivalent register, using the \
specific markers named in the strategy. Faithful enough that a native \
{target_language} reader takes it for an original.

Respect every glossary term in the accepted glossary list. Insert \
nothing the source doesn't say.

## Two non-negotiables

The system checks both. Operations that violate them are dropped.

**(1) The ``selected_passage_id`` you return must match the input \
verbatim.** Copy it exactly.

**(2) The ``canonical_name`` you return must match the input.** \
Cross-checked.

{voice_guide}

## Glossary discipline

The accepted glossary is the canonical record of how terms in this \
book have been decided to translate. **For any term in the glossary \
that appears in the source passage, use the accepted target form.** \
Do not retranslate, do not vary, do not invent.

The ``translation_strategy`` field tells you *why* the choice was \
made:
- ``keep_original``: the source-language form is preserved (proper \
nouns, made-up world-specific terms).
- ``translate_literally``: direct {target_language} equivalent the \
author has accepted.
- ``adapt``: adapted to fit {target_language} naturally — neither \
preserved nor literally translated.
- ``transliterate``: transliterated phonetically.

If you encounter a related term that ISN'T in the glossary (a place \
name, a magic term, a faction name in the same family), apply the \
same strategy as the established terms in that family. Consistency \
matters.

## Avoiding translation-ese

A native {target_language} reader should not be able to tell from \
your translation that the source was {source_language}. If they \
could, you've calqued.

Apply these patterns within the register named in the strategy. If \
the strategy directs you to "archaic-rural English," your idiom \
choices should come from that register's stock; if the strategy \
directs you to "modern educated English," from that register's stock. \
The patterns themselves apply to all registers:

1. **Idiom for idiom, not word for word.** Find the {target_language} \
idiom that does the same conversational job, not the literal \
translation.

2. **Live metaphors, not dead calques.** The {source_language} image \
often technically exists in {target_language} but reads archaic. Use \
the equivalent the target language actually uses.

3. **Plain words over learned ones.** Where {source_language} uses \
formal or Latinate words casually, {target_language} literary prose \
prefers shorter, plainer roots.

4. **Verb-heavy {target_language}, not noun-heavy {source_language}.** \
{source_language} loves long abstract noun phrases; {target_language} \
breaks them into verbs.

5. **Use contractions in dialogue** unless the strategy directs \
otherwise. Most dialogue contracts (*"we're"*, *"don't"*, *"I'm"*); \
deliberately formal or archaic registers may use fewer or different \
contractions, per the strategy.

## The "nothing inserted" rule

Every word in your translation must correspond to source content. If \
the source doesn't contain a phrase like *"easy now"* or *"trust me"* \
or *"my friend"*, your translation doesn't add one. The translator's \
craft is in *how* the existing source content is rendered, not in \
adding flavor.

This rule is strict. If you find yourself wanting to add a phrase to \
"make it flow better," resist. Better target-language flow is achieved \
through restructuring what the source says, not through addition.

This rule applies to register markers too. The strategy tells you \
which markers to use, but only deploy them where there's actual source \
content to render — don't sprinkle "ye" or "afore" into sentences \
that don't call for them in the source. Use markers where the source \
has voice work to translate; otherwise just translate cleanly.

## What to write in ``reasoning``

One or two clauses on translation choices that affect voice or that \
required interpretation. Examples:
- "Followed the strategy for his emphatic particle in both lines."
- "Kept the diminutive's patronizing weight with an English endearment."
- "Translated the register shift in sentence 2 by switching to short \
clipped clauses."
- "Used the glossary forms for both names."

Brief. This is for review traceability, not justification.

---

## Character

profile_id: {profile_id}
canonical_name: {canonical_name}

{voice_block}

## Accepted glossary ({n_terms} terms)

For any term below that appears in the source passage, use the \
accepted target form.

{glossary_block}

## Source passage

selected_passage_id: {selected_passage_id}

{passage_source_text}
"""


def render_glossary_block(terms: list[Any]) -> str:
    """Render the accepted glossary terms as a tabular reference."""
    if not terms:
        return "(empty — no accepted glossary terms; translate freely but consistently)"

    lines = ["term_source | term_target | strategy | notes"]
    for t in terms:
        notes = t.notes if t.notes else "—"
        lines.append(f"{t.term_source} | {t.term_target} | {t.translation_strategy} | {notes}")
    return "\n".join(lines)


VOICE_GUIDE_PROFILE = """\
## How to use the two voice fields

You receive two fields describing this character's voice:

- ``source_voice_observation`` describes what the character is REALLY \
doing in {source_language}. Specific markers: particles, archaic \
vocabulary, deliberate misspellings, address conventions, register \
shifts.
- ``target_voice_strategy`` directs you to a specific {target_language} \
register, names markers to use, and names things to avoid.

**The strategy is your primary directive.** Apply it specifically: \
when it names a marker (e.g., "use 'ye' for informal you"), use that \
marker. When it names an avoidance (e.g., "no Americanisms"), avoid \
the named pattern.

**The observation gives you context.** When you see a marker in the \
source that the observation has named, you know it's deliberate — the \
source author put it there to mark voice. Render its functional \
equivalent in {target_language}, using the strategy's markers.

If observation and strategy seem to conflict (rare; should be caught \
in author review), follow the strategy. The strategy is the craft \
decision; the observation supports it."""

VOICE_GUIDE_BRIEF = """\
## How to use the voice brief

**The source passage comes first:** translate what is said, with \
nothing added or lost. The voice brief tells you how this character \
comes across in {target_language}: who they sound like, how plain or \
elevated their words are, how formal they are. Let it guide *how* you \
say it: which words you reach for and how you build each sentence, so \
the character keeps their register and sounds unlike anyone else in \
the book. The brief ends with a short sample in the character's voice: \
use it to hear how they sound, never copy its phrases into the \
translation. Wherever the prompt below mentions "the strategy", read it \
as this brief."""


def render_voice_block(*, observation: str, strategy: str, brief: str | None) -> str:
    """The character's voice section: the brief when there is one, else both fields."""
    if brief:
        return f"### Voice brief\n\n{brief}"
    return (
        f"### Source voice observation\n\n{observation}\n\n### Target voice strategy\n\n{strategy}"
    )
