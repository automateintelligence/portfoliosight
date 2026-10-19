"""The shared candidate search of one experiment cell (protocol 3 and 5).

A cell is one (menu, origin, ceiling, replicate). For it the search proposes feasible portfolios,
refines them with each arm's own objective under equal budgets and returns the union archive,
from which the runner selects with the two-stage preference (`engine.preference.select`).
`search_cell` runs a whole cell; `prepare`, `run_arm` and `combine` are its three parts, so that
a runner can time each arm on its own (protocol 7, timing contract).

1. Bank. One History-replay bank (`evaluate.bank`: 2,000 x 252 stationary bootstrap, mean block
   21) of the replicate's path seed (`PATH_SEEDS`, 20261013..20261017) serves every evaluation of
   the cell, both arms included; the SHA-256 of its day indices is recorded.
2. Ceilings (protocol 3). `w_min` is production's minimum-variance program, `w_top` production's
   cap-constrained greedy fill of `mu_s`; `X(a) = sigma_min + a (sigma_top - sigma_min)` for
   a in {.25, .50} and `X(1) = sigma_top` exactly, as production's frontier ends on it. When the
   two ends are within 1e-6 the ceilings collapse: the cell at a = 1 is the one distinct cell,
   its ceiling `max(sigma_min, sigma_top)` so that solver noise cannot put `w_min` above it, and
   .25 and .50 are its aliases, each keeping its aggregation weight `CELL_WEIGHT` (1/3).
3. Anchors, at most eight, in this order: minimum variance (`w_min`); equal weight, exactly
   1/N, projected on the capped simplex only where 1/N exceeds a cap; the max-`mu_s` frontier
   mixes at X(.25), X(.50) (production's frontier program) and X(1) (the greedy fill `w_top`,
   production's frontier end); and the most-diversified portfolios (`MdpProgram`: maximize
   `sigma'w` s.t. `|C w| <= X`, `1'w = 1`, `0 <= w <= caps`, solved by production's
   `solve_with_retries`) at the same three ceilings; frontier and MDP only at ceilings at or
   below the cell's X. Every solved anchor must meet its bounds, sum and own ceiling within 1e-8,
   and `w_min` must also have `g_t > 0` on every recentred training row; otherwise the cell stops
   with a named computational error (`MIN_VARIANCE_UNSOLVED`, `W_MIN_INFEASIBLE`,
   `W_MIN_NONPOSITIVE_GROWTH`, `ANCHOR_UNSOLVED`, `ANCHOR_INFEASIBLE`). Equal weight is not
   solved: above the cell's ceiling it is an ordinary invalid proposal, recorded and kept out of
   the archive. A frontier or MDP anchor more than 1e-6 inside its own ceiling is flagged
   `off_ceiling`; its risk is recorded, never asserted to be on the ceiling.
4. Broad pool: `Budget.points` (1,024) scrambled Sobol points in dimension N + 1, one complete
   power-of-two draw from a generator seeded with the path seed + 1,000,000, new in each cell.
   Row r: for even r, `z = -log(clip(u, 2^-53, 1 - 2^-53))` of the first N coordinates,
   normalized to sum 1 and projected on the capped simplex (`project_capped_simplex`: 80
   bisection steps on `sum clip(z - lam, 0, cap) = 1` over `[min z - 1, max z]`, then the final
   bracket's midpoint); for odd r, production's greedy fill of the caps in descending coordinate
   order, ties in fund order (sparse boundary mixes). Each candidate c is mixed toward `w_min` by
   the square root of the last coordinate v, `w = (1 - sqrt v) c + sqrt v w_min` (the protocol's
   words read literally), and when its risk is above X it is moved along the segment toward
   `w_min` by 60 bisection steps, to the feasible end of the final bracket. Nothing is
   renormalized: a proposal that still breaks a check is an invalid proposal. The SHA-256 of the
   Sobol matrix and of the transformed candidates are recorded.
5. Starts: `Budget.starts` (6) starts shared by the arms, from the feasible broad archive
   (anchors and Sobol mixes): distinct weights in descending U (ties: higher B, T, G, then the
   smaller weight vector), keeping each at L1 distance >= .10 from every one already kept; then
   filled in U order; with fewer distinct mixes, the kept starts repeat in order, each with its own
   budget (`select_starts`).
6. Arms. Each arm refines the same starts with its own objective under scipy's COBYLA (PRIMA) in
   N - 1 coordinates, the last weight `1 - sum(x)`, `rhobeg = .05`, `tol = 1e-5`, `catol = 1e-8`,
   `maxiter`, with every bound and the risk ceiling as explicit inequality constraints
   (`constraint_values`). R minimizes -U. R+D minimizes -DR² (R+E -ENB of production's minimum
   torsion) with the protocol 2 guards as further inequality constraints, relative to the
   maximum-U member of the shared broad archive (known before either arm runs) at the allowance
   (2.5 bp primary). A feasible candidate that breaks a guard is archived with its guard flags and
   an unpenalized objective. An external counter allows `Budget.calls` (384) objective calls per
   start, repeated and invalid ones included; the next call raises a dedicated sentinel, caught
   only around the COBYLA call. A proposal that breaks a bound, the sum or the ceiling by more
   than 1e-8 scores `1e6 + 1e6 * (sum of its positive violations)` without being replayed; one
   with a recentred `g_t <= 0` scores 1e6 and keeps the named `nonpositive_daily_growth` status
   and date (`assess`, `objective`). Neither enters the feasible archive; a guard constraint has
   no figures to read there and returns minus that penalty. Each arm starts from a fresh cache
   that holds the shared broad archive only and never sees another arm's. Its native result on
   its own archive (broad plus its local candidates) is a diagnostic: R's is Stage A (`w_R`),
   a measure arm's the whole two-stage rule at the allowance.
7. Union (`combine`): every row of the broad archive and of the arms, in one fixed order
   (anchors, Sobol rows, then arms R, R+D, R+E by start and call) whatever order the arms ran in.
   The same weights must carry the same figures wherever they were evaluated (`InvarianceError`
   otherwise). The pool is the feasible rows deduplicated by exact weights (first occurrence),
   rescored once: their cached B/T/G, and DR² (ENB too when R+E ran) from the training
   covariance. The runner selects with `preference.select(cell.pool(measure), allowance)`.

Failure taxonomy (protocol 5), each class named by a `failure` property. An invalid proposal
(`infeasible`, `nonpositive_daily_growth`) costs a call and stays in the rows with its status
(`Attempt.failure`: `INVALID_PROPOSAL`). A start fails when COBYLA does not report success and the
start produced no feasible candidate other than its own first point (`StartRun.failure`:
`FAILED_START`); budget exhaustion with refinements is normal completion. An arm fails on a named
computational error in its measure (`ArmSearch.error`: `UNDEFINED_MEASURE`; `failure`:
`FAILED_ARM`) and then has no native result. A cell fails on a named computational error before
search (`CellSearch.error`; `failure`: `COMPUTATIONAL_ERROR`) or when any of its arms fails
(`failure`: `FAILED_ARM`); a failed cell has no pool. Any other exception propagates.

U coefficients. Every use of U (the replayed figures' `utility`, the start order, the R+D guard
reference, R's objective, the local U guard and the native selections) takes the cell's
`coefficients`, by default the owner's `preference.COEFFICIENTS`; protocol 7 (b) re-searches with
(.70, .20, .10) and (.50, .35, .15), since the arms' objectives are written in U.

Determinism. The same model, caps, ceiling, seed, budget, allowance, coefficients and arms give a
byte-identical archive (`CellSearch.digest`, over `canonical`) in any arm order: evaluations are
per mix and bit-identical (`research.evaluate`), the Sobol generator and COBYLA are
deterministic, and arm caches are isolated.

`production_sample_digest` recomputes the sample digest a production build records for a menu,
lookback and as-of date from price records, so the runner can reproduce the TSP investigation
digest `TSP_INVESTIGATION_DIGEST` before it trusts the harness (protocol 5). `tensor_ranges`
reproduces the investigation's recorded ranges as well: on the reconstructed sample, with
production's `estimate_moments`, `menu_beta_blend` at the tensor's recorded risk-free rate and
History replay (`range_model` of the tensor's `range_method` seed, `one_year_ranges`), it
recomputes Bad/Typical/Good of the tensor's stored frontier mix and every ladder level of the
given risk columns, one mix at a time, and reports the largest absolute difference from the
stored ranges. The build compounded every mix of the surface in one batch; NumPy hands a one-mix
product to BLAS `gemv` and a batch to `gemm`, which add in different orders (about 1e-14 apart),
so the runner allows `TENSOR_RANGE_TOLERANCE` (1e-12).
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, fields, is_dataclass, replace
from datetime import date, datetime, time
from types import MappingProxyType
from typing import Any

import cvxpy as cp
import numpy as np
import numpy.typing as npt
import pandas as pd
from scipy.optimize import minimize
from scipy.stats import qmc

from portfoliosight.data.returns import build_returns
from portfoliosight.engine import measures, preference
from portfoliosight.engine.caps import greedy_fill
from portfoliosight.engine.optimize import (
    MenuPrograms,
    SolveError,
    cholesky_factor,
    solve_with_retries,
)
from portfoliosight.engine.preference import COEFFICIENTS, Candidate
from portfoliosight.engine.ranges import METHOD, frame_digest, one_year_ranges, range_model
from portfoliosight.engine.stats import estimate_moments, menu_beta_blend
from portfoliosight.engine.torsion import TorsionBasis, TorsionError, enb, torsion_basis
from portfoliosight.engine.windows import select_window
from portfoliosight.research.evaluate import (
    NONPOSITIVE_DAILY_GROWTH,
    OK,
    Bank,
    ModelKey,
    OriginModel,
    bank,
    evaluate,
)

FRACTIONS = (0.25, 0.50, 1.0)  # protocol 3: X(a) for a in {.25, .50, 1}
CEILING_IDS = {0.25: "x25", 0.50: "x50", 1.0: "x100"}  # fixed string ids (timing contract)
CELL_WEIGHT = 1 / 3  # each prescribed ceiling's weight within an origin; an alias keeps its own
COLLAPSE_TOL = 1e-6  # the two ends of the risk span this close: one distinct cell
PATH_SEEDS = (20261013, 20261014, 20261015, 20261016, 20261017)  # optimizer replicates
GENERATOR_OFFSET = 1_000_000  # candidate generator seed = path seed + this
PRIMARY_ALLOWANCE = 0.00025  # the 2.5 bp U allowance of protocol 2, in decimal
FEASIBILITY_TOL = 1e-8  # a bound, the sum or the ceiling broken by more than this: invalid
PENALTY = 1e6  # objective of an invalid proposal: PENALTY + PENALTY * violations
TINY = 2.0**-53  # the even-row clip of the Sobol coordinates
PROJECTION_STEPS = 80
MIX_STEPS = 60  # bisection toward w_min onto the ceiling
START_SPACING = 0.10  # L1 distance between shared local starts
RHOBEG = 0.05
COBYLA_TOL = 1e-5
CATOL = 1e-8
OFF_CEILING_TOL = 1e-6  # an anchor this far inside its own ceiling is flagged off_ceiling

ARMS = ("R", "R+D", "R+E")  # the canonical arm order of every archive
ARM_MEASURES: dict[str, str | None] = {"R": None, "R+D": "dr2", "R+E": "enb"}
STAGE_1_ARMS = ("R", "R+D")

# Proposal statuses: OK and NONPOSITIVE_DAILY_GROWTH (research.evaluate), and
INFEASIBLE = "infeasible"  # a bound, the sum or the ceiling broken by more than 1e-8
# Row sources.
ANCHOR, BROAD, LOCAL = "anchor", "broad", "local"
# Start status when the external counter stopped COBYLA.
CALL_BUDGET_EXHAUSTED = "call_budget_exhausted"
# Failure classes (protocol 5): of a row, a start, an arm and a cell.
INVALID_PROPOSAL = "invalid_proposal"
FAILED_START = "failed_start"
FAILED_ARM = "failed_arm"
COMPUTATIONAL_ERROR = "named_computational_error"
# Named computational errors: of a cell before search ...
MIN_VARIANCE_UNSOLVED = "min_variance_unsolved"
W_MIN_INFEASIBLE = "w_min_infeasible"
W_MIN_NONPOSITIVE_GROWTH = "w_min_nonpositive_daily_growth"
ANCHOR_UNSOLVED = "anchor_unsolved"
ANCHOR_INFEASIBLE = "anchor_infeasible"
TORSION_FAILED = "torsion_basis_failed"
# ... and of an arm's measure.
UNDEFINED_MEASURE = "undefined_measure"

# Protocol 5: the latest saved TSP sample (5y, built 2026-10-16) must reproduce this digest.
TSP_INVESTIGATION_DIGEST = "d6f782a9947c0fad3a8b85f0ff6906160eff4b1e7a9c2de8e270ccd4eeeba24e"
TSP_INVESTIGATION_ASOF = date(2026, 10, 16)
TSP_INVESTIGATION_LOOKBACK = "5y"
# ... and the saved tensor of that build, whose recorded ranges must be reproduced too: the
# investigation's adjacent risk columns 36 and 37 (snapshot path as frozen by the freeze script).
TSP_INVESTIGATION_TENSOR = "tensors/2026-10-16-0.2.0/63643e52f0386317/5y.json"
TSP_INVESTIGATION_COLUMNS = (36, 37)
TENSOR_RANGE_TOLERANCE = 1e-12  # per-mix (gemv) against the build's batched (gemm) compounding
RANGE_FIGURES = ("bad", "typical", "good")


class InvarianceError(RuntimeError):
    """The same weights carry different figures in two places of one cell's archive."""


class _CallBudgetExhausted(Exception):
    """The sentinel the external counter raises on the call after a start's budget."""


@dataclass(frozen=True)
class Budget:
    """Search budgets of a cell; the defaults are the protocol's (sensitivity (d) doubles them)."""

    points: int = 1024  # Sobol points: a complete power-of-two draw
    starts: int = 6  # shared local starts
    calls: int = 384  # objective calls per start, counted outside COBYLA
    maxiter: int = 384  # COBYLA's own function-evaluation cap

    def __post_init__(self) -> None:
        for name in ("points", "starts", "calls", "maxiter"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"the budget's {name} must be a positive integer, got {value!r}")
        if self.points & (self.points - 1):
            raise ValueError(
                f"broad points must be a power of two (a complete Sobol draw), got {self.points}"
            )


DEFAULT_BUDGET = Budget()


@dataclass(frozen=True)
class Ceilings:
    """The risk span of one (menu, origin): its two ends and the three ceilings between them."""

    w_min: tuple[float, ...]  # production minimum variance
    w_top: tuple[float, ...]  # production greedy fill of mu_s under the caps
    sigma_min: float
    sigma_top: float
    collapsed: bool  # |sigma_top - sigma_min| <= 1e-6: one distinct cell

    def value(self, fraction: float) -> float:
        """`X(a) = sigma_min + a (sigma_top - sigma_min)`; `X(1)` is `sigma_top` itself.

        Collapsed, every fraction is the one cell's ceiling `max(sigma_min, sigma_top)`: solver
        noise can put `sigma(w_min)` up to 1e-6 above `sigma(w_top)`, and neither end may fall
        outside the cell.
        """
        fraction = _fraction(fraction)
        if self.collapsed:
            return max(self.sigma_min, self.sigma_top)
        if fraction == 1.0:
            return self.sigma_top
        return self.sigma_min + fraction * (self.sigma_top - self.sigma_min)

    @property
    def distinct(self) -> tuple[float, ...]:
        """The fractions whose cells are searched: all three, or a = 1 when collapsed."""
        return (1.0,) if self.collapsed else FRACTIONS

    def alias_of(self, fraction: float) -> float:
        """The fraction of the cell whose results stand for ``fraction``'s."""
        fraction = _fraction(fraction)
        return 1.0 if self.collapsed else fraction


@dataclass(frozen=True)
class Scored:
    """One weight vector checked against the cell's caps and ceiling and, if valid, replayed."""

    weights: tuple[float, ...]  # fixed menu order, -0.0 written as 0.0
    status: str  # OK | INFEASIBLE | NONPOSITIVE_DAILY_GROWTH
    ruin_day: date | None  # the first training date with g_t <= 0
    risk: float  # sqrt(w' cov w), annual, the training covariance
    bound_residual: float  # the largest breach of a bound (0 when none)
    sum_residual: float  # |sum(w) - 1|, correctly rounded
    risk_residual: float  # risk - X, signed
    violation: float  # the sum of every positive violation
    penalty: float | None  # the objective of an invalid proposal; None when OK
    bad: float  # NaN, like every figure, unless OK
    typical: float
    good: float
    utility: float  # engine.preference.utility(bad, typical, good)
    mean: float
    es_25: float


@dataclass(frozen=True)
class Anchor:
    """One shared anchor of protocol 5 step 3 as it was produced and checked."""

    name: str
    ceiling: float | None  # its own X(a') (frontier, MDP); None for minimum variance, equal weight
    solver_status: str  # cvxpy's status, "exact" for a closed form, or the failure text
    weights: tuple[float, ...] | None  # None when unsolved
    risk: float | None
    off_ceiling: bool | None  # frontier, MDP: risk below its own ceiling by more than 1e-6
    error: str | None  # the named computational error it raised, if any


@dataclass(frozen=True)
class Attempt:
    """One proposal of the cell (a row of the archive) and its evaluation."""

    source: str  # ANCHOR | BROAD | LOCAL
    arm: str | None  # LOCAL: the arm
    name: str | None  # ANCHOR: the anchor's name
    index: int  # ANCHOR: position; BROAD: Sobol row; LOCAL: start
    call: int | None  # LOCAL: the call, 1-based within its start
    cached: bool  # the evaluation was already in the cache (a duplicate attempt)
    scored: Scored
    objective: float | None = None  # LOCAL: what COBYLA received
    local_guards: tuple[str, ...] | None = None  # measure arms, OK rows: guards failed locally
    dr2: float | None = None  # OK rows: DR² (an R+D row from its arm, every row after the union)
    enb: float | None = None  # OK rows when R+E ran: ENB

    @property
    def failure(self) -> str | None:
        """`INVALID_PROPOSAL` unless the proposal is feasible and replayed."""
        return None if self.scored.status == OK else INVALID_PROPOSAL


@dataclass(frozen=True)
class StartRun:
    """One local search from one shared start, with COBYLA's raw report."""

    index: int
    start: tuple[float, ...]  # the broad-archive weights it started from
    repeat: bool  # a repeated start (fewer distinct broad mixes than starts)
    calls: int
    status: int | None  # COBYLA's raw status (PRIMA info); None when the counter stopped it
    success: bool
    message: str
    nfev: int | None
    fun: float | None
    maxcv: float | None
    x: tuple[float, ...] | None  # the weights of COBYLA's returned point
    budget_exhausted: bool  # the external counter stopped it
    feasible: int  # calls whose proposal is feasible and replayed
    refined: int  # distinct feasible proposals other than the start's own first point
    failed: bool  # no success and no refinement: a failed start
    trace: tuple[float, ...]  # the best arm objective after each call (feasible, guards met)

    @property
    def failure(self) -> str | None:
        return FAILED_START if self.failed else None


@dataclass(frozen=True)
class ArmSearch:
    """One arm's local searches of one cell and its native result."""

    cell: tuple  # the shared search's key
    label: str
    measure: str | None  # None (R) | "dr2" | "enb"
    reference: Candidate | None  # the local guard reference (measure arms)
    allowance: float
    starts: tuple[StartRun, ...]
    rows: tuple[Attempt, ...]  # LOCAL rows by start and call
    error: str | None  # a named computational error of the arm
    error_detail: str | None
    native_reference: Candidate | None  # w_R of the arm's own archive
    native_selection: Candidate | None  # R: w_R; a measure arm: Stage B at the allowance

    @property
    def failure(self) -> str | None:
        """`FAILED_ARM` when a named computational error stopped the arm."""
        return None if self.error is None else FAILED_ARM

    @property
    def calls(self) -> int:
        return len(self.rows)

    @property
    def evaluations(self) -> int:
        """Proposals checked and scored afresh (cache misses)."""
        return sum(not row.cached for row in self.rows)

    @property
    def failed_starts(self) -> int:
        return sum(start.failed for start in self.starts)

    @property
    def invalid(self) -> int:
        return sum(row.scored.status != OK for row in self.rows)


class _Measures:
    """The cell's diversification measures, from the origin's training moments."""

    def __init__(self, model: OriginModel, names: Iterable[str]):
        self._sigma = model.moments.sigma
        self._cov = model.moments.cov
        self._basis: TorsionBasis | None = torsion_basis(self._cov) if "enb" in names else None

    def value(self, name: str, weights: Sequence[float]) -> float:
        w = np.asarray(weights, dtype=float)
        if name == "dr2":
            return measures.dr2_from(w, self._sigma, self._cov)
        if name == "enb" and self._basis is not None:
            return enb(w, self._cov, self._basis)
        raise ValueError(f"measure {name!r} is not scored in this cell")


@dataclass(frozen=True)
class SharedSearch:
    """Everything both arms share: the bank, ceilings, anchors, broad archive and starts."""

    key: tuple  # model key, caps, fraction, seed, budget, allowance, coefficients
    model: OriginModel = field(compare=False, repr=False)
    caps: tuple[float, ...]
    fraction: float
    seed: int
    budget: Budget
    allowance: float
    coefficients: tuple[float, float, float]  # U's (Bad, Typical, Good) weights
    arms: tuple[str, ...]  # the cell's required arms, canonical order
    measures: tuple[str, ...]  # what the union scores: dr2, and enb with R+E
    ceilings: Ceilings | None
    ceiling: float | None
    bank: Bank | None = field(compare=False, repr=False)  # None when it stopped before the bank
    bank_sha256: str | None
    sobol_sha256: str | None
    broad_sha256: str | None
    anchors: tuple[Anchor, ...]
    rows: tuple[Attempt, ...]  # anchors, then Sobol rows
    starts: tuple[tuple[tuple[float, ...], bool], ...]  # (weights, repeat)
    reference: Candidate | None  # the maximum-U member of the broad archive
    error: str | None
    error_detail: str | None
    cache: Mapping[bytes, Scored] = field(compare=False, repr=False)
    scorer: _Measures | None = field(compare=False, repr=False)


@dataclass(frozen=True)
class CellSearch:
    """The archive of one cell: every proposal, both arms' searches and the union pool."""

    menu: str
    funds: tuple[str, ...]
    origin: date
    model_key: ModelKey
    shrinkage: float | None  # the fitted Ledoit-Wolf intensity of the training covariance
    caps: tuple[float, ...]
    fraction: float
    ceiling_id: str
    ceiling: float | None
    ceilings: Ceilings | None
    seed: int
    generator_seed: int
    budget: Budget
    allowance: float
    coefficients: tuple[float, float, float]
    measures: tuple[str, ...]
    bank_sha256: str | None  # None when the cell stopped before its bank was drawn
    sobol_sha256: str | None
    broad_sha256: str | None
    anchors: tuple[Anchor, ...]
    starts: tuple[tuple[tuple[float, ...], bool], ...]
    reference: Candidate | None  # the local guard reference: max U of the broad archive
    arms: tuple[ArmSearch, ...]  # canonical order
    rows: tuple[Attempt, ...]  # anchors, Sobol rows, then the arms' local rows
    pool_rows: tuple[int, ...]  # the rows of the union pool: first feasible occurrences
    error: str | None
    error_detail: str | None

    @property
    def failure(self) -> str | None:
        """The cell's failure class: a named computational error, a failed arm, or None."""
        if self.error is not None:
            return COMPUTATIONAL_ERROR
        if any(arm.error is not None for arm in self.arms):
            return FAILED_ARM
        return None

    def arm(self, label: str) -> ArmSearch:
        for entry in self.arms:
            if entry.label == label:
                return entry
        raise KeyError(label)

    def pool(self, measure: str = "dr2") -> tuple[Candidate, ...]:
        """The union pool as preference candidates carrying ``measure`` (empty if failed)."""
        if measure not in self.measures:
            raise ValueError(f"the pool carries {self.measures}; {measure!r} was not scored")
        out = []
        for i in self.pool_rows:
            row = self.rows[i]
            s = row.scored
            out.append(Candidate(s.weights, s.bad, s.typical, s.good, getattr(row, measure)))
        return tuple(out)

    def digest(self) -> str:
        """SHA-256 of the whole archive in `canonical` form: equal digests, equal archives."""
        return hashlib.sha256(canonical(self).encode("utf-8")).hexdigest()


# ------------------------------------------------------------------------------- the search


def search_cell(
    model: OriginModel,
    caps: Sequence[float],
    fraction: float,
    seed: int,
    *,
    arms: Sequence[str] = STAGE_1_ARMS,
    order: Sequence[str] | None = None,
    budget: Budget = DEFAULT_BUDGET,
    allowance: float = PRIMARY_ALLOWANCE,
    coefficients: Sequence[float] = COEFFICIENTS,
) -> CellSearch:
    """One whole cell: `prepare`, each arm in ``order`` (default canonical), then `combine`."""
    labels = _arms(arms)
    sequence = labels if order is None else tuple(order)
    if len(set(sequence)) != len(sequence) or set(sequence) != set(labels):
        raise ValueError(f"order must list each arm of the cell once: {labels}, got {sequence}")
    shared = prepare(
        model,
        caps,
        fraction,
        seed,
        arms=labels,
        budget=budget,
        allowance=allowance,
        coefficients=coefficients,
    )
    if shared.error is not None:
        return combine(shared, ())
    return combine(shared, [run_arm(shared, label) for label in sequence])


def prepare(
    model: OriginModel,
    caps: Sequence[float],
    fraction: float,
    seed: int,
    *,
    arms: Sequence[str] = STAGE_1_ARMS,
    budget: Budget = DEFAULT_BUDGET,
    allowance: float = PRIMARY_ALLOWANCE,
    coefficients: Sequence[float] = COEFFICIENTS,
) -> SharedSearch:
    """The shared part of a cell: bank, ceilings, anchors, broad archive, starts, reference."""
    limits = _caps(model, caps)
    k = preference.checked_coefficients(coefficients)
    fraction = _fraction(fraction)
    labels = _arms(arms)
    if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
        raise ValueError(f"the path seed must be a non-negative integer, got {seed!r}")
    allowance = float(allowance)
    if not (math.isfinite(allowance) and allowance >= 0.0):
        raise ValueError(f"the U allowance must be finite and non-negative, got {allowance}")
    names = ("dr2", "enb") if "R+E" in labels else ("dr2",)
    cov = model.moments.cov
    rows: list[Attempt] = []
    anchors: list[Anchor] = []
    cache: dict[bytes, Scored] = {}

    def shared(**changes) -> SharedSearch:
        base = {
            "key": (model.key, tuple(limits.tolist()), fraction, seed, budget, allowance, k),
            "model": model,
            "caps": tuple(limits.tolist()),
            "fraction": fraction,
            "seed": seed,
            "budget": budget,
            "allowance": allowance,
            "coefficients": k,
            "arms": labels,
            "measures": names,
            "ceilings": None,
            "ceiling": None,
            "bank": None,
            "bank_sha256": None,
            "sobol_sha256": None,
            "broad_sha256": None,
            "anchors": tuple(anchors),
            "rows": tuple(rows),
            "starts": (),
            "reference": None,
            "error": None,
            "error_detail": None,
            "cache": MappingProxyType(dict(cache)),
            "scorer": None,
        }
        return SharedSearch(**{**base, **changes})

    programs = MenuPrograms(model.mu_s, cov, np.zeros(len(limits)), limits)
    try:
        ceilings = _ceilings(programs, limits)
    except SolveError as exc:
        return shared(error=MIN_VARIANCE_UNSOLVED, error_detail=str(exc))
    if ceilings.collapsed and fraction != 1.0:
        raise ValueError(
            f"the ceilings collapse (|sigma_top - sigma_min| <= {COLLAPSE_TOL}): a = {fraction} "
            "is an alias of the cell at a = 1; search that cell"
        )
    ceiling = ceilings.value(fraction)
    try:
        scorer = _Measures(model, names)
    except TorsionError as exc:
        return shared(
            ceilings=ceilings, ceiling=ceiling, error=TORSION_FAILED, error_detail=str(exc)
        )
    drawn = bank(model, seed)  # after the cheap checks: the cell will be searched or fail named
    drawn_fields = {"bank": drawn, "bank_sha256": drawn.index_sha256}

    def propose(source: str, name: str | None, index: int, weights: npt.ArrayLike) -> Scored:
        w = _clean(np.asarray(weights, dtype=float))
        key = w.tobytes()
        cached = key in cache
        if not cached:
            cache[key] = assess(model, drawn, limits, ceiling, w, coefficients=k)
        rows.append(Attempt(source, None, name, index, None, cached, cache[key]))
        return cache[key]

    def stop(error: str, detail: str) -> SharedSearch:
        return shared(
            ceilings=ceilings, ceiling=ceiling, error=error, error_detail=detail, **drawn_fields
        )

    # protocol 5 step 3: w_min first, checked before anything is searched
    w_min = np.asarray(ceilings.w_min)
    scored = propose(ANCHOR, "min_variance", 0, w_min)
    error = {INFEASIBLE: W_MIN_INFEASIBLE, NONPOSITIVE_DAILY_GROWTH: W_MIN_NONPOSITIVE_GROWTH}.get(
        scored.status
    )
    anchors.append(
        Anchor("min_variance", None, "optimal", scored.weights, scored.risk, None, error)
    )
    if error is not None:
        return stop(error, f"min_variance: {scored.status}")
    equal = np.full(len(limits), 1.0 / len(limits))
    if (equal > limits).any():  # projected only where a cap cuts it; else exactly 1/N
        equal = project_capped_simplex(equal, limits)
    scored = propose(ANCHOR, "equal_weight", 1, equal)
    anchors.append(Anchor("equal_weight", None, "exact", scored.weights, scored.risk, None, None))

    mdp = MdpProgram(model.moments.sigma, cov, limits)
    solvers = (
        ("frontier", lambda a, x: _frontier(programs, ceilings, a, x)),
        ("mdp", lambda a, x: mdp.solve(x)),
    )
    for kind, solve in solvers:
        for a in FRACTIONS:
            own = ceilings.value(a)
            if own > ceiling:
                continue
            name = f"{kind}_{CEILING_IDS[a]}"
            weights, status = solve(a, own)
            if weights is None:
                anchors.append(Anchor(name, own, status, None, None, None, ANCHOR_UNSOLVED))
                return stop(ANCHOR_UNSOLVED, f"{name}: {status}")
            breach = _breach(_clean(weights), limits, cov, own)
            error = ANCHOR_INFEASIBLE if breach > FEASIBILITY_TOL else None
            scored = propose(ANCHOR, name, len(anchors), weights)
            off = own - scored.risk > OFF_CEILING_TOL
            anchors.append(Anchor(name, own, status, scored.weights, scored.risk, off, error))
            if error is not None:
                return stop(error, f"{name}: breaks its bounds, sum or ceiling by {breach!r}")

    # protocol 5 step 4: the broad pool
    generator_seed = seed + GENERATOR_OFFSET
    matrix = sobol_matrix(len(limits), budget.points, generator_seed)
    proposals = [
        broad_candidate(row, r, limits, w_min, cov, ceiling) for r, row in enumerate(matrix)
    ]
    for r, weights in enumerate(proposals):
        propose(BROAD, None, r, weights)

    # protocol 5 step 5: the shared starts and the R+D guard reference
    feasible = [_candidate(row.scored) for row in rows if row.scored.status == OK]
    return shared(
        ceilings=ceilings,
        ceiling=ceiling,
        **drawn_fields,
        sobol_sha256=_sha256(matrix),
        broad_sha256=_sha256(np.vstack(proposals)),
        starts=select_starts(feasible, budget.starts, START_SPACING, k),
        reference=preference.select_reference(feasible, k),
        scorer=scorer,
    )


def run_arm(shared: SharedSearch, label: str) -> ArmSearch:
    """One arm's six local searches from the shared starts, on a fresh arm-local cache."""
    if label not in shared.arms:
        raise ValueError(f"arm {label!r} is not one of this cell's arms {shared.arms}")
    if shared.error is not None:
        raise ValueError(f"the cell stopped before search ({shared.error}); no arm can run")
    measure = ARM_MEASURES[label]
    reference = shared.reference if measure is not None else None
    cache = dict(shared.cache)
    rows: list[Attempt] = []
    starts: list[StartRun] = []
    error = detail = None
    native_reference = native_selection = None
    try:
        for index, (start, repeat) in enumerate(shared.starts):
            run = _refine(shared, label, measure, reference, cache, rows, index, start, repeat)
            starts.append(run)
        native_reference, native_selection = _native(shared, measure, rows)
    except (measures.UndefinedMeasure, TorsionError) as exc:
        error, detail = UNDEFINED_MEASURE, f"{type(exc).__name__}: {exc}"
    return ArmSearch(
        cell=shared.key,
        label=label,
        measure=measure,
        reference=reference,
        allowance=shared.allowance,
        starts=tuple(starts),
        rows=tuple(rows),
        error=error,
        error_detail=detail,
        native_reference=native_reference,
        native_selection=native_selection,
    )


def combine(shared: SharedSearch, arms: Iterable[ArmSearch]) -> CellSearch:
    """The cell's archive: shared rows and every required arm's rows, and the union pool."""
    given = list(arms)
    for arm in given:
        if arm.cell != shared.key:
            raise ValueError(f"arm {arm.label!r} was searched for another cell")
    labels = sorted((arm.label for arm in given), key=ARMS.index)
    if shared.error is not None and given:
        raise ValueError(f"the cell stopped before search ({shared.error}); it has no arms")
    if shared.error is None and tuple(labels) != shared.arms:
        raise ValueError(f"the cell's arms are {shared.arms}; got {tuple(labels)}")
    ordered = tuple(sorted(given, key=lambda arm: ARMS.index(arm.label)))
    rows = [*shared.rows, *(row for arm in ordered for row in arm.rows)]
    pool_rows: tuple[int, ...] = ()
    if shared.error is None and all(arm.error is None for arm in ordered):
        rows, pool_rows = _rescore(shared, rows)
    model = shared.model
    return CellSearch(
        menu=model.menu,
        funds=model.funds,
        origin=model.origin,
        model_key=model.key,
        shrinkage=model.moments.shrinkage,
        caps=shared.caps,
        fraction=shared.fraction,
        ceiling_id=CEILING_IDS[shared.fraction],
        ceiling=shared.ceiling,
        ceilings=shared.ceilings,
        seed=shared.seed,
        generator_seed=shared.seed + GENERATOR_OFFSET,
        budget=shared.budget,
        allowance=shared.allowance,
        coefficients=shared.coefficients,
        measures=shared.measures,
        bank_sha256=shared.bank_sha256,
        sobol_sha256=shared.sobol_sha256,
        broad_sha256=shared.broad_sha256,
        anchors=shared.anchors,
        starts=shared.starts,
        reference=shared.reference,
        arms=ordered,
        rows=tuple(rows),
        pool_rows=pool_rows,
        error=shared.error,
        error_detail=shared.error_detail,
    )


# --------------------------------------------------------------------------- the pieces


def risk_ceilings(model: OriginModel, caps: Sequence[float]) -> Ceilings:
    """The origin's risk span under ``caps``; raises `SolveError` if minimum variance fails."""
    limits = _caps(model, caps)
    programs = MenuPrograms(model.mu_s, model.moments.cov, np.zeros(len(limits)), limits)
    return _ceilings(programs, limits)


def assess(
    model: OriginModel,
    drawn: Bank,
    caps: npt.ArrayLike,
    ceiling: float,
    weights: npt.ArrayLike,
    coefficients: Sequence[float] = COEFFICIENTS,
) -> Scored:
    """Check ``weights`` against the caps, the sum and the ceiling, then replay them if valid.

    A breach above 1e-8 of any bound, of the sum or of the ceiling makes the proposal
    `INFEASIBLE`, penalized `1e6 + 1e6 * (sum of positive violations)` and never replayed; a
    valid proposal is evaluated on ``drawn`` (`research.evaluate`), and a recentred `g_t <= 0`
    makes it `NONPOSITIVE_DAILY_GROWTH`, penalized 1e6, with its first such date. Its
    `utility` is U under ``coefficients`` (the owner's by default).
    """
    limits = np.asarray(caps, dtype=float)
    w = _clean(np.asarray(weights, dtype=float))
    if w.shape != limits.shape or not np.isfinite(w).all():
        raise ValueError(f"weights must be {len(limits)} finite numbers, got {w.shape}")
    risk = _risk(w, model.moments.cov)
    below = np.maximum(-w, 0.0)
    above = np.maximum(w - limits, 0.0)
    sum_residual = abs(math.fsum(w.tolist()) - 1.0)
    risk_residual = risk - ceiling
    violation = math.fsum([*below.tolist(), *above.tolist(), sum_residual, max(risk_residual, 0.0)])
    nan = math.nan
    invalid = Scored(
        weights=tuple(w.tolist()),
        status=INFEASIBLE,
        ruin_day=None,
        risk=risk,
        bound_residual=float(max(below.max(), above.max())),
        sum_residual=sum_residual,
        risk_residual=risk_residual,
        violation=violation,
        penalty=PENALTY + PENALTY * violation,
        bad=nan,
        typical=nan,
        good=nan,
        utility=nan,
        mean=nan,
        es_25=nan,
    )
    if max(invalid.bound_residual, sum_residual, risk_residual) > FEASIBILITY_TOL:
        return invalid
    figures = evaluate(model, drawn, w[None, :])
    if figures.status[0] != OK:
        return replace(
            invalid, status=figures.status[0], ruin_day=figures.ruin_day[0], penalty=PENALTY
        )
    bad, typical, good = float(figures.bad[0]), float(figures.typical[0]), float(figures.good[0])
    return replace(
        invalid,
        status=OK,
        penalty=None,
        bad=bad,
        typical=typical,
        good=good,
        utility=preference.utility(bad, typical, good, coefficients),
        mean=float(figures.mean[0]),
        es_25=float(figures.es_25[0]),
    )


def objective(scored: Scored, score: float) -> float:
    """What COBYLA minimizes: ``-score`` for a valid proposal, its penalty otherwise."""
    if scored.status == OK:
        return -score
    if scored.penalty is None:
        raise ValueError(f"an invalid proposal ({scored.status}) carries no penalty")
    return scored.penalty


def constraint_values(
    scored: Scored,
    caps: npt.ArrayLike,
    ceiling: float,
    reference: Candidate | None,
    allowance: float,
    coefficients: Sequence[float] = COEFFICIENTS,
) -> np.ndarray:
    """COBYLA's inequality constraints at a proposal, each feasible when >= 0.

    `w_i` and `cap_i - w_i` for every fund (the last weight is `1 - sum(x)`), `X - risk`, and for
    a measure arm (``reference`` given) the protocol 2 guards relative to ``reference``: Bad,
    Typical, Good, U at ``allowance`` (U under ``coefficients``, as the proposal's own `utility`
    was scored), and the veto `max(B - (B_R - 1e-10), T - (T_R - 1e-10))`. An invalid proposal
    has no figures: each guard is minus its penalty.
    """
    w = np.asarray(scored.weights, dtype=float)
    plain = np.concatenate([w, np.asarray(caps, dtype=float) - w, [ceiling - scored.risk]])
    if reference is None:
        return plain
    if scored.status != OK:
        penalty = objective(scored, math.nan)
        return np.concatenate([plain, np.full(5, -penalty)])
    veto = preference.VETO_TOLERANCE
    guards = [
        scored.bad - (reference.bad - preference.BAD_GUARD),
        scored.typical - (reference.typical - preference.TYPICAL_GUARD),
        scored.good - (reference.good - preference.GOOD_GUARD),
        scored.utility
        - (
            preference.utility(reference.bad, reference.typical, reference.good, coefficients)
            - allowance
        ),
        max(scored.bad - (reference.bad - veto), scored.typical - (reference.typical - veto)),
    ]
    return np.concatenate([plain, guards])


def project_capped_simplex(z: npt.ArrayLike, caps: npt.ArrayLike) -> np.ndarray:
    """Euclidean projection on `{0 <= w <= caps, sum w = 1}`: `clip(z - lam, 0, caps)`.

    `lam` solves `sum clip(z - lam, 0, cap) = 1` by 80 bisection steps on `[min z - 1, max z]`
    (caps at most 1 make the left end's sum `sum(caps) >= 1`); the final bracket's midpoint.
    """
    values = np.asarray(z, dtype=float)
    limits = np.asarray(caps, dtype=float)
    low, high = float(values.min()) - 1.0, float(values.max())
    for _ in range(PROJECTION_STEPS):
        mid = 0.5 * (low + high)
        if math.fsum(np.clip(values - mid, 0.0, limits).tolist()) > 1.0:
            low = mid
        else:
            high = mid
    return np.clip(values - 0.5 * (low + high), 0.0, limits)


def sobol_matrix(funds: int, points: int, generator_seed: int) -> np.ndarray:
    """``points`` scrambled Sobol points in dimension ``funds`` + 1: one power-of-two draw."""
    engine = qmc.Sobol(d=funds + 1, scramble=True, rng=np.random.default_rng(generator_seed))
    return engine.random_base2(points.bit_length() - 1)


def broad_candidate(
    row: npt.ArrayLike,
    index: int,
    caps: npt.ArrayLike,
    w_min: npt.ArrayLike,
    cov: npt.ArrayLike,
    ceiling: float,
) -> np.ndarray:
    """Sobol row ``index`` turned into a broad proposal (protocol 5 step 4)."""
    point = np.asarray(row, dtype=float)
    limits = np.asarray(caps, dtype=float)
    lowest = np.asarray(w_min, dtype=float)
    matrix = np.asarray(cov, dtype=float)
    u, v = point[:-1], float(point[-1])
    if index % 2 == 0:
        z = -np.log(np.clip(u, TINY, 1.0 - TINY))
        mix = project_capped_simplex(z / z.sum(), limits)
    else:
        mix = greedy_fill(u, np.zeros(len(u)), limits)
    share = math.sqrt(v)
    w = (1.0 - share) * mix + share * lowest
    if _risk(w, matrix) > ceiling:
        low, high = 0.0, 1.0  # the share of the way from w to w_min
        for _ in range(MIX_STEPS):
            mid = 0.5 * (low + high)
            if _risk((1.0 - mid) * w + mid * lowest, matrix) <= ceiling:
                high = mid
            else:
                low = mid
        w = (1.0 - high) * w + high * lowest
    return _clean(w)


def select_starts(
    candidates: Sequence[Candidate],
    count: int,
    spacing: float = START_SPACING,
    coefficients: Sequence[float] = COEFFICIENTS,
) -> tuple[tuple[tuple[float, ...], bool], ...]:
    """``count`` local starts as (weights, repeat), from feasible broad candidates.

    Distinct weights in descending U (ties: higher Bad, Typical, Good, then the smaller weight
    vector); each kept start is at L1 distance >= ``spacing`` from every start already kept; then
    the rest in the same order fill the remaining places; with fewer distinct weights than
    ``count``, the kept starts repeat in order, flagged `repeat`.
    """
    distinct: dict[tuple[float, ...], Candidate] = {}
    for candidate in candidates:
        distinct.setdefault(candidate.weights, candidate)
    if not distinct:
        raise ValueError("there is no feasible broad candidate to start from")
    k = preference.checked_coefficients(coefficients)
    order = sorted(distinct.values(), key=lambda candidate: _stage_a_order(candidate, k))
    kept: list[Candidate] = []
    for candidate in order:
        if len(kept) == count:
            break
        w = np.asarray(candidate.weights)
        if all(float(np.abs(w - np.asarray(k.weights)).sum()) >= spacing for k in kept):
            kept.append(candidate)
    chosen = {candidate.weights for candidate in kept}
    for candidate in order:
        if len(kept) == count:
            break
        if candidate.weights not in chosen:
            kept.append(candidate)
    starts = [(candidate.weights, False) for candidate in kept]
    starts += [(kept[i % len(kept)].weights, True) for i in range(len(kept), count)]
    return tuple(starts)


class MdpProgram:
    """The most-diversified portfolio at a ceiling (Choueifaty & Coignard 2008; protocol 5).

    `maximize sigma'w  s.t.  |C w| <= X,  1'w = 1,  0 <= w <= caps`, with `C` production's
    `cholesky_factor` of the training covariance; one DPP-parametrized program re-solved per
    ceiling by production's `solve_with_retries` (Clarabel options and retry ladder).
    """

    def __init__(self, sigma: npt.ArrayLike, cov: npt.ArrayLike, caps: npt.ArrayLike):
        volatility = np.asarray(sigma, dtype=float)
        limits = np.asarray(caps, dtype=float)
        n = len(volatility)
        self._w = cp.Variable(n)
        factor = cp.Parameter((n, n), value=cholesky_factor(cov))
        self._x = cp.Parameter(nonneg=True)
        menu = [
            cp.norm(factor @ self._w, 2) <= self._x,
            cp.sum(self._w) == 1,
            self._w >= 0,
            self._w <= limits,
        ]
        self._problem = cp.Problem(cp.Maximize(volatility @ self._w), menu)

    def solve(self, ceiling: float) -> tuple[np.ndarray | None, str]:
        """The MDP at ``ceiling`` and its status: `optimal`, or None and the `SolveError` text."""
        self._x.value = ceiling
        try:
            return solve_with_retries(self._problem, self._w, f"MDP at risk {ceiling!r}"), "optimal"
        except SolveError as exc:
            return None, str(exc)


def production_sample(
    records: Mapping[str, pd.DataFrame], funds: Sequence[str], lookback: str, asof: date
) -> pd.DataFrame:
    """The window sample a production build of ``funds`` at ``asof`` replays.

    Mirrors `jobs.build.inputs_from_store` and `engine.builder`: each fund's record cut to rows
    dated on or before ``asof``, `build_returns` of those records, the frame in menu order and
    `select_window` (every fund served). Raises `ValueError` when the window has no sample.
    """
    when = datetime.combine(asof, time())
    cut = {}
    for fund in funds:
        record = records[fund]
        cut[fund] = record.loc[pd.to_datetime(record["date"]) <= when].reset_index(drop=True)
    frame = build_returns(cut).reindex(columns=list(funds))
    selection = select_window(frame, lookback, pd.Timestamp(asof))
    if selection.sample is None:
        raise ValueError(f"no {lookback} window at {asof}: {selection.message}")
    return selection.sample


def production_sample_digest(
    records: Mapping[str, pd.DataFrame], funds: Sequence[str], lookback: str, asof: date
) -> str:
    """The `lookback.sample_sha256` a production build of ``funds`` at ``asof`` records."""
    return frame_digest(production_sample(records, funds, lookback, asof))


@dataclass(frozen=True)
class RangeCheck:
    """A saved tensor's recorded ranges recomputed one mix at a time (`tensor_ranges`)."""

    columns: tuple[int, ...]
    mixes: int  # each column's frontier mix and every ladder level
    max_abs_discrepancy: float  # over every mix and Bad, Typical and Good
    worst: str  # where it is: frontier|ladder, column, level, figure
    moments_max_abs_discrepancy: float  # recomputed mu_s and covariance against the tensor's

    def record(self) -> dict[str, object]:
        return {
            "columns": list(self.columns),
            "mixes": self.mixes,
            "max_abs_discrepancy": self.max_abs_discrepancy,
            "worst": self.worst,
            "moments_max_abs_discrepancy": self.moments_max_abs_discrepancy,
        }


def _field(tensor: Mapping[str, Any], *path: str | int) -> Any:
    """``tensor[path[0]][path[1]]...``, a `ValueError` naming the path when it is absent."""
    value: Any = tensor
    for key in path:
        try:
            value = value[key]
        except (KeyError, IndexError, TypeError) as exc:
            where = ".".join(map(str, path))
            raise ValueError(f"the tensor has no {where}") from exc
    return value


def tensor_ranges(
    records: Mapping[str, pd.DataFrame],
    funds: Sequence[str],
    lookback: str,
    asof: date,
    tensor: Mapping[str, Any],
    columns: Sequence[int],
) -> RangeCheck:
    """Recompute a saved tensor's recorded ranges in ``columns`` (module docstring).

    Raises `ValueError` when the tensor is not a build of this sample (funds, digest, range
    method) or lacks a field the check reads.
    """
    frame = production_sample(records, funds, lookback, asof)
    stored_funds = [_field(entry, "id") for entry in _field(tensor, "universe", "funds")]
    if stored_funds != list(funds):
        raise ValueError(f"the tensor's funds {stored_funds} are not {list(funds)}")
    if _field(tensor, "lookback", "sample_sha256") != frame_digest(frame):
        raise ValueError("the tensor's sample digest is not the reconstructed sample's")
    if _field(tensor, "range_method") != METHOD:
        raise ValueError(f"the tensor's range method is not production's {METHOD}")
    sample = frame.to_numpy()
    moments = estimate_moments(sample)
    mu_s, _ = menu_beta_blend(moments.mu, moments.cov, float(_field(tensor, "rf")))
    moments_gap = max(
        float(np.max(np.abs(mu_s - np.asarray(_field(tensor, "mu_s"), dtype=float)))),
        float(np.max(np.abs(moments.cov - np.asarray(_field(tensor, "cov"), dtype=float)))),
    )
    model = range_model(sample, mu_s, moments.cov, int(_field(tensor, "range_method", "seed")))
    mixes: list[tuple[str, np.ndarray, dict[str, float]]] = []
    for column in columns:
        mixes.append(
            (
                f"frontier column {column}",
                np.asarray(_field(tensor, "frontier", "w", column), dtype=float),
                {f: float(_field(tensor, "frontier", "range", f, column)) for f in RANGE_FIGURES},
            )
        )
        for level, weights in enumerate(_field(tensor, "ladder", "w", column)):
            stored = {
                f: float(_field(tensor, "ladder", "range", f, column, level)) for f in RANGE_FIGURES
            }
            where = f"ladder column {column} level {level}"
            mixes.append((where, np.asarray(weights, dtype=float), stored))
    worst, gap = "", 0.0
    for where, weights, stored in mixes:
        found = one_year_ranges(model, weights[None, :])  # one mix at a time
        for figure in RANGE_FIGURES:
            difference = abs(float(found[figure][0]) - stored[figure])
            if not difference <= gap:  # NaN or larger
                worst, gap = f"{where} {figure}", difference
    return RangeCheck(tuple(columns), len(mixes), gap, worst, moments_gap)


def canonical(value: object) -> str:
    """A deterministic text of a search result: compared fields of dataclasses, floats as hex."""
    if is_dataclass(value) and not isinstance(value, type):
        parts = [
            f"{item.name}={canonical(getattr(value, item.name))}"
            for item in fields(value)
            if item.compare
        ]
        return f"{type(value).__name__}({','.join(parts)})"
    if value is None or isinstance(value, bool):
        return repr(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return value.hex()
    if isinstance(value, str):
        return json.dumps(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, tuple | list):
        return "[" + ",".join(canonical(item) for item in value) + "]"
    raise TypeError(f"no canonical form for {type(value).__name__}")


# ------------------------------------------------------------------------------- internals


def _refine(
    shared: SharedSearch,
    label: str,
    measure: str | None,
    reference: Candidate | None,
    cache: dict[bytes, Scored],
    rows: list[Attempt],
    index: int,
    start: tuple[float, ...],
    repeat: bool,
) -> StartRun:
    """One COBYLA run from ``start`` under the external call counter; rows go to ``rows``."""
    model, drawn, scorer = shared.model, shared.bank, shared.scorer
    if shared.ceiling is None or scorer is None or drawn is None:
        raise ValueError("the shared search is incomplete")
    ceiling = shared.ceiling
    limits = np.asarray(shared.caps, dtype=float)
    budget, allowance, k = shared.budget, shared.allowance, shared.coefficients
    n = len(limits)
    state = {"calls": 0, "feasible": 0, "best": math.nan}
    first: list[bytes] = []
    refined: set[bytes] = set()
    trace: list[float] = []

    def weights_of(x: npt.ArrayLike) -> np.ndarray:
        head = np.asarray(x, dtype=float)
        w = np.empty(n)
        w[:-1] = head
        w[-1] = 1.0 - float(np.sum(head))
        return _clean(w)

    def lookup(w: np.ndarray) -> tuple[Scored, bool]:
        key = w.tobytes()
        if key in cache:
            return cache[key], True
        cache[key] = assess(model, drawn, limits, ceiling, w, coefficients=k)
        return cache[key], False

    def fun(x: npt.ArrayLike) -> float:
        if state["calls"] >= budget.calls:
            raise _CallBudgetExhausted
        state["calls"] += 1
        w = weights_of(x)
        scored, cached = lookup(w)
        score, guards, values = math.nan, None, {}
        if scored.status == OK:
            if measure is None:
                score = scored.utility
            else:
                score = scorer.value(measure, scored.weights)
                values[measure] = score
                if reference is not None:
                    found = _candidate(scored)
                    guards = preference.failed_guards(found, reference, allowance, k)
        value = objective(scored, score)
        call = int(state["calls"])
        rows.append(
            Attempt(LOCAL, label, None, index, call, cached, scored, value, guards, **values)
        )
        key = w.tobytes()
        if not first:
            first.append(key)
        if scored.status == OK:
            state["feasible"] += 1
            if key != first[0]:
                refined.add(key)
            if not guards and not value >= state["best"]:  # NaN best: the first one counts
                state["best"] = value
        trace.append(state["best"])
        return value

    def constraints(x: npt.ArrayLike) -> np.ndarray:
        key = weights_of(x).tobytes()
        if key not in cache:  # every point must have been an objective call, so counted
            raise RuntimeError(
                "COBYLA asked for constraints at a point the objective has not evaluated: "
                "the external call counter would miss it"
            )
        return constraint_values(cache[key], limits, ceiling, reference, allowance, k)

    options = {"rhobeg": RHOBEG, "tol": COBYLA_TOL, "catol": CATOL, "maxiter": budget.maxiter}
    try:
        result = minimize(
            fun,
            np.asarray(start[:-1], dtype=float),
            method="COBYLA",
            constraints=[{"type": "ineq", "fun": constraints}],
            options=options,
        )
    except _CallBudgetExhausted:
        result = None
    if result is None:
        status, success, message = None, False, CALL_BUDGET_EXHAUSTED
        nfev, fun_value, maxcv, x = None, None, None, None
    else:
        status, success, message = int(result.status), bool(result.success), str(result.message)
        nfev, fun_value, maxcv = int(result.nfev), float(result.fun), float(result.maxcv)
        x = tuple(weights_of(result.x).tolist())
    return StartRun(
        index=index,
        start=start,
        repeat=repeat,
        calls=int(state["calls"]),
        status=status,
        success=success,
        message=message,
        nfev=nfev,
        fun=fun_value,
        maxcv=maxcv,
        x=x,
        budget_exhausted=result is None,
        feasible=int(state["feasible"]),
        refined=len(refined),
        failed=not success and not refined,
        trace=tuple(float(value) for value in trace),
    )


def _native(
    shared: SharedSearch, measure: str | None, rows: Sequence[Attempt]
) -> tuple[Candidate, Candidate]:
    """An arm's own result on its own archive: (w_R, its selection)."""
    own: dict[tuple[float, ...], Scored] = {}
    for row in (*shared.rows, *rows):
        if row.scored.status == OK:
            own.setdefault(row.scored.weights, row.scored)
    k = shared.coefficients
    if measure is None:
        reference = preference.select_reference([_candidate(s) for s in own.values()], k)
        return reference, reference
    scorer = shared.scorer
    if scorer is None:
        raise ValueError("the shared search is incomplete")
    pool = [_candidate(s, scorer.value(measure, s.weights)) for s in own.values()]
    chosen = preference.select(pool, shared.allowance, k)
    return chosen.reference, chosen.selected


def _rescore(shared: SharedSearch, rows: list[Attempt]) -> tuple[list[Attempt], tuple[int, ...]]:
    """Check exact-weight invariance, attach the measures, and find the pool's rows."""
    scorer = shared.scorer
    if scorer is None:
        raise ValueError("the shared search is incomplete")
    seen: dict[bytes, Scored] = {}
    scores: dict[bytes, dict[str, float]] = {}
    pool_rows = []
    out = []
    for i, row in enumerate(rows):
        scored = row.scored
        key = np.asarray(scored.weights, dtype=float).tobytes()
        known = seen.setdefault(key, scored)
        if known is not scored and canonical(known) != canonical(scored):
            raise InvarianceError(f"weights {scored.weights} carry two different evaluations")
        if scored.status == OK:
            if key not in scores:
                scores[key] = {name: scorer.value(name, scored.weights) for name in shared.measures}
                pool_rows.append(i)
            values = scores[key]
            for name, value in values.items():
                held = getattr(row, name)
                if held is not None and held != value:
                    raise InvarianceError(f"weights {scored.weights}: {name} {held!r} != {value!r}")
            row = replace(row, **values)
        out.append(row)
    return out, tuple(pool_rows)


def _ceilings(programs: MenuPrograms, limits: np.ndarray) -> Ceilings:
    lowest = _clean(programs.min_variance())
    top = _clean(greedy_fill(programs.mu, programs.lo, limits))
    sigma_min, sigma_top = _risk(lowest, programs.cov), _risk(top, programs.cov)
    return Ceilings(
        w_min=tuple(lowest.tolist()),
        w_top=tuple(top.tolist()),
        sigma_min=sigma_min,
        sigma_top=sigma_top,
        collapsed=abs(sigma_top - sigma_min) <= COLLAPSE_TOL,
    )


def _frontier(
    programs: MenuPrograms, ceilings: Ceilings, fraction: float, ceiling: float
) -> tuple[np.ndarray | None, str]:
    """The max-`mu_s` mix at ``ceiling``: the greedy fill at X(1), else production's program."""
    if fraction == 1.0:
        return np.asarray(ceilings.w_top), "exact"
    try:
        return programs.frontier_point(ceiling), "optimal"
    except SolveError as exc:
        return None, str(exc)


def _breach(w: np.ndarray, limits: np.ndarray, cov: np.ndarray, ceiling: float) -> float:
    """The largest breach of a bound, the sum or ``ceiling`` (negative when all hold)."""
    return max(
        float(np.maximum(-w, w - limits).max()),
        abs(math.fsum(w.tolist()) - 1.0),
        _risk(w, cov) - ceiling,
    )


def _risk(w: np.ndarray, cov: np.ndarray) -> float:
    """`sqrt(w' cov w)`, as production's `MenuPrograms.sigma`; refuses a negative variance."""
    variance = float(w @ cov @ w)
    if not variance >= 0.0:
        raise ValueError(f"portfolio variance {variance!r} is negative or not a number")
    return float(np.sqrt(variance))


def _clean(w: np.ndarray) -> np.ndarray:
    """A float copy with -0.0 written as 0.0, so equal weights have equal bytes."""
    return np.asarray(w, dtype=float) + 0.0


def _candidate(scored: Scored, measure: float | None = None) -> Candidate:
    return Candidate(scored.weights, scored.bad, scored.typical, scored.good, measure)


def _stage_a_order(candidate: Candidate, coefficients: Sequence[float]) -> tuple:
    return (
        -preference.utility(candidate.bad, candidate.typical, candidate.good, coefficients),
        -candidate.bad,
        -candidate.typical,
        -candidate.good,
        candidate.weights,
    )


def _sha256(matrix: np.ndarray) -> str:
    return hashlib.sha256(np.ascontiguousarray(matrix, dtype="<f8").tobytes()).hexdigest()


def _caps(model: OriginModel, caps: Sequence[float]) -> np.ndarray:
    limits = np.array(caps, dtype=float)
    if limits.shape != (len(model.funds),):
        raise ValueError(f"caps must give one maximum for each of {len(model.funds)} funds")
    if not (np.isfinite(limits).all() and (limits > 0.0).all() and (limits <= 1.0).all()):
        raise ValueError("caps must lie in (0, 1]")
    if math.fsum(limits.tolist()) < 1.0:
        raise ValueError("the caps must sum to at least 1: no mix would be fully invested")
    limits.setflags(write=False)
    return limits


def _fraction(fraction: float) -> float:
    if fraction not in FRACTIONS:
        raise ValueError(f"the ceiling fraction must be one of {FRACTIONS}, got {fraction!r}")
    return float(fraction)


def _arms(arms: Sequence[str]) -> tuple[str, ...]:
    labels = tuple(arms)
    if not labels or len(set(labels)) != len(labels) or not set(labels) <= set(ARMS):
        raise ValueError(f"arms must be distinct labels among {ARMS}, got {labels}")
    return tuple(sorted(labels, key=ARMS.index))
