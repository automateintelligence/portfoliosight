"""Time tensor builds of synthetic menus, to see how a build scales with funds and workers.

Usage, from the repo root:
    python scripts/bench_build.py --funds 23 60 100 --workers 1 4 [--repeat 2] [--profile]
    taskset -c 0-3 python scripts/bench_build.py --funds 100 --workers 4
    docker exec -i portfoliosight-api python -c "import sys; exec(sys.stdin.read())" \
        --funds 23 --workers 4 < scripts/bench_build.py

The menus come from one generator, so a run can be repeated anywhere: a six-factor model drawn
from seed 7 over the business days 2016-01-04 to 2026-10-13, one column per fund, built for the
5y lookback with the default caps. `--workers` sets `PS_BUILD_WORKERS` for each build; pin the
process with `taskset` to measure a given number of CPUs. Piped into a container, the script
runs through `-c` and `exec`, not `python -`: a worker process re-imports the main module by its
path, and `<stdin>` has none. Each line reports the wall time of
the build call and the tensor's own `build_seconds`; the process pool for a worker count is
started before its builds and timed on its own (`pool_s`). `--profile` adds the wall time of
each stage of the build (the parallel stages include waiting for the workers).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import numpy as np
import pandas as pd

if "__file__" in globals():  # run from a checkout: its package; piped on stdin: the installed one
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from portfoliosight.cpus import build_workers  # noqa: E402
from portfoliosight.engine import builder, parallel, surface  # noqa: E402
from portfoliosight.engine.tensor import FundInput, TensorInputs, build_tensor  # noqa: E402

START, END = "2016-01-04", "2026-10-13"
SEED = 7
FACTORS = 6
LOOKBACK = "5y"
FACTOR_MEAN = np.array([0.0004, 0.0001, 0.00005, 0.0, 0.0, 0.0])  # daily
FACTOR_VOL = np.array([0.011, 0.006, 0.005, 0.004, 0.003, 0.002])  # daily
PHASES = (  # the build's stages, by the functions that run them, for --profile
    ("window, moments, torsion", builder, ("select_window", "estimate_moments", "torsion_basis")),
    ("frontiers (conic)", builder, ("frontier",)),
    ("peak search and first sweeps", surface, ("peak_pools",)),
    ("ladders", surface, ("ladders", "column")),
    ("sweeps after the ladders", surface, ("spread_peaks",)),
    ("raster", builder, ("raster",)),
    ("post-check", builder, ("_post_check",)),
    ("one-year ranges", builder, ("range_model", "one_year_ranges")),
    ("stress", builder, ("segments_from_returns", "stress_returns")),
    ("schema check", builder, ("validate_tensor",)),
)


def synthetic_returns(funds: int, seed: int = SEED) -> pd.DataFrame:
    """Daily returns of `funds` funds from a six-factor model: bond-like to stock-like."""
    rng = np.random.default_rng(seed)
    days = pd.bdate_range(START, END, name="date")
    factors = rng.normal(FACTOR_MEAN, FACTOR_VOL, (len(days), FACTORS))
    loadings = rng.normal(0.0, 0.5, (funds, FACTORS))
    loadings[:, 0] = rng.uniform(0.0, 1.3, funds)  # market beta
    noise = rng.normal(0.0, 1.0, (len(days), funds)) * rng.uniform(0.001, 0.008, funds)
    ids = [f"F{i:03d}" for i in range(funds)]
    return pd.DataFrame(factors @ loadings.T + noise, index=days, columns=ids)


def bench_inputs(funds: int) -> TensorInputs:
    frame = synthetic_returns(funds)
    menu = [
        FundInput(
            id=fund,
            name=fund,
            kind="etf",
            source="seed",
            adjusted_through=END,
            fetched_at=f"{END}T00:00:00Z",
        )
        for fund in frame.columns
    ]
    return TensorInputs(
        funds=menu, returns=frame, lookback=LOOKBACK, asof=END, universe_name="Benchmark"
    )


@contextmanager
def timed_phases(seconds: dict[str, float]) -> Iterator[None]:
    """Add the wall time of each phase's functions to `seconds` while the block runs."""
    patched = []
    for label, module, names in PHASES:
        for name in names:
            original = getattr(module, name, None)
            if original is None:
                continue

            def timed(*args, _original=original, _label=label, **kwargs):
                started = time.perf_counter()
                try:
                    return _original(*args, **kwargs)
                finally:
                    seconds[_label] = seconds.get(_label, 0.0) + time.perf_counter() - started

            patched.append((module, name, original))
            setattr(module, name, timed)
    try:
        yield
    finally:
        for module, name, original in patched:
            setattr(module, name, original)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Time tensor builds of synthetic menus.")
    parser.add_argument("--funds", type=int, nargs="+", default=[23, 60, 100])
    parser.add_argument("--workers", type=int, nargs="+", default=[1])
    parser.add_argument("--repeat", type=int, default=1, help="builds per (funds, workers)")
    parser.add_argument("--profile", action="store_true", help="print the time per phase")
    args = parser.parse_args(argv)

    cpus = sorted(os.sched_getaffinity(0))
    load = os.getloadavg()
    print(
        f"# cpus {len(cpus)} {cpus} auto_workers {build_workers({})} "
        f"load {load[0]:.1f} {load[1]:.1f} {load[2]:.1f}"
    )
    for funds in args.funds:
        inputs = bench_inputs(funds)
        for workers in args.workers:
            os.environ["PS_BUILD_WORKERS"] = str(workers)
            started = time.perf_counter()
            parallel.warm_up(workers)
            pool_s = time.perf_counter() - started
            for run in range(args.repeat):
                phases: dict[str, float] = {}
                started = time.perf_counter()
                if args.profile:
                    with timed_phases(phases):
                        tensor = build_tensor(inputs)
                else:
                    tensor = build_tensor(inputs)
                wall = time.perf_counter() - started
                row = {
                    "funds": funds,
                    "included": len(tensor["universe"]["funds"]),
                    "workers": workers,
                    "run": run,
                    "wall_s": round(wall, 2),
                    "build_seconds": tensor["build_seconds"],
                    "pool_s": round(pool_s, 2),
                    "load1": round(os.getloadavg()[0], 1),
                }
                if args.profile:
                    row["phases"] = {name: round(phases.get(name, 0.0), 2) for name, *_ in PHASES}
                print(json.dumps(row), flush=True)
    parallel.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
