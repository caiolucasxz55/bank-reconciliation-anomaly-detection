"""Invoice schedule: when each supplier bills and when it would normally be paid."""

from __future__ import annotations

import calendar as std_calendar
from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np

from bankrecon.calendar import month_starts, roll_forward
from bankrecon.generator.profiles import SPORADIC_MEAN_GAP_DAYS, Frequency, SupplierProfile

# Invoices are issued up to this many days before the scheduled payment. Together with the
# weekend roll (up to 2 days) a clean payment lands at most 5 days after the invoice.
MAX_ISSUE_LEAD_DAYS = 3


@dataclass
class Invoice:
    invoice_id: str
    supplier_id: str
    issue_date: date
    amount: float
    # When the invoice is normally paid; not part of the exported invoice table.
    scheduled_payment: date


def _scheduled_dates(
    profile: SupplierProfile, rng: np.random.Generator, start: date, end: date
) -> list[date]:
    """Nominal payment dates (before weekend roll) for one supplier inside [start, end]."""
    if profile.frequency is Frequency.MONTHLY:
        assert profile.payment_day is not None
        n_months = (end.year - start.year) * 12 + end.month - start.month + 1
        dates = []
        for month in month_starts(start, n_months):
            last_day = std_calendar.monthrange(month.year, month.month)[1]
            dates.append(month.replace(day=min(profile.payment_day, last_day)))
        return dates
    if profile.frequency is Frequency.WEEKLY:
        assert profile.payment_day is not None
        first = start + timedelta(days=(profile.payment_day - start.weekday()) % 7)
        return [first + timedelta(weeks=k) for k in range((end - first).days // 7 + 1)]

    dates = []
    current = start + timedelta(days=int(rng.integers(0, SPORADIC_MEAN_GAP_DAYS)))
    while current <= end:
        dates.append(current)
        current += timedelta(days=max(7, int(rng.exponential(SPORADIC_MEAN_GAP_DAYS))))
    return dates


def generate_invoices(
    profiles: list[SupplierProfile], rng: np.random.Generator, start: date, end: date
) -> list[Invoice]:
    """Generate every invoice issued in [start, end], ordered by issue date."""
    invoices: list[Invoice] = []
    for profile in profiles:
        for nominal in _scheduled_dates(profile, rng, start, end):
            payment = roll_forward(nominal)
            issue = nominal - timedelta(days=int(rng.integers(0, MAX_ISSUE_LEAD_DAYS + 1)))
            if issue < max(start, profile.registered_at) or payment > end:
                continue
            invoices.append(
                Invoice(
                    invoice_id="",
                    supplier_id=profile.supplier_id,
                    issue_date=issue,
                    amount=profile.draw_amount(rng),
                    scheduled_payment=payment,
                )
            )
    invoices.sort(key=lambda inv: (inv.issue_date, inv.supplier_id))
    for i, invoice in enumerate(invoices, start=1):
        invoice.invoice_id = f"NF{i:05d}"
    return invoices
