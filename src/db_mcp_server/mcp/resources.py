from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

RESOURCE_URI = "dbmcp://server-info"
RESOURCE_NAME = "server-info"
RESOURCE_TITLE = "Database MCP Server Info"
RESOURCE_DESCRIPTION = "A minimal resource describing the MCP surface exposed by db-mcp-server."


def register_resources(server: FastMCP[Any]) -> FastMCP[Any]:
    """Register the small placeholder resource set used by the MCP server."""

    @server.resource(
        RESOURCE_URI,
        name=RESOURCE_NAME,
        title=RESOURCE_TITLE,
        description=RESOURCE_DESCRIPTION,
        mime_type="text/markdown",
    )
    def server_info() -> str:
        return (
            "# db-mcp-server\n\n"
            "This MCP server exposes database connection discovery, metadata inspection, and query execution tools.\n"
            "Use the tool surface for live database interaction.\n"
        )

    return server


__all__ = ["RESOURCE_DESCRIPTION", "RESOURCE_NAME", "RESOURCE_TITLE", "RESOURCE_URI", "register_resources"]
