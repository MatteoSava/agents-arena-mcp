"""MCP server: the five ops as tools, plus the arena://guide resource."""

from __future__ import annotations

from fastmcp import FastMCP

from agents_arena_mcp import __version__
from agents_arena_mcp.arena import OPS
from agents_arena_mcp.config_data import data_text

INSTRUCTIONS = (
    "Agents Arena runs experiments on coding agents (harness, model, skill or strategy A/B with repeats) and "
    "returns a scorecard. Start with arena_plan. Read arena://guide for the full workflow."
)


def make_mcp() -> FastMCP:
    mcp = FastMCP(name="Agents Arena", instructions=INSTRUCTIONS, version=__version__)
    for op in OPS:
        mcp.tool(op)

    @mcp.resource("arena://guide", mime_type="text/markdown")
    def guide() -> str:
        """How to plan, run and read arenas."""
        return data_text("GUIDE.md")

    return mcp


def main() -> None:
    make_mcp().run()
