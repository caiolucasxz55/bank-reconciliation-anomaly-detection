"""Supplier profiles: the hidden payment patterns the generator follows."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, timedelta
from enum import StrEnum

import numpy as np

from bankrecon.generator.names import generate_cnpj, generate_names


class Frequency(StrEnum):
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    SPORADIC = "sporadic"


class PaymentMethod(StrEnum):
    PIX = "PIX"
    TED = "TED"
    BOLETO = "PAG BOLETO"


# Share of suppliers per frequency and log-uniform range of their mean invoice amount (BRL).
FREQUENCY_SHARE = {Frequency.WEEKLY: 0.25, Frequency.MONTHLY: 0.5, Frequency.SPORADIC: 0.25}
MEAN_AMOUNT_RANGE = {
    Frequency.WEEKLY: (400.0, 6_000.0),
    Frequency.MONTHLY: (1_500.0, 45_000.0),
    Frequency.SPORADIC: (800.0, 30_000.0),
}
AMOUNT_CV_RANGE = (0.03, 0.25)
SPORADIC_MEAN_GAP_DAYS = 40


@dataclass(frozen=True)
class SupplierProfile:
    supplier_id: str
    name: str
    tax_id: str
    frequency: Frequency
    mean_amount: float
    amount_cv: float
    # Day of month (1-28) for monthly suppliers, weekday (0=Mon..4=Fri) for weekly ones.
    payment_day: int | None
    payment_method: PaymentMethod
    registered_at: date

    def draw_amount(self, rng: np.random.Generator) -> float:
        """Log-normal amount whose expected value is ``mean_amount``."""
        sigma = self.amount_cv
        value = self.mean_amount * math.exp(rng.normal(0.0, sigma) - sigma**2 / 2)
        return round(max(value, 10.0), 2)


def _frequencies(rng: np.random.Generator, count: int) -> list[Frequency]:
    weekly = round(count * FREQUENCY_SHARE[Frequency.WEEKLY])
    sporadic = round(count * FREQUENCY_SHARE[Frequency.SPORADIC])
    monthly = count - weekly - sporadic
    freqs = (
        [Frequency.WEEKLY] * weekly
        + [Frequency.MONTHLY] * monthly
        + [Frequency.SPORADIC] * sporadic
    )
    return [freqs[i] for i in rng.permutation(count)]


def _log_uniform(rng: np.random.Generator, low: float, high: float) -> float:
    return float(math.exp(rng.uniform(math.log(low), math.log(high))))


def _payment_day(rng: np.random.Generator, frequency: Frequency) -> int | None:
    if frequency is Frequency.MONTHLY:
        return int(rng.integers(1, 29))
    if frequency is Frequency.WEEKLY:
        return int(rng.integers(0, 5))
    return None


def build_profiles(
    rng: np.random.Generator,
    count: int,
    start: date,
    n_late_registered: int,
    id_offset: int = 0,
) -> list[SupplierProfile]:
    """Create ``count`` supplier profiles.

    Most suppliers were registered long before ``start``. ``n_late_registered`` legitimate,
    non-weekly suppliers are registered during the first months of the period so that
    "new supplier" alone is not an anomaly - only a new supplier with a high amount is.
    """
    names = generate_names(rng, count)
    frequencies = _frequencies(rng, count)
    late_candidates = [i for i, f in enumerate(frequencies) if f is not Frequency.WEEKLY]
    late = set(
        rng.choice(
            late_candidates, size=min(n_late_registered, len(late_candidates)), replace=False
        ).tolist()
    )

    profiles = []
    for i, (name, frequency) in enumerate(zip(names, frequencies, strict=True)):
        if i in late:
            registered_at = start + timedelta(days=int(rng.integers(60, 240)))
        else:
            registered_at = start - timedelta(days=int(rng.integers(60, 1500)))
        profiles.append(
            SupplierProfile(
                supplier_id=f"S{id_offset + i + 1:03d}",
                name=name,
                tax_id=generate_cnpj(rng),
                frequency=frequency,
                mean_amount=round(_log_uniform(rng, *MEAN_AMOUNT_RANGE[frequency]), 2),
                amount_cv=round(float(rng.uniform(*AMOUNT_CV_RANGE)), 3),
                payment_day=_payment_day(rng, frequency),
                payment_method=PaymentMethod(rng.choice(list(PaymentMethod))),
                registered_at=registered_at,
            )
        )
    return profiles
