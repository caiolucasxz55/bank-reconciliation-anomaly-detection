import pandas as pd
import pytest

from bankrecon.evaluation import evaluate_reconciliation, to_markdown


def _matches(*rows):
    return pd.DataFrame(
        rows,
        columns=["transaction_id", "status", "layer", "confidence", "invoice_ids", "supplier_id"],
    ).astype({"layer": "Int64"})


def _truth(*rows):
    return pd.DataFrame(rows, columns=["transaction_id", "invoice_ids", "noise"])


@pytest.fixture
def report():
    matches = _matches(
        ("T1", "conciliada", 1, 1.0, "NF1", "S1"),
        ("T2", "sugerida", 2, 0.7, "NF3", "S1"),  # wrong invoice
        ("T3", "conciliada", 3, 0.9, "NF5;NF4", "S2"),  # order does not matter
        ("T4", "divergente", None, 0.0, "", "S1"),  # true duplicate
        ("T5", "divergente", None, 0.0, "", ""),  # missed match
    )
    truth = _truth(
        ("T1", "NF1", ""),
        ("T2", "NF2", "bank_fee"),
        ("T3", "NF4;NF5", "multi_invoice;late_payment"),
        ("T4", "", ""),
        ("T5", "NF6", "truncated_description"),
    )
    return evaluate_reconciliation(matches, truth)


def test_accuracy_counts_correct_unmatched(report):
    assert report.accuracy == pytest.approx(3 / 5)
    assert report.matchable_recall == pytest.approx(2 / 4)


def test_by_layer(report):
    layers = report.by_layer.set_index("Camada")
    assert layers.loc["1. Exata", "Acerto"] == "100%"
    assert layers.loc["2. Tolerante", "Acerto"] == "0%"
    assert layers.loc["3. Várias notas", "Transações"] == 1


def test_by_status(report):
    status = report.by_status.set_index("Status")
    assert status.loc["divergente", "Transações"] == 2
    assert status.loc["divergente", "Corretas"] == 1
    assert status.loc["conciliada", "Participação"] == "40%"


def test_by_noise_excludes_duplicates_from_clean_cases(report):
    noise = report.by_noise.set_index("Caso")
    assert noise.loc["Sem ruído", "Transações"] == 1
    assert noise.loc["Pagamento atrasado", "Acerto"] == "100%"
    assert noise.loc["Descrição abreviada", "Acerto"] == "0%"


def test_missing_ground_truth_is_an_error():
    with pytest.raises(ValueError, match="ground truth"):
        evaluate_reconciliation(
            _matches(("T9", "divergente", None, 0.0, "", "")), _truth(("T1", "", ""))
        )


def test_to_markdown():
    table = to_markdown(pd.DataFrame({"a": [1, 2], "b": ["x", "y"]}))
    assert table.splitlines() == ["| a | b |", "| --- | --- |", "| 1 | x |", "| 2 | y |"]


def test_empty_input_does_not_divide_by_zero():
    report = evaluate_reconciliation(_matches(), _truth())
    assert report.by_status["Participação"].tolist() == ["—", "—", "—"]
