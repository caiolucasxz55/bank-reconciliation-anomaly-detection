"""Persistence of pipeline outputs (reconciliation matches and anomaly scores) as CSV."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

RESULTS_DIR = "results"
MATCHES_FILE = "matches.csv"
SCORES_FILE = "anomaly_scores.csv"


class ResultsMissingError(FileNotFoundError):
    """A pipeline step's output is missing; ``step`` is the CLI command that creates it."""

    def __init__(self, path: Path, step: str) -> None:
        super().__init__(f"{path} não existe. Rode 'bankrecon {step}' antes.")
        self.path = path
        self.step = step


def results_dir(data_dir: Path) -> Path:
    return data_dir / RESULTS_DIR


def save_matches(matches: pd.DataFrame, data_dir: Path) -> Path:
    return _save(matches, results_dir(data_dir) / MATCHES_FILE)


def load_matches(data_dir: Path) -> pd.DataFrame:
    path = results_dir(data_dir) / MATCHES_FILE
    if not path.exists():
        raise ResultsMissingError(path, "reconcile")
    matches = pd.read_csv(
        path, keep_default_na=False, dtype={"invoice_ids": str, "supplier_id": str}
    )
    matches["layer"] = pd.to_numeric(matches["layer"]).astype("Int64")
    return matches


def save_scores(scores: pd.DataFrame, data_dir: Path) -> Path:
    return _save(scores, results_dir(data_dir) / SCORES_FILE)


def load_scores(data_dir: Path) -> pd.DataFrame:
    path = results_dir(data_dir) / SCORES_FILE
    if not path.exists():
        raise ResultsMissingError(path, "detect")
    return pd.read_csv(path, keep_default_na=False, dtype={"reasons": str})


def _save(frame: pd.DataFrame, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)
    return path
