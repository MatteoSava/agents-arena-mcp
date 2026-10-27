"""Phase C: checkpoints, forks, explore-then-fork, refinement depth cap, distinguishing tests."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from conftest import write_config

from agents_arena_mcp import arena as ops
from agents_arena_mcp.errors import ArenaError
from agents_arena_mcp.search import arena_fork, arena_refine
from agents_arena_mcp.store import Store


def ws(name: str) -> Path:
    return Path(ops.arena_status()["variants"][name]["workspace"])


def tree_bytes(root: Path) -> dict[str, bytes]:
    return {
        str(p.relative_to(root)): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file() and ".git" not in p.parts
    }


def test_checkpoints_accumulate_and_unchanged_trees_reuse_the_last(repo: Path):
    ops.arena_open("task", variants=["a"])
    (ws("a") / "app.py").write_text("v = 1\n")
    ops.arena_check()
    ops.arena_check()  # no change -> same checkpoint
    (ws("a") / "app.py").write_text("v = 2\n")

    status = ops.arena_check()

    assert status["variants"]["a"]["checkpoints"] == [1, 2]


def test_fork_is_byte_identical_including_ignored_dirs(repo: Path):
    (repo / ".gitignore").write_text(".venv/\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "ignore venv"], cwd=repo, check=True)
    ops.arena_open("task", variants=["explore"])
    (ws("explore") / "notes.md").write_text("findings\n")
    (ws("explore") / ".venv" / "lib").mkdir(parents=True)
    (ws("explore") / ".venv" / "lib" / "big.bin").write_bytes(b"\0" * 4096)
    ops.arena_check()

    arena_fork("explore", names=["child"])

    assert tree_bytes(ws("child")) == tree_bytes(ws("explore"))
    assert ops.arena_status()["variants"]["child"]["parent"] == "explore@1"


def test_explore_then_fork_uses_pending_strategies(repo: Path):
    opened = ops.arena_open("task", variants=["minimal_patch", "test_first"], explore=True)
    assert list(opened["variants"]) == ["explore"]
    (ws("explore") / "ARENA_NOTES.md").write_text("plan\n")
    ops.arena_check()

    forked = arena_fork("explore")

    assert set(forked["variants"]) == {"explore", "minimal_patch", "test_first"}
    assert Store(repo).load().pending_strategies == []
    assert (ws("test_first") / "ARENA_NOTES.md").read_text() == "plan\n"


def test_fork_requires_a_checkpoint(repo: Path):
    ops.arena_open("task", variants=["a"])
    with pytest.raises(ArenaError, match="no checkpoint"):
        arena_fork("a", names=["b"])


def test_refine_forks_contenders_with_critique_and_caps_depth(repo: Path, fakes, monkeypatch):
    monkeypatch.setenv("FAKE_JUDGE_MODE", "always_a")
    write_config(repo, fakes, extra="[judge]\nrunner = 'fake'\nmax_refine_depth = 1")
    ops.arena_open("task", variants=["x", "y"])
    (ws("x") / "app.py").write_text("X = 1\n")
    (ws("y") / "app.py").write_text("Y = 2\n")
    ops.arena_check()
    assert ops.arena_judge(wait=True)["decision"]["status"] == "needs_human"

    refined = arena_refine()

    assert {"x-r1", "y-r1"} <= set(refined["variants"])
    extra = Store(repo).arena_dir(refined["arena_id"]) / "variants" / "x-r1" / "extra-brief.md"
    assert "A looks better" in extra.read_text()
    assert (ws("x-r1") / "app.py").read_text() == "X = 1\n"
    ops.arena_check(variants=["x-r1"])
    with pytest.raises(ArenaError, match="max_refine_depth"):
        arena_refine(variants=["x-r1"])


def test_distinguishing_test_breaks_a_split_pair(repo: Path, fakes, monkeypatch):
    monkeypatch.setenv("FAKE_JUDGE_MODE", "evidence")
    write_config(repo, fakes, extra="[judge]\nrunner = 'fake'\ndistinguish = true")
    ops.arena_open("task", variants=["good", "bad"])
    (ws("good") / "probe.txt").write_text("probe-good\n")
    (ws("bad") / "probe.txt").write_text("probe-bad\nmore\n")
    ops.arena_check()

    decision = ops.arena_judge(wait=True)["decision"]

    assert decision["winner"] == "good" and decision["tie_break"] is None
    evidence = [m for m in Store(repo).load().matches.values() if m.evidence]
    assert len(evidence) == 2 and "cat probe.txt" in evidence[0].evidence


def test_agentic_final_round_resolves_top_two(repo: Path, fakes, monkeypatch):
    monkeypatch.setenv("FAKE_JUDGE_MODE", "always_a")  # plain rounds split -> unresolved
    write_config(repo, fakes, extra="[judge]\nrunner = 'fake'\nagentic_final = 'fake'")
    ops.arena_open("task", variants=["x", "y"])
    (ws("x") / "app.py").write_text("X = 1\n")
    (ws("y") / "app.py").write_text("Y = 2\nYY = 3\n")
    (ws("y") / "WINNER").write_text("")
    ops.arena_check()

    decision = ops.arena_judge(wait=True)["decision"]

    assert decision["winner"] == "y" and decision["tie_break"] is None
    assert sum(1 for m in Store(repo).load().matches.values() if m.evidence) == 2
