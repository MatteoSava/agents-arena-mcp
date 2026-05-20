from __future__ import annotations

from typing import Any

from shadow_pr_arena_mcp.core.telemetry import RunLedger, new_run_id
from shadow_pr_arena_mcp.core.util import sha256_text, utc_now
from shadow_pr_arena_mcp.runners.base import RunnerRequest


class ManualRunner:
    name = "manual"

    def run(self, request: RunnerRequest) -> dict[str, Any]:
        ledger = RunLedger(request.repo_root)
        run_id = new_run_id("manual")
        prompt_path = ledger.write_prompt(run_id, request.prompt)
        metadata = {
            "run_id": run_id,
            "arena_id": request.arena_id,
            "run_kind": "variant_implementation",
            "variant": request.variant,
            "runner": self.name,
            "runner_adapter": "manual",
            "status": "manual_pending",
            "exit_code": None,
            "model": {"provider": None, "name": request.model},
            "timing": {"started_at": utc_now(), "ended_at": None, "wall_ms": None},
            "tokens": {"source": "not_available"},
            "workspace": {"repo_root": str(request.repo_root), "worktree": str(request.worktree)},
            "prompt": {"prompt_path": str(prompt_path), "prompt_sha256": sha256_text(request.prompt)},
            "outputs": {},
            "safety": {"sandbox": request.sandbox, "approval_mode": request.approval_mode},
        }
        ledger.write_metadata(run_id, metadata)
        return metadata
