from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

PROMPT_NAME = "query-guidance"
PROMPT_TITLE = "Query Guidance"
PROMPT_DESCRIPTION = "A small placeholder prompt that reminds clients to stay read-only by default."


def register_prompts(server: FastMCP[Any]) -> FastMCP[Any]:
    """Register the lightweight prompt scaffolding used by the MCP server."""

    @server.prompt(name=PROMPT_NAME, title=PROMPT_TITLE, description=PROMPT_DESCRIPTION)
    def query_guidance() -> str:
        return (
            "You are helping a user work with a database through MCP. "
            "Prefer read-only SQL unless the caller explicitly requests otherwise, "
            "and ask for the target connection when needed."
        )

    return server


__all__ = ["PROMPT_DESCRIPTION", "PROMPT_NAME", "PROMPT_TITLE", "register_prompts"]
