"""Whole-build determinism and memory for simulation engines spec 4.1, 9 and 10.5."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import resource
import subprocess
import sys
import tracemalloc
from collections.abc import Callable
from pathlib import Path

import arch
import numpy as np
import pytest

import qse.distributions.joint as joint
from portfoliosight.engine import builder, parallel
from portfoliosight.engine.ranges import GarchRangeModel, RangeModel, bootstrap_index, path_counts
from portfoliosight.engine.shape import artifact_to_json, pool_bytes
from portfoliosight.engine.tensor import BuildResult, build_tensor_full, canonical_json
from tests.engine.helpers import ROOT, fixture_inputs, load_script

TELEMETRY = ("built_at", "build_seconds")
BUILD_BUDGET_MIB = 400  # Existing whole-build regression allowance, including non-panel objects.
CONTAINER_BUDGET_MIB = 1536  # Spec 12's deployment envelope; this test is a local measurement.


def _canonical_result(result: BuildResult) -> tuple[str, str, str, str]:
    model = result.models["garch"]
    assert isinstance(model, GarchRangeModel)
    assert model.panel.shape == (2000, 252, 23)
    assert np.shape(result.tensor["ladder"]["w"]) == (48, 14, 23)
    assert isinstance(result.models["replay"], RangeModel)
    assert result.models["replay"].counts.shape[0] == 2000
    assert set(result.models) == {"replay", "garch"}
    for engine in ("replay", "garch"):
        method = result.tensor["engines"][engine]["method"]
        assert (method["paths"], method["horizon_days"], method["seed"]) == (2000, 252, 20261013)
    return (
        canonical_json({k: v for k, v in result.tensor.items() if k not in TELEMETRY}),
        canonical_json(artifact_to_json(result.artifacts["garch"])),
        hashlib.sha256(pool_bytes(result.artifacts["garch"])).hexdigest(),
        hashlib.sha256(memoryview(model.panel)).hexdigest(),
    )


@pytest.fixture(scope="module")
def fresh_serial_result():
    # No supplied artifact: the reference and each worker count fit the history independently.
    result = build_tensor_full(fixture_inputs("5y", garch_artifact=None), workers=1)
    expected = _canonical_result(result)
    del result  # Do not retain a second 23-fund panel during the comparisons.
    yield expected
    parallel.shutdown()


@pytest.mark.parametrize("workers", [1, 2, 3, 4, 8])
def test_fresh_fit_full_build_is_identical_across_workers(
    workers: int, fresh_serial_result, record_property: Callable[[str, object], None]
):
    inputs = fixture_inputs("5y", garch_artifact=None)
    assert (inputs.nx, inputs.ny, inputs.levels) == (48, 32, 12)  # 12 interior levels + endpoints
    assert inputs.garch_artifact is None
    result = build_tensor_full(inputs, workers=workers)
    actual = _canonical_result(result)
    assert actual == fresh_serial_result
    assert result.tensor["range_default"] == "replay"
    for key in ("frontier", "ladder", "entered"):
        for figure in ("bad", "typical", "good"):
            assert (
                result.tensor[key]["range"][figure]
                == result.tensor[key]["ranges"]["replay"][figure]
            )
    record_property(
        "task25_determinism",
        json.dumps(
            {
                "workers": workers,
                "supplied_fit": False,
                "canonical_sha256": hashlib.sha256(actual[0].encode()).hexdigest(),
                "pool_sha256": actual[2],
                "panel_sha256": actual[3],
                "build_seconds": result.tensor["build_seconds"],
            }
        ),
    )


def _resident_kib() -> dict[str, int]:
    # Unlike ru_maxrss, /proc's memory-map high-water mark does not retain the parent's peak
    # across exec. Record both the live baseline and the child's own high-water mark.
    return {
        key.rstrip(":"): int(value)
        for line in Path("/proc/self/status").read_text().splitlines()
        if line.startswith(("VmRSS:", "VmHWM:"))
        for key, value, _unit in [line.split()]
    }


def _memory_probe() -> None:
    """Fresh interpreter, cold fit/draw caches; one worker keeps the whole build in this PID."""
    inputs = load_script("bench_build").bench_inputs(30)
    inputs = dataclasses.replace(
        inputs,
        engines=("replay", "garch"),
        allocation={fund.id: 1.0 for fund in inputs.funds},
    )
    cache_before = {
        "bootstrap_index": bootstrap_index.cache_info().currsize,
        "path_counts": path_counts.cache_info().currsize,
        "supplied_fit": inputs.garch_artifact is not None,
    }
    # Libraries and input construction precede the baseline; fitting, optimization, simulation,
    # ranges, stress and schema validation are all inside the measured build call.
    before = _resident_kib()
    before_rusage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    tracemalloc.start()
    result = build_tensor_full(inputs, workers=1)
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    after = _resident_kib()
    after_rusage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    garch = result.models["garch"]
    assert isinstance(garch, GarchRangeModel)
    tensor = result.tensor
    print(
        json.dumps(
            {
                "executable": sys.executable,
                "builder_origin": builder.__file__,
                "qse_origin": joint.__file__,
                "arch_origin": arch.__file__,
                "arch_version": arch.__version__,
                "numpy_version": np.__version__,
                "workers": 1,
                "cache_before": cache_before,
                "before_rss_kib": before["VmRSS"],
                "after_rss_kib": after["VmHWM"],
                "before_proc_status_kib": before,
                "after_proc_status_kib": after,
                "before_ru_maxrss_kib": before_rusage,
                "after_ru_maxrss_kib": after_rusage,
                "traced_current_bytes": current,
                "traced_peak_bytes": peak,
                "panel_bytes": garch.panel.nbytes,
                "panel_shape": list(garch.panel.shape),
                "grid_shape": list(np.shape(tensor["grid"]["z"])),
                "ladder_shape": list(np.shape(tensor["ladder"]["w"])),
                "mixes": sum(len(column) for column in tensor["ladder"]["w"])
                + int(tensor["entered"] is not None),
                "lookback_rows": tensor["lookback"]["rows"],
                "pool_rows": tensor["shape"]["pool_rows"],
                "sample_sha256": tensor["lookback"]["sample_sha256"],
                "shape_sha256": tensor["shape"]["sample_sha256"],
                "engines": tensor["engines"],
                "build_seconds": tensor["build_seconds"],
            }
        )
    )


def test_full_thirty_fund_dual_engine_build_memory(record_property: Callable[[str, object], None]):
    done = subprocess.run(
        [
            sys.executable,
            "-c",
            "from tests.engine.test_builder_resources import _memory_probe; _memory_probe()",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=900,
    )
    assert done.returncode == 0, done.stderr[-4000:]
    probe = json.loads(done.stdout.strip().splitlines()[-1])
    record_property("task25_memory", json.dumps(probe))
    assert probe["workers"] == 1
    assert probe["cache_before"] == {
        "bootstrap_index": 0,
        "path_counts": 0,
        "supplied_fit": False,
    }
    assert probe["grid_shape"] == [48, 32]
    assert probe["ladder_shape"] == [48, 14, 30]
    assert probe["mixes"] == 673
    assert probe["panel_shape"] == [2000, 252, 30]
    assert probe["panel_bytes"] == 2000 * 252 * 30 * 8
    assert probe["pool_rows"] == 2520
    for engine in ("replay", "garch"):
        assert probe["engines"][engine]["status"] == "ready"
        method = probe["engines"][engine]["method"]
        assert (method["paths"], method["horizon_days"], method["seed"]) == (2000, 252, 20261013)
    traced_mib = probe["traced_peak_bytes"] / 2**20
    resident_rise_mib = (probe["after_rss_kib"] - probe["before_rss_kib"]) / 1024
    assert probe["panel_bytes"] / 2**20 <= traced_mib < BUILD_BUDGET_MIB
    assert resident_rise_mib < BUILD_BUDGET_MIB
    assert probe["after_rss_kib"] / 1024 < CONTAINER_BUDGET_MIB
