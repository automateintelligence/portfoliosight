"""Shared helpers for the engine tests: paths and loading repo scripts as modules."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pyarrow.parquet as pq

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
