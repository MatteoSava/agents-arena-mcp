import json
from pathlib import Path

import pytest

from agents_arena_mcp import harness
from agents_arena_mcp.models import Contestant, JudgeSpec


def c(**kw):
    return Contestant.model_validate({"name": "x", "harness": "claude"} | kw)


def test_claude_clean_needs_a_token(monkeypatch):
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(harness.shutil, "which", lambda name: f"/bin/{name}")
    assert any("setup-token" in p for p in harness.get("claude").preflight(c(baseline="clean")))
    assert harness.get("claude").preflight(c(baseline="real")) == []
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "t")
    assert harness.get("claude").preflight(c(baseline="clean")) == []


def test_clean_envs_redirect_home_and_seed_codex_auth(tmp_path, monkeypatch):
    for var in ("UV_CACHE_DIR", "XDG_CACHE_HOME", "npm_config_cache"):
        monkeypatch.delenv(var, raising=False)
    real = tmp_path / "real"
    (real / ".codex").mkdir(parents=True)
    (real / ".codex" / "auth.json").write_text("{}")
    monkeypatch.setenv("HOME", str(real))
    home = tmp_path / "clean"
    env = harness.get("codex").clean_env(home)
    assert env["HOME"] == str(home) and env["CODEX_HOME"] == str(home / ".codex")
    assert (home / ".codex" / "auth.json").exists()
    assert env["UV_CACHE_DIR"] == str(real / ".cache" / "uv") and env["XDG_CACHE_HOME"] == str(real / ".cache")
    assert harness.get("claude").clean_env(home)["CLAUDE_CONFIG_DIR"] == str(home / ".claude")
    oc = harness.get("opencode").clean_env(home)
    assert oc["XDG_CONFIG_HOME"] == str(home / ".config") and oc["XDG_DATA_HOME"] == str(home / ".local" / "share")


def test_agent_argv_shapes():
    assert harness.get("claude").agent_argv(c(model="sonnet"), "P", Path("/r"), Path("/w"))[:3] == ["claude", "-p", "P"]
    codex = harness.get("codex").agent_argv(c(harness="codex"), "P", Path("/r"), Path("/w"))
    assert codex[:2] == ["codex", "exec"] and codex[-1] == "P" and "--model" not in codex
    oc = harness.get("opencode").agent_argv(c(harness="opencode", model="openrouter/x"), "P", Path("/r"), Path("/w"))
    assert "--standalone" in oc and oc[oc.index("-m") + 1] == "openrouter/x"
    cmd = harness.get("command").agent_argv(
        c(harness="command", argv=["run", "{workspace}", "{prompt}"]), "P", Path("/r"), Path("/w")
    )
    assert cmd == ["run", "/w", "P"]


def test_opencode_requires_model(monkeypatch):
    monkeypatch.setattr(harness.shutil, "which", lambda name: f"/bin/{name}")
    assert any("explicit model" in p for p in harness.get("opencode").preflight(c(harness="opencode")))


def test_metrics_parsing():
    claude_out = json.dumps(
        {
            "type": "result",
            "usage": {
                "input_tokens": 5,
                "cache_read_input_tokens": 100,
                "cache_creation_input_tokens": 10,
                "output_tokens": 7,
            },
            "total_cost_usd": 0.02,
            "num_turns": 3,
        }
    )
    m = harness.get("claude").metrics(claude_out, cwd=Path("."), env=None)
    assert (m.input_tokens, m.output_tokens, m.cost_usd, m.turns) == (115, 7, 0.02, 3)
    codex_out = "\n".join(
        json.dumps(e)
        for e in [
            {"type": "thread.started"},
            {"type": "turn.completed", "usage": {"input_tokens": 50, "output_tokens": 4}},
            {"type": "turn.completed", "usage": {"input_tokens": 10, "output_tokens": 1}},
        ]
    )
    m = harness.get("codex").metrics(codex_out, cwd=Path("."), env=None)
    assert (m.input_tokens, m.output_tokens, m.cost_usd, m.turns) == (60, 5, None, 2)


def test_opencode_metrics_come_from_session_export(monkeypatch):
    calls = []

    def fake_run(argv, cwd, timeout, **kw):
        calls.append(argv)
        info = {
            "info": {"tokens": {"input": 80, "output": 9, "cache": {"read": 20, "write": 0}}, "cost": 0.003},
            "messages": [],
        }
        return harness.proc.ProcResult("passed", 0, json.dumps(info), "", 5)

    monkeypatch.setattr(harness.proc, "run", fake_run)
    stdout = "\n".join(
        json.dumps(e) for e in [{"type": "step_start", "sessionID": "ses_1"}, {"type": "text", "sessionID": "ses_1"}]
    )
    m = harness.get("opencode").metrics(stdout, cwd=Path("."), env=None)
    assert calls[0][:4] == ["opencode", "session", "export", "ses_1"]
    assert (m.input_tokens, m.output_tokens, m.cost_usd, m.turns) == (100, 9, 0.003, 1)


def test_judge_argv_isolates(tmp_path):
    files = harness.JudgeFiles(prompt_file="/p", output_file="/o", schema_file="/s", schema_json="{}")
    claude = harness.get("claude").judge_argv(JudgeSpec(harness="claude"), "P", files)
    assert claude[claude.index("--setting-sources") + 1] == "" and claude[claude.index("--tools") + 1] == ""
    codex = harness.get("codex").judge_argv(JudgeSpec(harness="codex"), "P", files)
    assert {"--ignore-user-config", "--ephemeral", "read-only"} <= set(codex)


def test_unknown_harness():
    with pytest.raises(KeyError):
        harness.get("nope")


def test_opencode_clean_needs_env_keyed_provider(monkeypatch):
    for var in harness.OPENCODE_PROVIDER_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(harness.shutil, "which", lambda name: f"/bin/{name}")
    oc = harness.get("opencode")
    clean, real = c(harness="opencode", model="p/m", baseline="clean"), c(harness="opencode", model="p/m")
    assert any("OPENROUTER_API_KEY" in p for p in oc.preflight(clean))
    assert oc.preflight(real) == []
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    assert oc.preflight(clean) == []
