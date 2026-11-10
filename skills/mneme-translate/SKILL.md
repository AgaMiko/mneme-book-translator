---
name: mneme-translate
description: Translate a fiction manuscript (novel, novella, short stories) into English with Claude Code itself, following the Mneme workflow. The manuscript is split into chapters and fragments of about 1,200 words, then come a reviewed glossary of names and invented words, voice briefs for the characters, a fragment-by-fragment translation, checks and export. State is kept in plain files, so a run can stop and continue. Use when the user asks to translate a book, novel, manuscript or chapters, or to continue a Mneme translation in a folder that has mneme.json.
argument-hint: "<manuscript.docx|.md|.txt> [source language]"
allowed-tools: Bash(uv run ${CLAUDE_SKILL_DIR}/scripts/mneme.py *) Bash(python3 ${CLAUDE_SKILL_DIR}/scripts/mneme.py *)
---

# Mneme: translate a novel with Claude Code

You translate the book yourself. No API keys, no database, no Docker. The helper script does only what needs exact counting: splitting, fragment boundaries, merging translated paragraphs, checks and export.

The workflow is the one of the Mneme app (this skill's repository). Its rules are in `references/`; read each one when you reach its step, not all at once.

## The helper script

```bash
uv run ${CLAUDE_SKILL_DIR}/scripts/mneme.py --dir <book folder> <command>
```

Without `uv`, use `python3` in place of `uv run` (reading a `.docx` then needs `pip install python-docx`). Run `--help` for all commands. The ones you use most: `status`, `fragment <id>`, `save <id> <file>`, `check`.

## The book folder

Everything lives in one folder the user chooses (ask; default: a new folder named after the book, next to the manuscript). Never write into the manuscript itself.

```
mneme.json               state: chapters, fragments, step status (written by the script)
source/chapter-NN.md     source text, one [id] block per paragraph
glossary.md              the glossary table (you write it; the user reviews it)
voices/<name>.md         one voice brief per speaking character; _cast.md, _samples.md
passages.md              special passages: rule, status, first translation
translation/chapter-NN.md  the translation, same [id]s as the source
notes.md                 translator notes for the author
work/                    your scratch files (glossary notepad, attributed lines, fragment drafts)
check-report.md          output of `check`
export/                  the finished book
```

Paragraph files use one format: a line `[p012]` (or `[title]` for the chapter heading), then the paragraph text. The translation of a paragraph keeps its id.

## Starting or continuing

If the folder has `mneme.json`, run `status` and continue from the first step that is not done. Tell the user where you are in one or two lines. Otherwise:

1. **Split.** Ask for the source language if it is not clear from the text, then:
   `prepare <manuscript> --source-language pl --title "<title>"`.
   Known letter lists: `pl`, `de`, `kn`. For another language pass `--letters "<letters that must not stay in English>"`. Look at `source/chapter-01.md` and the chapter list from `status`. The script finds chapters by the Heading 1 style in a `.docx`, `#` or `##` lines in Markdown, and chapter words ("Rozdział 3", "Kapitel 3", "Chapter 3", prologue, epilogue). If the chapters come out wrong, make a `.md` copy of the manuscript with each chapter heading on its own `## ` line, and run `prepare` on that copy with `--force`.

Then follow the steps below in order. Record each step with `mark <step> <state>`.

## Steps

### 2. Glossary, then stop for review

Follow [references/glossary.md](references/glossary.md). Build `glossary.md` chapter by chapter, review it yourself, then **stop**: show the user a short summary and ask them to review `glossary.md`. Do not start the voices until the user says the glossary is ready. Then set kept rows to `accepted` and run `mark glossary reviewed`.

### 3. Voices, then stop for review

Follow [references/voices.md](references/voices.md): collect each character's lines (`dialogue`), profile them, write the cast notes and one brief per character, translate a short test exchange per main character, then **stop** and ask the user to review `voices/`. Run `mark voices reviewed` when they approve.

### 4. Special passages: scan

Follow steps 1 and 2 of [references/special-passages.md](references/special-passages.md): list verse, documents that may hide a message, and plot wordplay in `passages.md`, with their rules. Run `mark passages scanned`. Tell the user what you found in a few lines; no need to wait.

### 5. Translate

Read [references/translation-rules.md](references/translation-rules.md) once per session, and keep to it for every fragment. Then for each fragment in book order (`status` gives the next one):

1. `fragment <id>` prints the fragment: its source paragraphs, the end of the previous text (source and current English), the start of the next one, the glossary terms it found, and the voice briefs to read.
2. Read the voice briefs it lists, and any brief of a character who speaks or is named in the fragment that the script missed. Use the glossary's English forms exactly, also for terms the script did not list.
3. Translate in one pass, straight into the final English, following the rules. Write the result to `work/<id>.md` as the same `[id]` blocks, in the same order, one block per source block.
4. `save <id> work/<id>.md`. It refuses a fragment whose ids do not match, and prints problems it finds (leftover source letters, dialogue dashes, missing placeholders). Fix those and save again.
5. Add any translator notes to `notes.md` (format in the rules file).

Work through the book without stopping, unless the user asked for a part only ("translate chapters 1–3"). Every few chapters, give the user a one-line progress update. If the context grows long, finish the current fragment, save, and continue: all state is in files, so nothing is lost.

For a long book you may translate chapters in parallel with subagents. Give each subagent the book folder, the chapter's fragment ids, and tell it to read `references/translation-rules.md`, `glossary.md` and the voice briefs, and to use `fragment` and `save`. The first fragment of each chapter then has no English for the previous chapter's end; that is acceptable. Check the results with `check` afterwards.

Run `mark translation done` when `status` shows every fragment translated.

### 6. Check

1. `check` writes `check-report.md`: untranslated paragraphs, leftover source-language letters, dialogue dashes, markdown escapes, missing placeholders, glossary terms whose agreed English is missing, and style numbers per chapter (She/He sentence openers, ellipses and em dashes per 1,000 words, stock phrases) against the app's targets.
2. Fix real problems in `translation/chapter-NN.md`. A glossary warning can be a false alarm (a pronoun, a short form, an inflected form the script matched): read the paragraph before changing it. For a chapter over the style targets, revise the sentences the targets name, as the rules file describes.
3. Check the special passages: steps 3 and 4 of [references/special-passages.md](references/special-passages.md).
4. Run `check` again, then `mark check done`. Report to the user: the problems fixed, what is left, the passages that were corrected or failed, and the notes in `notes.md` that need the author.

### 7. Export

`export` writes `export/<title>.md`, plus `.docx` and `.epub` when `pandoc` is installed. It refuses while paragraphs are untranslated; `export --draft` marks the gaps and adds `_DRAFT` to the file name. Do not export a final version while a special passage has status `failed`, unless the user says so. Run `mark export done` and tell the user where the files are.

## Rules for working with the user

- Stop after the glossary and after the voices. These are the two review points, as in the app.
- The user's edits to `glossary.md`, `voices/` and `translation/` are their decisions. Do not overwrite them; if a later step seems to conflict with one, ask.
- If the user changes a glossary English form after translation started, replace the old form in `translation/` and run `check`.
- Keep messages to the user short and plain: what was done, what needs them, where the files are.
