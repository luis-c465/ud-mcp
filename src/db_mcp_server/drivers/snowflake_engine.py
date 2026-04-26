from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlalchemy.engine import Engine, URL

from db_mcp_server.adapters.sqlalchemy_base import build_engine
from db_mcp_server.config.models import SnowflakeConnectionConfig


def build_snowflake_engine(
    config: SnowflakeConnectionConfig,
    secrets: Mapping[str, str] | None = None,
    *,
    connection_name: str | None = None,
    **engine_kwargs: Any,
) -> Engine:
    """Build a Snowflake SQLAlchemy engine using the snowflake dialect."""

    account = _required_secret(secrets, "account", connection_name=connection_name)
    user = _required_secret(secrets, "user", connection_name=connection_name)
    password = _required_secret(secrets, "password", connection_name=connection_name)
    warehouse = _required_secret(secrets, "warehouse", connection_name=connection_name)
    role = _optional_secret(secrets, "role")

    url = URL.create(
        "snowflake",
        username=user,
        password=password,
        host=account,
        database=config.database,
        schema=config.schema_,
        query={
            "warehouse": warehouse,
            **({"role": role} if role else {}),
        },
    )

    return build_engine(url, **engine_kwargs)


def _required_secret(
    secrets: Mapping[str, str] | None,
    name: str,
    *,
    connection_name: str | None = None,
) -> str:
    value = _optional_secret(secrets, name)
    if value is None:
        raise ValueError(
            f"Missing resolved Snowflake {name} for connection {connection_name or '<unnamed>'!r}."
        )
    return value


def _optional_secret(secrets: Mapping[str, str] | None, name: str) -> str | None:
    if not secrets:
        return None
    value = secrets.get(name)
    return value if value else None


__all__ = ["build_snowflake_engine"]
