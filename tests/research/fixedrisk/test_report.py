import json
import sys
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from portfoliosight.research.fixedrisk import measures as M
from portfoliosight.research.fixedrisk import report

from .synth import HOLDINGS, build_run, fake_realized, month_labels, synth_horizon

FAST = {"resamples": 200}


@pytest.fixture(scope="module")
def run_dir(tmp_path_factory):
    root = tmp_path_factory.mktemp("rep")
    build_run(root, n_months=30, with_parent=True)
    return root


def _series():
    days = pd.bdate_range("2008-01-01", "2016-12-31")
    rng = np.random.default_rng(3)
    spy = pd.Series(100 * np.cumprod(1 + rng.normal(0.0003, 0.008, len(days))), index=days)
    cpi = pd.Series(
        np.linspace(100, 140, 130), index=pd.date_range("2008-01-01", periods=130, freq="MS")
    )
    dgs = pd.Series(2.0, index=days)
    return days, spy, cpi, dgs


def test_report_renders_every_section_and_caveat(run_dir):
    _, spy, cpi, dgs = _series()
    assert report.check_run(run_dir, report.read_parent(run_dir)) == []
    text = report.run_report(
        run_dir,
        horizon=synth_horizon(30, 16),
        span=None,
        cpi=cpi,
        spy_tr=spy,
        dgs10=dgs,
        study_options=FAST,
    )  # the parent's 20 published intervals and frozen masks
    assert "INTERIM" not in text and "Masks: frozen in the parent manifest" in text
    assert "Rows without a locked mix" in text
    for needle in (
        "# Fixed-risk optimization experiment report",
        "Jobs found: 2",
        "Warning: 4 jobs expected",
        "## Menu `m1`",
        "### m1 / replay",
        "### m1 / garch",
        "White line (U1 free cell vs w_F)",
        "Where U peaks",
        "Safest mix",
        "Line shape",
        "Which U weights",
        "deflated Sharpe ratio",
        "PBO not computable",
        "engine agreement",
        "Collapsed columns",
        "Retrospective menu",
        "VIPSX idealized convention",
        "Host confounding",
        "GARCH is not a production qualification",
        "Tail underpower",
        "Deflated Sharpe ratio and PBO",
        "Cost variant",
        "Regime buckets",
    ):
        assert needle in text, needle
    assert text.count("| r fraction |") >= 8
    assert "nan" not in text.lower().replace("finance", "")


def test_report_label_not_attainable_with_few_intervals(run_dir):
    _, spy, cpi, dgs = _series()
    text = report.run_report(
        run_dir,
        horizon=synth_horizon(30, 16),
        span=None,
        cpi=cpi,
        spy_tr=spy,
        dgs10=dgs,
        disjoint={"m1": [{"month": m} for m in month_labels(30)[:5]]},
        study_options=FAST,
    )
    assert "Realized support: not attainable" in text


def test_report_supported_label_from_controlled_realized(run_dir):
    t = M.load_run(run_dir)
    published = {"m1": [(m, None, None) for m in month_labels(30)[:20]]}
    study = M.Study(t, fake_realized(t.selections), disjoint=published, resamples=200)
    text = report.build_report(study)
    assert "White line (U1 free cell vs w_F): supported**" in text
    assert "tau_r = 0.001 check on 6 origins" in text and "signs agree" in text


def test_main_uses_piece_two_data_module(run_dir, tmp_path, monkeypatch):
    days = pd.bdate_range("2008-01-01", "2020-12-31")
    rng = np.random.default_rng(4)
    records = {
        h: pd.DataFrame(
            {"date": days, "tr_index": 100 * np.cumprod(1 + rng.normal(0.0003, 0.01, len(days)))}
        )
        for h in (*HOLDINGS, "SPY")
    }
    _, _, cpi, dgs = _series()
    horizon = synth_horizon(30, 16)
    parent = report.read_parent(run_dir)

    def load_inputs(snapshot):
        assert str(snapshot).endswith("snap")
        return SimpleNamespace(
            records=records, cpi=cpi, dgs10=pd.Series(2.0, index=days),
            manifest_sha256=parent["snapshot"]["manifest_sha256"],
        )  # fmt: skip

    def horizon_returns(inputs, menu, month):
        """`evaluate.Horizon` fields: days, returns and funds (returns None when immature)."""
        hz = horizon(menu, month)
        if hz is None:
            return SimpleNamespace(days=(), returns=None, funds=HOLDINGS)
        return SimpleNamespace(days=tuple(hz[0]), returns=hz[1], funds=tuple(hz[2]))

    fake = SimpleNamespace(load_inputs=load_inputs, horizon_returns=horizon_returns)
    monkeypatch.setitem(sys.modules, "portfoliosight.research.fixedrisk.data", fake)
    out = tmp_path / "docs" / "r.md"
    rc = report.main(
        ["--run-dir", str(run_dir), "--snapshot", str(tmp_path / "snap"), "--out", str(out)],
        study_options=FAST,
    )
    assert rc == 0
    text = out.read_text()
    assert "## Menu `m1`" in text and "3y real" in text  # span adapter produced multi-year figures
    assert "| 5y |" in text


def test_make_callables_reads_horizon_fields():
    from datetime import date

    from portfoliosight.research.evaluate import Horizon

    days = pd.bdate_range("2020-01-01", periods=300)
    records = {"SPY": pd.DataFrame({"date": days, "tr_index": np.arange(1.0, 301.0)})}
    inputs = SimpleNamespace(records=records, cpi=None, dgs10=None)
    returns = np.full((252, 2), 0.001)
    complete = Horizon("m", ("A", "B"), "2020-01", date(2020, 1, 31), "complete", (),
                       tuple(d.date() for d in days[:252]), returns, "x")  # fmt: skip
    immature = Horizon(
        "m", ("A", "B"), "2025-01", date(2025, 1, 31), "immature", (), (), None, None
    )
    data = SimpleNamespace(
        horizon_returns=lambda i, menu, month: complete if month == "2020-01" else immature
    )
    horizon, *_ = report.make_callables(inputs, data)
    got_days, values, funds = horizon("m", "2020-01")
    assert len(got_days) == 252 and values.shape == (252, 2) and funds == ("A", "B")
    assert horizon("m", "2025-01") is None


def _write_status(run_dir, job, **changes):
    path = run_dir / job / "job.json"
    info = {**json.loads(path.read_text()), **changes}
    path.write_text(json.dumps(info))


def test_an_incomplete_or_foreign_run_is_refused_or_reported_as_interim(tmp_path, capsys):
    import shutil

    import pyarrow.parquet as pq

    build_run(tmp_path, n_months=12, with_parent=True)
    parent = report.read_parent(tmp_path)
    assert report.check_run(tmp_path, parent) == []
    _write_status(tmp_path, "m1-garch", status="incomplete", tasks_done=11, tasks_failed=1,
                  breach={"rule": "arm_seconds"})  # fmt: skip
    stale = tmp_path / "m1-replay" / "tasks" / "m1-replay_2010-05.parquet"
    pq.write_table(pq.read_table(stale).replace_schema_metadata({b"parent_digest": b"x"}), stale)
    shutil.copytree(tmp_path / "m1-replay", tmp_path / "m1-extra")
    problems = report.check_run(tmp_path, parent)
    assert problems == [
        "unexpected job directory m1-extra (not a job of the parent manifest)",
        "job m1-garch is incomplete (11/12 tasks, 1 failed, breach arm_seconds)",
        "job m1-replay has 11 of 12 task files",
        "job m1-replay has 1 task files of another parent digest",
    ]
    _, spy, cpi, dgs = _series()
    kwargs = dict(horizon=synth_horizon(12, 6), span=None, cpi=cpi, spy_tr=spy, dgs10=dgs,
                  study_options=FAST)  # fmt: skip
    with pytest.raises(report.RunNotReady) as caught:
        report.run_report(tmp_path, **kwargs)
    assert caught.value.problems == problems
    text = report.run_report(tmp_path, allow_partial=True, **kwargs)
    assert text.startswith("# INTERIM (partial run, not a result)")
    assert "No label, interval or count below is a conclusion" in text
    assert "- job m1-garch is incomplete" in text
    assert "Jobs found: 2 (m1-garch, m1-replay)" in text  # the extra job is not read
    rc = report.main(["--run-dir", str(tmp_path), "--snapshot", "s", "--out", str(tmp_path / "r")])
    assert rc == 2 and "refusing to report" in capsys.readouterr().err
    assert not (tmp_path / "r").exists()
    (tmp_path / "parent.json").unlink()
    assert report.check_run(tmp_path, None) == [
        f"{tmp_path} has no parent manifest (parent.json); nothing can be checked"
    ]


def test_panel_span_adapter_and_make_callables_immature():
    days = pd.bdate_range("2020-01-01", periods=30)
    rec = {
        h: pd.DataFrame({"date": days, "tr_index": np.arange(1.0, 31.0) * (1 + i)})
        for i, h in enumerate("AB")
    }
    panel = report._panel_span(rec, ["A", "B"])
    assert panel.iloc[1]["A"] == pytest.approx(2 / 1 - 1)
    assert panel.shape == (30, 2)


def test_table_helpers():
    assert report.table(["a"], []) == "_no rows_\n"
    assert report._bp(1e-4) == "+1.0" and report._bp(None) == "n/a"
    assert report._pct(float("nan")) == "n/a" and report._ci(None) == "n/a"
