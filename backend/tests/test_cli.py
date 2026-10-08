import pytest

from bankrecon.cli import main
from bankrecon.generator import Dataset


def test_cli_requires_a_command():
    with pytest.raises(SystemExit):
        main([])


def test_generate_writes_dataset(tmp_path, capsys):
    assert main(["generate", "--seed", "3", "--months", "6", "--out", str(tmp_path)]) == 0
    dataset = Dataset.load(tmp_path)
    assert len(dataset.transactions) > 100
    assert "transações" in capsys.readouterr().out


def test_generate_reports_invalid_config(tmp_path, capsys):
    assert main(["generate", "--months", "1", "--out", str(tmp_path)]) == 2
    assert "months" in capsys.readouterr().err
