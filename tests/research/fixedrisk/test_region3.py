"""The region check (docs/plans/2026-11-09-fixed-risk-v3-region-check.md, with its corrections)
on small made-up pools and return series whose answers are known by hand: region membership at
the 50 bp floor and the risk ceiling, the left tip blend, the rank-blend picks and their
tie-break, the ceilings, the decision rules and determinism."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from portfoliosight.research import evidence
from portfoliosight.research.fixedrisk import analysis3 as A
from portfoliosight.research.fixedrisk import contracts as C
from portfoliosight.research.fixedrisk import ensemble3 as E
from portfoliosight.research.fixedrisk import realized as R
from portfoliosight.research.fixedrisk import region3 as G
from portfoliosight.research.fixedrisk.driver import DIGEST_KEY
from portfoliosight.research.fixedrisk.objectives3 import FIELDS
from portfoliosight.research.fixedrisk.pool import PoolBuffer, write_pool

from .synth import month_labels, origin_of

DIGEST = "digest-g"
MENU, ENGINE = "research2003", "replay"
BOUNDS = ((0.0, 0.0), (1.0, 1.0))  # the two-fund test menu


# ------------------------------------------------------------------------------ helpers


def _mixes(rows: list[dict]) -> pd.DataFrame:
    """A distinct-mix table as `distinct_mixes` returns it, in tie order."""
    base = {"record": 0, "r_fraction": 0.25, "sigma": 0.1, "mu": 0.08, "tdd": 0.2, "enb": 1.0,
            "h": 0.2, "line_mask": 0, "weights": None}  # fmt: skip
    out = [{**base, "record": i, **row} for i, row in enumerate(rows)]
    for row in out:
        if row["weights"] is None:
            row["weights"] = np.array([1.0, 0.0])
    return pd.DataFrame(out)


def _values(**kw) -> np.ndarray:
    v = np.zeros(len(FIELDS))
    for name, value in kw.items():
        v[FIELDS.index(name)] = value
    return v


# ------------------------------------------------------------------------- region edges


def test_region_membership_at_the_return_floor_and_the_risk_ceiling():
    r, mu_f = 0.1, 0.08
    # the ceiling is r (1 + 0.01) + 1e-8 = 0.10100001; the floor is mu_F - 0.005
    mixes = _mixes(
        [
            {"mu": mu_f - 0.005, "sigma": 0.1},  # 0: exactly at the floor: in
            {"mu": 0.0749999999, "sigma": 0.1},  # 1: just under the floor: out
            {"mu": 0.0750000001, "sigma": 0.1},  # 2: just over the floor: in
            {"mu": mu_f, "sigma": 0.101},  # 3: at r (1 + tau): in
            {"mu": mu_f, "sigma": 0.1010000099},  # 4: inside the tolerance: in
            {"mu": mu_f, "sigma": 0.1010000101},  # 5: past the tolerance: out
            {"mu": mu_f, "sigma": 0.10101},  # 6: r + 0.01 would admit it: out
            {"mu": mu_f, "sigma": 0.02, "r_fraction": 0.10},  # 7: far below, another setting: in
            {"mu": 0.2, "sigma": 0.09, "r_fraction": 0.85},  # 8: another setting: in
        ]
    )
    assert G.region_positions(mixes, mu_f, r).tolist() == [0, 2, 3, 4, 7, 8]


def test_below_the_risk_line_means_below_the_wide_band():
    sigma = np.array([0.0989999, 0.099, 0.0995, 0.1, 0.101])
    assert G.below_line(sigma, 0.1).tolist() == [True, False, False, False, False]


def test_distinct_mixes_count_identical_weights_once_in_risk_then_record_order():
    w = np.array([0.4, 0.6])
    pool = pd.DataFrame(
        [
            {"record": 9, "r_fraction": 0.40, "in_wide": True, "weights": w + 0.0, "mu": 0.3},
            {"record": 5, "r_fraction": 0.25, "in_wide": False, "weights": w + 0.0, "mu": 0.2},
            {"record": 2, "r_fraction": 0.25, "in_wide": True, "weights": w + 4e-10, "mu": 0.1},
            {"record": 7, "r_fraction": 0.25, "in_wide": True, "weights": np.array([1.0, 0.0]),
             "mu": 0.4},
            {"record": 1, "r_fraction": 0.85, "in_wide": True, "weights": np.array([-1e-12,
             1.0]), "mu": 0.5},
            {"record": 3, "r_fraction": 0.10, "in_wide": True, "weights": np.array([0.0, 1.0]),
             "mu": 0.6},
        ]
    )  # fmt: skip
    for name in ("sigma", "tdd", "enb", "h"):
        pool[name] = 0.1
    out = G.distinct_mixes(pool)
    # (0.10, 3) [0, 1]; (0.25, 2) [0.4, 0.6]; (0.25, 7) [1, 0]; the rest are duplicates
    assert out["record"].tolist() == [3, 2, 7]
    assert out["mu"].tolist() == [0.6, 0.1, 0.4]
    bit = {rf: 1 << j for j, rf in enumerate(A.RFS)}
    assert out["line_mask"].tolist() == [bit[0.10] | bit[0.85], bit[0.25] | bit[0.40], bit[0.25]]


def test_read_month_pool_keeps_the_main_rows_of_every_band(tmp_path):
    buf = PoolBuffer()
    rows = [
        ("3y", None, 1.0),  # main, on the line
        ("3y", None, 0.0),  # main, off the line: kept
        ("3y", C.LAMBDA, 1.0),  # arm 4 at the main penalty weight: kept
        ("3y", 0.05, 1.0),  # side check: dropped
        ("5y", None, 1.0),  # 5-year sensitivity: dropped
    ]
    for lookback, lam, wide in rows:
        buf.add(lookback=lookback, r_fraction=0.25, r=0.1, lam=lam, arm="U1", start=0, call=0,
                source="search", weights=np.array([0.5, 0.5]),
                values=_values(in_wide=wide, sigma=0.1, mu=0.05))  # fmt: skip
    table = buf.table(menu=MENU, month="2010-01", origin=origin_of("2010-01").date(),
                      engine=ENGINE, seed=C.PRIMARY_SEED)  # fmt: skip
    path = tmp_path / "pool.parquet"
    write_pool(path, table, {})
    pool = G.read_month_pool(path)
    assert sorted(pool["record"].tolist()) == [0, 1, 2]
    assert np.vstack(pool["weights"].to_list()).shape == (3, 2)


def test_in_domain_at_and_just_past_the_bounds():
    lower, upper = (0.0, 0.0), (0.4, 1.0)
    w = np.array(
        [
            [0.4, 0.6],  # exactly at fund 0's upper bound: allowed
            [0.4 + 5e-9, 0.6 - 5e-9],  # inside the 1e-8 tolerance: allowed
            [0.4 + 2e-8, 0.6 - 2e-8],  # just past it: out
            [-5e-9, 1.0 + 5e-9],  # inside the tolerance at both bounds: allowed
            [-2e-8, 1.0 + 2e-8],  # just past the lower bound: out
            [0.2, 0.8 + 5e-9],  # the budget inside the tolerance: allowed
            [0.2, 0.8 + 2e-8],  # the budget just past it: out
        ]
    )
    assert G.in_domain(w, lower, upper).tolist() == [True, True, False, True, False, True, False]


def test_in_domain_is_the_geometry_check():
    from portfoliosight.research.fixedrisk.anchors import geometry

    from .optimizer_data import synthetic_context

    geo = geometry(synthetic_context(funds=5, rows=300, cap=0.3, seed=7))
    rng = np.random.default_rng(4)
    w = rng.dirichlet(np.ones(5), size=400)
    w[:200] = np.clip(w[:200], 0.0, 0.3)  # many at the cap, the budget off for some
    w[200:300] += rng.choice([-3e-8, -5e-9, 0.0, 5e-9, 3e-8], size=(100, 5))
    got = G.in_domain(w, geo.lo, geo.hi)
    assert got.tolist() == [geo.in_domain(row) for row in w]
    assert 0 < int(got.sum()) < len(w)


# ----------------------------------------------------------------------------- left tip


@pytest.mark.parametrize(
    ("mu_f", "mu_lower", "t"),
    [
        (0.08, 0.07, 0.5),  # 50 bp of a 100 bp step
        (0.08, 0.06, 0.25),
        (0.08, 0.078, 1.0),  # the step is under 50 bp: clipped to the lower selection
        (0.08, 0.08, 1.0),  # no return step
        (0.08, 0.09, 1.0),  # the lower setting has the higher model return
    ],
)
def test_left_tip_blend_weight(mu_f, mu_lower, t):
    assert G.left_tip_t(mu_f, mu_lower) == pytest.approx(t, abs=1e-12)


def test_left_tip_blends_the_weights():
    w = G.left_tip(np.array([0.8, 0.2]), np.array([0.4, 0.6]), 0.25)
    assert w == pytest.approx([0.7, 0.3], abs=1e-15)


# -------------------------------------------------------------------------- rank blends


def test_the_fifteen_rules_and_the_named_ones():
    rules = G.rules()
    assert rules.shape == (15, 3)
    assert np.allclose(rules.sum(axis=1), 1.0)
    named = {G.rule_id(w): G.RULE_NAMES.get(tuple(w)) for w in rules}
    assert sorted(n for n in named.values() if n) == sorted(
        ["fair_drawdown", "enb", "owners_blend", "history"]
    )


# m0..m3 in tie order. Ranks, 1 the best:
#   tdd (lower better): m1 1, m2 2, m0 3, m3 4
#   enb (higher better): m2 1, m1 2, m0 3, m3 4
#   h   (lower better): m0 1, m2 2, m1 3, m3 4
FOUR = {
    "tdd": np.array([0.30, 0.10, 0.20, 0.40]),
    "enb": np.array([1.0, 1.5, 2.0, 0.5]),
    "h": np.array([0.10, 0.30, 0.20, 0.40]),
    "mu": np.array([0.080, 0.070, 0.075, 0.090]),
}


@pytest.mark.parametrize(
    ("weights", "pick"),
    [
        ((1.0, 0.0, 0.0), 1),
        ((0.0, 1.0, 0.0), 2),
        ((0.0, 0.0, 1.0), 0),
        ((0.5, 0.5, 0.0), 2),  # m1 and m2 both score 1.5: the higher mu (m2) wins
        ((0.25, 0.25, 0.5), 2),  # m0 2.0, m1 2.25, m2 1.75, m3 4.0
        ((0.5, 0.0, 0.5), 0),  # m0 2.0, m1 2.0, m2 2.0, m3 4.0: the highest mu of the tied, m0
    ],
)
def test_rule_picks_by_hand(weights, pick):
    got = G.rule_picks(FOUR["tdd"], FOUR["enb"], FOUR["h"], FOUR["mu"], np.array([weights]))
    assert got.tolist() == [pick]


def test_rule_picks_tie_on_score_and_mu_goes_to_the_first_row():
    tdd, enb, h = np.array([0.2, 0.1, 0.1]), np.array([1.0, 1.0, 1.0]), np.zeros(3)
    mu = np.array([0.09, 0.05, 0.05])
    # rows 1 and 2 share tdd (average rank 1.5) and mu: the first of them
    assert G.rule_picks(tdd, enb, h, mu, np.array([[1.0, 0.0, 0.0]])).tolist() == [1]


def test_rule_picks_of_every_rule_at_once_match_one_at_a_time():
    rules = G.rules()
    together = G.rule_picks(FOUR["tdd"], FOUR["enb"], FOUR["h"], FOUR["mu"], rules)
    alone = [G.rule_picks(FOUR["tdd"], FOUR["enb"], FOUR["h"], FOUR["mu"], w[None, :])[0]
             for w in rules]  # fmt: skip
    assert together.tolist() == alone


# ----------------------------------------------------------------------------- ceilings


def test_mix_ceiling_is_the_first_smallest_realized_drawdown():
    assert G.mix_ceiling(np.array([0.2, np.nan, 0.1, 0.1])) == 2
    assert G.mix_ceiling(np.array([np.nan, np.nan])) is None


def test_cell_spearman_needs_twenty_mixes():
    x = np.arange(20.0)
    assert G.cell_spearman(x, 2.0 * x + 1.0) == pytest.approx(1.0)
    assert G.cell_spearman(x, -x) == pytest.approx(-1.0)
    assert np.isnan(G.cell_spearman(x[:19], x[:19]))
    y = x.copy()
    y[3] = np.nan  # 19 finite pairs
    assert np.isnan(G.cell_spearman(x, y))


# ------------------------------------------------------------------- assembled statistics

K = 40
MONTHS = month_labels(K)


def _constant_picks(improve: dict[str, tuple[float, float]], mix_improve: float) -> pd.DataFrame:
    """F and L at dd 0.20, ret 0.05 (no L at the lowest setting); each named pick improves on
    both by a constant (drawdown, return) difference in every cell; the mix ceiling by
    `mix_improve` in drawdown."""
    rows = []
    for month in MONTHS:
        for rf in A.RFS:
            rows.append({"month": month, "rf": rf, "name": G.F, "dd": 0.20, "ret": 0.05})
            if rf != A.RFS[0]:
                rows.append({"month": month, "rf": rf, "name": G.L, "dd": 0.20, "ret": 0.05})
            rows.append({"month": month, "rf": rf, "name": G.MIX_CEILING,
                         "dd": 0.20 - mix_improve, "ret": 0.05, "sigma": 0.09, "mu": 0.07,
                         "enb": 2.0, "below": True})  # fmt: skip
            for name, (d_dd, d_ret) in improve.items():
                rows.append({"month": month, "rf": rf, "name": name, "dd": 0.20 - d_dd,
                             "ret": 0.05 + d_ret, "sigma": 0.1, "mu": 0.08, "enb": 1.0,
                             "below": rf == A.RFS[0]})  # fmt: skip
    return pd.DataFrame(rows)


def _cells(rho_dd: float = np.nan, rho_ret: float = np.nan) -> pd.DataFrame:
    return pd.DataFrame(
        [{"month": m, "rf": rf, "t": 0.5, "region": 3, "line": 20, "rho_dd": rho_dd,
          "rho_ret": rho_ret} for m in MONTHS for rf in A.RFS]
    )  # fmt: skip


RULE = {name: G.rule_id(w) for w, name in ((np.array(k), v) for k, v in G.RULE_NAMES.items())}


def _assemble(improve, mix_improve, **cells):
    return G.assemble(_constant_picks(improve, mix_improve), _cells(**cells), MONTHS,
                      resamples=50)  # fmt: skip


def test_rule_ceiling_is_the_rule_with_the_largest_mean_improvement_over_l():
    out = _assemble({RULE["fair_drawdown"]: (0.02, 0.0), RULE["enb"]: (0.03, -0.001)}, 0.05)
    assert out["rule_ceiling"]["rule"] == RULE["enb"]
    ceiling = out["picks"][G.RULE_CEILING]
    assert ceiling["vs_L"]["theta_dd"] == pytest.approx(0.03, abs=1e-12)
    assert ceiling["vs_L"]["paired_cells"] == 5 * K
    assert ceiling["vs_F"]["paired_cells"] == 6 * K
    assert ceiling["vs_L"]["theta_ret_lower_95"] == pytest.approx(-0.001, abs=1e-12)
    assert ceiling["model"]["below_line_share"] == pytest.approx(1 / 6, abs=1e-12)
    fair = out["picks"][RULE["fair_drawdown"]]
    assert fair["vs_L"]["theta_dd"] == pytest.approx(0.02, abs=1e-12)
    assert fair["vs_L"]["theta_dd_interval"] == pytest.approx([0.02, 0.02], abs=1e-12)
    mix = out["picks"][G.MIX_CEILING]
    assert mix["vs_L"]["theta_dd"] == pytest.approx(0.05, abs=1e-12)
    assert mix["model"]["sigma"] == pytest.approx(0.09) and mix["model"]["enb"] == 2.0
    assert mix["model"]["below_line_share"] == 1.0


def test_decision_rule_1_closes_when_the_mix_ceiling_is_under_1_pp():
    out = _assemble({RULE["fair_drawdown"]: (0.02, 0.0)}, 0.005)
    assert out["decision"] == {"rule": "1", "label": G.CLOSED_MIX}


def test_decision_rule_2_closes_when_the_rule_ceiling_is_under_1_pp():
    out = _assemble({RULE["fair_drawdown"]: (0.008, 0.0), RULE["history"]: (0.002, 0.0)}, 0.05)
    assert out["rule_ceiling"]["rule"] == RULE["fair_drawdown"]
    assert out["decision"] == {"rule": "2", "label": G.CLOSED_RULES}


def test_decision_rule_3_makes_a_candidate():
    out = _assemble({RULE["owners_blend"]: (0.02, -0.001)}, 0.05)
    assert out["decision"] == {"rule": "3", "label": G.CANDIDATE}


def test_decision_correction_3_closes_on_the_return_condition():
    out = _assemble({RULE["owners_blend"]: (0.02, -0.006)}, 0.05)
    assert out["decision"] == {"rule": "correction 3", "label": G.CLOSED_RETURN}


@pytest.mark.parametrize(
    ("args", "rule"),
    [
        ((0.009, 0.05, (0.04, 0.06), 0.0), "1"),
        ((0.05, 0.02, (0.0, 0.04), 0.0), "2"),  # the interval reaches 0
        ((0.05, 0.02, (-0.01, 0.04), 0.0), "2"),  # the interval includes 0
        ((0.05, 0.0099, (0.005, 0.02), 0.0), "2"),
        ((0.05, 0.01, (0.001, 0.02), -0.005), "3"),  # at the lines
        ((0.05, 0.01, (0.001, 0.02), -0.0051), "correction 3"),
    ],
)
def test_decide_at_the_lines(args, rule):
    assert G.decide(*args)["rule"] == rule


def test_decide_without_paired_cells_is_undetermined():
    assert G.decide(None, None, (None, None), None) == {"rule": None, "label": G.UNDETERMINED}


def test_predictiveness_mean_share_and_interval():
    out = _assemble({RULE["fair_drawdown"]: (0.02, 0.0)}, 0.05, rho_dd=0.25, rho_ret=-0.5)
    p = out["predictiveness"]
    assert p["tdd_vs_dd"]["mean"] == pytest.approx(0.25)
    assert p["tdd_vs_dd"]["positive_share"] == 1.0
    assert p["tdd_vs_dd"]["interval"] == pytest.approx([0.25, 0.25])
    assert p["tdd_vs_dd"]["cells"] == 6 * K
    assert p["mu_vs_ret"]["mean"] == pytest.approx(-0.5)
    assert p["mu_vs_ret"]["positive_share"] == 0.0


def test_predictiveness_weights_every_valid_cell_equally():
    # one start month with six cells at +1, another with one valid cell at -1: 5/7, not 0
    cells = _cells()
    cells.loc[cells["month"] == MONTHS[0], "rho_dd"] = 1.0
    cells.loc[(cells["month"] == MONTHS[1]) & (cells["rf"] == A.RFS[2]), "rho_dd"] = -1.0
    out = G.assemble(_constant_picks({RULE["fair_drawdown"]: (0.02, 0.0)}, 0.05), cells,
                     MONTHS, resamples=50)  # fmt: skip
    p = out["predictiveness"]["tdd_vs_dd"]
    assert p["mean"] == pytest.approx(5 / 7, abs=1e-15)
    assert p["cells"] == 7 and p["positive_share"] == pytest.approx(6 / 7)
    # the interval: the same cell-weighted mean over each resample's start months
    boot = evidence.Bootstrap(K, blocks=(evidence.BLOCK,), resamples=50,
                              seed=evidence.BOOTSTRAP_SEED)  # fmt: skip
    total, count = np.zeros(K), np.zeros(K)
    total[0], count[0], total[1], count[1] = 6.0, 6.0, -1.0, 1.0
    index = boot.indices[evidence.BLOCK]
    with np.errstate(invalid="ignore", divide="ignore"):
        draws = total[index].sum(axis=1) / count[index].sum(axis=1)
    want = np.percentile(draws[np.isfinite(draws)], [2.5, 97.5])
    assert p["interval"] == pytest.approx(want.tolist(), abs=1e-15)


# ------------------------------------------------------------------- end to end, one job

# Per risk setting j (r_j = 0.05 + 0.02 j): the frontier mix F_j = [a_j, 1 - a_j] with
# a_j = 0.3 + 0.1 j and mu 0.04 + 0.01 j on the line, and S_j = [a_j - 0.03, ...] 40 bp lower in
# mu at 0.9 r_j (below the line) with the lower TDD and H and the higher ENB. Every other
# setting's rows miss the cell's floor (lower settings) or ceiling (higher settings), so each
# region is {F_j, S_j}. Fund 0 crashes, so less of it is the smaller realized drawdown: S_j is
# the fair drawdown, ENB and history pick and the mix ceiling, F_j the same-line pick. The left
# tip is t = 0.005 / 0.01 = 0.5 of the way to F_{j-1}: [a_j - 0.05, ...].


def _r(j: int) -> float:
    return 0.05 + 0.02 * j


def _a(j: int) -> float:
    return 0.3 + 0.1 * j


def _mu(j: int) -> float:
    return 0.04 + 0.01 * j


def _pool(outside: bool = False) -> PoolBuffer:
    buf = PoolBuffer()
    for j, rf in enumerate(C.RISK_FRACTIONS):
        common = {"lookback": "3y", "r_fraction": rf, "r": _r(j), "start": -1, "call": -1}
        f = np.array([_a(j), 1.0 - _a(j)])
        s = np.array([_a(j) - 0.03, 1.03 - _a(j)])
        buf.add(
            **common,
            lam=None,
            arm=C.FRONTIER,
            source="anchor",
            weights=f,
            values=_values(sigma=_r(j), mu=_mu(j), in_wide=1.0, tdd=0.3, enb=1.0, h=0.3),
        )
        buf.add(
            **common,
            lam=None,
            arm=C.MIN_TDD,
            source="search",
            weights=s,
            values=_values(
                sigma=0.9 * _r(j), mu=_mu(j) - 0.004, in_wide=0.0, tdd=0.2, enb=1.2, h=0.25
            ),
        )
        # S_j again, later: counted once, so its recorded mu of 99 never enters
        buf.add(
            **common,
            lam=None,
            arm=C.U1_ARM,
            source="search",
            weights=s + 0.0,
            values=_values(sigma=0.9 * _r(j), mu=99.0, in_wide=0.0, tdd=0.2, enb=1.2, h=0.25),
        )
        # side checks that would win every rule if they were read
        for lookback, lam in (("3y", 0.05), ("5y", None)):
            buf.add(**{**common, "lookback": lookback}, lam=lam, arm=C.CRASH_PENALTY,
                    source="search", weights=np.array([0.0, 1.0]),
                    values=_values(sigma=_r(j), mu=_mu(j), in_wide=1.0, tdd=0.01, enb=9.0,
                                   h=0.01))  # fmt: skip
        if outside:
            # 2e-8 past fund 0's bound: it would win every rule and the same-line pick
            buf.add(**common, lam=None, arm=C.U1_ARM, source="search",
                    weights=np.array([1.0 + 2e-8, -2e-8]),
                    values=_values(sigma=_r(j), mu=_mu(j), in_wide=1.0, tdd=0.01, enb=9.0,
                                   h=0.01))  # fmt: skip
        if outside and j == 5:
            # exactly at fund 0's bound (the only such two-fund mix, so recorded once), below
            # the top setting's line and above every other setting's ceiling, worst on every
            # measure: kept, so the top cell's region has three mixes
            buf.add(**common, lam=None, arm=C.U1_ARM, source="search",
                    weights=np.array([1.0, 0.0]),
                    values=_values(sigma=0.95 * _r(j), mu=_mu(j), in_wide=0.0, tdd=0.9, enb=0.1,
                                   h=0.9))  # fmt: skip
    return buf


def _write(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pandas(frame, preserve_index=False)
    pq.write_table(table.replace_schema_metadata({DIGEST_KEY: DIGEST.encode()}), path)


def _selections(month: str) -> pd.DataFrame:
    return pd.DataFrame(
        [{"sel_id": f"{month}|{rf}", "kind": "main", "menu": MENU, "month": month,
          "origin": origin_of(month).date(), "engine": ENGINE, "lookback": "3y", "lam": None,
          "r_fraction": rf, "r": _r(j), "arm": C.FRONTIER, "pooled": False,
          "weights": [_a(j), 1.0 - _a(j)], "status": C.OK, "sigma": _r(j), "mu": _mu(j),
          "enb": 1.0} for j, rf in enumerate(C.RISK_FRACTIONS)]
    )  # fmt: skip


def _job(tmp_path: Path, months: list[str], outside: bool = False) -> Path:
    job = tmp_path / "run" / "research2003_replay"
    tasks = job / "tasks"
    for month in months:
        base = f"{MENU}_{month}_{ENGINE}"
        _write(tasks / f"{base}.parquet", _selections(month))
        _write(tasks / "columns" / f"{base}.parquet", pd.DataFrame({"month": [month]}))
        _write(tasks / "evaluated" / f"{base}.parquet", pd.DataFrame({"sel_id": ["x"]}))
        table = _pool(outside).table(menu=MENU, month=month, origin=origin_of(month).date(),
                              engine=ENGINE, seed=C.PRIMARY_SEED)  # fmt: skip
        write_pool(tasks / "pool" / f"{base}.parquet", table, {DIGEST_KEY: DIGEST.encode()})
    return job


def _returns() -> np.ndarray:
    """Fund 0 rises, crashes 26% in 30 days and recovers; fund 1 creeps up."""
    r0 = np.r_[np.full(100, 0.002), np.full(30, -0.01), np.full(122, 0.001)]
    return np.column_stack([r0, np.full(252, 0.0001)])


def _days(month: str) -> list:
    return list(pd.bdate_range(origin_of(month) + pd.Timedelta(days=1), periods=252))


def _horizon(complete: set[str]):
    def horizon(menu, month):
        if month not in complete:
            return None
        return _days(month), _returns(), ("F0", "F1")

    return horizon


def _parent(months, eligible):
    return {"digest": DIGEST, "menus": {MENU: {"schedule": months, "cscv": {"months": eligible}}}}


def _direct(a: float, month: str) -> tuple[float, float]:
    out = R.monthly_rebalanced(_returns(), _days(month), [[a, 1.0 - a]])
    return float(out.annual[0]), float(out.drawdown[0])


def _recorded_job(tmp_path, months, outside=False):
    job = _job(tmp_path, months, outside)
    analysis = tmp_path / "run" / "analysis" / "analysis.json"
    analysis.parent.mkdir(parents=True)
    analysis.write_text("{}")
    E.record_analysis(job, analysis)
    return job


def test_the_region_check_reads_no_outcome_before_the_analysis_digest_is_recorded(tmp_path):
    months = month_labels(2)
    job = _job(tmp_path, months)

    def horizon(menu, month):
        raise AssertionError("a realized outcome was read before the digest was recorded")

    with pytest.raises(ValueError, match="no analysis digest recorded"):
        G.region_job(job, _parent(months, months), MENU, ENGINE, horizon, bounds=BOUNDS)


def test_month_cells_on_a_known_pool(tmp_path):
    month = "2010-03"
    job = _job(tmp_path, [month])
    pool = G.read_month_pool(job / "tasks" / "pool" / f"{MENU}_{month}_{ENGINE}.parquet")
    frontier = A.locked_rows(_selections(month))
    picks, cells = G.month_cells(pool, frontier, menu=MENU, month=month,
                                 horizon=_horizon({month}))  # fmt: skip
    assert cells["region"].tolist() == [2] * 6
    assert cells["t"].iloc[0] != cells["t"].iloc[0]  # NaN: the lowest setting has no left tip
    assert cells["t"].iloc[1:].to_numpy() == pytest.approx([0.5] * 5)
    by = picks.set_index(["rf", "name"])
    for j, rf in enumerate(A.RFS):
        ret_f, dd_f = _direct(_a(j), month)
        ret_s, dd_s = _direct(_a(j) - 0.03, month)
        assert by.loc[(rf, G.F), "dd"] == pytest.approx(dd_f, abs=1e-12)
        assert by.loc[(rf, G.F), "ret"] == pytest.approx(ret_f, abs=1e-12)
        for name in (G.RULE_NAMES_ID["fair_drawdown"], G.RULE_NAMES_ID["enb"],
                     G.RULE_NAMES_ID["history"], G.MIX_CEILING):  # fmt: skip
            assert by.loc[(rf, name), "dd"] == pytest.approx(dd_s, abs=1e-12)
            assert by.loc[(rf, name), "record"] == 5 * j + 1  # S_j's first row, not its copy
            assert by.loc[(rf, name), "mu"] == pytest.approx(_mu(j) - 0.004)
            assert bool(by.loc[(rf, name), "below"])
        assert by.loc[(rf, G.SAME_LINE), "record"] == 5 * j
        assert not bool(by.loc[(rf, G.SAME_LINE), "below"])
        if j == 0:
            assert (rf, G.L) not in by.index
            continue
        ret_l, dd_l = _direct(_a(j) - 0.05, month)
        assert by.loc[(rf, G.L), "dd"] == pytest.approx(dd_l, abs=1e-12)
        assert by.loc[(rf, G.L), "ret"] == pytest.approx(ret_l, abs=1e-12)


def test_month_cells_realized_outcomes_equal_the_analysis_path(tmp_path):
    month = "2010-05"
    job = _job(tmp_path, [month])
    pool = G.read_month_pool(job / "tasks" / "pool" / f"{MENU}_{month}_{ENGINE}.parquet")
    sel = _selections(month)
    picks, _ = G.month_cells(pool, A.locked_rows(sel), menu=MENU, month=month,
                             horizon=_horizon({month}))  # fmt: skip
    analysed = A.realized_outcomes(sel, _horizon({month})).set_index("r_fraction")
    by = picks.set_index(["rf", "name"])
    for rf in A.RFS:
        assert by.loc[(rf, G.F), "dd"] == pytest.approx(analysed.loc[rf, "dd_m"], abs=1e-14)
        assert by.loc[(rf, G.F), "ret"] == pytest.approx(analysed.loc[rf, "ret_m"], abs=1e-14)


def test_region_job_end_to_end_against_direct_computations(tmp_path):
    months = month_labels(4)
    eligible = months[:3]
    job = _recorded_job(tmp_path, months)
    out = G.region_job(job, _parent(months, eligible), MENU, ENGINE, _horizon(set(eligible)),
                       bounds=BOUNDS, resamples=50)  # fmt: skip
    assert out["label"] == G.EXPLORATORY
    assert out["months"] == eligible and out["cells"] == 18
    assert out["region_scope"] == G.REGION_SCOPE
    dd = {
        key: np.array([[_direct(a, m)[1] for a in (_a(j) - d for j in range(6))] for m in eligible])
        for key, d in (("F", 0.0), ("S", 0.03))
    }
    dd["L"] = np.array([[_direct(_a(j) - 0.05, m)[1] if j else np.nan for j in range(6)]
                        for m in eligible])  # fmt: skip
    fair = out["picks"][G.RULE_NAMES_ID["fair_drawdown"]]
    assert fair["vs_L"]["paired_cells"] == 15 and fair["vs_F"]["paired_cells"] == 18
    # equal weight over the levels within a start month, then over the start months
    want_l = np.nanmean(np.nanmean(dd["L"] - dd["S"], axis=1))
    want_f = np.mean(np.mean(dd["F"] - dd["S"], axis=1))
    assert fair["vs_L"]["theta_dd"] == pytest.approx(want_l, abs=1e-12)
    assert fair["vs_F"]["theta_dd"] == pytest.approx(want_f, abs=1e-12)
    assert fair["model"]["below_line_share"] == 1.0
    assert fair["model"]["sigma"] == pytest.approx(np.mean([0.9 * _r(j) for j in range(6)]))
    same = out["picks"][G.SAME_LINE]
    assert same["vs_F"]["theta_dd"] == pytest.approx(0.0, abs=1e-15)
    assert same["model"]["below_line_share"] == 0.0
    assert out["picks"][G.MIX_CEILING]["vs_L"]["theta_dd"] == pytest.approx(want_l, abs=1e-12)
    assert out["predictiveness"]["tdd_vs_dd"]["cells"] == 0  # one same-line mix per cell


def test_region_job_is_deterministic(tmp_path):
    months = month_labels(3)
    job = _recorded_job(tmp_path, months)
    parent = _parent(months, months)
    first = G.region_job(
        job, parent, MENU, ENGINE, _horizon(set(months)), bounds=BOUNDS, resamples=50
    )
    second = G.region_job(
        job, parent, MENU, ENGINE, _horizon(set(months)), bounds=BOUNDS, resamples=50
    )
    assert json.dumps(first, default=str) == json.dumps(second, default=str)


def test_region_job_restricted_to_some_months(tmp_path):
    months = month_labels(4)
    job = _recorded_job(tmp_path, months)
    out = G.region_job(job, _parent(months, months), MENU, ENGINE, _horizon(set(months)),
                       bounds=BOUNDS, months=[months[1]], resamples=50)  # fmt: skip
    assert out["months"] == [months[1]] and out["cells"] == 6
    assert out["months_restricted"] is True


def test_record_region_adds_its_digest_after_the_analysis(tmp_path):
    months = month_labels(1)
    job = _recorded_job(tmp_path, months)
    path = tmp_path / "region_check.json"
    path.write_text("{}")
    G.record_region(job, path)
    record = json.loads((job / E.RECORD_FILE).read_text())
    assert set(record) == {"analysis", "region"}
    assert record["region"]["sha256"] == E.sha256_file(path)
    assert E.verified_entry(job, "region") == path.resolve()


def test_region_job_leaves_out_mixes_outside_the_bounds(tmp_path):
    months = month_labels(3)
    job = _recorded_job(tmp_path, months, outside=True)
    out = G.region_job(job, _parent(months, months), MENU, ENGINE, _horizon(set(months)),
                       bounds=BOUNDS, resamples=50)  # fmt: skip
    assert out["domain_removed_rows"] == 6 * 3  # one row per risk setting and month
    # F and S everywhere, plus the edge mix in the top setting's cells
    assert out["region_size"] == {"median": 2.0, "min": 2, "max": 3}
    dd_l = np.array([[_direct(_a(j) - 0.05, m)[1] for j in range(1, 6)] for m in months])
    dd_s = np.array([[_direct(_a(j) - 0.03, m)[1] for j in range(1, 6)] for m in months])
    fair = out["picks"][G.RULE_NAMES_ID["fair_drawdown"]]
    assert fair["vs_L"]["theta_dd"] == pytest.approx(np.mean(dd_l - dd_s), abs=1e-12)
    assert out["picks"][G.SAME_LINE]["vs_F"]["theta_dd"] == pytest.approx(0.0, abs=1e-15)
