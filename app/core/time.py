"""Time helpers for generating consistent timestamps."""

from __future__ import annotations

from datetime import datetime, timezone

from .config import ISO_FORMAT


def utcnow() -> datetime:
    """Return the current UTC time with timezone awareness."""
    return datetime.now(timezone.utc)


def to_iso(dt: datetime) -> str:
    """Format a datetime as an ISO 8601 string in UTC."""
    return dt.astimezone(timezone.utc).strftime(ISO_FORMAT)
