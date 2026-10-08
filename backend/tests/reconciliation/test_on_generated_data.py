"""End-to-end checks of the reconciliation on generated data, scored against the ground truth."""

import pytest

from bankrecon.evaluation import evaluate_reconciliation
from bankrecon.reconciliation import reconcile


@pytest.fixture(scope="module")
def matches(dataset):
    return reconcile(dataset.transactions, dataset.invoices, dataset.suppliers)


def test_overall_accuracy(matches, dataset):
    report = evaluate_reconciliation(matches, dataset.ground_truth)
    assert report.accuracy >= 0.97


def test_exact_layer_is_never_wrong(matches, dataset):
    report = evaluate_reconciliation(matches, dataset.ground_truth)
    exact = report.by_layer.iloc[0]
    assert exact["Corretas"] == exact["Transações"]


def test_every_layer_is_used(matches):
    assert set(matches["layer"].dropna()) == {1, 2, 3}


def test_each_invoice_is_matched_at_most_once(matches):
    used = matches["invoice_ids"].str.split(";").explode()
    used = used[used != ""]
    assert used.is_unique


def test_duplicates_end_up_unmatched(matches, dataset):
    duplicates = dataset.ground_truth["anomaly_type"] == "duplicate_payment"
    assert (matches.loc[duplicates, "status"] == "divergente").mean() >= 0.75


def test_resolved_supplier_is_right_for_almost_every_transaction(matches, dataset):
    agree = matches["supplier_id"] == dataset.ground_truth["supplier_id"]
    assert agree.mean() >= 0.98
