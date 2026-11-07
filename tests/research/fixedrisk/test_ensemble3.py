"""The §7.3 ensemble screen end to end on synthetic task files with known answers: the digest
gate, the pool filter, the picks' realized outcomes against a direct computation, and the
combination statistics, CSCV (omega = k/127) and DSR wiring."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from portfoliosight.research.fixedrisk import analysis3 as A
from portfoliosight.research.fixedrisk import contracts as C
from portfoliosight.research.fixedrisk import cscv
from portfoliosight.research.fixedrisk import ensemble3 as E
from portfoliosight.research.fixedrisk import realized as R
from portfoliosight.research.fixedrisk.driver import DIGEST_KEY
from portfoliosight.research.fixedrisk.objectives3 import FIELDS
from portfoliosight.research.fixedrisk.pool import PoolBuffer, write_pool

from .synth import month_labels, origin_of

DIGEST = "digest-e"
MENU, ENGINE = "research2003", "replay"
MIX = {"a": [1.0, 0.0], "b": [0.0, 1.0], "c": [0.5, 0.5]}
# objectives per mix: a is the frontier-like mix (arm 1), b the low-drawdown one, c diversified
OBJ = {
    "a": {"mu": 3.0, "u1": 3.0, "tdd": 0.3, "h": 0.3, "enlc": 1.0, "enb": 1.0},
    "b": {"mu": 1.0, "u1": 1.0, "tdd": 0.1, "h": 0.1, "enlc": 1.5, "enb": 1.5},
    "c": {"mu": 2.0, "u1": 2.0, "tdd": 0.2, "h": 0.2, "enlc": 2.0, "enb": 2.0},
}
RANK = {  # percentile ranks among the three candidates, oriented so higher is better
    "a": [1.0, 1.0, 1 / 3, 1 / 3, 1 / 3, 1 / 3],
    "b": [1 / 3, 1 / 3, 1.0, 1.0, 2 / 3, 2 / 3],
    "c": [2 / 3, 2 / 3, 2 / 3, 2 / 3, 1.0, 1.0],
}


def _values(**kw) -> np.ndarray:
    v = np.zeros(len(FIELDS))
    for name, value in kw.items():
        v[FIELDS.index(name)] = value
    return v


def _pool(month: str) -> PoolBuffer:
    buf = PoolBuffer()
    for rf in C.RISK_FRACTIONS:
        for name in ("a", "b", "c"):
            buf.add(lookback="3y", r_fraction=rf, r=0.1, lam=None, arm="", start=-1, call=-1,
                    source="sobol", weights=np.array(MIX[name]),
                    values=_values(in_wide=1.0, sigma=0.1, **OBJ[name]))  # fmt: skip
        noise = [
            ("3y", None, [1e-12, 1.0 - 1e-12], 1.0, {"mu": 99.0}),  # duplicate of b, later record
            ("3y", 0.05, [0.2, 0.8], 1.0, {"mu": 99.0, "u1": 99.0, "enb": 99.0}),  # side check
            ("3y", None, [0.3, 0.7], 0.0, {"mu": 99.0, "u1": 99.0}),  # outside the wide band
            ("5y", None, [0.4, 0.6], 1.0, {"mu": 99.0, "u1": 99.0}),  # 5-year side check
        ]
        for lookback, lam, w, wide, over in noise:
            buf.add(lookback=lookback, r_fraction=rf, r=0.1, lam=lam, arm="crash_penalty"
                    if lam else "U1", start=0, call=0, source="search", weights=np.array(w),
                    values=_values(in_wide=wide, sigma=0.1, **{**OBJ["b"], **over}))  # fmt: skip
    return buf


def _write(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pandas(frame, preserve_index=False)
    pq.write_table(table.replace_schema_metadata({DIGEST_KEY: DIGEST.encode()}), path)


def _job(tmp_path: Path, months: list[str]) -> Path:
    job = tmp_path / "run" / "research2003_replay"
    tasks = job / "tasks"
    for month in months:
        base = f"{MENU}_{month}_{ENGINE}"
        sel = pd.DataFrame(
            [{"sel_id": f"{month}|{rf}", "kind": "main", "menu": MENU, "month": month,
              "origin": origin_of(month).date(), "engine": ENGINE, "lookback": "3y",
              "lam": None, "r_fraction": rf, "arm": C.FRONTIER, "pooled": False,
              "weights": MIX["a"], "status": C.OK, "sigma": 0.1, "tdd": 0.3}
             for rf in C.RISK_FRACTIONS]
        )  # fmt: skip
        _write(tasks / f"{base}.parquet", sel)
        _write(tasks / "columns" / f"{base}.parquet", pd.DataFrame({"month": [month]}))
        _write(tasks / "evaluated" / f"{base}.parquet", pd.DataFrame({"sel_id": ["x"]}))
        table = _pool(month).table(menu=MENU, month=month, origin=origin_of(month).date(),
                                   engine=ENGINE, seed=C.PRIMARY_SEED)  # fmt: skip
        write_pool(tasks / "pool" / f"{base}.parquet", table, {DIGEST_KEY: DIGEST.encode()})
    return job


def _returns() -> np.ndarray:
    """Fund 0 rises, crashes 26% in 30 days and recovers; fund 1 creeps up."""
    r0 = np.r_[np.full(100, 0.002), np.full(30, -0.01), np.full(122, 0.001)]
    return np.column_stack([r0, np.full(252, 0.0001)])


def _horizon(complete: set[str]):
    def horizon(menu, month):
        if month not in complete:
            return None
        days = pd.bdate_range(origin_of(month) + pd.Timedelta(days=1), periods=252)
        return list(days), _returns(), ("F0", "F1")

    return horizon


def _parent(months, eligible, frozen=None):
    cscv_record = dict(frozen or {}) or {"months": eligible}
    disjoint = [{"month": m} for m in eligible[::2]]
    return {"digest": DIGEST,
            "menus": {MENU: {"schedule": months, "cscv": cscv_record,
                             "disjoint_intervals": disjoint}}}  # fmt: skip


def _direct(name: str, month: str) -> tuple[float, float]:
    days = pd.bdate_range(origin_of(month) + pd.Timedelta(days=1), periods=252)
    out = R.monthly_rebalanced(_returns(), list(days), [MIX[name]])
    return float(out.annual[0]), float(out.drawdown[0])


def _expected_pick(w: np.ndarray) -> str:
    scores = {name: float(np.dot(RANK[name], w)) for name in ("a", "b", "c")}
    best = max(scores.values())
    return next(n for n in ("a", "b", "c") if np.isclose(scores[n], best))  # record order a, b, c


# -------------------------------------------------------------------------------- tests


def test_the_digest_record_gates_and_detects_changes(tmp_path):
    job = tmp_path / "job"
    job.mkdir()
    analysis = tmp_path / "analysis.json"
    analysis.write_text('{"label": "pass"}')
    with pytest.raises(ValueError, match="no analysis digest recorded"):
        E.verified_entry(job, "analysis")
    E.record_analysis(job, analysis)
    assert E.verified_entry(job, "analysis") == analysis.resolve()
    assert E.verified_entry(job, "analysis", analysis) == analysis
    other = tmp_path / "other.json"
    other.write_text("{}")
    with pytest.raises(ValueError, match="is not the recorded analysis file"):
        E.verified_entry(job, "analysis", other)
    ensemble = tmp_path / "ensemble.json"
    ensemble.write_text("{}")
    E.record_ensemble(job, ensemble)
    record = json.loads((job / E.RECORD_FILE).read_text())
    assert set(record) == {"analysis", "ensemble"}
    analysis.write_text('{"label": "fail (return)"}')
    with pytest.raises(ValueError, match="changed after its digest was recorded"):
        E.verified_entry(job, "analysis")
    E.record_analysis(job, analysis)  # a new analysis drops the older ensemble entry
    assert set(json.loads((job / E.RECORD_FILE).read_text())) == {"analysis"}


def test_the_screen_reads_no_outcome_before_the_analysis_digest_is_recorded(tmp_path):
    months = month_labels(3)
    job = _job(tmp_path, months)

    def horizon(menu, month):
        raise AssertionError("a realized outcome was read before the digest was recorded")

    with pytest.raises(ValueError, match="no analysis digest recorded"):
        E.screen_job(job, _parent(months, months), MENU, ENGINE, horizon)


def test_read_main_pool_keeps_the_main_wide_band_three_year_rows(tmp_path):
    months = month_labels(1)
    job = _job(tmp_path, months)
    pool = E.read_main_pool(job / "tasks" / "pool" / f"{MENU}_{months[0]}_{ENGINE}.parquet")
    assert len(pool) == 6 * 4  # a, b, c and the duplicate of b per level
    assert set(pool["lookback"]) == {"3y"} and bool(pool["lam"].isna().all())
    assert bool(pool["in_wide"].all())
    assert np.vstack(pool["weights"].to_list()).shape == (24, 2)


def test_the_screen_picks_and_scores_against_a_direct_computation(tmp_path):
    months = month_labels(6)
    eligible = months[:5]  # the last origin has no complete realized year
    job = _job(tmp_path, months)
    analysis = tmp_path / "analysis.json"
    analysis.write_text("{}")
    E.record_analysis(job, analysis)
    picks_out = tmp_path / "picks.parquet"
    out = E.screen_job(job, _parent(months, eligible), MENU, ENGINE, _horizon(set(eligible)),
                       resamples=50, picks_out=picks_out)  # fmt: skip
    assert out["label"] == E.EXPLORATORY and out["combinations_count"] == 126
    assert out["analysis_sha256"] == E.sha256_file(analysis)
    assert out["candidates"]["cells"] == 6 * 5 and out["candidates"]["median"] == 3.0
    # each origin's calendar sets its own month-end rebalances, so the mean is over origins
    direct = {n: np.array([_direct(n, m) for m in eligible]) for n in ("a", "b", "c")}
    weights = A.simplex_weights()
    for combo in out["combinations"]:
        x = direct[_expected_pick(weights[combo["combination"]])]
        assert combo["paired_cells"] == 6 * 5
        assert combo["theta_dd"] == pytest.approx(np.mean(direct["a"][:, 1] - x[:, 1]), abs=1e-12)
        assert combo["theta_ret"] == pytest.approx(np.mean(x[:, 0] - direct["a"][:, 0]), abs=1e-12)
    mu_only = next(c for c in out["combinations"] if c["weights"]["mu"] == 1.0)
    assert mu_only["theta_dd"] == pytest.approx(0.0) and mu_only["description"] == A.FAIL_DD
    assert mu_only["theta_dd_interval"] == pytest.approx([0.0, 0.0])
    tdd_only = next(c for c in out["combinations"] if c["weights"]["tdd"] == 1.0)
    d_b = direct["a"][:, 1] - direct["b"][:, 1]
    assert np.ptp(d_b) == pytest.approx(0.0) and d_b[0] > 0.2  # b and a never rebalance
    assert tdd_only["theta_dd"] == pytest.approx(d_b[0])
    assert tdd_only["theta_dd_interval"] == pytest.approx([d_b[0]] * 2)
    picks = pd.read_parquet(picks_out)
    assert set(picks["month"]) == set(eligible)
    assert set(picks["record"] % 7) <= {0, 1, 2}  # only a, b or c (the first three rows a level)
    assert out["would_pass"] == [c["combination"] for c in out["combinations"]
                                 if c["A"] and c["B"]]  # fmt: skip


def test_combination_statistics_on_constant_differences():
    k = 40
    dd1, r1 = np.full((6, k), 0.20), np.full((6, k), 0.05)
    dd = np.stack([np.full((6, k), 0.20 - d) for d in (0.0, 0.02, 0.005)])
    ret = np.stack([np.full((6, k), 0.05 + d) for d in (0.0, -0.001, -0.01)])
    w = A.simplex_weights()[:3]
    out = E.combination_statistics(dd1, r1, dd, ret, w, resamples=50)
    assert [c["description"] for c in out] == [A.FAIL_DD, E.WOULD_PASS, A.FAIL_BOTH]
    assert out[1]["theta_ret_p5"] == pytest.approx(-0.001)


def test_cscv_over_the_combinations_uses_k_over_combinations_plus_one():
    months = month_labels(120)
    stamps = [origin_of(m).date() for m in months]
    ends = [(pd.Timestamp(s) + pd.Timedelta(days=20)).date() for s in stamps]
    frozen = cscv.frozen_record(months, stamps, ends)
    rng = np.random.default_rng(3)
    dd = 0.1 + 0.01 * rng.random((126, 6, len(months)))
    dd[5] = 0.01  # combination 5 always has the lowest realized drawdown
    out = E.cscv_combinations(dd, months, frozen)
    assert out["available"] and out["omega_denominator"] == 127 and out["evaluable"] > 0
    assert out["chosen_counts"] == {"5": out["evaluable"]}
    assert out["mean_test_rank"] == pytest.approx(126.0)
    assert not E.cscv_combinations(dd, months, {"months": months})["available"]


def test_dsr_over_the_combinations_takes_the_best_sharpe_as_primary():
    months = month_labels(30)
    rng = np.random.default_rng(5)
    dd1 = np.full((6, 30), 0.2)
    dd = 0.2 + rng.normal(0.0, 0.01, size=(126, 6, 30))
    dd[17] = 0.2 - 0.02 - rng.normal(0.0, 0.001, size=(6, 30))  # a steady improvement
    out = E.dsr_combinations(dd1, dd, months, months[::3])
    assert out["available"] and out["primary"] == 17 and out["trials"] == 126
    assert out["intervals"] == 10 and out["n"] == 10
