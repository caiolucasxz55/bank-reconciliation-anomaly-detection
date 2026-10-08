from datetime import timedelta

import pandas as pd
import pytest

from bankrecon.generator import Dataset, GeneratorConfig, generate_dataset
from bankrecon.generator.anomalies import AnomalyType
from bankrecon.schema import LIST_SEPARATOR


def test_same_seed_generates_identical_data(dataset):
    again = generate_dataset(GeneratorConfig(seed=7))
    for name in ("suppliers", "invoices", "transactions", "ground_truth"):
        pd.testing.assert_frame_equal(getattr(dataset, name), getattr(again, name))


def test_different_seed_generates_different_data(dataset):
    other = generate_dataset(GeneratorConfig(seed=8))
    assert not dataset.transactions.equals(other.transactions)


def test_ground_truth_covers_every_transaction(dataset):
    assert list(dataset.ground_truth["transaction_id"]) == list(
        dataset.transactions["transaction_id"]
    )
    assert dataset.transactions["transaction_id"].is_unique


def test_every_invoice_is_paid_exactly_once(dataset):
    paid = [
        invoice_id
        for ids in dataset.ground_truth["invoice_ids"]
        if ids
        for invoice_id in ids.split(LIST_SEPARATOR)
    ]
    assert sorted(paid) == sorted(dataset.invoices["invoice_id"])


def test_anomaly_counts(dataset):
    counts = dataset.ground_truth["anomaly_type"].value_counts()
    for anomaly in AnomalyType:
        assert counts[anomaly.value] == 8


def test_twelve_months_of_data(dataset):
    dates = dataset.transactions["date"]
    assert dates.min() >= pd.Timestamp("2025-01-01")
    assert dates.max() <= pd.Timestamp("2026-01-31")
    assert dates.dt.month.nunique() == 12


def test_observable_tables_hide_generator_parameters(dataset):
    assert set(dataset.suppliers.columns) == {"supplier_id", "name", "tax_id", "registered_at"}
    assert set(dataset.transactions.columns) == {"transaction_id", "date", "amount", "description"}


def test_all_noise_types_present(dataset):
    noise = set(dataset.ground_truth["noise"].str.split(LIST_SEPARATOR).explode()) - {""}
    assert noise == {"late_payment", "bank_fee", "multi_invoice", "truncated_description"}


def test_save_and_load_round_trip(dataset, tmp_path):
    dataset.save(tmp_path)
    loaded = Dataset.load(tmp_path)
    pd.testing.assert_frame_equal(loaded.transactions, dataset.transactions, check_dtype=False)
    pd.testing.assert_frame_equal(loaded.invoices, dataset.invoices, check_dtype=False)
    pd.testing.assert_frame_equal(loaded.suppliers, dataset.suppliers, check_dtype=False)
    pd.testing.assert_frame_equal(loaded.ground_truth, dataset.ground_truth)


def test_new_suppliers_are_registered_right_before_payment(dataset):
    truth = dataset.ground_truth.merge(dataset.transactions, on="transaction_id")
    new = truth[truth["anomaly_type"] == AnomalyType.NEW_SUPPLIER_HIGH_VALUE]
    registered = dataset.suppliers.set_index("supplier_id")["registered_at"]
    for row in new.itertuples():
        age = row.date - registered[row.supplier_id]
        assert timedelta(0) <= age <= timedelta(days=10)


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"months": 2}, "months"),
        ({"n_suppliers": 2}, "n_suppliers"),
        ({"anomalies_per_type": -1}, "anomalies_per_type"),
    ],
)
def test_config_validation(kwargs, message):
    with pytest.raises(ValueError, match=message):
        GeneratorConfig(**kwargs)


@pytest.mark.parametrize("seed", range(12))
def test_invariants_hold_across_seeds(seed):
    data = generate_dataset(GeneratorConfig(seed=seed))
    dates = data.transactions["date"]
    assert dates.min() >= pd.Timestamp("2025-01-01")
    assert dates.max() <= pd.Timestamp("2025-12-31")

    issue = data.invoices.set_index("invoice_id")["issue_date"]
    truth = data.ground_truth.merge(data.transactions, on="transaction_id")
    for row in truth[truth["invoice_ids"] != ""].itertuples():
        latest_issue = max(issue[i] for i in row.invoice_ids.split(LIST_SEPARATOR))
        assert row.date >= latest_issue, row.transaction_id


def test_invoice_ids_follow_issue_order(dataset):
    invoices = dataset.invoices
    expected = [f"NF{i:05d}" for i in range(1, len(invoices) + 1)]
    assert list(invoices["invoice_id"]) == expected
    assert invoices["issue_date"].is_monotonic_increasing


def test_shortest_supported_period():
    data = generate_dataset(GeneratorConfig(months=3, start=pd.Timestamp("2025-02-01").date()))
    assert data.transactions["date"].max() <= pd.Timestamp("2025-04-30")


def test_supplier_profiles_round_trip(dataset, tmp_path):
    dataset.save(tmp_path)
    loaded = Dataset.load(tmp_path)
    pd.testing.assert_frame_equal(
        loaded.supplier_profiles, dataset.supplier_profiles, check_dtype=False
    )
    assert loaded.supplier_profiles["payment_day"].dtype == "Int64"
