"""Helpers for resolving environment-backed secret references.

Configuration models keep secret-bearing values as environment variable names.
This module turns those references into runtime values while keeping the secret
material out of exception messages and debug representations.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from os import environ
from typing import Any

_MISSING = object()


class SecretResolutionError(RuntimeError):
    """Base class for secret resolution failures."""


class MissingSecretError(SecretResolutionError):
    """Raised when a referenced environment variable is not set."""

    def __init__(
        self,
        env_var: str,
        *,
        field_name: str | None = None,
        connection_name: str | None = None,
    ) -> None:
        self.env_var = env_var
        self.field_name = field_name
        self.connection_name = connection_name
        super().__init__(self._build_message())

    def _build_message(self) -> str:
        parts: list[str] = []
        if self.connection_name:
            parts.append(f"connection {self.connection_name!r}")
        if self.field_name:
            parts.append(f"field {self.field_name!r}")

        scope = " and ".join(parts)
        if scope:
            scope = f" ({scope})"

        return f"Missing required environment variable {self.env_var!r}{scope}."


class EmptySecretError(SecretResolutionError):
    """Raised when a referenced environment variable is set to an empty value."""

    def __init__(
        self,
        env_var: str,
        *,
        field_name: str | None = None,
        connection_name: str | None = None,
    ) -> None:
        self.env_var = env_var
        self.field_name = field_name
        self.connection_name = connection_name
        super().__init__(self._build_message())

    def _build_message(self) -> str:
        parts: list[str] = []
        if self.connection_name:
            parts.append(f"connection {self.connection_name!r}")
        if self.field_name:
            parts.append(f"field {self.field_name!r}")

        scope = " and ".join(parts)
        if scope:
            scope = f" ({scope})"

        return f"Environment variable {self.env_var!r}{scope} is set but empty."


@dataclass(frozen=True, slots=True)
class ResolvedSecret:
    """Resolved secret value with a redacted debug representation."""

    env_var: str
    value: str
    field_name: str | None = None
    connection_name: str | None = None

    def __repr__(self) -> str:  # pragma: no cover - trivial and security-sensitive
        parts = [f"env_var={self.env_var!r}"]
        if self.field_name is not None:
            parts.append(f"field_name={self.field_name!r}")
        if self.connection_name is not None:
            parts.append(f"connection_name={self.connection_name!r}")
        parts.append("value=<redacted>")
        return f"ResolvedSecret({', '.join(parts)})"

    def __str__(self) -> str:  # pragma: no cover - intentionally simple
        return "<redacted>"

    def reveal(self) -> str:
        """Return the raw secret value explicitly."""

        return self.value


SecretRef = str | None
SecretRefs = Mapping[str, SecretRef]


def resolve_env_secret(
    env_var: str | None,
    *,
    field_name: str | None = None,
    connection_name: str | None = None,
    env: Mapping[str, str] | None = None,
    allow_empty: bool = False,
) -> ResolvedSecret | None:
    """Resolve a single environment variable reference.

    Parameters
    ----------
    env_var:
        The environment variable name to read. If ``None``, ``None`` is
        returned so optional config fields can be represented directly.
    field_name:
        Logical field name for better error messages.
    connection_name:
        Optional connection name for better error messages.
    env:
        Environment mapping to read from. Defaults to :data:`os.environ`.
    allow_empty:
        Allow empty-string values. The default is ``False`` because empty secret
        values are usually configuration mistakes.
    """

    if env_var is None:
        return None

    source = environ if env is None else env
    raw_value = source.get(env_var, _MISSING)
    if raw_value is _MISSING:
        raise MissingSecretError(
            env_var,
            field_name=field_name,
            connection_name=connection_name,
        )

    if raw_value == "" and not allow_empty:
        raise EmptySecretError(
            env_var,
            field_name=field_name,
            connection_name=connection_name,
        )

    if not isinstance(raw_value, str):
        raw_value = str(raw_value)

    return ResolvedSecret(
        env_var=env_var,
        value=raw_value,
        field_name=field_name,
        connection_name=connection_name,
    )


def resolve_env_secrets(
    secret_refs: SecretRefs,
    *,
    connection_name: str | None = None,
    env: Mapping[str, str] | None = None,
    allow_empty: bool = False,
) -> dict[str, ResolvedSecret]:
    """Resolve multiple secret references in one pass.

    ``secret_refs`` maps logical field names to environment variable names.
    ``None`` values are ignored, which makes this suitable for optional secret
    inputs such as role names or database names that may be configured directly.
    """

    resolved: dict[str, ResolvedSecret] = {}
    for field_name, env_var in secret_refs.items():
        secret = resolve_env_secret(
            env_var,
            field_name=field_name,
            connection_name=connection_name,
            env=env,
            allow_empty=allow_empty,
        )
        if secret is not None:
            resolved[field_name] = secret
    return resolved


def resolve_env_secret_value(
    env_var: str | None,
    *,
    field_name: str | None = None,
    connection_name: str | None = None,
    env: Mapping[str, str] | None = None,
    allow_empty: bool = False,
) -> str | None:
    """Convenience wrapper that returns the raw secret value.

    Prefer :func:`resolve_env_secret` when you want a redacted object for debug
    logging or structured tracing.
    """

    secret = resolve_env_secret(
        env_var,
        field_name=field_name,
        connection_name=connection_name,
        env=env,
        allow_empty=allow_empty,
    )
    return None if secret is None else secret.value


def resolve_env_secret_values(
    secret_refs: SecretRefs,
    *,
    connection_name: str | None = None,
    env: Mapping[str, str] | None = None,
    allow_empty: bool = False,
) -> dict[str, str]:
    """Resolve multiple secret references and return raw values."""

    resolved: dict[str, str] = {}
    for field_name, env_var in secret_refs.items():
        value = resolve_env_secret_value(
            env_var,
            field_name=field_name,
            connection_name=connection_name,
            env=env,
            allow_empty=allow_empty,
        )
        if value is not None:
            resolved[field_name] = value
    return resolved


def secret_refs_from_mapping(
    mapping: Mapping[str, Any],
    *,
    suffix: str = "_env",
) -> dict[str, str | None]:
    """Collect secret reference fields from a generic mapping.

    Any key ending in ``suffix`` is treated as a secret reference field and the
    suffix is stripped from the returned logical field name.
    """

    refs: dict[str, str | None] = {}
    for key, value in mapping.items():
        if key.endswith(suffix):
            refs[key[: -len(suffix)] or key] = value
    return refs


__all__ = [
    "EmptySecretError",
    "MissingSecretError",
    "ResolvedSecret",
    "SecretRef",
    "SecretRefs",
    "SecretResolutionError",
    "resolve_env_secret",
    "resolve_env_secret_value",
    "resolve_env_secret_values",
    "resolve_env_secrets",
    "secret_refs_from_mapping",
]
