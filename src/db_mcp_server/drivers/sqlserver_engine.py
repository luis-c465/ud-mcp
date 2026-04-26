from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlalchemy.engine import Engine

from db_mcp_server.adapters.sqlalchemy_base import build_engine
from db_mcp_server.config.models import SqlServerConnectionConfig


def build_sqlserver_engine(
    config: SqlServerConnectionConfig,
    secrets: Mapping[str, str] | None = None,
    *,
    connection_name: str | None = None,
    **engine_kwargs: Any,
) -> Engine:
    """Build a SQL Server SQLAlchemy engine backed by pyodbc.

    The DSN or raw ODBC connection string is expected to be resolved already and
    supplied via ``secrets``. The URL itself stays secret-free so repr/log output
    does not leak credential material.
    """

    if config.driver != "pyodbc" and "creator" not in engine_kwargs:
        raise NotImplementedError(
            f"SQL Server driver {config.driver!r} is not implemented yet for connection {connection_name or '<unnamed>'!r}."
        )

    dsn_value = _first_secret(secrets, "dsn", "odbc_connect", "connection_string")
    if dsn_value is None and "creator" not in engine_kwargs:
        raise ValueError(
            f"Missing resolved SQL Server DSN for connection {connection_name or '<unnamed>'!r}."
        )

    connect_args = dict(engine_kwargs.pop("connect_args", {}) or {})
    if "creator" not in engine_kwargs:
        engine_kwargs["creator"] = _pyodbc_creator(_normalize_odbc_connect_string(dsn_value or ""), connect_args)

    return build_engine("mssql+pyodbc://", **engine_kwargs)


def _first_secret(secrets: Mapping[str, str] | None, *names: str) -> str | None:
    if not secrets:
        return None
    for name in names:
        value = secrets.get(name)
        if value:
            return value
    return None


def _normalize_odbc_connect_string(value: str) -> str:
    candidate = value.strip()
    if not candidate:
        raise ValueError("The resolved SQL Server DSN is empty.")

    upper_candidate = candidate.upper()
    if "=" in candidate or upper_candidate.startswith(("DSN=", "DRIVER=", "SERVER=", "UID=", "PWD=")):
        return candidate
    return f"DSN={candidate}"


def _pyodbc_creator(odbc_connect: str, connect_args: Mapping[str, Any]):
    def creator() -> Any:
        try:
            import pyodbc
        except ModuleNotFoundError as exc:  # pragma: no cover - dependency availability is environment specific
            raise RuntimeError("pyodbc is required to build the SQL Server engine.") from exc

        return pyodbc.connect(odbc_connect, **dict(connect_args))

    return creator


__all__ = ["build_sqlserver_engine"]
