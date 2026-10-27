"""Blind both-order judging, gates, baseline, and the Copeland decision."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from conftest import write_config

from agents_arena_mcp import arena as ops
from agents_arena_mcp.judge import extract_json
from agents_arena_mcp.models import Arena, Decision
from agents_arena_mcp.store import Store


def edit(opened: dict, name: str, files: dict[str, str], delete: tuple[str, ...] = ()) -> None:
    ws = Path(opened["variants"][name]["workspace"])
    for rel, content in files.items():
        (ws / rel).parent.mkdir(parents=True, exist_ok=True)
        (ws / rel).write_text(content)
    for rel in delete:
        (ws / rel).unlink()


def judged(repo: Path) -> tuple[Decision, Arena]:
    ops.arena_check()
    ops.arena_judge(wait=True)
    arena = Store(repo).load()
    assert arena.decision is not None
    return arena.decision, arena


def test_marker_judge_picks_the_good_variant_in_both_orders(repo: Path, fakes):
    write_config(repo, fakes, extra="[judge]\nrunner = 'fake'")
    opened = ops.arena_open("task", variants=["x", "y"])
    edit(opened, "x", {"app.py": "# GOOD\nX = 1\n"})
    edit(opened, "y", {"app.py": "Y = 1\n"})

    decision, arena = judged(repo)

    assert decision.status == "winner" and decision.winner == "x"
    assert decision.tie_break is None
    assert len(arena.matches) == 2  # one per order
    assert {(m.first, m.second) for m in arena.matches.values()} == {("x", "y"), ("y", "x")}


def test_position_biased_judge_produces_ties_not_a_winner(repo: Path, fakes, monkeypatch):
    monkeypatch.setenv("FAKE_JUDGE_MODE", "always_a")
    write_config(repo, fakes, extra="[judge]\nrunner = 'fake'")
    opened = ops.arena_open("task", variants=["x", "y", "z"])
    edit(opened, "x", {"app.py": "X = 1\n"})
    edit(opened, "y", {"app.py": "Y = 1\nY2 = 2\n"})
    edit(opened, "z", {"app.py": "Z = 1\nZ2 = 2\nZ3 = 3\n"})

    decision, _ = judged(repo)

    assert set(decision.scores.values()) == {0}  # every pair split -> no pair wins
    assert all("tie" in r for r in decision.rationale if " vs " in r)
    assert decision.winner == "x" and decision.tie_break == "smaller diff"


def test_identical_tie_goes_to_a_human(repo: Path, fakes, monkeypatch):
    monkeypatch.setenv("FAKE_JUDGE_MODE", "always_a")
    write_config(repo, fakes, extra="[judge]\nrunner = 'fake'")
    opened = ops.arena_open("task", variants=["x", "y"])
    edit(opened, "x", {"app.py": "A = 1\n"})
    edit(opened, "y", {"app.py": "B = 2\n"})

    decision, _ = judged(repo)

    assert decision.status == "needs_human"


def test_judge_prompt_is_anonymized(repo: Path, fakes):
    write_config(repo, fakes, extra="[judge]\nrunner = 'fake'")
    opened = ops.arena_open("task", variants=["minimal_patch", "test_first"])
    edit(opened, "minimal_patch", {"app.py": "A = 1\n"})
    edit(opened, "test_first", {"app.py": "B = 1\n"})

    _, arena = judged(repo)

    for match in arena.matches.values():
        prompt = (Path(match.run_dir) / "prompt.md").read_text()
        assert "minimal" not in prompt and "test_first" not in prompt and "test-first" not in prompt


def test_rejudging_is_idempotent(repo: Path, fakes):
    write_config(repo, fakes, extra="[judge]\nrunner = 'fake'")
    opened = ops.arena_open("task", variants=["x", "y"])
    edit(opened, "x", {"app.py": "X = 1\n"})
    edit(opened, "y", {"app.py": "Y = 1\n"})
    judged(repo)
    calls = len(list((Store(repo).arena_dir(opened["arena_id"]) / "judge").iterdir()))

    ops.arena_judge(wait=True)

    assert len(list((Store(repo).arena_dir(opened["arena_id"]) / "judge").iterdir())) == calls


def test_unusable_judge_output_becomes_a_recorded_tie(repo: Path, fakes, monkeypatch):
    monkeypatch.setenv("FAKE_JUDGE_MODE", "garbage")
    write_config(repo, fakes, extra="[judge]\nrunner = 'fake'")
    opened = ops.arena_open("task", variants=["x", "y"])
    edit(opened, "x", {"app.py": "X = 1\n"})
    edit(opened, "y", {"app.py": "Y = 1\nY = 2\n"})

    decision, arena = judged(repo)

    assert all(m.verdict.winner == "tie" and "no usable JSON" in m.verdict.reasons[0] for m in arena.matches.values())
    assert decision.winner == "x"  # deterministic tie-break still decides


def test_deleting_a_test_disqualifies(repo: Path):
    (repo / "tests").mkdir()
    (repo / "tests" / "test_app.py").write_text("def test_x():\n    assert True\n")
    import subprocess

    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "tests"], cwd=repo, check=True)
    opened = ops.arena_open("task", variants=["cheat", "honest"])
    edit(opened, "cheat", {"app.py": "X = 1\n"}, delete=("tests/test_app.py",))
    edit(opened, "honest", {"app.py": "X = 2\nY = 3\n"})

    decision, _ = judged(repo)

    assert decision.winner == "honest"
    assert any("cheat: disqualified (test_deleted" in r for r in decision.rationale)


def test_skip_marker_sends_winner_to_human(repo: Path):
    opened = ops.arena_open("task", variants=["x"])
    edit(opened, "x", {"tests/test_new.py": "import pytest\n\n@pytest.mark.skip\ndef test_a():\n    pass\n"})

    decision, _ = judged(repo)

    assert decision.status == "needs_human" and decision.winner == "x"


def test_failing_base_does_not_disqualify_everyone(repo: Path):
    write_config(repo, extra="checks = [{ name = 'always-fails', cmd = 'false' }]")
    opened = ops.arena_open("task", variants=["x", "y"])
    edit(opened, "x", {"app.py": "X = 1\n"})
    edit(opened, "y", {"app.py": "Y = 1\nY = 2\n"})

    decision, arena = judged(repo)

    assert arena.baseline is not None and arena.baseline.results[0].status == "failed"
    assert decision.status == "winner"
    assert all(g.kind == "check_failing_on_base_too" for v in arena.variants.values() for g in v.gates)


def test_regression_against_baseline_disqualifies(repo: Path):
    write_config(repo, extra="checks = [{ name = 'app-imports', cmd = 'python -c \"import app\"' }]")
    opened = ops.arena_open("task", variants=["broken", "fine"])
    edit(opened, "broken", {"app.py": "this is not python\n"})
    edit(opened, "fine", {"app.py": "def value():\n    return 2\n"})

    decision, _ = judged(repo)

    assert decision.winner == "fine"
    assert any("check_regression: app-imports" in r for r in decision.rationale)


def test_duplicate_patches_are_judged_once(repo: Path):
    opened = ops.arena_open("task", variants=["x", "y"])
    edit(opened, "x", {"app.py": "X = 1\n"})
    edit(opened, "y", {"app.py": "X  =  1\n"})  # whitespace-only difference

    decision, _ = judged(repo)

    assert decision.ranking == ["x"]
    assert any("y: duplicate of x" in r for r in decision.rationale)


def test_no_variant_passes_gates(repo: Path):
    ops.arena_open("task", variants=["x"])  # no changes at all

    decision, _ = judged(repo)

    assert decision.status == "no_viable"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ('{"winner": "A", "confidence": 1, "reasons": [], "risks": []}', "A"),
        ('```json\n{"winner": "B"}\n```', "B"),
        (json.dumps({"type": "result", "result": "x", "structured_output": {"winner": "tie"}}), "tie"),
        (json.dumps({"type": "result", "result": 'Sure: {"winner": "B", "reasons": []}'}), "B"),
        ('{"type":"text","part":{"text":"{\\"winner\\": \\"A\\"}"}}\n{"type":"step_finish"}', "A"),
    ],
)
def test_extract_json_handles_cli_output_shapes(text: str, expected: str):
    found = extract_json(text, "winner")
    assert found is not None and found["winner"] == expected


def test_judge_template_is_overridable(repo: Path, fakes):
    write_config(repo, fakes, extra="[judge]\nrunner = 'fake'\ntemplate = '.agents-arena/judge.tmpl'")
    (repo / ".agents-arena" / "judge.tmpl").write_text(
        "CUSTOM $task\n## Patch A\n$patch_a\n## Evidence for B\n$evidence_b\n## Patch B\n$patch_b\n"
    )
    opened = ops.arena_open("my task", variants=["x", "y"])
    edit(opened, "x", {"app.py": "X = 1\n"})
    edit(opened, "y", {"app.py": "Y = 1\n"})

    _, arena = judged(repo)

    prompt = (Path(next(iter(arena.matches.values())).run_dir) / "prompt.md").read_text()
    assert prompt.startswith("CUSTOM my task")


def test_same_family_judge_is_flagged(repo: Path, fakes):
    write_config(repo, fakes, extra="[judge]\nrunner = 'fake'", families=("shared", "shared"))
    ops.arena_open("task", variants=["x", "y"])
    ops.arena_run(wait=True)
    (Path(ops.arena_status()["variants"]["y"]["workspace"]) / "extra.py").write_text("E = 1\n")

    decision, _ = judged(repo)

    assert any("judge family 'shared' also generated x, y" in r for r in decision.rationale)
