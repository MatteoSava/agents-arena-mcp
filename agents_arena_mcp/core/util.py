from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .errors import ArenaError


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def slugify(value: str, max_len: int = 64) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9._-]+", "-", value)
    value = re.sub(r"-+", "-", value).strip("-._")
    return (value or "item")[:max_len]


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def write_json(path: Path, data: Any) -> None:
    ensure_dir(path.parent)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, sort_keys=True)
        fh.write("\n")
    tmp.replace(path)


def append_jsonl(path: Path, data: dict[str, Any]) -> None:
    ensure_dir(path.parent)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(data, sort_keys=True) + "\n")


def run_cmd(
    args: list[str],
    cwd: Path | str | None = None,
    timeout: int | None = None,
    env: dict[str, str] | None = None,
    check: bool = False,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        args,
        cwd=str(cwd) if cwd else None,
        env={**os.environ, **(env or {})},
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    if check and result.returncode != 0:
        raise ArenaError(
            f"Command failed ({result.returncode}): {' '.join(args)}\n"
            f"stdout:\n{result.stdout}\n\nstderr:\n{result.stderr}"
        )
    return result


def find_executable(name: str) -> str | None:
    return shutil.which(name)


@dataclass
class ShellOutcome:
    status: str  # passed | failed | error | timeout
    exit_code: int | None
    stdout: str
    stderr: str


def run_shell(command: str, cwd: Path, timeout: int) -> ShellOutcome:
    """Run a check command via `sh -c`. Missing tools (127) are errors; timeouts kill the process group."""
    proc = subprocess.Popen(
        ["sh", "-c", command], cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True
    )
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        out, err = proc.communicate()
        return ShellOutcome("timeout", None, out.decode("utf-8", "replace"), err.decode("utf-8", "replace"))
    code = proc.returncode
    status = "passed" if code == 0 else "error" if code in (126, 127) else "failed"
    return ShellOutcome(status, code, out.decode("utf-8", "replace"), err.decode("utf-8", "replace"))
