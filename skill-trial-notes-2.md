# mneme-translate: notes from the second trial run (Zaplataczka, chapters 1–2)

Second run of the skill after the fixes in d017462. Book folder: `~/Downloads/Zaplataczka-run2/`. Manuscript: `~/Downloads/Zaplataczka_101126.md`. Chapter 1 translated in the main session, chapter 2 by a subagent.

Each point: what happened, then the fix.

## Split

1. **The split worked first time.** Front matter, the `[title]` block with one part per line, the `### **\*\*\***` scene breaks: all correct, no re-split needed. No fix; recorded so the earlier fixes count as checked.
2. **The split checklist says "no leftover `\`", but `prepare` keeps escapes in body text.** Chapter 2 has `Pochodnia\!`, `Wracamy\!` and eight more. Read strictly, the split fails the checklist; in fact the translation step removes them (style sheet) and `check` flags any left. Fix: in SKILL.md step 1, say the checklist is about headings and scene breaks, and that `\!` inside paragraphs is fine. Better: have `prepare` drop markdown escapes from paragraph text, since they are never wanted.

## Glossary

3. **Match `case` cannot tell a term from a sentence-initial capital.** "Dłonie ścisnęły materiał fartucha" (01:p156, hands), "Gładka jak lód" (02:p009, smooth), "Ciało uderzyło o kamienie" (02:p099, a body), "Dłoń Tyrela" (02:p024) all start a sentence, so the `case` rows for the Hands, Smooths and the Body list them anyway. Fix: for `case` rows, skip a match that is the first word of a sentence (after `.`, `!`, `?`, `…`, a dash, a quote, or at the start of a paragraph), or add a Match value `mid` for that. Say in glossary.md that `case` still matches at sentence starts.
4. **No step tells the model to look for an existing translation or glossary.** The Downloads folder has `Zaplataczka_EN_final.docx` and the first trial's `glossary.md`. The glossary rules have "Starting from an existing glossary", but SKILL.md step 1 never asks "is there an earlier glossary or translation of this book?". In this run I built the glossary fresh on purpose. Fix: in SKILL.md "Starting or continuing", ask the user once whether a glossary or an earlier translation exists, and point to that section.
5. **The book title row has no type.** The rules say to decide the English title with the user, but the type list has nothing for the book's own title, so it goes in as `other`. `prepare --target-title` already holds it, so the row is only for the reviewer. Fix: say in glossary.md that the book title does not need a row when `--target-title` was given.
6. **Verb rows next to noun rows.** Polish uses one root for Weaver / weave / weaving and Shaper / shape. I made separate rows (`Zaplatacz` → Weaver, `zaplatać` → weave) so the kinship rule holds. The check then wants the exact string "weave" in any paragraph with "zaplótł", so "wove" and "woven" flag (as in trial 1, point 16). Fix: let the English column hold several forms separated by `/` (`weave/wove/woven/weaving`), any of which satisfies the check; say so in glossary.md.

## Voices

7. **Unnamed speakers all land in one `Unknown` section.** `dialogue --group` put 24 lines in `Unknown`: the arguing adepts (ch1), the guards and the inn men and women (ch2). These are exactly the minor speakers voices.md says can get a brief (`voices/inn-folk.md`), but `lines.md` mixes them, so I had to go back to the source to sort them. Fix: in voices.md step 1, say to label unnamed speakers with a short role (`Inn man 1`, `Older guard`, `Red-haired adept`) instead of `Unknown`, and keep `Unknown` for lines where even the role is unclear. `--group` then gives each role its own section.
8. **`lines.md` holds ids only, no text.** To profile a voice "from all of their lines at once", I needed the lines themselves; `lines.md` gives `[01:p055] to Mira` and nothing else, so I read them in `source/` again. Fix: have `--group` copy the line text (the dialogue part, up to ~200 characters) after each id, as `lines-draft.md` already does.
9. **The skeleton is noisy for this book.** 115 candidates, of which 9 were narration with a quoted word (`„klasyk"`, `„Dłonie”`, `„Lordzik z Akademii”`). Marking them `not dialogue` is quick, so this is minor. Fix (optional): only take a paragraph with quotation marks as a candidate when the quoted span is more than three words or ends the sentence with a speech tag.
10. **The voices step has no word on how to describe a POV character who barely speaks.** Einard has two spoken lines; his voice in chapter 2 is his thought. voices.md says "Use thoughts only to note where the inner voice differs", which leaves his brief nearly empty. Fix: add one line: for a POV character with few spoken lines, describe the inner voice too, since free indirect thought carries most of their chapters.
11. **The test step does not say how long the test passages should be or whether they are reused.** I wrote four short exchanges in `_samples.md`; when I then translated the same paragraphs for real, I reused the sample wording. Fix: say in voices.md step 4 that 3–6 lines per main character is enough, and that the sample English may be reused or improved in step 5.

## Special passages

12. **`letters` works on whole paragraphs only.** The execution passage (02:p126) is a quoted text inside a longer paragraph; `letters 2 p126 p126` prints the letters of the whole paragraph, so the quote's own sentence letters must be picked out by hand. Fix: accept `--from "<first words>"` to start inside the paragraph, or a sentence range (`p126:6-9`).
13. **No format for "scanned, nothing found".** special-passages.md shows the format for a kept passage only. I wrote a short list of the rejected candidates. Fix: say what `passages.md` holds when nothing is kept (one line per checked candidate and why it has no rule), so a later session does not scan again.

## Translate

14. **The glossary `Notes` I wrote were shown back to me in every fragment, including a wrong one.** My note on Elantria said "Ela" was a nickname. It came from reading the source with `head -c`, which cut "Elantria" to "Ela". `fragment` showed the note and I caught it, so the feature works; the lesson is about the build step. Fix: in glossary.md "Building it", say to read whole chapters from `source/`, not truncated previews, before adding a form.
15. **Glossary terms that are everyday English words leak into the prose.** "Weave" is the glossary verb for zaplatać; the source also uses "lawirując" (threading between cots) and "wplotła" (put a flower in a plait), which I first wrote as "weaving" and "wove". A reader would take them as Dust-weaving. Nothing in the rules warns about this. Fix: add a line to translation-rules.md: do not use a glossary term's English word in its everyday sense nearby (here: weave, shape, the Hands), pick another word.
16. **`fragment` lists `the Hands` for a sentence-initial "Dłonie" (01:p156).** Same cause as point 3. It costs only a moment, but over 96 fragments it teaches the translator to ignore the list.

## Parallel subagent (chapter 2)

The subagent route worked: three fragments saved with no id errors and no `save` warnings, notes only in `notes/chapter-02.md`, nothing outside its chapter touched. Its points, checked against the files:

17. **Nobody creates `notes/`.** The subagent and I both ran `mkdir`. With several subagents this is a harmless race, but it is extra manual work the docs don't mention. Fix: `prepare` creates `notes/` (as it does `work/` and `voices/`).
18. **`save` paths are relative to the book folder, and SKILL.md doesn't say so.** The subagent read the code to be sure. Fix: one line in step 5.4.
19. **Subagents get no style feedback, and it showed.** The subagent wrote `...` (three full stops), I wrote `…`; nothing caught the mix until I looked at `check` output by hand (20 in chapter 2). It also cannot see the She/He or ellipsis numbers. Fix: `save` prints the fragment's style numbers, and the style sheet names one ellipsis character (`…`); `check` flags `...`.
20. **`_samples.md` and rule 9 pull in two directions.** The samples are approved translations of real lines; rule 9 says never copy a sample's phrases. The subagent rewrote them. Same as point 11: say whether reviewed sample lines are to be reused.
21. **`added_clarification` covers only speaker tags.** In 02:p081 the subagent wrote "His own father" so the reader knows it is Einard's father, not Tyrel's. Fix: widen the kind to any added word that settles who or what is meant.
22. **Brief quality slipped past my own review.** `tyrel.md` says "orders and nothing else", but 02:p066 and p068 explain a plan. voices.md asks to count markers per line, and I did not. Fix: in voices.md step 3, ask for the count to be written in the brief ("bare imperatives in 10 of 13 lines"), so the claim is checked when written.

## Check

Numbers after fixes: chapter 1, 0 glossary warnings, She/He 14.9%, ellipses 4.6 per 1k (narration 1.6, dialogue 3.0; source 6.6). Chapter 2, 1 glossary warning (false), She/He 15.0%, ellipses 4.9 per 1k (narration 1.9, dialogue 2.9; source 8.8).

23. **A prefix in the English column causes false alarms.** I wrote `House Viathel` as the English for Viathel; "the Viathel residence" and "the Viathels' main seat" (02:p125, p128) were then flagged. My row was wrong, but glossary.md doesn't warn about it. Fix: say "English holds the bare name; put 'House X' or titles in Notes".
24. **The English check ignores case, so `case` rows are only half-checked.** Chapter 1 shows no warning for "Dłonie" at 01:p156 because "hands" satisfies "the Hands". That hides the false alarm, but it would also hide a real miss (lore "the Hands" written as "hands"). Fix: for rows with `case`, match the English with case too.
25. **"woven" is still flagged for `weave`** (02:p105). Known from trial 1 (point 16); see point 6 for a fix.
26. **The ellipsis warning is on the total, not on narration.** Both chapters show ⚠ at 4.6 and 4.9 although narration is 1.6 and 1.9 and SKILL.md says faltering dialogue may stay above. The warning stays however well the narration is trimmed. Fix: put the target and the ⚠ on narration; show dialogue with the source rate only.
27. **The stock-phrase check flags literal "suddenly".** "Tyrel stopped so suddenly that Einard almost walked into him" (02:p018, from "tak nagle"). Fix: flag only a sentence that opens with "Suddenly".
28. **She/He target sits right at the edge.** Chapter 1 went from 17.9% to 15.1% to 14.9% one sentence at a time. Rewriting openers to pass a number risks the "new pattern" the rules warn about (I used "Mira" as an opener four times). Fix: show the paragraphs with the most She/He openers in the report, so the revision goes where the runs are, not anywhere.

## Export and state

29. **No guidance on `mark` for a partial run.** SKILL.md says `mark translation done` only when every fragment is done, and `mark check done` / `mark export done` after them. For a run of chapters 1–2 I left translation, check and export as `todo`, so `status` now says nothing about what was checked. Fix: say how to record a partial run (`mark translation 1-2`, or leave todo and rely on `status`), and have `check` record which chapters it last checked.
30. **`pandoc` missing gives only `.md`.** The message is clear. Fix (small): add the install line (`brew install pandoc`) to SKILL.md step 7.
31. **Scene breaks export as `\* \* \*`.** Renders fine as a rule break in Markdown and pandoc; it looks odd in the raw `.md` a user may open. Fix (optional): write `* * *` on its own line without escapes, which Markdown also reads as a break.

## Top problems (summary)

1. `case` matching cannot tell a term from a sentence-initial capital, and the English check ignores case (points 3, 16, 24).
2. Unnamed speakers all fall into `Unknown`, and `lines.md` has no line text (points 7, 8).
3. Subagents get no style feedback; the ellipsis character is not fixed (point 19).
4. The ellipsis warning sits on the total, so it can never clear for a book with faltering dialogue (point 26).
5. Unclear whether reviewed `_samples.md` lines are reused (points 11, 20).
6. Glossary terms that are everyday English words ("weave") leak into the prose in their everyday sense (point 15).
7. One English form per row: "woven", "House Viathel" (points 6, 23, 25).
