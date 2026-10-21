import math

import pytest

from holdline import stats


def test_wilson_known_values():
    lo, hi = stats.wilson(8, 10)
    assert lo == pytest.approx(0.4902, abs=1e-3) and hi == pytest.approx(0.9433, abs=1e-3)
    assert stats.wilson(0, 10)[0] == 0.0 and stats.wilson(10, 10)[1] == 1.0
    assert stats.wilson(0, 0) == (0.0, 1.0)


def test_pass_at_k_and_pass_hat_k():
    assert stats.pass_hat_k(4, 4, 4) == 1.0
    assert stats.pass_hat_k(4, 3, 4) == 0.0
    assert stats.pass_hat_k(4, 2, 2) == pytest.approx(1 / 6)
    assert stats.pass_at_k(4, 1, 2) == pytest.approx(0.5)
    assert stats.pass_at_k(4, 0, 2) == 0.0
    with pytest.raises(ValueError):
        stats.pass_hat_k(2, 1, 3)


def test_mcnemar_exact():
    assert stats.mcnemar_exact(0, 0) == 1.0
    # 8 regressions, 0 fixes: 2 * 0.5^8
    assert stats.mcnemar_exact(8, 0) == pytest.approx(2 / 256)
    assert stats.mcnemar_exact(3, 3) == 1.0
    assert stats.mcnemar_exact(1, 5) == stats.mcnemar_exact(5, 1)


def test_bootstrap_is_seeded_and_brackets_estimate():
    pairs = [(1, 0)] * 6 + [(1, 1)] * 14
    a = stats.bootstrap_mean_diff(pairs)
    assert a == stats.bootstrap_mean_diff(pairs)
    est, lo, hi = a
    assert est == pytest.approx(-0.3) and lo <= est <= hi and hi < 0
    assert stats.bootstrap_mean([]) == (0.0, 0.0, 0.0)


def test_cohen_kappa():
    a = [1, 1, 0, 0, 1, 0, 1, 0]
    assert stats.cohen_kappa(a, a) == 1.0
    assert stats.cohen_kappa(a, [1 - x for x in a]) == -1.0
    # 50 items: po = 35/50 = 0.7; human passes 35, judge 30 -> pe = .7*.6 + .3*.4 = 0.54
    h = [1] * 25 + [1] * 10 + [0] * 5 + [0] * 10
    j = [1] * 25 + [0] * 10 + [1] * 5 + [0] * 10
    assert stats.cohen_kappa(h, j) == pytest.approx((0.7 - 0.54) / (1 - 0.54))
    k, lo, hi = stats.kappa_ci(h, j)
    assert lo <= k <= hi
    assert math.isnan(stats.cohen_kappa([], []))
    assert stats.describe_kappa(0.85) == "almost perfect" and stats.describe_kappa(0.5) == "moderate"
