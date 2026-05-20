#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

root = Path.cwd()
current = root / ".agents-arena" / "state" / "current-arena.json"
if not current.exists():
    raise SystemExit(0)
try:
    arena = json.loads(current.read_text(encoding="utf-8"))
except Exception:
    raise SystemExit(0)
status = arena.get("status")
if status == "open" and not arena.get("winner"):
    print("Agents Arena is still open and has no winner. Run arena_judge_all_pairs or arena_scoreboard, or explicitly close/cleanup the arena.", flush=True)
    raise SystemExit(2)
raise SystemExit(0)
