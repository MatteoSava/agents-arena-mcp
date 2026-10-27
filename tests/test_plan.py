from agents_arena_mcp import plan
from agents_arena_mcp.models import Spec


def test_detects_python_uv_and_node_pnpm(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[tool.ruff]\nline-length = 100\n")
    (tmp_path / "uv.lock").write_text("")
    (tmp_path / "tests").mkdir()
    (tmp_path / "package.json").write_text('{"scripts": {"test": "vitest", "lint": "eslint ."}}')
    (tmp_path / "pnpm-lock.yaml").write_text("")
    cmds = {c.name: c.cmd for c in plan.detect_checks(tmp_path)}
    assert cmds["tests"] == "uv run pytest -q" and cmds["lint"] == "uv run ruff check ."
    assert cmds["js-test"] == "pnpm run test" and cmds["js-lint"] == "pnpm run lint"
    assert plan.detect_setup(tmp_path) == "pnpm install --frozen-lockfile"


def test_detects_go_rust_make(tmp_path):
    (tmp_path / "go.mod").write_text("module x\n")
    assert [c.cmd for c in plan.detect_checks(tmp_path)] == ["go test ./..."]
    (tmp_path / "go.mod").unlink()
    (tmp_path / "Makefile").write_text("build:\n\ttrue\ntest:\n\ttrue\n")
    assert [c.cmd for c in plan.detect_checks(tmp_path)] == ["make test"]


def test_setup_detection(tmp_path):
    assert plan.detect_setup(tmp_path) == ""
    (tmp_path / "package.json").write_text("{}")
    (tmp_path / "package-lock.json").write_text("{}")
    assert plan.detect_setup(tmp_path) == "npm ci"
    (tmp_path / "package-lock.json").unlink()
    (tmp_path / "yarn.lock").write_text("")
    assert plan.detect_setup(tmp_path) == "yarn install --frozen-lockfile"


def test_plan_modes_return_valid_draft(repo, monkeypatch):
    monkeypatch.setattr(plan.shutil, "which", lambda name: f"/bin/{name}" if name in ("claude", "codex") else None)
    auto = plan.make_plan(repo, "compare claude and codex on the retry bug", "autopilot")
    Spec.model_validate(auto["draft_spec"])
    assert {c["harness"] for c in auto["draft_spec"]["contestants"]} == {"claude", "codex"}
    assert "questions" not in auto and auto["next"].startswith("Adapt")
    assert any(line.startswith("judge:") for line in auto["rationale"])
    assert any(line.startswith("setup:") for line in auto["rationale"])
    interview = plan.make_plan(repo, "did my skill edit help?", "interview")
    ids = [q["id"] for q in interview["questions"]]
    assert ids == ["compare", "objective", "baseline", "repeats", "checks", "setup", "judge", "ship"]
    assert interview["harnesses"]["claude"]["installed"] is True
