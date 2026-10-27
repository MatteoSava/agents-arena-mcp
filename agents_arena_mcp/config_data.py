"""Access to packaged files under agents_arena_mcp/data/."""

from __future__ import annotations

from importlib import resources


def data_text(name: str) -> str:
    return resources.files("agents_arena_mcp.data").joinpath(name).read_text(encoding="utf-8")
