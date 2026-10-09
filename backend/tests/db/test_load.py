from decimal import Decimal

import pytest
from sqlalchemy import func, select

from bankrecon.db import repository
from bankrecon.db.load import ReviewsWouldBeLostError, is_loaded, load_results
from bankrecon.db.models import (
    AnomalyScore,
    BankTransaction,
    Invoice,
    Match,
    Supplier,
    match_invoices,
)
from bankrecon.db.session import create_schema, make_engine, make_session_factory


def _count(session, model):
    return session.scalar(select(func.count()).select_from(model))


def test_every_table_is_loaded(session_factory, pipeline):
    data = pipeline.dataset
    with session_factory() as session:
        assert is_loaded(session)
        assert _count(session, Supplier) == len(data.suppliers)
        assert _count(session, Invoice) == len(data.invoices)
        assert _count(session, BankTransaction) == len(data.transactions)
        assert _count(session, Match) == len(data.transactions)
        assert _count(session, AnomalyScore) == len(data.transactions)
        linked = pipeline.matches["invoice_ids"].str.split(";").explode()
        assert _count(session, match_invoices) == (linked != "").sum()


def test_values_survive_the_round_trip(session_factory, pipeline):
    tx = pipeline.dataset.transactions.iloc[0]
    match = pipeline.matches.iloc[0]
    score = pipeline.scores.iloc[0]
    with session_factory() as session:
        row = session.get(BankTransaction, tx.transaction_id)
        assert row.amount == Decimal(str(tx.amount))
        assert row.date == tx.date.date()
        assert row.match.status == match.status
        assert [inv.invoice_id for inv in row.match.invoices] == match.invoice_ids.split(";")
        assert row.match.decided_by == "sistema"
        assert row.anomaly.rank == score["rank"]
        assert row.anomaly.reasons == ([] if not score.reasons else score.reasons.split(";"))


def test_loading_twice_replaces_the_data(session_factory, pipeline):
    data = pipeline.dataset
    with session_factory.begin() as session:
        load_results(
            session,
            suppliers=data.suppliers,
            invoices=data.invoices,
            transactions=data.transactions,
            matches=pipeline.matches,
            scores=pipeline.scores,
        )
    with session_factory() as session:
        assert _count(session, BankTransaction) == len(data.transactions)


def test_empty_database_is_not_loaded():
    engine = make_engine("sqlite://")
    create_schema(engine)
    with make_session_factory(engine)() as session:
        assert not is_loaded(session)


def _reload(session_factory, pipeline, **kwargs):
    data = pipeline.dataset
    with session_factory.begin() as session:
        load_results(
            session,
            suppliers=data.suppliers,
            invoices=data.invoices,
            transactions=data.transactions,
            matches=pipeline.matches,
            scores=pipeline.scores,
            **kwargs,
        )


def test_reload_refuses_to_erase_analyst_reviews(session_factory, pipeline):
    tx_id = pipeline.matches.loc[pipeline.matches["status"] == "sugerida", "transaction_id"].iloc[0]
    with session_factory.begin() as session:
        repository.approve(session, tx_id)

    with pytest.raises(ReviewsWouldBeLostError) as info:
        _reload(session_factory, pipeline)
    assert info.value.count == 1
    with session_factory() as session:
        assert session.get(Match, tx_id).decided_by == "analista"

    _reload(session_factory, pipeline, discard_reviews=True)
    with session_factory() as session:
        assert session.get(Match, tx_id).decided_by == "sistema"
