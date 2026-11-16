"""Model-side geometry check of the simple and diversification-driven recipes check
(docs/plans/2026-11-11-diversification-vs-simple-mixes.md, "Model-side check already run" and
"Cells at or above a frontier's top").

Usage, from the repo root, BLAS threads 1:
    .venv/bin/python scripts/fixedrisk_geometry_check.py --run-dir R --snapshot S
        [--job research2003_replay] [--out FILE]

Per scheduled start month it reads the training side (`data.origin_context`) and the recorded
columns, and computes: the equal-weight risk `sigma(E)` and its risk position `a(E)` on the recorded
limited ends, the limited top rebuilt from the greedy fill beside the recorded one, the top with no
weight limits, and the settings whose risk is at or above that unlimited top. No solver runs (every
top is a greedy fill) and no realized outcome is computed or read. `--out` writes the per-month
table as CSV; the summary is printed as JSON.

Exit status 1 when the equal-weight months excluded among the scheduled months differ from
`recipes3.E_EXCLUDED`, or an excluded U cell of `recipes3.U_EXCLUDED` is missing: the training side
rebuilt here would differ from the one the protocol was written against. The lists are not changed
to match; the difference goes to the owner.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd

from portfoliosight.engine import caps
from portfoliosight.research.fixedrisk import analysis3 as A
from portfoliosight.research.fixedrisk import cli, data
from portfoliosight.research.fixedrisk import recipes3 as RC

JOB = "research2003_replay"


def geometry_row(month: str, mu_s, cov, lower, upper, rec: RC.Recorded) -> dict[str, Any]:
    """One start month's geometry. `rec` is the month's recorded ends and settings
    (`recipes3.recorded_columns`); the tops are greedy fills, so no solver is called."""
    mu = np.asarray(mu_s, dtype=float)
    cov = np.asarray(cov, dtype=float)
    n = len(mu)
    equal = np.full(n, 1.0 / n)
    sigma_equal = float(np.sqrt(equal @ cov @ equal))
    top = caps.greedy_fill(mu, lower, upper)
    top_u = caps.greedy_fill(mu, np.zeros(n), np.ones(n))
    sigma_top_u = float(np.sqrt(top_u @ cov @ top_u))
    return {
        "month": month,
        "sigma_E": sigma_equal,
        "a_E": RC.risk_position(sigma_equal, rec.sigma_min, rec.sigma_top),
        "sigma_top": rec.sigma_top,
        "sigma_top_rebuilt": float(np.sqrt(top @ cov @ top)),
        "sigma_top_U": sigma_top_u,
        "e_excluded": RC.at_or_above_top(sigma_equal, rec.sigma_top),
        "u_excluded": [
            rf
            for rf, r in zip(A.RFS, rec.r, strict=True)
            if RC.at_or_above_top(float(r), sigma_top_u)
        ],
    }


def summary(rows: pd.DataFrame, eligible: Sequence[str]) -> dict[str, Any]:
    """The geometry table's facts: the excluded equal-weight months among the eligible start
    months and among the other scheduled ones, the excluded U cells (month, setting), the months
    whose unlimited top is below the limited top, `a(E)` (median and mean over the eligible
    months, median over all) and the largest gap between the recorded and rebuilt limited top."""
    records = [{str(k): v for k, v in row.items()} for row in rows.to_dict("records")]
    wanted = set(eligible)
    here = [r for r in records if r["month"] in wanted]
    a_here = [float(r["a_E"]) for r in here]
    return {
        "months": len(records),
        "eligible_months": len(here),
        "e_excluded": [r["month"] for r in here if r["e_excluded"]],
        "e_excluded_other": [r["month"] for r in records if r["e_excluded"] and r not in here],
        "u_excluded": [[r["month"], float(rf)] for r in records for rf in r["u_excluded"]],
        "u_top_below_limited_top": [
            r["month"] for r in records if r["sigma_top_U"] < r["sigma_top"]
        ],
        "a_E_median_eligible": float(np.median(a_here)),
        "a_E_mean_eligible": float(np.mean(a_here)),
        "a_E_median_all": float(np.median([float(r["a_E"]) for r in records])),
        "largest_top_gap": max(abs(r["sigma_top"] - r["sigma_top_rebuilt"]) for r in records),
    }


def build_table(run_dir: str, snapshot: str, job_name: str) -> tuple[pd.DataFrame, list[str]]:
    """The geometry table of every scheduled start month of the job, and its eligible months.
    Reads the parent manifest and the snapshot as `v3-safety` does (the digest checked) and the
    job's column table; never a realized outcome."""
    parent, loaded, _ = cli._v3_inputs(argparse.Namespace(run_dir=run_dir, snapshot=snapshot))
    inputs = cast(data.ResearchInputs, loaded)
    menu = parent["jobs"][job_name]["menu"]
    spec = inputs.menu(menu)
    columns = A.load_tables(Path(run_dir) / job_name, parent["digest"])["columns"]
    rows = []
    for month in parent["menus"][menu]["schedule"]:
        month = str(month)
        rec = RC.recorded_columns(columns, month)
        context = data.origin_context(inputs, spec, month)
        rows.append(geometry_row(month, context.mu_s, context.cov, spec.lower, spec.upper, rec))
        print(month, file=sys.stderr, flush=True)
    return pd.DataFrame(rows), A.eligible_origins(parent, menu)


def list_problems(result: dict[str, Any]) -> list[str]:
    """How the rebuilt exclusions differ from the pre-registered lists; empty when they match."""
    problems = []
    if result["e_excluded"] != list(RC.E_EXCLUDED):
        problems.append(
            f"e_excluded differs from the pre-registered list: got {result['e_excluded']}, "
            f"expected {list(RC.E_EXCLUDED)}"
        )
    found = {(month, rf) for month, rf in result["u_excluded"]}
    for month, rf in RC.U_EXCLUDED:
        if (month, rf) not in found:
            problems.append(f"the pre-registered U cell ({month}, {rf}) is not excluded")
    return problems


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--job", default=JOB)
    parser.add_argument("--out", help="write the per-month table here as CSV")
    args = parser.parse_args(argv)
    table, eligible = build_table(args.run_dir, args.snapshot, args.job)
    if args.out:
        table.to_csv(args.out, index=False)
    result = summary(table, eligible)
    print(json.dumps(result, indent=2))
    problems = list_problems(result)
    for problem in problems:
        print(problem, file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
