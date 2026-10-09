"""Queries and review actions used by the API."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import Select, delete, func, select, update
from sqlalchemy.orm import Session, contains_eager, joinedload

from bankrecon.db.models import (
    DECIDED_BY_ANALYST,
    AnomalyScore,
    BankTransaction,
    Match,
    match_invoices,
)
from bankrecon.reconciliation.models import MatchStatus

LIKE_ESCAPE = "\\"


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


def _escape_like(text: str) -> str:
    """Make ``%`` and ``_`` in user input match literally."""
    for char in (LIKE_ESCAPE, "%", "_"):
        text = text.replace(char, LIKE_ESCAPE + char)
    return text


def _filtered(query: Select, filters: TransactionFilter) -> Select:
    if filters.status is not None:
        query = query.where(Match.status == filters.status.value)
    if filters.max_percentile is not None:
        query = query.where(AnomalyScore.percentile <= filters.max_percentile)
    if filters.high_risk_only:
        query = query.where(AnomalyScore.high_risk)
    if filters.search:
        pattern = f"%{_escape_like(filters.search.strip())}%"
        query = query.where(
            BankTransaction.description.ilike(pattern, escape=LIKE_ESCAPE)
            | BankTransaction.transaction_id.ilike(pattern, escape=LIKE_ESCAPE)
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
        # Reuse the joins already made for filtering instead of joining again.
        base.options(
            contains_eager(BankTransaction.match).joinedload(Match.supplier),
            contains_eager(BankTransaction.anomaly),
        )
        .order_by(*_ORDER[filters.sort])
        .limit(filters.limit)
        .offset(filters.offset)
    )
    return list(session.scalars(page)), total


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


def _claim_suggestion(session: Session, transaction_id: str, **values) -> None:
    """Atomically move a match out of 'sugerida' with one conditional UPDATE.

    Two concurrent reviews of the same suggestion cannot both succeed: the second one
    finds the status already changed and fails with ``InvalidReviewError``. This works
    the same on SQLite (which ignores ``SELECT ... FOR UPDATE``) and on Postgres.
    """
    result = session.execute(
        update(Match)
        .where(
            Match.transaction_id == transaction_id,
            Match.status == MatchStatus.SUGGESTED.value,
        )
        .values(decided_by=DECIDED_BY_ANALYST, decided_at=datetime.now(UTC), **values)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount == 1:
        return
    current = session.scalar(select(Match.status).where(Match.transaction_id == transaction_id))
    if current is None:
        raise TransactionNotFoundError(transaction_id)
    raise InvalidReviewError(
        f"a transação {transaction_id} está '{current}'; só sugestões podem ser revisadas"
    )


def approve(session: Session, transaction_id: str) -> None:
    """Confirm a suggested match: it becomes reconciled, decided by the analyst."""
    _claim_suggestion(session, transaction_id, status=MatchStatus.RECONCILED.value)


def reject(session: Session, transaction_id: str) -> None:
    """Refuse a suggested match: its invoices go back to open and it becomes unmatched."""
    _claim_suggestion(
        session,
        transaction_id,
        status=MatchStatus.UNMATCHED.value,
        layer=None,
        confidence=0.0,
    )
    session.execute(delete(match_invoices).where(match_invoices.c.transaction_id == transaction_id))
