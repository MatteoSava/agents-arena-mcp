"""Checks, the base-commit baseline, and deterministic gates (including reward-hacking tripwires).

Trust model: checks and contestants run agent-written code on the host with your privileges, like
`make test` on an untrusted branch. Check commands come only from the spec.
"""

from __future__ import annotations

import re
import tempfile
from pathlib import Path

from agents_arena_mcp import git, proc
from agents_arena_mcp.errors import ArenaError
from agents_arena_mcp.models import Arena, Check, CheckReport, CheckResult, Gate, Run

PROTECTED = (".github/workflows/", ".gitlab-ci.yml", ".agents-arena/")
AGENT_CONFIG_DIRS = (".claude/", ".codex/", ".opencode/", ".agents/")
AGENT_CONFIG_FILES = ("AGENTS.md", "CLAUDE.md")
SECRET = (r"(^|/)\.env($|\.)", r"(^|/)secrets?(/|\.[a-z0-9]+$|$)", r"(^|/)credentials?(/|\.[a-z0-9]+$|$)",
          r"private[_-]?key", r"(^|/)id_(rsa|ed25519)")  # fmt: skip
TEST_PATH = re.compile(r"(^|/)(tests?|__tests__|spec)/|(^|/)test_[^/]+\.py$|_test\.(py|go)$|\.(test|spec)\.[jt]sx?$")
TEST_CONFIG = re.compile(
    r"(^|/)(conftest\.py|pytest\.ini|tox\.ini|setup\.cfg|jest\.config\.[a-z]+|vitest\.config\.[a-z]+)$"
)
SKIP_MARKER = re.compile(
    r"@pytest\.mark\.(skip|xfail)|pytest\.skip\(|@unittest\.skip|\b(it|test|describe)\.skip\(|\bxit\(|t\.Skip\("
)
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
            if arena.spec.setup:
                out = proc.shell(arena.spec.setup, path, arena.spec.check_timeout_sec, owner=arena.id)
                if not out.ok:
                    raise ArenaError(
                        f"setup failed on the base commit ({out.status}): {proc.tail(out.stdout + out.stderr, 800)}"
                    )
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
