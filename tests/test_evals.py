"""The judge eval harness computes the right metrics (checked with a purely position-biased fake judge)."""

from __future__ import annotations

import json
from pathlib import Path

from conftest import write_config

from agents_arena_mcp.evals import eval_judge, load_cases


def test_bundled_cases_are_well_formed():
    cases = load_cases("")
    assert len(cases) >= 8
    for case in cases:
        assert {"task", "expected", "base"} <= set(case), case["name"]
        expected = case["expected"] if isinstance(case["expected"], list) else [case["expected"]]
        assert set(expected) <= {"a", "b", "tie"}, case["name"]
    assert {c["expected"] for c in cases if isinstance(c["expected"], str)} >= {"a", "b", "tie"}


def test_position_biased_judge_is_caught(repo: Path, fakes, monkeypatch, tmp_path):
    monkeypatch.setenv("FAKE_JUDGE_MODE", "always_a")
    write_config(repo, fakes, extra="[judge]\nrunner = 'fake'")

    out = eval_judge(out=str(tmp_path / "results"))

    m = out["metrics"]
    tie_cases = sum(
        1 for c in load_cases("") if "tie" in (c["expected"] if isinstance(c["expected"], list) else [c["expected"]])
    )
    assert m["order_flip_rate"] == 1.0
    assert m["tie_rate"] == 1.0
    assert m["picked_label_A_rate"] == 1.0
    assert m["accuracy"] == round(tie_cases / m["cases"], 3)
    saved = json.loads(Path(out["results_path"]).read_text())
    assert saved["metrics"] == m and len(saved["results"]) == m["cases"]
