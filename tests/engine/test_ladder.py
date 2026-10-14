"""Fixed-risk ENB maximization: the entropy and its gradient, the pool, peaks and ladders."""

from __future__ import annotations

import numpy as np
import pytest

from portfoliosight.engine import ladder
from portfoliosight.engine.ladder import (
    Candidate,
    EnbProgram,
    Pool,
    bet_entropy,
    column,
    open_columns,
    peak_pools,
    random_start,
    spread_peaks,
)
from portfoliosight.engine.optimize import MenuPrograms, frontier
from portfoliosight.engine.torsion import torsion_basis
from tests.engine.helpers import Menu

TOL = 1e-6


@pytest.fixture(scope="module", params=[(5, 3805), (12, 3812)], ids=["n5", "n12"])
def menu(request) -> Menu:
    return Menu(*request.param)


@pytest.fixture(scope="module")
def pools(menu) -> list[Pool]:
    return peak_pools(menu.program, menu.programs, menu.front)


def _candidate(y: float, z: float) -> Candidate:
    return Candidate(w=np.array([y, z]), y=y, z=z)


def test_entropy_is_ln_enb_and_its_gradient_is_the_derivative(menu):
    rng = np.random.default_rng(4201)
    for _ in range(5):
        w = rng.dirichlet(np.ones(menu.n))
        risk = menu.sigma(w)
        u = menu.program.bets(w, risk)
        assert abs(u @ u - 1.0) <= 1e-12  # |u| = sigma(w) / risk
        entropy, gradient = bet_entropy(u)
        assert abs(np.exp(entropy) - menu.enb(w)) <= 1e-10 * menu.enb(w)
        numeric = np.array(
            [
                (bet_entropy(u + 1e-6 * e)[0] - bet_entropy(u - 1e-6 * e)[0]) / 2e-6
                for e in np.eye(menu.n)
            ]
        )
        assert np.abs(numeric - gradient).max() <= 1e-8
        assert abs(gradient @ u) <= 1e-12  # scaling u changes nothing
        assert abs(bet_entropy(3.0 * u)[0] - entropy) <= 1e-12


def test_entropy_handles_a_bet_with_no_share():
    entropy, gradient = bet_entropy(np.array([0.6, 0.0, 0.8]))
    shares = np.array([0.36, 0.64])
    assert abs(entropy + (shares * np.log(shares)).sum()) <= 1e-15
    assert gradient[1] == 0.0 and np.isfinite(gradient).all()
    assert bet_entropy(np.array([0.0, 2.0]))[0] == 0.0  # one bet: ENB = 1


def test_equal_shares_is_the_unconstrained_maximum():
    """Uncorrelated funds, no caps in the way: the peak splits risk evenly, ENB = N."""
    sigma = np.array([0.05, 0.10, 0.20, 0.15])
    cov = np.diag(sigma**2)
    program = EnbProgram(np.zeros(4), cov, np.zeros(4), np.ones(4), torsion_basis(cov))
    even = (1.0 / sigma) / (1.0 / sigma).sum()  # equal risk shares
    risk = program.sigma(even)
    found = program.solve(risk, None, np.array([0.4, 0.3, 0.1, 0.2]))
    assert found is not None and abs(found.z - 4.0) <= 1e-8
    assert np.abs(found.w - even).max() <= 1e-4
    assert program.bets(even, risk) == pytest.approx(np.full(4, 0.5), abs=1e-12)


def test_a_solved_mix_sits_on_its_risk_line_and_earns_its_floor(menu):
    j = menu.nx // 2
    risk, top = float(menu.front.x[j]), menu.front.w[j]
    peak = menu.program.solve(risk, None, top)
    assert peak is not None and peak.z > menu.enb(top) + 1e-3
    assert menu.feasible(peak.w, 1e-8) and abs(menu.sigma(peak.w) - risk) <= 1e-8
    assert peak.y == float(menu.mu @ peak.w) and peak.z == menu.enb(peak.w)
    floor = 0.5 * (menu.front.y[j] + peak.y)
    level = menu.program.solve(risk, floor, top)
    assert level is not None and level.y >= floor - 1e-8
    assert abs(menu.sigma(level.w) - risk) <= 1e-8 and menu.feasible(level.w, 1e-8)
    assert menu.enb(top) < level.z < peak.z  # the floor costs diversification
    again = menu.program.solve(risk, floor, top)
    assert again is not None and np.array_equal(again.w, level.w)  # deterministic


def test_an_answer_off_the_line_or_out_of_bounds_is_not_a_candidate(menu):
    risk = float(menu.front.x[3])
    good = menu.front.w[3]
    assert menu.program.feasible(good, risk, None) is (abs(menu.sigma(good) - risk) <= 1e-8)
    on_line = menu.program.solve(risk, None, good)
    assert on_line is not None and menu.program.feasible(on_line.w, risk, None)
    assert not menu.program.feasible(on_line.w, 1.01 * risk, None)  # another risk line
    assert not menu.program.feasible(on_line.w, risk, on_line.y + 1e-6)  # below the floor
    assert menu.program.feasible(on_line.w, risk, on_line.y - 1e-6)
    assert not menu.program.feasible(np.full(menu.n, np.nan), risk, None)
    outside = on_line.w.copy()
    outside[0] += 1e-6
    assert not menu.program.feasible(outside, risk, None)
    # a risk no mix of the menu has: the solver's answer is refused, not kept
    assert menu.program.solve(0.2 * float(menu.front.x[0]), None, good) is None


def test_pool_keeps_the_best_that_earns_the_floor():
    top = _candidate(0.10, 2.0)
    pool = Pool(top)
    assert pool.top is top and pool.best() is top and pool.best(0.10) is top
    pool.add(None)
    assert pool.members == [top]
    mid, low, tied = _candidate(0.08, 3.0), _candidate(0.05, 4.0), _candidate(0.07, 3.0)
    for member in (mid, low, tied):
        pool.add(member)
    assert pool.best() is low and pool.best(0.05) is low
    assert pool.best(0.06) is mid  # the tie at 3.0 stays with the member found first
    assert pool.best(0.09) is top  # nothing else earns that much
    assert pool.best(0.08 + 5e-9) is mid  # a floor is met within the solver's tolerance
    # a mix that claims more than the frontier's return is not one the ladder can use
    pool.add(_candidate(0.10 + 1e-6, 9.0))
    assert pool.best() is low
    equal = _candidate(0.10 + 5e-9, 5.0)  # the frontier's return, within the tolerance
    pool.add(equal)
    assert pool.best() is equal and pool.best(0.10) is equal


def test_pool_best_never_falls_as_the_floor_falls():
    rng = np.random.default_rng(4202)
    for _ in range(200):
        pool = Pool(_candidate(1.0, float(rng.uniform(1, 2))))
        for _ in range(int(rng.integers(1, 12))):
            pool.add(_candidate(float(rng.uniform(0, 1)), float(rng.choice([1.5, 2.5, 3.0, 4.0]))))
        floors = np.sort(rng.uniform(0, 1, 8))[::-1]
        chosen = [pool.best(float(floor)) for floor in floors]
        assert (np.diff([member.z for member in chosen]) >= 0).all()
        assert (np.diff([member.y for member in chosen]) <= 0).all()
        assert all(member.y >= floor - 1e-8 for member, floor in zip(chosen, floors, strict=True))


def test_random_start_is_on_the_risk_line_inside_the_bounds(menu):
    lowest, top = menu.front.w[0], menu.front.w[-1]
    for j in range(1, menu.nx):
        risk = float(menu.front.x[j])
        rng = np.random.default_rng([7, j])
        first = random_start(rng, menu.program, risk, lowest, top)
        assert menu.feasible(first, 1e-12) and abs(menu.sigma(first) - risk) <= 1e-12
        same = random_start(np.random.default_rng([7, j]), menu.program, risk, lowest, top)
        assert np.array_equal(first, same)  # a fixed seed gives a fixed start
        other = random_start(rng, menu.program, risk, lowest, top)
        assert not np.array_equal(first, other)


def test_random_start_reaches_the_line_from_either_side():
    """Too calm a draw moves toward the top of the frontier, too risky a one toward the bottom."""
    mu = np.array([0.02, 0.04, 0.06, 0.09])
    cov = np.diag([0.02, 0.06, 0.12, 0.25]) ** 2
    lo, hi = np.zeros(4), np.ones(4)
    programs = MenuPrograms(mu, cov, lo, hi)
    front = frontier(programs, nx=8)
    program = EnbProgram(mu, cov, lo, hi, torsion_basis(cov))
    lowest, top = front.w[0], front.w[-1]
    sides = set()
    for j in (1, 4, 7):
        risk = float(front.x[j])
        for seed in range(6):
            draw = np.mean(
                [
                    ladder.greedy_fill(row, lo, hi)
                    for row in np.random.default_rng(seed).random((ladder.RANDOM_VERTICES, 4))
                ],
                axis=0,
            )
            start = random_start(np.random.default_rng(seed), program, risk, lowest, top)
            assert abs(program.sigma(start) - risk) <= 1e-12 and abs(start.sum() - 1.0) <= 1e-12
            assert (start >= -1e-15).all()
            calm = program.sigma(draw) < risk
            sides.add(calm)
            other_end = top if calm else lowest
            share = (start - draw) @ (other_end - draw) / ((other_end - draw) @ (other_end - draw))
            assert -1e-9 <= share <= 1.0 + 1e-9  # on the segment between the draw and that end
    assert sides == {True, False}


def test_peaks_are_at_least_the_frontier_mix_and_the_first_column_is_alone(menu, pools):
    assert open_columns(menu.programs, menu.front) == list(range(1, menu.nx))
    assert len(pools) == menu.nx and len(pools[0].members) == 1
    gains = 0
    for j, pool in enumerate(pools):
        assert np.array_equal(pool.top.w, menu.front.w[j]) and pool.top.z == menu.enb(pool.top.w)
        best = pool.best()
        assert best.z >= pool.top.z and best.y <= pool.top.y + 1e-8
        assert abs(menu.sigma(best.w) - menu.front.x[j]) <= TOL and menu.feasible(best.w)
        gains += best.z > pool.top.z + 1e-3
    assert gains >= menu.nx - 2
    again = peak_pools(menu.program, menu.programs, menu.front)
    for first, second in zip(pools, again, strict=True):
        assert np.array_equal(first.best().w, second.best().w)  # deterministic
    # other random starts may settle on another optimum, never on a much worse one
    seeded = peak_pools(menu.program, menu.programs, menu.front, seed=1)
    for first, second in zip(pools, seeded, strict=True):
        assert abs(first.best().z - second.best().z) <= 0.05 * first.best().z


def test_spreading_carries_a_better_peak_to_the_columns_beside_it(menu, pools):
    """A column left with only its frontier mix gets its neighbours' optimum back."""
    bare = [Pool(pool.top) for pool in pools]
    donor = menu.nx // 2
    bare[donor].add(pools[donor].best())
    gained = spread_peaks(menu.program, menu.programs, menu.front, bare)
    has_more = {j for j in range(1, menu.nx) if pools[j].best().z > pools[j].top.z + 1e-3}
    assert donor in has_more and set(gained) >= has_more - {donor} and len(gained) >= 4
    for j in gained:
        assert bare[j].best().z > bare[j].top.z + TOL
        assert abs(bare[j].best().z - pools[j].best().z) <= 2e-2 * pools[j].best().z
    assert spread_peaks(menu.program, menu.programs, menu.front, bare) == []  # nothing left to gain


def test_ladder_runs_from_the_frontier_mix_to_the_peak(menu, pools):
    walked = 0
    for j in range(1, menu.nx):
        risk = float(menu.front.x[j])
        pool = Pool(pools[j].top)
        pool.add(pools[j].best())
        col = column(menu.program, risk, pool, levels=5)
        assert col.w.shape == (7, menu.n) and col.y.shape == col.z.shape == (7,)
        assert col.hop.shape == (6,) and col.hop.dtype == bool
        assert np.array_equal(col.w[0], menu.front.w[j]) and col.y[0] == menu.front.y[j]
        assert (np.diff(col.z) >= 0).all() and (np.diff(col.y) <= 1e-8).all()
        floors = np.linspace(col.y[0], col.y[-1], 7)
        for level in range(7):
            mix = col.w[level]
            assert abs(menu.sigma(mix) - risk) <= TOL and menu.feasible(mix)
            assert col.y[level] == float(menu.mu @ mix) >= floors[level] - 1e-8
            assert col.z[level] == menu.enb(mix)
        if col.collapsed:
            assert pools[j].best().z <= pools[j].top.z + TOL
            continue
        assert col.z[-1] == max(member.z for member in pool.members)  # the peak is the pool's best
        assert col.z[-1] > col.z[0] + 1e-3 and len({tuple(mix) for mix in col.w}) >= 5
        walked += 1
    assert walked >= menu.nx - 3


def test_a_ladder_that_finds_a_better_peak_is_laid_out_again(menu, pools):
    """Handed a poor peak far down the risk line, the levels find a better one above it."""
    j = menu.nx // 2
    risk, top, real = float(menu.front.x[j]), pools[j].top, pools[j].best()
    # what a peak search stuck in a poor optimum would hand over: little ENB for a lot of return
    poor = Candidate(w=real.w, y=real.y - 0.01, z=top.z + 0.05)
    pool = Pool(top)
    pool.add(poor)
    assert pool.best() is poor
    col = column(menu.program, risk, pool, levels=4)
    assert col.z[-1] > poor.z + 0.1 and col.y[-1] > poor.y + 1e-3  # a better peak, higher up
    assert col.z[-1] == max(member.z for member in pool.members)
    assert abs(col.z[-1] - real.z) <= 0.05 * real.z
    assert (np.diff(col.z) >= 0).all() and (np.diff(col.y) <= 1e-8).all()
    floors = np.linspace(col.y[0], col.y[-1], 6)  # the levels of the second layout
    assert (col.y >= floors - 1e-8).all()
    assert len({tuple(mix) for mix in col.w}) >= 4  # solved for, not copied from the first try
    assert poor.y not in col.y  # the poor mix is below every level and is in none of them


def test_a_column_with_nothing_better_than_its_frontier_mix_is_collapsed(menu):
    risk = float(menu.front.x[0])
    top = menu.program.candidate(menu.front.w[0])
    col = column(menu.program, risk, Pool(top), levels=3)
    assert col.collapsed and not col.hop.any()
    assert all(np.array_equal(mix, menu.front.w[0]) for mix in col.w)
    assert (col.y == menu.front.y[0]).all() and (col.z == col.z[0]).all()
    with pytest.raises(ValueError, match="at least 1 level"):
        column(menu.program, risk, Pool(top), levels=0)


def test_a_gain_within_the_tolerance_is_no_gain():
    """One feasible mix only: whatever else the pool was handed, the column is collapsed."""
    mu, cov = np.array([0.03, 0.05, 0.08, 0.06]), np.diag([0.02, 0.05, 0.16, 0.10]) ** 2
    only = np.array([0.4, 0.3, 0.2, 0.1])
    program = EnbProgram(mu, cov, only, only, torsion_basis(cov))
    top = program.candidate(only)
    pool = Pool(top)
    pool.add(Candidate(w=only, y=top.y - 0.01, z=top.z + 1e-7))
    assert pool.best() is not top
    col = column(program, program.sigma(only), pool, levels=3)
    assert col.collapsed and all(np.array_equal(mix, only) for mix in col.w)
    assert (col.z == top.z).all() and (col.y == top.y).all()


def test_equal_expected_returns_leave_a_ladder_with_no_return_span():
    """Tied funds: the peak costs nothing, so it follows the frontier mix at every level."""
    mu, cov = np.full(3, 0.05), 0.04 * np.eye(3)
    lo, hi = np.zeros(3), np.ones(3)
    programs = MenuPrograms(mu, cov, lo, hi)
    front = frontier(programs, nx=6)
    program = EnbProgram(mu, cov, lo, hi, torsion_basis(cov))
    pools = peak_pools(program, programs, front)
    j = 5  # the top of the frontier is one fund; its risk line holds nothing but single funds
    assert np.array_equal(front.w[j], [1.0, 0.0, 0.0])
    assert column(program, float(front.x[j]), pools[j], levels=3).collapsed
    j = 3
    col = column(program, float(front.x[j]), pools[j], levels=3)
    assert not col.collapsed and col.z[-1] > col.z[0] + 1e-3
    assert np.abs(col.y - 0.05).max() <= 1e-8  # no return is given up
    assert np.array_equal(col.w[0], front.w[j])
    assert all(np.array_equal(mix, col.w[-1]) for mix in col.w[1:])
    assert (col.z[1:] == col.z[-1]).all()


def test_two_levels_that_cannot_be_blended_are_a_hop():
    """Near the top risk of three uncorrelated funds the risk line is in separate pieces."""
    mu = np.array([0.115, 0.132, 0.094])
    cov = np.diag([0.159, 0.200, 0.172]) ** 2
    lo, hi = np.zeros(3), np.full(3, 0.6)
    programs = MenuPrograms(mu, cov, lo, hi)
    front = frontier(programs, nx=24)
    program = EnbProgram(mu, cov, lo, hi, torsion_basis(cov))
    pools = peak_pools(program, programs, front)
    hops = smooth = 0
    for j in open_columns(programs, front):
        risk = float(front.x[j])
        col = column(program, risk, pools[j], levels=6)
        for level in range(6):
            upper, lower = col.w[level], col.w[level + 1]
            lost = 1.0 - program.sigma((upper + lower) / 2.0) / risk
            assert bool(col.hop[level]) == (lost > ladder.HOP_TOL)
            if np.array_equal(upper, lower):
                assert not col.hop[level]
            hops += bool(col.hop[level])
            smooth += not col.hop[level]
        assert (np.diff(col.z) >= 0).all() and (np.diff(col.y) <= 1e-8).all()
    assert hops >= 3 and smooth >= 50
