"""Arena operations. Each function is both an MCP tool and a CLI subcommand (see OPS)."""

from __future__ import annotations

import os
import re
import shutil
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from string import Template
from typing import Annotated, Any, Literal

from fastmcp import Context
from pydantic import Field

from agents_arena_mcp import checks, git, jobs, proc, report, runners, select, workspace
from agents_arena_mcp.config import Config, load_config, template_text
from agents_arena_mcp.errors import ArenaError
from agents_arena_mcp.judge import agentic_round, run_pairs
from agents_arena_mcp.models import Arena, RunRecord, Variant
from agents_arena_mcp.store import Store, utc_now

ArenaId = Annotated[str | None, Field(description="Arena id; defaults to the most recently opened arena.")]
Names = Annotated[list[str] | None, Field(description="Variant names; defaults to all open variants.")]
Wait = Annotated[bool, Field(description="Block until done. False starts a background job; poll arena_status.")]


# ---- shared helpers -----------------------------------------------------------------------------
def context() -> tuple[Store, Config]:
    start = Path(os.environ.get("AGENTS_ARENA_ROOT") or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
    root = git.repo_root(start)
    return Store(root), load_config(root)


def slugify(value: str, max_len: int = 40) -> str:
    value = re.sub(r"[^a-z0-9_]+", "-", value.strip().lower()).strip("-")
    return (value or "item")[:max_len].rstrip("-")


def brief(arena: Arena, variant: Variant, extra: str = "") -> str:
    override = load_config(Path(arena.repo_root)).brief_template
    tmpl = Template(template_text(Path(arena.repo_root), override, "brief.md.tmpl"))
    return tmpl.safe_substitute(
        variant=variant.name, workspace=variant.workspace, task=arena.task, strategy=variant.strategy, extra=extra
    )


def selected(arena: Arena, names: list[str] | None) -> list[Variant]:
    pool = [v for v in arena.variants.values() if v.state != "closed"]
    if not names:
        return pool
    unknown = sorted(set(names) - set(arena.variants))
    if unknown:
        raise ArenaError(f"Unknown variant(s): {', '.join(unknown)}")
    return [arena.variants[n] for n in names]


def summary(arena: Arena) -> dict[str, Any]:
    d = arena.decision
    return {
        "arena_id": arena.id,
        "status": arena.status,
        "decision": d.model_dump() if d else None,
        "variants": {
            v.name: {
                "state": v.state,
                "workspace": v.workspace,
                "parent": v.parent,
                "checkpoints": [s.number for s in v.snapshots],
                "files_changed": len(v.snapshot.files) if v.snapshot else None,
                "checks": {r.name: r.status for r in v.checks.results} if v.checks else None,
                "gates": [f"{g.kind}[{g.severity}]: {g.detail}" for g in v.gates],
            }
            for v in arena.variants.values()
        },
    }


# ---- operations ---------------------------------------------------------------------------------
def arena_open(
    task: Annotated[str, Field(description="What the variants should implement.")],
    variants: Annotated[list[str] | None, Field(description="Strategy names; defaults to config.")] = None,
    base_ref: Annotated[str, Field(description="Commit or branch to start from.")] = "HEAD",
    carry_uncommitted: Annotated[bool, Field(description="Start from your uncommitted changes too.")] = False,
    explore: Annotated[
        bool, Field(description="Create only an `explore` variant; fork strategies from it later.")
    ] = False,
) -> dict[str, Any]:
    """Open an arena: one isolated worktree per strategy variant. Returns workspaces and briefs."""
    store, config = context()
    store.init()
    root = store.repo_root
    names = [slugify(v) for v in (variants or config.default_variants)]
    if len(set(names)) != len(names) or not names:
        raise ArenaError("Variant names must be non-empty and unique.")
    if len(names) > config.max_variants:
        raise ArenaError(f"At most {config.max_variants} variants (max_variants in config).")
    base = git.rev_parse(root, base_ref)
    dirty = git.is_dirty(root)
    if dirty and not carry_uncommitted:
        raise ArenaError("Working tree has uncommitted changes. Commit/stash them, or pass carry_uncommitted=true.")
    if dirty:
        base = git.snapshot_commit(root, base, "arena base: uncommitted changes")
    arena_id = f"{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}-{slugify(task, 32)}"
    arena = Arena(
        id=arena_id,
        task=task,
        repo_root=str(root),
        base_ref=base_ref,
        base_commit=base,
        carried_uncommitted=dirty,
        worktree_root=str(workspace.default_root(root, config.worktree_root) / arena_id),
        pending_strategies=names if explore else [],
        created_at=utc_now(),
    )
    git.update_ref(root, f"refs/arena/{arena_id}/base", base)  # keep the base reachable for --3way apply
    try:
        for name in ["explore"] if explore else names:
            path = workspace.create(arena, name, base, config.setup, config.run_timeout_sec)
            arena.variants[name] = Variant(name=name, strategy=config.strategy_text(name), workspace=str(path))
    except Exception:
        _teardown(arena)
        raise
    store.save(arena)
    store.set_current(arena_id)
    store.event(arena_id, "open", variants=list(arena.variants))
    out = summary(arena)
    out["briefs"] = {v.name: brief(arena, v) for v in arena.variants.values()}
    return out


def arena_status(
    arena_id: ArenaId = None,
    variant: Annotated[str | None, Field(description="Include this variant's brief.")] = None,
) -> dict[str, Any]:
    """Arena overview: variant states, checkpoints, checks, gates, decision, and background jobs."""
    store, _ = context()
    arena = store.load(arena_id)
    out = summary(arena)
    out["jobs"] = [j.model_dump() for j in jobs.list_jobs(store, arena.id)]
    if variant:
        out["brief"] = brief(arena, selected(arena, [variant])[0])
    return out


def arena_run(
    arena_id: ArenaId = None,
    variants: Names = None,
    runner: Annotated[str | None, Field(description="A [runners.*] key from config, or 'manual'.")] = None,
    model: Annotated[str, Field(description="Model passed to the runner.")] = "",
    timeout_sec: Annotated[int | None, Field(description="Per-variant timeout.")] = None,
    wait: Wait = False,
    ctx: Context | None = None,
) -> dict[str, Any]:
    """Run an implementation agent in each selected variant's workspace, in parallel."""
    store, config = context()
    arena = store.load(arena_id)
    targets = selected(arena, variants)
    name = runner or config.default_runner
    if name == "manual":
        record = RunRecord(
            run_id=runners.new_run_id("manual"), runner="manual", status="manual", started_at=utc_now(), run_dir=""
        )
        with store.mutate(arena.id) as a:
            for v in targets:
                a.variants[v.name].runs.append(record)
        return {"arena_id": arena.id, "runner": "manual", "briefs": {v.name: brief(arena, v) for v in targets}}
    spec = runners.lookup(config.runners, name, "runner")

    def one(v: Variant) -> None:
        with store.mutate(arena.id) as a:
            a.variants[v.name].state = "running"
        run_dir = store.arena_dir(arena.id) / "runs" / runners.new_run_id(v.name)
        prompt = brief(arena, v, extra=_extra_brief(store, arena.id, v.name))
        record = runners.run_agent(
            spec, name, Path(v.workspace), prompt, run_dir, model, timeout_sec or config.run_timeout_sec, arena.id
        )
        with store.mutate(arena.id) as a:
            a.variants[v.name].runs.append(record)
            a.variants[v.name].state = "ready" if record.status == "completed" else "failed"
        store.event(arena.id, "run", variant=v.name, status=record.status, run_id=record.run_id)

    def work(progress) -> None:
        done = 0
        with ThreadPoolExecutor(max_workers=max(1, config.max_parallel)) as pool:
            for future in [pool.submit(one, v) for v in targets]:
                future.result()
                done += 1
                progress(f"{done}/{len(targets)} variants finished")

    return jobs.in_background(store, arena.id, "run", wait, ctx, work) or summary(store.load(arena.id))


def _extra_brief(store: Store, arena_id: str, name: str) -> str:
    path = store.arena_dir(arena_id) / "variants" / name / "extra-brief.md"
    return path.read_text(encoding="utf-8") if path.exists() else ""


def arena_check(arena_id: ArenaId = None, variants: Names = None) -> dict[str, Any]:
    """Snapshot each variant (a new checkpoint), run configured checks vs. the base-commit baseline, apply gates."""
    store, config = context()
    arena = store.load(arena_id)
    if config.checks and not (arena.baseline and arena.baseline.commit == arena.base_commit):
        baseline = checks.baseline(arena, config)
        with store.mutate(arena.id) as a:
            a.baseline = baseline
    for v in selected(arena, variants):
        with store.mutate(arena.id) as a:
            snap = workspace.snapshot(store, a, a.variants[v.name])
        report_ = checks.run_checks(config.checks, Path(v.workspace), snap.commit, config.check_timeout_sec, arena.id)
        with store.mutate(arena.id) as a:
            current = a.variants[v.name]
            current.checks = report_
            current.gates = checks.gates(a, current, config)
            if current.state != "failed":
                current.state = "ready"
        store.event(arena.id, "check", variant=v.name, checkpoint=snap.number, passed=report_.passed)
    return summary(store.load(arena.id))


def arena_judge(
    arena_id: ArenaId = None,
    judge: Annotated[str | None, Field(description="A [judges.*] key, or 'none' for deterministic only.")] = None,
    model: Annotated[str | None, Field(description="Judge model override.")] = None,
    wait: Wait = False,
    ctx: Context | None = None,
) -> dict[str, Any]:
    """Judge surviving variants pairwise in both orders (blind A/B), then decide and write report.md."""
    store, config = context()
    if judge is not None:
        config.judge.runner = judge
    if model is not None:
        config.judge.model = model
    arena = store.load(arena_id)
    if any(v.snapshot is None for v in arena.variants.values() if v.state != "closed"):
        raise ArenaError("Run arena_check first: every open variant needs a checkpoint.")
    if jobs.running(store, arena.id):
        raise ArenaError("A background job is still running; wait for it (see arena_status).")
    names, notes = select.survivors(arena, config.judge.max_survivors)
    judged = config.judge.runner != "none" and len(names) > 1

    def work(progress) -> None:
        if judged:
            run_pairs(store, arena.id, config, names, progress)
            if config.judge.agentic_final:
                provisional = select.decide(store.load(arena.id), names, True, notes)
                agentic_round(store, arena.id, config, provisional.ranking[:2])
                progress("agentic final round done")
        with store.mutate(arena.id) as a:
            a.decision = select.decide(a, names, judged, notes)
            a.status = "judged"
        final = store.load(arena.id)
        (store.arena_dir(arena.id) / "report.md").write_text(report.render(final), encoding="utf-8")
        store.ledger(report.ledger_record(final, config, promoted=False))

    return jobs.in_background(store, arena.id, "judge", wait, ctx, work) or summary(store.load(arena.id))


def arena_promote(
    arena_id: ArenaId = None,
    variant: Annotated[str | None, Field(description="Variant to promote; defaults to the decided winner.")] = None,
    mode: Annotated[
        Literal["patch", "branch", "apply"],
        Field(
            description="patch: write files only; branch: create a branch at the variant snapshot (your checkout is untouched); apply: git apply --3way into your working tree."
        ),
    ] = "patch",
) -> dict[str, Any]:
    """Promote a variant: winner patch + PR summary, optionally as a branch or applied to your tree."""
    store, config = context()
    arena = store.load(arena_id)
    d = arena.decision
    if variant is None:
        if d is None or d.winner is None or d.status != "winner":
            raise ArenaError(
                f"No clear winner (decision: {d.status if d else 'not judged'}). Pass variant= explicitly. "
                + "; ".join(d.rationale if d else [])
            )
        variant = d.winner
    v = selected(arena, [variant])[0]
    if v.snapshot is None:
        raise ArenaError(f"{variant} has no checkpoint; run arena_check first.")
    out_dir = store.arena_dir(arena.id)
    patch_path = out_dir / "winner.diff"
    shutil.copyfile(v.snapshot.patch_path, patch_path)
    report_path = out_dir / "report.md"
    if not report_path.exists():
        report_path.write_text(report.render(arena), encoding="utf-8")
    summary_path = out_dir / "pr-summary.md"
    summary_path.write_text(report.pr_summary(arena, v, report_path), encoding="utf-8")
    result: dict[str, Any] = {
        "arena_id": arena.id,
        "variant": variant,
        "mode": mode,
        "patch": str(patch_path),
        "pr_summary": str(summary_path),
    }
    root = Path(arena.repo_root)
    if mode == "branch":
        branch = f"arena/{arena.id}-{variant}"
        git.create_branch(root, branch, v.snapshot.commit)
        result["branch"] = branch
        if arena.carried_uncommitted:
            result["note"] = "The branch includes a commit with your uncommitted changes from when the arena opened."
    elif mode == "apply":
        git.apply_3way(root, patch_path)
    with store.mutate(arena.id) as a:
        a.status = "promoted"
    store.event(arena.id, "promote", variant=variant, mode=mode)
    store.ledger({"arena_id": arena.id, "promoted": variant, "mode": mode})
    return result


def arena_close(
    arena_id: ArenaId = None,
    keep_artifacts: Annotated[bool, Field(description="Keep reports, patches and logs under .agents-arena/.")] = True,
) -> dict[str, Any]:
    """Close an arena: stop its processes, remove worktrees and refs/arena/<id>. Artifacts are kept by default."""
    store, _ = context()
    arena = store.load(arena_id)
    killed = proc.kill_owned(arena.id)
    _teardown(arena)
    with store.mutate(arena.id) as a:
        a.status = "closed"
        for v in a.variants.values():
            v.state = "closed"
    store.event(arena.id, "close", killed=killed)
    if not keep_artifacts:
        shutil.rmtree(store.arena_dir(arena.id), ignore_errors=True)
    return {"arena_id": arena.id, "closed": True, "killed_processes": killed, "artifacts_kept": keep_artifacts}


def _teardown(arena: Arena) -> None:
    root = Path(arena.repo_root)
    for v in arena.variants.values():
        workspace.destroy(arena, v)
    shutil.rmtree(arena.worktree_root, ignore_errors=True)
    git.delete_refs(root, f"refs/arena/{arena.id}/")
    git.worktree_prune(root)


OPS = (arena_open, arena_status, arena_run, arena_check, arena_judge, arena_promote, arena_close)
