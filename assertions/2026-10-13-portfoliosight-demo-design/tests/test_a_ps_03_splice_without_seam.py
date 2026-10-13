"""A-PS-03 — a provider tail splices onto a seeded record without a seam.

Claim: splicing a provider tail fetched from adjusted_through - 7 days onto a seed-style record at
adjusted_through yields a tr_index within 1e-5 of the all-provider index from the first spliced
day on, updates adjusted_through to the last fetched date, and the refresh logic skips a symbol
only when both its prices and its adjustments reach D_G.

Pinned interface (the product must provide exactly this):
- The recorded VTI fixture `tests/fixtures/provider/vti*.json` (raw Tiingo rows, full history,
  reaching at least 2026-04-01 so the spliced tail holds a dividend).
- `portfoliosight.data.store.LocalStore(root)`, canonical record `prices/{SYMBOL}.parquet` and
  `meta/manifest.json` = `{"symbols": {ID: entry}}` (shared pins).
- `portfoliosight.data.providers.tiingo.TiingoProvider()` (HTTP through `requests`; the prices call
  carries the `startDate` query parameter) and `portfoliosight.data.returns.build_tr_index(frame)`.
- `portfoliosight.data.download.run(mode, *, store, providers, clock, sleep, symbols=None,
  tiers=None) -> int`: `mode` is `"measure-limits" | "catch-up" | "refresh"`; `providers` maps a
  provider name to a provider (`"tiingo"` serves every id that does not start with `TSP-`, `"tsp"`
  the rest; a run without TSP ids needs only `"tiingo"`); `clock()` returns an aware UTC datetime
  and is the only source of time; `sleep(seconds)` is the only way the run waits; `symbols`, when
  given, is the configured set in priority order (no repo universe file is consulted, and a
  symbol's name/kind/tier come from its manifest entry); the return value is the exit code (0 on a
  clean run). `D_G` is `portfoliosight.data.calendar.generation_date(clock())`. In `refresh` a
  symbol with a record costs exactly one prices request, from `adjusted_through - 7 days`.
- `portfoliosight.data.download.plan_refresh(entries, symbols, d_g) -> list[tuple[str, date]]`: a
  pure function; `entries` is the manifest's `symbols` mapping (ISO date strings), `symbols` the
  configured set in priority order, `d_g` a `datetime.date`; it returns, in priority order, the
  `(symbol, start)` pairs to fetch, `start = adjusted_through - 7 days`, and omits a symbol only
  when `last_date >= d_g` and `adjusted_through >= d_g`.
"""

from __future__ import annotations

import importlib
import io
import json
import os
import re
import subprocess
import sys
from datetime import date, datetime, time, timedelta, timezone
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
        pytest.fail(f"A-PS-03 red: cannot import {module}: {type(exc).__name__}: {exc}")


TOL = 1e-5
CUT = "2025-12-31"
SEAM = "2026-01-02"
EXPECTED_START = "2025-12-24"  # CUT - 7 days, computed by hand
SEED_PRICES_END = "2026-02-27"  # the seed-style record carries price-only rows up to here
FIXTURE_DIR = ROOT / "tests" / "fixtures" / "provider"
PRICES_URL = re.compile(r"^https://api\.tiingo\.com/tiingo/daily/([^/?]+)/prices")
META_URL = re.compile(r"^https://api\.tiingo\.com/tiingo/daily/([^/?]+)/?(\?.*)?$")
RECORD_COLUMNS = ("date", "close", "tr_index", "div_cash", "split_factor")


def _vti_rows() -> list[dict]:
    if not FIXTURE_DIR.is_dir():
        pytest.fail(f"A-PS-03 red: fixture directory missing: {FIXTURE_DIR.relative_to(ROOT)}")
    hits = sorted(p for p in FIXTURE_DIR.glob("*.json") if p.stem.lower().startswith("vti"))
    if not hits:
        pytest.fail(f"A-PS-03 red: no recorded fixture {FIXTURE_DIR.relative_to(ROOT)}/vti*.json")
    rows = sorted(json.loads(hits[0].read_text()), key=lambda r: r["date"])
    days = [r["date"][:10] for r in rows]
    assert CUT in days and SEAM in days, "VTI fixture must contain 2025-12-31 and 2026-01-02"
    assert days[-1] >= "2026-04-01", f"VTI fixture ends {days[-1]}; it must reach 2026-04-01"
    assert days.index(CUT) >= 250, "VTI fixture must hold history before the cut"
    return rows


def _expected_dg(run_at: datetime) -> date:
    """Spec section 4.2, recomputed here: last XNYS close >= 6 h before 02:00 Los Angeles."""
    from zoneinfo import ZoneInfo

    pd = _need("pandas")
    xc = _need("exchange_calendars")
    la = ZoneInfo("America/Los_Angeles")
    la_day = run_at.astimezone(la).date()
    cutoff = pd.Timestamp(datetime.combine(la_day, time(2, 0), tzinfo=la) - timedelta(hours=6))
    cal = xc.get_calendar("XNYS")
    lo = pd.Timestamp(la_day - timedelta(days=15))
    for session in reversed(cal.sessions_in_range(lo, pd.Timestamp(la_day))):
        if cal.session_close(session) <= cutoff.tz_convert("UTC"):
            return session.date()
    pytest.fail("A-PS-03: no XNYS session found in the 15 days before the run date")


def _parquet_bytes(frame) -> bytes:
    buf = io.BytesIO()
    frame.to_parquet(buf, index=False)
    return buf.getvalue()


def _read_record(store, symbol: str):
    pd = _need("pandas")
    try:
        frame = pd.read_parquet(io.BytesIO(store.get(f"prices/{symbol}.parquet")))
    except KeyError:
        pytest.fail(f"A-PS-03 red: prices/{symbol}.parquet is absent from the store after the run")
    for column in RECORD_COLUMNS:
        assert column in frame.columns, f"canonical record lacks column {column}"
    return frame.sort_values("date").reset_index(drop=True)


def _manifest_symbols(store) -> dict:
    doc = json.loads(store.get("meta/manifest.json"))
    return doc["symbols"] if isinstance(doc.get("symbols"), dict) else doc


def _entry(**over) -> dict:
    base = {
        "name": "Fund",
        "kind": "etf",
        "tier": 1,
        "income": False,
        "source": "tiingo",
        "first_date": "2001-05-31",
        "last_date": None,
        "adjusted_through": None,
        "status": "ok",
        "reason": None,
        "fetched_at": "2026-01-01T00:00:00+00:00",
    }
    base.update(over)
    return base


if _OUTER:

    def test_a_ps_03_in_project_venv():
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
        assert proc.returncode == 0, "A-PS-03 is red inside the project virtualenv (output above)"

else:

    def test_tail_splices_onto_the_seed_record_without_a_seam(tmp_path, monkeypatch):
        pd = _need("pandas")
        np = _need("numpy")
        responses = _need("responses")
        store_mod = _need("portfoliosight.data.store")
        tiingo = _need("portfoliosight.data.providers.tiingo")
        returns_mod = _need("portfoliosight.data.returns")
        download = _need("portfoliosight.data.download")
        rows = _vti_rows()
        days = [r["date"][:10] for r in rows]
        close = np.array([float(r["close"]) for r in rows])
        adj = np.array([float(r["adjClose"]) for r in rows])
        div = np.array([float(r["divCash"]) for r in rows])
        split = np.array([float(r["splitFactor"]) for r in rows])
        i_cut, last_day = days.index(CUT), days[-1]
        post = [i for i, d in enumerate(days) if d > CUT]
        assert len(post) >= 20 and days[post[0]] == SEAM, "fixture must continue on 2026-01-02"

        # Seed-style record: tr_index from the back-adjusted close up to the cut, price-only after.
        n_seed = sum(1 for d in days if d <= max(SEED_PRICES_END, CUT))
        seed_tr = adj[:n_seed] / adj[0]
        seed_tr[i_cut + 1 :] = np.nan
        seed = pd.DataFrame(
            {
                "date": pd.to_datetime(days[:n_seed]),
                "close": close[:n_seed],
                "tr_index": seed_tr,
                "div_cash": np.full(n_seed, np.nan),
                "split_factor": np.full(n_seed, np.nan),
            }
        )
        assert n_seed > i_cut + 1, "the seed-style record must hold price-only rows after the cut"
        store = store_mod.LocalStore(tmp_path / "store")
        store.put("prices/VTI.parquet", _parquet_bytes(seed))
        manifest = {
            "symbols": {
                "VTI": _entry(
                    name="Vanguard Total Stock Market ETF",
                    source="seed",
                    status="pending",
                    first_date=days[0],
                    last_date=days[n_seed - 1],
                    adjusted_through=CUT,
                )
            }
        }
        store.put("meta/manifest.json", json.dumps(manifest).encode())

        now = [datetime.combine(date.fromisoformat(last_day), time(12, 5), tzinfo=timezone.utc)]
        now[0] += timedelta(days=1)
        assert _expected_dg(now[0]) == date.fromisoformat(last_day), "test clock does not give D_G"
        slept: list[float] = []

        def sleep(seconds):
            slept.append(float(seconds))
            assert len(slept) < 10_000, "runaway sleep loop in the downloader"
            now[0] += timedelta(seconds=max(float(seconds), 0.0))

        price_calls: list[dict] = []

        def prices(request):
            query = parse_qs(urlparse(request.url).query)
            start = query.get("startDate", [""])[0]
            end = query.get("endDate", [""])[0] or "9999-99-99"
            price_calls.append({"url": request.url, "startDate": start})
            if PRICES_URL.match(request.url).group(1).upper() != "VTI":
                return (404, {}, json.dumps({"detail": "Not found."}))
            body = [r for r in rows if (start or "0000") <= r["date"][:10] <= end]
            return (200, {"Content-Type": "application/json"}, json.dumps(body))

        def meta(request):
            body = {"ticker": "VTI", "name": "Vanguard Total Stock Market ETF"}
            body.update({"startDate": days[0], "endDate": last_day, "exchangeCode": "NYSE ARCA"})
            return (200, {"Content-Type": "application/json"}, json.dumps(body))

        monkeypatch.setenv("TIINGO_API_KEY", "gate-test-key")
        with responses.RequestsMock(assert_all_requests_are_fired=False) as mock:
            mock.add_callback(responses.GET, PRICES_URL, callback=prices)
            mock.add_callback(responses.GET, META_URL, callback=meta)
            provider = tiingo.TiingoProvider()
            try:
                code = download.run(
                    "refresh",
                    store=store,
                    providers={"tiingo": provider},
                    clock=lambda: now[0],
                    sleep=sleep,
                    symbols=["VTI"],
                )
            except Exception as exc:
                pytest.fail(f"A-PS-03 red: download.run('refresh') raised {exc!r}")
            refresh_calls = list(price_calls)
            # The all-provider index, through the same adapter and conversion.
            full_frame = provider.fetch_daily("VTI", date.fromisoformat(days[0]), None)
            requests_seen = [call.request.url for call in mock.calls]
        assert code == 0, f"refresh run exit code {code}"
        tr_full_product = returns_mod.build_tr_index(full_frame).to_numpy(dtype=float)
        assert len(tr_full_product) == len(rows), "all-provider frame differs from the fixture"

        # (2) the request the adapter received starts at adjusted_through - 7 days.
        assert len(refresh_calls) == 1, (
            f"refresh must cost exactly one prices request for VTI, saw {len(refresh_calls)}"
        )
        assert refresh_calls[0]["startDate"] == EXPECTED_START, (
            f"tail fetched from startDate={refresh_calls[0]['startDate']!r}, "
            f"expected {EXPECTED_START} (adjusted_through - 7 days)"
        )
        assert refresh_calls[0]["startDate"] != CUT, (
            "tail must not start at adjusted_through itself"
        )
        assert any(PRICES_URL.match(u) for u in requests_seen), "responses saw no prices request"

        # (3) adjusted_through moves to the tail's last date; no rows after it.
        record = _read_record(store, "VTI")
        got_days = [d.strftime("%Y-%m-%d") for d in pd.to_datetime(record["date"])]
        assert got_days == days, (
            f"spliced record has {len(got_days)} rows ending {got_days[-1]}; "
            f"expected the {len(days)} fixture days ending {last_day}"
        )
        entry = _manifest_symbols(store)["VTI"]
        assert entry["adjusted_through"] == last_day, (
            f"adjusted_through {entry['adjusted_through']}"
        )
        assert entry["last_date"] == last_day, f"last_date {entry['last_date']}"
        assert entry["adjusted_through"] != CUT, "adjusted_through was not advanced"
        assert not any(d > entry["adjusted_through"] for d in got_days), (
            "rows after adjusted_through"
        )
        tr = record["tr_index"].to_numpy(dtype=float)
        assert np.isfinite(tr).all(), "price-only rows (NaN tr_index) remain after the splice"
        assert tr[0] == 1.0, "tr_index must stay 1.0 on the first row"
        assert np.allclose(record["close"].to_numpy(dtype=float), close, rtol=1e-12, atol=0.0)

        # The stored index up to the cut is kept (the tail is anchored on it, not the reverse).
        before = np.abs(tr[: i_cut + 1] / (adj[: i_cut + 1] / adj[0]) - 1.0)
        assert before.max() <= TOL, f"pre-cut index rewritten (max rel. change {before.max():.2e})"

        # (1) every day from 2026-01-02 on, against two references rebased to the cut:
        # the product's all-provider index, and the section 4.1 formula recomputed here.
        both = [i for i in post if split[i] != 1.0 and div[i] > 0]
        assert not both, (
            "VTI tail has a split and a dividend on one day; the reference is ambiguous"
        )
        ref = np.ones(len(rows))
        for i in range(i_cut + 1, len(rows)):
            ref[i] = ref[i - 1] * (close[i] * split[i] + div[i]) / close[i - 1]
        checked = 0
        for i in post:
            spliced = tr[i] / tr[i_cut]
            for name, want in (
                ("all-provider", tr_full_product[i] / tr_full_product[i_cut]),
                ("formula", ref[i]),
            ):
                assert abs(spliced / want - 1.0) <= TOL, (
                    f"{days[i]}: spliced index is {spliced / want - 1.0:+.3e} off the {name} index"
                )
            checked += 1
        assert checked == len(post) and days[post[0]] == SEAM, "the seam day was not checked"

        # Must-not-contain: an invented one-day return at the seam.
        seam_return = tr[post[0]] / tr[i_cut] - 1.0
        true_return = adj[post[0]] / adj[i_cut] - 1.0
        assert not abs(seam_return - true_return) > TOL, (
            f"seam-day return {seam_return:+.6f} vs provider {true_return:+.6f}: an invented jump"
        )
        assert any(d > 0 for d in div[post]), "control: the tail holds no dividend, check is weak"

    def test_planner_skips_only_when_prices_and_adjustments_reach_dg():
        np = _need("numpy")
        download = _need("portfoliosight.data.download")
        rng = np.random.default_rng(303)
        states = 0
        for trial in range(40):
            d_g = date(2026, 1, 5) + timedelta(days=int(rng.integers(0, 250)))
            ahead = [int(k) for k in rng.integers(0, 4, size=4)]  # at or past D_G
            behind = [int(k) for k in rng.integers(1, 40, size=4)]  # strictly before D_G
            dates = {
                "AAA": (d_g + timedelta(days=ahead[0]), d_g + timedelta(days=ahead[1])),  # (a)
                "BBB": (d_g + timedelta(days=ahead[2]), d_g - timedelta(days=behind[0])),  # (b)
                "CCC": (d_g - timedelta(days=behind[1]), d_g + timedelta(days=ahead[3])),  # (c)
                "DDD": (d_g - timedelta(days=behind[2]), d_g - timedelta(days=behind[3])),  # (d)
            }
            if trial == 0:  # exact boundary: both dates equal D_G, and one day short of it
                dates["AAA"] = (d_g, d_g)
                dates["BBB"] = (d_g, d_g - timedelta(days=1))
                dates["CCC"] = (d_g - timedelta(days=1), d_g)
            statuses = ["ok", "stale", "pending"]
            entries = {}
            for symbol, (last, adjusted) in dates.items():
                status = statuses[int(rng.integers(0, 3))]
                entries[symbol] = _entry(
                    last_date=last.isoformat(),
                    adjusted_through=adjusted.isoformat(),
                    status=status,
                    source="seed" if status == "pending" else "tiingo",
                )
            order = [str(s) for s in rng.permutation(sorted(dates))]
            try:
                plan = download.plan_refresh(entries, order, d_g)
            except Exception as exc:
                pytest.fail(f"A-PS-03 red: plan_refresh raised {exc!r}")
            got = []
            for symbol, start in plan:
                got.append((symbol, start.date() if isinstance(start, datetime) else start))
            want = [(s, dates[s][1] - timedelta(days=7)) for s in order if s != "AAA"]
            assert got == want, f"D_G={d_g} order={order}: plan {got}, expected {want}"
            assert "AAA" not in [s for s, _ in got], "a symbol current on both dates was refetched"
            assert {s for s, _ in got} == {"BBB", "CCC", "DDD"}, "a lagging symbol was skipped"
            states += 4
        assert states == 160, "planner property did not cover all four states in every trial"
