"""The v3 task (protocol v3 §3, §4, §5, §8.4): one (menu, origin month, engine) per task.

`run_task(inputs, spec, hooks)` runs, in a fixed order:

1. the 3-year origin context and the training bank (seed `PRIMARY_SEED`);
2. arm 6's side columns for the six risks (engine-independent, `knee.knee_columns`);
3. the v3 search (`search3.search_origin_v3`) with the engine's arm set (replay: all six arms;
   GARCH: arms 1-4, arm 4 recorded but not reported) and, at replay showcase origins, arm 4's
   side checks `LAMBDA_SIDE`;
4. at replay showcase origins where the 5-year window is eligible, the 5-year side check: all six
   arms on the 5-year context and its own bank;
5. every locked selection on the five independent banks of its own context (Bad, Typical, Good,
   mean, `ES_2.5`, U1, TDD).

Files per task, written atomically, the selections last (the completion marker, with the parent
digest in its metadata): `tasks/<base>.parquet` (selections), `tasks/pool/<base>.parquet` (the
pool, §4.4), `tasks/columns/<base>.parquet` (arm 1's anchor and arm 6's ladder per column) and
`tasks/evaluated/<base>.parquet`. The selections' metadata also carries the task's timings and
costs (`timings`: phase seconds, evaluations, evaluation seconds, pool rows and bytes).
"""

from __future__ import annotations

import json
import math
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow as pa

from portfoliosight.research.fixedrisk import contracts as C
from portfoliosight.research.fixedrisk import data
from portfoliosight.research.fixedrisk.anchors import geometry
from portfoliosight.research.fixedrisk.knee import knee_columns
from portfoliosight.research.fixedrisk.objective import figures
from portfoliosight.research.fixedrisk.objectives3 import FIELDS, tail_drawdown
from portfoliosight.research.fixedrisk.pool import PoolBuffer, write_pool
from portfoliosight.research.fixedrisk.search3 import OriginV3, search_origin_v3

KINDS = ("main", "side_lambda", "sens_5y")
TIMINGS_KEY = b"timings"
DIGEST_KEY = b"parent_digest"

SELECTION_SCHEMA = pa.schema(
    [
        ("sel_id", pa.string()),
        ("kind", pa.string()),
        ("menu", pa.string()),
        ("month", pa.string()),
        ("origin", pa.date32()),
        ("engine", pa.string()),
        ("seed", pa.int64()),
        ("lookback", pa.string()),
        ("tau_r", pa.float64()),
        ("lam", pa.float64()),
        ("r_fraction", pa.float64()),
        ("r", pa.float64()),
        ("arm", pa.string()),
        ("pooled", pa.bool_()),
        ("weights", pa.list_(pa.float64())),
        ("pool_row", pa.int64()),
        *((name, pa.float64()) for name in FIELDS),
        ("status", pa.string()),
        ("starts", pa.int64()),
        ("calls", pa.int64()),
        ("seconds", pa.float64()),
        ("solver", pa.string()),
    ]
)
COLUMN_SCHEMA = pa.schema(
    [
        ("menu", pa.string()),
        ("month", pa.string()),
        ("engine", pa.string()),
        ("lookback", pa.string()),
        ("r_fraction", pa.float64()),
        ("r", pa.float64()),
        ("sigma_min", pa.float64()),
        ("sigma_top", pa.float64()),
        ("w_F", pa.list_(pa.float64())),
        ("anchor_status", pa.string()),
        ("anchor_starts", pa.int64()),
        ("anchor_iterations", pa.int64()),
        ("anchor_seconds", pa.float64()),
        ("sobol_seconds", pa.float64()),
        ("knee_status", pa.string()),
        ("knee_level", pa.int64()),
        ("knee_neighbours", pa.list_(pa.int64())),
        ("knee_line_error", pa.float64()),
        ("knee_seconds", pa.float64()),
        ("w_knee", pa.list_(pa.float64())),
        ("w_app_frontier", pa.list_(pa.float64())),
        ("ladder_y", pa.list_(pa.float64())),
        ("ladder_z", pa.list_(pa.float64())),
        ("ladder_w", pa.list_(pa.float64())),
        ("ladder_members", pa.int64()),
    ]
)
EVALUATED_SCHEMA = pa.schema(
    [
        ("sel_id", pa.string()),
        ("test_seed", pa.int64()),
        ("bad", pa.float64()),
        ("typical", pa.float64()),
        ("good", pa.float64()),
        ("mean", pa.float64()),
        ("es_25", pa.float64()),
        ("u1", pa.float64()),
        ("tdd", pa.float64()),
    ]
)


def engine_arms(engine: str) -> tuple[str, ...]:
    return C.V3_ARMS if engine == "replay" else C.V3_GARCH_ARMS


def searches_per_task(spec: Any) -> int:
    """The arm searches a v3 task schedules (risk levels x searched arms, side checks, 5-year);
    its wall alarm is the per-arm ceiling times this."""
    arms = [a for a in engine_arms(spec.engine) if a in C.V3_SEARCHED]
    count = len(C.RISK_FRACTIONS) * len(arms)
    if spec.showcase and spec.engine == "replay":
        count += len(C.RISK_FRACTIONS) * len(C.LAMBDA_SIDE)
    if spec.lookback5 and spec.engine == "replay":
        count += len(C.RISK_FRACTIONS) * len(arms)
    return count


@dataclass
class TaskOutput3:
    selections: list[dict[str, Any]] = field(default_factory=list)
    columns: list[dict[str, Any]] = field(default_factory=list)
    evaluated: list[dict[str, Any]] = field(default_factory=list)
    pool: PoolBuffer = field(default_factory=PoolBuffer)
    phases: dict[str, float] = field(default_factory=dict)
    timings: dict[str, Any] = field(default_factory=dict)
    fit_failures: list[dict[str, Any]] = field(default_factory=list)
    garch_fallbacks: list[dict[str, Any]] = field(default_factory=list)
    garch_windows: dict[str, str] = field(default_factory=dict)
    garch_cap_hits: list[dict[str, Any]] = field(default_factory=list)
    month: str = ""
    origin: Any = None
    menu: str = ""
    engine: str = ""


def _float(x: Any) -> float | None:
    if x is None:
        return None
    x = float(x)
    return x if math.isfinite(x) else None


def selection_rows(
    result: OriginV3, *, kind_of: Callable[[dict], str], ctx: C.OriginContext, engine: str,
    seed: int,
) -> list[dict[str, Any]]:  # fmt: skip
    """The search's selections as rows of `SELECTION_SCHEMA` (sel_id unique per task)."""
    rows = []
    for s in result.selections:
        kind = kind_of(s)
        lam = s["lam"]
        ident = "|".join(
            [
                ctx.menu.name, ctx.month, engine, kind, ctx.lookback, str(seed),
                f"{s['r_fraction']:.6f}", s["arm"], "" if lam is None else f"{lam:g}",
                "pooled" if s["pooled"] else "native",
            ]
        )  # fmt: skip
        values = s["values"]
        row: dict[str, Any] = {
            "sel_id": ident,
            "kind": kind,
            "menu": ctx.menu.name,
            "month": ctx.month,
            "origin": ctx.origin,
            "engine": engine,
            "seed": int(seed),
            "lookback": ctx.lookback,
            "tau_r": float(s["tau_r"]),
            "lam": None if lam is None else float(lam),
            "r_fraction": float(s["r_fraction"]),
            "r": float(s["r"]),
            "arm": s["arm"],
            "pooled": bool(s["pooled"]),
            "weights": None if s["weights"] is None else [float(x) for x in s["weights"]],
            "pool_row": int(s["pool_row"]),
            "status": s["status"],
            "starts": int(s.get("starts", 0)),
            "calls": int(s.get("calls", 0)),
            "seconds": float(s.get("seconds", 0.0)),
            "solver": str(s.get("solver", "")),
        }
        for j, name in enumerate(FIELDS):
            row[name] = None if values is None else _float(values[j])
        rows.append(row)
    return rows


def fit_failed_rows(
    ctx: C.OriginContext, engine: str, seed: int, arms: Sequence[str], kind: str
) -> list[dict[str, Any]]:
    """One `garch_fit_failed` row per scheduled (r, arm[, pooled]) when the bank cannot be built."""
    rows = []
    for a in C.RISK_FRACTIONS:
        for arm in arms:
            shapes = (True, False) if arm in C.V3_SEARCHED else (arm == C.MAX_ENLC,)
            extra = [C.APP_FRONTIER] if arm == C.ENB_KNEE else []
            for name in [arm, *extra]:
                for pooled in shapes:
                    row: dict[str, Any] = dict.fromkeys(SELECTION_SCHEMA.names)
                    row.update(
                        sel_id="|".join([ctx.menu.name, ctx.month, engine, kind, ctx.lookback,
                                         str(seed), f"{a:.6f}", name, "",
                                         "pooled" if pooled else "native"]),
                        kind=kind, menu=ctx.menu.name, month=ctx.month, origin=ctx.origin,
                        engine=engine, seed=seed, lookback=ctx.lookback, tau_r=0.0,
                        r_fraction=a, r=math.nan, arm=name, pooled=pooled, pool_row=-1,
                        status=C.FIT_FAILED, starts=0, calls=0, seconds=0.0, solver="",
                    )  # fmt: skip
                    rows.append(row)
    return rows


def evaluate_independent(
    ctx: C.OriginContext,
    items: Sequence[tuple[str, np.ndarray]],
    engine: C.Engine,
    make_bank: C.BankFactory,
    seeds: Iterable[int] = C.TEST_SEEDS,
) -> list[dict[str, Any]]:
    """Each locked mix on each independent bank (v3 §5): year-end figures, U1 and TDD; equal
    weight vectors are scored once per bank."""
    unique: dict[bytes, int] = {}
    mixes: list[np.ndarray] = []
    for _, w in items:
        key = np.ascontiguousarray(w, dtype="<f8").tobytes()
        if key not in unique:
            unique[key] = len(mixes)
            mixes.append(w)
    rows: list[dict[str, Any]] = []
    if not mixes:
        return rows
    for seed in seeds:
        bank = make_bank(ctx, engine, seed)
        scored = []
        for w in mixes:
            years, drawdowns, _ = bank.path_terms(w)  # type: ignore[attr-defined]
            f = figures(years)
            scored.append((f, tail_drawdown(drawdowns)))
        del bank
        for ident, w in items:
            f, tdd = scored[unique[np.ascontiguousarray(w, dtype="<f8").tobytes()]]
            rows.append(
                {
                    "sel_id": ident, "test_seed": int(seed), "bad": f.bad, "typical": f.typical,
                    "good": f.good, "mean": f.mean, "es_25": f.es_25, "u1": f.utility("U1"),
                    "tdd": tdd,
                }
            )  # fmt: skip
    return rows


def run_task(
    inputs: data.ResearchInputs,
    spec: Any,
    hooks: Any,
    clock: Callable[[], float] = time.perf_counter,
) -> TaskOutput3:
    """Everything one v3 task computes; see the module docstring. `spec` is a `driver.TaskSpec`
    (its `calls` and `starts` are the solver budget); `hooks.make_bank` builds the banks."""
    from portfoliosight.research.fixedrisk.driver import (
        is_fit_failure,
        record_cap_hits,
        record_fallbacks,
    )

    engine: C.Engine = spec.engine
    arms = engine_arms(engine)
    out = TaskOutput3(menu=spec.menu, month=spec.month, engine=engine)
    phases = out.phases
    evals = {"evaluations": 0, "eval_calls": 0, "eval_seconds": 0.0}
    arm_seconds: dict[str, float] = {}
    to_evaluate: dict[str, list[tuple[str, np.ndarray]]] = {}
    contexts: dict[str, C.OriginContext] = {}

    def timed(name: str, since: float) -> None:
        phases[name] = phases.get(name, 0.0) + clock() - since

    def bank_for(ctx: C.OriginContext, seed: int) -> C.PathBank | None:
        try:
            built = hooks.make_bank(ctx, engine, seed)
        except Exception as exc:
            if not is_fit_failure(exc):
                raise
            out.fit_failures.append(
                {"lookback": ctx.lookback, "seed": seed, "error": f"{type(exc).__name__}: {exc}"}
            )
            return None
        record_fallbacks(out.garch_fallbacks, ctx, built)
        record_cap_hits(out.garch_cap_hits, ctx, seed, built)
        if not out.garch_windows:
            out.garch_windows = dict(getattr(built, "windows", None) or {})
        return built

    def one_context(ctx: C.OriginContext, kind: str, side: tuple[float, ...]) -> None:
        contexts[ctx.lookback] = ctx
        t = clock()
        bank = bank_for(ctx, C.PRIMARY_SEED)
        timed(f"bank_{ctx.lookback}", t)
        if bank is None:
            out.selections += fit_failed_rows(ctx, engine, C.PRIMARY_SEED, arms, kind)
            return
        t = clock()
        geo = geometry(ctx)
        knee = knee_columns(ctx, {a: geo.x(a) for a in C.RISK_FRACTIONS})
        timed(f"knee_{ctx.lookback}", t)
        t = clock()
        result = search_origin_v3(
            ctx, bank, arms=arms, calls=spec.calls, starts=spec.starts, side_lambdas=side,
            knee=knee,
        )  # fmt: skip
        timed(f"search_{ctx.lookback}", t)
        del bank

        def kind_of(s: dict) -> str:
            if s["arm"] == C.CRASH_PENALTY and s["lam"] not in (None, C.LAMBDA):
                return "side_lambda"
            return kind

        rows = selection_rows(result, kind_of=kind_of, ctx=ctx, engine=engine, seed=C.PRIMARY_SEED)
        out.selections += rows
        for row in rows:
            if row["weights"] is not None:
                to_evaluate.setdefault(ctx.lookback, []).append(
                    (row["sel_id"], np.asarray(row["weights"], dtype=float))
                )
            if row["arm"] in C.V3_SEARCHED and row["pooled"]:
                key = f"{row['kind']}:{row['arm']}"
                arm_seconds[key] = arm_seconds.get(key, 0.0) + row["seconds"]
        for record in result.columns:
            out.columns.append({"menu": ctx.menu.name, "month": ctx.month, "engine": engine,
                                **record})  # fmt: skip
        out.pool.extend(result.pool)
        evals["evaluations"] += result.evaluations
        evals["eval_calls"] += result.eval_calls
        evals["eval_seconds"] += result.eval_seconds

    t = clock()
    ctx = data.origin_context(inputs, spec.menu, spec.month)
    out.origin = ctx.origin
    timed("context_3y", t)
    replay = engine == "replay"
    one_context(ctx, "main", C.LAMBDA_SIDE if (spec.showcase and replay) else ())
    if spec.lookback5 and replay:
        t = clock()
        ctx5 = data.origin_context(inputs, spec.menu, spec.month, C.SENSITIVITY_LOOKBACK)
        timed("context_5y", t)
        one_context(ctx5, "sens_5y", ())

    if spec.evaluate:
        t = clock()
        for lookback, items in to_evaluate.items():
            out.evaluated += evaluate_independent(contexts[lookback], items, engine,
                                                  hooks.make_bank)  # fmt: skip
        timed("evaluation", t)
    out.timings = {
        "phases": dict(phases),
        "arm_search_seconds": arm_seconds,
        "pool_rows": len(out.pool),
        **evals,
        "seconds_per_evaluation": evals["eval_seconds"] / max(evals["evaluations"], 1),
    }
    return out


# ------------------------------------------------------------------------------- files


def task_paths(tasks_dir: Path, spec: Any) -> dict[str, Path]:
    return {
        "selections": tasks_dir / f"{spec.base}.parquet",
        "pool": tasks_dir / "pool" / f"{spec.base}.parquet",
        "columns": tasks_dir / "columns" / f"{spec.base}.parquet",
        "evaluated": tasks_dir / "evaluated" / f"{spec.base}.parquet",
    }


def write_task(tasks_dir: Path, spec: Any, out: TaskOutput3, digest: str) -> dict[str, Any]:
    """Write the task's four files, the selections last; returns the timings written."""
    from portfoliosight.research.fixedrisk.driver import (
        CAP_HITS_KEY,
        FALLBACKS_KEY,
        WINDOWS_KEY,
        _write_table,
    )

    paths = task_paths(tasks_dir, spec)
    meta = {DIGEST_KEY: digest.encode()}
    table = out.pool.table(
        menu=out.menu or spec.menu, month=out.month or spec.month, origin=out.origin,
        engine=out.engine or spec.engine, seed=C.PRIMARY_SEED,
    )  # fmt: skip
    pool_bytes = write_pool(paths["pool"], table, meta)
    _write_table(paths["columns"], out.columns, COLUMN_SCHEMA, digest)
    _write_table(paths["evaluated"], out.evaluated, EVALUATED_SCHEMA, digest)
    timings = {**out.timings, "pool_bytes": int(pool_bytes)}
    extra: dict[bytes, bytes] = {TIMINGS_KEY: json.dumps(timings).encode()}
    if out.garch_fallbacks:
        extra[FALLBACKS_KEY] = json.dumps(out.garch_fallbacks).encode()
    if out.garch_windows:
        extra[WINDOWS_KEY] = json.dumps(out.garch_windows).encode()
    if out.garch_cap_hits:
        extra[CAP_HITS_KEY] = json.dumps(out.garch_cap_hits).encode()
    _write_table(paths["selections"], out.selections, SELECTION_SCHEMA, digest, extra)
    return timings
