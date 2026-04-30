# Demo Script

This script is designed for technical interview walkthroughs and demos.

## Goal

Show that RAG Service is a production-minded RAG application with realistic service boundaries: authenticated browser access, upload and ingestion, persistent chat sessions, background work, vector retrieval, citations, abstention, health checks, and observable logs.

## Setup

1. Start the stack:

   ```bash
   docker compose up --build
   ```

2. Open the app:

   `http://localhost:5173`

3. Keep health endpoints available:

   - `http://localhost:8000/health/live`
   - `http://localhost:8000/health/ready`

4. Prepare a small `.txt`, `.md`, or `.pdf` document with a few concrete facts that are easy to ask about.

## Walkthrough

1. Sign in through Clerk.
2. Upload the prepared document.
3. Point out that the document is stored first, then processed asynchronously by the worker.
4. Wait for the document status to move to `ready`.
5. Ask a question with an answer clearly present in the document.
6. Show the streamed answer text and final persisted assistant message.
7. Show citations and explain that only ready document chunks are eligible for retrieval.
8. Ask a question that is not supported by the uploaded content.
9. Show the abstention behavior instead of a fabricated answer.
10. Create or switch chat sessions and explain that sessions are scoped per signed-in Clerk user while ready documents are shared at the workspace level.
11. Show `/health/live` and `/health/ready`.
12. Inspect backend or worker logs and trace a request with `x-request-id` or `x-correlation-id`.

## Talking Points

- The product is intentionally a single-workspace MVP rather than a multi-tenant system.
- Document ingestion is asynchronous so upload latency is separated from parsing, chunking, embedding, and indexing.
- Postgres with `pgvector` keeps relational state and vector search in one local development database.
- Object storage keeps uploaded source bytes outside the relational database.
- The worker reuses backend service code and handles both ingestion jobs and chat-session title jobs.
- Clerk protects the browser workspace and backend API routes.
- The chat path supports streaming responses while preserving durable session history.
- Grounding and abstention are product requirements, not UI decorations.
- Docker Compose makes the demo reproducible across frontend, backend, worker, Postgres, and MinIO.

## Future Video Slot

The root [README](../README.md) has a placeholder for a future demo video or GIF. When a video is ready, replace the placeholder with a link or thumbnail that shows:

- Upload to `ready`.
- Grounded answer with citations.
- Unsupported question abstention.
- Health or log trace for one request.

## Related Docs

- [Local development](./local-development.md)
- [Testing](./testing.md)
- [Troubleshooting](./troubleshooting.md)
