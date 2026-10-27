from pathlib import Path

import pytest
from conftest import git

from agents_arena_mcp import workspace
from agents_arena_mcp.errors import ArenaError
from agents_arena_mcp.models import Arena, Overlay, Run, Spec
from agents_arena_mcp.store import Store


def make_arena(repo: Path, tmp_path: Path) -> Arena:
    base = git(repo, "rev-parse", "HEAD").strip()
    spec = Spec.model_validate({"task": "t", "contestants": [{"name": "a", "harness": "claude"}]})
    return Arena(
        id="arena1",
        spec=spec,
        repo_root=str(repo),
        base_commit=base,
        worktree_root=str(tmp_path / "wt"),
        created_at="now",
    )


def test_overlays_land_in_repo_and_home_and_are_not_counted(repo, tmp_path):
    arena = make_arena(repo, tmp_path)
    run = Run(id="a-1", contestant="a", repeat=1)
    src = tmp_path / "skill-v2"
    src.mkdir()
    (src / "SKILL.md").write_text("v2\n")
    ws = workspace.create(arena, run)
    home = workspace.home_dir(arena, run)
    workspace.apply_overlays(
        ws,
        home,
        [
            Overlay.model_validate({"from": str(src), "to": "repo:.claude/skills/foo"}),
            Overlay.model_validate({"from": str(src / "SKILL.md"), "to": "home:.codex/skills/s/SKILL.md"}),
        ],
    )
    assert (ws / ".claude/skills/foo/SKILL.md").read_text() == "v2\n"
    assert (home / ".codex/skills/s/SKILL.md").exists()
    run.base_commit = workspace.overlay_base(arena, run, ws, has_repo_overlays=True)
    (ws / "app.py").write_text("def value():\n    return 2\n")
    snap = workspace.snapshot(Store(repo), arena, run, ws)
    assert [f.path for f in snap.files] == ["app.py"]  # the overlay is part of the base, not the contestant's change
    workspace.destroy(arena, run.model_copy(update={"workspace": str(ws)}))
    assert not (Path(arena.worktree_root) / "a-1").exists()
    assert len(git(repo, "worktree", "list").splitlines()) == 1


def test_commit_patch_builds_a_branch_commit_without_checkout(repo, tmp_path):
    arena = make_arena(repo, tmp_path)
    run = Run(id="a-1", contestant="a", repeat=1, base_commit=arena.base_commit)
    ws = workspace.create(arena, run)
    (ws / "new.py").write_text("X = 1\n")
    snap = workspace.snapshot(Store(repo), arena, run, ws)
    from agents_arena_mcp import git as g

    commit = g.commit_patch(repo, arena.base_commit, Path(snap.patch_path), "arena: a-1")
    assert git(repo, "show", f"{commit}:new.py") == "X = 1\n"
    assert git(repo, "rev-parse", "--abbrev-ref", "HEAD").strip() == "main"


def test_overlay_refuses_symlink_escape_and_missing_source(repo, tmp_path):
    arena = make_arena(repo, tmp_path)
    run = Run(id="a-1", contestant="a", repeat=1)
    ws = workspace.create(arena, run)
    outside = tmp_path / "outside"
    outside.mkdir()
    (ws / "link").symlink_to(outside)
    src = tmp_path / "x.md"
    src.write_text("x\n")
    with pytest.raises(ArenaError, match="escapes"):
        workspace.apply_overlays(ws, None, [Overlay.model_validate({"from": str(src), "to": "repo:link/x.md"})])
    assert list(outside.iterdir()) == []
    with pytest.raises(ArenaError, match="not found"):
        workspace.apply_overlays(
            ws, None, [Overlay.model_validate({"from": str(tmp_path / "nope"), "to": "repo:y.md"})]
        )


def test_snapshot_excludes_build_artifacts(repo, tmp_path):
    arena = make_arena(repo, tmp_path)
    run = Run(id="a-1", contestant="a", repeat=1, base_commit=arena.base_commit)
    ws = workspace.create(arena, run)
    (ws / "a.py").write_text("X = 1\n")
    artifacts = {
        "__pycache__/a.cpython-312.pyc": b"\x00\x01",
        "pkg/__pycache__/b.pyc": b"\x00\x02",
        ".pytest_cache/v/x": b"x",
        "node_modules/m/index.js": b"x",
        ".DS_Store": b"x",
        ".venv/x": b"x",
        ".mypy_cache/x": b"x",
        ".ruff_cache/x": b"x",
        ".coverage": b"x",
    }
    for rel, data in artifacts.items():
        (ws / rel).parent.mkdir(parents=True, exist_ok=True)
        (ws / rel).write_bytes(data)
    snap = workspace.snapshot(Store(repo), arena, run, ws)
    assert [f.path for f in snap.files] == ["a.py"]
    assert "__pycache__" not in Path(snap.patch_path).read_text()
