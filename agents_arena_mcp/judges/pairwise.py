from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agents_arena_mcp.core.elo import score_for_outcome, update_pair
from agents_arena_mcp.core.telemetry import RunLedger, new_run_id, run_subprocess_capture
from agents_arena_mcp.core.util import find_executable, sha256_text, utc_now, write_json
from agents_arena_mcp.judges.prompts import pairwise_judge_prompt


def patch_excerpt(patch: str, max_chars: int = 12000) -> str:
    if len(patch) <= max_chars:
        return patch
    head = patch[: max_chars // 2]
    tail = patch[-max_chars // 2 :]
    return head + "\n...[patch truncated]...\n" + tail


def variant_judge_view(name: str, variant: dict[str, Any]) -> dict[str, Any]:
    diff = variant.get("diff", {}) or {}
    return {
        "name": name,
        "state": variant.get("state"),
        "checks": variant.get("checks"),
        "risk_flags": variant.get("risk_flags", []),
        "diff_summary": {
            "files_changed": diff.get("files_changed"),
            "lines_added": diff.get("lines_added"),
            "lines_removed": diff.get("lines_removed"),
            "changed_files": diff.get("changed_files", []),
        },
        "patch_excerpt": patch_excerpt(diff.get("patch", "")),
    }


def heuristic_pairwise(arena: dict[str, Any], a: str, b: str) -> dict[str, Any]:
    va = arena["variants"][a]
    vb = arena["variants"][b]

    def rank(v: dict[str, Any]) -> float:
        diff = v.get("diff", {}) or {}
        checks = v.get("checks", {}) or {}
        flags = v.get("risk_flags", []) or []
        score = 0.0
        score += 100 if checks.get("passed") is True else 0 if checks else 35
        if any("critical" in f for f in flags):
            score -= 100
        changed = diff.get("changed_files", []) or []
        if any(p.startswith("tests/") or "/tests/" in p or p.endswith("_test.py") for p in changed):
            score += 20
        if any(p.startswith("docs/") or p.endswith(".md") for p in changed):
            score += 5
        files = diff.get("files_changed", 0) or 0
        lines = (diff.get("lines_added", 0) or 0) + (diff.get("lines_removed", 0) or 0)
        score -= min(files * 2.5, 30)
        score -= min(lines / 50, 25)
        return score

    sa = rank(va)
    sb = rank(vb)
    if abs(sa - sb) < 4:
        winner = "draw"
        confidence = 0.55
        margin = "tiny"
    elif sa > sb:
        winner = a
        confidence = min(0.9, 0.62 + abs(sa - sb) / 100)
        margin = "moderate" if abs(sa - sb) < 25 else "strong"
    else:
        winner = b
        confidence = min(0.9, 0.62 + abs(sa - sb) / 100)
        margin = "moderate" if abs(sa - sb) < 25 else "strong"

    reasons = []
    if (va.get("checks", {}) or {}).get("passed") != (vb.get("checks", {}) or {}).get("passed"):
        reasons.append("One variant has stronger check evidence.")
    if (va.get("diff", {}) or {}).get("files_changed", 0) != (vb.get("diff", {}) or {}).get("files_changed", 0):
        reasons.append("Blast radius differs by changed file count.")
    reasons.append("Heuristic judge used because no external judge runner was selected or available.")
    return {
        "winner": winner,
        "outcome": "draw" if winner == "draw" else "win",
        "confidence": round(confidence, 2),
        "margin": margin,
        "reasons": reasons,
        "risks": [],
        "judge_mode": "heuristic",
    }


def parse_judge_json(text: str, variant_a: str, variant_b: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        if stripped.startswith("json"):
            stripped = stripped[4:].strip()
    try:
        data = json.loads(stripped)
    except Exception:
        # Try to extract the first JSON object.
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start >= 0 and end > start:
            data = json.loads(stripped[start : end + 1])
        else:
            raise
    winner = data.get("winner")
    if winner not in {variant_a, variant_b, "draw"}:
        raise ValueError(f"Invalid judge winner {winner!r}")
    data.setdefault("outcome", "draw" if winner == "draw" else "win")
    data.setdefault("confidence", 0.7)
    data.setdefault("margin", "unknown")
    data.setdefault("reasons", [])
    data.setdefault("risks", [])
    data.setdefault("judge_mode", "external")
    return data


def external_judge(
    repo_root: Path,
    arena: dict[str, Any],
    variant_a: str,
    variant_b: str,
    runner: str,
    model: str | None,
    timeout_sec: int,
) -> dict[str, Any]:
    ledger = RunLedger(repo_root)
    run_id = new_run_id("judge")
    run_dir = ledger.run_dir(run_id)
    va = variant_judge_view(variant_a, arena["variants"][variant_a])
    vb = variant_judge_view(variant_b, arena["variants"][variant_b])
    prompt = pairwise_judge_prompt(arena, va, vb)
    prompt_path = ledger.write_prompt(run_id, prompt)
    result_path = run_dir / "result.json"

    schema_path = repo_root / ".shadow-pr-arena" / "schemas" / "pairwise-judge.schema.json"
    if runner == "codex":
        exe = find_executable("codex")
        if not exe:
            raise RuntimeError("codex executable not found")
        cmd = [exe, "exec", "--cd", str(repo_root), "--sandbox", "read-only", "--json", "--output-last-message", str(result_path)]
        if model:
            cmd.extend(["--model", model])
        if schema_path.exists():
            cmd.extend(["--output-schema", str(schema_path)])
        cmd.append(prompt)
    elif runner == "opencode":
        exe = find_executable("opencode")
        if not exe:
            raise RuntimeError("opencode executable not found")
        cmd = [exe, "run", "--dir", str(repo_root), "--format", "json"]
        if model:
            cmd.extend(["--model", model])
        cmd.append(prompt)
    else:
        raise ValueError(f"Unsupported external judge runner: {runner}")

    capture = run_subprocess_capture(cmd, cwd=repo_root, run_dir=run_dir, timeout_sec=timeout_sec)
    output_text = ""
    if result_path.exists():
        output_text = result_path.read_text(encoding="utf-8", errors="replace")
    else:
        stdout_path = Path(capture["outputs"]["stdout_path"])
        output_text = stdout_path.read_text(encoding="utf-8", errors="replace") if stdout_path.exists() else ""
    parsed = parse_judge_json(output_text, variant_a, variant_b)
    metadata = {
        "run_id": run_id,
        "arena_id": arena["arena_id"],
        "run_kind": "pairwise_judge",
        "variant_a": variant_a,
        "variant_b": variant_b,
        "judge_runner": runner,
        "judge_model": model,
        "status": capture["status"],
        "exit_code": capture["exit_code"],
        "timing": capture["timing"],
        "tokens": capture["tokens"],
        "prompt": {"prompt_path": str(prompt_path), "prompt_sha256": sha256_text(prompt)},
        "outputs": capture["outputs"] | {"result_path": str(result_path) if result_path.exists() else None},
        "result": parsed,
    }
    ledger.write_metadata(run_id, metadata)
    parsed["run_id"] = run_id
    parsed["metadata_path"] = str(run_dir / "metadata.json")
    parsed["tokens"] = capture["tokens"]
    parsed["latency_ms"] = capture["timing"]["wall_ms"]
    return parsed
