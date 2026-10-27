import pytest
from pydantic import ValidationError

from agents_arena_mcp.models import Contestant, FileChange, Gate, Overlay, Run, Snapshot, Spec


def spec(**kw):
    base = {"task": "t", "contestants": [{"name": "a", "harness": "claude"}]}
    return Spec.model_validate(base | kw)


def test_overlay_targets_must_be_scoped():
    assert Overlay.model_validate({"from": "/x", "to": "repo:.claude/skills/foo"}).rel == ".claude/skills/foo"
    for bad in ("skills/foo", "repo:", "home:../escape"):
        with pytest.raises(ValidationError):
            Overlay.model_validate({"from": "/x", "to": bad})


def test_home_overlays_require_clean_baseline():
    with pytest.raises(ValidationError, match="home: overlays need baseline='clean'"):
        Contestant.model_validate(
            {
                "name": "a",
                "harness": "codex",
                "baseline": "real",
                "overlays": [{"from": "/x", "to": "home:.codex/skills/s"}],
            }
        )


def test_command_harness_requires_argv_and_names_are_slugs():
    with pytest.raises(ValidationError):
        Contestant(name="a", harness="command")
    with pytest.raises(ValidationError):
        Contestant(name="Bad Name", harness="claude")


def test_spec_rules():
    with pytest.raises(ValidationError, match="unique"):
        spec(contestants=[{"name": "a", "harness": "claude"}, {"name": "a", "harness": "codex"}])
    with pytest.raises(ValidationError):
        spec(contestants=[{"name": f"c{i}", "harness": "claude"} for i in range(7)])
    assert spec(objective="tokens").judged is False
    assert spec(objective="elegance").judged is True
    assert spec(judge={"harness": "none"}).judged is False


def test_run_eligibility():
    snap = Snapshot(commit="c", patch_hash="h", patch_path="/p", files=[FileChange(path="a.py", status="M", added=1)])
    ok = Run(id="a-1", contestant="a", repeat=1, state="done", snapshot=snap)
    assert ok.eligible
    assert not ok.model_copy(update={"gates": [Gate(kind="test_deleted", severity="disqualify")]}).eligible
    assert not ok.model_copy(update={"snapshot": snap.model_copy(update={"files": []})}).eligible
    assert not ok.model_copy(update={"state": "failed"}).eligible


def test_unknown_spec_fields_are_rejected():
    with pytest.raises(ValidationError):
        Spec.model_validate({"task": "t", "repeat": 3, "contestants": [{"name": "a", "harness": "claude"}]})
    with pytest.raises(ValidationError):
        Spec.model_validate({"task": "t", "contestants": [{"name": "a", "harness": "claude", "modle": "x"}]})


def test_check_names_must_be_unique():
    checks = [{"name": "tests", "cmd": "a"}, {"name": "tests", "cmd": "b"}]
    with pytest.raises(ValidationError, match="check names must be unique"):
        spec(checks=checks)


def test_names_cannot_contain_double_dots():
    with pytest.raises(ValidationError):
        Contestant(name="a..b", harness="claude")
    assert Contestant(name="a.b", harness="claude").name == "a.b"
