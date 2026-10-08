"""Business-day helpers."""

from __future__ import annotations

from datetime import date, timedelta

SATURDAY = 5


def is_weekend(day: date) -> bool:
    return day.weekday() >= SATURDAY


def roll_forward(day: date) -> date:
    """Return ``day`` itself if it is a business day, otherwise the next Monday."""
    while is_weekend(day):
        day += timedelta(days=1)
    return day


def roll_back(day: date) -> date:
    """Return ``day`` itself if it is a business day, otherwise the previous Friday."""
    while is_weekend(day):
        day -= timedelta(days=1)
    return day


def add_months(day: date, months: int) -> date:
    """First day of the month ``months`` after ``day``'s month."""
    index = day.year * 12 + (day.month - 1) + months
    return date(index // 12, index % 12 + 1, 1)


def month_starts(start: date, months: int) -> list[date]:
    first = date(start.year, start.month, 1)
    return [add_months(first, i) for i in range(months)]
