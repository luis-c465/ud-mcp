from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

from mcp.server.fastmcp import FastMCP

from db_mcp_server.mcp.schemas import (
    DescribeTableRequest,
    DescribeTableResponse,
    ExplainQueryRequest,
    ExplainQueryResponse,
    ListConnectionsResponse,
    ListSchemasRequest,
    ListSchemasResponse,
    ListTablesRequest,
    ListTablesResponse,
    RunQueryRequest,
    RunQueryResponse,
    TestConnectionResponse,
)
from db_mcp_server.models import ConnectionDescriptor, ConnectionTestResult, ExplainResult, QueryOptions, QueryResult, SchemaInfo, TableDescription, TableInfo


class ConnectionRegistryService(Protocol):
    """Minimal registry interface required by the MCP tools."""

    def list_connections(self) -> list[ConnectionDescriptor]: ...

    def create_adapter(self, name: str, *, env: Mapping[str, str] | None = None) -> Any: ...


class MetadataService(Protocol):
    """Minimal metadata interface required by the MCP tools."""

    def list_schemas(self, connection_name: str) -> list[SchemaInfo]: ...

    def list_tables(
        self,
        connection_name: str,
        catalog: str | None = None,
        schema: str | None = None,
        include_views: bool = False,
    ) -> list[TableInfo]: ...

    def describe_table(
        self,
        connection_name: str,
        catalog: str | None = None,
        schema: str | None = None,
        table: str | None = None,
    ) -> TableDescription: ...


class QueryService(Protocol):
    """Minimal query interface required by the MCP tools."""

    def run_query(
        self,
        connection_name: str,
        sql: str,
        params: Mapping[str, Any] | None = None,
        options: QueryOptions | None = None,
    ) -> QueryResult: ...

    def explain_query(
        self,
        connection_name: str,
        sql: str,
        params: Mapping[str, Any] | None = None,
        options: QueryOptions | None = None,
    ) -> ExplainResult: ...


def register_tools(
    server: FastMCP[Any],
    *,
    connection_registry: ConnectionRegistryService,
    metadata_service: MetadataService,
    query_service: QueryService,
) -> FastMCP[Any]:
    """Register the database MCP tools on a FastMCP server."""

    @server.tool(name="list_connections", description="List configured database connections.")
    def list_connections() -> ListConnectionsResponse:
        return ListConnectionsResponse(connections=connection_registry.list_connections())

    @server.tool(name="test_connection", description="Test a configured database connection.")
    def test_connection(connection_name: str) -> TestConnectionResponse:
        adapter = connection_registry.create_adapter(connection_name)
        result = adapter.test_connection()
        if not isinstance(result, ConnectionTestResult):
            result = ConnectionTestResult.model_validate(result)
        return TestConnectionResponse(result=result)

    @server.tool(name="list_schemas", description="List schemas for a configured connection.")
    def list_schemas(connection_name: str) -> ListSchemasResponse:
        request = ListSchemasRequest(connection_name=connection_name)
        return ListSchemasResponse(schemas=metadata_service.list_schemas(request.connection_name))

    @server.tool(name="list_tables", description="List tables or views for a configured connection.")
    def list_tables(
        connection_name: str,
        catalog: str | None = None,
        schema: str | None = None,
        include_views: bool = False,
    ) -> ListTablesResponse:
        request = ListTablesRequest(
            connection_name=connection_name,
            catalog=catalog,
            schema=schema,
            include_views=include_views,
        )
        return ListTablesResponse(
            tables=metadata_service.list_tables(
                request.connection_name,
                catalog=request.catalog,
                schema=request.schema,
                include_views=request.include_views,
            )
        )

    @server.tool(name="describe_table", description="Describe a table and its columns.")
    def describe_table(
        connection_name: str,
        table: str,
        catalog: str | None = None,
        schema: str | None = None,
    ) -> DescribeTableResponse:
        request = DescribeTableRequest(
            connection_name=connection_name,
            catalog=catalog,
            schema=schema,
            table=table,
        )
        return DescribeTableResponse(
            table=metadata_service.describe_table(
                request.connection_name,
                catalog=request.catalog,
                schema=request.schema,
                table=request.table,
            )
        )

    @server.tool(name="run_query", description="Execute a SQL query through the service layer.")
    def run_query(
        connection_name: str,
        sql: str,
        params: dict[str, Any] | None = None,
        options: QueryOptions | None = None,
    ) -> RunQueryResponse:
        request = RunQueryRequest(
            connection_name=connection_name,
            sql=sql,
            params={} if params is None else params,
            options=QueryOptions() if options is None else options,
        )
        return RunQueryResponse(
            result=query_service.run_query(
                request.connection_name,
                request.sql,
                params=request.params,
                options=request.options,
            )
        )

    @server.tool(name="explain_query", description="Explain a SQL query through the service layer.")
    def explain_query(
        connection_name: str,
        sql: str,
        params: dict[str, Any] | None = None,
        options: QueryOptions | None = None,
    ) -> ExplainQueryResponse:
        request = ExplainQueryRequest(
            connection_name=connection_name,
            sql=sql,
            params={} if params is None else params,
            options=QueryOptions() if options is None else options,
        )
        return ExplainQueryResponse(
            result=query_service.explain_query(
                request.connection_name,
                request.sql,
                params=request.params,
                options=request.options,
            )
        )

    return server


__all__ = ["ConnectionRegistryService", "MetadataService", "QueryService", "register_tools"]
