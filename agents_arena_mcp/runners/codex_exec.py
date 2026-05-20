from __future__ import annotations

from pathlib import Path
from typing import Any

from agents_arena_mcp.core.telemetry import RunLedger, new_run_id, run_subprocess_capture
from agents_arena_mcp.core.util import find_executable, sha256_text, utc_now
from agents_arena_mcp.runners.base import RunnerRequest


class CodexExecRunner:
    name = "codex"

    def run(self, request: RunnerRequest) -> dict[str, Any]:
        exe = find_executable("codex")
        if not exe:
            raise RuntimeError("codex executable not found. Install Codex CLI or use runner='manual'.")
        ledger = RunLedger(request.repo_root)
        run_id = new_run_id("codex")
        run_dir = ledger.run_dir(run_id)
        prompt_path = ledger.write_prompt(run_id, request.prompt)
        final_path = run_dir / "final.md"
        schema_path = request.repo_root / ".shadow-pr-arena" / "schemas" / "variant-result.schema.json"
        cmd = [
            exe,
            "exec",
            "--cd",
            str(request.worktree),
            "--sandbox",
            request.sandbox,
            "--json",
            "--output-last-message",
            str(final_path),
        ]
        if request.model:
            cmd.extend(["--model", request.model])
        if schema_path.exists():
            cmd.extend(["--output-schema", str(schema_path)])
        cmd.append(request.prompt)
        capture = run_subprocess_capture(cmd, cwd=request.worktree, run_dir=run_dir, timeout_sec=request.timeout_sec)
        metadata = {
            "run_id": run_id,
            "arena_id": request.arena_id,
            "run_kind": "variant_implementation",
            "variant": request.variant,
            "runner": self.name,
            "runner_adapter": "codex_exec",
            "status": capture["status"],
            "exit_code": capture["exit_code"],
            "model": {"provider": "openai", "name": request.model},
            "timing": capture["timing"],
            "tokens": capture["tokens"],
            "workspace": {"repo_root": str(request.repo_root), "worktree": str(request.worktree)},
            "prompt": {"prompt_path": str(prompt_path), "prompt_sha256": sha256_text(request.prompt)},
            "outputs": capture["outputs"] | {"final_message_path": str(final_path) if final_path.exists() else None},
            "safety": {"sandbox": request.sandbox, "approval_mode": request.approval_mode},
        }
        ledger.write_metadata(run_id, metadata)
        return metadata
