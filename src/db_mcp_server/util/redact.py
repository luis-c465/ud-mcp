"""Redaction helpers for secrets and connection strings.

The service layer passes around nested dictionaries, logging extras, and driver
error details. These helpers keep sensitive values out of logs and audit
records while staying lightweight and dependency-free.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import re
from typing import Any
from urllib.parse import urlsplit, urlunsplit

REDACTED = "<redacted>"

_SENSITIVE_KEY_RE = re.compile(
    r"(?:^|[^a-z0-9])(password|passwd|pwd|token|secret|api[_-]?key|access[_-]?key|dsn|connection[_-]?string)(?:$|[^a-z0-9])",
    re.IGNORECASE,
)

# Common key/value separators in DSNs and connection strings.
_KEY_VALUE_RE = re.compile(
    r"(?P<key>(?:password|passwd|pwd|token|secret|api[_-]?key|access[_-]?key|dsn|connection[_-]?string))"
    r"(?P<sep>\s*=\s*|\s*:\s*|\s*=\s*|\s*=\s*)"
    r"(?P<value>(?:'[^']*'|\"[^\"]*\"|[^;\s,]+))",
    re.IGNORECASE,
)

_URI_CREDENTIALS_RE = re.compile(
    r"(?P<scheme>[a-z][a-z0-9+.-]*://)(?P<user>[^/?#:]+)(?::(?P<password>[^@/?#]*))?@",
    re.IGNORECASE,
)


def is_sensitive_key(key: object) -> bool:
    """Return ``True`` when a mapping key looks secret-bearing."""

    if not isinstance(key, str):
        return False
    return _SENSITIVE_KEY_RE.search(key) is not None


def redact_text(value: str) -> str:
    """Redact sensitive values from free-form strings.

    This intentionally errs on the side of safety for common secret carriers
    such as DSNs, URI credentials, and ``key=value`` connection strings.
    """

    if not value:
        return value

    redacted = _URI_CREDENTIALS_RE.sub(lambda match: f"{match.group('scheme')}{match.group('user')}:{REDACTED}@", value)

    def _replace_key_value(match: re.Match[str]) -> str:
        return f"{match.group('key')}{match.group('sep')}{REDACTED}"

    redacted = _KEY_VALUE_RE.sub(_replace_key_value, redacted)
    return redacted


def redact_connection_string(value: str) -> str:
    """Redact well-known connection string formats.

    The implementation is intentionally simple: we preserve the shape of the
    string so the output remains useful for debugging, while hiding secret
    values such as passwords and tokens.
    """

    if not value:
        return value

    # Try URI-style redaction first.
    parts = urlsplit(value)
    if parts.scheme and parts.netloc:
        netloc = parts.netloc
        if "@" in netloc:
            credentials, host = netloc.rsplit("@", 1)
            if ":" in credentials:
                username = credentials.split(":", 1)[0]
                netloc = f"{username}:{REDACTED}@{host}"
            else:
                netloc = f"{REDACTED}@{host}"
        return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))

    return redact_text(value)


def redact_value(value: Any) -> Any:
    """Recursively redact secrets from common Python data structures."""

    if value is None:
        return None
    if isinstance(value, str):
        return redact_connection_string(value)
    if isinstance(value, bytes):
        return REDACTED
    if isinstance(value, Mapping):
        redacted: dict[Any, Any] = {}
        for key, item in value.items():
            if is_sensitive_key(key):
                redacted[key] = REDACTED
            else:
                redacted[key] = redact_value(item)
        return redacted
    if isinstance(value, tuple):
        return tuple(redact_value(item) for item in value)
    if isinstance(value, list):
        return [redact_value(item) for item in value]
    if isinstance(value, set):
        return {redact_value(item) for item in value}
    if isinstance(value, frozenset):
        return frozenset(redact_value(item) for item in value)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [redact_value(item) for item in value]
    return value


def redact_mapping(mapping: Mapping[str, Any]) -> dict[str, Any]:
    """Return a redacted copy of ``mapping``."""

    return {key: redact_value(value) for key, value in mapping.items()}


def redact_string(value: object) -> str:
    """Best-effort string redaction helper for arbitrary values."""

    if value is None:
        return ""
    if isinstance(value, str):
        return redact_connection_string(value)
    return redact_connection_string(str(value))
