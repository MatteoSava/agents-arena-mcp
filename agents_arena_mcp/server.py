"""MCP server: the five ops as tools, plus the arena://guide resource."""

from __future__ import annotations

import os
import signal

from fastmcp import FastMCP

from agents_arena_mcp import __version__, jobs
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


def _on_sigterm(signum: int, frame: object) -> None:
    jobs.stop_all()  # background arenas record the failure and remove their worktrees
    # A SystemExit raised here would be swallowed by the event loop, so exit the process directly.
    os._exit(128 + signum)


def main() -> None:
    signal.signal(signal.SIGTERM, _on_sigterm)
    make_mcp().run()
    jobs.stop_all()  # stdin closed (the client quit): stop background arenas before their threads die


if __name__ == "__main__":
    main()
