"""The five operations. Each is both an MCP tool and a CLI subcommand (OPS)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated, Any, Literal

from fastmcp import Context
from pydantic import Field, ValidationError

from agents_arena_mcp import git, jobs, pipeline, plan, scorecard
from agents_arena_mcp.errors import ArenaError
from agents_arena_mcp.models import Spec
from agents_arena_mcp.store import Store, utc_now, write_atomic

ArenaId = Annotated[str | None, Field(description="Arena id; defaults to the most recently started arena.")]


def store() -> Store:
    start = Path(os.environ.get("AGENTS_ARENA_ROOT") or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
    return Store(git.repo_root(start))


def arena_plan(
    request: Annotated[str, Field(description="What the user wants to compare or find, in their words.")],
    mode: Annotated[
        Literal["interview", "autopilot"],
        Field(description="interview: return questions to ask the user; autopilot: return a filled draft to adapt."),
    ] = "interview",
) -> dict[str, Any]:
    """Draft an arena spec: detected checks and setup, installed harnesses, and questions (interview) or a full draft (autopilot). Runs nothing."""
    return plan.make_plan(store().repo_root, request, mode)


def arena_start(
    spec: Annotated[dict[str, Any], Field(description="The arena spec (see arena_plan's draft_spec and spec_schema).")],
    wait: Annotated[
        bool, Field(description="Block until done. False runs in the background; poll arena_status.")
    ] = False,
    ctx: Context | None = None,
) -> dict[str, Any]:
    """Validate the spec, run preflight, then run every contestant x repeat in isolation, judge, and score."""
    try:
        parsed = Spec.model_validate(spec)
    except ValidationError as exc:
        raise ArenaError(f"Invalid spec: {exc}") from exc
    s = store()
    arena = pipeline.create(s, parsed)
    handle = jobs.in_background(
        s, arena.id, "arena", wait, ctx, lambda progress: pipeline.execute(s, arena.id, progress)
    )
    return handle or arena_status(arena.id)


def arena_status(arena_id: ArenaId = None) -> dict[str, Any]:
    """Arena progress: each run's state, exit status, eligibility, and background job progress."""
    s = store()
    arena = s.load(arena_id)
    all_jobs = jobs.list_jobs(s, arena.id)
    if arena.status == "running" and all_jobs and all(j.status == "failed" for j in all_jobs):
        with s.mutate(arena.id) as a:
            a.status, a.finished_at = "failed", utc_now()
            a.error = "background job died (server exited?); worktrees may remain under " + a.worktree_root
        arena = s.load(arena.id)
    return {
        "arena_id": arena.id, "status": arena.status, "error": arena.error,
        "runs": {r.id: {"state": r.state, "exit": r.exit_status, "eligible": r.eligible, "error": r.error}
                 for r in arena.runs.values()},
        "jobs": [j.model_dump() for j in all_jobs],
        "verdict": arena.scorecard.verdict if arena.scorecard else None,
    }  # fmt: skip


def arena_result(
    arena_id: ArenaId = None,
    html: Annotated[bool, Field(description="Also write a self-contained HTML report and return its path.")] = False,
    promote: Annotated[
        Literal["patch", "branch", "apply"] | None,
        Field(
            description="Ship the winner: patch (write winner.diff), branch (create arena/<id>-<winner> without touching your checkout), apply (git apply into your tree only if it applies cleanly)."
        ),
    ] = None,
) -> dict[str, Any]:
    """The scorecard: per-contestant medians, the winner for the objective, the verdict and notes."""
    s = store()
    arena = s.load(arena_id)
    if arena.scorecard is None:
        raise ArenaError(f"Arena {arena.id} is {arena.status}; no scorecard yet. Check arena_status.")
    out: dict[str, Any] = {
        "arena_id": arena.id,
        "scorecard": arena.scorecard.model_dump(),
        "report": scorecard.render_markdown(arena),
    }
    if html:
        path = s.arena_dir(arena.id) / "report.html"
        write_atomic(path, scorecard.render_html(arena))
        out["html"] = str(path)
    if promote:
        out["promoted"] = pipeline.promote(s, arena.id, promote)
    return out


def arena_history(
    contestant: Annotated[str | None, Field(description="Only arenas that included this contestant name.")] = None,
    task_contains: Annotated[str | None, Field(description="Only arenas whose task contains this text.")] = None,
    limit: Annotated[int, Field(description="Most recent entries to return.")] = 20,
) -> dict[str, Any]:
    """Past arena results (newest first), for trends such as one skill across several edits."""
    entries = [e for e in store().read_history() if "stats" in e]
    if contestant:
        entries = [e for e in entries if any(c["name"] == contestant for c in e["contestants"])]
    if task_contains:
        entries = [e for e in entries if task_contains.lower() in e["task"].lower()]
    return {"entries": list(reversed(entries))[:limit]}


OPS = (arena_plan, arena_start, arena_status, arena_result, arena_history)
