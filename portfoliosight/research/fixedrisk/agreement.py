"""Predeclared solver checks of protocol §4: the agreement check and the finite-difference check.

`agreement_check(cases)` solves each (ctx, bank, r_fraction, cell) case with the four solvers for
the U1 and max-Bad objectives (native search results, exact objective) and applies the rule: a
gradient solver is accepted for the engine when its exact objective is within 2.5 bp of, or above,
COBYLA-768's in at least 95% of the cell-objective pairs (57 of 60); if both gradient solvers pass
the cheaper in median wall time runs; if neither, COBYLA-128 runs if it meets the same rule against
COBYLA-768, otherwise COBYLA-768 runs.

`fdcheck(bank, ctx)` checks the analytic gradients of the exact and kernel-smoothed quantiles
(Bad, Typical, Good separately) by central differences along random directions at random feasible
mixes, skipping (and counting) a direction whose step changes the identity of the paths carrying
the quantile's weight or moves a path across the absorption boundary (-100%); a mix with more than
5 of 20 directions skipped is redrawn.
"""

from __future__ import annotations

import hashlib
import math
import statistics
from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np

from .anchors import column_anchors, geometry, project_box_simplex
from .contracts import (
    CELL_D,
    CELLS,
    QUANTILES,
    STARTS,
    TAU_R,
    Anchors,
    OriginContext,
    PathBank,
)
from .objective import Evaluator, _exact_plan, arm_value, kernel_weights
from .optimizer import SOLVERS, search_column

AGREEMENT_TOL = 0.00025  # 2.5 bp
PASS_SHARE = 0.95  # 57 of 60
AGREEMENT_OBJECTIVES = ("U1", "B")
GRADIENT_SOLVERS = ("exact_grad", "kernel_grad")
QUANTILE_OBJECTIVES = {"bad": (1.0, 0.0, 0.0), "typical": (0.0, 1.0, 0.0), "good": (0.0, 0.0, 1.0)}
MAX_REDRAWS = 50


def derived_seed(*parts: object) -> int:
    """A 63-bit seed from the parts' text (stable across hosts and Python runs)."""
    text = "\x1f".join(str(p) for p in parts).encode()
    return int.from_bytes(hashlib.sha256(text).digest()[:8], "big") >> 1


# --------------------------------------------------------------------------- agreement


@dataclass(frozen=True)
class AgreementCase:
    ctx: OriginContext
    bank: PathBank
    r_fraction: float
    cell: str  # "d25", "d50", "d75" or "free"
    anchors: Anchors | None = None  # computed when None


@dataclass(frozen=True)
class AgreementRow:
    case: int
    menu: str
    r_fraction: float
    cell: str
    objective: str
    solver: str
    value: float  # exact objective of the native answer; -inf when none was found
    seconds: float


@dataclass(frozen=True)
class AgreementReport:
    rows: tuple[AgreementRow, ...]
    pairs: int
    needed: int
    passes: dict[str, int]  # solver -> pairs within 2.5 bp of (or above) COBYLA-768
    accepted: dict[str, bool]
    median_seconds: dict[str, float]
    chosen: str


def solve_case(
    case: AgreementCase,
    solver: str,
    objectives: tuple[str, ...] = AGREEMENT_OBJECTIVES,
    starts: int = STARTS,
    tau_r: float = TAU_R,
) -> dict[str, tuple[float, float]]:
    """`objective -> (exact native value, seconds)` of one cell under `solver`.

    Interior cells are reached through the production order (d25, d50, d75 with continuation),
    so the cell's starts are those the run will use; the free cell's native search does not
    depend on the interior cells.
    """
    geo = geometry(case.ctx)
    anchor = case.anchors or column_anchors(geo, case.r_fraction, tau_r)
    if case.cell == "free":
        grid: tuple[float, ...] = ()
    else:
        interior = [c for c in CELLS if c != "free"]
        stop = interior.index(case.cell) + 1
        grid = tuple(float(CELL_D[c]) for c in interior[:stop])  # type: ignore[arg-type]
    col, runs = search_column(
        geo,
        case.bank,
        anchor,
        arms=objectives,
        d_grid=grid,
        include_free=case.cell == "free",
        tau_r=tau_r,
        solver=solver,
        starts=starts,
    )
    out = {}
    for run in runs:
        if run.cell.name != case.cell:
            continue
        btg = None if run.native is None else col.visits[run.native].btg
        value = -math.inf if btg is None else arm_value(btg, run.arm)
        out[run.arm] = (value, run.seconds)
    return out


def agreement_decision(rows: Sequence[AgreementRow]) -> AgreementReport:
    """The §4 rule applied to a table of rows (one per case, objective and solver)."""
    table: dict[tuple[int, str], dict[str, AgreementRow]] = {}
    for row in rows:
        table.setdefault((row.case, row.objective), {})[row.solver] = row
    pairs = len(table)
    needed = math.ceil(PASS_SHARE * pairs - 1e-9)
    passes: dict[str, int] = dict.fromkeys(("exact_grad", "kernel_grad", "cobyla128"), 0)
    for pair in table.values():
        ref = pair["cobyla768"].value
        for solver in passes:
            if solver in pair and pair[solver].value >= ref - AGREEMENT_TOL:
                passes[solver] += 1
    accepted = {s: passes[s] >= needed for s in passes}
    median_seconds = {
        s: statistics.median(p[s].seconds for p in table.values() if s in p)
        for s in SOLVERS
        if any(s in p for p in table.values())
    }
    gradient = [s for s in GRADIENT_SOLVERS if accepted[s]]
    if gradient:
        chosen = min(gradient, key=lambda s: (median_seconds[s], GRADIENT_SOLVERS.index(s)))
    elif accepted["cobyla128"]:
        chosen = "cobyla128"
    else:
        chosen = "cobyla768"
    return AgreementReport(
        rows=tuple(rows),
        pairs=pairs,
        needed=needed,
        passes=passes,
        accepted=accepted,
        median_seconds=median_seconds,
        chosen=chosen,
    )


def agreement_check(
    cases: Sequence[AgreementCase],
    objectives: tuple[str, ...] = AGREEMENT_OBJECTIVES,
    starts: int = STARTS,
    tau_r: float = TAU_R,
) -> AgreementReport:
    """Run every case under the four solvers and decide (protocol §4 agreement check)."""
    rows: list[AgreementRow] = []
    for k, case in enumerate(cases):
        if case.anchors is None:
            case = AgreementCase(
                case.ctx,
                case.bank,
                case.r_fraction,
                case.cell,
                column_anchors(geometry(case.ctx), case.r_fraction, tau_r),
            )
        for solver in SOLVERS:
            values = solve_case(case, solver, objectives, starts, tau_r)
            for objective in objectives:
                value, seconds = values.get(objective, (-math.inf, 0.0))
                rows.append(
                    AgreementRow(
                        k,
                        case.ctx.menu.name,
                        case.r_fraction,
                        case.cell,
                        objective,
                        solver,
                        value,
                        seconds,
                    )
                )
    return agreement_decision(rows)


# --------------------------------------------------------------------------- finite differences


@dataclass
class FDCheck:
    passed: bool
    checked: int = 0  # directions compared (|fd| > min_fd)
    small: int = 0  # directions with |fd| <= min_fd (not compared)
    skipped: int = 0  # rank or absorption changes
    failed: int = 0
    redrawn: int = 0
    max_rel_error: float = 0.0
    by_objective: dict[str, dict[str, int]] = field(default_factory=dict)


def _carriers(ev, mode: str, weights: tuple[float, float, float]) -> tuple:
    """The identities of the paths carrying the objective's weight, in rank order."""
    years = ev.years
    out = []
    for c, (j, _), q in zip(weights, _exact_plan(len(years))[0], QUANTILES, strict=True):
        if not c:
            continue
        if mode == "exact":
            ranks = np.argpartition(years, (j, min(j + 1, len(years) - 1)))
            out.append((int(ranks[j]), int(ranks[min(j + 1, len(years) - 1)])))
        else:
            first, w = kernel_weights(len(years), q)
            out.append(tuple(np.argsort(years, kind="stable")[first : first + len(w)].tolist()))
    return tuple(out)


def _interior_mix(rng: np.random.Generator, lo: np.ndarray, hi: np.ndarray) -> np.ndarray:
    centre = project_box_simplex(np.full(len(lo), 1.0 / len(lo)), lo, hi)
    z = project_box_simplex(rng.dirichlet(np.ones(len(lo))), lo, hi)
    return 0.5 * centre + 0.5 * z


def fdcheck(
    bank: PathBank,
    ctx: OriginContext,
    *,
    mixes: int = 10,
    directions: int = 20,
    step: float = 1e-6,
    rel_tol: float = 1e-4,
    min_fd: float = 1e-8,
    max_skipped: int = 5,
    modes: tuple[str, ...] = ("exact", "kernel"),
) -> FDCheck:
    """The predeclared directional finite-difference gradient check (protocol §4)."""
    lo = np.asarray(ctx.menu.lower, dtype=float)
    hi = np.asarray(ctx.menu.upper, dtype=float)
    result = FDCheck(passed=True)
    for mode in modes:
        evaluator = Evaluator(bank, mode)
        for name, weights in QUANTILE_OBJECTIVES.items():
            rng = np.random.default_rng(
                derived_seed(
                    "fdcheck", ctx.menu.name, ctx.origin, bank.engine, bank.seed, mode, name
                )
            )
            stats = {"checked": 0, "small": 0, "skipped": 0, "failed": 0, "redrawn": 0}
            done = 0
            while done < mixes:
                if stats["redrawn"] > MAX_REDRAWS:
                    result.passed = False
                    break
                w = _interior_mix(rng, lo, hi)
                base = evaluator.evaluate(w)
                analytic_grad = base.gradient(weights)
                carriers = _carriers(base, mode, weights)
                absorbed = base.years == -1.0
                rows = []
                for _ in range(directions):
                    d = rng.normal(size=len(w))
                    d -= d.mean()
                    d /= np.linalg.norm(d)
                    plus = evaluator.evaluate(w + step * d)
                    minus = evaluator.evaluate(w - step * d)
                    if (
                        _carriers(plus, mode, weights) != carriers
                        or _carriers(minus, mode, weights) != carriers
                        or not np.array_equal(plus.years == -1.0, absorbed)
                        or not np.array_equal(minus.years == -1.0, absorbed)
                    ):
                        rows.append(None)
                        continue
                    fd = (plus.value(weights) - minus.value(weights)) / (2.0 * step)
                    rows.append((fd, float(analytic_grad @ d)))
                skipped = sum(r is None for r in rows)
                if skipped > max_skipped:
                    stats["redrawn"] += 1
                    continue
                done += 1
                stats["skipped"] += skipped
                for row in rows:
                    if row is None:
                        continue
                    fd, an = row
                    if abs(fd) <= min_fd:
                        stats["small"] += 1
                        continue
                    stats["checked"] += 1
                    rel = abs(an - fd) / abs(fd)
                    result.max_rel_error = max(result.max_rel_error, rel)
                    if rel > rel_tol:
                        stats["failed"] += 1
            result.by_objective[f"{mode}:{name}"] = stats
            for key in ("checked", "small", "skipped", "failed", "redrawn"):
                setattr(result, key, getattr(result, key) + stats[key])
    if result.failed:
        result.passed = False
    return result
