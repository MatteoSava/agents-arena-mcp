"""Typed arena state. Everything persisted under .agents-arena/ round-trips through these models."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

CheckStatus = Literal["passed", "failed", "error", "timeout"]
GateSeverity = Literal["disqualify", "needs_human", "info"]


class FileChange(BaseModel):
    path: str
    status: str  # git name-status letter: A, M, D, R...
    added: int = 0
    removed: int = 0


class Snapshot(BaseModel):
    number: int
    commit: str
    ref: str
    patch_hash: str
    patch_path: str
    files: list[FileChange] = Field(default_factory=list)
    created_at: str

    @property
    def lines_changed(self) -> int:
        return sum(f.added + f.removed for f in self.files)


class TokenUsage(BaseModel):
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    cost_usd: float | None = None


class RunRecord(BaseModel):
    run_id: str
    runner: str
    model: str | None = None
    status: Literal["completed", "failed", "timeout", "error", "manual"]
    exit_code: int | None = None
    started_at: str
    wall_ms: int | None = None
    tokens: TokenUsage = Field(default_factory=TokenUsage)
    run_dir: str


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


class Variant(BaseModel):
    name: str
    strategy: str
    workspace: str
    state: Literal["created", "running", "ready", "failed", "closed"] = "created"
    parent: str | None = None  # "variant@checkpoint" this one was forked from
    depth: int = 0  # refinement depth
    runs: list[RunRecord] = Field(default_factory=list)
    snapshots: list[Snapshot] = Field(default_factory=list)
    checks: CheckReport | None = None
    gates: list[Gate] = Field(default_factory=list)

    @property
    def snapshot(self) -> Snapshot | None:
        return self.snapshots[-1] if self.snapshots else None


class Verdict(BaseModel):
    winner: Literal["A", "B", "tie"]
    confidence: float = 0.5
    reasons: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)


class Match(BaseModel):
    """One judge call. `first` was shown as A, `second` as B."""

    first: str
    second: str
    first_commit: str
    second_commit: str
    judge: str
    verdict: Verdict
    run_dir: str
    evidence: str = ""  # e.g. distinguishing-test output that informed this call

    @property
    def key(self) -> str:
        return f"{self.first}@{self.first_commit[:12]}|{self.second}@{self.second_commit[:12]}|{self.judge}|{self.evidence != ''}"

    @property
    def winner(self) -> str | None:
        return {"A": self.first, "B": self.second}.get(self.verdict.winner)


class Decision(BaseModel):
    status: Literal["winner", "needs_human", "no_viable"]
    winner: str | None = None
    ranking: list[str] = Field(default_factory=list)
    scores: dict[str, int] = Field(default_factory=dict)  # Copeland: pair wins - pair losses
    tie_break: str | None = None
    rationale: list[str] = Field(default_factory=list)


class Arena(BaseModel):
    id: str
    task: str
    repo_root: str
    base_ref: str
    base_commit: str
    carried_uncommitted: bool = False
    worktree_root: str
    status: Literal["open", "judged", "promoted", "closed"] = "open"
    variants: dict[str, Variant] = Field(default_factory=dict)
    pending_strategies: list[str] = Field(default_factory=list)  # explore-then-fork
    baseline: CheckReport | None = None
    matches: dict[str, Match] = Field(default_factory=dict)
    decision: Decision | None = None
    created_at: str


class Job(BaseModel):
    id: str
    op: str
    status: Literal["running", "done", "failed"] = "running"
    pid: int
    started_at: str
    ended_at: str | None = None
    progress: str = ""
    error: str | None = None
