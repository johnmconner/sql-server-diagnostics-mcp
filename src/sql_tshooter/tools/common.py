"""Shared helpers for SQL TShooter tool implementations."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def collected_at_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def truncate_text(value: Any, max_length: int) -> str:
    normalized_text = " ".join(str(value or "").split())
    if len(normalized_text) > max_length:
        return normalized_text[: max_length - 3].rstrip() + "..."
    return normalized_text


def truncate_identifier(value: Any, max_length: int) -> str:
    normalized = str(value or "unknown").strip() or "unknown"
    if len(normalized) > max_length:
        return normalized[: max_length - 3] + "..."
    return normalized

