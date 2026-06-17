# AGENTS.md

## Operational Commands

- Run full stack: `docker compose up --build`
- Run full stack in background: `docker compose up --build -d`
- Stop full stack: `docker compose down`
- Inspect service logs: `docker compose logs -f backend`, `docker compose logs -f pipeline`, or `docker compose logs -f frontend`
- Frontend build check: `cd aic-frontend && npm ci && npm run build`
- Backend local server: `cd aic-backend && python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload`
- Pipeline local server: `cd aic-pipeline && python -m uvicorn app.main:app --host 0.0.0.0 --port 9000 --reload`
- Python dependencies are pinned in `requirements.txt`; use `pip install -r requirements.txt`.
- Frontend uses npm with `package-lock.json`; do not switch to yarn, pnpm, or bun.

## Golden Rules

### Immutable

- Do not commit secrets, real credentials, JWT secrets, database passwords, generated model caches, or local `.env` files.
- Keep `JWT_SECRET` environment-driven and at least 32 characters; never weaken the validator in `aic-backend/app/config.py`.
- Keep `ENCRYPTION_KEY` environment-driven; never commit real field-encryption keys or disable encrypted PII handling.
- Preserve the service boundary: frontend calls backend under `/api/v1`; backend calls pipeline through `PIPELINE_URL`; frontend must not call pipeline directly.
- Preserve async database access in backend code; use `AsyncSession`, `await`, and SQLAlchemy async APIs consistently.
- Keep the pipeline CPU-oriented unless the deployment image and infrastructure are intentionally changed.

### Do's & Don'ts

- Do update backend schemas, routers, services, database models, `init.sql`, and frontend API consumers together when changing API contracts.
- Do keep long-running or CPU-heavy pipeline work out of the FastAPI event loop by using executor patterns already present in the pipeline service.
- Do use the existing Axios client in `aic-frontend/src/api/index.js` for authenticated frontend requests.
- Do keep generated scores and metric field names aligned across `aic-pipeline`, `aic-backend`, and UI chart views.
- Do not duplicate business logic between frontend and backend; frontend may format and display, backend owns authorization and persistence.
- Do not add a second authentication transport without updating refresh, logout, route guards, and CORS together.
- Do not add broad catch-and-ignore error handling around persistence or scoring paths.

## Project Context

AIC Web is a Vue/FastAPI/MySQL application for AI-informed classroom writing analysis. It supports student submissions, teacher analytics, asynchronous analysis jobs, and AIC metric computation.

Tech stack: Vue 3, Vite, Pinia, Vue Router, Axios, Chart.js, FastAPI, SQLAlchemy async, aiomysql, MySQL 8, pandas, NumPy, scikit-learn, sentence-transformers, PyTorch CPU, Docker Compose.

## Standards & References

- Existing high-level overview and Docker startup notes live in `README.md`; do not repeat them here.
- Status and product context live in `CURRENT_STATUS_VER8.md` and `ai-validated-dongarra.md`; consult them before changing scoring semantics or user-facing analytics.
- Commit messages should be concise imperative summaries, optionally scoped: `frontend: fix auth refresh retry`, `backend: add assignment metric query`.
- Keep changes scoped to the service boundary being modified; cross-service contract changes must include all affected services in the same change.
- Maintenance policy: when code behavior and these rules diverge, update the relevant `AGENTS.md` in the same change or explicitly flag the mismatch.

## Context Map

- **[Frontend UI and client state](./aic-frontend/AGENTS.md)** - Vue views, Pinia stores, Axios API calls, routing, charts, and Vite build work.
- **[Backend API and persistence](./aic-backend/AGENTS.md)** - FastAPI routers, auth, async SQLAlchemy, MySQL models, and pipeline job orchestration.
- **[Analysis pipeline](./aic-pipeline/AGENTS.md)** - SBERT/TF-IDF analysis, AIC metric computation, FastAPI pipeline API, and CPU model runtime.
