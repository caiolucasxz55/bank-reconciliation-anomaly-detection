"""Explainable per-payment features.

The same small set of features feeds the Isolation Forest and is turned into the
plain-language reasons shown to the analyst, so every score can be explained.

Features are computed over the whole statement (batch analysis): a supplier's average or
cycle uses all of its payments except the one being scored. Amounts are taken per invoice,
using the reconciliation, so a payment settling three invoices is not a "high value".
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from bankrecon.reconciliation.resolver import counterparty
from bankrecon.schema import split_list

# Columns fed to the model, in order.
MODEL_FEATURES = (
    "log_amount_ratio",
    "log_amount_vs_global",
    "short_interval",
    "is_new_supplier",
    "has_duplicate",
    "is_weekend",
    "off_cycle",
)


@dataclass(frozen=True)
class FeatureConfig:
    # A supplier registered at most this many days before the payment is "new".
    new_supplier_days: int = 30
    # Suppliers already known in the first days of the history are not "new": when real
    # data is imported, suppliers are registered from their first invoice, so every
    # supplier would otherwise look new at the start of the history.
    history_warmup_days: int = 14
    # Same supplier and amount (within ``duplicate_tolerance``) inside this many days.
    duplicate_window_days: int = 5
    duplicate_tolerance: float = 0.01
    # Off-cycle: farther than this from the supplier's usual day of the month.
    monthly_cycle_tolerance_days: int = 4
    # Cycles are only inferred for suppliers with at least this many payments.
    min_payments_for_cycle: int = 4


# A reference (typical amount or interval) needs at least this many other observations.
MIN_REFERENCE_SIZE = 2


def _leave_one_out_median(values: pd.Series) -> pd.Series:
    """For each position, the median of the other non-missing values of the group."""
    array = values.to_numpy(dtype=float)
    out = np.full(len(array), np.nan)
    for i in range(len(array)):
        others = np.delete(array, i)
        others = others[~np.isnan(others)]
        if len(others) >= MIN_REFERENCE_SIZE:
            out[i] = np.median(others)
    return pd.Series(out, index=values.index)


def _circular_day_distance(day: pd.Series, usual: int) -> pd.Series:
    diff = (day - usual).abs()
    return np.minimum(diff, 31 - diff)


def _cycle(group: pd.DataFrame, config: FeatureConfig) -> tuple[str, int | None]:
    """Infer ``("weekly", weekday)``, ``("monthly", day)`` or ``("none", None)``."""
    if len(group) < config.min_payments_for_cycle:
        return "none", None
    intervals = group["date"].diff().dt.days.dropna()
    median_interval = intervals.median()
    if 5 <= median_interval <= 9:
        return "weekly", int(group["date"].dt.weekday.mode().iloc[0])
    if 25 <= median_interval <= 35:
        return "monthly", int(group["date"].dt.day.mode().iloc[0])
    return "none", None


def compute_features(
    transactions: pd.DataFrame,
    matches: pd.DataFrame,
    suppliers: pd.DataFrame,
    config: FeatureConfig | None = None,
) -> pd.DataFrame:
    """One row per transaction with model features plus the raw values behind the reasons.

    ``matches`` is the reconciliation output; its ``supplier_id`` (the supplier the
    description resolves to, even for unmatched payments) groups payments by supplier.
    """
    config = config or FeatureConfig()
    if (transactions["amount"] <= 0).any():
        raise ValueError("transaction amounts must be positive debits")
    frame = transactions[["transaction_id", "date", "amount", "description"]].merge(
        matches[["transaction_id", "supplier_id", "invoice_ids"]], on="transaction_id", how="left"
    )
    frame["supplier_id"] = frame["supplier_id"].fillna("")
    n_invoices = frame["invoice_ids"].fillna("").map(lambda ids: len(split_list(ids)))
    frame["unit_amount"] = frame["amount"] / n_invoices.clip(lower=1)
    known = frame["supplier_id"] != ""
    # Payments to an unresolved payee share history by their normalized description, so
    # repeated payments to the same unknown counterparty are still compared.
    unknown_group = "?" + frame["description"].map(counterparty)
    frame["group"] = frame["supplier_id"].where(known, unknown_group)
    frame = frame.sort_values(["date", "transaction_id"]).reset_index(drop=True)

    frame["amount_vs_global"] = frame["unit_amount"] / frame["unit_amount"].median()

    by_group = frame.groupby("group", sort=False)
    frame["supplier_median"] = by_group["unit_amount"].transform(_leave_one_out_median)
    frame["amount_ratio"] = frame["unit_amount"] / frame["supplier_median"]
    frame["days_since_last"] = by_group["date"].diff().dt.days
    # Leave-one-out too: a short gap must not pull down its own reference.
    frame["usual_interval"] = frame.groupby("group", sort=False)["days_since_last"].transform(
        _leave_one_out_median
    )
    # One-sided: only a gap much shorter than usual is suspicious (long gaps are common,
    # e.g. sporadic suppliers or grouped invoices).
    interval_ratio = frame["days_since_last"] / frame["usual_interval"].clip(lower=1)
    frame["short_interval"] = (1.0 - interval_ratio).clip(lower=0.0).fillna(0.0)

    # A dict lookup (not Series.map with a Series) also works when there are no suppliers
    # yet; to_datetime keeps the datetime dtype when nothing matches.
    registered = dict(zip(suppliers["supplier_id"], suppliers["registered_at"], strict=True))
    registered_at = pd.to_datetime(frame["supplier_id"].map(registered))
    frame["supplier_age_days"] = (frame["date"] - registered_at).dt.days
    warmup_end = frame["date"].min() + pd.Timedelta(days=config.history_warmup_days)
    recently_registered = (frame["supplier_age_days"] <= config.new_supplier_days) & (
        registered_at > warmup_end
    )
    frame["is_new_supplier"] = (~known | recently_registered).astype(int)

    _add_duplicates(frame, config)
    _add_atypical_day(frame, config)

    frame["log_amount_ratio"] = np.log(frame["amount_ratio"]).fillna(0.0)
    frame["log_amount_vs_global"] = np.log(frame["amount_vs_global"])
    columns = [
        "transaction_id",
        "date",
        "supplier_id",
        *MODEL_FEATURES,
        "amount_ratio",
        "amount_vs_global",
        "days_since_last",
        "usual_interval",
        "supplier_age_days",
        "duplicate_days",
        "cycle",
        "usual_day",
    ]
    order = transactions[["transaction_id"]]
    return order.merge(frame[columns], on="transaction_id", how="left")


def _add_duplicates(frame: pd.DataFrame, config: FeatureConfig) -> None:
    """Flag the later payment of a same-supplier, same-amount pair a few days apart.

    The earlier payment is the legitimate one, so only the repeat is flagged.
    """
    duplicate_days = pd.Series(np.nan, index=frame.index)
    for _, group in frame.groupby("group", sort=False):
        dates = group["date"].to_numpy()
        amounts = group["amount"].to_numpy()
        for pos in range(1, len(group)):
            earlier = slice(0, pos)
            gap = (dates[pos] - dates[earlier]) / np.timedelta64(1, "D")
            same = (np.abs(amounts[earlier] - amounts[pos]) <= config.duplicate_tolerance) & (
                gap <= config.duplicate_window_days
            )
            if same.any():
                duplicate_days.iloc[group.index[pos]] = gap[same].min()
    frame["duplicate_days"] = duplicate_days
    frame["has_duplicate"] = duplicate_days.notna().astype(int)


def _add_atypical_day(frame: pd.DataFrame, config: FeatureConfig) -> None:
    frame["is_weekend"] = (frame["date"].dt.weekday >= 5).astype(int)
    frame["off_cycle"] = 0
    frame["cycle"] = "none"
    frame["usual_day"] = pd.array([pd.NA] * len(frame), dtype="Int64")
    for _, group in frame.groupby("group", sort=False):
        cycle, usual = _cycle(group, config)
        if usual is None:
            continue
        if cycle == "weekly":
            off = group["date"].dt.weekday != usual
        else:
            distance = _circular_day_distance(group["date"].dt.day, usual)
            off = distance > config.monthly_cycle_tolerance_days
        frame.loc[group.index, "off_cycle"] = off.astype(int)
        frame.loc[group.index, "cycle"] = cycle
        frame.loc[group.index, "usual_day"] = usual
