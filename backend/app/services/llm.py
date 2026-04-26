from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from inspect import isawaitable
from typing import Any, cast

from openai import AsyncOpenAI

from app.config import Settings
from app.db.constants import EMBEDDING_VECTOR_DIMENSIONS
from app.db.models import ChatMessage

EMBEDDING_PROVIDER_MAX_BATCH_SIZE = 10


async def _maybe_await(value: object) -> Any:
    if isawaitable(value):
        return await cast("Any", value)
    return value


def resolve_sync(value: object) -> Any:
    if not isawaitable(value):
        return value

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(cast("Any", value))

    raise RuntimeError(
        "Cannot synchronously resolve an async service call while an event loop is running."
    )


class EmbeddingService:
    def __init__(self, settings: Settings, client: AsyncOpenAI | object | None = None) -> None:
        self.settings = settings
        self.client = client or AsyncOpenAI(
            api_key=settings.provider_api_key,
            base_url=settings.provider_base_url,
        )

    async def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        items = list(texts)
        if not items:
            return []

        effective_batch_size = min(
            self.settings.chunk_max_batch_size,
            EMBEDDING_PROVIDER_MAX_BATCH_SIZE,
        )
        embeddings: list[list[float]] = []

        for index in range(0, len(items), effective_batch_size):
            batch = items[index : index + effective_batch_size]
            response = await _maybe_await(
                self.client.embeddings.create(
                    model=self.settings.embedding_model,
                    input=batch,
                    dimensions=EMBEDDING_VECTOR_DIMENSIONS,
                )
            )
            embeddings.extend(list(item.embedding) for item in response.data)

        return embeddings


@dataclass(slots=True)
class ChatTurn:
    role: str
    content: str


@dataclass(slots=True)
class RetrievalPlan:
    query: str
    broad: bool = False


class ChatService:
    not_supported_token = "NOT_SUPPORTED"

    def __init__(self, settings: Settings, client: AsyncOpenAI | object | None = None) -> None:
        self.settings = settings
        self.client = client or AsyncOpenAI(
            api_key=settings.provider_api_key,
            base_url=settings.provider_base_url,
        )

    async def generate_answer(
        self,
        *,
        question: str,
        context: str,
        history: Sequence[ChatMessage],
    ) -> str:
        response = await _maybe_await(
            self.client.chat.completions.create(
                model=self.settings.chat_model,
                messages=self._build_answer_messages(
                    question=question,
                    context=context,
                    history=history,
                ),
            )
        )
        return response.choices[0].message.content or self.not_supported_token

    async def generate_retrieval_plan(
        self,
        *,
        message: str,
        history: Sequence[ChatMessage],
    ) -> RetrievalPlan:
        response = await _maybe_await(
            self.client.chat.completions.create(
                model=self.settings.chat_model,
                messages=self._build_retrieval_plan_messages(message=message, history=history),
            )
        )
        content = response.choices[0].message.content or ""
        return _parse_retrieval_plan(content, fallback_message=message)

    async def stream_answer(
        self,
        *,
        question: str,
        context: str,
        history: Sequence[ChatMessage],
    ) -> AsyncIterator[str]:
        stream = await _maybe_await(
            self.client.chat.completions.create(
                model=self.settings.chat_model,
                messages=self._build_answer_messages(
                    question=question,
                    context=context,
                    history=history,
                ),
                stream=True,
            )
        )

        try:
            async for event in stream:
                for text in _extract_stream_text(event):
                    if text:
                        yield text
        finally:
            close = getattr(stream, "aclose", None)
            if callable(close):
                await _maybe_await(close())

    def _build_answer_messages(
        self,
        *,
        question: str,
        context: str,
        history: Sequence[ChatMessage],
    ) -> list[dict[str, str]]:
        messages: list[dict[str, str]] = [
            {
                "role": "system",
                "content": (
                    "You answer questions using only the provided document context. "
                    f"If the context is insufficient, reply exactly with "
                    f"{self.not_supported_token}. "
                    "Do not use outside knowledge. Do not fabricate citations."
                ),
            }
        ]
        for turn in history:
            messages.append({"role": turn.role, "content": turn.content})

        messages.append(
            {
                "role": "user",
                "content": (
                    f"Question:\n{question}\n\n"
                    f"Document context:\n{context}\n\n"
                    "Answer concisely and directly."
                ),
            }
        )
        return messages

    def _build_retrieval_plan_messages(
        self,
        *,
        message: str,
        history: Sequence[ChatMessage],
    ) -> list[dict[str, str]]:
        history_text = "\n".join(
            f"{turn.role}: {turn.content}" for turn in history[-4:]
        ).strip()
        return [
            {
                "role": "system",
                "content": (
                    "Create a retrieval plan for a RAG system. Do not answer the user. "
                    "Return only compact JSON with keys: query and scope. "
                    "query must be a concise search request for the document corpus. "
                    "scope must be focused or broad. Use broad for questions that need "
                    "many parts of a document, such as counts, totals, complete lists, "
                    "summaries, comparisons, or questions about all components/items."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Recent chat history:\n{history_text or '(none)'}\n\n"
                    f"User message:\n{message}"
                ),
            },
        ]

    async def generate_session_title(self, *, first_user_message: str) -> str:
        response = await _maybe_await(
            self.client.chat.completions.create(
                model=self.settings.chat_model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Write a short, stable title for a chat session based only on the "
                            "user's first message. Keep it under 60 characters. "
                            "Do not use quotation marks or trailing punctuation."
                        ),
                    },
                    {
                        "role": "user",
                        "content": f"First message:\n{first_user_message}",
                    },
                ],
            )
        )
        return (response.choices[0].message.content or "").strip()


def _extract_stream_text(event: object) -> list[str]:
    texts: list[str] = []
    choices = getattr(event, "choices", None)
    if choices is None:
        return texts

    for choice in choices:
        delta = getattr(choice, "delta", None)
        if delta is None:
            continue

        content = getattr(delta, "content", None)
        if isinstance(content, str):
            texts.append(content)
            continue

        if content is None:
            continue

        for part in content:
            if isinstance(part, dict):
                text = part.get("text")
            else:
                text = getattr(part, "text", None)
            if text:
                texts.append(text)

    return texts


def _parse_retrieval_plan(content: str, *, fallback_message: str) -> RetrievalPlan:
    try:
        parsed = json.loads(_strip_json_fence(content))
    except json.JSONDecodeError:
        return _fallback_retrieval_plan(fallback_message)

    if not isinstance(parsed, dict):
        return _fallback_retrieval_plan(fallback_message)

    query_value = parsed.get("query")
    query = " ".join(str(query_value or "").split())
    if not query:
        query = " ".join(fallback_message.split())

    scope = str(parsed.get("scope") or "").casefold()
    return RetrievalPlan(
        query=query[:500],
        broad=scope == "broad" or _looks_like_broad_request(fallback_message),
    )


def _fallback_retrieval_plan(message: str) -> RetrievalPlan:
    query = " ".join(message.split())
    return RetrievalPlan(query=query[:500], broad=_looks_like_broad_request(message))


def fallback_retrieval_plan(message: str) -> RetrievalPlan:
    return _fallback_retrieval_plan(message)


def _strip_json_fence(content: str) -> str:
    stripped = content.strip()
    if not stripped.startswith("```"):
        return stripped

    lines = stripped.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _looks_like_broad_request(message: str) -> bool:
    normalized = message.casefold()
    broad_markers = (
        "how many",
        "how much",
        "count",
        "total",
        "all ",
        "list",
        "summarize",
        "summary",
        "compare",
        "components",
        "items",
    )
    return any(marker in normalized for marker in broad_markers)
