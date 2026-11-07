"""Arm 6: the app's ENB knee (Optimized point) at the six experiment risks (protocol v3 §2.7, as
amended 2026-11-07).

Everything is the app's own code, called unmodified:

1. `mu_s` (production `menu_beta_blend`, `ctx.mu_s`), the origin's covariance, the menu bounds,
   ENB on the minimum torsion of that covariance (`torsion.torsion_basis`, builder.py:326);
2. the app's 48-column surface: `optimize.frontier(programs, 48)` and `surface.surface(...)`,
   exactly as `builder._build` runs them (`levels = ladder.LEVELS`, one worker);
3. one side column per experiment risk `r = X(a)`, which never feeds back into the 48 columns:
   its frontier node is the app's frontier program at ceiling `r` (`programs.frontier_point`),
   given the app's two corrections (never below the app node to its left, moved onto the line
   toward the greedy fill with `optimize.onto_risk`), so it sits on `sigma = r` within 1e-6; its
   pool is solved by `EnbProgram.solve` from that node, from `ladder.RANDOM_STARTS` random
   starts (`ladder.random_start`, generator seeded `[ladder.SEED, round(r * 1e6)]`) and from
   the peaks of the two adjacent app columns; its ladder is `ladder.column`;
4. the knee is `suggest.balanced_level` of that ladder: the rung maximizing `e - g`, ties to less
   return given up, a ladder gaining no ENB answers the frontier node (`knee_collapsed`), and one
   gaining ENB for no return answers the peak (suggest.py:48-49).
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field

import numpy as np

from portfoliosight.engine import ladder as L
from portfoliosight.engine.optimize import NX, TOL, MenuPrograms, SolveError, frontier, onto_risk
from portfoliosight.engine.suggest import balanced_level
from portfoliosight.engine.surface import Surface, surface
from portfoliosight.engine.torsion import TorsionError, torsion_basis

from . import contracts as C


@dataclass(frozen=True)
class KneeColumn:
    """The side column at one experiment risk."""

    r_fraction: float
    r: float
    status: str  # OK, KNEE_COLLAPSED or ANCHOR_FAILED
    level: int  # the knee's rung (0 = the frontier node); -1 when failed
    w_knee: np.ndarray  # the knee mix (arm 6)
    w_front: np.ndarray  # the app's frontier node at r (reference)
    ladder_y: np.ndarray  # the ladder's rungs: expected return, never rising
    ladder_z: np.ndarray  # ENB, never falling
    ladder_w: np.ndarray  # rungs x N
    members: list[np.ndarray] = field(repr=False)  # every pool member at the column, found order
    neighbours: tuple[int, int] = (-1, -1)  # the adjacent app columns
    line_error: float = math.nan  # |sigma(w_front) - r|
    seconds: float = 0.0


@dataclass
class KneeResult:
    columns: list[KneeColumn]
    app_x: np.ndarray  # the app's 48 column risks
    surface: Surface | None
    seconds: float
    error: str | None = None


def side_frontier_node(programs: MenuPrograms, front, r: float) -> np.ndarray:
    """The app's frontier mix at ceiling `r` with `optimize.frontier`'s two corrections."""
    j = int(np.searchsorted(front.x, r)) - 1
    mix = programs.frontier_point(r)
    left = front.w[max(j, 0)]
    if programs.mu @ mix < programs.mu @ left:
        mix = left
    if r - programs.sigma(mix) > TOL:
        mix = onto_risk(mix, front.w[-1], r, programs.cov)
    return mix


def side_column(
    program: L.EnbProgram,
    programs: MenuPrograms,
    front,
    surf: Surface,
    r: float,
    r_fraction: float,
    seed: int = L.SEED,
) -> KneeColumn:
    """The side column at risk `r` (see the module docstring, step 3 and 4)."""
    clock = time.perf_counter()
    j = int(np.searchsorted(front.x, r)) - 1
    j = min(max(j, 0), len(front.x) - 2)
    node = side_frontier_node(programs, front, r)
    pool = L.Pool(program.candidate(node))
    rng = np.random.default_rng([seed, int(round(r * 1e6))])
    lowest, top = front.w[0], front.w[-1]
    starts = [node]
    starts += [L.random_start(rng, program, r, lowest, top) for _ in range(L.RANDOM_STARTS)]
    starts += [surf.w[j, -1], surf.w[j + 1, -1]]
    for start in starts:
        pool.add(program.solve(r, None, start))
    col = L.column(program, r, pool)
    level = balanced_level(col.y, col.z)
    line_error = abs(programs.sigma(node) - r)
    status = C.KNEE_COLLAPSED if col.collapsed else C.OK
    if not line_error <= TOL:
        status = C.ANCHOR_FAILED
    return KneeColumn(
        r_fraction=r_fraction,
        r=r,
        status=status,
        level=int(level),
        w_knee=np.array(col.w[level], dtype=float),
        w_front=np.array(node, dtype=float),
        ladder_y=np.array(col.y, dtype=float),
        ladder_z=np.array(col.z, dtype=float),
        ladder_w=np.array(col.w, dtype=float),
        members=[np.array(m.w, dtype=float) for m in pool.members],
        neighbours=(j, j + 1),
        line_error=float(line_error),
        seconds=time.perf_counter() - clock,
    )


def _failed(a: float, r: float, n: int, reason_seconds: float) -> KneeColumn:
    nan = np.full(n, np.nan)
    return KneeColumn(
        a, r, C.ANCHOR_FAILED, -1, nan, nan, np.empty(0), np.empty(0), np.empty((0, n)), [],
        seconds=reason_seconds,
    )  # fmt: skip


def knee_columns(
    ctx: C.OriginContext,
    risk_of: dict[float, float],
    *,
    nx: int = NX,
    levels: int = L.LEVELS,
) -> KneeResult:
    """Arm 6 at each experiment risk `risk_of[a] = X(a)` of one (menu, origin, lookback).

    A failure of the app's programs (a Clarabel `SolveError`, a torsion that does not check)
    fails every column (`anchor_failed`), with the reason in `error`.
    """
    clock = time.perf_counter()
    lo = np.asarray(ctx.menu.lower, dtype=float)
    hi = np.asarray(ctx.menu.upper, dtype=float)
    mu_s = np.asarray(ctx.mu_s, dtype=float)
    cov = np.asarray(ctx.cov, dtype=float)
    n = len(mu_s)
    try:
        basis = torsion_basis(cov)
        programs = MenuPrograms(mu_s, cov, lo, hi)
        front = frontier(programs, nx, 1)
        program = L.EnbProgram(mu_s, cov, lo, hi, basis)
        surf = surface(program, programs, front, levels, 1)
        columns = [side_column(program, programs, front, surf, r, a) for a, r in risk_of.items()]
    except (SolveError, TorsionError, ValueError) as exc:
        seconds = time.perf_counter() - clock
        return KneeResult(
            [_failed(a, r, n, seconds) for a, r in risk_of.items()],
            np.empty(0), None, seconds, f"{type(exc).__name__}: {exc}",
        )  # fmt: skip
    return KneeResult(columns, np.array(front.x), surf, time.perf_counter() - clock)
