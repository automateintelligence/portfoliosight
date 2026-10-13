"""Per-fund weight bounds and the greedy endpoint portfolios (spec 4.4).

Default bounds are `min = 0`, `max = clamp(3/N, 0.25, 1.0)` with N the funds included in the
window: a demo heuristic that keeps small menus usable, editable per fund.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from numbers import Real

import numpy as np

RULE = "max(0.25, 3/N)"
MIN_FUNDS = 2
SUM_TOL = 1e-9  # slack on the two sum checks, so ten caps of 0.1 are not refused for rounding


class CapsError(ValueError):
    """A cap request that fails the validation of spec 4.4 (the API answers 422)."""


def default_max(n: int) -> float:
    """The default per-fund maximum for a menu of `n` included funds."""
    return min(max(3.0 / n, 0.25), 1.0)


def resolve_bounds(
    ids: Sequence[str], requested: Sequence[Mapping[str, object]] | None = None
) -> tuple[np.ndarray, np.ndarray]:
    """Resolved `(min, max)` arrays in `ids` order.

    `requested` is a list of `{"id", "min", "max"}`; a missing or `None` bound takes the default
    rule, and funds not listed are all default. Raises `CapsError` unless `0 <= min <= max <= 1`
    for every fund, `sum(min) <= 1 <= sum(max)` and the menu has at least two funds.
    """
    ids = list(ids)
    if len(ids) < MIN_FUNDS:
        raise CapsError(f"a menu needs at least {MIN_FUNDS} funds; this one has {len(ids)}")
    position = {fund: i for i, fund in enumerate(ids)}
    if len(position) != len(ids):
        repeated = sorted({fund for fund in ids if ids.count(fund) > 1})
        raise CapsError(f"{', '.join(repeated)}: listed more than once in the menu")
    lo = np.zeros(len(ids))
    hi = np.full(len(ids), default_max(len(ids)))
    seen: set[str] = set()
    for entry in requested or ():
        fund = entry.get("id")
        if not isinstance(fund, str):
            raise CapsError("every cap entry needs a fund id")
        if fund not in position:
            raise CapsError(f"{fund}: not a fund of this menu")
        if fund in seen:
            raise CapsError(f"{fund}: capped more than once")
        seen.add(fund)
        for name, target in (("min", lo), ("max", hi)):
            value = entry.get(name)
            if value is None:
                continue
            if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value):
                raise CapsError(f"{fund}: {name} must be a number between 0 and 1")
            target[position[fund]] = float(value)
    for fund, low, high in zip(ids, lo, hi, strict=True):
        if not 0.0 <= low <= high <= 1.0:
            raise CapsError(f"{fund}: bounds must satisfy 0 <= min <= max <= 1, got {low}, {high}")
    if lo.sum() > 1.0 + SUM_TOL:
        raise CapsError(f"the sum of the minimums is {lo.sum():.6g}; it must not exceed 1")
    if hi.sum() < 1.0 - SUM_TOL:
        raise CapsError(f"the sum of the maximums is {hi.sum():.6g}; it must reach 1")
    return lo, hi


def greedy_fill(mu, lo, hi, *, ascending: bool = False) -> np.ndarray:
    """The extreme-return portfolio under the bounds.

    Every fund gets its minimum first; the remainder goes to funds in descending `mu` order
    (ascending for the lowest-return fill), each up to its maximum. Ties keep menu order.
    """
    mu = np.asarray(mu, dtype=float)
    hi = np.asarray(hi, dtype=float)
    w = np.array(lo, dtype=float)
    rest = 1.0 - w.sum()
    for i in np.argsort(mu if ascending else -mu, kind="stable"):
        add = min(hi[i] - w[i], rest)
        w[i] += add
        rest -= add
    return w


def greedy_is_unique(mu, lo, hi, *, ascending: bool = False) -> bool:
    """Whether the greedy fill is the only mix with its return.

    Another mix earns the same exactly when two funds with the same `mu` can trade weight: one
    holds more than its minimum, the other less than its maximum.
    """
    mu = np.asarray(mu, dtype=float)
    fill = greedy_fill(mu, lo, hi, ascending=ascending)
    gives = fill - np.asarray(lo, dtype=float) > SUM_TOL
    takes = np.asarray(hi, dtype=float) - fill > SUM_TOL
    for value in np.intersect1d(mu[gives], mu[takes]):
        if np.count_nonzero((mu == value) & (gives | takes)) > 1:
            return False
    return True
