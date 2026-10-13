"""Tiingo adapter against the recorded fixtures (spec 4.1, 5.1; A-PS-02, A-PS-10 leg 2)."""

from __future__ import annotations

import json
import logging
import re
from datetime import date
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import numpy as np
import pandas as pd
import pytest
import responses

from portfoliosight.data import returns
from portfoliosight.data.providers import base, tiingo

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "provider"
PRICE_FILES = {
    "AAPL": "AAPL_2020-08.json",
    "NVDA": "NVDA_2024-06.json",
    "USO": "USO_2020-04.json",
    "VTI": "VTI.json",
    "VBIAX": "VBIAX.json",
}
SPLIT_DAYS = {
    "AAPL": ("2020-08-31", 4.0),
    "NVDA": ("2024-06-10", 10.0),
    "USO": ("2020-04-29", 0.125),
}
PRICES_URL = re.compile(r"^https://api\.tiingo\.com/tiingo/daily/([^/?]+)/prices")
META_URL = re.compile(r"^https://api\.tiingo\.com/tiingo/daily/([^/?]+)/?$")
SENTINEL = "ZZ-SENTINEL-KEY-ZZ"
TOL = 1e-5


def _rows(symbol: str) -> list[dict]:
    return json.loads((FIXTURES / PRICE_FILES[symbol]).read_text())


@pytest.fixture
def api_key(monkeypatch):
    monkeypatch.setenv("TIINGO_API_KEY", "unit-test-key")


@pytest.fixture
def mock():
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        yield rsps


def _replay(mock, symbol: str, seen: list | None = None):
    rows = _rows(symbol)

    def callback(request):
        query = parse_qs(urlparse(request.url).query)
        start = query["startDate"][0]
        end = query.get("endDate", ["9999-99-99"])[0]
        if seen is not None:
            seen.append((request, query))
        body = [r for r in rows if start <= r["date"][:10] <= end]
        return (200, {"Content-Type": "application/json"}, json.dumps(body))

    mock.add_callback(responses.GET, PRICES_URL, callback=callback)
    return rows


@pytest.mark.parametrize("symbol", sorted(PRICE_FILES))
def test_frame_shape_and_adjclose_cross_check(symbol, api_key, mock):
    seen: list = []
    rows = _replay(mock, symbol, seen)
    start = date.fromisoformat(rows[0]["date"][:10])
    frame = tiingo.TiingoProvider().fetch_daily(symbol, start, None)

    request, query = seen[0]
    assert request.headers["Authorization"] == "Token unit-test-key"
    assert query["startDate"] == [start.isoformat()] and "endDate" not in query
    assert query["format"] == ["json"]
    assert query["columns"] == ["date,close,adjClose,divCash,splitFactor"]

    assert isinstance(frame.index, pd.DatetimeIndex) and frame.index.name == "date"
    assert frame.index.tz is None and frame.index.is_monotonic_increasing
    assert frame.index.is_unique and len(frame) == len(rows)
    assert list(frame.columns) == ["close", "adj_close", "div_cash", "split_factor"]
    assert all(str(dtype) == "float64" for dtype in frame.dtypes)
    assert [d.strftime("%Y-%m-%d") for d in frame.index] == [r["date"][:10] for r in rows]

    adj = np.array([float(r["adjClose"]) for r in rows])
    close = np.array([float(r["close"]) for r in rows])
    adj_ratio = adj[1:] / adj[:-1]
    close_ratio = close[1:] / close[:-1]
    # The cross-check that fixes the basis rule: it must hold under the rule the adapter ships.
    record = returns.provider_rows_to_record(frame)
    tr = record["tr_index"].to_numpy()
    tr_ratio = tr[1:] / tr[:-1]
    assert tr[0] == 1.0
    assert np.abs(tr_ratio - adj_ratio).max() <= TOL
    for rule in ("post_split", "pre_split"):
        other = returns.build_tr_index(frame, basis_rule=rule).to_numpy()
        assert np.abs(other[1:] / other[:-1] - adj_ratio).max() <= TOL, rule

    if symbol in SPLIT_DAYS:
        day, factor = SPLIT_DAYS[symbol]
        i = [r["date"][:10] for r in rows].index(day)
        assert float(rows[i]["splitFactor"]) == factor
        assert abs(close_ratio[i - 1] - tr_ratio[i - 1]) > 0.3
        assert abs(tr_ratio[i - 1] - 1.0) < 0.5
    else:
        paid = np.nonzero(np.array([float(r["divCash"]) for r in rows[1:]]) > 0)[0]
        assert len(paid) >= 20
        assert (np.abs(close_ratio[paid] - tr_ratio[paid]) > 1e-10).all()

    without = returns.build_tr_index(frame.drop(columns=["adj_close"])).to_numpy()
    assert without.tobytes() == returns.build_tr_index(frame).to_numpy().tobytes()


def test_no_fixture_has_a_split_and_a_dividend_on_one_day():
    """Why both basis rules pass above: the shipped rule is a convention, not a measurement."""
    for symbol in PRICE_FILES:
        both = [
            r for r in _rows(symbol) if float(r["splitFactor"]) != 1 and float(r["divCash"]) > 0
        ]
        assert both == [], symbol
    assert returns.BASIS_RULE == "post_split"


def test_end_date_is_sent_and_empty_means_no_data(api_key, mock):
    seen: list = []
    _replay(mock, "AAPL", seen)
    provider = tiingo.TiingoProvider()
    frame = provider.fetch_daily("AAPL", date(2020, 8, 28), date(2020, 9, 1))
    assert seen[0][1]["endDate"] == ["2020-09-01"]
    assert [d.strftime("%Y-%m-%d") for d in frame.index] == [
        "2020-08-28",
        "2020-08-31",
        "2020-09-01",
    ]
    empty = provider.fetch_daily("AAPL", date(1999, 1, 1), date(1999, 1, 31))
    assert empty.empty and list(empty.columns) == ["close", "adj_close", "div_cash", "split_factor"]
    assert isinstance(empty.index, pd.DatetimeIndex) and empty.index.name == "date"


def test_rows_are_sorted_and_deduplicated():
    rows = _rows("AAPL")[:3]
    frame = tiingo.rows_to_frame([rows[2], rows[0], rows[1], rows[1]], "AAPL")
    assert [d.strftime("%Y-%m-%d") for d in frame.index] == [r["date"][:10] for r in rows]
    with pytest.raises(base.ProviderError, match="adjClose"):
        tiingo.rows_to_frame([{k: v for k, v in rows[0].items() if k != "adjClose"}], "AAPL")


def test_meta_and_404(api_key, mock):
    meta_body = json.loads((FIXTURES / "meta_VBIAX.json").read_text())
    mock.add(responses.GET, "https://api.tiingo.com/tiingo/daily/VBIAX", json=meta_body)
    mock.add(
        responses.GET,
        "https://api.tiingo.com/tiingo/daily/VTI",
        json=json.loads((FIXTURES / "meta_VTI.json").read_text()),
    )
    mock.add(
        responses.GET,
        "https://api.tiingo.com/tiingo/daily/NOSUCH",
        status=404,
        json={"detail": "Not found."},
    )
    mock.add(
        responses.GET,
        "https://api.tiingo.com/tiingo/daily/NOSUCH/prices",
        status=404,
        json={"detail": "Not found."},
    )
    mock.add(
        responses.GET,
        "https://api.tiingo.com/tiingo/daily/NODATES",
        json={"ticker": "NODATES", "name": None, "startDate": None, "endDate": None},
    )
    provider = tiingo.TiingoProvider()
    assert provider.name == "tiingo" and isinstance(provider, base.PriceProvider)

    meta = provider.fetch_meta("VBIAX")
    assert meta == base.SymbolMeta(
        name="VANGUARD BALANCED INDEX FUND ADMIRAL SHARES",
        first_date=date(2000, 11, 13),
        last_date=date.fromisoformat(meta_body["endDate"]),
        kind="mutual_fund",
    )
    vti = provider.fetch_meta("VTI")
    assert vti is not None and vti.kind == "etf" and vti.first_date == date(2001, 5, 31)
    assert provider.fetch_meta("NOSUCH") is None
    assert provider.fetch_daily("NOSUCH", date(2020, 1, 1), None).empty
    assert provider.fetch_meta("NODATES") == base.SymbolMeta("NODATES", None, None, "etf")


def _provider_with_429(mock, retry_after: str | None, **kwargs):
    headers = {"Retry-After": retry_after} if retry_after is not None else {}
    url = "https://api.tiingo.com/tiingo/daily/VTI"
    mock.add(responses.GET, url, status=429, headers=headers, json={"detail": "over"})
    mock.add(responses.GET, url, json={"ticker": "VTI", "name": "Vanguard Total"})
    slept: list[float] = []
    attempts: list[tuple[str, int]] = []
    provider = tiingo.TiingoProvider(
        sleep=slept.append,
        before_request=lambda symbol: attempts.append((symbol, len(mock.calls))),
        **kwargs,
    )
    return provider, slept, attempts


@pytest.mark.parametrize(("retry_after", "expected"), [("7", 7.0), (None, 60.0), ("soon", 60.0)])
def test_429_backs_off_then_retries(retry_after, expected, api_key, mock):
    provider, slept, attempts = _provider_with_429(mock, retry_after)
    meta = provider.fetch_meta("VTI")
    assert meta is not None and meta.name == "Vanguard Total"
    assert slept == [expected]
    # The hook runs once per HTTP attempt, and before the retry is sent.
    assert attempts == [("VTI", 0), ("VTI", 1)] and len(mock.calls) == 2


def test_probe_mode_raises_on_the_first_429(api_key, mock):
    provider, slept, attempts = _provider_with_429(mock, "7", retry_on_429=False)
    with pytest.raises(base.RateLimited) as caught:
        provider.fetch_meta("VTI")
    assert isinstance(caught.value, Exception) and caught.value.retry_after == 7.0
    assert slept == [] and len(mock.calls) == 1 and attempts == [("VTI", 0)]


def test_429_gives_up_after_the_retry_limit(api_key, mock):
    mock.add(responses.GET, "https://api.tiingo.com/tiingo/daily/VTI", status=429)
    slept: list[float] = []
    provider = tiingo.TiingoProvider(sleep=slept.append, max_retries=2)
    with pytest.raises(base.RateLimited):
        provider.fetch_meta("VTI")
    assert slept == [60.0, 60.0] and len(mock.calls) == 3


def test_default_wait_is_time_sleep_looked_up_at_call_time(api_key, mock, monkeypatch):
    mock.add(responses.GET, "https://api.tiingo.com/tiingo/daily/VTI", status=429)
    mock.add(responses.GET, "https://api.tiingo.com/tiingo/daily/VTI", json={"name": "V"})
    provider = tiingo.TiingoProvider()
    slept: list[float] = []
    monkeypatch.setattr("time.sleep", slept.append)
    assert provider.fetch_meta("VTI") is not None and slept == [60.0]


def test_errors_and_odd_payloads(api_key, mock, monkeypatch):
    import requests

    mock.add(responses.GET, "https://api.tiingo.com/tiingo/daily/BOOM", status=500)
    mock.add(responses.GET, "https://api.tiingo.com/tiingo/daily/TEXT", body="not json")
    mock.add(responses.GET, "https://api.tiingo.com/tiingo/daily/LIST", json=[1])
    mock.add(responses.GET, "https://api.tiingo.com/tiingo/daily/OBJ/prices", json={"a": 1})
    mock.add(
        responses.GET,
        "https://api.tiingo.com/tiingo/daily/DOWN",
        body=requests.ConnectionError(f"refused with {SENTINEL}"),
    )
    monkeypatch.setenv("TIINGO_API_KEY", SENTINEL)
    provider = tiingo.TiingoProvider()
    for symbol, pattern in (("BOOM", "500"), ("TEXT", "non-JSON"), ("LIST", "not an object")):
        with pytest.raises(base.ProviderError, match=pattern):
            provider.fetch_meta(symbol)
    with pytest.raises(base.ProviderError, match="not a list"):
        provider.fetch_daily("OBJ", date(2020, 1, 1), None)
    with pytest.raises(base.ProviderError) as caught:
        provider.fetch_meta("DOWN")
    assert SENTINEL not in str(caught.value) and caught.value.__cause__ is None
    monkeypatch.delenv("TIINGO_API_KEY")
    with pytest.raises(base.ProviderError, match="TIINGO_API_KEY"):
        tiingo.TiingoProvider()


def test_logs_never_carry_the_key(mock, monkeypatch, caplog):
    monkeypatch.setenv("TIINGO_API_KEY", SENTINEL)
    base_url = "https://api.tiingo.com/tiingo/daily"
    mock.add(responses.GET, f"{base_url}/NOSUCH", status=404, json={"detail": "Not found."})
    mock.add(responses.GET, f"{base_url}/VTI", status=429, headers={"Retry-After": "1"})
    mock.add(responses.GET, f"{base_url}/VTI", json={"name": "V"})
    provider = tiingo.TiingoProvider(sleep=lambda seconds: None)
    with caplog.at_level(logging.DEBUG):
        assert provider.fetch_meta("NOSUCH") is None
        assert provider.fetch_meta("VTI") is not None
        logging.getLogger(tiingo.__name__).info("Authorization: Token %s", SENTINEL)
    assert mock.calls[0].request.headers["Authorization"] == f"Token {SENTINEL}"
    text = caplog.text
    assert SENTINEL not in text
    for match in re.finditer(r"\bToken\s+(\S+)", text):
        assert match.group(1) == "[redacted]"
    assert "Token [redacted]" in text
    lines = [r.getMessage() for r in caplog.records if r.name == tiingo.__name__]
    assert sum(1 for line in lines if re.search(r"\b404\b", line)) == 1
    assert sum(1 for line in lines if re.search(r"\b429\b", line)) == 1
