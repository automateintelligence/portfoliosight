"""Per-asset GARCH(1,1)-t fits over a panel of returns with unequal histories.

Each asset is fitted on its own available history with the existing
:class:`~qse.distributions.fitters.garch_t_fitter.GarchTFitter`. The result holds per-asset
parameters in the ORIGINAL return units, conditional volatilities and standardized residuals
aligned on the panel's row index, and a per-asset status. It is the input to
:func:`qse.distributions.joint.fhs.simulate_fhs_panel`.

Inputs are daily returns as decimal fractions (0.01 = 1%), one column per asset, rows on a
common date index, NaN where an asset has no observation. Per ADR-004 they must come from
adjusted prices.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, cast

import numpy as np
import pandas as pd
from numpy.typing import ArrayLike, NDArray

from qse.distributions.fitters.garch_t_fitter import GarchTFitter
from qse.distributions.garch_recursion import (
    StartState,
    garch11_long_run_variance,
    garch11_next_variance,
)
from qse.distributions.validation.stationarity import MIN_SAMPLES
from qse.exceptions import DistributionFitError

FloatArray = NDArray[np.float64]
IntArray = NDArray[np.int64]
BoolArray = NDArray[np.bool_]

PanelStatus = Literal[
    "garch",
    "near_constant",
    "fit_failed",
    "non_stationary",
    "insufficient_history",
]

#: Minimum observations for a GARCH fit: the existing convention for ``garch_t`` (one trading year).
MIN_GARCH_HISTORY: int = MIN_SAMPLES["garch_t"]

#: Daily return standard deviation below which a series is treated as constant-volatility.
#: 3e-4 per day is about 0.5% annualized: stable-value and T-bill funds fall under it, short-term
#: bond funds do not. It is an absolute threshold and assumes decimal-fraction returns.
NEAR_CONSTANT_DAILY_VOL: float = 3e-4

#: A fit with ``alpha + beta >= 1 - PERSISTENCE_TOL`` is treated as non-stationary.
PERSISTENCE_TOL: float = 1e-4

#: Daily standard deviation at or below which a series counts as exactly constant. Returns
#: computed from prices carry rounding noise of about 1e-16, so a constant series rarely has a
#: sample variance of exactly zero; anything this small is that noise, not volatility.
ZERO_VOL_FLOOR: float = 1e-12

__all__ = [
    "MIN_GARCH_HISTORY",
    "NEAR_CONSTANT_DAILY_VOL",
    "PERSISTENCE_TOL",
    "ZERO_VOL_FLOOR",
    "GarchPanelFit",
    "PanelStatus",
    "fit_garch_t_panel",
]


@dataclass(frozen=True)
class GarchPanelFit:
    """Per-asset GARCH(1,1)-t fits for a panel of ``n_assets`` columns and ``n_rows`` dates.

    Constant-volatility fallback assets are stored as ``alpha = beta = 0`` with ``omega`` equal
    to the sample variance and ``nu = NaN``, so every asset obeys the same recursion.

    Attributes
    ----------
    assets
        Column labels as strings.
    index
        Row index of the input panel (dates for a DataFrame, a RangeIndex for an array).
    mu, omega, alpha, beta, nu
        Parameters in the original return units, shape ``(n_assets,)``.
    conditional_volatility
        ``sigma_t`` in original return units, shape ``(n_rows, n_assets)``, NaN where the asset
        has no observation.
    std_residuals
        ``z_t = (r_t - mu) / sigma_t``, same shape and NaN pattern. A zero-variance asset has
        zeros on its observed rows.
    status
        One of ``garch``, ``near_constant``, ``fit_failed``, ``non_stationary``,
        ``insufficient_history`` per asset; everything except ``garch`` is the
        constant-volatility fallback.
    messages
        Human-readable reason or fitter warnings per asset (empty string when there is none).
    n_obs
        Number of observations used per asset.
    last_row
        Row position of each asset's final observation.
    last_resid, last_sigma2
        Final in-sample residual ``eps_T`` and conditional variance ``sigma2_T`` per asset.
    """

    assets: tuple[str, ...]
    index: pd.Index
    mu: FloatArray
    omega: FloatArray
    alpha: FloatArray
    beta: FloatArray
    nu: FloatArray
    conditional_volatility: FloatArray
    std_residuals: FloatArray
    status: tuple[PanelStatus, ...]
    messages: tuple[str, ...]
    n_obs: IntArray
    last_row: IntArray
    last_resid: FloatArray
    last_sigma2: FloatArray

    @property
    def n_assets(self) -> int:
        return len(self.assets)

    @property
    def is_garch(self) -> BoolArray:
        """True for assets simulated with their fitted GARCH, False for the fallback."""
        return np.array([s == "garch" for s in self.status], dtype=np.bool_)

    @property
    def long_run_variance(self) -> FloatArray:
        """Unconditional variance per asset (the sample variance for fallback assets)."""
        return cast(FloatArray, garch11_long_run_variance(self.omega, self.alpha, self.beta))

    @property
    def next_variance(self) -> FloatArray:
        """One-step-ahead variance per asset following its own final observation."""
        return cast(
            FloatArray,
            garch11_next_variance(
                self.omega, self.alpha, self.beta, self.last_resid, self.last_sigma2
            ),
        )

    @property
    def common_rows(self) -> BoolArray:
        """Mask of rows where every asset has a standardized residual."""
        return cast(BoolArray, np.isfinite(self.std_residuals).all(axis=1))

    @property
    def n_common_rows(self) -> int:
        """Number of rows available for joint resampling."""
        return int(self.common_rows.sum())

    def start_variance(self, start: StartState) -> FloatArray:
        """Conditional variance of the first simulated step for the chosen start state.

        ``"long_run"`` is the unconditional variance. ``"last"`` is the one-step-ahead forecast
        following the last observed return, and requires every asset's final observation to
        sit on the panel's final row so that all assets share one forecast origin.
        """
        if start == "long_run":
            return self.long_run_variance
        if start == "last":
            final_row = self.std_residuals.shape[0] - 1
            stale = [
                a for a, row in zip(self.assets, self.last_row, strict=True) if row != final_row
            ]
            if stale:
                raise ValueError(
                    "start='last' needs every asset observed on the final row; stale assets: "
                    + ", ".join(stale)
                )
            return self.next_variance
        raise ValueError("start must be 'long_run' or 'last'")

    def params_frame(self) -> pd.DataFrame:
        """Per-asset parameters, status and long-run daily volatility as a DataFrame."""
        return pd.DataFrame(
            {
                "mu": self.mu,
                "omega": self.omega,
                "alpha": self.alpha,
                "beta": self.beta,
                "nu": self.nu,
                "long_run_vol": np.sqrt(self.long_run_variance),
                "n_obs": self.n_obs,
                "status": list(self.status),
                "message": list(self.messages),
            },
            index=pd.Index(self.assets, name="asset"),
        )


@dataclass(frozen=True)
class _AssetFit:
    mu: float
    omega: float
    alpha: float
    beta: float
    nu: float
    sigma: FloatArray
    z: FloatArray
    status: PanelStatus
    message: str


def _constant_vol_fit(x: FloatArray, status: PanelStatus, message: str) -> _AssetFit:
    """Constant-volatility fallback: sample mean and variance, residuals over the sample std."""
    mean = float(x.mean())
    variance = float(x.var(ddof=1))
    std = float(np.sqrt(variance))
    if std <= ZERO_VOL_FLOOR:
        variance = std = 0.0
    z = (x - mean) / std if std > 0.0 else np.zeros_like(x)
    return _AssetFit(
        mu=mean,
        omega=variance,
        alpha=0.0,
        beta=0.0,
        nu=float("nan"),
        sigma=np.full_like(x, std),
        z=z,
        status=status,
        message=message,
    )


def _fit_asset(
    x: FloatArray, *, min_history: int, near_constant_vol: float, persistence_tol: float
) -> _AssetFit:
    n = x.size
    if n < min_history:
        return _constant_vol_fit(
            x, "insufficient_history", f"{n} observations < min_history={min_history}"
        )
    std = float(x.std(ddof=1))
    if std < near_constant_vol:
        return _constant_vol_fit(
            x, "near_constant", f"daily std {std:.3e} < near_constant_vol={near_constant_vol:.3e}"
        )

    fitter = GarchTFitter()
    try:
        result = fitter.fit(x)
    except DistributionFitError as exc:
        return _constant_vol_fit(x, "fit_failed", str(exc))

    params = fitter.original_scale_params()
    sigma = fitter.conditional_volatility()
    z = fitter.standardized_residuals()
    mu, omega, alpha, beta, nu = (params[k] for k in ("mu", "omega", "alpha", "beta", "nu"))

    problems: list[str] = []
    if not fitter.optimizer_converged():
        problems.append("optimizer did not converge")
    if not all(np.isfinite(v) for v in (mu, omega, alpha, beta, nu)):
        problems.append("non-finite parameters")
    elif omega <= 0.0 or alpha < 0.0 or beta < 0.0 or nu <= 2.0:
        problems.append(
            f"invalid parameters omega={omega:.3e} alpha={alpha:.4f} beta={beta:.4f} nu={nu:.2f}"
        )
    if not (np.all(np.isfinite(sigma)) and np.all(sigma > 0.0) and np.all(np.isfinite(z))):
        problems.append("non-finite or non-positive conditional volatility")
    if problems:
        return _constant_vol_fit(x, "fit_failed", "; ".join(problems))

    persistence = alpha + beta
    if persistence >= 1.0 - persistence_tol:
        return _constant_vol_fit(
            x,
            "non_stationary",
            f"alpha+beta={persistence:.6f} >= 1 - {persistence_tol:g}: unconditional variance undefined",
        )

    return _AssetFit(
        mu=mu,
        omega=omega,
        alpha=alpha,
        beta=beta,
        nu=nu,
        sigma=sigma,
        z=z,
        status="garch",
        message="; ".join(result.warnings),
    )


def fit_garch_t_panel(
    returns: pd.DataFrame | ArrayLike,
    *,
    min_history: int = MIN_GARCH_HISTORY,
    near_constant_vol: float = NEAR_CONSTANT_DAILY_VOL,
    persistence_tol: float = PERSISTENCE_TOL,
) -> GarchPanelFit:
    """Fit GARCH(1,1)-t per asset on a ``(n_rows, n_assets)`` panel of daily returns.

    Each column is fitted on its own non-NaN observations, taken in row order (interior gaps
    are closed up, so the recursion treats the observations either side of a gap as
    consecutive). Parameters are returned in the units of the input returns regardless of the
    rescaling ``arch`` applies internally.

    An asset falls back to constant volatility (sample mean and variance, residuals
    standardized by the sample standard deviation; zero variance and zero residuals when the
    sample standard deviation is at or below ``ZERO_VOL_FLOOR``) and is flagged in ``status``
    when:

    - ``insufficient_history``: fewer than ``min_history`` observations;
    - ``near_constant``: sample daily standard deviation below ``near_constant_vol``;
    - ``fit_failed``: the fitter raised, the optimizer did not converge, or the parameters
      are invalid;
    - ``non_stationary``: ``alpha + beta >= 1 - persistence_tol``, where the unconditional
      variance does not exist.

    Parameters
    ----------
    returns
        DataFrame (columns are assets, index is the date index) or 2-D array, decimal-fraction
        daily returns, NaN where an asset has no observation.
    min_history
        Minimum observations for a GARCH fit. Defaults to, and may not be lower than, the
        existing ``garch_t`` minimum of 252, which the fitter itself enforces.
    near_constant_vol
        Absolute daily-volatility threshold for the near-constant fallback.
    persistence_tol
        Margin below 1 at which ``alpha + beta`` counts as non-stationary.

    Raises
    ------
    ValueError
        For a non-2-D panel, infinite values, or ``min_history`` below the fitter minimum.
    DistributionFitError
        When an asset has fewer than two observations, so not even a variance is defined.
    """
    if min_history < MIN_GARCH_HISTORY:
        raise ValueError(
            f"min_history={min_history} is below the garch_t minimum of {MIN_GARCH_HISTORY} "
            "that the fitter enforces"
        )

    if isinstance(returns, pd.DataFrame):
        assets = tuple(str(c) for c in returns.columns)
        index = returns.index
        values = returns.to_numpy(dtype=np.float64)
    else:
        values = np.asarray(returns, dtype=np.float64)
        if values.ndim != 2:
            raise ValueError("returns must be a 2-D (n_rows, n_assets) panel")
        assets = tuple(f"asset_{j}" for j in range(values.shape[1]))
        index = pd.RangeIndex(values.shape[0])
    if values.shape[1] == 0:
        raise ValueError("returns has no asset columns")
    if np.isinf(values).any():
        raise ValueError("returns contains infinite values")

    n_rows, n_assets = values.shape
    sigma_panel = np.full((n_rows, n_assets), np.nan, dtype=np.float64)
    z_panel = np.full((n_rows, n_assets), np.nan, dtype=np.float64)
    params = np.empty((5, n_assets), dtype=np.float64)
    n_obs = np.empty(n_assets, dtype=np.int64)
    last_row = np.empty(n_assets, dtype=np.int64)
    last_resid = np.empty(n_assets, dtype=np.float64)
    last_sigma2 = np.empty(n_assets, dtype=np.float64)
    status: list[PanelStatus] = []
    messages: list[str] = []

    for j, asset in enumerate(assets):
        rows = np.flatnonzero(np.isfinite(values[:, j]))
        if rows.size < 2:
            raise DistributionFitError(
                f"asset {asset} has {rows.size} observations; at least 2 are needed"
            )
        x = np.ascontiguousarray(values[rows, j])
        fit = _fit_asset(
            x,
            min_history=min_history,
            near_constant_vol=near_constant_vol,
            persistence_tol=persistence_tol,
        )
        params[:, j] = (fit.mu, fit.omega, fit.alpha, fit.beta, fit.nu)
        sigma_panel[rows, j] = fit.sigma
        z_panel[rows, j] = fit.z
        n_obs[j] = rows.size
        last_row[j] = rows[-1]
        last_resid[j] = x[-1] - fit.mu
        last_sigma2[j] = fit.sigma[-1] ** 2
        status.append(fit.status)
        messages.append(fit.message)

    return GarchPanelFit(
        assets=assets,
        index=index,
        mu=params[0].copy(),
        omega=params[1].copy(),
        alpha=params[2].copy(),
        beta=params[3].copy(),
        nu=params[4].copy(),
        conditional_volatility=sigma_panel,
        std_residuals=z_panel,
        status=tuple(status),
        messages=tuple(messages),
        n_obs=n_obs,
        last_row=last_row,
        last_resid=last_resid,
        last_sigma2=last_sigma2,
    )
