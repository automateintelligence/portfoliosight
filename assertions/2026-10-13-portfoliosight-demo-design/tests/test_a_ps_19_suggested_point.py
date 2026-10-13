"""A-PS-19 - the suggested point is bracketed; the standard-error walk stops at the first failure.

Claim: for every column y_div[j] <= y_sug[j] <= y_front[j]; on a collapsed ladder (k_div = -1)
y_sug = y_front; the walk uses g_k = mu_s'(w_front - w_k) and se_k = sqrt(252) sd(d) /
sqrt(T_eff/252) with d_t = (w_front - w_k)' r_t (omega-weighted for ew), and stops at the first
candidate with g_k > se_k even if a lower candidate would pass.

Pinned interface (the product must provide exactly this):
- scripts/build_tensor.py (shared CLI pin) and tests/fixtures/synthetic_23.parquet. The window's
  sample is the parquet rows dated lookback.start..lookback.end (inclusive) with a return for
  every included fund, and lookback.rows is their count; lookback.t_eff = rows for fixed windows.
- portfoliosight.engine.suggest.suggested_floor(w_front, y_front, cand_w, cand_y, mu_s, returns,
  omega=None) -> float. cand_w / cand_y are the column's feasible cells from the top down to
  k_div (empty for a collapsed ladder); returns is the T x N sample; omega=None is a fixed window
  (sd with ddof=1, T_eff = T); an omega vector (sums to 1) is the ew window: mean_w = sum(omega d),
  var = sum(omega (d - mean_w)^2) / (1 - sum(omega^2)), T_eff = 1 / sum(omega^2). Returns the
  floor of the last candidate that passed g_k <= se_k, or y_front when none did.
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

    def _se(d, omega=None) -> float:
        d = np.asarray(d, float)
        if omega is None:
            sd, t_eff = d.std(ddof=1), float(len(d))
        else:
            mean = omega @ d
            sd = float(np.sqrt(omega @ (d - mean) ** 2 / (1 - (omega**2).sum())))
            t_eff = 1.0 / (omega**2).sum()
        return float(np.sqrt(252.0) * sd / np.sqrt(t_eff / 252.0))

    def _fn():
        _deps()
        return _attr("portfoliosight.engine.suggest", "suggested_floor")

    def test_fixture_bracketing_and_walk(tmp_path_factory):
        t = _fixture_tensor(tmp_path_factory)
        a = _arrays(t)
        frame = _fixture_frame()
        ids = [f["id"] for f in t["universe"]["funds"]]
        lb = t["lookback"]
        assert lb["id"] == "5y"
        missing = [i for i in ids if i not in frame.columns]
        assert not missing, f"tensor funds missing from the fixture parquet: {missing}"
        window = frame.loc[pd.Timestamp(lb["start"]) : pd.Timestamp(lb["end"]), ids].dropna()
        assert len(window) == lb["rows"], (
            f"lookback.rows = {lb['rows']} but the parquet has {len(window)} complete rows in "
            f"{lb['start']}..{lb['end']}"
        )
        assert lb["rows"] >= 126 and float(lb["t_eff"]) == float(lb["rows"])
        r = window.to_numpy()

        collapsed = walked = unambiguous = 0
        for j in range(NX):
            assert not a.y_sug[j] < a.y_div[j] - 1e-12, f"y_sug[{j}] below y_div"
            assert not a.y_sug[j] > a.yf[j] + 1e-12, f"y_sug[{j}] above y_front"
            kd = a.k_div[j]
            if kd == -1:
                assert a.y_sug[j] == a.yf[j], f"collapsed column {j}: y_sug must equal y_front"
                collapsed += 1
                continue
            ladder = [k for k in range(NY - 1, kd - 1, -1) if a.gw[j][k] is not None]
            assert ladder and ladder[-1] == kd
            expected, exact = a.yf[j], True
            chosen = successor = None
            for k in ladder:
                diff = a.wf[j] - np.asarray(a.gw[j][k], float)
                g, se = float(a.mu @ diff), _se(r @ diff)
                if abs(g - se) <= 1e-9 * max(se, 1e-12):
                    exact = False  # knife edge: do not judge this column on rounding
                if g > se:
                    successor = (k, g, se)
                    break
                expected, chosen = a.gy[k], (k, g, se)
            walked += 1
            if not exact:
                continue
            unambiguous += 1
            assert a.y_sug[j] == expected, (
                f"column {j}: y_sug = {a.y_sug[j]!r}, the walk gives {expected!r} "
                f"(last pass {chosen}, first failure {successor})"
            )
            if chosen is not None:
                assert chosen[1] <= chosen[2]
            if successor is not None:
                assert successor[1] > successor[2]
                lower_passes = [k for k in ladder if k < successor[0]]
                assert a.y_sug[j] not in [a.gy[k] for k in lower_passes], (
                    f"column {j} skipped a failure"
                )
            else:
                assert a.y_sug[j] == a.gy[kd]
        assert collapsed + walked == NX
        assert unambiguous >= walked - 4, (
            f"{walked - unambiguous} knife-edge columns: nothing proven"
        )

    def _three_candidate_column():
        rng = np.random.default_rng(1901)
        t_rows, n = 600, 4
        r = rng.normal(0.0, 1.0, (t_rows, n)) * np.array([0.004, 0.008, 0.012, 0.02])
        w_front = np.array([0.7, 0.3, 0.0, 0.0])
        cands = [
            np.array([0.6, 0.3, 0.1, 0.0]),
            np.array([0.5, 0.3, 0.1, 0.1]),
            np.array([0.3, 0.2, 0.1, 0.4]),
        ]
        diffs = np.array([w_front - c for c in cands])
        ses = np.array([_se(r @ d) for d in diffs])
        return r, w_front, cands, diffs, ses

    def test_constructed_column_stops_at_first_failure():
        fn = _fn()
        r, w_front, cands, diffs, ses = _three_candidate_column()
        y_front, floors = 0.09, [0.08, 0.07, 0.06]
        mu_s = np.linalg.lstsq(diffs, ses * np.array([0.5, 1.5, 0.5]), rcond=None)[0]
        g = diffs @ mu_s
        assert g[0] <= ses[0] and g[1] > ses[1] and g[2] <= ses[2]  # pass, fail, would pass
        got = fn(w_front, y_front, cands, floors, mu_s, r)
        assert got == floors[0], f"walk returned {got!r}, expected candidate 1's floor {floors[0]}"
        assert got != floors[2] and got != floors[1] and got != y_front

        all_pass = np.linalg.lstsq(diffs, ses * 0.5, rcond=None)[0]
        assert fn(w_front, y_front, cands, floors, all_pass, r) == floors[2]
        none_pass = np.linalg.lstsq(diffs, ses * np.array([1.5, 0.5, 0.5]), rcond=None)[0]
        assert fn(w_front, y_front, cands, floors, none_pass, r) == y_front
        assert fn(w_front, y_front, [], [], mu_s, r) == y_front  # collapsed ladder
        # the threshold is one standard error with ddof = 1 over T rows: 2% either side flips it
        for scale, expected in ((0.98, floors[0]), (1.02, y_front)):
            mu = np.linalg.lstsq(diffs[:1], ses[:1] * scale, rcond=None)[0]
            assert fn(w_front, y_front, cands[:1], floors[:1], mu, r) == expected, f"scale {scale}"

    def test_ew_window_uses_t_eff_and_weighted_deviation():
        fn = _fn()
        rng = np.random.default_rng(1902)
        t_rows, n = 1260, 3
        vol = np.linspace(0.002, 0.02, t_rows)[:, None]  # recent rows are much noisier
        r = rng.normal(0.0, 1.0, (t_rows, n)) * vol
        omega = 0.5 ** ((t_rows - 1 - np.arange(t_rows)) / 252.0)
        omega /= omega.sum()
        t_eff = 1.0 / (omega**2).sum()
        assert t_eff < 0.75 * t_rows  # T_eff differs from T
        w_front, cand, y_front, floor = (
            np.array([0.8, 0.2, 0.0]),
            np.array([0.4, 0.3, 0.3]),
            0.08,
            0.05,
        )
        diff = w_front - cand
        d = r @ diff
        se_ew = _se(d, omega)
        mean = omega @ d
        sd_w = np.sqrt(omega @ (d - mean) ** 2 / (1 - (omega**2).sum()))
        se_with_t = np.sqrt(252.0) * sd_w / np.sqrt(t_rows / 252.0)  # the wrong one: T, not T_eff
        se_plain = _se(d)  # the wrong one: ignores omega altogether
        assert se_with_t < 0.9 * se_ew and abs(se_plain - se_ew) > 0.05 * se_ew

        def mu_for(g):
            return diff * g / (diff @ diff)

        # between the two standard errors: passes only when T_eff is used
        between = float(np.sqrt(se_with_t * se_ew))
        assert se_with_t < between < se_ew
        got = fn(w_front, y_front, [cand], [floor], mu_for(between), r, omega=omega)
        assert got == floor, "ew walk must compare the give-up with the T_eff standard error"
        assert got != y_front
        # 2% either side of the ew standard error flips the stop
        assert fn(w_front, y_front, [cand], [floor], mu_for(0.98 * se_ew), r, omega=omega) == floor
        assert (
            fn(w_front, y_front, [cand], [floor], mu_for(1.02 * se_ew), r, omega=omega) == y_front
        )
        # changing T_eff (uniform weights: T_eff = T) changes the stop for the same give-up
        uniform = np.full(t_rows, 1.0 / t_rows)
        se_uniform = _se(d, uniform)
        assert abs(se_uniform - se_plain) <= 1e-12
        g = 0.5 * (se_uniform + se_ew)
        lo_se, hi_se = sorted((se_uniform, se_ew))
        assert lo_se < g < hi_se
        ew_result = fn(w_front, y_front, [cand], [floor], mu_for(g), r, omega=omega)
        uniform_result = fn(w_front, y_front, [cand], [floor], mu_for(g), r, omega=uniform)
        assert ew_result != uniform_result
        assert ew_result == (floor if g <= se_ew else y_front)
        assert uniform_result == fn(w_front, y_front, [cand], [floor], mu_for(g), r)
