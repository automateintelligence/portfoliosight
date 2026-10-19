"""The shared candidate search of one experiment cell (protocol 3 and 5; plan 6b.4).

Fixtures are synthetic: `synthetic_model` (tests/research/helpers.py) draws seeded daily returns
with one common factor and fits them with the production estimators the protocol pins. Menu m4
has funds A..D capped at .60 (seed 7: its equal weight lies above X(.25)); m5 has five funds
capped at .60 and runs the protocol's default budgets end to end. Expectations come from oracles
written here: a breakpoint solution of the capped-simplex projection, cvxpy programs written with
a quadratic risk constraint for the anchors, scipy's Sobol engine seeded by hand, the greedy fill,
mixing segment and penalty arithmetic worked out by hand, DR² written out as
`(w'sigma)^2 / (w'Sigma w)`, and production's own tensor build for the sample digest. The
preference contract (`engine.preference`), the fixed-weight evaluation (`research.evaluate`) and
the minimum-torsion ENB are the pinned references, not the code under test.
"""

from __future__ import annotations

import functools
import hashlib
import math
from collections.abc import Sequence
from dataclasses import replace
from datetime import date

import cvxpy as cp
import numpy as np
import numpy.typing as npt
import pandas as pd
import pytest
from scipy.stats import qmc

from portfoliosight.data import store as store_mod
from portfoliosight.engine import measures, preference
from portfoliosight.engine.builder import build_tensor
from portfoliosight.engine.optimize import RETRY_OPTIONS, MenuPrograms, SolveError
from portfoliosight.engine.preference import Candidate
from portfoliosight.engine.torsion import TorsionError, effective_number_of_bets
from portfoliosight.jobs.build import inputs_from_store
from portfoliosight.research import evaluate as evaluation
from portfoliosight.research import search
from portfoliosight.research.evaluate import NONPOSITIVE_DAILY_GROWTH, OK, OriginModel, bank
from portfoliosight.research.search import (
    ANCHOR_INFEASIBLE,
    ANCHOR_UNSOLVED,
    CALL_BUDGET_EXHAUSTED,
    COMPUTATIONAL_ERROR,
    FAILED_ARM,
    FAILED_START,
    INFEASIBLE,
    INVALID_PROPOSAL,
    MIN_VARIANCE_UNSOLVED,
    PATH_SEEDS,
    PENALTY,
    PRIMARY_ALLOWANCE,
    TORSION_FAILED,
    UNDEFINED_MEASURE,
    W_MIN_INFEASIBLE,
    W_MIN_NONPOSITIVE_GROWTH,
    Budget,
    CellSearch,
    MdpProgram,
    assess,
    broad_candidate,
    constraint_values,
    objective,
    prepare,
    production_sample_digest,
    project_capped_simplex,
    risk_ceilings,
    run_arm,
    search_cell,
    select_starts,
)
from tests.research.helpers import synthetic_model

SEED = PATH_SEEDS[0]
FUNDS4 = ("A", "B", "C", "D")
CAPS4 = (0.6, 0.6, 0.6, 0.6)
FUNDS5 = ("G", "F", "C", "S", "I")
CAPS5 = (0.6,) * 5
SMALL = Budget(points=32, starts=3, calls=30, maxiter=30)
ANCHORS = (
    "min_variance",
    "equal_weight",
    "frontier_x25",
    "frontier_x50",
    "frontier_x100",
    "mdp_x25",
    "mdp_x50",
    "mdp_x100",
)
TOL = 1e-8


@functools.cache
def _m4() -> OriginModel:
    return synthetic_model(FUNDS4, 260, 7)


@functools.cache
def _m5() -> OriginModel:
    return synthetic_model(FUNDS5, 260, 5)


@functools.cache
def _cell(
    fraction: float = 0.5,
    order: tuple[str, ...] = ("R", "R+D"),
    budget: Budget = SMALL,
    arms: tuple[str, ...] = ("R", "R+D"),
) -> CellSearch:
    return search_cell(_m4(), CAPS4, fraction, SEED, arms=arms, order=order, budget=budget)


@functools.cache
def _defaults() -> CellSearch:
    """Protocol budgets end to end on the five-fund menu at X(.50)."""
    return search_cell(_m5(), CAPS5, 0.5, SEED)


# ------------------------------------------------------------------------------------ oracles


def _risk(weights: npt.ArrayLike | None, cov: np.ndarray) -> float:
    assert weights is not None
    w = np.asarray(weights, dtype=float)
    return float(np.sqrt(w @ cov @ w))


def _x(cell: CellSearch) -> float:
    """The cell's ceiling: set for every cell that got past its ceilings."""
    assert cell.ceiling is not None
    return cell.ceiling


def _feasible(
    weights: npt.ArrayLike | None, caps: Sequence[float], cov, ceiling: float | None
) -> bool:
    assert weights is not None and ceiling is not None
    w = np.asarray(weights, dtype=float)
    return bool(
        (w >= -TOL).all()
        and (w <= np.asarray(caps) + TOL).all()
        and abs(math.fsum(w.tolist()) - 1.0) <= TOL
        and _risk(w, cov) <= ceiling + TOL
    )


def _projection_oracle(z: np.ndarray, caps: np.ndarray) -> np.ndarray:
    """`clip(z - lam, 0, caps)` summing to 1, with `lam` found between sorted breakpoints."""

    def total(lam: float) -> float:
        return float(np.clip(z - lam, 0.0, caps).sum())

    points = sorted(set(np.concatenate([z, z - caps]).tolist()))
    for a, b in zip(points, points[1:], strict=False):
        ta, tb = total(a), total(b)
        if ta >= 1.0 >= tb:
            lam = a if ta == tb else a + (ta - 1.0) * (b - a) / (ta - tb)
            return np.clip(z - lam, 0.0, caps)
    raise AssertionError("no breakpoint bracket")


def _greedy_oracle(u: np.ndarray, caps: np.ndarray) -> np.ndarray:
    """Fill caps in descending u, ties in fund order, until the weights sum to 1."""
    w = np.zeros(len(u))
    rest = 1.0
    for i in sorted(range(len(u)), key=lambda k: (-u[k], k)):
        w[i] = min(caps[i], rest)
        rest -= w[i]
    return w


def _quadratic_program(model: OriginModel, caps, ceiling: float | None, objective) -> np.ndarray:
    """A cvxpy program in another form than production's: `quad_form(w, cov) <= X^2`."""
    n = len(model.funds)
    w = cp.Variable(n)
    cons = [cp.sum(w) == 1, w >= 0, w <= np.asarray(caps)]
    cov = cp.psd_wrap(model.moments.cov)
    if ceiling is None:
        problem = cp.Problem(cp.Minimize(cp.quad_form(w, cov)), cons)
    else:
        cons.append(cp.quad_form(w, cov) <= ceiling**2)
        problem = cp.Problem(cp.Maximize(objective @ w), cons)
    problem.solve(solver=cp.CLARABEL)
    assert problem.status == cp.OPTIMAL
    return np.asarray(w.value, dtype=float)


def _utility(row) -> float:
    return 0.60 * row.scored.bad + 0.30 * row.scored.typical + 0.10 * row.scored.good


def _figures(row) -> tuple[str, ...]:
    s = row.scored
    values = (s.bad, s.typical, s.good, s.utility, s.mean, s.es_25, s.risk)
    return (s.status, str(s.ruin_day), *(float(v).hex() for v in values))


def _ok_rows(rows):
    return [row for row in rows if row.scored.status == OK]


# --------------------------------------------------------------------------- ceilings (3)


def test_ceilings_are_the_protocol_risk_span() -> None:
    model = _m4()
    ceilings = risk_ceilings(model, CAPS4)
    w_min = _quadratic_program(model, CAPS4, None, None)
    # the minimum is flat: weights agree to the square root of the solvers' tolerance, risk tightly
    assert np.allclose(ceilings.w_min, w_min, atol=1e-4)
    assert ceilings.sigma_min == pytest.approx(_risk(w_min, model.moments.cov), abs=1e-9)
    top = _greedy_oracle(np.asarray(model.mu_s), np.asarray(CAPS4))
    assert ceilings.w_top == tuple(top.tolist())
    assert ceilings.sigma_top == _risk(top, model.moments.cov)
    span = ceilings.sigma_top - ceilings.sigma_min
    for a in (0.25, 0.50):
        assert ceilings.value(a) == ceilings.sigma_min + a * span
    assert ceilings.value(1.0) == ceilings.sigma_top  # w_top sits on X(1) exactly
    assert not ceilings.collapsed
    assert ceilings.distinct == (0.25, 0.50, 1.0)
    assert [ceilings.alias_of(a) for a in (0.25, 0.5, 1.0)] == [0.25, 0.5, 1.0]


def test_collapsed_ceilings_keep_one_cell_and_alias_the_others() -> None:
    caps = (0.25, 0.25, 0.25, 0.25)  # only equal weight fits: the two ends coincide
    ceilings = risk_ceilings(_m4(), caps)
    assert abs(ceilings.sigma_top - ceilings.sigma_min) <= 1e-6
    assert ceilings.collapsed and ceilings.distinct == (1.0,)
    assert ceilings.alias_of(0.25) == ceilings.alias_of(0.5) == 1.0
    assert search.CELL_WEIGHT == pytest.approx(1 / 3)
    with pytest.raises(ValueError, match="alias"):
        prepare(_m4(), caps, 0.25, SEED, budget=SMALL)
    high = max(ceilings.sigma_min, ceilings.sigma_top)
    assert ceilings.value(0.25) == ceilings.value(0.5) == ceilings.value(1.0) == high
    cell = search_cell(_m4(), caps, 1.0, SEED, budget=SMALL)
    assert cell.failure is None and cell.ceiling == high


def test_a_collapsed_cell_keeps_a_noisy_w_min_inside_its_ceiling(monkeypatch) -> None:
    """Solver noise puts the minimum-variance answer 5e-7 above sigma(w_top): still one cell."""
    model = _m4()
    cov = model.moments.cov
    caps = np.asarray(CAPS4)
    top = np.asarray(risk_ceilings(model, CAPS4).w_top)
    gradient = cov @ top / _risk(top, cov)
    moves = [
        (gradient[j] - gradient[i], i, j)
        for i in range(4)
        for j in range(4)
        if i != j and top[i] > 0.0 and top[j] < caps[j]
    ]
    slope, i, j = max(moves)
    noisy = top.copy()
    noisy[i] -= 5e-7 / slope
    noisy[j] += 5e-7 / slope
    gap = _risk(noisy, cov) - _risk(top, cov)
    assert 1e-8 < gap < 1e-6 and _feasible(noisy, CAPS4, cov, 1.0)
    monkeypatch.setattr(MenuPrograms, "min_variance", lambda self: noisy.copy())
    ceilings = risk_ceilings(model, CAPS4)
    assert ceilings.collapsed and ceilings.sigma_min - ceilings.sigma_top == gap
    assert ceilings.value(1.0) == ceilings.sigma_min  # not sigma_top: w_min would break it
    cell = search_cell(model, CAPS4, 1.0, SEED, budget=SMALL)
    assert cell.error is None and cell.failure is None and cell.ceiling == ceilings.sigma_min
    assert cell.anchors[0].weights == tuple(noisy.tolist())
    for candidate in cell.pool():
        assert _feasible(candidate.weights, CAPS4, cov, cell.ceiling)


def test_inputs_are_validated() -> None:
    with pytest.raises(ValueError, match="caps"):
        prepare(_m4(), (0.6, 0.6, 0.6), 0.5, SEED)
    with pytest.raises(ValueError, match="caps"):
        prepare(_m4(), (0.2, 0.2, 0.2, 0.2), 0.5, SEED)
    with pytest.raises(ValueError, match="fraction"):
        prepare(_m4(), CAPS4, 0.3, SEED)
    with pytest.raises(ValueError, match="arm"):
        prepare(_m4(), CAPS4, 0.5, SEED, arms=("R", "R+X"))
    with pytest.raises(ValueError, match="power of two"):
        Budget(points=1000)
    with pytest.raises(ValueError, match="order"):
        search_cell(_m4(), CAPS4, 0.5, SEED, order=("R",), budget=SMALL)


# ---------------------------------------------------------------------- broad pool (5.4)


def test_capped_simplex_projection_matches_the_breakpoint_oracle() -> None:
    rng = np.random.default_rng(3)
    for n, cap in ((4, 0.6), (5, 0.6), (23, 0.25), (3, 1.0)):
        caps = np.full(n, cap)
        for _ in range(25):
            z = rng.exponential(size=n)
            z = z / z.sum() if rng.random() < 0.5 else rng.normal(size=n)
            got = project_capped_simplex(z, caps)
            assert np.abs(got - _projection_oracle(z, caps)).max() <= 1e-12
            assert (got >= 0).all() and (got <= caps).all()
            assert abs(got.sum() - 1.0) <= 1e-12


def test_broad_rows_transform_even_interior_and_odd_boundary_points() -> None:
    model = _m4()
    cov = model.moments.cov
    caps = np.asarray(CAPS4)
    w_min = np.asarray(risk_ceilings(model, CAPS4).w_min)
    roomy = 1.0  # a ceiling no mix of the menu reaches: no bisection
    row = np.array([0.31, 0.02, 0.77, 0.5, 0.36])
    t = math.sqrt(0.36)
    z = -np.log(row[:4])
    interior = _projection_oracle(z / z.sum(), caps)
    got = broad_candidate(row, 0, caps, w_min, cov, roomy)
    assert np.abs(got - ((1 - t) * interior + t * w_min)).max() <= 1e-14
    boundary = _greedy_oracle(row[:4], caps)  # C (.77) to its cap, then D (.5): sparse
    assert boundary.tolist() == [0.0, 0.0, 0.6, 0.4]
    got = broad_candidate(row, 1, caps, w_min, cov, roomy)
    assert np.abs(got - ((1 - t) * boundary + t * w_min)).max() <= 1e-15
    # ties keep fund order; the clip keeps a zero coordinate finite
    tied = np.array([0.5, 0.5, 0.5, 0.0, 0.0])
    assert broad_candidate(tied, 1, caps, w_min, cov, roomy).tolist() == [0.6, 0.4, 0.0, 0.0]
    assert np.isfinite(broad_candidate(tied, 0, caps, w_min, cov, roomy)).all()


def test_a_mix_above_the_ceiling_moves_toward_w_min_onto_the_ceiling() -> None:
    model = _m4()
    cov = model.moments.cov
    caps = np.asarray(CAPS4)
    w_min = np.asarray(risk_ceilings(model, CAPS4).w_min)
    row = np.array([0.9, 0.1, 0.2, 0.3, 0.0])  # v = 0: the boundary mix itself, unmixed
    start = _greedy_oracle(row[:4], caps)
    ceiling = 0.5 * (_risk(start, cov) + _risk(w_min, cov))
    assert _risk(start, cov) > ceiling
    got = broad_candidate(row, 1, caps, w_min, cov, ceiling)
    assert 0.0 <= ceiling - _risk(got, cov) <= 1e-12
    share = (got - start) / (w_min - start)  # one point of the segment start -> w_min
    moved = share[np.abs(w_min - start) > 1e-9]
    assert np.ptp(moved) <= 1e-12 and 0.0 < moved[0] < 1.0


def test_sobol_matrix_and_bank_replay_from_their_seeds() -> None:
    cell = _cell()
    engine = qmc.Sobol(d=5, scramble=True, rng=np.random.default_rng(SEED + 1_000_000))
    matrix = engine.random_base2(5)
    assert cell.generator_seed == SEED + 1_000_000
    assert cell.sobol_sha256 == hashlib.sha256(matrix.astype("<f8").tobytes()).hexdigest()
    assert cell.bank_sha256 == bank(_m4(), SEED).index_sha256
    again = search_cell(_m4(), CAPS4, 0.5, SEED, budget=SMALL)
    assert again.digest() == cell.digest()
    other = search_cell(_m4(), CAPS4, 0.5, PATH_SEEDS[1], budget=SMALL)
    assert other.sobol_sha256 != cell.sobol_sha256 and other.bank_sha256 != cell.bank_sha256
    broad = [row for row in cell.rows if row.source == "broad"]
    assert [row.index for row in broad] == list(range(32))
    candidates = np.array([row.scored.weights for row in broad])
    assert cell.broad_sha256 == hashlib.sha256(candidates.astype("<f8").tobytes()).hexdigest()


# --------------------------------------------------------------------------- anchors (5.3)


@pytest.mark.parametrize(
    ("fraction", "names"), [(0.25, (0, 1, 2, 5)), (0.5, (0, 1, 2, 3, 5, 6)), (1.0, range(8))]
)
def test_anchors_are_the_protocol_eight_at_or_below_the_ceiling(fraction, names) -> None:
    model = _m4()
    cell = _cell(fraction)
    expected = tuple(ANCHORS[i] for i in names)
    assert tuple(anchor.name for anchor in cell.anchors) == expected
    rows = [row for row in cell.rows if row.source == "anchor"]
    assert tuple(row.name for row in rows) == expected
    ceilings = risk_ceilings(model, CAPS4)
    cov, sigma, mu = model.moments.cov, model.moments.sigma, model.mu_s
    for anchor in cell.anchors:
        assert anchor.error is None
        if anchor.name in ("min_variance", "equal_weight"):
            continue
        a = {"x25": 0.25, "x50": 0.5, "x100": 1.0}[anchor.name.split("_")[1]]
        own = ceilings.value(a)
        assert anchor.ceiling == own <= _x(cell)
        assert _feasible(anchor.weights, CAPS4, cov, own)
        assert anchor.off_ceiling == (own - _risk(anchor.weights, cov) > 1e-6)
        if anchor.name.startswith("frontier"):
            best = _quadratic_program(model, CAPS4, own, mu)
            assert mu @ np.asarray(anchor.weights) >= mu @ best - 1e-7
        else:
            best = _quadratic_program(model, CAPS4, own, sigma)
            assert sigma @ np.asarray(anchor.weights) >= sigma @ best - 1e-7
    by_name = {anchor.name: anchor for anchor in cell.anchors}
    assert by_name["min_variance"].weights == ceilings.w_min
    if fraction == 1.0:
        assert by_name["frontier_x100"].weights == ceilings.w_top
    # no pool member holds more sum(sigma_i w_i) than the MDP at the cell's own ceiling
    mdp = by_name[{0.25: "mdp_x25", 0.5: "mdp_x50", 1.0: "mdp_x100"}[fraction]]
    assert mdp.weights is not None
    ceiling_best = sigma @ np.asarray(mdp.weights)
    for candidate in cell.pool():
        assert sigma @ np.asarray(candidate.weights) <= ceiling_best + 1e-7


def test_equal_weight_above_the_ceiling_is_an_ordinary_invalid_proposal() -> None:
    model = _m4()
    cell = _cell(0.25)
    assert _risk([0.25] * 4, model.moments.cov) > _x(cell)
    row = next(row for row in cell.rows if row.name == "equal_weight")
    assert row.scored.weights == (0.25, 0.25, 0.25, 0.25)
    assert row.scored.status == INFEASIBLE and row.scored.penalty is not None
    assert cell.error is None and cell.failure is None
    assert (0.25, 0.25, 0.25, 0.25) not in {c.weights for c in cell.pool()}


def _ruined_everywhere() -> OriginModel:
    """Every fund loses 200% on day 100: every long-only mix has g_t <= 0 there."""
    return synthetic_model(FUNDS4, 260, 7, shocks={(100, i): -2.0 for i in range(4)})


def test_w_min_with_nonpositive_growth_is_a_named_cell_error() -> None:
    model = _ruined_everywhere()
    cell = search_cell(model, CAPS4, 0.5, SEED, budget=SMALL)
    assert cell.error == W_MIN_NONPOSITIVE_GROWTH
    assert cell.failure == COMPUTATIONAL_ERROR
    assert cell.arms == () and cell.pool_rows == ()
    assert [row.source for row in cell.rows] == ["anchor"]
    row = cell.rows[0]
    assert row.name == "min_variance" and row.scored.status == NONPOSITIVE_DAILY_GROWTH
    assert row.scored.ruin_day == model.days[100]


def test_named_computational_errors_of_the_anchors(monkeypatch: pytest.MonkeyPatch) -> None:
    model = _m4()

    def unsolved(self):
        raise SolveError("injected")

    with monkeypatch.context() as patch:
        patch.setattr(MenuPrograms, "min_variance", unsolved)
        cell = search_cell(model, CAPS4, 0.5, SEED, budget=SMALL)
    assert cell.error == MIN_VARIANCE_UNSOLVED and cell.rows == () and cell.arms == ()

    real = MenuPrograms.min_variance
    with monkeypatch.context() as patch:
        patch.setattr(MenuPrograms, "min_variance", lambda self: real(self) * (1 + 1e-7))
        cell = search_cell(model, CAPS4, 0.5, SEED, budget=SMALL)
    assert cell.error == W_MIN_INFEASIBLE and cell.anchors[0].error == W_MIN_INFEASIBLE

    top = np.asarray(risk_ceilings(model, CAPS4).w_top)
    with monkeypatch.context() as patch:  # a frontier answer above its own ceiling
        patch.setattr(MenuPrograms, "frontier_point", lambda self, x: top.copy())
        cell = search_cell(model, CAPS4, 0.5, SEED, budget=SMALL)
    assert cell.error == ANCHOR_INFEASIBLE and "frontier_x25" in (cell.error_detail or "")
    assert cell.anchors[-1].name == "frontier_x25" and cell.anchors[-1].error == ANCHOR_INFEASIBLE

    with monkeypatch.context() as patch:
        patch.setattr(MdpProgram, "solve", lambda self, x: (None, "solver error: injected"))
        cell = search_cell(model, CAPS4, 0.5, SEED, budget=SMALL)
    assert cell.error == ANCHOR_UNSOLVED and cell.anchors[-1].name == "mdp_x25"
    assert cell.anchors[-1].solver_status == "solver error: injected"
    assert cell.failure == COMPUTATIONAL_ERROR and cell.arms == ()


def test_the_mdp_program_walks_the_production_retry_ladder(monkeypatch) -> None:
    model = _m4()
    program = MdpProgram(model.moments.sigma, model.moments.cov, np.asarray(CAPS4))
    seen: list[dict] = []

    def failing(self, **kwargs):
        seen.append(kwargs)
        raise cp.SolverError("injected")

    monkeypatch.setattr(cp.Problem, "solve", failing)
    weights, status = program.solve(0.1)
    assert weights is None
    assert status == "MDP at risk 0.1: no optimal solution from Clarabel (last status: " + (
        "solver error: injected)"
    )
    assert len(seen) == len(RETRY_OPTIONS)
    for kwargs, extra in zip(seen, RETRY_OPTIONS, strict=True):
        assert kwargs["solver"] == cp.CLARABEL and kwargs["tol_feas"] == 1e-8
        assert {key: kwargs[key] for key in extra} == extra


# ------------------------------------------------------------------ penalties (5.5, 5.7)


def test_feasibility_breaches_get_the_deterministic_penalty() -> None:
    model = _m4()
    drawn = bank(model, SEED)
    cov = model.moments.cov
    caps = np.asarray(CAPS4)

    def oracle(weights, ceiling):
        w = np.asarray(weights, dtype=float)
        parts = [
            *np.maximum(-w, 0.0),
            *np.maximum(w - caps, 0.0),
            abs(math.fsum(w.tolist()) - 1.0),
            max(_risk(w, cov) - ceiling, 0.0),
        ]
        return PENALTY + PENALTY * math.fsum(parts)

    roomy = 1.0
    for weights in (
        (0.6 + 2e-6, 0.4 - 2e-6, 0.0, 0.0),  # above a cap
        (-2e-8, 0.4, 0.3, 0.3 + 2e-8),  # below zero
        (0.3, 0.3, 0.2, 0.2 + 2e-8),  # sum
    ):
        scored = assess(model, drawn, CAPS4, roomy, weights)
        assert scored.status == INFEASIBLE and scored.penalty == oracle(weights, roomy)
        assert math.isnan(scored.bad) and scored.ruin_day is None
        assert objective(scored, 123.0) == scored.penalty
    inside = (0.6 + 5e-9, 0.4 - 5e-9, 0.0, 0.0)  # within 1e-8: feasible, evaluated
    scored = assess(model, drawn, CAPS4, roomy, inside)
    assert scored.status == OK and scored.penalty is None and math.isfinite(scored.bad)
    assert scored.utility == preference.utility(scored.bad, scored.typical, scored.good)
    assert objective(scored, 0.05) == -0.05
    mix = (0.25, 0.25, 0.25, 0.25)
    tight = _risk(mix, cov) - 1e-7  # the risk ceiling breached by 1e-7
    scored = assess(model, drawn, CAPS4, tight, mix)
    assert scored.status == INFEASIBLE and scored.penalty == oracle(mix, tight)
    assert scored.risk_residual == _risk(mix, cov) - tight
    loose = _risk(mix, cov) - 5e-9
    assert assess(model, drawn, CAPS4, loose, mix).status == OK


def _ruined_fund_a() -> OriginModel:
    """Fund A loses 120% on day 40 and gains 300% on day 41.

    A mix holding more than about 0.83 of A has g_t <= 0 on day 40. A's mean makes it the
    greedy top, so X(1) is A's own (huge) risk and such mixes are feasible at X(1).
    """
    return synthetic_model(FUNDS4, 260, 7, shocks={(40, 0): -1.2, (41, 0): 3.0})


def test_nonpositive_growth_gets_the_base_penalty_and_stays_out_of_the_pool() -> None:
    model = _ruined_fund_a()
    drawn = bank(model, SEED)
    scored = assess(model, drawn, (1.0,) * 4, 10.0, (1.0, 0.0, 0.0, 0.0))
    assert scored.status == NONPOSITIVE_DAILY_GROWTH and scored.penalty == PENALTY
    assert scored.ruin_day == model.days[40] and math.isnan(scored.typical)
    assert objective(scored, 9.0) == PENALTY
    cell = search_cell(model, (1.0,) * 4, 1.0, SEED, budget=Budget(points=64, starts=2, calls=20))
    ruined = [row for row in cell.rows if row.scored.status == NONPOSITIVE_DAILY_GROWTH]
    assert ruined and all(row.scored.ruin_day == model.days[40] for row in ruined)
    pool = {c.weights for c in cell.pool()}
    assert not pool & {row.scored.weights for row in ruined}


def test_constraint_values_are_the_explicit_inequalities_and_guards() -> None:
    model = _m4()
    drawn = bank(model, SEED)
    caps = np.asarray(CAPS4)
    ceiling = 1.0
    mix = (0.4, 0.3, 0.2, 0.1)
    scored = assess(model, drawn, CAPS4, ceiling, mix)
    w = np.asarray(mix)
    plain = np.concatenate([w, caps - w, [ceiling - _risk(w, model.moments.cov)]])
    assert np.array_equal(constraint_values(scored, CAPS4, ceiling, None, PRIMARY_ALLOWANCE), plain)
    ref = Candidate((0.25,) * 4, scored.bad + 0.0005, scored.typical - 0.001, scored.good + 0.01)
    got = constraint_values(scored, CAPS4, ceiling, ref, PRIMARY_ALLOWANCE)
    u = preference.utility(scored.bad, scored.typical, scored.good)
    guards = [
        scored.bad - (ref.bad - 0.0010),
        scored.typical - (ref.typical - 0.0025),
        scored.good - (ref.good - 0.0050),
        u - (ref.utility - PRIMARY_ALLOWANCE),
        max(scored.bad - (ref.bad - 1e-10), scored.typical - (ref.typical - 1e-10)),
    ]
    assert np.array_equal(got, np.concatenate([plain, guards]))
    off = assess(model, drawn, CAPS4, ceiling, (0.7, 0.3, 0.0, 0.0))  # above a cap
    values = constraint_values(off, CAPS4, ceiling, ref, PRIMARY_ALLOWANCE)
    assert off.penalty is not None and (values[-5:] == -off.penalty).all()
    assert values[4] == pytest.approx(-0.1)  # cap - w for A
    assert values[8] == ceiling - off.risk


# ----------------------------------------------------------------- starts and local (5.5)


def _candidate(weights, bad, typical=0.0, good=0.0) -> Candidate:
    return Candidate(weights, bad, typical, good)


def test_starts_descend_in_u_spaced_by_l1_then_filled_then_repeated() -> None:
    a = _candidate((1.0, 0.0, 0.0), 0.05)
    b = _candidate((0.96, 0.04, 0.0), 0.04)  # 0.08 from a: skipped in the spaced pass
    c = _candidate((0.5, 0.5, 0.0), 0.03)
    d = _candidate((0.56, 0.44, 0.0), 0.02)  # 0.12 from c: spaced enough
    e = _candidate((0.0, 0.0, 1.0), 0.01)
    starts = select_starts([e, d, c, b, a, a], 4, 0.10)
    assert [s for s, _ in starts] == [a.weights, c.weights, d.weights, e.weights]
    starts = select_starts([e, d, c, b, a], 5, 0.10)  # b fills the fifth slot
    assert [s for s, _ in starts] == [a.weights, c.weights, d.weights, e.weights, b.weights]
    starts = select_starts([b, a, a], 5, 0.10)  # two distinct mixes: repeated in order
    assert starts == (
        (a.weights, False),
        (b.weights, False),
        (a.weights, True),
        (b.weights, True),
        (a.weights, True),
    )
    first = _candidate((1.0, 0.0, 0.0), 0.5)  # U = 0.6 * 0.5 = 0.3 exactly
    tie = _candidate((0.0, 1.0, 0.0), 0.0, 1.0)  # U = 0.3 * 1.0: the same double
    assert first.utility == tie.utility
    assert select_starts([tie, first], 1, 0.10)[0][0] == first.weights  # higher bad first


def test_shared_starts_guard_reference_and_local_guards() -> None:
    cell = _cell()
    shared_ok = [row for row in _ok_rows(cell.rows) if row.source in ("anchor", "broad")]
    best = max(shared_ok, key=_utility)
    others = [row for row in shared_ok if row.scored.weights != best.scored.weights]
    assert all(_utility(row) < _utility(best) for row in others)
    assert cell.reference is not None and cell.reference.weights == best.scored.weights
    candidates = [
        Candidate(r.scored.weights, r.scored.bad, r.scored.typical, r.scored.good)
        for r in shared_ok
    ]
    assert cell.starts == select_starts(candidates, SMALL.starts, 0.10)
    for arm in cell.arms:
        assert [start.start for start in arm.starts] == [s for s, _ in cell.starts]
    arm = cell.arm("R+D")
    assert arm.reference == cell.reference and cell.arm("R").reference is None
    assert arm.reference is not None
    for row in _ok_rows(arm.rows):
        found = Candidate(row.scored.weights, row.scored.bad, row.scored.typical, row.scored.good)
        assert row.local_guards == preference.failed_guards(found, arm.reference, PRIMARY_ALLOWANCE)
    violators = [row for row in _ok_rows(arm.rows) if row.local_guards]
    pool = {c.weights for c in cell.pool()}
    assert all(row.scored.weights in pool for row in violators)  # flagged, still archived


def test_each_call_returns_the_arm_objective_or_its_penalty() -> None:
    cell = _defaults()
    invalid = 0
    for arm in cell.arms:
        for row in arm.rows:
            scored = row.scored
            if scored.status != OK:
                invalid += 1
                assert row.objective == scored.penalty and row.failure == INVALID_PROPOSAL
            elif arm.label == "R":
                assert row.objective == -scored.utility and row.failure is None
            else:
                assert row.dr2 is not None and row.objective == -row.dr2
    assert invalid > 0  # COBYLA steps across the bounds and the ceiling


def test_call_budgets_are_capped_by_the_external_counter() -> None:
    capped = _cell(budget=Budget(points=8, starts=2, calls=12, maxiter=40))
    for arm in capped.arms:
        for start in arm.starts:
            assert start.calls <= 12
            assert len([row for row in arm.rows if row.index == start.index]) == start.calls
            if start.budget_exhausted:
                assert start.calls == 12 and start.status is None
                assert start.message == CALL_BUDGET_EXHAUSTED and not start.success
    assert any(start.budget_exhausted for arm in capped.arms for start in arm.starts)
    plain = _cell(budget=Budget(points=8, starts=2, calls=12, maxiter=12))
    for arm in plain.arms:
        for start in arm.starts:
            assert start.calls <= 12 and not start.budget_exhausted and start.status is not None


def test_a_start_with_no_refinement_and_no_success_is_failed_not_the_arm() -> None:
    with pytest.warns(UserWarning, match="Invalid MAXFUN"):  # PRIMA's own floor of N + 1
        cell = search_cell(_m4(), CAPS4, 0.5, SEED, budget=Budget(8, 2, calls=1, maxiter=1))
    for arm in cell.arms:
        assert arm.failure is None and arm.native_selection is not None
        for start in arm.starts:
            assert start.calls == 1 and not start.success and start.refined == 0
            assert start.failed and start.failure == FAILED_START
        assert arm.failed_starts == 2
    assert cell.failure is None
    ok = _cell()
    for arm in ok.arms:
        for start in arm.starts:
            assert start.failed == (not start.success and start.refined == 0)
            assert start.failure == (FAILED_START if start.failed else None)


def test_protocol_defaults_end_to_end_honour_every_budget() -> None:
    model = _m5()
    cell = _defaults()
    cov = model.moments.cov
    assert cell.budget == Budget() == Budget(points=1024, starts=6, calls=384, maxiter=384)
    assert len([row for row in cell.rows if row.source == "broad"]) == 1024
    assert len(cell.anchors) == 6 and len(cell.starts) == 6
    for arm in cell.arms:
        assert len(arm.starts) == 6 and arm.calls == len(arm.rows) <= 6 * 384
        for start in arm.starts:
            assert 1 <= start.calls <= 384 and start.status is not None
            assert len(start.trace) == start.calls
    spaced = [np.asarray(s) for s, _ in cell.starts]
    for i, first in enumerate(spaced):
        for second in spaced[:i]:
            assert np.abs(first - second).sum() >= 0.10
    for row in _ok_rows(cell.rows):
        assert _feasible(row.scored.weights, CAPS5, cov, cell.ceiling)
    for candidate in cell.pool():
        assert _feasible(candidate.weights, CAPS5, cov, cell.ceiling)
    for arm in cell.arms:
        assert arm.native_selection is not None
        assert _feasible(arm.native_selection.weights, CAPS5, cov, cell.ceiling)
    chosen = preference.select(cell.pool(), PRIMARY_ALLOWANCE)
    assert chosen.selected in cell.pool() and chosen.reference in cell.pool()


# ---------------------------------------------------- caching, isolation and invariance


def test_duplicate_calls_hit_the_arm_local_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    replayed: list[tuple[float, ...]] = []
    real = evaluation.evaluate

    def counted(model, drawn, weights):
        replayed.append(tuple(np.asarray(weights, dtype=float).ravel().tolist()))
        return real(model, drawn, weights)

    monkeypatch.setattr(search, "evaluate", counted)
    cell = search_cell(_m4(), CAPS4, 0.5, SEED, budget=SMALL)
    shared = [row for row in cell.rows if row.source in ("anchor", "broad")]
    scored_shared = {row.scored.weights for row in shared if row.scored.status != INFEASIBLE}
    expected = len(scored_shared)
    for arm in cell.arms:
        own = {row.scored.weights for row in arm.rows if row.scored.status != INFEASIBLE}
        expected += len(own - {row.scored.weights for row in shared})
    assert len(replayed) == expected
    for arm in cell.arms:
        seen = {row.scored.weights for row in shared}
        for row in arm.rows:
            assert row.cached == (row.scored.weights in seen)
            seen.add(row.scored.weights)


def test_repeated_starts_are_separate_budgets_served_from_the_cache() -> None:
    model = synthetic_model(("A", "B"), 260, 4)
    cell = search_cell(model, (1.0, 1.0), 0.25, SEED, budget=Budget(points=1, starts=6, calls=10))
    distinct = {s for s, _ in cell.starts}
    assert len(distinct) < 6
    for arm in cell.arms:
        first = {}
        for start in arm.starts:
            rows = [row for row in arm.rows if row.index == start.index]
            calls = [(row.scored.weights, row.objective) for row in rows]
            if start.repeat:
                assert all(row.cached for row in rows)
                assert calls == first[start.start]
            else:
                first[start.start] = calls


def test_arm_order_labels_and_cache_isolation_leave_the_archive_identical() -> None:
    forward = _cell(order=("R", "R+D"))
    backward = _cell(order=("R+D", "R"))
    assert forward.digest() == backward.digest()
    assert [arm.label for arm in backward.arms] == ["R", "R+D"]
    shared = prepare(_m4(), CAPS4, 0.5, SEED, budget=SMALL)
    alone = run_arm(shared, "R+D")
    assert search.canonical(alone) == search.canonical(forward.arm("R+D"))
    # the same weights give the same figures wherever and by whichever arm they were evaluated
    by_weights: dict[tuple[float, ...], tuple[str, ...]] = {}
    for row in forward.rows:
        if row.scored.status == INFEASIBLE:
            continue
        figures = _figures(row)
        assert by_weights.setdefault(row.scored.weights, figures) == figures


def test_rows_and_pool_have_a_stable_order() -> None:
    cell = _cell()
    sources = [row.source for row in cell.rows]
    anchors = len(cell.anchors)
    assert sources[:anchors] == ["anchor"] * anchors
    assert sources[anchors : anchors + 32] == ["broad"] * 32
    local = cell.rows[anchors + 32 :]
    keys = [(("R", "R+D", "R+E").index(row.arm), row.index, row.call) for row in local]
    assert keys == sorted(keys) and {key[0] for key in keys} == {0, 1}
    seen: set[tuple[float, ...]] = set()
    first = []
    for i, row in enumerate(cell.rows):
        if row.scored.status == OK and row.scored.weights not in seen:
            seen.add(row.scored.weights)
            first.append(i)
    assert list(cell.pool_rows) == first
    for candidate, i in zip(cell.pool(), cell.pool_rows, strict=True):
        row = cell.rows[i]
        assert candidate.weights == row.scored.weights
        assert (candidate.bad, candidate.typical, candidate.good) == (
            row.scored.bad,
            row.scored.typical,
            row.scored.good,
        )


def test_union_rescoring_attaches_dr2_from_the_training_covariance() -> None:
    model = _m4()
    cell = _cell()
    sigma, cov = model.moments.sigma, model.moments.cov
    for candidate in cell.pool():
        w = np.asarray(candidate.weights)
        assert candidate.measure == pytest.approx((w @ sigma) ** 2 / (w @ cov @ w), rel=1e-13)
    for row in cell.rows:
        assert (row.dr2 is not None) == (row.scored.status == OK)
        assert row.enb is None
    with pytest.raises(ValueError, match="enb"):
        cell.pool("enb")
    for arm in cell.arms:
        own = {
            row.scored.weights
            for row in [*cell.rows[: len(cell.anchors) + 32], *arm.rows]
            if row.scored.status == OK
        }
        assert arm.native_reference is not None and arm.native_reference.weights in own
    r = cell.arm("R")
    assert r.native_selection == r.native_reference


def test_the_enb_arm_runs_when_called() -> None:
    model = _m4()
    cell = _cell(arms=("R", "R+D", "R+E"), order=("R+E", "R", "R+D"))
    assert [arm.label for arm in cell.arms] == ["R", "R+D", "R+E"]
    arm = cell.arm("R+E")
    assert arm.measure == "enb" and arm.native_selection is not None
    for row in _ok_rows(arm.rows):
        assert row.enb is not None and row.objective == -row.enb
    for candidate in cell.pool("enb"):
        reference = effective_number_of_bets(np.asarray(candidate.weights), model.moments.cov)
        assert candidate.measure == pytest.approx(reference, rel=1e-12)
    assert search.canonical(cell.arm("R+D")) == search.canonical(_cell().arm("R+D"))


def test_a_named_measure_error_fails_the_arm_and_the_paired_cell(monkeypatch) -> None:
    def undefined(weights, sigma, cov):
        raise measures.UndefinedMeasure("injected")

    monkeypatch.setattr(search.measures, "dr2_from", undefined)
    cell = search_cell(_m4(), CAPS4, 0.5, SEED, budget=SMALL)
    assert cell.arm("R").failure is None and cell.arm("R").native_selection is not None
    failed = cell.arm("R+D")
    assert failed.error == UNDEFINED_MEASURE and failed.failure == FAILED_ARM
    assert failed.native_selection is None and "injected" in (failed.error_detail or "")
    assert cell.failure == FAILED_ARM and cell.pool_rows == ()

    def broken(cov):
        raise TorsionError("injected")

    monkeypatch.setattr(search, "torsion_basis", broken)
    cell = search_cell(_m4(), CAPS4, 0.5, SEED, arms=("R", "R+E"), budget=SMALL)
    assert cell.error == TORSION_FAILED and cell.failure == COMPUTATIONAL_ERROR
    assert cell.bank_sha256 is None  # stopped before the bank was drawn


def test_combine_refuses_arms_of_another_cell_or_a_missing_arm() -> None:
    shared = prepare(_m4(), CAPS4, 0.5, SEED, budget=SMALL)
    other = prepare(_m4(), CAPS4, 0.5, PATH_SEEDS[1], budget=SMALL)
    r, d = run_arm(shared, "R"), run_arm(shared, "R+D")
    with pytest.raises(ValueError, match="another cell"):
        search.combine(shared, [r, run_arm(other, "R+D")])
    with pytest.raises(ValueError, match="arm"):
        search.combine(shared, [r])
    with pytest.raises(ValueError, match="arm"):
        search.combine(shared, [r, d, d])
    with pytest.raises(ValueError, match="arm"):
        run_arm(shared, "R+E")
    assert search.combine(shared, [d, r]).digest() == _cell().digest()


# ------------------------------------------------------------ investigation digest (5)


def _production_digest(store, funds, lookback: str, asof: date, tmp_path) -> str:
    inputs = inputs_from_store(
        store,
        funds=[{"id": fund, "min": None, "max": None} for fund in funds],
        lookback=lookback,
        asof=asof,
        cache_dir=tmp_path / "cache",
        nx=6,
        ny=4,
        levels=2,
        engines=("replay",),
    )
    return build_tensor(inputs, workers=1)["lookback"]["sample_sha256"]


def test_production_sample_digest_reproduces_a_production_build(store, d_g, tmp_path) -> None:
    tsp = ("TSP-G", "TSP-F", "TSP-C", "TSP-S", "TSP-I")
    records = {fund: store_mod.get_record(store, fund) for fund in (*tsp, "VTI", "BND", "VWOB")}
    digest = production_sample_digest(records, tsp, "5y", d_g)
    assert digest == _production_digest(store, tsp, "5y", d_g, tmp_path)
    # VWOB starts inside the window's 10% slack: included, its first return trims the sample
    late = ("VTI", "BND", "VWOB")
    asof = date(2017, 12, 29)
    digest = production_sample_digest(records, late, "5y", asof)
    assert digest == _production_digest(store, late, "5y", asof, tmp_path)
    # a price after the as-of date cannot change it
    bumped = dict(records)
    frame = bumped["VTI"].copy()
    after = pd.to_datetime(frame["date"]) > pd.Timestamp(asof)
    frame.loc[after, "tr_index"] *= 1.5
    bumped["VTI"] = frame
    assert production_sample_digest(bumped, late, "5y", asof) == digest
    assert search.TSP_INVESTIGATION_DIGEST == (
        "d6f782a9947c0fad3a8b85f0ff6906160eff4b1e7a9c2de8e270ccd4eeeba24e"
    )
    assert (search.TSP_INVESTIGATION_ASOF, search.TSP_INVESTIGATION_LOOKBACK) == (
        date(2026, 10, 16),
        "5y",
    )
    with pytest.raises(ValueError, match="window"):
        production_sample_digest(records, tsp, "5y", date(2005, 3, 31))


def test_digest_covers_the_archive_not_the_model_object() -> None:
    cell = _cell()
    assert len(cell.digest()) == 64
    assert replace(cell, ceiling=_x(cell) + 1e-12).digest() != cell.digest()


def test_the_union_refuses_two_evaluations_of_the_same_weights() -> None:
    shared = prepare(_m4(), CAPS4, 0.5, SEED, budget=SMALL)
    r, d = run_arm(shared, "R"), run_arm(shared, "R+D")
    anchor = shared.rows[0].scored  # w_min, as the shared archive scored it
    forged = replace(r.rows[0], scored=replace(anchor, bad=anchor.bad + 1e-12))
    with pytest.raises(search.InvarianceError, match="two different evaluations"):
        search.combine(shared, [replace(r, rows=(forged, *r.rows[1:])), d])
    row = next(row for row in d.rows if row.dr2 is not None)
    assert row.dr2 is not None
    shifted = replace(row, dr2=row.dr2 + 1e-12)
    rows = tuple(shifted if item is row else item for item in d.rows)
    with pytest.raises(search.InvarianceError, match="dr2"):
        search.combine(shared, [r, replace(d, rows=rows)])


def test_cheap_checks_run_before_the_bank_is_drawn(monkeypatch) -> None:
    drawn: list[int] = []
    real = search.bank

    def counted(model, seed):
        drawn.append(seed)
        return real(model, seed)

    monkeypatch.setattr(search, "bank", counted)
    with pytest.raises(ValueError, match="alias"):
        prepare(_m4(), (0.25,) * 4, 0.5, SEED, budget=SMALL)

    def unsolved(self):
        raise SolveError("injected")

    with monkeypatch.context() as patch:
        patch.setattr(MenuPrograms, "min_variance", unsolved)
        cell = search_cell(_m4(), CAPS4, 0.5, SEED, budget=SMALL)
    assert cell.error == MIN_VARIANCE_UNSOLVED and cell.bank_sha256 is None
    assert drawn == []
    shared = prepare(_m4(), CAPS4, 0.5, SEED, budget=SMALL)
    assert drawn == [SEED] and shared.bank_sha256 == real(_m4(), SEED).index_sha256


def test_constraints_at_an_uncounted_point_fail_loudly(monkeypatch) -> None:
    """COBYLA must call the objective, which counts, before the constraints at any point."""

    def constraints_first(fun, x0, method, constraints, options):
        return constraints[0]["fun"](np.asarray(x0) + 0.01)

    shared = prepare(_m4(), CAPS4, 0.5, SEED, budget=SMALL)
    monkeypatch.setattr(search, "minimize", constraints_first)
    with pytest.raises(RuntimeError, match="has not evaluated"):
        run_arm(shared, "R")


# ------------------------------------------------- U coefficients other than the owner's (7 b)

HEAVY = (0.70, 0.20, 0.10)


def _hand_u(bad: float, typical: float, good: float, k: Sequence[float]) -> float:
    return k[0] * bad + k[1] * typical + k[2] * good


def test_default_coefficients_give_the_same_archive_as_no_argument() -> None:
    plain = search_cell(_m4(), CAPS4, 0.5, SEED, budget=SMALL)
    named = search_cell(_m4(), CAPS4, 0.5, SEED, budget=SMALL, coefficients=(0.60, 0.30, 0.10))
    assert plain.coefficients == preference.COEFFICIENTS
    assert named.digest() == plain.digest()


def test_assess_scores_u_with_the_coefficients_given() -> None:
    model = _m4()
    ceiling = risk_ceilings(model, CAPS4).value(1.0)
    drawn = bank(model, SEED)
    w = np.array([0.25, 0.25, 0.25, 0.25])
    scored = assess(model, drawn, CAPS4, ceiling, w, coefficients=HEAVY)
    assert scored.status == OK
    assert scored.utility.hex() == _hand_u(scored.bad, scored.typical, scored.good, HEAVY).hex()
    owner = assess(model, drawn, CAPS4, ceiling, w)
    assert (owner.bad, owner.typical, owner.good) == (scored.bad, scored.typical, scored.good)
    assert owner.utility != scored.utility


def test_coefficients_steer_the_starts_the_guard_reference_and_the_r_arm() -> None:
    cell = search_cell(_m4(), CAPS4, 0.5, SEED, budget=SMALL, coefficients=HEAVY)
    assert cell.failure is None and cell.coefficients == HEAVY
    broad = [row.scored for row in cell.rows if row.source != "local" and row.scored.status == OK]
    best = max(_hand_u(s.bad, s.typical, s.good, HEAVY) for s in broad)
    ties = [s for s in broad if _hand_u(s.bad, s.typical, s.good, HEAVY) >= best - 1e-12]
    top = min(ties, key=lambda s: (-s.bad, -s.typical, -s.good, s.weights))
    assert cell.reference is not None and cell.reference.weights == top.weights
    assert cell.starts[0][0] == top.weights  # the first start is the broad maximum of this U
    r = cell.arm("R")
    own = broad + [row.scored for row in r.rows if row.scored.status == OK]
    best_r = max(_hand_u(s.bad, s.typical, s.good, HEAVY) for s in own)
    assert r.native_selection is not None
    picked = r.native_selection
    assert _hand_u(picked.bad, picked.typical, picked.good, HEAVY) >= best_r - 1e-12
    for row in r.rows:  # R's objective is minus this U
        if row.scored.status == OK:
            u = _hand_u(row.scored.bad, row.scored.typical, row.scored.good, HEAVY)
            assert row.objective == -u
    reference = cell.reference
    d = cell.arm("R+D")
    for row in d.rows:  # R+D's local guards are taken under the same U
        if row.scored.status == OK:
            s = row.scored
            floor = (
                _hand_u(reference.bad, reference.typical, reference.good, HEAVY) - PRIMARY_ALLOWANCE
            )
            failed_u = not _hand_u(s.bad, s.typical, s.good, HEAVY) >= floor
            assert row.local_guards is not None and ("u" in row.local_guards) == failed_u
    owner = search_cell(_m4(), CAPS4, 0.5, SEED, budget=SMALL)
    assert owner.digest() != cell.digest()


def test_constraint_values_take_the_u_guard_under_the_coefficients_given() -> None:
    model = _m4()
    ceiling = risk_ceilings(model, CAPS4).value(1.0)
    drawn = bank(model, SEED)
    reference = Candidate((0.25, 0.25, 0.25, 0.25), 0.01, 0.05, 0.12)
    scored = assess(
        model, drawn, CAPS4, ceiling, np.array([0.25, 0.25, 0.25, 0.25]), coefficients=HEAVY
    )
    values = constraint_values(scored, CAPS4, ceiling, reference, 0.00025, coefficients=HEAVY)
    u_floor = _hand_u(0.01, 0.05, 0.12, HEAVY) - 0.00025
    assert values[-2] == scored.utility - u_floor
