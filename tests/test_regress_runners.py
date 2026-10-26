from __future__ import annotations

from pathlib import Path

from agents_arena_mcp.core.arena import ArenaEngine


def open_one(engine: ArenaEngine, name: str = "a") -> tuple[str, Path]:
    arena = engine.open("task", variants=[name])
    return arena["arena_id"], Path(arena["variants"][name]["worktree"])


def test_opencode_runner_does_not_pass_unknown_dir_flag(repo: Path, monkeypatch):
    from agents_arena_mcp.runners import opencode_run
    from agents_arena_mcp.runners.base import RunnerRequest

    seen: dict = {}

    def fake_capture(cmd, cwd, run_dir, timeout_sec, env=None):
        seen["cmd"], seen["cwd"] = cmd, cwd
        return {"status": "completed", "exit_code": 0, "timing": {}, "outputs": {}, "tokens": {}}

    monkeypatch.setattr(opencode_run, "find_executable", lambda name: "/usr/bin/opencode")
    monkeypatch.setattr(opencode_run, "run_subprocess_capture", fake_capture)
    req = RunnerRequest(repo_root=repo, worktree=repo, arena_id="x", variant="a", prompt="hi")
    opencode_run.OpenCodeRunRunner().run(req)

    assert "--dir" not in seen["cmd"]
    assert seen["cwd"] == repo
