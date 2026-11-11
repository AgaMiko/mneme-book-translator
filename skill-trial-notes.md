# mneme-translate: notes from the trial run (Zaplataczka, chapters 1–2)

What to improve in `skills/mneme-translate`, found while running it on a real manuscript. Book folder: `~/Downloads/Zaplataczka/`.

**Status:** all 30 are addressed in `mneme.py`, `SKILL.md` and `references/`. Things to know:
- 5: the tail limit is now 400 words in the skill; the app's fragmenter still uses 250.
- 12: `dialogue --skeleton` writes a draft with one line per candidate, and `dialogue --group` builds `work/lines.md`. Choosing the speaker is still the model's job.
- 15: notes now go to `notes/chapter-NN.md`; `check` joins them into `notes.md`, but never over a hand-written `notes.md`.
- 16: "woven" for "weave" is still flagged (an irregular English form).
- Found while fixing: bold-italic text such as `***J**ak` (the first letter of the hidden message in Einard's letters) was split into fake scene breaks. It is now kept as it is.

## Splitting (`prepare`)

1. **Front matter becomes a chapter.** The manuscript starts with `# Zaplataczka`, the author's name, then an empty `# ` line. The author line and the empty heading became "Chapter 1" (3 words), so every real chapter was numbered one too high. Fix: skip empty headings, and treat text before the first chapter word ("Rozdział", "Prolog") as front matter, not a chapter.
2. **The first heading is taken as the book title, even when `--title` is given.** With the front matter removed, the line `# *Mira* **Rozdział 1** …` was eaten as the title, and chapter 1 lost its `[title]` paragraph (`mneme.py` line ~233). Fix: when `--title` is passed, or the heading contains a chapter word, never treat it as the book title.
3. **Escaped scene breaks split into two paragraphs.** Word-to-Markdown exports write scene breaks as `### **\*\*\***`. The script made two paragraphs of it (`### **\*\*\` and `***`), so every scene break would be translated and exported twice. Fix: recognise `***` with markdown escapes, bold and heading marks around it, and the `*** Name` form (`### **\*\*\* Kerry**`, `### **\*\*\*** **Kerry**`).
4. **`prepare --force` leaves stale files.** After a re-split to 31 chapters, `source/chapter-32.md` from the earlier split stayed. Fix: clear `source/` on `--force` (and refuse `--force` once `translation/` has files).
5. **Tiny tail fragments.** Chapter 1 ends in a 282-word fragment (01-4). Merge a tail under ~400 words into the previous fragment.
6. **The SKILL.md remedy for a bad split is not enough here.** It says "make a `.md` copy with each chapter heading on a `## ` line", but the problems above are front matter, the title and scene breaks. Add a short "check the split" list: chapter 1 is the real first chapter, each chapter has a `[title]`, scene breaks are single `***` paragraphs.

## Glossary

7. **Inflected forms are missed when the ending changes.** "choroba pyłowa" was not found in "chorobę pyłową": the matcher allows extra letters at the end, but Polish changes the last letters. Fix: match on a stem (drop the last 1–2 letters of forms of 5+ letters), or tell the model to list every inflected form in Forms seen.
8. **Lore terms that are also everyday words match everywhere.** "Dłonie" (the Hands, a name for Weavers) matches every "dłoni" (a hand), so `terms` and `fragment` list it for nearly every fragment. Fix: an option per row to match case-sensitively, or the skill should tell the model to note it (done by hand here).
9. **Book title vs title of the edition.** The glossary had to hold the book title ("Zaplataczka" → The Weaver), but `export` uses the `--title` passed to `prepare` (the Polish title). Add `--target-title` or read it from the glossary.

## Voices

10. **`dialogue` without a chapter prints the whole book** (138 KB for this manuscript). For a trial or a big book that floods the context. Accept a range (`dialogue 1-2`).
11. **Minor speakers have no place.** Briefs are found by glossary name, so unnamed speakers with a strong voice (two tavern men in rural dialect in chapter 2) can't get a brief. I put their guidance in `_cast.md`, but `fragment` doesn't list `_cast.md`. Fix: have `fragment` always list `voices/_cast.md`, or allow briefs like `voices/tavern-men.md` with a "matches" line.
12. **Voice attribution is fully manual.** `dialogue` gives candidates, but writing `work/lines.md` for a whole book is a big job that the script could help with (e.g. a skeleton file with ids per chapter, so the model only fills in the speaker).

## Translate

13. **Ids shift silently after a re-split.** After fixing the scene breaks, ids in chapter 1 moved by one or two. Nothing was translated yet, so it was harmless, but notes, `lines.md` and voice evidence written before the re-split point at the wrong paragraphs. `prepare --force` should warn when `work/` or `voices/` already exist.
14. **`fragment` prints a long header.** All glossary rows and notes are repeated for every fragment, including false hits like "the Hands". Fine for 7 fragments; for 99 fragments it adds up. Print only Source → English, notes for new terms.
15. **Translator notes and parallel subagents share one `notes.md`.** Two writers append to the same file; easy to clobber. Use `notes/chapter-NN.md`, merged on export or check.

## Check

16. **Glossary check gives mostly false alarms.** 21 warnings in chapter 1, none real:
    - "the Medical Corps": the source line was "Mira, Korpus Medyczny" (no article in English). Compare without leading "the".
    - "Plainbands" vs "Plainband": singular/plural of the English form. Compare on a stem.
    - "weave" vs "weaving": same, English inflection.
    - "Jen" (a short form the rules say to keep) is matched to "Jenna" and flagged. A Forms-seen entry that is itself a separate English name needs its own mapping.
    - "Dłonie" matched every "dłoni" (hand): 16 of the 21 warnings.
    - "komendantka" where the translation used Agata's name. Unavoidable, but the report could group these per term with a count, so one false term doesn't drown the list.
17. **Ellipsis target ignores the source.** The source has many ellipses in dialogue (hesitation, speeches broken by Mira's thoughts). After trimming every narration ellipsis except moments of dread, chapter 1 is still 3.9 per 1,000 words (target 3.0). The report should split dialogue and narration, or show the source's rate next to the target.
18. **Formatting glitch in the style line:** "She/He openers 18.0 (target ≤ 15.0) ⚠%" — the % lands after the warning sign.
19. **The stock-phrase check flags literal uses.** "with a wave of her hand" was flagged as the stock phrase "a wave of". Skip it when followed by "hand"/"her hand", or list it as "check" rather than a warning.
20. **`check` with no chapter reports every untranslated chapter.** For a partial run the report is mostly "Not translated yet." Only list translated chapters, with one summary line for the rest.
21. **Glossary check is fooled by forms that are not names.** I listed "wuj" (uncle) as a form of Tyrel; the check then wanted "Tyrel" wherever the narration says "his uncle". The glossary rules should say: Forms seen holds names and inflections only, not common nouns that refer to the character.

## Export

22. **A partial run can't export just what is done.** `export --draft` writes the whole book, with "[Untranslated…]" markers and 29 chapters of Polish chapter headings. For a trial I cut chapters 1–2 out by hand. Add `export --draft --chapters 1-2`.
23. **Chapter heading layout.** The POV name becomes the `#` heading ("# *Mira*") and "Chapter 1" a bold line under it, so a table of contents in .docx/.epub would read "Mira, Einard, Mira…". Make "Chapter N" the heading and the POV name a line under it.
24. **Export title is the source title.** See 9.

## From the chapter 2 subagent

25. **Steps start at "### 2. Glossary"** in SKILL.md; "1. Split" is in a numbered list in another section. Make Split "### 1." so the numbering is consistent.
26. **The `[title]` paragraph is one line.** The source heading (POV, chapter line, epigraph lines, attribution) arrives on one line with double spaces between parts, so the translator has to guess the layout the style sheet asks to keep. `prepare` should split the heading into lines at the italic/bold run boundaries.
27. **`fragment` repeats the full Polish title paragraph in every fragment's header line.** Print "chapter 2 (Einard)" instead.
28. **Subagents are not told what not to run.** SKILL.md's parallel section should say: subagents do not run `check`, `mark` or `export`, and append to notes only under their fragment headings.
29. **Name typos in the source.** Rule 12 covers typos in general; add a line: a misspelt name ("Eianrd") is written in its glossary form, with no note.
30. **Notes order.** Say "notes in paragraph order within a fragment".
