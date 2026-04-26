# Testing

This guide collects the local and CI validation paths for RAG Service.

## Backend Checks

```bash
cd backend
uv sync --extra dev
uv run ruff check app tests --ignore UP042
uv run pytest tests -q
```

The Ruff invocation intentionally ignores `UP042` while the repo still carries a compatibility pattern in `backend/app/db/models.py`.

## Frontend Checks

```bash
cd frontend
npm ci
npm run typecheck
npm run build
```

## Docker Validation

```bash
docker compose config
docker build -f backend/Dockerfile .
docker build -f frontend/Dockerfile .
```

## RAG Quality Checks

Deterministic service-boundary checks live in pytest rather than a custom eval platform:

```bash
cd backend
uv run pytest tests/evals -q
```

These tests seed workspace documents and chunks with deterministic embeddings, then verify retrieval, citation correctness, abstention, ready-document filtering, and chunk-setting comparison.

Current boundaries:

- Live provider evals, report runners, and larger retrieval experiments are postponed until the project has a curated real demo corpus.
- Product chat defaults are unchanged by these checks.
- Retrieval and chunking default changes should still require evidence from representative cases.

## E2E Smoke Tests

The Playwright E2E layer runs against Docker Compose so it exercises the built frontend, nginx proxy, backend, worker, Postgres, and MinIO together.

Run the full E2E smoke suite from the repository root:

```bash
make e2e
```

If `5173` is already in use locally:

```bash
E2E_FRONTEND_PORT=5174 make e2e
```

The `e2e` target starts the deterministic stack, runs Playwright, then tears the stack down with volumes.

For manual debugging, you can keep the stack running:

Start the deterministic E2E stack:

```bash
make e2e-up
```

If `5173` is already in use locally, choose another frontend port:

```bash
E2E_FRONTEND_PORT=5174 make e2e-up
```

Run the browser smoke suite:

```bash
cd frontend
npm run e2e
```

When using a non-default local frontend port:

```bash
cd frontend
PLAYWRIGHT_BASE_URL=http://localhost:5174 npm run e2e
```

Shut down and remove E2E volumes:

```bash
make e2e-down
```

Coverage:

- Deterministic auth and sign-up route surfaces without loading Clerk.
- Upload-to-ready document ingestion through the worker.
- Grounded streamed chat with citations.
- Unsupported chat abstention.

E2E mode is explicitly gated by `APP_ENV=e2e` and `VITE_APP_ENV=e2e`; normal development and production continue to use Clerk and the configured OpenAI-compatible provider.

## CI Expectations

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
- `.github/workflows/e2e.yml`
  - Playwright Chromium install
  - Docker Compose E2E stack startup
  - browser smoke tests against the built app
  - Playwright report upload

Pull requests and pushes to `main` are expected to pass these workflows before merge.

## Milestone Verification

The current milestone verification pass is:

```bash
cd backend && uv sync --frozen --extra dev
cd backend && uv run ruff check app tests --ignore UP042
cd backend && uv run pytest tests -q
cd frontend && npm ci
cd frontend && npm run typecheck
cd frontend && npm run build
docker compose config
docker compose -f docker-compose.yml -f docker-compose.e2e.yml config
docker build -f backend/Dockerfile .
docker build -f frontend/Dockerfile .
```

If these are green and the upload-to-chat flow works in the browser, the repo is in good shape for MVP review or manual deployment setup.

## Related Docs

- [Local development](./local-development.md)
- [Demo script](./demo-script.md)
- [Troubleshooting](./troubleshooting.md)
