# Agents Arena v0.3 (Experiment Bench) Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn Agents Arena into an experiment bench. The user's agent writes a spec (task, contestants = harness + model + baseline + overlays + strategy, objective, repeats). The arena runs every contestant × repeat in isolation, then returns a scorecard. A winner can be shipped, and results are logged to history and can be rendered as an HTML report.

**Architecture:** Rebuild on the proven v0.2 primitives: `git.py` (snapshot commits), `proc.py` (process groups, timeouts), `store.py` (flock state), and the snapshot/gate/judge logic. Replace the step-by-step ops with a spec-driven pipeline behind 5 MCP tools. Each harness gets an adapter whose isolation recipe comes from `docs/v0.3-isolation-spike.md`:
- `clean` = a fresh `HOME` plus the harness config vars, with auth seeded.
- `real` = the user's actual home, never modified.

**Tech Stack:** Python 3.11+, fastmcp 3.3.1, pydantic 2.13.4, pytest, ruff, basedpyright, uv. No new dependencies.

**Source documents:** design in `~/.claude/plans/lets-revamp-the-project-optimized-pillow.md`; harness facts in `docs/v0.3-isolation-spike.md`. Clean Claude auth uses `CLAUDE_CODE_OAUTH_TOKEN` (from `claude setup-token`) or `ANTHROPIC_API_KEY`.

**Conventions for every task:** run commands from the repo root `/Users/matteo/Developer/agents-arena-mcp` on branch `revamp/v0.3`. Use `uv run` for everything. Commits follow Conventional Commits. Before every commit run `uv run ruff format . && uv run ruff check --fix .`, then `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run basedpyright`. All four must be green after every task (Task 1 deletes every module that later tasks rewrite, so nothing stale keeps the type checker red).

---

## File map (end state)

| File | Responsibility | Status |
|---|---|---|
| `agents_arena_mcp/models.py` | Spec (input) and Arena/Run/Scorecard (runtime) pydantic models | rewrite |
| `agents_arena_mcp/harness.py` | Adapters: claude, codex, opencode, command. argv, clean env, preflight, metrics | new |
| `agents_arena_mcp/workspace.py` | Run worktree + harness home, overlays, snapshot, destroy | rewrite |
| `agents_arena_mcp/checks.py` | Run checks, base-commit baseline, gates | adapt |
| `agents_arena_mcp/judge.py` | Rubric scoring per run, both-order finals, `extract_json` | rewrite (keeps `extract_json`) |
| `agents_arena_mcp/scorecard.py` | Stats, winner, markdown, HTML, history record | new |
| `agents_arena_mcp/pipeline.py` | create → execute (baseline, runs, judging, scorecard), promote | new |
| `agents_arena_mcp/plan.py` | Repo detection, draft spec, interview questions | new |
| `agents_arena_mcp/arena.py` | The 5 ops + `OPS` | rewrite |
| `agents_arena_mcp/server.py` / `cli.py` | MCP registration + `arena://guide`; CLI parity | rewrite |
| `agents_arena_mcp/scaffold.py` | `agents-arena init --skills …` (SKILL.md from GUIDE.md) | adapt |
| `agents_arena_mcp/evals.py` | `eval-judge` on the new pipeline | rewrite |
| `agents_arena_mcp/git.py`, `proc.py`, `store.py`, `jobs.py`, `errors.py` | Unchanged or nearly | keep |
| `agents_arena_mcp/data/` | `brief.md.tmpl`, `rubric.md.tmpl`, `final.md.tmpl`, `rubric.schema.json`, `judge.schema.json`, `GUIDE.md`, `judge_cases/` | adapt |
| Deleted | `config.py`, `select.py`, `search.py`, `report.py`, `runners.py`, `data/config.default.toml`, `data/distinguish*`, `data/judge_agentic.md.tmpl`, `data/judge.md.tmpl`, `data/SKILL.md` | delete |

---

## Chunk 1: Foundation (models, harness adapters, workspace, checks)

### Task 1: Clear the v0.2 surface

**Files:**
- Delete: `agents_arena_mcp/{arena.py,select.py,search.py,report.py,runners.py,config.py,scaffold.py,evals.py,server.py,cli.py,judge.py,checks.py,workspace.py}` (`judge.py`, `checks.py` and `workspace.py` are rewritten in Tasks 7, 5 and 4; their v0.2 code is in git history), `agents_arena_mcp/data/{config.default.toml,distinguish.md.tmpl,distinguish.schema.json,judge_agentic.md.tmpl,SKILL.md}`, `tests/{test_e2e.py,test_evals.py,test_judging.py,test_regressions.py,test_search.py,test_surface.py}`
- Keep: `tests/conftest.py` (rewritten in Task 2), `tests/test_snapshot_race.py`

- [ ] **Step 1: Delete files**

```bash
git rm -q agents_arena_mcp/{arena.py,select.py,search.py,report.py,runners.py,config.py,scaffold.py,evals.py,server.py,cli.py,judge.py,checks.py,workspace.py} \
  agents_arena_mcp/data/{config.default.toml,distinguish.md.tmpl,distinguish.schema.json,judge_agentic.md.tmpl,SKILL.md} \
  tests/{test_e2e.py,test_evals.py,test_judging.py,test_regressions.py,test_search.py,test_surface.py}
```

- [ ] **Step 2: Temporarily stub the console scripts.** `pyproject.toml` points at `cli:main` and `server:main`. Create minimal placeholders so the package imports (they're replaced in Chunk 4):

`agents_arena_mcp/cli.py`:
```python
"""Placeholder until Chunk 4 (v0.3 CLI)."""


def main(argv: list[str] | None = None) -> int:
    raise SystemExit("agents-arena v0.3 CLI is under construction")
```

`agents_arena_mcp/server.py`:
```python
"""Placeholder until Chunk 4 (v0.3 MCP server)."""


def main() -> None:
    raise SystemExit("agents-arena v0.3 MCP server is under construction")
```

- [ ] **Step 3: Fix `jobs.py`'s import of the deleted `runners.new_run_id`.** In `agents_arena_mcp/jobs.py`, delete the line `from agents_arena_mcp.runners import new_run_id`. Add `import secrets` and `from datetime import UTC, datetime` to the import block in sorted position, then define the helper right after the imports:

```python
def new_run_id(prefix: str) -> str:
    return f"{prefix}-{datetime.now(UTC).strftime('%Y%m%dT%H%M%S')}-{secrets.token_hex(3)}"
```

- [ ] **Step 4: Verify.** `uv run pytest -q` passes (only `test_snapshot_race.py` remains), and `uv run basedpyright` and `uv run ruff check .` are green.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -qm "refactor!: remove the v0.2 step-by-step surface ahead of the v0.3 rebuild"
```

### Task 2: Models

**Files:**
- Rewrite: `agents_arena_mcp/models.py`
- Rewrite: `tests/conftest.py`
- Test: `tests/test_models.py`

- [ ] **Step 1: Write the failing test** `tests/test_models.py`

```python
import pytest
from pydantic import ValidationError

from agents_arena_mcp.models import Contestant, FileChange, Gate, Overlay, Run, Snapshot, Spec


def spec(**kw):
    base = {"task": "t", "contestants": [{"name": "a", "harness": "claude"}]}
    return Spec.model_validate(base | kw)


def test_overlay_targets_must_be_scoped():
    assert Overlay.model_validate({"from": "/x", "to": "repo:.claude/skills/foo"}).rel == ".claude/skills/foo"
    for bad in ("skills/foo", "repo:", "home:../escape"):
        with pytest.raises(ValidationError):
            Overlay.model_validate({"from": "/x", "to": bad})


def test_home_overlays_require_clean_baseline():
    with pytest.raises(ValidationError, match="home: overlays need baseline='clean'"):
        Contestant.model_validate(
            {"name": "a", "harness": "codex", "baseline": "real", "overlays": [{"from": "/x", "to": "home:.codex/skills/s"}]}
        )


def test_command_harness_requires_argv_and_names_are_slugs():
    with pytest.raises(ValidationError):
        Contestant(name="a", harness="command")
    with pytest.raises(ValidationError):
        Contestant(name="Bad Name", harness="claude")


def test_spec_rules():
    with pytest.raises(ValidationError, match="unique"):
        spec(contestants=[{"name": "a", "harness": "claude"}, {"name": "a", "harness": "codex"}])
    with pytest.raises(ValidationError):
        spec(contestants=[{"name": f"c{i}", "harness": "claude"} for i in range(7)])
    assert spec(objective="tokens").judged is False
    assert spec(objective="elegance").judged is True
    assert spec(judge={"harness": "none"}).judged is False


def test_run_eligibility():
    snap = Snapshot(commit="c", patch_hash="h", patch_path="/p", files=[FileChange(path="a.py", status="M", added=1)])
    ok = Run(id="a-1", contestant="a", repeat=1, state="done", snapshot=snap)
    assert ok.eligible
    assert not ok.model_copy(update={"gates": [Gate(kind="test_deleted", severity="disqualify")]}).eligible
    assert not ok.model_copy(update={"snapshot": snap.model_copy(update={"files": []})}).eligible
    assert not ok.model_copy(update={"state": "failed"}).eligible
```

- [ ] **Step 2: Run it.** `uv run pytest tests/test_models.py -q`. Expected: FAIL (ImportError: `Contestant` not found).

- [ ] **Step 3: Write `agents_arena_mcp/models.py`**

```python
"""Typed state. A Spec is what the user asks for; an Arena is the record of running it."""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

HarnessName = Literal["claude", "codex", "opencode", "command"]
CheckStatus = Literal["passed", "failed", "error", "timeout"]
GateSeverity = Literal["disqualify", "needs_human", "info"]
METRIC_OBJECTIVES = ("speed", "tokens", "cost")
NAME = re.compile(r"[a-z0-9][a-z0-9_.-]{0,39}")


# ---- spec -----------------------------------------------------------------------------------------
class Overlay(BaseModel):
    """Copy `from` (any path) to `to` = 'repo:<path>' (the run's worktree) or 'home:<path>' (its clean home)."""

    model_config = ConfigDict(validate_by_name=True, serialize_by_alias=True)
    source: str = Field(alias="from")
    to: str

    @field_validator("to")
    @classmethod
    def _scoped(cls, value: str) -> str:
        scope, _, rel = value.partition(":")
        if scope not in ("repo", "home") or not rel.strip("/"):
            raise ValueError("overlay target must be 'repo:<path>' or 'home:<path>'")
        if ".." in PurePosixPath(rel).parts:
            raise ValueError("overlay target may not contain '..'")
        return value

    @property
    def scope(self) -> str:
        return self.to.partition(":")[0]

    @property
    def rel(self) -> str:
        return self.to.partition(":")[2].strip("/")


class Contestant(BaseModel):
    name: str
    harness: HarnessName
    model: str = ""
    baseline: Literal["clean", "real"] = "real"
    overlays: list[Overlay] = Field(default_factory=list)
    strategy: str = ""
    argv: list[str] = Field(default_factory=list)  # harness="command": {prompt} {workspace} {model} {run_dir}

    @field_validator("name")
    @classmethod
    def _slug(cls, value: str) -> str:
        if not NAME.fullmatch(value):
            raise ValueError("name must be lowercase letters, digits, '.', '_' or '-' (max 40)")
        return value

    @model_validator(mode="after")
    def _consistent(self) -> Contestant:
        if self.harness == "command" and not self.argv:
            raise ValueError("harness 'command' needs argv")
        if self.baseline == "real" and any(o.scope == "home" for o in self.overlays):
            raise ValueError(f"{self.name}: home: overlays need baseline='clean' (a real home is never modified)")
        return self


class Check(BaseModel):
    name: str
    cmd: str


class JudgeSpec(BaseModel):
    harness: Literal["claude", "codex", "opencode", "command", "none"] = "claude"
    model: str = ""
    argv: list[str] = Field(default_factory=list)  # harness="command": {prompt_file} {output_file} {schema_file}
    timeout_sec: int = 600


class Spec(BaseModel):
    task: str
    objective: str = "quality"  # quality | elegance | speed | tokens | cost | any custom rubric text
    repeats: int = Field(1, ge=1, le=20)
    checks: list[Check] = Field(default_factory=list)
    contestants: list[Contestant] = Field(min_length=1, max_length=6)
    judge: JudgeSpec = Field(default_factory=JudgeSpec)
    ship: bool = False
    base_ref: str = "HEAD"
    max_parallel: int = Field(4, ge=1, le=16)
    run_timeout_sec: int = 1800
    check_timeout_sec: int = 600

    @model_validator(mode="after")
    def _rules(self) -> Spec:
        names = [c.name for c in self.contestants]
        if len(set(names)) != len(names):
            raise ValueError("contestant names must be unique")
        if self.judge.harness == "command" and not self.judge.argv:
            raise ValueError("judge harness 'command' needs argv")
        return self

    @property
    def judged(self) -> bool:
        return self.objective not in METRIC_OBJECTIVES and self.judge.harness != "none"


# ---- runtime ------------------------------------------------------------------------------------
class FileChange(BaseModel):
    path: str
    status: str  # git name-status letter: A, M, D, R...
    added: int = 0
    removed: int = 0


class Snapshot(BaseModel):
    commit: str
    patch_hash: str
    patch_path: str
    files: list[FileChange] = Field(default_factory=list)

    @property
    def lines_changed(self) -> int:
        return sum(f.added + f.removed for f in self.files)


class CheckResult(BaseModel):
    name: str
    cmd: str
    status: CheckStatus
    exit_code: int | None = None
    duration_ms: int
    tail: str = ""


class CheckReport(BaseModel):
    commit: str
    results: list[CheckResult] = Field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(r.status == "passed" for r in self.results)

    def status_of(self, name: str) -> CheckStatus | None:
        return next((r.status for r in self.results if r.name == name), None)


class Gate(BaseModel):
    kind: str
    severity: GateSeverity
    detail: str = ""


class Metrics(BaseModel):
    wall_ms: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: float | None = None
    turns: int | None = None

    @property
    def total_tokens(self) -> int | None:
        if self.input_tokens is None and self.output_tokens is None:
            return None
        return (self.input_tokens or 0) + (self.output_tokens or 0)


class Score(BaseModel):
    score: float = Field(ge=0, le=10)
    reasons: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)


class Verdict(BaseModel):
    winner: Literal["A", "B", "tie"]
    confidence: float = 0.5
    reasons: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)


class Run(BaseModel):
    id: str  # "<contestant>-<repeat>"
    contestant: str
    repeat: int
    state: Literal["pending", "running", "done", "failed"] = "pending"
    workspace: str = ""
    base_commit: str = ""  # arena base + this run's repo overlays
    run_dir: str = ""
    exit_status: str = ""  # agent process: passed | failed | error | timeout
    snapshot: Snapshot | None = None
    checks: CheckReport | None = None
    gates: list[Gate] = Field(default_factory=list)
    metrics: Metrics = Field(default_factory=Metrics)
    score: Score | None = None
    error: str = ""

    @property
    def eligible(self) -> bool:
        """Produced a non-empty change and tripped no disqualifying gate (regressions are gates)."""
        return (
            self.state == "done"
            and self.snapshot is not None
            and bool(self.snapshot.files)
            and not any(g.severity == "disqualify" for g in self.gates)
        )


class Match(BaseModel):
    """One final-round judge call; run `first` was shown as A."""

    first: str
    second: str
    verdict: Verdict
    run_dir: str

    @property
    def winner(self) -> str | None:
        return {"A": self.first, "B": self.second}.get(self.verdict.winner)


class ContestantStats(BaseModel):
    name: str
    runs: int
    eligible: int
    pass_rate: float
    median_score: float | None = None
    median_tokens: float | None = None
    median_wall_ms: float | None = None
    median_cost_usd: float | None = None
    median_lines: float | None = None
    gate_hits: dict[str, int] = Field(default_factory=dict)


class Scorecard(BaseModel):
    objective: str
    stats: list[ContestantStats]
    winner: str | None = None
    winner_run: str | None = None
    verdict: str
    notes: list[str] = Field(default_factory=list)


class Arena(BaseModel):
    id: str
    spec: Spec
    repo_root: str
    base_commit: str
    worktree_root: str
    status: Literal["running", "done", "failed"] = "running"
    runs: dict[str, Run] = Field(default_factory=dict)
    baseline: CheckReport | None = None
    finals: list[Match] = Field(default_factory=list)
    scorecard: Scorecard | None = None
    error: str = ""
    created_at: str
    finished_at: str | None = None

    def contestant(self, name: str) -> Contestant:
        return next(c for c in self.spec.contestants if c.name == name)


class Job(BaseModel):
    id: str
    op: str
    status: Literal["running", "done", "failed"] = "running"
    pid: int
    started_at: str
    ended_at: str | None = None
    progress: str = ""
    error: str | None = None
```

- [ ] **Step 4: Rewrite `tests/conftest.py`** (shared fixtures for all later tasks):

```python
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
    return {"name": name, "harness": "command", "argv": [sys.executable, str(fakes["agent"]), "{workspace}", "{run_dir}"], **kw}


def command_judge(fakes: dict[str, Path]) -> dict:
    return {"harness": "command", "argv": [sys.executable, str(fakes["judge"]), "{prompt_file}", "{output_file}"]}
```

- [ ] **Step 5: Run.** `uv run pytest tests/test_models.py -q`. Expected: PASS (5 tests).

- [ ] **Step 6: Commit**

```bash
git add agents_arena_mcp/models.py tests/conftest.py tests/test_models.py
git commit -qm "feat(models): v0.3 spec and runtime models (contestants, overlays, runs, scorecard)"
```

### Task 3: Harness adapters

**Files:**
- Create: `agents_arena_mcp/harness.py`
- Test: `tests/test_harness.py`

- [ ] **Step 1: Write the failing test** `tests/test_harness.py`

```python
import json
from pathlib import Path

import pytest

from agents_arena_mcp import harness
from agents_arena_mcp.models import Contestant, JudgeSpec


def c(**kw):
    return Contestant.model_validate({"name": "x", "harness": "claude"} | kw)


def test_claude_clean_needs_a_token(monkeypatch):
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(harness.shutil, "which", lambda name: f"/bin/{name}")
    assert any("setup-token" in p for p in harness.get("claude").preflight(c(baseline="clean")))
    assert harness.get("claude").preflight(c(baseline="real")) == []
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "t")
    assert harness.get("claude").preflight(c(baseline="clean")) == []


def test_clean_envs_redirect_home_and_seed_codex_auth(tmp_path, monkeypatch):
    for var in ("UV_CACHE_DIR", "XDG_CACHE_HOME", "npm_config_cache"):
        monkeypatch.delenv(var, raising=False)
    real = tmp_path / "real"
    (real / ".codex").mkdir(parents=True)
    (real / ".codex" / "auth.json").write_text("{}")
    monkeypatch.setenv("HOME", str(real))
    home = tmp_path / "clean"
    env = harness.get("codex").clean_env(home)
    assert env["HOME"] == str(home) and env["CODEX_HOME"] == str(home / ".codex")
    assert (home / ".codex" / "auth.json").exists()
    assert env["UV_CACHE_DIR"] == str(real / ".cache" / "uv") and env["XDG_CACHE_HOME"] == str(real / ".cache")
    assert harness.get("claude").clean_env(home)["CLAUDE_CONFIG_DIR"] == str(home / ".claude")
    oc = harness.get("opencode").clean_env(home)
    assert oc["XDG_CONFIG_HOME"] == str(home / ".config") and oc["XDG_DATA_HOME"] == str(home / ".local" / "share")


def test_agent_argv_shapes():
    assert harness.get("claude").agent_argv(c(model="sonnet"), "P", Path("/r"), Path("/w"))[:3] == ["claude", "-p", "P"]
    codex = harness.get("codex").agent_argv(c(harness="codex"), "P", Path("/r"), Path("/w"))
    assert codex[:2] == ["codex", "exec"] and codex[-1] == "P" and "--model" not in codex
    oc = harness.get("opencode").agent_argv(c(harness="opencode", model="openrouter/x"), "P", Path("/r"), Path("/w"))
    assert "--standalone" in oc and oc[oc.index("-m") + 1] == "openrouter/x"
    cmd = harness.get("command").agent_argv(c(harness="command", argv=["run", "{workspace}", "{prompt}"]), "P", Path("/r"), Path("/w"))
    assert cmd == ["run", "/w", "P"]


def test_opencode_requires_model(monkeypatch):
    monkeypatch.setattr(harness.shutil, "which", lambda name: f"/bin/{name}")
    assert any("explicit model" in p for p in harness.get("opencode").preflight(c(harness="opencode")))


def test_metrics_parsing():
    claude_out = json.dumps({"type": "result", "usage": {"input_tokens": 5, "cache_read_input_tokens": 100, "cache_creation_input_tokens": 10, "output_tokens": 7}, "total_cost_usd": 0.02, "num_turns": 3})
    m = harness.get("claude").metrics(claude_out, cwd=Path("."), env=None)
    assert (m.input_tokens, m.output_tokens, m.cost_usd, m.turns) == (115, 7, 0.02, 3)
    codex_out = "\n".join(json.dumps(e) for e in [{"type": "thread.started"}, {"type": "turn.completed", "usage": {"input_tokens": 50, "output_tokens": 4}}, {"type": "turn.completed", "usage": {"input_tokens": 10, "output_tokens": 1}}])
    m = harness.get("codex").metrics(codex_out, cwd=Path("."), env=None)
    assert (m.input_tokens, m.output_tokens, m.cost_usd, m.turns) == (60, 5, None, 2)


def test_opencode_metrics_come_from_session_export(monkeypatch):
    calls = []

    def fake_run(argv, cwd, timeout, **kw):
        calls.append(argv)
        info = {"info": {"tokens": {"input": 80, "output": 9, "cache": {"read": 20, "write": 0}}, "cost": 0.003}, "messages": []}
        return harness.proc.ProcResult("passed", 0, json.dumps(info), "", 5)

    monkeypatch.setattr(harness.proc, "run", fake_run)
    stdout = "\n".join(json.dumps(e) for e in [{"type": "step_start", "sessionID": "ses_1"}, {"type": "text", "sessionID": "ses_1"}])
    m = harness.get("opencode").metrics(stdout, cwd=Path("."), env=None)
    assert calls[0][:4] == ["opencode", "session", "export", "ses_1"]
    assert (m.input_tokens, m.output_tokens, m.cost_usd, m.turns) == (100, 9, 0.003, 1)


def test_judge_argv_isolates(tmp_path):
    files = harness.JudgeFiles(prompt_file="/p", output_file="/o", schema_file="/s", schema_json="{}")
    claude = harness.get("claude").judge_argv(JudgeSpec(harness="claude"), "P", files)
    assert claude[claude.index("--setting-sources") + 1] == "" and claude[claude.index("--tools") + 1] == ""
    codex = harness.get("codex").judge_argv(JudgeSpec(harness="codex"), "P", files)
    assert {"--ignore-user-config", "--ephemeral", "read-only"} <= set(codex)


def test_unknown_harness():
    with pytest.raises(KeyError):
        harness.get("nope")
```

- [ ] **Step 2: Run.** `uv run pytest tests/test_harness.py -q`. Expected: FAIL (`ImportError: cannot import name 'harness'`).

- [ ] **Step 3: Write `agents_arena_mcp/harness.py`**

```python
"""Per-harness adapters: run an agent or judge headless, isolate it, read its metrics.

Every recipe below comes from docs/v0.3-isolation-spike.md:
- clean = a fresh HOME (plus the harness's config vars) with auth seeded; tool caches stay on real paths.
- real  = the user's actual home, untouched (never copied: copies lose keychain/db auth).
"""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from agents_arena_mcp import proc
from agents_arena_mcp.models import Contestant, JudgeSpec, Metrics

TOKEN_VARS = ("CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY")


@dataclass(frozen=True)
class JudgeFiles:
    prompt_file: str
    output_file: str
    schema_file: str
    schema_json: str


def fill(parts: list[str], values: dict[str, str]) -> list[str]:
    out = []
    for part in parts:
        for key, value in values.items():
            part = part.replace("{" + key + "}", value)
        out.append(part)
    return out


def _json_lines(stdout: str) -> list[dict]:
    events = []
    for line in stdout.splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return events


def _clean_base(home: Path) -> dict[str, str]:
    real = Path.home()
    home.mkdir(parents=True, exist_ok=True)
    env = {
        "HOME": str(home),
        # Keep package caches shared so runs don't re-download dependencies.
        "UV_CACHE_DIR": os.environ.get("UV_CACHE_DIR", str(real / ".cache" / "uv")),
        "npm_config_cache": os.environ.get("npm_config_cache", str(real / ".npm")),
        "XDG_CACHE_HOME": os.environ.get("XDG_CACHE_HOME", str(real / ".cache")),
    }
    if (real / ".gitconfig").exists():
        env["GIT_CONFIG_GLOBAL"] = str(real / ".gitconfig")
    return env


class Adapter:
    name = ""
    family = ""
    executable = ""

    def agent_argv(self, c: Contestant, prompt: str, run_dir: Path, workspace: Path) -> list[str]:
        raise NotImplementedError

    def judge_argv(self, j: JudgeSpec, prompt: str, files: JudgeFiles) -> list[str]:
        raise NotImplementedError

    def clean_env(self, home: Path) -> dict[str, str]:
        return _clean_base(home)

    def preflight(self, c: Contestant) -> list[str]:
        return [] if shutil.which(self.executable) else [f"`{self.executable}` is not installed or not on PATH"]

    def judge_preflight(self, j: JudgeSpec) -> list[str]:
        return [] if shutil.which(self.executable) else [f"judge `{self.executable}` is not installed or not on PATH"]

    def metrics(self, stdout: str, *, cwd: Path, env: dict[str, str] | None) -> Metrics:
        """Generic: sum `usage` blocks and take the last `total_cost_usd` found in JSON lines."""
        m = Metrics()
        for e in _json_lines(stdout):
            usage = e.get("usage")
            if isinstance(usage, dict):
                m.input_tokens = (m.input_tokens or 0) + int(usage.get("input_tokens") or 0)
                m.output_tokens = (m.output_tokens or 0) + int(usage.get("output_tokens") or 0)
            if isinstance(e.get("total_cost_usd"), int | float):
                m.cost_usd = float(e["total_cost_usd"])
        return m


class Claude(Adapter):
    name, family, executable = "claude", "anthropic", "claude"

    def agent_argv(self, c, prompt, run_dir, workspace):
        argv = ["claude", "-p", prompt, "--output-format", "json", "--permission-mode", "acceptEdits",
                "--allowedTools", "Bash,Edit,Write,Read,Grep,Glob"]  # fmt: skip
        return argv + (["--model", c.model] if c.model else [])

    def judge_argv(self, j, prompt, files):
        argv = ["claude", "-p", prompt, "--output-format", "json", "--json-schema", files.schema_json,
                "--setting-sources", "", "--tools", ""]  # fmt: skip
        return argv + (["--model", j.model] if j.model else [])

    def clean_env(self, home):
        env = _clean_base(home)
        (home / ".claude").mkdir(parents=True, exist_ok=True)
        env["CLAUDE_CONFIG_DIR"] = str(home / ".claude")
        return env  # auth: CLAUDE_CODE_OAUTH_TOKEN / ANTHROPIC_API_KEY pass through from the environment

    def preflight(self, c):
        problems = super().preflight(c)
        if c.baseline == "clean" and not any(os.environ.get(v) for v in TOKEN_VARS):
            problems.append(
                "clean claude can't use your keychain login: run `claude setup-token` once and export "
                "CLAUDE_CODE_OAUTH_TOKEN (or set ANTHROPIC_API_KEY)"
            )
        return problems

    def metrics(self, stdout, *, cwd, env):
        result = next((e for e in reversed(_json_lines(stdout)) if "usage" in e), None)
        if result is None:
            return Metrics()
        u = result["usage"]
        tokens_in = sum(int(u.get(k) or 0) for k in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))
        return Metrics(
            input_tokens=tokens_in,
            output_tokens=int(u.get("output_tokens") or 0),
            cost_usd=result.get("total_cost_usd"),
            turns=result.get("num_turns"),
        )


class Codex(Adapter):
    name, family, executable = "codex", "openai", "codex"

    def agent_argv(self, c, prompt, run_dir, workspace):
        argv = ["codex", "exec", "--skip-git-repo-check", "--sandbox", "workspace-write", "--json"]
        return argv + (["--model", c.model] if c.model else []) + [prompt]

    def judge_argv(self, j, prompt, files):
        argv = ["codex", "exec", "--skip-git-repo-check", "--ignore-user-config", "--ephemeral",
                "--sandbox", "read-only", "--output-schema", files.schema_file,
                "--output-last-message", files.output_file]  # fmt: skip
        return argv + (["--model", j.model] if j.model else []) + [prompt]

    def clean_env(self, home):
        env = _clean_base(home)
        codex_home = home / ".codex"
        codex_home.mkdir(parents=True, exist_ok=True)
        auth = Path.home() / ".codex" / "auth.json"
        if auth.exists():
            shutil.copy2(auth, codex_home / "auth.json")  # deleted with the run's home (workspace.destroy)
        env["CODEX_HOME"] = str(codex_home)
        return env

    def preflight(self, c):
        problems = super().preflight(c)
        if c.baseline == "clean" and not (Path.home() / ".codex" / "auth.json").exists() and not os.environ.get("OPENAI_API_KEY"):
            problems.append("clean codex needs ~/.codex/auth.json (run `codex login`) or OPENAI_API_KEY")
        return problems

    def metrics(self, stdout, *, cwd, env):
        m = Metrics(turns=0)
        for e in _json_lines(stdout):
            if e.get("type") == "turn.completed" and isinstance(e.get("usage"), dict):
                m.turns = (m.turns or 0) + 1
                m.input_tokens = (m.input_tokens or 0) + int(e["usage"].get("input_tokens") or 0)
                m.output_tokens = (m.output_tokens or 0) + int(e["usage"].get("output_tokens") or 0)
        return m  # codex reports no dollar cost


class OpenCode(Adapter):
    name, family, executable = "opencode", "opencode", "opencode"

    def agent_argv(self, c, prompt, run_dir, workspace):
        return ["opencode", "run", "--standalone", "--auto", "--format", "json", "-m", c.model, prompt]

    def judge_argv(self, j, prompt, files):
        return ["opencode", "run", "--standalone", "--format", "json", "-m", j.model, prompt]

    def clean_env(self, home):
        env = _clean_base(home)
        env["XDG_CONFIG_HOME"] = str(home / ".config")
        env["XDG_DATA_HOME"] = str(home / ".local" / "share")
        for key in ("XDG_CONFIG_HOME", "XDG_DATA_HOME"):
            Path(env[key]).mkdir(parents=True, exist_ok=True)
        return env  # stored logins live in opencode.db; clean runs only see env-keyed providers

    def preflight(self, c):
        problems = super().preflight(c)
        if not c.model:
            problems.append("opencode needs an explicit model (provider/model), e.g. openrouter/openai/gpt-5-mini")
        return problems

    def judge_preflight(self, j):
        problems = super().judge_preflight(j)
        if not j.model:
            problems.append("opencode judge needs an explicit model (provider/model)")
        return problems

    def metrics(self, stdout, *, cwd, env):
        events = _json_lines(stdout)
        session = next((e["sessionID"] for e in events if e.get("sessionID")), None)
        turns = sum(1 for e in events if e.get("type") == "step_start")
        if not session:
            return Metrics(turns=turns or None)
        out = proc.run(["opencode", "session", "export", session, "--standalone"], cwd, 60, env=env)
        try:
            info = json.loads(out.stdout[out.stdout.find("{") :])["info"]
        except (ValueError, KeyError):
            return Metrics(turns=turns or None)
        t = info.get("tokens") or {}
        cache = t.get("cache") or {}
        return Metrics(
            input_tokens=int(t.get("input") or 0) + int(cache.get("read") or 0) + int(cache.get("write") or 0),
            output_tokens=int(t.get("output") or 0) + int(t.get("reasoning") or 0),
            cost_usd=info.get("cost"),
            turns=turns or None,
        )


class Command(Adapter):
    """Any CLI given as argv in the spec. Used by tests and for harnesses without an adapter yet."""

    name, family = "command", "command"

    def agent_argv(self, c, prompt, run_dir, workspace):
        return fill(c.argv, {"prompt": prompt, "workspace": str(workspace), "model": c.model, "run_dir": str(run_dir)})

    def judge_argv(self, j, prompt, files):
        values = {"prompt": prompt, "prompt_file": files.prompt_file, "output_file": files.output_file,
                  "schema_file": files.schema_file, "model": j.model}  # fmt: skip
        return fill(j.argv, values)

    def preflight(self, c):
        return [] if shutil.which(c.argv[0]) else [f"`{c.argv[0]}` not found"]

    def judge_preflight(self, j):
        return [] if shutil.which(j.argv[0]) else [f"judge `{j.argv[0]}` not found"]


ADAPTERS: dict[str, Adapter] = {a.name: a for a in (Claude(), Codex(), OpenCode(), Command())}


def get(name: str) -> Adapter:
    return ADAPTERS[name]
```

- [ ] **Step 4: Run.** `uv run pytest tests/test_harness.py -q`. Expected: PASS (8 tests).

- [ ] **Step 5: Commit**

```bash
git add agents_arena_mcp/harness.py tests/test_harness.py
git commit -qm "feat(harness): adapters for claude, codex, opencode and command with clean/real isolation and metrics"
```

### Task 4: Workspace (worktree + home + overlays + snapshot)

**Files:**
- Rewrite: `agents_arena_mcp/workspace.py`
- Modify: `agents_arena_mcp/git.py` (add `commit_patch`)
- Test: `tests/test_workspace.py` (and keep `tests/test_snapshot_race.py` green)

- [ ] **Step 1: Write the failing test** `tests/test_workspace.py`

```python
from pathlib import Path

from conftest import git

from agents_arena_mcp import workspace
from agents_arena_mcp.models import Arena, Overlay, Run, Spec
from agents_arena_mcp.store import Store


def make_arena(repo: Path, tmp_path: Path) -> Arena:
    base = git(repo, "rev-parse", "HEAD").strip()
    spec = Spec.model_validate({"task": "t", "contestants": [{"name": "a", "harness": "claude"}]})
    return Arena(id="arena1", spec=spec, repo_root=str(repo), base_commit=base, worktree_root=str(tmp_path / "wt"), created_at="now")


def test_overlays_land_in_repo_and_home_and_are_not_counted(repo, tmp_path):
    arena = make_arena(repo, tmp_path)
    run = Run(id="a-1", contestant="a", repeat=1)
    src = tmp_path / "skill-v2"
    src.mkdir()
    (src / "SKILL.md").write_text("v2\n")
    ws = workspace.create(arena, run)
    home = workspace.home_dir(arena, run)
    workspace.apply_overlays(ws, home, [Overlay.model_validate({"from": str(src), "to": "repo:.claude/skills/foo"}),
                                        Overlay.model_validate({"from": str(src / "SKILL.md"), "to": "home:.codex/skills/s/SKILL.md"})])
    assert (ws / ".claude/skills/foo/SKILL.md").read_text() == "v2\n"
    assert (home / ".codex/skills/s/SKILL.md").exists()
    run.base_commit = workspace.overlay_base(arena, run, ws, has_repo_overlays=True)
    (ws / "app.py").write_text("def value():\n    return 2\n")
    snap = workspace.snapshot(Store(repo), arena, run, ws)
    assert [f.path for f in snap.files] == ["app.py"]  # the overlay is part of the base, not the contestant's change
    workspace.destroy(arena, run.model_copy(update={"workspace": str(ws)}))
    assert not (Path(arena.worktree_root) / "a-1").exists()
    assert len(git(repo, "worktree", "list").splitlines()) == 1


def test_commit_patch_builds_a_branch_commit_without_checkout(repo, tmp_path):
    arena = make_arena(repo, tmp_path)
    run = Run(id="a-1", contestant="a", repeat=1, base_commit=arena.base_commit)
    ws = workspace.create(arena, run)
    (ws / "new.py").write_text("X = 1\n")
    snap = workspace.snapshot(Store(repo), arena, run, ws)
    from agents_arena_mcp import git as g

    commit = g.commit_patch(repo, arena.base_commit, Path(snap.patch_path), "arena: a-1")
    assert git(repo, "show", f"{commit}:new.py") == "X = 1\n"
    assert git(repo, "rev-parse", "--abbrev-ref", "HEAD").strip() == "main"
```

- [ ] **Step 2: Run.** `uv run pytest tests/test_workspace.py -q`. Expected: FAIL (`AttributeError: ... has no attribute 'home_dir'`, or ImportError).

- [ ] **Step 3: Add `commit_patch` to `agents_arena_mcp/git.py`** (append at the end):

```python
def commit_patch(root: Path, base: str, patch_path: Path, message: str) -> str:
    """Commit `patch` on top of `base` using a temporary index: no checkout, the user's tree is untouched."""
    with tempfile.TemporaryDirectory() as tmp:
        env = {"GIT_INDEX_FILE": str(Path(tmp) / "index"), **IDENTITY}
        git(root, "read-tree", base, env=env)
        git(root, "apply", "--cached", "--binary", str(patch_path), env=env)
        tree = text(root, "write-tree", env=env)
    return text(root, "commit-tree", tree, "-p", base, "-m", message, env=IDENTITY)
```

- [ ] **Step 4: Rewrite `agents_arena_mcp/workspace.py`**

```python
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
        dst = root / overlay.rel
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


def destroy(arena: Arena, run: Run) -> None:
    """Remove the worktree and the run's home, which may hold a copied auth file."""
    if run.workspace:
        git.worktree_remove(Path(arena.repo_root), Path(run.workspace))
    shutil.rmtree(Path(arena.worktree_root) / run.id, ignore_errors=True)
```

- [ ] **Step 5: Run.** `uv run pytest tests/test_workspace.py tests/test_snapshot_race.py -q`. Expected: PASS (3 tests).

- [ ] **Step 6: Commit**

```bash
git add agents_arena_mcp/workspace.py agents_arena_mcp/git.py tests/test_workspace.py
git commit -qm "feat(workspace): per-run worktree and clean home, overlays excluded from the diff, patch-to-commit"
```

### Task 5: Checks and gates on runs

**Files:**
- Modify: `agents_arena_mcp/checks.py`
- Test: `tests/test_checks.py`

- [ ] **Step 1: Write the failing test** `tests/test_checks.py`

```python
from pathlib import Path

from agents_arena_mcp import checks
from agents_arena_mcp.models import Check, CheckReport, CheckResult, FileChange, Run, Snapshot


def run_with(files, patch_text="", checks_report=None, tmp_path=Path("/tmp")):
    patch = tmp_path / "p.diff"
    patch.write_text(patch_text)
    snap = Snapshot(commit="c", patch_hash="h", patch_path=str(patch), files=files)
    return Run(id="a-1", contestant="a", repeat=1, state="done", snapshot=snap, checks=checks_report)


def kinds(gates):
    return {(g.kind, g.severity) for g in gates}


def test_gates(tmp_path):
    assert ("empty", "disqualify") in kinds(checks.gates(run_with([], tmp_path=tmp_path), None))
    deleted = run_with([FileChange(path="tests/test_app.py", status="D")], tmp_path=tmp_path)
    assert ("test_deleted", "disqualify") in kinds(checks.gates(deleted, None))
    ci = run_with([FileChange(path=".github/workflows/ci.yml", status="M")], tmp_path=tmp_path)
    assert ("protected_path", "disqualify") in kinds(checks.gates(ci, None))
    skill = run_with([FileChange(path=".claude/skills/foo/SKILL.md", status="M")], tmp_path=tmp_path)
    assert ("agent_config_edited", "needs_human") in kinds(checks.gates(skill, None))
    nested = run_with([FileChange(path="pkg/AGENTS.md", status="M")], tmp_path=tmp_path)
    assert ("agent_config_edited", "needs_human") in kinds(checks.gates(nested, None))
    skip = run_with([FileChange(path="tests/test_x.py", status="A")], "+@pytest.mark.skip\n+def test_x(): pass\n", tmp_path=tmp_path)
    assert ("skip_marker_added", "needs_human") in kinds(checks.gates(skip, None))


def test_regressions_vs_baseline(tmp_path):
    base = CheckReport(commit="b", results=[CheckResult(name="t", cmd="x", status="passed", duration_ms=1),
                                             CheckResult(name="l", cmd="y", status="failed", duration_ms=1)])
    mine = CheckReport(commit="c", results=[CheckResult(name="t", cmd="x", status="failed", duration_ms=1),
                                             CheckResult(name="l", cmd="y", status="failed", duration_ms=1)])
    run = run_with([FileChange(path="app.py", status="M")], checks_report=mine, tmp_path=tmp_path)
    got = kinds(checks.gates(run, base))
    assert ("check_regression", "disqualify") in got and ("check_failing_on_base_too", "info") in got


def test_run_checks_records_missing_tool_and_timeout(tmp_path):
    report = checks.run_checks([Check(name="missing", cmd="definitely-not-a-tool-xyz"), Check(name="slow", cmd="sleep 5")],
                               tmp_path, "c", timeout=1, owner="t")
    assert [r.status for r in report.results] == ["error", "timeout"]
```

- [ ] **Step 2: Run.** `uv run pytest tests/test_checks.py -q`. Expected: FAIL (`ImportError: cannot import name 'checks'`).

- [ ] **Step 3: Rewrite `agents_arena_mcp/checks.py`**

```python
"""Checks, the base-commit baseline, and deterministic gates (including reward-hacking tripwires).

Trust model: checks and contestants run agent-written code on the host with your privileges, like
`make test` on an untrusted branch. Check commands come only from the spec.
"""

from __future__ import annotations

import re
import tempfile
from pathlib import Path

from agents_arena_mcp import git, proc
from agents_arena_mcp.models import Arena, Check, CheckReport, CheckResult, Gate, Run

PROTECTED = (".github/workflows/", ".gitlab-ci.yml", ".agents-arena/")
AGENT_CONFIG_DIRS = (".claude/", ".codex/", ".opencode/", ".agents/")
AGENT_CONFIG_FILES = ("AGENTS.md", "CLAUDE.md")
SECRET = (r"(^|/)\.env($|\.)", r"(^|/)secrets?(/|\.[a-z0-9]+$|$)", r"(^|/)credentials?(/|\.[a-z0-9]+$|$)",
          r"private[_-]?key", r"(^|/)id_(rsa|ed25519)")  # fmt: skip
TEST_PATH = re.compile(r"(^|/)(tests?|__tests__|spec)/|(^|/)test_[^/]+\.py$|_test\.(py|go)$|\.(test|spec)\.[jt]sx?$")
TEST_CONFIG = re.compile(r"(^|/)(conftest\.py|pytest\.ini|tox\.ini|setup\.cfg|jest\.config\.[a-z]+|vitest\.config\.[a-z]+)$")
SKIP_MARKER = re.compile(r"@pytest\.mark\.(skip|xfail)|pytest\.skip\(|@unittest\.skip|\b(it|test|describe)\.skip\(|\bxit\(|t\.Skip\(")
TRIVIAL_ASSERT = re.compile(r"^\s*assert\s+(True|1)\s*$|expect\(true\)\.toBe\(true\)")


def run_checks(specs: list[Check], workdir: Path, commit: str, timeout: int, owner: str) -> CheckReport:
    results = []
    for spec in specs:
        out = proc.shell(spec.cmd, workdir, timeout, owner=owner)
        results.append(CheckResult(name=spec.name, cmd=spec.cmd, status=out.status,  # type: ignore[arg-type]
                                   exit_code=out.exit_code, duration_ms=out.wall_ms,
                                   tail=proc.tail(out.stdout + out.stderr, 2000)))  # fmt: skip
    return CheckReport(commit=commit, results=results)


def baseline(arena: Arena) -> CheckReport:
    """Run the spec's checks once on the base commit, in a throwaway worktree."""
    root = Path(arena.repo_root)
    with tempfile.TemporaryDirectory(prefix="arena-baseline-") as tmp:
        path = Path(tmp) / "base"
        git.worktree_add(root, path, arena.base_commit)
        try:
            return run_checks(arena.spec.checks, path, arena.base_commit, arena.spec.check_timeout_sec, arena.id)
        finally:
            git.worktree_remove(root, path)


def gates(run: Run, base: CheckReport | None) -> list[Gate]:
    snap = run.snapshot
    if snap is None or not snap.files:
        return [Gate(kind="empty", severity="disqualify", detail="no changes")]
    found: list[Gate] = []
    for f in snap.files:
        if f.status == "D" and TEST_PATH.search(f.path):
            found.append(Gate(kind="test_deleted", severity="disqualify", detail=f.path))
        if any(f.path.startswith(p) or f.path == p.rstrip("/") for p in PROTECTED):
            found.append(Gate(kind="protected_path", severity="disqualify", detail=f.path))
        if f.path.startswith(AGENT_CONFIG_DIRS) or Path(f.path).name in AGENT_CONFIG_FILES:
            found.append(Gate(kind="agent_config_edited", severity="needs_human", detail=f.path))
        if any(re.search(p, f.path, re.IGNORECASE) for p in SECRET):
            found.append(Gate(kind="secret_path", severity="needs_human", detail=f.path))
        if TEST_CONFIG.search(f.path):
            found.append(Gate(kind="test_config_changed", severity="needs_human", detail=f.path))
        elif f.status == "M" and TEST_PATH.search(f.path):
            found.append(Gate(kind="existing_test_edited", severity="info", detail=f.path))
    for line in _added_lines(Path(snap.patch_path)):
        if SKIP_MARKER.search(line):
            found.append(Gate(kind="skip_marker_added", severity="needs_human", detail=line.strip()[:120]))
        elif TRIVIAL_ASSERT.search(line):
            found.append(Gate(kind="trivial_assert_added", severity="needs_human", detail=line.strip()[:120]))
    if run.checks:
        for result in run.checks.results:
            before = base.status_of(result.name) if base else None
            if result.status != "passed" and before in ("passed", None):
                found.append(Gate(kind="check_regression", severity="disqualify", detail=result.name))
            elif result.status != "passed":
                found.append(Gate(kind="check_failing_on_base_too", severity="info", detail=result.name))
    return found


def _added_lines(patch_path: Path) -> list[str]:
    lines = patch_path.read_bytes().decode("utf-8", "replace").splitlines()
    return [line[1:] for line in lines if line.startswith("+") and not line.startswith("+++")]


def failing_count(run: Run) -> int:
    return sum(1 for r in (run.checks.results if run.checks else []) if r.status != "passed")
```

- [ ] **Step 4: Run.** `uv run pytest tests/test_checks.py -q`. Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add agents_arena_mcp/checks.py tests/test_checks.py
git commit -qm "feat(checks): gates on runs, agent-config edits need review, regressions vs baseline"
```

---

## Chunk 2: Pipeline (runs × repeats, isolation, metrics)

### Task 6: Brief template and the pipeline's run phase

**Files:**
- Rewrite: `agents_arena_mcp/data/brief.md.tmpl`
- Create: `agents_arena_mcp/pipeline.py`
- Test: `tests/test_pipeline.py`

- [ ] **Step 1: Write `agents_arena_mcp/data/brief.md.tmpl`**

```
$task
$strategy
Rules:
- Work only in the current directory. Do not commit; the arena snapshots your changes.
- Do not delete or weaken tests, and do not edit CI or agent configuration (.claude/, .codex/, AGENTS.md, ...).
- Do not touch secrets or credentials.
- Prefer regression tests as evidence over claims.
```

- [ ] **Step 2: (done in Task 1: `jobs.new_run_id` exists.)**

- [ ] **Step 3: Write the failing test** `tests/test_pipeline.py`

```python
import json
import sys
import time
from pathlib import Path

import pytest
from conftest import command_contestant, git

from agents_arena_mcp import pipeline
from agents_arena_mcp.errors import ArenaError
from agents_arena_mcp.models import Spec
from agents_arena_mcp.store import Store


def spec(fakes, **kw):
    data = {"task": "make value() return the contestant name", "repeats": 2, "judge": {"harness": "none"},
            "contestants": [command_contestant(fakes, "a"), command_contestant(fakes, "b")]}  # fmt: skip
    return Spec.model_validate(data | kw)


def test_runs_every_contestant_times_repeats_and_cleans_up(repo, fakes):
    store = Store(repo)
    arena = pipeline.create(store, spec(fakes))
    pipeline.execute(store, arena.id, progress=lambda m: None)
    done = store.load(arena.id)
    assert done.status == "done" and sorted(done.runs) == ["a-1", "a-2", "b-1", "b-2"]
    for run in done.runs.values():
        assert run.state == "done" and [f.path for f in run.snapshot.files] == ["app.py"]
        assert run.metrics.total_tokens == 120 and run.metrics.cost_usd == 0.01 and run.metrics.wall_ms is not None
    assert not Path(done.worktree_root).exists() or not any(Path(done.worktree_root).iterdir())
    assert len(git(repo, "worktree", "list").splitlines()) == 1
    assert git(repo, "for-each-ref", f"refs/arena/{arena.id}/").count("\n") == 5  # base + 4 runs


def test_clean_baseline_gets_its_own_home(repo, fakes, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "realhome"))
    store = Store(repo)
    s = spec(fakes, repeats=1, contestants=[command_contestant(fakes, "a", baseline="clean"), command_contestant(fakes, "b")])
    arena = pipeline.create(store, s)
    pipeline.execute(store, arena.id, progress=lambda m: None)
    runs = store.load(arena.id).runs
    seen_clean = json.loads((Path(runs["a-1"].run_dir) / "env.json").read_text())
    seen_real = json.loads((Path(runs["b-1"].run_dir) / "env.json").read_text())
    assert seen_clean["HOME"].endswith("/a-1/home")
    assert seen_real["HOME"] == str(tmp_path / "realhome")


def test_checks_baseline_and_regression_gate(repo, fakes, monkeypatch):
    plans = {"a": {"write": {"app.py": "def value():\n    return 2\n"}}, "b": {"write": {"app.py": "this is not python\n"}}}
    monkeypatch.setenv("FAKE_PLAN", json.dumps(plans))
    s = spec(fakes, repeats=1, checks=[{"name": "imports", "cmd": f"{sys.executable} -c 'import app'"}])
    store = Store(repo)
    arena = pipeline.create(store, s)
    pipeline.execute(store, arena.id, progress=lambda m: None)
    done = store.load(arena.id)
    assert done.baseline.results[0].status == "passed"
    assert done.runs["a-1"].eligible and not done.runs["b-1"].eligible
    assert any(g.kind == "check_regression" for g in done.runs["b-1"].gates)


def test_runs_execute_in_parallel(repo, fakes, monkeypatch):
    monkeypatch.setenv("FAKE_SLEEP", "1")
    store = Store(repo)
    arena = pipeline.create(store, spec(fakes, repeats=2, max_parallel=4))
    started = time.monotonic()
    pipeline.execute(store, arena.id, progress=lambda m: None)
    assert time.monotonic() - started < 3.5


def test_preflight_fails_before_creating_anything(repo, fakes):
    bad = spec(fakes, contestants=[{"name": "a", "harness": "command", "argv": ["definitely-not-installed-xyz"]}])
    with pytest.raises(ArenaError, match="Preflight failed"):
        pipeline.create(Store(repo), bad)
    assert not (repo / ".agents-arena" / "arenas").exists()


def test_agent_crash_is_recorded_not_fatal(repo, fakes):
    s = spec(fakes, repeats=1, contestants=[command_contestant(fakes, "a"),
                                            {"name": "b", "harness": "command", "argv": ["false"]}])  # fmt: skip
    store = Store(repo)
    arena = pipeline.create(store, s)
    pipeline.execute(store, arena.id, progress=lambda m: None)
    b = store.load(arena.id).runs["b-1"]
    assert b.state == "done" and b.exit_status == "failed" and any(g.kind == "empty" for g in b.gates)
```

- [ ] **Step 4: Run.** `uv run pytest tests/test_pipeline.py -q`. Expected: FAIL (ImportError: `pipeline`).

- [ ] **Step 5: Write `agents_arena_mcp/pipeline.py`** (judging and the scorecard are wired in Chunk 3; for now `execute` stops after the runs and marks the arena done):

```python
"""The engine behind arena_start: preflight -> baseline -> runs (contestant x repeat) -> judging -> scorecard."""

from __future__ import annotations

import re
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from string import Template

from agents_arena_mcp import checks, git, harness, proc, workspace
from agents_arena_mcp.config_data import data_text
from agents_arena_mcp.errors import ArenaError
from agents_arena_mcp.models import Arena, Contestant, Run, Spec
from agents_arena_mcp.store import Store, utc_now, write_atomic

Progress = Callable[[str], None]


def slugify(value: str, max_len: int = 32) -> str:
    value = re.sub(r"[^a-z0-9_]+", "-", value.strip().lower()).strip("-")
    return (value or "arena")[:max_len].rstrip("-")


def preflight(spec: Spec, repo_root: Path) -> list[str]:
    problems = []
    for c in spec.contestants:
        problems += [f"{c.name}: {p}" for p in harness.get(c.harness).preflight(c)]
        for o in c.overlays:
            if not Path(o.source).expanduser().exists():
                problems.append(f"{c.name}: overlay source not found: {o.source}")
    if spec.judged:
        problems += harness.get(spec.judge.harness).judge_preflight(spec.judge)
    try:
        git.rev_parse(repo_root, spec.base_ref)
    except ArenaError as exc:
        problems.append(str(exc))
    return problems


def create(store: Store, spec: Spec) -> Arena:
    problems = preflight(spec, store.repo_root)
    if problems:
        raise ArenaError("Preflight failed:\n- " + "\n- ".join(problems))
    store.init()
    root = store.repo_root
    base = git.rev_parse(root, spec.base_ref)
    arena_id = f"{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}-{slugify(spec.task)}"
    runs = {f"{c.name}-{i}": Run(id=f"{c.name}-{i}", contestant=c.name, repeat=i)
            for c in spec.contestants for i in range(1, spec.repeats + 1)}  # fmt: skip
    arena = Arena(id=arena_id, spec=spec, repo_root=str(root), base_commit=base,
                  worktree_root=str(workspace.default_root(root) / arena_id), runs=runs, created_at=utc_now())  # fmt: skip
    git.update_ref(root, f"refs/arena/{arena_id}/base", base)
    store.save(arena)
    write_atomic(store.arena_dir(arena_id) / "spec.json", spec.model_dump_json(indent=2, by_alias=True))
    store.set_current(arena_id)
    store.event(arena_id, "create", runs=len(runs))
    return arena


def brief(spec: Spec, c: Contestant) -> str:
    strategy = f"\nApproach: {c.strategy}\n" if c.strategy else ""
    return Template(data_text("brief.md.tmpl")).safe_substitute(task=spec.task, strategy=strategy)


def run_one(store: Store, arena_id: str, run_id: str) -> None:
    arena = store.load(arena_id)
    run, c = arena.runs[run_id], arena.contestant(arena.runs[run_id].contestant)
    adapter, spec = harness.get(c.harness), arena.spec
    run_dir = store.arena_dir(arena_id) / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    ws: Path | None = None
    try:
        ws = workspace.create(arena, run)
        home = workspace.home_dir(arena, run) if c.baseline == "clean" else None
        env = adapter.clean_env(home) if home else None
        workspace.apply_overlays(ws, home, c.overlays)
        base = workspace.overlay_base(arena, run, ws, any(o.scope == "repo" for o in c.overlays))
        with store.mutate(arena_id) as a:
            r = a.runs[run_id]
            r.state, r.workspace, r.base_commit, r.run_dir = "running", str(ws), base, str(run_dir)
        prompt = brief(spec, c)
        (run_dir / "prompt.md").write_text(prompt, encoding="utf-8")
        out = proc.run(adapter.agent_argv(c, prompt, run_dir, ws), ws, spec.run_timeout_sec,
                       owner=arena_id, log_dir=run_dir, env=env)  # fmt: skip
        metrics = adapter.metrics(out.stdout, cwd=ws, env=env)
        metrics.wall_ms = out.wall_ms
        with store.mutate(arena_id) as a:
            r = a.runs[run_id]
            r.exit_status, r.metrics = out.status, metrics
            r.snapshot = workspace.snapshot(store, a, r, ws)
            snap_commit = r.snapshot.commit
        report = checks.run_checks(spec.checks, ws, snap_commit, spec.check_timeout_sec, arena_id) if spec.checks else None
        with store.mutate(arena_id) as a:
            r = a.runs[run_id]
            r.checks = report
            r.gates = checks.gates(r, a.baseline)
            r.state = "done"
    except Exception as exc:  # one broken run must not sink the arena; it's recorded and excluded
        with store.mutate(arena_id) as a:
            a.runs[run_id].state, a.runs[run_id].error = "failed", f"{type(exc).__name__}: {exc}"
    finally:
        workspace.destroy(arena, run.model_copy(update={"workspace": str(ws) if ws else ""}))
    store.event(arena_id, "run", run=run_id)


def execute(store: Store, arena_id: str, progress: Progress) -> None:
    try:
        arena = store.load(arena_id)
        if arena.spec.checks:
            progress("running baseline checks on the base commit")
            report = checks.baseline(arena)
            with store.mutate(arena_id) as a:
                a.baseline = report
        total = len(arena.runs)
        with ThreadPoolExecutor(max_workers=arena.spec.max_parallel) as pool:
            futures = [pool.submit(run_one, store, arena_id, run_id) for run_id in arena.runs]
            for done, future in enumerate(as_completed(futures), 1):
                future.result()
                progress(f"{done}/{total} runs finished")
        finish(store, arena_id, progress)
    except Exception as exc:
        with store.mutate(arena_id) as a:
            a.status, a.error, a.finished_at = "failed", f"{type(exc).__name__}: {exc}", utc_now()
        raise


def finish(store: Store, arena_id: str, progress: Progress) -> None:
    """Judging and scorecard (Chunk 3). For now just mark the arena done."""
    with store.mutate(arena_id) as a:
        a.status, a.finished_at = "done", utc_now()
```

- [ ] **Step 6: Create `agents_arena_mcp/config_data.py`** (the only thing kept from the deleted `config.py`):

```python
"""Access to packaged files under agents_arena_mcp/data/."""

from __future__ import annotations

from importlib import resources


def data_text(name: str) -> str:
    return resources.files("agents_arena_mcp.data").joinpath(name).read_text(encoding="utf-8")
```

- [ ] **Step 7: Run.** `uv run pytest tests/test_pipeline.py -q`. Expected: PASS (6 tests). If `test_runs_every…` fails on the ref count, check that `workspace.snapshot` writes `refs/arena/<id>/<run>` and `create` writes `refs/arena/<id>/base`.

- [ ] **Step 8: Commit**

```bash
git add agents_arena_mcp/pipeline.py agents_arena_mcp/config_data.py agents_arena_mcp/data/brief.md.tmpl tests/test_pipeline.py
git commit -qm "feat(pipeline): preflight, baseline and parallel contestant x repeat runs with isolation and metrics"
```

---

## Chunk 3: Judging, scorecard, history, HTML, promote

### Task 7: Rubric scoring and the both-order final

**Files:**
- Rewrite: `agents_arena_mcp/judge.py`
- Create: `agents_arena_mcp/data/rubric.md.tmpl`, `agents_arena_mcp/data/rubric.schema.json`
- Rename: `agents_arena_mcp/data/judge.md.tmpl` → `agents_arena_mcp/data/final.md.tmpl` (content unchanged: it already uses `$task $evidence_a $patch_a $evidence_b $patch_b $extra`)
- Test: `tests/test_judge.py`

- [ ] **Step 1: Data files**

```bash
git mv agents_arena_mcp/data/judge.md.tmpl agents_arena_mcp/data/final.md.tmpl
```

`agents_arena_mcp/data/rubric.schema.json`:
```json
{
  "type": "object",
  "additionalProperties": false,
  "required": ["score", "reasons", "risks"],
  "properties": {
    "score": {"type": "number", "minimum": 0, "maximum": 10},
    "reasons": {"type": "array", "items": {"type": "string"}},
    "risks": {"type": "array", "items": {"type": "string"}}
  }
}
```

`agents_arena_mcp/data/rubric.md.tmpl`:
````
You are reviewing one candidate code change for a task. Do not edit any files.
Score it from 0 to 10 against the rubric. You don't know who wrote it; judge only the change.

## Task

$task

## Rubric

$rubric

## Evidence

$evidence

## Patch

```diff
$patch
```

Cite concrete lines in your reasons. Answer with JSON only:
{"score": 0-10, "reasons": ["..."], "risks": ["..."]}
````

- [ ] **Step 2: Write the failing test** `tests/test_judge.py`

```python
import json

import pytest
from conftest import command_contestant, command_judge

from agents_arena_mcp import judge, pipeline
from agents_arena_mcp.models import Spec
from agents_arena_mcp.store import Store


def run_arena(repo, fakes, monkeypatch, plans, **kw):
    monkeypatch.setenv("FAKE_PLAN", json.dumps(plans))
    data = {"task": "t", "objective": "quality", "repeats": 1, "judge": command_judge(fakes),
            "contestants": [command_contestant(fakes, n) for n in plans]}  # fmt: skip
    store = Store(repo)
    arena = pipeline.create(store, Spec.model_validate(data | kw))
    pipeline.run_one(store, arena.id, "x-1")
    pipeline.run_one(store, arena.id, "y-1")
    return store, arena.id


def test_rubric_scores_each_eligible_run_blind(repo, fakes, monkeypatch):
    store, aid = run_arena(repo, fakes, monkeypatch, {"x": {"write": {"a.py": "# GOOD\n"}}, "y": {"write": {"a.py": "# meh\n"}}})
    judge.score_runs(store, aid, progress=lambda m: None)
    runs = store.load(aid).runs
    assert runs["x-1"].score.score == 9 and runs["y-1"].score.score == 5
    prompt = (store.arena_dir(aid) / "judge" / "rubric-x-1" / "prompt.md").read_text()
    assert "x-1" not in prompt and "command" not in prompt


def test_final_judges_best_runs_in_both_orders(repo, fakes, monkeypatch):
    store, aid = run_arena(repo, fakes, monkeypatch, {"x": {"write": {"a.py": "# GOOD\n"}}, "y": {"write": {"a.py": "# meh\n"}}})
    judge.score_runs(store, aid, progress=lambda m: None)
    judge.run_finals(store, aid, progress=lambda m: None)
    finals = store.load(aid).finals
    assert {(m.first, m.second) for m in finals} == {("x-1", "y-1"), ("y-1", "x-1")}
    assert judge.pair_winner(finals) == "x-1"


def test_position_bias_is_a_tie(repo, fakes, monkeypatch):
    monkeypatch.setenv("FAKE_JUDGE_MODE", "always_a")
    store, aid = run_arena(repo, fakes, monkeypatch, {"x": {"write": {"a.py": "1\n"}}, "y": {"write": {"a.py": "2\n"}}})
    judge.run_finals(store, aid, progress=lambda m: None)
    assert judge.pair_winner(store.load(aid).finals) is None


def test_unusable_judge_output_is_recorded(repo, fakes, monkeypatch):
    monkeypatch.setenv("FAKE_JUDGE_MODE", "garbage")
    store, aid = run_arena(repo, fakes, monkeypatch, {"x": {"write": {"a.py": "1\n"}}, "y": {"write": {"a.py": "2\n"}}})
    judge.score_runs(store, aid, progress=lambda m: None)
    run = store.load(aid).runs["x-1"]
    assert run.score is None and "no usable JSON" in run.error


@pytest.mark.parametrize(("text", "expected"), [('{"winner": "A"}', "A"), ('```json\n{"winner": "B"}\n```', "B"),
                                                (json.dumps({"structured_output": {"winner": "tie"}}), "tie")])
def test_extract_json(text, expected):
    assert judge.extract_json(text, "winner")["winner"] == expected


def test_rubric_text_presets_and_custom():
    assert "architecture" in judge.rubric_text("elegance")
    assert judge.rubric_text("Prefer async/await over callbacks") == "Prefer async/await over callbacks"
```

- [ ] **Step 3: Run.** `uv run pytest tests/test_judge.py -q`. Expected: FAIL (`ImportError: cannot import name 'judge'`).

- [ ] **Step 4: Rewrite `agents_arena_mcp/judge.py`**

```python
"""Blind judging: a rubric score per run, then a both-order final between contestants' best runs."""

from __future__ import annotations

import json
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from itertools import combinations
from pathlib import Path
from string import Template

from pydantic import ValidationError

from agents_arena_mcp import harness, proc
from agents_arena_mcp.checks import failing_count
from agents_arena_mcp.config_data import data_text
from agents_arena_mcp.models import Arena, CheckReport, Match, Run, Score, Spec, Verdict
from agents_arena_mcp.store import Store

PATCH_LIMIT = 40_000
RUBRICS = {
    "quality": "Correctness first: does it solve the task without breaking behavior? Then regression tests "
    "as evidence, then low risk and a small blast radius. Weakening or skipping tests is a serious defect.",
    "elegance": "Assume correctness is required. Reward clean architecture and clear boundaries, readable and "
    "idiomatic code, small cohesive changes, and good naming. Penalize hacks, special cases, and needless "
    "complexity. Length is not quality.",
}


def rubric_text(objective: str) -> str:
    return RUBRICS.get(objective, objective)


def evidence(run: Run, base: CheckReport | None) -> str:
    """What a judge may know: checks vs baseline, flags, size. Nothing identifying the contestant."""
    lines = [f"- Files changed: {len(run.snapshot.files)}, lines changed: {run.snapshot.lines_changed}"] if run.snapshot else []
    for r in run.checks.results if run.checks else []:
        before = base.status_of(r.name) if base else None
        lines.append(f"- Check `{r.name}`: {r.status}" + (f" (on base: {before})" if before else ""))
    if not run.checks:
        lines.append("- Checks: none configured")
    lines += [f"- Flag {g.kind} ({g.severity}): {g.detail}" for g in run.gates if g.severity != "info"]
    return "\n".join(lines)


def patch_text(run: Run) -> str:
    assert run.snapshot is not None
    raw = Path(run.snapshot.patch_path).read_bytes().decode("utf-8", "replace")
    return raw if len(raw) <= PATCH_LIMIT else raw[:PATCH_LIMIT] + "\n…[truncated]\n"


def extract_json(text: str, key: str) -> dict | None:
    """The last JSON object carrying `key`: bare, fenced, inside claude's structured_output/result, or JSONL."""
    found: list[dict] = []

    def visit(value: object) -> None:
        if isinstance(value, dict):
            if key in value:
                found.append(value)
            for v in value.values():
                visit(v)
        elif isinstance(value, list):
            for v in value:
                visit(v)
        elif isinstance(value, str) and "{" in value and key in value:
            scan(value)

    def scan(blob: str) -> None:
        decoder = json.JSONDecoder()
        i = blob.find("{")
        while i != -1:
            try:
                obj, end = decoder.raw_decode(blob, i)
            except json.JSONDecodeError:
                i = blob.find("{", i + 1)
                continue
            visit(obj)
            i = blob.find("{", end)

    scan(text)
    return found[-1] if found else None


def call(spec: Spec, prompt: str, schema_name: str, key: str, run_dir: Path, owner: str) -> tuple[dict | None, str]:
    """Run the judge CLI in an empty directory; return the parsed JSON object or an error message."""
    run_dir.mkdir(parents=True, exist_ok=True)
    schema = data_text(schema_name)
    files = harness.JudgeFiles(prompt_file=str(run_dir / "prompt.md"), output_file=str(run_dir / "output.json"),
                               schema_file=str(run_dir / "schema.json"), schema_json=json.dumps(json.loads(schema)))  # fmt: skip
    Path(files.prompt_file).write_text(prompt, encoding="utf-8")
    Path(files.schema_file).write_text(schema, encoding="utf-8")
    argv = harness.get(spec.judge.harness).judge_argv(spec.judge, prompt, files)
    out = proc.run(argv, run_dir, spec.judge.timeout_sec, owner=owner, log_dir=run_dir)
    written = Path(files.output_file).read_text(encoding="utf-8") if Path(files.output_file).exists() else ""
    parsed = extract_json(written, key) or extract_json(out.stdout, key)
    return (parsed, "") if parsed else (None, f"judge returned no usable JSON ({out.status}); see {run_dir}")


def score_one(store: Store, arena: Arena, run: Run) -> tuple[Score | None, str]:
    try:
        return _score_one(store, arena, run)
    except Exception as exc:  # one failed judge call must not stop scoring the others
        return None, f"rubric judge failed: {type(exc).__name__}: {exc}"


def _score_one(store: Store, arena: Arena, run: Run) -> tuple[Score | None, str]:
    prompt = Template(data_text("rubric.md.tmpl")).safe_substitute(
        task=arena.spec.task, rubric=rubric_text(arena.spec.objective),
        evidence=evidence(run, arena.baseline), patch=patch_text(run))  # fmt: skip
    parsed, error = call(arena.spec, prompt, "rubric.schema.json", "score",
                         store.arena_dir(arena.id) / "judge" / f"rubric-{run.id}", arena.id)  # fmt: skip
    if parsed is None:
        return None, error
    try:
        return Score.model_validate(parsed), ""
    except ValidationError as exc:
        return None, f"rubric output failed validation: {exc.errors()[0]['msg']}"


def score_runs(store: Store, arena_id: str, progress: Callable[[str], None]) -> None:
    arena = store.load(arena_id)
    todo = [r for r in arena.runs.values() if r.eligible and r.score is None]
    with ThreadPoolExecutor(max_workers=arena.spec.max_parallel) as pool:
        for i, (run, (score, error)) in enumerate(zip(todo, pool.map(lambda r: score_one(store, arena, r), todo), strict=True), 1):
            with store.mutate(arena_id) as a:
                a.runs[run.id].score = score
                if error:
                    a.runs[run.id].error = error
            progress(f"{i}/{len(todo)} runs scored")


def best_run(arena: Arena, contestant: str) -> Run | None:
    pool = [r for r in arena.runs.values() if r.contestant == contestant and r.eligible]
    if not pool:
        return None
    lines = lambda r: r.snapshot.lines_changed if r.snapshot else 10**9  # noqa: E731
    return min(pool, key=lambda r: (-(r.score.score if r.score else -1), failing_count(r), lines(r)))


def judge_order(store: Store, arena: Arena, first: Run, second: Run) -> Match:
    prompt = Template(data_text("final.md.tmpl")).safe_substitute(
        task=arena.spec.task, evidence_a=evidence(first, arena.baseline), evidence_b=evidence(second, arena.baseline),
        patch_a=patch_text(first), patch_b=patch_text(second), extra="")  # fmt: skip
    run_dir = store.arena_dir(arena.id) / "judge" / f"final-{first.id}-vs-{second.id}"
    parsed, error = call(arena.spec, prompt, "judge.schema.json", "winner", run_dir, arena.id)
    try:
        verdict = Verdict.model_validate(parsed) if parsed else Verdict(winner="tie", confidence=0.0, reasons=[error])
    except ValidationError as exc:
        verdict = Verdict(winner="tie", confidence=0.0, reasons=[f"final output failed validation: {exc.errors()[0]['msg']}"])
    return Match(first=first.id, second=second.id, verdict=verdict, run_dir=str(run_dir))


def run_finals(store: Store, arena_id: str, progress: Callable[[str], None]) -> None:
    arena = store.load(arena_id)
    bests = [b for c in arena.spec.contestants if (b := best_run(arena, c.name))]
    orders = [(x, y) for a, b in combinations(bests, 2) for x, y in ((a, b), (b, a))]
    with ThreadPoolExecutor(max_workers=arena.spec.max_parallel) as pool:
        matches = list(pool.map(lambda o: judge_order(store, arena, *o), orders))
    with store.mutate(arena_id) as a:
        a.finals = matches
    progress(f"final round: {len(matches)} judge calls")


def pair_winner(matches: list[Match]) -> str | None:
    """A run wins a pair only if it wins in every order; a split or tie is no signal."""
    winners = {m.winner for m in matches}
    return winners.pop() if len(matches) >= 2 and len(winners) == 1 else None
```

- [ ] **Step 5: Run.** `uv run pytest tests/test_judge.py -q`. Expected: PASS (8 tests). The final template's "## Patch A / ## Evidence for B / ## Patch B" headings must match the fake judge's split markers; `final.md.tmpl` already has them.

- [ ] **Step 6: Commit**

```bash
git add -A agents_arena_mcp/judge.py agents_arena_mcp/data tests/test_judge.py
git commit -qm "feat(judge): blind rubric score per run and both-order final between best runs"
```

### Task 8: Scorecard, history, HTML report, promote; wire into the pipeline

**Files:**
- Create: `agents_arena_mcp/scorecard.py`
- Modify: `agents_arena_mcp/pipeline.py` (`finish`, plus new `promote`)
- Modify: `agents_arena_mcp/store.py` (rename `ledger` → `history`, file `history.jsonl`; add `read_history`)
- Test: `tests/test_scorecard.py`

- [ ] **Step 1: Write the failing test** `tests/test_scorecard.py`

```python
import json

from conftest import command_contestant, command_judge, git

from agents_arena_mcp import pipeline, scorecard
from agents_arena_mcp.models import Spec
from agents_arena_mcp.store import Store


def arena_done(repo, fakes, monkeypatch, plans, **kw):
    monkeypatch.setenv("FAKE_PLAN", json.dumps(plans))
    data = {"task": "t", "repeats": 2, "judge": command_judge(fakes),
            "contestants": [command_contestant(fakes, n) for n in plans]}  # fmt: skip
    store = Store(repo)
    arena = pipeline.create(store, Spec.model_validate(data | kw))
    pipeline.execute(store, arena.id, progress=lambda m: None)
    return store, store.load(arena.id)


def test_quality_winner_from_final_and_medians(repo, fakes, monkeypatch):
    store, arena = arena_done(repo, fakes, monkeypatch, {"x": {"write": {"a.py": "# GOOD\n"}}, "y": {"write": {"a.py": "# meh\n"}}})
    card = arena.scorecard
    assert card.winner == "x" and "both orders" in card.verdict
    x = next(s for s in card.stats if s.name == "x")
    assert (x.runs, x.eligible, x.pass_rate, x.median_score, x.median_tokens) == (2, 2, 1.0, 9, 120)
    assert (store.arena_dir(arena.id) / "result.json").exists() and (store.arena_dir(arena.id) / "report.md").exists()
    history = store.read_history()
    assert history[-1]["arena_id"] == arena.id and history[-1]["winner"] == "x"


def test_metric_objective_needs_no_judge(repo, fakes, monkeypatch):
    store, arena = arena_done(repo, fakes, monkeypatch, {"x": {"write": {"a.py": "1\n"}}, "y": {"write": {"a.py": "2\n"}}},
                              objective="tokens", judge={"harness": "none"})
    assert arena.finals == [] and all(r.score is None for r in arena.runs.values())
    assert arena.scorecard.winner in {"x", "y"} and "tokens" in arena.scorecard.verdict
    assert arena.scorecard.winner_run is not None  # metric winners can be promoted too


def test_no_eligible_runs(repo, fakes, monkeypatch):
    store, arena = arena_done(repo, fakes, monkeypatch, {"x": {"delete": ["tests/test_app.py"]}}, judge={"harness": "none"})
    assert arena.scorecard.winner is None and "no contestant" in arena.scorecard.verdict


def test_html_report_is_self_contained(repo, fakes, monkeypatch):
    store, arena = arena_done(repo, fakes, monkeypatch, {"x": {"write": {"a.py": "# GOOD\n"}}, "y": {"write": {"a.py": "2\n"}}})
    html = scorecard.render_html(arena)
    assert html.startswith("<!doctype html>") and "<table" in html and ">x<" in html
    assert "<link" not in html and "<script src" not in html  # self-contained


def test_promote_branch_and_apply(repo, fakes, monkeypatch):
    store, arena = arena_done(repo, fakes, monkeypatch, {"x": {"write": {"new.py": "# GOOD\n"}}, "y": {"write": {"a.py": "2\n"}}})
    out = pipeline.promote(store, arena.id, "branch")
    assert git(repo, "show", f"{out['branch']}:new.py") == "# GOOD\n"
    assert git(repo, "rev-parse", "--abbrev-ref", "HEAD").strip() == "main"
    pipeline.promote(store, arena.id, "apply")
    assert (repo / "new.py").read_text() == "# GOOD\n"
```

- [ ] **Step 2: Run.** `uv run pytest tests/test_scorecard.py -q`. Expected: FAIL (ImportError: `scorecard`).

- [ ] **Step 3: Store history.** In `agents_arena_mcp/store.py`, replace the `ledger` method with:

```python
    def history(self, record: dict[str, Any]) -> None:
        append_jsonl(self.root / "history.jsonl", {"at": utc_now(), **record})

    def read_history(self) -> list[dict[str, Any]]:
        path = self.root / "history.jsonl"
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
```

Also change the `current_id` error message to `"No arena yet. Plan one with arena_plan, then arena_start."`, and make `load` reject arenas written by v0.2:

```python
    def load(self, arena_id: str | None = None) -> Arena:
        arena_id = arena_id or self.current_id()
        path = self.arena_dir(arena_id) / "arena.json"
        if not path.exists():
            raise ArenaError(f"Arena not found: {arena_id}")
        try:
            return Arena.model_validate_json(path.read_text(encoding="utf-8"))
        except ValidationError as exc:
            raise ArenaError(f"Arena {arena_id} was created by an older Agents Arena version and can't be read") from exc
```

(add `from pydantic import ValidationError` to the imports).

- [ ] **Step 4: Write `agents_arena_mcp/scorecard.py`**

```python
"""Scorecard: per-contestant medians, the winner for the arena's objective, markdown/HTML, history record."""

from __future__ import annotations

import html
import statistics
from collections import Counter

from agents_arena_mcp.judge import best_run, pair_winner
from agents_arena_mcp.models import METRIC_OBJECTIVES, Arena, ContestantStats, Scorecard

# Validated categorical palette (dataviz reference, light surface; contrast WARN -> values are always labeled).
PALETTE = ("#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300")
METRIC_FIELD = {"speed": "median_wall_ms", "tokens": "median_tokens", "cost": "median_cost_usd"}


def _median(values: list[float | int | None]) -> float | None:
    present = [v for v in values if v is not None]
    return statistics.median(present) if present else None


def stats_for(arena: Arena, name: str) -> ContestantStats:
    runs = [r for r in arena.runs.values() if r.contestant == name]
    ok = [r for r in runs if r.eligible]
    return ContestantStats(
        name=name, runs=len(runs), eligible=len(ok), pass_rate=round(len(ok) / len(runs), 3) if runs else 0.0,
        median_score=_median([r.score.score if r.score else None for r in ok]),
        median_tokens=_median([r.metrics.total_tokens for r in ok]),
        median_wall_ms=_median([r.metrics.wall_ms for r in ok]),
        median_cost_usd=_median([r.metrics.cost_usd for r in ok]),
        median_lines=_median([r.snapshot.lines_changed if r.snapshot else None for r in ok]),
        gate_hits=dict(Counter(g.kind for r in runs for g in r.gates if g.severity != "info")),
    )  # fmt: skip


def build(arena: Arena) -> Scorecard:
    spec = arena.spec
    stats = [stats_for(arena, c.name) for c in spec.contestants]
    notes = [f"{r.id}: {r.error}" for r in arena.runs.values() if r.error]
    if any(s.median_cost_usd is None and s.eligible for s in stats):
        notes.append("cost is only shown for harnesses that report it (codex reports tokens, not dollars)")
    alive = [s for s in stats if s.eligible]
    if not alive:
        return Scorecard(objective=spec.objective, stats=stats, verdict="no contestant produced an eligible run", notes=notes)
    if spec.objective in METRIC_OBJECTIVES:
        field = METRIC_FIELD[spec.objective]
        ranked = sorted(alive, key=lambda s: (getattr(s, field) is None, getattr(s, field) or 0, -s.pass_rate))
        best = ranked[0]
        if getattr(best, field) is None:
            return Scorecard(objective=spec.objective, stats=stats, verdict=f"no {spec.objective} data reported", notes=notes)
        verdict = f"{best.name} is best on {spec.objective}: median {getattr(best, field):g}"
        if len(ranked) > 1 and getattr(ranked[1], field) is not None:
            verdict += f" vs {getattr(ranked[1], field):g} for {ranked[1].name}"
        run = _best_metric_run(arena, best.name, spec.objective)
        return Scorecard(objective=spec.objective, stats=stats, winner=best.name, winner_run=run,
                         verdict=verdict, notes=notes)  # fmt: skip
    return _judged_winner(arena, stats, alive, notes)


def _best_metric_run(arena: Arena, name: str, objective: str) -> str | None:
    """The eligible run of `name` with the best (lowest) value of the objective's metric."""
    value = {"speed": lambda r: r.metrics.wall_ms, "tokens": lambda r: r.metrics.total_tokens,
             "cost": lambda r: r.metrics.cost_usd}[objective]  # fmt: skip
    pool = [r for r in arena.runs.values() if r.contestant == name and r.eligible and value(r) is not None]
    return min(pool, key=value).id if pool else None  # type: ignore[arg-type]


def _judged_winner(arena: Arena, stats: list[ContestantStats], alive: list[ContestantStats], notes: list[str]) -> Scorecard:
    spec = arena.spec
    wins = Counter[str]()
    by_run = {r.id: r.contestant for r in arena.runs.values()}
    finals_by_pair: dict[frozenset[str], list] = {}
    for m in arena.finals:
        finals_by_pair.setdefault(frozenset((m.first, m.second)), []).append(m)
    for pair in finals_by_pair.values():
        if (w := pair_winner(pair)) is not None:
            wins[by_run[w]] += 1
    ranked = sorted(alive, key=lambda s: (-wins[s.name], -(s.median_score or -1), -s.pass_rate))
    best = ranked[0]
    second = ranked[1] if len(ranked) > 1 else None
    if second and (wins[best.name], best.median_score, best.pass_rate) == (wins[second.name], second.median_score, second.pass_rate):
        return Scorecard(objective=spec.objective, stats=stats, verdict=f"tie between {best.name} and {second.name}: your call", notes=notes)
    label = spec.objective if spec.objective in ("quality", "elegance") else "rubric"
    decided = "won the final in both orders" if wins[best.name] else f"highest median {label} score"
    run = best_run(arena, best.name)
    return Scorecard(objective=spec.objective, stats=stats, winner=best.name, winner_run=run.id if run else None,
                     verdict=f"{best.name} {decided}", notes=notes)  # fmt: skip


def _fmt(value: float | None, kind: str) -> str:
    if value is None:
        return "—"
    return {"score": f"{value:.1f}", "tokens": f"{value / 1000:.1f}k", "ms": f"{value / 1000:.0f}s", "usd": f"${value:.3f}",
            "lines": f"{value:g}", "rate": f"{value:.0%}"}[kind]  # fmt: skip


COLUMNS = (("pass rate", "pass_rate", "rate"), ("score", "median_score", "score"), ("tokens", "median_tokens", "tokens"),
           ("time", "median_wall_ms", "ms"), ("cost", "median_cost_usd", "usd"), ("diff lines", "median_lines", "lines"))  # fmt: skip


def render_markdown(arena: Arena) -> str:
    card = arena.scorecard
    assert card is not None
    lines = [f"# Arena {arena.id}", "", f"**Task:** {arena.spec.task}", f"**Objective:** {card.objective} · "
             f"**Repeats:** {arena.spec.repeats}", "", f"**Verdict:** {card.verdict}", "",
             "| contestant | runs | " + " | ".join(c[0] for c in COLUMNS) + " | flags |",
             "|---|---:|" + "---:|" * len(COLUMNS) + "---|"]  # fmt: skip
    for s in card.stats:
        cells = " | ".join(_fmt(getattr(s, field), kind) for _, field, kind in COLUMNS)
        flags = ", ".join(f"{k}×{v}" for k, v in s.gate_hits.items()) or "—"
        lines.append(f"| {s.name} | {s.runs} | {cells} | {flags} |")
    lines += [""] + [f"- {n}" for n in card.notes]
    return "\n".join(lines) + "\n"


def render_html(arena: Arena) -> str:
    """One self-contained page: verdict, labeled bar small-multiples (one per metric), and the table."""
    card = arena.scorecard
    assert card is not None
    color = {s.name: PALETTE[i % len(PALETTE)] for i, s in enumerate(card.stats)}
    charts = []
    for title, field, kind in COLUMNS:
        values = [(s.name, getattr(s, field)) for s in card.stats]
        top = max((v for _, v in values if v is not None), default=0) or 1
        bars = "".join(
            f'<div class="row"><span class="lab">{html.escape(n)}</span><span class="bar" style="width:{(v or 0) / top * 70:.1f}%;'
            f'background:{color[n]}" title="{html.escape(n)}: {_fmt(v, kind)}"></span><span class="val">{_fmt(v, kind)}</span></div>'
            for n, v in values
        )  # fmt: skip
        charts.append(f'<div class="mini"><h3>{title}</h3>{bars}</div>')
    legend = "".join(f'<span><i style="background:{color[s.name]}"></i>{html.escape(s.name)}</span>' for s in card.stats)
    head = "<tr><td>contestant</td><td>runs</td>" + "".join(f"<td>{t}</td>" for t, _, _ in COLUMNS) + "<td>flags</td></tr>"
    rows = head + "".join(
        f"<tr><td>{html.escape(s.name)}</td><td>{s.runs}</td>"
        + "".join(f"<td>{_fmt(getattr(s, f), k)}</td>" for _, f, k in COLUMNS)
        + f"<td>{html.escape(', '.join(f'{k}x{v}' for k, v in s.gate_hits.items()) or '-')}</td></tr>"
        for s in card.stats
    )
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Arena {html.escape(arena.id)}</title>
<style>body{{font:15px/1.5 system-ui,sans-serif;color:#0b0b0b;background:#fcfcfb;max-width:1000px;margin:40px auto;padding:0 20px}}
h1{{font-size:22px}}.verdict{{background:#0b0b0b;color:#fcfcfb;padding:16px 20px;border-radius:6px;font-size:18px}}
.legend{{display:flex;gap:16px;margin:16px 0;color:#52514e}}.legend i{{display:inline-block;width:12px;height:12px;border-radius:3px;margin-right:6px}}
.grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}}.mini{{border:1px solid #e4e2dc;border-radius:6px;padding:10px 12px}}
.mini h3{{margin:0 0 8px;font-size:13px;color:#52514e;font-weight:600}}.row{{display:flex;align-items:center;gap:8px;margin:4px 0}}
.lab{{width:90px;font-size:12px;color:#52514e;overflow:hidden;text-overflow:ellipsis}}.bar{{height:14px;border-radius:0 4px 4px 0;min-width:2px}}
.val{{font-size:12px;font-weight:600}}table{{border-collapse:collapse;width:100%;margin-top:20px;font-size:13px}}
td{{border-bottom:1px solid #e4e2dc;padding:6px 8px}}tr:first-child td{{font-weight:600}}</style></head><body>
<h1>Arena {html.escape(arena.id)}</h1><p>{html.escape(arena.spec.task)}<br>objective: {html.escape(card.objective)} · repeats: {arena.spec.repeats}</p>
<div class="verdict">{html.escape(card.verdict)}</div><div class="legend">{legend}</div><div class="grid">{"".join(charts)}</div>
<table>{rows}</table>{"".join(f"<p>· {html.escape(n)}</p>" for n in card.notes)}</body></html>"""


def history_record(arena: Arena) -> dict:
    card = arena.scorecard
    assert card is not None
    return {"arena_id": arena.id, "task": arena.spec.task, "objective": card.objective, "winner": card.winner,
            "verdict": card.verdict, "contestants": [c.model_dump(mode="json", by_alias=True) for c in arena.spec.contestants],
            "stats": [s.model_dump(mode="json") for s in card.stats]}  # fmt: skip
```

- [ ] **Step 5: Wire judging and the scorecard into `pipeline.finish`, and add `promote`.** Replace `finish` in `pipeline.py` and add the imports `from agents_arena_mcp import judge, scorecard` and `import shutil`:

```python
def finish(store: Store, arena_id: str, progress: Progress) -> None:
    arena = store.load(arena_id)
    if arena.spec.judged:
        judge.score_runs(store, arena_id, progress)
        if len(arena.spec.contestants) > 1:
            judge.run_finals(store, arena_id, progress)
    with store.mutate(arena_id) as a:
        a.scorecard = scorecard.build(a)
        a.status, a.finished_at = "done", utc_now()
    done = store.load(arena_id)
    out = store.arena_dir(arena_id)
    write_atomic(out / "result.json", done.model_dump_json(indent=2, by_alias=True))
    write_atomic(out / "report.md", scorecard.render_markdown(done))
    store.history(scorecard.history_record(done))
    progress(done.scorecard.verdict if done.scorecard else "done")


def promote(store: Store, arena_id: str | None, mode: str) -> dict:
    """patch: write winner.diff; branch: commit it on the base without checkout; apply: git apply --3way."""
    if mode not in ("patch", "branch", "apply"):
        raise ArenaError(f"promote mode must be patch, branch or apply, not {mode!r}")
    arena = store.load(arena_id)
    card = arena.scorecard
    if card is None or card.winner_run is None:
        raise ArenaError(f"Nothing to promote: {card.verdict if card else 'arena has not finished'}")
    run = arena.runs[card.winner_run]
    assert run.snapshot is not None
    patch = store.arena_dir(arena.id) / "winner.diff"
    shutil.copyfile(run.snapshot.patch_path, patch)
    root, result = Path(arena.repo_root), {"arena_id": arena.id, "winner": card.winner, "run": run.id, "patch": str(patch)}
    if mode == "branch":
        branch = f"arena/{arena.id}-{card.winner}"
        if git.git(root, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}", check=False):
            raise ArenaError(f"Branch {branch} already exists; delete it or promote with mode='patch'")
        git.create_branch(root, branch, git.commit_patch(root, arena.base_commit, patch, f"arena {arena.id}: {run.id}"))
        result["branch"] = branch
    elif mode == "apply":
        git.apply_3way(root, patch)
    store.event(arena.id, "promote", mode=mode, run=run.id)
    return result
```

Note: `promote` applies `winner.diff` (measured from base + overlays) onto the arena base. If a repo overlay touched files that the agent also edited, `git apply` fails with a clear conflict error. This is expected, and it's documented in GUIDE.md (Task 10).

- [ ] **Step 6: Run.** `uv run pytest -q`. Expected: all tests PASS (models, harness, workspace, checks, pipeline, judge, scorecard, snapshot race).

- [ ] **Step 7: Commit**

```bash
git add -A agents_arena_mcp tests/test_scorecard.py
git commit -qm "feat(scorecard): per-objective winner, medians, markdown/HTML report, history and promote"
```

---

## Chunk 4: Surface (plan, 5 MCP tools, CLI, guide, evals, docs, release)

### Task 9: Repo detection and `arena_plan`

**Files:**
- Create: `agents_arena_mcp/plan.py`
- Test: `tests/test_plan.py`

- [ ] **Step 1: Write the failing test** `tests/test_plan.py`

```python
from agents_arena_mcp import plan
from agents_arena_mcp.models import Spec


def test_detects_python_uv_and_node_pnpm(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[tool.ruff]\nline-length = 100\n")
    (tmp_path / "uv.lock").write_text("")
    (tmp_path / "tests").mkdir()
    (tmp_path / "package.json").write_text('{"scripts": {"test": "vitest", "lint": "eslint ."}}')
    (tmp_path / "pnpm-lock.yaml").write_text("")
    cmds = {c.name: c.cmd for c in plan.detect_checks(tmp_path)}
    assert cmds["tests"] == "uv run pytest -q" and cmds["lint"] == "uv run ruff check ."
    assert cmds["js-test"] == "pnpm run test" and cmds["js-lint"] == "pnpm run lint"


def test_detects_go_rust_make(tmp_path):
    (tmp_path / "go.mod").write_text("module x\n")
    assert [c.cmd for c in plan.detect_checks(tmp_path)] == ["go test ./..."]
    (tmp_path / "go.mod").unlink()
    (tmp_path / "Makefile").write_text("build:\n\ttrue\ntest:\n\ttrue\n")
    assert [c.cmd for c in plan.detect_checks(tmp_path)] == ["make test"]


def test_plan_modes_return_valid_draft(repo, monkeypatch):
    monkeypatch.setattr(plan.shutil, "which", lambda name: f"/bin/{name}" if name in ("claude", "codex") else None)
    auto = plan.make_plan(repo, "compare claude and codex on the retry bug", "autopilot")
    Spec.model_validate(auto["draft_spec"])
    assert {c["harness"] for c in auto["draft_spec"]["contestants"]} == {"claude", "codex"}
    assert "questions" not in auto and auto["next"].startswith("Adapt")
    assert any(line.startswith("judge:") for line in auto["rationale"])
    interview = plan.make_plan(repo, "did my skill edit help?", "interview")
    ids = [q["id"] for q in interview["questions"]]
    assert ids == ["compare", "objective", "baseline", "repeats", "checks", "judge", "ship"]
    assert interview["harnesses"]["claude"]["installed"] is True
```

- [ ] **Step 2: Run.** `uv run pytest tests/test_plan.py -q`. Expected: FAIL (ImportError).

- [ ] **Step 3: Write `agents_arena_mcp/plan.py`**

```python
"""arena_plan's logic: detect how the repo is tested and which harnesses exist, then draft a spec.

The MCP doesn't interpret the request: the calling agent does. Autopilot returns a filled draft for the agent
to adapt; interview returns the questions the agent should ask the user first.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path
from typing import Any

from agents_arena_mcp import harness
from agents_arena_mcp.models import Check, Spec


def _python_prefix(root: Path) -> str:
    if (root / "uv.lock").exists():
        return "uv run"
    if (root / "poetry.lock").exists():
        return "poetry run"
    return "python -m"


def detect_checks(root: Path) -> list[Check]:
    found: list[Check] = []
    pyproject = root / "pyproject.toml"
    if pyproject.exists():
        text, prefix = pyproject.read_text(encoding="utf-8"), _python_prefix(root)
        if (root / "tests").is_dir() or "pytest" in text:
            found.append(Check(name="tests", cmd=f"{prefix} pytest -q"))
        if "[tool.ruff" in text or (root / "ruff.toml").exists():
            found.append(Check(name="lint", cmd=f"{prefix} ruff check ."))
    package = root / "package.json"
    if package.exists():
        scripts = json.loads(package.read_text(encoding="utf-8")).get("scripts", {})
        pm = next((m for m, lock in (("pnpm", "pnpm-lock.yaml"), ("yarn", "yarn.lock"), ("bun", "bun.lock"),
                                     ("bun", "bun.lockb")) if (root / lock).exists()), "npm")  # fmt: skip
        found += [Check(name=f"js-{s}", cmd=f"{pm} run {s}") for s in ("test", "lint", "typecheck") if s in scripts]
    if (root / "go.mod").exists():
        found.append(Check(name="tests", cmd="go test ./..."))
    if (root / "Cargo.toml").exists():
        found.append(Check(name="tests", cmd="cargo test"))
    makefile = root / "Makefile"
    if not found and makefile.exists() and re.search(r"^test:", makefile.read_text(encoding="utf-8"), re.M):
        found.append(Check(name="tests", cmd="make test"))
    return found


def harness_status() -> dict[str, dict[str, Any]]:
    out = {}
    for name in ("claude", "codex", "opencode"):
        installed = shutil.which(name) is not None
        clean = {"claude": any(os.environ.get(v) for v in harness.TOKEN_VARS),
                 "codex": (Path.home() / ".codex" / "auth.json").exists(),
                 "opencode": True}[name]  # fmt: skip
        out[name] = {"installed": installed, "clean_ready": installed and clean, "family": harness.get(name).family}
    return out


def questions(checks: list[Check], status: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    installed = [n for n, s in status.items() if s["installed"]]
    return [
        {"id": "compare", "question": "What should differ between contestants?",
         "options": ["harness (claude/codex/opencode)", "model", "a skill or file (overlay)", "strategy (approach)"],
         "why": "Vary one thing at a time for a clean comparison."},
        {"id": "objective", "question": "What decides the winner?",
         "options": ["quality", "elegance", "speed", "tokens", "cost", "custom rubric text"], "default": "quality"},
        {"id": "baseline", "question": "Start each contestant from a clean harness or your real setup?",
         "options": ["clean (only what the overlays add)", "real (your skills, plugins, MCP servers)"], "default": "real",
         "why": "clean claude needs CLAUDE_CODE_OAUTH_TOKEN (`claude setup-token`); real never modifies your home."},
        {"id": "repeats", "question": "How many runs per contestant?", "options": [1, 3, 5], "default": 3,
         "why": "Agents are noisy; medians over repeats are more trustworthy than one run."},
        {"id": "checks", "question": "Which checks gate the runs?", "options": [c.model_dump() for c in checks],
         "default": [c.model_dump() for c in checks], "why": "Detected from the repo; only regressions vs. the base count."},
        {"id": "judge", "question": "Which harness judges quality?", "options": installed + ["none"],
         "why": "Prefer a different model family than the contestants (judges favor their own family)."},
        {"id": "ship", "question": "Should the winner be promotable as a patch/branch?", "options": [True, False], "default": False},
    ]  # fmt: skip


def make_plan(root: Path, request: str, mode: str) -> dict[str, Any]:
    checks, status = detect_checks(root), harness_status()
    installed = [n for n, s in status.items() if s["installed"] and n != "opencode"] or ["claude"]
    judge = next((n for n in ("codex", "claude") if n in installed), "none")
    draft = Spec.model_validate({"task": request, "repeats": 3, "checks": [c.model_dump() for c in checks],
                                 "judge": {"harness": judge}, "contestants": [{"name": n, "harness": n} for n in installed]})  # fmt: skip
    out: dict[str, Any] = {"mode": mode, "draft_spec": draft.model_dump(by_alias=True), "detected_checks": [c.model_dump() for c in checks],
                           "harnesses": status, "spec_schema": Spec.model_json_schema(by_alias=True)}  # fmt: skip
    if mode == "interview":
        out["questions"] = questions(checks, status)
        out["next"] = "Ask the user these questions (one at a time), update draft_spec, show it, then call arena_start(spec)."
    else:
        out["rationale"] = [
            f"contestants: one per installed harness ({', '.join(installed)}); replace with the comparison the user asked for",
            f"judge: {judge} (prefer a different model family than the contestants)",
            "repeats: 3, enough for a median without much cost",
            f"checks: {', '.join(c.cmd for c in checks) or 'none detected; add the repo test command'}",
        ]
        out["next"] = ("Adapt draft_spec to the user's request (contestants, overlays, objective), explain each choice "
                       "in one line, then call arena_start(spec).")  # fmt: skip
    return out
```

- [ ] **Step 4: Run.** `uv run pytest tests/test_plan.py -q`. Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add agents_arena_mcp/plan.py tests/test_plan.py
git commit -qm "feat(plan): repo check detection, harness status, interview questions and autopilot drafts"
```

### Task 10: The 5 ops, MCP server with `arena://guide`, CLI with parity

**Files:**
- Create: `agents_arena_mcp/arena.py`, `agents_arena_mcp/data/GUIDE.md`
- Rewrite: `agents_arena_mcp/server.py`, `agents_arena_mcp/cli.py`
- Create: `agents_arena_mcp/scaffold.py`
- Test: `tests/test_surface.py`, `tests/test_e2e.py`

- [ ] **Step 1: Write the failing tests** `tests/test_surface.py`

```python
import asyncio
import json

from conftest import command_contestant, command_judge
from fastmcp import Client

from agents_arena_mcp import cli
from agents_arena_mcp.server import make_mcp


def tools():
    async def go():
        async with Client(make_mcp()) as c:
            return await c.list_tools(), await c.read_resource("arena://guide")

    return asyncio.run(go())


def test_five_tools_with_described_params_and_guide():
    listed, guide = tools()
    assert sorted(t.name for t in listed) == ["arena_history", "arena_plan", "arena_result", "arena_start", "arena_status"]
    for t in listed:
        assert t.description
        for name, prop in t.inputSchema.get("properties", {}).items():
            assert name != "ctx" and prop.get("description"), f"{t.name}.{name}"
    assert "arena_plan" in guide[0].text


def test_cli_and_mcp_parity():
    listed, _ = tools()
    mcp = {t.name: set(t.inputSchema.get("properties", {})) for t in listed}
    parser = cli.build_parser()
    sub = next(a for a in parser._actions if a.dest == "cmd")
    for name, fn in cli.COMMANDS.items():
        dests = {a.dest for a in sub.choices[name]._actions if a.dest != "help"}  # type: ignore[union-attr]
        assert dests == mcp[fn.__name__], name


def test_cli_plan_start_result(repo, fakes, tmp_path, capsys):
    assert cli.main(["plan", "x vs y", "--mode", "autopilot"]) == 0
    assert "draft_spec" in json.loads(capsys.readouterr().out)
    spec = {"task": "t", "judge": command_judge(fakes), "contestants": [command_contestant(fakes, "x"), command_contestant(fakes, "y")]}
    path = tmp_path / "spec.json"
    path.write_text(json.dumps(spec))
    assert cli.main(["start", str(path)]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "done"
    assert cli.main(["result", "--html"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["scorecard"]["verdict"] and out["html"].endswith("report.html")
```

`tests/test_e2e.py`:
```python
import asyncio
import json
import time

from conftest import command_contestant, command_judge
from fastmcp import Client

from agents_arena_mcp.server import make_mcp


def test_full_flow_over_mcp(repo, fakes, monkeypatch):
    monkeypatch.setenv("FAKE_PLAN", json.dumps({"x": {"write": {"a.py": "# GOOD\n"}}, "y": {"write": {"a.py": "2\n"}}}))
    spec = {"task": "t", "repeats": 2, "ship": True, "judge": command_judge(fakes),
            "contestants": [command_contestant(fakes, "x"), command_contestant(fakes, "y")]}  # fmt: skip

    async def go():
        async with Client(make_mcp()) as c:
            planned = (await c.call_tool("arena_plan", {"request": "x vs y", "mode": "interview"})).data
            assert planned["questions"]
            started = (await c.call_tool("arena_start", {"spec": spec})).data
            assert started["job"]["status"] == "running"
            for _ in range(150):
                status = (await c.call_tool("arena_status", {})).data
                if status["status"] != "running":
                    break
                time.sleep(0.1)
            assert status["status"] == "done", status
            result = (await c.call_tool("arena_result", {"promote": "branch"})).data
            history = (await c.call_tool("arena_history", {"contestant": "x"})).data
            return result, history

    result, history = asyncio.run(go())
    assert result["scorecard"]["winner"] == "x" and result["promoted"]["branch"].startswith("arena/")
    assert history["entries"][0]["winner"] == "x"
```

- [ ] **Step 2: Run.** `uv run pytest tests/test_surface.py tests/test_e2e.py -q`. Expected: FAIL (placeholder server/cli).

- [ ] **Step 3: Write `agents_arena_mcp/arena.py`**

```python
"""The five operations. Each is both an MCP tool and a CLI subcommand (OPS)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated, Any, Literal

from fastmcp import Context
from pydantic import Field, ValidationError

from agents_arena_mcp import git, jobs, pipeline, plan, scorecard
from agents_arena_mcp.errors import ArenaError
from agents_arena_mcp.models import Spec
from agents_arena_mcp.store import Store, write_atomic

ArenaId = Annotated[str | None, Field(description="Arena id; defaults to the most recently started arena.")]


def store() -> Store:
    start = Path(os.environ.get("AGENTS_ARENA_ROOT") or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
    return Store(git.repo_root(start))


def arena_plan(
    request: Annotated[str, Field(description="What the user wants to compare or find, in their words.")],
    mode: Annotated[Literal["interview", "autopilot"], Field(description="interview: return questions to ask the user; autopilot: return a filled draft to adapt.")] = "interview",  # noqa: E501
) -> dict[str, Any]:
    """Draft an arena spec: detected checks, installed harnesses, and questions (interview) or a full draft (autopilot). Runs nothing."""  # noqa: E501
    return plan.make_plan(store().repo_root, request, mode)


def arena_start(
    spec: Annotated[dict[str, Any], Field(description="The arena spec (see arena_plan's draft_spec and spec_schema).")],
    wait: Annotated[bool, Field(description="Block until done. False runs in the background; poll arena_status.")] = False,  # noqa: E501
    ctx: Context | None = None,
) -> dict[str, Any]:
    """Validate the spec, run preflight, then run every contestant x repeat in isolation, judge, and score."""
    try:
        parsed = Spec.model_validate(spec)
    except ValidationError as exc:
        raise ArenaError(f"Invalid spec: {exc}") from exc
    s = store()
    arena = pipeline.create(s, parsed)
    handle = jobs.in_background(s, arena.id, "arena", wait, ctx, lambda progress: pipeline.execute(s, arena.id, progress))
    return handle or arena_status(arena.id)


def arena_status(arena_id: ArenaId = None) -> dict[str, Any]:
    """Arena progress: each run's state, exit status, eligibility, and background job progress."""
    s = store()
    arena = s.load(arena_id)
    return {
        "arena_id": arena.id, "status": arena.status, "error": arena.error,
        "runs": {r.id: {"state": r.state, "exit": r.exit_status, "eligible": r.eligible, "error": r.error}
                 for r in arena.runs.values()},
        "jobs": [j.model_dump() for j in jobs.list_jobs(s, arena.id)],
        "verdict": arena.scorecard.verdict if arena.scorecard else None,
    }  # fmt: skip


def arena_result(
    arena_id: ArenaId = None,
    html: Annotated[bool, Field(description="Also write a self-contained HTML report and return its path.")] = False,
    promote: Annotated[Literal["patch", "branch", "apply"] | None, Field(description="Ship the winner: patch (write winner.diff), branch (create arena/<id>-<winner> without touching your checkout), apply (git apply --3way into your tree).")] = None,  # noqa: E501
) -> dict[str, Any]:
    """The scorecard: per-contestant medians, the winner for the objective, the verdict and notes."""
    s = store()
    arena = s.load(arena_id)
    if arena.scorecard is None:
        raise ArenaError(f"Arena {arena.id} is {arena.status}; no scorecard yet. Check arena_status.")
    out: dict[str, Any] = {"arena_id": arena.id, "scorecard": arena.scorecard.model_dump(), "report": scorecard.render_markdown(arena)}
    if html:
        path = s.arena_dir(arena.id) / "report.html"
        write_atomic(path, scorecard.render_html(arena))
        out["html"] = str(path)
    if promote:
        out["promoted"] = pipeline.promote(s, arena.id, promote)
    return out


def arena_history(
    contestant: Annotated[str | None, Field(description="Only arenas that included this contestant name.")] = None,
    task_contains: Annotated[str | None, Field(description="Only arenas whose task contains this text.")] = None,
    limit: Annotated[int, Field(description="Most recent entries to return.")] = 20,
) -> dict[str, Any]:
    """Past arena results (newest first), for trends such as one skill across several edits."""
    entries = [e for e in store().read_history() if "stats" in e]
    if contestant:
        entries = [e for e in entries if any(c["name"] == contestant for c in e["contestants"])]
    if task_contains:
        entries = [e for e in entries if task_contains.lower() in e["task"].lower()]
    return {"entries": list(reversed(entries))[:limit]}


OPS = (arena_plan, arena_start, arena_status, arena_result, arena_history)
```

- [ ] **Step 4: Write `agents_arena_mcp/data/GUIDE.md`**

````markdown
# Agents Arena: how to use it

Agents Arena runs **experiments** on coding agents. Contestants are full recipes:
**harness** (claude / codex / opencode) + **model** + **baseline** (`clean` | `real`) + **overlays** (any file, any target) + **strategy**.
Each contestant runs `repeats` times, each run in its own git worktree. The arena checks every run against the base commit and judges it blind, then returns a **scorecard** for the arena's **objective**.

## Flow
1. **`arena_plan(request, mode)`**:
   - `interview`: ask the user the returned questions, one at a time, and update `draft_spec`.
   - `autopilot`: adapt `draft_spec` to the request and explain each choice in one line.
   Show the final spec to the user before starting.
2. **`arena_start(spec, wait=false)`**: preflight runs first and fails fast. Then poll **`arena_status`** until `status` is `done`.
3. **`arena_result(html=true)`** returns the scorecard. Add `promote="branch"` to ship the winner without touching the user's checkout.
4. **`arena_history(contestant=...)`** shows trends across arenas.

## Writing good specs
- **Spec files** (CLI): TOML uses `[[contestants]]` tables, or pass the same structure as JSON.
- **Vary one thing.** For a skill A/B, keep the harness, model and baseline the same, and give each contestant a different overlay.
- **Overlays:** `{"from": "<any path>", "to": "repo:<path>"}` puts a file or directory into the run's checkout. `home:<path>` targets the clean harness home and requires `baseline="clean"`. Overlays are never counted as the contestant's code.
- **Baseline:**
  - `real` uses the user's actual setup, which is never modified.
  - `clean` starts from an empty harness home with auth only. Clean claude needs `CLAUDE_CODE_OAUTH_TOKEN` (`claude setup-token`) or `ANTHROPIC_API_KEY`. Clean opencode only sees providers keyed by environment variables.
- **Objective:**
  - `quality` and `elegance` are judged: a blind rubric score per run, then a final in both orders.
  - `speed`, `tokens` and `cost` are metrics only, with no judge.
  - Any other text becomes a custom rubric.
- **Repeats:** 3–5 for comparisons you want to trust.
- **Judge:** prefer a different model family than the contestants.
- **Strategies:** for "most elegant solution", write 2–4 genuinely different, concrete approaches.

## Rules
- Report the verdict honestly. A tie is a valid result.
- Contestants and checks run agent-written code on this machine, the same as running tests on an untrusted branch.
- `promote` applies the winner's diff onto the base. If repo overlays touched the same files the agent edited, it fails with a conflict.
````

- [ ] **Step 5: Write `agents_arena_mcp/server.py`**

```python
"""MCP server: the five ops as tools, plus the arena://guide resource."""

from __future__ import annotations

from fastmcp import FastMCP

from agents_arena_mcp import __version__
from agents_arena_mcp.arena import OPS
from agents_arena_mcp.config_data import data_text

INSTRUCTIONS = (
    "Agents Arena runs experiments on coding agents (harness, model, skill or strategy A/B with repeats) and "
    "returns a scorecard. Start with arena_plan. Read arena://guide for the full workflow."
)


def make_mcp() -> FastMCP:
    mcp = FastMCP(name="Agents Arena", instructions=INSTRUCTIONS, version=__version__)
    for op in OPS:
        mcp.tool(op)

    @mcp.resource("arena://guide", mime_type="text/markdown")
    def guide() -> str:
        """How to plan, run and read arenas."""
        return data_text("GUIDE.md")

    return mcp


def main() -> None:
    make_mcp().run()
```

- [ ] **Step 6: Write `agents_arena_mcp/scaffold.py`**

```python
"""`agents-arena init --skills claude,codex,opencode`: install the guide as a skill for each agent."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agents_arena_mcp.config_data import data_text
from agents_arena_mcp.errors import ArenaError

SKILL_DIRS = {"claude": ".claude/skills/agents-arena", "codex": ".agents/skills/agents-arena",
              "opencode": ".opencode/skills/agents-arena"}  # fmt: skip
FRONTMATTER = """---
name: agents-arena
description: >
  Run experiments on coding agents: compare harnesses, models, skill edits or strategies with repeats and get a
  scorecard. Use when the user says "arena", "compare agents", "A/B this skill", or wants the best of several attempts.
---

"""


def init(root: Path, skills: str) -> dict[str, Any]:
    written = []
    for name in filter(None, (s.strip() for s in skills.split(","))):
        if name not in SKILL_DIRS:
            raise ArenaError(f"Unknown skill target {name!r}; choose from {', '.join(SKILL_DIRS)}")
        path = root / SKILL_DIRS[name] / "SKILL.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(FRONTMATTER + data_text("GUIDE.md"), encoding="utf-8")
        written.append(str(path))
    return {"written": written}
```

- [ ] **Step 7: Write `agents_arena_mcp/cli.py`**

```python
"""CLI: the same five operations as the MCP tools (same parameter names), plus init and eval-judge."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tomllib
from pathlib import Path
from typing import Any

from agents_arena_mcp import __version__
from agents_arena_mcp.arena import arena_history, arena_plan, arena_result, arena_start, arena_status, store
from agents_arena_mcp.errors import ArenaError

COMMANDS = {"plan": arena_plan, "start": arena_start, "status": arena_status, "result": arena_result, "history": arena_history}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agents-arena", description="Experiments on coding agents.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--repo", help="Repository root (default: git root of the current directory).")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan", help="Draft a spec (interview questions or autopilot draft)")
    p.add_argument("request")
    p.add_argument("--mode", choices=["interview", "autopilot"], default="interview")
    p = sub.add_parser("start", help="Run a spec file (TOML or JSON)")
    p.add_argument("spec", help="Path to the spec file")
    p.add_argument("--wait", action=argparse.BooleanOptionalAction, default=True)
    p = sub.add_parser("status", help="Show arena progress")
    p.add_argument("--arena-id")
    p = sub.add_parser("result", help="Show the scorecard; optionally write HTML or promote")
    p.add_argument("--arena-id")
    p.add_argument("--html", action="store_true")
    p.add_argument("--promote", choices=["patch", "branch", "apply"])
    p = sub.add_parser("history", help="Past arena results")
    p.add_argument("--contestant")
    p.add_argument("--task-contains")
    p.add_argument("--limit", type=int, default=20)
    p = sub.add_parser("init", help="Install the arena skill for your agents")
    p.add_argument("--skills", default="claude")
    return parser


def _load_spec(path: str) -> dict[str, Any]:
    text = Path(path).read_text(encoding="utf-8")
    return tomllib.loads(text) if path.endswith(".toml") else json.loads(text)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.repo:
        os.environ["AGENTS_ARENA_ROOT"] = str(Path(args.repo).resolve())
    kwargs = {k: v for k, v in vars(args).items() if k not in {"cmd", "repo"}}
    try:
        if args.cmd == "init":
            from agents_arena_mcp.scaffold import init

            result: Any = init(store().repo_root, args.skills)
        else:
            if args.cmd == "start":
                if not args.wait:
                    raise ArenaError("Background runs need the MCP server (this CLI process would exit and kill them); use --wait")
                kwargs["spec"] = _load_spec(kwargs["spec"])
            result = COMMANDS[args.cmd](**kwargs)
    except ArenaError as exc:
        print(json.dumps({"error": str(exc)}, indent=2), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, default=str))
    return 0
```

- [ ] **Step 8: Run.** `uv run pytest -q` and the full gate. Expected: all PASS.

- [ ] **Step 9: Commit**

```bash
git add -A agents_arena_mcp tests/test_surface.py tests/test_e2e.py
git commit -qm "feat!(mcp): five tools (plan, start, status, result, history) and arena://guide; CLI parity"
```

### Task 11: `eval-judge` on the new pipeline

**Files:**
- Create: `agents_arena_mcp/evals.py`
- Modify: `agents_arena_mcp/cli.py` (add the `eval-judge` subcommand)
- Test: `tests/test_evals.py`

- [ ] **Step 1: Write the failing test** `tests/test_evals.py`

```python
import sys

from conftest import FAKE_JUDGE

from agents_arena_mcp import evals


def test_position_biased_judge_is_caught(repo, tmp_path, monkeypatch):
    judge = tmp_path / "j.py"
    judge.write_text(FAKE_JUDGE)
    monkeypatch.setenv("FAKE_JUDGE_MODE", "always_a")
    out = evals.eval_judge("command", "", argv=[sys.executable, str(judge), "{prompt_file}", "{output_file}"])
    m = out["metrics"]
    assert m["order_flip_rate"] == 1.0 and m["tie_rate"] == 1.0 and m["cases"] == 8
```

- [ ] **Step 2: Run.** `uv run pytest tests/test_evals.py -q`. Expected: FAIL (ImportError).

- [ ] **Step 3: Write `agents_arena_mcp/evals.py`**

```python
"""`agents-arena eval-judge`: run each seeded case as a real two-contestant arena and score the judge's final.

Reports accuracy vs. the expected winner, the order-flip rate (the verdict changed when A/B were swapped),
the tie rate, and latency. The case files' contestants are 'command' runs that write the case's files.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import tomllib
from importlib import resources
from pathlib import Path
from typing import Any

from agents_arena_mcp import pipeline
from agents_arena_mcp.judge import judge_order, pair_winner
from agents_arena_mcp.models import JudgeSpec, Spec
from agents_arena_mcp.store import Store, utc_now

WRITER = ("import json,os,sys\nw=json.loads(sys.argv[1])\nfor p,t in w.get('write',{}).items():\n"
          "    os.makedirs(os.path.dirname(p) or '.',exist_ok=True); open(p,'w').write(t)\n"
          "for p in w.get('delete',[]): os.remove(p)\n")  # fmt: skip


def cases() -> list[dict[str, Any]]:
    folder = resources.files("agents_arena_mcp.data").joinpath("judge_cases")
    return [tomllib.loads(f.read_text(encoding="utf-8")) | {"name": f.name[:-5]}
            for f in sorted(folder.iterdir(), key=lambda f: f.name) if f.name.endswith(".toml")]  # fmt: skip


def _run_case(case: dict[str, Any], judge: dict[str, Any]) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="arena-eval-") as tmp:
        repo = Path(tmp) / "repo"
        repo.mkdir()
        for rel, content in case["base"].items():
            (repo / rel).parent.mkdir(parents=True, exist_ok=True)
            (repo / rel).write_text(content, encoding="utf-8")
        ident = {"GIT_AUTHOR_NAME": "e", "GIT_AUTHOR_EMAIL": "e@x", "GIT_COMMITTER_NAME": "e", "GIT_COMMITTER_EMAIL": "e@x"}
        for args in (["init", "-q"], ["add", "-A"], ["commit", "-qm", "base"]):
            subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, env={**os.environ, **ident})
        contestants = [{"name": side, "harness": "command", "argv": [sys.executable, "-c", WRITER, json.dumps(
            {"write": case.get(side, {}), "delete": case.get(f"delete_{side}", [])})]} for side in ("a", "b")]  # fmt: skip
        # Run the contestants without judging, then judge the pair directly: when measuring the judge,
        # gated runs (e.g. the test-deleting cheat) must still be judged.
        spec = Spec.model_validate({"task": case["task"], "judge": {"harness": "none"}, "contestants": contestants})
        store = Store(repo)
        arena = pipeline.create(store, spec)
        pipeline.execute(store, arena.id, progress=lambda m: None)
        done = store.load(arena.id)
        done = done.model_copy(update={"spec": done.spec.model_copy(update={"judge": JudgeSpec.model_validate(judge)})})
        a_run, b_run = done.runs["a-1"], done.runs["b-1"]
        if a_run.snapshot is None or b_run.snapshot is None:
            return {"case": case["name"], "error": a_run.error or b_run.error or "a run produced no snapshot",
                    "expected": [], "combined": "error", "correct": False, "orders": [], "flipped": False,
                    "labels": [], "reasons": [], "latency_ms": 0}  # fmt: skip
        started = time.monotonic()
        finals = [judge_order(store, done, a_run, b_run), judge_order(store, done, b_run, a_run)]
        done = done.model_copy(update={"finals": finals})
    expected = case["expected"] if isinstance(case["expected"], list) else [case["expected"]]
    winner = pair_winner(done.finals)
    combined = winner.split("-")[0] if winner else "tie"
    orders = [m.winner.split("-")[0] if m.winner else "tie" for m in done.finals]
    return {"case": case["name"], "expected": expected, "combined": combined, "correct": combined in expected,
            "orders": orders, "flipped": len(set(orders)) > 1, "labels": [m.verdict.winner for m in done.finals],
            "reasons": [m.verdict.reasons[:3] for m in done.finals], "latency_ms": int((time.monotonic() - started) * 1000)}  # fmt: skip


def eval_judge(harness: str, model: str, argv: list[str] | None = None) -> dict[str, Any]:
    judge = {"harness": harness, "model": model, "argv": argv or []}
    results = [_run_case(c, judge) for c in cases()]
    n, labels = len(results) or 1, [label for r in results for label in r["labels"]]
    metrics = {"judge": f"{harness}:{model or 'default'}", "cases": len(results),
               "accuracy": round(sum(r["correct"] for r in results) / n, 3),
               "order_flip_rate": round(sum(r["flipped"] for r in results) / n, 3),
               "tie_rate": round(sum(r["combined"] == "tie" for r in results) / n, 3),
               "picked_label_A_rate": round(labels.count("A") / (len(labels) or 1), 3),
               "mean_latency_ms": int(sum(r["latency_ms"] for r in results) / n)}  # fmt: skip
    out_dir = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "agents-arena" / "evals"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"judge-{utc_now().replace(':', '')}.json"
    path.write_text(json.dumps({"metrics": metrics, "results": results}, indent=2), encoding="utf-8")
    return {"metrics": metrics, "results_path": str(path), "failures": [r for r in results if not r["correct"]]}
```

Note: each case gets exactly two judge calls (both orders), so under an always-A judge every one of the 8 cases flips and ties, which is what the test asserts. `eval-judge` results go to `~/.cache/agents-arena/evals/` because the eval runs in throwaway repos.

- [ ] **Step 4: Wire the CLI.** In `cli.py`'s `build_parser`, before `return parser`, add:

```python
    p = sub.add_parser("eval-judge", help="Measure a judge on seeded pairs with known answers")
    p.add_argument("--judge", default="claude")
    p.add_argument("--model", default="")
```

Then in `main`, before the final `else:`, add:

```python
        elif args.cmd == "eval-judge":
            from agents_arena_mcp.evals import eval_judge

            result = eval_judge(args.judge, args.model)
```

- [ ] **Step 5: Run.** `uv run pytest -q` plus the full gate. Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add agents_arena_mcp/evals.py agents_arena_mcp/cli.py tests/test_evals.py
git commit -qm "feat(evals): eval-judge runs seeded cases through the real v0.3 pipeline"
```

### Task 12: Docs, real-harness verification, release

**Files:** `README.md`, `CHANGELOG.md`, `TODO.md`, `docs/design.md`, `.agents/skills/agents-arena/SKILL.md`, `agents_arena_mcp/__init__.py`

- [ ] **Step 1: Full gate.** `uv run ruff format . && uv run ruff check --fix . && uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run basedpyright`. All green.

- [ ] **Step 2: Real stdio MCP smoke test.**
  - **Setup:** a scratch repo at `/tmp/arena-smoke` (one `calc.py` + `tests/test_calc.py`, committed). Launch the server with fastmcp's `StdioTransport(command="uvx", args=["--from", "/Users/matteo/Developer/agents-arena-mcp", "agents-arena-mcp"], env={"AGENTS_ARENA_ROOT": "/tmp/arena-smoke", "PATH": os.environ["PATH"], "HOME": os.environ["HOME"]})`.
  - **Calls:** `arena_plan(autopilot)`, then `arena_start` with 2 contestants (`claude` real and `codex` clean, `repeats=1`, judge `claude`, checks = the repo's pytest, and a one-line task), then poll `arena_status`, then `arena_result(html=true)`.
  - **Pass criteria:**
    - `status == "done"` and the verdict is not null.
    - Every contestant has `median_tokens` set.
    - `report.html` exists.
    - Afterwards, `git worktree list` shows only the main tree.
    - The mtimes of `~/.claude` and `~/.codex` didn't change: compare `stat` before and after.

- [ ] **Step 3: Real OpenCode as contestant and as judge.**
  - One arena with contestant `{"harness": "opencode", "model": "openrouter/openai/gpt-5-mini", "baseline": "real"}`. Pass: tokens and cost are non-null.
  - Then run `agents-arena eval-judge --judge opencode --model openrouter/openai/gpt-5-mini`.

- [ ] **Step 4: Real judge evals.** Run `agents-arena eval-judge --judge codex` and `--judge claude`. Record accuracy, order-flip rate and label-A rate for all three judges in TODO.md.

- [ ] **Step 5: Real skill A/B demo.**
  - Two claude contestants with the same model and `baseline="real"`, each with a different `repo:.claude/skills/<x>` overlay, `repeats=3`. Pass: scorecard and HTML render, 6 runs done.
  - Once the user has exported `CLAUDE_CODE_OAUTH_TOKEN`, repeat with `baseline="clean"`. If it isn't set, record this as `[BLOCKED]` in TODO.md.

- [ ] **Step 6: Docs.**
  - Rewrite README around the experiment bench, using the pitch's structure: the four jobs, the contestant recipe, the 5 tools, a spec example with `[[contestants]]`, and the isolation facts.
  - Replace `docs/design.md` with the v0.3 design, linking `docs/v0.3-isolation-spike.md`.
  - Run `uv run agents-arena init --skills codex` to refresh `.agents/skills/agents-arena/SKILL.md`.
  - Update TODO.md: mark the done items, and record deferrals with reasons:
    - task suites
    - authenticated smoke-call preflight (static checks only in v0.3)
    - dollar cost for codex
  - Add a CHANGELOG 0.3.0 entry with the breaking changes and the old → new tool mapping.
  - Commit: `git add -A && git commit -qm "docs: v0.3 README, design, guide-based skill, changelog and TODO"`.

- [ ] **Step 7: Release.**
  - Bump `__version__` to `0.3.0` and commit `chore(release): v0.3.0`.
  - Push `revamp/v0.3` and open a PR, with base `revamp/v0.2` while PR #1 is open, otherwise `master`.
  - Confirm the CI matrix (macOS and Linux × 3.11/3.13) is green on the PR.
  - Tag `v0.3.0` only after the user confirms.
