from __future__ import annotations

import asyncio
from collections.abc import Sequence
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
            api_key=settings.dashscope_api_key,
            base_url=str(settings.dashscope_base_url),
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


class ChatService:
    not_supported_token = "NOT_SUPPORTED"

    def __init__(self, settings: Settings, client: AsyncOpenAI | object | None = None) -> None:
        self.settings = settings
        self.client = client or AsyncOpenAI(
            api_key=settings.dashscope_api_key,
            base_url=str(settings.dashscope_base_url),
        )

    async def generate_answer(
        self,
        *,
        question: str,
        context: str,
        history: Sequence[ChatMessage],
    ) -> str:
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
        response = await _maybe_await(
            self.client.chat.completions.create(
                model=self.settings.chat_model,
                messages=messages,
            )
        )
        return response.choices[0].message.content or self.not_supported_token

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
