from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from db_mcp_server.models import (
    ConnectionTestResult,
    ExplainResult,
    QueryOptions,
    QueryResult,
    SchemaInfo,
    TableDescription,
    TableInfo,
)


@runtime_checkable
class DatabaseAdapter(Protocol):
    """Backend adapter contract for the universal DB MCP server."""

    def test_connection(self) -> ConnectionTestResult: ...

    def list_schemas(self) -> list[SchemaInfo]: ...

    def list_tables(
        self,
        catalog: str | None,
        schema: str | None,
        include_views: bool,
    ) -> list[TableInfo]: ...

    def describe_table(self, catalog: str | None, schema: str, table: str) -> TableDescription: ...

    def run_query(self, sql: str, params: dict[str, Any], options: QueryOptions) -> QueryResult: ...

    def explain_query(self, sql: str, params: dict[str, Any], options: QueryOptions) -> ExplainResult: ...


__all__ = ["DatabaseAdapter"]
