"""Writes pipeline output frames (matches, anomaly scores) as database rows."""

from __future__ import annotations

import pandas as pd
from sqlalchemy import insert
from sqlalchemy.orm import Session

from bankrecon.db.models import DECIDED_BY_SYSTEM, AnomalyScore, Match, match_invoices
from bankrecon.schema import split_list


def insert_matches(session: Session, matches: pd.DataFrame) -> None:
    """Reconciliation output (one row per transaction) as system decisions and links."""
    if matches.empty:
        return
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


def insert_scores(session: Session, scores: pd.DataFrame) -> None:
    """Anomaly detection output (one row per transaction)."""
    if scores.empty:
        return
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
