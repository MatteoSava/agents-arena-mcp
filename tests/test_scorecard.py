import json

from conftest import command_contestant, command_judge, git

from agents_arena_mcp import pipeline, scorecard
from agents_arena_mcp.models import Spec
from agents_arena_mcp.store import Store


def arena_done(repo, fakes, monkeypatch, plans, **kw):
    monkeypatch.setenv("FAKE_PLAN", json.dumps(plans))
    data = {"task": "t", "repeats": 2, "judge": command_judge(fakes),
            "contestants": [command_contestant(fakes, n) for n in plans]}  # fmt: skip
    store = Store(repo)
    arena = pipeline.create(store, Spec.model_validate(data | kw))
    pipeline.execute(store, arena.id, progress=lambda m: None)
    return store, store.load(arena.id)


def test_quality_winner_from_final_and_medians(repo, fakes, monkeypatch):
    store, arena = arena_done(
        repo, fakes, monkeypatch, {"x": {"write": {"a.py": "# GOOD\n"}}, "y": {"write": {"a.py": "# meh\n"}}}
    )
    card = arena.scorecard
    assert card.winner == "x" and "both orders" in card.verdict
    x = next(s for s in card.stats if s.name == "x")
    assert (x.runs, x.eligible, x.pass_rate, x.median_score, x.median_tokens) == (2, 2, 1.0, 9, 120)
    assert (store.arena_dir(arena.id) / "result.json").exists() and (store.arena_dir(arena.id) / "report.md").exists()
    history = store.read_history()
    assert history[-1]["arena_id"] == arena.id and history[-1]["winner"] == "x"


def test_metric_objective_needs_no_judge(repo, fakes, monkeypatch):
    store, arena = arena_done(
        repo,
        fakes,
        monkeypatch,
        {"x": {"write": {"a.py": "1\n"}}, "y": {"write": {"a.py": "2\n"}}},
        objective="tokens",
        judge={"harness": "none"},
    )
    assert arena.finals == [] and all(r.score is None for r in arena.runs.values())
    assert arena.scorecard.winner in {"x", "y"} and "tokens" in arena.scorecard.verdict
    assert arena.scorecard.winner_run is not None  # metric winners can be promoted too


def test_no_eligible_runs(repo, fakes, monkeypatch):
    store, arena = arena_done(
        repo, fakes, monkeypatch, {"x": {"delete": ["tests/test_app.py"]}}, judge={"harness": "none"}
    )
    assert arena.scorecard.winner is None and "no contestant" in arena.scorecard.verdict


def test_html_report_is_self_contained(repo, fakes, monkeypatch):
    store, arena = arena_done(
        repo, fakes, monkeypatch, {"x": {"write": {"a.py": "# GOOD\n"}}, "y": {"write": {"a.py": "2\n"}}}
    )
    html = scorecard.render_html(arena)
    assert html.startswith("<!doctype html>") and "<table" in html and ">x<" in html
    assert "<link" not in html and "<script src" not in html  # self-contained


def test_promote_branch_and_apply(repo, fakes, monkeypatch):
    store, arena = arena_done(
        repo, fakes, monkeypatch, {"x": {"write": {"new.py": "# GOOD\n"}}, "y": {"write": {"a.py": "2\n"}}}
    )
    out = pipeline.promote(store, arena.id, "branch")
    assert git(repo, "show", f"{out['branch']}:new.py") == "# GOOD\n"
    assert git(repo, "rev-parse", "--abbrev-ref", "HEAD").strip() == "main"
    pipeline.promote(store, arena.id, "apply")
    assert (repo / "new.py").read_text() == "# GOOD\n"
