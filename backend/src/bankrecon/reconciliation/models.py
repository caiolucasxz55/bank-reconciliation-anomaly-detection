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
    # Layer 1: same amount, same supplier, paid at most this many days after the invoice.
    exact_max_days: int = 5
    # Paying up to this many days before the due date is normal and costs no confidence.
    early_free_days: int = 10
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
    # Layer 2 candidates below this confidence are discarded instead of suggested, so weak
    # coincidences do not consume invoices that a later layer needs.
    tolerant_min_confidence: float = 0.5
    # A runner-up candidate this close to the best one makes the match ambiguous.
    ambiguity_margin: float = 0.05
    multi_max_invoices: int = 4
    # Oldest open invoices considered per supplier by layer 3 (bounds the combinatorics).
    multi_max_candidates: int = 12

    def __post_init__(self) -> None:
        for name in ("name_min_score", "auto_confirm_confidence", "tolerant_min_confidence"):
            if not 0 < getattr(self, name) <= 1:
                raise ValueError(f"{name} must be in (0, 1]")
        if not 0 <= self.exact_max_days <= self.tolerant_max_days <= self.multi_max_days:
            raise ValueError("day windows must satisfy 0 <= exact <= tolerant <= multi")
        if self.early_free_days < 0:
            raise ValueError("early_free_days must be >= 0")
        if self.fee_tolerance < 0:
            raise ValueError("fee_tolerance must be >= 0")
        if not 0 <= self.ambiguity_margin < 1:
            raise ValueError("ambiguity_margin must be in [0, 1)")
        if self.multi_max_invoices < 2:
            raise ValueError("multi_max_invoices must be >= 2")
        if self.multi_max_candidates < self.multi_max_invoices:
            raise ValueError("multi_max_candidates must be >= multi_max_invoices")


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
