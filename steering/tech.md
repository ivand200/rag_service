# Tech Steering

## Stack

- Backend: Python 3.12, FastAPI, Pydantic v2, SQLAlchemy async ORM, Alembic, `uv`, Ruff, mypy, pytest.
- Retrieval and persistence: Postgres 16 with `pgvector`; SQLite is used by tests through repository and service boundaries.
- Storage: S3-compatible object storage, with MinIO in local Docker Compose.
- Provider integration: OpenAI-compatible chat and embedding clients, defaulting to `gpt-4.1-mini` and `text-embedding-3-small` through environment settings.
- Frontend: Vue 3, TypeScript, Vite, Vue Router, Clerk Vue SDK, Playwright for browser smoke tests.
- Runtime: Docker Compose for local full-stack operation; nginx serves the built frontend and proxies `/api/*`.

## Key Services / Infrastructure
<<<<<<< Updated upstream
- FastAPI exposes health, workspace, document, and chat APIs.
- A long-running polling worker handles document ingestion jobs and chat-session title jobs with Postgres-backed claiming, scheduled retry backoff, and no separate queue broker.
- Clerk supplies browser authentication and backend bearer-token validation for protected routes.
- OpenAI supplies embeddings and chat completions through the OpenAI-compatible provider client; compatible legacy providers remain possible through configuration.
- Docker-based startup runs Alembic migrations before the backend API starts.
- CI validates backend checks, frontend type/build checks, Docker build behavior, and Playwright E2E smoke behavior.
=======

- `backend` runs Alembic migrations before starting FastAPI at `app.main:app`.
- `worker` runs `python -m app.worker.main` and claims ingestion jobs before chat-session title jobs.
- `postgres` uses the `pgvector/pgvector:pg16` image.
- `minio` stores uploaded source files; `minio-bootstrap` creates the configured bucket.
- `frontend` builds the Vue app and serves it from nginx on port `5173` by default.
- GitHub Actions run backend lint/tests, frontend typecheck/build, Docker build validation, and Compose-backed Playwright E2E smoke tests.
>>>>>>> Stashed changes

## Engineering Conventions

- Backend settings live in `app.config.Settings`; prefer adding typed settings with validation there over reading environment variables directly.
- Protected API routes use `require_current_user`; keep Clerk, local auth, and E2E auth behavior explicit at that dependency boundary.
- API response contracts live in `app.api.schemas`; frontend matching types live in `frontend/src/types/workspace.ts`.
- Long-running or provider-facing behavior should be service-level code under `backend/app/services`, with API routes kept thin.
- Database schema changes should be represented in SQLAlchemy models and Alembic migrations together.
- Use structured JSON logging through `app.services.observability`; preserve request and correlation IDs across request, upload, chat, and worker paths.
- Tests should prefer behavior at API, service, repository, worker, or browser boundaries over private helper call order.

## Related Steering Docs
<<<<<<< Updated upstream
- [Product Steering](./product.md)
- [Structure Steering](./structure.md)
<<<<<<< Updated upstream
- Task-level requirements, designs, and context notes live in [../tasks/](../tasks/).
- Historical root `rag_service*.md` notes are reference material, not the default source for new work.
=======
- Detailed baseline specs live in [../specs/](../specs/).
=======

- Product behavior and scope: `steering/product.md`.
- Repository layout and module boundaries: `steering/structure.md`.
- Frontend visual reference assets: `steering/frontend_reference/`.
- Local commands and service maps: `docs/local-development.md`.
- Validation paths: `docs/testing.md`.
>>>>>>> Stashed changes
>>>>>>> Stashed changes

## Technical Constraints

- `AUTH_MODE=local` is only for local development; `APP_ENV=production` must reject it.
- `VITE_*` frontend settings are build-time values, so auth-mode or API-base changes require rebuilding the frontend image.
- Docker Compose overrides container `DATABASE_URL` and `S3_ENDPOINT_URL`; host-local and container-local values differ intentionally.
- Retrieval must only search chunks from `ready` documents.
- The E2E path uses deterministic fake provider behavior gated by `APP_ENV=e2e`; normal development and production use configured provider clients.
- Keep generated, heavyweight, or environment-local outputs out of steering; use docs or task artifacts for details that are not durable project guidance.
