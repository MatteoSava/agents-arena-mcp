import json

import pytest

from agents_arena_mcp import __version__, cli


def test_version_flag_prints_package_version(capsys):
    with pytest.raises(SystemExit) as excinfo:
        cli.main(["--version"])

    assert excinfo.value.code == 0
    assert capsys.readouterr().out.strip() == f"agents-arena {__version__}"


def test_dry_run_open_prints_rich_json(capsys):
    exit_code = cli.main(["--dry-run", "open", "test task", "--base-ref", "HEAD", "--variant", "detailed", "--include-current-diff"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "args": {
            "base_ref": "HEAD",
            "include_current_diff": True,
            "risk_level": "normal",
            "task": "test task",
            "variants": ["detailed"],
        },
        "command": "open",
        "description": "Would create a new arena with task 'test task' using base ref HEAD.",
        "dry_run": True,
        "engine_method": "open",
        "side_effects": [
            "Creates git worktrees for each variant",
            "Writes arena metadata to .agents-arena/state/",
            "Appends an arena_open event to .agents-arena/state/arenas.jsonl",
        ],
    }


def test_dry_run_status_skips_engine_creation(monkeypatch, capsys):
    def explode(*args, **kwargs):
        raise AssertionError("ArenaEngine should not be created during dry-run")

    monkeypatch.setattr(cli, "ArenaEngine", explode)

    exit_code = cli.main(["--dry-run", "status", "--arena-id", "arena-123"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["command"] == "status"
    assert payload["engine_method"] == "status"
    assert payload["description"] == "Would show status for arena 'arena-123'."
    assert payload["args"] == {"arena_id": "arena-123"}
    assert payload["side_effects"] == []


def test_dry_run_brief_description_includes_variant_name(capsys):
    exit_code = cli.main(["--dry-run", "brief", "arena-123", "detailed"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["command"] == "brief"
    assert payload["engine_method"] == "variant_brief"
    assert payload["args"] == {"arena_id": "arena-123", "variant": "detailed"}
    assert payload["description"] == "Would show the variant brief for 'detailed' in arena 'arena-123'."
    assert payload["side_effects"] == []


def test_dry_run_cleanup_maps_discard_patches_to_keep_patches_false(capsys):
    exit_code = cli.main(["--dry-run", "cleanup", "arena-123", "--discard-patches"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["command"] == "cleanup"
    assert payload["engine_method"] == "cleanup"
    assert payload["args"] == {"arena_id": "arena-123", "keep_patches": False}
    assert payload["description"] == "Would remove arena worktrees for arena 'arena-123' and discard saved patches."
    assert payload["side_effects"] == [
        "Removes variant git worktrees",
        "Updates arena status to cleaned in .agents-arena/state/",
        "Appends a cleanup event to .agents-arena/state/arenas.jsonl",
    ]
