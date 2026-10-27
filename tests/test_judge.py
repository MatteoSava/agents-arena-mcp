import json

import pytest
from conftest import command_contestant, command_judge

from agents_arena_mcp import judge, pipeline
from agents_arena_mcp.models import Spec
from agents_arena_mcp.store import Store


def run_arena(repo, fakes, monkeypatch, plans, **kw):
    monkeypatch.setenv("FAKE_PLAN", json.dumps(plans))
    data = {"task": "t", "objective": "quality", "repeats": 1, "judge": command_judge(fakes),
            "contestants": [command_contestant(fakes, n) for n in plans]}  # fmt: skip
    store = Store(repo)
    arena = pipeline.create(store, Spec.model_validate(data | kw))
    pipeline.run_one(store, arena.id, "x-1")
    pipeline.run_one(store, arena.id, "y-1")
    return store, arena.id


def test_rubric_scores_each_eligible_run_blind(repo, fakes, monkeypatch):
    store, aid = run_arena(
        repo, fakes, monkeypatch, {"x": {"write": {"a.py": "# GOOD\n"}}, "y": {"write": {"a.py": "# meh\n"}}}
    )
    judge.score_runs(store, aid, progress=lambda m: None)
    runs = store.load(aid).runs
    assert runs["x-1"].score.score == 9 and runs["y-1"].score.score == 5
    prompt = (store.arena_dir(aid) / "judge" / "rubric-x-1" / "prompt.md").read_text()
    assert "x-1" not in prompt and "command" not in prompt


def test_final_judges_best_runs_in_both_orders(repo, fakes, monkeypatch):
    store, aid = run_arena(
        repo, fakes, monkeypatch, {"x": {"write": {"a.py": "# GOOD\n"}}, "y": {"write": {"a.py": "# meh\n"}}}
    )
    judge.score_runs(store, aid, progress=lambda m: None)
    judge.run_finals(store, aid, progress=lambda m: None)
    finals = store.load(aid).finals
    assert {(m.first, m.second) for m in finals} == {("x-1", "y-1"), ("y-1", "x-1")}
    assert judge.pair_winner(finals) == "x-1"


def test_position_bias_is_a_tie(repo, fakes, monkeypatch):
    monkeypatch.setenv("FAKE_JUDGE_MODE", "always_a")
    store, aid = run_arena(repo, fakes, monkeypatch, {"x": {"write": {"a.py": "1\n"}}, "y": {"write": {"a.py": "2\n"}}})
    judge.run_finals(store, aid, progress=lambda m: None)
    assert judge.pair_winner(store.load(aid).finals) is None


def test_unusable_judge_output_is_recorded(repo, fakes, monkeypatch):
    monkeypatch.setenv("FAKE_JUDGE_MODE", "garbage")
    store, aid = run_arena(repo, fakes, monkeypatch, {"x": {"write": {"a.py": "1\n"}}, "y": {"write": {"a.py": "2\n"}}})
    judge.score_runs(store, aid, progress=lambda m: None)
    run = store.load(aid).runs["x-1"]
    assert run.score is None and "no usable JSON" in run.error


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ('{"winner": "A"}', "A"),
        ('```json\n{"winner": "B"}\n```', "B"),
        (json.dumps({"structured_output": {"winner": "tie"}}), "tie"),
    ],
)
def test_extract_json(text, expected):
    assert judge.extract_json(text, "winner")["winner"] == expected


def test_rubric_text_presets_and_custom():
    assert "architecture" in judge.rubric_text("elegance")
    assert judge.rubric_text("Prefer async/await over callbacks") == "Prefer async/await over callbacks"


def test_failed_final_judge_call_is_a_recorded_tie(repo, fakes, monkeypatch):
    store, aid = run_arena(repo, fakes, monkeypatch, {"x": {"write": {"a.py": "1\n"}}, "y": {"write": {"a.py": "2\n"}}})

    def boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(judge, "call", boom)
    judge.run_finals(store, aid, progress=lambda m: None)
    finals = store.load(aid).finals
    assert len(finals) == 2
    for m in finals:
        assert m.verdict.winner == "tie" and m.verdict.confidence == 0.0
        assert "final judge failed" in m.verdict.reasons[0]
