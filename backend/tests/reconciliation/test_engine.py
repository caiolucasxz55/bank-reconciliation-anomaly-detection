import pandas as pd
import pytest

from bankrecon.reconciliation import Layer, MatchStatus, Reconciler, ReconciliationConfig, reconcile

SUPPLIERS = pd.DataFrame(
    {
        "supplier_id": ["S1", "S2", "S3"],
        "name": [
            "Acme Logística e Transportes Ltda",
            "Lumen Consultoria Eireli",
            "Brisa Têxtil ME",
        ],
    }
)


def _invoices(*rows):
    return pd.DataFrame(
        [
            {"invoice_id": i, "supplier_id": s, "issue_date": pd.Timestamp(d), "amount": a}
            for i, s, d, a in rows
        ]
    )


def _transactions(*rows):
    return pd.DataFrame(
        [
            {"transaction_id": t, "date": pd.Timestamp(d), "amount": a, "description": desc}
            for t, d, a, desc in rows
        ]
    )


def _run(transactions, invoices, config=None):
    matches = Reconciler(SUPPLIERS, config).run(transactions, invoices)
    return {m.transaction_id: m for m in matches}


def test_exact_layer():
    result = _run(
        _transactions(("T1", "2025-03-12", 1500.00, "PIX ACME LOGISTICA E TRANSPORTES")),
        _invoices(("NF1", "S1", "2025-03-10", 1500.00)),
    )
    match = result["T1"]
    assert match.status is MatchStatus.RECONCILED
    assert match.layer is Layer.EXACT
    assert match.invoice_ids == ("NF1",)
    assert match.confidence == 1.0
    assert match.supplier_id == "S1"


def test_exact_layer_prefers_closest_invoice_and_matches_one_to_one():
    result = _run(
        _transactions(
            ("T1", "2025-03-12", 900.00, "PIX ACME LOGISTICA E TRANSPORTES"),
            ("T2", "2025-03-13", 900.00, "PIX ACME LOGISTICA E TRANSPORTES"),
        ),
        _invoices(("NF1", "S1", "2025-03-08", 900.00), ("NF2", "S1", "2025-03-11", 900.00)),
    )
    assert result["T1"].invoice_ids == ("NF2",)
    assert result["T2"].invoice_ids == ("NF1",)


def test_payment_outside_exact_window_goes_to_tolerant_layer():
    result = _run(
        _transactions(("T1", "2025-03-25", 1500.00, "PIX ACME LOGISTICA E TRANSPORTES")),
        _invoices(("NF1", "S1", "2025-03-10", 1500.00)),
    )
    assert result["T1"].layer is Layer.TOLERANT
    assert result["T1"].invoice_ids == ("NF1",)


def test_tolerant_layer_accepts_bank_fee_and_abbreviated_name():
    result = _run(
        _transactions(("T1", "2025-03-12", 1492.50, "PIX ACME LOGIST TRANS LT")),
        _invoices(("NF1", "S1", "2025-03-10", 1500.00)),
    )
    match = result["T1"]
    assert match.layer is Layer.TOLERANT
    assert match.invoice_ids == ("NF1",)
    assert 0 < match.confidence < 1


def test_tolerant_layer_never_accepts_paying_more_than_the_invoice():
    result = _run(
        _transactions(("T1", "2025-03-12", 1505.00, "PIX ACME LOGIST TRANS LT")),
        _invoices(("NF1", "S1", "2025-03-10", 1500.00)),
    )
    assert result["T1"].status is MatchStatus.UNMATCHED


def test_low_confidence_match_is_only_suggested():
    config = ReconciliationConfig(auto_confirm_confidence=0.99)
    result = _run(
        _transactions(("T1", "2025-03-12", 1490.00, "PIX ACME LOGIST TRANS LT")),
        _invoices(("NF1", "S1", "2025-03-10", 1500.00)),
        config,
    )
    assert result["T1"].status is MatchStatus.SUGGESTED


def test_ambiguous_tolerant_match_is_only_suggested():
    result = _run(
        _transactions(("T1", "2025-03-12", 995.00, "PIX ACME LOGIST TRANS LT")),
        _invoices(("NF1", "S1", "2025-03-10", 1000.00), ("NF2", "S1", "2025-03-10", 1000.01)),
    )
    assert result["T1"].layer is Layer.TOLERANT
    assert result["T1"].status is MatchStatus.SUGGESTED


def test_multi_invoice_layer():
    result = _run(
        _transactions(("T1", "2025-03-20", 3300.00, "TED LUMEN CONSULTORIA EIRELI")),
        _invoices(
            ("NF1", "S2", "2025-03-01", 1000.00),
            ("NF2", "S2", "2025-03-08", 1100.00),
            ("NF3", "S2", "2025-03-15", 1200.00),
        ),
    )
    match = result["T1"]
    assert match.layer is Layer.MULTI_INVOICE
    assert set(match.invoice_ids) == {"NF1", "NF2", "NF3"}
    assert match.status is MatchStatus.RECONCILED


def test_multi_invoice_with_several_valid_subsets_is_suggested():
    result = _run(
        _transactions(("T1", "2025-03-20", 2000.00, "TED LUMEN CONSULTORIA EIRELI")),
        _invoices(
            ("NF1", "S2", "2025-03-01", 1000.00),
            ("NF2", "S2", "2025-03-08", 1000.00),
            ("NF3", "S2", "2025-03-15", 1000.00),
        ),
    )
    assert result["T1"].layer is Layer.MULTI_INVOICE
    assert result["T1"].status is MatchStatus.SUGGESTED


def test_unmatched_transaction_keeps_resolved_supplier():
    result = _run(
        _transactions(
            ("T1", "2025-03-12", 777.00, "PIX BRISA TEXTIL ME"),
            ("T2", "2025-03-12", 777.00, "PIX DESCONHECIDO QUALQUER"),
        ),
        _invoices(("NF1", "S3", "2025-01-02", 100.00)),
    )
    assert result["T1"].status is MatchStatus.UNMATCHED
    assert result["T1"].supplier_id == "S3"
    assert result["T1"].layer is None
    assert result["T2"].supplier_id is None


def test_duplicate_payment_is_left_unmatched():
    result = _run(
        _transactions(
            ("T1", "2025-03-12", 1500.00, "PIX ACME LOGISTICA E TRANSPORTES"),
            ("T2", "2025-03-13", 1500.00, "PIX ACME LOGISTICA E TRANSPORTES"),
        ),
        _invoices(("NF1", "S1", "2025-03-10", 1500.00)),
    )
    assert result["T1"].status is MatchStatus.RECONCILED
    assert result["T2"].status is MatchStatus.UNMATCHED


def test_reconcile_returns_frame_in_input_order():
    transactions = _transactions(
        ("T2", "2025-03-13", 10.00, "PIX X"),
        ("T1", "2025-03-12", 1500.00, "PIX ACME LOGISTICA E TRANSPORTES"),
    )
    frame = reconcile(transactions, _invoices(("NF1", "S1", "2025-03-10", 1500.00)), SUPPLIERS)
    assert list(frame["transaction_id"]) == ["T2", "T1"]
    assert list(frame.columns) == [
        "transaction_id",
        "status",
        "layer",
        "confidence",
        "invoice_ids",
        "supplier_id",
    ]
    assert frame.loc[1, "invoice_ids"] == "NF1"
    assert pd.isna(frame.loc[0, "layer"])


@pytest.mark.parametrize(
    "kwargs",
    [
        {"name_min_score": 0},
        {"auto_confirm_confidence": 1.5},
        {"exact_max_days": 10, "tolerant_max_days": 5},
        {"multi_max_invoices": 1},
    ],
)
def test_config_validation(kwargs):
    with pytest.raises(ValueError):  # noqa: PT011
        ReconciliationConfig(**kwargs)


def test_payment_is_never_matched_to_a_later_invoice():
    result = _run(
        _transactions(("T1", "2025-03-10", 900.00, "PIX ACME LOGISTICA E TRANSPORTES")),
        _invoices(("NF1", "S1", "2025-03-12", 900.00)),
    )
    assert result["T1"].status is MatchStatus.UNMATCHED


def test_duplicate_does_not_take_next_weeks_invoice_with_same_amount():
    result = _run(
        _transactions(
            ("T1", "2025-03-03", 900.00, "PIX ACME LOGISTICA E TRANSPORTES"),
            ("T2", "2025-03-06", 900.00, "PIX ACME LOGISTICA E TRANSPORTES"),  # duplicate
            ("T3", "2025-03-10", 900.00, "PIX ACME LOGISTICA E TRANSPORTES"),
        ),
        _invoices(("NF1", "S1", "2025-03-03", 900.00), ("NF2", "S1", "2025-03-10", 900.00)),
    )
    assert result["T1"].invoice_ids == ("NF1",)
    assert result["T2"].status is MatchStatus.UNMATCHED
    assert result["T3"].invoice_ids == ("NF2",)


def test_tolerant_layer_discards_weak_coincidences():
    config = ReconciliationConfig(tolerant_min_confidence=0.95)
    result = _run(
        _transactions(("T1", "2025-03-12", 1490.00, "PIX ACME LOGIST TRANS LT")),
        _invoices(("NF1", "S1", "2025-03-10", 1500.00)),
        config,
    )
    assert result["T1"].status is MatchStatus.UNMATCHED


def test_multi_invoice_prefers_oldest_open_invoices():
    result = _run(
        _transactions(
            ("T1", "2025-03-20", 2000.00, "TED LUMEN CONSULTORIA EIRELI"),
            ("T2", "2025-03-27", 2000.00, "TED LUMEN CONSULTORIA EIRELI"),
        ),
        _invoices(
            ("NF1", "S2", "2025-03-01", 1000.00),
            ("NF2", "S2", "2025-03-08", 1000.00),
            ("NF3", "S2", "2025-03-15", 1000.00),
            ("NF4", "S2", "2025-03-22", 1000.00),
        ),
    )
    assert set(result["T1"].invoice_ids) == {"NF1", "NF2"}
    assert set(result["T2"].invoice_ids) == {"NF3", "NF4"}


def test_reconciler_can_run_twice_with_identical_results():
    reconciler = Reconciler(SUPPLIERS)
    transactions = _transactions(("T1", "2025-03-12", 1500.00, "PIX ACME LOGISTICA E TRANSPORTES"))
    invoices = _invoices(("NF1", "S1", "2025-03-10", 1500.00))
    assert reconciler.run(transactions, invoices) == reconciler.run(transactions, invoices)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"fee_tolerance": -1},
        {"ambiguity_margin": -0.1},
        {"tolerant_min_confidence": 0},
        {"multi_max_candidates": 3},
        {"exact_max_days": -1},
    ],
)
def test_config_rejects_values_that_silently_break_layers(kwargs):
    with pytest.raises(ValueError):  # noqa: PT011
        ReconciliationConfig(**kwargs)


def test_payment_before_the_due_date_matches_when_after_the_issue_date():
    invoices = _invoices(("NF1", "S1", "2025-05-05", 1500.00)).assign(
        earliest_date=pd.Timestamp("2025-04-01")
    )
    early = _transactions(("T1", "2025-05-02", 1500.00, "PIX ACME LOGISTICA E TRANSPORTES"))
    assert _run(early, invoices)["T1"].layer is Layer.EXACT

    before_issue = _transactions(("T1", "2025-03-30", 1500.00, "PIX ACME LOGISTICA E TRANSPORTES"))
    assert _run(before_issue, invoices)["T1"].status is MatchStatus.UNMATCHED


def test_installment_due_nearest_to_the_payment_wins_without_ambiguity():
    # Two equal installments of one invoice issued 05/03, due 05/04 and 05/05; the
    # abbreviated description sends the payment of 07/04 to the tolerant layer.
    invoices = _invoices(
        ("NF1-1", "S1", "2025-04-05", 1500.00), ("NF1-2", "S1", "2025-05-05", 1500.00)
    ).assign(earliest_date=pd.Timestamp("2025-03-05"))
    result = _run(
        _transactions(("T1", "2025-04-07", 1500.00, "PIX ACME LOGIST TRANS LT")), invoices
    )["T1"]
    assert result.invoice_ids == ("NF1-1",)
    assert result.status is MatchStatus.RECONCILED
