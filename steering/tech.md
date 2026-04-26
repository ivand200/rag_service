# Tech Steering

## Stack
- Backend: Python 3.12, FastAPI, SQLAlchemy, Alembic, Pydantic settings, `uv`, Ruff, pytest, mypy, and OpenAI-compatible clients.
- Frontend: Vue 3, TypeScript, Vite, Vue Router, Clerk Vue SDK, npm on Node 20+, and nginx for the production image.
- Runtime: Docker Compose for local frontend, backend, worker, Postgres with `pgvector`, MinIO, and MinIO bootstrap.
- Storage/retrieval: Postgres relational data plus `pgvector` embeddings; S3-compatible object storage for uploaded source bytes.

## Key Services / Infrastructure
- FastAPI exposes health, workspace, document, and chat APIs.
- A long-running polling worker handles document ingestion jobs and chat-session title jobs without a separate queue broker.
- Clerk supplies browser authentication and backend bearer-token validation for protected routes.
- OpenAI supplies embeddings and chat completions through the OpenAI-compatible provider client; compatible legacy providers remain possible through configuration.
- Docker-based startup runs Alembic migrations before the backend API starts.
- CI validates backend checks, frontend type/build checks, Docker build behavior, and Playwright E2E smoke behavior.

## Engineering Conventions
- Centralize runtime settings in `backend/app/config.py`; validate new environment-driven behavior there.
- Keep HTTP concerns in API routes, auth/service wiring in dependencies, reusable domain behavior in services, and persistence concerns in `backend/app/db/`.
- Protected backend routes should use shared Clerk/current-user dependencies rather than parsing auth headers inline.
- Reuse service-layer logic from both API and worker paths where possible.
- Use shared structured logging helpers for request IDs, correlation IDs, uploads, chat requests, and worker jobs.
- Frontend configuration comes from Vite/repo-root environment values; keep Clerk frontend config and backend token verification aligned.
- E2E mode uses deterministic auth/provider behavior for browser smoke tests without requiring live Clerk or model-provider calls.
- Preserve the existing authenticated SSE/request-response chat contract unless a task explicitly changes realtime architecture.
- Prefer behavior-oriented tests around API, worker, service, E2E, and RAG quality surfaces over implementation-detail tests.

## Related Steering Docs
- [Product Steering](./product.md)
- [Structure Steering](./structure.md)
- Detailed baseline specs live in [../specs/](../specs/).

## Technical Constraints
- The database must support the `vector` extension and match the configured embedding dimensionality.
- Browser access depends on `FRONTEND_ORIGIN` and backend CORS being aligned.
- Object storage is required for uploaded documents, including local development.
- Authenticated browser flows require matching Clerk publishable key, JWT public key, and authorized-party settings.
- The frontend fails fast without `VITE_CLERK_PUBLISHABLE_KEY` outside E2E mode.
- Manual deployments should keep separate frontend, backend web, and worker processes backed by managed Postgres and S3-compatible storage.
