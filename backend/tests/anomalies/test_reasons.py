import numpy as np
import pandas as pd
import pytest

from bankrecon.anomalies import ReasonConfig, explain, rank_label
from bankrecon.anomalies.reasons import format_number


def _row(**overrides):
    base = {
        "transaction_id": "T",
        "date": pd.Timestamp("2025-03-05"),  # Wednesday
        "supplier_id": "S1",
        "log_amount_ratio": 0.0,
        "log_amount_vs_global": 0.0,
        "short_interval": 0.0,
        "is_new_supplier": 0,
        "has_duplicate": 0,
        "is_weekend": 0,
        "off_cycle": 0,
        "amount_ratio": 1.0,
        "amount_vs_global": 1.0,
        "days_since_last": 7.0,
        "usual_interval": 7.0,
        "supplier_age_days": 900.0,
        "duplicate_days": np.nan,
        "cycle": "weekly",
        "usual_day": 2,
    }
    base.update(overrides)
    base["log_amount_ratio"] = np.log(base["amount_ratio"]) if pd.notna(base["amount_ratio"]) else 0
    base["log_amount_vs_global"] = np.log(base["amount_vs_global"])
    return base


def _explain(*rows, config=None):
    # Pad with normal rows so rarity percentiles are meaningful.
    frame = pd.DataFrame([*rows, *[_row() for _ in range(20)]])
    return explain(frame, config)[: len(rows)]


def test_normal_payment_has_no_reasons():
    assert _explain(_row()) == [[]]


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"amount_ratio": 3.4}, "valor 3,4 vezes acima do normal para o fornecedor"),
        ({"amount_ratio": 0.25}, "valor 4,0 vezes abaixo do normal para o fornecedor"),
        (
            {"has_duplicate": 1, "duplicate_days": 2.0},
            "outro pagamento de mesmo valor ao mesmo fornecedor 2 dias antes",
        ),
        (
            {"has_duplicate": 1, "duplicate_days": 0.0},
            "outro pagamento de mesmo valor ao mesmo fornecedor no mesmo dia",
        ),
        ({"is_new_supplier": 1, "supplier_age_days": 4.0}, "fornecedor cadastrado há 4 dias"),
        ({"is_new_supplier": 1, "supplier_age_days": 1.0}, "fornecedor cadastrado há 1 dia"),
        (
            {"is_new_supplier": 1, "supplier_age_days": 0.0},
            "fornecedor cadastrado no dia do pagamento",
        ),
        (
            {"is_new_supplier": 1, "supplier_age_days": -5.0},
            "pago 5 dias antes do cadastro do fornecedor",
        ),
        (
            {"has_duplicate": 1, "duplicate_days": 1.0},
            "outro pagamento de mesmo valor ao mesmo fornecedor 1 dia antes",
        ),
        (
            {"short_interval": 0.9, "days_since_last": 1.0},
            "só 1 dia depois do último pagamento ao fornecedor (normal: cerca de 7 dias)",
        ),
        (
            {"short_interval": 1.0, "days_since_last": 0.0},
            "no mesmo dia do último pagamento ao fornecedor (normal: cerca de 7 dias)",
        ),
        (
            {"is_new_supplier": 1, "supplier_id": ""},
            "descrição não corresponde a nenhum fornecedor cadastrado",
        ),
        ({"is_weekend": 1, "date": pd.Timestamp("2025-03-08")}, "pago num sábado"),
        (
            {"off_cycle": 1},
            "fora do ciclo do fornecedor (normalmente pago às quartas)",
        ),
        (
            {"off_cycle": 1, "cycle": "monthly", "usual_day": 12},
            "fora do ciclo do fornecedor (normalmente pago por volta do dia 12)",
        ),
        (
            {"short_interval": 0.7, "days_since_last": 2.0},
            "só 2 dias depois do último pagamento ao fornecedor (normal: cerca de 7 dias)",
        ),
    ],
)
def test_reason_texts(overrides, expected):
    [reasons] = _explain(_row(**overrides))
    assert expected in reasons


def test_company_median_reason_only_without_supplier_history():
    [regular] = _explain(_row(amount_vs_global=8.0))
    [new] = _explain(_row(amount_vs_global=8.0, is_new_supplier=1, amount_ratio=np.nan))
    assert not any("mediana" in r for r in regular)
    assert "valor 8,0 vezes a mediana dos pagamentos da empresa" in new


def test_duplicate_hides_short_interval_reason():
    [reasons] = _explain(_row(has_duplicate=1, duplicate_days=1.0, short_interval=0.9))
    assert not any(r.startswith("só") for r in reasons)


def test_reasons_are_capped_and_rarest_first():
    sunday = pd.Timestamp("2025-03-09")
    target = _row(has_duplicate=1, duplicate_days=1.0, is_weekend=1, off_cycle=1, date=sunday)
    # Off-cycle is common in this population, weekend payments are not.
    frame = pd.DataFrame([target, *[_row(off_cycle=1)] * 8, *[_row()] * 11])
    [reasons, *_] = explain(frame, ReasonConfig(max_reasons=2))
    assert len(reasons) == 2
    assert not any("ciclo" in r for r in reasons)


def test_rarer_flag_comes_first_regardless_of_rule_order():
    # off_cycle is declared after is_new_supplier in RULES but is the rarer one here.
    target = _row(is_new_supplier=1, supplier_age_days=3.0, off_cycle=1)
    others = [_row(is_new_supplier=1, supplier_age_days=9.0)] * 9
    frame = pd.DataFrame([target, *others, *[_row()] * 10])
    [reasons, *_] = explain(frame)
    assert reasons[0].startswith("fora do ciclo")


@pytest.mark.parametrize(
    ("rank", "total", "expected"),
    [(1, 600, "entre as 1% mais incomuns"), (12, 600, "entre as 2% mais incomuns"),
     (600, 600, "entre as 100% mais incomuns")],
)  # fmt: skip
def test_rank_label(rank, total, expected):
    assert rank_label(rank, total) == expected


def test_format_number_uses_decimal_comma():
    assert format_number(3.44) == "3,4"
