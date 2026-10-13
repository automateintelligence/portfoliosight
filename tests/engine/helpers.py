"""Shared helpers for the engine tests: paths and loading repo scripts as modules."""

from __future__ import annotations

import dataclasses
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from portfoliosight.engine.tensor import FundInput, TensorInputs

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


def fixture_inputs(lookback: str = "5y", **changes) -> TensorInputs:
    """`TensorInputs` for the synthetic fixture, as the build CLI derives them from the parquet."""
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
    }
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
