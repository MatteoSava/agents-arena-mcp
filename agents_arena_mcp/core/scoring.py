from __future__ import annotations

from typing import Any


def category_for_file(path: str) -> str:
    if path.startswith(("tests/", "test/")) or "/tests/" in path or path.endswith("_test.py"):
        return "test"
    if path.startswith("docs/") or path.endswith((".md", ".rst")):
        return "docs"
    if path.endswith((".py",)):
        return "python"
    if path.endswith((".tsx", ".jsx", ".ts", ".js", ".css", ".html", ".vue", ".svelte")):
        return "frontend"
    if path.endswith((".tf", ".tfvars")) or path.startswith(("infra/", "k8s/", "terraform/")):
        return "iac"
    if path.startswith(".github/workflows/") or path.endswith((".yml", ".yaml")):
        return "config"
    return "other"


def blast_radius_score(files_changed: int) -> float:
    if files_changed <= 2:
        return 1.0
    if files_changed <= 5:
        return 0.8
    if files_changed <= 10:
        return 0.55
    if files_changed <= 20:
        return 0.3
    return 0.1


def diff_minimality_score(lines_added: int, lines_removed: int) -> float:
    total = lines_added + lines_removed
    if total <= 30:
        return 1.0
    if total <= 100:
        return 0.8
    if total <= 250:
        return 0.55
    if total <= 600:
        return 0.3
    return 0.1


def test_value_score(changed_files: list[str]) -> float:
    return 1.0 if any(category_for_file(f) == "test" for f in changed_files) else 0.0


def docs_score(changed_files: list[str]) -> float:
    return 1.0 if any(category_for_file(f) == "docs" for f in changed_files) else 0.0


def safety_score(flags: list[str]) -> float:
    if any(flag.startswith("critical") for flag in flags):
        return 0.0
    if flags:
        return 0.5
    return 1.0


def deterministic_variant_score(variant: dict[str, Any], weights: dict[str, int]) -> dict[str, Any]:
    diff = variant.get("diff", {}) or {}
    checks = variant.get("checks", {}) or {}
    changed_files = diff.get("changed_files", []) or []
    flags = variant.get("risk_flags", []) or []
    check_score = 1.0 if checks.get("passed") is True else 0.0 if checks else 0.4
    components = {
        "checks": check_score,
        "tests": test_value_score(changed_files),
        "diff_minimality": diff_minimality_score(diff.get("lines_added", 0), diff.get("lines_removed", 0)),
        "blast_radius": blast_radius_score(diff.get("files_changed", 0)),
        "maintainability": 0.65,  # intentionally conservative until agent judge supplies better signal
        "docs": docs_score(changed_files),
        "safety": safety_score(flags),
    }
    total_weight = sum(v for k, v in weights.items() if k in components)
    score = 0.0
    for key, value in components.items():
        score += value * weights.get(key, 0)
    normalized = round((score / total_weight) * 100, 2) if total_weight else 0
    return {"score": normalized, "components": components}
