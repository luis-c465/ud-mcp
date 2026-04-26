from __future__ import annotations

import pytest

from db_mcp_server.config.models import ConnectionConfigBase, DefaultsConfig
from db_mcp_server.safety.errors import QueryBlockedError
from db_mcp_server.safety.policies import PolicyEngine, PolicyReason
from db_mcp_server.safety.sql_parser import parse_sql


def _connection(*, read_only: bool = False, allow_full_permissions: bool = False) -> ConnectionConfigBase:
    return ConnectionConfigBase(
        type="stub",
        read_only=read_only,
        allow_full_permissions=allow_full_permissions,
    )


def test_readonly_mode_blocks_destructive_sql() -> None:
    engine = PolicyEngine(DefaultsConfig())
    analysis = parse_sql("DELETE FROM demo WHERE id = 1")

    decision = engine.evaluate_analysis(analysis, connection=_connection(read_only=False, allow_full_permissions=True))

    assert decision.allowed is False
    assert decision.reason is PolicyReason.DESTRUCTIVE_SQL_BLOCKED
    assert decision.message == "Destructive SQL is not allowed in readonly mode"
    assert decision.details["permission_mode"] == "readonly"
    assert decision.details["has_destructive"] is True

    with pytest.raises(QueryBlockedError) as exc_info:
        decision.raise_forbidden()

    assert exc_info.value.details["reason"] == PolicyReason.DESTRUCTIVE_SQL_BLOCKED.value


def test_full_permission_mode_is_blocked_without_explicit_connection_gate() -> None:
    engine = PolicyEngine(DefaultsConfig(permission_mode="readonly"))

    decision = engine.evaluate_query(
        "SELECT 1",
        connection=_connection(read_only=False, allow_full_permissions=False),
        permission_mode="full",
    )

    assert decision.allowed is False
    assert decision.reason is PolicyReason.FULL_PERMISSION_REQUIRED
    assert decision.message == "Full permissions are not allowed for this connection"
    assert decision.details["permission_mode"] == "full"
    assert decision.details["connection_allow_full_permissions"] is False


def test_full_permission_mode_allows_when_connection_grants_access() -> None:
    engine = PolicyEngine(DefaultsConfig())

    decision = engine.evaluate_query(
        "SELECT 1",
        connection=_connection(read_only=False, allow_full_permissions=True),
        permission_mode="full",
    )

    assert decision.allowed is True
    assert decision.reason is None
    assert decision.details["permission_mode"] == "full"
    assert decision.details["connection_allow_full_permissions"] is True
