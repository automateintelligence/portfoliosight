"""The diversification surface, the drawn frontier curve and the reference interpolation
(spec 4.7, 4.9, 4.11).

Cell `(j, k)` holds the least concentrated mix (smallest `|w|^2`, a convex proxy) with risk at
most `X_j` and return at least `Y_k`; its colour is the exact ENB of that mix. Per column the
frontier mix and the feasible cells are candidates, and the highest-ENB one is the column's
"most diversified" end.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np

from .caps import greedy_fill, greedy_is_unique
from .invariants import TOL
from .optimize import Frontier, MenuPrograms
from .stats import RANGE_Z
from .torsion import TorsionBasis, enb

NY = 32
SUBSTEPS = 8


@dataclass(frozen=True)
class Surface:
    """The grid of one (menu, lookback): `nx` risk columns by `ny` return floors."""

    y: np.ndarray  # return floors Y_k, ascending
    w: list[list[np.ndarray | None]]  # nx x ny mixes, None where Y_k > y_front[j]
    z: np.ndarray  # nx x ny ENB of each mix, NaN where there is none
    enb_front: np.ndarray  # ENB of each frontier mix
    k_div: np.ndarray  # row of the column's highest-ENB candidate, -1 = the frontier mix
    y_div: np.ndarray  # its return floor (y_front[j] when k_div = -1)
    w_div: np.ndarray  # nx x n, its mix
    enb_ref: float  # highest ENB among all candidates of all columns


def surface(programs: MenuPrograms, front: Frontier, basis: TorsionBasis, ny: int = NY) -> Surface:
    """Solve every feasible cell and pick each column's most diversified candidate.

    Two kinds of cell are not solved for, because their answer is exact without a solve.

    A cell that can hold nothing but the frontier mix is that mix: every cell of the
    minimum-risk column, and a cell whose floor equals its column's frontier return, provided
    that frontier mix is the only one with that return. It is the only one below the menu's top
    return (two such mixes would average to one strictly inside the ceiling, which could then
    earn more), and at the top return when the greedy fill is unique; with tied expected returns
    it is not, and the cell is solved like any other.

    Once a solved mix earns more than its floor asks, the floor is slack, so the same mix is
    the answer for every lower floor of the column. This is what makes "ties go to the highest
    return" pick the top of such a run.
    """
    if ny < 2:
        raise ValueError("a surface needs at least 2 rows")
    mu, cov = programs.mu, programs.cov
    nx = len(front.x)
    top = float(front.y.max())
    lowest = min(float(mu @ greedy_fill(mu, programs.lo, programs.hi, ascending=True)), top)
    y = np.linspace(lowest, top, ny)
    top_is_unique = greedy_is_unique(mu, programs.lo, programs.hi)
    w: list[list[np.ndarray | None]] = []
    z = np.full((nx, ny), np.nan)
    enb_front = np.array([enb(mix, cov, basis) for mix in front.w])
    enb_best = enb_front.copy()  # per column: the highest ENB among its candidates
    k_div = np.full(nx, -1, dtype=int)
    for j in range(nx):
        column: list[np.ndarray | None] = [None] * ny
        slack_mix = None
        for k in range(ny - 1, -1, -1):
            if y[k] > front.y[j]:
                continue
            if slack_mix is not None:
                mix = slack_mix
            elif front.pinned[j] or (
                y[k] == front.y[j] and (top_is_unique or front.y[j] < top - TOL)
            ):
                mix = front.w[j]
            else:
                mix = programs.cell(float(front.x[j]), float(y[k]))
                if float(mu @ mix) > y[k] + TOL:
                    slack_mix = mix
            column[k] = mix
            z[j, k] = enb(mix, cov, basis)
            if z[j, k] > enb_best[j]:  # strictly: a tie stays with the higher return
                enb_best[j], k_div[j] = z[j, k], k
        w.append(column)
    collapsed = k_div < 0
    y_div = np.where(collapsed, front.y, y[k_div])
    w_div = np.array(
        [front.w[j] if collapsed[j] else w[j][k_div[j]] for j in range(nx)], dtype=float
    )
    return Surface(
        y=y,
        w=w,
        z=z,
        enb_front=enb_front,
        k_div=k_div,
        y_div=y_div,
        w_div=w_div,
        enb_ref=float(enb_best.max()),
    )


def frontier_curve(w_front, mu_s, cov, substeps: int = SUBSTEPS) -> tuple[np.ndarray, np.ndarray]:
    """Actual `(sigma, mu)` of the interpolated frontier mix `w_front(s)`, `substeps` per gap."""
    w_front = np.asarray(w_front, dtype=float)
    mu_s = np.asarray(mu_s, dtype=float)
    cov = np.asarray(cov, dtype=float)
    last_gap = len(w_front) - 2
    sigma, mu = [], []
    for i in range((len(w_front) - 1) * substeps + 1):
        j = min(i // substeps, last_gap)
        lam = i / substeps - j
        mix = (1.0 - lam) * w_front[j] + lam * w_front[j + 1]
        sigma.append(math.sqrt(float(mix @ cov @ mix)))
        mu.append(float(mu_s @ mix))
    return np.array(sigma), np.array(mu)


def s_safe(sigma, mu, substeps: int = SUBSTEPS) -> float:
    """Left end of the risk slider: the rightmost maximum of `Low_front`, in `s` units."""
    low = np.asarray(mu, dtype=float) / 2.0 - RANGE_Z * np.asarray(sigma, dtype=float) / math.sqrt(
        2.0
    )
    return float(np.flatnonzero(low == low.max())[-1]) / substeps


def interpolate(tensor: Mapping, s: float, t: float) -> np.ndarray:
    """The mix at slider position `(s, t)`: the reference for the browser's interpolation.

    `tensor` needs `frontier.w`, `frontier.y`, `grid.w`, `grid.y` and `grid.k_div` in the
    tensor's own layout. `s` is the column position in `[0, nx - 1]`; `t` runs from 0 (the
    frontier mix) to 1 (the most diversified mix) along each neighbouring column's ladder, and
    reaches both ends exactly. Nothing is clipped or renormalized: the result is a convex
    combination of computed mixes.
    """
    columns = len(tensor["frontier"]["w"])
    if not (0.0 <= s <= columns - 1 and 0.0 <= t <= 1.0):
        raise ValueError(f"position ({s!r}, {t!r}) is outside [0, {columns - 1}] x [0, 1]")
    j = min(int(math.floor(s)), columns - 2)
    lam = s - j
    return (1.0 - lam) * _ladder_mix(tensor, j, t) + lam * _ladder_mix(tensor, j + 1, t)


def _ladder_mix(tensor: Mapping, j: int, t: float) -> np.ndarray:
    """Column `j`'s mix at fraction `t` of its ladder's return span.

    The ladder is the frontier mix, then the feasible cells from the top down to the most
    diversified one, each at its return floor. A ladder with no return span (a collapsed one,
    or one whose most diversified mix costs no return) has nothing to walk by return: `t`
    blends its two ends directly.
    """
    mixes = [np.asarray(tensor["frontier"]["w"][j], dtype=float)]
    returns = [float(tensor["frontier"]["y"][j])]
    k_div = int(tensor["grid"]["k_div"][j])
    if k_div >= 0:
        floors = tensor["grid"]["y"]
        for k in range(len(floors) - 1, k_div - 1, -1):
            cell = tensor["grid"]["w"][j][k]
            if cell is not None:
                mixes.append(np.asarray(cell, dtype=float))
                returns.append(min(returns[-1], float(floors[k])))
    if len(mixes) == 1:
        return mixes[0]
    if returns[0] <= returns[-1]:
        return (1.0 - t) * mixes[0] + t * mixes[-1]
    # written so that t = 0 and t = 1 land on the two ends exactly, whatever the rounding
    target = max((1.0 - t) * returns[0] + t * returns[-1], returns[-1])
    lower = next(i for i, value in enumerate(returns) if value <= target)
    if lower == 0:
        return mixes[0]
    share = (returns[lower - 1] - target) / (returns[lower - 1] - returns[lower])
    return (1.0 - share) * mixes[lower - 1] + share * mixes[lower]
