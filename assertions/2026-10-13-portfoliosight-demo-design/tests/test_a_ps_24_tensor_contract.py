"""A-PS-24 - a tensor is deterministic, schema-valid, full-precision, carries a correct
frontier_curve and s_safe, builds in <= 90 s, and the UI fixture is its unedited output.

Claim: building the 23-fund fixture twice from the same inputs yields identical canonical JSON
after removing built_at and build_seconds; the output validates against
portfoliosight/engine/tensor.schema.json; floats round-trip exactly; frontier_curve equals the
actual (sigma, mu) of w_front(s) at 8 sub-steps per gap (377 points) within 1e-9 relative;
frontier.s_safe is the rightmost maximum of Low_front over that curve; the build takes <= 90 s;
and web/fixtures/guide2017_5y.json equals a fresh build from tests/fixtures/synthetic_23.parquet
with the recorded asof (minus the telemetry fields).

Pinned interface (the product must provide exactly this):
- scripts/build_tensor.py --returns tests/fixtures/synthetic_23.parquet --lookback 5y
  --asof <the "asof" recorded in web/fixtures/guide2017_5y.json> --out <json>; exit 0.
- scripts/make_fixtures.py --out <path>: writes the synthetic 23-fund returns parquet from its
  built-in seed, byte-for-byte equal to the committed tests/fixtures/synthetic_23.parquet.
- portfoliosight/engine/tensor.schema.json (a JSON Schema that requires grid.z).
- web/fixtures/guide2017_5y.json: the unedited output of that build, lookback id 5y.
"""

from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

try:  # the gate's outer interpreter may lack them; every test calls _deps() first
    import numpy as np
    import pandas as pd
except Exception:  # pragma: no cover
    np = pd = None

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))


def _project_python() -> Path | None:
    """The project's virtualenv interpreter: this checkout's, else the main checkout's (worktree)."""
    roots = [ROOT]
    dot_git = ROOT / ".git"
    if dot_git.is_file():  # linked worktree: "gitdir: <main>/.git/worktrees/<name>"
        roots.append(Path(dot_git.read_text().split(":", 1)[1].strip()).parents[2])
    for root in roots:
        candidate = root / ".venv" / "bin" / "python"
        if candidate.exists():
            return candidate
    return None


_VENV_PY = _project_python()
_OUTER = (
    os.environ.get("PS_GATE_INNER") != "1"
    and _VENV_PY is not None
    and Path(sys.prefix).resolve() != _VENV_PY.parents[1].resolve()
)


def _need(module: str):
    """Import a product (or dev-dependency) module, failing the test cleanly when it is absent."""
    try:
        return importlib.import_module(module)
    except Exception as exc:  # ImportError, or an import-time crash in the product
        pytest.fail(f"A-PS-24 red: cannot import {module}: {type(exc).__name__}: {exc}")


def _attr(module: str, name: str):
    mod = _need(module)
    if not hasattr(mod, name):
        pytest.fail(f"A-PS-24 red: {module} has no attribute {name!r} (pinned interface)")
    return getattr(mod, name)


def _deps():
    if np is None or pd is None:
        pytest.fail("A-PS-24 red: numpy and pandas are not importable in this interpreter")


BUILD_CLI = ROOT / "scripts" / "build_tensor.py"
FIXTURE = ROOT / "tests" / "fixtures" / "synthetic_23.parquet"
NX, NY = 48, 32
TOL = 1e-6
_CACHE: dict = {}


def _run_cli(script: Path, args: list, timeout: int = 300):
    if not script.exists():
        pytest.fail(f"A-PS-24 red: {script.relative_to(ROOT)} does not exist")
    env = {k: v for k, v in os.environ.items() if k != "PYTEST_DISABLE_PLUGIN_AUTOLOAD"}
    try:
        return subprocess.run(
            [sys.executable, str(script), *[str(a) for a in args]],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        pytest.fail(f"A-PS-24 red: {script.name} did not finish within {timeout} s")


def _build(returns: Path, lookback: str, asof: str, out: Path, caps: Path | None = None) -> dict:
    """Build one tensor through the pinned CLI and return the parsed JSON."""
    args = ["--returns", returns, "--lookback", lookback, "--asof", asof, "--out", out]
    if caps is not None:
        args += ["--caps", caps]
    proc = _run_cli(BUILD_CLI, args)
    if proc.returncode != 0 or not Path(out).exists():
        pytest.fail(
            f"A-PS-24 red: build_tensor.py exit {proc.returncode}, file={Path(out).exists()}: "
            f"{proc.stderr[-1500:]}"
        )
    try:
        return json.loads(Path(out).read_text())
    except ValueError as exc:
        pytest.fail(f"A-PS-24 red: {out} is not JSON: {exc}")


def _fixture_frame():
    _deps()
    _need("pyarrow")
    if not FIXTURE.exists():
        pytest.fail(f"A-PS-24 red: fixture {FIXTURE.relative_to(ROOT)} does not exist")
    frame = pd.read_parquet(FIXTURE)
    assert isinstance(frame.index, pd.DatetimeIndex), "fixture index must be a DatetimeIndex"
    return frame


def _fixture_tensor(tmp_path_factory) -> dict:
    """The fixture tensor: synthetic_23.parquet, lookback 5y, asof = the parquet's last date."""
    if "fixture" not in _CACHE:
        frame = _fixture_frame()
        asof = frame.index.max().date().isoformat()
        out = tmp_path_factory.mktemp("fixture") / "tensor.json"
        _CACHE["fixture"] = _build(FIXTURE, "5y", asof, out)
    return _CACHE["fixture"]


def _arrays(t: dict):
    """Numpy views of the tensor fields the recomputations need (shape-checked)."""
    try:
        n = len(t["universe"]["funds"])
        a = SimpleNamespace(
            n=n,
            cov=np.array(t["cov"], float),
            mu=np.array(t["mu_s"], float),
            lo=np.array(t["bounds"]["min"], float),
            hi=np.array(t["bounds"]["max"], float),
            x=np.array(t["frontier"]["x"], float),
            yf=np.array(t["frontier"]["y"], float),
            wf=np.array(t["frontier"]["w"], float),
            gy=np.array(t["grid"]["y"], float),
            gw=t["grid"]["w"],
            gz=t["grid"]["z"],
            k_div=list(t["grid"]["k_div"]),
            y_div=np.array(t["grid"]["y_div"], float),
            w_div=np.array(t["grid"]["w_div"], float),
            y_sug=np.array(t["grid"]["y_sug"], float),
            tor=np.array(t["torsion"], float),
            tor_inv_t=np.array(t["torsion_inv_t"], float),
            lam=np.array(t["torsion_lambda"], float),
        )
    except (KeyError, TypeError, ValueError) as exc:
        pytest.fail(f"A-PS-24 red: tensor lacks a spec 7 field or has a ragged array: {exc!r}")
    assert n >= 2
    assert a.cov.shape == (n, n) and a.mu.shape == (n,)
    assert a.lo.shape == (n,) and a.hi.shape == (n,)
    assert a.x.shape == (NX,) and a.yf.shape == (NX,) and a.wf.shape == (NX, n)
    assert a.gy.shape == (NY,) and len(a.gw) == NX and len(a.gz) == NX
    assert all(len(col) == NY for col in a.gw) and all(len(col) == NY for col in a.gz)
    assert len(a.k_div) == NX and a.y_div.shape == (NX,) and a.w_div.shape == (NX, n)
    assert a.y_sug.shape == (NX,)
    assert a.tor.shape == (n, n) and a.tor_inv_t.shape == (n, n) and a.lam.shape == (n,)
    return a


def _sigma(w, cov) -> float:
    return float(np.sqrt(w @ cov @ w))


def _check_torsion_fields(a):
    """The shipped torsion triple must be a real diagonalizing torsion of the shipped cov."""
    m = a.tor @ a.cov @ a.tor.T
    off = np.abs(m - np.diag(np.diag(m))).max()
    assert off <= 1e-8 * np.trace(m), f"torsion does not diagonalize cov: max offdiag {off}"
    assert np.allclose(np.diag(m), a.lam, rtol=1e-9, atol=0), "torsion_lambda != diag(T cov T')"
    assert np.all(a.lam > 0)
    assert np.abs(a.tor_inv_t @ a.tor.T - np.eye(a.n)).max() <= 1e-8, "torsion_inv_t != inv(T')"


def _enb(w, a) -> float:
    """Independent ENB (spec 4.6) from the tensor's own cov / torsion_inv_t / torsion_lambda."""
    b = a.tor_inv_t @ w
    p = a.lam * b**2 / (w @ a.cov @ w)
    assert abs(p.sum() - 1) <= 1e-8, f"sum(p) = {p.sum()!r}"
    assert not (p < 0).any()
    nz = p[p > 0]
    return float(np.exp(-(nz * np.log(nz)).sum()))


def _greedy(mu, lo, hi, ascending: bool = False):
    """Spec 4.4 endpoint fill: every minimum first, then the remainder in mu order to each max."""
    w = np.array(lo, float)
    rest = 1.0 - w.sum()
    for i in np.argsort(mu if ascending else -np.asarray(mu), kind="stable"):
        add = min(hi[i] - w[i], rest)
        w[i] += add
        rest -= add
    return w


def _default_max(n: int) -> float:
    return min(max(3.0 / n, 0.25), 1.0)


def _random_menu(directory: Path, n: int, seed: int):
    """A seeded SPD menu: simulated daily returns in the pinned parquet format plus random caps.

    Returns (returns_path, caps_path, asof, lo, hi, requested) with lo/hi the expected resolved
    bounds (null entries resolve by the default rule) and requested the per-fund min/max as sent.
    """
    _deps()
    _need("pyarrow")
    rng = np.random.default_rng(seed)
    load = rng.normal(0.0, 1.0, (n, 3)) * np.array([0.10, 0.05, 0.03]) + np.array([0.06, 0.0, 0.0])
    idio = rng.uniform(0.02, 0.10, n)
    cov = load @ load.T + np.diag(idio**2)
    assert np.linalg.eigvalsh(cov).min() > 0
    mean = rng.uniform(0.01, 0.10, n)
    rows = 1400
    draws = rng.multivariate_normal(mean / 252.0, cov / 252.0, size=rows)
    ids = [f"M{i:02d}" for i in range(n)]
    index = pd.bdate_range(end="2026-06-30", periods=rows, name="date")
    path = directory / f"menu_{n}.parquet"
    pd.DataFrame(draws, index=index, columns=ids).to_parquet(path)
    lo, hi, requested, caps = np.zeros(n), np.full(n, _default_max(n)), [], []
    hi_low, hi_high = max(1.5 / n, 0.12), min(1.0, max(4.0 / n, 0.30))
    for i, fid in enumerate(ids):
        mn = float(rng.uniform(0.0, 0.3 / n)) if rng.random() < 0.5 else None
        mx = float(rng.uniform(hi_low, hi_high)) if rng.random() < 0.5 else None
        if mn is not None:
            lo[i] = mn
        if mx is not None:
            hi[i] = mx
        requested.append({"min": mn, "max": mx})
        caps.append({"id": fid, "min": mn, "max": mx})
    assert (lo <= hi).all() and lo.sum() <= 1.0 <= hi.sum()
    caps_path = directory / f"caps_{n}.json"
    caps_path.write_text(json.dumps(caps))
    return path, caps_path, "2026-06-30", lo, hi, requested


if _OUTER:

    def test_a_ps_24_in_project_venv():
        env = dict(os.environ, PS_GATE_INNER="1", PYTEST_DISABLE_PLUGIN_AUTOLOAD="1")
        proc = subprocess.run(
            [
                str(_VENV_PY),
                "-m",
                "pytest",
                "-q",
                "--noconftest",
                "-p",
                "no:cacheprovider",
                __file__,
            ],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
        )
        print(proc.stdout[-8000:], proc.stderr[-2000:])
        assert proc.returncode == 0, "A-PS-24 is red inside the project virtualenv (output above)"

else:
    import copy
    import math
    import re
    import time

    SCHEMA = ROOT / "portfoliosight" / "engine" / "tensor.schema.json"
    UI_FIXTURE = ROOT / "web" / "fixtures" / "guide2017_5y.json"
    MAKE_FIXTURES = ROOT / "scripts" / "make_fixtures.py"
    TELEMETRY = ("built_at", "build_seconds")

    def _ui_fixture() -> dict:
        if not UI_FIXTURE.exists():
            pytest.fail(f"A-PS-24 red: {UI_FIXTURE.relative_to(ROOT)} does not exist")
        try:
            doc = json.loads(UI_FIXTURE.read_text())
        except ValueError as exc:
            pytest.fail(f"A-PS-24 red: the UI fixture is not JSON: {exc}")
        assert isinstance(doc.get("asof"), str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", doc["asof"])
        return doc

    def _canonical(doc: dict) -> str:
        kept = {k: v for k, v in doc.items() if k not in TELEMETRY}
        return json.dumps(kept, sort_keys=True, separators=(",", ":"))

    def _builds(tmp_path_factory):
        """Two fresh CLI builds with the UI fixture's recorded asof: (docs, raw texts, seconds)."""
        if "builds" not in _CACHE:
            _deps()
            asof = _ui_fixture()["asof"]
            _fixture_frame()
            directory = tmp_path_factory.mktemp("builds")
            docs, texts, seconds = [], [], []
            for i in range(2):
                out = directory / f"build_{i}.json"
                started = time.monotonic()
                docs.append(_build(FIXTURE, "5y", asof, out))
                seconds.append(time.monotonic() - started)
                texts.append(out.read_text())
            _CACHE["builds"] = (docs, texts, seconds)
        return _CACHE["builds"]

    def _floats(node, out):
        if isinstance(node, float):
            out.append(node)
        elif isinstance(node, list):
            for item in node:
                _floats(item, out)
        elif isinstance(node, dict):
            for item in node.values():
                _floats(item, out)
        return out

    def test_1_two_builds_are_identical_without_telemetry(tmp_path_factory):
        docs, _, _ = _builds(tmp_path_factory)
        for key in TELEMETRY:
            assert key in docs[0] and key in docs[1], f"telemetry field {key} missing"
        first, second = _canonical(docs[0]), _canonical(docs[1])
        assert len(first) > 100_000, "the canonical dump is implausibly small for a 23-fund tensor"
        assert not first != second, "a second build from the same inputs differs"
        assert first.encode() == second.encode()
        assert len(docs[0]["universe"]["funds"]) == 23

    def test_2_schema_accepts_the_build_and_rejects_a_missing_grid_z(tmp_path_factory):
        jsonschema = _need("jsonschema")
        docs, _, _ = _builds(tmp_path_factory)
        if not SCHEMA.exists():
            pytest.fail(f"A-PS-24 red: {SCHEMA.relative_to(ROOT)} does not exist")
        schema = json.loads(SCHEMA.read_text())
        try:
            jsonschema.validate(docs[0], schema)
        except jsonschema.ValidationError as exc:
            pytest.fail(f"the built tensor does not validate against its schema: {exc.message}")
        broken = copy.deepcopy(docs[0])
        del broken["grid"]["z"]
        try:
            jsonschema.validate(broken, schema)
        except jsonschema.ValidationError:
            return
        pytest.fail("the schema accepted a tensor without grid.z: it is permissive")

    def test_3_floats_are_written_at_full_precision(tmp_path_factory):
        docs, texts, _ = _builds(tmp_path_factory)
        doc, text = docs[0], texts[0]
        fr = doc["frontier"]
        pool = _floats(
            [doc["mu_s"], doc["cov"], fr["x"], fr["y"], doc["frontier_curve"], doc["grid"]["y"]], []
        )
        assert len(pool) > 1000
        rng = np.random.default_rng(2401)
        sample = [pool[i] for i in rng.choice(len(pool), size=50, replace=False)]
        long_form = 0
        for x in sample:
            assert json.loads(json.dumps(x)) == x
            assert repr(x) in text, f"the file does not hold {x!r} at repr precision"
            digits = repr(x).replace("-", "").replace(".", "").split("e")[0].lstrip("0")
            long_form += len(digits) >= 15
        assert long_form >= 35, (
            f"only {long_form}/50 sampled floats carry 15+ digits: rounded output"
        )
        match = re.search(r'"mu_s"\s*:\s*\[\s*([^,\]\s]+)', text)
        assert match, "mu_s not found in the raw file text"
        assert match.group(1) == repr(doc["mu_s"][0]), "mu_s[0] is not printed as repr()"
        rounded = [v for v in doc["mu_s"] if v == round(v, 8)]
        assert not rounded, f"mu_s holds values rounded to 8 places: {rounded[:3]}"

    def _curve(doc):
        a = _arrays(doc)
        sig, mu = [], []
        for i in range((NX - 1) * 8 + 1):
            j = min(i // 8, NX - 2)
            lam = i / 8.0 - j
            w = (1.0 - lam) * a.wf[j] + lam * a.wf[j + 1]
            sig.append(_sigma(w, a.cov))
            mu.append(float(a.mu @ w))
        return np.array(sig), np.array(mu)

    def test_4_frontier_curve_is_the_recomputed_locus(tmp_path_factory):
        docs, _, _ = _builds(tmp_path_factory)
        doc = docs[0]
        got_sigma = np.array(doc["frontier_curve"]["sigma"], float)
        got_mu = np.array(doc["frontier_curve"]["mu"], float)
        assert got_sigma.shape == (377,) and got_mu.shape == (377,)
        sig, mu = _curve(doc)
        assert len(sig) == 377
        assert not (np.abs(got_sigma - sig) > 1e-9 * np.abs(sig)).any(), (
            "frontier_curve.sigma is off"
        )
        assert not (np.abs(got_mu - mu) > 1e-9 * np.abs(mu)).any(), "frontier_curve.mu is off"
        x = np.array(doc["frontier"]["x"], float)
        assert np.abs(got_sigma[::8][:-1] - x[:-1]).max() <= 1e-6  # nodes sit on their ceilings
        between = got_sigma[4::8] - 0.5 * (x[:-1] + x[1:])
        assert (between <= 1e-9).all() and between.min() < -1e-9  # a real curve, not the chord

    def test_5_s_safe_is_the_rightmost_maximum_of_low_front(tmp_path_factory):
        docs, _, _ = _builds(tmp_path_factory)
        doc = docs[0]
        sig, mu = _curve(doc)
        low = mu / 2.0 - 1.96 * sig / math.sqrt(2.0)
        top = low.max()
        rightmost = int(np.flatnonzero(low == top)[-1])
        near = np.flatnonzero(low >= top - 1e-12)  # ties within rounding: any of them is honest
        s_safe = doc["frontier"]["s_safe"]
        assert isinstance(s_safe, (int, float)) and 0 <= s_safe <= NX - 1
        assert abs(s_safe * 8 - round(s_safe * 8)) <= 1e-9, "s_safe is not on the 1/8 sampling grid"
        index = int(round(s_safe * 8))
        assert index in near, f"s_safe = {s_safe} is not at the maximum of Low_front"
        assert index == int(near[-1]), (
            f"s_safe = {s_safe} is not the rightmost maximum ({near[-1] / 8})"
        )
        if len(near) == 1:
            assert s_safe == rightmost / 8.0
        if index > 0:
            assert s_safe != float(index)  # s units (index / 8), not a raw sample index
        low_shipped = np.array(doc["frontier_curve"]["mu"]) / 2.0 - 1.96 * np.array(
            doc["frontier_curve"]["sigma"]
        ) / math.sqrt(2.0)
        assert not (low_shipped[index + 1 :] >= low_shipped[index] + 1e-12).any()

    def test_6_the_build_takes_at_most_90_seconds(tmp_path_factory):
        _, _, seconds = _builds(tmp_path_factory)
        assert max(seconds) <= 90.0, f"builds took {seconds} s; the fixture must build in <= 90 s"
        assert not min(seconds) < 0.5, "a tensor build cannot be instant: nothing was solved"

    def test_7_fixtures_are_reproducible_and_the_ui_fixture_is_a_fresh_build(
        tmp_path_factory, tmp_path
    ):
        ui = _ui_fixture()
        _fixture_frame()
        out = tmp_path / "regenerated.parquet"
        proc = _run_cli(MAKE_FIXTURES, ["--out", out], timeout=120)
        assert proc.returncode == 0 and out.exists(), (
            f"make_fixtures.py failed: {proc.stderr[-800:]}"
        )
        assert out.read_bytes() == FIXTURE.read_bytes(), (
            "make_fixtures.py does not reproduce the fixture"
        )
        assert FIXTURE.stat().st_size > 50_000
        docs, _, _ = _builds(tmp_path_factory)
        assert ui["lookback"]["id"] == "5y" and len(ui["universe"]["funds"]) == 23
        assert set(ui) == set(docs[0]), f"top-level keys differ: {sorted(set(ui) ^ set(docs[0]))}"
        assert not _canonical(ui) != _canonical(docs[0]), (
            "the UI fixture is not the fresh build's output"
        )
