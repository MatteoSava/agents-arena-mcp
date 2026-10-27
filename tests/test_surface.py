import asyncio
import json

from conftest import command_contestant, command_judge
from fastmcp import Client

from agents_arena_mcp import cli
from agents_arena_mcp.server import make_mcp


def tools():
    async def go():
        async with Client(make_mcp()) as c:
            return await c.list_tools(), await c.read_resource("arena://guide")

    return asyncio.run(go())


def test_five_tools_with_described_params_and_guide():
    listed, guide = tools()
    assert sorted(t.name for t in listed) == [
        "arena_history",
        "arena_plan",
        "arena_result",
        "arena_start",
        "arena_status",
    ]
    for t in listed:
        assert t.description
        for name, prop in t.inputSchema.get("properties", {}).items():
            assert name != "ctx" and prop.get("description"), f"{t.name}.{name}"
    assert "arena_plan" in guide[0].text


def test_cli_and_mcp_parity():
    listed, _ = tools()
    mcp = {t.name: set(t.inputSchema.get("properties", {})) for t in listed}
    parser = cli.build_parser()
    sub = next(a for a in parser._actions if a.dest == "cmd")
    for name, fn in cli.COMMANDS.items():
        dests = {a.dest for a in sub.choices[name]._actions if a.dest != "help"}  # type: ignore[union-attr]
        assert dests == mcp[fn.__name__], name


def test_cli_plan_start_result(repo, fakes, tmp_path, capsys):
    assert cli.main(["plan", "x vs y", "--mode", "autopilot"]) == 0
    assert "draft_spec" in json.loads(capsys.readouterr().out)
    spec = {
        "task": "t",
        "judge": command_judge(fakes),
        "contestants": [command_contestant(fakes, "x"), command_contestant(fakes, "y")],
    }
    path = tmp_path / "spec.json"
    path.write_text(json.dumps(spec))
    assert cli.main(["start", str(path)]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "done"
    assert cli.main(["result", "--html"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["scorecard"]["verdict"] and out["html"].endswith("report.html")


def test_cli_bad_spec_files_exit_cleanly(tmp_path, capsys):
    assert cli.main(["start", "/nonexistent/spec.json"]) == 2
    assert "Can't read spec file" in capsys.readouterr().err
    bad = tmp_path / "bad.json"
    bad.write_text("not json")
    assert cli.main(["start", str(bad)]) == 2
    assert "Can't read spec file" in capsys.readouterr().err


def _toml_table(d):
    return "\n".join(f"{k} = {json.dumps(v)}" for k, v in d.items())


def test_cli_start_toml_spec(repo, fakes, tmp_path, capsys):
    text = f'task = "t"\n\n[judge]\n{_toml_table(command_judge(fakes))}\n'
    for name in ("x", "y"):
        text += f"\n[[contestants]]\n{_toml_table(command_contestant(fakes, name))}\n"
    path = tmp_path / "spec.toml"
    path.write_text(text)
    assert cli.main(["start", str(path)]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "done"


def test_cli_init_installs_skills(repo, capsys):
    assert cli.main(["init", "--skills", "claude,codex"]) == 0
    for d in (".claude", ".agents"):
        text = (repo / d / "skills/agents-arena/SKILL.md").read_text()
        assert text.startswith("---\nname: agents-arena") and "arena_plan" in text
    assert cli.main(["init", "--skills", "nope"]) == 2


def test_repo_mcp_json_starts_a_working_server():
    """The server Claude Code launches from this repo's .mcp.json must answer over stdio."""
    from pathlib import Path

    from fastmcp.client.transports import StdioTransport

    root = Path(__file__).resolve().parent.parent
    server = json.loads((root / ".mcp.json").read_text())["mcpServers"]["agents-arena"]
    transport = StdioTransport(server["command"], server["args"], env=server.get("env"), cwd=str(root))

    async def go():
        async with Client(transport) as c:
            return await asyncio.wait_for(c.list_tools(), timeout=60)

    assert "arena_plan" in {t.name for t in asyncio.run(go())}
