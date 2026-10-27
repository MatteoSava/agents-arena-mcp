"""Configuration: packaged defaults overlaid with the repo's .agents-arena/config.toml."""

from __future__ import annotations

import tomllib
from importlib import resources
from pathlib import Path

from pydantic import BaseModel, Field

from agents_arena_mcp.errors import ArenaError


class CheckSpec(BaseModel):
    name: str
    cmd: str


class CommandSpec(BaseModel):
    """An argv template for an agent or judge CLI."""

    argv: list[str]
    model_flag: list[str] = Field(default_factory=list)
    family: str = ""


class JudgeConfig(BaseModel):
    runner: str = "none"
    model: str = ""
    timeout_sec: int = 600
    max_survivors: int = 5
    template: str = ""
    distinguish: bool = False
    max_refine_depth: int = 1
    agentic_final: str = ""


class Config(BaseModel):
    default_variants: list[str]
    default_runner: str = "manual"
    max_variants: int = 6
    max_parallel: int = 4
    run_timeout_sec: int = 1800
    check_timeout_sec: int = 600
    worktree_root: str = ""
    setup: str = ""
    brief_template: str = ""
    checks: list[CheckSpec] = Field(default_factory=list)
    protected_paths: list[str] = Field(default_factory=list)
    secret_patterns: list[str] = Field(default_factory=list)
    strategies: dict[str, str] = Field(default_factory=dict)
    judge: JudgeConfig = Field(default_factory=JudgeConfig)
    runners: dict[str, CommandSpec] = Field(default_factory=dict)
    judges: dict[str, CommandSpec] = Field(default_factory=dict)

    def strategy_text(self, name: str) -> str:
        return self.strategies.get(name, f"Implement the task following the '{name}' approach.")


def data_text(name: str) -> str:
    return resources.files("agents_arena_mcp.data").joinpath(name).read_text(encoding="utf-8")


def _merge(base: dict, override: dict) -> dict:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_config(repo_root: Path) -> Config:
    """Always read from the main repo, never from a variant worktree (variants are untrusted)."""
    data = tomllib.loads(data_text("config.default.toml"))
    path = repo_root / ".agents-arena" / "config.toml"
    if path.exists():
        try:
            data = _merge(data, tomllib.loads(path.read_text(encoding="utf-8")))
        except tomllib.TOMLDecodeError as exc:
            raise ArenaError(f"Invalid {path}: {exc}") from exc
    return Config.model_validate(data)


def template_text(repo_root: Path, override: str, default_name: str) -> str:
    if override:
        path = Path(override) if Path(override).is_absolute() else repo_root / override
        return path.read_text(encoding="utf-8")
    return data_text(default_name)
