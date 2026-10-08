import pytest

from bankrecon.cli import main


def test_cli_requires_a_command():
    with pytest.raises(SystemExit):
        main([])
