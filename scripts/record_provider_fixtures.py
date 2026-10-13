#!/usr/bin/env python3
"""Record the provider fixtures of spec section 10, live, once.

Writes raw Tiingo rows for the split windows (AAPL, NVDA, USO) and the full histories (VTI,
VBIAX) and each symbol's meta object. Needs ``TIINGO_API_KEY`` in the environment; the key is
never written. Cost: ten Tiingo requests.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from portfoliosight.data.providers.tiingo import TiingoProvider  # noqa: E402

FULL_HISTORY_START = date(1990, 1, 1)
PRICE_WINDOWS: dict[str, tuple[str, date, date | None]] = {
    # file stem -> (symbol, start, end); two months around each split of spec 4.1
    "AAPL_2020-08": ("AAPL", date(2020, 8, 1), date(2020, 9, 30)),
    "NVDA_2024-06": ("NVDA", date(2024, 5, 10), date(2024, 7, 10)),
    "USO_2020-04": ("USO", date(2020, 4, 1), date(2020, 5, 29)),
    "VTI": ("VTI", FULL_HISTORY_START, None),
    "VBIAX": ("VBIAX", FULL_HISTORY_START, None),
}


def _write_rows(path: Path, rows: list[dict]) -> None:
    lines = ",\n".join(json.dumps(row, separators=(",", ":")) for row in rows)
    path.write_text(f"[\n{lines}\n]\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=REPO_ROOT / "tests" / "fixtures")
    parser.add_argument("--skip-tiingo", action="store_true")
    args = parser.parse_args(argv)

    if not args.skip_tiingo:
        provider_dir = args.out / "provider"
        provider_dir.mkdir(parents=True, exist_ok=True)
        provider = TiingoProvider()
        for stem, (symbol, start, end) in PRICE_WINDOWS.items():
            rows = provider.fetch_daily_raw(symbol, start, end)
            if not rows:
                print(f"{symbol}: no rows returned", file=sys.stderr)
                return 1
            _write_rows(provider_dir / f"{stem}.json", rows)
            meta = provider.fetch_meta_raw(symbol)
            (provider_dir / f"meta_{symbol}.json").write_text(
                json.dumps(meta, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            print(f"{symbol}: {len(rows)} rows {rows[0]['date'][:10]}..{rows[-1]['date'][:10]}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
