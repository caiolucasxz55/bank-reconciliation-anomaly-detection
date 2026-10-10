"""Relational model: imported data, the pipeline's outputs and the analyst's decisions."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    MetaData,
    Numeric,
    String,
    Table,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

MONEY = Numeric(14, 2)
# Who made the current decision on a match.
DECIDED_BY_SYSTEM = "sistema"
DECIDED_BY_ANALYST = "analista"

# Kinds of imported files.
IMPORT_STATEMENT = "extrato"
IMPORT_INVOICES = "notas"

# Deterministic constraint names, so migrations are reproducible on every database.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class ImportBatch(Base):
    """One imported file and what happened to its rows."""

    __tablename__ = "imports"

    import_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(16))
    filename: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    imported: Mapped[int] = mapped_column(default=0)
    duplicates: Mapped[int] = mapped_column(default=0)
    # Rows deliberately left out, e.g. credits in a bank statement.
    skipped: Mapped[int] = mapped_column(default=0)
    errors: Mapped[list[str]] = mapped_column(JSON, default=list)


class Supplier(Base):
    __tablename__ = "suppliers"

    supplier_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    # Formatted CNPJ (00.000.000/0000-00); unique so imports can find existing suppliers.
    tax_id: Mapped[str] = mapped_column(String(18), unique=True)
    registered_at: Mapped[date] = mapped_column(Date)


class Invoice(Base):
    __tablename__ = "invoices"

    # NF-e access key (44 digits) or "<CNPJ digits>-<number>" for CSV imports.
    invoice_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    number: Mapped[str | None] = mapped_column(String(32))
    supplier_id: Mapped[str] = mapped_column(ForeignKey("suppliers.supplier_id"), index=True)
    issue_date: Mapped[date] = mapped_column(Date)
    # Installment due date; payments are matched around it when it is known.
    due_date: Mapped[date | None] = mapped_column(Date)
    amount: Mapped[Decimal] = mapped_column(MONEY)
    import_id: Mapped[int | None] = mapped_column(ForeignKey("imports.import_id"))

    supplier: Mapped[Supplier] = relationship()

    @property
    def reference_date(self) -> date:
        """Date payments are expected around: the due date, else the issue date."""
        return self.due_date or self.issue_date


class BankTransaction(Base):
    __tablename__ = "bank_transactions"

    # OFX FITID based or a content hash for CSV imports; reimports are recognized by it.
    transaction_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    date: Mapped[date] = mapped_column(Date, index=True)
    # Amount paid, always positive: only debits are imported.
    amount: Mapped[Decimal] = mapped_column(MONEY)
    description: Mapped[str] = mapped_column(String(255))
    import_id: Mapped[int | None] = mapped_column(ForeignKey("imports.import_id"))

    match: Mapped[Match | None] = relationship(back_populates="transaction")
    anomaly: Mapped[AnomalyScore | None] = relationship(back_populates="transaction")


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
