"""Tail splice and the refresh planner (spec 4.1 splice test, 5.1, 5.4; A-PS-03)."""

from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import numpy as np
import pandas as pd
import pytest
import responses

from portfoliosight.data import refresh, returns
from portfoliosight.data.providers import tiingo

VTI = Path(__file__).resolve().parents[1] / "fixtures" / "provider" / "VTI.json"
PRICES_URL = re.compile(r"^https://api\.tiingo\.com/tiingo/daily/VTI/prices")
CUT = date(2025, 12, 31)
SEAM = "2026-01-02"
SEED_PRICES_END = "2026-02-27"
TOL = 1e-5


@pytest.fixture(scope="module")
def rows() -> list[dict]:
    return json.loads(VTI.read_text())


def _seed_record(rows: list[dict]) -> pd.DataFrame:
    """A seed-style record: index from adjClose up to the cut, price-only rows after it."""
    kept = [r for r in rows if r["date"][:10] <= SEED_PRICES_END]
    adj = np.array([float(r["adjClose"]) for r in kept])
    days = pd.to_datetime([r["date"][:10] for r in kept])
    tr = adj / adj[0]
    tr[days > pd.Timestamp(CUT)] = np.nan
    return pd.DataFrame(
        {
            "date": days,
            "close": [float(r["close"]) for r in kept],
            "tr_index": tr,
            "div_cash": np.nan,
            "split_factor": np.nan,
        }
    )


def _fetch_tail(rows: list[dict], monkeypatch) -> tuple[pd.DataFrame, list[str]]:
    monkeypatch.setenv("TIINGO_API_KEY", "unit-test-key")
    starts: list[str] = []

    def callback(request):
        start = parse_qs(urlparse(request.url).query)["startDate"][0]
        starts.append(start)
        body = [r for r in rows if r["date"][:10] >= start]
        return (200, {"Content-Type": "application/json"}, json.dumps(body))

    with responses.RequestsMock() as mock:
        mock.add_callback(responses.GET, PRICES_URL, callback=callback)
        tail = tiingo.TiingoProvider().fetch_daily("VTI", refresh.tail_start(CUT), None)
    return tail, starts


def test_tail_splices_without_a_seam(rows, monkeypatch):
    seed = _seed_record(rows)
    tail, starts = _fetch_tail(rows, monkeypatch)
    assert starts == ["2025-12-24"]

    spliced, adjusted_through = returns.splice_tail(seed, tail, CUT)

    days = [r["date"][:10] for r in rows]
    assert adjusted_through == date.fromisoformat(days[-1])
    assert [d.strftime("%Y-%m-%d") for d in spliced["date"]] == days
    assert list(spliced.columns) == list(returns.RECORD_COLUMNS)
    tr = spliced["tr_index"].to_numpy()
    assert np.isfinite(tr).all() and tr[0] == 1.0

    full = returns.build_tr_index(tiingo.rows_to_frame(rows)).to_numpy()
    i_cut = days.index(CUT.isoformat())
    assert days[i_cut + 1] == SEAM
    post = slice(i_cut + 1, None)
    np.testing.assert_allclose(tr[post] / tr[i_cut], full[post] / full[i_cut], rtol=TOL, atol=0)
    # The stored index up to the cut is kept bit for bit.
    np.testing.assert_array_equal(tr[: i_cut + 1], seed["tr_index"].to_numpy()[: i_cut + 1])
    # Provider rows carry their actions; seed rows do not.
    assert spliced["div_cash"].iloc[: i_cut + 1].isna().all()
    assert (spliced["div_cash"].iloc[i_cut + 1 :] > 0).any()
    assert (spliced["split_factor"].iloc[i_cut + 1 :] == 1.0).all()
    # No invented one-day return at the seam.
    adj = np.array([float(r["adjClose"]) for r in rows])
    assert abs(tr[i_cut + 1] / tr[i_cut] - adj[i_cut + 1] / adj[i_cut]) <= TOL


def test_splice_when_the_tail_lacks_the_anchor_day(rows, monkeypatch):
    seed = _seed_record(rows)
    tail, _ = _fetch_tail(rows, monkeypatch)
    without_anchor = tail.loc[tail.index != pd.Timestamp(CUT)]
    a, _ = returns.splice_tail(seed, without_anchor, CUT)
    b, _ = returns.splice_tail(seed, tail, CUT)
    pd.testing.assert_frame_equal(a, b)


def test_tail_with_nothing_new_changes_nothing(rows, monkeypatch):
    seed = _seed_record(rows)
    tail, _ = _fetch_tail(rows, monkeypatch)
    old = tail.loc[tail.index <= pd.Timestamp(CUT)]
    same, adjusted_through = returns.splice_tail(seed, old, CUT)
    assert adjusted_through == CUT
    pd.testing.assert_frame_equal(same, seed)


def test_anchor_is_the_last_indexed_row_on_or_before_adjusted_through(rows, monkeypatch):
    seed = _seed_record(rows)
    tail, _ = _fetch_tail(rows, monkeypatch)
    # adjusted_through on a Saturday: the anchor is the Friday before it.
    spliced, _ = returns.splice_tail(seed, tail, date(2026, 1, 3))
    reference, _ = returns.splice_tail(seed, tail, date(2026, 1, 2))
    assert len(spliced) == len(reference) and np.isfinite(spliced["tr_index"]).all()
    with pytest.raises(ValueError, match="no index value"):
        returns.splice_tail(seed, tail, date(1999, 1, 1))


def _entry(last: date | None, adjusted: date | None) -> dict:
    return {
        "last_date": last.isoformat() if last else None,
        "adjusted_through": adjusted.isoformat() if adjusted else None,
        "status": "ok",
    }


def test_planner_skips_only_symbols_current_on_both_dates():
    d_g = date(2026, 3, 13)
    day = timedelta(days=1)
    entries = {
        "A": _entry(d_g, d_g),
        "B": _entry(d_g, d_g - day),
        "C": _entry(d_g - day, d_g),
        "D": _entry(d_g - 9 * day, d_g - 12 * day),
        "AHEAD": _entry(d_g + day, d_g + day),
        "NEW": _entry(None, None),
    }
    order = ["D", "AHEAD", "C", "NEW", "A", "B", "MISSING"]
    plan = refresh.plan_refresh(entries, order, d_g)
    assert plan == [
        ("D", d_g - 19 * day),
        ("C", d_g - 7 * day),
        ("B", d_g - 8 * day),
    ]


def test_planner_reads_objects_and_dates():
    class Entry:
        last_date = date(2026, 3, 12)
        adjusted_through = datetime(2026, 3, 12, 9, 30)

    assert refresh.plan_refresh({"X": Entry()}, ["X"], date(2026, 3, 13)) == [
        ("X", date(2026, 3, 5))
    ]
    assert refresh.plan_refresh({"X": Entry()}, ["X"], date(2026, 3, 12)) == []
    assert refresh.as_date("") is None and refresh.as_date("2026-03-12T00:00:00") == date(
        2026, 3, 12
    )
