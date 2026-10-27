"""Background jobs: threads inside the long-lived MCP server, recorded on disk so status can report them."""

from __future__ import annotations

import os
import threading
import traceback
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastmcp import Context

from agents_arena_mcp.models import Job
from agents_arena_mcp.runners import new_run_id
from agents_arena_mcp.store import Store, utc_now, write_atomic


def _path(store: Store, arena_id: str, job_id: str) -> Path:
    return store.arena_dir(arena_id) / "jobs" / f"{job_id}.json"


def start(store: Store, arena_id: str, op: str, work: Callable[[Callable[[str], None]], object]) -> Job:
    """Run work(progress) in a daemon thread. `progress(msg)` updates the job record."""
    job = Job(id=new_run_id(op), op=op, pid=os.getpid(), started_at=utc_now())
    path = _path(store, arena_id, job.id)
    lock = threading.Lock()

    def save() -> None:
        with lock:
            write_atomic(path, job.model_dump_json(indent=2))

    def progress(message: str) -> None:
        job.progress = message
        save()

    def body() -> None:
        try:
            work(progress)
            job.status = "done"
        except Exception as exc:  # recorded for arena_status; nothing else would see it
            job.status, job.error = "failed", f"{exc}\n{traceback.format_exc(limit=3)}"
        job.ended_at = utc_now()
        save()

    save()
    threading.Thread(target=body, name=f"arena-{job.id}", daemon=True).start()
    return job


def list_jobs(store: Store, arena_id: str) -> list[Job]:
    folder = store.arena_dir(arena_id) / "jobs"
    jobs = [Job.model_validate_json(p.read_text(encoding="utf-8")) for p in sorted(folder.glob("*.json"))]
    for job in jobs:
        if job.status == "running" and not _alive(job.pid):
            job.status, job.error = "failed", "server process exited before the job finished"
    return jobs


def running(store: Store, arena_id: str) -> list[Job]:
    return [j for j in list_jobs(store, arena_id) if j.status == "running"]


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def in_background(
    store: Store,
    arena_id: str,
    op: str,
    wait: bool,
    ctx: Context | None,
    work: Callable[[Callable[[str], None]], object],
) -> dict[str, Any] | None:
    """Run `work(progress)` now (returns None) or as a background job (returns the job handle)."""
    if wait:
        work(lambda msg: _report_progress(ctx, msg))
        return None
    job = start(store, arena_id, op, work)
    return {"arena_id": arena_id, "job": job.model_dump(), "hint": "poll arena_status for progress"}


def _report_progress(ctx: Context | None, message: str) -> None:
    if ctx is None:
        return
    try:  # sync tools run in a worker thread; hop back to the event loop for the notification
        import anyio.from_thread

        anyio.from_thread.run(ctx.report_progress, 0, None, message)
    except Exception:
        pass  # progress is best-effort; never fail the operation over it
