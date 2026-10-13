"""A-PS-04 — the seed converts the lake faithfully, refuses drift, and never writes to the lake.

Claim: scripts/seed_r2_from_lake.py converts each lake parquet to the canonical record with
tr_index = adj_close / adj_close[0], refuses to upload anything when any row after
--adjusted-through has adj_close != close, writes manifest entries source: seed, status: pending,
adjusted_through as given, exits non-zero with a clear message when the lake path is missing or
holds fewer than 1,000 files, and leaves every lake file byte-identical.

Pinned interface (the product must provide exactly this):
- `python scripts/seed_r2_from_lake.py --lake <dir> --adjusted-through YYYY-MM-DD [--dry-run]`,
  run from the repository root; the target store comes from the environment (`PS_STORE=local`,
  `PS_LOCAL_STORE_DIR=<dir>`). There is no flag that lowers the 1,000-file floor; the floor counts
  `*.parquet` files only (the real lake also holds `.csv` files, which are ignored).
- A lake file `<SYMBOL>.parquet` (columns `date, open, high, low, close, adj_close, volume`)
  becomes `prices/<SYMBOL>.parquet` (the file stem is the symbol id): every lake row kept, `close`
  unchanged, `tr_index` 1.0 on the first row and NaN on rows after `--adjusted-through`,
  `div_cash` and `split_factor` null; plus `meta/manifest.json` = `{"symbols": {ID: entry}}` with
  `source: "seed"`, `status: "pending"`, `adjusted_through`, `first_date`, `last_date`.
- Refusals exit non-zero without a Python traceback; the drift message names the symbol and the
  ISO date of the offending row; the missing-path and under-floor messages name the lake path.
- `--dry-run` writes nothing and prints, per symbol, a line holding the symbol and the ISO date of
  its latest adjustment (the last row with `adj_close != close`).
- The fixture lake `tests/fixtures/lake/*.parquet` (three symbols) must hold at least one row
  dated after the latest adjustment date found in it, as the real lake does.
- `portfoliosight.data.store.LocalStore(root)` reads the result back (shared pin).
"""

from __future__ import annotations

import hashlib
import importlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))


def _project_python() -> Path | None:
    """The project's virtualenv interpreter: this checkout's, else the main checkout's (worktree)."""
    roots = [ROOT]
    dot_git = ROOT / ".git"
    if dot_git.is_file():  # linked worktree: "gitdir: <main>/.git/worktrees/<name>"
        roots.append(Path(dot_git.read_text().split(":", 1)[1].strip()).parents[2])
    for root in roots:
        candidate = root / ".venv" / "bin" / "python"
        if candidate.exists():
            return candidate
    return None


_VENV_PY = _project_python()
_OUTER = (
    os.environ.get("PS_GATE_INNER") != "1"
    and _VENV_PY is not None
    and Path(sys.prefix).resolve() != _VENV_PY.parents[1].resolve()
)


def _need(module: str):
    """Import a product (or dev-dependency) module, failing the test cleanly when it is absent."""
    try:
        return importlib.import_module(module)
    except Exception as exc:  # ImportError, or an import-time crash in the product
        pytest.fail(f"A-PS-04 red: cannot import {module}: {type(exc).__name__}: {exc}")


SCRIPT = ROOT / "scripts" / "seed_r2_from_lake.py"
FIXTURE_LAKE = ROOT / "tests" / "fixtures" / "lake"
FLOOR = 1000
LAKE_COLUMNS = ("date", "open", "high", "low", "close", "adj_close", "volume")
RECORD_COLUMNS = ("date", "close", "tr_index", "div_cash", "split_factor")
_CACHE: dict = {}


def _days(frame) -> list[str]:
    pd = _need("pandas")
    return [d.strftime("%Y-%m-%d") for d in pd.to_datetime(frame["date"])]


def _latest_adjustment(frame) -> str | None:
    """The last date on which adj_close differs from close (None when it never does)."""
    differs = frame["adj_close"].to_numpy(dtype=float) != frame["close"].to_numpy(dtype=float)
    days = _days(frame)
    hits = [d for d, flag in zip(days, differs) if flag]
    return max(hits) if hits else None


def _lakes(tmp_path_factory) -> dict:
    """Build the temp lakes once: 1,000 clean files, 999 files, and a drifted copy of the 1,000."""
    if _CACHE:
        return _CACHE
    if not SCRIPT.is_file():
        pytest.fail(f"A-PS-04 red: {SCRIPT.relative_to(ROOT)} does not exist")
    pq = _need("pyarrow.parquet")
    pa = _need("pyarrow")
    sources = sorted(FIXTURE_LAKE.glob("*.parquet")) if FIXTURE_LAKE.is_dir() else []
    if len(sources) < 3:
        pytest.fail(
            f"A-PS-04 red: fixture lake {FIXTURE_LAKE.relative_to(ROOT)} needs three *.parquet "
            f"files, found {len(sources)}"
        )
    tables = {}
    for path in sources:
        table = pq.read_table(path)
        missing = [c for c in LAKE_COLUMNS if c not in table.column_names]
        assert not missing, f"fixture lake file {path.name} lacks columns {missing}"
        days = _days(table.to_pandas())
        assert days == sorted(days) and len(set(days)) == len(days), f"{path.name}: dates unsorted"
        tables[path.stem] = table
    latest = {s: _latest_adjustment(t.to_pandas()) for s, t in tables.items()}
    assert any(latest.values()), "fixture lake has no row with adj_close != close (no adjustments)"
    through = max(d for d in latest.values() if d)
    for symbol, table in tables.items():
        assert sum(1 for d in _days(table.to_pandas()) if d <= through) >= 2, (
            f"fixture lake file {symbol} has fewer than two rows on or before {through}"
        )
    assert any(d > through for t in tables.values() for d in _days(t.to_pandas())), (
        f"fixture lake has no row dated after its latest adjustment date {through}; "
        "the price-only and drift legs need at least one"
    )

    base = tmp_path_factory.mktemp("a_ps_04")
    clean = base / "lake_clean"
    clean.mkdir()
    for path in sources:
        shutil.copyfile(path, clean / path.name)
    symbols = sorted(tables)
    for i in range(1, FLOOR - len(sources) + 1):  # tiny slices around the adjustment date
        table = tables[symbols[i % len(symbols)]]
        days = _days(table.to_pandas())
        pos = max(k for k, d in enumerate(days) if d <= through)
        lo = max(0, pos - 30)
        pq.write_table(table.slice(lo, min(len(days) - lo, 42)), clean / f"ZZF{i:04d}.parquet")
    for name in ("ZZF0001.csv", "AAA_NOTES.csv", "README.csv"):  # the real lake holds csv too
        (clean / name).write_text("date,close\n2026-01-02,1.0\n")
    names = sorted(p.name for p in clean.glob("*.parquet"))
    assert len(names) == FLOOR, f"test lake has {len(names)} parquet files"

    short = base / "lake_999"
    shutil.copytree(clean, short)
    (short / "ZZF0500.parquet").unlink()
    assert len(list(short.glob("*.parquet"))) == FLOOR - 1
    assert len(list(short.iterdir())) > FLOOR, "999-parquet lake must hold >= 1,000 files in all"

    drift = base / "lake_drift"
    shutil.copytree(clean, drift)
    candidates = []
    for name in names:
        days = _days(pq.read_table(drift / name, columns=["date"]).to_pandas())
        if any(d > through for d in days):
            candidates.append(name)
    victim = max(candidates)  # alphabetically last: worst case for an upload-as-you-go script
    table = pq.read_table(drift / victim)
    frame = table.to_pandas()
    days = _days(frame)
    row = max(k for k, d in enumerate(days) if d > through)
    frame.loc[row, "adj_close"] = float(frame.loc[row, "close"]) * 1.01
    pq.write_table(
        pa.Table.from_pandas(frame, schema=table.schema, preserve_index=False), drift / victim
    )

    _CACHE.update(
        clean=clean,
        short=short,
        drift=drift,
        missing=base / "no_such_lake",
        through=through,
        latest=latest,
        drift_symbol=Path(victim).stem,
        drift_day=days[row],
        base=base,
    )
    return _CACHE


def _snapshot(lake: Path) -> dict[str, str]:
    if not lake.exists():
        return {}
    out = {}
    for path in sorted(lake.rglob("*")):
        rel = str(path.relative_to(lake))
        out[rel] = "dir" if path.is_dir() else hashlib.sha256(path.read_bytes()).hexdigest()
    return out


def _run(lake: Path, store_dir: Path, through: str, *extra: str):
    """Run the seed script; assert the lake is byte-identical afterwards. Returns (code, output)."""
    before = _snapshot(lake)
    env = {k: v for k, v in os.environ.items() if not k.startswith(("CLOUDFLARE_", "AWS_"))}
    env.update(PS_STORE="local", PS_LOCAL_STORE_DIR=str(store_dir), PYTHONDONTWRITEBYTECODE="1")
    cmd = [sys.executable, str(SCRIPT), "--lake", str(lake), "--adjusted-through", through, *extra]
    try:
        proc = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True, timeout=600)
    except subprocess.TimeoutExpired:
        pytest.fail(f"A-PS-04 red: seed script did not finish within 600 s ({' '.join(extra)})")
    after = _snapshot(lake)
    new = sorted(set(after) - set(before))
    gone = sorted(set(before) - set(after))
    changed = sorted(k for k in before if k in after and before[k] != after[k])
    assert not new, f"the seed wrote new files under the lake: {new[:5]}"
    assert not gone and not changed, (
        f"lake files changed: removed {gone[:5]}, modified {changed[:5]}"
    )
    assert after == before
    assert not lake.exists() or lake.is_dir(), "the lake path was replaced by a file"
    return proc.returncode, proc.stdout + "\n" + proc.stderr


def _store(store_dir: Path):
    store_dir.mkdir(parents=True, exist_ok=True)
    return _need("portfoliosight.data.store").LocalStore(store_dir)


def _assert_nothing_written(store_dir: Path, what: str):
    keys = _store(store_dir).list("")
    assert not [k for k in keys if k.startswith("prices/")], f"{what}: prices/ keys were written"
    assert keys == [], f"{what}: the store must stay empty, found {keys[:5]}"


if _OUTER:

    def test_a_ps_04_in_project_venv():
        env = dict(os.environ, PS_GATE_INNER="1", PYTEST_DISABLE_PLUGIN_AUTOLOAD="1")
        proc = subprocess.run(
            [
                str(_VENV_PY),
                "-m",
                "pytest",
                "-q",
                "--noconftest",
                "-p",
                "no:cacheprovider",
                __file__,
            ],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
        )
        print(proc.stdout[-8000:], proc.stderr[-2000:])
        assert proc.returncode == 0, "A-PS-04 is red inside the project virtualenv (output above)"

else:

    def test_clean_lake_is_converted_faithfully(tmp_path, tmp_path_factory):
        pd = _need("pandas")
        np = _need("numpy")
        lakes = _lakes(tmp_path_factory)
        through = lakes["through"]
        store_dir = tmp_path / "store"
        code, output = _run(lakes["clean"], store_dir, through)
        assert code == 0, f"seed over the clean 1,000-file lake exited {code}:\n{output[-1500:]}"
        store = _store(store_dir)

        lake_files = {p.stem: p for p in lakes["clean"].glob("*.parquet")}
        keys = store.list("prices/")
        assert sorted(keys) == sorted(f"prices/{s}.parquet" for s in lake_files), (
            f"{len(keys)} prices/ keys for {len(lake_files)} lake parquet files"
        )
        assert "prices/README.parquet" not in keys, "a csv file was treated as a lake record"
        doc = json.loads(store.get("meta/manifest.json"))
        entries = doc["symbols"]
        assert set(entries) == set(lake_files), "manifest ids differ from the lake's symbols"

        pairs = price_only = 0
        for symbol, path in sorted(lake_files.items()):
            lake = pd.read_parquet(path).sort_values("date").reset_index(drop=True)
            record = pd.read_parquet(io.BytesIO(store.get(f"prices/{symbol}.parquet")))
            for column in RECORD_COLUMNS:
                assert column in record.columns, f"{symbol}: record lacks column {column}"
            record = record.sort_values("date").reset_index(drop=True)
            assert pd.to_datetime(record["date"]).dt.tz is None, f"{symbol}: date must be tz-naive"
            days = _days(lake)
            assert _days(record) == days, f"{symbol}: record dates differ from the lake file"
            close = lake["close"].to_numpy(dtype=float)
            adj = lake["adj_close"].to_numpy(dtype=float)
            assert np.array_equal(record["close"].to_numpy(dtype=float), close), f"{symbol}: close"
            tr = record["tr_index"].to_numpy(dtype=float)
            assert tr[0] == 1.0, f"{symbol}: tr_index[0] is {tr[0]}, not 1.0"
            inside = np.array([d <= through for d in days])
            assert np.isfinite(tr[inside]).all(), f"{symbol}: NaN tr_index on or before {through}"
            assert np.isnan(tr[~inside]).all(), (
                f"{symbol}: rows after {through} must be price-only (NaN tr_index)"
            )
            price_only += int((~inside).sum())
            k = int(inside.sum())
            gap = np.abs(tr[1:k] / tr[: k - 1] - adj[1:k] / adj[: k - 1])
            assert (gap <= 1e-12).all(), (
                f"{symbol}: tr_index ratio off adj_close ratio by {gap.max()}"
            )
            pairs += len(gap)
            for column in ("div_cash", "split_factor"):
                assert record[column].isna().all(), f"{symbol}: seed rows must not carry {column}"
            entry = entries[symbol]
            assert entry["source"] == "seed", f"{symbol}: source {entry['source']!r}"
            assert entry["status"] == "pending", f"{symbol}: status {entry['status']!r}"
            assert entry["status"] != "ok", f"{symbol}: a seeded symbol must not be served"
            assert entry["adjusted_through"] == through, f"{symbol}: {entry['adjusted_through']!r}"
            assert entry["first_date"] == days[0] and entry["last_date"] == days[-1], symbol
        assert pairs >= 2_000, f"only {pairs} day pairs checked"
        assert price_only >= 1, "no price-only row was checked"
        # Control: the index is not a copy of close on the fixture symbols that have adjustments.
        adjusted = [s for s, d in lakes["latest"].items() if d]
        for symbol in adjusted:
            record = pd.read_parquet(io.BytesIO(store.get(f"prices/{symbol}.parquet")))
            record = record.sort_values("date").reset_index(drop=True)
            close = record["close"].to_numpy(dtype=float)
            tr = record["tr_index"].to_numpy(dtype=float)
            ok = np.isfinite(tr)
            assert not np.allclose(tr[ok], close[ok] / close[0], rtol=1e-9), (
                f"{symbol}: tr_index equals close/close[0]; adj_close was not used"
            )

    def test_drifted_lake_uploads_nothing(tmp_path, tmp_path_factory):
        lakes = _lakes(tmp_path_factory)
        store_dir = tmp_path / "store"
        code, output = _run(lakes["drift"], store_dir, lakes["through"])
        assert code != 0, "seed accepted a lake with adj_close != close after --adjusted-through"
        assert "Traceback (most recent call last)" not in output, (
            f"crash, not a refusal:\n{output[-800:]}"
        )
        symbol, day = lakes["drift_symbol"], lakes["drift_day"]
        assert re.search(rf"\b{re.escape(symbol)}\b", output), f"message does not name {symbol}"
        assert day in output, f"message does not name the date {day}:\n{output[-800:]}"
        _assert_nothing_written(store_dir, "drifted lake")
        # A dry run over the drifted lake writes nothing either.
        _run(lakes["drift"], store_dir, lakes["through"], "--dry-run")
        _assert_nothing_written(store_dir, "drifted lake, dry run")

    def test_dry_run_reports_and_writes_nothing(tmp_path, tmp_path_factory):
        lakes = _lakes(tmp_path_factory)
        store_dir = tmp_path / "store"
        code, output = _run(lakes["clean"], store_dir, lakes["through"], "--dry-run")
        assert code == 0, f"dry run over the clean lake exited {code}:\n{output[-1500:]}"
        reported = 0
        for symbol, day in lakes["latest"].items():
            if day is None:
                continue
            pattern = re.compile(rf"(?<![A-Za-z0-9]){re.escape(symbol)}(?![A-Za-z0-9]).*{day}")
            assert any(pattern.search(line) for line in output.splitlines()), (
                f"dry run does not print the latest adjustment date {day} for {symbol}"
            )
            reported += 1
        assert reported >= 1, "no adjustment date was checked"
        _assert_nothing_written(store_dir, "dry run")

    def test_missing_or_small_lake_is_refused(tmp_path, tmp_path_factory):
        lakes = _lakes(tmp_path_factory)
        cases = {
            "missing path": lakes["missing"],
            "999 parquet files": lakes["short"],
            "three-file fixture lake": lakes["base"] / "lake_three",
        }
        cases["three-file fixture lake"].mkdir(exist_ok=True)
        for path in sorted(FIXTURE_LAKE.glob("*.parquet")):
            shutil.copyfile(path, cases["three-file fixture lake"] / path.name)
        for label, lake in cases.items():
            for extra in ((), ("--dry-run",)):
                store_dir = tmp_path / f"store_{label.split()[0]}_{len(extra)}"
                code, output = _run(lake, store_dir, lakes["through"], *extra)
                assert code != 0, f"{label} {extra}: the seed must exit non-zero"
                assert str(lake) in output, f"{label} {extra}: message does not name the lake path"
                assert "Traceback (most recent call last)" not in output, (
                    f"{label} {extra}: crashed instead of refusing:\n{output[-800:]}"
                )
                _assert_nothing_written(store_dir, label)
        assert not lakes["missing"].exists(), "the seed created the missing lake path"
        # The floor is exactly 1,000: the same lake with one more parquet file is accepted.
        code, output = _run(lakes["clean"], tmp_path / "store_floor", lakes["through"], "--dry-run")
        assert code == 0, f"a lake of exactly 1,000 parquet files was refused:\n{output[-800:]}"
