"""Generate the synthetic 23-fund returns fixture, `tests/fixtures/synthetic_23.parquet`.

Daily simple returns for the 23 funds of the 2017 guide portfolio (Step 2) on XNYS sessions from
2005-01-03 to 2026-10-12, drawn once from a seeded three-factor model (equity, interest rates,
international). Nothing here is market data: the tickers only name the columns. Coverage is
partial on purpose, so the stress windows have something to show: six funds start after
2008-09-01 (one of them inside the 2008 window). Every fund runs to the last session and is
served, so no view of this menu sets a fund aside.

The file is the returns parquet of the tensor build CLI (`DatetimeIndex` named `date`, one float
column per fund, NaN where the fund has no return). Its schema metadata carries, under the key
`portfoliosight`, the universe name and the per-fund catalog facts a build needs, so
`scripts/build_tensor.py --returns <this file>` reproduces the UI fixture with no other input.

Usage: python scripts/make_fixtures.py [--out PATH]
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

import exchange_calendars as xcals
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

SEED = 20171013
FIRST_SESSION = "2005-01-03"
LAST_SESSION = "2026-10-12"
DEFAULT_OUT = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "synthetic_23.parquet"
METADATA_KEY = b"portfoliosight"
TRADING_DAYS = 252
FETCHED_AT = "2026-10-13T09:05:11Z"
UNIVERSE = {"name": "The 2017 guide portfolio", "preset_id": "guide2017"}

# Annual factor premia and volatilities: equity, interest rates, international.
FACTOR_MEAN = np.array([0.055, 0.010, 0.010])
FACTOR_VOL = np.array([0.160, 0.045, 0.080])
CARRY = 0.030  # annual return every fund earns before factor premia


@dataclass(frozen=True)
class Fund:
    id: str
    name: str
    kind: str
    betas: tuple[float, float, float]
    idio: float  # annual idiosyncratic volatility
    start: str = FIRST_SESSION


FUNDS = (
    Fund("VTI", "Vanguard Total Stock Market ETF", "etf", (1.00, 0.00, 0.00), 0.020),
    Fund("VTV", "Vanguard Value ETF", "etf", (0.92, 0.00, 0.00), 0.040),
    Fund("VOE", "Vanguard Mid-Cap Value ETF", "etf", (1.05, 0.00, 0.00), 0.050),
    Fund("VB", "Vanguard Small-Cap ETF", "etf", (1.15, 0.00, 0.00), 0.060),
    Fund("VBR", "Vanguard Small-Cap Value ETF", "etf", (1.15, 0.00, 0.00), 0.070),
    Fund("VEA", "Vanguard FTSE Developed Markets ETF", "etf", (0.85, 0.00, 0.60), 0.050),
    Fund(
        "SCHF",
        "Schwab International Equity ETF",
        "etf",
        (0.85, 0.00, 0.60),
        0.050,
        start="2008-11-03",
    ),
    Fund("VWO", "Vanguard FTSE Emerging Markets ETF", "etf", (1.00, 0.00, 1.20), 0.080),
    Fund("VNQ", "Vanguard Real Estate ETF", "etf", (1.00, 0.50, 0.00), 0.100),
    Fund(
        "VBIAX",
        "Vanguard Balanced Index Fund Admiral Shares",
        "mutual_fund",
        (0.60, 0.40, 0.00),
        0.010,
    ),
    Fund(
        "SCHO",
        "Schwab Short-Term U.S. Treasury ETF",
        "etf",
        (0.00, 0.08, 0.00),
        0.0035,
        start="2009-08-06",
    ),
    Fund("BND", "Vanguard Total Bond Market ETF", "etf", (0.00, 1.00, 0.00), 0.008),
    Fund("AGG", "iShares Core U.S. Aggregate Bond ETF", "etf", (0.00, 1.00, 0.00), 0.008),
    Fund("TIP", "iShares TIPS Bond ETF", "etf", (0.00, 1.10, 0.00), 0.025),
    Fund(
        "VTIP",
        "Vanguard Short-Term Inflation-Protected Securities ETF",
        "etf",
        (0.00, 0.60, 0.00),
        0.015,
        start="2012-10-16",
    ),
    Fund(
        "LQD",
        "iShares iBoxx $ Investment Grade Corporate Bond ETF",
        "etf",
        (0.12, 1.50, 0.00),
        0.025,
    ),
    Fund(
        "VWOB",
        "Vanguard Emerging Markets Government Bond ETF",
        "etf",
        (0.15, 1.20, 0.35),
        0.025,
        start="2013-06-04",
    ),
    Fund(
        "PCY",
        "Invesco Emerging Markets Sovereign Debt ETF",
        "etf",
        (0.18, 1.30, 0.35),
        0.030,
    ),
    Fund("EFA", "iShares MSCI EAFE ETF", "etf", (0.85, 0.00, 0.60), 0.050),
    Fund(
        "LTPZ",
        "PIMCO 15+ Year U.S. TIPS Index ETF",
        "etf",
        (0.00, 1.55, 0.00),
        0.025,
        start="2009-09-03",
    ),
    Fund("EDV", "Vanguard Extended Duration Treasury ETF", "etf", (-0.05, 1.65, 0.00), 0.020),
    Fund("VGSTX", "Vanguard STAR Fund", "mutual_fund", (0.62, 0.30, 0.10), 0.015),
    Fund(
        "DBJP",
        "Xtrackers MSCI Japan Hedged Equity ETF",
        "etf",
        (0.75, 0.00, 0.00),
        0.110,
        start="2011-06-09",
    ),
)


def sessions() -> pd.DatetimeIndex:
    """XNYS sessions of the fixture's span, tz-naive, named `date`."""
    calendar = xcals.get_calendar("XNYS", start="2005-01-01", end="2026-12-31")
    index = calendar.sessions_in_range(FIRST_SESSION, LAST_SESSION)
    return pd.DatetimeIndex(index.tz_localize(None), name="date")


def build_frame() -> pd.DataFrame:
    """The seeded return matrix: one column per fund, NaN outside the fund's own history."""
    index = sessions()
    rng = np.random.default_rng(SEED)
    daily_vol = FACTOR_VOL / np.sqrt(TRADING_DAYS)
    factors = FACTOR_MEAN / TRADING_DAYS + rng.normal(size=(len(index), 3)) * daily_vol
    noise = rng.normal(size=(len(index), len(FUNDS)))
    columns = {}
    for position, fund in enumerate(FUNDS):
        series = (
            CARRY / TRADING_DAYS
            + factors @ np.array(fund.betas)
            + noise[:, position] * fund.idio / np.sqrt(TRADING_DAYS)
        )
        columns[fund.id] = np.where(index >= pd.Timestamp(fund.start), series, np.nan)
    return pd.DataFrame(columns, index=index, dtype="float64")


def build_metadata(frame: pd.DataFrame) -> dict:
    """Universe name and per-fund catalog facts, as the build CLI reads them."""
    funds = {}
    for fund in FUNDS:
        growth = float(np.prod(1.0 + frame[fund.id].dropna().to_numpy()))
        funds[fund.id] = {
            "name": fund.name,
            "kind": fund.kind,
            "source": "tiingo" if fund.kind == "mutual_fund" else "seed+tiingo",
            "adjusted_through": LAST_SESSION,
            "fetched_at": FETCHED_AT,
            "last_close": round(25.0 * growth, 2),
            "served": True,
            "catalog_reason": None,
        }
    return {"universe": UNIVERSE, "funds": funds}


def write(out: Path) -> None:
    frame = build_frame()
    table = pa.Table.from_pandas(frame, preserve_index=True)
    metadata = dict(table.schema.metadata or {})
    document = json.dumps(build_metadata(frame), sort_keys=True, separators=(",", ":"))
    metadata[METADATA_KEY] = document.encode()
    out.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table.replace_schema_metadata(metadata), out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write the synthetic 23-fund returns fixture.")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="parquet file to write")
    args = parser.parse_args(argv)
    write(args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
