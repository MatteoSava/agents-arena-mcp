from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from shadow_pr_arena_mcp.core.arena import ArenaEngine


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=repo, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
    return result.stdout


@pytest.fixture
def repo(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init")
    git(repo, "config", "user.email", "arena@example.com")
    git(repo, "config", "user.name", "Arena Test")
    (repo / "app.py").write_text("def value():\n    return 1\n", encoding="utf-8")
    (repo / "tests").mkdir()
    (repo / "tests" / "test_app.py").write_text("from app import value\n\ndef test_value():\n    assert value() == 1\n", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "initial")
    return repo


def test_arena_open_record_judge_scoreboard_cleanup(repo: Path):
    engine = ArenaEngine(repo)
    arena = engine.open("Compare simple value changes", variants=["minimal_patch", "test_first"])
    aid = arena["arena_id"]

    # Modify variant A without adding tests.
    va = Path(arena["variants"]["minimal_patch"]["worktree"])
    (va / "app.py").write_text("def value():\n    return 2\n", encoding="utf-8")
    rec_a = engine.record_variant(aid, "minimal_patch")
    assert rec_a["diff"]["files_changed"] == 1

    # Modify variant B with test evidence and matching app change.
    vb = Path(arena["variants"]["test_first"]["worktree"])
    (vb / "app.py").write_text("def value():\n    return 2\n", encoding="utf-8")
    (vb / "tests" / "test_app.py").write_text("from app import value\n\ndef test_value():\n    assert value() == 2\n", encoding="utf-8")
    rec_b = engine.record_variant(aid, "test_first")
    assert rec_b["diff"]["files_changed"] == 2

    match = engine.pairwise_judge(aid, "minimal_patch", "test_first", judge_runner="heuristic")
    assert match["winner"] in {"minimal_patch", "test_first", "draw"}
    sb = engine.scoreboard(aid)
    assert "# Shadow PR Arena Scoreboard" in sb["markdown"]
    assert "Pairwise matrix" in sb["markdown"]
    patch = engine.promote_winner(aid, mode="patch")
    assert Path(patch["patch_path"]).exists()
    cleanup = engine.cleanup(aid)
    assert cleanup["arena_id"] == aid


def test_manual_runner_records_metadata(repo: Path):
    engine = ArenaEngine(repo)
    arena = engine.open("Manual run", variants=["minimal_patch"])
    md = engine.run_variant_agent(arena["arena_id"], "minimal_patch", runner="manual")
    assert md["runner"] == "manual"
    assert md["status"] == "manual_pending"
    assert Path(md["prompt"]["prompt_path"]).exists()
