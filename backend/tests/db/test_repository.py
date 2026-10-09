import pytest
from sqlalchemy import select

from bankrecon.db import repository
from bankrecon.db.models import Match, match_invoices
from bankrecon.db.repository import (
    InvalidReviewError,
    SortOrder,
    TransactionFilter,
    TransactionNotFoundError,
)
from bankrecon.reconciliation.models import MatchStatus


def _first_with_status(pipeline, status):
    return pipeline.matches.loc[pipeline.matches["status"] == status, "transaction_id"].iloc[0]


def test_summary_matches_pipeline(session_factory, pipeline):
    with session_factory() as session:
        result = repository.summary(session)
    counts = pipeline.matches["status"].value_counts()
    assert result.total == len(pipeline.matches)
    assert result.reconciled == counts["conciliada"]
    assert result.suggested == counts["sugerida"]
    assert result.unmatched == counts["divergente"]
    assert result.high_risk == pipeline.scores["high_risk"].sum()


def test_default_listing_is_by_risk_and_paginated(session_factory, pipeline):
    with session_factory() as session:
        page, total = repository.list_transactions(session, TransactionFilter(limit=10))
    assert total == len(pipeline.matches)
    assert [t.anomaly.rank for t in page] == list(range(1, 11))


def test_offset(session_factory):
    with session_factory() as session:
        page, _ = repository.list_transactions(session, TransactionFilter(limit=5, offset=5))
    assert [t.anomaly.rank for t in page] == list(range(6, 11))


@pytest.mark.parametrize("status", list(MatchStatus))
def test_filter_by_status(session_factory, pipeline, status):
    with session_factory() as session:
        page, total = repository.list_transactions(
            session, TransactionFilter(status=status, limit=1000)
        )
    assert total == (pipeline.matches["status"] == status.value).sum()
    assert {t.match.status for t in page} <= {status.value}


def test_filter_by_score(session_factory, pipeline):
    with session_factory() as session:
        _, top10 = repository.list_transactions(session, TransactionFilter(max_percentile=0.1))
        page, high = repository.list_transactions(
            session, TransactionFilter(high_risk_only=True, limit=1000)
        )
    assert top10 == (pipeline.scores["percentile"] <= 0.1).sum()
    assert high == pipeline.scores["high_risk"].sum()
    assert all(t.anomaly.high_risk for t in page)


def test_search_by_description_or_id(session_factory, pipeline):
    tx = pipeline.dataset.transactions.iloc[3]
    with session_factory() as session:
        _, by_id = repository.list_transactions(
            session, TransactionFilter(search=tx.transaction_id.lower())
        )
        page, _ = repository.list_transactions(
            session, TransactionFilter(search=tx.description[:12], limit=1000)
        )
    assert by_id == 1
    assert tx.transaction_id in {t.transaction_id for t in page}


@pytest.mark.parametrize("sort", list(SortOrder))
def test_sort_orders(session_factory, sort):
    with session_factory() as session:
        page, _ = repository.list_transactions(session, TransactionFilter(sort=sort, limit=50))
    if sort is SortOrder.DATE:
        dates = [t.date for t in page]
        assert dates == sorted(dates, reverse=True)
    elif sort is SortOrder.AMOUNT:
        amounts = [t.amount for t in page]
        assert amounts == sorted(amounts, reverse=True)


def test_get_transaction_includes_invoices_and_reasons(session_factory, pipeline):
    tx_id = pipeline.scores.sort_values("rank")["transaction_id"].iloc[0]
    with session_factory() as session:
        transaction = repository.get_transaction(session, tx_id)
    assert transaction.anomaly.rank == 1
    assert transaction.anomaly.reasons


def test_get_unknown_transaction(session_factory):
    with session_factory() as session, pytest.raises(TransactionNotFoundError):
        repository.get_transaction(session, "TX99999")


def test_approve_suggestion(session_factory, pipeline):
    tx_id = _first_with_status(pipeline, "sugerida")
    with session_factory.begin() as session:
        repository.approve(session, tx_id)
    with session_factory() as session:
        match = session.get(Match, tx_id)
        assert match.status == "conciliada"
        assert match.decided_by == "analista"
        assert match.decided_at is not None
        assert match.invoices


def test_reject_suggestion_releases_invoices(session_factory, pipeline):
    tx_id = _first_with_status(pipeline, "sugerida")
    with session_factory.begin() as session:
        repository.reject(session, tx_id)
    with session_factory() as session:
        match = session.get(Match, tx_id)
        assert match.status == "divergente"
        assert match.layer is None
        assert match.decided_by == "analista"
        links = session.execute(
            select(match_invoices).where(match_invoices.c.transaction_id == tx_id)
        ).all()
        assert links == []


@pytest.mark.parametrize("action", [repository.approve, repository.reject])
def test_only_suggestions_can_be_reviewed(session_factory, pipeline, action):
    tx_id = _first_with_status(pipeline, "conciliada")
    with session_factory() as session, pytest.raises(InvalidReviewError, match="conciliada"):
        action(session, tx_id)


@pytest.mark.parametrize("action", [repository.approve, repository.reject])
def test_review_unknown_transaction(session_factory, action):
    with session_factory() as session, pytest.raises(TransactionNotFoundError):
        action(session, "TX99999")
