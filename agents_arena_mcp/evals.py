"""`agents-arena eval-judge`: score the configured judge on seeded pairs with known answers.

Each case builds a throwaway repo, opens a real two-variant arena and judges it in both orders through the
same code path as arena_judge. Reported: accuracy against the expected winner, order-flip rate (the verdict
changed when A/B were swapped), tie rate, how often the judge picked the label "A", and latency.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
import tomllib
from importlib import resources
from pathlib import Path
from typing import Any

from agents_arena_mcp.arena import arena_check, arena_close, arena_open, context
from agents_arena_mcp.judge import judge_order
from agents_arena_mcp.select import pair_winner
from agents_arena_mcp.store import utc_now


def load_cases(directory: str) -> list[dict[str, Any]]:
    if directory:
        paths = sorted(Path(directory).glob("*.toml"))
        return [tomllib.loads(p.read_text(encoding="utf-8")) | {"name": p.stem} for p in paths]
    bundled = resources.files("agents_arena_mcp.data").joinpath("judge_cases")
    return [
        tomllib.loads(f.read_text(encoding="utf-8")) | {"name": f.name.removesuffix(".toml")}
        for f in sorted(bundled.iterdir(), key=lambda f: f.name)
        if f.name.endswith(".toml")
    ]


def _write(root: Path, files: dict[str, str]) -> None:
    for rel, content in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def run_case(case: dict[str, Any], config) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="arena-eval-") as tmp:
        repo = Path(tmp) / "repo"
        repo.mkdir()
        env = {
            "GIT_AUTHOR_NAME": "eval",
            "GIT_AUTHOR_EMAIL": "e@x",
            "GIT_COMMITTER_NAME": "eval",
            "GIT_COMMITTER_EMAIL": "e@x",
        }
        _write(repo, case["base"])
        for args in (["init", "-q"], ["add", "-A"], ["commit", "-qm", "base"]):
            subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, env={**os.environ, **env})
        previous = os.environ.get("AGENTS_ARENA_ROOT")
        os.environ["AGENTS_ARENA_ROOT"] = str(repo)
        try:
            opened = arena_open(case["task"], variants=["a", "b"])
            for side in ("a", "b"):
                workspace = Path(opened["variants"][side]["workspace"])
                _write(workspace, case.get(side, {}))
                for rel in case.get(f"delete_{side}", []):
                    (workspace / rel).unlink()
            arena_check()
            store, _ = context()
            arena = store.load()
            va, vb = arena.variants["a"], arena.variants["b"]
            started = time.monotonic()
            matches = [judge_order(store, arena, config, va, vb), judge_order(store, arena, config, vb, va)]
            latency_ms = int((time.monotonic() - started) * 1000)
            arena_close()
        finally:
            if previous is None:
                os.environ.pop("AGENTS_ARENA_ROOT", None)
            else:
                os.environ["AGENTS_ARENA_ROOT"] = previous
    expected = case["expected"] if isinstance(case["expected"], list) else [case["expected"]]
    combined = pair_winner(matches) or "tie"
    return {
        "case": case["name"],
        "expected": expected,
        "combined": combined,
        "correct": combined in expected,
        "orders": [m.winner or "tie" for m in matches],
        "flipped": matches[0].winner != matches[1].winner,
        "labels": [m.verdict.winner for m in matches],
        "reasons": [m.verdict.reasons[:3] for m in matches],
        "latency_ms": latency_ms,
        "errors": [m.verdict.reasons[0] for m in matches if m.verdict.confidence == 0.0 and m.verdict.reasons],
    }


def eval_judge(cases: str = "", judge: str | None = None, model: str | None = None, out: str = "") -> dict[str, Any]:
    store, config = context()  # judge config comes from the repo you run this in
    store.init()
    if judge is not None:
        config.judge.runner = judge
    if model is not None:
        config.judge.model = model
    results = [run_case(case, config) for case in load_cases(cases)]
    n = len(results) or 1
    labels = [label for r in results for label in r["labels"]]
    metrics = {
        "judge": f"{config.judge.runner}:{config.judge.model or 'default'}",
        "cases": len(results),
        "accuracy": round(sum(r["correct"] for r in results) / n, 3),
        "order_flip_rate": round(sum(r["flipped"] for r in results) / n, 3),
        "tie_rate": round(sum(r["combined"] == "tie" for r in results) / n, 3),
        "picked_label_A_rate": round(labels.count("A") / (len(labels) or 1), 3),
        "mean_latency_ms": int(sum(r["latency_ms"] for r in results) / n),
    }
    out_dir = Path(out) if out else store.root / "evals"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"judge-{utc_now().replace(':', '')}.json"
    path.write_text(json.dumps({"metrics": metrics, "results": results}, indent=2), encoding="utf-8")
    return {"metrics": metrics, "results_path": str(path), "failures": [r for r in results if not r["correct"]]}
