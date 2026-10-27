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
