# Local Development

This guide covers the local runtime for RAG Service. The project is a single-workspace RAG app with authenticated browser access, document ingestion, shared ready documents, and per-user chat sessions.

## Repository Shape

- `backend/`: FastAPI API, SQLAlchemy models, Alembic migrations, worker pipeline, retrieval, and provider integration.
- `frontend/`: Vue 3 + Vite single-page app served by nginx in production mode.
- `docker-compose.yml`: local multi-service development runtime.
- `.env.example`: environment variable template for backend, frontend, storage, auth, and provider configuration.
- `specs/`: durable product, tech, and structure steering docs.
- `tasks/`: task-level design notes and implementation artifacts.

## Prerequisites

- Docker Desktop or Docker Engine with Compose.
- A valid OpenAI API key.
- Clerk frontend and backend configuration for signed-in browser flows.
- Node 20+ and `uv` if running frontend or backend checks outside Docker.

## Environment

Copy the example file and fill in required values:

```bash
cp .env.example .env
```

Important variables:

- `OPENAI_API_KEY`: required for embeddings and chat.
- `OPENAI_BASE_URL`: OpenAI-compatible provider endpoint; defaults to the OpenAI API.
- `CHAT_MODEL`: chat completion model.
- `EMBEDDING_MODEL`: embedding model.
- `RETRIEVAL_TOP_K`: focused retrieval chunk count for ordinary questions.
- `RETRIEVAL_EXPANDED_TOP_K`: broader chunk count for model-planned count/list/summary questions.
- `CHUNK_MAX_BATCH_SIZE`: defaults to `10` to match the current provider limit.
- `VITE_CLERK_PUBLISHABLE_KEY`: required by the Vue app for Clerk browser auth.
- `CLERK_JWT_PUBLIC_KEY`: required by the backend to verify Clerk bearer tokens.
- `CLERK_AUTHORIZED_PARTIES`: optional comma-separated allowlist for Clerk token `azp`; defaults to `FRONTEND_ORIGIN`.
- `FRONTEND_ORIGIN`: browser origin allowed by backend CORS.
- `DATABASE_URL`: backend database connection string.
- `S3_*`: object-storage settings for uploaded source files.

Local notes:

- Docker Compose overrides `DATABASE_URL` and `S3_ENDPOINT_URL` so containers talk to `postgres` and `minio` on the Compose network.
- The backend loads environment from either the repo-root `.env` or a local `.env`, depending on the working directory.
- Clerk uses the repo-root `.env` values for both frontend and backend local runs, so fill in both the publishable key and JWT public key before testing signed-in flows.

## Start The Stack

```bash
docker compose up --build
```

Useful endpoints:

- App UI: `http://localhost:5173`
- Backend API: `http://localhost:8000`
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

## Runtime Services

- `frontend`: nginx serves the built Vue app and proxies `/api/*` to the backend.
- `backend`: FastAPI app for health, workspace, document, and session-aware chat endpoints.
- `worker`: long-running loop that claims queued ingestion jobs and chat-session title jobs.
- `postgres`: relational store plus `pgvector` index storage.
- `minio`: S3-compatible object storage for raw uploaded files.
- `minio-bootstrap`: one-shot bucket bootstrap helper for local development.

## Backend API Surface

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
- `POST /api/chat/messages/stream`

## Frontend Behavior

- Upload panel and document status rail.
- Session switcher with `New session`.
- Active-session chat history scoped per signed-in user.
- Citation rendering for grounded answers.
- Streamed assistant text for live chat sends, with final reconciliation to the persisted server message.
- Polling while ingestion is still active.
- Polling for async session-title updates after the first send.

## Ingestion And Chat Workflow

Document ingestion:

- Supported extensions are `.txt`, `.md`, and `.pdf`.
- Uploads are stored in object storage first.
- The worker updates document state through `pending -> processing -> ready` or `failed`.
- Failed jobs are retried up to `INGESTION_MAX_RETRIES`.
- Documents are not searchable until ingestion completes successfully.

Retrieval and answer generation:

- Only `ready` document chunks are eligible for retrieval.
- Every chat session searches the same shared ready-document corpus.
- The API embeds the user query, ranks chunks with vector similarity, and uses a minimum grounding threshold.
- The live send path streams assistant text over `POST /api/chat/messages/stream`.
- Completed assistant messages remain the durable session history.
- When supporting context is insufficient, the assistant returns an abstention response instead of hallucinating.
- Grounded answers include citations with document and chunk metadata.

Session behavior:

- Each authenticated Clerk user can keep multiple independent chat sessions.
- The backend auto-creates one empty `New session` for first-time users.
- Creating a new session keeps earlier sessions intact, reuses the latest session when it is still empty, and otherwise creates a fresh session.
- Session rename, delete, and archive flows are intentionally out of scope in this MVP.

## Health And Observability

Health endpoints:

- `/health/live`: lightweight process liveness plus service metadata.
- `/health/ready`: checks database connectivity, object storage bucket access, and provider configuration presence.

Observability behavior:

- API requests emit structured JSON logs.
- Request middleware assigns or forwards `x-request-id`.
- `x-correlation-id` is accepted from the client or defaults to the request ID.
- Upload, chat, worker, and ingestion events include fields such as `document_id`, `job_id`, `workspace_id`, `session_id`, message IDs, status, and timing.

Debugging tip:

- Use the shared `request_id` or `correlation_id` in response headers and logs to trace an upload or chat request across the backend path.

## Related Docs

- [Testing](./testing.md)
- [Troubleshooting](./troubleshooting.md)
- [Demo script](./demo-script.md)
