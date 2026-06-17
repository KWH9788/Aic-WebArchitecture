# AGENTS.md

## Module Context

This service is the authenticated FastAPI backend for users, classes, submissions, jobs, metrics, and teacher feedback. It owns persistence in MySQL and calls the pipeline service for analysis.

## Tech Stack & Constraints

- Use FastAPI, Pydantic, SQLAlchemy async, aiomysql, httpx, passlib/bcrypt, and python-jose.
- Run with Python 3.11 in Docker.
- Use `AsyncSession` from `app.database`; do not introduce synchronous SQLAlchemy sessions.
- Environment settings are centralized in `app.config.Settings`.
- Pipeline calls go through `app/services/pipeline_client.py` and `settings.PIPELINE_URL`.

## Implementation Patterns

- Add HTTP endpoints in `app/routers`, business logic in `app/services`, request/response models in `app/schemas`, and database tables in `app/models/db_models.py`.
- Route prefixes are registered in `app/main.py`; keep public API paths under `/api/v1` except `/health`.
- Keep auth and role checks in dependencies or service-layer queries, not in frontend assumptions.
- When adding database fields, update SQLAlchemy models, Pydantic schemas, service queries, and `init.sql` together.
- Preserve analysis job status values: `pending`, `running`, `done`, `failed`.
- Keep pipeline timeouts explicit; long analysis calls currently use `httpx.AsyncClient(timeout=120.0)`.

## Testing Strategy

- Install dependencies: `pip install -r requirements.txt`
- Local server: `python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload`
- Container check: `docker compose up --build backend`
- No backend test suite is configured; validate changed endpoints with FastAPI docs, HTTP requests, or service-level checks against a seeded database.

## Local Golden Rules

- Do keep JWT validation strict and environment-driven.
- Do keep `ENCRYPTION_KEY` environment-driven; never commit real encryption keys or weaken encrypted PII handling.
- Do return schema-shaped responses rather than raw ORM objects unless an existing router pattern already handles serialization.
- Do preserve async boundaries when calling database and pipeline code.
- Do keep metric score names aligned with pipeline response fields and frontend chart expectations.
- Do not allow frontend-only role checks to protect backend data.
- Do not weaken `pool_pre_ping=False` without testing the Windows/MySQL aiomysql behavior noted in `app/database.py`.
- Do not add migrations unless the project is first given a migration tool; update `init.sql` for current schema changes.
