from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from db_mcp_server.config.models import Config, DefaultsConfig, ServerConfig, SqlServerConnectionConfig
from db_mcp_server.models.connection import ConnectionDescriptor, ConnectionTestResult
from db_mcp_server.models.metadata import ColumnInfo
from db_mcp_server.models.query import QueryOptions
from db_mcp_server.models.result import ExplainResult, QueryResult, ResultWarning
from db_mcp_server.server import build_server_bundle
from db_mcp_server.services.metadata_service import SchemaInfo, TableColumnInfo, TableDescription, TableInfo


class FakeAdapter:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []

    def test_connection(self) -> ConnectionTestResult:
        self.calls.append(("test_connection",))
        return ConnectionTestResult(
            ok=True,
            connection=ConnectionDescriptor(
                name="primary",
                backend_type="fake",
                description="Smoke-test adapter",
                catalog="demo",
                schema="public",
                read_only=True,
                allow_full_permissions=False,
                object_type="connection",
                backend_metadata={"adapter": "fake"},
            ),
            message="connected",
            elapsed_ms=1.25,
            warnings=[],
            backend_metadata={"adapter": "fake"},
        )

    def run_query(self, sql: str, params: dict[str, object], options: QueryOptions) -> QueryResult:
        self.calls.append(("run_query", sql, params, options.model_dump()))
        return QueryResult(
            columns=[
                ColumnInfo(name="id", data_type="INTEGER", ordinal_position=1, nullable=False),
                ColumnInfo(name="name", data_type="VARCHAR", ordinal_position=2, nullable=False),
            ],
            rows=[[1, "alpha"]],
            row_count=1,
            truncated=False,
            elapsed_ms=12,
            warnings=[ResultWarning(code="informational", message="fake row set")],
            query_id="query-1",
            statement_type="SELECT",
            backend_metadata={"backend_type": "fake", "query_id": "query-1"},
        )

    def explain_query(self, sql: str, params: dict[str, object], options: QueryOptions) -> ExplainResult:
        self.calls.append(("explain_query", sql, params, options.model_dump()))
        return ExplainResult(
            columns=[],
            rows=[],
            row_count=0,
            truncated=False,
            elapsed_ms=6,
            warnings=[],
            query_id="query-2",
            statement_type="EXPLAIN",
            backend_metadata={"backend_type": "fake", "query_id": "query-2"},
            plan_text="SEQ SCAN widgets",
            plan_format="text",
            source_query=sql,
        )


def _build_bundle():
    config = Config(
        server=ServerConfig(name="smoke-test-server", transport="stdio", log_level="info"),
        defaults=DefaultsConfig(),
        connections={
            "primary": SqlServerConnectionConfig(
                description="Smoke-test connection",
                dsn_env="PRIMARY_DSN",
            )
        },
    )
    return build_server_bundle(config)


def _bundle_json_content(result: object) -> object:
    if isinstance(result, tuple) and len(result) == 2:
        structured_result = result[1]
        if isinstance(structured_result, dict) and "result" in structured_result:
            return structured_result["result"]
        return structured_result

    content_blocks = result
    assert isinstance(content_blocks, list)
    assert len(content_blocks) == 1
    content = content_blocks[0]
    assert getattr(content, "type", "text") == "text"
    return json.loads(content.text)


async def _read_resource(bundle, uri: str) -> str:
    contents = await bundle.server.read_resource(uri)
    assert len(contents) == 1
    return contents[0].content



@pytest.fixture()
def bundle_and_adapter(monkeypatch):
    bundle = _build_bundle()
    adapter = FakeAdapter()

    monkeypatch.setattr(bundle.registry, "get_adapter", lambda name, env=None: adapter)
    monkeypatch.setattr(
        bundle.validation_service,
        "validate_metadata_request",
        lambda connection_name, operation, permission_mode=None: SimpleNamespace(
            connection_name=connection_name,
            operation=operation,
            policy=SimpleNamespace(details={"permission_mode": permission_mode or "readonly"}),
        ),
    )
    monkeypatch.setattr(
        bundle.validation_service,
        "validate_query_request",
        lambda connection_name, sql, **kwargs: SimpleNamespace(
            connection_name=connection_name,
            sql=sql,
            policy=SimpleNamespace(
                details={
                    "permission_mode": kwargs.get("permission_mode") or "readonly",
                    "allow_multiple_statements": kwargs.get("allow_multiple_statements", False),
                }
            ),
            limits=SimpleNamespace(
                timeout_ms=kwargs.get("timeout_ms") or 1_000,
                max_rows=kwargs.get("max_rows") or 10,
                max_bytes=kwargs.get("max_bytes") or 2_048,
            ),
        ),
    )
    monkeypatch.setattr(
        bundle.metadata_service,
        "list_schemas",
        lambda connection_name: [SchemaInfo(catalog="demo", schema="analytics", name="analytics")],
    )
    monkeypatch.setattr(
        bundle.metadata_service,
        "list_tables",
        lambda connection_name, catalog=None, schema=None, include_views=False: [
            TableInfo(catalog=catalog, schema=schema, name="widgets", object_type="table")
        ],
    )
    monkeypatch.setattr(
        bundle.metadata_service,
        "describe_table",
        lambda connection_name, catalog=None, schema=None, table=None: TableDescription(
            catalog=catalog,
            schema=schema,
            name=table or "widgets",
            object_type="table",
            columns=[
                TableColumnInfo(name="id", type="INTEGER", ordinal_position=1, nullable=False),
                TableColumnInfo(name="name", type="VARCHAR", ordinal_position=2, nullable=False),
            ],
        ),
    )
    monkeypatch.setattr(bundle.audit_service, "success", lambda *args, **kwargs: None)
    monkeypatch.setattr(bundle.audit_service, "failure", lambda *args, **kwargs: None)

    return bundle, adapter


def test_build_server_registers_tools_resources_and_prompts(bundle_and_adapter):
    bundle, _adapter = bundle_and_adapter

    tool_names = {tool.name for tool in asyncio.run(bundle.server.list_tools())}
    assert tool_names == {
        "list_connections",
        "test_connection",
        "list_schemas",
        "list_tables",
        "describe_table",
        "run_query",
        "explain_query",
    }

    resource_uris = {str(resource.uri) for resource in asyncio.run(bundle.server.list_resources())}
    assert resource_uris == {"dbmcp://config", "dbmcp://connections"}

    resource_templates = {str(template.uriTemplate) for template in asyncio.run(bundle.server.list_resource_templates())}
    assert resource_templates == {"dbmcp://connections/{connection_name}"}

    prompt_names = {prompt.name for prompt in asyncio.run(bundle.server.list_prompts())}
    assert prompt_names == {"review_query", "inspect_connection"}

    config_text = asyncio.run(_read_resource(bundle, "dbmcp://config"))
    assert "smoke-test-server" in config_text
    assert "primary" in config_text

    connection_text = asyncio.run(_read_resource(bundle, "dbmcp://connections/primary"))
    assert "primary" in connection_text
    assert "sqlserver" in connection_text


@pytest.mark.parametrize(
    "tool_name,arguments,expected",
    [
        pytest.param(
            "list_connections",
            {},
            lambda payload: payload[0]["name"] == "primary",
            id="list-connections",
        ),
        pytest.param(
            "test_connection",
            {"connection_name": "primary"},
            lambda payload: payload["ok"] is True and payload["connection"]["name"] == "primary",
            id="test-connection",
        ),
        pytest.param(
            "list_schemas",
            {"connection_name": "primary"},
            lambda payload: [schema["name"] for schema in payload] == ["analytics"],
            id="list-schemas",
        ),
        pytest.param(
            "list_tables",
            {"connection_name": "primary", "catalog": "demo", "schema": "public", "include_views": True},
            lambda payload: payload[0]["name"] == "widgets" and payload[0]["schema"] == "public",
            id="list-tables",
        ),
        pytest.param(
            "describe_table",
            {"connection_name": "primary", "catalog": "demo", "schema": "public", "table": "widgets"},
            lambda payload: payload["name"] == "widgets" and [column["name"] for column in payload["columns"]] == ["id", "name"],
            id="describe-table",
        ),
        pytest.param(
            "run_query",
            {
                "connection_name": "primary",
                "sql": "select 1",
                "params": {"tenant": "demo"},
                "timeout_ms": 5_000,
                "max_rows": 25,
                "max_bytes": 8_192,
                "dialect": "ansi",
            },
            lambda payload: payload["row_count"] == 1 and payload["rows"] == [[1, "alpha"]] and payload["backend_metadata"]["backend_type"] == "fake",
            id="run-query",
        ),
        pytest.param(
            "explain_query",
            {
                "connection_name": "primary",
                "sql": "select 1",
                "params": {"tenant": "demo"},
                "timeout_ms": 5_000,
                "max_rows": 25,
                "max_bytes": 8_192,
                "dialect": "ansi",
            },
            lambda payload: payload["plan"] == "SEQ SCAN widgets" and payload["statement_type"] == "EXPLAIN",
            id="explain-query",
        ),
    ],
)
def test_fastmcp_tool_paths_return_offline_payloads(bundle_and_adapter, tool_name, arguments, expected):
    bundle, adapter = bundle_and_adapter

    payload = _bundle_json_content(asyncio.run(bundle.server.call_tool(tool_name, arguments)))
    assert expected(payload)

    if tool_name == "test_connection":
        assert adapter.calls[0][0] == "test_connection"
    elif tool_name in {"run_query", "explain_query"}:
        assert adapter.calls[-1][0] == tool_name
        assert adapter.calls[-1][2] == {"tenant": "demo"}
        assert adapter.calls[-1][3]["permission_mode"] == "readonly"
