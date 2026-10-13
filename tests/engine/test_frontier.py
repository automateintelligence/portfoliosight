"""The conic programs and the frontier (spec 4.5)."""

from __future__ import annotations

import cvxpy as cp
import numpy as np
import pytest

from portfoliosight.engine import optimize
from portfoliosight.engine.caps import greedy_fill
from portfoliosight.engine.optimize import (
    MenuPrograms,
    SolveError,
    cholesky_factor,
    frontier,
)

TOL = 1e-6


def _menu(n: int, seed: int):
    """A seeded SPD menu with random valid bounds: (mu_s, cov, lo, hi)."""
    rng = np.random.default_rng(seed)
    load = rng.normal(0.0, 1.0, (n, 3)) * np.array([0.10, 0.05, 0.03]) + np.array([0.06, 0, 0])
    cov = load @ load.T + np.diag(rng.uniform(0.02, 0.10, n) ** 2)
    mu = rng.uniform(0.01, 0.10, n)
    lo = np.where(rng.random(n) < 0.5, rng.uniform(0.0, 0.3 / n, n), 0.0)
    default = min(max(3.0 / n, 0.25), 1.0)
    high = rng.uniform(max(1.5 / n, 0.12), min(1.0, max(4.0 / n, 0.30)), n)
    hi = np.where(rng.random(n) < 0.5, high, default)
    assert (lo <= hi).all() and lo.sum() <= 1.0 <= hi.sum()
    return mu, cov, lo, hi


def _sigma(w, cov) -> float:
    return float(np.sqrt(w @ cov @ w))


def _own_min_variance(cov, lo, hi) -> float:
    w = cp.Variable(len(lo))
    variance = cp.quad_form(w, cp.psd_wrap(cov))
    menu: list = [cp.sum(w) == 1, w >= lo, w <= hi]
    problem = cp.Problem(cp.Minimize(variance), menu)
    problem.solve(solver=cp.CLARABEL, tol_feas=1e-11, tol_gap_abs=1e-11, tol_gap_rel=1e-11)
    assert problem.status == "optimal"
    return _sigma(np.array(w.value), cov)


def _feasible(w, lo, hi) -> bool:
    return bool(abs(w.sum() - 1) <= TOL and (w >= lo - TOL).all() and (w <= hi + TOL).all())


def test_cholesky_factor_is_upper_and_reproduces_the_variance():
    rng = np.random.default_rng(3601)
    n = 15
    a = rng.normal(size=(n, n))
    cov = (a @ a.T / n + 0.1 * np.eye(n)) * 0.04
    c = cholesky_factor(cov)
    assert np.array_equal(c, np.linalg.cholesky(cov).T)
    assert np.abs(np.tril(c, -1)).max() == 0.0  # L', not L
    worst_wrong = 0.0
    for _ in range(100):
        w = rng.dirichlet(np.ones(n))
        assert abs((c @ w) @ (c @ w) - w @ cov @ w) <= 1e-12
        worst_wrong = max(worst_wrong, abs((c.T @ w) @ (c.T @ w) - w @ cov @ w))
    assert worst_wrong > 1e-8  # the orientation matters


@pytest.mark.parametrize(("n", "seed"), [(2, 3602), (5, 3605), (12, 3612), (23, 3623), (30, 3630)])
def test_frontier_on_random_menus(n, seed):
    mu, cov, lo, hi = _menu(n, seed)
    nx = 48 if n == 23 else 14
    front = frontier(MenuPrograms(mu, cov, lo, hi), nx=nx)
    assert front.x.shape == (nx,) and front.y.shape == (nx,) and front.w.shape == (nx, n)
    top = greedy_fill(mu, lo, hi)
    assert abs(front.x[0] - _own_min_variance(cov, lo, hi)) <= TOL
    assert front.x[-1] == _sigma(top, cov) and np.array_equal(front.w[-1], top)
    assert np.abs(front.x - np.linspace(front.x[0], front.x[-1], nx)).max() <= 1e-12
    assert front.x[-1] - front.x[0] > 1e-4
    assert front.pinned.tolist() == [True] + [False] * (nx - 1)
    sigma = np.array([_sigma(w, cov) for w in front.w])
    assert (sigma <= front.x + TOL).all()
    assert np.abs(sigma - front.x)[:-1].max() <= TOL  # every node below sigma_max is on its ceiling
    assert front.y.tolist() == [float(mu @ w) for w in front.w]
    assert (np.diff(front.y) >= -1e-9).all() and front.y[-1] - front.y[0] > 1e-6
    assert all(_feasible(w, lo, hi) for w in front.w)
    # no feasible mix under a ceiling earns more than the node on it
    rng = np.random.default_rng(seed)
    judged = 0
    for j in range(nx):
        for _ in range(30):
            vertex = greedy_fill(rng.normal(size=n), lo, hi)
            share = rng.uniform()
            other = share * front.w[rng.integers(0, nx)] + (1.0 - share) * vertex
            assert _feasible(other, lo, hi)
            if _sigma(other, cov) <= front.x[j]:
                assert mu @ other <= front.y[j] + 1e-7
                judged += 1
    assert judged > nx


def test_frontier_point_and_cell_solve_their_programs():
    mu, cov, lo, hi = _menu(8, 3608)
    programs = MenuPrograms(mu, cov, lo, hi)
    front = frontier(programs, nx=9)
    x, y_front = float(front.x[5]), float(front.y[5])
    assert np.abs(programs.frontier_point(x) - front.w[5]).max() <= 1e-9  # deterministic
    floor = y_front - 0.4 * (y_front - front.y[0])
    w = programs.cell(x, floor)
    assert _feasible(w, lo, hi) and _sigma(w, cov) <= x + TOL and mu @ w >= floor - TOL
    assert w @ w < front.w[5] @ front.w[5] - 1e-6  # really less concentrated than the frontier mix
    v = cp.Variable(8)
    constraints: list = [cp.sum(v) == 1, v >= lo, v <= hi, mu @ v >= floor]
    constraints.append(cp.quad_form(v, cp.psd_wrap(cov)) <= x**2)
    own = cp.Problem(cp.Minimize(cp.sum_squares(v)), constraints)
    own.solve(solver=cp.CLARABEL, tol_feas=1e-10, tol_gap_abs=1e-10, tol_gap_rel=1e-10)
    assert abs(w @ w - own.value) <= 1e-7 and np.abs(w - v.value).max() <= 1e-4
    # a floor nobody has to reach leaves the least concentrated mix under the ceiling
    slack = programs.cell(x, -1.0)
    assert slack @ slack <= w @ w + 1e-9
    assert np.abs(programs.cell(x, -2.0) - slack).max() <= 1e-6
    assert programs.sigma(w) == _sigma(w, cov)


def test_infeasible_program_raises_and_names_what_failed():
    mu, cov, lo, hi = _menu(6, 3606)
    programs = MenuPrograms(mu, cov, lo, hi)
    floor_risk = programs.sigma(programs.min_variance())
    with pytest.raises(SolveError, match=r"frontier point at risk .* infeasible"):
        programs.frontier_point(0.5 * floor_risk)
    with pytest.raises(SolveError, match=r"cell at risk .*, return floor .* infeasible"):
        programs.cell(2.0 * floor_risk, 10.0)


class _FlakyProblem:
    """Stands in for a cvxpy problem: fails as scripted, then reports a status."""

    def __init__(self, script: list[object]):
        self.script = list(script)
        self.calls: list[dict] = []
        self.status = "never solved"

    def solve(self, **options):
        self.calls.append(options)
        outcome = self.script.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        self.status = outcome


class _Value:
    value = np.array([0.25, 0.75])


def test_solver_settings_and_the_retry_ladder():
    assert optimize.SOLVER_OPTIONS == {
        "tol_feas": 1e-8,
        "tol_gap_abs": 1e-8,
        "tol_gap_rel": 1e-8,
        "direct_solve_method": "qdldl",
    }
    assert optimize.RETRY_OPTIONS[0] == {} and len(optimize.RETRY_OPTIONS) == 3
    flaky = _FlakyProblem([cp.SolverError("numerical trouble"), "optimal_inaccurate", "optimal"])
    w = optimize._solve(flaky, _Value(), "a test program")
    assert w.tolist() == [0.25, 0.75] and len(flaky.calls) == 3
    for call, extra in zip(flaky.calls, optimize.RETRY_OPTIONS, strict=True):
        base = {"solver": cp.CLARABEL, "warm_start": False}
        assert call == {**base, **optimize.SOLVER_OPTIONS, **extra}
    tight = _FlakyProblem(["optimal"])
    optimize._solve(tight, _Value(), "a test program", 1e-10)
    assert tight.calls[0]["tol_feas"] == tight.calls[0]["tol_gap_abs"] == 1e-10
    assert (
        tight.calls[0]["tol_gap_rel"] == 1e-10 and tight.calls[0]["direct_solve_method"] == "qdldl"
    )
    never = _FlakyProblem([cp.SolverError("x"), "optimal_inaccurate", "user_limit"])
    with pytest.raises(SolveError, match="a test program: no optimal solution .* user_limit"):
        optimize._solve(never, _Value(), "a test program")
    assert len(never.calls) == 3


def _near_tied_menu(gap: float):
    """Four funds whose two best differ in expected return by `gap`: a nearly flat frontier."""
    mu = np.array([0.03, 0.05, 0.08, 0.08 + gap])
    cov = np.diag([0.03, 0.08, 0.15, 0.22]) ** 2 + 0.0004
    return mu, cov, np.zeros(4), np.full(4, 0.75)


def _inside(front, cov) -> np.ndarray:
    """How far each node below sigma_max sits inside its ceiling."""
    return (front.x - np.array([_sigma(w, cov) for w in front.w]))[:-1]


def test_nodes_on_a_nearly_flat_frontier_are_refined_onto_their_ceilings(monkeypatch):
    mu, cov, lo, hi = _near_tied_menu(1e-7)
    front = frontier(MenuPrograms(mu, cov, lo, hi))
    assert np.abs(_inside(front, cov)).max() <= TOL
    assert (np.diff(front.y) >= -1e-9).all() and all(_feasible(w, lo, hi) for w in front.w)
    # at 1e-8 alone the same nodes sit well inside: the return they give up is below tolerance
    assert optimize.REFINE_TOLERANCES == (1e-10, 1e-12)
    monkeypatch.setattr(optimize, "REFINE_TOLERANCES", ())
    plain = frontier(MenuPrograms(mu, cov, lo, hi))
    assert _inside(plain, cov).max() > 20 * TOL
    assert np.abs(plain.y - front.y).max() <= 1e-8  # the same frontier in return terms


def test_refinement_is_best_effort(monkeypatch):
    mu, cov, lo, hi = _near_tied_menu(1e-7)
    real = optimize._solve

    def only_at_base_tolerance(problem, variable, what, tolerance=1e-8):
        if tolerance < 1e-8:
            raise SolveError(f"{what}: no optimal solution at {tolerance}")
        return real(problem, variable, what, tolerance)

    monkeypatch.setattr(optimize, "_solve", only_at_base_tolerance)
    front = frontier(MenuPrograms(mu, cov, lo, hi))  # a failed refinement keeps the 1e-8 answer
    assert _inside(front, cov).max() > 20 * TOL and all(_feasible(w, lo, hi) for w in front.w)


def test_exactly_tied_top_funds_leave_nodes_inside_their_ceilings():
    """With a tie the highest return is reached below sigma_max: there is no ceiling to sit on."""
    mu = np.array([0.03, 0.05, 0.08, 0.08])
    cov = np.diag([0.03, 0.08, 0.22, 0.15]) ** 2 + 0.0004  # the riskier tied fund comes first
    lo, hi = np.zeros(4), np.full(4, 0.75)
    front = frontier(MenuPrograms(mu, cov, lo, hi))
    assert np.array_equal(front.w[-1], [0.0, 0.0, 0.75, 0.25])  # greedy fill, in menu order
    sigma = np.array([_sigma(w, cov) for w in front.w])
    assert (sigma <= front.x + TOL).all() and (np.diff(front.y) >= -1e-9).all()
    assert all(_feasible(w, lo, hi) for w in front.w)
    plateau = np.flatnonzero(front.y >= front.y[-1] - 1e-8)
    assert len(plateau) > 5 and _inside(front, cov)[plateau[:-1]].max() > 1e-3
    assert np.abs(_inside(front, cov)[: plateau[0]]).max() <= TOL  # below it, risk binds


def test_a_menu_with_one_possible_mix_is_a_single_point():
    mu, cov = np.array([0.03, 0.05, 0.08, 0.06]), np.diag([0.02, 0.05, 0.16, 0.10]) ** 2
    pinned = np.array([0.4, 0.3, 0.2, 0.1])
    front = frontier(MenuPrograms(mu, cov, pinned, pinned), nx=6)
    assert np.array_equal(front.w, np.tile(pinned, (6, 1)))
    assert np.array_equal(front.x, np.full(6, _sigma(pinned, cov)))
    assert np.abs(front.y - mu @ pinned).max() <= 1e-15 and not front.pinned.any()


def test_bad_arguments_are_refused():
    mu, cov, lo, hi = _menu(4, 3604)
    with pytest.raises(ValueError, match="at least 2 columns"):
        frontier(MenuPrograms(mu, cov, lo, hi), nx=1)
    with pytest.raises(ValueError, match="same number of funds"):
        MenuPrograms(mu, cov, lo[:3], hi)
    with pytest.raises(ValueError, match="same number of funds"):
        MenuPrograms(mu, cov[:3, :3], lo, hi)
