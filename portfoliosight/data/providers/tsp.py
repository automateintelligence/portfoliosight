"""TSP fund prices from tsp.gov (spec 5.5).

A TSP share price is already a total-return NAV, so ``adj_close`` is the price itself,
``div_cash`` is 0 and ``split_factor`` is 1. The CSV is parsed only under the exact header.
"""

from __future__ import annotations

import csv
import io
import logging
from datetime import UTC, date, datetime

import pandas as pd
import requests

from portfoliosight.data.providers.base import PROVIDER_COLUMNS, ProviderError, SymbolMeta
from portfoliosight.data.universe import TSP_FUNDS

logger = logging.getLogger(__name__)

CSV_URL = "https://www.tsp.gov/data/fund-price-history.csv"
# tsp.gov answers 403 to non-browser agents.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)
INCEPTION = date(2003, 6, 2)
# The exact column order of the CSV and the id of each fund column.
HEADER: tuple[str, ...] = (
    "Date",
    "L Income",
    "L 2030",
    "L 2035",
    "L 2040",
    "L 2045",
    "L 2050",
    "L 2055",
    "L 2060",
    "L 2065",
    "L 2070",
    "L 2075",
    "G Fund",
    "F Fund",
    "C Fund",
    "S Fund",
    "I Fund",
)
_ID_OF = {name: symbol for symbol, name in TSP_FUNDS.items()}
COLUMN_IDS: tuple[str, ...] = tuple(_ID_OF[name] for name in HEADER[1:])


class TspHeaderError(ValueError):
    """The CSV header is not exactly the expected column set and order."""


def _parse_day(cell: str) -> date:
    """tsp.gov writes ISO dates; any other spelling pandas can read is accepted too."""
    try:
        return date.fromisoformat(cell)
    except ValueError:
        return date.fromisoformat(str(pd.to_datetime(cell))[:10])


def parse_tsp_csv(text: str) -> dict[str, pd.DataFrame]:
    """One provider frame per TSP id; raises ``TspHeaderError`` unless the header is exact.

    Header cells are compared after stripping whitespace. A fund has a row only on days its
    cell holds a price.
    """
    rows = list(csv.reader(io.StringIO(text.lstrip("﻿"))))
    cells = [cell.strip() for cell in rows[0]] if rows else []
    for position, expected in enumerate(HEADER):
        found = cells[position] if position < len(cells) else None
        if found != expected:
            raise TspHeaderError(
                f"TSP CSV column {position + 1}: expected {expected!r}, found {found!r}"
            )
    if len(cells) > len(HEADER):
        extra = cells[len(HEADER)]
        raise TspHeaderError(f"TSP CSV column {len(HEADER) + 1}: unexpected column {extra!r}")

    prices: dict[str, dict[date, float]] = {symbol: {} for symbol in COLUMN_IDS}
    for row in rows[1:]:
        if not row or not row[0].strip():
            continue
        day = _parse_day(row[0].strip())
        for symbol, cell in zip(COLUMN_IDS, row[1:], strict=False):
            if cell.strip():
                prices[symbol][day] = float(cell)

    frames: dict[str, pd.DataFrame] = {}
    for symbol, by_day in prices.items():
        days = sorted(by_day)
        close = [by_day[day] for day in days]
        frames[symbol] = pd.DataFrame(
            {
                "close": close,
                "adj_close": close,
                "div_cash": [0.0] * len(days),
                "split_factor": [1.0] * len(days),
            },
            index=pd.DatetimeIndex(pd.to_datetime([day.isoformat() for day in days]), name="date"),
            columns=list(PROVIDER_COLUMNS),
            dtype=float,
        )
    return frames


class TspProvider:
    """``PriceProvider`` over the tsp.gov CSV; one download serves all 16 funds."""

    name = "tsp"

    def __init__(self, session: requests.Session | None = None, timeout: float = 60.0):
        self._session = session or requests.Session()
        self.timeout = timeout
        self._cache: dict[tuple[date, date], dict[str, pd.DataFrame]] = {}

    def fetch_csv(self, start: date, end: date) -> str:
        """The CSV as served. tsp.gov may answer with more history than asked for."""
        params = {
            "startdate": start.isoformat(),
            "enddate": end.isoformat(),
            "Lfunds": "1",
            "InvFunds": "1",
            "download": "1",
        }
        try:
            response = self._session.get(
                CSV_URL, params=params, headers={"User-Agent": USER_AGENT}, timeout=self.timeout
            )
        except requests.RequestException as exc:
            raise ProviderError(f"tsp.gov request failed: {type(exc).__name__}") from None
        if response.status_code != 200:
            logger.error("tsp.gov: HTTP %d", response.status_code)
            raise ProviderError(f"tsp.gov answered {response.status_code}")
        response.encoding = response.encoding or "utf-8"
        return response.text

    def fetch_all(self, start: date, end: date | None = None) -> dict[str, pd.DataFrame]:
        """Frames for all 16 funds over ``start..end`` (``end`` defaults to today, UTC)."""
        last = end if end is not None else datetime.now(UTC).date()
        key = (max(start, INCEPTION), last)
        if key not in self._cache:
            # The download can ignore the date range, so the range is applied here as well.
            first, final = pd.Timestamp(key[0]), pd.Timestamp(key[1])
            self._cache[key] = {
                symbol: frame.loc[(frame.index >= first) & (frame.index <= final)]
                for symbol, frame in parse_tsp_csv(self.fetch_csv(*key)).items()
            }
        return self._cache[key]

    def _frames(self, symbol: str, start: date, end: date | None) -> dict[str, pd.DataFrame]:
        if symbol not in TSP_FUNDS:
            raise ProviderError(f"{symbol} is not a TSP fund id")
        return self.fetch_all(start, end)

    def fetch_daily(self, symbol: str, start: date, end: date | None) -> pd.DataFrame:
        return self._frames(symbol, start, end)[symbol].copy()

    def fetch_meta(self, symbol: str) -> SymbolMeta | None:
        """Display name and the priced date range, from the full history."""
        frame = self._frames(symbol, INCEPTION, None)[symbol]
        if frame.empty:
            return None
        return SymbolMeta(
            name=TSP_FUNDS[symbol],
            first_date=date.fromisoformat(str(frame.index[0])[:10]),
            last_date=date.fromisoformat(str(frame.index[-1])[:10]),
            kind="tsp",
        )
