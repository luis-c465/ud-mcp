"""Query limit helpers and truncation metadata."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Generic, Sequence, TypeVar

from ..config.models import DefaultsConfig

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class QueryLimits:
    """Resolved execution limits for a request."""

    timeout_ms: int
    max_rows: int
    max_bytes: int


@dataclass(frozen=True, slots=True)
class TruncationMetadata:
    """Structured metadata describing a truncated payload."""

    truncated: bool
    reason: str | None = None
    limit_name: str | None = None
    limit_value: int | None = None
    original_count: int | None = None
    returned_count: int | None = None
    original_bytes: int | None = None
    returned_bytes: int | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class LimitedResult(Generic[T]):
    """Convenience wrapper for truncated data and its metadata."""

    data: T
    truncation: TruncationMetadata | None


def resolve_query_limits(
    defaults: DefaultsConfig,
    *,
    timeout_ms: int | None = None,
    max_rows: int | None = None,
    max_bytes: int | None = None,
) -> QueryLimits:
    """Resolve execution limits from defaults and optional overrides."""

    return QueryLimits(
        timeout_ms=_resolve_positive_int(timeout_ms, defaults.timeout_ms, field_name="timeout_ms"),
        max_rows=_resolve_positive_int(max_rows, defaults.max_rows, field_name="max_rows"),
        max_bytes=_resolve_positive_int(max_bytes, defaults.max_bytes, field_name="max_bytes"),
    )


def truncate_sequence(items: Sequence[T], max_rows: int) -> LimitedResult[list[T]]:
    """Truncate a sequence to the requested row limit."""

    resolved_max_rows = _require_positive_int(max_rows, field_name="max_rows")
    kept = list(items[:resolved_max_rows])
    truncation = None
    if len(items) > resolved_max_rows:
        truncation = TruncationMetadata(
            truncated=True,
            reason="max_rows_exceeded",
            limit_name="max_rows",
            limit_value=resolved_max_rows,
            original_count=len(items),
            returned_count=len(kept),
        )
    return LimitedResult(data=kept, truncation=truncation)


def truncate_bytes(data: bytes | str, max_bytes: int) -> LimitedResult[bytes | str]:
    """Truncate a text or byte payload to the requested byte limit."""

    resolved_max_bytes = _require_positive_int(max_bytes, field_name="max_bytes")
    if isinstance(data, bytes):
        truncated = data[:resolved_max_bytes]
        was_truncated = len(data) > resolved_max_bytes
        returned_bytes = len(truncated)
        original_bytes = len(data)
    else:
        encoded = data.encode("utf-8")
        truncated_bytes = encoded[:resolved_max_bytes]
        was_truncated = len(encoded) > resolved_max_bytes
        truncated = truncated_bytes.decode("utf-8", errors="ignore")
        returned_bytes = len(truncated_bytes)
        original_bytes = len(encoded)

    truncation = None
    if was_truncated:
        truncation = TruncationMetadata(
            truncated=True,
            reason="max_bytes_exceeded",
            limit_name="max_bytes",
            limit_value=resolved_max_bytes,
            original_bytes=original_bytes,
            returned_bytes=returned_bytes,
        )
    return LimitedResult(data=truncated, truncation=truncation)


def _resolve_positive_int(value: int | None, default: int, *, field_name: str) -> int:
    resolved = default if value is None else value
    if resolved <= 0:
        raise ValueError(f"{field_name} must be a positive integer")
    return resolved


def _require_positive_int(value: int, *, field_name: str) -> int:
    if value <= 0:
        raise ValueError(f"{field_name} must be a positive integer")
    return value


__all__ = [
    "LimitedResult",
    "QueryLimits",
    "TruncationMetadata",
    "resolve_query_limits",
    "truncate_bytes",
    "truncate_sequence",
]