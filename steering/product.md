# Product Steering

## Purpose
<<<<<<< Updated upstream
=======
<<<<<<< Updated upstream
- Build an interview-ready, portfolio-quality RAG service that demonstrates production-minded backend and full-stack engineering.
>>>>>>> Stashed changes
- Provide a chat-first document Q&A product for a single shared workspace.
- Show realistic service boundaries: authentication, document upload, background ingestion, vector retrieval, streaming chat, citations, abstention, persistence, and reproducible local runtime.

## Users / Actors
- Signed-in demo users who upload documents and ask grounded questions through the web UI.
- Clerk, FastAPI, the worker, Postgres/pgvector, object storage, and the model provider as collaborating system actors.
=======

- RAG Service is a production-minded web application for uploading documents and asking grounded questions over the shared ready-document corpus.
- The product should demonstrate real service behavior: authenticated browser flows, asynchronous ingestion, retrieval-backed answers, citations, abstention when evidence is weak, and reproducible local operation.
- Favor product behavior that is explainable in a demo: users should be able to trace a document from upload, through ingestion, into cited chat answers.

## Users / Actors

- Signed-in browser user: uploads documents, monitors ingestion status, creates or resumes personal chat sessions, asks questions, and inspects citations.
- Local development user: uses the local auth bypass for day-to-day work while exercising the same document, ingestion, retrieval, chat, citation, and session behavior.
- Worker process: claims queued ingestion and chat-session title jobs and updates durable database state.
- Operator or developer: verifies health, logs, local infrastructure, CI checks, and demo readiness.
>>>>>>> Stashed changes

## Core Workflows

- Document upload: accept `.txt`, `.md`, or `.pdf`; store the source object; create a document row; enqueue ingestion; show `pending`, `processing`, `ready`, or `failed`.
- Document ingestion: parse, chunk, embed, index chunks, mark the document ready, and retry failures with scheduled backoff before final failure.
- Grounded chat: use the signed-in user's chat session, retrieve from shared ready chunks, stream answer text, persist final messages, include citations when grounded, and abstain when evidence is insufficient.
- Session management: support multiple per-user chat sessions, auto-create an initial session, and asynchronously title sessions after the first user message.
- Demo and validation: local Docker Compose should exercise frontend, backend, worker, Postgres with pgvector, MinIO, and provider configuration together.

## Core Domain Concepts

- Workspace: currently a singleton shared workspace that owns all uploaded documents and chat data.
- Document: uploaded source file metadata and lifecycle state.
- Ingestion job: durable background work item for parsing, chunking, embedding, and indexing a document.
- Document chunk: retrievable text segment with embedding, snippet, and optional page or section metadata.
- Chat session: per-user conversation thread over the shared ready-document corpus.
- Chat message: persisted user or assistant message, with grounded flag and optional citations for assistant output.
- Citation: document and chunk metadata used to show which evidence supported an answer.

## Scope Boundaries

- Supported upload types are `.txt`, `.md`, and `.pdf`; other file types should remain explicit product decisions.
- Ready documents are shared across users in the singleton workspace, while chat sessions and histories are scoped per authenticated user.
- Unsupported or weakly supported questions should abstain instead of inventing answers.
- Local auth mode is for local development only; realistic auth validation uses Clerk.
- Session rename, delete, and archive flows are currently out of scope.
- The app is not a general multi-tenant knowledge-base product until workspace and permission semantics are deliberately redesigned.

## Durable Constraints

- New user-facing features should preserve the upload-to-ready-to-cited-chat story.
- Changes to retrieval, chunking, grounding thresholds, or abstention behavior need behavior tests or eval coverage with representative evidence.
- UI and API changes should keep local auth and Clerk mode aligned unless intentionally changing auth behavior.
- Features that alter document visibility, workspace ownership, auth, data deletion, or citation trust require deeper product and interface review.
