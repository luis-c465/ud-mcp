"""Command-line entry point for db-mcp-server."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from db_mcp_server.config.loader import ConfigError, load_config
from db_mcp_server.server import run_server


def build_parser() -> argparse.ArgumentParser:
    """Create the CLI argument parser."""

    parser = argparse.ArgumentParser(prog="db-mcp-server")
    parser.add_argument(
        "--config",
        type=Path,
        required=True,
        help="Path to the YAML configuration file.",
    )
    parser.add_argument(
        "--transport",
        choices=("stdio", "streamable-http"),
        default=None,
        help="Transport to use when launching the server.",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host to bind when using streamable HTTP transport.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port to bind when using streamable HTTP transport.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and start the configured MCP server."""

    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    try:
        config = load_config(args.config)
    except ConfigError as exc:
        parser.exit(status=2, message=f"{exc}\n")

    run_server(
        config,
        transport=args.transport or config.server.transport,
        host=args.host,
        port=args.port,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))


__all__ = ["build_parser", "main"]
