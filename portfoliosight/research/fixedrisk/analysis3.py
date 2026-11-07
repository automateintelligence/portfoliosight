"""Report hooks of the v3 run (protocol v3 §5, §6, §7): realized outcomes per arm, the
confirmatory test and the descriptive statistics, from the task files.

- `load_tables`: the selections (and columns, evaluated) of a job's task files of one digest;
- `realized_outcomes`: `realized.realized_table` on the selections, with the v3 multi-year
  horizons (2, 3 and 5 years) and realized volatility;
- `arm_grid`: one arm's (6 levels x K origins) grid of a column, from the arm's locked row
  (arm 1 and arm 6 their own program's row, arms 2-5 the pooled selection);
- `confirmatory_test`: §6 exactly: equal weight over the six levels within an origin, then over
  the eligible origins; paired circular block bootstrap over the chronological origin index
  (block 24, 2,000 resamples, seed 20261201; blocks 12 and 36 as sensitivities); (A) the
  two-sided 95% interval of theta_DD above 0 and the point estimate at least 1 pp (a relevance
  filter, not a tested claim); (B) the 5th bootstrap percentile of theta_Ret at or above -50 bp;
  labels pass / fail (drawdown) / fail (return) / fail (both) / inconclusive (a verdict-blocking
  label on arm 1 or arm 3 at an eligible cell, §4.5); per-level estimates, the "pass, uneven
  across risk" flag, the point-estimate verdict, the relative drawdown change, the risk
  difference, a Newey-West (Bartlett, lag 12) interval on Delta_DD(o), and the verdict wording
  of §8.4;
- `rank_agreement`: Spearman and Kendall tau-b across the six arms between model TDD and
  realized dd_m at each (origin, r) (§5);
- `cscv_arms`: purged CSCV across the six arms on realized dd_m (§7.1, `omega = k/7`);
- `ensemble_candidates`, `ensemble_picks`, `simplex_weights`: the exploratory screen of §7.3.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

from portfoliosight.research import evidence
from portfoliosight.research.fixedrisk import contracts as C
from portfoliosight.research.fixedrisk import cscv
from portfoliosight.research.fixedrisk import realized as R

RFS = tuple(round(x, 6) for x in C.RISK_FRACTIONS)
DD_LINE = 0.01  # (A)'s relevance filter on the point estimate
RET_LINE = -0.005  # (B): the one-sided 95% lower bound of theta_Ret at or above -50 bp
NEWEY_WEST_LAG = 12
BLOCKING = (C.SEARCH_FAILED, C.ANCHOR_FAILED, C.NO_ELIGIBLE, C.FIT_FAILED)
PASS = "pass"
FAIL_DD = "fail (drawdown)"
FAIL_RET = "fail (return)"
FAIL_BOTH = "fail (both)"
INCONCLUSIVE = "inconclusive"
ENSEMBLE_OBJECTIVES = ("mu", "u1", "tdd", "h", "enlc", "enb")  # tdd and h enter negated
ENSEMBLE_SIGN = {"mu": 1.0, "u1": 1.0, "tdd": -1.0, "h": -1.0, "enlc": 1.0, "enb": 1.0}
ENSEMBLE_STEP = 0.25
WEIGHT_DECIMALS = 9  # two rows are the same mix when every weight agrees after rounding to 1e-9


# ------------------------------------------------------------------------------- loading


def load_tables(job_dir: Path, digest: str | None = None) -> dict[str, pd.DataFrame]:
    """The job's selections, columns and evaluated tables (task files of `digest` only)."""
    import pyarrow.parquet as pq

    tasks = Path(job_dir) / "tasks"
    parts: dict[str, list[pd.DataFrame]] = {"selections": [], "columns": [], "evaluated": []}
    for marker in sorted(tasks.glob("*.parquet")):
        meta = pq.read_schema(marker).metadata or {}
        if digest is not None and meta.get(b"parent_digest") != digest.encode():
            continue
        parts["selections"].append(pd.read_parquet(marker))
        for name in ("columns", "evaluated"):
            path = tasks / name / marker.name
            if path.is_file():
                parts[name].append(pd.read_parquet(path))
    return {k: pd.concat(v, ignore_index=True) if v else pd.DataFrame() for k, v in parts.items()}


def realized_outcomes(
    selections: pd.DataFrame,
    horizon: R.HorizonFn,
    *,
    span: R.SpanFn | None = None,
    cpi: pd.Series | None = None,
    spy_tr: pd.Series | None = None,
    dgs10: pd.Series | None = None,
) -> pd.DataFrame:
    """Realized figures per selection (v3 §5): 1-year return, drawdown, volatility, the 10 bp
    variant, the 2-, 3- and 5-year returns, the real 1-year return and the regime."""
    sel = selections.copy()
    sel["weights"] = sel["weights"].map(lambda w: [] if w is None else list(w))
    out = R.realized_table(
        sel, horizon, span=span, cpi=cpi, spy_tr=spy_tr, dgs10=dgs10,
        multi_years=C.V3_MULTI_YEARS,
    )  # fmt: skip
    return selections.merge(out, on="sel_id", how="left", validate="one_to_one")


# ---------------------------------------------------------------------------------- grids


def locked_rows(table: pd.DataFrame, *, kind: str = "main", lookback: str = C.LOOKBACK):
    """Each arm's locked row per (month, r_fraction): arm 1 and arm 6 their program's row, arms
    2-5 the pooled selection; arm 4 at the main lambda."""
    t = table[(table["kind"] == kind) & (table["lookback"] == lookback)]
    native_arms = (C.FRONTIER, C.ENB_KNEE, C.APP_FRONTIER)
    keep = np.where(t["arm"].isin(native_arms), ~t["pooled"].astype(bool), t["pooled"].astype(bool))
    t = t[keep]
    lam = t["lam"].astype(float)
    t = t[(t["arm"] != C.CRASH_PENALTY) | np.isclose(lam.fillna(-1.0), C.LAMBDA)]
    out = t.copy()
    out["rf"] = out["r_fraction"].astype(float).round(6)
    return out


def arm_grid(
    rows: pd.DataFrame, arm: str, column: str, months: Sequence[str], *, usable: bool = True
) -> np.ndarray:
    """(levels x K) values of `column` for `arm`, NaN where missing or (with `usable`) where the
    row's label is not a usable one."""
    grid = np.full((len(RFS), len(months)), np.nan)
    pos = {m: j for j, m in enumerate(months)}
    sub = rows[rows["arm"] == arm]
    for _, row in sub.iterrows():
        j = pos.get(str(row["month"]))
        if j is None or row["rf"] not in RFS:
            continue
        if usable and row["status"] not in C.V3_USABLE:
            continue
        value = row.get(column)
        grid[RFS.index(row["rf"]), j] = np.nan if value is None else float(value)
    return grid


def blocking_cells(
    rows: pd.DataFrame, arms: Sequence[str], months: Sequence[str]
) -> list[dict[str, Any]]:
    """Eligible (month, r) cells where an arm's row is missing or carries a verdict-blocking
    label (§4.5)."""
    found = []
    for arm in arms:
        sub = rows[rows["arm"] == arm].set_index(["month", "rf"])
        for month in months:
            for rf in RFS:
                if (month, rf) not in sub.index:
                    found.append({"arm": arm, "month": month, "rf": rf, "status": "missing"})
                    continue
                status = sub.loc[(month, rf), "status"]
                status = status.iloc[0] if isinstance(status, pd.Series) else status
                if status not in C.V3_USABLE:
                    found.append({"arm": arm, "month": month, "rf": rf, "status": status})
    return found


# ------------------------------------------------------------------------------ statistics


def newey_west(series: np.ndarray, lag: int = NEWEY_WEST_LAG) -> tuple[float, float]:
    """Mean of a series in date order and its Newey-West standard error (Bartlett kernel)."""
    x = np.asarray(series, dtype=float)
    x = x[np.isfinite(x)]
    n = len(x)
    if n < 2:
        return (float(x.mean()) if n else math.nan), math.nan
    mean = float(x.mean())
    d = x - mean
    s = float(d @ d) / n
    for k in range(1, min(lag, n - 1) + 1):
        s += 2.0 * (1.0 - k / (lag + 1.0)) * float(d[k:] @ d[:-k]) / n
    return mean, math.sqrt(max(s, 0.0) / n)


def _estimate(boot: evidence.Bootstrap, grid: np.ndarray, level: float) -> evidence.Estimate:
    return boot.estimate(lambda i: evidence.origin_mean(grid, i), level, evidence._count(grid))


def _conditions(dd: evidence.Estimate, ret90: evidence.Estimate, block: int) -> tuple[bool, bool]:
    lower_dd = dd.lower(block)
    p5 = ret90.lower(block)
    a = lower_dd is not None and lower_dd > 0.0 and dd.value is not None and dd.value >= DD_LINE
    b = p5 is not None and p5 >= RET_LINE
    return a, b


def _label(a: bool, b: bool) -> str:
    return PASS if a and b else FAIL_DD if b else FAIL_RET if a else FAIL_BOTH


def confirmatory_test(
    table: pd.DataFrame,
    months: Sequence[str],
    *,
    eligible: Sequence[str] | None = None,
    candidate: str = C.MIN_TDD,
    comparator: str = C.FRONTIER,
    blocks: Sequence[int] = evidence.BLOCKS,
    resamples: int = evidence.RESAMPLES,
    seed: int = evidence.BOOTSTRAP_SEED,
) -> dict[str, Any]:
    """The §6 test of `candidate` (arm 3) against `comparator` (arm 1); see the module docstring.

    `table` holds the selections with their realized columns (`ret_m`, `dd_m`, `complete`);
    `months` is the chronological origin index of the bootstrap (the schedule); `eligible` the
    origins with a complete realized year (default: those with a complete row).
    """
    rows = locked_rows(table)
    months = [str(m) for m in months]
    if eligible is None:
        done = rows[rows["complete"].fillna(False).astype(bool)]
        eligible = sorted(set(done["month"].astype(str)))
    eligible = [m for m in months if m in set(eligible)]
    mask = np.array([m in set(eligible) for m in months])
    k = len(months)

    def grid(arm: str, col: str) -> np.ndarray:
        g = arm_grid(rows, arm, col, months)
        g[:, ~mask] = np.nan
        return g

    dd1, dd3 = grid(comparator, "dd_m"), grid(candidate, "dd_m")
    r1, r3 = grid(comparator, "ret_m"), grid(candidate, "ret_m")
    s1, s3 = grid(comparator, "sigma"), grid(candidate, "sigma")
    paired = np.isfinite(dd1) & np.isfinite(dd3) & np.isfinite(r1) & np.isfinite(r3)
    d_dd = np.where(paired, dd1 - dd3, np.nan)
    d_ret = np.where(paired, r3 - r1, np.nan)
    with np.errstate(invalid="ignore", divide="ignore"):
        rho = np.where(paired & (dd1 > 0.0), d_dd / dd1, np.nan)
    boot = evidence.Bootstrap(k, blocks=tuple(blocks), resamples=resamples, seed=seed)
    primary = evidence.BLOCK if evidence.BLOCK in boot.blocks else boot.blocks[0]
    dd = _estimate(boot, d_dd, 0.95)
    ret95 = _estimate(boot, d_ret, 0.95)
    ret90 = _estimate(boot, d_ret, 0.90)  # its lower end is the 5th percentile
    rel = _estimate(boot, rho, 0.95)
    a, b = _conditions(dd, ret90, primary)
    blocked = blocking_cells(rows[rows["month"].isin(eligible)], (comparator, candidate), eligible)
    label = INCONCLUSIVE if blocked else _label(a, b)

    per_level = []
    for j, rf in enumerate(RFS):
        e_dd = boot.estimate(lambda i, x=d_dd[j]: evidence.cell_mean(x, i), 0.95,
                             evidence._count(d_dd[j]))  # fmt: skip
        e_ret = boot.estimate(lambda i, x=d_ret[j]: evidence.cell_mean(x, i), 0.95,
                              evidence._count(d_ret[j]))  # fmt: skip
        per_level.append(
            {"rf": rf, "n": e_dd.n, "d_dd": e_dd.value, "d_dd_interval": e_dd.intervals[primary],
             "d_ret": e_ret.value, "d_ret_interval": e_ret.intervals[primary]}
        )  # fmt: skip
    wrong = sum(
        1 for row in per_level
        if row["d_dd"] is not None and (row["d_dd"] < 0.0 or (row["d_ret"] or 0.0) < RET_LINE)
    )  # fmt: skip
    sensitivities = {}
    for block in boot.blocks:
        if block == primary:
            continue
        sa, sb = _conditions(dd, ret90, block)
        sensitivities[str(block)] = {
            "dd_interval": dd.intervals[block],
            "ret_p5": ret90.lower(block),
            "A": sa,
            "B": sb,
            "agrees": (sa, sb) == (a, b),
        }
    per_origin = evidence._masked_mean(d_dd, axis=0)[mask]
    nw_mean, nw_se = newey_west(per_origin)
    nw_interval = (nw_mean - 1.96 * nw_se, nw_mean + 1.96 * nw_se)
    nw_a = bool(nw_interval[0] > 0.0 and nw_mean >= DD_LINE)
    risk = (s3 - s1)[paired]
    r_grid = np.broadcast_to(np.array(C.RISK_FRACTIONS)[:, None], s1.shape)
    sigma_share = ((s3 - s1) / np.where(s1 > 0, s1, np.nan))[paired]
    result = {
        "candidate": candidate,
        "comparator": comparator,
        "origins_index": k,
        "eligible_origins": len(eligible),
        "paired_cells": int(paired.sum()),
        "theta_dd": dd.record(),
        "theta_ret": ret95.record(),
        "theta_ret_p5": {str(bk): ret90.lower(bk) for bk in boot.blocks},
        "A": a,
        "B": b,
        "label": label,
        "blocking_cells": blocked,
        "point_estimate_verdict": (
            PASS if (dd.value or -1) >= DD_LINE and (ret95.value or -1) >= RET_LINE else "fail"
        ),  # fmt: skip
        "uneven_across_risk": bool(label == PASS and wrong >= 3),
        "per_level": per_level,
        "sensitivities": sensitivities,
        "newey_west": {
            "lag": NEWEY_WEST_LAG,
            "mean": nw_mean,
            "se": nw_se,
            "interval": list(nw_interval),
            "A": nw_a,
            "agrees": nw_a == a,
        },  # fmt: skip
        "relative_dd": rel.record(),
        "risk_difference": {
            "mean": float(np.mean(risk)) if risk.size else None,
            "p5": float(np.percentile(risk, 5)) if risk.size else None,
            "p95": float(np.percentile(risk, 95)) if risk.size else None,
            "share_of_sigma_mean": float(np.mean(sigma_share)) if risk.size else None,
            "levels": r_grid.shape[0],
        },
    }
    result["verdict_text"] = verdict_text(result)
    return result


def verdict_text(result: Mapping[str, Any]) -> str:
    """§8.4's wording: the hypothesis' words and §6.3's, nothing stronger."""
    dd = result["theta_dd"]
    point_pp = None if dd["value"] is None else 100.0 * dd["value"]
    p5 = result["theta_ret_p5"].get(str(evidence.BLOCK))
    bound_bp = None if p5 is None else 1e4 * p5
    figures = (
        f"point estimate {point_pp:.2f} pp" if point_pp is not None else "no point estimate"
    ) + (f"; one-sided 95% lower bound of the return difference {bound_bp:.1f} bp"
         if bound_bp is not None else "")  # fmt: skip
    if result["label"] == PASS:
        return (
            "Averaged with equal weight over the six fixed risk levels and the "
            f"{result['eligible_origins']} eligible origins, the lowest-simulated-drawdown mix had "
            "a smaller realized maximum drawdown than the frontier mix (95% interval above zero; "
            f"point estimate {point_pp:.2f} pp, at least the 1 pp relevance line) and gave up no "
            f"more than 50 bp of realized annual return (one-sided 95% lower bound {bound_bp:.1f}"
            " bp)."
        )
    if result["label"] == INCONCLUSIVE:
        return (
            f"Inconclusive: {len(result['blocking_cells'])} eligible cells of arm 1 or arm 3 carry "
            f"a verdict-blocking label or are missing ({figures})."
        )
    return f"{result['label'].capitalize()}: {figures}."


def rank_agreement(
    rows: pd.DataFrame,
    months: Sequence[str],
    arms: Sequence[str] = C.V3_ARMS,
    *,
    resamples: int = evidence.RESAMPLES,
) -> dict[str, Any]:
    """Spearman and Kendall tau-b across the arms between model TDD and realized dd_m at each
    (origin, r) (§5); the mean of each over origins per level with a block-bootstrap interval."""
    months = [str(m) for m in months]
    tdd = np.stack([arm_grid(rows, arm, "tdd", months) for arm in arms])
    real = np.stack([arm_grid(rows, arm, "dd_m", months) for arm in arms])
    spear = np.full(tdd.shape[1:], np.nan)
    kend = np.full(tdd.shape[1:], np.nan)
    for j in range(tdd.shape[1]):
        for o in range(tdd.shape[2]):
            x, y = tdd[:, j, o], real[:, j, o]
            ok = np.isfinite(x) & np.isfinite(y)
            if ok.sum() >= 3 and np.ptp(x[ok]) > 0 and np.ptp(y[ok]) > 0:
                spear[j, o] = stats.spearmanr(x[ok], y[ok]).statistic
                kend[j, o] = stats.kendalltau(x[ok], y[ok]).statistic  # tau-b
    boot = evidence.Bootstrap(len(months), blocks=(evidence.BLOCK,), resamples=resamples)
    out: dict[str, Any] = {"by_level": []}
    for j, rf in enumerate(RFS):
        entry: dict[str, Any] = {"rf": rf}
        for name, grid in (("spearman", spear[j]), ("kendall", kend[j])):
            e = boot.estimate(lambda i, x=grid: evidence.cell_mean(x, i), 0.95,
                              evidence._count(grid))  # fmt: skip
            entry[name] = e.value
            entry[f"{name}_interval"] = e.intervals[evidence.BLOCK]
            entry[f"{name}_positive_share"] = (
                float(np.mean(grid[np.isfinite(grid)] > 0)) if np.isfinite(grid).any() else None
            )
        out["by_level"].append(entry)
    return out


def cscv_arms(
    rows: pd.DataFrame, frozen: Mapping[str, Any], arms: Sequence[str] = C.V3_ARMS
) -> cscv.CscvResult | None:
    """Purged CSCV across the arms on realized dd_m (§7.1); None when the masks are unavailable."""
    if "splits" not in frozen:
        return None
    masks = cscv.CscvMasks.from_manifest(dict(frozen))
    months = [str(m) for m in frozen["months"]]
    values = np.stack([arm_grid(rows, arm, "dd_m", months).T for arm in arms])  # A x K x C
    return cscv.cscv_candidates(masks, values, lower_is_better=True)


# --------------------------------------------------------------------- ensemble screen (§7.3)


def simplex_weights(k: int = len(ENSEMBLE_OBJECTIVES), step: float = ENSEMBLE_STEP) -> np.ndarray:
    """Every point of the simplex grid with `step` over `k` objectives (126 for six at 0.25)."""
    units = round(1.0 / step)
    points = [c for c in itertools.product(range(units + 1), repeat=k) if sum(c) == units]
    return np.array(points, dtype=float) / units


def ensemble_candidates(pool: pd.DataFrame) -> pd.DataFrame:
    """Per (lookback, r_fraction) of one task's pool: the distinct mixes (weights equal after
    rounding to 1e-9, represented by the lowest pool row id) among the main rows (side checks
    excluded) in the wide band with all six objectives defined, with their average-tie
    percentile ranks (`rank_<objective>`, oriented so higher is better)."""
    p = pool[(pool["lam"].isna()) | np.isclose(pool["lam"].fillna(-1.0), C.LAMBDA)]
    p = p[p["in_wide"].astype(bool)]
    p = p.dropna(subset=list(ENSEMBLE_OBJECTIVES))
    if p.empty:
        return p.assign(**{f"rank_{o}": [] for o in ENSEMBLE_OBJECTIVES})
    keys = p["weights"].map(lambda w: tuple(np.round(np.asarray(w, dtype=float),
                                                     WEIGHT_DECIMALS)))  # fmt: skip
    p = p.assign(_key=keys).sort_values("record")
    p = p.drop_duplicates(subset=["lookback", "r_fraction", "_key"], keep="first")
    parts = []
    for _, group in p.groupby(["lookback", "r_fraction"], sort=True):
        g = group.copy()
        n = len(g)
        for o in ENSEMBLE_OBJECTIVES:
            g[f"rank_{o}"] = stats.rankdata(ENSEMBLE_SIGN[o] * g[o].to_numpy(float)) / n
        parts.append(g)
    return pd.concat(parts).drop(columns="_key")


def ensemble_picks(candidates: pd.DataFrame, weights: np.ndarray) -> pd.DataFrame:
    """For each weight combination and (lookback, r_fraction), the candidate with the highest
    weighted rank score; ties to the lowest pool row id."""
    rank_cols = [f"rank_{o}" for o in ENSEMBLE_OBJECTIVES]
    out = []
    for _, group in candidates.groupby(["lookback", "r_fraction"], sort=True):
        g = group.sort_values("record")
        ranks = g[rank_cols].to_numpy(float)
        scores = ranks @ np.asarray(weights, dtype=float).T  # n x combos
        best = np.argmax(scores, axis=0)  # first maximum = lowest record
        for c, i in enumerate(best):
            row = g.iloc[int(i)]
            out.append(
                {"combination": c, "lookback": row["lookback"], "r_fraction": row["r_fraction"],
                 "record": int(row["record"]), "score": float(scores[i, c])}
            )  # fmt: skip
    return pd.DataFrame(out)


# ------------------------------------------------------------------------------- one job

SUMMARY_COLUMNS = (
    "ret_m", "dd_m", "vol_m", "ret_net", "dd_net", "real_m", "ret_2y", "ret_3y", "ret_5y",
    "sigma", "mu", "u1", "bad", "tdd", "h", "enlc", "enb", "dr2",
)  # fmt: skip


def arm_summary(rows: pd.DataFrame, arms: Sequence[str]) -> list[dict[str, Any]]:
    """Per arm and risk level, the mean of each realized and model figure over the usable rows
    with a complete realized year (realized means), or all usable rows (model means)."""
    out = []
    usable = rows[rows["status"].isin(C.V3_USABLE)]
    for arm in arms:
        for rf in RFS:
            sub = usable[(usable["arm"] == arm) & (usable["rf"] == rf)]
            done = sub[sub["complete"].fillna(False).astype(bool)] if "complete" in sub else sub
            entry: dict[str, Any] = {"arm": arm, "rf": rf, "n": int(len(sub)),
                                     "n_complete": int(len(done))}  # fmt: skip
            for col in SUMMARY_COLUMNS:
                if col not in sub:
                    continue
                source = done if col in R.REALIZED_COLUMNS else sub
                values = pd.to_numeric(source[col], errors="coerce")
                entry[col] = float(values.mean()) if values.notna().any() else None
            out.append(entry)
    return out


def diversification(rows: pd.DataFrame, months: Sequence[str]) -> dict[str, Any]:
    """Arm 3 against arm 1: mean differences of ENB, DR^2 and ENLC, and the share of (origin, r)
    where arm 3 has the higher ENB (§5)."""
    out: dict[str, Any] = {}
    for col in ("enb", "dr2", "enlc"):
        a3, a1 = arm_grid(rows, C.MIN_TDD, col, months), arm_grid(rows, C.FRONTIER, col, months)
        d = (a3 - a1)[np.isfinite(a3) & np.isfinite(a1)]
        out[f"{col}_mean_difference"] = float(d.mean()) if d.size else None
        if col == "enb":
            out["share_higher_enb"] = float(np.mean(d > 0)) if d.size else None
    return out


def analyze_job(
    job_dir: Path,
    parent: Mapping[str, Any],
    menu: str,
    engine: str,
    inputs: Any,
    callables: tuple,
) -> dict[str, Any]:
    """Realized outcomes per arm, the confirmatory test and the descriptive statistics of one
    job (the report's inputs). No ensemble code runs here (§7.3, point 1)."""
    tables = load_tables(job_dir, parent["digest"])
    horizon, span, spy_tr, cpi, dgs10 = callables
    table = realized_outcomes(
        tables["selections"], horizon, span=span, cpi=cpi, spy_tr=spy_tr, dgs10=dgs10
    )
    facts = parent["menus"][menu]
    months = [str(m) for m in facts["schedule"]]
    frozen = facts.get("cscv") or {}
    eligible = [m for m in frozen.get("months", []) if m in set(months)] or None
    arms = C.V3_ARMS if engine == "replay" else C.V3_GARCH_REPORTED
    rows = locked_rows(table)
    rows = rows[rows["arm"].isin([*arms, C.APP_FRONTIER])]
    result: dict[str, Any] = {
        "job": Path(job_dir).name,
        "parent_digest": parent["digest"],
        "selections": int(len(tables["selections"])),
        "labels": tables["selections"]["status"].value_counts().to_dict(),
        "confirmatory": confirmatory_test(table, months, eligible=eligible),
        "arms": arm_summary(rows, [*arms, C.APP_FRONTIER]),
        "diversification": diversification(rows, months),
        "descriptive_comparisons": {},
    }
    for arm in arms:
        if arm in (C.FRONTIER, C.MIN_TDD):
            continue
        result["descriptive_comparisons"][f"{arm}_vs_{C.FRONTIER}"] = confirmatory_test(
            table, months, eligible=eligible, candidate=arm
        )
        result["descriptive_comparisons"][f"{C.MIN_TDD}_vs_{arm}"] = confirmatory_test(
            table, months, eligible=eligible, candidate=C.MIN_TDD, comparator=arm
        )
    if len(arms) == len(C.V3_ARMS):
        result["rank_agreement"] = rank_agreement(rows, months)
    masks = cscv_arms(rows, frozen, arms) if frozen else None
    if masks is not None:
        result["cscv"] = {
            "evaluable": len(masks.evaluable), "total": masks.splits_total, "pbo": masks.pbo,
            "note": masks.pbo_note, "choice_shares": masks.choice_shares(list(arms)),
        }  # fmt: skip
    return result
