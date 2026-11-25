# Single Price Source Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One job on the laptop keeps every price (Schwab prices, yfinance dividends and splits, through the QSE lake); PortfolioSight serves only what the lake has checked, keeps every old record, and the server fetches no prices.

**Architecture:** QSE gains a guard on its experiment list, a way to start or rebuild a symbol from the lake's own files, an evening price run, retries, a pass or fail verdict and alerts. PortfolioSight gains fund metadata and a requested list, a sync in which the lake wins and every replaced record is archived first, a second sync window with the TSP fetch, an as-of date on the page, and a daily build that fetches nothing and publishes only behind a gate.

**Tech Stack:** Python 3.12, pandas, pyarrow, tenacity, requests, exchange_calendars, pytest (both repos); React, TypeScript, vitest, Playwright (page); cron on the laptop, systemd on KS-001, Cloudflare R2.

**Spec:** `docs/specs/2026-11-16-single-price-source-design.md` (main, commit 80aa189). Executors read both. "Spec N" below means section N of that file.

Paths are in the PortfolioSight repo unless they start with `QSE:` (relative to `/home/jeff/programming/quant-scenario-engine`).

## Global Constraints

Every task carries these.

- Nothing merges or goes live without the owner. Each PR goes through the owner's review loop first.
- No file under `assertions/` changes (the frozen checks, `README.md:23`). A task that cannot pass with a frozen check as it is carries the mark **BLOCKED-D3** and is not started until the owner answers decision D3 below.
- New tests are fast: the smallest inputs that show the behavior (frames of 12 rows or fewer where the test builds its own), no network, no real waiting (clocks and sleeps are passed in). The PortfolioSight suite is already over the frozen time limit of 1200 s (`assertions/2026-10-13-portfoliosight-demo-design/tests/test_a_ps_65_quality_gates_docs.py:148`).
- QSE's experiment universe never changes: no task writes `data/tft/raw/eodhd/universes/datalake_us_core.txt` (`QSE:scripts/daily_pipeline.py:149`).
- Another session (QSE Step 2) is taking a frozen copy of the lake. No QSE PR changes a stored row, a dividend or split record, or a starting point of a symbol the lake already holds, except through the owner-named `--rebuild` path of Q2.
- Portability (spec 11): no home path, laptop path or schedule written into new code. The lake folder, state folder, lock, run times, sync windows, alert addresses and keys are settings or environment names. Each new command has a test that runs it against a lake in a temporary folder with every path passed in.
- No R2 backup work for the lake (spec 1, decision 12).
- In PortfolioSight code under `portfoliosight/data`, `engine`, `api`, `jobs` and `scripts`, no line may hold the bare word `yfinance` and no URL may name a host outside the four allowed ones, comments included (`tests/test_hygiene.py:22-31`, frozen A-PS-10). Field names such as `prices_from_yfinance` are fine; comments say "the Yahoo Finance library". Alert addresses come from the environment.
- Never read `~/.secrets`. Source it. Never print a secret.
- Tests assert on outputs and stored state, with exact values. No test is deleted, skipped or loosened to pass. Where this plan changes the pinned value of an existing test, it is listed under "Existing tests whose pinned values change", with the spec item that changes it.
- Each task ends green on the repo's own checks. PortfolioSight: `ruff check . && ruff format --check . && pyright .` and the touched test files. QSE: `ruff check .`, `mypy`, and the touched test files (`QSE:AGENTS.md`, manual additions); `make ci-local` once before the PR is called ready (`QSE:Makefile:156`).
- Branches and PRs: remote `github`, feature branch per PR, commit message lists files with line numbers.

Every task runs the same steps: write the test and see it fail, make the change, see the test pass, run the repo checks, commit. The task text gives the test, the change and the acceptance check.

## Decisions for the owner

Three decisions. The first two are the spec's open questions (spec 10) with the spec's recommended defaults. The third was found while writing this plan. The code for each recommended option is in this plan; the alternative is not built.

**D1. If the Schwab measurement finds that Schwab's history for a fund starts later than the record the site serves today (VGSTX starts 1985 today), what should that fund's history be?** Only matters if the measurement (owner step O1) finds this.
- a (recommended): Schwab's history only. One price source per fund. Cost: the fund's history gets shorter and long views set it aside; the older record stays in the archive, not served. Built in Q2 task 4.
- b: fill the earlier years from yfinance prices, labelled. Cost: two price sources inside one fund's history, and yfinance's older dividend record is known to differ in one case (spec 2.2). Not built.

**D2. When Schwab is down for a day or more, should the job fill those days from yfinance?**
- a (recommended): no. The alert fires, late funds stay served for 10 trading days with their date, and Schwab's 30-day request fills the gap when it returns. yfinance prices are used only for a fund Schwab cannot supply at all, named by the owner and labelled. Built in Q2 task 5.
- b: yes, automatically after a set number of failed runs. Cost: more code, and days whose source changes afterwards. Not built.

**D3. May the frozen checks that pin the old rules be changed to the new rules?** The frozen checks under `assertions/` were written for the demo spec. Four parts of this spec contradict them:

| Frozen check | What it pins | Spec item that contradicts it | Task it blocks |
|---|---|---|---|
| A-PS-07 (`test_a_ps_07_served_means_current.py:296-335`, `425-438`) | A fund is served only within 3 sessions; a seed record is `pending` | 10 trading days (spec 1 decision 7, spec 7.1); `pending` no longer given (spec 6) | P2 task 9 |
| A-PS-59 (`test_a_ps_59_served_symbols_current.py:217-223`, `318-351`), live | Every symbol on the menu is within 3 trading days | The same | P2 task 9, once live |
| A-PS-30 (`test_a_ps_30_generation_publish_atomic.py:10-16`, `676-702`) | The nightly takes price providers, asks the TSP provider, marks TSP stale on one failed fetch, and publishes from a store with no lake record | The server fetches no prices and publishes only behind the gate (spec 1 decisions 1 and 6, spec 3.1) | P4, all tasks |
| A-PS-02, 03, 04, 06, 10, 14 | The Tiingo adapter, the tail splice, the seed script, the request budget, `api.tiingo.com` in the code | Their removal (spec 9, P5) | P5, all tasks |

- y (recommended): yes. Each named check is changed to the new rule in its own gate-change commit with a one-page note in `docs/reviews/`, in the form of `docs/reviews/2026-10-15_gate-change_parallel-ladder.md`. That work is ordered by the owner and is not a task in this plan. Why: your decisions 1, 6 and 7 of 2026-11-16 cannot be met otherwise.
- n: no. Then P2 task 9, P4 and P5 are not built. Funds stay on the 3-session rule, the server keeps fetching TSP and Tiingo prices, and expectations S3, S4, S8, F1, F10, M2 and M5 are not met. Everything else in this plan is built.

Everything not marked BLOCKED-D3 passes with the frozen checks as they are. Two design choices in this plan exist only to keep it that way: the sync keeps one cron line for both windows (frozen A-PS-58 allows at most one lake-sync line), and the PortfolioSight Pushover address comes from the environment (frozen A-PS-10 allows no new host in the code).

## Review Focus

Conditions the spec implies but does not test, most likely first. Each has a test in the task that owns the code.

1. The Tiingo walk on KS-001 writes a fund's record while the laptop sync is moving that fund. Expected: the bytes that get replaced are exactly the bytes that were archived, or the fund is not moved this poll. Test in P2 task 3.
2. A move fails halfway and is retried after the old record changed, so the archive key already holds other bytes. Expected: the archive key is never overwritten; the newer bytes get their own key. Test in P2 task 3.
3. The laptop was off at the run time, so there is no verdict for today when the retry fire comes. Expected: the retry fire runs the price step (a run that never started did not finish). Test in Q3 task 6.
4. A requested ticker that is already a preset stock (WMT) or already on QSE's core list (FCX, TSM). Expected: it is listed once, keeps its lower tier, and is never added to QSE's second list. Tests in P1 tasks 2 and 3.
5. The lake's state file cannot be read during a sync. Expected: nothing is uploaded, because a fund priced from yfinance could otherwise be served without its label. Test in P2 task 5.

## Merge order and files

| Order | PR | Repo | Needs | Agent |
|---|---|---|---|---|
| 1 | G0 Schwab measurement script | QSE | nothing | sonnet, xhigh |
| 2 | P1 fund metadata, requested list, export | PortfolioSight | nothing | sonnet, xhigh |
| 3 | Q1 fetch list and universe guard | QSE | P1's export | sonnet, xhigh |
| 4 | Q2 start or rebuild a symbol from the lake's files | QSE | Q1; owner step O1 before it is used | opus, high |
| 5 | Q3 evening run, retries, verdict, alerts | QSE | nothing (independent of Q1, Q2) | opus, high |
| 6 | P1b refresh the copy of QSE's list, order test | PortfolioSight | Q1 merged, owner step O4 done | sonnet, xhigh |
| 7 | P2 sync rules, labels, archive, second window, TSP | PortfolioSight | P1b, owner step O4 | opus, high |
| 8 | P3 the page shows the as-of date | PortfolioSight | with or after P2 | sonnet, xhigh |
| 9 | P4 daily build with no price fetch, behind the gate | PortfolioSight | P2 live with TSP on the laptop; D3 | opus, high |
| 10 | P5 remove the retired code, amend the demo spec | PortfolioSight | P4 live; D3; the owner's go | sonnet, xhigh |

New files and what each is for:

- `QSE:scripts/probe_schwab_funds.py`: asks Schwab about the sample funds and writes what it answered. Reads no lake file.
- `QSE:qse/data/lake_start.py`: load a new symbol; build or rebuild a starting point. Kept out of `total_return_lake.py` (2,225 lines) so the new logic is read on its own.
- `QSE:scripts/lake_start.py`: the owner-run command around it.
- `QSE:qse/data/price_run.py`: the verdict of one price run, a pure function.
- `data/universes/funds.json`, `data/universes/requested.txt`: names and kinds; the requested tickers.
- `scripts/export_qse_fetch_list.py`: writes QSE's second list from what PortfolioSight wants.
- `portfoliosight/data/migration.py`: comparing an old record with the lake's, and the archive copy.
- `portfoliosight/data/tsp_sync.py`: the TSP fetch on the laptop.
- `portfoliosight/data/alerts.py`: one sender, two channels.
- `portfoliosight/jobs/publish_gate.py`: may this generation be published.

---

## PR G0. Schwab measurement script

Repo: QSE. Branch `feat/schwab-funds-probe`. Agent: sonnet, xhigh. The owner runs it (owner step O1). It measures; it does not gate whether Schwab has mutual funds (spec 2.1).

### Task G0.1: the probe and its summary

**Files:** Create `QSE:scripts/probe_schwab_funds.py`, `QSE:tests/scripts/test_probe_schwab_funds.py`. The owner's run adds the saved answers next to `QSE:tests/data/schwab_quotes_fundamental_2026-10-14.json` and a report in `QSE:docs/reviews/`.

**Interfaces (produces):**
- `PROBE_SYMBOLS = ("VTSAX", "VBIAX", "VGSTX", "FXAIX", "SWPPX", "DODGX", "PTTRX", "VTV", "SCHO", "NSRGY", "LVMUY", "SIEGY", "ASML")` (spec 9, G0).
- `HISTORY_REQUESTS`: the price history requests tried per symbol, in order: `periodType=year, period=20, frequencyType=daily, frequency=1` (the longest period QSE's notes list, `QSE:docs/data-sources/schwab_contract.md:31-38`), and the same with `startDate` set to 1970-01-01 in epoch milliseconds.
- `probe(client, symbols, label) -> dict`: the raw answers (per symbol and request: status, number of candles, first and last candle; the quote body).
- `summarize(answers: dict) -> dict`: per symbol `returned_prices`, `first_date`, `deepest_request` (index into `HISTORY_REQUESTS`), `has_dividend_block`, `div_ex_date`, `div_pay_amount`, `last_bar_date`, `last_bar_close`. Pure.
- `compare_timing(snapshots: list[dict]) -> dict`: per symbol, the first label whose last bar is the trading day, and whether its close changed in a later snapshot. Pure.
- Command: `--out-dir` (required), `--label` (one snapshot), `--tokens`, and `--report PATH --fixture PATH` (writes the report and one fixture file from all snapshots in `--out-dir`).

- [ ] **Test first** (`uv run --extra dev python -m pytest tests/scripts/test_probe_schwab_funds.py -q`, expected to fail: module missing). Made-up answers only.
  - `test_summary_gives_first_date_deepest_request_and_dividend_fields`: VBIAX answers whose first request starts 2006-11-17 and second starts 2000-11-13, quote `{"fundamental": {"divExDate": "2025-12-23T00:00:00Z", "divPayAmount": 1.628}}`. Assert `first_date == date(2000, 11, 13)`, `deepest_request == 1`, `has_dividend_block is True`, `div_pay_amount == 1.628`. A symbol with no `fundamental` block: `has_dividend_block is False`. A symbol whose requests all return no candles: `returned_prices is False` and `first_date is None`.
  - `test_timing_names_the_first_snapshot_with_the_days_bar_and_a_later_change`: four snapshots labelled `1400`, `1600`, `1800`, `2000` for trading day 2026-11-18; VTSAX's last bar is 2026-11-17, 2026-11-17, 2026-11-18 at 150.00, 2026-11-18 at 150.10. Assert `first_present == "1800"` and `changed_after is True`.
  - `test_the_probe_writes_only_under_out_dir`: run the command with a fake client and a temporary `--out-dir`; the only files created are under it.
- [ ] **Change:** write the script. It creates the Schwab client the way the repair does (`QSE:scripts/repair_lake_total_return.py:82-140`). It takes no lake path and writes none.
- [ ] **Acceptance:** the three tests pass; `ruff check .` and `mypy` are clean for the new files.
- [ ] **Commit.**

---

## PR P1. Fund metadata, the requested list and the fetch-list export

Repo: PortfolioSight. Branch `feat/fund-metadata-requested-export`. Agent: sonnet, xhigh.

### Task P1.1: `funds.json` and its loader

**Files:** Create `data/universes/funds.json`. Modify `portfoliosight/data/universe.py` (next to `TIERS_FILE`, `universe.py:16`). Test `tests/data/test_universe.py`.

**Interfaces (produces):** `FUNDS_FILE`; `FundMeta(name: str, kind: str)` (frozen dataclass); `load_funds(path: Path = FUNDS_FILE) -> dict[str, FundMeta]`. It raises `ValueError` for a kind outside `etf`, `mutual_fund`, `stock`, and for a name that is empty or equal to its ticker (`manifest.unnamed`, `portfoliosight/data/manifest.py:55-57`).

- [ ] **Test first** (`.venv/bin/python -m pytest tests/data/test_universe.py -q -k funds`):
  - `test_every_wanted_fund_has_a_real_name_and_a_kind`: with `tiers = load_tiers()` and `funds = load_funds()`, every tier 1 and tier 2 symbol that is not TSP, and every requested ticker, is a key; no name equals its ticker. `len(funds) == 353` (325 tier 1 and 2 symbols that are not TSP, FIENX among them, plus 29 requested, WMT counted once). Kinds by count: `{"etf": 192, "mutual_fund": 125, "stock": 36}`. For tier 2 symbols, the kind is `mutual_fund` exactly when the ticker has five letters ending in X (spec Appendix A).
  - `test_funds_file_refuses_a_bad_kind_and_a_missing_name` (temporary file): kind `"fund"` raises; name `"VTI"` for `VTI` raises.
- [ ] **Change:** write the loader. Fill `funds.json` once: names from the catalog as served today (a one-off read of `meta/manifest.json`, not committed), so no displayed name changes; kinds of tier 2 funds from the section headings of `data/universes/portfoliosight.txt` (lines 4, 61, 85, 119, 187 are ETF headings; 206, 259, 298, 308 are mutual fund headings); the eight tier 1 stocks outside tier 2 (AIG, C, GE, INTC, MSFT, PFE, WMT, XOM) and the requested tickers are `stock`. A symbol whose catalog name is missing or is its ticker gets the issuer's full name by hand; list those in the PR body for the owner to check.
- [ ] **Acceptance:** both tests pass.
- [ ] **Commit.**

### Task P1.2: `requested.txt` as a third tier 3 file

**Files:** Create `data/universes/requested.txt`. Modify `data/universes/tiers.json:15-20`, `portfoliosight/data/universe.py:52-89` and `150-183`. Test `tests/data/test_universe.py`.

**Interfaces (produces):** `tiers.json` tier 3 gets a third entry in `files` and a key `"requested": "data/universes/requested.txt"` naming which of them is the request list. `Tiers.requested: tuple[str, ...]` (file order). `SymbolInfo.requested: bool` is true for a symbol of `Tiers.requested` whose lowest tier is 3.

- [ ] **Test first** (`-k requested`):
  - `test_a_requested_ticker_is_a_tier_3_stock`: `info["NSRGY"].tier == 3`, `info["NSRGY"].kind == "stock"`, `info["NSRGY"].requested is True`.
  - `test_a_requested_ticker_already_listed_keeps_its_place`: `info["WMT"].tier == 1` and `info["WMT"].requested is False`; `list(tiers.tier3).count("FCX") == 1`; `len(tiers.requested) == 29`; `len(tiers.tier3) == 1038 + 356 + 26`.
- [ ] **Change:** the file holds the 29 tickers of spec Appendix A, one per line, under the comment `# 2026-11-11, site request log (one CSV upload), read 2026-11-16`. `load_tiers` records the requested file's symbols.
- [ ] **Acceptance:** both tests pass. Pinned values in `test_tier3_is_the_qse_core_list_then_the_qse_portfoliosight_list` (`tests/data/test_universe.py:70-80`) change; see the list at the end.
- [ ] **Commit.**

### Task P1.3: the export

**Files:** Create `scripts/export_qse_fetch_list.py`, `tests/data/test_export_qse_fetch_list.py`.

**Interfaces (produces):**
- `wanted_symbols(tiers: Tiers) -> set[str]`: tier 1, tier 2 and requested symbols that are not TSP and have no note in `tiers.json`.
- `fetch_list(current: Iterable[str], tiers: Tiers, core: Iterable[str]) -> list[str]`: `sorted(set(current) | (wanted_symbols(tiers) - set(core)))`.
- Command: `--qse-file PATH` (QSE's current second list; default `data/universes/qse_portfoliosight.txt`), `--core-file PATH` (default `data/universes/qse_core.txt`), `--out PATH` (default: print), `--new-only` (only the symbols not in `--qse-file`). The module docstring, shown by `--help`, states the four steps of spec 4 for adding a ticker later.

- [ ] **Test first:**
  - `test_export_on_the_committed_lists`: `out = fetch_list(current, load_tiers(), core)` with the committed files. `len(out) == 629`, `out == sorted(set(out))`, `set(current) <= set(out)`, no symbol starts with `TSP-`, `"FIENX" not in out`, `not set(out) & set(core)`, `{"VTSAX", "VTV", "NSRGY"} <= set(out)`, and `"WMT"`, `"FCX"`, `"TSM"` are absent (they are on the core list).
  - `test_export_on_a_small_universe` (made-up `Tiers` and lists): current `["ADC", "ZTS"]`, core `["AAPL", "FCX"]`, tier 2 `("VTI", "AAPL", "TSP-G", "GONE")` with a note on `GONE`, requested `("FCX", "NEWT")`. Assert the result is `["ADC", "NEWT", "VTI", "ZTS"]` and `--new-only` gives `["NEWT", "VTI"]`.
  - `test_adding_a_line_to_requested_txt_reaches_the_export` (temporary copy of the universe files): append `ZZNEW` to the requested file; it is in the export, with no code change.
- [ ] **Change:** write the script.
- [ ] **Acceptance:** `python scripts/export_qse_fetch_list.py | wc -l` prints 629; `--new-only` prints 273 lines.
- [ ] **Commit.**

### Task P1.4: the provider walk never starts a requested ticker

Not in spec 9. It is needed for spec 4.1 ("a ticker Schwab does not know stays off the menu"): on the Power plan the nightly walk fetches every tier 3 symbol that has no record from Tiingo (`portfoliosight/data/download.py:361-372`, `portfoliosight/data/limits.py:66-69`), so a new requested ticker would be served from Tiingo. Which plan production records is in R2 and was not checked.

**Files:** Modify `portfoliosight/data/download.py:361-372`. Test `tests/data/test_download.py`.

- [ ] **Test first:** `test_the_walk_never_fetches_a_requested_ticker_that_has_no_record`: a universe whose tier 3 holds requested ticker `ZZZQ` with no catalog entry, set up as the default walk is in `tests/data/test_lake.py:410`. After `download.run("refresh", ...)` over tier 3, the provider recorded no call for `ZZZQ` and the manifest has no `ZZZQ` entry. A requested ticker that already has a record is refreshed as before.
- [ ] **Change:** in `_visit`, a symbol with no record whose `SymbolInfo.requested` is true is left alone.
- [ ] **Acceptance:** the test passes; `tests/data/test_download.py`, `tests/data/test_lake.py` and `tests/jobs/test_nightly.py` pass unchanged.
- [ ] **Commit.**

---

## PR Q1. Fetch list and universe guard

Repo: QSE. Branch `feat/portfoliosight-fetch-list-guard`. Agent: sonnet, xhigh.

### Task Q1.1: a missing core list stops the run

**Files:** Modify `QSE:scripts/daily_pipeline.py:699-715` (the rebuild of the list inside `refresh_eodhd`) and `864-867` (the listing fallback inside `refresh_schwab_eod`). Test `QSE:tests/scripts/test_daily_pipeline.py`.

**Interfaces (produces):** `class CoreUniverseMissing(RuntimeError)`; `_core_universe() -> list[str]` returns `_read_symbols(UNIVERSE_FILE)` and raises `CoreUniverseMissing` when the file does not exist. Both steps call it. Neither writes the file.

- [ ] **Test first** (`uv run --extra dev python -m pytest tests/scripts/test_daily_pipeline.py -q -k core_list`):
  - `test_a_missing_core_list_stops_the_price_step_and_writes_no_list`: temporary lake with `eod_history/AAPL.parquet` and `ADC.parquet`, no core file, second list `ADC`. `refresh_schwab_eod()` raises `CoreUniverseMissing`; the core file still does not exist; the fake client recorded no price request (fake client as in `QSE:tests/scripts/test_daily_pipeline.py:528-573`).
  - `test_a_missing_core_list_stops_the_eodhd_step_and_writes_no_list`: the same for `refresh_eodhd()`, with `subprocess.run` replaced by a recorder that must stay empty.
  - `test_the_price_step_gets_n_plus_m_and_the_dataset_names_the_core_file_only`: core `MSFT`, `AAPL` (N = 2), second list `ZTS`, `AAPL`, `ADC` (M = 2 others). Priced symbols are `["MSFT", "AAPL", "ZTS", "ADC"]`; the dataset command's `--symbols-file` is the core file and the second file is not in the command.
- [ ] **Change:** replace both fallbacks with `_core_universe()`.
- [ ] **Acceptance:** the three tests pass. `test_refresh_eodhd_raises_when_eod_history_missing` and `test_refresh_eodhd_raises_when_eod_history_empty` (`:345`, `:364`) test the rebuild that is removed; they are replaced by the second test above, and the PR body says so.
- [ ] **Commit.**

### Task Q1.2: the new second list

**Files:** Modify `QSE:qse/config/universes/datalake_portfoliosight.txt`, `QSE:tests/scripts/test_daily_pipeline.py:666-677`.

- [ ] **Test first:** `test_portfoliosight_universe_file_is_tracked_and_disjoint_from_the_dead_symbols` with the count pin moved from 356 to 629, plus: no symbol starts with `TSP-`, `"FIENX"` is absent, `{"VTSAX", "VTV", "NSRGY", "ASML"}` are present. The existing checks (sorted, unique, dead symbols and KRG, RBA absent) stay.
- [ ] **Change:** the file is the output of `scripts/export_qse_fetch_list.py --qse-file <this file> --out <this file>`, run from the PortfolioSight P1 branch.
- [ ] **Acceptance:** the test passes. On the laptop (owner step O3): the next run logs 629 PortfolioSight-only symbols (`QSE:scripts/daily_pipeline.py:822-827`) and the dataset has the same tickers as the day before.
- [ ] **Commit.**

---

## PR Q2. Start or rebuild a symbol from the lake's own files

Repo: QSE. Branch `feat/lake-start-from-own-files`. Agent: opus, high (data integrity).

Rules for the whole PR: no function here takes an EODHD input; `build_start` takes no network source at all; `QSE:tests/unit/data/test_total_return_lake.py` and `QSE:tests/scripts/test_repair_lake_total_return.py` pass with no change to either file.

Shared test lake for tasks 1 to 4, symbol `NEWF`, six sessions 2026-01-05, 06, 07, 08, 09, 12: raw closes `[100, 100, 50, 50, 50, 50]`; a 2 for 1 split with ex-date 2026-01-07; dividends of 1.00 (ex 2026-01-06) and 0.50 (ex 2026-01-09), source `yfinance`. Helpers as in `QSE:tests/unit/data/test_total_return_lake.py:38-83`.

### Task Q2.1: build a starting point

**Files:** Create `QSE:qse/data/lake_start.py`, `QSE:tests/unit/data/test_lake_start.py`.

**Interfaces (produces):**
- `StartReport(symbol: str, action: str, reasons: list[str], details: list[str], first_date: date | None, last_date: date | None, adjusted_through: date | None, kept_file: str | None)`; `action` is one of `built`, `kept`, `rebuilt`, `loaded`, `refused`.
- `build_start(store: LakeStore, symbol: str, run_date: date, book: AdjustedThroughBook, *, rebuild: bool = False) -> StartReport`.
- The starting point covers the symbol's rows dated before `run_date` (a row dated the run day is never part of it). Anchor: the last of those dates. Evidence text: `lake_files:{run_date.isoformat()}` (the existing evidence field, `QSE:qse/data/total_return_lake.py:137`, `458-464`).

- [ ] **Test first** (`uv run --extra dev python -m pytest tests/unit/data/test_lake_start.py -q`):

```python
def test_build_gives_hand_computed_adjusted_closes_a_starting_point_and_a_vouched_date(tmp_path):
    store, book = _newf_lake(tmp_path)                      # no adj_base, not vouched
    report = build_start(store, "NEWF", date(2026, 1, 13), book)
    want = [49.005, 49.5, 49.5, 49.5, 50.0, 50.0]
    base = store.read_adj_base("NEWF")
    assert report.action == "built" and report.reasons == []
    assert base.eodhd_adj_close.tolist() == pytest.approx(want, abs=1e-9)
    assert base.anchor == pd.Timestamp("2026-01-12")
    assert store.read_eod("NEWF")["adj_close"].tolist() == pytest.approx(want, abs=1e-9)
    assert book.through["NEWF"] == date(2026, 1, 12)
    assert store.adj_base_evidence("NEWF") == "lake_files:2026-01-13"
```

  The values are close times the factor of every later action: 0.99 (1.00 on a close of 100), 0.5 (the split), 0.99 (0.50 on a close of 50).
- [ ] **Change:** adjusted closes come from `compute_adj_close(eod, dividends, splits, None)` (`QSE:qse/data/corporate_actions.py:463-512`); the file is written with `LakeStore.write_adj_base` (`total_return_lake.py:466-482`); the symbol is vouched with `book.vouch(symbol, anchor_date, run_date)` (`:224-251`). A symbol with dividend conflicts on file (`dividend_conflicts`, `corporate_actions.py:329`) is refused with reason `action_conflict` and nothing is written.
- [ ] **Acceptance:** the test passes.
- [ ] **Commit.**

### Task Q2.2: after the build, the daily job treats the symbol like any other

**Files:** Test only, `QSE:tests/unit/data/test_lake_start.py`. If it fails, the fix belongs in `lake_start.py`, not in the daily job.

- [ ] **Test first:** `test_a_dividend_listed_a_day_late_lowers_every_earlier_adjusted_close_and_the_date_advances`. Build as in Q2.1. Then run `run_daily_stitch` for run date 2026-01-14 with bars for 2026-01-13 (close 49.5) and 2026-01-14 (close 49.6), a Schwab quote whose latest dividend is 0.25 with ex-date 2026-01-13, and a yfinance history that lists the same payout (set up as `test_daily_stitch_records_schwab_dividend_recomputes_and_advances`, `QSE:tests/unit/data/test_total_return_lake.py:294`). Assert the adjusted closes are `[48.759975, 49.2525, 49.2525, 49.2525, 49.75, 49.75, 49.5, 49.6]` (abs 1e-9) and `book.through["NEWF"] == date(2026, 1, 14)`. The payout is 0.25, not 0.50: two equal payouts two sessions apart are read as one (`collapse_near_duplicates`, `corporate_actions.py:306`).
- [ ] **Acceptance:** the test passes with no change to `total_return_lake.py`.
- [ ] **Commit.**

### Task Q2.3: existing starting points stay; `--rebuild` replaces only on agreement

**Files:** Modify `QSE:qse/data/lake_start.py`, `QSE:qse/data/total_return_lake.py:466-482` (one new method next to `write_adj_base`). Test `QSE:tests/unit/data/test_lake_start.py`.

**Interfaces (produces):** `LakeStore.replace_adj_base(symbol: str, base: AdjBase, evidence: str, stamp: datetime) -> Path`: moves the old file to `adj_base_replaced/{SYMBOL}.{stamp:%Y%m%dT%H%M%SZ}.parquet` (a sibling folder, so nothing that lists `adj_base/` sees it), then writes the new one; returns the kept path. `write_adj_base` is unchanged.

Agreement rule for `rebuild=True`: for every date the old starting point holds, the adjusted close the lake computes today from the old file and the one computed from the symbol's own files differ by at most `FACTOR_TOLERANCE` in ratio (`total_return_lake.py:129`).

- [ ] **Test first:**
  - `test_a_symbol_with_a_starting_point_is_left_byte_for_byte`: on the repaired lake of `_repaired_lake` (`test_total_return_lake.py:285`), record the sha256 of every file under the lake root; `build_start(store, "VTI", run_date, book)` returns `action == "kept"` and every hash is unchanged.
  - `test_rebuild_with_agreeing_values_replaces_and_keeps_the_old_file`: `rebuild=True` on `NEWF` after Q2.1. `action == "rebuilt"`; exactly one file exists under `adj_base_replaced/` and its bytes equal the old file's; the adjusted closes are unchanged (abs 1e-9).
  - `test_rebuild_with_disagreeing_values_writes_nothing`: change the 1.00 dividend on file to 2.00 first. `action == "refused"`, `reasons == ["rebuild_disagrees"]`, `details` names 2026-01-05 and both values, and every file hash is unchanged.
  - `test_a_symbol_blocked_by_adj_base_gap_is_vouched_after_rebuild`: produce the block as `test_adj_base_gap_is_a_loud_per_symbol_block` does (`test_total_return_lake.py:552`); after `rebuild=True`, `book.get(sym).blocked is None` and the symbol is in `book.through`.
- [ ] **Change:** `build_start` returns `kept` for a symbol that has a starting point unless `rebuild` is true.
- [ ] **Acceptance:** the four tests pass.
- [ ] **Commit.**

### Task Q2.4: load a new symbol, all checks or nothing

**Files:** Modify `QSE:qse/data/lake_start.py`, `QSE:qse/data/corporate_actions.py:886-959` (one new method on `YFinanceActionSource`). Test `QSE:tests/unit/data/test_lake_start.py`.

**Interfaces (produces):**
- `class PriceCheckSource(Protocol)`: `fetch_prices(symbol: str, start: date) -> pd.DataFrame | None` with columns `date`, `close` (not dividend-adjusted), `adj_close` (yfinance's own); `None` means no answer. `YFinanceActionSource.fetch_prices` implements it from the same request as `fetch`.
- `load_symbol(store, symbol, *, fetch_history: Callable[[str], pd.DataFrame | None], source: ActionSource, prices: PriceCheckSource, run_date: date, price_tolerance: float, book: AdjustedThroughBook, yfinance_prices: bool = False) -> StartReport`.
- `price_tolerance` has no default: it is the largest allowed relative difference between Schwab's close and yfinance's close on a shared date, set from the Schwab measurement (owner step O1).
- Reasons, exact text: `schwab_no_data`, `schwab_bad_close`, `yfinance_no_answer`, `price_mismatch`, `existing_rows_disagree`, `adjusted_mismatch`.

Order inside `load_symbol`: fetch; the three checks of spec 5 step A; write raw closes (splits undone with `_to_raw`, `total_return_lake.py:1756-1761`) and the action records with source `yfinance`; compute the adjusted series from those files and compare it with yfinance's `adj_close` on shared dates within `FACTOR_TOLERANCE`; only then `build_start`. On `adjusted_mismatch` no starting point is written, so the daily job never vouches the symbol (spec 2.4 fact 1).

- [ ] **Test first** (Schwab bars are split-adjusted: closes `[50, 50, 50, 50, 50, 50]`; yfinance lists the 2 for 1 split on 2026-01-07 and one dividend, 0.50 on today's basis, ex 2026-01-06; tolerance 0.001 passed in):
  - `test_load_writes_raw_closes_and_action_records_and_vouches`: stored closes `[100, 100, 50, 50, 50, 50]`; the dividend file has one row, 2026-01-06, unadjusted value 1.00, source `yfinance`; the split file has one row, 2026-01-07, source `yfinance`; adjusted closes `[49.5, 50, 50, 50, 50, 50]`; `book.through["NEWF"] == date(2026, 1, 12)`; `action == "loaded"`.
  - `test_load_refuses_and_writes_nothing` (four cases): Schwab returns no rows gives `schwab_no_data`; one Schwab close of 0 gives `schwab_bad_close`; the action request returns `None` gives `yfinance_no_answer`; a yfinance close of 51.0 on one date gives `price_mismatch`. In each case no file for the symbol exists under the lake root and it is not in `book.through`.
  - `test_load_keeps_the_rows_the_daily_job_wrote_earlier`: a short unvouched file with 2026-01-09 and 2026-01-12 at 50 exists first. After the load the file has all six dates and those two rows are unchanged. With an earlier row at 55 instead: `existing_rows_disagree` and the file's bytes are unchanged.
  - `test_history_starts_where_schwabs_starts`: yfinance prices start 2025-12-29, Schwab's 2026-01-05; the stored first date is 2026-01-05 (decision D1, option a).
  - `test_a_new_symbol_whose_adjusted_series_disagrees_is_not_vouched`: yfinance's own `adj_close` is 49.0 on 2026-01-05 (a payout the action list lacks). `reasons == ["adjusted_mismatch"]`, no file under `adj_base/`, not in `book.through`.
  - `test_a_second_run_changes_nothing`: run the load twice; every file hash is equal after the second run and its report says `kept`.
- [ ] **Change:** as ordered above.
- [ ] **Acceptance:** all tests pass.
- [ ] **Commit.**

### Task Q2.5: yfinance prices only for a symbol Schwab cannot supply, named by the owner

Spec 5 and spec 6 require this path (decision D2, option a); spec 9 lists no test for it.

**Files:** Modify `QSE:qse/data/total_return_lake.py:181-213`, `485-555` (one state field and its round trip), `QSE:qse/data/lake_start.py`, `QSE:qse/data/corporate_actions.py` (one method), `QSE:scripts/daily_pipeline.py:896-909`. Tests `QSE:tests/unit/data/test_lake_start.py`, `QSE:tests/scripts/test_daily_pipeline.py`.

**Interfaces (produces):** `SymbolState.price_source: str | None = None` (`"yfinance"`, or `None` for Schwab), saved in `_corporate_actions_state.json` as `price_source`. PortfolioSight reads this field in P2 task 5. `YFinanceActionSource.fetch_bars(symbol: str, start: date) -> pd.DataFrame | None` with the columns of `candles_to_bars` (`total_return_lake.py:570-584`). New reason: `schwab_has_prices`.

- [ ] **Test first:**
  - `test_yfinance_prices_are_refused_for_a_symbol_schwab_supplies`: `load_symbol(..., yfinance_prices=True)` when Schwab returns rows gives `reasons == ["schwab_has_prices"]` and writes nothing.
  - `test_an_owner_named_symbol_is_loaded_from_yfinance_and_marked`: Schwab returns nothing; after the load and a `save_book` and `load_book` round trip, `book.get(sym).price_source == "yfinance"`.
  - `test_a_schwab_failure_never_brings_a_yfinance_price` (pipeline test): Schwab answers 503 for a Schwab-priced symbol on every try; no yfinance bar request is recorded for it and its file's bytes are unchanged.
  - `test_a_yfinance_priced_symbol_gets_its_daily_bars_from_yfinance`: for a symbol whose state says `yfinance`, the Schwab client recorded no price request and the new row comes from the fake yfinance bars.
- [ ] **Change:** the price step reads the state book once and routes only marked symbols to `fetch_bars`.
- [ ] **Acceptance:** the four tests pass; a lake state file without the field loads as before.
- [ ] **Commit.**

### Task Q2.6: the command

**Files:** Create `QSE:scripts/lake_start.py`, `QSE:tests/scripts/test_lake_start.py`.

**Interfaces (produces):** `main(argv) -> int` with: `--lake-dir` (default: the environment name `QSE_LAKE_DIR`, else today's path, `QSE:scripts/daily_pipeline.py:137`); `--symbols` or `--symbols-file`; `--load-only`, `--build-only` (default: load new symbols, then build); `--rebuild SYM[,SYM]`; `--yfinance-prices SYM[,SYM]`; `--price-tolerance FLOAT` (required whenever a load runs); `--run-date`; `--schwab-tokens`; `--throttle-seconds`; `--report-json PATH`. It holds the pipeline lock named by `QSE_PIPELINE_LOCK` for the whole run, reusing `pipeline_lock` and the Schwab helpers of `QSE:scripts/repair_lake_total_return.py:63-140`. The Schwab history request is the one the measurement names as reaching furthest back; until then, the first entry of `HISTORY_REQUESTS` (G0.1). The report: `{"run_date", "counts": {action: n}, "symbols": {SYM: {"action", "reasons", "details", "first_date", "last_date", "adjusted_through"}}}`.

- [ ] **Test first** (fake Schwab client and fake sources passed through the same seams the repair script's tests use):
  - `test_the_command_runs_against_a_lake_in_a_temporary_folder`: every path passed in; exit code 0; the report lists `NEWF` as `loaded` and an unknown symbol as `refused` with `schwab_no_data`; nothing is written outside the temporary folder.
  - `test_the_command_refuses_while_the_pipeline_lock_is_held`.
  - `test_rebuild_needs_named_symbols_that_exist` and `test_a_load_needs_a_price_tolerance`: each exits with an error before any file is read.
  - `test_load_skips_a_symbol_the_lake_already_vouches`: its files' hashes are unchanged and the report says `kept`.
  - `test_build_only_makes_no_network_call`: the Schwab client factory and the yfinance source are replaced by ones that raise when used; `--build-only` on `NEWF` succeeds.
- [ ] **Change:** write the command.
- [ ] **Acceptance:** the tests pass. On the laptop (owner step O4): a report for the 273 new symbols with the number vouched and each failure's reason, and the held-out check.
- [ ] **Commit.**

### Task Q2.7: the dividend policy for mutual funds. Built only if the measurement calls for it

Build this task only if the report of owner step O1 says that a sampled mutual fund's Schwab quote has no dividend block, or that VBIAX's amount for 2025-12-23 is not 1.628 (spec 5, last part). Otherwise skip it and say so in the PR.

**Files:** Modify `QSE:qse/data/total_return_lake.py:181-213`, `485-555`, `1357-1535`. Test `QSE:tests/unit/data/test_total_return_lake.py` (new tests only).

**Interfaces (produces):** `SymbolState.action_policy: str | None = None` (`"yfinance"`; `None` is today's behavior). `load_symbol` sets it for a symbol named in the measurement's list of affected kinds.

- [ ] **Test first:**
  - `test_a_yfinance_policy_fund_with_no_schwab_dividend_block_advances_on_five_runs_in_a_row`: five run dates (2026-01-13, 14, 15, 16 and 20; the 19th is a market holiday), one new bar each; after each run `book.through[sym]` is that run's bar date.
  - `test_a_failed_yfinance_request_leaves_the_date_where_it_was`.
  - `test_a_schwab_amount_that_differs_raises_no_conflict_for_a_yfinance_policy_fund`: Schwab says 0.30, yfinance 0.50 on the same ex-date; `book.get(sym).conflict is None` and the fund is vouched.
  - `test_a_fund_without_the_policy_behaves_as_before`: the same inputs without the policy give the conflict the code gives today.
- [ ] **Acceptance:** the tests pass and every existing test in the file passes unchanged.
- [ ] **Commit.**

---

## PR Q3. The evening run, retries, the verdict and the alerts

Repo: QSE. Branch `feat/evening-price-run-alerts`. Agent: opus, high (a second daily run under the shared lock, and a retry driven by saved state). Independent of Q1 and Q2.

### Task Q3.1: the lake folder and the state folder are settings

**Files:** Modify `QSE:scripts/daily_pipeline.py:136-137`. Test `QSE:tests/scripts/test_daily_pipeline.py`.

**Interfaces (produces):** `_lake_dir(env: Mapping[str, str]) -> Path` (`QSE_LAKE_DIR`, default today's path) and `_state_dir(env) -> Path` (`QSE_PIPELINE_STATE_DIR`, default `PROJECT_ROOT / "runs/live"`); `RAW_DIR = _lake_dir(os.environ)`; `STATE_DIR = _state_dir(os.environ)`.

- [ ] **Test first:** `test_the_lake_and_state_folders_come_from_settings`: `_lake_dir({"QSE_LAKE_DIR": "/x/lake"}) == Path("/x/lake")`; `_lake_dir({}) == PROJECT_ROOT / "data/tft/raw/eodhd/datalake_us_core"`; the same pair for `_state_dir`.
- [ ] **Acceptance:** the test passes; existing tests that replace `RAW_DIR` still pass.
- [ ] **Commit.**

### Task Q3.2: retries on daily bars

**Files:** Modify `QSE:scripts/daily_pipeline.py:896-909`. Test `QSE:tests/scripts/test_daily_pipeline.py`.

**Interfaces (produces):** `fetch_schwab_bars(client, symbol: str, cutoff: pd.Timestamp, *, sleep: Callable[[float], None] = time.sleep) -> pd.DataFrame`; `class SchwabRetryable(RuntimeError)`. Three tries, waits doubling from 2 s to at most 20 s (tenacity, as `QSE:qse/data/total_return_lake.py:593`), on network errors, HTTP 429 and HTTP 500 to 599. Any other status raises at once.

- [ ] **Test first** (the `sleep` passed in records its arguments; no real wait):
  - `test_a_price_request_that_fails_twice_then_succeeds_yields_its_bars`: statuses 503, 429, 200. Three calls, the bars are returned, two sleeps, each between 2 and 20.
  - `test_three_failures_are_counted_and_the_run_goes_on`: `AAPL` answers 503 three times, `MSFT` answers 200. `summary.errors == 1`, `MSFT` has its new row, `AAPL` was asked exactly three times.
  - `test_an_unknown_symbol_answer_is_not_retried`: 404 gives one call; 401 gives one call.
- [ ] **Change:** move the body of the inner `fetch_bars` into `fetch_schwab_bars`.
- [ ] **Acceptance:** the tests pass.
- [ ] **Commit.**

### Task Q3.3: the run summary carries what the verdict needs

**Files:** Modify `QSE:qse/data/total_return_lake.py:587-611`, `630-643`, `1357-1535`; `QSE:scripts/daily_pipeline.py:831-960`. Test `QSE:tests/unit/data/test_total_return_lake.py` (new tests only), `QSE:tests/scripts/test_daily_pipeline.py`.

**Interfaces (produces):** `DailySummary.schwab_down: bool = False`, `DailySummary.yfinance_tripped: bool = False`, `DailySummary.quote_batches_failed: list[str]` (`"qse"`, `"portfoliosight"`). `SCHWAB_BREAKER_FAILURES = YFINANCE_BREAKER_FAILURES` (10, `total_return_lake.py:171`). `fetch_schwab_dividend_infos(client, symbols, batch_size=500, failed: list[tuple[int, int]] | None = None)` appends the range of each batch that failed after its retries. `refresh_schwab_eod` returns the `DailySummary` (`None` when it skipped).

Counting rule: only failures that were retried (`SchwabRetryable`) count toward the ten in a row; a success or a refusal that is not retried resets the count. When the count reaches ten, `schwab_down` is set and the rest of the symbols are not requested in this run (they count as errors), as the yfinance breaker does (`total_return_lake.py:709-735`). The spec names the count but not whether to stop; stopping is this plan's choice, so a Schwab outage does not hold the lock through hundreds of retries.

- [ ] **Test first:**
  - `test_ten_retried_failures_in_a_row_mark_schwab_down_and_stop_the_requests`: twelve symbols that all fail; `summary.schwab_down is True` and the fetch function was called for ten symbols only.
  - `test_nine_failures_then_a_success_do_not_mark_schwab_down`.
  - `test_unknown_symbols_never_mark_schwab_down`: twelve 404 answers; `schwab_down is False`.
  - `test_a_failed_portfoliosight_quote_batch_is_reported`: the second quote call raises on every try; `summary.quote_batches_failed == ["portfoliosight"]` and the QSE symbols' captures are kept.
  - `test_a_tripped_yfinance_breaker_is_reported`: `summary.yfinance_tripped is True`.
- [ ] **Acceptance:** the tests pass; no existing test changes.
- [ ] **Commit.**

### Task Q3.4: the verdict

**Files:** Create `QSE:qse/data/price_run.py`, `QSE:tests/unit/data/test_price_run.py`. Modify `QSE:pyproject.toml` (add `exchange_calendars`, the library PortfolioSight uses, `pyproject.toml:20` there).

**Interfaces (produces):**
- `Verdict(status: Literal["ok", "failed"], reasons: list[str], counts: dict[str, int])`.
- `price_step_verdict(summary: DailySummary | None, *, run_kind: Literal["evening", "morning"], run_date: date, latest_vouched: date | None, is_session: Callable[[date], bool]) -> Verdict`. `summary is None` means the step did not finish.
- `xnys_is_session(day: date) -> bool`.
- Reasons, exact text: `price step did not finish`; `Schwab is down: daily bars failed for 10 symbols in a row`; `Schwab quote batch failed for PortfolioSight symbols`; `yfinance is down: its breaker tripped`; `nothing moved: latest vouched date {date}, expected {run_date}`.
- `counts`: `written`, `no_data`, `errors`, `conflicts`, `split_unconfirmed`, `vouched`.

`sessions_between` (`QSE:qse/data/corporate_actions.py:1163-1171`) is not changed: the calendar is used for the verdict only.

- [ ] **Test first** (pure; no files):
  - `test_a_step_that_did_not_finish_is_failed`: `summary=None` gives `status == "failed"` and `reasons == ["price step did not finish"]`.
  - `test_schwab_down_a_failed_portfoliosight_batch_and_a_tripped_breaker_each_fail`: one case each; all three together give three reasons in one verdict.
  - `test_three_failed_symbols_give_ok_with_counts`: `errors=3`, nothing else wrong; `status == "ok"` and `counts["errors"] == 3`.
  - `test_an_evening_run_on_a_trading_day_that_moved_nothing_is_failed`: evening, run date 2026-11-18, latest vouched 2026-11-17, `is_session=xnys_is_session`; reasons are `["nothing moved: latest vouched date 2026-11-17, expected 2026-11-18"]`.
  - `test_an_evening_run_on_an_exchange_holiday_is_ok`: run date 2026-11-26 (Thanksgiving), latest vouched 2026-11-25; `status == "ok"`.
  - `test_a_morning_run_is_not_judged_on_the_date`: morning, latest vouched one session back; `status == "ok"`.
- [ ] **Acceptance:** the tests pass.
- [ ] **Commit.**

### Task Q3.5: one alert helper, two channels

**Files:** Modify `QSE:scripts/daily_pipeline.py:186-233`. Test `QSE:tests/scripts/test_daily_pipeline.py`.

**Interfaces (produces):** `send_alert(check_env: str, ok: bool, title: str, message: str) -> list[str]`. It pings the healthchecks.io address held in the environment name `check_env` (with `/fail` appended when `ok` is false), and, when `ok` is false, also calls the existing Pushover sender. It returns the channels that accepted the message (`"healthchecks"`, `"pushover"`). When `ok` is false and the list is empty it logs `alert not delivered: no channel configured`. It never raises. `_send_pushover_alert` stays and returns whether Pushover accepted. `_report_schwab_token_health` goes through `send_alert("QSE_SCHWAB_HC_URL", ...)`. New name: `QSE_LAKE_HC_URL`.

- [ ] **Test first** (requests captured as `_record_hc` does, `QSE:tests/scripts/test_daily_pipeline.py:1079-1089`):
  - `test_an_alert_makes_one_request_per_channel_that_is_set`: both set, a failure gives exactly one healthchecks request ending in `/fail` and one Pushover request, and returns both names. Pushover names unset: one healthchecks request, returns `["healthchecks"]`. Neither set: no request, returns `[]`, and the log says the alert was not delivered.
  - `test_a_success_ping_goes_to_healthchecks_only`.
  - `test_a_request_that_fails_never_fails_the_run`: both senders raise; `send_alert` returns `[]` and raises nothing.
- [ ] **Acceptance:** the tests pass; the existing token health tests (`:1092-1154`) pass unchanged.
- [ ] **Commit.**

### Task Q3.6: the price-only run, the verdict in both runs, the retry fire

**Files:** Modify `QSE:scripts/daily_pipeline.py:1684-1736`. Test `QSE:tests/scripts/test_daily_pipeline.py`.

**Interfaces (produces):**
- `--price-only`: the login check (`preflight_schwab_refresh_token`, `check_schwab_token`), the price step, the verdict and its alert. Nothing else, and no dataset file is needed.
- `--run-kind evening|morning` (default `morning`).
- `--only-if-failed`: with `--price-only`, run only when the saved verdict for this run kind and today is `failed`, or there is none for today.
- `run_price_step(run_kind: str, run_date: date) -> Verdict`: runs the price step, computes the verdict (a step that raises or skips is "did not finish"), saves it to `STATE_DIR / "price_run_verdict_{run_kind}.json"` as `{"run_kind", "run_date", "status", "reasons", "counts", "finished_at"}`, and sends one alert through `send_alert("QSE_LAKE_HC_URL", ...)`: a success ping whose message carries the counts, or a failure with the reasons. An exception from the price step is raised again after the alert.
- In the full run the verdict and the alert come right after the price step, before the EODHD step, so the alert does not depend on the pipeline's exit code (spec 7.3).

- [ ] **Test first** (each step function replaced by a recorder):
  - `test_price_only_runs_the_login_check_and_the_price_step_and_nothing_else`: the recorded steps are the two login checks and the price step; the EODHD step, the FRED step, the dataset build and the scanner token sync were not called; exit code 0 with no dataset file present.
  - `test_the_alert_is_sent_before_the_eodhd_step`: in a full run whose EODHD step raises, the lake check already received its ping.
  - `test_a_price_step_that_dies_gives_failed_and_one_alert`: the price step raises `SystemExit(1)`; one failure alert naming `price step did not finish`; the exit code is kept.
  - `test_ten_schwab_failures_in_a_row_give_failed_and_one_alert_with_the_reason`.
  - `test_a_day_with_three_failed_symbols_gives_ok_and_a_success_ping_with_counts`: the ping's message contains `errors 3`.
  - `test_the_retry_fire_runs_only_after_a_failed_or_missing_run`: today's verdict `ok` gives no price step; `failed` gives one; a verdict dated yesterday, or no file, gives one.
- [ ] **Acceptance:** the tests pass.
- [ ] **Commit.**

### Task Q3.7: the login alert at two days, on weekends too

**Files:** Modify `QSE:scripts/daily_pipeline.py:164-176`, `236-336`, `1684-1736`. Test `QSE:tests/scripts/test_daily_pipeline.py`.

**Interfaces (produces):** `SCHWAB_REFRESH_TOKEN_WARN_DAYS = 2`. `report_schwab_login() -> bool`: the reporting half of the preflight (reads the tokens file, sends the healthy or failing alert); it never starts the login flow. `--login-check-only` runs it and exits 0.

- [ ] **Test first** (tokens aged with `_token_aged`, `:104-119`):
  - `test_two_and_a_half_days_left_is_healthy_and_one_point_nine_is_an_alert`: age 4.5 days gives a success ping; age 5.1 days gives a failure.
  - `test_the_weekend_check_only_reports`: `--login-check-only` with a token aged 8 days, and the login flow replaced by a function that fails the test if called; one failure alert, exit code 0.
- [ ] **Change:** as above. Pinned values in four existing tests change (owner decision 7); see the list at the end.
- [ ] **Acceptance:** the tests pass.
- [ ] **Commit.**

### Task Q3.8: the cron wrapper's modes

**Files:** Modify `QSE:scripts/daily_pipeline_cron.sh:100-128`. Create `QSE:tests/scripts/test_daily_pipeline_cron_modes.py`.

**Interfaces (produces):** `daily_pipeline_cron.sh [full|price-only|retry-price <evening|morning>|login-check]`; no argument means `full`, which is today's behavior line for line. `price-only` runs `daily_pipeline.py --price-only --run-kind evening` under the same lock and nothing after it (no comparator, no background downloads). `retry-price K` adds `--only-if-failed --run-kind K`. `login-check` runs `--login-check-only` without the lock.

- [ ] **Test first** (the wrapper is run with `subprocess.run` from a temporary copy of `scripts/`, with a stub `python3` first on `PATH` that records its arguments, and a temporary lock path in `QSE_PIPELINE_LOCK`):
  - `test_no_argument_runs_the_full_pipeline_as_before`: the recorded arguments hold `--data-only` and not `--price-only`.
  - `test_price_only_runs_the_price_step_and_no_background_work`: the arguments hold `--price-only --run-kind evening`; the stub was started once.
  - `test_retry_price_passes_only_if_failed`; `test_login_check_takes_no_lock`: it runs while another process holds the lock.
- [ ] **Acceptance:** the tests pass; `QSE:tests/scripts/test_script_modes.py` passes (the file stays executable).
- [ ] **Commit.**

PR acceptance, on the laptop (owner step O5): the check exists and `QSE_LAKE_HC_URL` is set; a forced failure reaches the owner; a good run turns the check green; the cron lines are installed and one evening run completes.

---

## PR P1b. Refresh the copy of QSE's list; the order test

Repo: PortfolioSight. Branch `feat/qse-list-refresh`. Agent: sonnet, xhigh. After Q1 is merged and the load of owner step O4 has run (spec 4, steps 3 and 4).

### Task P1b.1

**Files:** Modify `data/universes/qse_portfoliosight.txt`. Test `tests/data/test_universe.py`.

- [ ] **Test first:** `test_every_wanted_symbol_is_on_a_qse_list`: every tier 1 fund, tier 2 fund and requested ticker that is not TSP and has no note is in `qse_core.txt` or `qse_portfoliosight.txt`.
- [ ] **Change:** the file is QSE's file at the merged commit: `git -C /home/jeff/programming/quant-scenario-engine show <merged sha>:qse/config/universes/datalake_portfoliosight.txt`, under the first line `# Copy of qse/config/universes/datalake_portfoliosight.txt at QSE commit <sha7> (629 symbols).`
- [ ] **Acceptance:** the test passes. Count pins of 356 in `tests/data/test_universe.py:72`, `:76` and the tail pin at `:80` are recomputed from the files; see the list at the end.
- [ ] **Commit.**

---

## PR P2. Sync rules, labels, the archive, the second window and TSP

Repo: PortfolioSight. Branch `feat/lake-wins-archive-second-window`. Agent: opus, high (data integrity). After P1b and the load.

Tests extend the fixtures of `tests/data/test_sync_lake.py:54-205`. The helper that writes the test lake (`:82-88`) also writes `_corporate_actions_state.json` from this PR on.

### Task P2.1: name and kind from `funds.json`

**Files:** Modify `scripts/sync_lake.py:224-269`, `354-388`. Test `tests/data/test_sync_lake.py`.

**Interfaces:** consumes `load_funds` (P1.1). `sync(..., funds: Mapping[str, FundMeta] | None = None)`; `None` loads the committed file.

- [ ] **Test first:** `test_name_and_kind_come_from_funds_json`: `funds={"BND": FundMeta("Vanguard Total Bond Market ETF", "etf")}` while the lake's files give `BND` another name; the entry's name and kind are those of `funds`. `AAPL`, outside `funds`, keeps the lake's name as today (`tests/data/test_sync_lake.py:478`).
- [ ] **Change:** name order: `funds.json`, the lake's `fundamentals_full` file, the lake's US symbol list, the catalog's current name, the ticker (spec 8). Kind: `funds.json`, then the universe's kind, then the catalog's, then `etf`.
- [ ] **Acceptance:** the test passes.
- [ ] **Commit.**

### Task P2.2: the lake wins; nothing is released to `seed`

**Files:** Modify `scripts/sync_lake.py:82-83`, `86`, `191-193`, `230-231`, `316-351`, `370-405`; `portfoliosight/data/lake.py:34`, `165-189`. Tests `tests/data/test_sync_lake.py`, `tests/data/test_lake.py`.

**Interfaces (produces):** `apply_lake(manifest, overlay, d_g) -> None` no longer changes any entry's source. A symbol the sync took earlier that does not qualify in this run keeps its overlay entry and its stored record; its status follows the date rule. A symbol with a note in `tiers.json` (FIENX) is never taken: new skip reason `SKIP_NOTED = "data ended"`.

- [ ] **Test first:**
  - `test_the_lake_takes_a_tier_2_fund_a_provider_kept`: `BND` has a `tiingo` entry and the lake vouches it; after the sync its entry is `source: lake`.
  - `test_a_taken_symbol_that_falls_behind_stays_lake_and_stale_and_comes_back`: the lake stops vouching `MSFT` and time moves past the served rule: entry `source == "lake"`, `status == "stale"`, record bytes unchanged. The lake vouches it again: `status == "ok"`.
  - `test_no_run_writes_seed`: across the runs above, the set of symbols whose source is `seed` after each run is a subset of that set before it.
- [ ] **Change:** remove the provider rule and the release.
- [ ] **Acceptance:** the tests pass. `test_a_symbol_the_lake_stops_vouching_is_released` (`tests/data/test_sync_lake.py:337`) and the release half of `test_apply_lake_replaces_restatuses_and_releases` (`tests/data/test_lake.py:57`) test the removed release; they are replaced by the tests above and the PR body says so.
- [ ] **Commit.**

### Task P2.3: archive before replace

**Files:** Create `portfoliosight/data/migration.py`, `tests/data/test_migration.py`. Modify `scripts/sync_lake.py:286-293`, `420-465`. Test `tests/data/test_sync_lake.py`.

**Interfaces (produces):**
- `MIGRATION_KEY = "meta/migration.json"`; `ARCHIVE_PREFIX = "archive/prices/"`; `OLD_SOURCES = frozenset({"tiingo", "seed+tiingo", "seed"})`.
- `compare_records(old: pd.DataFrame, new: pd.DataFrame) -> dict` with `old_first_date`, `new_first_date`, `overlap_start`, `overlap_end`, `growth_old`, `growth_new` (growth of one dollar over the shared dates, from each record's `tr_index`), `largest_year_difference: {"year", "old", "new"}` (the calendar year, within the shared dates, whose returns differ most).
- `archive_record(store, symbol: str, old_source: str, data: bytes) -> str`: writes `archive/prices/{SYMBOL}.{old_source}.parquet` only if that key is absent; if it is present with the same bytes, uses it; if present with other bytes, writes `archive/prices/{SYMBOL}.{old_source}.{first 12 hex of sha256}.parquet` instead. Reads the key back and compares bytes. Returns the key. Raises `ArchiveFailed` on any store error or mismatch. It never overwrites and never deletes.
- A report row: `{"old_source", **compare_records, "state": "archived" | "moved", "archive_key", "moved_at"}` under `rows[SYMBOL]` of `meta/migration.json`, written with `update_json` (`portfoliosight/data/store.py:326-356`).

The move, for a symbol the lake vouches inside the window. It applies whenever `prices/{SYMBOL}.parquet` exists and the previous overlay does not hold the symbol with a digest, whatever the entry's label says (so a leaked label can never skip the archive):

1. Read the old record with its tag: `store.get_tagged` (`store.py:141-144`, `231-239`).
2. Write the report row, state `archived` pending, with the comparison.
3. `archive_record`. On `ArchiveFailed` the fund stops here: record and label untouched, exit code 1.
4. Publish the claim (the existing first step, `sync_lake.py:420-427`), so the Tiingo walk stops touching the symbol (`download.py:298-306`).
5. Replace the record with `store.put_if(key, new_bytes, tag)` (`store.py:146-157`, `241-255`). A refusal means the record changed after step 1: the fund stops, the claim is withdrawn, and the catalog write puts back the entry read at the start of the sync if it had become `lake`. The next poll starts again at step 1.
6. The overlay and the catalog carry `source: lake`; the report row gets `state: moved`, the archive key and the time.

A symbol with no stored record is written with `put_if(key, new_bytes, None)`.

- [ ] **Test first** (`.venv/bin/python -m pytest tests/data/test_migration.py tests/data/test_sync_lake.py -q -k "move or archive or migration"`):

```python
def test_compare_records_gives_first_dates_growth_and_the_largest_year_difference():
    old = _record(["2026-01-02", "2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08"],
                  tr=[1.0, 2.0, 2.02, 2.04, 2.06])
    new = _record(["2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08"],
                  tr=[1.0, 1.01, 1.02, 1.0403])
    row = compare_records(old, new)
    assert row["old_first_date"] == "2026-01-02" and row["new_first_date"] == "2026-01-05"
    assert (row["overlap_start"], row["overlap_end"]) == ("2026-01-05", "2026-01-08")
    assert row["growth_old"] == pytest.approx(1.03) and row["growth_new"] == pytest.approx(1.0403)
    assert row["largest_year_difference"]["year"] == 2026
    assert row["largest_year_difference"]["old"] == pytest.approx(0.03)
    assert row["largest_year_difference"]["new"] == pytest.approx(0.0403)
```

  - `test_a_tiingo_fund_the_lake_vouches_is_moved_whole`: the stored record equals `eod_to_record` of the lake's whole file (`portfoliosight/data/lake.py:45-61`), with no `tr_index` after the vouched date; `source == "lake"`; the name is unchanged; `meta/migration.json` has its row with `state == "moved"`; the archive key's bytes equal the old record's bytes.
  - `test_an_archive_that_cannot_be_written_leaves_record_and_label` and `test_an_archive_that_reads_back_different_leaves_record_and_label` (store subclasses, as `RacingStore` at `tests/data/test_sync_lake.py:367`): the record's bytes and the entry are unchanged, the overlay does not hold the symbol, the exit code is 1.
  - `test_a_record_that_changes_during_the_move_is_not_replaced`: a store that rewrites `prices/BND.parquet` right after the archive write. The stored record is the rewritten one, the entry is still `tiingo`. A second sync archives the rewritten bytes under the digest key and moves the fund; both archive keys exist.
  - `test_an_archive_key_is_never_overwritten`: the key exists with other bytes before the sync; after it, those bytes are still there.
  - `test_a_fund_the_lake_does_not_vouch_keeps_bytes_and_label`, and in the same test FIENX: entry and record bytes unchanged, no archive key, no report row.
  - `test_after_any_run_the_store_holds_every_key_it_held_before`: for the runs above, the key list before each sync is a subset of the key list after it.
  - `test_the_report_shows_a_first_date_that_moved`: the row of a fund whose lake history starts later holds both first dates.
- [ ] **Change:** as numbered. The dry run counts the funds that would move.
- [ ] **Acceptance:** all tests pass.
- [ ] **Commit.**

### Task P2.4: the report lists every requested ticker

**Files:** Modify `scripts/sync_lake.py:316-351`, `385-408`. Test `tests/data/test_sync_lake.py`.

**Interfaces (produces):** the report gains `requested: dict[str, str]` and `old_source_ok: list[str]` (served entries whose source is still an old one). Each requested ticker's line is `on the menu` or `not yet: {reason}`, the reason being the skip reason or the entry's status reason.

- [ ] **Test first:** `test_the_report_lists_every_requested_ticker_with_its_outcome`: requested `("AAPL", "PART", "ZZZQ")` where the lake vouches `AAPL`, holds `PART` unvouched and has no `ZZZQ`. The emitted lines include `requested AAPL: on the menu`, `requested PART: not yet: not vouched by the lake`, `requested ZZZQ: not yet: not in the lake`, and the dry run prints all three and writes nothing.
- [ ] **Acceptance:** the test passes.
- [ ] **Commit.**

### Task P2.5: the label `prices_from_yfinance`

**Files:** Modify `portfoliosight/data/manifest.py:27-45`, `scripts/sync_lake.py:116-130`, `253-266`. Tests `tests/data/test_manifest.py`, `tests/data/test_sync_lake.py`.

**Interfaces:** consumes the lake state field `price_source` (Q2.5). Produces `ManifestEntry.prices_from_yfinance: bool = False`; `LakeRun.yfinance_priced: frozenset[str]`, read from `_corporate_actions_state.json`. A state file that is missing or cannot be read raises `LakeUnreadable` (`scripts/sync_lake.py:97-98`).

- [ ] **Test first:**
  - `test_a_fund_priced_from_the_yahoo_library_carries_the_label`: the state file marks `PART`; its entry has `prices_from_yfinance is True`, every other taken entry `False`.
  - `test_an_unreadable_state_file_uploads_nothing`: the file holds `{not json`; exit code 1 and the store's key list and bytes are unchanged.
- [ ] **Acceptance:** the tests pass. `ENTRY_KEYS` in `tests/data/test_manifest.py` gains the new key; see the list at the end.
- [ ] **Commit.**

### Task P2.6: two sync windows, from a setting

**Files:** Modify `scripts/sync_lake.py:73-74`, `133-156`; `scripts/install_sync_lake_cron.sh:3-10`. Tests `tests/data/test_sync_lake.py`, `tests/data/test_backup_scripts.py`.

**Interfaces (produces):** `Window(ready: time, last_poll: time)`; `windows_from_env(env) -> tuple[Window, ...]` reading `PS_SYNC_WINDOWS`, default `06:45-09:50,18:00-21:50`; `gate(now, generated_at, force, windows) -> tuple[bool, int, str]`. The active window is the latest one whose `ready` has passed today; a lake run is complete for it when `generated_at` is at or after its `ready` time today. The installer writes one cron line whose hour field comes from `PS_SYNC_CRON_HOURS`, default `7-9,18-21`. One line for both windows, because frozen A-PS-58 allows at most one lake-sync line; the poll at 18:00 simply waits.

- [ ] **Test first** (times on 2026-10-14, Pacific Daylight Time):
  - `test_each_window_takes_only_a_run_written_after_its_start`: poll at 18:10 with a run written at 17:59 waits (exit 0, nothing uploaded); with a run written at 18:07 it syncs. Poll at 07:30 with a run written at 06:50 syncs, as today.
  - `test_each_windows_last_poll_is_an_alert`: poll at 21:50 with the morning's run still the latest gives exit code 1 and an `ALERT` line; the same at 09:50 with yesterday evening's run.
  - `test_windows_come_from_the_setting`: `windows_from_env({"PS_SYNC_WINDOWS": "05:00-06:00"})` gives one window, 05:00 to 06:00; a malformed value raises `ValueError`.
  - Installer test: the line written is `*/10 7-9,18-21 * * 1-5 ...`, and with `PS_SYNC_CRON_HOURS=5-6` it is `*/10 5-6 * * 1-5 ...`; still exactly one line.
- [ ] **Acceptance:** the tests pass; `test_an_incomplete_lake_run_is_refused` (`tests/data/test_sync_lake.py:292-311`) passes unchanged. The pinned cron line at `tests/data/test_backup_scripts.py:185` changes; see the list at the end.
- [ ] **Commit.**

### Task P2.7: TSP on the laptop

**Files:** Create `portfoliosight/data/tsp_sync.py`, `tests/data/test_tsp_sync.py`. Modify `portfoliosight/data/calendar.py` (one helper), `scripts/sync_lake.py:470-505`.

**Interfaces (produces):**
- `latest_closed_session(now: datetime) -> date`: the last XNYS session whose close is at or before `now`. In the evening window that is today's session; the generation date of an evening poll is still the day before (`portfoliosight/data/calendar.py:29-45`), so it cannot be used here.
- `TspResult(requested: bool, stored: bool, current: bool, error: str | None)`; `sync_tsp(store, now: datetime, provider, sleep: Callable[[float], None]) -> TspResult`.

`sync_tsp` runs only after the window's lake run is synced. If every TSP entry's last date already reaches `latest_closed_session(now)` it asks nothing. Otherwise it downloads the whole file once (`TspProvider.fetch_all`, `portfoliosight/data/providers/tsp.py:141-152`), with three tries and waits doubling from 2 s to at most 20 s. For each fund it builds the whole record from the file (`provider_rows_to_record`, `portfoliosight/data/returns.py:62`) and stores it only when the new record starts no later and ends no earlier than the stored one; then it updates that fund's entry (source `tsp`, dates, `fetched_at`, status by the date rule against `generation_date(now)`) with the conditional catalog write the sync uses (`scripts/sync_lake.py:445-458`). A failed download touches nothing. It does not go through the downloader: the existing refresh skips a fund that reaches the generation date (`portfoliosight/data/download.py:380`), so an evening poll would never store the day's price, and it marks TSP stale on one failed fetch (`download.py:55`).

- [ ] **Test first** (a fake provider with a tiny CSV, as `tests/data/test_tsp.py:41`):
  - `test_latest_closed_session_is_today_in_the_evening_and_yesterday_in_the_morning`: 2026-11-17 18:10 Pacific gives 2026-11-17; 2026-11-17 07:00 Pacific gives 2026-11-16.
  - `test_tsp_is_fetched_after_the_lake_sync_and_stored`: an evening poll; one download; the 16 records end on the day's session; the entries are `source: tsp`, `status: ok`.
  - `test_a_failed_tsp_fetch_keeps_the_funds_served`: the download raises three times; three tries, two sleeps between 2 and 20; every TSP entry and record is unchanged and still `ok`; `result.error` is set.
  - `test_a_tsp_file_that_lost_history_replaces_nothing`: the file starts later than the stored record; the stored bytes are unchanged and `result.error` names the fund.
  - `test_tsp_already_current_asks_nothing`: no download.
  - `test_tsp_is_not_fetched_while_the_lake_run_is_missing`: the sync waits; no download.
- [ ] **Acceptance:** the tests pass; `portfoliosight/data/download.py` is unchanged in this task.
- [ ] **Commit.**

### Task P2.8: alerts from the sync

**Files:** Create `portfoliosight/data/alerts.py`, `tests/data/test_alerts.py`. Modify `scripts/sync_lake.py:470-512`, `portfoliosight/data/secrets.py` (the new names join the redacted ones). Test `tests/data/test_sync_lake.py`.

**Interfaces (produces):** `send_alert(ok: bool, title: str, message: str, *, env: Mapping[str, str], post: Callable) -> list[str]`, with the behavior of Q3.5. Names: `PS_SYNC_HC_URL`; `PUSHOVER_TOKEN`, `PUSHOVER_USER` and `PS_PUSHOVER_URL` (the Pushover address; all three must be set for Pushover to send). `LATE_ALERT_SESSIONS = 5`. One ping per poll: a failure when any rule below holds, else a success when the window's lake run is synced, else nothing.

Failure rules (spec 7.3): the lake run is not complete at the window's last poll; a record could not be stored; the sync crashed; no TSP download succeeded in this window by its last poll; a tier 1 or 2 fund is 5 or more sessions late (`trading_days_behind`, `portfoliosight/data/calendar.py:83-88`, on the older of its two dates), listed by ticker.

- [ ] **Test first:**
  - `test_one_request_per_channel_that_is_set_and_none_without_an_address` and `test_a_failed_request_never_changes_the_exit_code` (as Q3.5).
  - `test_a_run_missing_at_the_last_poll_is_a_failure_and_a_synced_run_a_success`.
  - `test_a_fund_five_sessions_late_fails_and_is_named`: `BND` five sessions behind gives one failure whose message contains `BND`; four sessions behind gives a success.
  - `test_the_alert_address_never_reaches_the_log`: the address value is absent from every captured log line.
- [ ] **Acceptance:** the tests pass; `tests/test_hygiene.py` passes unchanged (no new host in the code).
- [ ] **Commit.**

### Task P2.9: served for 10 trading days; `pending` no longer given. BLOCKED-D3

Frozen A-PS-07 and A-PS-59 pin the 3-session rule and `pending`. Do not start until the owner answers D3 with yes and the gate change is done.

**Files:** Modify `portfoliosight/data/manifest.py:18`, `102-116`, `scripts/sync_lake.py:88`. Tests `tests/data/test_manifest.py`, `tests/data/test_lake.py`.

- [ ] **Test first:** `test_a_fund_is_served_for_ten_sessions_across_a_holiday_week`: generation date 2026-12-02. `session_back(date(2026, 12, 2), 10) == date(2026, 11, 17)` (Thanksgiving, 2026-11-26, is not a session). For k from 0 to 10, an entry whose two dates are k sessions back is `ok`; at k = 11 (2026-11-16) it is `stale` with reason `no data since 2026-11-16`. An entry with source `seed` follows the same date rule and is never `pending`.
- [ ] **Change:** `SERVED_WITHIN_SESSIONS = 10`; remove the `seed` branch of `status_for`.
- [ ] **Acceptance:** the test passes. Pins in `tests/data/test_manifest.py:78-96` and `tests/data/test_lake.py:46` change; see the list at the end.
- [ ] **Commit.**

PR acceptance, on the laptop (owner step O6): the dry run prints how many funds move to the lake and each requested ticker's outcome; after the real run `meta/migration.json` exists, every replaced fund has an archive copy, and the number of served entries with an old source is reported.

---

## PR P3. The page shows the as-of date

Repo: PortfolioSight. Branch `feat/fund-as-of-date`. Agent: sonnet, xhigh. With or after P2.

### Task P3.1

**Files:** Modify `web/src/sections/Funds.tsx:366-377`, `web/src/copy.ts` (next to `staleLine`, `:210`), `web/src/api/tensor.ts:122-123` (the comment's "three sessions"), `docs/specs/2026-10-13-portfoliosight-demo-design.md` section 3.6 (one row). Create `web/tests/funds-asof.test.tsx`.

**Interfaces (produces):** `pricesAsOf(date: string) => string` returning `prices as of {date}` (ISO date, as `staleLine` shows dates); a note with `data-testid="asof-note"` inside the fund's row.

- [ ] **Test first** (`cd web && npx vitest run tests/funds-asof.test.tsx`; render as `web/tests/funds.test.tsx:35` does): tensor `asof` 2026-11-16. A fund in use whose `last_close_date` is `2026-11-12` shows `prices as of 2026-11-12` in its row. A fund whose `last_close_date` is `2026-11-16`, and a fund without the field, show no such note.
- [ ] **Change:** the note is shown for a fund in use whose `last_close_date` is before the tensor's `asof` (the data is already sent, `portfoliosight/engine/builder.py:126-129`).
- [ ] **Acceptance:** `cd web && npm run lint && npm run typecheck && npm run test`, then `npm run build` and `npm run e2e:local` (the build must come first: the local run serves `dist/`).
- [ ] **Commit.**

---

## PR P4. Daily build with no price fetch, behind the gate. BLOCKED-D3

Repo: PortfolioSight. Branch `feat/nightly-no-fetch-gate`. Agent: opus, high (data integrity). Frozen A-PS-30 pins the price providers, the TSP request and publishing without a lake record. Do not start until the owner answers D3 with yes and the gate change is done. Also only after P2 runs TSP on the laptop, and when P2 reports no served entry with an old source or the owner accepts the list left behind.

### Task P4.1: the gate

**Files:** Create `portfoliosight/jobs/publish_gate.py`, `tests/jobs/test_publish_gate.py`. Modify `portfoliosight/data/calendar.py` (one helper).

**Interfaces (produces):** `session_close(day: date) -> datetime` (UTC). `publish_allowed(overlay: LakeOverlay, d_g: date) -> tuple[bool, str]`: true only when `overlay.generated_at` is after `session_close(d_g)` and the latest `adjusted_through` among the overlay's entries is `d_g` or later. The lake writes `generated_at` at the end of its run (`QSE:qse/data/total_return_lake.py:517-518`), so "the run started after the close" in spec 3.1 is checked as "the run was written after the close".

- [ ] **Test first** (generation date 2026-11-16, a Monday; its session closed at 21:00 UTC):
  - `test_a_run_from_before_the_close_is_refused`: `generated_at` `2026-11-14T02:10:00+00:00` (Friday evening) gives `(False, reason)` and the reason names both times.
  - `test_a_run_after_the_close_with_an_older_vouched_date_is_refused`: `generated_at` `2026-11-17T02:10:00+00:00`, latest vouched 2026-11-13.
  - `test_a_run_that_meets_both_is_allowed`: the same `generated_at`, latest vouched 2026-11-16.
  - `test_no_lake_record_is_refused`: an empty overlay.
- [ ] **Acceptance:** the tests pass.
- [ ] **Commit.**

### Task P4.2: the nightly fetches nothing and asks the gate

**Files:** Modify `portfoliosight/jobs/nightly.py:1-22`, `235-355`, `358-371`, `399-426`; `deploy/docker-compose.yml:50-53`. Tests `tests/jobs/test_nightly.py`, `tests/deploy/test_compose.py`. `deploy/systemd/portfoliosight-nightly.timer` is not changed.

**Interfaces (produces):** `run(*, store, now, build_fn=None, clock=None) -> dict`. No providers, no refresh. Before building it applies the overlay and recomputes every status against the generation date (`apply_lake`, `manifest_mod.restatus`, `portfoliosight/data/manifest.py:139-152`) and writes the catalog. If the generation is not yet published and `publish_allowed` says no, it builds nothing, writes the reason to `meta/status.json` under step `publish`, leaves `meta/current.json` as it is, and the entry point exits 1.

- [ ] **Test first** (fast fake build as `_FastBuild`, `tests/jobs/test_nightly.py:79`):
  - `test_the_run_builds_and_publishes_from_the_store_with_no_provider_and_no_network`: `socket.socket` is replaced by a function that fails the test; the run publishes.
  - `test_a_lake_run_from_before_the_close_publishes_nothing`, `test_an_older_vouched_date_publishes_nothing`: the bytes of `meta/current.json` are unchanged and no key exists under `tensors/{G}/`.
  - `test_a_run_that_meets_both_publishes`.
  - `test_a_fund_four_sessions_late_stays_served_and_one_eleven_late_is_set_aside`: after the run the first entry is `ok` and the second `stale` with reason `no data since {its date}` (needs P2 task 9).
  - `test_pruning_never_touches_prices_or_archive`: after a run that prunes an old generation, every key under `prices/` and `archive/` is still there.
- [ ] **Change:** remove `refresh` and the provider setup; add the gate. The nightly's tests of the removed fetch (`tests/jobs/test_nightly.py:251`, `291`, `328`, `388`, `413`, `434`, `781`, `849`, `870`) go with it; the PR body lists each.
- [ ] **Acceptance:** the tests pass. On KS-001 the day after (owner step O7): the current generation is the previous session's, built at 02:00; the log shows no outside price request; the KS-001 secrets file no longer needs the Tiingo key.
- [ ] **Commit.**

---

## PR P5. Remove the retired code and amend the demo spec. BLOCKED-D3, and needs the owner's go

Repo: PortfolioSight. Branch `chore/retire-tiingo`. Agent: sonnet, xhigh. Frozen A-PS-02, 03, 04, 06, 10 and 14 exercise the code this PR removes.

### Task P5.1: remove code only, no stored data

**Files:** Remove `portfoliosight/data/providers/tiingo.py`, the Tiingo part of `portfoliosight/data/download.py`, `portfoliosight/data/budget.py`, `portfoliosight/data/limits.py`, `scripts/seed_r2_from_lake.py`, `scripts/backfill_names.py`, `scripts/record_provider_fixtures.py`, and the tests of those features (`tests/data/test_tiingo.py`, `test_budget.py`, `test_seed.py`, `test_splice.py`, `test_backfill_names.py`, `test_live_provider.py`, and the Tiingo cases of `test_download.py`). Keep `portfoliosight/data/providers/tsp.py`, `portfoliosight/data/providers/base.py` and `provider_rows_to_record` (`portfoliosight/data/returns.py:62`), which the TSP fetch of P2.7 uses. What is left of `download.py` after the Tiingo walk is gone is removed too if nothing imports it. Update the host lists in `tests/test_hygiene.py:22`, `:62-74`, `:94-103`.

- [ ] **Test first:** the existing TSP tests (`tests/data/test_tsp.py`, `tests/data/test_tsp_sync.py`) and the sync and nightly tests are the regression net; they must pass before and after. No new test.
- [ ] **Acceptance:** `grep -ri tiingo portfoliosight scripts` prints nothing; lint, type check and tests pass; line coverage stays above 80 percent.
- [ ] **Commit.**

### Task P5.2: amend the demo spec (documents only)

**Files:** `docs/specs/2026-10-13-portfoliosight-demo-design.md` and `docs/specs/2026-10-13-portfoliosight-demo-design.assertions.md`, the sections of spec Appendix B.

- [ ] **Change:** each row of Appendix B, in order.
- [ ] **Acceptance:** each amended section names this spec and its date.
- [ ] **Commit.**

---

## Owner-only steps

None of these blocks writing code. Each gates turning something on. Laptop paths are as the cron lines have them (`$HOME/programming/...`); the QSE path on the laptop was not checked from this machine.

**O1. Schwab measurement (G0).** After the G0 PR is merged. On a trading day, on the laptop:

```bash
cd ~/programming/quant-scenario-engine
set -a; . ~/.secrets/qse.env; set +a
python3 scripts/probe_schwab_funds.py --out-dir runs/live/schwab_probe --label 1400   # at 14:00 PT
python3 scripts/probe_schwab_funds.py --out-dir runs/live/schwab_probe --label 1600   # at 16:00 PT
python3 scripts/probe_schwab_funds.py --out-dir runs/live/schwab_probe --label 1800   # at 18:00 PT
python3 scripts/probe_schwab_funds.py --out-dir runs/live/schwab_probe --label 2000   # at 20:00 PT
python3 scripts/probe_schwab_funds.py --out-dir runs/live/schwab_probe --label 0645   # next trading day, 06:45 PT
python3 scripts/probe_schwab_funds.py --out-dir runs/live/schwab_probe \
  --report docs/reviews/$(date +%F)-schwab-funds-probe.md \
  --fixture tests/data/schwab_funds_probe_$(date +%F).json
```

The report decides: the evening run time (the cron line of O5); whether Q2 task 7 is built; whether D1 needs an answer; the value passed as `--price-tolerance` in O4.

**O2. healthchecks.io.** Create two checks, one for the lake update and one for the sync. Each must alarm when a weekday passes with no ping: that is what reports "the laptop was off". Put the addresses in the two secrets files yourself, under the names `QSE_LAKE_HC_URL` (in the QSE file) and `PS_SYNC_HC_URL` (in the PortfolioSight file). Confirm `QSE_SCHWAB_HC_URL` is set in the QSE file and that its check now expects a ping every day of the week (O5 adds the weekend line).

**O3. After Q1 is merged,** the morning after the next lake run:

```bash
cd ~/programming/quant-scenario-engine
grep "Schwab EOD universe" runs/live/cron.log | tail -1      # expect: 629 PortfolioSight-only symbols
```

and confirm the dataset holds the same tickers as the day before.

**O4. The load (Q2).** After Q1 and Q2 are merged, O1 is done, and the QSE Step 2 session has confirmed its frozen copy of the lake is taken. On the laptop:

```bash
cd ~/programming/portfoliosight
.venv/bin/python scripts/export_qse_fetch_list.py --new-only --out /tmp/new_symbols.txt     # 273 lines, before P1b
cd ~/programming/quant-scenario-engine
set -a; . ~/.secrets/qse.env; set +a
python3 scripts/lake_start.py --symbols-file /tmp/new_symbols.txt \
  --price-tolerance <value from the O1 report> \
  --report-json runs/live/lake_start_$(date +%F).json
```

Held-out check: before the load, name ten of the 273 that are not in the measurement's list. Proposed: VFIAX, FSKAX, SWTSX, AGTHX, PRWCX, DODFX, IWF, VYM, BIV, MUB. The PR for P1b records their lines from the report: each must be `loaded` with no reason, which means Schwab's closes agreed with yfinance's within the tolerance and the lake's adjusted series agreed with yfinance's adjusted close.

For a symbol the report lists with `schwab_no_data` that you want served from yfinance: `python3 scripts/lake_start.py --symbols SYM --yfinance-prices SYM --price-tolerance <value> --report-json ...`.

**O5. Turning on the evening run and the alerts (Q3).** After Q3 is merged and O2 is done:

```bash
( set -a; . ~/.secrets/qse.env; set +a; \
  curl -fsS -m 10 --data-raw "forced failure test" "${QSE_LAKE_HC_URL%/}/fail" )   # the alert must reach you
crontab -e    # add, under the existing CRON_TZ=America/Los_Angeles line:
#  0 18 * * 1-5  <QSE>/scripts/daily_pipeline_cron.sh price-only          >> <QSE>/runs/live/cron.log 2>&1
#  0 20 * * 1-5  <QSE>/scripts/daily_pipeline_cron.sh retry-price evening >> <QSE>/runs/live/cron.log 2>&1
# 45  8 * * 1-5  <QSE>/scripts/daily_pipeline_cron.sh retry-price morning >> <QSE>/runs/live/cron.log 2>&1
# 45  6 * * 6,0  <QSE>/scripts/daily_pipeline_cron.sh login-check         >> <QSE>/runs/live/cron.log 2>&1
```

The 18:00 line is the spec's time and needs validation; use the time the O1 report supports. After the first evening run the lake check must be green.

**O6. The sync (P2).** After P2 is merged, on the laptop:

```bash
cd ~/programming/portfoliosight
.venv/bin/python scripts/sync_lake.py --dry-run --force     # prints how many funds move and each requested ticker
.venv/bin/python scripts/sync_lake.py --force               # the real run
bash scripts/install_sync_lake_cron.sh                      # one line, both windows
```

Check that `meta/migration.json` exists and read the count of served entries that still have an old source.

**O7. The build (P4).** After D3 and the P4 merge: `make deploy-backend`. The next morning: `curl -s https://portfoliosight.ai/api/health` shows `asof` equal to the previous session; the KS-001 log shows no outside price request; then remove the Tiingo key from the KS-001 secrets file.

**O8. Decide D3,** and if yes, order the gate change for the named checks.

**O9. Later: Pushover.** Set `PUSHOVER_TOKEN` and `PUSHOVER_USER` in both secrets files, and `PS_PUSHOVER_URL` (the Pushover messages address) in the PortfolioSight file. No code change.

**O10. Give the go for P5.** Review late distributions after December 2026 (spec 1, decision 9).

Every merge is the owner's.

## Existing tests whose pinned values change

No test here is weakened. Each pins data or a rule that the spec changes.

| Test | Pin | New value | Why |
|---|---|---|---|
| `tests/data/test_universe.py:70-80` | tier 3 is core plus the second list; last three symbols | plus the 26 requested tickers; last three `TM`, `UL`, `UNCRY` (P1.2); recomputed after the copy grows to 629 (P1b) | spec 4.1; spec 4 step 4 |
| `QSE:tests/scripts/test_daily_pipeline.py:666-677` | 356 symbols | 629 | spec 4 |
| `QSE:tests/scripts/test_daily_pipeline.py:345`, `:364` | errors of the list rebuild | replaced by the missing-list test | spec 4, the hole Q1 closes |
| `QSE:tests/scripts/test_daily_pipeline.py:132`, `:146`, `:156`, `:1105` | warning from 4 days before expiry (ages 3.1 and 4.0 warn; window at least 4) | warning from 2 days (ages become 5.1 and later; window is 2 with a check every day) | owner decision 7 |
| `tests/data/test_sync_lake.py:337`, `tests/data/test_lake.py:57` | release to `seed` | replaced | spec 6 |
| `tests/data/test_manifest.py` `ENTRY_KEYS` | entry keys | plus `prices_from_yfinance` | spec 6 |
| `tests/data/test_backup_scripts.py:185` | cron hours `7-9` | `7-9,18-21` | spec 3.1 |
| `tests/data/test_manifest.py:78-96`, `tests/data/test_lake.py:46` | 3 sessions; seed is `pending` | 10 sessions; no `pending` | spec 7.1, spec 6. BLOCKED-D3 |
| `tests/jobs/test_nightly.py:251`, `291`, `328`, `388`, `413`, `434`, `781`, `849`, `870` | the nightly's price fetch | removed with it | spec 3.1. BLOCKED-D3 |

## Expectations: which task and test proves each

| Expectation | Task | Test |
|---|---|---|
| S1 a wanted fund appears once the lake has checked it | P1b.1; P2.4 | `test_every_wanted_symbol_is_on_a_qse_list`; `test_the_report_lists_every_requested_ticker_with_its_outcome` |
| S2 the 29 tickers, one by one | P2.4 | `test_the_report_lists_every_requested_ticker_with_its_outcome` |
| S3 the morning after, portfolios are dated that trading day | P4.1, P4.2 (BLOCKED-D3); Q3.6 | `test_a_run_that_meets_both_publishes`; `test_price_only_runs_the_login_check_and_the_price_step_and_nothing_else`; owner step O7 |
| S4 a late fund is usable for 10 trading days, with its date | P2.9 (BLOCKED-D3); P3.1 | `test_a_fund_is_served_for_ten_sessions_across_a_holiday_week`; the as-of test of P3.1 |
| S5 alert two days before the login runs out, weekends too | Q3.7 | `test_two_and_a_half_days_left_is_healthy_and_one_point_nine_is_an_alert`; `test_the_weekend_check_only_reports` |
| S6 alert when the update fails or nothing ran | Q3.4, Q3.6; P2.8 | `test_a_price_step_that_dies_gives_failed_and_one_alert`; `test_a_run_missing_at_the_last_poll_is_a_failure_and_a_synced_run_a_success`; silence: owner step O2 |
| S7 healthchecks.io now, Pushover the day the keys exist | Q3.5; P2.8 | `test_an_alert_makes_one_request_per_channel_that_is_set`; `test_one_request_per_channel_that_is_set_and_none_without_an_address` |
| S8 one job on the laptop; TSP on the laptop; the server fetches nothing | P2.7; P4.2 (BLOCKED-D3) | `test_tsp_is_fetched_after_the_lake_sync_and_stored`; `test_the_run_builds_and_publishes_from_the_store_with_no_provider_and_no_network` |
| S9 without EODHD and Tiingo everything still works | Q2.6; Q2.3; Q3.6 | `test_build_only_makes_no_network_call`; `test_a_symbol_blocked_by_adj_base_gap_is_vouched_after_rebuild`; `test_price_only_runs_the_login_check_and_the_price_step_and_nothing_else` |
| S10 every old record still exists; a report says how they differ | P2.3 | `test_a_tiingo_fund_the_lake_vouches_is_moved_whole`; `test_compare_records_gives_first_dates_growth_and_the_largest_year_difference` |
| S11 QSE's experiments run on the same list | Q1.1 | `test_the_price_step_gets_n_plus_m_and_the_dataset_names_the_core_file_only` |
| S12 a later ticker is added by a short procedure, no new code | P1.3 | `test_adding_a_line_to_requested_txt_reaches_the_export` |
| S13 the job moves by changing settings | Q3.1; Q2.6; P2.6 | `test_the_lake_and_state_folders_come_from_settings`; `test_the_command_runs_against_a_lake_in_a_temporary_folder`; `test_windows_come_from_the_setting` |
| F1 a date published without its prices | P4.1, P4.2 (BLOCKED-D3) | `test_a_run_from_before_the_close_is_refused`; `test_a_lake_run_from_before_the_close_publishes_nothing` |
| F2 a payout never recorded | Q2.4 | `test_load_refuses_and_writes_nothing` (case `yfinance_no_answer`); `test_a_new_symbol_whose_adjusted_series_disagrees_is_not_vouched` |
| F3 yfinance prices used quietly when Schwab fails | Q2.5 | `test_a_schwab_failure_never_brings_a_yfinance_price` |
| F4 a requested ticker counted as done but never appears | Q2.6; P2.4 | `test_the_command_runs_against_a_lake_in_a_temporary_folder` (the refused symbol and its reason); `test_the_report_lists_every_requested_ticker_with_its_outcome` |
| F5 an "archive" written over the original, never checked | P2.3 | `test_an_archive_that_cannot_be_written_leaves_record_and_label`; `test_an_archive_that_reads_back_different_leaves_record_and_label`; `test_a_record_that_changes_during_the_move_is_not_replaced` |
| F6 an alert "sent" to a channel with no keys | Q3.5; P2.8 | `test_an_alert_makes_one_request_per_channel_that_is_set` (the empty list and the log line) |
| F7 Schwab down for part of the list, day counted as good | Q3.3; Q3.4 | `test_a_failed_portfoliosight_quote_batch_is_reported`; `test_schwab_down_a_failed_portfoliosight_batch_and_a_tripped_breaker_each_fail` |
| F8 a history got shorter and no report line says so | P2.3 | `test_the_report_shows_a_first_date_that_moved` |
| F9 a list file goes missing and the experiments gain funds | Q1.1 | `test_a_missing_core_list_stops_the_price_step_and_writes_no_list`; `test_a_missing_core_list_stops_the_eodhd_step_and_writes_no_list` |
| F10 a late fund served on day 11, or with no date | P2.9, P4.2 (BLOCKED-D3); P3.1 | `test_a_fund_is_served_for_ten_sessions_across_a_holiday_week`; `test_a_fund_four_sessions_late_stays_served_and_one_eleven_late_is_set_aside`; the as-of test of P3.1 |
| F11 a late-listed payout still shows as a drop after the next update | Q2.2; existing sync behavior | `test_a_dividend_listed_a_day_late_lowers_every_earlier_adjusted_close_and_the_date_advances`; `test_a_new_run_rewrites_only_changed_symbols_and_a_repeat_is_a_no_op` (`tests/data/test_sync_lake.py:272`) |
| F12 a rebuild changes a good history | Q2.3 | `test_a_symbol_with_a_starting_point_is_left_byte_for_byte`; `test_rebuild_with_disagreeing_values_writes_nothing` |
| F13 a fund replaced before the lake checked it | P2.3 | `test_a_fund_the_lake_does_not_vouch_keeps_bytes_and_label` |
| M1 no price history is ever deleted | P2.3; P4.2; Q2.3; Q2.4 | `test_after_any_run_the_store_holds_every_key_it_held_before`; `test_an_archive_key_is_never_overwritten`; `test_pruning_never_touches_prices_or_archive`; `test_rebuild_with_agreeing_values_replaces_and_keeps_the_old_file`; `test_load_keeps_the_rows_the_daily_job_wrote_earlier` |
| M2 no date newer than its prices; no day published without them | P4.1 (BLOCKED-D3); P3.1 | the four gate tests; the as-of test of P3.1 |
| M3 nothing requires EODHD or Tiingo | Q2.1, Q2.6; P5.1 | `test_build_gives_hand_computed_adjusted_closes_a_starting_point_and_a_vouched_date`; `test_build_only_makes_no_network_call`; the grep of P5.1 |
| M4 QSE's experiment universe never changes | Q1.1 | the three tests of Q1.1 |
| M5 no price is fetched anywhere but the laptop job | P4.2 (BLOCKED-D3); P1.4 | `test_the_run_builds_and_publishes_from_the_store_with_no_provider_and_no_network`; `test_the_walk_never_fetches_a_requested_ticker_that_has_no_record` |
| M6 yfinance prices never for a fund Schwab supplies, never unlabelled | Q2.5; P2.5 | `test_yfinance_prices_are_refused_for_a_symbol_schwab_supplies`; `test_a_fund_priced_from_the_yahoo_library_carries_the_label`; `test_an_unreadable_state_file_uploads_nothing` |
| M7 never served past the date the lake checked | P2.3 | `test_a_tiingo_fund_the_lake_vouches_is_moved_whole` (no `tr_index` after the vouched date) |
| M8 FIENX is never touched | P2.3 | `test_a_fund_the_lake_does_not_vouch_keeps_bytes_and_label` |
| M9 a starting point is replaced only for a fund the owner named | Q2.3; Q2.6 | `test_a_symbol_with_a_starting_point_is_left_byte_for_byte`; `test_rebuild_needs_named_symbols_that_exist` |
| M10 the Pushover code stays; a failed alert never stops the update | Q3.5 | `test_an_alert_makes_one_request_per_channel_that_is_set` (a Pushover request is made when its names are set); `test_a_request_that_fails_never_fails_the_run` |

## What the plan found in the spec

1. **The frozen checks contradict four parts of the spec** (decision D3 above). Spec Appendix B lists the assertions document for amendment but not the frozen tests built from it.
2. **Spec 9 gives no pull request, file or test for the owner-named yfinance price path** that spec 5 and spec 6 require. This plan puts it in Q2 task 5 (the lake) and P2 task 5 (the label).
3. **The move in spec 6 does not say what happens when the Tiingo walk writes the same record during the move.** "The walk never touches a lake entry" holds only once the entry says `lake`. P2 task 3 closes it with a conditional write.
4. **A new requested ticker could be fetched from Tiingo by the nightly walk** on the Power plan, against spec 4.1. P1 task 4 closes it. Which plan production records was not checked.
5. **WMT is already a tier 1 preset stock.** Spec 2.5 says none of the 29 is in tier 1 or tier 2. The counts of 629 and 273 are unaffected; `funds.json` has 353 entries, not 354.
6. **Spec 3.1 says the gate checks when the lake run "started"; the recorded time is when the run ended.** P4 task 1 checks that it ended after the close, which is stricter.
7. **Spec 9 says existing tests stay as they are.** Owner decision 7 (2 days) changes four QSE tests of the 4-day window, and the list above names every other pin that moves.
8. **Spec 7.3 names the count of ten Schwab failures but not whether the run stops asking.** Q3 task 3 stops, as the yfinance breaker does.
9. **The PortfolioSight Pushover sender needs a third name,** `PS_PUSHOVER_URL`, because the frozen host check allows no new host in the code. Spec 7.3 says two names.
10. **The TSP fetch cannot reuse the downloader in the evening window.** The downloader skips a fund that reaches the generation date, and in the evening that is still the day before, so the day's TSP price would not be stored. P2 task 7 writes the TSP records itself. Spec 9 (P5) says the TSP fetch keeps part of the downloader; with this design it keeps none.
11. **Not buildable before the measurement:** the load's price tolerance (no default in code), the Schwab history request that reaches furthest back, and whether Q2 task 7 exists. The evening run time is a cron line the owner installs.
