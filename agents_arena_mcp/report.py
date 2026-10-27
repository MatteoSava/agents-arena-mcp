"""Markdown report and PR summary rendered from arena state."""

from __future__ import annotations

from itertools import combinations
from pathlib import Path
from typing import Any

from agents_arena_mcp.config import Config
from agents_arena_mcp.models import Arena, Variant
from agents_arena_mcp.select import pair_matches, pair_winner


def _diff_overlap(a: Variant, b: Variant) -> float:
    """Jaccard overlap of touched files: a cheap diversity signal between strategies."""
    fa = {f.path for f in a.snapshot.files} if a.snapshot else set()
    fb = {f.path for f in b.snapshot.files} if b.snapshot else set()
    return len(fa & fb) / len(fa | fb) if fa | fb else 1.0


def render(arena: Arena) -> str:
    d = arena.decision
    lines = [
        f"# Arena report: {arena.id}",
        "",
        f"**Task:** {arena.task}",
        f"**Base:** `{arena.base_commit[:12]}`"
        + (" (includes your uncommitted changes)" if arena.carried_uncommitted else ""),
    ]
    if d:
        verdict = f"**Decision:** {d.status}" + (f" → **{d.winner}**" if d.winner else "")
        lines += [verdict + (f" (tie broken by {d.tie_break})" if d.tie_break else ""), ""]
    if arena.baseline:
        base = ", ".join(f"{r.name}: {r.status}" for r in arena.baseline.results) or "no checks configured"
        lines += [f"**Baseline checks on base commit:** {base}", ""]
    lines += ["| Variant | Score | Checks | Flags | Diff | Runs | Tokens |", "|---|---:|---|---|---|---:|---:|"]
    for v in arena.variants.values():
        checks = ", ".join(f"{r.name}:{r.status}" for r in v.checks.results) if v.checks else "—"
        flags = ", ".join(sorted({f"{g.kind}[{g.severity[0]}]" for g in v.gates})) or "—"
        size = f"{len(v.snapshot.files)} files / {v.snapshot.lines_changed} lines" if v.snapshot else "—"
        tokens = sum(r.tokens.total_tokens or 0 for r in v.runs) or ""
        score = d.scores.get(v.name, "") if d else ""
        lines.append(f"| {v.name} | {score} | {checks} | {flags} | {size} | {len(v.runs)} | {tokens} |")
    names = [n for n, v in arena.variants.items() if v.snapshot]
    if len(names) > 1:
        lines += ["", "## Pairs", "", "| Pair | Result | File overlap | Reasons |", "|---|---|---:|---|"]
        for a, b in combinations(names, 2):
            va, vb = arena.variants[a], arena.variants[b]
            matches = pair_matches(arena, va, vb)
            if not matches:
                result, reasons = "not judged", ""
            else:
                result = pair_winner(matches) or "tie"
                reasons = " / ".join(
                    f"{'A' if m.first == a else 'B'}={a}: {m.verdict.winner} ({m.verdict.confidence:.2f})"
                    for m in matches
                )
            lines.append(f"| {a} vs {b} | {result} | {_diff_overlap(va, vb):.0%} | {reasons} |")
    if d and d.rationale:
        lines += ["", "## Rationale", ""] + [f"- {r}" for r in d.rationale]
    return "\n".join(lines) + "\n"


def pr_summary(arena: Arena, variant: Variant, report_path: Path) -> str:
    snap = variant.snapshot
    files = "\n".join(f"- `{f.path}` ({f.status}, +{f.added}/-{f.removed})" for f in snap.files) if snap else ""
    reasons = [r for m in arena.matches.values() if m.winner == variant.name for r in m.verdict.reasons][:5]
    why = "\n".join(f"- {r}" for r in reasons) or "- See the arena report."
    return f"""# {arena.task}

Selected by Agents Arena from {len(arena.variants)} variants (strategy: `{variant.name}`).

## Changes

{files}

## Why this variant

{why}

Full report: `{report_path}`
"""


def ledger_record(arena: Arena, config: Config, promoted: bool) -> dict[str, Any]:
    d = arena.decision
    return {
        "arena_id": arena.id,
        "task": arena.task,
        "judge": f"{config.judge.runner}:{config.judge.model or 'default'}",
        "strategies": {
            v.name: {
                "runner": v.runs[-1].runner if v.runs else None,
                "model": v.runs[-1].model if v.runs else None,
                "gates": [g.kind for g in v.gates],
                "checks_passed": v.checks.passed if v.checks else None,
                "score": d.scores.get(v.name) if d else None,
            }
            for v in arena.variants.values()
        },
        "matches": [
            {"first": m.first, "second": m.second, "winner": m.verdict.winner, "confidence": m.verdict.confidence}
            for m in arena.matches.values()
        ],
        "decision": d.model_dump() if d else None,
        "promoted": promoted,
    }
