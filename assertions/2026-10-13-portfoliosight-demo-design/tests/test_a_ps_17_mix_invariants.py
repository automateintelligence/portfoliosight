"""A-PS-17 - every computed mix is real, and a bad vector raises.

Claim: every weight vector the builder writes (frontier.w[j], every non-null grid.w[j][k], every
grid.w_div[j]) satisfies |sum(w) - 1| <= 1e-6, min - 1e-6 <= w <= max + 1e-6 against the tensor's
resolved bounds, sigma(w) <= X_j + 1e-6 and 1 - 1e-6 <= ENB(w) <= N + 1e-6; and the builder's
post-check raises when handed a vector violating any one of them.

Pinned interface (the product must provide exactly this):
- scripts/build_tensor.py (shared CLI pin) and tests/fixtures/synthetic_23.parquet.
- portfoliosight.engine.tensor.check_weights(w, *, lo, hi, cov, ceiling, enb) -> None: the
  builder's post-check for one solved vector (enb = the ENB already computed for w; N = len(w)).
  On a violation it raises portfoliosight.engine.tensor.InvariantError, a ValueError subclass with
  attribute .invariant in {"sum", "bounds", "sigma", "enb"} and that name in its message.
  Tolerance 1e-6 on each invariant (a 5e-7 excess does not raise).
The tensor-wide leg recomputes sigma and ENB in the test from cov / torsion_inv_t /
torsion_lambda; nothing is asked of the product a second time.
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
        pytest.fail(f"A-PS-17 red: cannot import {module}: {type(exc).__name__}: {exc}")


def _attr(module: str, name: str):
    mod = _need(module)
    if not hasattr(mod, name):
        pytest.fail(f"A-PS-17 red: {module} has no attribute {name!r} (pinned interface)")
    return getattr(mod, name)


def _deps():
    if np is None or pd is None:
        pytest.fail("A-PS-17 red: numpy and pandas are not importable in this interpreter")


BUILD_CLI = ROOT / "scripts" / "build_tensor.py"
FIXTURE = ROOT / "tests" / "fixtures" / "synthetic_23.parquet"
NX, NY = 48, 32
TOL = 1e-6
_CACHE: dict = {}


def _run_cli(script: Path, args: list, timeout: int = 300):
    if not script.exists():
        pytest.fail(f"A-PS-17 red: {script.relative_to(ROOT)} does not exist")
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
        pytest.fail(f"A-PS-17 red: {script.name} did not finish within {timeout} s")


def _build(returns: Path, lookback: str, asof: str, out: Path, caps: Path | None = None) -> dict:
    """Build one tensor through the pinned CLI and return the parsed JSON."""
    args = ["--returns", returns, "--lookback", lookback, "--asof", asof, "--out", out]
    if caps is not None:
        args += ["--caps", caps]
    proc = _run_cli(BUILD_CLI, args)
    if proc.returncode != 0 or not Path(out).exists():
        pytest.fail(
            f"A-PS-17 red: build_tensor.py exit {proc.returncode}, file={Path(out).exists()}: "
            f"{proc.stderr[-1500:]}"
        )
    try:
        return json.loads(Path(out).read_text())
    except ValueError as exc:
        pytest.fail(f"A-PS-17 red: {out} is not JSON: {exc}")


def _fixture_frame():
    _deps()
    _need("pyarrow")
    if not FIXTURE.exists():
        pytest.fail(f"A-PS-17 red: fixture {FIXTURE.relative_to(ROOT)} does not exist")
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
        pytest.fail(f"A-PS-17 red: tensor lacks a spec 7 field or has a ragged array: {exc!r}")
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

    def test_a_ps_17_in_project_venv():
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
        assert proc.returncode == 0, "A-PS-17 is red inside the project virtualenv (output above)"

else:

    def test_every_vector_in_the_fixture_tensor(tmp_path_factory):
        t = _fixture_tensor(tmp_path_factory)
        a = _arrays(t)
        _check_torsion_fields(a)
        checked = cells = 0

        def check(w, j, what):
            w = np.asarray(w, float)
            assert w.shape == (a.n,), f"{what}: wrong length"
            assert abs(w.sum() - 1) <= TOL, f"{what}: sum {w.sum()!r}"
            assert not (w < a.lo - TOL).any(), f"{what}: weight below its minimum"
            assert not (w > a.hi + TOL).any(), f"{what}: weight above its maximum"
            sig = _sigma(w, a.cov)
            assert not sig > a.x[j] + TOL, f"{what}: sigma {sig} above ceiling {a.x[j]}"
            value = _enb(w, a)
            assert 1 - TOL <= value <= a.n + TOL, f"{what}: ENB {value} out of [1, N]"

        for j in range(NX):
            check(a.wf[j], j, f"frontier.w[{j}]")
            check(a.w_div[j], j, f"grid.w_div[{j}]")
            checked += 2
            for k in range(NY):
                if a.gw[j][k] is not None:
                    check(a.gw[j][k], j, f"grid.w[{j}][{k}]")
                    cells += 1
        checked += cells
        assert cells >= 500, f"only {cells} non-null cells: the check would be vacuous"
        assert checked == 48 + 48 + cells
        assert cells != NX * NY  # some cells must be infeasible (null) on a real surface

    def _case():
        cov = np.diag([0.02, 0.05, 0.08, 0.12]) ** 2 + 1e-4
        w = np.full(4, 0.25)
        lo, hi = np.zeros(4), np.full(4, 0.5)
        return w, lo, hi, cov, _sigma(w, cov) + 1e-3, 2.0

    def _expect_raise(check, exc_type, name, w, lo, hi, cov, ceiling, enb):
        try:
            returned = check(w, lo=lo, hi=hi, cov=cov, ceiling=ceiling, enb=enb)
        except exc_type as exc:
            assert getattr(exc, "invariant", None) == name, (
                f"violating {name!r} raised invariant {getattr(exc, 'invariant', None)!r}: {exc}"
            )
            assert name in str(exc), f"message does not name {name!r}: {exc}"
            assert isinstance(exc, ValueError)
            return
        pytest.fail(f"post-check returned {returned!r} for a vector violating {name!r} by 1e-4")

    def test_post_check_raises_on_each_invariant_alone():
        _deps()
        check = _attr("portfoliosight.engine.tensor", "check_weights")
        err = _attr("portfoliosight.engine.tensor", "InvariantError")
        assert isinstance(err, type) and issubclass(err, ValueError)
        w, lo, hi, cov, ceiling, enb = _case()
        assert check(w, lo=lo, hi=hi, cov=cov, ceiling=ceiling, enb=enb) is None  # control
        # inside the 1e-6 tolerance: must not raise
        check(w + 5e-7 / 4, lo=lo, hi=hi, cov=cov, ceiling=ceiling, enb=enb)
        check(w, lo=lo, hi=hi, cov=cov, ceiling=_sigma(w, cov) - 5e-7, enb=enb)
        check(w, lo=lo, hi=hi, cov=cov, ceiling=ceiling, enb=4 + 5e-7)
        check(w, lo=lo, hi=hi, cov=cov, ceiling=ceiling, enb=1 - 5e-7)

        raised = 0
        # 1. sum off by 1e-4, everything else inside
        _expect_raise(check, err, "sum", w + 1e-4 / 4, lo, hi, cov, ceiling, enb)
        _expect_raise(check, err, "sum", w - 1e-4 / 4, lo, hi, cov, ceiling, enb)
        # 2. one weight 1e-4 above its maximum / below its minimum, sum still 1
        over = np.array([0.5 + 1e-4, 0.5 - 1e-4, 0.0, 0.0])
        _expect_raise(check, err, "bounds", over, lo, hi, cov, _sigma(over, cov) + 1e-3, enb)
        under = np.array([0.1 - 1e-4, 0.3 + 1e-4, 0.3, 0.3])
        lo_b = np.array([0.1, 0.0, 0.0, 0.0])
        _expect_raise(check, err, "bounds", under, lo_b, hi, cov, _sigma(under, cov) + 1e-3, enb)
        # 3. sigma 1e-4 above the ceiling
        _expect_raise(check, err, "sigma", w, lo, hi, cov, _sigma(w, cov) - 1e-4, enb)
        # 4. ENB 1e-4 outside [1, N]
        _expect_raise(check, err, "enb", w, lo, hi, cov, ceiling, 4 + 1e-4)
        _expect_raise(check, err, "enb", w, lo, hi, cov, ceiling, 1 - 1e-4)
        raised += 7
        assert raised == 7
