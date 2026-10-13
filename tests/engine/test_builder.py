"""The tensor builder: contract, determinism, and that every computed mix is real."""

from __future__ import annotations

import copy
import hashlib
import json
import math
import re

import jsonschema
import numpy as np
import pandas as pd
import pytest

from portfoliosight.engine import ENGINE_VERSION, builder
from portfoliosight.engine.caps import CapsError
from portfoliosight.engine.stats import ew_weights
from portfoliosight.engine.surface import interpolate
from portfoliosight.engine.tensor import (
    InvariantError,
    WindowUnavailable,
    build_tensor,
    canonical_json,
    check_weights,
    load_schema,
    universe_hash,
    validate_tensor,
)
from portfoliosight.engine.torsion import TorsionError
from tests.engine.helpers import (
    CONVERTED,
    CONVERTED_REASON,
    converted_menu_inputs,
    fixture_inputs,
)

TOL = 1e-6
NX, NY = 48, 32
TELEMETRY = ("built_at", "build_seconds")
GFC_NULLS = ["SCHF", "SCHO", "VTIP", "VWOB", "LTPZ", "DBJP"]
SMALL = {"nx": 6, "ny": 5}


class Arrays:
    """Numpy views of a tensor's fields."""

    def __init__(self, t: dict):
        self.ids = [fund["id"] for fund in t["universe"]["funds"]]
        self.n = len(self.ids)
        self.cov = np.array(t["cov"])
        self.mu = np.array(t["mu_s"])
        self.lo, self.hi = np.array(t["bounds"]["min"]), np.array(t["bounds"]["max"])
        self.x, self.yf = np.array(t["frontier"]["x"]), np.array(t["frontier"]["y"])
        self.wf = np.array(t["frontier"]["w"])
        self.gy, self.gw, self.gz = np.array(t["grid"]["y"]), t["grid"]["w"], t["grid"]["z"]
        self.k_div = t["grid"]["k_div"]
        self.y_div, self.w_div = np.array(t["grid"]["y_div"]), np.array(t["grid"]["w_div"])
        self.y_sug = np.array(t["grid"]["y_sug"])
        self.tor, self.inv_t = np.array(t["torsion"]), np.array(t["torsion_inv_t"])
        self.lam = np.array(t["torsion_lambda"])

    def sigma(self, w) -> float:
        return float(np.sqrt(w @ self.cov @ w))

    def enb(self, w) -> float:
        b = self.inv_t @ w
        p = self.lam * b**2 / (w @ self.cov @ w)
        assert abs(p.sum() - 1.0) <= 1e-8 and (p >= 0).all()
        p = p[p > 0]
        return float(np.exp(-(p * np.log(p)).sum()))


@pytest.fixture(scope="module")
def arrays(fixture_tensor) -> Arrays:
    return Arrays(fixture_tensor)


def _without_telemetry(tensor: dict) -> str:
    return canonical_json({k: v for k, v in tensor.items() if k not in TELEMETRY})


def test_two_builds_are_identical_apart_from_telemetry(fixture_tensor):
    again = build_tensor(fixture_inputs("5y"))
    first, second = _without_telemetry(fixture_tensor), _without_telemetry(again)
    assert len(first) > 100_000 and first.encode() == second.encode()
    assert set(TELEMETRY) <= set(fixture_tensor) and builder.TELEMETRY_FIELDS == TELEMETRY
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", fixture_tensor["built_at"])
    assert 0.5 <= fixture_tensor["build_seconds"] <= 90.0  # really solved, and within the bound
    assert again["build_seconds"] <= 90.0


def test_schema_accepts_the_build_and_is_not_permissive(fixture_tensor):
    schema = load_schema()
    jsonschema.Draft202012Validator.check_schema(schema)
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(schema["properties"]) == set(fixture_tensor)
    validate_tensor(fixture_tensor)

    def broken(change) -> dict:
        doc = copy.deepcopy(fixture_tensor)
        change(doc)
        return doc

    cases = {
        "no grid.z": lambda d: d["grid"].pop("z"),
        "no torsion_lambda": lambda d: d.pop("torsion_lambda"),
        "extra key": lambda d: d.update(extra=1),
        "extra grid key": lambda d: d["grid"].update(extra=[]),
        "null frontier weight": lambda d: d["frontier"]["w"][3].__setitem__(0, None),
        "null in cov": lambda d: d["cov"][0].__setitem__(0, None),
        "text weight": lambda d: d["grid"]["w_div"][0].__setitem__(0, "0.1"),
        "bad hash": lambda d: d["universe"].update(hash="XYZ"),
        "unknown lookback": lambda d: d["lookback"].update(id="7y"),
        "k_div below -1": lambda d: d["grid"]["k_div"].__setitem__(0, -2),
        "fractional k_div": lambda d: d["grid"]["k_div"].__setitem__(0, 1.5),
        "missing stress window": lambda d: d["stress"].pop("covid2020"),
        "fund without last_close": lambda d: d["universe"]["funds"][0].pop("last_close"),
        "unknown kind": lambda d: d["universe"]["funds"][0].update(kind="crypto"),
        "schema 1": lambda d: d.update(schema=1),
        "another rule": lambda d: d["bounds"].update(rule="max(0.3, 3/N)"),
    }
    for label, change in cases.items():
        with pytest.raises(jsonschema.ValidationError):
            validate_tensor(broken(change))
        assert label
    # null is allowed exactly where spec 7 says
    for change in (
        lambda d: d["universe"]["funds"][0].update(last_close=None),
        lambda d: d["universe"].update(preset_id=None),
        lambda d: d["stress"]["rates2022"]["r"].__setitem__(0, None),
    ):
        validate_tensor(broken(change))


def test_floats_are_written_at_full_precision(fixture_tensor):
    text = canonical_json(fixture_tensor)
    assert json.loads(text) == fixture_tensor
    assert " " not in text.replace(" ", "", 0)[:0] and "\n" not in text and "NaN" not in text
    assert text.index('"asof"') < text.index('"bounds"') < text.index('"cov"')  # sorted keys
    pool: list[float] = []

    def collect(node):
        if isinstance(node, float):
            pool.append(node)
        elif isinstance(node, list):
            for item in node:
                collect(item)
        elif isinstance(node, dict):
            for item in node.values():
                collect(item)

    collect([fixture_tensor[k] for k in ("mu_s", "cov", "frontier", "frontier_curve", "grid")])
    rng = np.random.default_rng(4101)
    long_form = 0
    for value in (pool[i] for i in rng.choice(len(pool), size=50, replace=False)):
        assert json.loads(json.dumps(value)) == value and repr(value) in text
        digits = repr(value).replace("-", "").replace(".", "").split("e")[0].lstrip("0")
        long_form += len(digits) >= 15
    assert long_form >= 35
    match = re.search(r'"mu_s":\[([^,\]]+)', text)
    assert match and match.group(1) == repr(fixture_tensor["mu_s"][0])
    with pytest.raises(ValueError):
        canonical_json({"x": float("nan")})


def test_identity_block(fixture_tensor, fixture_frame):
    t = fixture_tensor
    assert t["schema"] == 2 and t["engine_version"] == ENGINE_VERSION == "0.1.0"
    assert t["asof"] == "2026-10-12" and t["generation"] == "2026-10-12-0.1.0"
    universe = t["universe"]
    assert universe["name"] == "The 2017 guide portfolio" and universe["preset_id"] == "guide2017"
    ids = [fund["id"] for fund in universe["funds"]]
    assert ids == list(fixture_frame.columns) and len(ids) == 23  # the 23 Step 2 funds
    assert universe["excluded"] == []  # the default menu sets no fund aside
    for fund in universe["funds"]:
        assert set(fund) == {
            "id",
            "name",
            "kind",
            "source",
            "adjusted_through",
            "fetched_at",
            "last_close",
        }
        assert fund["adjusted_through"] == "2026-10-12" and fund["last_close"] > 0
    # the hash covers the requested policy of the whole menu, excluded funds included
    rows = sorted(({"id": c, "min": None, "max": None} for c in fixture_frame.columns), key=str)
    rows.sort(key=lambda row: row["id"])
    canon = json.dumps({"schema": 2, "funds": rows}, sort_keys=True, separators=(",", ":"))
    assert universe["hash"] == hashlib.sha256(canon.encode()).hexdigest()[:16]
    assert re.fullmatch(r"[0-9a-f]{16}", universe["hash"])
    assert t["notes"] == list(builder.NOTES) and len(t["notes"]) == 2
    assert "50/50 blend of the sample mean and a menu-beta heuristic" in t["notes"][0]
    assert "within one standard error" in t["notes"][1] and "heuristic" in t["notes"][1]
    assert t["rf"] == 0.04  # no SGOV or TSP G Fund series was supplied


def test_lookback_block_describes_the_sample(fixture_tensor, fixture_frame, arrays):
    lookback = fixture_tensor["lookback"]
    assert lookback["id"] == "5y" and lookback["end"] == "2026-10-12"
    assert lookback["rows"] == 1260 and lookback["t_eff"] == 1260.0
    assert lookback["ew_halflife_days"] is None
    assert lookback["start"] == fixture_frame.index[-1260].date().isoformat()
    window = fixture_frame.loc[lookback["start"] : lookback["end"], arrays.ids].dropna()
    assert len(window) == lookback["rows"]
    sample = window.to_numpy()
    assert np.abs(np.array(fixture_tensor["mu_sample"]) - 252.0 * sample.mean(axis=0)).max() < 1e-12
    sigma = np.sqrt(252.0) * sample.std(axis=0, ddof=1)
    assert np.abs(np.array(fixture_tensor["sigma"]) - sigma).max() < 1e-12
    assert np.abs(np.diag(arrays.cov) - sigma**2).max() < 1e-12
    w_eq = np.full(arrays.n, 1.0 / arrays.n)
    beta = arrays.cov @ w_eq / (w_eq @ arrays.cov @ w_eq)
    mu_hat = np.array(fixture_tensor["mu_sample"])
    pi = 0.04 + beta * max(w_eq @ mu_hat - 0.04, 0.0)
    assert np.abs(arrays.mu - (0.5 * mu_hat + 0.5 * pi)).max() < 1e-15


def test_bounds_are_the_default_rule_and_no_weight_exceeds_a_quarter(fixture_tensor, arrays):
    bounds = fixture_tensor["bounds"]
    assert bounds["rule"] == "max(0.25, 3/N)"
    assert bounds["requested"] == [{"min": None, "max": None}] * arrays.n
    assert (arrays.lo == 0.0).all() and (arrays.hi == 0.25).all()
    vectors = [*arrays.wf, *arrays.w_div]
    vectors += [np.array(w) for column in arrays.gw for w in column if w is not None]
    worst = max(float(w.max()) for w in vectors)
    assert 0.25 - 1e-3 < worst <= 0.25 + TOL


def test_torsion_fields_diagonalize_the_shipped_covariance(arrays):
    rotated = arrays.tor @ arrays.cov @ arrays.tor.T
    assert np.abs(rotated - np.diag(np.diag(rotated))).max() <= 1e-8 * np.trace(rotated)
    assert np.allclose(np.diag(rotated), arrays.lam, rtol=1e-12, atol=0) and (arrays.lam > 0).all()
    assert np.abs(arrays.inv_t @ arrays.tor.T - np.eye(arrays.n)).max() <= 1e-9


def test_every_vector_is_real(fixture_tensor, arrays):
    """S23: every mix adds to 100%, respects the limits and sits under its ceiling."""
    checked = cells = 0
    for j in range(NX):
        for w in (arrays.wf[j], arrays.w_div[j]):
            check_weights(
                w,
                lo=arrays.lo,
                hi=arrays.hi,
                cov=arrays.cov,
                ceiling=arrays.x[j],
                enb=arrays.enb(w),
            )
            checked += 1
        for k in range(NY):
            cell, z = arrays.gw[j][k], arrays.gz[j][k]
            assert (cell is None) == (z is None) == bool(arrays.gy[k] > arrays.yf[j])
            if cell is None:
                continue
            w = np.array(cell)
            assert abs(z - arrays.enb(w)) <= 1e-9 * z
            check_weights(w, lo=arrays.lo, hi=arrays.hi, cov=arrays.cov, ceiling=arrays.x[j], enb=z)
            assert arrays.mu @ w >= arrays.gy[k] - TOL
            cells += 1
            checked += 1
    assert cells >= 500 and cells != NX * NY and checked == 48 + 48 + cells
    assert len(arrays.wf) == NX and all(len(column) == NY for column in arrays.gw)
    sigma = np.array([arrays.sigma(w) for w in arrays.wf])
    assert np.abs(sigma - arrays.x)[:-1].max() <= TOL  # nodes sit on their ceilings
    assert np.abs(arrays.yf - arrays.wf @ arrays.mu).max() <= 1e-15
    assert (np.diff(arrays.yf) >= -1e-9).all()
    assert np.abs(arrays.x - np.linspace(arrays.x[0], arrays.x[-1], NX)).max() <= 1e-12


def test_post_check_failure_stops_the_build(monkeypatch):
    def refuse(w, **_):
        raise InvariantError("sum", "injected")

    monkeypatch.setattr(builder, "check_weights", refuse)
    with pytest.raises(InvariantError, match="injected"):
        build_tensor(fixture_inputs("5y", **SMALL))


def test_surface_block(fixture_tensor, arrays):
    herf = np.full((NX, NY), np.nan)
    for j in range(NX):
        for k in range(NY):
            if arrays.gw[j][k] is not None:
                herf[j, k] = float(np.dot(arrays.gw[j][k], arrays.gw[j][k]))
    for j in range(NX):
        column = herf[j][~np.isnan(herf[j])]
        assert (np.diff(column) >= -TOL).all()
    for k in range(NY):
        row = herf[:, k][~np.isnan(herf[:, k])]
        assert (np.diff(row) <= TOL).all()
    best_overall = -np.inf
    for j in range(NX):
        candidates = [(arrays.enb(arrays.wf[j]), NY, -1)]
        candidates += [(arrays.gz[j][k], k, k) for k in range(NY) if arrays.gz[j][k] is not None]
        top = max(value for value, _, _ in candidates)
        best_overall = max(best_overall, top)
        winner = max((c for c in candidates if c[0] >= top - 1e-12), key=lambda c: c[1])
        k_div = arrays.k_div[j]
        assert k_div == winner[2]
        if k_div == -1:
            assert arrays.y_div[j] == arrays.yf[j]
            assert np.array_equal(arrays.w_div[j], arrays.wf[j])
        else:
            assert arrays.y_div[j] == arrays.gy[k_div] < arrays.yf[j]
            assert np.array_equal(arrays.w_div[j], np.array(arrays.gw[j][k_div]))
        # F9: the "more diversified" end is at least as diversified as the "more return" end
        assert arrays.enb(arrays.w_div[j]) >= arrays.enb(arrays.wf[j]) - 1e-9
    assert abs(fixture_tensor["enb_ref"] - best_overall) <= 1e-12
    assert arrays.k_div[0] == -1 and sum(k >= 0 for k in arrays.k_div) >= NX - 2


def test_frontier_curve_and_s_safe(fixture_tensor, arrays):
    sigma = np.array(fixture_tensor["frontier_curve"]["sigma"])
    mu = np.array(fixture_tensor["frontier_curve"]["mu"])
    assert sigma.shape == mu.shape == (377,)
    for i in range(377):
        j = min(i // 8, NX - 2)
        lam = i / 8.0 - j
        w = (1.0 - lam) * arrays.wf[j] + lam * arrays.wf[j + 1]
        assert abs(sigma[i] - arrays.sigma(w)) <= 1e-9 * sigma[i]
        assert abs(mu[i] - arrays.mu @ w) <= 1e-9 * abs(mu[i])
    low = mu / 2.0 - 1.96 * sigma / math.sqrt(2.0)
    rightmost = int(np.flatnonzero(low == low.max())[-1])
    s_safe = fixture_tensor["frontier"]["s_safe"]
    assert s_safe == rightmost / 8.0 and 0.0 <= s_safe < NX - 1
    assert len(np.flatnonzero(low >= low.max() - 1e-12)) == 1  # no near-tie to argue about


def test_suggested_point_is_bracketed_and_is_the_recomputed_walk(
    fixture_tensor, fixture_frame, arrays
):
    lookback = fixture_tensor["lookback"]
    r = fixture_frame.loc[lookback["start"] : lookback["end"], arrays.ids].dropna().to_numpy()
    walked = collapsed = moved = 0
    for j in range(NX):
        assert arrays.y_div[j] <= arrays.y_sug[j] <= arrays.yf[j]
        k_div = arrays.k_div[j]
        if k_div == -1:
            assert arrays.y_sug[j] == arrays.yf[j]
            collapsed += 1
            continue
        expected = arrays.yf[j]
        for k in range(NY - 1, k_div - 1, -1):
            if arrays.gw[j][k] is None:
                continue
            diff = arrays.wf[j] - np.array(arrays.gw[j][k])
            give_up = float(arrays.mu @ diff)
            noise = float(np.sqrt(252.0) * (r @ diff).std(ddof=1) / np.sqrt(len(r) / 252.0))
            if give_up > noise:
                break
            expected = arrays.gy[k]
        assert arrays.y_sug[j] == expected
        walked += 1
        moved += expected < arrays.yf[j]
    assert collapsed + walked == NX and moved >= 10
    t_sug = [
        (arrays.yf[j] - arrays.y_sug[j]) / (arrays.yf[j] - arrays.y_div[j])
        for j in range(NX)
        if arrays.k_div[j] >= 0
    ]
    assert all(0.0 <= value <= 1.0 for value in t_sug) and 0.0 < max(t_sug) < 1.0


def test_stress_block_never_fabricates(fixture_tensor, fixture_frame, arrays):
    stress = fixture_tensor["stress"]
    assert list(stress) == ["gfc2008", "covid2020", "rates2022"]
    for block in stress.values():
        assert set(block) == {"label", "start", "end", "r"} and len(block["r"]) == arrays.n
    gfc = dict(zip(arrays.ids, stress["gfc2008"]["r"], strict=True))
    assert sorted(i for i, value in gfc.items() if value is None) == sorted(GFC_NULLS)
    assert sum(value is not None for value in gfc.values()) >= 15
    assert None not in stress["covid2020"]["r"] and None not in stress["rates2022"]["r"]
    for block in stress.values():  # each number compounds the fund's own returns after the start
        days = fixture_frame.index
        window = fixture_frame.loc[(days > block["start"]) & (days <= block["end"])]
        for fund, value in zip(arrays.ids, block["r"], strict=True):
            if value is not None:
                own = float(np.prod(1.0 + window[fund].to_numpy()) - 1.0)
                assert abs(value - own) <= 1e-12


def test_interpolated_mixes_keep_the_invariants(fixture_tensor, arrays):
    rng = np.random.default_rng(4102)
    for _ in range(200):
        s, t = float(rng.uniform(0, NX - 1)), float(rng.uniform())
        j = min(int(math.floor(s)), NX - 2)
        lam = s - j
        w = interpolate(fixture_tensor, s, t)
        ceiling = (1.0 - lam) * arrays.x[j] + lam * arrays.x[j + 1]
        check_weights(
            w, lo=arrays.lo, hi=arrays.hi, cov=arrays.cov, ceiling=ceiling, enb=arrays.enb(w)
        )
    for s in (1.0, 12.5, 46.5, 47.0):
        j = min(int(math.floor(s)), NX - 2)
        lam = s - j
        bottom = (1.0 - lam) * arrays.w_div[j] + lam * arrays.w_div[j + 1]
        assert np.abs(interpolate(fixture_tensor, s, 1.0) - bottom).max() <= 1e-12
    for t in (0.0, 0.3, 1.0):  # the minimum-risk column is a collapsed ladder
        assert np.array_equal(interpolate(fixture_tensor, 0.0, t), arrays.wf[0])


def test_a_fund_the_catalog_does_not_serve_is_set_aside_with_its_reason(fixture_frame):
    """A custom menu holding FIENX: listed with the catalog's reason, absent from the math."""
    inputs = converted_menu_inputs("5y", **SMALL)
    tensor = build_tensor(inputs)
    validate_tensor(tensor)
    universe = tensor["universe"]
    assert universe["name"] == "Custom menu" and universe["preset_id"] is None
    assert [fund["id"] for fund in universe["funds"]] == list(fixture_frame.columns)
    aside = [{"id": CONVERTED, "reason": CONVERTED_REASON, "last_close": None}]
    assert universe["excluded"] == aside
    assert len(inputs.funds) == 24 and len(tensor["mu_s"]) == 23
    vectors = [*tensor["frontier"]["w"], *tensor["grid"]["w_div"]]
    vectors += [w for column in tensor["grid"]["w"] for w in column if w is not None]
    assert {len(w) for w in vectors} == {23}  # no weight vector carries the fund
    assert all(len(block["r"]) == 23 for block in tensor["stress"].values())
    # the hash is the menu's, FIENX included; the numbers are the 23 funds' own
    rows = [{"id": fund.id, "min": None, "max": None} for fund in inputs.funds]
    plain = build_tensor(fixture_inputs("5y", **SMALL))
    assert universe["hash"] == universe_hash(rows) != plain["universe"]["hash"]
    for key in ("mu_s", "cov", "bounds", "frontier", "grid", "stress", "lookback"):
        assert tensor[key] == plain[key], key
    # with returns through the last day the catalog still decides: not served, not used
    current = inputs.returns.assign(**{CONVERTED: inputs.returns["EFA"]})
    served_data = build_tensor(converted_menu_inputs("5y", returns=current, **SMALL))
    assert served_data["universe"]["excluded"] == aside


def test_requested_caps_are_recorded_and_respected():
    requested = [
        {"id": "VTI", "min": None, "max": 0.10},
        {"id": "BND", "min": 0.05, "max": None},
        {"id": CONVERTED, "min": None, "max": 0.5},  # excluded in this window: hashed, not resolved
    ]
    capped = build_tensor(converted_menu_inputs("5y", requested_bounds=requested, **SMALL))
    plain = build_tensor(converted_menu_inputs("5y", **SMALL))
    a = Arrays(capped)
    vti, bnd = a.ids.index("VTI"), a.ids.index("BND")
    assert capped["bounds"]["requested"][vti] == {"min": None, "max": 0.10}
    assert capped["bounds"]["requested"][bnd] == {"min": 0.05, "max": None}
    assert sum(r != {"min": None, "max": None} for r in capped["bounds"]["requested"]) == 2
    assert a.hi[vti] == 0.10 and a.lo[bnd] == 0.05 and a.hi[bnd] == 0.25 and a.lo[vti] == 0.0
    vectors = [*a.wf, *a.w_div, *(np.array(w) for col in a.gw for w in col if w is not None)]
    assert max(w[vti] for w in vectors) <= 0.10 + TOL
    assert min(w[bnd] for w in vectors) >= 0.05 - TOL
    assert capped["universe"]["hash"] != plain["universe"]["hash"]
    rows = [{"id": f.id, "min": None, "max": None} for f in converted_menu_inputs().funds]
    assert CONVERTED in [row["id"] for row in rows] and capped["universe"]["excluded"]
    assert plain["universe"]["hash"] == universe_hash(rows) == universe_hash(rows[::-1])
    for row in rows:
        row.update(
            next(
                ({"min": r["min"], "max": r["max"]} for r in requested if r["id"] == row["id"]), {}
            )
        )
    assert capped["universe"]["hash"] == universe_hash(rows)
    assert capped["frontier"]["w"] != plain["frontier"]["w"]


@pytest.mark.parametrize(
    ("requested", "message"),
    [
        ([{"id": "ZZZ", "max": 0.5}], "ZZZ: not a fund of this menu"),
        ([{"id": "VTI", "max": 0.5}, {"id": "VTI", "max": 0.4}], "VTI: capped more than once"),
        ([{"max": 0.5}], "every cap entry needs a fund id"),
        ([{"id": "VTI", "min": 0.3}], "VTI"),  # above the default maximum of this window
        ([{"id": CONVERTED, "min": 2, "max": -1}], CONVERTED),  # excluded here, still validated
        ([{"id": CONVERTED, "min": 0.5, "max": 0.2}], "FIENX: min 0.5 is above max 0.2"),
        ([{"id": f, "max": 0.04} for f in ("VTI", "VTV", "VOE", "VB", "VBR", "VEA")], "sum"),
    ],
)
def test_bad_caps_are_refused_before_anything_is_solved(requested, message):
    if message == "sum":  # caps that leave less than 100% to hold
        requested = [{"id": f.id, "max": 0.04} for f in fixture_inputs().funds]
    with pytest.raises(CapsError, match=message):
        build_tensor(converted_menu_inputs("5y", requested_bounds=requested, **SMALL))


def test_window_without_enough_shared_history_is_unavailable(fixture_frame):
    young = fixture_frame.iloc[-300:]
    assert build_tensor(fixture_inputs("1y", returns=young, **SMALL))["lookback"]["rows"] == 252
    with pytest.raises(WindowUnavailable, match="5y window is unavailable") as caught:
        build_tensor(fixture_inputs("5y", returns=young, **SMALL))
    assert caught.value.reason == "not enough shared history"
    assert caught.value.selection.status == "unavailable"
    assert isinstance(caught.value, ValueError)


def test_ew_window_carries_its_weights_through(fixture_frame):
    tensor = build_tensor(fixture_inputs("ew", **SMALL))
    fixed = build_tensor(fixture_inputs("5y", **SMALL))
    lookback = tensor["lookback"]
    omega = ew_weights(1260)
    assert lookback["id"] == "ew" and lookback["rows"] == 1260
    assert lookback["ew_halflife_days"] == 252
    assert abs(lookback["t_eff"] - 1.0 / (omega**2).sum()) <= 1e-9 and lookback["t_eff"] < 700
    ids = [fund["id"] for fund in tensor["universe"]["funds"]]
    sample = fixture_frame.iloc[-1260:][ids].to_numpy()
    assert np.abs(np.array(tensor["mu_sample"]) - 252.0 * (omega @ sample)).max() <= 1e-12
    assert tensor["mu_sample"] != fixed["mu_sample"] and tensor["cov"] != fixed["cov"]
    a = Arrays(tensor)
    for j, k_div in enumerate(a.k_div):  # the walk uses the weighted deviation and T_eff
        expected = a.yf[j]
        for k in range(len(a.gy) - 1, k_div - 1, -1):
            if k_div < 0 or a.gw[j][k] is None:
                continue
            d = sample @ (a.wf[j] - np.array(a.gw[j][k]))
            mean = omega @ d
            deviation = np.sqrt(omega @ (d - mean) ** 2 / (1.0 - (omega**2).sum()))
            noise = np.sqrt(252.0) * deviation / np.sqrt(lookback["t_eff"] / 252.0)
            if a.mu @ (a.wf[j] - np.array(a.gw[j][k])) > noise:
                break
            expected = a.gy[k]
        assert a.y_sug[j] == expected


def test_risk_free_rate_comes_from_the_supplied_series(fixture_frame):
    rng = np.random.default_rng(4103)
    sgov = pd.Series(0.00017 + rng.normal(0, 1e-5, len(fixture_frame)), index=fixture_frame.index)
    future = pd.Series(0.01, index=pd.bdate_range("2026-10-13", periods=30))
    series = pd.concat([sgov, future])
    tensor = build_tensor(fixture_inputs("1y", rf_series={"SGOV": series}, **SMALL))
    expected = float(np.prod(1.0 + sgov.to_numpy()[-252:]) - 1.0)
    assert abs(tensor["rf"] - expected) <= 1e-15 and tensor["rf"] != 0.04
    plain = build_tensor(fixture_inputs("1y", **SMALL))
    assert plain["rf"] == 0.04 and plain["mu_s"] != tensor["mu_s"]
    assert plain["mu_sample"] == tensor["mu_sample"]


def test_stress_uses_a_supplied_total_return_index_up_to_asof(fixture_frame):
    derived = build_tensor(fixture_inputs("1y", **SMALL))
    supplied = {
        fund: (1.0 + fixture_frame[fund].dropna()).cumprod() * 37.0 for fund in ("VTI", "SCHF")
    }
    spliced = pd.concat([supplied["VTI"], pd.Series([1e9], index=[pd.Timestamp("2027-01-04")])])
    tensor = build_tensor(
        fixture_inputs("1y", tr_index={"VTI": spliced, "SCHF": supplied["SCHF"]}, **SMALL)
    )
    for window in ("gfc2008", "covid2020", "rates2022"):
        ours, theirs = tensor["stress"][window]["r"], derived["stress"][window]["r"]
        assert [v is None for v in ours] == [v is None for v in theirs]
        pairs = [(a, b) for a, b in zip(ours, theirs, strict=True) if a is not None]
        assert all(abs(a - b) <= 1e-12 for a, b in pairs)
    # a longer record than the returns frame changes the answer: the index is really used
    early = supplied["SCHF"].copy()
    early = pd.concat([pd.Series([20.0], index=[pd.Timestamp("2008-08-29")]), early])
    with_history = build_tensor(fixture_inputs("1y", tr_index={"SCHF": early}, **SMALL))
    position = [f["id"] for f in tensor["universe"]["funds"]].index("SCHF")
    assert derived["stress"]["gfc2008"]["r"][position] is None
    assert with_history["stress"]["gfc2008"]["r"][position] is not None
    # a hole in the returns hides the growth across it: no number is made up from the pieces
    holed = fixture_frame.copy()
    holed.loc["2022-06-20":"2022-06-21", "VTI"] = np.nan
    gapped = build_tensor(fixture_inputs("1y", returns=holed, **SMALL))
    assert gapped["stress"]["rates2022"]["r"][0] is None
    assert gapped["stress"]["gfc2008"]["r"][0] == derived["stress"]["gfc2008"]["r"][0]
    assert gapped["stress"]["rates2022"]["r"][1:] == derived["stress"]["rates2022"]["r"][1:]
    known = build_tensor(
        fixture_inputs("1y", returns=holed, tr_index={"VTI": supplied["VTI"]}, **SMALL)
    )
    assert (
        abs(known["stress"]["rates2022"]["r"][0] - derived["stress"]["rates2022"]["r"][0]) < 1e-12
    )
    # and the caller's sessions drive the three-session rule
    sparse = build_tensor(fixture_inputs("1y", xnys_sessions=[pd.Timestamp("2026-10-12")], **SMALL))
    assert None not in [v for v in sparse["stress"]["covid2020"]["r"]]


def test_menu_defects_are_refused_or_explained(fixture_frame):
    inputs = fixture_inputs("1y", **SMALL)
    with pytest.raises(ValueError, match="more than once"):
        build_tensor(fixture_inputs("1y", funds=[*inputs.funds, inputs.funds[0]], **SMALL))
    with pytest.raises(ValueError, match="asof must be a date"):
        build_tensor(fixture_inputs("1y", asof=None, **SMALL))
    # a fund the returns frame does not hold is excluded with "no data", not invented
    tensor = build_tensor(fixture_inputs("1y", returns=fixture_frame.drop(columns="EDV"), **SMALL))
    assert {"id": "EDV", "reason": "no data", "last_close": inputs.funds[20].last_close} in (
        tensor["universe"]["excluded"]
    )
    assert len(tensor["universe"]["funds"]) == 22 and len(tensor["mu_s"]) == 22
    # extra columns in the frame are not part of the menu
    wide = fixture_frame.assign(EXTRA=0.001)
    assert (
        build_tensor(fixture_inputs("1y", returns=wide, **SMALL))["mu_s"]
        == (build_tensor(inputs)["mu_s"])
    )
    # an unserved fund without a catalog reason is explained by its adjustment date
    funds = [
        f
        if f.id != "PCY"
        else type(f)(**{**f.__dict__, "served": False, "adjusted_through": "2026-09-30"})
        for f in inputs.funds
    ]
    stale = build_tensor(fixture_inputs("1y", funds=funds, **SMALL))
    assert {
        "id": "PCY",
        "reason": "corporate actions not yet verified after 2026-09-30",
        "last_close": inputs.funds[17].last_close,
    } in stale["universe"]["excluded"]


def test_funds_in_exact_lockstep_fail_the_build_and_identical_funds_do_not(
    fixture_frame, monkeypatch
):
    """Ledoit-Wolf shrinks nothing when every varying fund switches between two values together.

    The fixed-window correlation is then singular and the build fails with the torsion error
    before anything is factored or solved; nothing is regularized. The weighted window shrinks
    by a fixed amount and builds, and so do two funds that merely have the same returns.
    """
    ids = ["VTI", "VTV", "AGG"]
    funds = [fund for fund in fixture_inputs().funds if fund.id in ids]
    frame = fixture_frame[ids]
    swing = 0.01 * np.where(np.arange(len(frame)) % 2 == 0, 1.0, -1.0)
    lockstep = frame.assign(VTI=swing, VTV=swing, AGG=0.0001)  # 252 rows of +-1%, 1%, 0.01%
    programs = builder.MenuPrograms
    made = []
    monkeypatch.setattr(builder, "MenuPrograms", lambda *args: made.append(args) or programs(*args))
    for returns in (lockstep, lockstep.iloc[:-1]):  # the swing ending up, and ending down
        with pytest.raises(TorsionError, match="^the correlation matrix is not positive definite$"):
            build_tensor(fixture_inputs("1y", funds=funds, returns=returns, **SMALL))
    assert made == []
    weighted = build_tensor(fixture_inputs("ew", funds=funds, returns=lockstep, **SMALL))
    sigma = np.array(weighted["sigma"])
    assert np.array(weighted["cov"])[0, 1] / (sigma[0] * sigma[1]) == pytest.approx(0.8, abs=1e-12)
    twins = build_tensor(
        fixture_inputs("1y", funds=funds, returns=frame.assign(VTV=frame["VTI"]), **SMALL)
    )
    sigma = np.array(twins["sigma"])
    assert 0.9 < np.array(twins["cov"])[0, 1] / (sigma[0] * sigma[1]) < 0.99
    assert sigma[0] == sigma[1] and 1.0 <= twins["enb_ref"] <= 3.0
    assert len(made) == 2
