from pathlib import Path

import pytest
from sqlalchemy import select, text

from bankrecon.cli import main
from bankrecon.db import repository
from bankrecon.db.models import Match
from bankrecon.db.session import make_engine, make_session_factory
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


@pytest.mark.usefixtures("no_database_env")
def test_load_db_protects_analyst_reviews(data_dir, capsys):
    data = str(data_dir)
    for step in ("reconcile", "detect", "load-db"):
        assert main([step, "--data", data]) == 0
    url = f"sqlite:///{(data_dir / 'bankrecon.db').as_posix()}"
    engine = make_engine(url)
    with make_session_factory(engine).begin() as session:
        match = session.scalar(select(Match).where(Match.status == "sugerida").limit(1))
        repository.approve(session, match.transaction_id)
    engine.dispose()
    capsys.readouterr()

    assert main(["load-db", "--data", data]) == 2
    assert "--replace" in capsys.readouterr().err
    assert main(["load-db", "--data", data, "--replace"]) == 0


@pytest.mark.usefixtures("no_database_env")
def test_demo_force_regenerates_with_the_requested_seed(tmp_path, capsys):
    data = tmp_path / "demo"
    assert main(["generate", "--seed", "1", "--months", "3", "--out", str(data)]) == 0
    assert main(["demo", "--data", str(data)]) == 0
    assert "Usando os dados" in capsys.readouterr().out
    assert _transaction_count(data / "bankrecon.db") < 300  # the 3-month dataset

    assert main(["demo", "--data", str(data), "--seed", "2", "--force"]) == 0
    assert _transaction_count(data / "bankrecon.db") > 500  # regenerated, 12 months


FIXTURES = Path(__file__).parent / "ingest" / "fixtures"


@pytest.fixture
def db_args(tmp_path):
    return [
        "--data",
        str(tmp_path),
        "--database-url",
        f"sqlite:///{(tmp_path / 'r.db').as_posix()}",
    ]


def test_import_real_files_and_process(db_args, tmp_path, capsys):
    invoices = [str(FIXTURES / n) for n in ("nfe_parcelada.xml", "nfe_a_vista.xml")]
    assert main(["import-invoices", *invoices, *db_args]) == 0
    out = capsys.readouterr().out
    assert "3 importados" in out
    assert "2 fornecedores novos" in out

    assert main(["import-statement", str(FIXTURES / "extrato_v1.ofx"), *db_args]) == 0
    out = capsys.readouterr().out
    assert "3 importados, 0 já existiam, 1 créditos ignorados" in out
    assert "Processadas 3 transações" in out

    assert main(["import-statement", str(FIXTURES / "extrato_v1.ofx"), *db_args]) == 0
    assert "0 importados, 3 já existiam" in capsys.readouterr().out
    assert main(["process", *db_args]) == 0
    assert "Processadas 3 transações" in capsys.readouterr().out


def test_import_reports_row_warnings(db_args, capsys):
    assert main(["import-statement", str(FIXTURES / "extrato.csv"), *db_args]) == 0
    assert "aviso: linha 7: valor inválido" in capsys.readouterr().out


def test_unreadable_statement_imports_nothing(db_args, tmp_path, capsys):
    good, bad = FIXTURES / "extrato_v1.ofx", tmp_path / "extrato.pdf"
    bad.write_bytes(b"%PDF")
    assert main(["import-statement", str(good), str(bad), *db_args]) == 2
    assert "extrato.pdf: formato não suportado" in capsys.readouterr().err
    assert main(["process", *db_args]) == 0
    assert "Processadas 0 transações" in capsys.readouterr().out  # all or nothing


def test_missing_file_is_reported(db_args, tmp_path, capsys):
    assert main(["import-invoices", str(tmp_path / "nao_existe.xml"), *db_args]) == 2
    assert "não foi possível ler" in capsys.readouterr().err


def test_import_invoices_fails_when_no_file_can_be_read(db_args, tmp_path, capsys):
    bad = tmp_path / "notas.pdf"
    bad.write_bytes(b"%PDF")
    cancelled = FIXTURES / "nfe_cancelada.xml"
    assert main(["import-invoices", str(bad), str(cancelled), *db_args]) == 2
    err = capsys.readouterr().err
    assert "nenhum arquivo pôde ser lido" in err
    assert "notas.pdf" in err
