"""arena_plan's logic: detect how the repo is tested and which harnesses exist, then draft a spec.

The MCP doesn't interpret the request: the calling agent does. Autopilot returns a filled draft for the agent
to adapt; interview returns the questions the agent should ask the user first.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path
from typing import Any

from agents_arena_mcp import harness
from agents_arena_mcp.models import Check, Spec

# Lockfile -> (package manager, install command). Order matters: the first lockfile present wins.
NODE_LOCKS = (("pnpm-lock.yaml", "pnpm", "pnpm install --frozen-lockfile"), ("yarn.lock", "yarn", "yarn install --frozen-lockfile"),
              ("bun.lock", "bun", "bun install --frozen-lockfile"), ("bun.lockb", "bun", "bun install --frozen-lockfile"),
              ("package-lock.json", "npm", "npm ci"))  # fmt: skip


def _python_prefix(root: Path) -> str:
    if (root / "uv.lock").exists():
        return "uv run"
    if (root / "poetry.lock").exists():
        return "poetry run"
    return "python -m"


def _node(root: Path) -> tuple[str, str]:
    """(package manager, install command) for a Node repo, from its lockfile."""
    return next(((pm, cmd) for lock, pm, cmd in NODE_LOCKS if (root / lock).exists()), ("npm", "npm install"))


def _scripts(package: Path) -> dict[str, Any]:
    """package.json scripts, or {} when the file is malformed."""
    try:
        data = json.loads(package.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {}
    scripts = data.get("scripts") if isinstance(data, dict) else None
    return scripts if isinstance(scripts, dict) else {}


def detect_setup(root: Path) -> str:
    """The command a fresh worktree needs before checks can run. uv-managed Python needs none (`uv run` syncs)."""
    if (root / "package.json").exists():
        return _node(root)[1]
    if (root / "poetry.lock").exists():
        return "poetry install"
    return ""


def detect_checks(root: Path) -> list[Check]:
    found: list[Check] = []
    pyproject = root / "pyproject.toml"
    if pyproject.exists():
        text, prefix = pyproject.read_text(encoding="utf-8"), _python_prefix(root)
        if (root / "tests").is_dir() or "pytest" in text:
            found.append(Check(name="tests", cmd=f"{prefix} pytest -q"))
        if "[tool.ruff" in text or (root / "ruff.toml").exists():
            found.append(Check(name="lint", cmd=f"{prefix} ruff check ."))
    package = root / "package.json"
    if package.exists():
        pm = _node(root)[0]
        found += [
            Check(name=f"js-{s}", cmd=f"{pm} run {s}") for s in ("test", "lint", "typecheck") if s in _scripts(package)
        ]
    if (root / "go.mod").exists():
        found.append(Check(name="go-test", cmd="go test ./..."))
    if (root / "Cargo.toml").exists():
        found.append(Check(name="rust-test", cmd="cargo test"))
    makefile = root / "Makefile"
    if not found and makefile.exists() and re.search(r"^test:", makefile.read_text(encoding="utf-8"), re.M):
        found.append(Check(name="tests", cmd="make test"))
    return found


def harness_status() -> dict[str, dict[str, Any]]:
    out = {}
    for name in ("claude", "codex", "opencode"):
        installed = shutil.which(name) is not None
        clean = {"claude": any(os.environ.get(v) for v in harness.TOKEN_VARS),
                 "codex": (Path.home() / ".codex" / "auth.json").exists(),
                 "opencode": any(os.environ.get(v) for v in harness.OPENCODE_PROVIDER_VARS)}[name]  # fmt: skip
        out[name] = {"installed": installed, "clean_ready": installed and clean, "family": harness.get(name).family}
        if name == "opencode":
            out[name]["note"] = (
                "clean opencode only sees providers keyed by environment variables; it also needs an explicit model"
            )
    return out


def questions(checks: list[Check], setup: str, status: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    installed = [n for n, s in status.items() if s["installed"]]
    return [
        {"id": "compare", "question": "What should differ between contestants?",
         "options": ["harness (claude/codex/opencode)", "model", "a skill or file (overlay)", "strategy (approach)"],
         "why": "Vary one thing at a time for a clean comparison."},
        {"id": "objective", "question": "What decides the winner?",
         "options": ["quality", "elegance", "speed", "tokens", "cost", "custom rubric text"], "default": "quality"},
        {"id": "baseline", "question": "Start each contestant from a clean harness or your real setup?",
         "options": ["clean (only what the overlays add)", "real (your skills, plugins, MCP servers)"], "default": "real",
         "why": "clean claude needs CLAUDE_CODE_OAUTH_TOKEN (`claude setup-token`); real never modifies your home."},
        {"id": "repeats", "question": "How many runs per contestant?", "options": [1, 3, 5], "default": 3,
         "why": "Agents are noisy; medians over repeats are more trustworthy than one run."},
        {"id": "checks", "question": "Which checks gate the runs?", "options": [c.model_dump() for c in checks],
         "default": [c.model_dump() for c in checks], "why": "Detected from the repo; only regressions vs. the base count."},
        {"id": "setup", "question": "Does a fresh checkout need a setup command before checks run?",
         "options": [setup] if setup else [], "default": setup,
         "why": "Runs once on the base commit and in every run's worktree (e.g. installing dependencies)."},
        {"id": "judge", "question": "Which harness judges quality?", "options": installed + ["none"],
         "why": "Prefer a different model family than the contestants (judges favor their own family)."},
        {"id": "ship", "question": "Should the winner be promotable as a patch/branch?", "options": [True, False], "default": False},
    ]  # fmt: skip


def make_plan(root: Path, request: str, mode: str) -> dict[str, Any]:
    checks, setup, status = detect_checks(root), detect_setup(root), harness_status()
    installed = [n for n, s in status.items() if s["installed"] and n != "opencode"] or ["claude"]
    judge = next((n for n in ("codex", "claude") if n in installed), "none")
    draft = Spec.model_validate({"task": request, "repeats": 3, "checks": [c.model_dump() for c in checks], "setup": setup,
                                 "judge": {"harness": judge}, "contestants": [{"name": n, "harness": n} for n in installed]})  # fmt: skip
    same_family = judge != "none" and any(harness.get(n).family == harness.get(judge).family for n in installed)
    judge_line = (f"judge: {judge} (same family as a contestant; prefer a different family or model for a fairer verdict)"
                  if same_family else f"judge: {judge} (prefer a different model family than the contestants)")  # fmt: skip
    out: dict[str, Any] = {"mode": mode, "draft_spec": draft.model_dump(by_alias=True), "detected_checks": [c.model_dump() for c in checks],
                           "detected_setup": setup, "harnesses": status, "spec_schema": Spec.model_json_schema(by_alias=True)}  # fmt: skip
    if mode == "interview":
        out["questions"] = questions(checks, setup, status)
        out["next"] = (
            "Ask the user these questions (one at a time), update draft_spec, show it, then call arena_start(spec)."
        )
    else:
        out["rationale"] = [
            f"contestants: one per installed harness ({', '.join(installed)}); replace with the comparison the user asked for",
            judge_line,
            "repeats: 3, enough for a median without much cost",
            f"checks: {', '.join(c.cmd for c in checks) or 'none detected; add the repo test command'}",
            f"setup: {setup or 'none needed'}",
        ]
        out["next"] = ("Adapt draft_spec to the user's request (contestants, overlays, objective), explain each choice "
                       "in one line, then call arena_start(spec).")  # fmt: skip
    return out
