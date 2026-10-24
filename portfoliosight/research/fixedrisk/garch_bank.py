"""Piece 3 of the fixed-risk experiment: the GARCH(1,1)-t FHS path bank (protocol §3, §4).

`garch_bank(ctx, "garch", seed)` is the production volatility model (simulation engines spec
§4.3, §4.5; `engine/shape.py`, `engine/ranges.py`) run at one origin under protocol amendment 1
as revised 2026-10-24 (ADR 0005; terms in `GLOSSARY.md`): dynamics from a recent window, shocks
from the full common history, level from the lookback.

1. Dynamics window, once per holding and origin. Each holding's daily log returns `log1p(r)`,
   its own rows of `ctx.history` (nothing after `ctx.origin`), are fitted by QSE's
   `fit_garch_t_panel` on its last `DYNAMICS_ROWS` (10 x 252) rows, or all it has when shorter.
   When QSE's status is `fit_failed` or `non_stationary`, the last `RETRY_ROWS` (3 x 252) rows
   are fitted instead; when that is not `garch` either, the holding is held at constant
   volatility with the 10-year window's sample mean and variance (QSE's own fallback of that
   fit). `near_constant` and `insufficient_history` stay as QSE rules them on the 10-year
   window. `GarchBank.windows` names the window per holding (`10y`, `3y`, `fallback`),
   `GarchBank.fit_status` QSE's status of the fit used, `GarchBank.fallbacks` the fallback
   holdings with both reasons. The result is cached in-process by (holding, origin, first and
   last day and digest of the 10-year window), so every seed, lookback and menu at the origin
   reuses it. `GarchFitFailed` is left for unusable input: a non-finite return or a day at or
   below -100% in the dynamics window or the shock pool span, fewer than two returns, or a
   varying holding whose shocks are constant on the pool's rows.
2. Shock pool: every common row of `ctx.history` (all holdings have a return), from the
   youngest holding's first return to the origin, weighted equally. Each holding's column is
   standardized by running its fitted variance recursion forward over its own rows of that span,
   started at the fit's long-run variance on the span's first row: `z_t = (r_t - mu) / sigma_t`.
   A constant-volatility holding divides by its sample standard deviation (0 stays 0). The
   common rows are then re-standardized per column (QSE `residual_pool`, at least 126 rows).
   Older shocks are standardized with recent parameters, on purpose (ADR 0005).
3. Simulate: production `shape.simulate_panel` with the bank's seed, 2,000 x 252 days, each
   recursion started at the dynamics fit's long-run variance (the production start).
4. Level: production `ranges.garch_range_model` takes the pooled moments and the lookback's chart
   moments (`ctx.mu_s`, `ctx.cov`, from `ctx.sample`); the 5-year sensitivity changes only these.
   Step 1 is then applied once to the whole panel, in place, and the levelled panel `R'` is kept
   on the bank, fund-major (`levelled_t`, N x P*H, float64: both matrix-vector products of the
   hot path then stream contiguous rows, about 2.3 times faster than the path-major layout).
   `years` and `years_and_vjp` never exponentiate again.

Step 2 per mix: `y_pt = m'w + k(w) x_pt'w`, `x = R' - R_bar'`,
`k = sqrt(w'(Sigma/252)w / w'Sigma_R'w)`.
Zero-variance branch (protocol §4): `w'Sigma_R'w <= 1e-14` gives `k = 0`. A path with a day at or
below -100% is absorbed: its year is exactly -1 and its gradient zero; the mask is taken from the
gross days before any division.

Differences from production (§5: not a qualification of the production engine): the dynamics
window is each holding's own last 10 years with a 3-year retry, where production fits on the
menu calendar's last ten years without a retry; the shock pool spans the full common history,
where production pools the fit window's common rows; the zero-variance threshold is the
protocol's `1e-14` on `w'Sigma_R'w`, where production tests `sd(y) = 0` exactly (no feasible mix
of either menu comes near either threshold).
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd
from scipy.signal import lfilter

from portfoliosight.engine.ranges import (
    MIX_BLOCK,
    _levelled,
    _step_one,
    garch_range_model,
    sample_digest,
)
from portfoliosight.engine.shape import (
    CANONICAL_NAN,
    MIN_POOL_ROWS,
    OUTLIER_Z,
    RETURNS,
    GarchArtifact,
    qse_commit,
    simulate_panel,
)
from portfoliosight.engine.stats import TRADING_DAYS
from portfoliosight.research.fixedrisk.contracts import (
    FIT_FAILED,
    HORIZON,
    PATHS,
    PRIMARY_SEED,
    Engine,
    OriginContext,
)
from qse.distributions.garch_recursion import garch11_long_run_variance
from qse.distributions.joint import fit_garch_t_panel, residual_pool
from qse.distributions.joint.panel_fit import GarchPanelFit
from qse.exceptions import DistributionFitError

ZERO_VARIANCE = 1e-14  # protocol §4: w' Sigma_R' w at or below this gives k = 0 and grad k = 0
CHUNK_BYTES = 8 * 2**20  # `years` work buffer: mixes x paths of gross days, cache-sized
_CONSTANT_RESIDUALS = 1e-12  # QSE residual_pool's rounding floor for a constant column
DYNAMICS_ROWS = 10 * TRADING_DAYS  # the dynamics window: a holding's own last 10 years of rows
RETRY_ROWS = 3 * TRADING_DAYS  # the retry when the 10-year fit is not `garch`
RETRY_STATUSES = ("fit_failed", "non_stationary")  # QSE statuses that trigger the 3-year retry
FALLBACK = "fallback"  # window label: neither window fits, constant volatility (amendment 1)


class GarchFitFailed(RuntimeError):
    """A holding's input at an origin cannot be used; the driver labels its cells
    `garch_fit_failed`. A fit that merely fails is retried, then held at constant volatility."""

    label = FIT_FAILED

    def __init__(self, holding: str, origin: date, reason: str):
        super().__init__(f"GARCH fit failed for {holding} at {origin.isoformat()}: {reason}")
        self.holding = holding
        self.origin = origin
        self.reason = reason

    def __reduce__(self):
        # Rebuilt from its three fields, so it crosses process boundaries (worker -> parent).
        return (type(self), (self.holding, self.origin, self.reason))


@dataclass(frozen=True)
class HoldingFit:
    """One holding's dynamics: the QSE fit used, its window label and, if any, why not 10 years."""

    fit: GarchPanelFit  # one column, indexed by the window's own days
    window: str  # "10y" | "3y" | FALLBACK
    reason: str  # empty for "10y"; the failed fits' QSE messages otherwise


_FitKey = tuple[str, date, str, str, str]
_FIT_CACHE: dict[_FitKey, HoldingFit | GarchFitFailed] = {}


def clear_fit_cache() -> None:
    """Forget every cached holding fit (tests; a long driver may call it between origins)."""
    _FIT_CACHE.clear()


def fit_cache_size() -> int:
    return len(_FIT_CACHE)


def origin_history(ctx: OriginContext) -> pd.DataFrame:
    """The context's history (`ctx.history`), checked: menu columns, no day after the origin."""
    history = ctx.history
    if history is None:
        raise ValueError("the context carries no history (data.origin_context builds it)")
    if tuple(str(column) for column in history.columns) != tuple(ctx.menu.holdings):
        raise ValueError("the history has one column per holding, in menu order")
    index = history.index
    if not isinstance(index, pd.DatetimeIndex) or len(index) < 2:
        raise ValueError("the history is indexed by at least two dates")
    if not index.is_monotonic_increasing or index[-1] > pd.Timestamp(ctx.origin):
        raise ValueError("the history must be in date order and end on or before the origin")
    return history


def holding_fit(ctx: OriginContext, n: int) -> HoldingFit:
    """Holding `n`'s dynamics fit (10 years, else 3, else constant volatility), cached.

    Raises `GarchFitFailed` for unusable input in the dynamics window (a non-finite return, a day
    at or below -100%, fewer than two returns); the failure is cached too.
    """
    holding = ctx.menu.holdings[n]
    window = origin_history(ctx).iloc[:, n].dropna().iloc[-DYNAMICS_ROWS:]
    days = [stamp.date().isoformat() for stamp in pd.DatetimeIndex(window.index)]
    column = np.ascontiguousarray(window.to_numpy(dtype=np.float64))
    first, last = (days[0], days[-1]) if days else ("", "")
    key = (holding, ctx.origin, first, last, sample_digest([holding], days, column[:, None]))
    cached = _FIT_CACHE.get(key)
    if cached is None:
        cached = _dynamics(holding, ctx.origin, pd.DatetimeIndex(window.index), column)
        _FIT_CACHE[key] = cached
    if isinstance(cached, GarchFitFailed):
        raise cached
    return cached


def _unusable(column: np.ndarray) -> str | None:
    if not np.isfinite(column).all():
        return "non-finite returns"
    if (column <= -1.0).any():
        return "a daily return at or below -100% has no log return"
    return None


def _dynamics(
    holding: str, origin: date, index: pd.DatetimeIndex, column: np.ndarray
) -> HoldingFit | GarchFitFailed:
    problem = _unusable(column)
    if problem is not None:
        return GarchFitFailed(holding, origin, f"the dynamics window holds {problem}")
    logs = np.log1p(column)
    try:
        ten = fit_garch_t_panel(pd.DataFrame({holding: logs}, index=index))
        if ten.status[0] not in RETRY_STATUSES:
            return HoldingFit(ten, "10y", "")
        reason = f"10y {ten.status[0]}: {ten.messages[0]}"
        three = fit_garch_t_panel(
            pd.DataFrame({holding: logs[-RETRY_ROWS:]}, index=index[-RETRY_ROWS:])
        )
    except DistributionFitError as exc:
        return GarchFitFailed(holding, origin, str(exc))
    if three.status[0] == "garch":
        return HoldingFit(three, "3y", reason)
    return HoldingFit(ten, FALLBACK, f"{reason}; 3y {three.status[0]}: {three.messages[0]}")


def _standardized(logs: np.ndarray, fit: GarchPanelFit) -> tuple[np.ndarray, np.ndarray]:
    """Shocks and volatilities of `logs` under the fitted recursion, from its long-run variance.

    `sigma2_0` is the long-run variance; `sigma2_t = omega + alpha e_{t-1}^2 + beta sigma2_{t-1}`
    with `e = logs - mu`. A constant-volatility fit (`alpha = beta = 0`, `omega` the sample
    variance) divides by its sample standard deviation; a zero one leaves zero shocks.
    """
    mu, omega = float(fit.mu[0]), float(fit.omega[0])
    alpha, beta = float(fit.alpha[0]), float(fit.beta[0])
    e = logs - mu
    if alpha == 0.0 and beta == 0.0:
        sigma = np.full_like(logs, np.sqrt(omega))
    else:
        start = float(garch11_long_run_variance(omega, alpha, beta))
        drive = omega + alpha * e[:-1] ** 2
        rest = lfilter([1.0], [1.0, -beta], drive, zi=[beta * start])[0]
        sigma = np.sqrt(np.concatenate([[start], rest]))
    z = np.divide(e, sigma, out=np.zeros_like(e), where=sigma > 0.0)
    return z, sigma


def _frozen(values) -> np.ndarray:
    array = np.array(values, dtype=np.float64)
    array.setflags(write=False)
    return array


def origin_artifact(ctx: OriginContext) -> tuple[GarchArtifact, dict[str, str]]:
    """The production artifact (`shape.GarchArtifact`) of the context's dynamics fits and shock
    pool, and each holding's window label."""
    import arch  # QSE's fitter imports it anyway; only its version is read here

    holdings = list(ctx.menu.holdings)
    history = origin_history(ctx)
    fits = [holding_fit(ctx, n) for n in range(len(holdings))]
    common = history.notna().all(axis=1).to_numpy()
    if not common.any():
        raise ValueError("the holdings share no day with a return: no shock pool")
    span = history.iloc[int(np.argmax(common)) :]  # the youngest holding's first return onward
    index = pd.DatetimeIndex(span.index)
    z = np.full(span.shape, np.nan)
    sigma = np.full(span.shape, np.nan)
    for n, holding in enumerate(holdings):
        rows = np.flatnonzero(span.iloc[:, n].notna().to_numpy())
        column = span.iloc[rows, n].to_numpy(dtype=np.float64)
        problem = _unusable(column)
        if problem is not None:
            raise GarchFitFailed(holding, ctx.origin, f"the shock pool span holds {problem}")
        z[rows, n], sigma[rows, n] = _standardized(np.log1p(column), fits[n].fit)

    def stack(name: str) -> np.ndarray:
        return np.concatenate([np.asarray(getattr(item.fit, name)) for item in fits])

    panel = GarchPanelFit(
        assets=tuple(holdings),
        index=index,
        mu=stack("mu"),
        omega=stack("omega"),
        alpha=stack("alpha"),
        beta=stack("beta"),
        nu=stack("nu"),
        conditional_volatility=sigma,
        std_residuals=z,
        status=tuple(item.fit.status[0] for item in fits),
        messages=tuple(item.reason or item.fit.messages[0] for item in fits),
        n_obs=stack("n_obs"),
        last_row=stack("last_row"),
        last_resid=stack("last_resid"),
        last_sigma2=stack("last_sigma2"),
    )
    pooled = panel.common_rows
    for n, holding in enumerate(holdings):
        if panel.omega[n] > 0.0 and np.ptp(z[pooled, n]) <= _CONSTANT_RESIDUALS:
            reason = "constant shocks on the pool's rows for a varying holding"
            raise GarchFitFailed(holding, ctx.origin, reason)
    pool = np.asarray(residual_pool(panel, restandardize=True, min_rows=MIN_POOL_ROWS))
    days = [stamp.date().isoformat() for stamp in index]
    values = span.to_numpy(dtype=np.float64, copy=True)
    values[np.isnan(values)] = CANONICAL_NAN
    outliers = tuple(
        {"id": holdings[n], "date": days[row], "z": float(z[row, n])}
        for row, n in np.argwhere(np.abs(z) > OUTLIER_Z)
    )
    long_run = garch11_long_run_variance(panel.omega, panel.alpha, panel.beta)
    artifact = GarchArtifact(
        funds=tuple(holdings),
        rows=len(days),
        start=days[0],
        end=days[-1],
        sample_sha256=sample_digest(holdings, days, values),
        mu=_frozen(panel.mu),
        omega=_frozen(panel.omega),
        alpha=_frozen(panel.alpha),
        beta=_frozen(panel.beta),
        nu=_frozen(panel.nu),
        status=tuple(str(status) for status in panel.status),
        messages=tuple(panel.messages),
        n_obs=tuple(int(count) for count in panel.n_obs),
        long_run_sigma_annual=_frozen(np.sqrt(TRADING_DAYS * long_run)),
        pool=_frozen(pool),
        pool_rows=len(pool),
        pool_sha256=hashlib.sha256(np.ascontiguousarray(pool, dtype="<f8").tobytes()).hexdigest(),
        outliers=outliers,
        splice_dates=(),
        unavailable_reason=None,
        qse=qse_commit(),
        arch=str(arch.__version__),
        returns=RETURNS,
    )
    return artifact, {holding: item.window for holding, item in zip(holdings, fits, strict=True)}


@dataclass(eq=False)
class GarchBank:
    """2,000 levelled GARCH-t FHS paths of one (menu, origin, seed); implements `PathBank`."""

    seed: int
    holdings: tuple[str, ...]
    origin: date
    levelled_t: np.ndarray  # N x (P*H) levelled simple returns R', fund-major, read-only
    level_mean: np.ndarray  # N, pooled mean of R'
    level_cov: np.ndarray  # N x N, pooled (ddof 0) covariance of R'
    mu_s: np.ndarray  # N, annual
    cov: np.ndarray  # N x N, annual
    fit_status: dict[str, str]  # holding -> QSE status of the fit used
    windows: dict[str, str]  # holding -> dynamics window: "10y", "3y" or FALLBACK
    artifact: GarchArtifact = field(repr=False)
    horizon: int = HORIZON
    engine: Engine = "garch"
    growth_bound_ok: bool = True

    def __post_init__(self) -> None:
        self.paths = self.levelled_t.shape[1] // self.horizon
        self.m = self.mu_s / TRADING_DAYS  # daily chart means

    @property
    def fallbacks(self) -> dict[str, str]:
        """Holdings that fit on neither window, held at constant volatility: name -> reasons."""
        art = self.artifact
        return {
            fund: message
            for fund, message in zip(art.funds, art.messages, strict=True)
            if self.windows[fund] == FALLBACK
        }

    @property
    def nbytes(self) -> int:
        """Bytes held by the bank's arrays (the levelled panel dominates)."""
        arrays = (self.levelled_t, self.level_mean, self.level_cov, self.mu_s, self.cov)
        pool = self.artifact.pool
        return sum(a.nbytes for a in arrays) + (0 if pool is None else pool.nbytes)

    # ------------------------------------------------------------------ step 2 terms

    def _terms(self, mixes: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Each mix's weights on R' (M x N, `k w`) and its daily constant (M), as `_garch_terms`."""
        m_w = mixes @ self.m
        s_w = np.sqrt(np.einsum("ij,jk,ik->i", mixes, self.cov, mixes) / TRADING_DAYS)
        v2 = np.einsum("ij,jk,ik->i", mixes, self.level_cov, mixes)
        sd_y = np.sqrt(np.maximum(v2, 0.0))
        k = np.divide(s_w, sd_y, out=np.zeros_like(s_w), where=v2 > ZERO_VARIANCE)
        return k[:, None] * mixes, m_w - k * (mixes @ self.level_mean)

    def _mixes(self, weights) -> np.ndarray:
        mixes = np.atleast_2d(np.asarray(weights, dtype=np.float64))
        if mixes.ndim != 2 or mixes.shape[1] != len(self.holdings):
            raise ValueError(f"a mix of this menu has {len(self.holdings)} weights")
        if not np.isfinite(mixes).all():
            raise ValueError("a mix's weights must be finite")
        return mixes

    # ------------------------------------------------------------------ PathBank

    def years(self, mixes: np.ndarray) -> np.ndarray:
        """(P, M) compounded one-year returns; an absorbed path is exactly -1.0."""
        mixes = self._mixes(mixes)
        weights, shift = self._terms(mixes)
        days, paths = self.horizon, self.paths
        width = min(MIX_BLOCK, len(mixes))
        step = max(1, CHUNK_BYTES // (days * width * 8))
        buffer = np.empty(width * min(step, paths) * days)  # reused: its pages are touched once
        years = np.empty((paths, len(mixes)))
        for start in range(0, len(mixes), width):
            block = slice(start, start + width)
            v = weights[block]  # B x N
            for first in range(0, paths, step):
                part = slice(first, min(first + step, paths))
                cols = (part.stop - part.start) * days
                gross = np.matmul(
                    v,
                    self.levelled_t[:, part.start * days : part.stop * days],
                    out=buffer[: len(v) * cols].reshape(len(v), cols),
                )
                gross += (1.0 + shift[block])[:, None]
                daily = gross.reshape(len(v), -1, days)
                product = daily.prod(axis=2)
                product[daily.min(axis=2) <= 0.0] = 0.0
                years[part, block] = product.T
        years -= 1.0
        return years

    def years_and_vjp(self, w: np.ndarray) -> tuple[np.ndarray, Callable[[np.ndarray], np.ndarray]]:
        """One mix's (P,) years and `vjp(a)`: the gradient of `sum_p a_p R_p` with respect to `w`.

        With `g_pt = 1 + m'w + k x_pt'w` and `c_p = a_p (1 + R_p)` (0 on absorbed paths),
        `grad = m U + k (R''u - R_bar' U) + (grad k / k) (H C - (1 + m'w) U)`, where
        `u_pt = c_p / g_pt`, `U = sum u` and `C = sum c`; the last term is
        `sum_p c_p sum_t (x_pt'w) grad k / g_pt`, since `x_pt'w = (g_pt - 1 - m'w) / k`.
        """
        if np.ndim(w) != 1:
            raise ValueError("years_and_vjp takes one mix, a vector of weights")
        w = self._mixes(w)[0]
        m_w = float(w @ self.m)
        sigma_w = self.cov @ w
        s2 = float(w @ sigma_w)
        level_w = self.level_cov @ w
        v2 = float(w @ level_w)
        if v2 > ZERO_VARIANCE and s2 > 0.0:
            k = float(np.sqrt(s2 / TRADING_DAYS) / np.sqrt(v2))
            dlogk = sigma_w / s2 - level_w / v2  # grad k / k
        else:
            k, dlogk = 0.0, np.zeros_like(w)
        shift = m_w - k * float(w @ self.level_mean)
        gross = (k * w) @ self.levelled_t
        gross += 1.0 + shift
        daily = gross.reshape(self.paths, self.horizon)
        lost: np.ndarray = np.any(daily <= 0.0, axis=1)  # absorption mask, before any division
        year = daily.prod(axis=1)
        year[lost] = 0.0
        year -= 1.0
        horizon = self.horizon

        def vjp(a: np.ndarray) -> np.ndarray:
            a = np.asarray(a, dtype=np.float64)
            if a.shape != year.shape:
                raise ValueError(f"path weights must have shape {year.shape}")
            c = a * (1.0 + year)
            c[lost] = 0.0
            safe = np.where(lost[:, None], 1.0, daily) if lost.any() else daily
            u = c[:, None] / safe
            total_u = float(u.sum())
            grad = self.m * total_u
            if k > 0.0:
                grad += k * (self.levelled_t @ u.reshape(-1) - self.level_mean * total_u)
                grad += dlogk * (horizon * float(c.sum()) - (1.0 + m_w) * total_u)
            return grad

        return year, vjp


def garch_bank(ctx: OriginContext, engine: Engine = "garch", seed: int = PRIMARY_SEED) -> GarchBank:
    """The GARCH bank of one (menu, origin, seed): dynamics window, shock pool, lookback level.

    Raises `GarchFitFailed` when a holding's input cannot be used (a fit that fails on both
    windows is held at constant volatility instead), and `ValueError` when the context holds a
    day after its origin or a levelled return overflows (production `garch_range_model`).
    """
    if engine != "garch":
        raise ValueError(f"garch_bank builds the garch engine, not {engine!r}")
    if not ctx.days or max(ctx.days) > ctx.origin:
        raise ValueError("the training window must be non-empty and end on or before the origin")
    artifact, windows = origin_artifact(ctx)
    panel = simulate_panel(artifact, PATHS, HORIZON, seed)  # P x H x N, C-contiguous, ours
    model = garch_range_model(panel, ctx.mu_s, ctx.cov, seed)
    step = _step_one(model.mu_s, model.cov, model.mean, model.sd)
    level_mean, level_cov, mu_s, cov = model.level_mean, model.level_cov, model.mu_s, model.cov
    flat = panel.reshape(-1, panel.shape[2])  # a view: step 1 runs in place, once
    _levelled(flat, step, out=flat)
    levelled_t = np.ascontiguousarray(flat.T)
    del model, panel, flat  # the path-major copy goes; only the fund-major one stays
    levelled_t.setflags(write=False)
    return GarchBank(
        seed=seed,
        holdings=tuple(ctx.menu.holdings),
        origin=ctx.origin,
        levelled_t=levelled_t,
        level_mean=level_mean,
        level_cov=level_cov,
        mu_s=mu_s,
        cov=cov,
        fit_status=dict(zip(artifact.funds, artifact.status, strict=True)),
        windows=windows,
        artifact=artifact,
    )
