import pandas as pd
import pytest

from bankrecon.anomalies import AnomalyConfig, detect_anomalies
from bankrecon.evaluation.anomalies import evaluate_anomalies
from bankrecon.reconciliation import reconcile


@pytest.fixture(scope="module")
def scores(dataset):
    matches = reconcile(dataset.transactions, dataset.invoices, dataset.suppliers)
    return detect_anomalies(dataset.transactions, matches, dataset.suppliers)


def test_one_row_per_transaction_in_input_order(scores, dataset):
    assert list(scores["transaction_id"]) == list(dataset.transactions["transaction_id"])
    assert set(scores.columns) == {
        "transaction_id",
        "score",
        "rank",
        "percentile",
        "rank_label",
        "high_risk",
        "reasons",
    }


def test_ranking_is_a_permutation_ordered_by_score(scores):
    assert sorted(scores["rank"]) == list(range(1, len(scores) + 1))
    ordered = scores.sort_values("rank")["score"]
    assert ordered.is_monotonic_decreasing


def test_high_risk_is_the_top_share(scores):
    expected = round(len(scores) * AnomalyConfig().high_risk_share)
    assert scores["high_risk"].sum() == expected
    assert scores.loc[scores["high_risk"], "rank"].max() == expected


def test_every_high_risk_transaction_is_explained(scores):
    assert (scores.loc[scores["high_risk"], "reasons"] != "").all()


def test_detection_is_deterministic(scores, dataset):
    matches = reconcile(dataset.transactions, dataset.invoices, dataset.suppliers)
    again = detect_anomalies(dataset.transactions, matches, dataset.suppliers)
    pd.testing.assert_frame_equal(scores, again)


def test_quality_floor_against_ground_truth(scores, dataset):
    report = evaluate_anomalies(scores, dataset.ground_truth)
    recall = report.recall_by_type.set_index("Tipo de anomalia")["Recall (top 10%)"]
    assert recall["Pagamento duplicado"] == "100%"
    assert recall["Fornecedor novo com valor alto"] == "100%"
    # The top 50 holds far more anomalies than chance (32 of ~600 is about 5%).
    assert report.precision_at_k >= 0.4


def test_empty_input_is_rejected(dataset):
    with pytest.raises(ValueError, match="no transactions"):
        detect_anomalies(dataset.transactions.iloc[:0], dataset.transactions, dataset.suppliers)


def test_config_validation():
    with pytest.raises(ValueError, match="high_risk_share"):
        AnomalyConfig(high_risk_share=0)
