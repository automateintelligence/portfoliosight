#!/usr/bin/env python3
"""Generate the three-symbol fixture lake of spec section 10 (seeded, synthetic, no real prices).

Each file has the QSE lake's columns ``date, open, high, low, close, adj_close, volume`` and
dividend-style back-adjustments: ``adj_close`` differs from ``close`` on every row before the
last ex-date and equals it from that day on, so the rows after the last adjustment are
price-only, as in the real lake. An earlier ex-date makes the adjusted series differ from the
raw one in shape, not only in level.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
FIRST_DAY, LAST_DAY = "2025-01-02", "2026-03-13"
# symbol -> (start price, daily volatility, [(ex-date, cash per share)], numpy seed)
SYMBOLS: dict[str, tuple[float, float, list[tuple[str, float]], int]] = {
    "VTI": (290.0, 0.010, [("2025-09-26", 0.91), ("2025-12-22", 0.95)], 4101),
    "AAPL": (240.0, 0.016, [("2025-11-10", 0.26), ("2026-02-09", 0.26)], 4102),
    "SGOV": (100.3, 0.0002, [("2026-01-02", 0.34), ("2026-02-02", 0.33)], 4103),
}


def build(symbol: str) -> pd.DataFrame:
    start, volatility, dividends, seed = SYMBOLS[symbol]
    rng = np.random.default_rng(seed)
    days = pd.bdate_range(FIRST_DAY, LAST_DAY)
    close = np.round(start * np.cumprod(1.0 + rng.normal(0.0003, volatility, len(days))), 2)
    spread = np.abs(rng.normal(0.0, volatility / 2, len(days)))
    factor = np.ones(len(days))
    for ex_date, cash in dividends:
        ex = int(np.searchsorted(days.values, np.datetime64(ex_date)))
        factor[:ex] *= 1.0 - cash / close[ex - 1]
    adj_close = np.where(factor == 1.0, close, np.round(close * factor, 6))
    return pd.DataFrame(
        {
            "date": days.to_numpy().astype("datetime64[ns]"),
            "open": np.round(close * (1.0 - spread / 2), 2),
            "high": np.round(close * (1.0 + spread), 2),
            "low": np.round(close * (1.0 - spread), 2),
            "close": close,
            "adj_close": adj_close,
            "volume": rng.integers(1_000_000, 30_000_000, len(days)).astype("int64"),
        }
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=REPO_ROOT / "tests" / "fixtures" / "lake")
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    for symbol in SYMBOLS:
        frame = build(symbol)
        frame.to_parquet(args.out / f"{symbol}.parquet", index=False)
        differs = frame["adj_close"] != frame["close"]
        latest = str(frame.loc[differs, "date"].iloc[-1])[:10]
        print(f"{symbol}: {len(frame)} rows, latest adjustment {latest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
