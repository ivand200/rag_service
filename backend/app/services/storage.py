from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from inspect import isawaitable
from io import BytesIO
from typing import Any, BinaryIO, Protocol, cast

from botocore.exceptions import ClientError

from app.config import Settings

try:
    import aioboto3
except ImportError:  # pragma: no cover - exercised only in underspecified local envs
    aioboto3 = None


async def maybe_await(value: object) -> Any:
    if isawaitable(value):
        return await cast("Any", value)
    return value


class S3BodyReader(Protocol):
    def read(self) -> object: ...


class S3ClientProtocol(Protocol):
    def head_bucket(self, **kwargs: object) -> object: ...
    def create_bucket(self, **kwargs: object) -> object: ...
    def upload_fileobj(self, *args: object, **kwargs: object) -> object: ...
    def get_object(self, **kwargs: object) -> object: ...


class StorageService:
    def __init__(
        self,
        settings: Settings,
        client: S3ClientProtocol | None = None,
        client_factory: Callable[[], AbstractAsyncContextManager[S3ClientProtocol]] | None = None,
    ) -> None:
        self.settings = settings
        self.bucket = settings.s3_bucket
        self._client = client
        self._session = aioboto3.Session() if aioboto3 is not None else None
        self._client_factory = client_factory

    @asynccontextmanager
    async def _get_client(self) -> AsyncIterator[S3ClientProtocol]:
        if self._client_factory is not None:
            async with self._client_factory() as client:
                yield client
            return

        if self._client is not None:
            yield self._client
            return

        if self._session is None:
            raise RuntimeError("aioboto3 is required for runtime S3 access")

        async with self._session.client(
            "s3",
            endpoint_url=str(self.settings.s3_endpoint_url)
            if self.settings.s3_endpoint_url
            else None,
            aws_access_key_id=self.settings.s3_access_key,
            aws_secret_access_key=self.settings.s3_secret_key,
            region_name=self.settings.s3_region,
            use_ssl=self.settings.s3_secure,
        ) as client:
            yield cast(S3ClientProtocol, client)

    async def ensure_bucket(self) -> None:
        async with self._get_client() as client:
            try:
                await maybe_await(client.head_bucket(Bucket=self.bucket))
            except ClientError:
                await maybe_await(client.create_bucket(Bucket=self.bucket))

    async def check_bucket_access(self) -> None:
        async with self._get_client() as client:
            await maybe_await(client.head_bucket(Bucket=self.bucket))

    async def upload_bytes(self, key: str, content: bytes, content_type: str | None) -> None:
        extra_args = {"ContentType": content_type} if content_type else None
        stream: BinaryIO = BytesIO(content)
        async with self._get_client() as client:
            if extra_args:
                await maybe_await(
                    client.upload_fileobj(
                        stream,
                        self.bucket,
                        key,
                        ExtraArgs=extra_args,
                    )
                )
            else:
                await maybe_await(client.upload_fileobj(stream, self.bucket, key))

    async def download_bytes(self, key: str) -> bytes:
        async with self._get_client() as client:
            response = await maybe_await(client.get_object(Bucket=self.bucket, Key=key))
            body = cast("dict[str, S3BodyReader]", response)["Body"]
            content = await maybe_await(body.read())
            return cast(bytes, content)
