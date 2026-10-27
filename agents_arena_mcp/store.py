"""Persistence under <repo>/.agents-arena/: one directory per arena, flock-guarded JSON, append-only logs."""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agents_arena_mcp.errors import ArenaError
from agents_arena_mcp.models import Arena

GITIGNORE = "*\n!.gitignore\n!config.toml\n"
LEGACY_HINT = """This repo has state from Agents Arena v0.1 (.agents-arena/state or policy.json).
v0.2 does not migrate it. Inspect and clean up, then retry:

  git worktree list            # remove any arena worktrees: git worktree remove --force <path>
  git branch --list 'arena/*' 'shadow/*'   # then: git branch -D <names>
  rm -rf .agents-arena/state .agents-arena/runs .agents-arena/patches .agents-arena/reports .agents-arena/logs .agents-arena/policy.json
"""


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def write_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(content)
    os.replace(tmp, path)


def append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, sort_keys=True) + "\n")


_held = threading.local()


@contextmanager
def file_lock(path: Path) -> Iterator[None]:
    """Exclusive flock on a dedicated lock file; re-entrant within a thread."""
    held: set[str] = getattr(_held, "paths", None) or set()
    _held.paths = held
    key = str(path)
    if key in held:
        yield
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        held.add(key)
        try:
            yield
        finally:
            held.discard(key)
            fcntl.flock(fh, fcntl.LOCK_UN)


class Store:
    def __init__(self, repo_root: Path):
        self.repo_root = repo_root
        self.root = repo_root / ".agents-arena"

    # ---- layout -------------------------------------------------------------
    def arena_dir(self, arena_id: str) -> Path:
        return self.root / "arenas" / arena_id

    def init(self) -> None:
        if (self.root / "state").exists() or (self.root / "policy.json").exists():
            raise ArenaError(LEGACY_HINT)
        self.root.mkdir(parents=True, exist_ok=True)
        gitignore = self.root / ".gitignore"
        if not gitignore.exists():
            gitignore.write_text(GITIGNORE, encoding="utf-8")

    # ---- arenas -------------------------------------------------------------
    def current_id(self) -> str:
        pointer = self.root / "current"
        if not pointer.exists():
            raise ArenaError("No arena yet. Start one with arena_open.")
        return pointer.read_text(encoding="utf-8").strip()

    def set_current(self, arena_id: str) -> None:
        write_atomic(self.root / "current", arena_id + "\n")

    def load(self, arena_id: str | None = None) -> Arena:
        arena_id = arena_id or self.current_id()
        path = self.arena_dir(arena_id) / "arena.json"
        if not path.exists():
            raise ArenaError(f"Arena not found: {arena_id}")
        return Arena.model_validate_json(path.read_text(encoding="utf-8"))

    def save(self, arena: Arena) -> None:
        write_atomic(self.arena_dir(arena.id) / "arena.json", arena.model_dump_json(indent=2))

    @contextmanager
    def mutate(self, arena_id: str) -> Iterator[Arena]:
        """Read-modify-write under the arena lock. Hold it only around state changes, never agent runs."""
        with file_lock(self.arena_dir(arena_id) / "arena.lock"):
            arena = self.load(arena_id)
            yield arena
            self.save(arena)

    def event(self, arena_id: str, event: str, **data: Any) -> None:
        append_jsonl(self.arena_dir(arena_id) / "events.jsonl", {"at": utc_now(), "event": event, **data})

    def ledger(self, record: dict[str, Any]) -> None:
        append_jsonl(self.root / "ledger.jsonl", {"at": utc_now(), **record})
