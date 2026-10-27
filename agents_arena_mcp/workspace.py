"""Variant workspaces: detached git worktrees, snapshotted into commits, forkable from any checkpoint."""

from __future__ import annotations

import hashlib
import os
import platform
import subprocess
from pathlib import Path

from agents_arena_mcp import git, proc
from agents_arena_mcp.errors import ArenaError
from agents_arena_mcp.models import Arena, Snapshot, Variant
from agents_arena_mcp.store import Store, utc_now


def default_root(repo_root: Path, configured: str) -> Path:
    if configured:
        path = Path(configured).expanduser()
        return path if path.is_absolute() else (repo_root / path).resolve()
    digest = hashlib.sha256(str(repo_root).encode()).hexdigest()[:8]
    cache = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "agents-arena" / "worktrees"
    cache = cache / f"{repo_root.name}-{digest}"
    if _same_volume(repo_root, cache):
        return cache
    # APFS clones and uv hardlinks need the same volume; fall back to a sibling directory.
    return repo_root.parent / ".agents-arena-worktrees" / f"{repo_root.name}-{digest}"


def _same_volume(a: Path, b: Path) -> bool:
    probe = b
    while not probe.exists():
        probe = probe.parent
    return os.stat(a).st_dev == os.stat(probe).st_dev


def create(arena: Arena, name: str, commit: str, setup: str, timeout: int) -> Path:
    path = Path(arena.worktree_root) / name
    if path.exists():
        raise ArenaError(f"Workspace path already exists: {path}")
    git.worktree_add(Path(arena.repo_root), path, commit)
    if setup:
        result = proc.shell(setup, path, timeout, owner=arena.id)
        if not result.ok:
            raise ArenaError(f"setup command failed in {path} ({result.status}): {proc.tail(result.stderr, 800)}")
    return path


def snapshot(store: Store, arena: Arena, variant: Variant) -> Snapshot:
    """Capture the variant's tree as a commit on top of the arena base and store its patch."""
    workspace = Path(variant.workspace)
    number = len(variant.snapshots) + 1
    commit = git.snapshot_commit(workspace, arena.base_commit, f"arena {arena.id} {variant.name} #{number}")
    last = variant.snapshot
    if last and git.text(workspace, "rev-parse", f"{commit}^{{tree}}") == git.text(
        workspace, "rev-parse", f"{last.commit}^{{tree}}"
    ):
        return last  # nothing changed since the last checkpoint
    ref = f"refs/arena/{arena.id}/{variant.name}/{number}"
    git.update_ref(Path(arena.repo_root), ref, commit)
    patch = git.patch(workspace, arena.base_commit, commit)
    patch_path = store.arena_dir(arena.id) / "variants" / variant.name / f"patch-{number}.diff"
    patch_path.parent.mkdir(parents=True, exist_ok=True)
    patch_path.write_bytes(patch)
    snap = Snapshot(
        number=number,
        commit=commit,
        ref=ref,
        patch_hash=hashlib.sha256(_normalize(patch)).hexdigest(),
        patch_path=str(patch_path),
        files=git.changed_files(workspace, arena.base_commit, commit),
        created_at=utc_now(),
    )
    variant.snapshots.append(snap)
    return snap


def _normalize(patch: bytes) -> bytes:
    """Hash only the changed lines, ignoring whitespace, so trivially equal patches dedupe."""
    keep = []
    for line in patch.splitlines():
        if line.startswith((b"+++", b"---", b"index ", b"@@")):
            continue
        if line.startswith((b"+", b"-")):
            keep.append(b"".join(line[1:].split()) + line[:1])
        elif line.startswith(b"diff --git"):
            keep.append(line)
    return b"\n".join(keep)


def fork(
    arena: Arena, source: Variant, checkpoint: int | None, name: str, setup: str, timeout: int
) -> tuple[Path, str]:
    """New workspace at source's checkpoint; ignored dirs (venvs, node_modules) are cloned copy-on-write."""
    snaps = {s.number: s for s in source.snapshots}
    if not snaps:
        raise ArenaError(f"{source.name} has no checkpoint yet; run arena_check on it first.")
    number = checkpoint if checkpoint is not None else max(snaps)
    if number not in snaps:
        raise ArenaError(f"{source.name} has no checkpoint #{number}; available: {sorted(snaps)}")
    path = create(arena, name, snaps[number].commit, "", timeout)
    _clone_ignored(Path(source.workspace), path)
    if setup:
        result = proc.shell(setup, path, timeout, owner=arena.id)
        if not result.ok:
            raise ArenaError(f"setup command failed in fork {name}: {proc.tail(result.stderr, 800)}")
    return path, f"{source.name}@{number}"


def _clone_ignored(src: Path, dst: Path) -> None:
    listed = git.text(src, "ls-files", "--others", "--ignored", "--exclude-standard", "--directory")
    flag = ["-c"] if platform.system() == "Darwin" else ["--reflink=auto"]
    for rel in filter(None, listed.splitlines()):
        rel = rel.rstrip("/")
        target = dst / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["cp", *flag, "-R", str(src / rel), str(target)], check=False, capture_output=True)


def destroy(arena: Arena, variant: Variant) -> None:
    git.worktree_remove(Path(arena.repo_root), Path(variant.workspace))
