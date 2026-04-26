# Universal Database MCP Server

Universal Database MCP Server is a Python 3.12+ read-only MCP server scaffold for SQL Server, Snowflake, and Databricks.

## Getting started

### Prerequisites

- Python 3.12 or newer
- [`uv`](https://docs.astral.sh/uv/)

### Install dependencies

Runtime dependencies only:

```bash
uv sync
```

Install runtime plus development extras:

```bash
uv sync --extra dev
```

The `dev` extra currently adds `pytest`, `pytest-cov`, `ruff`, and `mypy`.

### Create a config file

The server is started from a YAML config file passed with `--config`. The file must contain a top-level mapping and should define `server`, `defaults`, and `connections` sections.

Secrets are not stored directly in YAML. Instead, each backend connection points to environment variable names that are resolved at runtime.

Minimal example:

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

  dbx_prod:
    type: databricks
    server_hostname_env: DATABRICKS_SERVER_HOSTNAME
    http_path_env: DATABRICKS_HTTP_PATH
    token_env: DATABRICKS_TOKEN
```

Backend-specific required environment variables:

- SQL Server: `dsn_env`
- Snowflake: `account_env`, `user_env`, `password_env`, `warehouse_env` (`role_env` is optional)
- Databricks: `server_hostname_env`, `http_path_env`, `token_env`

### Transports

The current CLI entrypoint supports these transports:

- `stdio` — default for local MCP client workflows
- `streamable-http` — HTTP transport for local or containerized use

The config model also includes `sse` in the transport enum, but the CLI currently exposes `stdio` and `streamable-http`.

### Run the server

```bash
uv run python -m db_mcp_server.main --config ./config.yaml
```

To choose the HTTP transport:

```bash
uv run python -m db_mcp_server.main --config ./config.yaml --transport streamable-http --host 127.0.0.1 --port 8000
```

### Common commands

```bash
uv run pytest
uv run ruff check .
uv run mypy src
```

## Project layout

- `src/db_mcp_server/` — package source
- `src/db_mcp_server/config/` — configuration models, loading, and secret resolution
- `src/db_mcp_server/safety/` — SQL policy and validation helpers
- `src/db_mcp_server/services/` — service layer implementations
- `src/db_mcp_server/adapters/` — backend adapter abstractions and implementations
- `src/db_mcp_server/drivers/` — backend driver setup helpers
- `src/db_mcp_server/mcp/` — MCP schemas, tools, resources, and prompts
- `docs/` — developer documentation

## Developer docs

See [docs/README.md](docs/README.md) for the documentation index and [docs/development.md](docs/development.md) for step-by-step local setup notes.
