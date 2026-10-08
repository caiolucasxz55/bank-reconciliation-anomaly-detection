from datetime import date

import numpy as np
import pytest

from bankrecon.generator.config import NoiseConfig
from bankrecon.generator.invoices import Invoice
from bankrecon.generator.profiles import Frequency, PaymentMethod, SupplierProfile
from bankrecon.generator.statement import (
    BANK_FEES,
    DESCRIPTION_MAX_LEN,
    NoiseType,
    abbreviated_description,
    bank_description,
    build_statement,
)

NO_NOISE = NoiseConfig(0, 0, 0, 0)
END = date(2025, 12, 31)


def _profile(name="Acme Logística e Transportes Ltda", frequency=Frequency.WEEKLY):
    return SupplierProfile(
        "S001", name, "", frequency, 1000.0, 0.1, 0, PaymentMethod.PIX, date(2020, 1, 1)
    )


def _invoices(n=20):
    return [
        Invoice(f"NF{i:05d}", "S001", date(2025, 1, 6 + i), 1000.0 + i, date(2025, 1, 6 + i))
        for i in range(n)
    ]


def test_bank_description_is_a_prefix_of_the_normalized_name():
    assert bank_description(_profile()) == "PIX ACME LOGISTICA E TRANSPORTES"
    assert len(bank_description(_profile())) <= DESCRIPTION_MAX_LEN


def test_bank_description_has_no_trailing_space():
    assert not bank_description(_profile("Vale Verde Papelaria Ltda Filial")).endswith(" ")


def test_abbreviated_description_shortens_words_and_drops_stopwords():
    description = abbreviated_description(_profile(), np.random.default_rng(0))
    words = description.split()
    assert words[0] == "PIX"
    assert words[-1] == "LT"
    assert "E" not in words
    assert all(4 <= len(w) <= 6 for w in words[1:-1])


def test_clean_statement_has_one_exact_payment_per_invoice():
    invoices = _invoices()
    payments = build_statement([_profile()], invoices, NO_NOISE, np.random.default_rng(0), END)
    assert len(payments) == len(invoices)
    for payment, invoice in zip(payments, invoices, strict=True):
        assert payment.invoice_ids == [invoice.invoice_id]
        assert payment.amount == invoice.amount
        assert payment.date == invoice.scheduled_payment
        assert payment.is_clean


def test_multi_invoice_groups_sum_amounts():
    noise = NoiseConfig(0, 0, 1, 0)
    invoices = _invoices()
    payments = build_statement([_profile()], invoices, noise, np.random.default_rng(0), END)
    by_id = {inv.invoice_id: inv for inv in invoices}
    assert sum(len(p.invoice_ids) for p in payments) == len(invoices)
    for p in payments:
        if len(p.invoice_ids) > 1:
            assert NoiseType.MULTI_INVOICE in p.noise
            assert p.amount == pytest.approx(sum(by_id[i].amount for i in p.invoice_ids))
            assert p.date == max(by_id[i].scheduled_payment for i in p.invoice_ids)


def test_sporadic_suppliers_never_group_invoices():
    noise = NoiseConfig(0, 0, 1, 0)
    payments = build_statement(
        [_profile(frequency=Frequency.SPORADIC)], _invoices(), noise, np.random.default_rng(0), END
    )
    assert all(len(p.invoice_ids) == 1 for p in payments)


def test_late_payment_and_bank_fee():
    noise = NoiseConfig(late_payment=1, bank_fee=1, multi_invoice=0, truncated_description=0)
    invoices = _invoices()
    payments = build_statement([_profile()], invoices, noise, np.random.default_rng(0), END)
    for payment, invoice in zip(payments, invoices, strict=True):
        delay = (payment.date - invoice.scheduled_payment).days
        assert 6 <= delay <= 22
        assert round(invoice.amount - payment.amount, 2) in BANK_FEES
        assert set(payment.noise) == {NoiseType.LATE_PAYMENT, NoiseType.BANK_FEE}


def test_noise_config_validates_probabilities():
    with pytest.raises(ValueError, match="probability"):
        NoiseConfig(late_payment=1.5)


def test_late_payment_never_leaves_the_period():
    noise = NoiseConfig(late_payment=1, bank_fee=0, multi_invoice=0, truncated_description=0)
    invoices = _invoices()
    end = invoices[-1].scheduled_payment
    payments = build_statement([_profile()], invoices, noise, np.random.default_rng(0), end)
    assert max(p.date for p in payments) <= end
    assert NoiseType.LATE_PAYMENT not in payments[-1].noise
