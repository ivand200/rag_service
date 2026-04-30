from __future__ import annotations

from datetime import datetime, timedelta

from app.config import Settings

try:
    from datetime import UTC
except ImportError:  # pragma: no cover - Python < 3.11 compatibility
    from datetime import timezone

    UTC = timezone.utc  # noqa: UP017


def next_retry_at(*, attempt_count: int, settings: Settings) -> datetime:
    if settings.job_retry_initial_delay_seconds == 0:
        return datetime.now(UTC)

    exponent = max(attempt_count - 1, 0)
    delay_seconds = settings.job_retry_initial_delay_seconds * (2**exponent)
    capped_delay_seconds = min(delay_seconds, settings.job_retry_max_delay_seconds)
    return datetime.now(UTC) + timedelta(seconds=capped_delay_seconds)
