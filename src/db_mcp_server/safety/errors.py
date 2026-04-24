"""Stable internal and MCP-facing error types.

This module centralizes error codes used across the service, adapter, and MCP
layers. The goal is to ensure callers can convert arbitrary backend, driver,
or validation failures into a small, predictable set of machine-readable
codes without exposing raw driver exceptions to clients.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import Any


class ErrorCode(StrEnum):
    """Normalized error codes used by the server."""

    UNKNOWN_CONNECTION = "UNKNOWN_CONNECTION"
    CONNECTION_FAILED = "CONNECTION_FAILED"
    AUTH_FAILED = "AUTH_FAILED"
    QUERY_BLOCKED = "QUERY_BLOCKED"
    QUERY_TIMEOUT = "QUERY_TIMEOUT"
    QUERY_TOO_LARGE = "QUERY_TOO_LARGE"
    INVALID_SQL = "INVALID_SQL"
    UNSUPPORTED_OPERATION = "UNSUPPORTED_OPERATION"
    BACKEND_ERROR = "BACKEND_ERROR"


class DbMcpError(Exception):
    """Base exception that carries a stable error code and redacted metadata."""

    code: ErrorCode = ErrorCode.BACKEND_ERROR

    def __init__(
        self,
        message: str,
        *,
        details: Mapping[str, Any] | None = None,
        cause: BaseException | None = None,
        code: ErrorCode | str | None = None,
    ) -> None:
        self.code = coerce_error_code(code or self.code)
        self.message = str(message)
        self.details = dict(details or {})
        self.cause = cause
        super().__init__(self.message)

    def __str__(self) -> str:
        return f"[{self.code}] {self.message}"

    def to_dict(self) -> dict[str, Any]:
        """Return a redacted, machine-readable representation."""

        payload: dict[str, Any] = {
            "code": self.code.value,
            "message": self.message,
        }
        if self.details:
            payload["details"] = dict(self.details)
        if self.cause is not None:
            payload["cause_type"] = type(self.cause).__name__
        return payload


class UnknownConnectionError(DbMcpError):
    code = ErrorCode.UNKNOWN_CONNECTION


class ConnectionFailedError(DbMcpError):
    code = ErrorCode.CONNECTION_FAILED


class AuthFailedError(DbMcpError):
    code = ErrorCode.AUTH_FAILED


class QueryBlockedError(DbMcpError):
    code = ErrorCode.QUERY_BLOCKED


class QueryTimeoutError(DbMcpError):
    code = ErrorCode.QUERY_TIMEOUT


class QueryTooLargeError(DbMcpError):
    code = ErrorCode.QUERY_TOO_LARGE


class InvalidSqlError(DbMcpError):
    code = ErrorCode.INVALID_SQL


class UnsupportedOperationError(DbMcpError):
    code = ErrorCode.UNSUPPORTED_OPERATION


class BackendError(DbMcpError):
    code = ErrorCode.BACKEND_ERROR


_ERROR_CLASS_BY_CODE: dict[ErrorCode, type[DbMcpError]] = {
    ErrorCode.UNKNOWN_CONNECTION: UnknownConnectionError,
    ErrorCode.CONNECTION_FAILED: ConnectionFailedError,
    ErrorCode.AUTH_FAILED: AuthFailedError,
    ErrorCode.QUERY_BLOCKED: QueryBlockedError,
    ErrorCode.QUERY_TIMEOUT: QueryTimeoutError,
    ErrorCode.QUERY_TOO_LARGE: QueryTooLargeError,
    ErrorCode.INVALID_SQL: InvalidSqlError,
    ErrorCode.UNSUPPORTED_OPERATION: UnsupportedOperationError,
    ErrorCode.BACKEND_ERROR: BackendError,
}


def coerce_error_code(value: ErrorCode | str) -> ErrorCode:
    """Convert a string or enum value into a normalized error code."""

    if isinstance(value, ErrorCode):
        return value
    return ErrorCode(value)


def error_from_code(
    code: ErrorCode | str,
    message: str,
    *,
    details: Mapping[str, Any] | None = None,
    cause: BaseException | None = None,
) -> DbMcpError:
    """Build a typed error instance from a normalized error code."""

    normalized_code = coerce_error_code(code)
    error_cls = _ERROR_CLASS_BY_CODE.get(normalized_code, DbMcpError)
    return error_cls(message, details=details, cause=cause, code=normalized_code)


def normalize_exception(
    exc: BaseException,
    *,
    message: str | None = None,
    details: Mapping[str, Any] | None = None,
) -> DbMcpError:
    """Convert an arbitrary exception into a stable :class:`DbMcpError`.

    Existing ``DbMcpError`` instances are passed through unchanged unless a new
    message/details payload is explicitly requested by the caller.
    """

    if isinstance(exc, DbMcpError):
        if message is None and details is None:
            return exc
        merged_details = dict(exc.details)
        if details:
            merged_details.update(details)
        return error_from_code(
            exc.code,
            message or exc.message,
            details=merged_details,
            cause=exc.cause or exc,
        )

    code = classify_exception(exc)
    resolved_message = message or _default_message_for_code(code, exc)
    merged_details = {
        "exception_type": type(exc).__name__,
    }
    if details:
        merged_details.update(details)
    return error_from_code(code, resolved_message, details=merged_details, cause=exc)


def classify_exception(exc: BaseException) -> ErrorCode:
    """Infer a stable error code from a raw exception.

    The classification is intentionally conservative: callers should prefer
    explicit error construction when they know the exact failure category.
    """

    if isinstance(exc, TimeoutError):
        return ErrorCode.QUERY_TIMEOUT

    name = type(exc).__name__.lower()
    message = str(exc).lower()

    if _matches_any(name, message, ("unknownconnection", "unknown connection", "connection not found")):
        return ErrorCode.UNKNOWN_CONNECTION
    if _matches_any(name, message, ("auth", "authentication", "login failed", "invalid credentials", "password")):
        return ErrorCode.AUTH_FAILED
    if _matches_any(name, message, ("blocked", "forbidden", "permission denied", "not allowed", "policy")):
        return ErrorCode.QUERY_BLOCKED
    if _matches_any(name, message, ("timeout", "timed out", "deadline exceeded")):
        return ErrorCode.QUERY_TIMEOUT
    if _matches_any(name, message, ("too large", "row limit", "payload too large", "result too large")):
        return ErrorCode.QUERY_TOO_LARGE
    if _matches_any(name, message, ("syntax", "parse", "invalid sql", "malformed")):
        return ErrorCode.INVALID_SQL
    if _matches_any(name, message, ("unsupported", "not implemented", "not supported")):
        return ErrorCode.UNSUPPORTED_OPERATION
    if _matches_any(name, message, ("connection", "connect", "network", "socket", "tls", "transport")):
        return ErrorCode.CONNECTION_FAILED

    return ErrorCode.BACKEND_ERROR


def _matches_any(name: str, message: str, needles: tuple[str, ...]) -> bool:
    haystack = f"{name} {message}"
    return any(needle in haystack for needle in needles)


def _default_message_for_code(code: ErrorCode, _exc: BaseException) -> str:
    """Generate a safe default message for a normalized error code."""

    defaults = {
        ErrorCode.UNKNOWN_CONNECTION: "Unknown connection",
        ErrorCode.CONNECTION_FAILED: "Connection failed",
        ErrorCode.AUTH_FAILED: "Authentication failed",
        ErrorCode.QUERY_BLOCKED: "Query blocked by policy",
        ErrorCode.QUERY_TIMEOUT: "Query timed out",
        ErrorCode.QUERY_TOO_LARGE: "Query result exceeded limits",
        ErrorCode.INVALID_SQL: "Invalid SQL",
        ErrorCode.UNSUPPORTED_OPERATION: "Unsupported operation",
        ErrorCode.BACKEND_ERROR: "Backend error",
    }
    return defaults.get(code, "Backend error")


__all__ = [
    "AuthFailedError",
    "BackendError",
    "ConnectionFailedError",
    "DbMcpError",
    "ErrorCode",
    "InvalidSqlError",
    "QueryBlockedError",
    "QueryTimeoutError",
    "QueryTooLargeError",
    "UnknownConnectionError",
    "UnsupportedOperationError",
    "classify_exception",
    "coerce_error_code",
    "error_from_code",
    "normalize_exception",
]
