"""The conic programs behind the frontier and the diversification surface (spec 4.5, 4.7).

Three second-order-cone programs share the menu's constraints `1'w = 1`, `min <= w <= max`:

    minimum variance   minimize |C w|
    frontier point     maximize mu_s' w   s.t. |C w| <= X
    surface cell       minimize |w|^2     s.t. |C w| <= X,  mu_s' w >= Y

with `C = cholesky(cov)'`, so `|C w|^2 = w' cov w`. Each is one DPP-parametrized cvxpy problem,
built once per menu and re-solved with new parameter values; Clarabel runs at 1e-8.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass

import cvxpy as cp
import numpy as np

from .caps import greedy_fill

NX = 48
TOL = 1e-6  # the one tolerance of spec 4.11
SOLVER_OPTIONS = {
    "tol_feas": 1e-8,
    "tol_gap_abs": 1e-8,
    "tol_gap_rel": 1e-8,
    "direct_solve_method": "qdldl",  # single-threaded LDL: the same bits on every run
}
# Clarabel now and then stops at "almost solved" on an ordinary program. Each program is tried
# with the plain settings first, then with two numerically different ones; an answer is taken
# only when Clarabel calls it optimal.
RETRY_OPTIONS = ({}, {"equilibrate_enable": False}, {"static_regularization_constant": 1e-9})


class SolveError(RuntimeError):
    """Clarabel found no optimal solution for a program the engine needed."""


@dataclass(frozen=True)
class Frontier:
    """Frontier nodes on `nx` uniform risk ceilings from sigma_min to sigma_max."""

    x: np.ndarray  # risk ceilings X_j
    y: np.ndarray  # mu_s' w of each node
    w: np.ndarray  # nx x n
    pinned: np.ndarray  # True where X_j is the minimum risk: one mix only fits under it


def cholesky_factor(cov) -> np.ndarray:
    """Upper-triangular `C = cholesky(cov)'`, so that `|C w|^2 = w' cov w`."""
    return np.linalg.cholesky(np.asarray(cov, dtype=float)).T


class MenuPrograms:
    """The three programs of one menu: moments and bounds fixed, `X` and `Y` free."""

    def __init__(self, mu_s, cov, lo, hi):
        self.mu = np.asarray(mu_s, dtype=float)
        self.cov = np.asarray(cov, dtype=float)
        self.lo = np.asarray(lo, dtype=float)
        self.hi = np.asarray(hi, dtype=float)
        n = len(self.mu)
        if not (self.cov.shape == (n, n) and self.lo.shape == (n,) and self.hi.shape == (n,)):
            raise ValueError("moments and bounds must describe the same number of funds")
        self._w = cp.Variable(n)
        mu = cp.Parameter(n, value=self.mu)
        factor = cp.Parameter((n, n), value=cholesky_factor(self.cov))
        self._x = cp.Parameter(nonneg=True)
        self._y = cp.Parameter()
        risk = cp.norm(factor @ self._w, 2)
        menu = [cp.sum(self._w) == 1, self._w >= self.lo, self._w <= self.hi]
        self._min_variance = cp.Problem(cp.Minimize(risk), menu)
        self._frontier = cp.Problem(cp.Maximize(mu @ self._w), [risk <= self._x, *menu])
        self._cell = cp.Problem(
            cp.Minimize(cp.sum_squares(self._w)),
            [risk <= self._x, mu @ self._w >= self._y, *menu],
        )

    def sigma(self, w) -> float:
        """Annual risk of a mix, from the covariance the browser also holds."""
        return float(np.sqrt(w @ self.cov @ w))

    def min_variance(self) -> np.ndarray:
        return _solve(self._min_variance, self._w, "minimum-variance mix")

    def frontier_point(self, x: float) -> np.ndarray:
        """The highest-return mix with risk at most `x`."""
        self._x.value = x
        return _solve(self._frontier, self._w, f"frontier point at risk {x!r}")

    def cell(self, x: float, y: float) -> np.ndarray:
        """The least concentrated mix with risk at most `x` and return at least `y`."""
        self._x.value = x
        self._y.value = y
        return _solve(self._cell, self._w, f"cell at risk {x!r}, return floor {y!r}")


def frontier(programs: MenuPrograms, nx: int = NX) -> Frontier:
    """Frontier nodes from the minimum-variance mix to the max-return greedy fill.

    The two ends are not solved for: under `X = sigma_min` the minimum-variance mix is the only
    feasible one, and at `X = sigma_max` the greedy fill is the maximum by construction. A menu
    whose two ends are within the 1e-6 tolerance in risk has one frontier mix, the greedy fill.
    """
    if nx < 2:
        raise ValueError("a frontier needs at least 2 columns")
    lowest = programs.min_variance()
    top = greedy_fill(programs.mu, programs.lo, programs.hi)
    sigma_min, sigma_max = programs.sigma(lowest), programs.sigma(top)
    if sigma_max - sigma_min <= TOL:
        x = np.full(nx, sigma_max)
        w = np.tile(top, (nx, 1))
        pinned = np.zeros(nx, dtype=bool)
    else:
        x = np.linspace(sigma_min, sigma_max, nx)
        inner = [programs.frontier_point(float(ceiling)) for ceiling in x[1:-1]]
        w = np.vstack([lowest, *inner, top])
        pinned = np.arange(nx) == 0
    return Frontier(x=x, y=w @ programs.mu, w=w, pinned=pinned)


def _solve(problem, variable, what: str) -> np.ndarray:
    """Solve with Clarabel, walking the retry ladder; only an optimal answer is returned."""
    status = "not attempted"
    for extra in RETRY_OPTIONS:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")  # the status is read below, not the warning
                problem.solve(solver=cp.CLARABEL, warm_start=False, **SOLVER_OPTIONS, **extra)
        except cp.SolverError as exc:
            status = f"solver error: {exc}"
            continue
        status = problem.status
        if status == cp.OPTIMAL:
            return np.array(variable.value, dtype=float)
    raise SolveError(f"{what}: no optimal solution from Clarabel (last status: {status})")
