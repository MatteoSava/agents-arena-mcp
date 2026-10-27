"""`agents-arena init`: config file, state .gitignore, and the workflow skill for each agent."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agents_arena_mcp.arena import context
from agents_arena_mcp.config import data_text
from agents_arena_mcp.errors import ArenaError

SKILL_DIRS = {
    "claude": ".claude/skills/agents-arena",
    "codex": ".agents/skills/agents-arena",
    "opencode": ".opencode/skills/agents-arena",
}
MCP_SNIPPET = {
    "mcpServers": {
        "agents-arena": {
            "command": "uvx",
            "args": ["--from", "git+https://github.com/MatteoSava/agents-arena-mcp@v0.2.0", "agents-arena-mcp"],
        }
    }
}


def init(skills: str = "", force: bool = False) -> dict[str, Any]:
    store, _ = context()
    store.init()
    written = []
    config = store.root / "config.toml"
    if force or not config.exists():
        config.write_text(data_text("config.default.toml"), encoding="utf-8")
        written.append(str(config))
    for name in filter(None, (s.strip() for s in skills.split(","))):
        if name not in SKILL_DIRS:
            raise ArenaError(f"Unknown skill target {name!r}; choose from {', '.join(SKILL_DIRS)}")
        path = Path(store.repo_root) / SKILL_DIRS[name] / "SKILL.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(data_text("SKILL.md"), encoding="utf-8")
        written.append(str(path))
    return {"written": written, "mcp_config": MCP_SNIPPET}
