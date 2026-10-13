"""A-PS-09 — tsp.gov rows are parsed only under the exact header.

Claim: the TSP provider parses the CSV only when its header is exactly the spec §5.5 column set
and order, maps each fund column to its TSP-* id with tr_index = price, div_cash = 0,
split_factor = 1, adjusted_through = last_date, and rejects any other header.

Pinned interface (the product must provide exactly this):
- `portfoliosight.data.providers.tsp.parse_tsp_csv(text: str) -> dict[str, pandas.DataFrame]`:
  keys are exactly the 16 TSP ids; each frame is in the provider format of spec §5.1 (tz-naive
  `DatetimeIndex` named `date`; columns `close`, `adj_close`, `div_cash`, `split_factor`), with
  `adj_close == close` (the price is the total-return index), `div_cash == 0`, `split_factor == 1`.
  Header cells are compared after stripping surrounding whitespace. Any other header raises a
  `ValueError` (or a subclass) whose message contains the EXPECTED column name at the first
  mismatching position, and no frames are returned.
- `portfoliosight.data.providers.tsp.TspProvider()` with `fetch_daily(symbol, start, end)` and
  `fetch_meta(symbol)`; both go through `requests` to
  `https://www.tsp.gov/data/fund-price-history.csv` with the query keys `startdate`, `enddate`
  (YYYY-MM-DD), `Lfunds=1`, `InvFunds=1`, `download=1` and a browser User-Agent ("Mozilla/5.0 ...").
  `fetch_daily` raises the same header error when the served CSV has a non-exact header.
  `fetch_meta(symbol)` returns an object with `.name` (display name, e.g. "C Fund"), `.kind`
  ("tsp") and `.last_date` (the last priced date; `adjusted_through` equals it because every
  returned row carries `adj_close`).
- The recorded TSP CSV slice of spec §10: the first `*.csv` under `tests/fixtures/` (sorted,
  recursive) whose file name contains `tsp`, raw as downloaded from tsp.gov, at least 5 data rows.
"""

from __future__ import annotations

import csv
import importlib
import io
import os
import re
import subprocess
import sys
from datetime import date
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

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
        pytest.fail(f"A-PS-09 red: cannot import {module}: {type(exc).__name__}: {exc}")


# Spec §5.5: column order of the tsp.gov CSV and the id of each fund column.
HEADER = [
    "Date",
    "L Income",
    "L 2030",
    "L 2035",
    "L 2040",
    "L 2045",
    "L 2050",
    "L 2055",
    "L 2060",
    "L 2065",
    "L 2070",
    "L 2075",
    "G Fund",
    "F Fund",
    "C Fund",
    "S Fund",
    "I Fund",
]
ID_OF = {
    "L Income": "TSP-LINC",
    "L 2030": "TSP-L2030",
    "L 2035": "TSP-L2035",
    "L 2040": "TSP-L2040",
    "L 2045": "TSP-L2045",
    "L 2050": "TSP-L2050",
    "L 2055": "TSP-L2055",
    "L 2060": "TSP-L2060",
    "L 2065": "TSP-L2065",
    "L 2070": "TSP-L2070",
    "L 2075": "TSP-L2075",
    "G Fund": "TSP-G",
    "F Fund": "TSP-F",
    "C Fund": "TSP-C",
    "S Fund": "TSP-S",
    "I Fund": "TSP-I",
}
NAME_OF = {v: k for k, v in ID_OF.items()}
TSP_URL = re.compile(r"https://www\.tsp\.gov/data/fund-price-history\.csv(\?.*)?$")


def _fixture_text() -> str:
    base = ROOT / "tests" / "fixtures"
    found = (
        sorted(p for p in base.rglob("*.csv") if "tsp" in p.name.lower()) if base.is_dir() else []
    )
    if not found:
        pytest.fail(
            "A-PS-09 red: no recorded TSP CSV slice (a *.csv whose name contains 'tsp') under "
            "tests/fixtures/"
        )
    return found[0].read_text(encoding="utf-8-sig")


def _cells(line: str) -> list[str]:
    return next(csv.reader([line]))


def _split(text: str) -> tuple[str, list[str]]:
    lines = text.splitlines()
    assert lines, "the TSP CSV text is empty"
    return lines[0], lines[1:]


def _expected(pd, text: str) -> dict[str, dict]:
    """Independent parse: {id: {Timestamp: price}} for every non-empty cell."""
    head, body = _split(text)
    assert [c.strip() for c in _cells(head.lstrip("﻿"))] == HEADER, (
        "the TSP CSV used by the test does not carry the spec §5.5 header"
    )
    out: dict[str, dict] = {ID_OF[c]: {} for c in HEADER[1:]}
    for row in csv.reader(io.StringIO("\n".join(body))):
        if not row or not row[0].strip():
            continue
        day = pd.Timestamp(row[0].strip())
        for col, cell in zip(HEADER[1:], row[1:], strict=False):
            if cell.strip():
                out[ID_OF[col]][day] = float(cell)
    return out


def _with_header(text: str, cells: list[str]) -> str:
    _, body = _split(text)
    return "\n".join([",".join(cells), *body]) + "\n"


def _swapped(text: str) -> tuple[str, str]:
    cells = list(HEADER)
    i, j = cells.index("L 2040"), cells.index("F Fund")
    cells[i], cells[j] = cells[j], cells[i]
    return _with_header(text, cells), "L 2040"


def _renamed(text: str) -> tuple[str, str]:
    cells = ["C Fund Price" if c == "C Fund" else c for c in HEADER]
    return _with_header(text, cells), "C Fund"


def _check_frame(pd, frame, want: dict, label: str) -> int:
    assert isinstance(frame, pd.DataFrame), f"{label}: not a DataFrame ({type(frame)})"
    assert isinstance(frame.index, pd.DatetimeIndex), f"{label}: index is not a DatetimeIndex"
    assert frame.index.tz is None, f"{label}: index must be tz-naive"
    assert frame.index.name == "date", f"{label}: index must be named 'date'"
    for col in ("close", "adj_close", "div_cash", "split_factor"):
        assert col in frame.columns, f"{label}: column {col} missing"
    priced = frame[frame["close"].notna()]
    assert len(priced) == len(want), f"{label}: {len(priced)} priced rows, CSV has {len(want)}"
    assert len(want) > 0, f"{label}: the CSV has no price for this fund"
    assert list(priced.index) == sorted(want), f"{label}: dates differ from the CSV"
    for day, price in want.items():
        got = float(priced.at[day, "close"])
        assert abs(got - price) <= 1e-9, f"{label} {day.date()}: close {got} != CSV cell {price}"
        adj = float(priced.at[day, "adj_close"])
        assert abs(adj - price) <= 1e-9, f"{label} {day.date()}: adj_close {adj} != price {price}"
    assert not priced["adj_close"].isna().any(), f"{label}: adj_close missing on a priced row"
    assert (priced["div_cash"] == 0).all(), f"{label}: div_cash must be 0 on every row"
    assert (priced["split_factor"] == 1).all(), f"{label}: split_factor must be 1 on every row"
    return len(want)


class _Server:
    """Replays one CSV body for every tsp.gov request and records what was asked."""

    def __init__(self, responses, body: str):
        self.requests: list = []
        self.mock = responses.RequestsMock(assert_all_requests_are_fired=False)
        self.body = body
        self.mock.add_callback(responses.GET, TSP_URL, callback=self._serve)

    def _serve(self, request):
        self.requests.append(request)
        return (200, {"Content-Type": "text/csv"}, self.body)

    def __enter__(self):
        self.mock.start()
        return self

    def __exit__(self, *exc):
        self.mock.stop()
        self.mock.reset()
        return False


def _provider():
    mod = _need("portfoliosight.data.providers.tsp")
    cls = getattr(mod, "TspProvider", None)
    assert cls is not None, "portfoliosight.data.providers.tsp.TspProvider is missing"
    return cls()


def _parser():
    mod = _need("portfoliosight.data.providers.tsp")
    fn = getattr(mod, "parse_tsp_csv", None)
    assert callable(fn), "portfoliosight.data.providers.tsp.parse_tsp_csv is missing"
    return fn


if _OUTER:

    def test_a_ps_09_in_project_venv():
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
        assert proc.returncode == 0, "A-PS-09 is red inside the project virtualenv (output above)"

else:

    def test_recorded_slice_carries_the_exact_header():
        pd = _need("pandas")
        text = _fixture_text()
        want = _expected(pd, text)
        assert len(want) == 16
        assert len(want["TSP-C"]) >= 5, "the recorded TSP slice needs at least 5 priced rows"

    def test_exact_header_fetch_daily_all_16_ids():
        pd = _need("pandas")
        responses = _need("responses")
        text = _fixture_text()
        want = _expected(pd, text)
        days = sorted({d for series in want.values() for d in series})
        provider = _provider()
        cells = 0
        with _Server(responses, text) as server:
            for name in HEADER[1:]:
                symbol = ID_OF[name]
                try:
                    frame = provider.fetch_daily(symbol, days[0].date(), days[-1].date())
                except Exception as exc:
                    pytest.fail(f"A-PS-09 red: fetch_daily({symbol}) raised {exc!r}")
                cells += _check_frame(pd, frame, want[symbol], f"fetch_daily({symbol})")
            assert server.requests, "fetch_daily never asked www.tsp.gov for the CSV"
            for request in server.requests:
                agent = request.headers.get("User-Agent", "")
                assert "Mozilla/5.0" in agent, f"User-Agent is not browser-like: {agent!r}"
                assert not agent.lower().startswith("python-requests/"), agent
                assert not agent.lower().startswith("curl/"), agent
                assert "python-requests" not in agent.lower(), agent
                query = parse_qs(urlsplit(request.url).query)
                assert query.get("Lfunds") == ["1"], f"Lfunds=1 missing from {request.url}"
                assert query.get("InvFunds") == ["1"], f"InvFunds=1 missing from {request.url}"
                assert query.get("download") == ["1"], f"download=1 missing from {request.url}"
                for key in ("startdate", "enddate"):
                    value = (query.get(key) or [""])[0]
                    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", value), f"{key} bad in {request.url}"
        assert cells >= 16 * 5, f"only {cells} price cells were checked"

    def test_display_names_and_last_date():
        pd = _need("pandas")
        responses = _need("responses")
        text = _fixture_text()
        want = _expected(pd, text)
        provider = _provider()
        names = {}
        with _Server(responses, text):
            for symbol in NAME_OF:
                try:
                    meta = provider.fetch_meta(symbol)
                except Exception as exc:
                    pytest.fail(f"A-PS-09 red: fetch_meta({symbol}) raised {exc!r}")
                assert meta is not None, f"fetch_meta({symbol}) returned None"
                names[symbol] = meta.name
                assert meta.kind == "tsp", f"{symbol}: kind {meta.kind!r}"
                last = pd.Timestamp(meta.last_date).normalize()
                assert last == max(want[symbol]), (
                    f"{symbol}: last_date {last.date()} is not the last priced date of the CSV"
                )
        assert names == NAME_OF
        assert names["TSP-G"] == "G Fund" and names["TSP-L2030"] == "L 2030"
        assert names["TSP-LINC"] == "L Income"
        assert len(set(names.values())) == 16

    def test_parser_maps_columns_and_follows_its_input():
        pd = _need("pandas")
        np = _need("numpy")
        parse = _parser()
        text = _fixture_text()
        want = _expected(pd, text)
        frames = parse(text)
        assert set(frames) == set(NAME_OF), f"ids produced: {sorted(frames)}"
        for symbol in NAME_OF:
            _check_frame(pd, frames[symbol], want[symbol], f"parse_tsp_csv[{symbol}]")
        some_day = sorted(want["TSP-C"])[len(want["TSP-C"]) // 2]
        c_col = HEADER.index("C Fund")
        row = next(
            r
            for r in csv.reader(io.StringIO(text))
            if r and r[0].strip() not in ("", "Date") and pd.Timestamp(r[0].strip()) == some_day
        )
        assert float(frames["TSP-C"].at[some_day, "adj_close"]) == float(row[c_col])
        assert float(frames["TSP-C"].at[some_day, "adj_close"]) != float(row[c_col - 1])

        # A CSV the product has never seen: the output must follow the cells, column by column.
        rng = np.random.default_rng(909)
        dates = ["2031-03-03", "2031-03-04", "2031-03-05", "2031-03-06"]
        lines = [",".join(HEADER)]
        for day in dates:
            lines.append(",".join([day, *[f"{x:.4f}" for x in rng.uniform(10, 90, size=16)]]))
        synthetic = "\n".join(lines) + "\n"
        want_syn = _expected(pd, synthetic)
        got_syn = parse(synthetic)
        assert set(got_syn) == set(NAME_OF)
        checked = 0
        for symbol in NAME_OF:
            checked += _check_frame(pd, got_syn[symbol], want_syn[symbol], f"synthetic[{symbol}]")
        assert checked == 64

    def test_non_exact_headers_are_rejected_without_rows():
        responses = _need("responses")
        parse = _parser()
        text = _fixture_text()
        double = [
            "L 2035 X" if c == "L 2035" else "S Fund X" if c == "S Fund" else c for c in HEADER
        ]
        variants = [
            ("swapped", *_swapped(text), None),
            ("renamed", *_renamed(text), None),
            ("two renamed", _with_header(text, double), "L 2035", "S Fund"),
        ]
        provider = _provider()
        rejected = 0
        for label, bad, first, later in variants:
            produced = None
            with pytest.raises(ValueError) as caught:
                produced = parse(bad)
            # Must-not-contain: rows produced from a non-exact header.
            assert produced is None, f"{label}: the parser returned frames for a bad header"
            message = str(caught.value)
            assert first in message, f"{label}: error {message!r} does not name column {first!r}"
            if later is not None:
                assert later not in message, (
                    f"{label}: error {message!r} names {later!r}, not only the first mismatch"
                )
            frame = None
            with _Server(responses, bad) as server:
                with pytest.raises(ValueError):
                    frame = provider.fetch_daily("TSP-C", date(2026, 1, 2), date(2026, 1, 30))
                assert server.requests, f"{label}: fetch_daily did not request the CSV"
            assert frame is None, f"{label}: fetch_daily returned rows for a bad header"
            rejected += 1
        assert rejected == 3
