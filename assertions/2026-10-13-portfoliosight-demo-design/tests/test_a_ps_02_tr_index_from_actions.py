"""A-PS-02 — the total-return index is rebuilt from close, dividends and splits, not from adjClose.

Claim: for every recorded provider fixture, the tr_index the adapter builds from close, divCash and
splitFactor alone reproduces the provider's adjClose ratio day by day within 1e-5, and the adapter
does not read adjClose to build it.

Pinned interface (the product must provide exactly this):
- Recorded raw Tiingo JSON under `tests/fixtures/provider/`: one `*.json` per ticker whose file stem
  starts (case-insensitive) with `aapl`, `nvda`, `uso`, `vti`, `vbiax`; each a JSON list of rows
  `{"date", "close", "adjClose", "divCash", "splitFactor"}` exactly as Tiingo returns them. AAPL
  holds 2020-08-31 (splitFactor 4), NVDA 2024-06-10 (10), USO 2020-04-29 (0.125); VTI and VBIAX
  are full histories (VTI from 2001-05-31 or earlier; VBIAX including a December 2025 distribution).
- `portfoliosight.data.providers.tiingo.TiingoProvider()`; `fetch_daily(symbol, start, end)` does a
  `requests` GET on `https://api.tiingo.com/tiingo/daily/{symbol}/prices` and returns a frame with a
  tz-naive `DatetimeIndex` named `date` and float columns `close, adj_close, div_cash, split_factor`.
- `portfoliosight.data.returns.build_tr_index(frame) -> pandas.Series`: `frame` is a provider frame
  as above (the `adj_close` column may be absent); the result has the same index, is 1.0 on the
  first row and follows spec section 4.1.
"""

from __future__ import annotations

import importlib
import json
import os
import re
import subprocess
import sys
from datetime import date
from pathlib import Path
from urllib.parse import parse_qs, urlparse

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
        pytest.fail(f"A-PS-02 red: cannot import {module}: {type(exc).__name__}: {exc}")


TOL = 1e-5
FIXTURE_DIR = ROOT / "tests" / "fixtures" / "provider"
SPLIT_DAYS = {
    "aapl": ("2020-08-31", 4.0),
    "nvda": ("2024-06-10", 10.0),
    "uso": ("2020-04-29", 0.125),
}
DIVIDEND_FIXTURES = ("vti", "vbiax")
TICKERS = ("aapl", "nvda", "uso", "vti", "vbiax")
PRICES_URL = re.compile(r"^https://api\.tiingo\.com/tiingo/daily/([^/?]+)/prices")


def _fixture_rows(ticker: str) -> list[dict]:
    if not FIXTURE_DIR.is_dir():
        pytest.fail(f"A-PS-02 red: fixture directory missing: {FIXTURE_DIR.relative_to(ROOT)}")
    hits = sorted(p for p in FIXTURE_DIR.glob("*.json") if p.stem.lower().startswith(ticker))
    if not hits:
        pytest.fail(
            f"A-PS-02 red: no recorded Tiingo fixture {FIXTURE_DIR.relative_to(ROOT)}/{ticker}*.json"
        )
    rows = json.loads(hits[0].read_text())
    ok = isinstance(rows, list) and len(rows) >= 5 and isinstance(rows[0], dict)
    keys = {"date", "close", "adjClose", "divCash", "splitFactor"}
    if not ok or not all(keys <= set(r) for r in rows):
        pytest.fail(
            f"A-PS-02 red: {hits[0].name} is not a raw Tiingo list of rows with keys {keys}"
        )
    rows = sorted(rows, key=lambda r: r["date"])
    days = [r["date"][:10] for r in rows]
    assert len(set(days)) == len(days), f"{hits[0].name}: duplicate dates in the fixture"
    return rows


def _replay(responses, rows_by_ticker: dict[str, list[dict]], seen: list):
    """A `responses` callback that answers like Tiingo's prices endpoint from the fixtures."""

    def callback(request):
        url = urlparse(request.url)
        ticker = PRICES_URL.match(request.url).group(1).lower()
        query = parse_qs(url.query)
        start = query.get("startDate", ["0000-00-00"])[0]
        end = query.get("endDate", ["9999-99-99"])[0] or "9999-99-99"
        seen.append((ticker, start, end))
        if ticker not in rows_by_ticker:
            return (404, {}, json.dumps({"detail": "Not found."}))
        body = [r for r in rows_by_ticker[ticker] if start <= r["date"][:10] <= end]
        return (200, {"Content-Type": "application/json"}, json.dumps(body))

    return callback


def _fetch_frame(ticker: str, rows: list[dict], monkeypatch):
    """Go through the real adapter with HTTP replayed from the recorded fixture."""
    responses = _need("responses")
    tiingo = _need("portfoliosight.data.providers.tiingo")
    monkeypatch.setenv("TIINGO_API_KEY", "gate-test-key")
    seen: list = []
    start = date.fromisoformat(rows[0]["date"][:10])
    with responses.RequestsMock(assert_all_requests_are_fired=False) as mock:
        mock.add_callback(
            responses.GET, PRICES_URL, callback=_replay(responses, {ticker: rows}, seen)
        )
        try:
            frame = tiingo.TiingoProvider().fetch_daily(ticker.upper(), start, None)
        except Exception as exc:
            pytest.fail(f"A-PS-02 red: TiingoProvider.fetch_daily({ticker.upper()}) raised {exc!r}")
    assert seen, "the adapter made no request to the Tiingo prices endpoint (must use requests)"
    return frame


def _check_frame(ticker: str, frame, rows: list[dict]):
    pd = _need("pandas")
    np = _need("numpy")
    assert isinstance(frame, pd.DataFrame), f"{ticker}: fetch_daily must return a DataFrame"
    assert isinstance(frame.index, pd.DatetimeIndex), f"{ticker}: index must be a DatetimeIndex"
    assert frame.index.tz is None, f"{ticker}: index must be tz-naive"
    for column in ("close", "adj_close", "div_cash", "split_factor"):
        assert column in frame.columns, f"{ticker}: provider frame lacks column {column}"
    assert len(frame) == len(rows), f"{ticker}: {len(frame)} rows from {len(rows)} fixture rows"
    days = [d.strftime("%Y-%m-%d") for d in frame.index]
    assert days == [r["date"][:10] for r in rows], f"{ticker}: frame dates differ from the fixture"
    for column, key in (
        ("close", "close"),
        ("div_cash", "divCash"),
        ("split_factor", "splitFactor"),
    ):
        want = np.array([float(r[key]) for r in rows])
        got = frame[column].to_numpy(dtype=float)
        assert np.allclose(got, want, rtol=1e-12, atol=0.0), f"{ticker}: {column} != fixture {key}"


def _tr(returns_mod, frame, label: str):
    pd = _need("pandas")
    np = _need("numpy")
    try:
        tr = returns_mod.build_tr_index(frame)
    except Exception as exc:
        pytest.fail(f"A-PS-02 red: build_tr_index failed on {label}: {exc!r}")
    assert isinstance(tr, pd.Series), f"{label}: build_tr_index must return a Series"
    assert len(tr) == len(frame), f"{label}: tr_index length differs from the frame"
    values = tr.to_numpy(dtype=float)
    assert np.isfinite(values).all(), f"{label}: tr_index has non-finite values"
    assert (values > 0).all(), f"{label}: tr_index must be positive"
    assert values[0] == 1.0, f"{label}: tr_index must be 1.0 on the first row, got {values[0]}"
    return values


if _OUTER:

    def test_a_ps_02_in_project_venv():
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
        assert proc.returncode == 0, "A-PS-02 is red inside the project virtualenv (output above)"

else:

    def test_fixtures_hold_the_named_corporate_actions():
        """Non-triviality of the setup: each fixture really contains the action the spec names."""
        for ticker, (day, factor) in SPLIT_DAYS.items():
            rows = _fixture_rows(ticker)
            by_day = {r["date"][:10]: r for r in rows}
            assert day in by_day, f"{ticker}: fixture lacks the split day {day}"
            assert float(by_day[day]["splitFactor"]) == factor, f"{ticker}: splitFactor on {day}"
            assert by_day[day]["splitFactor"] != 1, f"{ticker}: no split recorded on {day}"
            assert rows[0]["date"][:10] != day, f"{ticker}: split day has no previous day to pair"
        for ticker in DIVIDEND_FIXTURES:
            rows = _fixture_rows(ticker)
            assert len(rows) >= 5000, f"{ticker}: fixture is not a full history ({len(rows)} rows)"
            assert sum(1 for r in rows[1:] if float(r["divCash"]) > 0) >= 20, f"{ticker}: dividends"
        assert _fixture_rows("vti")[0]["date"][:10] <= "2001-06-01", "VTI must start at inception"
        december = [r for r in _fixture_rows("vbiax") if r["date"][:7] == "2025-12"]
        assert any(float(r["divCash"]) > 0 for r in december), (
            "VBIAX lacks its Dec-2025 distribution"
        )

    @pytest.mark.parametrize("ticker", TICKERS)
    def test_tr_index_reproduces_adjclose_ratio_every_day(ticker, monkeypatch):
        returns_mod = _need("portfoliosight.data.returns")
        np = _need("numpy")
        rows = _fixture_rows(ticker)
        frame = _fetch_frame(ticker, rows, monkeypatch)
        _check_frame(ticker, frame, rows)
        tr = _tr(returns_mod, frame, ticker)

        close = np.array([float(r["close"]) for r in rows])
        adj = np.array(
            [float(r["adjClose"]) for r in rows]
        )  # read from the raw JSON, not the frame
        div = np.array([float(r["divCash"]) for r in rows])
        split = np.array([float(r["splitFactor"]) for r in rows])
        tr_ratio = tr[1:] / tr[:-1]
        adj_ratio = adj[1:] / adj[:-1]
        close_ratio = close[1:] / close[:-1]

        gap = np.abs(tr_ratio - adj_ratio)
        worst = int(np.argmax(gap))
        assert len(gap) == len(rows) - 1 and len(gap) >= 4, f"{ticker}: too few day pairs checked"
        assert gap.max() <= TOL, (
            f"{ticker}: tr_index ratio differs from adjClose ratio by {gap.max():.3e} on "
            f"{rows[worst + 1]['date'][:10]} (limit {TOL})"
        )

        # Must-contain: an action day on which the adjustment did something.
        if ticker in SPLIT_DAYS:
            action = np.nonzero(split[1:] != 1.0)[0]
            kind = "splitFactor != 1"
        else:
            action = np.nonzero(div[1:] > 0)[0]
            kind = "divCash > 0"
        assert len(action) >= 1, f"{ticker}: fixture has no day with {kind}"
        moved = np.abs(close_ratio[action] - tr_ratio[action])
        assert (moved > 1e-10).all(), (
            f"{ticker}: on {int((moved <= 1e-10).sum())} action day(s) the tr_index ratio equals "
            "the raw close ratio (the adjustment did nothing)"
        )
        # A split shown as a crash or jump is exactly what must not survive in the index.
        if ticker in SPLIT_DAYS:
            day, factor = SPLIT_DAYS[ticker]
            i = [r["date"][:10] for r in rows].index(day) - 1
            assert abs(close_ratio[i] - tr_ratio[i]) > 0.3, f"{ticker}: split on {day} not removed"
            assert not abs(tr_ratio[i] - 1.0) > 0.5, f"{ticker}: split day {day} shown as a jump"

    @pytest.mark.parametrize("ticker", TICKERS)
    def test_tr_index_does_not_depend_on_adjclose(ticker, monkeypatch):
        returns_mod = _need("portfoliosight.data.returns")
        np = _need("numpy")
        rows = _fixture_rows(ticker)
        frame = _fetch_frame(ticker, rows, monkeypatch)
        base = _tr(returns_mod, frame.copy(), ticker)

        withheld = _tr(
            returns_mod, frame.drop(columns=["adj_close"]), f"{ticker} without adj_close"
        )
        assert withheld.tobytes() == base.tobytes(), (
            f"{ticker}: tr_index changes when adj_close is withheld (the conversion reads adjClose)"
        )

        rng = np.random.default_rng(20261013)
        poisoned = frame.copy()
        poisoned["adj_close"] = poisoned["adj_close"].to_numpy() * rng.uniform(0.5, 2.0, len(frame))
        spoiled = _tr(returns_mod, poisoned, f"{ticker} with scrambled adj_close")
        assert spoiled.tobytes() == base.tobytes(), (
            f"{ticker}: tr_index follows a scrambled adj_close column (it is copied, not rebuilt)"
        )
        # Control: the scrambled column really differs, so the equality above is not vacuous.
        assert not np.allclose(poisoned["adj_close"].to_numpy(), frame["adj_close"].to_numpy())
