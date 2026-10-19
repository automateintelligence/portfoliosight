"""`report.md` of the return-optimization report, rendered from `summary.json` alone.

`render(summary)` turns the summary written by `research.report` into markdown: the limits first,
then the verdict and the Stage 2 decision, protocol compliance apart from scientific support, the
panel, R against the three return-agnostic references before R+D against R, the white-line
candidates, realized outcomes, the forecast-error diagnostic, calibration, stability, the native
selections, the sensitivities side by side, cost, every threshold result, the protocol readings
and per-origin appendices. It computes nothing new: every figure is a summary entry, differences
in basis points with their block-24 interval and the 12/36 sensitivity intervals. When the summary
says its statistics are descriptive only (`validity.descriptive_only`: a Stage 1 cell failed, did
not finish or is missing), that label stands next to every table computed from the outcomes.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from portfoliosight.research.evidence import BLOCK, BLOCKS, BP, RISK_CELLS

REALIZED_LABELS = {
    "annual_return": "annual return",
    "max_drawdown": "max-drawdown improvement",
    "loss": "loss rate",
    "below_20": "below -20% rate",
    "worst_day": "worst day",
    "volatility": "realized volatility",
}
_SHARES = frozenset({"loss", "below_20"})
DELTA_LABELS = {"utility": "ΔU", "bad": "ΔB", "typical": "ΔT", "good": "ΔG", "es_25": "ΔES_2.5"}
LEVEL_LABELS = {"utility": "U", "bad": "B", "typical": "T", "good": "G", "es_25": "ES_2.5"}
ACROSS_ORIGINS = {
    "bad": "q(.025) (Bad)",
    "typical": "q(.50) (Typical)",
    "good": "q(.975) (Good)",
    "utility": "U of the quantiles",
    "es_25": "ES_2.5",
}


def _result(passed: bool | None) -> str:
    return "not assessed" if passed is None else "pass" if passed else "FAIL"


def _references(summary: Mapping[str, Any]) -> list[str]:
    return [name for name in summary["references"] if name != "equal_weight_within_ceiling_share"]


def _bp(value: Any) -> str:
    return "n/a" if value is None else f"{value / BP:+.2f}"


def _pct(value: Any) -> str:
    return "n/a" if value is None else f"{100 * value:.1f}%"


def _num(value: Any, digits: int = 4) -> str:
    return "n/a" if value is None else f"{value:.{digits}f}"


def _ci(record: Mapping[str, Any] | None, scale: str = "bp", block: int = BLOCK) -> str:
    if record is None:
        return "n/a"
    low, high = record["interval"].get(str(block), [None, None])
    fmt = _bp if scale == "bp" else _num
    return f"[{fmt(low)}, {fmt(high)}]"


def _est(record: Mapping[str, Any] | None, scale: str = "bp") -> str:
    """Value, primary interval, then the 12/36 sensitivity intervals."""
    if record is None:
        return "n/a"
    fmt = _bp if scale == "bp" else _num
    others = "; ".join(f"L{b} {_ci(record, scale, b)}" for b in BLOCKS[1:])
    return f"{fmt(record['value'])} {_ci(record, scale)} ({others}; n {record['n']})"


def _table(headers: Sequence[str], rows: Sequence[Sequence[Any]]) -> list[str]:
    lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    lines += ["| " + " | ".join(str(cell) for cell in row) + " |" for row in rows]
    return lines + [""]


def _contrast_rows(table: Mapping[str, Any], menus: Sequence[str], scale: str = "bp") -> list:
    rows = []
    for menu in menus:
        for cell in RISK_CELLS:
            rows.append([menu, cell, _est(table["by_cell"][menu][cell], scale)])
        rows.append([menu, "**menu**", _est(table["by_menu"][menu], scale)])
    rows.append(["50/50", "aggregate (never decides)", _est(table["aggregate"], scale)])
    return rows


def _contrast_block(title: str, block: Mapping[str, Any], menus: Sequence[str]) -> list[str]:
    lines = [f"### {title}: {block['first']} minus {block['second']}", ""]
    lines.append("Pooled independent test banks (10,000 outcomes), bp, 95% interval at block 24:")
    lines.append("")
    for figure in block["replay"]:
        lines.append(f"{DELTA_LABELS.get(figure, figure)}:")
        lines.append("")
        lines += _table(
            ["menu", "risk cell", "mean paired difference"],
            _contrast_rows(block["replay"][figure], menus),
        )
    lines.append("Realized (one annual return per origin, realized mask):")
    lines.append("")
    for column in block["realized"]:
        label = REALIZED_LABELS.get(column, column)
        scale = (
            "bp"
            if column in ("annual_return", "max_drawdown", "worst_day", "volatility")
            else "num"
        )
        lines.append(f"{label} ({'bp' if scale == 'bp' else 'share'}):")
        lines.append("")
        lines += _table(
            ["menu", "risk cell", "mean paired difference"],
            _contrast_rows(block["realized"][column], menus, scale),
        )
    return lines


def render(summary: Mapping[str, Any]) -> str:
    """report.md from the summary alone."""
    run = summary["run"]
    menus = run["menus"]
    scope = summary["scope"]
    lines = [
        f"# Return-optimization experiment report: run {run['id']}",
        "",
        f"Protocol `{(run['protocol'] or {}).get('path')}` SHA-256 "
        f"`{(run['protocol'] or {}).get('sha256')}`. Stage {run['stage']}, state `{run['state']}`, "
        f"code `{(run['code'] or {}).get('head')}`. Written by `portfoliosight.research.report` "
        "from this run directory alone; the numbers are in `summary.json`.",
        "",
        "## Read this first",
        "",
        f"- **Design.** {scope['design']}.",
        f"- **Overlapping cohorts.** {scope['cohorts']}.",
        f"- **Tail power.** {scope['tail_power']}.",
        f"- **Intervals.** {scope['intervals']}. Origin index: "
        f"{scope.get('origin_index') or 'unavailable'}.",
        f"- **Allowance sweep.** {scope['allowance_sweep']}.",
        f"- **Process model.** {scope['process_model']}.",
        f"- **Forecast-error diagnostic.** {scope['forecast_error']}.",
        f"- **Stage 2 and the stability branch.** {scope['stage_2_stability_branch']}",
        f"- **Scope of this report.** {scope['stage_2_artifacts']}; {scope['manifest']}.",
        f"- **Review and authority.** {scope['review']}",
        f"- **Settings.** Deviations from the protocol: "
        f"{run['deviations_from_protocol'] or 'none'}; CPU-hour amendment: "
        f"{run['cpu_hours_amendment']}.",
        "",
        "Definitions:",
        "",
    ]
    for name, text in (scope["definitions"] or {}).items():
        lines.append(f"- `{name}`: {text}")
    lines.append("")
    lines += _verdict_lines(summary, menus)
    lines += _compliance_lines(summary)
    if summary["panel"] is None or summary["references"] is None:
        lines += ["## Statistics", "", "Unavailable: the run has no outcomes to assess.", ""]
        lines += _cost_lines(summary, menus)
        lines += _readings_lines(summary)
        return "\n".join(lines) + "\n"
    lines += _panel_lines(summary, menus)
    note = summary["validity"].get("descriptive_only")
    statistics = [
        "## R against the return-agnostic references (before R+D versus R)",
        "",
        "No predeclared threshold applies; R is validated descriptively against each "
        "reference first (protocol 6, D3).",
        "",
    ]
    for ref in _references(summary):
        statistics += _contrast_block(f"R vs {ref}", summary["references"][ref], menus)
    share = summary["references"]["equal_weight_within_ceiling_share"]
    statistics += [f"Equal weight within the cell's ceiling (share of cells): {share}", ""]
    statistics += [
        "## White-line candidates: max-U w_R and the max-mu_s frontier",
        "",
        "Per origin and ceiling the two candidates, with risk, B/T/G, U, ES_2.5 and DR² on "
        "the training and independent banks, are in Appendix A; C8 decides.",
        "",
    ]
    statistics += _contrast_block(
        "w_R vs frontier", summary["white_line"]["w_r_minus_frontier"], menus
    )
    statistics += _primary_lines(summary, menus)
    statistics += _realized_lines(summary, menus)
    statistics += _forecast_lines(summary, menus)
    statistics += _calibration_lines(summary, menus)
    statistics += _stability_lines(summary, menus)
    statistics += _native_lines(summary, menus)
    statistics += _sensitivity_lines(summary, menus)
    lines += _labelled(statistics, note)
    lines += _cost_lines(summary, menus)
    lines += _labelled(_criteria_lines(summary), note)
    lines += _readings_lines(summary)
    lines += _labelled(_appendix_lines(summary), note)
    return "\n".join(lines) + "\n"


def _labelled(lines: list[str], note: str | None) -> list[str]:
    """``note`` (italic) and a blank line before every table of ``lines``; unchanged if None."""
    if note is None:
        return lines
    out: list[str] = []
    for i, line in enumerate(lines):
        if line.startswith("| ") and (i == 0 or not lines[i - 1].startswith("|")):
            out += [f"_{note}_", ""]
        out.append(line)
    return out


def _verdict_lines(summary: Mapping[str, Any], menus: Sequence[str]) -> list[str]:
    labels = summary["labels"]
    lines = ["## Verdict", "", f"Experiment: **{labels['experiment']}**.", ""]
    for reason in labels.get("experiment_reasons", []):
        lines.append(f"- {reason}")
    if labels.get("experiment_reasons"):
        lines.append("")
    rows = []
    for menu, label in labels["menus"].items():
        rows.append(
            [
                menu,
                label["conditional"],
                label["branch"] or "none",
                label["score_change"],
                label["realized"],
                label["tail_power"],
                label["intervals"],
                label["sensitivity"],
            ]
        )
    if rows:
        lines += _table(
            [
                "menu",
                "conditional model",
                "branch",
                "score change",
                "realized",
                "tail power",
                "intervals",
                "sensitivities",
            ],
            rows,
        )
    harm = summary["material_harm"] or []
    lines.append(
        "Material harm: "
        + (
            "none."
            if not harm
            else "; ".join(f"{h['menu']} {h['location']} {h['test']}" for h in harm)
        )
    )
    lines.append("")
    lines.append(
        f"Confirmed worthwhile benefit (the production-default bar, not the Stage 2 gate): "
        f"**{summary['confirmed_worthwhile_benefit']}**."
    )
    stage_2 = summary["stage_2"]
    lines += [
        "",
        f"**Stage 2 (ENB): {'run' if stage_2['run'] else 'skip'}.** {stage_2['reason']}",
        "",
    ]
    for item in stage_2["failing_criteria"]:
        lines.append(f"- {item}")
    return lines + [""]


def _compliance_lines(summary: Mapping[str, Any]) -> list[str]:
    lines = ["## Protocol compliance (separate from scientific support)", ""]
    rows = [
        [c["check"], "met" if c["met"] else "NOT met", c["detail"]]
        for c in summary["validity"]["checks"]
    ]
    lines += _table(["check", "result", "detail"], rows)
    verified = summary["verification"]["stage_1"]
    lines += [f"Artifacts re-hashed against the manifest: {', '.join(sorted(verified))}.", ""]
    d = summary["denominator"]
    lines += [
        f"Denominator (Stage 1 cells, frozen before any search): {d['cells']}; statuses "
        f"{d['by_status']}; missing {d['missing']}; training-ineligible excluded "
        f"{d['training_ineligible_excluded']}; failed {d['failed']} of "
        f"{d['failure_denominator']} = {d['failure_rate']:.4f} (the {d['failure_rate_limit']} "
        "line is information: any unresolved failure prevents a valid completed verdict, R25).",
        "",
    ]
    if d["failed_cells"]:
        lines.append(
            "Failed, incomplete or missing cells (kept in the denominator; every statistic "
            "below is descriptive over the remaining cells):"
        )
        lines.append("")
        lines += _table(
            ["cell", "status", "error", "detail"],
            [
                [c["cell_key"], c["cell_status"], c["error"], c["error_detail"]]
                for c in d["failed_cells"]
            ],
        )
    return lines


def _panel_lines(summary: Mapping[str, Any], menus: Sequence[str]) -> list[str]:
    panel = summary["panel"]
    lines = [
        "## Panel, coverage and missingness",
        "",
        f"Origin index: {panel['origins']} months ({panel['months'][0]} to "
        f"{panel['months'][-1]}), {panel['scheduled']} scheduled; realized panel (complete in "
        f"both menus): {panel['realized_panel']}. Ledger month statuses: "
        f"{panel['ledger_status_counts']}.",
        "",
    ]
    rows = []
    for menu in menus:
        f = panel["menus"][menu]
        rows.append(
            [
                menu,
                f["mature"],
                f["complete"],
                f["mature_missing"],
                f["unexplained_missing"],
                f["immature"],
                f["disjoint_menu"],
                f["disjoint_panel"],
                f"{f['first_origin']} to {f['last_horizon_end']}",
            ]
        )
    lines += _table(
        [
            "menu",
            "mature",
            "complete",
            "missing",
            "unexplained",
            "immature",
            "disjoint (own)",
            "disjoint (realized panel)",
            "calendar span",
        ],
        rows,
    )
    lines += _table(
        ["gate", "value", "rule", "met"],
        [[g["gate"], g["value"], g["rule"], g["met"]] for g in panel["coverage_gates"]],
    )
    return lines


def _primary_lines(summary: Mapping[str, Any], menus: Sequence[str]) -> list[str]:
    primary = summary["primary"]
    lines = [
        "## R+D against R at the 2.5 bp primary cap",
        "",
        "On the optimization bank ΔU lies in [-2.5 bp, 0] by construction; the independent "
        "banks ask whether the Stage B selection recovers more than its sacrifice.",
        "",
    ]
    lines += _contrast_block("Primary", primary, menus)
    lines += ["Optimization-bank (training) ΔU, bp:", ""]
    lines += _table(
        ["menu", "risk cell", "mean paired difference"],
        _contrast_rows(primary["train"]["utility"], menus),
    )
    lines += ["Raw DR² gain (R+D minus R):", ""]
    lines += _table(
        ["menu", "risk cell", "mean"], _contrast_rows(primary["dr2_gain"], menus, "num")
    )
    rows = []
    for menu in menus:
        m = primary["menus"][menu]
        banks = ", ".join(_bp(b["u"]) for b in m["replay"]["banks"])
        rows.append(
            [
                menu,
                banks,
                _pct(m["changed_share"]),
                _pct(m["share_all_three_improve"]),
                _pct(m["share_all_four_improve"]),
                _bp(m["sacrifice"]["mean"]),
                _bp(m["sacrifice"]["max"]),
                _pct(m["sacrifice"]["share_at_cap"]),
                ", ".join(f"{g} {_pct(v)}" for g, v in m["binding_guards"].items()),
            ]
        )
    lines += _table(
        [
            "menu",
            "ΔU per test bank (bp)",
            "L1 >= .02",
            "all three improve",
            "all four improve",
            "mean sacrifice (bp)",
            "max sacrifice (bp)",
            "at cap",
            "binding guards",
        ],
        rows,
    )
    return lines


def _realized_lines(summary: Mapping[str, Any], menus: Sequence[str]) -> list[str]:
    realized = summary["realized"]
    lines = ["## Realized outcomes", "", realized["underpowered"] + ".", ""]
    rows = []
    for menu in menus:
        for arm, cells in realized["per_arm"][menu]["quantiles"].items():
            for cell, q in cells.items():
                rows.append(
                    [
                        menu,
                        arm,
                        cell,
                        _pct(q["bad"]),
                        _pct(q["typical"]),
                        _pct(q["good"]),
                        _pct(q["utility"]),
                        _pct(q["es_25"]),
                    ]
                )
    lines += _table(
        [
            "menu",
            "arm",
            "risk cell",
            "q(.025) (underpowered)",
            "q(.50)",
            "q(.975)",
            "U of the quantiles",
            "ES_2.5 across origins (underpowered)",
        ],
        rows,
    )
    for name, table in realized["quantile_contrasts_rd_minus_r"].items():
        lines += [f"R+D minus R, {ACROSS_ORIGINS.get(name, name)} across origins (bp):", ""]
        lines += _table(["menu", "risk cell", "contrast"], _contrast_rows(table, menus))
    rows = []
    for menu in menus:
        guard = [
            c
            for c in summary["criteria"]
            if c["menu"] == menu and c["key"].startswith(("support.", "guard."))
        ]
        for c in guard:
            rows.append(
                [menu, c["location"], c["test"], c["value"], c["threshold"], _result(c["passed"])]
            )
    lines += ["Realized guardrails and benefit support (99% intervals at block 24):", ""]
    lines += _table(["menu", "location", "test", "value", "threshold", "result"], rows)
    return lines


def _forecast_lines(summary: Mapping[str, Any], menus: Sequence[str]) -> list[str]:
    lines = ["## Forecast-error diagnostic (mechanism (a); not a gate)", ""]
    rows = []
    for menu in menus:
        for cell, r in summary["forecast_error"][menu].items():
            rows.append([menu, cell, _num(r["value"]), r["sign"], _ci(r, "num"), r["n"]])
    return lines + _table(["menu", "risk cell", "correlation", "sign", "95% interval", "n"], rows)


def _calibration_lines(summary: Mapping[str, Any], menus: Sequence[str]) -> list[str]:
    lines = [
        "## Calibration (forecast honesty; never used to select)",
        "",
        "Lower pinball loss for a near-cash allocation does not establish a better portfolio. "
        "q(.025) calibration is underpowered below 200 disjoint intervals.",
        "",
    ]
    rows = []
    for menu in menus:
        for arm, forecasts in summary["calibration"][menu].items():
            for forecast, levels in forecasts.items():
                for name, entry in levels.items():
                    m = entry["menu"]
                    rows.append(
                        [
                            menu,
                            arm,
                            forecast,
                            f"{LEVEL_LABELS.get(name, name)} q({entry['nominal']})",
                            _num(m["coverage"], 3),
                            _num(m["pinball"], 5),
                            m["n"],
                        ]
                    )
    return lines + _table(["menu", "arm", "forecast", "q", "coverage", "pinball", "n"], rows)


def _stability_lines(summary: Mapping[str, Any], menus: Sequence[str]) -> list[str]:
    lines = ["## Stability across the optimizer seeds", ""]
    rows = []
    for menu in menus:
        for arm, s in summary["stability"][menu].items():
            if arm == "selection":
                continue
            for cell in RISK_CELLS:
                d = s["diagnostics"]["cells"][cell]
                sd = d["seed_sd_median"]
                rows.append(
                    [
                        menu,
                        arm,
                        cell,
                        _num(s["median_l1"][cell]),
                        _num(s["p90_l1"][cell]),
                        _pct(s["bad_sd_share"][cell]),
                        _num(s["turnover_median"][cell]),
                        _num(d["turnover_median_primary"]),
                        _levels(sd),
                        _levels(d["bank_sd_median_primary"]),
                    ]
                )
    return (
        lines
        + _table(
            [
                "menu",
                "arm",
                "risk cell",
                "median L1",
                "p90 L1",
                "Bad SD <= .1 vol",
                "turnover (all seeds)",
                "turnover (primary)",
                "median seed SD (bp)",
                "median SD across the 5 banks (bp, primary seed's fixed weights)",
            ],
            rows,
        )
        + _selection_lines(summary, menus)
    )


def _selection_lines(summary: Mapping[str, Any], menus: Sequence[str]) -> list[str]:
    rows = []
    for menu in menus:
        for cell, entry in summary["stability"][menu]["selection"].items():
            guards = ", ".join(f"{g} {_pct(v)}" for g, v in entry["binding_guards"].items())
            rows.append([menu, cell, entry["entries"], _pct(entry["r_plus_d_is_w_r"]), guards])
    lines = ["Selection and guard frequencies of R+D at 2.5 bp, every optimizer seed:", ""]
    return lines + _table(["menu", "risk cell", "cells", "R+D = w_R", "binding guards"], rows)


def _native_lines(summary: Mapping[str, Any], menus: Sequence[str]) -> list[str]:
    lines = ["## Native-search selections (diagnostic; the union selections are primary)", ""]
    for figure in summary["native"]:
        lines.append(f"{DELTA_LABELS.get(figure, figure)} (R+D:native minus R:native, bp):")
        lines.append("")
        lines += _table(
            ["menu", "risk cell", "mean"], _contrast_rows(summary["native"][figure], menus)
        )
    return lines


def _sensitivity_lines(summary: Mapping[str, Any], menus: Sequence[str]) -> list[str]:
    s = summary["sensitivities"]
    lines = [
        "## Sensitivities (side by side; none is a headline)",
        "",
        f"Six origins {', '.join(s['origins'])}; {s['seed']}. Each setting is assessed with "
        "the replay criteria on these origins; a disclosure blocks Stage 2 progression.",
        "",
    ]
    rows = []
    for menu in menus:
        m = s["menus"][menu]
        base = m["stage_1_six_origins"]
        rows.append(
            [
                menu,
                "Stage 1 (2.5 bp)",
                _bp(base and base["u"]),
                _bp(base and base["bad"]),
                _bp(base and base["typical"]),
                _bp(base and base["good"]),
                _bp(base and base["es"]),
                "",
                "",
                "",
            ]
        )
        for name, entry in m["settings"].items():
            r, d = entry["replay"], entry["disclosure"] or {}
            said = list(d.get("reasons", []))
            if not entry["available"]:
                said += entry["unavailable"]
            if entry["descriptive_only"]:
                said.append("figures descriptive only: computed over the available cells")
            rows.append(
                [
                    menu,
                    name,
                    _bp(r and r["u"]),
                    _bp(r and r["bad"]),
                    _bp(r and r["typical"]),
                    _bp(r and r["good"]),
                    _bp(r and r["es"]),
                    d.get("banks_positive_u"),
                    "blocks"
                    if d.get("blocking")
                    else "not assessed: no qualifying branch"
                    if d.get("branch") is None
                    else "does not block",
                    "; ".join(said),
                ]
            )
        stability = m["cross_seed_stability"]
        if stability:
            rows.append(
                [
                    menu,
                    "cross-seed stability",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "blocks",
                    "; ".join(stability["reasons"]),
                ]
            )
    return lines + _table(
        ["menu", "setting", "ΔU", "ΔB", "ΔT", "ΔG", "ΔES", "banks ΔU > 0", "Stage 2", "disclosure"],
        rows,
    )


def _cost_lines(summary: Mapping[str, Any], menus: Sequence[str]) -> list[str]:
    cost = summary["cost"]
    lines = ["## Cost", "", cost["separation"] + ".", ""]
    rows = []
    for menu in menus:
        c = cost["stage_1"][menu]
        for arm, parts in c["search_cost_by_arm"].items():
            rows.append(
                [
                    menu,
                    arm,
                    _num(parts["wall"]["median"], 2),
                    _num(parts["wall"]["p95"], 2),
                    _num(parts["return_evaluation"]["sum"], 1),
                    _num(parts["score"]["sum"], 1),
                    _num(parts["solver"]["sum"], 1),
                    int(parts["invalid"]["sum"]),
                    int(parts["failed_starts"]["sum"]),
                ]
            )
    lines += _table(
        [
            "menu",
            "arm",
            "wall median (s)",
            "wall p95 (s)",
            "replay scoring (s)",
            "measure scoring (s)",
            "solver (s)",
            "invalid calls",
            "failed starts",
        ],
        rows,
    )
    rows = []
    for menu in menus:
        c = cost["stage_1"][menu]
        rows.append(
            [
                menu,
                c["cells"],
                _num(c["paired_wall_ratio"]["median"], 3),
                _num(c["paired_wall_ratio"]["p95"], 3),
                _num(c["shared_preprocessing_and_broad_search"]["wall"]["sum"], 1),
                _num(c["union_rescoring"]["sum"], 1),
                _num(c["failed_cell_wall"]["sum"], 1),
            ]
        )
    lines += _table(
        [
            "menu",
            "cells",
            "R+D/R ratio median",
            "ratio p95",
            "shared (s)",
            "union (s)",
            "failed cells (s)",
        ],
        rows,
    )
    hours = cost["cpu_hours"]
    lines += [
        f"CPU hours: Stage 1 {_num(hours['stage_1'], 3)}, sensitivities "
        f"{hours['sensitivities']}, total {_num(hours['total'], 3)} against the "
        f"{hours['ceiling']} h ceiling (amended: {hours['amended']}). Independent "
        f"evaluation: {cost['stage_1']['independent_evaluation']}. Every paired ratio is in "
        "summary.json (cost.stage_1.<menu>.paired_wall_ratios).",
        "",
    ]
    return lines


def _criteria_lines(summary: Mapping[str, Any]) -> list[str]:
    lines = ["## Every threshold result (protocol 7)", ""]
    rows = [
        [
            c["menu"],
            c["dimension"],
            c["location"],
            c["test"],
            c["value"],
            c["threshold"],
            _result(c["passed"]),
            c.get("reason") or "",
        ]
        for c in summary["criteria"]
    ]
    return lines + _table(
        ["menu", "dimension", "location", "test", "value", "threshold", "result", "reason"], rows
    )


def _levels(values: Mapping[str, Any]) -> str:
    return ", ".join(f"{LEVEL_LABELS.get(k, k)} {_bp(v)}" for k, v in values.items())


def _readings_lines(summary: Mapping[str, Any]) -> list[str]:
    lines = ["## Protocol readings", ""]
    lines += [f"{i}. {text}" for i, text in enumerate(summary["protocol_readings"], start=1)]
    return lines + [""]


def _appendix_lines(summary: Mapping[str, Any]) -> list[str]:
    lines = [
        "## Appendix A: white-line candidates per origin and ceiling (primary seed)",
        "",
        "Test = pooled independent banks; train = optimization bank; weights in summary.json.",
        "",
    ]
    rows_a, rows_b = [], []
    for cell in summary["white_line"]["per_origin"]:
        for name in ("w_R", "frontier"):
            c = cell.get(name)
            if c is None:
                continue
            rows_a.append(
                [
                    cell["menu"],
                    cell["month"],
                    cell["ceiling_id"],
                    name,
                    _pct(c["risk"]),
                    _pct(c["train_bad"]),
                    _pct(c["train_typical"]),
                    _pct(c["train_good"]),
                    _pct(c["train_utility"]),
                    _pct(c["train_es_25"]),
                    _pct(c["test_bad"]),
                    _pct(c["test_typical"]),
                    _pct(c["test_good"]),
                    _pct(c["test_utility"]),
                    _pct(c["test_es_25"]),
                    _num(c["dr2"], 3),
                ]
            )
        rd = cell.get("R+D") or {}
        rows_b.append(
            [
                cell["menu"],
                cell["month"],
                cell["ceiling_id"],
                _bp(rd.get("sacrifice")),
                ", ".join(rd.get("guards") or []) or "none",
                _num((cell.get("w_R") or {}).get("dr2"), 3),
                _num(rd.get("dr2"), 3),
                _num((cell.get("pool_max_dr2") or {}).get("dr2"), 3),
                _num((cell.get("mdp") or {}).get("dr2"), 3),
            ]
        )
    lines += _table(
        [
            "menu",
            "month",
            "ceiling",
            "candidate",
            "risk",
            "train B",
            "train T",
            "train G",
            "train U",
            "train ES",
            "test B",
            "test T",
            "test G",
            "test U",
            "test ES",
            "DR²",
        ],
        rows_a,
    )
    lines += ["## Appendix B: R+D selections per origin and ceiling (primary seed)", ""]
    lines += _table(
        [
            "menu",
            "month",
            "ceiling",
            "U sacrifice (bp)",
            "binding guards",
            "DR² w_R",
            "DR² R+D",
            "DR² pool max",
            "DR² MDP",
        ],
        rows_b,
    )
    return lines
