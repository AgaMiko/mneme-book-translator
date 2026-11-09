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

**First, read the lines closely.** For each character, go through \
their lines (the "Lines" list) word by word before writing anything, \
and notice the subtleties that make the voice:
- **dialect or regional words** and particles;
- **non-standard grammar**: wrong agreement, a dialect form of a verb, \
unusual case or word order;
- **old-fashioned or high words** and how learned the vocabulary is \
(Latinate, technical, scholarly, ceremonial);
- **eye-dialect spelling** (the author misspells words on purpose);
- how others address them (titles, familiar names).

Count how many lines carry each. Keep apart what is **occasional** \
(say, eye-dialect spelling in one scene) and what runs through \
**most lines** (say, dialect words and grammar). What runs through most \
lines *is* the voice: the brief must say so plainly and the sample \
must show it. Do not let a profile's caution ("not sustained", \
"broadly intelligible", "standard {source_language}") talk you out of what the \
lines show.

Format, about 100 words in total, in {target_language}, in two parts:

**Voice:** (tell) one or two sentences: who this person sounds like \
(social position, education, profession, age, region or accent), how \
plain or elevated their vocabulary is, how formal they are, the \
{source_language} markers that carry the voice (name two or three), \
and what that should sound like in {target_language}. Then one or two \
short tips on what must not be lost, including, if the character is in \
a group from cast_notes, how they differ from the closest voice ("Next \
to the healer, he sounds noticeably more educated and formal"). Examples of \
the tell: "An educated aristocrat and researcher: precise, Latinate \
vocabulary and courteous, well-formed sentences; in English, cultivated \
and slightly formal, never slangy." "A healer who talks plainly: \
everyday words, short practical sentences, medical terms only when she \
is working." "A village man who speaks dialect in nearly every line \
(dialect words and non-standard agreement): in English, \
consistent country grammar and words in every sentence, readable, not \
phonetic spelling."

**In their voice (style only, don't reuse phrases):** (show) two or \
three sentences in {target_language} as this character would actually \
say them, so the translator can hear the voice:
- carry over **what runs through their lines**: dialect speech gets \
{target_language} dialect grammar and words in every sentence (for \
English, things like non-standard verb forms, "them" for "those", \
"were" for "was", regional words); an educated voice gets its learned \
vocabulary and sentence shape; broken grammar stays broken;
- the **same frequency** as their real lines: dense where they are \
dense, occasional where they are occasional; no phonetic spelling \
unless their lines use eye-dialect throughout;
- something they could plausibly say in the book's world, but **not** a \
quote or paraphrase of their actual lines, and no new plot facts;
- one sentence is enough for a character with very few lines.

Write the brief as plain text with the two labels, like this:

Voice: …

In their voice (style only, don't reuse phrases):
"…"

Judge the register from the **lines and passages** as well as the \
profile. The profiles were told not to infer a voice from a \
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
