"""Portfolio aggregation of simulated asset returns.

Generic helpers over simulated daily SIMPLE returns of shape ``(n_paths, n_steps, n_assets)``:
constant-mix portfolios (rebalanced to fixed weights every step) and compounding to a horizon
return. Simple returns are required because a portfolio's return is the weighted sum of its
assets' simple returns; that identity does not hold for log returns.
"""

from __future__ import annotations

from typing import Any, Literal, cast

import numpy as np
from numpy.typing import ArrayLike, NDArray

FloatArray = NDArray[np.floating[Any]]
RuinPolicy = Literal["raise", "absorb"]

#: Default cap on the per-chunk ``(paths, steps, mixes)`` work buffer, in bytes.
DEFAULT_CHUNK_BYTES: int = 32 * 1024 * 1024

# A spread at or below this multiple of the largest magnitude is floating-point rounding.
_CONSTANT_RELATIVE_SPREAD: float = 64.0 * float(np.finfo(np.float64).eps)

__all__ = [
    "DEFAULT_CHUNK_BYTES",
    "RuinPolicy",
    "compound_horizon_returns",
    "constant_mix_daily_returns",
    "constant_mix_horizon_returns",
    "rescale_to_targets",
    "rescaled_horizon_returns",
]


def _growth(gross: FloatArray, ruin: RuinPolicy) -> FloatArray:
    """Product of gross returns ``1 + r`` along axis 1, accumulated in float64.

    ``gross`` may be modified in place. Non-finite input is rejected: NaN and ``-inf`` show up
    in the minimum, which is checked before any clipping, and ``+inf`` makes the product
    non-finite. The product check also catches overflow of the accumulation itself.
    """
    if ruin not in ("raise", "absorb"):
        raise ValueError("ruin must be 'raise' or 'absorb'")
    lowest = float(gross.min()) if gross.size else 0.0
    if not np.isfinite(lowest):
        raise ValueError("returns must be finite; found NaN or infinity")
    if lowest < 0.0:
        if ruin == "raise":
            raise ValueError(
                "a daily return below -100% was found; pass ruin='absorb' to treat it as total loss"
            )
        np.maximum(gross, 0.0, out=gross)
    with np.errstate(invalid="ignore", over="ignore"):  # reported below as an error instead
        growth = np.multiply.reduce(gross, axis=1, dtype=np.float64)
    if not np.isfinite(growth).all():
        raise ValueError("compounded return is not finite; check the returns for NaN or infinity")
    return cast(FloatArray, growth)


def compound_horizon_returns(daily_returns: ArrayLike, *, ruin: RuinPolicy = "raise") -> FloatArray:
    """Compound daily simple returns ``(n_paths, n_steps)`` to horizon returns ``(n_paths,)``.

    Returns ``prod_t(1 + r_t) - 1`` per path. A daily return of exactly -100% is total loss
    and stays there. A daily return below -100% has no meaning for a compounding wealth
    process: by default it raises; ``ruin="absorb"`` floors the gross return at zero (total
    loss, absorbing), which is a limited-liability convention that changes the distribution.
    """
    r = np.asarray(daily_returns, dtype=np.float64)
    if r.ndim != 2:
        raise ValueError("daily_returns must have shape (n_paths, n_steps)")
    return _growth(1.0 + r, ruin) - 1.0


def _validated_panel(asset_returns: ArrayLike) -> FloatArray:
    r = np.asarray(asset_returns)
    if r.dtype != np.float32:
        r = np.asarray(r, dtype=np.float64)
    if r.ndim != 3:
        raise ValueError("asset_returns must have shape (n_paths, n_steps, n_assets)")
    return cast(FloatArray, r)


def constant_mix_daily_returns(asset_returns: ArrayLike, weights: ArrayLike) -> FloatArray:
    """Daily returns ``(n_paths, n_steps)`` of ONE constant-mix portfolio.

    ``weights`` has shape ``(n_assets,)``. The portfolio is rebalanced to these weights at
    every step, so its daily return is ``sum_n w_n r_n``. Weights need not sum to one; any
    remainder earns zero.
    """
    r = _validated_panel(asset_returns)
    w = np.asarray(weights, dtype=r.dtype)
    if w.shape != (r.shape[2],):
        raise ValueError(f"weights must have shape ({r.shape[2]},), got {w.shape}")
    return cast(FloatArray, r @ w)


def constant_mix_horizon_returns(
    asset_returns: ArrayLike,
    weights: ArrayLike,
    *,
    ruin: RuinPolicy = "raise",
    max_chunk_bytes: int = DEFAULT_CHUNK_BYTES,
) -> FloatArray:
    """Compounded horizon returns ``(n_mixes, n_paths)`` for constant-mix portfolios.

    Parameters
    ----------
    asset_returns
        Simulated daily simple returns, shape ``(n_paths, n_steps, n_assets)``.
    weights
        Weight matrix ``(n_mixes, n_assets)``, one portfolio per row, held constant by
        rebalancing at every step. Rows need not sum to one; any remainder earns zero.
    ruin
        What to do with a portfolio daily return below -100%; see
        :func:`compound_horizon_returns`.
    max_chunk_bytes
        Cap on the ``(chunk_paths, n_steps, n_mixes)`` work buffer, which is allocated once and
        reused. Paths are processed in chunks sized to stay under it, so working memory does
        not grow with ``n_paths``; a single path's ``n_steps x n_mixes`` block is the floor.

    Returns
    -------
    ``prod_t(1 + sum_n w[m, n] * r[p, t, n]) - 1`` as a float64 array ``(n_mixes, n_paths)``.
    """
    r = _validated_panel(asset_returns)
    n_paths, n_steps, n_assets = r.shape
    w = np.asarray(weights, dtype=r.dtype)
    if w.ndim != 2 or w.shape[1] != n_assets:
        raise ValueError(f"weights must have shape (n_mixes, {n_assets}), got {w.shape}")
    if w.shape[0] == 0 or n_paths == 0 or n_steps == 0:
        raise ValueError("asset_returns and weights must be non-empty")
    if not np.isfinite(w).all():
        raise ValueError("weights must be finite")
    n_mixes = w.shape[0]
    w_t = np.ascontiguousarray(w.T)

    # The gross-return buffer is float64 whatever the panel's dtype: adding 1.0 in float32 would
    # round away daily returns below about 6e-8 before compounding.
    bytes_per_path = max(n_steps * n_mixes * np.dtype(np.float64).itemsize, 1)
    chunk_paths = min(n_paths, max(1, int(max_chunk_bytes) // bytes_per_path))

    out = np.empty((n_mixes, n_paths), dtype=np.float64)
    work = np.empty((chunk_paths * n_steps, n_mixes), dtype=np.float64)
    for lo in range(0, n_paths, chunk_paths):
        hi = min(lo + chunk_paths, n_paths)
        gross = work[: (hi - lo) * n_steps]
        np.matmul(r[lo:hi].reshape((hi - lo) * n_steps, n_assets), w_t, out=gross)
        gross += 1.0
        out[:, lo:hi] = _growth(gross.reshape(hi - lo, n_steps, n_mixes), ruin).T
    out -= 1.0
    return out


def rescale_to_targets(
    daily_returns: ArrayLike, target_mean: float, target_vol: float
) -> FloatArray:
    """Affinely rescale ONE portfolio's daily returns to a target daily mean and volatility.

    Applies ``y = target_mean + (x - mean(x)) * (target_vol / std(x))``, where the mean and the
    population standard deviation (``ddof=0``) are pooled over all paths and steps. The pooled
    arithmetic daily mean and volatility of the result equal the targets; individual paths
    keep their own differing moments. A positive affine map leaves the standardized shape of
    the distribution (skew, kurtosis, relative volatility clustering) unchanged.

    The targets are DAILY arithmetic moments; converting an annual expected return and risk to
    daily figures is the caller's choice. Because the two constants are estimated from the
    same simulated batch, the expected compounded return is close to, not exactly,
    ``(1 + target_mean)**n_steps - 1``.

    Raises ``ValueError`` when the input has zero dispersion (it is constant, up to
    floating-point rounding) and ``target_vol`` is positive, since no affine map can create
    volatility.
    """
    x = np.asarray(daily_returns, dtype=np.float64)
    if x.ndim != 2:
        raise ValueError("daily_returns must have shape (n_paths, n_steps)")
    if x.size == 0:
        raise ValueError("daily_returns must be non-empty")
    if not np.isfinite(x).all():
        raise ValueError("daily_returns must be finite")
    if not (np.isfinite(target_mean) and np.isfinite(target_vol)) or target_vol < 0.0:
        raise ValueError("target_mean must be finite and target_vol finite and non-negative")

    # Constancy is tested on the spread, not on the computed standard deviation: the mean of a
    # constant array is generally off by a rounding error, which gives a tiny positive std.
    magnitude = float(np.abs(x).max())
    if float(np.ptp(x)) <= _CONSTANT_RELATIVE_SPREAD * magnitude:
        if target_vol > 0.0:
            raise ValueError(
                "daily_returns has zero dispersion; cannot rescale to a positive target_vol"
            )
        return np.full_like(x, target_mean)
    return cast(FloatArray, target_mean + (x - float(x.mean())) * (target_vol / float(x.std())))


def rescaled_horizon_returns(
    daily_returns: ArrayLike,
    target_mean: float,
    target_vol: float,
    *,
    ruin: RuinPolicy = "raise",
) -> FloatArray:
    """Rescale one portfolio's daily returns to the targets, then compound to ``(n_paths,)``.

    Equivalent to :func:`compound_horizon_returns` of :func:`rescale_to_targets`.
    """
    return compound_horizon_returns(
        rescale_to_targets(daily_returns, target_mean, target_vol), ruin=ruin
    )
