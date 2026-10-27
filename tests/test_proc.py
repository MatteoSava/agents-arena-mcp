import sys
from pathlib import Path

import pytest

from agents_arena_mcp import proc

PRINT_PWD = [sys.executable, "-c", "import os,sys; sys.stdout.write(os.environ.get('PWD',''))"]


def test_run_sets_pwd_to_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PWD", "/somewhere/else")
    assert proc.run(PRINT_PWD, tmp_path, 10).stdout == str(tmp_path)


def test_run_pwd_survives_env_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PWD", "/somewhere/else")
    result = proc.run(PRINT_PWD, tmp_path, 10, env={"PWD": "/override", "X": "1"})
    assert result.stdout == str(tmp_path)


def test_shell_sets_pwd_to_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PWD", "/somewhere/else")
    assert proc.shell('printf %s "$PWD"', tmp_path, 10).stdout == str(tmp_path)
