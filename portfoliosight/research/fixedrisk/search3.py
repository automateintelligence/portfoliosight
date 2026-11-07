"""The v3 search of one (menu, origin, lookback, engine, seed) (protocol v3 §2, §4, as amended
2026-11-07).

Per risk column `r = X(a)`, on one bank, every mix evaluated is scored on the full objective set
(`objectives3.Scorer`) and recorded in the task's pool (`pool.PoolBuffer`):

1. arm 1, the frontier mix: `argmax mu_s'w` on the narrow band (`TAU_NARROW`), v2's anchor
   program (`anchors.maximize_on_band` from `anchors._anchor_starts`); every start and end point
   it produced is recorded (source `anchor`);
2. arm 6's side column (`knee.py`): every member of its ENB pool (source `knee_ladder`); the knee
   mix is arm 6, the frontier node a reference row (`app_frontier`);
3. the column's 256 Sobol points projected onto the narrow band (inside the wide band too),
   scored once and shared by the arms (source `sobol`);
4. arms 2, 3 and 4 (U1 on the wide band, min TDD on the narrow band, U1 - lambda H on the wide
   band), each searched by COBYLA (`optimizer.cobyla_on_band`, `calls` per start) from three
   deduplicated starts: the frontier mix, the knee mix (projected onto the arm's band if
   needed), then the best Sobol points on the arm's objective inside its band. Every solver call
   and the end point are recorded (source `search`);
5. selections: a searched arm's pooled selection is the best member of the column's pool inside
   its band on its objective (ties to the earlier record), its native result the best of its own
   search; arm 5 is the wide-band member with a defined ENLC and `mu_s'w >= mu_s'w_F - 50 bp`
   with the highest ENLC (ties to the higher `mu_s'w`, then the earlier record);
6. arm 4's side checks (`side_lambdas`, showcase origins) run after the main selections, so they
   never change them; each side check's pooled selection reads the main rows and its own.

No random draw is made here: Sobol points and starts depend only on (menu, origin, lookback, r).
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from . import contracts as C
from .anchors import Geometry, _anchor_starts, geometry, maximize_on_band
from .knee import KneeColumn, KneeResult, knee_columns
from .objectives3 import INDEX, Scorer, history_returns, origin_basis
from .optimizer import DEDUP_L1, PENALTY, cobyla_on_band
from .pool import PoolBuffer

MAIN = "main"


@dataclass
class ArmRun:
    arm: str
    lam: float | None
    label: str = C.OK
    starts: int = 0
    calls: int = 0
    seconds: float = 0.0
    rows: list[int] = field(default_factory=list)
    native: int | None = None


@dataclass
class OriginV3:
    """Everything one v3 search produced."""

    selections: list[dict[str, Any]] = field(default_factory=list)
    columns: list[dict[str, Any]] = field(default_factory=list)  # anchors and knee per column
    pool: PoolBuffer = field(default_factory=PoolBuffer)
    labels: dict[str, int] = field(default_factory=dict)
    seconds: dict[str, float] = field(default_factory=dict)  # phase -> wall seconds
    evaluations: int = 0
    eval_calls: int = 0
    eval_seconds: float = 0.0


def arm_tau(arm: str) -> float:
    return C.ARM_TAU.get(arm, C.TAU_WIDE)


class Column:
    """One risk column on one bank: the scorer, the column's pool rows and its searches."""

    def __init__(
        self,
        geo: Geometry,
        scorer: Scorer,
        pool: PoolBuffer,
        *,
        lookback: str,
        r_fraction: float,
        r: float,
        calls: int,
        starts: int,
    ) -> None:
        self.geo, self.scorer, self.pool = geo, scorer, pool
        self.lookback, self.a, self.r = lookback, r_fraction, r
        self.calls, self.starts = calls, starts
        self.ids: list[int] = []  # pool row ids of this column, in record order
        self.lams: dict[int, float | None] = {}
        self.sobol: list[int] = []

    # ---------------------------------------------------------------- recording

    def add(
        self,
        w: np.ndarray,
        source: str,
        arm: str = "",
        lam: float | None = None,
        start: int = -1,
        call: int = -1,
    ) -> int:
        values = self.scorer.evaluate(w)
        rid = self.pool.add(
            lookback=self.lookback, r_fraction=self.a, r=self.r, lam=lam, arm=arm, start=start,
            call=call, source=source, weights=w, values=values,
        )  # fmt: skip
        self.ids.append(rid)
        self.lams[rid] = lam
        return rid

    def value(self, rid: int, name: str) -> float:
        return float(self.pool.values[rid][INDEX[name]])

    def weights(self, rid: int) -> np.ndarray:
        return self.pool.weights[rid]

    def in_band(self, rid: int, tau: float) -> bool:
        flag = "in_narrow" if tau == C.TAU_NARROW else "in_wide"
        if tau not in (C.TAU_NARROW, C.TAU_WIDE):
            return self.geo.in_band(self.weights(rid), self.r, tau)
        return self.value(rid, flag) == 1.0

    def objective(self, rid: int, arm: str, lam: float | None) -> float:
        """The arm's objective, higher is better; -inf where it is undefined."""
        if arm == C.U1_ARM:
            x = self.value(rid, "u1")
        elif arm == C.MIN_TDD:
            x = -self.value(rid, "tdd")
        elif arm == C.CRASH_PENALTY:
            x = self.value(rid, "u1") - float(lam if lam is not None else C.LAMBDA) * self.value(
                rid, "h"
            )
        else:
            raise ValueError(f"{arm!r} is not a searched arm")
        return x if math.isfinite(x) else -math.inf

    def best(self, ids, arm: str, lam: float | None) -> int | None:
        tau = arm_tau(arm)
        best, key = None, -math.inf
        for rid in ids:
            if not self.in_band(rid, tau):
                continue
            v = self.objective(rid, arm, lam)
            if best is None or v > key:
                best, key = rid, v
        return best

    # ---------------------------------------------------------------- searches

    def collect_starts(
        self, arm: str, lam: float | None, fixed: list[np.ndarray | None]
    ) -> list[np.ndarray]:
        tau = arm_tau(arm)
        accepted: list[np.ndarray] = []

        def consider(w: np.ndarray | None) -> None:
            if w is None or len(accepted) >= self.starts or not np.isfinite(w).all():
                return
            if not self.geo.in_band(w, self.r, tau):
                w = self.geo.project(w, self.r, tau)
                if w is None or not self.geo.in_band(w, self.r, tau):
                    return
            if any(float(np.abs(w - a).sum()) <= DEDUP_L1 for a in accepted):
                return
            accepted.append(w)

        for w in fixed:
            consider(w)
        ranked = [rid for rid in self.sobol if self.in_band(rid, tau)]
        ranked.sort(key=lambda rid: (-self.objective(rid, arm, lam), rid))
        for rid in ranked:
            if len(accepted) >= self.starts:
                break
            consider(self.weights(rid))
        return accepted

    def run_arm(
        self, arm: str, lam: float | None, fixed: list[np.ndarray | None], growth_ok: bool
    ) -> ArmRun:
        clock = time.perf_counter()
        tau = arm_tau(arm)
        run = ArmRun(arm, lam)
        starts = self.collect_starts(arm, lam, fixed)
        run.starts = len(starts)
        for k, x0 in enumerate(starts):
            counter = [0]

            def fun(w: np.ndarray, k: int = k, counter: list[int] = counter) -> float:
                rid = self.add(w, "search", arm, lam, start=k, call=counter[0])
                counter[0] += 1
                run.rows.append(rid)
                v = self.objective(rid, arm, lam)
                return -v if math.isfinite(v) else PENALTY

            x, nfev = cobyla_on_band(self.geo, self.r, tau, x0, fun, self.calls)
            run.calls += nfev
            end = self.geo.normalize(x)
            if not self.geo.in_band(end, self.r, tau):
                end = self.geo.project(end, self.r, tau)
            if end is not None:
                run.rows.append(self.add(end, "search", arm, lam, start=k, call=counter[0]))
        run.native = self.best(run.rows, arm, lam)
        if not starts or run.native is None:
            run.label = C.SEARCH_FAILED
        elif len(starts) < self.starts:
            run.label = C.INSUFFICIENT_STARTS
        if not growth_ok and run.label in (C.OK, C.INSUFFICIENT_STARTS):
            run.label = C.GROWTH_BOUND_FAILED
        run.seconds = time.perf_counter() - clock
        return run

    def main_ids(self) -> list[int]:
        """The column's rows that are not side checks (lam null or the main lambda)."""
        return [rid for rid in self.ids if self.lams[rid] in (None, C.LAMBDA)]


def frontier_anchor(
    geo: Geometry, r: float, tau: float
) -> tuple[np.ndarray | None, list[np.ndarray], int, int]:
    """Arm 1: `argmax mu_s'w` on the band, v2's anchor program; its answer, every start and end
    point it produced, its starts and its SLSQP iterations."""
    starts = _anchor_starts(geo, r, tau, geo.frontier_surrogate(r))
    visited: list[np.ndarray] = []
    w, iterations = maximize_on_band(
        geo, r, tau, lambda w: float(geo.mu_s @ w), lambda w: geo.mu_s, starts, visited
    )
    return w, visited, len(starts), iterations


def _distinct(mixes: list[np.ndarray]) -> list[np.ndarray]:
    seen: set[bytes] = set()
    out = []
    for w in mixes:
        key = np.ascontiguousarray(w, dtype=np.float64).tobytes()
        if key not in seen and np.isfinite(w).all():
            seen.add(key)
            out.append(w)
    return out


def search_origin_v3(
    ctx: C.OriginContext,
    bank: C.PathBank,
    *,
    arms: tuple[str, ...] = C.V3_ARMS,
    risk_fractions: tuple[float, ...] = C.RISK_FRACTIONS,
    calls: int = 768,
    starts: int = C.V3_STARTS,
    side_lambdas: tuple[float, ...] = (),
    knee: KneeResult | None = None,
    solver: str = C.V3_SOLVER,
) -> OriginV3:
    """The v3 search of one origin on one bank; see the module docstring.

    `knee` (arm 6's side columns, engine-independent) is computed when not given. Selection rows
    carry the pool row id of their mix (`pool_row`) and every objective value.
    """
    clock = time.perf_counter()
    out = OriginV3()
    geo = geometry(ctx)
    history = history_returns(ctx)
    basis = origin_basis(ctx)
    growth_ok = bool(bank.growth_bound_ok)
    if knee is None:
        t = time.perf_counter()
        knee = knee_columns(ctx, {a: geo.x(a) for a in risk_fractions})
        out.seconds["knee"] = time.perf_counter() - t
    knees: dict[float, KneeColumn] = {col.r_fraction: col for col in knee.columns}
    searched = [arm for arm in C.V3_SEARCHED if arm in arms]

    def count(label: str) -> None:
        out.labels[label] = out.labels.get(label, 0) + 1

    for a in risk_fractions:
        r = geo.x(a)
        scorer = Scorer(geo, bank, history, basis, r)
        col = Column(
            geo, scorer, out.pool, lookback=ctx.lookback, r_fraction=a, r=r, calls=calls,
            starts=starts,
        )  # fmt: skip
        seconds: dict[str, float] = {}

        def select(
            arm: str, rid: int | None, status: str, *, pooled: bool, lam=None, a=a, r=r,
            col=col, **run,
        ) -> None:  # fmt: skip
            row: dict[str, Any] = {
                "r_fraction": a, "r": r, "arm": arm, "lam": lam, "pooled": pooled,
                "tau_r": arm_tau(arm) if arm in C.ARM_TAU else 0.0,
                "status": status if rid is not None or status != C.OK else C.SEARCH_FAILED,
                "pool_row": -1 if rid is None else int(rid),
                "weights": None if rid is None else col.weights(rid),
                "values": None if rid is None else out.pool.values[rid],
                "solver": run.pop("solver", ""), **run,
            }  # fmt: skip
            out.selections.append(row)
            count(row["status"])

        # 1. arm 1
        t = time.perf_counter()
        w_f, visited, anchor_starts, anchor_iters = frontier_anchor(geo, r, C.TAU_NARROW)
        f_rid = None
        for w in _distinct(visited):
            rid = col.add(w, "anchor", C.FRONTIER)
            if w_f is not None and np.array_equal(w, w_f):
                f_rid = rid
        if w_f is not None and f_rid is None:
            f_rid = col.add(w_f, "anchor", C.FRONTIER)
        seconds["anchor"] = time.perf_counter() - t
        anchor_status = C.OK if f_rid is not None else C.ANCHOR_FAILED

        # 2. arm 6's side column
        kc = knees.get(a)
        k_rid = front_rid = None
        if kc is not None and kc.status != C.ANCHOR_FAILED:
            for w in _distinct(kc.members):
                rid = col.add(w, "knee_ladder", C.ENB_KNEE)
                if np.array_equal(w, kc.w_knee):
                    k_rid = rid
                if np.array_equal(w, kc.w_front):
                    front_rid = rid
            if k_rid is None:
                k_rid = col.add(kc.w_knee, "knee_ladder", C.ENB_KNEE)
            if front_rid is None:
                front_rid = col.add(kc.w_front, "knee_ladder", C.ENB_KNEE)

        # 3. Sobol pool, narrow band
        t = time.perf_counter()
        for w in geo.band_points(r, C.TAU_NARROW, 0):
            col.sobol.append(col.add(w, "sobol"))
        seconds["sobol"] = time.perf_counter() - t

        # 4. searched arms
        w_knee = kc.w_knee if kc is not None and k_rid is not None else None
        fixed = [w_f, w_knee]
        runs = {arm: col.run_arm(arm, C.LAMBDA if arm == C.CRASH_PENALTY else None, fixed,
                                 growth_ok) for arm in searched}  # fmt: skip

        # 5. selections
        main = col.main_ids()
        if C.FRONTIER in arms:
            select(C.FRONTIER, f_rid, anchor_status, pooled=False, starts=anchor_starts,
                   calls=anchor_iters, seconds=seconds["anchor"], solver="slsqp")  # fmt: skip
        for arm in searched:
            run = runs[arm]
            info = dict(starts=run.starts, calls=run.calls, seconds=run.seconds, solver=solver)
            lam = run.lam
            pooled = col.best(main, arm, lam) if run.native is not None else None
            select(arm, pooled, run.label, pooled=True, lam=lam, **info)
            select(arm, run.native, run.label, pooled=False, lam=lam, **info)
        if C.MAX_ENLC in arms:
            t = time.perf_counter()
            if f_rid is None:
                rid, status = None, C.ANCHOR_FAILED
            else:
                rid = _max_enlc(col, main, col.value(f_rid, "mu"))
                status = C.OK if rid is not None else C.NO_ELIGIBLE
            select(C.MAX_ENLC, rid, status, pooled=True, starts=0, calls=0,
                   seconds=time.perf_counter() - t, solver="rerank")  # fmt: skip
        if C.ENB_KNEE in arms:
            status = C.ANCHOR_FAILED if kc is None or k_rid is None else kc.status
            info = dict(starts=0, calls=0, seconds=kc.seconds if kc else 0.0, solver="app_ladder")
            select(C.ENB_KNEE, k_rid, status, pooled=False, **info)
            select(C.APP_FRONTIER, front_rid, status if front_rid is not None else
                   C.ANCHOR_FAILED, pooled=False, **info)  # fmt: skip

        # 6. arm 4 side checks
        if C.CRASH_PENALTY in arms:
            for lam in side_lambdas:
                run = col.run_arm(C.CRASH_PENALTY, lam, fixed, growth_ok)
                own = [rid for rid in col.ids if col.lams[rid] == lam]
                pooled = col.best(main + own, C.CRASH_PENALTY, lam) if run.native is not None \
                    else None  # fmt: skip
                info = dict(starts=run.starts, calls=run.calls, seconds=run.seconds,
                            solver=solver)  # fmt: skip
                select(C.CRASH_PENALTY, pooled, run.label, pooled=True, lam=lam, **info)
                select(C.CRASH_PENALTY, run.native, run.label, pooled=False, lam=lam, **info)

        out.columns.append(_column_record(ctx, geo, a, r, w_f, anchor_status, anchor_starts,
                                          anchor_iters, seconds, kc))  # fmt: skip
        out.evaluations += scorer.evaluations
        out.eval_calls += scorer.calls
        out.eval_seconds += scorer.seconds
    out.seconds["total"] = time.perf_counter() - clock
    return out


def _max_enlc(col: Column, ids: list[int], mu_f: float) -> int | None:
    """Arm 5: highest ENLC among the eligible rows; ties to higher mu_s'w, then earlier."""
    best, key = None, None
    for rid in ids:
        enlc, mu = col.value(rid, "enlc"), col.value(rid, "mu")
        if not (col.in_band(rid, C.TAU_WIDE) and math.isfinite(enlc)):
            continue
        if mu < mu_f - C.ENLC_RETURN_TOL:
            continue
        k = (enlc, mu)
        if key is None or k > key:
            best, key = rid, k
    return best


def _vec(w: np.ndarray | None) -> list[float] | None:
    return None if w is None else [float(x) for x in np.asarray(w, dtype=float)]


def _column_record(
    ctx: C.OriginContext,
    geo: Geometry,
    a: float,
    r: float,
    w_f: np.ndarray | None,
    status: str,
    starts: int,
    iterations: int,
    seconds: dict[str, float],
    kc: KneeColumn | None,
) -> dict[str, Any]:
    """One row of the task's column table: arm 1's anchor and arm 6's side column."""
    return {
        "lookback": ctx.lookback,
        "r_fraction": float(a),
        "r": float(r),
        "sigma_min": float(geo.sigma_min),
        "sigma_top": float(geo.sigma_top),
        "w_F": _vec(w_f),
        "anchor_status": status,
        "anchor_starts": int(starts),
        "anchor_iterations": int(iterations),
        "anchor_seconds": float(seconds.get("anchor", math.nan)),
        "sobol_seconds": float(seconds.get("sobol", math.nan)),
        "knee_status": kc.status if kc else C.ANCHOR_FAILED,
        "knee_level": int(kc.level) if kc else -1,
        "knee_neighbours": list(kc.neighbours) if kc else [-1, -1],
        "knee_line_error": float(kc.line_error) if kc else math.nan,
        "knee_seconds": float(kc.seconds) if kc else math.nan,
        "w_knee": _vec(kc.w_knee) if kc else None,
        "w_app_frontier": _vec(kc.w_front) if kc else None,
        "ladder_y": _vec(kc.ladder_y) if kc else None,
        "ladder_z": _vec(kc.ladder_z) if kc else None,
        "ladder_w": _vec(kc.ladder_w.reshape(-1)) if kc else None,
        "ladder_members": len(kc.members) if kc else 0,
    }
