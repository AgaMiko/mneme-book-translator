# Mneme

**Translation that remembers.**

Mneme is an open-source AI translation workspace for fiction manuscripts. It keeps persistent state across the book: manuscript structure, metadata, glossary decisions, speaker windows, and character voice profiles. The model is an assistant inside a reviewable workflow, not a one-shot translator.

This repo is a working Docker stack: upload a `.docx`, parse it into chapters and paragraphs, persist it to Postgres, extract metadata, build a reviewable glossary, identify speaker windows, draft per-character voice profiles, translate the book fragment by fragment straight into fluent English, and export the result as PDF, EPUB or DOCX.

**Repository:** [github.com/AgaMiko/mneme-book-translator](https://github.com/AgaMiko/mneme-book-translator)

## Stack

| Layer       | Choice                                          |
| ----------- | ----------------------------------------------- |
| API         | FastAPI · Pydantic v2 · SQLAlchemy 2.0 (async)  |
| Persistence | PostgreSQL 16 · Alembic                         |
| Parsing     | `python-docx`                                   |
| Export      | WeasyPrint (PDF) · EPUB 3 · `python-docx`       |
| LLM         | Gemini (`google-genai`) · OpenAI (`openai`) · Langfuse tracing |
| Frontend    | Vite · React 18 · TypeScript · Tailwind         |
| Data        | TanStack Query · Zod                            |
| Tooling     | `uv` · `pnpm` · `ruff` · `mypy` · `just`        |
| Container   | Docker Compose · multi-stage Dockerfiles        |

## What works

- Upload `.docx` manuscripts and preserve book/chapter/paragraph structure.
- Extract title-adjacent metadata asynchronously after upload.
- Estimate, start, stop, continue, and reset glossary extraction.
- Review working glossary terms, translations, variants, and statuses.
- Import the reviewed glossary of another book (a new version of the manuscript, or the next book in a series), then expand it: Mneme reads the manuscript again and adds only the missing terms as proposals. Terms you accepted or removed are never renamed, rewritten or merged away by extraction.
- Identify character speaker windows as the first pass of voice extraction.
- Draft, review, edit, accept, reject, regenerate, and reset character voice profiles.
- Translate the book, or chosen chapters, fragment by fragment (about 1,200 words each), with a cost estimate before you start, live progress, and stop and continue. See [How translation works](#how-translation-works).
- Read the translation next to the Polish, paragraph by paragraph, with translator notes (possible source typos, ambiguities, wordplay, added words), style metrics per chapter, and automatic checks (leftover Polish letters, dialogue dashes, missing placeholders).
- See glossary terms highlighted in both languages. Hovering a term shows its agreed English and a short note; clicking opens it in the glossary. A term is marked as a warning when the English paragraph does not use its agreed target.
- See which chapters are translated (a tick), partly translated ("2/3") or not started. Finished chapters are skipped unless you choose to translate them again.
- Export the translation as PDF (typeset in EB Garamond), EPUB or DOCX. Untranslated fragments are marked so gaps are visible.
- Open each book on the pipeline stage it has reached.
- Keep long-running extraction and translation state in Postgres so interrupted runs can be continued.

## How translation works

By default each fragment is translated in **one step**: gpt-6.1-sol, at high thinking, translates straight from the Polish into the final English. It works from meaning rather than word for word, keeps the author's style and each character's voice, varies sentence length, avoids repeating words, and aims at measured style targets (few sentences starting with "She"/"He", ellipses and em dashes only where they belong, no stock phrases).

Each call gets:

- **the fixed part**: translation rules, the book's style sheet (British spelling, quote style, units, scene breaks) and the whole accepted glossary. It is the same for every call, so it is cached and billed at about a tenth of the normal price;
- **the voice profiles of the characters in the scene**: those who speak in the fragment's speaker windows or are named in it;
- **the neighbouring text**: the end of the previous fragment (Polish and its current English) and the start of the next one;
- **the fragment itself**, paragraph by paragraph. The answer must have the same paragraphs in the same order.

Calls use the OpenAI **Flex** tier (half price, slower). A 100,000-word novel costs about $11–14 to translate this way.

Two other modes exist: `TRANSLATION_STAGE_COUNT=2` adds a faithful draft by gpt-6-luna before Sol's pass, and `3` adds a separate final edit. Any stage can use a Gemini model instead. The default was chosen by blind comparisons on the author's novel: one step won 30 of 40 paragraphs against two steps, with fewer errors, at about the same cost. Results and costs of all tested setups are in [docs/step5-translation-pipeline.md](docs/step5-translation-pipeline.md#model-and-pipeline-tests-2026-10-21).

## Quickstart

You need: Docker, Docker Compose, and (optionally) [`just`](https://github.com/casey/just).

Create a local `.env` with your API keys. Gemini is used for metadata, glossary and voice extraction; OpenAI for translation (by default):

```bash
GEMINI_API_KEY=...
OPENAI_API_KEY=...   # needed for the default translation models

# Optional overrides
GEMINI_MODEL=gemini-3.1-flash-lite-preview
# Fragment translation. Defaults: one step, Sol straight into the final text,
# high thinking, OpenAI Flex tier (half price, slower).
TRANSLATION_MODEL=gpt-6.1-sol          # any gemini-… or gpt-… model
TRANSLATION_STAGE_COUNT=1              # 2 = draft + revision, 3 = draft, line edit, final edit
TRANSLATION_FAITHFUL_MODEL=gpt-6-luna  # the draft model in modes 2 and 3
TRANSLATION_LINE_EDIT_MODEL=           # per-stage overrides (3-stage mode)
TRANSLATION_POLISH_MODEL=              # the Final stage
TRANSLATION_THINKING_LINE_EDIT=high    # minimal | low | medium | high, per stage
TRANSLATION_OPENAI_SERVICE_TIER=flex   # empty = standard tier
TRANSLATION_CONCURRENCY=4
LANGFUSE_PUBLIC_KEY=...
LANGFUSE_SECRET_KEY=...
LANGFUSE_HOST=https://cloud.langfuse.com
```

Start the stack:

```bash
just up
# or: docker compose up --build
```

The API container runs Alembic migrations on startup.

Then open:

- Frontend → <http://localhost:5177>
- API docs → <http://localhost:8000/docs>

## Architecture overview

```
┌─────────────┐      ┌─────────────┐      ┌─────────────┐
│   React     │─────▶│   FastAPI   │─────▶│  Postgres   │
│  (Vite/TS)  │ JSON │  (async)    │ ORM  │     16      │
└─────────────┘      └─────────────┘      └─────────────┘
   :5177                :8000                :5432
```

Three schema layers are kept deliberately separate:

```
backend/app/
├── schemas/        # API contracts (request/response DTOs) - FE-facing
├── models/         # SQLAlchemy ORM - persistence shape
└── generation/
    ├── prompt_manager/
    │   ├── models/  # LLM output schemas
    │   └── prompts/ # prompt templates
    └── chains/      # provider calls + structured output parsing
```

## Project layout

```
mneme-book-translator/
├── backend/                 # FastAPI app + Alembic
│   ├── app/
│   │   ├── api/routes/      # endpoints
│   │   ├── constants/       # pipeline sizing and taxonomy
│   │   ├── core/            # config, db, lifespan
│   │   ├── generation/      # LLM schemas, prompts, providers, chains
│   │   ├── models/          # SQLAlchemy
│   │   ├── schemas/         # Pydantic API contracts
│   │   └── services/        # business logic and pipeline orchestration
│   ├── alembic/
│   ├── pyproject.toml
│   └── Dockerfile
├── frontend/                # Vite + React
│   ├── src/
│   │   ├── components/
│   │   ├── constants/       # FE pipeline constants
│   │   ├── hooks/
│   │   ├── lib/             # API client, query hooks, utilities
│   │   └── App.tsx
│   ├── package.json
│   └── Dockerfile
├── docs/                    # design notes (Step 5/6 translation pipeline)
├── data/uploads/            # bind-mounted upload storage (gitignored)
├── docker-compose.yml
└── justfile
```

## Common commands

```bash
just up              # start the stack
just down            # stop everything
just logs <service>  # tail logs (api | postgres | frontend)
just shell api       # exec into the API container
just migrate         # run alembic upgrade head
just makemigration "msg"  # autogenerate migration
just reset-db        # drop + recreate Postgres data (destructive; prompts)
just fmt             # ruff + prettier
just lint            # ruff + mypy + tsc
just test            # backend pytest
just gen-client      # regenerate TS API types from OpenAPI
```

## Roadmap

- [x] Step 1 — Upload `.docx`, parse, persist, display
- [x] Step 2 — Async metadata extraction and iterative glossary extraction
- [x] Step 3 — Author glossary review UI and acceptance flow
- [x] Step 4 — Speaker identification and character voice profile extraction
- [~] Step 5 — Fragment translation with context windows, accepted glossary, and voice memory. Built: one-step translation by default (two- and three-step modes optional), Gemini and OpenAI models, Flex pricing and prompt caching, style metrics, translator notes, glossary term highlighting with drift warnings, chapter status, and PDF/EPUB/DOCX export. Still to do: updating translated text when a glossary term changes, and a style sheet you can edit in the app; see [docs/step5-translation-pipeline.md](docs/step5-translation-pipeline.md).
- [ ] Step 6 — Problematic-fragment detection and author flag review

## License

Apache 2.0 — see [LICENSE](./LICENSE).

## Acknowledgements

The LLM tokens used to build and run Mneme were sponsored by [CHAPTR](https://www.chaptr.com/).
