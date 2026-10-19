"""A synthetic experiment shared by the runner and report tests (plan 6b.5, 6b.6).

Seeded total-return indices (tests/research/helpers.py) on the installed XNYS sessions for a
three-fund "tsp" menu (caps .60) and a five-fund "example" menu (caps .25), D* 2025-09-30, a 2y
lookback and reduced search budgets (`make_settings` makes the reductions explicit, and a run's
manifest lists them as deviations). Origins 2024-07 and 2024-08 are mature, 2024-09 is
immature. `run_experiment` writes a run under ``tmp/out``; nothing reads the mirror.
"""

from __future__ import annotations

import functools
import hashlib
import importlib.util
import sys
from collections.abc import Callable
from dataclasses import replace
from datetime import date
from pathlib import Path
from types import ModuleType
from typing import Any

import exchange_calendars as xcals
import pandas as pd

from portfoliosight.research import experiment, harness, search
from portfoliosight.research.experiment import Inputs, Investigation, Limits, Provenance, Settings
from portfoliosight.research.search import Budget
from tests.research.helpers import random_indices, record

ROOT = Path(__file__).resolve().parents[2]
D_STAR = date(2025, 9, 30)
MENUS = {"tsp": ("TSP-G", "TSP-F", "TSP-C"), "example": ("X", "Y", "Z", "V", "W")}
DRIFT_VOL = {
    "TSP-G": (1.2e-4, 3e-5),
    "TSP-F": (1.5e-4, 0.003),
    "TSP-C": (4e-4, 0.011),
    "X": (3e-4, 0.009),
    "Y": (2e-4, 0.005),
    "Z": (5e-4, 0.014),
    "V": (1e-4, 0.002),
    "W": (3.5e-4, 0.012),
}
TINY = Budget(points=8, starts=2, calls=8, maxiter=8)
PRIMARY, SECOND = 20261013, 20261014
PROTOCOL_BYTES = b"the protocol text at HEAD"
PROVENANCE = Provenance(
    head="a" * 40,
    dirty=(),
    protocol_sha256=hashlib.sha256(PROTOCOL_BYTES).hexdigest(),
    protocol_status="Status: test",
    worktrees=(),
    git_dirs=(),
    ignored=lambda path: False,
)
PREFIX = hashlib.sha256(PROTOCOL_BYTES).hexdigest()[:16]

Records = dict[str, pd.DataFrame]
Mutation = Callable[[dict[str, pd.Series]], dict[str, pd.Series]]


@functools.cache
def xnys_sessions() -> pd.DatetimeIndex:
    return pd.DatetimeIndex(
        xcals.get_calendar("XNYS", start="2021-01-01", end="2027-12-31").sessions
    )


@functools.cache
def fixture_indices() -> dict[str, pd.Series]:
    sessions = xnys_sessions()
    days = sessions[(sessions >= pd.Timestamp("2022-01-03")) & (sessions <= pd.Timestamp(D_STAR))]
    return random_indices(pd.DatetimeIndex(days), DRIFT_VOL, 20261019)


def make_records(*mutations: Mutation) -> Records:
    series = dict(fixture_indices())
    for mutate in mutations:
        series = mutate(dict(series))
    return {symbol: record(values) for symbol, values in series.items()}


def scale_price(day: str, factor: float, *symbols: str) -> Mutation:
    def mutate(series: dict[str, pd.Series]) -> dict[str, pd.Series]:
        for symbol in symbols:
            values = series[symbol].copy()
            values[pd.Timestamp(day)] *= factor
            series[symbol] = values
        return series

    return mutate


def make_inputs(records: Records, root: Path) -> Inputs:
    data = harness.SnapshotInputs(
        root=root / "snapshot",
        manifest_sha256="f" * 64,
        source_root=str(root / "mirror"),
        d_star=D_STAR,
        menus=dict(MENUS),
        records=records,
        sessions=xnys_sessions(),
    )
    manifest = {
        "files": [{"path": "prices/X.parquet", "sha256": "0" * 64}],
        "calendar": {"name": "XNYS"},
    }
    return Inputs(data, manifest, "2026-10-19T00:00:00+00:00")


def make_settings(records: Records, **changes: Any) -> Settings:
    """Reduced settings whose investigation digest is this fixture's own (a precondition)."""
    digest = search.production_sample_digest(records, MENUS["tsp"], "1y", D_STAR)
    base = Settings(
        lookback="2y",
        seeds=(PRIMARY, SECOND),
        budget=TINY,
        months=("2024-07", "2024-09"),
        investigation=Investigation(menu="tsp", lookback="1y", asof=D_STAR, digest=digest),
    )
    return replace(base, **changes)


def run_experiment(
    tmp: Path, records: Records | None = None, **kwargs: Any
) -> experiment.RunResult:
    records = records if records is not None else make_records()
    settings = kwargs.pop("settings", None) or make_settings(records)
    limits = kwargs.pop("limits", Limits(workers=0))
    out = kwargs.pop("out", tmp / "out")
    return experiment.run(
        make_inputs(records, tmp), PROVENANCE, out, settings=settings, limits=limits, **kwargs
    )


def load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module
