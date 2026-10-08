import pytest

from bankrecon.calendar import is_weekend
from bankrecon.generator.anomalies import OUTLIER_FACTOR, AnomalyType
from bankrecon.generator.dataset import LIST_SEPARATOR


@pytest.fixture(scope="module")
def frame(dataset):
    merged = dataset.ground_truth.merge(dataset.transactions, on="transaction_id")
    return merged.merge(
        dataset.supplier_profiles[["supplier_id", "frequency", "mean_amount", "payment_day"]],
        on="supplier_id",
    )


def _of(frame, anomaly):
    rows = frame[frame["anomaly_type"] == anomaly.value]
    assert len(rows) == 8
    return rows


def test_anomalies_are_injected_on_clean_payments(frame):
    anomalous = frame[frame["anomaly_type"] != ""]
    assert (anomalous["noise"] == "").all()


def test_duplicates_repeat_an_existing_payment_without_invoice(frame):
    for row in _of(frame, AnomalyType.DUPLICATE_PAYMENT).itertuples():
        assert row.invoice_ids == ""
        same = frame[
            (frame["supplier_id"] == row.supplier_id)
            & (frame["amount"] == row.amount)
            & (frame["transaction_id"] != row.transaction_id)
        ]
        assert ((row.date - same["date"]).dt.days.between(0, 5)).any()


def test_outliers_are_far_above_the_supplier_mean(frame):
    for row in _of(frame, AnomalyType.AMOUNT_OUTLIER).itertuples():
        assert row.amount / row.mean_amount > OUTLIER_FACTOR[0] * 0.6


def test_outlier_invoice_amount_matches_payment(dataset, frame):
    invoices = dataset.invoices.set_index("invoice_id")["amount"]
    for row in _of(frame, AnomalyType.AMOUNT_OUTLIER).itertuples():
        assert invoices[row.invoice_ids] == row.amount


def test_new_supplier_payments_are_high_and_unique(frame):
    rows = _of(frame, AnomalyType.NEW_SUPPLIER_HIGH_VALUE)
    regular = frame[frame["anomaly_type"] == ""]["amount"]
    assert (rows["amount"] > regular.quantile(0.9)).all()
    assert frame[frame["supplier_id"].isin(rows["supplier_id"])].shape[0] == 8


def test_atypical_days_are_weekends_or_off_cycle(frame):
    for row in _of(frame, AnomalyType.ATYPICAL_DAY).itertuples():
        day = row.date.date()
        if is_weekend(day):
            continue
        if row.frequency == "weekly":
            assert day.weekday() != row.payment_day
        else:
            assert abs(day.day - row.payment_day) >= 6


def test_regular_payments_never_fall_on_weekends(frame):
    regular = frame[frame["anomaly_type"] != AnomalyType.ATYPICAL_DAY.value]
    assert not regular["date"].map(lambda d: is_weekend(d.date())).any()


def test_invoice_ids_reference_existing_invoices(dataset):
    ids = set(dataset.invoices["invoice_id"])
    referenced = dataset.ground_truth["invoice_ids"].str.split(LIST_SEPARATOR).explode()
    assert set(referenced[referenced != ""]) <= ids
