"""Bank statement construction: turns invoices into payments and adds real-world noise."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from enum import StrEnum

import numpy as np

from bankrecon.calendar import roll_forward
from bankrecon.generator.config import NoiseConfig
from bankrecon.generator.invoices import Invoice
from bankrecon.generator.profiles import Frequency, SupplierProfile
from bankrecon.text import normalize

# Banks cap the counterparty field; a plain cut keeps the name as a prefix.
DESCRIPTION_MAX_LEN = 32
LATE_PAYMENT_DAYS = (6, 20)
BANK_FEES = (2.50, 3.90, 7.50, 10.00, 12.90)
MULTI_INVOICE_GROUP = {Frequency.WEEKLY: (2, 4), Frequency.MONTHLY: (2, 2)}
_STOPWORDS = {"DE", "DA", "DO", "DOS", "DAS", "E"}
_ABBREVIATIONS = {"LTDA": "LT", "EIRELI": "EI"}


class NoiseType(StrEnum):
    LATE_PAYMENT = "late_payment"
    BANK_FEE = "bank_fee"
    MULTI_INVOICE = "multi_invoice"
    TRUNCATED_DESCRIPTION = "truncated_description"


@dataclass
class Payment:
    """A bank statement line plus the ground truth about where it came from."""

    date: date
    amount: float
    description: str
    supplier_id: str
    invoice_ids: list[str]
    noise: list[NoiseType] = field(default_factory=list)
    anomaly: str | None = None

    @property
    def is_clean(self) -> bool:
        return not self.noise and self.anomaly is None and len(self.invoice_ids) == 1


def bank_description(profile: SupplierProfile) -> str:
    """Description as the bank prints it: method plus name cut to the field size."""
    return f"{profile.payment_method.value} {normalize(profile.name)}"[
        :DESCRIPTION_MAX_LEN
    ].rstrip()


def abbreviated_description(profile: SupplierProfile, rng: np.random.Generator) -> str:
    """Harder variant where every word is abbreviated, e.g. ``PIX ACME LOGIST LT``."""
    words = []
    for word in normalize(profile.name).split():
        if word in _STOPWORDS:
            continue
        if word in _ABBREVIATIONS:
            words.append(_ABBREVIATIONS[word])
        else:
            words.append(word[: int(rng.integers(4, 7))])
    return f"{profile.payment_method.value} {' '.join(words)}"[:DESCRIPTION_MAX_LEN].rstrip()


def _group_invoices(
    invoices: list[Invoice],
    profile: SupplierProfile,
    rng: np.random.Generator,
    probability: float,
) -> list[list[Invoice]]:
    """Split one supplier's invoices into payment groups; most groups have one invoice."""
    sizes = MULTI_INVOICE_GROUP.get(profile.frequency)
    groups: list[list[Invoice]] = []
    i = 0
    while i < len(invoices):
        size = 1
        if sizes and rng.random() < probability:
            size = int(rng.integers(sizes[0], sizes[1] + 1))
        groups.append(invoices[i : i + size])
        i += size
    return groups


def build_statement(
    profiles: list[SupplierProfile],
    invoices: list[Invoice],
    noise: NoiseConfig,
    rng: np.random.Generator,
    end: date,
) -> list[Payment]:
    """One payment per invoice (or per group of invoices), with noise applied.

    No payment is dated after ``end``: a late payment that would leave the period is
    paid on schedule instead.
    """
    by_supplier: dict[str, list[Invoice]] = {p.supplier_id: [] for p in profiles}
    for invoice in invoices:
        by_supplier[invoice.supplier_id].append(invoice)

    payments: list[Payment] = []
    for profile in profiles:
        own = sorted(by_supplier[profile.supplier_id], key=lambda inv: inv.scheduled_payment)
        for group in _group_invoices(own, profile, rng, noise.multi_invoice):
            payments.append(_make_payment(profile, group, noise, rng, end))
    return payments


def _make_payment(
    profile: SupplierProfile,
    group: list[Invoice],
    noise: NoiseConfig,
    rng: np.random.Generator,
    end: date,
) -> Payment:
    applied: list[NoiseType] = []
    if len(group) > 1:
        applied.append(NoiseType.MULTI_INVOICE)

    pay_date = max(inv.scheduled_payment for inv in group)
    if rng.random() < noise.late_payment:
        late = roll_forward(pay_date + timedelta(days=int(rng.integers(*LATE_PAYMENT_DAYS))))
        if late <= end:
            pay_date = late
            applied.append(NoiseType.LATE_PAYMENT)

    amount = round(sum(inv.amount for inv in group), 2)
    if rng.random() < noise.bank_fee:
        fee = float(rng.choice(BANK_FEES))
        if amount > fee * 10:
            amount = round(amount - fee, 2)
            applied.append(NoiseType.BANK_FEE)

    if rng.random() < noise.truncated_description:
        description = abbreviated_description(profile, rng)
        applied.append(NoiseType.TRUNCATED_DESCRIPTION)
    else:
        description = bank_description(profile)

    return Payment(
        date=pay_date,
        amount=amount,
        description=description,
        supplier_id=profile.supplier_id,
        invoice_ids=[inv.invoice_id for inv in group],
        noise=applied,
    )
