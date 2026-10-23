"""Run one engine's pre-lock gates of the fixed-risk experiment (protocol v2 §4, §9).

Usage, from the repo root, with BLAS threads set to 1:
    .venv/bin/python scripts/fixed_risk_gates.py --snapshot S --engine replay|garch --out DIR
        [--workers 6]

Two checks, written to `DIR/gates_<engine>.json`:
- finite differences: `agreement.fdcheck` on the primary bank at one mid-sample showcase origin
  per menu (10 mixes x 20 directions per quantile and mode);
- agreement: 30 cells drawn by a fixed seed, 15 per menu, 10 of them narrow (d25 or d75), each
  solved for U1 and max-Bad by the exact- and kernel-gradient solvers and by COBYLA at 768 and 128
  calls per start; `agreement.agreement_decision` applies the 57-of-60 rule.
Cases run in parallel worker processes; each worker loads the snapshot once.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
from pathlib import Path

import numpy as np

from portfoliosight.research.fixedrisk import agreement, data, driver
from portfoliosight.research.fixedrisk import contracts as C

CASES_PER_MENU = 15
NARROW_PER_MENU = 5
_STATE: dict[str, object] = {}


def _init(snapshot: str, cache: str) -> None:
    _STATE["inputs"] = data.load_inputs(snapshot, ledger_cache=cache)


def _ctx_bank(menu: str, month: str, engine: str):
    inputs = _STATE["inputs"]
    ctx = data.origin_context(inputs, menu, month)
    return ctx, driver.real_make_bank(ctx, engine, C.PRIMARY_SEED)


def _agreement_case(job: tuple[int, str, str, float, str, str]) -> list[dict]:
    k, menu, month, r_fraction, cell, engine = job
    ctx, bank = _ctx_bank(menu, month, engine)
    case = agreement.AgreementCase(ctx, bank, r_fraction, cell)
    report = agreement.agreement_check([case])
    rows = []
    for row in report.rows:
        item = asdict(row)
        item["case"] = k
        item["month"] = month
        rows.append(item)
    return rows


def _fd(job: tuple[str, str, str]) -> dict:
    menu, month, engine = job
    ctx, bank = _ctx_bank(menu, month, engine)
    result = agreement.fdcheck(bank, ctx)
    out = {"menu": menu, "month": month}
    out.update(
        {
            k: (v if isinstance(v, (bool, int, float, str)) else str(v))
            for k, v in vars(result).items()
        }
    )
    return out


def draw_cases(inputs, engine: str) -> list[tuple[int, str, str, float, str, str]]:
    rng = np.random.default_rng(agreement.derived_seed("agreement-cases", engine))
    cases = []
    for menu in ("research2003", "tsp"):
        months = data.schedule(inputs, menu)
        for j in range(CASES_PER_MENU):
            month = months[int(rng.integers(len(months)))]
            r_fraction = float(C.RISK_FRACTIONS[int(rng.integers(len(C.RISK_FRACTIONS)))])
            if j < NARROW_PER_MENU:
                cell = ("d25", "d75")[j % 2]
            else:
                cell = C.CELLS[int(rng.integers(len(C.CELLS)))]
            cases.append((len(cases), menu, month, r_fraction, cell, engine))
    return cases


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--engine", required=True, choices=C.ENGINES)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args(argv)
    for name in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
        if os.environ.get(name) != "1":
            print(f"set {name}=1", file=sys.stderr)
            return 2
    args.out.mkdir(parents=True, exist_ok=True)
    cache = str(args.out / "ledger_cache")
    inputs = data.load_inputs(args.snapshot, ledger_cache=cache)
    cases = draw_cases(inputs, args.engine)
    fd_jobs = []
    for menu in ("research2003", "tsp"):
        months = data.showcase_months(inputs, menu)
        fd_jobs.append((menu, months[len(months) // 2], args.engine))
    started = time.time()
    with ProcessPoolExecutor(
        args.workers, initializer=_init, initargs=(args.snapshot, cache)
    ) as pool:
        fd_futures = [pool.submit(_fd, job) for job in fd_jobs]
        case_futures = [pool.submit(_agreement_case, job) for job in cases]
        fd = [f.result() for f in fd_futures]
        rows = [row for f in case_futures for row in f.result()]
    decision = agreement.agreement_decision(
        [
            agreement.AgreementRow(**{k: r[k] for k in agreement.AgreementRow.__dataclass_fields__})
            for r in rows
        ]
    )
    result = {
        "engine": args.engine,
        "snapshot": args.snapshot,
        "seconds": time.time() - started,
        "fdcheck": fd,
        "fd_passed": all(item.get("passed") is True for item in fd),
        "cases": [
            dict(zip(("case", "menu", "month", "r_fraction", "cell"), c[:5], strict=True))
            for c in cases
        ],
        "agreement": {
            "pairs": decision.pairs,
            "needed": decision.needed,
            "passes": decision.passes,
            "accepted": decision.accepted,
            "median_seconds": decision.median_seconds,
            "chosen": decision.chosen,
        },
        "rows": rows,
    }
    path = args.out / f"gates_{args.engine}.json"
    path.write_text(json.dumps(result, indent=2, default=str))
    print(
        json.dumps(
            {k: result[k] for k in ("engine", "seconds", "fd_passed", "agreement")},
            indent=2,
            default=str,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
