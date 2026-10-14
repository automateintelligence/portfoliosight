"""A provider that replays recorded files and never touches the network.

For the offline run of the nightly (``PS_NIGHTLY_PROVIDERS=fixture``, local container only): it
reads the recorded Tiingo rows and the tsp.gov CSV found under one directory and has no data for
anything else.

    {dir}/provider/{TICKER}.json or {TICKER}_*.json   raw Tiingo price rows
    {dir}/provider/meta_{TICKER}.json                 raw Tiingo meta object
    {dir}/**/*tsp*.csv                                the tsp.gov price history
"""

from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path

import pandas as pd

from portfoliosight.data.providers.base import SymbolMeta, empty_frame
from portfoliosight.data.providers.tiingo import meta_from_payload, rows_to_frame
from portfoliosight.data.providers.tsp import parse_tsp_csv
from portfoliosight.data.universe import TSP_FUNDS, is_tsp


def _between(frame: pd.DataFrame, start: date, end: date | None) -> pd.DataFrame:
    kept = frame.loc[frame.index >= pd.Timestamp(start)]
    return kept if end is None else kept.loc[kept.index <= pd.Timestamp(end)]


class FixtureProvider:
    """``PriceProvider`` over the recorded files of one directory."""

    name = "fixture"

    def __init__(self, directory: str | os.PathLike[str]):
        self.directory = Path(directory)
        if not self.directory.is_dir():
            raise FileNotFoundError(f"fixture directory {self.directory} does not exist")
        self._tsp: dict[str, pd.DataFrame] | None = None

    def _price_file(self, symbol: str) -> Path | None:
        """The ticker's recording; the match is exact, so ``meta_AAPL.json`` is not ``META``."""
        folder = self.directory / "provider"
        for path in sorted(folder.glob("*.json")):
            if path.stem == symbol or path.stem.startswith(f"{symbol}_"):
                return path
        return None

    def _tsp_frames(self) -> dict[str, pd.DataFrame]:
        if self._tsp is None:
            files = sorted(p for p in self.directory.rglob("*.csv") if "tsp" in p.name.lower())
            self._tsp = parse_tsp_csv(files[0].read_text(encoding="utf-8")) if files else {}
        return self._tsp

    def fetch_daily(self, symbol: str, start: date, end: date | None) -> pd.DataFrame:
        if is_tsp(symbol):
            frame = self._tsp_frames().get(symbol)
            return empty_frame() if frame is None else _between(frame, start, end).copy()
        path = self._price_file(symbol)
        if path is None:
            return empty_frame()
        rows = json.loads(path.read_text(encoding="utf-8"))
        return _between(rows_to_frame(rows, symbol), start, end) if rows else empty_frame()

    def fetch_meta(self, symbol: str) -> SymbolMeta | None:
        if is_tsp(symbol):
            frame = self._tsp_frames().get(symbol)
            if frame is None or frame.empty:
                return None
            return SymbolMeta(
                name=TSP_FUNDS.get(symbol, symbol),
                first_date=date.fromisoformat(str(frame.index[0])[:10]),
                last_date=date.fromisoformat(str(frame.index[-1])[:10]),
                kind="tsp",
            )
        path = self.directory / "provider" / f"meta_{symbol}.json"
        if not path.is_file():
            return None
        return meta_from_payload(json.loads(path.read_text(encoding="utf-8")), symbol)
