"""The `estimate` command: per-unit costs measured on the six showcase origins (protocol §8).

For each menu, the six showcase origins run the primary-seed main grid (anchors included), a
native-only arm U1 pass, and the timing of exact evaluations on a bank. CPU seconds
(`time.process_time`) are used, one thread. The unit costs are then multiplied by the protocol's
counts for the whole schedule: main grid at every origin, stability on every fourth origin (the
primary seed and four stability seeds), the 48 x 19 showcase surface, the sensitivities, the
independent evaluation of every selection on five banks, and the banks themselves; 10% contingency.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import numpy as np

from portfoliosight.research.fixedrisk import contracts as C
from portfoliosight.research.fixedrisk import data, driver, manifest

CONTINGENCY = 0.10
EVAL_MIXES = 64


def _cpu() -> float:
    return time.process_time()


def measure_menu(
    inputs: data.ResearchInputs, menu: str, engine: C.Engine, hooks: driver.Hooks
) -> dict[str, Any]:
    months = data.showcase_months(inputs, menu)
    bank_s, main_s, native_s, anchor_s, eval_s = [], [], [], [], []
    selections = comparators = columns = 0
    solver = hooks.solvers[engine]
    for month in months:
        ctx = data.origin_context(inputs, menu, month)
        t = _cpu()
        bank = hooks.make_bank(ctx, engine, C.PRIMARY_SEED)
        bank_s.append(_cpu() - t)
        t = _cpu()
        main = hooks.search_origin(ctx, bank, anchors=None, solver=solver)
        main_s.append(_cpu() - t)
        anchors_cpu = float(sum(a.seconds for a in main.anchors))
        anchor_s.append(anchors_cpu / max(len(main.anchors), 1))
        columns = len(main.anchors)
        selections += len(main.selections)
        comparators += len(main.comparators)
        t = _cpu()
        hooks.search_origin(ctx, bank, anchors=main.anchors, native_only=True, solver=solver)
        native_s.append(_cpu() - t)
        weights = [np.asarray(s.weights, dtype=float) for s in main.selections]
        weights = [w for w in weights if np.isfinite(w).all()][:EVAL_MIXES]
        if weights:
            matrix = np.vstack(weights)
            t = _cpu()
            driver.figures_of_years(bank.years(matrix))
            eval_s.append((_cpu() - t) / len(weights))
    n = max(len(months), 1)
    return {
        "origins_measured": months,
        "bank_seconds": float(np.mean(bank_s)),
        "main_seconds": float(np.mean(main_s)),
        "native_seconds": float(np.mean(native_s)),
        "anchor_seconds_per_column": float(np.mean(anchor_s)),
        "eval_seconds_per_mix": float(np.mean(eval_s)) if eval_s else 0.0,
        "main_selections": selections / n,
        "comparators": comparators / n,
        "columns": columns,
    }


def project_menu(inputs: data.ResearchInputs, menu: str, unit: dict[str, Any]) -> dict[str, Any]:
    n = len(data.schedule(inputs, menu))
    n_stab = len(data.stability_months(inputs, menu))
    n_show = len(data.showcase_months(inputs, menu))
    n5 = len(data.lookback5_months(inputs, menu))
    n_main = unit["main_selections"]
    n_comp = unit["comparators"]
    per_sel = max(
        unit["main_seconds"] - unit["anchor_seconds_per_column"] * unit["columns"], 0.0
    ) / max(n_main, 1.0)
    anchor = unit["anchor_seconds_per_column"]
    surface = len(driver.SHOWCASE_FRACTIONS) * len(driver.SHOWCASE_D)
    selections_evaluated = (
        n * (n_main + n_comp)
        + n_show * (surface + n_main + n_comp + len(C.RISK_FRACTIONS) * 2)
        + n5 * (n_main + n_comp)
    )
    parts = {
        "main_search": n * unit["main_seconds"],
        "stability_search": n_stab * (1 + len(C.STABILITY_SEEDS)) * unit["native_seconds"],
        "showcase_search": n_show * (surface * per_sel + len(driver.SHOWCASE_FRACTIONS) * anchor),
        "sensitivity_search": (n_show + n5) * unit["main_seconds"]
        + n_show * len(C.RISK_FRACTIONS) * 2 * per_sel,
        "independent_evaluation": selections_evaluated
        * len(C.TEST_SEEDS)
        * unit["eval_seconds_per_mix"],
        "banks": (n * (1 + len(C.TEST_SEEDS)) + n_stab * len(C.STABILITY_SEEDS)
                  + n5 * (1 + len(C.TEST_SEEDS))) * unit["bank_seconds"],
    }  # fmt: skip
    hours = {name: seconds / 3600.0 for name, seconds in parts.items()}
    total = sum(hours.values())
    return {
        "counts": {
            "origins": n,
            "stability_origins": n_stab,
            "showcase_origins": n_show,
            "lookback5_origins": n5,
            "selections_evaluated": selections_evaluated,
        },
        "cpu_hours": hours,
        "cpu_hours_total": total,
        "cpu_hours_with_contingency": total * (1.0 + CONTINGENCY),
    }


def run_estimate(
    inputs: data.ResearchInputs,
    engine: C.Engine,
    host_label: str,
    hooks: driver.Hooks,
    out_dir: Path | None = None,
) -> dict[str, Any]:
    started = time.perf_counter()
    result: dict[str, Any] = {
        "kind": "fixed_risk_estimate",
        "engine": engine,
        "host": manifest.host_info(host_label),
        "snapshot_manifest_sha256": inputs.manifest_sha256,
        "solver": hooks.solvers[engine],
        "contingency": CONTINGENCY,
        "menus": {},
        "jobs": {},
    }
    for menu in inputs.menus:
        unit = measure_menu(inputs, menu.name, engine, hooks)
        projection = project_menu(inputs, menu.name, unit)
        result["menus"][menu.name] = {"unit_costs": unit, **projection}
        result["jobs"][manifest.job_key(menu.name, engine)] = projection[
            "cpu_hours_with_contingency"
        ]
    result["measure_wall_seconds"] = time.perf_counter() - started
    if out_dir is not None:
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / "estimate.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
        os.replace(tmp, path)
    return result
