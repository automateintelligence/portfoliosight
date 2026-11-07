"""The v3 column search: pool rows for every evaluation, selections, bands, arm 5's re-rank."""

from __future__ import annotations

import math

import numpy as np
import pyarrow.parquet as pq
import pytest

from portfoliosight.research.fixedrisk import contracts as C
from portfoliosight.research.fixedrisk import search3 as S
from portfoliosight.research.fixedrisk.anchors import geometry
from portfoliosight.research.fixedrisk.banks import replay_bank
from portfoliosight.research.fixedrisk.knee import knee_columns
from portfoliosight.research.fixedrisk.objectives3 import FIELDS, INDEX
from portfoliosight.research.fixedrisk.pool import pool_schema, read_weights, write_pool

from .optimizer_data import synthetic_context, with_history

CALLS = 24
RF = (0.25, 0.70)


@pytest.fixture(scope="module")
def setup():
    ctx = with_history(synthetic_context(funds=5, rows=400, cap=0.6, seed=7))
    bank = replay_bank(ctx, "replay", 13)
    geo = geometry(ctx)
    knee = knee_columns(ctx, {a: geo.x(a) for a in (*RF, 0.4)}, nx=12)  # a small app grid
    return ctx, bank, knee


@pytest.fixture(scope="module")
def result(setup):
    ctx, bank, knee = setup
    return S.search_origin_v3(ctx, bank, risk_fractions=RF, calls=CALLS, knee=knee)


@pytest.fixture(scope="module")
def with_side(setup, result):
    ctx, bank, knee = setup
    return S.search_origin_v3(
        ctx, bank, risk_fractions=RF, calls=CALLS, side_lambdas=C.LAMBDA_SIDE, knee=knee
    )


def _value(res, rid, name):
    return float(res.pool.values[rid][INDEX[name]])


def test_every_evaluation_is_one_pool_row(result):
    assert len(result.pool) == result.eval_calls
    sources = set(result.pool.source)
    assert sources == {"search", "sobol", "anchor", "knee_ladder"}
    for arm in C.V3_SEARCHED:
        for a in RF:
            rows = [
                i
                for i in range(len(result.pool))
                if result.pool.arm[i] == arm
                and result.pool.r_fraction[i] == a
                and result.pool.source[i] == "search"
            ]
            sel = next(
                s
                for s in result.selections
                if s["arm"] == arm and s["r_fraction"] == a and s["pooled"]
            )
            # every solver call plus one end point per start
            assert len(rows) == sel["calls"] + sel["starts"]
            starts = {result.pool.start[i] for i in rows}
            assert starts == set(range(sel["starts"]))


def test_scheduled_selection_rows(result):
    per_column = {}
    for s in result.selections:
        per_column.setdefault(s["r_fraction"], []).append((s["arm"], s["pooled"]))
    want = sorted(
        [(C.FRONTIER, False), (C.MAX_ENLC, True), (C.ENB_KNEE, False), (C.APP_FRONTIER, False)]
        + [(arm, p) for arm in C.V3_SEARCHED for p in (True, False)]
    )
    for a in RF:
        assert sorted(per_column[a]) == want


def _column_rows(res, a, main_only=True):
    return [
        i for i in range(len(res.pool))
        if res.pool.r_fraction[i] == a and (not main_only or res.pool.lam[i] in (None, C.LAMBDA))
    ]  # fmt: skip


def test_pooled_selections_are_the_best_in_band_member(result):
    for s in result.selections:
        if not s["pooled"] or s["arm"] not in C.V3_SEARCHED:
            continue
        a, arm = s["r_fraction"], s["arm"]
        band = "in_narrow" if arm == C.MIN_TDD else "in_wide"
        rows = [i for i in _column_rows(result, a) if _value(result, i, band) == 1.0]

        def obj(i, arm=arm):
            if arm == C.U1_ARM:
                return _value(result, i, "u1")
            if arm == C.MIN_TDD:
                return -_value(result, i, "tdd")
            return _value(result, i, "u1") - C.LAMBDA * _value(result, i, "h")

        assert s["status"] == C.OK
        assert obj(s["pool_row"]) == max(obj(i) for i in rows)
        assert _value(result, s["pool_row"], band) == 1.0


def test_bands_per_arm(result, setup):
    ctx, _, _ = setup
    for s in result.selections:
        if s["weights"] is None:
            continue
        sigma = math.sqrt(s["weights"] @ ctx.cov @ s["weights"])
        if s["arm"] in (C.FRONTIER, C.MIN_TDD):
            assert abs(sigma - s["r"]) <= C.TAU_NARROW * s["r"] + 1e-8
        elif s["arm"] in (C.ENB_KNEE, C.APP_FRONTIER):
            assert abs(sigma - s["r"]) <= 1e-6
        else:
            assert abs(sigma - s["r"]) <= C.TAU_WIDE * s["r"] + 1e-8


def test_arm5_is_the_eligible_max_enlc(result):
    for a in RF:
        f = next(s for s in result.selections if s["arm"] == C.FRONTIER and s["r_fraction"] == a)
        mu_f = _value(result, f["pool_row"], "mu")
        s5 = next(s for s in result.selections if s["arm"] == C.MAX_ENLC and s["r_fraction"] == a)
        eligible = [
            i for i in _column_rows(result, a)
            if _value(result, i, "in_wide") == 1.0
            and math.isfinite(_value(result, i, "enlc"))
            and _value(result, i, "mu") >= mu_f - C.ENLC_RETURN_TOL
        ]  # fmt: skip
        assert s5["status"] == C.OK
        best = max(_value(result, i, "enlc") for i in eligible)
        assert _value(result, s5["pool_row"], "enlc") == best
        assert _value(result, s5["pool_row"], "mu") >= mu_f - C.ENLC_RETURN_TOL


def test_side_checks_do_not_change_the_main_selections(result, with_side):
    def main(res):
        return [
            (s["r_fraction"], s["arm"], s["pooled"], tuple(s["weights"]))
            for s in res.selections
            if s["lam"] in (None, C.LAMBDA) and s["weights"] is not None
        ]

    assert main(result) == main(with_side)
    lams = {s["lam"] for s in with_side.selections if s["arm"] == C.CRASH_PENALTY}
    assert lams == {C.LAMBDA, *C.LAMBDA_SIDE}


def test_pool_table_round_trip(result, setup, tmp_path):
    ctx, bank, knee = setup
    table = result.pool.table(
        menu=ctx.menu.name, month=ctx.month, origin=ctx.origin, engine="replay", seed=bank.seed
    )
    assert table.schema.equals(pool_schema(5))
    assert table.num_rows == len(result.pool)
    assert {f for f in FIELDS} <= set(table.column_names)
    path = tmp_path / "pool.parquet"
    size = write_pool(path, table, {b"parent_digest": b"x"})
    assert size == path.stat().st_size > 0
    back = pq.read_table(path)
    assert back.schema.metadata[b"parent_digest"] == b"x"
    keys = list(zip(
        back.column("r_fraction").to_pylist(), back.column("arm").to_pylist(),
        back.column("start").to_pylist(), back.column("call").to_pylist(), strict=True,
    ))  # fmt: skip
    assert keys == sorted(keys)
    w = read_weights(back)
    record = back.column("record").to_numpy()
    np.testing.assert_array_equal(w, np.vstack(result.pool.weights)[record])
    tdd = back.column("tdd").to_numpy()
    np.testing.assert_array_equal(tdd, np.vstack(result.pool.values)[record, INDEX["tdd"]])


def test_garch_arm_set_runs_arms_one_to_four(setup):
    ctx, bank, knee = setup
    res = S.search_origin_v3(
        ctx, bank, arms=C.V3_GARCH_ARMS, risk_fractions=(0.4,), calls=12, knee=knee
    )
    assert {s["arm"] for s in res.selections} == set(C.V3_GARCH_ARMS)
