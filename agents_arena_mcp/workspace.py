"""Per-run workspaces: <worktree_root>/<run>/repo (detached worktree) and <run>/home (clean harness home)."""

from __future__ import annotations

import hashlib
import os
import shutil
from pathlib import Path

from agents_arena_mcp import git
from agents_arena_mcp.errors import ArenaError
from agents_arena_mcp.models import Arena, Overlay, Run, Snapshot
from agents_arena_mcp.store import Store


def default_root(repo_root: Path) -> Path:
    digest = hashlib.sha256(str(repo_root).encode()).hexdigest()[:8]
    cache = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "agents-arena" / "worktrees"
    cache = cache / f"{repo_root.name}-{digest}"
    probe = cache
    while not probe.exists():
        probe = probe.parent
    if os.stat(repo_root).st_dev == os.stat(probe).st_dev:
        return cache
    return repo_root.parent / ".agents-arena-worktrees" / f"{repo_root.name}-{digest}"  # same volume as the repo


def create(arena: Arena, run: Run) -> Path:
    path = Path(arena.worktree_root) / run.id / "repo"
    git.worktree_add(Path(arena.repo_root), path, arena.base_commit)
    return path


def home_dir(arena: Arena, run: Run) -> Path:
    return Path(arena.worktree_root) / run.id / "home"


def apply_overlays(workspace: Path, home: Path | None, overlays: list[Overlay]) -> None:
    for overlay in overlays:
        src = Path(overlay.source).expanduser()
        root = workspace if overlay.scope == "repo" else home
        if root is None:
            raise ArenaError(f"overlay {overlay.to} needs baseline='clean'")
        if not src.exists():
            raise ArenaError(f"overlay source not found: {overlay.source}")
        dst = root / overlay.rel
        if not dst.parent.resolve().is_relative_to(root.resolve()):
            raise ArenaError(f"overlay target {overlay.to} escapes its root")
        if dst.is_dir() and not dst.is_symlink():
            shutil.rmtree(dst)
        elif dst.exists() or dst.is_symlink():
            dst.unlink()
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            shutil.copytree(src, dst, symlinks=True)
        else:
            shutil.copy2(src, dst)


def overlay_base(arena: Arena, run: Run, workspace: Path, has_repo_overlays: bool) -> str:
    """The commit a run's diff is measured from: the arena base plus its repo overlays (pinned by a ref)."""
    if not has_repo_overlays:
        return arena.base_commit
    commit = git.snapshot_commit(workspace, arena.base_commit, f"arena {arena.id}: overlays for {run.id}")
    git.update_ref(Path(arena.repo_root), f"refs/arena/{arena.id}/{run.id}-base", commit)
    return commit


def snapshot(store: Store, arena: Arena, run: Run, workspace: Path) -> Snapshot:
    commit = git.snapshot_commit(workspace, run.base_commit, f"arena {arena.id}: {run.id}")
    git.update_ref(Path(arena.repo_root), f"refs/arena/{arena.id}/{run.id}", commit)  # keeps the commit reachable
    patch = git.patch(workspace, run.base_commit, commit)
    patch_path = store.arena_dir(arena.id) / "runs" / run.id / "patch.diff"
    patch_path.parent.mkdir(parents=True, exist_ok=True)
    patch_path.write_bytes(patch)
    return Snapshot(
        commit=commit,
        patch_hash=hashlib.sha256(_normalize(patch)).hexdigest(),
        patch_path=str(patch_path),
        files=git.changed_files(workspace, run.base_commit, commit),
    )


def _normalize(patch: bytes) -> bytes:
    """Hash only changed lines, whitespace-insensitive, so trivially equal patches compare equal."""
    keep = []
    for line in patch.splitlines():
        if line.startswith((b"+++", b"---", b"index ", b"@@")):
            continue
        if line.startswith((b"+", b"-")):
            keep.append(b"".join(line[1:].split()) + line[:1])
        elif line.startswith(b"diff --git"):
            keep.append(line)
    return b"\n".join(keep)


def remove_root(arena: Arena) -> None:
    """Drop the arena's worktree dir, and the per-repo dir above it, once they are empty."""
    root = Path(arena.worktree_root)
    for path in (root, root.parent):
        try:
            path.rmdir()
        except FileNotFoundError:
            continue
        except OSError:  # not empty: another arena of this repo is still using it
            return


def destroy(arena: Arena, run: Run) -> None:
    """Remove the worktree and the run's home, which may hold a copied auth file."""
    if run.workspace:
        git.worktree_remove(Path(arena.repo_root), Path(run.workspace))
    shutil.rmtree(Path(arena.worktree_root) / run.id, ignore_errors=True)
