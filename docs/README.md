# Developer Documentation

This directory contains the working notes for the Universal Database MCP Server.

## Documents

- [Development setup](development.md) — bootstrap, config expectations, transports, and day-to-day commands

## Quick links

- [Project README](../README.md)
- [Development setup](development.md)

## Notes

- Use `uv sync` for runtime dependencies and `uv sync --extra dev` when you want the local test/lint/typecheck toolchain.
- Configuration is YAML-based, with secrets supplied through environment variables referenced from the config file.
- The default security posture is read-only.
- The current CLI entrypoint supports `stdio` and `streamable-http` transports; `stdio` is the default.
