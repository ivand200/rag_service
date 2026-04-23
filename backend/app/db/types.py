from __future__ import annotations

from typing import Any

from sqlalchemy import JSON
from sqlalchemy.types import TypeDecorator

try:
    from pgvector.sqlalchemy import Vector
except ImportError:  # pragma: no cover - optional in non-Postgres test environments
    Vector = None


class EmbeddingVector(TypeDecorator[list[float]]):
    impl = JSON
    cache_ok = True
    if Vector is not None:
        comparator_factory = Vector.comparator_factory

    def __init__(self, dimensions: int) -> None:
        super().__init__()
        self.dimensions = dimensions

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql" and Vector is not None:
            return dialect.type_descriptor(Vector(self.dimensions))
        return dialect.type_descriptor(JSON())

    def process_bind_param(self, value: list[float] | None, dialect) -> Any:
        if value is None:
            return None
        return value

    def process_result_value(self, value: Any, dialect) -> list[float] | None:
        if value is None:
            return None
        return list(value)
