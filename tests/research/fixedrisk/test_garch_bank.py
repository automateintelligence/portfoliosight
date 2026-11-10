"""Piece 3: the GARCH(1,1)-t FHS bank of the fixed-risk experiment (protocol §3, §4)."""

from __future__ import annotations

import warnings
from dataclasses import replace
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from portfoliosight.engine.ranges import garch_range_model, simulated_years
from portfoliosight.engine.shape import simulate_panel
from portfoliosight.research.fixedrisk import garch_bank as gb
from portfoliosight.research.fixedrisk.contracts import (
    FIT_FAILED,
    HORIZON,
    PATHS,
    MenuSpec,
    OriginContext,
)
from qse.distributions.garch_recursion import simulate_garch11
from qse.distributions.joint import fit_garch_t_panel

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
    history: pd.DataFrame | None = None,
) -> OriginContext:
    """A context whose history is `history`, by default the training rows themselves."""
    sample = np.asarray(sample, dtype=float)
    if history is None:
        history = _frame(sample, days, holdings)
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
        history=history,
    )


def _frame(values: np.ndarray, days, holdings) -> pd.DataFrame:
    return pd.DataFrame(
        np.asarray(values, dtype=float),
        index=pd.DatetimeIndex([pd.Timestamp(day) for day in days]),
        columns=pd.Index(list(holdings)),
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
    # uncapped: the cap (ADR 0006) trims the tails that reach -100% here; absorption is step 2's
    return ctx, gb.garch_bank(ctx, "garch", SEED, vol_cap=None)


def _production_years(bank: gb.GarchBank, ctx: OriginContext, mixes: np.ndarray) -> np.ndarray:
    """Production's levelling and years on the bank's simulated panel: production
    `shape.simulate_panel` when uncapped, its capped twin (`gb.simulate_capped`, byte-identical
    at an infinite cap) when the bank is capped (ADR 0006)."""
    if bank.vol_cap is None:
        panel = simulate_panel(bank.artifact, PATHS, HORIZON, bank.seed)
    else:
        cap = gb.variance_cap(ctx, bank.artifact, bank.vol_cap)
        panel, _ = gb.simulate_capped(bank.artifact, cap, PATHS, HORIZON, bank.seed)
    return simulated_years(garch_range_model(panel, ctx.mu_s, ctx.cov, bank.seed), mixes)


def _mixes(rng: np.random.Generator, funds: int, count: int) -> np.ndarray:
    return np.vstack([np.eye(funds), rng.dirichlet(np.ones(funds), size=count)])


def test_bank_shape_and_protocol_fields(bank):
    assert (bank.engine, bank.seed, bank.paths, bank.horizon) == ("garch", SEED, PATHS, HORIZON)
    assert bank.growth_bound_ok is True
    assert bank.levelled_t.shape == (4, PATHS * HORIZON)
    assert bank.levelled_t.dtype == np.float64 and not bank.levelled_t.flags.writeable
    assert set(bank.fit_status.values()) == {"garch"}
    assert set(bank.windows.values()) == {"10y"} and bank.fallbacks == {}


def _manual_pool(history: pd.DataFrame, art) -> np.ndarray:
    """The shock pool by hand: each column's recursion over its own rows from the first common
    row, started at the long-run variance, then the common rows re-standardized (ddof 0)."""
    common = history.notna().all(axis=1).to_numpy()
    span = history.iloc[int(np.argmax(common)) :]
    z = np.full(span.shape, np.nan)
    for n in range(span.shape[1]):
        rows = np.flatnonzero(span.iloc[:, n].notna().to_numpy())
        e = np.log1p(span.iloc[rows, n].to_numpy()) - art.mu[n]
        w, a, b = art.omega[n], art.alpha[n], art.beta[n]
        s2 = w / (1.0 - a - b)
        out = np.empty_like(e)
        for t in range(len(e)):
            out[t] = e[t] / np.sqrt(s2) if s2 > 0 else 0.0
            s2 = w + a * e[t] ** 2 + b * s2
        z[rows, n] = out
    pool = z[np.isfinite(z).all(axis=1)]
    return (pool - pool.mean(axis=0)) / pool.std(axis=0)


def _assert_pool(art, history: pd.DataFrame) -> None:
    assert art.pool is not None
    np.testing.assert_allclose(art.pool, _manual_pool(history, art), rtol=0, atol=1e-10)


def test_fit_equals_the_production_panel_fit_and_the_pool_is_filtered_forward(ctx, bank):
    frame = pd.DataFrame(np.log1p(ctx.sample), columns=pd.Index(ctx.menu.holdings))
    fit = fit_garch_t_panel(frame)  # fewer than 10 years: the window is every row
    art = bank.artifact
    for name in ("mu", "omega", "alpha", "beta", "nu"):
        np.testing.assert_array_equal(getattr(art, name), getattr(fit, name))
    _assert_pool(art, ctx.history)
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
        history=ctx.history[["C", "A"]],
        mu_s=ctx.mu_s[[2, 0]],
        cov=ctx.cov[np.ix_([2, 0], [2, 0])],
    )
    gb.garch_bank(sub, "garch", SEED)
    assert len(calls) == 4  # same holdings, same dynamics windows: reused
    gb.garch_bank(replace(ctx, lookback="5y"), "garch", SEED)
    assert len(calls) == 4  # the dynamics windows do not depend on the lookback
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


def test_a_non_converging_10_year_fit_is_retried_on_3_years_and_cached(ctx, monkeypatch):
    """The non-convergence is injected (`_failing`): whether a real optimizer converges on a
    degenerate series turns on the last floating-point unit and on the BLAS thread count."""
    _failing(monkeypatch, "B", longer_than=gb.RETRY_ROWS)
    gb.clear_fit_cache()
    bank = gb.garch_bank(ctx, "garch", SEED)
    assert bank.windows == {"A": "10y", "B": "3y", "C": "10y", "D": "10y"}
    assert bank.fit_status["B"] == "garch" and bank.fallbacks == {}
    assert bank.artifact.messages[1].startswith("10y fit_failed")
    calls = []
    monkeypatch.setattr(gb, "fit_garch_t_panel", lambda *a, **k: calls.append(1))
    assert gb.holding_fit(ctx, 1).window == "3y"  # cached: no refit
    assert calls == []


def _failing(monkeypatch, holding: str, longer_than: int = 0):
    """`fit_garch_t_panel` whose optimizer does not converge for `holding` on windows longer than
    `longer_than` rows (QSE's own `fit_failed` fallback then runs)."""
    from qse.distributions.joint import panel_fit

    real = gb.fit_garch_t_panel
    calls = []

    def fit(frame, **kwargs):
        calls.append((frame.columns[0], len(frame)))
        if frame.columns[0] != holding or len(frame) <= longer_than:
            return real(frame, **kwargs)
        with monkeypatch.context() as patch:
            patch.setattr(panel_fit.GarchTFitter, "optimizer_converged", lambda self: False)
            return real(frame, **kwargs)

    monkeypatch.setattr(gb, "fit_garch_t_panel", fit)
    return calls


def test_a_10_year_failure_is_refitted_on_3_years(ctx, monkeypatch):
    calls = _failing(monkeypatch, "B", longer_than=gb.RETRY_ROWS)
    gb.clear_fit_cache()
    bank = gb.garch_bank(ctx, "garch", SEED)
    assert bank.windows == {"A": "10y", "B": "3y", "C": "10y", "D": "10y"}
    assert [c for c in calls if c[0] == "B"] == [("B", ROWS), ("B", gb.RETRY_ROWS)]
    assert bank.fit_status["B"] == "garch" and bank.fallbacks == {}
    three = fit_garch_t_panel(pd.DataFrame({"B": np.log1p(ctx.sample[-gb.RETRY_ROWS :, 1])}))
    art = bank.artifact
    for name in ("mu", "omega", "alpha", "beta", "nu"):
        assert getattr(art, name)[1] == getattr(three, name)[0]
    assert art.n_obs[1] == gb.RETRY_ROWS and "10y fit_failed" in art.messages[1]
    # the pool still spans every common row, filtered with the 3-year parameters
    assert art.pool_rows == ROWS
    _assert_pool(art, ctx.history)


def test_failing_both_windows_falls_back_to_constant_volatility(ctx, monkeypatch):
    """Amendment 1 (revised): neither window fits; the other holdings keep GARCH."""
    _failing(monkeypatch, "B")
    gb.clear_fit_cache()
    bank = gb.garch_bank(ctx, "garch", SEED)
    assert bank.windows == {"A": "10y", "B": "fallback", "C": "10y", "D": "10y"}
    assert bank.fit_status == {"A": "garch", "B": "fit_failed", "C": "garch", "D": "garch"}
    assert bank.fallbacks == {
        "B": "10y fit_failed: optimizer did not converge; 3y fit_failed: optimizer did not converge"
    }
    art = bank.artifact
    logs = np.log1p(ctx.sample[:, 1])  # the 10-year window's sample mean and variance
    assert art.alpha[1] == art.beta[1] == 0.0 and np.isnan(art.nu[1])
    assert art.mu[1] == pytest.approx(logs.mean(), rel=1e-12)
    assert art.omega[1] == pytest.approx(logs.var(ddof=1), rel=1e-12)
    assert (art.alpha[[0, 2, 3]] > 0.0).all()
    _assert_pool(art, ctx.history)
    mixes = _mixes(np.random.default_rng(9), 4, 3)
    assert np.max(np.abs(bank.years(mixes) - _production_years(bank, ctx, mixes))) <= 1e-10


@pytest.mark.parametrize(
    ("value", "reason"), [(-1.0, "-100%"), (np.inf, "non-finite"), (-np.inf, "non-finite")]
)
def test_unusable_input_is_a_named_failure(ctx, monkeypatch, value, reason):
    history = ctx.history.copy()
    history.iloc[5, 1] = value
    bad = replace(ctx, history=history)
    gb.clear_fit_cache()
    with pytest.raises(gb.GarchFitFailed) as caught:
        gb.garch_bank(bad, "garch", SEED)
    err = caught.value
    assert (err.holding, err.origin, err.label) == ("B", ORIGIN, FIT_FAILED)
    assert reason in err.reason
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


def test_a_near_constant_holding_like_tsp_g_is_a_counted_fallback(ctx, monkeypatch):
    rng = np.random.default_rng(4)
    sample = ctx.sample.copy()
    sample[:, 3] = 1e-4 + rng.normal(0, 1e-5, ROWS)  # a stable-value fund
    calm = _ctx(sample, ctx.days, ctx.menu.holdings)
    gb.clear_fit_cache()
    bank = gb.garch_bank(calm, "garch", SEED)
    assert bank.fit_status["D"] == "near_constant"
    assert bank.windows == {"A": "10y", "B": "10y", "C": "10y", "D": "fallback"}
    assert set(bank.fallbacks) == {"D"}
    assert bank.fallbacks["D"].startswith("10y near_constant: daily std")
    calls = _failing(monkeypatch, "none")  # QSE's rule stands: no 3-year retry
    gb.clear_fit_cache()
    gb.garch_bank(calm, "garch", SEED)
    assert sorted(calls) == [(h, ROWS) for h in ("A", "B", "C", "D")]
    mixes = _mixes(np.random.default_rng(8), 4, 3)
    assert np.max(np.abs(bank.years(mixes) - _production_years(bank, calm, mixes))) <= 1e-10


def test_rejects_other_engines_and_bad_mixes(ctx, bank):
    with pytest.raises(ValueError):
        gb.garch_bank(ctx, "replay", SEED)
    with pytest.raises(ValueError):
        bank.years(np.ones((2, 3)) / 3)
    with pytest.raises(ValueError):
        bank.years_and_vjp(np.ones((2, 4)) / 4)


def _long_history(extra: int, rng: np.random.Generator, funds: int = 3):
    """`extra` rows before a ROWS-row lookback ending at the origin, and 50 rows after it."""
    total = extra + ROWS + 50
    returns = _garch_series(total, funds, rng)
    after = pd.bdate_range(start=pd.Timestamp(ORIGIN + timedelta(days=1)), periods=50)
    days = _days(extra + ROWS, ORIGIN) + tuple(stamp.date() for stamp in after)
    cut = extra + ROWS
    return returns, days, cut


def test_dynamics_window_is_10_years_and_the_pool_spans_the_common_history(monkeypatch):
    rng = np.random.default_rng(31)
    holdings = ("X", "Y", "Z")
    returns, days, cut = _long_history(2000, rng)  # 2,800 rows to the origin
    lookback = slice(cut - ROWS, cut)
    history = _frame(returns[:cut], days[:cut], holdings)
    history.iloc[:100, 2] = np.nan  # Z, the youngest, starts later, before the 10-year windows
    ctx = _ctx(returns[lookback], days[lookback], holdings, history=history)
    seen = {}
    real = gb.fit_garch_t_panel

    def spy(frame, **kwargs):
        seen[frame.columns[0]] = frame.copy()
        return real(frame, **kwargs)

    monkeypatch.setattr(gb, "fit_garch_t_panel", spy)
    gb.clear_fit_cache()
    bank = gb.garch_bank(ctx, "garch", SEED)
    for n, holding in enumerate(holdings):
        frame = seen[holding]
        first = cut - gb.DYNAMICS_ROWS  # each holding's own last 10 years
        assert frame.index[0] == pd.Timestamp(days[first])
        assert frame.index[-1] == pd.Timestamp(ORIGIN)
        np.testing.assert_array_equal(frame.iloc[:, 0], np.log1p(returns[first:cut, n]))
    art = bank.artifact
    assert art.n_obs == (gb.DYNAMICS_ROWS,) * 3
    # the pool: every common row from Z's first return on, older than the dynamics windows
    assert (art.rows, art.start, art.end) == (cut - 100, days[100].isoformat(), ORIGIN.isoformat())
    assert art.pool_rows == cut - 100 > gb.DYNAMICS_ROWS
    _assert_pool(art, history)
    # a -100% day in the pool span but before X's dynamics window is unusable input too
    lost = history.copy()
    lost.iloc[cut - gb.DYNAMICS_ROWS - 5, 0] = -1.0
    with pytest.raises(gb.GarchFitFailed, match="shock pool span"):
        gb.garch_bank(replace(ctx, history=lost), "garch", SEED)
    # rows after the origin never reach the fit; a history holding one is refused
    leaky = replace(ctx, history=_frame(returns[: cut + 1], days[: cut + 1], holdings))
    with pytest.raises(ValueError, match="origin"):
        gb.garch_bank(leaky, "garch", SEED)
    with pytest.raises(ValueError, match="history"):
        gb.garch_bank(replace(ctx, history=None), "garch", SEED)


def test_the_level_comes_from_the_lookback_not_the_dynamics_window():
    rng = np.random.default_rng(41)
    holdings = ("X", "Y", "Z")
    returns, days, cut = _long_history(1000, rng)
    lookback = slice(cut - ROWS, cut)
    full = _frame(returns[:cut], days[:cut], holdings)
    short = _ctx(returns[lookback], days[lookback], holdings)  # history = the lookback
    long = replace(short, history=full)  # same lookback and chart moments, longer history
    gb.clear_fit_cache()
    a, b = gb.garch_bank(short, "garch", SEED), gb.garch_bank(long, "garch", SEED)
    assert a.artifact.rows == ROWS and b.artifact.rows == cut
    assert not np.array_equal(a.artifact.alpha, b.artifact.alpha)  # the shape moved
    for bank in (a, b):  # the level did not: the lookback's chart moments, from ctx.sample
        np.testing.assert_array_equal(bank.mu_s, short.mu_s)
        np.testing.assert_array_equal(bank.cov, short.cov)
        np.testing.assert_array_equal(bank.m, short.mu_s / 252)
    mixes = _mixes(np.random.default_rng(6), 3, 4)
    assert np.max(np.abs(b.years(mixes) - _production_years(b, long, mixes))) <= 1e-10
    # another lookback on the same history: same fit and pool, the new level
    later = _ctx(returns[cut - 500 : cut], days[cut - 500 : cut], holdings, history=full)
    c = gb.garch_bank(later, "garch", SEED)
    np.testing.assert_array_equal(c.artifact.alpha, b.artifact.alpha)
    np.testing.assert_array_equal(c.artifact.pool, b.artifact.pool)
    np.testing.assert_array_equal(c.mu_s, later.mu_s)
    np.testing.assert_array_equal(c.cov, later.cov)
    assert not np.allclose(c.cov, b.cov)


# ---------------------------------------------- simulated volatility cap (ADR 0006)


def _integrated(art, alpha: float = 0.2, beta: float = 0.799):
    """The artifact with every fund's dynamics near integrated (persistence 0.999, as C, IYR and
    SPY in 2010-2011), the long-run variance kept."""
    n = len(art.funds)
    long_run = art.omega / (1.0 - art.alpha - art.beta)
    return replace(
        art,
        alpha=np.full(n, alpha),
        beta=np.full(n, beta),
        omega=long_run * (1.0 - alpha - beta),
    )


def _reference(art, cap: np.ndarray, paths: int, seed: int) -> tuple[np.ndarray, np.ndarray]:
    """The capped recursion one path and fund at a time, in plain Python, and its hit counts:
    clamps on days 2 onward only (day 1 starts at the long-run variance, `start_capped`)."""
    from qse.distributions.joint import draw_row_indices

    z = art.pool[draw_row_indices(art.pool_rows, paths, HORIZON, seed=seed)]
    out = np.empty_like(z)
    hits = np.zeros(len(art.funds), dtype=np.int64)
    for n in range(len(art.funds)):
        w, a, b, mu = art.omega[n], art.alpha[n], art.beta[n], art.mu[n]
        for p in range(paths):
            s2 = w / (1.0 - a - b)
            for t in range(HORIZON):
                if s2 > cap[n]:
                    hits[n] += t >= 1
                    s2 = cap[n]
                eps = np.sqrt(s2) * z[p, t, n]
                out[p, t, n] = mu + eps
                s2 = w + a * eps * eps + b * s2
    return out, hits


def test_an_infinite_cap_is_the_production_simulation_byte_for_byte(bank):
    art = bank.artifact
    panel, hits = gb.simulate_capped(art, np.full(4, np.inf), PATHS, HORIZON, SEED)
    assert panel.tobytes() == simulate_panel(art, PATHS, HORIZON, SEED).tobytes()
    np.testing.assert_array_equal(hits, 0)


def test_the_cap_binds_on_a_near_integrated_fit_and_the_variance_never_exceeds_it(bank):
    from qse.distributions.joint import draw_row_indices

    art = _integrated(bank.artifact)
    free, none = gb.simulate_capped(art, np.full(4, np.inf), PATHS, HORIZON, SEED)
    sd = np.sqrt(art.omega / (1.0 - art.alpha - art.beta))
    cap = (1.5 * sd) ** 2  # 1.5 x the long-run volatility: well inside the paths' wander
    panel, hits = gb.simulate_capped(art, cap, PATHS, HORIZON, SEED)
    assert (hits > 0).all() and (hits < PATHS * HORIZON).all()
    np.testing.assert_array_equal(none, 0)
    assert np.abs(free - art.mu).max() > np.abs(panel - art.mu).max()
    # every day's volatility, recovered as (r - mu) / z, is at most the cap's
    z = art.pool[draw_row_indices(art.pool_rows, PATHS, HORIZON, seed=SEED)]
    moved = np.abs(z) > 1e-3
    sigma = np.abs(panel - art.mu)[moved] / np.abs(z)[moved]
    funds = np.broadcast_to(np.arange(4), z.shape)[moved]
    assert (sigma <= np.sqrt(cap)[funds] * (1 + 1e-9)).all()
    assert (sigma >= np.sqrt(cap)[funds] * (1 - 1e-9)).sum() > 0  # held at the cap on some days


def test_cap_hit_counts_and_returns_match_a_plain_recursion(bank):
    art = _integrated(bank.artifact)
    sd = np.sqrt(art.omega / (1.0 - art.alpha - art.beta))
    cap = np.array([1.2, 1.5, 2.0, np.inf]) ** 2 * sd**2
    paths = 40
    panel, hits = gb.simulate_capped(art, cap, paths, HORIZON, SEED)
    ref, ref_hits = _reference(art, cap, paths, SEED)
    np.testing.assert_array_equal(hits, ref_hits)
    assert hits[0] > hits[1] > hits[2] > 0 and hits[3] == 0
    np.testing.assert_allclose(panel, ref, rtol=1e-12, atol=1e-15)


def test_the_cap_starts_at_the_first_day_when_the_long_run_variance_is_above_it(bank):
    art = bank.artifact
    long_run = art.omega / (1.0 - art.alpha - art.beta)
    panel, hits = gb.simulate_capped(art, long_run / 4.0, 3, HORIZON, SEED)
    ref, ref_hits = _reference(art, long_run / 4.0, 3, SEED)
    np.testing.assert_array_equal(hits, ref_hits)  # day-1 clamps are not counted as hits
    np.testing.assert_allclose(panel, ref, rtol=1e-12, atol=1e-15)  # but they are applied
    np.testing.assert_array_equal(gb.start_capped(art, long_run / 4.0), True)
    np.testing.assert_array_equal(gb.start_capped(art, long_run * 4.0), False)
    # day 1 of every path is clamped: its volatility is the cap's, not the long run's
    from qse.distributions.joint import draw_row_indices

    z = art.pool[draw_row_indices(art.pool_rows, 3, HORIZON, seed=SEED)]
    np.testing.assert_allclose(panel[:, 0] - art.mu, np.sqrt(long_run / 4.0) * z[:, 0])


def test_simulate_capped_rejects_non_finite_or_negative_dynamics(bank):
    art = bank.artifact
    cap = np.full(4, np.inf)
    integrated = replace(art, alpha=np.full(4, 0.2), beta=np.full(4, 0.8))  # no long-run level
    with pytest.raises(ValueError, match="long-run variance"):
        gb.simulate_capped(integrated, cap, 3, HORIZON, SEED)
    for name, bad in (("mu", np.nan), ("omega", -1e-6), ("alpha", np.inf), ("beta", -0.1)):
        values = np.array(getattr(art, name), dtype=float)
        values[2] = bad
        with pytest.raises(ValueError, match=name):
            gb.simulate_capped(replace(art, **{name: values}), cap, 3, HORIZON, SEED)


def test_a_garch_fund_with_a_flat_lookback_is_a_fit_failure(ctx, bank):
    sample = np.array(ctx.sample)
    sample[:, 2] = 0.0005  # fund C has a GARCH fit but no variance in the lookback
    flat = replace(ctx, sample=sample)
    with pytest.raises(gb.GarchFitFailed, match="C"):
        gb.variance_cap(flat, bank.artifact, 3.0)


def test_the_bank_records_which_funds_start_above_the_cap(ctx):
    gb.clear_fit_cache()
    tight = gb.garch_bank(ctx, "garch", SEED, vol_cap=0.2)  # below every long-run volatility
    assert tight.start_capped == dict.fromkeys(ctx.menu.holdings, True)
    loose = gb.garch_bank(ctx, "garch", SEED, vol_cap=50.0)
    assert loose.start_capped == dict.fromkeys(ctx.menu.holdings, False)
    assert gb.garch_bank(ctx, "garch", SEED, vol_cap=None).start_capped == {}


def test_the_cap_is_k_times_the_lookbacks_realized_volatility(ctx, bank):
    cap = gb.variance_cap(ctx, bank.artifact, 3.0)
    expected = 9.0 * np.var(np.log1p(ctx.sample), axis=0, ddof=1)
    np.testing.assert_allclose(cap, expected, rtol=1e-15)
    long_run = bank.artifact.omega / (1.0 - bank.artifact.alpha - bank.artifact.beta)
    assert not np.allclose(cap, 9.0 * long_run)  # not anchored on the long-run variance
    for k in (0.0, -1.0, np.inf, np.nan):
        with pytest.raises(ValueError, match="cap"):
            gb.variance_cap(ctx, bank.artifact, k)


def test_a_constant_volatility_fund_is_never_capped(ctx, monkeypatch):
    _failing(monkeypatch, "B")
    gb.clear_fit_cache()
    bank = gb.garch_bank(ctx, "garch", SEED, vol_cap=1e-3)  # a cap every GARCH fund hits
    cap = gb.variance_cap(ctx, bank.artifact, 1e-3)
    assert cap[1] == np.inf and np.isfinite(cap[[0, 2, 3]]).all()
    assert bank.cap_hits["B"] == 0 and all(bank.cap_hits[h] > 0 for h in "ACD")


def test_the_bank_is_capped_at_k_3_by_default_and_records_its_hits(ctx, monkeypatch):
    assert gb.GARCH_VOL_CAP == 3.0
    gb.clear_fit_cache()
    real = gb.simulate_capped
    seen = {}

    def spy(art, cap, paths, horizon, seed):
        seen["cap"] = cap
        return real(art, cap, paths, horizon, seed)

    monkeypatch.setattr(gb, "simulate_capped", spy)
    bank = gb.garch_bank(ctx, "garch", SEED)
    assert bank.vol_cap == 3.0
    np.testing.assert_array_equal(seen["cap"], gb.variance_cap(ctx, bank.artifact, 3.0))
    assert set(bank.cap_hits) == set(ctx.menu.holdings)
    tight = gb.garch_bank(ctx, "garch", SEED, vol_cap=1.0)
    assert tight.vol_cap == 1.0
    _, hits = real(bank.artifact, gb.variance_cap(ctx, bank.artifact, 1.0), PATHS, HORIZON, SEED)
    assert tight.cap_hits == dict(zip(ctx.menu.holdings, hits.tolist(), strict=True))
    assert all(isinstance(n, int) for n in tight.cap_hits.values())
    assert tight.cap_hit_share == {h: n / (PATHS * HORIZON) for h, n in tight.cap_hits.items()}
    assert 0 < max(tight.cap_hit_share.values()) < 1


def test_no_cap_leaves_the_bank_on_the_production_simulation(ctx):
    gb.clear_fit_cache()
    bank = gb.garch_bank(ctx, "garch", SEED, vol_cap=None)
    assert bank.vol_cap is None and bank.cap_hits == {} and bank.cap_hit_share == {}
    mixes = _mixes(np.random.default_rng(12), 4, 5)
    theirs = _production_years(bank, ctx, mixes)
    assert np.max(np.abs(bank.years(mixes) - theirs)) <= 1e-10


def test_path_terms_years_drawdowns_and_fund_sums(bank):
    # v3 §2.3, §2.6: wealth is the cumulative product of 1 + y_pt; S w is the additive year
    w = np.array([0.1, 0.2, 0.3, 0.4])
    years, drawdowns, sums = bank.path_terms(w)
    np.testing.assert_allclose(years, bank.years(w)[:, 0], rtol=0, atol=1e-12)
    daily = ((_k(bank, w) * w) @ bank.levelled_t).reshape(PATHS, HORIZON)
    daily += 1.0 + float(w @ bank.m) - _k(bank, w) * float(w @ bank.level_mean)
    for p in (0, 11, PATHS - 1):
        peak, worst = 1.0, 0.0
        for value in np.cumprod(daily[p]):
            peak = max(peak, value)
            worst = max(worst, 1.0 - value / peak)
        assert drawdowns[p] == pytest.approx(worst, abs=1e-13)
    np.testing.assert_allclose(sums @ w, (daily - 1.0).sum(axis=1), rtol=0, atol=1e-12)


def test_path_terms_absorbed_paths_have_drawdown_one(absorbing):
    _, bank = absorbing
    years, drawdowns, _ = bank.path_terms(np.array([0.5, 0.5]))
    lost = years == -1.0
    assert lost.any() and (drawdowns[lost] == 1.0).all() and (drawdowns[~lost] < 1.0).all()
