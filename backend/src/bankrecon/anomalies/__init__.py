"""Explainable anomaly detection: features, Isolation Forest ranking and reasons."""

from bankrecon.anomalies.detector import AnomalyConfig, detect_anomalies, score_features
from bankrecon.anomalies.features import MODEL_FEATURES, FeatureConfig, compute_features
from bankrecon.anomalies.reasons import ReasonConfig, explain, rank_label

__all__ = [
    "MODEL_FEATURES",
    "AnomalyConfig",
    "FeatureConfig",
    "ReasonConfig",
    "compute_features",
    "detect_anomalies",
    "explain",
    "rank_label",
    "score_features",
]
