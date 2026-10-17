"""The volatility model's shape (simulation engines spec 4.3): panel, fit, guard and pool."""

from __future__ import annotations

import hashlib
import io
import json
import pickle

import numpy as np
import pandas as pd
import pytest

from portfoliosight.engine import shape
from portfoliosight.engine.ranges import HORIZON_DAYS, PATHS, SEED, sample_digest
from portfoliosight.engine.shape import (
    MIN_POOL_ROWS,
    OUTLIER_Z,
    SHAPE_ROWS,
    UNAVAILABLE_REASON,
    GarchArtifact,
    ShapeError,
    artifact_from_json,
    artifact_to_json,
    fit_shape,
    garch_method,
    pool_bytes,
    pool_from_bytes,
    qse_commit,
    shape_panel,
    simulate_panel,
)
from portfoliosight.engine.windows import select_window
from qse.distributions.garch_recursion import (
    garch11_long_run_variance,
    simulate_garch11,
    standardized_t_shocks,
)
from qse.distributions.joint import draw_row_indices
from tests.engine.helpers import FIXTURE_ASOF, ROOT

MU = np.array([3e-4, 5e-4])
OMEGA = np.array([2e-6, 4e-6])
ALPHA = np.array([0.08, 0.10])
BETA = np.array([0.90, 0.85])
FALLBACKS = ("near_constant", "near_constant", "insufficient_history", "non_stationary")
MIXED_STATUS = ("garch", "garch", *FALLBACKS)


def _days(rows: int, end: str = "2026-06-30") -> pd.DatetimeIndex:
    return pd.bdate_range(end=end, periods=rows, name="date")


def _garch_pair(rows: int, seed: int) -> np.ndarray:
    """Two GARCH(1,1)-t funds in decimal returns, as QSE's own tests make them: rows x 2."""
    shocks = standardized_t_shocks(np.random.default_rng(seed), 6.0, (1, rows, 2))
    long_run = OMEGA / (1.0 - ALPHA - BETA)
    return simulate_garch11(
        shocks, mu=MU, omega=OMEGA, alpha=ALPHA, beta=BETA, sigma2_init=long_run
    )[0]


def _igarch(rows: int) -> np.ndarray:
    """A series whose volatility never reverts: its fit has alpha + beta at 1."""
    shocks = standardized_t_shocks(np.random.default_rng(5), 8.0, (1, rows))
    return simulate_garch11(shocks, mu=0.0, omega=1e-7, alpha=0.12, beta=0.88, sigma2_init=1e-4)[0]


@pytest.fixture(scope="module")
def mixed() -> shape.ShapePanel:
    """Two GARCH funds and one of each fallback: TSP-G-like, constant, young, non-stationary."""
    rows = 1500
    pair = _garch_pair(rows, 21)
    noise = np.random.default_rng(22).normal(0.0, 2e-5, rows)
    young = np.full(rows, np.nan)
    young[-200:] = np.random.default_rng(23).normal(4e-4, 0.012, 200)
    frame = pd.DataFrame(
        {
            "CALM": pair[:, 0],
            "BUSY": pair[:, 1],
            "TSPG": 1.2e-4 + noise,
            "FLAT": np.full(rows, 1e-4),
            "YOUNG": young,
            "WILD": _igarch(rows),
        },
        index=_days(rows),
    )
    return shape_panel(frame, list(frame.columns), "2026-06-30")


@pytest.fixture(scope="module")
def artifact(mixed) -> GarchArtifact:
    return fit_shape(mixed)


def _trio(rows: int = 600, seed: int = 31) -> pd.DataFrame:
    """Three near-identical funds of 1% daily volatility: they move together every day."""
    rng = np.random.default_rng(seed)
    base = rng.normal(3e-4, 0.01, rows)
    noise = rng.normal(0.0, 0.001, (rows, 2))
    return pd.DataFrame(
        {"A": base, "B": base + noise[:, 0], "C": base + noise[:, 1]}, index=_days(rows)
    )


def _iso(stamp) -> str:
    return pd.Timestamp(stamp).date().isoformat()


def _day(frame: pd.DataFrame, row: int) -> str:
    return _iso(frame.index[row])


def test_constants_are_the_spec_s():
    assert SHAPE_ROWS == 2520 and MIN_POOL_ROWS == 126 and OUTLIER_Z == 6.0
    assert UNAVAILABLE_REASON == "not enough shared history for the volatility model"


def test_panel_is_the_last_rows_of_the_included_funds_own_calendar():
    rng = np.random.default_rng(41)
    index = _days(400)
    frame = pd.DataFrame(rng.normal(0, 0.01, (400, 3)), index=index, columns=["A", "B", "OTHER"])
    resting = np.broadcast_to(np.arange(400)[:, None] % 7 == 3, (400, 2))
    frame.iloc[:, :2] = frame.iloc[:, :2].mask(resting)  # A and B rest on these days, OTHER not
    frame.iloc[:50, 1] = np.nan  # B starts later
    frame.loc[index[-1], ["A", "B"]] = 0.02  # after asof: never used
    asof = _iso(index[-2])
    panel = shape_panel(frame, ["B", "A"], asof)
    traded = frame.loc[frame.index <= asof, ["B", "A"]].dropna(how="all")
    assert panel.rows == len(traded) == 400 - 1 - len(range(3, 399, 7))
    assert list(panel.frame.columns) == ["B", "A"] and panel.frame.index.equals(traded.index)
    assert panel.start == traded.index[0].date().isoformat() and panel.end == asof
    values = panel.frame.to_numpy()
    assert np.array_equal(np.isnan(values), traded.isna().to_numpy())  # NaN where none
    assert np.array_equal(values[~np.isnan(values)], traded.to_numpy()[~np.isnan(values)])
    assert np.isnan(values[:40, 0]).all() and not np.isnan(values[:, 1]).any()
    days = [stamp.date().isoformat() for stamp in traded.index]
    assert panel.sample_sha256 == sample_digest(["B", "A"], days, traded.to_numpy())


def test_panel_of_the_fixture_spans_ten_years_and_one_digest_serves_like_fund_sets(fixture_frame):
    ids = list(fixture_frame.columns)
    ten, five = (select_window(fixture_frame, lb, FIXTURE_ASOF) for lb in ("10y", "5y"))
    assert ten.funds == five.funds == ids
    panel = shape_panel(fixture_frame, ten.funds, FIXTURE_ASOF)
    assert panel.rows == SHAPE_ROWS and panel.frame.shape == (SHAPE_ROWS, 23)
    assert (
        panel.end == FIXTURE_ASOF
        and panel.start == fixture_frame.index[-SHAPE_ROWS].date().isoformat()
    )
    assert panel.frame.equals(fixture_frame.iloc[-SHAPE_ROWS:])
    assert shape_panel(fixture_frame, five.funds, FIXTURE_ASOF).sample_sha256 == panel.sample_sha256
    # a fund young enough for the one-year view only: the 1y panel holds it, the 5y one does not
    young = fixture_frame["VTI"].where(np.arange(len(fixture_frame)) >= len(fixture_frame) - 240)
    menu = fixture_frame.assign(NEWB=young)
    one, five = (select_window(menu, lb, FIXTURE_ASOF) for lb in ("1y", "5y"))
    assert one.funds == [*ids, "NEWB"] and five.funds == ids
    with_young = shape_panel(menu, one.funds, FIXTURE_ASOF)
    without = shape_panel(menu, five.funds, FIXTURE_ASOF)
    assert without.sample_sha256 == panel.sample_sha256 != with_young.sample_sha256
    assert np.isnan(with_young.frame["NEWB"].to_numpy()[:-240]).all()


def test_digest_encodes_every_missing_return_as_the_canonical_quiet_nan():
    rng = np.random.default_rng(42)
    values = rng.normal(0, 0.01, (30, 2))
    values[:5, 1] = np.nan
    frame = pd.DataFrame(values, index=_days(30), columns=["A", "B"])
    plain = shape_panel(frame, ["A", "B"], frame.index[-1]).sample_sha256
    negative = np.array([0xFFF8000000000001], dtype=np.uint64).view(np.float64)[0]
    assert np.isnan(negative)
    other = values.copy()
    other[:5, 1] = negative  # a NaN with another sign and payload
    odd = pd.DataFrame(other, index=frame.index, columns=["A", "B"])
    assert odd.to_numpy().tobytes() != frame.to_numpy().tobytes()
    assert shape_panel(odd, ["A", "B"], frame.index[-1]).sample_sha256 == plain
    quiet = np.array([0x7FF8000000000000], dtype=np.uint64).view(np.float64)
    values = frame.to_numpy().copy()
    values[np.isnan(values)] = quiet[0]  # the bytes the digest must have hashed
    days = [stamp.date().isoformat() for stamp in frame.index]
    digest = hashlib.sha256()
    digest.update(b"A\x1fB\x1e" + "\x1f".join(days).encode() + b"\x1e")
    digest.update(np.ascontiguousarray(values, dtype="<f8").tobytes())
    assert plain == digest.hexdigest()
    assert values.astype("<f8").tobytes().count(quiet.astype("<f8").tobytes()) == 5


def test_panel_inputs_are_checked():
    frame = pd.DataFrame({"A": [0.01, 0.02, 0.0], "B": [0.0, 0.01, 0.02]}, index=_days(3))
    with pytest.raises(ValueError, match="DatetimeIndex"):
        shape_panel(frame.reset_index(drop=True), ["A", "B"], "2026-06-30")
    with pytest.raises(ValueError, match="ZZZ"):
        shape_panel(frame, ["A", "ZZZ"], "2026-06-30")
    with pytest.raises(ValueError, match="at least one fund"):
        shape_panel(frame, [], "2026-06-30")
    with pytest.raises(ValueError, match="at least two rows"):
        shape_panel(frame, ["A", "B"], frame.index[0])
    with pytest.raises(ValueError, match="asof must be a date"):
        shape_panel(frame, ["A", "B"], None)


def test_fit_names_every_fund_s_status_and_keeps_the_fallbacks_constant(mixed, artifact):
    a = artifact
    assert a.funds == tuple(mixed.frame.columns) and a.status == MIXED_STATUS
    assert (a.rows, a.start, a.end, a.sample_sha256) == (
        mixed.rows,
        mixed.start,
        mixed.end,
        mixed.sample_sha256,
    )
    assert a.n_obs == (1500, 1500, 1500, 1500, 200, 1500)
    garch = np.array([s == "garch" for s in a.status])
    assert np.all(a.nu[garch] > 2.0) and np.isnan(a.nu[~garch]).all()
    assert np.all(a.alpha[~garch] == 0.0) and np.all(a.beta[~garch] == 0.0)
    assert np.all(a.alpha[garch] + a.beta[garch] < 1.0 - 1e-4)
    values = mixed.frame.to_numpy()
    for n in np.flatnonzero(~garch):
        own = values[~np.isnan(values[:, n]), n]
        assert a.mu[n] == pytest.approx(own.mean(), rel=1e-12)
        if a.funds[n] == "FLAT":
            assert a.omega[n] == 0.0  # sd at the floor: zero residuals
        else:
            assert a.omega[n] == pytest.approx(own.var(ddof=1), rel=1e-12)
    expected = np.sqrt(252.0 * a.omega / (1.0 - a.alpha - a.beta))
    assert np.allclose(a.long_run_sigma_annual, expected, rtol=1e-14, atol=0.0)
    assert "near_constant_vol" in a.messages[2] and "min_history" in a.messages[4]
    assert "unconditional variance undefined" in a.messages[5]
    assert a.qse == qse_commit() and a.arch == "8.0.0" and a.unavailable_reason is None
    for field in ("mu", "omega", "alpha", "beta", "nu", "long_run_sigma_annual"):
        with pytest.raises(ValueError, match="read-only"):
            getattr(a, field)[0] = 1.0


def test_pool_is_the_common_rows_restandardised(artifact):
    pool = artifact.pool
    assert pool is not None and pool.shape == (200, 6) and artifact.pool_rows == 200
    assert pool.dtype == np.float64 and not pool.flags.writeable
    live = [n for n, fund in enumerate(artifact.funds) if fund != "FLAT"]
    assert np.abs(pool[:, live].mean(axis=0)).max() <= 1e-12
    assert np.abs(pool[:, live].var(axis=0, ddof=0) - 1.0).max() <= 1e-12
    assert not pool[:, artifact.funds.index("FLAT")].any()  # a zero-residual fund stays at zero
    data = np.ascontiguousarray(pool, dtype="<f8").tobytes()
    assert artifact.pool_sha256 == hashlib.sha256(data).hexdigest()


def test_every_fund_runs_the_same_recursion_and_a_fallback_only_scales_its_shock(artifact):
    """M5: a fund that could not be fitted keeps a constant volatility, never filled or clipped."""
    paths, horizon, seed = 40, 30, 7
    sim = simulate_panel(artifact, paths=paths, horizon=horizon, seed=seed)
    assert sim.shape == (paths, horizon, 6) and sim.dtype == np.float64
    assert np.isfinite(sim).all()
    pool = artifact.pool
    assert pool is not None
    shocks = pool[draw_row_indices(artifact.pool_rows, paths, horizon, seed=seed)]
    for n, status in enumerate(artifact.status):
        if status != "garch":
            scaled = artifact.mu[n] + np.sqrt(artifact.omega[n]) * shocks[..., n]
            assert np.array_equal(sim[..., n], scaled), artifact.funds[n]
            continue
        start = garch11_long_run_variance(artifact.omega[n], artifact.alpha[n], artifact.beta[n])
        variance = np.full(paths, start)
        for t in range(horizon):  # the recursion, step by step, from the long-run variance
            eps = np.sqrt(variance) * shocks[:, t, n]
            assert np.array_equal(sim[:, t, n], artifact.mu[n] + eps)
            variance = (
                artifact.omega[n] + artifact.alpha[n] * (eps * eps) + artifact.beta[n] * variance
            )
    flat = artifact.funds.index("FLAT")
    assert (sim[..., flat] == artifact.mu[flat]).all()
    full = simulate_panel(artifact)
    assert full.shape == (PATHS, HORIZON_DAYS, 6) and (PATHS, HORIZON_DAYS, SEED) == (
        2000,
        252,
        20261013,
    )
    again = simulate_panel(artifact)
    assert full.tobytes() == again.tobytes()  # one draw, fixed by its seed
    assert not np.array_equal(simulate_panel(artifact, seed=SEED + 1), full)


def test_artifact_round_trips_through_json_and_npy_to_the_same_bytes(artifact):
    text = json.dumps(artifact_to_json(artifact), allow_nan=False, sort_keys=True)
    doc = json.loads(text)
    data = pool_bytes(artifact)
    assert data.startswith(b"\x93NUMPY")
    back = artifact_from_json(doc, pool_from_bytes(data))
    assert back.funds == artifact.funds and back.status == artifact.status
    assert back.messages == artifact.messages and back.n_obs == artifact.n_obs
    assert back.outliers == artifact.outliers and back.qse == artifact.qse
    for field in ("mu", "omega", "alpha", "beta", "nu", "long_run_sigma_annual"):
        assert getattr(back, field).tobytes() == getattr(artifact, field).tobytes(), field
    sim = simulate_panel(artifact)
    assert simulate_panel(back).tobytes() == sim.tobytes()
    assert doc["nu"][2] is None and doc["pool_rows"] == 200 and doc["name"] == "garch_t_fhs"
    # what does not belong together is refused, never repaired
    pool = pool_from_bytes(data)
    tampered = np.array(pool)
    tampered[3, 1] = np.nextafter(tampered[3, 1], 9.0)
    with pytest.raises(ValueError, match="pool does not match"):
        artifact_from_json(doc, tampered)
    with pytest.raises(ValueError, match="pool does not match"):
        artifact_from_json(doc, pool[:-1])
    with pytest.raises(ValueError, match="pool does not match"):
        artifact_from_json(doc, None)
    with pytest.raises(ValueError, match="one entry per fund"):
        artifact_from_json({**doc, "mu": doc["mu"][:-1]}, pool)
    with pytest.raises(ValueError, match="not a volatility model"):
        artifact_from_json({**doc, "name": "copula"}, pool)
    objects = io.BytesIO()
    np.save(objects, np.array([{"a": 1}], dtype=object), allow_pickle=True)
    with pytest.raises(ValueError):
        pool_from_bytes(objects.getvalue())
    one_d = io.BytesIO()
    np.save(one_d, np.zeros(4))
    with pytest.raises(ValueError, match="2-D float64"):
        pool_from_bytes(one_d.getvalue())
    assert pickle.loads(pickle.dumps(back)).funds == back.funds


def test_a_short_pool_marks_the_engine_unavailable_and_records_its_rows():
    pair = _garch_pair(600, 24)
    young = np.full(600, np.nan)
    young[-100:] = np.random.default_rng(25).normal(0.0, 0.01, 100)
    frame = pd.DataFrame({"A": pair[:, 0], "B": pair[:, 1], "Y": young}, index=_days(600))
    short = fit_shape(shape_panel(frame, ["A", "B", "Y"], frame.index[-1]))
    assert short.pool is None and short.pool_rows == 100 < MIN_POOL_ROWS
    assert short.unavailable_reason == UNAVAILABLE_REASON and short.pool_sha256 is None
    assert short.status[2] == "insufficient_history"
    with pytest.raises(ValueError, match=UNAVAILABLE_REASON):
        simulate_panel(short)
    with pytest.raises(ValueError, match="no pool"):
        pool_bytes(short)
    doc = json.loads(json.dumps(artifact_to_json(short), allow_nan=False))
    back = artifact_from_json(doc, None)
    assert back.pool is None and back.unavailable_reason == UNAVAILABLE_REASON
    with pytest.raises(ValueError, match="pool does not match"):
        artifact_from_json(doc, np.zeros((100, 3)))


def test_residuals_constant_on_the_common_rows_fail_the_fit():
    """A fund that varies on its early rows but not on the rows it shares: nothing to resample."""
    rng = np.random.default_rng(26)
    flat_late = np.concatenate([rng.normal(0.0, 0.01, 100), np.full(140, 1e-3)])
    young = np.full(240, np.nan)
    young[-140:] = rng.normal(0.0, 0.01, 140)
    frame = pd.DataFrame({"OLD": flat_late, "NEW": young}, index=_days(240))
    with pytest.raises(ShapeError, match="OLD") as caught:
        fit_shape(shape_panel(frame, ["OLD", "NEW"], frame.index[-1]))
    assert "constant over the common rows" in str(caught.value)
    assert caught.value.fund is None and caught.value.date is None
    assert isinstance(caught.value, ValueError)


def test_a_drop_on_a_fund_s_own_splice_date_fails_and_names_fund_and_date():
    frame = _trio()
    frame.iloc[400, 0] = -0.30  # an ex-date drop the record did not adjust for
    day = _day(frame, 400)
    with pytest.raises(ShapeError) as caught:
        fit_shape(shape_panel(frame, ["A", "B", "C"], frame.index[-1]), {"A": day})
    assert caught.value.fund == "A" and caught.value.date == day
    assert "A" in str(caught.value) and day in str(caught.value)


def test_the_same_drop_on_another_day_is_an_outlier_and_fails_nothing():
    frame = _trio()
    frame.iloc[400, 0] = -0.30
    frame.iloc[:50, 1] = np.nan  # B starts later: its splice date below has no residual
    panel = shape_panel(frame, ["A", "B", "C"], frame.index[-1])
    splices = {
        "A": _day(frame, 300),
        "B": _day(frame, 10),
        "C": "1999-01-04",
        "ZZZ": _day(frame, 5),
    }
    fitted = fit_shape(panel, splices)
    assert [(o["id"], o["date"]) for o in fitted.outliers] == [("A", _day(frame, 400))]
    assert fitted.outliers[0]["z"] < -OUTLIER_Z and isinstance(fitted.outliers[0]["z"], float)
    assert fitted.pool is not None  # the day stays in the pool: nothing is clipped
    with pytest.raises(ValueError, match="2026/01/02"):
        fit_shape(panel, {"A": "2026/01/02"})


def test_a_drop_of_the_whole_menu_on_the_splice_date_is_an_outlier_not_a_failure():
    """A crash: every fund falls together. Under a year of history each fund is standardized the
    same way (constant volatility), so the three residuals that day agree."""
    frame = _trio(rows=240)
    frame.iloc[200, :] = -0.30
    fitted = fit_shape(
        shape_panel(frame, ["A", "B", "C"], frame.index[-1]), {"A": _day(frame, 200)}
    )
    assert set(fitted.status) == {"insufficient_history"}
    assert [(o["id"], o["date"]) for o in fitted.outliers] == [
        (fund, _day(frame, 200)) for fund in ("A", "B", "C")
    ]


def test_a_splice_day_no_other_fund_traded_cannot_be_called_a_crash():
    frame = _trio()
    frame.iloc[400, 0] = -0.30
    frame.iloc[400, 1:] = np.nan  # the rest of the menu has no return that day
    with pytest.raises(ShapeError) as caught:
        fit_shape(shape_panel(frame, ["A", "B", "C"], frame.index[-1]), {"A": _day(frame, 400)})
    assert caught.value.fund == "A" and "no other fund" in str(caught.value)


def test_method_block_names_the_pinned_code(artifact):
    lock = json.loads((ROOT / "qse" / "qse.lock.json").read_text(encoding="utf-8"))
    assert qse_commit() == lock["commit"] == "ca8c0445a56712c92dc028e68845b94963fdd590"
    assert garch_method(artifact) == {
        "name": "garch_t_fhs",
        "paths": 2000,
        "horizon_days": 252,
        "seed": 20261013,
        "start": "long_run",
        "shape_rows": 2520,
        "qse": lock["commit"],
        "arch": "8.0.0",
    }
