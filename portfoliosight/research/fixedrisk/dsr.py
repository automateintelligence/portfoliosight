"""Deflated Sharpe ratio as computed in protocol v2 section 7a (a modified Bailey-Lopez de Prado).

A diagnostic of selection bias, not a gate. The series are annual-return differences on the ledger's
disjoint intervals, so the Sharpe ratio is in annual units and is not annualized further.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

import numpy as np
from scipy import stats

EULER_GAMMA = 0.5772156649015329
N_EFF_MIN = 1.0
N_EFF_MAX = 20.0
ZERO_SD = 1e-12


@dataclass(frozen=True)
class DsrResult:
    n: int  # observations in the primary series
    sr: float | None  # Sharpe ratio of the primary series (ddof 1), annual units
    sr0: float | None  # benchmark Sharpe ratio
    trial_variance: float | None  # variance of the trials' SR (ddof 1)
    n_eff: float | None  # participation ratio, clipped to [1, 20]
    trials_used: int
    trials_dropped: int  # zero-sd trials
    skew: float | None
    kurtosis: float | None  # non-excess
    dsr: float | None
    reason: str = ""

    def record(self) -> dict:
        return asdict(self)


def _sharpe(x: np.ndarray) -> float:
    return float(x.mean() / x.std(ddof=1))


def participation_ratio(trials: np.ndarray) -> float:
    """`(sum lambda)^2 / sum lambda^2` of the trials' correlation matrix, clipped to [1, 20]."""
    k = trials.shape[1]
    if k < 2:
        return N_EFF_MIN
    eig = np.clip(np.linalg.eigvalsh(np.corrcoef(trials.T)), 0.0, None)
    ratio = float(eig.sum() ** 2 / np.sum(eig**2))
    return float(min(max(ratio, N_EFF_MIN), N_EFF_MAX))


def benchmark_sr(variance: float, n_eff: float) -> float:
    """`sqrt(V) ((1 - g) Phi^-1(1 - 1/N) + g Phi^-1(1 - 1/(N e)))`; 0 when N_eff < 2."""
    if n_eff < 2.0 or not math.isfinite(variance):
        return 0.0
    ppf = stats.norm.ppf
    return math.sqrt(variance) * (
        (1.0 - EULER_GAMMA) * ppf(1.0 - 1.0 / n_eff)
        + EULER_GAMMA * ppf(1.0 - 1.0 / (n_eff * math.e))
    )


def deflated_sharpe(trials: np.ndarray, primary: int = 0) -> DsrResult:
    """DSR of column `primary` among the columns of `trials` (n x K, no missing values).

    Zero-sd trials are dropped and counted; a zero-sd primary series has no DSR.
    """
    x = np.asarray(trials, dtype=float)
    if x.ndim != 2 or not np.isfinite(x).all():
        raise ValueError("trials must be a finite n x K array")
    n, k = x.shape
    if n < 3:
        return DsrResult(
            n, None, None, None, None, 0, 0, None, None, None, "fewer than 3 observations"
        )
    sd = x.std(axis=0, ddof=1)
    keep = sd > ZERO_SD
    dropped = int((~keep).sum())
    if not keep[primary]:
        return DsrResult(
            n,
            None,
            None,
            None,
            None,
            int(keep.sum()),
            dropped,
            None,
            None,
            None,
            "primary series has zero standard deviation",
        )
    kept = x[:, keep]
    srs = kept.mean(axis=0) / kept.std(axis=0, ddof=1)
    variance = float(np.var(srs, ddof=1)) if kept.shape[1] > 1 else math.nan
    n_eff = participation_ratio(kept)
    sr0 = benchmark_sr(variance, n_eff)
    series = x[:, primary]
    sr = _sharpe(series)
    skew = float(stats.skew(series, bias=True))
    kurt = float(stats.kurtosis(series, fisher=False, bias=True))
    denominator = 1.0 - skew * sr + (kurt - 1.0) / 4.0 * sr**2
    reason = ""
    dsr: float | None = None
    if denominator <= 0:
        reason = "non-positive variance term"
    else:
        dsr = float(stats.norm.cdf((sr - sr0) * math.sqrt(n - 1) / math.sqrt(denominator)))
    return DsrResult(
        n,
        sr,
        sr0,
        None if math.isnan(variance) else variance,
        n_eff,
        int(kept.shape[1]),
        dropped,
        skew,
        kurt,
        dsr,
        reason,
    )
