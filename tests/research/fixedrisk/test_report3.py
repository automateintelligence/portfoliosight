"""The v3 report on synthetic analysis outputs with known answers: the plain-language summary
and decision rule per label, §8.4's verdict wording, every §8.4 section, sensitivity
disagreements next to the verdict, the interim label and the digest checks of `run_report`."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from portfoliosight.research.fixedrisk import analysis3 as A
from portfoliosight.research.fixedrisk import contracts as C
from portfoliosight.research.fixedrisk import ensemble3 as E
from portfoliosight.research.fixedrisk import report3 as R3

from .synth import month_labels
from .test_analysis3 import _realized_rows

K = 30
SECTIONS = (
    "## In plain words",
    "## How to read this report",
    "## The confirmatory verdict (§6)",
    "## Per risk level (descriptive, no per-level claim)",
    "### Relative drawdown change (§6.1, descriptive)",
    "### Risk difference (§5)",
    "## The six mixes side by side (descriptive)",
    "### Realized volatility beside drawdown (§5.1)",
    "## Other mixes against the frontier mix, and arm 3 against each (descriptive)",
    "## Diversification of the selections (§5)",
    "## Does the simulated drawdown ranking match the realized one? (§5)",
    "## Regime buckets (descriptive)",
    "## Longer horizons, inflation and costs (descriptive)",
    "## Side checks (descriptive)",
    "## Selection-bias diagnostics: CSCV and deflated Sharpe ratio (§7.1, §7.2)",
    "## Labels, failures, overrides and amendments (§4.5, §8.4)",
    "## EXPLORATORY: post-hoc ensemble screen (§7.3)",
    "## Limits stated by the protocol",
)


def _analysis(d_dd: float = 0.02, d_ret: float = -0.001, complete: bool = True) -> dict:
    months = month_labels(K)

    def value(arm, j, o, col):
        tested = arm == C.MIN_TDD
        knee = arm == C.ENB_KNEE
        return {
            "dd_m": 0.20 - d_dd * tested - 0.005 * knee,
            "ret_m": 0.05 + d_ret * tested - 0.002 * knee,
            "enb": 10.0 + 2.0 * tested + 3.0 * knee,
            "vol_m": 0.10,
            "tdd": 0.30 - 0.05 * tested + 0.001 * o,
        }.get(col, 0.1)

    table = _realized_rows(months, value, regime_of=lambda o: "calm" if o % 3 else "rate shock")
    table = table.assign(sigma=0.1, mu=0.06, dr2=2.0, enlc=3.0, ret_net=0.049, real_m=0.03,
                         ret_2y=0.1, ret_3y=0.15, ret_5y=0.3)  # fmt: skip
    rows = A.locked_rows(table)
    conf = A.confirmatory_test(table, months, eligible=months, resamples=50)
    knee = A.confirmatory_test(table, months, eligible=months, candidate=C.ENB_KNEE, resamples=50)
    return {
        "job": "research2003_replay",
        "parent_digest": "digest-r",
        "run": {"status": "complete" if complete else "running", "task_files": K if complete else 3,
                "schedule": K, "tasks_done": K, "tasks_total": K, "complete": complete,
                "failures": [], "overrides": [{"reason": "owner approved budget"}],
                "amendments": []},
        "selections": len(table), "eligible_frozen": K, "eligible_outside_schedule": [],
        "labels": {"ok": len(table)},
        "confirmatory": conf,
        "arms": A.arm_summary(rows, C.V3_ARMS),
        "diversification": A.diversification(rows, months),
        "descriptive_comparisons": {f"{C.ENB_KNEE}_vs_{C.FRONTIER}": knee},
        "regimes": A.regime_buckets(rows, months, eligible=months),
        "side_checks": A.side_checks(table),
        "independent_banks": [],
        "rank_agreement": A.rank_agreement(rows, months, resamples=50),
        "dsr": A.dsr_arms(rows, months[::3]),
        "cscv": {"evaluable": 35, "total": 70, "pbo": None,
                 "note": "PBO not computable: 35 of 70 splits evaluable (minimum 50)",
                 "choice_shares": {a: 0.0 for a in C.V3_ARMS}},
    }  # fmt: skip


def _ensemble() -> dict:
    w = A.simplex_weights()
    combos = []
    for c, (dd, ret) in enumerate([(0.03, -0.001), (0.0, 0.0), (-0.01, -0.02)]):
        a, b = dd > 0.01, ret >= -0.005
        described = E.WOULD_PASS if a and b else A._label(a, b)
        combos.append({"combination": c,
                       "weights": dict(zip(A.ENSEMBLE_OBJECTIVES, map(float, w[c]), strict=True)),
                       "paired_cells": 6 * K, "theta_dd": dd, "theta_dd_interval": [dd, dd],
                       "theta_ret": ret, "theta_ret_interval": [ret, ret], "theta_ret_p5": ret,
                       "A": a, "B": b, "description": described})  # fmt: skip
    return {"label": E.EXPLORATORY, "notice": E.NOTICE, "combinations_count": 126,
            "analysis_sha256": "x", "added_after_results": [],
            "candidates": {"cells": 6 * K, "eligible_cells": 6 * K, "median": 1900.0, "min": 1400,
                           "max": 2400},
            "distinct_picked_mixes": 500, "combinations": combos, "would_pass": [0],
            "cscv": {"available": True, "candidates": 126, "omega_denominator": 127,
                     "evaluable": 35, "total": 70, "pbo": None, "note": "PBO not computable",
                     "mean_test_rank": 80.0},
            "dsr": {"available": False, "reason": "fewer than 3 observations"}}  # fmt: skip


PARENT = {"digest": "digest-r", "protocol": {"path": C.V3_PROTOCOL_PATH, "revision": 4,
                                              "sha256": "ab" * 32},
          "snapshot": {"manifest_sha256": "cd" * 32}}  # fmt: skip


def test_a_pass_reports_the_wording_every_section_and_the_next_stage():
    analysis = _analysis()
    text = R3.build_report(analysis, _ensemble(), parent=PARENT)
    c = analysis["confirmatory"]
    assert c["label"] == A.PASS
    assert c["verdict_text"] in text
    assert "Averaged with equal weight over the six fixed risk levels and the 30 eligible" in text
    positions = [text.index(s) for s in SECTIONS]
    assert positions == sorted(positions)  # every §8.4 item, in order, the screen near the end
    summary = text[: text.index("## How to read this report")]
    assert "**Yes, under History replay.**" in summary and "fell 2.00 pp less" in summary
    assert "GARCH confirmation" in summary and R3.KEEP_APP not in summary
    assert "2.00 higher ENB than the frontier mix (more diversified)" in summary
    line = next(x for x in summary.splitlines() if x.startswith("**Lower drawdown, more"))
    assert (
        "the lowest-simulated-drawdown mix (arm 3) (drawdown -2.00 pp, ENB +2.00, return -10.0"
        in line
    )
    assert "the app's Optimized point (arm 6) (drawdown -0.50 pp, ENB +3.00, return -20.0" in line
    assert "U1 mix" not in line  # the same as the frontier mix here: no lower drawdown
    assert "higher ENB in 100.0% of origin-and-risk-level cells" in summary
    assert "app's Optimized point (arm 6), described, not tested" in summary
    assert "return -0.20 pp a year, drawdown -0.50 pp" in summary
    assert "1 of 126 weightings" in summary
    for rf in C.RISK_FRACTIONS:
        assert f"a = {rf:.2f}" in text
    assert "owner approved budget" in text


@pytest.mark.parametrize(
    ("d_dd", "d_ret", "label", "phrase"),
    [
        (0.02, -0.02, A.FAIL_RET, "it gave up too much return"),
        (0.005, 0.0, A.FAIL_DD, "it did not fall clearly less"),
        (-0.01, -0.02, A.FAIL_BOTH, "both conditions failed"),
    ],
)
def test_a_fail_names_the_condition_and_keeps_the_app(d_dd, d_ret, label, phrase):
    analysis = _analysis(d_dd, d_ret)
    assert analysis["confirmatory"]["label"] == label
    text = R3.build_report(analysis, None, parent=PARENT)
    summary = text[: text.index("## How to read this report")]
    assert "**No.**" in summary and phrase in summary and R3.KEEP_APP in summary
    assert f"**Label: {label}.**" in text
    assert analysis["confirmatory"]["verdict_text"] in text
    assert "_The screen has not been run" in text
    line = next(x for x in summary.splitlines() if x.startswith("**Lower drawdown, more"))
    assert ("arm 3" in line) == (d_dd > 0 and d_ret >= -0.005)
    if d_dd < 0:
        assert "fell 1.00 pp more than the frontier mix" in summary


def test_an_inconclusive_verdict_withholds_the_decision():
    analysis = _analysis()
    cell = {"arm": C.FRONTIER, "month": "2010-03", "rf": 0.4, "status": C.ANCHOR_FAILED}
    analysis["confirmatory"] = {
        **analysis["confirmatory"], "label": A.INCONCLUSIVE, "blocking_cells": [cell]
    }  # fmt: skip
    text = R3.build_report(analysis, None, parent=PARENT)
    assert "**No answer yet.**" in text and "no decision until the blocked cells" in text
    assert "| frontier mix (arm 1) | 2010-03 | a = 0.40 | anchor_failed |" in text


def test_a_sensitivity_that_disagrees_is_reported_next_to_the_verdict():
    analysis = _analysis()
    sens = analysis["confirmatory"]["sensitivities"]["12"]
    sens.update(A=False, agrees=False)
    text = R3.build_report(analysis, None, parent=PARENT)
    verdict = text[text.index("## The confirmatory verdict") : text.index("## Per risk level")]
    assert "**Disagreement, reported next to the verdict (§6.2):** blocks of 12 origins " \
           "disagree about the drawdown (A) condition" in verdict  # fmt: skip
    assert "**Caution:**" in text[: text.index("## How to read")]


def test_an_incomplete_run_is_labelled_interim():
    analysis = _analysis(complete=False)
    problems = R3.run_problems(analysis)
    assert problems and "3 of 30 task files" in problems[0]
    text = R3.build_report(analysis, None, parent=PARENT, interim=problems)
    assert text.startswith("# INTERIM (incomplete run, not a result)")


def _recorded(tmp_path, analysis, ensemble=None):
    job = tmp_path / "run" / "research2003_replay"
    job.mkdir(parents=True)
    out = tmp_path / "out"
    out.mkdir()
    path = out / "analysis.json"
    path.write_text(json.dumps(analysis, default=str))
    E.record_analysis(job, path)
    if ensemble is not None:
        ensemble = {**ensemble, "analysis_sha256": E.sha256_file(path)}
        epath = out / "ensemble.json"
        epath.write_text(json.dumps(ensemble))
        E.record_ensemble(job, epath)
    return tmp_path / "run", path


def test_run_report_reads_the_recorded_files_and_checks_their_digests(tmp_path):
    run, path = _recorded(tmp_path, _analysis(), _ensemble())
    text = R3.run_report(run, parent=PARENT, job="research2003_replay")
    assert "1 of 126 weightings would meet both" in text
    assert f"analysis file SHA-256 `{E.sha256_file(path)[:12]}" in text
    path.write_text(path.read_text().replace("digest-r", "digest-r "))
    with pytest.raises(ValueError, match="changed after its digest was recorded"):
        R3.run_report(run, parent=PARENT, job="research2003_replay")


def test_run_report_refuses_a_foreign_parent_a_stale_ensemble_and_an_incomplete_run(tmp_path):
    run, _ = _recorded(tmp_path / "a", _analysis())
    with pytest.raises(ValueError, match="parent digest"):
        R3.run_report(run, parent={**PARENT, "digest": "other"}, job="research2003_replay")
    assert "_The screen has not been run" in R3.run_report(run, parent=PARENT,
                                                           job="research2003_replay")  # fmt: skip
    run, path = _recorded(tmp_path / "b", _analysis(), _ensemble())
    job = run / "research2003_replay"
    record = json.loads((job / E.RECORD_FILE).read_text())
    ens = json.loads((tmp_path / "b" / "out" / "ensemble.json").read_text())
    ens["analysis_sha256"] = "0" * 64
    (tmp_path / "b" / "out" / "ensemble.json").write_text(json.dumps(ens))
    record["ensemble"]["sha256"] = E.sha256_file(tmp_path / "b" / "out" / "ensemble.json")
    (job / E.RECORD_FILE).write_text(json.dumps(record))
    with pytest.raises(ValueError, match="not made after the recorded analysis"):
        R3.run_report(run, parent=PARENT, job="research2003_replay")
    run, _ = _recorded(tmp_path / "c", _analysis(complete=False))
    with pytest.raises(ValueError, match="incomplete run"):
        R3.run_report(run, parent=PARENT, job="research2003_replay")
    text = R3.run_report(run, parent=PARENT, job="research2003_replay", allow_partial=True)
    assert text.startswith("# INTERIM")


def test_arm_means_pool_the_six_levels_with_equal_weight():
    analysis = _analysis()
    for row in analysis["arms"]:
        if row["arm"] == C.FRONTIER:
            row["dd_m"] = 0.1 + float(np.round(row["rf"], 2))
    pooled = R3._arm_pooled(analysis, C.FRONTIER, "dd_m")
    assert pooled == pytest.approx(0.1 + float(pd.Series(C.RISK_FRACTIONS).mean()))
