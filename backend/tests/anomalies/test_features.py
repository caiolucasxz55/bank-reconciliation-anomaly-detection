import numpy as np
import pandas as pd
import pytest

from bankrecon.anomalies import MODEL_FEATURES, compute_features

SUPPLIERS = pd.DataFrame(
    {
        "supplier_id": ["W", "M", "N"],
        "name": ["Weekly", "Monthly", "New"],
        "registered_at": pd.to_datetime(["2020-01-01", "2020-01-01", "2025-06-01"]),
    }
)


def _frames(rows):
    """rows: (transaction_id, date, amount, supplier_id, invoice_ids)."""
    transactions = pd.DataFrame(
        {
            "transaction_id": [r[0] for r in rows],
            "date": pd.to_datetime([r[1] for r in rows]),
            "amount": [r[2] for r in rows],
            "description": [f"PIX {r[3] or 'DESCONHECIDO'}" for r in rows],
        }
    )
    matches = pd.DataFrame(
        {
            "transaction_id": [r[0] for r in rows],
            "supplier_id": [r[3] for r in rows],
            "invoice_ids": [r[4] for r in rows],
        }
    )
    return transactions, matches


def _weekly(n=8, amount=1000.0, start="2025-03-03"):
    dates = pd.date_range(start, periods=n, freq="7D")  # Mondays
    return [(f"W{i}", d, amount + i, "W", f"NF{i}") for i, d in enumerate(dates)]


def _features(rows):
    transactions, matches = _frames(rows)
    return compute_features(transactions, matches, SUPPLIERS).set_index("transaction_id")


def test_regular_weekly_payments_look_normal():
    features = _features(_weekly())
    assert set(MODEL_FEATURES) <= set(features.columns)
    assert (features["has_duplicate"] == 0).all()
    assert (features["is_weekend"] == 0).all()
    assert (features["off_cycle"] == 0).all()
    assert (features["is_new_supplier"] == 0).all()
    assert features["amount_ratio"].between(0.99, 1.01).all()
    assert (features["cycle"] == "weekly").all()


def test_amount_ratio_uses_other_payments_of_the_supplier():
    rows = _weekly()
    rows[3] = ("W3", rows[3][1], 5000.0, "W", "NF3")
    features = _features(rows)
    assert features.loc["W3", "amount_ratio"] == pytest.approx(5000 / 1004)
    assert features.loc["W3", "log_amount_ratio"] == pytest.approx(np.log(5000 / 1004))


def test_grouped_payment_amount_is_split_per_invoice():
    rows = _weekly()
    rows[3] = ("W3", rows[3][1], 2006.0, "W", "NF3;NF4")
    features = _features(rows)
    assert features.loc["W3", "amount_ratio"] == pytest.approx(1003 / 1004)


def test_only_the_later_payment_of_a_duplicate_pair_is_flagged():
    rows = [*_weekly(), ("DUP", "2025-03-05", 1000.0, "W", "")]
    features = _features(rows)
    assert features.loc["DUP", "has_duplicate"] == 1
    assert features.loc["DUP", "duplicate_days"] == 2
    assert features.loc["W0", "has_duplicate"] == 0
    assert features.loc["DUP", "short_interval"] > 0.5


def test_weekend_and_off_cycle():
    rows = [*_weekly()]
    rows[2] = ("W2", "2025-03-22", 1002.0, "W", "NF2")  # Saturday
    rows[5] = ("W5", "2025-04-09", 1005.0, "W", "NF5")  # Wednesday
    features = _features(rows)
    assert features.loc["W2", "is_weekend"] == 1
    assert features.loc["W5", "off_cycle"] == 1
    assert features.loc["W5", "usual_day"] == 0
    assert features.loc["W1", "off_cycle"] == 0


def test_monthly_cycle_uses_circular_day_distance():
    dates = ["2025-01-30", "2025-03-02", "2025-03-31", "2025-04-30", "2025-05-30", "2025-06-16"]
    rows = [(f"M{i}", d, 5000.0, "M", f"N{i}") for i, d in enumerate(dates)]
    features = _features(rows)
    assert (features["cycle"] == "monthly").all()
    assert features.loc["M1", "off_cycle"] == 0  # day 2 is close to day 30
    assert features.loc["M5", "off_cycle"] == 1


def test_new_and_unknown_suppliers():
    rows = [
        *_weekly(),
        ("N1", "2025-06-10", 90000.0, "N", "NFX"),
        ("U1", "2025-06-10", 10.0, "", ""),
    ]
    features = _features(rows)
    assert features.loc["N1", "is_new_supplier"] == 1
    assert features.loc["N1", "supplier_age_days"] == 9
    assert np.isnan(features.loc["N1", "amount_ratio"])
    assert features.loc["N1", "log_amount_ratio"] == 0
    assert features.loc["U1", "is_new_supplier"] == 1
    assert features.loc["N1", "amount_vs_global"] > 50


def test_output_keeps_input_order_and_has_no_missing_model_values():
    rows = list(reversed(_weekly()))
    transactions, matches = _frames(rows)
    features = compute_features(transactions, matches, SUPPLIERS)
    assert list(features["transaction_id"]) == [r[0] for r in rows]
    assert not features[list(MODEL_FEATURES)].isna().any().any()


def test_repeated_payments_to_an_unknown_payee_are_compared():
    unknown = [("U1", "2025-06-10", 9800.0, "", ""), ("U2", "2025-06-11", 9800.0, "", "")]
    features = _features([*_weekly(), *unknown])
    assert features.loc["U2", "has_duplicate"] == 1
    assert features.loc["U1", "has_duplicate"] == 0


def test_usual_interval_excludes_the_payment_itself():
    rows = [*_weekly(), ("W8", "2025-04-22", 1008.0, "W", "NF8")]  # 1 day after W7
    features = _features(rows)
    assert features.loc["W8", "usual_interval"] == 7
    assert features.loc["W8", "short_interval"] == pytest.approx(1 - 1 / 7)


def test_short_history_has_no_reference():
    features = _features(_weekly(n=2))
    assert features["usual_interval"].isna().all()
    assert np.isnan(features.loc["W1", "amount_ratio"])
    assert (features["short_interval"] == 0).all()


@pytest.mark.parametrize("amount", [0.0, -10.0])
def test_non_positive_amounts_are_rejected(amount):
    transactions, matches = _frames([*_weekly(), ("X", "2025-06-10", amount, "W", "")])
    with pytest.raises(ValueError, match="positive"):
        compute_features(transactions, matches, SUPPLIERS)


def test_works_before_any_supplier_is_registered():
    transactions, matches = _frames(
        [("U1", "2025-06-10", 50.0, "", ""), ("U2", "2025-06-11", 70.0, "", "")]
    )
    no_suppliers = SUPPLIERS.iloc[0:0]
    features = compute_features(transactions, matches, no_suppliers)
    assert (features["is_new_supplier"] == 1).all()
    assert not features[list(MODEL_FEATURES)].isna().any().any()


def test_suppliers_seen_at_the_start_of_the_history_are_not_new():
    suppliers = SUPPLIERS.assign(registered_at=pd.to_datetime("2025-03-01"))
    transactions, matches = _frames(_weekly())  # first payment 2025-03-03
    features = compute_features(transactions, matches, suppliers).set_index("transaction_id")
    assert features.loc["W0", "supplier_age_days"] == 2
    assert features.loc["W0", "is_new_supplier"] == 0
