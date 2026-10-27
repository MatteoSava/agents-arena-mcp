"""Git plumbing. Variant state lives in snapshot commits under refs/arena/, never in branches."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from agents_arena_mcp.errors import ArenaError
from agents_arena_mcp.models import FileChange

IDENTITY = {
    "GIT_AUTHOR_NAME": "Agents Arena",
    "GIT_AUTHOR_EMAIL": "arena@localhost",
    "GIT_COMMITTER_NAME": "Agents Arena",
    "GIT_COMMITTER_EMAIL": "arena@localhost",
}
STATE_DIR = ".agents-arena"


def git(cwd: Path, *args: str, env: dict[str, str] | None = None, check: bool = True) -> bytes:
    result = subprocess.run(["git", *args], cwd=cwd, env={**os.environ, **(env or {})}, capture_output=True)
    if check and result.returncode != 0:
        raise ArenaError(f"git {' '.join(args)} failed: {result.stderr.decode('utf-8', 'replace').strip()}")
    return result.stdout


def text(cwd: Path, *args: str, env: dict[str, str] | None = None) -> str:
    return git(cwd, *args, env=env).decode("utf-8", "replace").strip()


def repo_root(start: Path) -> Path:
    try:
        return Path(text(start, "rev-parse", "--show-toplevel")).resolve()
    except (ArenaError, FileNotFoundError, NotADirectoryError) as exc:
        raise ArenaError(f"Not inside a git repository: {start}") from exc


def rev_parse(cwd: Path, ref: str) -> str:
    return text(cwd, "rev-parse", "--verify", f"{ref}^{{commit}}")


def is_dirty(root: Path) -> bool:
    status = text(root, "status", "--porcelain", "--", ".", f":(exclude){STATE_DIR}")
    return bool(status)


# Artifacts produced by running tools are never part of a contestant's change.
ARTIFACT_EXCLUDES = [
    ":(exclude,glob)**/__pycache__/**",
    ":(exclude,glob)**/*.pyc",
    ":(exclude,glob)**/.pytest_cache/**",
    ":(exclude,glob)**/node_modules/**",
    ":(exclude,glob)**/.DS_Store",
]


def snapshot_commit(workdir: Path, parent: str, message: str) -> str:
    """Commit the whole working tree (tracked + untracked, minus ignored) without touching the real index."""
    index = Path(text(workdir, "rev-parse", "--path-format=absolute", "--git-path", "index"))
    with tempfile.TemporaryDirectory() as tmp:
        tmp_index = Path(tmp) / "index"
        if index.exists():
            # copy2 keeps the index mtime: git's racy-entry check depends on it, or same-second edits go unseen.
            shutil.copy2(index, tmp_index)
        env = {"GIT_INDEX_FILE": str(tmp_index), **IDENTITY}
        git(workdir, "add", "-A", "--", ".", f":(exclude){STATE_DIR}", *ARTIFACT_EXCLUDES, env=env)
        tree = text(workdir, "write-tree", env=env)
    return text(workdir, "commit-tree", tree, "-p", parent, "-m", message, env=IDENTITY)


def update_ref(root: Path, ref: str, commit: str) -> None:
    git(root, "update-ref", ref, commit)


def delete_refs(root: Path, prefix: str) -> None:
    refs = text(root, "for-each-ref", "--format=%(refname)", prefix).splitlines()
    for ref in refs:
        git(root, "update-ref", "-d", ref)


def worktree_add(root: Path, path: Path, commit: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    git(root, "worktree", "add", "--detach", "--quiet", str(path), commit)


def worktree_remove(root: Path, path: Path) -> None:
    git(root, "worktree", "remove", "--force", str(path), check=False)
    shutil.rmtree(path, ignore_errors=True)


def worktree_prune(root: Path) -> None:
    git(root, "worktree", "prune", check=False)


def changed_files(cwd: Path, base: str, head: str) -> list[FileChange]:
    status = git(cwd, "diff", "--name-status", "-z", "-M", base, head).decode("utf-8", "replace").split("\0")
    numstat = git(cwd, "diff", "--numstat", "-z", "-M", base, head).decode("utf-8", "replace")
    counts: dict[str, tuple[int, int]] = {}
    # -z numstat: "added\tremoved\tpath\0" or, for renames, "added\tremoved\t\0old\0new\0"
    parts = numstat.split("\0")
    i = 0
    while i < len(parts) and parts[i]:
        added, removed, path = parts[i].split("\t", 2)
        if not path:
            path, i = parts[i + 2], i + 2
        counts[path] = (int(added) if added != "-" else 0, int(removed) if removed != "-" else 0)
        i += 1
    files: list[FileChange] = []
    j = 0
    while j < len(status) and status[j]:
        code = status[j]
        if code.startswith(("R", "C")):
            path, j = status[j + 2], j + 3
        else:
            path, j = status[j + 1], j + 2
        added, removed = counts.get(path, (0, 0))
        files.append(FileChange(path=path, status=code[0], added=added, removed=removed))
    return files


def patch(cwd: Path, base: str, head: str) -> bytes:
    return git(cwd, "diff", "--binary", "-M", base, head)


def create_branch(root: Path, name: str, commit: str) -> None:
    git(root, "branch", name, commit)


def apply_patch(root: Path, patch_path: Path) -> None:
    """Apply to the working tree only if it applies cleanly; never leaves a half-applied tree."""
    if subprocess.run(["git", "apply", "--check", str(patch_path)], cwd=root, capture_output=True).returncode != 0:
        raise ArenaError(
            "winner.diff doesn't apply cleanly to your working tree (it changed since the arena started?). "
            "Nothing was modified. Use promote='branch' instead."
        )
    git(root, "apply", str(patch_path))


def commit_patch(root: Path, base: str, patch_path: Path, message: str) -> str:
    """Commit `patch` on top of `base` using a temporary index: no checkout, the user's tree is untouched."""
    with tempfile.TemporaryDirectory() as tmp:
        env = {"GIT_INDEX_FILE": str(Path(tmp) / "index"), **IDENTITY}
        git(root, "read-tree", base, env=env)
        git(root, "apply", "--cached", "--binary", str(patch_path), env=env)
        tree = text(root, "write-tree", env=env)
    return text(root, "commit-tree", tree, "-p", base, "-m", message, env=IDENTITY)
