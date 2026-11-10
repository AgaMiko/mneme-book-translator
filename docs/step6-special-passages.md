# Step 6 — special passages and author flags

Status: built 2026-11-10 for special passages. Translator notes (typos, ambiguities, added words) still live on each fragment and are shown in the Translation tab; they can move into the flags table later. The wider design is in [step5-translation-pipeline.md](step5-translation-pipeline.md), sections 9 and 10. This page describes what the code does and where it differs from that design.

## What a special passage is

A run of paragraphs whose wording follows a rule, so that a translation of the meaning alone breaks it.

| Kind | Rule the English must keep | How it is checked |
|---|---|---|
| `verse` | Poem, song, rhyme, chant: number of lines, rhyme scheme, line length. | Line count by code, rhyme and metre by a model. |
| `hidden_message` | Letters or words spell a message. When it is made of the first letters of sentences, lines, paragraphs, words or marked (italic, bold) words, the passage stores that unit. | By code when a unit is stored. By a model for any other rule. |
| `wordplay` | A pun, anagram or play on a name that the plot or a later line depends on. | By a model. |

For a first-letter message, the code accepts letters before and after the message, because a letter's salutation and sign-off are not part of it. How many is measured on the source, plus one on each side, so a short message cannot match by chance in the middle of a long letter. It also accepts a different wording of the message when a dependent paragraph states that wording in capitals in quotes (the decoding scene: "the letters spelt out: 'THEY'RE WATCHING ME'"). The passage's target message is then updated to that wording.

A passage can have **dependent paragraphs**: paragraphs of the same chapter that quote it, explain its rule or state what it hides. They are kept consistent with the translated passage.

## Flow

1. **Scan** (`special_passages_service.scan_book`). One call per chapter lists candidates: verse, quoted documents that could hide a message, plot-relevant wordplay. Every quoted letter of several sentences is a candidate, because a model reading for meaning does not notice an acrostic.
2. **Rule** (one call per candidate). The code computes the first letters of the candidate's sentences, lines, paragraphs, words and marked words (`passage_rules.letter_strings`) and gives them to the model with the whole chapter. The model says whether there is a rule, states it, gives the hidden message in the source and in the target language, and lists the dependent paragraphs. A candidate with no rule is dropped.
3. **Translate** as usual. Nothing changes in the fragment translation.
4. **Check** (`check_book`). For every passage whose paragraphs are translated, the English is checked against the rule.
5. **Correct.** When the rule is broken, a dedicated call translates the passage again with the rule stated, and returns patches for the dependent paragraphs. The attempt is checked the same way. A failed attempt is sent back with what was wrong, up to `PASSAGES_REWRITE_ATTEMPTS` times (default 3). The first attempt that passes replaces the text in the fragment's final rendition.
6. **Flag.** Each checked passage gets one row in `translation_flags`:

| Passage status | Meaning | Flag severity |
|---|---|---|
| `passed` | The normal translation keeps the rule. Nothing was changed. | `fyi` |
| `corrected` | It broke the rule. A new translation passed the check and replaced it. | `review` |
| `failed` | It broke the rule and no attempt passed. The first translation stays. | `blocking` |

The first scan starts by itself when a translation run starts and runs beside it. The check runs when the translation run ends. Both can be started by hand in the Review tab.

A passage is checked again when its own English changed since the last check, for example after its fragment was re-translated. A change to a dependent paragraph alone does not count, because two passages can share one (a scene that decodes both). Passages are checked one at a time, each on the current English, so two corrections in the same fragment do not overwrite each other. Checking a corrected passage again keeps its status, problems and versions.

## What the author can do

In the Review tab, per passage:

- **Accept** the current text.
- **Edit the English** of the passage and its dependent paragraphs.
- **Restore the first translation.**
- **Use this version**: any attempt, including those that failed the check.
- **Check again.**
- **Change the rule** or the message the English should spell. The passage is then checked again.
- **Not a special passage**: puts the first translation back and stops checking. A new scan does not list the passage again.
- **Mark a passage yourself**: chapter, first and last paragraph, kind, and optionally the rule. Without a rule, the first check works it out.

Export is refused while a `blocking` flag is open, unless the request has `draft=true`; a draft's file name ends in `_DRAFT`. The Translation tab waits for the passage list before it offers export links, then labels them "Draft PDF" and so on, and links to Review.

## Storage

- `special_passages`: kind, paragraph ids, dependent paragraph ids, rule, unit, source and target message, status, the problems found, `first_translation` (English before the correction), `checked_translation` (English at the last check or author action), and every attempt in `candidates`.
- `translation_flags`: severity, question, status (`open`, `accepted`, `changed`, `dismissed`), linked to the passage.
- `books.passages_state`: status and progress of the scan or check.

Paragraph ids are stored as text, because a chapter heading with an epigraph uses the id `title:<chapter id>`.

The corrected text is written into the fragment's final rendition, so the Translation tab and the export show it without any change.

## Differences from the earlier design

- The fragmenter is unchanged. The correction call works on the passage's paragraphs, so a passage may cross a fragment boundary.
- The best attempt is applied first and reviewed after. The earlier design held three candidates behind a blocking flag.
- Rhyme is judged by a model. A pronouncing dictionary does not know invented names.
- `gendered_grammar` and `quoted_document` are not kinds here. A quoted document is a scan candidate and is kept only when it has a rule.

## Limits

- Dependent paragraphs are found in the passage's own chapter. A scene in a later chapter that decodes a letter is not patched; the Review card shows the target message so the author can check that scene.
- The scan can miss a passage. Marking one by hand covers that.
- A hidden message in English often needs sentences merged, split or reordered. The card shows the source, the first translation and the new text side by side, and the model's note on what it changed.
- The prompts have not been run on a full manuscript yet. Code checks and the correction loop are covered by unit tests with the model calls faked.

## Settings

```bash
PASSAGES_MODEL=gpt-6.1-sol        # scan, rule, check and new translation
PASSAGES_REWRITE_THINKING=high    # the new translation has to fit letters or rhyme
PASSAGES_REWRITE_ATTEMPTS=3
```
