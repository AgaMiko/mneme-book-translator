# Translation rules

Read this file before translating the first fragment of a session, and keep to it for every fragment. The text below is the one-step translation prompt of the Mneme app (`backend/app/generation/prompt_manager/prompts/translate_fragment_prompt.py`: `RULES_CORE`, `STYLE_SHEET` and `ONE_STEP_TASK`), rendered for English. If the target language is not English, read "English" as the target language, and use that language's usual spelling and quotation marks in place of the British English style sheet.

The "voice profiles" mentioned below are the briefs in `voices/`. The "glossary" is the accepted rows of `glossary.md`.

## Translation rules

1. **Translate meaning, not words.** Every piece of content in the source (each event, image, fact, line of dialogue and feeling) is in the translation, and the translation adds no content the source does not have. Wording and sentence structure are free: words, clauses and sentences do not need to match the source one to one. Do not add content to make the text flow (no "easy now", "trust me", "my friend" unless the source has them), and no images, details or stronger wording than the source has; better flow comes from restructuring what the source says.

2. **Idiom for idiom.** Use the English idiom that does the same job, not a word-for-word copy.

3. **Living images.** If a source image sounds old or odd in English, use the image English writers use today.

4. **Plain words over learned words in narration.** Where the source uses formal or Latinate words casually, English fiction prefers shorter, plainer words.
   **Exception:** when a character's voice profile names a Latinate, clinical, elevated, archaic or broken register, follow the profile for that character's lines and for free indirect thought in their point of view. A character who speaks in clinical Latinate terms keeps them ("haemorrhage", "fabricates images"). A character with broken non-native grammar keeps the broken grammar.

5. **Verbs over abstract nouns.** Break long abstract noun phrases into verbs.

6. **Contractions in dialogue**, unless the character's voice profile says otherwise (formal, ritual or archaic speech).

7. **Names in their glossary form.** If the source changes a name's ending by case or adds a suffix to it, still write the glossary form. Show possession with English 's. Short forms the glossary lists are separate names; keep them as they are.

8. **Glossary terms.** For every glossary term in the source, use the glossary's target form exactly. Do not vary it. A term's notes may say when an ordinary word is NOT the glossary term (a literal object that shares its name with a lore term). For a new name or term in the same family as glossary terms, follow the same strategy, and report it as a term_choice note.

9. **Voices.** The source text comes first: translate what the character says, with nothing added or lost. The character's voice profile guides *how* you say it in English: which words to reach for (plain, educated, technical, rural, old-fashioned) and how to build the sentence, so each character keeps their register and sounds unlike the others. Do not add markers the source line does not carry. A brief may end with a short sample in the character's voice: use it to hear how they sound, never copy its phrases into the translation.

10. **Free indirect thought** stays in past tense. Only direct thought is in italics.

11. **Author placeholders** (xxxxxxx, [xxxx]) are copied exactly and reported as placeholder notes.

12. **Source typos.** Translate an obvious typo as the word that was meant. If you had to guess what was meant, add a source_typo note. Do not report single-letter slips.

13. **No modern idiom in narration** (no "light years", "on the same page", "reach out").

## Book style sheet

- Spelling: British English.
- Dialogue: the source's dialogue punctuation (dashes, „…“, »…« or other marks) becomes English double quotes. Em dashes (—) only for interruptions and sharp asides.
- Ellipses (…): keep in dialogue where a speaker trails off or falters, and at real moments of fear. In narration, prefer a full stop, a comma or a different sentence.
- Units: narration uses traditional units (paces, feet, miles, pounds); measurements on charts, documents and instruments stay as in the source (°C). Round converted numbers naturally ("a good five paces"), don't give false precision.
- Chapter headings: a paragraph may hold the chapter heading: the point-of-view name, the chapter line (number and title), and an epigraph with its attribution line. Translate all of it and keep its line breaks; the chapter word becomes "Chapter". Epigraphs keep their own register; attribution lines start with an em dash.
- Scene breaks: keep a "***" paragraph as "***". If a scene break carries a point-of-view name (e.g. "*** Kerry"), write "***" and put the name in the same paragraph on a new line in italics: "***\n*Kerry*".
- Mind-to-mind speech: the point-of-view character's words in double quotes, the other speaker's words in italics, as in the source.
- Keep italics for thoughts, letters and quoted documents where the source has them. Remove markdown escape backslashes (\!, \.).
- Epigraphs, letters, scripture and quoted documents keep their own register. Rhymes and wordplay: report as wordplay notes.

## Your task: translation (one pass)

Translate the source paragraphs into fluent, natural English, the way a skilled English novelist would have written this passage, so it reads like a published fantasy novel and not like a translation. There is no draft before you and no editor after you: what you write is the final text. Account for every sentence of the source: nothing dropped, nothing added. Apply the rules and the style sheet above, including names, glossary terms, quotes, units and scene breaks.

Work from the meaning, not the words. Read each source paragraph, understand what it says and how it says it, then write the best English version of that. You may reorder, merge, split or rebuild sentences, change parts of speech, and replace any phrase that sounds translated with what a native writer would say. Keep:
- the meaning: every event, image, fact, line of dialogue and feeling, with nothing added and nothing lost;
- the author's style: tone, register, pace, how plain or ornate the prose is, the point of view and the mood of each scene;
- each character's voice, as the voice profiles describe.

Check every paragraph against the source when you are done.

- Vary sentence openings. Avoid runs of "She… She… She…" or "He… He…".
- Sentence rhythm: vary sentence length. Translating sentence by sentence tends to give runs of sentences of about the same length; mix short, medium and long ones so the prose has movement. Short sentences for impact and action, longer ones for reflection and description, as the author does in the source. Keep the author's deliberate effects (a run of short fragments, a long breathless sentence).
- Word repetition: do not use the same word again within a few lines. The source may avoid repetition through inflection; English needs a synonym, a pronoun or a rebuilt sentence. Keep a repetition only where the source repeats on purpose (anaphora, a refrain, emphasis), and keep glossary terms and names exactly as they are.
- Meaning wins over variety. A precise word used twice is better than a synonym that shifts the meaning: soldiers are not "guards" or "infantrymen", patients are not "sick men", "the shrine" is not "a shrine". Prefer a pronoun or a rebuilt sentence to a looser synonym. Do not add images, details or intensity to vary a sentence ("from her knees" does not become "from the muck"; "angry shouts" do not become "ragged screams").
- Merge or split sentences for English rhythm. Break up long chains of clauses carried over from the source.
- Fix stiff or word-for-word phrases. No modern slang in narration.
- Ellipses: keep them in dialogue at hesitation or fear; trim them from neutral narration.
- Vary dialogue tags and prefer action beats; don't repeat "muttered" or "murmured" within a few lines.
- When two characters of the same gender talk, make sure the reader can tell who speaks. You may add a minimal clarifying beat (a name, "he said"). Report every such addition as an added_clarification note.
- Do not flatten voices. The source line comes first; the voice profile guides word choice and sentence structure in that character's lines, so they keep their register and sound unlike the others.
- Keep glossary terms, names, placeholders, epigraphs and letters exactly.
- She/He openers: vary with the character's name, a participial or prepositional opener, object-first order, merging two short sentences, or starting with the action. Don't fall into a new pattern: use at most one participial opener ("Turning, she…", "Sitting on the cot, she…") per paragraph, and keep simple "She did X" sentences where they read best.
- Ellipses: keep only where a speaker trails off or falters, or at a real moment of dread. Never for mood alone.
- Em dashes: keep for interruptions and sharp asides; use commas, colons, semicolons or full stops elsewhere.
- Stock phrases (the weight of, a beat, ghost of a smile, a flicker of, a wave of, couldn't help but, suddenly…): replace with something concrete, or cut.
- Also fix clunky lines (especially converted units), long clause chains and repeated dialogue tags.

Add a note only when the author needs to know or decide something, and report every added clarifying beat as an added_clarification note.

Return one paragraph for each source paragraph, with the same id, in the same order. Never merge or split paragraphs across ids.

## Translator notes

The rules above ask for notes in some cases. Add each one as a line in `notes.md`, under a heading for the fragment:

```
## 03-2
- [p014] source_typo: "…" read as "…" (the source has an obvious slip).
- [p020] added_clarification: added "Kerry said" so the reader knows who speaks.
```

Kinds, as in the app: `source_typo`, `continuity`, `ambiguity`, `wordplay`, `placeholder`, `added_clarification`, `term_choice`. Add a note only when the author needs to know or decide something.
