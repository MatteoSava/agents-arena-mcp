"""`agents-arena init --skills claude,codex,opencode`: install the guide as a skill for each agent."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agents_arena_mcp.config_data import data_text
from agents_arena_mcp.errors import ArenaError

SKILL_DIRS = {"claude": ".claude/skills/agents-arena", "codex": ".agents/skills/agents-arena",
              "opencode": ".opencode/skills/agents-arena"}  # fmt: skip
FRONTMATTER = """---
name: agents-arena
description: >
  Run experiments on coding agents: compare harnesses, models, skill edits or strategies with repeats and get a
  scorecard. Use when the user says "arena", "compare agents", "A/B this skill", or wants the best of several attempts.
---

"""


def init(root: Path, skills: str) -> dict[str, Any]:
    written = []
    for name in filter(None, (s.strip() for s in skills.split(","))):
        if name not in SKILL_DIRS:
            raise ArenaError(f"Unknown skill target {name!r}; choose from {', '.join(SKILL_DIRS)}")
        path = root / SKILL_DIRS[name] / "SKILL.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(FRONTMATTER + data_text("GUIDE.md"), encoding="utf-8")
        written.append(str(path))
    return {"written": written}
