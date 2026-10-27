"""The engine behind arena_start: preflight -> baseline -> runs (contestant x repeat) -> judging -> scorecard."""

from __future__ import annotations

import re
import secrets
import shutil
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from string import Template

from agents_arena_mcp import checks, git, harness, judge, proc, scorecard, workspace
from agents_arena_mcp.config_data import data_text
from agents_arena_mcp.errors import ArenaError
from agents_arena_mcp.models import Arena, Contestant, Run, Spec
from agents_arena_mcp.store import Store, utc_now, write_atomic

Progress = Callable[[str], None]
USER_REFS = ("refs/heads", "refs/tags", "refs/stash")  # where an agent in a worktree can leave refs


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
    arena_id = f"{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}-{slugify(spec.task)}-{secrets.token_hex(2)}"
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
        if spec.setup:
            # setup and checks are the spec author's commands: they run in your environment, like the baseline
            out = proc.shell(spec.setup, ws, spec.check_timeout_sec, owner=arena_id)
            if not out.ok:
                raise ArenaError(f"setup failed ({out.status}): {proc.tail(out.stdout + out.stderr, 800)}")
        base = workspace.overlay_base(arena, run, ws, any(o.scope == "repo" for o in c.overlays) or bool(spec.setup))
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
            if out.status != "passed":
                r.error = f"agent {out.status}: {proc.tail(out.stderr or out.stdout, 600)}"
            r.snapshot = workspace.snapshot(store, a, r, ws)
            snap_commit = r.snapshot.commit
        report = (
            checks.run_checks(spec.checks, ws, snap_commit, spec.check_timeout_sec, arena_id) if spec.checks else None
        )
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
    arena = store.load(arena_id)
    root = Path(arena.repo_root)
    try:
        if arena.spec.checks or arena.spec.setup:
            progress("running baseline checks on the base commit")
            report = checks.baseline(arena)
            with store.mutate(arena_id) as a:
                a.baseline = report
        total, refs_before = len(arena.runs), git.list_refs(root, *USER_REFS)
        with ThreadPoolExecutor(max_workers=arena.spec.max_parallel) as pool:
            futures = [pool.submit(run_one, store, arena_id, run_id) for run_id in arena.runs]
            try:
                for done, future in enumerate(as_completed(futures), 1):
                    future.result()
                    progress(f"{done}/{total} runs finished")
            except KeyboardInterrupt:
                proc.cancel(arena_id)  # agents run in their own process groups; Ctrl-C alone doesn't reach them
                raise
        with store.mutate(arena_id) as a:
            a.new_refs = sorted(git.list_refs(root, *USER_REFS) - refs_before)
        finish(store, arena_id, progress)
    except KeyboardInterrupt:
        proc.cancel(arena_id)
        _fail(store, arena_id, "interrupted (Ctrl-C); running agents and judges were killed")
        raise
    except Exception as exc:
        _fail(store, arena_id, f"{type(exc).__name__}: {exc}")
        raise
    finally:
        workspace.remove_root(arena)


def _fail(store: Store, arena_id: str, error: str) -> None:
    with store.mutate(arena_id) as a:
        a.status, a.error, a.finished_at = "failed", error, utc_now()


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
    """patch: write winner.diff; branch: commit it on the base without checkout; apply: git apply."""
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
    root, result = (
        Path(arena.repo_root),
        {"arena_id": arena.id, "winner": card.winner, "run": run.id, "patch": str(patch)},
    )
    if mode == "branch":
        branch = f"arena/{arena.id}-{card.winner}"
        if git.git(root, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}", check=False):
            raise ArenaError(f"Branch {branch} already exists; delete it or promote with mode='patch'")
        git.create_branch(root, branch, git.commit_patch(root, arena.base_commit, patch, f"arena {arena.id}: {run.id}"))
        result["branch"] = branch
    elif mode == "apply":
        git.apply_patch(root, patch)
    store.event(arena.id, "promote", mode=mode, run=run.id)
    return result
