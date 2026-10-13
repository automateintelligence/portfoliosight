"""Tiingo end-of-day adapter (spec 5.1).

Raw ``requests`` rather than the ``tiingo`` client: the budget ledger needs a hook before every
HTTP attempt (retries included) and the limits probe needs the first 429 unretried.
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable
from datetime import date
from typing import Any

import pandas as pd
import requests

from portfoliosight.data.providers.base import (
    PROVIDER_COLUMNS,
    ProviderError,
    RateLimited,
    SymbolMeta,
    empty_frame,
)
from portfoliosight.data.secrets import install_redaction

logger = logging.getLogger(__name__)

API_ROOT = "https://api.tiingo.com/tiingo/daily"
PRICE_COLUMNS = "date,close,adjClose,divCash,splitFactor"
DEFAULT_BACKOFF_SECONDS = 60.0
MUTUAL_FUND_EXCHANGES = frozenset({"NMFQS"})
_RENAME = {
    "close": "close",
    "adjClose": "adj_close",
    "divCash": "div_cash",
    "splitFactor": "split_factor",
}


class TiingoProvider:
    """``PriceProvider`` over Tiingo's daily endpoints.

    ``before_request(symbol)`` is called before every HTTP attempt, so a ledger sees a retry as
    a second request. With ``retry_on_429=False`` the first 429 raises ``RateLimited``.
    """

    name = "tiingo"

    def __init__(
        self,
        api_key: str | None = None,
        session: requests.Session | None = None,
        sleep: Callable[[float], None] | None = None,
        *,
        before_request: Callable[[str], None] | None = None,
        retry_on_429: bool = True,
        max_retries: int = 3,
        timeout: float = 60.0,
    ):
        self._api_key = api_key if api_key is not None else os.environ.get("TIINGO_API_KEY", "")
        if not self._api_key:
            raise ProviderError("TIINGO_API_KEY is not set in the environment")
        self._session = session or requests.Session()
        self._sleep = sleep
        self.before_request = before_request
        self.retry_on_429 = retry_on_429
        self.max_retries = max_retries
        self.timeout = timeout
        install_redaction([logger.name], values=[self._api_key])

    def _wait(self, seconds: float) -> None:
        # ``time.sleep`` is looked up at call time so a caller can replace it.
        (self._sleep or time.sleep)(seconds)

    def _get(self, symbol: str, url: str, params: dict[str, str] | None = None) -> Any | None:
        """Parsed JSON of a 200, ``None`` for a 404; a 429 backs off and retries."""
        headers = {"Authorization": f"Token {self._api_key}", "Content-Type": "application/json"}
        retries = 0
        while True:
            if self.before_request is not None:
                self.before_request(symbol)
            try:
                response = self._session.get(
                    url, params=params, headers=headers, timeout=self.timeout
                )
            except requests.RequestException as exc:
                raise ProviderError(
                    f"Tiingo request for {symbol} failed: {type(exc).__name__}"
                ) from None
            status = response.status_code
            if status == 429:
                retry_after = _retry_after(response)
                if not self.retry_on_429 or retries >= self.max_retries:
                    logger.warning("tiingo %s: HTTP 429, not retried", symbol)
                    raise RateLimited(f"Tiingo answered 429 for {symbol}", retry_after)
                wait = retry_after if retry_after is not None else DEFAULT_BACKOFF_SECONDS
                logger.warning("tiingo %s: HTTP 429, backing off %.0f s", symbol, wait)
                self._wait(wait)
                retries += 1
                continue
            if status == 404:
                logger.info("tiingo %s: HTTP 404, no such symbol", symbol)
                return None
            if status != 200:
                logger.error("tiingo %s: HTTP %d", symbol, status)
                raise ProviderError(f"Tiingo answered {status} for {symbol}")
            logger.debug("tiingo %s: HTTP 200", symbol)
            try:
                return response.json()
            except ValueError:
                raise ProviderError(f"Tiingo sent a non-JSON body for {symbol}") from None

    def fetch_daily_raw(self, symbol: str, start: date, end: date | None) -> list[dict] | None:
        """Tiingo's own price rows, or ``None`` when the symbol is unknown."""
        params = {"startDate": start.isoformat(), "format": "json", "columns": PRICE_COLUMNS}
        if end is not None:
            params["endDate"] = end.isoformat()
        payload = self._get(symbol, f"{API_ROOT}/{symbol}/prices", params)
        if payload is None:
            return None
        if not isinstance(payload, list):
            raise ProviderError(f"Tiingo price payload for {symbol} is not a list of rows")
        return payload

    def fetch_meta_raw(self, symbol: str) -> dict | None:
        payload = self._get(symbol, f"{API_ROOT}/{symbol}")
        if payload is None:
            return None
        if not isinstance(payload, dict):
            raise ProviderError(f"Tiingo meta payload for {symbol} is not an object")
        return payload

    def fetch_daily(self, symbol: str, start: date, end: date | None) -> pd.DataFrame:
        rows = self.fetch_daily_raw(symbol, start, end)
        if not rows:
            return empty_frame()
        return rows_to_frame(rows, symbol)

    def fetch_meta(self, symbol: str) -> SymbolMeta | None:
        payload = self.fetch_meta_raw(symbol)
        return None if payload is None else meta_from_payload(payload, symbol)


def meta_from_payload(payload: dict, symbol: str) -> SymbolMeta:
    """Tiingo's meta object as a ``SymbolMeta``; a mutual-fund exchange code decides the kind."""
    exchange = str(payload.get("exchangeCode") or "").upper()
    return SymbolMeta(
        name=str(payload.get("name") or symbol),
        first_date=_iso_date(payload.get("startDate")),
        last_date=_iso_date(payload.get("endDate")),
        kind="mutual_fund" if exchange in MUTUAL_FUND_EXCHANGES else "etf",
    )


def rows_to_frame(rows: list[dict], symbol: str = "") -> pd.DataFrame:
    """Tiingo price rows as a provider frame (spec 5.1), sorted, one row per date."""
    missing = sorted({"date", *_RENAME} - set(rows[0]))
    if missing:
        raise ProviderError(f"Tiingo price rows for {symbol} lack the field(s) {missing}")
    # Tiingo stamps every row at midnight UTC: the calendar date is the first ten characters.
    index = pd.to_datetime([str(row["date"])[:10] for row in rows], format="%Y-%m-%d")
    frame = pd.DataFrame(
        {column: [float(row[field]) for row in rows] for field, column in _RENAME.items()},
        index=pd.DatetimeIndex(index, name="date"),
        columns=list(PROVIDER_COLUMNS),
        dtype=float,
    )
    frame = frame.loc[~frame.index.duplicated(keep="last")]
    return frame.sort_index()


def _retry_after(response: requests.Response) -> float | None:
    value = response.headers.get("Retry-After")
    try:
        seconds = float(value) if value is not None else None
    except ValueError:
        return None
    return seconds if seconds is not None and seconds >= 0 else None


def _iso_date(value: object) -> date | None:
    if not value:
        return None
    return date.fromisoformat(str(value)[:10])
