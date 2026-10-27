"""Per-harness adapters: run an agent or judge headless, isolate it, read its metrics.

Every recipe below comes from docs/v0.3-isolation-spike.md:
- clean = a fresh HOME (plus the harness's config vars) with auth seeded; tool caches stay on real paths.
- real  = the user's actual home, untouched (never copied: copies lose keychain/db auth).
"""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from agents_arena_mcp import proc
from agents_arena_mcp.models import Contestant, JudgeSpec, Metrics

TOKEN_VARS = ("CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY")
OPENCODE_PROVIDER_VARS = ("OPENROUTER_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY")


@dataclass(frozen=True)
class JudgeFiles:
    prompt_file: str
    output_file: str
    schema_file: str
    schema_json: str


def fill(parts: list[str], values: dict[str, str]) -> list[str]:
    out = []
    for part in parts:
        for key, value in values.items():
            part = part.replace("{" + key + "}", value)
        out.append(part)
    return out


def _json_lines(stdout: str) -> list[dict]:
    events = []
    for line in stdout.splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return events


def _clean_base(home: Path) -> dict[str, str]:
    real = Path.home()
    home.mkdir(parents=True, exist_ok=True)
    env = {
        "HOME": str(home),
        # Keep package caches shared so runs don't re-download dependencies.
        "UV_CACHE_DIR": os.environ.get("UV_CACHE_DIR", str(real / ".cache" / "uv")),
        "npm_config_cache": os.environ.get("npm_config_cache", str(real / ".npm")),
        "XDG_CACHE_HOME": os.environ.get("XDG_CACHE_HOME", str(real / ".cache")),
    }
    if (real / ".gitconfig").exists():
        env["GIT_CONFIG_GLOBAL"] = str(real / ".gitconfig")
    return env


class Adapter:
    name = ""
    family = ""
    executable = ""

    def agent_argv(self, c: Contestant, prompt: str, run_dir: Path, workspace: Path) -> list[str]:
        raise NotImplementedError

    def judge_argv(self, j: JudgeSpec, prompt: str, files: JudgeFiles) -> list[str]:
        raise NotImplementedError

    def clean_env(self, home: Path) -> dict[str, str]:
        return _clean_base(home)

    def preflight(self, c: Contestant) -> list[str]:
        return [] if shutil.which(self.executable) else [f"`{self.executable}` is not installed or not on PATH"]

    def judge_preflight(self, j: JudgeSpec) -> list[str]:
        return [] if shutil.which(self.executable) else [f"judge `{self.executable}` is not installed or not on PATH"]

    def metrics(self, stdout: str, *, cwd: Path, env: dict[str, str] | None) -> Metrics:
        """Generic: sum `usage` blocks and take the last `total_cost_usd` found in JSON lines."""
        m = Metrics()
        for e in _json_lines(stdout):
            usage = e.get("usage")
            if isinstance(usage, dict):
                m.input_tokens = (m.input_tokens or 0) + int(usage.get("input_tokens") or 0)
                m.output_tokens = (m.output_tokens or 0) + int(usage.get("output_tokens") or 0)
            if isinstance(e.get("total_cost_usd"), int | float):
                m.cost_usd = float(e["total_cost_usd"])
        return m


class Claude(Adapter):
    name, family, executable = "claude", "anthropic", "claude"

    def agent_argv(self, c, prompt, run_dir, workspace):
        argv = ["claude", "-p", prompt, "--output-format", "json", "--permission-mode", "acceptEdits",
                "--allowedTools", "Bash,Edit,Write,Read,Grep,Glob"]  # fmt: skip
        return argv + (["--model", c.model] if c.model else [])

    def judge_argv(self, j, prompt, files):
        argv = ["claude", "-p", prompt, "--output-format", "json", "--json-schema", files.schema_json,
                "--setting-sources", "", "--tools", ""]  # fmt: skip
        return argv + (["--model", j.model] if j.model else [])

    def clean_env(self, home):
        env = _clean_base(home)
        (home / ".claude").mkdir(parents=True, exist_ok=True)
        env["CLAUDE_CONFIG_DIR"] = str(home / ".claude")
        return env  # auth: CLAUDE_CODE_OAUTH_TOKEN / ANTHROPIC_API_KEY pass through from the environment

    def preflight(self, c):
        problems = super().preflight(c)
        if c.baseline == "clean" and not any(os.environ.get(v) for v in TOKEN_VARS):
            problems.append(
                "clean claude can't use your keychain login: run `claude setup-token` once and export "
                "CLAUDE_CODE_OAUTH_TOKEN (or set ANTHROPIC_API_KEY)"
            )
        return problems

    def metrics(self, stdout, *, cwd, env):
        result = next((e for e in reversed(_json_lines(stdout)) if "usage" in e), None)
        if result is None:
            return Metrics()
        u = result["usage"]
        tokens_in = sum(
            int(u.get(k) or 0) for k in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")
        )
        return Metrics(
            input_tokens=tokens_in,
            output_tokens=int(u.get("output_tokens") or 0),
            cost_usd=result.get("total_cost_usd"),
            turns=result.get("num_turns"),
        )


class Codex(Adapter):
    name, family, executable = "codex", "openai", "codex"

    def agent_argv(self, c, prompt, run_dir, workspace):
        argv = ["codex", "exec", "--skip-git-repo-check", "--sandbox", "workspace-write", "--json"]
        return argv + (["--model", c.model] if c.model else []) + [prompt]

    def judge_argv(self, j, prompt, files):
        argv = ["codex", "exec", "--skip-git-repo-check", "--ignore-user-config", "--ephemeral",
                "--sandbox", "read-only", "--output-schema", files.schema_file,
                "--output-last-message", files.output_file]  # fmt: skip
        return argv + (["--model", j.model] if j.model else []) + [prompt]

    def clean_env(self, home):
        env = _clean_base(home)
        codex_home = home / ".codex"
        codex_home.mkdir(parents=True, exist_ok=True)
        auth = Path.home() / ".codex" / "auth.json"
        if auth.exists():
            shutil.copy2(auth, codex_home / "auth.json")  # deleted with the run's home (workspace.destroy)
        env["CODEX_HOME"] = str(codex_home)
        return env

    def preflight(self, c):
        problems = super().preflight(c)
        if (
            c.baseline == "clean"
            and not (Path.home() / ".codex" / "auth.json").exists()
            and not os.environ.get("OPENAI_API_KEY")
        ):
            problems.append("clean codex needs ~/.codex/auth.json (run `codex login`) or OPENAI_API_KEY")
        return problems

    def metrics(self, stdout, *, cwd, env):
        m = Metrics(turns=0)
        for e in _json_lines(stdout):
            if e.get("type") == "turn.completed" and isinstance(e.get("usage"), dict):
                m.turns = (m.turns or 0) + 1
                m.input_tokens = (m.input_tokens or 0) + int(e["usage"].get("input_tokens") or 0)
                m.output_tokens = (m.output_tokens or 0) + int(e["usage"].get("output_tokens") or 0)
        return m  # codex reports no dollar cost


class OpenCode(Adapter):
    name, family, executable = "opencode", "opencode", "opencode"

    def agent_argv(self, c, prompt, run_dir, workspace):
        return ["opencode", "run", "--standalone", "--auto", "--format", "json", "-m", c.model, prompt]

    def judge_argv(self, j, prompt, files):
        return ["opencode", "run", "--standalone", "--format", "json", "-m", j.model, prompt]

    def clean_env(self, home):
        env = _clean_base(home)
        env["XDG_CONFIG_HOME"] = str(home / ".config")
        env["XDG_DATA_HOME"] = str(home / ".local" / "share")
        for key in ("XDG_CONFIG_HOME", "XDG_DATA_HOME"):
            Path(env[key]).mkdir(parents=True, exist_ok=True)
        return env  # stored logins live in opencode.db; clean runs only see env-keyed providers

    def preflight(self, c):
        problems = super().preflight(c)
        if not c.model:
            problems.append("opencode needs an explicit model (provider/model), e.g. openrouter/openai/gpt-5-mini")
        if c.baseline == "clean" and not any(os.environ.get(v) for v in OPENCODE_PROVIDER_VARS):
            problems.append(
                "clean opencode only sees providers keyed by environment variables; "
                f"set one of {', '.join(OPENCODE_PROVIDER_VARS)}"
            )
        return problems

    def judge_preflight(self, j):
        problems = super().judge_preflight(j)
        if not j.model:
            problems.append("opencode judge needs an explicit model (provider/model)")
        return problems

    def metrics(self, stdout, *, cwd, env):
        events = _json_lines(stdout)
        session = next((e["sessionID"] for e in events if e.get("sessionID")), None)
        turns = sum(1 for e in events if e.get("type") == "step_start")
        if not session:
            return Metrics(turns=turns or None)
        out = proc.run(["opencode", "session", "export", session, "--standalone"], cwd, 60, env=env)
        try:
            info = json.loads(out.stdout[out.stdout.find("{") :])["info"]
        except (ValueError, KeyError):
            return Metrics(turns=turns or None)
        t = info.get("tokens") or {}
        cache = t.get("cache") or {}
        return Metrics(
            input_tokens=int(t.get("input") or 0) + int(cache.get("read") or 0) + int(cache.get("write") or 0),
            output_tokens=int(t.get("output") or 0) + int(t.get("reasoning") or 0),
            cost_usd=info.get("cost"),
            turns=turns or None,
        )


class Command(Adapter):
    """Any CLI given as argv in the spec. Used by tests and for harnesses without an adapter yet."""

    name, family = "command", "command"

    def agent_argv(self, c, prompt, run_dir, workspace):
        return fill(c.argv, {"prompt": prompt, "workspace": str(workspace), "model": c.model, "run_dir": str(run_dir)})

    def judge_argv(self, j, prompt, files):
        values = {"prompt": prompt, "prompt_file": files.prompt_file, "output_file": files.output_file,
                  "schema_file": files.schema_file, "model": j.model}  # fmt: skip
        return fill(j.argv, values)

    def preflight(self, c):
        return [] if shutil.which(c.argv[0]) else [f"`{c.argv[0]}` not found"]

    def judge_preflight(self, j):
        return [] if shutil.which(j.argv[0]) else [f"judge `{j.argv[0]}` not found"]


ADAPTERS: dict[str, Adapter] = {a.name: a for a in (Claude(), Codex(), OpenCode(), Command())}


def get(name: str) -> Adapter:
    return ADAPTERS[name]
