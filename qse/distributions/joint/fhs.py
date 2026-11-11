"""Joint filtered historical simulation (FHS) over a fitted GARCH panel.

At each step of each path one ROW of the standardized-residual matrix is drawn, and that whole
row is the shock vector for all assets. Whatever dependence the assets' shocks had on a given
day (correlation, joint tails) is therefore carried into the simulation empirically; each
asset then runs its own GARCH(1,1) recursion on its column of shocks.

The seam for a later copula step is :data:`ShockSource`: a callable
``(n_paths, n_steps, rng) -> (n_paths, n_steps, n_assets)`` of standardized shocks. The
default is :func:`row_bootstrap_shock_source`; pass any other source to
:func:`simulate_fhs_panel` through ``shock_source`` and the recursion is unchanged.

Notes on what the simulation does and does not preserve:

- Rows are drawn independently across steps, so serial dependence of the shocks is removed on
  purpose; volatility clustering comes from the recursion.
- Dependence is that of the rows where ALL assets have a residual. A short overlap identifies
  joint tails poorly, and a pool selected by missingness may not be representative.
- The shocks are the empirical residuals, not Student-t draws: the fitted ``nu`` is not used.
- Simulated return correlations differ somewhat from shock correlations because returns also
  carry each asset's own stochastic volatility.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, cast

import numpy as np
from numpy.typing import ArrayLike, DTypeLike, NDArray

from qse.distributions.garch_recursion import StartState, simulate_garch11
from qse.distributions.joint.panel_fit import GarchPanelFit

FloatArray = NDArray[np.floating[Any]]
IntArray = NDArray[np.integer[Any]]
Seed = int | np.random.Generator | None

#: Replaceable source of standardized shocks: ``(n_paths, n_steps, rng)`` to an array of shape
#: ``(n_paths, n_steps, n_assets)`` with zero mean and unit variance per asset.
ShockSource = Callable[[int, int, np.random.Generator], FloatArray]

#: Fewest common residual rows accepted for resampling: the library's default minimum sample.
MIN_POOL_ROWS: int = 60

_CONSTANT_COLUMN_SPREAD: float = 1e-12

__all__ = [
    "MIN_POOL_ROWS",
    "ShockSource",
    "draw_row_indices",
    "residual_pool",
    "row_bootstrap_shock_source",
    "simulate_fhs_panel",
]


def _float_dtype(dtype: DTypeLike) -> np.dtype[Any]:
    resolved = np.dtype(dtype)
    if resolved not in (np.dtype(np.float64), np.dtype(np.float32)):
        raise ValueError("dtype must be float64 or float32")
    return resolved


def residual_pool(
    fit: GarchPanelFit,
    *,
    restandardize: bool = True,
    min_rows: int = MIN_POOL_ROWS,
    dtype: DTypeLike = np.float64,
) -> FloatArray:
    """Residual rows available for resampling, shape ``(n_pool_rows, n_assets)``.

    The pool is the rows of ``fit.std_residuals`` where every asset has a residual, in panel
    order. With ``restandardize`` (the default) each column is demeaned and scaled to unit
    variance over the pool rows, using the population standard deviation (``ddof=0``). The
    pool is the discrete distribution that gets sampled, so this makes the resampled shocks
    satisfy ``E[z] = 0`` and ``E[z^2] = 1`` exactly, and the simulated process then has
    unconditional mean ``mu`` and unconditional variance ``omega / (1 - alpha - beta)``.
    Without it, ``E[z^2] != 1`` changes the effective persistence and ``E[z] != 0`` shifts
    the mean.

    Each column is transformed by a positive affine map, which leaves rank correlations, the
    empirical copula and Pearson correlations of the shock rows unchanged.

    The drift of the simulation is the fitted location ``mu``, which for a Student-t fit is
    generally not the historical arithmetic mean.

    A zero-variance asset has a constant (zero) residual column, which stays at zero. A
    constant column for any other asset means the common rows carry no information about its
    shocks, and raises ``ValueError``; so does a pool of fewer than ``min_rows`` rows.
    """
    resolved = _float_dtype(dtype)
    pool = np.array(fit.std_residuals[fit.common_rows], dtype=np.float64)
    n_rows = pool.shape[0]
    if n_rows < max(min_rows, 1):
        raise ValueError(
            f"only {n_rows} rows have residuals for every asset; need at least {max(min_rows, 1)}"
        )

    # Standardized residuals are of order one, so a spread this small is rounding noise.
    constant = np.ptp(pool, axis=0) <= _CONSTANT_COLUMN_SPREAD
    degenerate = [
        asset
        for asset, is_constant, omega in zip(fit.assets, constant, fit.omega, strict=True)
        if is_constant and omega > 0.0
    ]
    if degenerate:
        raise ValueError(
            "residuals are constant over the common rows for non-constant assets: "
            + ", ".join(degenerate)
        )

    if restandardize:
        pool -= pool.mean(axis=0)
        pool /= np.where(constant, 1.0, pool.std(axis=0))
        pool[:, constant] = 0.0
    return cast(FloatArray, pool.astype(resolved, copy=False))


def draw_row_indices(n_pool_rows: int, n_paths: int, n_steps: int, seed: Seed = None) -> IntArray:
    """Draw pool row positions, uniform with replacement, shape ``(n_paths, n_steps)``.

    Values index the pool returned by :func:`residual_pool` (positions among the common rows),
    not rows of the original panel. Pass the result to :func:`simulate_fhs_panel` as
    ``row_indices`` to reuse one draw across calls.
    """
    if n_pool_rows <= 0 or n_paths <= 0 or n_steps <= 0:
        raise ValueError("n_pool_rows, n_paths and n_steps must be positive")
    rng = np.random.default_rng(seed)
    return cast(IntArray, rng.integers(0, n_pool_rows, size=(n_paths, n_steps)))


def row_bootstrap_shock_source(pool: FloatArray) -> ShockSource:
    """Default shock source: one common pool row per ``(path, step)``, uniform with replacement.

    This is the replaceable step. A copula-based source would return shocks of the same shape
    drawn from a fitted dependence model instead of from the historical rows.
    """

    def source(n_paths: int, n_steps: int, rng: np.random.Generator) -> FloatArray:
        return pool[draw_row_indices(pool.shape[0], n_paths, n_steps, rng)]

    return source


def _replay_shock_source(pool: FloatArray, row_indices: IntArray) -> ShockSource:
    """Shock source that replays a precomputed draw of pool row positions."""

    def source(n_paths: int, n_steps: int, rng: np.random.Generator) -> FloatArray:
        return pool[row_indices]

    return source


def _validated_indices(
    row_indices: ArrayLike, n_pool_rows: int, shape: tuple[int, int]
) -> IntArray:
    idx = np.asarray(row_indices)
    if not np.issubdtype(idx.dtype, np.integer):
        raise ValueError("row_indices must be an integer array")
    if idx.shape != shape:
        raise ValueError(f"row_indices must have shape {shape}, got {idx.shape}")
    if idx.size and (idx.min() < 0 or idx.max() >= n_pool_rows):
        raise ValueError(f"row_indices must lie in [0, {n_pool_rows})")
    return cast(IntArray, idx)


def simulate_fhs_panel(
    fit: GarchPanelFit,
    n_paths: int,
    n_steps: int,
    seed: Seed = None,
    start: StartState = "long_run",
    *,
    row_indices: ArrayLike | None = None,
    shock_source: ShockSource | None = None,
    restandardize: bool = True,
    min_pool_rows: int = MIN_POOL_ROWS,
    dtype: DTypeLike = np.float64,
) -> FloatArray:
    """Simulate joint daily returns, shape ``(n_paths, n_steps, n_assets)``.

    Parameters
    ----------
    fit
        Result of :func:`~qse.distributions.joint.panel_fit.fit_garch_t_panel`.
    n_paths, n_steps
        Number of paths and of daily steps per path.
    seed
        Integer seed or a ``numpy.random.Generator``. A local generator is used; numpy's
        global random state is never read or written.
    start
        ``"long_run"`` starts every asset at its unconditional variance. This reproduces the
        long-run mean and variance from the first step, though not the full stationary
        distribution of the variance. ``"last"`` starts at the one-step-ahead forecast
        ``omega + alpha * eps_T^2 + beta * sigma2_T`` following the last observed return, and
        requires every asset to be observed on the panel's final row.
    row_indices
        Optional precomputed integer matrix ``(n_paths, n_steps)`` of pool row positions (see
        :func:`draw_row_indices`); when given, ``seed`` is not used.
    shock_source
        Optional replacement for the row bootstrap (the copula seam). It must return
        standardized shocks of shape ``(n_paths, n_steps, n_assets)``. Mutually exclusive
        with ``row_indices``.
    restandardize, min_pool_rows
        Passed to :func:`residual_pool` for the default shock source.
    dtype
        ``float64`` (default) or ``float32``. The output is the only array of size
        ``paths x steps x assets`` that is allocated: 8 bytes per element in float64
        (2,000 x 252 x 30 is about 121 MB), half that in float32.

    The returned moments are those of the model in expectation, not exactly in any one
    simulated batch. Finite variance (``alpha + beta < 1``) does not imply finite kurtosis,
    which needs ``E[(alpha * z^2 + beta)^2] < 1``.
    """
    if n_paths <= 0 or n_steps <= 0:
        raise ValueError("n_paths and n_steps must be positive")
    resolved = _float_dtype(dtype)
    sigma2_init = fit.start_variance(start)
    shape = (n_paths, n_steps, fit.n_assets)

    if shock_source is not None and row_indices is not None:
        raise ValueError("pass either row_indices or shock_source, not both")

    source: ShockSource
    if shock_source is not None:
        source = shock_source
    else:
        pool = residual_pool(
            fit, restandardize=restandardize, min_rows=min_pool_rows, dtype=resolved
        )
        if row_indices is None:
            source = row_bootstrap_shock_source(pool)
        else:
            source = _replay_shock_source(
                pool, _validated_indices(row_indices, pool.shape[0], (n_paths, n_steps))
            )

    shocks = np.asarray(source(n_paths, n_steps, np.random.default_rng(seed)), dtype=resolved)
    if shocks.shape != shape:
        raise ValueError(f"shock source returned shape {shocks.shape}, expected {shape}")
    # The built-in sources gather a fresh array, so the recursion may overwrite it in place.
    # A caller-supplied source may hand back an array it still owns, so that one is not reused.
    out = shocks if shock_source is None else None

    return simulate_garch11(
        shocks,
        mu=fit.mu,
        omega=fit.omega,
        alpha=fit.alpha,
        beta=fit.beta,
        sigma2_init=sigma2_init,
        out=out,
    )
