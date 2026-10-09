"""Relational model: the pipeline's inputs and outputs, plus the analyst's review decisions."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    Table,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

MONEY = Numeric(14, 2)
# Who made the current decision on a match.
DECIDED_BY_SYSTEM = "sistema"
DECIDED_BY_ANALYST = "analista"


class Base(DeclarativeBase):
    pass


class Supplier(Base):
    __tablename__ = "suppliers"

    supplier_id: Mapped[str] = mapped_column(String(16), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    tax_id: Mapped[str] = mapped_column(String(18))
    registered_at: Mapped[date] = mapped_column(Date)


class Invoice(Base):
    __tablename__ = "invoices"

    invoice_id: Mapped[str] = mapped_column(String(16), primary_key=True)
    supplier_id: Mapped[str] = mapped_column(ForeignKey("suppliers.supplier_id"), index=True)
    issue_date: Mapped[date] = mapped_column(Date)
    amount: Mapped[Decimal] = mapped_column(MONEY)

    supplier: Mapped[Supplier] = relationship()


class BankTransaction(Base):
    __tablename__ = "bank_transactions"

    transaction_id: Mapped[str] = mapped_column(String(16), primary_key=True)
    date: Mapped[date] = mapped_column(Date, index=True)
    amount: Mapped[Decimal] = mapped_column(MONEY)
    description: Mapped[str] = mapped_column(String(64))

    match: Mapped[Match] = relationship(back_populates="transaction")
    anomaly: Mapped[AnomalyScore] = relationship(back_populates="transaction")


# An invoice is settled by at most one transaction, hence the unique invoice_id.
match_invoices = Table(
    "match_invoices",
    Base.metadata,
    Column(
        "transaction_id",
        ForeignKey("matches.transaction_id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("invoice_id", ForeignKey("invoices.invoice_id"), primary_key=True, unique=True),
)


class Match(Base):
    """Reconciliation outcome of one transaction (status, layer and matched invoices)."""

    __tablename__ = "matches"

    transaction_id: Mapped[str] = mapped_column(
        ForeignKey("bank_transactions.transaction_id"), primary_key=True
    )
    status: Mapped[str] = mapped_column(String(12), index=True)
    layer: Mapped[int | None]
    confidence: Mapped[float]
    # Supplier the description resolves to; set even when no invoice matched.
    supplier_id: Mapped[str | None] = mapped_column(ForeignKey("suppliers.supplier_id"))
    decided_by: Mapped[str] = mapped_column(String(16), default=DECIDED_BY_SYSTEM)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    transaction: Mapped[BankTransaction] = relationship(back_populates="match")
    supplier: Mapped[Supplier | None] = relationship()
    invoices: Mapped[list[Invoice]] = relationship(
        secondary=match_invoices, order_by=Invoice.issue_date
    )


class AnomalyScore(Base):
    __tablename__ = "anomaly_scores"

    transaction_id: Mapped[str] = mapped_column(
        ForeignKey("bank_transactions.transaction_id"), primary_key=True
    )
    score: Mapped[float]
    rank: Mapped[int] = mapped_column(index=True)
    percentile: Mapped[float]
    rank_label: Mapped[str] = mapped_column(String(64))
    high_risk: Mapped[bool] = mapped_column(index=True)
    reasons: Mapped[list[str]] = mapped_column(JSON)

    transaction: Mapped[BankTransaction] = relationship(back_populates="anomaly")
