"""Calibration of a GARCH bank rule on fixed mixes: simulation only, no optimizer.

Usage, from the repo root of the code version under test, BLAS threads 1:
    .venv/bin/python scripts/fixed_risk_rule_compare.py run --snapshot S --run-dir R --out DIR
        [--ledger-cache C] [--workers 2] [--menus research2003 tsp] [--months M ...]
    .venv/bin/python scripts/fixed_risk_rule_compare.py summary --rule old=DIR1 --rule new=DIR2
        [--json OUT]

`run` builds, at every scheduled origin of each menu (primary seed, 3-year lookback), the GARCH
bank of the code it runs under and evaluates on it the fixed mixes of the replay run's locked
primary-seed main-grid U1 selections (`R/<menu>_replay/tasks/<menu>_<month>_replay.parquet`, all
cells, every row with weights). For each (origin, mix) it records the bank's Bad quantile (2.5th
percentile, NumPy "linear"), the realized daily-rebalanced year (`realized.daily_rebalanced`,
protocol §5), its percentile in the bank (PIT: the share of simulated years below it, ties
counted half) and whether it fell below Bad. One JSON file per origin, `DIR/<menu>/<month>.json`;
an origin already written is skipped, so a run resumes. An origin whose bank cannot be built
(`garch_fit_failed`) is written with that status and no rows; one without a complete realized
horizon is written as `no_horizon`.

`summary` compares rules per menu: the Bad-breach rate against the nominal 2.5% with Kupiec's
proportion-of-failures test, and the PIT decile histogram with a chi-square uniformity test, on
all origins (overlapping years) and on the disjoint intervals (`data.disjoint_intervals`), each
on the origins every rule has and on each rule's own origins. Origins a rule dropped are counted
as missing. The tests treat every (origin, mix) as independent; the mixes of one origin share a
year and neighbouring origins overlap, so their p-values overstate the evidence, and the disjoint
rows are the honest ones.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
import warnings
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

import numpy as np

NOMINAL = 0.025
DECILES = 10
_STATE: dict[str, Any] = {}


# ----------------------------------------------------------------------------------- run


def _init(snapshot: str, cache: str | None) -> None:
    warnings.simplefilter("ignore")
    from portfoliosight.research.fixedrisk import data

    _STATE["inputs"] = data.load_inputs(snapshot, ledger_cache=cache)


def _mixes(run_dir: Path, menu: str, month: str) -> tuple[list[str], np.ndarray] | None:
    import pyarrow.parquet as pq

    from portfoliosight.research.fixedrisk import contracts as C

    path = run_dir / f"{menu}_replay" / "tasks" / f"{menu}_{month}_replay.parquet"
    if not path.is_file():
        return None
    rows = pq.read_table(path).to_pylist()
    chosen = [
        r
        for r in rows
        if r["kind"] == "main"
        and r["arm"] == "U1"
        and r["seed"] == C.PRIMARY_SEED
        and r["lookback"] == C.LOOKBACK
        and r["weights"]
    ]
    if not chosen:
        return None
    return [r["sel_id"] for r in chosen], np.array([r["weights"] for r in chosen], dtype=float)


def _origin(job: tuple[str, str, str, bool]) -> dict[str, Any]:
    from portfoliosight.research.fixedrisk import contracts as C
    from portfoliosight.research.fixedrisk import data, driver, realized

    menu, month, run_dir, disjoint = job
    inputs = _STATE["inputs"]
    started = time.perf_counter()
    out: dict[str, Any] = {"menu": menu, "month": month, "disjoint": disjoint, "rows": []}
    found = _mixes(Path(run_dir), menu, month)
    if found is None:
        return {**out, "status": "no_mixes", "seconds": time.perf_counter() - started}
    ids, weights = found
    horizon = data.horizon_returns(inputs, menu, month)
    if horizon.returns is None:
        return {**out, "status": "no_horizon", "seconds": time.perf_counter() - started}
    ctx = data.origin_context(inputs, menu, month)
    try:
        bank = driver.real_make_bank(ctx, "garch", C.PRIMARY_SEED)
    except Exception as exc:
        if not driver.is_fit_failure(exc):
            raise
        return {
            **out,
            "status": C.FIT_FAILED,
            "error": f"{type(exc).__name__}: {exc}",
            "seconds": time.perf_counter() - started,
        }
    years = bank.years(weights)  # P x M
    bad = np.percentile(years, 2.5, axis=0)
    real = realized.daily_rebalanced(horizon.returns, weights).annual
    below = (years < real).sum(axis=0)
    ties = (years == real).sum(axis=0)
    pit = (below + 0.5 * ties) / years.shape[0]
    out["rows"] = [
        {
            "sel_id": ids[j],
            "bad": float(bad[j]),
            "realized": float(real[j]),
            "pit": float(pit[j]),
            "breach": bool(real[j] < bad[j]),
        }
        for j in range(len(ids))
    ]
    out["windows"] = getattr(bank, "windows", None)
    out["fallbacks"] = getattr(bank, "fallbacks", None) or {}
    return {**out, "status": "ok", "seconds": time.perf_counter() - started}


def _write(path: Path, body: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(body, indent=1, sort_keys=True))
    os.replace(tmp, path)


def run(args: argparse.Namespace) -> int:
    from portfoliosight.research.fixedrisk import data

    _init(args.snapshot, args.ledger_cache)
    inputs = _STATE["inputs"]
    out = Path(args.out)
    jobs = []
    for menu in args.menus:
        disjoint = {interval.month for interval in data.disjoint_intervals(inputs, menu)}
        for month in data.schedule(inputs, menu):
            if args.months and month not in args.months:
                continue
            if not (out / menu / f"{month}.json").is_file():
                jobs.append((menu, month, args.run_dir, month in disjoint))
    print(f"{len(jobs)} origins to run", flush=True)
    started, cpu = time.perf_counter(), time.process_time()
    seconds = 0.0
    with ProcessPoolExecutor(
        args.workers, initializer=_init, initargs=(args.snapshot, args.ledger_cache)
    ) as pool:
        for k, result in enumerate(pool.map(_origin, jobs)):
            seconds += result["seconds"]
            _write(out / result["menu"] / f"{result['month']}.json", result)
            if k % 25 == 0:
                print(f"{k} {result['menu']} {result['month']} {result['status']}", flush=True)
    wall = time.perf_counter() - started
    print(f"done: {len(jobs)} origins, wall {wall:.0f}s, worker seconds {seconds:.0f}", flush=True)
    _write(
        out / "cost.json",
        {"origins": len(jobs), "wall_seconds": wall, "worker_seconds": seconds,
         "parent_cpu_seconds": time.process_time() - cpu},
    )  # fmt: skip
    return 0


# ------------------------------------------------------------------------------- summary


def kupiec(n: int, x: int, p: float = NOMINAL) -> tuple[float, float]:
    """Kupiec's proportion-of-failures likelihood ratio and its chi-square(1) p-value."""
    from scipy.stats import chi2

    if n == 0:
        return math.nan, math.nan

    def loglik(q: float) -> float:
        a = (n - x) * math.log(1.0 - q) if x < n else 0.0
        b = x * math.log(q) if x > 0 else 0.0
        return a + b

    lr = -2.0 * (loglik(p) - loglik(x / n))
    return lr, float(chi2.sf(lr, 1))


def pit_uniformity(pits: np.ndarray) -> tuple[list[int], float]:
    """Decile counts of the PITs and the chi-square uniformity p-value (9 df)."""
    from scipy.stats import chisquare

    counts = np.histogram(np.clip(pits, 0.0, 1.0), bins=DECILES, range=(0.0, 1.0))[0]
    if counts.sum() == 0:
        return counts.tolist(), math.nan
    return counts.tolist(), float(chisquare(counts).pvalue)


def _load(root: Path) -> dict[str, dict[str, dict[str, Any]]]:
    found: dict[str, dict[str, dict[str, Any]]] = {}
    for path in sorted(root.glob("*/*.json")):
        body = json.loads(path.read_text())
        found.setdefault(body["menu"], {})[body["month"]] = body
    return found


def _stats(origins: list[dict[str, Any]]) -> dict[str, Any]:
    rows = [row for origin in origins for row in origin["rows"]]
    n, x = len(rows), sum(row["breach"] for row in rows)
    lr, p_kupiec = kupiec(n, x)
    counts, p_uniform = pit_uniformity(np.array([row["pit"] for row in rows]))
    return {
        "origins": len(origins),
        "obs": n,
        "breaches": x,
        "breach_rate": x / n if n else math.nan,
        "kupiec_lr": lr,
        "kupiec_p": p_kupiec,
        "pit_deciles": counts,
        "pit_uniform_p": p_uniform,
    }


def summary(args: argparse.Namespace) -> int:
    rules = dict(item.split("=", 1) for item in args.rule)
    loaded = {name: _load(Path(path)) for name, path in rules.items()}
    menus = sorted({menu for found in loaded.values() for menu in found})
    report: dict[str, Any] = {}
    lines = [
        "| menu | scope | origins | rule | origins used | missing (fit failed) | obs | breaches"
        " | rate | Kupiec p | PIT deciles | PIT uniform p |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for menu in menus:
        per_rule = {name: found.get(menu, {}) for name, found in loaded.items()}
        months = sorted(set().union(*(set(found) for found in per_rule.values())))
        ok = {
            name: {m for m, body in found.items() if body["status"] == "ok"}
            for name, found in per_rule.items()
        }
        evaluable = {
            m
            for m in months
            if all(found.get(m, {}).get("status") not in ("no_mixes", "no_horizon")
                   for found in per_rule.values())
        }  # fmt: skip
        common = set.intersection(*ok.values()) if ok else set()
        for scope in ("all", "disjoint"):
            for subset in ("own", "common"):
                for name, found in per_rule.items():
                    chosen = sorted(
                        m
                        for m in (common if subset == "common" else ok[name])
                        if scope == "all" or found[m]["disjoint"]
                    )
                    base = sorted(
                        m
                        for m in evaluable
                        if scope == "all"
                        or any(f.get(m, {}).get("disjoint") for f in per_rule.values())
                    )
                    missing = sum(found.get(m, {}).get("status") != "ok" for m in base)
                    stats = _stats([found[m] for m in chosen])
                    stats["missing"] = missing if subset == "own" else len(base) - len(chosen)
                    report.setdefault(menu, {}).setdefault(f"{scope}/{subset}", {})[name] = stats
                    lines.append(
                        f"| {menu} | {scope}, {subset} origins | {len(base)} | {name} "
                        f"| {stats['origins']} | {stats['missing']} | {stats['obs']} "
                        f"| {stats['breaches']} | {stats['breach_rate']:.3%} "
                        f"| {stats['kupiec_p']:.3g} | {stats['pit_deciles']} "
                        f"| {stats['pit_uniform_p']:.3g} |"
                    )
    text = "\n".join(lines)
    print(text)
    if args.json:
        Path(args.json).write_text(json.dumps(report, indent=1, sort_keys=True))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    r = sub.add_parser("run")
    r.add_argument("--snapshot", required=True)
    r.add_argument("--run-dir", required=True)
    r.add_argument("--out", required=True)
    r.add_argument("--ledger-cache")
    r.add_argument("--workers", type=int, default=2)
    r.add_argument("--menus", nargs="+", default=["research2003", "tsp"])
    r.add_argument("--months", nargs="+", help="only these origin months (a smoke test)")
    s = sub.add_parser("summary")
    s.add_argument("--rule", action="append", required=True, help="name=DIR, repeated")
    s.add_argument("--json")
    args = parser.parse_args(argv)
    return run(args) if args.command == "run" else summary(args)


if __name__ == "__main__":
    sys.exit(main())
