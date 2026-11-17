"""The simple and diversification-driven recipes check
(docs/plans/2026-11-11-diversification-vs-simple-mixes.md, built by
docs/plans/2026-11-15-diversification-vs-simple-mixes-build-plan.md) on made-up menus whose
answers are known by hand or by the optimizer's own frontier: the most-diversified mix against
the paper's two examples, the exact-line frontier mix at its three branches, and one start
month's mixes with their statuses. No data file, fixed seeds."""

from __future__ import annotations

import dataclasses
import itertools
import json
import math
from collections import Counter
from datetime import date
from pathlib import Path
from types import SimpleNamespace
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
from tests.research.fixedrisk.optimizer_data import synthetic_context
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
    """E kept at model return 0.05 and risk 0.10, with its comparator `F@E` on its risk line."""
    return [_cell(RC.E, mu=0.05, sigma=0.10, mu_gap=mu_gap, weights=np.array(INSIDE), **e),
            _cell("F@E", mu=0.05 + mu_gap, sigma=0.10, risk_gap=0.0,
                  weights=np.array([0.3, 0.4, 0.3]))]  # fmt: skip


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


# ---------------------------------------------------------------- the gates across months

NO_LISTS: tuple[tuple[str, ...], tuple[tuple[str, float], ...]] = ((), ())


def _months(k: int, start: int = 2012) -> list[str]:
    return [f"{start + i // 12}-{i % 12 + 1:02d}" for i in range(k)]


def _model_cells(months: list[str]) -> pd.DataFrame:
    """Made-up `month_pool_checks` rows of `months` that pass every gate: F, arm 1 and U kept at
    the six settings; E, D and D10 kept off the frontier, each with its comparator."""
    w = np.array([0.5, 0.5])
    rows: list[Row] = []

    def add(month: str, mix: str, **values: Any) -> None:
        row = _cell(mix, month=month, weights=w, pool_dr2_max=math.nan, pool_mu_bound=math.nan,
                    pool_mu_at_risk=math.nan, tie=False)  # fmt: skip
        row.update(values)
        rows.append(row)

    for m in months:
        for j, rf in enumerate(A.RFS):
            r = 0.05 + 0.01 * j
            add(m, RC.F, rf=rf, r=r, mu=0.05, sigma=r, rebuilt_mu_gap=0.0,
                rebuilt_sigma_gap=0.0, rebuilt_l1=0.0, ends_gap=0.0)  # fmt: skip
            add(m, RC.F_ARM1, rf=rf, r=r, mu=0.05, sigma=r)
        for j, rf in enumerate(A.RFS):
            r = 0.05 + 0.01 * j
            add(m, RC.U, rf=rf, r=r, mu=0.051, sigma=r, risk_gap=0.0, mu_gap=0.001, l1=0.1,
                breaks_limit=False, pool_mu_bound=0.04)  # fmt: skip
        for mix, dr2, a in ((RC.E, 1.2, 0.5), (RC.D, 1.5, 0.2), (RC.D10, 1.3, 0.3)):
            add(m, mix, mu=0.04, sigma=0.08, a=a, mu_gap=0.01, l1=0.2, dr2=dr2,
                pool_dr2_max=dr2 - 0.1, pool_mu_at_risk=0.03)  # fmt: skip
            add(m, RC.COMPARATOR[mix], mu=0.05, sigma=0.08, risk_gap=0.0)
    return pd.DataFrame(rows)


def _at(cells: pd.DataFrame, month: str, mix: str, rf: float | None = None) -> np.ndarray:
    mask = (cells["month"].to_numpy() == month) & (cells["mix"].to_numpy() == mix)
    if rf is not None:
        mask &= np.isclose(cells["rf"].to_numpy(dtype=float), rf)
    assert mask.sum() == 1
    return mask


def _set(cells: pd.DataFrame, month: str, mix: str, rf: float | None = None, **values) -> None:
    mask = _at(cells, month, mix, rf)
    for name, value in values.items():
        cells.loc[mask, name] = value


def _exclude(cells: pd.DataFrame, month: str, mix: str, rf: float | None = None) -> pd.DataFrame:
    """`mix` excluded at the cell, as `month_mixes` leaves it: no comparator row; U unbuilt."""
    if mix == RC.U:
        _set(cells, month, mix, rf, status=RC.EXCLUDED, mu=math.nan, mu_gap=math.nan,
             risk_gap=math.nan, pool_mu_bound=math.nan)  # fmt: skip
        cells.loc[_at(cells, month, mix, rf), "weights"] = None
        return cells
    _set(cells, month, mix, status=RC.EXCLUDED, a=1.2, mu_gap=math.nan, pool_mu_at_risk=math.nan)
    return cells.loc[~_at(cells, month, RC.COMPARATOR[mix])].reset_index(drop=True)


def _fail(cells: pd.DataFrame, month: str, mix: str, rf: float | None = None,
          reason: str = "solver: made up") -> None:  # fmt: skip
    _set(cells, month, mix, rf, status=RC.FAILED, reason=reason)
    if mix in RC.RECIPES:
        _set(cells, month, RC.COMPARATOR[mix], status=RC.FAILED, reason=reason)


def _stops(checks: dict) -> list[str]:
    return [s["gate"] for s in checks["stops"]]


def test_a_consistent_table_passes_every_gate():
    months = _months(4)
    checks = RC.gates(_model_cells(months), months, expected=NO_LISTS)
    assert checks["stops"] == []
    assert checks["reconstruction"]["cells"] == 24
    assert checks["failed_cells"][RC.U]["cells"] == 24
    assert checks["check_b"][RC.D]["months"] == 4


def test_reconstruction_stops_above_one_percent():
    months = _months(50)  # 300 F cells: 3 failed are 1%, 4 are above
    cells = _model_cells(months)
    for k in range(3):
        _fail(cells, months[k], RC.F, A.RFS[k], reason=RC.RECONSTRUCTION)
        _fail(cells, months[k], RC.U, A.RFS[k], reason="the F row of this setting failed")
    checks = RC.gates(cells, months, expected=NO_LISTS)
    assert "reconstruction" not in _stops(checks)
    assert checks["reconstruction"]["failed"] == 3
    assert len(checks["reconstruction"]["failed_cells"]) == 3
    _fail(cells, months[3], RC.F, A.RFS[0], reason=RC.RECONSTRUCTION)
    assert "reconstruction" in _stops(RC.gates(cells, months, expected=NO_LISTS))


def test_a_kept_f_row_with_a_gap_above_the_tolerance_counts_as_failed():
    months = _months(1)
    cells = _model_cells(months)
    _set(cells, months[0], RC.F, A.RFS[0], rebuilt_sigma_gap=2e-6)
    checks = RC.gates(cells, months, expected=NO_LISTS)
    assert checks["reconstruction"]["failed"] == 1
    assert "reconstruction" in _stops(checks)
    _set(cells, months[0], RC.F, A.RFS[0], rebuilt_sigma_gap=math.nan)
    assert RC.gates(cells, months, expected=NO_LISTS)["reconstruction"]["failed"] == 1
    cells = _model_cells(months)
    cells["rebuilt_mu_gap"] = cells["rebuilt_mu_gap"].astype(object)
    cells.loc[_at(cells, months[0], RC.F, A.RFS[1]), "rebuilt_mu_gap"] = None
    assert RC.gates(cells, months, expected=NO_LISTS)["reconstruction"]["failed"] == 1


def test_list_gate():
    months = ["2009-01", "2009-02", "2015-01", "2015-02"]
    expected = (("2009-01", "2009-02"), (("2015-01", 0.85),))
    base = _model_cells(months)
    for month in ("2009-01", "2009-02"):
        base = _exclude(base, month, RC.E)
    _exclude(base, "2015-01", RC.U, 0.85)

    checks = RC.gates(base, months, expected=expected)
    assert "list gate" not in _stops(checks)
    assert checks["list_gate"]["e_excluded"] == ["2009-01", "2009-02"]
    assert checks["exclusions"][RC.E]["excluded"] == 2
    assert checks["exclusions"][RC.E]["list"] == ["2009-01", "2009-02"]
    assert checks["exclusions"][RC.U]["list"] == [{"month": "2015-01", "rf": 0.85}]

    more = _exclude(base.copy(), "2015-02", RC.E)
    assert "list gate" in _stops(RC.gates(more, months, expected=expected))
    fewer = RC.gates(base, months, expected=(("2009-01", "2009-02", "2015-02"), expected[1]))
    assert "list gate" in _stops(fewer)
    extra_u = base.copy()
    _exclude(extra_u, "2015-02", RC.U, 0.85)
    assert "list gate" not in _stops(RC.gates(extra_u, months, expected=expected))
    missing_u = RC.gates(base, months, expected=(expected[0], (("2015-02", 0.85),)))
    assert "list gate" in _stops(missing_u)
    assert missing_u["list_gate"]["u_missing"] == [{"month": "2015-02", "rf": 0.85}]

    scoped = A._frame(base.loc[base["month"].isin(["2009-01", "2015-01"])])
    checks = RC.gates(scoped, months, expected=expected, scope=["2009-01", "2015-01"])
    assert checks["list_gate"]["e_expected"] == ["2009-01"]
    assert checks["stops"] == []


def test_the_pre_registered_lists_are_the_default_expectation(monkeypatch):
    months = ["2009-01", "2015-01"]
    cells = _exclude(_model_cells(months), "2009-01", RC.E)
    _exclude(cells, "2015-01", RC.U, 0.85)
    monkeypatch.setattr(RC, "E_EXCLUDED", ("2009-01",))
    monkeypatch.setattr(RC, "U_EXCLUDED", (("2015-01", 0.85),))
    assert RC.gates(cells, months)["stops"] == []
    monkeypatch.setattr(RC, "E_EXCLUDED", ("2009-01", "2015-01"))
    assert "list gate" in _stops(RC.gates(cells, months))


@pytest.mark.parametrize("mix", [RC.D, RC.D10])
def test_check_b_stops_on_one_month(mix):
    months = _months(3)
    cells = _model_cells(months)
    _set(cells, months[1], mix, dr2=1.5, pool_dr2_max=1.5000005)
    checks = RC.gates(cells, months, expected=NO_LISTS)
    assert "check (b)" not in _stops(checks)
    assert checks["check_b"][mix]["smallest_margin"] == pytest.approx(-5e-7, abs=1e-12)
    _set(cells, months[1], mix, pool_dr2_max=1.50001)
    checks = RC.gates(cells, months, expected=NO_LISTS)
    assert "check (b)" in _stops(checks)
    assert [f["month"] for f in checks["check_b"][mix]["failed"]] == [months[1]]


@pytest.mark.parametrize("mix", [RC.D, RC.D10])
def test_check_b_fails_closed(mix):
    months = _months(2)
    cells = _model_cells(months)
    _set(cells, months[0], mix, dr2=math.nan)
    assert "check (b)" in _stops(RC.gates(cells, months, expected=NO_LISTS))
    cells = _model_cells(months)
    _set(cells, months[0], mix, pool_dr2_max=math.nan)  # never read against the pool
    assert "check (b)" in _stops(RC.gates(cells, months, expected=NO_LISTS))
    cells = _model_cells(months)
    for month in months:  # no month to judge
        _fail(cells, month, mix)
        cells.loc[_at(cells, month, mix), "weights"] = None
    assert "check (b)" in _stops(RC.gates(cells, months, expected=NO_LISTS))


def test_check_b_passes_a_month_without_an_allowed_row_and_lists_it():
    months = _months(2)
    cells = _model_cells(months)
    _set(cells, months[0], RC.D10, pool_dr2_max=-math.inf)
    checks = RC.gates(cells, months, expected=NO_LISTS)
    assert "check (b)" not in _stops(checks)
    assert checks["check_b"][RC.D10]["without_rows"] == [months[0]]


def test_check_b_judges_an_excluded_d():
    months = _months(2)
    cells = _exclude(_model_cells(months), months[0], RC.D)
    _set(cells, months[0], RC.D, dr2=1.0, pool_dr2_max=1.2)
    assert "check (b)" in _stops(RC.gates(cells, months, expected=NO_LISTS))


def test_u_gates():
    months = _months(2)
    m, rf = months[1], A.RFS[2]
    cells = _model_cells(months)
    _set(cells, m, RC.U, rf, mu_gap=-5e-7)
    assert "U return" not in _stops(RC.gates(cells, months, expected=NO_LISTS))
    _set(cells, m, RC.U, rf, mu_gap=-2e-6)
    checks = RC.gates(cells, months, expected=NO_LISTS)
    assert "U return" in _stops(checks)
    assert checks["u_return"]["failed"] == [{"month": m, "rf": rf, "mu_gap": -2e-6}]

    cells = _model_cells(months)
    _set(cells, m, RC.U, rf, mu=0.05, pool_mu_bound=0.05 + 5e-7)
    assert "U pool bound" not in _stops(RC.gates(cells, months, expected=NO_LISTS))
    _set(cells, m, RC.U, rf, pool_mu_bound=0.05 + 2e-6)
    assert "U pool bound" in _stops(RC.gates(cells, months, expected=NO_LISTS))


def test_u_gates_fail_closed():
    months = _months(2)
    for column in ("mu_gap", "pool_mu_bound"):
        cells = _model_cells(months)
        _set(cells, months[0], RC.U, A.RFS[0], **{column: math.nan})
        stops = _stops(RC.gates(cells, months, expected=NO_LISTS))
        assert ("U return" if column == "mu_gap" else "U pool bound") in stops
    cells = _model_cells(months)
    for month in months:
        for rf in A.RFS:
            _fail(cells, month, RC.U, rf)
    stops = _stops(RC.gates(cells, months, expected=NO_LISTS))
    assert {"U return", "U pool bound"} <= set(stops)  # no kept U cell to judge


def test_a_u_cell_without_a_pool_row_at_its_risk_passes_and_is_listed():
    months = _months(2)
    cells = _model_cells(months)
    _set(cells, months[0], RC.U, A.RFS[0], pool_mu_bound=-math.inf)
    checks = RC.gates(cells, months, expected=NO_LISTS)
    assert checks["stops"] == []
    assert checks["u_pool_bound"]["without_rows"] == [{"month": months[0], "rf": A.RFS[0]}]


def test_failed_cells_use_the_kept_cells_of_the_eligible_months():
    eligible = _months(100)
    other = "2030-01"
    cells = _model_cells([*eligible, other])
    for k in range(20):
        _exclude(cells, eligible[k], RC.U, A.RFS[k % 6])
    for k in range(5):
        _fail(cells, eligible[50 + k], RC.U, A.RFS[k], reason=f"made up {k}")
    _fail(cells, other, RC.U, A.RFS[0])
    checks = RC.gates(cells, eligible, expected=NO_LISTS)
    u = checks["failed_cells"][RC.U]
    assert (u["cells"], u["failed"]) == (580, 5)
    assert [c["reason"] for c in u["list"]] == [f"made up {k}" for k in range(5)]
    assert u["other_months"] == [{"month": other, "rf": A.RFS[0], "reason": "solver: made up"}]
    assert "failed cells" not in _stops(checks)
    _fail(cells, eligible[60], RC.U, A.RFS[0])
    checks = RC.gates(cells, eligible, expected=NO_LISTS)
    assert checks["failed_cells"][RC.U]["failed"] == 6
    assert "failed cells" in _stops(checks)


@pytest.mark.parametrize("mix", [RC.E, RC.D, RC.D10])
def test_failed_cells_of_a_recipe_stop_above_one_percent(mix):
    eligible = _months(100)
    cells = _model_cells(eligible)
    _fail(cells, eligible[0], mix)
    checks = RC.gates(cells, eligible, expected=NO_LISTS)
    assert checks["failed_cells"][mix]["failed"] == 1
    assert "failed cells" not in _stops(checks)
    _fail(cells, eligible[1], mix)
    assert "failed cells" in _stops(RC.gates(cells, eligible, expected=NO_LISTS))


def test_a_kept_cell_off_its_risk_line_counts_as_failed():
    months = _months(1)
    cells = _model_cells(months)
    _set(cells, months[0], RC.U, A.RFS[0], risk_gap=3e-6)
    _set(cells, months[0], "F@E", risk_gap=2e-6)
    checks = RC.gates(cells, months, expected=NO_LISTS)
    assert checks["failed_cells"][RC.U]["failed"] == 1
    assert checks["failed_cells"][RC.E]["failed"] == 1
    assert checks["risk_gap"][RC.U]["above"] == 1
    cells = A._frame(cells.loc[~_at(cells, months[0], "F@D")])  # a kept D with no comparator
    assert "structure" in _stops(RC.gates(cells, months, expected=NO_LISTS))


def test_a_mix_with_no_cell_to_judge_stops():
    months = _months(2)
    cells = _model_cells(months)
    for month in months:
        cells = _exclude(cells, month, RC.D)
    assert "failed cells" in _stops(RC.gates(cells, months, expected=NO_LISTS))


def test_an_eligible_month_without_cells_stops_unless_out_of_scope():
    months = _months(3)
    cells = _model_cells(months[:2])
    assert "coverage" in _stops(RC.gates(cells, months, expected=NO_LISTS))
    checks = RC.gates(cells, months, expected=NO_LISTS, scope=months[:2])
    assert checks["stops"] == []


def test_a_u_that_keeps_the_limits_is_reported_as_equal_to_f(rec12):
    mixes = RC.month_mixes(MONTH, M12_OPEN.mu_s, M12_OPEN.cov, M12_OPEN.lower, M12_OPEN.upper,
                           recorded(M12_OPEN))  # fmt: skip
    cells = RC.month_pool_checks(mixes, _pool([]), M12_OPEN.lower, M12_OPEN.upper)
    checks = RC.gates(cells, [MONTH], expected=NO_LISTS)
    assert checks["u_limits"] == {"breaks_share": 0.0, "l1_above_share": 0.0}
    assert checks["u_return"]["failed"] == []


def test_strict_gap_report():
    months = _months(3)
    cells = _model_cells(months)
    _set(cells, months[0], RC.D, mu_gap=0.0, tie=True, l1=5e-5)
    _fail(cells, months[1], RC.D, reason=RC.REFUTED)
    checks = RC.gates(cells, months, expected=NO_LISTS)
    assert checks["strict_gap"][RC.D] == {"ties_kept": 1, "ties_refuted": 1, "undecided": 0,
                                          "l1_below": 1}  # fmt: skip
    assert checks["strict_gap"][RC.E] == {"ties_kept": 0, "ties_refuted": 0, "undecided": 0,
                                          "l1_below": 0}  # fmt: skip


def test_risk_position_counts_months_at_or_above_the_top():
    months = _months(5)
    cells = _model_cells(months)
    for month, a in zip(months, (0.12, 0.5, 0.3, 0.86), strict=False):
        _set(cells, month, RC.E, a=a)
    cells = _exclude(cells, months[4], RC.E)
    _set(cells, months[4], RC.E, a=1.3)
    position = RC.gates(cells, months[1:], expected=NO_LISTS)["risk_position"]
    every = position[RC.E]["all"]
    assert every["at_or_above_top"] == 1
    assert every["nearest"] == {0.10: 1, 0.25: 1, 0.40: 0, 0.55: 1, 0.70: 0, 0.85: 1}
    assert every["months"] == 5
    assert every["median"] == pytest.approx(0.5)
    assert every["mean"] == pytest.approx((0.12 + 0.5 + 0.3 + 0.86 + 1.3) / 5)
    assert every["p5"] == pytest.approx(np.percentile([0.12, 0.5, 0.3, 0.86, 1.3], 5))
    eligible = position[RC.E]["eligible"]
    assert eligible["months"] == 4
    assert eligible["nearest"] == {0.10: 0, 0.25: 1, 0.40: 0, 0.55: 1, 0.70: 0, 0.85: 1}


def test_flagged_months_and_geometry():
    months = _months(2)
    cells = _model_cells(months)
    _fail(cells, months[1], RC.F, A.RFS[3], reason=RC.RECONSTRUCTION)
    _set(cells, months[0], RC.F, A.RFS[0], ends_gap=3e-7)
    checks = RC.gates(cells, months, expected=NO_LISTS)
    assert checks["flagged_months"] == [
        {"month": months[1], "settings": [A.RFS[3]], "kept": [RC.E, RC.D, RC.D10]}
    ]
    assert checks["geometry"]["largest_ends_gap"] == 3e-7


# ------------------------------------------------------------- the model side of a job

SIDE_MONTHS = ["2015-01", "2015-02", "2015-03"]  # made up; none is on the pre-registered lists
_POOL_FILES = itertools.count()


@pytest.fixture(scope="module")
def side_inputs(tmp_path_factory):
    """Three made-up start months on 12-holding menus (seeds 7, 8, 9) with the recorded columns
    the run would hold and a pool file each of 50 mixes inside the limits, scored with their true
    model return, risk and diversification ratio."""
    folder = tmp_path_factory.mktemp("side")
    contexts, column_rows, pools = {}, [], {}
    for k, month in enumerate(SIDE_MONTHS):
        ctx = synthetic_context(funds=12, rows=400, cap=0.4, seed=7 + k)
        menu = SimpleNamespace(mu_s=ctx.mu_s, cov=ctx.cov, lower=M12.lower, upper=M12.upper)
        contexts[month] = SimpleNamespace(mu_s=ctx.mu_s, cov=ctx.cov, origin=date(2015, k + 1, 28))
        column_rows += _column_rows(recorded(menu), month=month)
        rng = np.random.default_rng(100 + k)
        rows = []
        for _ in range(50):
            w = anchors.project_box_simplex(rng.normal(0.0, 0.3, 12), M12.lower, M12.upper)
            rows.append({"weights": w, "mu": float(ctx.mu_s @ w),
                         "sigma": float(np.sqrt(w @ ctx.cov @ w)),
                         "dr2": anchors.dr2(w, ctx.sigma, ctx.cov), "tdd": 0.2, "enb": 1.5,
                         "h": 0.3})  # fmt: skip
        pools[month] = rows
    return contexts, pd.DataFrame(column_rows), pools, folder


def _side(side_inputs, pools=None, **kwargs) -> RC.ModelSide:
    contexts, columns, default_pools, folder = side_inputs
    pools = default_pools if pools is None else pools
    paths = {}
    for month, rows in pools.items():
        paths[month] = _pool_file(folder / f"{month}-{next(_POOL_FILES)}.parquet", rows)
    return RC.model_side(SIDE_MONTHS, contexts.__getitem__, columns, paths.__getitem__,
                         M12.lower, M12.upper, SIDE_MONTHS, **kwargs)  # fmt: skip


@pytest.fixture(scope="module")
def side3(side_inputs) -> RC.ModelSide:
    return _side(side_inputs, expected=NO_LISTS)


def test_model_side_passes_on_a_consistent_run(side3, side_inputs):
    assert side3.checks["stops"] == []
    assert list(dict.fromkeys(side3.cells["month"])) == SIDE_MONTHS
    assert len(side3.cells) == 3 * 24
    origins = side3.cells.groupby("month")["origin"].unique()
    assert {m: list(v) for m, v in origins.items()} == {
        m: [side_inputs[0][m].origin] for m in SIDE_MONTHS
    }
    assert set(RC.POOL_CHECKS) <= set(side3.cells.columns)


def test_model_side_reports_each_month(side_inputs):
    said: list[str] = []
    _side(side_inputs, expected=NO_LISTS, progress=said.append)
    assert len(said) == 3 and all(m in s for m, s in zip(SIDE_MONTHS, said, strict=True))


def test_the_pre_registered_lists_are_the_default(side_inputs):
    assert "list gate" in _stops(_side(side_inputs).checks)


def test_a_restricted_run_requires_only_the_listed_months_it_chose(side_inputs):
    assert "list gate" not in _stops(_side(side_inputs, restricted=True).checks)


def test_an_inflated_recorded_ratio_stops_at_check_b(side_inputs):
    pools = dict(side_inputs[2])
    month = SIDE_MONTHS[1]
    pools[month] = [{**pools[month][0], "dr2": 99.0}, *pools[month][1:]]
    checks = _side(side_inputs, pools=pools, expected=NO_LISTS).checks
    assert "check (b)" in _stops(checks)
    assert [f["month"] for f in checks["check_b"][RC.D]["failed"]] == [month]


def test_a_month_without_pool_rows_is_allowed(side_inputs):
    pools = dict(side_inputs[2])
    month = SIDE_MONTHS[0]
    pools[month] = [{**row, "lookback": "5y"} for row in pools[month]]  # no main row
    checks = _side(side_inputs, pools=pools, expected=NO_LISTS).checks
    assert checks["stops"] == []
    assert checks["check_b"][RC.D]["without_rows"] == [month]
    assert len([c for c in checks["u_pool_bound"]["without_rows"] if c["month"] == month]) == 6


def test_an_allowed_pool_row_without_a_model_measure_stops_naming_the_month(side_inputs):
    pools = dict(side_inputs[2])
    month = SIDE_MONTHS[2]
    pools[month] = [{**pools[month][0], "tdd": math.nan}, *pools[month][1:]]
    with pytest.raises(ValueError, match=month):
        _side(side_inputs, pools=pools, expected=NO_LISTS)


def test_model_side_is_deterministic(side3, side_inputs):
    again = _side(side_inputs, expected=NO_LISTS)
    pd.testing.assert_frame_equal(again.cells, side3.cells)
    assert json.dumps(again.checks, sort_keys=True) == json.dumps(side3.checks, sort_keys=True)


# ------------------------------------------------------------- review round 1: fail closed


def test_a_kept_tie_is_paired_with_the_mix_itself():
    w = np.array(INSIDE)
    cells = [_cell(RC.E, mu=0.05, sigma=0.10, mu_gap=5e-7, l1=0.3, dr2=1.4, a=0.4, weights=w),
             _cell("F@E", mu=0.05 + 5e-7, sigma=0.10, dr2=1.1, a=0.4, risk_gap=3e-7,
                   weights=np.array([0.2, 0.5, 0.3]))]  # fmt: skip
    e, comp = _checked(cells, [{"weights": INSIDE, "sigma": 0.09, "mu": 0.049}])
    assert e["tie"] is True and e["status"] == comp["status"] == RC.KEPT
    assert np.array_equal(comp["weights"], w)  # differences 0 by construction
    assert (comp["mu"], comp["sigma"], comp["dr2"], comp["risk_gap"]) == (0.05, 0.10, 1.4, 0.0)
    assert e["l1"] == 0.3  # the distance to F(sigma(M)) stays reported


def test_a_missing_risk_or_return_leaves_the_pool_checks_undecided():
    (u,) = _checked([_cell(RC.U, rf=0.1, r=math.nan, mu=0.08, sigma=0.1)],
                    [{"weights": INSIDE, "sigma": 0.05, "mu": 0.01}])  # fmt: skip
    assert math.isnan(u["pool_mu_bound"])
    for e_values in ({"sigma": math.nan}, {"mu": math.nan, "mu_gap": 0.01}):
        cells = [_cell(RC.E, **{"mu": 0.05, "sigma": 0.10, "mu_gap": 0.0, **e_values}),
                 _cell("F@E", mu=0.05, sigma=0.10)]  # fmt: skip
        e, comp = _checked(cells, [])
        assert e["status"] == comp["status"] == RC.FAILED
        assert e["reason"] == RC.UNDECIDED


def test_an_incomplete_repeated_or_unknown_row_stops():
    months = _months(2)
    base = _model_cells(months)
    assert "structure" not in _stops(RC.gates(base, months, expected=NO_LISTS))
    for mix, rf in ((RC.F, A.RFS[2]), (RC.E, None), (RC.U, A.RFS[0]), (RC.F_ARM1, A.RFS[5])):
        dropped = A._frame(base.loc[~_at(base, months[1], mix, rf)])
        assert "structure" in _stops(RC.gates(dropped, months, expected=NO_LISTS))
    repeated = pd.concat([base, base.loc[_at(base, months[0], RC.U, A.RFS[1])]])
    assert "structure" in _stops(RC.gates(repeated, months, expected=NO_LISTS))
    repeated = pd.concat([base, base.loc[_at(base, months[0], "F@D")]])
    assert "structure" in _stops(RC.gates(repeated, months, expected=NO_LISTS))
    unknown = base.copy()
    _set(unknown, months[0], RC.D, status="maybe")
    assert "structure" in _stops(RC.gates(unknown, months, expected=NO_LISTS))
    stranger = pd.concat([base, base.loc[_at(base, months[0], RC.E)].assign(mix="V")])
    assert "structure" in _stops(RC.gates(stranger, months, expected=NO_LISTS))


def test_a_kept_or_excluded_d_without_weights_fails_check_b():
    months = _months(3)
    for status in (RC.KEPT, RC.EXCLUDED):
        cells = _model_cells(months)
        _set(cells, months[1], RC.D, status=status, dr2=0.0, pool_dr2_max=99.0)
        cells.loc[_at(cells, months[1], RC.D), "weights"] = None
        checks = RC.gates(cells, months, expected=NO_LISTS)
        assert "check (b)" in _stops(checks)
        assert [f["month"] for f in checks["check_b"][RC.D]["failed"]] == [months[1]]


@pytest.mark.parametrize(
    ("mix", "rf", "name", "value"),
    [
        ("F@E", None, "weights", None),
        (RC.U, A.RFS[4], "weights", None),
        (RC.D, None, "weights", np.zeros(0)),
        (RC.E, None, "weights", np.array([0.5, math.nan])),
        (RC.E, None, "weights", np.array(["x", "y"], dtype=object)),
        (RC.U, A.RFS[1], "mu", math.nan),
        (RC.U, A.RFS[1], "breaks_limit", None),
        (RC.U, A.RFS[2], "pool_mu_bound", math.nan),
        (RC.D10, None, "pool_dr2_max", math.nan),
        (RC.E, None, "a", math.nan),
        (RC.F, A.RFS[0], "mu", math.nan),
        (RC.F_ARM1, A.RFS[0], "weights", None),
        ("F@D", None, "risk_gap", math.nan),
    ],
)
def test_a_kept_row_with_a_missing_or_malformed_value_stops(mix, rf, name, value):
    months = _months(1)
    cells = _model_cells(months)
    cells[name] = cells[name].astype(object)
    mask = _at(cells, months[0], mix, rf)
    cells.loc[mask, name] = pd.Series([value], index=cells.index[mask], dtype=object)
    assert "structure" in _stops(RC.gates(cells, months, expected=NO_LISTS))


def test_an_excluded_d_without_its_ratio_stops():
    months = _months(1)
    cells = _exclude(_model_cells(months), months[0], RC.D)
    assert "structure" not in _stops(RC.gates(cells, months, expected=NO_LISTS))
    _set(cells, months[0], RC.D, dr2=math.nan)
    assert "structure" in _stops(RC.gates(cells, months, expected=NO_LISTS))


def test_a_mix_and_its_comparator_out_of_step_stop():
    months = _months(1)
    base = _model_cells(months)
    for mix, comp_status in ((RC.D, RC.FAILED), (RC.E, RC.EXCLUDED)):
        cells = base.copy()
        _set(cells, months[0], RC.COMPARATOR[mix], status=comp_status)
        assert "structure" in _stops(RC.gates(cells, months, expected=NO_LISTS))
    cells = base.copy()
    _set(cells, months[0], RC.E, status=RC.EXCLUDED)  # excluded, yet with a comparator row
    assert "structure" in _stops(RC.gates(cells, months, expected=NO_LISTS))
    cells = base.copy()
    _set(cells, months[0], RC.D10, status=RC.FAILED)  # failed, with a kept comparator
    assert "structure" in _stops(RC.gates(cells, months, expected=NO_LISTS))


def test_judge_writes_the_gates_statuses_into_the_cells():
    months = _months(1)
    cells = _model_cells(months)
    _set(cells, months[0], RC.U, A.RFS[0], risk_gap=math.nan)
    _set(cells, months[0], "F@D", risk_gap=2e-6)
    _set(cells, months[0], RC.F, A.RFS[3], rebuilt_mu_gap=2e-6)
    judged = _records(RC.judge(cells))
    u = _rows(judged, RC.U)
    assert [r["status"] for r in u] == [RC.FAILED, RC.KEPT, RC.KEPT, RC.FAILED, RC.KEPT, RC.KEPT]
    assert _row(judged, RC.D)["status"] == _row(judged, "F@D")["status"] == RC.FAILED
    assert _rows(judged, RC.F)[3]["status"] == RC.FAILED
    assert _row(judged, RC.E)["status"] == RC.KEPT
    assert len(judged) == len(cells)


def test_model_side_returns_the_judged_cells(side_inputs, monkeypatch):
    original = RC.month_pool_checks

    def off_line(mixes, pool, lower, upper):
        out = original(mixes, pool, lower, upper)
        if out["month"].iloc[0] == SIDE_MONTHS[1]:
            out.loc[(out["mix"] == RC.U).to_numpy() & np.isclose(out["rf"], A.RFS[0]),
                    "risk_gap"] = 3e-6  # fmt: skip
        return out

    monkeypatch.setattr(RC, "month_pool_checks", off_line)
    side = _side(side_inputs, expected=NO_LISTS)
    cells = _records(side.cells)
    u = [r for r in cells if r["mix"] == RC.U and r["month"] == SIDE_MONTHS[1]]
    assert u[0]["status"] == RC.FAILED
    assert side.checks["failed_cells"][RC.U]["failed"] == 1


def test_the_gates_read_the_cells_before_they_are_judged(side_inputs, monkeypatch):
    original = RC.month_pool_checks

    def unbuilt(mixes, pool, lower, upper):
        out = original(mixes, pool, lower, upper)
        if out["month"].iloc[0] == SIDE_MONTHS[1]:
            mask = (out["mix"] == RC.D).to_numpy()
            out.loc[mask, "weights"] = pd.Series([None], index=out.index[mask], dtype=object)
        return out

    monkeypatch.setattr(RC, "month_pool_checks", unbuilt)
    stops = _stops(_side(side_inputs, expected=NO_LISTS).checks)
    assert {"structure", "check (b)"} <= set(stops)


def test_a_tie_is_not_applied_to_a_comparator_off_its_line_or_unbuilt():
    pool = [{"weights": INSIDE, "sigma": 0.09, "mu": 0.049}]
    off_line = _pair()
    off_line[1].update(weights=np.array([0.2, 0.5, 0.3]), risk_gap=2e-6)
    e, comp = _checked(off_line, pool)
    assert e["tie"] is False
    assert np.array_equal(comp["weights"], [0.2, 0.5, 0.3]) and comp["risk_gap"] == 2e-6
    unbuilt = _pair()
    unbuilt[1].update(weights=None, risk_gap=0.0)
    e, comp = _checked(unbuilt, pool)
    assert e["tie"] is False and comp["weights"] is None


def test_a_pool_row_with_missing_weights_stops_naming_the_month():
    with pytest.raises(ValueError, match=MONTH):
        _checked([_cell(RC.D, dr2=2.0)], [{"weights": [math.nan, 0.5, 0.5]}])
