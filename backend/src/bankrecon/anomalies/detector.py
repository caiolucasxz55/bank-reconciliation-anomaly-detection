"""Isolation Forest scoring, ranking and reasons.

The score is not a probability of fraud: it only says how unusual a payment is compared
with the others. It is shown as a position in the ranking ("entre as 2% mais incomuns")
and accompanied by reasons, so a human decides what deserves investigation.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd
from sklearn.ensemble import IsolationForest

from bankrecon.anomalies.features import MODEL_FEATURES, FeatureConfig, compute_features
from bankrecon.anomalies.reasons import ReasonConfig, explain, rank_label
from bankrecon.schema import join_list


@dataclass(frozen=True)
class AnomalyConfig:
    n_estimators: int = 300
    random_state: int = 0
    # Share of the ranking flagged as high risk (the "alto risco" total in the UI).
    high_risk_share: float = 0.05
    features: FeatureConfig = field(default_factory=FeatureConfig)
    reasons: ReasonConfig = field(default_factory=ReasonConfig)

    def __post_init__(self) -> None:
        if not 0 < self.high_risk_share <= 1:
            raise ValueError("high_risk_share must be in (0, 1]")
        if self.n_estimators < 1:
            raise ValueError("n_estimators must be >= 1")


def score_features(features: pd.DataFrame, config: AnomalyConfig | None = None) -> pd.DataFrame:
    """Fit the Isolation Forest on the features and rank every transaction."""
    config = config or AnomalyConfig()
    x = features[list(MODEL_FEATURES)].to_numpy(dtype=float)
    model = IsolationForest(n_estimators=config.n_estimators, random_state=config.random_state)
    model.fit(x)
    # score_samples is higher for normal points; flip it so higher means more unusual.
    scores = -model.score_samples(x)

    total = len(features)
    result = pd.DataFrame({"transaction_id": features["transaction_id"], "score": scores})
    result["rank"] = result["score"].rank(ascending=False, method="first").astype(int)
    result["percentile"] = result["rank"] / total
    result["rank_label"] = [rank_label(r, total) for r in result["rank"]]
    result["high_risk"] = result["rank"] <= max(1, round(total * config.high_risk_share))
    result["reasons"] = [join_list(r) for r in explain(features, config.reasons)]
    return result


def detect_anomalies(
    transactions: pd.DataFrame,
    matches: pd.DataFrame,
    suppliers: pd.DataFrame,
    config: AnomalyConfig | None = None,
) -> pd.DataFrame:
    """Score every transaction; one row per transaction, in the input order.

    Columns: ``transaction_id``, ``score`` (higher is more unusual), ``rank`` (1 = most
    unusual), ``percentile``, ``rank_label``, ``high_risk`` and ``reasons``
    (``;``-separated, most distinctive first).
    """
    config = config or AnomalyConfig()
    if transactions.empty:
        raise ValueError("no transactions to score")
    features = compute_features(transactions, matches, suppliers, config.features)
    return score_features(features, config)
