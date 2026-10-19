"""The experiment runner and its artifacts (protocol 4-9; plan 6b.5).

Fixtures are synthetic (tests/research/fixtures.py, shared with the report tests): seeded
total-return indices (tests/research/helpers.py) on the installed XNYS sessions for a three-fund
"tsp" menu (caps .60) and a five-fund "example" menu (caps .25), D* 2025-09-30, a 2y lookback and
reduced search budgets (`Settings` makes the reductions explicit and the manifest lists them).
Origins 2024-07 and 2024-08 are mature, 2024-09 is immature. Runs go to `tmp_path`; nothing
reads the mirror. Expectations come from oracles written here: hashlib for keys and order, hand
counts for the denominator, explicit day-by-day compounding of production's bootstrap paths for
bank figures, hand formulas for DR², `mu_s'w`, turnover, L1 and the forecast-error correlation.
Production's origin model, bootstrap index and realized horizon are the pinned references
(tested in 6.3), not the code under test.
"""

from __future__ import annotations

import hashlib
import io
import json
import math
import shutil
import sys
from collections.abc import Sequence
from dataclasses import replace
from datetime import date
from pathlib import Path
from types import ModuleType
from typing import Any

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from portfoliosight.engine.ranges import bootstrap_index
from portfoliosight.research import (
    evaluate,
    experiment,
    harness,
    outcomes,
    report,
    runner,
    search,
    selection,
)
from portfoliosight.research.experiment import (
    Investigation,
    Limits,
    Settings,
    build_schedule,
)
from portfoliosight.research.outcomes import OUTCOMES_SCHEMA, TEST_SEEDS, EvaluationTask
from portfoliosight.research.runner import Breach, Monitor, Usage
from portfoliosight.research.search import Budget
from portfoliosight.research.selection import (
    ALLOWANCES,
    LOCKED_SCHEMA,
    SEARCH_SCHEMA,
    LockedFileChanged,
)
from tests.research.fixtures import (
    D_STAR,
    INVESTIGATION_COLUMNS,
    MENUS,
    PREFIX,
    PRIMARY,
    PROVENANCE,
    ROOT,
    SECOND,
    TINY,
    investigation_tensor,
    load_module,
    make_inputs,
    make_records,
    make_settings,
    run_experiment,
    scale_price,
    tensor_bytes,
    xnys_sessions,
)
from tests.research.helpers import random_indices, record

ROLES_STAGE_1 = {"R", "R+D", "R:native", "R+D:native", "frontier", "mdp", "min_variance"}
ROLES_STAGE_1 |= {"equal_weight", "pool_max_dr2"}

# ------------------------------------------------------------------------------------ fixtures


def _rows(directory: Path, name: str) -> list[dict[str, Any]]:
    return pq.read_table(directory / name).to_pylist()


def _hex(value: Any) -> Any:
    """Floats as hex (exact, NaN-safe), lists element by element, anything else as it is."""
    if isinstance(value, float):
        return value.hex()
    if isinstance(value, list):
        return [_hex(item) for item in value]
    return value


def _bytes(table: pa.Table) -> bytes:
    buffer = io.BytesIO()
    pq.write_table(table, buffer)
    return buffer.getvalue()


def _frame(directory: Path, name: str) -> pd.DataFrame:
    return pq.read_table(directory / name).to_pandas()


def _resources(directory: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in (directory / "resources.jsonl").read_text().splitlines()]


@pytest.fixture(scope="module")
def stage1(tmp_path_factory: pytest.TempPathFactory) -> experiment.RunResult:
    """Stage 1 on three origins, two seeds, both menus, in this process."""
    return run_experiment(tmp_path_factory.mktemp("stage1"), run_id="main")


@pytest.fixture(scope="module")
def schedule() -> experiment.Schedule:
    records = make_records()
    run_profiles = experiment.profiles(1, None, make_settings(records))
    return build_schedule(
        make_inputs(records, Path("/nonexistent")), make_settings(records), run_profiles
    )


@pytest.fixture(scope="module")
def models() -> dict[tuple[str, str], evaluate.OriginModel]:
    records = make_records()
    ledger = harness.build_ledger(records, xnys_sessions(), D_STAR, MENUS, "2y")
    return {
        (month, menu): evaluate.origin_model(records, ledger, month, menu)
        for month in ("2024-07", "2024-08", "2024-09")
        for menu in MENUS
    }


# --------------------------------------------------------------------------- keys and order


def test_cell_key_is_compact_json_and_hashed_as_utf8() -> None:
    key = selection.cell_key("tsp", date(2024, 3, 28), "x25", 20261013)
    assert key == '["tsp","2024-03-28","x25",20261013]'
    hand = hashlib.sha256(b'["tsp","2024-03-28","x25",20261013]').hexdigest()
    spec = next(iter(_spec_list()))
    assert spec.sha256 == hashlib.sha256(spec.key.encode("utf-8")).hexdigest()
    assert len(hand) == 64


def _spec_list() -> list[selection.CellSpec]:
    return [
        selection.CellSpec(
            "stage-1", "tsp", "2024-03", date(2024, 3, 28), "5y", "x25", 0.25, 20261013,
            ("x25",), 1 / 3, '["tsp","2024-03-28","x25",20261013]',
            hashlib.sha256(b'["tsp","2024-03-28","x25",20261013]').hexdigest(),
        )
    ]  # fmt: skip


def test_cells_sort_by_key_digest_and_alternate_arms_by_parity(
    schedule: experiment.Schedule,
) -> None:
    origins = {"2024-07": "2024-07-31", "2024-08": "2024-08-30", "2024-09": "2024-09-30"}
    for menu in MENUS:
        cells = [cell for cell in schedule.cells if cell.menu == menu]
        keys = [
            f'["{menu}","{origins[month]}","{ceiling}",{seed}]'
            for month in origins
            for ceiling in ("x25", "x50", "x100")
            for seed in (PRIMARY, SECOND)
        ]
        hand = sorted(keys, key=lambda key: (hashlib.sha256(key.encode()).hexdigest(), key))
        assert [cell.key for cell in cells] == hand
        assert [cell.menu_index for cell in cells] == list(range(len(hand)))
        orders = [cell.arm_order for cell in cells]
        assert orders == [("R", "R+D") if i % 2 == 0 else ("R+D", "R") for i in range(len(hand))]
        first = sum(order[0] == "R" for order in orders)
        assert abs(first - (len(orders) - first)) <= 1
    assert [cell.order for cell in schedule.cells] == list(range(len(schedule.cells)))
    assert [cell.menu for cell in schedule.cells[:18]] == ["tsp"] * 18


def test_sensitivity_origins_are_the_floor_indices() -> None:
    months = [f"m{i:03d}" for i in range(100)]
    assert experiment.sensitivity_months(months) == tuple(
        f"m{i:03d}" for i in (0, 19, 39, 59, 79, 99)
    )
    assert experiment.sensitivity_months(months[:7]) == tuple(
        f"m{i:03d}" for i in (0, 1, 2, 3, 4, 6)
    )
    assert experiment.sensitivity_months(["a", "b", "c"]) == ("a", "b", "c")
    assert experiment.sensitivity_months(["a"]) == ("a",)


def test_profiles_of_each_stage_and_sensitivity() -> None:
    settings = Settings()
    (base,) = experiment.profiles(1, None, settings)
    assert (base.arms, base.seeds, base.origins) == (("R", "R+D"), search.PATH_SEEDS, "scheduled")
    assert base.coefficients == (0.60, 0.30, 0.10) and base.budget == Budget()
    heavy, light = experiment.profiles(1, "coefficients", settings)
    assert (heavy.coefficients, light.coefficients) == ((0.70, 0.20, 0.10), (0.50, 0.35, 0.15))
    assert heavy.name == "coefficients-70-20-10" and light.name == "coefficients-50-35-15"
    (lookback,) = experiment.profiles(1, "lookback", settings)
    assert lookback.lookback == "1y" and lookback.name == "lookback-252"
    (doubled,) = experiment.profiles(1, "budget", settings)
    assert doubled.budget == Budget(points=2048, starts=6, calls=768, maxiter=768)
    for profile in (heavy, light, lookback, doubled):
        assert profile.seeds == (20261013,) and profile.origins == "sensitivity"
    (stage2,) = experiment.profiles(2, None, settings)
    assert stage2.arms == ("R", "R+D", "R+E") and stage2.seeds == search.PATH_SEEDS
    assert experiment.arm_order(stage2.arms, 4) == ("R+D", "R+E", "R")
    with pytest.raises(ValueError):
        experiment.profiles(2, "budget", settings)
    with pytest.raises(ValueError):
        experiment.profiles(1, "allowance", settings)


# ------------------------------------------------------------------------------- denominator


def test_the_frozen_denominator_counts_distinct_cells_once_with_alias_weights(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Example with four funds capped at .25: only equal weight fits, so its span collapses."""
    records = make_records()
    menus = {"tsp": MENUS["tsp"], "example": ("X", "Y", "Z", "V")}
    inputs = make_inputs(records, Path("/nonexistent"))
    inputs = replace(inputs, data=replace(inputs.data, menus=menus))
    settings = make_settings(records, seeds=search.PATH_SEEDS)
    original = search.risk_ceilings

    def unsolved(model, caps):  # minimum variance fails at one origin of one menu
        if model.menu == "tsp" and model.month == "2024-08":
            raise search.SolveError("injected")
        return original(model, caps)

    monkeypatch.setattr(search, "risk_ceilings", unsolved)
    schedule = build_schedule(inputs, settings, experiment.profiles(1, None, settings))
    counted = experiment.denominator(schedule)
    # tsp: 3 origins x 3 ceilings x 5 seeds (2024-08's 15 preset failed); example: 3 x 1 x 5
    assert counted["cells"] == 45 + 15 == len(schedule.cells)
    assert counted["by_profile_menu"] == {"stage-1/example": 15, "stage-1/tsp": 45}
    assert counted["preset_failures"] == 15
    assert counted["collapsed_aliases"] == 2 * 15
    example = [cell for cell in schedule.cells if cell.menu == "example"]
    assert {cell.ceiling_id for cell in example} == {"x100"}
    assert {cell.stands_for for cell in example} == {("x25", "x50", "x100")}
    assert {cell.weight for cell in example} == {1.0}
    failed = [cell for cell in schedule.cells if cell.preset is not None]
    assert {(cell.menu, cell.month, cell.preset) for cell in failed} == {
        ("tsp", "2024-08", "min_variance_unsolved")
    }
    assert sorted(cell.ceiling_id for cell in failed) == sorted(["x25", "x50", "x100"] * 5)
    keys = [entry["key"] + "|" + entry["profile"] for entry in counted["listing"]]
    hand = hashlib.sha256(json.dumps(keys, separators=(",", ":")).encode()).hexdigest()
    assert counted["cells_sha256"] == hand


def test_a_forced_failed_cell_stays_in_the_denominator(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    records = make_records()
    settings = make_settings(records, months=("2024-08", "2024-08"), seeds=(PRIMARY,))
    original = search.run_arm

    def failing(shared, label, **kwargs):
        arm = original(shared, label, **kwargs)
        if label == "R+D" and shared.fraction == 0.5 and shared.model.menu == "example":
            return replace(arm, error=search.UNDEFINED_MEASURE, error_detail="injected")
        return arm

    monkeypatch.setattr(search, "run_arm", failing)
    result = run_experiment(tmp_path, records, settings=settings, run_id="failed")
    assert result.status == "complete" and result.cells == 6
    assert result.outcome["failed"] == 1 and result.outcome["completed"] == 5
    assert result.outcome["failure_rate"] == 1 / 6
    assert result.outcome["failure_rate_above_limit"] is True
    cells = _frame(result.directory, "search.parquet").query("kind == 'cell'")
    failed = cells[cells["cell_status"] == search.FAILED_ARM]
    assert list(zip(failed["menu"], failed["ceiling_id"], strict=True)) == [("example", "x50")]
    locked = _frame(result.directory, "locked.parquet")
    assert not ((locked["menu"] == "example") & (locked["ceiling_id"] == "x50")).any()
    assert len(set(zip(locked["menu"], locked["ceiling_id"], strict=True))) == 5
    manifest = json.loads((result.directory / "manifest.json").read_text())
    assert manifest["status"]["denominator"]["by_status"] == {"failed_arm": 1, "ok": 5}
    assert manifest["denominator"]["cells"] == 6


# ---------------------------------------------------------------------------- the artifacts


def test_the_protocol_9_artifacts_exist_with_their_schemas(stage1: experiment.RunResult) -> None:
    directory = stage1.directory
    assert directory == directory.parent.parent / PREFIX / "main"
    names = sorted(path.name for path in directory.iterdir())
    assert names == [
        "locked.parquet", "manifest.json", "origins.parquet", "outcomes.parquet",
        "resources.jsonl", "search.parquet",
    ]  # fmt: skip
    assert pq.read_schema(directory / "search.parquet") == SEARCH_SCHEMA
    assert pq.read_schema(directory / "locked.parquet").remove_metadata() == LOCKED_SCHEMA
    assert pq.read_schema(directory / "outcomes.parquet").remove_metadata() == OUTCOMES_SCHEMA
    columns = pq.read_schema(directory / "origins.parquet").names
    assert columns[: len(harness.LEDGER_COLUMNS)] == list(harness.LEDGER_COLUMNS)
    origins = _rows(directory, "origins.parquet")
    months = harness.ledger_frame(
        harness.build_ledger(make_records(), xnys_sessions(), D_STAR, MENUS, "2y")
    )
    assert len(origins) == len(months)  # every enumerated month, both menus
    scheduled = [row for row in origins if row["scheduled"]]
    assert sorted({row["month"] for row in scheduled}) == ["2024-07", "2024-08", "2024-09"]
    assert all(row["shrinkage"] > 0 and row["ceiling_x50"] > 0 for row in scheduled)
    assert all(row["shrinkage"] is None for row in origins if not row["scheduled"])
    kinds = {entry["kind"] for entry in _resources(directory)}
    assert {"run", "cell", "lock", "evaluation"} <= kinds


def test_reviews_are_recorded_verbatim_by_the_run_and_the_report(tmp_path: Path) -> None:
    """R28: `reviews` holds each entry exactly as given, never interpreted; default empty."""
    records = make_records()
    settings = make_settings(records, months=("2024-08", "2024-08"), seeds=(PRIMARY,))
    given = ("Codex (GPT-6), 2026-10-19: Stage 1 code at HEAD", "  owner; scope: none  ")
    result = run_experiment(tmp_path, records, settings=settings, run_id="rv", reviews=given)
    path = result.directory / "manifest.json"
    assert json.loads(path.read_text())["reviews"] == list(given)
    later = "Fable 5.1, 2026-10-20, results"
    written = report.write_report(result.directory, allow_incomplete=True, reviews=(later,))
    assert json.loads(path.read_text())["reviews"] == [*given, later]
    assert later in written.summary["scope"]["review"]
    report.write_report(result.directory, allow_incomplete=True, reviews=(later,))
    assert json.loads(path.read_text())["reviews"] == [*given, later]  # recorded once


def test_the_manifest_records_provenance_and_claims_no_review(
    stage1: experiment.RunResult,
) -> None:
    directory = stage1.directory
    manifest = json.loads((directory / "manifest.json").read_text())
    assert manifest["reviews"] == []
    assert manifest["protocol"]["sha256"] == PROVENANCE.protocol_sha256
    assert manifest["protocol"]["prefix"] == PREFIX
    assert manifest["code"] == {"head": "a" * 40, "dirty": False}
    assert manifest["status"]["state"] == "complete" and manifest["status"]["breach"] is None
    assert manifest["definitions"]["max_drawdown"].startswith("max_t 1 - W_t / max(1,")
    assert (
        manifest["definitions"]["volatility"]
        == "sqrt(252) * std(ddof=1) of the 252 daily portfolio returns"
    )
    assert set(manifest["deviations_from_protocol"]) == {
        "lookback", "seeds", "budget", "months", "investigation",
    }  # fmt: skip
    assert manifest["preference"]["u_allowances_evaluated"] == [0.00025, 0.0, 0.0005, 0.001]
    assert manifest["search"]["independent_bank_seeds"] == list(TEST_SEEDS)
    assert manifest["limits"]["cpu_hours"] == 36.0 and not manifest["limits"]["cpu_hours_amendment"]
    assert (
        manifest["limits"]["arm_seconds"] == 120.0 and manifest["limits"]["rss_bytes"] == 4 * 2**30
    )
    assert manifest["menus"] == {
        "tsp": {"funds": list(MENUS["tsp"]), "cap": 0.6},
        "example": {"funds": list(MENUS["example"]), "cap": 0.25},
    }
    assert manifest["denominator"]["cells"] == 36 == stage1.cells
    assert manifest["data"]["snapshot_manifest_sha256"] == "f" * 64
    for name in ("search.parquet", "locked.parquet", "outcomes.parquet", "origins.parquet"):
        digest = hashlib.sha256((directory / name).read_bytes()).hexdigest()
        assert manifest["artifacts"][name] == digest
    assert manifest["lock"]["sha256"] == manifest["artifacts"]["locked.parquet"]


def _by(rows: Sequence[dict[str, Any]], key: str) -> dict[Any, list[dict[str, Any]]]:
    groups: dict[Any, list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault(row[key], []).append(row)
    return groups


def test_search_rows_flag_the_union_winners(stage1: experiment.RunResult) -> None:
    rows = _rows(stage1.directory, "search.parquet")
    cells = [row for row in rows if row["kind"] == "cell"]
    assert [row["schedule_order"] for row in cells] == list(range(36))
    assert {row["cell_status"] for row in cells} == {"ok"}
    for key, group in _by(rows, "cell_key").items():
        candidates = [row for row in group if row["kind"] == "candidate"]
        pool = [row for row in candidates if row["in_pool"]]
        assert sum(row["w_r"] for row in pool) == 1 and sum(row["stage_b"] for row in pool) == 1
        for row in pool:
            if row["w_r"] or row["stage_b"]:
                assert row["admissible"] and not row["dominated"], key
        assert [row["row"] for row in candidates] == list(range(len(candidates)))
        assert not any(row["in_pool"] for row in candidates if row["status"] != "ok")
        assert sorted(row["arm"] for row in group if row["kind"] == "arm") == ["R", "R+D"]
        assert sum(row["kind"] == "start" for row in group) == 2 * TINY.starts
        (top,) = [row for row in group if row["kind"] == "cell"]
        assert top["shrinkage"] > 0 and isinstance(top["reference"], str)


def test_locked_roles_carry_exact_figures_dr2_and_the_forecast(
    stage1: experiment.RunResult, models: dict
) -> None:
    locked = _rows(stage1.directory, "locked.parquet")
    anchors = [row for row in _rows(stage1.directory, "search.parquet") if row["kind"] == "anchor"]
    for key, group in _by(locked, "cell_key").items():
        assert {row["role"] for row in group} == ROLES_STAGE_1
        rd = [row for row in group if row["role"] == "R+D"]
        assert sorted(row["allowance"] for row in rd) == sorted(ALLOWANCES)
        for row in rd:
            assert row["admissible"]
            assert -1e-12 <= row["sacrifice"] <= row["allowance"] + 1e-12
        named = {row["name"]: row["weights"] for row in anchors if row["cell_key"] == key}
        ceiling = group[0]["ceiling_id"]
        roles = {row["role"]: row["weights"] for row in group}
        assert roles["frontier"] == named[f"frontier_{ceiling}"]
        assert roles["mdp"] == named[f"mdp_{ceiling}"]
        assert roles["min_variance"] == named["min_variance"]
    for row in locked[::7]:
        model = models[(row["month"], row["menu"])]
        w = row["weights"]
        forecast = sum(m * x for m, x in zip(model.mu_s.tolist(), w, strict=True))
        assert row["expected_return"] == pytest.approx(forecast, abs=1e-15)
        sigma, cov = model.moments.sigma.tolist(), model.moments.cov.tolist()
        num = sum(x * s for x, s in zip(w, sigma, strict=True)) ** 2
        den = sum(w[i] * cov[i][j] * w[j] for i in range(len(w)) for j in range(len(w)))
        assert row["dr2"] == pytest.approx(num / den, rel=1e-12)
        assert row["model_inputs_sha256"] == model.inputs_sha256


def _explicit_years(model: evaluate.OriginModel, seed: int, w: np.ndarray) -> np.ndarray:
    index = bootstrap_index(len(model.sample), seed=seed)
    daily = model.sample @ w
    growth = 1.0 + daily - daily.mean() + float(model.mu_s @ w) / 252
    return np.prod(growth[index], axis=1) - 1.0


def test_outcomes_pool_five_new_banks_and_match_explicit_compounding(
    stage1: experiment.RunResult, models: dict
) -> None:
    written = _rows(stage1.directory, "outcomes.parquet")
    locked = {row["selection_id"]: row for row in _rows(stage1.directory, "locked.parquet")}
    assert len(written) == len(locked)
    assert {row["test_paths"] for row in written} == {10_000}
    assert {row["train_paths"] for row in written} == {2_000}
    assert all(row["bank_seeds"] == list(TEST_SEEDS) for row in written)
    assert all(row["primary"] == (row["seed"] == PRIMARY) for row in written)
    ok = [row for row in written if row["test_status"] == "ok"]
    assert all(row["test_es_25"] <= row["test_bad"] for row in ok)
    for row in written:
        before = locked[row["selection_id"]]
        if before["status"] == "ok":
            for name in ("train_bad", "train_typical", "train_good", "train_es_25"):
                assert row[name] == before[name]
    row = next(r for r in ok if r["role"] == "R+D" and r["allowance"] == ALLOWANCES[0])
    model = models[(row["month"], row["menu"])]
    w = np.asarray(row["weights"])
    years = np.concatenate([_explicit_years(model, seed, w) for seed in TEST_SEEDS])
    ordered = np.sort(years)
    for name, q in (("bad", 0.025), ("typical", 0.5), ("good", 0.975)):
        position = q * (len(ordered) - 1)
        low = int(math.floor(position))
        value = ordered[low] + (position - low) * (ordered[low + 1] - ordered[low])
        assert row[f"test_{name}"] == pytest.approx(value, abs=1e-12)
    assert row["test_es_25"] == pytest.approx(ordered[:250].mean(), abs=1e-12)
    first = _explicit_years(model, TEST_SEEDS[0], w)
    assert row["bank_bad"][0] == pytest.approx(np.percentile(first, 2.5), abs=1e-12)
    assert row["test_utility"] == pytest.approx(
        0.6 * row["test_bad"] + 0.3 * row["test_typical"] + 0.1 * row["test_good"], abs=1e-15
    )


def test_an_infeasible_reference_is_flagged_beside_its_evaluated_figures(
    stage1: experiment.RunResult,
) -> None:
    """Fable Minor 1: an equal-weight reference above its ceiling keeps its locked status
    `infeasible`; the row's evaluated figures carry `reference_infeasible`, so it never reads
    `status: infeasible` with `train_status: ok` and nothing else."""
    rows = _rows(stage1.directory, "outcomes.parquet")
    flagged = [row for row in rows if row["reference_infeasible"]]
    assert flagged and {row["role"] for row in flagged} == {"equal_weight"}
    for row in rows:
        assert row["reference_infeasible"] is (row["status"] == search.INFEASIBLE)
    for row in flagged:
        assert row["train_status"] == "ok" and row["within_ceiling"] is False
        assert row["risk"] > row["ceiling"]


def test_realized_legs_follow_the_ledger_and_hand_compounding(
    stage1: experiment.RunResult,
) -> None:
    written = _rows(stage1.directory, "outcomes.parquet")
    immature = [row for row in written if row["month"] == "2024-09"]
    assert {row["realized_status"] for row in immature} == {harness.IMMATURE}
    assert all(row["annual_return"] is None and row["forecast_error"] is None for row in immature)
    mature = [row for row in written if row["month"] != "2024-09"]
    assert {row["realized_status"] for row in mature} == {harness.COMPLETE}
    records = make_records()
    ledger = harness.build_ledger(records, xnys_sessions(), D_STAR, MENUS, "2y")
    row = next(r for r in mature if r["role"] == "R")
    horizon = evaluate.realized_horizon(records, ledger, row["month"], row["menu"])
    assert horizon.returns is not None
    wealth, peak, drawdown = 1.0, 1.0, 0.0
    for day in horizon.returns.tolist():
        wealth *= 1.0 + sum(x * r for x, r in zip(row["weights"], day, strict=True))
        peak = max(peak, wealth)
        drawdown = max(drawdown, 1.0 - wealth / peak)
    assert row["annual_return"] == pytest.approx(wealth - 1.0, abs=1e-12)
    assert row["max_drawdown"] == pytest.approx(drawdown, abs=1e-12)
    assert row["horizon_start"] == horizon.days[0] and row["horizon_end"] == horizon.days[-1]
    y, f = row["annual_return"], row["test_bad"]
    assert row["test_pinball_bad"] == pytest.approx((0.025 - (y < f)) * (y - f), abs=1e-15)
    assert row["test_at_or_below_bad"] == (y <= f)


def test_cross_row_columns_pair_seeds_and_adjacent_origins(stage1: experiment.RunResult) -> None:
    written = _rows(stage1.directory, "outcomes.parquet")

    def key(row: dict[str, Any], **changes: Any) -> tuple:
        row = {**row, **changes}
        return (
            row["menu"],
            row["month"],
            row["ceiling_id"],
            row["seed"],
            row["role"],
            row["allowance"],
        )

    index = {key(row): row for row in written}
    previous = {"2024-07": None, "2024-08": "2024-07", "2024-09": "2024-08"}
    for row in written:
        annual = row["annual_return"]
        if annual is not None:
            assert row["forecast_error"] == annual - row["expected_return"]
        if row["role"] == "R+D" and annual is not None:
            base = index[key(row, role="R", allowance=None)]
            assert row["paired_role"] == "R"
            assert row["paired_realized_difference"] == annual - base["annual_return"]
        other = SECOND if row["seed"] == PRIMARY else PRIMARY
        twin = index[key(row, seed=other)]
        assert row["seed_l1_seeds"] == [other]
        hand = sum(abs(a - b) for a, b in zip(row["weights"], twin["weights"], strict=True))
        assert row["seed_l1"][0] == pytest.approx(hand, abs=1e-15)
        assert row["stands_for"] == [row["ceiling_id"]]
        month = previous[row["month"]]
        if month is None:
            assert row["turnover_prev"] == [None]
        else:
            before = index[key(row, month=month)]
            hand = 0.5 * sum(
                abs(a - b) for a, b in zip(row["weights"], before["weights"], strict=True)
            )
            assert row["turnover_prev"][0] == pytest.approx(hand, abs=1e-15)


def test_forecast_error_diagnostic_matches_hand_values() -> None:
    rows = []
    errors = {"2020-01": 0.02, "2020-02": -0.01, "2020-03": 0.05}
    paired = {"2020-01": -0.004, "2020-02": 0.001, "2020-03": -0.006}
    for month in errors:
        common = {"profile": "stage-1", "seed": PRIMARY, "realized_status": "complete",
                  "menu": "tsp", "month": month, "stands_for": ["x25"]}  # fmt: skip
        rows.append({**common, "role": "R", "allowance": None, "forecast_error": errors[month],
                     "paired_realized_difference": None})  # fmt: skip
        rows.append({**common, "role": "R+D", "allowance": ALLOWANCES[0], "forecast_error": 0.0,
                     "paired_realized_difference": paired[month]})  # fmt: skip
    rows.append({**rows[0], "seed": SECOND, "forecast_error": 9.0})  # another seed: ignored
    x, y = [0.02, -0.01, 0.05], [-0.004, 0.001, -0.006]
    mx, my = sum(x) / 3, sum(y) / 3
    cov = sum((a - mx) * (b - my) for a, b in zip(x, y, strict=True))
    hand = cov / math.sqrt(sum((a - mx) ** 2 for a in x) * sum((b - my) ** 2 for b in y))
    result = outcomes.forecast_error_diagnostic(pd.DataFrame(rows))
    assert result.to_dict("records") == [
        {"menu": "tsp", "ceiling_id": "x25", "n": 3, "correlation": pytest.approx(hand), "sign": -1}
    ]


# ---------------------------------------------------------------------- lock before evaluate


def test_the_lock_is_written_before_any_independent_draw_or_realized_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    records = make_records()
    settings = make_settings(records, months=("2024-08", "2024-08"), seeds=(PRIMARY,))
    events: list[tuple[str, Any, bool]] = []
    directory = tmp_path / "out" / PREFIX / "lock"
    original_bank, original_horizon, original_arm = (
        evaluate.bank,
        experiment.realized_horizon,
        search.run_arm,
    )

    def spy_bank(model: Any, seed: int, engine: Any = "replay") -> Any:
        events.append(("bank", seed, (directory / "locked.parquet").exists()))
        return original_bank(model, seed, engine)

    def spy_horizon(*args):
        events.append(("horizon", args[2], (directory / "locked.parquet").exists()))
        return original_horizon(*args)

    def spy_arm(shared, label, **kwargs):
        events.append(("arm", (shared.model.menu, shared.fraction, label), False))
        return original_arm(shared, label, **kwargs)

    monkeypatch.setattr(evaluate, "bank", spy_bank)
    monkeypatch.setattr(experiment, "realized_horizon", spy_horizon)
    monkeypatch.setattr(search, "run_arm", spy_arm)
    result = run_experiment(tmp_path, records, settings=settings, run_id="lock")
    assert result.directory == directory and result.status == "complete"
    draws = [event for event in events if event[0] in ("bank", "horizon")]
    assert draws and all(locked for _, _, locked in draws)
    assert {seed for kind, seed, _ in draws if kind == "bank"} == {PRIMARY, *TEST_SEEDS}
    kinds = [entry["kind"] for entry in _resources(directory)]
    assert kinds.index("lock") < kinds.index("evaluation")
    assert max(i for i, kind in enumerate(kinds) if kind == "cell") < kinds.index("lock")
    # each cell ran its arms in its scheduled order
    schedule_rows = _frame(directory, "search.parquet").query("kind == 'cell'")
    arms = [event[1] for event in events if event[0] == "arm"]
    expected = [
        (menu, fraction, label)
        for menu, fraction, order in zip(
            schedule_rows["menu"],
            schedule_rows["fraction"],
            schedule_rows["arm_order"],
            strict=True,
        )
        for label in order
    ]
    assert arms == expected


def test_evaluation_reads_only_the_locked_rows(
    stage1: experiment.RunResult, models: dict, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(*args, **kwargs):
        raise AssertionError("the evaluation touched the search")

    for name in ("prepare", "run_arm", "combine", "search_cell"):
        monkeypatch.setattr(search, name, refuse)
    monkeypatch.setattr(selection.preference, "select", refuse)
    for name in ("choose", "lock_rows", "search_table"):
        monkeypatch.setattr(selection, name, refuse)
    copy = tmp_path / "locked.parquet"
    shutil.copyfile(stage1.directory / "locked.parquet", copy)
    digest = hashlib.sha256(copy.read_bytes()).hexdigest()
    groups = dict(outcomes.evaluation_groups(selection.read_locked(copy, digest)))
    assert list(groups) == [
        ("stage-1", menu, month) for menu in MENUS for month in ("2024-07", "2024-08", "2024-09")
    ]
    records = make_records()
    ledger = harness.build_ledger(records, xnys_sessions(), D_STAR, MENUS, "2y")
    horizon = evaluate.realized_horizon(records, ledger, "2024-08", "tsp")
    rows = tuple(groups[("stage-1", "tsp", "2024-08")])
    model = models[("2024-08", "tsp")]
    task = EvaluationTask("stage-1", "tsp", "2024-08", model, horizon, rows, digest)
    evaluated = outcomes.evaluate_group(task).to_pylist()
    written = {row["selection_id"]: row for row in _rows(stage1.directory, "outcomes.parquet")}
    assert [row["selection_id"] for row in evaluated] == [row["selection_id"] for row in rows]
    for row in evaluated:
        for name in ("test_bad", "test_es_25", "train_typical", "annual_return"):
            assert float(row[name]).hex() == float(written[row["selection_id"]][name]).hex()
    other = groups[("stage-1", "example", "2024-08")][:1]
    with pytest.raises(ValueError, match="holds locked rows of"):
        outcomes.evaluate_group(replace(task, rows=(*rows, *other)))
    buffer = io.BytesIO()
    pq.write_table(pq.read_table(copy).slice(1), buffer)  # one selection fewer
    copy.write_bytes(buffer.getvalue())
    with pytest.raises(LockedFileChanged):  # the runner reads and verifies the file once
        selection.read_locked(copy, digest)


def test_selection_and_search_never_import_the_evaluation_side() -> None:
    """The pre-lock modules cannot reach realized returns or the post-lock evaluation."""
    import ast
    import subprocess

    forbidden_modules = {"portfoliosight.research.outcomes"}
    forbidden_names = {"Horizon", "realized", "realized_horizon", "path_metrics", "outcomes"}
    for name in ("search", "selection"):
        tree = ast.parse((ROOT / "portfoliosight" / "research" / f"{name}.py").read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert not {alias.name for alias in node.names} & forbidden_modules, name
            if isinstance(node, ast.ImportFrom):
                assert node.module not in forbidden_modules, (name, node.module)
                assert not {alias.name for alias in node.names} & forbidden_names, (
                    name,
                    node.module,
                )
            if isinstance(node, ast.Attribute):
                assert node.attr not in forbidden_names - {"outcomes"}, (name, node.attr)
    loaded = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys, portfoliosight.research.search, portfoliosight.research.selection; "
            "print('portfoliosight.research.outcomes' in sys.modules)",
        ],
        capture_output=True,
        text=True,
        check=True,
        cwd=ROOT,
    )
    assert loaded.stdout.strip() == "False"


# -------------------------------------------------------------------------------- isolation


def test_arm_order_and_cache_isolation_leave_a_cell_unchanged(
    schedule: experiment.Schedule,
) -> None:
    records = make_records()
    settings = make_settings(records)
    cell = next(c for c in schedule.cells if c.menu == "tsp" and c.ceiling_id == "x50")
    facts = schedule.origins[(cell.lookback, cell.month, cell.menu)]
    task = runner.SearchTask(
        cell, schedule.profile("stage-1"), facts.model, facts.ceilings,
        schedule.caps(settings, "tsp"), 120.0,
    )  # fmt: skip
    forward = runner.run_search_task(replace(task, cell=replace(cell, arm_order=("R", "R+D"))))
    backward = runner.run_search_task(replace(task, cell=replace(cell, arm_order=("R+D", "R"))))
    assert forward.table is not None and backward.table is not None
    assert _bytes(forward.table.drop_columns(["arm_order"])) == _bytes(
        backward.table.drop_columns(["arm_order"])
    )
    assert _bytes(forward.locked) == _bytes(backward.locked)
    assert forward.locked.num_rows == len(ROLES_STAGE_1) + 3  # R+D at four allowances
    preloaded = {arm["preloaded_rows"] for arm in forward.resources["arms"]}
    shared = {
        tuple(row["weights"])
        for row in forward.table.to_pylist()
        if row["kind"] == "candidate" and row["source"] != "local"
    }
    assert preloaded == {len(shared)}  # each arm's cache holds the shared archive only
    assert [arm["arm"] for arm in backward.resources["arms"]] == ["R+D", "R"]


# --------------------------------------------------------------------------------- stop rules


class _Meter:
    """A meter that reports ``after`` once it has been read ``calls`` times."""

    def __init__(self, after: Usage, calls: int) -> None:
        self.after, self.calls, self.read = after, calls, 0

    def usage(self, pids: Sequence[int]) -> Usage:
        self.read += 1
        return self.after if self.read > self.calls else Usage(1.0, 2**20, 2**20)


def test_the_monitor_names_each_aggregate_breach() -> None:
    def check(usage: Usage, before: float = 0.0) -> Breach | None:
        return Monitor(4 * 2**30, 24.0, _Meter(usage, 0), before).check([])

    assert check(Usage(3600.0, 2**30, 2**31)) is None
    assert check(Usage(1.0, 2**20, 4 * 2**30 + 1)) == Breach(
        "aggregate_peak_rss", 4 * 2**30, 4 * 2**30 + 1
    )
    assert check(Usage(1.0, 4 * 2**30 + 1, 2**20)).rule == "aggregate_peak_rss"  # type: ignore[union-attr]
    late = check(Usage(86_400.5, 2**20, 2**20))
    assert late is not None and (late.rule, late.limit, late.value) == (
        "cpu_hours",
        86_400.0,
        86_400.5,
    )
    spent = check(Usage(10.0, 2**20, 2**20), before=86_395.0)  # a sensitivity after Stage 1
    assert spent is not None and spent.rule == "cpu_hours" and spent.value == 86_405.0


def test_limits_hold_six_workers_and_a_recorded_cpu_amendment() -> None:
    with pytest.raises(ValueError, match="at most 6"):
        Limits(workers=7)
    with pytest.raises(ValueError, match="amendment"):
        Limits(cpu_hours=48.0)
    assert Limits(cpu_hours=48.0, cpu_amended=True).cpu_hours == 48.0


def _stopped(result: experiment.RunResult, rule: str, evaluated: bool = False) -> pd.DataFrame:
    assert (
        result.status == "incomplete" and result.breach is not None and result.breach.rule == rule
    )
    manifest = json.loads((result.directory / "manifest.json").read_text())
    assert manifest["status"]["state"] == "incomplete"
    assert manifest["status"]["breach"]["rule"] == rule
    assert manifest["execution"]["breach"]["rule"] == rule
    assert any(
        entry["kind"] == "breach" and entry["rule"] == rule
        for entry in _resources(result.directory)
    )
    assert (result.directory / "outcomes.parquet").exists() == evaluated
    cells = _frame(result.directory, "search.parquet").query("kind == 'cell'")
    assert len(cells) == result.cells  # every scheduled cell keeps a row
    return cells


@pytest.mark.parametrize(
    ("usage", "rule"),
    [
        (Usage(1.0, 2**20, 5 * 2**30), "aggregate_peak_rss"),
        (Usage(129_601.0, 2**20, 2**20), "cpu_hours"),
    ],
)
def test_an_aggregate_breach_stops_the_run_and_keeps_partial_artifacts(
    tmp_path: Path, usage: Usage, rule: str
) -> None:
    records = make_records()
    settings = make_settings(records, months=("2024-08", "2024-08"), seeds=(PRIMARY,))
    meter = _Meter(usage, calls=1)  # the check before the first cell passes, the next breaches
    result = run_experiment(tmp_path, records, settings=settings, run_id=rule, meter=meter)
    cells = _stopped(result, rule)
    assert list(cells["cell_status"]) == ["ok"] + ["unattempted"] * 5
    assert not (result.directory / "locked.parquet").exists()  # nothing is locked or evaluated


def test_an_arm_past_its_ceiling_stops_the_run(tmp_path: Path) -> None:
    records = make_records()
    settings = make_settings(records, months=("2024-08", "2024-08"), seeds=(PRIMARY,))
    ticks = iter(range(0, 10**9, 200))
    result = run_experiment(
        tmp_path, records, settings=settings, run_id="arm", clock=lambda: float(next(ticks))
    )
    cells = _stopped(result, "arm_seconds")
    assert list(cells["cell_status"]) == ["resource_breach"] + ["unattempted"] * 5
    assert result.breach is not None and result.breach.value == 200.0
    arm = _breached_arm(result, cells, "measured 200.0 s > 120.0 s")
    # measured after the arm finished: every start and its native selection are kept
    assert arm["calls"] > 0 and arm["native_selection"] is not None
    starts = _rows(result.directory, "search.parquet")
    assert sum(row["kind"] == "start" for row in starts) == TINY.starts


def _breached_arm(result: experiment.RunResult, cells: pd.DataFrame, said: str) -> dict[str, Any]:
    """The stopped cell keeps the shared archive and the breached arm's attempts so far, its
    starts, raw statuses and counters (Codex P2-5); returns the arm row."""
    key = cells["cell_key"].iloc[0]
    rows = [row for row in _rows(result.directory, "search.parquet") if row["cell_key"] == key]
    label = list(cells["arm_order"].iloc[0])[0]
    (arm,) = [row for row in rows if row["kind"] == "arm"]
    assert arm["arm"] == label
    assert (arm["error"], arm["failure"]) == ("arm_seconds", "resource_breach")
    assert said in arm["error_detail"] and "attempt rows so far are kept" in arm["error_detail"]
    (cell,) = [row for row in rows if row["kind"] == "cell"]
    assert (cell["cell_status"], cell["error"]) == ("resource_breach", "arm_seconds")
    assert cell["error_detail"].startswith(f"{label}: ")
    candidates = [row for row in rows if row["kind"] == "candidate"]
    assert sum(row["source"] == "broad" for row in candidates) == TINY.points
    assert sum(row["source"] == "anchor" for row in candidates) >= 2
    local = [row for row in candidates if row["source"] == "local"]
    assert {row["arm"] for row in local} <= {label} and arm["calls"] == len(local)
    assert arm["evaluations"] == sum(not row["cached"] for row in local)
    record = next(
        r for r in _resources(result.directory) if r["kind"] == "cell" and r["cell_key"] == key
    )
    (timing,) = record["arms"]
    assert (timing["arm"], timing["stopped"], timing["calls"]) == (label, "arm_seconds", len(local))
    return arm


def test_the_alarm_stops_an_arm_that_overruns_inside_the_solver(tmp_path: Path) -> None:
    records = make_records()
    settings = make_settings(records, months=("2024-08", "2024-08"), seeds=(PRIMARY,))
    limits = Limits(workers=0, arm_seconds=1e-4)
    result = run_experiment(
        tmp_path, records, settings=settings, limits=limits, run_id="alarm", clock=lambda: 0.0
    )
    cells = _stopped(result, "arm_seconds")
    assert cells["cell_status"].iloc[0] == "resource_breach"
    assert "alarm" in result.breach.detail  # type: ignore[union-attr]
    arm = _breached_arm(result, cells, "the alarm stopped the arm inside its search")
    assert arm["native_selection"] is None  # stopped before it


def test_a_breach_while_evaluating_keeps_the_lock_and_partial_outcomes(tmp_path: Path) -> None:
    records = make_records()
    settings = make_settings(records, months=("2024-08", "2024-08"), seeds=(PRIMARY,))
    # reads: 1 before the search and 6 after its cells pass, 1 before evaluating passes, and the
    # read after the first (profile, menu, origin) group reports 5 GiB
    meter = _Meter(Usage(1.0, 2**20, 5 * 2**30), calls=8)
    result = run_experiment(tmp_path, records, settings=settings, run_id="late", meter=meter)
    cells = _stopped(result, "aggregate_peak_rss", evaluated=True)
    assert set(cells["cell_status"]) == {"ok"}
    manifest = json.loads((result.directory / "manifest.json").read_text())
    assert manifest["lock"]["sha256"] == manifest["artifacts"]["locked.parquet"]
    assert manifest["status"]["denominator"]["completed"] == 6
    locked = _rows(result.directory, "locked.parquet")
    written = _rows(result.directory, "outcomes.parquet")
    assert {row["menu"] for row in locked} == {"tsp", "example"}
    assert [row["selection_id"] for row in written] == [
        row["selection_id"] for row in locked if row["menu"] == "tsp"
    ]  # the first group only
    kinds = [entry["kind"] for entry in _resources(result.directory)]
    assert kinds.count("evaluation") == 1 and kinds.index("lock") < kinds.index("breach")


def test_each_arm_records_its_native_selection_time(stage1: experiment.RunResult) -> None:
    """Fable Minor 2: an arm's native selection is a timed sub-part of its wall time."""
    for entry in _resources(stage1.directory):
        if entry["kind"] != "cell":
            continue
        for arm in entry["arms"]:
            assert arm["native_selection"] > 0.0
            parts = sum(arm.get(name, 0.0) for name in runner.ARM_PARTS)
            assert arm["solver"] == pytest.approx(arm["wall"] - parts, abs=1e-12)
            assert runner.ARM_PARTS == ("return_evaluation", "score", "native_selection")


def test_the_probe_counts_a_nested_call_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """Measure scoring inside the native selection is scoring, not selection."""
    monkeypatch.setattr(search._Measures, "value", lambda self, name, weights: 0.0)

    def native(shared: Any, measure: Any, rows: Any) -> tuple[None, None]:
        search._Measures.value(None, "dr2", ())  # type: ignore[arg-type]
        return None, None

    monkeypatch.setattr(search, "_native", native)
    ticks = iter(range(100))
    with runner.Probe(clock=lambda: float(next(ticks))) as probe:
        search._native(None, None, ())  # type: ignore[arg-type]
    # native from 0 to 3, its scoring from 1 to 2
    assert probe.seconds == {"score": 1.0, "native_selection": 2.0}
    assert probe.calls == {"score": 1, "native_selection": 1}


def test_the_arm_alarm_interrupts_python_code() -> None:
    with pytest.raises(runner.ArmTimeLimit), runner.arm_alarm(0.01):
        while True:
            sum(range(1000))
    with runner.arm_alarm(5.0):
        pass  # cancelled on exit: nothing rings later


# ----------------------------------------------------------------------------------- preflight


def test_preflight_refusals_leave_no_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    records = make_records()
    settings = make_settings(records)
    wrong = replace(settings, investigation=replace(settings.investigation, digest="0" * 64))
    with pytest.raises(experiment.InvestigationMismatch, match="digest"):
        run_experiment(tmp_path, records, settings=wrong)
    with pytest.raises(experiment.DirtyRepository):
        experiment.run(
            make_inputs(records, tmp_path),
            replace(PROVENANCE, dirty=("x.py",)),
            tmp_path / "out",
            settings=settings,
            limits=Limits(workers=0),
        )
    with pytest.raises(experiment.ScheduleTooLarge):
        build_schedule(
            make_inputs(records, tmp_path),
            settings,
            experiment.profiles(1, None, settings),
            max_origins=2,
        )
    monkeypatch.setenv("OMP_NUM_THREADS", "4")
    with pytest.raises(experiment.BlasThreads, match="OMP_NUM_THREADS"):
        run_experiment(tmp_path, records, settings=settings)
    assert not (tmp_path / "out").exists()


def test_preflight_reproduces_the_investigation_tensor_ranges(tmp_path: Path) -> None:
    """R17 and the Codex note: the saved tensor's recorded ranges are recomputed one mix at a
    time; above 1e-12 the run is refused before any directory, within it the check is recorded."""
    records = make_records()
    settings = make_settings(records, months=("2024-08", "2024-08"), seeds=(PRIMARY,))
    inputs = make_inputs(records, tmp_path)
    raw = inputs.data.tensors[search.TSP_INVESTIGATION_TENSOR]
    found = experiment.check_investigation(inputs, settings.investigation)
    ranges = found["ranges"]
    assert found["reproduced"] == settings.investigation.digest
    assert ranges["columns"] == [0, 1] and ranges["mixes"] == 2 * (1 + 3)  # frontier + levels
    assert 0.0 <= ranges["max_abs_discrepancy"] <= 1e-12 == ranges["tolerance"]
    assert ranges["moments_max_abs_discrepancy"] == 0.0  # the same production fit
    assert ranges["tensor"] == search.TSP_INVESTIGATION_TENSOR
    assert ranges["tensor_sha256"] == hashlib.sha256(raw).hexdigest()
    off = investigation_tensor(records)
    off["ladder"]["range"]["good"][1][2] += 1e-9
    with pytest.raises(
        experiment.InvestigationRangesMismatch, match="at ladder column 1 level 2 good"
    ):
        run_experiment(tmp_path, records, settings=settings, tensor=json.dumps(off).encode())
    other = tensor_bytes(records, lookback="2y")  # a build of another sample
    with pytest.raises(experiment.InvestigationMismatch, match="sample digest"):
        run_experiment(tmp_path, records, settings=settings, tensor=other)
    bare = replace(inputs, data=replace(inputs.data, tensors={}))
    with pytest.raises(experiment.InvestigationMismatch, match="no investigation tensor"):
        experiment.run(bare, PROVENANCE, tmp_path / "out", settings=settings)
    assert not (tmp_path / "out").exists()
    for bad_value in (math.nan, math.inf):  # a non-finite figure is never outvoted by later ones
        broken = investigation_tensor(records)
        broken["frontier"]["range"]["bad"][0] = bad_value
        with pytest.raises(
            experiment.InvestigationRangesMismatch, match="at frontier column 0 bad"
        ):
            run_experiment(tmp_path, records, settings=settings, tensor=json.dumps(broken).encode())
    near = investigation_tensor(records)
    near["frontier"]["range"]["bad"][0] += 1e-13  # within the per-mix tolerance
    result = run_experiment(
        tmp_path, records, settings=settings, tensor=json.dumps(near).encode(), run_id="near"
    )
    recorded = json.loads((result.directory / "manifest.json").read_text())["data"]
    gap = recorded["investigation"]["ranges"]["max_abs_discrepancy"]
    assert 5e-14 < gap <= 1e-12
    assert recorded["investigation"]["ranges"]["worst"] == "frontier column 0 bad"
    assert recorded["investigation"]["columns"] == [0, 1]


def test_output_must_avoid_the_snapshot_mirror_and_tracked_repository(tmp_path: Path) -> None:
    inputs = make_inputs(make_records(), tmp_path)
    repo = tmp_path / "repo"
    provenance = replace(
        PROVENANCE,
        worktrees=(repo,),
        git_dirs=(repo / ".git",),
        ignored=lambda path: ".omx" in path.parts,
    )
    for refused in (
        tmp_path / "snapshot" / "out",
        tmp_path / "mirror" / "x",
        repo / ".git" / "x",
        repo / "results",
    ):
        with pytest.raises(experiment.UnsafeOutput):
            experiment.guard_output(refused, inputs, provenance)
    for allowed in (repo / ".omx" / "research", tmp_path / "elsewhere"):
        assert experiment.guard_output(allowed, inputs, provenance) == allowed.resolve()


# -------------------------------------------------------------------------- determinism


def test_any_worker_count_writes_byte_identical_artifacts(tmp_path: Path) -> None:
    records = make_records()
    settings = make_settings(records, months=("2024-08", "2024-09"), seeds=(PRIMARY,))
    results = {
        workers: run_experiment(
            tmp_path,
            records,
            settings=settings,
            limits=Limits(workers=workers),
            run_id=f"d{workers}",
            out=tmp_path / str(workers),
        )  # fmt: skip
        for workers in (0, 1, 2, 4)
    }
    for name in ("search.parquet", "locked.parquet", "outcomes.parquet", "origins.parquet"):
        digests = {
            hashlib.sha256((r.directory / name).read_bytes()).hexdigest() for r in results.values()
        }
        assert len(digests) == 1, name
    manifests = []
    for result in results.values():
        manifest = json.loads((result.directory / "manifest.json").read_text())
        for volatile in ("run", "execution", "limits", "lock"):
            manifest.pop(volatile)
        manifests.append(manifest)
    assert manifests[0] == manifests[1] == manifests[2]
    limits = {
        n: json.loads((r.directory / "manifest.json").read_text())["limits"]
        for n, r in results.items()
    }
    assert limits[2]["process_model"] == limits[1]["process_model"] == experiment.PROCESS_MODEL
    assert experiment.PROCESS_MODEL == (
        "1 coordinator (serial preparation, no concurrent compute) + <=6 compute workers"
    )
    assert limits[0]["process_model"].startswith("in-process")
    workers = [entry for entry in _resources(results[2].directory) if entry["kind"] == "worker"]
    assert len(workers) == 2 and all(w["env"]["OPENBLAS_NUM_THREADS"] == "1" for w in workers)
    pids = {entry["pid"] for entry in _resources(results[2].directory) if entry["kind"] == "cell"}
    assert pids <= {w["pid"] for w in workers}
    for result in results.values():
        orders = [
            entry["order"] for entry in _resources(result.directory) if entry["kind"] == "cell"
        ]
        assert sorted(orders) == list(range(12))


# ---------------------------------------------------------------------- leakage (A-SE-32)


def test_prices_after_the_origin_change_only_the_realized_legs(tmp_path: Path) -> None:
    """A-SE-32: the runner's selections and predictions ignore every price after the origin."""
    month = ("2024-08", "2024-08")
    base_records = make_records()
    after = make_records(
        scale_price("2024-10-15", 1.5, "X", "TSP-C"), scale_price("2025-01-15", 0.8, "Y", "TSP-F")
    )
    before = make_records(scale_price("2024-03-15", 1.5, "X", "TSP-C"))
    runs = {}
    for name, records in (("base", base_records), ("after", after), ("before", before)):
        settings = make_settings(records, months=month, seeds=(PRIMARY,))
        runs[name] = run_experiment(
            tmp_path / name, records, settings=settings, run_id=name
        ).directory
    locked = {name: (runs[name] / "locked.parquet").read_bytes() for name in runs}
    assert (
        locked["after"] == locked["base"]
    )  # w_R and every selection at every allowance, bit for bit
    predicted = [c for c in OUTCOMES_SCHEMA.names if c.startswith(("train_", "test_", "bank_"))]
    predicted = [
        c for c in predicted if "pinball" not in c and "at_or_below" not in c and c != "test_pit"
    ]
    tables = {name: pq.read_table(runs[name] / "outcomes.parquet") for name in runs}
    keyed = ["selection_id", "weights", *predicted]
    # byte-identical: written to parquet, every float is compared bit for bit, NaN included
    assert _bytes(tables["after"].select(keyed)) == _bytes(tables["base"].select(keyed))
    for column in predicted:
        for a, b in zip(
            tables["after"][column].to_pylist(), tables["base"][column].to_pylist(), strict=True
        ):
            assert _hex(a) == _hex(b), column
    for menu in MENUS:  # the mutation reaches both menus' horizons
        rows = {
            name: [row for row in tables[name].to_pylist() if row["menu"] == menu]
            for name in ("after", "base")
        }
        assert all(
            a["annual_return"] != b["annual_return"]
            for a, b in zip(rows["after"], rows["base"], strict=True)
        )
    for menu in MENUS:  # a mutation on or before the origin moves w_R in both menus
        chosen = {
            name: [
                row["weights"]
                for row in _rows(runs[name], "locked.parquet")
                if row["menu"] == menu and row["role"] == "R"
            ]
            for name in ("base", "before")
        }
        assert chosen["base"] != chosen["before"]


# ------------------------------------------------------------------- sensitivities, stage 2


@pytest.fixture(scope="module")
def small(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, experiment.RunResult]:
    tmp = tmp_path_factory.mktemp("small")
    records = make_records()
    settings = make_settings(records, months=("2024-08", "2024-09"), seeds=(PRIMARY, SECOND))
    return tmp, run_experiment(tmp, records, settings=settings, run_id="small")


def test_sensitivities_write_separate_artifacts_on_the_primary_seed(
    small: tuple[Path, experiment.RunResult],
) -> None:
    tmp, first = small
    records = make_records()
    settings = make_settings(records, months=("2024-08", "2024-09"), seeds=(PRIMARY, SECOND))
    stage_1_cpu = json.loads((first.directory / "manifest.json").read_text())["execution"][
        "cpu_seconds"
    ]
    spent = stage_1_cpu
    for name, profiles in (
        ("coefficients", {"coefficients-70-20-10", "coefficients-50-35-15"}),
        ("lookback", {"lookback-252"}),
        ("budget", {"budget-x2"}),
    ):
        result = run_experiment(tmp, records, settings=settings, run_id="small", sensitivity=name)
        assert result.directory == first.directory / f"sensitivity-{name}"
        manifest = json.loads((result.directory / "manifest.json").read_text())
        assert manifest["execution"]["cpu_before"] == pytest.approx(spent)
        spent += manifest["execution"]["cpu_seconds"]
        written = _frame(result.directory, "outcomes.parquet")
        assert set(written["profile"]) == profiles and set(written["seed"]) == {PRIMARY}
        assert set(written["month"]) == {"2024-08", "2024-09"}
        for profile in manifest["profiles"]:
            assert profile["seeds"] == [PRIMARY]
        if name == "coefficients":
            heavy = written[written["profile"] == "coefficients-70-20-10"]
            assert all(list(k) == [0.7, 0.2, 0.1] for k in heavy["coefficients"])
            assert heavy["test_utility"].tolist() == pytest.approx(
                (
                    0.7 * heavy["test_bad"] + 0.2 * heavy["test_typical"] + 0.1 * heavy["test_good"]
                ).tolist()
            )
        if name == "lookback":
            assert set(written["lookback"]) == {"1y"}
        if name == "budget":
            cells = _frame(result.directory, "search.parquet").query("kind == 'cell'")
            assert {json.loads(b)["points"] for b in cells["budget"]} == {16}
    with pytest.raises(experiment.Refused, match="exists"):
        run_experiment(tmp, records, settings=settings, run_id="small", sensitivity="budget")
    with pytest.raises(experiment.StageNotReady):
        run_experiment(tmp, records, settings=settings, run_id="missing", sensitivity="budget")
    with pytest.raises(experiment.StageNotReady, match="other code, data or settings"):
        run_experiment(
            tmp,
            records,
            settings=replace(settings, seeds=(PRIMARY,)),
            run_id="small",
            sensitivity="lookback",
        )


def test_stage_2_needs_the_report_and_an_amended_ceiling(
    small: tuple[Path, experiment.RunResult],
) -> None:
    tmp, first = small
    records = make_records()
    settings = make_settings(records, months=("2024-08", "2024-09"), seeds=(PRIMARY, SECOND))
    amended = Limits(workers=0, cpu_hours=1.0, cpu_amended=True)
    with pytest.raises(experiment.Refused, match="Stage 2 CPU ceiling"):
        run_experiment(tmp, records, settings=settings, run_id="small", stage=2)
    with pytest.raises(experiment.StageNotReady, match="stage_2.run"):
        run_experiment(tmp, records, settings=settings, limits=amended, run_id="small", stage=2)
    (first.directory / "summary.json").write_text(json.dumps({"stage_2": {"run": True}}))
    try:
        result = run_experiment(
            tmp, records, settings=settings, limits=amended, run_id="small", stage=2
        )
    finally:
        (first.directory / "summary.json").unlink()
    assert result.directory == first.directory / "stage-2" and result.status == "complete"
    locked = _frame(result.directory, "locked.parquet")
    assert {"R+E", "R+E:native", "pool_max_enb"} <= set(locked["role"])
    assert locked.loc[locked["role"] == "R+E", "enb"].notna().all()
    orders = _frame(result.directory, "search.parquet").query("kind == 'cell'")["arm_order"]
    assert {tuple(order) for order in orders} <= {
        ("R", "R+D", "R+E"),
        ("R+D", "R+E", "R"),
        ("R+E", "R", "R+D"),
    }
    manifest = json.loads((result.directory / "manifest.json").read_text())
    assert manifest["limits"]["cpu_hours_amendment"] is True and manifest["stage"] == 2


# ------------------------------------------------------------------------------ estimate, CLI


def test_an_estimate_that_crosses_a_ceiling_records_it_and_refuses(tmp_path: Path) -> None:
    records = make_records()
    with pytest.raises(experiment.Refused, match="crossed a ceiling"):
        experiment.estimate(
            make_inputs(records, tmp_path), PROVENANCE, tmp_path / "out",
            settings=make_settings(records), limits=Limits(workers=0), estimate_id="hot",
            meter=_Meter(Usage(129_601.0, 2**20, 2**20), calls=1),
        )  # fmt: skip
    directory = tmp_path / "out" / PREFIX / "estimates" / "hot"
    body = json.loads((directory / "estimate.json").read_text())
    assert body["complete"] is False and body["not_a_run"] is True
    assert body["breach"]["rule"] == "cpu_hours" and body["cells_done"] == 1
    lines = [json.loads(line) for line in (directory / "resources.jsonl").read_text().splitlines()]
    assert lines[-1]["kind"] == "breach" and lines[-1]["rule"] == "cpu_hours"


def test_estimate_projects_from_a_sample_and_is_not_a_run(tmp_path: Path) -> None:
    records = make_records()
    settings = make_settings(records)
    projection = experiment.estimate(
        make_inputs(records, tmp_path), PROVENANCE, tmp_path / "out", settings=settings,
        limits=Limits(workers=0), estimate_id="e1",
    )  # fmt: skip
    assert projection.directory == tmp_path / "out" / PREFIX / "estimates" / "e1"
    assert projection.sample_cells == 6  # three sensitivity origins x two menus x x50 x primary
    assert projection.stage_1_cells == {"tsp": 18, "example": 18}
    assert projection.total_cpu_hours == pytest.approx(sum(projection.parts.values()) / 3600)
    assert projection.fits and projection.cpu_hours_ceiling == 36.0
    body = json.loads((projection.directory / "estimate.json").read_text())
    assert body["not_a_run"] is True and body["sample"][0].startswith('["')
    lines = [
        json.loads(line)
        for line in (projection.directory / "resources.jsonl").read_text().splitlines()
    ]
    assert sum(entry["kind"] == "cell" for entry in lines) == 6
    assert lines[-1]["kind"] == "projection"
    assert not (tmp_path / "out" / PREFIX / "e1").exists()


@pytest.fixture(scope="module")
def cli() -> ModuleType:
    return load_module("backtest_ranges_experiment", ROOT / "scripts" / "backtest_ranges.py")


@pytest.fixture(scope="module")
def snapshot(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A freeze-script snapshot holding the protocol's 28 funds (synthetic prices)."""
    freeze = load_module("freeze_research_inputs", ROOT / "scripts" / "freeze_research_inputs.py")
    from tests.test_backtest_ranges import _snapshot

    funds = [*freeze.TSP_MENU, *freeze.EXAMPLE_MENU]
    drift_vol = {
        fund: (1e-4 * (1 + i % 5), 0.002 + 0.001 * (i % 7)) for i, fund in enumerate(funds)
    }
    sessions = xnys_sessions()
    days = pd.DatetimeIndex(
        sessions[(sessions >= pd.Timestamp("2022-01-03")) & (sessions <= pd.Timestamp(D_STAR))]
    )
    records = {fund: record(values) for fund, values in random_indices(days, drift_vol, 7).items()}
    tensor = tensor_bytes(records, funds=tuple(freeze.TSP_MENU))
    return _snapshot(tmp_path_factory.mktemp("cli"), freeze, records, D_STAR, tensor)


def _cli_settings(snapshot: Path) -> Settings:
    inputs = experiment.read_inputs(
        snapshot, lambda root: json.loads((root / "snapshot.json").read_text())
    )
    digest = search.production_sample_digest(
        inputs.data.records, inputs.data.menus["tsp"], "1y", D_STAR
    )
    investigation = Investigation(
        menu="tsp", lookback="1y", asof=D_STAR, digest=digest, columns=INVESTIGATION_COLUMNS
    )
    budget = Budget(points=8, starts=1, calls=24, maxiter=24)  # COBYLA needs N + 1 on 23 funds
    return Settings(
        lookback="2y", seeds=(PRIMARY,), budget=budget, months=("2024-08", "2024-08"),
        investigation=investigation,
    )  # fmt: skip


def test_cli_runs_and_estimates_the_experiment(
    cli: ModuleType, snapshot: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    monkeypatch.setattr(cli, "_settings", lambda: _cli_settings(snapshot))
    monkeypatch.setattr(cli, "_provenance", lambda: PROVENANCE)
    out = tmp_path / "out"
    argv = [
        "experiment",
        "run",
        "--snapshot",
        str(snapshot),
        "--out",
        str(out),
        "--workers",
        "0",
        "--run-id",
        "cli",
    ]
    reviews = ["--review", "Codex, 2026-10-19, code", "--review", "Fable, 2026-10-19"]
    assert cli.main([*argv, *reviews]) == 0
    printed = capsys.readouterr().out
    assert f"{out.resolve() / PREFIX / 'cli'}: complete" in printed
    assert "cells 6: completed 6, failed 0, incomplete 0" in printed
    manifest = json.loads((out.resolve() / PREFIX / "cli" / "manifest.json").read_text())
    assert manifest["reviews"] == ["Codex, 2026-10-19, code", "Fable, 2026-10-19"]
    assert cli.main([*argv[:-2], "--run-id", "cli", "--sensitivity", "budget"]) == 0
    argv = [
        "experiment",
        "estimate",
        "--snapshot",
        str(snapshot),
        "--out",
        str(out),
        "--workers",
        "0",
    ]
    assert cli.main([*argv, "--estimate-id", "e"]) == 0
    assert "CPU h ceiling" in capsys.readouterr().out


def test_cli_exit_codes_for_refusals(
    cli: ModuleType, snapshot: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    monkeypatch.setattr(cli, "_provenance", lambda: PROVENANCE)
    base = ["experiment", "run", "--snapshot", str(snapshot), "--workers", "0"]
    assert cli.main([*base, "--out", str(tmp_path / "out")]) == 7  # protocol digest: synthetic data
    assert "refused" in capsys.readouterr().err
    monkeypatch.setattr(cli, "_settings", lambda: _cli_settings(snapshot))
    assert cli.main([*base, "--out", str(snapshot / "inside")]) == 2
    assert (
        cli.main(["experiment", "run", "--snapshot", str(tmp_path), "--out", str(tmp_path / "o")])
        == 6
    )
    with pytest.raises(SystemExit) as stop:
        cli.main([*base, "--sensitivity", "allowance"])
    assert stop.value.code == 2
    assert not (tmp_path / "out").exists()


def test_cli_provenance_reads_head_and_git_ignore_rules(cli: ModuleType) -> None:
    """Read-only against this checkout: the protocol digest is that of the file at HEAD."""
    import subprocess

    provenance = cli._provenance()
    blob = subprocess.run(
        ["git", "-C", str(ROOT), "show", f"HEAD:{experiment.PROTOCOL_PATH}"],
        capture_output=True,
        check=True,
    ).stdout
    head = subprocess.run(
        ["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, check=True, text=True
    ).stdout.strip()
    assert provenance.head == head
    assert provenance.protocol_sha256 == hashlib.sha256(blob).hexdigest()
    assert "Status:" in provenance.protocol_status
    assert ROOT.resolve() in provenance.worktrees
    assert all(path.name == ".git" or path.is_dir() for path in provenance.git_dirs)
    assert cli._ignored(ROOT / ".omx" / "research" / "return-optimization" / "x")
    assert not cli._ignored(ROOT / "scripts" / "experiment-output")
    assert cli.DEFAULT_OUT == ROOT / ".omx" / "research" / "return-optimization"
