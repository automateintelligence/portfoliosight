# PortfolioSight

Free portfolio risk/return tool for AutomateIntelligence.ai. Enter the funds you can
choose from (a 401(k) menu, the TSP funds, a brokerage account), see where your current
mix sits against the efficient frontier, drag a risk slider, and get a better-diversified
mix at the same risk. Domain: portfoliosight.ai. A FERS pension planner for the same
federal-employee audience is planned alongside it (see ROADMAP.md, Phase 2b).

Status: greenfield, seeded 2026-10-12 from the research tool
`efficient_frontier_portfolio.py` (Windows `Programming/Python/Finance`). Prior work is
advisory only.

## Layout

```
portfoliosight/        Python engine package (frontier, diversification surface, risk ranges)
  frontier_cli.py      the seed: the Oct 2026 research tool, unchanged (run-tracking, caps, halfway)
data/holdings/         example holdings files (personal IRAs, 2017 guide Step 2 universe)
docs/reviews/          strategy memo, six research reports, decision addendum (2026-10-12)
docs/plans/            specs and plans (next: brainstorm -> spec)
runs/                  iteration outputs from the research tool (run_log.csv is the index)
web/                   Cloudflare Worker + D3 front end (empty until the spec exists)
```

## Engine quick start

```
uv venv && source .venv/bin/activate
uv pip install -e .
python -m portfoliosight.frontier_cli --holdings data/holdings/holdings_2026-10.csv --label baseline
python -m portfoliosight.frontier_cli --holdings data/holdings/holdings_guide2017_step2.csv \
       --label guide2017 --cap-alloc 0.25
```

Outputs land in `runs/rNNN_<label>/` and a row is appended to `runs/run_log.csv`.
Prices are cached per date window in `runs/_cache/`. The seed uses yfinance for
research only; the product must use the EODHD corpus (see Data).

## Data

The QSE daily pipeline (`~/programming/quant-scenario-engine/scripts/daily_pipeline.py`)
uses two sources, and PortfolioSight should use both the same way:

- **EODHD** is the bulk historical corpus. `python -m qse.experimental.tft.cli
  download-raw-eodhd --output-dir <dir> --symbols-file <universe.txt> --start 1995-01-01`
  writes per-symbol parquet under `eod_history/`, `dividends/`, `splits/` (plus
  fundamentals, calendars, news). The existing universe is
  `data/tft/raw/eodhd/universes/datalake_us_core.txt` (1,038 symbols, 13 of the ETFs we need
  already present: AGG BND IEF LQD QQQ SCHP SGOV SPY TLT VCIT VEA VTI VWO) and lands in
  `data/tft/raw/eodhd/datalake_us_core/` (symlinked to `/mnt/d/tft-quantile-forecaster/...`).
  Client: `qse/experimental/tft/data/eodhd_client.py` (`get_eod` with adjusted close,
  `get_dividends`, `get_splits`, `get_bulk_eod`, `build_survivorship_free_universe`).
  This is the only source with dividends and adjustments, so it is the source for
  **total returns**, which matter most for bond ETFs (SGOV is +3.8%/yr total vs +0.1% price).
- **Schwab** (`qse/data/schwab.py`, `SchwabDataSource.fetch_ohlcv`, via `schwabdev`; OAuth
  tokens in `.schwab/tokens.json`, refreshed Sundays on the laptop) returns open, high, low,
  close and volume only: unadjusted, no dividends. Use it for quotes, option chains and
  price-only history (also works for ETFs), not for total-return estimation.
  `qse.data.factory.get_data_source("schwab", fallback="yfinance")` and
  `qse.data.data_loader.DataLoader` give cached access.
- **Keep the PortfolioSight universe separate and supplemental (decided).** Add
  `universes/portfoliosight.txt` (ETFs, mutual funds, 401(k) menu funds) and run the same
  downloader into `datalake_portfoliosight/` on its own schedule. Join with the core datalake
  at read time. Nothing in the existing download or universe file changes.
- Compute total returns from raw closes plus the dividend and split records so cached
  histories do not drift when EODHD back-adjusts. Confirm EODHD fund coverage (mutual funds
  such as VTSAX, FXAIX) and the splits/dividends endpoints, which the QSE roadmap noted
  returning 403.
- TSP funds (G, F, C, S, I and the L funds) have no tickers; tsp.gov publishes daily share
  prices for every fund, which is the source for the TSP page.
- yfinance is personal-use only and must not be used by the site.

## Reading order

1. `docs/reviews/2026-10-12_strategy_memo_portfolio_risk_return_website.md`
2. `docs/reviews/2026-10-12_addendum_user_feedback_and_decisions.md`
3. `ROADMAP.md`
4. The six research reports in `docs/reviews/`
