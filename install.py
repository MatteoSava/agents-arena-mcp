#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
from pathlib import Path


def copytree_merge(src: Path, dst: Path, overwrite: bool = False) -> None:
    for item in src.rglob("*"):
        rel = item.relative_to(src)
        target = dst / rel
        if item.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists() and not overwrite:
                continue
            shutil.copy2(item, target)


def append_once(path: Path, text: str, marker: str) -> None:
    current = path.read_text(encoding="utf-8") if path.exists() else ""
    if marker in current:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        if current and not current.endswith("\n"):
            fh.write("\n")
        fh.write("\n" + text.strip() + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Install Shadow PR Arena scaffold into a repository.")
    parser.add_argument("--target", default=".", help="Target repo root")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing scaffold files")
    parser.add_argument("--append-agents", action="store_true", help="Append AGENTS snippet")
    parser.add_argument("--append-claude", action="store_true", help="Append CLAUDE snippet")
    args = parser.parse_args()

    here = Path(__file__).resolve().parent
    target = Path(args.target).resolve()
    copytree_merge(here / "project_scaffold", target, overwrite=args.overwrite)

    if args.append_agents:
        snippet = (here / "project_scaffold" / "AGENTS.shadow-pr-arena.md").read_text(encoding="utf-8")
        append_once(target / "AGENTS.md", snippet, "SHADOW_PR_ARENA_SNIPPET")
    if args.append_claude:
        snippet = (here / "project_scaffold" / "CLAUDE.shadow-pr-arena.md").read_text(encoding="utf-8")
        append_once(target / "CLAUDE.md", snippet, "SHADOW_PR_ARENA_SNIPPET")

    print(f"Installed Shadow PR Arena scaffold into {target}")
    print("Next steps:")
    print("  1. pip install -e /path/to/agents-arena-mcp")
    print("  2. Configure Claude/Codex/OpenCode using the generated example files.")
    print("  3. Run: shadow-pr-arena --repo . open 'Compare strategies for my task'")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
