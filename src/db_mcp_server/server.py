"""Server assembly for the db-mcp-server package.

This module keeps the boot path explicit and testable:
- load configuration from YAML or a pre-built config model
- wire the registry and service layer together
- register MCP tools, resources, and prompts
- expose helpers for running the server with a chosen transport
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from dataclasses import dataclass
from datetime import date, datetime, time
from enum import Enum
from pathlib import Path
from time import monotonic

from mcp.server import FastMCP
from pydantic import BaseModel

from db_mcp_server.config.loader import load_config
from db_mcp_server.config.models import Config, PermissionMode
from db_mcp_server.safety.errors import DbMcpError, normalize_exception
from db_mcp_server.services.audit_service import AuditService
from db_mcp_server.services.connection_registry import ConnectionRegistry
from db_mcp_server.services.metadata_service import MetadataService
from db_mcp_server.services.query_service import QueryService
from db_mcp_server.services.result_formatter import ResultFormatter
from db_mcp_server.services.validation_service import ValidationService


@dataclass(slots=True)
class ServerBundle:
    """Container for the assembled MCP server and its collaborating services."""

    server: FastMCP
    config: Config
    registry: ConnectionRegistry
    validation_service: ValidationService
    metadata_service: MetadataService
    query_service: QueryService
    result_formatter: ResultFormatter
    audit_service: AuditService


def load_server_config(config: Config | str | Path | None = None) -> Config:
    """Return a validated server config from a YAML path or an existing model."""

    if config is None:
        return Config()
    if isinstance(config, Config):
        return config
    return load_config(config)


def build_server_bundle(
    config: Config | str | Path | None = None,
    *,
    host: str = "127.0.0.1",
    port: int = 8000,
) -> ServerBundle:
    """Build the FastMCP server together with the registry and service layer."""

    resolved_config = load_server_config(config)
    registry = ConnectionRegistry(resolved_config)
    validation_service = ValidationService(resolved_config)
    metadata_service = MetadataService(registry)
    result_formatter = ResultFormatter()
    audit_service = AuditService()
    query_service = QueryService(
        validation_service,
        registry,
        result_formatter=result_formatter,
        audit_service=audit_service,
    )

    server = FastMCP(
        name=resolved_config.server.name,
        log_level=resolved_config.server.log_level.upper(),
        host=host,
        port=port,
        instructions="Universal database MCP server assembled from YAML configuration.",
    )

    _register_tools(
        server,
        registry=registry,
        validation_service=validation_service,
        metadata_service=metadata_service,
        query_service=query_service,
        result_formatter=result_formatter,
        audit_service=audit_service,
    )
    _register_resources(server, registry=registry, config=resolved_config)
    _register_prompts(server, registry=registry, validation_service=validation_service)

    return ServerBundle(
        server=server,
        config=resolved_config,
        registry=registry,
        validation_service=validation_service,
        metadata_service=metadata_service,
        query_service=query_service,
        result_formatter=result_formatter,
        audit_service=audit_service,
    )


def create_server(
    config: Config | str | Path | None = None,
    *,
    host: str = "127.0.0.1",
    port: int = 8000,
) -> FastMCP:
    """Return only the assembled FastMCP server object."""

    return build_server_bundle(config, host=host, port=port).server


def run_server(
    config: Config | str | Path | None = None,
    *,
    transport: str | None = None,
    host: str = "127.0.0.1",
    port: int = 8000,
) -> None:
    """Build and run the MCP server with the requested transport."""

    bundle = build_server_bundle(config, host=host, port=port)
    bundle.server.run(transport=transport or bundle.config.server.transport)


def _register_tools(
    server: FastMCP,
    *,
    registry: ConnectionRegistry,
    validation_service: ValidationService,
    metadata_service: MetadataService,
    query_service: QueryService,
    result_formatter: ResultFormatter,
    audit_service: AuditService,
) -> None:
    @server.tool(name="list_connections", description="List the configured database connections.")
    def list_connections() -> list[dict[str, Any]]:
        start = monotonic()
        connections = registry.list_connections()
        audit_service.success(
            "list_connections",
            resource="connections",
            details={"connection_count": len(connections)},
            duration_ms=_elapsed_ms(start),
        )
        return _jsonify(connections)

    @server.tool(name="test_connection", description="Test that a configured connection can be opened.")
    def test_connection(connection_name: str) -> dict[str, Any]:
        start = monotonic()
        try:
            validated = validation_service.validate_metadata_request(connection_name, "test_connection")
            result = registry.get_adapter(connection_name).test_connection()
        except Exception as exc:
            error = _normalize_error(exc, message=f"Failed to test connection {connection_name!r}.", details={"connection_name": connection_name})
            audit_service.failure(
                "test_connection",
                resource=connection_name,
                details=error.to_dict(),
                duration_ms=_elapsed_ms(start),
            )
            raise error from exc

        audit_service.success(
            "test_connection",
            resource=connection_name,
            details={"policy": validated.policy.details, "ok": getattr(result, "ok", True)},
            duration_ms=_elapsed_ms(start),
        )
        return _jsonify(result)

    @server.tool(name="list_schemas", description="List schemas for a configured connection.")
    def list_schemas(
        connection_name: str,
        permission_mode: PermissionMode | None = None,
    ) -> list[dict[str, Any]]:
        start = monotonic()
        try:
            validated = validation_service.validate_metadata_request(
                connection_name,
                "list_schemas",
                permission_mode=permission_mode,
            )
            result = metadata_service.list_schemas(connection_name)
        except Exception as exc:
            error = _normalize_error(exc, message=f"Failed to list schemas for connection {connection_name!r}.", details={"connection_name": connection_name})
            audit_service.failure(
                "list_schemas",
                resource=connection_name,
                details=error.to_dict(),
                duration_ms=_elapsed_ms(start),
            )
            raise error from exc

        audit_service.success(
            "list_schemas",
            resource=connection_name,
            details={"policy": validated.policy.details, "schema_count": len(result)},
            duration_ms=_elapsed_ms(start),
        )
        return _jsonify(result)

    @server.tool(name="list_tables", description="List tables or views for a configured connection.")
    def list_tables(
        connection_name: str,
        catalog: str | None = None,
        schema: str | None = None,
        include_views: bool = False,
        permission_mode: PermissionMode | None = None,
    ) -> list[dict[str, Any]]:
        start = monotonic()
        try:
            validated = validation_service.validate_metadata_request(
                connection_name,
                "list_tables",
                permission_mode=permission_mode,
            )
            result = metadata_service.list_tables(connection_name, catalog=catalog, schema=schema, include_views=include_views)
        except Exception as exc:
            error = _normalize_error(exc, message=f"Failed to list tables for connection {connection_name!r}.", details={"connection_name": connection_name})
            audit_service.failure(
                "list_tables",
                resource=connection_name,
                details=error.to_dict(),
                duration_ms=_elapsed_ms(start),
            )
            raise error from exc

        audit_service.success(
            "list_tables",
            resource=connection_name,
            details={
                "policy": validated.policy.details,
                "catalog": catalog,
                "schema": schema,
                "include_views": include_views,
                "table_count": len(result),
            },
            duration_ms=_elapsed_ms(start),
        )
        return _jsonify(result)

    @server.tool(name="describe_table", description="Describe a single table or view.")
    def describe_table(
        connection_name: str,
        schema: str,
        table: str,
        catalog: str | None = None,
        permission_mode: PermissionMode | None = None,
    ) -> dict[str, Any]:
        start = monotonic()
        try:
            validated = validation_service.validate_metadata_request(
                connection_name,
                "describe_table",
                permission_mode=permission_mode,
            )
            result = metadata_service.describe_table(connection_name, catalog=catalog, schema=schema, table=table)
        except Exception as exc:
            error = _normalize_error(exc, message=f"Failed to describe table {table!r} for connection {connection_name!r}.", details={"connection_name": connection_name, "schema": schema, "table": table})
            audit_service.failure(
                "describe_table",
                resource=f"{connection_name}:{schema}.{table}",
                details=error.to_dict(),
                duration_ms=_elapsed_ms(start),
            )
            raise error from exc

        audit_service.success(
            "describe_table",
            resource=f"{connection_name}:{schema}.{table}",
            details={"policy": validated.policy.details},
            duration_ms=_elapsed_ms(start),
        )
        return _jsonify(result)

    @server.tool(name="run_query", description="Validate and execute a SQL query.")
    def run_query(
        connection_name: str,
        sql: str,
        params: dict[str, Any] | None = None,
        permission_mode: PermissionMode | None = None,
        timeout_ms: int | None = None,
        max_rows: int | None = None,
        max_bytes: int | None = None,
        dialect: str | None = None,
    ) -> dict[str, Any]:
        start = monotonic()
        try:
            normalized = query_service.run_query(
                connection_name,
                sql,
                params=params or {},
                permission_mode=permission_mode,
                timeout_ms=timeout_ms,
                max_rows=max_rows,
                max_bytes=max_bytes,
                dialect=dialect,
            )
        except Exception as exc:
            error = _normalize_error(exc, message=f"Failed to run query for connection {connection_name!r}.", details={"connection_name": connection_name})
            audit_service.failure(
                "run_query",
                resource=connection_name,
                details=error.to_dict(),
                duration_ms=_elapsed_ms(start),
            )
            raise error from exc

        return _jsonify(normalized)

    @server.tool(name="explain_query", description="Validate and explain a SQL query without executing it.")
    def explain_query(
        connection_name: str,
        sql: str,
        params: dict[str, Any] | None = None,
        permission_mode: PermissionMode | None = None,
        timeout_ms: int | None = None,
        max_rows: int | None = None,
        max_bytes: int | None = None,
        dialect: str | None = None,
    ) -> dict[str, Any]:
        start = monotonic()
        try:
            normalized = query_service.explain_query(
                connection_name,
                sql,
                params=params or {},
                permission_mode=permission_mode,
                timeout_ms=timeout_ms,
                max_rows=max_rows,
                max_bytes=max_bytes,
                dialect=dialect,
            )
        except Exception as exc:
            error = _normalize_error(exc, message=f"Failed to explain query for connection {connection_name!r}.", details={"connection_name": connection_name})
            audit_service.failure(
                "explain_query",
                resource=connection_name,
                details=error.to_dict(),
                duration_ms=_elapsed_ms(start),
            )
            raise error from exc

        return _jsonify(normalized)



def _register_resources(server: FastMCP, *, registry: ConnectionRegistry, config: Config) -> None:
    @server.resource("dbmcp://config", name="server-config", description="Summarize the loaded server configuration.")
    def server_config() -> dict[str, Any]:
        return {
            "server": _jsonify(config.server),
            "defaults": _jsonify(config.defaults),
            "connection_names": registry.connection_names(),
            "connections": _jsonify(registry.list_connections()),
        }

    @server.resource("dbmcp://connections", name="connections", description="List all configured database connections.")
    def connections() -> list[dict[str, Any]]:
        return _jsonify(registry.list_connections())

    @server.resource(
        "dbmcp://connections/{connection_name}",
        name="connection",
        description="Return a safe summary for a single configured connection.",
    )
    def connection(connection_name: str) -> dict[str, Any]:
        return _jsonify(registry.describe_connection(connection_name))


def _register_prompts(
    server: FastMCP,
    *,
    registry: ConnectionRegistry,
    validation_service: ValidationService,
) -> None:
    @server.prompt(name="review_query", description="Build a prompt for safely reviewing a SQL statement.")
    def review_query(
        connection_name: str,
        sql: str,
        permission_mode: PermissionMode | None = None,
    ) -> list[dict[str, str]]:
        connection = registry.describe_connection(connection_name)
        policy = {
            "default_permission_mode": validation_service.config.defaults.permission_mode,
            "requested_permission_mode": permission_mode,
        }
        return [
            {
                "role": "system",
                "content": "You are helping review a SQL statement for a database MCP server. Focus on safety, clarity, and expected impact.",
            },
            {
                "role": "user",
                "content": (
                    f"Connection summary:\n{_stable_text(connection)}\n\n"
                    f"Policy context:\n{_stable_text(policy)}\n\n"
                    f"SQL:\n{sql.strip()}"
                ),
            },
        ]

    @server.prompt(name="inspect_connection", description="Build a prompt for inspecting a database connection.")
    def inspect_connection(connection_name: str) -> list[dict[str, str]]:
        connection = registry.describe_connection(connection_name)
        return [
            {
                "role": "system",
                "content": "You are helping a user understand a configured database connection.",
            },
            {
                "role": "user",
                "content": f"Connection summary:\n{_stable_text(connection)}",
            },
        ]


def _normalize_error(exc: BaseException, *, message: str, details: Mapping[str, Any] | None = None) -> DbMcpError:
    if isinstance(exc, DbMcpError):
        if message == exc.message and not details:
            return exc
        merged_details = dict(exc.details)
        if details:
            merged_details.update(details)
        return normalize_exception(exc, message=message, details=merged_details)
    return normalize_exception(exc, message=message, details=details)


def _jsonify(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return _jsonify(value.model_dump(mode="python", by_alias=True, exclude_none=True))
    if isinstance(value, Mapping):
        return {str(key): _jsonify(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonify(item) for item in value]
    if isinstance(value, set):
        return [_jsonify(item) for item in value]
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if hasattr(value, "model_dump"):
        dumped = value.model_dump()
        return _jsonify(dumped)
    if hasattr(value, "__dict__") and not isinstance(value, type):
        return _jsonify({key: item for key, item in vars(value).items() if not key.startswith("_")})
    return value


def _stable_text(value: Any) -> str:
    from json import dumps

    return dumps(_jsonify(value), indent=2, sort_keys=True, ensure_ascii=False)


def _elapsed_ms(start: float) -> float:
    return round((monotonic() - start) * 1000.0, 3)


__all__ = [
    "ServerBundle",
    "build_server_bundle",
    "create_server",
    "load_server_config",
    "run_server",
]
