"""The live provider gate (spec 12 Phase 0, DoD 22; A-PS-14). Needs the key and the network.

Cost per run: two Tiingo price requests. The limits are READ from the store, never re-measured
here: a probe spends up to 60 requests and can trip the provider's hourly limit, so
``python -m portfoliosight.data.download --mode measure-limits`` is run once, by hand, against
the store this test reads (``PS_STORE`` / ``PS_LOCAL_STORE_DIR``, else the R2 bucket).
"""

from __future__ import annotations

import os
from datetime import UTC, date, datetime

import pandas as pd
import pytest

from portfoliosight.data import store as store_mod
from portfoliosight.data.limits import LIMITS_KEY
from portfoliosight.data.providers.tiingo import TiingoProvider

pytestmark = pytest.mark.live

START = date(2025, 1, 2)
COLUMNS = ["close", "adj_close", "div_cash", "split_factor"]
LIMIT_KEYS = {
    "provider",
    "tier",
    "req_per_hour",
    "req_per_day",
    "unique_symbols_per_month",
    "measured_on",
    "method",
}


@pytest.fixture(scope="module")
def frames() -> dict[str, pd.DataFrame]:
    provider = TiingoProvider()
    return {symbol: provider.fetch_daily(symbol, START, None) for symbol in ("VTI", "VBIAX")}


@pytest.mark.parametrize("symbol", ["VTI", "VBIAX"])
def test_live_frames_carry_the_four_fields(frames, symbol):
    frame = frames[symbol]
    assert list(frame.columns) == COLUMNS and len(frame) >= 250
    assert not frame.isna().to_numpy().any()
    assert isinstance(frame.index, pd.DatetimeIndex) and frame.index.tz is None
    assert frame.index.is_monotonic_increasing and frame.index.is_unique
    assert frame.index[0] >= pd.Timestamp(START)
    assert (frame["close"] > 0).all() and (frame["split_factor"] > 0).all()


def test_vbiax_has_its_december_2025_distribution(frames):
    december = frames["VBIAX"].loc["2025-12-01":"2025-12-31"]
    assert len(december) >= 15 and (december["div_cash"] > 0).any()


def test_recorded_provider_limits():
    store = store_mod.store_from_env()
    assert store.exists(LIMITS_KEY), "run `download --mode measure-limits` once against this store"
    raw = store.get(LIMITS_KEY)
    assert os.environ["TIINGO_API_KEY"].encode() not in raw
    limits = store_mod.get_json(store, LIMITS_KEY)
    assert set(limits) == LIMIT_KEYS and limits["provider"] == "tiingo"
    assert limits["method"] in ("probe", "documented") and limits["tier"].strip()
    for key in ("req_per_hour", "req_per_day", "unique_symbols_per_month"):
        assert type(limits[key]) is int and limits[key] > 0
    measured = date.fromisoformat(limits["measured_on"])
    assert date(2026, 10, 13) <= measured <= datetime.now(UTC).date()
