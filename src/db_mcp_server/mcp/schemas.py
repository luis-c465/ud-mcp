from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from db_mcp_server.models import ConnectionDescriptor, ConnectionTestResult, ExplainResult, QueryOptions, QueryResult, SchemaInfo, TableDescription, TableInfo


class MCPModel(BaseModel):
    """Base model for MCP request and response payloads."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class ListConnectionsRequest(MCPModel):
    """Request model for list_connections."""


class ListConnectionsResponse(MCPModel):
    """Response model for list_connections."""

    connections: list[ConnectionDescriptor] = Field(default_factory=list)


class TestConnectionRequest(MCPModel):
    """Request model for test_connection."""

    connection_name: str


class TestConnectionResponse(MCPModel):
    """Response model for test_connection."""

    result: ConnectionTestResult


class ListSchemasRequest(MCPModel):
    """Request model for list_schemas."""

    connection_name: str


class ListSchemasResponse(MCPModel):
    """Response model for list_schemas."""

    schemas: list[SchemaInfo] = Field(default_factory=list)


class ListTablesRequest(MCPModel):
    """Request model for list_tables."""

    connection_name: str
    catalog: str | None = None
    schema_name: str | None = Field(default=None, alias="schema", serialization_alias="schema")
    include_views: bool = False

    @property
    def schema(self) -> str | None:
        return self.schema_name


class ListTablesResponse(MCPModel):
    """Response model for list_tables."""

    tables: list[TableInfo] = Field(default_factory=list)


class DescribeTableRequest(MCPModel):
    """Request model for describe_table."""

    connection_name: str
    catalog: str | None = None
    schema_name: str | None = Field(default=None, alias="schema", serialization_alias="schema")
    table: str

    @property
    def schema(self) -> str | None:
        return self.schema_name


class DescribeTableResponse(MCPModel):
    """Response model for describe_table."""

    table: TableDescription


class RunQueryRequest(MCPModel):
    """Request model for run_query."""

    connection_name: str
    sql: str
    params: dict[str, Any] = Field(default_factory=dict)
    options: QueryOptions = Field(default_factory=QueryOptions)


class RunQueryResponse(MCPModel):
    """Response model for run_query."""

    result: QueryResult


class ExplainQueryRequest(MCPModel):
    """Request model for explain_query."""

    connection_name: str
    sql: str
    params: dict[str, Any] = Field(default_factory=dict)
    options: QueryOptions = Field(default_factory=QueryOptions)


class ExplainQueryResponse(MCPModel):
    """Response model for explain_query."""

    result: ExplainResult


__all__ = [
    "DescribeTableRequest",
    "DescribeTableResponse",
    "ExplainQueryRequest",
    "ExplainQueryResponse",
    "ListConnectionsRequest",
    "ListConnectionsResponse",
    "ListSchemasRequest",
    "ListSchemasResponse",
    "ListTablesRequest",
    "ListTablesResponse",
    "MCPModel",
    "RunQueryRequest",
    "RunQueryResponse",
    "TestConnectionRequest",
    "TestConnectionResponse",
]
