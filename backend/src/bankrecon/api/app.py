"""HTTP API over the reconciliation and anomaly results.

Run with ``uvicorn --factory bankrecon.api.app:create_app``. The database comes from
``DATABASE_URL``; allowed browser origins from ``CORS_ORIGINS`` (comma-separated).
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from bankrecon.api.schemas import (
    SummaryOut,
    TransactionDetailOut,
    TransactionOut,
    TransactionPage,
    TransactionQuery,
)
from bankrecon.db import repository
from bankrecon.db.repository import (
    InvalidReviewError,
    TransactionFilter,
    TransactionNotFoundError,
)
from bankrecon.db.session import create_schema, make_engine, make_session_factory

DEFAULT_CORS_ORIGINS = "http://localhost:3000"


def get_session(request: Request) -> Iterator[Session]:
    """One session per request, committed on success and rolled back on error."""
    factory: sessionmaker[Session] = request.app.state.session_factory
    with factory.begin() as session:
        yield session


SessionDep = Annotated[Session, Depends(get_session)]
router = APIRouter(prefix="/api")


@router.get("/health")
def health(session: SessionDep) -> dict[str, str]:
    session.execute(text("SELECT 1"))
    return {"status": "ok"}


@router.get("/summary")
def summary(session: SessionDep) -> SummaryOut:
    totals = repository.summary(session)
    return SummaryOut(
        total=totals.total,
        conciliadas=totals.reconciled,
        sugeridas=totals.suggested,
        divergentes=totals.unmatched,
        alto_risco=totals.high_risk,
    )


@router.get("/transactions")
def list_transactions(
    session: SessionDep, query: Annotated[TransactionQuery, Query()]
) -> TransactionPage:
    filters = TransactionFilter(
        status=query.status,
        max_percentile=query.max_percentile,
        high_risk_only=query.high_risk,
        search=query.q or None,
        sort=query.sort,
        limit=query.limit,
        offset=query.offset,
    )
    items, total = repository.list_transactions(session, filters)
    return TransactionPage(
        items=[TransactionOut.of(tx) for tx in items],
        total=total,
        limit=query.limit,
        offset=query.offset,
    )


def _detail(session: Session, transaction_id: str) -> TransactionDetailOut:
    try:
        return TransactionDetailOut.of(repository.get_transaction(session, transaction_id))
    except TransactionNotFoundError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "transação não encontrada") from error


@router.get("/transactions/{transaction_id}")
def get_transaction(session: SessionDep, transaction_id: str) -> TransactionDetailOut:
    return _detail(session, transaction_id)


def _review(session: Session, transaction_id: str, action) -> TransactionDetailOut:
    try:
        action(session, transaction_id)
    except TransactionNotFoundError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "transação não encontrada") from error
    except InvalidReviewError as error:
        raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error
    session.flush()
    session.expire_all()
    return _detail(session, transaction_id)


@router.post("/transactions/{transaction_id}/approve")
def approve(session: SessionDep, transaction_id: str) -> TransactionDetailOut:
    """Confirm a suggested match."""
    return _review(session, transaction_id, repository.approve)


@router.post("/transactions/{transaction_id}/reject")
def reject(session: SessionDep, transaction_id: str) -> TransactionDetailOut:
    """Refuse a suggested match; its invoices go back to open."""
    return _review(session, transaction_id, repository.reject)


def create_app(session_factory: sessionmaker[Session] | None = None) -> FastAPI:
    """Build the app; tests pass their own session factory."""
    if session_factory is None:
        engine = make_engine()
        session_factory = make_session_factory(engine)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        create_schema(app.state.session_factory.kw["bind"])
        yield

    app = FastAPI(
        title="Bank Reconciliation & Anomaly Detection",
        description="Conciliação de extrato com notas fiscais e transações incomuns para "
        "investigação humana. O score é uma posição no ranking, não uma probabilidade de fraude.",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.session_factory = session_factory
    origins = os.environ.get("CORS_ORIGINS", DEFAULT_CORS_ORIGINS).split(",")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in origins if o.strip()],
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )
    app.include_router(router)
    return app
