from __future__ import annotations

import threading
from pathlib import Path

import pytest

from agents_arena_mcp.core.arena import ArenaEngine
from agents_arena_mcp.core.errors import ArenaError


def open_one(engine: ArenaEngine, name: str = "a") -> tuple[str, Path]:
    arena = engine.open("task", variants=[name])
    return arena["arena_id"], Path(arena["variants"][name]["worktree"])


def test_scoreboard_does_not_persist_winner(repo: Path):
    engine = ArenaEngine(repo)
    aid, wt = open_one(engine)
    (wt / "app.py").write_text("def value():\n    return 2\n")
    engine.record_variant(aid, "a")

    engine.scoreboard(aid)

    assert engine.load_arena(aid)["winner"] is None


def test_current_arena_does_not_follow_unrelated_saves(repo: Path):
    engine = ArenaEngine(repo)
    first, _ = open_one(engine, "a")
    second, _ = open_one(engine, "b")

    engine.record_variant(first, "a")

    assert engine.status()["arena_id"] == second


def test_status_without_arena_does_not_create_state(repo: Path):
    with pytest.raises(ArenaError):
        ArenaEngine(repo).status()
    assert not (repo / ".agents-arena").exists()


def test_concurrent_saves_do_not_lose_updates(repo: Path):
    engine = ArenaEngine(repo)
    arena = engine.open("task", variants=[f"v{i}" for i in range(6)])
    aid = arena["arena_id"]
    errors: list[BaseException] = []

    def note(name: str) -> None:
        try:
            ArenaEngine(repo).record_variant(aid, name, notes=f"note-{name}")
        except BaseException as exc:  # pragma: no cover - surfaced via assert
            errors.append(exc)

    threads = [threading.Thread(target=note, args=(f"v{i}",)) for i in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    final = engine.load_arena(aid)
    assert all(final["variants"][f"v{i}"]["notes"] == f"note-v{i}" for i in range(6))
