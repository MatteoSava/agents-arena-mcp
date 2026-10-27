"""Blind judging: a rubric score per run, then a both-order final between contestants' best runs."""

from __future__ import annotations

import json
import shutil
import tempfile
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from itertools import combinations
from pathlib import Path
from string import Template

from pydantic import ValidationError

from agents_arena_mcp import harness, proc
from agents_arena_mcp.checks import failing_count
from agents_arena_mcp.config_data import data_text
from agents_arena_mcp.models import Arena, CheckReport, Match, Run, Score, Spec, Verdict
from agents_arena_mcp.store import Store

PATCH_LIMIT = 40_000
RUBRICS = {
    "quality": "Correctness first: does it solve the task without breaking behavior? Then regression tests "
    "as evidence, then low risk and a small blast radius. Weakening or skipping tests is a serious defect.",
    "elegance": "Assume correctness is required. Reward clean architecture and clear boundaries, readable and "
    "idiomatic code, small cohesive changes, and good naming. Penalize hacks, special cases, and needless "
    "complexity. Length is not quality.",
}


def rubric_text(objective: str) -> str:
    return RUBRICS.get(objective, objective)


def evidence(run: Run, base: CheckReport | None) -> str:
    """What a judge may know: checks vs baseline, flags, size. Nothing identifying the contestant."""
    lines = (
        [f"- Files changed: {len(run.snapshot.files)}, lines changed: {run.snapshot.lines_changed}"]
        if run.snapshot
        else []
    )
    for r in run.checks.results if run.checks else []:
        before = base.status_of(r.name) if base else None
        lines.append(f"- Check `{r.name}`: {r.status}" + (f" (on base: {before})" if before else ""))
    if not run.checks:
        lines.append("- Checks: none configured")
    lines += [f"- Flag {g.kind} ({g.severity}): {g.detail}" for g in run.gates if g.severity != "info"]
    return "\n".join(lines)


def patch_text(run: Run) -> str:
    assert run.snapshot is not None
    raw = Path(run.snapshot.patch_path).read_bytes().decode("utf-8", "replace")
    return raw if len(raw) <= PATCH_LIMIT else raw[:PATCH_LIMIT] + "\n…[truncated]\n"


def extract_json(text: str, key: str) -> dict | None:
    """The last JSON object carrying `key`: bare, fenced, inside claude's structured_output/result, or JSONL."""
    found: list[dict] = []

    def visit(value: object) -> None:
        if isinstance(value, dict):
            if key in value:
                found.append(value)
            for v in value.values():
                visit(v)
        elif isinstance(value, list):
            for v in value:
                visit(v)
        elif isinstance(value, str) and "{" in value and key in value:
            scan(value)

    def scan(blob: str) -> None:
        decoder = json.JSONDecoder()
        i = blob.find("{")
        while i != -1:
            try:
                obj, end = decoder.raw_decode(blob, i)
            except json.JSONDecodeError:
                i = blob.find("{", i + 1)
                continue
            visit(obj)
            i = blob.find("{", end)

    scan(text)
    return found[-1] if found else None


def call(spec: Spec, prompt: str, schema_name: str, key: str, run_dir: Path, owner: str) -> tuple[dict | None, str]:
    """Run the judge CLI in an empty temp dir outside the repo; return the parsed JSON object or an error message."""
    run_dir.mkdir(parents=True, exist_ok=True)
    schema = data_text(schema_name)
    with tempfile.TemporaryDirectory(prefix="arena-judge-") as tmp:
        work = Path(tmp)
        files = harness.JudgeFiles(prompt_file=str(work / "prompt.md"), output_file=str(work / "output.json"),
                                   schema_file=str(work / "schema.json"), schema_json=json.dumps(json.loads(schema)))  # fmt: skip
        Path(files.prompt_file).write_text(prompt, encoding="utf-8")
        Path(files.schema_file).write_text(schema, encoding="utf-8")
        argv = harness.get(spec.judge.harness).judge_argv(spec.judge, prompt, files)
        out = proc.run(argv, work, spec.judge.timeout_sec, owner=owner, log_dir=work)
        written = Path(files.output_file).read_text(encoding="utf-8") if Path(files.output_file).exists() else ""
        for name in ("prompt.md", "schema.json", "output.json", "stdout.log", "stderr.log"):
            if (work / name).exists():
                shutil.copyfile(work / name, run_dir / name)
    parsed = extract_json(written, key) or extract_json(out.stdout, key)
    return (parsed, "") if parsed else (None, f"judge returned no usable JSON ({out.status}); see {run_dir}")


def score_one(store: Store, arena: Arena, run: Run) -> tuple[Score | None, str]:
    try:
        return _score_one(store, arena, run)
    except Exception as exc:  # one failed judge call must not stop scoring the others
        return None, f"rubric judge failed: {type(exc).__name__}: {exc}"


def _score_one(store: Store, arena: Arena, run: Run) -> tuple[Score | None, str]:
    prompt = Template(data_text("rubric.md.tmpl")).safe_substitute(
        task=arena.spec.task, rubric=rubric_text(arena.spec.objective),
        evidence=evidence(run, arena.baseline), patch=patch_text(run))  # fmt: skip
    parsed, error = call(arena.spec, prompt, "rubric.schema.json", "score",
                         store.arena_dir(arena.id) / "judge" / f"rubric-{run.id}", arena.id)  # fmt: skip
    if parsed is None:
        return None, error
    try:
        return Score.model_validate(parsed), ""
    except ValidationError as exc:
        return None, f"rubric output failed validation: {exc.errors()[0]['msg']}"


def score_runs(store: Store, arena_id: str, progress: Callable[[str], None]) -> None:
    arena = store.load(arena_id)
    todo = [r for r in arena.runs.values() if r.eligible and r.score is None]
    with ThreadPoolExecutor(max_workers=arena.spec.max_parallel) as pool:
        for i, (run, (score, error)) in enumerate(
            zip(todo, pool.map(lambda r: score_one(store, arena, r), todo), strict=True), 1
        ):
            with store.mutate(arena_id) as a:
                a.runs[run.id].score = score
                if error:
                    a.runs[run.id].error = error
                elif a.runs[run.id].error.startswith(("judge returned", "rubric")):
                    a.runs[run.id].error = ""  # stale error from an earlier rubric attempt
            progress(f"{i}/{len(todo)} runs scored")


def best_run(arena: Arena, contestant: str) -> Run | None:
    pool = [r for r in arena.runs.values() if r.contestant == contestant and r.eligible]
    if not pool:
        return None
    lines = lambda r: r.snapshot.lines_changed if r.snapshot else 10**9  # noqa: E731
    return min(pool, key=lambda r: (-(r.score.score if r.score else -1), failing_count(r), lines(r)))


def judge_order(store: Store, arena: Arena, first: Run, second: Run) -> Match:
    try:
        return _judge_order(store, arena, first, second)
    except Exception as exc:  # one failed judge call must not abort the whole final round
        reason = f"final judge failed: {type(exc).__name__}: {exc}"
        return Match(
            first=first.id,
            second=second.id,
            verdict=Verdict(winner="tie", confidence=0.0, reasons=[reason]),
            run_dir=str(store.arena_dir(arena.id) / "judge" / f"final-{first.id}-vs-{second.id}"),
        )


def _judge_order(store: Store, arena: Arena, first: Run, second: Run) -> Match:
    prompt = Template(data_text("final.md.tmpl")).safe_substitute(
        task=arena.spec.task, evidence_a=evidence(first, arena.baseline), evidence_b=evidence(second, arena.baseline),
        patch_a=patch_text(first), patch_b=patch_text(second), extra="")  # fmt: skip
    run_dir = store.arena_dir(arena.id) / "judge" / f"final-{first.id}-vs-{second.id}"
    parsed, error = call(arena.spec, prompt, "judge.schema.json", "winner", run_dir, arena.id)
    try:
        verdict = Verdict.model_validate(parsed) if parsed else Verdict(winner="tie", confidence=0.0, reasons=[error])
    except ValidationError as exc:
        verdict = Verdict(
            winner="tie", confidence=0.0, reasons=[f"final output failed validation: {exc.errors()[0]['msg']}"]
        )
    return Match(first=first.id, second=second.id, verdict=verdict, run_dir=str(run_dir))


def run_finals(store: Store, arena_id: str, progress: Callable[[str], None]) -> None:
    arena = store.load(arena_id)
    bests = [b for c in arena.spec.contestants if (b := best_run(arena, c.name))]
    orders = [(x, y) for a, b in combinations(bests, 2) for x, y in ((a, b), (b, a))]
    with ThreadPoolExecutor(max_workers=arena.spec.max_parallel) as pool:
        matches = list(pool.map(lambda o: judge_order(store, arena, *o), orders))
    with store.mutate(arena_id) as a:
        a.finals = matches
    progress(f"final round: {len(matches)} judge calls")


def pair_winner(matches: list[Match]) -> str | None:
    """A run wins a pair only if it wins in every order; a split or tie is no signal."""
    winners = {m.winner for m in matches}
    return winners.pop() if len(matches) >= 2 and len(winners) == 1 else None
