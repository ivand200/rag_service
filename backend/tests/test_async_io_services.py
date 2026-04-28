from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any

import pytest
from botocore.exceptions import ClientError

from app.config import Settings
from app.db.constants import EMBEDDING_VECTOR_DIMENSIONS
from app.services.llm import ChatService, EmbeddingService, RetrievalPlanProviderSchema
from app.services.storage import StorageService


def build_settings(**overrides: object) -> Settings:
    return Settings(
        openai_api_key="test-key",
        dashscope_api_key="",
        database_url="sqlite+pysqlite:///:memory:",
        s3_endpoint_url="http://localhost:9000",
        **overrides,
    )


class FakeEmbeddingsAPI:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def create(self, *, model: str, input: list[str], dimensions: int) -> object:
        self.calls.append({"model": model, "input": input, "dimensions": dimensions})
        return SimpleNamespace(
            data=[
                SimpleNamespace(embedding=[float(index + 1)] * dimensions)
                for index, _ in enumerate(input)
            ]
        )


class FakeChatCompletionsAPI:
    def __init__(self, responses: list[str]) -> None:
        self.responses = responses
        self.calls: list[dict[str, object]] = []

    async def create(self, *, model: str, messages: list[dict[str, str]]) -> object:
        self.calls.append({"model": model, "messages": messages})
        content = self.responses[len(self.calls) - 1]
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


class FakeStructuredChatCompletionsAPI:
    def __init__(
        self,
        *,
        parsed: object | None = None,
        response: object | None = None,
        error: Exception | None = None,
    ) -> None:
        self.parsed = parsed
        self.response = response
        self.error = error
        self.parse_calls: list[dict[str, object]] = []
        self.create_calls: list[dict[str, object]] = []

    async def parse(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        response_format: type[RetrievalPlanProviderSchema],
    ) -> object:
        self.parse_calls.append(
            {
                "model": model,
                "messages": messages,
                "response_format": response_format,
            }
        )
        if self.error is not None:
            raise self.error
        if self.response is not None:
            return self.response
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    finish_reason="stop",
                    message=SimpleNamespace(parsed=self.parsed, refusal=None),
                )
            ]
        )

    async def create(self, *, model: str, messages: list[dict[str, str]]) -> object:
        self.create_calls.append({"model": model, "messages": messages})
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content='{"query":"unexpected json planner","scope":"broad"}'
                    )
                )
            ]
        )


class FakeStream:
    def __init__(self, events: list[object]) -> None:
        self._events = events
        self.closed = False

    def __aiter__(self) -> FakeStream:
        self._iterator = iter(self._events)
        return self

    async def __anext__(self) -> object:
        try:
            return next(self._iterator)
        except StopIteration as exc:
            raise StopAsyncIteration from exc

    async def aclose(self) -> None:
        self.closed = True


class FakeStreamingChatCompletionsAPI:
    def __init__(self, stream_events: list[object]) -> None:
        self.stream_events = stream_events
        self.calls: list[dict[str, Any]] = []
        self.stream = FakeStream(stream_events)

    async def create(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        stream: bool = False,
    ) -> object:
        self.calls.append({"model": model, "messages": messages, "stream": stream})
        return self.stream


class FakeAsyncS3Body:
    def __init__(self, content: bytes) -> None:
        self.content = content

    async def read(self) -> bytes:
        return self.content


class FakeAsyncS3Client:
    def __init__(self, *, head_bucket_error: Exception | None = None) -> None:
        self.head_bucket_error = head_bucket_error
        self.created_buckets: list[str] = []
        self.uploads: list[dict[str, object]] = []
        self.objects: dict[str, bytes] = {"documents/existing.txt": b"stored bytes"}
        self.head_bucket_calls = 0

    async def head_bucket(self, *, Bucket: str) -> None:  # noqa: N803
        self.head_bucket_calls += 1
        if self.head_bucket_error is not None:
            raise self.head_bucket_error

    async def create_bucket(self, *, Bucket: str) -> None:  # noqa: N803
        self.created_buckets.append(Bucket)

    async def upload_fileobj(
        self,
        Fileobj,  # noqa: N803
        Bucket: str,  # noqa: N803
        Key: str,  # noqa: N803
        ExtraArgs: dict[str, str] | None = None,  # noqa: N803
    ) -> None:
        content = Fileobj.read()
        self.uploads.append(
            {
                "bucket": Bucket,
                "key": Key,
                "content": content,
                "extra_args": ExtraArgs,
            }
        )
        self.objects[Key] = content

    async def get_object(
        self,
        *,
        Bucket: str,  # noqa: N803
        Key: str,  # noqa: N803
    ) -> dict[str, FakeAsyncS3Body]:
        return {"Body": FakeAsyncS3Body(self.objects[Key])}


def test_embedding_service_batches_requests_and_preserves_order() -> None:
    embeddings_api = FakeEmbeddingsAPI()
    client = SimpleNamespace(embeddings=embeddings_api)
    service = EmbeddingService(
        build_settings(chunk_max_batch_size=20),
        client=client,
    )

    result = asyncio.run(service.embed_texts(["first", "second", "third"]))

    assert result == [
        [1.0] * EMBEDDING_VECTOR_DIMENSIONS,
        [2.0] * EMBEDDING_VECTOR_DIMENSIONS,
        [3.0] * EMBEDDING_VECTOR_DIMENSIONS,
    ]
    assert [call["input"] for call in embeddings_api.calls] == [["first", "second", "third"]]
    assert [call["dimensions"] for call in embeddings_api.calls] == [EMBEDDING_VECTOR_DIMENSIONS]


def test_chat_service_generates_answer_and_session_title_from_async_client() -> None:
    chat_api = FakeChatCompletionsAPI(["Grounded answer", "Short title"])
    client = SimpleNamespace(chat=SimpleNamespace(completions=chat_api))
    service = ChatService(build_settings(), client=client)

    answer = asyncio.run(
        service.generate_answer(
            question="What is the capital of France?",
            context="Paris is the capital of France.",
            history=[],
        )
    )
    title = asyncio.run(
        service.generate_session_title(first_user_message="What is the capital of France?")
    )

    assert (answer, title) == ("Grounded answer", "Short title")
    assert len(chat_api.calls) == 2


def test_chat_service_streams_text_deltas_and_closes_provider_stream() -> None:
    chat_api = FakeStreamingChatCompletionsAPI(
        [
            SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="Paris "))]),
            SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        delta=SimpleNamespace(
                            content=[
                                {"text": "is "},
                                SimpleNamespace(text="the capital"),
                            ]
                        )
                    )
                ]
            ),
            SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=None))]),
        ]
    )
    client = SimpleNamespace(chat=SimpleNamespace(completions=chat_api))
    service = ChatService(build_settings(), client=client)

    async def collect_chunks() -> list[str]:
        return [
            chunk
            async for chunk in service.stream_answer(
                question="What is the capital of France?",
                context="Paris is the capital of France.",
                history=[],
            )
        ]

    result = asyncio.run(collect_chunks())

    assert result == ["Paris ", "is ", "the capital"]
    assert chat_api.calls[0]["stream"] is True
    assert chat_api.stream.closed is True


def test_chat_service_uses_structured_retrieval_plan_parse_contract() -> None:
    chat_api = FakeStructuredChatCompletionsAPI(
        parsed=RetrievalPlanProviderSchema(
            query="  Paris   capital   evidence  ",
            scope="broad",
        )
    )
    client = SimpleNamespace(chat=SimpleNamespace(completions=chat_api))
    service = ChatService(
        build_settings(enable_structured_retrieval_plan=True, chat_model="planner-model"),
        client=client,
    )

    result = asyncio.run(service.generate_retrieval_plan(message="Tell me about Paris", history=[]))

    assert result.query == "Paris capital evidence"
    assert result.broad is True
    assert chat_api.parse_calls[0]["model"] == "planner-model"
    assert chat_api.parse_calls[0]["response_format"] is RetrievalPlanProviderSchema
    system_prompt = chat_api.parse_calls[0]["messages"][0]["content"]
    assert "supplied structured response schema" in system_prompt
    assert "Return only compact JSON" not in system_prompt
    assert chat_api.create_calls == []


def test_chat_service_structured_plan_preserves_fallback_cap_and_broad_heuristic() -> None:
    chat_api = FakeStructuredChatCompletionsAPI(
        parsed=RetrievalPlanProviderSchema(query="   ", scope="focused")
    )
    client = SimpleNamespace(chat=SimpleNamespace(completions=chat_api))
    service = ChatService(
        build_settings(enable_structured_retrieval_plan=True),
        client=client,
    )
    message = "How many " + "items " * 200

    result = asyncio.run(service.generate_retrieval_plan(message=message, history=[]))

    assert result.query == " ".join(message.split())[:500]
    assert result.broad is True


def test_chat_service_falls_back_when_structured_parse_method_is_missing(
    caplog: pytest.LogCaptureFixture,
) -> None:
    chat_api = FakeChatCompletionsAPI(['{"query":"provider json","scope":"broad"}'])
    client = SimpleNamespace(chat=SimpleNamespace(completions=chat_api))
    service = ChatService(
        build_settings(enable_structured_retrieval_plan=True),
        client=client,
    )
    message = "How many components are listed?"
    caplog.set_level(logging.INFO, logger="app.services.llm")

    result = asyncio.run(service.generate_retrieval_plan(message=message, history=[]))

    assert result.query == message
    assert result.broad is True
    assert chat_api.calls == []
    assert "retrieval_plan_structured_failed" in caplog.text
    assert message not in caplog.text


def test_chat_service_falls_back_when_structured_parse_raises() -> None:
    chat_api = FakeStructuredChatCompletionsAPI(error=RuntimeError("provider rejected schema"))
    client = SimpleNamespace(chat=SimpleNamespace(completions=chat_api))
    service = ChatService(
        build_settings(enable_structured_retrieval_plan=True),
        client=client,
    )

    result = asyncio.run(
        service.generate_retrieval_plan(message="Summarize all sections", history=[])
    )

    assert result.query == "Summarize all sections"
    assert result.broad is True
    assert chat_api.create_calls == []


@pytest.mark.parametrize(
    "response",
    [
        SimpleNamespace(
            choices=[
                SimpleNamespace(
                    finish_reason="stop",
                    message=SimpleNamespace(parsed=None, refusal="Cannot comply"),
                )
            ]
        ),
        SimpleNamespace(
            choices=[
                SimpleNamespace(
                    finish_reason="length",
                    message=SimpleNamespace(
                        parsed=RetrievalPlanProviderSchema(query="planned", scope="focused"),
                        refusal=None,
                    ),
                )
            ]
        ),
        SimpleNamespace(
            choices=[
                SimpleNamespace(
                    finish_reason="stop",
                    message=SimpleNamespace(
                        parsed=SimpleNamespace(query="planned", scope="focused"),
                        refusal=None,
                    ),
                )
            ]
        ),
    ],
)
def test_chat_service_falls_back_when_structured_parsed_output_is_unusable(
    response: object,
) -> None:
    chat_api = FakeStructuredChatCompletionsAPI(response=response)
    client = SimpleNamespace(chat=SimpleNamespace(completions=chat_api))
    service = ChatService(
        build_settings(enable_structured_retrieval_plan=True),
        client=client,
    )

    result = asyncio.run(service.generate_retrieval_plan(message="List all components", history=[]))

    assert result.query == "List all components"
    assert result.broad is True
    assert chat_api.create_calls == []


def test_chat_service_uses_legacy_json_retrieval_plan_when_structured_flag_is_disabled() -> None:
    chat_api = FakeStructuredChatCompletionsAPI()
    client = SimpleNamespace(chat=SimpleNamespace(completions=chat_api))
    service = ChatService(
        build_settings(enable_structured_retrieval_plan=False),
        client=client,
    )

    result = asyncio.run(service.generate_retrieval_plan(message="Tell me about Paris", history=[]))

    assert result.query == "unexpected json planner"
    assert result.broad is True
    assert chat_api.parse_calls == []
    assert "Return only compact JSON" in chat_api.create_calls[0]["messages"][0]["content"]


def test_storage_service_ensures_bucket_uploads_and_downloads_with_async_client() -> None:
    client = FakeAsyncS3Client()

    @asynccontextmanager
    async def client_factory():
        yield client

    service = StorageService(
        build_settings(s3_bucket="rag-documents"),
        client_factory=client_factory,
    )

    asyncio.run(service.check_bucket_access())
    asyncio.run(service.upload_bytes("documents/new.txt", b"hello", "text/plain"))
    downloaded = asyncio.run(service.download_bytes("documents/new.txt"))

    assert downloaded == b"hello"
    assert client.head_bucket_calls == 1
    assert client.uploads == [
        {
            "bucket": "rag-documents",
            "key": "documents/new.txt",
            "content": b"hello",
            "extra_args": {"ContentType": "text/plain"},
        }
    ]


def test_storage_service_creates_missing_bucket_on_head_bucket_error() -> None:
    missing_bucket_error = ClientError(
        {"Error": {"Code": "404", "Message": "Not Found"}},
        "HeadBucket",
    )
    client = FakeAsyncS3Client(head_bucket_error=missing_bucket_error)

    @asynccontextmanager
    async def client_factory():
        yield client

    service = StorageService(
        build_settings(s3_bucket="rag-documents"),
        client_factory=client_factory,
    )

    asyncio.run(service.ensure_bucket())

    assert client.created_buckets == ["rag-documents"]
