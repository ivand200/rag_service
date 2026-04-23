from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.db.constants import (
    EMBEDDING_VECTOR_DIMENSIONS,
    SINGLETON_WORKSPACE_ID,
    SINGLETON_WORKSPACE_NAME,
)
from app.db.types import EmbeddingVector


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class DocumentStatus(StrEnum):
    pending = "pending"
    processing = "processing"
    ready = "ready"
    failed = "failed"


class JobStatus(StrEnum):
    queued = "queued"
    processing = "processing"
    completed = "completed"
    failed = "failed"


class MessageRole(StrEnum):
    user = "user"
    assistant = "assistant"


class Workspace(TimestampMixin, Base):
    __tablename__ = "workspace"
    __table_args__ = (
        CheckConstraint(f"id = {SINGLETON_WORKSPACE_ID}", name="ck_workspace_singleton_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), default=SINGLETON_WORKSPACE_NAME)

    documents: Mapped[list[Document]] = relationship(back_populates="workspace")
    sessions: Mapped[list[ChatSession]] = relationship(back_populates="workspace")
    messages: Mapped[list[ChatMessage]] = relationship(back_populates="workspace")


class Document(TimestampMixin, Base):
    __tablename__ = "document"

    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspace.id", ondelete="CASCADE"))
    filename: Mapped[str] = mapped_column(String(512))
    content_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    storage_key: Mapped[str] = mapped_column(String(512), unique=True)
    status: Mapped[str] = mapped_column(String(32), default=DocumentStatus.pending.value)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_hash: Mapped[str] = mapped_column(String(128))

    workspace: Mapped[Workspace] = relationship(back_populates="documents")
    ingestion_jobs: Mapped[list[IngestionJob]] = relationship(back_populates="document")
    chunks: Mapped[list[DocumentChunk]] = relationship(back_populates="document")


class IngestionJob(TimestampMixin, Base):
    __tablename__ = "ingestion_job"
    __table_args__ = (Index("ix_ingestion_job_status_created_at_id", "status", "created_at", "id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("document.id", ondelete="CASCADE"), unique=True
    )
    status: Mapped[str] = mapped_column(String(32), default=JobStatus.queued.value)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    document: Mapped[Document] = relationship(back_populates="ingestion_jobs")


class DocumentChunk(TimestampMixin, Base):
    __tablename__ = "document_chunk"
    __table_args__ = (UniqueConstraint("document_id", "chunk_index"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("document.id", ondelete="CASCADE"))
    chunk_index: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    snippet: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float]] = mapped_column(EmbeddingVector(EMBEDDING_VECTOR_DIMENSIONS))
    token_count: Mapped[int] = mapped_column(Integer)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    section_label: Mapped[str | None] = mapped_column(String(255), nullable=True)

    document: Mapped[Document] = relationship(back_populates="chunks")


class ChatSession(TimestampMixin, Base):
    __tablename__ = "chat_session"
    __table_args__ = (
        Index(
            "ix_chat_session_workspace_id_clerk_user_id_updated_at_id",
            "workspace_id",
            "clerk_user_id",
            "updated_at",
            "id",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspace.id", ondelete="CASCADE"))
    clerk_user_id: Mapped[str] = mapped_column(String(255))
    title: Mapped[str] = mapped_column(String(255), default="New session")

    workspace: Mapped[Workspace] = relationship(back_populates="sessions")
    messages: Mapped[list[ChatMessage]] = relationship(back_populates="session")
    title_job: Mapped[ChatSessionTitleJob | None] = relationship(
        back_populates="session",
        uselist=False,
    )


class ChatSessionTitleJob(TimestampMixin, Base):
    __tablename__ = "chat_session_title_job"
    __table_args__ = (
        Index("ix_chat_session_title_job_status_id", "status", "id"),
        UniqueConstraint("session_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("chat_session.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(32), default=JobStatus.queued.value)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    session: Mapped[ChatSession] = relationship(back_populates="title_job")


class ChatMessage(TimestampMixin, Base):
    __tablename__ = "chat_message"
    __table_args__ = (
        Index(
            "ix_chat_message_workspace_id_clerk_user_id_id",
            "workspace_id",
            "clerk_user_id",
            "id",
        ),
        Index("ix_chat_message_session_id_id", "session_id", "id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspace.id", ondelete="CASCADE"))
    clerk_user_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    session_id: Mapped[int | None] = mapped_column(
        ForeignKey("chat_session.id", ondelete="SET NULL"), nullable=True
    )
    role: Mapped[str] = mapped_column(String(32))
    content: Mapped[str] = mapped_column(Text)
    grounded: Mapped[bool] = mapped_column(Boolean, default=False)
    citations_json: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSON, default=list, nullable=True
    )

    workspace: Mapped[Workspace] = relationship(back_populates="messages")
    session: Mapped[ChatSession | None] = relationship(back_populates="messages")
