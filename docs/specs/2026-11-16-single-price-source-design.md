# Single price source: Schwab plus yfinance, through the QSE lake

Status: draft, updated 2026-11-16 with the owner's answers of that day (section 1). Not approved: two questions remain (section 10). It amends the demo spec `docs/specs/2026-10-13-portfoliosight-demo-design.md` (sections listed in Appendix B).

Paths are in the PortfolioSight repo unless they start with `QSE:` (the quant-scenario-engine repo). "The lake" is QSE's price store on the owner's laptop. "Vouched" means the lake lists a date for the fund in `_adjusted_through.json`: prices and dividends are checked through that date. A fund's "starting point" is its `adj_base` file in the lake: the adjusted closes the lake computes every later value from.

## 1. Owner decisions, 2026-11-16 (settled)

1. **One job, one place.** The laptop updates every price. QSE's price job writes the lake for every stock and fund. The 16 TSP funds move to the laptop too ("I don't care, just make it one place"): the laptop sync fetches the tsp.gov file. KS-001 fetches no prices.
2. **Sources.** Schwab supplies daily prices for stocks, ETFs and mutual funds; the owner is certain about mutual funds. yfinance supplies dividends and splits. yfinance prices are a fallback only when Schwab fails, and a fund served that way is labelled. No Tiingo purchase; Tiingo stops being a source.
3. **The Parquet files are the baseline.** "The parquet files ARE the baseline. We haven't used EODHD for pricing for a long time, it should NOT be a requirement for maintaining the price history." The lake builds a fund's starting point from its own files: raw closes plus the recorded dividends and splits. Starting points EODHD history made stay valid. EODHD is never required.
4. PortfolioSight offers every fund the lake can vouch.
5. QSE's experiments keep a constant universe. Adding PortfolioSight funds to QSE's second list must not change it.
6. **Timing.** Two lake runs each weekday: a new one in the evening, after the close, and the 06:45 PT run, kept for late corrections and for dividends yfinance lists a day late. The laptop sync runs after each. The KS-001 build stays at 02:00 PT. It never publishes a generation whose prices are older than its date: if the evening run did not happen, it publishes nothing and the site keeps the last generation.
7. **Safety.** Retries on yfinance and Schwab failures. A late fund keeps being served, with its as-of date, for 10 trading days. An alert 2 days before the weekly Schwab login expires and on any failed update. Alerts go to healthchecks.io now, and also to Pushover once its keys exist. The Pushover code stays.
8. **Nothing is deleted.** "Don't delete old prices unless you are 1000% sure that they exist in the lake." A Tiingo-era or seed record is moved to `archive/` in R2, and only after the lake vouches the fund, the sync has written the lake's record for it, and its migration report row exists. FIENX stays as it is.
9. **A distribution yfinance lists a day late is accepted.** Review after the December 2026 distributions.
10. **No review of yfinance-based funds before public launch.** That rule is dropped (section 6).
11. **The requested tickers are added:** 29 from the site's request log (section 4.1).
12. **The lake's R2 backup is parked.** QSE pull request #181 is a draft. "get everything formatted and updating daily how we want/need it, and then can move the backup to R2 and possibly devbox or another server at some point. Not now, but develop with that in mind." This spec's pull requests do no backup work; new code follows section 11.

Standing facts: EODHD fundamentals is paused until 2027-01-16 (the API returns 403); EODHD options keeps working. Neither touches prices: EODHD's price, dividend and split requests were refused long before the pause (2.4, fact 2).

## 2. What was checked

### 2.1 Schwab: what is still to measure

The owner is certain Schwab returns daily prices for mutual funds. QSE's repo holds no record of such a request:

- The only live test asks for SPY and QQQ (`QSE:tests/integration/test_schwab_price_history_fetch.py:17`).
- QSE's notes on the Schwab price call name no asset types (`QSE:docs/data-sources/schwab_contract.md:31-40`).
- The recorded Schwab quote sample holds stocks only (`QSE:tests/data/schwab_quotes_fundamental_2026-10-14.json`).

So the laptop test (G0, section 9) stays, as a measurement and not as a gate on whether Schwab has mutual funds. It measures:

- **History depth.** How far back Schwab's daily history goes per fund. The longest period QSE's notes list is 20 years; start and end dates are optional parameters (`schwab_contract.md:31-38`).
- **Fields.** What the quote's dividend block holds for a mutual fund (2.4, fact 3).
- **Timing.** When the day's price is present and final (3.1).
- **Coverage.** Whether the OTC tickers of section 4.1 return prices.

ETFs trade on an exchange and are fetched like stocks; the lake already keeps ETFs (VTI, SGOV, TLT: demo spec line 22). The 123 ETFs of Appendix A are expected to work but were not tested one by one. This machine has no Schwab login.

### 2.2 yfinance sample (run 2026-11-16)

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

The ETF rows ending 2026-11-16 are that day's unfinished session. The sample used yfinance prices; under decision 2 yfinance supplies only the dividends and splits, and its prices serve as a cross-check (section 5).

What the sample shows:

- **Year-end distributions arrive as dividends.** VBIAX on 2025-12-23: yfinance 1.628. yfinance also returns a separate "Capital Gains" column; it was zero on every row of all 14 funds.
- **The total-return arithmetic reproduces yfinance's own adjusted close** to better than one part in a million on all 14 funds (price times one minus dividend over the prior close, compounded).
- **Mutual funds do split** (SWPPX, DODGX), so the lake's split handling applies to them.
- **QSE's own yfinance reader works on mutual funds.** `YFinanceActionSource` (yfinance 0.2.66 in the QSE venv on this machine) returned the same VBIAX payouts and the DODGX split since 2025 (`QSE:qse/data/corporate_actions.py:886-959`).
- **FIENX has no data in yfinance.** It is already not served ("converted to an ETF", `data/universes/tiers.json:22-24`; demo spec line 287).
- **Names from yfinance are abbreviated** ("Vanguard Balanced Index Adm").
- **History, not a decision point: yfinance's dividend record before 2005 differs from Tiingo's for VBIAX,** the one fund compared. From 2005 on the two agree on every payout. Before that, yfinance lacks four payouts (2001-03-16, 2001-12-21, 2002-09-27, 2002-12-27), lists 2003-03-28 as 0.224 against Tiingo's 0.112, and dates two 2004 payouts a week earlier. Growth of one dollar since 2000-11-13 came out 3.2 percent lower from yfinance. Tiingo is no longer a choice (decision 2); the migration report (section 6) shows such differences fund by fund.

### 2.3 TSP

The KS-001 nightly fetches the 16 TSP funds today: `refresh((1,))` at `portfoliosight/jobs/nightly.py:320`, provider chosen at `nightly.py:368-371`, one CSV from tsp.gov (`portfoliosight/data/providers/tsp.py:22,110-131`). A TSP price is already a total return, with no dividends or splits (`tsp.py:1-5`). Decision 1 moves this fetch to the laptop sync (section 3).

### 2.4 Three facts in QSE's code that shape the design

1. **The lake vouches a fund only if it has a starting point, and today only EODHD history can create one.**
   - The daily job skips vouching for a symbol with none (`QSE:qse/data/total_return_lake.py:1469-1470`, `1335-1336`, `1151-1152`).
   - The file is written once (`total_return_lake.py:446-480`), and only by the one-off repair, from rows dated before 2026-03-23 in the pre-repair EODHD copy (`1994-2000`, `2198-2199`). A symbol with no such rows ends as `no_eod` or `no_eodhd_base` (`1980-1984`, `1997-1999`). KRG and RBA were dropped from the list on 2026-10-16 for this reason (QSE commit `4f32dbe7`).
   - A stored row that has no value in the file blocks the fund with `adj_base_gap`, in the daily job (`1436-1440`), in the yfinance re-check (`1171-1174`) and in the repair (`2191-2196`). The code refuses to fill the value in (`QSE:qse/data/corporate_actions.py:456-460`, `495-501`), and a blocked fund waits for a person (`total_return_lake.py:140`, `334-335`).
   - The arithmetic itself needs no EODHD. For a fund with no starting point the lake already computes every adjusted close as raw close times the factor of every later dividend and split (`corporate_actions.py:471-472`; `total_return_lake.py:646-668`). What is missing is the file, and so the vouching.
   - The new funds have no EODHD rows. Without section 5 they would be fetched and never vouched, so PortfolioSight would never take them (`scripts/sync_lake.py:232-234`).
2. **A dividend that only yfinance reports is accepted today, and EODHD has supplied none for months.**
   - A yfinance-only dividend is added to the record (`corporate_actions.py:589-643`). As far as dividends go, the vouched date stops only before a Schwab-only or an EODHD-only one (`total_return_lake.py:1279-1298`). yfinance is the only source the code treats as the full amount (`corporate_actions.py:70`).
   - EODHD dividends were a separate request, and it has been refused since before August: price, split and dividend requests return 403 (probed 2026-08-14, `QSE:docs/adr/ADR-004-corporate-actions-and-price-adjustment.md:60-61`), and the last EODHD dividend row in the lake is dated 2026-04-06 (`total_return_lake.py:123-125`). The fundamentals pause changed nothing for dividends.
3. **What a fund without Schwab dividend data loses is daily progress.** Day to day, the vouched date moves only when Schwab's quote covers the latest dividend (`corporate_actions.py:1134-1157`). Two ways that can fail for a mutual fund, both unverified (G0):
   - The quote has no dividend block. The fund is then re-checked with yfinance, but not on every run: a re-check waits until the last one is more than 2 sessions old (`total_return_lake.py:174`, `1538-1553`), and a fund missing from the quote freezes after 3 sessions and is re-checked on the next run (`corporate_actions.py:84`, `1189-1190`; `total_return_lake.py:1408-1410`). Its date would move every few sessions.
   - The quote's amount leaves out the capital-gain part. It then disagrees with yfinance's. For any symbol that is not a foreign listing (ADR) a disagreement is a conflict, and a conflict removes the symbol from the vouched list (`total_return_lake.py:776-778`, `283-284`).

### 2.5 The requested tickers

- **Source.** The live site's request log (`GET /api/ticker-requests`, admin only; demo spec line 481), read 2026-11-16: 30 rows. 29 came from one CSV upload on 2026-11-11. The 30th, ZZZZ, is a test ticker typed on 2026-11-16 and is left out.
- **Already on QSE's lists: three.** FCX, TSM and WMT are in the core list (`data/universes/qse_core.txt`). None of the 29 is in `data/universes/qse_portfoliosight.txt`, in QSE's own file (`QSE:qse/config/universes/datalake_portfoliosight.txt`), or in tier 1 or tier 2. So 26 are new to QSE.
- **FCX, TSM and WMT were not served on 2026-11-11 although QSE fetches them:** the log does not count a ticker the site serves (demo spec line 481). Why is unverified; the lake is not on this machine.
- **Eleven have five letters ending in Y,** the usual form of an OTC ticker for a foreign company: ATLKY CMWAY EADSY FRCOY ISNPY LRLCY LVMUY MTSUY NSRGY SIEGY UNCRY. Whether Schwab returns daily prices for them is unverified (G0). The lake already handles foreign listings: Schwab's dividend amount for them is net, so yfinance's amount wins (`corporate_actions.py:66-70`).

## 3. Data flow

```
Schwab (daily prices; latest-dividend quote)        yfinance (dividends, splits)
            \                               /
   QSE price job, laptop, weekdays 18:00 PT and 06:45 PT: the one writer of stock and fund prices
            |
   the lake on the laptop: eod_history/ dividends/ splits/ adj_base/ _adjusted_through.json
            |
   scripts/sync_lake.py, laptop, after each lake run: reads the lake, never writes it;
   also fetches the 16 TSP funds from tsp.gov
            |
   R2 bucket portfoliosight-data: prices/{SYM}.parquet, archive/, meta/lake.json,
   meta/manifest.json, meta/symbols.json, meta/migration.json
            |
   KS-001: daily build at 02:00 PT, then the API; both read R2 only; no price request
```

### 3.1 Schedule

| When (PT) | Where | What |
|---|---|---|
| Weekdays 18:00 (needs validation) | laptop | Lake run, price step only: the session that closed at 13:00. |
| Weekdays 18:10 to 21:50, every 10 minutes | laptop | Sync: lake to R2, then the TSP file. |
| Every day 02:00 | KS-001 | Build and publish, behind the gate below. |
| Weekdays 06:45 | laptop | Lake run as today (`QSE:scripts/daily_pipeline_cron.sh:7-11`): late corrections, and dividends yfinance lists a day late. |
| Weekdays 07:00 to 09:50, every 10 minutes | laptop | Sync, as today (`scripts/install_sync_lake_cron.sh:10`). |

**How 18:00 was chosen.**

- Stocks and ETFs: the daily bar is the regular session, which ends at 13:00 PT.
- Mutual funds: a fund's price for the day is set after the close and reported to Nasdaq's fund price service. Its nightly deadline is 20:00 ET, which is 17:00 PT, and most prices arrive by 18:05 ET (Investment Company Institute memo, 2009-06-11: `https://www.nasdaqtrader.com/content/newsalerts/2009/dn/ICImemo_06112009.pdf`). That document is from 2009, names no time zone (Nasdaq works in Eastern time), and was not confirmed as current.
- 18:00 PT is one hour after that deadline and eight hours before the build. The build already counts a session as settled once it closed six hours before 02:00 (`portfoliosight/data/calendar.py:13-15`, `29-45`).
- **Needs validation.** When Schwab's API first shows a fund's price for the day, and whether a bar changes after it first appears, are not confirmed. G0 measures both. The time is a setting (section 11).

**The evening run** is the price step only: the login check and `refresh_schwab_eod` (`QSE:scripts/daily_pipeline.py:831-960`), for every symbol of both lists. It needs a new flag: today one command runs the price step, the EODHD and FRED steps and the dataset build together (`daily_pipeline.py:1727-1735`), and the wrapper is built around one dataset build per day (`daily_pipeline_cron.sh:10-23`). The dataset build stays in the 06:45 run only. Both runs take the same lock (`daily_pipeline_cron.sh:100`). Each run writes `_adjusted_through.json` last (`total_return_lake.py:1534`), which is how the sync knows a run is complete (`scripts/sync_lake.py:133-156`).

**The sync** keeps its shape and gains a second window. "Complete" becomes "written at or after the start of this window's run" (today: at or after 06:45, `sync_lake.py:73`, `140-141`). Each window ends with an alert when its run is missing (7.3). In each window, after the lake is synced, the sync fetches the TSP file until it holds the latest session's price. When tsp.gov posts a day's price is unverified; a TSP fund that misses the evening window is one day late at the build and shows its date (7.1).

**The build stays at 02:00** (`deploy/systemd/portfoliosight-nightly.timer:6`). Its generation date is the latest session that closed at least six hours before 02:00 (`calendar.py:29-45`): Monday's for Tuesday's build, Friday's for the builds of Saturday, Sunday and Monday. Rows after that date are never used (`portfoliosight/engine/builder.py:141`).

**The gate.** The build publishes a generation only when both hold:

1. the lake run recorded in R2 started after the generation date's session closed (`generated_at` in `meta/lake.json`, `portfoliosight/data/lake.py:139-146`);
2. the latest vouched date among the lake's entries is the generation date or later.

Otherwise it publishes nothing and the site stays on the last generation, whose date and prices agree. Example: the laptop is off on Monday evening. Tuesday's build finds Friday evening's run, so it publishes nothing. Tuesday's 06:45 run brings Monday's prices, but no build follows it. Wednesday's build publishes Tuesday's generation. Monday never gets a generation of its own.

**What stops on KS-001.** Every price fetch: `refresh((1,))` (`nightly.py:320`: TSP and the tier 1 Tiingo walk), `refresh((2, 3), deadline)` (`nightly.py:344`), and the providers (`nightly.py:368-371`).

**What the nightly keeps.** The generation date and id (`nightly.py:263-264`), building the ready-made portfolios (`325`), publishing (`328-338`), deleting old generations (`345-347`), the status file (`352-353`), the cache clean-up (`354`). Deleting old generations removes built outputs only (`nightly.py:138-152`); it never touches `prices/` or `archive/`.

### 3.2 File formats

- **Inside PortfolioSight there is one format for every source.** One canonical Parquet record per symbol: `date`, `close` (raw), `tr_index`, `div_cash`, `split_factor` (demo spec line 337). It is stored at `prices/{SYM}.parquet` in R2. TSP records use it too.
- **The lake has QSE's own layout.** `eod_history/{SYM}.parquet` with date, open, high, low, close, adj_close, volume (`total_return_lake.py:135`), plus `dividends/`, `splits/`, `adj_base/` and `_adjusted_through.json`.
- **`scripts/sync_lake.py` converts lake files to the canonical format.** It reads date, close and adj_close (`portfoliosight/data/lake.py:35-42`) and writes `tr_index` as adj_close over the first adj_close. `div_cash` and `split_factor` stay empty, because the lake's adjusted close already includes them. Rows after the vouched date carry a price and no `tr_index` (`lake.py:45-61`).
- **Tiingo-era files exist only in R2,** in the canonical format, and in R2's nightly copy on the laptop drive (`scripts/r2_backup.sh:4`). None is in the lake: PortfolioSight only reads the lake (`lake.py:3`).

## 4. Fund list: how wanted funds reach QSE's fetch list

- **PortfolioSight decides what it wants.** Tier 1 and tier 2 (`data/universes/tiers.json`, `data/universes/portfoliosight.txt`), and the requested tickers (4.1).
- **QSE owns the file its job reads:** `QSE:qse/config/universes/datalake_portfoliosight.txt` (`QSE:scripts/daily_pipeline.py:150-153`).
- **A new script writes the list:** `scripts/export_qse_fetch_list.py`. Output: the symbols already in QSE's file, plus every tier 1 fund, tier 2 fund and requested ticker that is not TSP, has no "data ended" note in `tiers.json` (FIENX), and is not in QSE's core list. Sorted, one per line. Today: 356 + 247 + 26 = 629 symbols.
- **Changes flow QSE first.**
  1. Edit tier 2 or the requested list on a PortfolioSight branch and run the export.
  2. Open a QSE pull request with the new file. Merge it.
  3. On the laptop, load the new symbols into the lake (section 5).
  4. Refresh PortfolioSight's copy `data/universes/qse_portfoliosight.txt` at the merged QSE commit (it records the commit in its first line today) and merge the PortfolioSight branch.
- **A PortfolioSight test enforces the order:** every tier 1 fund, tier 2 fund and requested ticker that is not TSP and has no note must be in `qse_core.txt` or `qse_portfoliosight.txt`. Nothing can reach the menu before QSE fetches it.
- **QSE's experiment universe stays untouched.**
  - The dataset build is given the core file only (`QSE:scripts/daily_pipeline.py:1158-1159`). The second file adds to the price fetch only (`864-881`), in separate quote batches (`888-891`), and a symbol in both is fetched once (`813-828`).
  - One hole to close: when the core file is missing, the pipeline rebuilds it from every file in the lake (`daily_pipeline.py:699-715`) and fetches by the same listing (`864-867`). That would pull every PortfolioSight symbol into the experiment universe. The lake already holds 356 such symbols; this change adds 273. QSE pull request Q1 makes a missing core file stop the run.

### 4.1 Requested tickers

- **Where they go: tier 3, through a new file.** `data/universes/requested.txt`, one ticker per line, with a comment giving the date and the source. `tiers.json` lists it as a third tier 3 file, so each ticker is a stock (`portfoliosight/data/universe.py:67-90`) and is offered once the lake vouches it, like every tier 3 symbol (`scripts/sync_lake.py:14-16`). Tier 2 is for curated funds and would give them a fund's kind.
- **First content:** the 29 tickers of Appendix A. The export adds 26 to QSE's fetch list; FCX, TSM and WMT are in the core list already.
- **Names:** each gets an entry in `data/universes/funds.json` (section 8).
- **How a later request reaches the list.** By hand, no automation:
  1. The owner, or a session with admin access, reads the log (`GET /api/ticker-requests`).
  2. Add the tickers worth serving to `requested.txt`. Leave out test entries and typing mistakes.
  3. Follow the four steps above.
- **A ticker Schwab does not know** gets nothing written by the load and is reported (section 5). It stays off the menu.
- **The report of P2** lists each requested ticker as served or not served, with the reason.

## 5. Starting or rebuilding a fund from the lake's own files (QSE)

A fund's starting point is built from the lake's own Parquet files: its raw closes plus its recorded dividends and splits. No outside history is needed, so EODHD is never required to keep, extend or repair the price history (decision 3). This is a general QSE capability, used for every new symbol and available for any symbol the lake holds.

The existing repair cannot do it: `repair_symbol` takes the starting point from the pre-repair EODHD copy (`QSE:qse/data/total_return_lake.py:1849-1962`, `1994-2000`), and an `adj_base_gap` block has no way out without EODHD (2.4, fact 1).

One owner-run command on the laptop, `QSE:scripts/lake_start.py` (new), with two steps that also run separately. It holds the daily pipeline's lock while it runs, as the repair does (`QSE:scripts/repair_lake_total_return.py:63-79`).

**Step A, load. New symbols only.**

1. Fetch Schwab's daily history as far back as it goes, and yfinance's dividends and splits.
2. Check. All must pass, or nothing is written and the symbol is reported with the reason:
   - Schwab returned rows, and every close is a positive number.
   - yfinance answered the dividend and split request. No answer is not "no dividends".
   - On every date both have, Schwab's close agrees with yfinance's close. yfinance's prices are compared, never stored. The tolerance is set from the G0 sample and then checked on funds outside it; the repair's own comparison allows 3 percent (`total_return_lake.py:1783-1810`; `corporate_actions.py:77`), which is too loose to catch a bad price.
3. Write the lake's files: raw closes (Schwab's bars are split-adjusted, so splits are undone as the lake stores them: `total_return_lake.py:1756-1761`; `QSE:scripts/daily_pipeline.py:842-844`), and the dividend and split records with source `yfinance`.

**Step B, build. Any symbol.**

1. Read the symbol's own files. The adjusted close of each row is its raw close times the factor of every later recorded dividend and split: the formula the lake already uses (`corporate_actions.py:471-472`).
2. Write those values as the starting point, through the last finished session, with the anchor set to that date. From then on the daily job treats the symbol like any other: a row inside a starting point is "stored value times the factors after the anchor" (`corporate_actions.py:471`, `502-503`). The file's metadata records that it was built from the lake's files, and when (the existing evidence field, `total_return_lake.py:137`, `458-464`).
3. Vouch the symbol through that date.

For a new symbol, after step B the lake's adjusted series must agree with yfinance's own adjusted close, on the dates both have, within the lake's factor tolerance (`total_return_lake.py:129`); if not, the symbol is not vouched and is reported.

Rules:

- **Existing starting points stay valid.** Step B never touches a symbol that has one, unless the owner names it with `--rebuild`.
- **`--rebuild`, owner only, per symbol.** For a symbol blocked by `adj_base_gap` or with a damaged file. The new file replaces the old only when the two agree, within the factor tolerance, on every date both have. Otherwise nothing is written and the difference is reported. The old file is kept under another name, never deleted.
- **Nothing in the lake is dropped.** A symbol the daily job reached before its load has a short unvouched file. The load keeps those rows; where Schwab returns the same dates, the closes must agree or nothing is written.
- **History starts where Schwab's starts.** yfinance's older prices are not used. If that is later than the record the site has today, see open question 1.
- **A symbol Schwab returns nothing for** is reported and not loaded. The owner may then name it for yfinance prices (decision 2): its history and its daily prices come from yfinance and it is labelled (section 6). Open question 2 covers a Schwab outage.

**Dividends for mutual funds: the action policy, built only if G0 shows it is needed.**

It is kept in the design because of fact 3 in 2.4. If a mutual fund's Schwab quote has no dividend block, its vouched date moves only every few sessions. A mix is computed on the days all its funds have (`portfoliosight/engine/windows.py:110`), so every mix holding a mutual fund would lose its latest days, and prices would not be current for the 02:00 build. If instead Schwab's amount leaves out the capital-gain part, the fund drops off the vouched list at each year-end distribution.

- If G0 shows Schwab's quote carries the full amount on the ex-date for the sampled mutual funds: the policy is not built. Every symbol keeps today's behaviour.
- Otherwise each symbol gets a policy, set at load and kept in the lake's state file:
  - `schwab+yfinance` (default): today's behaviour, unchanged.
  - `yfinance` (mutual funds, and any symbol whose Schwab quote has no dividend block): Schwab's dividend amount is not used, so it cannot raise a conflict. Every run asks yfinance for the fund's actions. If the request succeeds, the fund is vouched through its last price row. If it fails after the retries, the date does not move. "Confirmed" for these funds means "yfinance lists it"; there is no second source. Cost: one yfinance request per such fund per run (124 mutual funds today, two runs a day).

## 6. Labels, statuses and migration

**After the change**

| Field | Values | Meaning |
|---|---|---|
| `source` | `lake`, `tsp` | Who keeps the record. `seed`, `tiingo` and `seed+tiingo` are no longer written (`portfoliosight/data/manifest.py:36`). An entry that has one keeps it until the lake takes the fund. |
| `status` | `ok` | Served: checked through a date at most 10 trading days old. |
| | `stale` | Was served; now more than 10 trading days old. Reason: `no data since {date}` or `corporate actions not yet verified after {date}` (`manifest.py:119-136`). |
| | `unavailable` | No usable data (FIENX). |
| `relies_on_yfinance` | true or false | True when yfinance is the source of a dividend or split after 2026-03-20 (`scripts/sync_lake.py:77-81`). Unchanged. After this change it is true for nearly every fund that pays. |
| `prices_from_yfinance` | true or false | New. True only for a fund whose prices come from yfinance because Schwab has none (decision 2). |

`pending` is no longer given (`manifest.py:109-110`). A newly listed fund has no entry until the lake first vouches it, and appears on the menu that day.

**Public launch.** The rule "review symbols with `relies_on_yfinance` before public launch" is dropped (decision 10; demo spec lines 356 and 511). Nothing replaces it as a launch gate. What remains: the two labels stay in the catalog as information, every new symbol passes the checks of section 5, and late distributions are reviewed after December 2026 (decision 9).

**Sync rule changes**

- **The lake wins for every non-TSP symbol.** The rule that a tier 1 or 2 fund stays with the provider goes (`scripts/sync_lake.py:82-83`, `191-193`, `230-231`).
- **No release to `seed`.** A symbol the sync has taken stays `source: lake`. When it falls behind it keeps its last record and becomes `stale`; it returns to `ok` at the first sync that finds it inside the window (today it is released: `sync_lake.py:396`; `portfoliosight/data/lake.py:34`, `165-189`).

**Migration of `tiingo`, `seed+tiingo` and `seed` records: nothing is deleted**

- **Whole record or nothing.** When the lake vouches a fund inside the window, the sync replaces the fund's served record with the lake's full history (`portfoliosight/data/lake.py:45-61`; `sync_lake.py:252`). No row of the old record is joined to the new one. The only code that joins a new tail onto an old record is the Tiingo downloader (demo spec line 289), and it retires.
- **Order for each fund.** A step that fails stops that fund, with its old record still in place:
  1. The lake vouches the fund inside the window.
  2. Its row is written to the report `meta/migration.json`: old source, old and new first date, the dates both cover, growth of one dollar over those dates from each record, and the largest calendar-year difference.
  3. The old record is copied to `archive/prices/{SYM}.{old source}.parquet` and read back. The bytes must match.
  4. The lake's record is written to `prices/{SYM}.parquet`.
  5. The entry becomes `source: lake`, and the report row records the archive key.
- **What "moved" means.** The old and the new record share one key. So the old record is copied to the archive, the copy is checked, and only then is it replaced in place. The live key is never empty, and the old bytes exist at every moment.
- **The archive is permanent.** Nothing reads it for the site, and no job removes anything under `archive/`. R2's copy on the laptop drive takes it like every other key (`scripts/r2_backup.sh:4`).
- **Not touched at all:** FIENX, and any seed or Tiingo-era record of a fund the lake never vouches. They stay at their keys with their labels, not served.
- **A difference does not block replacement** (decision 2). The report is how the owner sees it.
- **The first date can change.** A view that needs more history than the lake has sets the fund aside with the existing reason `history starts {date}, not enough for the {window} view`. See open question 1.
- **While a fund waits** (the lake has not vouched it): nothing touches its record or its label. It is served from its last Tiingo update for up to 10 trading days, showing that date. After that it is `stale`, listed as set aside with `no data since {date}`, until the lake vouches it.
- **Order, to avoid a gap:** load the funds into the lake first, then ship the new sync rules, then stop the Tiingo walk. The walk never touches a `lake` entry (`portfoliosight/data/refresh.py:53`), so the two can overlap safely. If Tiingo access ends sooner, the 10-day rule is the only buffer.
- **Done when** no `ok` entry has an old source. Leftover entries are listed for the owner and stay where they are.

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
| The whole price step | One fire a day, no retry (`QSE:scripts/daily_pipeline_cron.sh:8`, `25-26`) | Two runs a day (3.1). After each, one more fire two hours later (20:00 and 08:45 PT) that runs the price step only, and only if that run's verdict was "failed". |
| Sync to R2 | Polls every 10 minutes; a record that could not be stored is retried at the next poll (`scripts/sync_lake.py:428-443`) | Same, in both windows. |
| TSP file | One try, on KS-001 | 3 tries, 2 s to 20 s, per sync poll, on the laptop. |

A missed day needs no special repair: each run asks Schwab for the last 30 days and fills what is missing (`daily_pipeline.py:805`, `896-909`).

### 7.3 Alerts

Every alert is sent two ways by one helper:

- **healthchecks.io,** which QSE already uses (`QSE:scripts/backup_local.sh:1152-1155`, `QSE:scripts/options_pull_cron.sh:169-170`) and which also alarms when a check goes silent (laptop off, cron dead). It works as soon as the owner creates the check and sets its address.
- **Pushover,** through the existing sender (`QSE:scripts/daily_pipeline.py:186-211`). It sends nothing until `PUSHOVER_TOKEN` and `PUSHOVER_USER` are set (`daily_pipeline.py:188-191`), and starts working the day they are, with no code change. The Pushover code is not removed. The PortfolioSight sync gets the same small sender, reading the same two names.

Today's state: the Schwab login alerts go to Pushover (`daily_pipeline.py:326`, `384`), whose keys were never set, so they are dropped. A healthchecks.io ping for the login exists in code (`daily_pipeline.py:214-233`) and sends nothing unless `QSE_SCHWAB_HC_URL` is set. Whether it is set on the laptop is unverified; the owner reports that no alert reaches him.

| Alert | Check | Rule |
|---|---|---|
| Schwab login about to expire | `QSE_SCHWAB_HC_URL` (exists, `daily_pipeline.py:224`) | Fails from 2 days before expiry. Today it is 4 days and weekdays only, because a shorter window can fall on a weekend (`daily_pipeline.py:164-176`). So the check also runs on Saturday and Sunday: one more cron line on the laptop that runs the check only and never opens the login flow. |
| Price update failed | `QSE_LAKE_HC_URL` (new) | After each of the two runs: a success ping after a good price step, with counts in the message; a fail ping when the update failed (below). |
| Sync failed, or a fund is about to drop | `PS_SYNC_HC_URL` (new) | Success ping when a window's lake run is in R2. Fail ping when: the lake run is not complete by the window's last poll (`scripts/sync_lake.py:143-150`); records could not be stored (`459-465`); the sync crashed (`497-505`); the TSP file could not be fetched in the window; or any tier 1 or 2 fund is 5 or more trading days late, listed by ticker (halfway to the drop). Today these are log lines nobody is sent (`scripts/install_sync_lake_cron.sh:10`; demo spec line 360, "Alerts: none"). |

**"The update failed" means any one of:**

1. The price step did not finish: it stopped before rewriting `_adjusted_through.json`. This includes a Schwab login that expired or was blocked (`daily_pipeline.py:307`, `335`, `389`).
2. Schwab is down: daily bars failed, after retries, for 10 symbols in a row (the count the yfinance breaker already uses), or the quote batch for PortfolioSight's symbols failed.
3. yfinance is down: its breaker tripped (`total_return_lake.py:727-734`).
4. Nothing moved: after the evening run of a trading day, the lake's latest vouched date is not that day. The rule needs to know exchange holidays. QSE counts weekdays today (`corporate_actions.py:1163-1171`), so Q3 adds `exchange_calendars`, the library PortfolioSight uses (`pyproject.toml:20`; `portfoliosight/data/calendar.py:20-21`).

Not a failed update: single symbols with an error, no data, a conflict or an unconfirmed split. They are counted in the ping message and reach the owner through the "about to drop" alert if they last.

The verdict is about the price step only. In the 06:45 run the EODHD step runs after it (`daily_pipeline.py:1729-1731`) and cannot block prices; the evening run has no EODHD step. Whether EODHD's 403 makes that step, and so the pipeline, exit with an error is unverified (`daily_pipeline.py:753`); the alert must not depend on the pipeline's exit code.

## 8. Names and kinds

Today a name comes from the lake's EODHD files, then the catalog, then the ticker (`portfoliosight/data/lake.py:84-130`; `scripts/sync_lake.py:239`); names still missing come from Tiingo (`scripts/backfill_names.py`; demo spec line 355). A fund's kind comes from Tiingo, or defaults to "etf" (`sync_lake.py:255`). Neither source continues for the new symbols: Tiingo retires, EODHD's name files come from fundamentals, which is paused, and QSE asks EODHD about its core list only (`QSE:scripts/daily_pipeline.py:699`, `726-727`).

- **New committed file `data/universes/funds.json`:** symbol to `{name, kind}` for every tier 1 and tier 2 fund that is not TSP, and for every requested ticker (kind `stock`). Funds are filled once from the names the catalog shows today, so no displayed name changes; their kinds come from the section headings of the tier 2 file (Appendix A). The owner edits it like any other list.
- **Order for a name:** `funds.json`; then the lake's archived `fundamentals_full` file; then the lake's US symbol list; then the catalog's current name; then the ticker. Stocks outside `funds.json` keep today's behaviour. The archived files stay on the laptop and are simply no longer refreshed.
- **A test requires an entry** with a real name for every tier 1 fund, tier 2 fund and requested ticker, so nothing new can ship unnamed.
- yfinance names are not used: they are abbreviated (2.2).

## 9. Work breakdown

In order. Each pull request has a regression test that fails before and passes after; existing tests stay as they are unless the feature they test is removed (P5). No pull request here does R2 backup work (decision 12), and all new code follows section 11.

**G0. Measurement: Schwab on the laptop (QSE repo, small script, owner or Marshal runs it).** Not a gate on whether Schwab has mutual funds (decision 2).
- Files: `QSE:scripts/probe_schwab_funds.py` (new); the saved answers as a test fixture next to `QSE:tests/data/schwab_quotes_fundamental_2026-10-14.json`; a short report in `QSE:docs/reviews/`.
- Asks Schwab, for VTSAX, VBIAX, VGSTX, FXAIX, SWPPX, DODGX, PTTRX, two ETFs (VTV, SCHO) and four requested tickers (NSRGY, LVMUY, SIEGY, ASML): the daily price history as far back as it goes, and the quote with its dividend block.
- Answers:
  - (a) History depth: the first date Schwab returns for each, and which request reaches furthest back.
  - (b) Fields: does the quote carry dividend fields for mutual funds, and does VBIAX's amount for 2025-12-23 equal 1.628.
  - (c) Timing: asked at 14:00, 16:00, 18:00 and 20:00 PT on one trading day, when is that day's bar present for a mutual fund and for an ETF, and does it change afterwards. Does a 06:45 PT request return that day's unfinished session.
  - (d) Coverage: do the OTC tickers return prices.
- Decides: the evening run time (3.1); whether the action policy is built (section 5); whether open question 1 needs an answer; the price tolerance of the load.

**P1. PortfolioSight: fund metadata, the requested list and the fetch-list export.**
- Files: `data/universes/funds.json` (new), `data/universes/requested.txt` (new), `data/universes/tiers.json`, `scripts/export_qse_fetch_list.py` (new), `portfoliosight/data/universe.py`, `tests/data/test_universe.py`.
- Tests: every non-TSP tier 1 and 2 fund and every requested ticker has a name that is not its ticker, and a kind. A requested ticker is a tier 3 stock. The export contains QSE's current list and every wanted symbol outside the core list; no TSP id, no FIENX, no core symbol; sorted, no repeats.
- Acceptance: the export prints 629 symbols.

**Q1. QSE: fetch list and universe guard.**
- Files: `QSE:qse/config/universes/datalake_portfoliosight.txt`, `QSE:scripts/daily_pipeline.py` (`699-715`, `864-867`), `QSE:tests/scripts/test_daily_pipeline.py`.
- Tests: with a core list of N and a second list of M other symbols, the price step receives N + M and the dataset command names the core file only. With the core file missing, the run stops and writes no universe file.
- Acceptance: the next run logs 629 PortfolioSight-only symbols (`daily_pipeline.py:822-827`); the dataset has the same tickers as the day before.

**Q2. QSE: start or rebuild a symbol from the lake's own files.**
- Files: `QSE:qse/data/total_return_lake.py`, `QSE:qse/data/corporate_actions.py`, `QSE:scripts/lake_start.py` (new), `QSE:tests/unit/data/test_total_return_lake.py`, `QSE:tests/scripts/test_lake_start.py` (new).
- Tests:
  - Build: a symbol with raw closes, two dividends and one split on file, and no starting point, ends with the hand-computed adjusted closes, a starting point, and a vouched date equal to its last finished session. No network call is made.
  - After the build, a new dividend lowers every earlier adjusted close by its factor and the vouched date advances.
  - A symbol with an existing starting point is left byte for byte as it was. With `--rebuild` and agreeing values the file is replaced and the old one still exists under its other name. With disagreeing values nothing is written.
  - A symbol blocked by `adj_base_gap` is vouched after `--rebuild`.
  - Load: a symbol with no lake files, given made-up Schwab bars with one split and matching yfinance actions, ends with raw closes and the action records on file.
  - Schwab closes that disagree with yfinance's: nothing written, reason reported. A symbol Schwab does not know: nothing written. A failed yfinance request: nothing written.
  - A short file the daily job wrote earlier keeps its rows after the load.
  - A second run changes nothing.
  - Only if G0 calls for the policy: a `yfinance`-policy fund with no Schwab dividend block advances on each of five runs in a row; a failed yfinance request leaves its date where it was; a Schwab amount that differs from yfinance's raises no conflict for it.
  - Every existing lake test passes unchanged.
- Acceptance, on the laptop: a report for the 273 new symbols with the number vouched and each failure's reason. Held-out check: for 10 funds not used during development, growth over the last 10 years from the lake equals yfinance's adjusted close within the lake's factor tolerance (`total_return_lake.py:129`), and Schwab's closes agree with yfinance's within the tolerance set in G0.
- PortfolioSight then refreshes `data/universes/qse_portfoliosight.txt` (section 4, step 4); the order test of section 4 lands with that commit.

**Q3. QSE: the evening run, retries, the verdict and the alerts.** Independent of Q1 and Q2.
- Files: `QSE:scripts/daily_pipeline.py` (`176`, `186-233`, `896-909`, `1684-1736`), `QSE:scripts/daily_pipeline_cron.sh`, `QSE:qse/data/total_return_lake.py` (`630-643`), `QSE:pyproject.toml`, `QSE:tests/scripts/test_daily_pipeline.py`.
- Tests:
  - The price-only flag runs the login check and the price step and nothing else: no EODHD call, no dataset build.
  - A price request that fails twice and then succeeds yields its bars. One that fails three times is counted and the run goes on. An unknown-symbol answer is not retried.
  - Ten Schwab failures in a row, or a tripped yfinance breaker, give "failed" and one alert with the reason.
  - A day with three failed symbols gives "ok" and a success ping with counts.
  - An evening run on a trading day that leaves the latest vouched date behind gives "failed"; on an exchange holiday it gives "ok".
  - Each alert makes one healthchecks.io request and one Pushover request when both are set; only the first when the Pushover names are unset; none when neither is set. A request that fails never fails the run.
  - Login check: 2.5 days left is healthy, 1.9 is an alert. The weekend check only reports; it never opens the login flow.
- Acceptance: the owner creates the check and sets `QSE_LAKE_HC_URL`; a forced failure reaches the owner; a good run turns the check green; the evening cron line is installed and one evening run completes.

**P2. PortfolioSight: sync rules, labels, the archive, the second window and TSP.** After Q2's load.
- Files: `portfoliosight/data/manifest.py`, `portfoliosight/data/lake.py`, `scripts/sync_lake.py`, `scripts/install_sync_lake_cron.sh`, `tests/data/test_manifest.py`, `tests/data/test_lake.py`, `tests/data/test_sync_lake.py`.
- Tests:
  - A fund vouched k sessions before the generation date is `ok` for k from 0 to 10 and `stale` at 11, across a holiday week.
  - A `tiingo` fund the lake vouches gets a record equal to the lake's whole history, `source: lake`, its name unchanged, a row in the migration report, and an archive copy whose bytes equal the old record.
  - When the archive copy cannot be written or does not read back equal, the old record and its label are unchanged.
  - A fund the lake does not vouch keeps its record bytes and its label. FIENX is unchanged.
  - After any run the store holds every key it held before.
  - A taken symbol that falls behind stays `lake` and `stale`, and comes back to `ok`. No run writes `seed`.
  - Name and kind come from `funds.json`.
  - Each window: a run written before the window's start is not synced; one written after is.
  - TSP: fetched on the laptop after the lake sync; a failed fetch keeps the funds served inside the 10-day rule.
  - Alerts: run not complete at a window's last poll fails; a synced run succeeds; a fund 5 sessions late fails and is named; no address, no request.
- Acceptance: a dry run on the laptop prints how many funds move to the lake and lists each requested ticker with its outcome. After the real run, `meta/migration.json` exists, every replaced fund has an archive copy, and the number of `ok` entries with an old source is reported.

**P3. PortfolioSight: the page shows the as-of date.** With or after P2.
- Files: the Funds table in `web/src/`; the copy table of demo spec section 3.6.
- Tests: a late fund shows "prices as of {date}"; a current fund shows nothing.
- Acceptance: `npm run lint && npm run typecheck`, then `npm run build` and `npm run e2e:local`.

**P4. PortfolioSight: daily build with no price fetch, behind the gate.** Only after P2 runs TSP on the laptop, and when P2 reports zero `ok` entries with an old source or the owner accepts the list of funds left behind.
- Files: `portfoliosight/jobs/nightly.py`, `deploy/docker-compose.yml`, `tests/jobs/test_nightly.py`, `tests/deploy/`. The timer file is not changed.
- Tests: with no provider and no network, the run builds and publishes from the store. A lake run that started before the generation date's close publishes nothing and leaves the current generation in place; so does a run that started after it but whose latest vouched date is older than the generation date; a run that meets both publishes. A fund 4 sessions late is included with its date; one 11 late is set aside with its reason. After pruning, every key under `prices/` and `archive/` is still there.
- Acceptance: on KS-001 the day after, the current generation is the previous session's, built at 02:00; the log shows no outside price request; the KS-001 secrets file no longer needs the Tiingo key.

**P5. PortfolioSight: remove the retired code and amend the demo spec.** Needs the owner's go.
- Removes code only, no stored data: the Tiingo provider, the Tiingo part of the downloader and its request budget, the seed script and the Tiingo name backfill, with the tests of those features. The TSP fetch keeps the part of the downloader it uses. Amends the sections of Appendix B (documents only).
- Acceptance: no "tiingo" left under `portfoliosight/` or `scripts/`; lint, type check and tests pass; coverage stays above 80 percent.

## 10. Open questions and risks for the owner

**Open questions**

1. **Only if G0 finds Schwab's daily history starts later than a fund's record does today** (VGSTX starts 1985 in the record the site serves). What should the fund's history be?
   - a (recommended): Schwab's history only. It follows decision 2 and keeps one price source per fund. Cost: the fund's history gets shorter, and long views set it aside; the older record stays in the archive, not served.
   - b: fill the earlier years from yfinance prices, labelled, with the join date recorded. Cost: two price sources inside one fund's history, and yfinance's older dividend record is known to differ in one case (2.2).
2. **When Schwab is down for a day or more** (login lapsed, outage), should the job fill those days from yfinance?
   - a (recommended): no. The alert fires, late funds stay served for 10 trading days with their date, and Schwab's 30-day request fills the gap when it returns. yfinance prices are used only for a fund Schwab cannot supply at all, named by the owner and labelled.
   - b: yes, automatically after a set number of failed runs, labelled, and replaced by Schwab's prices when it returns. Cost: more code, and days whose source changes afterwards.

**Risks to know**

- **The laptop must be on and awake at both run times.** A missed evening run means no new generation the next morning (3.1); the alert says so.
- **The evening time rests on a 2009 document and on no Schwab measurement** (3.1).

**Things only the owner can do:** create two healthchecks.io checks and put their addresses in `~/.secrets/qse.env` (`QSE_LAKE_HC_URL`) and `~/.secrets/portfoliosight.env` (`PS_SYNC_HC_URL`); confirm `QSE_SCHWAB_HC_URL` is set; later, set the two Pushover names; run G0 and the load on the laptop (or have Marshal do it); install the new cron lines.

**Still unverified:** how far back Schwab's daily history goes; Schwab's dividend fields for mutual funds; when Schwab shows a mutual fund's price for the day; whether Schwab returns prices for the OTC tickers; each of the 123 ETFs on Schwab; whether the lake's last row at 06:45 PT is an unfinished session; when tsp.gov posts a day's price; why FCX, TSM and WMT are not served; whether `QSE_SCHWAB_HC_URL` is set on the laptop; whether EODHD's 403 fails the pipeline; whether the lake holds name files for any of the new symbols; which of the 77 tier 1 and 2 funds already on QSE's lists the lake vouches today; whether a second daily price run changes anything QSE's dataset build reads. The lake is not on the machine this spec was written on.

## 11. Portability

The job runs on the laptop for now. New code must not assume that, so the job can later run on the devbox or a server and back up to R2 (decision 12).

- **Backup today.** No R2 backup work in this spec. The laptop's nightly backup already copies the lake to the USB drive: it mirrors everything under `data/` and `runs/` to `/mnt/d`, and never deletes there (`QSE:scripts/backup_local.sh:5-9`, `163-169`, `377-381`, `1249-1250`). The drive is often absent, and the backup then skips (`backup_local.sh:5-9`, `519`). The R2 leg leaves the lake out, which is what the parked pull request #181 would change (`backup_local.sh:22-23`).
- **The lake's folder is a setting.** Today QSE fixes it relative to the repo (`QSE:scripts/daily_pipeline.py:136-137`). New QSE code reads it from one setting with today's path as the default. PortfolioSight already takes it as an option (`scripts/sync_lake.py:472`).
- **Run times and sync windows are settings.** Today they are constants and cron lines (`scripts/sync_lake.py:73-74`; `scripts/install_sync_lake_cron.sh:10`).
- **No hardcoded home path in new code.** Existing examples not to copy: `QSE:scripts/backup_local.sh:163`, `QSE:scripts/daily_pipeline_cron.sh:182`, `QSE:scripts/daily_pipeline.py:706`.
- **Lock, alert addresses and keys come from the environment,** as the pipeline lock already does (`daily_pipeline_cron.sh:100`).
- **No new step needs a screen or a browser.** The weekly Schwab login does today (`daily_pipeline.py:236-242`); moving the job to a server means solving that, which is outside this spec.
- **Each new command has a test that runs it against a lake in a temporary folder,** with every path passed in.

## Expectations

Written in the owner's voice. They say what done means; section 9 says how it is built. S is a success scenario, F a failure that looks like success, M a must-not.

### Success scenarios

- **S1.** I can pick any fund or stock I asked for once the lake has checked prices for it. I do nothing on the site to make that happen. Until then it is simply not on the menu.
- **S2.** For the 29 tickers I asked for, I get a list that says, one by one, "on the menu" or "not yet, because". None is silently missing.
- **S3.** When I open the site the morning after a trading day, the ready-made portfolios are dated that trading day and their prices run through its close.
- **S4.** When one fund is late, I can still use it for 10 trading days, and beside it I see the date its prices run to. On the 11th trading day it is set aside and I am told why.
- **S5.** I get an alert two days before the Schwab login runs out, on a weekend too.
- **S6.** I get an alert on any day the price update fails, and also when nothing ran at all because the laptop was off.
- **S7.** Alerts reach me through healthchecks.io now. The day I add my Pushover keys they also arrive there, with no code change.
- **S8.** One job on my laptop updates stock and fund prices. The TSP prices are fetched on the same laptop. The server that runs the site fetches no prices.
- **S9.** If EODHD and Tiingo both stopped answering tomorrow, every price would still update, I could still add a fund, and I could still rebuild a fund's history from the files I already have.
- **S10.** After the move, every price record from before still exists. I can find each replaced one in the archive, and a report tells me, fund by fund, how the old and the new history differ.
- **S11.** QSE's experiments run on the same list of stocks the day after PortfolioSight adds funds as the day before.
- **S12.** When someone asks for a new ticker later, I or a session can add it by following a short written procedure, with no new code.
- **S13.** I can move the price job to another machine by changing settings, not code.

### Failure scenarios

- **F1.** A ready-made portfolio shows yesterday's date while its prices stop a day earlier, because the evening update was missed and the build published anyway.
- **F2.** The update "ran", so a fund looks current, but one of its payouts was never recorded and its growth is too low.
- **F3.** A fund quietly gets its prices from yfinance on a day Schwab fails, and nothing on the fund says so.
- **F4.** A ticker I asked for is added to a list and counted as done, but it never appears, because Schwab has no prices for it and nobody told me.
- **F5.** An old record is "archived" by writing the new one over it. The copy was never checked, and the old prices are gone.
- **F6.** An alert is "sent" to a channel that has no keys, as happens today, and is counted as delivered.
- **F7.** The update succeeds for most funds while Schwab is down for the rest, the day is counted as good, and no alert fires.
- **F8.** A fund's history gets shorter in the move, for example it used to start in 1985 and now starts later, and no report line says so.
- **F9.** A list file goes missing, the job rebuilds it from every file in the lake, and QSE's experiments silently gain hundreds of funds.
- **F10.** A late fund is still served on day 11, or is served with no date beside it, so an old price looks fresh.
- **F11.** A year-end payout that yfinance lists a day late shows as a one-day drop. I accepted that for one day. It is a failure if the drop is still there after the next update.
- **F12.** Rebuilding a starting point from the lake's files changes the history of a fund that already had a good one.
- **F13.** A fund is replaced by the lake's record before the lake has checked it, so the site trades a checked history for an unchecked one.

### Must-nots

- **M1.** No price history is ever deleted. Not in the lake, not in R2, not as a clean-up, not because a newer copy exists.
- **M2.** I never see a fund's prices dated newer than they are, and the site never publishes a day whose prices it does not have.
- **M3.** Nothing requires EODHD or Tiingo: not the daily update, not adding a fund, not rebuilding a history.
- **M4.** QSE's experiment universe never changes because PortfolioSight added funds.
- **M5.** No price is fetched anywhere but the laptop job, until I move it.
- **M6.** yfinance prices are never used for a fund Schwab can supply, and never without a label.
- **M7.** A fund is never served past the date the lake has checked it through.
- **M8.** FIENX's record is never touched.
- **M9.** An existing starting point is never replaced unless I named that fund.
- **M10.** The Pushover code is never removed, and a failed alert never stops the price update.

### Open points

The expectations leave two boundaries undecided, because the spec does: what a fund's history should be when Schwab's is shorter than the record I have today, and whether a Schwab outage is filled from yfinance. Both are in section 10.

## Appendix A: tier 1 and tier 2 funds outside QSE's lists (recount, 2026-11-16)

Counted with `portfoliosight.data.universe.load_tiers()` against `data/universes/qse_core.txt` (1,038 symbols; PortfolioSight's copy of QSE's core list, which is not on this machine) and `QSE:qse/config/universes/datalake_portfoliosight.txt` (356).

| | Funds | Outside the QSE lists | Of which |
|---|---|---|---|
| Tier 1 | 56 | 33 | 14 ETFs, 3 mutual funds, 16 TSP |
| Tier 2 | 317 | 248 | 123 ETFs, 125 mutual funds (FIENX among them) |
| Tier 1 and 2 together | 341 | 264 | 123 ETFs, 124 mutual funds, 16 TSP, 1 other (FIENX) |

The 17 tier 1 funds that are not TSP are all in tier 2 as well. Kinds are taken from the section headings of `data/universes/portfoliosight.txt`. All 125 mutual funds, and no ETF, have five letters ending in X. To be added to QSE's fetch list: 247 funds (the ETFs and mutual funds; not TSP, not FIENX) and the 26 requested tickers below, 273 in all.

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

**Requested tickers (29; section 4.1):** ASML ATLKY AZN BHP BUD CMWAY DB EADSY FCX FRCOY HSBC ISNPY LRLCY LVMUY LYG MTSUY MUFG NSRGY NVS RIO RY SAP SIEGY SPOT TM TSM UL UNCRY WMT. In QSE's core list already: FCX TSM WMT. New to QSE's fetch list: the other 26.

## Appendix B: demo spec sections to amend (in P5)

| Demo spec | What changes |
|---|---|
| Line 22, data decisions | "Tiingo; no yfinance, no Schwab" becomes Schwab plus yfinance through the lake; the lake is the source, not a one-time seed. |
| 5.1, lines 277-289 | The Tiingo adapter and the tail splice retire. |
| 5.2, lines 295-308 | Served rule 3 becomes 10 trading days; the Tiingo plan table, the starter slice and the limits probe retire; tier 2 funds and requested tickers come from the lake. |
| 5.3, lines 314-331 | `source` values; `meta/provider_limits.json` and `meta/budget.json` retire; `meta/migration.json`, the `archive/` prefix and `prices_from_yfinance` added. |
| 5.4, lines 347-360 | The seed and the downloader's Tiingo walk retire; lake sync precedence, release to seed and the 3-session rule change; the sync gains the evening window and the TSP fetch; the nightly loses its price fetches and gains the gate; "Alerts: none" becomes section 7.3. |
| 5.5, line 364 | The laptop sync fetches TSP; the 10-day rule for TSP. |
| 9.6, lines 507-514, and 13, lines 581-584, 592 | The plan limits and seed quality risks retire; the Tiingo license note retires (owner, 2026-11-16: the data is used for analysis and results, not redistributed); the yfinance review rule is removed (decision 10). |
| Appendix A, line 608 | "not the provider" wording. |
| `2026-10-13-portfoliosight-demo-design.assertions.md` | 14 lines that name Tiingo or the 3-session rule. |
