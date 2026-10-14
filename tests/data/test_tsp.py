"""TSP provider against the recorded tsp.gov slice (spec 5.5; A-PS-09)."""

from __future__ import annotations

import csv
import io
from datetime import date
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import numpy as np
import pandas as pd
import pytest
import requests
import responses

from portfoliosight.data import returns
from portfoliosight.data.providers import base, tsp
from portfoliosight.data.universe import TSP_FUNDS

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "tsp" / "tsp-fund-price-history.csv"
TEXT = FIXTURE.read_text(encoding="utf-8")
START, END = date(2026, 1, 1), date(2026, 3, 31)


@pytest.fixture
def served():
    """Replay the recorded CSV for every tsp.gov request; yields the recorded calls."""
    with responses.RequestsMock() as mock:
        mock.add(responses.GET, tsp.CSV_URL, body=TEXT, content_type="text/csv")
        yield mock.calls


def _cell(day: str, column: str) -> float:
    rows = list(csv.reader(io.StringIO(TEXT)))
    row = next(r for r in rows[1:] if r[0] == day)
    return float(row[rows[0].index(column)])


def test_fetch_all_gives_16_provider_frames(served):
    frames = tsp.TspProvider().fetch_all(START, END)
    assert list(frames) == list(tsp.COLUMN_IDS) and set(frames) == set(TSP_FUNDS)
    assert len(frames) == 16 and len(served) == 1
    for symbol, frame in frames.items():
        assert list(frame.columns) == ["close", "adj_close", "div_cash", "split_factor"], symbol
        assert isinstance(frame.index, pd.DatetimeIndex) and frame.index.name == "date"
        assert frame.index.tz is None and frame.index.is_monotonic_increasing
        assert len(frame) == 61 and frame.index.is_unique
        assert (frame["adj_close"] == frame["close"]).all()
        assert (frame["div_cash"] == 0).all() and (frame["split_factor"] == 1).all()
    assert frames["TSP-C"].at[pd.Timestamp("2026-03-30"), "close"] == _cell("2026-03-30", "C Fund")
    assert frames["TSP-LINC"].at[pd.Timestamp("2026-01-02"), "close"] == 29.2952


def test_request_carries_a_browser_agent_and_the_query(served):
    provider = tsp.TspProvider()
    assert provider.name == "tsp" and isinstance(provider, base.PriceProvider)
    provider.fetch_daily("TSP-G", START, END)
    request = served[0].request
    assert request.headers["User-Agent"].startswith("Mozilla/5.0 ")
    assert "Chrome/" in request.headers["User-Agent"]
    assert parse_qs(urlsplit(request.url).query) == {
        "startdate": ["2026-01-01"],
        "enddate": ["2026-03-31"],
        "Lfunds": ["1"],
        "InvFunds": ["1"],
        "download": ["1"],
    }


def test_canonical_record_is_the_price_over_the_first_price(served):
    frame = tsp.TspProvider().fetch_daily("TSP-C", START, END)
    record = returns.provider_rows_to_record(frame)
    close = frame["close"].to_numpy()
    assert record["tr_index"].iloc[0] == 1.0
    np.testing.assert_allclose(record["tr_index"].to_numpy(), close / close[0], rtol=1e-13)
    np.testing.assert_array_equal(record["close"].to_numpy(), close)
    # adjusted_through is the last priced date: every row carries the total-return price.
    assert str(record["date"].iloc[-1])[:10] == "2026-03-31"


def test_one_download_serves_every_fund_and_the_range_is_applied(served):
    provider = tsp.TspProvider()
    for symbol in TSP_FUNDS:
        assert len(provider.fetch_daily(symbol, START, END)) == 61
    assert len(served) == 1
    # tsp.gov can answer with more history than asked for: rows outside the range are dropped.
    february = provider.fetch_daily("TSP-G", date(2026, 2, 2), date(2026, 2, 27))
    assert len(served) == 2
    assert (
        str(february.index[0])[:10] == "2026-02-02" and str(february.index[-1])[:10] == "2026-02-27"
    )
    early = provider.fetch_daily("TSP-G", date(1990, 1, 1), END)
    assert parse_qs(urlsplit(served[2].request.url).query)["startdate"] == ["2003-06-02"]
    assert len(early) == 61
    mutated = provider.fetch_daily("TSP-G", START, END)
    mutated.iloc[0, 0] = -1.0
    assert provider.fetch_daily("TSP-G", START, END).iloc[0, 0] > 0


def test_meta_has_display_names_and_the_last_priced_date(served, monkeypatch):
    provider = tsp.TspProvider()
    names = {}
    for symbol in TSP_FUNDS:
        meta = provider.fetch_meta(symbol)
        assert meta is not None and meta.kind == "tsp"
        assert meta.first_date == date(2026, 1, 2) and meta.last_date == date(2026, 3, 31)
        names[symbol] = meta.name
    assert names == TSP_FUNDS and names["TSP-L2030"] == "L 2030" and names["TSP-G"] == "G Fund"
    assert len(served) == 1
    with pytest.raises(base.ProviderError, match="not a TSP fund id"):
        provider.fetch_meta("VTI")


def test_fund_without_prices_has_no_meta():
    header = ",".join(tsp.HEADER)
    text = f"{header}\n2026-01-02,1.5{',' * 14},9.5\n\n"
    frames = tsp.parse_tsp_csv(text)
    assert len(frames["TSP-LINC"]) == 1 and len(frames["TSP-I"]) == 1
    assert frames["TSP-G"].empty and list(frames["TSP-G"].columns) == list(base.PROVIDER_COLUMNS)
    with responses.RequestsMock() as mock:
        mock.add(responses.GET, tsp.CSV_URL, body=text)
        assert tsp.TspProvider().fetch_meta("TSP-G") is None


def _with_header(cells: list[str]) -> str:
    return "\n".join([",".join(cells), *TEXT.splitlines()[1:]]) + "\n"


def test_non_exact_headers_are_refused():
    swapped = list(tsp.HEADER)
    i, j = swapped.index("L 2040"), swapped.index("F Fund")
    swapped[i], swapped[j] = swapped[j], swapped[i]
    renamed = ["C Fund Price" if cell == "C Fund" else cell for cell in tsp.HEADER]
    cases = [
        (_with_header(swapped), "column 5: expected 'L 2040', found 'F Fund'"),
        (_with_header(renamed), "column 15: expected 'C Fund', found 'C Fund Price'"),
        (_with_header(list(tsp.HEADER[:-1])), "column 17: expected 'I Fund', found None"),
        (_with_header([*tsp.HEADER, "X Fund"]), "column 18: unexpected column 'X Fund'"),
        ("", "column 1: expected 'Date', found None"),
    ]
    for text, message in cases:
        with pytest.raises(tsp.TspHeaderError) as caught:
            tsp.parse_tsp_csv(text)
        assert message in str(caught.value)
        assert isinstance(caught.value, ValueError)
        with responses.RequestsMock() as mock:
            mock.add(responses.GET, tsp.CSV_URL, body=text)
            with pytest.raises(tsp.TspHeaderError):
                tsp.TspProvider().fetch_daily("TSP-C", START, END)
    other_dates = TEXT.replace("2026-03-31,", "Mar 31 2026,").replace("2026-03-30,", "3/30/2026,")
    pd.testing.assert_frame_equal(
        tsp.parse_tsp_csv(other_dates)["TSP-C"], tsp.parse_tsp_csv(TEXT)["TSP-C"]
    )
    spaced = _with_header([f" {cell} " for cell in tsp.HEADER])
    assert len(tsp.parse_tsp_csv("﻿" + spaced)["TSP-C"]) == 61


def test_http_failures_are_provider_errors():
    with responses.RequestsMock() as mock:
        mock.add(responses.GET, tsp.CSV_URL, status=403)
        with pytest.raises(base.ProviderError, match="403"):
            tsp.TspProvider().fetch_daily("TSP-C", START, END)
    with responses.RequestsMock() as mock:
        mock.add(responses.GET, tsp.CSV_URL, body=requests.ConnectionError("down"))
        with pytest.raises(base.ProviderError, match="ConnectionError"):
            tsp.TspProvider().fetch_daily("TSP-C", START, END)


def test_end_defaults_to_today(served):
    frame = tsp.TspProvider().fetch_daily("TSP-C", START, None)
    assert len(frame) == 61
    enddate = parse_qs(urlsplit(served[0].request.url).query)["enddate"][0]
    assert date.fromisoformat(enddate) >= date(2026, 10, 13)
