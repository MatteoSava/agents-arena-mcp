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
    skip = run_with(
        [FileChange(path="tests/test_x.py", status="A")], "+@pytest.mark.skip\n+def test_x(): pass\n", tmp_path=tmp_path
    )
    assert ("skip_marker_added", "needs_human") in kinds(checks.gates(skip, None))


def test_regressions_vs_baseline(tmp_path):
    base = CheckReport(
        commit="b",
        results=[
            CheckResult(name="t", cmd="x", status="passed", duration_ms=1),
            CheckResult(name="l", cmd="y", status="failed", duration_ms=1),
        ],
    )
    mine = CheckReport(
        commit="c",
        results=[
            CheckResult(name="t", cmd="x", status="failed", duration_ms=1),
            CheckResult(name="l", cmd="y", status="failed", duration_ms=1),
        ],
    )
    run = run_with([FileChange(path="app.py", status="M")], checks_report=mine, tmp_path=tmp_path)
    got = kinds(checks.gates(run, base))
    assert ("check_regression", "disqualify") in got and ("check_failing_on_base_too", "info") in got


def test_run_checks_records_missing_tool_and_timeout(tmp_path):
    report = checks.run_checks(
        [Check(name="missing", cmd="definitely-not-a-tool-xyz"), Check(name="slow", cmd="sleep 5")],
        tmp_path,
        "c",
        timeout=1,
        owner="t",
    )
    assert [r.status for r in report.results] == ["error", "timeout"]
