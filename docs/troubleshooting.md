# Troubleshooting

Use this guide for common local development and demo issues.

## Doubled `/api/api` Paths Return `404`

Symptoms:

- `POST /api/api/...` or `GET /api/api/...` returns `404`.

Checks:

- The frontend should call relative API paths while nginx already proxies `/api`.
- Rebuild or refresh to pick up the current frontend bundle if an older build is still cached.

Commands:

```bash
docker compose up --build frontend
```

## Browser Shows Old Behavior

Checks:

- Do a hard refresh to drop a stale JavaScript bundle.
- Rebuild the frontend container if the browser still shows stale behavior.

```bash
docker compose up --build frontend
```

## Worker Crashes With SQLAlchemy Bind Errors

Checks:

- Confirm the worker opens sessions through the shared session factory.
- Confirm `DATABASE_URL` is set correctly for the worker environment.
- Rebuild backend and worker images to pick up current code.

```bash
docker compose up --build backend worker
```

## Ingestion Fails With Provider Batch-Size Errors

Checks:

- Keep `CHUNK_MAX_BATCH_SIZE=10`.
- Larger values may exceed the embedding provider's current request limit.

## Frontend Returns `502` After Backend Rebuilds

Checks:

- Ensure the frontend proxy uses Docker DNS resolution for `backend`.
- Recreate the frontend container if it still holds an old upstream state.

```bash
docker compose up --build frontend
```

## `/health/ready` Fails

Checks:

- Confirm Postgres connectivity.
- Confirm object-storage credentials and bucket reachability.
- Confirm `OPENAI_API_KEY` is present in the running service.
- Confirm the backend and worker use the same expected database and object-storage configuration.

Useful URLs:

- Live health: `http://localhost:8000/health/live`
- Ready health: `http://localhost:8000/health/ready`
- MinIO console: `http://localhost:9001`

## Chat Does Not Return Citations

Checks:

- Confirm the uploaded document reached `ready`.
- Ask a question clearly supported by the uploaded content.
- Inspect backend logs for retrieval count, grounding status, `session_id`, and message IDs.
- Use `x-request-id` or `x-correlation-id` from response headers to follow the request through logs.

## Unsupported Questions Do Not Abstain

Checks:

- Confirm the question is genuinely outside the uploaded ready-document corpus.
- Check retrieval threshold and provider configuration.
- Run focused RAG quality checks:

```bash
cd backend
uv run pytest tests/evals -q
```

## Related Docs

- [Local development](./local-development.md)
- [Testing](./testing.md)
- [Demo script](./demo-script.md)
