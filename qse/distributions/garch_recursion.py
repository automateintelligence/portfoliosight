"""Vectorized GARCH(1,1) recursion in pure numpy.

Model, per series::

    r_t      = mu + eps_t,            eps_t = sigma_t * z_t
    sigma2_t = omega + alpha * eps_{t-1}^2 + beta * sigma2_{t-1}

``z_t`` are standardized shocks (zero mean, unit variance). The recursion is vectorized
across paths, and across assets when the shock array carries a trailing asset axis; the
only Python loop is over time steps. Nothing here touches numpy's global random state.

A constant-volatility series is the special case ``alpha = beta = 0`` with ``omega`` equal
to its variance, so a mixed panel runs through the same recursion without branching.
"""

from __future__ import annotations

from typing import Any, Literal, cast

import numpy as np
from numpy.typing import ArrayLike, DTypeLike, NDArray

FloatArray = NDArray[np.floating[Any]]
StartState = Literal["long_run", "last"]

__all__ = [
    "StartState",
    "garch11_long_run_variance",
    "garch11_next_variance",
    "simulate_garch11",
    "standardized_t_shocks",
]


def garch11_long_run_variance(omega: ArrayLike, alpha: ArrayLike, beta: ArrayLike) -> FloatArray:
    """Unconditional variance ``omega / (1 - alpha - beta)``.

    Returns NaN where ``alpha + beta >= 1``: the unconditional variance does not exist there.
    """
    omega_arr = np.asarray(omega, dtype=np.float64)
    persistence = np.asarray(alpha, dtype=np.float64) + np.asarray(beta, dtype=np.float64)
    stationary = persistence < 1.0
    denom = np.where(stationary, 1.0 - persistence, 1.0)
    return cast(FloatArray, np.where(stationary, omega_arr / denom, np.nan))


def garch11_next_variance(
    omega: ArrayLike,
    alpha: ArrayLike,
    beta: ArrayLike,
    last_resid: ArrayLike,
    last_sigma2: ArrayLike,
) -> FloatArray:
    """One-step-ahead variance ``omega + alpha * eps_T^2 + beta * sigma2_T``.

    ``last_resid`` is the final in-sample residual ``eps_T = r_T - mu`` and ``last_sigma2`` the
    final in-sample conditional variance. The result is the conditional variance of the first
    out-of-sample step, which is what a simulation continuing the fitted series starts from.
    """
    eps = np.asarray(last_resid, dtype=np.float64)
    return cast(
        FloatArray,
        np.asarray(omega, dtype=np.float64)
        + np.asarray(alpha, dtype=np.float64) * (eps * eps)
        + np.asarray(beta, dtype=np.float64) * np.asarray(last_sigma2, dtype=np.float64),
    )


def standardized_t_shocks(
    rng: np.random.Generator,
    df: ArrayLike,
    size: tuple[int, ...],
    dtype: DTypeLike = np.float64,
) -> FloatArray:
    """Student-t draws rescaled to unit variance: ``t_nu * sqrt((nu - 2) / nu)``.

    ``df`` broadcasts against ``size`` (a scalar, or one value per asset on the last axis).
    Requires ``nu > 2``; the variance of a Student-t is undefined otherwise.
    """
    nu = np.asarray(df, dtype=np.float64)
    if not np.all(np.isfinite(nu)) or np.any(nu <= 2.0):
        raise ValueError(
            "Student-t degrees of freedom must be finite and > 2 for unit-variance shocks"
        )
    draws = rng.standard_t(nu, size=size) * np.sqrt((nu - 2.0) / nu)
    return cast(FloatArray, draws.astype(dtype, copy=False))


def _as_param(
    name: str, value: ArrayLike, dtype: np.dtype[Any], *, non_negative: bool
) -> FloatArray:
    arr = np.asarray(value, dtype=dtype)
    if not np.all(np.isfinite(arr)):
        raise ValueError(f"{name} must be finite")
    if non_negative and np.any(arr < 0):
        raise ValueError(f"{name} must be non-negative")
    return cast(FloatArray, arr)


def _same_layout(a: FloatArray, b: FloatArray) -> bool:
    """True when two arrays address exactly the same elements in the same order."""
    return (
        a.shape == b.shape
        and a.strides == b.strides
        and a.__array_interface__["data"][0] == b.__array_interface__["data"][0]
    )


def _addresses_distinct(a: FloatArray) -> bool:
    """True when the strides are nested, so that no two indices address the same memory.

    Sufficient, not necessary: it holds for every ordinary array, slice and transpose, and
    fails for broadcast (zero-stride) and sliding-window layouts, whose elements overlap.
    """
    span = a.itemsize
    for stride, length in sorted((abs(s), n) for s, n in zip(a.strides, a.shape, strict=True)):
        if length > 1:
            if stride < span:
                return False
            span += stride * (length - 1)
    return True


def simulate_garch11(
    shocks: ArrayLike,
    *,
    mu: ArrayLike,
    omega: ArrayLike,
    alpha: ArrayLike,
    beta: ArrayLike,
    sigma2_init: ArrayLike,
    out: FloatArray | None = None,
) -> FloatArray:
    """Run the GARCH(1,1) recursion over a shock array and return simulated returns.

    Parameters
    ----------
    shocks
        Standardized shocks of shape ``(n_paths, n_steps)`` or ``(n_paths, n_steps, n_assets)``.
        A float32 array yields float32 output; anything else is computed in float64.
    mu, omega, alpha, beta
        Scalars, or arrays that broadcast against one time slice of ``shocks`` (shape
        ``(n_paths,)`` or ``(n_paths, n_assets)``); pass ``(n_assets,)`` arrays for a panel.
    sigma2_init
        Conditional variance of the FIRST simulated step, same broadcasting rule. Use
        :func:`garch11_long_run_variance` to start at the unconditional variance, or
        :func:`garch11_next_variance` to continue a fitted series.
    out
        Optional array of the same shape and dtype as ``shocks`` that receives the returns.
        Passing the shock array itself overwrites it in place and avoids a second
        ``paths x steps x assets`` allocation. Any other array that shares memory with the
        shocks is rejected.

    Returns
    -------
    Simulated returns with the shape of ``shocks``.
    """
    z = np.asarray(shocks)
    if z.dtype != np.float32:
        z = np.asarray(z, dtype=np.float64)
    if z.ndim not in (2, 3):
        raise ValueError(
            "shocks must have shape (n_paths, n_steps) or (n_paths, n_steps, n_assets)"
        )
    dtype = z.dtype
    n_steps = z.shape[1]
    state_shape = (z.shape[0],) + z.shape[2:]

    mu_arr = _as_param("mu", mu, dtype, non_negative=False)
    omega_arr = _as_param("omega", omega, dtype, non_negative=True)
    alpha_arr = _as_param("alpha", alpha, dtype, non_negative=True)
    beta_arr = _as_param("beta", beta, dtype, non_negative=True)
    sigma2 = np.broadcast_to(
        _as_param("sigma2_init", sigma2_init, dtype, non_negative=True), state_shape
    ).copy()

    if out is None:
        out = np.empty(z.shape, dtype=dtype)
    elif out.shape != z.shape or out.dtype != dtype:
        raise ValueError("out must have the same shape and dtype as shocks")
    elif not _addresses_distinct(out):
        raise ValueError("out must not have overlapping elements (for example a broadcast view)")
    elif not _same_layout(out, z) and np.shares_memory(out, z):
        # Step t is written before later shocks are read, so a partial overlap (for example a
        # reversed view) would overwrite shocks that are still needed.
        raise ValueError("out overlaps shocks; pass the shock array itself or a separate array")

    for t in range(n_steps):
        eps = np.sqrt(sigma2) * z[:, t]
        out[:, t] = mu_arr + eps
        sigma2 = omega_arr + alpha_arr * (eps * eps) + beta_arr * sigma2
    return out
