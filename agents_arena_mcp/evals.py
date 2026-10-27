"""`agents-arena eval-judge`: run each seeded case as a real two-contestant arena and score the judge's final.

Reports accuracy vs. the expected winner, the order-flip rate (the verdict changed when A/B were swapped),
the tie rate, and latency. The case files' contestants are 'command' runs that write the case's files.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import tomllib
from importlib import resources
from pathlib import Path
from typing import Any

from agents_arena_mcp import harness as harnesses
from agents_arena_mcp import pipeline
from agents_arena_mcp.errors import ArenaError
from agents_arena_mcp.judge import judge_order, pair_winner
from agents_arena_mcp.models import JudgeSpec, Spec
from agents_arena_mcp.store import Store, utc_now

WRITER = ("import json,os,sys\nw=json.loads(sys.argv[1])\nfor p,t in w.get('write',{}).items():\n"
          "    os.makedirs(os.path.dirname(p) or '.',exist_ok=True); open(p,'w').write(t)\n"
          "for p in w.get('delete',[]): os.remove(p)\n")  # fmt: skip


def cases() -> list[dict[str, Any]]:
    folder = resources.files("agents_arena_mcp.data").joinpath("judge_cases")
    return [tomllib.loads(f.read_text(encoding="utf-8")) | {"name": f.name[:-5]}
            for f in sorted(folder.iterdir(), key=lambda f: f.name) if f.name.endswith(".toml")]  # fmt: skip


def _run_case(case: dict[str, Any], judge: dict[str, Any]) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="arena-eval-") as tmp:
        repo = Path(tmp) / "repo"
        repo.mkdir()
        for rel, content in case["base"].items():
            (repo / rel).parent.mkdir(parents=True, exist_ok=True)
            (repo / rel).write_text(content, encoding="utf-8")
        ident = {
            "GIT_AUTHOR_NAME": "e",
            "GIT_AUTHOR_EMAIL": "e@x",
            "GIT_COMMITTER_NAME": "e",
            "GIT_COMMITTER_EMAIL": "e@x",
        }
        for args in (["init", "-q"], ["add", "-A"], ["commit", "-qm", "base"]):
            subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, env={**os.environ, **ident})
        contestants = [{"name": side, "harness": "command", "argv": [sys.executable, "-c", WRITER, json.dumps(
            {"write": case.get(side, {}), "delete": case.get(f"delete_{side}", [])})]} for side in ("a", "b")]  # fmt: skip
        # Run the contestants without judging, then judge the pair directly: when measuring the judge,
        # gated runs (e.g. the test-deleting cheat) must still be judged.
        spec = Spec.model_validate({"task": case["task"], "judge": {"harness": "none"}, "contestants": contestants})
        store = Store(repo)
        arena = pipeline.create(store, spec)
        pipeline.execute(store, arena.id, progress=lambda m: None)
        done = store.load(arena.id)
        done = done.model_copy(update={"spec": done.spec.model_copy(update={"judge": JudgeSpec.model_validate(judge)})})
        a_run, b_run = done.runs["a-1"], done.runs["b-1"]
        if a_run.snapshot is None or b_run.snapshot is None:
            return {"case": case["name"], "error": a_run.error or b_run.error or "a run produced no snapshot",
                    "expected": [], "combined": "error", "correct": False, "orders": [], "flipped": False,
                    "labels": [], "reasons": [], "latency_ms": 0}  # fmt: skip
        started = time.monotonic()
        finals = [judge_order(store, done, a_run, b_run), judge_order(store, done, b_run, a_run)]
        done = done.model_copy(update={"finals": finals})
    expected = case["expected"] if isinstance(case["expected"], list) else [case["expected"]]
    winner = pair_winner(done.finals)
    combined = winner.split("-")[0] if winner else "tie"
    orders = [m.winner.split("-")[0] if m.winner else "tie" for m in done.finals]
    return {"case": case["name"], "expected": expected, "combined": combined, "correct": combined in expected,
            "orders": orders, "flipped": len(set(orders)) > 1, "labels": [m.verdict.winner for m in done.finals],
            "reasons": [m.verdict.reasons[:3] for m in done.finals], "latency_ms": int((time.monotonic() - started) * 1000)}  # fmt: skip


def eval_judge(harness: str, model: str, argv: list[str] | None = None) -> dict[str, Any]:
    judge = {"harness": harness, "model": model, "argv": argv or []}
    problems = harnesses.get(harness).judge_preflight(JudgeSpec.model_validate(judge))
    if problems:
        raise ArenaError("Judge preflight failed:\n- " + "\n- ".join(problems))
    results = [_run_case(c, judge) for c in cases()]
    n, labels = len(results) or 1, [label for r in results for label in r["labels"]]
    metrics = {"judge": f"{harness}:{model or 'default'}", "cases": len(results),
               "accuracy": round(sum(r["correct"] for r in results) / n, 3),
               "order_flip_rate": round(sum(r["flipped"] for r in results) / n, 3),
               "tie_rate": round(sum(r["combined"] == "tie" for r in results) / n, 3),
               "picked_label_A_rate": round(labels.count("A") / (len(labels) or 1), 3),
               "mean_latency_ms": int(sum(r["latency_ms"] for r in results) / n)}  # fmt: skip
    out_dir = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "agents-arena" / "evals"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"judge-{utc_now().replace(':', '')}.json"
    path.write_text(json.dumps({"metrics": metrics, "results": results}, indent=2), encoding="utf-8")
    return {"metrics": metrics, "results_path": str(path), "failures": [r for r in results if not r["correct"]]}
