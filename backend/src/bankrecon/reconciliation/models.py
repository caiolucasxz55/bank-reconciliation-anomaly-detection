"""Reconciliation result types and configuration."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum, StrEnum


class MatchStatus(StrEnum):
    RECONCILED = "conciliada"
    SUGGESTED = "sugerida"
    UNMATCHED = "divergente"


class Layer(IntEnum):
    EXACT = 1
    TOLERANT = 2
    MULTI_INVOICE = 3


@dataclass(frozen=True)
class ReconciliationConfig:
    # Layer 1: same amount, same supplier, payment at most this many days from the invoice.
    exact_max_days: int = 5
    # Layers 2 and 3 accept later payments (delays, off-cycle payments).
    tolerant_max_days: int = 30
    # Two monthly invoices paid together and late can be ~55 days old.
    multi_max_days: int = 60
    # Largest bank fee that may have been deducted from the paid amount.
    fee_tolerance: float = 15.0
    # Minimum rapidfuzz similarity (0-1) for a description to point at a supplier.
    name_min_score: float = 0.6
    # Layer 2/3 matches at or above this confidence are reconciled without human review.
    auto_confirm_confidence: float = 0.85
    # A runner-up candidate this close to the best one makes the match ambiguous.
    ambiguity_margin: float = 0.05
    multi_max_invoices: int = 4
    multi_max_candidates: int = 12

    def __post_init__(self) -> None:
        if not 0 < self.name_min_score <= 1:
            raise ValueError("name_min_score must be in (0, 1]")
        if not 0 < self.auto_confirm_confidence <= 1:
            raise ValueError("auto_confirm_confidence must be in (0, 1]")
        if not self.exact_max_days <= self.tolerant_max_days <= self.multi_max_days:
            raise ValueError("day windows must satisfy exact <= tolerant <= multi")
        if self.multi_max_invoices < 2:
            raise ValueError("multi_max_invoices must be >= 2")


@dataclass(frozen=True)
class Match:
    """Outcome for one bank transaction."""

    transaction_id: str
    status: MatchStatus
    invoice_ids: tuple[str, ...] = ()
    layer: Layer | None = None
    confidence: float = 0.0
    # Supplier the description points to, even when no invoice matched.
    supplier_id: str | None = None
