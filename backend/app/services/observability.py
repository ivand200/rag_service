from __future__ import annotations

import contextlib
import contextvars
import json
import logging
import time
import uuid
from collections.abc import Callable, Iterator

from fastapi import Request, Response

_LOG_CONTEXT: contextvars.ContextVar[dict[str, object] | None] = contextvars.ContextVar(
    "log_context",
    default=None,
)


def _sanitize_fields(fields: dict[str, object]) -> dict[str, object]:
    return {key: value for key, value in fields.items() if value is not None}


def configure_logging() -> None:
    root_logger = logging.getLogger()
    if getattr(configure_logging, "_configured", False):
        root_logger.setLevel(logging.INFO)
        return

    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(logging.INFO)

    for logger_name in ("uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(logger_name)
        logger.handlers.clear()
        logger.propagate = True

    configure_logging._configured = True  # type: ignore[attr-defined]


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def get_log_context() -> dict[str, object]:
    context = _LOG_CONTEXT.get()
    return dict(context or {})


@contextlib.contextmanager
def bind_log_context(**fields: object) -> Iterator[None]:
    token = _LOG_CONTEXT.set({**get_log_context(), **_sanitize_fields(fields)})
    try:
        yield
    finally:
        _LOG_CONTEXT.reset(token)


def log_event(logger: logging.Logger, event: str, **fields: object) -> None:
    payload = {
        "event": event,
        "logger": logger.name,
        **get_log_context(),
        **_sanitize_fields(fields),
    }
    logger.info(json.dumps(payload, default=str))


async def request_id_middleware(request: Request, call_next: Callable) -> Response:
    request_id = request.headers.get("x-request-id", str(uuid.uuid4()))
    correlation_id = request.headers.get("x-correlation-id", request_id)
    request.state.request_id = request_id
    request.state.correlation_id = correlation_id

    started_at = time.perf_counter()
    client_host = request.client.host if request.client else None

    with bind_log_context(
        request_id=request_id,
        correlation_id=correlation_id,
        method=request.method,
        path=request.url.path,
        client_ip=client_host,
    ):
        log_event(get_logger("app.request"), "request_started")
        try:
            response = await call_next(request)
        except Exception as exc:
            duration_ms = round((time.perf_counter() - started_at) * 1000, 2)
            log_event(
                get_logger("app.request"),
                "request_failed",
                duration_ms=duration_ms,
                error=type(exc).__name__,
            )
            raise

        duration_ms = round((time.perf_counter() - started_at) * 1000, 2)
        response.headers["x-request-id"] = request_id
        response.headers["x-correlation-id"] = correlation_id
        log_event(
            get_logger("app.request"),
            "request_completed",
            status_code=response.status_code,
            duration_ms=duration_ms,
        )
        return response
