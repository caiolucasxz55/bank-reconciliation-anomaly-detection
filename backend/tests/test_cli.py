import pytest
from sqlalchemy import text

from bankrecon.cli import main
from bankrecon.db.session import make_engine
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
    assert "reconcile" in capsys.readouterr().err


def test_results_from_another_seed_with_same_ids_are_rejected(data_dir, capsys):
    data = str(data_dir)
    assert main(["reconcile", "--data", data]) == 0
    assert main(["detect", "--data", data]) == 0
    # Same period and settings: transaction ids may coincide, the content does not.
    assert main(["generate", "--seed", "5", "--months", "4", "--out", data]) == 0
    capsys.readouterr()
    assert main(["detect", "--data", data]) == 2
    assert "outros dados" in capsys.readouterr().err
    assert main(["evaluate", "--data", data]) == 2


def _transaction_count(db_path):
    engine = make_engine(f"sqlite:///{db_path.as_posix()}")
    try:
        with engine.connect() as connection:
            return connection.execute(text("SELECT COUNT(*) FROM bank_transactions")).scalar()
    finally:
        engine.dispose()


@pytest.fixture
def no_database_env(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)


@pytest.mark.usefixtures("no_database_env")
def test_load_db_after_pipeline(data_dir):
    data = str(data_dir)
    assert main(["reconcile", "--data", data]) == 0
    assert main(["detect", "--data", data]) == 0
    assert main(["load-db", "--data", data]) == 0
    assert _transaction_count(data_dir / "bankrecon.db") == len(Dataset.load(data_dir).transactions)


@pytest.mark.usefixtures("no_database_env")
def test_load_db_requires_results(data_dir, capsys):
    assert main(["load-db", "--data", str(data_dir)]) == 2
    assert "bankrecon reconcile" in capsys.readouterr().err


@pytest.mark.usefixtures("no_database_env")
def test_demo_runs_everything_once(tmp_path, capsys):
    data = tmp_path / "demo"
    db = tmp_path / "demo.db"
    url = f"sqlite:///{db.as_posix()}"
    assert main(["demo", "--data", str(data), "--database-url", url]) == 0
    assert _transaction_count(db) > 500
    capsys.readouterr()

    assert main(["demo", "--data", str(data), "--database-url", url]) == 0
    assert "nada a fazer" in capsys.readouterr().out

    assert main(["demo", "--data", str(data), "--database-url", url, "--force"]) == 0
    assert "Banco carregado" in capsys.readouterr().out


def test_unreachable_database_fails_cleanly(data_dir, capsys):
    url = "postgresql+psycopg://user:pass@127.0.0.1:1/none?connect_timeout=1"
    assert main(["demo", "--data", str(data_dir), "--database-url", url]) == 2
    assert "não foi possível acessar o banco" in capsys.readouterr().err
