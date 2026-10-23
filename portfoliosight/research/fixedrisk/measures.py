"""Statistics of the fixed-risk experiment (protocol v2 section 6), from the run's three tables.

`load_run` reads `<run_dir>/<job>/tasks/*.parquet`; `Study` holds the tables plus the realized
figures of `realized.realized_table` and computes each criterion for one `(menu, engine)`. Every
paired statistic uses the v1 circular moving-block bootstrap over the monthly origin index
(block 24, 2,000 resamples, seed 20261201, identical blocks for every arm, cell and menu).
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from portfoliosight.research import evaluate, evidence
from portfoliosight.research.fixedrisk import contracts as C
from portfoliosight.research.fixedrisk import cscv, dsr
from portfoliosight.research.fixedrisk.realized import REALIZED_COLUMNS

BP = 1e-4
BAD_Q = 0.025
U1 = C.ARMS["U1"]
GAIN = 5 * BP  # white line: pooled independent-bank mean dU
BANKS_NEEDED = 4
MEDIAN_LOSS = 25 * BP
MEAN_LOSS = 25 * BP
LOSS_FREQUENCY = 0.05
DRAWDOWN_WORSENING = 0.01
SUPPORT_GAIN = 25 * BP
SUPPORT_DRAWDOWN = 0.01
SUPPORT_DISJOINT = 20
TAIL_DISJOINT = 200
BAD_SD_FACTOR = 0.10
BAD_SD_SHARE = 0.95
MEDIAN_L1 = 0.20
P90_L1 = 0.40
ENGINE_L1 = 0.10
D_STAR_BAND = 0.25
SELECTION_KEYS = ["month", "rf", "cell", "arm"]
RFS = tuple(round(x, 6) for x in C.RISK_FRACTIONS)
BANK_METRICS = ("bad", "typical", "good", "mean", "es_25")

SUPPORTED = "supported"
NOT_SUPPORTED = "not supported"
INCONCLUSIVE = "inconclusive"
NOT_ATTAINABLE = "not attainable"


def u_of(arm: str, bad: Any, typical: Any, good: Any) -> Any:
    b, t, g = C.ARMS[arm]
    return b * bad + t * typical + g * good


# ----------------------------------------------------------------------------------- loading


@dataclass
class RunTables:
    selections: pd.DataFrame
    anchors: pd.DataFrame
    evaluated: pd.DataFrame
    jobs: list[str]


def load_run(run_dir: str | Path) -> RunTables:
    """Concatenate every job's task files into the three logical tables.

    A file is classified by its columns (selections carry `sel_id` and `weights`; anchors `w_F`;
    evaluated `test_seed`), so the file naming of the writer does not matter.
    """
    root = Path(run_dir)
    parts: dict[str, list[pd.DataFrame]] = {"selections": [], "anchors": [], "evaluated": []}
    jobs: list[str] = []
    for job in sorted(p for p in root.iterdir() if (p / "tasks").is_dir()):
        files = sorted((job / "tasks").glob("*.parquet"))
        if not files:
            continue
        jobs.append(job.name)
        for file in files:
            frame = pd.read_parquet(file)
            cols = set(frame.columns)
            if {"sel_id", "weights"} <= cols:
                parts["selections"].append(frame)
            elif "w_F" in cols:
                parts["anchors"].append(frame)
            elif "test_seed" in cols:
                parts["evaluated"].append(frame)
            else:
                raise ValueError(f"{file}: columns match none of the three run tables")
    if not parts["selections"]:
        raise ValueError(f"{root}: no selections found under <job>/tasks/*.parquet")
    tables = {
        k: (pd.concat(v, ignore_index=True) if v else pd.DataFrame()) for k, v in parts.items()
    }
    sel = tables["selections"]
    dup = sel["sel_id"].duplicated()
    if dup.any():
        raise ValueError(f"{int(dup.sum())} duplicated sel_id values across task files")
    return RunTables(_norm(sel), _norm(tables["anchors"]), tables["evaluated"], jobs)


def _norm(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    if "r_fraction" in out:
        out["rf"] = out["r_fraction"].astype(float).round(6)
    if "origin" in out:
        out["origin"] = pd.to_datetime(out["origin"])
    return out


# ------------------------------------------------------------------------------------ helpers


def _num(value: Any) -> float | None:
    if value is None:
        return None
    x = float(value)
    return x if math.isfinite(x) else None


def _grid(frame: pd.DataFrame, col: str, months: Sequence[str], rfs: Sequence[float] = RFS):
    """R x K array of `col` placed on the origin index; NaN where absent."""
    if frame.empty:
        return np.full((len(rfs), len(months)), np.nan)
    piv = frame.pivot_table(index="rf", columns="month", values=col, aggfunc="first", dropna=False)
    return piv.reindex(index=list(rfs), columns=list(months)).to_numpy(dtype=float)


def _mean_point(grid: np.ndarray) -> float | None:
    return _num(evidence.origin_mean(grid, np.arange(grid.shape[1])[None, :])[0])


def _l1(a: Any, b: Any) -> float:
    return float(np.abs(np.asarray(a, dtype=float) - np.asarray(b, dtype=float)).sum())


def disjoint_origins(origins: Sequence[Any], ends: Sequence[Any]) -> list[int]:
    """Indices (greedy, origin order) of intervals starting strictly after the last retained end."""
    kept: list[int] = []
    last = None
    order = sorted(range(len(origins)), key=lambda i: origins[i])
    for i in order:
        if last is None or origins[i] > last:
            kept.append(i)
            last = ends[i]
    return kept


def _quantiles(values: np.ndarray, qs: Sequence[float]) -> list[float | None]:
    v = values[np.isfinite(values)]
    return [float(np.percentile(v, q)) for q in qs] if len(v) else [None] * len(qs)


# --------------------------------------------------------------------------------------- study


class Study:
    """The run's tables plus realized figures; one method per section 6 criterion."""

    def __init__(
        self,
        tables: RunTables,
        realized: pd.DataFrame | None = None,
        *,
        primary_seed: int = C.PRIMARY_SEED,
        disjoint: Mapping[str, Sequence[Any]] | None = None,
        blocks: Sequence[int] = evidence.BLOCKS,
        resamples: int = evidence.RESAMPLES,
    ) -> None:
        sel = tables.selections
        if realized is not None:
            sel = sel.merge(realized, on="sel_id", how="left", validate="one_to_one")
        else:
            for name in REALIZED_COLUMNS:
                sel[name] = False if name == "complete" else np.nan
        sel["complete"] = sel["complete"].fillna(False).astype(bool)
        self.sel = sel
        self.anchors = tables.anchors
        self.jobs = tables.jobs
        self.primary_seed = primary_seed
        self.blocks = tuple(blocks)
        self.resamples = resamples
        self._disjoint = dict(disjoint) if disjoint else None
        self._boots: dict[tuple[int, bool], evidence.Bootstrap] = {}
        ev = tables.evaluated
        self.test_seeds = sorted(ev["test_seed"].unique()) if len(ev) else []
        self.evw: dict[str, pd.DataFrame] = {}
        for name in BANK_METRICS:
            self.evw[name] = (
                ev.pivot_table(index="sel_id", columns="test_seed", values=name, aggfunc="first")
                if len(ev)
                else pd.DataFrame()
            )
        if len(ev):
            self.evw["u1"] = u_of("U1", self.evw["bad"], self.evw["typical"], self.evw["good"])

    # ------------------------------------------------------------------------ index helpers

    def menus(self) -> list[str]:
        return sorted(self.sel["menu"].unique())

    def engines(self, menu: str) -> list[str]:
        return sorted(self.sel.loc[self.sel["menu"] == menu, "engine"].unique())

    def months(self, menu: str) -> list[str]:
        """Every ledger month from the first to the last scheduled origin of the menu."""
        m = self.sel.loc[self.sel["menu"] == menu, "month"]
        return [str(p) for p in pd.period_range(m.min(), m.max(), freq="M")]

    def boot(self, k: int, full: bool = False) -> evidence.Bootstrap:
        key = (k, full)
        if key not in self._boots:
            blocks = self.blocks if full else (evidence.BLOCK,)
            self._boots[key] = evidence.Bootstrap(k, blocks=blocks, resamples=self.resamples)
        return self._boots[key]

    def pick(
        self,
        menu: str,
        engine: str,
        *,
        kind: str | Sequence[str] | None = None,
        arm: str | None = None,
        cell: str | None = None,
        pooled: bool | None = None,
        tau: float | None = C.TAU_R,
        seed: int | None = ...,  # type: ignore[assignment]
        keys: Sequence[str] = SELECTION_KEYS,
    ) -> pd.DataFrame:
        s = self.sel
        m = (s["menu"] == menu) & (s["engine"] == engine)
        if kind is not None:
            kinds = [kind] if isinstance(kind, str) else list(kind)
            m &= s["kind"].isin(kinds)
        if arm is not None:
            m &= s["arm"] == arm
        if cell is not None:
            m &= s["cell"] == cell
        if pooled is not None:
            m &= s["pooled"].astype(bool) == pooled
        if tau is not None:
            m &= np.isclose(s["tau_r"].astype(float), tau)
        if seed is ...:
            seed = self.primary_seed
        if seed is not None:
            m &= s["seed"] == seed
        return s[m].drop_duplicates(list(keys)).reset_index(drop=True)

    def ledger(self, menu: str) -> pd.DataFrame:
        """Month, origin and horizon end of the menu's complete realized years."""
        s = self.sel[(self.sel["menu"] == menu) & self.sel["complete"]]
        out = s.drop_duplicates("month")[["month", "origin", "horizon_end"]].sort_values("month")
        out["horizon_end"] = pd.to_datetime(out["horizon_end"])
        return out.reset_index(drop=True)

    def disjoint_months(self, menu: str) -> list[str]:
        """Origin months of the disjoint annual intervals (published intervals if given)."""
        if self._disjoint and menu in self._disjoint:
            return [str(t[0]) for t in self._disjoint[menu]]
        led = self.ledger(menu)
        idx = disjoint_origins(list(led["origin"]), list(led["horizon_end"]))
        return [led["month"].iloc[i] for i in idx]

    # --------------------------------------------------------------------- paired comparison

    def compare(
        self, menu: str, a: pd.DataFrame, b: pd.DataFrame, *, full_boot: bool = True
    ) -> dict[str, Any]:
        """Selection rows `a` against comparator rows `b`, paired on (month, r): model figures on
        the independent banks and realized figures on the monthly convention."""
        months = self.months(menu)
        k = len(months)
        m = a.merge(b, on=["month", "rf"], suffixes=("_a", "_b"))
        out: dict[str, Any] = {"pairs": int(len(m)), "origins": int(m["month"].nunique())}
        if m.empty:
            return out
        for name in ("u1", "bad", "es_25"):
            if name not in self.evw or self.evw[name].empty:
                continue
            cols = []
            for bank in self.test_seeds:
                m[f"{name}_{bank}"] = m["sel_id_a"].map(self.evw[name][bank]) - m["sel_id_b"].map(
                    self.evw[name][bank]
                )
                cols.append(f"{name}_{bank}")
            m[f"d_{name}"] = m[cols].mean(axis=1)
        m["d_risk"] = m["sigma_a"] - m["sigma_b"]
        boot = self.boot(k, full_boot)
        model: dict[str, Any] = {}
        for name in ("u1", "bad", "es_25"):
            if f"d_{name}" not in m:
                continue
            grid = _grid(m, f"d_{name}", months)
            est = boot.estimate(
                lambda i, g=grid: evidence.origin_mean(g, i), 0.95, evidence._count(grid)
            )
            model[name] = {
                "mean": est.value,
                "interval": list(est.intervals[evidence.BLOCK]),
                "by_r": [_num(evidence.cell_mean(row, np.arange(k)[None, :])[0]) for row in grid],
            }
        grid = _grid(m, "d_risk", months)
        model["risk"] = {
            "mean": _mean_point(grid),
            "by_r": [_num(evidence.cell_mean(row, np.arange(k)[None, :])[0]) for row in grid],
        }
        if "d_u1" in m:
            per_bank = []
            for bank in self.test_seeds:
                per_bank.append(_mean_point(_grid(m, f"u1_{bank}", months)))
            model["banks"] = per_bank
            model["banks_positive"] = int(sum(1 for x in per_bank if x is not None and x > 0))
            model["banks_n"] = len(per_bank)
        out["model"] = model
        out["realized"] = self._realized_pair(m, months, boot)
        return out

    def _realized_pair(self, m: pd.DataFrame, months: Sequence[str], boot) -> dict[str, Any]:
        """Realized monthly-convention guardrails and benefit, candidate (a) vs comparator (b)."""
        y1, y2 = _grid(m, "ret_m_a", months), _grid(m, "ret_m_b", months)
        paired = np.isfinite(y1) & np.isfinite(y2)
        y1, y2 = np.where(paired, y1, np.nan), np.where(paired, y2, np.nan)
        d1 = np.where(paired, _grid(m, "dd_m_a", months), np.nan)
        d2 = np.where(paired, _grid(m, "dd_m_b", months), np.nan)
        n = evidence._count(y1 - y2)
        if n == 0:
            return {"n": 0}
        diff, improvement = y1 - y2, d2 - d1
        gain = boot.estimate(lambda i: evidence.origin_mean(diff, i), evidence.SUPPORT_LEVEL, n)
        dd = boot.estimate(
            lambda i: evidence.origin_mean(improvement, i), evidence.SUPPORT_LEVEL, n
        )
        cells = []
        for j, rf in enumerate(RFS):
            ok = paired[j]
            if not ok.any():
                cells.append({"rf": rf, "n": 0, "ok": None})
                continue
            median_loss = float(np.median(y2[j][ok]) - np.median(y1[j][ok]))
            mean_loss = float(-np.mean(y1[j][ok] - y2[j][ok]))
            loss_up = float(np.mean(y1[j][ok] < 0) - np.mean(y2[j][ok] < 0))
            dd_worse = float(np.mean(d1[j][ok] - d2[j][ok]))
            flags = (
                median_loss <= MEDIAN_LOSS,
                mean_loss <= MEAN_LOSS,
                loss_up <= LOSS_FREQUENCY,
                dd_worse <= DRAWDOWN_WORSENING,
            )
            cells.append(
                {
                    "rf": rf,
                    "n": int(ok.sum()),
                    "median_loss": median_loss,
                    "mean_loss": mean_loss,
                    "loss_increase": loss_up,
                    "drawdown_worsening": dd_worse,
                    "ok": all(flags),
                    "flags": list(flags),
                }
            )
        guardrails = all(c["ok"] for c in cells if c["ok"] is not None) and any(
            c["ok"] is not None for c in cells
        )
        mean_gain = gain.value
        return {
            "n": n,
            "gain": mean_gain,
            "gain_interval": list(gain.intervals[evidence.BLOCK]),
            "drawdown_improvement": dd.value,
            "drawdown_interval": list(dd.intervals[evidence.BLOCK]),
            "cells": cells,
            "guardrails_hold": guardrails,
            "mean_loss": None if mean_gain is None else -mean_gain,
        }

    # ---------------------------------------------------------------------------- white line

    def white_line(self, menu: str, engine: str) -> dict[str, Any]:
        u = self.pick(menu, engine, kind="main", arm="U1", cell="free", pooled=True)
        ref = self.pick(menu, engine, kind="comparator", arm="F", cell="free", pooled=None)
        bs = self.pick(menu, engine, kind="comparator", arm="BS", cell="free", pooled=None)
        out: dict[str, Any] = {"menu": menu, "engine": engine}
        out["vs_F"] = self.compare(menu, u, ref)
        out["vs_BS"] = self.compare(menu, u, bs, full_boot=False) if len(bs) else {"pairs": 0}
        out["tau"] = self._tau_check(menu, engine, u, ref)
        disjoint_n = len(self.disjoint_months(menu))
        out["disjoint"] = disjoint_n
        out["tail_underpowered"] = disjoint_n < TAIL_DISJOINT
        out.update(self._label(out))
        return out

    def _tau_check(self, menu: str, engine: str, u_main: pd.DataFrame, f_main: pd.DataFrame):
        """Sign of the pooled dU at tau_r = 0.001 against the main grid on the same origins."""
        kinds = ["sens_tau", "comparator"]
        u = self.pick(
            menu, engine, kind=kinds, arm="U1", cell="free", pooled=True, tau=C.TAU_R_SENSITIVITY
        )
        f = self.pick(
            menu, engine, kind=kinds, arm="F", cell="free", pooled=None, tau=C.TAU_R_SENSITIVITY
        )
        if u.empty or f.empty or "u1" not in self.evw:
            return {"available": False}
        months = self.months(menu)
        sens = self._pooled_du(u, f, months)
        same = sorted(set(u["month"]) & set(f["month"]))
        main = self._pooled_du(
            u_main[u_main["month"].isin(same)], f_main[f_main["month"].isin(same)], months
        )
        if sens is None or main is None:
            return {"available": False}
        return {
            "available": True,
            "origins": len(same),
            "main": main,
            "sensitivity": sens,
            "agree": bool(np.sign(main) == np.sign(sens)),
        }

    def _pooled_du(self, a: pd.DataFrame, b: pd.DataFrame, months: Sequence[str]) -> float | None:
        m = a.merge(b, on=["month", "rf"], suffixes=("_a", "_b"))
        if m.empty:
            return None
        u = self.evw["u1"]
        m["d"] = m["sel_id_a"].map(u.mean(axis=1)) - m["sel_id_b"].map(u.mean(axis=1))
        return _mean_point(_grid(m, "d", months))

    @staticmethod
    def _label(wl: dict[str, Any]) -> dict[str, Any]:
        """supported / not supported / inconclusive, with the realized-support state."""
        vs = wl["vs_F"]
        model, real = vs.get("model", {}), vs.get("realized", {})
        du = model.get("u1", {}).get("mean")
        if du is None or real.get("n", 0) == 0:
            return {
                "model_pass": None,
                "support": INCONCLUSIVE,
                "label": INCONCLUSIVE,
                "reason": "no paired model or realized rows",
            }
        model_pass = du >= GAIN and model.get("banks_positive", 0) >= BANKS_NEEDED
        tau = wl["tau"]
        guard = bool(real.get("guardrails_hold"))
        if wl["disjoint"] < SUPPORT_DISJOINT:
            support = NOT_ATTAINABLE
        else:
            lower_gain = real["gain_interval"][0]
            lower_dd = real["drawdown_interval"][0]
            gain, imp = real["gain"], real["drawdown_improvement"]
            by_gain = (
                gain is not None
                and gain >= SUPPORT_GAIN
                and lower_gain is not None
                and lower_gain > 0
            )
            by_dd = (
                imp is not None
                and imp >= SUPPORT_DRAWDOWN
                and lower_dd is not None
                and lower_dd > 0
                and real["mean_loss"] is not None
                and real["mean_loss"] <= MEAN_LOSS
            )
            support = "met" if guard and (by_gain or by_dd) else "not met"
        out = {"model_pass": bool(model_pass), "support": support, "guardrails": guard}
        if not tau.get("available"):
            return {**out, "label": INCONCLUSIVE, "reason": "tau_r = 0.001 sensitivity unavailable"}
        if not tau["agree"]:
            return {
                **out,
                "label": INCONCLUSIVE,
                "reason": "pooled dU changes sign at tau_r = 0.001",
            }
        if not model_pass:
            return {**out, "label": NOT_SUPPORTED, "reason": "model criterion not met"}
        if not guard:
            return {**out, "label": NOT_SUPPORTED, "reason": "a realized guardrail is breached"}
        if support == NOT_ATTAINABLE:
            return {
                **out,
                "label": INCONCLUSIVE,
                "reason": f"realized support not attainable ({wl['disjoint']} disjoint intervals)",
            }
        if support == "met":
            return {**out, "label": SUPPORTED, "reason": "all criteria met"}
        return {**out, "label": NOT_SUPPORTED, "reason": "realized support not met"}

    # ------------------------------------------------------------------------------ d* and anchors

    def d_star(self, menu: str, engine: str) -> dict[str, Any]:
        u = self.pick(menu, engine, kind="main", arm="U1", cell="free", pooled=True)
        native = self.pick(menu, engine, kind="main", arm="U1", cell="free", pooled=False)
        anchors = self.anchors_for(menu)
        rows = []
        for rf in RFS:
            s = u[u["rf"] == rf]
            d = s["d"].astype(float)
            ok = d.notna()
            n_ok = int(ok.sum())
            row: dict[str, Any] = {
                "rf": rf,
                "n": int(len(s)),
                "undefined": int((~ok).sum()),
                "quantiles": _quantiles(d.to_numpy(), (10, 50, 90)),
            }
            if n_ok:
                row.update(
                    below_0=float((d[ok] < 0).mean()),
                    above_1=float((d[ok] > 1).mean()),
                    inside=float(((d[ok] >= 0) & (d[ok] <= 1)).mean()),
                    at_least_quarter=float((d[ok] >= D_STAR_BAND).mean()),
                )
            hi = s[ok & (d > 1)].merge(
                anchors[["month", "rf", "M_MDP"]], on=["month", "rf"], how="left"
            )
            if len(hi):
                regret = hi["measure"] - hi["M_MDP"]
                row["regret_mean"], row["regret_max"] = _num(regret.mean()), _num(regret.max())
            n_s = native[native["rf"] == rf].merge(s, on=["month", "rf"], suffixes=("_n", "_p"))
            if len(n_s):
                differs = [
                    _l1(a, b) > 1e-6
                    for a, b in zip(n_s["weights_n"], n_s["weights_p"], strict=True)
                ]
                row["pooled_beyond_native"] = float(np.mean(differs))
            rows.append(row)
        return {"rows": rows}

    def anchors_for(self, menu: str) -> pd.DataFrame:
        a = self.anchors
        if a.empty:
            return pd.DataFrame(columns=["month", "rf", "M_MDP"])
        a = a[(a["menu"] == menu) & np.isclose(a["tau_r"].astype(float), C.TAU_R)]
        a = a[a["lookback"] == C.LOOKBACK]
        return a.drop_duplicates(["month", "rf"])

    def collapsed(self, menu: str) -> dict[str, Any]:
        a = self.anchors_for(menu)
        if a.empty:
            return {"available": False}
        main = a[a["rf"].isin(RFS)]
        show_months = set(
            self.sel.loc[(self.sel["menu"] == menu) & (self.sel["kind"] == "showcase"), "month"]
        )
        show = a[a["month"].isin(show_months)]
        return {
            "available": True,
            "by_r": [
                {
                    "rf": rf,
                    "n": int((main["rf"] == rf).sum()),
                    "share": float(main.loc[main["rf"] == rf, "collapsed"].astype(bool).mean())
                    if (main["rf"] == rf).any()
                    else None,
                }
                for rf in RFS
            ],
            "overall": float(main["collapsed"].astype(bool).mean()) if len(main) else None,
            "showcase_columns": int(len(show)),
            "showcase_share": float(show["collapsed"].astype(bool).mean()) if len(show) else None,
        }

    # ------------------------------------------------------------------------- safest mix

    def safest_mix(self, menu: str, engine: str) -> dict[str, Any]:
        """Max-Bad arm (B) against U1 in the free cell: realized outcomes and model Bad/ES."""
        months = self.months(menu)
        k = len(months)
        u = self.pick(menu, engine, kind="main", arm="U1", cell="free", pooled=True)
        b = self.pick(menu, engine, kind="main", arm="B", cell="free", pooled=True)
        m = b.merge(u, on=["month", "rf"], suffixes=("_b", "_u"))
        out: dict[str, Any] = {"pairs": int(len(m))}
        if m.empty:
            return out
        boot = self.boot(k)
        stats_: dict[str, Any] = {}
        for tag in ("b", "u"):
            y = _grid(m, f"ret_m_{tag}", months)
            dd = _grid(m, f"dd_m_{tag}", months)
            ok = np.isfinite(y).any()
            stats_[tag] = {
                "realized_bad": [
                    _num(evidence.quantile(row, BAD_Q, np.arange(k)[None, :])[0]) for row in y
                ]
                if ok
                else [],
                "mean_drawdown": [
                    _num(evidence.cell_mean(row, np.arange(k)[None, :])[0]) for row in dd
                ]
                if ok
                else [],
                "mean_return": [
                    _num(evidence.cell_mean(row, np.arange(k)[None, :])[0]) for row in y
                ]
                if ok
                else [],
                "worst_year": [
                    _num(np.nanmin(row)) if np.isfinite(row).any() else None for row in y
                ],
            }
        out["stats"] = stats_
        y_b, y_u = _grid(m, "ret_m_b", months), _grid(m, "ret_m_u", months)
        d_b, d_u = _grid(m, "dd_m_b", months), _grid(m, "dd_m_u", months)
        paired = np.isfinite(y_b) & np.isfinite(y_u)
        diff_r = np.where(paired, y_b - y_u, np.nan)
        diff_d = np.where(paired, d_b - d_u, np.nan)
        n = evidence._count(diff_r)
        if n:
            for name, g in (("return", diff_r), ("drawdown", diff_d)):
                est = boot.estimate(lambda i, g=g: evidence.origin_mean(g, i), 0.95, n)
                out[f"{name}_diff"] = {
                    "mean": est.value,
                    "interval": list(est.intervals[evidence.BLOCK]),
                }
        for name in ("bad", "es_25"):
            if name in self.evw and not self.evw[name].empty:
                dm = m["sel_id_b"].map(self.evw[name].mean(axis=1)) - m["sel_id_u"].map(
                    self.evw[name].mean(axis=1)
                )
                m[f"d_{name}"] = dm
                out[f"model_d_{name}"] = _mean_point(_grid(m, f"d_{name}", months))
        return out

    # ------------------------------------------------------------------------------ line shape

    def line_shape(self, menu: str, engine: str) -> dict[str, Any]:
        """OLS slope on d of realized Bad, mean drawdown, mean return across d = .25/.50/.75."""
        months = self.months(menu)
        k = len(months)
        ds = np.array([C.CELL_D[c] for c in ("d25", "d50", "d75")], dtype=float)
        coef = (ds - ds.mean()) / np.sum((ds - ds.mean()) ** 2)
        picks = [
            self.pick(menu, engine, kind="main", arm="U1", cell=c, pooled=True)
            for c in ("d25", "d50", "d75")
        ]
        boot = self.boot(k)
        rows = []
        for rf in RFS:
            ys = [_grid(p[p["rf"] == rf], "ret_m", months, [rf])[0] for p in picks]
            dds = [_grid(p[p["rf"] == rf], "dd_m", months, [rf])[0] for p in picks]
            common = np.all(
                [np.isfinite(y) & np.isfinite(d) for y, d in zip(ys, dds, strict=True)], axis=0
            )
            if common.sum() < 3:
                rows.append({"rf": rf, "n": int(common.sum())})
                continue
            ys = [np.where(common, y, np.nan) for y in ys]
            dds = [np.where(common, d, np.nan) for d in dds]
            row: dict[str, Any] = {"rf": rf, "n": int(common.sum())}
            specs = {
                "bad": lambda i, S=ys: sum(
                    c * evidence.quantile(s, BAD_Q, i) for c, s in zip(coef, S, strict=True)
                ),
                "drawdown": lambda i, S=dds: sum(
                    c * evidence.cell_mean(s, i) for c, s in zip(coef, S, strict=True)
                ),
                "return": lambda i, S=ys: sum(
                    c * evidence.cell_mean(s, i) for c, s in zip(coef, S, strict=True)
                ),
            }
            for name, fn in specs.items():
                est = boot.estimate(fn, 0.95, int(common.sum()))
                row[name] = {"slope": est.value, "interval": list(est.intervals[evidence.BLOCK])}
            rows.append(row)
        return {"rows": rows}

    # --------------------------------------------------------------------- engine agreement

    def engine_agreement(self, menu: str) -> dict[str, Any]:
        engines = self.engines(menu)
        if len(engines) < 2:
            return {"available": False}
        e1, e2 = engines[0], engines[1]
        a = self.pick(menu, e1, kind="main", pooled=True)
        b = self.pick(menu, e2, kind="main", pooled=True)
        m = a.merge(b, on=SELECTION_KEYS, suffixes=("_a", "_b"))
        if m.empty:
            return {"available": False}
        m["l1"] = [_l1(x, y) for x, y in zip(m["weights_a"], m["weights_b"], strict=True)]
        m["within"] = m["l1"] <= ENGINE_L1
        by_cell = m.groupby("cell")["within"].mean().to_dict()
        by_arm = m.groupby("arm")["within"].mean().to_dict()
        out: dict[str, Any] = {
            "available": True,
            "engines": [e1, e2],
            "pairs": int(len(m)),
            "share_within": float(m["within"].mean()),
            "by_cell": by_cell,
            "by_arm": by_arm,
            "median_l1": float(m["l1"].median()),
        }
        months = self.months(menu)
        k = len(months)
        free = m[(m["arm"] == "U1") & (m["cell"] == "free")]
        if len(free):
            free = free.assign(
                dr=free["ret_m_a"] - free["ret_m_b"], dd=free["dd_m_a"] - free["dd_m_b"]
            )
            boot = self.boot(k)
            res = {}
            for name in ("dr", "dd"):
                g = _grid(free, name, months)
                n = evidence._count(g)
                if n:
                    est = boot.estimate(lambda i, g=g: evidence.origin_mean(g, i), 0.95, n)
                    res[name] = {
                        "mean": est.value,
                        "interval": list(est.intervals[evidence.BLOCK]),
                        "n": n,
                    }
            out["paired_realized"] = res
        return out

    # ---------------------------------------------------------------------------- stability

    def stability(self, menu: str, engine: str) -> dict[str, Any]:
        """Native U1 on the primary and four stability banks: v1's Bad SD and pairwise L1 rules."""
        s = self.sel
        base = (s["menu"] == menu) & (s["engine"] == engine) & (s["arm"] == "U1")
        base &= np.isclose(s["tau_r"].astype(float), C.TAU_R)
        primary = s[
            base
            & (s["kind"] == "main")
            & (s["seed"] == self.primary_seed)
            & ~s["pooled"].astype(bool)
        ]
        others = s[base & (s["kind"] == "stability")]
        rows = pd.concat([primary, others], ignore_index=True)
        rows = rows.sort_values("pooled").drop_duplicates(["month", "rf", "cell", "seed"])
        if "u1" in self.evw and not self.evw["u1"].empty:
            rows["bad_eval"] = rows["sel_id"].map(self.evw["bad"].mean(axis=1))
        else:
            rows["bad_eval"] = np.nan
        rows["bad_used"] = rows["bad_eval"].fillna(rows["bad"])
        seeds = {self.primary_seed, *C.STABILITY_SEEDS}
        out_rows = []
        for cell in C.CELLS:
            for rf in RFS:
                sub = rows[(rows["cell"] == cell) & (rows["rf"] == rf)]
                l1s, share_ok, used = [], [], 0
                for _, g in sub.groupby("month"):
                    if set(g["seed"]) != seeds or len(g) != len(seeds):
                        continue
                    used += 1
                    w = [np.asarray(x, dtype=float) for x in g["weights"]]
                    for i in range(len(w)):
                        for j in range(i + 1, len(w)):
                            l1s.append(float(np.abs(w[i] - w[j]).sum()))
                    sigma = float(g.loc[g["seed"] == self.primary_seed, "sigma"].iloc[0])
                    sd = float(np.std(g["bad_used"].to_numpy(dtype=float), ddof=1))
                    share_ok.append(sd <= BAD_SD_FACTOR * sigma)
                if not used:
                    continue
                med, p90 = float(np.percentile(l1s, 50)), float(np.percentile(l1s, 90))
                share = float(np.mean(share_ok))
                out_rows.append(
                    {
                        "cell": cell,
                        "rf": rf,
                        "origins": used,
                        "median_l1": med,
                        "p90_l1": p90,
                        "bad_sd_share": share,
                        "pass": bool(med <= MEDIAN_L1 and p90 <= P90_L1 and share >= BAD_SD_SHARE),
                    }
                )
        return {"rows": out_rows}

    # ------------------------------------------------------------------------- calibration

    def calibration(self, menu: str, engine: str) -> dict[str, Any]:
        """Coverage `1[y <= f]` and pinball per quantile: daily-rebalanced realized year against the
        training-bank and the independent-bank forecasts, per arm."""
        out: dict[str, Any] = {}
        sel = self.pick(menu, engine, kind="main", pooled=True, keys=SELECTION_KEYS)
        sel = sel[sel["complete"]]
        for arm in C.ARM_ORDER:
            a = sel[sel["arm"] == arm]
            if a.empty:
                continue
            row = {}
            for source in ("training", "independent"):
                for name, q in zip(("bad", "typical", "good"), C.QUANTILES, strict=True):
                    if source == "training":
                        f = a[name].astype(float).to_numpy()
                    elif name in self.evw and not self.evw[name].empty:
                        f = a["sel_id"].map(self.evw[name].mean(axis=1)).to_numpy(dtype=float)
                    else:
                        continue
                    y = a["ret_daily"].astype(float).to_numpy()
                    ok = np.isfinite(y) & np.isfinite(f)
                    if not ok.any():
                        continue
                    frame = pd.DataFrame(
                        {
                            "month": a["month"].to_numpy()[ok],
                            "cover": evaluate.at_or_below(y[ok], f[ok]).astype(float),
                            "loss": evaluate.pinball(q, y[ok], f[ok]),
                        }
                    )
                    per_origin = frame.groupby("month").mean()
                    row[f"{source}_{name}"] = {
                        "nominal": q,
                        "coverage": float(per_origin["cover"].mean()),
                        "pinball": float(per_origin["loss"].mean()),
                        "n": int(ok.sum()),
                    }
            out[arm] = row
        return out

    # ----------------------------------------------------------------------------------- cost

    def cost(self, menu: str, engine: str) -> dict[str, Any]:
        s = self.sel[(self.sel["menu"] == menu) & (self.sel["engine"] == engine)]
        out: dict[str, Any] = {"total_hours": float(s["seconds"].sum() / 3600.0)}
        main = s[s["kind"] == "main"]
        rows = []
        for arm, g in main.groupby("arm"):
            sec = g["seconds"].astype(float)
            rows.append(
                {
                    "arm": arm,
                    "n": int(len(g)),
                    "median": float(sec.median()),
                    "p95": float(np.percentile(sec, 95)),
                    "iterations": float(g["iterations"].median()),
                }
            )
        out["by_arm"] = rows
        show = s[s["kind"] == "showcase"]
        if len(show):
            surfaces = max(show["month"].nunique(), 1)
            out["showcase_seconds_per_surface"] = float(show["seconds"].sum() / surfaces)
            out["showcase_surfaces"] = int(show["month"].nunique())
        out["solvers"] = {str(k): int(v) for k, v in s["solver"].value_counts().items()}
        return out

    def labels(self, menu: str, engine: str) -> list[dict[str, Any]]:
        """Counts of non-ok statuses per cell and risk level (never called infeasible)."""
        s = self.sel[
            (self.sel["menu"] == menu)
            & (self.sel["engine"] == engine)
            & (self.sel["kind"] == "main")
        ]
        bad = s[s["status"] != C.OK]
        if bad.empty:
            return []
        g = bad.groupby(["status", "cell", "rf"]).size().reset_index(name="count")
        return g.to_dict("records")

    # ------------------------------------------------------------------------------ regimes

    def regimes(self, menu: str, engine: str) -> list[dict[str, Any]]:
        """White-line realized difference (U1 free minus w_F) by regime bucket; descriptive."""
        u = self.pick(menu, engine, kind="main", arm="U1", cell="free", pooled=True)
        f = self.pick(menu, engine, kind="comparator", arm="F", cell="free", pooled=None)
        m = u.merge(f, on=["month", "rf"], suffixes=("_a", "_b"))
        m = m[m["complete_a"] & m["regime_a"].notna()]
        rows = []
        for label, g in m.groupby("regime_a"):
            origins = g.groupby("month")
            d = (g["ret_m_a"] - g["ret_m_b"]).groupby(g["month"]).mean()
            dd = (g["dd_m_a"] - g["dd_m_b"]).groupby(g["month"]).mean()
            rows.append(
                {
                    "regime": label,
                    "origins": int(origins.ngroups),
                    "mean_return_diff": float(d.mean()),
                    "mean_drawdown_diff": float(dd.mean()),
                    "mean_return_u1": float(g["ret_m_a"].mean()),
                    "mean_return_f": float(g["ret_m_b"].mean()),
                }
            )
        return rows

    def horizons(self, menu: str, engine: str) -> list[dict[str, Any]]:
        """Descriptive 1/3/5-year nominal and real outcomes (monthly convention): U1 free vs F."""
        u = self.pick(menu, engine, kind="main", arm="U1", cell="free", pooled=True)
        f = self.pick(menu, engine, kind="comparator", arm="F", cell="free", pooled=None)
        m = u.merge(f, on=["month", "rf"], suffixes=("_a", "_b"))
        rows = []
        for name, col in (
            ("1y", "ret_m"),
            ("3y", "ret_3y"),
            ("5y", "ret_5y"),
            ("1y real", "real_m"),
            ("3y real", "real_3y"),
            ("5y real", "real_5y"),
        ):
            a, b = m[f"{col}_a"], m[f"{col}_b"]
            ok = a.notna() & b.notna()
            if not ok.any():
                continue
            rows.append(
                {
                    "horizon": name,
                    "n": int(ok.sum()),
                    "origins": int(m.loc[ok, "month"].nunique()),
                    "u1": float(a[ok].mean()),
                    "f": float(b[ok].mean()),
                    "diff": float((a[ok] - b[ok]).mean()),
                }
            )
        return rows

    def cost_variant(self, menu: str, engine: str) -> dict[str, Any]:
        u = self.pick(menu, engine, kind="main", arm="U1", cell="free", pooled=True)
        f = self.pick(menu, engine, kind="comparator", arm="F", cell="free", pooled=None)
        m = u.merge(f, on=["month", "rf"], suffixes=("_a", "_b"))
        m = m[m["ret_m_a"].notna() & m["ret_m_b"].notna()]
        if m.empty:
            return {}
        return {
            "gross_diff": float((m["ret_m_a"] - m["ret_m_b"]).mean()),
            "net_diff": float((m["ret_net_a"] - m["ret_net_b"]).mean()),
            "turnover_u1": float(m["turnover_a"].mean()),
            "turnover_f": float(m["turnover_b"].mean()),
            "net_u1": float(m["ret_net_a"].mean()),
            "net_f": float(m["ret_net_b"].mean()),
        }

    # ----------------------------------------------------------------------- CSCV and DSR

    def cscv_inputs(self, menu: str, engine: str) -> tuple[np.ndarray, list[str], dict[str, Any]]:
        """(returns A x K x C, eligible months, counts) for the four triples' common mask."""
        led = self.ledger(menu)
        months = list(led["month"])
        idx = {m: i for i, m in enumerate(months)}
        pairs = [(rf, c) for rf in RFS for c in C.CELLS]
        arms = ("U1", "U2", "U3", "U4")
        x = np.full((4, len(months), len(pairs)), np.nan)
        counts = {"excluded_labelled": 0, "excluded_incomplete": 0, "rows": 0}
        picks = [self.pick(menu, engine, kind="main", arm=a, pooled=True) for a in arms]
        keyed = [p.set_index(["month", "rf", "cell"]) for p in picks]
        every = set().union(*[set(k.index) for k in keyed])
        for key in every:
            month, rf, cell = key
            if month not in idx:
                counts["excluded_incomplete"] += 1
                continue
            rows = [k.loc[key] if key in k.index else None for k in keyed]
            if any(r is None for r in rows):
                counts["excluded_incomplete"] += 1
                continue
            if any((r["status"] != C.OK) or not np.isfinite(r["ret_m"]) for r in rows):
                counts["excluded_labelled"] += 1
                continue
            j = pairs.index((rf, cell))
            for a, r in enumerate(rows):
                x[a, idx[month], j] = r["ret_m"]
            counts["rows"] += 1
        return x, months, counts

    def cscv(self, menu: str, engine: str, masks: cscv.CscvMasks | None = None) -> dict[str, Any]:
        led = self.ledger(menu)
        if len(led) < cscv.BLOCKS:
            return {"available": False, "reason": f"{len(led)} eligible origins"}
        masks = masks or cscv.cscv_masks(led["origin"].to_numpy(), led["horizon_end"].to_numpy())
        x, _, counts = self.cscv_inputs(menu, engine)
        result = cscv.cscv_run(masks, x)
        disjoint_train = [
            len(disjoint_origins(list(masks.origins[s.train]), list(masks.ends[s.train])))
            for s in masks.splits
        ]
        disjoint_test = [
            len(disjoint_origins(list(masks.origins[s.test]), list(masks.ends[s.test])))
            for s in masks.splits
        ]
        names = ("U1", "U2", "U3", "U4")
        ev = result.evaluable
        return {
            "available": True,
            "pairs": result.pairs,
            "counts": counts,
            "splits": result.splits_total,
            "evaluable": len(ev),
            "dropped": len(result.dropped),
            "dropped_reasons": sorted({d["reason"].split(" keeps")[0] for d in result.dropped}),
            "pbo": result.pbo,
            "note": result.pbo_note,
            "chosen_share": result.choice_shares(names),
            "tied_splits": int(sum(r["tied"] for r in ev)),
            "mean_test_u": [
                float(np.mean([r["test_u"][i] for r in ev])) if ev else None for i in range(4)
            ],
            "mean_rank_u1": float(np.mean([r["rank"] for r in ev])) if ev else None,
            "scatter": [(r["train_u"][r["chosen"]], r["test_u"][r["chosen"]]) for r in ev],
            "origins_train": [
                int(min(s.train.sum() for s in masks.splits)),
                int(max(s.train.sum() for s in masks.splits)),
            ],
            "origins_test": [
                int(min(s.test.sum() for s in masks.splits)),
                int(max(s.test.sum() for s in masks.splits)),
            ],
            "disjoint_train_median": float(np.median(disjoint_train)),
            "disjoint_test_median": float(np.median(disjoint_test)),
        }

    def dsr_series(self, menu: str, engine: str) -> tuple[np.ndarray, list[str], list[str]]:
        """(n x 20 trial series on the disjoint origins, their (arm, cell) names, the months)."""
        months = self.disjoint_months(menu)
        f = self.pick(menu, engine, kind="comparator", arm="F", cell="free", pooled=None)
        fm = f.groupby(["month", "rf"])["ret_m"].first()
        names, cols = [], []
        for arm in C.ARM_ORDER:
            for cell in ("free", "d25", "d50", "d75"):
                s = self.pick(menu, engine, kind="main", arm=arm, cell=cell, pooled=True)
                sm = s.groupby(["month", "rf"])["ret_m"].first()
                diff = (sm - fm).dropna()
                per_month = diff.groupby(level="month").mean()
                names.append(f"{arm}/{cell}")
                cols.append(per_month.reindex(months).to_numpy(dtype=float))
        return np.column_stack(cols), names, months

    def deflated_sharpe(self, menu: str, engine: str) -> dict[str, Any]:
        x, names, months = self.dsr_series(menu, engine)
        rows = np.isfinite(x).all(axis=1)
        if rows.sum() < 3:
            return {"available": False, "reason": f"{int(rows.sum())} complete disjoint origins"}
        primary = names.index("U1/free")
        res = dsr.deflated_sharpe(x[rows], primary)
        return {
            "available": True,
            "disjoint_total": len(months),
            "dropped_origins": int((~rows).sum()),
            **res.record(),
        }
