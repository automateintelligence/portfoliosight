"""Fixed-weight evaluation at one origin (protocol 3, 4, 5 steps 1 and 5, 6 and 8; plan 6.3).

Every fixture is synthetic: funds A, B, C, D and SGOV priced on the XNYS sessions of the installed
`exchange_calendars` from 2023-01-03, with seeded random daily returns; D has no 2024-05-15
price. Menus: m = (A, B, C) and n = (A, D); lookback 1y (252 rows); D* 2025-03-31. Expectations
come from oracles written here: training and horizon rows cut straight from the generated
total-return arrays, explicit day-by-day multiplication of the recentred growth along the bank's
day indices, a sorted and interpolated percentile, a sorted expected shortfall, and realized
years worked out by hand. The production estimators (`estimate_moments`, `menu_beta_blend`,
`one_year_ranges`) are the references the protocol pins, not the code under test.

Ledger facts the tests rest on (the 6.1 ledger of this fixture): 2023-12 is training-ineligible
(250 union rows, 252 needed); 2024-01 (origin 2024-01-31) is mature, its window starts
2023-01-31, its horizon 2024-02-01 .. 2025-02-03 is complete in m and missing in n (D on
2024-05-15); 2024-03 is administratively immature; at 2024-06 menu n has 250 complete rows.
"""

from __future__ import annotations

import functools
import hashlib
import math
from dataclasses import replace
from datetime import date

import exchange_calendars as xcals
import numpy as np
import pandas as pd
import pytest

from portfoliosight.data.returns import build_returns
from portfoliosight.engine import ranges
from portfoliosight.engine.ranges import SEED, bootstrap_index, one_year_ranges, sample_digest
from portfoliosight.engine.stats import estimate_moments, menu_beta_blend
from portfoliosight.engine.windows import select_window
from portfoliosight.research import evaluate as evaluation
from portfoliosight.research.evaluate import (
    NONPOSITIVE_DAILY_GROWTH,
    OK,
    Horizon,
    OriginModel,
    at_or_below,
    bank,
    breaches,
    evaluate,
    origin_model,
    path_metrics,
    pinball,
    pit,
    realized,
    realized_horizon,
    simulate,
    summarize,
)
from portfoliosight.research.harness import (
    COMPLETE,
    HORIZON_MISSING,
    HORIZON_VALUE_MISSING,
    IMMATURE,
    Ledger,
    build_ledger,
)

SESSIONS = pd.DatetimeIndex(
    xcals.get_calendar("XNYS", start="2022-06-01", end="2026-06-30").sessions
)
FIRST = pd.Timestamp("2023-01-03")
D_STAR = date(2025, 3, 31)
MENUS = {"m": ("A", "B", "C"), "n": ("A", "D")}
DRIFT_VOL = {
    "A": (4e-4, 0.010),
    "B": (2e-4, 0.006),
    "C": (6e-4, 0.015),
    "D": (3e-4, 0.008),
    "SGOV": (1.5e-4, 0.0),
}
GAP = pd.Timestamp("2024-05-15")  # D has no price on this session
ORIGIN = pd.Timestamp("2024-01-31")  # the mature month 2024-01
MIXES = np.array(
    [
        [1.0, 0.0, 0.0],
        [0.0, 1.0, 0.0],
        [0.0, 0.0, 1.0],
        [1 / 3, 1 / 3, 1 / 3],
        [0.6, 0.4, 0.0],
        [0.25, 0.5, 0.25],
        [0.1, 0.3, 0.6],
        [0.45, 0.1, 0.45],
        [0.2, 0.7, 0.1],
    ]
)
FIGURES = ("bad", "typical", "good", "mean", "es_25", "p_loss", "p_below_20")


# ----------------------------------------------------------------------------------- fixtures


@functools.cache
def _tr() -> dict[str, pd.Series]:
    """Each symbol's total-return index on every session from FIRST (D's gap not removed here)."""
    days = SESSIONS[SESSIONS >= FIRST]
    rng = np.random.default_rng(20261019)
    out = {}
    for symbol, (drift, vol) in DRIFT_VOL.items():
        r = drift + vol * rng.standard_normal(len(days))
        out[symbol] = pd.Series(np.concatenate(([1.0], np.cumprod(1.0 + r[1:]))), index=days)
    return out


def _records(
    bump: tuple[tuple[str, str], ...] = (), drop: tuple[str, str] | None = None
) -> dict[str, pd.DataFrame]:
    """The price records, each (symbol, day) of ``bump`` priced 1.5 times higher, ``drop`` gone."""
    records = {}
    for symbol, series in _tr().items():
        values = series.copy()
        for name, day in bump:
            if name == symbol:
                values[pd.Timestamp(day)] *= 1.5
        if symbol == "D":
            values = values.drop(GAP)
        if drop is not None and drop[0] == symbol:
            values = values.drop(pd.Timestamp(drop[1]))
        records[symbol] = pd.DataFrame(
            {
                "date": values.index,
                "close": 100.0 * values.to_numpy(),
                "tr_index": values.to_numpy(),
                "div_cash": 0.0,
                "split_factor": 1.0,
            }
        )
    return records


@pytest.fixture(scope="module")
def ledger() -> Ledger:
    return build_ledger(_records(), SESSIONS, D_STAR, MENUS, "1y")


@pytest.fixture(scope="module")
def model(ledger: Ledger) -> OriginModel:
    return origin_model(_records(), ledger, "2024-01", "m")


def _returns_on(symbol: str, days: pd.DatetimeIndex) -> np.ndarray:
    """Each day's return against the session before it, from the generated index."""
    series = _tr()[symbol]
    position = series.index.get_indexer(days)
    assert (position > 0).all()
    values = series.to_numpy()
    return values[position] / values[position - 1] - 1.0


def _rows(days: pd.DatetimeIndex, funds: tuple[str, ...]) -> np.ndarray:
    return np.column_stack([_returns_on(fund, days) for fund in funds])


def _window(origin: str, rows: int = 252) -> pd.DatetimeIndex:
    """The last ``rows`` sessions ending at ``origin`` (every session is on the union calendar)."""
    days = _tr()["A"].index
    end = days.get_loc(pd.Timestamp(origin))
    assert isinstance(end, int)
    return pd.DatetimeIndex(days[end - rows + 1 : end + 1])


def _linear_percentile(values: np.ndarray, q: float) -> float:
    """The sorted, linearly interpolated percentile: position (n - 1) q / 100."""
    ordered = sorted(values.tolist())
    h = (len(ordered) - 1) * q / 100.0
    low = math.floor(h)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (h - low) * (ordered[high] - ordered[low])


def _explicit_years(model: OriginModel, seed: int, mix: np.ndarray) -> np.ndarray:
    """Each path's year by multiplying the recentred growth day by day along the day indices."""
    daily = (model.sample * mix).sum(axis=1)
    growth = 1.0 + daily - daily.mean() + float((model.mu_s * mix).sum()) / 252.0
    index = bootstrap_index(len(model.sample), seed=seed)
    wealth = np.ones(len(index))
    for day in range(index.shape[1]):
        wealth = wealth * growth[index[:, day]]
    return wealth - 1.0


def _bits(result) -> bytes:
    return b"".join(np.ascontiguousarray(getattr(result, name)).tobytes() for name in FIGURES)


# ------------------------------------------------------------------------- training model


def test_origin_model_rebuilds_the_training_window_with_production_estimators(
    ledger: Ledger, model: OriginModel
) -> None:
    window = _window("2024-01-31")
    assert window[0] == pd.Timestamp("2023-01-31")
    oracle = _rows(window, ("A", "B", "C"))
    assert (model.menu, model.funds, model.month, model.lookback) == (
        "m",
        ("A", "B", "C"),
        "2024-01",
        "1y",
    )
    assert model.origin == date(2024, 1, 31)
    assert model.days == tuple(day.date() for day in window)
    np.testing.assert_array_equal(model.sample, oracle)
    assert not model.sample.flags.writeable
    assert model.sample_sha256 == sample_digest(
        ["A", "B", "C"], [day.date().isoformat() for day in window], oracle
    )
    assert model.key == ("m", "2024-01-31", "1y", model.sample_sha256)

    sgov = _returns_on("SGOV", _window("2024-01-31"))  # its last 252 own-date returns at the origin
    rate = float(np.prod(1.0 + sgov) - 1.0)
    assert (model.risk_free_source, model.risk_free_rate) == ("SGOV", rate)
    assert (ledger.row("2024-01").risk_free_source, ledger.row("2024-01").risk_free_rate) == (
        "SGOV",
        rate,
    )

    # the production builder's path: `select_window`'s sample frame, `to_numpy()` (column-major;
    # the layout decides the last bit of sigma), `estimate_moments`, then `menu_beta_blend`
    records = _records()
    cut = {fund: records[fund].loc[records[fund]["date"] <= ORIGIN] for fund in ("A", "B", "C")}
    frame = select_window(build_returns(cut), "1y", ORIGIN).sample
    assert frame is not None
    np.testing.assert_array_equal(frame.to_numpy(), oracle)
    moments = estimate_moments(frame.to_numpy())
    for name in ("mu", "sigma", "cov"):
        np.testing.assert_array_equal(getattr(model.moments, name), getattr(moments, name))
    assert model.moments.t_eff == 252.0
    assert model.moments.shrinkage is not None
    assert model.moments.shrinkage == moments.shrinkage
    mu_s, _ = menu_beta_blend(moments.mu, moments.cov, rate)
    np.testing.assert_array_equal(model.mu_s, mu_s)


def test_origin_model_keeps_complete_rows_only(ledger: Ledger) -> None:
    built = origin_model(_records(), ledger, "2024-06", "n")
    # D's missing 2024-05-15 price costs that day's return and the next day's
    window = pd.DatetimeIndex(
        _window("2024-06-28").drop([pd.Timestamp("2024-05-15"), pd.Timestamp("2024-05-16")])
    )
    assert len(built.days) == 250
    assert built.days == tuple(day.date() for day in window)
    np.testing.assert_array_equal(built.sample, _rows(window, ("A", "D")))


def test_origin_model_refuses_what_the_protocol_does_not_schedule(ledger: Ledger) -> None:
    with pytest.raises(ValueError, match="not training-eligible"):
        origin_model(_records(), ledger, "2023-12", "m")
    with pytest.raises(ValueError, match="fixed-window"):
        origin_model(_records(), replace(ledger, lookback="ew"), "2024-01", "m")
    # records that are not the ledger's: B lost a day inside the 2024-01 window
    with pytest.raises(ValueError, match="ledger"):
        origin_model(_records(drop=("B", "2023-06-01")), ledger, "2024-01", "m")
    with pytest.raises(KeyError):
        origin_model(_records(), ledger, "2024-01", "absent")


def test_prices_after_the_origin_change_only_the_realized_leg(
    ledger: Ledger, model: OriginModel
) -> None:
    # prices after the origin: A inside the horizon, SGOV the day after the origin
    moved = _records(bump=(("A", "2024-06-03"), ("SGOV", "2024-02-01")))
    again = origin_model(moved, ledger, "2024-01", "m")
    assert again.sample.tobytes() == model.sample.tobytes()
    assert again.days == model.days and again.sample_sha256 == model.sample_sha256
    assert again.mu_s.tobytes() == model.mu_s.tobytes()
    assert again.moments.cov.tobytes() == model.moments.cov.tobytes()
    assert again.moments.shrinkage == model.moments.shrinkage
    assert (again.risk_free_source, again.risk_free_rate) == (
        model.risk_free_source,
        model.risk_free_rate,
    )
    before = realized_horizon(_records(), ledger, "2024-01", "m")
    after = realized_horizon(moved, ledger, "2024-01", "m")
    assert before.returns is not None and after.returns is not None
    changed = np.flatnonzero((after.returns != before.returns).any(axis=1))
    assert [before.days[i] for i in changed] == [date(2024, 6, 3), date(2024, 6, 4)]
    assert (after.returns[:, 1:] == before.returns[:, 1:]).all()
    assert after.returns_sha256 != before.returns_sha256


# ------------------------------------------------------------------------------------ bank


def test_bank_is_the_production_replay_bank(model: OriginModel) -> None:
    drawn = bank(model, SEED)
    index = bootstrap_index(252, seed=SEED)
    assert index.shape == (2000, 252)
    assert (drawn.engine, drawn.seed, drawn.paths, drawn.model_key) == (
        "replay",
        SEED,
        2000,
        model.key,
    )
    counts = np.stack([np.bincount(row, minlength=252) for row in index]).astype(float)
    np.testing.assert_array_equal(drawn.replay.counts, counts)
    assert drawn.index_sha256 == hashlib.sha256(index.astype("<i4").tobytes()).hexdigest()
    assert drawn.replay.sample is model.sample
    np.testing.assert_array_equal(drawn.replay.mu_s, model.mu_s)
    np.testing.assert_array_equal(drawn.replay.cov, model.moments.cov)
    other = bank(model, 20261113)
    assert other.index_sha256 != drawn.index_sha256
    with pytest.raises(ValueError, match="engine"):
        bank(model, SEED, "garch")  # pyright: ignore[reportArgumentType]


# ------------------------------------------------------------------------ training figures


def test_count_matrix_compounding_matches_explicit_daily_multiplication(
    model: OriginModel,
) -> None:
    for seed in (SEED, 20261113):
        simulated = simulate(model, bank(model, seed), MIXES)
        assert simulated.years.shape == (2000, len(MIXES))
        assert simulated.status == (OK,) * len(MIXES)
        for j, mix in enumerate(MIXES):
            explicit = _explicit_years(model, seed, mix)
            np.testing.assert_allclose(simulated.years[:, j], explicit, rtol=0, atol=1e-10)


def test_figures_match_sorted_oracles(model: OriginModel) -> None:
    drawn = bank(model, SEED)
    simulated = simulate(model, drawn, MIXES)
    figures = evaluate(model, drawn, MIXES)
    assert (figures.paths, figures.seeds, figures.status) == (2000, (SEED,), simulated.status)
    np.testing.assert_array_equal(figures.weights, MIXES)
    for j, mix in enumerate(MIXES):
        years = simulated.years[:, j]
        explicit = _explicit_years(model, SEED, mix)
        for name, q in (("bad", 2.5), ("typical", 50.0), ("good", 97.5)):
            value = getattr(figures, name)[j]
            assert value == pytest.approx(_linear_percentile(years, q), abs=1e-15)
            assert value == pytest.approx(_linear_percentile(explicit, q), abs=1e-10)
        worst = sorted(years.tolist())[:50]  # ceil(0.025 * 2000)
        assert figures.es_25[j] == pytest.approx(sum(worst) / 50, abs=1e-15)
        assert figures.mean[j] == pytest.approx(years.sum() / 2000, abs=1e-15)
        assert figures.p_loss[j] == np.count_nonzero(years < 0.0) / 2000
        assert figures.p_below_20[j] == np.count_nonzero(years < -0.20) / 2000
    assert 0.0 < figures.p_loss.max() < 1.0
    assert figures.p_below_20.max() > 0.0


def test_figures_are_production_one_year_ranges(model: OriginModel) -> None:
    drawn = bank(model, SEED)
    figures = evaluate(model, drawn, MIXES)
    for j, mix in enumerate(MIXES):
        production = one_year_ranges(drawn.replay, mix)
        for name in ("bad", "typical", "good"):
            assert getattr(figures, name)[j].tobytes() == production[name][0].tobytes()


def test_same_weights_and_bank_give_identical_bits(model: OriginModel) -> None:
    drawn = bank(model, SEED)
    whole = evaluate(model, drawn, MIXES)
    pieces = [
        evaluate(model, drawn, MIXES[part]) for part in (slice(0, 1), slice(1, 5), slice(5, None))
    ]
    singles = [evaluate(model, drawn, mix) for mix in MIXES]  # one mix as a vector
    backwards = evaluate(model, drawn, MIXES[::-1])
    routed = summarize([simulate(model, drawn, MIXES)])
    ranges.path_counts.cache_clear()
    ranges.bootstrap_index.cache_clear()
    fresh = evaluate(model, bank(model, SEED), MIXES)

    for name in FIGURES:
        expected = getattr(whole, name).tobytes()
        assert np.concatenate([getattr(p, name) for p in pieces]).tobytes() == expected
        assert np.concatenate([getattr(s, name) for s in singles]).tobytes() == expected
        assert getattr(backwards, name)[::-1].tobytes() == expected
        assert getattr(routed, name).tobytes() == expected
        assert getattr(fresh, name).tobytes() == expected
    assert _bits(fresh) == _bits(whole)
    years = simulate(model, drawn, MIXES).years
    split = np.hstack(
        [simulate(model, drawn, MIXES[:4]).years, simulate(model, drawn, MIXES[4:]).years]
    )
    assert split.tobytes() == years.tobytes()


def test_weights_are_validated(model: OriginModel) -> None:
    drawn = bank(model, SEED)
    with pytest.raises(ValueError, match="weights"):
        evaluate(model, drawn, np.ones((2, 4)) / 4)
    with pytest.raises(ValueError, match="finite"):
        evaluate(model, drawn, [[np.nan, 0.5, 0.5]])
    with pytest.raises(ValueError, match="weights"):
        evaluate(model, drawn, np.empty((0, 3)))


# --------------------------------------------------------------------- nonpositive growth


def _ruin_model(model: OriginModel) -> OriginModel:
    """Four training days on which some mixes have a recentred growth at or below zero.

    `g_t = 1 + r_t'w - mean(r'w) + mu_s'w / 252` with `mu_s = (-126, 0, 0)`:
      (1, 0, 0)     g = (1, 1, 0, 0) exactly: first nonpositive day is the third
      (0, 1, 0)     g = (1, 1, 1, 1)
      (0, 0, 1)     g = (1.375, -0.125, 1.375, 1.375): the second day
      (.5, .5, 0)   g = (1, 1, .5, .5)
    """
    sample = np.array([[0.0, 0.0, 0.0], [0.0, 0.0, -1.5], [-1.0, 0.0, 0.0], [-1.0, 0.0, 0.0]])
    sample.setflags(write=False)
    days = model.days[:4]
    return replace(
        model,
        days=days,
        sample=sample,
        sample_sha256=sample_digest(list(model.funds), [d.isoformat() for d in days], sample),
        moments=estimate_moments(sample),
        mu_s=np.array([-126.0, 0.0, 0.0]),
    )


def test_nonpositive_daily_growth_is_named_and_never_reaches_production(
    model: OriginModel, monkeypatch: pytest.MonkeyPatch
) -> None:
    ruin = _ruin_model(model)
    drawn = bank(ruin, SEED)
    mixes = np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0], [0.5, 0.5, 0.0]])
    # production replay raises for the two ruined mixes ...
    for j in (0, 2):
        with pytest.raises(ValueError, match="loses everything"):
            ranges.simulated_years(drawn.replay, mixes[j])
    # ... and is never asked about them
    calls: list[np.ndarray] = []
    production = evaluation.simulated_years

    def spy(replay, weights):
        calls.append(np.array(weights, copy=True))
        return production(replay, weights)

    monkeypatch.setattr(evaluation, "simulated_years", spy)
    figures = evaluate(ruin, drawn, mixes)
    assert len(calls) == 2
    np.testing.assert_array_equal(calls[0], mixes[1:2])
    np.testing.assert_array_equal(calls[1], mixes[3:4])

    assert figures.status == (NONPOSITIVE_DAILY_GROWTH, OK, NONPOSITIVE_DAILY_GROWTH, OK)
    assert figures.ruin_day == (ruin.days[2], None, ruin.days[1], None)
    np.testing.assert_array_equal(figures.weights, mixes)
    for name in FIGURES:
        values = getattr(figures, name)
        assert np.isnan(values[[0, 2]]).all(), name
        assert np.isfinite(values[[1, 3]]).all(), name
    assert figures.bad[1] == 0.0 and figures.good[1] == 0.0  # g = 1 every day
    # (.5, .5, 0) compounds 1, 1, .5, .5 along each path
    simulated = simulate(ruin, drawn, mixes)
    assert np.isnan(simulated.years[:, [0, 2]]).all()
    index = bootstrap_index(4, seed=SEED)
    halves = (index >= 2).sum(axis=1)
    np.testing.assert_allclose(simulated.years[:, 3], 0.5**halves - 1.0, rtol=0, atol=1e-15)


# ------------------------------------------------------------------------- pooled banks


def test_summarize_pools_independent_banks(model: OriginModel) -> None:
    first = simulate(model, bank(model, 20261113), MIXES)
    second = simulate(model, bank(model, 20261114), MIXES)
    pooled = summarize([first, second])
    assert (pooled.paths, pooled.seeds) == (4000, (20261113, 20261114))
    for j in range(len(MIXES)):
        years = np.concatenate([first.years[:, j], second.years[:, j]])
        for name, q in (("bad", 2.5), ("typical", 50.0), ("good", 97.5)):
            assert getattr(pooled, name)[j] == pytest.approx(
                _linear_percentile(years, q), abs=1e-15
            )
        worst = sorted(years.tolist())[:100]  # ceil(0.025 * 4000)
        assert pooled.es_25[j] == pytest.approx(sum(worst) / 100, abs=1e-15)
        assert pooled.mean[j] == pytest.approx(years.sum() / 4000, abs=1e-15)
        assert pooled.p_loss[j] == np.count_nonzero(years < 0.0) / 4000

    with pytest.raises(ValueError, match="twice"):
        summarize([first, first])
    with pytest.raises(ValueError, match="same"):
        summarize([first, simulate(model, bank(model, 20261115), MIXES[:2])])
    with pytest.raises(ValueError, match="at least one"):
        summarize([])
    ruin = _ruin_model(model)
    with pytest.raises(ValueError, match="another"):
        simulate(ruin, bank(model, SEED), MIXES)
    with pytest.raises(ValueError, match="same"):
        summarize([first, simulate(ruin, bank(ruin, 20261114), MIXES)])


# ------------------------------------------------------------------------------- realized


def test_realized_horizon_is_the_ledgers_252_rows(ledger: Ledger) -> None:
    horizon = realized_horizon(_records(), ledger, "2024-01", "m")
    days = _tr()["A"].index
    start = days.get_loc(ORIGIN)
    assert isinstance(start, int)
    dates = pd.DatetimeIndex(days[start + 1 : start + 253])
    assert horizon.status == COMPLETE and horizon.issues == ()
    assert horizon.days == tuple(day.date() for day in dates)
    assert (horizon.days[0], horizon.days[-1]) == (date(2024, 2, 1), date(2025, 2, 3))
    oracle = _rows(dates, ("A", "B", "C"))
    assert horizon.returns is not None
    np.testing.assert_array_equal(horizon.returns, oracle)
    assert not horizon.returns.flags.writeable
    assert horizon.returns_sha256 == sample_digest(
        ["A", "B", "C"], [day.date().isoformat() for day in dates], oracle
    )

    outcome = realized(horizon, MIXES)
    assert outcome.status == COMPLETE and outcome.metrics is not None
    for j, mix in enumerate(MIXES):
        wealth = 1.0
        for row in oracle.tolist():
            wealth *= 1.0 + sum(w * r for w, r in zip(mix.tolist(), row, strict=True))
        assert outcome.metrics.annual_return[j] == pytest.approx(wealth - 1.0, abs=1e-12)


def test_incomplete_horizons_are_named_statuses(ledger: Ledger) -> None:
    missing = realized_horizon(_records(), ledger, "2024-01", "n")
    assert missing.status == HORIZON_MISSING
    assert [(i.code, i.fund, i.day) for i in missing.issues] == [
        (HORIZON_VALUE_MISSING, "D", date(2024, 5, 15))
    ]
    assert (missing.days, missing.returns, missing.returns_sha256) == ((), None, None)
    outcome = realized(missing, [[0.5, 0.5]])
    assert (outcome.status, outcome.metrics) == (HORIZON_MISSING, None)
    np.testing.assert_array_equal(outcome.weights, [[0.5, 0.5]])

    immature = realized_horizon(_records(), ledger, "2024-03", "m")
    assert (immature.status, immature.issues, immature.returns) == (IMMATURE, (), None)
    assert realized(immature, MIXES).metrics is None

    # records that are not the ledger's: B lost a day inside the 2024-01 horizon
    with pytest.raises(ValueError, match="ledger"):
        realized_horizon(_records(drop=("B", "2024-06-03")), ledger, "2024-01", "m")


def _hand_horizon() -> Horizon:
    returns = np.zeros((252, 3))
    returns[:3, 0] = [0.10, -0.40, 0.20]
    returns[:2, 1] = [0.10, -0.10]
    returns[0, 2], returns[5, 2] = -0.05, 0.10
    days = tuple(day.date() for day in pd.DatetimeIndex(_tr()["A"].index[1:253]))
    return Horizon(
        "m", ("A", "B", "C"), "2024-01", date(2024, 1, 31), COMPLETE, (), days, returns, None
    )


def _vol(total: float, squares: float) -> float:
    """sqrt(252) x the ddof-1 deviation of 252 daily returns with this sum and sum of squares."""
    return math.sqrt(252.0 * (squares - total**2 / 252.0) / 251.0)


def test_realized_metrics_by_hand() -> None:
    mixes = [[1.0, 0.0, 0.0], [0.5, 0.5, 0.0], [0.0, 0.0, 1.0], [0.0, 1.0, 0.0]]
    outcome = realized(_hand_horizon(), mixes)
    assert outcome.status == COMPLETE and outcome.metrics is not None
    metrics = outcome.metrics
    # (1,0,0): 1.1, .66, .792; (.5,.5,0): 1.1, .825, .9075; (0,0,1): .95 then 1.045 on day 6,
    # a drawdown from the initial wealth; (0,1,0): 1.1, .99
    expected = {
        "annual_return": [1.1 * 0.6 * 1.2 - 1.0, 1.1 * 0.75 * 1.1 - 1.0, 0.95 * 1.1 - 1.0, -0.01],
        "worst_day": [-0.40, -0.25, -0.05, -0.10],
        "max_drawdown": [0.40, 0.25, 0.05, 0.10],
        "volatility": [_vol(-0.1, 0.21), _vol(-0.05, 0.0825), _vol(0.05, 0.0125), _vol(0.0, 0.02)],
    }
    for name, values in expected.items():
        np.testing.assert_allclose(getattr(metrics, name), values, rtol=0, atol=1e-12)
    assert metrics.annual_return[0] == pytest.approx(-0.208, abs=1e-12)
    assert metrics.loss.tolist() == [True, True, False, True]
    assert metrics.below_20.tolist() == [True, False, False, False]
    split = [realized(_hand_horizon(), [mix]).metrics for mix in mixes]
    for name in ("annual_return", "worst_day", "max_drawdown", "volatility"):
        joined = np.concatenate([getattr(part, name) for part in split if part is not None])
        assert joined.tobytes() == getattr(metrics, name).tobytes()


def test_constant_weight_year_of_the_plan_snippet() -> None:
    daily = np.array([[0.10, 0.00], [-0.10, 0.10]])
    metrics = path_metrics(daily, [0.5, 0.5])
    assert metrics.annual_return[0] == pytest.approx(0.05, abs=1e-15)  # 1.05 * 1.00 - 1
    with pytest.raises(ValueError, match="loses everything"):
        path_metrics(np.array([[-1.0, 0.0], [0.0, 0.0]]), [1.0, 0.0])
    with pytest.raises(ValueError, match="rows"):
        path_metrics(np.array([[0.1, 0.0]]), [1.0, 0.0])
    with pytest.raises(ValueError, match="finite"):
        path_metrics(np.array([[0.1, np.nan], [0.0, 0.0]]), [1.0, 0.0])


# ---------------------------------------------------------------------------- calibration


def test_pinball_loss_of_the_plan_snippet() -> None:
    # errors y - f = -0.10 and 0.20 at q = 0.025: max(q e, (q - 1) e) = 0.0975 and 0.005
    loss = pinball(0.025, [0.0, 0.3], [0.1, 0.1])
    np.testing.assert_allclose(loss, [0.0975, 0.005], rtol=0, atol=1e-15)
    np.testing.assert_allclose(pinball(0.5, [0.0, 0.3], [0.1, 0.1]), [0.05, 0.1], atol=1e-15)
    np.testing.assert_allclose(pinball(0.975, [0.0, 0.3], [0.1, 0.1]), [0.0025, 0.195], atol=1e-15)
    assert pinball(0.025, 0.1, 0.1).tolist() == 0.0  # y = f: no loss
    for q in (0.0, 1.0):
        with pytest.raises(ValueError, match="level"):
            pinball(q, 0.0, 0.0)


def test_coverage_indicators_breaches_and_pit() -> None:
    # 1[y <= f]: a tie counts as at or below
    assert at_or_below([-0.2, -0.1, 0.0, 0.1], -0.1).tolist() == [True, True, False, False]
    counts = breaches([-0.3, -0.1, 0.0, 0.2, 0.25, 0.3], -0.1, 0.25)
    assert (counts.below, counts.inside, counts.above) == (2, 3, 1)
    with pytest.raises(ValueError, match="Bad"):
        breaches([0.0], 0.1, -0.1)
    assert pit(0.1, [-0.1, 0.0, 0.1, 0.2]) == 0.75
    assert pit(-0.5, [-0.1, 0.0]) == 0.0
    with pytest.raises(ValueError, match="vector"):
        pit(0.0, [[0.1]])
    with pytest.raises(ValueError, match="finite"):
        at_or_below([np.nan], 0.0)
