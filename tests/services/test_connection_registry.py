from __future__ import annotations

import pytest

from db_mcp_server.config.models import Config, SqlServerConnectionConfig
from db_mcp_server.safety.errors import UnknownConnectionError
from db_mcp_server.services.connection_registry import ConnectionRegistry


def test_connection_registry_returns_configured_connection_and_descriptor() -> None:
    config = Config(
        connections={
            "primary": SqlServerConnectionConfig(
                description="Primary reporting warehouse",
                read_only=False,
                allow_full_permissions=True,
                dsn_env="PRIMARY_DSN",
            )
        }
    )
    registry = ConnectionRegistry(config)

    connection = registry.get_connection("primary")
    descriptor = registry.describe_connection("primary")

    assert connection.dsn_env == "PRIMARY_DSN"
    assert descriptor.name == "primary"
    assert descriptor.type == "sqlserver"
    assert descriptor.description == "Primary reporting warehouse"
    assert descriptor.read_only is False
    assert descriptor.allow_full_permissions is True


def test_connection_registry_raises_for_unknown_connection() -> None:
    registry = ConnectionRegistry(Config())

    with pytest.raises(UnknownConnectionError) as exc_info:
        registry.get_connection("missing")

    assert exc_info.value.details == {"connection_name": "missing"}
    assert "missing" in str(exc_info.value)
