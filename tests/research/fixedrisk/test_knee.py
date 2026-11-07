"""Arm 6: the app's ENB knee at the experiment risks, by the app's own functions."""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from portfoliosight.engine import ladder as L
from portfoliosight.engine.optimize import MenuPrograms, frontier
from portfoliosight.engine.suggest import balanced_level
from portfoliosight.engine.surface import surface
from portfoliosight.engine.torsion import torsion_basis
from portfoliosight.research.fixedrisk import contracts as C
from portfoliosight.research.fixedrisk import knee
from portfoliosight.research.fixedrisk.anchors import geometry

from .optimizer_data import synthetic_context

NX = 12  # a smaller app grid keeps the tests quick; the code path is the app's


def _app(ctx):
    lo, hi = np.asarray(ctx.menu.lower), np.asarray(ctx.menu.upper)
    programs = MenuPrograms(ctx.mu_s, ctx.cov, lo, hi)
    front = frontier(programs, NX, 1)
    program = L.EnbProgram(ctx.mu_s, ctx.cov, lo, hi, torsion_basis(ctx.cov))
    return programs, front, program, surface(program, programs, front, L.LEVELS, 1)


@pytest.fixture(scope="module")
def ctx():
    return synthetic_context(funds=5, rows=400, cap=0.6, seed=7)


@pytest.fixture(scope="module")
def result(ctx):
    geo = geometry(ctx)
    risks = {a: geo.x(a) for a in (0.10, 0.55)}
    return knee.knee_columns(ctx, risks, nx=NX)


def test_app_columns_are_untouched(ctx, result):
    _, _, _, surf = _app(ctx)
    np.testing.assert_array_equal(result.surface.w, surf.w)
    np.testing.assert_array_equal(result.surface.z, surf.z)


def test_knee_is_balanced_level_of_the_side_ladder(ctx, result):
    cov = np.asarray(ctx.cov)
    for col in result.columns:
        assert col.status in (C.OK, C.KNEE_COLLAPSED)
        assert col.level == balanced_level(col.ladder_y, col.ladder_z)
        np.testing.assert_array_equal(col.w_knee, col.ladder_w[col.level])
        assert len(col.ladder_y) == L.LEVELS + 2
        assert (np.diff(col.ladder_y) <= 1e-12).all() and (np.diff(col.ladder_z) >= -1e-12).all()
        # every rung sits on the exact risk line, inside the bounds, fully invested
        for w in col.ladder_w:
            assert abs(np.sqrt(w @ cov @ w) - col.r) <= 1e-8
        assert col.line_error <= 1e-6
        assert any(np.array_equal(m, col.w_knee) for m in col.members)


def test_side_frontier_node_matches_the_app_frontier_on_an_app_column(ctx):
    programs, front, _, _ = _app(ctx)
    for j in (3, 7):
        node = knee.side_frontier_node(programs, front, float(front.x[j]))
        np.testing.assert_allclose(node, front.w[j], atol=1e-7)


def test_knee_is_deterministic(ctx, result):
    geo = geometry(ctx)
    again = knee.knee_columns(ctx, {a: geo.x(a) for a in (0.10, 0.55)}, nx=NX)
    for one, two in zip(result.columns, again.columns, strict=True):
        np.testing.assert_array_equal(one.w_knee, two.w_knee)


def test_ladder_gaining_enb_for_no_return_answers_the_peak():
    # equal expected returns: diversification is free, so the knee is the peak (suggest.py:48)
    base = synthetic_context(funds=4, rows=400, cap=0.7, seed=3)
    flat = replace(base, mu_s=np.full(4, 0.06), inputs_sha256=base.inputs_sha256 + "flat")
    lo, hi = np.asarray(flat.menu.lower), np.asarray(flat.menu.upper)
    programs = MenuPrograms(flat.mu_s, flat.cov, lo, hi)
    front = frontier(programs, NX, 1)
    r = float(front.x[0] + 0.4 * (front.x[-1] - front.x[0]))
    out = knee.knee_columns(flat, {0.4: r}, nx=NX)
    col = out.columns[0]
    assert col.status == C.OK, (out.error, col.line_error)
    assert col.level == len(col.ladder_y) - 1
    assert col.ladder_z[-1] > col.ladder_z[0]
