"""Runs reconciliation and anomaly detection over what is in the database.

Called after every import. Matches decided by an analyst are kept as they are: those
transactions and their invoices are left out of the new reconciliation. Every other match
is recomputed, and the anomaly ranking is recomputed for all transactions, so reviews and
new data are reflected in the scores.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session

from bankrecon.anomalies import detect_anomalies
from bankrecon.db.models import (
    DECIDED_BY_ANALYST,
    AnomalyScore,
    BankTransaction,
    Invoice,
    Match,
    Supplier,
    match_invoices,
)
from bankrecon.db.rows import insert_matches, insert_scores
from bankrecon.reconciliation import reconcile
from bankrecon.schema import join_list, split_list


@dataclass(frozen=True)
class ProcessSummary:
    transactions: int
    reconciled_now: int
    kept_reviews: int
    high_risk: int


def _frames(session: Session) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Suppliers, invoices and transactions in the engine's format (column selects only)."""
    suppliers = pd.DataFrame(
        session.execute(select(Supplier.supplier_id, Supplier.name, Supplier.registered_at)).all(),
        columns=["supplier_id", "name", "registered_at"],
    )
    invoices = pd.DataFrame(
        session.execute(
            select(
                Invoice.invoice_id,
                Invoice.supplier_id,
                # Payments are expected around the due date when the invoice has one...
                func.coalesce(Invoice.due_date, Invoice.issue_date),
                # ...and may come as early as the issue date (a boleto paid in advance).
                Invoice.issue_date,
                Invoice.amount,
            )
        ).all(),
        columns=["invoice_id", "supplier_id", "issue_date", "earliest_date", "amount"],
    )
    transactions = pd.DataFrame(
        session.execute(
            select(
                BankTransaction.transaction_id,
                BankTransaction.date,
                BankTransaction.amount,
                BankTransaction.description,
            ).order_by(BankTransaction.date, BankTransaction.transaction_id)
        ).all(),
        columns=["transaction_id", "date", "amount", "description"],
    )
    for frame, column in ((suppliers, "registered_at"), (invoices, "issue_date"),
                          (invoices, "earliest_date"), (transactions, "date")):  # fmt: skip
        frame[column] = pd.to_datetime(frame[column])
    for frame in (invoices, transactions):
        frame["amount"] = frame["amount"].astype(float)
    return suppliers, invoices, transactions


MATCH_COLUMNS = ["transaction_id", "status", "layer", "confidence", "invoice_ids", "supplier_id"]


def _analyst_matches(session: Session) -> pd.DataFrame:
    """Matches decided by an analyst, in the reconciliation output format (one query)."""
    rows: dict[str, dict] = {}
    query = (
        select(
            Match.transaction_id,
            Match.status,
            Match.layer,
            Match.confidence,
            Match.supplier_id,
            match_invoices.c.invoice_id,
        )
        .outerjoin(match_invoices, match_invoices.c.transaction_id == Match.transaction_id)
        .where(Match.decided_by == DECIDED_BY_ANALYST)
    )
    for tx_id, status, layer, confidence, supplier_id, invoice_id in session.execute(query):
        row = rows.setdefault(
            tx_id,
            {
                "transaction_id": tx_id,
                "status": status,
                "layer": layer,
                "confidence": confidence,
                "invoice_ids": [],
                "supplier_id": supplier_id or "",
            },
        )
        if invoice_id is not None:
            row["invoice_ids"].append(invoice_id)
    for row in rows.values():
        row["invoice_ids"] = join_list(sorted(row["invoice_ids"]))
    return pd.DataFrame(list(rows.values()), columns=MATCH_COLUMNS).astype({"layer": "Int64"})


# Arbitrary constant identifying the processing lock in Postgres.
POSTGRES_PROCESSING_LOCK_ID = 7_204_118_302


def _lock(session: Session) -> None:
    """Serialize concurrent reprocessing (two uploads, or an upload and a manual run).

    Postgres gets a transaction-scoped advisory lock; SQLite allows a single writer.
    """
    if session.get_bind().dialect.name == "postgresql":
        session.execute(
            text("SELECT pg_advisory_xact_lock(:id)"), {"id": POSTGRES_PROCESSING_LOCK_ID}
        )


def process(session: Session) -> ProcessSummary:
    """Recompute system matches and anomaly scores; runs in the caller's transaction."""
    _lock(session)
    suppliers, invoices, transactions = _frames(session)
    kept = _analyst_matches(session)
    reviewed = set(kept["transaction_id"])
    taken = {i for ids in kept["invoice_ids"] for i in split_list(ids)}

    pending = transactions[~transactions["transaction_id"].isin(reviewed)]
    open_invoices = invoices[~invoices["invoice_id"].isin(taken)]
    new = (
        reconcile(pending, open_invoices, suppliers)
        if not pending.empty
        else pd.DataFrame(columns=MATCH_COLUMNS)
    )

    # Replace every system decision; analyst decisions stay.
    system_ids = select(Match.transaction_id).where(Match.decided_by != DECIDED_BY_ANALYST)
    session.execute(delete(match_invoices).where(match_invoices.c.transaction_id.in_(system_ids)))
    session.execute(delete(Match).where(Match.decided_by != DECIDED_BY_ANALYST))
    insert_matches(session, new)

    session.execute(delete(AnomalyScore))
    high_risk = 0
    if not transactions.empty:
        matches = pd.concat([kept, new], ignore_index=True) if not kept.empty else new
        scores = detect_anomalies(transactions, matches, suppliers)
        high_risk = int(scores["high_risk"].sum())
        insert_scores(session, scores)
    session.flush()
    return ProcessSummary(
        transactions=len(transactions),
        reconciled_now=len(new),
        kept_reviews=len(kept),
        high_risk=high_risk,
    )
