# Universal Database MCP Server

Universal Database MCP Server is a Python 3.12+ project scaffold for a read-only, multi-backend MCP server targeting SQL Server, Snowflake, and Databricks.

## Current status

The repository is in early bootstrap. Core packages, dependency metadata, and the initial source tree are in place. Runtime behavior and backend adapters are still under active development.

## What this repository will provide

- an MCP surface built with the official Python SDK
- a service layer for query, metadata, validation, and audit flows
- adapter and driver layers for backend-specific integration
- safety-first defaults with read-only operation as the baseline

## Local development

### Prerequisites

- Python 3.12 or newer
- `uv`

### Bootstrap

```bash
uv sync
```

### Useful commands

```bash
# run tests
uv run pytest

# run linting
uv run ruff check .

# type checking
uv run mypy src
```

## Project layout

- `src/db_mcp_server/` — package source
- `src/db_mcp_server/config/` — configuration models and loading
- `src/db_mcp_server/safety/` — SQL policy and validation helpers
- `src/db_mcp_server/services/` — service layer implementations
- `src/db_mcp_server/adapters/` — backend adapter abstractions and implementations
- `src/db_mcp_server/drivers/` — backend driver setup helpers
- `src/db_mcp_server/mcp/` — MCP schemas, tools, resources, and prompts
- `docs/` — developer documentation

## Developer docs

See [docs/README.md](docs/README.md) for a short guide to the repository and [docs/development.md](docs/development.md) for day-to-day setup notes.
