"""Response models of the HTTP API."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from bankrecon.db.models import BankTransaction, ImportBatch, Invoice
from bankrecon.db.processing import ProcessSummary
from bankrecon.db.repository import SortOrder
from bankrecon.reconciliation.models import MatchStatus

MAX_PAGE_SIZE = 200


class TransactionQuery(BaseModel):
    """Query parameters of the transaction listing."""

    model_config = ConfigDict(extra="forbid")

    status: MatchStatus | None = None
    # Keep only the top share of the ranking (0.05 = the 5% most unusual).
    max_percentile: float | None = Field(default=None, gt=0, le=1)
    high_risk: bool = False
    q: str | None = Field(default=None, max_length=64)
    sort: SortOrder = SortOrder.RISK
    limit: int = Field(default=50, ge=1, le=MAX_PAGE_SIZE)
    offset: int = Field(default=0, ge=0)


class SummaryOut(BaseModel):
    total: int
    conciliadas: int
    sugeridas: int
    divergentes: int
    alto_risco: int


class InvoiceOut(BaseModel):
    invoice_id: str
    issue_date: date
    amount: float

    @classmethod
    def of(cls, invoice: Invoice) -> InvoiceOut:
        return cls(
            invoice_id=invoice.invoice_id,
            issue_date=invoice.issue_date,
            amount=float(invoice.amount),
        )


class TransactionOut(BaseModel):
    transaction_id: str
    date: date
    amount: float
    description: str
    status: MatchStatus
    layer: int | None
    confidence: float
    supplier_id: str | None
    supplier_name: str | None
    score: float
    rank: int
    rank_label: str
    high_risk: bool
    # The most distinctive reason, for the list; the detail has all of them.
    top_reason: str | None

    @classmethod
    def of(cls, tx: BankTransaction) -> TransactionOut:
        match, anomaly = tx.match, tx.anomaly
        return cls(
            transaction_id=tx.transaction_id,
            date=tx.date,
            amount=float(tx.amount),
            description=tx.description,
            status=MatchStatus(match.status),
            layer=match.layer,
            confidence=match.confidence,
            supplier_id=match.supplier_id,
            supplier_name=match.supplier.name if match.supplier else None,
            score=anomaly.score,
            rank=anomaly.rank,
            rank_label=anomaly.rank_label,
            high_risk=anomaly.high_risk,
            top_reason=anomaly.reasons[0] if anomaly.reasons else None,
        )


class TransactionDetailOut(TransactionOut):
    reasons: list[str]
    invoices: list[InvoiceOut]
    decided_by: str
    decided_at: datetime | None
    can_review: bool

    @classmethod
    def of(cls, tx: BankTransaction) -> TransactionDetailOut:
        return cls(
            **TransactionOut.of(tx).model_dump(),
            reasons=tx.anomaly.reasons,
            invoices=[InvoiceOut.of(inv) for inv in tx.match.invoices],
            decided_by=tx.match.decided_by,
            decided_at=tx.match.decided_at,
            can_review=tx.match.status == MatchStatus.SUGGESTED.value,
        )


class TransactionPage(BaseModel):
    items: list[TransactionOut]
    total: int
    limit: int
    offset: int


class ImportOut(BaseModel):
    import_id: int
    kind: str
    filename: str
    created_at: datetime
    imported: int
    duplicates: int
    skipped: int
    errors: list[str]

    @classmethod
    def of(cls, batch: ImportBatch) -> ImportOut:
        return cls(
            import_id=batch.import_id,
            kind=batch.kind,
            filename=batch.filename,
            created_at=batch.created_at,
            imported=batch.imported,
            duplicates=batch.duplicates,
            skipped=batch.skipped,
            errors=batch.errors,
        )


class ProcessOut(BaseModel):
    transactions: int
    kept_reviews: int
    high_risk: int

    @classmethod
    def of(cls, summary: ProcessSummary) -> ProcessOut:
        return cls(
            transactions=summary.transactions,
            kept_reviews=summary.kept_reviews,
            high_risk=summary.high_risk,
        )


class ImportResultOut(ImportOut):
    suppliers_created: int
    processed: ProcessOut
