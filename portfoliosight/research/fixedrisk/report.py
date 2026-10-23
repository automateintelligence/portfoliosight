# ruff: noqa: E501  (prose and f-string table cells)
"""The fixed-risk experiment report (protocol v2 sections 5-7a) as Markdown, from a run directory.

    python -m portfoliosight.research.fixedrisk.report --run-dir R --snapshot S --out docs/research/X.md
        [--allow-partial]

Descriptive figures are tables; there is no plotting. Piece 2's `data` module is imported inside
`main()` only, so the rest of this module runs on arrays and callables.

Before any conclusion is computed the run is checked against its parent manifest (`check_run`):
every expected job present, complete, of the parent's digest, with all its task files, and no
unexpected job. A run that fails a check is refused; `--allow-partial` instead writes a clearly
labelled interim report from the expected jobs' task files of the parent's digest. The CSCV masks
and the disjoint intervals are the ones frozen in the parent manifest.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from portfoliosight.research.fixedrisk import contracts as C
from portfoliosight.research.fixedrisk import measures as M
from portfoliosight.research.fixedrisk import realized as R

EXPECTED_JOBS = 4

CAVEATS = (
    "**Retrospective menu.** The 19-holding research menu and its eight stocks (the US companies "
    "in the 2004 global top ten) are a research choice made with hindsight about which firms "
    "existed in 2004; one dated ranking is not a point-in-time membership history, the 10% cap "
    "limits direct concentration but not survivorship, and the equity ETFs hold the same issuers.",
    "**VIPSX idealized convention.** Weights are set from data through the origin close and returns "
    "are earned from the next session, frictionless except for the cost variant. A mutual fund "
    "priced at its own close cannot be traded at the origin's value, and VIPSX is an actively "
    "managed fund, not a price-history extension of TIP.",
    "**Host confounding.** The two engines run on different hosts (replay local, GARCH on KS-002 by "
    "default); the host is confounded with the engine, and across hosts last-bit differences can "
    "change path ranks and a nonconvex solver's end point.",
    "**GARCH is not a production qualification.** GARCH here is fitted on the 3-year training "
    "window (spec 4.3 fits the shape on up to ten years) and the realized convention differs from "
    "the spec's; the spec's 6.4/6.5 validation stays owed.",
    "**Tail underpower.** Realized 2.5% quantiles rest on a handful of distinct bad years; with "
    "fewer than 200 disjoint annual intervals a confirmed real-world tail benefit cannot be "
    "claimed. Monthly cohorts overlap heavily, and menus, risk levels and cells share outcomes; "
    "none of them is an independent historical replication.",
    "**Same band is not same risk.** Mixes inside one risk band can differ by up to 2% of r in "
    "volatility; the risk difference is reported beside every dU.",
    "**Higher U is not lower downside.** dBad, dES and drawdown are shown beside dU; no equivalence "
    "claim is made.",
    "**Deflated Sharpe ratio and PBO.** The DSR is a modified, ungated diagnostic on about twenty "
    "annual observations with little power; it cannot account for the choices made across the "
    "protocol's revisions (menus, arms, tolerances). The CSCV adaptation is purged, so its two "
    "sides are unequal and dropped splits change the sampling scheme; with four candidates PBO "
    "takes only the values 0.2 to 0.8 per split and is read with the per-triple distributions.",
)


# ---------------------------------------------------------------------------------- formatting


def _f(x: Any, digits: int = 3) -> str:
    if x is None or (isinstance(x, float) and not math.isfinite(x)):
        return "n/a"
    return f"{x:.{digits}f}"


def _bp(x: Any) -> str:
    return "n/a" if x is None or not math.isfinite(x) else f"{x * 1e4:+.1f}"


def _pp(x: Any) -> str:
    return "n/a" if x is None or not math.isfinite(x) else f"{x * 100:+.2f}"


def _pct(x: Any) -> str:
    return "n/a" if x is None or not math.isfinite(x) else f"{x * 100:.1f}%"


def _ci(interval: Sequence[Any] | None, fmt: Callable[[Any], str] = _bp) -> str:
    if not interval or interval[0] is None:
        return "n/a"
    return f"[{fmt(interval[0])}, {fmt(interval[1])}]"


def table(headers: Sequence[str], rows: Sequence[Sequence[Any]]) -> str:
    if not rows:
        return "_no rows_\n"
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    lines += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(lines) + "\n"


# ----------------------------------------------------------------------------------- sections


def _white_line(wl: dict[str, Any]) -> str:
    out = [f"**White line (U1 free cell vs w_F): {wl['label']}** - {wl['reason']}.\n"]
    out.append(
        f"Realized support: {wl['support']}; disjoint annual intervals: {wl['disjoint']}"
        + (
            " (tail adequacy needs 200; realized tails are underpowered)"
            if wl["tail_underpowered"]
            else ""
        )
        + ".\n"
    )
    rows = []
    for tag, name in (("vs_F", "w_F (gated)"), ("vs_BS", "w_BS (reported)")):
        v = wl.get(tag, {})
        model, real = v.get("model"), v.get("realized", {})
        if not model:
            rows.append([name, "0", "n/a", "n/a", "n/a", "n/a", "n/a", "n/a", "n/a"])
            continue
        rows.append(
            [
                name,
                v["pairs"],
                _bp(model.get("u1", {}).get("mean"))
                + " "
                + _ci(model.get("u1", {}).get("interval")),
                f"{model.get('banks_positive', 'n/a')}/{model.get('banks_n', 'n/a')}",
                _bp(model.get("bad", {}).get("mean")),
                _bp(model.get("es_25", {}).get("mean")),
                _bp(model.get("risk", {}).get("mean")),
                _bp(real.get("gain")) + " " + _ci(real.get("gain_interval")),
                _pp(real.get("drawdown_improvement")),
            ]
        )
    out.append(
        table(
            [
                "Comparator",
                "Pairs",
                "Pooled dU bp (95%)",
                "Banks +",
                "dBad bp",
                "dES bp",
                "Risk diff bp",
                "Realized gain bp (95%)",
                "Drawdown improvement pp",
            ],
            rows,
        )
    )
    tau = wl["tau"]
    if tau.get("available"):
        out.append(
            f"tau_r = 0.001 check on {tau['origins']} origins: main dU {_bp(tau['main'])} bp, "
            f"sensitivity {_bp(tau['sensitivity'])} bp, signs {'agree' if tau['agree'] else 'DIFFER'}.\n"
        )
    else:
        out.append("tau_r = 0.001 check: unavailable.\n")
    real = wl["vs_F"].get("realized", {})
    if real.get("cells"):
        out.append(
            "\nRealized guardrails by risk level (monthly convention, U1 free minus w_F; "
            "positive loss is worse):\n"
        )
        out.append(
            table(
                [
                    "r fraction",
                    "n",
                    "Median loss bp",
                    "Mean loss bp",
                    "Loss freq pp",
                    "Drawdown worse pp",
                    "Holds",
                ],
                [
                    [
                        c["rf"],
                        c["n"],
                        _bp(c.get("median_loss")),
                        _bp(c.get("mean_loss")),
                        _pp(c.get("loss_increase")),
                        _pp(c.get("drawdown_worsening")),
                        "n/a" if c["ok"] is None else ("yes" if c["ok"] else "NO"),
                    ]
                    for c in real["cells"]
                ],
            )
        )
    return "\n".join(out)


def _d_star(ds: dict[str, Any]) -> str:
    rows = []
    for r in ds["rows"]:
        q = r["quantiles"]
        rows.append(
            [
                r["rf"],
                r["n"],
                r["undefined"],
                _f(q[0], 2),
                _f(q[1], 2),
                _f(q[2], 2),
                _pct(r.get("below_0")),
                _pct(r.get("above_1")),
                _pct(r.get("at_least_quarter")),
                _f(r.get("regret_mean"), 4),
                _pct(r.get("pooled_beyond_native")),
            ]
        )
    return table(
        [
            "r fraction",
            "Origins",
            "Undefined (collapsed)",
            "d* p10",
            "d* p50",
            "d* p90",
            "d* < 0",
            "d* > 1",
            "d* >= 0.25",
            "Anchor regret (mean, d*>1)",
            "Pooled peak beyond native",
        ],
        rows,
    )


def _safest(sm: dict[str, Any]) -> str:
    if not sm.get("pairs"):
        return "_no max-Bad / U1 pairs_\n"
    out = []
    st = sm["stats"]
    rows = []
    for j, rf in enumerate(M.RFS):

        def pick(tag: str, key: str, j: int = j) -> Any:
            v = st[tag][key]
            return v[j] if j < len(v) else None

        rows.append(
            [
                rf,
                _pct(pick("b", "realized_bad")),
                _pct(pick("u", "realized_bad")),
                _pct(pick("b", "mean_drawdown")),
                _pct(pick("u", "mean_drawdown")),
                _pct(pick("b", "mean_return")),
                _pct(pick("u", "mean_return")),
            ]
        )
    out.append(
        table(
            [
                "r fraction",
                "Bad: max-Bad",
                "Bad: U1",
                "Mean DD: max-Bad",
                "Mean DD: U1",
                "Mean return: max-Bad",
                "Mean return: U1",
            ],
            rows,
        )
    )
    for key, label in (("return_diff", "Realized return"), ("drawdown_diff", "Realized drawdown")):
        if key in sm:
            out.append(
                f"{label}, max-Bad minus U1: {_pp(sm[key]['mean'])} pp {_ci(sm[key]['interval'], _pp)}. "
            )
    out.append(
        f"Model dBad {_bp(sm.get('model_d_bad'))} bp, dES {_bp(sm.get('model_d_es_25'))} bp "
        "(independent banks, max-Bad minus U1).\n"
    )
    return "\n".join(out)


def _line_shape(ls: dict[str, Any]) -> str:
    rows = []
    for r in ls["rows"]:
        if "bad" not in r:
            rows.append([r["rf"], r["n"], "n/a", "n/a", "n/a"])
            continue
        rows.append(
            [r["rf"], r["n"]]
            + [
                f"{_pp(r[k]['slope'])} {_ci(r[k]['interval'], _pp)}"
                for k in ("bad", "drawdown", "return")
            ]
        )
    return table(
        [
            "r fraction",
            "Common origins",
            "Slope on d: realized Bad pp",
            "Slope: mean drawdown pp",
            "Slope: mean return pp",
        ],
        rows,
    )


def _stability(st: dict[str, Any]) -> str:
    rows = [
        [
            r["cell"],
            r["rf"],
            r["origins"],
            _f(r["median_l1"], 2),
            _f(r["p90_l1"], 2),
            _pct(r["bad_sd_share"]),
            "pass" if r["pass"] else "no",
        ]
        for r in st["rows"]
    ]
    return table(
        [
            "Cell",
            "r fraction",
            "Origins (5 banks)",
            "Median L1",
            "P90 L1",
            "Bad SD <= 0.10 sigma",
            "v1 rules",
        ],
        rows,
    )


def _calibration(cal: dict[str, Any]) -> str:
    rows = []
    for arm, row in cal.items():
        for key, v in row.items():
            rows.append([arm, key, v["nominal"], _pct(v["coverage"]), _f(v["pinball"], 5), v["n"]])
    return table(["Arm", "Forecast", "Nominal", "Coverage", "Pinball", "Rows"], rows)


def _cscv(c: dict[str, Any]) -> str:
    if not c.get("available"):
        return f"_CSCV not available: {c.get('reason')}_\n"
    lines = [
        f"Splits evaluable: {c['evaluable']} of {c['splits']} ({c['dropped']} dropped"
        + (f": {'; '.join(c['dropped_reasons'])}" if c["dropped_reasons"] else "")
        + f"); (r, cell) pairs in the common mask: {c['pairs']}; rows used {c['counts']['rows']}, "
        f"excluded for labels {c['counts']['excluded_labelled']}, for collapsed columns "
        f"{c['counts'].get('excluded_collapsed', 0)}, for missing triples "
        f"{c['counts']['excluded_incomplete']}. Masks: frozen in the parent manifest.",
        f"PBO: {_pct(c['pbo']) if c['pbo'] is not None else c['note']}. "
        f"Training side {c['origins_train'][0]}-{c['origins_train'][1]} origins "
        f"(median {c['disjoint_train_median']:.0f} disjoint years), test side "
        f"{c['origins_test'][0]}-{c['origins_test'][1]} (median {c['disjoint_test_median']:.0f}).",
    ]
    names = ("U1", "U2", "U3", "U4")
    rows = [
        [n, _pct(c["chosen_share"].get(n)), _pct(c["mean_test_u"][i])] for i, n in enumerate(names)
    ]
    body = (
        "\n\n".join(lines) + "\n\n" + table(["Triple", "Chosen in training", "Mean test U1"], rows)
    )
    if c.get("mean_rank_u1") is not None:
        body += f"\nMean test rank of the chosen triple: {c['mean_rank_u1']:.2f} of 4 (4 best); ties in training: {c['tied_splits']}.\n"
    if c["scatter"]:
        arr = np.array(c["scatter"])
        body += f"\nDegradation (chosen triple): mean training U1 {_pct(arr[:, 0].mean())}, mean test U1 {_pct(arr[:, 1].mean())}.\n"
    return body


def _dsr(d: dict[str, Any]) -> str:
    if not d.get("available"):
        return f"_DSR not available: {d.get('reason')}_\n"
    return table(
        [
            "n",
            "SR",
            "SR_0",
            "Trial var",
            "N_eff",
            "Trials used",
            "Zero-sd dropped",
            "Skew",
            "Kurtosis",
            "DSR",
        ],
        [
            [
                d["n"],
                _f(d["sr"]),
                _f(d["sr0"]),
                _f(d["trial_variance"], 4),
                _f(d["n_eff"], 2),
                d["trials_used"],
                d["trials_dropped"],
                _f(d["skew"]),
                _f(d["kurtosis"]),
                _f(d["dsr"]) + (f" ({d['reason']})" if d["reason"] else ""),
            ]
        ],
    )


def _cost(c: dict[str, Any]) -> str:
    rows = [
        [r["arm"], r["n"], _f(r["median"], 2), _f(r["p95"], 2), _f(r["iterations"], 0)]
        for r in c["by_arm"]
    ]
    extra = f"Total search time {c['total_hours']:.2f} h."
    if "showcase_seconds_per_surface" in c:
        extra += f" Showcase: {c['showcase_seconds_per_surface']:.1f} s per surface ({c['showcase_surfaces']} surfaces)."
    return (
        table(["Arm", "Cells", "Median s", "P95 s", "Median iterations"], rows)
        + "\n"
        + extra
        + f" Solvers: {c['solvers']}.\n"
    )


def _realized_extra(study: M.Study, menu: str, engine: str) -> str:
    out = []
    hz = study.horizons(menu, engine)
    if hz:
        out.append(
            "**Multi-year and real returns (U1 free vs w_F, monthly convention, descriptive)**\n"
        )
        out.append(
            table(
                ["Horizon", "Rows", "Origins", "U1 mean", "w_F mean", "Difference"],
                [
                    [
                        h["horizon"],
                        h["n"],
                        h["origins"],
                        _pct(h["u1"]),
                        _pct(h["f"]),
                        _pp(h["diff"]),
                    ]
                    for h in hz
                ],
            )
        )
    cv = study.cost_variant(menu, engine)
    if cv:
        out.append("**Cost variant (10 bp of one-way turnover, funding included)**\n")
        out.append(
            table(
                ["", "Gross", "Net"],
                [
                    ["U1 mean return", "", _pct(cv["net_u1"])],
                    ["w_F mean return", "", _pct(cv["net_f"])],
                    ["U1 - w_F", _pp(cv["gross_diff"]), _pp(cv["net_diff"])],
                    [
                        "Mean rebalance turnover (U1 / w_F)",
                        "",
                        f"{_f(cv['turnover_u1'], 2)} / {_f(cv['turnover_f'], 2)}",
                    ],
                ],
            )
        )
    rg = study.regimes(menu, engine)
    if rg:
        out.append("**Regime buckets (U1 free minus w_F, realized monthly convention)**\n")
        out.append(
            table(
                ["Regime", "Origins", "Return diff pp", "Drawdown diff pp", "U1 mean", "w_F mean"],
                [
                    [
                        r["regime"],
                        r["origins"],
                        _pp(r["mean_return_diff"]),
                        _pp(r["mean_drawdown_diff"]),
                        _pct(r["mean_return_u1"]),
                        _pct(r["mean_return_f"]),
                    ]
                    for r in rg
                ],
            )
        )
    return "\n".join(out)


def _collapsed(col: dict[str, Any]) -> str:
    if not col.get("available"):
        return "_no anchors table_\n"
    rows = [[r["rf"], r["n"], _pct(r["share"])] for r in col["by_r"]]
    return (
        table(["r fraction", "Columns", "Collapsed share"], rows)
        + f"\nOverall {_pct(col['overall'])}; showcase surfaces: {col['showcase_columns']} columns, "
        f"collapsed share {_pct(col['showcase_share'])}.\n"
    )


def _exclusions(rows: list[dict[str, Any]]) -> str:
    return table(["Kind", "Status", "Rows"], [[r["kind"], r["status"], r["count"]] for r in rows])


def build_report(
    study: M.Study,
    *,
    title: str = "Fixed-risk optimization experiment report",
    jobs: Sequence[str] | None = None,
    interim: Sequence[str] | None = None,
) -> str:
    """The Markdown report. `interim` lists why the run is not complete; when given, the report is
    labelled an interim report throughout and states that its figures are not conclusions."""
    jobs = list(jobs if jobs is not None else study.jobs)
    if interim is not None:
        title = f"INTERIM (partial run, not a result): {title}"
    out = [f"# {title}\n", f"Protocol: `{C.PROTOCOL_PATH}` revision {C.PROTOCOL_REVISION}.\n"]
    if interim is not None:
        out.append(
            "**This is an interim report of an incomplete or inconsistent run. No label, interval "
            "or count below is a conclusion of the experiment.** The run failed these checks:\n"
        )
        out.extend(f"- {problem}" for problem in interim)
        out.append("")
    out.append("## Run\n")
    out.append(f"Jobs found: {len(jobs)} ({', '.join(jobs)}).")
    if len(jobs) != EXPECTED_JOBS:
        out.append(
            f"**Warning: {EXPECTED_JOBS} jobs expected; the run is incomplete or has extras.**"
        )
    n_sel = study.sel.groupby(["menu", "engine", "kind"]).size().reset_index(name="rows")
    out.append("\n" + table(["Menu", "Engine", "Kind", "Selections"], n_sel.values.tolist()))
    out.append("## Caveats stated by the protocol\n")
    out.extend(f"- {c}" for c in CAVEATS)
    out.append("")
    for menu in study.menus():
        out.append(f"## Menu `{menu}`\n")
        out.append("### Collapsed columns\n")
        out.append(_collapsed(study.collapsed(menu)))
        for engine in study.engines(menu):
            out.append(f"### {menu} / {engine}\n")
            out.append("#### White line\n")
            out.append(_white_line(study.white_line(menu, engine)))
            out.append("\n#### Where U peaks: d* of the free-cell U1 winner\n")
            out.append(_d_star(study.d_star(menu, engine)))
            out.append("\n#### Safest mix: max-Bad arm vs U1 (free cell)\n")
            out.append(_safest(study.safest_mix(menu, engine)))
            out.append("\n#### Line shape: U1 at d = 0.25, 0.50, 0.75\n")
            out.append(_line_shape(study.line_shape(menu, engine)))
            out.append("\n#### Realized extras\n")
            out.append(_realized_extra(study, menu, engine))
            out.append("\n#### Stability (native U1, five banks)\n")
            out.append(_stability(study.stability(menu, engine)))
            out.append("\n#### Forecast calibration (daily-rebalanced realized year)\n")
            out.append(_calibration(study.calibration(menu, engine)))
            out.append("\n#### Which U weights: purged CSCV adaptation\n")
            out.append(_cscv(study.cscv(menu, engine)))
            out.append("\n#### Selection bias: deflated Sharpe ratio (diagnostic, not a gate)\n")
            out.append(_dsr(study.deflated_sharpe(menu, engine)))
            labels = study.labels(menu, engine)
            out.append("\n#### Rows without a locked mix (excluded from every statistic above)\n")
            out.append(_exclusions(study.exclusions(menu, engine)))
            out.append("\n#### Cell labels (non-ok; none is called infeasible)\n")
            out.append(
                table(
                    ["Status", "Cell", "r fraction", "Count"],
                    [[x["status"], x["cell"], x["rf"], x["count"]] for x in labels],
                )
            )
            out.append("\n#### Cost\n")
            out.append(_cost(study.cost(menu, engine)))
        ea = study.engine_agreement(menu)
        out.append(f"### {menu}: engine agreement\n")
        if ea.get("available"):
            out.append(
                f"{ea['engines'][0]} vs {ea['engines'][1]}: {_pct(ea['share_within'])} of {ea['pairs']} locked "
                f"mixes within L1 <= 0.10 (median L1 {_f(ea['median_l1'], 3)}).\n"
            )
            out.append(
                table(
                    ["Cell", "Share within"],
                    [[k, _pct(v)] for k, v in sorted(ea["by_cell"].items())],
                )
            )
            out.append(
                table(
                    ["Arm", "Share within"], [[k, _pct(v)] for k, v in sorted(ea["by_arm"].items())]
                )
            )
            pr = ea.get("paired_realized", {})
            for key, label, fmt in (
                ("dr", "Realized return", _pp),
                ("dd", "Realized drawdown", _pp),
            ):
                if key in pr:
                    out.append(
                        f"{label}, {ea['engines'][0]} minus {ea['engines'][1]} (U1 free, n={pr[key]['n']}): "
                        f"{fmt(pr[key]['mean'])} pp {_ci(pr[key]['interval'], fmt)}.\n"
                    )
        else:
            out.append("_only one engine present_\n")
    return "\n".join(out) + "\n"


# --------------------------------------------------------------------------- data adapters


def _panel_span(records: Mapping[str, pd.DataFrame], holdings: Sequence[str]):
    """Daily simple returns of the holdings on their union calendar (tr_index, forward filled)."""
    series = {}
    for h in holdings:
        df = records[h]
        s = pd.Series(df["tr_index"].to_numpy(dtype=float), index=pd.to_datetime(df["date"]))
        series[h] = s[~s.index.duplicated(keep="last")]
    calendar = sorted(set().union(*[set(s.index) for s in series.values()]))
    panel = pd.DataFrame({h: s.reindex(calendar).ffill() for h, s in series.items()})
    return panel.pct_change()


def make_callables(inputs: Any, data: Any):
    """(horizon, span, spy_tr, cpi, dgs10) from piece 2's `load_inputs` object."""

    def horizon(menu: str, month: str):
        try:
            hz = data.horizon_returns(inputs, menu, month)
        except (ValueError, KeyError, LookupError):
            return None
        if hz.returns is None or not hz.days:  # the ledger has no complete realized year
            return None
        return list(hz.days), np.asarray(hz.returns, dtype=float), tuple(hz.funds)

    panels: dict[str, pd.DataFrame] = {}

    def span(menu: str, month: str, n_days: int):
        hz = horizon(menu, month)
        if hz is None:
            return None
        if menu not in panels:
            panels[menu] = _panel_span(inputs.records, list(hz[2]))
        panel = panels[menu]
        rows = panel[panel.index >= pd.Timestamp(hz[0][0])].iloc[:n_days]
        if len(rows) < n_days or rows.isna().any().any():
            return None
        return list(rows.index), rows.to_numpy(dtype=float)

    spy = inputs.records["SPY"]
    spy_tr = pd.Series(spy["tr_index"].to_numpy(dtype=float), index=pd.to_datetime(spy["date"]))
    return horizon, span, spy_tr, inputs.cpi, inputs.dgs10


# ------------------------------------------------------------------------------ run checks


class RunNotReady(RuntimeError):
    """The run directory fails `check_run`; `problems` says how."""

    def __init__(self, problems: Sequence[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = list(problems)


def read_parent(run_dir: str | Path) -> dict[str, Any] | None:
    from portfoliosight.research.fixedrisk import manifest

    path = Path(run_dir) / "parent.json"
    return manifest.read_parent(Path(run_dir)) if path.is_file() else None


def check_run(run_dir: str | Path, parent: Mapping[str, Any] | None) -> list[str]:
    """Why the run directory is not a complete run of its parent manifest (empty when it is):
    missing, incomplete or foreign-digest jobs, missing task files, unexpected job directories."""
    root = Path(run_dir)
    if parent is None:
        return [f"{root} has no parent manifest (parent.json); nothing can be checked"]
    digest = parent["digest"]
    expected = dict(parent["jobs"])
    problems = []
    present = sorted(
        p.name
        for p in root.iterdir()
        if p.is_dir() and ((p / "tasks").is_dir() or (p / "job.json").is_file())
    )
    for name in present:
        if name not in expected:
            problems.append(f"unexpected job directory {name} (not a job of the parent manifest)")
    for key, job in sorted(expected.items()):
        directory = root / key
        info_path = directory / "job.json"
        if not info_path.is_file():
            problems.append(f"job {key} has not run (no job manifest)")
            continue
        info = json.loads(info_path.read_text())
        if info.get("parent_digest") != digest:
            problems.append(
                f"job {key} ran under another parent digest {info.get('parent_digest')}"
            )
            continue
        if info.get("status") != "complete":
            breach = info.get("breach")
            problems.append(
                f"job {key} is {info.get('status')} ({info.get('tasks_done')}/"
                f"{info.get('tasks_total')} tasks, {info.get('tasks_failed')} failed"
                + (f", breach {breach.get('rule')}" if breach else "")
                + ")"
            )
        schedule = parent["menus"][job["menu"]]["schedule"]
        markers = sorted((directory / "tasks").glob("*.parquet"))
        own = [m for m in markers if M._task_digest(m) == digest]
        if len(own) != len(schedule):
            problems.append(f"job {key} has {len(own)} of {len(schedule)} task files")
        if len(own) != len(markers):
            problems.append(
                f"job {key} has {len(markers) - len(own)} task files of another parent digest"
            )
    return problems


def run_report(
    run_dir: str | Path,
    *,
    horizon: R.HorizonFn,
    span: R.SpanFn | None,
    cpi: pd.Series | None,
    spy_tr: pd.Series | None,
    dgs10: pd.Series | None,
    disjoint: Mapping[str, Sequence[Any]] | None = None,
    study_options: Mapping[str, Any] | None = None,
    parent: Mapping[str, Any] | None = None,
    allow_partial: bool = False,
    **kwargs: Any,
) -> str:
    """Check the run against its parent manifest, then build the report.

    A run failing `check_run` raises `RunNotReady` unless `allow_partial`, which builds an interim
    report from the expected jobs' task files of the parent's digest. The parent's frozen CSCV
    masks and disjoint intervals are used (`disjoint` overrides the latter).
    """
    parent = parent if parent is not None else read_parent(run_dir)
    problems = check_run(run_dir, parent)
    if problems and not allow_partial:
        raise RunNotReady(problems)
    if parent is not None:
        tables = M.load_run(run_dir, digest=parent["digest"], jobs=sorted(parent["jobs"]))
        menus = parent["menus"]
        frozen = {m: facts["cscv"] for m, facts in menus.items() if "cscv" in facts}
        if disjoint is None:
            disjoint = {m: facts["disjoint_intervals"] for m, facts in menus.items()}
    else:
        tables, frozen = M.load_run(run_dir), {}
    realized = R.realized_table(
        tables.selections, horizon, span=span, cpi=cpi, spy_tr=spy_tr, dgs10=dgs10
    )
    study = M.Study(
        tables, realized, disjoint=disjoint, cscv_frozen=frozen, **(study_options or {})
    )
    return build_report(study, interim=problems if problems else None, **kwargs)


def main(argv: Sequence[str] | None = None, study_options: Mapping[str, Any] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--snapshot", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument(
        "--allow-partial",
        action="store_true",
        help="write a labelled interim report when the run is incomplete or inconsistent",
    )
    args = parser.parse_args(argv)
    parent = read_parent(args.run_dir)
    problems = check_run(args.run_dir, parent)
    if problems and not args.allow_partial:
        print("refusing to report on an incomplete or inconsistent run:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        print("(--allow-partial writes a labelled interim report)", file=sys.stderr)
        return 2
    import importlib

    data = importlib.import_module("portfoliosight.research.fixedrisk.data")  # lazily, by name

    inputs = data.load_inputs(args.snapshot)
    if parent is not None and inputs.manifest_sha256 != parent["snapshot"]["manifest_sha256"]:
        print(
            f"snapshot {args.snapshot} has digest {inputs.manifest_sha256}, the parent manifest "
            f"names {parent['snapshot']['manifest_sha256']}",
            file=sys.stderr,
        )
        return 2
    horizon, span, spy_tr, cpi, dgs10 = make_callables(inputs, data)
    text = run_report(
        args.run_dir,
        horizon=horizon,
        span=span,
        cpi=cpi,
        spy_tr=spy_tr,
        dgs10=dgs10,
        study_options=study_options,
        parent=parent,
        allow_partial=args.allow_partial,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
