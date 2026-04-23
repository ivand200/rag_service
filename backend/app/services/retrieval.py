from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from math import sqrt

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.api.schemas import Citation
from app.db.models import Document, DocumentChunk
from app.services.chunking import ChunkCandidate


@dataclass(slots=True)
class RetrievedChunk:
    chunk_id: int
    document_id: int
    document_name: str
    text: str
    snippet: str
    page_number: int | None
    section_label: str | None
    score: float


def replace_document_chunks(
    session: Session,
    document: Document,
    chunks: Sequence[ChunkCandidate],
    embeddings: Sequence[list[float]],
) -> None:
    session.execute(delete(DocumentChunk).where(DocumentChunk.document_id == document.id))
    for chunk, embedding in zip(chunks, embeddings, strict=True):
        session.add(
            DocumentChunk(
                document_id=document.id,
                chunk_index=chunk.chunk_index,
                text=chunk.text,
                snippet=chunk.snippet,
                embedding=embedding,
                token_count=chunk.token_count,
                page_number=chunk.page_number,
                section_label=chunk.section_label,
            )
        )


async def search_ready_chunks(
    *,
    session: AsyncSession,
    workspace_id: int,
    query_embedding: Sequence[float],
    top_k: int,
) -> list[RetrievedChunk]:
    base_statement = (
        select(DocumentChunk, Document)
        .join(Document, Document.id == DocumentChunk.document_id)
        .where(Document.workspace_id == workspace_id, Document.status == "ready")
    )

    if _get_dialect_name(session) == "postgresql":
        distance = DocumentChunk.embedding.cosine_distance(list(query_embedding))
        result = await session.execute(
            base_statement.add_columns(distance.label("distance"))
            .order_by(distance.asc())
            .limit(top_k)
        )
        rows = result.all()
        return [
            RetrievedChunk(
                chunk_id=chunk.id,
                document_id=document.id,
                document_name=document.filename,
                text=chunk.text,
                snippet=chunk.snippet,
                page_number=chunk.page_number,
                section_label=chunk.section_label,
                score=max(0.0, 1.0 - float(distance_value)),
            )
            for chunk, document, distance_value in rows
        ]

    scored_chunks: list[RetrievedChunk] = []
    result = await session.execute(base_statement)
    for chunk, document in result.all():
        score = _cosine_similarity(query_embedding, chunk.embedding)
        scored_chunks.append(
            RetrievedChunk(
                chunk_id=chunk.id,
                document_id=document.id,
                document_name=document.filename,
                text=chunk.text,
                snippet=chunk.snippet,
                page_number=chunk.page_number,
                section_label=chunk.section_label,
                score=score,
            )
        )

    scored_chunks.sort(key=lambda item: item.score, reverse=True)
    return scored_chunks[:top_k]


def build_citations(chunks: Sequence[RetrievedChunk]) -> list[Citation]:
    return [
        Citation(
            document_id=chunk.document_id,
            document_name=chunk.document_name,
            chunk_id=chunk.chunk_id,
            snippet=chunk.snippet,
            page_number=chunk.page_number,
            section_label=chunk.section_label,
        )
        for chunk in chunks
    ]


def build_grounding_context(chunks: Sequence[RetrievedChunk]) -> str:
    sections: list[str] = []
    for index, chunk in enumerate(chunks, start=1):
        location_parts: list[str] = []
        if chunk.page_number is not None:
            location_parts.append(f"page {chunk.page_number}")
        if chunk.section_label:
            location_parts.append(f"section {chunk.section_label}")
        location = f" ({', '.join(location_parts)})" if location_parts else ""
        sections.append(f"[Source {index}] {chunk.document_name}{location}\n{chunk.text}")
    return "\n\n".join(sections)


def _get_dialect_name(session: AsyncSession) -> str | None:
    bind = session.bind
    if bind is None:
        return None
    return bind.sync_engine.dialect.name


def _cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0

    numerator = sum(
        left_value * right_value for left_value, right_value in zip(left, right, strict=True)
    )
    left_norm = sqrt(sum(value * value for value in left))
    right_norm = sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return numerator / (left_norm * right_norm)
