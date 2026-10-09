"""Loads a dataset and its pipeline results into the database."""

from __future__ import annotations

from decimal import Decimal

import pandas as pd
from sqlalchemy import delete, func, insert, select
from sqlalchemy.orm import Session

from bankrecon.db.models import (
    DECIDED_BY_ANALYST,
    DECIDED_BY_SYSTEM,
    AnomalyScore,
    BankTransaction,
    Invoice,
    Match,
    Supplier,
    match_invoices,
)
from bankrecon.schema import split_list

# Children first, so foreign keys are never violated while clearing.
_TABLES_IN_DELETE_ORDER = (
    match_invoices,
    AnomalyScore.__table__,
    Match.__table__,
    BankTransaction.__table__,
    Invoice.__table__,
    Supplier.__table__,
)


def _money(value: float) -> Decimal:
    return Decimal(str(round(float(value), 2)))


def _date(value) -> object:
    return pd.Timestamp(value).date()


class ReviewsWouldBeLostError(RuntimeError):
    """Reloading would erase decisions made by an analyst."""

    def __init__(self, count: int) -> None:
        super().__init__(f"o banco tem {count} revisões feitas por analistas")
        self.count = count


def is_loaded(session: Session) -> bool:
    return session.scalar(select(BankTransaction.transaction_id).limit(1)) is not None


def analyst_reviews(session: Session) -> int:
    return session.scalar(select(func.count()).where(Match.decided_by == DECIDED_BY_ANALYST)) or 0


def load_results(
    session: Session,
    *,
    suppliers: pd.DataFrame,
    invoices: pd.DataFrame,
    transactions: pd.DataFrame,
    matches: pd.DataFrame,
    scores: pd.DataFrame,
    discard_reviews: bool = False,
) -> None:
    """Replace everything in the database with this dataset and its results.

    Refuses (``ReviewsWouldBeLostError``) when analysts already approved or rejected
    suggestions, unless ``discard_reviews`` is set. Runs in the caller's transaction;
    nothing is visible until it commits.
    """
    if not discard_reviews and (count := analyst_reviews(session)):
        raise ReviewsWouldBeLostError(count)
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
    session.execute(
        insert(Match),
        [
            {
                "transaction_id": r.transaction_id,
                "status": r.status,
                "layer": None if pd.isna(r.layer) else int(r.layer),
                "confidence": float(r.confidence),
                "supplier_id": r.supplier_id or None,
                "decided_by": DECIDED_BY_SYSTEM,
            }
            for r in matches.itertuples(index=False)
        ],
    )
    links = [
        {"transaction_id": r.transaction_id, "invoice_id": invoice_id}
        for r in matches.itertuples(index=False)
        for invoice_id in split_list(r.invoice_ids)
    ]
    if links:
        session.execute(insert(match_invoices), links)
    session.execute(
        insert(AnomalyScore),
        [
            {
                "transaction_id": r.transaction_id,
                "score": float(r.score),
                "rank": int(r.rank),
                "percentile": float(r.percentile),
                "rank_label": r.rank_label,
                "high_risk": bool(r.high_risk),
                "reasons": split_list(r.reasons),
            }
            for r in scores.itertuples(index=False)
        ],
    )
