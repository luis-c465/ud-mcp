# Development Setup

This page covers the quickest path from a fresh clone to a working local environment.

## Prerequisites

- Python 3.12 or newer
- `uv`

## Bootstrap the project

Runtime dependencies only:

```bash
uv sync
```

Runtime plus development extras:

```bash
uv sync --extra dev
```

The `dev` extra currently installs `pytest`, `pytest-cov`, `ruff`, and `mypy`.

## Configuration file expectations

The server is started with `--config PATH_TO_YAML`. The config loader expects:

- valid YAML
- a top-level mapping object
- backend connections defined under `connections`
- secrets referenced by environment variable name, not stored directly in the file

A small local config can look like this:

```yaml
server:
  name: db-mcp-server
  transport: stdio
  log_level: info

defaults:
  permission_mode: readonly
  timeout_ms: 30000
  max_rows: 500
  max_bytes: 1048576
  allow_multiple_statements: false
  block_destructive_sql: true

connections:
  app_sqlserver:
    type: sqlserver
    dsn_env: APP_SQLSERVER_DSN

  warehouse_sf:
    type: snowflake
    account_env: SNOWFLAKE_ACCOUNT
    user_env: SNOWFLAKE_USER
    password_env: SNOWFLAKE_PASSWORD
    warehouse_env: SNOWFLAKE_WAREHOUSE
    role_env: SNOWFLAKE_ROLE

  dbx_prod:
    type: databricks
    server_hostname_env: DATABRICKS_SERVER_HOSTNAME
    http_path_env: DATABRICKS_HTTP_PATH
    token_env: DATABRICKS_TOKEN
```

Backend environment variables by connection type:

- SQL Server: `dsn_env` is required. It should point at a shell environment variable containing the DSN or ODBC connect string.
- Snowflake: `account_env`, `user_env`, `password_env`, and `warehouse_env` are required; `role_env` is optional. `database` and `schema` may be set directly in YAML.
- Databricks: `server_hostname_env`, `http_path_env`, and `token_env` are required. `catalog` and `schema` may be set directly in YAML.

## Transports

The current codebase supports these server transports:

- `stdio` — default transport for local MCP client workflows
- `streamable-http` — HTTP transport for browser, container, or networked use

The configuration model also includes `sse`, but the command-line entry point currently exposes `stdio` and `streamable-http`.

## Run the server locally

```bash
uv run python -m db_mcp_server.main --config ./config.yaml
```

To run over HTTP instead of stdio:

```bash
uv run python -m db_mcp_server.main --config ./config.yaml --transport streamable-http --host 127.0.0.1 --port 8000
```

Before starting the server, export the environment variables referenced by the config file, for example:

```bash
export APP_SQLSERVER_DSN='DSN=sqlserver-local;Trusted_Connection=yes'
export SNOWFLAKE_ACCOUNT='my-account'
export SNOWFLAKE_USER='my-user'
export SNOWFLAKE_PASSWORD='my-password'
export SNOWFLAKE_WAREHOUSE='my-warehouse'
export DATABRICKS_SERVER_HOSTNAME='adb-1234567890123456.7.azuredatabricks.net'
export DATABRICKS_HTTP_PATH='/sql/1.0/warehouses/abcd1234'
export DATABRICKS_TOKEN='dapi...'
```

## Common commands

```bash
uv run pytest
uv run ruff check .
uv run mypy src
```

## Repository conventions

- Keep source files under `src/db_mcp_server/`.
- Prefer explicit, backend-neutral model names such as `catalog`, `schema`, `name`, and `object_type`.
- Treat secrets as sensitive and avoid logging raw connection strings, tokens, or passwords.
- Default to read-only behavior unless a task explicitly calls for write support.

## Current bootstrap status

The project is still in early scaffolding. Documentation and package layout are present, but most runtime features are intentionally not implemented yet.
