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
| LLM         | Gemini via `google-genai` · Langfuse tracing    |
| Frontend    | Vite · React 18 · TypeScript · Tailwind         |
| Data        | TanStack Query · Zod                            |
| Tooling     | `uv` · `pnpm` · `ruff` · `mypy` · `just`        |
| Container   | Docker Compose · multi-stage Dockerfiles        |

## What works

- Upload `.docx` manuscripts and preserve book/chapter/paragraph structure.
- Extract title-adjacent metadata asynchronously after upload.
- Estimate, start, stop, continue, and reset glossary extraction.
- Review working glossary terms, translations, variants, and statuses.
- Identify character speaker windows as the first pass of voice extraction.
- Draft, review, edit, accept, reject, regenerate, and reset character voice profiles.
- Translate fragments in one step by default: gpt-6.1-sol, at high thinking, translates each fragment straight into the final English, following the rules for meaning, voices, rhythm and style targets. Two- and three-step modes (a gpt-6-luna draft first, and optionally a separate final edit) are available. Uses the accepted glossary and voice profiles, with style metrics and translator notes.
- Check rhythm and repetition in the line edit and final stages, keeping the meaning of the source over word variety.
- Export the translation as PDF, EPUB or DOCX, choosing which stage to export. Untranslated fragments are marked so gaps are visible.
- Open each book on the pipeline stage it has reached.
- Keep long-running extraction and translation state in Postgres so interrupted runs can be continued.

## Quickstart

You need: Docker, Docker Compose, and (optionally) [`just`](https://github.com/casey/just).

Create a local `.env` if you want LLM-backed extraction:

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
- [~] Step 5 — Fragment translation with context windows, accepted glossary, and voice memory. First slice built: one translation step per fragment by default (two- and three-step modes optional), Gemini and OpenAI models, Flex pricing and prompt caching, style metrics, translator notes, rhythm and repetition checks, a Translation tab, and PDF/EPUB/DOCX export. Glossary change propagation and flags review are still to do; see [docs/step5-translation-pipeline.md](docs/step5-translation-pipeline.md).
- [ ] Step 6 — Problematic-fragment detection and author flag review

## License

Apache 2.0 — see [LICENSE](./LICENSE).

## Acknowledgements

The LLM tokens used to build and run Mneme were sponsored by [CHAPTR](https://www.chaptr.com/).
