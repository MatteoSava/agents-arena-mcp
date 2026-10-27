"""Regression: same-size edits made in the same second as checkout must still be snapshotted (racy-git)."""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

from conftest import git

from agents_arena_mcp import git as arena_git


def test_same_second_same_size_edits_are_captured(tmp_path: Path, repo: Path):
    base = git(repo, "rev-parse", "HEAD").strip()
    missed = 0
    for i in range(3):
        wt = tmp_path / f"wt{i}"
        subprocess.run(["git", "worktree", "add", "-q", "--detach", str(wt), base], cwd=repo, check=True)
        (wt / "app.py").write_text("def value():\n    return 2\n")  # same size, same second as checkout
        time.sleep(1.1)  # snapshot after the second boundary, when git would trust stale stat data
        commit = arena_git.snapshot_commit(wt, base, "t")
        if not arena_git.changed_files(wt, base, commit):
            missed += 1
    assert missed == 0, f"{missed}/3 snapshots missed a same-size edit"
