from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace

from botocore.exceptions import ClientError

from app.config import Settings
from app.db.constants import EMBEDDING_VECTOR_DIMENSIONS
from app.services.llm import ChatService, EmbeddingService
from app.services.storage import StorageService


def build_settings(**overrides: object) -> Settings:
    return Settings(
        dashscope_api_key="test-key",
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
