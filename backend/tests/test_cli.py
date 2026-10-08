import pytest

from bankrecon.cli import main
from bankrecon.generator import Dataset


@pytest.fixture
def data_dir(tmp_path):
    assert main(["generate", "--seed", "3", "--months", "4", "--out", str(tmp_path)]) == 0
    return tmp_path


def test_cli_requires_a_command():
    with pytest.raises(SystemExit):
        main([])


def test_generate_writes_dataset(tmp_path, capsys):
    assert main(["generate", "--seed", "3", "--months", "4", "--out", str(tmp_path)]) == 0
    assert len(Dataset.load(tmp_path).transactions) > 100
    assert "transações" in capsys.readouterr().out


def test_generate_reports_invalid_config(tmp_path, capsys):
    assert main(["generate", "--months", "1", "--out", str(tmp_path)]) == 2
    assert "months" in capsys.readouterr().err


def test_full_pipeline(data_dir, capsys):
    data = str(data_dir)
    assert main(["reconcile", "--data", data]) == 0
    assert main(["detect", "--data", data]) == 0
    assert (data_dir / "results" / "matches.csv").exists()
    assert (data_dir / "results" / "anomaly_scores.csv").exists()
    capsys.readouterr()

    assert main(["evaluate", "--data", data]) == 0
    out = capsys.readouterr().out
    assert "| 1. Exata |" in out
    assert "| Pagamento duplicado |" in out
    assert "Precisão nas 50" in out


def test_reconcile_without_data_fails_cleanly(tmp_path, capsys):
    assert main(["reconcile", "--data", str(tmp_path / "missing")]) == 2
    assert "bankrecon generate" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("steps", "command", "hint"),
    [
        ([], "detect", "bankrecon reconcile"),
        ([], "evaluate", "bankrecon reconcile"),
        (["reconcile"], "evaluate", "bankrecon detect"),
    ],
)
def test_missing_previous_step_fails_cleanly(data_dir, capsys, steps, command, hint):
    for step in steps:
        assert main([step, "--data", str(data_dir)]) == 0
    capsys.readouterr()
    assert main([command, "--data", str(data_dir)]) == 2
    assert hint in capsys.readouterr().err


def test_stale_results_fail_cleanly(data_dir, capsys):
    data = str(data_dir)
    assert main(["reconcile", "--data", data]) == 0
    assert main(["detect", "--data", data]) == 0
    assert main(["generate", "--seed", "4", "--months", "3", "--out", data]) == 0
    capsys.readouterr()

    assert main(["detect", "--data", data]) == 2
    assert "reconcile" in capsys.readouterr().err
    assert main(["evaluate", "--data", data]) == 2
    assert "pipeline" in capsys.readouterr().err
