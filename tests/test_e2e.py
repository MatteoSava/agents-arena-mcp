import asyncio
import json
import time

from conftest import command_contestant, command_judge
from fastmcp import Client

from agents_arena_mcp.server import make_mcp


def test_full_flow_over_mcp(repo, fakes, monkeypatch):
    monkeypatch.setenv("FAKE_PLAN", json.dumps({"x": {"write": {"a.py": "# GOOD\n"}}, "y": {"write": {"a.py": "2\n"}}}))
    spec = {"task": "t", "repeats": 2, "judge": command_judge(fakes),
            "contestants": [command_contestant(fakes, "x"), command_contestant(fakes, "y")]}  # fmt: skip

    async def go():
        async with Client(make_mcp()) as c:
            planned = (await c.call_tool("arena_plan", {"request": "x vs y", "mode": "interview"})).data
            assert planned["questions"]
            started = (await c.call_tool("arena_start", {"spec": spec})).data
            assert started["job"]["status"] == "running"
            for _ in range(150):
                status = (await c.call_tool("arena_status", {})).data
                if status["status"] != "running":
                    break
                time.sleep(0.1)
            assert status["status"] == "done", status
            result = (await c.call_tool("arena_result", {"promote": "branch"})).data
            history = (await c.call_tool("arena_history", {"contestant": "x"})).data
            return result, history

    result, history = asyncio.run(go())
    assert result["scorecard"]["winner"] == "x" and result["promoted"]["branch"].startswith("arena/")
    assert history["entries"][0]["winner"] == "x"
