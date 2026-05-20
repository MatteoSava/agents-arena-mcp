import pytest

from agents_arena_mcp import __version__
from agents_arena_mcp.cli import main


def test_version_flag_prints_package_version(capsys):
    with pytest.raises(SystemExit) as excinfo:
        main(["--version"])

    assert excinfo.value.code == 0
    assert capsys.readouterr().out.strip() == f"agents-arena {__version__}"
