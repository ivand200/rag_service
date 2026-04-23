from __future__ import annotations

from functools import lru_cache

from pydantic import Field, HttpUrl, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=("../.env", ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_env: str = "development"
    app_name: str = "rag-service"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    frontend_origin: str = "http://localhost:5173"
    clerk_jwt_public_key: str | None = None
    clerk_authorized_parties: list[str] = Field(default_factory=list)

    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/rag_service"

    s3_endpoint_url: HttpUrl | None = Field(default="http://localhost:9000")
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"
    s3_bucket: str = "rag-service-documents"
    s3_region: str = "us-east-1"
    s3_secure: bool = False

    dashscope_api_key: str
    dashscope_base_url: HttpUrl = Field(
        default="https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
    )
    chat_model: str = "qwen3.6-plus"
    embedding_model: str = "text-embedding-v4"
    retrieval_top_k: int = 5
    enable_thinking: bool = False

    upload_max_bytes: int = 25 * 1024 * 1024
    ingestion_max_retries: int = 3
    ingestion_poll_interval_seconds: int = 5
    chunk_target_tokens: int = 800
    chunk_overlap_tokens: int = 120
    chunk_max_batch_size: int = 10

    @field_validator("frontend_origin")
    @classmethod
    def validate_frontend_origin(cls, value: str) -> str:
        if not value.startswith(("http://", "https://")):
            raise ValueError("FRONTEND_ORIGIN must start with http:// or https://")
        return value.rstrip("/")

    @field_validator("clerk_jwt_public_key", mode="before")
    @classmethod
    def normalize_clerk_jwt_public_key(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.replace("\\n", "\n").strip()
        return normalized or None

    @field_validator("clerk_authorized_parties", mode="before")
    @classmethod
    def parse_clerk_authorized_parties(cls, value: object) -> list[str]:
        if value in (None, ""):
            return []
        if isinstance(value, str):
            return [part.strip().rstrip("/") for part in value.split(",") if part.strip()]
        if isinstance(value, list):
            return [str(part).strip().rstrip("/") for part in value if str(part).strip()]
        raise ValueError("CLERK_AUTHORIZED_PARTIES must be a comma-separated string or list")

    @field_validator("clerk_authorized_parties")
    @classmethod
    def validate_clerk_authorized_parties(cls, value: list[str]) -> list[str]:
        for item in value:
            if not item.startswith(("http://", "https://")):
                raise ValueError(
                    "CLERK_AUTHORIZED_PARTIES entries must start with http:// or https://"
                )
        return value

    @field_validator("retrieval_top_k", "ingestion_max_retries", "chunk_max_batch_size")
    @classmethod
    def validate_positive_ints(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("Value must be positive")
        return value

    @field_validator("chunk_overlap_tokens")
    @classmethod
    def validate_chunk_overlap(cls, value: int) -> int:
        if value < 0:
            raise ValueError("CHUNK_OVERLAP_TOKENS cannot be negative")
        return value

    @model_validator(mode="after")
    def validate_chunk_window(self) -> Settings:
        if self.chunk_target_tokens <= self.chunk_overlap_tokens:
            raise ValueError("CHUNK_TARGET_TOKENS must be greater than CHUNK_OVERLAP_TOKENS")
        if not self.clerk_authorized_parties:
            self.clerk_authorized_parties = [self.frontend_origin]
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
