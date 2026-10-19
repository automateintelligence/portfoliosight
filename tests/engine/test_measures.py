"""DR² and ES_2.5: analytic identities, the disclosed cash property, the tail-mean identities."""

from __future__ import annotations

import math
from dataclasses import FrozenInstanceError
from fractions import Fraction

import numpy as np
import pytest

from portfoliosight.engine import stats
from portfoliosight.engine.measures import (
    TAIL_FRACTION,
    Dr2,
    UndefinedMeasure,
    dr2,
    dr2_from,
    es_25,
)


def _factor_returns(seed: int, n: int = 6, rows: int = 800) -> np.ndarray:
    """Daily returns that share one positive factor: pairwise sample correlations are positive."""
    rng = np.random.default_rng(seed)
    load = rng.uniform(0.004, 0.009, n)
    factor = rng.normal(0.0, 1.0, (rows, 1))
    return factor * load + rng.normal(0.0, 0.004, (rows, n)) + 0.0003


def _dr_squared(w, sigma, cov) -> float:
    """DR² by explicit exactly-rounded sums, not by the matrix products the module uses."""
    w, sigma, cov = list(w), list(sigma), [list(row) for row in cov]
    n = len(w)
    numerator = math.fsum(w[i] * sigma[i] for i in range(n))
    variance = math.fsum(w[i] * cov[i][j] * w[j] for i in range(n) for j in range(n))
    return numerator**2 / variance


# ---- DR²: analytic identities -------------------------------------------------------------


@pytest.mark.parametrize(("rho", "expected"), [(0.95, 2 / 1.95), (0.0, 2.0), (-0.5, 4.0)])
def test_equal_weight_pair_of_equal_volatility_funds(rho, expected):
    cov = np.array([[1.0, rho], [rho, 1.0]])
    assert dr2_from(np.array([0.5, 0.5]), np.ones(2), cov) == pytest.approx(expected, rel=1e-13)


def test_correlation_095_pair_is_barely_more_than_one_fund():
    assert round(dr2_from(np.array([0.5, 0.5]), np.ones(2), [[1, 0.95], [0.95, 1]]), 2) == 1.03


def test_negative_correlation_control_exceeds_its_holding_count():
    held = 2
    assert dr2_from(np.array([0.5, 0.5]), np.ones(2), [[1.0, -0.5], [-0.5, 1.0]]) > held


@pytest.mark.parametrize("held", [1, 2, 3, 5, 8])
def test_uncorrelated_inverse_volatility_weights_score_the_holding_count(held):
    rng = np.random.default_rng(held)
    sigma = rng.uniform(0.01, 0.4, 8)
    chosen = rng.permutation(8)[:held]
    w = np.zeros(8)
    w[chosen] = 1.0 / sigma[chosen]
    w /= w.sum()
    assert dr2_from(w, sigma, np.diag(sigma**2)) == pytest.approx(held, rel=1e-12)


@pytest.mark.parametrize("window", ["fixed", "ew"])
def test_every_single_fund_scores_exactly_one(window):
    r = _factor_returns(5101)
    r[:, 4] = 0.0001  # constant: sigma sits on the floor
    omega = None if window == "fixed" else stats.ew_weights(len(r))
    m = stats.estimate_moments(r, omega=omega)
    for i in range(r.shape[1]):
        for weight in (1.0, 0.37):  # a single fund at any scale is still one fund
            w = np.zeros(r.shape[1])
            w[i] = weight
            assert abs(dr2(w, m).value - 1.0) <= 1e-9, (window, i, weight)


def test_scaling_all_weights_together_leaves_dr2_unchanged():
    m = stats.estimate_moments(_factor_returns(5102))
    w = np.array([0.3, 0.1, 0.2, 0.0, 0.25, 0.15])
    base = dr2(w, m).value
    for scale in (0.01, 0.5, 3.0, 1e4):
        assert dr2(scale * w, m).value == pytest.approx(base, rel=1e-12)


@pytest.mark.parametrize("window", ["fixed", "ew"])
def test_dr2_is_the_ratio_of_squared_weighted_volatility_to_variance(window):
    r = _factor_returns(5103)
    omega = None if window == "fixed" else stats.ew_weights(len(r))
    m = stats.estimate_moments(r, omega=omega)
    rng = np.random.default_rng(5104)
    for _ in range(20):
        w = rng.dirichlet(np.ones(r.shape[1]))
        assert dr2(w, m).value == pytest.approx(_dr_squared(w, m.sigma, m.cov), rel=1e-12)


# ---- DR²: the shrinkage it reports and the estimator it depends on -------------------------


def test_dr2_returns_the_shrinkage_the_moments_applied():
    r = _factor_returns(5105)
    w = np.full(6, 1.0 / 6.0)
    fixed = stats.estimate_moments(r)
    assert fixed.shrinkage is not None
    assert dr2(w, fixed).shrinkage == fixed.shrinkage
    ew = dr2(w, stats.estimate_moments(r, omega=stats.ew_weights(len(r))))
    assert ew.shrinkage == 0.2
    no_live_column = stats.estimate_moments(np.tile([0.0001, 0.0003], (252, 1)))
    assert no_live_column.shrinkage is None
    result = dr2(np.array([0.5, 0.5]), no_live_column)
    assert result.shrinkage is None
    assert result.value == pytest.approx(2.0, rel=1e-13)  # two floored, uncorrelated funds


def test_dr2_result_is_a_frozen_value_and_shrinkage():
    result = dr2(np.array([1.0]), stats.Moments(np.zeros(1), np.ones(1), np.eye(1), 10.0, 0.25))
    assert result == Dr2(value=1.0, shrinkage=0.25)
    with pytest.raises(FrozenInstanceError):
        result.value = 2.0  # type: ignore[misc]


def test_shrinkage_toward_the_identity_raises_dr2_for_non_negative_correlations():
    r = _factor_returns(5106)
    raw_corr = np.corrcoef(r, rowvar=False)
    assert (raw_corr >= 0.0).all()
    m = stats.estimate_moments(r)
    raw_cov = np.outer(m.sigma, m.sigma) * raw_corr  # the same sigma: only the correlation differs
    w = np.array([0.3, 0.1, 0.2, 0.05, 0.25, 0.1])
    assert dr2_from(w, m.sigma, raw_cov) < dr2(w, m).value


def test_shrinkage_toward_the_identity_lowers_dr2_for_a_negatively_correlated_pair():
    r = _factor_returns(5107, n=2)
    r[:, 1] = -r[:, 1] + 0.0006  # one fund is the other's mirror plus its own noise
    raw_corr = np.corrcoef(r, rowvar=False)
    assert raw_corr[0, 1] < -0.2
    m = stats.estimate_moments(r)
    raw_cov = np.outer(m.sigma, m.sigma) * raw_corr
    w = np.array([0.5, 0.5])
    assert dr2_from(w, m.sigma, raw_cov) > dr2(w, m).value


# ---- DR²: the zero-volatility holding, a disclosed property --------------------------------


def _risky_block(seed: int = 5108, n: int = 5) -> tuple[np.ndarray, np.ndarray]:
    m = stats.estimate_moments(_factor_returns(seed, n=n))
    return m.sigma, m.cov


def _with_zero_volatility_fund(sigma: np.ndarray, cov: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    n = len(sigma)
    full_cov = np.zeros((n + 1, n + 1))
    full_cov[:n, :n] = cov
    return np.append(sigma, 0.0), full_cov


def test_a_fund_with_sigma_exactly_zero_does_not_move_dr2():
    """Asserts two things, both exact up to rounding.

    (a) with the risky weights fixed, DR² is the same for every weight of the zero-volatility fund;
    (b) renormalizing the risky weights to make room for that weight, proportionally, leaves DR²
        the same too: it equals DR² of the risky weights alone.
    """
    sigma, cov = _risky_block()
    full_sigma, full_cov = _with_zero_volatility_fund(sigma, cov)
    risky = np.array([0.4, 0.1, 0.25, 0.05, 0.2])
    alone = _dr_squared(risky, sigma, cov)
    for cash in (0.0, 0.003, 0.25, 0.6, 0.97, 5.0):
        fixed_risky = np.append(risky, cash)
        assert dr2_from(fixed_risky, full_sigma, full_cov) == pytest.approx(alone, rel=1e-13), cash
    for cash in (0.0, 0.003, 0.25, 0.6, 0.97):
        summing_to_one = np.append((1.0 - cash) * risky, cash)
        assert summing_to_one.sum() == pytest.approx(1.0, abs=1e-15)
        assert dr2_from(summing_to_one, full_sigma, full_cov) == pytest.approx(alone, rel=1e-13)


def test_a_fund_on_the_sigma_floor_with_no_correlation_moves_dr2_by_a_derived_amount():
    """Production floors sigma at 1e-4, so a constant series is not exactly zero-volatility.

    stats leaves the floor fund uncorrelated with the rest. With its weight c, delta = c * 1e-4,
    A = w'sigma and V = w'Cw of the risky weights alone, DR² = (A + delta)² / (V + delta²), and
        DR² - A²/V = delta (2AV + (V - A²) delta) / (V (V + delta²)),
    which is about 2 delta / A of DR² (1.8e-5 at c = 0.01, 1.6e-3 at c = 0.9 for the weights below)
    and zero only at delta = 0.
    """
    r = _factor_returns(5109, n=5)
    r = np.column_stack([r, np.full(len(r), 0.0001)])
    m = stats.estimate_moments(r)
    assert m.sigma[5] == stats.SIGMA_FLOOR
    risky = np.array([0.4, 0.1, 0.25, 0.05, 0.2])
    a = float(risky @ m.sigma[:5])
    v = float(risky @ m.cov[:5, :5] @ risky)
    for cash in (0.01, 0.25, 0.9):
        delta = cash * stats.SIGMA_FLOOR
        got = dr2(np.append(risky, cash), m).value
        assert got == pytest.approx((a + delta) ** 2 / (v + delta**2), rel=1e-12)
        derived = delta * (2 * a * v + (v - a * a) * delta) / (v * (v + delta**2))
        assert got - a * a / v == pytest.approx(derived, rel=1e-6)
        assert got != a * a / v  # near-invariance, not invariance


@pytest.mark.parametrize("seed", [5110, 5111, 5112])
def test_a_correlated_fund_on_the_sigma_floor_stays_inside_the_triangle_bound(seed):
    """Bound for any correlation of the floor fund with the rest.

    With u = (w_risky, 0) and v = (0, c) in the covariance seminorm, ||u|| = sqrt(V) and
    ||v|| = delta = c * SIGMA_FLOOR, so sqrt(V) - delta <= ||u + v|| <= sqrt(V) + delta, and the
    numerator is A + delta. DR² of the mix therefore lies between (A + delta)² / (sqrt(V) + delta)²
    and (A + delta)² / (sqrt(V) - delta)².
    """
    m = stats.estimate_moments(_factor_returns(seed, n=6))
    corr = m.cov / np.outer(m.sigma, m.sigma)
    assert abs(corr[5, :5]).min() > 0.05  # really correlated with the rest
    sigma = m.sigma.copy()
    sigma[5] = stats.SIGMA_FLOOR
    cov = np.outer(sigma, sigma) * corr
    risky = np.array([0.4, 0.1, 0.25, 0.05, 0.2])
    a = float(risky @ sigma[:5])
    v = float(risky @ cov[:5, :5] @ risky)
    base = a * a / v
    moved = False
    for cash in (0.01, 0.25, 0.9):
        delta = cash * stats.SIGMA_FLOOR
        low = (a + delta) ** 2 / (math.sqrt(v) + delta) ** 2
        high = (a + delta) ** 2 / (math.sqrt(v) - delta) ** 2
        got = dr2_from(np.append(risky, cash), sigma, cov)
        assert low <= got <= high, cash
        moved |= got != base
    assert moved


# ---- DR²: the undefined condition and the input contract -------------------------------------


@pytest.mark.parametrize(
    ("weights", "sigma", "cov"),
    [
        ([1.0], [0.0], [[0.0]]),  # all cash
        ([0.0, 0.0], [0.1, 0.2], [[0.01, 0.0], [0.0, 0.04]]),  # no position
        ([0.3, 0.7], [0.0, 0.0], np.zeros((2, 2))),  # only zero-volatility funds
    ],
)
def test_exactly_zero_portfolio_variance_is_a_named_undefined_condition(weights, sigma, cov):
    with pytest.raises(UndefinedMeasure, match="portfolio variance is exactly zero"):
        dr2_from(np.array(weights), np.array(sigma), np.array(cov))


def test_the_undefined_condition_is_a_value_error_and_reaches_dr2():
    assert issubclass(UndefinedMeasure, ValueError)
    m = stats.estimate_moments(_factor_returns(5113))
    with pytest.raises(UndefinedMeasure):
        dr2(np.zeros(6), m)


def test_a_tiny_positive_variance_is_scored_not_screened_by_an_epsilon():
    for sigma in (1e-4, 1e-30, 1e-120):
        assert dr2_from(np.array([1.0]), np.array([sigma]), np.array([[sigma**2]])) == (
            pytest.approx(1.0, rel=1e-12)
        )


def test_a_negative_variance_is_a_malformed_covariance_not_an_undefined_score():
    with pytest.raises(ValueError, match="positive semidefinite") as raised:
        dr2_from(np.array([1.0, -1.0]), np.ones(2), np.array([[1.0, 2.0], [2.0, 1.0]]))
    assert not isinstance(raised.value, UndefinedMeasure)


_COV = np.array([[0.04, 0.01], [0.01, 0.09]])


@pytest.mark.parametrize(
    ("weights", "sigma", "cov", "message"),
    [
        (np.array([np.nan, 0.5]), np.array([0.2, 0.3]), _COV, "weights.*finite"),
        (np.array([0.5, np.inf]), np.array([0.2, 0.3]), _COV, "weights.*finite"),
        (np.array([0.5, 0.5]), np.array([np.nan, 0.3]), _COV, "sigma.*finite"),
        (
            np.array([0.5, 0.5]),
            np.array([0.2, 0.3]),
            np.array([[0.04, np.nan], [0.01, 0.09]]),
            "cov.*finite",
        ),
        (np.array([0.5, 0.5]), np.array([0.2, -0.3]), _COV, "sigma.*non-negative"),
        (np.array([0.5, 0.5, 0.0]), np.array([0.2, 0.3]), _COV, "sigma.*shape"),
        (np.array([0.5, 0.5]), np.array([0.2, 0.3]), np.eye(3), "cov.*shape"),
        (np.array([0.5, 0.5]), np.array([0.2, 0.3]), np.ones(4), "cov.*shape"),
        (np.array([[0.5, 0.5]]), np.array([0.2, 0.3]), _COV, "weights.*1-D"),
        (np.array([0.5, 0.5]), np.array([[0.2, 0.3]]), _COV, "sigma.*shape"),
        (np.array([]), np.array([]), np.zeros((0, 0)), "at least one"),
    ],
)
def test_dr2_from_rejects_malformed_inputs(weights, sigma, cov, message):
    with pytest.raises(ValueError, match=message):
        dr2_from(weights, sigma, cov)


# ---- ES_2.5 -----------------------------------------------------------------------------------


def _bad(x: np.ndarray) -> float:
    """Production's Bad: the linear-interpolation 2.5th percentile (ranges.one_year_ranges)."""
    return float(np.percentile(x, 2.5))


def test_the_tail_is_two_and_a_half_percent_held_exactly():
    assert TAIL_FRACTION == Fraction(1, 40)
    assert float(TAIL_FRACTION) == 0.025


@pytest.mark.parametrize(
    ("paths", "tail"),
    [
        (1, 1),
        (2, 1),
        (39, 1),
        (40, 1),
        (41, 2),
        (79, 2),
        (80, 2),
        (81, 3),
        (2000, 50),
        (10000, 250),
    ],
)
def test_the_tail_holds_ceil_of_two_and_a_half_percent_of_the_paths(paths, tail):
    x = np.random.default_rng(paths).permutation(paths).astype(float)  # 0, 1, ..., paths - 1
    assert es_25(x) == pytest.approx((tail - 1) / 2.0, abs=1e-12)  # mean of 0, ..., tail - 1


def test_the_tail_is_exact_where_two_and_a_half_percent_is_a_whole_number():
    for paths in range(40, 4001, 40):  # a float 0.025 * paths could round up past the integer
        x = np.arange(paths, dtype=float)
        assert es_25(x) == (paths // 40 - 1) / 2.0


def test_hand_built_40_path_sample_is_its_single_worst_outcome():
    x = np.array(
        [0.08, 0.02, -0.01, 0.15, 0.04, -0.12, 0.09, 0.0, 0.11, 0.05]
        + [0.07, 0.03, -0.04, 0.12, 0.06, 0.01, -0.02, 0.10, 0.13, 0.14]
        + [0.16, -0.07, 0.17, 0.18, -0.05, 0.19, 0.20, -0.03, 0.21, 0.22]
        + [0.23, 0.24, -0.06, 0.25, 0.26, 0.27, -0.08, 0.28, 0.29, 0.30]
    )
    assert len(x) == 40
    assert es_25(x) == -0.12  # ceil(0.025 * 40) = 1: the minimum, with no averaging error
    assert _bad(x) == pytest.approx(-0.12 + 0.975 * (-0.08 + 0.12), abs=1e-15)  # linear, > ES
    assert es_25(x) < _bad(x)


def test_2000_path_sample_is_the_mean_of_its_50_worst_by_an_independent_sorted_oracle():
    x = np.random.default_rng(6001).standard_t(4, 2000) * 0.12 + 0.07
    oracle = math.fsum(sorted(x.tolist())[:50]) / 50
    assert es_25(x) == pytest.approx(oracle, abs=1e-15)
    assert es_25(x) < _bad(x)


def test_10000_path_pool_is_the_mean_of_its_250_worst():
    x = np.random.default_rng(6002).normal(0.06, 0.15, 10000)
    assert es_25(x) == pytest.approx(math.fsum(sorted(x.tolist())[:250]) / 250, abs=1e-15)


def test_es_never_exceeds_bad_at_any_path_count_or_with_heavy_ties():
    rng = np.random.default_rng(6003)
    for paths in [*range(1, 301), 1999, 2000, 2001, 10000]:
        samples = {
            "normal": rng.normal(0.05, 0.15, paths),
            "heavy tail": rng.standard_t(2, paths) * 0.1,
            "ties": np.round(rng.normal(0.05, 0.15, paths), 1),  # few distinct values
            "constant": np.full(paths, 0.0731),
            "mass at ruin": np.where(rng.random(paths) < 0.1, -1.0, rng.normal(0.05, 0.1, paths)),
        }
        for name, x in samples.items():
            assert es_25(x) <= _bad(x), (paths, name)


def test_es_equals_bad_when_the_sample_is_constant_or_two_valued_with_a_deep_low_side():
    """Bad interpolates between sorted indices floor(h) and floor(h) + 1 <= k, so a low value held
    by at least k + 1 paths puts the whole tail and both interpolation ends on it."""
    for paths in (1, 40, 41, 100, 2000, 2001):
        k = -(-paths // 40)
        assert es_25(np.full(paths, 0.1)) == _bad(np.full(paths, 0.1)) == 0.1
        for low_paths in sorted({k + 1, paths // 2, paths - 1}):
            if k + 1 <= low_paths <= paths:
                x = np.where(np.arange(paths) < low_paths, -0.3, 0.2)
                assert es_25(x) == _bad(x) == -0.3, (paths, low_paths)


def test_es_is_strictly_below_bad_when_the_low_value_is_shallower_than_the_tail():
    x = np.full(2000, 0.1)
    x[:10] = -0.4  # 10 of the 50 tail paths are low; Bad (index 49.975) is 0.1
    assert es_25(x) == pytest.approx((10 * -0.4 + 40 * 0.1) / 50, abs=1e-15) == pytest.approx(0.0)
    assert _bad(x) == pytest.approx(0.1)
    assert es_25(x) < _bad(x)


def test_ties_at_the_cut_are_interchangeable():
    """80 paths, tail of 2: the worst, then three paths tied at -0.3 straddling the cut."""
    base = np.concatenate([[-0.5, -0.3, -0.3, -0.3], np.linspace(0.0, 0.4, 76)])
    assert len(base) == 80
    assert es_25(base) == pytest.approx(-0.4, abs=1e-15)  # -0.5 and one of the tied -0.3
    assert es_25(base) < _bad(base) == pytest.approx(-0.3, abs=1e-15)
    for seed in range(20):  # whichever tied path the sort puts first, the answer is the same
        assert es_25(np.random.default_rng(seed).permutation(base)) == es_25(base)
    # the mean of the k smallest values, not of the values at most the percentile
    below_or_at_bad = base[base <= _bad(base)]
    assert len(below_or_at_bad) == 4 and es_25(base) != float(np.mean(below_or_at_bad))


def test_es_is_invariant_to_path_order_bit_for_bit():
    x = np.random.default_rng(6004).standard_t(3, 2000) * 0.1
    expected = es_25(x)
    rng = np.random.default_rng(6005)
    for _ in range(25):
        assert es_25(rng.permutation(x)) == expected
    assert es_25(x[::-1]) == expected
    assert es_25(np.sort(x)) == expected


def test_es_ignores_the_paths_above_its_tail():
    x = np.random.default_rng(6006).normal(0.05, 0.15, 2000)
    changed = x.copy()
    changed[x > np.sort(x)[49]] += 5.0  # move every path above the 50 worst
    assert es_25(changed) == es_25(x)


def test_equal_bad_with_different_tails_gives_different_es():
    shallow = np.full(2000, 0.1)
    deep = shallow.copy()
    shallow[:50] = -0.2
    deep[:50] = -0.2
    deep[:5] = -0.9  # same sorted indices 49 and 50, so the same Bad, but a deeper tail
    assert _bad(shallow) == _bad(deep)
    assert es_25(shallow) == pytest.approx(-0.2, abs=1e-15)
    assert es_25(deep) == pytest.approx((5 * -0.9 + 45 * -0.2) / 50, abs=1e-15)
    assert es_25(deep) - es_25(shallow) < -0.06


def test_es_accepts_integers_and_returns_a_float():
    result = es_25(np.array([3, 1, 2] * 14))
    assert isinstance(result, float) and result == 1.0


@pytest.mark.parametrize(
    ("returns", "message"),
    [
        (np.array([]), "at least one"),
        (np.array([0.1, np.nan, 0.2]), "finite"),
        (np.array([0.1, np.inf]), "finite"),
        (np.array([0.1, -np.inf]), "finite"),
        (np.zeros((4, 2)), "1-D"),
        (np.float64(0.1), "1-D"),
    ],
)
def test_es_rejects_malformed_inputs(returns, message):
    with pytest.raises(ValueError, match=message):
        es_25(returns)
