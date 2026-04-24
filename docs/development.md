# Development Setup

## Bootstrap the project

```bash
uv sync
```

This installs the runtime and development dependencies defined in `pyproject.toml`.

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
