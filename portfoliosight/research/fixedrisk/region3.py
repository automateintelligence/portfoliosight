"""The region check of fixed-risk experiment v3, an exploratory addendum
(docs/plans/2026-11-09-fixed-risk-v3-region-check.md, with its corrections of 2026-11-09, which
govern where they differ from the text above them). EXPLORATORY ONLY: no result here is a
finding, and nothing here can change the v3 verdict.

Per cell (an eligible start month and one of the six risk settings):

- the frontier mix F is arm 1's locked row, with model return `mu_F` and risk target `r`;
- the region is every distinct main-pool mix of the start month, recorded under any risk setting
  (correction 2: one simulated bank per month, so a mix's `mu`, `sigma`, `tdd`, `enb` and `h`
  depend on its weights and the month alone), with `mu >= mu_F - 50 bp` and
  `sigma <= r (1 + TAU_R) + FEASIBILITY_TOL` (correction 1); rows with the same weights after
  rounding to 1e-9 count once, the first in (risk setting, record) order; only allowed mixes
  enter (correction 5: `in_domain`, the rule of `anchors.Geometry.in_domain`), so every pick,
  the mix ceiling and the same-line and predictiveness sets are allowed mixes;
- the left tip L blends F towards the frontier selection one setting lower,
  `L = F + t (F_lower - F)` with `t = clip(0.005 / (mu_F - mu_F_lower), 0, 1)`, 1 when
  `mu_F <= mu_F_lower`; the lowest setting has no L;
- the 15 rules (`rules`) pick the region mix with the lowest weighted average rank of `tdd`
  (lower is better), `enb` (higher is better) and `h` (lower is better), ties to the higher `mu`,
  then the first row; one extra pick, the fair drawdown rule on the region's mixes on the cell's
  own risk line (recorded in the wide band under the cell's setting);
- the mix ceiling is the region mix with the smallest realized drawdown.

Realized outcomes are `realized.realized_table`'s monthly rebalanced gross `ret_m` and `dd_m`
from each mix's weights, the code path `v3-analyze` uses for a selection. Across cells
(`assemble`): paired differences against L and against F with v3's bootstrap
(`analysis3._estimate`: levels within a start month, then start months; block 24, 2,000
resamples, seed 20261201), the rule ceiling (the rule with the largest mean drawdown improvement
over L), the predictiveness correlations (a mean over valid cells, each weighted equally,
with the same bootstrap's resampled start months; correction 8) and the decision rules (`decide`).
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from scipy import stats

from portfoliosight.research import evidence
from portfoliosight.research.fixedrisk import analysis3 as A
from portfoliosight.research.fixedrisk import contracts as C
from portfoliosight.research.fixedrisk import ensemble3 as E
from portfoliosight.research.fixedrisk import realized as R
from portfoliosight.research.fixedrisk.pool import read_weights

EXPLORATORY = "EXPLORATORY"
SPEC = "docs/plans/2026-11-09-fixed-risk-v3-region-check.md"
NOTICE = (
    "Exploratory region check (addendum of 2026-11-09 with its corrections): computed after the "
    "v3 result on the same 234 start months; no result here is a finding, and a promising rule "
    "is at most a candidate for one held-out confirmation on the TSP menu."
)
REGION_SCOPE = "every main-pool mix of the start month, under any of the six risk settings"
SCOPE_CHECK = (
    "one bank, geometry, history and torsion basis per start month serve every risk setting "
    "(driver3.run_task, search3.search_origin_v3); rescoring pool rows of all six settings "
    "with one scorer reproduced their recorded mu, sigma, tdd, enb and h exactly"
)
RETURN_FLOOR = 0.005  # region: mu >= mu_F - 50 bp
LEFT_TIP_STEP = 0.005  # L gives up 50 bp of model return
MIN_LINE_MIXES = 20  # predictiveness: cells with at least 20 same-line mixes
OBJECTIVES = ("tdd", "enb", "h")
ORIENT = {"tdd": 1.0, "enb": -1.0, "h": 1.0}  # rank 1 is the best
RULE_STEP = 0.25
RULE_NAMES: dict[tuple[float, float, float], str] = {
    (1.0, 0.0, 0.0): "fair_drawdown",
    (0.0, 1.0, 0.0): "enb",
    (0.5, 0.5, 0.0): "owners_blend",
    (0.0, 0.0, 1.0): "history",
}
FAIR = np.array([[1.0, 0.0, 0.0]])
F, L = "F", "L"
SAME_LINE = "fair_drawdown_same_line"
MIX_CEILING = "mix_ceiling"
RULE_CEILING = "rule_ceiling"
CLOSED_MIX = (
    "closed: no mix in the region, even picked with hindsight, beats lowering the risk setting"
)
CLOSED_RULES = "closed for these three measures: no further experiment recommended"
CANDIDATE = (
    "not a finding: the rule ceiling's rule is a candidate for one held-out confirmation on the "
    "TSP menu; the owner decides"
)
CLOSED_RETURN = "closed for these measures: fails the return condition"
UNDETERMINED = "undetermined: no paired cells"
POOL_COLUMNS = ("record", "lookback", "seed", "r_fraction", "lam", "in_wide", "weights",
                "sigma", "mu", *OBJECTIVES)  # fmt: skip
MODEL = ("sigma", "mu", "tdd", "enb", "h")


def rules() -> np.ndarray:
    """The 15 weight triples (tdd, enb, h) of the simplex grid with step 0.25."""
    return A.simplex_weights(len(OBJECTIVES), RULE_STEP)


def rule_id(w: Any) -> str:
    return "_".join(f"{o}{float(x):.2f}" for o, x in zip(OBJECTIVES, w, strict=True))


RULE_NAMES_ID = {name: rule_id(w) for w, name in RULE_NAMES.items()}


def risk_ceiling(r: float) -> float:
    """The wide band's upper edge (correction 1)."""
    return r * (1.0 + C.TAU_R) + C.FEASIBILITY_TOL


def below_line(sigma: Any, r: float) -> np.ndarray:
    """Below the wide band (correction 4)."""
    return np.asarray(sigma, dtype=float) < r * (1.0 - C.TAU_R)


def left_tip_t(mu_f: float, mu_lower: float) -> float:
    """The blend weight of the lower setting's frontier selection in L."""
    step = mu_f - mu_lower
    if step <= 0.0:
        return 1.0
    return float(np.clip(LEFT_TIP_STEP / step, 0.0, 1.0))


def left_tip(w_f: np.ndarray, w_lower: np.ndarray, t: float) -> np.ndarray:
    w_f = np.asarray(w_f, dtype=float)
    return w_f + t * (np.asarray(w_lower, dtype=float) - w_f)


# ------------------------------------------------------------------------------ the pool


def read_month_pool(path: Path) -> pd.DataFrame:
    """A start month's main-pool rows (3-year lookback, the main seed, no penalty weight or the
    main one) in every band, with their weights (one array per row)."""
    table = pq.read_table(
        path, columns=list(POOL_COLUMNS),
        filters=[("lookback", "==", C.LOOKBACK), ("seed", "==", C.PRIMARY_SEED)],
    )  # fmt: skip
    lam = np.asarray(table.column("lam").to_numpy(zero_copy_only=False), dtype=float)
    table = table.filter(pa.array(np.isnan(lam) | np.isclose(lam, C.LAMBDA)))
    weights = read_weights(table)
    frame = table.drop_columns(["weights"]).to_pandas()
    frame["weights"] = list(weights)
    return frame


def in_domain(weights: Any, lower: Any, upper: Any) -> np.ndarray:
    """Per row of `weights`, `anchors.Geometry.in_domain`'s rule: every weight within its bounds
    and the weights summing to one (an exact sum), each within `FEASIBILITY_TOL`."""
    w = np.atleast_2d(np.asarray(weights, dtype=float))
    lo, hi = np.asarray(lower, dtype=float), np.asarray(upper, dtype=float)
    box = (w >= lo - C.FEASIBILITY_TOL).all(axis=1) & (w <= hi + C.FEASIBILITY_TOL).all(axis=1)
    budget = np.array(
        [abs(math.fsum(row.tolist()) - 1.0) <= C.FEASIBILITY_TOL for row in w], dtype=bool
    )
    return box & budget


def _level(r_fraction: Any) -> np.ndarray:
    rf = np.round(np.asarray(r_fraction, dtype=float), 6)
    index = {v: j for j, v in enumerate(A.RFS)}
    return np.array([index.get(float(v), -1) for v in rf], dtype=np.int64)


def _undefined(pool: pd.DataFrame) -> int:
    """Rows of `pool` without one of the model measures."""
    return int(np.asarray(pool[list(MODEL)].isna().any(axis=1)).sum())


def distinct_mixes(pool: pd.DataFrame) -> pd.DataFrame:
    """The month's distinct mixes in tie order (risk setting ascending, then record): rows whose
    weights agree after rounding to 1e-9 count once, the first kept. `line_mask` has bit j set
    when any copy was recorded in the wide band under risk setting `A.RFS[j]`. A row without
    `mu`, `sigma`, `tdd`, `enb` or `h` is an error (correction 7), never left out."""
    missing = _undefined(pool)
    if missing:
        raise ValueError(f"{missing} row(s) lack a model measure (mu, sigma, tdd, enb or h)")
    p = A._frame(pool.sort_values(["r_fraction", "record"], kind="stable"))
    if p.empty:
        return p.assign(line_mask=np.zeros(0, dtype=np.int64)).reset_index(drop=True)
    w = np.vstack(p["weights"].to_list())
    keys = [row.tobytes() for row in np.round(w, A.WEIGHT_DECIMALS) + 0.0]
    level = _level(p["r_fraction"])
    bits = np.where(p["in_wide"].astype(bool).to_numpy() & (level >= 0),
                    np.left_shift(1, np.maximum(level, 0)), 0).astype(np.int64)  # fmt: skip
    masks: dict[bytes, int] = {}
    for k, b in zip(keys, bits.tolist(), strict=True):
        masks[k] = masks.get(k, 0) | int(b)
    first = ~pd.Series(keys).duplicated(keep="first").to_numpy()
    out = p.loc[p.index[first]].reset_index(drop=True)
    out["line_mask"] = [masks[k] for k, keep in zip(keys, first, strict=True) if keep]
    return out


def region_positions(mixes: pd.DataFrame, mu_f: float, r: float) -> np.ndarray:
    """Positions (in `mixes`) of the cell's region: the return floor and the risk ceiling."""
    mu = mixes["mu"].to_numpy(dtype=float)
    sigma = mixes["sigma"].to_numpy(dtype=float)
    return np.flatnonzero((mu >= mu_f - RETURN_FLOOR) & (sigma <= risk_ceiling(r)))


def rule_picks(
    tdd: np.ndarray, enb: np.ndarray, h: np.ndarray, mu: np.ndarray, weights: np.ndarray
) -> np.ndarray:
    """Per rule (row of `weights`), the position of the mix with the lowest weighted rank; ties
    to the higher `mu`, then the first position.

    Ranks are average ranks (1 the best, multiples of 1/2) and weights multiples of 1/4, so the
    scores are sums of multiples of 1/8 that floating point holds exactly: equal scores tie."""
    raw = np.column_stack(
        [stats.rankdata(ORIENT[o] * np.asarray(x, dtype=float))
         for o, x in zip(OBJECTIVES, (tdd, enb, h), strict=True)]
    )  # fmt: skip
    scores = raw @ np.asarray(weights, dtype=float).T
    neg_mu = -np.asarray(mu, dtype=float)
    order = np.arange(len(neg_mu))
    return np.array(
        [int(np.lexsort((order, neg_mu, scores[:, c]))[0]) for c in range(scores.shape[1])],
        dtype=np.int64,
    )


def mix_ceiling(dd: np.ndarray) -> int | None:
    """The position of the smallest finite realized drawdown (the first of equals)."""
    d = np.asarray(dd, dtype=float)
    ok = np.flatnonzero(np.isfinite(d))
    return None if not len(ok) else int(ok[np.argmin(d[ok])])


def cell_spearman(x: np.ndarray, y: np.ndarray, minimum: int = MIN_LINE_MIXES) -> float:
    """Spearman's rank correlation over the finite pairs; NaN with fewer than `minimum` pairs
    or a constant side."""
    x, y = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    ok = np.isfinite(x) & np.isfinite(y)
    if ok.sum() < minimum or np.ptp(x[ok]) == 0.0 or np.ptp(y[ok]) == 0.0:
        return float("nan")
    return float(stats.spearmanr(x[ok], y[ok]).statistic)


# ---------------------------------------------------------------------------- one month


def _weights(row: Any) -> np.ndarray | None:
    w = row.get("weights")
    return None if w is None or len(w) == 0 else np.asarray(w, dtype=float)


def month_cells(
    pool: pd.DataFrame,
    frontier: pd.DataFrame,
    *,
    menu: str,
    month: str,
    horizon: R.HorizonFn,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """The picks and cell facts of one start month.

    `pool` holds the month's allowed main-pool rows (`read_month_pool`, then `in_domain`, as
    `region_job` reads them). `frontier` holds arm 1's locked rows (`analysis3.locked_rows`).
    Returns the picks (one row per cell and name: F, L, every rule id, the same-line pick and
    the mix ceiling, with the pool `record` (-1 for F and L), realized `dd` and `ret`, and model
    `sigma`, `mu`, `enb` and `below`) and the cells (`t`, region and same-line counts, the two
    Spearman correlations)."""
    keep = (
        (frontier["arm"] == C.FRONTIER).to_numpy()
        & (frontier["month"].astype(str) == month).to_numpy()
        & frontier["status"].isin(C.V3_USABLE).to_numpy()
    )
    sel = A._frame(frontier.loc[keep])
    by_rf = {round(float(row["r_fraction"]), 6): row for row in sel.to_dict("records")}
    mixes = distinct_mixes(pool)
    model = {name: mixes[name].to_numpy(dtype=float) for name in MODEL}
    line_mask = mixes["line_mask"].to_numpy(dtype=np.int64)
    records = mixes["record"].to_numpy(dtype=np.int64)
    rule_w = rules()
    ids = [rule_id(w) for w in rule_w]

    plans: list[dict[str, Any]] = []
    extra: dict[str, np.ndarray] = {}
    need: set[int] = set()
    origin = None
    for j, rf in enumerate(A.RFS):
        f = by_rf.get(rf)
        w_f = None if f is None else _weights(f)
        if f is None or w_f is None:
            continue
        origin = f["origin"]
        r, mu_f = float(f["r"]), float(f["mu"])
        extra[f"{F}|{rf}"] = w_f
        t = float("nan")
        lower = by_rf.get(A.RFS[j - 1]) if j else None
        w_lower = None if lower is None else _weights(lower)
        if lower is not None and w_lower is not None:
            t = left_tip_t(mu_f, float(lower["mu"]))
            extra[f"{L}|{rf}"] = left_tip(w_f, w_lower, t)
        region = region_positions(mixes, mu_f, r)
        picked: dict[str, int] = {}
        if len(region):
            got = rule_picks(model["tdd"][region], model["enb"][region], model["h"][region],
                             model["mu"][region], rule_w)  # fmt: skip
            picked = {i: int(region[g]) for i, g in zip(ids, got, strict=True)}
            on = region[(line_mask[region] >> j) & 1 == 1]
            if len(on):
                g = rule_picks(model["tdd"][on], model["enb"][on], model["h"][on],
                               model["mu"][on], FAIR)[0]  # fmt: skip
                picked[SAME_LINE] = int(on[g])
        line = np.flatnonzero((line_mask >> j) & 1 == 1)
        need.update(region.tolist())
        need.update(line.tolist())
        plans.append({"rf": rf, "f": f, "r": r, "t": t, "region": region, "line": line,
                      "picked": picked})  # fmt: skip

    dd = np.full(len(mixes), np.nan)
    ret = np.full(len(mixes), np.nan)
    outcome: dict[str, tuple[float, float]] = {}
    if plans:
        positions = sorted(need)
        frame = pd.DataFrame(
            {"sel_id": [*(f"m|{p}" for p in positions), *extra],
             "menu": menu, "month": month, "origin": origin,
             "weights": [*(list(mixes.at[p, "weights"]) for p in positions),
                         *(list(w) for w in extra.values())]}
        )  # fmt: skip
        got = R.realized_table(frame, horizon, multi_years=()).set_index("sel_id")
        if positions:
            keys = [f"m|{p}" for p in positions]
            dd[positions] = got.loc[keys, "dd_m"].to_numpy(dtype=float)
            ret[positions] = got.loc[keys, "ret_m"].to_numpy(dtype=float)
        for key in extra:
            outcome[key] = (float(got.at[key, "dd_m"]), float(got.at[key, "ret_m"]))

    nan = float("nan")
    pick_rows: list[dict[str, Any]] = []
    cell_rows: list[dict[str, Any]] = []
    for plan in plans:
        rf, f, r = plan["rf"], plan["f"], plan["r"]

        def mix_row(name: str, p: int, rf=rf, r=r) -> dict[str, Any]:
            return {"month": month, "rf": rf, "name": name, "record": int(records[p]),
                    "dd": dd[p], "ret": ret[p], "sigma": model["sigma"][p],
                    "mu": model["mu"][p], "enb": model["enb"][p],
                    "below": float(below_line(model["sigma"][p], r))}  # fmt: skip

        d_f, r_f = outcome[f"{F}|{rf}"]
        sigma_f = float(f.get("sigma", nan))
        pick_rows.append({"month": month, "rf": rf, "name": F, "record": -1, "dd": d_f,
                          "ret": r_f, "sigma": sigma_f, "mu": float(f["mu"]),
                          "enb": float(f.get("enb", nan)),
                          "below": float(below_line(sigma_f, r))})  # fmt: skip
        if f"{L}|{rf}" in outcome:
            d_l, r_l = outcome[f"{L}|{rf}"]
            pick_rows.append(
                {
                    "month": month,
                    "rf": rf,
                    "name": L,
                    "record": -1,
                    "dd": d_l,
                    "ret": r_l,
                    "sigma": nan,
                    "mu": nan,
                    "enb": nan,
                    "below": nan,
                }
            )
        for name, p in plan["picked"].items():
            pick_rows.append(mix_row(name, p))
        region, line = plan["region"], plan["line"]
        best = mix_ceiling(dd[region]) if len(region) else None
        if best is not None:
            pick_rows.append(mix_row(MIX_CEILING, int(region[best])))
        cell_rows.append(
            {"month": month, "rf": rf, "t": plan["t"], "region": int(len(region)),
             "line": int(len(line)),
             "rho_dd": cell_spearman(model["tdd"][line], dd[line]),
             "rho_ret": cell_spearman(model["mu"][line], ret[line])}
        )  # fmt: skip
    return pd.DataFrame(pick_rows), pd.DataFrame(cell_rows)


# ----------------------------------------------------------------------- across months


def _grid(frame: pd.DataFrame, column: str, months: Sequence[str]) -> np.ndarray:
    """(levels x months) values of `column`, NaN where a cell has no row."""
    g = np.full((len(A.RFS), len(months)), np.nan)
    if frame.empty:
        return g
    pos = {m: o for o, m in enumerate(months)}
    o = np.array([pos.get(str(m), -1) for m in frame["month"]], dtype=np.int64)
    j = _level(frame["rf"])
    ok = (o >= 0) & (j >= 0)
    g[j[ok], o[ok]] = _floats(frame[column])[ok]
    return g


def paired(
    boot: evidence.Bootstrap,
    ref: tuple[np.ndarray, np.ndarray],
    pick: tuple[np.ndarray, np.ndarray],
) -> dict[str, Any]:
    """The mean paired difference in realized drawdown (reference minus pick: positive means
    the pick fell less) and return (pick minus reference) over the cells where both have both,
    with the v3 bootstrap: a two-sided 95% interval for each and the one-sided 95% lower bound
    of the return difference."""
    (dd_ref, ret_ref), (dd, ret) = ref, pick
    ok = np.isfinite(dd_ref) & np.isfinite(ret_ref) & np.isfinite(dd) & np.isfinite(ret)
    d_dd = np.where(ok, dd_ref - dd, np.nan)
    d_ret = np.where(ok, ret - ret_ref, np.nan)
    e_dd = A._estimate(boot, d_dd, 0.95)
    e_ret = A._estimate(boot, d_ret, 0.95)
    e_ret90 = A._estimate(boot, d_ret, 0.90)
    return {
        "paired_cells": int(ok.sum()),
        "theta_dd": e_dd.value,
        "theta_dd_interval": list(e_dd.intervals[evidence.BLOCK]),
        "theta_ret": e_ret.value,
        "theta_ret_interval": list(e_ret.intervals[evidence.BLOCK]),
        "theta_ret_lower_95": e_ret90.lower(evidence.BLOCK),
    }


def _floats(values: Any) -> np.ndarray:
    return np.asarray(pd.to_numeric(values, errors="coerce"), dtype=float)


def _mean(values: Any) -> float | None:
    x = _floats(values)
    x = x[np.isfinite(x)]
    return float(x.mean()) if x.size else None


def _model(rows: pd.DataFrame) -> dict[str, Any]:
    return {"cells": int(len(rows)), "sigma": _mean(rows["sigma"]), "mu": _mean(rows["mu"]),
            "enb": _mean(rows["enb"]), "below_line_share": _mean(rows["below"])}  # fmt: skip


def decide(
    mix_dd: float | None,
    rule_dd: float | None,
    rule_dd_interval: Sequence[float | None],
    rule_ret_lower: float | None,
) -> dict[str, Any]:
    """The decision rules fixed in the addendum, with correction 3, against L."""
    if mix_dd is None or rule_dd is None:
        return {"rule": None, "label": UNDETERMINED}
    if mix_dd < A.DD_LINE:
        return {"rule": "1", "label": CLOSED_MIX}
    low = rule_dd_interval[0]
    if rule_dd < A.DD_LINE or low is None or low <= 0.0:
        return {"rule": "2", "label": CLOSED_RULES}
    if rule_ret_lower is not None and rule_ret_lower >= A.RET_LINE:
        return {"rule": "3", "label": CANDIDATE}
    return {"rule": "correction 3", "label": CLOSED_RETURN}


def _predictive(boot: evidence.Bootstrap, grid: np.ndarray) -> dict[str, Any]:
    """The mean over the valid cells of a (levels x months) grid, each cell weighted equally
    (correction 8), with a 95% interval from resampled start months: per resample, the sum of
    the valid cell values over its months divided by their count."""
    ok = np.isfinite(grid)
    total = np.where(ok, grid, 0.0).sum(axis=0)
    count = ok.sum(axis=0).astype(float)

    def mean(index: np.ndarray) -> np.ndarray:
        n = count[index].sum(axis=1)
        return np.where(n > 0, total[index].sum(axis=1) / np.maximum(n, 1.0), np.nan)

    e = boot.estimate(mean, 0.95, evidence._count(grid))
    finite = grid[ok]
    return {"cells": int(finite.size), "mean": e.value,
            "interval": list(e.intervals[evidence.BLOCK]),
            "positive_share": float(np.mean(finite > 0.0)) if finite.size else None}  # fmt: skip


def assemble(
    picks: pd.DataFrame,
    cells: pd.DataFrame,
    months: Sequence[str],
    *,
    resamples: int = evidence.RESAMPLES,
    seed: int = evidence.BOOTSTRAP_SEED,
) -> dict[str, Any]:
    """The statistics of every pick and ceiling against L and F, the rule ceiling, the
    predictiveness and the decision, over the (levels x months) cells; `months` is the
    chronological index of the bootstrap."""
    months = [str(m) for m in months]
    boot = evidence.Bootstrap(len(months), blocks=(evidence.BLOCK,), resamples=resamples,
                              seed=seed)  # fmt: skip

    def rows(name: str) -> pd.DataFrame:
        return A._frame(picks.loc[(picks["name"] == name).to_numpy()]) if not picks.empty \
            else picks  # fmt: skip

    def grids(name: str) -> tuple[np.ndarray, np.ndarray]:
        sub = rows(name)
        return _grid(sub, "dd", months), _grid(sub, "ret", months)

    ref = {L: grids(L), F: grids(F)}
    names = [*(rule_id(w) for w in rules()), SAME_LINE, MIX_CEILING]
    out: dict[str, Any] = {}
    for name in names:
        weights = None
        if name not in (SAME_LINE, MIX_CEILING):
            weights = dict(zip(OBJECTIVES, map(float, name_weights(name)), strict=True))
        g = grids(name)
        out[name] = {
            "weights": weights,
            "named": RULE_NAMES.get(name_weights(name)) if weights else None,
            "vs_L": paired(boot, ref[L], g),
            "vs_F": paired(boot, ref[F], g),
            "model": _model(rows(name)),
        }
    rule_names = names[: len(rules())]
    values = [out[n]["vs_L"]["theta_dd"] for n in rule_names]
    best = None
    for n, v in zip(rule_names, values, strict=True):
        if v is not None and (best is None or v > out[best]["vs_L"]["theta_dd"]):
            best = n
    out[RULE_CEILING] = dict(out[best]) if best is not None else None
    ceiling = out[RULE_CEILING] or {}
    mix = out[MIX_CEILING]["vs_L"]
    vs_l = ceiling.get("vs_L", {})
    decision = decide(mix["theta_dd"], vs_l.get("theta_dd"),
                      vs_l.get("theta_dd_interval", (None, None)),
                      vs_l.get("theta_ret_lower_95"))  # fmt: skip
    return {
        "picks": out,
        "rule_ceiling": {
            "rule": best,
            "named": ceiling.get("named"),
            "chosen_from": len(rule_names),
        },  # fmt: skip
        "predictiveness": {
            "min_mixes": MIN_LINE_MIXES,
            "tdd_vs_dd": _predictive(boot, _grid(cells, "rho_dd", months)),
            "mu_vs_ret": _predictive(boot, _grid(cells, "rho_ret", months)),
        },
        "decision": decision,
    }


def name_weights(name: str) -> tuple[float, float, float]:
    """The weight triple of a rule id (`rule_id`'s inverse)."""
    parts = name.split("_")
    values = [float(p[len(o) :]) for o, p in zip(OBJECTIVES, parts, strict=True)]
    return values[0], values[1], values[2]


# -------------------------------------------------------------------------------- one job


def record_region(job_dir: Path, region_path: Path) -> dict[str, Any]:
    """Add the region check's SHA-256 to the job's analysis record, after its analysis entry."""
    record = E._read_record(job_dir)
    if "analysis" not in record:
        raise ValueError(f"{Path(job_dir) / E.RECORD_FILE} has no analysis entry")
    record["region"] = E._entry(region_path)
    E._write_record(job_dir, record)
    return record


def region_job(
    job_dir: Path,
    parent: Mapping[str, Any],
    menu: str,
    engine: str,
    horizon: R.HorizonFn,
    *,
    bounds: tuple[Sequence[float], Sequence[float]],
    analysis_path: Path | None = None,
    months: Sequence[str] | None = None,
    resamples: int = evidence.RESAMPLES,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """The region check of one job; refuses to read a realized outcome before the confirmatory
    analysis' digest is recorded (`ensemble3.verified_entry`). `bounds` are the menu's (lower,
    upper) weight bounds in holding order; rows outside them (`in_domain`) are left out and
    counted. `months` restricts the eligible start months (a smoke run); the bootstrap index
    stays the job's schedule."""
    from portfoliosight.research.fixedrisk.driver3 import base_paths

    job_dir = Path(job_dir)
    analysis = E.verified_entry(job_dir, "analysis", analysis_path)
    schedule = [str(m) for m in parent["menus"][menu]["schedule"]]
    eligible = set(A.eligible_origins(parent, menu))
    if months is not None:
        unknown = sorted({str(m) for m in months} - eligible)
        if unknown:
            raise ValueError(f"not eligible start months of {menu}: {unknown}")
    wanted = eligible if months is None else {str(m) for m in months}
    chosen = [m for m in schedule if m in wanted]
    tables = A.load_tables(job_dir, parent["digest"])
    frontier = A.locked_rows(tables["selections"])
    frontier = A._frame(frontier.loc[(frontier["arm"] == C.FRONTIER).to_numpy()])
    pick_parts, cell_parts = [], []
    removed = 0
    for month in chosen:
        path = base_paths(job_dir / "tasks", f"{menu}_{month}_{engine}")["pool"]
        pool = read_month_pool(path)
        allowed = in_domain(np.vstack(pool["weights"].to_list()), *bounds) if len(pool) else \
            np.zeros(0, dtype=bool)  # fmt: skip
        removed += int((~allowed).sum())
        pool = A._frame(pool.loc[allowed]).reset_index(drop=True)
        missing = _undefined(pool)
        if missing:
            raise ValueError(
                f"{month}: {missing} allowed main-pool row(s) lack a model measure "
                "(mu, sigma, tdd, enb or h); the region check stops (correction 7)"
            )
        p, c = month_cells(pool, frontier, menu=menu, month=month, horizon=horizon)
        pick_parts.append(p)
        cell_parts.append(c)
        if progress is not None:
            sizes = c["region"].tolist() if not c.empty else []
            progress(f"{month}: {len(pool)} main rows, regions {sizes}")
        del pool
    picks = pd.concat(pick_parts, ignore_index=True) if pick_parts else pd.DataFrame()
    cells = pd.concat(cell_parts, ignore_index=True) if cell_parts else pd.DataFrame()
    body = assemble(picks, cells, schedule, resamples=resamples)
    sizes = cells["region"].to_numpy(dtype=float) if not cells.empty else np.zeros(0)
    left = cells["t"].to_numpy(dtype=float) if not cells.empty else np.zeros(0)
    return {
        "label": EXPLORATORY,
        "notice": NOTICE,
        "spec": SPEC,
        "job": job_dir.name,
        "parent_digest": parent["digest"],
        "analysis_sha256": E.sha256_file(analysis),
        "months": chosen,
        "months_restricted": months is not None,
        "cells": int(len(cells)),
        "cells_with_left_tip": int(np.isfinite(left).sum()),
        "region_scope": REGION_SCOPE,
        "region_scope_check": SCOPE_CHECK,
        "definitions": {
            "return_floor": RETURN_FLOOR,
            "risk_ceiling": "r * (1 + TAU_R) + FEASIBILITY_TOL",
            "tau_r": C.TAU_R,
            "feasibility_tol": C.FEASIBILITY_TOL,
            "below_line": "sigma < r * (1 - TAU_R)",
            "left_tip_step": LEFT_TIP_STEP,
            "rule_step": RULE_STEP,
            "objectives": list(OBJECTIVES),
            "block": evidence.BLOCK,
            "resamples": resamples,
            "seed": evidence.BOOTSTRAP_SEED,
        },  # fmt: skip
        "domain_removed_rows": removed,
        "region_size": {
            "median": float(np.median(sizes)) if sizes.size else None,
            "min": int(sizes.min()) if sizes.size else None,
            "max": int(sizes.max()) if sizes.size else None,
        },
        "left_tip_t": {
            "mean": float(np.mean(left[np.isfinite(left)])) if np.isfinite(left).any() else None,
            "clipped_share": float(np.mean(left[np.isfinite(left)] == 1.0))
            if np.isfinite(left).any()
            else None,
        },  # fmt: skip
        **body,
    }
