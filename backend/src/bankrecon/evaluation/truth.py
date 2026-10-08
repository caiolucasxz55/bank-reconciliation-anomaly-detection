"""Joining pipeline output with the ground truth."""

from __future__ import annotations

import pandas as pd


def join_truth(
    output: pd.DataFrame, ground_truth: pd.DataFrame, columns: list[str]
) -> pd.DataFrame:
    """Attach ground-truth ``columns`` to ``output``, one row per transaction.

    Raises ``ValueError`` unless both cover exactly the same transactions: output from
    other data must never be scored silently.
    """
    if set(output["transaction_id"]) != set(ground_truth["transaction_id"]):
        raise ValueError("the output and the ground truth cover different transactions")
    truth = ground_truth[["transaction_id", *columns]]
    return output.merge(truth, on="transaction_id", how="inner", validate="one_to_one")
