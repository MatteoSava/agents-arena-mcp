from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

from .util import append_jsonl, ensure_dir, read_json, sha256_text, utc_now, write_json


def new_run_id(prefix: str = "run") -> str:
    return f"{prefix}-{utc_now().replace(':', '').replace('.', '').replace('Z', 'z')}"


class RunLedger:
    def __init__(self, repo_root: Path):
        self.repo_root = repo_root
        self.base = repo_root / ".agents-arena"
        self.runs_dir = self.base / "runs"
        self.state_dir = self.base / "state"
        ensure_dir(self.runs_dir)
        ensure_dir(self.state_dir)

    def run_dir(self, run_id: str) -> Path:
        return ensure_dir(self.runs_dir / run_id)

    def write_prompt(self, run_id: str, prompt: str) -> Path:
        path = self.run_dir(run_id) / "prompt.md"
        path.write_text(prompt, encoding="utf-8")
        return path

    def write_metadata(self, run_id: str, metadata: dict[str, Any]) -> Path:
        path = self.run_dir(run_id) / "metadata.json"
        write_json(path, metadata)
        append_jsonl(self.state_dir / "runs.jsonl", metadata)
        return path

    def append_pairwise_result(self, result: dict[str, Any]) -> None:
        append_jsonl(self.state_dir / "pairwise-results.jsonl", result)

    def read_pairwise_results(self, arena_id: str) -> list[dict[str, Any]]:
        path = self.state_dir / "pairwise-results.jsonl"
        if not path.exists():
            return []
        rows = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if item.get("arena_id") == arena_id:
                rows.append(item)
        return rows


def parse_jsonl_token_usage(path: Path) -> dict[str, Any]:
    usage = {
        "input_tokens": None,
        "cached_input_tokens": None,
        "output_tokens": None,
        "reasoning_output_tokens": None,
        "total_tokens": None,
        "source": "not_found",
    }
    if not path.exists():
        return usage
    totals: dict[str, int] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            event = json.loads(line)
        except Exception:
            continue
        # Accept several likely shapes from CLIs/SDKs.
        candidates = []
        if isinstance(event, dict):
            candidates.extend([event.get("usage"), event.get("token_usage")])
            data = event.get("data")
            if isinstance(data, dict):
                candidates.extend([data.get("usage"), data.get("token_usage")])
        for cand in candidates:
            if not isinstance(cand, dict):
                continue
            mapping = {
                "input_tokens": ["input_tokens", "prompt_tokens", "tokens_in"],
                "cached_input_tokens": ["cached_input_tokens", "cached_tokens"],
                "output_tokens": ["output_tokens", "completion_tokens", "tokens_out"],
                "reasoning_output_tokens": ["reasoning_output_tokens", "reasoning_tokens"],
                "total_tokens": ["total_tokens"],
            }
            for key, names in mapping.items():
                for name in names:
                    value = cand.get(name)
                    if isinstance(value, int):
                        totals[key] = max(totals.get(key, 0), value)
    if totals:
        usage.update(totals)
        if usage.get("total_tokens") is None:
            total = sum(v for k, v in totals.items() if k != "cached_input_tokens" and isinstance(v, int))
            usage["total_tokens"] = total or None
        usage["source"] = "json_events"
    return usage


def run_subprocess_capture(
    command: list[str],
    cwd: Path,
    run_dir: Path,
    timeout_sec: int,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    started = utc_now()
    start_time = time.monotonic()
    stdout_path = run_dir / "stdout.log"
    stderr_path = run_dir / "stderr.log"
    events_path = run_dir / "events.jsonl"

    with stdout_path.open("w", encoding="utf-8") as out, stderr_path.open("w", encoding="utf-8") as err:
        try:
            proc = subprocess.run(
                command,
                cwd=str(cwd),
                env={**os.environ, **(env or {})},
                text=True,
                stdout=out,
                stderr=err,
                timeout=timeout_sec,
                check=False,
            )
            exit_code = proc.returncode
            status = "completed" if exit_code == 0 else "failed"
        except subprocess.TimeoutExpired as exc:
            exit_code = 124
            status = "timeout"
            err.write(f"\nTIMEOUT after {timeout_sec}s: {exc}\n")

    ended = utc_now()
    wall_ms = int((time.monotonic() - start_time) * 1000)

    # If stdout is JSONL, copy it into events.jsonl for normalized consumers.
    stdout_text = stdout_path.read_text(encoding="utf-8", errors="replace") if stdout_path.exists() else ""
    json_lines = []
    for line in stdout_text.splitlines():
        try:
            json.loads(line)
            json_lines.append(line)
        except Exception:
            continue
    if json_lines:
        events_path.write_text("\n".join(json_lines) + "\n", encoding="utf-8")

    return {
        "status": status,
        "exit_code": exit_code,
        "timing": {"started_at": started, "ended_at": ended, "wall_ms": wall_ms},
        "outputs": {
            "stdout_path": str(stdout_path),
            "stderr_path": str(stderr_path),
            "json_events_path": str(events_path) if events_path.exists() else None,
        },
        "tokens": parse_jsonl_token_usage(events_path if events_path.exists() else stdout_path),
    }
