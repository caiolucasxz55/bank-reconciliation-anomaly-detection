"""Loads a synthetic dataset and its pipeline results into the database (demo, evaluation).

Real data goes through ``bankrecon.db.importer`` instead, which adds to what is there.
"""

from __future__ import annotations

from decimal import Decimal

import pandas as pd
from sqlalchemy import delete, func, insert, select
from sqlalchemy.orm import Session

from bankrecon.db.models import (
    DECIDED_BY_ANALYST,
    AnomalyScore,
    BankTransaction,
    ImportBatch,
    Invoice,
    Match,
    Supplier,
    match_invoices,
)
from bankrecon.db.rows import insert_matches, insert_scores

# Children first, so foreign keys are never violated while clearing.
_TABLES_IN_DELETE_ORDER = (
    match_invoices,
    AnomalyScore.__table__,
    Match.__table__,
    BankTransaction.__table__,
    Invoice.__table__,
    Supplier.__table__,
    ImportBatch.__table__,
)


def _money(value: float) -> Decimal:
    return Decimal(str(round(float(value), 2)))


def _date(value) -> object:
    return pd.Timestamp(value).date()


class DataWouldBeLostError(RuntimeError):
    """Reloading would erase analyst decisions or imported files."""

    def __init__(self, reviews: int, imports: int) -> None:
        parts = []
        if reviews:
            parts.append(f"{reviews} revisões feitas por analistas")
        if imports:
            parts.append(f"{imports} arquivos importados")
        super().__init__(f"o banco tem {' e '.join(parts)}")
        self.reviews = reviews
        self.imports = imports


def is_loaded(session: Session) -> bool:
    return session.scalar(select(BankTransaction.transaction_id).limit(1)) is not None


def analyst_reviews(session: Session) -> int:
    return session.scalar(select(func.count()).where(Match.decided_by == DECIDED_BY_ANALYST)) or 0


def imported_files(session: Session) -> int:
    return session.scalar(select(func.count()).select_from(ImportBatch)) or 0


def load_results(
    session: Session,
    *,
    suppliers: pd.DataFrame,
    invoices: pd.DataFrame,
    transactions: pd.DataFrame,
    matches: pd.DataFrame,
    scores: pd.DataFrame,
    replace_existing: bool = False,
) -> None:
    """Replace everything in the database with this dataset and its results.

    Refuses (``DataWouldBeLostError``) when the database holds analyst decisions or
    imported files, unless ``replace_existing`` is set. Runs in the caller's
    transaction; nothing is visible until it commits.
    """
    if not replace_existing:
        reviews, imports = analyst_reviews(session), imported_files(session)
        if reviews or imports:
            raise DataWouldBeLostError(reviews, imports)
    for table in _TABLES_IN_DELETE_ORDER:
        session.execute(delete(table))

    session.execute(
        insert(Supplier),
        [
            {
                "supplier_id": r.supplier_id,
                "name": r.name,
                "tax_id": r.tax_id,
                "registered_at": _date(r.registered_at),
            }
            for r in suppliers.itertuples(index=False)
        ],
    )
    session.execute(
        insert(Invoice),
        [
            {
                "invoice_id": r.invoice_id,
                "supplier_id": r.supplier_id,
                "issue_date": _date(r.issue_date),
                "amount": _money(r.amount),
            }
            for r in invoices.itertuples(index=False)
        ],
    )
    session.execute(
        insert(BankTransaction),
        [
            {
                "transaction_id": r.transaction_id,
                "date": _date(r.date),
                "amount": _money(r.amount),
                "description": r.description,
            }
            for r in transactions.itertuples(index=False)
        ],
    )
    insert_matches(session, matches)
    insert_scores(session, scores)
