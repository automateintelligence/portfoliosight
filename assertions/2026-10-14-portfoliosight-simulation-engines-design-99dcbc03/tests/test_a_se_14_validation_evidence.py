"""A-SE-14: run the real validation CLI without providers; audit machine rows against
source records and independent coverage/pinball/PIT calculations. Pinned output-directory
contract: coverage.json {rows,metrics}, compare.json {rows,stress_rows,invariants}, report.md.
This is serialization for the experiment, not an extra financial decision threshold.
"""

from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))


def _runtime():
    """Run this frozen file in installed dependencies, importing this run's source."""
    roots = [ROOT]
    if (ROOT / ".git").is_file():
        roots.append(Path((ROOT / ".git").read_text().split(":", 1)[1].strip()).parents[2])
    python = next(
        (p / ".venv/bin/python" for p in roots if (p / ".venv/bin/python").exists()), None
    )
    if python and Path(sys.prefix).resolve() != python.parents[1].resolve():
        result = subprocess.run(
            [str(python), "-m", "pytest", "-q", "--noconftest", "-p", "no:cacheprovider", __file__],
            cwd=ROOT,
            env={
                **os.environ,
                "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
                "PYTHONPATH": str(ROOT),
                "OPENBLAS_NUM_THREADS": "1",
                "OMP_NUM_THREADS": "1",
            },
            text=True,
            capture_output=True,
            timeout=14400,
        )
        assert result.returncode == 0, result.stdout[-12000:] + result.stderr[-3000:]
        return False
    return True


def _product(name, attr=None):
    try:
        module = importlib.import_module(name)
    except Exception as exc:
        pytest.fail(f"Required runtime {name} is unavailable: {type(exc).__name__}: {exc}")
    if name.startswith(("portfoliosight", "scripts")):
        assert Path(module.__file__).resolve().is_relative_to(ROOT), (
            f"Imported foreign source: {module.__file__}"
        )
    if attr is not None:
        if not hasattr(module, attr):
            pytest.fail(f"Missing required runtime interface {name}.{attr}")
        return getattr(module, attr)
    return module


def _fixture_store(directory):
    """Frozen nontrivial returns and canonical records; no mutable fixture helper."""
    np, pd = _product("numpy"), _product("pandas")
    sm = _product("portfoliosight.data.store")
    manifest_mod = _product("portfoliosight.data.manifest")
    store = sm.LocalStore(directory)
    ids = [
        "VTI",
        "VTV",
        "VOE",
        "VB",
        "VBR",
        "VEA",
        "SCHF",
        "VWO",
        "VNQ",
        "VBIAX",
        "SCHO",
        "BND",
        "AGG",
        "TIP",
        "VTIP",
        "LQD",
        "VWOB",
        "PCY",
        "EFA",
        "LTPZ",
        "EDV",
        "VGSTX",
        "DBJP",
        "TSP-G",
        "TSP-F",
        "TSP-C",
        "TSP-S",
        "TSP-I",
        "SGOV",
    ]
    days = pd.bdate_range("2005-01-03", "2026-10-12", name="date")
    rng = np.random.default_rng(20261013)
    factors = rng.normal(size=(len(days), 3))
    manifest = manifest_mod.Manifest()
    for j, fid in enumerate(ids):
        if fid in ("TSP-G", "SGOV"):
            returns = np.full(len(days), 0.035 / 252)
        else:
            # Correlated funds with distinct level, volatility, idiosyncratic noise and tails.
            vol = 0.035 + 0.007 * (j % 19)
            loading = np.array([0.65, 0.2 * ((j % 3) - 1), 0.15])
            returns = (0.025 + 0.002 * (j % 13)) / 252 + (
                factors @ loading + rng.standard_t(7, len(days)) * 0.45
            ) * vol / np.sqrt(252)
        active = days >= (pd.Timestamp("2020-05-28") if fid == "SGOV" else days[0])
        calendar, daily = days[active], returns[active]
        growth = np.r_[1.0, np.cumprod(1 + daily)]
        stamps = pd.DatetimeIndex([calendar[0] - pd.offsets.BDay(1)]).append(calendar)
        record = pd.DataFrame(
            {
                "date": stamps,
                "close": growth * 100,
                "tr_index": growth,
                "div_cash": np.zeros(len(stamps)),
                "split_factor": np.ones(len(stamps)),
            }
        )
        sm.put_record(store, fid, record)
        manifest.symbols[fid] = manifest_mod.ManifestEntry(
            name="Frozen " + fid,
            kind="tsp" if fid.startswith("TSP-") else "etf",
            tier=1,
            source="tsp" if fid.startswith("TSP-") else "seed",
            status="ok",
            first_date=stamps[0].date(),
            last_date=stamps[-1].date(),
            adjusted_through=stamps[-1].date(),
            fetched_at="2026-10-13T09:05:11Z",
        )
    sm.put_json(store, "meta/manifest.json", manifest.to_json())
    return store


def _years(model, weights):
    """Independent §4.5 oracle from the exact arrays the builder consumed, no range call."""
    np = _product("numpy")
    w = np.asarray(weights, dtype=float)
    target = float(np.asarray(model.mu_s) @ w) / 252
    if getattr(model, "engine", "replay") == "replay":
        daily = np.asarray(model.sample) @ w
        growth = 1 + daily - daily.mean() + target
        assert np.all(growth > 0)
        assert model.counts.shape[0] == 2000
        np.testing.assert_array_equal(model.counts.sum(axis=1), np.full(2000, 252))
        return np.expm1(np.asarray(model.counts) @ np.log(growth))
    panel = np.asarray(model.panel, dtype=float)
    assert panel.shape[:2] == (2000, 252)
    flat = panel.reshape(-1, panel.shape[-1])
    mean, sd = flat.mean(axis=0), flat.std(axis=0, ddof=0)
    m = np.asarray(model.mu_s) / 252
    v = np.log1p(np.diag(model.cov) / 252 / (1 + m) ** 2)
    levelled = np.empty_like(flat)
    for n in range(flat.shape[1]):
        if sd[n] <= 64 * np.finfo(float).eps * max(1.0, abs(mean[n])):
            levelled[:, n] = m[n]
        else:
            levelled[:, n] = np.expm1(
                np.log1p(m[n]) - v[n] / 2 + (flat[:, n] - mean[n]) * np.sqrt(v[n]) / sd[n]
            )
    y = levelled @ w
    spread = y.std(ddof=0)
    sigma = float(np.sqrt(w @ np.asarray(model.cov) @ w)) / np.sqrt(252)
    daily = np.full_like(y, target) if spread <= 1e-15 else target + (y - y.mean()) * sigma / spread
    daily = daily.reshape(2000, 252)
    ruined = (daily <= -1).any(axis=1)
    years = np.full(2000, -1.0)
    years[~ruined] = np.expm1(np.log1p(daily[~ruined]).sum(axis=1))
    return years


def _blocked_run(tmp_path, command):
    """Deny provider access and writes outside this invocation's scratch directory."""
    wrapper = tmp_path / "offline_validation.py"
    wrapper.write_text(r"""import os,pathlib,runpy,socket,sys
allowed=pathlib.Path(os.environ['PS_VALIDATION_SCRATCH']).resolve()
def path_of(value):
    if isinstance(value,int): return None
    return pathlib.Path(os.fsdecode(value)).resolve()
def assert_writable(value):
    path=path_of(value)
    if path is not None and not path.is_relative_to(allowed):
        raise AssertionError('Validation attempted a write outside scratch: '+str(path))
def audit(event,args):
    if event=='open':
        path,mode,flags=args
        writing=(isinstance(mode,str) and any(c in mode for c in 'wax+'))
        writing=writing or bool(flags & (os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC|os.O_APPEND))
        if writing: assert_writable(path)
    elif event in ('os.remove','os.rmdir','os.mkdir','os.chmod','os.utime','os.truncate'):
        assert_writable(args[0])
    elif event in ('os.rename','os.link','os.symlink'):
        assert_writable(args[0]); assert_writable(args[1])
    elif event in ('subprocess.Popen','os.system','os.exec','os.posix_spawn'):
        raise AssertionError('Validation cannot bypass the frozen read-only process boundary')
sys.addaudithook(audit)
def blocked(*a,**k): raise AssertionError('Provider/network access forbidden')
socket.create_connection=blocked
socket.socket.connect=blocked
sys.argv=sys.argv[1:]
runpy.run_path(sys.argv[0],run_name='__main__')
""")
    # Filesystem metadata detects native-extension writes that bypass Python's open audit event.
    marker = command.index("--store-dir")
    source = Path(command[marker + 1])

    def snapshot():
        return {
            str(path.relative_to(source)): (path.stat().st_size, path.stat().st_mtime_ns)
            for path in source.rglob("*")
            if path.is_file()
        }

    before = snapshot()
    try:
        result = subprocess.run(
            [sys.executable, str(wrapper), *command],
            cwd=ROOT,
            env={
                **os.environ,
                "PYTHONPATH": str(ROOT),
                "PS_ENGINES": "replay,garch",
                "PS_BUILD_WORKERS": "1",
                "PS_VALIDATION_SCRATCH": str(tmp_path),
                "PS_CACHE_DIR": str(tmp_path / "validation-cache"),
                "XDG_CACHE_HOME": str(tmp_path / "xdg-cache"),
                "TMPDIR": str(tmp_path),
                "PYTHONDONTWRITEBYTECODE": "1",
            },
            capture_output=True,
            text=True,
            timeout=7200,
        )
    finally:
        assert snapshot() == before, "Validation modified its input store"
    assert result.returncode == 0, result.stdout[-5000:] + result.stderr[-4000:]


def _audit_rows(rows, store):
    np = _product("numpy")
    sm = _product("portfoliosight.data.store")
    hashes = _product("hashlib")
    metrics = {}
    for row in rows:
        assert row["fit_end"] <= row["origin"]
        assert row["paths"] == 2000 and row["horizon_days"] == 252
        years = np.asarray(row["simulated_years"], float)
        assert years.shape == (2000,) and np.isfinite(years).all()
        expected = np.percentile(years, [2.5, 50, 97.5], method="linear")
        np.testing.assert_allclose(
            [row["predicted"][k] for k in ("bad", "typical", "good")],
            expected,
            atol=2e-10,
            rtol=2e-9,
        )
        future = []
        for record in row["source_records"]:
            assert hashes.sha256(store.get(record["key"])).hexdigest() == record["sha256"]
            data = sm.get_record(store, record["id"]).set_index("date")["tr_index"].sort_index()
            origin = _product("pandas").Timestamp(row["origin"])
            # The approved Phase 6 plan compounds constant-weight daily returns.
            future.append(data.pct_change().loc[data.index > origin].iloc[:252])
        matrix = _product("pandas").concat(future, axis=1, join="inner").dropna().to_numpy()
        assert matrix.shape == (252, len(row["weights"]))
        realized = float(np.expm1(np.log1p(matrix @ np.asarray(row["weights"])).sum()))
        assert row["realized"] == pytest.approx(realized, abs=1e-12)
        group = (row["menu"], row["lookback"], row["engine"])
        record = metrics.setdefault(group, [])
        losses = [
            float((q - (realized < pred)) * (realized - pred))
            for q, pred in zip((0.025, 0.5, 0.975), expected, strict=True)
        ]
        pit = float(np.count_nonzero(years <= realized) / 2000)
        record.append(
            {
                "origin": row["origin"],
                "covered": bool(expected[0] <= realized <= expected[2]),
                "breach": bool(realized < expected[0]),
                "pinball": losses,
                "pit": pit,
            }
        )
    return metrics


def test_a_se_14_prescribed_validation_evidence(tmp_path):
    if not _runtime():
        return
    script = ROOT / "scripts/backtest_ranges.py"
    if not script.exists():
        pytest.fail("A-SE-14 expected RED: scripts/backtest_ranges.py is not implemented")
    mirror = Path(os.environ.get("PS_ENGINE_VALIDATION_STORE", "/mnt/d/portfoliosight-data"))
    if not mirror.is_dir():
        pytest.fail("A-SE-14 requires the local backup mirror; no provider fallback")
    np = _product("numpy")
    sm = _product("portfoliosight.data.store")
    store = sm.LocalStore(mirror)
    out = tmp_path / "validation"
    common = [
        "--store-dir",
        str(mirror),
        "--menus",
        "guide2017,tsp",
        "--lookbacks",
        "5y,1y",
        "--engines",
        "replay,garch",
        "--out",
        str(out),
    ]
    for subcommand in ("coverage", "compare"):
        _blocked_run(tmp_path, [str(script), subcommand, *common])
    doc = json.loads((out / "coverage.json").read_text())
    rows = doc["rows"]
    expected_quarters = {
        f"{year}-{month:02d}"
        for year in range(2015, 2026)
        for month in (3, 6, 9, 12)
        if "2015-12" <= f"{year}-{month:02d}" <= "2025-09"
    }
    assert len(expected_quarters) == 40
    keys = [(r["menu"], r["lookback"], r["origin"], r["mix"], r["engine"]) for r in rows]
    assert len(keys) == len(set(keys)), "Duplicate observations inflate coverage evidence"
    historical = {}
    preset_definitions = _product("portfoliosight.api.presets").preset_definitions()
    pd = _product("pandas")
    for preset in preset_definitions:
        prices = pd.DataFrame(
            {fid: sm.get_record(store, fid).set_index("date")["tr_index"] for fid in preset.funds}
        ).sort_index()
        historical[preset.id] = prices / prices.shift(1) - 1
    for menu in ("guide2017", "tsp"):
        for lb in ("1y", "5y"):
            subset = [r for r in rows if r["menu"] == menu and r["lookback"] == lb]
            assert {r["origin"][:7] for r in subset} == expected_quarters
            assert len({r["origin"] for r in subset}) == 40
            calendar = _product("exchange_calendars").get_calendar("XNYS")
            pd = _product("pandas")
            expected_days = set()
            for quarter in expected_quarters:
                end = pd.Period(quarter, freq="M").end_time.normalize()
                sessions = calendar.sessions_in_range(end - pd.Timedelta(days=10), end)
                expected_days.add(sessions[-1].date().isoformat())
            assert {r["origin"] for r in subset} == expected_days
            assert len({r["origin"] for r in subset if r["origin"][5:7] == "12"}) == 10
            paired = {(r["origin"], r["mix"]) for r in subset if r["engine"] == "replay"}
            assert paired == {(r["origin"], r["mix"]) for r in subset if r["engine"] == "garch"}
            paired_rows = {(r["origin"], r["mix"], r["engine"]): r for r in subset}
            for origin, mix in paired:
                replay_row = paired_rows[origin, mix, "replay"]
                garch_row = paired_rows[origin, mix, "garch"]
                assert replay_row["weights"] == garch_row["weights"], (
                    "Engine comparison changed the mix"
                )
                assert [r["id"] for r in replay_row["source_records"]] == [
                    r["id"] for r in garch_row["source_records"]
                ]
            assert "equal_weight" in {r["mix"] for r in subset}
            preset = next(preset for preset in preset_definitions if preset.id == menu)
            if preset.allocation:
                assert {r["origin"] for r in subset if r["mix"] == "entered"} == {
                    r["origin"] for r in subset
                }
            else:
                assert not [r for r in subset if r["mix"] == "entered"], (
                    "Fabricated an absent entered allocation"
                )
                unavailable = [
                    item
                    for item in doc["unavailable_cases"]
                    if item["menu"] == menu and item["lookback"] == lb and item["mix"] == "entered"
                ]
                assert {item["origin"] for item in unavailable} == {r["origin"] for r in subset}
                assert len(unavailable) == 80
                assert {(item["origin"], item["engine"]) for item in unavailable} == {
                    (origin, engine)
                    for origin in {r["origin"] for r in subset}
                    for engine in ("replay", "garch")
                }
                assert all(
                    item["status"] == "unavailable" and item["reason"] == "no_allocation"
                    for item in unavailable
                )
            for origin in {r["origin"] for r in subset}:
                mixes = {r["mix"] for r in subset if r["origin"] == origin}
                assert all(
                    any(kind in mix and location in mix for mix in mixes)
                    for kind in ("frontier", "optimized")
                    for location in ("safe", "mid", "max")
                )
                origin_rows = [row for row in subset if row["origin"] == origin]
                included = {item["id"] for item in origin_rows[0]["source_records"]}
                frame = historical[menu].loc[:origin]
                length = 252 if lb == "1y" else 1260
                start = len(frame) - length
                expected_included = set()
                for fid in frame.columns:
                    valid = frame[fid].notna().to_numpy()
                    if valid.any() and 10 * (int(valid.argmax()) - start) <= length:
                        expected_included.add(fid)
                assert included == expected_included, (
                    "Validation omitted or fabricated eligible funds"
                )
                for row in origin_rows:
                    ids = [item["id"] for item in row["source_records"]]
                    assert ids == [fid for fid in frame.columns if fid in expected_included]
                    weights = np.asarray(row["weights"], dtype=float)
                    assert weights.shape == (len(ids),) and weights.sum() == pytest.approx(
                        1.0, abs=1e-12
                    )
                    assert np.all(weights >= -1e-12)
                    if row["mix"] == "equal_weight":
                        np.testing.assert_allclose(
                            weights, np.full(len(ids), 1 / len(ids)), atol=1e-12
                        )
                    elif row["mix"].startswith("single:"):
                        fund = row["mix"].split(":", 1)[1]
                        np.testing.assert_array_equal(
                            weights, np.array([float(fid == fund) for fid in ids])
                        )
                    elif row["mix"] == "entered":
                        assert preset.allocation
                        allocation = np.array([preset.allocation.get(fid, 0.0) for fid in ids])
                        assert allocation.sum() > 0
                        np.testing.assert_allclose(
                            weights, allocation / allocation.sum(), atol=1e-12
                        )
                assert {m for m in mixes if m.startswith("single:")} == {
                    "single:" + fid for fid in included
                }
                assert 2 <= len(included) <= (23 if menu == "guide2017" else 5)
    recomputed = _audit_rows(rows, store)
    for metric in doc["metrics"]:
        group = recomputed[metric["menu"], metric["lookback"], metric["engine"]]
        sample = [
            x for x in group if metric["origin_set"] == "quarterly" or x["origin"][5:7] == "12"
        ]
        assert metric["observations"] == len(sample)
        assert metric["coverage"] == pytest.approx(
            np.mean([x["covered"] for x in sample]), abs=1e-12
        )
        assert metric["below_bad"] == sum(x["breach"] for x in sample)
        np.testing.assert_allclose(
            metric["pinball"], np.sum([x["pinball"] for x in sample], axis=0), atol=1e-10
        )
        pits = np.sort([x["pit"] for x in sample])
        n = len(pits)
        ks = max(np.max(np.arange(1, n + 1) / n - pits), np.max(pits - np.arange(n) / n))
        assert metric["pit_ks"] == pytest.approx(ks, abs=1e-12)
    assert len(doc["metrics"]) == 2 * 2 * 2 * 2
    metric_keys = [(m["menu"], m["lookback"], m["engine"], m["origin_set"]) for m in doc["metrics"]]
    assert len(metric_keys) == len(set(metric_keys))
    assert set(metric_keys) == {
        (menu, lb, engine, scope)
        for menu in ("guide2017", "tsp")
        for lb in ("1y", "5y")
        for engine in ("replay", "garch")
        for scope in ("quarterly", "year_end")
    }
    assert {metric["origin_set"] for metric in doc["metrics"]} == {"quarterly", "year_end"}
    # Sample each menu/lookback through the actual builder at its historical origin.
    builder = _product("portfoliosight.engine.builder")
    build = _product("portfoliosight.engine.builder", "build_tensor_full")
    presets = _product("portfoliosight.api.presets").preset_definitions()
    pd = _product("pandas")
    for menu in ("guide2017", "tsp"):
        preset = next(p for p in presets if p.id == menu)
        records = {
            fid: sm.get_record(store, fid).set_index("date")["tr_index"].sort_index()
            for fid in preset.funds
        }
        prices = pd.DataFrame(records).sort_index()
        returns = prices / prices.shift(1) - 1
        for lb in ("1y", "5y"):
            row = next(
                r
                for r in rows
                if r["menu"] == menu
                and r["lookback"] == lb
                and r["engine"] == "garch"
                and r["mix"] == "equal_weight"
            )
            origin = row["origin"]
            funds = [
                builder.FundInput(
                    id=fid,
                    name=fid,
                    kind="tsp" if menu == "tsp" else "etf",
                    source="seed",
                    adjusted_through=origin,
                    fetched_at=origin + "T00:00:00Z",
                )
                for fid in preset.funds
            ]
            rf = {}
            for fid in ("SGOV", "SHV", "TSP-G"):
                if store.exists(sm.record_key(fid)):
                    rf[fid] = (
                        sm.get_record(store, fid)
                        .set_index("date")["tr_index"]
                        .sort_index()
                        .pct_change(fill_method=None)
                    )
            result = build(
                builder.TensorInputs(
                    funds=funds,
                    returns=returns,
                    lookback=lb,
                    asof=origin,
                    universe_name=menu,
                    preset_id=menu,
                    rf_series=rf,
                    engines=("replay", "garch"),
                ),
                workers=1,
            )
            assert [f["id"] for f in result.tensor["universe"]["funds"]] == [
                f["id"] for f in row["source_records"]
            ]
            np.testing.assert_allclose(row["mu"], result.tensor["mu_s"], atol=1e-12)
            np.testing.assert_allclose(row["cov"], result.tensor["cov"], atol=1e-12)
            for engine in ("replay", "garch"):
                observed = next(
                    r
                    for r in rows
                    if r["menu"] == menu
                    and r["lookback"] == lb
                    and r["origin"] == origin
                    and r["mix"] == "equal_weight"
                    and r["engine"] == engine
                )
                np.testing.assert_allclose(
                    observed["simulated_years"],
                    _years(result.models[engine], observed["weights"]),
                    atol=2e-10,
                    rtol=2e-9,
                )
    # Synthetic no-leakage control through the same public CLI, using a temporary fixture store.
    fixture = _fixture_store(tmp_path / "synthetic")
    origin = "2020-12-31"
    synthetic_args = [
        "--store-dir",
        str(tmp_path / "synthetic"),
        "--menus",
        "tsp",
        "--lookbacks",
        "1y",
        "--engines",
        "replay,garch",
        "--origins",
        origin,
    ]
    first_out, second_out = tmp_path / "synthetic-a", tmp_path / "synthetic-b"
    _blocked_run(tmp_path, [str(script), "coverage", *synthetic_args, "--out", str(first_out)])
    a = json.loads((first_out / "coverage.json").read_text())["rows"]
    frame = sm.get_record(fixture, "TSP-C")
    later = frame["date"] > _product("pandas").Timestamp(origin)
    frame.loc[later, "tr_index"] *= np.exp(np.arange(later.sum()) * 0.001)
    sm.put_record(fixture, "TSP-C", frame)
    _blocked_run(tmp_path, [str(script), "coverage", *synthetic_args, "--out", str(second_out)])
    b = json.loads((second_out / "coverage.json").read_text())["rows"]
    assert [r["predicted"] for r in a] == [r["predicted"] for r in b], (
        "Future observations leaked into origin prediction"
    )
    assert [r["realized"] for r in a] != [r["realized"] for r in b], (
        "Validation is disconnected from realized prices"
    )
    _audit_rows(
        a,
        _fixture_store(tmp_path / "synthetic-original"),
    )
    _audit_rows(b, fixture)
    constant = [row for row in a if row["mix"] == "single:TSP-G"]
    assert len(constant) == 2
    for row in constant:
        assert row["realized"] == pytest.approx((1 + 0.035 / 252) ** 252 - 1, abs=1e-12)
    compare = json.loads((out / "compare.json").read_text())
    assert {r["menu"] for r in compare["rows"]} == {"guide2017", "tsp"}
    for menu in ("guide2017", "tsp"):
        for engine in ("replay", "garch"):
            assert {
                r["column"]
                for r in compare["rows"]
                if r["menu"] == menu and r["engine"] == engine and r["point"] == "frontier"
            } == set(range(48))
            assert (
                len(
                    [
                        r
                        for r in compare["stress_rows"]
                        if r["menu"] == menu and r["engine"] == engine
                    ]
                )
                >= 9
            )
    assert compare["invariants"] and all(r["passed"] for r in compare["invariants"])
    # Numeric live/stress evidence cannot be replaced with headings or placeholder rows.
    live_summary, stress_summary = [], []
    windows = {
        "gfc2008": ("2008-09-01", "2009-03-09"),
        "covid2020": ("2020-02-19", "2020-03-23"),
        "rates2022": ("2022-01-03", "2022-10-12"),
    }
    for row in compare["rows"]:
        years = np.asarray(row["simulated_years"], dtype=float)
        assert years.shape == (2000,) and np.isfinite(years).all()
        expected = np.percentile(years, [2.5, 50, 97.5], method="linear")
        np.testing.assert_allclose(
            [row["predicted"][name] for name in ("bad", "typical", "good")],
            expected,
            atol=2e-10,
            rtol=2e-9,
        )
        assert row["point"] in ("frontier", "optimized")
        assert 0 <= row["column"] < 48
        live_summary.append(
            {
                key: row[key]
                for key in ("menu", "lookback", "engine", "point", "column", "predicted")
            }
        )
    for row in compare["stress_rows"]:
        assert row["window"] in windows and row["location"] in ("safe", "mid", "max")
        start, end = windows[row["window"]]
        assert (row["start"], row["end"]) == (start, end)
        weights = np.asarray(row["weights"], dtype=float)
        assert len(weights) == len(row["source_records"])
        assert np.all(weights >= -1e-6) and weights.sum() == pytest.approx(1.0, abs=1e-6)
        gained, covered = 0.0, 0.0
        for weight, record in zip(weights, row["source_records"], strict=True):
            assert (
                _product("hashlib").sha256(store.get(record["key"])).hexdigest() == record["sha256"]
            )
            values = (
                sm.get_record(store, record["id"])
                .set_index("date")["tr_index"]
                .dropna()
                .sort_index()
            )
            left, right = values.loc[:start], values.loc[:end]
            if left.empty or right.empty:
                continue
            left_age = len(calendar.sessions_in_range(left.index[-1], pd.Timestamp(start))) - 1
            right_age = len(calendar.sessions_in_range(right.index[-1], pd.Timestamp(end))) - 1
            if left_age > 3 or right_age > 3:
                continue
            covered += weight
            gained += weight * (float(right.iloc[-1] / left.iloc[-1]) - 1)
        assert row["covered"] == pytest.approx(covered, abs=1e-12)
        if covered < 0.5:
            assert row["loss"] is None and row["pit"] is None
        else:
            loss = gained / covered
            assert row["loss"] == pytest.approx(loss, abs=1e-12)
            years = np.asarray(row["simulated_years"], dtype=float)
            assert years.shape == (2000,) and np.isfinite(years).all()
            assert row["pit"] == pytest.approx(
                float(np.count_nonzero(years <= loss) / 2000), abs=1e-12
            )
        stress_summary.append(
            {
                key: row[key]
                for key in (
                    "menu",
                    "lookback",
                    "engine",
                    "window",
                    "location",
                    "loss",
                    "covered",
                    "pit",
                )
            }
        )
    for menu in ("guide2017", "tsp"):
        for lb in ("1y", "5y"):
            for engine in ("replay", "garch"):
                scope = [
                    row
                    for row in compare["rows"]
                    if row["menu"] == menu and row["lookback"] == lb and row["engine"] == engine
                ]
                for point in ("frontier", "optimized"):
                    assert {row["column"] for row in scope if row["point"] == point} == set(
                        range(48)
                    )
                stress_scope = [
                    row
                    for row in stress_summary
                    if row["menu"] == menu and row["lookback"] == lb and row["engine"] == engine
                ]
                assert {(row["window"], row["location"]) for row in stress_scope} == {
                    (window, location) for window in windows for location in ("safe", "mid", "max")
                }
    components = []
    # Only explicitly defined components are judged. No new breach aggregation or winner rule.
    for menu in ("guide2017", "tsp"):
        for lb in ("1y", "5y"):
            grouped = {}
            for engine in ("replay", "garch"):
                values = recomputed[menu, lb, engine]
                annual = {}
                for row in values:
                    if row["origin"][5:7] == "12":
                        annual.setdefault(row["origin"], np.zeros(3))
                        annual[row["origin"]] += row["pinball"]
                assert len(annual) == 10
                grouped[engine] = annual
            years = sorted(grouped["replay"])
            assert years == sorted(grouped["garch"])
            a = np.asarray([grouped["replay"][year] for year in years])
            b = np.asarray([grouped["garch"][year] for year in years])
            components.append(
                {
                    "menu": menu,
                    "lookback": lb,
                    "bad_pinball_wins": int(np.count_nonzero(b[:, 0] < a[:, 0])),
                    "nonoverlapping_years": 10,
                    "median_no_worse": bool(b[:, 1].sum() <= a[:, 1].sum()),
                    "good_no_worse": bool(b[:, 2].sum() <= a[:, 2].sum()),
                }
            )
    report = (out / "report.md").read_text()
    assert (
        "overlap" in report.lower() and "weak" in report.lower() and "lower bound" in report.lower()
    )
    # Structured decision criteria prevent changing the rule to match a result.
    assert doc["decision_rule"] == {
        "bad_pinball_wins_required": 8,
        "nonoverlapping_years": 10,
        "median_good_no_worse": True,
        "breaches_allowed": [0, 1],
        "stress_percentile_floor": 0.005,
        "owner_review_required": True,
        "tie_keeps_default": True,
    }
    import re

    summaries = []
    for fence in re.findall(r"```(?:json)?\s*\n(.*?)```", report, re.S):
        try:
            value = json.loads(fence)
        except ValueError:
            continue
        if isinstance(value, dict) and "engine_validation_summary" in value:
            summaries.append(value["engine_validation_summary"])
    assert len(summaries) == 1, "Published report needs one compact verified experiment summary"
    summary = summaries[0]
    for key, expected in {
        "metrics": doc["metrics"],
        "unavailable_cases": doc.get("unavailable_cases", []),
        "decision_rule": doc["decision_rule"],
        "decision_components": components,
        "live_comparison": live_summary,
        "stress_comparison": stress_summary,
        "invariant_results": compare["invariants"],
        "default_engine": "replay",
        "owner_review_required": True,
    }.items():
        assert summary[key] == expected, "Published report detached from evaluated " + key
    # Human-readable metric tables must carry their corresponding verified values too.
    table = [line for line in report.splitlines() if line.strip().startswith("|")]
    for metric in doc["metrics"]:
        labels = (metric["menu"], "Example Portfolio" if metric["menu"] == "guide2017" else "TSP")
        matching = [
            line
            for line in table
            if any(label.lower() in line.lower() for label in labels)
            and metric["lookback"] in line
            and metric["engine"] in line
            and metric["origin_set"].replace("_", " ").lower() in line.replace("_", " ").lower()
        ]
        coverage = (
            str(metric["coverage"]),
            f"{metric['coverage']:.4f}",
            f"{metric['coverage'] * 100:.1f}%",
            f"{metric['coverage'] * 100:.2f}%",
        )
        assert any(
            any(value in line for value in coverage)
            and re.search(r"\b" + str(metric["below_bad"]) + r"\b", line)
            for line in matching
        ), "Published table omits or changes verified coverage/breach values"
    saved_reports = list((ROOT / "docs/reviews").glob("*engine*validation*.md"))
    bound_saved = []
    for path in saved_reports:
        for fence in re.findall(r"```(?:json)?\s*\n(.*?)```", path.read_text(), re.S):
            try:
                saved = json.loads(fence)
            except ValueError:
                continue
            if isinstance(saved, dict) and saved.get("engine_validation_summary") == summary:
                bound_saved.append(path)
    assert bound_saved, "No saved docs/reviews report binds to the evaluated experiment"
