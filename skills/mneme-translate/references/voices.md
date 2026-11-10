# Voices

A voice brief tells the translator how a character should come across in English, so each speaker keeps their register and sounds unlike the others. These rules come from the app's voice prompts (`build_voice_profile_prompt.py` and `cast_voices_prompt.py`) and from `docs/voice-pipeline-redesign.md`.

## 1. Collect each character's lines

Run `mneme.py dialogue` (or `dialogue <chapter>`) to list the paragraphs that look like dialogue, with their ids. It finds paragraphs that start with a dash and paragraphs with quotation marks. Quoted paragraphs are only candidates: many are titles, quoted phrases or thoughts.

For each line decide: is it speech, a thought, or not dialogue; who says it (use the glossary's character names); and to whom. Read the narration around it for who is talking when there is no speech tag. Write the result to `work/lines.md`, one section per character, with the line ids, for example `[03:p041] to Kerry`. Lines you cannot attribute go under "Unknown". For a long book, use subagents per group of chapters.

## 2. Profile each character (from all of their lines at once)

Read all of a character's lines in book order. Describe the voice across the book, not one scene: a feature seen once is a moment, not a voice. Every feature must be visible in lines you can cite. Do not project features from role, profession or class: a teacher who speaks with a village accent has a village voice.

Look for:
- emphatic particles, modal markers, sentence-final tags;
- deliberate non-standard spelling (eye-dialect) and non-standard grammar (a foreigner's broken cases, a child's syntax, dropped articles, tense confusion);
- signature patterns: tic phrases, hesitation markers, stutters, fragments, run-ons, repetitions;
- switching to other languages, and what it signals;
- stable sociolect by class, era, region or profession, in both vocabulary and sentence habits (the scientist hedges, the peasant is concrete, the soldier is terse, the courtier indirect);
- address forms (formal or familiar pronouns, titles, diminutives), and how others address them;
- changes of register with particular people or situations.

Describe speech from speech lines. Use thoughts only to note where the inner voice differs in a way the translator should keep.

For each feature, decide the move:
- **MIRROR**: carry it over directly (non-standard grammar, tics, signature phrases, stutters, fragments, repetition, switching language). The form may change (case errors in the source become article or preposition errors in English), but the brokenness carries over. Keep foreign phrases as they are, unglossed unless the original glosses them.
- **RECAST**: use an English equivalent (source-specific particles and honorifics, archaic words, regional vocabulary).
- **WATCH**: name the trap (anachronisms, the wrong regional accent, stagey foreign accents, inline glosses, softening a sharp tone, expanding clipped orders, modern slang).

Eye-dialect is decided per character: sparse equivalent eye-dialect for a regional or class accent within the language (one or two marks per sentence); grammar errors, not phonetic spelling, for a foreign speaker's accent.

## 3. Look at the whole cast, then write the briefs

First write `voices/_cast.md`: group the characters whose English voices could collapse into one (same register, rhythm and markers). For each group, say what separates them in the source lines, and name the English markers you will give each so they stay apart. Keep it short.

Then write one file per speaking character: `voices/<english-name>.md`, where the file name is the character's English glossary form in lower case with hyphens (`Old Marta` → `voices/old-marta.md`). The script uses this name to list the briefs a fragment needs.

Before writing, read the character's lines word by word again and count how many lines carry each marker. What runs through most lines *is* the voice: the brief must say so plainly and the sample must show it. Keep apart what is occasional (eye-dialect in one scene) and what runs through most lines (dialect words and grammar).

Format, about 100 words, in English:

```markdown
# Old Marta

Source name: Marta (glossary). Lines: 34, chapters 2–11.

Voice: A village woman who speaks dialect in nearly every line (dialect words and non-standard agreement). In English, consistent country grammar and words in every sentence, readable, not phonetic spelling. Next to the healer she sounds plainer and older; never let her drift into neutral English.

In their voice (style only, don't reuse phrases):
"Them lot from the mill, they was never no good to nobody. You mind the goat and leave the talking to me."

Evidence: [02:p014] [05:p033] [09:p007]
```

- **Voice** (one or two sentences, then one or two tips): who this person sounds like (social position, education, profession, age, region), how plain or elevated the vocabulary is, how formal they are, the two or three source markers that carry the voice and what they become in English, what must not be lost, and how they differ from the nearest voice in their cast group.
- **In their voice**: two or three sentences as this character would say them in English. Carry over what runs through their lines, at the same frequency (dense where they are dense). Something they could say in the book's world, but not a quote or paraphrase of their real lines, and no new plot facts. One sentence is enough for a character with very few lines.
- **Evidence**: a few line ids, so the user can check the brief against the source.

Leave out what applies to everyone (contractions in dialogue, natural idiom, no anachronisms).

## 4. Test the briefs, then stop for review

Translate one short exchange per main character with its brief, following `translation-rules.md`. Read the results as a cast. Fix a brief when its passage is **flattened** (an educated speaker made casual, a plain speaker made literary, a rural voice made standard, an address form dropped), **sounds like another character**, or goes against the brief in another way. Never count it as a fault that the translation stays close to what the source says.

Put the test passages in `voices/_samples.md` (source, then English) so the user can judge the briefs by their effect. Then stop: ask the user to read `voices/` and `voices/_samples.md` and edit or approve. When they approve, run `mark voices reviewed`. A brief the user edited is their decision: keep it faithful to their changes.
