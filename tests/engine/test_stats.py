"""Moments, the menu-beta blend, the risk-free rate and the six-month range (spec 4.3, 4.9)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from sklearn.covariance import LedoitWolf

from portfoliosight.engine import ENGINE_VERSION, stats


def _returns(degenerate: bool = False) -> np.ndarray:
    rng = np.random.default_rng(3201)
    rows, n = 800, 6
    load = rng.normal(0.0, 1.0, (n, 2)) * 0.006
    r = rng.normal(0.0, 1.0, (rows, 2)) @ load.T + rng.normal(0.0, 0.005, (rows, n)) + 0.0003
    if degenerate:
        r[:, 1] = 0.00012 + rng.normal(0.0, 0.003 / np.sqrt(252.0), rows)  # about 0.3% a year
        r[:, 4] = 0.0001  # exactly constant
    return r


def _own_scatter(r: np.ndarray, omega: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    mean = omega @ r
    x = r - mean
    return mean, (x * omega[:, None]).T @ x / (1.0 - (omega**2).sum())


def test_engine_version_is_the_spec_version():
    assert ENGINE_VERSION == "0.3.0"


def test_fixed_window_is_ledoit_wolf_on_correlations():
    r = _returns()
    m = stats.estimate_moments(r)
    sd = r.std(axis=0, ddof=1)
    assert np.abs(m.mu - 252.0 * r.mean(axis=0)).max() <= 1e-12
    assert np.abs(m.sigma - np.sqrt(252.0) * sd).max() <= 1e-12
    q = LedoitWolf().fit(r / sd).covariance_
    corr = q / np.sqrt(np.outer(np.diag(q), np.diag(q)))
    assert np.abs(m.cov - np.outer(m.sigma, m.sigma) * corr).max() <= 1e-12
    assert np.abs(m.cov - np.cov(r, rowvar=False) * 252.0).max() > 1e-7  # really shrunk
    assert np.abs(np.diag(m.cov) - m.sigma**2).max() <= 1e-15
    assert np.array_equal(m.cov, m.cov.T)
    assert m.t_eff == float(len(r))
    # shrinking correlations leaves every fund its own variance, whatever its scale
    scaled = stats.estimate_moments(r * np.array([1.0, 50.0, 1.0, 0.02, 1.0, 1.0]))
    assert np.abs(scaled.sigma / m.sigma - np.array([1.0, 50.0, 1.0, 0.02, 1.0, 1.0])).max() < 1e-9
    assert np.abs(scaled.cov / np.outer(scaled.sigma, scaled.sigma) - corr).max() <= 1e-9


def test_ew_weights_have_a_252_day_half_life():
    omega = stats.ew_weights(900)
    own = 0.5 ** ((899 - np.arange(900)) / 252.0)
    assert np.abs(omega - own / own.sum()).max() <= 1e-15
    assert abs(omega.sum() - 1.0) <= 1e-12
    assert abs(omega[-1] / omega[-253] - 2.0) <= 1e-9 and omega[-1] > omega[0]
    assert (
        abs(stats.ew_weights(10, halflife=5)[-1] / stats.ew_weights(10, halflife=5)[-6] - 2) < 1e-9
    )
    assert stats.ew_weights(1).tolist() == [1.0]
    with pytest.raises(ValueError, match="at least one row"):
        stats.ew_weights(0)


def test_ew_path_uses_the_weighted_sample_correction_and_fixed_shrinkage():
    r = _returns()
    rows, n = r.shape
    fixed = stats.estimate_moments(r)
    uniform = stats.estimate_moments(r, omega=np.full(rows, 1.0 / rows))
    assert np.abs(uniform.sigma - fixed.sigma).max() <= 1e-12
    assert np.abs(uniform.mu - fixed.mu).max() <= 1e-12
    assert abs(uniform.t_eff - rows) <= 1e-6

    omega = stats.ew_weights(rows)
    m = stats.estimate_moments(r, omega=omega)
    mean, s = _own_scatter(r, omega)
    sigma = np.sqrt(252.0 * np.diag(s))
    assert np.abs(m.mu - 252.0 * mean).max() <= 1e-12
    assert np.abs(m.sigma - sigma).max() <= 1e-12
    corr = s / np.sqrt(np.outer(np.diag(s), np.diag(s)))
    assert np.abs(m.cov - np.outer(sigma, sigma) * (0.8 * corr + 0.2 * np.eye(n))).max() <= 1e-12
    assert abs(m.t_eff - 1.0 / (omega**2).sum()) <= 1e-9 and m.t_eff < rows - 1
    assert np.abs(m.sigma - fixed.sigma).max() > 1e-6
    assert np.array_equal(m.cov, m.cov.T)


def test_floor_applies_before_factorization_in_both_paths():
    r = _returns(degenerate=True)
    rows = len(r)
    own_sd = np.sqrt(252.0) * r.std(axis=0, ddof=1)
    assert 0.002 < own_sd[1] < 0.004 and own_sd[4] < 1e-12
    paths = {
        "fixed": stats.estimate_moments(r),
        "ew-uniform": stats.estimate_moments(r, omega=np.full(rows, 1.0 / rows)),
        "ew": stats.estimate_moments(r, omega=stats.ew_weights(rows)),
    }
    for name, m in paths.items():
        assert np.isfinite(m.sigma).all() and np.isfinite(m.cov).all(), name
        assert m.sigma[4] == stats.SIGMA_FLOOR == 1e-4, name
        assert (m.sigma >= 1e-4).all(), name
        corr = m.cov / np.outer(m.sigma, m.sigma)
        assert np.abs(np.diag(corr) - 1.0).max() <= 1e-12, name
        assert np.abs(np.delete(corr[4], 4)).max() <= 1e-9, name  # no made-up correlation
        assert np.abs(np.diag(m.cov) - m.sigma**2).max() <= 1e-15, name
        np.linalg.cholesky(m.cov)
    for name in ("fixed", "ew-uniform"):
        assert abs(paths[name].sigma[1] - own_sd[1]) <= 1e-12, name
        assert np.abs(paths[name].sigma[[0, 2, 3, 5]] - own_sd[[0, 2, 3, 5]]).max() <= 1e-12


def test_floor_changes_the_variance_never_the_correlation():
    """A fund below the floor that still moves keeps the correlations its returns show."""
    rng = np.random.default_rng(3204)
    base = rng.normal(0.0, 1.0, 500)
    other = rng.normal(0.0, 0.01, 500)
    r = np.column_stack([1e-6 * base, 0.01 * base, other])  # the first two move together
    assert np.sqrt(252.0) * r[:, 0].std(ddof=1) < stats.SIGMA_FLOOR
    weighted = stats.estimate_moments(r, omega=stats.ew_weights(500))
    corr = weighted.cov / np.outer(weighted.sigma, weighted.sigma)
    assert weighted.sigma[0] == 1e-4 and abs(corr[0, 1] - 0.8) <= 1e-12  # 0.8 R + 0.2 I, R = 1
    assert abs(corr[0, 2] - corr[1, 2]) <= 1e-12
    fixed = stats.estimate_moments(r)
    corr = fixed.cov / np.outer(fixed.sigma, fixed.sigma)
    assert fixed.sigma[0] == 1e-4 and corr[0, 1] > 0.98 and abs(corr[0, 2] - corr[1, 2]) <= 1e-12
    # the same matrix as for the fund scaled up above the floor: only its variance differs
    scaled = stats.estimate_moments(r * np.array([1e4, 1.0, 1.0]))
    assert np.abs(scaled.cov / np.outer(scaled.sigma, scaled.sigma) - corr).max() <= 1e-9
    np.linalg.cholesky(fixed.cov)
    np.linalg.cholesky(weighted.cov)


def test_as_correlation_treats_a_zero_scale_as_uncorrelated():
    matrix = np.array([[4.0, 0.0, 1.0], [0.0, 0.0, 0.0], [1.0, 0.0, 1.0]])
    corr = stats._as_correlation(matrix, np.sqrt(np.diag(matrix)))
    assert np.array_equal(corr, np.array([[1.0, 0.0, 0.5], [0.0, 1.0, 0.0], [0.5, 0.0, 1.0]]))


def test_funds_that_do_not_vary_are_uncorrelated_with_each_other():
    """Two constant series have no correlation to estimate; rounding must not invent one."""
    r = np.tile([0.0001, 0.0003], (252, 1))
    for name, omega in (("fixed", None), ("ew", stats.ew_weights(252))):
        m = stats.estimate_moments(r, omega)
        assert np.array_equal(m.sigma, [1e-4, 1e-4]), name
        assert np.array_equal(m.cov, 1e-8 * np.eye(2)), name
        assert np.full(2, 0.5) @ m.cov @ np.full(2, 0.5) == pytest.approx(0.5e-8, rel=1e-12), name
        np.linalg.cholesky(m.cov)


def test_funds_that_do_not_vary_take_no_part_in_the_shrinkage():
    """The other funds keep the correlations they have in a menu without the constant ones."""
    r = _returns()
    still = np.column_stack([r[:, 0], np.full(len(r), 0.0001), r[:, 1:], np.full(len(r), 0.0003)])
    moving = [0, 2, 3, 4, 5, 6]
    for name, omega in (("fixed", None), ("ew", stats.ew_weights(len(r)))):
        alone = stats.estimate_moments(r, omega)
        m = stats.estimate_moments(still, omega)
        assert np.abs(m.cov[np.ix_(moving, moving)] - alone.cov).max() <= 1e-15, name
        rest = np.delete(m.cov, moving, axis=0)
        assert np.array_equal(rest, 1e-8 * np.eye(8)[[1, 7]]), name
        np.linalg.cholesky(m.cov)


def test_fixed_window_records_the_ledoit_wolf_shrinkage_it_applied():
    r = _returns()
    sd = r.std(axis=0, ddof=1)
    expected = LedoitWolf().fit(r / sd).shrinkage_
    m = stats.estimate_moments(r)
    assert m.shrinkage is not None
    assert 0.0 < m.shrinkage < 1.0
    assert abs(m.shrinkage - expected) <= 1e-15


def test_fixed_window_shrinkage_comes_from_the_live_columns_only():
    r = _returns(degenerate=True)  # column 4 is constant: no scale, no part in the fit
    live = [0, 1, 2, 3, 5]
    sd = r.std(axis=0, ddof=1)
    expected = LedoitWolf().fit(r[:, live] / sd[live]).shrinkage_
    m = stats.estimate_moments(r)
    assert m.shrinkage is not None
    assert abs(m.shrinkage - expected) <= 1e-15
    assert abs(m.shrinkage - LedoitWolf().fit(r / np.where(sd > 1e-9, sd, 1.0)).shrinkage_) > 1e-6


def test_fixed_window_without_a_live_column_has_no_shrinkage():
    r = np.tile([0.0001, 0.0003], (252, 1))
    assert stats.estimate_moments(r).shrinkage is None


def test_ew_window_records_its_fixed_shrinkage_explicitly():
    r = _returns()
    for omega in (stats.ew_weights(len(r)), np.full(len(r), 1.0 / len(r))):
        m = stats.estimate_moments(r, omega=omega)
        assert m.shrinkage == 0.2 and isinstance(m.shrinkage, float)
    constant = np.tile([0.0001, 0.0003], (252, 1))  # no live column, still the fixed 0.2
    assert stats.estimate_moments(constant, omega=stats.ew_weights(252)).shrinkage == 0.2


def test_moments_built_without_a_shrinkage_keep_working():
    m = stats.Moments(mu=np.zeros(2), sigma=np.ones(2), cov=np.eye(2), t_eff=10.0)
    assert m.shrinkage is None
    with pytest.raises(AttributeError):
        m.shrinkage = 0.1  # type: ignore[misc]  # still frozen


def test_recording_the_shrinkage_leaves_the_moments_as_they_were():
    """Expected values are an inline reimplementation of the estimator before the field existed."""
    r = _returns(degenerate=True)
    rows, n = r.shape
    sd = r.std(axis=0, ddof=1)
    live = sd > 1e-9
    fit = LedoitWolf().fit(r[:, live] / sd[live]).covariance_
    corr = np.eye(n)
    corr[np.ix_(live, live)] = fit / np.sqrt(np.outer(np.diag(fit), np.diag(fit)))
    sigma = np.maximum(np.sqrt(252.0) * sd, 1e-4)
    fixed = stats.estimate_moments(r)
    assert np.abs(fixed.mu - 252.0 * r.mean(axis=0)).max() <= 1e-12
    assert np.abs(fixed.sigma - sigma).max() <= 1e-12
    assert np.abs(fixed.cov - np.outer(sigma, sigma) * corr).max() <= 1e-12
    assert fixed.t_eff == float(rows)

    omega = stats.ew_weights(rows)
    mean, s = _own_scatter(r, omega)
    ew_live = np.diag(s) > 0
    ew_sd = np.sqrt(np.diag(s))
    ew_corr = np.eye(n)
    ew_corr[np.ix_(ew_live, ew_live)] = s[np.ix_(ew_live, ew_live)] / np.outer(
        ew_sd[ew_live], ew_sd[ew_live]
    )
    ew_sigma = np.maximum(np.sqrt(252.0) * ew_sd, 1e-4)
    weighted = stats.estimate_moments(r, omega=omega)
    assert np.abs(weighted.mu - 252.0 * mean).max() <= 1e-12
    assert np.abs(weighted.sigma - ew_sigma).max() <= 1e-12
    expected_cov = np.outer(ew_sigma, ew_sigma) * (0.8 * ew_corr + 0.2 * np.eye(n))
    assert np.abs(weighted.cov - expected_cov).max() <= 1e-12
    assert abs(weighted.t_eff - 1.0 / (omega**2).sum()) <= 1e-9


@pytest.mark.parametrize(
    ("returns", "omega", "message"),
    [
        (np.zeros(5), None, "T x N"),
        (np.zeros((1, 3)), None, "T x N"),
        (np.zeros((4, 0)), None, "T x N"),
        (np.array([[0.01, np.nan], [0.0, 0.01], [0.0, 0.0]]), None, "non-finite"),
        (np.zeros((4, 2)), np.full(3, 1 / 3), "one weight per row"),
        (np.zeros((4, 2)), np.array([0.5, 0.5, 0.5, -0.5]), "non-negative"),
        (np.zeros((4, 2)), np.full(4, 0.3), "sum to 1"),
        (np.zeros((4, 2)), np.array([0.0, 0.0, 0.0, 1.0]), "more than one row"),
    ],
)
def test_estimate_moments_rejects_bad_inputs(returns, omega, message):
    with pytest.raises(ValueError, match=message):
        stats.estimate_moments(returns, omega=omega)


def test_menu_beta_blend_scales_the_premium_by_beta():
    rng = np.random.default_rng(3202)
    n = 7
    a = rng.normal(size=(n, n))
    cov = (a @ a.T / n + 0.2 * np.eye(n)) * 0.03
    w_eq = np.full(n, 1.0 / n)
    beta = cov @ w_eq / (w_eq @ cov @ w_eq)
    mu_hat = rng.uniform(0.02, 0.12, n)
    mu_s, pi = stats.menu_beta_blend(mu_hat, cov, 0.03)
    assert abs(w_eq @ pi - w_eq @ mu_hat) <= 1e-12  # the menu's average return is preserved
    assert np.abs(pi - (0.03 + beta * (w_eq @ mu_hat - 0.03))).max() <= 1e-12
    assert np.abs(mu_s - (0.5 * mu_hat + 0.5 * pi)).max() <= 1e-15
    # a cash-like fund (beta near 0) is pulled toward r_f, not toward the equity average
    cash_cov = np.diag([1e-6, 0.03, 0.04])
    cash_mu, cash_pi = stats.menu_beta_blend(np.array([0.035, 0.09, 0.10]), cash_cov, 0.03)
    assert abs(cash_pi[0] - 0.03) < 1e-3 and cash_pi[1] > 0.06
    assert abs(cash_mu[0] - (0.5 * 0.035 + 0.5 * cash_pi[0])) <= 1e-15

    for low_mu, rf in (
        (rng.uniform(-0.05, 0.02, n), 0.045),
        (np.full(n, 0.04) + np.linspace(-0.01, 0.01, n), 0.04),
    ):
        mu_s, pi = stats.menu_beta_blend(low_mu, cov, rf)
        assert np.abs(pi - rf).max() <= 1e-15  # the prior collapses to cash
        assert np.abs(mu_s - (0.5 * low_mu + 0.5 * rf)).max() <= 1e-15


def test_risk_free_rate_prefers_sgov_then_tsp_g_then_four_percent():
    rng = np.random.default_rng(3203)
    index = pd.bdate_range(end="2026-06-30", periods=400, name="date")
    sgov = pd.Series(0.00018 + rng.normal(0.0, 1e-5, 400), index=index)
    tsp_g = pd.Series(0.00011 + rng.normal(0.0, 1e-5, 400), index=index)
    r_sgov = float(np.prod(1.0 + sgov.to_numpy()[-252:]) - 1.0)
    r_tsp = float(np.prod(1.0 + tsp_g.to_numpy()[-252:]) - 1.0)
    assert abs(stats.risk_free_rate({"TSP-G": tsp_g, "SGOV": sgov}) - r_sgov) <= 1e-15
    assert abs(stats.risk_free_rate({"TSP-G": tsp_g}) - r_tsp) <= 1e-15
    assert stats.risk_free_rate({"VTI": sgov}) == stats.RISK_FREE_FALLBACK == 0.04
    assert stats.risk_free_rate({}) == 0.04
    # missing days are not returns, and a year needs 252 of them
    holed = sgov.copy()
    holed.iloc[[5, 399]] = np.nan
    expected = float(np.prod(1.0 + holed.dropna().to_numpy()[-252:]) - 1.0)
    assert abs(stats.risk_free_rate({"SGOV": holed}) - expected) <= 1e-15
    assert abs(stats.risk_free_rate({"SGOV": sgov.iloc[:251], "TSP-G": tsp_g}) - r_tsp) <= 1e-15
    assert stats.risk_free_rate({"SGOV": sgov.iloc[:251]}) == 0.04
