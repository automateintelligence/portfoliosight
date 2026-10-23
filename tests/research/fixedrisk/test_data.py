"""Menus, the freeze script and the data layer of the fixed-risk experiment.

The freeze tests build a throwaway mirror, git repository and destination in ``tmp_path`` (the real
mirror and checkout are never opened) and inject Tiingo and FRED. The data tests use the seeded
synthetic records of ``fakes.py`` on the real XNYS calendar.
"""

from __future__ import annotations

import json
import os
import subprocess
from datetime import date
from pathlib import Path
from types import ModuleType

import numpy as np
import pandas as pd
import pytest

from portfoliosight.research.fixedrisk import data
from portfoliosight.research.fixedrisk.menus import (
    ALL_SYMBOLS,
    RESEARCH2003,
    TSP,
    menu_named,
)
from tests.research.fixedrisk import fakes
from tests.research.fixtures import load_module

ROOT = Path(__file__).resolve().parents[3]
GIT_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "tester",
    "GIT_AUTHOR_EMAIL": "tester@example.invalid",
    "GIT_COMMITTER_NAME": "tester",
    "GIT_COMMITTER_EMAIL": "tester@example.invalid",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_SYSTEM": os.devnull,
}


# ----------------------------------------------------------------------------------- menus


def test_menus_match_the_protocol() -> None:
    assert RESEARCH2003.holdings == tuple(
        "SPY IWM IWD EFA EEM IYR TLT IEF SHY LQD VIPSX GE MSFT XOM PFE C WMT AIG INTC".split()
    )
    assert len(RESEARCH2003.holdings) == 19
    assert RESEARCH2003.upper == (0.40,) * 11 + (0.10,) * 8
    assert RESEARCH2003.lower == (0.0,) * 19
    assert TSP.holdings == ("TSP-G", "TSP-F", "TSP-C", "TSP-S", "TSP-I")
    assert TSP.upper == (0.60,) * 5
    assert len(ALL_SYMBOLS) == 25 and ALL_SYMBOLS[-1] == "SGOV"
    assert menu_named("tsp") is TSP
    with pytest.raises(ValueError):
        menu_named("example")


def test_market_cap_csv_is_the_dated_top_ten() -> None:
    text = (ROOT / data.MARKET_CAP_FILE).read_text()
    assert text.splitlines()[0].startswith("# source: https://en.wikipedia.org/wiki/List_of_public")
    assert "accessed 2026-10-23" in text.splitlines()[0]
    frame = data.read_market_caps(text.encode())
    assert list(frame["rank"]) == list(range(1, 11))
    us = frame[frame["country"] == "US"]["company"].tolist()
    assert len(us) == 8 and "General Electric" in us and "American International Group" in us
    assert frame.set_index("company").loc["Walmart", "market_value_usd_million"] == 258888


# ------------------------------------------------------------------------ the data layer


@pytest.fixture(scope="module")
def inputs() -> data.ResearchInputs:
    return fakes.synthetic_inputs()


def test_schedule_starts_after_the_first_full_window(inputs: data.ResearchInputs) -> None:
    months = data.schedule(inputs, fakes.ALPHA)
    assert months == sorted(set(months))
    ledger = inputs.ledger(fakes.ALPHA)
    # 756 union-calendar rows after the first price (2018-01-02): the first origin is the first
    # month end with at least 756 rows on or before it.
    sessions = fakes.sessions_index()
    rows = np.searchsorted(sessions, pd.Timestamp("2018-01-02"))
    first_row = sessions[rows + 755]
    expected = next(
        r.month
        for r in ledger.rows
        if pd.Timestamp(r.origin) >= first_row and r.menu("research2003").training_eligible
    )
    assert months[0] == expected
    assert months[-1] == "2025-09"
    assert all(ledger.row(m).menu("research2003").training_eligible for m in months)


def test_each_menu_has_its_own_start() -> None:
    late = fakes.synthetic_inputs(first_x="2019-06-03")
    alpha, beta = (data.schedule(late, m) for m in fakes.TEST_MENUS)
    assert beta[0] > alpha[0]
    assert late.ledger(fakes.BETA).boundary_month == "2019-06"
    assert late.ledger(fakes.ALPHA).boundary_month == "2018-01"


def test_showcase_stability_and_lookback5_months(inputs: data.ResearchInputs) -> None:
    months = data.schedule(inputs, fakes.ALPHA)
    k = len(months)
    expected = sorted({j * (k - 1) // 5 for j in range(6)})
    assert data.showcase_months(inputs, fakes.ALPHA) == [months[i] for i in expected]
    assert len(expected) == 6 and expected[0] == 0 and expected[-1] == k - 1
    assert data.stability_months(inputs, fakes.ALPHA) == months[::4]
    five = data.lookback5_months(inputs, fakes.ALPHA)
    eligible5 = set(data.schedule(inputs, fakes.ALPHA, "5y"))
    assert five and set(five) <= set(data.showcase_months(inputs, fakes.ALPHA))
    assert set(five) <= eligible5
    assert data.showcase_months(inputs, fakes.ALPHA)[0] not in five  # first origin lacks 5y


def test_disjoint_intervals_do_not_overlap(inputs: data.ResearchInputs) -> None:
    intervals = data.disjoint_intervals(inputs, fakes.ALPHA)
    assert len(intervals) >= 2
    for first, second in zip(intervals, intervals[1:], strict=False):
        assert second.origin > first.horizon_end
    for interval in intervals:
        assert interval.horizon_start > interval.origin
        assert interval.horizon_end <= fakes.D_STAR


def test_origin_context_matches_production_moments(inputs: data.ResearchInputs) -> None:
    month = data.schedule(inputs, fakes.ALPHA)[10]
    ctx = data.origin_context(inputs, fakes.ALPHA, month)
    assert ctx.sample.shape == (756, 4) and not ctx.sample.flags.writeable
    assert ctx.days[-1] == ctx.origin and len(ctx.days) == 756
    np.testing.assert_allclose(ctx.mu_hat, 252 * ctx.sample.mean(axis=0))
    np.testing.assert_allclose(ctx.sigma, np.sqrt(np.diag(ctx.cov)))
    np.testing.assert_allclose(ctx.sigma[0], np.sqrt(252) * ctx.sample[:, 0].std(ddof=1), rtol=1e-6)
    assert np.allclose(ctx.cov, ctx.cov.T)
    assert np.linalg.eigvalsh(ctx.cov).min() > 0
    assert ctx.lookback == "3y" and ctx.menu is fakes.ALPHA
    again = data.origin_context(inputs, "research2003", month)
    assert again.inputs_sha256 == ctx.inputs_sha256
    five = data.origin_context(
        inputs, fakes.ALPHA, data.lookback5_months(inputs, fakes.ALPHA)[0], "5y"
    )
    assert five.sample.shape[0] == 1260 and five.lookback == "5y"


def test_origin_context_reads_nothing_after_the_origin() -> None:
    records = fakes.synthetic_records()
    month = "2023-03"
    base = data.build_inputs(records, fakes.sessions_index(), fakes.D_STAR, menus=fakes.TEST_MENUS)
    origin = pd.Timestamp(base.ledger(fakes.ALPHA).row(month).origin)
    changed = {}
    for symbol, frame in records.items():
        frame = frame.copy()
        later = frame["date"] > origin
        frame.loc[later, ["tr_index", "close"]] *= 3.0
        changed[symbol] = frame
    other = data.build_inputs(changed, fakes.sessions_index(), fakes.D_STAR, menus=fakes.TEST_MENUS)
    a = data.origin_context(base, fakes.ALPHA, month)
    b = data.origin_context(other, fakes.ALPHA, month)
    assert a.inputs_sha256 == b.inputs_sha256
    np.testing.assert_array_equal(a.sample, b.sample)


def test_horizon_returns_are_the_next_252_rows(inputs: data.ResearchInputs) -> None:
    month = data.schedule(inputs, fakes.ALPHA)[5]
    horizon = data.horizon_returns(inputs, fakes.ALPHA, month)
    ctx = data.origin_context(inputs, fakes.ALPHA, month)
    assert horizon.status == "complete" and horizon.returns.shape == (252, 4)
    assert horizon.days[0] > ctx.origin
    assert horizon.days[-1] <= fakes.D_STAR


def test_ledger_cache_round_trip(tmp_path: Path) -> None:
    records = fakes.synthetic_records()
    kwargs = dict(menus=fakes.TEST_MENUS, manifest_sha256="a" * 64, ledger_cache=tmp_path)
    first = data.build_inputs(records, fakes.sessions_index(), fakes.D_STAR, **kwargs)
    built = first.ledger(fakes.BETA)
    assert len(list(tmp_path.glob("*.pkl"))) == 1
    second = data.build_inputs(records, fakes.sessions_index(), fakes.D_STAR, **kwargs)
    loaded = second.ledger(fakes.BETA)
    assert [r.month for r in loaded.rows] == [r.month for r in built.rows]
    assert data.schedule(second, fakes.BETA) == data.schedule(first, fakes.BETA)


def test_read_series_parses_fred_missing_values() -> None:
    series = data.read_series(b"observation_date,DGS10\n2026-01-01,.\n2026-01-02,4.25\n", "DGS10")
    assert np.isnan(series.iloc[0]) and series.iloc[1] == 4.25
    assert series.index[1] == pd.Timestamp("2026-01-02")
    with pytest.raises(ValueError):
        data.read_series(b"a,b,c\n1,2,3\n", "x")


# ------------------------------------------------------------------------- freeze script


@pytest.fixture(scope="module")
def freeze() -> ModuleType:
    return load_module("freeze_fixed_risk_inputs", ROOT / "scripts" / "freeze_fixed_risk_inputs.py")


D_STAR = date(2026, 10, 16)


def _bdays(first: str, last: str) -> pd.DatetimeIndex:
    return pd.bdate_range(first, last)


def _price_frame(index: int, last: str = "2026-10-20", first: str = "2026-01-05") -> pd.DataFrame:
    dates = _bdays(first, last)
    steps = np.arange(len(dates), dtype=float)
    return pd.DataFrame(
        {
            "date": dates,
            "close": 100.0 + index + 0.01 * steps,
            "tr_index": 1.0 + 0.001 * (index + 1) * steps,
            "div_cash": 0.0,
            "split_factor": 1.0,
        }
    )


def _provider_for(frame: pd.DataFrame, extra_to: str | None = None) -> pd.DataFrame:
    """A Tiingo-style frame consistent with the record's good tr_index values."""
    good = frame.dropna(subset=["tr_index"])
    adj = pd.Series(good["tr_index"].to_numpy() * 2.0, index=pd.DatetimeIndex(good["date"]))
    close = pd.Series(good["close"].to_numpy(), index=adj.index)
    if extra_to is not None:
        more = _bdays(adj.index[-1] + pd.Timedelta(days=1), extra_to)
        steps = np.arange(1, len(more) + 1)
        adj = pd.concat([adj, pd.Series(adj.iloc[-1] * (1 + 0.002 * steps), index=more)])
        close = pd.concat([close, pd.Series(close.iloc[-1] * (1 + 0.002 * steps), index=more)])
    return pd.DataFrame(
        {"close": close, "adj_close": adj, "div_cash": 0.0, "split_factor": 1.0}
    ).rename_axis("date")


def make_mirror(base: Path) -> tuple[Path, dict[str, pd.DataFrame]]:
    mirror = base / "mirror"
    entries, frames = {}, {}
    for index, symbol in enumerate(ALL_SYMBOLS):
        frame = _price_frame(index)
        if symbol == "WMT":
            frame = frame[frame["date"] <= "2026-10-12"].copy()
            frame.loc[frame["date"] > "2026-03-27", "tr_index"] = np.nan
        if symbol == "MSFT":
            frame.loc[frame["date"] > D_STAR.isoformat(), "tr_index"] = np.nan
        path = mirror / "prices" / f"{symbol}.parquet"
        path.parent.mkdir(parents=True, exist_ok=True)
        frame.to_parquet(path, index=False)
        frames[symbol] = frame
        entries[symbol] = {
            "name": symbol, "kind": "etf", "tier": 1, "source": "seed", "first_date": "2026-01-05",
            "last_date": "2026-10-20", "adjusted_through": "2026-10-16", "status": "ok",
            "reason": None, "relies_on_yfinance": False,
        }  # fmt: skip
    meta = mirror / "meta"
    meta.mkdir(parents=True)
    (meta / "manifest.json").write_text(json.dumps({"symbols": entries}))
    (meta / "lake.json").write_text(json.dumps({"symbols": {}}))
    return mirror, frames


def make_repo(base: Path) -> Path:
    repo = base / "repo"
    (repo / "data" / "research").mkdir(parents=True)
    (repo / "data" / "research" / "ft_global500_2004_top10.csv").write_text(
        (ROOT / "data" / "research" / "ft_global500_2004_top10.csv").read_text()
    )
    for args in (["init", "-q"], ["add", "."], ["commit", "-q", "-m", "x"]):
        subprocess.run(["git", *args], cwd=repo, env=GIT_ENV, check=True, capture_output=True)
    return repo


def fake_tiingo(frames: dict[str, pd.DataFrame], *, skew: bool = False):
    def fetch(symbol: str, start: date, end: date) -> pd.DataFrame:
        frame = _provider_for(frames[symbol], "2026-10-16" if symbol == "WMT" else None)
        if skew and symbol == "WMT":
            frame.iloc[20, frame.columns.get_loc("adj_close")] *= 1.001
        return frame

    return fetch


FRED = {
    "CPIAUCNS": (
        b"observation_date,CPIAUCNS\n2026-01-01,320.1\n2026-09-01,325.0\n2026-11-01,326.0\n"
    ),
    "DGS10": b"observation_date,DGS10\n2026-10-15,4.10\n2026-10-16,.\n2026-10-19,4.2\n",
}


def test_freeze_builds_a_verified_snapshot(freeze: ModuleType, tmp_path: Path) -> None:
    mirror, frames = make_mirror(tmp_path)
    repo = make_repo(tmp_path)
    snapshot = freeze.freeze(
        mirror=mirror, root=tmp_path / "snaps", repo=repo, tiingo=fake_tiingo(frames),
        fred=lambda series: FRED[series],
    )  # fmt: skip
    manifest = freeze.verify_snapshot(snapshot)
    assert snapshot.name == f"2026-10-16-{manifest['manifest_sha256'][:12]}"
    paths = {entry["path"] for entry in manifest["files"]}
    expected = {
        "prices/WMT.parquet",
        "macro/CPIAUCNS.csv",
        "macro/DGS10.csv",
        "reports/corporate_action_check.json",
        "data/research/ft_global500_2004_top10.csv",
        "calendar/xnys_sessions.csv",
        "environment/dependency_lock.txt",
        "meta/manifest.json",
    }
    assert expected <= paths
    assert sum(p.startswith("prices/") for p in paths) == len(ALL_SYMBOLS) == 25
    # every record is cut at D*
    for symbol in ALL_SYMBOLS:
        frame = pd.read_parquet(snapshot / "prices" / f"{symbol}.parquet")
        assert frame["date"].max() <= pd.Timestamp(D_STAR)
        assert frame["tr_index"].notna().all()
    wmt = pd.read_parquet(snapshot / "prices" / "WMT.parquet")
    assert wmt["date"].max() == pd.Timestamp(D_STAR) and len(wmt) == len(
        _bdays("2026-01-05", D_STAR.isoformat())
    )
    repair = manifest["repairs"]["WMT"]
    holes = int(frames["WMT"]["tr_index"].isna().sum())
    assert holes > 100
    assert (
        repair["rows_spliced"] == holes + 4 and repair["overlap_max_abs_return_difference"] < 1e-6
    )
    assert repair["mirror_rows_replaced"] == holes
    # FRED truncated at D*, vintage recorded
    assert "2026-11-01" not in (snapshot / "macro" / "CPIAUCNS.csv").read_text()
    assert manifest["fred"]["CPIAUCNS"]["last_observation"] == "2026-09-01"
    assert manifest["fred"]["DGS10"]["last_non_missing"] == "2026-10-15"
    assert manifest["fred"]["DGS10"]["downloaded_utc"]
    assert set(manifest["menus"]) == {"research2003", "tsp"}
    assert manifest["menus"]["research2003"]["upper"][-1] == 0.10
    report = json.loads((snapshot / "reports" / "corporate_action_check.json").read_text())
    assert set(report["symbols"]) == {*"GE MSFT XOM PFE C WMT AIG INTC VIPSX".split()}
    # the data layer reads it back
    inputs = data.load_inputs(snapshot)
    assert inputs.manifest_sha256 == manifest["manifest_sha256"]
    assert inputs.records["WMT"]["tr_index"].notna().all()
    assert inputs.cpi.iloc[-1] == 325.0
    assert inputs.dgs10.index[-1] == pd.Timestamp("2026-10-16") and np.isnan(inputs.dgs10.iloc[-1])
    assert len(inputs.market_caps) == 10
    # immutable: files are read-only, and verify catches a change
    victim = snapshot / "prices" / "SPY.parquet"
    assert not os.access(victim, os.W_OK)
    os.chmod(victim, 0o644)
    victim.write_bytes(victim.read_bytes() + b"x")
    with pytest.raises(freeze.FreezeError) as raised:
        freeze.verify_snapshot(snapshot)
    assert raised.value.code == 6


def test_freeze_refuses_a_dirty_repository(freeze: ModuleType, tmp_path: Path) -> None:
    mirror, frames = make_mirror(tmp_path)
    repo = make_repo(tmp_path)
    csv = repo / "data" / "research" / "ft_global500_2004_top10.csv"
    csv.write_text(csv.read_text() + "11,X,US,1\n")
    with pytest.raises(freeze.FreezeError) as raised:
        freeze.freeze(mirror=mirror, root=tmp_path / "snaps", repo=repo, tiingo=fake_tiingo(frames),
                      fred=lambda s: FRED[s])  # fmt: skip
    assert raised.value.code == 3 and "uncommitted" in str(raised.value)


def test_freeze_stops_when_adj_close_disagrees_with_tr_index(
    freeze: ModuleType, tmp_path: Path
) -> None:
    mirror, frames = make_mirror(tmp_path)
    repo = make_repo(tmp_path)
    with pytest.raises(freeze.FreezeError) as raised:
        freeze.freeze(mirror=mirror, root=tmp_path / "snaps", repo=repo,
                      tiingo=fake_tiingo(frames, skew=True), fred=lambda s: FRED[s])  # fmt: skip
    assert raised.value.code == 3 and "not splicing" in str(raised.value)
    assert not (tmp_path / "snaps").exists() or not any((tmp_path / "snaps").glob("2026*"))


def test_destination_inside_the_repository_is_refused(freeze: ModuleType, tmp_path: Path) -> None:
    mirror, frames = make_mirror(tmp_path)
    repo = make_repo(tmp_path)
    with pytest.raises(freeze.FreezeError) as raised:
        freeze.freeze(mirror=mirror, root=repo / "snaps", repo=repo, tiingo=fake_tiingo(frames),
                      fred=lambda s: FRED[s])  # fmt: skip
    assert raised.value.code == 2


def test_action_days_and_yearly_comparison(freeze: ModuleType) -> None:
    dates = _bdays("2020-01-01", "2020-01-10")
    close = [100.0, 101.0, 50.5, 51.0, 52.0, 53.0, 54.0, 55.0]
    tr = [1.0, 1.01, 1.0201, 1.03, 1.04, 1.05, 1.06, 1.07]
    frame = pd.DataFrame(
        {
            "date": dates,
            "close": close,
            "tr_index": tr,
            "div_cash": 0.0,
            "split_factor": [1, 1, 2, 1, 1, 1, 1, 1.0],
        }
    )
    days = freeze.action_days(frame)
    assert [d["date"] for d in days] == ["2020-01-03"]
    assert days[0]["close_return"] == pytest.approx(-0.5) and days[0][
        "tr_index_return"
    ] == pytest.approx(0.01)
    adj = pd.Series(np.array(tr) * 1.0, index=dates)
    years = freeze.yearly_comparison(frame, adj)
    assert len(years) == 1 and not years[0]["flag"]
    adj.iloc[-1] *= 1.02
    flagged = freeze.yearly_comparison(frame, adj)
    assert flagged[0]["flag"] and flagged[0]["difference_bp"] < -150


def test_fred_truncation_requires_data_before_d_star(freeze: ModuleType) -> None:
    with pytest.raises(freeze.FreezeError):
        freeze.fred_truncated(b"observation_date,DGS10\n2027-01-01,4\n", D_STAR, "DGS10")
    with pytest.raises(freeze.FreezeError):
        freeze.fred_truncated(b"observation_date,WRONG\n2026-01-01,4\n", D_STAR, "DGS10")


def test_repair_needs_a_clean_prefix_and_overlap(freeze: ModuleType) -> None:
    frame = _price_frame(0, "2026-10-12")
    frame.loc[frame["date"] > "2026-03-27", "tr_index"] = np.nan
    provider = _provider_for(frame, "2026-10-16")
    repaired, report = freeze.repair_record(frame, provider, D_STAR)
    ratio = repaired["tr_index"].to_numpy()[-1] / repaired["tr_index"].to_numpy()[-2]
    assert ratio == pytest.approx(provider["adj_close"].iloc[-1] / provider["adj_close"].iloc[-2])
    assert report["dates_only_in_provider"] == [
        "2026-10-13",
        "2026-10-14",
        "2026-10-15",
        "2026-10-16",
    ]
    short = frame[frame["date"] >= "2026-03-20"]
    with pytest.raises(freeze.FreezeError):
        freeze.repair_record(short, provider, D_STAR)
    hole = frame.copy()
    hole.loc[5, "tr_index"] = np.nan
    with pytest.raises(freeze.FreezeError):
        freeze.repair_record(hole, provider, D_STAR)


def test_cli_verify_mode(freeze: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    mirror, frames = make_mirror(tmp_path)
    repo = make_repo(tmp_path)
    snapshot = freeze.freeze(mirror=mirror, root=tmp_path / "snaps", repo=repo,
                             tiingo=fake_tiingo(frames), fred=lambda s: FRED[s])  # fmt: skip
    assert freeze.main(["--verify", str(snapshot)]) == 0
    assert str(snapshot) in capsys.readouterr().out
    assert freeze.main(["--verify", str(tmp_path / "nowhere")]) == 6
