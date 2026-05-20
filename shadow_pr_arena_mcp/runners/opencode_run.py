from __future__ import annotations

from typing import Any

from shadow_pr_arena_mcp.core.telemetry import RunLedger, new_run_id, run_subprocess_capture
from shadow_pr_arena_mcp.core.util import find_executable, sha256_text
from shadow_pr_arena_mcp.runners.base import RunnerRequest


class OpenCodeRunRunner:
    name = "opencode"

    def run(self, request: RunnerRequest) -> dict[str, Any]:
        exe = find_executable("opencode")
        if not exe:
            raise RuntimeError("opencode executable not found. Install OpenCode CLI or use runner='manual'.")
        ledger = RunLedger(request.repo_root)
        run_id = new_run_id("opencode")
        run_dir = ledger.run_dir(run_id)
        prompt_path = ledger.write_prompt(run_id, request.prompt)
        cmd = [exe, "run", "--dir", str(request.worktree), "--format", "json"]
        if request.model:
            cmd.extend(["--model", request.model])
        cmd.append(request.prompt)
        capture = run_subprocess_capture(cmd, cwd=request.worktree, run_dir=run_dir, timeout_sec=request.timeout_sec)
        metadata = {
            "run_id": run_id,
            "arena_id": request.arena_id,
            "run_kind": "variant_implementation",
            "variant": request.variant,
            "runner": self.name,
            "runner_adapter": "opencode_run",
            "status": capture["status"],
            "exit_code": capture["exit_code"],
            "model": {"provider": None, "name": request.model},
            "timing": capture["timing"],
            "tokens": capture["tokens"],
            "workspace": {"repo_root": str(request.repo_root), "worktree": str(request.worktree)},
            "prompt": {"prompt_path": str(prompt_path), "prompt_sha256": sha256_text(request.prompt)},
            "outputs": capture["outputs"],
            "safety": {"sandbox": request.sandbox, "approval_mode": request.approval_mode},
        }
        ledger.write_metadata(run_id, metadata)
        return metadata
