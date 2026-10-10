from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import func, select

from bankrecon.db.importer import import_invoices, import_statement, transaction_id
from bankrecon.db.models import BankTransaction, ImportBatch, Invoice, Supplier
from bankrecon.db.session import create_schema, make_engine, make_session_factory
from bankrecon.ingest import ParseError

FIXTURES = Path(__file__).parents[1] / "ingest" / "fixtures"


def _read(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


@pytest.fixture
def empty_db():
    engine = make_engine("sqlite://")
    create_schema(engine)
    yield make_session_factory(engine)
    engine.dispose()


def _count(session, model):
    return session.scalar(select(func.count()).select_from(model))


def test_statement_import_keeps_payments_and_skips_credits(empty_db):
    with empty_db.begin() as session:
        summary = import_statement(session, "extrato.ofx", _read("extrato_v1.ofx"))
    assert (summary.imported, summary.duplicates, summary.skipped) == (3, 0, 1)
    assert summary.errors == []
    with empty_db() as session:
        amounts = sorted(session.scalars(select(BankTransaction.amount)))
        assert amounts == [Decimal("12.90"), Decimal("845.90"), Decimal("1500.00")]
        batch = session.get(ImportBatch, summary.import_id)
        assert (batch.kind, batch.filename, batch.imported, batch.skipped) == (
            "extrato",
            "extrato.ofx",
            3,
            1,
        )


def test_reimporting_a_statement_creates_no_duplicates(empty_db):
    with empty_db.begin() as session:
        import_statement(session, "extrato.ofx", _read("extrato_v1.ofx"))
    with empty_db.begin() as session:
        again = import_statement(session, "extrato.ofx", _read("extrato_v1.ofx"))
    assert (again.imported, again.duplicates) == (0, 3)
    with empty_db() as session:
        assert _count(session, BankTransaction) == 3
        assert _count(session, ImportBatch) == 2


def test_statement_row_errors_are_recorded(empty_db):
    with empty_db.begin() as session:
        summary = import_statement(session, "extrato.csv", _read("extrato.csv"))
    assert summary.imported == 4  # 4 payments, 1 credit skipped, 1 bad line
    assert summary.skipped == 1
    assert summary.errors == ["linha 7: valor inválido: 'abc'"]
    with empty_db() as session:
        assert session.get(ImportBatch, summary.import_id).errors == summary.errors


def test_unreadable_statement_stores_nothing(empty_db):
    with empty_db.begin() as session, pytest.raises(ParseError):
        import_statement(session, "extrato.pdf", b"%PDF")
    with empty_db() as session:
        assert _count(session, ImportBatch) == 0


def test_transaction_ids_are_stable():
    assert transaction_id("ofx:1:2") == transaction_id("ofx:1:2")
    assert transaction_id("ofx:1:2") != transaction_id("ofx:1:3")
    assert len(transaction_id("x" * 500)) <= 64


def test_invoice_import_registers_suppliers_and_installments(empty_db):
    files = [
        ("parcelada.xml", _read("nfe_parcelada.xml")),
        ("a_vista.xml", _read("nfe_a_vista.xml")),
        ("cancelada.xml", _read("nfe_cancelada.xml")),
    ]
    with empty_db.begin() as session:
        summary = import_invoices(session, files)
    assert (summary.imported, summary.duplicates, summary.suppliers_created) == (3, 0, 2)
    assert len(summary.errors) == 1
    assert summary.errors[0].startswith("cancelada.xml: NF-e não autorizada")
    assert summary.filename == "3 arquivos: parcelada.xml, a_vista.xml, cancelada.xml"
    with empty_db() as session:
        acme = session.scalar(select(Supplier).where(Supplier.tax_id == "45.997.418/0001-53"))
        assert acme.name == "Acme Logística e Transportes Ltda"
        assert acme.supplier_id == "45997418000153"
        assert acme.registered_at == date(2025, 3, 5)
        installments = session.scalars(
            select(Invoice).where(Invoice.supplier_id == acme.supplier_id).order_by(Invoice.number)
        ).all()
        assert [i.number for i in installments] == ["1234/001", "1234/002"]
        assert [i.reference_date for i in installments] == [date(2025, 4, 5), date(2025, 5, 5)]


def test_reimporting_invoices_creates_no_duplicates(empty_db):
    files = [("parcelada.xml", _read("nfe_parcelada.xml"))]
    with empty_db.begin() as session:
        import_invoices(session, files)
    with empty_db.begin() as session:
        again = import_invoices(session, files * 2)  # also duplicated inside the batch
    assert (again.imported, again.duplicates, again.suppliers_created) == (0, 4, 0)
    with empty_db() as session:
        assert _count(session, Invoice) == 2
        assert _count(session, Supplier) == 1


def test_existing_supplier_is_reused_and_registration_moves_back(empty_db):
    with empty_db.begin() as session:
        session.add(
            Supplier(
                supplier_id="S1",
                name="Acme",
                tax_id="45.997.418/0001-53",
                registered_at=date(2025, 6, 1),
            )
        )
    with empty_db.begin() as session:
        summary = import_invoices(session, [("n.xml", _read("nfe_parcelada.xml"))])
    assert summary.suppliers_created == 0
    with empty_db() as session:
        supplier = session.get(Supplier, "S1")
        assert supplier.registered_at == date(2025, 3, 5)
        assert {i.supplier_id for i in session.scalars(select(Invoice))} == {"S1"}


def test_unreadable_invoice_file_is_an_error_and_others_import(empty_db):
    files = [("notas.pdf", b"%PDF"), ("notas.csv", _read("notas.csv"))]
    with empty_db.begin() as session:
        summary = import_invoices(session, files)
    assert summary.imported == 3
    assert summary.errors[0].startswith("notas.pdf: formato não suportado")
    assert "CNPJ inválido" in summary.errors[1]
