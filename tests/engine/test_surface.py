"""The diversification surface, the raster, the frontier curve, s_safe and the interpolation."""

from __future__ import annotations

import math

import numpy as np
import pytest

from portfoliosight.engine import surface as surface_module
from portfoliosight.engine.ladder import EnbProgram, random_start
from portfoliosight.engine.optimize import MenuPrograms, frontier
from portfoliosight.engine.surface import (
    Raster,
    Surface,
    frontier_curve,
    interpolate,
    raster,
    s_safe,
    surface,
)
from portfoliosight.engine.torsion import torsion_basis
from tests.engine.helpers import Menu

TOL = 1e-6
NX, LEVELS, NY = 10, 5, 9


class Solved(Menu):
    """A menu with its surface and raster solved, and the tensor-shaped view the page reads."""

    def __init__(self, n: int, seed: int):
        super().__init__(n, seed, nx=NX)
        self.surf: Surface = surface(self.program, self.programs, self.front, levels=LEVELS)
        self.grid: Raster = raster(self.surf, self.front, self.program, ny=NY)
        self.tensor = {"ladder": {"w": self.surf.w.tolist(), "hop": self.surf.hop.tolist()}}


@pytest.fixture(scope="module", params=[(5, 3805), (12, 3812)], ids=["n5", "n12"])
def menu(request) -> Solved:
    return Solved(*request.param)


def _uncorrelated_menu(nx: int = 24) -> tuple[EnbProgram, MenuPrograms]:
    """Three uncorrelated funds capped at 60%: near the top risk the risk line is in pieces."""
    mu = np.array([0.115, 0.132, 0.094])
    cov = np.diag([0.159, 0.200, 0.172]) ** 2
    lo, hi = np.zeros(3), np.full(3, 0.6)
    return EnbProgram(mu, cov, lo, hi, torsion_basis(cov)), MenuPrograms(mu, cov, lo, hi)


def test_every_column_is_a_ladder_on_its_own_risk_line(menu):
    surf = menu.surf
    assert surf.w.shape == (NX, LEVELS + 2, menu.n)
    assert surf.y.shape == surf.z.shape == (NX, LEVELS + 2) and surf.hop.shape == (NX, LEVELS + 1)
    for j in range(NX):
        assert np.array_equal(surf.w[j, 0], menu.front.w[j]) and surf.y[j, 0] == menu.front.y[j]
        floors = np.linspace(surf.y[j, 0], surf.y[j, -1], LEVELS + 2)
        for level in range(LEVELS + 2):
            mix = surf.w[j, level]
            assert menu.feasible(mix) and abs(menu.sigma(mix) - menu.front.x[j]) <= TOL
            assert surf.y[j, level] == float(menu.mu @ mix) >= floors[level] - TOL
            assert surf.z[j, level] == menu.enb(mix) and 1 - TOL <= surf.z[j, level] <= menu.n + TOL


def test_enb_never_falls_and_return_never_rises_down_a_column(menu):
    assert (np.diff(menu.surf.z, axis=1) >= 0).all()
    assert (np.diff(menu.surf.y, axis=1) <= 1e-8).all()
    walked = ~menu.surf.collapsed
    assert walked.sum() >= NX - 3
    assert (menu.surf.z[walked, -1] > menu.surf.z[walked, 0] + 1e-3).all()
    assert (menu.surf.y[walked, -1] < menu.surf.y[walked, 0] - 1e-4).all()


def test_the_peak_is_the_most_diversified_mix_of_its_column(menu):
    surf = menu.surf
    assert (surf.z[:, -1] == surf.z.max(axis=1)).all()
    assert surf.enb_ref == surf.z.max() == surf.z[:, -1].max()
    lowest, top = menu.front.w[0], menu.front.w[-1]
    for j in range(1, NX):  # no random point of the risk line, solved from, does better
        risk = float(menu.front.x[j])
        rng = np.random.default_rng([99, j])
        for _ in range(3):
            found = menu.program.solve(
                risk, None, random_start(rng, menu.program, risk, lowest, top)
            )
            assert found is None or found.z <= surf.z[j, -1] * 1.05


def test_minimum_risk_column_is_collapsed(menu):
    surf = menu.surf
    assert surf.collapsed[0] and not surf.hop[0].any()
    assert all(np.array_equal(mix, menu.front.w[0]) for mix in surf.w[0])
    for j in np.flatnonzero(surf.collapsed):
        assert all(np.array_equal(mix, menu.front.w[j]) for mix in surf.w[j])
        assert (surf.z[j] == surf.z[j, 0]).all() and (surf.y[j] == menu.front.y[j]).all()


def test_surface_is_deterministic(menu):
    again = surface(menu.program, menu.programs, menu.front, levels=LEVELS)
    assert np.array_equal(again.w, menu.surf.w) and np.array_equal(again.z, menu.surf.z)
    assert np.array_equal(again.hop, menu.surf.hop) and again.enb_ref == menu.surf.enb_ref


def test_a_column_that_gains_from_its_neighbours_is_laid_out_again(menu, monkeypatch):
    calls = []
    real_column = surface_module.column

    def recording(program, risk, pool, levels):
        calls.append(risk)
        return real_column(program, risk, pool, levels)

    monkeypatch.setattr(surface_module, "column", recording)
    monkeypatch.setattr(surface_module, "spread_peaks", lambda *_: [2, 5])
    again = surface(menu.program, menu.programs, menu.front, levels=LEVELS)
    assert len(calls) == NX + 2 and calls[-2:] == [menu.front.x[2], menu.front.x[5]]
    assert (np.diff(again.z, axis=1) >= 0).all() and again.enb_ref >= menu.surf.enb_ref - 1e-9


def test_raster_resamples_the_ladders_on_shared_floors(menu):
    surf, grid = menu.surf, menu.grid
    assert grid.y[0] == surf.y[:, -1].min() and grid.y[-1] == menu.front.y.max()
    assert np.abs(grid.y - np.linspace(grid.y[0], grid.y[-1], NY)).max() <= 1e-15
    cells = blends = 0
    for j in range(NX):
        peak_y, front_y = surf.y[j, -1], surf.y[j, 0]
        bottom = max(k for k in range(NY) if grid.y[k] <= peak_y)
        assert grid.k_div[j] == (-1 if surf.collapsed[j] else bottom)
        assert grid.y_div[j] == (front_y if surf.collapsed[j] else grid.y[bottom])
        for k in range(NY):
            mix = grid.w[j][k]
            inside = bottom <= k and grid.y[k] <= front_y
            assert (mix is not None) == inside and bool(np.isnan(grid.z[j, k])) == (not inside)
            if mix is None:
                continue
            cells += 1
            assert menu.feasible(mix) and menu.sigma(mix) <= menu.front.x[j] + TOL
            assert menu.mu @ mix >= grid.y[k] - TOL and grid.z[j, k] == menu.enb(mix)
            if k == bottom:
                assert np.array_equal(mix, surf.w[j, -1])  # the bottom cell is the peak itself
                continue
            lower = int(np.argmax(surf.y[j] < grid.y[k]))  # the two levels around that return
            if surf.hop[j, lower - 1]:
                assert np.array_equal(mix, surf.w[j, lower - 1])
            else:
                assert abs(menu.mu @ mix - grid.y[k]) <= 1e-12  # the ladder at exactly that return
                share = (surf.y[j, lower - 1] - grid.y[k]) / (
                    surf.y[j, lower - 1] - surf.y[j, lower]
                )
                blend = (1.0 - share) * surf.w[j, lower - 1] + share * surf.w[j, lower]
                assert np.abs(mix - blend).max() <= 1e-15
                blends += 1
    assert cells >= NX and blends >= 5
    with pytest.raises(ValueError, match="at least 2 rows"):
        raster(surf, menu.front, menu.program, ny=1)


def test_raster_does_not_blend_across_a_hop():
    program, programs = _uncorrelated_menu()
    front = frontier(programs, nx=24)
    surf = surface(program, programs, front, levels=6)
    assert surf.hop.any() and not surf.hop.all()
    grid = raster(surf, front, program, ny=40)
    checked = 0
    for j in range(24):
        for k, mix in enumerate(grid.w[j]):
            if mix is None or k == grid.k_div[j] or surf.collapsed[j]:
                continue
            lower = int(np.argmax(surf.y[j] < grid.y[k]))
            if surf.hop[j, lower - 1]:
                assert np.array_equal(mix, surf.w[j, lower - 1])  # the upper level, unblended
                assert abs(program.sigma(mix) - front.x[j]) <= TOL
                checked += 1
    assert checked >= 3


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


def test_s_safe_is_the_rightmost_column_with_the_best_bad_year():
    assert s_safe([-0.05, -0.02, -0.03, -0.06]) == 1.0
    assert s_safe([-0.05, -0.02, -0.02, -0.06]) == 2.0  # a tie takes the right one
    assert s_safe([-0.01, -0.02, -0.04]) == 0.0  # the safest end is the first column
    assert s_safe([-0.09, -0.04, -0.01]) == 2.0  # equal to s_max: the slider has no domain
    assert s_safe(np.full(5, -0.03)) == 4.0
    assert isinstance(s_safe([-0.1, 0.0]), float)


def test_interpolation_reproduces_the_ends_and_keeps_every_invariant(menu):
    rng = np.random.default_rng(3811)
    surf = menu.surf
    for s in [0.0, 0.5, 3.25, NX - 1.5, float(NX - 1), *rng.uniform(0, NX - 1, 20)]:
        j = min(int(math.floor(s)), NX - 2)
        lam = s - j
        top = (1.0 - lam) * menu.front.w[j] + lam * menu.front.w[j + 1]
        bottom = (1.0 - lam) * surf.w[j, -1] + lam * surf.w[j + 1, -1]
        assert np.abs(interpolate(menu.tensor, s, 0.0) - top).max() <= 1e-15
        assert np.abs(interpolate(menu.tensor, s, 1.0) - bottom).max() <= 1e-15
    for j in range(NX):  # at a column and a level the mix is the stored one, exactly
        for level in range(LEVELS + 2):
            mix = interpolate(menu.tensor, float(j), level / (LEVELS + 1))
            assert np.abs(mix - surf.w[j, level]).max() <= 1e-15
    for _ in range(200):
        s, t = rng.uniform(0, NX - 1), rng.uniform()
        j = min(int(math.floor(s)), NX - 2)
        lam = s - j
        mix = interpolate(menu.tensor, s, t)
        ceiling = (1.0 - lam) * menu.front.x[j] + lam * menu.front.x[j + 1]
        assert menu.feasible(mix) and menu.sigma(mix) <= ceiling + TOL
        assert 1 - TOL <= menu.enb(mix) <= menu.n + TOL


def test_interpolation_blends_two_levels_and_stays_near_the_risk_line(menu):
    surf = menu.surf
    blended = 0
    for j in np.flatnonzero(~surf.collapsed):
        for level in range(LEVELS + 1):
            mix = interpolate(menu.tensor, float(j), (level + 0.5) / (LEVELS + 1))
            if surf.hop[j, level]:
                assert np.abs(mix - surf.w[j, level + 1]).max() <= 1e-15
                continue
            assert np.abs(mix - 0.5 * (surf.w[j, level] + surf.w[j, level + 1])).max() <= 1e-15
            assert menu.sigma(mix) >= 0.99 * menu.front.x[j]  # what "no hop" promises
            blended += 1
    assert blended >= 10
    j = int(np.argmax(surf.y[:, 0] - surf.y[:, -1]))  # the longest ladder
    moved = interpolate(menu.tensor, float(j), 1.0) - interpolate(menu.tensor, float(j), 0.0)
    assert np.abs(moved).max() > 1e-3
    for t in (0.0, 0.4, 1.0):  # the minimum-risk column is collapsed: one mix whatever t
        assert np.abs(interpolate(menu.tensor, 0.0, t) - menu.front.w[0]).max() <= 1e-15


def test_interpolation_hops_instead_of_blending_where_the_line_is_broken():
    program, programs = _uncorrelated_menu()
    front = frontier(programs, nx=24)
    surf = surface(program, programs, front, levels=6)
    tensor = {"ladder": {"w": surf.w.tolist(), "hop": surf.hop.tolist()}}
    hops = [(int(j), int(level)) for j, level in zip(*np.nonzero(surf.hop), strict=True)]
    assert hops
    for j, level in hops:
        upper, lower = surf.w[j, level], surf.w[j, level + 1]
        for share, expected in ((0.0, upper), (0.3, upper), (0.5, lower), (0.9, lower)):
            mix = interpolate(tensor, float(j), (level + share) / 7)
            assert np.abs(mix - expected).max() <= 1e-15
            assert abs(program.sigma(mix) - front.x[j]) <= TOL  # still on the risk line
        blend = 0.5 * (upper + lower)  # what a straight blend would have shown
        assert program.sigma(blend) < 0.99 * front.x[j]


def test_positions_outside_the_grid_are_refused(menu):
    for s, t in ((-0.1, 0.5), (NX - 0.9, 0.5), (1.0, -0.01), (1.0, 1.01), (float("nan"), 0.5)):
        with pytest.raises(ValueError, match="outside"):
            interpolate(menu.tensor, s, t)


def test_a_single_mix_menu_has_a_flat_surface():
    mu, cov = np.array([0.03, 0.05, 0.08, 0.06]), np.diag([0.02, 0.05, 0.16, 0.10]) ** 2
    only = np.array([0.4, 0.3, 0.2, 0.1])
    programs = MenuPrograms(mu, cov, only, only)
    front = frontier(programs, nx=5)
    program = EnbProgram(mu, cov, only, only, torsion_basis(cov))
    surf = surface(program, programs, front, levels=3)
    assert surf.collapsed.all() and not surf.hop.any()
    assert all(np.array_equal(mix, only) for column in surf.w for mix in column)
    grid = raster(surf, front, program, ny=4)
    assert np.abs(grid.y - mu @ only).max() <= 1e-15 and (grid.k_div == -1).all()
    assert np.array_equal(grid.y_div, front.y)
    cells = [cell for column in grid.w for cell in column if cell is not None]
    assert len(cells) >= 5 and all(np.array_equal(cell, only) for cell in cells)


def test_tied_returns_put_the_free_diversification_below_the_frontier_mix():
    """With equal expected returns the frontier mix is not the only one at its own return."""
    mu, cov = np.full(3, 0.05), 0.04 * np.eye(3)
    programs = MenuPrograms(mu, cov, np.zeros(3), np.ones(3))
    front = frontier(programs, nx=8)
    program = EnbProgram(mu, cov, np.zeros(3), np.ones(3), torsion_basis(cov))
    surf = surface(program, programs, front, levels=4)
    assert np.abs(surf.y - 0.05).max() <= 1e-8  # nothing costs any return
    assert (np.diff(surf.z, axis=1) >= 0).all()
    walked = np.flatnonzero(~surf.collapsed)
    assert len(walked) >= 4
    for j in walked:
        assert np.array_equal(surf.w[j, 0], front.w[j]) and surf.z[j, -1] > surf.z[j, 0] + 1e-3
        assert all(np.array_equal(mix, surf.w[j, -1]) for mix in surf.w[j, 1:])
        assert abs(program.sigma(surf.w[j, -1]) - front.x[j]) <= TOL
    grid = raster(surf, front, program, ny=5)  # one return: every floor is that return
    assert np.abs(grid.y - 0.05).max() <= 1e-8
