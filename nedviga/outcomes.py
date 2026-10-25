"""Helpers for building the ApiOutcome JSON envelope."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from .models import ApiOutcomeEnvelope


STATUS_EXIT_CODES = {
    "ok": 0,
    "degraded": 2,
    "error": 3,
}
USAGE_ERROR_EXIT = 4


def make_envelope(
    status: Literal["ok", "degraded", "error"],
    reason: str | None = None,
    source: str | None = None,
    data: Any = None,
    metadata: dict | None = None,
) -> ApiOutcomeEnvelope:
    """Build a valid ApiOutcome envelope."""
    return ApiOutcomeEnvelope(
        ok=(status == "ok"),
        status=status,
        reason=reason,
        source=source,
        parsed_at=datetime.now(timezone.utc),
        data=data,
        metadata=metadata or {},
    )
