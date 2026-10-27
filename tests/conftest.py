"""Fixtures: a throwaway git repo wired as the arena root, plus fake agent and judge CLIs."""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

FAKE_RUNNER = textwrap.dedent(
    """
    import os, sys, time
    workspace, run_dir = sys.argv[1], sys.argv[2]
    name = os.path.basename(workspace)
    with open(os.path.join(run_dir, "times.txt"), "w") as fh:
        fh.write(f"{time.time()}\\n")
        time.sleep(float(os.environ.get("FAKE_RUNNER_SLEEP", "0")))
        fh.write(f"{time.time()}\\n")
    open(os.path.join(workspace, "app.py"), "w").write(f"def value():\\n    return '{name}'\\n")
    open(os.path.join(workspace, f"new_{name.replace('-', '_')}.py"), "w").write("X = 1\\n")
    open(os.path.join(workspace, "blob.bin"), "wb").write(bytes(range(256)))
    if os.path.exists(os.path.join(workspace, "old.txt")):
        os.remove(os.path.join(workspace, "old.txt"))
    print('{"type": "turn.completed", "usage": {"input_tokens": 10, "output_tokens": 5}}')
    """
)

# Picks the label whose patch contains the marker GOOD; "always_a" mode ignores content (pure position bias).
FAKE_JUDGE = textwrap.dedent(
    """
    import json, os, re, sys
    prompt = open(sys.argv[1]).read()
    out = sys.argv[2]
    mode = os.environ.get("FAKE_JUDGE_MODE", "marker")
    if "- Checkout A: " in prompt:  # agentic final round: inspect the checkouts themselves
        path_a = prompt.split("- Checkout A: ")[1].split("\\n")[0]
        winner = "A" if os.path.exists(os.path.join(path_a, "WINNER")) else "B"
        answer = {"winner": winner, "confidence": 0.9, "reasons": ["inspected checkouts"], "risks": []}
    elif "Propose ONE shell command" in prompt:
        answer = {"command": "cat probe.txt", "rationale": "probe differs"}
    elif mode == "always_a":
        answer = {"winner": "A", "confidence": 0.9, "reasons": ["A looks better"], "risks": []}
    elif mode == "garbage":
        print("I refuse to answer in JSON")
        sys.exit(0)
    else:
        a = prompt.split("## Patch A")[1].split("## Evidence for B")[0]
        b = prompt.split("## Patch B")[1]
        if mode == "evidence" and "## Distinguishing test" in prompt:
            winner = "A" if "Output in A (passed" in prompt and "probe-good" in prompt.split("Output in A")[1].split("Output in B")[0] else "B"
        elif mode == "evidence":
            winner = "tie"
        else:
            winner = "A" if "GOOD" in a and "GOOD" not in b else "B" if "GOOD" in b and "GOOD" not in a else "tie"
        answer = {"winner": winner, "confidence": 0.8, "reasons": [f"picked {winner}"], "risks": []}
    open(out, "w").write(json.dumps(answer))
    """
)


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, text=True, capture_output=True, check=True).stdout


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "arena@example.com")
    git(repo, "config", "user.name", "Arena Test")
    (repo / "app.py").write_text("def value():\n    return 1\n")
    (repo / "old.txt").write_text("to be deleted\n")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "initial")
    monkeypatch.setenv("AGENTS_ARENA_ROOT", str(repo))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    return repo


@pytest.fixture
def fakes(tmp_path: Path) -> dict[str, Path]:
    runner = tmp_path / "fake_runner.py"
    runner.write_text(FAKE_RUNNER)
    judge = tmp_path / "fake_judge.py"
    judge.write_text(FAKE_JUDGE)
    return {"runner": runner, "judge": judge}


def write_config(repo: Path, fakes: dict[str, Path] | None = None, extra: str = "") -> None:
    """Write .agents-arena/config.toml. `extra` is TOML (top-level keys first); fake runner/judge tables go last."""
    head = ["default_runner = 'fake'"] if fakes else []
    tables = []
    if fakes:
        py = sys.executable
        tables = [
            "[runners.fake]",
            f"argv = ['{py}', '{fakes['runner']}', '{{workspace}}', '{{run_dir}}']",
            "family = 'fake-gen'",
            "[judges.fake]",
            f"argv = ['{py}', '{fakes['judge']}', '{{prompt_file}}', '{{output_file}}']",
            "family = 'fake-judge'",
        ]
    config = repo / ".agents-arena" / "config.toml"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text("\n".join([*head, textwrap.dedent(extra), *tables]) + "\n")
