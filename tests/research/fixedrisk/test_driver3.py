"""The v3 task, its files, the v3 parent manifest and the job driver on v3 tasks."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq
import pytest

from portfoliosight.research.fixedrisk import contracts as C
from portfoliosight.research.fixedrisk import data, driver, driver3, manifest

from . import fakes

LOADER = "tests.research.fixedrisk.fakes:load_inputs"
CALLS = 6


@pytest.fixture(scope="module")
def inputs() -> data.ResearchInputs:
    return fakes.synthetic_inputs()


def hooks() -> driver.Hooks:
    return driver.load_hooks(None, dict.fromkeys(C.ENGINES, C.V3_SOLVER))


def spec_for(inputs, month=None, **kw) -> driver.TaskSpec:
    months = data.schedule(inputs, fakes.ALPHA)
    return driver.TaskSpec(
        "research2003", month or months[-3], "replay", protocol=3, calls=CALLS, **kw
    )


@pytest.fixture(scope="module")
def showcase_out(inputs):
    five = data.lookback5_months(inputs, fakes.ALPHA)[0]
    spec = spec_for(inputs, five, showcase=True, lookback5=True)
    return spec, driver3.run_task(inputs, spec, hooks())


def test_v3_task_rows(showcase_out):
    spec, out = showcase_out
    kinds = {}
    for row in out.selections:
        kinds.setdefault(row["kind"], []).append(row)
    per_column = 2 * len(C.V3_SEARCHED) + 4  # pooled+native per searched arm; F, ENLC, knee, app
    assert len(kinds["main"]) == len(C.RISK_FRACTIONS) * per_column
    assert len(kinds["sens_5y"]) == len(C.RISK_FRACTIONS) * per_column
    assert len(kinds["side_lambda"]) == len(C.RISK_FRACTIONS) * 2 * len(C.LAMBDA_SIDE)
    assert {r["lookback"] for r in kinds["sens_5y"]} == {C.SENSITIVITY_LOOKBACK}
    assert len({r["sel_id"] for r in out.selections}) == len(out.selections)
    assert all(r["status"] in C.V3_USABLE for r in out.selections)
    # the independent banks score every locked selection with weights on each of five seeds
    locked = [r for r in out.selections if r["weights"] is not None]
    assert len(out.evaluated) == len(locked) * len(C.TEST_SEEDS)
    assert {"u1", "tdd"} <= set(out.evaluated[0])
    assert out.timings["pool_rows"] == len(out.pool) > 0
    assert out.timings["seconds_per_evaluation"] > 0
    assert {"knee_3y", "search_3y", "search_5y", "evaluation"} <= set(out.timings["phases"])


def test_v3_task_files(showcase_out, tmp_path):
    spec, out = showcase_out
    driver3.write_task(tmp_path, spec, out, "digest-1")
    paths = driver3.task_paths(tmp_path, spec)
    assert driver.task_done(tmp_path, spec, "digest-1")
    sel = pq.read_table(paths["selections"])
    assert sel.schema.names == driver3.SELECTION_SCHEMA.names
    meta = sel.schema.metadata
    timings = json.loads(meta[driver3.TIMINGS_KEY])
    assert timings["pool_bytes"] == paths["pool"].stat().st_size
    pool = pq.read_table(paths["pool"])
    assert pool.num_rows == len(out.pool)
    assert pool.schema.metadata[b"parent_digest"] == b"digest-1"
    assert set(pool.column("lookback").to_pylist()) == {"3y", "5y"}
    assert pq.read_table(paths["columns"]).num_rows == 2 * len(C.RISK_FRACTIONS)
    assert pq.read_table(paths["evaluated"]).num_rows == len(out.evaluated)


def make_parent_v3(inputs, run_dir: Path, months, **kw) -> dict:
    parent = manifest.build_parent_v3(
        inputs, snapshot_dir=Path("/snap"), cpu_hours=5.0, calls=CALLS, only_months=months, **kw
    )
    manifest.write_parent(run_dir, parent)
    return parent


def test_v3_parent_digest_and_settings(inputs, tmp_path):
    months = data.schedule(inputs, fakes.ALPHA)[-2:]
    parent = make_parent_v3(inputs, tmp_path, months)
    assert parent["kind"] == manifest.V3_KIND and parent["smoke"] is True
    assert parent["digest"] == manifest.body_digest(parent)
    assert parent["protocol"]["path"] == C.V3_PROTOCOL_PATH
    assert parent["protocol"]["revision"] == C.V3_PROTOCOL_REVISION
    assert parent["menus"]["research2003"]["schedule"] == months
    assert (
        parent["settings"]["calls"] == CALLS and parent["settings"]["arm_tau"]["min_tdd"] == 0.001
    )
    assert list(parent["jobs"]) == ["research2003_replay"]
    assert manifest.v3_mismatches(parent) == []
    other = manifest.build_parent_v3(
        inputs, snapshot_dir=Path("/snap"), cpu_hours=5.0, calls=768, only_months=months
    )
    assert other["digest"] != parent["digest"]  # the solver budget is in the digest
    # a parent whose settings differ from the code is refused
    tampered = json.loads(json.dumps(parent))
    tampered["settings"]["lambda"] = 0.2
    assert any("lambda" in p for p in manifest.v3_mismatches(tampered))
    tampered = json.loads(json.dumps(parent))
    tampered["protocol"]["revision"] = 1
    assert any("revision" in p for p in manifest.v3_mismatches(tampered))
    tasks = driver.job_tasks(parent, "research2003", "replay")
    assert [t.month for t in tasks] == months
    assert all(t.protocol == 3 and t.calls == CALLS and not t.stability for t in tasks)


def test_v3_job_runs_and_resumes_and_refuses_mismatched_settings(inputs, tmp_path):
    months = data.schedule(inputs, fakes.ALPHA)[-1:]
    parent = make_parent_v3(inputs, tmp_path, months)
    kw: dict[str, Any] = dict(workers=0, snapshot_dir="/snap", inputs_loader=LOADER, poll=0.0)
    result = driver.run_job(tmp_path, "research2003", "replay", **kw)
    assert result.status == "complete" and result.tasks_done == 1
    job = tmp_path / "research2003_replay"
    spec = driver.job_tasks(parent, "research2003", "replay")[0]
    assert driver3.task_paths(job / "tasks", spec)["pool"].is_file()
    again = driver.run_job(tmp_path, "research2003", "replay", **kw)
    assert again.status == "complete" and "0 to run" in (job / "progress.log").read_text()
    # the same run directory under a parent whose settings the code does not have
    body = {k: v for k, v in parent.items() if k not in ("digest", "created_utc")}
    body["settings"] = {**body["settings"], "tail_paths": 50}
    body["digest"] = manifest.body_digest(body)
    (tmp_path / "parent.json").write_text(json.dumps(body))
    with pytest.raises(RuntimeError, match="tail_paths"):
        driver.run_job(tmp_path, "research2003", "replay", **kw)


def test_searches_per_task_counts_side_checks_and_5y(inputs):
    spec = spec_for(inputs)
    assert driver3.searches_per_task(spec) == 6 * 3
    assert driver3.searches_per_task(replace(spec, showcase=True, lookback5=True)) == 6 * 3 * 2 + 12
    assert driver3.searches_per_task(replace(spec, engine="garch", showcase=True)) == 6 * 3
