"""Synthetic run directory, horizons and realized tables for the piece-4 tests."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from portfoliosight.research.fixedrisk import contracts as C

RFS = tuple(round(x, 6) for x in C.RISK_FRACTIONS)
HOLDINGS = ("A", "B", "C")
TEST_SEEDS = C.TEST_SEEDS


def month_labels(n: int, start: str = "2010-01") -> list[str]:
    return [str(p) for p in pd.period_range(start, periods=n, freq="M")]


def origin_of(month: str) -> pd.Timestamp:
    return pd.Period(month, freq="M").to_timestamp(how="end").normalize()


def _weights(rng_seed: int) -> np.ndarray:
    return np.random.default_rng(rng_seed).dirichlet(np.ones(len(HOLDINGS)))


def _row(**kw):
    base = dict(
        lookback="3y",
        tau_r=C.TAU_R,
        pooled=True,
        status=C.OK,
        starts=3,
        iterations=20,
        seconds=1.0,
        solver="exact_grad",
        seed=C.PRIMARY_SEED,
    )
    base.update(kw)
    return base


def build_run(
    root: Path,
    *,
    n_months: int = 30,
    engines: tuple[str, ...] = ("replay", "garch"),
    menu: str = "m1",
    seed: int = 0,
    with_parent: bool = False,
    complete_until: int = 16,
    disjoint: int = 20,
) -> list[str]:
    """Write <root>/<menu>-<engine>/tasks/ in the driver's layout; return the ledger months.

    `with_parent` also writes a parent manifest naming exactly these jobs (its frozen CSCV masks
    on the months up to `complete_until`, `disjoint` published intervals), complete job manifests,
    and stamps every task file with its digest."""
    months = month_labels(n_months)
    rng = np.random.default_rng(seed)
    parent = (
        synth_parent(months, engines, menu, complete_until=complete_until, disjoint=disjoint)
        if with_parent
        else None
    )
    digest = parent["digest"] if parent else ""
    for engine in engines:
        sel, anc, ev = [], [], []
        for mi, month in enumerate(months):
            origin = origin_of(month).date()
            for ri, rf in enumerate(RFS):
                anc.append(
                    dict(
                        menu=menu,
                        month=month,
                        origin=origin,
                        lookback="3y",
                        tau_r=C.TAU_R,
                        r_fraction=rf,
                        r=0.05 + 0.1 * rf,
                        sigma_min=0.03,
                        sigma_top=0.2,
                        w_F=[1.0, 0, 0],
                        w_MDP=[0.3, 0.3, 0.4],
                        w_BS=[0.5, 0.5, 0],
                        M_F=1.0,
                        M_MDP=1.5,
                        collapsed=bool(mi == 0 and ri == 0),
                        status=C.OK,
                        engine=engine,
                        grid="main",
                    )
                )
                for cell in C.CELLS:
                    for ai, arm in enumerate(C.ARM_ORDER):
                        key = 1 + mi * 1000 + ri * 100 + C.CELLS.index(cell) * 10 + ai
                        w = _weights(abs(key))
                        if engine == "garch" and arm not in ("U1", "U2"):
                            w = 0.5 * w
                            w[np.argmin(w)] += 0.5
                        d = (
                            None
                            if (mi == 0 and ri == 0)
                            else float(rng.uniform(-0.2, 1.2))
                            if cell == "free"
                            else C.CELL_D[cell]
                        )
                        sel_args = dict(
                            menu=menu,
                            month=month,
                            origin=origin,
                            engine=engine,
                            r_fraction=rf,
                            r=0.05 + 0.1 * rf,
                            cell=cell,
                            arm=arm,
                            weights=list(w),
                            sigma=0.05 + 0.1 * rf,
                            measure=1.2,
                            d=d,
                            bad=-0.10 + 0.01 * rng.standard_normal(),
                            typical=0.05,
                            good=0.2,
                            mean=0.06,
                            es_25=-0.13,
                        )
                        sel.append(
                            _row(
                                sel_id=f"{engine}|main|{month}|{rf}|{cell}|{arm}|T",
                                kind="main",
                                **sel_args,
                            )
                        )
                        if arm == "U1":
                            sel.append(
                                _row(
                                    sel_id=f"{engine}|main|{month}|{rf}|{cell}|{arm}|F",
                                    kind="main",
                                    **{**sel_args, "pooled": False},
                                )
                            )
                            if mi % 4 == 0:  # the primary seed's native-only run and four more
                                for s in (C.PRIMARY_SEED, *C.STABILITY_SEEDS):
                                    sel.append(
                                        _row(
                                            sel_id=f"{engine}|stab|{month}|{rf}|{cell}|{s}",
                                            kind="stability",
                                            **{
                                                **sel_args,
                                                "pooled": False,
                                                "seed": s,
                                                "weights": list(_weights(abs(key) + s % 1000)),
                                            },
                                        )
                                    )
                for arm in ("F", "BS"):
                    sel.append(
                        _row(
                            sel_id=f"{engine}|comp|{month}|{rf}|{arm}",
                            kind="comparator",
                            menu=menu,
                            month=month,
                            origin=origin,
                            engine=engine,
                            r_fraction=rf,
                            r=0.05 + 0.1 * rf,
                            cell="free",
                            arm=arm,
                            weights=list(_weights(mi * 7 + ri)),
                            sigma=0.05 + 0.1 * rf + 0.001,
                            measure=1.0,
                            d=0.0,
                            bad=-0.11,
                            typical=0.05,
                            good=0.2,
                            mean=0.06,
                            es_25=-0.14,
                        )
                    )
                if mi < 6:
                    for arm in ("U1", "F"):
                        sel.append(
                            _row(
                                sel_id=f"{engine}|tau|{month}|{rf}|{arm}",
                                kind="sens_tau",
                                tau_r=C.TAU_R_SENSITIVITY,
                                menu=menu,
                                month=month,
                                origin=origin,
                                engine=engine,
                                r_fraction=rf,
                                r=0.05 + 0.1 * rf,
                                cell="free",
                                arm=arm,
                                weights=list(_weights(mi * 11 + ri)),
                                sigma=0.05,
                                measure=1.0,
                                d=0.0,
                                bad=-0.10 if arm == "U1" else -0.11,
                                typical=0.05,
                                good=0.2,
                                mean=0.06,
                                es_25=-0.13,
                            )
                        )
        for srf in (0.05, 0.15):
            anc.append(
                dict(
                    menu=menu,
                    month=months[0],
                    origin=origin_of(months[0]).date(),
                    lookback="3y",
                    tau_r=C.TAU_R,
                    r_fraction=srf,
                    r=0.06,
                    sigma_min=0.03,
                    sigma_top=0.2,
                    w_F=[1.0, 0, 0],
                    w_MDP=[0.3, 0.3, 0.4],
                    w_BS=[0.5, 0.5, 0],
                    M_F=1.0,
                    M_MDP=1.5,
                    collapsed=srf == 0.05,
                    status=C.OK,
                    engine=engine,
                    grid="showcase",
                )
            )
            sel.append(
                _row(
                    sel_id=f"{engine}|show|{srf}",
                    kind="showcase",
                    menu=menu,
                    month=months[0],
                    origin=origin_of(months[0]).date(),
                    engine=engine,
                    r_fraction=srf,
                    r=0.06,
                    cell="d25",
                    arm="U1",
                    weights=[0.3, 0.3, 0.4],
                    sigma=0.06,
                    measure=1.2,
                    d=0.25,
                    bad=-0.1,
                    typical=0.05,
                    good=0.2,
                    mean=0.06,
                    es_25=-0.13,
                )
            )
        for row in sel:
            if row["kind"] == "showcase":
                continue
            for ts in TEST_SEEDS:
                u1 = row["arm"] == "U1" and row["kind"] in ("main", "sens_tau")
                ev.append(
                    dict(
                        sel_id=row["sel_id"],
                        test_seed=ts,
                        bad=row["bad"] + (0.003 if u1 else 0.0),
                        typical=row["typical"],
                        good=row["good"],
                        mean=row["mean"],
                        es_25=row["es_25"],
                    )
                )
        write_job(root / f"{menu}-{engine}", sel, anc, ev, digest)
        if parent:
            job = {
                "parent_digest": digest,
                "status": "complete",
                "tasks_done": len(months),
                "tasks_total": len(months),
                "tasks_failed": 0,
                "breach": None,
            }
            (root / f"{menu}-{engine}" / "job.json").write_text(json.dumps(job))
    if parent:
        (root / "parent.json").write_text(json.dumps(parent))
    return months


def frozen_cscv(months: list[str], complete_until: int) -> dict:
    """The parent's CSCV record over the months with a complete realized year (origin + 365 d)."""
    from portfoliosight.research.fixedrisk import cscv

    done = months[: complete_until + 1]
    origins = [origin_of(m) for m in done]
    return cscv.frozen_record(done, origins, [o + pd.Timedelta(days=365) for o in origins])


def synth_parent(
    months: list[str], engines, menu: str = "m1", *, complete_until: int = 16, disjoint: int = 20
) -> dict:
    from portfoliosight.research.fixedrisk import manifest

    body = {
        "kind": "fixed_risk_parent",
        "snapshot": {"manifest_sha256": "5" * 64},
        "jobs": {
            f"{menu}-{e}": {"menu": menu, "engine": e, "host": "local", "cpu_hours_budget": 1.0}
            for e in engines
        },
        "menus": {
            menu: {
                "schedule": list(months),
                "cscv": frozen_cscv(months, complete_until),
                "disjoint_intervals": [{"month": m} for m in months[:disjoint]],
            }
        },
    }
    return {**body, "digest": manifest.body_digest(body)}


def write_job(
    job: Path, sel: list[dict], anc: list[dict], ev: list[dict], digest: str = ""
) -> None:
    """The driver's layout: one task per month, `tasks/<task>.parquet` (selections, the marker),
    `tasks/anchors/<task>.parquet`, `tasks/evaluated/<task>.parquet`, each with the digest."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    month_of = {row["sel_id"]: row["month"] for row in sel}
    for month in sorted({row["month"] for row in sel}):
        base = f"{job.name}_{month}"
        parts = {
            job / "tasks" / f"{base}.parquet": [r for r in sel if r["month"] == month],
            job / "tasks" / "anchors" / f"{base}.parquet": [r for r in anc if r["month"] == month],
            job / "tasks" / "evaluated" / f"{base}.parquet": [
                r for r in ev if month_of[r["sel_id"]] == month
            ],
        }
        for path, rows in parts.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            table = pa.Table.from_pandas(pd.DataFrame(rows), preserve_index=False)
            table = table.replace_schema_metadata({b"parent_digest": digest.encode()})
            pq.write_table(table, path)


def synth_horizon(n_months: int = 30, complete_until: int = 16):
    """horizon(menu, month): 252 seeded business days; None after `complete_until`."""
    months = month_labels(n_months)

    def horizon(menu: str, month: str):
        mi = months.index(month)
        if mi > complete_until:
            return None
        days = pd.bdate_range(origin_of(month) + pd.Timedelta(days=1), periods=252)
        values = np.random.default_rng(mi).normal(0.0004, 0.01, size=(252, len(HOLDINGS)))
        return list(days), values, HOLDINGS

    return horizon


def fake_realized(
    sel: pd.DataFrame,
    *,
    complete_until: int = 16,
    n_months: int = 30,
    white_offset: float = 0.01,
    noise: float = 0.0,
) -> pd.DataFrame:
    """Controlled realized table: base return per (month, r); U1 free = base + white_offset;
    U1 at d = .25/.50/.75 = base + 0.1 d (drawdown base - 0.05 d); max-Bad = base - .005."""
    import zlib

    months = month_labels(n_months)
    rows = []
    for r in sel.itertuples():
        mi = months.index(r.month)
        if mi > complete_until:
            rows.append(dict(sel_id=r.sel_id, complete=False))
            continue
        base = np.random.default_rng(zlib.crc32(f"{r.month}|{r.rf}".encode())).normal(0.05, 0.1)
        base_dd = 0.2 + 0.01 * (zlib.crc32(f"d{r.month}|{r.rf}".encode()) % 10)
        eps = (
            np.random.default_rng(
                zlib.crc32(f"{r.month}|{r.rf}|{r.cell}|{r.arm}".encode())
            ).normal()
            * noise
        )
        ret, dd = base, base_dd
        if r.arm == "U1" and r.cell == "free" and r.kind in ("main", "sens_tau"):
            ret, dd = base + white_offset + eps, base_dd - 0.02
        elif r.arm == "U1" and r.cell in ("d25", "d50", "d75"):
            d = C.CELL_D[r.cell]
            ret, dd = base + 0.1 * d + eps, base_dd - 0.05 * d
        elif r.arm == "B":
            ret = base - 0.005 + eps
        elif r.arm in ("U2", "U3", "U4"):
            ret = base + 0.001 * int(r.arm[1]) + eps
        end = origin_of(r.month) + pd.Timedelta(days=365)
        rows.append(
            dict(
                sel_id=r.sel_id,
                complete=True,
                horizon_end=end,
                ret_daily=ret + 0.001,
                dd_daily=dd,
                ret_m=ret,
                dd_m=dd,
                ret_net=ret - 0.001,
                dd_net=dd,
                turnover=0.1,
                real_m=ret - 0.02,
                regime="equity drawdown" if mi % 5 == 0 else "calm",
                ret_3y=ret * 3,
                ret_5y=np.nan,
                real_3y=ret * 3 - 0.05,
                real_5y=np.nan,
            )
        )
    return pd.DataFrame(rows)
