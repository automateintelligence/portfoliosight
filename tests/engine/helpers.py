"""Shared helpers for the engine tests: paths and loading repo scripts as modules."""

from __future__ import annotations

import dataclasses
import importlib.util
import json
import sys
from functools import lru_cache
from pathlib import Path
from types import ModuleType

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from threadpoolctl import threadpool_limits

from portfoliosight.engine.ladder import EnbProgram
from portfoliosight.engine.optimize import Frontier, MenuPrograms, frontier
from portfoliosight.engine.shape import GarchArtifact, fit_shape, shape_panel
from portfoliosight.engine.tensor import FundInput, TensorInputs
from portfoliosight.engine.torsion import TorsionBasis, enb, torsion_basis

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
FIXTURE = ROOT / "tests" / "fixtures" / "synthetic_23.parquet"
UI_FIXTURE = ROOT / "web" / "fixtures" / "guide2017_5y.json"
HOLDINGS = ROOT / "data" / "holdings" / "holdings_guide2017_step2.csv"
FIXTURE_ASOF = "2026-10-12"
METADATA_KEY = b"portfoliosight"
# The catalog's converted fund (spec 5.1): its data ended, so no menu can use it.
CONVERTED = "FIENX"
CONVERTED_LAST_DAY = "2024-10-30"
CONVERTED_REASON = f"converted to an ETF; no data since {CONVERTED_LAST_DAY}"
CONVERTED_FACTS = {
    "name": "Fidelity International Enhanced Index Fund",
    "kind": "mutual_fund",
    "source": "tiingo",
    "adjusted_through": CONVERTED_LAST_DAY,
    "fetched_at": "2026-10-13T09:05:11Z",
    "last_close": None,
    "served": False,
    "catalog_reason": CONVERTED_REASON,
}


def load_script(name: str) -> ModuleType:
    """Import `scripts/<name>.py` as a module (scripts/ is not a package)."""
    spec = importlib.util.spec_from_file_location(f"ps_script_{name}", SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None, f"scripts/{name}.py is missing"
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses resolve their module through sys.modules
    spec.loader.exec_module(module)
    return module


def fixture_metadata(path: Path = FIXTURE) -> dict:
    """The JSON document stored under the parquet's `portfoliosight` schema-metadata key."""
    metadata = pq.read_schema(path).metadata or {}
    return json.loads(metadata[METADATA_KEY])


@lru_cache(maxsize=1)
def fixture_artifact() -> GarchArtifact:
    """The volatility model fitted to the fixture's 23 funds at its asof, once per session.

    It is fitted as a build fits it (BLAS on one thread). A build reuses it only for its own
    panel (`TensorInputs.garch_artifact`): any build whose included funds or returns differ fits
    its own, and the CLI's builds always fit.
    """
    frame = pd.read_parquet(FIXTURE)
    with threadpool_limits(limits=1, user_api="blas"):
        return fit_shape(shape_panel(frame, list(frame.columns), FIXTURE_ASOF))


def fixture_inputs(lookback: str = "5y", **changes) -> TensorInputs:
    """`TensorInputs` for the synthetic fixture, as the build CLI derives them from the parquet.

    The fixture's fitted volatility model is offered for reuse (`fixture_artifact`); pass
    `garch_artifact=None` to make the build fit it.
    """
    frame = pd.read_parquet(FIXTURE)
    meta = fixture_metadata()
    funds = [
        FundInput(
            id=fund,
            name=meta["funds"][fund]["name"],
            kind=meta["funds"][fund]["kind"],
            source=meta["funds"][fund]["source"],
            adjusted_through=meta["funds"][fund]["adjusted_through"],
            fetched_at=meta["funds"][fund]["fetched_at"],
            last_close=meta["funds"][fund]["last_close"],
            served=meta["funds"][fund]["served"],
            catalog_reason=meta["funds"][fund]["catalog_reason"],
        )
        for fund in frame.columns
    ]
    fields = {
        "funds": funds,
        "returns": frame,
        "lookback": lookback,
        "asof": FIXTURE_ASOF,
        "universe_name": meta["universe"]["name"],
        "preset_id": meta["universe"]["preset_id"],
        "allocation": meta["universe"]["allocation"],
    }
    if "garch_artifact" not in changes and "garch" in changes.get("engines", ("garch",)):
        fields["garch_artifact"] = fixture_artifact()
    return TensorInputs(**{**fields, **changes})


def converted_fund_returns(index: pd.Index) -> pd.Series:
    """Seeded daily returns for FIENX on `index`: numbers to its last day, nothing after."""
    values = np.random.default_rng(20241030).normal(0.0003, 0.011, len(index))
    values[index > pd.Timestamp(CONVERTED_LAST_DAY)] = np.nan
    return pd.Series(values, index=index, name=CONVERTED)


def converted_menu_inputs(lookback: str = "5y", **changes) -> TensorInputs:
    """A custom menu: the fixture's 23 funds plus FIENX, which the catalog does not serve."""
    base = fixture_inputs(lookback)
    fields = {
        "funds": [*base.funds, FundInput(id=CONVERTED, **CONVERTED_FACTS)],
        "returns": base.returns.assign(**{CONVERTED: converted_fund_returns(base.returns.index)}),
        "universe_name": "Custom menu",
        "preset_id": None,
    }
    return dataclasses.replace(base, **{**fields, **changes})


def write_converted_menu_parquet(path: Path) -> Path:
    """The returns parquet of that custom menu, catalog facts in its metadata, for the CLI."""
    frame = pd.read_parquet(FIXTURE)
    frame[CONVERTED] = converted_fund_returns(frame.index)
    document = fixture_metadata()
    document["universe"] = {"name": "Custom menu", "preset_id": None}
    document["funds"][CONVERTED] = CONVERTED_FACTS
    table = pa.Table.from_pandas(frame, preserve_index=True)
    metadata = dict(table.schema.metadata or {})
    metadata[METADATA_KEY] = json.dumps(document).encode()
    pq.write_table(table.replace_schema_metadata(metadata), path)
    return path


class Menu:
    """A seeded random menu with its programs and frontier solved: three factors plus noise."""

    def __init__(self, n: int, seed: int, nx: int = 10):
        rng = np.random.default_rng(seed)
        load = rng.normal(0.0, 1.0, (n, 3)) * np.array([0.10, 0.05, 0.03]) + np.array([0.06, 0, 0])
        self.cov = load @ load.T + np.diag(rng.uniform(0.02, 0.10, n) ** 2)
        self.mu = rng.uniform(0.01, 0.10, n)
        self.lo = np.where(rng.random(n) < 0.5, rng.uniform(0.0, 0.3 / n, n), 0.0)
        self.hi = np.full(n, min(max(3.0 / n, 0.25), 1.0))
        self.n, self.nx = n, nx
        self.programs = MenuPrograms(self.mu, self.cov, self.lo, self.hi)
        self.basis: TorsionBasis = torsion_basis(self.cov)
        self.front: Frontier = frontier(self.programs, nx=nx)
        self.program = EnbProgram(self.mu, self.cov, self.lo, self.hi, self.basis)

    def sigma(self, w) -> float:
        return float(np.sqrt(w @ self.cov @ w))

    def enb(self, w) -> float:
        return enb(w, self.cov, self.basis)

    def feasible(self, w, tol: float = 1e-6) -> bool:
        inside = (w >= self.lo - tol).all() and (w <= self.hi + tol).all()
        return bool(inside and abs(w.sum() - 1.0) <= tol)
