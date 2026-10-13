"""A-PS-16 - frontier nodes sit on their ceiling and returns do not decrease.

Claim: through the builder's public entry point every frontier node j with X_j < sigma_max has
sigma(w_front[j]) = X_j within 1e-6, y_front is non-decreasing, X_0 is the minimum-variance risk
under the bounds, X_47 is the risk of the max-return greedy fill, and |Cw|^2 = w' cov w for
C = cholesky(cov)'.

Pinned interface (the product must provide exactly this):
- scripts/build_tensor.py --returns <parquet> --lookback <id> --asof YYYY-MM-DD --out <json>
  [--caps <json list of {"id","min","max"}; null = default rule>]; exit 0 and a spec 7 tensor.
- tests/fixtures/synthetic_23.parquet (returns parquet: DatetimeIndex "date", one float column
  per fund).
- portfoliosight.engine.optimize.cholesky_factor(cov) -> C, upper triangular, C = cholesky(cov)'.
All frontier checks are the test's own numpy/cvxpy math on the tensor's cov, mu_s, bounds and
frontier fields. The five random menus (N = 2, 5, 12, 23, 30) are simulated by the test from
seeded SPD covariances, written to tmp_path and built through the same CLI with random caps; the
tensor must record exactly those caps in bounds.min/max and bounds.requested.
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
        pytest.fail(f"A-PS-16 red: cannot import {module}: {type(exc).__name__}: {exc}")


def _attr(module: str, name: str):
    mod = _need(module)
    if not hasattr(mod, name):
        pytest.fail(f"A-PS-16 red: {module} has no attribute {name!r} (pinned interface)")
    return getattr(mod, name)


def _deps():
    if np is None or pd is None:
        pytest.fail("A-PS-16 red: numpy and pandas are not importable in this interpreter")


BUILD_CLI = ROOT / "scripts" / "build_tensor.py"
FIXTURE = ROOT / "tests" / "fixtures" / "synthetic_23.parquet"
NX, NY = 48, 32
TOL = 1e-6
_CACHE: dict = {}


def _run_cli(script: Path, args: list, timeout: int = 300):
    if not script.exists():
        pytest.fail(f"A-PS-16 red: {script.relative_to(ROOT)} does not exist")
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
        pytest.fail(f"A-PS-16 red: {script.name} did not finish within {timeout} s")


def _build(returns: Path, lookback: str, asof: str, out: Path, caps: Path | None = None) -> dict:
    """Build one tensor through the pinned CLI and return the parsed JSON."""
    args = ["--returns", returns, "--lookback", lookback, "--asof", asof, "--out", out]
    if caps is not None:
        args += ["--caps", caps]
    proc = _run_cli(BUILD_CLI, args)
    if proc.returncode != 0 or not Path(out).exists():
        pytest.fail(
            f"A-PS-16 red: build_tensor.py exit {proc.returncode}, file={Path(out).exists()}: "
            f"{proc.stderr[-1500:]}"
        )
    try:
        return json.loads(Path(out).read_text())
    except ValueError as exc:
        pytest.fail(f"A-PS-16 red: {out} is not JSON: {exc}")


def _fixture_frame():
    _deps()
    _need("pyarrow")
    if not FIXTURE.exists():
        pytest.fail(f"A-PS-16 red: fixture {FIXTURE.relative_to(ROOT)} does not exist")
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
        pytest.fail(f"A-PS-16 red: tensor lacks a spec 7 field or has a ragged array: {exc!r}")
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

    def test_a_ps_16_in_project_venv():
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
        assert proc.returncode == 0, "A-PS-16 is red inside the project virtualenv (output above)"

else:

    def _min_variance_sigma(cov, lo, hi) -> float:
        cp = _need("cvxpy")
        n = len(lo)
        c = np.linalg.cholesky(cov).T
        w = cp.Variable(n)
        problem = cp.Problem(cp.Minimize(cp.norm(c @ w, 2)), [cp.sum(w) == 1, w >= lo, w <= hi])
        try:
            problem.solve(solver=cp.CLARABEL, tol_feas=1e-10, tol_gap_abs=1e-10, tol_gap_rel=1e-10)
        except Exception as exc:
            pytest.fail(f"A-PS-16 red: the test's own minimum-variance solve failed: {exc!r}")
        assert problem.status == "optimal", problem.status
        return _sigma(np.array(w.value), cov)

    def _check_frontier(t: dict, label: str) -> int:
        a = _arrays(t)
        sig = np.array([_sigma(w, a.cov) for w in a.wf])
        s_min, s_max = a.x[0], a.x[-1]
        assert s_max - s_min > 1e-4, f"{label}: degenerate risk grid"
        assert np.abs(a.x - np.linspace(s_min, s_max, NX)).max() <= 1e-9, f"{label}: X not uniform"
        bound = 0
        for j in range(NX):
            assert not sig[j] > a.x[j] + TOL, (
                f"{label}: node {j} above its ceiling ({sig[j]} > {a.x[j]})"
            )
            if a.x[j] < s_max - 1e-9:
                assert not sig[j] < a.x[j] - TOL, f"{label}: node {j} strictly inside its ceiling"
                assert abs(sig[j] - a.x[j]) <= TOL
                bound += 1
            assert abs(a.yf[j] - a.mu @ a.wf[j]) <= TOL, f"{label}: y_front[{j}] != mu_s . w_front"
        assert bound >= NX - 2, f"{label}: only {bound} nodes below sigma_max"
        steps = np.diff(a.yf)
        assert not (steps < -1e-9).any(), (
            f"{label}: y_front decreases at {np.flatnonzero(steps < -1e-9)}"
        )
        assert a.yf[-1] - a.yf[0] > 1e-6, f"{label}: flat frontier"
        expected_min = _min_variance_sigma(a.cov, a.lo, a.hi)
        assert abs(s_min - expected_min) <= TOL, (
            f"{label}: X_0 {s_min} != min-variance {expected_min}"
        )
        greedy = _greedy(a.mu, a.lo, a.hi)
        assert abs(greedy.sum() - 1) <= 1e-12
        assert abs(s_max - _sigma(greedy, a.cov)) <= TOL, (
            f"{label}: X_47 != sigma of the greedy fill"
        )
        assert np.abs(a.wf[-1] - greedy).max() <= TOL, f"{label}: last node != greedy fill"
        return bound

    def test_fixture_frontier(tmp_path_factory):
        t = _fixture_tensor(tmp_path_factory)
        assert len(t["frontier"]["x"]) == 48
        assert _check_frontier(t, "fixture") >= 46

    def test_random_spd_menus(tmp_path):
        seen = []
        for n, seed in ((2, 1602), (5, 1605), (12, 1612), (23, 1623), (30, 1630)):
            returns, caps, asof, lo, hi, requested = _random_menu(tmp_path, n, seed)
            t = _build(returns, "5y", asof, tmp_path / f"tensor_{n}.json", caps)
            assert len(t["universe"]["funds"]) == n, f"N={n}: menu size changed"
            assert [f["id"] for f in t["universe"]["funds"]] == [f"M{i:02d}" for i in range(n)]
            assert np.abs(np.array(t["bounds"]["min"]) - lo).max() <= 1e-12, (
                f"N={n}: caps min ignored"
            )
            assert np.abs(np.array(t["bounds"]["max"]) - hi).max() <= 1e-12, (
                f"N={n}: caps max ignored"
            )
            got = [{"min": r.get("min"), "max": r.get("max")} for r in t["bounds"]["requested"]]
            assert got == requested, f"N={n}: bounds.requested does not echo the requested caps"
            _check_frontier(t, f"N={n}")
            seen.append(n)
        assert seen == [2, 5, 12, 23, 30]

    def test_cholesky_identity():
        _deps()
        factor = _attr("portfoliosight.engine.optimize", "cholesky_factor")
        rng = np.random.default_rng(1699)
        n = 15
        a = rng.normal(size=(n, n))
        cov = (a @ a.T / n + 0.1 * np.eye(n)) * 0.04
        c = np.asarray(factor(cov), float)
        assert c.shape == (n, n)
        assert np.abs(c - np.linalg.cholesky(cov).T).max() <= 1e-12, "C != cholesky(cov)'"
        assert np.abs(np.tril(c, -1)).max() == 0.0, "C must be upper triangular (L', not L)"
        checked = 0
        worst_wrong = 0.0
        for _ in range(100):
            w = rng.dirichlet(np.ones(n))
            assert abs((c @ w) @ (c @ w) - w @ cov @ w) <= 1e-12
            worst_wrong = max(worst_wrong, abs((c.T @ w) @ (c.T @ w) - w @ cov @ w))
            checked += 1
        assert checked == 100
        assert (
            worst_wrong > 1e-8
        )  # the identity is not symmetric in C vs C': the convention matters
