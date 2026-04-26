# Book Translator

LLM-assisted translation pipeline for Polish fiction → English, with author-in-the-loop glossary review and per-fragment quality gates.

This repo is **Step 1**: a working Docker stack where you can upload a `.docx` manuscript, parse it into chapters and paragraphs, persist to Postgres, and read it back in a minimal web UI. The translation pipeline (glossary extraction, fragment translation, problematic-fragment flagging) lands in subsequent steps.

## Stack

| Layer       | Choice                                          |
| ----------- | ----------------------------------------------- |
| API         | FastAPI · Pydantic v2 · SQLAlchemy 2.0 (async)  |
| Persistence | PostgreSQL 16 · Alembic                         |
| Parsing     | `python-docx`                                   |
| Frontend    | Vite · React 18 · TypeScript · Tailwind         |
| Data        | TanStack Query · Zod                            |
| Tooling     | `uv` · `pnpm` · `ruff` · `mypy` · `just`        |
| Container   | Docker Compose · multi-stage Dockerfiles        |

## Quickstart

You need: Docker, Docker Compose, and (optionally) [`just`](https://github.com/casey/just).

```bash
cp .env.example .env
just up           # or: docker compose up --build
just migrate      # apply Alembic migrations
```

Then open:

- Frontend → <http://localhost:5173>
- API docs → <http://localhost:8000/docs>

## Architecture overview

```
┌─────────────┐      ┌─────────────┐      ┌─────────────┐
│   React     │─────▶│   FastAPI   │─────▶│  Postgres   │
│  (Vite/TS)  │ JSON │  (async)    │ ORM  │     16      │
└─────────────┘      └─────────────┘      └─────────────┘
   :5173                :8000                :5432
```

Three schema layers are kept deliberately separate (this matters more once the pipeline lands):

```
backend/app/
├── schemas/        # API contracts (request/response DTOs) — stable, FE-facing
├── models/         # SQLAlchemy ORM — persistence shape
└── pipeline/       # (next step) LLM I/O contracts — model-facing
    └── schemas/
```

## Project layout

```
book-translator/
├── backend/                 # FastAPI app + Alembic
│   ├── app/
│   │   ├── api/routes/      # endpoints
│   │   ├── core/            # config, db, lifespan
│   │   ├── models/          # SQLAlchemy
│   │   ├── schemas/         # Pydantic API contracts
│   │   └── services/        # business logic (parsing, persistence)
│   ├── alembic/
│   ├── pyproject.toml
│   └── Dockerfile
├── frontend/                # Vite + React
│   ├── src/
│   │   ├── components/
│   │   ├── lib/             # api client, utilities
│   │   └── App.tsx
│   ├── package.json
│   └── Dockerfile
├── data/uploads/            # bind-mounted upload storage (gitignored)
├── docker-compose.yml
├── .env.example
└── justfile
```

## Common commands

```bash
just up              # start the stack (detached)
just down            # stop everything
just logs <service>  # tail logs (api | postgres | frontend)
just shell api       # exec into the API container
just migrate         # run alembic upgrade head
just makemigration "msg"  # autogenerate migration
just reset-db        # drop + recreate (destructive; prompts)
just fmt             # ruff + prettier
just lint            # ruff + mypy + tsc
```

## Roadmap

- [x] Step 1 — Upload `.docx`, parse, persist, display
- [ ] Step 2 — Redis + ARQ worker, Langfuse, glossary extraction (two-pass)
- [ ] Step 3 — Author glossary review UI + acceptance flow
- [ ] Step 4 — Fragment translation with context windows + character-voice consistency
- [ ] Step 5 — Problematic-fragment detection + author flag review

## License

Apache 2.0 — see [LICENSE](./LICENSE).
