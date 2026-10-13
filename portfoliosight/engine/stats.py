"""Moments, the expected-return blend, the risk-free rate and the six-month range (spec 4.3, 4.9).

Everything leaves this module in annual units: `mu = 252 * mean(r)`, `sigma = sqrt(252) * sd(r)`.
Correlations are shrunk, not covariances, so a fund with almost no volatility keeps its own
variance; a floor of 0.01% a year on `sigma` keeps every covariance matrix factorable. The
floor applies to the variances only: correlations are those of the returns as they are.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np
from sklearn.covariance import LedoitWolf

TRADING_DAYS = 252
SIGMA_FLOOR = 1e-4
EW_HALFLIFE_DAYS = 252
EW_SHRINKAGE = 0.2
RISK_FREE_SOURCES = ("SGOV", "TSP-G")
RISK_FREE_FALLBACK = 0.04
RANGE_Z = 1.96
ROUNDING_NOISE = 1e3 * np.finfo(float).eps  # a deviation this small, relative to the returns


@dataclass(frozen=True)
class Moments:
    """Annualized sample moments of one window."""

    mu: np.ndarray  # sample mean, the `mu_hat` of spec 4.3
    sigma: np.ndarray  # volatility, floored at SIGMA_FLOOR
    cov: np.ndarray  # diag(sigma) R diag(sigma) with the shrunk correlation R
    t_eff: float  # rows for a fixed window, 1 / sum(omega^2) for a weighted one


def ew_weights(rows: int, halflife: int = EW_HALFLIFE_DAYS) -> np.ndarray:
    """Observation weights that halve every `halflife` rows, heaviest last, summing to 1."""
    if rows < 1:
        raise ValueError("a window needs at least one row")
    age = rows - 1 - np.arange(rows)
    weights = 0.5 ** (age / float(halflife))
    return weights / weights.sum()


def estimate_moments(returns, omega=None) -> Moments:
    """Annual `mu`, `sigma` and shrunk covariance of a T x N matrix of daily returns.

    `omega=None` is a fixed window: sample moments with ddof = 1 and `LedoitWolf` on standardized
    returns, renormalized to a correlation matrix. An `omega` vector (non-negative, summing to 1)
    is the exponentially weighted window: weighted moments with the sample correction
    `1 / (1 - sum(omega^2))` and the fixed shrinkage `R_s = 0.8 R + 0.2 I`.
    """
    r = np.asarray(returns, dtype=float)
    if r.ndim != 2 or r.shape[0] < 2 or r.shape[1] < 1:
        raise ValueError("returns must be a T x N array with T >= 2 and N >= 1")
    if not np.isfinite(r).all():
        raise ValueError("returns hold missing or non-finite values")
    if omega is None:
        mean = r.mean(axis=0)
        daily_sd = r.std(axis=0, ddof=1)
        t_eff = float(len(r))
        corr = _shrunk_correlation(r, _live_scale(r, daily_sd))
    else:
        weights = _observation_weights(omega, len(r))
        concentration = float(weights @ weights)
        mean = weights @ r
        centered = r - mean
        scatter = (centered * weights[:, None]).T @ centered / (1.0 - concentration)
        daily_sd = np.sqrt(np.diag(scatter))
        t_eff = 1.0 / concentration
        raw = _as_correlation(scatter, _live_scale(r, daily_sd))
        corr = (1.0 - EW_SHRINKAGE) * raw + EW_SHRINKAGE * np.eye(r.shape[1])
    sigma = np.maximum(np.sqrt(TRADING_DAYS) * daily_sd, SIGMA_FLOOR)
    return Moments(
        mu=TRADING_DAYS * mean, sigma=sigma, cov=np.outer(sigma, sigma) * corr, t_eff=t_eff
    )


def menu_beta_blend(mu_hat, cov, rf: float) -> tuple[np.ndarray, np.ndarray]:
    """The menu-beta heuristic of spec 4.3: `(mu_s, pi)`.

    `pi_i = rf + beta_i * max(mu_eq - rf, 0)` with `beta` each fund's beta to the equal-weighted
    menu, and `mu_s = 0.5 * mu_hat + 0.5 * pi`.
    """
    mu_hat = np.asarray(mu_hat, dtype=float)
    cov = np.asarray(cov, dtype=float)
    w_eq = np.full(len(mu_hat), 1.0 / len(mu_hat))
    beta = cov @ w_eq / float(w_eq @ cov @ w_eq)
    premium = max(float(w_eq @ mu_hat) - rf, 0.0)
    pi = rf + beta * premium
    return 0.5 * mu_hat + 0.5 * pi, pi


def risk_free_rate(returns_by_symbol: Mapping[str, object]) -> float:
    """Trailing-12-month total return of SGOV, else of the TSP G Fund, else 4%.

    Each value is a served symbol's daily total-return series up to `asof`, on the symbol's own
    pricing days: on a wider calendar the days it did not price would be missing returns, and
    the growth across them with them. The 12-month return compounds its last 252 returns; a
    series with fewer than 252 has no such return and is passed over.
    """
    for symbol in RISK_FREE_SOURCES:
        series = returns_by_symbol.get(symbol)
        if series is None:
            continue
        values = np.asarray(series, dtype=float)
        values = values[~np.isnan(values)]
        if len(values) >= TRADING_DAYS:
            return float(np.prod(1.0 + values[-TRADING_DAYS:]) - 1.0)
    return RISK_FREE_FALLBACK


def range6m(mu: float, sigma: float) -> tuple[float, float, float]:
    """`(low, typical, high)` over six months: `mu/2 -+ 1.96 * sigma/sqrt(2)` (spec 4.9)."""
    typical = mu / 2.0
    spread = RANGE_Z * sigma / np.sqrt(2.0)
    return float(typical - spread), float(typical), float(typical + spread)


def _observation_weights(omega, rows: int) -> np.ndarray:
    weights = np.asarray(omega, dtype=float)
    if weights.shape != (rows,):
        raise ValueError("omega must hold one weight per row")
    if not np.isfinite(weights).all() or (weights < 0).any():
        raise ValueError("omega must be finite and non-negative")
    if abs(weights.sum() - 1.0) > 1e-9:
        raise ValueError("omega must sum to 1")
    if float(weights @ weights) >= 1.0:
        raise ValueError("omega must put weight on more than one row")
    return weights


def _live_scale(r: np.ndarray, daily_sd: np.ndarray) -> np.ndarray:
    """Each fund's own daily deviation, or 0 for a fund whose returns do not vary.

    The floor on `sigma` changes a fund's variance, never its correlations: those come from
    the deviation the returns actually show. Only a series that is constant up to rounding has
    none to show; it is marked with a zero scale and treated as uncorrelated.
    """
    return np.where(daily_sd > ROUNDING_NOISE * np.abs(r).max(axis=0), daily_sd, 0.0)


def _shrunk_correlation(r: np.ndarray, scale: np.ndarray) -> np.ndarray:
    """`LedoitWolf` on the returns standardized by `scale`, renormalized to a correlation.

    A fund with a zero scale has nothing to standardize by: it takes no part in the shrinkage
    and is uncorrelated with every other fund, another such fund included.
    """
    live = scale > 0
    corr = np.eye(len(scale))
    if live.any():
        shrunk = LedoitWolf(store_precision=False).fit(r[:, live] / scale[live]).covariance_
        corr[np.ix_(live, live)] = _as_correlation(shrunk, np.sqrt(np.diag(shrunk)))
    return corr


def _as_correlation(matrix: np.ndarray, scale: np.ndarray) -> np.ndarray:
    """`matrix / (scale scale')` made exactly symmetric with a unit diagonal.

    A zero scale has no correlation to compute: that fund is treated as uncorrelated.
    """
    dead = ~(scale > 0)
    safe = np.where(dead, 1.0, scale)
    corr = matrix / np.outer(safe, safe)
    corr[dead, :] = 0.0
    corr[:, dead] = 0.0
    corr = (corr + corr.T) / 2.0
    np.fill_diagonal(corr, 1.0)
    return corr
