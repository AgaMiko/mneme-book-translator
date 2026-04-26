set dotenv-load := true

# Show available commands
default:
    @just --list

# Build & start the stack
build:
    ddocker compose up -d --build
up:
    docker compose up

# Stop everything
down:
    docker compose down

# Tear down including volumes (destructive)
nuke:
    docker compose down -v

# Tail logs for a service (api | frontend | postgres)
logs service="api":
    docker compose logs -f {{service}}

# Exec into a running container
shell service="api":
    docker compose exec {{service}} /bin/bash

# Run alembic upgrade head
migrate:
    docker compose exec api alembic upgrade head

# Autogenerate a new migration
makemigration message:
    docker compose exec api alembic revision --autogenerate -m "{{message}}"

# Drop the DB and re-run migrations (destructive — confirms first)
reset-db:
    @read -p "Drop and recreate database? [y/N] " ans && [ "$ans" = "y" ] || exit 1
    docker compose down -v postgres
    docker compose up -d postgres
    sleep 3
    just migrate

# Format code
fmt:
    docker compose exec api ruff format app
    docker compose exec frontend pnpm format

# Lint everything
lint:
    docker compose exec api ruff check app
    docker compose exec api mypy app
    docker compose exec frontend pnpm lint
    docker compose exec frontend pnpm typecheck

# Run backend tests
test:
    docker compose exec api pytest

# Generate the TS API client from OpenAPI (requires API running)
gen-client:
    docker compose exec frontend pnpm gen:api

db:
    docker compose exec postgres psql -U zt -d book-translator