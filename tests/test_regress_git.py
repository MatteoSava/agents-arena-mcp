from __future__ import annotations

from pathlib import Path

import pytest
from conftest import git

from agents_arena_mcp.core.arena import ArenaEngine


def open_one(engine: ArenaEngine, name: str = "a") -> tuple[str, Path]:
    arena = engine.open("task", variants=[name])
    return arena["arena_id"], Path(arena["variants"][name]["worktree"])


def test_untracked_files_are_included_in_variant_diff(repo: Path):
    engine = ArenaEngine(repo)
    aid, wt = open_one(engine)
    (wt / "new_module.py").write_text("X = 1\n")

    rec = engine.record_variant(aid, "a")

    assert "new_module.py" in rec["diff"]["changed_files"]
    assert "new_module.py" in rec["diff"]["patch"]


def test_include_current_diff_carries_uncommitted_changes(repo: Path):
    (repo / "app.py").write_text("def value():\n    return 42\n")
    (repo / "wip.py").write_text("WIP = True\n")
    engine = ArenaEngine(repo)

    aid, wt = engine.open("task", variants=["a"], include_current_diff=True)["arena_id"], None
    wt = Path(engine.load_arena(aid)["variants"]["a"]["worktree"])

    assert (wt / "app.py").read_text() == "def value():\n    return 42\n"
    assert (wt / "wip.py").exists()
    # The user's own WIP must not be credited to the variant.
    assert engine.record_variant(aid, "a")["diff"]["files_changed"] == 0


def test_cleanup_removes_branches_and_worktree_dirs(repo: Path):
    engine = ArenaEngine(repo)
    aid, wt = open_one(engine)

    engine.cleanup(aid)

    assert not wt.exists()
    assert not wt.parent.exists()
    assert git(repo, "branch", "--list", "arena/*").strip() == ""


def test_open_rolls_back_created_worktrees_on_failure(repo: Path, monkeypatch):
    import agents_arena_mcp.core.arena as arena_mod

    real = arena_mod.create_worktree
    calls = {"n": 0}

    def flaky(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 2:
            raise arena_mod.ArenaError("boom")
        return real(*args, **kwargs)

    monkeypatch.setattr(arena_mod, "create_worktree", flaky)
    with pytest.raises(arena_mod.ArenaError):
        ArenaEngine(repo).open("task", variants=["a", "b"])

    assert git(repo, "branch", "--list", "arena/*").strip() == ""
    assert len(git(repo, "worktree", "list").splitlines()) == 1


def test_promote_branch_does_not_switch_user_checkout(repo: Path):
    engine = ArenaEngine(repo)
    aid, wt = open_one(engine)
    (wt / "app.py").write_text("def value():\n    return 2\n")
    engine.record_variant(aid, "a")

    result = engine.promote_winner(aid, "a", mode="branch")

    assert git(repo, "rev-parse", "--abbrev-ref", "HEAD").strip() == "main"
    assert (repo / "app.py").read_text() == "def value():\n    return 1\n"
    assert git(repo, "show", f"{result['branch']}:app.py") == "def value():\n    return 2\n"


def test_non_utf8_file_does_not_crash_diff(repo: Path):
    engine = ArenaEngine(repo)
    aid, wt = open_one(engine)
    (wt / "app.py").write_bytes(b"# caf\xe9\ndef value():\n    return 2\n")

    rec = engine.record_variant(aid, "a")

    assert rec["diff"]["files_changed"] == 1
