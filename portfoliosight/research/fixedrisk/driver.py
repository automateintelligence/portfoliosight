"""The run driver of the fixed-risk experiment (protocol §3, §8).

Task unit: (menu, origin month, engine). In one process a task
 1. builds the origin context and the primary-seed bank;
 2. runs the main grid (all arms, all cells, `RISK_FRACTIONS`) with `anchors=None`, which computes
    the origin's anchors once; every later call at the same context and band reuses them;
 3. at a stability origin (scheduled index 0, 4, 8, ...) runs arm U1 native-only on the primary
    seed (like for like) and on each stability seed;
 4. at a showcase origin runs the 48-column x 19-position surface (arm U1), then the sensitivities:
    `tau_r = 0.001` main grid, the 5-year lookback main grid where eligible, and `d` in (0, 1)
    arm U1 on the main risk levels;
 5. evaluates every locked selection (main, comparators, showcase, sensitivities) on the five
    independent test banks of its own training context.

Every scheduled (r, cell, arm) outcome is one selections row: outcomes without a locked mix (the
optimizer's `unselected` rows, and every search on a bank whose GARCH fit failed) have status =
their label, empty weights and NaN figures, so the measurements can count and exclude them.
A holding that fits on neither GARCH dynamics window and that the bank holds at constant
volatility (protocol amendment 1, revised) leaves its rows as they are: the task summary counts it
(`garch_fallback`), the progress log names it, and the selections file's schema metadata lists it
(`garch_fallbacks`). The metadata also names each holding's dynamics window (`garch_windows`:
10y, 3y or fallback); the progress log repeats it when some holding is not on 10 years.

A task runs under a wall alarm of the per-arm ceiling (600 s) times its arm-cells; a task that
rings it, or holds a selection slower than 600 s, writes `<job>/breaches/<base>.json` and no task
file, so it is never marked done, and the job stops. The cumulative CPU is checkpointed atomically
to `<job>/usage.json` at least every 60 s of monitoring and after each task.

Output per task, written atomically and last-file-wins (`selections` is written last, so a task is
complete only when `tasks/<menu>_<month>_<engine>.parquet` exists with the run's parent digest in
its schema metadata): `tasks/<base>.parquet` (selections), `tasks/anchors/<base>.parquet`,
`tasks/evaluated/<base>.parquet`.

A job is (menu, engine). `run_job` feeds the tasks, in origin order, to up to six spawned worker
processes (BLAS threads 1), watches CPU, resident memory (from /proc, v1 `ProcMeter`) and the
per-arm seconds, and on the first breach stops, keeps every artifact and marks the job incomplete.
Progress lines go to `<job>/progress.log`, failed tasks (with tracebacks) to `failures.jsonl`.
"""

from __future__ import annotations

import fcntl
import functools
import importlib
import json
import math
import multiprocessing
import os
import queue
import time
import traceback
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from portfoliosight.research import runner
from portfoliosight.research.fixedrisk import contracts as C
from portfoliosight.research.fixedrisk import data, manifest

SHOWCASE_COLUMNS = 48  # the app's NX (portfoliosight/engine/optimize.py)
SHOWCASE_FRACTIONS = tuple(j / (SHOWCASE_COLUMNS - 1) for j in range(SHOWCASE_COLUMNS))
SHOWCASE_D = tuple(round(0.05 * k, 2) for k in range(1, 20))
ENDPOINT_D = (0.0, 1.0)
EVAL_CHUNK = 256
KINDS = ("main", "stability", "showcase", "sens_tau", "sens_5y", "sens_endpoints", "comparator")
DIGEST_KEY = b"parent_digest"
FALLBACKS_KEY = b"garch_fallbacks"
WINDOWS_KEY = b"garch_windows"
COMPARATOR_ARMS = ("F", "BS")

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
        ("r_fraction", pa.float64()),
        ("r", pa.float64()),
        ("cell", pa.string()),
        ("arm", pa.string()),
        ("pooled", pa.bool_()),
        ("weights", pa.list_(pa.float64())),
        ("sigma", pa.float64()),
        ("measure", pa.float64()),
        ("d", pa.float64()),
        ("bad", pa.float64()),
        ("typical", pa.float64()),
        ("good", pa.float64()),
        ("mean", pa.float64()),
        ("es_25", pa.float64()),
        ("status", pa.string()),
        ("starts", pa.int64()),
        ("iterations", pa.int64()),
        ("seconds", pa.float64()),
        ("solver", pa.string()),
    ]
)
ANCHOR_SCHEMA = pa.schema(
    [
        ("menu", pa.string()),
        ("month", pa.string()),
        ("origin", pa.date32()),
        ("engine", pa.string()),
        ("grid", pa.string()),  # main | showcase | sens_tau | sens_5y
        ("lookback", pa.string()),
        ("tau_r", pa.float64()),
        ("r_fraction", pa.float64()),
        ("r", pa.float64()),
        ("sigma_min", pa.float64()),
        ("sigma_top", pa.float64()),
        ("w_F", pa.list_(pa.float64())),
        ("w_MDP", pa.list_(pa.float64())),
        ("w_BS", pa.list_(pa.float64())),
        ("M_F", pa.float64()),
        ("M_MDP", pa.float64()),
        ("collapsed", pa.bool_()),
        ("status", pa.string()),
        ("starts", pa.int64()),
        ("iterations", pa.int64()),
        ("seconds", pa.float64()),
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
    ]
)


# ------------------------------------------------------------------------------ hooks


@dataclass(frozen=True)
class Hooks:
    """The injected collaborators of a task: pieces 1 and 3 in production, fakes in tests."""

    make_bank: C.BankFactory
    search_origin: C.SearchOrigin
    solvers: dict[str, str] = field(default_factory=lambda: dict.fromkeys(C.ENGINES, "exact_grad"))


def real_make_bank(ctx: C.OriginContext, engine: C.Engine, seed: int) -> C.PathBank:
    if engine == "replay":
        from portfoliosight.research.fixedrisk.banks import replay_bank

        return replay_bank(ctx, engine, seed)
    if engine == "garch":
        from portfoliosight.research.fixedrisk.garch_bank import garch_bank

        return garch_bank(ctx, engine, seed)
    raise ValueError(f"unknown engine {engine!r}")


def real_search_origin(*args: Any, **kwargs: Any) -> C.OriginResult:
    from portfoliosight.research.fixedrisk.optimizer import search_origin

    return search_origin(*args, **kwargs)


def load_hooks(spec: str | None, solvers: dict[str, str]) -> Hooks:
    """`None`: the real banks and optimizer. A module name: its `make_bank` and `search_origin`."""
    if not spec:
        return Hooks(real_make_bank, real_search_origin, dict(solvers))
    module = importlib.import_module(spec)
    return Hooks(module.make_bank, module.search_origin, dict(solvers))


# ----------------------------------------------------------------------------- figures


def figures_of_years(years: np.ndarray) -> list[C.Figures]:
    """Exact figures of each column of a (P, M) array of one-year returns.

    Bad, Typical and Good are NumPy linear percentiles (2.5, 50, 97.5); `es_25` is the mean of the
    years at or below Bad.
    """
    years = np.asarray(years, dtype=float)
    if years.ndim == 1:
        years = years[:, None]
    bad, typical, good = np.percentile(years, [2.5, 50.0, 97.5], axis=0)
    out = []
    for j in range(years.shape[1]):
        column = np.ascontiguousarray(years[:, j])
        tail = column[column <= bad[j]]
        # correctly rounded sums: the same bits whatever the batch the column came in
        out.append(
            C.Figures(
                float(bad[j]),
                float(typical[j]),
                float(good[j]),
                math.fsum(column) / len(column),
                math.fsum(tail) / len(tail),
            )  # fmt: skip
        )
    return out


# --------------------------------------------------------------------------------- tasks


@dataclass(frozen=True)
class TaskSpec:
    menu: str
    month: str
    engine: str
    stability: bool = False
    showcase: bool = False
    lookback5: bool = False

    @property
    def base(self) -> str:
        return f"{self.menu}_{self.month}_{self.engine}"


@dataclass
class TaskOutput:
    selections: list[dict[str, Any]] = field(default_factory=list)
    anchors: list[dict[str, Any]] = field(default_factory=list)
    evaluated: list[dict[str, Any]] = field(default_factory=list)
    phases: dict[str, float] = field(default_factory=dict)
    fit_failures: list[dict[str, Any]] = field(default_factory=list)  # GARCH banks not built
    # GARCH holdings held at constant volatility after a failed fit, once per (lookback, holding)
    garch_fallbacks: list[dict[str, Any]] = field(default_factory=list)
    garch_windows: dict[str, str] = field(default_factory=dict)  # holding -> dynamics window


def job_tasks(parent: dict[str, Any], menu: str, engine: str) -> list[TaskSpec]:
    facts = parent["menus"][menu]
    stability, showcase = set(facts["stability_months"]), set(facts["showcase_months"])
    five = set(facts["lookback5_months"])
    return [
        TaskSpec(menu, month, engine, month in stability, month in showcase, month in five)
        for month in facts["schedule"]
    ]


def _selection_row(
    sel: C.Selection, *, kind: str, ctx: C.OriginContext, tau_r: float, sel_id: str
) -> dict[str, Any]:
    f = sel.figures
    return {
        "sel_id": sel_id,
        "kind": kind,
        "menu": sel.menu,
        "month": ctx.month,
        "origin": sel.origin,
        "engine": sel.engine,
        "seed": int(sel.seed),
        "lookback": ctx.lookback,
        "tau_r": float(tau_r),
        "r_fraction": float(sel.r_fraction),
        "r": float(sel.r),
        "cell": str(sel.cell),
        "arm": sel.arm,
        "pooled": bool(sel.pooled),
        "weights": [float(x) for x in np.asarray(sel.weights, dtype=float)],
        "sigma": float(sel.sigma),
        "measure": float(sel.measure),
        "d": None if sel.d is None else float(sel.d),
        "bad": float(f.bad),
        "typical": float(f.typical),
        "good": float(f.good),
        "mean": float(f.mean),
        "es_25": float(f.es_25),
        "status": sel.status,
        "starts": int(sel.starts),
        "iterations": int(sel.iterations),
        "seconds": float(sel.seconds),
        "solver": sel.solver,
    }


def _anchor_row(
    a: C.Anchors, *, ctx: C.OriginContext, engine: str, grid: str, tau_r: float
) -> dict[str, Any]:
    def vec(w: Any) -> list[float] | None:
        return None if w is None else [float(x) for x in np.asarray(w, dtype=float)]

    return {
        "menu": ctx.menu.name,
        "month": ctx.month,
        "origin": ctx.origin,
        "engine": engine,
        "grid": grid,
        "lookback": ctx.lookback,
        "tau_r": float(tau_r),
        "r_fraction": float(a.r_fraction),
        "r": float(a.r),
        "sigma_min": float(a.sigma_min),
        "sigma_top": float(a.sigma_top),
        "w_F": vec(a.w_F),
        "w_MDP": vec(a.w_MDP),
        "w_BS": vec(a.w_BS),
        "M_F": float(a.M_F),
        "M_MDP": float(a.M_MDP),
        "collapsed": bool(a.collapsed),
        "status": a.status,
        "starts": int(a.starts),
        "iterations": int(a.iterations),
        "seconds": float(a.seconds),
    }


class _Collector:
    """Rows of one task with unique selection ids and the weights to evaluate."""

    def __init__(self, spec: TaskSpec, engine: str) -> None:
        self.spec, self.engine = spec, engine
        self.out = TaskOutput()
        self._ids: dict[str, int] = {}
        self.to_evaluate: dict[str, list[tuple[str, np.ndarray]]] = {}  # lookback -> (id, w)

    def _unique(self, base: str) -> str:
        n = self._ids.get(base, 0)
        self._ids[base] = n + 1
        return base if n == 0 else f"{base}#{n}"

    def add(
        self,
        result: C.OriginResult,
        *,
        kind: str,
        ctx: C.OriginContext,
        tau_r: float,
        grid: str | None,
        evaluate: bool,
        comparator_kind: str,
    ) -> None:
        if grid is not None:
            for anchor in result.anchors:
                self.out.anchors.append(
                    _anchor_row(anchor, ctx=ctx, engine=self.engine, grid=grid, tau_r=tau_r)
                )
        rows = [(s, kind) for s in result.selections]
        rows += [(s, comparator_kind) for s in result.comparators]
        rows += [
            (s, comparator_kind if s.arm in COMPARATOR_ARMS else kind) for s in result.unselected
        ]
        for sel, k in rows:
            ident = self._unique(
                "|".join(
                    [
                        ctx.menu.name,
                        ctx.month,
                        self.engine,
                        k,
                        ctx.lookback,
                        f"{tau_r:g}",
                        str(sel.seed),
                        f"{sel.r_fraction:.6f}",
                        str(sel.cell),
                        sel.arm,
                        "pooled" if sel.pooled else "native",
                    ]
                )  # fmt: skip
            )
            self.out.selections.append(
                _selection_row(sel, kind=k, ctx=ctx, tau_r=tau_r, sel_id=ident)
            )
            weights = np.asarray(sel.weights, dtype=float)
            if evaluate and weights.size and np.isfinite(weights).all():
                self.to_evaluate.setdefault(ctx.lookback, []).append(
                    (ident, np.asarray(sel.weights, dtype=float))
                )


def evaluate_on_test_banks(
    ctx: C.OriginContext,
    items: Sequence[tuple[str, np.ndarray]],
    engine: C.Engine,
    make_bank: C.BankFactory,
    seeds: Iterable[int] = C.TEST_SEEDS,
) -> list[dict[str, Any]]:
    """Figures of each locked mix on each independent bank; equal weights are scored once."""
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
    matrix = np.vstack(mixes)
    index = [unique[np.ascontiguousarray(w, dtype="<f8").tobytes()] for _, w in items]
    for seed in seeds:
        bank = make_bank(ctx, engine, seed)
        figures: list[C.Figures] = []
        for start in range(0, len(matrix), EVAL_CHUNK):
            figures += figures_of_years(bank.years(matrix[start : start + EVAL_CHUNK]))
        del bank
        for (ident, _), j in zip(items, index, strict=True):
            f = figures[j]
            rows.append(
                {
                    "sel_id": ident,
                    "test_seed": int(seed),
                    "bad": f.bad,
                    "typical": f.typical,
                    "good": f.good,
                    "mean": f.mean,
                    "es_25": f.es_25,
                }
            )
    return rows


def is_fit_failure(exc: BaseException) -> bool:
    """A bank that cannot be built because a holding's GARCH fit failed (`garch_fit_failed`)."""
    return getattr(exc, "label", None) == C.FIT_FAILED


def fit_failed_result(
    ctx: C.OriginContext,
    engine: C.Engine,
    seed: int,
    *,
    solver: str,
    arms: tuple[str, ...] = C.ARM_ORDER,
    risk_fractions: tuple[float, ...] = C.RISK_FRACTIONS,
    d_grid: tuple[float, ...] | None = None,
    include_free: bool = True,
    native_only: bool = False,
    **_: Any,
) -> C.OriginResult:
    """What a search reports when its bank could not be built: one `garch_fit_failed` row per
    scheduled outcome (`contracts.scheduled_outcomes`), no anchors, no mixes."""
    grid = (0.25, 0.50, 0.75) if d_grid is None else tuple(d_grid)
    cells = tuple(C.cell_name(d) for d in grid) + (("free",) if include_free else ())
    result = C.OriginResult(menu=ctx.menu.name, origin=ctx.origin, engine=engine, seed=seed)
    for r_fraction, cell, arm, pooled in C.scheduled_outcomes(
        risk_fractions=tuple(risk_fractions), cells=cells, arms=arms, native_only=native_only
    ):
        result.unselected.append(
            C.unselected(
                menu=ctx.menu.name, origin=ctx.origin, engine=engine, seed=seed,
                r_fraction=r_fraction, r=math.nan, cell=cell, arm=arm, pooled=pooled,
                status=C.FIT_FAILED, solver=solver,
            )
        )  # fmt: skip
    result.labels = {C.FIT_FAILED: len(result.unselected)}
    return result


def record_fallbacks(found: list[dict[str, Any]], ctx: C.OriginContext, bank: C.PathBank) -> None:
    """Add the bank's constant-volatility fallback holdings (`GarchBank.fallbacks`) to `found`,
    once per (lookback, holding): every seed's bank at a context shares the fit."""
    seen = {(item["lookback"], item["holding"]) for item in found}
    for holding, reason in (getattr(bank, "fallbacks", None) or {}).items():
        if (ctx.lookback, holding) not in seen:
            found.append({"lookback": ctx.lookback, "holding": holding, "reason": reason})


def run_task(
    inputs: data.ResearchInputs,
    spec: TaskSpec,
    hooks: Hooks,
    clock: Callable[[], float] = time.perf_counter,
) -> TaskOutput:
    """Everything one (menu, month, engine) task computes; see the module docstring.

    A bank that cannot be built because a GARCH fit failed turns every search on it into
    `garch_fit_failed` rows (persisted and counted); the reason is kept in `fit_failures`. A
    holding held at constant volatility after a failed fit is kept in `garch_fallbacks`.
    """
    engine: C.Engine = spec.engine  # type: ignore[assignment]
    solver = hooks.solvers[engine]
    col = _Collector(spec, engine)
    phases = col.out.phases

    def timed(name: str, since: float) -> None:
        phases[name] = phases.get(name, 0.0) + clock() - since

    def bank_for(ctx: C.OriginContext, seed: int) -> C.PathBank | None:
        try:
            built = hooks.make_bank(ctx, engine, seed)
        except Exception as exc:
            if not is_fit_failure(exc):
                raise
            col.out.fit_failures.append(
                {"lookback": ctx.lookback, "seed": seed, "error": f"{type(exc).__name__}: {exc}"}
            )
            return None
        record_fallbacks(col.out.garch_fallbacks, ctx, built)
        if not col.out.garch_windows:  # the same at every seed and lookback of the origin
            col.out.garch_windows = dict(getattr(built, "windows", None) or {})
        return built

    def search(ctx: C.OriginContext, bank: C.PathBank | None, seed: int, **kw: Any):
        if bank is None:
            return fit_failed_result(ctx, engine, seed, solver=solver, **kw)
        return hooks.search_origin(ctx, bank, solver=solver, **kw)

    t = clock()
    ctx = data.origin_context(inputs, spec.menu, spec.month)
    bank = bank_for(ctx, C.PRIMARY_SEED)
    timed("context_and_bank", t)

    # 2. Main grid; anchors=None makes the optimizer compute the origin's anchors once.
    t = clock()
    main = search(ctx, bank, C.PRIMARY_SEED, anchors=None)
    timed("main", t)
    anchors = main.anchors
    col.add(
        main, kind="main", ctx=ctx, tau_r=C.TAU_R, grid="main", evaluate=True,
        comparator_kind="comparator",
    )  # fmt: skip

    # 3. Stability: arm U1 native-only on the primary seed and the four stability seeds.
    if spec.stability:
        t = clock()
        native = search(ctx, bank, C.PRIMARY_SEED, anchors=anchors, native_only=True)
        col.add(native, kind="stability", ctx=ctx, tau_r=C.TAU_R, grid=None, evaluate=False,
                comparator_kind="stability")  # fmt: skip
        for seed in C.STABILITY_SEEDS:
            other = bank_for(ctx, seed) if bank is not None else None
            result = search(ctx, other, seed, anchors=anchors, native_only=True)
            col.add(result, kind="stability", ctx=ctx, tau_r=C.TAU_R, grid=None, evaluate=False,
                    comparator_kind="stability")  # fmt: skip
            del other
        timed("stability", t)

    # 4. Showcase surface and the sensitivities at showcase origins.
    if spec.showcase:
        t = clock()
        surface = search(
            ctx, bank, C.PRIMARY_SEED, anchors=None, arms=("U1",),
            risk_fractions=SHOWCASE_FRACTIONS, d_grid=SHOWCASE_D, include_free=False,
        )  # fmt: skip
        col.add(surface, kind="showcase", ctx=ctx, tau_r=C.TAU_R, grid="showcase", evaluate=True,
                comparator_kind="showcase")  # fmt: skip
        timed("showcase", t)

        t = clock()
        tau = search(ctx, bank, C.PRIMARY_SEED, anchors=None, tau_r=C.TAU_R_SENSITIVITY)
        col.add(tau, kind="sens_tau", ctx=ctx, tau_r=C.TAU_R_SENSITIVITY, grid="sens_tau",
                evaluate=True, comparator_kind="sens_tau")  # fmt: skip
        ends = search(
            ctx, bank, C.PRIMARY_SEED, anchors=anchors, arms=("U1",), d_grid=ENDPOINT_D,
            include_free=False,
        )  # fmt: skip
        col.add(ends, kind="sens_endpoints", ctx=ctx, tau_r=C.TAU_R, grid=None, evaluate=True,
                comparator_kind="sens_endpoints")  # fmt: skip
        timed("sens_main", t)

    ctx5: C.OriginContext | None = None
    if spec.lookback5:
        t = clock()
        ctx5 = data.origin_context(inputs, spec.menu, spec.month, C.SENSITIVITY_LOOKBACK)
        bank5 = bank_for(ctx5, C.PRIMARY_SEED)
        five = search(ctx5, bank5, C.PRIMARY_SEED, anchors=None)
        col.add(five, kind="sens_5y", ctx=ctx5, tau_r=C.TAU_R, grid="sens_5y", evaluate=True,
                comparator_kind="sens_5y")  # fmt: skip
        del bank5
        timed("sens_5y", t)
    del bank

    # 5. Independent evaluation of every locked selection, on its own training context.
    t = clock()
    for lookback, items in col.to_evaluate.items():
        target = ctx5 if lookback == C.SENSITIVITY_LOOKBACK else ctx
        assert target is not None
        col.out.evaluated += evaluate_on_test_banks(target, items, engine, hooks.make_bank)
    timed("evaluation", t)
    return col.out


# ------------------------------------------------------------------------------- files


def task_paths(tasks_dir: Path, spec: TaskSpec) -> dict[str, Path]:
    return {
        "selections": tasks_dir / f"{spec.base}.parquet",
        "anchors": tasks_dir / "anchors" / f"{spec.base}.parquet",
        "evaluated": tasks_dir / "evaluated" / f"{spec.base}.parquet",
    }


def _write_table(
    path: Path,
    rows: list[dict[str, Any]],
    schema: pa.Schema,
    digest: str,
    extra: dict[bytes, bytes] | None = None,
) -> None:
    table = pa.Table.from_pylist(rows, schema=schema)
    table = table.replace_schema_metadata({DIGEST_KEY: digest.encode(), **(extra or {})})
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    pq.write_table(table, tmp)
    os.replace(tmp, path)


def write_task(tasks_dir: Path, spec: TaskSpec, out: TaskOutput, digest: str) -> None:
    paths = task_paths(tasks_dir, spec)
    _write_table(paths["anchors"], out.anchors, ANCHOR_SCHEMA, digest)
    _write_table(paths["evaluated"], out.evaluated, EVALUATED_SCHEMA, digest)
    extra: dict[bytes, bytes] = {}
    if out.garch_fallbacks:
        extra[FALLBACKS_KEY] = json.dumps(out.garch_fallbacks).encode()
    if out.garch_windows:
        extra[WINDOWS_KEY] = json.dumps(out.garch_windows).encode()
    # last: the marker
    _write_table(paths["selections"], out.selections, SELECTION_SCHEMA, digest, extra)


def task_done(tasks_dir: Path, spec: TaskSpec, digest: str) -> bool:
    path = task_paths(tasks_dir, spec)["selections"]
    if not path.is_file():
        return False
    try:
        meta = pq.read_schema(path).metadata or {}
    except (OSError, pa.ArrowInvalid):
        return False
    return meta.get(DIGEST_KEY) == digest.encode()


# ---------------------------------------------------------------------------- pools


@dataclass(frozen=True)
class WorkerInit:
    """What a worker needs to run tasks: all picklable."""

    snapshot_dir: str
    hooks: str | None
    solvers: dict[str, str]
    inputs_loader: str | None = None  # "module:function(snapshot_dir)"; default data.load_inputs
    ledger_cache: str | None = None  # directory shared by the parent and the workers
    expect_digest: str | None = None  # the parent's snapshot manifest digest


@dataclass
class WorkerState:
    inputs: data.ResearchInputs
    hooks: Hooks


def build_state(init: WorkerInit) -> WorkerState:
    loader: Callable[[str], data.ResearchInputs] = functools.partial(
        data.load_inputs, ledger_cache=init.ledger_cache
    )
    if init.hooks:
        module = importlib.import_module(init.hooks)
        loader = getattr(module, "load_inputs", loader)
    if init.inputs_loader:
        name, _, attr = init.inputs_loader.partition(":")
        loader = getattr(importlib.import_module(name), attr)
    inputs = loader(init.snapshot_dir)
    if init.expect_digest and inputs.manifest_sha256 != init.expect_digest:
        raise RuntimeError(
            f"snapshot {init.snapshot_dir} has digest {inputs.manifest_sha256}, "
            f"the parent manifest names {init.expect_digest}"
        )
    return WorkerState(inputs, load_hooks(init.hooks, init.solvers))


def task_arm_cells(spec: TaskSpec) -> int:
    """The (r, cell, arm) searches a task schedules; its wall alarm is `arm_seconds` times this."""
    rf, cells, arms = len(C.RISK_FRACTIONS), len(C.CELLS), len(C.ARM_ORDER)
    main = rf * cells * arms
    count = main
    if spec.stability:
        count += (1 + len(C.STABILITY_SEEDS)) * rf * cells
    if spec.showcase:
        count += SHOWCASE_COLUMNS * len(SHOWCASE_D) + main + rf * len(ENDPOINT_D)
    if spec.lookback5:
        count += main
    return count


def breach_path(tasks_dir: Path, spec: TaskSpec) -> Path:
    return tasks_dir.parent / "breaches" / f"{spec.base}.json"


def _write_json(path: Path, body: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(body, indent=2, sort_keys=True, default=str) + "\n")
    os.replace(tmp, path)


def execute(state: WorkerState, payload: tuple[Any, ...]) -> dict[str, Any]:
    """Run and write one task; never raises (a failure is reported in the summary).

    `payload` is `(spec, tasks_dir, digest[, arm_seconds])`. The task runs under a wall alarm of
    `arm_seconds` x `task_arm_cells(spec)`; when the alarm rings, or a finished task holds a
    selection slower than `arm_seconds`, the breach is written to `<job>/breaches/<task>.json`,
    the summary carries it and no task file is written, so the task is not done.
    """
    spec, tasks_dir, digest, *rest = payload
    arm_seconds = float(rest[0]) if rest else math.inf
    started, cpu = time.perf_counter(), time.process_time()
    summary: dict[str, Any] = {"task": spec.base, "pid": os.getpid(), "ok": False}
    ceiling = arm_seconds * task_arm_cells(spec)
    breach: dict[str, Any] | None = None
    try:
        try:
            with runner.arm_alarm(ceiling):
                out = run_task(state.inputs, spec, state.hooks)
        except runner.ArmTimeLimit:
            breach = {
                "rule": "arm_seconds",
                "limit": ceiling,
                "value": time.perf_counter() - started,
                "detail": f"task wall alarm: {task_arm_cells(spec)} arm-cells x {arm_seconds} s",
            }
        else:
            slowest = max(out.selections, key=lambda row: row["seconds"], default=None)
            seconds = 0.0 if slowest is None else float(slowest["seconds"])
            if seconds > arm_seconds:
                breach = {
                    "rule": "arm_seconds",
                    "limit": arm_seconds,
                    "value": seconds,
                    "detail": f"selection {slowest['sel_id']}" if slowest else "",
                }
            else:
                write_task(Path(tasks_dir), spec, out, digest)
                summary.update(
                    ok=True,
                    selections=len(out.selections),
                    labels=_label_counts(out.selections, out.garch_fallbacks),
                    fit_failures=out.fit_failures,
                    garch_fallbacks=out.garch_fallbacks,
                    garch_windows=out.garch_windows,
                    evaluated=len(out.evaluated),
                    max_selection_seconds=seconds,
                    phases=out.phases,
                )
        if breach is not None:
            breach["task"] = spec.base
            breach["utc"] = runner.utc()
            _write_json(breach_path(Path(tasks_dir), spec), {**breach, "parent_digest": digest})
            summary["breach"] = breach
    except BaseException:
        summary["error"] = traceback.format_exc()
    summary["seconds"] = time.perf_counter() - started
    summary["cpu_seconds"] = time.process_time() - cpu
    return summary


def _label_counts(
    rows: list[dict[str, Any]], fallbacks: list[dict[str, Any]] | None = None
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        if row["status"] != C.OK:
            counts[row["status"]] = counts.get(row["status"], 0) + 1
    if fallbacks:  # holdings, not rows: their rows keep their own labels
        counts[C.FIT_FALLBACK] = len(fallbacks)
    return counts


class InlinePool:
    """Tasks run in this process, one at a time (tests, `--workers 0`)."""

    def __init__(self, init: WorkerInit) -> None:
        self.state = build_state(init)
        self._queue: list[tuple[int, Any]] = []

    def pids(self) -> list[int]:
        return []

    def idle(self) -> int:
        return 0 if self._queue else 1

    def submit(self, index: int, task: Any) -> None:
        self._queue.append((index, task))

    def next(self, timeout: float) -> tuple[str, int, Any] | None:
        if not self._queue:
            return None
        index, task = self._queue.pop(0)
        return ("done", index, execute(self.state, task))

    def close(self) -> None:
        self._queue.clear()

    terminate = close


def _worker_main(init: WorkerInit, inbox: Any, outbox: Any) -> None:
    pid = os.getpid()
    try:
        env = {name: os.environ.get(name) for name in runner.BLAS_ENV}
        if any(value != "1" for value in env.values()):
            raise RuntimeError(f"a worker must run BLAS on one thread; its environment has {env}")
        from threadpoolctl import threadpool_limits

        limiter = threadpool_limits(limits=1, user_api="blas")
        started = time.perf_counter()
        state = build_state(init)
        outbox.put(
            ("ready", pid, None, {"env": env, "load_seconds": time.perf_counter() - started})
        )
    except BaseException:
        outbox.put(("error", pid, None, traceback.format_exc()))
        return
    while True:
        item = inbox.get()
        if item is None:
            break
        index, task = item
        outbox.put(("done", pid, index, execute(state, task)))
    del limiter


class ProcessPool:
    """Spawned worker processes, each loading the inputs once and fed one task at a time."""

    def __init__(self, count: int, init: WorkerInit, ready_timeout: float = 3600.0) -> None:
        context = multiprocessing.get_context("spawn")
        self._outbox = context.Queue()
        self._procs: dict[int, Any] = {}
        self._inbox: dict[int, Any] = {}
        self._busy: dict[int, int | None] = {}
        self.workers: list[dict[str, Any]] = []
        starting = {}
        for _ in range(count):
            inbox = context.Queue()
            process = context.Process(
                target=_worker_main, args=(init, inbox, self._outbox), daemon=True
            )
            process.start()
            starting[process.pid] = (process, inbox)
        while len(self.workers) < count:
            try:
                kind, pid, _index, payload = self._outbox.get(timeout=ready_timeout)
            except queue.Empty as exc:
                runner._kill(p for p, _ in starting.values())
                raise runner.WorkerError("a worker did not start in time") from exc
            if kind == "error":
                runner._kill(p for p, _ in starting.values())
                raise runner.WorkerError(payload)
            process, inbox = starting[pid]
            self._procs[pid], self._inbox[pid], self._busy[pid] = process, inbox, None
            self.workers.append({"kind": "worker", "pid": pid, **payload})

    def pids(self) -> list[int]:
        return list(self._procs)

    def idle(self) -> int:
        return sum(index is None for index in self._busy.values())

    def submit(self, index: int, task: Any) -> None:
        pid = next(pid for pid, busy in self._busy.items() if busy is None)
        self._busy[pid] = index
        self._inbox[pid].put((index, task))

    def next(self, timeout: float) -> tuple[str, int, Any] | None:
        try:
            kind, pid, index, payload = self._outbox.get(timeout=timeout)
        except queue.Empty:
            for pid, process in self._procs.items():
                if not process.is_alive() and self._busy[pid] is not None:
                    raise runner.WorkerError(
                        f"worker {pid} stopped (exit code {process.exitcode})"
                    ) from None
            return None
        self._busy[pid] = None
        return (kind, index, payload)

    def close(self) -> None:
        for inbox in self._inbox.values():
            inbox.put(None)
        for process in self._procs.values():
            process.join(timeout=30)
        self.terminate()

    def terminate(self) -> None:
        runner._kill(self._procs.values())


# ---------------------------------------------------------------------------------- job


@dataclass
class JobResult:
    job: str
    status: str  # complete | incomplete
    tasks_total: int
    tasks_done: int
    tasks_failed: int
    cpu_seconds: float
    breach: dict[str, Any] | None = None
    directory: Path | None = None


class JobLog:
    def __init__(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        self.progress = (directory / "progress.log").open("a", encoding="utf-8")
        self.failures = (directory / "failures.jsonl").open("a", encoding="utf-8")
        self.resources = runner.Resources(directory / "resources.jsonl")

    def line(self, text: str) -> None:
        self.progress.write(f"{runner.utc()} {text}\n")
        self.progress.flush()

    def failure(self, record: dict[str, Any]) -> None:
        self.failures.write(json.dumps(record, default=str) + "\n")
        self.failures.flush()

    def close(self) -> None:
        for handle in (self.progress, self.failures):
            handle.close()
        self.resources.close()


@dataclass
class HostLock:
    path: Path
    _handle: Any = None

    def __enter__(self) -> HostLock:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = self.path.open("w")
        try:
            fcntl.flock(self._handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self._handle.close()
            raise RuntimeError(
                f"another job holds {self.path}: one job at a time per host (protocol §8)"
            ) from None
        return self

    def __exit__(self, *exc: object) -> None:
        fcntl.flock(self._handle, fcntl.LOCK_UN)
        self._handle.close()


def _read_usage(directory: Path) -> float:
    path = directory / "usage.json"
    return float(json.loads(path.read_text())["cpu_seconds"]) if path.is_file() else 0.0


def write_usage(directory: Path, cpu_seconds: float) -> None:
    """The job's cumulative CPU seconds (earlier attempts included), written atomically."""
    _write_json(directory / "usage.json", {"cpu_seconds": cpu_seconds, "utc": runner.utc()})


CHECKPOINT_SECONDS = 60.0


class CheckpointMonitor(runner.Monitor):
    """`runner.Monitor` that also calls `on_checkpoint()` at most every `every` seconds of its
    checks (the first check included), so the cumulative CPU reaches disk while tasks run."""

    def __init__(
        self,
        *args: Any,
        on_checkpoint: Callable[[], None],
        every: float = CHECKPOINT_SECONDS,
        clock: Callable[[], float] = time.monotonic,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.on_checkpoint, self.every, self.clock = on_checkpoint, every, clock
        self._last = -math.inf

    def check(self, pids: Sequence[int]) -> runner.Breach | None:
        breach = super().check(pids)
        now = self.clock()
        if now - self._last >= self.every:
            self._last = now
            self.on_checkpoint()
        return breach


@dataclass(frozen=True)
class ResumeOverride:
    """An owner-approved resume of a stopped job, recorded in the job's `overrides.jsonl` and
    progress log: a CPU budget other than the parent's, and/or commits after the parent's that
    change only `allowed_paths` (driver plumbing, never the computation)."""

    reason: str
    cpu_hours: float | None = None
    allowed_paths: tuple[str, ...] = ()


def run_job(
    run_dir: Path,
    menu: str,
    engine: str,
    *,
    override: ResumeOverride | None = None,
    snapshot_dir: str | None = None,
    workers: int = manifest.WORKERS,
    hooks: str | None = None,
    inputs_loader: str | None = None,
    host_label: str | None = None,
    pool_factory: Callable[[int, WorkerInit], Any] | None = None,
    meter: runner.Meter | None = None,
    limits: dict[str, float] | None = None,
    poll: float = 1.0,
    checkpoint_seconds: float = CHECKPOINT_SECONDS,
) -> JobResult:
    """Run (or resume) the job (menu, engine) of the run in ``run_dir``; see the module doc.

    Before any cached task is accepted or a worker starts, the running code must be the code the
    parent manifest records (`manifest.code_mismatches`: git HEAD, settings, seeds, ceilings,
    hooks, solvers); otherwise the job is refused with the reasons.
    """
    parent = manifest.read_parent(run_dir)
    allowed = override.allowed_paths if override else ()
    problems = manifest.code_mismatches(parent, hooks=hooks, allowed_paths=allowed)
    if problems:
        raise RuntimeError(
            f"refusing to run or resume {run_dir}: the running code is not the code its parent "
            "manifest records (" + "; ".join(problems) + "). Check out that commit (and sync it "
            "to this host), or write a new parent manifest in a new run directory."
        )
    key = manifest.job_key(menu, engine)
    job = parent["jobs"].get(key)
    if job is None:
        raise ValueError(f"{key} is not one of the parent's jobs {sorted(parent['jobs'])}")
    if host_label and job["host"] and host_label != job["host"]:
        raise ValueError(f"{key} is placed on {job['host']!r}, not on {host_label!r}")
    digest = parent["digest"]
    directory = run_dir / key
    tasks_dir = directory / "tasks"
    snapshot = snapshot_dir or parent["snapshot"]["path"]
    solvers = {e: parent["engines"][e]["solver"] for e in C.ENGINES}
    limit = {
        "rss_bytes": parent["ceilings"]["rss_bytes_per_host"],
        "arm_seconds": parent["ceilings"]["arm_seconds"],
        "cpu_hours": job["cpu_hours_budget"],
        **(limits or {}),
    }
    if override and override.cpu_hours is not None:
        limit["cpu_hours"] = float(override.cpu_hours)
    init = WorkerInit(
        str(snapshot), hooks or parent.get("hooks"), solvers, inputs_loader,
        str(run_dir / "ledger_cache"), parent["snapshot"]["manifest_sha256"],
    )  # fmt: skip

    tasks = job_tasks(parent, menu, engine)
    with HostLock(run_dir / "host.lock"):
        directory.mkdir(parents=True, exist_ok=True)
        log = JobLog(directory)
        started = manifest.utc()
        before = _read_usage(directory)
        pending = [(i, t) for i, t in enumerate(tasks) if not task_done(tasks_dir, t, digest)]
        done_before = len(tasks) - len(pending)
        state = {"done": done_before, "failed": 0, "cpu": before}

        def write_manifest(status: str, breach: dict[str, Any] | None = None) -> None:
            body = manifest.job_manifest(
                parent, menu, engine, host_label, status=status, tasks_total=len(tasks),
                tasks_done=state["done"], failed=state["failed"], cpu_seconds=state["cpu"],
                breach=breach, started_utc=started,
            )  # fmt: skip
            tmp = directory / "job.json.tmp"
            tmp.write_text(json.dumps(body, indent=2, sort_keys=True) + "\n")
            os.replace(tmp, directory / "job.json")
            write_usage(directory, state["cpu"])

        write_manifest("running")
        if override:
            record = {
                "utc": manifest.utc(),
                "reason": override.reason,
                "cpu_hours_budget_parent": job["cpu_hours_budget"],
                "cpu_hours_budget": limit["cpu_hours"],
                "git_head_parent": parent.get("git_head"),
                "git_head_run": manifest.code_head(),
                "changed_paths": manifest.changed_paths(parent.get("git_head") or "HEAD"),
                "allowed_paths": list(override.allowed_paths),
            }
            with (directory / "overrides.jsonl").open("a") as fh:
                fh.write(json.dumps(record, sort_keys=True) + "\n")
            log.line(f"OVERRIDE {json.dumps(record, sort_keys=True)}")
        log.line(
            f"job {key} start: {len(tasks)} tasks, {done_before} already done, "
            f"{len(pending)} to run, cpu budget {limit['cpu_hours']:.2f} h, workers {workers}"
        )
        usage_meter = meter or runner.ProcMeter()

        def checkpoint() -> None:
            state["cpu"] = before + monitor.cpu_seconds
            write_usage(directory, state["cpu"])

        monitor = CheckpointMonitor(
            int(limit["rss_bytes"]), float(limit["cpu_hours"]), usage_meter, cpu_before=before,
            on_checkpoint=checkpoint, every=checkpoint_seconds,
        )  # fmt: skip
        pool = (pool_factory or _default_pool)(workers, init)
        payloads = [
            (i, (t, str(tasks_dir), digest, float(limit["arm_seconds"]))) for i, t in pending
        ]
        breach: runner.Breach | None = None

        def handle(index: int, summary: dict[str, Any]) -> runner.Breach | None:
            if summary.get("ok"):
                state["done"] += 1
            else:
                state["failed"] += 1
                log.failure({"utc": runner.utc(), **summary})
            state["cpu"] = before + monitor.cpu_seconds
            labels = summary.get("labels") or {}
            log.line(
                f"task {summary['task']} {'done' if summary.get('ok') else 'FAILED'} "
                f"{summary['seconds']:.1f}s cpu_total_h={state['cpu'] / 3600.0:.3f} "
                f"failures={state['failed']} ({state['done']}/{len(tasks)})"
                + (f" labels={json.dumps(labels, sort_keys=True)}" if labels else "")
            )
            for item in summary.get("fit_failures") or []:
                log.line(f"task {summary['task']} garch_fit_failed: {json.dumps(item)}")
            for item in summary.get("garch_fallbacks") or []:
                log.line(f"task {summary['task']} {C.FIT_FALLBACK}: {json.dumps(item)}")
            windows = summary.get("garch_windows") or {}
            if any(window != "10y" for window in windows.values()):
                log.line(f"task {summary['task']} garch_windows: {json.dumps(windows)}")
            write_manifest("running")
            found = summary.get("breach")
            if found:  # recorded by the worker; the task wrote no files and is not done
                return runner.Breach(
                    found["rule"], found["limit"], found["value"],
                    f"{summary['task']}: {found['detail']}",
                )  # fmt: skip
            return None

        try:
            stop = runner.drive(pool, payloads, monitor, poll, handle)
            breach = stop.breach
            if breach is not None:
                log.line(f"BREACH {breach.record()}; stopping, artifacts kept")
        except runner.WorkerError as exc:
            breach = runner.Breach("worker_error", 0.0, 0.0, str(exc)[:2000])
            log.line(f"WORKER ERROR; stopping: {str(exc)[:500]}")
        finally:
            pool.terminate() if breach is not None else pool.close()
            state["cpu"] = before + monitor.cpu_seconds
            for sample in monitor.samples:
                log.resources.write(sample)
        complete = breach is None and state["done"] == len(tasks) and state["failed"] == 0
        status = "complete" if complete else "incomplete"
        write_manifest(status, breach.record() if breach else None)
        log.line(
            f"job {key} {status}: {state['done']}/{len(tasks)} tasks, failures={state['failed']}, "
            f"cpu_h={state['cpu'] / 3600.0:.3f}"
        )
        log.close()
    return JobResult(
        key, status, len(tasks), state["done"], state["failed"], state["cpu"],
        breach.record() if breach else None, directory,
    )  # fmt: skip


def _default_pool(workers: int, init: WorkerInit) -> Any:
    return InlinePool(init) if workers <= 0 else ProcessPool(workers, init)


def job_status(run_dir: Path) -> list[dict[str, Any]]:
    """One record per expected job: tasks done, failures, CPU-hours against budget, status."""
    parent = manifest.read_parent(run_dir)
    rows = []
    for key, job in sorted(parent["jobs"].items()):
        directory = run_dir / key
        path = directory / "job.json"
        info = json.loads(path.read_text()) if path.is_file() else None
        tasks = len(list((directory / "tasks").glob("*.parquet"))) if directory.is_dir() else 0
        failures = 0
        if (directory / "failures.jsonl").is_file():
            failures = sum(1 for _ in (directory / "failures.jsonl").open())
        rows.append(
            {
                "job": key,
                "host": job["host"],
                "status": info["status"] if info else "not started",
                "task_files": tasks,
                "tasks_total": len(parent["menus"][job["menu"]]["schedule"]),
                "failure_lines": failures,
                "cpu_hours": (info["cpu_seconds"] / 3600.0) if info else 0.0,
                "cpu_hours_budget": job["cpu_hours_budget"],
                "breach": info["breach"] if info else None,
            }
        )
    return rows


__all__ = [
    "Hooks",
    "InlinePool",
    "JobResult",
    "ProcessPool",
    "TaskSpec",
    "WorkerInit",
    "evaluate_on_test_banks",
    "figures_of_years",
    "job_status",
    "job_tasks",
    "load_hooks",
    "run_job",
    "run_task",
    "task_done",
    "write_task",
]
