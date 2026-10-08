import pandas as pd
import pytest

from bankrecon.evaluation.anomalies import evaluate_anomalies, render_anomalies


def _scores(n, high_risk):
    return pd.DataFrame(
        {
            "transaction_id": [f"T{i}" for i in range(1, n + 1)],
            "rank": range(1, n + 1),
            "high_risk": [i <= high_risk for i in range(1, n + 1)],
        }
    )


def _truth(n, anomalies):
    types = [anomalies.get(f"T{i}", "") for i in range(1, n + 1)]
    return pd.DataFrame(
        {"transaction_id": [f"T{i}" for i in range(1, n + 1)], "anomaly_type": types}
    )


@pytest.fixture
def report():
    truth = _truth(
        40,
        {
            "T1": "duplicate_payment",
            "T2": "duplicate_payment",
            "T3": "amount_outlier",
            "T4": "atypical_day",  # inside top 10% (4 of 40) but not high risk
            "T30": "atypical_day",
        },
    )
    return evaluate_anomalies(_scores(40, high_risk=3), truth, k=5)


def test_recall_by_type(report):
    recall = report.recall_by_type.set_index("Tipo de anomalia")
    assert recall.loc["Pagamento duplicado", "Recall (alto risco)"] == "100%"
    assert recall.loc["Dia atípico", "Recall (alto risco)"] == "0%"
    assert recall.loc["Dia atípico", "Recall (top 10%)"] == "50%"
    assert recall.loc["Fornecedor novo com valor alto", "Injetadas"] == 0
    assert recall.loc["Fornecedor novo com valor alto", "Recall (alto risco)"] == "—"


def test_precision_at_k(report):
    assert report.k == 5
    assert report.precision_at_k == pytest.approx(4 / 5)


def test_render(report):
    text = render_anomalies(report)
    assert "| Pagamento duplicado | 2 | 100% | 100% |" in text
    assert "Precisão nas 5 transações de maior score: 80%" in text


@pytest.mark.parametrize(("n_scores", "n_truth"), [(3, 2), (2, 3)])
def test_scores_and_truth_must_cover_the_same_transactions(n_scores, n_truth):
    with pytest.raises(ValueError, match="different transactions"):
        evaluate_anomalies(_scores(n_scores, 1), _truth(n_truth, {}))
