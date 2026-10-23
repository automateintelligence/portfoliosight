"""Task execution, files, resume, resource stops, manifests and the CLI of the fixed-risk driver.

Banks and the optimizer are the fakes of ``fakes.py`` (also the ``--hooks`` module of spawned
workers); inputs are the seeded synthetic records on the real XNYS calendar.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq
import pytest

from portfoliosight.research import runner
from portfoliosight.research.fixedrisk import cli, data, driver, estimate, manifest
from portfoliosight.research.fixedrisk import contracts as C
from tests.research.fixedrisk import fakes

HOOKS = "tests.research.fixedrisk.fakes"
SOLVERS = {"replay": "exact_grad", "garch": "exact_grad"}


@pytest.fixture(scope="module")
def inputs() -> data.ResearchInputs:
    return fakes.synthetic_inputs()


@pytest.fixture(autouse=True)
def reset_fakes(monkeypatch: pytest.MonkeyPatch) -> None:
    fakes.CALLS.clear()
    monkeypatch.setattr(fakes, "FAIL_MONTH", None)
    monkeypatch.delenv("FAKE_FAIL_MONTH", raising=False)


def hooks() -> driver.Hooks:
    return driver.Hooks(fakes.make_bank, fakes.search_origin, dict(SOLVERS))


def full_spec(inputs: data.ResearchInputs, engine: str = "replay") -> driver.TaskSpec:
    five = data.lookback5_months(inputs, fakes.ALPHA)[0]
    return driver.TaskSpec(
        "research2003", five, engine, stability=True, showcase=True, lookback5=True
    )


# ------------------------------------------------------------------------------ figures


def test_figures_of_years_are_linear_percentiles_and_tail_mean() -> None:
    rng = np.random.default_rng(3)
    years = rng.normal(0.05, 0.2, size=(2000, 3))
    figures = driver.figures_of_years(years)
    for j, f in enumerate(figures):
        bad, typical, good = np.percentile(years[:, j], [2.5, 50, 97.5])
        assert (f.bad, f.typical, f.good) == (bad, typical, good)
        assert f.es_25 == pytest.approx(years[years[:, j] <= bad, j].mean())
        assert f.mean == pytest.approx(years[:, j].mean())
        assert f.es_25 <= f.bad
    assert driver.figures_of_years(years[:, 0])[0] == figures[0]


# ----------------------------------------------------------------------------- one task


def test_task_runs_every_stage_in_order(inputs: data.ResearchInputs) -> None:
    spec = full_spec(inputs)
    out = driver.run_task(inputs, spec, hooks())
    calls = fakes.CALLS
    main, *rest = calls
    assert main["anchors"] is None and main["seed"] == C.PRIMARY_SEED
    assert main["risk_fractions"] == C.RISK_FRACTIONS and main["arms"] == C.ARM_ORDER
    assert main["solver"] == "exact_grad" and not main["native_only"]
    # stability: primary seed then the four stability seeds, native only, anchors reused
    native = [c for c in rest if c["native_only"]]
    assert [c["seed"] for c in native] == [C.PRIMARY_SEED, *C.STABILITY_SEEDS]
    assert all(c["anchors"] is not None and len(c["anchors"]) == 6 for c in native)
    # showcase surface: 48 columns at the app's positions, 19 slider positions, arm U1, no free cell
    surface = next(c for c in rest if c["d_grid"] == driver.SHOWCASE_D)
    assert len(surface["risk_fractions"]) == 48 and surface["risk_fractions"][0] == 0.0
    assert surface["risk_fractions"][-1] == pytest.approx(1.0)
    assert surface["risk_fractions"][1] == pytest.approx(1 / 47)
    assert (
        len(surface["d_grid"]) == 19
        and surface["d_grid"][0] == 0.05
        and surface["d_grid"][-1] == 0.95
    )
    assert surface["arms"] == ("U1",) and surface["include_free"] is False
    # sensitivities
    tau = next(c for c in rest if c["tau_r"] == C.TAU_R_SENSITIVITY)
    assert tau["anchors"] is None and tau["lookback"] == "3y"
    ends = next(c for c in rest if c["d_grid"] == (0.0, 1.0))
    assert ends["arms"] == ("U1",) and ends["anchors"] is not None
    five = next(c for c in rest if c["lookback"] == "5y")
    assert five["anchors"] is None
    kinds = {row["kind"] for row in out.selections}
    assert kinds == {
        "main",
        "comparator",
        "stability",
        "showcase",
        "sens_tau",
        "sens_endpoints",
        "sens_5y",
    }
    # comparators (arms F, BS): kind "comparator" from the main call, else the call's own kind
    searched = {
        k: sum(r["kind"] == k and r["arm"] not in ("F", "BS") for r in out.selections)
        for k in kinds
    }
    assert searched["main"] == 6 * 4 * 5
    assert (
        sum(r["kind"] == "comparator" and r["arm"] in ("F", "BS") for r in out.selections) == 6 * 2
    )
    assert searched["showcase"] == 48 * 19 and searched["stability"] == 5 * 6 * 4
    assert searched["sens_endpoints"] == 6 * 2 and searched["sens_tau"] == 6 * 4 * 5
    assert searched["sens_5y"] == 6 * 4 * 5
    ids = [row["sel_id"] for row in out.selections]
    assert len(ids) == len(set(ids))
    assert {a["grid"] for a in out.anchors} == {"main", "showcase", "sens_tau", "sens_5y"}
    assert sum(a["grid"] == "main" for a in out.anchors) == 6


def test_stability_selections_are_not_evaluated_everything_else_is(
    inputs: data.ResearchInputs,
) -> None:
    out = driver.run_task(inputs, full_spec(inputs), hooks())
    evaluated = {}
    for row in out.evaluated:
        evaluated.setdefault(row["sel_id"], []).append(row["test_seed"])
    by_id = {row["sel_id"]: row for row in out.selections}
    for ident, row in by_id.items():
        if row["kind"] == "stability":
            assert ident not in evaluated
        else:
            assert sorted(evaluated[ident]) == sorted(C.TEST_SEEDS)
    assert len(out.evaluated) == 5 * sum(r["kind"] != "stability" for r in out.selections)


def test_evaluation_uses_independent_banks_of_the_training_context(
    inputs: data.ResearchInputs,
) -> None:
    spec = full_spec(inputs)
    out = driver.run_task(inputs, spec, hooks())
    ctx3 = data.origin_context(inputs, spec.menu, spec.month)
    ctx5 = data.origin_context(inputs, spec.menu, spec.month, "5y")
    by_id = {row["sel_id"]: row for row in out.selections}
    for evaluated in (out.evaluated[0], out.evaluated[-1], out.evaluated[len(out.evaluated) // 2]):
        row = by_id[evaluated["sel_id"]]
        ctx = ctx5 if row["lookback"] == "5y" else ctx3
        bank = fakes.make_bank(ctx, "replay", evaluated["test_seed"])
        f = driver.figures_of_years(bank.years(np.array(row["weights"])[None, :]))[0]
        assert evaluated["bad"] == pytest.approx(f.bad) and evaluated["es_25"] == pytest.approx(
            f.es_25
        )
        assert evaluated["test_seed"] in C.TEST_SEEDS and evaluated["test_seed"] != row["seed"]


def test_equal_weights_are_scored_once_per_bank(inputs: data.ResearchInputs) -> None:
    ctx = data.origin_context(inputs, fakes.ALPHA, data.schedule(inputs, fakes.ALPHA)[0])
    w = np.array([0.1, 0.2, 0.3, 0.4])
    seen = []

    class CountingBank(fakes.FakeBank):
        def years(self, mixes):
            seen.append(np.atleast_2d(mixes).shape[0])
            return super().years(mixes)

    rows = driver.evaluate_on_test_banks(
        ctx, [("a", w), ("b", w.copy()), ("c", w[::-1].copy())], "replay",
        lambda c, e, s: CountingBank(c, e, s),
    )  # fmt: skip
    assert seen == [2] * 5  # two distinct mixes on each of the five banks
    assert len(rows) == 15
    first = {r["sel_id"]: r for r in rows if r["test_seed"] == C.TEST_SEEDS[0]}
    assert first["a"]["bad"] == first["b"]["bad"] != first["c"]["bad"]


def test_a_stage_flag_off_skips_the_stage(inputs: data.ResearchInputs) -> None:
    month = data.schedule(inputs, fakes.ALPHA)[1]
    out = driver.run_task(inputs, driver.TaskSpec("research2003", month, "garch"), hooks())
    assert len(fakes.CALLS) == 1
    assert {r["kind"] for r in out.selections} == {"main", "comparator"}
    assert {r["engine"] for r in out.selections} == {"garch"}


# ------------------------------------------------------------------------------- files


def test_task_files_round_trip_and_carry_the_parent_digest(
    inputs: data.ResearchInputs, tmp_path: Path
) -> None:
    spec = full_spec(inputs)
    out = driver.run_task(inputs, spec, hooks())
    assert not driver.task_done(tmp_path, spec, "d1")
    driver.write_task(tmp_path, spec, out, "d1")
    paths = driver.task_paths(tmp_path, spec)
    assert paths["selections"] == tmp_path / f"research2003_{spec.month}_replay.parquet"
    assert all(p.is_file() for p in paths.values())
    assert driver.task_done(tmp_path, spec, "d1") and not driver.task_done(tmp_path, spec, "d2")
    table = pq.read_table(paths["selections"])
    assert table.schema.names == [f.name for f in driver.SELECTION_SCHEMA]
    assert table.num_rows == len(out.selections)
    row = table.slice(0, 1).to_pylist()[0]
    assert (
        isinstance(row["weights"], list) and len(row["weights"]) == 4 and row["origin"].year >= 2020
    )
    assert pq.read_table(paths["anchors"]).num_rows == len(out.anchors)
    assert pq.read_table(paths["evaluated"]).num_rows == len(out.evaluated)
    assert not list(tmp_path.rglob("*.tmp"))
    # d is null on the free cell
    free = [r for r in table.to_pylist() if r["cell"] == "free" and r["arm"] == "U1"]
    assert free and all(r["d"] is None for r in free)


# ------------------------------------------------------------------------- manifests


def make_parent(inputs: data.ResearchInputs, run_dir: Path, hooks_name: str | None = HOOKS) -> dict:
    parent = manifest.build_parent(
        inputs, snapshot_dir=Path("/snap"), solvers=SOLVERS,
        placement=dict(manifest.PROTOCOL_PLACEMENT), projections=dict(manifest.PROTOCOL_PROJECTION),
        hooks=hooks_name,
    )  # fmt: skip
    manifest.write_parent(run_dir, parent)
    return parent


def test_budgets_sum_to_the_ceiling_in_proportion() -> None:
    b = manifest.budgets(manifest.PROTOCOL_PROJECTION)
    assert sum(b.values()) == pytest.approx(240.0)
    assert b["research2003_garch"] / b["tsp_replay"] == pytest.approx(36.6 / 18.9)


def test_placement_minimizes_the_larger_wall_time() -> None:
    costs = {
        "a": {"local": 10.0, "ks": 14.0},
        "b": {"local": 10.0, "ks": 14.0},
        "c": {"local": 30.0, "ks": 36.0},
        "d": {"local": 8.0, "ks": 9.0},
    }
    placement, wall = manifest.place(costs, ["local", "ks"], workers=6)
    assert set(placement) == set(costs)
    assert max(wall.values()) == pytest.approx(
        max(sum(costs[j][h] for j in costs if placement[j] == h) for h in wall) / 6
    )
    brute = min(
        max(
            sum(costs[j][h] for j, hh in zip(sorted(costs), pick, strict=True) if hh == h)
            for h in ("local", "ks")
        )
        for pick in __import__("itertools").product(("local", "ks"), repeat=4)
    )
    assert max(wall.values()) * 6 == pytest.approx(brute)


def test_parent_manifest_contents_and_digest(inputs: data.ResearchInputs, tmp_path: Path) -> None:
    parent = make_parent(inputs, tmp_path)
    assert parent["protocol"]["path"] == C.PROTOCOL_PATH and len(parent["protocol"]["sha256"]) == 64
    assert sorted(parent["jobs"]) == sorted(manifest.expected_job_keys())
    assert sum(j["cpu_hours_budget"] for j in parent["jobs"].values()) == pytest.approx(240.0)
    assert parent["seeds"]["primary"] == 20261013 and parent["seeds"]["test"] == list(C.TEST_SEEDS)
    facts = parent["menus"]["research2003"]
    assert facts["schedule"] == data.schedule(inputs, fakes.ALPHA)
    assert (
        facts["origins"] == len(facts["schedule"]) and facts["first_origin"] == facts["schedule"][0]
    )
    assert facts["disjoint_interval_count"] == len(facts["disjoint_intervals"]) >= 1
    assert parent["engines"]["garch"]["solver"] == "exact_grad"
    assert parent["git_head"] and parent["ceilings"]["workers_per_host"] == 6
    assert manifest.read_parent(tmp_path)["digest"] == parent["digest"]
    manifest.write_parent(tmp_path, parent)  # same digest: idempotent
    other = {**parent, "digest": "x" * 64}
    with pytest.raises(FileExistsError):
        manifest.write_parent(tmp_path, other)
    path = tmp_path / "parent.json"
    tampered = json.loads(path.read_text())
    tampered["seeds"]["primary"] = 1
    path.write_text(json.dumps(tampered))
    with pytest.raises(ValueError):
        manifest.read_parent(tmp_path)


def test_parent_rejects_unknown_jobs(inputs: data.ResearchInputs) -> None:
    with pytest.raises(ValueError):
        manifest.build_parent(
            inputs, snapshot_dir=Path("/s"), solvers=SOLVERS, placement={"x": "local"},
            projections={"x": 1.0},
        )  # fmt: skip


# ----------------------------------------------------------------------------- the job


def run(run_dir: Path, **kwargs):
    return driver.run_job(
        run_dir, "tsp", "replay", workers=0, hooks=HOOKS, snapshot_dir="/snap", poll=0.0, **kwargs
    )


def test_job_runs_every_task_then_resumes_without_rerunning(
    inputs: data.ResearchInputs, tmp_path: Path
) -> None:
    parent = make_parent(inputs, tmp_path)
    result = run(tmp_path)
    months = parent["menus"]["tsp"]["schedule"]
    assert result.status == "complete" and result.tasks_done == len(months) == result.tasks_total
    job = tmp_path / "tsp_replay"
    files = sorted(p.name for p in (job / "tasks").glob("*.parquet"))
    assert files == [f"tsp_{m}_replay.parquet" for m in months]
    info = json.loads((job / "job.json").read_text())
    assert info["parent_digest"] == parent["digest"] and info["status"] == "complete"
    assert (
        info["host"]["cpu_model"]
        and info["host"]["libraries"]["numpy"]
        and info["host"]["hostname"]
    )
    log = (job / "progress.log").read_text()
    assert f"({len(months)}/{len(months)})" in log and "cpu_total_h=" in log and "failures=0" in log
    assert not (job / "failures.jsonl").read_text()
    # stability and showcase flags came from the parent's lists
    first = pq.read_table(job / "tasks" / files[0]).to_pylist()
    assert {r["kind"] for r in first} >= {"main", "stability", "showcase"}
    calls_before = len(fakes.CALLS)
    again = run(tmp_path)
    assert again.status == "complete" and len(fakes.CALLS) == calls_before
    assert "0 to run" in (job / "progress.log").read_text()


def test_a_new_parent_digest_invalidates_finished_tasks(
    inputs: data.ResearchInputs, tmp_path: Path
) -> None:
    make_parent(inputs, tmp_path)
    run(tmp_path)
    spec = driver.job_tasks(manifest.read_parent(tmp_path), "tsp", "replay")[0]
    assert driver.task_done(
        tmp_path / "tsp_replay" / "tasks", spec, manifest.read_parent(tmp_path)["digest"]
    )
    assert not driver.task_done(tmp_path / "tsp_replay" / "tasks", spec, "another")


def test_a_failing_task_is_logged_and_the_rest_finish(
    inputs: data.ResearchInputs, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    parent = make_parent(inputs, tmp_path)
    months = parent["menus"]["tsp"]["schedule"]
    monkeypatch.setattr(fakes, "FAIL_MONTH", months[3])
    result = run(tmp_path)
    assert result.status == "incomplete" and result.tasks_failed == 1
    assert result.tasks_done == len(months) - 1
    lines = [
        json.loads(x) for x in (tmp_path / "tsp_replay" / "failures.jsonl").read_text().splitlines()
    ]
    assert len(lines) == 1 and lines[0]["task"] == f"tsp_{months[3]}_replay"
    assert "fake failure" in lines[0]["error"] and "Traceback" in lines[0]["error"]
    assert "FAILED" in (tmp_path / "tsp_replay" / "progress.log").read_text()
    info = json.loads((tmp_path / "tsp_replay" / "job.json").read_text())
    assert info["status"] == "incomplete" and info["tasks_failed"] == 1
    # rerun after the cause is fixed finishes only the failed task
    monkeypatch.setattr(fakes, "FAIL_MONTH", None)
    fakes.CALLS.clear()
    again = run(tmp_path)
    assert again.status == "complete" and {c["month"] for c in fakes.CALLS} == {months[3]}


class FixedMeter:
    def __init__(self, cpu: float = 0.0, rss: int = 0) -> None:
        self.cpu, self.rss = cpu, rss

    def usage(self, pids):
        return runner.Usage(self.cpu, self.rss, self.rss)


def test_cpu_budget_breach_stops_the_job_and_keeps_artifacts(
    inputs: data.ResearchInputs, tmp_path: Path
) -> None:
    make_parent(inputs, tmp_path)
    result = run(tmp_path, meter=FixedMeter(cpu=10 * 3600.0), limits={"cpu_hours": 1.0})
    assert result.status == "incomplete" and result.breach["rule"] == "cpu_hours"
    assert result.tasks_done == 0
    info = json.loads((tmp_path / "tsp_replay" / "job.json").read_text())
    assert info["incomplete"] and info["breach"]["rule"] == "cpu_hours"
    assert "BREACH" in (tmp_path / "tsp_replay" / "progress.log").read_text()


def test_memory_breach_stops_the_job(inputs: data.ResearchInputs, tmp_path: Path) -> None:
    make_parent(inputs, tmp_path)
    result = run(tmp_path, meter=FixedMeter(rss=5 * 2**30))
    assert result.breach["rule"] == "aggregate_peak_rss" and result.status == "incomplete"


def test_arm_seconds_breach_stops_after_the_task_and_keeps_its_files(
    inputs: data.ResearchInputs, tmp_path: Path
) -> None:
    make_parent(inputs, tmp_path)
    result = run(tmp_path, limits={"arm_seconds": 0.005})  # the fake's selections take 0.01 s
    assert result.breach["rule"] == "arm_seconds" and result.status == "incomplete"
    assert (
        result.tasks_done == 1
        and len(list((tmp_path / "tsp_replay" / "tasks").glob("*.parquet"))) == 1
    )


def test_cpu_of_earlier_attempts_counts_against_the_budget(
    inputs: data.ResearchInputs, tmp_path: Path
) -> None:
    make_parent(inputs, tmp_path)
    (tmp_path / "tsp_replay").mkdir()
    (tmp_path / "tsp_replay" / "usage.json").write_text(json.dumps({"cpu_seconds": 10 * 3600.0}))
    result = run(tmp_path, limits={"cpu_hours": 5.0})
    assert result.breach["rule"] == "cpu_hours" and result.breach["value"] >= 10 * 3600.0


def test_one_job_at_a_time_per_host(inputs: data.ResearchInputs, tmp_path: Path) -> None:
    make_parent(inputs, tmp_path)
    with (
        driver.HostLock(tmp_path / "host.lock"),
        pytest.raises(RuntimeError, match="one job at a time"),
    ):
        run(tmp_path)


def test_a_job_on_another_hosts_label_is_refused(
    inputs: data.ResearchInputs, tmp_path: Path
) -> None:
    make_parent(inputs, tmp_path)
    with pytest.raises(ValueError, match="placed on"):
        run(tmp_path, host_label="ks002")  # tsp_replay is placed on local


def test_worker_processes_run_tasks_and_write_the_same_files(
    inputs: data.ResearchInputs, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in runner.BLAS_ENV:
        monkeypatch.setenv(name, "1")
    monkeypatch.setenv("PYTHONPATH", str(Path(__file__).resolve().parents[3]))
    parent = make_parent(inputs, tmp_path)
    result = driver.run_job(
        tmp_path, "tsp", "replay", workers=2, hooks=HOOKS, snapshot_dir="/snap", poll=0.2
    )
    months = parent["menus"]["tsp"]["schedule"]
    assert result.status == "complete" and result.tasks_done == len(months)
    assert result.cpu_seconds > 0
    lines = (tmp_path / "tsp_replay" / "progress.log").read_text().splitlines()
    assert sum("done" in line and "task " in line for line in lines) == len(months)
    # identical content to an in-process run of the same task
    spec = driver.job_tasks(parent, "tsp", "replay")[2]
    ref = driver.run_task(inputs, spec, hooks())
    got = pq.read_table(
        driver.task_paths(tmp_path / "tsp_replay" / "tasks", spec)["selections"]
    ).to_pylist()
    assert [r["sel_id"] for r in got] == [r["sel_id"] for r in ref.selections]
    assert got[5]["weights"] == ref.selections[5]["weights"]


def test_a_worker_refuses_a_snapshot_the_parent_does_not_name(
    inputs: data.ResearchInputs, tmp_path: Path
) -> None:
    make_parent(inputs, tmp_path)
    parent = manifest.read_parent(tmp_path)
    init = driver.WorkerInit("/snap", HOOKS, SOLVERS, None, None, "0" * 64)
    with pytest.raises(RuntimeError, match="parent manifest names"):
        driver.InlinePool(init)
    ok = driver.WorkerInit(
        "/snap", HOOKS, SOLVERS, None, None, parent["snapshot"]["manifest_sha256"]
    )
    driver.InlinePool(ok).close()


def test_worker_refuses_multithreaded_blas(
    inputs: data.ResearchInputs, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENBLAS_NUM_THREADS", "4")
    monkeypatch.setenv("PYTHONPATH", str(Path(__file__).resolve().parents[3]))
    make_parent(inputs, tmp_path)
    with pytest.raises(runner.WorkerError, match="BLAS on one thread"):
        driver.run_job(tmp_path, "tsp", "replay", workers=1, hooks=HOOKS, snapshot_dir="/snap")


# -------------------------------------------------------------------------- estimate


def test_estimate_projects_the_schedule_from_six_showcase_origins(
    inputs: data.ResearchInputs, tmp_path: Path
) -> None:
    result = estimate.run_estimate(inputs, "replay", "local", hooks(), tmp_path)
    assert set(result["jobs"]) == {"research2003_replay", "tsp_replay"}
    for name, menu in result["menus"].items():
        assert len(menu["unit_costs"]["origins_measured"]) == 6
        assert menu["unit_costs"]["main_selections"] == 120 and menu["unit_costs"]["columns"] == 6
        counts = menu["counts"]
        assert counts["origins"] == len(data.schedule(inputs, name))
        assert counts["stability_origins"] == len(data.stability_months(inputs, name))
        assert counts["showcase_origins"] == 6
        assert menu["cpu_hours_total"] > 0
        assert menu["cpu_hours_with_contingency"] == pytest.approx(1.1 * menu["cpu_hours_total"])
        assert set(menu["cpu_hours"]) >= {
            "main_search",
            "showcase_search",
            "independent_evaluation",
        }
    assert json.loads((tmp_path / "estimate.json").read_text())["host"]["label"] == "local"


def test_estimate_scales_with_the_schedule(inputs: data.ResearchInputs) -> None:
    unit = {
        "bank_seconds": 1.0, "main_seconds": 10.0, "native_seconds": 2.0,
        "anchor_seconds_per_column": 0.0, "eval_seconds_per_mix": 0.001, "main_selections": 120.0,
        "comparators": 12.0, "columns": 6,
    }  # fmt: skip
    p = estimate.project_menu(inputs, "research2003", unit)
    n = p["counts"]["origins"]
    s = p["counts"]["stability_origins"]
    assert p["cpu_hours"]["main_search"] == pytest.approx(n * 10.0 / 3600)
    assert p["cpu_hours"]["stability_search"] == pytest.approx(s * 5 * 2.0 / 3600)
    per_search = 10.0 / 120.0
    assert p["cpu_hours"]["showcase_search"] == pytest.approx(6 * 912 * per_search / 3600)


# ------------------------------------------------------------------------------- CLI


def test_cli_parent_run_and_status(
    inputs: data.ResearchInputs, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    for name in runner.BLAS_ENV:
        monkeypatch.setenv(name, "1")
    monkeypatch.setattr(cli.data, "load_inputs", lambda snapshot, **kw: inputs)
    run_dir = tmp_path / "run"
    code = cli.main(["parent", "--snapshot", str(tmp_path), "--run-dir", str(run_dir),
                     "--solver-replay", "exact_grad", "--solver-garch", "exact_grad",
                     "--hooks", HOOKS])  # fmt: skip
    assert code == 0 and (run_dir / "parent.json").is_file()
    capsys.readouterr()
    code = cli.main(["run", "--run-dir", str(run_dir), "--menu", "tsp", "--engine", "replay",
                     "--workers", "0", "--snapshot", "/snap", "--hooks", HOOKS])  # fmt: skip
    assert code == 0
    capsys.readouterr()
    assert cli.main(["status", "--run-dir", str(run_dir)]) == 0
    rows = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    by_job = {r["job"]: r for r in rows}
    assert by_job["tsp_replay"]["status"] == "complete"
    assert by_job["tsp_replay"]["task_files"] == by_job["tsp_replay"]["tasks_total"]
    assert by_job["tsp_garch"]["status"] == "not started"


def test_cli_parent_places_jobs_from_estimates(
    inputs: data.ResearchInputs, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli.data, "load_inputs", lambda snapshot, **kw: inputs)
    files = []
    for label, factor in (("local", 1.0), ("ks002", 1.5)):
        for engine in C.ENGINES:
            est = {
                "host": {"label": label},
                "jobs": {
                    f"research2003_{engine}": factor * (30.0 if engine == "garch" else 20.0),
                    f"tsp_{engine}": factor * (10.0 if engine == "garch" else 18.0),
                },
            }
            path = tmp_path / f"{label}_{engine}.json"
            path.write_text(json.dumps(est))
            files.append(str(path))
    run_dir = tmp_path / "run"
    code = cli.main(["parent", "--snapshot", str(tmp_path), "--run-dir", str(run_dir),
                     "--solver-replay", "exact_grad", "--solver-garch", "cobyla768",
                     "--estimate", *files])  # fmt: skip
    assert code == 0
    parent = manifest.read_parent(run_dir)
    assert set(parent["placement"].values()) <= {"local", "ks002"}
    assert parent["engines"]["garch"]["solver"] == "cobyla768"
    hosts = {parent["placement"][k] for k in parent["placement"]}
    assert hosts == {"local", "ks002"}  # splitting the load beats putting everything on one host
    for key, job in parent["jobs"].items():
        factor = 1.0 if job["host"] == "local" else 1.5
        base = {
            "research2003_garch": 30,
            "tsp_garch": 10,
            "research2003_replay": 20,
            "tsp_replay": 18,
        }[key]
        assert job["projected_cpu_hours"] == pytest.approx(factor * base)
