# Prompt for the QSE session: repair total-return prices in the US core lake

Paste everything below the line into a Claude session opened in `~/programming/quant-scenario-engine`.

---

PortfolioSight (`~/programming/portfoliosight`, a portfolio risk/return site) wants to use the QSE US core lake as its price source for stocks and ETFs. The lake is current but its adjusted prices stopped being maintained in late March 2026, so PortfolioSight can only trust it up to 2026-03-27. Please make the lake carry correct total-return prices every day, and tell me how you did it.

## What is wrong (measured 2026-10-13, read-only)

Lake: `~/tft-quantile-forecaster/data/tft/raw/eodhd/datalake_us_core/` (per-symbol `eod_history/{SYM}.parquet` with columns `date, open, high, low, close, adj_close, volume`; `_orchestration_state.json` shows run 2026-10-13 done, 22,836 calls).

1. **Prices are current.** AAPL, MSFT, SPY and VTI all end 2026-10-12. About 70% of a 60-file sample ends 2026-10-12; some symbols stopped in March (for example AMH at 2026-03-25).
2. **`adj_close` is no longer adjusted after 2026-03-27.** For VTI, `adj_close / close` ranges 0.991 to 1.000 for 2025-06-01 to 2026-03-27, but is exactly 1.000 on all 136 rows after 2026-03-28, although VTI paid dividends in June and September 2026. The daily update appends the bulk row with `adj_close = close` and never back-adjusts.
3. **Corporate actions are missing.** `dividends/VTI.parquet` is empty, and the `splits/` files sampled have no rows. The QSE roadmap noted 403s on the EODHD dividends and splits endpoints.

Consequence: returns computed from `adj_close` after March leave out every dividend and show a false drop on each ex-date. That is about 1.3% a year for VTI, and 3 to 5% a year for bond funds. Any split after March would show as a crash.

## What PortfolioSight needs (the contract)

For every symbol in `datalake_us_core` (and later a separate `datalake_portfoliosight` for its fund list, per the README decision):

- A daily series through the latest closed session with raw `close`, and **either** `adj_close` fully back-adjusted for splits and dividends as of the last date, **or** raw `close` plus complete dividend (cash, ex-date) and split (factor, date) records from which a total-return index can be computed.
- A per-symbol `adjusted_through` date: the last date for which the adjustment is known complete. A machine-readable file is fine, for example `_adjusted_through.json` mapping symbol to date.
- The same guarantee every day, not a one-off repair.

PortfolioSight reads the lake read-only and re-seeds its own store with `scripts/seed_r2_from_lake.py --adjusted-through <date>`. That script already refuses rows after the cut-off whose `adj_close` differs from `close`.

## Options, cheapest first. Pick one, verify it on 5 symbols, then run it

1. **EODHD, the plan that already works.** The lake is refreshed with the bulk endpoint (`bulk/eod/latest.parquet` has `adjusted_close`). Check whether the plan allows:
   - the bulk corporate-action variants, `GET https://eodhd.com/api/eod-bulk-last-day/US?type=dividends&date=YYYY-MM-DD` and `type=splits`;
   - per-symbol `/api/div/{SYM}.US` and `/api/splits/{SYM}.US`.

   If either works, store dividends and splits daily and compute `adj_close` locally from raw closes. That is the README's own rule: "Compute total returns from raw closes plus the dividend and split records so cached histories do not drift when EODHD back-adjusts." If none works but per-symbol `eod` with adjusted close works, re-pull full adjusted history for symbols with an ex-date or split that day. The bulk dividends list tells you which. The EODHD key is in `~/.secrets/qse.env`, which the QSE session already uses.
2. **Tiingo**, which returns `close, adjClose, divCash, splitFactor` per symbol, already back-adjusted:
   - endpoint: `GET https://api.tiingo.com/tiingo/daily/{SYM}/prices?startDate=&endDate=&format=json&columns=date,close,adjClose,divCash,splitFactor`, with header `Authorization: Token $TIINGO_API_KEY`;
   - key: `TIINGO_API_KEY` in `/home/danie906/.secrets/portfoliosight.env`; load with `set -a; . file; set +a`; never print or log it;
   - limits on this key's Starter plan: 45 requests an hour, 900 a day, 450 distinct symbols a month. That covers only dividend repairs (symbols with an ex-date in the window), not a full daily refresh of 1,038 symbols. PortfolioSight's nightly also spends this key's budget, so coordinate: no more than about 200 symbols a month from QSE unless Jeff upgrades the plan.
3. **Schwab** (`qse/data/schwab.py`): open, high, low, close and volume only, unadjusted, no dividends. It can supply raw closes but not total return; it would still need dividend and split records from option 1 or 2. Use it only as a raw-close backstop.

## Ground rules

- Repo and lake belong to QSE. Follow its CLAUDE.md. Work on a branch with a pull request, and don't merge without Jeff.
- Do not rewrite existing history in place without a backup copy of `eod_history/` first, on `/mnt/d`.
- Verification to report back:
  - for VTI, BND, AAPL and one symbol that split in 2026, the ratio `adj_close / close` across each 2026 ex-date;
  - the yearly total return for 2026 YTD compared against Tiingo's `adjClose` for the same symbols (Tiingo spot checks within the budget above);
  - the `adjusted_through` file.
- Tell PortfolioSight's session, or Jeff, the new `adjusted_through` date. Its session will re-seed its store from the lake.
