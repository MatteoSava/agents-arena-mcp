"""Regression tests for the v0.1 review bugs, ported to the v0.2 API. Each failed on v0.1."""

from __future__ import annotations

import re
import threading
from pathlib import Path

import pytest
from conftest import git, write_config

from agents_arena_mcp import arena as ops
from agents_arena_mcp.config import load_config
from agents_arena_mcp.errors import ArenaError
from agents_arena_mcp.store import Store


def workspace(opened: dict, name: str) -> Path:
    return Path(opened["variants"][name]["workspace"])


def test_untracked_and_non_utf8_files_are_captured(repo: Path):
    opened = ops.arena_open("task", variants=["a"])
    ws = workspace(opened, "a")
    (ws / "new_module.py").write_text("X = 1\n")
    (ws / "app.py").write_bytes(b"# caf\xe9\ndef value():\n    return 2\n")

    status = ops.arena_check()

    snap = Store(repo).load().variants["a"].snapshot
    assert snap is not None
    assert {f.path for f in snap.files} == {"new_module.py", "app.py"}
    assert b"new_module.py" in Path(snap.patch_path).read_bytes()
    assert status["variants"]["a"]["files_changed"] == 2


def test_carry_uncommitted_starts_variants_from_user_wip(repo: Path):
    (repo / "app.py").write_text("def value():\n    return 42\n")
    (repo / "wip.py").write_text("WIP = True\n")

    opened = ops.arena_open("task", variants=["a"], carry_uncommitted=True)

    ws = workspace(opened, "a")
    assert (ws / "app.py").read_text() == "def value():\n    return 42\n"
    assert (ws / "wip.py").exists()
    ops.arena_check()
    snap = Store(repo).load().variants["a"].snapshot
    assert snap is not None and snap.files == []  # the user's WIP is not credited to the variant


def test_dirty_repo_is_refused_without_carry(repo: Path):
    (repo / "app.py").write_text("changed\n")
    with pytest.raises(ArenaError, match="uncommitted"):
        ops.arena_open("task", variants=["a"])


def test_close_leaves_no_worktrees_refs_or_dirs(repo: Path):
    opened = ops.arena_open("task", variants=["a", "b"])
    (workspace(opened, "a") / "app.py").write_text("x = 1\n")
    ops.arena_check()
    root = Path(Store(repo).load().worktree_root)

    ops.arena_close()

    assert not root.exists()
    assert git(repo, "for-each-ref", "refs/arena/").strip() == ""
    assert git(repo, "branch", "--list", "arena/*").strip() == ""
    assert len(git(repo, "worktree", "list").splitlines()) == 1


def test_open_rolls_back_on_partial_failure(repo: Path, monkeypatch):
    from agents_arena_mcp import workspace as ws_mod

    real = ws_mod.create
    calls = {"n": 0}

    def flaky(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 2:
            raise ArenaError("boom")
        return real(*args, **kwargs)

    monkeypatch.setattr(ws_mod, "create", flaky)
    with pytest.raises(ArenaError, match="boom"):
        ops.arena_open("task", variants=["a", "b"])

    assert len(git(repo, "worktree", "list").splitlines()) == 1
    assert git(repo, "for-each-ref", "refs/arena/").strip() == ""


def test_promote_branch_leaves_user_checkout_alone(repo: Path):
    opened = ops.arena_open("task", variants=["a"])
    (workspace(opened, "a") / "app.py").write_text("def value():\n    return 2\n")
    ops.arena_check()
    ops.arena_judge(wait=True)

    result = ops.arena_promote(mode="branch")

    assert git(repo, "rev-parse", "--abbrev-ref", "HEAD").strip() == "main"
    assert (repo / "app.py").read_text() == "def value():\n    return 1\n"
    assert git(repo, "show", f"{result['branch']}:app.py") == "def value():\n    return 2\n"


def test_opencode_templates_have_no_dir_flag(repo: Path):
    config = load_config(repo)
    assert "--dir" not in config.runners["opencode"].argv
    assert "--dir" not in config.judges["opencode"].argv


def test_missing_tool_and_timeout_are_recorded(repo: Path):
    write_config(
        repo,
        extra="""
        check_timeout_sec = 1
        checks = [{ name = "missing", cmd = "definitely-not-a-tool-xyz" }, { name = "slow", cmd = "sleep 5" }]
        """,
    )
    opened = ops.arena_open("task", variants=["a"])
    (workspace(opened, "a") / "app.py").write_text("x = 2\n")

    status = ops.arena_check()

    assert status["variants"]["a"]["checks"] == {"missing": "error", "slow": "timeout"}


def test_reads_have_no_side_effects(repo: Path):
    with pytest.raises(ArenaError):
        ops.arena_status()
    assert not (repo / ".agents-arena").exists()


def test_current_arena_is_the_last_opened(repo: Path):
    first = ops.arena_open("first", variants=["a"])["arena_id"]
    second = ops.arena_open("second", variants=["a"])["arena_id"]

    ops.arena_check(arena_id=first)

    assert ops.arena_status()["arena_id"] == second


@pytest.mark.parametrize("path", ["docs/secrets-handling.md", "src/credentials_form.tsx"])
def test_secret_patterns_ignore_ordinary_files(repo: Path, path: str):
    patterns = load_config(repo).secret_patterns
    assert not any(re.search(p, path, re.IGNORECASE) for p in patterns)


@pytest.mark.parametrize("path", [".env", "config/.env.production", "keys/id_rsa", "secrets.yaml", "credentials.json"])
def test_secret_patterns_flag_secret_files(repo: Path, path: str):
    patterns = load_config(repo).secret_patterns
    assert any(re.search(p, path, re.IGNORECASE) for p in patterns)


def test_concurrent_mutations_do_not_lose_updates(repo: Path):
    arena_id = ops.arena_open("task", variants=["a"])["arena_id"]
    store = Store(repo)
    errors: list[BaseException] = []

    def bump(i: int) -> None:
        try:
            with Store(repo).mutate(arena_id) as a:
                a.pending_strategies.append(f"s{i}")
        except BaseException as exc:  # pragma: no cover - surfaced by the assert
            errors.append(exc)

    threads = [threading.Thread(target=bump, args=(i,)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    assert sorted(store.load(arena_id).pending_strategies) == sorted(f"s{i}" for i in range(20))


def test_default_strategy_names_keep_their_strategy_text(repo: Path):
    opened = ops.arena_open("task", variants=["minimal_patch"])
    assert "smallest safe patch" in opened["briefs"]["minimal_patch"]
