# ruff: noqa: E501
"""A-SE-17 property: covariance DR², qualified bound, builder and browser fidelity.

Pins engine.measures.dr2(w,cov), parallel to engine.torsion.enb(w,cov,basis),
and portfolioMath(tensor).stats(w).dr2. Builder fields are normative spec §7.
Synthetic price fixtures use the actual preset fund menus across every lookback.
Tolerances: 1e-9 identity, 2e-9 formula roundoff, inherited 1e-6 holdings.
"""

from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))


def _runtime():
    """Use project dependencies while importing product exclusively from this run checkout."""
    try:
        importlib.import_module("numpy")
        importlib.import_module("pandas")
    except ImportError:
        main = Path(
            subprocess.check_output(
                ["git", "rev-parse", "--git-common-dir"], cwd=ROOT, text=True
            ).strip()
        )
        if not main.is_absolute():
            main = ROOT / main
        python = main.resolve().parent / ".venv/bin/python"
        assert python.exists(), (
            "Project runtime missing; this gate cannot pass without its dependencies"
        )
        assert not os.environ.get("A_SE_REEXEC"), (
            "Project runtime still lacks required dependencies"
        )
        result = subprocess.run(
            [
                str(python),
                "-m",
                "pytest",
                "-q",
                "--noconftest",
                "-p",
                "no:cacheprovider",
                str(Path(__file__).resolve()),
            ],
            cwd=ROOT,
            env={
                **os.environ,
                "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
                "PYTHONPATH": str(ROOT),
                "A_SE_REEXEC": "1",
            },
            capture_output=True,
            text=True,
            timeout=21600,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        return False
    package = importlib.import_module("portfoliosight")
    assert Path(package.__file__).resolve().is_relative_to(ROOT), (
        "Imported another editable checkout"
    )
    return True


def _module(name):
    try:
        module = importlib.import_module(name)
    except ImportError as exc:
        raise AssertionError(f"Required implementation {name} is unavailable: {exc}") from exc
    assert Path(module.__file__).resolve().is_relative_to(ROOT), (
        f"{name} came from another checkout"
    )
    return module


def _vitest(tmp_path, source):
    """Compile frozen embedded TS against runroot product; use installed tools only."""
    roots = [ROOT]
    if (ROOT / ".git").is_file():
        roots.append(Path((ROOT / ".git").read_text().split(":", 1)[1].strip()).parents[2])
    modules = next(
        (r / "web/node_modules" for r in roots if (r / "web/node_modules/.bin/vitest").exists()),
        None,
    )
    if modules is None:
        pytest.fail("Local vitest/jsdom prerequisite is missing; no install/network fallback")
    package = json.loads((ROOT / "web/package.json").read_text())
    aliases = {
        name: str(modules / name)
        for name in {**package.get("dependencies", {}), **package.get("devDependencies", {})}
        if (modules / name).exists()
    }
    # NODE/PS_GATE_NODE and PATH work on a normal clone; nvm is optional discovery only.
    import re
    import shutil

    configured = os.environ.get("PS_GATE_NODE") or os.environ.get("NODE")
    candidates = [Path(configured)] if configured else []
    located = shutil.which("node")
    if located:
        candidates.append(Path(located))
    candidates.extend((Path.home() / ".nvm/versions/node").glob("*/bin/node"))

    def supports(version, expression):
        for alternative in expression.split("||"):
            ok = True
            for token in alternative.split():
                match = re.fullmatch(r"(>=|<=|>|<|\^|~|=)?(\d+)(?:\.(\d+))?(?:\.(\d+))?", token)
                if not match:
                    ok = False
                    break
                op, major, minor, patch = match.groups()
                bound = (int(major), int(minor or 0), int(patch or 0))
                check = {
                    ">=": version >= bound,
                    "<=": version <= bound,
                    ">": version > bound,
                    "<": version < bound,
                    "^": bound <= version < (bound[0] + 1, 0, 0),
                    "~": bound <= version < (bound[0], bound[1] + 1, 0),
                    "=": version == bound,
                    None: version == bound,
                }[op]
                ok = ok and check
            if ok:
                return True
        return False

    compatible = []
    requirements = [
        json.loads((modules / pkg / "package.json").read_text())
        .get("engines", {})
        .get("node", ">=0.0.0")
        for pkg in ("vite", "vitest", "jsdom")
    ]
    for candidate in dict.fromkeys(candidates):
        try:
            result = subprocess.run(
                [str(candidate), "-p", "process.versions.node"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            version = tuple(int(n) for n in result.stdout.strip().split("."))
        except (OSError, ValueError, subprocess.TimeoutExpired):
            continue
        if result.returncode == 0 and all(
            supports(version, requirement) for requirement in requirements
        ):
            compatible.append((version, candidate))
    if not compatible:
        pytest.fail(
            "Compatible installed Node prerequisite missing; required: " + "; ".join(requirements)
        )
    node = max(compatible, key=lambda item: item[0])[1]
    source = source.replace("@RUNROOT@", str(ROOT))
    test = tmp_path / "assertion.test.tsx"
    test.write_text(source)
    config = tmp_path / "vitest.config.mjs"
    config.write_text(
        "export default "
        + json.dumps(
            {
                "root": str(ROOT / "web"),
                "resolve": {"alias": aliases},
                "esbuild": {"jsx": "automatic"},
                "test": {
                    "include": [str(test)],
                    "environment": "jsdom",
                    "testTimeout": 120000,
                    "hookTimeout": 10000,
                    "pool": "forks",
                    "maxWorkers": 1,
                    "minWorkers": 1,
                },
            }
        )
    )
    try:
        result = subprocess.run(
            [str(node), str(modules / "vitest/vitest.mjs"), "run", "--config", str(config)],
            cwd=ROOT / "web",
            capture_output=True,
            text=True,
            timeout=180,
            env={
                **os.environ,
                "CI": "1",
                "NO_COLOR": "1",
                "PATH": str(node.parent) + os.pathsep + os.environ.get("PATH", ""),
            },
        )
    except subprocess.TimeoutExpired:
        pytest.fail("Application runtime gate exceeded 180 seconds")
    assert result.returncode == 0, result.stdout[-14000:] + result.stderr[-6000:]


def test_a_se_17_dr2_identities(tmp_path):
    if not _runtime():
        return
    import numpy as np
    import pandas as pd

    measures = _module("portfoliosight.engine.measures")
    assert callable(getattr(measures, "dr2", None)), "Phase 2 requires dr2(weights, covariance)"
    builder = _module("portfoliosight.engine.builder")
    rng = np.random.default_rng(91017)
    browser_cases = []

    def oracle(w, cov):
        return float((w @ np.sqrt(np.diag(cov))) ** 2 / (w @ cov @ w))

    def check(w, cov):
        expected = oracle(w, cov)
        actual = float(measures.dr2(w, cov))
        assert np.isclose(actual, expected, rtol=2e-9, atol=1e-12)
        held = np.flatnonzero(w > 1e-6)
        # Generated weights have exact zeros or weights well above the reporting cutoff.
        corr = cov / np.sqrt(np.outer(np.diag(cov), np.diag(cov)))
        if np.all(corr[np.ix_(held, held)] >= 0):
            assert actual <= len(held) + 1e-9
        browser_cases.append({"w": w.tolist(), "cov": cov.tolist(), "expected": expected})
        return actual

    for n in (2, 3, 5, 11, 23):
        vols = np.linspace(0.03, 0.31, n)
        inverse = 1 / vols
        inverse /= inverse.sum()
        assert abs(check(inverse, np.diag(vols**2)) - n) <= 1e-9
        for _ in range(8):
            a = rng.uniform(0.01, 1, (n, n))
            cov = (a @ a.T + np.eye(n) * 0.1) * 0.01
            w = rng.uniform(0.05, 1, n)
            w[rng.random(n) < 0.25] = 0
            if not w.any():
                w[0] = 1
            w /= w.sum()
            check(w, cov)
            b = rng.normal(size=(n, n))
            check(w, (b @ b.T + np.eye(n) * 0.2) * 0.01)
            for single in np.eye(n):
                assert abs(check(single, cov) - 1) <= 1e-9
    pair = np.array([0.5, 0.5])
    assert abs(check(pair, np.array([[0.04, 0.038], [0.038, 0.04]])) - 2 / 1.95) < 1e-9
    assert check(pair, np.array([[0.04, -0.02], [-0.02, 0.04]])) > 2, (
        "Negative correlation must not be clipped to holdings"
    )

    dates = pd.bdate_range(end="2026-10-13", periods=6000)
    presets = json.loads((ROOT / "data/presets.json").read_text())["presets"]
    assert {(x["id"], len(x["funds"])) for x in presets} == {("guide2017", 23), ("tsp", 5)}
    assert len(presets) == 2
    tensors = []
    for preset in presets:
        ids = preset["funds"]
        common = rng.normal(0, 0.003, (len(dates), 1))
        values = (
            0.00015
            + common
            + rng.normal(0, np.linspace(0.001, 0.012, len(ids)), (len(dates), len(ids)))
        )
        returns = pd.DataFrame(values, index=dates, columns=ids)
        funds = [
            builder.FundInput(
                i,
                i,
                "tsp" if i.startswith("TSP-") else "etf",
                "tsp" if i.startswith("TSP-") else "tiingo",
                "2026-10-13",
                "2026-10-13T00:00:00Z",
            )
            for i in ids
        ]
        for lookback in ("1y", "2y", "3y", "5y", "10y", "ew"):
            tensor = builder.build_tensor(
                builder.TensorInputs(
                    funds=funds,
                    returns=returns,
                    lookback=lookback,
                    asof="2026-10-13",
                    universe_name=preset["name"],
                    preset_id=preset["id"],
                    nx=3,
                    ny=3,
                    levels=2,
                ),
                workers=1,
            )
            cov = np.array(tensor["cov"])
            for w in np.eye(len(ids)):
                assert abs(check(w, cov) - 1) < 1e-9
            assert "dr2" in tensor["ladder"] and "dr2" in tensor["grid"], (
                "Builder has not emitted covariance measures"
            )
            for j, column in enumerate(tensor["ladder"]["w"]):
                for level, weights in enumerate(column):
                    expected = check(np.array(weights), cov)
                    assert abs(tensor["ladder"]["dr2"][j][level] - expected) < 2e-9
            for j, column in enumerate(tensor["grid"]["w"]):
                for k, weights in enumerate(column):
                    actual = tensor["grid"]["dr2"][j][k]
                    if weights is None:
                        assert actual is None
                    else:
                        assert abs(actual - check(np.array(weights), cov)) < 2e-9
            tensors.append(tensor)
    assert len(tensors) == 12
    source = r"""import { expect, it } from "vitest";
import { portfolioMath } from "@RUNROOT@/web/src/math/portfolio";
const tensors = __TENSORS__;
const cases = __CASES__;
it("DR2 browser runtime matches independent covariance oracles", () => {
  for (const t of tensors) {
    const math = portfolioMath(t as any);
    for (let j=0; j<t.ladder.w.length; j++) for (let l=0; l<t.ladder.w[j].length; l++)
      expect(math.stats(t.ladder.w[j][l]).dr2).toBeCloseTo(t.ladder.dr2[j][l], 9);
  }
  for (const c of cases) {
    const t = structuredClone(tensors[0]);
    const n = c.w.length;
    t.cov = c.cov; t.sigma = c.cov.map((r:any,i:number)=>Math.sqrt(r[i]));
    t.mu_s = Array(n).fill(0);
    t.frontier.w = t.frontier.w.map(()=>c.w.slice());
    t.ladder.w = t.ladder.w.map((levels:any[])=>levels.map(()=>c.w.slice()));
    t.torsion_inv_t = c.cov.map((_:any,i:number)=>Array.from({length:n},(_,j)=>i===j?1:0));
    t.torsion_lambda = Array(n).fill(1);
    expect(portfolioMath(t as any).stats(c.w).dr2).toBeCloseTo(c.expected, 9);
  }
});""".replace("__TENSORS__", json.dumps(tensors)).replace("__CASES__", json.dumps(browser_cases))
    _vitest(tmp_path, source)
