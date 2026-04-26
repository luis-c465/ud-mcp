from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

import pytest

from db_mcp_server.adapters.base import DatabaseAdapter
from db_mcp_server.config.models import Config, DefaultsConfig, ServerConfig, SqlServerConnectionConfig
from db_mcp_server.models.connection import ConnectionDescriptor, ConnectionTestResult
from db_mcp_server.models.metadata import ColumnInfo, SchemaInfo, TableDescription, TableInfo
from db_mcp_server.models.query import QueryOptions
from db_mcp_server.models.result import ExplainResult, QueryResult, ResultWarning
from db_mcp_server.services.connection_registry import ConnectionRegistry


@dataclass(slots=True)
class FakeAdapter:
    calls: list[tuple[object, ...]] = field(default_factory=list)

    def test_connection(self) -> ConnectionTestResult:
        self.calls.append(("test_connection",))
        return ConnectionTestResult(
            ok=True,
            connection=ConnectionDescriptor(
                name="primary",
                backend_type="fake",
                description="Fake adapter",
                catalog="demo",
                schema="public",
                read_only=True,
                allow_full_permissions=False,
                object_type="connection",
                backend_metadata={"adapter": "fake"},
            ),
            message="ok",
            elapsed_ms=3.5,
            warnings=[ResultWarning(code="informational", message="no live database was contacted")],
            backend_metadata={"adapter": "fake"},
        )

    def list_schemas(self) -> list[SchemaInfo]:
        self.calls.append(("list_schemas",))
        return [SchemaInfo(catalog="demo", schema="analytics", name="analytics")]

    def list_tables(self, catalog: str | None, schema: str | None, include_views: bool) -> list[TableInfo]:
        self.calls.append(("list_tables", catalog, schema, include_views))
        return [TableInfo(catalog=catalog, schema=schema, name="widgets", object_type="table")]

    def describe_table(self, catalog: str | None, schema: str, table: str) -> TableDescription:
        self.calls.append(("describe_table", catalog, schema, table))
        return TableDescription(
            catalog=catalog,
            schema=schema,
            name=table,
            object_type="table",
            columns=[
                ColumnInfo(name="id", data_type="INTEGER", ordinal_position=1, nullable=False),
                ColumnInfo(name="name", data_type="VARCHAR", ordinal_position=2, nullable=False),
            ],
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
            elapsed_ms=11.25,
            warnings=[ResultWarning(code="informational", message="fake execution")],
            query_id="query-1",
            statement_type="SELECT",
            backend_metadata={"backend_type": "fake"},
        )

    def explain_query(self, sql: str, params: dict[str, object], options: QueryOptions) -> ExplainResult:
        self.calls.append(("explain_query", sql, params, options.model_dump()))
        return ExplainResult(
            columns=[],
            rows=[],
            row_count=0,
            truncated=False,
            elapsed_ms=4.0,
            warnings=[],
            query_id="query-2",
            statement_type="EXPLAIN",
            backend_metadata={"backend_type": "fake"},
            plan_text="SEQ SCAN widgets",
            plan_format="text",
            source_query=sql,
        )


def _build_config() -> Config:
    return Config(
        server=ServerConfig(name="adapter-contracts", transport="stdio", log_level="info"),
        defaults=DefaultsConfig(),
        connections={
            "primary": SqlServerConnectionConfig(
                description="Test connection",
                dsn_env="PRIMARY_DSN",
            )
        },
    )


def _build_direct_adapter() -> FakeAdapter:
    return FakeAdapter()


def _build_registry_adapter() -> FakeAdapter:
    registry = ConnectionRegistry(
        _build_config(),
        adapter_factories={"sqlserver": lambda *args, **kwargs: FakeAdapter()},
    )
    return registry.create_adapter("primary", env={"PRIMARY_DSN": "Driver={ODBC Driver 18 for SQL Server};Server=unit-test;"})


def _exercise_adapter_contract(adapter: DatabaseAdapter) -> None:
    assert isinstance(adapter, DatabaseAdapter)

    connection_test = adapter.test_connection()
    assert connection_test.ok is True
    assert connection_test.connection is not None
    assert connection_test.connection.name == "primary"
    assert connection_test.connection.backend_type == "fake"

    schemas = adapter.list_schemas()
    assert [schema.name for schema in schemas] == ["analytics"]
    assert schemas[0].object_type == "schema"

    tables = adapter.list_tables("demo", "public", True)
    assert [table.name for table in tables] == ["widgets"]
    assert tables[0].schema == "public"

    description = adapter.describe_table("demo", "public", "widgets")
    assert description.name == "widgets"
    assert [column.name for column in description.columns] == ["id", "name"]

    query_options = QueryOptions(
        permission_mode="readonly",
        timeout_ms=1_000,
        max_rows=10,
        max_bytes=2_048,
        allow_multiple_statements=False,
    )
    query_result = adapter.run_query("select 1", {"tenant": "demo"}, query_options)
    assert query_result.row_count == 1
    assert query_result.rows == [[1, "alpha"]]
    assert query_result.statement_type == "SELECT"

    explain_result = adapter.explain_query("select 1", {"tenant": "demo"}, query_options)
    assert explain_result.plan_text == "SEQ SCAN widgets"
    assert explain_result.source_query == "select 1"
    assert explain_result.statement_type == "EXPLAIN"

    assert [call[0] for call in adapter.calls] == [
        "test_connection",
        "list_schemas",
        "list_tables",
        "describe_table",
        "run_query",
        "explain_query",
    ]
    assert adapter.calls[4][3] == query_options.model_dump()
    assert adapter.calls[5][3] == query_options.model_dump()


@pytest.mark.parametrize(
    "adapter_builder",
    [
        pytest.param(_build_direct_adapter, id="direct-fake-adapter"),
        pytest.param(_build_registry_adapter, id="registry-builder-fake-adapter"),
    ],
)
def test_fake_adapters_follow_the_shared_database_adapter_contract(
    adapter_builder: Callable[[], FakeAdapter],
) -> None:
    _exercise_adapter_contract(adapter_builder())
