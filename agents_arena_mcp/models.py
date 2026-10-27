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

    model_config = ConfigDict(validate_by_name=True, serialize_by_alias=True, extra="forbid")
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
    model_config = ConfigDict(extra="forbid")

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
    model_config = ConfigDict(extra="forbid")

    name: str
    cmd: str


class JudgeSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    harness: Literal["claude", "codex", "opencode", "command", "none"] = "claude"
    model: str = ""
    argv: list[str] = Field(default_factory=list)  # harness="command": {prompt_file} {output_file} {schema_file}
    timeout_sec: int = 600


class Spec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task: str
    objective: str = "quality"  # quality | elegance | speed | tokens | cost | any custom rubric text
    repeats: int = Field(1, ge=1, le=20)
    checks: list[Check] = Field(default_factory=list)
    setup: str = ""  # shell command run in the baseline and in each run's worktree before the agent, e.g. "npm ci"
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
    pass_rate: float  # eligible runs / runs (non-empty change, no disqualifying gate)
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
