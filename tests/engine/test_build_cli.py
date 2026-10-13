"""The tensor build CLI and the UI fixture it produces."""

from __future__ import annotations

import csv
import json
import math
import re
import subprocess
import sys

import numpy as np
import pandas as pd
import pytest

from portfoliosight.data.calendar import session_back
from portfoliosight.engine.tensor import canonical_json, validate_tensor
from tests.engine.helpers import FIXTURE, FIXTURE_ASOF, HOLDINGS, ROOT, UI_FIXTURE, load_script

TELEMETRY = ("built_at", "build_seconds")
SMALL = ["--nx", "6", "--ny", "5"]
FORBIDDEN_COPY = [
    "bets",
    "knee",
    "Sharpe",
    "tangency",
    "covariance",
    "sigma",
    "quantile",
    "significant",
    "you should",
    "we recommend",
    "Risk Number",
    "Risk Score",
]


@pytest.fixture(scope="module")
def cli():
    return load_script("build_tensor")


@pytest.fixture(scope="module")
def ui() -> dict:
    return json.loads(UI_FIXTURE.read_text(encoding="utf-8"))


def _core(tensor: dict) -> str:
    return canonical_json({k: v for k, v in tensor.items() if k not in TELEMETRY})


def _run(cli, tmp_path, *extra, returns=FIXTURE, lookback="5y", asof=FIXTURE_ASOF, name="out.json"):
    out = tmp_path / name
    args = ["--returns", str(returns), "--lookback", lookback, "--asof", asof, "--out", str(out)]
    code = cli.main([*args, *extra])
    return code, out


def _bare_parquet(tmp_path, rows: int = 400, columns=("AAA", "BBB", "CCC")) -> tuple:
    rng = np.random.default_rng(4201)
    index = pd.bdate_range(end="2026-06-30", periods=rows, name="date")
    frame = pd.DataFrame(rng.normal(0.0003, 0.01, (rows, len(columns))), index=index)
    frame.columns = list(columns)
    path = tmp_path / "bare.parquet"
    frame.to_parquet(path)
    return path, frame


def test_pinned_invocation_reproduces_the_ui_fixture(tmp_path, ui, fixture_tensor):
    out = tmp_path / "fresh.json"
    command = [sys.executable, "scripts/build_tensor.py", "--returns"]
    command += ["tests/fixtures/synthetic_23.parquet", "--lookback", "5y"]
    command += ["--asof", FIXTURE_ASOF, "--out", str(out)]
    done = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=300)
    assert done.returncode == 0, done.stderr[-2000:]
    text = out.read_text(encoding="utf-8")
    fresh = json.loads(text)
    assert set(fresh) == set(ui) and set(TELEMETRY) <= set(fresh)
    assert _core(fresh) == _core(ui), "web/fixtures/guide2017_5y.json is not the CLI's output"
    assert _core(fresh) == _core(fixture_tensor)  # the test helper builds what the CLI builds
    assert text == canonical_json(fresh) + "\n"  # the file is the canonical form
    assert ui["asof"] == FIXTURE_ASOF == str(pd.read_parquet(FIXTURE).index.max())[:10]
    assert UI_FIXTURE.read_text(encoding="utf-8") == canonical_json(ui) + "\n"
    validate_tensor(ui)


def test_ui_fixture_has_what_the_page_tests_need(ui):
    """The properties Phase 5's tests read from the fixture (plan 3.12, spec 11)."""
    ids = [fund["id"] for fund in ui["universe"]["funds"]]
    with HOLDINGS.open(newline="") as handle:
        amounts = {r["Symbol"]: float(r["Qty"]) * float(r["Price"]) for r in csv.DictReader(handle)}
    excluded = ui["universe"]["excluded"]
    assert [entry["id"] for entry in excluded] == ["FIENX"]
    assert excluded[0]["reason"] == "converted to an ETF; no data since 2024-10-30"
    assert sorted(ids + ["FIENX"]) == sorted(amounts) and len(ids) == 22 and "VTI" in ids
    assert ui["lookback"]["id"] == "5y" and ui["generation"] == "2026-10-12-0.1.0"
    assert re.fullmatch(r"[0-9a-f]{16}", ui["universe"]["hash"])
    assert ui["universe"]["name"] == "The 2017 guide portfolio"
    assert ui["bounds"]["requested"] == [{"min": None, "max": None}] * 22
    assert ui["bounds"]["max"] == [0.25] * 22 and ui["bounds"]["min"] == [0.0] * 22
    closes = [fund["last_close"] for fund in ui["universe"]["funds"]]
    assert all(isinstance(c, float) and c > 0 for c in closes) and closes[0] != closes[1]

    # stress: the 2008 card has both gaps and numbers, and the guide mix is mostly covered
    held = sum(amounts[i] for i in ids)
    gfc = ui["stress"]["gfc2008"]["r"]
    assert sum(v is None for v in gfc) >= 1 and sum(v is not None for v in gfc) >= 15
    for block in ui["stress"].values():
        covered = sum(amounts[i] for i, v in zip(ids, block["r"], strict=True) if v is not None)
        assert covered / held >= 0.5

    nx, ny = len(ui["frontier"]["x"]), len(ui["grid"]["y"])
    assert (nx, ny) == (48, 32) and len(ui["frontier_curve"]["mu"]) == 377
    mu, cov = np.array(ui["mu_s"]), np.array(ui["cov"])
    w_front, w_div = np.array(ui["frontier"]["w"]), np.array(ui["grid"]["w_div"])
    y_front, k_div = np.array(ui["frontier"]["y"]), ui["grid"]["k_div"]
    s_safe = ui["frontier"]["s_safe"]
    domain = range(math.ceil(s_safe), nx)
    assert s_safe < nx - 3  # a real slider domain
    # the current mix sits inside the chart's risk range, so its marker is drawn
    current = np.array([amounts[i] for i in ids]) / held
    assert (
        ui["frontier"]["x"][0] < float(np.sqrt(current @ cov @ current)) < ui["frontier"]["x"][-1]
    )
    # some column gives up at least 0.4 points of yearly return for diversification
    assert max(float(mu @ (w_front[c] - w_div[c])) for c in domain if k_div[c] >= 0) >= 0.004
    # the suggested default is strictly inside the slider somewhere
    y_div, y_sug = np.array(ui["grid"]["y_div"]), np.array(ui["grid"]["y_sug"])
    t_sug = [(y_front[c] - y_sug[c]) / (y_front[c] - y_div[c]) for c in domain if k_div[c] >= 0]
    assert any(0.05 < value < 0.95 for value in t_sug)
    # the heatmap has an interior and its colours vary
    z = ui["grid"]["z"]
    interior = [
        z[j][k] / ui["enb_ref"]
        for j in range(1, nx - 1)
        for k in range(1, ny - 2)
        if ui["grid"]["y"][k + 2] <= min(y_front[j - 1], y_front[j])
        and all(z[j + dj][k + dk] is not None for dj in (-1, 0, 1) for dk in (-1, 0, 1))
    ]
    assert len(interior) >= 20 and max(interior) - min(interior) > 0.25
    # the frontier keeps rising well past the first columns
    assert y_front.max() - y_front[10] > 0.2 * (y_front.max() - ui["grid"]["y"][0])
    # mixes in the slider domain hold partly, mostly and fully pre-2008 funds
    covered = [
        sum(w[i] for i in range(22) if gfc[i] is not None) / w.sum()
        for c in domain
        for w in (w_front[c], w_div[c])
    ]
    assert any(0.5 <= value < 0.995 for value in covered)
    assert any(value < 0.5 for value in covered) and any(value >= 1 - 1e-12 for value in covered)
    # nothing the page prints by default uses a forbidden word
    printed = [fund["name"] for fund in ui["universe"]["funds"]] + ui["notes"]
    printed += [entry["reason"] for entry in excluded] + [ui["universe"]["name"]]
    printed += [block["label"] for block in ui["stress"].values()]
    for word in FORBIDDEN_COPY:
        assert not [text for text in printed if re.search(rf"\b{word}\b", text, re.IGNORECASE)]


def test_other_lookbacks_build_and_the_ten_year_view_excludes_fienx(cli, tmp_path):
    for lookback, rows in (("ew", 1260), ("10y", 2520), ("1y", 252)):
        code, out = _run(cli, tmp_path, *SMALL, lookback=lookback, name=f"{lookback}.json")
        assert code == 0
        tensor = json.loads(out.read_text())
        validate_tensor(tensor)
        assert tensor["lookback"]["id"] == lookback and tensor["lookback"]["rows"] == rows
        assert [e["id"] for e in tensor["universe"]["excluded"]] == ["FIENX"]
        assert len(tensor["frontier"]["x"]) == 6 and len(tensor["grid"]["y"]) == 5
    assert tensor["lookback"]["ew_halflife_days"] is None


def test_fallback_grid_builds(cli, tmp_path):
    code, out = _run(cli, tmp_path, "--nx", "32", "--ny", "24")
    tensor = json.loads(out.read_text())
    assert code == 0 and len(tensor["frontier"]["w"]) == 32 and len(tensor["grid"]["y"]) == 24
    assert len(tensor["frontier_curve"]["sigma"]) == 31 * 8 + 1
    validate_tensor(tensor)


def test_caps_file_changes_the_requested_bounds_and_the_weights(cli, tmp_path):
    caps = tmp_path / "caps.json"
    entries = [{"id": "VWO", "min": None, "max": 0.10}, {"id": "VB", "min": None, "max": None}]
    caps.write_text(json.dumps(entries))
    code, out = _run(cli, tmp_path, *SMALL, "--caps", str(caps), name="capped.json")
    _, plain_out = _run(cli, tmp_path, *SMALL, name="plain.json")
    capped, plain = json.loads(out.read_text()), json.loads(plain_out.read_text())
    ids = [fund["id"] for fund in capped["universe"]["funds"]]
    vwo = ids.index("VWO")
    assert code == 0 and capped["bounds"]["requested"][vwo] == {"min": None, "max": 0.10}
    assert capped["bounds"]["max"][vwo] == 0.10 and plain["bounds"]["max"][vwo] == 0.25
    assert sum(r != {"min": None, "max": None} for r in capped["bounds"]["requested"]) == 1
    assert max(w[vwo] for w in capped["frontier"]["w"]) <= 0.10 + 1e-6
    assert max(w[vwo] for w in plain["frontier"]["w"]) > 0.25 - 1e-6  # the cap really binds
    assert capped["universe"]["hash"] != plain["universe"]["hash"]


def test_unavailable_window_reports_and_writes_nothing(cli, tmp_path, capsys):
    path, frame = _bare_parquet(tmp_path)
    frame.iloc[-200:-48, 2] = np.nan  # a gap in CCC: 100 shared rows in the one-year window
    frame.to_parquet(path)
    code, out = _run(cli, tmp_path, returns=path, lookback="1y", asof="2026-06-30")
    printed = capsys.readouterr()
    assert code == 2 and not out.exists()
    assert "unavailable" in printed.err and "not enough shared history" in printed.err
    done = subprocess.run(
        [sys.executable, "scripts/build_tensor.py", "--returns", str(path), "--lookback", "5y"]
        + ["--asof", "2026-06-30", "--out", str(out)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=300,
    )
    text = done.stdout + done.stderr
    assert done.returncode == 2 and not out.exists() and "Traceback" not in text
    assert "unavailable" in text and "not enough shared history" in text


def test_invalid_caps_exit_with_the_reason(cli, tmp_path, capsys):
    caps = tmp_path / "caps.json"
    caps.write_text(json.dumps([{"id": "VTI", "min": 0.5, "max": 0.3}]))
    code, out = _run(cli, tmp_path, *SMALL, "--caps", str(caps))
    printed = capsys.readouterr()
    assert code == 2 and not out.exists() and "VTI" in printed.err and "caps" in printed.err


def test_parquet_without_metadata_gets_plain_catalog_facts(cli, tmp_path):
    path, frame = _bare_parquet(tmp_path)
    frame.iloc[-3:, 1] = np.nan  # BBB's last return is three sessions before asof: still served
    frame.to_parquet(path)
    code, out = _run(cli, tmp_path, *SMALL, returns=path, lookback="1y", asof="2026-06-30")
    tensor = json.loads(out.read_text())
    assert code == 0
    validate_tensor(tensor)
    universe = tensor["universe"]
    assert universe["name"] == "Custom menu" and universe["preset_id"] is None
    assert [fund["id"] for fund in universe["funds"]] == ["AAA", "BBB", "CCC"]
    assert universe["excluded"] == [] and tensor["rf"] == 0.04
    last_bbb = frame["BBB"].last_valid_index().date().isoformat()
    for fund in universe["funds"]:
        assert fund["name"] == fund["id"] and fund["kind"] == "etf" and fund["source"] == "seed"
        assert fund["last_close"] is None
        expected = last_bbb if fund["id"] == "BBB" else "2026-06-30"
        assert fund["adjusted_through"] == expected
        assert fund["fetched_at"] == f"{expected}T00:00:00Z"
    assert last_bbb == "2026-06-25" and tensor["lookback"]["rows"] == 252 - 3


def test_parquet_without_metadata_applies_the_served_rule(cli, tmp_path):
    """Spec 5.2: served means a last return no more than three sessions before asof."""
    path, frame = _bare_parquet(tmp_path, columns=("AAA", "BBB", "CCC", "DDD"))
    frame.iloc[-4:, 1] = np.nan  # BBB's last return is four sessions before asof
    frame["DDD"] = np.nan  # never priced
    frame.to_parquet(path)
    code, out = _run(cli, tmp_path, *SMALL, returns=path, lookback="1y", asof="2026-06-30")
    tensor = json.loads(out.read_text())
    assert code == 0
    validate_tensor(tensor)
    assert [fund["id"] for fund in tensor["universe"]["funds"]] == ["AAA", "CCC"]
    assert tensor["universe"]["excluded"] == [
        {"id": "BBB", "last_close": None, "reason": "no data since 2026-06-24"},
        {"id": "DDD", "last_close": None, "reason": "no data"},
    ]
    assert tensor["lookback"]["rows"] == 252


def test_served_rule_counts_sessions_back_from_asof(cli, tmp_path):
    """The same file: a fund current for a Sunday asof has fallen behind two sessions later."""
    path, frame = _bare_parquet(tmp_path)
    frame.iloc[-5:, 1] = np.nan  # BBB's last return is Tuesday 2026-06-23
    frame.to_parquet(path)
    code, out = _run(cli, tmp_path, *SMALL, returns=path, lookback="1y", asof="2026-06-28")
    sunday = json.loads(out.read_text())
    assert code == 0 and sunday["universe"]["excluded"] == []
    assert [fund["id"] for fund in sunday["universe"]["funds"]] == ["AAA", "BBB", "CCC"]
    code, out = _run(cli, tmp_path, *SMALL, returns=path, lookback="1y", asof="2026-06-30")
    tuesday = json.loads(out.read_text())
    assert code == 0
    assert tuesday["universe"]["excluded"] == [
        {"id": "BBB", "last_close": None, "reason": "no data since 2026-06-23"}
    ]


def test_served_floor_is_the_session_three_back_as_the_data_layer_counts_it(cli):
    days = ("2025-11-28", "2025-12-26", "2026-01-02", "2026-06-28", "2026-06-30", "2026-07-06")
    for day in days:
        floor = cli.served_floor(pd.Timestamp(day))
        assert floor.date() == session_back(pd.Timestamp(day).date(), 3), day
    assert cli.served_floor(pd.Timestamp("2026-06-30")) == pd.Timestamp("2026-06-25")
    # any date, not only the years the default calendar spans (Presidents' Day, 2005-02-21)
    assert cli.served_floor(pd.Timestamp("2005-02-24")) == pd.Timestamp("2005-02-18")


def test_asof_must_name_a_day(cli, tmp_path):
    assert cli.as_day("2026-06-30T17:00") == pd.Timestamp("2026-06-30")
    with pytest.raises(ValueError, match="asof must be a date, got 'NaT'"):
        _run(cli, tmp_path, asof="NaT")


def test_served_sgov_column_sets_the_risk_free_rate(cli, tmp_path):
    path, frame = _bare_parquet(tmp_path, columns=("AAA", "BBB", "SGOV"))
    frame["SGOV"] = 0.00016
    frame.to_parquet(path)
    code, out = _run(cli, tmp_path, *SMALL, returns=path, lookback="1y", asof="2026-06-30")
    assert code == 0
    assert abs(json.loads(out.read_text())["rf"] - (1.00016**252 - 1.0)) <= 1e-12


def test_last_close_is_only_known_for_the_files_last_day(cli, tmp_path):
    """The parquet's metadata holds the close on its last day: no other day's close is known."""
    code, out = _run(cli, tmp_path, *SMALL, lookback="1y", asof="2026-10-09", name="earlier.json")
    earlier = json.loads(out.read_text())
    assert code == 0 and earlier["asof"] == "2026-10-09"
    assert [fund["last_close"] for fund in earlier["universe"]["funds"]] == [None] * 22
    code, out = _run(cli, tmp_path, *SMALL, lookback="1y", name="last.json")
    assert all(fund["last_close"] > 0 for fund in json.loads(out.read_text())["universe"]["funds"])
