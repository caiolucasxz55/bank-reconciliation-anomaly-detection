from collections import Counter
from datetime import date

import numpy as np

from bankrecon.generator.profiles import Frequency, SupplierProfile, build_profiles

START = date(2025, 1, 1)


def _profiles(count=30, late=3, seed=0):
    return build_profiles(np.random.default_rng(seed), count, START, late)


def test_frequency_mix():
    counts = Counter(p.frequency for p in _profiles())
    assert counts == {Frequency.WEEKLY: 8, Frequency.MONTHLY: 14, Frequency.SPORADIC: 8}


def test_payment_day_matches_frequency():
    for p in _profiles():
        if p.frequency is Frequency.MONTHLY:
            assert 1 <= p.payment_day <= 28
        elif p.frequency is Frequency.WEEKLY:
            assert 0 <= p.payment_day <= 4
        else:
            assert p.payment_day is None


def test_late_registered_suppliers_are_not_weekly():
    late = [p for p in _profiles() if p.registered_at > START]
    assert len(late) == 3
    assert all(p.frequency is not Frequency.WEEKLY for p in late)


def test_ids_are_sequential_with_offset():
    ids = [p.supplier_id for p in build_profiles(np.random.default_rng(0), 3, START, 0, 30)]
    assert ids == ["S031", "S032", "S033"]


def test_draw_amount_is_centered_on_mean():
    profile = _profiles()[0]
    rng = np.random.default_rng(1)
    amounts = np.array([profile.draw_amount(rng) for _ in range(4000)])
    assert abs(amounts.mean() / profile.mean_amount - 1) < 0.02
    assert all(round(a, 2) == a for a in amounts[:50])


def test_draw_amount_has_floor():
    profile = SupplierProfile(
        "S1", "X", "", Frequency.SPORADIC, 1.0, 0.1, None, _profiles()[0].payment_method, START
    )
    assert profile.draw_amount(np.random.default_rng(0)) == 10.0
