"""YAML configuration loading helpers for db-mcp-server.

The loader is intentionally small and opinionated:
- it accepts a file path or raw YAML text
- it requires a mapping at the top level
- it converts the result into the typed config model
- it raises stable, user-friendly errors for parse/validation failures
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from .models import Config


class ConfigError(RuntimeError):
    """Base class for configuration loading failures."""


class ConfigFileNotFoundError(ConfigError):
    """Raised when the requested config file does not exist."""


class ConfigParseError(ConfigError):
    """Raised when YAML cannot be parsed into a mapping."""


class ConfigValidationError(ConfigError):
    """Raised when parsed config data does not validate."""


def load_config(path: str | Path) -> Config:
    """Load a configuration file from disk.

    Parameters
    ----------
    path:
        Path to a YAML configuration file.

    Returns
    -------
    Config
        A validated configuration model.
    """

    config_path = Path(path).expanduser()
    if not config_path.is_file():
        raise ConfigFileNotFoundError(f"Config file does not exist: {config_path}")

    try:
        raw_text = config_path.read_text(encoding="utf-8")
    except OSError as exc:  # pragma: no cover - filesystem failures are environment-specific
        raise ConfigError(f"Failed to read config file {config_path}: {exc}") from exc

    return load_config_text(raw_text, source=str(config_path))


def load_config_text(text: str, *, source: str = "<config>") -> Config:
    """Load a configuration model from YAML text."""

    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ConfigParseError(_format_yaml_error(exc, source)) from exc

    return load_config_data(raw, source=source)


def load_config_data(data: Any, *, source: str = "<config>") -> Config:
    """Validate already-parsed config data."""

    if data is None:
        data = {}

    if not isinstance(data, Mapping):
        raise ConfigParseError(
            f"Configuration in {source} must be a mapping at the top level, "
            f"got {type(data).__name__}."
        )

    try:
        return Config.model_validate(data)
    except ValidationError as exc:
        raise ConfigValidationError(_format_validation_error(exc, source)) from exc


def _format_yaml_error(exc: yaml.YAMLError, source: str) -> str:
    message = str(exc).strip() or "Invalid YAML"
    problem = getattr(exc, "problem", None)
    context = getattr(exc, "context", None)
    mark = getattr(exc, "problem_mark", None) or getattr(exc, "context_mark", None)

    parts: list[str] = []
    if context:
        parts.append(str(context).strip())
    if problem and problem not in parts:
        parts.append(str(problem).strip())
    if not parts:
        parts.append(message)

    location = _format_mark(mark)
    prefix = f"Failed to parse YAML in {source}"
    if location:
        prefix = f"{prefix} at {location}"

    return f"{prefix}: {'; '.join(parts)}"


def _format_validation_error(exc: ValidationError, source: str) -> str:
    lines = [f"Invalid configuration in {source}:"]
    for error in exc.errors():
        location = ".".join(str(part) for part in error.get("loc", ())) or "<root>"
        message = error.get("msg", "Invalid value")
        error_type = error.get("type")
        if error_type:
            lines.append(f"- {location}: {message} ({error_type})")
        else:
            lines.append(f"- {location}: {message}")
    return "\n".join(lines)


def _format_mark(mark: Any) -> str:
    if mark is None:
        return ""

    line = getattr(mark, "line", None)
    column = getattr(mark, "column", None)
    if line is None or column is None:
        return ""

    return f"line {line + 1}, column {column + 1}"


__all__ = [
    "ConfigError",
    "ConfigFileNotFoundError",
    "ConfigParseError",
    "ConfigValidationError",
    "load_config",
    "load_config_data",
    "load_config_text",
]
