# Deployment

This repo is ready for manual platform deployment, but platform-specific auto-deploy wiring is intentionally out of scope. The safest production shape mirrors local Compose while replacing local infrastructure with managed services.

## Production Shape

Use separate processes or services for:

- Frontend web service.
- Backend web service.
- Worker process.
- Managed Postgres with `pgvector`.
- S3-compatible object storage.

The backend API and worker should share the same backend image, environment settings, database, object-storage bucket, and provider configuration. Docker-based workflows run Alembic migrations before starting the backend API or worker.

## Required Configuration

Set the same application variables described in `.env.example`, including:

- `DATABASE_URL`
- `FRONTEND_ORIGIN`
- `OPENAI_API_KEY`
- `OPENAI_BASE_URL`
- `CHAT_MODEL`
- `EMBEDDING_MODEL`
- `VITE_CLERK_PUBLISHABLE_KEY`
- `CLERK_JWT_PUBLIC_KEY`
- `CLERK_AUTHORIZED_PARTIES`
- `S3_*`

Deployment constraints:

- The database must support the `vector` extension and stay aligned with the configured embedding dimensionality.
- Browser access assumes a configured `FRONTEND_ORIGIN` and backend CORS policy for that origin.
- Object storage is required for uploaded document bytes.
- Signed-in flows require matching Clerk frontend and backend configuration, including the publishable key, JWT public key, and authorized party settings.
- Frontend auth and API configuration are build-time concerns for the Vue app, so deploy-time frontend builds must receive the correct public values.

## Railway

Recommended Railway layout:

- `backend` web service from `backend/Dockerfile`.
- `worker` private service from `backend/Dockerfile` with the worker command.
- `frontend` web service from `frontend/Dockerfile`.
- Railway Postgres, or external Postgres with `pgvector`.
- External S3-compatible object storage. Local MinIO is only for development.

Suggested commands:

Backend:

```bash
uv run alembic upgrade head && uv run uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

Worker:

```bash
uv run alembic upgrade head && uv run python -m app.worker.main
```

Railway notes:

- Set the same application env vars as `.env.example`.
- Do not point `S3_ENDPOINT_URL` at MinIO unless you also deploy a compatible object store.
- Ensure `DATABASE_URL` points at a Postgres instance with the `vector` extension available.
- Set `FRONTEND_ORIGIN` to the deployed frontend URL.

## Render

Recommended Render layout:

- Frontend as a Web Service using `frontend/Dockerfile`.
- Backend as a Web Service using `backend/Dockerfile`.
- Worker as a Background Worker using the backend image and worker command.
- Render Postgres only if it supports the required extension path; otherwise use external Postgres with `pgvector`.
- External S3-compatible storage for uploaded files.

Render notes:

- Run Alembic migrations before or during backend startup.
- Keep backend and worker on the same environment variable set.
- Point the frontend at `/api` if it is reverse-proxied through the same host, or set a different base URL at build time if backend is exposed separately.

## Rollback Notes

No database rollback strategy is documented here beyond normal Alembic migration practice. For demo-oriented manual deploys, prefer small changes, verify migrations in a disposable environment first, and keep frontend, backend, and worker versions aligned.

## Related Docs

- [Local development](./local-development.md)
- [Testing](./testing.md)
- [Troubleshooting](./troubleshooting.md)
