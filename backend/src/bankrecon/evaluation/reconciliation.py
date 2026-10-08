"""Reconciliation accuracy against the ground truth."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from bankrecon.evaluation.tables import format_percent, to_markdown
from bankrecon.reconciliation.models import Layer, MatchStatus
from bankrecon.schema import LIST_SEPARATOR, split_list

LAYER_LABELS = {
    Layer.EXACT: "1. Exata",
    Layer.TOLERANT: "2. Tolerante",
    Layer.MULTI_INVOICE: "3. Várias notas",
}
NOISE_LABELS = {
    "": "Sem ruído",
    "late_payment": "Pagamento atrasado",
    "bank_fee": "Tarifa descontada",
    "multi_invoice": "Várias notas",
    "truncated_description": "Descrição abreviada",
}


def _invoice_set(value: str) -> frozenset[str]:
    return frozenset(split_list(value))


@dataclass(frozen=True)
class ReconciliationReport:
    by_layer: pd.DataFrame
    by_status: pd.DataFrame
    by_noise: pd.DataFrame
    accuracy: float
    # Share of transactions that do pay invoices and got exactly the right invoices.
    matchable_recall: float


def _join(matches: pd.DataFrame, ground_truth: pd.DataFrame) -> pd.DataFrame:
    truth = ground_truth[["transaction_id", "invoice_ids", "noise"]].rename(
        columns={"invoice_ids": "true_invoice_ids"}
    )
    frame = matches.merge(truth, on="transaction_id", how="inner", validate="one_to_one")
    if len(frame) != len(matches):
        raise ValueError("every transaction must appear in the ground truth")
    frame["correct"] = [
        _invoice_set(found) == _invoice_set(true)
        for found, true in zip(frame["invoice_ids"], frame["true_invoice_ids"], strict=True)
    ]
    return frame


def evaluate_reconciliation(
    matches: pd.DataFrame, ground_truth: pd.DataFrame
) -> ReconciliationReport:
    """Compare reconciliation output with the ground truth.

    A transaction is correct when the set of invoices it was matched to equals the true
    set; an unmatched transaction is correct when it truly pays no invoice (a duplicate).
    """
    frame = _join(matches, ground_truth)

    by_layer = []
    for layer, label in LAYER_LABELS.items():
        rows = frame[frame["layer"] == layer.value]
        by_layer.append(
            {
                "Camada": label,
                "Transações": len(rows),
                "Corretas": int(rows["correct"].sum()),
                "Acerto": format_percent(rows["correct"].mean() if len(rows) else float("nan")),
            }
        )

    by_status = []
    for status in MatchStatus:
        rows = frame[frame["status"] == status.value]
        by_status.append(
            {
                "Status": status.value,
                "Transações": len(rows),
                "Participação": format_percent(
                    len(rows) / len(frame) if len(frame) else float("nan")
                ),
                "Corretas": int(rows["correct"].sum()),
            }
        )

    exploded = frame.assign(noise=frame["noise"].str.split(LIST_SEPARATOR)).explode("noise")
    by_noise = []
    for noise, label in NOISE_LABELS.items():
        rows = exploded[exploded["noise"] == noise]
        if noise == "":
            rows = rows[rows["true_invoice_ids"] != ""]
        by_noise.append(
            {
                "Caso": label,
                "Transações": len(rows),
                "Acerto": format_percent(rows["correct"].mean() if len(rows) else float("nan")),
            }
        )

    matchable = frame[frame["true_invoice_ids"] != ""]
    return ReconciliationReport(
        by_layer=pd.DataFrame(by_layer),
        by_status=pd.DataFrame(by_status),
        by_noise=pd.DataFrame(by_noise),
        accuracy=float(frame["correct"].mean()) if len(frame) else float("nan"),
        matchable_recall=float(matchable["correct"].mean()) if len(matchable) else float("nan"),
    )


def render_reconciliation(report: ReconciliationReport) -> str:
    """Markdown section for the README."""
    sections = [
        "## Conciliação",
        f"Acerto geral: {report.accuracy:.1%}",
        "### Acerto por camada",
        to_markdown(report.by_layer),
        "### Status",
        to_markdown(report.by_status),
        "### Acerto por caso difícil",
        to_markdown(report.by_noise),
    ]
    return "\n\n".join(sections)
