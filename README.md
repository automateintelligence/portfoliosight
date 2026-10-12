# PortfolioSight

Free portfolio risk/return tool for AutomateIntelligence.ai. Enter the funds you can
choose from (a 401(k) menu, the TSP funds, a brokerage account), see where your current
mix sits against the efficient frontier, drag a risk slider, and get a better-diversified
mix at the same risk. Domain: portfoliosight.ai.

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

- Production prices come from the EODHD datalake at
  `/mnt/d/tft-quantile-forecaster/data/tft/raw/eodhd/datalake_us_core/` via the cached client in
  `~/programming/quant-scenario-engine/qse/experimental/tft/data/eodhd_client.py`.
  The corpus stores raw and adjusted series; compute total returns from raw closes plus
  dividend and split records so cached histories do not drift when EODHD back-adjusts.
- TSP funds (G, F, C, S, I and the L funds) have no tickers; tsp.gov publishes daily
  share prices for every fund, which is the source to use for the TSP page.
- yfinance is personal-use only and must not be used by the site.

## Reading order

1. `docs/reviews/2026-10-12_strategy_memo_portfolio_risk_return_website.md`
2. `docs/reviews/2026-10-12_addendum_user_feedback_and_decisions.md`
3. `ROADMAP.md`
4. The six research reports in `docs/reviews/`
