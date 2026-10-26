"""Prompt templates for the cast pass: briefs, then a check of the passages.

Paired with ``../models/cast_voices_model.py``. Both run once per book
(``services.voice_build_service``): ``BRIEFS_PROMPT`` after the profiles
are built, ``CHECK_PROMPT`` after the reference passages are translated
with those briefs.
"""

BRIEFS_PROMPT = """\
You are the voice editor for the {target_language} translation of a \
{source_language} novel. Every speaking character already has a voice \
profile, built from all of their lines, and a few reference passages. \
The profiles were written one character at a time. Your job is to look \
at the whole cast together and:

1. write a **short brief** per character: how they should come across \
in {target_language}, the only voice guidance the translator will see;
2. make sure **no two characters would sound the same** in \
{target_language}.

## 1. cast_notes (write first)

Group the characters whose {target_language} voices could collapse into \
one: same register, same rhythm, same markers. For each group, say what \
actually separates them in the source lines (features, address forms, \
rhythm, vocabulary, what they do in conversation). Name the \
{target_language} markers you will give each so they stay apart. Keep it \
short.

## 2. briefs

One brief per character, in the order given, with the code and \
canonical name copied from the heading.

**What a brief is for.** The translator reads it while translating, \
with the {source_language} line already in front of them. They do not \
need to be told what is in the line; they need to know how this \
character should *come across* in {target_language}, so the voice \
survives the translation. Describe the character's vibe and register, \
not mechanics of single lines.

Format, about 100 words in total, in {target_language}, in two parts:

**Voice:** (tell) one or two sentences: who this person sounds like \
(social position, education, profession, age, region or accent), how \
plain or elevated their vocabulary is, how formal they are, and what \
that should sound like in {target_language}. Then one or two short tips \
on what must not be lost, including, if the character is in a group \
from cast_notes, how they differ from the closest voice ("Next to Mira, \
he sounds noticeably more educated and formal"). Examples of the tell: \
"An educated aristocrat and researcher: precise, Latinate vocabulary \
and courteous, well-formed sentences; in English, cultivated and \
slightly formal, never slangy." "A healer who talks plainly: everyday \
words, short practical sentences, medical terms only when she is \
working." "A rural household man; country-coloured English, coarse \
humour, never stage dialect."

**In their voice (style only, don't reuse phrases):** (show) two or \
three sentences in {target_language} as this character would actually \
say them: their vocabulary, rhythm, formality and colouring, so the \
translator can hear the voice. Rules for the sample:
- the **same density** of markers as their real lines (check the \
sample lines): a light rural colouring stays light, an educated voice \
is not turned into a parody of one;
- something they could plausibly say in the book's world, but **not** a \
quote or paraphrase of their actual lines, and no new plot facts;
- one sentence is enough for a character with very few lines.

Write the brief as plain text with the two labels, like this:

Voice: …

In their voice (style only, don't reuse phrases):
"…"

Judge the register from the **sample lines and passages** as well as \
the profile. The profiles were told not to infer a voice from a \
character's role, so they can under-state how educated, formal or \
rural someone sounds; where the lines show it (vocabulary, titles \
others use for them, how they explain things), say so. Leave out what \
applies to everyone (contractions in dialogue, natural idiom, no \
anachronisms). A character with very few lines gets one \
sentence in each part. A profile marked **accepted by the author**: \
keep its brief faithful to that strategy.

---

{cast_section}
"""

CHECK_PROMPT = """\
You are the voice editor for the {target_language} translation of a \
{source_language} novel. Each speaking character has a short voice \
brief: how they should come across in {target_language}. Their \
reference passages were translated with those briefs. Look at the whole \
cast together and flag the passages whose translation loses the voice.

## passage_flags

Read each reference passage's source and proposed {target_language} \
translation. Flag a passage only when:
- **flattened**: the translation loses the voice the brief describes \
(an educated speaker made casual, a plain speaker made literary, a \
rural voice made standard, an address form dropped);
- **sounds_like_other**: the character's lines would pass for another \
character in the cast;
- **off_brief**: the translation goes against the brief in another way.

The source text has the highest priority: never flag a translation for \
staying close to what the source says. Do not flag for general quality, \
word choice unrelated to voice, or other speakers' lines. Passages \
marked **accepted by the author** are reference only: do not flag them. \
For each flag, give the reason in one or two sentences and the **whole \
passage translated again**, fixing only the voice problem and keeping \
everything else as close to the proposed translation as possible. \
Return an empty list when every passage carries its voice.

---

{cast_section}
"""
