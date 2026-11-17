# Single price source: Schwab plus yfinance, through the QSE lake

Status: draft for the owner's review, 2026-11-16. Not approved. It amends the demo spec `docs/specs/2026-10-13-portfoliosight-demo-design.md` (sections listed in Appendix B).

Paths are in the PortfolioSight repo unless they start with `QSE:` (the quant-scenario-engine repo). "The lake" is QSE's price store on the owner's laptop. "Vouched" means the lake lists a date for the fund in `_adjusted_through.json`: prices and dividends are checked through that date.

## 1. Owner decisions, 2026-11-16 (settled)

1. Schwab plus yfinance supply every stock and fund price, dividend and split, for now. No Tiingo purchase. Tiingo stops being a price source.
2. Exactly one job in one location updates stock and fund prices: QSE's daily pipeline on the laptop, which writes the lake. The lake stays on the laptop until the owner moves it.
3. PortfolioSight offers every fund the lake can vouch.
4. QSE's experiments keep a constant universe. Adding PortfolioSight funds to QSE's second list must not change it.
5. Safety: retries on yfinance and Schwab failures; a late fund keeps being served, with its as-of date, for 10 trading days; an alert 2 days before the weekly Schwab login expires and on any day the update fails.
6. EODHD fundamentals is paused until 2027-01-16 (the API returns 403). EODHD options keeps working.
7. The lake is backed up to R2 by separate QSE work (branch `feat/backup-eodhd-archive-r2`; no pull request open on 2026-11-16). This spec adds no lake folder, only more files in the existing ones.

## 2. What was checked

### 2.1 Schwab and mutual funds: unverified

Nothing in QSE records a Schwab daily price request for a mutual fund.

- The only live test asks for SPY and QQQ (`QSE:tests/integration/test_schwab_price_history_fetch.py:17`).
- QSE's notes on the Schwab price call name no asset types (`QSE:docs/data-sources/schwab_contract.md:31-40`).
- The recorded Schwab quote sample holds stocks only (`QSE:tests/data/schwab_quotes_fundamental_2026-10-14.json`).
- A web search found no Schwab statement either way. This machine has no Schwab login.

ETFs trade on an exchange and are fetched like stocks; the lake already keeps ETFs (VTI, SGOV, TLT: demo spec line 22). The 123 ETFs of Appendix A are expected to work but were not tested one by one. How many years of daily history Schwab returns is also unverified.

Section 9 makes a laptop test of a few mutual funds the first step (G0).

### 2.2 yfinance sample (run today)

Script: `/tmp/claude-1001/-home-jeff-programming-portfoliosight/92a6dff0-bd52-44b1-be75-ab0dcdd71cf9/scratchpad/design/yf_sample.py`, PortfolioSight venv Python 3.12.8. yfinance is not installed in that venv (it is in the `research` extra, `pyproject.toml:28-29`), so yfinance 1.8.0 was installed into the scratch folder. Call: `history(period="max", actions=True, auto_adjust=False)`, one symbol every 3 seconds. None of these 15 is in the QSE lists.

| Symbol | Kind (yfinance) | First date | Last date | Dividends | Splits |
|---|---|---|---|---|---|
| VBIAX | mutual fund | 2000-11-13 | 2026-11-13 | 99 | 0 |
| VTSAX | mutual fund | 2000-11-13 | 2026-11-13 | 105 | 0 |
| VGSTX | mutual fund | 1985-03-29 | 2026-11-13 | 88 | 0 |
| VIPSX | mutual fund | 2000-06-29 | 2026-11-13 | 88 | 0 |
| FXAIX | mutual fund | 2011-05-04 | 2026-11-13 | 63 | 0 |
| SWPPX | mutual fund | 1997-05-20 | 2026-11-13 | 30 | 1 (6 for 1, 2025-08-15) |
| DODGX | mutual fund | 1980-01-02 | 2026-11-13 | 187 | 1 (16 for 1, 2025-10-27) |
| PTTRX | mutual fund | 1987-05-11 | 2026-11-13 | 497 | 0 |
| FIENX | none | no data | no data | none | none |
| VTV | ETF | 2004-01-30 | 2026-11-16 | 91 | 0 |
| VNQ | ETF | 2004-09-29 | 2026-11-16 | 88 | 0 |
| TIP | ETF | 2003-12-05 | 2026-11-16 | 203 | 0 |
| SCHO | ETF | 2010-08-05 | 2026-11-16 | 192 | 1 (2 for 1, 2024-10-11) |
| EDV | ETF | 2008-01-29 | 2026-11-16 | 74 | 0 |
| DBJP | ETF | 2011-06-09 | 2026-11-16 | 28 | 0 |

The ETF rows ending 2026-11-16 are today's unfinished session.

What the sample shows:

- **History depth matches Tiingo where it can be compared.** VBIAX starts 2000-11-13 in both (`tests/fixtures/provider/meta_VBIAX.json`); VGSTX starts 1985-03-29 in both (demo spec line 287).
- **Year-end distributions arrive as dividends.** VBIAX on 2025-12-23: yfinance 1.628, Tiingo 1.627563 (`tests/fixtures/provider/VBIAX.json`). yfinance also returns a separate "Capital Gains" column; it was zero on every row of all 14 funds.
- **The total-return arithmetic reproduces yfinance's own adjusted close** to better than one part in a million on all 14 funds (price times one minus dividend over the prior close, compounded).
- **FIENX has no data in yfinance.** It is already not served ("converted to an ETF", `data/universes/tiers.json:22-24`; demo spec line 287). Its only history is Tiingo's, which ends 2024-10-30. So no served fund in the sample needs Tiingo.
- **One measured difference from Tiingo, before 2005.** VBIAX is the only fund with a recorded Tiingo history that is not already in the lake. From 2005 on the two agree on every payout. Before that, yfinance lacks four payouts (2001-03-16, 2001-12-21, 2002-09-27, 2002-12-27), lists 2003-03-28 as 0.224 against Tiingo's 0.112, and dates two 2004 payouts a week earlier. Result: growth of one dollar since 2000-11-13 comes out 3.2 percent lower from yfinance (adjusted over raw close on the first row: 0.4804 against 0.4655). One fund compared; needs validation on more.
- **Mutual funds do split** (SWPPX, DODGX), so the lake's split handling applies to them.
- **QSE's own yfinance reader works on mutual funds.** `YFinanceActionSource` (yfinance 0.2.66 in the QSE venv on this machine) returned the same VBIAX payouts and the DODGX split since 2025 (`QSE:qse/data/corporate_actions.py:886-959`).
- **Names from yfinance are abbreviated** ("Vanguard Balanced Index Adm" against Tiingo's "VANGUARD BALANCED INDEX FUND ADMIRAL SHARES").

### 2.3 TSP

The KS-001 nightly fetches the 16 TSP funds: `refresh((1,))` at `portfoliosight/jobs/nightly.py:320`, provider chosen at `nightly.py:368-371`, one CSV from tsp.gov (`portfoliosight/data/providers/tsp.py:22,110-131`). A TSP price is already a total return, with no dividends or splits (`tsp.py:1-5`). See open question 1.

### 2.4 Three facts in QSE's code that shape the design

1. **The lake vouches a fund only if it has a baseline file (`adj_base`), and only EODHD history can create one today.**
   - The daily job skips vouching for a symbol with no baseline (`QSE:qse/data/total_return_lake.py:1469-1470`, `1335-1336`, `1151-1152`).
   - The baseline is written only by the one-off repair, from rows dated before 2026-03-23 in the pre-repair EODHD copy (`total_return_lake.py:1994-2000`, `2198-2199`). A symbol with no such rows ends as `no_eod` or `no_eodhd_base` (`1980-1984`, `1997-1999`).
   - KRG and RBA were dropped from the list on 2026-10-16 for this reason (QSE commit `4f32dbe7`).
   - The 247 new funds have no EODHD rows, and EODHD is paused. Without section 5 they would be fetched and never vouched, so PortfolioSight would never take them (`scripts/sync_lake.py:232-234`).
2. **A dividend that only yfinance reports is accepted today.** It is added to the record (`QSE:qse/data/corporate_actions.py:589-643`). As far as dividends go, the vouched date stops only before a Schwab-only or an EODHD-only one (`total_return_lake.py:1279-1298`). yfinance is the only source the code treats as the full amount (`corporate_actions.py:70`). There is no "two sources must agree" rule for a yfinance row.
3. **What a fund without Schwab dividend data loses is daily progress.** Day to day, the vouched date moves only when Schwab's quote covers the latest dividend (`corporate_actions.py:1134-1157`). If the quote has no dividend block, the fund freezes after 3 sessions and is re-checked with yfinance on the next run (`corporate_actions.py:1189-1190`; `total_return_lake.py:1408-1410`), so its date would move about every fifth session. If Schwab instead sends an amount that leaves out the capital-gain part, it disagrees with yfinance's. For any symbol that is not a foreign listing (ADR) a disagreement is a conflict, and a conflict removes the symbol from the vouched list (`total_return_lake.py:776-778`, `283-284`). Which of the two Schwab does for mutual funds is unverified (G0).

## 3. Data flow

```
Schwab (daily bars, dividend quote)      yfinance (dividends, splits; full history when a fund is added)
            \                               /
   QSE daily pipeline, laptop, weekdays 06:45 PT: the one writer of stock and fund prices
            |
   the lake on the laptop: eod_history/ dividends/ splits/ adj_base/ _adjusted_through.json
            |                                  (lake backup to R2: separate QSE work)
   scripts/sync_lake.py, laptop, weekdays every 10 min, 07:00 to 09:50 PT; reads the lake, never writes it
            |
   R2 bucket portfoliosight-data: prices/{SYM}.parquet, meta/lake.json, meta/manifest.json, meta/symbols.json
            |
   KS-001: daily build (ready-made portfolios, publish, clean-up), then the API; both read R2 only
```

- **The writer.** `QSE:scripts/daily_pipeline_cron.sh:7-8` fires once each weekday at 06:45 PT. The price step is `refresh_schwab_eod` (`QSE:scripts/daily_pipeline.py:831-960`). It writes `_adjusted_through.json` last (`total_return_lake.py:1534`), which is how the sync knows a run is complete (`scripts/sync_lake.py:133-156`).
- **The sync** is unchanged in shape (`scripts/install_sync_lake_cron.sh:10`). Its rules change (sections 6 and 7).
- **What stops.** The KS-001 nightly's two Tiingo walks: `refresh((1,))` (`nightly.py:320`) and `refresh((2, 3), deadline)` (`nightly.py:344`), and the Tiingo provider (`nightly.py:368-371`). KS-001 then makes no price request (TSP: open question 1).
- **What the nightly keeps.** Everything that is not a price fetch: the generation date and id (`nightly.py:263-264`), building the ready-made portfolios (`325`), publishing (`328-338`), deleting old generations (`345-347`), the status file (`352-353`), the cache clean-up (`354`).
- **When it runs: after the sync, not at 02:00.** The lake job fetches a session's prices the next weekday morning. At 02:00 PT that has not happened yet, so every fund would be one session behind the generation date. Today only the stocks are in that position; after this change every fund in a ready-made portfolio would be. The timer (`deploy/systemd/portfoliosight-nightly.timer:6`) moves to 10:15 PT, after the sync's last poll at 09:50 (`scripts/sync_lake.py:74`). The date rule needs no change: any start on the same Los Angeles day gives the same generation date (`portfoliosight/data/calendar.py:29-45`), and rows after that date are never used (`portfoliosight/engine/builder.py:141`).
- **A gate, so the schedule cannot publish old prices under a new date.** The build publishes a generation only when the lake run in R2 started after that generation date's session closed. It reads the run's time from `meta/lake.json` (`generated_at`, `portfoliosight/data/lake.py:139-146`). Otherwise it publishes nothing and the site stays on the last generation, whose date and prices agree. Example: on Saturday the generation date is Friday but the newest lake run is Friday morning's, which holds Thursday's prices, so nothing is published; Monday's run brings Friday's prices and Friday's generation is built then. See open question 4.

## 4. Fund list: how wanted funds reach QSE's fetch list

- **PortfolioSight decides what it wants.** Tier 1 and tier 2 (`data/universes/tiers.json`, `data/universes/portfoliosight.txt`).
- **QSE owns the file its job reads:** `QSE:qse/config/universes/datalake_portfoliosight.txt` (`QSE:scripts/daily_pipeline.py:150-153`).
- **A new script writes the list:** `scripts/export_qse_fetch_list.py`. Output: the symbols already in QSE's file, plus every tier 1 and tier 2 fund that is not TSP, has no "data ended" note in `tiers.json` (FIENX), and is not in QSE's core list. Sorted, one per line. Today: 356 + 247 = 603 symbols.
- **Changes flow QSE first.**
  1. Edit tier 2 on a PortfolioSight branch and run the export.
  2. Open a QSE pull request with the new file. Merge it.
  3. On the laptop, add the new funds to the lake (section 5).
  4. Refresh PortfolioSight's copy `data/universes/qse_portfoliosight.txt` at the merged QSE commit (it records the commit in its first line today) and merge the PortfolioSight branch.
- **A PortfolioSight test enforces the order:** every tier 1 and tier 2 fund that is not TSP and has no note must be in `qse_core.txt` or `qse_portfoliosight.txt`. A fund cannot reach the menu before QSE fetches it.
- **QSE's experiment universe stays untouched.**
  - The dataset build is given the core file only (`QSE:scripts/daily_pipeline.py:1158-1159`). The second file adds to the price fetch only (`864-881`), in separate quote batches (`888-891`), and a symbol in both is fetched once (`813-828`).
  - One hole to close: when the core file is missing, the pipeline rebuilds it from every file in the lake (`daily_pipeline.py:699-715`) and fetches by the same listing (`864-867`). That would pull every PortfolioSight fund into the experiment universe. The lake already holds 356 such symbols; this change adds 247. QSE pull request Q1 makes a missing core file stop the run.

## 5. Lake baseline for funds with no EODHD history (QSE)

A fund with no EODHD history gets its baseline from Schwab plus yfinance, once, by an owner-run command on the laptop: `QSE:scripts/onboard_lake_symbols.py` (new). The existing repair cannot do it: `repair_symbol` takes the baseline from the pre-repair EODHD copy (`QSE:qse/data/total_return_lake.py:1849-1962`, `1994-2000`). The new command holds the daily pipeline's lock while it runs, as the repair does (`QSE:scripts/repair_lake_total_return.py:67`).

For each symbol:

1. **Fetch** the full yfinance history (closes, dividends, splits) and Schwab's daily bars for as far back as Schwab goes.
2. **Check** (all must pass, or nothing is written and the symbol is reported with the reason):
   - yfinance returned rows, and every close is a positive number;
   - on every date both have, Schwab's close and yfinance's close agree. The tolerance is set from the G0 sample and then checked on funds outside it; the repair's own comparison allows 3 percent (`total_return_lake.py:1783-1810`; `corporate_actions.py:77`), which is too loose to catch a bad price;
   - the adjusted series computed in step 3 matches yfinance's own adjusted close within the lake's factor tolerance (`total_return_lake.py:129`).
3. **Write** raw closes (splits undone, as the lake stores them: `QSE:scripts/daily_pipeline.py:842-844`), the dividend and split records with source `yfinance`, and the adjusted close computed from them. With no baseline the lake computes it as close times every later dividend and split factor (`corporate_actions.py:471-472`).
4. **Write the baseline:** those adjusted values through the baseline date (the last finished session), with the anchor set to that date. From then on the daily job treats the fund exactly like an EODHD-based one: the formula for rows inside a baseline is "stored value times the factors after the anchor" (`corporate_actions.py:471`, `502-503`). The file's metadata records the origin (`yfinance`) and the date built.
5. **Vouch** the fund through the baseline date.

Rules:

- **The vendor boundary is explicit, never silent.** Before the baseline date: yfinance prices, checked against Schwab. After it: Schwab's daily bars, as for every lake symbol. The boundary date is in the baseline file. This is the lake's existing shape with yfinance in EODHD's place.
- **A baseline is written once** (`total_return_lake.py:466-470`). Unlike an EODHD baseline it can be rebuilt from the sources, so the command has an owner-only `--rebuild`.
- **A symbol the daily job reached before it was onboarded** has a short unvouched file. Onboarding replaces it.
- **If Schwab returns no daily bars for mutual funds** (G0): the Schwab check in step 2 cannot run. Fallback: yfinance supplies the daily prices too for those funds, and each is labelled (section 6). See open question 2.

**Dividends for mutual funds: what "confirmed" means.** Each symbol gets an action policy, set at onboarding and kept in the lake's state file:

- `schwab+yfinance` (default): today's behaviour, unchanged.
- `yfinance` (mutual funds, and any symbol whose Schwab quote has no dividend block):
  - Schwab's dividend amount is not used, so it cannot raise a conflict (fact 3 in 2.4).
  - Every daily run asks yfinance for the fund's actions. If the request succeeds, the fund is vouched through its last price row. If it fails after the retries, the date does not move.
  - "Confirmed" for these funds means "yfinance lists it". There is no second source. Section 6 labels them.
  - Cost: one yfinance request per such fund per day (124 mutual funds today).

## 6. Labels, statuses and migration

**After the change**

| Field | Values | Meaning |
|---|---|---|
| `source` | `lake`, `tsp` | Who keeps the record. `seed`, `tiingo` and `seed+tiingo` retire (`portfoliosight/data/manifest.py:36`). |
| `status` | `ok` | Served: checked through a date at most 10 trading days old. |
| | `stale` | Was served; now more than 10 trading days old. Reason: `no data since {date}` or `corporate actions not yet verified after {date}` (`manifest.py:119-136`). |
| | `unavailable` | No usable data (FIENX). |
| `relies_on_yfinance` | true or false | True when yfinance is the source of a dividend or split after 2026-03-20 (`scripts/sync_lake.py:77-81`), and now also when the fund's baseline was built from yfinance. |
| `prices_from_yfinance` | true or false | New, and only if Schwab has no daily prices for mutual funds (G0): the fund's daily prices also come from yfinance. |

`pending` retires with `seed` (`manifest.py:109-110`). A newly listed fund has no entry until the lake first vouches it, and appears on the menu that day.

**Sync rule changes**

- **The lake wins for every non-TSP symbol.** The rule that a tier 1 or 2 fund stays with the provider goes (`scripts/sync_lake.py:82-83`, `191-193`, `230-231`).
- **No release to `seed`.** A symbol the sync has taken stays `source: lake`. When it falls behind it keeps its last record and becomes `stale`; it returns to `ok` at the first sync that finds it inside the window (today it is released: `sync_lake.py:396`; `portfoliosight/data/lake.py:34`, `165-189`).

**Migration of `tiingo` and `seed+tiingo` records**

- **Whole record or nothing.** When the lake vouches a fund inside the window, the sync replaces the fund's whole record with the lake's full history (`portfoliosight/data/lake.py:45-61`; `sync_lake.py:252`). No row of the old record survives. The only code that joins a new tail onto an old record is the Tiingo downloader (demo spec line 289), and it retires.
- **A report, written before each replacement:** `meta/migration.json`, one row per fund: old source, old and new first date, the dates both cover, growth of one dollar over those dates from each record, and the largest calendar-year difference. Replacement is not blocked by a difference (decision 1). See open question 3.
- **The first date can change.** A view that needs more history than the lake has sets the fund aside with the existing reason `history starts {date}, not enough for the {window} view`.
- **While a fund waits** (the lake has not vouched it): nothing touches its record or its label. It is served from its last Tiingo update for up to 10 trading days, showing that date. After that it is `stale`, listed as set aside with `no data since {date}`, until the lake vouches it.
- **Order, to avoid a gap:** onboard the funds in the lake first, then ship the new sync rules, then stop the Tiingo walk. The walk never touches a `lake` entry (`portfoliosight/data/refresh.py:53`), so the two can overlap safely. If Tiingo access ends sooner, the 10-day rule is the only buffer.
- **Done when** no `ok` entry has a retired source. Leftover entries (FIENX, seeds the lake never took) are listed for the owner. See open question 6.

## 7. Safety rules

### 7.1 Served rule: 10 trading days

- A fund is `ok` when its last price row and its vouched date are both on or after the session 10 NYSE sessions before the generation date. It is dropped at 11. One constant sets both the status rule and the sync's take rule: `SERVED_WITHIN_SESSIONS`, 3 today (`portfoliosight/data/manifest.py:18`, `102-116`; `scripts/sync_lake.py:222`, `235-236`); sessions are counted on the NYSE calendar (`portfoliosight/data/calendar.py:75-80`).
- TSP follows the same rule. Today one failed TSP fetch marks it not served at once (`portfoliosight/data/download.py:55`, `318-323`).
- **A late fund shows its date.** The page shows "prices as of {date}" beside a served fund whose latest price is before the generation date. The data is already sent (`portfoliosight/engine/builder.py:126-129`) and parsed (`web/src/api/tensor.ts:124`), but not displayed.
- **Consequence to know.** A mix is computed on the days all its funds have (`portfoliosight/engine/windows.py:110`). One fund that is k days late removes the last k days from every mix that holds it, up to 10.

### 7.2 Retries

| Call | Today | After |
|---|---|---|
| Schwab dividend quotes, per batch | 3 tries, waits doubling from 2 s to 20 s; a batch that still fails is skipped (`total_return_lake.py:587-611`) | Same. A failed PortfolioSight batch counts toward "Schwab is down". |
| Schwab daily bars, per symbol | None. One bad answer skips the symbol for the day (`QSE:scripts/daily_pipeline.py:896-909`; `total_return_lake.py:1441-1445`) | 3 tries, 2 s to 20 s, on network errors, "too many requests" and server errors. No retry on other refusals (unknown symbol, login). |
| yfinance, per symbol | 4 tries, 1 s to 20 s, half a second between calls; after 10 failures in a row the run stops calling yfinance (`corporate_actions.py:897-922`; `total_return_lake.py:171`, `709-735`) | Same. |
| The whole price step | One fire a day, no retry (`QSE:scripts/daily_pipeline_cron.sh:8`, `25-26`) | A second fire at 08:45 PT that runs the price step only, and only if the first run's verdict was "failed". |
| Sync to R2 | Polls every 10 minutes; a record that could not be stored is retried at the next poll (`scripts/sync_lake.py:428-443`) | Same. |
| TSP file | One try | 3 tries, 2 s to 20 s. |

### 7.3 Alerts

All alerts go to healthchecks.io, which QSE already uses (`QSE:scripts/backup_local.sh:1152-1155`, `QSE:scripts/options_pull_cron.sh:169-170`) and which also alarms when a check goes silent (laptop off, cron dead). Pushover is not used: its keys were never set, so every Pushover alert has been dropped (`QSE:scripts/daily_pipeline.py:186-191`, `214-222`).

| Alert | Check | Rule |
|---|---|---|
| Schwab login about to expire | `QSE_SCHWAB_HC_URL` (exists, `daily_pipeline.py:224`) | Fails from 2 days before expiry. Today it is 4 days and weekdays only (`daily_pipeline.py:163-176`); 2 days needs a check that also runs on weekends. See open question 5. |
| Price update failed | `QSE_LAKE_HC_URL` (new) | Success ping after a good price step, with counts in the message. Fail ping when the update failed (below). |
| Sync failed, or a fund is about to drop | `PS_SYNC_HC_URL` (new) | Success ping when the day's lake run is in R2. Fail ping when: the lake run is not complete by 09:50 (`scripts/sync_lake.py:143-150`); records could not be stored (`459-465`); the sync crashed (`497-505`); or any tier 1 or 2 fund is 5 or more trading days late, listed by ticker (halfway to the drop). Today these are log lines nobody is sent (`scripts/install_sync_lake_cron.sh:10`; demo spec line 360, "Alerts: none"). |

**"The update failed" means any one of:**

1. The price step did not finish: it stopped before rewriting `_adjusted_through.json`. This includes a Schwab login that expired or was blocked (`daily_pipeline.py:307`, `335`, `389`).
2. Schwab is down: daily bars failed, after retries, for 10 symbols in a row (the count the yfinance breaker already uses), or the quote batch for PortfolioSight's symbols failed.
3. yfinance is down: its breaker tripped (`total_return_lake.py:727-734`).
4. Nothing moved: the latest vouched date in the lake did not advance although the previous day was a trading day.

Not a failed update: single symbols with an error, no data, a conflict or an unconfirmed split. They are counted in the ping message and reach the owner through the "about to drop" alert if they last.

The verdict is about the price step only. The EODHD step runs after it (`daily_pipeline.py:1729-1731`) and cannot block prices. Whether EODHD's 403 makes that step, and so the pipeline, exit with an error is unverified (`daily_pipeline.py:753`); the alert must not depend on the pipeline's exit code.

## 8. Names and kinds

Today a name comes from the lake's EODHD files, then the catalog, then the ticker (`portfoliosight/data/lake.py:84-130`; `scripts/sync_lake.py:239`); names still missing come from Tiingo (`scripts/backfill_names.py`; demo spec line 355). A fund's kind comes from Tiingo, or defaults to "etf" (`sync_lake.py:255`). Neither source continues for funds: EODHD fundamentals is paused, and QSE asks EODHD about its core list only (`QSE:scripts/daily_pipeline.py:699`, `726-727`).

- **New committed file `data/universes/funds.json`:** symbol to `{name, kind}` for every tier 1 and tier 2 fund that is not TSP. It is filled once from the names the catalog shows today, so no displayed name changes; kinds come from the section headings of the tier 2 file (Appendix A). The owner edits it like any other list.
- **Order for a name:** `funds.json`; then the lake's archived `fundamentals_full` file; then the lake's US symbol list; then the catalog's current name; then the ticker. Stocks are not in `funds.json`, so they keep today's behaviour. The archived files stay on the laptop and are simply no longer refreshed.
- **A test requires an entry** with a real name for every tier 1 and tier 2 fund, so a new fund cannot ship unnamed.
- yfinance names are not used: they are abbreviated (2.2).

## 9. Work breakdown

In order. Each pull request has a regression test that fails before and passes after; existing tests stay as they are unless the feature they test is removed (P5).

**G0. Gate: Schwab fund test on the laptop (QSE repo, small script, owner or Marshal runs it).**
- Files: `QSE:scripts/probe_schwab_funds.py` (new); the saved answers as a test fixture next to `QSE:tests/data/schwab_quotes_fundamental_2026-10-14.json`; a short report in `QSE:docs/reviews/`.
- Asks Schwab, for VTSAX, VBIAX, VGSTX, FXAIX, SWPPX, DODGX, PTTRX and two ETFs (VTV, SCHO): the daily price history as far back as it goes, and the quote with its dividend block.
- Answers: (a) does Schwab return daily prices for mutual funds, and from what date; (b) does the quote carry dividend fields for them, and does VBIAX's amount for 2025-12-23 equal 1.628; (c) does a 06:45 PT request return today's unfinished session.
- Decides: Schwab or yfinance daily prices for mutual funds (section 5), and confirms the `yfinance` action policy.

**P1. PortfolioSight: fund metadata and the fetch-list export.**
- Files: `data/universes/funds.json` (new), `scripts/export_qse_fetch_list.py` (new), `portfoliosight/data/universe.py`, `tests/data/test_universe.py`.
- Tests: every non-TSP tier 1 and 2 fund has a name that is not its ticker, and a kind. The export contains QSE's current list and every wanted fund outside the core list; no TSP id, no FIENX, no core symbol; sorted, no repeats.
- Acceptance: the export prints 603 symbols.

**Q1. QSE: fetch list and universe guard.**
- Files: `QSE:qse/config/universes/datalake_portfoliosight.txt`, `QSE:scripts/daily_pipeline.py` (`699-715`, `864-867`), `QSE:tests/scripts/test_daily_pipeline.py`.
- Tests: with a core list of N and a second list of M other symbols, the price step receives N + M and the dataset command names the core file only. With the core file missing, the run stops and writes no universe file.
- Acceptance: the next run logs 603 PortfolioSight-only symbols (`daily_pipeline.py:822-827`); the dataset has the same tickers as the day before.

**Q2. QSE: baseline from Schwab plus yfinance, and the action policy.**
- Files: `QSE:qse/data/total_return_lake.py`, `QSE:qse/data/corporate_actions.py`, `QSE:scripts/onboard_lake_symbols.py` (new), `QSE:tests/unit/data/test_total_return_lake.py`, `QSE:tests/scripts/test_onboard_lake_symbols.py` (new).
- Tests:
  - A symbol with no lake files, given a made-up history with two dividends and one split and matching Schwab bars, ends with the hand-computed adjusted closes, a baseline, and a vouched date equal to the baseline date.
  - Schwab closes that disagree with yfinance's: nothing written, not vouched, reason reported.
  - A symbol yfinance does not know (FIENX): nothing written.
  - After onboarding, a new dividend lowers every earlier adjusted close by its factor and the vouched date advances.
  - A `yfinance`-policy fund with no Schwab dividend block advances on each of five run days in a row.
  - A failed yfinance request leaves its date where it was.
  - A Schwab amount that differs from yfinance's raises no conflict for a `yfinance`-policy fund.
  - A second onboarding run changes nothing without `--rebuild`.
  - Every existing lake test passes unchanged.
- Acceptance, on the laptop: a report for the 247 funds with the number vouched and each failure's reason. Held-out check: for 10 funds not used during development, growth over the last 10 years from the lake equals yfinance's adjusted close within the lake's factor tolerance (`total_return_lake.py:129`), and Schwab's closes agree with yfinance's within the tolerance set in G0.
- PortfolioSight then refreshes `data/universes/qse_portfoliosight.txt` (section 4, step 4); the order test of section 4 lands with that commit.

**Q3. QSE: retries, the verdict and the alerts.** Independent of Q1 and Q2.
- Files: `QSE:scripts/daily_pipeline.py` (`176`, `214-233`, `896-909`), `QSE:scripts/daily_pipeline_cron.sh`, `QSE:qse/data/total_return_lake.py` (`630-643`), `QSE:tests/scripts/test_daily_pipeline.py`.
- Tests:
  - A price request that fails twice and then succeeds yields its bars. One that fails three times is counted and the run goes on. An unknown-symbol answer is not retried.
  - Ten Schwab failures in a row, or a tripped yfinance breaker, give "failed" and one fail ping with the reason.
  - A day with three failed symbols gives "ok" and a success ping with counts.
  - No address set: no request. A ping that fails never fails the run.
  - Login check: 2.5 days left is healthy, 1.9 is a fail ping. The weekend check only reports; it never opens the login flow.
- Acceptance: the owner creates the check and sets `QSE_LAKE_HC_URL`; a forced failure reaches the owner; a good run turns the check green.

**P2. PortfolioSight: sync rules and labels.** After Q2's onboarding.
- Files: `portfoliosight/data/manifest.py`, `portfoliosight/data/lake.py`, `scripts/sync_lake.py`, `tests/data/test_manifest.py`, `tests/data/test_lake.py`, `tests/data/test_sync_lake.py`.
- Tests:
  - A fund vouched k sessions before the generation date is `ok` for k from 0 to 10 and `stale` at 11, across a holiday week.
  - A `tiingo` fund the lake vouches gets a record equal to the lake's whole history, `source: lake`, its name unchanged, and a row in the migration report.
  - A fund the lake does not vouch keeps its record bytes and its label.
  - A taken symbol that falls behind stays `lake` and `stale`, and comes back to `ok`. No run writes `seed`.
  - A fund on a yfinance baseline has `relies_on_yfinance` true.
  - Name and kind come from `funds.json`.
  - Pings: run not complete at 09:50 fails; a synced run succeeds; a fund 5 sessions late fails and is named; no address, no request.
- Acceptance: a dry run on the laptop prints how many tier 1 and 2 funds move to the lake. After the real run, `meta/migration.json` exists and the number of `ok` entries with a retired source is reported.

**P3. PortfolioSight: the page shows the as-of date.** With or after P2.
- Files: the Funds table in `web/src/`; the copy table of demo spec section 3.6.
- Tests: a late fund shows "prices as of {date}"; a current fund shows nothing.
- Acceptance: `npm run lint && npm run typecheck`, then `npm run build` and `npm run e2e:local`.

**P4. PortfolioSight: daily build without Tiingo.** Only when P2 reports zero `ok` entries with a retired source, or the owner accepts the list of funds left behind.
- Files: `portfoliosight/jobs/nightly.py`, `deploy/systemd/portfoliosight-nightly.timer`, `deploy/docker-compose.yml`, `tests/jobs/test_nightly.py`, `tests/deploy/`.
- Tests: with no provider and no network, the run builds and publishes from the store. A lake run that started before the generation date's close publishes nothing and leaves the current generation in place; a later one publishes. A fund 4 sessions late is included with its date; one 11 late is set aside with its reason. The timer starts at the new time.
- Acceptance: on KS-001 the day after, the current generation is that day's, built after the sync; the log shows no outside price request; the KS-001 secrets file no longer needs the Tiingo key.
- TSP moves or stays here, per open question 1.

**P5. PortfolioSight: remove the retired code and amend the demo spec.** Needs the owner's go.
- Removes the Tiingo provider, the downloader and its request budget, the seed script and the Tiingo name backfill, with the tests of those features. Amends the sections of Appendix B (documents only).
- Acceptance: no "tiingo" left under `portfoliosight/` or `scripts/`; lint, type check and tests pass; coverage stays above 80 percent.

## 10. Risks and open questions for the owner

1. **Who fetches the 16 TSP funds?** They come from a tsp.gov file, not from Schwab or yfinance, and the KS-001 nightly fetches them today.
   - a (recommended): TSP stays a named exception and its fetch moves into the laptop sync job. One location updates every price and one job writes R2's prices; KS-001 fetches nothing. Cost: the sync gains a second source.
   - b: TSP stays on the KS-001 nightly as it is. No work. Cost: prices are updated in two places.
   - c: TSP moves into QSE's lake job, which is "one job" to the letter. Cost: QSE gains a source its experiments never use, and the lake needs a special path for a fund with no Schwab or yfinance data.
2. **If Schwab has no daily prices for mutual funds (G0), may yfinance supply both their prices and their distributions?**
   - y (recommended): the 124 mutual funds are served and labelled `prices_from_yfinance`. Cost: one unofficial source with no cross-check for those funds.
   - n: mutual funds are not served until another source exists.
3. **yfinance's older history can differ from Tiingo's** (VBIAX before 2005, 3.2 percent since 2000; one fund measured).
   - a (recommended): replace every fund's history with the lake's and list the differences in the migration report for the owner to read. All screens that use the last 10 years or less are unaffected in the one fund measured.
   - b: hold back any fund whose difference passes a limit until the owner looks. Cost: fewer funds at first, and the limit must be chosen and checked.
4. **The site's daily refresh gets later.** The lake job runs on weekday mornings and fetches the previous session, so a day's close appears the next weekday mid-morning PT, and Friday's close on Monday. Today Tiingo delivers it at about 02:00 PT the next calendar day, and Friday's on Saturday.
   - a (recommended): accept it. The build runs at 10:15 PT behind the gate of section 3. No change to QSE's schedule.
   - b: also run the price step, the sync and the build on Saturday mornings, so Friday's close appears on Saturday. Cost: the laptop must be on every Saturday morning, and a missed Saturday raises an alert.
5. **Schwab login alert: exactly 2 days before, or keep today's rule?** Today the alert starts 4 days before expiry and is checked on weekdays only, because a 2-day window can fall on a weekend.
   - a (recommended): 2 days before, checked every day including weekends. Cost: one more cron line on the laptop, running the check only.
   - b: keep 4 days, weekdays only. No work.
6. **Delete the Tiingo-era records once they are replaced, and FIENX's record?** Replacement overwrites a fund's file, and the laptop backup mirrors that. What remains is FIENX's history and any fund the lake never vouches.
   - y (recommended): delete them when migration is done. Tiingo's terms allow stored data only while a paid plan is active (demo spec line 581). FIENX then shows "no data".
   - n: keep them, not served.
7. **A distribution yfinance lists a day late** shows as a one-day drop the size of the payout until the next run corrects the record. No second source exists to catch it.
   - a (recommended): accept it for now and review after the December 2026 distributions.
   - b: hold a mutual fund's date back when its price falls sharply with no listed payout. Cost: a threshold that must be fitted and checked on held-out data.
8. **Keep the rule that yfinance-based funds are reviewed before the site opens to the public?** (demo spec lines 356 and 511). After this change that is nearly every fund.
   - y (recommended): the rule stands; `relies_on_yfinance` is the list to review.
   - n: yfinance is accepted for public launch too.

**Things only the owner can do:** create two healthchecks.io checks and put their addresses in `~/.secrets/qse.env` (`QSE_LAKE_HC_URL`) and `~/.secrets/portfoliosight.env` (`PS_SYNC_HC_URL`); confirm `QSE_SCHWAB_HC_URL` is set; run G0 and the onboarding on the laptop (or have Marshal do it).

**Still unverified:** Schwab daily prices and dividend fields for mutual funds; how far back Schwab's daily history goes; each of the 123 ETFs on Schwab; whether the lake's last row at 06:45 PT is an unfinished session; whether EODHD's 403 fails the pipeline; whether the lake holds name files for any of the 247 funds; which of the 77 tier 1 and 2 funds already on QSE's lists the lake vouches today. The lake is not on the machine this spec was written on.

## Appendix A: tier 1 and tier 2 funds outside QSE's lists (recount, 2026-11-16)

Counted with `portfoliosight.data.universe.load_tiers()` against `data/universes/qse_core.txt` (1,038 symbols; PortfolioSight's copy of QSE's core list, which is not on this machine) and `QSE:qse/config/universes/datalake_portfoliosight.txt` (356).

| | Funds | Outside the QSE lists | Of which |
|---|---|---|---|
| Tier 1 | 56 | 33 | 14 ETFs, 3 mutual funds, 16 TSP |
| Tier 2 | 317 | 248 | 123 ETFs, 125 mutual funds (FIENX among them) |
| Tier 1 and 2 together | 341 | 264 | 123 ETFs, 124 mutual funds, 16 TSP, 1 other (FIENX) |

The 17 tier 1 funds that are not TSP are all in tier 2 as well. Kinds are taken from the section headings of `data/universes/portfoliosight.txt`. All 125 mutual funds, and no ETF, have five letters ending in X. To be added to QSE's fetch list: 247 (the ETFs and mutual funds; not TSP, not FIENX).

**ETFs (123)**

- US equity (38): SPTM VV VUG VTV IWF IWD SCHV VO MDY SCHM VOE VOT IWR VB SCHA VBR VBK VXF VIG DVY VYM HDV SDY NOBL DGRO USMV SPLV MTUM QUAL VLUE IWN IWO IWS IWP AVUV AVUS DFUS DFAC
- Sector and real estate (8): VGT VHT VFH VDE VNQ USRT VPU VDC
- International equity (22): IXUS SCHE VGK VPL DBJP HEDJ VSS SCZ IDV VYMI DFAX AVDV AVEM SCHC EFV EFG ACWI VEU IOO URTH FNDF FNDE
- Bond (44): SCHZ BNDW BIV BSV BLV IGSB IGIB IGLB JNK SHYG VGSH VGLT SHV IEI TLH EDV ZROZ SCHO SCHR SCHQ SPTS TIP VTIP STIP LTPZ TIPX MUB SUB HYD PCY VWOB EMLC IAGG IGOV BWX FLOT USFR TFLO MBB VMBS CWB PFF FALN ANGL
- Commodity, alternative and allocation (11): DBC GSG VNQI REET IGF AOA AOR AOM AOK NTSX SWAN

**Mutual funds (124)**

- Vanguard (51): VTSAX VTSMX VFIAX VFINX VIMAX VSMAX VVIAX VIGAX VTIAX VGTSX VTMGX VEMAX VBTLX VBMFX VBILX VBIRX VBLAX VSIGX VSCSX VTAPX VIPSX VWEHX VWINX VWELX VBIAX VGSTX VTINX VTTVX VTHRX VTTHX VFORX VTIVX VFIFX VFFVX VTTSX VLXVX VSVNX VGSLX VDIGX VWIAX VWIGX VWUSX VPMCX VHCAX VEXAX VMVAX VSIAX VSGAX VTMSX VFSVX VGAVX
- Fidelity (36): FXAIX FSKAX FZROX FNILX FSMAX FSSNX FSPSX FTIHX FZILX FPADX FXNAX FTBFX FUAMX FIPDX FBALX FPURX FFNOX FFFCX FFTWX FFFEX FFTHX FFFFX FFFGX FFFHX FDEEX FDKVX FCNTX FMAGX FLPSX FDGRX FBGRX FOCPX FSELX FSPGX FLCOX FSRNX
- Schwab (8): SWTSX SWPPX SWLGX SWSSX SWMCX SWISX SWAGX SWRSX
- Other 401(k) staples (29): PRGFX PRWCX PRFDX TRBCX RPMGX AGTHX AIVSX AWSHX ANWPX AEPGX CAIBX ABALX AMECX ANCFX CWGIX SMCWX DODGX DODFX DODIX DODBX OAKMX OAKIX PTTAX PTTRX PONAX MWTRX BCOIX LSBDX FKINX

**TSP (16):** TSP-G TSP-F TSP-C TSP-S TSP-I TSP-LINC TSP-L2030 TSP-L2035 TSP-L2040 TSP-L2045 TSP-L2050 TSP-L2055 TSP-L2060 TSP-L2065 TSP-L2070 TSP-L2075

**Other (1):** FIENX. A Fidelity mutual fund converted to an ETF; Tiingo's history ends 2024-10-30; yfinance has none; not served.

**Tier 1 funds in the list above:** ETFs VTV VOE VB VBR VNQ SCHO TIP VTIP VWOB PCY LTPZ EDV DBJP IWD; mutual funds VBIAX VGSTX VIPSX; the 16 TSP funds.

## Appendix B: demo spec sections to amend (in P5)

| Demo spec | What changes |
|---|---|
| Line 22, data decisions | "Tiingo; no yfinance, no Schwab" becomes Schwab plus yfinance through the lake; the lake is the source, not a one-time seed. |
| 5.1, lines 277-289 | The Tiingo adapter and the tail splice retire. |
| 5.2, lines 295-308 | Served rule 3 becomes 10 trading days; the Tiingo plan table, the starter slice and the limits probe retire; tier 2 funds come from the lake. |
| 5.3, lines 314-331 | `source` values; `meta/provider_limits.json` and `meta/budget.json` retire; `meta/migration.json` and `prices_from_yfinance` added. |
| 5.4, lines 347-360 | The seed and the downloader retire; lake sync precedence, release to seed and the 3-session rule change; the nightly loses steps 2 and 4 and moves after the sync; "Alerts: none" becomes section 7.3. |
| 5.5, line 364 | Who fetches TSP (open question 1); the 10-day rule for TSP. |
| 9.1, line 467 | The timer's start time. |
| 9.6, lines 507-514, and 13, lines 581-584, 592 | The Tiingo license, plan limits and seed quality risks retire; the yfinance review rule is restated (open question 8). |
| Appendix A, line 608 | "not the provider" wording. |
| `2026-10-13-portfoliosight-demo-design.assertions.md` | 14 lines that name Tiingo or the 3-session rule. |
