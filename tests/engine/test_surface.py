"""The diversification surface, the frontier curve, s_safe and the reference interpolation."""

from __future__ import annotations

import math

import cvxpy as cp
import numpy as np
import pytest

from portfoliosight.engine.caps import greedy_fill
from portfoliosight.engine.optimize import Frontier, MenuPrograms, frontier
from portfoliosight.engine.surface import (
    Surface,
    frontier_curve,
    interpolate,
    s_safe,
    surface,
)
from portfoliosight.engine.torsion import TorsionBasis, enb, torsion_basis

TOL = 1e-6
NX, NY = 14, 11


class Menu:
    """A solved random menu: programs, frontier, surface and the tensor-shaped view of them."""

    def __init__(self, n: int, seed: int, nx: int = NX, ny: int = NY):
        rng = np.random.default_rng(seed)
        load = rng.normal(0.0, 1.0, (n, 3)) * np.array([0.10, 0.05, 0.03]) + np.array([0.06, 0, 0])
        self.cov = load @ load.T + np.diag(rng.uniform(0.02, 0.10, n) ** 2)
        self.mu = rng.uniform(0.01, 0.10, n)
        self.lo = np.where(rng.random(n) < 0.5, rng.uniform(0.0, 0.3 / n, n), 0.0)
        self.hi = np.full(n, min(max(3.0 / n, 0.25), 1.0))
        self.n, self.nx, self.ny = n, nx, ny
        self.programs = MenuPrograms(self.mu, self.cov, self.lo, self.hi)
        self.basis: TorsionBasis = torsion_basis(self.cov)
        self.front: Frontier = frontier(self.programs, nx=nx)
        self.surf: Surface = surface(self.programs, self.front, self.basis, ny=ny)
        self.tensor = {
            "frontier": {"w": self.front.w.tolist(), "y": self.front.y.tolist()},
            "grid": {
                "w": [[None if c is None else c.tolist() for c in col] for col in self.surf.w],
                "y": self.surf.y.tolist(),
                "k_div": self.surf.k_div.tolist(),
            },
        }

    def sigma(self, w) -> float:
        return float(np.sqrt(w @ self.cov @ w))

    def enb(self, w) -> float:
        return enb(w, self.cov, self.basis)

    def cells(self):
        for j in range(self.nx):
            for k in range(self.ny):
                mix = self.surf.w[j][k]
                if mix is not None:
                    yield j, k, mix


@pytest.fixture(scope="module", params=[(5, 3805), (12, 3812)], ids=["n5", "n12"])
def menu(request) -> Menu:
    return Menu(*request.param)


def test_floors_run_from_the_lowest_fill_to_the_top_of_the_frontier(menu):
    lowest = greedy_fill(menu.mu, menu.lo, menu.hi, ascending=True)
    assert abs(menu.surf.y[0] - menu.mu @ lowest) <= 1e-15
    assert menu.surf.y[-1] == menu.front.y.max()
    assert (
        np.abs(menu.surf.y - np.linspace(menu.surf.y[0], menu.surf.y[-1], menu.ny)).max() <= 1e-15
    )


def test_cells_are_null_exactly_above_the_frontier_and_real_below(menu):
    feasible = nulls = 0
    for j in range(menu.nx):
        for k in range(menu.ny):
            mix, above = menu.surf.w[j][k], bool(menu.surf.y[k] > menu.front.y[j])
            assert (mix is None) == above and bool(np.isnan(menu.surf.z[j, k])) == above
            nulls += above
            feasible += not above
    assert feasible >= menu.nx and nulls >= 1 and feasible + nulls == menu.nx * menu.ny
    for j, k, mix in menu.cells():
        assert abs(mix.sum() - 1.0) <= TOL
        assert (mix >= menu.lo - TOL).all() and (mix <= menu.hi + TOL).all()
        assert menu.sigma(mix) <= menu.front.x[j] + TOL
        assert menu.mu @ mix >= menu.surf.y[k] - TOL
        assert menu.surf.z[j, k] == menu.enb(mix) and 1 - TOL <= menu.surf.z[j, k] <= menu.n + TOL


def test_herfindahl_is_monotone_across_the_grid(menu):
    herf = np.full((menu.nx, menu.ny), np.nan)
    for j, k, mix in menu.cells():
        herf[j, k] = mix @ mix
    for j in range(menu.nx):  # a higher floor shrinks the feasible set
        column = herf[j][~np.isnan(herf[j])]
        assert (np.diff(column) >= -TOL).all()
    for k in range(menu.ny):  # a higher ceiling enlarges it
        row = herf[:, k][~np.isnan(herf[:, k])]
        assert (np.diff(row) <= TOL).all()
    assert np.nanmax(herf) - np.nanmin(herf) > 1e-3  # the surface is not flat


def test_cells_match_an_independent_solve(menu):
    rng = np.random.default_rng(3899)
    solved = [(j, k, mix) for j, k, mix in menu.cells() if j > 0]
    for index in rng.choice(len(solved), size=6, replace=False):
        j, k, mix = solved[index]
        v = cp.Variable(menu.n)
        constraints: list = [cp.sum(v) == 1, v >= menu.lo, v <= menu.hi]
        constraints.append(menu.mu @ v >= menu.surf.y[k])
        constraints.append(cp.quad_form(v, cp.psd_wrap(menu.cov)) <= menu.front.x[j] ** 2)
        own = cp.Problem(cp.Minimize(cp.sum_squares(v)), constraints)
        own.solve(solver=cp.CLARABEL)  # another formulation of the same cell
        assert own.status == "optimal" and abs(mix @ mix - own.value) <= TOL


def test_minimum_risk_column_and_frontier_floors_hold_the_frontier_mix(menu):
    assert menu.front.pinned[0] and menu.surf.k_div[0] == -1
    for k in range(menu.ny):
        if menu.surf.y[k] <= menu.front.y[0]:
            assert np.array_equal(menu.surf.w[0][k], menu.front.w[0])
    top = int(np.argmax(menu.front.y))
    assert menu.surf.y[-1] == menu.front.y[top]
    assert np.array_equal(menu.surf.w[top][-1], menu.front.w[top])


def test_a_slack_floor_reuses_its_mix_and_ties_go_to_the_highest_return(menu):
    reused = 0
    for j in range(1, menu.nx):
        column = menu.surf.w[j]
        feasible = [k for k in range(menu.ny) if column[k] is not None]
        for upper, lower in zip(feasible[1:], feasible[:-1], strict=True):
            mix = column[upper]
            if menu.mu @ mix > menu.surf.y[upper] + TOL:  # the floor above was slack
                assert column[lower] is mix
                reused += 1
            else:
                assert column[lower] is not mix
        run = [k for k in feasible if column[k] is column[feasible[0]]]
        if len(run) > 1:  # the least concentrated mix under this ceiling, whatever the floor
            free = menu.programs.cell(float(menu.front.x[j]), -1.0)
            assert abs(column[run[0]] @ column[run[0]] - free @ free) <= TOL
            assert menu.surf.k_div[j] not in run[:-1]  # never a lower copy of the same mix
    assert reused > 0


def test_most_diversified_candidate_is_recomputed_exactly(menu):
    best_overall = -np.inf
    for j in range(menu.nx):
        candidates = [(menu.enb(menu.front.w[j]), menu.ny, -1)]
        candidates += [(menu.enb(mix), k, k) for jj, k, mix in menu.cells() if jj == j]
        top = max(value for value, _, _ in candidates)
        best_overall = max(best_overall, top)
        winner = max((c for c in candidates if c[0] == top), key=lambda c: c[1])  # highest return
        k_div = int(menu.surf.k_div[j])
        assert k_div == winner[2]
        assert menu.surf.enb_front[j] == candidates[0][0]
        if k_div == -1:
            assert menu.surf.y_div[j] == menu.front.y[j]
            assert np.array_equal(menu.surf.w_div[j], menu.front.w[j])
        else:
            assert menu.surf.y_div[j] == menu.surf.y[k_div] < menu.front.y[j]
            assert np.array_equal(menu.surf.w_div[j], menu.surf.w[j][k_div])
        assert menu.enb(menu.surf.w_div[j]) >= menu.surf.enb_front[j]
    assert menu.surf.enb_ref == best_overall
    assert (menu.surf.k_div >= 0).any()  # some column really has a more diversified mix


def test_frontier_curve_is_the_locus_of_interpolated_frontier_mixes(menu):
    sigma, mu = frontier_curve(menu.front.w, menu.mu, menu.cov)
    points = (menu.nx - 1) * 8 + 1
    assert sigma.shape == (points,) and mu.shape == (points,)
    for i in range(points):
        j = min(i // 8, menu.nx - 2)
        lam = i / 8.0 - j
        mix = (1.0 - lam) * menu.front.w[j] + lam * menu.front.w[j + 1]
        assert abs(sigma[i] - menu.sigma(mix)) <= 1e-12 * sigma[i]
        assert abs(mu[i] - menu.mu @ mix) <= 1e-12 * abs(mu[i])
    assert np.abs(sigma[::8] - menu.front.x)[:-1].max() <= TOL  # nodes sit on their ceilings
    assert np.abs(mu[::8] - menu.front.y).max() <= 1e-15
    between = sigma[4::8] - 0.5 * (menu.front.x[:-1] + menu.front.x[1:])
    assert (between <= 1e-9).all() and between.min() < -1e-9  # left of the chord: risk is convex
    coarse_sigma, _ = frontier_curve(menu.front.w, menu.mu, menu.cov, substeps=2)
    assert np.array_equal(coarse_sigma, sigma[::4])


def test_s_safe_is_the_rightmost_maximum_in_s_units(menu):
    sigma, mu = frontier_curve(menu.front.w, menu.mu, menu.cov)
    low = mu / 2.0 - 1.96 * sigma / math.sqrt(2.0)
    expected = int(np.flatnonzero(low == low.max())[-1])
    assert s_safe(sigma, mu) == expected / 8.0
    assert 0.0 <= s_safe(sigma, mu) <= menu.nx - 1
    # constructed curves: a plateau takes its right end, and the units follow the sub-steps
    flat_sigma = np.zeros(9)
    assert s_safe(flat_sigma, np.array([0.0, 2, 4, 4, 4, 3, 2, 1, 0.0])) == 4 / 8.0
    assert s_safe(flat_sigma, np.array([0.0, 2, 4, 4, 4, 3, 2, 1, 0.0]), substeps=4) == 1.0
    assert s_safe(flat_sigma, np.full(9, 0.03)) == 1.0  # one point: the slider has no domain
    rising = np.linspace(0.02, 0.2, 9)
    assert s_safe(rising, 0.3 * rising) == 0.0  # low falls with risk: the safest end is s = 0
    assert s_safe(rising, 3.0 * rising) == 1.0


def test_interpolation_reproduces_the_ends_and_keeps_every_invariant(menu):
    rng = np.random.default_rng(3811)
    w_front, w_div = menu.front.w, menu.surf.w_div
    for s in [0.0, 0.5, 3.25, menu.nx - 1.5, float(menu.nx - 1), *rng.uniform(0, menu.nx - 1, 20)]:
        j = min(int(math.floor(s)), menu.nx - 2)
        lam = s - j
        top = (1.0 - lam) * w_front[j] + lam * w_front[j + 1]
        bottom = (1.0 - lam) * w_div[j] + lam * w_div[j + 1]
        assert np.abs(interpolate(menu.tensor, s, 0.0) - top).max() <= 1e-15
        assert np.abs(interpolate(menu.tensor, s, 1.0) - bottom).max() <= 1e-12
    for _ in range(200):
        s, t = rng.uniform(0, menu.nx - 1), rng.uniform()
        j = min(int(math.floor(s)), menu.nx - 2)
        lam = s - j
        mix = interpolate(menu.tensor, s, t)
        assert abs(mix.sum() - 1.0) <= TOL
        assert (mix >= menu.lo - TOL).all() and (mix <= menu.hi + TOL).all()
        ceiling = (1.0 - lam) * menu.front.x[j] + lam * menu.front.x[j + 1]
        assert menu.sigma(mix) <= ceiling + TOL
        assert 1 - TOL <= menu.enb(mix) <= menu.n + TOL


def test_interpolation_walks_each_ladder_by_return_floor(menu):
    j = int(np.argmax(menu.front.y - menu.surf.y_div))  # the longest ladder
    k_div = int(menu.surf.k_div[j])
    assert k_div >= 0
    span = menu.front.y[j] - menu.surf.y_div[j]
    rungs = [k for k in range(menu.ny - 1, k_div - 1, -1) if menu.surf.w[j][k] is not None]
    for k in rungs:  # at a rung's own floor the mix is that cell
        t = min(max((menu.front.y[j] - menu.surf.y[k]) / span, 0.0), 1.0)
        if t > 0.0:
            assert np.abs(interpolate(menu.tensor, float(j), t) - menu.surf.w[j][k]).max() <= 1e-9
    upper, lower = rungs[-2], rungs[-1]  # halfway between two rungs: their midpoint
    t_mid = (menu.front.y[j] - 0.5 * (menu.surf.y[upper] + menu.surf.y[lower])) / span
    expected = 0.5 * (menu.surf.w[j][upper] + menu.surf.w[j][lower])
    assert np.abs(interpolate(menu.tensor, float(j), t_mid) - expected).max() <= 1e-9
    moved = interpolate(menu.tensor, float(j), 1.0) - interpolate(menu.tensor, float(j), 0.0)
    assert np.abs(moved).max() > 1e-3


def test_collapsed_ladders_are_constant_in_t(menu):
    tensor = {
        "frontier": menu.tensor["frontier"],
        "grid": {**menu.tensor["grid"], "k_div": [-1] * menu.nx},
    }
    for s in (0.0, 2.5, menu.nx - 1.0):
        reference = interpolate(tensor, s, 0.0)
        for t in (0.25, 0.5, 1.0):
            assert np.array_equal(interpolate(tensor, s, t), reference)
    assert menu.surf.k_div[0] == -1  # the real minimum-risk column is collapsed too
    for t in (0.0, 0.4, 1.0):
        assert np.array_equal(interpolate(menu.tensor, 0.0, t), menu.front.w[0])


def test_positions_outside_the_grid_are_refused(menu):
    for s, t in ((-0.1, 0.5), (menu.nx - 0.9, 0.5), (1.0, -0.01), (1.0, 1.01), (float("nan"), 0.5)):
        with pytest.raises(ValueError, match="outside"):
            interpolate(menu.tensor, s, t)


def test_a_single_mix_menu_has_a_flat_surface():
    mu, cov = np.array([0.03, 0.05, 0.08, 0.06]), np.diag([0.02, 0.05, 0.16, 0.10]) ** 2
    only = np.array([0.4, 0.3, 0.2, 0.1])
    programs = MenuPrograms(mu, cov, only, only)
    front = frontier(programs, nx=5)
    surf = surface(programs, front, torsion_basis(cov), ny=4)
    assert np.abs(surf.y - mu @ only).max() <= 1e-15 and (surf.k_div == -1).all()
    cells = [cell for column in surf.w for cell in column if cell is not None]
    assert len(cells) == 5 * 4 and all(np.array_equal(cell, only) for cell in cells)
    assert np.array_equal(surf.w_div, front.w) and np.array_equal(surf.y_div, front.y)
    sigma, curve_mu = frontier_curve(front.w, mu, cov)
    assert s_safe(sigma, curve_mu) == 4.0  # equal to s_max: the slider is disabled
    with pytest.raises(ValueError, match="at least 2 rows"):
        surface(programs, front, torsion_basis(cov), ny=1)


def test_tied_returns_do_not_break_the_surface():
    """With equal expected returns the frontier mix is not the only one at its own return."""
    mu, cov = np.full(3, 0.05), 0.04 * np.eye(3)
    programs = MenuPrograms(mu, cov, np.zeros(3), np.ones(3))
    front = frontier(programs, nx=8)
    surf = surface(programs, front, torsion_basis(cov), ny=5)
    herf = np.array([[np.nan if c is None else c @ c for c in column] for column in surf.w])
    # every return is the same up to rounding, so rounding decides which cells exist; each one
    # that does holds the least concentrated mix, not a copy of an arbitrary frontier mix
    assert np.count_nonzero(~np.isnan(herf)) >= 1 and not np.isnan(herf[-1]).all()
    assert np.nanmax(np.abs(herf - 1.0 / 3.0)) <= 1e-5
    assert front.w[-1] @ front.w[-1] == 1.0  # while the top frontier mix is one fund
    for k in range(5):
        row = herf[:, k][~np.isnan(herf[:, k])]
        assert (np.diff(row) <= TOL).all()


def test_tied_top_funds_get_the_least_concentrated_top_mix():
    mu = np.array([0.08, 0.08, 0.05, 0.03, 0.02])
    cov = np.diag([0.2, 0.2, 0.1, 0.05, 0.03]) ** 2
    lo, hi = np.zeros(5), np.full(5, 0.6)
    programs = MenuPrograms(mu, cov, lo, hi)
    front = frontier(programs, nx=8)
    surf = surface(programs, front, torsion_basis(cov), ny=6)
    assert np.array_equal(front.w[-1], [0.6, 0.4, 0.0, 0.0, 0.0])  # the greedy fill, by menu order
    top = surf.w[-1][-1]  # the highest floor under the highest ceiling: solved, not copied
    assert top is not None and np.abs(top - [0.5, 0.5, 0.0, 0.0, 0.0]).max() <= 1e-3
    assert top @ top < front.w[-1] @ front.w[-1] - 1e-3
    assert mu @ top >= surf.y[-1] - TOL and programs.sigma(top) <= front.x[-1] + TOL
