"""The synthetic 23-fund fixture: reproducible, shaped as the returns parquet, partly covered."""

from __future__ import annotations

import csv

import exchange_calendars as xcals
import numpy as np
import pandas as pd
import pytest

from tests.engine.helpers import FIXTURE, HOLDINGS, fixture_metadata, load_script

STRESS = {
    "gfc2008": ("2008-09-01", "2009-03-09"),
    "covid2020": ("2020-02-19", "2020-03-23"),
    "rates2022": ("2022-01-03", "2022-10-12"),
}
EQUITY = ["VTI", "VTV", "VOE", "VB", "VBR", "VEA", "SCHF", "VWO", "VNQ", "EFA", "DBJP"]
BONDS = ["BND", "AGG", "TIP", "VTIP", "LQD", "VWOB", "PCY", "LTPZ", "EDV"]
HYBRID = ["VBIAX", "VGSTX"]
CASH_LIKE = ["SCHO"]


@pytest.fixture(scope="module")
def make_fixtures():
    return load_script("make_fixtures")


@pytest.fixture(scope="module")
def frame() -> pd.DataFrame:
    return pd.read_parquet(FIXTURE)


def _step2() -> list[tuple[str, float]]:
    with HOLDINGS.open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    return [(row["Symbol"], float(row["Qty"]) * float(row["Price"])) for row in rows]


def test_generator_is_byte_reproducible(make_fixtures, tmp_path):
    first, second = tmp_path / "a.parquet", tmp_path / "b.parquet"
    assert make_fixtures.main(["--out", str(first)]) == 0
    assert make_fixtures.main(["--out", str(second)]) == 0
    assert first.read_bytes() == second.read_bytes()
    assert first.read_bytes() == FIXTURE.read_bytes(), "the committed fixture is stale"
    assert FIXTURE.stat().st_size > 50_000


def test_frame_is_the_returns_parquet_shape(frame):
    assert isinstance(frame.index, pd.DatetimeIndex) and frame.index.name == "date"
    assert frame.index.tz is None and frame.index.is_monotonic_increasing and frame.index.is_unique
    assert list(frame.columns) == [symbol for symbol, _ in _step2()]
    assert frame.shape[1] == 23 and all(str(dtype) == "float64" for dtype in frame.dtypes)
    calendar = xcals.get_calendar("XNYS", start="2005-01-01", end="2026-12-31")
    sessions = calendar.sessions_in_range("2005-01-03", "2026-10-12")
    assert frame.index.equals(pd.DatetimeIndex(sessions.tz_localize(None), name="date"))
    assert frame.index[0] == pd.Timestamp("2005-01-03")
    assert frame.index[-1] == pd.Timestamp("2026-10-12")
    values = frame.to_numpy()
    assert np.isfinite(values[~np.isnan(values)]).all()
    assert np.abs(np.nan_to_num(values)).max() < 0.25


def test_partial_coverage_is_deliberate(frame):
    first = {column: frame[column].first_valid_index() for column in frame.columns}
    last = {column: frame[column].last_valid_index() for column in frame.columns}
    after_gfc_start = [c for c, day in first.items() if day > pd.Timestamp("2008-09-01")]
    inside_gfc = [c for c in after_gfc_start if first[c] <= pd.Timestamp("2009-03-09")]
    assert len(after_gfc_start) >= 5 and len(inside_gfc) == 1
    assert len(frame.columns) - len(after_gfc_start) >= 15  # numbers on the 2008 card
    assert all(day == frame.index[-1] for day in last.values())  # no fund has stopped
    for column in frame.columns:  # no holes: each fund's returns are one contiguous run
        held = frame[column].loc[first[column] : last[column]]
        assert not held.isna().any(), f"{column} has a gap"
    # every fund is old enough for the 10y view and the three stress windows keep >= 50% of
    # the guide allocation covered (A-PS-50's default-preset leg needs a number on every card)
    assert max(first.values()) < pd.Timestamp("2014-01-01")
    amounts = dict(_step2())
    total = sum(amounts.values())
    for start, _end in STRESS.values():
        covered = sum(v for c, v in amounts.items() if first[c] <= pd.Timestamp(start))
        assert covered / total >= 0.5


def test_moments_are_realistic(frame):
    sigma = frame.std(ddof=1) * np.sqrt(252.0)
    mean = frame.mean() * 252.0
    assert sorted(EQUITY + BONDS + HYBRID + CASH_LIKE) == sorted(frame.columns)
    assert sigma[EQUITY].between(0.12, 0.25).all(), sigma[EQUITY]
    assert sigma[BONDS].between(0.03, 0.08).all(), sigma[BONDS]
    assert sigma[HYBRID].between(0.08, 0.12).all(), sigma[HYBRID]
    assert sigma[CASH_LIKE].between(0.003, 0.008).all(), sigma[CASH_LIKE]
    assert mean.between(-0.02, 0.20).all(), mean
    recent = frame.loc["2021-10-01":]
    assert not recent.isna().any().any()  # the five-year view uses all 23 funds
    corr = recent.corr()
    assert corr.loc["VTI", "VTV"] > 0.8 and corr.loc["BND", "AGG"] > 0.8
    assert abs(corr.loc["VTI", "BND"]) < 0.3  # separate factors, not one


def test_metadata_describes_the_guide_universe(frame):
    meta = fixture_metadata()
    assert meta["universe"] == {"name": "The 2017 guide portfolio", "preset_id": "guide2017"}
    funds = meta["funds"]
    assert sorted(funds) == sorted(frame.columns)  # fund order is the frame's column order
    keys = {
        "name",
        "kind",
        "source",
        "adjusted_through",
        "fetched_at",
        "last_close",
        "served",
        "catalog_reason",
    }
    for fund_id, entry in funds.items():
        assert set(entry) == keys, fund_id
        assert entry["kind"] in {"etf", "mutual_fund"}
        assert entry["source"] in {"seed+tiingo", "tiingo"}
        assert entry["name"] and entry["name"] != fund_id
    served = [entry for entry in funds.values() if entry["served"]]
    assert len(served) == 23  # the default menu sets no fund aside
    assert all(entry["adjusted_through"] == "2026-10-12" for entry in served)
    assert all(entry["catalog_reason"] is None for entry in served)
    closes = [entry["last_close"] for entry in served]
    assert all(isinstance(value, float) and value > 1.0 for value in closes)
    assert len(set(closes)) == len(closes)
    assert [f for f, entry in funds.items() if entry["kind"] == "mutual_fund"] == ["VBIAX", "VGSTX"]
