# ruff: noqa: E501
"""A-SE-18 property: real objective paths, pooled ladder choices, risk flags and hops.

Pins ladder.Dr2Program with existing EnbProgram(mu,cov,lo,hi,basis) conventions
(without torsion argument), builder.LADDER_MEASURE, and the existing Pool/column
surface. Wrappers observe real solver answers; no solver output is mocked.
Reduced geometry does not reduce the 2,000 simulation paths.
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


def test_a_se_18_dr2_ladders(tmp_path):
    if not _runtime():
        return
    from unittest.mock import patch

    import numpy as np
    import pandas as pd

    ladder = _module("portfoliosight.engine.ladder")
    builder = _module("portfoliosight.engine.builder")
    assert hasattr(ladder, "Dr2Program"), "Phase 2 SOCP Dr2Program is missing"
    assert hasattr(builder, "LADDER_MEASURE"), "Builder must select the actual ladder objective"
    rng = np.random.default_rng(20261018)

    def dr2(w, cov):
        return float((w @ np.sqrt(np.diag(cov))) ** 2 / (w @ cov @ w))

    # Two funds: enumerate the one-dimensional feasible interval independently.
    cov = np.diag([0.04, 0.09])
    mu = np.array([0.04, 0.12])
    program = ladder.Dr2Program(mu, cov, np.zeros(2), np.array([0.8, 0.8]))
    xs = np.linspace(0.2, 0.8, 200001)
    mixes = np.column_stack([1 - xs, xs])
    risks = np.sqrt(np.einsum("ij,jk,ik->i", mixes, cov, mixes))
    for risk, floor in ((0.18, 0.07), (0.24, 0.08), (0.4, 0.05)):
        candidate = program.solve(risk, floor, np.array([0.5, 0.5]))
        feasible = (risks <= risk) & (mixes @ mu >= floor)
        assert feasible.any() and candidate is not None
        optimum = (mixes[feasible] @ np.sqrt(np.diag(cov))).max()
        assert abs(candidate.w @ np.sqrt(np.diag(cov)) - optimum) <= 1e-6
        assert np.sqrt(candidate.w @ cov @ candidate.w) <= risk + 1e-6
        assert candidate.w @ mu >= floor - 1e-6
    assert np.sqrt(candidate.w @ cov @ candidate.w) < 0.4 - 0.01

    presets = json.loads((ROOT / "data/presets.json").read_text())["presets"]
    assert {(x["id"], len(x["funds"])) for x in presets} == {("guide2017", 23), ("tsp", 5)}
    assert len(presets) == 2
    cases = [(preset["id"], preset["funds"]) for preset in presets] + [
        ("synthetic", ["VTI", "BND", "VNQ"])
    ]
    selected = {}
    observed = {"enb": 0, "dr2": 0}
    browser_tensors = []
    for name, ids in cases:
        days = pd.bdate_range(end="2026-10-13", periods=1600)
        values = rng.normal(
            0, np.linspace(0.002, 0.02, len(ids)), (len(days), len(ids))
        ) + np.linspace(0.00003, 0.0008, len(ids))
        frame = pd.DataFrame(values, index=days, columns=ids)
        funds = [
            builder.FundInput(i, i, "etf", "tiingo", "2026-10-13", "2026-10-13T00:00:00Z")
            for i in ids
        ]
        args = builder.TensorInputs(
            funds=funds,
            returns=frame,
            lookback="5y",
            asof="2026-10-13",
            universe_name=name,
            nx=5,
            ny=5,
            levels=3,
        )
        for measure, cls in (("enb", ladder.EnbProgram), ("dr2", ladder.Dr2Program)):
            candidates = []
            solve = cls.solve

            def traced(
                self, risk, floor, start, _real=solve, _measure=measure, _candidates=candidates
            ):
                answer = _real(self, risk, floor, start)
                observed[_measure] += 1
                if answer is not None:
                    _candidates.append((risk, np.asarray(answer.w).copy()))
                return answer

            with (
                patch.object(builder, "LADDER_MEASURE", measure),
                patch.object(cls, "solve", traced),
            ):
                tensor = builder.build_tensor(args, workers=1)
            assert observed[measure] > 0, (
                f"{measure} label did not dispatch its real optimization path"
            )
            assert tensor["ladder"]["measure"] == measure
            selected[name, measure] = tensor
            cov = np.array(tensor["cov"])
            mu = np.array(tensor["mu_s"])
            lo = np.array(tensor["bounds"]["min"])
            hi = np.array(tensor["bounds"]["max"])
            inv = np.array(tensor["torsion_inv_t"])
            lam = np.array(tensor["torsion_lambda"])

            def enb(w, lam=lam, inv=inv, cov=cov):
                q = lam * (inv @ w) ** 2 / (w @ cov @ w)
                q = q[q > 0]
                return float(np.exp(-np.sum(q * np.log(q))))

            for j, column in enumerate(tensor["ladder"]["w"]):
                weights = np.array(column)
                risk = tensor["frontier"]["x"][j]
                ys = weights @ mu
                ds = np.array([dr2(w, cov) for w in weights])
                es = np.array([enb(w) for w in weights])
                zs = ds if measure == "dr2" else es
                assert np.allclose(weights.sum(axis=1), 1, atol=1e-6, rtol=0)
                assert np.all(weights >= lo - 1e-6) and np.all(weights <= hi + 1e-6)
                sigmas = np.sqrt(np.einsum("ij,jk,ik->i", weights, cov, weights))
                assert np.all(sigmas <= risk + 1e-6)
                assert np.all(ys >= np.linspace(ys[0], ys[-1], len(ys)) - 1e-6)
                assert np.all(np.diff(zs) >= -1e-6) and np.all(np.diff(ys) <= 1e-6)
                assert np.allclose(tensor["ladder"]["dr2"][j], ds, atol=2e-9, rtol=0)
                assert np.allclose(tensor["ladder"]["enb"][j], es, atol=2e-9, rtol=0)
                assert np.allclose(tensor["ladder"]["z"][j], zs, atol=2e-9, rtol=0)
                flags = np.array(tensor["ladder"]["on_line"][j])
                assert np.array_equal(flags, np.abs(sigmas - risk) <= 1e-6)
                if tensor["ladder"]["collapsed"][j]:
                    assert np.max(np.abs(weights - weights[0])) < 1e-12
                for level, (left, right) in enumerate(zip(weights[:-1], weights[1:], strict=True)):
                    midpoint = (left + right) / 2
                    expected = bool(
                        np.max(np.abs(left - right)) > 1e-12
                        and np.sqrt(midpoint @ cov @ midpoint) < 0.99 * risk
                    )
                    assert tensor["ladder"]["hop"][j][level] == expected
                if measure == "dr2":
                    pool = [w for r, w in candidates if abs(r - risk) < 1e-10] + [weights[0]]
                    for level, floor in enumerate(np.linspace(ys[0], ys[-1], len(ys))):
                        # Floor zero remains the exact frontier by specification.
                        if level == 0:
                            continue
                        eligible = [dr2(w, cov) for w in pool if w @ mu >= floor - 1e-8]
                        assert eligible and zs[level] >= max(eligible) - 1e-6
            assert tensor["enb_ref"] == tensor["refs"]["enb"]
            for metric in ("dr2", "enb"):
                assert abs(tensor["refs"][metric] - np.max(tensor["ladder"][metric])) < 1e-9
                for j, col in enumerate(tensor["grid"]["w"]):
                    for k, w in enumerate(col):
                        value = tensor["grid"][metric][j][k]
                        if w is None:
                            assert value is None
                        else:
                            expected = (
                                dr2(np.array(w), cov) if metric == "dr2" else enb(np.array(w))
                            )
                            assert abs(value - expected) < 2e-9
            assert tensor["grid"]["z"] == tensor["grid"][measure]
            browser_tensors.append(tensor)
    assert any(
        np.max(
            np.abs(
                np.array(selected[name, "enb"]["ladder"]["w"])
                - np.array(selected[name, "dr2"]["ladder"]["w"])
            )
        )
        > 1e-5
        for name, _ in cases
    ), "Relabelling one common ladder is not two optimization methods"

    # Equal returns avoid solving new floors: a real Pool/column carries a mandatory hop.
    cov = np.diag([0.04, 0.08, 0.08])
    mu = np.full(3, 0.1)
    program = ladder.Dr2Program(mu, cov, np.zeros(3), np.ones(3))
    top = program.candidate(np.array([1.0, 0, 0]))
    peak = program.candidate(np.array([0.0, 0.5, 0.5]))
    pool = ladder.Pool(top)
    pool.add(peak)
    col = ladder.column(program, 0.2, pool, levels=1)
    assert col.hop[0] and not col.collapsed
    collapsed = ladder.column(program, 0.2, ladder.Pool(top), levels=1)
    assert collapsed.collapsed and not np.any(collapsed.hop)
    # The browser gets the actual forced-hop column above, even if an ordinary
    # preset happens to have no hops; toggling every browser hop flag off must fail.
    forced = json.loads(json.dumps(selected["synthetic", "dr2"]))
    count = len(forced["frontier"]["w"])
    forced["cov"] = cov.tolist()
    forced["mu_s"] = mu.tolist()
    forced["sigma"] = np.sqrt(np.diag(cov)).tolist()
    forced["torsion_inv_t"] = np.eye(3).tolist()
    forced["torsion_lambda"] = np.diag(cov).tolist()
    forced["frontier"]["w"] = [top.w.tolist() for _ in range(count)]
    forced["frontier"]["x"] = [0.2] * count
    forced["ladder"]["w"] = [col.w.tolist() for _ in range(count)]
    forced["ladder"]["hop"] = [col.hop.tolist() for _ in range(count)]
    forced["ladder"]["collapsed"] = [False] * count
    browser_tensors.append(forced)
    source = r"""import {it,expect} from "vitest";
import {portfolioMath} from "@RUNROOT@/web/src/math/portfolio";
const ts=__TENSORS__;
it("actual coordinates and every flagged hop",()=>{
 for(const t of ts){const m=portfolioMath(t as any);
 for(let j=0;j<t.ladder.w.length;j++)for(let l=0;l<t.ladder.w[j].length-1;l++){
  const steps=t.ladder.w[j].length-1;
  for(const f of [.49,.51]){
   const a=t.ladder.w[j][l],b=t.ladder.w[j][l+1];
   const q=t.ladder.hop[j][l]?(f<.5?0:1):f;
   const expected=a.map((x:number,i:number)=>(1-q)*x+q*b[i]);
   const actual=m.interpolate(j,(l+f)/steps);
   actual.forEach((x:number,i:number)=>expect(x).toBeCloseTo(expected[i],10));
   const risk=Math.sqrt(expected.reduce((s:number,x:number,i:number)=>s+x*t.cov[i].reduce((v:number,c:number,k:number)=>v+c*expected[k],0),0));
   expect(m.stats(actual).sigma).toBeCloseTo(risk,10);
  }
 }}
});""".replace("__TENSORS__", json.dumps(browser_tensors))
    _vitest(tmp_path, source)
