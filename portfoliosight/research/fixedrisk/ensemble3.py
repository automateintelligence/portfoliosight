"""The post-hoc ensemble screen of protocol v3 §7.3, end to end. EXPLORATORY ONLY: nothing here
is an input of the confirmatory verdict (§6.3) or of the decision rule (§6.4).

Order (§7.3, point 1): the confirmatory analysis is written first and its SHA-256 recorded in the
run directory (`record_analysis`, `<run>/<job>/analysis_record.json`); `screen_job` refuses to run
until that record exists and matches the analysis file, and only then reads a realized outcome.

Per eligible origin task, one pool file at a time (`stream_picks`):

1. `read_main_pool`: the pool's main rows (the 3-year lookback; no lambda or the main lambda, so
   the side checks are left out) inside the wide band, read with a Parquet filter;
2. `analysis3.ensemble_candidates`: the distinct mixes (weights equal after rounding to 1e-9,
   each the lowest pool row id) with all six objectives defined, percentile-ranked with average
   ranks for ties; `analysis3.ensemble_picks`: per weight combination (the 126 points of the
   simplex grid with step 0.25) and risk level, the highest weighted rank score, ties to the
   lowest pool row id;
3. the realized outcomes of the distinct picked mixes, from their pool weights, with
   `realized.realized_table` (monthly rebalanced, gross: `ret_m`, `dd_m`, `vol_m`).

Then, across the combinations (`combination_statistics`, `cscv_combinations`, `dsr_combinations`):
theta_DD and theta_Ret against arm 1 with §6.1's estimands and §6.2's primary bootstrap (block 24,
2,000 resamples, seed 20261201), and conditions (A) and (B) of §6.3 read as a description; the
purged CSCV over the combinations with §7.1's score (mean realized dd_m, equal weight over the
levels; lower is better), so `omega = k / (combinations + 1)` (§7.1's `k/7` for six candidates);
the deflated Sharpe ratio with every combination a trial, on Delta_DD(o) against arm 1 at the
disjoint intervals (§7.2's series), the primary trial being the combination with the highest
Sharpe ratio there (the one a screen would pick).
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from portfoliosight.research import evidence
from portfoliosight.research.fixedrisk import analysis3 as A
from portfoliosight.research.fixedrisk import contracts as C
from portfoliosight.research.fixedrisk import cscv, dsr
from portfoliosight.research.fixedrisk import realized as R
from portfoliosight.research.fixedrisk.pool import read_weights

EXPLORATORY = "EXPLORATORY"
NOTICE = (
    "Exploratory screen (protocol v3 §7.3): computed after the confirmatory result was written and "
    "its digest recorded; it cannot change the v3 verdict or the decision rule, and a promising "
    "combination is a hypothesis for a new preregistered protocol, not a finding."
)
RECORD_FILE = "analysis_record.json"
WOULD_PASS = "would pass (A) and (B)"
POOL_COLUMNS = ("record", "lookback", "r_fraction", "lam", "in_wide", "weights", "sigma",
                *A.ENSEMBLE_OBJECTIVES)  # fmt: skip


# ------------------------------------------------------------------------- digest record


def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _read_record(job_dir: Path) -> dict[str, Any]:
    path = Path(job_dir) / RECORD_FILE
    return json.loads(path.read_text()) if path.is_file() else {}


def _write_record(job_dir: Path, record: Mapping[str, Any]) -> None:
    path = Path(job_dir) / RECORD_FILE
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(json.dumps(record, indent=2) + "\n")
    tmp.replace(path)


def _entry(path: Path) -> dict[str, Any]:
    return {"path": str(Path(path).resolve()), "sha256": sha256_file(path),
            "utc": datetime.now(UTC).isoformat()}  # fmt: skip


def record_analysis(job_dir: Path, analysis_path: Path) -> dict[str, Any]:
    """Record the confirmatory analysis file's SHA-256 in the run directory (§7.3, point 1); a
    new analysis replaces the record, and with it any ensemble entry made before it."""
    record = {"analysis": _entry(analysis_path)}
    _write_record(job_dir, record)
    return record


def record_ensemble(job_dir: Path, ensemble_path: Path) -> dict[str, Any]:
    """Add the ensemble file's SHA-256 to the record, after its analysis entry."""
    record = _read_record(job_dir)
    if "analysis" not in record:
        raise ValueError(f"{Path(job_dir) / RECORD_FILE} has no analysis entry")
    record["ensemble"] = _entry(ensemble_path)
    _write_record(job_dir, record)
    return record


def verified_entry(job_dir: Path, name: str, path: Path | None = None) -> Path:
    """The recorded file `name` ("analysis" or "ensemble"), checked against its recorded SHA-256
    (and, when `path` is given, the same file); a ValueError otherwise."""
    entry = _read_record(job_dir).get(name)
    if entry is None:
        raise ValueError(f"no {name} digest recorded in {Path(job_dir) / RECORD_FILE}")
    target = Path(path) if path is not None else Path(entry["path"])
    if path is not None and target.resolve() != Path(entry["path"]):
        raise ValueError(f"{target} is not the recorded {name} file {entry['path']}")
    if not target.is_file():
        raise ValueError(f"the recorded {name} file {target} is missing")
    if sha256_file(target) != entry["sha256"]:
        raise ValueError(f"{target} changed after its digest was recorded")
    return target


# ---------------------------------------------------------------------------- streaming


def read_main_pool(path: Path) -> pd.DataFrame:
    """The pool's main rows (3-year lookback, no lambda or the main lambda) in the wide band,
    with their weights (one array per row) and the six objectives."""
    table = pq.read_table(
        path, columns=list(POOL_COLUMNS),
        filters=[("lookback", "==", C.LOOKBACK), ("in_wide", "==", True)],
    )  # fmt: skip
    lam = np.asarray(table.column("lam").to_numpy(zero_copy_only=False), dtype=float)
    table = table.filter(pa.array(np.isnan(lam) | np.isclose(lam, C.LAMBDA)))
    weights = read_weights(table)
    frame = table.drop_columns(["weights"]).to_pandas()
    frame["weights"] = list(weights)
    return frame


def pick_outcomes(
    picks: pd.DataFrame, pool: pd.DataFrame, *, menu: str, month: str, origin: Any,
    horizon: R.HorizonFn,
) -> pd.DataFrame:  # fmt: skip
    """`picks` with the realized `ret_m`, `dd_m`, `vol_m` and `complete` of each picked mix,
    computed once per distinct pool row from its weights."""
    records = sorted({int(r) for r in picks["record"]})
    by_record = pool.set_index("record")
    sel = pd.DataFrame(
        {"sel_id": [str(r) for r in records], "menu": menu, "month": month, "origin": origin,
         "weights": [list(by_record.loc[r, "weights"]) for r in records]}
    )  # fmt: skip
    out = R.realized_table(sel, horizon, multi_years=())
    out["record"] = out["sel_id"].astype(int)
    keep = out[["record", "complete", "ret_m", "dd_m", "vol_m"]]
    return picks.merge(keep, on="record", how="left", validate="many_to_one")


def stream_picks(
    tasks_dir: Path,
    *,
    menu: str,
    engine: str,
    months: Sequence[str],
    eligible: Sequence[str],
    weights: np.ndarray,
    horizon: R.HorizonFn,
    origin_of: Callable[[str], Any],
    progress: Callable[[str], None] | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, pd.DataFrame]:
    """Per eligible origin, one pool file at a time: the candidates, the picks of every weight
    combination and their realized outcomes. Returns `dd` and `ret` (combinations x levels x
    months, NaN where an origin is not eligible or a cell has no candidate), the candidate count
    per (level, month) and the picks table."""
    from portfoliosight.research.fixedrisk.driver3 import base_paths

    shape = (len(weights), len(A.RFS), len(months))
    dd, ret = np.full(shape, np.nan), np.full(shape, np.nan)
    counts = np.zeros(shape[1:], dtype=int)
    frozen = {str(m) for m in eligible}
    parts = []
    for o, month in enumerate(months):
        if month not in frozen:
            continue
        path = base_paths(Path(tasks_dir), f"{menu}_{month}_{engine}")["pool"]
        pool = read_main_pool(path)
        candidates = A.ensemble_candidates(pool)
        if candidates.empty:
            continue
        rf_of = candidates["r_fraction"].to_numpy(dtype=float).round(6)
        for j, rf in enumerate(A.RFS):
            counts[j, o] = int(np.sum(rf_of == rf))
        picks = A.ensemble_picks(candidates, weights)
        picks = pick_outcomes(picks, pool, menu=menu, month=month, origin=origin_of(month),
                              horizon=horizon)  # fmt: skip
        picks["month"] = month
        level = picks["r_fraction"].to_numpy(dtype=float).round(6)
        combo = picks["combination"].to_numpy(dtype=int)
        values = picks[["dd_m", "ret_m"]].to_numpy(dtype=float)
        for j, rf in enumerate(A.RFS):
            at = level == rf
            dd[combo[at], j, o], ret[combo[at], j, o] = values[at, 0], values[at, 1]
        parts.append(picks)
        if progress is not None:
            progress(f"{month}: {len(candidates)} candidates, {picks['record'].nunique()} mixes")
        del pool, candidates
    table = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
    return dd, ret, counts, table


# --------------------------------------------------------------------------- statistics


def combination_statistics(
    dd1: np.ndarray,
    r1: np.ndarray,
    dd: np.ndarray,
    ret: np.ndarray,
    weights: np.ndarray,
    *,
    resamples: int = evidence.RESAMPLES,
    seed: int = evidence.BOOTSTRAP_SEED,
) -> list[dict[str, Any]]:
    """Per combination, theta_DD = mean dd_m(arm 1) - dd_m(pick) and theta_Ret = mean ret_m(pick)
    - ret_m(arm 1) on the paired cells (levels within an origin, then origins), with §6.2's
    primary bootstrap, and (A) and (B) of §6.3 read as a description. `dd1`, `r1` are arm 1's
    (levels x months) grids, NaN outside the eligible origins; `dd`, `ret` the picks' grids."""
    boot = evidence.Bootstrap(dd1.shape[1], blocks=(evidence.BLOCK,), resamples=resamples,
                              seed=seed)  # fmt: skip
    out = []
    for c in range(len(weights)):
        paired = np.isfinite(dd1) & np.isfinite(r1) & np.isfinite(dd[c]) & np.isfinite(ret[c])
        d_dd = np.where(paired, dd1 - dd[c], np.nan)
        d_ret = np.where(paired, ret[c] - r1, np.nan)
        e_dd = A._estimate(boot, d_dd, 0.95)
        e_ret = A._estimate(boot, d_ret, 0.95)
        e_ret90 = A._estimate(boot, d_ret, 0.90)
        a, b = A._conditions(e_dd, e_ret90, evidence.BLOCK)
        out.append(
            {"combination": c,
             "weights": dict(zip(A.ENSEMBLE_OBJECTIVES, map(float, weights[c]), strict=True)),
             "paired_cells": int(paired.sum()),
             "theta_dd": e_dd.value, "theta_dd_interval": e_dd.intervals[evidence.BLOCK],
             "theta_ret": e_ret.value, "theta_ret_interval": e_ret.intervals[evidence.BLOCK],
             "theta_ret_p5": e_ret90.lower(evidence.BLOCK), "A": a, "B": b,
             "description": WOULD_PASS if a and b else A._label(a, b)}
        )  # fmt: skip
    return out


def cscv_combinations(
    dd: np.ndarray, months: Sequence[str], frozen: Mapping[str, Any]
) -> dict[str, Any]:
    """Purged CSCV over the combinations on realized dd_m (§7.1's score, lower is better), on
    the frozen masks; `omega = k / (combinations + 1)`."""
    if "splits" not in frozen:
        return {"available": False, "reason": frozen.get("unavailable", "no frozen CSCV masks")}
    masks = cscv.CscvMasks.from_manifest(dict(frozen))
    pos = {m: o for o, m in enumerate(months)}
    values = np.full((dd.shape[0], len(masks.origins), dd.shape[1]), np.nan)
    for k, month in enumerate(str(m) for m in frozen["months"]):
        if month in pos:
            values[:, k, :] = dd[:, :, pos[month]]
    res = cscv.cscv_candidates(masks, values, lower_is_better=True)
    chosen = np.bincount([int(r["chosen"]) for r in res.evaluable], minlength=dd.shape[0])
    return {
        "available": True, "candidates": int(dd.shape[0]), "omega_denominator": dd.shape[0] + 1,
        "evaluable": len(res.evaluable), "total": res.splits_total, "pbo": res.pbo,
        "note": res.pbo_note, "dropped": len(res.dropped),
        "chosen_counts": {str(k): int(v) for k, v in enumerate(chosen) if v},
        "mean_test_rank": (float(np.mean([r["rank"] for r in res.evaluable]))
                           if res.evaluable else None),
    }  # fmt: skip


def dsr_combinations(
    dd1: np.ndarray, dd: np.ndarray, months: Sequence[str], disjoint: Sequence[str]
) -> dict[str, Any]:
    """The deflated Sharpe ratio with every combination a trial: Delta_DD(o) against arm 1 on
    the disjoint intervals (rows where every trial is defined); the primary trial is the one
    with the highest Sharpe ratio."""
    pos = {m: o for o, m in enumerate(months)}
    cols = [pos[m] for m in (str(x) for x in disjoint) if m in pos]
    if not cols:
        return {"available": False, "reason": "no disjoint interval in the schedule"}
    series = np.stack(
        [evidence._masked_mean(dd1[:, cols] - dd[c][:, cols], axis=0) for c in range(len(dd))],
        axis=1,
    )  # intervals x combinations
    ok = np.isfinite(series).all(axis=1)
    x = series[ok]
    if len(x) < 2:
        return {"available": False, "reason": f"{len(x)} disjoint intervals with every trial"}
    sd = x.std(axis=0, ddof=1)
    sharpe = np.where(sd > dsr.ZERO_SD, x.mean(axis=0) / np.where(sd > 0, sd, 1.0), -math.inf)
    primary = int(np.argmax(sharpe))
    result = dsr.deflated_sharpe(x, primary=primary).record()
    return {"available": True, "trials": int(len(dd)), "primary": primary,
            "intervals": int(len(x)), **result}  # fmt: skip


# ------------------------------------------------------------------------------- one job


def screen_job(
    job_dir: Path,
    parent: Mapping[str, Any],
    menu: str,
    engine: str,
    horizon: R.HorizonFn,
    *,
    analysis_path: Path | None = None,
    picks_out: Path | None = None,
    resamples: int = evidence.RESAMPLES,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """The §7.3 screen of one job; refuses to read a realized outcome before the confirmatory
    analysis' digest is recorded (`verified_entry`). Writes the picks with their outcomes to
    `picks_out` (Parquet) when given."""
    job_dir = Path(job_dir)
    analysis = verified_entry(job_dir, "analysis", analysis_path)
    analysis_sha = sha256_file(analysis)
    facts = parent["menus"][menu]
    months = [str(m) for m in facts["schedule"]]
    eligible = A.eligible_origins(parent, menu)
    mask = np.array([m in set(eligible) for m in months])
    tables = A.load_tables(job_dir, parent["digest"])
    sel = tables["selections"]
    arm1 = A._frame(sel.loc[(sel["arm"] == C.FRONTIER).to_numpy()
                            & ~sel["pooled"].astype(bool).to_numpy()])  # fmt: skip
    arm1 = A.locked_rows(A.realized_outcomes(arm1, horizon))
    dd1 = A.arm_grid(arm1, C.FRONTIER, "dd_m", months)
    r1 = A.arm_grid(arm1, C.FRONTIER, "ret_m", months)
    dd1[:, ~mask], r1[:, ~mask] = np.nan, np.nan
    origins = arm1.groupby(arm1["month"].astype(str))["origin"].first().to_dict()
    weights = A.simplex_weights()
    dd, ret, counts, picks = stream_picks(
        job_dir / "tasks", menu=menu, engine=engine, months=months, eligible=eligible,
        weights=weights, horizon=horizon, origin_of=lambda m: origins.get(m), progress=progress,
    )  # fmt: skip
    if picks_out is not None and not picks.empty:
        Path(picks_out).parent.mkdir(parents=True, exist_ok=True)
        picks.to_parquet(picks_out, index=False)
    combos = combination_statistics(dd1, r1, dd, ret, weights, resamples=resamples)
    passing = [c["combination"] for c in combos if c["description"] == WOULD_PASS]
    filled = counts[:, mask]
    disjoint = [str(i["month"]) for i in facts.get("disjoint_intervals", [])]
    return {
        "label": EXPLORATORY,
        "notice": NOTICE,
        "job": job_dir.name,
        "parent_digest": parent["digest"],
        "analysis_sha256": analysis_sha,
        "objectives": list(A.ENSEMBLE_OBJECTIVES),
        "objective_signs": dict(A.ENSEMBLE_SIGN),
        "step": A.ENSEMBLE_STEP,
        "combinations_count": int(len(weights)),
        "added_after_results": [],
        "candidates": {
            "cells": int((filled > 0).sum()),
            "eligible_cells": int(filled.size),
            "median": float(np.median(filled[filled > 0])) if (filled > 0).any() else None,
            "min": int(filled[filled > 0].min()) if (filled > 0).any() else None,
            "max": int(filled.max()) if filled.size else None,
        },
        "distinct_picked_mixes": int(picks[["month", "record"]].drop_duplicates().shape[0])
        if not picks.empty else 0,
        "combinations": combos,
        "would_pass": passing,
        "cscv": cscv_combinations(dd, months, facts.get("cscv") or {}),
        "dsr": dsr_combinations(dd1, dd, months, disjoint),
    }  # fmt: skip
