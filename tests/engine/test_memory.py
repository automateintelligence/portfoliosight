"""The volatility model's memory budget (simulation engines spec 9): a 30-fund build.

The build runs in a fresh interpreter so that nothing this test process holds counts. Two
measures of what the build itself needs at its peak, the simulated panel (2,000 x 252 x 30
float64, 121 MB) and the ranges' work buffer (at most 64 MB) among it:

- the peak of the memory allocated during the build, as `tracemalloc` counts it (NumPy reports
  every array buffer to it). It depends on the code alone, not on the machine, so it is checked
  from both sides: at least the panel, under the budget;
- the rise of the peak resident set (`ru_maxrss`) from before the build, once the libraries a
  build uses are loaded and the inputs are made, to after it. It also sees what `tracemalloc`
  does not (BLAS and the fit's own C buffers), but a machine short of memory keeps part of a
  process swapped out, so it is checked against the budget only.
"""

from __future__ import annotations

import json
import subprocess
import sys

from tests.engine.helpers import ROOT

BUDGET_MB = 400
FUNDS = 30

PROBE = """
import dataclasses, json, resource, sys, tracemalloc
sys.path.insert(0, sys.argv[1])
from arch import arch_model  # the fit's own import, made before the baseline like the others
from portfoliosight.engine.tensor import build_tensor
from tests.engine.helpers import load_script

inputs = load_script("bench_build").bench_inputs(int(sys.argv[2]))
inputs = dataclasses.replace(inputs, nx=6, ny=5, levels=3)  # the panel does not shrink
before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
tracemalloc.start()
tensor = build_tensor(inputs, workers=1)
_, traced = tracemalloc.get_traced_memory()
tracemalloc.stop()
after = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
print(json.dumps({
    "before_kb": before,
    "after_kb": after,
    "traced_peak_bytes": traced,
    "garch": tensor["engines"]["garch"]["status"],
    "funds": len(tensor["shape"]["funds"]),
    "pool_rows": tensor["shape"]["pool_rows"],
}))
"""


def test_a_thirty_fund_build_stays_inside_its_memory_budget():
    done = subprocess.run(
        [sys.executable, "-c", PROBE, str(ROOT), str(FUNDS)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=900,
    )
    assert done.returncode == 0, done.stderr[-2000:]
    probe = json.loads(done.stdout.strip().splitlines()[-1])
    assert probe["garch"] == "ready" and probe["funds"] == FUNDS and probe["pool_rows"] >= 2520
    panel_mb = 2000 * 252 * FUNDS * 8 / 2**20
    traced_mb = probe["traced_peak_bytes"] / 2**20
    assert panel_mb <= traced_mb < BUDGET_MB, f"the build allocated {traced_mb:.0f} MB at its peak"
    resident_mb = (probe["after_kb"] - probe["before_kb"]) / 1024.0
    assert resident_mb < BUDGET_MB, f"the build's peak resident set rose {resident_mb:.0f} MB"
