"""Build the preset tensors of one day from a local store, without writing to it (plan task 3.6).

Usage, from the repo root:
    python scripts/build_presets.py --store-dir /mnt/d/portfoliosight-data --asof 2026-10-15 \
        --out runs/dry-0.3.0/ [--presets guide2017,tsp] [--lookbacks 1y,2y,3y,5y,10y,ew] \
        [--engines replay,garch]

A dry run of the nightly's preset builds for this engine version against a copy of the store,
such as the laptop's backup mirror. The store is opened read-only: nothing is ever written to
it. Each preset x lookback is built as the nightly builds it (`inputs_from_store` at `--asof`,
then the volatility model looked up by its shape digest, fitted when absent, and stored), with
the API's grid (`PS_GRID_NX`, `PS_GRID_NY`, `PS_GRID_LEVELS`) and the build's own worker count
(`PS_BUILD_WORKERS`, else the CPUs available). `--engines` defaults to `PS_ENGINES`, the presets'
engines. Everything is written under `--out`, which must be new or empty and outside the store,
in the store's own layout: `tensors/{G}/{hash}/{lookback}.json` and
`models/{G}/{shape16}/garch.json` with `pool.npy`, `G` = `{asof}-{engine version}`. The price
records are read through a scratch cache in a temporary directory.

Prints JSON lines: the run (store, generation, engines, CPUs, load average); then per tensor its
`build_seconds`, the wall time, the time spent fitting the volatility model (`fit_seconds`, 0
when a fit stored for the same fund set was reused, null when the model was not asked for),
`reused`, the model's status, `shape16`, `pool_rows`, each fund's fit status, the funds that
fell back to constant volatility, the outliers, the worst simulated day (`worst_day`: the fund
and its daily log return in the raw panel, and simple return after engines spec 4.5, step 1;
each value names its return space), the paths the model counts as ruined (`ruin_paths`, when the
tensor carries it), the Optimized point's bad, typical and good year under each engine at the
slider's three reference
columns (`s_safe`, the domain midpoint, `s_max`), the load average; last the totals.

Exit status 0 when every tensor was built; 2 with one line on stderr naming the preset and
lookback when a build is refused (the splice guard names the fund and the date: a data fix, not
an engine change), and for arguments that cannot be run.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import date
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # this checkout's package

from portfoliosight.api.hashing import universe_hash  # noqa: E402
from portfoliosight.api.presets import (  # noqa: E402
    LOOKBACKS,
    preset_definitions,
    preset_funds,
    tensor_key,
)
from portfoliosight.api.settings import (  # noqa: E402
    EngineSettings,
    GridSettings,
    SettingsError,
    parse_engines,
)
from portfoliosight.cpus import build_workers  # noqa: E402
from portfoliosight.data.store import LocalStore, ReadOnlyStore  # noqa: E402
from portfoliosight.engine import ENGINE_VERSION, builder, parallel  # noqa: E402
from portfoliosight.engine.caps import CapsError  # noqa: E402
from portfoliosight.engine.ranges import GarchRangeModel, _levelled, _step_one  # noqa: E402
from portfoliosight.engine.shape import ShapeError  # noqa: E402
from portfoliosight.engine.tensor import BuildResult, WindowUnavailable  # noqa: E402
from portfoliosight.jobs.build import (  # noqa: E402
    BuildRefused,
    build_with_artifacts,
    inputs_from_store,
    put_tensor,
)

FITTED = "garch"  # the fit status of a fund whose volatility follows its own fitted pattern
FIGURES = ("bad", "typical", "good")


@contextmanager
def timed_fits() -> Iterator[list[float]]:
    """The seconds of every volatility-model fit the builds make while the block runs."""
    seconds: list[float] = []
    original = builder.fit_shape

    def timed(*args, **kwargs):
        started = time.perf_counter()
        try:
            return original(*args, **kwargs)
        finally:
            seconds.append(time.perf_counter() - started)

    builder.fit_shape = timed
    try:
        yield seconds
    finally:
        builder.fit_shape = original


def _load() -> list[float]:
    return [round(value, 2) for value in os.getloadavg()]


def _listed(raw: str, known: list[str] | tuple[str, ...], what: str, parser) -> list[str]:
    named = [part.strip() for part in raw.split(",") if part.strip()]
    unknown = [name for name in named if name not in known]
    if unknown or not named:
        parser.error(f"unknown {what} {(unknown or [raw])[0]!r}; expected some of {list(known)}")
    return named


def _arguments(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the preset tensors of one day.")
    parser.add_argument("--store-dir", type=Path, required=True, help="a local store, read-only")
    parser.add_argument("--asof", type=date.fromisoformat, required=True, help="D_G, YYYY-MM-DD")
    parser.add_argument("--out", type=Path, required=True, help="a new or empty directory")
    parser.add_argument("--presets", default=None, help="comma-separated ids (default: all)")
    parser.add_argument("--lookbacks", default=",".join(LOOKBACKS), help="comma-separated")
    parser.add_argument("--engines", default=None, help="comma-separated (default: PS_ENGINES)")
    args = parser.parse_args(argv)
    ids = [preset.id for preset in preset_definitions()]
    args.presets = _listed(args.presets or ",".join(ids), ids, "preset", parser)
    args.lookbacks = _listed(args.lookbacks, LOOKBACKS, "lookback", parser)
    try:
        engines = EngineSettings.from_env().engines
        args.engines = engines if args.engines is None else parse_engines(args.engines, "--engines")
    except SettingsError as exc:
        parser.error(str(exc))
    store_dir: Path = args.store_dir.resolve()
    out: Path = args.out.resolve()
    if not store_dir.is_dir():
        parser.error(f"--store-dir {args.store_dir} is not a directory")
    if out == store_dir or store_dir in out.parents:
        parser.error(f"--out {args.out} is inside the store; nothing is written there")
    if out.exists() and (not out.is_dir() or any(out.iterdir())):
        parser.error(f"--out {args.out} must be a new or empty directory")
    args.store_dir, args.out = store_dir, out
    return args


def worst_day(model: GarchRangeModel, funds: list[str]) -> dict:
    """The lowest simulated daily log return, and simple return after the per-fund level step.

    Step 1 is the engine's lognormal moment match, then `expm1`. Its scale is nonnegative,
    so each fund's lowest log return is also its lowest levelled simple return. A constant
    fund receives its daily target exactly, as it does in the engine.
    """
    low = model.panel.min(axis=(0, 1))
    step = _step_one(model.mu_s, model.cov, model.mean, model.sd)
    level = _levelled(low[None, :], step, np.empty((1, len(low))))[0]

    def lowest(values: np.ndarray, returns: str) -> dict:
        n = int(np.argmin(values))
        return {"id": funds[n], "value": float(values[n]), "returns": returns}

    return {"raw": lowest(low, "log"), "level": lowest(level, "simple")}


def optimized_points(tensor: Mapping) -> dict:
    """The Optimized point's bad, typical and good year under each engine the tensor carries, at
    the slider's left end (`s_safe`), its midpoint and its right end (`s_max`)."""
    ladder = tensor["ladder"]
    last_column = len(ladder["t_suggested"]) - 1
    last_level = len(ladder["y"][0]) - 1
    left = int(tensor["frontier"]["s_safe"])
    columns = {"s_safe": left, "mid": (left + last_column) // 2, "s_max": last_column}
    points = {}
    for name, column in columns.items():
        level = round(ladder["t_suggested"][column] * last_level)
        figures = {
            engine: {figure: block[figure][column][level] for figure in FIGURES}
            for engine, block in ladder["ranges"].items()
        }
        points[name] = {"column": column, "level": level, **figures}
    return points


def _row(
    preset: str,
    lookback: str,
    result: BuildResult,
    wall: float,
    fits: list[float],
    reused: bool,
) -> dict:
    tensor = result.tensor
    shape = tensor["shape"]
    funds = {} if shape is None else {fund["id"]: fund["status"] for fund in shape["funds"]}
    garch = tensor["engines"]["garch"]
    model = result.models.get("garch")
    if not isinstance(model, GarchRangeModel):
        model = None
    return {
        "preset": preset,
        "lookback": lookback,
        "hash": tensor["universe"]["hash"],
        "included": len(tensor["universe"]["funds"]),
        "excluded": [entry["id"] for entry in tensor["universe"]["excluded"]],
        "build_seconds": tensor["build_seconds"],
        "wall_seconds": round(wall, 3),
        "fit_seconds": None if shape is None else round(sum(fits), 3),
        "reused": None if shape is None else reused,
        "garch": garch["status"] if garch["status"] == "ready" else garch["reason"],
        "shape16": None if shape is None else shape["sample_sha256"][:16],
        "pool_rows": None if shape is None else shape["pool_rows"],
        "funds": funds,
        "fallback": [fund for fund, status in funds.items() if status != FITTED],
        "outliers": [] if shape is None else shape["outliers"],
        "worst_day": None if model is None else worst_day(model, list(funds)),
        "ruin_paths": garch.get("ruin_paths"),
        "optimized": optimized_points(tensor),
        "load": _load(),
    }


def main(argv: list[str] | None = None) -> int:
    args = _arguments(argv)
    store = ReadOnlyStore(LocalStore(args.store_dir))
    output = LocalStore(args.out)
    grid = GridSettings.from_env()
    generation = f"{args.asof.isoformat()}-{ENGINE_VERSION}"
    presets = {preset.id: preset for preset in preset_definitions()}
    print(
        json.dumps(
            {
                "store": store.describe(),
                "asof": args.asof.isoformat(),
                "generation": generation,
                "engines": list(args.engines),
                "grid": grid.model_dump(),
                "cpus": sorted(os.sched_getaffinity(0)),
                "workers": build_workers(),
                "load": _load(),
            }
        ),
        flush=True,
    )
    began = time.perf_counter()
    built = 0
    all_fits: list[float] = []
    try:
        with tempfile.TemporaryDirectory(prefix="ps-build-presets-") as cache, timed_fits() as fits:
            for preset_id in args.presets:
                preset = presets[preset_id]
                funds = preset_funds(preset)
                uhash = universe_hash(funds)
                for lookback in args.lookbacks:
                    fits.clear()
                    started = time.perf_counter()
                    inputs = inputs_from_store(
                        store,
                        funds=funds,
                        lookback=lookback,
                        asof=args.asof,
                        cache_dir=cache,
                        universe_name=preset.name,
                        preset_id=preset.id,
                        allocation=preset.allocation,
                        nx=grid.nx,
                        ny=grid.ny,
                        levels=grid.levels,
                        engines=args.engines,
                    )
                    try:
                        result, reused = build_with_artifacts(
                            output, generation, inputs, cache_dir=cache
                        )
                    except ShapeError as exc:
                        where = f" ({exc.fund} on {exc.date})" if exc.fund else ""
                        print(f"{preset_id} {lookback}: refused{where}: {exc}", file=sys.stderr)
                        return 2
                    except (WindowUnavailable, CapsError, BuildRefused) as exc:
                        print(f"{preset_id} {lookback}: refused: {exc}", file=sys.stderr)
                        return 2
                    put_tensor(output, tensor_key(generation, uhash, lookback), result.tensor)
                    wall = time.perf_counter() - started
                    all_fits.extend(fits)
                    built += 1
                    row = _row(preset_id, lookback, result, wall, fits, reused)
                    print(json.dumps(row), flush=True)
    finally:
        parallel.shutdown()
    total = {
        "tensors": built,
        "fits": len(all_fits),
        "fit_seconds": round(sum(all_fits), 3),
        "total_seconds": round(time.perf_counter() - began, 3),
        "load": _load(),
    }
    print(json.dumps(total), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
