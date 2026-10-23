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
    build_run(root, n_months=30)
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
    published = {"m1": [(m, None, None) for m in month_labels(30)[:20]]}
    text = report.run_report(
        run_dir,
        horizon=synth_horizon(30, 16),
        span=None,
        cpi=cpi,
        spy_tr=spy,
        dgs10=dgs,
        disjoint=published,
        study_options=FAST,
    )
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

    def load_inputs(snapshot):
        assert str(snapshot).endswith("snap")
        return SimpleNamespace(records=records, cpi=cpi, dgs10=pd.Series(2.0, index=days))

    fake = SimpleNamespace(
        load_inputs=load_inputs,
        horizon_returns=lambda inputs, menu, month: (
            lambda r: r if r else (_ for _ in ()).throw(ValueError("immature"))
        )(horizon(menu, month)),
        disjoint_intervals=lambda inputs, menu: [(m, None, None) for m in month_labels(30)[:20]],
    )
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
