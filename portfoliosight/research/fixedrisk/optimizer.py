"""Fixed-risk search of one (menu, origin, engine, seed) (protocol §2, §4).

`search_origin` has the `contracts.SearchOrigin` signature. For each risk column `r = X(a)`:

1. Anchors (`anchors.py`, engine-independent, passed in or computed).
2. The column's Sobol pool: 256 of v1's broad candidates projected onto the risk band, evaluated
   once on the bank and reused by every cell and arm (a second block of 256 only when a cell has
   fewer than `starts` distinct feasible starts).
3. Interior cells in d order (`d25 -> d50 -> d75`, or `d_grid`), then the free cell. Per cell and
   arm, `starts` deduplicated feasible starts: interior (i) the point at fraction d on the segment
   `w_F -> w_MDP` projected onto the band, (ii) the previous cell's U1 solution (`w_F` for the
   first), (iii) the best Sobol point in the cell on the arm's objective, then the next best as
   replacements; free cell `w_F`, `w_MDP`, the best Sobol point. A start outside the cell's measure
   band is moved into it by the feasibility program `min (M(w) - M(r, d))^2` on the risk band (at
   most eight attempts per cell and arm); none reaching the band is `not_found`.
4. Each start is searched by the column's solver: SLSQP with analytic gradients ("exact_grad",
   "kernel_grad") under the bounds, the budget, the risk band (two inequalities) and the measure
   band (two more, interior cells), or COBYLA on the exact objective ("cobyla768", "cobyla128"
   function calls per start). Iterates are clipped to the bounds and renormalized before they are
   evaluated; each visited mix is evaluated once on the bank (exact Bad/Typical/Good) and shared by
   every arm.
5. Selections: the arm's native answer is its best feasible visited mix on its exact objective;
   the pooled answer is the best over the cell's pool (every arm's visits in the cell and the Sobol
   pool); the free cell's pool also holds every interior visit of the column (`pooled=True`), and
   its native answer is reported beside it (`pooled=False`). `native_only` runs arm U1 alone and
   reports native answers only (the stability procedure).
6. Outcomes without a locked mix are reported too, as `unselected` rows whose status is the label
   (`search_failed`, `not_found`, `collapsed` interior cells, `anchor_failed` cells and
   comparators), so every scheduled `(r, cell, arm)` row exists once (`scheduled_outcomes`).

No random draw is made here: the Sobol scramble seed is v1's fixed generator seed, so results depend
only on (menu, origin, engine, seed, r, cell, arm, start) and never on host or worker count.
"""

from __future__ import annotations

import math
import time
import warnings
from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import minimize

from .anchors import (
    ANCHOR_STARTS,
    Geometry,
    band_constraints,
    column_anchors,
    dr2_grad,
    geometry,
    slider_position,
    slsqp,
)
from .contracts import (
    ANCHOR_FAILED,
    ARM_ORDER,
    CELL_D,
    COLLAPSED,
    FEASIBILITY_TOL,
    GROWTH_BOUND_FAILED,
    INSUFFICIENT_STARTS,
    NOT_FOUND,
    OK,
    RISK_FRACTIONS,
    SEARCH_FAILED,
    STARTS,
    TAU_D,
    TAU_R,
    Anchors,
    OriginContext,
    OriginResult,
    PathBank,
    Selection,
    cell_name,
    unselected,
)
from .objective import Evaluation, Evaluator, arm_value, batch_quantiles, figures

SOLVERS = ("exact_grad", "kernel_grad", "cobyla768", "cobyla128")
COBYLA_CALLS = {"cobyla768": 768, "cobyla128": 128}
DEDUP_L1 = 1e-6
PENALTY = 1e6
RHOBEG = 0.05  # v1's COBYLA settings (research/search.py)
COBYLA_TOL = 1e-5
CATOL = 1e-8
INTERIOR = ("d25", "d50", "d75")
INTERIOR_D: tuple[float, ...] = tuple(float(CELL_D[c] or 0.0) for c in INTERIOR)


@dataclass(frozen=True)
class Cell:
    name: str
    d: float | None  # None: the free cell
    target: float = math.nan  # M(r, d)
    half: float = math.nan  # tau_d * span


@dataclass
class Visit:
    w: np.ndarray
    sigma: float
    measure: float
    btg: np.ndarray | None  # None: the bank refused the mix (growth bound failed banks only)
    band: bool  # evaluated, inside the bounds, the budget and the risk band (to 1e-8)


@dataclass
class ArmRun:
    cell: Cell
    arm: str
    label: str = OK
    visits: list[int] = field(default_factory=list)
    starts: int = 0
    iterations: int = 0
    seconds: float = 0.0
    native: int | None = None


class ColumnSearch:
    """One risk column on one bank: the visit archive, the Sobol pool and the cell searches."""

    def __init__(
        self,
        geo: Geometry,
        bank: PathBank,
        anchors: Anchors,
        tau_r: float,
        solver: str,
        starts: int,
    ):
        if solver not in SOLVERS:
            raise ValueError(f"solver must be one of {SOLVERS}, got {solver!r}")
        self.geo = geo
        self.bank = bank
        self.anchors = anchors
        self.r = anchors.r
        self.tau = tau_r
        self.growth_ok = bool(bank.growth_bound_ok)
        self.solver = solver if self.growth_ok else "cobyla768"
        self.evaluator = Evaluator(bank, "kernel" if self.solver == "kernel_grad" else "exact")
        self.starts = starts
        self.visits: list[Visit] = []
        self.index: dict[bytes, int] = {}
        self.sobol: dict[int, list[int]] = {}
        self.batch_evaluations = 0
        self._repairs: dict[tuple[str, bytes], np.ndarray | None] = {}
        self.span = anchors.M_MDP - anchors.M_F

    # ------------------------------------------------------------------ archive

    def _record(self, w: np.ndarray, btg: np.ndarray | None) -> int:
        vid = len(self.visits)
        sigma = self.geo.risk(w)
        band = (
            btg is not None
            and self.geo.in_domain(w)
            and abs(sigma - self.r) <= self.tau * self.r + FEASIBILITY_TOL
        )
        self.visits.append(Visit(w, sigma, self.geo.measure(w), btg, band))
        self.index[w.tobytes()] = vid
        return vid

    def evaluate(self, w: np.ndarray) -> tuple[int, Evaluation | None]:
        """Evaluate `w` on the bank with its path weights; record it once."""
        try:
            ev = self.evaluator.evaluate(w)
        except ValueError:
            ev = None
        vid = self.index.get(w.tobytes())
        if vid is None:
            vid = self._record(w, None if ev is None else ev.exact)
        return vid, ev

    def visit(self, w: np.ndarray) -> int:
        vid = self.index.get(w.tobytes())
        if vid is not None:
            return vid
        return self.evaluate(w)[0]

    def sobol_block(self, block: int) -> list[int]:
        if block in self.sobol:
            return self.sobol[block]
        points = self.geo.band_points(self.r, self.tau, block)
        ids: list[int] = []
        if points:
            mixes = np.vstack(points)
            if self.growth_ok:
                btg = batch_quantiles(self.bank.years(mixes))
                self.batch_evaluations += len(mixes)
                for w, row in zip(points, btg, strict=True):
                    vid = self.index.get(w.tobytes())
                    ids.append(self._record(w, row) if vid is None else vid)
            else:
                ids = [self.visit(w) for w in points]
        self.sobol[block] = ids
        return ids

    # ------------------------------------------------------------------ feasibility

    def in_band(self, v: Visit) -> bool:
        return v.band

    def in_cell(self, v: Visit, cell: Cell) -> bool:
        if not v.band:
            return False
        return cell.d is None or abs(v.measure - cell.target) <= cell.half + FEASIBILITY_TOL

    def _w_in_cell(self, w: np.ndarray, cell: Cell) -> bool:
        if not self.geo.in_band(w, self.r, self.tau):
            return False
        return (
            cell.d is None or abs(self.geo.measure(w) - cell.target) <= cell.half + FEASIBILITY_TOL
        )

    def measure_constraints(self, cell: Cell) -> list[dict]:
        if cell.d is None:
            return []
        geo, span = self.geo, self.span
        low, high = cell.target - cell.half, cell.target + cell.half
        return [
            {
                "type": "ineq",
                "fun": lambda w: (geo.measure(w) - low) / span,
                "jac": lambda w: dr2_grad(w, geo.sigma, geo.cov) / span,
            },
            {
                "type": "ineq",
                "fun": lambda w: (high - geo.measure(w)) / span,
                "jac": lambda w: -dr2_grad(w, geo.sigma, geo.cov) / span,
            },
        ]

    def repair(self, w: np.ndarray, cell: Cell) -> np.ndarray | None:
        """The feasibility program `min ((M - M(r, d)) / span)^2` on the risk band from `w`."""
        key = (cell.name, w.tobytes())
        if key in self._repairs:
            return self._repairs[key]
        geo, span, target = self.geo, self.span, cell.target

        def fun(x):
            return ((geo.measure(x) - target) / span) ** 2

        def jac(x):
            return 2.0 * (geo.measure(x) - target) / span**2 * dr2_grad(x, geo.sigma, geo.cov)

        res = slsqp(fun, jac, w, geo, band_constraints(geo, self.r, self.tau))
        end = geo.normalize(res.x)
        if not geo.in_band(end, self.r, self.tau):
            end = geo.project(end, self.r, self.tau)
        out = end if end is not None and self._w_in_cell(end, cell) else None
        self._repairs[key] = out
        return out

    # ------------------------------------------------------------------ starts

    def collect_starts(
        self, cell: Cell, arm: str, fixed: list[np.ndarray | None]
    ) -> list[np.ndarray]:
        accepted: list[np.ndarray] = []
        repairs = [ANCHOR_STARTS]

        def consider(w: np.ndarray | None) -> None:
            if w is None:
                return
            if not self._w_in_cell(w, cell):
                if cell.d is None:
                    w = self.geo.project(w, self.r, self.tau)
                elif repairs[0] > 0:
                    repairs[0] -= 1
                    w = self.repair(w, cell)
                else:
                    return
                if w is None or not self._w_in_cell(w, cell):
                    return
            if any(float(np.abs(w - a).sum()) <= DEDUP_L1 for a in accepted):
                return
            accepted.append(w)

        for w in fixed:
            if len(accepted) >= self.starts:
                break
            consider(w)
        for block in (0, 1):
            if len(accepted) >= self.starts:
                break
            ids = self.sobol_block(block)
            inside = [i for i in ids if self.in_cell(self.visits[i], cell)]
            inside.sort(key=lambda i: (-self.value(i, arm), i))
            for i in inside:
                if len(accepted) >= self.starts:
                    break
                consider(self.visits[i].w)
            if cell.d is not None and len(accepted) < self.starts:
                outside = [i for i in ids if self.visits[i].btg is not None and i not in inside]
                outside.sort(key=lambda i: (abs(self.visits[i].measure - cell.target), i))
                for i in outside:
                    if len(accepted) >= self.starts or repairs[0] <= 0:
                        break
                    consider(self.visits[i].w)
        return accepted

    # ------------------------------------------------------------------ local searches

    def _slsqp(self, cell: Cell, arm: str, x0: np.ndarray, run: ArmRun) -> np.ndarray:
        geo = self.geo
        last: dict[bytes, tuple[np.ndarray, Evaluation | None]] = {}

        def prep(x: np.ndarray) -> tuple[np.ndarray, Evaluation | None]:
            key = x.tobytes()
            if key not in last:
                v = geo.normalize(x)
                vid, ev = self.evaluate(v)
                run.visits.append(vid)
                last.clear()
                last[key] = (v, ev)
            return last[key]

        def fun(x: np.ndarray) -> float:
            _, ev = prep(x)
            return PENALTY if ev is None else -ev.value(arm)

        def jac(x: np.ndarray) -> np.ndarray:
            v, ev = prep(x)
            if ev is None:
                return np.zeros_like(x)
            gv = ev.gradient(arm)
            clipped = np.clip(x, geo.lo, geo.hi)
            gx = (gv - float(v @ gv)) / clipped.sum()
            gx[(x < geo.lo) | (x > geo.hi)] = 0.0
            return -gx

        constraints = band_constraints(geo, self.r, self.tau) + self.measure_constraints(cell)
        res = slsqp(fun, jac, x0, geo, constraints)
        run.iterations += int(res.nit)
        return res.x

    def _cobyla(self, cell: Cell, arm: str, x0: np.ndarray, run: ArmRun, calls: int):
        geo = self.geo
        lo, hi, cov, r2 = geo.lo, geo.hi, geo.cov, self.r**2
        lo2, hi2 = (1.0 - self.tau) ** 2, (1.0 + self.tau) ** 2
        span = self.span

        def full(y: np.ndarray) -> np.ndarray:
            return np.append(y, 1.0 - y.sum())

        def fun(y: np.ndarray) -> float:
            vid = self.visit(geo.normalize(full(y)))
            run.visits.append(vid)
            btg = self.visits[vid].btg
            return PENALTY if btg is None else -arm_value(btg, arm)

        def cons(y: np.ndarray) -> np.ndarray:
            w = full(y)
            var = float(w @ cov @ w) / r2
            parts = [w - lo, hi - w, [var - lo2, hi2 - var]]
            if cell.d is not None:
                m = geo.measure(w)
                parts.append(
                    [(m - cell.target + cell.half) / span, (cell.target + cell.half - m) / span]
                )
            return np.concatenate(parts)

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            res = minimize(
                fun,
                x0[:-1],
                method="COBYLA",
                constraints=[{"type": "ineq", "fun": cons}],
                options={"maxiter": calls, "rhobeg": RHOBEG, "tol": COBYLA_TOL, "catol": CATOL},
            )
        run.iterations += int(res.nfev)
        return full(res.x)

    def run_arm(self, cell: Cell, arm: str, fixed: list[np.ndarray | None]) -> ArmRun:
        clock = time.perf_counter()
        run = ArmRun(cell, arm)
        starts = self.collect_starts(cell, arm, fixed)
        run.starts = len(starts)
        if not starts:
            run.label = NOT_FOUND if cell.d is not None else SEARCH_FAILED
        for x0 in starts:
            run.visits.append(self.visit(x0))
            if self.solver in COBYLA_CALLS:
                x = self._cobyla(cell, arm, x0, run, COBYLA_CALLS[self.solver])
            else:
                x = self._slsqp(cell, arm, x0, run)
            end = self.geo.normalize(x)
            if not self.geo.in_band(end, self.r, self.tau):
                end = self.geo.project(end, self.r, self.tau)
            if end is not None:
                run.visits.append(self.visit(end))
        run.native = self.best(run.visits, cell, arm)
        if starts and run.native is None:
            run.label = SEARCH_FAILED
        elif starts and len(starts) < self.starts:
            run.label = INSUFFICIENT_STARTS
        if not self.growth_ok and run.label in (OK, INSUFFICIENT_STARTS):
            run.label = GROWTH_BOUND_FAILED
        run.seconds = time.perf_counter() - clock
        return run

    def value(self, vid: int, arm: str) -> float:
        btg = self.visits[vid].btg
        return -math.inf if btg is None else arm_value(btg, arm)

    def best(self, ids, cell: Cell, arm: str) -> int | None:
        best, best_key = None, None
        for i in sorted(set(ids)):
            v = self.visits[i]
            if not self.in_cell(v, cell):
                continue
            key = self.value(i, arm)
            if best_key is None or key > best_key:
                best, best_key = i, key
        return best


# --------------------------------------------------------------------------- the entry point


def _select(
    ctx: OriginContext,
    bank: PathBank,
    anchors: Anchors,
    col: ColumnSearch,
    run: ArmRun,
    vid: int,
    pooled: bool,
    solver: str,
) -> dict:
    """A selection's fields except its figures, which come from one batch evaluation."""
    v = col.visits[vid]
    return {
        "menu": ctx.menu.name,
        "origin": ctx.origin,
        "engine": bank.engine,
        "seed": bank.seed,
        "r_fraction": anchors.r_fraction,
        "r": anchors.r,
        "cell": run.cell.name,
        "arm": run.arm,
        "pooled": pooled,
        "weights": v.w,
        "sigma": v.sigma,
        "measure": v.measure,
        "d": slider_position(v.measure, anchors),
        "status": run.label,
        "starts": run.starts,
        "iterations": run.iterations,
        "seconds": run.seconds,
        "solver": solver,
    }


def _with_figures(
    bank: PathBank, rows: list[dict], refused: list[Selection] | None = None
) -> list[Selection]:
    """Exact figures of every selected mix from one bank call (per mix if the bank refuses one).

    A mix the bank refuses has no figures; it goes to `refused` as a `search_failed` row."""
    if not rows:
        return []
    mixes = np.vstack([row["weights"] for row in rows])
    try:
        years = bank.years(mixes)
        figs = [figures(years[:, j]) for j in range(len(rows))]
    except ValueError:
        figs = []
        for w in mixes:
            try:
                figs.append(figures(bank.years(w[None, :])[:, 0]))
            except ValueError:
                figs.append(None)
    out = []
    for row, f in zip(rows, figs, strict=True):
        if f is not None:
            out.append(Selection(**row, figures=f))
        elif refused is not None:
            refused.append(_unselected_row(row, SEARCH_FAILED))
    return out


def _unselected_row(row: dict, status: str) -> Selection:
    keep = ("menu", "origin", "engine", "seed", "r_fraction", "r", "cell", "arm", "pooled")
    return unselected(
        **{k: row[k] for k in keep},
        status=status,
        solver=row["solver"],
        starts=row["starts"],
        iterations=row["iterations"],
        seconds=row["seconds"],
    )


def search_column(
    geo: Geometry,
    bank: PathBank,
    anchors: Anchors,
    *,
    arms: tuple[str, ...],
    d_grid: tuple[float, ...],
    include_free: bool,
    tau_r: float,
    solver: str,
    starts: int,
) -> tuple[ColumnSearch, list[ArmRun]]:
    """Every cell and arm of one column, interior cells in `d_grid` order, free cell last."""
    col = ColumnSearch(geo, bank, anchors, tau_r, solver, starts)
    runs: list[ArmRun] = []
    w_f, w_mdp = anchors.w_F, anchors.w_MDP
    lead = "U1" if "U1" in arms else arms[0]
    previous = w_f
    if not anchors.collapsed:
        for d in d_grid:
            cell = Cell(cell_name(d), d, anchors.M_F + d * col.span, TAU_D * col.span)
            line = geo.project((1.0 - d) * w_f + d * w_mdp + 0.0, anchors.r, tau_r)
            cell_runs = [col.run_arm(cell, arm, [line, previous]) for arm in arms]
            runs += cell_runs
            lead_run = next(run for run in cell_runs if run.arm == lead)
            if lead_run.native is not None:
                previous = col.visits[lead_run.native].w
    if include_free:
        free = Cell("free", None)
        runs += [col.run_arm(free, arm, [w_f, w_mdp]) for arm in arms]
    return col, runs


def search_origin(
    ctx: OriginContext,
    bank: PathBank,
    *,
    anchors: list[Anchors] | None = None,
    arms: tuple[str, ...] = ARM_ORDER,
    risk_fractions: tuple[float, ...] = RISK_FRACTIONS,
    d_grid: tuple[float, ...] | None = None,
    include_free: bool = True,
    native_only: bool = False,
    tau_r: float = TAU_R,
    solver: str = "exact_grad",
    starts: int = STARTS,
) -> OriginResult:
    """The fixed-risk search of one (menu, origin, engine, seed); see the module docstring."""
    clock = time.perf_counter()
    if solver not in SOLVERS:
        raise ValueError(f"solver must be one of {SOLVERS}, got {solver!r}")
    if native_only:
        arms = ("U1",)
    grid = INTERIOR_D if d_grid is None else tuple(d_grid)
    geo = geometry(ctx)
    given = {a.r_fraction: a for a in anchors or []}
    result = OriginResult(menu=ctx.menu.name, origin=ctx.origin, engine=bank.engine, seed=bank.seed)
    labels: dict[str, int] = {}
    pending: list[dict] = []
    pending_comparators: list[dict] = []
    evaluations = 0
    cell_names = [cell_name(d) for d in grid] + (["free"] if include_free else [])

    def count(label: str, n: int = 1) -> None:
        labels[label] = labels.get(label, 0) + n

    def missing(anchor: Anchors, cell: str, arm: str, pooled: bool, status: str, **run) -> None:
        result.unselected.append(
            unselected(
                menu=ctx.menu.name, origin=ctx.origin, engine=bank.engine, seed=bank.seed,
                r_fraction=anchor.r_fraction, r=anchor.r, cell=cell, arm=arm, pooled=pooled,
                status=status, solver=run.pop("solver", solver), **run,
            )
        )  # fmt: skip

    def shapes(cell: str) -> tuple[bool, ...]:
        """The rows a (cell, arm) reports: native only, pooled, or pooled and native (free)."""
        if native_only:
            return (False,)
        return (True, False) if cell == "free" else (True,)

    for a in risk_fractions:
        anchor = given.get(a) or column_anchors(geo, a, tau_r)
        result.anchors.append(anchor)
        if anchor.status != OK:
            count(ANCHOR_FAILED, len(cell_names) * len(arms))
            for cell in cell_names:
                for arm in arms:
                    for pooled in shapes(cell):
                        missing(anchor, cell, arm, pooled, ANCHOR_FAILED)
            if not native_only:
                for arm in ("F", "BS"):
                    missing(anchor, "free", arm, False, ANCHOR_FAILED)
            continue
        col, runs = search_column(
            geo,
            bank,
            anchor,
            arms=arms,
            d_grid=grid,
            include_free=include_free,
            tau_r=tau_r,
            solver=solver,
            starts=starts,
        )
        used = col.solver
        if anchor.collapsed:
            count(COLLAPSED, len(grid) * len(arms))
            for d in grid:
                for arm in arms:
                    for pooled in shapes(cell_name(d)):
                        missing(anchor, cell_name(d), arm, pooled, COLLAPSED, solver=used)
        for run in runs:
            count(run.label)
            if run.native is None:
                for pooled in shapes(run.cell.name):
                    missing(
                        anchor, run.cell.name, run.arm, pooled, run.label, solver=used,
                        starts=run.starts, iterations=run.iterations, seconds=run.seconds,
                    )  # fmt: skip
                continue
            if native_only:
                pending.append(_select(ctx, bank, anchor, col, run, run.native, False, used))
                continue
            if run.cell.d is None:
                pool = [i for i, v in enumerate(col.visits) if col.in_band(v)]
            else:
                pool = [i for r_ in runs if r_.cell.name == run.cell.name for i in r_.visits]
                pool += [i for ids in col.sobol.values() for i in ids]
            pooled = col.best(pool, run.cell, run.arm)
            if pooled is not None:
                pending.append(_select(ctx, bank, anchor, col, run, pooled, True, used))
            if run.cell.d is None:
                pending.append(_select(ctx, bank, anchor, col, run, run.native, False, used))
        evaluations += col.evaluator.calls + col.batch_evaluations
        if not native_only:
            for arm, w in (("F", anchor.w_F), ("BS", anchor.w_BS)):
                run = ArmRun(Cell("free", None), arm, OK, [], anchor.starts, anchor.iterations)
                run.seconds = anchor.seconds
                vid = col.visit(w)
                pending_comparators.append(_select(ctx, bank, anchor, col, run, vid, False, used))
    result.selections = _with_figures(bank, pending, result.unselected)
    result.comparators = _with_figures(bank, pending_comparators, result.unselected)
    evaluations += len(pending) + len(pending_comparators)
    result.labels = labels
    result.evaluations = evaluations
    result.seconds = time.perf_counter() - clock
    return result
