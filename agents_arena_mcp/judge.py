"""Blind pairwise judging. Every pair is judged in both orders; labels are A/B only, never variant names."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from string import Template

from pydantic import ValidationError

from agents_arena_mcp import proc, runners
from agents_arena_mcp import select as select_mod
from agents_arena_mcp.config import Config, data_text, template_text
from agents_arena_mcp.errors import ArenaError
from agents_arena_mcp.models import Arena, Match, Variant, Verdict
from agents_arena_mcp.store import Store

PATCH_LIMIT = 40_000


def evidence(arena: Arena, variant: Variant) -> str:
    """What the judge may know about a variant: checks vs baseline, gates, size. Nothing identifying."""
    snap = variant.snapshot
    lines = []
    if snap:
        lines.append(f"- Files changed: {len(snap.files)}, lines changed: {snap.lines_changed}")
    if variant.checks:
        for r in variant.checks.results:
            before = arena.baseline.status_of(r.name) if arena.baseline else None
            note = f" (on base: {before})" if before else ""
            lines.append(f"- Check `{r.name}`: {r.status}{note}")
    else:
        lines.append("- Checks: not run")
    for g in variant.gates:
        if g.severity != "info" or g.kind == "existing_test_edited":
            lines.append(f"- Flag {g.kind} ({g.severity}): {g.detail}")
    return "\n".join(lines)


def _patch_text(variant: Variant) -> str:
    assert variant.snapshot is not None
    raw = Path(variant.snapshot.patch_path).read_bytes().decode("utf-8", "replace")
    return raw if len(raw) <= PATCH_LIMIT else raw[:PATCH_LIMIT] + "\n…[truncated; full patch in the run directory]\n"


def extract_json(text: str, key: str) -> dict | None:
    """Find the JSON object carrying `key`, whether bare, fenced, inside claude's `structured_output`/`result`,
    or inside a string field of a JSONL event stream (opencode). Returns the last match."""
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


def call(
    config: Config,
    prompt: str,
    schema_name: str,
    run_dir: Path,
    owner: str,
    runner: str = "",
    extra_values: dict[str, str] | None = None,
) -> tuple[dict | None, str]:
    """Run the configured judge CLI in an empty directory and return the parsed JSON object (or None)."""
    name = runner or config.judge.runner
    spec = runners.lookup(config.judges, name, "judge")
    run_dir.mkdir(parents=True, exist_ok=True)
    schema = data_text(schema_name)
    schema_file = run_dir / "schema.json"
    schema_file.write_text(schema, encoding="utf-8")
    (run_dir / "prompt.md").write_text(prompt, encoding="utf-8")
    output_file = run_dir / "output.json"
    values = {
        "prompt": prompt,
        "prompt_file": str(run_dir / "prompt.md"),
        "run_dir": str(run_dir),
        "workspace": str(run_dir),
        "schema_file": str(schema_file),
        "schema_json": json.dumps(json.loads(schema)),
        "output_file": str(output_file),
        "model": config.judge.model,
        **(extra_values or {}),
    }
    result = proc.run(runners.build_argv(spec, values), run_dir, config.judge.timeout_sec, owner=owner, log_dir=run_dir)
    key = "winner" if schema_name == "judge.schema.json" else "command"
    out = output_file.read_text(encoding="utf-8") if output_file.exists() else ""
    parsed = extract_json(out, key) or extract_json(result.stdout, key)
    if parsed is None:
        return None, f"judge {name} returned no usable JSON ({result.status}); see {run_dir}"
    return parsed, ""


def judge_order(
    store: Store, arena: Arena, config: Config, first: Variant, second: Variant, extra: str = "", agentic: bool = False
) -> Match:
    assert first.snapshot and second.snapshot
    if agentic:
        tmpl = Template(data_text("judge_agentic.md.tmpl"))
    else:
        tmpl = Template(template_text(Path(arena.repo_root), config.judge.template, "judge.md.tmpl"))
    prompt = tmpl.safe_substitute(
        task=arena.task,
        evidence_a=evidence(arena, first),
        evidence_b=evidence(arena, second),
        patch_a=_patch_text(first),
        patch_b=_patch_text(second),
        workspace_a=first.workspace,
        workspace_b=second.workspace,
        extra=extra,
    )
    run_dir = store.arena_dir(arena.id) / "judge" / runners.new_run_id("match")
    (run_dir / "A.diff").parent.mkdir(parents=True, exist_ok=True)
    (run_dir / "A.diff").write_bytes(Path(first.snapshot.patch_path).read_bytes())
    (run_dir / "B.diff").write_bytes(Path(second.snapshot.patch_path).read_bytes())
    runner = config.judge.agentic_final if agentic else ""
    workspaces = {"workspace_a": first.workspace, "workspace_b": second.workspace}
    parsed, error = call(config, prompt, "judge.schema.json", run_dir, arena.id, runner, workspaces)
    try:
        verdict = Verdict.model_validate(parsed) if parsed else None
    except ValidationError as exc:
        verdict, error = None, f"judge output failed validation: {exc.errors()[0]['msg']} ({run_dir})"
    if verdict is None:
        # An unusable answer is no signal: record a tie so the run can finish and the report shows why.
        verdict = Verdict(winner="tie", confidence=0.0, reasons=[error])
    return Match(
        first=first.name,
        second=second.name,
        first_commit=first.snapshot.commit,
        second_commit=second.snapshot.commit,
        judge=f"{runner or config.judge.runner}:{config.judge.model or 'default'}",
        verdict=verdict,
        run_dir=str(run_dir),
        evidence=extra,
    )


def distinguish(store: Store, arena: Arena, config: Config, a: Variant, b: Variant) -> dict:
    """S*-style: ask for a command where the two differ and run it in both workspaces."""
    tmpl = Template(data_text("distinguish.md.tmpl"))
    prompt = tmpl.safe_substitute(task=arena.task, patch_a=_patch_text(a), patch_b=_patch_text(b))
    run_dir = store.arena_dir(arena.id) / "judge" / runners.new_run_id("distinguish")
    parsed, error = call(config, prompt, "distinguish.schema.json", run_dir, arena.id)
    if not parsed or not isinstance(parsed.get("command"), str):
        raise ArenaError(error or "distinguish step returned no command")
    outputs = {}
    for variant in (a, b):
        out = proc.shell(parsed["command"], Path(variant.workspace), 60, owner=arena.id)
        outputs[variant.name] = (
            f"({out.status}, exit {out.exit_code})\n```\n{proc.tail(out.stdout + out.stderr, 3000)}\n```"
        )
    return {"command": parsed["command"], "rationale": str(parsed.get("rationale", "")), "outputs": outputs}


def distinguish_section(test: dict, first: Variant, second: Variant) -> str:
    """Render the test evidence with labels matching this order (first = A)."""
    return (
        f"\n## Distinguishing test\n\nCommand: `{test['command']}`\nRationale: {test['rationale']}\n\n"
        f"Output in A {test['outputs'][first.name]}\n\nOutput in B {test['outputs'][second.name]}\n"
    )


def run_pairs(store: Store, arena_id: str, config: Config, names: list[str], progress) -> None:
    arena = store.load(arena_id)
    vs = arena.variants
    orders = [(vs[a], vs[b]) for a in names for b in names if a != b]
    todo = [(f, s) for f, s in orders if not already_judged(arena, f, s)]
    with ThreadPoolExecutor(max_workers=max(1, config.max_parallel)) as pool:
        for i, match in enumerate(pool.map(lambda o: judge_order(store, arena, config, *o), todo), 1):
            with store.mutate(arena_id) as a:
                a.matches[match.key] = match
            progress(f"{i}/{len(todo)} judge calls done")
    if not config.judge.distinguish:
        return
    arena = store.load(arena_id)
    for i, a_name in enumerate(names):
        for b_name in names[i + 1 :]:
            va, vb = arena.variants[a_name], arena.variants[b_name]
            pair = select_mod.pair_matches(arena, va, vb)
            if select_mod.pair_winner(pair) is not None or any(m.evidence for m in pair):
                continue
            test = distinguish(store, arena, config, va, vb)
            for first, second in ((va, vb), (vb, va)):
                match = judge_order(store, arena, config, first, second, distinguish_section(test, first, second))
                with store.mutate(arena_id) as a:
                    a.matches[match.key] = match
            progress(f"distinguishing test run for {a_name} vs {b_name}")


def already_judged(arena: Arena, first: Variant, second: Variant) -> bool:
    """Re-judging is idempotent: skip an order already judged at these exact snapshots."""
    assert first.snapshot and second.snapshot
    return any(
        m.first == first.name
        and m.second == second.name
        and m.first_commit == first.snapshot.commit
        and m.second_commit == second.snapshot.commit
        and not m.evidence
        for m in arena.matches.values()
    )


AGENTIC_NOTE = "\n(Final round: agentic review of both checkouts.)\n"


def agentic_round(store: Store, arena_id: str, config: Config, top_two: list[str]) -> None:
    """Opt-in final round: a tool-using judge inspects both checkouts read-only, in both orders."""
    arena = store.load(arena_id)
    a, b = (arena.variants[n] for n in top_two)
    if select_mod.pair_winner(select_mod.pair_matches(arena, a, b)) is not None:
        return
    for first, second in ((a, b), (b, a)):
        match = judge_order(store, arena, config, first, second, extra=AGENTIC_NOTE, agentic=True)
        with store.mutate(arena_id) as current:
            current.matches[match.key] = match
