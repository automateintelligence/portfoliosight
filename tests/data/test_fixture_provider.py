"""The offline provider replays the recorded files and has no data for anything else."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from portfoliosight.data.providers.base import PROVIDER_COLUMNS, PriceProvider
from portfoliosight.data.providers.fixture import FixtureProvider

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


@pytest.fixture
def provider() -> FixtureProvider:
    return FixtureProvider(FIXTURES)


def test_it_is_a_price_provider(provider):
    assert isinstance(provider, PriceProvider) and provider.name == "fixture"


def test_recorded_tiingo_rows_are_replayed_and_sliced(provider):
    frame = provider.fetch_daily("AAPL", date(2020, 8, 28), None)
    assert list(frame.columns) == list(PROVIDER_COLUMNS) and frame.index.name == "date"
    assert str(frame.index[0])[:10] == "2020-08-28"
    assert frame["split_factor"].max() == 4.0  # the August 2020 split is in the recording
    bounded = provider.fetch_daily("AAPL", date(2020, 8, 3), date(2020, 8, 4))
    assert [str(day)[:10] for day in bounded.index] == ["2020-08-03", "2020-08-04"]
    meta = provider.fetch_meta("VTI")
    assert meta is not None and meta.kind == "etf" and "Vanguard" in meta.name


def test_a_ticker_matches_its_own_file_only(provider):
    assert not provider.fetch_daily("TR", date(2024, 1, 1), None).empty
    for symbol in ("T", "V", "AAP", "META", "NOSUCH"):
        assert provider.fetch_daily(symbol, date(1970, 1, 1), None).empty
        assert provider.fetch_meta(symbol) is None


def test_tsp_funds_come_from_the_recorded_csv(provider):
    frame = provider.fetch_daily("TSP-G", date(2026, 3, 30), None)
    assert [str(day)[:10] for day in frame.index] == ["2026-03-30", "2026-03-31"]
    assert frame["close"].iloc[-1] == 19.7918 and (frame["split_factor"] == 1.0).all()
    meta = provider.fetch_meta("TSP-L2030")
    assert meta is not None and meta.name == "L 2030" and meta.kind == "tsp"
    assert meta.last_date == date(2026, 3, 31)
    assert provider.fetch_daily("TSP-NOPE", date(2026, 1, 1), None).empty
    assert provider.fetch_meta("TSP-NOPE") is None


def test_a_directory_without_recordings_has_no_data(tmp_path):
    empty = FixtureProvider(tmp_path)
    assert empty.fetch_daily("VTI", date(2020, 1, 1), None).empty
    assert empty.fetch_daily("TSP-G", date(2020, 1, 1), None).empty
    assert empty.fetch_meta("TSP-G") is None
    with pytest.raises(FileNotFoundError):
        FixtureProvider(tmp_path / "missing")
