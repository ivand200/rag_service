# Structure Steering

## Repository Shape
- `backend/`: FastAPI app, worker, services, database models/session helpers, Alembic migrations, and backend tests.
- `frontend/`: Vue SPA source, routing, components, styles, E2E tests, Vite config, and production container assets.
- `.github/workflows/`: CI, Docker build validation, and Playwright E2E workflows.
- `docs/`: user-facing local development, testing, deployment, troubleshooting, and demo guidance.
- `specs/`: detailed durable product, tech, and structure specs plus focused reference assets.
- `steering/`: compact project-level guidance for future tasks.
- `tasks/`: task-level requirements, designs, context notes, and implementation plans.
- `cv/`: portfolio/resume collateral, separate from product runtime code.
- `portable-spec-driven-kit/`, `qwen_spec/`, and root `rag_service*.md`: reference or historical planning material, not the default home for new product code.

## Entry Points
- `backend/app/main.py`: FastAPI app factory, middleware, lifespan, workspace bootstrap, and router registration.
- `backend/app/worker/main.py`: polling worker for ingestion and chat-session title jobs.
- `backend/alembic/env.py`: migration environment.
- `frontend/src/main.ts`: Vue, Clerk, router, and global-style bootstrap.
- `frontend/src/router/index.ts`: SPA route definitions for workspace and auth flows.
- `frontend/src/views/AuthView.vue` and `frontend/src/views/SignUpView.vue`: Clerk sign-in/sign-up route views, with deterministic E2E-mode fallbacks.
- `frontend/src/views/WorkspaceRouteView.vue`: authenticated route shell that waits for Clerk state and supplies tokens.
- `frontend/src/views/WorkspaceView.vue`: primary signed-in workspace screen.
- `docker-compose.yml`: local multi-service runtime.

## Architectural Conventions
- Keep API handlers thin; route modules should delegate business behavior to services.
- Keep database models, custom types, constants, and session helpers inside `backend/app/db/`.
- Keep API-facing schema shapes in `backend/app/api/schemas.py`.
- Put reusable backend domain and integration logic in `backend/app/services/`.
- Treat the singleton workspace as an application convention: documents are shared at workspace scope, chat sessions are owned by Clerk users.
- In frontend work, compose route-level screens in `frontend/src/views/`, reusable UI in `frontend/src/components/`, network calls in `frontend/src/api/`, shared types in `frontend/src/types/`, and shared styles/tokens in `frontend/src/styles/`.
- Keep product runtime code in `backend/` and `frontend/`; do not couple it to portfolio assets, historical notes, or spec-kit experiments.

## Module Contract
- Backend features usually require coordinated route, dependency, service, schema, persistence, and test changes.
- Database schema changes require Alembic migrations plus matching SQLAlchemy model updates.
- Protected endpoints should depend on the shared current-user/auth dependency.
- New worker-backed behavior should reuse the existing worker/service pattern before introducing another background execution mechanism.
- Frontend features should extend focused views and components rather than pushing workspace logic into `App.vue`.

## Where To Put New Work
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
- Durable detailed specs: `specs/`; compact steering: `steering/`; task artifacts: `tasks/`.
