from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .errors import ArenaError
from .util import ensure_dir, read_json, write_json

DEFAULT_POLICY: dict[str, Any] = {
    "version": 1,
    "worktrees": {
        "location": "../.agents-arena-worktrees/{repo_name}",
        "refuse_dirty_repo_by_default": True,
    },
    "variants": [
        "minimal_patch",
        "test_first",
        "clean_boundary",
        "maintainability_refactor",
    ],
    "runner": {
        "default_runner": "manual",
        "default_judge_runner": "heuristic",
        "timeout_sec": 900,
        "sandbox": "workspace-write",
        "approval_mode": "prompt",
        "max_parallel_runs": 1,
    },
    "pairwise": {
        "default_mode": "all_pairs",
        "max_all_pairs_variants": 5,
        "initial_elo": 1500,
        "k_factor": 32,
        "judge_count": 1,
    },
    "scoring_profiles": {
        "balanced": {
            "checks": 35,
            "tests": 15,
            "diff_minimality": 10,
            "blast_radius": 15,
            "maintainability": 10,
            "docs": 5,
            "safety": 10,
            "elo": 20,
        },
        "minimal_risk": {
            "checks": 30,
            "tests": 20,
            "diff_minimality": 20,
            "blast_radius": 20,
            "maintainability": 5,
            "docs": 0,
            "safety": 5,
            "elo": 20,
        },
        "architecture": {
            "checks": 25,
            "tests": 15,
            "diff_minimality": 5,
            "blast_radius": 15,
            "maintainability": 25,
            "docs": 10,
            "safety": 5,
            "elo": 20,
        },
    },
    "checks": {
        "generic": ["git diff --check"],
        "python": ["python -m pytest -q", "python -m ruff check ."],
        "node": ["npm test", "npm run lint"],
        "frontend": ["browser smoke evidence required"],
        "terraform": ["terraform fmt -check", "terraform validate", "terraform plan -detailed-exitcode"],
    },
    "hard_gates": {
        "failed_checks_cannot_win_if_any_pass": True,
        "security_critical_cannot_win": True,
        "compile_failure_cannot_win": True,
    },
    "safety": {
        "allow_network_commands": False,
        "blocked_command_patterns": [
            r"\brm\s+-rf\s+(/|\.|~|\$HOME)",
            r"\bgit\s+reset\s+--hard\b",
            r"\bgit\s+clean\s+-fdx\b",
            r"\bterraform\s+(apply|destroy)\b",
            r"\btofu\s+(apply|destroy)\b",
            r"\bkubectl\s+delete\b",
            r"\bhelm\s+(uninstall|delete)\b",
            r"\bdocker\s+system\s+prune\b",
            r"\bdocker\s+volume\s+prune\b",
            r"\bchmod\s+-R\s+777\b",
            r"\bcurl\b.*\|\s*(bash|sh)",
            r"\bwget\b.*\|\s*(bash|sh)",
            r"\bdd\b.*\bof=/dev/",
            r"\bmkfs\b",
            r"\bfdisk\b",
        ],
        "secret_path_patterns": [
            r"(^|/)\.env($|\.)",
            r"secret",
            r"credential",
            r"private[_-]?key",
            r"id_rsa",
            r"id_ed25519",
        ],
    },
}


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def policy_path(repo_root: Path) -> Path:
    return repo_root / ".agents-arena" / "policy.json"


def load_policy(repo_root: Path) -> dict[str, Any]:
    path = policy_path(repo_root)
    if path.exists():
        return deep_merge(DEFAULT_POLICY, read_json(path, {}))
    return DEFAULT_POLICY.copy()


def init_policy(repo_root: Path, overwrite: bool = False) -> Path:
    path = policy_path(repo_root)
    if path.exists() and not overwrite:
        return path
    ensure_dir(path.parent)
    write_json(path, DEFAULT_POLICY)
    return path


def assert_command_allowed(command: str, policy: dict[str, Any]) -> None:
    for pattern in policy.get("safety", {}).get("blocked_command_patterns", []):
        if re.search(pattern, command, flags=re.IGNORECASE):
            raise ArenaError(f"Blocked unsafe command by policy: {command!r} matched {pattern!r}")


def path_has_secret_signal(path: str, policy: dict[str, Any]) -> bool:
    for pattern in policy.get("safety", {}).get("secret_path_patterns", []):
        if re.search(pattern, path, flags=re.IGNORECASE):
            return True
    return False
