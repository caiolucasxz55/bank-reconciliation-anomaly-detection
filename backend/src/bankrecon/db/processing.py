"""Runs reconciliation and anomaly detection over what is in the database.

Called after every import. Matches decided by an analyst are kept as they are: those
transactions and their invoices are left out of the new reconciliation. Every other match
is recomputed, and the anomaly ranking is recomputed for all transactions, so reviews and
new data are reflected in the scores.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

import pandas as pd
from sqlalchemy import delete, insert, select
from sqlalchemy.orm import Session

from bankrecon.anomalies import detect_anomalies
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
from bankrecon.reconciliation import reconcile
from bankrecon.schema import join_list, split_list


@dataclass(frozen=True)
class ProcessSummary:
    transactions: int
    reconciled_now: int
    kept_reviews: int
    high_risk: int


def _frames(session: Session) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    suppliers = pd.DataFrame(
        session.execute(select(Supplier.supplier_id, Supplier.name, Supplier.registered_at)).all(),
        columns=["supplier_id", "name", "registered_at"],
    )
    invoices = pd.DataFrame(
        [
            (inv.invoice_id, inv.supplier_id, inv.reference_date, float(inv.amount))
            for inv in session.scalars(select(Invoice))
        ],
        # The engine calls it issue_date: the date payments are expected around.
        columns=["invoice_id", "supplier_id", "issue_date", "amount"],
    )
    transactions = pd.DataFrame(
        [
            (tx.transaction_id, tx.date, float(tx.amount), tx.description)
            for tx in session.scalars(select(BankTransaction).order_by(BankTransaction.date))
        ],
        columns=["transaction_id", "date", "amount", "description"],
    )
    for frame, column in ((suppliers, "registered_at"), (invoices, "issue_date"),
                          (transactions, "date")):  # fmt: skip
        frame[column] = pd.to_datetime(frame[column])
    return suppliers, invoices, transactions


def _analyst_matches(session: Session) -> pd.DataFrame:
    """Matches decided by an analyst, in the reconciliation output format."""
    links: dict[str, list[str]] = defaultdict(list)
    for tx_id, invoice_id in session.execute(
        select(match_invoices.c.transaction_id, match_invoices.c.invoice_id)
        .join(Match, Match.transaction_id == match_invoices.c.transaction_id)
        .where(Match.decided_by == DECIDED_BY_ANALYST)
    ):
        links[tx_id].append(invoice_id)
    rows = [
        {
            "transaction_id": m.transaction_id,
            "status": m.status,
            "layer": m.layer,
            "confidence": m.confidence,
            "invoice_ids": join_list(links[m.transaction_id]),
            "supplier_id": m.supplier_id or "",
        }
        for m in session.scalars(select(Match).where(Match.decided_by == DECIDED_BY_ANALYST))
    ]
    columns = ["transaction_id", "status", "layer", "confidence", "invoice_ids", "supplier_id"]
    return pd.DataFrame(rows, columns=columns).astype({"layer": "Int64"})


def process(session: Session) -> ProcessSummary:
    """Recompute system matches and anomaly scores; runs in the caller's transaction."""
    suppliers, invoices, transactions = _frames(session)
    kept = _analyst_matches(session)
    reviewed = set(kept["transaction_id"])
    taken = {i for ids in kept["invoice_ids"] for i in split_list(ids)}

    pending = transactions[~transactions["transaction_id"].isin(reviewed)]
    open_invoices = invoices[~invoices["invoice_id"].isin(taken)]
    new = (
        reconcile(pending, open_invoices, suppliers) if not pending.empty else kept.iloc[0:0].copy()
    )

    # Replace every system decision; analyst decisions stay.
    system_ids = select(Match.transaction_id).where(Match.decided_by != DECIDED_BY_ANALYST)
    session.execute(delete(match_invoices).where(match_invoices.c.transaction_id.in_(system_ids)))
    session.execute(delete(Match).where(Match.decided_by != DECIDED_BY_ANALYST))
    if not new.empty:
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
                for r in new.itertuples(index=False)
            ],
        )
        links = [
            {"transaction_id": r.transaction_id, "invoice_id": invoice_id}
            for r in new.itertuples(index=False)
            for invoice_id in split_list(r.invoice_ids)
        ]
        if links:
            session.execute(insert(match_invoices), links)

    session.execute(delete(AnomalyScore))
    high_risk = 0
    if not transactions.empty:
        matches = pd.concat([kept, new], ignore_index=True)
        scores = detect_anomalies(transactions, matches, suppliers)
        high_risk = int(scores["high_risk"].sum())
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
    session.flush()
    return ProcessSummary(
        transactions=len(transactions),
        reconciled_now=len(new),
        kept_reviews=len(kept),
        high_risk=high_risk,
    )
