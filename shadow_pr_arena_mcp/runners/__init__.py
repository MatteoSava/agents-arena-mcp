from __future__ import annotations

from shadow_pr_arena_mcp.runners.codex_exec import CodexExecRunner
from shadow_pr_arena_mcp.runners.manual import ManualRunner
from shadow_pr_arena_mcp.runners.opencode_run import OpenCodeRunRunner


def get_runner(name: str):
    if name == "codex":
        return CodexExecRunner()
    if name == "opencode":
        return OpenCodeRunRunner()
    if name == "manual":
        return ManualRunner()
    raise ValueError(f"Unknown runner: {name}")
