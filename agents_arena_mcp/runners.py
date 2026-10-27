"""Agent and judge CLIs as argv templates from config. No per-tool classes."""

from __future__ import annotations

import json
import secrets
from datetime import UTC, datetime
from pathlib import Path

from agents_arena_mcp import proc
from agents_arena_mcp.config import CommandSpec
from agents_arena_mcp.errors import ArenaError
from agents_arena_mcp.models import RunRecord, TokenUsage
from agents_arena_mcp.store import utc_now


def new_run_id(prefix: str) -> str:
    return f"{prefix}-{datetime.now(UTC).strftime('%Y%m%dT%H%M%S')}-{secrets.token_hex(3)}"


def build_argv(spec: CommandSpec, values: dict[str, str]) -> list[str]:
    """Substitute {placeholders}. "{model_flag}" expands to spec.model_flag when a model is set, else nothing."""
    argv: list[str] = []
    for part in spec.argv:
        if part == "{model_flag}":
            if values.get("model"):
                argv.extend(_fill(p, values) for p in spec.model_flag)
            continue
        argv.append(_fill(part, values))
    return argv


def _fill(part: str, values: dict[str, str]) -> str:
    for key, value in values.items():
        part = part.replace("{" + key + "}", value)
    return part


def run_agent(
    spec: CommandSpec, runner: str, workspace: Path, prompt: str, run_dir: Path, model: str, timeout: int, owner: str
) -> RunRecord:
    run_dir.mkdir(parents=True, exist_ok=True)
    prompt_file = run_dir / "prompt.md"
    prompt_file.write_text(prompt, encoding="utf-8")
    values = {
        "prompt": prompt,
        "prompt_file": str(prompt_file),
        "workspace": str(workspace),
        "run_dir": str(run_dir),
        "model": model,
    }
    started = utc_now()
    result = proc.run(build_argv(spec, values), workspace, timeout, owner=owner, log_dir=run_dir)
    status = {"passed": "completed", "failed": "failed", "timeout": "timeout"}.get(result.status, "error")
    return RunRecord(
        run_id=run_dir.name,
        runner=runner,
        model=model or None,
        status=status,  # type: ignore[arg-type]
        exit_code=result.exit_code,
        started_at=started,
        wall_ms=result.wall_ms,
        tokens=parse_usage(result.stdout),
        run_dir=str(run_dir),
    )


def lookup(specs: dict[str, CommandSpec], name: str, kind: str) -> CommandSpec:
    if name not in specs:
        raise ArenaError(f"Unknown {kind} {name!r}. Configured: {', '.join(sorted(specs)) or 'none'}")
    return specs[name]


def parse_usage(stdout: str) -> TokenUsage:
    """Best-effort token/cost extraction from JSON or JSONL agent output (codex, claude, opencode)."""
    usage = TokenUsage()
    for line in stdout.splitlines() or [stdout]:
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        cand = event.get("usage")  # codex `turn.completed` events and claude's final JSON both carry `usage`
        if isinstance(cand, dict):
            tokens_in = cand.get("input_tokens") or cand.get("prompt_tokens")
            tokens_out = cand.get("output_tokens") or cand.get("completion_tokens")
            if isinstance(tokens_in, int):
                usage.input_tokens = (usage.input_tokens or 0) + tokens_in
            if isinstance(tokens_out, int):
                usage.output_tokens = (usage.output_tokens or 0) + tokens_out
        cost = event.get("total_cost_usd")
        if isinstance(cost, int | float):
            usage.cost_usd = float(cost)
    if usage.input_tokens is not None or usage.output_tokens is not None:
        usage.total_tokens = (usage.input_tokens or 0) + (usage.output_tokens or 0)
    return usage
