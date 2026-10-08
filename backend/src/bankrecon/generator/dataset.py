"""Dataset orchestration and CSV persistence."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from bankrecon.calendar import add_months
from bankrecon.generator.anomalies import AnomalyInjector
from bankrecon.generator.config import GeneratorConfig
from bankrecon.generator.invoices import generate_invoices
from bankrecon.generator.profiles import build_profiles
from bankrecon.generator.statement import build_statement

LIST_SEPARATOR = ";"

SUPPLIERS_FILE = "suppliers.csv"
INVOICES_FILE = "invoices.csv"
TRANSACTIONS_FILE = "bank_transactions.csv"
TRUTH_DIR = "ground_truth"
TRUTH_TRANSACTIONS_FILE = "transactions.csv"
TRUTH_PROFILES_FILE = "supplier_profiles.csv"

_DATE_COLUMNS = {
    SUPPLIERS_FILE: ["registered_at"],
    INVOICES_FILE: ["issue_date"],
    TRANSACTIONS_FILE: ["date"],
}


@dataclass(frozen=True)
class Dataset:
    """What the system sees (suppliers, invoices, transactions) plus the hidden ground truth.

    ``ground_truth`` has one row per transaction with the real supplier, the invoices it
    pays (``;``-separated, empty for duplicates), the noise applied and the anomaly type.
    ``supplier_profiles`` holds the generator's hidden parameters and must never feed the
    reconciliation or the anomaly detector.
    """

    suppliers: pd.DataFrame
    invoices: pd.DataFrame
    transactions: pd.DataFrame
    ground_truth: pd.DataFrame
    supplier_profiles: pd.DataFrame

    def save(self, directory: Path) -> None:
        truth_dir = directory / TRUTH_DIR
        truth_dir.mkdir(parents=True, exist_ok=True)
        self.suppliers.to_csv(directory / SUPPLIERS_FILE, index=False)
        self.invoices.to_csv(directory / INVOICES_FILE, index=False)
        self.transactions.to_csv(directory / TRANSACTIONS_FILE, index=False)
        self.ground_truth.to_csv(truth_dir / TRUTH_TRANSACTIONS_FILE, index=False)
        self.supplier_profiles.to_csv(truth_dir / TRUTH_PROFILES_FILE, index=False)

    @classmethod
    def load(cls, directory: Path) -> Dataset:
        def read(name: str) -> pd.DataFrame:
            return pd.read_csv(directory / name, parse_dates=_DATE_COLUMNS.get(name, []))

        truth_dir = directory / TRUTH_DIR
        return cls(
            suppliers=read(SUPPLIERS_FILE),
            invoices=read(INVOICES_FILE),
            transactions=read(TRANSACTIONS_FILE),
            ground_truth=pd.read_csv(
                truth_dir / TRUTH_TRANSACTIONS_FILE, keep_default_na=False, dtype=str
            ),
            supplier_profiles=pd.read_csv(truth_dir / TRUTH_PROFILES_FILE),
        )


def generate_dataset(config: GeneratorConfig | None = None) -> Dataset:
    """Generate a full, reproducible dataset: the same config always yields the same data."""
    config = config or GeneratorConfig()
    rng = np.random.default_rng(config.seed)
    start = config.start
    end = add_months(start, config.months) - timedelta(days=1)

    profiles = build_profiles(rng, config.n_suppliers, start, config.n_late_registered_suppliers)
    invoices = generate_invoices(profiles, rng, start, end)
    payments = build_statement(profiles, invoices, config.noise, rng)
    AnomalyInjector(
        rng, profiles=profiles, invoices=invoices, payments=payments, start=start, end=end
    ).inject(config.anomalies_per_type)

    payments.sort(key=lambda p: (p.date, p.supplier_id, p.amount))
    transaction_ids = [f"TX{i:05d}" for i in range(1, len(payments) + 1)]

    suppliers = pd.DataFrame(
        {
            "supplier_id": [p.supplier_id for p in profiles],
            "name": [p.name for p in profiles],
            "tax_id": [p.tax_id for p in profiles],
            "registered_at": pd.to_datetime([p.registered_at for p in profiles]),
        }
    )
    invoice_frame = pd.DataFrame(
        {
            "invoice_id": [inv.invoice_id for inv in invoices],
            "supplier_id": [inv.supplier_id for inv in invoices],
            "issue_date": pd.to_datetime([inv.issue_date for inv in invoices]),
            "amount": [inv.amount for inv in invoices],
        }
    )
    transactions = pd.DataFrame(
        {
            "transaction_id": transaction_ids,
            "date": pd.to_datetime([p.date for p in payments]),
            "amount": [p.amount for p in payments],
            "description": [p.description for p in payments],
        }
    )
    ground_truth = pd.DataFrame(
        {
            "transaction_id": transaction_ids,
            "supplier_id": [p.supplier_id for p in payments],
            "invoice_ids": [LIST_SEPARATOR.join(p.invoice_ids) for p in payments],
            "noise": [LIST_SEPARATOR.join(n.value for n in p.noise) for p in payments],
            "anomaly_type": [str(p.anomaly or "") for p in payments],
        }
    )
    supplier_profiles = pd.DataFrame([asdict(p) for p in profiles])
    for column in ("frequency", "payment_method"):
        supplier_profiles[column] = supplier_profiles[column].map(str)

    return Dataset(suppliers, invoice_frame, transactions, ground_truth, supplier_profiles)
