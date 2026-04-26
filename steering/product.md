# Product Steering

## Purpose
- Build an interview-ready, portfolio-quality RAG service that demonstrates production-minded backend and full-stack engineering.
- Provide a chat-first document Q&A product for a single shared workspace.
- Show realistic service boundaries: authentication, document upload, background ingestion, vector retrieval, streaming chat, citations, abstention, persistence, and reproducible local runtime.

## Users / Actors
- Signed-in demo users who upload documents and ask grounded questions through the web UI.
- The project owner, who uses the repo for LinkedIn, portfolio, and technical-interview demonstrations.
- Clerk, FastAPI, the worker, Postgres/pgvector, object storage, and the model provider as collaborating system actors.

## Core Workflows
- Sign in or sign up through Clerk before entering the workspace.
- Upload `.txt`, `.md`, or `.pdf` files and wait for asynchronous ingestion to mark them ready.
- Ask questions against the shared ready-document corpus and receive cited, grounded answers.
- Preserve per-user chat sessions and histories while sharing ready documents at workspace scope.
- Generate a stable chat-session title asynchronously after the first user message.
- Stream chat answers through the backend, then persist the completed assistant turn with citations.
- Abstain instead of guessing when retrieval evidence is too weak.
- Run locally or deploy manually with the same frontend, backend, worker, database, and object-storage shape.

## Core Domain Concepts
- `Workspace`: the singleton shared container for documents and chat activity in this MVP.
- `Document`: uploaded source file with an ingestion status such as `pending`, `processing`, `ready`, or `failed`.
- `IngestionJob`: worker-owned processing record for parsing, chunking, embedding, and indexing a document.
- `DocumentChunk`: indexed retrieval unit with text, metadata, and an embedding.
- `ChatSession`: Clerk-user-owned conversation thread inside the shared workspace, titled asynchronously after use.
- `ChatMessage`: persisted user or assistant turn, including citations for grounded assistant replies.

## Scope Boundaries
- Keep the core product to a single-workspace MVP, not multi-tenant workspace management.
- Limit supported ingestion formats to `.txt`, `.md`, and `.pdf`.
- Optimize for grounded document Q&A, not general-purpose open chat.
- Leave billing, collaboration permissions, granular document ownership, and advanced document-management flows out of the core demo.
- Treat session rename, delete, and archive flows as non-core unless a task explicitly adds them.

## Durable Constraints
- Grounded answers should cite retrieved document context.
- Weak retrieval support should produce abstention behavior.
- Newly uploaded documents must not be searchable until ingestion succeeds.
- Workspace access and protected API calls assume a valid signed-in Clerk session.
- Demo readiness depends on local reproducibility, health checks, and observable upload, ingestion, and chat flows.
- Keep the project explainable in interviews while preserving realistic production architecture.
