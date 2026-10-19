"""The statistics and report writer (protocol 6, 7 and 9; plan 6b.6).

Two kinds of tests. Constructed cases (small hand-built outcome tables and evidence records) give
hand-calculated oracles for the bootstrap blocks, the aggregation order, the pinball identity,
every protocol 7 label on both sides of its threshold, the Stage 2 decision and a menu that fails
while the 50/50 aggregate looks favorable. A tiny synthetic run (the runner's shared fixtures in
tests/research/fixtures.py: Stage 1 and the three sensitivities) gives real artifacts for the
reading, verification, summary and CLI tests. Oracles are written here: explicit block assembly
from NumPy's seeded generator, sorted-interpolation percentiles, hand means and medians, and the
max-form pinball identity; the code under test never computes its own expectation.
"""

from __future__ import annotations

import hashlib
import json
import math
import shutil
from dataclasses import replace
from pathlib import Path
from types import ModuleType
from typing import Any

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from portfoliosight.research import evidence, experiment, outcomes, report, search
from portfoliosight.research.evidence import (
    BP,
    BankReplay,
    Bootstrap,
    Cost,
    Estimate,
    Grid,
    MenuEvidence,
    RealizedCell,
    RealizedEvidence,
    Replay,
    Stability,
    Validity,
)
from portfoliosight.research.experiment import Limits
from tests.research.fixtures import (
    ROOT,
    load_module,
    make_records,
    make_settings,
    run_experiment,
)

P, S = 20261013, 20261014
CELLS = ("x25", "x50", "x100")
RD = ("R+D", 0.00025)
R = ("R", None)


# ----------------------------------------------------------------------------- bootstrap blocks


def test_block_index_wraps_blocks_around_the_origin_index() -> None:
    """Hand oracle: n = 5, block 2, three blocks per resample, cut to five positions."""
    starts = np.array([[3, 0, 4], [4, 4, 1]])
    assert evidence.block_index(starts, 5, 2).tolist() == [[3, 4, 0, 1, 4], [4, 0, 4, 0, 1]]
    # n = 7, block 3: (5, 6, 0), (1, 2, 3), (6, 0, 1) -> the first seven
    assert evidence.block_index(np.array([[5, 1, 6]]), 7, 3).tolist() == [[5, 6, 0, 1, 2, 3, 6]]
    # a block longer than the index wraps more than once
    assert evidence.block_index(np.array([[2]]), 3, 24).tolist() == [[2, 0, 1]]


def test_resample_index_draws_block_starts_from_the_seeded_generator() -> None:
    n, block = 50, 24
    index = evidence.resample_index(n, block)
    assert index.shape == (2000, 50)
    blocks = math.ceil(n / block)
    starts = np.random.default_rng(20261201).integers(0, n, size=(2000, blocks))
    for r in (0, 1, 999, 1999):
        hand: list[int] = []
        for s in starts[r].tolist():
            hand += [(s + j) % n for j in range(block)]
        assert index[r].tolist() == hand[:n]
    assert evidence.BOOTSTRAP_SEED == 20261201 and evidence.RESAMPLES == 2000
    assert evidence.BLOCKS == (24, 12, 36)


def _sorted_percentile(values: list[float], p: float) -> float:
    ordered = sorted(values)
    position = p / 100 * (len(ordered) - 1)
    low = int(math.floor(position))
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (position - low) * (ordered[high] - ordered[low])


def test_quantiles_interpolate_over_each_resamples_available_origins() -> None:
    x = np.array([0.03, np.nan, -0.01, 0.10, 0.02])
    index = np.array([[0, 1, 2, 3, 4], [1, 1, 3, 3, 0], [1, 1, 1, 1, 1]])
    for q in (0.025, 0.5, 0.975):
        found = evidence.quantile(x, q, index)
        assert found[0] == pytest.approx(_sorted_percentile([0.03, -0.01, 0.10, 0.02], 100 * q))
        assert found[1] == pytest.approx(_sorted_percentile([0.10, 0.10, 0.03], 100 * q))
        assert math.isnan(found[2])  # no available origin: undefined, never filled


def test_identical_blocks_pair_every_arm_and_menu_and_intervals_are_percentiles() -> None:
    """One index matrix serves every series: a paired mean resamples as a difference of means."""
    rng = np.random.default_rng(5)
    a, b = rng.normal(size=30), rng.normal(size=30)
    b[[3, 17]] = np.nan  # missing outcomes stay on the index, masked in both arms
    a_paired = np.where(np.isfinite(b), a, np.nan)
    boot = Bootstrap(30)
    index = boot.indices[24]
    difference = evidence.cell_mean(a - b, index)
    assert np.allclose(
        difference, evidence.cell_mean(a_paired, index) - evidence.cell_mean(b, index)
    )
    estimate = boot.estimate(lambda i: evidence.cell_mean(a - b, i), 0.95, 28)
    hand = []
    for row in index.tolist():
        values = [a[t] - b[t] for t in row if math.isfinite(b[t])]
        hand.append(sum(values) / len(values))
    low, high = estimate.intervals[24]
    assert low == pytest.approx(_sorted_percentile(hand, 2.5), abs=1e-12)
    assert high == pytest.approx(_sorted_percentile(hand, 97.5), abs=1e-12)
    assert estimate.value == pytest.approx(float(np.nanmean(a - b)), abs=1e-12)
    assert set(estimate.intervals) == {24, 12, 36} and estimate.level == 0.95
    wide = boot.estimate(lambda i: evidence.cell_mean(a - b, i), 0.99, 28)
    assert wide.intervals[24][0] == pytest.approx(_sorted_percentile(hand, 0.5), abs=1e-12)


# ---------------------------------------------------------------------------- outcome tables

_COLUMNS = (
    "profile",
    "menu",
    "month",
    "ceiling_id",
    "stands_for",
    "seed",
    "role",
    "allowance",
    "weights",
    "risk",
    "dr2",
    "guards",
    "sacrifice",
    "coefficients",
    "train_bad",
    "train_typical",
    "train_good",
    "train_utility",
    "train_es_25",
    "test_bad",
    "test_typical",
    "test_good",
    "test_utility",
    "test_es_25",
    "bank_bad",
    "bank_typical",
    "bank_good",
    "bank_utility",
    "bank_es_25",
    "annual_return",
    "max_drawdown",
    "loss",
    "below_20",
    "worst_day",
    "volatility",
    "forecast_error",
    "turnover_prev",
)


def _row(menu: str, month: str, ceiling: str, arm: tuple[str, float | None], **values: Any):
    row: dict[str, Any] = dict.fromkeys(_COLUMNS)
    row.update(
        profile="stage-1",
        menu=menu,
        month=month,
        ceiling_id=ceiling,
        stands_for=[ceiling],
        seed=P,
        role=arm[0],
        allowance=arm[1],
        coefficients=[0.6, 0.3, 0.1],
    )
    row.update(values)
    return row


def _table(rows: list[dict[str, Any]]) -> pa.Table:
    return pa.Table.from_pylist(rows)


def _pair(menu: str, month: str, ceiling: str, du: float, **more: Any) -> list[dict[str, Any]]:
    """An R row and an R+D row whose pooled-test U differ by ``du`` bp (other figures equal)."""
    base = {"test_utility": 0.05, "test_bad": -0.02, "test_typical": 0.06, "test_good": 0.15}
    banks = {f"bank_{k.removeprefix('test_')}": [v] * 5 for k, v in base.items()}
    up = {**base, "test_utility": 0.05 + du * BP}
    up_banks = {**banks, "bank_utility": [0.05 + du * BP] * 5}
    return [
        _row(menu, month, ceiling, R, **base, **banks, **more),
        _row(menu, month, ceiling, RD, **up, **up_banks, **more),
    ]


def _aggregation_rows() -> list[dict[str, Any]]:
    """TSP: m1 cells +6/+3/0 bp; m2 collapsed (x100 stands for all three) +9; m3 x25 -3, x50
    failed (no rows), x100 +1. Example: m1 -1 everywhere, m2 -4, m3 every cell failed."""
    rows = []
    for ceiling, du in zip(CELLS, (6.0, 3.0, 0.0), strict=True):
        rows += _pair("tsp", "2020-01", ceiling, du)
    rows += _pair("tsp", "2020-02", "x100", 9.0, stands_for=list(CELLS))
    rows += _pair("tsp", "2020-03", "x25", -3.0) + _pair("tsp", "2020-03", "x100", 1.0)
    for ceiling in CELLS:
        rows += _pair("example", "2020-01", ceiling, -1.0) + _pair(
            "example", "2020-02", ceiling, -4.0
        )
    return rows


MONTHS = ("2020-01", "2020-02", "2020-03")


def test_risk_cells_are_averaged_within_each_origin_before_origins_and_menus_split_50_50() -> None:
    grid = Grid(_table(_aggregation_rows()), MONTHS, profile="stage-1")
    tsp = evidence.replay_contrast(grid, "tsp", RD, R, P)
    # origins: (6 + 3 + 0) / 3 = 3, 9 (alias weights), (-3 + 1) / 2 = -1 -> mean 11/3 bp
    assert tsp.u == pytest.approx(11 / 3 * BP, abs=1e-15)
    # per risk cell across origins: x25 (6 + 9 - 3) / 3, x50 (3 + 9) / 2, x100 (0 + 9 + 1) / 3
    assert tsp.cells_u == pytest.approx({"x25": 4 * BP, "x50": 6 * BP, "x100": 10 / 3 * BP})
    example = evidence.replay_contrast(grid, "example", RD, R, P)
    assert example.u == pytest.approx(-2.5 * BP, abs=1e-15)
    boot = Bootstrap(len(MONTHS))
    table = evidence.paired_estimates(grid, ("tsp", "example"), RD, R, "test_utility", P, boot)
    # menus 50/50: (11/3 - 2.5) / 2 bp, not the concatenated origin mean (3 + 9 - 1 - 1 - 4) / 5
    assert table["aggregate"].value == pytest.approx((11 / 3 - 2.5) / 2 * BP, abs=1e-15)
    assert table["aggregate"].value != pytest.approx(1.2 * BP, abs=1e-12)
    assert table["by_menu"]["tsp"].value == pytest.approx(11 / 3 * BP, abs=1e-15)
    assert table["by_menu"]["example"].n == 2
    assert table["by_cell"]["tsp"]["x50"].value == pytest.approx(6 * BP, abs=1e-15)
    assert table["by_cell"]["tsp"]["x50"].n == 2


def _realized_rows(r_returns, rd_returns, *, menu="tsp", ceiling="x100", stands=None):
    rows = []
    for month, y_r, y_rd in zip(MONTHS, r_returns, rd_returns, strict=True):
        for arm, y in ((R, y_r), (RD, y_rd)):
            values = {}
            if y is not None:
                values = {
                    "annual_return": y,
                    "max_drawdown": max(0.0, -y) + 0.05,
                    "loss": y < 0,
                    "below_20": y < -0.2,
                    "worst_day": -0.01,
                    "volatility": 0.1,
                    "forecast_error": y - 0.04,
                }
            rows.append(_row(menu, month, ceiling, arm, stands_for=stands or [ceiling], **values))
    return rows


def test_nonlinear_realized_metrics_take_quantiles_within_a_cell_before_contrasting() -> None:
    """Median loss is median(R) - median(R+D) across origins, not minus the median difference."""
    rows = _realized_rows([0.10, 0.00, -0.05], [0.00, 0.06, -0.06], stands=list(CELLS))
    rows += _realized_rows(
        [0.02, 0.02, 0.02], [0.02, 0.02, 0.02], menu="example", stands=list(CELLS)
    )
    grid = Grid(_table(rows), MONTHS, profile="stage-1")
    found = evidence.realized(grid, "tsp", RD, R, P, Bootstrap(3), disjoint=3)
    for cell in CELLS:
        one = found.cells[cell]
        assert one.median_loss == pytest.approx(0.0, abs=1e-15)  # medians 0.00 and 0.00
        # paired differences -0.10, +0.06, -0.01: minus their median would be 0.01
        assert one.mean_loss == pytest.approx(-(-0.10 + 0.06 - 0.01) / 3, abs=1e-15)
        assert one.loss_increase == pytest.approx(1 / 3 - 1 / 3, abs=1e-15)
    assert found.gain.value == pytest.approx((-0.10 + 0.06 - 0.01) / 3, abs=1e-15)
    assert found.gain.level == 0.99 and found.drawdown_improvement.level == 0.99


def test_the_realized_mask_is_the_intersection_of_both_menus() -> None:
    """Example's horizon is missing at m2: TSP's realized statistics drop m2 too (ruling 6)."""
    rows = _realized_rows([0.01, 0.50, 0.03], [0.02, 0.10, 0.05])
    rows += _realized_rows([0.01, None, 0.01], [0.01, None, 0.01], menu="example")
    complete = {"tsp": [True, True, True], "example": [True, False, True]}
    mask = evidence.intersection_mask(complete, ("tsp", "example"))
    assert mask.tolist() == [True, False, True]
    grid = Grid(_table(rows), MONTHS, profile="stage-1", realized_mask=mask)
    found = evidence.realized(grid, "tsp", RD, R, P, Bootstrap(3), disjoint=2)
    assert found.gain.value == pytest.approx(((0.02 - 0.01) + (0.05 - 0.03)) / 2, abs=1e-15)
    assert found.gain.n == 2


# ------------------------------------------------------------------------------- calibration


def test_calibration_scores_coverage_and_the_pinball_identity() -> None:
    """Pinball (q - 1[y < f])(y - f) equals max(q (y - f), (q - 1)(y - f)); coverage 1[y <= f]."""
    ys = [0.05, -0.10, 0.20]
    forecasts = {"bad": [-0.02, -0.05, 0.20], "typical": [0.06, 0.04, 0.10]}
    forecasts["good"] = [0.18, 0.15, 0.30]
    rows = []
    for t, month in enumerate(MONTHS):
        rows.append(
            _row(
                "tsp",
                month,
                "x100",
                R,
                stands_for=list(CELLS),
                annual_return=ys[t],
                **{f"test_{k}": v[t] for k, v in forecasts.items()},
            )
        )
    grid = Grid(_table(rows), MONTHS, profile="stage-1")
    found = evidence.calibration(grid, "tsp", R, P, "test")
    for name, q in (("bad", 0.025), ("typical", 0.5), ("good", 0.975)):
        f = forecasts[name]
        pinball = [max(q * (y - x), (q - 1) * (y - x)) for y, x in zip(ys, f, strict=True)]
        cover = [y <= x for y, x in zip(ys, f, strict=True)]
        assert found[name]["menu"]["pinball"] == pytest.approx(sum(pinball) / 3, abs=1e-15)
        assert found[name]["menu"]["coverage"] == pytest.approx(sum(cover) / 3, abs=1e-15)
        assert found[name]["nominal"] == q
        assert found[name]["cells"]["x25"]["n"] == 3


# ----------------------------------------------------------------------------- stability


def test_stability_pools_seed_pairs_and_turnover_per_risk_cell() -> None:
    """Three seeds at two origins in x100 (stands for all): 3 pairs per origin, 6 pooled."""
    w = {
        ("2020-01", P): [0.6, 0.4, 0.0],
        ("2020-01", S): [0.5, 0.5, 0.0],
        ("2020-01", 3): [0.6, 0.2, 0.2],
        ("2020-02", P): [0.2, 0.4, 0.4],
        ("2020-02", S): [0.2, 0.4, 0.4],
        ("2020-02", 3): [0.0, 0.6, 0.4],
    }
    bad = {("2020-01", P): -0.02, ("2020-01", S): -0.03, ("2020-01", 3): -0.025}
    bad |= {("2020-02", P): -0.01, ("2020-02", S): -0.01, ("2020-02", 3): -0.04}
    turnover = {("2020-01", P): None, ("2020-02", P): 0.4, ("2020-02", S): 0.3}
    turnover |= {("2020-01", S): None, ("2020-01", 3): None, ("2020-02", 3): 0.5}
    rows = [
        _row(
            "tsp",
            month,
            "x100",
            RD,
            seed=seed,
            stands_for=list(CELLS),
            weights=weights,
            test_bad=bad[(month, seed)],
            risk=0.1,
            turnover_prev=[turnover[(month, seed)]] * 3,
            bank_bad=[-0.02, -0.021, -0.019, -0.02, -0.02],
        )
        for (month, seed), weights in w.items()
    ]
    grid = Grid(_table(rows), ("2020-01", "2020-02"), profile="stage-1")
    found = evidence.stability(grid, "tsp", RD, P)
    pairs = [0.2, 0.4, 0.6, 0.0, 0.4, 0.4]  # m1: P-S, P-3, S-3; m2: P-S, P-3, S-3
    median = _sorted_percentile(pairs, 50)
    p90 = _sorted_percentile(pairs, 90)
    for cell in CELLS:
        assert found.median_l1[cell] == pytest.approx(median, abs=1e-12)
        assert found.p90_l1[cell] == pytest.approx(p90, abs=1e-12)
        assert found.turnover_median[cell] == pytest.approx(0.4, abs=1e-15)
    sd1 = float(np.std([-0.02, -0.03, -0.025], ddof=1))  # 0.005 <= 0.1 * 0.1
    sd2 = float(np.std([-0.01, -0.01, -0.04], ddof=1))  # 0.0173 > 0.01
    assert sd1 <= 0.01 < sd2
    assert found.bad_sd_share["x25"] == pytest.approx(0.5, abs=1e-15)


# ------------------------------------------------------------------- decisions, constructed


def _bank(
    u: float = 6 * BP,
    *,
    bad: float = 0.0,
    typical: float = 0.0,
    good: float = 0.0,
    cells_u: dict[str, float | None] | None = None,
) -> BankReplay:
    cells: dict[str, float | None] = {cell: u for cell in CELLS}
    cells = cells_u if cells_u is not None else cells
    return BankReplay(u=u, bad=bad, typical=typical, good=good, cells_u=cells)


def _replay(
    u: float = 6 * BP,
    *,
    banks: list[BankReplay] | None = None,
    bad: float = 0.0,
    typical: float = 0.0,
    good: float = 0.0,
    cells_u: dict[str, float | None] | None = None,
) -> Replay:
    cells: dict[str, float | None] = {cell: u for cell in CELLS}
    cells = cells_u if cells_u is not None else cells
    return Replay(
        u=u,
        bad=bad,
        typical=typical,
        good=good,
        cells_u=cells,
        banks=tuple(banks if banks is not None else [_bank(u)] * 5),
    )


def _stable(median: float, p90: float, share: float = 1.0, turnover: float = 0.1) -> Stability:
    return Stability(
        median_l1=dict.fromkeys(CELLS, median),
        p90_l1=dict.fromkeys(CELLS, p90),
        bad_sd_share=dict.fromkeys(CELLS, share),
        turnover_median=dict.fromkeys(CELLS, turnover),
    )


def _estimate(value: float, low: float, level: float = 0.99) -> Estimate:
    return Estimate(
        value=value, n=30, level=level, intervals={24: (low, value + 1.0)}, undefined={}
    )


def _realized(**changes: Any) -> RealizedEvidence:
    cell = RealizedCell(median_loss=0.0, mean_loss=0.0, loss_increase=0.0, drawdown_worsening=0.0)
    base = RealizedEvidence(
        gain=_estimate(30 * BP, 1 * BP),
        drawdown_improvement=_estimate(0.0, -0.01),
        mean_loss=-30 * BP,
        cells=dict.fromkeys(CELLS, cell),
        disjoint=25,
    )
    return replace(base, **changes)


def _menu(name: str = "tsp", **changes: Any) -> MenuEvidence:
    base = MenuEvidence(
        menu=name,
        replay=_replay(),
        stability={"R": _stable(0.30, 0.50), "R+D": _stable(0.10, 0.20, turnover=0.12)},
        dr2_gain=0.5,
        changed_share=0.5,
        cost=Cost(r_wall_p95=5.0, ratio_p95=1.1, cells=10),
        realized=_realized(),
    )
    return replace(base, **changes)


VALID = Validity(valid=True, reasons=())


def _settings(replay: Replay | None = None) -> dict[str, Replay | None]:
    return {name: replay or _replay() for name in evidence.SENSITIVITY_SETTINGS}


def _decide(tsp: MenuEvidence | None = None, example: MenuEvidence | None = None, **kw: Any):
    menus = {"tsp": tsp or _menu("tsp"), "example": example or _menu("example")}
    validity = kw.pop("validity", VALID)
    sensitivities = kw.pop("sensitivities", {menu: _settings() for menu in menus})
    baselines = kw.pop("baselines", {menu: _replay() for menu in menus})  # Stage 1, six origins
    return evidence.decide(validity, menus, sensitivities, baselines)


def _disclosure(verdict: evidence.Verdict, menu: str, setting: str) -> evidence.Disclosure:
    (found,) = [d for d in verdict.disclosures if (d.menu, d.setting) == (menu, setting)]
    return found


def _criterion(
    verdict: evidence.Verdict, menu: str, key: str, location: str = "menu"
) -> evidence.Criterion:
    found = [c for c in verdict.criteria if (c.menu, c.key, c.location) == (menu, key, location)]
    assert len(found) == 1, (menu, key, location, found)
    return found[0]


def _passed(verdict: evidence.Verdict, menu: str, key: str, location: str = "menu") -> bool:
    """Whether an assessed criterion passed (a not-assessed one fails this helper)."""
    passed = _criterion(verdict, menu, key, location).passed
    assert passed is not None, (menu, key, location, "not assessed")
    return passed


def test_both_menus_with_every_criterion_met_authorize_stage_2() -> None:
    verdict = _decide()
    assert verdict.valid
    for menu in ("tsp", "example"):
        label = verdict.menus[menu]
        assert label.conditional == "positive conditional-model evidence"
        assert label.branch == "replay-return" and label.pcme
        assert label.realized == "realized policy support"
        assert label.sensitivity == "robust across the predeclared sensitivities"
    assert verdict.stage_2["run"] is True and verdict.stage_2["failing_criteria"] == []
    assert verdict.confirmed_worthwhile_benefit is True and verdict.material_harm == ()


@pytest.mark.parametrize(
    ("changes", "key", "location"),
    [
        ({"replay": _replay(4.99 * BP)}, "replay.u", "menu"),
        ({"replay": _replay(bad=-5.01 * BP)}, "replay.bad", "menu"),
        ({"replay": _replay(typical=-10.01 * BP)}, "replay.typical", "menu"),
        ({"replay": _replay(good=-20.01 * BP)}, "replay.good", "menu"),
        (
            {"replay": _replay(cells_u={"x25": 6 * BP, "x50": -2.51 * BP, "x100": 6 * BP})},
            "replay.cell_u",
            "x50",
        ),
        ({"replay": _replay(banks=[_bank()] * 3 + [_bank(0.0)] * 2)}, "replay.banks", "menu"),
    ],
)
def test_each_replay_threshold_fails_just_past_its_line(changes, key, location) -> None:
    passing = _decide()
    assert _passed(passing, "example", key, location)
    verdict = _decide(example=_menu("example", **changes))
    assert not _passed(verdict, "example", key, location)
    assert verdict.menus["example"].branch != "replay-return"
    assert verdict.stage_2["run"] is False
    assert any(item.startswith("example:") for item in verdict.stage_2["failing_criteria"])


def test_replay_thresholds_pass_exactly_at_their_lines() -> None:
    at = _replay(
        5 * BP,
        bad=-5 * BP,
        typical=-10 * BP,
        good=-20 * BP,
        cells_u={"x25": -2.5 * BP, "x50": 7.5 * BP, "x100": 10 * BP},
        banks=[_bank(1e-12)] * 4 + [_bank(-1.0)],
    )
    verdict = _decide(example=_menu("example", replay=at))
    for key, location in (("replay.u", "menu"), ("replay.bad", "menu"), ("replay.cell_u", "x25")):
        assert _passed(verdict, "example", key, location)
    assert _passed(verdict, "example", "replay.banks")
    assert verdict.menus["example"].branch == "replay-return"


def _stability_case(**replay: Any) -> MenuEvidence:
    """Pooled ΔU 1 bp (< 5 bp): the replay branch fails, the stability branch is evaluated."""
    base = {"u": 1 * BP, "banks": [_bank(-2.5 * BP)] * 4 + [_bank(-3 * BP)]}
    base.update(replay)
    return _menu("example", replay=_replay(**base))


def test_the_stability_branch_is_evaluated_only_below_5_bp_and_has_its_own_bank_rule() -> None:
    verdict = _decide(example=_stability_case())
    label = verdict.menus["example"]
    assert label.branch == "stability" and label.pcme
    assert _passed(verdict, "example", "stability.bank_floors")  # floors in 4/5, gains never
    assert not _passed(verdict, "example", "replay.banks")
    # a stability-branch menu cannot authorize Stage 2: its sensitivity is unavailable (ruling 1)
    assert verdict.stage_2["run"] is False
    assert label.sensitivity == "parameter/search sensitive or unverified"
    assert any(
        "stability sensitivity unavailable" in item for item in verdict.stage_2["failing_criteria"]
    )
    above = _decide(example=_menu("example", replay=_replay(6 * BP, banks=[_bank(0.0)] * 5)))
    assert above.menus["example"].branch is None  # >= 5 bp: no stability branch (ruling 3)
    rows = {c.key: c for c in above.criteria if c.menu == "example" and c.key.startswith("stab")}
    assert set(rows) == {
        "stability.assessed",
        "stability.l1_relative",
        "stability.l1_absolute",
        "stability.l1_p90",
    }
    assert all(c.passed is None for c in rows.values())  # recorded, not assessed
    assert rows["stability.assessed"].reason == "not assessed: pooled ΔU >= 5 bp (R24-3)"
    # the cross-seed L1 comparison is kept as information: R .30/.50, R+D .10/.20
    assert rows["stability.l1_relative"].value == pytest.approx(0.2 / 0.3)
    assert rows["stability.l1_absolute"].value == pytest.approx(0.2)
    assert rows["stability.l1_p90"].value == pytest.approx(-0.3)
    assert not any("Stable gain" in item for item in above.stage_2["failing_criteria"])


def test_an_undefined_r_turnover_fails_general_stability_with_its_reason() -> None:
    base = _stable(0.30, 0.50)
    base = replace(base, turnover_median={"x25": None, "x50": 0.1, "x100": 0.1})
    verdict = _decide(example=_menu("example", stability={"R": base, "R+D": _stable(0.1, 0.2)}))
    found = _criterion(verdict, "example", "general.turnover", "x25")
    assert found.passed is False and found.threshold is None
    assert found.reason is not None and "undefined" in found.reason
    assert found.record()["reason"] == found.reason
    assert verdict.menus["example"].conditional == (
        "did not meet observed conditional screening criteria"
    )
    assert _passed(verdict, "example", "general.turnover", "x50")


def test_no_menu_is_no_confirmed_benefit() -> None:
    verdict = evidence.decide(VALID, {}, {}, {})
    assert verdict.confirmed_worthwhile_benefit is False and verdict.stage_2["run"] is False


@pytest.mark.parametrize(
    ("change", "key"),
    [
        ({"u": -2.51 * BP}, "stability.u"),
        ({"banks": [_bank(-2.5 * BP)] * 3 + [_bank(-2.51 * BP)] * 2}, "stability.bank_floors"),
        ({"banks": [_bank(0.0, bad=-5.01 * BP)] * 2 + [_bank(0.0)] * 3}, "stability.bank_floors"),
    ],
)
def test_stability_branch_floors_fail_past_their_lines(change, key) -> None:
    verdict = _decide(example=_stability_case(**change))
    assert not _passed(verdict, "example", key)
    assert verdict.menus["example"].branch is None


@pytest.mark.parametrize(
    ("r", "rd", "key"),
    [
        ((0.30, 0.50), (0.2401, 0.50), "stability.l1_relative"),  # 19.97% < 20%
        ((0.09, 0.30), (0.0701, 0.30), "stability.l1_absolute"),  # 22% but .0199 < .02
        ((0.30, 0.50), (0.10, 0.5001), "stability.l1_p90"),
    ],
)
def test_the_cross_seed_l1_comparison_fails_past_each_line(r, rd, key) -> None:
    stability = {"R": _stable(*r), "R+D": _stable(*rd)}
    case = replace(_stability_case(), stability=stability)
    verdict = _decide(example=case)
    assert not _passed(verdict, "example", key)
    assert verdict.menus["example"].branch is None
    at = {"R": _stable(0.625, 0.75), "R+D": _stable(0.5, 0.75)}  # exactly 20%, .125, equal p90
    assert _decide(example=replace(case, stability=at)).menus["example"].branch == "stability"


def test_meaningful_score_change_failing_labels_the_preference_inactive() -> None:
    for changes, key in (
        ({"dr2_gain": 0.0999}, "score.dr2"),
        ({"changed_share": 0.1999}, "score.changed"),
    ):
        verdict = _decide(example=_menu("example", **changes))
        assert not _passed(verdict, "example", key)
        label = verdict.menus["example"]
        assert label.score_change == "inactive/near-inactive at the 2.5 bp primary cap"
        assert label.conditional == "did not meet observed conditional screening criteria"
    passing = _decide(example=_menu("example", dr2_gain=0.10, changed_share=0.20))
    assert passing.menus["example"].score_change == "active at the 2.5 bp primary cap"


@pytest.mark.parametrize(
    ("rd", "key"),
    [
        (_stable(0.10, 0.20, share=0.9499), "general.bad_sd"),
        (_stable(0.2001, 0.30), "general.median_l1"),
        (_stable(0.10, 0.4001), "general.p90_l1"),
        (_stable(0.10, 0.20, turnover=0.1501), "general.turnover"),
    ],
)
def test_general_stability_fails_in_a_risk_cell(rd, key) -> None:
    menu = _menu("example", stability={"R": _stable(0.30, 0.50), "R+D": rd})
    verdict = _decide(example=menu)
    assert not _passed(verdict, "example", key, "x25")
    assert verdict.menus["example"].conditional == (
        "did not meet observed conditional screening criteria"
    )
    at = _stable(0.20, 0.40, share=0.95, turnover=0.15)
    ok = _decide(example=_menu("example", stability={"R": _stable(0.30, 0.50), "R+D": at}))
    assert _passed(ok, "example", key, "x25")


@pytest.mark.parametrize(
    ("cost", "key"),
    [(Cost(30.01, 1.1, 10), "cost.r_wall"), (Cost(5.0, 1.2501, 10), "cost.ratio")],
)
def test_cost_fails_per_menu_wall_and_paired_ratio(cost, key) -> None:
    verdict = _decide(example=_menu("example", cost=cost))
    assert not _passed(verdict, "example", key)
    assert verdict.stage_2["run"] is False
    assert _passed(_decide(example=_menu("example", cost=Cost(30.0, 1.25, 10))), "example", key)
    tsp = _decide(tsp=_menu("tsp", cost=Cost(10.01, 1.0, 10)))
    assert not _passed(tsp, "tsp", "cost.r_wall")  # TSP's line is 10 s


@pytest.mark.parametrize(
    ("cell", "key"),
    [
        (RealizedCell(25.01 * BP, 0.0, 0.0, 0.0), "guard.median_loss"),
        (RealizedCell(0.0, 25.01 * BP, 0.0, 0.0), "guard.mean_loss"),
        (RealizedCell(0.0, 0.0, 0.0501, 0.0), "guard.loss_frequency"),
        (RealizedCell(0.0, 0.0, 0.0, 0.0101), "guard.drawdown"),
    ],
)
def test_a_realized_guardrail_breach_is_material_harm_at_its_location(cell, key) -> None:
    ok = RealizedCell(0.0, 0.0, 0.0, 0.0)
    realized = _realized(cells={"x25": ok, "x50": cell, "x100": ok})
    verdict = _decide(example=_menu("example", realized=realized))
    assert not _passed(verdict, "example", key, "x50")
    assert [(c.menu, c.key, c.location) for c in verdict.material_harm] == [("example", key, "x50")]
    label = verdict.menus["example"]
    assert label.realized == "inconclusive historical evidence"
    assert label.conditional == "positive conditional-model evidence"  # harm does not gate PCME
    assert verdict.stage_2["run"] is True  # nor Stage 2 (D7)
    assert verdict.confirmed_worthwhile_benefit is False
    at = RealizedCell(25 * BP, 25 * BP, 0.05, 0.01)
    edge = _decide(example=_menu("example", realized=_realized(cells=dict.fromkeys(CELLS, at))))
    assert edge.material_harm == ()


def test_realized_support_needs_twenty_disjoint_intervals_and_a_positive_99_lower_bound() -> None:
    for realized in (
        _realized(disjoint=19),
        _realized(gain=_estimate(30 * BP, 0.0)),
        _realized(gain=_estimate(24.99 * BP, 1 * BP)),
    ):
        verdict = _decide(example=_menu("example", realized=realized))
        assert verdict.menus["example"].realized == "inconclusive historical evidence"
        assert verdict.confirmed_worthwhile_benefit is False
        assert verdict.stage_2["run"] is True  # confirmed benefit never gates Stage 2
    drawdown = _realized(
        gain=_estimate(-10 * BP, -0.01),
        mean_loss=10 * BP,
        drawdown_improvement=_estimate(0.01, 1e-6),
    )
    assert _decide(example=_menu("example", realized=drawdown)).menus["example"].realized == (
        "realized policy support"
    )
    too_costly = replace(drawdown, mean_loss=25.01 * BP)
    verdict = _decide(example=_menu("example", realized=too_costly))
    assert verdict.menus["example"].realized == "inconclusive historical evidence"


def test_tail_power_and_exploratory_interval_labels() -> None:
    verdict = _decide(example=_menu("example", realized=_realized(disjoint=19)))
    assert verdict.menus["example"].tail_power == "underpowered"
    assert verdict.menus["example"].intervals == "exploratory"
    full = _decide(example=_menu("example", realized=_realized(disjoint=200)))
    assert full.menus["example"].tail_power.startswith("at least 200")
    assert full.menus["example"].intervals == "at least 20 disjoint annual intervals"


def test_a_replay_floor_breach_is_material_harm() -> None:
    verdict = _decide(example=_menu("example", replay=_replay(bad=-5.01 * BP)))
    assert ("example", "replay.bad", "menu") in [
        (c.menu, c.key, c.location) for c in verdict.material_harm
    ]


def test_an_invalid_experiment_is_inconclusive_and_never_a_winner() -> None:
    invalid = Validity(valid=False, reasons=("paired-cell failure rate 0.02 > 0.01",))
    verdict = _decide(validity=invalid)
    assert not verdict.valid
    for label in verdict.menus.values():
        assert label.conditional == "inconclusive/invalid" and not label.pcme
        assert label.realized == "inconclusive/invalid"
        # no protocol 7 label derives from statistics of an invalid experiment (R25)
        assert label.branch is None and label.sensitivity == "inconclusive/invalid"
        assert label.score_change == "inconclusive/invalid"
    assert not any(d.blocking for d in verdict.disclosures)
    assert verdict.stage_2["run"] is False
    assert verdict.stage_2["failing_criteria"][0].startswith("validity:")
    assert verdict.confirmed_worthwhile_benefit is False


def test_confirmed_benefit_needs_conditional_model_evidence_in_both_menus() -> None:
    """Codex P2-6: realized support passes in both menus, Example's screening fails."""
    verdict = _decide(example=_menu("example", dr2_gain=0.0999))
    assert all(label.support for label in verdict.menus.values())
    assert verdict.menus["example"].pcme is False and verdict.material_harm == ()
    assert verdict.confirmed_worthwhile_benefit is False
    assert _decide().confirmed_worthwhile_benefit is True


def test_stage_2_needs_both_menus_and_confirmed_benefit_does_not_gate_it() -> None:
    one = _decide(tsp=_menu("tsp", dr2_gain=0.0))
    assert one.menus["example"].pcme and not one.menus["tsp"].pcme
    assert one.stage_2["run"] is False
    assert "ENB unevaluated, not ineffective" in one.stage_2["reason"]
    benefit_only = _decide(tsp=_menu("tsp", dr2_gain=0.0), example=_menu("example", dr2_gain=0.0))
    assert benefit_only.menus["tsp"].realized == "realized policy support"
    assert benefit_only.stage_2["run"] is False


def test_sensitivity_disclosures_block_stage_2_except_the_inert_0_bp_cap() -> None:
    inert = _settings()
    inert["cap-0bp"] = _replay(0.0, banks=[_bank(0.0)] * 5)
    assert _decide(sensitivities={"tsp": inert, "example": inert}).stage_2["run"] is True
    # protocol amendment R26: the 0 bp diagnostic control never blocks, unavailable included
    gone = _settings()
    gone["cap-0bp"] = None
    verdict = _decide(sensitivities={"tsp": gone, "example": gone})
    assert verdict.stage_2["run"] is True
    zero = _disclosure(verdict, "example", "cap-0bp")
    assert not zero.available and zero.inert and not zero.blocking
    assert any("R26" in reason for reason in _disclosure(verdict, "tsp", "cap-0bp").reasons)
    small = _settings()
    small["budget-x2"] = _replay(1 * BP)  # positive, under 5 bp: reported, does not block alone
    assert _decide(sensitivities={"tsp": _settings(), "example": small}).stage_2["run"] is True
    for name, replay_ in (
        ("cap-5bp", _replay(-0.5 * BP)),  # sign reversal
        ("cap-10bp", _replay(6 * BP, good=-20.01 * BP)),  # a floor fails
        ("lookback-252", _replay(6 * BP, banks=[_bank()] * 3 + [_bank(0.0)] * 2)),  # banks
        ("coefficients-70-20-10", None),  # unavailable
    ):
        settings = _settings()
        settings[name] = replay_
        verdict = _decide(sensitivities={"tsp": _settings(), "example": settings})
        assert verdict.menus["example"].pcme  # the label stands; progression is blocked
        assert verdict.menus["example"].sensitivity == "parameter/search sensitive or unverified"
        assert verdict.stage_2["run"] is False
        assert any(name in item for item in verdict.stage_2["failing_criteria"])


def test_a_sign_reversal_is_judged_against_stage_1_on_the_same_six_origins() -> None:
    """R27: the full panel's ΔU is +6 bp in both cases; the setting is compared with Stage 1 on
    its own six origins, in either direction the full-panel comparison would get wrong."""
    negative = _replay(-1 * BP, banks=[_bank(-1 * BP)] * 5)
    settings = _settings()
    settings["budget-x2"] = negative
    # Stage 1 is negative on the six origins too: no reversal (the full panel would say one)
    same = _decide(
        sensitivities={"tsp": _settings(), "example": settings},
        baselines={"tsp": _replay(), "example": negative},
    )
    found = _disclosure(same, "example", "budget-x2")
    assert found.sign_reversal is False and found.baseline == -1 * BP
    assert "replay-return sign reversal" not in found.reasons
    # Stage 1 is negative on the six origins, the setting positive: a reversal (the full panel
    # would see none)
    flipped = _decide(baselines={"tsp": _replay(), "example": negative})
    found = _disclosure(flipped, "example", "budget-x2")
    assert found.sign_reversal is True and found.blocking
    assert found.record()["baseline_u"] == -1 * BP
    assert flipped.stage_2["run"] is False
    assert any("budget-x2" in item for item in flipped.stage_2["failing_criteria"])
    # without the Stage 1 baseline a reversal cannot be ruled out: unverified, it blocks
    unknown = _decide(baselines={"tsp": _replay(), "example": None})
    found = _disclosure(unknown, "example", "budget-x2")
    assert found.blocking and any("baseline unavailable" in r for r in found.reasons)
    assert not _disclosure(unknown, "example", "cap-0bp").blocking  # R26
    assert unknown.stage_2["run"] is False


def test_one_failing_menu_fails_the_aggregate_even_when_the_50_50_mean_looks_favorable() -> None:
    """TSP +20 bp, Example +2 bp: the 50/50 aggregate is 11 bp, yet Example fails."""
    rows = []
    for month in MONTHS:
        for ceiling in CELLS:
            rows += _pair("tsp", month, ceiling, 20.0) + _pair("example", month, ceiling, 2.0)
    grid = Grid(_table(rows), MONTHS, profile="stage-1")
    boot = Bootstrap(3)
    table = evidence.paired_estimates(grid, ("tsp", "example"), RD, R, "test_utility", P, boot)
    assert table["aggregate"].value == pytest.approx(11 * BP, abs=1e-15)
    flat = {"R": _stable(0.10, 0.20), "R+D": _stable(0.10, 0.20)}  # no L1 reduction
    menus = {
        menu: _menu(menu, replay=evidence.replay_contrast(grid, menu, RD, R, P), stability=flat)
        for menu in ("tsp", "example")
    }
    verdict = evidence.decide(
        VALID, menus, {menu: _settings() for menu in menus}, {menu: _replay() for menu in menus}
    )
    assert verdict.menus["tsp"].pcme
    assert verdict.menus["example"].conditional == (
        "did not meet observed conditional screening criteria"
    )
    assert verdict.stage_2["run"] is False
    assert "example: Independent replay return gain" in " | ".join(
        verdict.stage_2["failing_criteria"]
    )


def test_calibration_never_enters_a_decision() -> None:
    """The decision takes no calibration input: changing pinball loss cannot select an arm."""
    import inspect

    assert "calibration" not in inspect.signature(evidence.decide).parameters
    assert not any("calibration" in f for f in MenuEvidence.__dataclass_fields__)


def test_disjoint_intervals_are_counted_greedily_in_origin_order() -> None:
    """Hand oracle: an origin is retained only when strictly after the last retained end."""
    origins = [1, 2, 13, 14, 26, 40]
    ends = [12, 13, 25, 26, 38, 52]
    assert evidence.disjoint_count(origins, ends) == 4  # 1-12, 13-25, 26-38, 40-52
    assert evidence.disjoint_count([1, 12, 13], [12, 24, 25]) == 2  # 12 is not after 12


# ------------------------------------------------------------------------- real artifacts


@pytest.fixture(scope="module")
def run_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Stage 1 (three origins, two seeds, both menus) and its three sensitivities."""
    tmp = tmp_path_factory.mktemp("report")
    records = make_records()
    settings = make_settings(records)
    run_experiment(tmp, records, settings=settings, run_id="r")
    for name in ("coefficients", "lookback", "budget"):
        run_experiment(tmp, records, settings=settings, run_id="r", sensitivity=name)
    return tmp


def _copy(run_root: Path, tmp_path: Path, *, sensitivities: bool = True) -> Path:
    """A copy of the fixture's output tree; returns the Stage 1 run directory in it."""
    ignore = None if sensitivities else shutil.ignore_patterns("sensitivity-*")
    shutil.copytree(run_root / "out", tmp_path / "out", ignore=ignore)
    (directory,) = (tmp_path / "out").glob("*/r")
    return directory


def _files(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_an_incomplete_run_is_refused_unless_allowed_and_then_invalid(
    run_root: Path, tmp_path: Path
) -> None:
    directory = _copy(run_root, tmp_path, sensitivities=False)
    with pytest.raises(report.IncompleteRun, match="sensitivity has not run"):
        report.write_report(directory)
    assert not (directory / "summary.json").exists()
    before = _files(tmp_path)
    written = report.write_report(directory, allow_incomplete=True)
    after = _files(tmp_path)
    assert set(after) - set(before) == {
        "out/" + str(directory.relative_to(tmp_path / "out")) + n
        for n in ("/summary.json", "/report.md")
    }
    assert {k: v for k, v in after.items() if k in before} == before  # nothing else changed
    summary = json.loads((directory / "summary.json").read_text())
    assert summary["labels"]["experiment"] == "inconclusive/invalid"
    assert any(r.startswith("sensitivity_budget_complete") for r in summary["validity"]["reasons"])
    assert summary["stage_2"]["run"] is False
    assert summary["stage_2"]["failing_criteria"][0].startswith("validity:")
    for menu in ("tsp", "example"):
        settings = summary["sensitivities"]["menus"][menu]["settings"]
        assert settings["budget-x2"]["replay"] is None  # unavailable, kept on the table
    assert written.verdict is not None and not written.verdict.valid


def test_every_listed_artifact_is_verified_against_its_digest(
    run_root: Path, tmp_path: Path
) -> None:
    directory = _copy(run_root, tmp_path)
    outcomes_path = directory / "outcomes.parquet"
    original = outcomes_path.read_bytes()
    outcomes_path.write_bytes(original + b"\0")
    with pytest.raises(report.ArtifactChanged, match="outcomes.parquet"):
        report.write_report(directory)
    outcomes_path.write_bytes(original)
    resources = directory / "sensitivity-budget" / "resources.jsonl"
    saved = resources.read_bytes()
    resources.unlink()
    with pytest.raises(report.ArtifactChanged, match="missing"):
        report.write_report(directory)
    resources.write_bytes(saved)
    search = directory / "search.parquet"
    search.write_bytes(search.read_bytes()[:-1] + b"X")
    with pytest.raises(report.ArtifactChanged, match="search.parquet"):
        report.write_report(directory)
    assert not (directory / "summary.json").exists()


@pytest.fixture(scope="module")
def written(run_root: Path, tmp_path_factory: pytest.TempPathFactory) -> report.Report:
    return report.write_report(_copy(run_root, tmp_path_factory.mktemp("written")))


def test_the_summary_has_every_section_and_a_stage_2_decision(written: report.Report) -> None:
    summary = json.loads((written.directory / "summary.json").read_text())
    assert list(summary) == list(report.SUMMARY_SECTIONS)
    assert set(summary["stage_2"]) == {"run", "reason", "failing_criteria"}
    # reduced settings and two mature origins: not the protocol experiment
    assert summary["labels"]["experiment"] == "inconclusive/invalid"
    reasons = " ".join(summary["validity"]["reasons"])
    assert "protocol_settings" in reasons and "coverage_gate" in reasons
    assert summary["stage_2"]["run"] is False
    assert summary["denominator"]["cells"] == 36 and summary["denominator"]["failed"] == 0
    names = {"locked.parquet", "origins.parquet", "outcomes.parquet", "search.parquet"}
    assert set(summary["verification"]["stage_1"]) == names | {"resources.jsonl"}
    arms = summary["cost"]["stage_1"]["tsp"]["search_cost_by_arm"]
    assert arms["R+D"]["native_selection"]["sum"] > 0.0  # a timed sub-part of each arm
    for name, entry in summary["verification"]["sensitivities"].items():
        assert entry["state"] == "complete", name
    assert summary["panel"]["months"] == ["2024-07", "2024-08", "2024-09"]
    assert summary["panel"]["realized_mask"] == [True, True, False]
    menus = summary["sensitivities"]["menus"]
    assert set(menus["tsp"]["settings"]) == set(evidence.SENSITIVITY_SETTINGS)
    assert summary["labels"]["menus"]["tsp"]["tail_power"] == "underpowered"
    assert summary["labels"]["menus"]["tsp"]["intervals"] == "exploratory"
    keys = {(c["menu"], c["key"], c["location"]) for c in summary["criteria"]}
    for key in ("replay.u", "score.dr2", "cost.ratio", "support.gain", "harm.u"):
        assert ("example", key, "menu") in keys
    for cell in CELLS:
        assert ("tsp", "general.bad_sd", cell) in keys and ("tsp", "guard.drawdown", cell) in keys
    assert len(summary["protocol_readings"]) == len(report.PROTOCOL_READINGS)
    assert "R23" in summary["scope"]["allowance_sweep"]
    assert summary["scope"]["process_model"].startswith("in-process")


def _outcome_rows(directory: Path) -> list[dict[str, Any]]:
    return pq.read_table(directory / "outcomes.parquet").to_pylist()


def test_summary_statistics_match_hand_aggregation_of_the_outcomes(
    written: report.Report,
) -> None:
    rows = [r for r in _outcome_rows(written.directory) if r["profile"] == "stage-1"]
    primary = [r for r in rows if r["seed"] == P]
    by = {
        (r["menu"], r["month"], c, r["role"], r["allowance"]): r
        for r in primary
        for c in r["stands_for"]
    }
    summary = written.summary
    for menu in ("tsp", "example"):
        origins = []
        for month in ("2024-07", "2024-08", "2024-09"):
            cells = [
                by[(menu, month, c, "R+D", 0.00025)]["test_utility"]
                - by[(menu, month, c, "R", None)]["test_utility"]
                for c in CELLS
            ]
            origins.append(sum(cells) / 3)
        hand = sum(origins) / 3
        value = summary["primary"]["replay"]["utility"]["by_menu"][menu]["value"]
        assert value == pytest.approx(hand, abs=1e-15)
        realized = []
        for month in ("2024-07", "2024-08"):  # 2024-09 is immature: outside the realized mask
            cells = [
                by[(menu, month, c, "R+D", 0.00025)]["annual_return"]
                - by[(menu, month, c, "R", None)]["annual_return"]
                for c in CELLS
            ]
            realized.append(sum(cells) / 3)
        gain = summary["primary"]["realized"]["annual_return"]["by_menu"][menu]["value"]
        assert gain == pytest.approx(sum(realized) / 2, abs=1e-15)
        assert summary["primary"]["realized"]["annual_return"]["by_menu"][menu]["n"] == 2
    tsp = summary["primary"]["replay"]["utility"]["by_menu"]["tsp"]["value"]
    example = summary["primary"]["replay"]["utility"]["by_menu"]["example"]["value"]
    aggregate = summary["primary"]["replay"]["utility"]["aggregate"]["value"]
    assert aggregate == pytest.approx((tsp + example) / 2, abs=1e-15)
    # the forecast-error correlation agrees with the runner's point diagnostic
    point = outcomes.forecast_error_diagnostic(pd.DataFrame(rows))
    defined = 0
    for record in point.to_dict("records"):
        found = summary["forecast_error"][record["menu"]][record["ceiling_id"]]
        correlation = record["correlation"]
        if correlation is None or math.isnan(correlation):  # no variation: undefined in both
            assert found["value"] is None and found["sign"] is None
            continue
        defined += 1
        assert found["value"] == pytest.approx(correlation, abs=1e-12)
        assert found["sign"] == record["sign"]
    assert defined > 0


def test_calibration_of_the_run_follows_the_pinball_identity(written: report.Report) -> None:
    rows = [
        r
        for r in _outcome_rows(written.directory)
        if r["profile"] == "stage-1" and r["seed"] == P and r["role"] == "R"
    ]
    for row in rows:
        if row["annual_return"] is None:
            continue
        y = row["annual_return"]
        for name, q in (("bad", 0.025), ("typical", 0.5), ("good", 0.975)):
            f = row[f"test_{name}"]
            assert row[f"test_pinball_{name}"] == pytest.approx(
                max(q * (y - f), (q - 1) * (y - f)), abs=1e-15
            )
    for menu in ("tsp", "example"):
        mature = [r for r in rows if r["menu"] == menu and r["month"] != "2024-09"]
        y_f = [(r["annual_return"], r["test_bad"]) for r in mature]
        hand = sum(max(0.025 * (y - f), (0.025 - 1) * (y - f)) for y, f in y_f) / len(y_f)
        found = written.summary["calibration"][menu]["R"]["test"]["bad"]["menu"]
        assert found["pinball"] == pytest.approx(hand, abs=1e-15)
        assert found["coverage"] == pytest.approx(sum(y <= f for y, f in y_f) / len(y_f))


def test_the_markdown_puts_limits_first_and_references_before_r_plus_d(
    written: report.Report,
) -> None:
    text = (written.directory / "report.md").read_text()
    order = [
        "## Read this first",
        "## Verdict",
        "## Protocol compliance",
        "## Panel, coverage",
        "## R against the return-agnostic references",
        "## White-line candidates",
        "## R+D against R at the 2.5 bp primary cap",
        "## Realized outcomes",
        "## Forecast-error diagnostic",
        "## Calibration",
        "## Stability",
        "## Native-search",
        "## Sensitivities",
        "## Cost",
        "## Every threshold result",
        "## Protocol readings",
        "## Appendix A",
        "## Appendix B",
    ]
    positions = [text.index(heading) for heading in order]
    assert positions == sorted(positions)
    for phrase in (
        "retrospective fixed-menu, as-of-truncated backtest",
        "monthly cohorts overlap",
        "underpowered",
        "understates a search targeted at those caps",
        "cannot authorize Stage 2",
        "claims no review",
        "ΔES_2.5",
        "**Stage 2 (ENB): skip.**",
        "ENB unevaluated, not ineffective",
    ):
        assert phrase in text, phrase
    assert "best" not in text.split("## Sensitivities")[1].split("## Cost")[0].lower()
    for raw in ("Δutility", "Δbad", "Δtypical", "Δgood", "Δes_25", "es_25 ", "utility "):
        assert raw not in text, raw  # every figure is labeled ΔU/ΔB/ΔT/ΔG/ΔES_2.5 or U/B/T/G
    assert "ΔU:" in text and "ΔES_2.5:" in text and "q(.025) (Bad) across origins" in text


def test_writing_twice_gives_identical_bytes(written: report.Report) -> None:
    first = {
        name: (written.directory / name).read_bytes() for name in ("summary.json", "report.md")
    }
    report.write_report(written.directory)
    for name, data in first.items():
        assert (written.directory / name).read_bytes() == data


def test_invariance_breaks_name_equal_weights_with_different_outcomes(
    written: report.Report,
) -> None:
    table = pq.read_table(written.directory / "outcomes.parquet")
    assert report.invariance_breaks(table) == []
    rows = table.to_pylist()
    r = next(i for i, row in enumerate(rows) if row["role"] == "R")
    twin = next(
        i
        for i, row in enumerate(rows)
        if i != r
        and row["cell_key"] == rows[r]["cell_key"]
        and row["weights"] == rows[r]["weights"]
    )  # R+D at 0 bp chooses w_R
    rows[twin]["test_bad"] += 1e-12
    broken = report.invariance_breaks(pa.Table.from_pylist(rows, schema=table.schema))
    assert len(broken) == 1


def test_the_runner_reads_the_report_stage_2_decision(run_root: Path, tmp_path: Path) -> None:
    directory = _copy(run_root, tmp_path)
    report.write_report(directory)
    records = make_records()
    amended = Limits(workers=0, cpu_hours=1.0, cpu_amended=True)
    with pytest.raises(experiment.StageNotReady, match="stage_2.run"):
        run_experiment(
            tmp_path, records, settings=make_settings(records), limits=amended, run_id="r", stage=2
        )


@pytest.fixture(scope="module")
def cli() -> ModuleType:
    return load_module("backtest_ranges_report", ROOT / "scripts" / "backtest_ranges.py")


def test_cli_writes_the_report_and_names_refusals(
    cli: ModuleType, run_root: Path, tmp_path: Path, capsys
) -> None:
    directory = _copy(run_root, tmp_path)
    review = ["--review", "Codex (GPT-6), 2026-10-25, Stage 1 results"]
    assert cli.main(["experiment", "report", "--run", str(directory), *review]) == 0
    printed = capsys.readouterr().out
    assert "summary.json and report.md written" in printed and "stage 2: skip" in printed
    manifest = json.loads((directory / "manifest.json").read_text())
    assert manifest["reviews"] == ["Codex (GPT-6), 2026-10-25, Stage 1 results"]
    lone = _copy(run_root, tmp_path / "lone", sensitivities=False)
    assert cli.main(["experiment", "report", "--run", str(lone)]) == 7
    assert "refused" in capsys.readouterr().err
    assert cli.main(["experiment", "report", "--run", str(lone), "--allow-incomplete"]) == 0
    (directory / "locked.parquet").write_bytes(b"changed")
    assert cli.main(["experiment", "report", "--run", str(directory)]) == 6


def test_menus_of_different_sizes_keep_their_own_weight_width() -> None:
    """Weights of a 3-fund and a 5-fund menu: neither pads the other's L1 or stability."""
    rows = []
    for seed, shift in ((P, 0.0), (S, 0.1)):
        rows.append(
            _row(
                "tsp",
                "2020-01",
                "x100",
                R,
                seed=seed,
                stands_for=list(CELLS),
                weights=[0.5, 0.5, 0.0],
                dr2=1.0,
                risk=0.1,
                test_bad=-0.02,
            )
        )
        rows.append(
            _row(
                "tsp",
                "2020-01",
                "x100",
                RD,
                seed=seed,
                stands_for=list(CELLS),
                weights=[0.5 - shift, 0.3 + shift, 0.2],
                dr2=1.3,
                risk=0.1,
                test_bad=-0.02,
            )
        )
        rows.append(
            _row(
                "example",
                "2020-01",
                "x100",
                R,
                seed=seed,
                stands_for=list(CELLS),
                weights=[0.2] * 5,
                dr2=2.0,
                risk=0.1,
                test_bad=-0.02,
            )
        )
        rows.append(
            _row(
                "example",
                "2020-01",
                "x100",
                RD,
                seed=seed,
                stands_for=list(CELLS),
                weights=[0.25, 0.25, 0.2, 0.15, 0.15],
                dr2=2.0,
                risk=0.1,
                test_bad=-0.02,
            )
        )
    grid = Grid(_table(rows), ("2020-01",), profile="stage-1")
    assert grid.lists("tsp", RD, "weights", P).shape == (3, 3, 1)
    assert grid.lists("example", RD, "weights", P).shape == (5, 3, 1)
    dr2, changed = evidence.score_change(grid, "tsp", RD, R, P)
    assert dr2 == pytest.approx(0.3) and changed == 1.0  # L1 = 0.2 + 0.2 = 0.4 >= .02
    assert evidence.score_change(grid, "example", RD, R, P)[1] == 1.0  # L1 = 0.2
    found = evidence.stability(grid, "tsp", RD, P)
    assert found.median_l1["x25"] == pytest.approx(0.2)  # one seed pair: |0.1| + |0.1|


def test_expected_shortfall_averages_the_worst_ceil_2_5_percent_of_origins() -> None:
    """40 origins: the single worst (ceil(1.0) = 1); 41 origins: the two worst (ceil(1.025))."""
    rng = np.random.default_rng(3)
    x = rng.normal(size=41)
    identity = np.arange(41)[None, :]
    assert evidence.expected_shortfall(x, identity)[0] == pytest.approx(np.sort(x)[:2].mean())
    masked = x.copy()
    masked[0] = np.nan  # 40 available
    assert evidence.expected_shortfall(masked, identity)[0] == pytest.approx(np.nanmin(masked))
    assert math.isnan(evidence.expected_shortfall(np.full(3, np.nan), np.arange(3)[None, :])[0])


def _cells(
    statuses: dict[str, int], *, listing: list[str] | None = None, state: str = "complete"
) -> report.RunFiles:
    """search.parquet cell rows by status; ``listing`` is the manifest's frozen denominator."""
    cells = []
    for status, count in statuses.items():
        for i in range(count):
            cells.append(
                {
                    "profile": "stage-1",
                    "cell_key": f"{status}-{i}",
                    "cell_status": status,
                    "error": None if status == "ok" else status,
                    "error_detail": "named",
                }
            )
    manifest: dict[str, Any] = {"status": {"state": state}}
    if listing is not None:
        entries = [{"profile": "stage-1", "key": key} for key in listing]
        manifest["denominator"] = {"cells": len(entries), "listing": entries}
    return report.RunFiles(Path("."), manifest, {}, None, None, tuple(cells), ())


def test_the_failure_rate_excludes_training_ineligible_cells() -> None:
    """Failed arms and named errors count; training_ineligible is excluded from both sides."""
    at_limit = report.denominator(_cells({"ok": 97, "failed_arm": 1, "training_ineligible": 2}))
    assert at_limit["failure_denominator"] == 98 and at_limit["failed"] == 1
    assert at_limit["training_ineligible_excluded"] == 2
    assert at_limit["failure_rate"] == pytest.approx(1 / 98)
    assert at_limit["failure_rate_above_limit"] is True  # 1/98 > 1%
    within = report.denominator(_cells({"ok": 99, "named_computational_error": 1}))
    assert within["failure_rate"] == 0.01 and within["failure_rate_above_limit"] is False
    assert [c["cell_key"] for c in within["failed_cells"]] == ["named_computational_error-0"]
    stopped = report.denominator(_cells({"ok": 10, "unattempted": 1, "interrupted": 1}))
    assert stopped["incomplete"] == 2 and stopped["failed"] == 0
    assert {c["cell_status"] for c in stopped["failed_cells"]} == {"unattempted", "interrupted"}


def _check(checks: list[dict[str, Any]], name: str) -> dict[str, Any]:
    (found,) = [c for c in checks if c["check"] == name]
    return found


def test_one_failed_cell_in_a_hundred_prevents_a_valid_verdict() -> None:
    """R25: a valid verdict needs zero unresolved required-arm failures; 1% is not a pass."""
    run = _cells({"ok": 99, "named_computational_error": 1})
    counted = report.denominator(run)
    assert counted["failure_rate"] == 0.01 and counted["failure_rate_above_limit"] is False
    valid, checks = report.validity(run, {}, None, counted, {})
    found = _check(checks, "no_failed_cells")
    assert found["met"] is False and "1 failed of 100" in found["detail"]
    assert not valid.valid and any(r.startswith("no_failed_cells") for r in valid.reasons)
    clean = _cells({"ok": 100, "training_ineligible": 3})
    _, checks = report.validity(clean, {}, None, report.denominator(clean), {})
    assert _check(checks, "no_failed_cells")["met"] is True


def test_every_frozen_cell_must_have_its_search_row() -> None:
    """The frozen denominator is the reference: a cell without a row is missing, not dropped."""
    run = _cells({"ok": 3}, listing=["ok-0", "ok-1", "ok-2", "lost"])
    counted = report.denominator(run)
    assert counted["missing"] == 1 and counted["missing_cells"] == ["lost"]
    assert counted["cells"] == 4  # the frozen count, the missing cell included
    _, checks = report.validity(run, {}, None, counted, {})
    found = _check(checks, "frozen_schedule")
    assert found["met"] is False and "lost" in found["detail"]
    whole = _cells({"ok": 3}, listing=["ok-0", "ok-1", "ok-2"])
    _, checks = report.validity(whole, {}, None, report.denominator(whole), {})
    assert _check(checks, "frozen_schedule")["met"] is True


def test_a_stage_1_run_without_outcomes_is_reported_invalid_only_when_allowed(
    run_root: Path, tmp_path: Path
) -> None:
    """A run stopped before its lock: no locked or outcomes file, state incomplete."""
    directory = _copy(run_root, tmp_path)
    manifest = json.loads((directory / "manifest.json").read_text())
    manifest["status"] = {"state": "incomplete", "breach": {"rule": "cpu_hours", "limit": 1.0}}
    for name in ("locked.parquet", "outcomes.parquet"):
        del manifest["artifacts"][name]
        (directory / name).unlink()
    del manifest["lock"]
    (directory / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(report.IncompleteRun, match="incomplete"):
        report.write_report(directory)
    written = report.write_report(directory, allow_incomplete=True)
    summary = written.summary
    assert list(summary) == list(report.SUMMARY_SECTIONS)
    assert summary["labels"]["experiment"] == "inconclusive/invalid"
    assert summary["stage_2"]["run"] is False and summary["primary"] is None
    assert "stage_1_complete: Stage 1 state incomplete" in summary["validity"]["reasons"]
    assert "Unavailable: the run has no outcomes to assess." in written.markdown
    assert written.verdict is None


def test_selection_and_guard_frequencies_count_every_seed_and_origin() -> None:
    rows = []
    for seed, rd, guards in ((P, [0.5, 0.5, 0.0], "[]"), (S, [0.4, 0.4, 0.2], '["u"]')):
        rows.append(
            _row(
                "tsp",
                "2020-01",
                "x100",
                R,
                seed=seed,
                stands_for=list(CELLS),
                weights=[0.5, 0.5, 0.0],
            )
        )
        rows.append(
            _row(
                "tsp",
                "2020-01",
                "x100",
                RD,
                seed=seed,
                stands_for=list(CELLS),
                weights=rd,
                guards=guards,
            )
        )
    found = report.selection_frequencies(Grid(_table(rows), ("2020-01",), profile="stage-1"), "tsp")
    for cell in CELLS:
        assert found[cell]["entries"] == 2 and found[cell]["r_plus_d_is_w_r"] == 0.5
        assert found[cell]["binding_guards"] == {
            "bad": 0.0,
            "typical": 0.0,
            "good": 0.0,
            "u": 0.5,
            "veto": 0.0,
        }


def test_search_parquet_is_parsed_from_the_handle_that_was_hashed(
    run_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A change between hashing and parsing (here: right after the hash) refuses the report."""
    directory = _copy(run_root, tmp_path)
    search = directory / "search.parquet"
    original = report._hash_handle

    def hash_then_change(handle):
        digest = original(handle)
        with search.open("ab") as other:  # the same file, through another handle
            other.write(b"\0")
        return digest

    monkeypatch.setattr(report, "_hash_handle", hash_then_change)
    with pytest.raises(report.ArtifactChanged, match="changed while it was hashed"):
        report.read_run(directory)
    monkeypatch.undo()
    with pytest.raises(report.ArtifactChanged, match="SHA-256"):  # the bytes now differ too
        report.read_run(directory)


def _rewrite(directory: Path, name: str, change) -> None:
    """Rewrite one parquet artifact row by row (``change`` returns None to drop a row) and
    record its new digest in the manifest."""
    path = directory / name
    table = pq.read_table(path)
    rows = [new for new in (change(row) for row in table.to_pylist()) if new is not None]
    pq.write_table(pa.Table.from_pylist(rows, schema=table.schema), path)
    manifest = json.loads((directory / "manifest.json").read_text())
    manifest["artifacts"][name] = hashlib.sha256(path.read_bytes()).hexdigest()
    (directory / "manifest.json").write_text(json.dumps(manifest))


def test_a_missing_horizon_in_one_menu_masks_that_origin_in_both(
    run_root: Path, tmp_path: Path
) -> None:
    """Example's 2024-08 horizon is made incomplete: TSP's realized statistics drop 2024-08 too."""
    directory = _copy(run_root, tmp_path)
    issue = '[{"code": "horizon_value_missing", "fund": "X", "date": "2025-01-02", "note": ""}]'

    def origins(row: dict[str, Any]) -> dict[str, Any]:
        if row["menu"] == "example" and row["month"] == "2024-08" and row["lookback"] == "2y":
            row = {**row, "outcome": "mature_horizon_missing", "menu_issues": issue}
        return row

    realized = ("annual_return", "loss", "below_20", "worst_day", "max_drawdown", "volatility")

    def outcome(row: dict[str, Any]) -> dict[str, Any]:
        if row["menu"] == "example" and row["month"] == "2024-08":
            row = {**row, **dict.fromkeys(realized), "realized_status": "mature_horizon_missing"}
        return row

    _rewrite(directory, "origins.parquet", origins)
    _rewrite(directory, "outcomes.parquet", outcome)
    summary = report.write_report(directory).summary
    assert summary["panel"]["realized_mask"] == [True, False, False]
    facts = summary["panel"]["menus"]["example"]
    assert (facts["complete"], facts["mature_missing"], facts["unexplained_missing"]) == (1, 1, 0)
    assert [r["month"] for r in facts["missing_reasons"]] == ["2024-08"]
    gates = {g["gate"]: g for g in summary["panel"]["coverage_gates"]}
    assert (
        gates["example_completeness"]["value"] == 0.5 and not gates["example_completeness"]["met"]
    )
    assert gates["tsp_completeness"]["value"] == 1.0
    july = {
        (r["ceiling_id"], r["role"]): r["annual_return"]
        for r in _outcome_rows(directory)
        if (r["profile"], r["seed"], r["menu"], r["month"]) == ("stage-1", P, "tsp", "2024-07")
        and r["allowance"] in (None, 0.00025)
    }
    hand = sum(july[(c, "R+D")] - july[(c, "R")] for c in CELLS) / 3  # TSP's 2024-08 is dropped
    found = summary["primary"]["realized"]["annual_return"]["by_menu"]["tsp"]
    assert found["n"] == 1 and found["value"] == pytest.approx(hand, abs=1e-15)
    assert summary["labels"]["menus"]["tsp"]["disjoint_panel"] == 1


def _stage_1_cell(directory: Path, menu: str, ceiling: str, month: str = "2024-07") -> str:
    """The primary-seed cell key of one menu, ceiling and month in a run's search.parquet."""
    (key,) = {
        row["cell_key"]
        for row in pq.read_table(directory / "search.parquet").to_pylist()
        if row["kind"] == "cell"
        and (row["menu"], row["ceiling_id"], row["month"], row["seed"]) == (menu, ceiling, month, P)
    }
    return key


def _fail_cell(directory: Path, key: str) -> None:
    """Mark one cell a failed arm in search.parquet and drop its outcome rows (as a run would)."""

    def search(row: dict[str, Any]) -> dict[str, Any]:
        if row["kind"] == "cell" and row["cell_key"] == key:
            return {
                **row,
                "cell_status": "failed_arm",
                "error": "undefined_measure",
                "error_detail": "R+D: injected",
            }
        return row

    _rewrite(directory, "search.parquet", search)
    _rewrite(directory, "outcomes.parquet", lambda row: None if row["cell_key"] == key else row)


def _table_headers(lines: list[str]) -> list[int]:
    """The line index of every markdown table's header row."""
    return [
        i
        for i, line in enumerate(lines)
        if line.startswith("| ") and (i == 0 or not lines[i - 1].startswith("|"))
    ]


def _between(text: str, first: str, last: str | None) -> list[str]:
    block = text.split(first, 1)[1]
    return (block if last is None else block.split(last, 1)[0]).split("\n")


def test_a_failed_stage_1_cell_invalidates_and_labels_every_statistic_descriptive(
    run_root: Path, tmp_path: Path
) -> None:
    """R25: the cell stays listed in the denominator; statistics over the rest are descriptive."""
    directory = _copy(run_root, tmp_path)
    key = _stage_1_cell(directory, "example", "x50")
    _fail_cell(directory, key)
    written = report.write_report(directory)
    summary = written.summary
    assert any(r.startswith("no_failed_cells") for r in summary["validity"]["reasons"])
    denominator = summary["denominator"]
    assert denominator["failed"] == 1 and denominator["cells"] == 36
    assert denominator["failed_cells"] == [
        {
            "cell_key": key,
            "cell_status": "failed_arm",
            "error": "undefined_measure",
            "error_detail": "R+D: injected",
        }
    ]
    note = summary["validity"]["descriptive_only"]
    assert note is not None and "1 failed" in note and "denominator" in note
    for menu, label in summary["labels"]["menus"].items():
        assert label["conditional"] == "inconclusive/invalid", menu
        assert label["realized"] == "inconclusive/invalid", menu
        assert label["sensitivity"] == "inconclusive/invalid", menu
        assert label["score_change"] == "inconclusive/invalid", menu
        assert label["branch"] is None and label["positive_conditional_model_evidence"] is False
    assert summary["confirmed_worthwhile_benefit"] is False and summary["stage_2"]["run"] is False
    # the failed cell is masked: two of the three origins remain in example's x50 cell
    assert summary["primary"]["replay"]["utility"]["by_cell"]["example"]["x50"]["n"] == 2
    lines = written.markdown.split("\n")
    label = f"_{note}_"
    text = written.markdown
    blocks = [
        _between(text, "## R against the return-agnostic references", "## Cost"),
        _between(text, "## Every threshold result", "## Protocol readings"),
        _between(text, "## Appendix A", None),
    ]
    for block in blocks:
        headers = _table_headers(block)
        assert headers
        for i in headers:
            assert block[i - 2] == label and block[i - 1] == "", block[i]
    assert label not in _between(text, "## Cost", "## Every threshold result")
    assert lines.count(label) >= 20


def test_a_clean_run_carries_no_descriptive_label(written: report.Report) -> None:
    assert written.summary["validity"]["descriptive_only"] is None
    assert "Descriptive only" not in written.markdown
    checks = {c["check"]: c for c in written.summary["validity"]["checks"]}
    for name in (
        "no_failed_cells",
        "frozen_schedule",
        "denominator_agrees_with_manifest",
        "investigation_digest",
        "investigation_ranges",
    ):
        assert checks[name]["met"] is True, name
    for name in ("coefficients", "lookback", "budget"):
        assert checks[f"sensitivity_{name}_cells"]["met"] is True, name


def test_a_failed_sensitivity_cell_makes_its_setting_unavailable_and_the_run_invalid(
    run_root: Path, tmp_path: Path
) -> None:
    """Each sensitivity profile is validated against its own frozen schedule (Codex P1-2)."""
    directory = _copy(run_root, tmp_path)
    budget = directory / "sensitivity-budget"
    _fail_cell(budget, _stage_1_cell(budget, "tsp", "x25", "2024-08"))
    lookback = directory / "sensitivity-lookback"
    lost = _stage_1_cell(lookback, "example", "x100", "2024-09")
    _rewrite(
        lookback,
        "search.parquet",
        lambda row: None if row["kind"] == "cell" and row["cell_key"] == lost else row,
    )
    summary = report.write_report(directory).summary
    checks = {c["check"]: c for c in summary["validity"]["checks"]}
    assert checks["sensitivity_budget_cells"]["met"] is False
    assert "budget-x2: 1 failed" in checks["sensitivity_budget_cells"]["detail"]
    assert checks["sensitivity_lookback_cells"]["met"] is False
    assert "lookback-252: 1 missing" in checks["sensitivity_lookback_cells"]["detail"]
    assert checks["sensitivity_coefficients_cells"]["met"] is True
    assert summary["labels"]["experiment"] == "inconclusive/invalid"
    for menu in ("tsp", "example"):
        settings = summary["sensitivities"]["menus"][menu]["settings"]
        for name in ("budget-x2", "lookback-252"):
            entry = settings[name]
            assert entry["available"] is False, (menu, name)
            assert entry["descriptive_only"] is True and entry["replay"] is not None
            assert entry["disclosure"]["available"] is False
            assert entry["unavailable"], (menu, name)
        assert settings["coefficients-70-20-10"]["available"] is True
        assert settings["coefficients-70-20-10"]["descriptive_only"] is False


def _drop_outcomes(directory: Path, key: str, role: str, allowance: float | None) -> None:
    _rewrite(
        directory,
        "outcomes.parquet",
        lambda row: (
            None
            if (row["cell_key"], row["role"], row["allowance"]) == (key, role, allowance)
            else row
        ),
    )


def test_a_missing_zero_cap_output_alone_never_blocks_in_any_profile(
    run_root: Path, tmp_path: Path
) -> None:
    """R26: the 0 bp control is not required; a missing required arm still invalidates."""
    directory = _copy(run_root, tmp_path)
    budget = directory / "sensitivity-budget"
    stage1_key = _stage_1_cell(directory, "tsp", "x25", "2024-08")
    budget_key = _stage_1_cell(budget, "tsp", "x25", "2024-08")
    _drop_outcomes(directory, stage1_key, "R+D", 0.0)
    _drop_outcomes(budget, budget_key, "R+D", 0.0)
    checks = {c["check"]: c for c in report.write_report(directory).summary["validity"]["checks"]}
    assert checks["paired_arms"]["met"] is True
    assert checks["sensitivity_budget_cells"]["met"] is True
    _drop_outcomes(directory, stage1_key, "R+D", 0.0005)
    _drop_outcomes(budget, budget_key, "R", None)
    checks = {c["check"]: c for c in report.write_report(directory).summary["validity"]["checks"]}
    assert checks["paired_arms"]["met"] is False
    assert checks["sensitivity_budget_cells"]["met"] is False
    assert (
        "budget-x2: 1 completed cells lack a paired arm"
        in (checks["sensitivity_budget_cells"]["detail"])
    )


def test_a_completed_cell_missing_its_primary_outcome_labels_the_tables_descriptive(
    run_root: Path, tmp_path: Path
) -> None:
    directory = _copy(run_root, tmp_path)
    key = _stage_1_cell(directory, "example", "x50")
    _drop_outcomes(directory, key, "R+D", 0.00025)
    summary = report.write_report(directory).summary
    assert any(r.startswith("paired_arms") for r in summary["validity"]["reasons"])
    note = summary["validity"]["descriptive_only"]
    assert note is not None and "lack a required paired outcome" in note and key in note
    assert summary["validity"]["unpaired_cells"] == [key]


def test_the_manifest_and_the_report_count_failures_alike(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A lookback-252 profile with training-ineligible cells and one failed cell: the runner's
    manifest and the report give the same denominator, failed count and rate (Fable Imp 2)."""
    drop = pd.bdate_range("2024-06-03", "2024-07-15")

    def gap(series: dict[str, pd.Series]) -> dict[str, pd.Series]:
        series["TSP-C"] = series["TSP-C"].drop(index=drop, errors="ignore")
        return series

    records = make_records(gap)
    settings = make_settings(records, months=("2024-08", "2024-08"), seeds=(P,))
    run_experiment(tmp_path, records, settings=settings, run_id="f8")
    original = search.run_arm

    def failing(shared: Any, label: str, **kwargs: Any) -> Any:
        arm = original(shared, label, **kwargs)
        if label == "R+D" and shared.fraction == 0.5 and shared.model.menu == "example":
            return replace(arm, error=search.UNDEFINED_MEASURE, error_detail="injected")
        return arm

    monkeypatch.setattr(search, "run_arm", failing)
    result = run_experiment(
        tmp_path, records, settings=settings, run_id="f8", sensitivity="lookback"
    )
    manifest = json.loads((result.directory / "manifest.json").read_text())
    recorded = manifest["status"]["denominator"]
    counted = report.denominator(report.read_run(result.directory), "lookback-252")
    hand = {
        "cells": 6,
        "training_ineligible_excluded": 3,  # tsp: 31 incomplete rows of 252 (< 227 complete)
        "failure_denominator": 3,
        "failed": 1,
        "failure_rate": 1 / 3,
        "by_status": {"failed_arm": 1, "ok": 2, "training_ineligible": 3},
    }
    for name, value in hand.items():
        assert recorded[name] == counted[name] == value, name


def _uncertainty_tables() -> dict[str, Any]:
    """A summary skeleton whose every estimate names where it sits (`tag`)."""

    def table(tag: str) -> dict[str, Any]:
        menus = ("tsp", "example")
        return {
            "by_menu": {m: {"tag": f"{tag}/{m}"} for m in menus},
            "by_cell": {m: {c: {"tag": f"{tag}/{m}/{c}"} for c in CELLS} for m in menus},
        }

    return {
        "primary": {
            "replay": {f: table(f"replay.{f}") for f in ("bad", "typical", "good", "utility")},
            "realized": {
                f: table(f"realized.{f}") for f in ("annual_return", "loss", "max_drawdown")
            },
        },
        "realized": {"quantile_contrasts_rd_minus_r": {"typical": table("median")}},
    }


@pytest.mark.parametrize(
    ("key", "location", "tag", "said"),
    [
        ("replay.bad", "menu", "replay.bad/example", "R+D minus R paired replay bad"),
        ("replay.typical", "menu", "replay.typical/example", "R+D minus R paired replay typical"),
        ("replay.good", "menu", "replay.good/example", "R+D minus R paired replay good"),
        ("replay.cell_u", "x50", "replay.utility/example/x50", "R+D minus R paired replay utility"),
        ("harm.u", "menu", "replay.utility/example", "R+D minus R paired replay utility"),
        (
            "guard.mean_loss",
            "x25",
            "realized.annual_return/example/x25",
            "R+D minus R paired realized annual_return",
        ),
        (
            "guard.loss_frequency",
            "x100",
            "realized.loss/example/x100",
            "R+D minus R paired realized loss",
        ),
        (
            "guard.drawdown",
            "x50",
            "realized.max_drawdown/example/x50",
            "R+D minus R paired realized max_drawdown (improvement: R minus R+D)",
        ),
        (
            "guard.median_loss",
            "x25",
            "median/example/x25",
            "R+D minus R median annual return across origins",
        ),
    ],
)
def test_each_material_harm_key_carries_the_uncertainty_of_its_own_figure(
    key: str, location: str, tag: str, said: str
) -> None:
    """Fable Minor 4: every key `_harm_record` maps finds its table entry at its location."""
    criterion = evidence.Criterion("example", "dimension", key, location, "test", 0.1, 0.0, False)
    record = report._harm_record(criterion, _uncertainty_tables())
    assert record["uncertainty"] == {"tag": tag}
    assert record["uncertainty_of"] == said
    assert (record["key"], record["location"], record["passed"]) == (key, location, False)


def test_every_material_harm_key_has_an_uncertainty_test() -> None:
    tested = {
        "replay.bad",
        "replay.typical",
        "replay.good",
        "replay.cell_u",
        "harm.u",
        "guard.mean_loss",
        "guard.loss_frequency",
        "guard.drawdown",
        "guard.median_loss",
    }
    verdict = _decide(
        example=_menu(
            "example",
            replay=_replay(4 * BP, bad=-6 * BP, typical=-11 * BP, good=-21 * BP),
            realized=_realized(cells=dict.fromkeys(CELLS, RealizedCell(1.0, 1.0, 1.0, 1.0))),
        )
    )
    keys = {c.key for c in verdict.criteria if c.key in evidence._HARM_KEYS}
    keys |= {c.key for c in verdict.criteria if c.key.startswith("guard.")}
    assert keys == tested
