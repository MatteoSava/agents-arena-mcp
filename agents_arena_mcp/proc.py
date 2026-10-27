"""The one place that starts subprocesses: timeouts, process-group kill, log capture."""

from __future__ import annotations

import os
import signal
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path

# Live process groups, keyed by an owner tag (an arena id), so close() can kill stragglers.
_live: dict[int, str] = {}
_live_lock = threading.Lock()


@dataclass
class ProcResult:
    status: str  # passed | failed | error | timeout
    exit_code: int | None
    stdout: str
    stderr: str
    wall_ms: int

    @property
    def ok(self) -> bool:
        return self.status == "passed"


def clean_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}  # allow nested `claude -p`
    return {**env, **(extra or {})}


def run(
    argv: list[str],
    cwd: Path,
    timeout: int,
    *,
    owner: str = "",
    log_dir: Path | None = None,
    env: dict[str, str] | None = None,
) -> ProcResult:
    """Run argv. Exit 126/127 or a missing executable is `error`; a timeout kills the whole group."""
    started = time.monotonic()
    try:
        proc = subprocess.Popen(
            argv,
            cwd=cwd,
            env=clean_env(env),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
    except (FileNotFoundError, PermissionError) as exc:
        return ProcResult("error", None, "", str(exc), 0)
    with _live_lock:
        _live[proc.pid] = owner
    try:
        out, err = proc.communicate(timeout=timeout)
        code: int | None = proc.returncode
        status = "passed" if code == 0 else "error" if code in (126, 127) else "failed"
    except subprocess.TimeoutExpired:
        _kill_group(proc.pid)
        out, err = proc.communicate()
        code, status = None, "timeout"
    finally:
        with _live_lock:
            _live.pop(proc.pid, None)
    result = ProcResult(
        status,
        code,
        out.decode("utf-8", "replace"),
        err.decode("utf-8", "replace"),
        int((time.monotonic() - started) * 1000),
    )
    if log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True)
        (log_dir / "stdout.log").write_text(result.stdout, encoding="utf-8")
        (log_dir / "stderr.log").write_text(result.stderr, encoding="utf-8")
    return result


def shell(command: str, cwd: Path, timeout: int, *, owner: str = "") -> ProcResult:
    return run(["sh", "-c", command], cwd, timeout, owner=owner)


def kill_owned(owner: str) -> int:
    with _live_lock:
        pids = [pid for pid, tag in _live.items() if tag == owner]
    for pid in pids:
        _kill_group(pid)
    return len(pids)


def _kill_group(pid: int) -> None:
    try:
        os.killpg(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


def tail(text: str, limit: int = 4000) -> str:
    return text if len(text) <= limit else "…" + text[-limit:]
