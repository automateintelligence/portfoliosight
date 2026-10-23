"""Fixed-risk search of one origin (piece 1, protocol §4): cells, arms, pooling, labels."""

from __future__ import annotations

import time
from dataclasses import replace

import numpy as np
import pytest

from portfoliosight.research.fixedrisk.agreement import (
    AgreementCase,
    AgreementRow,
    agreement_check,
    agreement_decision,
)
from portfoliosight.research.fixedrisk.anchors import geometry, origin_anchors
from portfoliosight.research.fixedrisk.banks import replay_bank
from portfoliosight.research.fixedrisk.contracts import (
    ARM_ORDER,
    GROWTH_BOUND_FAILED,
    OK,
    TAU_D,
    TAU_R,
)
from portfoliosight.research.fixedrisk.objective import figures
from portfoliosight.research.fixedrisk.optimizer import search_origin
from tests.research.fixedrisk.optimizer_data import synthetic_context

TOL = 1e-8
FRACTION = (0.40,)


@pytest.fixture(scope="module")
def ctx():
    return synthetic_context()


@pytest.fixture(scope="module")
def bank(ctx):
    return replay_bank(ctx, "replay", 20261013)


@pytest.fixture(scope="module")
def anchors(ctx):
    return origin_anchors(ctx, FRACTION)


@pytest.fixture(scope="module")
def result(ctx, bank, anchors):
    clock = time.perf_counter()
    out = search_origin(ctx, bank, anchors=anchors, risk_fractions=FRACTION)
    out.seconds = time.perf_counter() - clock
    return out


def test_end_to_end_all_cells_all_arms(result, anchors, bank, ctx):
    assert result.seconds < 30.0
    assert result.labels == {OK: 4 * len(ARM_ORDER)}
    pooled = [s for s in result.selections if s.pooled]
    native = [s for s in result.selections if not s.pooled]
    assert {(s.cell, s.arm) for s in pooled} == {
        (c, a) for c in ("d25", "d50", "d75", "free") for a in ARM_ORDER
    }
    assert {(s.cell, s.arm) for s in native} == {("free", a) for a in ARM_ORDER}
    assert [(c.arm, c.cell) for c in result.comparators] == [("F", "free"), ("BS", "free")]
    np.testing.assert_array_equal(result.comparators[0].weights, anchors[0].w_F)
    geo = geometry(ctx)
    a = anchors[0]
    span = a.M_MDP - a.M_F
    for s in result.selections + result.comparators:
        w = s.weights
        assert (w >= -TOL).all() and (w <= 0.6 + TOL).all() and abs(w.sum() - 1) <= TOL
        assert abs(s.sigma - a.r) <= TAU_R * a.r + TOL
        assert s.sigma == pytest.approx(geo.risk(w))
        single = figures(bank.years(w)[:, 0])  # gemv vs the batch's gemm: ~1e-17 apart
        for name in ("bad", "typical", "good", "mean", "es_25"):
            assert getattr(s.figures, name) == pytest.approx(getattr(single, name), abs=1e-12)
        assert s.d == pytest.approx((s.measure - a.M_F) / span)
        if s.cell.startswith("d") and s.arm not in ("F", "BS"):
            d = int(s.cell[1:]) / 100
            assert abs(s.measure - (a.M_F + d * span)) <= TAU_D * span + TOL
        assert s.engine == "replay" and s.seed == 20261013 and s.solver == "exact_grad"
    assert result.evaluations > 0


def test_free_cell_pool_dominates_interior_winners(result):
    for arm in ARM_ORDER:
        free = next(s for s in result.selections if s.cell == "free" and s.pooled and s.arm == arm)
        native = next(
            s for s in result.selections if s.cell == "free" and not s.pooled and s.arm == arm
        )
        value = free.figures.utility(arm)
        assert value >= native.figures.utility(arm)
        for s in result.selections:
            if s.cell != "free" and s.pooled:
                assert value >= s.figures.utility(arm) - 1e-15


def test_pooled_beats_or_matches_comparator_frontier(result):
    """w_F is a free-cell start, so the free pool's U is at least w_F's."""
    w_f = result.comparators[0]
    for arm in ARM_ORDER:
        free = next(s for s in result.selections if s.cell == "free" and s.pooled and s.arm == arm)
        assert free.figures.utility(arm) >= w_f.figures.utility(arm)


def test_deterministic(ctx, bank, anchors, result):
    again = search_origin(ctx, bank, anchors=anchors, risk_fractions=FRACTION)
    for a, b in zip(result.selections, again.selections, strict=True):
        np.testing.assert_array_equal(a.weights, b.weights)
        assert a.figures == b.figures and a.iterations == b.iterations
    assert result.labels == again.labels and result.evaluations == again.evaluations


def test_native_only_runs_u1_without_pooling(ctx, bank, anchors):
    out = search_origin(ctx, bank, anchors=anchors, risk_fractions=FRACTION, native_only=True)
    assert {s.arm for s in out.selections} == {"U1"}
    assert not any(s.pooled for s in out.selections)
    assert [s.cell for s in out.selections] == ["d25", "d50", "d75", "free"]
    assert out.comparators == []


def test_d_grid_override_and_endpoint_bands(ctx, bank, anchors):
    out = search_origin(
        ctx,
        bank,
        anchors=anchors,
        arms=("U1",),
        risk_fractions=FRACTION,
        d_grid=(0.0, 1.0),
        include_free=False,
    )
    cells = [s.cell for s in out.selections]
    assert cells == ["d00", "d100"]
    a = anchors[0]
    d0 = out.selections[0]
    # the d = 0 band holds w_F (a start), so its max-U mix is at least as good as the anchor
    assert d0.figures.utility("U1") >= out.comparators[0].figures.utility("U1")
    assert abs(d0.measure - a.M_F) <= TAU_D * (a.M_MDP - a.M_F) + TOL


@pytest.mark.parametrize("solver", ["kernel_grad", "cobyla128"])
def test_other_solvers(ctx, bank, anchors, solver):
    out = search_origin(
        ctx,
        bank,
        anchors=anchors,
        arms=("U1", "B"),
        risk_fractions=FRACTION,
        d_grid=(0.5,),
        solver=solver,
    )
    assert out.labels == {OK: 4}
    assert all(s.solver == solver for s in out.selections)


def test_growth_bound_failed_bank_uses_cobyla(ctx):
    sample = np.array(ctx.sample)
    sample[10, 0] = -1.5
    broken_ctx = replace(ctx, sample=sample, inputs_sha256="broken")
    bank = replay_bank(broken_ctx, "replay", 20261013)
    assert not bank.growth_bound_ok
    out = search_origin(
        broken_ctx, bank, arms=("U1",), risk_fractions=FRACTION, d_grid=(), native_only=True
    )
    assert out.labels == {GROWTH_BOUND_FAILED: 1}
    (sel,) = out.selections
    assert sel.status == GROWTH_BOUND_FAILED and sel.solver == "cobyla768"
    assert np.isfinite(sel.figures.bad)


def test_agreement_rule():
    def rows(values: dict[str, list[float]]) -> list[AgreementRow]:
        out = []
        for solver, vals in values.items():
            for k, v in enumerate(vals):
                out.append(
                    AgreementRow(
                        k // 2,
                        "m",
                        0.4,
                        "d50",
                        ("U1", "B")[k % 2],
                        solver,
                        v,
                        1.0 if solver == "exact_grad" else 2.0,
                    )
                )
        return out

    ref = [0.01] * 60
    worse = [0.01 - 0.0003] * 3 + [0.01] * 57  # 57 of 60 within 2.5 bp: passes
    worst = [0.01 - 0.0003] * 4 + [0.01] * 56  # 56 of 60: fails
    report = agreement_decision(
        rows({"exact_grad": worse, "kernel_grad": worst, "cobyla768": ref, "cobyla128": worst})
    )
    assert report.pairs == 60 and report.needed == 57
    assert report.accepted == {"exact_grad": True, "kernel_grad": False, "cobyla128": False}
    assert report.chosen == "exact_grad"
    report = agreement_decision(
        rows({"exact_grad": worst, "kernel_grad": worst, "cobyla768": ref, "cobyla128": ref})
    )
    assert report.chosen == "cobyla128"
    report = agreement_decision(
        rows({"exact_grad": worst, "kernel_grad": worst, "cobyla768": ref, "cobyla128": worst})
    )
    assert report.chosen == "cobyla768"


def test_agreement_check_runs_four_solvers(ctx, bank, anchors):
    report = agreement_check([AgreementCase(ctx, bank, FRACTION[0], "d25", anchors[0])])
    assert report.pairs == 2 and len(report.rows) == 8
    assert {r.solver for r in report.rows} == {
        "exact_grad",
        "kernel_grad",
        "cobyla768",
        "cobyla128",
    }
    assert all(np.isfinite(r.value) for r in report.rows)
    assert report.chosen in ("exact_grad", "kernel_grad", "cobyla128", "cobyla768")
