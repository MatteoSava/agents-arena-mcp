from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from .errors import ArenaError
from .util import ensure_dir, run_cmd, slugify


def discover_repo_root(start: Path | None = None) -> Path:
    start = Path(
        start or os.environ.get("AGENTS_ARENA_ROOT") or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    ).resolve()
    result = run_cmd(["git", "rev-parse", "--show-toplevel"], cwd=start)
    if result.returncode == 0 and result.stdout.strip():
        return Path(result.stdout.strip()).resolve()
    return start


def git(repo_root: Path, args: list[str], check: bool = True):
    return run_cmd(["git", *args], cwd=repo_root, check=check)


def current_commit(repo_root: Path, ref: str = "HEAD") -> str:
    result = git(repo_root, ["rev-parse", ref])
    return result.stdout.strip()


def repo_name(repo_root: Path) -> str:
    return slugify(repo_root.name)


def status_porcelain(repo_root: Path) -> str:
    return git(repo_root, ["status", "--porcelain"], check=True).stdout


def is_dirty(repo_root: Path) -> bool:
    lines = []
    for line in status_porcelain(repo_root).splitlines():
        path = line[3:] if len(line) > 3 else line
        # Internal arena state should not prevent opening an arena.
        if path.startswith(".agents-arena/"):
            continue
        lines.append(line)
    return bool(lines)


def resolve_worktree_root(repo_root: Path, policy: dict) -> Path:
    template = policy.get("worktrees", {}).get("location", "../.agents-arena-worktrees/{repo_name}")
    value = template.format(repo_name=repo_name(repo_root))
    path = Path(value)
    if not path.is_absolute():
        path = (repo_root / path).resolve()
    ensure_dir(path)
    return path


def create_worktree(repo_root: Path, worktree_path: Path, branch: str, base_ref: str) -> None:
    ensure_dir(worktree_path.parent)
    if worktree_path.exists() and any(worktree_path.iterdir()):
        raise ArenaError(f"Worktree path already exists and is not empty: {worktree_path}")
    # Remove stale branch if it points nowhere usable is intentionally not automatic.
    result = run_cmd(["git", "worktree", "add", "-b", branch, str(worktree_path), base_ref], cwd=repo_root)
    if result.returncode != 0:
        raise ArenaError(f"Failed to create git worktree {worktree_path}:\n{result.stderr or result.stdout}")


def remove_worktree(repo_root: Path, worktree_path: Path, force: bool = True) -> dict:
    args = ["git", "worktree", "remove"]
    if force:
        args.append("--force")
    args.append(str(worktree_path))
    result = run_cmd(args, cwd=repo_root)
    return {"returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr}


SNAPSHOT_IDENTITY = {
    "GIT_AUTHOR_NAME": "Agents Arena",
    "GIT_AUTHOR_EMAIL": "arena@localhost",
    "GIT_COMMITTER_NAME": "Agents Arena",
    "GIT_COMMITTER_EMAIL": "arena@localhost",
}


def git_bytes(cwd: Path, args: list[str], env: dict[str, str] | None = None) -> bytes:
    result = subprocess.run(["git", *args], cwd=cwd, env={**os.environ, **(env or {})}, capture_output=True)
    if result.returncode != 0:
        raise ArenaError(f"git {' '.join(args)} failed: {result.stderr.decode('utf-8', 'replace')}")
    return result.stdout


def snapshot_commit(workdir: Path, parent: str, message: str = "arena snapshot") -> str:
    """Commit the full working tree (tracked + untracked, minus ignored) without touching the real index."""
    index = Path(git_bytes(workdir, ["rev-parse", "--path-format=absolute", "--git-path", "index"]).decode().strip())
    with tempfile.TemporaryDirectory() as tmp:
        tmp_index = Path(tmp) / "index"
        if index.exists():
            shutil.copyfile(index, tmp_index)
        env = {"GIT_INDEX_FILE": str(tmp_index), **SNAPSHOT_IDENTITY}
        git_bytes(workdir, ["add", "-A", "--", ".", ":(exclude).agents-arena"], env)
        tree = git_bytes(workdir, ["write-tree"], env).decode().strip()
    return git_bytes(workdir, ["commit-tree", tree, "-p", parent, "-m", message], SNAPSHOT_IDENTITY).decode().strip()


def diff_commits(cwd: Path, base: str, head: str) -> dict:
    names = git_bytes(cwd, ["diff", "--name-only", "-z", base, head]).decode("utf-8", "replace").split("\0")
    stat = git_bytes(cwd, ["diff", "--stat", base, head]).decode("utf-8", "replace")
    patch = git_bytes(cwd, ["diff", "--binary", base, head])
    numstat = git_bytes(cwd, ["diff", "--numstat", base, head]).decode("utf-8", "replace")
    added = removed = 0
    for line in numstat.splitlines():
        parts = line.split("\t")
        if len(parts) >= 3 and parts[0] != "-":
            added += int(parts[0])
            removed += int(parts[1])
    changed = [n for n in names if n]
    return {
        "changed_files": changed,
        "files_changed": len(changed),
        "lines_added": added,
        "lines_removed": removed,
        "stat": stat,
        "patch": patch.decode("utf-8", "replace"),
        "patch_bytes": patch,
        "commit": head,
    }


def diff_against(worktree: Path, base_commit: str) -> dict:
    return diff_commits(worktree, base_commit, snapshot_commit(worktree, base_commit))


def delete_branch(repo_root: Path, branch: str) -> None:
    run_cmd(["git", "branch", "-D", branch], cwd=repo_root)


def prune_worktrees(repo_root: Path) -> None:
    run_cmd(["git", "worktree", "prune"], cwd=repo_root)
