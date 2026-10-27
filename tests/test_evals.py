import sys

from conftest import FAKE_JUDGE

from agents_arena_mcp import evals


def test_position_biased_judge_is_caught(repo, tmp_path, monkeypatch):
    judge = tmp_path / "j.py"
    judge.write_text(FAKE_JUDGE)
    monkeypatch.setenv("FAKE_JUDGE_MODE", "always_a")
    out = evals.eval_judge("command", "", argv=[sys.executable, str(judge), "{prompt_file}", "{output_file}"])
    m = out["metrics"]
    assert m["order_flip_rate"] == 1.0 and m["tie_rate"] == 1.0 and m["cases"] == 8
