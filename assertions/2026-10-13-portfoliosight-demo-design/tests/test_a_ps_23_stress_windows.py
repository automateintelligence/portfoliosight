"""A-PS-23 - stress returns are never fabricated.

Claim: for each of gfc2008, covid2020, rates2022 with the exact spec 4.10 dates, the per-fund r
is the buy-and-hold total return from the last price on or before the start to the last price on
or before the end, and is null whenever the fund lacks a price within 3 trading days of either
endpoint.

Pinned interface (the product must provide exactly this):
- portfoliosight.engine.stress.stress_returns(tr_by_fund) -> the tensor's "stress" object:
  {"gfc2008": {"label", "start", "end", "r": [float | None per fund, mapping order]}, ...}.
  tr_by_fund maps fund id -> pandas Series of tr_index over a tz-naive DatetimeIndex (dates the
  fund has a price). "Within 3 trading days": at most 3 XNYS sessions lie after the last price
  date, up to and including the endpoint.
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
        pytest.fail(f"A-PS-23 red: cannot import {module}: {type(exc).__name__}: {exc}")


def _attr(module: str, name: str):
    mod = _need(module)
    if not hasattr(mod, name):
        pytest.fail(f"A-PS-23 red: {module} has no attribute {name!r} (pinned interface)")
    return getattr(mod, name)


def _deps():
    if np is None or pd is None:
        pytest.fail("A-PS-23 red: numpy and pandas are not importable in this interpreter")


BUILD_CLI = ROOT / "scripts" / "build_tensor.py"
FIXTURE = ROOT / "tests" / "fixtures" / "synthetic_23.parquet"
NX, NY = 48, 32
TOL = 1e-6
_CACHE: dict = {}


def _run_cli(script: Path, args: list, timeout: int = 300):
    if not script.exists():
        pytest.fail(f"A-PS-23 red: {script.relative_to(ROOT)} does not exist")
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
        pytest.fail(f"A-PS-23 red: {script.name} did not finish within {timeout} s")


def _build(returns: Path, lookback: str, asof: str, out: Path, caps: Path | None = None) -> dict:
    """Build one tensor through the pinned CLI and return the parsed JSON."""
    args = ["--returns", returns, "--lookback", lookback, "--asof", asof, "--out", out]
    if caps is not None:
        args += ["--caps", caps]
    proc = _run_cli(BUILD_CLI, args)
    if proc.returncode != 0 or not Path(out).exists():
        pytest.fail(
            f"A-PS-23 red: build_tensor.py exit {proc.returncode}, file={Path(out).exists()}: "
            f"{proc.stderr[-1500:]}"
        )
    try:
        return json.loads(Path(out).read_text())
    except ValueError as exc:
        pytest.fail(f"A-PS-23 red: {out} is not JSON: {exc}")


def _fixture_frame():
    _deps()
    _need("pyarrow")
    if not FIXTURE.exists():
        pytest.fail(f"A-PS-23 red: fixture {FIXTURE.relative_to(ROOT)} does not exist")
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
        pytest.fail(f"A-PS-23 red: tensor lacks a spec 7 field or has a ragged array: {exc!r}")
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

    def test_a_ps_23_in_project_venv():
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
        assert proc.returncode == 0, "A-PS-23 is red inside the project virtualenv (output above)"

else:
    WINDOWS = {
        "gfc2008": ("2008 financial crisis", "2008-09-01", "2009-03-09"),
        "covid2020": ("COVID crash, Feb–Mar 2020", "2020-02-19", "2020-03-23"),
        "rates2022": ("2022 rate shock", "2022-01-03", "2022-10-12"),
    }

    def _series(seed: int, start="2007-01-02", end="2023-12-29"):
        index = pd.bdate_range(start, end, name="date")
        rng = np.random.default_rng(seed)
        return pd.Series(np.cumprod(1.0 + rng.normal(0.0003, 0.012, len(index))), index=index)

    def _at(series, day: str) -> float:
        return float(series[series.index <= pd.Timestamp(day)].iloc[-1])

    def _own(series, start: str, end: str) -> float:
        return _at(series, end) / _at(series, start) - 1.0

    def _funds():
        full = _series(2301)
        late = _series(2302, start="2010-01-04")
        gap = _series(2303)
        # ten sessions without a price around 2020-02-19 (2020-02-17 is a market holiday)
        gap = gap[(gap.index < "2020-02-10") | (gap.index > "2020-02-24")]
        to_oct7 = _series(2304, end="2022-10-07")  # 3 sessions before 2022-10-12
        to_oct6 = _series(2305, end="2022-10-06")  # 4 sessions before: one too many
        to_sep30 = _series(2306, end="2022-09-30")
        return {
            "FULL": full,
            "LATE": late,
            "GAP": gap,
            "OCT7": to_oct7,
            "OCT6": to_oct6,
            "SEP30": to_sep30,
        }

    def test_stress_windows_and_null_rule():
        _deps()
        fn = _attr("portfoliosight.engine.stress", "stress_returns")
        _need("exchange_calendars")
        funds = _funds()
        ids = list(funds)
        out = fn(funds)
        assert set(out) == set(WINDOWS), f"stress windows: {sorted(out)}"
        for wid, (label, start, end) in WINDOWS.items():
            assert (
                out[wid]["label"] == label and out[wid]["start"] == start and out[wid]["end"] == end
            )
            assert len(out[wid]["r"]) == len(ids)
        r = {wid: dict(zip(ids, out[wid]["r"])) for wid in WINDOWS}

        numbers = 0
        for wid, (_, start, end) in WINDOWS.items():  # full history: a number in all three windows
            value = r[wid]["FULL"]
            assert value is not None, f"{wid}: full-history fund has no return"
            assert abs(value - _own(funds["FULL"], start, end)) <= 1e-12, f"{wid}: wrong return"
            numbers += 1
        # 2008-09-01 is a holiday: the start price is the last one on or before it
        weekend = funds["FULL"].drop(pd.Timestamp("2008-09-01"), errors="ignore")
        again = fn({"FULL": weekend})["gfc2008"]["r"][0]
        assert again is not None and abs(again - _own(weekend, "2008-09-01", "2009-03-09")) <= 1e-12
        assert abs(again - (_at(weekend, "2009-03-09") / _at(weekend, "2008-08-29") - 1.0)) <= 1e-12

        assert r["gfc2008"]["LATE"] is None, "a fund with no 2008 prices got a 2008 return"
        for wid in ("covid2020", "rates2022"):
            _, start, end = WINDOWS[wid]
            assert r[wid]["LATE"] is not None
            assert abs(r[wid]["LATE"] - _own(funds["LATE"], start, end)) <= 1e-12
            numbers += 1

        assert r["covid2020"]["GAP"] is None, "a 10-session gap over the start must give null"
        fabricated = _at(funds["GAP"], "2020-03-23") / _at(funds["GAP"], "2020-02-19") - 1.0
        assert r["covid2020"]["GAP"] != fabricated  # not computed from the price 7 sessions back
        for wid in ("gfc2008", "rates2022"):
            _, start, end = WINDOWS[wid]
            assert abs(r[wid]["GAP"] - _own(funds["GAP"], start, end)) <= 1e-12
            numbers += 1

        assert r["rates2022"]["OCT7"] is not None, (
            "a last price 3 sessions before the end is covered"
        )
        assert (
            abs(r["rates2022"]["OCT7"] - _own(funds["OCT7"], "2022-01-03", "2022-10-12")) <= 1e-12
        )
        assert (
            abs(
                r["rates2022"]["OCT7"]
                - (float(funds["OCT7"].iloc[-1]) / _at(funds["OCT7"], "2022-01-03") - 1.0)
            )
            <= 1e-12
        )
        numbers += 1
        assert r["rates2022"]["OCT6"] is None, (
            "a last price 4 sessions before the end must give null"
        )
        assert r["rates2022"]["SEP30"] is None, (
            "a fund ending 2022-09-30 must give null for rates2022"
        )
        for fund in ("OCT7", "OCT6", "SEP30"):
            for wid in ("gfc2008", "covid2020"):
                _, start, end = WINDOWS[wid]
                assert abs(r[wid][fund] - _own(funds[fund], start, end)) <= 1e-12
                numbers += 1
        nulls = [(wid, f) for wid in WINDOWS for f in ids if r[wid][f] is None]
        assert sorted(nulls) == sorted(
            [
                ("gfc2008", "LATE"),
                ("covid2020", "GAP"),
                ("rates2022", "OCT6"),
                ("rates2022", "SEP30"),
            ]
        ), f"null pattern: {nulls}"
        assert numbers == 14 and numbers + len(nulls) == 18

    def test_start_side_three_session_boundary():
        _deps()
        fn = _attr("portfoliosight.engine.stress", "stress_returns")
        base = _series(2307)
        # sessions before 2022-01-03: 12-31, 12-30, 12-29, 12-28 (all open)
        three = base[(base.index <= "2021-12-29") | (base.index > "2022-01-03")]  # 3 sessions back
        four = base[(base.index <= "2021-12-28") | (base.index > "2022-01-03")]  # 4 sessions back
        out = fn({"THREE": three, "FOUR": four})["rates2022"]["r"]
        expected = (
            _at(three, "2022-10-12") / float(three[three.index <= "2021-12-29"].iloc[-1]) - 1.0
        )
        assert out[0] is not None and abs(out[0] - expected) <= 1e-12
        assert out[1] is None, "a start price 4 sessions before the window start must give null"
        assert out[0] != out[1]
