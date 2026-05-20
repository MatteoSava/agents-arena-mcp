from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agents_arena_mcp.core.arena import ArenaEngine


def make_mcp():
    try:
        from fastmcp import FastMCP
    except Exception as exc:  # pragma: no cover - exercised only without dependency
        raise RuntimeError("FastMCP is required to run the MCP server. Install with `pip install -e .`.") from exc

    mcp = FastMCP(name="Shadow PR Arena MCP")

    @mcp.tool
    def arena_open(
        task: str,
        base_ref: str = "HEAD",
        variants: list[str] | None = None,
        include_current_diff: bool = False,
        risk_level: str = "normal",
    ) -> dict[str, Any]:
        """Create a Shadow PR Arena with isolated git worktrees for competing variants."""
        return ArenaEngine().open(task, base_ref, variants, include_current_diff, risk_level)

    @mcp.tool
    def arena_variant_brief(arena_id: str, variant: str) -> dict[str, Any]:
        """Return the implementation brief and worktree for one arena variant."""
        return ArenaEngine().variant_brief(arena_id, variant)

    @mcp.tool
    def arena_status(arena_id: str | None = None) -> dict[str, Any]:
        """Return current arena status, variant states, checks and Elo ratings."""
        return ArenaEngine().status(arena_id)

    @mcp.tool
    def arena_run_variant_agent(
        arena_id: str,
        variant: str,
        runner: str = "manual",
        model: str | None = None,
        timeout_sec: int | None = None,
        sandbox: str | None = None,
        approval_mode: str | None = None,
    ) -> dict[str, Any]:
        """Run a variant implementation via manual, Codex, or OpenCode adapter and record telemetry."""
        return ArenaEngine().run_variant_agent(arena_id, variant, runner, model, timeout_sec, sandbox, approval_mode)

    @mcp.tool
    def arena_record_variant(arena_id: str, variant: str, notes: str = "") -> dict[str, Any]:
        """Record a variant diff, patch, changed files, line counts and risk flags."""
        return ArenaEngine().record_variant(arena_id, variant, notes)

    @mcp.tool
    def arena_run_checks(
        arena_id: str,
        variant: str,
        commands: list[str] | None = None,
        timeout_sec: int = 300,
    ) -> dict[str, Any]:
        """Run allowlisted checks for a variant and record pass/fail evidence."""
        return ArenaEngine().run_checks(arena_id, variant, commands, timeout_sec)

    @mcp.tool
    def arena_pairwise_judge(
        arena_id: str,
        variant_a: str,
        variant_b: str,
        judge_runner: str = "heuristic",
        judge_model: str | None = None,
        criteria_profile: str = "balanced",
        timeout_sec: int = 600,
    ) -> dict[str, Any]:
        """Judge one pair of variants and update Elo ratings."""
        return ArenaEngine().pairwise_judge(arena_id, variant_a, variant_b, judge_runner, judge_model, criteria_profile, timeout_sec)

    @mcp.tool
    def arena_judge_all_pairs(
        arena_id: str,
        judge_runner: str = "heuristic",
        judge_model: str | None = None,
        max_pairs: int | None = None,
        mode: str = "all_pairs",
    ) -> dict[str, Any]:
        """Run pairwise judging for variant pairs and generate a scoreboard."""
        return ArenaEngine().judge_all_pairs(arena_id, judge_runner, judge_model, max_pairs, mode)

    @mcp.tool
    def arena_score(arena_id: str, weights_profile: str = "balanced") -> dict[str, Any]:
        """Compute deterministic score plus Elo component and select a provisional winner."""
        return ArenaEngine().score(arena_id, weights_profile)

    @mcp.tool
    def arena_scoreboard(
        arena_id: str,
        include_metadata: bool = True,
        include_pairwise_matrix: bool = True,
    ) -> dict[str, Any]:
        """Render and save the arena scoreboard with Elo, pairwise matrix, checks and telemetry."""
        return ArenaEngine().scoreboard(arena_id, include_metadata, include_pairwise_matrix)

    @mcp.tool
    def arena_promote_winner(arena_id: str, variant: str | None = None, mode: str = "patch") -> dict[str, Any]:
        """Export, apply, or branch the winning variant. Default is safe patch export."""
        return ArenaEngine().promote_winner(arena_id, variant, mode)

    @mcp.tool
    def arena_export_pr_bundle(arena_id: str) -> dict[str, Any]:
        """Create scoreboard, winner patch and PR summary artifacts."""
        return ArenaEngine().export_pr_bundle(arena_id)

    @mcp.tool
    def arena_cleanup(arena_id: str, keep_patches: bool = True) -> dict[str, Any]:
        """Remove arena worktrees while keeping reports and patches by default."""
        return ArenaEngine().cleanup(arena_id, keep_patches)

    @mcp.resource("arena://current")
    def current_arena() -> str:
        """Current arena status as JSON."""
        try:
            return json.dumps(ArenaEngine().status(), indent=2)
        except Exception as exc:
            return json.dumps({"error": str(exc)}, indent=2)

    @mcp.resource("arena://policy")
    def policy() -> str:
        """Current Shadow PR Arena policy as JSON."""
        engine = ArenaEngine()
        return json.dumps(engine.policy, indent=2)

    @mcp.resource("arena://{arena_id}/scoreboard")
    def scoreboard_resource(arena_id: str) -> str:
        """Arena scoreboard markdown."""
        return ArenaEngine().scoreboard(arena_id)["markdown"]

    @mcp.resource("arena://{arena_id}/variant/{variant}/diff")
    def variant_diff_resource(arena_id: str, variant: str) -> str:
        """Variant diff patch."""
        engine = ArenaEngine()
        arena = engine.load_arena(arena_id)
        rec = arena["variants"][variant]
        patch_path = rec.get("diff", {}).get("patch_path")
        if patch_path and Path(patch_path).exists():
            return Path(patch_path).read_text(encoding="utf-8")
        return rec.get("diff", {}).get("patch", "")

    @mcp.prompt
    def arena_variant_implementer(task: str, variant: str, constraints: str = "") -> str:
        """Prompt template for implementing a Shadow PR Arena variant."""
        return f"""Implement one Shadow PR Arena variant.

Task: {task}
Variant: {variant}
Constraints: {constraints}

Work only inside the variant worktree. Preserve behavior unless explicitly requested. Add evidence. Do not run destructive commands.
"""

    @mcp.prompt
    def arena_pairwise_judge_prompt(task: str, variant_a: str, variant_b: str) -> str:
        """Prompt template for judging two variants."""
        return f"""Judge two competing implementation variants for the same task.

Task: {task}
Variant A: {variant_a}
Variant B: {variant_b}

Prefer correctness, passing checks, regression coverage, smaller safe blast radius, maintainability, and reversibility. Return structured JSON with winner, confidence, reasons, risks.
"""

    return mcp


def main() -> None:
    make_mcp().run()


if __name__ == "__main__":
    main()
