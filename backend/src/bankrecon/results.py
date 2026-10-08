"""Persistence of pipeline outputs (reconciliation matches and anomaly scores) as CSV.

Each output has a ``.meta.json`` sidecar with fingerprints of the inputs it was computed
from, so a later step refuses to use results produced from different data.
"""

from __future__ import annotations

import hashlib
import json
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


class StaleResultsError(ValueError):
    """A pipeline step's output was computed from other inputs."""

    def __init__(self, path: Path, step: str) -> None:
        super().__init__(
            f"{path} foi gerado a partir de outros dados. Rode 'bankrecon {step}' de novo."
        )
        self.path = path
        self.step = step


def fingerprint(*frames: pd.DataFrame) -> str:
    """Content hash of one or more data frames (values and column names)."""
    digest = hashlib.sha256()
    for frame in frames:
        digest.update(",".join(map(str, frame.columns)).encode())
        digest.update(pd.util.hash_pandas_object(frame, index=False).to_numpy().tobytes())
    return digest.hexdigest()


def results_dir(data_dir: Path) -> Path:
    return data_dir / RESULTS_DIR


def save_matches(matches: pd.DataFrame, data_dir: Path, *, dataset_fp: str) -> Path:
    return _save(matches, results_dir(data_dir) / MATCHES_FILE, {"dataset": dataset_fp})


def load_matches(data_dir: Path, *, dataset_fp: str) -> pd.DataFrame:
    path = results_dir(data_dir) / MATCHES_FILE
    _check(path, "reconcile", {"dataset": dataset_fp})
    matches = pd.read_csv(
        path, keep_default_na=False, dtype={"invoice_ids": str, "supplier_id": str}
    )
    matches["layer"] = pd.to_numeric(matches["layer"]).astype("Int64")
    return matches


def save_scores(scores: pd.DataFrame, data_dir: Path, *, dataset_fp: str, matches_fp: str) -> Path:
    meta = {"dataset": dataset_fp, "matches": matches_fp}
    return _save(scores, results_dir(data_dir) / SCORES_FILE, meta)


def load_scores(data_dir: Path, *, dataset_fp: str, matches_fp: str) -> pd.DataFrame:
    path = results_dir(data_dir) / SCORES_FILE
    _check(path, "detect", {"dataset": dataset_fp, "matches": matches_fp})
    return pd.read_csv(path, keep_default_na=False, dtype={"reasons": str})


def _meta_path(path: Path) -> Path:
    return path.with_suffix(".meta.json")


def _save(frame: pd.DataFrame, path: Path, meta: dict[str, str]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)
    _meta_path(path).write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return path


def _check(path: Path, step: str, expected: dict[str, str]) -> None:
    if not path.exists():
        raise ResultsMissingError(path, step)
    try:
        meta = json.loads(_meta_path(path).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as error:
        raise StaleResultsError(path, step) from error
    if any(meta.get(key) != value for key, value in expected.items()):
        raise StaleResultsError(path, step)
