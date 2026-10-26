from __future__ import annotations

from pathlib import Path

from agents_arena_mcp.core.arena import ArenaEngine


def open_one(engine: ArenaEngine, name: str = "a") -> tuple[str, Path]:
    arena = engine.open("task", variants=[name])
    return arena["arena_id"], Path(arena["variants"][name]["worktree"])


def test_missing_check_executable_is_recorded_not_raised(repo: Path):
    engine = ArenaEngine(repo)
    aid, _ = open_one(engine)

    result = engine.run_checks(aid, "a", commands=["definitely-not-a-real-tool-xyz --flag"])

    assert result["passed"] is False
    assert result["commands"][0]["status"] == "error"


def test_check_timeout_is_recorded_not_raised(repo: Path):
    engine = ArenaEngine(repo)
    aid, _ = open_one(engine)

    result = engine.run_checks(aid, "a", commands=["sleep 5"], timeout_sec=1)

    assert result["commands"][0]["status"] == "timeout"
