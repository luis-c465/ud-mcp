from __future__ import annotations

from types import SimpleNamespace

import pytest

from db_mcp_server.config.models import Config, SqlServerConnectionConfig
from db_mcp_server.models import QueryOptions
from db_mcp_server.safety.errors import DbMcpError, ErrorCode
from db_mcp_server.services.connection_registry import ConnectionRegistry
from db_mcp_server.services.query_service import QueryService
from db_mcp_server.services.validation_service import ValidationService


class FakeAdapter:
    def __init__(self) -> None:
        self.run_calls: list[tuple[str, dict[str, object], QueryOptions]] = []
        self.explain_calls: list[tuple[str, dict[str, object], QueryOptions]] = []

    def test_connection(self) -> dict[str, object]:
        return {"ok": True}

    def list_schemas(self) -> list[object]:
        return []

    def list_tables(self, catalog: str | None, schema: str | None, include_views: bool) -> list[object]:
        return []

    def describe_table(self, catalog: str | None, schema: str, table: str) -> dict[str, object]:
        return {}

    def run_query(self, sql: str, params: dict[str, object], options: QueryOptions) -> dict[str, object]:
        self.run_calls.append((sql, params, options))
        return {
            "columns": [
                {"name": "id", "data_type": "INTEGER"},
                {"name": "name", "data_type": "VARCHAR"},
            ],
            "rows": [{"id": 1, "name": "Alice"}],
            "warnings": [{"message": "partial result", "code": "WARN_PARTIAL"}],
            "backend_metadata": {"query_id": "query-123", "statement_type": "SELECT"},
            "elapsed_ms": 5,
            "row_count": 1,
            "truncated": False,
            "statement_type": "SELECT",
            "query_id": "query-123",
        }

    def explain_query(self, sql: str, params: dict[str, object], options: QueryOptions) -> dict[str, object]:
        self.explain_calls.append((sql, params, options))
        return {
            "columns": ["step", "details"],
            "rows": [("scan", "table scans")],
            "backend_metadata": {"query_id": "plan-456", "statement_type": "EXPLAIN"},
            "elapsed_ms": 3,
            "statement_type": "EXPLAIN",
        }


class RecordingAuditService:
    def __init__(self) -> None:
        self.success_calls: list[tuple[tuple[object, ...], dict[str, object]]] = []
        self.failure_calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def success(self, *args: object, **kwargs: object) -> None:
        self.success_calls.append((args, kwargs))

    def failure(self, *args: object, **kwargs: object) -> None:
        self.failure_calls.append((args, kwargs))


class FakeValidationService:
    def __init__(self, config: Config) -> None:
        self._service = ValidationService(config)
        self.calls: list[tuple[str, str, dict[str, object]]] = []

    def validate_query_request(self, connection_name: str, sql: str, **kwargs: object):
        self.calls.append((connection_name, sql, dict(kwargs)))
        analysis = SimpleNamespace(kind=SimpleNamespace(value="select"), statements=[])
        policy = SimpleNamespace(
            allowed=True,
            reason=SimpleNamespace(value="allowed"),
            message="allowed",
            details={"permission_mode": kwargs.get("permission_mode")},
        )
        connection = self._service.config.connections[connection_name]
        return SimpleNamespace(
            connection_name=connection_name,
            connection=connection,
            sql=sql.strip(),
            analysis=analysis,
            limits=SimpleNamespace(
                timeout_ms=kwargs.get("timeout_ms"),
                max_rows=kwargs.get("max_rows"),
                max_bytes=kwargs.get("max_bytes"),
            ),
            policy=policy,
        )


def test_query_service_runs_query_with_validation_adapter_and_audit() -> None:
    config = Config(
        connections={
            "primary": SqlServerConnectionConfig(dsn_env="PRIMARY_DSN", read_only=True),
        }
    )
    validation_service = FakeValidationService(config)
    adapter = FakeAdapter()
    audit_service = RecordingAuditService()

    def fake_factory(*, config: object, secrets: object, connection_name: str) -> FakeAdapter:
        assert connection_name == "primary"
        assert secrets == {"dsn": "dsn://example"}
        return adapter

    registry = ConnectionRegistry(config, adapter_factories={"sqlserver": fake_factory})
    service = QueryService(
        validation_service,  # type: ignore[arg-type]
        registry,
        audit_service=audit_service,
        env={"PRIMARY_DSN": "dsn://example"},
    )

    result = service.run_query(
        "primary",
        "  SELECT id, name FROM users  ",
        params={"limit": 1},
        options=QueryOptions(permission_mode="readonly", timeout_ms=100, max_rows=20, max_bytes=1024, allow_multiple_statements=True),
        max_rows=10,
        request_id="req-1",
        actor="alice",
    )

    assert validation_service.calls == [
        (
            "primary",
            "  SELECT id, name FROM users  ",
            {
                "permission_mode": "readonly",
                "timeout_ms": 100,
                "max_rows": 10,
                "max_bytes": 1024,
                "dialect": None,
            },
        )
    ]
    assert adapter.run_calls == [
        (
            "SELECT id, name FROM users",
            {"limit": 1},
            QueryOptions(permission_mode="readonly", timeout_ms=100, max_rows=10, max_bytes=1024, allow_multiple_statements=True),
        )
    ]
    assert result.row_count == 1
    assert result.rows == [[1, "Alice"]]
    assert result.columns[0].name == "id"
    assert result.statement_type == "SELECT"
    assert result.query_id == "query-123"
    assert result.backend_metadata == {"query_id": "query-123", "statement_type": "SELECT", "backend_type": "sqlserver"}
    assert audit_service.failure_calls == []
    assert len(audit_service.success_calls) == 1
    assert audit_service.success_calls[0][0] == ("run_query",)


def test_query_service_explain_query_normalizes_plan_text() -> None:
    config = Config(
        connections={
            "primary": SqlServerConnectionConfig(dsn_env="PRIMARY_DSN"),
        }
    )
    validation_service = FakeValidationService(config)
    adapter = FakeAdapter()
    audit_service = RecordingAuditService()

    def fake_factory(*, config: object, secrets: object, connection_name: str) -> FakeAdapter:
        assert connection_name == "primary"
        assert secrets == {"dsn": "dsn://example"}
        return adapter

    registry = ConnectionRegistry(config, adapter_factories={"sqlserver": fake_factory})
    service = QueryService(validation_service, registry, audit_service=audit_service, env={"PRIMARY_DSN": "dsn://example"})

    result = service.explain_query("primary", "SELECT id FROM users", params={"limit": 5})

    assert validation_service.calls == [
        (
            "primary",
            "SELECT id FROM users",
            {
                "permission_mode": None,
                "timeout_ms": None,
                "max_rows": None,
                "max_bytes": None,
                "dialect": None,
            },
        )
    ]
    assert adapter.explain_calls == [
        (
            "SELECT id FROM users",
            {"limit": 5},
            QueryOptions(permission_mode=None, timeout_ms=None, max_rows=None, max_bytes=None, allow_multiple_statements=None),
        )
    ]
    assert result.plan_text == "scan\ttable scans"
    assert result.plan_format == "text"
    assert result.source_query == "SELECT id FROM users"
    assert result.statement_type == "EXPLAIN"
    assert result.backend_metadata == {"query_id": "plan-456", "statement_type": "EXPLAIN", "backend_type": "sqlserver"}
    assert len(audit_service.success_calls) == 1
    assert audit_service.failure_calls == []


def test_query_service_normalizes_adapter_failures() -> None:
    config = Config(
        connections={
            "primary": SqlServerConnectionConfig(dsn_env="PRIMARY_DSN"),
        }
    )
    validation_service = FakeValidationService(config)
    audit_service = RecordingAuditService()

    class FailingAdapter(FakeAdapter):
        def run_query(self, sql: str, params: dict[str, object], options: QueryOptions) -> dict[str, object]:
            raise RuntimeError("driver exploded")

    failing_adapter = FailingAdapter()

    def fake_factory(*, config: object, secrets: object, connection_name: str) -> FailingAdapter:
        return failing_adapter

    registry = ConnectionRegistry(config, adapter_factories={"sqlserver": fake_factory})
    service = QueryService(validation_service, registry, audit_service=audit_service, env={"PRIMARY_DSN": "dsn://example"})

    with pytest.raises(DbMcpError) as exc_info:
        service.run_query("primary", "SELECT 1")

    assert exc_info.value.code == ErrorCode.BACKEND_ERROR
    assert audit_service.success_calls == []
    assert len(audit_service.failure_calls) == 1
    assert audit_service.failure_calls[0][0] == ("run_query",)
