"""The v3 objective set of one mix (protocol v3 §2.1, §2.5, §2.6, §4.4).

Every mix a v3 column evaluates gets one row of `FIELDS`, from one call of the bank's
`path_terms(w)` (the mix's compounded years, its path maximum drawdowns and its funds' additive
path sums) plus the engine-independent figures (`sigma`, `mu_s'w`, ENB, DR^2, `H`):

- `tail_drawdown`: TDD, the mean of the `TAIL_PATHS` largest path maximum drawdowns;
- `enlc`: the effective number of loss contributors in the mix's `TAIL_PATHS` worst years;
- `worst_fall`: `H`, the maximum drawdown of the mix's actual daily history up to the origin;
- the year-end figures and U-values of `objective.figures` (linear percentiles).

Drawdowns follow `realized._drawdown`: peak counted from the starting value 1.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from portfoliosight.engine.torsion import TorsionBasis, TorsionError, enb, torsion_basis

from . import contracts as C
from .anchors import Geometry, dr2
from .objective import figures
from .realized import _drawdown

FIELDS = (
    "sigma",
    "mu",
    "in_narrow",  # 1.0 / 0.0: inside the bounds, the budget and the narrow band (to 1e-8)
    "in_wide",
    "bad",
    "typical",
    "good",
    "mean",
    "es_25",
    "u1",
    "u2",
    "u3",
    "u4",
    "max_bad",
    "tdd",
    "h",
    "enlc",  # NaN when no fund loses in the mix's bad years
    "enb",
    "dr2",
    "dd_median",
    "dd_p95",
    "absorbed",  # paths with a day at or below -100% (D = 1, Y = -1)
)
INDEX = {name: i for i, name in enumerate(FIELDS)}


def path_drawdowns(wealth: np.ndarray) -> np.ndarray:
    """Maximum drawdown of each path of a (P, H) wealth array, `realized._drawdown`'s rule."""
    return np.asarray(_drawdown(np.asarray(wealth, dtype=float).T), dtype=float)


def tail_mean(values: np.ndarray, tail: int = C.TAIL_PATHS) -> float:
    """Mean of the `tail` largest values (a correctly rounded sum: the same bits in any order)."""
    v = np.asarray(values, dtype=float)
    if tail < 1 or tail > len(v):
        raise ValueError(f"the tail must hold between 1 and {len(v)} values, got {tail}")
    top = np.partition(v, len(v) - tail)[len(v) - tail :]
    return math.fsum(np.sort(top).tolist()) / tail


def tail_drawdown(drawdowns: np.ndarray, tail: int = C.TAIL_PATHS) -> float:
    """TDD: the mean of the `tail` largest path maximum drawdowns (v3 §2.1). Lower is better."""
    return tail_mean(drawdowns, tail)


def enlc(years: np.ndarray, sums: np.ndarray, w: np.ndarray, tail: int = C.TAIL_PATHS) -> float:
    """Effective number of loss contributors (v3 §2.6); NaN when no fund loses.

    The bad years are the `tail` paths with the lowest compounded year (ties to the lower path
    index). Fund `n`'s contribution to path `p` is `w_n sums[p, n]`; its loss is minus the mean
    contribution over the bad years; shares over the losing funds only; `exp(-sum s ln s)`.
    """
    y = np.asarray(years, dtype=float)
    bad = np.argsort(y, kind="stable")[:tail]
    loss = -np.asarray(w, dtype=float) * np.asarray(sums, dtype=float)[bad].mean(axis=0)
    positive = np.maximum(loss, 0.0)
    total = float(positive.sum())
    if not total > 0.0:
        return math.nan
    s = positive / total
    nz = s[s > 0.0]
    return float(np.exp(-float(nz @ np.log(nz))))


def history_returns(ctx: C.OriginContext) -> np.ndarray:
    """The menu's actual daily returns on its common rows (every holding has a return), from the
    first common day to the origin's close inclusive; nothing after the origin (v3 §2.5)."""
    history = ctx.history
    if history is None:
        raise ValueError("the context carries no history (data.origin_context builds it)")
    index = pd.DatetimeIndex(history.index)
    kept = history.loc[index <= pd.Timestamp(ctx.origin)]
    common = kept.dropna(how="any")
    if len(common) < 1:
        raise ValueError("the holdings share no day with a return before the origin")
    return np.ascontiguousarray(common.to_numpy(dtype=np.float64))


def worst_fall(returns: np.ndarray, w: np.ndarray) -> float:
    """`H(w)`: maximum drawdown of the mix held at constant weights on `returns` (T x N)."""
    wealth = np.cumprod(1.0 + np.asarray(returns, dtype=float) @ np.asarray(w, dtype=float))
    return float(_drawdown(wealth))


@dataclass(eq=False)
class Scorer:
    """Evaluates mixes of one (origin, risk column, bank) on the full v3 objective set.

    `evaluate(w)` returns a read-only vector over `FIELDS`; equal weight vectors are scored once
    (`calls` counts requests, `evaluations` bank evaluations, `seconds` their wall time).
    """

    geo: Geometry
    bank: C.PathBank
    history: np.ndarray  # history_returns(ctx)
    basis: TorsionBasis | None
    r: float
    calls: int = 0
    evaluations: int = 0
    seconds: float = 0.0
    _cache: dict[bytes, np.ndarray] = field(default_factory=dict, repr=False)

    def in_band(self, w: np.ndarray, tau: float) -> bool:
        return self.geo.in_band(w, self.r, tau)

    def evaluate(self, w: np.ndarray) -> np.ndarray:
        import time

        self.calls += 1
        key = np.ascontiguousarray(w, dtype=np.float64).tobytes()
        hit = self._cache.get(key)
        if hit is not None:
            return hit
        clock = time.perf_counter()
        out = self._score(np.asarray(w, dtype=float))
        out.setflags(write=False)
        self._cache[key] = out
        self.evaluations += 1
        self.seconds += time.perf_counter() - clock
        return out

    def _score(self, w: np.ndarray) -> np.ndarray:
        years, drawdowns, sums = self.bank.path_terms(w)  # type: ignore[attr-defined]
        f = figures(years)
        out = np.full(len(FIELDS), np.nan)
        geo = self.geo
        out[INDEX["sigma"]] = geo.risk(w)
        out[INDEX["mu"]] = float(geo.mu_s @ w)
        out[INDEX["in_narrow"]] = float(self.in_band(w, C.TAU_NARROW))
        out[INDEX["in_wide"]] = float(self.in_band(w, C.TAU_WIDE))
        out[INDEX["bad"]] = f.bad
        out[INDEX["typical"]] = f.typical
        out[INDEX["good"]] = f.good
        out[INDEX["mean"]] = f.mean
        out[INDEX["es_25"]] = f.es_25
        for arm in ("U1", "U2", "U3", "U4"):
            out[INDEX[arm.lower()]] = f.utility(arm)
        out[INDEX["max_bad"]] = f.bad
        out[INDEX["tdd"]] = tail_drawdown(drawdowns)
        out[INDEX["h"]] = worst_fall(self.history, w)
        out[INDEX["enlc"]] = enlc(years, sums, w)
        if self.basis is not None:
            try:
                out[INDEX["enb"]] = enb(w, geo.cov, self.basis)
            except TorsionError:
                pass
        out[INDEX["dr2"]] = dr2(w, geo.sigma, geo.cov)
        out[INDEX["dd_median"]], out[INDEX["dd_p95"]] = np.percentile(drawdowns, [50.0, 95.0])
        out[INDEX["absorbed"]] = float(np.count_nonzero(drawdowns >= 1.0))
        return out


def origin_basis(ctx: C.OriginContext) -> TorsionBasis | None:
    """The minimum torsion of the origin's covariance, as the app computes ENB (builder.py:326)."""
    try:
        return torsion_basis(np.asarray(ctx.cov, dtype=float))
    except TorsionError:
        return None
