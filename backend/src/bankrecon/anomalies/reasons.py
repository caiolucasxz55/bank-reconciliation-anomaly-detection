"""Plain-language reasons built from the same features the model sees.

A reason is only written when its feature crosses a readable threshold. Reasons are
ordered by how rare the transaction's value is among all transactions, so the first
reason is the one that most sets this payment apart.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
import pandas as pd

WEEKDAYS = ("segundas", "terças", "quartas", "quintas", "sextas", "sábados", "domingos")
WEEKEND_DAYS = {5: "sábado", 6: "domingo"}


@dataclass(frozen=True)
class ReasonConfig:
    max_reasons: int = 3
    high_amount_ratio: float = 2.0
    low_amount_ratio: float = 0.5
    high_amount_vs_global: float = 3.0
    short_interval: float = 0.5


def format_number(value: float) -> str:
    """Brazilian decimal comma, one decimal place: 3.4 -> '3,4'."""
    return f"{value:.1f}".replace(".", ",")


def _count_days(n: int) -> str:
    return "1 dia" if n == 1 else f"{n} dias"


def _days_before(n: float) -> str:
    n = int(n)
    return "no mesmo dia" if n == 0 else f"{_count_days(n)} antes"


@dataclass(frozen=True)
class _Rule:
    # Column whose rarity ranks the reason.
    feature: str
    applies: Callable[[pd.Series, ReasonConfig], bool]
    text: Callable[[pd.Series], str]


def _amount_text(row: pd.Series) -> str:
    ratio = row["amount_ratio"]
    if ratio >= 1:
        return f"valor {format_number(ratio)} vezes acima do normal para o fornecedor"
    return f"valor {format_number(1 / ratio)} vezes abaixo do normal para o fornecedor"


def _new_supplier_text(row: pd.Series) -> str:
    if not row["supplier_id"]:
        return "descrição não corresponde a nenhum fornecedor cadastrado"
    age = int(row["supplier_age_days"])
    if age < 0:
        return f"pago {_count_days(-age)} antes do cadastro do fornecedor"
    if age == 0:
        return "fornecedor cadastrado no dia do pagamento"
    return f"fornecedor cadastrado há {_count_days(age)}"


def _short_interval_text(row: pd.Series) -> str:
    days = int(row["days_since_last"])
    since = "no mesmo dia do" if days == 0 else f"só {_count_days(days)} depois do"
    return (
        f"{since} último pagamento ao fornecedor "
        f"(normal: cerca de {_count_days(round(row['usual_interval']))})"
    )


def _off_cycle_text(row: pd.Series) -> str:
    usual = int(row["usual_day"])
    if row["cycle"] == "weekly":
        return f"fora do ciclo do fornecedor (normalmente pago às {WEEKDAYS[usual]})"
    return f"fora do ciclo do fornecedor (normalmente pago por volta do dia {usual})"


RULES = (
    _Rule(
        "has_duplicate",
        lambda r, _: bool(r["has_duplicate"]),
        lambda r: (
            "outro pagamento de mesmo valor ao mesmo fornecedor "
            + _days_before(r["duplicate_days"])
        ),
    ),
    _Rule(
        "abs_log_amount_ratio",
        lambda r, c: (
            pd.notna(r["amount_ratio"])
            and not c.low_amount_ratio < r["amount_ratio"] < c.high_amount_ratio
        ),
        _amount_text,
    ),
    _Rule("is_new_supplier", lambda r, _: bool(r["is_new_supplier"]), _new_supplier_text),
    _Rule(
        "log_amount_vs_global",
        # Only meaningful without the supplier's own history: a large regular supplier is
        # always far above the company median.
        lambda r, c: (
            (bool(r["is_new_supplier"]) or pd.isna(r["amount_ratio"]))
            and r["amount_vs_global"] >= c.high_amount_vs_global
        ),
        lambda r: (
            f"valor {format_number(r['amount_vs_global'])} vezes a mediana "
            "dos pagamentos da empresa"
        ),
    ),
    _Rule(
        "is_weekend",
        lambda r, _: bool(r["is_weekend"]),
        lambda r: f"pago num {WEEKEND_DAYS[r['weekday']]}",
    ),
    _Rule("off_cycle", lambda r, _: bool(r["off_cycle"]), _off_cycle_text),
    _Rule(
        "short_interval",
        lambda r, c: r["short_interval"] >= c.short_interval and not r["has_duplicate"],
        _short_interval_text,
    ),
)


def _rarity(features: pd.DataFrame) -> pd.DataFrame:
    """Per feature, 1 minus the share of transactions at least as extreme as each value.

    A flag set on 2% of payments gets rarity 0.98 and one set on 40% gets 0.60, so the
    rarer reason comes first.
    """
    columns = sorted({rule.feature for rule in RULES})
    ranked = features.assign(abs_log_amount_ratio=features["log_amount_ratio"].abs())
    share_at_least = ranked[columns].rank(ascending=False, method="max", pct=True)
    return 1.0 - share_at_least


def explain(features: pd.DataFrame, config: ReasonConfig | None = None) -> list[list[str]]:
    """Up to ``config.max_reasons`` reasons per transaction, most distinctive first."""
    config = config or ReasonConfig()
    rarity = _rarity(features)
    rows = features.assign(weekday=features["date"].dt.weekday)
    out = []
    for index, row in rows.iterrows():
        triggered = [
            (rarity.at[index, rule.feature], position, rule.text(row))
            for position, rule in enumerate(RULES)
            if rule.applies(row, config)
        ]
        # Rarest first; rule order breaks ties so the output is deterministic.
        triggered.sort(key=lambda item: (-item[0], item[1]))
        out.append([text for _, _, text in triggered[: config.max_reasons]])
    return out


def rank_label(rank: int, total: int) -> str:
    """Position as a share of the ranking: 'entre as 2% mais incomuns'."""
    share = max(1, int(np.ceil(100 * rank / total)))
    return f"entre as {share}% mais incomuns"
