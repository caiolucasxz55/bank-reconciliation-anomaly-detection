from datetime import date, timedelta

import numpy as np

from bankrecon.calendar import is_weekend
from bankrecon.generator.invoices import MAX_ISSUE_LEAD_DAYS, generate_invoices
from bankrecon.generator.profiles import Frequency, PaymentMethod, SupplierProfile

START, END = date(2025, 1, 1), date(2025, 12, 31)


def _profile(frequency, payment_day, registered_at=date(2020, 1, 1), sid="S001"):
    return SupplierProfile(
        sid, "Acme", "", frequency, 1000.0, 0.1, payment_day, PaymentMethod.PIX, registered_at
    )


def _invoices(*profiles):
    return generate_invoices(list(profiles), np.random.default_rng(0), START, END)


def test_monthly_supplier_gets_one_invoice_per_month_on_its_day():
    invoices = _invoices(_profile(Frequency.MONTHLY, 15))
    assert len(invoices) == 12
    for inv in invoices:
        nominal = inv.scheduled_payment
        assert nominal.day == 15 or (is_weekend(nominal - timedelta(days=1)) and nominal.day <= 17)


def test_monthly_payment_day_is_clamped_to_month_length():
    invoices = _invoices(_profile(Frequency.MONTHLY, 28))
    assert len(invoices) == 12  # February included


def test_weekly_supplier_pays_on_its_weekday():
    invoices = _invoices(_profile(Frequency.WEEKLY, 2))
    assert 51 <= len(invoices) <= 53
    assert {inv.scheduled_payment.weekday() for inv in invoices} == {2}


def test_payments_are_business_days_close_to_issue():
    invoices = _invoices(
        _profile(Frequency.MONTHLY, 6),
        _profile(Frequency.SPORADIC, None, sid="S002"),
        _profile(Frequency.WEEKLY, 0, sid="S003"),
    )
    for inv in invoices:
        assert not is_weekend(inv.scheduled_payment)
        assert 0 <= (inv.scheduled_payment - inv.issue_date).days <= MAX_ISSUE_LEAD_DAYS + 2
        assert inv.issue_date >= START
        assert inv.scheduled_payment <= END


def test_no_invoice_before_registration():
    registered = date(2025, 6, 10)
    invoices = _invoices(_profile(Frequency.MONTHLY, 5, registered_at=registered))
    assert invoices
    assert all(inv.issue_date >= registered for inv in invoices)


def test_ids_follow_issue_order():
    invoices = _invoices(_profile(Frequency.WEEKLY, 1), _profile(Frequency.MONTHLY, 3, sid="S2"))
    assert [inv.invoice_id for inv in invoices] == [
        f"NF{i:05d}" for i in range(1, len(invoices) + 1)
    ]
    assert [inv.issue_date for inv in invoices] == sorted(inv.issue_date for inv in invoices)
