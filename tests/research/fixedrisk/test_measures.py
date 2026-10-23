import pandas as pd
import pytest

from portfoliosight.research.fixedrisk import contracts as C
from portfoliosight.research.fixedrisk import measures as M

from .synth import build_run, fake_realized

PUBLISHED = {"m1": [(f"2010-{i:02d}", None, None) for i in range(1, 21)]}


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    root = tmp_path_factory.mktemp("run")
    months = build_run(root, n_months=30)
    tables = M.load_run(root)
    return root, months, tables


@pytest.fixture(scope="module")
def study(run):
    _, _, tables = run
    return M.Study(tables, fake_realized(tables.selections), disjoint=PUBLISHED)


def test_load_run_classifies_tables_by_columns(run):
    _, _, t = run
    assert t.jobs == ["m1-garch", "m1-replay"]
    assert {"sel_id", "weights", "rf"} <= set(t.selections.columns)
    assert "w_MDP" in t.anchors and "test_seed" in t.evaluated
    assert t.selections["sel_id"].is_unique


def test_load_run_rejects_duplicates_and_unknown_files(tmp_path):
    build_run(tmp_path, n_months=10, engines=("replay",))
    tasks = tmp_path / "m1-replay" / "tasks"
    pd.read_parquet(tasks / "part-0.parquet").to_parquet(tasks / "part-9.parquet")
    with pytest.raises(ValueError, match="duplicated sel_id"):
        M.load_run(tmp_path)
    (tasks / "part-9.parquet").unlink()
    pd.DataFrame({"x": [1]}).to_parquet(tasks / "junk.parquet")
    with pytest.raises(ValueError, match="match none"):
        M.load_run(tmp_path)


def test_white_line_supported_when_everything_clears(study):
    wl = study.white_line("m1", "replay")
    assert wl["label"] == M.SUPPORTED, wl["reason"]
    model = wl["vs_F"]["model"]
    assert model["u1"]["mean"] >= M.GAIN and model["banks_positive"] == 5
    assert model["bad"]["mean"] > 0
    assert model["risk"]["mean"] == pytest.approx(-0.001)  # sigma_U - sigma_F by construction
    real = wl["vs_F"]["realized"]
    assert real["gain"] == pytest.approx(0.01) and real["guardrails_hold"]
    assert real["gain_interval"][0] > 0 and real["drawdown_improvement"] == pytest.approx(0.02)
    assert wl["tau"]["available"] and wl["tau"]["agree"] and wl["tau"]["origins"] == 6
    assert wl["support"] == "met" and wl["vs_BS"]["pairs"] == 180


def test_white_line_realized_support_not_attainable_below_20_intervals(run):
    _, _, t = run
    s = M.Study(t, fake_realized(t.selections))  # intervals computed from the ledger: far below 20
    wl = s.white_line("m1", "replay")
    assert wl["support"] == M.NOT_ATTAINABLE and wl["label"] == M.INCONCLUSIVE
    assert "not attainable" in wl["reason"] and wl["tail_underpowered"]


def test_white_line_guardrail_breach_is_not_supported(run):
    _, _, t = run
    s = M.Study(t, fake_realized(t.selections, white_offset=-0.05), disjoint=PUBLISHED)
    wl = s.white_line("m1", "replay")
    assert wl["vs_F"]["realized"]["guardrails_hold"] is False
    assert wl["label"] == M.NOT_SUPPORTED


def test_label_rules_directly():
    base = {
        "vs_F": {
            "model": {"u1": {"mean": 6e-4}, "banks_positive": 4},
            "realized": {
                "n": 10,
                "guardrails_hold": True,
                "gain": 0.003,
                "gain_interval": [0.001, 0.004],
                "drawdown_improvement": 0.0,
                "drawdown_interval": [-0.1, 0.1],
                "mean_loss": -0.003,
            },
        },
        "tau": {"available": True, "agree": True},
        "disjoint": 25,
    }
    assert M.Study._label(base)["label"] == M.SUPPORTED
    low = {**base, "vs_F": {**base["vs_F"], "model": {"u1": {"mean": 4e-4}, "banks_positive": 5}}}
    assert M.Study._label(low)["label"] == M.NOT_SUPPORTED  # < 5 bp
    banks = {**base, "vs_F": {**base["vs_F"], "model": {"u1": {"mean": 6e-4}, "banks_positive": 3}}}
    assert M.Study._label(banks)["label"] == M.NOT_SUPPORTED
    flip = {**base, "tau": {"available": True, "agree": False}}
    assert M.Study._label(flip)["label"] == M.INCONCLUSIVE
    missing = {**base, "tau": {"available": False}}
    assert M.Study._label(missing)["label"] == M.INCONCLUSIVE
    weak = {
        **base,
        "vs_F": {**base["vs_F"], "realized": {**base["vs_F"]["realized"], "gain": 0.001}},
    }
    assert M.Study._label(weak)["label"] == M.NOT_SUPPORTED  # < 25 bp and no drawdown route
    dd = {
        **base,
        "vs_F": {
            **base["vs_F"],
            "realized": {
                **base["vs_F"]["realized"],
                "gain": 0.001,
                "drawdown_improvement": 0.02,
                "drawdown_interval": [0.005, 0.03],
                "mean_loss": 0.001,
            },
        },
    }
    assert M.Study._label(dd)["label"] == M.SUPPORTED  # drawdown route
    short = {**base, "disjoint": 19}
    assert M.Study._label(short)["support"] == M.NOT_ATTAINABLE
    assert M.Study._label(short)["label"] == M.INCONCLUSIVE


def test_d_star_shares_and_anchor_regret(study, run):
    _, _, t = run
    ds = study.d_star("m1", "replay")
    sel = t.selections
    u = sel[
        (sel.engine == "replay")
        & (sel.kind == "main")
        & (sel.arm == "U1")
        & (sel.cell == "free")
        & sel.pooled
    ]
    for row in ds["rows"]:
        d = u[u.rf == row["rf"]]["d"].dropna()
        assert row["n"] == 30 and row["undefined"] == 30 - len(d)
        assert row["below_0"] == pytest.approx((d < 0).mean())
        assert row["above_1"] == pytest.approx((d > 1).mean())
        assert row["at_least_quarter"] == pytest.approx((d >= 0.25).mean())
        if (d > 1).any():
            assert row["regret_mean"] == pytest.approx(1.2 - 1.5)  # measure 1.2 vs M_MDP 1.5
        assert 0 <= row["pooled_beyond_native"] <= 1
    assert ds["rows"][0]["undefined"] == 1  # collapsed column: d* missing


def test_line_shape_slopes(study):
    ls = study.line_shape("m1", "replay")
    for row in ls["rows"]:
        assert row["n"] == 17
        assert row["return"]["slope"] == pytest.approx(0.1)
        assert row["bad"]["slope"] == pytest.approx(0.1)
        assert row["drawdown"]["slope"] == pytest.approx(-0.05)
        lo, hi = row["return"]["interval"]
        assert lo == pytest.approx(0.1) and hi == pytest.approx(0.1)


def test_safest_mix(study):
    sm = study.safest_mix("m1", "replay")
    assert sm["pairs"] == 180
    # max-Bad realized return = base - .005 vs U1 free = base + .01
    assert sm["return_diff"]["mean"] == pytest.approx(-0.015)
    assert sm["drawdown_diff"]["mean"] == pytest.approx(0.02)
    assert len(sm["stats"]["b"]["realized_bad"]) == 6
    assert sm["model_d_bad"] == pytest.approx(-0.003, abs=0.01)


def test_engine_agreement(study):
    ea = study.engine_agreement("m1")
    assert ea["available"] and ea["engines"] == ["garch", "replay"]
    assert ea["share_within"] == pytest.approx(0.4)  # U1 and U2 identical, the other three differ
    assert ea["by_arm"]["U1"] == 1.0 and ea["by_arm"]["B"] == 0.0
    assert ea["paired_realized"]["dr"]["mean"] == pytest.approx(0.0)


def test_engine_agreement_needs_two_engines(tmp_path):
    build_run(tmp_path, n_months=10, engines=("replay",))
    t = M.load_run(tmp_path)
    assert M.Study(t, fake_realized(t.selections, n_months=10)).engine_agreement("m1") == {
        "available": False
    }


def test_stability_rules(run):
    _, _, t = run
    s = M.Study(t, fake_realized(t.selections), disjoint=PUBLISHED)
    rows = s.stability("m1", "replay")["rows"]
    assert len(rows) == 24 and all(r["origins"] == 8 for r in rows)
    assert not any(r["pass"] for r in rows)  # random weights: L1 is far above .20
    # identical weights and identical Bad across the five banks pass v1's rules
    sel = s.sel
    nat = sel[
        (sel.kind == "main")
        & (sel.arm == "U1")
        & ~sel.pooled.astype(bool)
        & (sel.engine == "replay")
    ]
    key = ["month", "rf", "cell"]
    wmap = nat.set_index(key)["weights"]
    stab = sel["kind"] == "stability"
    new = [
        wmap[(m, r, c)]
        for m, r, c in zip(
            sel.loc[stab, "month"], sel.loc[stab, "rf"], sel.loc[stab, "cell"], strict=True
        )
    ]
    sel.loc[stab, "weights"] = pd.Series(new, index=sel.index[stab], dtype=object)
    bmap = s.evw["bad"].mean(axis=1)
    nat_bad = nat.set_index(key)["sel_id"].map(bmap)
    for i in sel.index[stab & (sel.engine == "replay")]:
        s.evw["bad"].loc[sel.at[i, "sel_id"]] = nat_bad[
            (sel.at[i, "month"], sel.at[i, "rf"], sel.at[i, "cell"])
        ]
    rows = s.stability("m1", "replay")["rows"]
    assert all(r["median_l1"] == 0 and r["pass"] for r in rows)


def test_collapsed_and_cost(study):
    col = study.collapsed("m1")
    assert col["by_r"][0]["share"] == pytest.approx(1 / 30) and col["by_r"][1]["share"] == 0
    assert col["overall"] == pytest.approx(1 / 180)
    assert col["showcase_columns"] == 8 and col["showcase_share"] == pytest.approx(2 / 8)
    c = study.cost("m1", "replay")
    n = (study.sel["engine"] == "replay").sum()
    assert c["total_hours"] == pytest.approx(n / 3600)
    assert c["showcase_seconds_per_surface"] == pytest.approx(2.0)
    assert {r["arm"] for r in c["by_arm"]} == set(C.ARM_ORDER)
    assert c["solvers"] == {"exact_grad": int(n)}


def test_labels_count_non_ok(run):
    _, _, t = run
    s = M.Study(t, fake_realized(t.selections))
    idx = s.sel.index[(s.sel.kind == "main") & (s.sel.engine == "replay") & (s.sel.cell == "d25")][
        :3
    ]
    s.sel.loc[idx, "status"] = C.NOT_FOUND
    out = s.labels("m1", "replay")
    assert sum(r["count"] for r in out) == 3 and out[0]["status"] == C.NOT_FOUND
    assert s.labels("m1", "garch") == []


def test_calibration_coverage(run):
    _, _, t = run
    s = M.Study(t, fake_realized(t.selections))
    s.sel["ret_daily"] = -1.0
    cal = s.calibration("m1", "replay")
    assert (
        cal["U1"]["training_bad"]["coverage"] == 1.0
        and cal["U1"]["independent_good"]["coverage"] == 1.0
    )
    assert cal["U1"]["training_bad"]["pinball"] > 0
    s.sel["ret_daily"] = 2.0
    assert s.calibration("m1", "replay")["B"]["training_typical"]["coverage"] == 0.0


def test_regimes_horizons_and_cost_variant(study):
    rg = {r["regime"]: r for r in study.regimes("m1", "replay")}
    assert set(rg) == {"calm", "equity drawdown"}
    assert rg["calm"]["mean_return_diff"] == pytest.approx(0.01)
    hz = {h["horizon"]: h for h in study.horizons("m1", "replay")}
    assert hz["1y"]["diff"] == pytest.approx(0.01) and "3y" in hz and "5y" not in hz
    cv = study.cost_variant("m1", "replay")
    assert cv["gross_diff"] == pytest.approx(cv["net_diff"])  # same turnover charge for both


def test_cscv_and_dsr_through_study(tmp_path):
    months = build_run(tmp_path, n_months=60, engines=("replay",))
    assert len(months) == 60
    t = M.load_run(tmp_path)
    s = M.Study(t, fake_realized(t.selections, complete_until=48, n_months=60, noise=0.004))
    c = s.cscv("m1", "replay")
    assert c["available"] and c["splits"] == 70 and c["evaluable"] == 0 and c["pbo"] is None
    assert "not computable" in c["note"] and c["counts"]["rows"] > 0
    d = s.deflated_sharpe("m1", "replay")
    assert d["available"] and d["n"] == 4 and d["trials_used"] <= 20
    assert d["dsr"] is None or 0 <= d["dsr"] <= 1
    x, names, mons = s.dsr_series("m1", "replay")
    assert x.shape == (4, 20) and names[0] == "U1/free" and len(mons) == 4
