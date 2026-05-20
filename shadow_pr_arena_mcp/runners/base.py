from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


@dataclass
class RunnerRequest:
    repo_root: Path
    worktree: Path
    arena_id: str
    variant: str
    prompt: str
    model: str | None = None
    timeout_sec: int = 900
    sandbox: str = "workspace-write"
    approval_mode: str = "prompt"


class Runner(Protocol):
    name: str

    def run(self, request: RunnerRequest) -> dict[str, Any]:
        ...
