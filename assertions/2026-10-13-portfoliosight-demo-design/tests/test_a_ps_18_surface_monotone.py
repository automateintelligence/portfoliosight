"""A-PS-18 - every ladder holds its risk, gives up return and gains ENB, and ends at its peak.

Claim: every column's ladder (at least 8 interior levels) starts at the frontier mix, keeps every
level on the column's risk line (|sigma - X_j| <= 1e-6), never rises in return (+1e-8) and never
falls in exact ENB from one level to the next, ends at the peak (the highest ENB on the ladder,
at least the frontier mix's), stores each level's own return and ENB, is collapsed exactly when
the peak gains no more than 1e-6 ENB (then every level is the frontier mix), keeps every level at
or above its evenly spaced return floor, and flags a hop exactly where the midpoint blend of two
levels loses more than 1% of the risk; enb_ref is the best ENB of all ladders; the heatmap raster
is uniform from the lowest peak return to max(y_front), holds the peak in every row at or below
the peak's return and the ladder's mix (earning at least Y_k) above it up to y_front, is null
exactly where Y_k > y_front[j], and its k_div, y_div and w_div name the peak's highest row, its
floor and the peak.

Pinned interface (the product must provide exactly this): scripts/build_tensor.py (shared CLI
pin, including --caps) and tests/fixtures/synthetic_23.parquet. Everything else is the test's own
numpy recomputation from the tensor's cov, mu_s, bounds, torsion_inv_t, torsion_lambda, frontier
grid and ladder fields. Three menus: the fixture and two simulated SPD menus (N = 5 and N = 12).
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
        pytest.fail(f"A-PS-18 red: cannot import {module}: {type(exc).__name__}: {exc}")


def _attr(module: str, name: str):
    mod = _need(module)
    if not hasattr(mod, name):
        pytest.fail(f"A-PS-18 red: {module} has no attribute {name!r} (pinned interface)")
    return getattr(mod, name)


def _deps():
    if np is None or pd is None:
        pytest.fail("A-PS-18 red: numpy and pandas are not importable in this interpreter")


BUILD_CLI = ROOT / "scripts" / "build_tensor.py"
FIXTURE = ROOT / "tests" / "fixtures" / "synthetic_23.parquet"
NX, NY = 48, 32
TOL = 1e-6
_CACHE: dict = {}


def _run_cli(script: Path, args: list, timeout: int = 300):
    if not script.exists():
        pytest.fail(f"A-PS-18 red: {script.relative_to(ROOT)} does not exist")
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
        pytest.fail(f"A-PS-18 red: {script.name} did not finish within {timeout} s")


def _build(returns: Path, lookback: str, asof: str, out: Path, caps: Path | None = None) -> dict:
    """Build one tensor through the pinned CLI and return the parsed JSON."""
    args = ["--returns", returns, "--lookback", lookback, "--asof", asof, "--out", out]
    if caps is not None:
        args += ["--caps", caps]
    proc = _run_cli(BUILD_CLI, args)
    if proc.returncode != 0 or not Path(out).exists():
        pytest.fail(
            f"A-PS-18 red: build_tensor.py exit {proc.returncode}, file={Path(out).exists()}: "
            f"{proc.stderr[-1500:]}"
        )
    try:
        return json.loads(Path(out).read_text())
    except ValueError as exc:
        pytest.fail(f"A-PS-18 red: {out} is not JSON: {exc}")


def _fixture_frame():
    _deps()
    _need("pyarrow")
    if not FIXTURE.exists():
        pytest.fail(f"A-PS-18 red: fixture {FIXTURE.relative_to(ROOT)} does not exist")
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
        pytest.fail(f"A-PS-18 red: tensor lacks a spec 7 field or has a ragged array: {exc!r}")
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

    def test_a_ps_18_in_project_venv():
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
        assert proc.returncode == 0, "A-PS-18 is red inside the project virtualenv (output above)"

else:

    def _check_surface(t: dict, label: str) -> int:
        a = _arrays(t)
        _check_torsion_fields(a)
        n = a.n
        ladder = t["ladder"]
        lw = np.array(ladder["w"], float)
        ly = np.array(ladder["y"], float)
        lz = np.array(ladder["z"], float)
        hop = np.array(ladder["hop"], bool)
        collapsed = np.array(ladder["collapsed"], bool)
        levels = lw.shape[1]
        assert lw.shape == (NX, levels, n) and ly.shape == lz.shape == (NX, levels), f"{label}: ladder shapes"
        assert hop.shape == (NX, levels - 1) and collapsed.shape == (NX,), f"{label}: hop / collapsed shapes"
        assert levels - 2 >= 8, f"{label}: {levels - 2} interior levels, at least 8 expected"

        enb_front = np.array([_enb(w, a) for w in a.wf])
        for j in range(NX):
            assert np.array_equal(lw[j, 0], a.wf[j]), f"{label}: ladder {j} does not start at the frontier mix"
            for level in range(levels):
                w = lw[j, level]
                where = f"{label}: level ({j},{level})"
                sig = _sigma(w, a.cov)
                assert abs(sig - a.x[j]) <= TOL, f"{where}: sigma {sig} off the risk line {a.x[j]}"
                assert abs(float(a.mu @ w) - ly[j, level]) <= 1e-12, f"{where}: y is not its mix's return"
                value = _enb(w, a)
                assert abs(lz[j, level] - value) <= 1e-9 * value, f"{where}: z is not its mix's ENB"
                assert 1 - TOL <= value <= n + TOL, f"{where}: ENB {value} outside [1, N]"
            # down the ladder the return never rises and the ENB never falls (spec 4.7)
            assert not (np.diff(ly[j]) > 1e-8).any(), f"{label}: return rises down ladder {j}"
            assert not (np.diff(lz[j]) < 0).any(), f"{label}: ENB falls down ladder {j}"
            assert lz[j, -1] == lz[j].max() >= enb_front[j] - 1e-9, f"{label}: the peak of column {j} is not its best mix"
            assert collapsed[j] == bool(lz[j, -1] <= lz[j, 0] + TOL), f"{label}: collapsed[{j}] disagrees with the ENB gain"
            if collapsed[j]:
                assert all(np.array_equal(w, a.wf[j]) for w in lw[j]), f"{label}: collapsed column {j} holds another mix"
            elif ly[j, 0] - ly[j, -1] > TOL:
                floors = np.linspace(ly[j, 0], ly[j, -1], levels)
                assert not (ly[j] < floors - 1e-8).any(), f"{label}: a level of column {j} earns less than its floor"
            for level in range(levels - 1):
                upper, lower = lw[j, level], lw[j, level + 1]
                middle = _sigma((upper + lower) / 2.0, a.cov)
                if hop[j, level]:
                    assert middle < 0.99 * a.x[j], f"{label}: hop ({j},{level}) on a blend that keeps the risk"
                else:
                    assert middle >= 0.99 * a.x[j] - 1e-12, f"{label}: blend ({j},{level}) leaves the risk line"
        enb_ref = float(t["enb_ref"])
        assert enb_ref == lz.max(), f"{label}: enb_ref {enb_ref} != the best ladder ENB {lz.max()}"

        # the raster: the ladders resampled on uniform floors from the lowest peak to the top
        assert abs(a.gy[0] - ly[:, -1].min()) <= 1e-12, f"{label}: Y_min is not the lowest peak return"
        assert a.gy[-1] == a.yf.max(), f"{label}: Y_max != max(y_front)"
        assert np.abs(a.gy - np.linspace(a.gy[0], a.gy[-1], NY)).max() <= 1e-9, f"{label}: Y not uniform"
        feasible = nulls = 0
        for j in range(NX):
            bottom = int(np.flatnonzero(a.gy <= ly[j, -1])[-1])
            for k in range(NY):
                w, z = a.gw[j][k], a.gz[j][k]
                want_null = bool(a.gy[k] > a.yf[j])
                assert (w is None) == want_null, f"{label}: cell ({j},{k}) null={w is None}, expected {want_null}"
                assert (z is None) == want_null, f"{label}: grid.z null pattern differs at ({j},{k})"
                if want_null:
                    nulls += 1
                    continue
                w = np.asarray(w, float)
                value = _enb(w, a)
                assert abs(z - value) <= 1e-9 * value, f"{label}: Z({j},{k}) != ENB of its mix"
                assert 1 - TOL <= z <= n + TOL, f"{label}: Z({j},{k}) = {z} outside [1, N]"
                assert not _sigma(w, a.cov) > a.x[j] + TOL, f"{label}: cell ({j},{k}) above its ceiling"
                if k <= bottom:  # the floor does not bind: the most diversified mix is the peak
                    assert np.array_equal(w, lw[j, -1]), f"{label}: cell ({j},{k}) is not the peak"
                else:
                    assert float(a.mu @ w) >= a.gy[k] - 1e-9, f"{label}: cell ({j},{k}) earns less than Y_k"
                feasible += 1
            assert a.k_div[j] == (-1 if collapsed[j] else bottom), f"{label}: k_div[{j}] = {a.k_div[j]}"
            assert np.array_equal(a.w_div[j], lw[j, -1]), f"{label}: w_div[{j}] is not the peak"
            want_div = a.yf[j] if collapsed[j] else a.gy[bottom]
            assert a.y_div[j] == want_div, f"{label}: y_div[{j}] = {a.y_div[j]}, expected {want_div}"
        assert feasible + nulls == NX * NY == 1536
        assert feasible >= NX and nulls >= 1, f"{label}: {feasible} feasible / {nulls} null cells"
        return feasible

    def test_fixture_surface(tmp_path_factory):
        feasible = _check_surface(_fixture_tensor(tmp_path_factory), "fixture")
        assert feasible >= 2 * NX

    def test_two_random_menus(tmp_path):
        done = []
        for n, seed in ((5, 1805), (12, 1812)):
            returns, caps, asof, lo, hi, _ = _random_menu(tmp_path, n, seed)
            t = _build(returns, "5y", asof, tmp_path / f"tensor_{n}.json", caps)
            assert len(t["universe"]["funds"]) == n
            assert np.abs(np.array(t["bounds"]["max"]) - hi).max() <= 1e-12
            _check_surface(t, f"N={n}")
            done.append(n)
        assert done == [5, 12]
