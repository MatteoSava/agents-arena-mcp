"""Check execution, the base-commit baseline, and deterministic gates (including reward-hacking tripwires).

Trust model: checks run agent-written code on the host with your privileges, like `make test` on an
untrusted branch. Check commands come only from the main repo's config or the calling agent.
"""

from __future__ import annotations

import re
import tempfile
from pathlib import Path

from agents_arena_mcp import git, proc
from agents_arena_mcp.config import CheckSpec, Config
from agents_arena_mcp.models import Arena, CheckReport, CheckResult, Gate, Variant

TEST_PATH = re.compile(r"(^|/)(tests?|__tests__|spec)/|(^|/)test_[^/]+\.py$|_test\.(py|go)$|\.(test|spec)\.[jt]sx?$")
TEST_CONFIG = re.compile(
    r"(^|/)(conftest\.py|pytest\.ini|tox\.ini|setup\.cfg|jest\.config\.[a-z]+|vitest\.config\.[a-z]+)$"
)
SKIP_MARKER = re.compile(
    r"@pytest\.mark\.(skip|xfail)|pytest\.skip\(|@unittest\.skip|\b(it|test|describe)\.skip\(|\bxit\(|t\.Skip\("
)
TRIVIAL_ASSERT = re.compile(r"^\s*assert\s+(True|1)\s*$|expect\(true\)\.toBe\(true\)")


def run_checks(specs: list[CheckSpec], workdir: Path, commit: str, timeout: int, owner: str) -> CheckReport:
    results = []
    for spec in specs:
        out = proc.shell(spec.cmd, workdir, timeout, owner=owner)
        results.append(
            CheckResult(
                name=spec.name,
                cmd=spec.cmd,
                status=out.status,  # type: ignore[arg-type]
                exit_code=out.exit_code,
                duration_ms=out.wall_ms,
                tail=proc.tail(out.stdout + out.stderr, 2000),
            )
        )
    return CheckReport(commit=commit, results=results)


def baseline(arena: Arena, config: Config) -> CheckReport:
    """Run the checks once on the base commit, in a throwaway worktree. Cached by commit on the arena."""
    if arena.baseline and arena.baseline.commit == arena.base_commit:
        return arena.baseline
    root = Path(arena.repo_root)
    with tempfile.TemporaryDirectory(prefix="arena-baseline-") as tmp:
        path = Path(tmp) / "base"
        git.worktree_add(root, path, arena.base_commit)
        try:
            if config.setup:
                proc.shell(config.setup, path, config.check_timeout_sec, owner=arena.id)
            return run_checks(config.checks, path, arena.base_commit, config.check_timeout_sec, arena.id)
        finally:
            git.worktree_remove(root, path)


def gates(arena: Arena, variant: Variant, config: Config) -> list[Gate]:
    snap = variant.snapshot
    if snap is None or not snap.files:
        return [Gate(kind="empty", severity="disqualify", detail="no changes")]
    found: list[Gate] = []
    for f in snap.files:
        if f.status == "D" and TEST_PATH.search(f.path):
            found.append(Gate(kind="test_deleted", severity="disqualify", detail=f.path))
        if any(f.path.startswith(p) or f.path == p.rstrip("/") for p in config.protected_paths):
            found.append(Gate(kind="protected_path", severity="disqualify", detail=f.path))
        if any(re.search(p, f.path, re.IGNORECASE) for p in config.secret_patterns):
            found.append(Gate(kind="secret_path", severity="needs_human", detail=f.path))
        if TEST_CONFIG.search(f.path):
            found.append(Gate(kind="test_config_changed", severity="needs_human", detail=f.path))
        elif f.status == "M" and TEST_PATH.search(f.path):
            # Legitimate for test-first work, so report it rather than block.
            found.append(Gate(kind="existing_test_edited", severity="info", detail=f.path))
    for line in _added_lines(Path(snap.patch_path)):
        if SKIP_MARKER.search(line):
            found.append(Gate(kind="skip_marker_added", severity="needs_human", detail=line.strip()[:120]))
        elif TRIVIAL_ASSERT.search(line):
            found.append(Gate(kind="trivial_assert_added", severity="needs_human", detail=line.strip()[:120]))
    if variant.checks and arena.baseline:
        for result in variant.checks.results:
            before = arena.baseline.status_of(result.name)
            if result.status != "passed" and before == "passed":
                found.append(Gate(kind="check_regression", severity="disqualify", detail=result.name))
            elif result.status != "passed":
                found.append(Gate(kind="check_failing_on_base_too", severity="info", detail=result.name))
    return found


def _added_lines(patch_path: Path) -> list[str]:
    lines = patch_path.read_bytes().decode("utf-8", "replace").splitlines()
    return [line[1:] for line in lines if line.startswith("+") and not line.startswith("+++")]


def failing_count(variant: Variant) -> int:
    return sum(1 for r in (variant.checks.results if variant.checks else []) if r.status != "passed")
