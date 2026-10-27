"""MCP server: every operation in OPS is a tool; the arena report is a resource."""

from __future__ import annotations

from fastmcp import FastMCP

from agents_arena_mcp import __version__
from agents_arena_mcp.arena import OPS, context
from agents_arena_mcp.search import SEARCH_OPS

INSTRUCTIONS = """Agents Arena runs competing implementations of one task in isolated git worktrees and picks a
winner on evidence. Workflow: arena_open -> implement in each workspace (yourself, or arena_run with an agent
runner) -> arena_check -> arena_judge -> arena_promote -> arena_close. Long runs: pass wait=false and poll
arena_status. Optional: arena_open(explore=true) + arena_fork, and arena_refine for unresolved decisions."""


def make_mcp() -> FastMCP:
    mcp = FastMCP(name="Agents Arena", instructions=INSTRUCTIONS, version=__version__)
    for op in (*OPS, *SEARCH_OPS):
        mcp.tool(op)

    @mcp.resource("arena://{arena_id}/report", mime_type="text/markdown")
    def arena_report(arena_id: str) -> str:
        """The arena's markdown report (written by arena_judge)."""
        store, _ = context()
        path = store.arena_dir(arena_id) / "report.md"
        return path.read_text(encoding="utf-8") if path.exists() else f"No report yet for {arena_id}; run arena_judge."

    return mcp


def main() -> None:
    make_mcp().run()


if __name__ == "__main__":
    main()
