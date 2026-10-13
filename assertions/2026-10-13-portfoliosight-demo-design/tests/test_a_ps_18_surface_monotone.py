"""A-PS-18 - the surface proxy is monotone and the bottom end is at least as diversified as the top.

Claim: the optimized Herfindahl |w[j][k]|^2 is non-decreasing in ascending Y_k within each column
and non-increasing in ascending X_j within each row (+-1e-6); a cell is null exactly when
Y_k > y_front[j]; 1 <= Z <= N on every feasible cell; ENB(w_div[j]) >= ENB(w_front[j]) - 1e-9;
y_div[j] is the return floor of the highest-ENB candidate (ties -> highest return) and enb_ref is
the maximum over all candidates in all columns.

Pinned interface (the product must provide exactly this): scripts/build_tensor.py (shared CLI
pin, including --caps) and tests/fixtures/synthetic_23.parquet. Everything else is the test's own
numpy recomputation from the tensor's cov, mu_s, bounds, torsion_inv_t, torsion_lambda, frontier
and grid fields. Three menus: the fixture and two simulated SPD menus (N = 5 and N = 12).
Exact ENB is not asserted monotone (spec 4.7).
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
        # return floors: uniform from the lowest-mu greedy fill to max(y_front)
        y_min = float(a.mu @ _greedy(a.mu, a.lo, a.hi, ascending=True))
        assert abs(a.gy[0] - y_min) <= 1e-9, (
            f"{label}: Y_min {a.gy[0]} != lowest-return fill {y_min}"
        )
        assert a.gy[-1] == a.yf.max(), f"{label}: Y_max != max(y_front)"
        assert np.abs(a.gy - np.linspace(a.gy[0], a.gy[-1], NY)).max() <= 1e-9, (
            f"{label}: Y not uniform"
        )

        herf = np.full((NX, NY), np.nan)
        enb = np.full((NX, NY), np.nan)
        feasible = nulls = 0
        for j in range(NX):
            for k in range(NY):
                w, z = a.gw[j][k], a.gz[j][k]
                want_null = bool(a.gy[k] > a.yf[j])
                assert (w is None) == want_null, (
                    f"{label}: cell ({j},{k}) null={w is None} but Y_k > y_front[j] is {want_null}"
                )
                assert (z is None) == want_null, (
                    f"{label}: grid.z null pattern differs at ({j},{k})"
                )
                if want_null:
                    nulls += 1
                    continue
                w = np.asarray(w, float)
                assert w.shape == (n,)
                herf[j, k] = w @ w
                enb[j, k] = _enb(w, a)
                assert abs(z - enb[j, k]) <= 1e-9 * enb[j, k], (
                    f"{label}: Z({j},{k}) != ENB of its mix"
                )
                assert 1 - TOL <= z <= n + TOL, f"{label}: Z({j},{k}) = {z} outside [1, N]"
                feasible += 1
        assert feasible + nulls == NX * NY == 1536
        assert feasible >= NX and nulls >= 1, f"{label}: {feasible} feasible / {nulls} null cells"

        for j in range(NX):  # ascending Y within a column: the feasible set shrinks
            col = herf[j][~np.isnan(herf[j])]
            assert not (np.diff(col) < -TOL).any(), (
                f"{label}: Herfindahl falls with Y in column {j}"
            )
        for k in range(NY):  # ascending X within a row: the feasible set grows
            row = herf[:, k][~np.isnan(herf[:, k])]
            assert not (np.diff(row) > TOL).any(), f"{label}: Herfindahl rises with X in row {k}"

        enb_front = np.array([_enb(w, a) for w in a.wf])
        best_overall = -np.inf
        candidates = 0
        for j in range(NX):
            ks = [k for k in range(NY) if not np.isnan(enb[j, k])]
            cand = [(enb_front[j], NY, -1)] + [
                (enb[j, k], k, k) for k in ks
            ]  # (ENB, return rank, id)
            candidates += len(cand)
            top = max(c[0] for c in cand)
            best_overall = max(best_overall, top)
            kd = a.k_div[j]
            assert kd == -1 or kd in ks, f"{label}: k_div[{j}] = {kd} is not a feasible cell"
            chosen = enb_front[j] if kd == -1 else enb[j, kd]
            chosen_rank = NY if kd == -1 else kd
            assert chosen >= top - 1e-9, (
                f"{label}: k_div[{j}] = {kd} is not the highest-ENB candidate"
            )
            clear = [c for c in cand if c[0] >= top - 1e-9]
            if len(clear) == 1:
                assert kd == clear[0][2], f"{label}: k_div[{j}] = {kd}, expected {clear[0][2]}"
            ties_above = [c for c in cand if c[0] == chosen and c[1] > chosen_rank]
            assert not ties_above, f"{label}: column {j} tie not broken toward the highest return"
            if kd == -1:
                assert a.y_div[j] == a.yf[j], f"{label}: collapsed column {j} must store y_front"
                assert np.array_equal(a.w_div[j], a.wf[j])
            else:
                assert a.y_div[j] == a.gy[kd], f"{label}: y_div[{j}] is not the floor of cell {kd}"
                assert np.array_equal(a.w_div[j], np.asarray(a.gw[j][kd], float))
            enb_div = _enb(a.w_div[j], a)
            assert not enb_div < enb_front[j] - 1e-9, (
                f"{label}: ENB(w_div) < ENB(w_front) in column {j}"
            )
        enb_ref = float(t["enb_ref"])
        assert abs(enb_ref - best_overall) <= 1e-9, f"{label}: enb_ref {enb_ref} != {best_overall}"
        assert not enb_ref < np.nanmax(enb) - 1e-9
        assert not enb_ref < enb_front.max() - 1e-9
        assert candidates == NX + feasible
        return feasible

    def test_fixture_surface(tmp_path_factory):
        feasible = _check_surface(_fixture_tensor(tmp_path_factory), "fixture")
        assert feasible >= 500

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
