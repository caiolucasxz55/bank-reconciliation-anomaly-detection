"""Imports real files into the database: bank statements and invoices.

Imports are idempotent: lines already in the database (same statement line, same NF-e
installment) are counted as duplicates and left untouched. Suppliers are registered from
the CNPJ on the invoices. Every import is recorded in the ``imports`` table.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from sqlalchemy import insert, select
from sqlalchemy.orm import Session

from bankrecon.cnpj import only_digits
from bankrecon.db.models import (
    IMPORT_INVOICES,
    IMPORT_STATEMENT,
    BankTransaction,
    ImportBatch,
    Invoice,
    Supplier,
)
from bankrecon.ingest import ParsedInvoice, ParseError, parse_invoice_file, parse_statement
from bankrecon.ingest.common import short_hash

# Error messages kept per import; the rest is summarized.
MAX_STORED_ERRORS = 50
FILENAME_MAX_LEN = 255


@dataclass
class ImportSummary:
    import_id: int
    kind: str
    filename: str
    imported: int = 0
    duplicates: int = 0
    # Lines deliberately left out: credits in a statement.
    skipped: int = 0
    errors: list[str] = field(default_factory=list)
    suppliers_created: int = 0
    files: int = 1
    # Files that yielded nothing but errors (unreadable, wrong format, cancelled NF-e...).
    files_failed: int = 0


def transaction_id(external_id: str) -> str:
    """Compact database id derived from the statement line's stable external id."""
    return "TX" + short_hash(external_id).upper()


def _start_batch(session: Session, kind: str, filename: str) -> ImportBatch:
    batch = ImportBatch(kind=kind, filename=filename[:FILENAME_MAX_LEN], errors=[])
    session.add(batch)
    session.flush()
    return batch


def _finish(session: Session, batch: ImportBatch, summary: ImportSummary) -> ImportSummary:
    if len(summary.errors) > MAX_STORED_ERRORS:
        hidden = len(summary.errors) - MAX_STORED_ERRORS
        summary.errors = [*summary.errors[:MAX_STORED_ERRORS], f"... e mais {hidden} erros"]
    batch.imported = summary.imported
    batch.duplicates = summary.duplicates
    batch.skipped = summary.skipped
    batch.errors = summary.errors
    session.flush()
    return summary


def import_statement(
    session: Session, filename: str, content: bytes, account: str = "conta"
) -> ImportSummary:
    """Import the payments (debits) of one statement file; credits are skipped.

    Raises ``ParseError`` when the file cannot be read at all; nothing is stored then.
    """
    parsed = parse_statement(filename, content, account)
    batch = _start_batch(session, IMPORT_STATEMENT, filename)
    summary = ImportSummary(batch.import_id, IMPORT_STATEMENT, batch.filename, errors=parsed.errors)

    payments = [line for line in parsed.rows if line.amount < 0]
    summary.skipped = len(parsed.rows) - len(payments)
    by_id = {transaction_id(line.external_id): line for line in payments}
    existing = set(
        session.scalars(
            select(BankTransaction.transaction_id).where(
                BankTransaction.transaction_id.in_(by_id.keys())
            )
        )
    )
    new = [
        {
            "transaction_id": tx_id,
            "date": line.date,
            "amount": -line.amount,
            "description": line.description,
            "import_id": batch.import_id,
        }
        for tx_id, line in by_id.items()
        if tx_id not in existing
    ]
    if new:
        session.execute(insert(BankTransaction), new)
    summary.imported = len(new)
    summary.duplicates = len(payments) - len(new)
    return _finish(session, batch, summary)


def _batch_name(filenames: list[str]) -> str:
    if len(filenames) == 1:
        return filenames[0]
    return f"{len(filenames)} arquivos: {', '.join(filenames)}"


def _upsert_suppliers(session: Session, invoices: list[ParsedInvoice]) -> tuple[dict, int]:
    """Supplier id per CNPJ, creating the missing suppliers. Returns (ids, created)."""
    earliest: dict[str, ParsedInvoice] = {}
    for invoice in invoices:
        known = earliest.get(invoice.supplier_tax_id)
        if known is None or invoice.issue_date < known.issue_date:
            earliest[invoice.supplier_tax_id] = invoice

    existing = {
        s.tax_id: s
        for s in session.scalars(select(Supplier).where(Supplier.tax_id.in_(earliest.keys())))
    }
    created = 0
    for tax_id, first in earliest.items():
        supplier = existing.get(tax_id)
        if supplier is None:
            # Real registration dates are unknown; the first invoice approximates them.
            supplier = Supplier(
                supplier_id=only_digits(tax_id),
                name=first.supplier_name or tax_id,
                tax_id=tax_id,
                registered_at=first.issue_date,
            )
            session.add(supplier)
            existing[tax_id] = supplier
            created += 1
        else:
            supplier.registered_at = min(supplier.registered_at, first.issue_date)
            if supplier.name == supplier.tax_id and first.supplier_name:
                supplier.name = first.supplier_name
    session.flush()
    return {tax_id: s.supplier_id for tax_id, s in existing.items()}, created


def import_invoices(session: Session, files: Iterable[tuple[str, bytes]]) -> ImportSummary:
    """Import invoices from one or more files (NF-e XML or CSV) as a single import.

    A file that cannot be read becomes an error message; the other files still import.
    """
    files = list(files)
    batch = _start_batch(session, IMPORT_INVOICES, _batch_name([name for name, _ in files]))
    summary = ImportSummary(batch.import_id, IMPORT_INVOICES, batch.filename, files=len(files))

    parsed: dict[str, ParsedInvoice] = {}
    for filename, content in files:
        try:
            result = parse_invoice_file(filename, content)
        except ParseError as error:
            summary.errors.append(f"{filename}: {error}")
            summary.files_failed += 1
            continue
        summary.errors.extend(result.errors)
        if not result.rows and result.errors:
            summary.files_failed += 1
        for invoice in result.rows:
            if invoice.invoice_id in parsed:
                summary.duplicates += 1
            else:
                parsed[invoice.invoice_id] = invoice

    existing = set(
        session.scalars(select(Invoice.invoice_id).where(Invoice.invoice_id.in_(parsed.keys())))
    )
    summary.duplicates += len(existing)
    new = [invoice for invoice_id, invoice in parsed.items() if invoice_id not in existing]
    supplier_ids, summary.suppliers_created = _upsert_suppliers(session, new)
    if new:
        session.execute(
            insert(Invoice),
            [
                {
                    "invoice_id": invoice.invoice_id,
                    "number": invoice.number,
                    "supplier_id": supplier_ids[invoice.supplier_tax_id],
                    "issue_date": invoice.issue_date,
                    "due_date": invoice.due_date,
                    "amount": invoice.amount,
                    "import_id": batch.import_id,
                }
                for invoice in new
            ],
        )
    summary.imported = len(new)
    return _finish(session, batch, summary)
