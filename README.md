# RAG Service MVP

RAG Service is a small, chat-first retrieval-augmented generation app. You upload `.txt`, `.md`, or `.pdf` documents, a worker parses and chunks them, embeddings are stored in Postgres with `pgvector`, and the chat API answers using only grounded context from the uploaded document set.

The repo is split into:

- `backend/`: FastAPI API, SQLAlchemy models, Alembic migrations, worker pipeline, retrieval, and provider integration
- `frontend/`: Vue 3 + Vite single-page app served by nginx in production mode
- root infra files: `docker-compose.yml`, `.env.example`, and GitHub Actions workflows

## Product Overview

Core MVP behaviors:

- single-workspace experience
- document upload and ingestion status tracking
- background parsing, chunking, embedding, and indexing
- multiple per-user chat sessions for signed-in users
- grounded chat answers with citations across the shared ready-document corpus
- abstention when the retrieved context is too weak
- async worker-generated session titles after the first user message
- local-first stack with MinIO + Postgres for development

## Architecture Overview

Runtime services:

- `frontend`: nginx serves the built Vue app and proxies `/api/*` to the backend
- `backend`: FastAPI app for health, workspace, document, and session-aware chat endpoints
- `worker`: long-running loop that claims queued ingestion jobs and chat-session title jobs
- `postgres`: primary relational store plus `pgvector` index storage
- `minio`: S3-compatible object storage for raw uploaded files
- `minio-bootstrap`: one-shot bucket bootstrap helper for local development

Data flow:

1. The frontend uploads a document to `POST /api/documents`.
2. The backend writes the file to object storage, creates a `document`, and queues an `ingestion_job`.
3. The worker downloads the file, parses it, chunks it, requests embeddings, and stores chunk vectors in Postgres.
4. Once ingestion finishes, the document becomes `ready`.
5. Signed-in users open one or more personal chat sessions that all point at the same shared document library.
6. Chat requests embed the user question, search shared `ready` chunks, assemble grounded context, and generate a cited answer or abstain.
7. After the first user message in a new session, the backend enqueues a title job and the worker replaces `New session` with a stable generated title.

## Service Map

Backend API surface:

- `GET /health/live`
- `GET /health/ready`
- `GET /api/workspace`
- `GET /api/documents`
- `POST /api/documents`
- `GET /api/documents/{id}`
- `GET /api/chat/sessions`
- `POST /api/chat/sessions`
- `GET /api/chat/messages?session_id=<id>`
- `POST /api/chat/messages`

Frontend behavior:

- upload panel and document status rail
- session switcher with `New session`
- active-session chat history scoped per signed-in user
- citation rendering for grounded answers
- polling while ingestion is still active
- polling for async session-title updates after the first send

## Environment Variables

Copy `.env.example` to `.env` and fill in at least the provider key:

```bash
cp .env.example .env
```

Important variables:

- `DASHSCOPE_API_KEY`: required for embeddings and chat
- `VITE_CLERK_PUBLISHABLE_KEY`: required by the Vue app to initialize Clerk in local dev and production builds
- `CLERK_JWT_PUBLIC_KEY`: required by the backend to verify Clerk bearer tokens on protected API routes
- `CLERK_AUTHORIZED_PARTIES`: optional comma-separated allowlist for the Clerk token `azp`; defaults to `FRONTEND_ORIGIN`
- `DASHSCOPE_BASE_URL`: defaults to the DashScope compatible OpenAI-style endpoint
- `CHAT_MODEL`: defaults to `qwen3.6-plus`
- `EMBEDDING_MODEL`: defaults to `text-embedding-v4`
- `CHUNK_MAX_BATCH_SIZE`: defaults to `10` to match the current provider limit
- `FRONTEND_ORIGIN`: browser origin allowed by backend CORS
- `S3_*`: object storage settings
- `DATABASE_URL`: backend database connection string

Notes:

- In local Docker Compose, `DATABASE_URL` and `S3_ENDPOINT_URL` are overridden so containers talk to `postgres` and `minio` over the Compose network.
- The backend loads environment from either `../.env` or `.env`, depending on the working directory.
- Clerk uses the repo-root `.env` values for both frontend and backend local runs, so fill in both the publishable key and JWT public key before testing signed-in flows.

## Local Development With Docker Compose

Prerequisites:

- Docker Desktop or Docker Engine with Compose
- a valid DashScope API key in `.env`

Start the full stack:

```bash
docker compose up --build
```

Useful endpoints:

- app UI: `http://localhost:5173`
- backend API: `http://localhost:8000`
- MinIO API: `http://localhost:9000`
- MinIO console: `http://localhost:9001`

Shut down:

```bash
docker compose down
```

Reset local state including Postgres and MinIO volumes:

```bash
docker compose down -v
```

## Running Backend and Frontend Checks Locally

Backend:

```bash
cd backend
uv sync --extra dev
uv run ruff check app tests --ignore UP042
uv run pytest tests -q
```

Frontend:

```bash
cd frontend
npm ci
npm run typecheck
npm run build
```

Docker validation:

```bash
docker compose config
docker build -f backend/Dockerfile .
docker build -f frontend/Dockerfile .
```

## Ingestion and Chat Workflow

Document ingestion:

- supported extensions: `.txt`, `.md`, `.pdf`
- uploads are stored in object storage first
- the worker updates document state through `pending -> processing -> ready` or `failed`
- failed jobs are retried up to `INGESTION_MAX_RETRIES`

Retrieval and answer generation:

- only `ready` document chunks are eligible for retrieval
- every chat session searches the same shared ready-document corpus
- the API embeds the user query, ranks chunks with vector similarity, and uses a minimum grounding threshold
- when supporting context is insufficient, the assistant returns an abstention response instead of hallucinating
- grounded answers include citations with document and chunk metadata

Session behavior:

- each authenticated Clerk user can keep multiple independent chat sessions
- the backend auto-creates one empty `New session` for first-time users
- creating a new session keeps earlier sessions intact, reuses the latest session when it is still empty, and otherwise creates a fresh session
- session rename, delete, and archive flows are intentionally out of scope in this MVP

## Health, Observability, and Logging

Health endpoints:

- `/health/live`: lightweight process liveness plus service metadata
- `/health/ready`: checks database connectivity, object storage bucket access, and provider configuration presence

Observability behavior:

- API requests emit structured JSON logs
- request middleware assigns or forwards `x-request-id`
- `x-correlation-id` is accepted from the client or defaults to the request ID
- upload, chat, worker, and ingestion events add useful fields like `document_id`, `job_id`, `workspace_id`, `session_id`, message IDs, status, and timing

Practical debugging tip:

- use the shared `request_id` / `correlation_id` in response headers and logs to trace an upload or chat request across the backend path

## CI/CD Expectations

GitHub Actions currently provide:

- `.github/workflows/ci.yml`
  - backend dependency install
  - backend Ruff check
  - backend test suite
  - frontend `npm ci`
  - frontend typecheck
  - frontend production build
- `.github/workflows/build.yml`
  - `docker compose config`
  - backend Docker image build
  - frontend Docker image build

Current expectation:

- pull requests should pass both workflows before merge
- pushes to `main` also run the same checks

Intentional current limitation:

- backend CI ignores Ruff rule `UP042` because the repo still carries a compatibility pattern in `backend/app/db/models.py` that would otherwise keep CI red

## Cloud Deployment Guidance

This repo is ready for manual platform deployment, but platform-specific auto-deploy wiring is not committed yet. The safest production shape mirrors local Compose:

- one frontend service
- one backend web service
- one worker service
- managed Postgres with `pgvector`
- S3-compatible object storage

### Railway

Recommended Railway layout:

- `backend` web service from `backend/Dockerfile`
- `worker` private service from `backend/Dockerfile` with the worker command
- `frontend` web service from `frontend/Dockerfile`
- Railway Postgres, or external Postgres with `pgvector`
- object storage via external S3-compatible provider because local MinIO is only for development

Suggested commands:

- backend:
  - `uv run alembic upgrade head && uv run uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- worker:
  - `uv run alembic upgrade head && uv run python -m app.worker.main`

Railway env guidance:

- set the same application env vars as `.env.example`
- do not point `S3_ENDPOINT_URL` at MinIO unless you also deploy a compatible object store
- ensure `DATABASE_URL` points at a Postgres instance with the `vector` extension available
- set `FRONTEND_ORIGIN` to the deployed frontend URL

### Render

Recommended Render layout:

- frontend as a Web Service using `frontend/Dockerfile`
- backend as a Web Service using `backend/Dockerfile`
- worker as a Background Worker using the backend image and worker command
- Render Postgres only if it supports the required extension path, otherwise use external Postgres with `pgvector`
- external S3-compatible storage for uploaded files

Render setup notes:

- run Alembic migrations before or during backend startup
- keep backend and worker on the same environment variable set
- point the frontend at `/api` if it is reverse-proxied through the same host, or set a different base URL at build time if you expose backend separately

## Demo Walkthrough

Suggested MVP demo:

1. Start the stack with `docker compose up --build`.
2. Open `http://localhost:5173`.
3. Upload a small `.txt`, `.md`, or `.pdf` document.
4. Wait for the document status to become `ready`.
5. Ask a question clearly answered by that document and confirm citations appear.
6. Ask a question not supported by the uploaded content and confirm the assistant abstains.
7. Check `/health/live` and `/health/ready`.
8. Inspect backend or worker logs and trace a request via `x-request-id`.

## Troubleshooting

`POST /api/api/...` or `GET /api/api/...` returns `404`:

- the frontend should talk to relative paths while nginx already proxies `/api`
- if you see doubled `/api/api`, rebuild or refresh to pick up the current frontend bundle

Browser still shows old behavior after a fix:

- do a hard refresh to drop a stale JS bundle
- if needed, rebuild the frontend container with `docker compose up --build frontend`

Worker crashes with SQLAlchemy bind errors:

- confirm the worker opens sessions through the shared session factory and that `DATABASE_URL` is set correctly
- rebuilding the backend and worker images is the fastest way to pick up the current fix

Ingestion fails with provider batch-size errors:

- keep `CHUNK_MAX_BATCH_SIZE=10`
- larger values may exceed the embedding provider’s current request limit

Frontend returns `502` after backend rebuilds:

- ensure the frontend proxy uses Docker DNS resolution for `backend`
- recreate the frontend container if it still holds an old upstream state

`/health/ready` fails:

- check Postgres connectivity
- check object-storage credentials and bucket reachability
- check that `DASHSCOPE_API_KEY` is present in the running service

## Milestone Verification

The current milestone verification pass for this MVP is:

```bash
cd backend && uv sync --frozen --extra dev
cd backend && uv run ruff check app tests --ignore UP042
cd backend && uv run pytest tests -q
cd frontend && npm ci
cd frontend && npm run typecheck
cd frontend && npm run build
docker compose config
docker build -f backend/Dockerfile .
docker build -f frontend/Dockerfile .
```

If these are green and the upload-to-chat flow works in the browser, the repo is in good shape for MVP review or manual deployment setup.
