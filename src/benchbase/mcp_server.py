"""MCP server mounted on the BenchBase FastAPI app."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi_mcp import FastApiMCP

# SSE endpoints are not callable as single JSON MCP tools.
MCP_EXCLUDED_OPERATIONS = [
    "stream_run_log",
    "arena_stream",
]


def setup_mcp(app: FastAPI) -> FastApiMCP:
    """Register Streamable HTTP MCP at /mcp. Call after all API routes are registered."""
    mcp = FastApiMCP(
        app,
        name="BenchBase",
        description=(
            "Local LLM benchmark dashboard: run speed, coding, tool-use, and reasoning "
            "benchmarks; compare models; manage LiteLLM-connected models and settings."
        ),
        exclude_operations=MCP_EXCLUDED_OPERATIONS,
    )
    mcp.mount_http(mount_path="/mcp")
    return mcp
