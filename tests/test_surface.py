"""The CLI and the MCP server expose the same operations and parameters; init and legacy handling."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from fastmcp import Client

from agents_arena_mcp import __version__, cli
from agents_arena_mcp import arena as ops
from agents_arena_mcp.errors import ArenaError
from agents_arena_mcp.server import make_mcp


def mcp_tools() -> dict[str, set[str]]:
    async def fetch():
        async with Client(make_mcp()) as client:
            return await client.list_tools()

    return {t.name: set(t.inputSchema.get("properties", {})) for t in asyncio.run(fetch())}


def cli_params() -> dict[str, set[str]]:
    parser = cli.build_parser()
    sub = next(a for a in parser._actions if a.dest == "cmd")
    out = {}
    for name, p in sub.choices.items():  # type: ignore[union-attr]
        if name in cli.COMMANDS:
            out[cli.COMMANDS[name].__name__] = {a.dest for a in p._actions if a.dest != "help"}
    return out


def test_cli_and_mcp_expose_the_same_parameters():
    tools, commands = mcp_tools(), cli_params()
    assert set(tools) == set(commands)
    for name, params in tools.items():
        assert params == commands[name], name


def test_mcp_tools_have_descriptions_and_no_context_param():
    async def fetch():
        async with Client(make_mcp()) as client:
            return await client.list_tools()

    for tool in asyncio.run(fetch()):
        assert tool.description, tool.name
        assert "ctx" not in tool.inputSchema.get("properties", {})
        for prop, schema in tool.inputSchema.get("properties", {}).items():
            assert schema.get("description"), f"{tool.name}.{prop}"


def test_report_resource(repo: Path):
    opened = ops.arena_open("task", variants=["a"])
    (Path(opened["variants"]["a"]["workspace"]) / "app.py").write_text("x = 1\n")
    ops.arena_check()
    ops.arena_judge(wait=True)

    async def read():
        async with Client(make_mcp()) as client:
            return await client.read_resource(f"arena://{opened['arena_id']}/report")

    contents = asyncio.run(read())
    assert "Arena report" in contents[0].text  # type: ignore[union-attr]


def test_cli_round_trip(repo: Path, capsys):
    assert cli.main(["open", "cli task", "--variant", "a"]) == 0
    opened = json.loads(capsys.readouterr().out)
    assert cli.main(["status"]) == 0
    assert json.loads(capsys.readouterr().out)["arena_id"] == opened["arena_id"]
    assert cli.main(["close", "--discard"]) == 0


def test_cli_reports_errors_as_json(repo: Path, capsys):
    assert cli.main(["status"]) == 2
    assert "No arena yet" in json.loads(capsys.readouterr().err)["error"]


def test_version_flag(capsys):
    with pytest.raises(SystemExit):
        cli.main(["--version"])
    assert capsys.readouterr().out.strip() == f"agents-arena {__version__}"


def test_init_writes_config_gitignore_and_skills(repo: Path, capsys):
    assert cli.main(["init", "--skills", "claude,codex"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert (repo / ".agents-arena" / "config.toml").exists()
    assert (repo / ".agents-arena" / ".gitignore").read_text().startswith("*")
    assert (repo / ".claude/skills/agents-arena/SKILL.md").exists()
    assert (repo / ".agents/skills/agents-arena/SKILL.md").exists()
    assert out["mcp_config"]["mcpServers"]["agents-arena"]["command"] == "uvx"


def test_legacy_state_is_refused_with_instructions(repo: Path):
    (repo / ".agents-arena" / "state").mkdir(parents=True)
    with pytest.raises(ArenaError, match="v0.1"):
        ops.arena_open("task", variants=["a"])


def test_wait_true_emits_mcp_progress_notifications(repo: Path, fakes):
    from conftest import write_config

    write_config(repo, fakes)
    ops.arena_open("task", variants=["a", "b"])
    messages: list[str] = []

    async def on_progress(progress: float, total: float | None, message: str | None) -> None:
        messages.append(message or "")

    async def call():
        async with Client(make_mcp()) as client:
            return await client.call_tool("arena_run", {"wait": True}, progress_handler=on_progress)

    asyncio.run(call())
    assert "2/2 variants finished" in messages


def test_templates_are_overridable(repo: Path):
    from conftest import write_config

    write_config(repo, extra="brief_template = '.agents-arena/brief.tmpl'")
    (repo / ".agents-arena" / "brief.tmpl").write_text("CUSTOM BRIEF for $variant: $task\n")
    opened = ops.arena_open("do it", variants=["a"])
    assert opened["briefs"]["a"] == "CUSTOM BRIEF for a: do it\n"
