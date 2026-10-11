"""Layered reconciliation of bank transactions against invoices.

Each layer only sees the transactions the previous ones left unresolved, from the most
reliable rule to the least reliable:

1. exact: same amount, same supplier (description is a prefix of its name), close dates;
2. tolerant: amount reduced by a bank fee and/or fuzzy supplier name and/or later payment;
3. multi-invoice: open invoices of one supplier whose sum equals the paid amount.

Each invoice has a reference date (``issue_date`` column: the due date when known) and
an earliest payment date (optional ``earliest_date`` column, default: the reference date).
A payment can match an invoice from its earliest date up to a few days after its reference
date, so a boleto paid before its due date still matches, while a payment is never matched
to an invoice issued after it.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from itertools import combinations

import pandas as pd

from bankrecon.reconciliation.models import Layer, Match, MatchStatus, ReconciliationConfig
from bankrecon.reconciliation.resolver import SupplierCandidate, SupplierResolver
from bankrecon.schema import join_list

# Weights of the layer 2/3 confidence score.
NAME_WEIGHT, AMOUNT_WEIGHT, DATE_WEIGHT = 0.5, 0.3, 0.2


@dataclass(frozen=True)
class _Transaction:
    transaction_id: str
    date: date
    cents: int
    description: str


@dataclass(frozen=True)
class _Invoice:
    invoice_id: str
    supplier_id: str
    issue_date: date  # reference date: payments are expected around it
    cents: int
    earliest: date  # no payment before this date can settle the invoice


@dataclass(frozen=True)
class _Candidate:
    confidence: float
    supplier_id: str
    invoices: tuple[_Invoice, ...]


def _to_cents(amount: float) -> int:
    return round(amount * 100)


class Reconciler:
    """Stateless entry point; every :meth:`run` works on its own :class:`_Run`."""

    def __init__(self, suppliers: pd.DataFrame, config: ReconciliationConfig | None = None):
        self.config = config or ReconciliationConfig()
        self.resolver = SupplierResolver(
            zip(suppliers["supplier_id"], suppliers["name"], strict=True)
        )

    def run(self, transactions: pd.DataFrame, invoices: pd.DataFrame) -> list[Match]:
        """Return one :class:`Match` per transaction, in the input order."""
        txs = [
            _Transaction(
                r.transaction_id, pd.Timestamp(r.date).date(), _to_cents(r.amount), r.description
            )
            for r in transactions.itertuples(index=False)
        ]
        has_earliest = "earliest_date" in invoices.columns
        open_invoices = []
        for r in invoices.sort_values(["issue_date", "invoice_id"]).itertuples(index=False):
            reference = pd.Timestamp(r.issue_date).date()
            earliest = pd.Timestamp(r.earliest_date).date() if has_earliest else reference
            open_invoices.append(
                _Invoice(
                    r.invoice_id,
                    r.supplier_id,
                    reference,
                    _to_cents(r.amount),
                    min(earliest, reference),
                )
            )
        results = _Run(self.config, self.resolver, open_invoices).execute(txs)
        return [results[tx.transaction_id] for tx in txs]


class _Run:
    """Working state of one reconciliation: open invoices, results and resolver cache."""

    def __init__(
        self,
        config: ReconciliationConfig,
        resolver: SupplierResolver,
        invoices: list[_Invoice],
    ) -> None:
        self.config = config
        self.resolver = resolver
        self.fee_cents = _to_cents(config.fee_tolerance)
        self.open: dict[str, list[_Invoice]] = defaultdict(list)
        for invoice in invoices:  # already in issue order
            self.open[invoice.supplier_id].append(invoice)
        self.results: dict[str, Match] = {}
        self._supplier_cache: dict[str, list[SupplierCandidate]] = {}

    def execute(self, txs: list[_Transaction]) -> dict[str, Match]:
        pending = sorted(txs, key=lambda t: (t.date, t.transaction_id))
        pending = self._exact_layer(pending)
        pending = self._tolerant_layer(pending)
        pending = self._multi_invoice_layer(pending)
        for tx in pending:
            best = self._suppliers(tx)
            self.results[tx.transaction_id] = Match(
                tx.transaction_id,
                MatchStatus.UNMATCHED,
                supplier_id=best[0].supplier_id if best else None,
            )
        return self.results

    # -- helpers ---------------------------------------------------------------------------

    def _suppliers(self, tx: _Transaction) -> list[SupplierCandidate]:
        cached = self._supplier_cache.get(tx.description)
        if cached is None:
            cached = self.resolver.candidates(tx.description, self.config.name_min_score)
            self._supplier_cache[tx.description] = cached
        return cached

    def _confidence(self, name_score: float, fee_cents: int, date_score: float) -> float:
        amount_score = 1.0 - fee_cents / (self.fee_cents + 1)
        return round(
            NAME_WEIGHT * name_score + AMOUNT_WEIGHT * amount_score + DATE_WEIGHT * date_score, 4
        )

    @staticmethod
    def _payable(tx: _Transaction, inv: _Invoice, max_days_late: int) -> bool:
        """Paid on or after the invoice's earliest date, at most ``max_days_late`` days
        after its reference date."""
        return inv.earliest <= tx.date and (tx.date - inv.issue_date).days <= max_days_late

    def _date_score(self, days: int) -> float:
        """1.0 within ``exact_max_days`` of the reference date, either side, then decreasing
        linearly: a boleto paid weeks before its due date is as unlikely a match as one paid
        weeks late, so the installment due nearest to the payment ranks first."""
        cfg = self.config
        off_days = max(0, abs(days) - cfg.exact_max_days)
        return max(0.0, 1.0 - off_days / (cfg.tolerant_max_days - cfg.exact_max_days + 1))

    def _status(self, confidence: float, ambiguous: bool) -> MatchStatus:
        if confidence >= self.config.auto_confirm_confidence and not ambiguous:
            return MatchStatus.RECONCILED
        return MatchStatus.SUGGESTED

    def _settle(
        self, tx: _Transaction, candidate: _Candidate, layer: Layer, status: MatchStatus
    ) -> None:
        for invoice in candidate.invoices:
            self.open[invoice.supplier_id].remove(invoice)
        self.results[tx.transaction_id] = Match(
            tx.transaction_id,
            status,
            tuple(inv.invoice_id for inv in candidate.invoices),
            layer,
            candidate.confidence,
            candidate.supplier_id,
        )

    # -- layers ----------------------------------------------------------------------------

    def _exact_layer(self, pending: list[_Transaction]) -> list[_Transaction]:
        left = []
        for tx in pending:
            supplier_id = self.resolver.exact(tx.description)
            open_invoices = self.open.get(supplier_id, []) if supplier_id else []
            matches = [
                inv
                for inv in open_invoices
                if inv.cents == tx.cents and self._payable(tx, inv, self.config.exact_max_days)
            ]
            if not matches:
                left.append(tx)
                continue
            best = min(
                matches, key=lambda inv: (abs((tx.date - inv.issue_date).days), inv.issue_date)
            )
            candidate = _Candidate(1.0, best.supplier_id, (best,))
            self._settle(tx, candidate, Layer.EXACT, MatchStatus.RECONCILED)
        return left

    def _tolerant_layer(self, pending: list[_Transaction]) -> list[_Transaction]:
        proposals: list[tuple[_Candidate, bool, _Transaction]] = []
        for tx in pending:
            ranked = sorted(self._tolerant_candidates(tx), key=lambda c: -c.confidence)
            if not ranked:
                continue
            ambiguous = (
                len(ranked) > 1
                and ranked[0].confidence - ranked[1].confidence < self.config.ambiguity_margin
            )
            proposals.append((ranked[0], ambiguous, tx))
            # Runner-ups let a transaction fall back if its best invoice is taken; such a
            # fallback is never auto-confirmed.
            proposals.extend((c, True, tx) for c in ranked[1:])

        settled: set[str] = set()
        taken: set[str] = set()
        proposals.sort(key=lambda p: (-p[0].confidence, p[2].date, p[2].transaction_id))
        for candidate, ambiguous, tx in proposals:
            invoice = candidate.invoices[0]
            if tx.transaction_id in settled or invoice.invoice_id in taken:
                continue
            settled.add(tx.transaction_id)
            taken.add(invoice.invoice_id)
            status = self._status(candidate.confidence, ambiguous)
            self._settle(tx, candidate, Layer.TOLERANT, status)
        return [tx for tx in pending if tx.transaction_id not in settled]

    def _tolerant_candidates(self, tx: _Transaction) -> list[_Candidate]:
        cfg = self.config
        out = []
        for supplier in self._suppliers(tx):
            for inv in self.open.get(supplier.supplier_id, []):
                days = (tx.date - inv.issue_date).days
                fee = inv.cents - tx.cents
                if not (
                    self._payable(tx, inv, cfg.tolerant_max_days) and 0 <= fee <= self.fee_cents
                ):
                    continue
                confidence = self._confidence(supplier.score, fee, self._date_score(days))
                if confidence >= cfg.tolerant_min_confidence:
                    out.append(_Candidate(confidence, supplier.supplier_id, (inv,)))
        return out

    def _multi_invoice_layer(self, pending: list[_Transaction]) -> list[_Transaction]:
        left = []
        for tx in pending:
            candidates = self._multi_candidates(tx)
            if not candidates:
                left.append(tx)
                continue
            # Highest confidence first; ties go to the oldest invoices, which is how open
            # invoices are usually settled.
            best = min(
                candidates,
                key=lambda c: (-c.confidence, [inv.issue_date for inv in c.invoices]),
            )
            # Several subsets adding up to the paid amount: a human has to pick.
            status = self._status(best.confidence, ambiguous=len(candidates) > 1)
            self._settle(tx, best, Layer.MULTI_INVOICE, status)
        return left

    def _multi_candidates(self, tx: _Transaction) -> list[_Candidate]:
        cfg = self.config
        out = []
        for supplier in self._suppliers(tx):
            window = [
                inv
                for inv in self.open.get(supplier.supplier_id, [])
                if self._payable(tx, inv, cfg.multi_max_days)
            ]
            # Safety bound on the combinatorial search; the window rarely holds this many.
            pool = window[: cfg.multi_max_candidates]
            for size in range(2, cfg.multi_max_invoices + 1):
                for combo in combinations(pool, size):
                    fee = sum(inv.cents for inv in combo) - tx.cents
                    if 0 <= fee <= self.fee_cents:
                        # The date window is already enforced; dates do not rank subsets.
                        confidence = self._confidence(supplier.score, fee, date_score=1.0)
                        out.append(_Candidate(confidence, supplier.supplier_id, combo))
        return out


def reconcile(
    transactions: pd.DataFrame,
    invoices: pd.DataFrame,
    suppliers: pd.DataFrame,
    config: ReconciliationConfig | None = None,
) -> pd.DataFrame:
    """Reconcile and return one row per transaction (see :func:`matches_to_frame`)."""
    return matches_to_frame(Reconciler(suppliers, config).run(transactions, invoices))


def matches_to_frame(matches: list[Match]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "transaction_id": [m.transaction_id for m in matches],
            "status": [m.status.value for m in matches],
            "layer": pd.array([m.layer.value if m.layer else None for m in matches], dtype="Int64"),
            "confidence": [m.confidence for m in matches],
            "invoice_ids": [join_list(m.invoice_ids) for m in matches],
            "supplier_id": [m.supplier_id or "" for m in matches],
        }
    )
