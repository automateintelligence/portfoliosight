"""GARCH-T fitter placeholder with explicit failure messaging."""

from __future__ import annotations

from typing import Any

import numpy as np
from numpy.typing import NDArray

from qse.distributions.models import FitResult
from qse.distributions.validation.stationarity import ensure_min_samples
from qse.exceptions import DistributionFitError

FloatArray = NDArray[np.float64]


class GarchTFitter:
    name = "garch_t"
    k = 4  # omega, alpha, beta, nu (rough estimate for criteria)

    def __init__(self) -> None:
        self._fit_params: dict[str, float] | None = None
        self._scale_factor: float | None = None  # Store scale factor for rescaling samples
        self._fit_result: Any = None  # Store arch model result for simulation

    def fit(self, returns: FloatArray) -> FitResult:
        returns_arr = np.asarray(returns, dtype=np.float64)
        ensure_min_samples(returns_arr, self.name)
        try:
            from arch import arch_model
        except Exception as exc:  # pragma: no cover - dependency guard
            raise DistributionFitError(f"GARCH-T requires 'arch' package: {exc}") from exc

        try:
            # Build model WITH rescaling for numerical stability
            # rescale=True prevents false convergence due to tiny parameter values
            am = arch_model(
                returns_arr,
                mean="Constant",  # Estimate mean parameter
                vol="GARCH",
                p=1,
                o=0,
                q=1,
                dist="t",
                rescale=True,  # CRITICAL: Enables proper optimization
            )

            # Fit with robust optimization settings
            # Let arch auto-initialize starting values (works better with rescaling)
            res = am.fit(
                update_freq=0,
                disp="off",
                show_warning=False,
                options={
                    "maxiter": 1000,  # More iterations for convergence
                    "ftol": 1e-10,    # Tight tolerance
                },
            )

            # Extract parameters (in rescaled units) and scale factor
            params = {k: float(v) for k, v in res.params.items()}
            loglik = float(res.loglikelihood)

            # Store scale factor for converting samples back to original scale
            self._scale_factor = float(res.scale)

            # Check convergence
            converged_attr = getattr(res, "converged", None)
            converged = bool(converged_attr) if converged_attr is not None else bool(getattr(res, "convergence", 0) == 0)

            # Validate fitted parameters (detect degenerate solutions)
            # Note: Parameters are in rescaled units
            warnings: list[str] = []
            omega = params.get("omega", 0.0)
            alpha1 = params.get("alpha[1]", 0.0)
            beta1 = params.get("beta[1]", 0.0)
            nu = params.get("nu", 5.0)

            # Check for degenerate GARCH parameters
            persistence = alpha1 + beta1
            if persistence < 0.1:
                warnings.append(
                    f"Low GARCH persistence (α+β={persistence:.4f}). "
                    "Model may not capture volatility clustering."
                )
                converged = False

            if persistence >= 1.0:
                warnings.append(
                    f"Non-stationary GARCH (α+β={persistence:.4f} ≥ 1). "
                    "Variance process is explosive."
                )
                converged = False

            if omega <= 0 or alpha1 < 0 or beta1 < 0:
                warnings.append(
                    f"Invalid parameter signs: ω={omega:.6f}, α={alpha1:.6f}, β={beta1:.6f}"
                )
                converged = False

            if nu <= 2.0:
                warnings.append(
                    f"Student-t degrees of freedom too low (ν={nu:.2f} ≤ 2). "
                    "Variance may be undefined."
                )

            # Store fitted params and model result for sampling
            self._fit_params = params
            self._fit_result = res  # Store full result for simulate() method

            return FitResult(
                model_name=self.name,
                log_likelihood=loglik,
                aic=float(res.aic),
                bic=float(res.bic),
                params=params,
                n=len(returns_arr),
                converged=converged,
                heavy_tailed=True,  # Student-t always heavy-tailed if nu < 30
                fit_success=converged and not warnings,
                warnings=warnings,
            )
        except Exception as exc:
            raise DistributionFitError(f"GARCH-T fit failed: {exc}") from exc

    def sample(self, n_paths: int, n_steps: int, seed: int | None = None) -> FloatArray:
        """
        Sample from fitted GARCH-t distribution.

        Uses arch model's simulate() method which properly handles conditional
        volatility dynamics, then rescales back to original data scale.

        Parameters
        ----------
        n_paths : int
            Number of independent paths to generate
        n_steps : int
            Number of time steps per path
        seed : int | None
            Random seed for reproducibility

        Returns
        -------
        np.ndarray
            Simulated returns in original scale, shape (n_paths, n_steps)
        """
        if self._fit_result is None or self._scale_factor is None:
            raise DistributionFitError("GarchTFitter.sample called before fit")

        # Set random seed if provided
        if seed is not None:
            np.random.seed(seed)

        # Generate paths using arch model's simulate method
        # This properly handles GARCH conditional volatility dynamics
        paths: list[FloatArray] = []
        for _ in range(n_paths):
            sim = self._fit_result.model.simulate(self._fit_result.params, nobs=n_steps)
            # Rescale back to original data scale
            path = np.asarray(sim.data.values / self._scale_factor, dtype=np.float64)
            paths.append(path)

        return np.vstack(paths)

    def _require_fit(self) -> tuple[Any, float]:
        if self._fit_result is None or self._scale_factor is None:
            raise DistributionFitError("GarchTFitter accessor called before fit")
        return self._fit_result, self._scale_factor

    def original_scale_params(self) -> dict[str, float]:
        """Fitted parameters in the units of the returns passed to ``fit``.

        ``fit`` lets ``arch`` rescale the data (``r_scaled = scale * r``) and reports parameters
        in the rescaled units. Undoing that: ``mu = mu_scaled / scale``,
        ``omega = omega_scaled / scale**2``; ``alpha``, ``beta`` and ``nu`` are unit-free.
        Keys: ``mu``, ``omega``, ``alpha``, ``beta``, ``nu``.
        """
        res, scale = self._require_fit()
        params = res.params
        return {
            "mu": float(params["mu"]) / scale,
            "omega": float(params["omega"]) / scale**2,
            "alpha": float(params["alpha[1]"]),
            "beta": float(params["beta[1]"]),
            "nu": float(params["nu"]),
        }

    def conditional_volatility(self) -> FloatArray:
        """In-sample conditional volatility ``sigma_t`` in the units of the fitted returns."""
        res, scale = self._require_fit()
        return np.asarray(res.conditional_volatility, dtype=np.float64) / scale

    def standardized_residuals(self) -> FloatArray:
        """In-sample standardized residuals ``z_t = (r_t - mu) / sigma_t`` (unit-free)."""
        res, _ = self._require_fit()
        return np.asarray(res.std_resid, dtype=np.float64)

    def optimizer_converged(self) -> bool:
        """True when the ``arch`` optimizer reported success (``convergence_flag == 0``)."""
        res, _ = self._require_fit()
        return int(res.convergence_flag) == 0

    def log_likelihood(self) -> float:
        raise DistributionFitError("GARCH-T log-likelihood not available (not implemented)")


__all__ = ["GarchTFitter"]
