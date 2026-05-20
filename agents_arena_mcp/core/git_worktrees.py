from __future__ import annotations

import os
from pathlib import Path

from .errors import ArenaError
from .util import ensure_dir, run_cmd, slugify


def discover_repo_root(start: Path | None = None) -> Path:
    start = Path(start or os.environ.get("AGENTS_ARENA_ROOT") or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()).resolve()
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


def diff_against(repo_root_or_worktree: Path, base_commit: str) -> dict:
    names = run_cmd(["git", "diff", "--name-only", base_commit], cwd=repo_root_or_worktree, check=True).stdout.splitlines()
    stat = run_cmd(["git", "diff", "--stat", base_commit], cwd=repo_root_or_worktree, check=False).stdout
    patch = run_cmd(["git", "diff", "--binary", base_commit], cwd=repo_root_or_worktree, check=False).stdout
    numstat = run_cmd(["git", "diff", "--numstat", base_commit], cwd=repo_root_or_worktree, check=False).stdout
    added = 0
    removed = 0
    for line in numstat.splitlines():
        parts = line.split("\t")
        if len(parts) >= 3:
            try:
                added += int(parts[0]) if parts[0] != "-" else 0
                removed += int(parts[1]) if parts[1] != "-" else 0
            except ValueError:
                pass
    return {
        "changed_files": [line.strip() for line in names if line.strip()],
        "files_changed": len([line for line in names if line.strip()]),
        "lines_added": added,
        "lines_removed": removed,
        "stat": stat,
        "patch": patch,
    }
