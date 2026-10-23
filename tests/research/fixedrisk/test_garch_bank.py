"""Piece 3: the GARCH(1,1)-t FHS bank of the fixed-risk experiment (protocol §3, §4)."""

from __future__ import annotations

import warnings
from dataclasses import replace
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from portfoliosight.engine.ranges import garch_range_model, simulated_years
from portfoliosight.engine.shape import MIN_POOL_ROWS, simulate_panel
from portfoliosight.research.fixedrisk import garch_bank as gb
from portfoliosight.research.fixedrisk.contracts import (
    FIT_FAILED,
    HORIZON,
    PATHS,
    MenuSpec,
    OriginContext,
)
from qse.distributions.garch_recursion import simulate_garch11
from qse.distributions.joint import fit_garch_t_panel, residual_pool

SEED = 20261013
ROWS = 800
ORIGIN = date(2024, 6, 28)


def _garch_series(rows: int, funds: int, rng: np.random.Generator, rho: float = 0.5) -> np.ndarray:
    """Correlated GARCH(1,1) daily simple returns with Student-t(5) shocks: rows x funds."""
    corr = np.full((funds, funds), rho) + (1 - rho) * np.eye(funds)
    t = rng.standard_t(5, size=(1, rows, funds)) * np.sqrt(3 / 5)
    shocks = t @ np.linalg.cholesky(corr).T
    vol = np.linspace(0.006, 0.014, funds)
    omega = vol**2 * (1 - 0.08 - 0.9)
    logs = simulate_garch11(
        np.ascontiguousarray(shocks),
        mu=np.full(funds, 3e-4),
        omega=omega,
        alpha=np.full(funds, 0.08),
        beta=np.full(funds, 0.9),
        sigma2_init=vol**2,
    )[0]
    return np.expm1(logs)


def _days(rows: int, end: date) -> tuple[date, ...]:
    stamps = pd.bdate_range(end=pd.Timestamp(end), periods=rows)
    return tuple(stamp.date() for stamp in stamps)


def _ctx(
    sample: np.ndarray,
    days: tuple[date, ...],
    holdings: tuple[str, ...],
    origin: date = ORIGIN,
    sigma: np.ndarray | None = None,
    corr: np.ndarray | None = None,
) -> OriginContext:
    sample = np.asarray(sample, dtype=float)
    cov = np.cov(sample.T, ddof=1) * 252
    if sigma is not None and corr is not None:
        cov = corr * np.outer(sigma, sigma)
    mu = sample.mean(axis=0) * 252
    n = len(holdings)
    return OriginContext(
        menu=MenuSpec("synthetic", holdings, (0.0,) * n, (1.0,) * n),
        month=origin.strftime("%Y-%m"),
        origin=origin,
        lookback="3y",
        days=days,
        sample=sample,
        mu_hat=mu,
        mu_s=0.5 * mu + 0.03,
        cov=cov,
        sigma=np.sqrt(np.diag(cov)),
        risk_free_rate=0.02,
        inputs_sha256="synthetic",
    )


@pytest.fixture(autouse=True)
def _quiet():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        yield


@pytest.fixture(scope="module")
def ctx() -> OriginContext:
    rng = np.random.default_rng(7)
    return _ctx(_garch_series(ROWS, 4, rng), _days(ROWS, ORIGIN), ("A", "B", "C", "D"))


@pytest.fixture(scope="module")
def bank(ctx) -> gb.GarchBank:
    gb.clear_fit_cache()
    return gb.garch_bank(ctx, "garch", SEED)


@pytest.fixture(scope="module")
def absorbing() -> tuple[OriginContext, gb.GarchBank]:
    """Two funds that move against each other while the chart says they move together.

    The 50/50 mix then has a tiny simulated spread and a large chart one, so `k` is large and the
    mix's levelled days reach -100% on some paths.
    """
    rng = np.random.default_rng(11)
    a = _garch_series(ROWS, 1, rng)[:, 0]
    b = -a + _garch_series(ROWS, 1, rng)[:, 0] * 0.2
    sample = np.column_stack([a, b])
    sigma = np.array([2.0, 2.0])
    corr = np.array([[1.0, 0.95], [0.95, 1.0]])
    ctx = _ctx(sample, _days(ROWS, ORIGIN), ("P", "Q"), sigma=sigma, corr=corr)
    return ctx, gb.garch_bank(ctx, "garch", SEED)


def _production_years(bank: gb.GarchBank, ctx: OriginContext, mixes: np.ndarray) -> np.ndarray:
    panel = simulate_panel(bank.artifact, PATHS, HORIZON, bank.seed)
    return simulated_years(garch_range_model(panel, ctx.mu_s, ctx.cov, bank.seed), mixes)


def _mixes(rng: np.random.Generator, funds: int, count: int) -> np.ndarray:
    return np.vstack([np.eye(funds), rng.dirichlet(np.ones(funds), size=count)])


def test_bank_shape_and_protocol_fields(bank):
    assert (bank.engine, bank.seed, bank.paths, bank.horizon) == ("garch", SEED, PATHS, HORIZON)
    assert bank.growth_bound_ok is True
    assert bank.levelled_t.shape == (4, PATHS * HORIZON)
    assert bank.levelled_t.dtype == np.float64 and not bank.levelled_t.flags.writeable
    assert set(bank.fit_status.values()) == {"garch"}


def test_fit_and_pool_equal_the_production_panel_fit(ctx, bank):
    frame = pd.DataFrame(np.log1p(ctx.sample), columns=pd.Index(ctx.menu.holdings))
    fit = fit_garch_t_panel(frame)
    pool = residual_pool(fit, restandardize=True, min_rows=MIN_POOL_ROWS)
    art = bank.artifact
    for name in ("mu", "omega", "alpha", "beta", "nu"):
        np.testing.assert_array_equal(getattr(art, name), getattr(fit, name))
    np.testing.assert_array_equal(art.pool, pool)
    assert art.pool_rows == ROWS and art.end == ORIGIN.isoformat()


def test_years_equal_production(ctx, bank):
    mixes = _mixes(np.random.default_rng(1), 4, 12)
    ours = bank.years(mixes)
    theirs = _production_years(bank, ctx, mixes)
    assert ours.shape == (PATHS, len(mixes))
    assert np.max(np.abs(ours - theirs)) <= 1e-10
    one, _ = bank.years_and_vjp(mixes[5])
    assert np.max(np.abs(one - theirs[:, 5])) <= 1e-10


def _check_gradient(bank, w, a, directions):
    year, vjp = bank.years_and_vjp(w)
    grad = vjp(a)
    h = 1e-6
    checked = 0
    for d in directions:
        up, _ = bank.years_and_vjp(w + h * d)
        down, _ = bank.years_and_vjp(w - h * d)
        fd = float(a @ (up - down)) / (2 * h)
        if abs(fd) <= 1e-8:
            continue
        assert abs(grad @ d - fd) / abs(fd) <= 1e-4, (grad @ d, fd)
        checked += 1
    return checked


def test_gradient_matches_central_differences(bank):
    rng = np.random.default_rng(3)
    checked = 0
    for _ in range(4):
        w = rng.dirichlet(np.ones(4))
        a = rng.normal(size=PATHS)
        checked += _check_gradient(bank, w, a, rng.normal(size=(5, 4)))
    # order-statistic weights: a few paths only
    w = rng.dirichlet(np.ones(4))
    year, _ = bank.years_and_vjp(w)
    a = np.zeros(PATHS)
    a[np.argsort(year)[48:52]] = 0.25
    checked += _check_gradient(bank, w, a, np.eye(4))
    assert checked >= 20


def test_zero_variance_branch(bank):
    # a mix with w'Sigma_R'w = 0: weights orthogonal to every direction of R' (here, all zero)
    year, vjp = bank.years_and_vjp(np.zeros(4))
    np.testing.assert_array_equal(year, 0.0)
    a = np.ones(PATHS)
    np.testing.assert_allclose(vjp(a), bank.m * HORIZON * PATHS)


def test_absorbed_paths(absorbing):
    ctx, bank = absorbing
    w = np.array([0.5, 0.5])
    year, vjp = bank.years_and_vjp(w)
    lost = year == -1.0
    assert lost.any() and not lost.all()
    both = bank.years(np.array([w, [0.6, 0.4]]))
    np.testing.assert_array_equal(both[:, 0] == -1.0, lost)
    assert np.max(np.abs(both - _production_years(bank, ctx, np.array([w, [0.6, 0.4]])))) <= 1e-10
    # an absorbed path's gradient is zero; the others' stays exact
    a = np.zeros(PATHS)
    a[np.flatnonzero(lost)[0]] = 1.0
    np.testing.assert_array_equal(vjp(a), 0.0)
    gross_min = (
        ((_k(bank, w) * w) @ bank.levelled_t).reshape(PATHS, HORIZON).min(axis=1)
    )  # paths far from the boundary
    safe = gross_min > gross_min[~lost].min() + 0.5 * np.ptp(gross_min[~lost])
    a = np.where(safe, np.random.default_rng(5).normal(size=PATHS), 0.0)
    a[lost] = 1.0  # weight on absorbed paths must contribute nothing
    assert _check_gradient(bank, w, a, np.array([[1.0, -1.0], [1.0, 0.3], [-0.2, 1.0]])) == 3


def _k(bank, w):
    v, _ = bank._terms(np.atleast_2d(w))
    return v[0, 0] / w[0]


def test_fit_cache_is_reused_across_seeds_and_menus(ctx, monkeypatch):
    gb.clear_fit_cache()
    calls = []
    real = gb.fit_garch_t_panel

    def spy(frame, **kwargs):
        calls.append(tuple(frame.columns))
        return real(frame, **kwargs)

    monkeypatch.setattr(gb, "fit_garch_t_panel", spy)
    first = gb.garch_bank(ctx, "garch", SEED)
    second = gb.garch_bank(ctx, "garch", SEED + 1)
    assert len(calls) == 4 and gb.fit_cache_size() == 4
    assert not np.array_equal(first.levelled_t, second.levelled_t)
    sub = replace(
        ctx,
        menu=MenuSpec("sub", ("C", "A"), (0.0, 0.0), (1.0, 1.0)),
        sample=np.ascontiguousarray(ctx.sample[:, [2, 0]]),
        mu_s=ctx.mu_s[[2, 0]],
        cov=ctx.cov[np.ix_([2, 0], [2, 0])],
    )
    gb.garch_bank(sub, "garch", SEED)
    assert len(calls) == 4  # same holdings, same training rows: reused
    later = replace(ctx, origin=ORIGIN + timedelta(days=31))
    gb.garch_bank(later, "garch", SEED)
    assert len(calls) == 8  # a new origin fits again
    again = gb.garch_bank(ctx, "garch", SEED)
    np.testing.assert_array_equal(again.levelled_t, first.levelled_t)


def test_no_look_ahead():
    rng = np.random.default_rng(21)
    total = ROWS + 100
    returns = _garch_series(total, 3, rng)
    days = _days(total, ORIGIN + timedelta(days=90))
    cut = sum(day <= ORIGIN for day in days)

    def context(values):
        keep = slice(cut - ROWS, cut)
        return _ctx(values[keep], days[keep], ("X", "Y", "Z"))

    gb.clear_fit_cache()
    before = gb.garch_bank(context(returns), "garch", SEED)
    changed = returns.copy()
    changed[cut:] = rng.normal(0, 0.05, size=changed[cut:].shape)
    gb.clear_fit_cache()
    after = gb.garch_bank(context(changed), "garch", SEED)
    np.testing.assert_array_equal(before.levelled_t, after.levelled_t)
    leaky = _ctx(returns[cut - ROWS + 1 : cut + 1], days[cut - ROWS + 1 : cut + 1], ("X", "Y", "Z"))
    with pytest.raises(ValueError, match="origin"):
        gb.garch_bank(leaky, "garch", SEED)


def test_named_failure_on_a_degenerate_series(ctx, monkeypatch):
    rng = np.random.default_rng(2)
    sample = ctx.sample.copy()
    sample[:, 1] = np.r_[np.zeros(ROWS - 260), rng.normal(0, 0.01, 260)]  # flat, then trading
    bad = replace(ctx, sample=sample)
    gb.clear_fit_cache()
    with pytest.raises(gb.GarchFitFailed) as caught:
        gb.garch_bank(bad, "garch", SEED)
    err = caught.value
    assert (err.holding, err.origin, err.label) == ("B", ORIGIN, FIT_FAILED)
    assert "converge" in err.reason
    calls = []
    monkeypatch.setattr(gb, "fit_garch_t_panel", lambda *a, **k: calls.append(1))
    with pytest.raises(gb.GarchFitFailed):  # the failure is cached: no refit, same name
        gb.holding_fit(bad, 1)
    assert calls == []


def test_fit_failure_crosses_process_boundaries():
    """A worker's GarchFitFailed is unpickled by its parent (ProcessPool result channel)."""
    import pickle
    from concurrent.futures import ProcessPoolExecutor

    err = pickle.loads(pickle.dumps(gb.GarchFitFailed("TSP-F", ORIGIN, "did not converge")))
    assert (err.holding, err.origin, err.reason, err.label) == (
        "TSP-F", ORIGIN, "did not converge", FIT_FAILED,
    )  # fmt: skip
    assert str(err) == f"GARCH fit failed for TSP-F at {ORIGIN.isoformat()}: did not converge"
    with ProcessPoolExecutor(1) as pool:
        with pytest.raises(gb.GarchFitFailed) as caught:
            pool.submit(_raise_fit_failed).result()
    assert caught.value.holding == "GE" and caught.value.reason == "x"


def _raise_fit_failed():
    raise gb.GarchFitFailed("GE", ORIGIN, "x")


def test_near_constant_holding_is_the_production_fallback(ctx):
    rng = np.random.default_rng(4)
    sample = ctx.sample.copy()
    sample[:, 3] = 1e-4 + rng.normal(0, 1e-5, ROWS)  # a stable-value fund
    calm = replace(ctx, sample=sample)
    gb.clear_fit_cache()
    bank = gb.garch_bank(calm, "garch", SEED)
    assert bank.fit_status["D"] == "near_constant"
    mixes = _mixes(np.random.default_rng(8), 4, 3)
    assert np.max(np.abs(bank.years(mixes) - _production_years(bank, calm, mixes))) <= 1e-10


def test_rejects_other_engines_and_bad_mixes(ctx, bank):
    with pytest.raises(ValueError):
        gb.garch_bank(ctx, "replay", SEED)
    with pytest.raises(ValueError):
        bank.years(np.ones((2, 3)) / 3)
    with pytest.raises(ValueError):
        bank.years_and_vjp(np.ones((2, 4)) / 4)
