from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from shadow_pr_arena_mcp.core.arena import ArenaEngine
from shadow_pr_arena_mcp.core.errors import ArenaError


def print_json(data: Any) -> None:
    print(json.dumps(data, indent=2, sort_keys=True))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="shadow-pr-arena", description="Shadow PR Arena MCP CLI")
    parser.add_argument("--repo", default=None, help="Repository root. Defaults to git root/cwd/env.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("open", help="Create a new arena")
    p.add_argument("task")
    p.add_argument("--base-ref", default="HEAD")
    p.add_argument("--variant", action="append", dest="variants", help="Variant name; can repeat")
    p.add_argument("--include-current-diff", action="store_true")
    p.add_argument("--risk-level", default="normal")

    p = sub.add_parser("status", help="Show arena status")
    p.add_argument("--arena-id", default=None)

    p = sub.add_parser("brief", help="Show variant brief")
    p.add_argument("arena_id")
    p.add_argument("variant")

    p = sub.add_parser("run-agent", help="Run a variant implementation agent")
    p.add_argument("arena_id")
    p.add_argument("variant")
    p.add_argument("--runner", default="manual", choices=["manual", "codex", "opencode"])
    p.add_argument("--model", default=None)
    p.add_argument("--timeout-sec", type=int, default=None)

    p = sub.add_parser("record", help="Record variant diff")
    p.add_argument("arena_id")
    p.add_argument("variant")
    p.add_argument("--notes", default="")

    p = sub.add_parser("checks", help="Run checks for a variant")
    p.add_argument("arena_id")
    p.add_argument("variant")
    p.add_argument("--command", action="append", dest="commands")
    p.add_argument("--timeout-sec", type=int, default=300)

    p = sub.add_parser("judge", help="Judge one pair")
    p.add_argument("arena_id")
    p.add_argument("variant_a")
    p.add_argument("variant_b")
    p.add_argument("--judge-runner", default="heuristic", choices=["heuristic", "auto", "codex", "opencode"])
    p.add_argument("--judge-model", default=None)

    p = sub.add_parser("judge-all", help="Judge all pairs")
    p.add_argument("arena_id")
    p.add_argument("--judge-runner", default="heuristic", choices=["heuristic", "auto", "codex", "opencode"])
    p.add_argument("--judge-model", default=None)
    p.add_argument("--max-pairs", type=int, default=None)
    p.add_argument("--mode", default="all_pairs", choices=["all_pairs", "swiss", "top_k_playoff"])

    p = sub.add_parser("score", help="Score variants")
    p.add_argument("arena_id")
    p.add_argument("--weights-profile", default="balanced")

    p = sub.add_parser("scoreboard", help="Render scoreboard")
    p.add_argument("arena_id")

    p = sub.add_parser("promote", help="Export/apply/branch winner")
    p.add_argument("arena_id")
    p.add_argument("--variant", default=None)
    p.add_argument("--mode", default="patch", choices=["patch", "apply", "branch"])

    p = sub.add_parser("export-pr-bundle", help="Export PR bundle")
    p.add_argument("arena_id")

    p = sub.add_parser("cleanup", help="Remove arena worktrees")
    p.add_argument("arena_id")
    p.add_argument("--discard-patches", action="store_true")

    args = parser.parse_args(argv)
    engine = ArenaEngine(Path(args.repo).resolve() if args.repo else None)

    try:
        if args.cmd == "open":
            print_json(engine.open(args.task, args.base_ref, args.variants, args.include_current_diff, args.risk_level))
        elif args.cmd == "status":
            print_json(engine.status(args.arena_id))
        elif args.cmd == "brief":
            print_json(engine.variant_brief(args.arena_id, args.variant))
        elif args.cmd == "run-agent":
            print_json(engine.run_variant_agent(args.arena_id, args.variant, args.runner, args.model, args.timeout_sec))
        elif args.cmd == "record":
            print_json(engine.record_variant(args.arena_id, args.variant, args.notes))
        elif args.cmd == "checks":
            print_json(engine.run_checks(args.arena_id, args.variant, args.commands, args.timeout_sec))
        elif args.cmd == "judge":
            print_json(engine.pairwise_judge(args.arena_id, args.variant_a, args.variant_b, args.judge_runner, args.judge_model))
        elif args.cmd == "judge-all":
            print_json(engine.judge_all_pairs(args.arena_id, args.judge_runner, args.judge_model, args.max_pairs, args.mode))
        elif args.cmd == "score":
            print_json(engine.score(args.arena_id, args.weights_profile))
        elif args.cmd == "scoreboard":
            data = engine.scoreboard(args.arena_id)
            print(data["markdown"])
        elif args.cmd == "promote":
            print_json(engine.promote_winner(args.arena_id, args.variant, args.mode))
        elif args.cmd == "export-pr-bundle":
            print_json(engine.export_pr_bundle(args.arena_id))
        elif args.cmd == "cleanup":
            print_json(engine.cleanup(args.arena_id, keep_patches=not args.discard_patches))
        return 0
    except ArenaError as exc:
        print_json({"error": str(exc)})
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
