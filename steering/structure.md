# Structure Steering

## Repository Shape
<<<<<<< Updated upstream
- `backend/`: FastAPI app, worker, services, database models/session helpers, Alembic migrations, and backend tests.
- `frontend/`: Vue SPA source, routing, components, styles, E2E tests, Vite config, and production container assets.
- `.github/workflows/`: CI, Docker build validation, and Playwright E2E workflows.
- `docs/`: user-facing local development, testing, deployment, troubleshooting, and demo guidance.
- `steering/`: compact project-level guidance for future tasks.
- `steering/frontend_reference/`: visual reference assets for frontend styling direction.
- `tasks/`: task-level requirements, designs, context notes, and implementation plans.
<<<<<<< Updated upstream
=======
- `cv/`: portfolio/resume collateral, separate from product runtime code.
- `portable-spec-driven-kit/`, `qwen_spec/`, and root `rag_service*.md`: reference or historical planning material, not the default home for new product code.
=======

- `backend/`: FastAPI API, SQLAlchemy models, Alembic migrations, async services, worker, and backend tests.
- `frontend/`: Vue 3 SPA, typed API client, Clerk/local auth route handling, workspace UI, styles, and Playwright tests.
- `docs/`: operational guides for local development, testing, deployment, troubleshooting, and demos.
- `infra/`: local infrastructure support files.
- `tasks/`: task-level specs, design notes, and implementation artifacts.
- `steering/`: durable project guidance and visual reference assets.
>>>>>>> Stashed changes
>>>>>>> Stashed changes

## Entry Points

- Backend API starts at `backend/app/main.py`; `create_app()` wires settings, CORS, request IDs, and routers.
- Worker execution starts at `backend/app/worker/main.py`; the loop claims background jobs and delegates processing to services.
- API route reading starts under `backend/app/api/routes/`, with shared dependencies in `backend/app/api/dependencies.py` and contracts in `backend/app/api/schemas.py`.
- Database model reading starts at `backend/app/db/models.py`; migrations live under `backend/alembic/`.
- Frontend app bootstrap starts at `frontend/src/main.ts`; routing starts at `frontend/src/router/index.ts`; the workspace experience starts in `frontend/src/views/WorkspaceView.vue`.
- Frontend backend access starts at `frontend/src/api/client.ts`; shared frontend contract types live in `frontend/src/types/workspace.ts`.
- Local full-stack execution starts from `docker-compose.yml`; common commands are exposed through `Makefile`.

## Architectural Conventions

- Keep routes thin: validate transport-level inputs, call services or repositories, and return schema objects.
- Keep durable business behavior in services and repositories, not Vue components or API glue.
- Treat Pydantic API schemas and TypeScript workspace types as the public contract between backend and frontend.
- Treat SQLAlchemy models and Alembic migrations as the database contract; avoid tests that depend on incidental query order unless order is part of the contract.
- Keep background work idempotent and job-state driven because the worker may retry after partial failures.
- Keep frontend state and polling behavior in the workspace layer; reusable display belongs in components.

## Module Contract

- Public API changes require synchronized backend schemas, frontend types/client calls, and API or E2E tests.
- Auth changes require review across backend dependencies, frontend Clerk/local auth mode, E2E auth fixtures, and production constraints.
- Ingestion changes require preserving document status transitions, job retry semantics, source-object handling, and ready-only retrieval.
- Retrieval and chat changes require preserving citation shape, grounded flag behavior, streaming event shape, final persistence, and abstention semantics.
- Data deletion changes require reviewing database cascade behavior, object-storage cleanup, and user-visible document/chat consistency.
- UI workflow changes should keep the first screen as the usable workspace, not a marketing or documentation surface.

## Module Interface Map

- Workspace API: exposes `GET /api/workspace` as the signed-in user's current workspace summary; callers may rely on document summaries and visible chat messages, but not on repository query details. Changes to workspace ownership, user scoping, or response shape need deeper review.
- Documents API: exposes list, detail, upload, and delete under `/api/documents`; callers may rely on supported extension validation, document status values, and async ingestion enqueueing, but not on storage-key format or cleanup timing. Protected by API document tests and E2E upload flow.
- Ingestion worker: owns claiming, parsing, chunking, embedding, indexing, retry, and final document status; callers may rely on document becoming searchable only after `ready`, but not on chunk boundaries, provider batch shape, or helper order. Protected by worker ingestion tests.
- Retrieval service: owns ready-document search, citation construction, and grounding context formatting; callers may rely on retrieved chunks, citation fields, and ready-only filtering, but not on private scoring fallback or context wording. Protected by chat API tests and `tests/evals`.
- Chat API and service: expose session list/create, history, non-streaming send, and SSE streaming send under `/api/chat`; callers may rely on `start`, `token`, `done`, and `error` event names plus final persistence, but not on prompt text, provider call sequence, or title-generation timing. Protected by chat API tests and browser smoke tests.
- Auth boundary: `require_current_user` owns Clerk verification, local auth bypass, and E2E token handling; callers may rely on an `AuthenticatedUser`, but not on token parsing internals. Protected by auth dependency tests and local-auth E2E tests.
- Frontend API client: `frontend/src/api/client.ts` owns HTTP paths, bearer-token attachment, error parsing, and SSE parsing; UI components should depend on typed client operations rather than constructing fetch calls directly.

## Where To Put New Work
<<<<<<< Updated upstream
- Backend endpoints: `backend/app/api/routes/`.
- Backend auth/dependency wiring: `backend/app/api/dependencies.py` and `backend/app/services/auth.py`.
- Backend services and integrations: `backend/app/services/`.
- Persistence models and migrations: `backend/app/db/` and `backend/alembic/versions/`.
- Backend tests: `backend/tests/`, grouped by API, service, worker, E2E, or eval surface.
- Frontend screens and flows: `frontend/src/views/`.
- Frontend reusable UI: `frontend/src/components/`.
- Frontend API helpers and shared types: `frontend/src/api/` and `frontend/src/types/`.
- Frontend routing: `frontend/src/router/`.
- Shared frontend styles and tokens: `frontend/src/styles/`, imported through `frontend/src/styles.css`.
<<<<<<< Updated upstream
- Compact steering: `steering/`; task artifacts: `tasks/`; user-facing project docs: `docs/`.
=======
- Durable detailed specs: `specs/`; compact steering: `steering/`; task artifacts: `tasks/`.
=======

- New backend endpoints: `backend/app/api/routes/`, with schemas in `backend/app/api/schemas.py` and dependencies in `backend/app/api/dependencies.py` when shared.
- New backend business behavior: `backend/app/services/`; add repository methods when behavior needs durable database access.
- New database state: `backend/app/db/models.py` plus an Alembic migration and tests that exercise the public behavior.
- New ingestion, retrieval, or chat behavior: add or update service tests, API tests, and focused eval tests when grounding quality changes.
- New frontend API usage: extend `frontend/src/api/client.ts` and `frontend/src/types/workspace.ts` first, then consume from views/components.
- New workspace UI: `frontend/src/views/WorkspaceView.vue` for page orchestration, `frontend/src/components/` for reusable panels, and `frontend/src/styles/` for shared styling.
- New full-stack smoke behavior: `frontend/e2e/` and the relevant Compose override or Make target.
>>>>>>> Stashed changes
>>>>>>> Stashed changes
