from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class DocumentSummary(BaseModel):
    id: int
    filename: str
    status: str
    content_type: str | None
    error_summary: str | None
    created_at: datetime
    updated_at: datetime


class DocumentDetail(DocumentSummary):
    storage_key: str


class DocumentListResponse(BaseModel):
    documents: list[DocumentSummary]


class Citation(BaseModel):
    document_id: int
    document_name: str
    chunk_id: int
    snippet: str
    page_number: int | None = None
    section_label: str | None = None


class ChatMessageRead(BaseModel):
    id: int
    role: str
    content: str
    grounded: bool
    citations_json: list[Citation] | None
    created_at: datetime


class ChatSessionRead(BaseModel):
    id: int
    title: str
    created_at: datetime
    updated_at: datetime


class ChatSessionsResponse(BaseModel):
    sessions: list[ChatSessionRead]


class ChatMessageCreate(BaseModel):
    session_id: int
    message: str


class ChatHistoryResponse(BaseModel):
    messages: list[ChatMessageRead]


class ChatExchangeResponse(BaseModel):
    user_message: ChatMessageRead
    assistant_message: ChatMessageRead
    citations: list[Citation]
    grounded: bool


class WorkspaceResponse(BaseModel):
    id: int
    name: str
    documents: list[DocumentSummary]
    messages: list[ChatMessageRead]
