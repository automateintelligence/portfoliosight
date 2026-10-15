"""The diversification surface, the heatmap raster, the drawn frontier curve and the reference
interpolation (spec 4.7, 4.9, 4.11).

Every risk column holds a ladder of mixes on its own risk line, from the frontier mix at the top
down to the most diversified mix found there, the peak (`ladder.py`). Nothing below a peak is
computed: such a mix would earn less and be less diversified. The raster resamples the ladders
on shared return floors, with no further solving, so a chart can paint rectangles.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np

from .ladder import LEVELS, EnbProgram, ladders, peak_pools, spread_peaks
from .optimize import Frontier, MenuPrograms
from .torsion import enb

NY = 32
SUBSTEPS = 8


@dataclass(frozen=True)
class Surface:
    """`nx` risk columns, each a ladder of `levels + 2` mixes with risk `X_j`."""

    w: np.ndarray  # nx x (levels + 2) x n, the frontier mix first and the peak last
    y: np.ndarray  # nx x (levels + 2), expected return of each mix, never rising down a column
    z: np.ndarray  # nx x (levels + 2), ENB of each mix, never falling down a column
    hop: np.ndarray  # nx x (levels + 1), True where two neighbouring levels must not be blended
    collapsed: np.ndarray  # True where the frontier mix is the most diversified one found
    enb_ref: float  # highest ENB among all mixes of all columns


@dataclass(frozen=True)
class Raster:
    """The ladders resampled on `ny` shared return floors, for drawing."""

    y: np.ndarray  # return floors Y_k, ascending
    w: list[list[np.ndarray | None]]  # nx x ny mixes, None outside the column's span
    z: np.ndarray  # nx x ny ENB of each mix, NaN where there is none
    k_div: np.ndarray  # row holding the column's peak, -1 for a collapsed column
    y_div: np.ndarray  # that row's floor (y_front[j] for a collapsed column)


def surface(
    program: EnbProgram,
    programs: MenuPrograms,
    front: Frontier,
    levels: int = LEVELS,
    workers: int = 1,
) -> Surface:
    """Find every column's peak, then lay out and solve its ladder.

    A ladder can come across a mix more diversified than the peak it started from. Once all
    ladders are solved, each column's best is offered to its neighbours once more, and a column
    that gains from it has its ladder laid out again. The ladders, which are most of the work,
    and the peak search's own starts are solved on `workers` processes (`parallel.py`); the
    starts and sweeps that pass a column's best to its neighbour run here, in order.
    """
    pools = peak_pools(program, programs, front, workers=workers)
    risks = [float(risk) for risk in front.x]
    found = ladders(program, risks, pools, range(len(pools)), levels, workers)
    gained = spread_peaks(program, programs, front, pools)
    found.update(ladders(program, risks, pools, gained, levels, workers))
    columns = [found[j] for j in range(len(pools))]
    z = np.array([entry.z for entry in columns])
    return Surface(
        w=np.array([entry.w for entry in columns]),
        y=np.array([entry.y for entry in columns]),
        z=z,
        hop=np.array([entry.hop for entry in columns]),
        collapsed=np.array([entry.collapsed for entry in columns]),
        enb_ref=float(z.max()),
    )


def raster(surf: Surface, front: Frontier, program: EnbProgram, ny: int = NY) -> Raster:
    """Resample the ladders on `ny` floors from the lowest peak return to the top of the frontier.

    Cell `(j, k)` holds the most diversified mix found at risk `X_j` that earns at least `Y_k`.
    Inside the ladder's span, `y_peak[j] < Y_k <= y_front[j]`, that is the ladder's mix at that
    return: the straight blend of the two ladder mixes whose returns enclose it, which earns
    exactly `Y_k` and whose risk is at most `X_j`; where those two are a hop apart, the upper
    one, which earns more than `Y_k`. At or below the peak's return the floor no longer binds
    and the cell holds the peak itself (the frontier mix in a collapsed column). Above the
    frontier nothing is feasible and the cell is empty. `k_div[j]` is the highest row that
    holds the peak.
    """
    if ny < 2:
        raise ValueError("a raster needs at least 2 rows")
    nx = len(front.x)
    y = np.linspace(float(surf.y[:, -1].min()), float(front.y.max()), ny)
    w: list[list[np.ndarray | None]] = []
    z = np.full((nx, ny), np.nan)
    k_div = np.full(nx, -1, dtype=int)
    for j in range(nx):
        cells: list[np.ndarray | None] = [None] * ny
        returns = surf.y[j]
        bottom = int(np.searchsorted(y, returns[-1], side="right")) - 1
        for k in range(ny):
            if y[k] > returns[0]:
                break
            if k <= bottom:
                mix = surf.w[j, -1]
            else:
                lower = int(np.argmax(returns < y[k]))  # the first level earning less than Y_k
                share = (returns[lower - 1] - y[k]) / (returns[lower - 1] - returns[lower])
                if surf.hop[j, lower - 1]:
                    share = 0.0
                mix = (1.0 - share) * surf.w[j, lower - 1] + share * surf.w[j, lower]
            cells[k] = mix
            z[j, k] = enb(mix, program.cov, program.basis)
        if not surf.collapsed[j]:
            k_div[j] = bottom
        w.append(cells)
    y_div = np.where(surf.collapsed, front.y, y[k_div])
    return Raster(y=y, w=w, z=z, k_div=k_div, y_div=y_div)


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


def s_safe(bad_front) -> float:
    """Left end of the risk slider: the rightmost column whose frontier mix has the best bad year.

    `bad_front` is the bad one-year return of each frontier node. Between nodes the page reads
    the range by straight interpolation, so no position between two columns can beat both.
    """
    bad = np.asarray(bad_front, dtype=float)
    return float(np.flatnonzero(bad == bad.max())[-1])


def interpolate(tensor: Mapping, s: float, t: float) -> np.ndarray:
    """The mix at slider position `(s, t)`: the reference for the browser's interpolation.

    `tensor` needs `ladder.w` and `ladder.hop` in the tensor's own layout. `s` is the column
    position in `[0, nx - 1]`; `t` runs from 0 (the frontier mix) to 1 (the peak) along each
    neighbouring column's ladder, and reaches both ends exactly. Nothing is clipped or
    renormalized: the result is a convex combination of computed mixes.
    """
    ladders, hops = tensor["ladder"]["w"], tensor["ladder"]["hop"]
    columns = len(ladders)
    if not (0.0 <= s <= columns - 1 and 0.0 <= t <= 1.0):
        raise ValueError(f"position ({s!r}, {t!r}) is outside [0, {columns - 1}] x [0, 1]")
    j = min(int(math.floor(s)), columns - 2)
    lam = s - j
    left = _ladder_mix(ladders[j], hops[j], t)
    return (1.0 - lam) * left + lam * _ladder_mix(ladders[j + 1], hops[j + 1], t)


def _ladder_mix(ladder, hops, t: float) -> np.ndarray:
    """A column's mix at fraction `t` of its ladder: straight between the two levels around it.

    Levels are evenly spaced in `t`, level `l` of `L` at `t = l / (L - 1)`. Across a hop
    nothing is blended: the upper level holds up to the middle of the step, the lower one from
    there on.
    """
    last = len(ladder) - 1
    position = t * last
    level = min(int(math.floor(position)), last - 1)
    share = position - level
    if hops[level]:
        share = 0.0 if share < 0.5 else 1.0
    upper = np.asarray(ladder[level], dtype=float)
    return (1.0 - share) * upper + share * np.asarray(ladder[level + 1], dtype=float)
