"""Shared helpers for the engine tests: paths and loading repo scripts as modules."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pandas as pd
import pyarrow.parquet as pq

from portfoliosight.engine.tensor import FundInput, TensorInputs

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
FIXTURE = ROOT / "tests" / "fixtures" / "synthetic_23.parquet"
UI_FIXTURE = ROOT / "web" / "fixtures" / "guide2017_5y.json"
HOLDINGS = ROOT / "data" / "holdings" / "holdings_guide2017_step2.csv"
FIXTURE_ASOF = "2026-10-12"
METADATA_KEY = b"portfoliosight"


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
