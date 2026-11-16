"""The simple and diversification-driven recipes check of fixed-risk experiment v3, an exploratory
addendum (docs/plans/2026-11-11-diversification-vs-simple-mixes.md, "the protocol", built by
docs/plans/2026-11-15-diversification-vs-simple-mixes-build-plan.md). EXPLORATORY ONLY: no result
here is a finding.

Mixes of one start month, all from its training side and its recorded columns alone, never from a
realized outcome:

- F, the frontier mix with the weight limits, at the six risk settings (the recorded rows);
- U, the frontier mix with no weight limits, at the same risk as F;
- E, equal weight; D, the most-diversified mix under the menu's limits; D10, the same with a flat
  10% limit; each with a comparator, the exact-line frontier mix with the limits at the mix's own
  risk (`F@E`, `F@D`, `F@D10`).

This module so far holds the mixes (`most_diversified`, `frontier_exact`, `month_mixes`) and the
two pre-registered lists the model-side gates compare against.
"""

from __future__ import annotations

import cvxpy as cp
import numpy as np

from portfoliosight.engine import optimize

TOL = optimize.TOL  # 1e-6 in annual volatility and model return (protocol, "Inputs, fixed")
D10_CAP = 0.10  # D10's flat limit on every holding


def most_diversified(sigma: np.ndarray, cov: np.ndarray, hi) -> np.ndarray:
    """The most-diversified mix under `0 <= w <= hi`, `1'w = 1`: the highest diversification ratio
    `(sigma' w) / sqrt(w' cov w)` (Choueifaty and Coignard 2008).

    The paper's synthetic-asset form, one convex program: minimize `y' cov y` subject to
    `sigma' y = 1`, `y >= 0` and `y_i <= hi_i (1' y)` (the limits are linear in `y`), then
    `w = y / 1'y`. `hi` is one limit for every holding or one per holding. `SolveError` when
    Clarabel finds no optimal answer, as when the limits cannot sum to one.
    """
    sigma = np.asarray(sigma, dtype=float)
    limits = np.broadcast_to(np.asarray(hi, dtype=float), sigma.shape)
    y = cp.Variable(len(sigma))
    problem = cp.Problem(
        cp.Minimize(cp.norm(optimize.cholesky_factor(cov) @ y, 2)),
        [sigma @ y == 1, y >= 0, y <= cp.multiply(limits, cp.sum(y))],
    )
    solved = optimize.solve_with_retries(problem, y, "most-diversified mix")
    return solved / solved.sum()


def at_or_above_top(s: float, sigma_top: float) -> bool:
    """The exclusion rule: a risk `s` within `TOL` of a frontier's top, or above it, has no frontier
    mix to pair with (the last node is the max-return greedy fill)."""
    return s >= sigma_top - TOL


def risk_position(s: float, sigma_min: float, sigma_top: float) -> float:
    """`a = (s - sigma_min) / (sigma_top - sigma_min)`: a risk on the axis of the six settings."""
    return (s - sigma_min) / (sigma_top - sigma_min)


def frontier_exact(
    programs: optimize.MenuPrograms,
    lowest: np.ndarray,
    top: np.ndarray,
    s: float,
    sigma_min: float,
    sigma_top: float,
) -> np.ndarray | None:
    """`F(s)`, the exact-line frontier mix with the limits, at any risk `s`.

    `lowest` (the minimum-variance mix) when `s <= sigma_min + TOL`; `None` when `s` is at or
    above the top (`at_or_above_top`: the cell is excluded); otherwise `programs.frontier_point(s)`,
    moved toward `top` (the greedy fill) with `optimize.onto_risk` when it sits more than `TOL`
    inside the ceiling, so that `|sigma(F) - s| <= TOL`. There is no retry on the risk gap;
    `SolveError` propagates.
    """
    if s <= sigma_min + TOL:
        return lowest
    if at_or_above_top(s, sigma_top):
        return None
    mix = programs.frontier_point(s)
    if s - programs.sigma(mix) > TOL:
        mix = optimize.onto_risk(mix, top, s, programs.cov)
    return mix
