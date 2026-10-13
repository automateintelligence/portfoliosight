"""Minimum torsion and the effective number of bets (spec 4.6)."""

from __future__ import annotations

import math

import numpy as np
import pytest
from scipy.linalg import expm

from portfoliosight.engine import torsion
from portfoliosight.engine.torsion import (
    TorsionError,
    bet_shares,
    effective_number_of_bets,
    enb,
    min_torsion,
    torsion_basis,
)


def _spd(rng: np.random.Generator, n: int) -> np.ndarray:
    a = rng.normal(size=(n, n))
    corr_like = a @ a.T / n + np.diag(rng.uniform(0.2, 1.0, n))
    vol = rng.uniform(0.03, 0.30, n)
    return corr_like * np.outer(vol, vol)


def _correlation_root(cov: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    sigma = np.sqrt(np.diag(cov))
    values, vectors = np.linalg.eigh(cov / np.outer(sigma, sigma))
    return sigma, (vectors * np.sqrt(values)) @ vectors.T


def _distance(rotation: np.ndarray, root: np.ndarray) -> float:
    """Tracking error of the decorrelating transform built on an orthogonal `rotation`."""
    scale = np.diag(rotation @ root)  # the best diagonal for this rotation
    return float(np.linalg.norm(root - scale[:, None] * rotation))


@pytest.mark.parametrize("n", [2, 5, 23])
def test_diagonal_covariance_gives_identity_and_inverse_vol_gives_n(n):
    rng = np.random.default_rng(3300 + n)
    vol = rng.uniform(0.02, 0.40, n)
    cov = np.diag(vol**2)
    t = min_torsion(cov)
    assert np.abs(t - np.eye(n)).max() <= 1e-10
    inverse_vol = (1.0 / vol) / (1.0 / vol).sum()
    assert abs(effective_number_of_bets(inverse_vol, cov) - n) <= 1e-8
    single = np.zeros(n)
    single[n // 2] = 1.0
    assert abs(effective_number_of_bets(single, cov) - 1.0) <= 1e-8
    assert abs(effective_number_of_bets(rng.dirichlet(np.ones(n)), cov) - n) > 1e-6


def test_two_uncorrelated_funds_closed_form():
    cov = np.diag([0.10**2, 0.20**2])
    expected = math.exp(-(0.2 * math.log(0.2) + 0.8 * math.log(0.8)))
    assert abs(expected - 1.649) < 1e-3
    assert abs(effective_number_of_bets(np.array([0.5, 0.5]), cov) - expected) <= 1e-12
    shares = bet_shares(np.array([0.5, 0.5]), cov, torsion_basis(cov))
    assert np.abs(shares - [0.2, 0.8]).max() < 1e-12


@pytest.mark.parametrize(("n", "rho"), [(2, 0.6), (5, 0.3), (5, -0.1), (12, 0.5)])
def test_equicorrelated_menu_is_symmetric_and_equal_weights_give_n(n, rho):
    cov = 0.04 * ((1 - rho) * np.eye(n) + rho * np.ones((n, n)))
    t = min_torsion(cov)
    assert np.abs(t - t.T).max() <= 1e-10
    assert abs(effective_number_of_bets(np.full(n, 1.0 / n), cov) - n) <= 1e-8


def test_single_torsion_bet_gives_one_and_a_single_fund_need_not():
    rng = np.random.default_rng(3302)
    cov = _spd(rng, 8)
    t = min_torsion(cov)
    for i in (0, 7):
        bet = t.T[:, i] / t.T[:, i].sum()
        assert abs(effective_number_of_bets(bet, cov) - 1.0) <= 1e-8
    fund = np.zeros(8)
    fund[1] = 1.0
    assert effective_number_of_bets(fund, cov) > 1.0 + 1e-3  # a correlated fund loads several


def test_random_spd_matrices_are_diagonalized_and_shares_sum_to_one():
    rng = np.random.default_rng(3303)
    sizes = [2, 30] + [int(v) for v in rng.integers(2, 31, size=23)]
    for n in sizes:
        cov = _spd(rng, n)
        w = rng.dirichlet(np.ones(n))
        basis = torsion_basis(cov)
        m = basis.t @ cov @ basis.t.T
        assert np.abs(m - np.diag(np.diag(m))).max() <= 1e-8 * np.trace(m)
        assert np.array_equal(basis.lam, np.diag(m)) and (basis.lam > 0).all()
        assert np.abs(basis.inv_t @ basis.t.T - np.eye(n)).max() <= 1e-9
        p = bet_shares(w, cov, basis)
        assert abs(p.sum() - 1.0) <= 1e-8 and (p >= 0).all()
        value = enb(w, cov, basis)
        assert 1 - 1e-6 <= value <= n + 1e-6
        nonzero = p[p > 0]
        assert abs(value - math.exp(-float((nonzero * np.log(nonzero)).sum()))) <= 1e-12
        assert effective_number_of_bets(w, cov) == value
        assert effective_number_of_bets(w, cov, torsion=basis.t) == value
    assert len(sizes) == 25


def test_shares_stay_exact_for_a_mix_of_very_different_volatilities():
    """Low-variance mixes are where a trace-relative diagonality bound would hide an error."""
    rng = np.random.default_rng(3304)
    n = 12
    a = rng.normal(size=(n, n))
    corr_like = a @ a.T / n + 0.05 * np.eye(n)
    vol = np.geomspace(1e-4, 0.4, n)
    cov = corr_like * np.outer(vol, vol)
    basis = torsion_basis(cov)
    quiet = np.zeros(n)
    quiet[:2] = [0.7, 0.3]
    assert abs(bet_shares(quiet, cov, basis).sum() - 1.0) <= 1e-10
    assert 1.0 <= enb(quiet, cov, basis) <= n


def test_the_torsion_is_the_minimum_one():
    """No nearby rotation, and no principal-components rotation, tracks the funds more closely."""
    rng = np.random.default_rng(3305)
    for n in (4, 9, 16):
        cov = _spd(rng, n)
        sigma, root = _correlation_root(cov)
        x = min_torsion(cov) * sigma[None, :] / sigma[:, None]  # back to correlation space
        perturbation = x @ root
        scale = np.sqrt(np.diag(perturbation @ perturbation.T))
        rotation = perturbation / scale[:, None]
        assert np.abs(rotation @ rotation.T - np.eye(n)).max() <= 1e-10
        best = _distance(rotation, root)
        assert abs(best - np.linalg.norm(root - perturbation)) <= 1e-9
        for _ in range(40):
            skew = rng.normal(size=(n, n)) * 10.0 ** rng.uniform(-4, -1)
            step = expm(skew - skew.T)  # a proper rotation near the identity
            assert _distance(rotation @ step, root) >= best - 1e-10
        principal = np.linalg.eigh(cov / np.outer(sigma, sigma))[1].T
        assert _distance(principal, root) > best + 1e-3


def test_recursion_runs_to_the_fixed_point_or_raises():
    cov = _spd(np.random.default_rng(3306), 23)
    with pytest.raises(TorsionError, match="did not converge in 1 iterations"):
        min_torsion(cov, max_iter=1)
    converged = min_torsion(cov)
    # a far tighter stop moves nothing that matters: the default is at the fixed point
    assert np.abs(min_torsion(cov, tol=1e-13) - converged).max() <= 1e-7
    assert np.abs(min_torsion(cov, tol=1e-4) - converged).max() > 1e-7  # a loose stop is not


@pytest.mark.parametrize(
    ("cov", "message"),
    [
        (np.ones((2, 3)), "square"),
        (np.array([[0.04, np.nan], [np.nan, 0.04]]), "finite"),
        (np.array([[0.04, 0.01], [0.02, 0.04]]), "symmetric"),
        (np.array([[0.04, 0.0], [0.0, 0.0]]), "positive diagonal"),
        (np.array([[0.04, 0.05], [0.05, 0.04]]), "positive definite"),
    ],
)
def test_min_torsion_rejects_what_is_not_a_covariance(cov, message):
    with pytest.raises(TorsionError, match=message):
        min_torsion(cov)


def test_explicit_torsion_is_checked_not_trusted():
    rng = np.random.default_rng(3307)
    for n in (4, 11):
        cov = _spd(rng, n)
        w = rng.dirichlet(np.ones(n))
        t = min_torsion(cov)
        m = t @ cov @ t.T
        bad_m = np.diag(np.diag(m)).copy()
        bad_m[0, 1] = bad_m[1, 0] = 1e-6 * np.trace(m)
        good_l = np.linalg.cholesky(np.diag(np.diag(m)))
        bad_t = np.linalg.cholesky(bad_m) @ np.linalg.inv(good_l) @ t
        with pytest.raises(TorsionError, match="offdiag") as caught:
            effective_number_of_bets(w, cov, torsion=bad_t)
        assert isinstance(caught.value, ValueError) and "1e-08 * trace" in str(caught.value)
    with pytest.raises(TorsionError, match="shape"):
        torsion_basis(np.diag([0.04, 0.09]), torsion=np.eye(3))
    with pytest.raises(TorsionError, match="singular"):
        torsion_basis(np.diag([0.04, 0.09]), torsion=np.diag([1.0, 0.0]))
    with pytest.raises(TorsionError, match="offdiag"):
        torsion_basis(np.diag([0.04, 0.09]), torsion=np.array([[1.0, np.nan], [0.0, 1.0]]))


def test_share_sum_is_checked_and_never_renormalized():
    cov = np.diag([1.0, 1e-12])
    skewed = np.array([[1.0, 0.0], [5e-9, 1.0]])  # passes the trace-relative bound
    basis = torsion_basis(cov, torsion=skewed)
    with pytest.raises(TorsionError, match=r"sum\(p\)"):
        bet_shares(np.array([0.0, 1.0]), cov, basis)
    with pytest.raises(TorsionError, match="no variance"):
        bet_shares(np.zeros(2), cov, basis)
    assert torsion.OFFDIAG_TOL == torsion.SHARE_SUM_TOL == 1e-8
