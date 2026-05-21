from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Callable

from agents_arena_mcp import __version__
from agents_arena_mcp.core.arena import ArenaEngine
from agents_arena_mcp.core.errors import ArenaError

DryRunArgsExtractor = Callable[[argparse.Namespace], dict[str, Any]]
DryRunTextBuilder = Callable[[argparse.Namespace], str]


def print_json(data: Any) -> None:
    print(json.dumps(data, indent=2, sort_keys=True))


def _cleanup_args(args: argparse.Namespace) -> dict[str, Any]:
    return {"arena_id": args.arena_id, "keep_patches": not args.discard_patches}


def _current_or_named_arena(arena_id: str | None) -> str:
    return f"arena {arena_id!r}" if arena_id else "the current arena"


CMD_INFO: dict[str, dict[str, str | list[str] | DryRunArgsExtractor | DryRunTextBuilder]] = {
    "open": {
        "engine_method": "open",
        "args": lambda args: {
            "task": args.task,
            "base_ref": args.base_ref,
            "variants": args.variants,
            "include_current_diff": args.include_current_diff,
            "risk_level": args.risk_level,
        },
        "description": lambda args: f"Would create a new arena with task {args.task!r} using base ref {args.base_ref}.",
        "side_effects": [
            "Creates git worktrees for each variant",
            "Writes arena metadata to .agents-arena/state/",
            "Appends an arena_open event to .agents-arena/state/arenas.jsonl",
        ],
    },
    "status": {
        "engine_method": "status",
        "args": lambda args: {"arena_id": args.arena_id},
        "description": lambda args: f"Would show status for {_current_or_named_arena(args.arena_id)}.",
        "side_effects": [],
    },
    "brief": {
        "engine_method": "variant_brief",
        "args": lambda args: {"arena_id": args.arena_id, "variant": args.variant},
        "description": lambda args: f"Would show the variant brief for {args.variant!r} in arena {args.arena_id!r}.",
        "side_effects": [],
    },
    "run-agent": {
        "engine_method": "run_variant_agent",
        "args": lambda args: {
            "arena_id": args.arena_id,
            "variant": args.variant,
            "runner": args.runner,
            "model": args.model,
            "timeout_sec": args.timeout_sec,
        },
        "description": lambda args: f"Would run the {args.runner} agent for variant {args.variant!r} in arena {args.arena_id!r}.",
        "side_effects": [
            "Runs an implementation agent inside the variant worktree",
            "Records the run in arena state",
            "Appends a variant_run event to .agents-arena/state/arenas.jsonl",
        ],
    },
    "record": {
        "engine_method": "record_variant",
        "args": lambda args: {"arena_id": args.arena_id, "variant": args.variant, "notes": args.notes},
        "description": lambda args: f"Would record the diff for variant {args.variant!r} in arena {args.arena_id!r}.",
        "side_effects": [
            "Computes the diff against the arena base commit",
            "Writes a patch file to .agents-arena/patches/",
            "Updates variant metadata in .agents-arena/state/",
            "Appends a variant_recorded event to .agents-arena/state/arenas.jsonl",
        ],
    },
    "checks": {
        "engine_method": "run_checks",
        "args": lambda args: {
            "arena_id": args.arena_id,
            "variant": args.variant,
            "commands": args.commands,
            "timeout_sec": args.timeout_sec,
        },
        "description": lambda args: f"Would run checks for variant {args.variant!r} in arena {args.arena_id!r}.",
        "side_effects": [
            "May record the variant diff before running checks",
            "Executes allowed check commands inside the variant worktree",
            "Updates check results in .agents-arena/state/",
            "Appends a checks_run event to .agents-arena/state/arenas.jsonl",
        ],
    },
    "judge": {
        "engine_method": "pairwise_judge",
        "args": lambda args: {
            "arena_id": args.arena_id,
            "variant_a": args.variant_a,
            "variant_b": args.variant_b,
            "judge_runner": args.judge_runner,
            "judge_model": args.judge_model,
        },
        "description": lambda args: f"Would judge variant {args.variant_a!r} against {args.variant_b!r} in arena {args.arena_id!r}.",
        "side_effects": [
            "May record missing variant diffs before judging",
            "Runs heuristic or external judging",
            "Updates pairwise Elo ratings in .agents-arena/state/",
            "Appends pairwise results to telemetry and arena history",
        ],
    },
    "judge-all": {
        "engine_method": "judge_all_pairs",
        "args": lambda args: {
            "arena_id": args.arena_id,
            "judge_runner": args.judge_runner,
            "judge_model": args.judge_model,
            "max_pairs": args.max_pairs,
            "mode": args.mode,
        },
        "description": lambda args: f"Would judge variant pairs for arena {args.arena_id!r} using {args.mode} mode.",
        "side_effects": [
            "Runs pairwise judging for one or more variant pairs",
            "Updates Elo ratings and pairwise match history",
            "Recomputes the scoreboard report in .agents-arena/reports/",
        ],
    },
    "score": {
        "engine_method": "score",
        "args": lambda args: {"arena_id": args.arena_id, "weights_profile": args.weights_profile},
        "description": lambda args: f"Would score variants for arena {args.arena_id!r} using the {args.weights_profile!r} profile.",
        "side_effects": [
            "Computes deterministic and Elo-based scores",
            "Updates the stored winner in .agents-arena/state/",
        ],
    },
    "scoreboard": {
        "engine_method": "scoreboard",
        "args": lambda args: {"arena_id": args.arena_id},
        "description": lambda args: f"Would render the scoreboard for arena {args.arena_id!r}.",
        "side_effects": [
            "Recomputes scores and winner for the arena",
            "Writes a markdown scoreboard report to .agents-arena/reports/",
        ],
    },
    "promote": {
        "engine_method": "promote_winner",
        "args": lambda args: {"arena_id": args.arena_id, "variant": args.variant, "mode": args.mode},
        "description": lambda args: f"Would promote the winner for arena {args.arena_id!r} using {args.mode!r} mode.",
        "side_effects": [
            "May record the winner diff before promotion",
            "Writes a winner patch to .agents-arena/patches/",
            "May apply the patch or create a branch in the repository",
            "Updates arena status in .agents-arena/state/",
        ],
    },
    "export-pr-bundle": {
        "engine_method": "export_pr_bundle",
        "args": lambda args: {"arena_id": args.arena_id},
        "description": lambda args: f"Would export a PR bundle for arena {args.arena_id!r}.",
        "side_effects": [
            "Recomputes the scoreboard and winner",
            "Writes winner patch and PR summary artifacts",
            "Writes markdown reports to .agents-arena/reports/",
        ],
    },
    "cleanup": {
        "engine_method": "cleanup",
        "args": _cleanup_args,
        "description": lambda args: (
            f"Would remove arena worktrees for arena {args.arena_id!r} and discard saved patches."
            if args.discard_patches
            else f"Would remove arena worktrees for arena {args.arena_id!r} while keeping saved patches."
        ),
        "side_effects": [
            "Removes variant git worktrees",
            "Updates arena status to cleaned in .agents-arena/state/",
            "Appends a cleanup event to .agents-arena/state/arenas.jsonl",
        ],
    },
}


def build_dry_run_payload(args: argparse.Namespace) -> dict[str, Any]:
    info = CMD_INFO[args.cmd]
    extractor = info["args"]
    description = info["description"]
    return {
        "dry_run": True,
        "command": args.cmd,
        "engine_method": info["engine_method"],
        "args": extractor(args) if callable(extractor) else {},
        "description": description(args) if callable(description) else "",
        "side_effects": list(info["side_effects"]),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agents-arena", description="Agents Arena MCP CLI")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--repo", default=None, help="Repository root. Defaults to git root/cwd/env.")
    parser.add_argument("--dry-run", action="store_true", help="Show the engine call and side effects without running it.")
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
    if args.dry_run:
        print_json(build_dry_run_payload(args))
        return 0

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
