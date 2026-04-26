# Glossary extraction: schema + prompt + chain + domain stubs

What this drop adds:

```
backend/app/generation/
├── prompt_manager/
│   ├── models/extract_glossary_model.py     ← LLM contract (delta-shaped)
│   └── prompts/extract_glossary_prompt.py   ← prompt template + renderers
└── chains/extract_glossary_chain.py         ← schema + prompt + provider wired

backend/app/models/glossary.py               ← persisted ORM (NEW domain layer)
backend/app/services/glossary_service.py     ← delta application + orchestration
                                                (mostly NotImplementedError —
                                                 you fill these in)
```

Plus `INIT_PATCH.txt` — lines to add to `app/generation/__init__.py` to
expose the new chain and types at the package level.

## What's done

The **LLM-facing layer is complete and ready to call**:

- The schema implements everything we agreed on: delta-shaped output
  (new / extend / merge / refine), `TranslationRecommendation` as an
  object with `suggestion + proposed_target + rationale`, the 7-type
  closed taxonomy (cipher handling deferred), 3-note bounded notepad,
  reasoning-first field ordering on every operation.
- The prompt frames task and translation behavior; notepad caps and
  exclusions are defined on the schema. Includes the conditional first-pass
  note for window 1.
- The chain takes the right inputs (`window_text`, `current_glossary`
  compact form, `previous_notepad`, window N of M, source/target
  languages, settings), wraps in `@observe`, returns a `GlossaryUpdate`.

The **domain ORM model** is defined: `GlossaryEntry` with status
workflow (proposed/accepted/adjusted/rejected — invisible to the LLM),
plus a `GlossaryNotepad` row that gets fully replaced each pass.

## What's left for you

In `services/glossary_service.py`, four functions are skeletons:

1. **`make_windows()`** — split text using
   `app.constants.glossary_extraction` (`GLOSSARY_EXTRACTION_WINDOW_WORDS`,
   `GLOSSARY_EXTRACTION_OVERLAP_WORDS`). Watch for paragraph integrity at
   boundaries.

2. **`load_compact_glossary()`** — query `GlossaryEntry` rows for the
   book where `status != 'rejected'`, map to `GlossaryEntryCompact`.
   Skip rejected entries so the model doesn't rediscover them.

3. **`load_previous_notepad()`** — read the `GlossaryNotepad` row,
   deserialize JSON to `list[str]`, return `[]` if no row yet.

4. **`apply_delta()`** — the big one. Five steps, single transaction:
   merges → refinements → extensions → new_entries → replace notepad.
   Occurrence counts and first-seen window are **not** updated per window;
   after a run finishes (or is cancelled / fails mid-way), the service
   rescans the **full** manuscript and persists those fields, and fills
   empty translation targets for review.

5. **`extract_book_glossary()`** — the loop. Open a session per window
   (not one for the whole run — this can take minutes). Set Langfuse
   `session_id` to `str(book_id)` so windows group in the dashboard.

The signatures are deliberate — they're the contract between the chain
and the rest of the system. The bodies are mechanical orchestration on
top of those contracts.

## What's NOT in this drop

- **Alembic migration** for the new tables. Run
  `just makemigration "add glossary tables"` after adding the model
  files; Alembic will autogenerate it from the metadata. Verify by hand
  before applying — autogenerate is good but not perfect with JSONB and
  ARRAY columns.

- **API schemas** in `app/schemas/glossary.py` for the FE review UI.
  Skipped until step 3 of the roadmap (author review). The shape will
  mirror `GlossaryEntry` minus internal fields like `first_seen_window`,
  plus the workflow status as an exposed `Literal["proposed"|"accepted"|
  "adjusted"|"rejected"]`.

- **Routes** in `api/routes/glossary.py`. Same — comes with step 3.

- **Final consolidation pass**. Once iterative extraction works, a single
  cleanup chain that takes the full glossary (no source text) and looks
  for duplicates the iterative passes missed is worth adding. Different
  schema, different prompt — separate file when it lands.

## Tests worth writing as you go

- **Round-trip**: build a compact glossary, render the prompt with
  `render_glossary_table`, parse a synthetic JSON response into
  `GlossaryUpdate`. Validates the schema works end-to-end without
  burning API calls.
- **Apply delta on a fresh book**: empty glossary + a delta with
  `new_entries=[term]` ⇒ one DB row exists.
- **Apply delta with merge**: two existing entries A (variants=[a1])
  and B (variants=[b1]); merge winner=A, loser=B ⇒ A has variants=[a1,
  b1], B is deleted.
- **Window 1 framing**: chain called with `window_number=1` and empty
  glossary should include the first-pass note in the rendered prompt
  (assert with a substring check on the rendered string — extract it
  before sending to the provider in tests).
