"""Background jobs: threads inside the long-lived MCP server, recorded on disk so status can report them."""

from __future__ import annotations

import os
import secrets
import threading
import time
import traceback
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastmcp import Context

from agents_arena_mcp import proc
from agents_arena_mcp.models import Job
from agents_arena_mcp.store import Store, utc_now, write_atomic

_threads: list[threading.Thread] = []


def new_run_id(prefix: str) -> str:
    return f"{prefix}-{datetime.now(UTC).strftime('%Y%m%dT%H%M%S')}-{secrets.token_hex(3)}"


def _path(store: Store, arena_id: str, job_id: str) -> Path:
    return store.arena_dir(arena_id) / "jobs" / f"{job_id}.json"


def _create(store: Store, arena_id: str, op: str) -> tuple[Job, Callable[[], None]]:
    job = Job(id=new_run_id(op), op=op, pid=os.getpid(), started_at=utc_now())
    path = _path(store, arena_id, job.id)
    lock = threading.Lock()

    def save() -> None:
        with lock:
            write_atomic(path, job.model_dump_json(indent=2))

    save()
    return job, save


def _run(job: Job, save: Callable[[], None], work: Callable[[Callable[[str], None]], object],
         notify: Callable[[str], None] | None = None) -> None:  # fmt: skip
    """Run work(progress) and record how it ended. Failures, Ctrl-C included, are recorded and re-raised."""

    def progress(message: str) -> None:
        job.progress = message
        save()
        if notify:
            notify(message)

    try:
        work(progress)
        job.status = "done"
    except BaseException as exc:
        job.status, job.error = "failed", f"{type(exc).__name__}: {exc}\n{traceback.format_exc(limit=3)}"
        raise
    finally:
        job.ended_at = utc_now()
        save()


def start(store: Store, arena_id: str, op: str, work: Callable[[Callable[[str], None]], object]) -> Job:
    """Run work(progress) in a daemon thread. `progress(msg)` updates the job record."""
    job, save = _create(store, arena_id, op)

    def body() -> None:
        try:
            _run(job, save, work)
        except Exception:
            pass  # recorded on the job for arena_status; nothing else would see it

    thread = threading.Thread(target=body, name=f"arena-{job.id}", daemon=True)
    _threads[:] = [t for t in _threads if t.is_alive()] + [thread]
    thread.start()
    return job


def stop_all(timeout: float = 30) -> None:
    """Cancel every arena running in this process and give its job time to record the failure and clean up."""
    proc.cancel_all()
    deadline = time.monotonic() + timeout
    for thread in list(_threads):
        thread.join(max(0.0, deadline - time.monotonic()))


def on_sigterm(signum: int, frame: object) -> None:
    """SIGTERM handler for the server and CLI: stop arenas cleanly instead of dying mid-run."""
    stop_all()
    raise SystemExit(128 + signum)


def list_jobs(store: Store, arena_id: str) -> list[Job]:
    folder = store.arena_dir(arena_id) / "jobs"
    jobs = [Job.model_validate_json(p.read_text(encoding="utf-8")) for p in sorted(folder.glob("*.json"))]
    for job in jobs:
        if job.status == "running" and not _alive(job.pid):
            job.status, job.error = "failed", "server process exited before the job finished"
    return jobs


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
    if wait:  # tracked like a background job, so arena_status can tell if this process died mid-run
        job, save = _create(store, arena_id, op)
        _run(job, save, work, lambda msg: _report_progress(ctx, msg))
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
