"""Safety and policy helpers for db-mcp-server."""

from .errors import (
    AuthFailedError,
    BackendError,
    ConnectionFailedError,
    DbMcpError,
    ErrorCode,
    InvalidSqlError,
    QueryBlockedError,
    QueryTimeoutError,
    QueryTooLargeError,
    UnknownConnectionError,
    UnsupportedOperationError,
    classify_exception,
    coerce_error_code,
    error_from_code,
    normalize_exception,
)

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
