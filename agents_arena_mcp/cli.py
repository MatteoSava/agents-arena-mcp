"""CLI: the same five operations as the MCP tools (same parameter names), plus init."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tomllib
from pathlib import Path
from typing import Any

from agents_arena_mcp import __version__
from agents_arena_mcp.arena import arena_history, arena_plan, arena_result, arena_start, arena_status, store
from agents_arena_mcp.errors import ArenaError

COMMANDS = {
    "plan": arena_plan,
    "start": arena_start,
    "status": arena_status,
    "result": arena_result,
    "history": arena_history,
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agents-arena", description="Experiments on coding agents.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--repo", help="Repository root (default: git root of the current directory).")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan", help="Draft a spec (interview questions or autopilot draft)")
    p.add_argument("request")
    p.add_argument("--mode", choices=["interview", "autopilot"], default="interview")
    p = sub.add_parser("start", help="Run a spec file (TOML or JSON)")
    p.add_argument("spec", help="Path to the spec file")
    p.add_argument("--wait", action=argparse.BooleanOptionalAction, default=True)
    p = sub.add_parser("status", help="Show arena progress")
    p.add_argument("--arena-id")
    p = sub.add_parser("result", help="Show the scorecard; optionally write HTML or promote")
    p.add_argument("--arena-id")
    p.add_argument("--html", action="store_true")
    p.add_argument("--promote", choices=["patch", "branch", "apply"])
    p = sub.add_parser("history", help="Past arena results")
    p.add_argument("--contestant")
    p.add_argument("--task-contains")
    p.add_argument("--limit", type=int, default=20)
    p = sub.add_parser("init", help="Install the arena skill for your agents")
    p.add_argument("--skills", default="claude")
    return parser


def _load_spec(path: str) -> dict[str, Any]:
    text = Path(path).read_text(encoding="utf-8")
    return tomllib.loads(text) if path.endswith(".toml") else json.loads(text)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.repo:
        os.environ["AGENTS_ARENA_ROOT"] = str(Path(args.repo).resolve())
    kwargs = {k: v for k, v in vars(args).items() if k not in {"cmd", "repo"}}
    try:
        if args.cmd == "init":
            from agents_arena_mcp.scaffold import init

            result: Any = init(store().repo_root, args.skills)
        else:
            if args.cmd == "start":
                if not args.wait:
                    raise ArenaError(
                        "Background runs need the MCP server (this CLI process would exit and kill them); use --wait"
                    )
                kwargs["spec"] = _load_spec(kwargs["spec"])
            result = COMMANDS[args.cmd](**kwargs)
    except ArenaError as exc:
        print(json.dumps({"error": str(exc)}, indent=2), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, default=str))
    return 0
