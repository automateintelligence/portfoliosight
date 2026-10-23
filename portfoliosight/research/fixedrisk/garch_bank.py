"""Piece 3 of the fixed-risk experiment: the GARCH(1,1)-t FHS path bank (protocol §3, §4).

`garch_bank(ctx, "garch", seed)` is the production volatility model (simulation engines spec
§4.3, §4.5; `engine/shape.py`, `engine/ranges.py`) run on one origin's training window only:

1. Fit, once per holding and origin. Each holding's daily log returns `log1p(r)` over the
   context's training rows (`ctx.sample`, `ctx.days`; nothing after `ctx.origin`) are fitted by
   QSE's `fit_garch_t_panel`, exactly as the production panel fit fits that column. The fit is
   cached in-process by (holding, origin, lookback, digest of the holding's dated column), so
   every seed and every menu whose training rows coincide reuse it. A fit QSE marks `fit_failed`
   (the optimizer did not converge, invalid or non-finite parameters) raises `GarchFitFailed`;
   nothing is substituted. QSE's other fallbacks are the production engine's own rules and stay
   (`near_constant`, e.g. TSP G; `non_stationary`; `insufficient_history`): a fallback holding is
   simulated at constant volatility and `GarchBank.fit_status` names it.
2. Pool: the training rows' standardized residuals (the sample has complete rows, so every row is
   a common row), re-standardized per column (QSE `residual_pool`, at least 126 rows).
3. Simulate: production `shape.simulate_panel` with the bank's seed, 2,000 x 252 days.
4. Level: production `ranges.garch_range_model` takes the pooled moments; step 1 is then applied
   once to the whole panel, in place, and the levelled panel `R'` is kept on the bank, fund-major
   (`levelled_t`, N x P*H, float64: both matrix-vector products of the hot path then stream
   contiguous rows, about 2.3 times faster than the path-major layout). `years` and
   `years_and_vjp` never exponentiate again.

Step 2 per mix: `y_pt = m'w + k(w) x_pt'w`, `x = R' - R_bar'`,
`k = sqrt(w'(Sigma/252)w / w'Sigma_R'w)`.
Zero-variance branch (protocol §4): `w'Sigma_R'w <= 1e-14` gives `k = 0`. A path with a day at or
below -100% is absorbed: its year is exactly -1 and its gradient zero; the mask is taken from the
gross days before any division.

Differences from production, both named by the protocol: the fit window is the 3-year training
window, not up to ten years of each fund's history (§5: not a qualification of the production
engine); the zero-variance threshold is the protocol's `1e-14` on `w'Sigma_R'w`, where production
tests `sd(y) = 0` exactly (no feasible mix of either menu comes near either threshold).
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd

from portfoliosight.engine.ranges import (
    MIX_BLOCK,
    _levelled,
    _step_one,
    garch_range_model,
    sample_digest,
)
from portfoliosight.engine.shape import (
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


class GarchFitFailed(RuntimeError):
    """A holding's GARCH fit at an origin failed; the driver labels its cells `garch_fit_failed`."""

    label = FIT_FAILED

    def __init__(self, holding: str, origin: date, reason: str):
        super().__init__(f"GARCH fit failed for {holding} at {origin.isoformat()}: {reason}")
        self.holding = holding
        self.origin = origin
        self.reason = reason

    def __reduce__(self):
        # Rebuilt from its three fields, so it crosses process boundaries (worker -> parent).
        return (type(self), (self.holding, self.origin, self.reason))


_FitKey = tuple[str, date, str, str]
_FIT_CACHE: dict[_FitKey, GarchPanelFit | GarchFitFailed] = {}


def clear_fit_cache() -> None:
    """Forget every cached holding fit (tests; a long driver may call it between origins)."""
    _FIT_CACHE.clear()


def fit_cache_size() -> int:
    return len(_FIT_CACHE)


def holding_fit(ctx: OriginContext, n: int) -> GarchPanelFit:
    """Holding `n`'s one-column GARCH-t fit on the context's training rows, cached.

    Raises `GarchFitFailed` when QSE reports `fit_failed`, when a day has no log return, or when
    the residuals of a varying holding are constant (QSE's pool would refuse them). A failure is
    cached too, so the other menus and seeds at the origin fail at once.
    """
    holding = ctx.menu.holdings[n]
    days = [day.isoformat() for day in ctx.days]
    column = np.ascontiguousarray(ctx.sample[:, n], dtype=np.float64)
    key = (holding, ctx.origin, ctx.lookback, sample_digest([holding], days, column[:, None]))
    cached = _FIT_CACHE.get(key)
    if cached is None:
        cached = _fit(holding, ctx.origin, pd.DatetimeIndex(ctx.days), column)
        _FIT_CACHE[key] = cached
    if isinstance(cached, GarchFitFailed):
        raise cached
    return cached


def _fit(
    holding: str, origin: date, index: pd.DatetimeIndex, column: np.ndarray
) -> GarchPanelFit | GarchFitFailed:
    if not np.isfinite(column).all():
        return GarchFitFailed(holding, origin, "the training column holds non-finite returns")
    if (column <= -1.0).any():
        return GarchFitFailed(holding, origin, "a daily return at or below -100% has no log return")
    frame = pd.DataFrame({holding: np.log1p(column)}, index=index)
    try:
        fit = fit_garch_t_panel(frame)
    except DistributionFitError as exc:
        return GarchFitFailed(holding, origin, str(exc))
    if fit.status[0] == "fit_failed":
        return GarchFitFailed(holding, origin, fit.messages[0] or "fit_failed")
    z = fit.std_residuals[:, 0]
    if np.ptp(z) <= _CONSTANT_RESIDUALS and fit.omega[0] > 0.0:
        return GarchFitFailed(holding, origin, "constant residuals for a varying holding")
    return fit


def _panel_fit(fits: list[GarchPanelFit]) -> GarchPanelFit:
    """The one-column fits side by side: what `fit_garch_t_panel` returns for the whole sample."""

    def stack(name: str) -> np.ndarray:
        return np.concatenate([np.asarray(getattr(fit, name)) for fit in fits], axis=-1)

    return GarchPanelFit(
        assets=tuple(fit.assets[0] for fit in fits),
        index=fits[0].index,
        mu=stack("mu"),
        omega=stack("omega"),
        alpha=stack("alpha"),
        beta=stack("beta"),
        nu=stack("nu"),
        conditional_volatility=stack("conditional_volatility"),
        std_residuals=stack("std_residuals"),
        status=tuple(fit.status[0] for fit in fits),
        messages=tuple(fit.messages[0] for fit in fits),
        n_obs=stack("n_obs"),
        last_row=stack("last_row"),
        last_resid=stack("last_resid"),
        last_sigma2=stack("last_sigma2"),
    )


def _frozen(values) -> np.ndarray:
    array = np.array(values, dtype=np.float64)
    array.setflags(write=False)
    return array


def origin_artifact(ctx: OriginContext) -> GarchArtifact:
    """The production artifact (`shape.GarchArtifact`) of the context's training window."""
    import arch  # QSE's fitter imports it anyway; only its version is read here

    holdings = list(ctx.menu.holdings)
    sample = np.asarray(ctx.sample, dtype=np.float64)
    if sample.shape != (len(ctx.days), len(holdings)):
        raise ValueError("the training sample has one row per day and one column per holding")
    fit = _panel_fit([holding_fit(ctx, n) for n in range(len(holdings))])
    pool = np.asarray(residual_pool(fit, restandardize=True, min_rows=MIN_POOL_ROWS))
    days = [day.isoformat() for day in ctx.days]
    z = fit.std_residuals
    outliers = tuple(
        {"id": holdings[n], "date": days[row], "z": float(z[row, n])}
        for row, n in np.argwhere(np.abs(z) > OUTLIER_Z)
    )
    long_run = garch11_long_run_variance(fit.omega, fit.alpha, fit.beta)
    return GarchArtifact(
        funds=tuple(holdings),
        rows=len(days),
        start=days[0],
        end=days[-1],
        sample_sha256=sample_digest(holdings, days, sample),
        mu=_frozen(fit.mu),
        omega=_frozen(fit.omega),
        alpha=_frozen(fit.alpha),
        beta=_frozen(fit.beta),
        nu=_frozen(fit.nu),
        status=tuple(str(status) for status in fit.status),
        messages=tuple(fit.messages),
        n_obs=tuple(int(count) for count in fit.n_obs),
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
    fit_status: dict[str, str]  # holding -> QSE status ("garch" or a production fallback)
    artifact: GarchArtifact = field(repr=False)
    horizon: int = HORIZON
    engine: Engine = "garch"
    growth_bound_ok: bool = True

    def __post_init__(self) -> None:
        self.paths = self.levelled_t.shape[1] // self.horizon
        self.m = self.mu_s / TRADING_DAYS  # daily chart means

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
    """The GARCH bank of one (menu, origin, seed), from the context's training window only.

    Raises `GarchFitFailed` when a holding's fit fails, and `ValueError` when the context holds a
    day after its origin or a levelled return overflows (production `garch_range_model`).
    """
    if engine != "garch":
        raise ValueError(f"garch_bank builds the garch engine, not {engine!r}")
    if not ctx.days or max(ctx.days) > ctx.origin:
        raise ValueError("the training window must be non-empty and end on or before the origin")
    artifact = origin_artifact(ctx)
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
        artifact=artifact,
    )
