"""The v3 sizing run (protocol v3 §8.1): the six showcase origins, all six arms, pool recording,
the arm 3 solver check of §4.6, and the projection of the full replay stage. No realized outcome
is computed.

`run_sizing` runs each showcase origin's v3 task in its own spawned process (one BLAS thread,
`max_tasks_per_child=1`, so each process's peak resident memory is that task's), writes the task
files under `<out_dir>/tasks/`, runs arm 3 alone at `V3_CHECK_CALLS` per start beside it, and
writes `<out_dir>/sizing.json`:

- measured: seconds per evaluation of the full objective set, seconds per arm search, wall and
  CPU seconds per task, pool rows and bytes per task, peak memory per worker;
- the solver check (§4.6): per column, the native arm 3 TDD of each budget, and each budget's
  calls and starts per start (the check runs at the task's start count); the 768-call solver
  is accepted when its native TDD is within 0.1 pp of, or below, the 1,536-call one in at least
  34 of the 36 columns;
- the projection: the scale factor is v3's search seconds per (origin, r, arm) at the showcase
  origins over v2's main-grid search seconds there (the `seconds` of v2's `kind = main` rows);
  each scheduled origin gets v2's task wall time times the factor (at the showcase origins v2's
  non-showcase median instead, plus v3's measured side checks); projected wall = max(sum /
  workers, longest task); the decision of the rules (36 h, 72 h).
"""

from __future__ import annotations

import json
import math
import os
import re
import resource
import time
from collections.abc import Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor
from multiprocessing import get_context
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from portfoliosight.research.fixedrisk import contracts as C

CHECK_TOLERANCE = 0.001  # 0.1 percentage point of TDD
CHECK_NEEDED = 34
RUN_AS_SPECIFIED_HOURS = 36.0
CUT_HOURS = 72.0
RUN = "run as specified"
CUT = "cut starts to two (drop the Sobol start), rerun the solver check, then lock"
STOP = "stop and report to the owner before the lock"
TASK_LINE = re.compile(r"task (\S+)_(\d{4}-\d{2})_(\w+) done ([0-9.]+)s")


# ------------------------------------------------------------------------- v2 references


def v2_task_seconds(progress_log: Path) -> dict[str, float]:
    """Each v2 task's wall seconds by month, from its job's `progress.log` (the last 'done')."""
    out: dict[str, float] = {}
    for line in Path(progress_log).read_text().splitlines():
        m = TASK_LINE.search(line)
        if m:
            out[m.group(2)] = float(m.group(4))
    return out


def v2_main_seconds(tasks_dir: Path, months: Sequence[str], menu: str, engine: str) -> dict:
    """v2's main-grid search seconds per month: the sum of `seconds` of the `kind = main` rows."""
    out = {}
    for month in months:
        path = Path(tasks_dir) / f"{menu}_{month}_{engine}.parquet"
        frame = pd.read_parquet(path, columns=["kind", "seconds"])
        out[month] = float(frame.loc[frame["kind"] == "main", "seconds"].sum())
    return out


# ------------------------------------------------------------------------------ one task


def v3_search_seconds(selections: Sequence[Mapping[str, Any]]) -> float:
    """v3's search seconds per (origin, r, arm) summed over a task's main rows: one row per
    (r, arm) (arms 2-5 their pooled row, arms 1 and 6 their own row; the app's frontier node,
    which shares arm 6's seconds, is not counted)."""
    seen: set[tuple[float, str]] = set()
    total = 0.0
    for row in selections:
        if row["kind"] != "main" or row["arm"] == C.APP_FRONTIER:
            continue
        if row["arm"] in C.V3_SEARCHED and not row["pooled"]:
            continue
        key = (round(float(row["r_fraction"]), 6), row["arm"])
        if key not in seen:
            seen.add(key)
            total += float(row["seconds"] or 0.0)
    return total


def side_check_seconds(out: Any) -> float:
    """A showcase task's side checks: arm 4 at the side lambdas and the 5-year side check."""
    side = sum(
        float(r["seconds"] or 0.0)
        for r in out.selections
        if r["kind"] == "side_lambda" and r["pooled"]
    )
    phases = out.phases
    return side + sum(phases.get(k, 0.0) for k in ("context_5y", "bank_5y", "knee_5y", "search_5y"))


def solver_check(
    ctx: C.OriginContext, bank: C.PathBank, knee: Any, calls: int, starts: int
) -> list[dict]:
    """Arm 3 alone at `calls` per start and the run's `starts`: its native TDD per column."""
    from portfoliosight.research.fixedrisk import search3

    res = search3.search_origin_v3(
        ctx, bank, arms=(C.FRONTIER, C.MIN_TDD), calls=calls, starts=starts, knee=knee
    )
    out = []
    for s in res.selections:
        if s["arm"] == C.MIN_TDD and not s["pooled"]:
            tdd = math.nan if s["values"] is None else float(s["values"][_tdd_index()])
            out.append({"r_fraction": s["r_fraction"], "tdd": tdd, "status": s["status"],
                        "seconds": s["seconds"]})  # fmt: skip
    return out


def _tdd_index() -> int:
    from portfoliosight.research.fixedrisk.objectives3 import INDEX

    return INDEX["tdd"]


def sizing_task(payload: Mapping[str, Any]) -> dict[str, Any]:
    """One showcase origin in a fresh process: the v3 task (files written), then arm 3 at the
    check budget; its timings, CPU, peak memory and both budgets' native arm 3 TDD."""
    from threadpoolctl import threadpool_limits

    from portfoliosight.research.fixedrisk import data, driver, driver3
    from portfoliosight.research.fixedrisk.anchors import geometry
    from portfoliosight.research.fixedrisk.knee import knee_columns

    with threadpool_limits(limits=1, user_api="blas"):
        started, cpu = time.perf_counter(), time.process_time()
        inputs = data.load_inputs(payload["snapshot"], ledger_cache=payload.get("ledger_cache"))
        spec = driver.TaskSpec(**payload["spec"])
        hooks = driver.load_hooks(None, dict.fromkeys(C.ENGINES, C.V3_SOLVER))
        t = time.perf_counter()
        out = driver3.run_task(inputs, spec, hooks)
        task_wall = time.perf_counter() - t
        timings = driver3.write_task(Path(payload["tasks_dir"]), spec, out, payload["digest"])
        native768 = [
            {"r_fraction": r["r_fraction"], "tdd": r["tdd"], "status": r["status"]}
            for r in out.selections
            if r["kind"] == "main" and r["arm"] == C.MIN_TDD and not r["pooled"]
        ]
        check: list[dict] = []
        check_seconds = 0.0
        if payload.get("check_calls"):
            t = time.perf_counter()
            ctx = data.origin_context(inputs, spec.menu, spec.month)
            bank = hooks.make_bank(ctx, "replay", C.PRIMARY_SEED)
            geo = geometry(ctx)
            knee = knee_columns(ctx, {a: geo.x(a) for a in C.RISK_FRACTIONS})
            check = solver_check(ctx, bank, knee, int(payload["check_calls"]), spec.starts)
            check_seconds = time.perf_counter() - t
        return {
            "month": spec.month,
            "task_wall_seconds": task_wall,
            "process_wall_seconds": time.perf_counter() - started,
            "cpu_seconds": time.process_time() - cpu,
            "peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
            "timings": timings,
            "search_seconds": v3_search_seconds(out.selections),
            "side_check_seconds": side_check_seconds(out),
            "native_768": native768,
            "native_check": check,
            "check_seconds": check_seconds,
            "budgets": {
                "run": {"calls": spec.calls, "starts": spec.starts},
                "check": {"calls": int(payload.get("check_calls") or 0), "starts": spec.starts},
            },
            "labels": sorted({r["status"] for r in out.selections}),
        }


# ---------------------------------------------------------------------------- projection


def check_verdict(tasks: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """§4.6: per column, native TDD at 768 calls within 0.1 pp of, or below, the check budget's;
    with the two budgets (calls, starts), which every task must share."""
    budgets = [t["budgets"] for t in tasks]
    if any(b != budgets[0] for b in budgets):
        raise ValueError(f"tasks ran the solver check at different budgets: {budgets}")
    columns = []
    for task in tasks:
        base = {round(r["r_fraction"], 6): r["tdd"] for r in task["native_768"]}
        for r in task["native_check"]:
            a = round(r["r_fraction"], 6)
            t768, tcheck = base.get(a, math.nan), r["tdd"]
            ok = bool(math.isfinite(t768) and math.isfinite(tcheck)
                      and t768 <= tcheck + CHECK_TOLERANCE)  # fmt: skip
            columns.append({"month": task["month"], "r_fraction": a, "tdd_768": t768,
                            "tdd_check": tcheck, "ok": ok})  # fmt: skip
    passed = sum(c["ok"] for c in columns)
    return {
        "budgets": budgets[0] if budgets else None,
        "columns": columns,
        "passed": passed,
        "total": len(columns),
        "needed": CHECK_NEEDED,
        "accepted": bool(len(columns) >= 36 and passed >= CHECK_NEEDED),
    }


def project(
    schedule: Sequence[str],
    showcase: Sequence[str],
    tasks: Sequence[Mapping[str, Any]],
    v2_seconds: Mapping[str, float],
    v2_main: Mapping[str, float],
    *,
    workers: int,
) -> dict[str, Any]:
    """§8.1's projection and decision (see the module docstring)."""
    by_month = {t["month"]: t for t in tasks}
    v3_sum = sum(by_month[m]["search_seconds"] for m in by_month)
    v2_sum = sum(v2_main[m] for m in by_month)
    scale = v3_sum / v2_sum if v2_sum > 0 else math.nan
    phase_sum = sum(
        sum(v for k, v in by_month[m]["timings"]["phases"].items() if k.endswith("_3y"))
        for m in by_month
    )
    others = [v2_seconds[m] for m in schedule if m not in set(showcase) and m in v2_seconds]
    median = float(np.median(others)) if others else math.nan
    per_task = {}
    for m in schedule:
        if m in set(showcase):
            side = by_month[m]["side_check_seconds"] if m in by_month else 0.0
            per_task[m] = median * scale + side
        elif m in v2_seconds:
            per_task[m] = v2_seconds[m] * scale
        else:
            per_task[m] = median * scale
    total = sum(per_task.values())
    wall = max(total / workers, max(per_task.values(), default=0.0))
    hours = wall / 3600.0
    cut_hours = hours * 2.0 / 3.0  # an estimate before the rerun on the cut configuration
    decision = RUN if hours <= RUN_AS_SPECIFIED_HOURS else (
        CUT if cut_hours <= CUT_HOURS else STOP
    )  # fmt: skip
    return {
        "scale_factor": scale,
        "scale_factor_phase_wall": phase_sum / v2_sum if v2_sum > 0 else math.nan,
        "v3_search_seconds_showcase": v3_sum,
        "v2_main_seconds_showcase": v2_sum,
        "v2_non_showcase_median_seconds": median,
        "projected_task_seconds": per_task,
        "projected_cpu_hours": total / 3600.0,
        "projected_wall_hours": hours,
        "longest_task_seconds": max(per_task.values(), default=0.0),
        "workers": workers,
        "cut_wall_hours_estimate": cut_hours,
        "decision": decision,
        "cpu_hours_ceiling": 2.0 * total / 3600.0,
    }


def run_sizing(
    *,
    snapshot: str,
    out_dir: Path,
    v2_job_dir: Path,
    months: Sequence[str] | None = None,
    schedule: Sequence[str] | None = None,
    showcase: Sequence[str] | None = None,
    lookback5: Sequence[str] | None = None,
    ledger_cache: str | None = None,
    workers: int = 6,
    project_workers: int = 10,
    calls: int = 768,
    starts: int = C.V3_STARTS,
    check_calls: int = C.V3_CHECK_CALLS,
) -> dict[str, Any]:
    """Run the sizing (see the module docstring); returns and writes `sizing.json`."""
    if os.environ.get("OPENBLAS_NUM_THREADS") != "1":
        raise RuntimeError("set OPENBLAS_NUM_THREADS=OMP_NUM_THREADS=MKL_NUM_THREADS=1")
    from portfoliosight.research.fixedrisk import data

    inputs = data.load_inputs(snapshot, ledger_cache=ledger_cache)
    menu = C.V3_MENU
    order = list(schedule or data.schedule(inputs, menu))
    shown = list(showcase or data.showcase_months(inputs, menu))
    five = set(lookback5 or data.lookback5_months(inputs, menu))
    chosen = list(months or shown)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    payloads = [
        {
            "snapshot": snapshot,
            "ledger_cache": ledger_cache,
            "tasks_dir": str(out_dir / "tasks"),
            "digest": "sizing",
            "check_calls": check_calls,
            "spec": dict(
                menu=menu,
                month=m,
                engine="replay",
                showcase=m in set(shown),
                lookback5=m in five,
                protocol=3,
                calls=calls,
                starts=starts,
            ),
        }  # fmt: skip
        for m in chosen
    ]
    started = time.perf_counter()
    context = get_context("spawn")
    with ProcessPoolExecutor(workers, mp_context=context, max_tasks_per_child=1) as pool:
        tasks = list(pool.map(sizing_task, payloads))
    wall = time.perf_counter() - started
    v2_seconds = v2_task_seconds(Path(v2_job_dir) / "progress.log")
    v2_main = v2_main_seconds(Path(v2_job_dir) / "tasks", chosen, menu, "replay")
    body = {
        "kind": "fixed_risk_v3_sizing",
        "protocol": {"path": C.V3_PROTOCOL_PATH, "revision": C.V3_PROTOCOL_REVISION},
        "snapshot_manifest_sha256": inputs.manifest_sha256,
        "settings": {"calls": calls, "starts": starts, "check_calls": check_calls},
        "months": chosen,
        "sizing_wall_seconds": wall,
        "tasks": tasks,
        "measured": {
            "seconds_per_evaluation": float(
                np.mean([t["timings"]["seconds_per_evaluation"] for t in tasks])
            ),
            "task_wall_seconds": {t["month"]: t["task_wall_seconds"] for t in tasks},
            "pool_rows": {t["month"]: t["timings"]["pool_rows"] for t in tasks},
            "pool_bytes": {t["month"]: t["timings"]["pool_bytes"] for t in tasks},
            "peak_rss_bytes": {t["month"]: t["peak_rss_bytes"] for t in tasks},
            "arm_search_seconds": {t["month"]: t["timings"]["arm_search_seconds"] for t in tasks},
        },  # fmt: skip
        "solver_check": check_verdict(tasks) if check_calls else None,
        "projection": project(
            order, shown, tasks, v2_seconds, v2_main, workers=project_workers
        ),  # fmt: skip
    }
    (out_dir / "sizing.json").write_text(json.dumps(body, indent=2, default=str) + "\n")
    return body
