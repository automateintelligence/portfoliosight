"""A-PS-20 - moments are estimated as specified (spec 4.3).

Claim: fixed windows use mu_i = 252 mean, sigma_i = sqrt(252) sd(ddof=1), LedoitWolf on
standardized returns renormalized to a correlation matrix and rescaled with annual variances; ew
uses half-life 252 weights, the weighted sample correction and R_s = 0.8 R + 0.2 I; the diagonal
floor sigma_i >= 1e-4 applies before factorization in both paths; mu_s = 0.5 mu_hat + 0.5 pi with
pi_i = r_f + beta_i max(mu_eq - r_f, 0); r_f is SGOV's trailing-12-month total return if served,
else TSP-G's, else 0.04.

Pinned interface (the product must provide exactly this), all in portfoliosight.engine.stats:
- estimate_moments(returns, omega=None) -> object with .mu, .sigma, .cov (annual units, numpy)
  and .t_eff. returns is a T x N array of daily returns. omega=None is the fixed-window path
  (LedoitWolf); an omega vector (sums to 1) is the ew path (weighted moments, 0.8/0.2 shrink).
- ew_weights(T) -> the half-life-252 weights by position (last row heaviest), summing to 1.
- menu_beta_blend(mu_hat, cov, rf) -> (mu_s, pi).
- risk_free_rate(returns_by_symbol) -> float, where returns_by_symbol maps a served symbol id to
  its daily total-return series (rows up to asof); the 12-month return is the compounded last
  252 rows; ids "SGOV" then "TSP-G"; 0.04 when neither is present.
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
        pytest.fail(f"A-PS-20 red: cannot import {module}: {type(exc).__name__}: {exc}")


def _attr(module: str, name: str):
    mod = _need(module)
    if not hasattr(mod, name):
        pytest.fail(f"A-PS-20 red: {module} has no attribute {name!r} (pinned interface)")
    return getattr(mod, name)


def _deps():
    if np is None or pd is None:
        pytest.fail("A-PS-20 red: numpy and pandas are not importable in this interpreter")


BUILD_CLI = ROOT / "scripts" / "build_tensor.py"
FIXTURE = ROOT / "tests" / "fixtures" / "synthetic_23.parquet"
NX, NY = 48, 32
TOL = 1e-6
_CACHE: dict = {}


def _run_cli(script: Path, args: list, timeout: int = 300):
    if not script.exists():
        pytest.fail(f"A-PS-20 red: {script.relative_to(ROOT)} does not exist")
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
        pytest.fail(f"A-PS-20 red: {script.name} did not finish within {timeout} s")


def _build(returns: Path, lookback: str, asof: str, out: Path, caps: Path | None = None) -> dict:
    """Build one tensor through the pinned CLI and return the parsed JSON."""
    args = ["--returns", returns, "--lookback", lookback, "--asof", asof, "--out", out]
    if caps is not None:
        args += ["--caps", caps]
    proc = _run_cli(BUILD_CLI, args)
    if proc.returncode != 0 or not Path(out).exists():
        pytest.fail(
            f"A-PS-20 red: build_tensor.py exit {proc.returncode}, file={Path(out).exists()}: "
            f"{proc.stderr[-1500:]}"
        )
    try:
        return json.loads(Path(out).read_text())
    except ValueError as exc:
        pytest.fail(f"A-PS-20 red: {out} is not JSON: {exc}")


def _fixture_frame():
    _deps()
    _need("pyarrow")
    if not FIXTURE.exists():
        pytest.fail(f"A-PS-20 red: fixture {FIXTURE.relative_to(ROOT)} does not exist")
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
        pytest.fail(f"A-PS-20 red: tensor lacks a spec 7 field or has a ragged array: {exc!r}")
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

    def test_a_ps_20_in_project_venv():
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
        assert proc.returncode == 0, "A-PS-20 is red inside the project virtualenv (output above)"

else:

    def _stats():
        _deps()
        return _need("portfoliosight.engine.stats")

    def _returns(with_degenerate: bool):
        rng = np.random.default_rng(2001)
        t_rows, n = 900, 6
        load = rng.normal(0.0, 1.0, (n, 2)) * 0.006
        r = (
            rng.normal(0.0, 1.0, (t_rows, 2)) @ load.T
            + rng.normal(0.0, 0.005, (t_rows, n))
            + 0.0003
        )
        if with_degenerate:
            r[:, 1] = 0.00012 + rng.normal(0.0, 0.003 / np.sqrt(252.0), t_rows)  # sigma ~ 0.3%/yr
            r[:, 4] = 0.0001  # exactly constant
        return r

    def _own_ew(r, omega):
        mean = omega @ r
        x = r - mean
        s = (x * omega[:, None]).T @ x / (1.0 - (omega**2).sum())
        return mean, s

    def test_fixed_window_matches_the_recipe():
        stats = _stats()
        lw = _need("sklearn.covariance")
        r = _returns(False)
        m = stats.estimate_moments(r)
        mu, sigma, cov = np.asarray(m.mu), np.asarray(m.sigma), np.asarray(m.cov)
        sd = r.std(axis=0, ddof=1)
        assert np.abs(mu - 252.0 * r.mean(axis=0)).max() <= 1e-12
        assert np.abs(sigma - np.sqrt(252.0) * sd).max() <= 1e-12
        assert np.abs(sigma - np.sqrt(252.0) * r.std(axis=0, ddof=0)).max() > 1e-7  # not ddof=0
        q = lw.LedoitWolf().fit(r / sd).covariance_
        corr = q / np.sqrt(np.outer(np.diag(q), np.diag(q)))
        expected = np.outer(sigma, sigma) * corr
        assert np.abs(cov - expected).max() <= 1e-10, "cov is not the LedoitWolf correlation recipe"
        sample = np.cov(r, rowvar=False) * 252.0
        assert np.abs(cov - sample).max() > 1e-7  # shrinkage really applied
        assert np.abs(np.diag(cov) - sigma**2).max() <= 1e-12
        assert float(m.t_eff) == float(len(r))

    def test_ew_path_and_uniform_weights_reproduce_fixed_sigma():
        stats = _stats()
        r = _returns(False)
        t_rows, n = r.shape
        uniform = np.full(t_rows, 1.0 / t_rows)
        fixed, ew_u = stats.estimate_moments(r), stats.estimate_moments(r, omega=uniform)
        assert np.abs(np.asarray(ew_u.sigma) - np.asarray(fixed.sigma)).max() <= 1e-12
        assert np.abs(np.asarray(ew_u.mu) - np.asarray(fixed.mu)).max() <= 1e-12
        assert abs(float(ew_u.t_eff) - t_rows) <= 1e-6

        omega = np.asarray(stats.ew_weights(t_rows), float)
        own = 0.5 ** ((t_rows - 1 - np.arange(t_rows)) / 252.0)
        own /= own.sum()
        assert omega.shape == (t_rows,) and np.abs(omega - own).max() <= 1e-15
        assert abs(omega[-1] / omega[-253] - 2.0) <= 1e-9 and omega[-1] > omega[0]
        m = stats.estimate_moments(r, omega=omega)
        mean, s = _own_ew(r, own)
        sigma = np.sqrt(252.0 * np.diag(s))
        assert np.abs(np.asarray(m.mu) - 252.0 * mean).max() <= 1e-12
        assert np.abs(np.asarray(m.sigma) - sigma).max() <= 1e-12
        corr = s / np.sqrt(np.outer(np.diag(s), np.diag(s)))
        expected = np.outer(sigma, sigma) * (0.8 * corr + 0.2 * np.eye(n))
        assert np.abs(np.asarray(m.cov) - expected).max() <= 1e-10, "ew cov is not 0.8 R + 0.2 I"
        assert np.abs(np.asarray(m.cov) - np.outer(sigma, sigma) * corr).max() > 1e-7
        assert abs(float(m.t_eff) - 1.0 / (own**2).sum()) <= 1e-6
        assert not abs(float(m.t_eff) - t_rows) < 1.0
        assert np.abs(np.asarray(m.sigma) - np.asarray(fixed.sigma)).max() > 1e-6

    def test_floor_and_near_constant_fund_keep_their_own_variance():
        stats = _stats()
        r = _returns(True)
        t_rows, n = r.shape
        paths = {
            "fixed": stats.estimate_moments(r),
            "ew-uniform": stats.estimate_moments(r, omega=np.full(t_rows, 1.0 / t_rows)),
            "ew": stats.estimate_moments(r, omega=np.asarray(stats.ew_weights(t_rows), float)),
        }
        own_sd = np.sqrt(252.0) * r.std(axis=0, ddof=1)
        assert 0.002 < own_sd[1] < 0.004 and own_sd[4] < 1e-12
        for name, m in paths.items():
            sigma, cov = np.asarray(m.sigma, float), np.asarray(m.cov, float)
            assert np.isfinite(sigma).all() and np.isfinite(cov).all(), (
                f"{name}: non-finite moments"
            )
            assert sigma[4] == 1e-4, f"{name}: constant column sigma {sigma[4]!r}, floor is 1e-4"
            assert not (sigma < 1e-4).any(), f"{name}: a sigma below the floor"
            corr = cov / np.outer(sigma, sigma)
            assert np.abs(np.diag(corr) - 1.0).max() <= 1e-12, f"{name}: R diagonal is not 1"
            assert np.abs(np.diag(cov) - sigma**2).max() <= 1e-12, f"{name}: cov_ii != sigma_i^2"
            assert np.abs(cov - cov.T).max() <= 1e-15
            try:
                np.linalg.cholesky(cov)
            except np.linalg.LinAlgError:
                pytest.fail(f"{name}: covariance does not factor after the floor")
        for name in ("fixed", "ew-uniform"):
            sigma = np.asarray(paths[name].sigma, float)
            assert abs(sigma[1] - own_sd[1]) <= 1e-12, (
                f"{name}: near-constant fund lost its variance"
            )
            assert (
                sigma[1] < 0.1 * np.delete(sigma, [1, 4]).mean()
            )  # not pulled to the menu average
            keep = [0, 2, 3, 5]
            assert np.abs(sigma[keep] - own_sd[keep]).max() <= 1e-12

    def test_menu_beta_blend_both_premium_signs():
        stats = _stats()
        rng = np.random.default_rng(2002)
        n = 7
        a = rng.normal(size=(n, n))
        cov = (a @ a.T / n + 0.2 * np.eye(n)) * 0.03
        w_eq = np.full(n, 1.0 / n)
        beta = cov @ w_eq / (w_eq @ cov @ w_eq)
        mu_hat = rng.uniform(0.02, 0.12, n)
        rf = 0.03
        assert w_eq @ mu_hat - rf > 0.01
        mu_s, pi = (np.asarray(v, float) for v in stats.menu_beta_blend(mu_hat, cov, rf))
        assert abs(w_eq @ pi - w_eq @ mu_hat) <= 1e-12
        assert np.abs(pi - (rf + beta * (w_eq @ mu_hat - rf))).max() <= 1e-12
        assert np.abs(mu_s - (0.5 * mu_hat + 0.5 * pi)).max() <= 1e-12
        assert np.abs(pi - rf).max() > 1e-3 and np.abs(mu_s - mu_hat).max() > 1e-4

        for label, low_mu, low_rf in (
            ("negative premium", rng.uniform(-0.05, 0.02, n), 0.045),
            ("zero premium", np.full(n, 0.04) + np.linspace(-0.01, 0.01, n), 0.04),
        ):
            assert w_eq @ low_mu - low_rf <= 1e-15, label
            mu_s, pi = (np.asarray(v, float) for v in stats.menu_beta_blend(low_mu, cov, low_rf))
            assert not (np.abs(pi - low_rf) > 1e-15).any(), f"{label}: a pi_i differs from r_f"
            assert np.abs(mu_s - (0.5 * low_mu + 0.5 * low_rf)).max() <= 1e-12, label

    def test_risk_free_rate_sources():
        stats = _stats()
        rng = np.random.default_rng(2003)
        index = pd.bdate_range(end="2026-06-30", periods=400, name="date")
        sgov = pd.Series(0.00018 + rng.normal(0.0, 1e-5, 400), index=index)
        tsp_g = pd.Series(0.00011 + rng.normal(0.0, 1e-5, 400), index=index)
        vti = pd.Series(rng.normal(0.0004, 0.01, 400), index=index)
        r_sgov = float(np.prod(1.0 + sgov.to_numpy()[-252:]) - 1.0)
        r_tsp = float(np.prod(1.0 + tsp_g.to_numpy()[-252:]) - 1.0)
        assert abs(r_sgov - r_tsp) > 0.01
        with_sgov = stats.risk_free_rate({"VTI": vti, "TSP-G": tsp_g, "SGOV": sgov})
        assert abs(with_sgov - r_sgov) <= 1e-12
        assert abs(with_sgov - r_tsp) > 0.01  # SGOV wins over TSP-G whatever the order
        assert abs(with_sgov - float(np.prod(1.0 + sgov.to_numpy()) - 1.0)) > 0.01  # 252 rows only
        assert abs(stats.risk_free_rate({"VTI": vti, "TSP-G": tsp_g}) - r_tsp) <= 1e-12
        assert stats.risk_free_rate({"VTI": vti}) == 0.04
        assert stats.risk_free_rate({}) == 0.04
