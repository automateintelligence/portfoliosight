"""A-PS-22 - window inclusion, the 126-row floor and the fixed exclusion templates.

Claim: a fund is included in a window only if it is served and its first return date is on or
before window_start + 0.10 * window_length; a window whose intersection sample has fewer than 126
rows is unavailable; every excluded fund appears in the tensor's excluded array with a reason that
is exactly one of the five spec 5.6 templates; a current mix with weight in excluded funds is
renormalized and the set-aside share is reported.

Pinned interface (the product must provide exactly this):
- scripts/build_tensor.py (shared CLI pin). When the window is unavailable it exits non-zero,
  writes no file at --out, and its output (stdout + stderr) contains "unavailable" and
  "not enough shared history".
- portfoliosight.engine.tensor.select_window(returns, lookback, asof, catalog=None) -> object with
  .status ("ready" | "unavailable"), .message (contains "not enough shared history" when
  unavailable), .funds (included ids, column order), .excluded (list of {"id", "reason"}) and
  .sample (the intersection DataFrame when ready). returns is the returns-parquet frame; catalog
  maps id -> manifest entry (shared pin: "status", "adjusted_through", "last_date", "reason");
  an entry whose status is not "ok" is not served; a stale entry with adjusted_through behind
  asof gets "corporate actions not yet verified after {adjusted_through}".
- portfoliosight.engine.tensor.renormalize_allocation(weights, included) -> (dict, set_aside):
  weights of included funds rescaled to sum 1, and the share of the original total set aside.
Reason strings: the spec 5.6 template, optionally prefixed "{ID}: " (spec 3.6 shows the prefixed
display form, spec 7 the bare one); {date} is ISO; {window} for lookback 5y is "5-year" or "5y".
The returns are simulated by the test on XNYS sessions (1,500 ending 2026-06-30), so "trading
days" means the same thing under either reading of the window rule.
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
        pytest.fail(f"A-PS-22 red: cannot import {module}: {type(exc).__name__}: {exc}")


def _attr(module: str, name: str):
    mod = _need(module)
    if not hasattr(mod, name):
        pytest.fail(f"A-PS-22 red: {module} has no attribute {name!r} (pinned interface)")
    return getattr(mod, name)


def _deps():
    if np is None or pd is None:
        pytest.fail("A-PS-22 red: numpy and pandas are not importable in this interpreter")


BUILD_CLI = ROOT / "scripts" / "build_tensor.py"
FIXTURE = ROOT / "tests" / "fixtures" / "synthetic_23.parquet"
NX, NY = 48, 32
TOL = 1e-6
_CACHE: dict = {}


def _run_cli(script: Path, args: list, timeout: int = 300):
    if not script.exists():
        pytest.fail(f"A-PS-22 red: {script.relative_to(ROOT)} does not exist")
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
        pytest.fail(f"A-PS-22 red: {script.name} did not finish within {timeout} s")


def _build(returns: Path, lookback: str, asof: str, out: Path, caps: Path | None = None) -> dict:
    """Build one tensor through the pinned CLI and return the parsed JSON."""
    args = ["--returns", returns, "--lookback", lookback, "--asof", asof, "--out", out]
    if caps is not None:
        args += ["--caps", caps]
    proc = _run_cli(BUILD_CLI, args)
    if proc.returncode != 0 or not Path(out).exists():
        pytest.fail(
            f"A-PS-22 red: build_tensor.py exit {proc.returncode}, file={Path(out).exists()}: "
            f"{proc.stderr[-1500:]}"
        )
    try:
        return json.loads(Path(out).read_text())
    except ValueError as exc:
        pytest.fail(f"A-PS-22 red: {out} is not JSON: {exc}")


def _fixture_frame():
    _deps()
    _need("pyarrow")
    if not FIXTURE.exists():
        pytest.fail(f"A-PS-22 red: fixture {FIXTURE.relative_to(ROOT)} does not exist")
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
        pytest.fail(f"A-PS-22 red: tensor lacks a spec 7 field or has a ragged array: {exc!r}")
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

    def test_a_ps_22_in_project_venv():
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
        assert proc.returncode == 0, "A-PS-22 is red inside the project virtualenv (output above)"

else:
    import re

    ASOF = "2026-06-30"
    ROWS, LENGTH = 1500, 1260
    START = ROWS - LENGTH  # first row of the 5y window
    DATE = r"\d{4}-\d{2}-\d{2}"
    TEMPLATES = [
        r"no data",
        rf"converted to an ETF; no data since {DATE}",
        rf"no data since {DATE}",
        rf"corporate actions not yet verified after {DATE}",
        rf"history starts {DATE}, not enough for the [0-9A-Za-z-]+ view",
    ]

    def _is_template(reason: str, fund: str) -> bool:
        bare = reason[len(fund) + 2 :] if reason.startswith(f"{fund}: ") else reason
        return any(re.fullmatch(t, bare) for t in TEMPLATES)

    def _bare(reason: str, fund: str) -> str:
        return reason[len(fund) + 2 :] if reason.startswith(f"{fund}: ") else reason

    def _sessions():
        _deps()
        xcals = _need("exchange_calendars")
        cal = xcals.get_calendar("XNYS")
        sessions = cal.sessions_in_range("2020-01-02", ASOF)
        index = pd.DatetimeIndex(
            sessions.tz_localize(None) if sessions.tz is not None else sessions
        )
        assert index[-1] == pd.Timestamp(ASOF) and len(index) >= ROWS
        return index[-ROWS:].rename("date")

    def _frame(ids, seed=2201):
        index = _sessions()
        rng = np.random.default_rng(seed)
        n = len(ids)
        load = rng.normal(0.0, 1.0, (n, 2)) * 0.005
        r = rng.normal(0.0, 1.0, (ROWS, 2)) @ load.T + rng.normal(0.0, 0.004, (ROWS, n)) + 0.0003
        return pd.DataFrame(r, index=index, columns=ids)

    def _boundary_frame():
        """Six full funds, NEAR starting at window_start + 0.09 len, LATE at + 0.11 len."""
        frame = _frame(["AAA", "BBB", "CCC", "DDD", "EEE", "FFF", "NEAR", "LATE"])
        near_row, late_row = START + int(0.09 * LENGTH), START + int(0.11 * LENGTH) + 1
        frame.iloc[:near_row, frame.columns.get_loc("NEAR")] = np.nan
        frame.iloc[:late_row, frame.columns.get_loc("LATE")] = np.nan
        return frame, frame.index[near_row], frame.index[late_row]

    def _short_frame(shared: int):
        """Three funds; GONE has returns only for the first `shared` rows of the window."""
        frame = _frame(["AAA", "BBB", "GONE"], seed=2202)
        frame.iloc[START + shared :, frame.columns.get_loc("GONE")] = np.nan
        return frame

    def test_cli_boundary_funds_and_reason_template(tmp_path):
        _need("pyarrow")
        frame, near_date, late_date = _boundary_frame()
        path = tmp_path / "boundary.parquet"
        frame.to_parquet(path)
        t = _build(path, "5y", ASOF, tmp_path / "boundary.json")
        funds = [f["id"] for f in t["universe"]["funds"]]
        excluded = {e["id"]: e["reason"] for e in t["universe"]["excluded"]}
        assert "NEAR" in funds, "the fund starting at +0.09 of the window must be included"
        assert "LATE" not in funds, "the fund starting at +0.11 of the window must be excluded"
        assert funds == ["AAA", "BBB", "CCC", "DDD", "EEE", "FFF", "NEAR"]
        assert list(excluded) == ["LATE"]
        reason = excluded["LATE"]
        iso = late_date.date().isoformat()
        allowed = {f"history starts {iso}, not enough for the {w} view" for w in ("5-year", "5y")}
        assert _bare(reason, "LATE") in allowed, f"reason not filled exactly: {reason!r}"
        for fund, text in excluded.items():
            assert _is_template(text, fund), f"reason outside the five templates: {text!r}"
        n = len(funds)
        vectors = list(t["frontier"]["w"]) + list(t["grid"]["w_div"])
        vectors += [w for col in t["grid"]["w"] for w in col if w is not None]
        assert len(vectors) > 96
        assert not [w for w in vectors if len(w) != n], "a weight vector carries an excluded fund"
        assert len(t["mu_s"]) == n and len(t["cov"]) == n
        # the sample is the intersection: it starts where NEAR starts
        assert t["lookback"]["rows"] == ROWS - (START + int(0.09 * LENGTH))
        lb = t["lookback"]
        inside = frame.loc[pd.Timestamp(lb["start"]) : pd.Timestamp(lb["end"]), funds].dropna()
        assert len(inside) == lb["rows"] and inside.index[0] == near_date
        assert lb["end"] == ASOF

    def test_cli_window_with_100_shared_rows_is_unavailable(tmp_path):
        _need("pyarrow")
        frame = _short_frame(100)
        assert len(frame.iloc[START:].dropna()) == 100
        path, out = tmp_path / "short.parquet", tmp_path / "short.json"
        frame.to_parquet(path)
        proc = _run_cli(
            BUILD_CLI, ["--returns", path, "--lookback", "5y", "--asof", ASOF, "--out", out]
        )
        text = proc.stdout + proc.stderr
        assert proc.returncode != 0, "a window with 100 shared rows must not build (exit 0 seen)"
        assert not out.exists(), "a tensor was written for a window with fewer than 126 rows"
        assert "Traceback" not in text, (
            f"the unavailable window crashed instead of reporting:\n{text[-800:]}"
        )
        assert "unavailable" in text and "not enough shared history" in text, text[-800:]

    def test_select_window_served_rule_templates_and_row_floor():
        _deps()
        select = _attr("portfoliosight.engine.tensor", "select_window")
        frame, near_date, late_date = _boundary_frame()
        frame = frame.assign(STALE=_frame(["STALE"], seed=2203)["STALE"])
        ok = {"status": "ok", "reason": None, "adjusted_through": ASOF, "last_date": ASOF}
        catalog = {c: dict(ok) for c in frame.columns}
        catalog["STALE"] = {
            "status": "stale",
            "reason": None,
            "adjusted_through": "2026-06-10",
            "last_date": ASOF,
        }
        sel = select(frame, "5y", pd.Timestamp(ASOF).date(), catalog)
        assert sel.status == "ready"
        funds = list(sel.funds)
        excluded = {e["id"]: e["reason"] for e in sel.excluded}
        assert funds == ["AAA", "BBB", "CCC", "DDD", "EEE", "FFF", "NEAR"]
        assert set(excluded) == {"LATE", "STALE"}
        assert "STALE" not in funds and "LATE" not in funds
        assert (
            _bare(excluded["STALE"], "STALE")
            == "corporate actions not yet verified after 2026-06-10"
        )
        iso = late_date.date().isoformat()
        assert _bare(excluded["LATE"], "LATE") in {
            f"history starts {iso}, not enough for the {w} view" for w in ("5-year", "5y")
        }
        for fund, text in excluded.items():
            assert _is_template(text, fund), f"reason outside the five templates: {text!r}"
        assert not _is_template("insufficient history", "LATE")  # the regex is not permissive
        sample = sel.sample
        assert list(sample.columns) == funds and not sample.isna().any().any()
        assert len(sample) == ROWS - (START + int(0.09 * LENGTH)) and sample.index[0] == near_date
        # the same STALE fund is included once it is served
        catalog["STALE"] = dict(ok)
        assert "STALE" in list(select(frame, "5y", pd.Timestamp(ASOF).date(), catalog).funds)

        asof = pd.Timestamp(ASOF).date()
        for shared, want in (
            (100, "unavailable"),
            (125, "unavailable"),
            (126, "ready"),
            (400, "ready"),
        ):
            sel = select(_short_frame(shared), "5y", asof, None)
            assert sel.status == want, (
                f"{shared} shared rows: status {sel.status!r}, expected {want!r}"
            )
            if want == "unavailable":
                assert "not enough shared history" in sel.message
                assert sel.status != "ready"
            else:
                assert len(sel.sample) == shared and list(sel.funds) == ["AAA", "BBB", "GONE"]

    def test_renormalized_allocation_reports_the_set_aside_share():
        _deps()
        renorm = _attr("portfoliosight.engine.tensor", "renormalize_allocation")
        included = ["AAA", "BBB", "CCC", "NEAR"]
        weights, set_aside = renorm({"AAA": 0.5, "LATE": 0.2, "CCC": 0.3}, included)
        assert abs(set_aside - 0.20) <= 1e-12
        assert abs(sum(weights.values()) - 1.0) <= 1e-12
        assert abs(weights["AAA"] - 0.625) <= 1e-12 and abs(weights["CCC"] - 0.375) <= 1e-12
        assert weights.get("LATE", 0.0) == 0.0 and not [k for k in weights if k not in included]
        # unit-free: dollar amounts give the same shares
        weights, set_aside = renorm({"AAA": 5000.0, "LATE": 2000.0, "CCC": 3000.0}, included)
        assert abs(set_aside - 0.20) <= 1e-12 and abs(weights["AAA"] - 0.625) <= 1e-12
        weights, set_aside = renorm({"AAA": 0.4, "BBB": 0.6}, included)
        assert set_aside == 0.0 and abs(weights["BBB"] - 0.6) <= 1e-12
