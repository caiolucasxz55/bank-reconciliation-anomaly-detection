"""Anomaly injection. Every injected anomaly is recorded on its payment for the ground truth."""

from __future__ import annotations

from collections import Counter
from dataclasses import replace
from datetime import date, timedelta
from enum import StrEnum

import numpy as np

from bankrecon.calendar import SATURDAY, roll_forward
from bankrecon.generator.invoices import Invoice
from bankrecon.generator.profiles import Frequency, SupplierProfile, build_profiles
from bankrecon.generator.statement import Payment, bank_description

DUPLICATE_MAX_DELAY_DAYS = 3
OUTLIER_FACTOR = (3.0, 6.0)
OUTLIER_MIN_SUPPLIER_PAYMENTS = 6
NEW_SUPPLIER_QUANTILE = 0.95
NEW_SUPPLIER_FACTOR = (1.5, 3.0)
NEW_SUPPLIER_MAX_AGE_DAYS = 10
NEW_SUPPLIER_WARMUP_DAYS = 30
ATYPICAL_WEEKEND_SHARE = 0.6
OFF_CYCLE_MONTHLY_SHIFT = (8, 15)


class AnomalyType(StrEnum):
    DUPLICATE_PAYMENT = "duplicate_payment"
    AMOUNT_OUTLIER = "amount_outlier"
    NEW_SUPPLIER_HIGH_VALUE = "new_supplier_high_value"
    ATYPICAL_DAY = "atypical_day"


class AnomalyInjector:
    """Mutates a clean statement in place, picking each target payment at most once."""

    def __init__(
        self,
        rng: np.random.Generator,
        *,
        profiles: list[SupplierProfile],
        invoices: list[Invoice],
        payments: list[Payment],
        start: date,
        end: date,
    ) -> None:
        self.rng = rng
        self.profiles = profiles
        self.invoices = invoices
        self.payments = payments
        self.start = start
        self.end = end
        self._profile_by_id = {p.supplier_id: p for p in profiles}
        self._invoice_by_id = {inv.invoice_id: inv for inv in invoices}
        self._used: set[int] = set()

    def inject(self, per_type: int) -> None:
        # The new-supplier threshold is taken from the untouched amount distribution.
        reference_amounts = [p.amount for p in self.payments]
        self._amount_outliers(per_type)
        self._duplicates(per_type)
        self._atypical_days(per_type)
        self._new_suppliers(per_type, reference_amounts)

    def _pick(self, eligible: list[int], count: int) -> list[int]:
        candidates = [i for i in eligible if i not in self._used]
        if len(candidates) < count:
            raise ValueError(f"not enough clean payments to inject {count} anomalies")
        picked = [int(i) for i in self.rng.choice(candidates, size=count, replace=False)]
        self._used.update(picked)
        return sorted(picked)

    def _clean_indices(self, frequencies: set[Frequency]) -> list[int]:
        return [
            i
            for i, p in enumerate(self.payments)
            if p.is_clean and self._profile_by_id[p.supplier_id].frequency in frequencies
        ]

    def _amount_outliers(self, count: int) -> None:
        sizes = Counter(p.supplier_id for p in self.payments)
        eligible = [
            i
            for i in self._clean_indices(set(Frequency))
            if sizes[self.payments[i].supplier_id] >= OUTLIER_MIN_SUPPLIER_PAYMENTS
        ]
        for i in self._pick(eligible, count):
            payment = self.payments[i]
            invoice = self._invoice_by_id[payment.invoice_ids[0]]
            invoice.amount = round(invoice.amount * float(self.rng.uniform(*OUTLIER_FACTOR)), 2)
            payment.amount = invoice.amount
            payment.anomaly = AnomalyType.AMOUNT_OUTLIER

    def _duplicates(self, count: int) -> None:
        for i in self._pick(self._clean_indices(set(Frequency)), count):
            original = self.payments[i]
            delay = timedelta(days=int(self.rng.integers(0, DUPLICATE_MAX_DELAY_DAYS + 1)))
            self.payments.append(
                replace(
                    original,
                    date=roll_forward(original.date + delay),
                    invoice_ids=[],
                    noise=[],
                    anomaly=AnomalyType.DUPLICATE_PAYMENT,
                )
            )
            # The original stays a regular payment but must not be reused as a target.
            self._used.add(len(self.payments) - 1)

    def _atypical_days(self, count: int) -> None:
        eligible = self._clean_indices({Frequency.WEEKLY, Frequency.MONTHLY})
        for i in self._pick(eligible, count):
            payment = self.payments[i]
            if self.rng.random() < ATYPICAL_WEEKEND_SHARE:
                target_weekday = SATURDAY + int(self.rng.integers(0, 2))
                shift = (target_weekday - payment.date.weekday()) % 7 or 7
                payment.date += timedelta(days=shift)
            else:
                payment.date = self._off_cycle(payment)
            payment.anomaly = AnomalyType.ATYPICAL_DAY

    def _off_cycle(self, payment: Payment) -> date:
        profile = self._profile_by_id[payment.supplier_id]
        if profile.frequency is Frequency.MONTHLY:
            shift = int(self.rng.integers(*OFF_CYCLE_MONTHLY_SHIFT))
            return roll_forward(payment.date + timedelta(days=shift))
        # Weekly: pay on another weekday of the same week.
        assert profile.payment_day is not None
        other_days = [d for d in range(5) if d != profile.payment_day]
        weekday = int(self.rng.choice(other_days))
        return payment.date + timedelta(days=weekday - payment.date.weekday())

    def _new_suppliers(self, count: int, reference_amounts: list[float]) -> None:
        if count == 0:
            return
        threshold = float(np.quantile(reference_amounts, NEW_SUPPLIER_QUANTILE))
        new_profiles = build_profiles(
            self.rng, count, self.start, n_late_registered=0, id_offset=len(self.profiles)
        )
        taken = {p.name for p in self.profiles}
        next_invoice = len(self.invoices) + 1
        for draft in new_profiles:
            pay_date = self._random_business_day(
                self.start + timedelta(days=NEW_SUPPLIER_WARMUP_DAYS)
            )
            amount = round(threshold * float(self.rng.uniform(*NEW_SUPPLIER_FACTOR)), 2)
            age = int(self.rng.integers(0, NEW_SUPPLIER_MAX_AGE_DAYS + 1))
            name = draft.name if draft.name not in taken else f"{draft.name} {draft.supplier_id}"
            taken.add(name)
            profile = replace(
                draft,
                name=name,
                frequency=Frequency.SPORADIC,
                payment_day=None,
                mean_amount=amount,
                registered_at=pay_date - timedelta(days=age),
            )
            self.profiles.append(profile)
            self._profile_by_id[profile.supplier_id] = profile

            invoice = Invoice(
                invoice_id=f"NF{next_invoice:05d}",
                supplier_id=profile.supplier_id,
                issue_date=max(profile.registered_at, pay_date - timedelta(days=2)),
                amount=amount,
                scheduled_payment=pay_date,
            )
            next_invoice += 1
            self.invoices.append(invoice)
            self.payments.append(
                Payment(
                    date=pay_date,
                    amount=amount,
                    description=bank_description(profile),
                    supplier_id=profile.supplier_id,
                    invoice_ids=[invoice.invoice_id],
                    anomaly=AnomalyType.NEW_SUPPLIER_HIGH_VALUE,
                )
            )

    def _random_business_day(self, earliest: date) -> date:
        """Business day in [earliest, end]; assumes the period has at least one."""
        span = (self.end - earliest).days
        day = roll_forward(earliest + timedelta(days=int(self.rng.integers(0, span + 1))))
        return day if day <= self.end else roll_forward(earliest)
