"""scripts/fixedrisk_geometry_check.py: the model-side geometry table (equal weight and the
unlimited top against the recorded limited ends) and the two pre-registered lists it must
reproduce, on made-up menus. No realized outcome, no data file."""

from __future__ import annotations

import importlib.util
import json
import math
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pandas as pd
import pytest

from portfoliosight.research.fixedrisk import analysis3 as A
from portfoliosight.research.fixedrisk import recipes3 as RC
from tests.research.fixedrisk.recipe_data import M12, MENU12, THREE_E, THREE_U, recorded

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "fixedrisk_geometry_check.py"
MONTH = "2010-01"


@pytest.fixture(scope="module")
def geo():
    spec = importlib.util.spec_from_file_location("fixedrisk_geometry_check_under_test", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _row(geo, m, month: str = MONTH) -> dict[str, Any]:
    return geo.geometry_row(month, m.mu_s, m.cov, m.lower, m.upper, recorded(m))


def test_geometry_row_flags_equal_weight_above_the_top(geo):
    row = _row(geo, THREE_E)
    assert row["e_excluded"] is True
    assert row["sigma_E"] == pytest.approx(0.1424, abs=5e-5)
    assert row["a_E"] > 1
    assert row["sigma_top"] == pytest.approx(0.05, abs=1e-12)
    assert row["sigma_top_rebuilt"] == pytest.approx(row["sigma_top"], abs=1e-12)


def test_geometry_row_keeps_equal_weight_inside_the_top(geo):
    row = _row(geo, M12)
    assert row["e_excluded"] is False
    assert 0 < row["a_E"] < 1


def test_geometry_row_lists_the_settings_above_the_unlimited_top(geo):
    row = _row(geo, THREE_U)
    assert row["u_excluded"] == [0.55, 0.70, 0.85]
    assert row["sigma_top_U"] == pytest.approx(0.10, abs=1e-12)
    assert row["sigma_top_U"] < row["sigma_top"]


def test_geometry_row_has_no_excluded_setting_when_the_unlimited_top_is_higher(geo):
    assert _row(geo, M12)["u_excluded"] == []


def _made_up(month: str, *, e: bool, a_e: float, u: list[float], u_top: float) -> dict[str, Any]:
    return {
        "month": month, "sigma_E": 0.1, "a_E": a_e, "sigma_top": 0.12,
        "sigma_top_rebuilt": 0.12 + 1e-9, "sigma_top_U": u_top, "e_excluded": e,
        "u_excluded": u,
    }  # fmt: skip


def test_summary_separates_eligible_months(geo):
    rows = pd.DataFrame(
        [
            _made_up("2009-01", e=True, a_e=1.4, u=[], u_top=0.2),  # excluded, eligible
            _made_up("2009-02", e=True, a_e=1.2, u=[0.85], u_top=0.1),  # excluded, not eligible
            _made_up("2009-03", e=False, a_e=0.5, u=[], u_top=0.2),
        ]
    )
    out = geo.summary(rows, ["2009-01", "2009-03"])
    assert out["e_excluded"] == ["2009-01"]
    assert out["e_excluded_other"] == ["2009-02"]
    assert out["u_excluded"] == [["2009-02", 0.85]]
    assert out["u_top_below_limited_top"] == ["2009-02"]
    assert out["a_E_median_eligible"] == pytest.approx(0.95)
    assert out["a_E_mean_eligible"] == pytest.approx(0.95)
    assert out["a_E_median_all"] == pytest.approx(1.2)
    assert out["largest_top_gap"] == pytest.approx(1e-9, abs=1e-12)
    assert (out["months"], out["eligible_months"]) == (3, 2)


def _expected_table() -> tuple[pd.DataFrame, list[str]]:
    """A table in which exactly the pre-registered months and cells are excluded."""
    months = sorted({*RC.E_EXCLUDED, "2008-09", "2010-07", "2011-01"})
    rows = []
    for k, month in enumerate(months):
        u = [rf for m, rf in RC.U_EXCLUDED if m == month]
        rows.append(_made_up(month, e=month in RC.E_EXCLUDED, a_e=0.5 + k / 100, u=u, u_top=0.2))
    return pd.DataFrame(rows), months


def _builder(table: pd.DataFrame, eligible: list[str]):
    def build(run_dir, snapshot, job):
        return table, eligible

    return build


ARGS = ["--run-dir", "R", "--snapshot", "S"]


def test_main_passes_and_prints_the_summary_when_the_lists_match(
    geo, monkeypatch, capsys, tmp_path
):
    table, months = _expected_table()
    monkeypatch.setattr(geo, "build_table", _builder(table, months))
    out = tmp_path / "geometry.csv"
    assert geo.main([*ARGS, "--out", str(out)]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["e_excluded"] == list(RC.E_EXCLUDED)
    assert printed["months"] == len(months)
    assert len(pd.read_csv(out)) == len(months)


def test_main_fails_when_the_lists_differ(geo, monkeypatch, capsys):
    table, months = _expected_table()
    table["e_excluded"] = False  # no excluded month at all
    monkeypatch.setattr(geo, "build_table", _builder(table, months))
    assert geo.main(ARGS) == 1
    assert "e_excluded" in capsys.readouterr().err


def test_main_fails_when_a_pre_registered_u_cell_is_missing(geo, monkeypatch, capsys):
    table, months = _expected_table()
    table["u_excluded"] = [[] for _ in range(len(table))]
    monkeypatch.setattr(geo, "build_table", _builder(table, months))
    assert geo.main(ARGS) == 1
    assert "2008-09" in capsys.readouterr().err


def test_main_fails_when_an_equal_weight_month_is_missing(geo, monkeypatch):
    table, months = _expected_table()
    table.loc[table["month"] == "2020-05", "e_excluded"] = False
    monkeypatch.setattr(geo, "build_table", _builder(table, months))
    assert geo.main(ARGS) == 1


def test_build_table_reads_every_scheduled_month_and_the_eligible_ones(geo, monkeypatch):
    rec = recorded(M12)
    schedule = ["2010-01", "2010-02", "2010-03"]
    parent = {"digest": "d", "jobs": {"job": {"menu": "m", "engine": "e"}}}
    parent["menus"] = {"m": {"schedule": schedule, "cscv": {"months": schedule[:2]}}}
    spec = SimpleNamespace(lower=tuple(M12.lower), upper=tuple(M12.upper))
    inputs = SimpleNamespace(menu=lambda name: spec)
    seen: list[Any] = []
    columns = pd.DataFrame(
        [
            {
                "month": month, "lookback": "3y", "r_fraction": a, "r": float(rec.r[j]),
                "sigma_min": rec.sigma_min, "sigma_top": rec.sigma_top,
                "w_F": list(rec.w_f[j]), "w_app_frontier": list(rec.w_app[j]),
            }
            for month in schedule
            for j, a in enumerate(A.RFS)
        ]
    )  # fmt: skip

    def v3_inputs(args):
        seen.append((args.run_dir, args.snapshot))
        return parent, inputs, ()

    def context(inp, menu, month):
        assert inp is inputs and menu is spec
        return MENU12

    def tables(job_dir, digest):
        seen.append((str(job_dir), digest))
        return {"columns": columns}

    monkeypatch.setattr(geo.cli, "_v3_inputs", v3_inputs)
    monkeypatch.setattr(geo.data, "origin_context", context)
    monkeypatch.setattr(geo.A, "load_tables", tables)
    table, eligible = geo.build_table("R", "S", "job")
    assert seen == [("R", "S"), (str(Path("R") / "job"), "d")]
    assert list(table["month"]) == schedule and eligible == schedule[:2]
    assert not any(table["e_excluded"])  # M12's equal weight is inside its top
    assert all(math.isfinite(x) for x in table["a_E"])
    assert np.allclose(table["sigma_top"], rec.sigma_top)
