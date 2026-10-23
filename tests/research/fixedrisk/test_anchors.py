"""Anchors, band projection and Bayes-Stein (piece 1, protocol §2 and §5)."""

from __future__ import annotations

from dataclasses import replace
from datetime import date

import numpy as np
import pytest

from portfoliosight.research.fixedrisk import anchors as anchors_mod
from portfoliosight.research.fixedrisk.anchors import (
    bayes_stein_mu,
    column_anchors,
    dr2,
    geometry,
    origin_anchors,
    slider_position,
)
from portfoliosight.research.fixedrisk.contracts import (
    OK,
    RISK_FRACTIONS,
    TAU_R,
    MenuSpec,
    OriginContext,
)
from tests.research.fixedrisk.optimizer_data import synthetic_context

TOL = 1e-8


@pytest.fixture(scope="module")
def ctx():
    return synthetic_context()


@pytest.fixture(scope="module")
def column(ctx):
    return origin_anchors(ctx)


def _in_band(geo, w, r, tau=TAU_R):
    return (
        (w >= geo.lo - TOL).all()
        and (w <= geo.hi + TOL).all()
        and abs(w.sum() - 1) <= TOL
        and abs(geo.risk(w) - r) <= tau * r + TOL
    )


def test_anchors_lie_on_the_band(ctx, column):
    geo = geometry(ctx)
    assert [a.r_fraction for a in column] == list(RISK_FRACTIONS)
    for a in column:
        assert a.status == OK and not a.collapsed
        assert a.r == pytest.approx(geo.sigma_min + a.r_fraction * (geo.sigma_top - geo.sigma_min))
        for w in (a.w_F, a.w_MDP, a.w_BS):
            assert _in_band(geo, w, a.r)
        assert a.M_F == pytest.approx(dr2(a.w_F, geo.sigma, geo.cov))
        assert a.M_MDP > a.M_F
        assert geo.mu_s @ a.w_F >= geo.mu_s @ a.w_BS - 1e-9  # w_F maximizes mu_s on the band
        assert geo.mu_bs @ a.w_BS >= geo.mu_bs @ a.w_F - 1e-9
        assert slider_position(a.M_F, a) == 0.0 and slider_position(a.M_MDP, a) == 1.0


def test_anchors_beat_band_points(ctx, column):
    """No projected Sobol point on the band beats the anchors on their own objectives."""
    geo = geometry(ctx)
    for a in column:
        for w in geo.band_points(a.r, TAU_R):
            assert geo.mu_s @ w <= geo.mu_s @ a.w_F + 1e-9
            assert geo.measure(w) <= a.M_MDP + 1e-9


def test_sigma_min_and_top(ctx):
    geo = geometry(ctx)
    assert geo.sigma_min == pytest.approx(geo.risk(geo.w_min))
    assert geo.mu_s @ geo.w_top >= max(geo.mu_s @ w for w in geo.sobol_mixes()) - 1e-12
    assert geo.sigma_min <= min(geo.risk(w) for w in geo.sobol_mixes()) + 1e-9


def test_projection_reaches_half_band(ctx):
    geo = geometry(ctx)
    r = geo.x(0.4)
    for v in geo.sobol_mixes()[:40]:
        w = geo.project(np.array(v), r, TAU_R)
        assert w is not None
        s = geo.risk(np.array(v))
        if abs(s - r) > TAU_R * r:
            assert abs(geo.risk(w) - r) <= 0.5 * TAU_R * r + 1e-12
        else:
            assert np.array_equal(w, v)
        assert _in_band(geo, w, r)
    assert geo.project(geo.w_top, geo.sigma_top * 1.5, TAU_R) is None  # unreachable


def _two_fund_ctx() -> OriginContext:
    """Two uncorrelated funds at 10% and 30% volatility (protocol §2 counterexample)."""
    rng = np.random.default_rng(0)
    sample = rng.normal(size=(300, 2)) * np.array([0.1, 0.3]) / np.sqrt(252)
    cov = np.diag([0.01, 0.09])
    return OriginContext(
        menu=MenuSpec("two", ("A", "B"), (0.0, 0.0), (1.0, 1.0)),
        month="2020-01",
        origin=date(2020, 1, 31),
        lookback="3y",
        days=(),
        sample=sample,
        mu_hat=np.array([0.03, 0.08]),
        mu_s=np.array([0.03, 0.08]),
        cov=cov,
        sigma=np.array([0.1, 0.3]),
        risk_free_rate=0.0,
        inputs_sha256="two-fund-counterexample",
    )


def test_mdp_maximizes_dr2_not_its_numerator():
    ctx = _two_fund_ctx()
    geo = geometry(ctx)
    a = (0.2 - geo.sigma_min) / (geo.sigma_top - geo.sigma_min)
    anchor = column_anchors(geo, a, TAU_R)
    assert anchor.r == pytest.approx(0.2)
    # the numerator's maximum on the band sits at the upper edge, sigma = 20.2%
    x = np.linspace(0, 1, 200001)
    w = np.stack([1 - x, x], axis=1)
    risk = np.sqrt(0.01 * (1 - x) ** 2 + 0.09 * x**2)
    band = np.abs(risk - 0.2) <= 0.002
    numerator_best = w[band][np.argmax(w[band] @ geo.sigma)]
    m_numerator = dr2(numerator_best, geo.sigma, geo.cov)
    assert m_numerator == pytest.approx(1.328, abs=1e-3)
    assert anchor.M_MDP == pytest.approx(1.348, abs=1e-3)
    assert anchor.M_MDP > m_numerator + 0.015
    assert anchor.M_MDP >= max(dr2(v, geo.sigma, geo.cov) for v in w[band]) - 1e-6


def test_bayes_stein_formula(ctx):
    mu_bs = bayes_stein_mu(ctx.sample, ctx.mu_hat)
    t, n = ctx.sample.shape
    s = np.cov(ctx.sample, rowvar=False) * (t - 1) / (t - n - 2)
    inv = np.linalg.inv(s)
    mu = ctx.mu_hat / 252
    one = np.ones(n)
    mu0 = mu @ inv @ one / (one @ inv @ one)
    phi = (n + 2) / ((n + 2) + t * (mu - mu0) @ inv @ (mu - mu0))
    np.testing.assert_allclose(mu_bs, 252 * ((1 - phi) * mu + phi * mu0), rtol=1e-12)
    assert 0 < phi < 1
    assert np.std(mu_bs) < np.std(ctx.mu_hat)
    equal = np.full(n, 0.07)
    np.testing.assert_allclose(bayes_stein_mu(ctx.sample, equal), equal, rtol=1e-12)


def test_collapse_flag(ctx, column):
    a = column[0]
    collapsed = replace(a, M_MDP=a.M_F + 5e-7, collapsed=True)
    assert slider_position(a.M_F, collapsed) is None


def test_anchors_are_deterministic(ctx, column):
    anchors_mod._GEOMETRY.clear()
    again = origin_anchors(ctx)
    for a, b in zip(column, again, strict=True):
        np.testing.assert_array_equal(a.w_F, b.w_F)
        np.testing.assert_array_equal(a.w_MDP, b.w_MDP)
        np.testing.assert_array_equal(a.w_BS, b.w_BS)
