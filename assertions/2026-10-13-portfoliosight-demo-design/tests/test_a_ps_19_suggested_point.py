"""A-PS-19 - the suggested point is the balanced point: the knee of ENB gained against return given up.

Claim: on every column's ladder (returns never rising, ENB never falling, frontier mix first, peak
last) the balanced level is the one that maximizes e - g, where e is the share of the ladder's ENB
gain reached and g the share of its return span given up (the perpendicular distance above the
chord from the frontier mix to the peak, up to a factor), the earliest level on a tie; a ladder
that gains no more than 1e-6 ENB answers level 0 (the frontier mix) and one that gains ENB for
no more than 1e-6 of return answers the last level. The tensor stores t_balanced = level / (L - 1)
and y_balanced = that level's return for every column, default_point = "balanced", and
t_suggested / y_suggested equal to the balanced ones; the peak stays the last level; the
suggested return lies between the peak's and the frontier's.

Pinned interface (the product must provide exactly this):
- scripts/build_tensor.py (shared CLI pin) and tests/fixtures/synthetic_23.parquet.
- portfoliosight.engine.suggest.balanced_level(returns, enbs) -> int: the balanced level of one
  ladder given its levels' returns and ENBs (frontier mix first); ValueError on arrays of
  different shapes or fewer than two levels.
- portfoliosight.engine.suggest.suggested_level(returns, enbs, point="balanced") -> int: the
  balanced level, or the last level for point="peak" (0 when the ladder gains no ENB);
  ValueError on any other point.
- portfoliosight.engine.suggest.DEFAULT_POINT == "balanced".
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
        pytest.fail(f"A-PS-19 red: cannot import {module}: {type(exc).__name__}: {exc}")


def _attr(module: str, name: str):
    mod = _need(module)
    if not hasattr(mod, name):
        pytest.fail(f"A-PS-19 red: {module} has no attribute {name!r} (pinned interface)")
    return getattr(mod, name)


def _deps():
    if np is None or pd is None:
        pytest.fail("A-PS-19 red: numpy and pandas are not importable in this interpreter")


BUILD_CLI = ROOT / "scripts" / "build_tensor.py"
FIXTURE = ROOT / "tests" / "fixtures" / "synthetic_23.parquet"
NX, NY = 48, 32
TOL = 1e-6
_CACHE: dict = {}


def _run_cli(script: Path, args: list, timeout: int = 300):
    if not script.exists():
        pytest.fail(f"A-PS-19 red: {script.relative_to(ROOT)} does not exist")
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
        pytest.fail(f"A-PS-19 red: {script.name} did not finish within {timeout} s")


def _build(returns: Path, lookback: str, asof: str, out: Path, caps: Path | None = None) -> dict:
    """Build one tensor through the pinned CLI and return the parsed JSON."""
    args = ["--returns", returns, "--lookback", lookback, "--asof", asof, "--out", out]
    if caps is not None:
        args += ["--caps", caps]
    proc = _run_cli(BUILD_CLI, args)
    if proc.returncode != 0 or not Path(out).exists():
        pytest.fail(
            f"A-PS-19 red: build_tensor.py exit {proc.returncode}, file={Path(out).exists()}: "
            f"{proc.stderr[-1500:]}"
        )
    try:
        return json.loads(Path(out).read_text())
    except ValueError as exc:
        pytest.fail(f"A-PS-19 red: {out} is not JSON: {exc}")


def _fixture_frame():
    _deps()
    _need("pyarrow")
    if not FIXTURE.exists():
        pytest.fail(f"A-PS-19 red: fixture {FIXTURE.relative_to(ROOT)} does not exist")
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
        pytest.fail(f"A-PS-19 red: tensor lacks a spec 7 field or has a ragged array: {exc!r}")
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

    def test_a_ps_19_in_project_venv():
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
        assert proc.returncode == 0, "A-PS-19 is red inside the project virtualenv (output above)"

else:

    def _knee(returns, enbs) -> int:
        """The test's own balanced level (spec 4.8), from the stored returns and ENBs."""
        returns, enbs = np.asarray(returns, float), np.asarray(enbs, float)
        gained, given_up = enbs[-1] - enbs[0], returns[0] - returns[-1]
        if not gained > TOL:
            return 0
        if not given_up > TOL:
            return len(returns) - 1
        above = (enbs - enbs[0]) / gained - (returns[0] - returns) / given_up
        return int(np.flatnonzero(above == above.max())[0])

    def _fns():
        _deps()
        return (
            _attr("portfoliosight.engine.suggest", "balanced_level"),
            _attr("portfoliosight.engine.suggest", "suggested_level"),
            _attr("portfoliosight.engine.suggest", "DEFAULT_POINT"),
        )

    def test_fixture_stores_the_balanced_point_and_the_peak(tmp_path_factory):
        balanced_level, _, default_point = _fns()
        t = _fixture_tensor(tmp_path_factory)
        a = _arrays(t)
        ladder = t["ladder"]
        ly, lz = np.array(ladder["y"], float), np.array(ladder["z"], float)
        last = ly.shape[1] - 1
        assert last - 1 >= 8, f"the ladders have {last - 1} interior levels; at least 8 expected"
        assert default_point == "balanced" and ladder["default_point"] == "balanced"
        interior = 0
        for j in range(NX):
            level = _knee(ly[j], lz[j])
            assert balanced_level(ly[j], lz[j]) == level, f"column {j}: balanced_level != the knee"
            t_bal = ladder["t_balanced"][j]
            assert abs(t_bal * last - level) <= 1e-12, f"column {j}: t_balanced {t_bal} != {level}/{last}"
            assert ladder["y_balanced"][j] == ly[j, level], f"column {j}: y_balanced is not level {level}'s return"
            assert ladder["t_suggested"][j] == t_bal and ladder["y_suggested"][j] == ladder["y_balanced"][j]
            assert ly[j, -1] - 1e-12 <= ladder["y_suggested"][j] <= a.yf[j] + 1e-12, f"column {j}: unbracketed"
            assert lz[j, level] >= lz[j, 0], f"column {j}: the balanced point is less diversified than the frontier"
            if ladder["collapsed"][j]:
                assert level == 0, f"collapsed column {j} must suggest the frontier mix"
            interior += 0 < level < last
        assert interior >= NX // 2, f"only {interior} columns have a knee strictly inside the ladder"

    def test_constructed_ladders():
        balanced_level, suggested_level, _ = _fns()
        returns = np.array([0.10, 0.09, 0.08, 0.07, 0.06])
        # ENB rises fast and then flattens: the knee is level 1, well above the chord
        concave = np.array([5.0, 9.0, 10.0, 10.5, 11.0])
        assert balanced_level(returns, concave) == _knee(returns, concave) == 1
        # rises late (below the chord everywhere): nothing beats the frontier mix
        convex = np.array([5.0, 5.1, 5.3, 6.0, 11.0])
        assert balanced_level(returns, convex) == 0
        # a tie between levels 1 and 3 goes to level 1, which gives up less return (the returns
        # and ENBs are exact in binary, so the two distances are equal, not merely close)
        exact = np.array([0.5, 0.375, 0.25, 0.125, 0.0])
        tied = np.array([4.0, 6.0, 6.0, 8.0, 8.0])
        assert _knee(exact, tied) == 1 and balanced_level(exact, tied) == 1
        # no ENB gain (a collapsed ladder) and ENB gained for no return
        assert balanced_level(returns, np.full(5, 7.0)) == 0
        assert balanced_level(np.full(5, 0.08), concave) == 4
        # the peak point is the last level unless the ladder gains nothing
        assert suggested_level(returns, concave, "peak") == 4
        assert suggested_level(returns, concave, "balanced") == suggested_level(returns, concave) == 1
        assert suggested_level(returns, np.full(5, 7.0), "peak") == 0
        with pytest.raises(ValueError):
            suggested_level(returns, concave, "knee")
        with pytest.raises(ValueError):
            balanced_level(returns, concave[:4])
        with pytest.raises(ValueError):
            balanced_level(returns[:1], concave[:1])
        # rescaling either axis leaves the knee where it is (both axes run from 0 to 1)
        assert balanced_level(returns * 3.0, concave) == balanced_level(returns, concave * 2.0 + 1.0) == 1
