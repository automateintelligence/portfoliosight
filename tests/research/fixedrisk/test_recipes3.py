"""The simple and diversification-driven recipes check
(docs/plans/2026-11-11-diversification-vs-simple-mixes.md, built by
docs/plans/2026-11-15-diversification-vs-simple-mixes-build-plan.md) on made-up menus whose
answers are known by hand or by the optimizer's own frontier: the most-diversified mix against
the paper's two examples, the exact-line frontier mix at its three branches, and one start
month's mixes with their statuses. No data file, fixed seeds."""

from __future__ import annotations

import dataclasses
import math
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

from portfoliosight.engine import optimize, torsion
from portfoliosight.research.fixedrisk import analysis3 as A
from portfoliosight.research.fixedrisk import anchors
from portfoliosight.research.fixedrisk import contracts as C
from portfoliosight.research.fixedrisk import recipes3 as RC
from portfoliosight.research.fixedrisk import region3 as G
from portfoliosight.research.fixedrisk.objectives3 import FIELDS
from portfoliosight.research.fixedrisk.pool import PoolBuffer, write_pool
from tests.research.fixedrisk.recipe_data import (
    M12,
    M12_OPEN,
    MENU12,
    THREE_E,
    THREE_U,
    programs,
    recorded,
)


def _cov(vols, corr) -> np.ndarray:
    v = np.asarray(vols, dtype=float)
    return np.outer(v, v) * np.asarray(corr, dtype=float)


# ------------------------------------------------------------------ the most-diversified mix


@pytest.mark.parametrize("rho", [-0.5, 0.0, 0.5, 0.9])
def test_most_diversified_reproduces_the_papers_first_example(rho):
    sigma = np.array([0.15, 0.30])
    cov = _cov(sigma, [[1.0, rho], [rho, 1.0]])
    w = RC.most_diversified(sigma, cov, 1.0)
    assert np.allclose(w, [2 / 3, 1 / 3], atol=1e-3)


def test_most_diversified_reproduces_the_papers_second_example():
    sigma = np.full(3, 0.20)
    corr = [[1.0, 0.9, 0.1], [0.9, 1.0, 0.1], [0.1, 0.1, 1.0]]
    w = RC.most_diversified(sigma, _cov(sigma, corr), 1.0)
    assert np.allclose(w, [0.257, 0.257, 0.486], atol=1e-3)


@pytest.mark.parametrize("cap", [0.10, 0.40])
def test_most_diversified_keeps_the_limits_and_beats_feasible_mixes(cap):
    sigma, cov = MENU12.sigma, MENU12.cov
    n = len(sigma)
    hi = np.full(n, cap)
    w = RC.most_diversified(sigma, cov, hi)
    assert abs(w.sum() - 1) <= 1e-8
    assert (w >= -1e-8).all()
    assert (w <= hi + 1e-8).all()
    rng = np.random.default_rng(0)
    best = anchors.dr2(w, sigma, cov)
    for _ in range(200):
        x = anchors.project_box_simplex(rng.normal(0.0, 0.3, n), np.zeros(n), hi)
        assert best >= anchors.dr2(x, sigma, cov) - 1e-6


def test_most_diversified_without_a_feasible_mix_is_a_solve_error():
    sigma = np.array([0.10, 0.12, 0.15, 0.20, 0.25])
    cov = _cov(sigma, np.eye(5))
    with pytest.raises(optimize.SolveError):
        RC.most_diversified(sigma, cov, 0.10)


# ------------------------------------------------ the exact-line frontier mix, risk position


@pytest.fixture(scope="module")
def frontier12():
    """MENU12's programs, its 8-node app frontier and the two ends the recorded columns hold."""
    menu = programs(M12)
    front = optimize.frontier(menu, 8)
    return menu, front, float(front.x[0]), float(front.x[-1])


def test_frontier_exact_inside_matches_the_app_frontier(frontier12):
    programs, front, smin, stop = frontier12
    for j in range(1, 7):
        w = RC.frontier_exact(programs, front.w[0], front.w[-1], float(front.x[j]), smin, stop)
        assert w is not None
        assert abs(programs.sigma(w) - front.x[j]) <= 1e-6
        assert abs(programs.mu @ w - front.y[j]) <= 1e-6


def test_frontier_exact_at_the_minimum_risk_is_the_frontiers_first_node(frontier12):
    programs, front, smin, stop = frontier12
    for s in (smin, smin + 5e-7, smin + 1e-6):
        w = RC.frontier_exact(programs, front.w[0], front.w[-1], s, smin, stop)
        assert w is not None
        assert np.array_equal(w, front.w[0])
    assert np.array_equal(programs.min_variance(), front.w[0])


def test_frontier_exact_at_the_top_is_excluded(frontier12):
    programs, front, smin, stop = frontier12
    for s in (stop - 1e-6, stop - 5e-7, stop, stop + 0.01):
        assert RC.frontier_exact(programs, front.w[0], front.w[-1], s, smin, stop) is None
        assert RC.at_or_above_top(s, stop)
    s = stop - 2e-6
    assert not RC.at_or_above_top(s, stop)
    w = RC.frontier_exact(programs, front.w[0], front.w[-1], s, smin, stop)
    assert w is not None
    assert abs(programs.sigma(w) - s) <= 1e-6


def test_frontier_exact_lands_on_the_line_when_expected_returns_tie():
    mu = np.full(3, 0.05)
    programs = optimize.MenuPrograms(mu, np.diag([0.01, 0.04, 0.09]), np.zeros(3), np.ones(3))
    front = optimize.frontier(programs, 8)
    smin, stop = float(front.x[0]), float(front.x[-1])
    s = (smin + stop) / 2
    w = RC.frontier_exact(programs, front.w[0], front.w[-1], s, smin, stop)
    assert w is not None
    assert abs(programs.sigma(w) - s) <= 1e-6
    assert abs(programs.mu @ w - 0.05) <= 1e-9


def test_risk_position():
    assert RC.risk_position(0.07, 0.05, 0.09) == pytest.approx(0.5)
    assert RC.risk_position(0.10, 0.05, 0.09) > 1


# ------------------------------------------------------------------- one start month's mixes

MONTH = "2010-01"
COLUMNS = {
    "month", "rf", "mix", "r", "comparator", "status", "reason", "weights", "mu", "sigma", "a",
    "enb", "dr2", "risk_gap", "mu_gap", "l1", "breaks_limit", "rebuilt_mu_gap",
    "rebuilt_sigma_gap", "rebuilt_l1", "ends_gap",
}  # fmt: skip
Row = dict[str, Any]


@pytest.fixture(scope="module")
def rec12() -> RC.Recorded:
    return recorded(M12)


@pytest.fixture(scope="module")
def mixes12(rec12) -> pd.DataFrame:
    return RC.month_mixes(MONTH, M12.mu_s, M12.cov, M12.lower, M12.upper, rec12)


def _mixes(m, rec: RC.Recorded) -> list[Row]:
    return _records(RC.month_mixes(MONTH, m.mu_s, m.cov, m.lower, m.upper, rec))


def _rows(rows: list[Row], mix: str) -> list[Row]:
    return [r for r in rows if r["mix"] == mix]


def _row(rows: list[Row], mix: str) -> Row:
    found = _rows(rows, mix)
    assert len(found) == 1
    return found[0]


def _col(rows: list[Row], name: str) -> list[Any]:
    return [r[name] for r in rows]


def _records(frame: pd.DataFrame) -> list[Row]:
    return [{str(k): v for k, v in row.items()} for row in frame.to_dict("records")]


def test_every_mix_and_cell_has_a_row_with_the_documented_columns(mixes12, rec12):
    assert set(mixes12.columns) == COLUMNS
    rows = _records(mixes12)
    assert Counter(_col(rows, "mix")) == {
        "F": 6, "F_arm1": 6, "U": 6, "E": 1, "F@E": 1, "D": 1, "F@D": 1, "D10": 1, "F@D10": 1,
    }  # fmt: skip
    assert set(_col(rows, "month")) == {MONTH}
    for mix in (RC.F, RC.F_ARM1, RC.U):
        assert _col(_rows(rows, mix), "rf") == list(A.RFS)
        assert _col(_rows(rows, mix), "r") == list(rec12.r)
    for mix in ("E", "F@E", "D", "F@D", "D10", "F@D10"):
        row = _row(rows, mix)
        assert math.isnan(row["rf"]) and math.isnan(row["r"])
    assert set(_col(_rows(rows, RC.U), "comparator")) == {RC.F}
    for mix in (RC.E, RC.D, RC.D10):
        assert _row(rows, mix)["comparator"] == RC.COMPARATOR[mix]
    for mix in (RC.F, RC.F_ARM1, "F@E", "F@D", "F@D10"):
        assert all(c is None or pd.isna(c) for c in _col(_rows(rows, mix), "comparator"))


def test_month_mixes_reconstructs_the_recorded_frontier_rows(mixes12, rec12):
    f = _rows(_records(mixes12), RC.F)
    assert set(_col(f, "status")) == {RC.KEPT}
    assert max(_col(f, "rebuilt_mu_gap")) <= 1e-6
    assert max(_col(f, "rebuilt_sigma_gap")) <= 1e-6
    assert max(_col(f, "ends_gap")) <= 1e-6
    for j in range(6):
        assert np.array_equal(f[j]["weights"], rec12.w_app[j])


def test_arm_one_rows_are_the_recorded_anchor_rows_and_kept(rec12):
    shifted = 0.9 * rec12.w_f + 0.1 / 12
    rows = _rows(_mixes(M12, dataclasses.replace(rec12, w_f=shifted)), RC.F_ARM1)
    assert set(_col(rows, "status")) == {RC.KEPT}
    for j in range(6):
        assert np.array_equal(rows[j]["weights"], shifted[j])


def test_a_recorded_row_off_the_frontier_fails_its_cell_and_u_there(rec12):
    w_app = rec12.w_app.copy()
    w_app[2] = np.full(12, 1 / 12)
    rows = _mixes(M12, dataclasses.replace(rec12, w_app=w_app))
    f, u = _rows(rows, RC.F), _rows(rows, RC.U)
    assert f[2]["status"] == RC.FAILED and f[2]["reason"] == "reconstruction"
    assert u[2]["status"] == RC.FAILED
    assert [r["status"] for r in f if r is not f[2]] == [RC.KEPT] * 5
    for mix in (RC.E, RC.D, RC.D10):
        assert _row(rows, mix)["status"] == RC.KEPT


def test_equal_weight_and_its_comparator_sit_at_the_same_risk(mixes12, rec12):
    rows = _records(mixes12)
    e, comp = _row(rows, RC.E), _row(rows, "F@E")
    assert np.allclose(e["weights"], 1 / 12)
    assert comp["risk_gap"] <= 1e-6
    assert e["mu_gap"] > 1e-6
    assert e["a"] == pytest.approx(
        RC.risk_position(e["sigma"], rec12.sigma_min, rec12.sigma_top), abs=1e-12
    )
    assert e["status"] == comp["status"] == RC.KEPT


def test_a_mix_at_or_above_the_top_is_excluded_without_a_comparator():
    rows = _mixes(THREE_E, recorded(THREE_E))
    e = _row(rows, RC.E)
    assert e["status"] == RC.EXCLUDED and e["a"] > 1
    assert e["weights"] is not None
    assert _rows(rows, "F@E") == []


def test_u_is_solved_below_the_unlimited_top_and_excluded_at_or_above_it():
    u = _rows(_mixes(THREE_U, recorded(THREE_U)), RC.U)
    assert _col(u, "status") == [RC.KEPT] * 3 + [RC.EXCLUDED] * 3
    assert max(_col(u[:3], "risk_gap")) <= 2e-6
    assert all(r["weights"] is not None for r in u[:3])
    assert all(r["weights"] is None for r in u[3:])


def test_a_u_that_keeps_the_limits_equals_f():
    kept = [r for r in _rows(_mixes(M12_OPEN, recorded(M12_OPEN)), RC.U) if r["status"] == RC.KEPT]
    assert len(kept) > 0
    assert min(_col(kept, "mu_gap")) >= -1e-6
    assert max(_col(kept, "l1")) <= 1e-4
    assert not any(_col(kept, "breaks_limit"))


def test_u_beyond_the_limits_is_flagged_when_it_breaks_one():
    kept = [r for r in _rows(_mixes(THREE_U, recorded(THREE_U)), RC.U) if r["status"] == RC.KEPT]
    assert all(_col(kept, "breaks_limit"))  # 100% in one holding at the top, over the 40% limit
    assert min(_col(kept, "mu_gap")) >= -1e-6
    assert max(_col(kept, "l1")) > 1e-4


def test_every_row_carries_its_model_figures(mixes12, rec12):
    sigma = np.sqrt(np.diag(M12.cov))
    for row in _records(mixes12):
        w = row["weights"]
        assert w is not None
        assert row["mu"] == pytest.approx(M12.mu_s @ w, abs=1e-12)
        assert row["sigma"] == pytest.approx(np.sqrt(w @ M12.cov @ w), abs=1e-12)
        assert row["dr2"] == pytest.approx(anchors.dr2(w, sigma, M12.cov), abs=1e-12)
        assert row["enb"] == pytest.approx(torsion.effective_number_of_bets(w, M12.cov), abs=1e-9)
        expected_a = RC.risk_position(row["sigma"], rec12.sigma_min, rec12.sigma_top)
        assert row["a"] == pytest.approx(expected_a, abs=1e-12)


def test_a_row_without_weights_has_no_figures():
    row = _rows(_mixes(THREE_U, recorded(THREE_U)), RC.U)[5]
    assert row["weights"] is None
    for name in ("mu", "sigma", "a", "enb", "dr2", "risk_gap", "mu_gap", "l1"):
        assert math.isnan(row[name])


@pytest.mark.parametrize("failing", ["torsion_basis", "enb"])
def test_a_torsion_failure_leaves_enb_empty_and_the_rest(monkeypatch, rec12, failing):
    def fail(*args, **kwargs):
        raise torsion.TorsionError("injected")

    monkeypatch.setattr(torsion, failing, fail)
    rows = _mixes(M12, rec12)
    assert all(math.isnan(r["enb"]) for r in rows)
    assert not any(math.isnan(r["mu"]) or math.isnan(r["dr2"]) for r in rows)


def test_a_mix_that_cannot_be_solved_fails_alone_and_has_no_comparator():
    rows = _mixes(THREE_U, recorded(THREE_U))  # three holdings cannot sum to 100% at 10% each
    d10 = _row(rows, RC.D10)
    assert d10["status"] == RC.FAILED and d10["weights"] is None
    assert _rows(rows, "F@D10") == []
    assert _row(rows, RC.D)["status"] == RC.KEPT
    assert _row(rows, RC.E)["status"] == RC.KEPT


def _fail_where(monkeypatch, name: str, limited: bool | None):
    """Make `MenuPrograms.<name>` raise `SolveError` on the programs with weight limits
    (`limited`), without (not `limited`), or on every one (None)."""
    original = getattr(optimize.MenuPrograms, name)

    def wrapper(self, *args):
        if limited is None or (self.hi.max() < 1) == limited:
            raise optimize.SolveError("injected")
        return original(self, *args)

    monkeypatch.setattr(optimize.MenuPrograms, name, wrapper)


def test_a_failed_limited_minimum_variance_program_fails_f_u_and_the_comparators(
    monkeypatch, rec12
):
    _fail_where(monkeypatch, "min_variance", limited=True)
    rows = _mixes(M12, rec12)
    assert set(_col(_rows(rows, RC.F), "status")) == {RC.FAILED}
    assert set(_col(_rows(rows, RC.U), "status")) == {RC.FAILED}
    assert set(_col(_rows(rows, RC.F_ARM1), "status")) == {RC.KEPT}
    for mix in (RC.E, RC.D, RC.D10):
        assert _row(rows, mix)["status"] == RC.FAILED
        comp = _row(rows, RC.COMPARATOR[mix])
        assert comp["status"] == RC.FAILED and comp["weights"] is None


def test_a_failed_unlimited_minimum_variance_program_fails_u_only(monkeypatch, rec12):
    _fail_where(monkeypatch, "min_variance", limited=False)
    rows = _mixes(M12, rec12)
    assert set(_col(_rows(rows, RC.U), "status")) == {RC.FAILED}
    assert set(_col(_rows(rows, RC.F), "status")) == {RC.KEPT}
    assert _row(rows, RC.E)["status"] == RC.KEPT


def test_a_u_program_that_cannot_be_solved_fails_its_cell(monkeypatch, rec12):
    _fail_where(monkeypatch, "frontier_point", limited=False)
    rows = _mixes(M12, rec12)
    u = _rows(rows, RC.U)
    assert set(_col(u, "status")) == {RC.FAILED}
    assert all(w is None for w in _col(u, "weights"))
    assert set(_col(_rows(rows, RC.F), "status")) == {RC.KEPT}


def test_a_comparator_that_cannot_be_solved_fails_the_mix(monkeypatch, rec12):
    _fail_where(monkeypatch, "frontier_point", limited=True)
    rows = _mixes(M12, rec12)
    assert set(_col(_rows(rows, RC.F), "status")) == {RC.FAILED}  # the rebuild cannot be made
    assert set(_col(_rows(rows, RC.U), "status")) == {RC.FAILED}  # U's F row failed
    for mix in (RC.E, RC.D, RC.D10):
        row, comp = _row(rows, mix), _row(rows, RC.COMPARATOR[mix])
        assert row["status"] == comp["status"] == RC.FAILED
        assert row["weights"] is not None and comp["weights"] is None


def test_a_comparator_off_the_risk_line_fails_the_mix(monkeypatch, rec12):
    def lowest(programs, lowest, top, s, sigma_min, sigma_top):
        return lowest  # on no risk line but the lowest

    monkeypatch.setattr(RC, "frontier_exact", lowest)
    rows = _mixes(M12, rec12)
    for mix in (RC.E, RC.D, RC.D10):
        row, comp = _row(rows, mix), _row(rows, RC.COMPARATOR[mix])
        assert row["status"] == comp["status"] == RC.FAILED
        assert comp["weights"] is not None and comp["risk_gap"] > 1e-6


def test_a_u_off_the_risk_line_fails_its_cell(monkeypatch, rec12):
    original = RC.frontier_exact

    def wrong_for_u(programs, lowest, top, s, sigma_min, sigma_top):
        if programs.hi.max() >= 1:
            return lowest
        return original(programs, lowest, top, s, sigma_min, sigma_top)

    monkeypatch.setattr(RC, "frontier_exact", wrong_for_u)
    u = _rows(_mixes(M12, rec12), RC.U)
    assert set(_col(u, "status")) == {RC.FAILED}
    assert min(_col(u, "risk_gap")) > RC.U_TOL
    assert all(w is not None for w in _col(u, "weights"))


# ----------------------------------------------------------------------- the recorded columns


def _column_rows(rec: RC.Recorded, month: str = MONTH, lookback: str = "3y") -> list[Row]:
    return [
        {
            "menu": "m", "month": month, "engine": "replay", "lookback": lookback,
            "r_fraction": a, "r": float(rec.r[j]), "sigma_min": rec.sigma_min,
            "sigma_top": rec.sigma_top, "w_F": list(rec.w_f[j]),
            "w_app_frontier": list(rec.w_app[j]),
        }
        for j, a in enumerate(A.RFS)
    ]  # fmt: skip


def test_recorded_columns_reads_the_six_three_year_rows(rec12):
    other = dataclasses.replace(
        rec12, r=rec12.r + 0.01, sigma_min=rec12.sigma_min + 0.01, w_app=rec12.w_app[:, ::-1]
    )
    rows = [
        *reversed(_column_rows(rec12)),
        *_column_rows(other, lookback="5y"),
        *_column_rows(other, month="2010-02"),
    ]
    got = RC.recorded_columns(pd.DataFrame(rows), MONTH)
    assert np.array_equal(got.r, rec12.r)
    assert got.sigma_min == rec12.sigma_min and got.sigma_top == rec12.sigma_top
    assert np.array_equal(got.w_f, rec12.w_f) and np.array_equal(got.w_app, rec12.w_app)
    short = [r for r in rows if not (r["lookback"] == "3y" and r["r_fraction"] == A.RFS[3])]
    with pytest.raises(ValueError, match=MONTH):
        RC.recorded_columns(pd.DataFrame(short), MONTH)


def test_recorded_columns_refuses_a_repeated_setting_and_a_missing_weight(rec12):
    rows = _column_rows(rec12)
    with pytest.raises(ValueError):
        RC.recorded_columns(pd.DataFrame([*rows, rows[0]]), MONTH)
    for name in ("w_F", "w_app_frontier"):
        holed = [dict(rows[0], **{name: None}), *rows[1:]]
        with pytest.raises(ValueError, match=name):
            RC.recorded_columns(pd.DataFrame(holed), MONTH)


# ------------------------------------------------------------- the pre-registered lists


def test_the_pre_registered_lists_are_the_protocols():
    months = RC.E_EXCLUDED
    assert len(months) == 25
    assert list(months) == sorted(set(months))  # in order, each once
    assert months[0] == "2008-11" and months[-1] == "2020-05"
    assert max(months) < "2021-09"  # E keeps 161 of the 186 five-year start months
    assert [m for m in months if m.startswith("2009")] == [f"2009-{k:02d}" for k in range(1, 13)]
    assert RC.U_EXCLUDED == (("2008-09", 0.85), ("2010-08", 0.85))


# ------------------------------------------------------------ the pool, with the ratio dr2

POOL_N = 3
POOL_LIMITS = (np.zeros(POOL_N), np.full(POOL_N, 0.5))


def _values(**kw: float) -> np.ndarray:
    v = np.zeros(len(FIELDS))
    for name, value in kw.items():
        v[FIELDS.index(name)] = value
    return v


def _pool_file(path: Path, rows: list[dict[str, Any]]) -> Path:
    """A pool file as the run writes it (`PoolBuffer`, `write_pool`); each row gives `weights`
    and its fields, with `lookback`, `r_fraction` and `lam` defaulting to a main row."""
    buf = PoolBuffer()
    for row in rows:
        row = dict(row)
        weights = np.asarray(row.pop("weights"), dtype=float)
        key = {"lookback": row.pop("lookback", "3y"), "r_fraction": row.pop("r_fraction", 0.10),
               "lam": row.pop("lam", None)}  # fmt: skip
        buf.add(**key, r=0.1, arm="F", start=-1, call=-1, source="search", weights=weights,
                values=_values(**row))  # fmt: skip
    table = buf.table(menu="m", month=MONTH, origin=date(2010, 1, 29), engine="replay",
                      seed=C.PRIMARY_SEED)  # fmt: skip
    write_pool(path, table, {b"digest": b"x"})
    return path


INSIDE = [0.4, 0.35, 0.25]
FIGURES = {"sigma": 0.1, "mu": 0.05, "tdd": 0.2, "enb": 1.5, "h": 0.3, "in_wide": 1.0}


def test_the_extended_reader_reads_the_region_checks_rows_with_dr2(tmp_path):
    path = _pool_file(
        tmp_path / "pool.parquet",
        [
            {"weights": INSIDE, "dr2": 1.5, **FIGURES},
            {"weights": INSIDE, "dr2": 1.5, **FIGURES, "r_fraction": 0.25},
            {"weights": [0.8, 0.1, 0.1], "dr2": 9.0, **FIGURES},
            {"weights": INSIDE, "dr2": 2.0, **FIGURES, "lookback": "5y"},
            {"weights": INSIDE, "dr2": 3.0, **FIGURES, "lam": 0.05},
        ],
    )
    pool = RC.read_month_pool_dr2(path)
    assert len(pool) == 3
    assert "dr2" in pool.columns
    assert set(G.POOL_COLUMNS) <= set(pool.columns)
    assert list(pool["record"]) == list(G.read_month_pool(path)["record"])
    assert sorted(pool["dr2"]) == [1.5, 1.5, 9.0]


def test_allowed_mixes_drops_rows_outside_the_limits_and_repeats(tmp_path):
    path = _pool_file(
        tmp_path / "pool.parquet",
        [
            {"weights": INSIDE, "dr2": 1.5, **FIGURES},
            {"weights": INSIDE, "dr2": 1.5, **FIGURES, "r_fraction": 0.25},
            {"weights": [0.8, 0.1, 0.1], "dr2": 9.0, **FIGURES},
        ],
    )
    allowed = RC.allowed_mixes(RC.read_month_pool_dr2(path), *POOL_LIMITS)
    assert len(allowed) == 1
    assert allowed["dr2"].iloc[0] == 1.5


# --------------------------------------------------------- the pool checks of one start month

POOL_CHECKS = ("pool_dr2_max", "pool_mu_bound", "pool_mu_at_risk", "tie")


def _cell(mix: str, **values: Any) -> Row:
    """One made-up row of `month_mixes`: every column, kept, in `MONTH`."""
    row: Row = dict.fromkeys(COLUMNS, math.nan)
    row.update(month=MONTH, mix=mix, status=RC.KEPT, reason="", weights=None, comparator=None,
               breaks_limit=None)  # fmt: skip
    if mix in RC.COMPARATOR:
        row["comparator"] = RC.COMPARATOR[mix]
    row.update(values)
    return row


def _pool(rows: list[Row]) -> pd.DataFrame:
    """A made-up pool as `read_month_pool_dr2` returns it: each row gives `weights` and any of
    `sigma`, `mu`, `dr2`; the other measures are filled in."""
    full = [
        {"record": k, "lookback": "3y", "seed": C.PRIMARY_SEED, "r_fraction": 0.10,
         "lam": math.nan, "in_wide": True, "sigma": 0.1, "mu": 0.05, "tdd": 0.2, "enb": 1.5,
         "h": 0.3, "dr2": 1.0, **row, "weights": np.asarray(row["weights"], dtype=float)}
        for k, row in enumerate(rows)
    ]  # fmt: skip
    return pd.DataFrame(full, columns=list(RC.POOL_COLUMNS_DR2))


def _checked(cells: list[Row], pool: list[Row], limits=POOL_LIMITS) -> list[Row]:
    return _records(RC.month_pool_checks(pd.DataFrame(cells), _pool(pool), *limits))


def test_month_pool_checks_adds_four_columns_and_keeps_every_row():
    cells = [_cell(RC.F, rf=0.1, r=0.1), _cell(RC.E, mu=0.05, sigma=0.1, mu_gap=0.01),
             _cell("F@E", mu=0.06, sigma=0.1)]  # fmt: skip
    out = RC.month_pool_checks(pd.DataFrame(cells), _pool([]), *POOL_LIMITS)
    assert list(out.columns) == [*pd.DataFrame(cells).columns, *POOL_CHECKS]
    assert list(out["mix"]) == [RC.F, RC.E, "F@E"]


def test_check_b_reads_the_largest_recorded_ratio_in_the_mixes_domain():
    n = 12
    limits = (np.zeros(n), np.full(n, 0.4))
    pool = [
        {"weights": np.full(n, 1 / n), "dr2": 1.2},  # every weight at most 10%
        {"weights": [0.3, *np.full(n - 1, 0.7 / (n - 1))], "dr2": 1.4},  # one weight 30%
        {"weights": [0.5, *np.full(n - 1, 0.5 / (n - 1))], "dr2": 9.0},  # above the 40% limit
    ]
    built = {"weights": np.full(n, 1 / n), "dr2": 2.0}
    cells = [_cell(RC.D, **built), _cell(RC.D10, **built), _cell(RC.D10, status=RC.FAILED)]
    d, d10, unbuilt = _checked(cells, pool, limits)
    assert d["pool_dr2_max"] == 1.4
    assert d10["pool_dr2_max"] == 1.2
    assert math.isnan(unbuilt["pool_dr2_max"])  # a mix not built is the failed-cell rule's


def test_check_b_reads_the_ratio_for_an_excluded_d_too():
    cells = [_cell(RC.D, status=RC.EXCLUDED, weights=np.array(INSIDE), dr2=2.0)]
    (d,) = _checked(cells, [{"weights": INSIDE, "dr2": 1.7}])
    assert d["pool_dr2_max"] == 1.7


def test_the_u_bound_uses_rows_at_or_below_the_risk_with_no_tolerance():
    r = 0.1
    cells = [_cell(RC.U, rf=0.1, r=r, mu=0.08, sigma=r)]
    pool = [
        {"weights": INSIDE, "sigma": r, "mu": 0.05},
        {"weights": INSIDE, "sigma": r + 1e-9, "mu": 0.09},
    ]
    (u,) = _checked(cells, pool)
    assert u["pool_mu_bound"] == 0.05
    breaking = [*pool, {"weights": [0.8, 0.1, 0.1], "sigma": r, "mu": 0.07}]
    (u,) = _checked(cells, breaking)
    assert u["pool_mu_bound"] == 0.07


def test_the_u_bound_is_left_empty_on_an_excluded_or_failed_u():
    cells = [_cell(RC.U, rf=0.1, r=0.1, status=RC.EXCLUDED),
             _cell(RC.U, rf=0.25, r=0.1, status=RC.FAILED)]  # fmt: skip
    for u in _checked(cells, [{"weights": INSIDE, "sigma": 0.05, "mu": 0.05}]):
        assert math.isnan(u["pool_mu_bound"])


def _pair(mu_gap: float = 0.0, **e: Any) -> list[Row]:
    """E kept at model return 0.05 and risk 0.10, with its comparator `F@E`."""
    return [_cell(RC.E, mu=0.05, sigma=0.10, mu_gap=mu_gap, **e),
            _cell("F@E", mu=0.05 + mu_gap, sigma=0.10)]  # fmt: skip


def test_a_mix_on_the_frontier_is_a_kept_tie():
    e, comp = _checked(_pair(), [{"weights": INSIDE, "sigma": 0.09, "mu": 0.049}])
    assert e["tie"] is True and e["status"] == RC.KEPT
    assert e["pool_mu_at_risk"] == 0.049
    assert comp["status"] == RC.KEPT


def test_a_comparator_that_misses_a_better_pool_row_is_a_failed_cell():
    e, comp = _checked(_pair(), [{"weights": INSIDE, "sigma": 0.10, "mu": 0.06}])
    assert e["tie"] is False
    assert e["status"] == comp["status"] == RC.FAILED
    assert e["reason"] == comp["reason"] == "the comparator missed a better recorded mix"


def test_rows_above_the_risk_or_outside_the_limits_do_not_refute_a_tie():
    above = {"weights": INSIDE, "sigma": 0.11, "mu": 0.06}
    outside = {"weights": [0.8, 0.1, 0.1], "sigma": 0.09, "mu": 0.06}
    for pool in ([above], [outside]):
        e, comp = _checked(_pair(), pool)
        assert e["tie"] is True
        assert e["status"] == comp["status"] == RC.KEPT


def test_a_gap_above_the_tolerance_is_no_tie():
    e, comp = _checked(_pair(mu_gap=2e-6), [{"weights": INSIDE, "sigma": 0.09, "mu": 0.5}])
    assert e["tie"] is False
    assert e["status"] == comp["status"] == RC.KEPT


def test_a_gap_at_the_tolerance_is_a_tie_decided_by_the_pool():
    e, _ = _checked(_pair(mu_gap=1e-6), [{"weights": INSIDE, "sigma": 0.09, "mu": 0.05 + 1e-6}])
    assert e["tie"] is True and e["status"] == RC.KEPT
    e, _ = _checked(_pair(mu_gap=1e-6), [{"weights": INSIDE, "sigma": 0.09, "mu": 0.05 + 2e-6}])
    assert e["status"] == RC.FAILED


def test_a_kept_mix_without_a_return_gap_fails_its_cell():
    e, comp = _checked(_pair(mu_gap=math.nan), [])
    assert e["tie"] is False
    assert e["status"] == comp["status"] == RC.FAILED


def test_a_cell_with_no_pool_row_at_its_risk_passes():
    cells = [_cell(RC.U, rf=0.1, r=0.1, mu=0.08, sigma=0.1), *_pair()]
    u, e, _ = _checked(cells, [{"weights": INSIDE, "sigma": 0.2, "mu": 0.5}])
    assert u["pool_mu_bound"] == -math.inf
    assert e["pool_mu_at_risk"] == -math.inf
    assert e["tie"] is True and e["status"] == RC.KEPT
    u, e, _ = _checked(cells, [])
    assert u["pool_mu_bound"] == -math.inf


def test_a_pool_row_without_a_model_measure_stops_naming_the_month():
    cells = [_cell(RC.D, dr2=2.0)]
    for missing in ("mu", "sigma", "dr2"):
        with pytest.raises(ValueError, match=MONTH):
            _checked(cells, [{"weights": INSIDE, missing: math.nan}])
    outside = {"weights": [0.8, 0.1, 0.1], "mu": math.nan}  # the U bound reads it too
    with pytest.raises(ValueError, match=MONTH):
        _checked(cells, [outside])
