from pathlib import Path

import pytest
from sqlalchemy import func, select

from bankrecon.db import repository
from bankrecon.db.importer import import_invoices, import_statement
from bankrecon.db.models import AnomalyScore, BankTransaction, Match
from bankrecon.db.processing import process
from bankrecon.db.session import create_schema, make_engine, make_session_factory

FIXTURES = Path(__file__).parents[1] / "ingest" / "fixtures"

INVOICES = ("nfe_parcelada.xml", "nfe_a_vista.xml")
# Payments of: installment 001 of NF 1234 (due 05/04), NF 88 (issued 08/04) and
# installment 002 of NF 1234 (due 05/05), plus an energy bill with no invoice.
STATEMENT = b"""data;descricao;valor
07/04/2025;PIX ENVIADO ACME LOGISTICA E TRANSPORTES LTDA;-1.500,00
10/04/2025;PAG BOLETO NORTE TRANSPORTES ME;-845,90
06/05/2025;PIX ENVIADO ACME LOGISTICA E TRANSPORTES LTDA;-1.500,00
06/05/2025;PAG BOLETO ENERGIA ELETRICA;-87,35
"""


@pytest.fixture
def db():
    engine = make_engine("sqlite://")
    create_schema(engine)
    factory = make_session_factory(engine)
    with factory.begin() as session:
        import_invoices(session, [(n, (FIXTURES / n).read_bytes()) for n in INVOICES])
        import_statement(session, "extrato.csv", STATEMENT)
    yield factory
    engine.dispose()


def _matches(factory) -> dict[str, tuple[str, list[str]]]:
    """description+date -> (status, invoice numbers)."""
    with factory() as session:
        out = {}
        for tx in session.scalars(select(BankTransaction)):
            numbers = sorted(inv.number for inv in tx.match.invoices)
            out[f"{tx.date:%d/%m} {tx.description}"] = (tx.match.status, numbers)
        return out


def test_empty_database_processes_to_nothing():
    engine = make_engine("sqlite://")
    create_schema(engine)
    with make_session_factory(engine).begin() as session:
        summary = process(session)
    assert (summary.transactions, summary.reconciled_now, summary.high_risk) == (0, 0, 0)
    engine.dispose()


def test_imported_payments_are_matched_to_the_right_installments(db):
    with db.begin() as session:
        summary = process(session)
    assert summary.transactions == 4
    matches = _matches(db)
    assert matches["07/04 PIX ENVIADO ACME LOGISTICA E TRANSPORTES LTDA"][1] == ["1234/001"]
    assert matches["06/05 PIX ENVIADO ACME LOGISTICA E TRANSPORTES LTDA"][1] == ["1234/002"]
    assert matches["10/04 PAG BOLETO NORTE TRANSPORTES ME"] == ("conciliada", ["88"])
    assert matches["06/05 PAG BOLETO ENERGIA ELETRICA"] == ("divergente", [])


def test_every_transaction_gets_a_score(db):
    with db.begin() as session:
        process(session)
    with db() as session:
        assert session.scalar(select(func.count()).select_from(AnomalyScore)) == 4
        page, total = repository.list_transactions(session, repository.TransactionFilter())
    assert total == 4
    assert sorted(t.anomaly.rank for t in page) == [1, 2, 3, 4]


def test_processing_twice_gives_the_same_result(db):
    with db.begin() as session:
        process(session)
    first = _matches(db)
    with db.begin() as session:
        process(session)
    assert _matches(db) == first


def test_analyst_decisions_survive_reprocessing(db):
    with db.begin() as session:
        process(session)
    with db() as session:
        acme = session.scalar(
            select(Match)
            .join(BankTransaction)
            .where(BankTransaction.description.like("PIX ENVIADO ACME%"))
            .order_by(BankTransaction.date)
        )
        tx_id = acme.transaction_id
    with db.begin() as session:
        session.execute(
            Match.__table__.update().where(Match.transaction_id == tx_id).values(status="sugerida")
        )
        repository.reject(session, tx_id)

    # New data arrives and everything is processed again.
    with db.begin() as session:
        import_statement(session, "maio.csv", b"data;descricao;valor\n20/05/2025;PIX X;-10,00\n")
        summary = process(session)
    assert summary.kept_reviews == 1
    with db() as session:
        match = session.get(Match, tx_id)
        assert (match.status, match.decided_by, match.invoices) == ("divergente", "analista", [])
