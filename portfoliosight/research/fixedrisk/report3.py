# ruff: noqa: E501  (prose and f-string table cells)
"""The v3 fixed-risk report (protocol v3 §8.4) as Markdown, from `v3-analyze`'s outputs.

    python -m portfoliosight.research.fixedrisk.cli v3-report --run-dir R --snapshot S --out FILE
        [--job research2003_replay] [--analysis FILE] [--ensemble FILE] [--allow-partial]

The analysis and ensemble files are found through the digest record `v3-analyze` wrote in the run
directory (`<run>/<job>/analysis_record.json`) and checked against it; the snapshot's digest and
the analysis' parent digest must be the parent manifest's. A job that is not complete is refused
unless `--allow-partial`, which labels the whole report interim.

The report leads with a plain-language summary for the owner, then every §8.4 item; the
ensemble screen sits in its own section headed EXPLORATORY. One name per concept (GLOSSARY.md):
`ARM_NAMES` names the six arms, and every figure states its risk level or says it is averaged over
the six levels.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from portfoliosight.research.fixedrisk import contracts as C
from portfoliosight.research.fixedrisk.report import _bp, _ci, _f, _pct, _pp, table

PRIMARY = "24"
ARM_NAMES = {
    C.FRONTIER: "frontier mix (arm 1)",
    C.U1_ARM: "U1 mix (arm 2)",
    C.MIN_TDD: "lowest-simulated-drawdown mix (arm 3)",
    C.CRASH_PENALTY: "crash-penalty mix (arm 4)",
    C.MAX_ENLC: "most-loss-contributors mix (arm 5)",
    C.ENB_KNEE: "app's Optimized point (arm 6)",
    C.APP_FRONTIER: "app's frontier mix (reference, exact risk line)",
}
SHORT = {
    C.FRONTIER: "1 frontier",
    C.U1_ARM: "2 U1",
    C.MIN_TDD: "3 lowest sim. drawdown",
    C.CRASH_PENALTY: "4 crash penalty",
    C.MAX_ENLC: "5 most loss contributors",
    C.ENB_KNEE: "6 app's Optimized point",
    C.APP_FRONTIER: "app frontier (ref.)",
}
OBJECTIVE_NAMES = {"mu": "model return", "u1": "U1", "tdd": "low sim. drawdown",
                   "h": "low worst historical fall", "enlc": "loss contributors", "enb": "ENB"}  # fmt: skip
KEEP_APP = "keep the app's ENB Optimized point as it is"

TERMS = (
    "**Origin**: a monthly start date. The mix is chosen with data up to that month's end and held for the next year.",
    "**Risk level a**: where the fixed risk sits, from the lowest-risk mix (a = 0) to the highest-return mix (a = 1). The six levels are a = 0.10, 0.25, 0.40, 0.55, 0.70 and 0.85; every mix at one level has the same model volatility.",
    "**Drawdown**: the realized maximum drawdown within the year, the deepest fall from a peak during the year after the origin (monthly rebalanced). Lower is better.",
    "**Return**: the realized annual return of the year after the origin (monthly rebalanced, before costs unless marked net).",
    "**ENB**: the effective number of bets, the app's diversification measure. Higher means the mix's risk is spread over more independent bets.",
    "**pp / bp**: percentage points (1 pp = 0.01) and basis points (1 bp = 0.0001, 100 bp = 1 pp).",
    "**Interval**: a 95% block-bootstrap interval over origins (blocks of 24 origins) unless stated otherwise.",
    "**The six mixes**: frontier mix (arm 1, the highest model return at the risk), U1 mix (arm 2), lowest-simulated-drawdown mix (arm 3, the one tested), crash-penalty mix (arm 4), most-loss-contributors mix (arm 5), and the app's Optimized point (arm 6, the ENB knee the app opens on).",
)

LIMITS = (
    "**What preregistration covers (§1).** v3 reuses the frozen history of v2, and its arms were chosen after the owner saw v2's realized results. The thresholds (1 pp, 50 bp, 95%) were chosen after v2's realized intervals on these years were seen; v2's realized-support rule used a 99% lower bound.",
    "**Replay understates long falls (§2.3).** History replay strings together runs of about 21 days, so it keeps losses that cluster within a month and breaks a longer bear market into pieces. Simulated drawdowns therefore understate multi-month falls, which is why a replay pass must be confirmed under GARCH.",
    "**Short crash history before 2009 (§2.4).** The history behind the worst historical fall starts in 2003 (EEM's first price). Origins before late 2008 hold no complete major crash, so the crash penalty (arm 4) mostly reflects the milder dips of 2003-2007 there.",
    "**Arm 6 is the app's method on the experiment's settings (§2.7).** The menu and caps are the experiment's (research2003, 40% per fund, 10% per stock) and the lookback is 3 years where the app uses 5; the 5-year side check is where arm 6 uses the app's window. Its frontier node sits exactly on the risk line and can differ slightly from arm 1, which may sit anywhere in the ±0.1% band.",
    "**Daily versus monthly rebalancing (§11 item 8).** Simulated paths are rebalanced daily, realized outcomes monthly; the mismatch is assumed small next to a 1 pp line. This is an assumption, not a measured result.",
    "**Dependent origins (§6.2).** Neighbouring origins share up to eleven of twelve realized months and 35 of 36 lookback months; only 19 realized years are disjoint. The intervals assume this dependence dies out within about 24 origins, and the false-pass rate is nominal under that assumption.",
)


# ---------------------------------------------------------------------------- helpers


def _value(estimate: Mapping[str, Any] | None) -> float | None:
    return None if not estimate else estimate.get("value")


def _interval(estimate: Mapping[str, Any] | None, block: str = PRIMARY) -> list[Any] | None:
    return None if not estimate else (estimate.get("interval") or {}).get(block)


def _rf(x: Any) -> str:
    return f"a = {float(x):.2f}"


def _yes(flag: Any) -> str:
    return "n/a" if flag is None else ("yes" if flag else "no")


def _mean(values: Sequence[Any]) -> float | None:
    clean = [float(v) for v in values if v is not None and math.isfinite(float(v))]
    return sum(clean) / len(clean) if clean else None


def _arm_rows(analysis: Mapping[str, Any], arm: str) -> list[Mapping[str, Any]]:
    return [row for row in analysis.get("arms", []) if row["arm"] == arm]


def _arm_pooled(analysis: Mapping[str, Any], arm: str, col: str) -> float | None:
    """The mean of an arm's per-level means: equal weight over the six risk levels."""
    return _mean([row.get(col) for row in _arm_rows(analysis, arm)])


def _arm_level(analysis: Mapping[str, Any], arm: str, rf: float, col: str) -> Any:
    for row in _arm_rows(analysis, arm):
        if math.isclose(float(row["rf"]), rf):
            return row.get(col)
    return None


def _arms(analysis: Mapping[str, Any]) -> list[str]:
    present = {row["arm"] for row in analysis.get("arms", [])}
    return [a for a in C.V3_ARMS if a in present]


def _levels(analysis: Mapping[str, Any]) -> list[float]:
    return sorted({float(row["rf"]) for row in analysis.get("arms", [])})


def _diff(a: Any, b: Any) -> float | None:
    return None if a is None or b is None else float(a) - float(b)


def _num(x: Any, digits: int = 2) -> str:
    return _f(x, digits)


def _pbo(cs: Mapping[str, Any]) -> str:
    """'PBO 12.3%', or the CSCV note when PBO is not computable."""
    return f"PBO {_pct(cs['pbo'])}" if cs.get("pbo") is not None else str(cs.get("note"))


def _signed(x: Any, digits: int = 2) -> str:
    return "n/a" if x is None or not math.isfinite(x) else f"{x:+.{digits}f}"


# --------------------------------------------------------------------------- summary


def _answer(c: Mapping[str, Any]) -> str:
    label = c["label"]
    dd, ret = _value(c["theta_dd"]), _value(c["theta_ret"])
    p5 = (c.get("theta_ret_p5") or {}).get(PRIMARY)
    falls = (
        "has no drawdown estimate"
        if dd is None
        else f"fell {abs(dd) * 100:.2f} pp {'less' if dd >= 0 else 'more'} than the frontier mix on average"
    )
    earned = (
        "has no return estimate"
        if ret is None
        else f"earned {abs(ret) * 1e4:.1f} bp a year {'less' if ret < 0 else 'more'} than the frontier mix"
    )
    cost = (f"{earned}; the cautious (one-sided 95%) estimate of the return difference is "
            f"{_bp(p5)} bp, where the line is −50 bp")  # fmt: skip
    if label == "pass":
        return (
            f"**Yes, under History replay.** At the same risk, the lowest-simulated-drawdown mix {falls} "
            f"(the interval is above zero and the estimate clears the 1 pp line), and it {cost}."
        )
    if label == "inconclusive":
        return (
            f"**No answer yet.** {len(c.get('blocking_cells', []))} origin-and-risk-level cells of the frontier mix or the "
            "lowest-simulated-drawdown mix are missing, failed or lack a realized outcome. They must be rerun "
            "under a recorded amendment before the test can be read."
        )
    why = {
        "fail (drawdown)": "it did not fall clearly less: the drawdown condition failed (it needs an interval above zero and an estimate of at least 1 pp)",
        "fail (return)": "it gave up too much return: the return condition failed",
        "fail (both)": "it neither fell clearly less nor kept its return: both conditions failed",
    }[label]
    return f"**No.** At the same risk, the lowest-simulated-drawdown mix {falls}, and it {cost}. So {why}."


def _decision(c: Mapping[str, Any]) -> str:
    label = c["label"]
    if label == "pass":
        return (
            "**What happens next:** the GARCH confirmation (protocol §6.4): arms 1-4 rerun under the GARCH "
            "engine with the same test. The app does not change at this stage; a change needs GARCH and the "
            "TSP menu to confirm, then a separate product decision."
        )
    if label == "inconclusive":
        return (
            "**What happens next:** no decision until the blocked cells are rerun under a recorded amendment "
            "(protocol §4.5). Until then the app stays as it is."
        )
    return (
        f"**Recommendation (decision rule, §6.4 item 5):** nothing passed, so {KEEP_APP}. The other mixes "
        "below inform that recommendation but cannot change it, since none of them was tested."
    )


def _disagreements(c: Mapping[str, Any]) -> list[str]:
    out = []
    for block, s in sorted((c.get("sensitivities") or {}).items(), key=lambda kv: int(kv[0])):
        if s.get("agrees"):
            continue
        which = [n for n, k in (("drawdown (A)", "A"), ("return (B)", "B")) if s.get(k) != c.get(k)]
        out.append(f"blocks of {block} origins disagree about the {' and '.join(which)} condition")
    nw = c.get("newey_west") or {}
    if nw and not nw.get("agrees", True):
        out.append("the Newey-West interval disagrees about the drawdown (A) condition")
    return out


def owner_question(analysis: Mapping[str, Any]) -> str:
    """The owner's question read off the six mixes' means (descriptive): which mixes fell less
    than the frontier mix, had higher ENB and gave up at most 50 bp a year."""
    f = {k: _arm_pooled(analysis, C.FRONTIER, k) for k in ("ret_m", "dd_m", "enb")}
    found = []
    for arm in _arms(analysis):
        if arm == C.FRONTIER:
            continue
        ret, dd, enb = (_arm_pooled(analysis, arm, k) for k in ("ret_m", "dd_m", "enb"))
        d_ret, d_dd, d_enb = _diff(ret, f["ret_m"]), _diff(dd, f["dd_m"]), _diff(enb, f["enb"])
        if d_ret is None or d_dd is None or d_enb is None:
            continue
        if d_dd < 0 and d_enb > 0 and d_ret >= -0.005:
            found.append(f"the {ARM_NAMES[arm]} (drawdown {_pp(d_dd)} pp, ENB {_signed(d_enb)}, "
                         f"return {_bp(d_ret)} bp a year)")  # fmt: skip
    head = ("**Lower drawdown, more diversified and at most 50 bp less return, all at once?** Averaged "
            "over the six risk levels and read from the means only (not a test): ")  # fmt: skip
    if not found:
        return head + "none of the five other mixes managed all three against the frontier mix.\n"
    return head + "; ".join(found) + ".\n"


def summary(analysis: Mapping[str, Any], ensemble: Mapping[str, Any] | None) -> str:
    c = analysis["confirmatory"]
    div = analysis.get("diversification") or {}
    out = ["## In plain words\n"]
    out.append(
        "**The question.** At a fixed risk, is there a mix with slightly lower return that is more "
        "diversified and falls less in a bad year than the frontier mix, or should the app always "
        "pick the frontier mix?\n"
    )
    out.append(
        f"**What was tested.** One pass/fail test: the lowest-simulated-drawdown mix (arm 3) against the "
        f"frontier mix (arm 1), averaged with equal weight over the six risk levels and over "
        f"{c['eligible_origins']} origins with a complete realized year, under the History replay engine. "
        "It passes only if it falls clearly less (by at least 1 pp on average) and costs at most 50 bp of "
        "return a year.\n"
    )
    out.append(f"**The answer.** {_answer(c)}\n")
    flags = _disagreements(c)
    if flags:
        out.append("**Caution:** " + "; ".join(flags) + ". See the verdict section.\n")
    d_enb, share = div.get("enb_mean_difference"), div.get("share_higher_enb")
    if d_enb is not None:
        direction = "more" if d_enb > 0 else "less"
        out.append(
            f"**More diversified?** Averaged over the six risk levels, the lowest-simulated-drawdown mix had "
            f"{abs(d_enb):.2f} {'higher' if d_enb > 0 else 'lower'} ENB than the frontier mix ({direction} "
            f"diversified), and higher ENB in {_pct(share)} of origin-and-risk-level cells.\n"
        )
    out.append(owner_question(analysis))
    knee = C.ENB_KNEE
    if _arm_rows(analysis, knee):
        f_ret, f_dd, f_enb = (
            _arm_pooled(analysis, C.FRONTIER, k) for k in ("ret_m", "dd_m", "enb")
        )
        k_ret, k_dd, k_enb = (_arm_pooled(analysis, knee, k) for k in ("ret_m", "dd_m", "enb"))
        out.append(
            "**The app's Optimized point (arm 6), described, not tested.** Averaged over the six risk levels, "
            f"against the frontier mix: return {_pp(_diff(k_ret, f_ret))} pp a year, drawdown "
            f"{_pp(_diff(k_dd, f_dd))} pp (negative: it fell less), ENB {_signed(_diff(k_enb, f_enb))}.\n"
        )
    out.append(f"{_decision(c)}\n")
    if ensemble:
        n = len(ensemble.get("would_pass", []))
        out.append(
            f"**Exploratory screen.** On the same years, {n} of {ensemble.get('combinations_count', 126)} "
            "weightings of six objectives would have met both conditions. This was a look after the fact: "
            "it cannot change the answer above, and any promising weighting would need its own new test.\n"
        )
    return "\n".join(out)


# --------------------------------------------------------------------------- sections


def verdict_section(c: Mapping[str, Any]) -> str:
    out = ["## The confirmatory verdict (§6)\n"]
    out.append(f"**Label: {c['label']}.**\n")
    out.append(f"> {c['verdict_text']}\n")
    dd, ret = c["theta_dd"], c["theta_ret"]
    p5 = (c.get("theta_ret_p5") or {}).get(PRIMARY)
    out.append(
        "Rows: the two conditions of §6.3. Drawdown difference = frontier mix minus lowest-simulated-drawdown "
        "mix (positive: arm 3 fell less); return difference = arm 3 minus arm 1 (negative: arm 3 earned less). "
        "Both averaged over the six risk levels, then over origins.\n"
    )
    out.append(
        table(
            [
                "Condition",
                "Point estimate",
                "95% interval",
                "One-sided 95% lower bound",
                "Line",
                "Holds",
            ],
            [
                [
                    "(A) drawdown",
                    f"{_pp(_value(dd))} pp",
                    _ci(_interval(dd), _pp) + " pp",
                    "",
                    "interval above 0 and estimate ≥ 1 pp",
                    _yes(c.get("A")),
                ],
                [
                    "(B) return",
                    f"{_bp(_value(ret))} bp",
                    _ci(_interval(ret), _bp) + " bp",
                    f"{_bp(p5)} bp",
                    "lower bound ≥ −50 bp",
                    _yes(c.get("B")),
                ],
            ],
        )  # fmt: skip
    )
    out.append(
        f"Origins in the test: {c['eligible_origins']} (of {c['origins_index']} on the schedule); paired "
        f"origin-and-risk-level cells: {c['paired_cells']}. The 1 pp line is a relevance filter on the point "
        "estimate, not a tested claim.\n"
    )
    out.append("**Sensitivities (they do not change the verdict, §6.2).**\n")
    rows = []
    for block, s in sorted((c.get("sensitivities") or {}).items(), key=lambda kv: int(kv[0])):
        rows.append([f"block of {block} origins", _ci(s.get("dd_interval"), _pp) + " pp",
                     f"{_bp(s.get('ret_p5'))} bp", _yes(s.get("A")), _yes(s.get("B")),
                     "yes" if s.get("agrees") else "**NO**"])  # fmt: skip
    nw = c.get("newey_west") or {}
    if nw:
        rows.append([f"Newey-West, lag {nw.get('lag')}", _ci(nw.get("interval"), _pp) + " pp", "",
                     _yes(nw.get("A")), "", "yes" if nw.get("agrees") else "**NO**"])  # fmt: skip
    out.append(
        table(
            [
                "Interval",
                "Drawdown difference interval",
                "Return lower bound",
                "(A)",
                "(B)",
                "Agrees with the verdict",
            ],
            rows,
        )
    )
    flags = _disagreements(c)
    if flags:
        out.append(
            "**Disagreement, reported next to the verdict (§6.2):** " + "; ".join(flags) + ".\n"
        )
    out.append(
        f"Point-estimate verdict (descriptive, not the rule): **{c.get('point_estimate_verdict')}** "
        "(drawdown estimate ≥ 1 pp and return estimate ≥ −50 bp).\n"
    )
    if c.get("uneven_across_risk"):
        out.append(
            "**Pass, uneven across risk:** three or more risk levels go the wrong way (drawdown difference "
            "below 0 or return difference below −50 bp).\n"
        )
    if c.get("blocking_cells"):
        out.append(f"**Blocking cells ({len(c['blocking_cells'])}):**\n")
        out.append(table(["Arm", "Origin", "Risk level", "Status"],
                         [[ARM_NAMES.get(b["arm"], b["arm"]), b["month"], _rf(b["rf"]), b["status"]]
                          for b in c["blocking_cells"][:50]]))  # fmt: skip
        if len(c["blocking_cells"]) > 50:
            out.append(f"... and {len(c['blocking_cells']) - 50} more (analysis file).\n")
    return "\n".join(out)


def per_level_section(c: Mapping[str, Any]) -> str:
    out = ["## Per risk level (descriptive, no per-level claim)\n"]
    out.append(
        "Rows: risk level a. Columns: lowest-simulated-drawdown mix (arm 3) against the frontier mix (arm 1); "
        "unadjusted 95% intervals.\n"
    )
    out.append(
        table(
            ["Risk level", "Origins", "Drawdown difference pp (95%)", "Return difference bp (95%)"],
            [
                [
                    _rf(r["rf"]),
                    r["n"],
                    f"{_pp(r['d_dd'])} {_ci(r['d_dd_interval'], _pp)}",
                    f"{_bp(r['d_ret'])} {_ci(r['d_ret_interval'], _bp)}",
                ]
                for r in c.get("per_level", [])
            ],
        )  # fmt: skip
    )
    rel, risk = c.get("relative_dd") or {}, c.get("risk_difference") or {}
    out.append("### Relative drawdown change (§6.1, descriptive)\n")
    out.append(
        f"Share of the frontier mix's drawdown that the lowest-simulated-drawdown mix avoided, averaged over "
        f"the six risk levels and then origins: {_pct(_value(rel))} {_ci(_interval(rel), _pct)}.\n"
    )
    out.append("### Risk difference (§5)\n")
    out.append(
        "Model volatility of arm 3 minus that of arm 1, over every origin-and-risk-level cell (both sit in "
        "the ±0.1% band, so up to 0.2% of the risk apart): "
        f"mean {_pp(risk.get('mean'))} pp, 5th percentile {_pp(risk.get('p5'))} pp, 95th percentile "
        f"{_pp(risk.get('p95'))} pp; mean share of the frontier mix's volatility {_pct(risk.get('share_of_sigma_mean'))}.\n"
    )
    return "\n".join(out)


def _arm_level_table(analysis: Mapping[str, Any], col: str, fmt, title: str) -> str:
    arms = _arms(analysis)
    rows = [
        [_rf(rf)] + [fmt(_arm_level(analysis, a, rf, col)) for a in arms]
        for rf in _levels(analysis)
    ]
    rows.append(["mean of the six levels"] + [fmt(_arm_pooled(analysis, a, col)) for a in arms])
    return f"**{title}** Rows: risk level a. Columns: the six mixes.\n\n" + table(
        ["Risk level", *[SHORT[a] for a in arms]], rows
    )


def arms_section(analysis: Mapping[str, Any]) -> str:
    out = ["## The six mixes side by side (descriptive)\n"]
    out.append(
        "This answers the owner's question directly: for each mix, the return it earned, how far it fell "
        "and how diversified it was, at each risk level. Means over origins with a complete realized year "
        "(realized figures) or over all origins (model figures).\n"
    )
    arms = [*_arms(analysis), *([C.APP_FRONTIER] if _arm_rows(analysis, C.APP_FRONTIER) else [])]
    rows = []
    f = {k: _arm_pooled(analysis, C.FRONTIER, k) for k in ("ret_m", "dd_m", "enb")}
    for a in arms:
        ret, dd, enb = (_arm_pooled(analysis, a, k) for k in ("ret_m", "dd_m", "enb"))
        rows.append([ARM_NAMES[a], _pct(ret), _pp(_diff(ret, f["ret_m"])), _pct(dd),
                     _pp(_diff(dd, f["dd_m"])), _num(enb), _signed(_diff(enb, f["enb"])),
                     _pct(_arm_pooled(analysis, a, "vol_m"))])  # fmt: skip
    out.append(
        "**Averaged over the six risk levels.** Rows: the mixes. Differences are against the frontier mix (drawdown: negative means it fell less).\n"
    )
    out.append(
        table(
            [
                "Mix",
                "Return",
                "vs frontier pp",
                "Drawdown",
                "vs frontier pp",
                "ENB",
                "vs frontier",
                "Realized volatility",
            ],
            rows,
        )
    )
    out.append(_arm_level_table(analysis, "ret_m", _pct, "Realized annual return."))
    out.append(
        _arm_level_table(
            analysis, "dd_m", _pct, "Realized drawdown (the deepest fall within the year)."
        )
    )
    out.append(
        _arm_level_table(
            analysis,
            "enb",
            lambda x: _num(x),
            "ENB (effective number of bets) of the selected mix.",
        )
    )
    out.append("### Realized volatility beside drawdown (§5.1)\n")
    out.append(
        "Every mix at one risk level has the same model volatility, yet realized drawdowns differ: losses "
        "that come together compound into deeper troughs (order); a mix holding something that rises in a "
        "crash falls less (crash co-movement); at equal volatility a higher return lowers drawdown (drift); "
        "and mixes at the same estimated volatility realize different volatilities (estimated versus "
        "realized). Rows: risk level a. A drawdown gain with the same realized volatility points to a "
        "better path shape; one with lower realized volatility points to lower realized risk.\n"
    )
    out.append(
        table(
            [
                "Risk level",
                "Arm 1 volatility",
                "Arm 3 volatility",
                "Arm 1 drawdown",
                "Arm 3 drawdown",
            ],
            [
                [
                    _rf(rf),
                    _pct(_arm_level(analysis, C.FRONTIER, rf, "vol_m")),
                    _pct(_arm_level(analysis, C.MIN_TDD, rf, "vol_m")),
                    _pct(_arm_level(analysis, C.FRONTIER, rf, "dd_m")),
                    _pct(_arm_level(analysis, C.MIN_TDD, rf, "dd_m")),
                ]
                for rf in _levels(analysis)
            ],
        )  # fmt: skip
    )
    return "\n".join(out)


def comparisons_section(analysis: Mapping[str, Any]) -> str:
    out = ["## Other mixes against the frontier mix, and arm 3 against each (descriptive)\n"]
    out.append(
        "The same statistics as the test, read as a description only (no other comparison was tested). "
        "Averaged over the six risk levels, then origins. Drawdown difference: comparator minus mix "
        "(positive: the mix fell less); return difference: mix minus comparator.\n"
    )
    rows = []
    for res in (analysis.get("descriptive_comparisons") or {}).values():
        rows.append([ARM_NAMES.get(res["candidate"], res["candidate"]),
                     ARM_NAMES.get(res["comparator"], res["comparator"]),
                     f"{_pp(_value(res['theta_dd']))} {_ci(_interval(res['theta_dd']), _pp)}",
                     f"{_bp(_value(res['theta_ret']))} {_ci(_interval(res['theta_ret']), _bp)}",
                     _bp((res.get('theta_ret_p5') or {}).get(PRIMARY)),
                     res["label"] if res["label"] != "pass" else "would pass"])  # fmt: skip
    out.append(
        table(
            [
                "Mix",
                "Against",
                "Drawdown difference pp (95%)",
                "Return difference bp (95%)",
                "Return lower bound bp",
                "Read against the test's lines",
            ],
            rows,
        )
    )
    return "\n".join(out)


def diversification_section(analysis: Mapping[str, Any]) -> str:
    div = analysis.get("diversification") or {}
    out = ["## Diversification of the selections (§5)\n"]
    out.append(
        "Lowest-simulated-drawdown mix (arm 3) minus frontier mix (arm 1), over every origin-and-risk-level "
        f"cell: ENB {_signed(div.get('enb_mean_difference'))} (arm 3 higher in {_pct(div.get('share_higher_enb'))} "
        f"of cells), diversification ratio squared {_signed(div.get('dr2_mean_difference'))}, effective number "
        f"of loss contributors {_signed(div.get('enlc_mean_difference'))}.\n"
    )
    arms = _arms(analysis)
    out.append("Rows: the mixes; averaged over the six risk levels.\n")
    out.append(table(["Mix", "ENB", "Diversification ratio squared", "Loss contributors (ENLC)", "Model return", "Simulated tail drawdown"],
                     [[ARM_NAMES[a], _num(_arm_pooled(analysis, a, "enb")), _num(_arm_pooled(analysis, a, "dr2")),
                       _num(_arm_pooled(analysis, a, "enlc")), _pct(_arm_pooled(analysis, a, "mu")),
                       _pct(_arm_pooled(analysis, a, "tdd"))] for a in arms]))  # fmt: skip
    return "\n".join(out)


def ranking_section(analysis: Mapping[str, Any]) -> str:
    ra = analysis.get("rank_agreement")
    out = ["## Does the simulated drawdown ranking match the realized one? (§5)\n"]
    if not ra:
        return "\n".join([*out, "_not computed for this job_\n"])
    out.append(
        "At each origin and risk level, the six mixes are ranked by simulated tail drawdown and by realized "
        "drawdown; the figures are the mean rank correlation over origins. With six mixes a correlation is "
        "coarse, so read it as sign agreement: above 0 means the orderings agree more often than not. "
        "Rows: risk level a.\n"
    )
    out.append(table(["Risk level", "Spearman (95%)", "Share above 0", "Kendall tau-b (95%)", "Share above 0"],
                     [[_rf(r["rf"]), f"{_f(r['spearman'], 2)} {_ci(r['spearman_interval'], lambda x: _f(x, 2))}",
                       _pct(r.get("spearman_positive_share")),
                       f"{_f(r['kendall'], 2)} {_ci(r['kendall_interval'], lambda x: _f(x, 2))}",
                       _pct(r.get("kendall_positive_share"))] for r in ra["by_level"]]))  # fmt: skip
    return "\n".join(out)


def regimes_section(analysis: Mapping[str, Any]) -> str:
    out = ["## Regime buckets (descriptive)\n"]
    buckets = analysis.get("regimes") or []
    out.append(
        "Each origin's realized year is labelled: equity drawdown (SPY fell 15% or more inside the year), "
        "else rate shock (the 10-year Treasury yield rose 1.5 pp or more), else calm. Figures are averaged "
        "over the six risk levels, then over the origins in the bucket. Rows: regime.\n"
    )
    out.append(table(["Regime", "Origins", "Drawdown: arm 1", "Drawdown: arm 3", "Drawdown difference pp", "Return: arm 1", "Return: arm 3", "Return difference pp"],
                     [[b["regime"], b["origins"], _pct(b["arms"].get(C.FRONTIER, {}).get("dd_m")),
                       _pct(b["arms"].get(C.MIN_TDD, {}).get("dd_m")), _pp(b.get("d_dd")),
                       _pct(b["arms"].get(C.FRONTIER, {}).get("ret_m")),
                       _pct(b["arms"].get(C.MIN_TDD, {}).get("ret_m")), _pp(b.get("d_ret"))]
                      for b in buckets]))  # fmt: skip
    if buckets:
        arms = [a for a in C.V3_ARMS if a in buckets[0]["arms"]]
        out.append("Drawdown of every mix by regime. Rows: regime; columns: the mixes.\n")
        out.append(table(["Regime", *[SHORT[a] for a in arms]],
                         [[b["regime"], *[_pct(b["arms"][a].get("dd_m")) for a in arms]] for b in buckets]))  # fmt: skip
    return "\n".join(out)


def horizons_section(analysis: Mapping[str, Any]) -> str:
    out = ["## Longer horizons, inflation and costs (descriptive)\n"]
    out.append(
        "Compounded 2-, 3- and 5-year realized returns from the same origin where the years are complete, "
        "the real (inflation-adjusted) 1-year return, and the 1-year return net of 10 bp per unit of "
        "turnover. Rows: the mixes; averaged over the six risk levels.\n"
    )
    arms = _arms(analysis)
    out.append(table(["Mix", "1 year", "1 year net of costs", "1 year real", "2 years", "3 years", "5 years"],
                     [[ARM_NAMES[a], *[_pct(_arm_pooled(analysis, a, k))
                                       for k in ("ret_m", "ret_net", "real_m", "ret_2y", "ret_3y", "ret_5y")]]
                      for a in arms]))  # fmt: skip
    return "\n".join(out)


def side_checks_section(analysis: Mapping[str, Any]) -> str:
    sc = analysis.get("side_checks") or {}
    out = ["## Side checks (descriptive)\n"]
    lam = sc.get("lambda") or {}
    out.append(
        f"**Crash-penalty weight (arm 4), showcase origins {', '.join(lam.get('months', [])) or 'none'}.** "
        "Rows: the penalty weight (0.1 is the main setting); pooled over the six risk levels. Realized "
        "figures cover the origins with a complete year.\n"
    )
    out.append(table(["Penalty weight", "Cells", "U1", "Worst historical fall", "Sim. tail drawdown", "Return", "Drawdown", "ENB"],
                     [[_f(r["lam"], 2), r["n"], _pct(r.get("u1")), _pct(r.get("h")), _pct(r.get("tdd")),
                       _pct(r.get("ret_m")), _pct(r.get("dd_m")), _num(r.get("enb"))]
                      for r in lam.get("rows", [])]))  # fmt: skip
    five = sc.get("lookback_5y") or {}
    out.append(
        f"**5-year lookback, origins {', '.join(five.get('months', [])) or 'none'}.** The app's own window. "
        "Rows: the mixes; pooled over the six risk levels; the 3-year figures are the same origins.\n"
    )
    three = {r["arm"]: r for r in five.get("arms_3y", [])}
    out.append(table(["Mix", "Return 5y lookback", "Return 3y lookback", "Drawdown 5y lookback", "Drawdown 3y lookback", "ENB 5y lookback", "ENB 3y lookback"],
                     [[ARM_NAMES.get(r["arm"], r["arm"]), _pct(r.get("ret_m")), _pct(three.get(r["arm"], {}).get("ret_m")),
                       _pct(r.get("dd_m")), _pct(three.get(r["arm"], {}).get("dd_m")),
                       _num(r.get("enb")), _num(three.get(r["arm"], {}).get("enb"))]
                      for r in five.get("arms_5y", [])]))  # fmt: skip
    banks = analysis.get("independent_banks") or []
    out.append(
        "**Independent simulation banks (§5).** The model figures of each selected mix on its training "
        "bank and averaged over five fresh banks; a gap shows how much of a simulated advantage is search "
        "noise on the training bank. Rows: the mixes; all origins and risk levels.\n"
    )
    out.append(table(["Mix", "Seeds", "Sim. tail drawdown: training", "independent", "Bad year: training", "independent", "U1: training", "independent"],
                     [[ARM_NAMES.get(b["arm"], b["arm"]), b["seeds"], _pct(b.get("tdd_train")), _pct(b.get("tdd_independent")),
                       _pct(b.get("bad_train")), _pct(b.get("bad_independent")),
                       _pct(b.get("u1_train")), _pct(b.get("u1_independent"))] for b in banks]))  # fmt: skip
    return "\n".join(out)


def cscv_dsr_section(analysis: Mapping[str, Any]) -> str:
    out = ["## Selection-bias diagnostics: CSCV and deflated Sharpe ratio (§7.1, §7.2)\n"]
    cs = analysis.get("cscv")
    if cs:
        pbo = _pbo(cs)
        out.append(
            f"**Purged CSCV across the six mixes** (score: mean realized drawdown over the six risk levels, "
            f"lower is better; omega = k/7). Splits evaluable: {cs['evaluable']} of {cs['total']}. {pbo}. "
            "The protocol expected about 35 of 70 splits, below the 50-split minimum; the rule is not relaxed.\n"
        )
        out.append(table(["Mix", "Chosen in training"],
                         [[ARM_NAMES.get(a, a), _pct(v)] for a, v in (cs.get("choice_shares") or {}).items()]))  # fmt: skip
    else:
        out.append("_CSCV not computed (no frozen masks)._\n")
    d = analysis.get("dsr")
    if d:
        out.append(
            "**Deflated Sharpe ratio**, a diagnostic, never a gate: the drawdown difference of arm 3 against "
            f"arm 1 on the {d.get('intervals')} disjoint realized years, deflated for the five trials "
            f"(arms 2-6 against arm 1). DSR {_f(d.get('dsr'))}"
            + (f" ({d['reason']})" if d.get("reason") else "")
            + f"; Sharpe ratio {_f(d.get('sr'))}, benchmark {_f(d.get('sr0'))}, effective trials {_f(d.get('n_eff'), 2)}.\n"
        )
    return "\n".join(out)


def labels_section(analysis: Mapping[str, Any]) -> str:
    run = analysis.get("run") or {}
    out = ["## Labels, failures, overrides and amendments (§4.5, §8.4)\n"]
    out.append(
        "Usable warnings (counted): ok, insufficient_starts, growth_bound_failed, knee_collapsed. "
        "Verdict-blocking failures: search_failed, anchor_failed, no_eligible (arm 5 only, not tested).\n"
    )
    out.append(table(["Label", "Selection rows"], sorted((analysis.get("labels") or {}).items())))
    out.append(f"Task failures recorded by the job: {len(run.get('failures', []))}.\n")
    for item in run.get("failures", [])[:20]:
        out.append(f"- {json.dumps(item)[:300]}")
    out.append(f"\nOwner overrides: {len(run.get('overrides', []))}.\n")
    for item in run.get("overrides", []):
        out.append(f"- {json.dumps(item)}")
    out.append(f"\nAmendments in the parent manifest: {len(run.get('amendments', []))}.\n")
    for item in run.get("amendments", []):
        out.append(f"- {json.dumps(item)}")
    return "\n".join(out) + "\n"


def _weights_text(w: Mapping[str, float]) -> str:
    return ", ".join(f"{OBJECTIVE_NAMES.get(k, k)} {v:.2f}" for k, v in w.items() if v > 0)


def ensemble_section(ensemble: Mapping[str, Any] | None) -> str:
    out = ["## EXPLORATORY: post-hoc ensemble screen (§7.3)\n"]
    if not ensemble:
        return "\n".join([*out, "_The screen has not been run (`v3-ensemble`)._\n"])
    out.append(f"**{ensemble['label']}.** {ensemble['notice']}\n")
    out.append(
        "How it works: at each origin and risk level, every distinct mix that any search visited inside "
        "the ±1% risk band is ranked on six objectives (model return, U1, low simulated drawdown, low worst "
        "historical fall, loss contributors, ENB); each of the 126 weightings of those ranks (steps of 0.25) "
        "picks one mix, and its realized outcomes are compared with the frontier mix exactly as in the test. "
        "Limit: the screen can only pick among mixes the six mixes' searches visited.\n"
    )
    cand = ensemble.get("candidates") or {}
    out.append(
        f"Candidates per origin and risk level: median {_f(cand.get('median'), 0)}, minimum {cand.get('min')}, "
        f"maximum {cand.get('max')} ({cand.get('cells')} of {cand.get('eligible_cells')} cells filled); distinct "
        f"mixes picked: {ensemble.get('distinct_picked_mixes')}. Objectives added after seeing results: "
        f"{', '.join(ensemble.get('added_after_results') or []) or 'none'}.\n"
    )
    combos = ensemble.get("combinations") or []
    n_pass = len(ensemble.get("would_pass", []))
    out.append(
        f"**{n_pass} of {ensemble.get('combinations_count', len(combos))} weightings would meet both of "
        "the test's conditions on these years.** "
        "With 126 tries on the same years, some will look good by chance; the CSCV and deflated Sharpe ratio "
        "below estimate how much.\n"
    )
    ranked = sorted((c for c in combos if c.get("theta_dd") is not None),
                    key=lambda c: (-c["theta_dd"], c["combination"]))[:10]  # fmt: skip
    out.append(
        "Ten weightings with the largest drawdown improvement. Rows: weightings; averaged over the six risk levels, then origins; against the frontier mix.\n"
    )
    out.append(table(["#", "Weights", "Drawdown difference pp (95%)", "Return difference bp (95%)", "Return lower bound bp", "Read against the test's lines"],
                     [[c["combination"], _weights_text(c["weights"]),
                       f"{_pp(c['theta_dd'])} {_ci(c.get('theta_dd_interval'), _pp)}",
                       f"{_bp(c['theta_ret'])} {_ci(c.get('theta_ret_interval'), _bp)}",
                       _bp(c.get("theta_ret_p5")), c["description"]] for c in ranked]))  # fmt: skip
    cs = ensemble.get("cscv") or {}
    if cs.get("available"):
        pbo = _pbo(cs)
        out.append(
            f"**CSCV over the {cs['candidates']} weightings** (score: mean realized drawdown, lower is better; "
            f"omega = k/{cs['omega_denominator']}): {cs['evaluable']} of {cs['total']} splits evaluable; "
            f"{pbo}; mean test rank of the training choice {_f(cs.get('mean_test_rank'), 1)} of {cs['candidates']}.\n"
        )
    else:
        out.append(f"CSCV over the weightings: not available ({cs.get('reason')}).\n")
    d = ensemble.get("dsr") or {}
    if d.get("available"):
        primary = (
            combos[d["primary"]]["weights"]
            if d.get("primary") is not None and d["primary"] < len(combos)
            else {}
        )
        out.append(
            f"**Deflated Sharpe ratio with {d['trials']} trials** on {d['intervals']} disjoint years, primary "
            f"trial #{d['primary']} ({_weights_text(primary)}): DSR {_f(d.get('dsr'))}"
            + (f" ({d['reason']})" if d.get("reason") else "")
            + f"; Sharpe ratio {_f(d.get('sr'))}, benchmark {_f(d.get('sr0'))}.\n"
        )
    else:
        out.append(
            f"Deflated Sharpe ratio over the weightings: not available ({d.get('reason')}).\n"
        )
    return "\n".join(out)


# ------------------------------------------------------------------------------ report


def build_report(
    analysis: Mapping[str, Any],
    ensemble: Mapping[str, Any] | None,
    *,
    parent: Mapping[str, Any],
    digests: Mapping[str, str] | None = None,
    interim: Sequence[str] | None = None,
    title: str = "Fixed-risk experiment v3 report",
) -> str:
    """The Markdown report of one job from its analysis (and ensemble) outputs."""
    protocol = parent.get("protocol") or {}
    if interim is not None:
        title = f"INTERIM (incomplete run, not a result): {title}"
    out = [f"# {title}\n"]
    out.append(
        f"Protocol: `{protocol.get('path', C.V3_PROTOCOL_PATH)}` revision {protocol.get('revision')} "
        f"(SHA-256 {str(protocol.get('sha256', ''))[:12]}...). Job `{analysis['job']}`, parent digest "
        f"`{str(analysis['parent_digest'])[:12]}...`, snapshot `{str((parent.get('snapshot') or {}).get('manifest_sha256', ''))[:12]}...`."
        + "".join(f" {k} file SHA-256 `{v[:12]}...`." for k, v in (digests or {}).items())
        + "\n"
    )
    if interim is not None:
        out.append(
            "**This is an interim report of an incomplete run. No label, interval or count below is a "
            "conclusion of the experiment.** Why:\n"
        )
        out.extend(f"- {p}" for p in interim)
        out.append("")
    out.append(summary(analysis, ensemble))
    out.append("## How to read this report\n")
    out.extend(f"- {t}" for t in TERMS)
    out.append("")
    c = analysis["confirmatory"]
    out.append(verdict_section(c))
    out.append(per_level_section(c))
    out.append(arms_section(analysis))
    out.append(comparisons_section(analysis))
    out.append(diversification_section(analysis))
    out.append(ranking_section(analysis))
    out.append(regimes_section(analysis))
    out.append(horizons_section(analysis))
    out.append(side_checks_section(analysis))
    out.append(cscv_dsr_section(analysis))
    out.append(labels_section(analysis))
    out.append(ensemble_section(ensemble))
    out.append("## Limits stated by the protocol\n")
    out.extend(f"- {t}" for t in LIMITS)
    return "\n".join(out) + "\n"


def run_problems(analysis: Mapping[str, Any]) -> list[str]:
    """Why the analysed job is not a complete run (empty when it is)."""
    run = analysis.get("run") or {}
    if run.get("complete"):
        return []
    return [f"job status {run.get('status')!r}: {run.get('task_files')} of {run.get('schedule')} task "
            f"files, {run.get('tasks_done')} of {run.get('tasks_total')} tasks done"]  # fmt: skip


def run_report(
    run_dir: Path,
    *,
    parent: Mapping[str, Any],
    job: str,
    analysis_path: Path | None = None,
    ensemble_path: Path | None = None,
    allow_partial: bool = False,
) -> str:
    """Load the recorded, digest-checked outputs of `job` and build the report; a ValueError when
    a digest does not match, and when the run is incomplete unless `allow_partial`."""
    from portfoliosight.research.fixedrisk import ensemble3

    job_dir = Path(run_dir) / job
    analysis_file = ensemble3.verified_entry(job_dir, "analysis", analysis_path)
    analysis = json.loads(analysis_file.read_text())
    if analysis.get("parent_digest") != parent["digest"]:
        raise ValueError(
            f"{analysis_file} was made under parent digest {analysis.get('parent_digest')}"
        )
    digests = {"analysis": ensemble3.sha256_file(analysis_file)}
    ensemble = None
    try:
        ensemble_file = ensemble3.verified_entry(job_dir, "ensemble", ensemble_path)
    except ValueError as exc:
        if ensemble_path is not None or "no ensemble digest" not in str(exc):
            raise
    else:
        ensemble = json.loads(ensemble_file.read_text())
        if ensemble.get("analysis_sha256") != digests["analysis"]:
            raise ValueError(f"{ensemble_file} was not made after the recorded analysis")
        digests["ensemble"] = ensemble3.sha256_file(ensemble_file)
    problems = run_problems(analysis)
    if problems and not allow_partial:
        raise ValueError("refusing to report on an incomplete run: " + "; ".join(problems))
    return build_report(analysis, ensemble, parent=parent, digests=digests,
                        interim=problems if problems else None)  # fmt: skip
