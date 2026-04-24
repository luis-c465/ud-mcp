"""Typed configuration models for the database MCP server.

These models intentionally mirror the YAML structure described in PLAN.md.
The secret-bearing fields are expressed as environment variable names so that
secret resolution can happen in a separate layer.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


LogLevel = Literal["debug", "info", "warning", "error", "critical"]
Transport = Literal["stdio", "streamable-http", "sse"]
PermissionMode = Literal["readonly", "full"]


class ServerConfig(BaseModel):
    """Configuration for the MCP server process itself."""

    model_config = ConfigDict(extra="forbid")

    name: str = "db-mcp-server"
    transport: Transport = "stdio"
    log_level: LogLevel = "info"


class DefaultsConfig(BaseModel):
    """Default policy and query execution settings."""

    model_config = ConfigDict(extra="forbid")

    permission_mode: PermissionMode = "readonly"
    timeout_ms: int = 30_000
    max_rows: int = 500
    max_bytes: int = 1_048_576
    allow_multiple_statements: bool = False
    block_destructive_sql: bool = True


class ConnectionConfigBase(BaseModel):
    """Backend-agnostic connection settings."""

    model_config = ConfigDict(extra="forbid")

    type: str
    description: str | None = None
    read_only: bool = True
    allow_full_permissions: bool = False


class SqlServerConnectionConfig(ConnectionConfigBase):
    """Connection settings for SQL Server."""

    type: Literal["sqlserver"] = "sqlserver"
    driver: str = "pyodbc"
    dsn_env: str


class SnowflakeConnectionConfig(ConnectionConfigBase):
    """Connection settings for Snowflake."""

    type: Literal["snowflake"] = "snowflake"
    account_env: str
    user_env: str
    password_env: str
    warehouse_env: str
    database: str | None = None
    schema_: str | None = Field(default=None, alias="schema")
    role_env: str | None = None


class DatabricksConnectionConfig(ConnectionConfigBase):
    """Connection settings for Databricks SQL."""

    type: Literal["databricks"] = "databricks"
    server_hostname_env: str
    http_path_env: str
    token_env: str
    catalog: str | None = None
    schema_: str | None = Field(default=None, alias="schema")


ConnectionConfig = Annotated[
    SqlServerConnectionConfig | SnowflakeConnectionConfig | DatabricksConnectionConfig,
    Field(discriminator="type"),
]


class DatabaseConfig(BaseModel):
    """Top-level application configuration loaded from YAML."""

    model_config = ConfigDict(extra="forbid")

    server: ServerConfig = Field(default_factory=ServerConfig)
    defaults: DefaultsConfig = Field(default_factory=DefaultsConfig)
    connections: dict[str, ConnectionConfig] = Field(default_factory=dict)


Config = DatabaseConfig


__all__ = [
    "Config",
    "ConnectionConfig",
    "ConnectionConfigBase",
    "DatabaseConfig",
    "DatabricksConnectionConfig",
    "DefaultsConfig",
    "PermissionMode",
    "ServerConfig",
    "SnowflakeConnectionConfig",
    "SqlServerConnectionConfig",
    "Transport",
    "LogLevel",
]
