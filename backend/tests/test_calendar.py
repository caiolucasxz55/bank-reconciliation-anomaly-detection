from datetime import date

from bankrecon.calendar import add_months, is_weekend, month_starts, roll_forward


def test_is_weekend():
    assert is_weekend(date(2025, 1, 4))  # Saturday
    assert is_weekend(date(2025, 1, 5))  # Sunday
    assert not is_weekend(date(2025, 1, 6))


def test_roll_forward_moves_weekends_to_monday():
    assert roll_forward(date(2025, 1, 4)) == date(2025, 1, 6)
    assert roll_forward(date(2025, 1, 5)) == date(2025, 1, 6)
    assert roll_forward(date(2025, 1, 7)) == date(2025, 1, 7)


def test_add_months_crosses_year():
    assert add_months(date(2025, 11, 20), 2) == date(2026, 1, 1)
    assert add_months(date(2025, 1, 31), 0) == date(2025, 1, 1)


def test_month_starts():
    assert month_starts(date(2025, 12, 15), 3) == [
        date(2025, 12, 1),
        date(2026, 1, 1),
        date(2026, 2, 1),
    ]
