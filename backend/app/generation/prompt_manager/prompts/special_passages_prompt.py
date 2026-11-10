"""Prompt templates for special passages (Step 6).

Paired with ``../models/special_passages_model.py``. Like the other
prompts, they describe what to look for and hold no examples in a source
language.
"""

SCAN_PROMPT = """\
You are preparing a {source_language} novel for translation into \
{target_language}. Below is one chapter, paragraph by paragraph. Find the \
passages that an ordinary translation would damage, because their wording \
follows a rule and not only a meaning.

Return a candidate for:

- **verse**: a poem, song, nursery rhyme, chant, prayer, spell or riddle \
set in lines, whether the lines are separate paragraphs or line breaks \
inside one paragraph. An epigraph in the chapter heading counts.
- **document**: a letter, note, inscription, list or other text quoted in \
the story that could hide a message. Signs: the story says or hints that \
it is coded, strange, stiff or worth reading twice; a character studies \
it, counts letters or reads it in an unusual order; its sentences or lines \
are oddly regular; some words are marked. Return every quoted letter or \
note of several sentences even without such signs: a later step looks at \
its letters.
- **wordplay**: a pun, anagram, riddle or play on a name that the plot, a \
joke or a later line depends on. Ordinary figures of speech do not count.

Rules:
- A passage is a run of paragraphs that follow each other. Give its first \
and last paragraph id. Leave out the narration around it.
- Do not return dialogue, thoughts or descriptions that have no rule of \
this kind.
- Most chapters have none. Return an empty list then.

## Chapter

{chapter_text}
"""

RULE_PROMPT = """\
You are preparing a {source_language} novel for translation into \
{target_language}. A scan marked the passage below as one whose wording \
may follow a rule. Decide whether it does, and state the rule so a \
translator can keep it.

## What to decide

- **verse**: say the number of lines, the rhyme scheme as letters, and \
what the metre is like (line length, a refrain). The translation must \
keep these.
- **hidden_message**: letters or words of the passage spell something. \
The letter strings below were computed by code; read them as text in \
{source_language}, and also check what the chapter says about the \
passage (a character who decodes it, a stated message). Give the units \
that carry the letters, the message in {source_language}, and the same \
message in {target_language} with the same meaning, as short as it can \
be. If the rule is not "first letters of units", choose unit "other" and \
describe the rule exactly, with the steps to read the message. Say which \
part of the passage carries the message: a salutation, heading or \
sign-off often stands outside it.
- **wordplay**: say what the two meanings or the two forms are, and what \
depends on them.
- **none**: a text with no such rule. A letter string that spells nothing \
is the normal case; do not read a message into letters that do not form \
words.

Write the rule in plain words for a translator. Do not refer to \
paragraph ids in it.

Then list the **dependent paragraphs**: paragraphs of the chapter outside \
the passage that quote its words, explain its rule, give worked examples \
of the rule, or state what it hides. They must stay consistent with the \
translated passage.

## Passage ({first_id} to {last_id}, first marked as: {candidate_kind})

{passage_text}

## Letter strings of the passage (computed by code)

{letter_strings}

## The whole chapter

{chapter_text}
"""

CHECK_PROMPT = """\
You are checking the {target_language} translation of a passage from a \
{source_language} novel. The passage follows a rule, and the translation \
must follow it too.

Kind: {kind}
Rule: {rule}
{message_block}
Check only the rule. Do not judge style, word choice or accuracy beyond \
it.

- **verse**: compare line count, rhyme scheme and metre with the source. \
Read the line endings aloud: a rhyme must be heard in {target_language}, \
and near-rhymes count only where the source uses them. A translation that \
is correct prose in lines, without the rhyme the source has, breaks the \
rule.
- **hidden_message**: apply the rule to the translation and say what it \
spells. It must spell the target message. When letter strings are given \
below, they were computed by code: use them and do not recount.
- **wordplay**: both meanings or forms must be readable in the \
translation, and whatever depends on them must still make sense.
- The dependent paragraphs must agree with the translated passage: quoted \
words match it, and a stated message is the one it spells.

## Source passage

{source_text}

## Translation

{target_text}

## Letter strings of the translation (computed by code)

{letter_strings}

## Dependent paragraphs (source, then translation)

{dependent_text}
"""

REWRITE_PROMPT = """\
You are a literary translator working from {source_language} into \
{target_language}. The passage below follows a rule. Its current \
translation is accurate but breaks the rule. Translate the passage again \
so that the {target_language} text follows the rule.

Kind: {kind}
Rule: {rule}
{message_block}
## What the current translation gets wrong

{problems}

## How to work

- The rule comes first, then the meaning, then the exact wording. Keep \
everything the source says that the rule allows; change wording, word \
order and sentence breaks freely to fit the rule.
- Keep the voice and register of the source: a letter still sounds like \
its writer, a folk song still sounds like one.
- Use the names and terms exactly as the current translation has them.
- **Hidden message**: write the plan first, one unit per letter of the \
target message. The part of the passage that carries the message must \
have exactly as many units as the message has letters, so merge or split \
sentences where needed. A salutation, heading or sign-off stays outside \
it, as in the source. After writing, read the first letter of every unit \
in order and compare with the target message letter by letter; fix any \
mismatch before you answer. \
The text must still read as a natural letter or note, with no sign that \
it was built around letters.
- **Verse**: keep the number of lines and the rhyme scheme, with rhymes \
that are heard in {target_language}, and a line length close to the \
source. Keep line breaks where the current translation has them.
- **Wordplay**: find a {target_language} pair that carries both meanings, \
or the closest play that keeps what depends on it.
- Return every paragraph of the passage with its id. Keep the paragraph \
count, and keep markup (italics, line breaks) as in the current \
translation.
- **Dependent paragraphs** quote or decode the passage. Return those that \
must change so that they agree with your new text: quoted words must match \
it, worked examples must use words that are in it, and a stated message \
must be the target message. Change only what is needed and return the \
paragraph in full.

## Source passage

{source_text}

## Current translation

{target_text}

## Dependent paragraphs (source, then current translation)

{dependent_text}
"""
