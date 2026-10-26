from __future__ import annotations

import pytest

from agents_arena_mcp.core.policy import DEFAULT_POLICY, path_has_secret_signal


@pytest.mark.parametrize("path", ["docs/secrets-handling.md", "src/credentials_form.tsx"])
def test_secret_patterns_do_not_flag_ordinary_files(path: str):
    assert not path_has_secret_signal(path, DEFAULT_POLICY)


@pytest.mark.parametrize(
    "path", [".env", "config/.env.production", "keys/id_rsa", "secrets.yaml", "credentials.json", "secrets/db.txt"]
)
def test_secret_patterns_still_flag_secret_files(path: str):
    assert path_has_secret_signal(path, DEFAULT_POLICY)
