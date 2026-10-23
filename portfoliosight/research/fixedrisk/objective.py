"""Search objectives of the fixed-risk experiment (protocol §4, gradient objective).

- Exact quantile: NumPy's linear estimator, `j = floor(q (P - 1))`, `f = q (P - 1) - j`,
  `Q_q = (1 - f) R_(j+1) + f R_(j+2)`; its gradient is the same two-weight combination of the two
  paths' gradients (at a tie, the mean gradient of the tied paths).
- Kernel-smoothed quantile: `sum_i k_i R_(i)` with rank coordinate `u_i = (i - 1) / (P - 1)`,
  Gaussian raw weights `phi((u_i - q) / h)` for `|u_i - q| <= 4 h`, normalized to sum 1.

One bank evaluation of a mix (`Evaluator.evaluate`) yields the exact Bad/Typical/Good, the search
objective's three values and their path weights, and the bank's vector-Jacobian product, so every
arm (`U_k`, max-Bad) is served from it. Reported figures are always exact (`figures`).
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache

import numpy as np

from portfoliosight.engine import measures

from .contracts import ARMS, KERNEL_BANDWIDTH, KERNEL_TRUNCATION, QUANTILES, Figures, PathBank

PERCENTILES = tuple(100.0 * q for q in QUANTILES)
MODES = ("exact", "kernel")


@lru_cache(maxsize=16)
def linear_point(paths: int, q: float) -> tuple[int, float]:
    """0-based rank `j` and fraction `f` of NumPy's linear percentile of `paths` values."""
    virtual = (paths - 1) * (np.true_divide(100.0 * q, 100))
    j = int(math.floor(virtual))
    return j, float(virtual - j)


def _lerp(low: float, high: float, f: float) -> float:
    """NumPy's `_lerp`, so the value is bitwise NumPy's linear percentile."""
    diff = high - low
    return high - diff * (1.0 - f) if f >= 0.5 else low + diff * f


@lru_cache(maxsize=16)
def kernel_weights(
    paths: int, q: float, h: float = KERNEL_BANDWIDTH, cut: float = KERNEL_TRUNCATION
) -> tuple[int, np.ndarray]:
    """First 0-based rank and normalized weights of the kernel-smoothed quantile."""
    u = np.arange(paths) / (paths - 1)
    z = (u - q) / h
    inside = np.flatnonzero(np.abs(z) <= cut)
    raw = np.exp(-0.5 * z[inside] ** 2)
    weights = raw / raw.sum()
    weights.setflags(write=False)
    return int(inside[0]), weights


@lru_cache(maxsize=16)
def _exact_plan(paths: int) -> tuple[tuple[tuple[int, float], ...], tuple[int, ...]]:
    points = tuple(linear_point(paths, q) for q in QUANTILES)
    kth = sorted({k for j, _ in points for k in (j, min(j + 1, paths - 1))})
    return points, tuple(kth)


def _tied_weights(years: np.ndarray, rank_paths, j: int, f: float):
    """Path ids and weights of `(1 - f) R_(j+1) + f R_(j+2)`; tied paths share their weight."""
    idx_parts, w_parts = [], []
    for k, share in ((j, 1.0 - f), (min(j + 1, len(years) - 1), f)):
        if share == 0.0:
            continue
        p = int(rank_paths[k])
        v = years[p]
        if np.count_nonzero(years == v) > 1:
            tied = np.flatnonzero(years == v)
            idx_parts.append(tied)
            w_parts.append(np.full(len(tied), share / len(tied)))
        else:
            idx_parts.append(np.array([p]))
            w_parts.append(np.array([share]))
    return np.concatenate(idx_parts), np.concatenate(w_parts)


def exact_values(years: np.ndarray, rank_paths: np.ndarray) -> np.ndarray:
    """Bad/Typical/Good linear quantiles, given paths at least partitioned at the plan's ranks."""
    points, _ = _exact_plan(len(years))
    last = len(years) - 1
    return np.array(
        [
            _lerp(float(years[rank_paths[j]]), float(years[rank_paths[min(j + 1, last)]]), f)
            for j, f in points
        ]
    )


def exact_quantiles(years: np.ndarray, order: np.ndarray | None = None):
    """Bad/Typical/Good linear quantiles and their path weights from one partition.

    Returns `(values (3,), [(paths, weights)] * 3)`; at a tie the tied paths share the weight.
    """
    points, kth = _exact_plan(len(years))
    rank_paths = np.argpartition(years, kth) if order is None else order
    parts = [_tied_weights(years, rank_paths, j, f) for j, f in points]
    return exact_values(years, rank_paths), parts


def exact_quantile(years: np.ndarray, q: float) -> tuple[float, np.ndarray, np.ndarray]:
    """`(Q_q, paths, weights)` for one `q`: the linear quantile and its path weights."""
    j, f = linear_point(len(years), q)
    order = np.argsort(years, kind="stable")
    low, high = years[order[j]], years[order[min(j + 1, len(years) - 1)]]
    idx, w = _tied_weights(years, order, j, f)
    return _lerp(float(low), float(high), f), idx, w


def kernel_quantile(
    years: np.ndarray, q: float, order: np.ndarray | None = None
) -> tuple[float, np.ndarray, np.ndarray]:
    """`(Q~_q, paths, weights)`: the kernel-smoothed quantile at the current ranks."""
    if order is None:
        order = np.argsort(years, kind="stable")
    first, weights = kernel_weights(len(years), q)
    paths = order[first : first + len(weights)]
    return float(weights @ years[paths]), paths, weights


def figures(years: np.ndarray) -> Figures:
    """Exact figures of one mix's years: linear percentiles, mean and `measures.es_25`."""
    bad, typical, good = np.percentile(years, PERCENTILES)
    return Figures(
        bad=float(bad),
        typical=float(typical),
        good=float(good),
        mean=math.fsum(years.tolist()) / len(years),
        es_25=measures.es_25(years),
    )


def coefficients(arm: str | tuple[float, float, float]) -> tuple[float, float, float]:
    """An arm's (Bad, Typical, Good) weights; a tuple is taken as given (e.g. (0, 1, 0))."""
    return ARMS[arm] if isinstance(arm, str) else arm


def arm_value(btg: np.ndarray, arm: str | tuple[float, float, float]) -> float:
    """`U_k` or Bad (arm "B") from the three quantiles."""
    b, t, g = coefficients(arm)
    return b * float(btg[0]) + t * float(btg[1]) + g * float(btg[2])


@dataclass
class Evaluation:
    """One bank evaluation of one mix; path weights are formed only when a gradient is asked."""

    exact: np.ndarray  # Bad, Typical, Good, exact linear quantiles
    search: np.ndarray  # the search objective's three values (= exact in exact mode)
    years: np.ndarray
    ranks: np.ndarray  # paths in rank order (kernel) or partitioned at the plan's ranks (exact)
    vjp: Callable[[np.ndarray], np.ndarray]
    mode: str

    def value(self, arm: str | tuple[float, float, float]) -> float:
        return arm_value(self.search, arm)

    def path_weights(self, arm: str | tuple[float, float, float]) -> np.ndarray:
        """`a` (P,): the arm's search objective as a weighted sum of the paths at their ranks."""
        a = np.zeros(len(self.years))
        weights = coefficients(arm)
        if self.mode == "exact":
            points, _ = _exact_plan(len(self.years))
            for c, (j, f) in zip(weights, points, strict=True):
                if c:
                    idx, wts = _tied_weights(self.years, self.ranks, j, f)
                    np.add.at(a, idx, c * wts)
        else:
            for c, q in zip(weights, QUANTILES, strict=True):
                if c:
                    first, wts = kernel_weights(len(self.years), q)
                    a[self.ranks[first : first + len(wts)]] += c * wts
        return a

    def gradient(self, arm: str | tuple[float, float, float]) -> np.ndarray:
        """Gradient in `w` of the arm's search objective (one vjp)."""
        return self.vjp(self.path_weights(arm))


class Evaluator:
    """Evaluates mixes on one bank for a search mode ("exact" or "kernel")."""

    def __init__(self, bank: PathBank, mode: str = "exact"):
        if mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}, got {mode!r}")
        self.bank = bank
        self.mode = mode
        self.calls = 0

    def evaluate(self, w: np.ndarray) -> Evaluation:
        years, vjp = self.bank.years_and_vjp(w)
        self.calls += 1
        if self.mode == "exact":
            ranks = np.argpartition(years, _exact_plan(len(years))[1])
            values = exact_values(years, ranks)
            return Evaluation(values, values, years, ranks, vjp, "exact")
        ranks = np.argsort(years, kind="stable")
        smooth = np.array([kernel_quantile(years, q, ranks)[0] for q in QUANTILES])
        return Evaluation(exact_values(years, ranks), smooth, years, ranks, vjp, "kernel")


def batch_quantiles(years: np.ndarray) -> np.ndarray:
    """Exact Bad/Typical/Good of each column of a P x M year matrix: M x 3."""
    return np.percentile(years, PERCENTILES, axis=0).T
