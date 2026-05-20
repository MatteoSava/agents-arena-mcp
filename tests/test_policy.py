import pytest

from shadow_pr_arena_mcp.core.errors import ArenaError
from shadow_pr_arena_mcp.core.policy import DEFAULT_POLICY, assert_command_allowed


def test_blocks_destructive_command():
    with pytest.raises(ArenaError):
        assert_command_allowed("git reset --hard", DEFAULT_POLICY)


def test_allows_pytest():
    assert_command_allowed("python -m pytest -q", DEFAULT_POLICY)
