"""Full workflow with fake agent and judge CLIs: open -> run -> check -> judge -> promote -> close."""

from __future__ import annotations

import time
from pathlib import Path

from conftest import git, write_config

from agents_arena_mcp import arena as ops
from agents_arena_mcp.store import Store


def test_full_workflow_leaves_repo_clean(repo: Path, fakes):
    write_config(repo, fakes, extra="[judge]\nrunner = 'fake'")
    opened = ops.arena_open("make value() return the variant name", variants=["alpha", "beta"])

    ran = ops.arena_run(wait=True)
    assert {v["state"] for v in ran["variants"].values()} == {"ready"}

    checked = ops.arena_check()
    alpha = Store(repo).load().variants["alpha"]
    assert alpha.snapshot is not None
    assert {(f.path, f.status) for f in alpha.snapshot.files} == {
        ("app.py", "M"),
        ("new_alpha.py", "A"),
        ("blob.bin", "A"),
        ("old.txt", "D"),
    }
    assert checked["variants"]["beta"]["checkpoints"] == [1]
    assert alpha.runs[0].tokens.total_tokens == 15

    judged = ops.arena_judge(wait=True)
    # The fake judge sees no GOOD marker, so every pair ties and the deterministic tie-break decides.
    assert judged["decision"]["status"] in {"winner", "needs_human"}
    report = (Store(repo).arena_dir(opened["arena_id"]) / "report.md").read_text()
    assert "alpha vs beta" in report

    promoted = ops.arena_promote(variant="alpha", mode="branch")
    assert git(repo, "rev-parse", "--abbrev-ref", "HEAD").strip() == "main"
    assert git(repo, "show", f"{promoted['branch']}:app.py") == "def value():\n    return 'alpha'\n"
    assert Path(promoted["pr_summary"]).exists()

    ops.arena_close()
    assert git(repo, "for-each-ref", "refs/arena/").strip() == ""
    assert len(git(repo, "worktree", "list").splitlines()) == 1
    # Only the committable config files are visible; all arena state is ignored.
    assert git(repo, "status", "--porcelain", "-uall").split() == [
        "??",
        ".agents-arena/.gitignore",
        "??",
        ".agents-arena/config.toml",
    ]
    assert (Store(repo).root / "ledger.jsonl").exists()


def test_apply_mode_applies_patch_to_working_tree(repo: Path, fakes):
    write_config(repo, fakes)
    ops.arena_open("task", variants=["alpha"])
    ops.arena_run(wait=True)
    ops.arena_check()
    ops.arena_judge(wait=True)

    ops.arena_promote(mode="apply")

    assert (repo / "app.py").read_text() == "def value():\n    return 'alpha'\n"
    assert (repo / "new_alpha.py").exists()
    assert not (repo / "old.txt").exists()


def test_variants_run_in_parallel(repo: Path, fakes, monkeypatch):
    monkeypatch.setenv("FAKE_RUNNER_SLEEP", "1")
    write_config(repo, fakes, extra="max_parallel = 4")
    ops.arena_open("task", variants=["a", "b", "c", "d"])

    started = time.monotonic()
    ops.arena_run(wait=True)
    elapsed = time.monotonic() - started

    spans = []
    for v in Store(repo).load().variants.values():
        start, end = map(float, (Path(v.runs[0].run_dir) / "times.txt").read_text().split())
        spans.append((start, end))
    latest_start = max(s for s, _ in spans)
    earliest_end = min(e for _, e in spans)
    assert latest_start < earliest_end, "all four runs should overlap"
    assert elapsed < 3.5


def test_background_job_reports_completion(repo: Path, fakes):
    write_config(repo, fakes)
    ops.arena_open("task", variants=["a"])

    started = ops.arena_run(wait=False)
    assert started["job"]["status"] == "running"

    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        jobs = ops.arena_status()["jobs"]
        if jobs and jobs[0]["status"] != "running":
            break
        time.sleep(0.1)
    assert jobs[0]["status"] == "done", jobs
    assert ops.arena_status()["variants"]["a"]["state"] == "ready"


def test_manual_runner_returns_briefs(repo: Path):
    ops.arena_open("do the thing", variants=["a"])
    out = ops.arena_run(runner="manual")
    assert "do the thing" in out["briefs"]["a"]
    assert "Leave changes uncommitted" in out["briefs"]["a"]
