"""v3 sizing: v2 references, the solver check's acceptance rule and the projection's rules."""

from __future__ import annotations

import pandas as pd
import pytest

from portfoliosight.research.fixedrisk import contracts as C
from portfoliosight.research.fixedrisk import sizing3 as S


def test_v2_task_seconds_reads_the_last_done_line(tmp_path):
    log = tmp_path / "progress.log"
    log.write_text(
        "2026 job research2003_replay start: 3 tasks\n"
        "2026 task research2003_2006-05_replay done 1367.7s cpu_total_h=3.7 failures=0 (1/3)\n"
        "2026 task research2003_2006-06_replay FAILED 10.0s cpu_total_h=3.8 failures=1 (1/3)\n"
        "2026 task research2003_2006-06_replay done 1389.0s cpu_total_h=3.8 failures=0 (2/3)\n"
    )
    assert S.v2_task_seconds(log) == {"2006-05": 1367.7, "2006-06": 1389.0}


def test_v2_main_seconds_sums_main_rows(tmp_path):
    frame = pd.DataFrame({"kind": ["main", "main", "showcase"], "seconds": [1.5, 2.0, 99.0]})
    frame.to_parquet(tmp_path / "research2003_2014-06_replay.parquet")
    assert S.v2_main_seconds(tmp_path, ["2014-06"], "research2003", "replay") == {"2014-06": 3.5}


def test_v3_search_seconds_counts_one_row_per_column_and_arm():
    rows = [
        dict(kind="main", arm=C.U1_ARM, pooled=True, r_fraction=0.1, seconds=10.0),
        dict(kind="main", arm=C.U1_ARM, pooled=False, r_fraction=0.1, seconds=10.0),
        dict(kind="main", arm=C.FRONTIER, pooled=False, r_fraction=0.1, seconds=1.0),
        dict(kind="main", arm=C.ENB_KNEE, pooled=False, r_fraction=0.1, seconds=0.5),
        dict(kind="main", arm=C.APP_FRONTIER, pooled=False, r_fraction=0.1, seconds=0.5),
        dict(kind="side_lambda", arm=C.CRASH_PENALTY, pooled=True, r_fraction=0.1, seconds=7.0),
    ]
    assert S.v3_search_seconds(rows) == pytest.approx(11.5)


def _task(month, tdd768, tddcheck):
    return {
        "month": month,
        "native_768": [{"r_fraction": a, "tdd": t} for a, t in zip(C.RISK_FRACTIONS, tdd768,
                                                                    strict=True)],
        "native_check": [{"r_fraction": a, "tdd": t} for a, t in zip(C.RISK_FRACTIONS, tddcheck,
                                                                      strict=True)],
    }  # fmt: skip


def test_solver_check_accepts_at_34_of_36():
    good = [0.200] * 6
    tasks = [_task(f"m{i}", good, [0.2] * 6) for i in range(5)]
    # 768 calls worse by more than 0.1 pp in two columns: still accepted (34 of 36)
    tasks.append(_task("m5", [0.2015, 0.2015, 0.2009, 0.19, 0.2, 0.2], [0.2] * 6))
    verdict = S.check_verdict(tasks)
    assert (verdict["passed"], verdict["total"], verdict["accepted"]) == (34, 36, True)
    tasks[0] = _task("m0", [0.21] + [0.2] * 5, [0.2] * 6)
    assert not S.check_verdict(tasks)["accepted"]


def _projection(v3_search, v2_task, side=0.0, workers=10):
    schedule = [f"2010-{m:02d}" for m in range(1, 13)]
    showcase = ["2010-01"]
    tasks = [{"month": "2010-01", "search_seconds": v3_search, "side_check_seconds": side,
              "timings": {"phases": {"search_3y": v3_search}}}]  # fmt: skip
    v2_seconds = {m: v2_task for m in schedule}
    v2_seconds["2010-01"] = 10 * v2_task  # a showcase task carried v2's surfaces
    return S.project(schedule, showcase, tasks, v2_seconds, {"2010-01": 1000.0},
                     workers=workers)  # fmt: skip


def test_projection_scales_v2_task_times_and_uses_the_median_at_showcase_origins():
    p = _projection(v3_search=2000.0, v2_task=3600.0, side=500.0, workers=2)
    assert p["scale_factor"] == pytest.approx(2.0)
    assert p["projected_task_seconds"]["2010-02"] == pytest.approx(7200.0)
    assert p["projected_task_seconds"]["2010-01"] == pytest.approx(7200.0 + 500.0)
    total = 11 * 7200.0 + 7700.0
    assert p["projected_wall_hours"] == pytest.approx(total / 2 / 3600.0)
    assert p["cpu_hours_ceiling"] == pytest.approx(2 * total / 3600.0)


@pytest.mark.parametrize(
    ("v2_task", "decision"),
    [(3600.0 * 25, S.RUN), (3600.0 * 45, S.CUT), (3600.0 * 120, S.STOP)],
)
def test_projection_rules(v2_task, decision):
    # one worker per task: the wall time is the longest task (v2 time x scale 1)
    p = _projection(v3_search=1000.0, v2_task=v2_task, workers=1000)
    assert p["projected_wall_hours"] == pytest.approx(v2_task / 3600.0)
    assert p["decision"] == decision


def test_sizing_task_runs_a_task_and_the_solver_check(tmp_path, monkeypatch):
    from portfoliosight.research.fixedrisk import data

    from . import fakes

    inputs = fakes.synthetic_inputs()
    monkeypatch.setattr(data, "load_inputs", lambda *a, **k: inputs)
    month = data.schedule(inputs, fakes.ALPHA)[-2]
    payload = {
        "snapshot": "/snap", "tasks_dir": str(tmp_path / "tasks"), "digest": "sizing",
        "check_calls": 8,
        "spec": dict(menu="research2003", month=month, engine="replay", protocol=3, calls=4,
                     evaluate=False),
    }  # fmt: skip
    out = S.sizing_task(payload)
    assert out["month"] == month and out["peak_rss_bytes"] > 0
    assert out["timings"]["pool_rows"] > 0 and out["timings"]["pool_bytes"] > 0
    assert len(out["native_768"]) == len(out["native_check"]) == len(C.RISK_FRACTIONS)
    assert out["search_seconds"] > 0
    assert (tmp_path / "tasks" / f"research2003_{month}_replay.parquet").is_file()
    verdict = S.check_verdict([out])
    assert verdict["total"] == 6 and not verdict["accepted"]  # 36 columns are needed
