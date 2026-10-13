#!/usr/bin/env python3
"""Record the provider fixtures of spec section 10, live, once.

Writes raw Tiingo rows for the split windows (AAPL, NVDA, USO), the full histories (VTI, VBIAX),
their meta objects, and a TR window whose annual stock dividend and cash dividend share one
ex-date (the days that fix the basis rule of spec 4.1). Needs ``TIINGO_API_KEY`` in the
environment; the key is never written. Cost: eleven Tiingo requests.
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
PRICE_WINDOWS: dict[str, tuple[str, date, date | None, bool]] = {
    # file stem -> (symbol, start, end, record meta); two months around each split of spec 4.1
    "AAPL_2020-08": ("AAPL", date(2020, 8, 1), date(2020, 9, 30), True),
    "NVDA_2024-06": ("NVDA", date(2024, 5, 10), date(2024, 7, 10), True),
    "USO_2020-04": ("USO", date(2020, 4, 1), date(2020, 5, 29), True),
    "VTI": ("VTI", FULL_HISTORY_START, None, True),
    "VBIAX": ("VBIAX", FULL_HISTORY_START, None, True),
    # 3% stock dividend and cash dividend on one ex-date in March 2024, 2025 and 2026
    "TR_2024-02": ("TR", date(2024, 2, 1), date(2026, 4, 30), False),
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
        for stem, (symbol, start, end, with_meta) in PRICE_WINDOWS.items():
            rows = provider.fetch_daily_raw(symbol, start, end)
            if not rows:
                print(f"{symbol}: no rows returned", file=sys.stderr)
                return 1
            _write_rows(provider_dir / f"{stem}.json", rows)
            if with_meta:
                meta = provider.fetch_meta_raw(symbol)
                (provider_dir / f"meta_{symbol}.json").write_text(
                    json.dumps(meta, indent=2, sort_keys=True) + "\n", encoding="utf-8"
                )
            print(f"{symbol}: {len(rows)} rows {rows[0]['date'][:10]}..{rows[-1]['date'][:10]}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
