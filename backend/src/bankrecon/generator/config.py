"""Generator configuration."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass(frozen=True)
class NoiseConfig:
    """Probability of each real-world imperfection being applied to a payment."""

    late_payment: float = 0.08
    bank_fee: float = 0.08
    multi_invoice: float = 0.06
    truncated_description: float = 0.12

    def __post_init__(self) -> None:
        for name, value in vars(self).items():
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be a probability, got {value}")


# Anomalies need some payment history around them (supplier averages, a warm-up before new
# suppliers appear), so shorter periods are rejected up front.
MIN_MONTHS = 3


@dataclass(frozen=True)
class GeneratorConfig:
    seed: int = 42
    start: date = date(2025, 1, 1)
    months: int = 12
    n_suppliers: int = 30
    n_late_registered_suppliers: int = 3
    anomalies_per_type: int = 8
    noise: NoiseConfig = field(default_factory=NoiseConfig)

    def __post_init__(self) -> None:
        if self.months < MIN_MONTHS:
            raise ValueError(f"months must be >= {MIN_MONTHS}")
        if self.n_suppliers < 4:
            raise ValueError("n_suppliers must be >= 4")
        if not 0 <= self.n_late_registered_suppliers < self.n_suppliers:
            raise ValueError("n_late_registered_suppliers must be in [0, n_suppliers)")
        if self.anomalies_per_type < 0:
            raise ValueError("anomalies_per_type must be >= 0")
