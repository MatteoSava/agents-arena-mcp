from __future__ import annotations

import itertools
import json
import shlex
from pathlib import Path
from typing import Any

from shadow_pr_arena_mcp.core.elo import score_for_outcome, update_pair
from shadow_pr_arena_mcp.core.errors import ArenaError
from shadow_pr_arena_mcp.core.git_worktrees import (
    create_worktree,
    current_commit,
    diff_against,
    discover_repo_root,
    is_dirty,
    remove_worktree,
    repo_name,
    resolve_worktree_root,
)
from shadow_pr_arena_mcp.core.policy import assert_command_allowed, init_policy, load_policy, path_has_secret_signal
from shadow_pr_arena_mcp.core.scoring import deterministic_variant_score
from shadow_pr_arena_mcp.core.telemetry import RunLedger, new_run_id
from shadow_pr_arena_mcp.core.util import append_jsonl, ensure_dir, find_executable, read_json, run_cmd, sha256_text, slugify, utc_now, write_json
from shadow_pr_arena_mcp.judges.pairwise import external_judge, heuristic_pairwise
from shadow_pr_arena_mcp.runners import get_runner
from shadow_pr_arena_mcp.runners.base import RunnerRequest

STRATEGY_BRIEFS = {
    "minimal_patch": """Implement the smallest safe patch. Avoid public API changes. Add only targeted tests needed to prove the fix. Do not refactor unrelated code.""",
    "test_first": """Write or update regression tests first, confirm the behavior is captured, then implement the minimum code needed to pass. Preserve existing behavior outside the target case.""",
    "clean_boundary": """Improve the local boundary or adapter shape while preserving behavior. Accept a larger diff only when it reduces coupling or clarifies ownership. Add regression coverage.""",
    "maintainability_refactor": """Favor long-term readability and maintainability. Extract small helpers or policies if they reduce branching and duplication. Avoid broad rewrites.""",
    "policy_object": """Model the business rule as an explicit policy object or strategy. Keep side effects at the edges. Add tests around policy decisions.""",
    "adapter_boundary": """Push integration details behind an adapter boundary. Keep domain/core code independent of transport, framework, or provider details.""",
    "performance_oriented": """Optimize only where the task justifies it. Preserve correctness first. Include measurement or a clear performance rationale.""",
}


class ArenaEngine:
    def __init__(self, repo_root: Path | None = None):
        self.repo_root = discover_repo_root(repo_root)
        self.base_dir = self.repo_root / ".shadow-pr-arena"
        self.state_dir = self.base_dir / "state"
        self.reports_dir = self.base_dir / "reports"
        self.patches_dir = self.base_dir / "patches"
        self.logs_dir = self.base_dir / "logs"
        for path in [self.base_dir, self.state_dir, self.reports_dir, self.patches_dir, self.logs_dir]:
            ensure_dir(path)
        self.policy = load_policy(self.repo_root)
        init_policy(self.repo_root)

    @property
    def current_arena_path(self) -> Path:
        return self.state_dir / "current-arena.json"

    def _arena_path(self, arena_id: str) -> Path:
        return self.state_dir / f"{arena_id}.json"

    def _save_arena(self, arena: dict[str, Any]) -> None:
        arena["updated_at"] = utc_now()
        write_json(self._arena_path(arena["arena_id"]), arena)
        write_json(self.current_arena_path, arena)

    def _append_arena_event(self, arena: dict[str, Any], event: str, data: dict[str, Any] | None = None) -> None:
        append_jsonl(
            self.state_dir / "arenas.jsonl",
            {"at": utc_now(), "arena_id": arena["arena_id"], "event": event, "data": data or {}},
        )

    def load_arena(self, arena_id: str | None = None) -> dict[str, Any]:
        path = self.current_arena_path if arena_id is None else self._arena_path(arena_id)
        arena = read_json(path)
        if not arena:
            raise ArenaError(f"Arena not found: {arena_id or 'current'}")
        return arena

    def open(
        self,
        task: str,
        base_ref: str = "HEAD",
        variants: list[str] | None = None,
        include_current_diff: bool = False,
        risk_level: str = "normal",
    ) -> dict[str, Any]:
        if is_dirty(self.repo_root) and not include_current_diff and self.policy.get("worktrees", {}).get("refuse_dirty_repo_by_default", True):
            raise ArenaError("Working tree is dirty. Commit/stash changes or pass include_current_diff=True.")
        variants = variants or list(self.policy.get("variants", []))
        variants = [slugify(v) for v in variants]
        if len(set(variants)) != len(variants):
            raise ArenaError("Variant names must be unique after slugification.")
        base_commit = current_commit(self.repo_root, base_ref)
        arena_id = f"arena-{utc_now().replace(':', '').replace('.', '').replace('Z', 'z')}-{slugify(task, 28)}"
        worktree_root = resolve_worktree_root(self.repo_root, self.policy) / arena_id
        ensure_dir(worktree_root)
        variant_records: dict[str, Any] = {}
        for variant in variants:
            branch = f"shadow/{arena_id}/{variant}"[:240]
            worktree_path = worktree_root / variant
            create_worktree(self.repo_root, worktree_path, branch, base_ref)
            variant_records[variant] = {
                "name": variant,
                "state": "created",
                "strategy": STRATEGY_BRIEFS.get(variant, "Implement this strategy while preserving task constraints."),
                "branch": branch,
                "worktree": str(worktree_path),
                "created_at": utc_now(),
                "runs": [],
                "checks": {},
                "diff": {},
                "risk_flags": [],
            }
        arena = {
            "arena_id": arena_id,
            "task": task,
            "base_ref": base_ref,
            "base_commit": base_commit,
            "repo_root": str(self.repo_root),
            "repo_name": repo_name(self.repo_root),
            "risk_level": risk_level,
            "status": "open",
            "created_at": utc_now(),
            "updated_at": utc_now(),
            "include_current_diff": include_current_diff,
            "variants": variant_records,
            "pairwise": {"results": [], "elo": {v: self.policy.get("pairwise", {}).get("initial_elo", 1500) for v in variants}},
            "winner": None,
        }
        self._save_arena(arena)
        self._append_arena_event(arena, "arena_open", {"variants": variants})
        return arena

    def status(self, arena_id: str | None = None) -> dict[str, Any]:
        arena = self.load_arena(arena_id)
        return {
            "arena_id": arena["arena_id"],
            "status": arena.get("status"),
            "task": arena.get("task"),
            "base_commit": arena.get("base_commit"),
            "winner": arena.get("winner"),
            "variants": {
                name: {
                    "state": v.get("state"),
                    "worktree": v.get("worktree"),
                    "files_changed": (v.get("diff") or {}).get("files_changed"),
                    "checks": v.get("checks", {}).get("status") or ("passed" if v.get("checks", {}).get("passed") else "pending"),
                    "elo": arena.get("pairwise", {}).get("elo", {}).get(name),
                }
                for name, v in arena["variants"].items()
            },
        }

    def variant_brief(self, arena_id: str, variant: str) -> dict[str, Any]:
        arena = self.load_arena(arena_id)
        if variant not in arena["variants"]:
            raise ArenaError(f"Unknown variant {variant!r}")
        rec = arena["variants"][variant]
        prompt = f"""# Shadow PR Arena Variant Brief

Arena: {arena_id}
Variant: {variant}
Worktree: {rec['worktree']}

## Original task

{arena['task']}

## Strategy

{rec.get('strategy') or STRATEGY_BRIEFS.get(variant, '')}

## Constraints

- Work only inside this variant worktree.
- Preserve behavior outside the requested task.
- Prefer regression evidence over unsupported claims.
- Do not run destructive commands.
- Do not touch secrets or production credentials.
- When complete, leave changes uncommitted and run `arena_record_variant`.
"""
        return {"arena_id": arena_id, "variant": variant, "worktree": rec["worktree"], "brief": prompt}

    def run_variant_agent(
        self,
        arena_id: str,
        variant: str,
        runner: str = "manual",
        model: str | None = None,
        timeout_sec: int | None = None,
        sandbox: str | None = None,
        approval_mode: str | None = None,
    ) -> dict[str, Any]:
        arena = self.load_arena(arena_id)
        if variant not in arena["variants"]:
            raise ArenaError(f"Unknown variant {variant!r}")
        rec = arena["variants"][variant]
        brief = self.variant_brief(arena_id, variant)["brief"]
        runner_obj = get_runner(runner)
        request = RunnerRequest(
            repo_root=self.repo_root,
            worktree=Path(rec["worktree"]),
            arena_id=arena_id,
            variant=variant,
            prompt=brief,
            model=model,
            timeout_sec=timeout_sec or self.policy.get("runner", {}).get("timeout_sec", 900),
            sandbox=sandbox or self.policy.get("runner", {}).get("sandbox", "workspace-write"),
            approval_mode=approval_mode or self.policy.get("runner", {}).get("approval_mode", "prompt"),
        )
        metadata = runner_obj.run(request)
        rec["runs"].append(metadata["run_id"])
        rec["state"] = "agent_run_completed" if metadata.get("status") == "completed" else metadata.get("status", "run_recorded")
        self._save_arena(arena)
        self._append_arena_event(arena, "variant_run", {"variant": variant, "run_id": metadata["run_id"], "runner": runner})
        return metadata

    def record_variant(self, arena_id: str, variant: str, notes: str = "") -> dict[str, Any]:
        arena = self.load_arena(arena_id)
        if variant not in arena["variants"]:
            raise ArenaError(f"Unknown variant {variant!r}")
        rec = arena["variants"][variant]
        worktree = Path(rec["worktree"])
        diff = diff_against(worktree, arena["base_commit"])
        risk_flags: list[str] = []
        for f in diff.get("changed_files", []):
            if path_has_secret_signal(f, self.policy):
                risk_flags.append(f"critical_secret_path:{f}")
            if f.startswith((".github/workflows/", ".claude/", ".codex/", ".opencode/", ".agents/")):
                risk_flags.append(f"sensitive_config_path:{f}")
        patch_path = self.patches_dir / f"{arena_id}-{variant}.patch"
        patch_path.write_text(diff.get("patch", ""), encoding="utf-8")
        rec["diff"] = diff | {"patch_path": str(patch_path)}
        rec["risk_flags"] = sorted(set(risk_flags))
        rec["state"] = "implemented" if diff.get("files_changed", 0) else "no_changes"
        rec["notes"] = notes
        rec["recorded_at"] = utc_now()
        self._save_arena(arena)
        self._append_arena_event(arena, "variant_recorded", {"variant": variant, "files_changed": diff.get("files_changed")})
        return rec

    def discover_checks(self, changed_files: list[str]) -> list[str]:
        checks = list(self.policy.get("checks", {}).get("generic", []))
        if any(f.endswith(".py") for f in changed_files):
            checks.extend(self.policy.get("checks", {}).get("python", []))
        if any(f.endswith((".js", ".jsx", ".ts", ".tsx", ".css", ".html", ".vue", ".svelte")) for f in changed_files):
            checks.extend(self.policy.get("checks", {}).get("node", []))
        if any(f.endswith((".tf", ".tfvars")) or f.startswith(("infra/", "terraform/", "k8s/")) for f in changed_files):
            checks.extend(self.policy.get("checks", {}).get("terraform", []))
        # Keep order, de-dupe, and drop declarative evidence requirements from executable checks.
        deduped = []
        for cmd in checks:
            if cmd not in deduped and "required" not in cmd:
                deduped.append(cmd)
        return deduped

    def run_checks(self, arena_id: str, variant: str, commands: list[str] | None = None, timeout_sec: int = 300) -> dict[str, Any]:
        arena = self.load_arena(arena_id)
        if variant not in arena["variants"]:
            raise ArenaError(f"Unknown variant {variant!r}")
        rec = arena["variants"][variant]
        worktree = Path(rec["worktree"])
        if not rec.get("diff"):
            self.record_variant(arena_id, variant)
            arena = self.load_arena(arena_id)
            rec = arena["variants"][variant]
        commands = commands or self.discover_checks(rec.get("diff", {}).get("changed_files", []))
        results = []
        passed = True
        for command in commands:
            assert_command_allowed(command, self.policy)
            started = utc_now()
            proc = run_cmd(shlex.split(command), cwd=worktree, timeout=timeout_sec, check=False)
            item = {
                "command": command,
                "status": "passed" if proc.returncode == 0 else "failed",
                "exit_code": proc.returncode,
                "started_at": started,
                "ended_at": utc_now(),
                "stdout_excerpt": proc.stdout[-4000:],
                "stderr_excerpt": proc.stderr[-4000:],
            }
            if proc.returncode != 0:
                passed = False
            results.append(item)
        check_record = {"passed": passed, "status": "passed" if passed else "failed", "commands": results, "updated_at": utc_now()}
        rec["checks"] = check_record
        rec["state"] = "checked_passed" if passed else "checked_failed"
        self._save_arena(arena)
        self._append_arena_event(arena, "checks_run", {"variant": variant, "passed": passed})
        return check_record

    def pairwise_judge(
        self,
        arena_id: str,
        variant_a: str,
        variant_b: str,
        judge_runner: str = "heuristic",
        judge_model: str | None = None,
        criteria_profile: str = "balanced",
        timeout_sec: int = 600,
    ) -> dict[str, Any]:
        arena = self.load_arena(arena_id)
        for v in [variant_a, variant_b]:
            if v not in arena["variants"]:
                raise ArenaError(f"Unknown variant {v!r}")
            if not arena["variants"][v].get("diff"):
                self.record_variant(arena_id, v)
                arena = self.load_arena(arena_id)
        if judge_runner == "auto":
            if find_executable("codex"):
                judge_runner = "codex"
            elif find_executable("opencode"):
                judge_runner = "opencode"
            else:
                judge_runner = "heuristic"
        if judge_runner == "heuristic":
            result = heuristic_pairwise(arena, variant_a, variant_b)
            run_id = new_run_id("heuristic-judge")
        else:
            result = external_judge(self.repo_root, arena, variant_a, variant_b, judge_runner, judge_model, timeout_sec)
            run_id = result.get("run_id", new_run_id("judge"))
        ratings = arena.setdefault("pairwise", {}).setdefault("elo", {})
        initial = self.policy.get("pairwise", {}).get("initial_elo", 1500)
        ratings.setdefault(variant_a, initial)
        ratings.setdefault(variant_b, initial)
        score_a = score_for_outcome(result["winner"], variant_a, variant_b)
        new_a, new_b, delta_a, delta_b = update_pair(
            ratings[variant_a],
            ratings[variant_b],
            score_a,
            confidence=float(result.get("confidence", 0.7)),
            k_factor=int(self.policy.get("pairwise", {}).get("k_factor", 32)),
        )
        ratings[variant_a] = round(new_a, 2)
        ratings[variant_b] = round(new_b, 2)
        match = {
            "match_id": f"{arena_id}:{variant_a}-vs-{variant_b}",
            "arena_id": arena_id,
            "run_id": run_id,
            "variant_a": variant_a,
            "variant_b": variant_b,
            "winner": result["winner"],
            "outcome": result.get("outcome"),
            "confidence": result.get("confidence"),
            "margin": result.get("margin"),
            "reasons": result.get("reasons", []),
            "risks": result.get("risks", []),
            "judge_runner": judge_runner,
            "judge_model": judge_model,
            "criteria_profile": criteria_profile,
            "elo_delta": {variant_a: delta_a, variant_b: delta_b},
            "created_at": utc_now(),
            "tokens": result.get("tokens"),
            "latency_ms": result.get("latency_ms"),
        }
        arena.setdefault("pairwise", {}).setdefault("results", []).append(match)
        RunLedger(self.repo_root).append_pairwise_result(match)
        self._save_arena(arena)
        self._append_arena_event(arena, "pairwise_judged", match)
        return match

    def judge_all_pairs(
        self,
        arena_id: str,
        judge_runner: str = "heuristic",
        judge_model: str | None = None,
        max_pairs: int | None = None,
        mode: str = "all_pairs",
    ) -> dict[str, Any]:
        arena = self.load_arena(arena_id)
        variants = list(arena["variants"].keys())
        pairs = list(itertools.combinations(variants, 2))
        if mode == "all_pairs":
            max_variants = self.policy.get("pairwise", {}).get("max_all_pairs_variants", 5)
            if len(variants) > max_variants and max_pairs is None:
                raise ArenaError(f"All-pairs mode limited to {max_variants} variants by policy. Set max_pairs or use fewer variants.")
        elif mode == "top_k_playoff":
            pairs = pairs[: max_pairs or min(6, len(pairs))]
        elif mode == "swiss":
            pairs = pairs[: max_pairs or min(len(variants), len(pairs))]
        else:
            raise ArenaError(f"Unsupported pairwise mode: {mode}")
        if max_pairs is not None:
            pairs = pairs[:max_pairs]
        results = [self.pairwise_judge(arena_id, a, b, judge_runner=judge_runner, judge_model=judge_model) for a, b in pairs]
        scoreboard = self.scoreboard(arena_id, include_metadata=True)
        return {"arena_id": arena_id, "pairs": len(results), "results": results, "scoreboard": scoreboard}

    def score(self, arena_id: str, weights_profile: str = "balanced") -> dict[str, Any]:
        arena = self.load_arena(arena_id)
        weights = self.policy.get("scoring_profiles", {}).get(weights_profile) or self.policy["scoring_profiles"]["balanced"]
        variant_scores = {}
        any_passed = any((v.get("checks", {}) or {}).get("passed") is True for v in arena["variants"].values())
        for name, rec in arena["variants"].items():
            det = deterministic_variant_score(rec, weights)
            hard_gate_failed = False
            reasons = []
            if any_passed and (rec.get("checks", {}) or {}).get("passed") is False:
                hard_gate_failed = True
                reasons.append("failed_checks_cannot_win_if_any_pass")
            if any(str(flag).startswith("critical") for flag in rec.get("risk_flags", [])):
                hard_gate_failed = True
                reasons.append("security_critical_cannot_win")
            elo = arena.get("pairwise", {}).get("elo", {}).get(name, self.policy.get("pairwise", {}).get("initial_elo", 1500))
            elo_component = max(0, min(100, 50 + (elo - 1500) / 4))
            total = det["score"] + (weights.get("elo", 0) * elo_component / 100)
            variant_scores[name] = {
                "deterministic_score": det["score"],
                "elo": elo,
                "elo_component": round(elo_component, 2),
                "score": round(total, 2),
                "hard_gate_failed": hard_gate_failed,
                "hard_gate_reasons": reasons,
                "components": det["components"],
            }
        eligible = {k: v for k, v in variant_scores.items() if not v["hard_gate_failed"]}
        winner = max(eligible or variant_scores, key=lambda k: variant_scores[k]["score"]) if variant_scores else None
        arena["winner"] = winner
        self._save_arena(arena)
        return {"arena_id": arena_id, "winner": winner, "scores": variant_scores, "weights_profile": weights_profile}

    def scoreboard(self, arena_id: str, include_metadata: bool = True, include_pairwise_matrix: bool = True) -> dict[str, Any]:
        arena = self.load_arena(arena_id)
        score = self.score(arena_id)
        arena = self.load_arena(arena_id)
        variants = arena["variants"]
        pairwise_results = arena.get("pairwise", {}).get("results", [])
        rows = []
        for name, rec in variants.items():
            diff = rec.get("diff", {}) or {}
            checks = rec.get("checks", {}) or {}
            tokens_total = 0
            latency_total = 0
            run_count = 0
            for run_id in rec.get("runs", []):
                meta = read_json(self.base_dir / "runs" / run_id / "metadata.json", {})
                if meta:
                    run_count += 1
                    tokens = meta.get("tokens", {}) or {}
                    if isinstance(tokens.get("total_tokens"), int):
                        tokens_total += tokens["total_tokens"]
                    timing = meta.get("timing", {}) or {}
                    if isinstance(timing.get("wall_ms"), int):
                        latency_total += timing["wall_ms"]
            wl = self._win_loss_draw(name, pairwise_results)
            rows.append({
                "variant": name,
                "elo": arena.get("pairwise", {}).get("elo", {}).get(name),
                "wld": wl,
                "tests": checks.get("status") or ("pass" if checks.get("passed") else "pending"),
                "risk": "critical" if any(str(f).startswith("critical") for f in rec.get("risk_flags", [])) else "flagged" if rec.get("risk_flags") else "normal",
                "diff": f"{diff.get('files_changed', 0)} files / +{diff.get('lines_added', 0)} -{diff.get('lines_removed', 0)}",
                "tokens": tokens_total or None,
                "latency_ms": latency_total or None,
                "score": score["scores"].get(name, {}).get("score"),
            })
        rows.sort(key=lambda r: (r.get("score") or 0, r.get("elo") or 0), reverse=True)
        markdown = self._render_scoreboard_markdown(arena, rows, score, pairwise_results if include_pairwise_matrix else [])
        report_path = self.reports_dir / f"{arena_id}-scoreboard.md"
        report_path.write_text(markdown, encoding="utf-8")
        return {"arena_id": arena_id, "winner": score.get("winner"), "rows": rows, "report_path": str(report_path), "markdown": markdown}

    def _win_loss_draw(self, variant: str, results: list[dict[str, Any]]) -> str:
        w = l = d = 0
        for r in results:
            if variant not in {r.get("variant_a"), r.get("variant_b")}:
                continue
            if r.get("winner") == "draw":
                d += 1
            elif r.get("winner") == variant:
                w += 1
            else:
                l += 1
        return f"{w}-{l}-{d}"

    def _render_scoreboard_markdown(self, arena: dict[str, Any], rows: list[dict[str, Any]], score: dict[str, Any], pairwise_results: list[dict[str, Any]]) -> str:
        lines = [
            "# Shadow PR Arena Scoreboard",
            "",
            f"Arena: `{arena['arena_id']}`",
            f"Task: {arena.get('task')}",
            f"Base commit: `{arena.get('base_commit')}`",
            f"Winner: **{score.get('winner')}**",
            "",
            "| Variant | Elo | W-L-D | Checks | Risk | Diff | Tokens | Latency | Score |",
            "|---|---:|---:|---|---|---|---:|---:|---:|",
        ]
        for r in rows:
            lines.append(
                f"| {r['variant']} | {r.get('elo') or ''} | {r['wld']} | {r['tests']} | {r['risk']} | {r['diff']} | {r.get('tokens') or ''} | {r.get('latency_ms') or ''} | {r.get('score') or ''} |"
            )
        if pairwise_results:
            variants = list(arena["variants"].keys())
            lines.extend(["", "## Pairwise matrix", ""])
            header = "| | " + " | ".join(variants) + " |"
            sep = "|---|" + "|".join(["---" for _ in variants]) + "|"
            lines.extend([header, sep])
            lookup: dict[tuple[str, str], str] = {}
            for r in pairwise_results:
                a, b, winner = r.get("variant_a"), r.get("variant_b"), r.get("winner")
                if winner == "draw":
                    lookup[(a, b)] = "D"
                    lookup[(b, a)] = "D"
                else:
                    lookup[(a, b)] = "W" if winner == a else "L"
                    lookup[(b, a)] = "W" if winner == b else "L"
            for a in variants:
                cells = []
                for b in variants:
                    cells.append("—" if a == b else lookup.get((a, b), ""))
                lines.append("| " + a + " | " + " | ".join(cells) + " |")
            lines.extend(["", "## Pairwise reasons", ""])
            for r in pairwise_results:
                reasons = "; ".join(r.get("reasons", [])[:3])
                lines.append(f"- `{r.get('variant_a')}` vs `{r.get('variant_b')}` → **{r.get('winner')}** ({r.get('confidence')}, {r.get('margin')}): {reasons}")
        return "\n".join(lines) + "\n"

    def promote_winner(self, arena_id: str, variant: str | None = None, mode: str = "patch") -> dict[str, Any]:
        arena = self.load_arena(arena_id)
        variant = variant or arena.get("winner") or self.score(arena_id)["winner"]
        if not variant or variant not in arena["variants"]:
            raise ArenaError("No valid winner to promote")
        rec = arena["variants"][variant]
        if not rec.get("diff"):
            self.record_variant(arena_id, variant)
            arena = self.load_arena(arena_id)
            rec = arena["variants"][variant]
        source_patch = Path(rec["diff"].get("patch_path"))
        winner_patch = self.patches_dir / f"{arena_id}-winner-{variant}.patch"
        winner_patch.write_text(source_patch.read_text(encoding="utf-8"), encoding="utf-8")
        result: dict[str, Any] = {"arena_id": arena_id, "variant": variant, "mode": mode, "patch_path": str(winner_patch)}
        if mode == "apply":
            proc = run_cmd(["git", "apply", str(winner_patch)], cwd=self.repo_root, check=False)
            result.update({"applied": proc.returncode == 0, "stdout": proc.stdout, "stderr": proc.stderr})
            if proc.returncode != 0:
                raise ArenaError(f"Failed to apply winner patch:\n{proc.stderr or proc.stdout}")
        elif mode == "branch":
            branch = f"shadow/winner/{arena_id}/{variant}"[:240]
            run_cmd(["git", "checkout", "-b", branch, arena["base_commit"]], cwd=self.repo_root, check=True)
            proc = run_cmd(["git", "apply", str(winner_patch)], cwd=self.repo_root, check=False)
            result.update({"branch": branch, "applied": proc.returncode == 0, "stdout": proc.stdout, "stderr": proc.stderr})
            if proc.returncode != 0:
                raise ArenaError(f"Failed to apply winner patch on branch:\n{proc.stderr or proc.stdout}")
        elif mode != "patch":
            raise ArenaError("mode must be patch, apply, or branch")
        arena["status"] = "winner_promoted" if mode != "patch" else "winner_exported"
        arena["winner"] = variant
        self._save_arena(arena)
        self._append_arena_event(arena, "winner_promoted", result)
        return result

    def export_pr_bundle(self, arena_id: str) -> dict[str, Any]:
        sb = self.scoreboard(arena_id)
        arena = self.load_arena(arena_id)
        winner = arena.get("winner") or sb.get("winner")
        patch = self.promote_winner(arena_id, winner, mode="patch")
        summary_path = self.reports_dir / f"{arena_id}-pr-summary.md"
        summary = f"""# PR Summary from Shadow PR Arena

Task: {arena.get('task')}

Winner: {winner}

Artifacts:
- Scoreboard: {sb['report_path']}
- Winner patch: {patch['patch_path']}

## Why this variant won

See the scoreboard report for pairwise matrix, Elo ratings, checks, risk flags, and telemetry.
"""
        summary_path.write_text(summary, encoding="utf-8")
        return {"arena_id": arena_id, "winner": winner, "scoreboard_path": sb["report_path"], "winner_patch_path": patch["patch_path"], "pr_summary_path": str(summary_path)}

    def cleanup(self, arena_id: str, keep_patches: bool = True) -> dict[str, Any]:
        arena = self.load_arena(arena_id)
        results = {}
        for name, rec in arena["variants"].items():
            path = Path(rec["worktree"])
            if path.exists():
                results[name] = remove_worktree(self.repo_root, path, force=True)
        arena["status"] = "cleaned"
        self._save_arena(arena)
        self._append_arena_event(arena, "cleanup", results)
        return {"arena_id": arena_id, "removed": results, "keep_patches": keep_patches}
