"""The provider Protocol (spec 5.1) and the types every provider shares."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol, runtime_checkable

import pandas as pd

PROVIDER_COLUMNS = ("close", "adj_close", "div_cash", "split_factor")


@dataclass(frozen=True)
class SymbolMeta:
    name: str
    first_date: date | None
    last_date: date | None
    kind: str  # etf | mutual_fund | stock | tsp


class ProviderError(Exception):
    """A provider answered with something the adapter cannot use."""


class RateLimited(ProviderError):
    """The provider answered HTTP 429."""

    def __init__(self, message: str = "", retry_after: float | None = None):
        super().__init__(message)
        self.retry_after = retry_after


@runtime_checkable
class PriceProvider(Protocol):
    name: str

    def fetch_daily(self, symbol: str, start: date, end: date | None) -> pd.DataFrame:
        """Rows ``start..end``: tz-naive ``DatetimeIndex`` named ``date``, ``PROVIDER_COLUMNS``.

        An empty frame means the provider has no data for the symbol.
        """
        ...

    def fetch_meta(self, symbol: str) -> SymbolMeta | None: ...


def empty_frame() -> pd.DataFrame:
    """The provider frame with no rows."""
    index = pd.DatetimeIndex([], name="date")
    return pd.DataFrame({column: [] for column in PROVIDER_COLUMNS}, index=index, dtype=float)
