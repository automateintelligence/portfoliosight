"""A-PS-15 - minimum-torsion ENB identities hold and violations raise.

Claim: min_torsion(cov) returns T with T cov T' diagonal, ENB(w) built from b = T^-T w,
Lambda = diag(T cov T'), p_i = Lambda_i b_i^2 / (w' cov w) satisfies the spec 4.6 identities, and
the ENB check raises (never clips) when the diagonality check fails.

Pinned interface (the product must provide exactly this):
- portfoliosight.engine.torsion.min_torsion(cov) -> ndarray (n x n)
- portfoliosight.engine.torsion.effective_number_of_bets(w, cov, torsion=None) -> float
  (torsion=None means min_torsion(cov); an explicit torsion is checked, not trusted: when
  max|offdiag(T cov T')| > 1e-8 * trace(T cov T') it raises a ValueError subclass whose message
  contains the text "offdiag"; it never returns a clipped number).

Spec leg (c) says a single-FUND vector on a random SPD matrix has ENB = 1. That is false for
minimum torsion (spec 4.9 says so itself: a single holding loads several factors when it is
correlated). Encoded instead: single fund on a diagonal matrix, and a single torsion BET
(w proportional to T' e_i) on a random SPD matrix, both give ENB = 1.
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
        pytest.fail(f"A-PS-15 red: cannot import {module}: {type(exc).__name__}: {exc}")


def _attr(module: str, name: str):
    mod = _need(module)
    if not hasattr(mod, name):
        pytest.fail(f"A-PS-15 red: {module} has no attribute {name!r} (pinned interface)")
    return getattr(mod, name)


def _deps():
    if np is None or pd is None:
        pytest.fail("A-PS-15 red: numpy and pandas are not importable in this interpreter")


BUILD_CLI = ROOT / "scripts" / "build_tensor.py"
FIXTURE = ROOT / "tests" / "fixtures" / "synthetic_23.parquet"
NX, NY = 48, 32
TOL = 1e-6
_CACHE: dict = {}


def _run_cli(script: Path, args: list, timeout: int = 300):
    if not script.exists():
        pytest.fail(f"A-PS-15 red: {script.relative_to(ROOT)} does not exist")
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
        pytest.fail(f"A-PS-15 red: {script.name} did not finish within {timeout} s")


def _build(returns: Path, lookback: str, asof: str, out: Path, caps: Path | None = None) -> dict:
    """Build one tensor through the pinned CLI and return the parsed JSON."""
    args = ["--returns", returns, "--lookback", lookback, "--asof", asof, "--out", out]
    if caps is not None:
        args += ["--caps", caps]
    proc = _run_cli(BUILD_CLI, args)
    if proc.returncode != 0 or not Path(out).exists():
        pytest.fail(
            f"A-PS-15 red: build_tensor.py exit {proc.returncode}, file={Path(out).exists()}: "
            f"{proc.stderr[-1500:]}"
        )
    try:
        return json.loads(Path(out).read_text())
    except ValueError as exc:
        pytest.fail(f"A-PS-15 red: {out} is not JSON: {exc}")


def _fixture_frame():
    _deps()
    _need("pyarrow")
    if not FIXTURE.exists():
        pytest.fail(f"A-PS-15 red: fixture {FIXTURE.relative_to(ROOT)} does not exist")
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
        pytest.fail(f"A-PS-15 red: tensor lacks a spec 7 field or has a ragged array: {exc!r}")
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

    def test_a_ps_15_in_project_venv():
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
        assert proc.returncode == 0, "A-PS-15 is red inside the project virtualenv (output above)"

else:
    import math

    def _spd(rng, n):
        a = rng.normal(size=(n, n))
        corr_like = a @ a.T / n + np.diag(rng.uniform(0.2, 1.0, n))
        vol = rng.uniform(0.03, 0.30, n)
        return corr_like * np.outer(vol, vol)

    def _p(w, cov, t):
        m = t @ cov @ t.T
        b = np.linalg.solve(t.T, w)
        return np.diag(m) * b**2 / (w @ cov @ w), m

    def _enb_own(w, cov, t):
        p, _ = _p(w, cov, t)
        nz = p[p > 0]
        return float(np.exp(-(nz * np.log(nz)).sum()))

    def _fns():
        _deps()
        return (
            _attr("portfoliosight.engine.torsion", "min_torsion"),
            _attr("portfoliosight.engine.torsion", "effective_number_of_bets"),
        )

    def test_a_diagonal_cov_gives_identity_and_b_inverse_vol_gives_n():
        min_torsion, enb = _fns()
        rng = np.random.default_rng(1501)
        for n in (2, 5, 23):
            vol = rng.uniform(0.02, 0.40, n)
            cov = np.diag(vol**2)
            t = np.asarray(min_torsion(cov), float)
            assert t.shape == (n, n)
            assert np.abs(t - np.eye(n)).max() <= 1e-10, f"N={n}: T != I on a diagonal covariance"
            w = (1 / vol) / (1 / vol).sum()
            assert abs(enb(w, cov) - n) <= 1e-8, f"N={n}: inverse-volatility ENB != N"
            one = np.zeros(n)
            one[n // 2] = 1.0
            assert abs(enb(one, cov) - 1.0) <= 1e-8, f"N={n}: single-fund ENB != 1 on diagonal cov"
            skew = rng.dirichlet(np.ones(n))
            assert abs(enb(skew, cov) - n) > 1e-6  # ENB must respond to the weights, not echo N

    def test_c_single_bet_on_random_spd_gives_one():
        min_torsion, enb = _fns()
        rng = np.random.default_rng(1502)
        for n in (3, 8, 17):
            cov = _spd(rng, n)
            t = np.asarray(min_torsion(cov), float)
            for i in (0, n - 1):
                w = t.T[:, i] / t.T[:, i].sum()
                assert abs(enb(w, cov) - 1.0) <= 1e-8, f"N={n}: one torsion bet must give ENB = 1"
            fund = np.zeros(n)
            fund[1] = 1.0
            value = enb(fund, cov)
            assert 1 - 1e-6 <= value <= n + 1e-6
            assert abs(value - _enb_own(fund, cov, t)) <= 1e-9

    def test_d_two_uncorrelated_funds_closed_form():
        _, enb = _fns()
        cov = np.diag([0.10**2, 0.20**2])
        expected = math.exp(-(0.2 * math.log(0.2) + 0.8 * math.log(0.8)))
        assert abs(expected - 1.649) < 1e-3
        value = enb(np.array([0.5, 0.5]), cov)
        assert abs(value - expected) <= 1e-3
        assert abs(value - 2.0) > 0.3  # not the weight count

    def test_equicorrelated_equal_weights_give_n():
        """Minimum torsion is symmetric on an exchangeable menu, so equal weights spread risk.

        A principal-components diagonalizer would pass the diagonal-matrix legs and report ENB = 1
        here; this is the leg that tells the minimum torsion from any other decorrelation.
        """
        min_torsion, enb = _fns()
        for n, rho in ((2, 0.6), (5, 0.3), (5, -0.1), (12, 0.5)):
            cov = 0.04 * ((1 - rho) * np.eye(n) + rho * np.ones((n, n)))
            t = np.asarray(min_torsion(cov), float)
            assert np.abs(t - t.T).max() <= 1e-8, f"N={n} rho={rho}: torsion not symmetric"
            value = enb(np.full(n, 1 / n), cov)
            assert abs(value - n) <= 1e-6, f"N={n} rho={rho}: ENB {value} != N"
            assert not abs(value - 1.0) < 0.5

    def test_e_random_spd_property():
        min_torsion, enb = _fns()
        rng = np.random.default_rng(1503)
        sizes = [2, 30] + [int(v) for v in rng.integers(2, 31, size=23)]
        checked = 0
        for n in sizes:
            cov = _spd(rng, n)
            w = rng.dirichlet(np.ones(n))
            t = np.asarray(min_torsion(cov), float)
            assert t.shape == (n, n)
            p, m = _p(w, cov, t)
            trace = np.trace(m)
            assert np.abs(m - np.diag(np.diag(m))).max() <= 1e-8 * trace, f"N={n}: not diagonal"
            assert abs(p.sum() - 1) <= 1e-8, f"N={n}: sum(p) = {p.sum()!r}"
            assert not (p < 0).any(), f"N={n}: negative variance contribution"
            value = enb(w, cov)
            assert 1 - 1e-6 <= value <= n + 1e-6, f"N={n}: ENB {value} out of range"
            assert abs(value - _enb_own(w, cov, t)) <= 1e-9, (
                f"N={n}: ENB differs from the 4.6 formula"
            )
            assert abs(enb(w, cov, torsion=t) - value) <= 1e-12
            checked += 1
        assert checked == 25 and min(sizes) == 2 and max(sizes) == 30

    def test_f_perturbed_torsion_raises_and_never_returns():
        min_torsion, enb = _fns()
        rng = np.random.default_rng(1504)
        for n in (4, 11):
            cov = _spd(rng, n)
            w = rng.dirichlet(np.ones(n))
            t = np.asarray(min_torsion(cov), float)
            m = t @ cov @ t.T
            bad_m = np.diag(np.diag(m)).copy()
            bad_m[0, 1] = bad_m[1, 0] = 1e-6 * np.trace(m)
            # T' = chol(M') chol(M)^-1 T gives T' cov T'' = M' exactly (M diagonal up to 1e-8)
            good_l = np.linalg.cholesky(np.diag(np.diag(m)))
            bad_t = np.linalg.cholesky(bad_m) @ np.linalg.inv(good_l) @ t
            check = bad_t @ cov @ bad_t.T
            assert abs(check[0, 1] - 1e-6 * np.trace(check)) <= 1e-9 * np.trace(check)
            returned = None
            try:
                returned = enb(w, cov, torsion=bad_t)
            except ValueError as exc:
                assert "offdiag" in str(exc).lower(), f"error does not name the bound: {exc}"
            except Exception as exc:
                pytest.fail(f"expected a ValueError subclass, got {type(exc).__name__}: {exc}")
            assert returned is None, (
                f"N={n}: ENB check returned {returned!r} for a non-diagonal torsion"
            )
