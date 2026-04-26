"""Utility helpers used across the service layer."""

from __future__ import annotations

from .logging import (
    REQUEST_ID_HEADER,
    KeyValueLogFormatter,
    RequestIdFilter,
    StructuredLogFormatter,
    configure_logging,
    emit_structured,
    get_logger,
    get_request_id,
    request_id_context,
    reset_request_id,
    set_request_id,
)
from .redact import (
    REDACTED,
    is_sensitive_key,
    redact_connection_string,
    redact_mapping,
    redact_string,
    redact_text,
    redact_value,
)
from .timing import TimingResult, elapsed_ms, timing

__all__ = [
    "REDACTED",
    "REQUEST_ID_HEADER",
    "KeyValueLogFormatter",
    "RequestIdFilter",
    "StructuredLogFormatter",
    "TimingResult",
    "configure_logging",
    "elapsed_ms",
    "emit_structured",
    "get_logger",
    "get_request_id",
    "is_sensitive_key",
    "redact_connection_string",
    "redact_mapping",
    "redact_string",
    "redact_text",
    "redact_value",
    "request_id_context",
    "reset_request_id",
    "set_request_id",
    "timing",
]
