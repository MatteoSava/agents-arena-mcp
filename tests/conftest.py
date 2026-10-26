from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, text=True, capture_output=True, check=True).stdout


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "arena@example.com")
    git(repo, "config", "user.name", "Arena Test")
    (repo / "app.py").write_text("def value():\n    return 1\n")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "initial")
    return repo
