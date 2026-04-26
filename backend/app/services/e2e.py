from __future__ import annotations

from collections.abc import AsyncIterator, Sequence

from app.config import Settings
from app.db.constants import EMBEDDING_VECTOR_DIMENSIONS
from app.db.models import ChatMessage
from app.services.auth import AuthenticatedUser
from app.services.llm import ChatService, EmbeddingService, RetrievalPlan

E2E_BEARER_TOKEN = "e2e-user"
E2E_CLERK_USER_ID = "e2e-user"
E2E_USER_LABEL = "E2E Demo User"


def authenticate_e2e_token(*, token: str, settings: Settings) -> AuthenticatedUser | None:
    if not settings.is_e2e or token != E2E_BEARER_TOKEN:
        return None

    return AuthenticatedUser(clerk_user_id=E2E_CLERK_USER_ID, session_id="e2e-session")


def create_embedding_service(settings: Settings) -> EmbeddingService:
    if settings.is_e2e:
        return E2EEmbeddingService(settings)
    return EmbeddingService(settings)


def create_chat_service(settings: Settings) -> ChatService:
    if settings.is_e2e:
        return E2EChatService(settings)
    return ChatService(settings)


class E2EEmbeddingService(EmbeddingService):
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = None

    async def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        return [_embedding_for_text(text) for text in texts]


class E2EChatService(ChatService):
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = None

    async def generate_answer(
        self,
        *,
        question: str,
        context: str,
        history: Sequence[ChatMessage],
    ) -> str:
        return _answer_for_context(question=question, context=context)

    async def stream_answer(
        self,
        *,
        question: str,
        context: str,
        history: Sequence[ChatMessage],
    ) -> AsyncIterator[str]:
        answer = _answer_for_context(question=question, context=context)
        for chunk in _stream_chunks(answer):
            yield chunk

    async def generate_retrieval_plan(
        self,
        *,
        message: str,
        history: Sequence[ChatMessage],
    ) -> RetrievalPlan:
        del history
        return RetrievalPlan(query=message, broad=False)

    async def generate_session_title(self, *, first_user_message: str) -> str:
        lower_message = first_user_message.lower()
        if any(keyword in lower_message for keyword in ("paris", "france", "capital")):
            return "Paris Question"
        if any(keyword in lower_message for keyword in ("upload", "format", ".txt", ".md", ".pdf")):
            return "Upload Formats"
        return "Document Question"


def _answer_for_context(*, question: str, context: str) -> str:
    lower_question = question.lower()
    lower_context = context.lower()
    if not lower_context.strip():
        return ChatService.not_supported_token

    if "paris" in lower_context and any(
        keyword in lower_question for keyword in ("paris", "france", "capital")
    ):
        return "Paris is the capital of France, based on the uploaded document."

    if any(keyword in lower_context for keyword in (".txt", ".md", ".pdf")) and any(
        keyword in lower_question for keyword in ("upload", "format", ".txt", ".md", ".pdf")
    ):
        return "The supported upload formats are .txt, .md, and .pdf."

    return ChatService.not_supported_token


def _stream_chunks(answer: str) -> list[str]:
    if answer == ChatService.not_supported_token:
        return [answer]
    midpoint = max(1, len(answer) // 2)
    return [answer[:midpoint], answer[midpoint:]]


def _embedding_for_text(text: str) -> list[float]:
    vector = [0.0] * EMBEDDING_VECTOR_DIMENSIONS
    vector[_bucket_for_text(text)] = 1.0
    return vector


def _bucket_for_text(text: str) -> int:
    lower_text = text.lower()
    if any(keyword in lower_text for keyword in ("paris", "france", "capital")):
        return 0
    if any(keyword in lower_text for keyword in ("upload", "format", ".txt", ".md", ".pdf")):
        return 2
    return 1
