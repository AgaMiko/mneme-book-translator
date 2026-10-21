"""Prompt templates for the three fragment translation stages.

Paired with ``../models/translate_fragment_model.py``.

The rules come from the manual translation of *Zaplataczka*
(``translations/zaplataczka/BRIEF.md`` and ``POLISH_BRIEF.md``) and from the
calibration prompt (``translate_passage_prompt.py``), with the changes listed
in ``docs/step5-translation-pipeline.md`` §4:

- an explicit exception to "plain words over Latinate" when a character's
  voice strategy names a Latinate, clinical, elevated, archaic or broken
  register;
- names always in the nominative (no Polish case endings);
- punctuation guidance for dialogue dashes, em dashes and ellipses;
- clarifying beats allowed only in the line edit, and always reported;
- author placeholders copied as is; source typos translated as intended
  and reported.

Prompt order: the fixed part (``render_fixed_context``: rules, style sheet,
glossary) first, then the stage's task, then the per-fragment context
(``render_fragment_context``: chapter, voices, neighbours) and the text.
The ``build_*_prompt`` functions return everything after the fixed part; the
chain puts the fixed part in front, or points at a cache that holds it.
"""

from __future__ import annotations

from dataclasses import dataclass

RULES_CORE = """\
## Translation rules

1. **Translate meaning, not words.** Every piece of content in the source \
(each event, image, fact, line of dialogue and feeling) is in the \
translation, and the translation adds no content the source does not have. \
Wording and sentence structure are free: words, clauses and sentences do not \
need to match the source one to one. Do not add content to make the text \
flow (no "easy now", "trust me", "my friend" unless the source has them), \
and no images, details or stronger wording than the source has; better \
flow comes from restructuring what the source says.

2. **Idiom for idiom.** Use the {target_language} idiom that does the same \
job, not a word-for-word copy. Polish "No proszę" → "Would you look at \
this", not "Well, please".

3. **Living images.** If a source image sounds old or odd in \
{target_language}, use the image {target_language} writers use today.

4. **Plain words over Latinate words in narration.** Polish uses Latinate \
words casually; English fiction prefers shorter, plainer words. "prawdziwa \
katastrofa" → "serious trouble", not "a real catastrophe".
   **Exception:** when a character's voice strategy names a Latinate, \
clinical, elevated, archaic or broken register, follow the strategy for that \
character's lines and for free indirect thought in their point of view. A \
character who speaks in clinical Latinate terms keeps them ("haemorrhage", \
"fabricates images"). A character with broken non-native grammar keeps the \
broken grammar.

5. **Verbs over abstract nouns.** Break long abstract noun phrases into \
verbs. "wymusić strach na obywatelach" → "terrorise the public".

6. **Contractions in dialogue**, unless the character's voice strategy says \
otherwise (formal, ritual or archaic speech).

7. **Names in the nominative.** Polish names change their endings by case \
(Miro, Mirze, Mirą are all Mira; Einardzie is Einard; Steina is Stein). \
Always write the glossary form. Show possession with English 's. Short forms \
the glossary lists (e.g. Jen, Ein) are separate names; keep them as they are.

8. **Glossary terms.** For every glossary term in the source, use the \
glossary's target form exactly. Do not vary it. A term's notes may say when \
an ordinary word is NOT the glossary term (for example, a literal hair braid \
is not the magic "weave"). For a new name or term in the same family as \
glossary terms, follow the same strategy, and report it as a term_choice note.

9. **Voices.** Follow each character's target voice strategy. The source \
observation explains why. Use the named markers only where the source has \
voice to translate; do not sprinkle them in.

10. **Free indirect thought** stays in past tense. Only direct thought is in \
italics.

11. **Author placeholders** (xxxxxxx, [xxxx]) are copied exactly and \
reported as placeholder notes.

12. **Source typos.** Translate an obvious typo as the word that was meant. \
If you had to guess what was meant, add a source_typo note. Do not report \
single-letter slips.

13. **No modern idiom in narration** (no "light years", "on the same page", \
"reach out").
"""

STYLE_SHEET = """\
## Book style sheet

- Spelling: {spelling}.
- Dialogue: Polish dialogue dashes ("\u2013 ") become {target_language} double \
quotes. Em dashes (—) only for interruptions and sharp asides.
- Ellipses (…): keep in dialogue where a speaker trails off or falters, and \
at real moments of fear. In narration, prefer a full stop, a comma or a \
different sentence.
- Units: narration uses traditional units (paces, feet, miles, pounds); \
measurements on charts, documents and instruments stay as in the source \
(°C). Round converted numbers naturally ("a good five paces"), don't give \
false precision.
- Chapter headings: a paragraph may hold the chapter heading: the \
point-of-view name, "Rozdział N. Title", and an epigraph with its \
attribution line. Translate all of it and keep its line breaks. \
"Rozdział" is "Chapter". Epigraphs keep their own register; attribution \
lines start with an em dash.
- Scene breaks: keep a "***" paragraph as "***". If a scene break carries a \
point-of-view name (e.g. "*** Kerry"), write "***" and put the name in the \
same paragraph on a new line in italics: "***\\n*Kerry*".
- Mind-to-mind speech: the point-of-view character's words in double \
quotes, the other speaker's words in italics, as in the source.
- Keep italics for thoughts, letters and quoted documents where the source \
has them. Remove markdown escape backslashes (\\!, \\.).
- Epigraphs, letters, scripture and quoted documents keep their own \
register. Rhymes and wordplay: report as wordplay notes.
"""

FAITHFUL_TASK = """\
## Your task: faithful translation (stage 1 of 3)

Translate the source paragraphs into {target_language}. This is the faithful \
pass: every sentence is accounted for and the meaning is exact. Apply the \
rules and the style sheet above, including names, glossary terms, quotes, \
units and scene breaks. Write correct, readable {target_language}, but do not \
yet work on rhythm or variety; a line editor does that next.

Return one paragraph for each source paragraph, with the same id, in the same \
order. Never merge or split paragraphs across ids.

Add a note only when the author needs to know or decide something.
"""

LINE_EDIT_TASK = """\
## Your task: line edit (stage 2 of 3)

Below is a faithful translation of the source paragraphs. It is accurate \
but still follows the source too closely. Rewrite it into fluent, natural \
{target_language}, the way a skilled {target_language} novelist would have \
written this passage, so it reads like a published fantasy novel and not \
like a translation.

Work from the meaning, not the words. Read each source paragraph, \
understand what it says and how it says it, then write the best \
{target_language} version of that. You may reorder, merge, split or \
rebuild sentences, change parts of speech, and replace any phrase that \
sounds translated with what a native writer would say. Keep:
- the meaning: every event, image, fact, line of dialogue and feeling, with \
nothing added and nothing lost;
- the author's style: tone, register, pace, how plain or ornate the prose \
is, the point of view and the mood of each scene;
- each character's voice, as the voice profiles describe.

Check your rewrite against the source paragraph, not against the faithful \
translation: the faithful text is a draft, not the standard.

- Vary sentence openings. Avoid runs of "She… She… She…" or "He… He…".
- Sentence rhythm: vary sentence length. Translating sentence by sentence \
tends to give runs of sentences of about the same length; mix short, \
medium and long ones so the prose has movement. Short sentences for \
impact and action, longer ones for reflection and description, as the \
author does in the source. Keep the author's deliberate effects (a run of \
short fragments, a long breathless sentence).
- Word repetition: do not use the same word again within a few lines. \
Polish avoids repetition through inflection and synonyms; English needs a \
synonym, a pronoun or a rebuilt sentence. Keep a repetition only where the \
source repeats on purpose (anaphora, a refrain, emphasis), and keep \
glossary terms and names exactly as they are.
- Meaning wins over variety. A precise word used twice is better than a \
synonym that shifts the meaning: soldiers are not "guards" or \
"infantrymen", patients are not "sick men", "the shrine" is not "a \
shrine". Prefer a pronoun or a rebuilt sentence to a looser synonym. Do \
not add images, details or intensity to vary a sentence ("from her knees" \
does not become "from the muck"; "angry shouts" do not become "ragged \
screams").
- Merge or split sentences for {target_language} rhythm. Cut Polish-style \
chains of "and… and…" or "so… so…".
- Fix stiff or word-for-word phrases. No modern slang in narration.
- Ellipses: keep them in dialogue at hesitation or fear; trim them from \
neutral narration.
- Vary dialogue tags and prefer action beats; don't repeat "muttered" or \
"murmured" within a few lines.
- When two characters of the same gender talk, make sure the reader can tell \
who speaks. You may add a minimal clarifying beat (a name, "he said"). \
Report every such addition as an added_clarification note.
- Do not flatten voices: keep each character's register as the voice \
strategy describes.
- Keep glossary terms, names, placeholders, epigraphs and letters exactly.
- Fix every problem listed under "Problems found by automatic checks", and \
look at each spot listed under "Rhythm and repetition in the draft".

Return one paragraph for each paragraph id, in the same order.
"""

POLISH_TASK = """\
## Your task: final polish (stage 3 of 3)

Below is the line-edited translation. Make it read like a professionally \
edited {target_language} fantasy novel without changing what happens, what \
is said, or who says it.

Measured targets, with this fragment's current numbers:

{metrics_block}

When a target is missed, rewrite the listed sentences until the fragment \
meets it; expect to change many sentences. Return the text unchanged only \
when every target is met and nothing reads clumsily.

- She/He openers: vary with the character's name, a participial or \
prepositional opener, object-first order, merging two short sentences, or \
starting with the action. Don't fall into a new pattern: use at most one \
participial opener ("Turning, she…", "Sitting on the cot, she…") per \
paragraph, and keep simple "She did X" sentences where they read best.
- Ellipses: keep only where a speaker trails off or falters, or at a real \
moment of dread. Never for mood alone.
- Em dashes: keep for interruptions and sharp asides; use commas, colons, \
semicolons or full stops elsewhere.
- Stock phrases (the weight of, a beat, ghost of a smile, a flicker of, a \
wave of, couldn't help but, suddenly…): replace with something concrete, or \
cut.
- Also fix clunky lines (especially converted units), long clause chains \
and repeated dialogue tags.
- Sentence rhythm: vary sentence length. Translating sentence by sentence \
tends to give runs of sentences of about the same length; mix short, \
medium and long ones so the prose has movement. Short sentences for \
impact and action, longer ones for reflection and description, as the \
author does in the source. Keep the author's deliberate effects (a run of \
short fragments, a long breathless sentence).
- Word repetition: do not use the same word again within a few lines. \
Polish avoids repetition through inflection and synonyms; English needs a \
synonym, a pronoun or a rebuilt sentence. Keep a repetition only where the \
source repeats on purpose (anaphora, a refrain, emphasis), and keep \
glossary terms and names exactly as they are.
- Meaning wins over variety. A precise word used twice is better than a \
synonym that shifts the meaning: soldiers are not "guards" or \
"infantrymen", patients are not "sick men", "the shrine" is not "a \
shrine". Prefer a pronoun or a rebuilt sentence to a looser synonym. Do \
not add images, details or intensity to vary a sentence ("from her knees" \
does not become "from the muck"; "angry shouts" do not become "ragged \
screams"). Three or more \
rhetorical questions in a row may be merged only if nothing is lost.

Do not:
- add events, images, jokes or lines of dialogue, or cut content;
- change glossary terms or names;
- flatten voices (Latinate snobbery, rural dialect, broken grammar, formal \
ritual speech stay as they are). A character's deliberate ellipses or \
fragments are a voice device, not a style problem;
- touch epigraph wording, quoted documents, letters, acrostics, ciphers, \
placeholders, or scene-break formatting.

If an edit might change meaning, removes a voice device, or fixes a \
continuity slip, list it in declared_edits, with "before" and "after" both \
quoted from the English (before = the line-edited English you received). \
Do not list translation choices or stylistic rewording: a sentence \
rephrased with the same meaning is not a meaning risk and is not listed.

Return one paragraph for each paragraph id, in the same order.
"""


@dataclass(slots=True)
class GlossaryRow:
    source: str
    target: str
    strategy: str
    variants: list[str]
    notes: str | None


@dataclass(slots=True)
class VoiceRow:
    name: str
    observation: str
    strategy: str


def render_glossary(rows: list[GlossaryRow]) -> str:
    if not rows:
        return "(no accepted glossary terms)"
    lines = ["source | target | strategy | source forms seen | notes"]
    for r in rows:
        variants = ", ".join(v for v in r.variants if v and v != r.source) or "—"
        lines.append(f"{r.source} | {r.target} | {r.strategy} | {variants} | {r.notes or '—'}")
    return "\n".join(lines)


def render_voices(rows: list[VoiceRow]) -> str:
    if not rows:
        return "(no voice profiles for the characters in this fragment)"
    parts = []
    for r in rows:
        parts.append(
            f"### {r.name}\n\nSource voice (what the character does in the source):\n"
            f"{r.observation}\n\nTarget voice strategy (how to render it):\n{r.strategy}"
        )
    return "\n\n".join(parts)


def render_paragraphs(paragraphs: list[tuple[str, str]]) -> str:
    return "\n\n".join(f"[{pid}]\n{text}" for pid, text in paragraphs)


def render_fixed_context(
    *,
    book_title: str,
    source_language: str,
    target_language: str,
    glossary: list[GlossaryRow],
) -> str:
    """The part of every prompt that is the same for the whole book.

    Rules, style sheet and glossary. It always comes first, so Gemini can
    reuse it from a cache: an explicit one per run (``translation_cache``) or
    its automatic prefix caching. Anything that changes per chapter or per
    fragment must stay out of it, or the cached prefix stops matching.
    """
    spelling = "British English" if target_language.lower().startswith("en") else target_language
    return "\n\n".join(
        [
            f'You are a literary translator working on the novel "{book_title}", '
            f"translating from {source_language} into {target_language}.",
            RULES_CORE.format(target_language=target_language),
            STYLE_SHEET.format(target_language=target_language, spelling=spelling),
            f"## Accepted glossary ({len(glossary)} terms)\n\n{render_glossary(glossary)}",
        ]
    )


def render_fragment_context(
    *,
    chapter_title: str,
    voices: list[VoiceRow],
    previous_source: str,
    previous_target: str,
    next_source: str,
) -> str:
    """The part of the prompt that changes per fragment: chapter, voices, neighbours."""
    blocks = [
        f"## Current chapter\n\n{chapter_title}",
        f"## Voice profiles\n\n{render_voices(voices)}",
    ]
    neighbours: list[str] = []
    if previous_source:
        neighbours.append(
            "### End of the previous fragment (source; context only, do not translate)\n\n"
            + previous_source
        )
    if previous_target:
        neighbours.append(
            "### End of the previous fragment (current translation; match its terms and tone)\n\n"
            + previous_target
        )
    if next_source:
        neighbours.append(
            "### Start of the next fragment (source; context only, do not translate)\n\n"
            + next_source
        )
    if neighbours:
        blocks.append("## Neighbouring text\n\n" + "\n\n".join(neighbours))
    return "\n\n".join(blocks)


def build_faithful_prompt(
    *, context: str, target_language: str, source: list[tuple[str, str]]
) -> str:
    return "\n\n".join(
        [
            FAITHFUL_TASK.format(target_language=target_language),
            context,
            "## Source paragraphs\n\n" + render_paragraphs(source),
        ]
    )


def build_line_edit_prompt(
    *,
    context: str,
    target_language: str,
    source: list[tuple[str, str]],
    faithful: list[tuple[str, str]],
    checks: list[str],
    rhythm: list[str],
) -> str:
    return "\n\n".join(
        [
            LINE_EDIT_TASK.format(target_language=target_language),
            context,
            "## Problems found by automatic checks\n\n"
            + ("\n".join(f"- {c}" for c in checks) if checks else "(none)"),
            "## Rhythm and repetition in the draft\n\n"
            + ("\n".join(f"- {r}" for r in rhythm) if rhythm else "(none found)"),
            "## Source paragraphs\n\n" + render_paragraphs(source),
            "## Faithful translation to edit\n\n" + render_paragraphs(faithful),
        ]
    )


def build_polish_prompt(
    *,
    context: str,
    target_language: str,
    source: list[tuple[str, str]],
    line_edited: list[tuple[str, str]],
    metrics_block: str,
) -> str:
    return "\n\n".join(
        [
            POLISH_TASK.format(target_language=target_language, metrics_block=metrics_block),
            context,
            "## Source paragraphs (for checking meaning)\n\n" + render_paragraphs(source),
            "## Line-edited translation to polish\n\n" + render_paragraphs(line_edited),
        ]
    )
