import math

import numpy as np
import pandas as pd
import pytest

from portfoliosight.research.fixedrisk import realized as R

from .synth import HOLDINGS, build_run, synth_horizon

DAYS = pd.to_datetime(["2020-01-30", "2020-01-31", "2020-02-03", "2020-02-04"])
A_B = np.array([[0.10, 0.0], [0.0, 0.0], [0.10, 0.0], [0.0, 0.10]])
W = np.array([0.5, 0.5])


def test_rebalance_positions_exclude_horizon_end():
    days = pd.to_datetime(["2020-01-30", "2020-01-31", "2020-02-03", "2020-02-28", "2020-03-02"])
    assert R.rebalance_positions(days).tolist() == [1, 3]
    # a horizon that ends on a month's last session does not rebalance on its final day
    assert R.rebalance_positions(days[:2]).tolist() == []


def test_monthly_rebalancing_and_turnover_by_hand():
    out = R.monthly_rebalanced(A_B, DAYS, W)
    # day 0: (.55, .50), total 1.05; Jan 31 close: drift (.55/1.05, .50/1.05) -> trade to .525 each
    drift_a = 0.55 / 1.05
    turnover = 0.5 * (abs(0.5 - drift_a) + abs(0.5 - (1 - drift_a)))
    assert out.turnover[0] == pytest.approx(turnover)
    # Feb 3: A +10% -> (.5775, .525); Feb 4: B +10% -> (.5775, .5775)
    assert out.annual[0] == pytest.approx(1.155 - 1)
    daily = R.daily_rebalanced(A_B, W)
    assert daily.annual[0] == pytest.approx(1.05**3 - 1)


def test_cost_deducts_funding_and_rebalance_turnover():
    cost = 0.01  # 100 bp
    out = R.monthly_rebalanced(A_B, DAYS, W, cost_bp=100.0)
    holdings = W * (1 - cost)  # funded from cash at turnover 1.0
    held = holdings * np.array([1.1, 1.0])  # day 0; Jan 31 return is 0
    value = held.sum()
    trade = 0.5 * np.abs(W - held / value).sum()
    value *= 1 - cost * trade
    holdings = W * value
    holdings = holdings * np.array([1.1, 1.0])  # Feb 3
    holdings = holdings * np.array([1.0, 1.1])  # Feb 4
    assert out.annual[0] == pytest.approx(holdings.sum() - 1)
    assert out.turnover[0] == pytest.approx(trade)  # funding not counted in the rebalance sum


def test_drawdown_uses_initial_wealth_as_peak():
    days = pd.to_datetime(["2020-01-02", "2020-01-03"])
    out = R.daily_rebalanced(np.array([[0.10], [-0.20]]), [1.0])
    assert out.drawdown[0] == pytest.approx(1 - 0.88 / 1.10)
    down = R.daily_rebalanced(np.array([[-0.10], [0.05]]), [1.0])
    assert down.drawdown[0] == pytest.approx(0.10)
    assert len(days) == 2


def test_weights_must_match_holdings():
    with pytest.raises(ValueError):
        R.daily_rebalanced(A_B, [1.0, 0.0, 0.0])


def _cpi():
    idx = pd.to_datetime(["2020-01-01", "2020-02-01", "2021-01-01", "2021-02-01"])
    return pd.Series([100.0, 101.0, 110.0, 111.0], index=idx)


def test_cpi_uses_origin_month_and_end_month():
    # origin in Jan 2020 (wealth start), horizon ends Jan 2021: ratio 110/100, not 110/101
    assert R.cpi_factor(_cpi(), "2020-01-31", "2021-01-29") == pytest.approx(1.10)
    assert R.real_return(0.21, 1.10) == pytest.approx(1.21 / 1.10 - 1)
    assert math.isnan(R.cpi_factor(_cpi(), "2020-01-31", "2021-06-30"))
    assert math.isnan(R.real_return(0.1, math.nan))


def _dgs(change: float) -> pd.Series:
    idx = pd.bdate_range("2020-01-01", periods=10)
    vals = np.full(10, 2.0)
    vals[5:] = 2.0 + change
    return pd.Series(vals, index=idx)


def test_regime_priority():
    origin, end = "2020-01-02", "2020-01-14"
    spy_crash = pd.Series(
        [100.0, 101, 80, 85, 90, 95, 95, 95, 95, 95], index=pd.bdate_range("2020-01-01", periods=10)
    )
    spy_calm = pd.Series([100.0, 101, 99, 100, 101, 102, 102, 102, 102, 102], index=spy_crash.index)
    assert (
        R.regime_label(spy_crash, _dgs(2.0), origin, end) == "equity drawdown"
    )  # beats rate shock
    assert R.regime_label(spy_calm, _dgs(2.0), origin, end) == "rate shock"
    assert R.regime_label(spy_calm, _dgs(1.5), origin, end) == "rate shock"  # exactly 150 bp
    assert R.regime_label(spy_calm, _dgs(1.49), origin, end) == "calm"
    assert R.regime_label(spy_calm, _dgs(-3.0), origin, end) == "calm"  # a fall is not a shock


def test_regime_drawdown_threshold_is_inclusive_and_starts_at_origin_level():
    idx = pd.bdate_range("2020-01-01", periods=6)
    spy = pd.Series([100.0, 100, 85, 90, 90, 90], index=idx)
    # origin 2020-01-02 (level 100) -> 85 is exactly a 15% fall
    assert R.regime_label(spy, _dgs(0.0), idx[1], idx[5]) == "equity drawdown"
    spy2 = pd.Series([100.0, 100, 85.01, 90, 90, 90], index=idx)
    assert R.regime_label(spy2, _dgs(0.0), idx[1], idx[5]) == "calm"


def test_realized_table_complete_and_incomplete(tmp_path):
    from portfoliosight.research.fixedrisk.measures import load_run

    months = build_run(tmp_path, n_months=20, engines=("replay",))
    tables = load_run(tmp_path)
    cpi = pd.Series(
        np.linspace(100, 130, 60), index=pd.date_range("2010-01-01", periods=60, freq="MS")
    )
    spy = pd.Series(np.linspace(100, 150, 2000), index=pd.bdate_range("2009-12-01", periods=2000))
    dgs = pd.Series(2.0, index=spy.index)

    def span(menu, month, n):
        hz = synth_horizon(20, 16)(menu, month)
        if hz is None:
            return None
        days = pd.bdate_range(hz[0][0], periods=n)
        return list(days), np.random.default_rng(1).normal(0.0004, 0.01, size=(n, 3))

    out = R.realized_table(
        tables.selections, synth_horizon(20, 10), span=span, cpi=cpi, spy_tr=spy, dgs10=dgs
    )
    assert len(out) == len(tables.selections)
    done = out[out["complete"]]
    assert set(pd.to_datetime(done["horizon_end"]).dt.year) <= {2010, 2011}
    last = tables.selections.merge(out, on="sel_id").loc[lambda f: f["month"] == months[-1]]
    assert not last["complete"].any() and last["ret_m"].isna().all()
    ok = done.dropna(subset=["ret_3y"])
    assert len(ok) > 0 and ok["real_3y"].notna().all()
    assert (done["regime"] == "calm").all()
    assert (done["ret_net"] < done["ret_m"] + 1e-9).all()
    assert done["real_m"].notna().all()
    assert HOLDINGS == ("A", "B", "C")
