# Voice pipeline redesign: collect all lines, then one profile call per character

Status: steps 1 (line finder) and 2 (attribution) built; step 3 next.

## Goal

Build each character's voice profile from all of their dialogue at once. Today Pass 2 builds it window by window and rewrites a short summary as it goes, so the result depends on the order of windows and loses earlier evidence.

New flow:

1. **Find dialogue lines** (code, no LLM).
2. **Attribute lines** (new Pass 1, LLM): who says each line, and to whom.
3. **Build profiles** (new Pass 2, LLM): one call per character with all of their lines. Writes the observation, the strategy and picks the reference passages.
4. **Translate reference passages** (unchanged).

The separate passage-selection call, the 8-passage candidate pool and the voice notepad go away.

## What the data looks like (Zaplataczka, latest upload)

- 107k words, about 3,900 paragraphs.
- About 1,400 paragraphs start with a dash (`–`). That is the dialogue convention: a paragraph starts with `– `, and narration inside it is set off with ` – ` (for example `– Rozeszły się. – Hania wzruszyła ramionami. – Po tym…`).
- About 240 paragraphs contain „…” quotes. Most of these are titles, quoted phrases or thoughts, not speech.
- About 28k words sit in dialogue paragraphs (including the narration inside them).
- Pass 1 currently maps 20 speakers. The most active one speaks in 115 windows; the median is 8.

So the whole book's dialogue is about 40k tokens. The largest single character fits in one call with room to spare.

## Step 1: find dialogue lines (code)

New module `app/services/dialogue_lines.py`.

- Work on `Paragraph` rows, not on word windows. Paragraphs already keep their breaks and order (chapter position, paragraph position).
- A paragraph is a **dialogue candidate** when it starts with a dash (`–`, `—`, `-`) or contains quotation marks (`„ ” " “ « »`).
- For dash paragraphs, split the text on ` – ` into alternating speech and narration parts (part 0 is speech, part 1 narration, part 2 speech, and so on). Store the speech parts joined as `speech_text`. The full paragraph stays the unit shown to the model, because the narration ("szepnęła", "wzruszyła ramionami") shows tone.
- Quote paragraphs are only candidates. The LLM in step 2 decides whether they are speech.
- Pure function, unit-tested on real Zaplataczka paragraphs, including edge cases: narration-only paragraphs that contain a dash, lines interrupted mid-sentence, a dash followed by `…`.

The unit of a "line" is one dialogue paragraph. A paragraph with two speakers is rare in this convention. When it happens, the model attributes it to the main speaker and the paragraph is marked `mixed`.

## Step 2: attribute lines (replaces current Pass 1)

### Calls

- Split each chapter into chunks of about 2,500 words at paragraph boundaries (instead of 500-word windows with overlap). There is no overlap, so no line is read twice.
- Each chunk is sent as all of its paragraphs. Dialogue candidates are numbered `L1…Ln`; narration paragraphs are shown without numbers as context.
- The last 3 paragraphs of the previous chunk come first, marked as context only, so the model knows who was talking.
- The glossary character list (ID, name, variants) is sent as now.

### Output schema (`identify_speakers_model.py`, rewritten)

Per numbered line:

- `line` (L-number)
- `kind`: `speech` | `thought` | `not_dialogue` (titles, quoted phrases, signs)
- `speaker_code` + `speaker_name`, or null when unknown. Characters are listed as short codes (`C1…Cn`) instead of UUIDs, to keep output small; the code and name are cross-checked.
- `addressee_code` + `addressee_name`, or null when unclear or addressing a group
- `confidence`: `clear` | `inferred` (no speech tag, worked out from turn order)

No verbatim quote is needed, because the code already has the text. The code/name cross-check stays. A line the model leaves out, or a chunk whose output can't be parsed, is stored with kind `unknown`. The old cross-window notepad is no longer used; the context paragraphs carry their stored attributions instead (`[Mira → Stein] – …`).

First trial (one dense chunk of Zaplataczka, 69 lines, gpt-6.1-sol): all 69 lines returned and matched, $0.05, 38 s. Estimate for the whole book: 48 calls, about $1.50.

### Storage

New table `dialogue_lines` (migration `0018`):

| column | notes |
|---|---|
| `id`, `book_id` | |
| `paragraph_id` | FK to `paragraphs`, unique per book |
| `kind` | speech / thought / not_dialogue |
| `speaker_glossary_entry_id` | nullable (unknown or not in glossary) |
| `addressee_glossary_entry_id` | nullable |
| `confidence` | clear / inferred |
| `mixed` | bool |
| `speech_text` | dash-split speech parts, for word counts |
| `word_offset` | start offset in the book (same counting as `fragmenter`) |

The chapter and position come from the paragraph.

### Keeping current consumers working

`window_speakers` is still read by translation (`speakers_for_range`), the voices list sort and the speakers review tab. After attribution, the code derives `window_speakers` rows from `dialogue_lines` using `word_offset` and the current window geometry. `quoted_evidence` is filled with the first 15 words of a line. Nothing downstream changes in this step.

Follow-up (separate change): translation fragments already know their `paragraph_ids`, so translation can read speakers directly from `dialogue_lines`. That is more precise than overlapping windows. After that, `window_speakers` can be dropped.

### Review UI

The speakers tab shows, per character: line count, word count, chapters, and lines grouped by addressee. A new row shows "lines with no speaker" with a count, and opens the list of those lines with their chapter, so the author can see what was missed. The glossary is not changed automatically.

## Step 3: build profiles (replaces current Pass 2 and passage selection)

### Calls

One call per character that has at least one `speech` line. Calls run in parallel (semaphore, default 4).

Prompt input:

- Character name, variants, and the glossary note if there is one.
- All of their lines in book order, each as `[L812 · rozdz. 4 · do: Hanna · inferred] – full paragraph text`. Chapter headings separate the chapters.
- A short list of who they talk to most, with counts (computed in code).
- The same instructions on observation and strategy as now (the existing prompt text about particles, eye-dialect, sociolect, MIRROR/RECAST/WATCH is moved over).
- Thoughts (`kind = thought`) are sent in a separate, marked section, because inner voice can differ from spoken voice. The prompt says to describe speech from speech lines only. If the inner voice differs in a way the translator should know, the model adds a short note about it to the observation.

**Large characters.** If a character's lines exceed a token budget (default 60k tokens), send a sample. The sample keeps lines spread evenly across chapters, makes sure every addressee appears, and prefers `clear` over `inferred` lines. The prompt says it is a sample and how many lines were left out.

**Small characters.** Characters with fewer than 3 speech lines are grouped, up to 8 per call. Their profiles are marked `low_evidence` in the UI.

### Output schema (`build_voice_profile_model.py`, new)

- `features`: list of `{feature, line_ids}`. Each named feature cites the lines that show it. The validator drops line IDs that are not this character's, and drops features with no valid lines.
- `register_shifts`: list of `{situation_or_addressee, change, line_ids}`. Optional.
- `source_voice_observation`: written from the features. No fixed length limit; the prompt asks for what the translator needs and no more, and keeps line-level evidence in `features`, not here. Translation sends this field to every fragment the character speaks in, so the comparison run (step 5) records the length of each field and the resulting translation prompt size.
- `target_voice_strategy`: same rules as today.
- `reference_passages`: list of `{first_line_id, last_line_id, why}`. The code builds the passage text from the paragraphs in that range, including other speakers' lines in between. This gives the translator the exchange, not isolated lines.

The number of reference passages uses the existing percentile rule in `compute_passage_counts`, but counted on **speech line count** instead of glossary mentions.

### Storage

- `character_voices`: keep `source_voice_observation`, `target_voice_strategy`, `status`, `needs_regeneration`. Add `evidence` (JSONB: features and register shifts with line IDs), `line_count`, `low_evidence`. `first_seen_window` / `last_observed_window` are replaced by the first and last chapter (computed, not stored).
- `voice_selected_passages`: keep. `source_candidate_id` becomes nullable. Add `first_paragraph_id`, `last_paragraph_id`.
- `voice_passage_candidates` and `voice_notepads` are dropped in the cleanup step.

### Existing profiles on a new run

Profiles with status `accepted` or `adjusted` are kept as they are, with their selected passages and translations. Only `proposed` profiles, and characters with no profile yet, are built. `rejected` profiles are not rebuilt. The author can flag a kept profile for regeneration to rebuild it from the new lines. Reset still clears everything.

### Regeneration

"Regenerate" becomes a single profile call for that character on the stored lines, then translation of its new passages. The code path that re-reads every speaker window goes away.

### Progress, resume, cost guard

- Progress counts characters done out of characters total, instead of windows.
- Continue skips characters whose profile was built in this run (new column `built_at` compared with the run start).
- The cost guard uses characters as units. The expected cost per character scales with that character's line tokens, so a main character does not trigger the pause early.

## Step 4: estimates and frontend

- `voice_extraction_estimate.py`: Pass 1 cost uses chunk count and paragraph text size. Pass 2 cost uses the dialogue word count (known after step 1, before any LLM call) and the number of characters.
- `VoiceView.tsx`: the Pass 2 progress label reads "characters" instead of "windows". The profile card shows line count, the chapter span, a `low evidence` badge, and each feature with links to its lines. Remove the window range text.
- `frontend/src/constants/voiceExtraction.ts`: window constants stay while `window_speakers` is still used.

## Cost, rough, for Zaplataczka

| | now | new |
|---|---|---|
| Pass 1 calls | ~270 windows × ~3.5k input tokens | ~45 chunks × ~5k input tokens |
| Pass 2 calls | ~180 windows with speakers × ~5k input tokens, in sequence | ~12 calls (20 characters, small ones grouped), ~40k dialogue tokens + ~4k instructions each, in parallel |
| Selection calls | 20 | 0 |

Both passes should cost less than half of today's, and Pass 2 should take minutes instead of running window by window.

## Order of work

Each step lands as its own commit and leaves the app working.

1. **Line finder.** `dialogue_lines.py` and tests on Zaplataczka paragraphs. No behaviour change.
2. **Attribution.** Migration for `dialogue_lines`. New Pass 1 prompt, schema and chain. Rewrite `speakers_service.extract_book_speakers` to use chunks. Derive `window_speakers`. Update the speakers tab. Old Pass 2 keeps working on the derived map.
3. **Profile building.** New chain, prompt and schema. New `voice_service.build_book_voices` with parallel calls, resume and cost guard. Update regeneration. Passage counts from line counts. Translation of reference passages unchanged.
4. **Estimates and UI.** As above.
5. **Comparison.** Run old and new pipelines on Zaplataczka and compare the profiles of the 5 most active characters side by side, blind, before removing the old path.
6. **Cleanup.** Drop `voice_passage_candidates`, `voice_notepads`, `speaker_notepads`, the extract-voices and select-passages chains, prompts and models. Update `backend/app/generation/README.md`.

## Decisions (2026-10-23)

1. **Thoughts:** sent in a separate section of the profile call. The profile describes spoken voice; a short note covers the inner voice when it differs.
2. **Speakers not in the glossary:** the speakers tab shows the count and the lines. No automatic glossary suggestions.
3. **Observation length:** no fixed limit. Field lengths and translation prompt size are checked in the comparison run.
4. **Existing profiles:** accepted and adjusted profiles are kept; proposed ones are rebuilt. Flag for regeneration to rebuild a kept one.
