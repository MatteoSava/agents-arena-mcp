"""Fixtures: a throwaway git repo wired as the arena root, plus fake agent/judge scripts."""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

# Fake agent: writes files from FAKE_PLAN (JSON {"write": {path: text}, "delete": [path]}), echoes usage JSON.
FAKE_AGENT = textwrap.dedent(
    """
    import json, os, sys, time
    workspace = sys.argv[1]
    name = os.path.basename(os.path.dirname(workspace)).rsplit("-", 1)[0]
    plans = json.loads(os.environ.get("FAKE_PLAN", "{}"))
    plan = plans.get(name, {"write": {"app.py": f"def value():\\n    return '{name}'\\n"}})
    time.sleep(float(os.environ.get("FAKE_SLEEP", "0")))
    for rel, text in plan.get("write", {}).items():
        path = os.path.join(workspace, rel)
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        open(path, "w").write(text)
    for rel in plan.get("delete", []):
        os.remove(os.path.join(workspace, rel))
    seen = {k: os.environ.get(k, "") for k in ("HOME", "CODEX_HOME", "CLAUDE_CONFIG_DIR")}
    open(os.path.join(sys.argv[2], "env.json"), "w").write(json.dumps(seen))
    print(json.dumps({"usage": {"input_tokens": 100, "output_tokens": 20}, "total_cost_usd": 0.01}))
    """
)

# Fake judge: rubric -> score from the GOOD marker; final -> label holding GOOD (or "A" in always_a mode).
FAKE_JUDGE = textwrap.dedent(
    """
    import json, os, sys
    prompt, out = open(sys.argv[1]).read(), sys.argv[2]
    mode = os.environ.get("FAKE_JUDGE_MODE", "marker")
    if mode == "garbage":
        print("no json here"); sys.exit(0)
    if "## Patch A" not in prompt:
        answer = {"score": 9 if "GOOD" in prompt else 5, "reasons": ["rubric"], "risks": []}
    elif mode == "always_a":
        answer = {"winner": "A", "confidence": 0.9, "reasons": ["A"], "risks": []}
    else:
        a = prompt.split("## Patch A")[1].split("## Evidence for B")[0]
        b = prompt.split("## Patch B")[1]
        winner = "A" if "GOOD" in a and "GOOD" not in b else "B" if "GOOD" in b and "GOOD" not in a else "tie"
        answer = {"winner": winner, "confidence": 0.8, "reasons": [winner], "risks": []}
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
    (repo / "tests").mkdir()
    (repo / "tests" / "test_app.py").write_text("def test_ok():\n    assert True\n")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "initial")
    monkeypatch.setenv("AGENTS_ARENA_ROOT", str(repo))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    return repo


@pytest.fixture
def fakes(tmp_path: Path) -> dict[str, Path]:
    agent, judge = tmp_path / "fake_agent.py", tmp_path / "fake_judge.py"
    agent.write_text(FAKE_AGENT)
    judge.write_text(FAKE_JUDGE)
    return {"agent": agent, "judge": judge}


def command_contestant(fakes: dict[str, Path], name: str, **kw) -> dict:
    return {
        "name": name,
        "harness": "command",
        "argv": [sys.executable, str(fakes["agent"]), "{workspace}", "{run_dir}"],
        **kw,
    }


def command_judge(fakes: dict[str, Path]) -> dict:
    return {"harness": "command", "argv": [sys.executable, str(fakes["judge"]), "{prompt_file}", "{output_file}"]}
