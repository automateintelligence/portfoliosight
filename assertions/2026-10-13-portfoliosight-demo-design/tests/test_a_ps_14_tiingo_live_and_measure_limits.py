"""A-PS-14 — the Tiingo adapter returns the four fields live and measure-limits records the
tier (LIVE).

Claim: against the real API the adapter returns >= 250 rows with close, adjClose, divCash,
splitFactor for VTI and for VBIAX, and `download --mode measure-limits` writes
meta/provider_limits.json with provider, tier, req_per_hour, req_per_day,
unique_symbols_per_month, measured_on, method.

Pinned interface (the product must provide exactly this):
- `portfoliosight.data.providers.tiingo.TiingoProvider().fetch_daily(symbol, start, end)` with
  the real `TIINGO_API_KEY` from the environment; `end=None` means "through the latest row". The
  frame is in the provider format of spec 5.1: tz-naive `DatetimeIndex` named `date`, columns
  `close`, `adj_close`, `div_cash`, `split_factor` (Tiingo's close, adjClose, divCash,
  splitFactor).
- `python -m portfoliosight.data.download --mode measure-limits`, run from the repo root with
  `PS_STORE=local`, `PS_LOCAL_STORE_DIR=<dir>`, `PS_LIVE_TESTS=1` and `TIINGO_API_KEY`; exit 0,
  and the key `meta/provider_limits.json` readable through
  `portfoliosight.data.store.LocalStore(<dir>).get(...)`: a JSON object with the seven keys;
  `provider` is "tiingo", `measured_on` an ISO date (today, local or UTC), `method` "probe" or
  "documented". Neither the command's output nor the file contains the API key.
"""

from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

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
        pytest.fail(f"A-PS-14 red: cannot import {module}: {type(exc).__name__}: {exc}")


COLUMNS = ("close", "adj_close", "div_cash", "split_factor")
LIMIT_KEYS = (
    "provider",
    "tier",
    "req_per_hour",
    "req_per_day",
    "unique_symbols_per_month",
    "measured_on",
    "method",
)
START = date(2025, 1, 2)  # covers the December 2025 VBIAX distribution and > 250 sessions


def _key() -> str:
    key = os.environ.get("TIINGO_API_KEY", "")
    if not key:
        pytest.fail(
            "A-PS-14 red: environment variable TIINGO_API_KEY is not set "
            "(load ~/.secrets/portfoliosight.env before running the gate)"
        )
    return key


def _scrub(text: str, key: str) -> str:
    return text.replace(key, "<TIINGO_API_KEY>") if key else text


_FRAMES: dict = {}


def _live_frame(symbol: str):
    key = _key()
    pd = _need("pandas")
    if symbol in _FRAMES:
        return pd, _FRAMES[symbol]
    mod = _need("portfoliosight.data.providers.tiingo")
    cls = getattr(mod, "TiingoProvider", None)
    assert cls is not None, "portfoliosight.data.providers.tiingo.TiingoProvider is missing"
    try:
        frame = cls().fetch_daily(symbol, START, None)
    except Exception as exc:
        pytest.fail(
            f"A-PS-14 red: live fetch_daily({symbol}) raised {type(exc).__name__}: "
            + _scrub(str(exc), key)[:500]
        )
    assert isinstance(frame, pd.DataFrame), f"{symbol}: not a DataFrame ({type(frame)})"
    _FRAMES[symbol] = frame
    return pd, frame


def _check_frame(pd, frame, symbol: str) -> None:
    # Must-not-contain: a frame missing any of the four columns.
    missing = [col for col in COLUMNS if col not in frame.columns]
    assert not missing, f"{symbol}: live frame is missing column(s) {missing}"
    assert len(frame) >= 250, f"{symbol}: {len(frame)} rows, expected at least 250"
    for col in COLUMNS:
        nulls = int(frame[col].isna().sum())
        assert nulls == 0, f"{symbol}: {nulls} null value(s) in {col}"
    index = frame.index
    assert isinstance(index, pd.DatetimeIndex), f"{symbol}: index is {type(index).__name__}"
    assert index.tz is None, f"{symbol}: dates must be tz-naive"
    assert index.is_monotonic_increasing and index.is_unique, (
        f"{symbol}: dates are not strictly increasing"
    )
    assert index[0] >= pd.Timestamp(START), f"{symbol}: first row {index[0]} is before the start"
    assert (index == index.normalize()).all(), f"{symbol}: dates carry a time of day"
    assert (frame["close"] > 0).all() and (frame["adj_close"] > 0).all()
    assert (frame["div_cash"] >= 0).all() and (frame["split_factor"] > 0).all()
    assert frame["close"].nunique() > 100, f"{symbol}: close does not look like market data"


if _OUTER:

    def test_a_ps_14_in_project_venv():
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
        assert proc.returncode == 0, "A-PS-14 is red inside the project virtualenv (output above)"

else:

    def test_vti_live_frame():
        pd, frame = _live_frame("VTI")
        _check_frame(pd, frame, "VTI")

    def test_vbiax_live_frame_has_the_december_2025_distribution():
        pd, frame = _live_frame("VBIAX")
        _check_frame(pd, frame, "VBIAX")
        december = frame[(frame.index >= "2025-12-01") & (frame.index <= "2025-12-31")]
        assert len(december) >= 15, f"VBIAX: only {len(december)} rows dated 2025-12"
        paid = december[december["div_cash"] > 0]
        assert len(paid) >= 1, "VBIAX: no div_cash > 0 row dated 2025-12"
        assert not (frame["div_cash"] > 0).all(), "VBIAX: div_cash is positive on every row"
        _, vti = _live_frame("VTI")
        shared = frame.index.intersection(vti.index)
        assert len(shared) >= 250
        assert not (
            frame.loc[shared, "close"].to_numpy() == vti.loc[shared, "close"].to_numpy()
        ).all(), "VBIAX and VTI came back with identical closes"

    def test_measure_limits_writes_provider_limits(tmp_path):
        key = _key()
        store_mod = _need("portfoliosight.data.store")
        _need("portfoliosight.data.download")
        local_store = getattr(store_mod, "LocalStore", None)
        assert local_store is not None, "portfoliosight.data.store.LocalStore is missing"
        store_dir = tmp_path / "store"
        store_dir.mkdir()
        env = dict(
            os.environ,
            PS_STORE="local",
            PS_LOCAL_STORE_DIR=str(store_dir),
            PS_LIVE_TESTS="1",
        )
        env.pop("PS_GATE_INNER", None)
        env.pop("PYTEST_DISABLE_PLUGIN_AUTOLOAD", None)
        today_before = {date.today(), datetime.now(timezone.utc).date()}
        try:
            proc = subprocess.run(
                [sys.executable, "-m", "portfoliosight.data.download", "--mode", "measure-limits"],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                timeout=900,
            )
        except subprocess.TimeoutExpired:
            pytest.fail("A-PS-14 red: download --mode measure-limits did not finish in 900 s")
        output = proc.stdout + "\n" + proc.stderr
        shown = _scrub(output, key)[-3000:]
        code = proc.returncode  # plain values only: pytest prints what an assert compares
        assert code == 0, f"measure-limits exited {code}:\n{shown}"
        key_in_output = key in output
        assert not key_in_output, "the measure-limits output contains the Tiingo API key"

        store = local_store(store_dir)
        assert store.exists("meta/provider_limits.json"), (
            f"meta/provider_limits.json was not written to the local store:\n{shown}"
        )
        raw = store.get("meta/provider_limits.json")
        key_in_file = key.encode() in raw
        assert not key_in_file, "meta/provider_limits.json contains the Tiingo API key"
        limits = json.loads(raw)
        assert isinstance(limits, dict), "meta/provider_limits.json is not a JSON object"
        missing = [name for name in LIMIT_KEYS if name not in limits]
        assert not missing, f"meta/provider_limits.json is missing {missing}"
        assert limits["provider"] == "tiingo", f"provider is {limits['provider']!r}"
        # Must-not-contain: a limits file with tier empty.
        assert isinstance(limits["tier"], str), f"tier is {limits['tier']!r}"
        assert limits["tier"].strip() != "", "tier is empty"
        assert limits["method"] in ("probe", "documented"), f"method is {limits['method']!r}"
        for name in ("req_per_hour", "req_per_day", "unique_symbols_per_month"):
            value = limits[name]
            assert type(value) is int, f"{name} is {value!r}, not an integer"
            assert value > 0, f"{name} is {value}, not positive"
        assert limits["req_per_hour"] <= limits["req_per_day"], "hourly limit above the daily one"
        today_after = {date.today(), datetime.now(timezone.utc).date()}
        allowed = {d.isoformat() for d in today_before | today_after}
        assert limits["measured_on"] in allowed, (
            f"measured_on is {limits['measured_on']!r}, expected today ({sorted(allowed)})"
        )
