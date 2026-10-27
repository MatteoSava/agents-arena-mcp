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
    assert not Path(done.worktree_root).exists() and not Path(done.worktree_root).parent.exists()
    assert len(git(repo, "worktree", "list").splitlines()) == 1
    assert git(repo, "for-each-ref", f"refs/arena/{arena.id}/").count("\n") == 5  # base + 4 runs


def test_clean_baseline_gets_its_own_home(repo, fakes, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "realhome"))
    store = Store(repo)
    s = spec(
        fakes, repeats=1, contestants=[command_contestant(fakes, "a", baseline="clean"), command_contestant(fakes, "b")]
    )
    arena = pipeline.create(store, s)
    pipeline.execute(store, arena.id, progress=lambda m: None)
    runs = store.load(arena.id).runs
    seen_clean = json.loads((Path(runs["a-1"].run_dir) / "env.json").read_text())
    seen_real = json.loads((Path(runs["b-1"].run_dir) / "env.json").read_text())
    assert seen_clean["HOME"].endswith("/a-1/home")
    assert seen_real["HOME"] == str(tmp_path / "realhome")


def test_checks_baseline_and_regression_gate(repo, fakes, monkeypatch):
    plans = {
        "a": {"write": {"app.py": "def value():\n    return 2\n"}},
        "b": {"write": {"app.py": "this is not python\n"}},
    }
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


def test_setup_runs_before_agent_and_is_not_counted(repo, fakes):
    store = Store(repo)
    s = spec(fakes, repeats=1, setup="echo built > built.txt", checks=[{"name": "built", "cmd": "test -f built.txt"}])
    arena = pipeline.create(store, s)
    pipeline.execute(store, arena.id, progress=lambda m: None)
    done = store.load(arena.id)
    assert done.baseline.status_of("built") == "passed"
    assert done.runs
    for run in done.runs.values():
        assert run.state == "done" and run.checks.status_of("built") == "passed"
        assert [f.path for f in run.snapshot.files] == ["app.py"]


def test_failing_setup_on_base_fails_the_arena(repo, fakes):
    store = Store(repo)
    s = spec(fakes, repeats=1, setup="false", checks=[{"name": "ok", "cmd": "true"}])
    arena = pipeline.create(store, s)
    with pytest.raises(ArenaError):
        pipeline.execute(store, arena.id, progress=lambda m: None)
    failed = store.load(arena.id)
    assert failed.status == "failed" and "setup" in failed.error


def test_agent_failure_records_stderr(repo, fakes):
    bad = {"name": "b", "harness": "command", "argv": ["sh", "-c", "echo login required >&2; exit 3"]}
    store = Store(repo)
    arena = pipeline.create(store, spec(fakes, repeats=1, contestants=[command_contestant(fakes, "a"), bad]))
    pipeline.execute(store, arena.id, progress=lambda m: None)
    done = store.load(arena.id)
    assert done.runs["b-1"].error.startswith("agent failed") and "login required" in done.runs["b-1"].error
    assert "login required" in " ".join(done.scorecard.notes)


def test_timed_out_agent_cannot_win(repo, fakes):
    slow = {"name": "a", "harness": "command", "argv": ["sh", "-c", "echo x > f.txt; sleep 5"]}
    store = Store(repo)
    arena = pipeline.create(store, spec(fakes, repeats=1, run_timeout_sec=1, contestants=[slow]))
    pipeline.execute(store, arena.id, progress=lambda m: None)
    run = store.load(arena.id).runs["a-1"]
    assert run.exit_status == "timeout" and not run.eligible
    assert any(g.kind == "agent_timeout" for g in run.gates)


def test_status_marks_arena_failed_when_its_job_died(repo, fakes):
    from agents_arena_mcp import arena as arena_ops
    from agents_arena_mcp.models import Job

    store = Store(repo)
    arena = pipeline.create(store, spec(fakes))
    job = Job(id="arena-1", op="arena", pid=999999, started_at="2026-01-01T00:00:00Z")
    jobs_dir = store.arena_dir(arena.id) / "jobs"
    jobs_dir.mkdir(parents=True, exist_ok=True)
    (jobs_dir / "arena-1.json").write_text(job.model_dump_json())
    status = arena_ops.arena_status(arena.id)
    assert status["status"] == "failed" and "died" in status["error"]
    assert store.load(arena.id).status == "failed"


def test_arena_ids_are_unique_within_a_second(repo, fakes):
    store = Store(repo)
    assert pipeline.create(store, spec(fakes)).id != pipeline.create(store, spec(fakes)).id


def test_state_dir_is_fully_ignored_by_git(repo):
    Store(repo).init()
    assert git(repo, "status", "--porcelain") == ""


def test_old_state_gitignore_is_upgraded(repo):
    state = repo / ".agents-arena"
    state.mkdir()
    (state / ".gitignore").write_text("*\n!.gitignore\n!config.toml\n")
    Store(repo).init()
    assert (state / ".gitignore").read_text() == "*\n" and git(repo, "status", "--porcelain") == ""


def test_setup_runs_in_the_real_environment_even_for_clean_contestants(repo, fakes, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "realhome"))
    store = Store(repo)
    s = spec(fakes, repeats=1, setup='echo "$HOME" > home.txt',
             contestants=[command_contestant(fakes, "a", baseline="clean")])  # fmt: skip
    arena = pipeline.create(store, s)
    pipeline.execute(store, arena.id, progress=lambda m: None)
    assert store.load(arena.id).runs["a-1"].state == "done"
    seen = git(repo, "show", f"refs/arena/{arena.id}/a-1-base:home.txt").strip()
    assert seen == str(tmp_path / "realhome")


def test_interrupt_kills_running_agents_and_marks_the_arena_failed(repo, fakes, monkeypatch):
    monkeypatch.setenv("FAKE_PLAN", json.dumps({"b": {"sleep": 30, "write": {"b.py": "1\n"}}}))
    store = Store(repo)
    arena = pipeline.create(store, spec(fakes, repeats=1))

    def progress(message):
        if message.startswith("1/2"):
            raise KeyboardInterrupt

    started = time.monotonic()
    with pytest.raises(KeyboardInterrupt):
        pipeline.execute(store, arena.id, progress)
    assert time.monotonic() - started < 15  # b's 30s agent was killed, not waited for
    done = store.load(arena.id)
    assert done.status == "failed" and "interrupted" in done.error


def test_foreground_start_is_tracked_as_a_job(repo, fakes):
    from agents_arena_mcp import arena as arena_ops

    started = arena_ops.arena_start(spec(fakes, repeats=1).model_dump(by_alias=True), wait=True)
    jobs = arena_ops.arena_status(started["arena_id"])["jobs"]
    assert [j["status"] for j in jobs] == ["done"]


def test_refs_created_during_the_arena_are_reported(repo, fakes):
    store = Store(repo)
    sneaky = {"name": "s", "harness": "command", "argv": ["sh", "-c", "git branch sneaky && echo 1 > f.txt"]}
    arena = pipeline.create(store, spec(fakes, repeats=1, contestants=[sneaky]))
    pipeline.execute(store, arena.id, progress=lambda m: None)
    notes = store.load(arena.id).scorecard.notes
    assert any("refs/heads/sneaky" in n for n in notes), notes


def test_stopping_cancels_background_arenas_and_cleans_up(repo, fakes, monkeypatch):
    from agents_arena_mcp import arena as arena_ops
    from agents_arena_mcp import jobs

    monkeypatch.setenv("FAKE_PLAN", json.dumps({"a": {"sleep": 30}}))
    started = arena_ops.arena_start(
        spec(fakes, repeats=1, contestants=[command_contestant(fakes, "a")]).model_dump(by_alias=True)
    )
    store = Store(repo)
    for _ in range(100):  # wait until the agent is running
        if store.load(started["arena_id"]).runs["a-1"].state == "running":
            break
        time.sleep(0.05)
    t0 = time.monotonic()
    jobs.stop_all(timeout=20)
    assert time.monotonic() - t0 < 15
    done = store.load(started["arena_id"])
    assert done.status == "failed" and "interrupted" in done.error
    assert not Path(done.worktree_root).exists()


def test_sigterm_on_the_cli_kills_agents_and_fails_the_arena(repo, tmp_path):
    import os
    import secrets
    import signal
    import subprocess

    marker = f"61.{secrets.randbelow(10**6):06d}"  # unique, so pgrep only sees this test's agent
    spec_file = tmp_path / "spec.json"
    spec_file.write_text(json.dumps({"task": "t", "judge": {"harness": "none"}, "contestants": [
        {"name": "s", "harness": "command", "argv": ["sh", "-c", f"sleep {marker}"]}]}))  # fmt: skip
    cli = subprocess.Popen(
        [sys.executable, "-c", "import sys; from agents_arena_mcp.cli import main; sys.exit(main())",
         "start", str(spec_file)], env=os.environ.copy(), stdout=subprocess.PIPE, stderr=subprocess.PIPE)  # fmt: skip
    for _ in range(100):
        if subprocess.run(["pgrep", "-f", f"^sleep {marker}"], capture_output=True).returncode == 0:
            break
        time.sleep(0.1)
    cli.send_signal(signal.SIGTERM)
    code = cli.wait(timeout=20)
    assert code == 128 + signal.SIGTERM, cli.stderr.read().decode()[-1500:]
    assert subprocess.run(["pgrep", "-f", f"^sleep {marker}"], capture_output=True).returncode == 1  # agent is gone
    store = Store(repo)
    done = store.load()
    assert done.status == "failed" and "interrupted" in done.error
    assert not Path(done.worktree_root).exists()
