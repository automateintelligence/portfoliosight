"""A-PS-05 — missing prices stay missing.

Claim: the returns builder leaves a fund's return NaN on every day it has no price, uses the union
of all funds' dates as the calendar, and a window's sample is exactly the intersection of included
funds' return dates; no value is forward-filled, interpolated or back-filled.

Pinned interface (the product must provide exactly this):
- `portfoliosight.data.returns.build_returns(records) -> pandas.DataFrame`: `records` maps a fund
  id to its canonical record frame (columns `date, close, tr_index, div_cash, split_factor`). The
  result has a tz-naive `DatetimeIndex` named `date` holding the sorted union of all records'
  dates and one float column per fund id; the value on day t is `tr_index_t / tr_index_{t-1} - 1`
  where t-1 is the previous day OF THAT CALENDAR, and NaN when the fund has no price on t or t-1.
- `portfoliosight.data.returns.window_sample(returns, funds, start, end) -> pandas.DataFrame`:
  the rows of `returns[funds]` dated `start <= date <= end` (`datetime.date`, inclusive) on which
  every listed fund has a return; nothing else, nothing filled.
"""

from __future__ import annotations

import contextlib
import importlib
import os
import subprocess
import sys
from datetime import timedelta
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
        pytest.fail(f"A-PS-05 red: cannot import {module}: {type(exc).__name__}: {exc}")


N_DAYS = 300
GAP = range(20, 25)  # B has no price on these five interior days
C_START = 60  # C's first price is 60 days after A's and B's
_MISSING = object()


class _FillUsed(AssertionError):
    pass


@contextlib.contextmanager
def _no_filling(used: list):
    """Make every pandas fill path raise while the product code runs."""
    pd = _need("pandas")
    saved = []

    def patch(cls, name, replacement):
        saved.append((cls, name, cls.__dict__.get(name, _MISSING)))
        setattr(cls, name, replacement)

    def banned(name):
        def method(self, *args, **kwargs):
            used.append(name)
            raise _FillUsed(f"pandas {name}() was called while building returns")

        return method

    def guarded(name, original, keyword):
        def method(self, *args, **kwargs):
            if kwargs.get(keyword) is not None:
                used.append(f"{name}({keyword}={kwargs[keyword]!r})")
                raise _FillUsed(f"pandas {name}({keyword}=...) was called while building returns")
            return original(self, *args, **kwargs)

        return method

    for cls in (pd.DataFrame, pd.Series):
        for name in ("ffill", "bfill", "interpolate", "pad", "backfill", "_pad_or_backfill"):
            if hasattr(cls, name):
                patch(cls, name, banned(f"{cls.__name__}.{name}"))
        for name, keyword in (
            ("fillna", "method"),
            ("reindex", "method"),
            ("pct_change", "fill_method"),
        ):
            patch(cls, name, guarded(f"{cls.__name__}.{name}", getattr(cls, name), keyword))
    try:
        yield
    finally:
        for cls, name, original in reversed(saved):
            if original is _MISSING:
                delattr(cls, name)
            else:
                setattr(cls, name, original)


def _record(days, tr):
    pd = _need("pandas")
    np = _need("numpy")
    tr = np.asarray(tr, dtype=float)
    return pd.DataFrame(
        {
            "date": pd.DatetimeIndex(days),
            "close": 50.0 * tr / tr[0],
            "tr_index": tr / tr[0],
            "div_cash": np.full(len(tr), np.nan),
            "split_factor": np.full(len(tr), np.nan),
        }
    )


def _make(seed: int, keep: dict[str, list[int]]):
    """Records over one business-day grid; `keep[fund]` lists the grid positions it has a price."""
    pd = _need("pandas")
    np = _need("numpy")
    grid = pd.bdate_range("2024-01-02", periods=N_DAYS)
    rng = np.random.default_rng(seed)
    records, levels = {}, {}
    for fund, positions in keep.items():
        walk = np.cumprod(1.0 + rng.normal(0.0004, 0.011, N_DAYS))
        levels[fund] = {grid[i]: float(walk[i] / walk[positions[0]]) for i in positions}
        records[fund] = _record([grid[i] for i in positions], [walk[i] for i in positions])
    return grid, records, levels


def _reference(levels: dict) -> tuple[list, dict]:
    """Independent rule: union calendar; a return exists only with a price on t and on t-1."""
    calendar = sorted(set().union(*[set(v) for v in levels.values()]))
    expected = {}
    for fund, level in levels.items():
        expected[fund] = {
            calendar[i]: level[calendar[i]] / level[calendar[i - 1]] - 1.0
            for i in range(1, len(calendar))
            if calendar[i] in level and calendar[i - 1] in level
        }
    return calendar, expected


def _build(records, order):
    returns_mod = _need("portfoliosight.data.returns")
    used: list = []
    with _no_filling(used):
        pd = _need("pandas")
        with pytest.raises(_FillUsed):  # control: the guard is live
            pd.Series([1.0, None]).ffill()
        used.clear()
        try:
            frame = returns_mod.build_returns({fund: records[fund] for fund in order})
        except _FillUsed as exc:
            pytest.fail(f"A-PS-05: {exc}")
        except Exception as exc:
            pytest.fail(f"A-PS-05 red: build_returns raised {exc!r}")
    assert used == [], f"fill methods reached from build_returns: {used}"
    return frame


def _sample(frame, funds, start, end):
    returns_mod = _need("portfoliosight.data.returns")
    used: list = []
    with _no_filling(used):
        try:
            sample = returns_mod.window_sample(frame, list(funds), start, end)
        except _FillUsed as exc:
            pytest.fail(f"A-PS-05: {exc}")
        except Exception as exc:
            pytest.fail(f"A-PS-05 red: window_sample raised {exc!r}")
    assert used == [], f"fill methods reached from window_sample: {used}"
    return sample


def _check_returns(frame, calendar, expected) -> int:
    pd = _need("pandas")
    np = _need("numpy")
    assert isinstance(frame, pd.DataFrame) and isinstance(frame.index, pd.DatetimeIndex)
    assert frame.index.tz is None, "returns index must be tz-naive"
    assert list(frame.index) == calendar, (
        f"calendar has {len(frame.index)} days, the union of the funds' dates has {len(calendar)}"
    )
    assert sorted(frame.columns) == sorted(expected), f"columns {list(frame.columns)}"
    cells = 0
    for fund, want in expected.items():
        values = frame[fund].to_numpy(dtype=float)
        for day, value in zip(calendar, values):
            if day in want:
                assert np.isfinite(value), f"{fund} {day.date()}: return missing"
                assert abs(value - want[day]) <= 1e-12, (
                    f"{fund} {day.date()}: {value} != {want[day]}"
                )
            else:
                assert not np.isfinite(value), (
                    f"{fund} {day.date()}: finite return {value} on a day without one "
                    "(no price that day or the day before)"
                )
            cells += 1
    return cells


def _check_sample(sample, frame, expected, funds, start, end) -> int:
    np = _need("numpy")
    want_days = sorted(
        set.intersection(*[set(expected[f]) for f in funds])
        & {d for d in frame.index if start <= d.date() <= end}
    )
    assert list(sample.index) == want_days, (
        f"window {start}..{end} over {funds}: {len(sample)} rows, expected {len(want_days)}"
    )
    assert sorted(sample.columns) == sorted(funds), f"sample columns {list(sample.columns)}"
    for fund in funds:
        got = sample[fund].to_numpy(dtype=float)
        want = np.array([expected[fund][d] for d in want_days])
        assert np.isfinite(got).all(), f"{fund}: NaN inside the window sample"
        assert np.array_equal(got, frame.loc[want_days, fund].to_numpy(dtype=float)), fund
        assert np.allclose(got, want, rtol=0.0, atol=1e-12), f"{fund}: sample values altered"
    return len(want_days)


if _OUTER:

    def test_a_ps_05_in_project_venv():
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
        assert proc.returncode == 0, "A-PS-05 is red inside the project virtualenv (output above)"

else:

    def _three_records():
        keep = {
            "A": list(range(N_DAYS)),
            "B": [i for i in range(N_DAYS) if i not in GAP],
            "C": list(range(C_START, N_DAYS)),
        }
        return _make(5, keep), keep

    def test_calendar_is_the_union_and_gaps_stay_nan():
        np = _need("numpy")
        (grid, records, levels), keep = _three_records()
        calendar, expected = _reference(levels)
        assert calendar == list(grid), "test setup: A must cover every day"
        cells = 0
        for order in (("A", "B", "C"), ("C", "B", "A"), ("B", "C", "A")):
            frame = _build(records, order)
            cells += _check_returns(frame, calendar, expected)
        assert cells == 3 * 3 * N_DAYS, f"checked {cells} cells"

        frame = _build(records, ("C", "A", "B"))
        # (2) spelled out: B on the five gap days and on the first day after; C before its start.
        b_nan = [grid[i] for i in list(GAP) + [GAP[-1] + 1]]
        assert len(b_nan) == 6
        for day in b_nan:
            assert not np.isfinite(frame.loc[day, "B"]), f"B has a return on {day.date()}"
        assert np.isfinite(frame.loc[grid[GAP[-1] + 2], "B"]), (
            "B must resume two days after the gap"
        )
        assert np.isfinite(frame.loc[grid[GAP[0] - 1], "B"]), "B has a return just before the gap"
        for i in range(0, C_START + 1):
            assert not np.isfinite(frame.loc[grid[i], "C"]), f"C has a return on {grid[i].date()}"
        assert np.isfinite(frame.loc[grid[C_START + 1], "C"]), "C's first return is its second day"
        assert not np.isfinite(frame.loc[grid[0], "A"]), "A has no return on the first day"
        assert int(np.isfinite(frame["A"].to_numpy(dtype=float)).sum()) == N_DAYS - 1
        # A carried-forward price would show as an exact zero return on a gap day.
        assert not (frame.loc[[grid[i] for i in GAP], "B"] == 0.0).any(), "gap days were filled"

    def test_window_sample_is_the_intersection_of_return_dates():
        (grid, records, levels), keep = _three_records()
        calendar, expected = _reference(levels)
        frame = _build(records, ("A", "B", "C"))
        first, last = grid[0].date(), grid[-1].date()
        gap_days = {grid[i] for i in GAP}

        # (3) as the spec states it: the window holds the gap, all three funds included.
        sample = _sample(frame, ("A", "B", "C"), first, last)
        shared_prices = set.intersection(*[set(levels[f]) for f in ("A", "B", "C")])
        assert len(sample) == len(shared_prices) - 1, (
            f"{len(sample)} rows; expected |shared dates| - 1 = {len(shared_prices) - 1}"
        )
        assert len(sample) == N_DAYS - C_START - 1
        assert not gap_days & set(sample.index), "a gap day is in the sample"
        _check_sample(sample, frame, expected, ("A", "B", "C"), first, last)

        # The same window over A and B only: the gap now falls inside the shared history, so the
        # five gap days and the day after them (no return for B) must all be absent.
        pair = _sample(frame, ("A", "B"), first, last)
        assert len(pair) == (N_DAYS - 1) - len(GAP) - 1, f"{len(pair)} rows in the A+B sample"
        assert not gap_days & set(pair.index), "a gap day is in the A+B sample"
        assert grid[GAP[-1] + 1] not in set(pair.index), "the day after the gap is in the sample"
        assert grid[GAP[-1] + 2] in set(pair.index) and grid[GAP[0] - 1] in set(pair.index)
        _check_sample(pair, frame, expected, ("A", "B"), first, last)

        # Windows that start or end inside the gap, and single-fund windows.
        rows = 0
        for lo, hi in ((GAP[0] + 2, 200), (5, GAP[0] + 2), (C_START - 3, C_START + 30), (0, 19)):
            for funds in (("A", "B"), ("A", "B", "C"), ("B",), ("C", "A")):
                start, end = grid[lo].date(), grid[hi].date()
                got = _sample(frame, funds, start, end)
                rows += _check_sample(got, frame, expected, funds, start, end)
                assert not gap_days & set(got.index) or "B" not in funds
        assert rows >= 500, f"only {rows} sample rows checked"
        # Inclusive bounds, and nothing outside them.
        one = _sample(frame, ("A",), grid[100].date(), grid[100].date())
        assert list(one.index) == [grid[100]], "window bounds must be inclusive"
        before = _sample(frame, ("A",), first - timedelta(days=30), first - timedelta(days=1))
        assert len(before) == 0, "rows returned for a window before any data"

    def test_property_random_gaps_never_get_a_return():
        np = _need("numpy")
        cells = rows = 0
        for seed in range(12):
            rng = np.random.default_rng(1000 + seed)
            b_missing = {
                int(i) for i in rng.choice(np.arange(1, N_DAYS - 1), size=25, replace=False)
            }
            c_start = int(rng.integers(10, 150))
            c_missing = {
                int(i) for i in rng.choice(np.arange(c_start + 1, N_DAYS), size=8, replace=False)
            }
            keep = {
                "A": list(range(N_DAYS)),
                "B": [i for i in range(N_DAYS) if i not in b_missing],
                "C": [i for i in range(c_start, N_DAYS) if i not in c_missing],
            }
            grid, records, levels = _make(2000 + seed, keep)
            calendar, expected = _reference(levels)
            order = [str(f) for f in rng.permutation(["A", "B", "C"])]
            frame = _build(records, order)
            cells += _check_returns(frame, calendar, expected)
            lo = int(rng.integers(0, 120))
            hi = int(rng.integers(lo + 60, N_DAYS))
            start, end = grid[lo].date(), grid[hi].date()
            sample = _sample(frame, ("A", "B", "C"), start, end)
            rows += _check_sample(sample, frame, expected, ("A", "B", "C"), start, end)
            banned = {grid[i] for i in b_missing | c_missing}
            assert not banned & set(sample.index), f"seed {seed}: a missing-price day was sampled"
        assert cells == 12 * 3 * N_DAYS and rows >= 300, f"checked {cells} cells, {rows} rows"
