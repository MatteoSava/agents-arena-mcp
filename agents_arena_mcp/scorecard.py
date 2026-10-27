"""Scorecard: per-contestant medians, the winner for the arena's objective, markdown/HTML, history record."""

from __future__ import annotations

import html
import statistics
from collections import Counter

from agents_arena_mcp.judge import best_run, pair_winner
from agents_arena_mcp.models import METRIC_OBJECTIVES, Arena, ContestantStats, Scorecard

# Validated categorical palette (dataviz reference, light surface; contrast WARN -> values are always labeled).
PALETTE = ("#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300")
METRIC_FIELD = {"speed": "median_wall_ms", "tokens": "median_tokens", "cost": "median_cost_usd"}


def _median(values: list[float | int | None]) -> float | None:
    present = [v for v in values if v is not None]
    return statistics.median(present) if present else None


def stats_for(arena: Arena, name: str) -> ContestantStats:
    runs = [r for r in arena.runs.values() if r.contestant == name]
    ok = [r for r in runs if r.eligible]
    return ContestantStats(
        name=name, runs=len(runs), eligible=len(ok), pass_rate=round(len(ok) / len(runs), 3) if runs else 0.0,
        median_score=_median([r.score.score if r.score else None for r in ok]),
        median_tokens=_median([r.metrics.total_tokens for r in ok]),
        median_wall_ms=_median([r.metrics.wall_ms for r in ok]),
        median_cost_usd=_median([r.metrics.cost_usd for r in ok]),
        median_lines=_median([r.snapshot.lines_changed if r.snapshot else None for r in ok]),
        gate_hits=dict(Counter(g.kind for r in runs for g in r.gates if g.severity != "info")),
    )  # fmt: skip


def build(arena: Arena) -> Scorecard:
    spec = arena.spec
    stats = [stats_for(arena, c.name) for c in spec.contestants]
    notes = [f"{r.id}: {r.error}" for r in arena.runs.values() if r.error]
    if any(s.median_cost_usd is None and s.eligible for s in stats):
        notes.append("cost is only shown for harnesses that report it (codex reports tokens, not dollars)")
    alive = [s for s in stats if s.eligible]
    if not alive:
        return Scorecard(
            objective=spec.objective, stats=stats, verdict="no contestant produced an eligible run", notes=notes
        )
    if spec.objective in METRIC_OBJECTIVES:
        field = METRIC_FIELD[spec.objective]
        ranked = sorted(alive, key=lambda s: (getattr(s, field) is None, getattr(s, field) or 0, -s.pass_rate))
        best = ranked[0]
        if getattr(best, field) is None:
            return Scorecard(
                objective=spec.objective, stats=stats, verdict=f"no {spec.objective} data reported", notes=notes
            )
        verdict = f"{best.name} is best on {spec.objective}: median {getattr(best, field):g}"
        if len(ranked) > 1 and getattr(ranked[1], field) is not None:
            verdict += f" vs {getattr(ranked[1], field):g} for {ranked[1].name}"
        run = _best_metric_run(arena, best.name, spec.objective)
        return Scorecard(objective=spec.objective, stats=stats, winner=best.name, winner_run=run,
                         verdict=verdict, notes=notes)  # fmt: skip
    return _judged_winner(arena, stats, alive, notes)


def _best_metric_run(arena: Arena, name: str, objective: str) -> str | None:
    """The eligible run of `name` with the best (lowest) value of the objective's metric."""
    value = {"speed": lambda r: r.metrics.wall_ms, "tokens": lambda r: r.metrics.total_tokens,
             "cost": lambda r: r.metrics.cost_usd}[objective]  # fmt: skip
    pool = [r for r in arena.runs.values() if r.contestant == name and r.eligible and value(r) is not None]
    return min(pool, key=value).id if pool else None  # type: ignore[arg-type]


def _judged_winner(
    arena: Arena, stats: list[ContestantStats], alive: list[ContestantStats], notes: list[str]
) -> Scorecard:
    spec = arena.spec
    wins = Counter[str]()
    by_run = {r.id: r.contestant for r in arena.runs.values()}
    finals_by_pair: dict[frozenset[str], list] = {}
    for m in arena.finals:
        finals_by_pair.setdefault(frozenset((m.first, m.second)), []).append(m)
    for pair in finals_by_pair.values():
        if (w := pair_winner(pair)) is not None:
            wins[by_run[w]] += 1
    ranked = sorted(
        alive, key=lambda s: (-wins[s.name], -(s.median_score if s.median_score is not None else -1), -s.pass_rate)
    )
    best = ranked[0]
    second = ranked[1] if len(ranked) > 1 else None
    if second and (wins[best.name], best.median_score, best.pass_rate) == (
        wins[second.name],
        second.median_score,
        second.pass_rate,
    ):
        return Scorecard(
            objective=spec.objective,
            stats=stats,
            verdict=f"tie between {best.name} and {second.name}: your call",
            notes=notes,
        )
    label = spec.objective if spec.objective in ("quality", "elegance") else "rubric"
    if second is None or wins[best.name] > wins[second.name]:
        decided = "won the final in both orders" if wins[best.name] else "only eligible contestant"
    elif best.median_score is not None:
        decided = f"highest median {label} score"
    else:
        decided = "highest eligible rate"
    run = best_run(arena, best.name)
    return Scorecard(objective=spec.objective, stats=stats, winner=best.name, winner_run=run.id if run else None,
                     verdict=f"{best.name} {decided}", notes=notes)  # fmt: skip


def _fmt(value: float | None, kind: str) -> str:
    if value is None:
        return "—"
    return {"score": f"{value:.1f}", "tokens": f"{value / 1000:.1f}k", "ms": f"{value / 1000:.0f}s", "usd": f"${value:.3f}",
            "lines": f"{value:g}", "rate": f"{value:.0%}"}[kind]  # fmt: skip


COLUMNS = (("eligible", "pass_rate", "rate"), ("score", "median_score", "score"), ("tokens", "median_tokens", "tokens"),
           ("time", "median_wall_ms", "ms"), ("cost", "median_cost_usd", "usd"), ("diff lines", "median_lines", "lines"))  # fmt: skip


def render_markdown(arena: Arena) -> str:
    card = arena.scorecard
    assert card is not None
    lines = [f"# Arena {arena.id}", "", f"**Task:** {arena.spec.task}", f"**Objective:** {card.objective} · "
             f"**Repeats:** {arena.spec.repeats}", "", f"**Verdict:** {card.verdict}", "",
             "| contestant | runs | " + " | ".join(c[0] for c in COLUMNS) + " | flags |",
             "|---|---:|" + "---:|" * len(COLUMNS) + "---|"]  # fmt: skip
    for s in card.stats:
        cells = " | ".join(_fmt(getattr(s, field), kind) for _, field, kind in COLUMNS)
        flags = ", ".join(f"{k}×{v}" for k, v in s.gate_hits.items()) or "—"
        lines.append(f"| {s.name} | {s.runs} | {cells} | {flags} |")
    lines += [""] + [f"- {n}" for n in card.notes]
    return "\n".join(lines) + "\n"


def _bar_row(name: str, value: float | None, top: float, kind: str, color: str) -> str:
    bar = ""
    if value is not None:
        bar = (f'<span class="bar" style="width:{value / top * 100:.1f}%;background:{color}" '
               f'title="{html.escape(name)}: {_fmt(value, kind)}"></span>')  # fmt: skip
    return (f'<div class="row"><span class="lab">{html.escape(name)}</span><span class="track">{bar}</span>'
            f'<span class="val">{_fmt(value, kind)}</span></div>')  # fmt: skip


def render_html(arena: Arena) -> str:
    """One self-contained page: verdict, labeled bar small-multiples (one per metric), and the table."""
    card = arena.scorecard
    assert card is not None
    color = {s.name: PALETTE[i % len(PALETTE)] for i, s in enumerate(card.stats)}
    charts = []
    for title, field, kind in COLUMNS:
        values = [(s.name, getattr(s, field)) for s in card.stats]
        top = max((v for _, v in values if v is not None), default=0) or 1
        bars = "".join(_bar_row(n, v, top, kind, color[n]) for n, v in values)
        charts.append(f'<div class="mini"><h3>{title}</h3>{bars}</div>')
    legend = "".join(
        f'<span><i style="background:{color[s.name]}"></i>{html.escape(s.name)}</span>' for s in card.stats
    )
    head = (
        "<tr><td>contestant</td><td>runs</td>" + "".join(f"<td>{t}</td>" for t, _, _ in COLUMNS) + "<td>flags</td></tr>"
    )
    rows = head + "".join(
        f"<tr><td>{html.escape(s.name)}</td><td>{s.runs}</td>"
        + "".join(f"<td>{_fmt(getattr(s, f), k)}</td>" for _, f, k in COLUMNS)
        + f"<td>{html.escape(', '.join(f'{k}x{v}' for k, v in s.gate_hits.items()) or '-')}</td></tr>"
        for s in card.stats
    )
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Arena {html.escape(arena.id)}</title>
<style>body{{font:15px/1.5 system-ui,sans-serif;color:#0b0b0b;background:#fcfcfb;max-width:1000px;margin:40px auto;padding:0 20px}}
h1{{font-size:22px}}.verdict{{background:#0b0b0b;color:#fcfcfb;padding:16px 20px;border-radius:6px;font-size:18px}}
.legend{{display:flex;gap:16px;margin:16px 0;color:#52514e}}.legend i{{display:inline-block;width:12px;height:12px;border-radius:3px;margin-right:6px}}
.grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}}.mini{{border:1px solid #e4e2dc;border-radius:6px;padding:10px 12px}}
.mini h3{{margin:0 0 8px;font-size:13px;color:#52514e;font-weight:600}}.row{{display:flex;align-items:center;gap:8px;margin:4px 0}}
.track{{flex:1;min-width:0}}.lab{{flex-shrink:0;width:90px;font-size:12px;color:#52514e;overflow:hidden;text-overflow:ellipsis}}.bar{{height:14px;border-radius:0 4px 4px 0;min-width:2px}}
.val{{flex-shrink:0;min-width:48px;font-size:12px;font-weight:600}}table{{border-collapse:collapse;width:100%;margin-top:20px;font-size:13px}}
td{{border-bottom:1px solid #e4e2dc;padding:6px 8px}}tr:first-child td{{font-weight:600}}</style></head><body>
<h1>Arena {html.escape(arena.id)}</h1><p>{html.escape(arena.spec.task)}<br>objective: {html.escape(card.objective)} · repeats: {arena.spec.repeats}</p>
<div class="verdict">{html.escape(card.verdict)}</div><div class="legend">{legend}</div><div class="grid">{"".join(charts)}</div>
<table>{rows}</table>{"".join(f"<p>· {html.escape(n)}</p>" for n in card.notes)}</body></html>"""


def history_record(arena: Arena) -> dict:
    card = arena.scorecard
    assert card is not None
    return {"arena_id": arena.id, "task": arena.spec.task, "objective": card.objective, "winner": card.winner,
            "verdict": card.verdict, "contestants": [c.model_dump(mode="json", by_alias=True) for c in arena.spec.contestants],
            "stats": [s.model_dump(mode="json") for s in card.stats]}  # fmt: skip
