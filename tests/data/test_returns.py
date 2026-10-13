"""Canonical record, the union calendar and the window sample (spec 4.1, 4.2, 5.6)."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from portfoliosight.data import returns

N_DAYS = 120
GAP = range(20, 25)
C_START = 60


def _provider_frame(rows: list[tuple[str, float, float, float]]) -> pd.DataFrame:
    index = pd.DatetimeIndex([r[0] for r in rows], name="date")
    return pd.DataFrame(
        {
            "close": [r[1] for r in rows],
            "adj_close": [r[1] for r in rows],
            "div_cash": [r[2] for r in rows],
            "split_factor": [r[3] for r in rows],
        },
        index=index,
        dtype=float,
    )


HAND_ROWS = [
    ("2024-01-02", 100.0, 0.0, 1.0),
    ("2024-01-03", 102.0, 1.0, 1.0),  # dividend
    ("2024-01-04", 26.0, 0.0, 4.0),  # 4:1 split
    ("2024-01-05", 13.0, 0.5, 2.0),  # split and dividend on one day
]


@pytest.mark.parametrize(
    ("basis_rule", "last_growth"),
    [("post_split", (13.0 * 2.0 + 0.5 * 2.0) / 26.0), ("pre_split", (13.0 * 2.0 + 0.5) / 26.0)],
)
def test_record_follows_the_formula_by_hand(basis_rule, last_growth):
    frame = _provider_frame(HAND_ROWS)
    record = returns.provider_rows_to_record(frame, basis_rule=basis_rule)
    assert list(record.columns) == ["date", "close", "tr_index", "div_cash", "split_factor"]
    assert record["date"].dt.tz is None and len(record) == 4
    expected = [1.0, 103.0 / 100.0]
    expected.append(expected[-1] * (26.0 * 4.0) / 102.0)
    expected.append(expected[-1] * last_growth)
    assert record["tr_index"].iloc[0] == 1.0
    np.testing.assert_allclose(record["tr_index"].to_numpy(), expected, rtol=1e-14)
    np.testing.assert_array_equal(record["close"].to_numpy(), [100.0, 102.0, 26.0, 13.0])
    np.testing.assert_array_equal(record["div_cash"].to_numpy(), [0.0, 1.0, 0.0, 0.5])
    np.testing.assert_array_equal(record["split_factor"].to_numpy(), [1.0, 1.0, 4.0, 2.0])
    # The split is not a crash: the raw close fell 75%, the index did not.
    assert abs(record["tr_index"].iloc[2] / record["tr_index"].iloc[1] - 1.0) < 0.05


def test_tr_index_ignores_adj_close_and_sorts_rows():
    frame = _provider_frame(HAND_ROWS)
    base = returns.build_tr_index(frame)
    assert isinstance(base, pd.Series) and base.index.equals(frame.index)
    scrambled = frame.assign(adj_close=frame["adj_close"] * [3.0, 0.5, 9.0, 2.0])
    assert returns.build_tr_index(scrambled).to_numpy().tobytes() == base.to_numpy().tobytes()
    without = returns.build_tr_index(frame.drop(columns=["adj_close"]))
    assert without.to_numpy().tobytes() == base.to_numpy().tobytes()
    shuffled = returns.provider_rows_to_record(frame.iloc[[2, 0, 3, 1]])
    pd.testing.assert_frame_equal(shuffled, returns.provider_rows_to_record(frame))


def test_missing_actions_and_bad_rows_are_refused():
    frame = _provider_frame(HAND_ROWS[:3])
    assert returns.build_tr_index(frame.iloc[:0]).empty
    with pytest.raises(ValueError, match="unknown basis rule"):
        returns.build_tr_index(frame, basis_rule="sideways")  # type: ignore[arg-type]
    bad = _provider_frame([("2024-01-02", 100.0, 0.0, 1.0), ("2024-01-03", 0.0, 0.0, 1.0)])
    with pytest.raises(ValueError, match="2024-01-03 has no positive close"):
        returns.build_tr_index(bad)
    # A missing split on the 4:1 day must not become "no split" (a 75% crash that never was).
    for column, value in (
        ("split_factor", np.nan),
        ("div_cash", np.nan),
        ("split_factor", 0.0),
        ("div_cash", -1.0),
    ):
        broken = frame.copy()
        broken.loc[broken.index[2], column] = value
        with pytest.raises(ValueError, match="2024-01-04 has no usable div_cash or split_factor"):
            returns.build_tr_index(broken)
        with pytest.raises(ValueError, match="2024-01-04"):
            returns.provider_rows_to_record(broken)


def _record(days, level) -> pd.DataFrame:
    level = np.asarray(level, dtype=float)
    return pd.DataFrame(
        {
            "date": pd.DatetimeIndex(days),
            "close": 50.0 * level,
            "tr_index": level / level[0],
            "div_cash": np.nan,
            "split_factor": np.nan,
        }
    )


@pytest.fixture
def three_records():
    grid = pd.bdate_range("2024-01-02", periods=N_DAYS)
    rng = np.random.default_rng(5)
    keep = {
        "A": list(range(N_DAYS)),
        "B": [i for i in range(N_DAYS) if i not in GAP],
        "C": list(range(C_START, N_DAYS)),
    }
    records = {}
    for fund, positions in keep.items():
        walk = np.cumprod(1.0 + rng.normal(0.0004, 0.011, N_DAYS))
        records[fund] = _record([grid[i] for i in positions], [walk[i] for i in positions])
    return grid, records


@pytest.fixture
def no_filling(monkeypatch):
    """Every pandas fill path raises while the code under test runs."""

    def banned(self, *args, **kwargs):
        raise AssertionError("a pandas fill method was called")

    for cls in (pd.DataFrame, pd.Series):
        for name in ("ffill", "bfill", "interpolate"):
            monkeypatch.setattr(cls, name, banned)


def test_union_calendar_and_gaps_stay_missing(three_records, no_filling):
    grid, records = three_records
    frame = returns.build_returns(records)
    assert isinstance(frame.index, pd.DatetimeIndex) and frame.index.name == "date"
    assert frame.index.tz is None and list(frame.index) == list(grid)
    assert list(frame.columns) == ["A", "B", "C"]
    a = records["A"].set_index("date")["tr_index"]
    np.testing.assert_allclose(
        frame["A"].to_numpy()[1:], (a / a.shift(1) - 1.0).to_numpy()[1:], rtol=0, atol=1e-15
    )
    assert np.isnan(frame["A"].iloc[0])
    gap_and_after = [grid[i] for i in list(GAP) + [GAP[-1] + 1]]
    assert frame.loc[gap_and_after, "B"].isna().all()
    assert np.isfinite(frame.loc[grid[GAP[-1] + 2], "B"])
    assert np.isfinite(frame.loc[grid[GAP[0] - 1], "B"])
    assert frame.loc[grid[: C_START + 1], "C"].isna().all()
    assert np.isfinite(frame.loc[grid[C_START + 1], "C"])
    assert not (frame.loc[[grid[i] for i in GAP], "B"] == 0.0).any()


def test_price_only_rows_give_no_return(no_filling):
    days = pd.bdate_range("2024-01-02", periods=6)
    record = _record(days, [1.0, 1.01, 1.02, 1.03, 1.04, 1.05])
    record.loc[4:, "tr_index"] = np.nan  # price-only after adjusted_through
    frame = returns.build_returns({"X": record})
    assert list(frame.index) == list(days)
    assert np.isfinite(frame["X"].iloc[1:4]).all() and frame["X"].iloc[4:].isna().all()


def test_window_sample_is_the_intersection(three_records, no_filling):
    grid, records = three_records
    frame = returns.build_returns(records)
    first, last = grid[0].date(), grid[-1].date()
    sample = returns.window_sample(frame, ["A", "B", "C"], first, last)
    assert len(sample) == N_DAYS - C_START - 1
    assert list(sample.columns) == ["A", "B", "C"] and np.isfinite(sample.to_numpy()).all()
    pair = returns.window_sample(frame, ["A", "B"], first, last)
    assert len(pair) == (N_DAYS - 1) - len(GAP) - 1
    assert not {grid[i] for i in GAP} & set(pair.index)
    assert grid[GAP[-1] + 1] not in pair.index and grid[GAP[-1] + 2] in pair.index
    one = returns.window_sample(frame, ["A"], grid[100].date(), grid[100].date())
    assert list(one.index) == [grid[100]]
    assert returns.window_sample(frame, ["A"], date(2020, 1, 1), date(2020, 12, 31)).empty
    np.testing.assert_array_equal(pair["B"].to_numpy(), frame.loc[pair.index, "B"].to_numpy())


def test_build_returns_of_nothing_is_empty():
    frame = returns.build_returns({})
    assert frame.empty and frame.index.name == "date"
