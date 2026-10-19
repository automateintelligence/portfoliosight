"""Diversification ratio squared (DR²) and expected shortfall at 2.5% (ES_2.5) of one portfolio.

DR² (spec 5.2) is `(w'sigma)² / (w'Sigma w)`, with `sigma` and `Sigma` the annual volatilities and
shrunk covariance of `stats.estimate_moments`. The estimator is part of the measure's definition:
DR² rises with correlation shrinkage toward the identity for long-only holdings whose pairwise
correlations are non-negative and can fall for a negatively correlated pair, so a value is not
comparable across estimators. `dr2` returns the shrinkage the moments applied beside the value.
The score is unchanged when every weight is multiplied by the same non-zero factor.
It is undefined when the portfolio variance computes to exactly zero (`UndefinedMeasure`); a
variance that is tiny but positive is scored as it stands, never screened by an epsilon.

Disclosed property, zero-volatility holding. A fund whose `sigma` is exactly 0 has zero covariance
with every fund and adds nothing to numerator or denominator, so DR² is the same at every weight of
that fund, and the same again when the risky weights are scaled to make room for it. DR² therefore
cannot set the weight of such a fund; a risk ceiling or a guard has to (TSP G, protocol 2). In
production `sigma` is floored at `stats.SIGMA_FLOOR`, so a near-constant fund is not exactly
zero-volatility and DR² is only nearly indifferent to it. At weight c the relative shift is about
`2 c SIGMA_FLOOR / (w'sigma)` for an uncorrelated floor fund (stats gives a constant series no
correlation), and for any correlation DR² stays between `(A + d)² / (sqrt(V) + d)²` and
`(A + d)² / (sqrt(V) - d)²`, with `A = w'sigma` and `V = w'Sigma w` of the other funds and
`d = c SIGMA_FLOOR < sqrt(V)` (triangle inequality in the covariance norm). Both are tested.

ES_2.5 (protocol 6) is the mean of the lowest `ceil(0.025 P)` of `P` simulated annual returns.
It is a diagnostic field retained beside Bad / Typical / Good, never a guard: no module may read it
as one (promotion needs a recorded amendment, protocol D4). Take `Bad` as the linear-interpolation
2.5th percentile (`np.percentile(x, 2.5)`, as `ranges.one_year_ranges` does). Then `ES_2.5 <= Bad`
on every sample, exactly in floating point: with `k = ceil(0.025 P)` the tail is the sorted
indices `0 .. k - 1`, `k - 1 = floor(0.025 (P - 1))`, and Bad interpolates upward from that index.
Equality holds when the lowest `k + 1` returns are equal, in particular for a constant sample or a
two-valued one whose low value has more than `k` paths. Ties: the tail is the `k` smallest values
by value, so paths tied at the cut are interchangeable and the result is the same however they are
ordered, which makes it invariant to path order, bit for bit.

Phase 7.1 reuses this module for the browser twin.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from fractions import Fraction

import numpy as np

from portfoliosight.engine.stats import Moments

TAIL_FRACTION = Fraction(25, 1000)  # ES_2.5 averages the worst 2.5% of paths; exact, not a float


class UndefinedMeasure(ValueError):
    """A measure with no value for the portfolio asked about (not a malformed input)."""


@dataclass(frozen=True)
class Dr2:
    """DR² of one portfolio and the covariance shrinkage intensity its moments applied."""

    value: float
    shrinkage: float | None  # `Moments.shrinkage`: fitted (fixed window), 0.2 (EW), None if none


def dr2(weights, moments: Moments) -> Dr2:
    """DR² of `weights` on `moments`, with the shrinkage those moments applied."""
    return Dr2(
        value=dr2_from(weights, moments.sigma, moments.cov),
        shrinkage=moments.shrinkage,
    )


def dr2_from(weights, sigma, cov) -> float:
    """`(w'sigma)² / (w'Sigma w)` for `weights` held in the annual `sigma` and `cov`.

    The weights need not sum to 1 or be non-negative; the score is the same at any positive scale.
    Raises `UndefinedMeasure` when `w'Sigma w` is exactly zero (no weight, or only funds with zero
    variance), and `ValueError` for a non-finite or mis-shaped input, a negative `sigma`, or a
    negative `w'Sigma w` (a covariance that is not positive semidefinite).
    """
    w, s, c = _dr2_arrays(weights, sigma, cov)
    variance = float(w @ c @ w)
    if variance < 0.0:
        raise ValueError(
            f"portfolio variance {variance:.3g} is negative: cov is not positive semidefinite"
        )
    if variance == 0.0:
        raise UndefinedMeasure("portfolio variance is exactly zero: DR² is undefined")
    return float((w @ s) ** 2 / variance)


def es_25(annual_returns) -> float:
    """Mean of the lowest `ceil(0.025 P)` of `P` simulated annual returns.

    The tail is the `k` smallest values by value, so paths tied at the cut are interchangeable and
    path order cannot matter. The mean is taken about the tail's largest value, so that equal
    values average to themselves and the result never exceeds that value, hence never exceeds the
    linear-interpolation 2.5th percentile.
    """
    x = _annual_returns(annual_returns)
    k = math.ceil(TAIL_FRACTION * len(x))
    tail = np.partition(x, k - 1)[:k]
    cut = tail.max()
    return float(cut + math.fsum((tail - cut).tolist()) / k)


def _dr2_arrays(weights, sigma, cov) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    w = np.asarray(weights, dtype=float)
    if w.ndim != 1:
        raise ValueError(f"weights must be a 1-D array, got shape {w.shape}")
    if w.size == 0:
        raise ValueError("weights must hold at least one fund")
    s = np.asarray(sigma, dtype=float)
    if s.shape != w.shape:
        raise ValueError(f"sigma must have the shape of weights {w.shape}, got {s.shape}")
    c = np.asarray(cov, dtype=float)
    if c.shape != (len(w), len(w)):
        raise ValueError(f"cov must have shape {(len(w), len(w))}, got {c.shape}")
    for name, array in (("weights", w), ("sigma", s), ("cov", c)):
        if not np.isfinite(array).all():
            raise ValueError(f"{name} hold missing or non-finite values: they must be finite")
    if (s < 0.0).any():
        raise ValueError("sigma must be non-negative")
    return w, s, c


def _annual_returns(annual_returns) -> np.ndarray:
    x = np.asarray(annual_returns, dtype=float)
    if x.ndim != 1:
        raise ValueError(f"annual returns must be a 1-D array, got shape {x.shape}")
    if x.size == 0:
        raise ValueError("annual returns must hold at least one path")
    if not np.isfinite(x).all():
        raise ValueError("annual returns hold missing or non-finite values: they must be finite")
    return x
