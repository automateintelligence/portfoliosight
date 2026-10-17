"""The volatility model's memory budget (simulation engines spec 9): a 30-fund build.

The build runs in a fresh interpreter so that nothing this test process holds counts. Its peak
resident set (`ru_maxrss`) is read before the build, once the libraries a build uses are loaded
and the inputs are made, and again after it: the difference is what the build itself needed at
its peak, the simulated panel (2,000 x 252 x 30 float64, 121 MB) and the ranges' work buffer
(at most 64 MB) among it.
"""

from __future__ import annotations

import json
import subprocess
import sys

from tests.engine.helpers import ROOT

BUDGET_MB = 400
FUNDS = 30

PROBE = """
import dataclasses, json, resource, sys
sys.path.insert(0, sys.argv[1])
from arch import arch_model  # the fit's own import, made before the baseline like the others
from portfoliosight.engine.tensor import build_tensor
from tests.engine.helpers import load_script

inputs = load_script("bench_build").bench_inputs(int(sys.argv[2]))
inputs = dataclasses.replace(inputs, nx=6, ny=5, levels=3)  # the panel does not shrink
before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
tensor = build_tensor(inputs, workers=1)
after = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
print(json.dumps({
    "before_kb": before,
    "after_kb": after,
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
    used_mb = (probe["after_kb"] - probe["before_kb"]) / 1024.0
    panel_mb = 2000 * 252 * FUNDS * 8 / 2**20
    assert panel_mb <= used_mb < BUDGET_MB, f"the build's peak rose {used_mb:.0f} MB"
