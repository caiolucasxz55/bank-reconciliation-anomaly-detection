"""Anomaly detection quality against the ground truth."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from bankrecon.evaluation.tables import format_percent, to_markdown

ANOMALY_LABELS = {
    "duplicate_payment": "Pagamento duplicado",
    "amount_outlier": "Valor fora do padrão",
    "new_supplier_high_value": "Fornecedor novo com valor alto",
    "atypical_day": "Dia atípico",
}
TOP_K = 50
WIDE_SHARE = 0.10


@dataclass(frozen=True)
class AnomalyReport:
    recall_by_type: pd.DataFrame
    precision_at_k: float
    k: int
    high_risk_count: int
    wide_count: int


def evaluate_anomalies(
    scores: pd.DataFrame, ground_truth: pd.DataFrame, k: int = TOP_K
) -> AnomalyReport:
    """Recall per injected anomaly type and precision among the ``k`` highest scores.

    Recall is measured at the high-risk cut (``high_risk`` column) and, for context, at
    a wider cut of the top 10% of the ranking.
    """
    frame = scores.merge(
        ground_truth[["transaction_id", "anomaly_type"]],
        on="transaction_id",
        how="inner",
        validate="one_to_one",
    )
    if len(frame) != len(scores):
        raise ValueError("every transaction must appear in the ground truth")

    wide_count = max(1, round(len(frame) * WIDE_SHARE))
    frame["wide"] = frame["rank"] <= wide_count
    rows = []
    for anomaly, label in ANOMALY_LABELS.items():
        of_type = frame[frame["anomaly_type"] == anomaly]
        rows.append(
            {
                "Tipo de anomalia": label,
                "Injetadas": len(of_type),
                "Recall (alto risco)": format_percent(
                    of_type["high_risk"].mean() if len(of_type) else float("nan")
                ),
                f"Recall (top {WIDE_SHARE:.0%})": format_percent(
                    of_type["wide"].mean() if len(of_type) else float("nan")
                ),
            }
        )

    top = frame.nsmallest(k, "rank")
    precision = float((top["anomaly_type"] != "").mean()) if len(top) else float("nan")
    return AnomalyReport(
        recall_by_type=pd.DataFrame(rows),
        precision_at_k=precision,
        k=min(k, len(frame)),
        high_risk_count=int(frame["high_risk"].sum()),
        wide_count=wide_count,
    )


def render_anomalies(report: AnomalyReport) -> str:
    """Markdown section for the README."""
    return "\n\n".join(
        [
            "## Anomalias",
            f"Alto risco = as {report.high_risk_count} transações de maior score; "
            f"top 10% = {report.wide_count} transações.",
            "### Recall por tipo",
            to_markdown(report.recall_by_type),
            "### Priorização",
            f"Precisão nas {report.k} transações de maior score: "
            f"{format_percent(report.precision_at_k)}",
        ]
    )
