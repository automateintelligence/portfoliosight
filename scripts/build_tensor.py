"""Build one tensor (spec section 7) from a returns parquet.

Usage, from the repo root:
    python scripts/build_tensor.py --returns <parquet> --lookback <id> --asof YYYY-MM-DD
        --out <json> [--caps <json file>] [--nx N --ny N]

The returns parquet has a DatetimeIndex named `date` and one float column per fund id of daily
simple returns, NaN where the fund has no return. Its schema metadata may carry, under the key
`portfoliosight`, the universe name and per-fund catalog facts (as `scripts/make_fixtures.py`
writes them). The metadata's `last_close` is the close on the file's last day, so it is used
only when `--asof` is that day; for any other day the close is not known. A file without that
metadata still builds: a fund is taken as served when its last return is no more than three
XNYS sessions before `--asof` (spec 5.2) and described as an ETF from the seed, verified through
its own last return, with no last close.

`--caps` is a JSON list of {"id", "min", "max"} with null for the default rule. `--nx/--ny`
select the grid (48 x 32; the one fallback of spec 4.12 is 32 x 24).

Exit status 0 with a canonical-JSON tensor at --out; 2 with one line on stderr and no file when
the window is unavailable or the caps are invalid.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import timedelta
from pathlib import Path
from typing import cast

import pandas as pd
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # this checkout's package

from portfoliosight.engine.caps import CapsError  # noqa: E402
from portfoliosight.engine.optimize import NX  # noqa: E402
from portfoliosight.engine.stats import RISK_FREE_SOURCES  # noqa: E402
from portfoliosight.engine.surface import NY  # noqa: E402
from portfoliosight.engine.tensor import (  # noqa: E402
    FundInput,
    TensorInputs,
    WindowUnavailable,
    build_tensor,
    canonical_json,
)

METADATA_KEY = b"portfoliosight"
LOOKBACKS = ("1y", "2y", "3y", "5y", "10y", "ew")
DEFAULT_UNIVERSE = {"name": "Custom menu", "preset_id": None}
SERVED_WITHIN_SESSIONS = 3  # spec 5.2: verified through D - 3 trading days or later
CALENDAR_SPAN = timedelta(days=366)  # more than enough days to hold four sessions


def served_floor(asof: pd.Timestamp) -> pd.Timestamp:
    """The XNYS session three sessions before the last session on or before `asof`."""
    import exchange_calendars  # deferred: only a fund without catalog facts needs it

    end = asof.date()
    calendar = exchange_calendars.get_calendar(
        "XNYS", start=(end - CALENDAR_SPAN).isoformat(), end=end.isoformat()
    )
    sessions = pd.DatetimeIndex(calendar.sessions.tz_localize(None))
    return cast(pd.Timestamp, sessions[-(SERVED_WITHIN_SESSIONS + 1)])


def as_day(asof: str) -> pd.Timestamp:
    """`--asof` as a day; `ValueError` when it does not name one."""
    stamp = pd.Timestamp(asof)
    if not isinstance(stamp, pd.Timestamp):
        raise ValueError(f"asof must be a date, got {asof!r}")
    return stamp.normalize()


def default_status(last: pd.Timestamp | None, floor: pd.Timestamp) -> tuple[bool, str | None]:
    """Served or not, with the reason, for a fund the metadata says nothing about."""
    if last is None:
        return False, "no data"
    if last < floor:
        return False, f"no data since {last.date().isoformat()}"
    return True, None


def read_inputs(
    returns: Path, lookback: str, asof: str, caps: Path | None, nx: int, ny: int
) -> TensorInputs:
    """Everything a build needs, from the parquet and its metadata alone."""
    frame = pd.read_parquet(returns)
    raw = (pq.read_schema(returns).metadata or {}).get(METADATA_KEY)
    metadata = json.loads(raw) if raw else {}
    catalog = metadata.get("funds", {})
    day = as_day(asof)
    history = frame.loc[frame.index <= day]
    close_is_known = len(frame) > 0 and day == frame.index.max()
    floor: pd.Timestamp | None = None  # looked up for the first fund that needs it
    funds = []
    for fund in frame.columns:
        last = history[fund].last_valid_index()
        verified = asof if last is None else last.date().isoformat()
        entry = catalog.get(fund, {})
        if "served" in entry:
            served, reason = entry["served"], entry.get("catalog_reason")
        else:
            floor = served_floor(day) if floor is None else floor
            served, reason = default_status(last, floor)
        adjusted_through = entry.get("adjusted_through", verified)
        funds.append(
            FundInput(
                id=fund,
                name=entry.get("name", fund),
                kind=entry.get("kind", "etf"),
                source=entry.get("source", "seed"),
                adjusted_through=adjusted_through,
                fetched_at=entry.get("fetched_at", f"{adjusted_through}T00:00:00Z"),
                last_close=entry.get("last_close") if close_is_known else None,
                served=served,
                catalog_reason=reason,
            )
        )
    served = {fund.id for fund in funds if fund.served}
    rf_series: dict[str, pd.Series] = {
        symbol: frame.loc[:, symbol] for symbol in RISK_FREE_SOURCES if symbol in served
    }
    universe = metadata.get("universe", DEFAULT_UNIVERSE)
    return TensorInputs(
        funds=funds,
        returns=frame,
        lookback=lookback,
        asof=asof,
        universe_name=universe["name"],
        preset_id=universe["preset_id"],
        requested_bounds=None if caps is None else json.loads(caps.read_text(encoding="utf-8")),
        rf_series=rf_series,
        nx=nx,
        ny=ny,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build one tensor from a returns parquet.")
    parser.add_argument("--returns", type=Path, required=True, help="returns parquet")
    parser.add_argument("--lookback", choices=LOOKBACKS, required=True)
    parser.add_argument("--asof", required=True, help="YYYY-MM-DD; later rows are not used")
    parser.add_argument("--out", type=Path, required=True, help="tensor JSON to write")
    parser.add_argument("--caps", type=Path, help='JSON list of {"id", "min", "max"}')
    parser.add_argument("--nx", type=int, default=NX, help="risk columns")
    parser.add_argument("--ny", type=int, default=NY, help="return floors")
    args = parser.parse_args(argv)
    inputs = read_inputs(args.returns, args.lookback, args.asof, args.caps, args.nx, args.ny)
    try:
        tensor = build_tensor(inputs)
    except WindowUnavailable as exc:
        print(f"unavailable: {exc.reason} ({args.lookback} window)", file=sys.stderr)
        return 2
    except CapsError as exc:
        print(f"invalid caps: {exc}", file=sys.stderr)
        return 2
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(canonical_json(tensor) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
