"""Queries and review actions used by the API."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session, joinedload, selectinload

from bankrecon.db.models import AnomalyScore, BankTransaction, Match
from bankrecon.reconciliation.models import MatchStatus

ANALYST = "analista"


class TransactionNotFoundError(LookupError):
    pass


class InvalidReviewError(ValueError):
    """Only suggested matches can be approved or rejected."""


class SortOrder(StrEnum):
    RISK = "risco"
    DATE = "data"
    AMOUNT = "valor"


@dataclass(frozen=True)
class Summary:
    total: int
    reconciled: int
    suggested: int
    unmatched: int
    high_risk: int


@dataclass(frozen=True)
class TransactionFilter:
    status: MatchStatus | None = None
    # Keep only the top share of the ranking, e.g. 0.05 for the 5% most unusual.
    max_percentile: float | None = None
    high_risk_only: bool = False
    search: str | None = None
    sort: SortOrder = SortOrder.RISK
    limit: int = 50
    offset: int = 0


def summary(session: Session) -> Summary:
    counts = dict(session.execute(select(Match.status, func.count()).group_by(Match.status)).all())
    high_risk = session.scalar(
        select(func.count()).select_from(AnomalyScore).where(AnomalyScore.high_risk)
    )
    return Summary(
        total=sum(counts.values()),
        reconciled=counts.get(MatchStatus.RECONCILED.value, 0),
        suggested=counts.get(MatchStatus.SUGGESTED.value, 0),
        unmatched=counts.get(MatchStatus.UNMATCHED.value, 0),
        high_risk=high_risk or 0,
    )


def _filtered(query: Select, filters: TransactionFilter) -> Select:
    if filters.status is not None:
        query = query.where(Match.status == filters.status.value)
    if filters.max_percentile is not None:
        query = query.where(AnomalyScore.percentile <= filters.max_percentile)
    if filters.high_risk_only:
        query = query.where(AnomalyScore.high_risk)
    if filters.search:
        pattern = f"%{filters.search.strip()}%"
        query = query.where(
            BankTransaction.description.ilike(pattern)
            | BankTransaction.transaction_id.ilike(pattern)
        )
    return query


_ORDER = {
    SortOrder.RISK: (AnomalyScore.rank.asc(),),
    SortOrder.DATE: (BankTransaction.date.desc(), BankTransaction.transaction_id.desc()),
    SortOrder.AMOUNT: (BankTransaction.amount.desc(), BankTransaction.transaction_id),
}


def list_transactions(
    session: Session, filters: TransactionFilter
) -> tuple[list[BankTransaction], int]:
    """One page of transactions matching ``filters`` and the total number of matches."""
    base = _filtered(
        select(BankTransaction).join(BankTransaction.match).join(BankTransaction.anomaly),
        filters,
    )
    total = session.scalar(select(func.count()).select_from(base.subquery())) or 0
    page = (
        base.options(
            joinedload(BankTransaction.match).joinedload(Match.supplier),
            joinedload(BankTransaction.anomaly),
        )
        .order_by(*_ORDER[filters.sort])
        .limit(filters.limit)
        .offset(filters.offset)
    )
    return list(session.scalars(page).unique()), total


def get_transaction(session: Session, transaction_id: str) -> BankTransaction:
    transaction = session.scalar(
        select(BankTransaction)
        .where(BankTransaction.transaction_id == transaction_id)
        .options(
            joinedload(BankTransaction.match).joinedload(Match.supplier),
            joinedload(BankTransaction.match).selectinload(Match.invoices),
            joinedload(BankTransaction.anomaly),
        )
    )
    if transaction is None:
        raise TransactionNotFoundError(transaction_id)
    return transaction


def _suggested_match(session: Session, transaction_id: str) -> Match:
    match = session.scalar(
        select(Match)
        .where(Match.transaction_id == transaction_id)
        .options(selectinload(Match.invoices))
        .with_for_update()
    )
    if match is None:
        raise TransactionNotFoundError(transaction_id)
    if match.status != MatchStatus.SUGGESTED.value:
        raise InvalidReviewError(
            f"a transação {transaction_id} está '{match.status}'; só sugestões podem ser revisadas"
        )
    return match


def approve(session: Session, transaction_id: str) -> None:
    """Confirm a suggested match: it becomes reconciled, decided by the analyst."""
    match = _suggested_match(session, transaction_id)
    match.status = MatchStatus.RECONCILED.value
    match.decided_by = ANALYST
    match.decided_at = datetime.now(UTC)


def reject(session: Session, transaction_id: str) -> None:
    """Refuse a suggested match: its invoices go back to open and it becomes unmatched."""
    match = _suggested_match(session, transaction_id)
    match.invoices.clear()
    match.status = MatchStatus.UNMATCHED.value
    match.layer = None
    match.confidence = 0.0
    match.decided_by = ANALYST
    match.decided_at = datetime.now(UTC)
