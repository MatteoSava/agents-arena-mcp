"""CLI: one subcommand per operation (same parameters as the MCP tools), plus `init` and `eval-judge`."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from agents_arena_mcp import __version__
from agents_arena_mcp.arena import (
    arena_check,
    arena_close,
    arena_judge,
    arena_open,
    arena_promote,
    arena_run,
    arena_status,
)
from agents_arena_mcp.errors import ArenaError
from agents_arena_mcp.search import arena_fork, arena_refine

COMMANDS = {
    "open": arena_open,
    "status": arena_status,
    "run": arena_run,
    "check": arena_check,
    "judge": arena_judge,
    "promote": arena_promote,
    "close": arena_close,
    "fork": arena_fork,
    "refine": arena_refine,
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agents-arena", description="Competing coding-agent variants, judged blind.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--repo", help="Repository root (default: git root of the current directory).")
    sub = parser.add_subparsers(dest="cmd", required=True)

    def cmd(name: str, help_: str) -> argparse.ArgumentParser:
        return sub.add_parser(name, help=help_)

    def arena_id(p: argparse.ArgumentParser) -> None:
        p.add_argument("--arena-id", help="Defaults to the most recently opened arena.")

    def variants(p: argparse.ArgumentParser, dest: str = "variants") -> None:
        p.add_argument("--variant", dest=dest, action="append", help="Repeatable. Defaults to all.")

    p = cmd("open", "Open an arena with one worktree per strategy")
    p.add_argument("task")
    variants(p)
    p.add_argument("--base-ref", default="HEAD")
    p.add_argument("--carry-uncommitted", action="store_true")
    p.add_argument("--explore", action="store_true")

    p = cmd("status", "Show arena status")
    arena_id(p)
    p.add_argument("--variant", help="Include this variant's brief.")

    p = cmd("run", "Run an agent in each variant workspace")
    arena_id(p)
    variants(p)
    p.add_argument("--runner")
    p.add_argument("--model", default="")
    p.add_argument("--timeout-sec", type=int)
    p.add_argument("--wait", action=argparse.BooleanOptionalAction, default=True)

    p = cmd("check", "Checkpoint variants, run checks and gates")
    arena_id(p)
    variants(p)

    p = cmd("judge", "Judge survivors pairwise in both orders and decide")
    arena_id(p)
    p.add_argument("--judge")
    p.add_argument("--model")
    p.add_argument("--wait", action=argparse.BooleanOptionalAction, default=True)

    p = cmd("promote", "Promote a variant (patch, branch, or apply)")
    arena_id(p)
    p.add_argument("--variant")
    p.add_argument("--mode", choices=["patch", "branch", "apply"], default="patch")

    p = cmd("close", "Remove worktrees and refs; keep artifacts unless --discard")
    arena_id(p)
    p.add_argument("--discard", dest="keep_artifacts", action="store_false")

    p = cmd("fork", "Fork variants from a checkpoint of another variant")
    p.add_argument("source")
    arena_id(p)
    p.add_argument("--name", dest="names", action="append", help="Repeatable. Defaults to pending strategies.")
    p.add_argument("--checkpoint", type=int)

    p = cmd("refine", "Fork the top contenders with the judge's critique")
    arena_id(p)
    variants(p)

    p = cmd("init", "Write .agents-arena/config.toml and install the workflow skill")
    p.add_argument("--skills", default="", help="Comma-separated: claude,codex,opencode")
    p.add_argument("--force", action="store_true", help="Overwrite an existing config.toml")

    p = cmd("eval-judge", "Measure the configured judge on seeded pairs with known winners")
    p.add_argument("--cases", default="", help="Directory of case TOML files (default: bundled)")
    p.add_argument("--judge")
    p.add_argument("--model")
    p.add_argument("--out", default="", help="Directory for results JSON (default: evals/judge/results)")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.repo:
        os.environ["AGENTS_ARENA_ROOT"] = str(Path(args.repo).resolve())
    kwargs = {k: v for k, v in vars(args).items() if k not in {"cmd", "repo"}}
    try:
        if args.cmd == "init":
            from agents_arena_mcp.scaffold import init

            result: Any = init(**kwargs)
        elif args.cmd == "eval-judge":
            from agents_arena_mcp.evals import eval_judge

            result = eval_judge(**kwargs)
        else:
            result = COMMANDS[args.cmd](**kwargs)
    except ArenaError as exc:
        print(json.dumps({"error": str(exc)}, indent=2), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
