"""Stdlib-first structured logging helpers.

The helpers in this module keep request identifiers attached to log records and
serialize records in a simple structured form that is safe to hand to the
service layer.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, Token
from datetime import datetime, timezone
import json
import logging
from typing import Any, Iterator

from .redact import redact_value

REQUEST_ID_HEADER = "request_id"
_request_id_var: ContextVar[str | None] = ContextVar("db_mcp_request_id", default=None)

_STANDARD_RECORD_ATTRS = {
    "args",
    "asctime",
    "created",
    "exc_info",
    "exc_text",
    "filename",
    "funcName",
    "levelname",
    "levelno",
    "lineno",
    "module",
    "msecs",
    "message",
    "msg",
    "name",
    "pathname",
    "process",
    "processName",
    "relativeCreated",
    "stack_info",
    "thread",
    "threadName",
}


def get_request_id() -> str | None:
    """Return the current request identifier, if one has been set."""

    return _request_id_var.get()


def set_request_id(request_id: str | None) -> Token[str | None]:
    """Set the active request identifier for the current context."""

    return _request_id_var.set(request_id)


def reset_request_id(token: Token[str | None]) -> None:
    """Restore a previous request-id context token."""

    _request_id_var.reset(token)


@contextmanager
def request_id_context(request_id: str | None) -> Iterator[None]:
    """Context manager that binds ``request_id`` to the current context."""

    token = set_request_id(request_id)
    try:
        yield
    finally:
        reset_request_id(token)


class RequestIdFilter(logging.Filter):
    """Attach the active request identifier to each log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = get_request_id()
        return True


class StructuredLogFormatter(logging.Formatter):
    """Serialize log records as compact JSON objects."""

    def format(self, record: logging.LogRecord) -> str:  # pragma: no cover - exercised indirectly
        payload = self._build_payload(record)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, separators=(",", ":"))

    def _build_payload(self, record: logging.LogRecord) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        request_id = getattr(record, "request_id", None) or get_request_id()
        if request_id is not None:
            payload[REQUEST_ID_HEADER] = request_id

        extra_fields = self._extract_extra_fields(record)
        if extra_fields:
            payload.update(extra_fields)

        return redact_value(payload)

    def _extract_extra_fields(self, record: logging.LogRecord) -> dict[str, Any]:
        extras: dict[str, Any] = {}
        for key, value in record.__dict__.items():
            if key in _STANDARD_RECORD_ATTRS or key == REQUEST_ID_HEADER:
                continue
            extras[key] = value
        return extras


class KeyValueLogFormatter(logging.Formatter):
    """Human-readable formatter used when JSON output is not desired."""

    def format(self, record: logging.LogRecord) -> str:  # pragma: no cover - exercised indirectly
        payload = StructuredLogFormatter()._build_payload(record)
        parts = [f"{key}={_format_scalar(value)}" for key, value in payload.items()]
        if record.exc_info:
            parts.append(f"exception={self.formatException(record.exc_info)!r}")
        return " ".join(parts)


def configure_logging(
    *,
    level: int = logging.INFO,
    json_format: bool = True,
    stream: Any | None = None,
    force: bool = False,
) -> None:
    """Configure the root logger for structured output.

    The helper intentionally stays small: it wires a single stream handler with
    request-id propagation and leaves higher-level logging policy to callers.
    """

    handler = logging.StreamHandler(stream)
    handler.setFormatter(StructuredLogFormatter() if json_format else KeyValueLogFormatter())
    handler.addFilter(RequestIdFilter())

    logging.basicConfig(level=level, handlers=[handler], force=force)


def get_logger(name: str | None = None) -> logging.Logger:
    """Return a standard library logger ready for structured output."""

    logger = logging.getLogger(name)
    return logger


def emit_structured(
    logger: logging.Logger,
    event: str,
    *,
    level: int = logging.INFO,
    message: str | None = None,
    **fields: Any,
) -> None:
    """Log a structured event using standard ``logging`` APIs."""

    payload = redact_value(fields)
    logger.log(level, message or event, extra={"event": event, "fields": payload})


def _format_scalar(value: Any) -> str:
    if isinstance(value, str):
        return json.dumps(value)
    if value is None:
        return "null"
    return str(value)
