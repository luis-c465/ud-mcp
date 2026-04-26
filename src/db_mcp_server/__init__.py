"""db-mcp-server public package API."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

from .main import build_parser, main
from .server import ServerBundle, build_server_bundle, create_server, load_server_config, run_server

try:
    __version__ = version("db-mcp-server")
except PackageNotFoundError:  # pragma: no cover - only applies outside an installed build
    __version__ = "0.0.0"

__all__ = [
    "ServerBundle",
    "__version__",
    "build_parser",
    "build_server_bundle",
    "create_server",
    "load_server_config",
    "main",
    "run_server",
]
