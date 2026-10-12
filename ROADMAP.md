# PortfolioSight roadmap

Seeded 2026-10-12. Items are grouped by phase; evidence and reasoning are in
`docs/reviews/`. Decisions already taken are marked (decided).

## Phase 0: spec

- Run the brainstorm on the strategy memo and write the spec (next step, decided).
- Confirm EODHD adjusted-close and dividend/split coverage for the seed universe
  (the QSE roadmap noted 403s on splits/dividends endpoints).
- Name: PortfolioSight (decided; portfoliosight.ai purchased 2026-10-12; no live or
  abandoned USPTO word marks found).

## Phase 1: engine (Python, nightly batch on a Contabo VPS)

- Data separation (decided): the PortfolioSight universe (ETFs, mutual funds, TSP funds,
  401(k) menus) is stored separately from, and supplemental to, the existing EODHD daily
  download that feeds the QSE/TFT models. Same datalake root is fine, but separate files
  and a separate refresh job, joined at read time, so nothing changes under the other models.
- Robust inputs: Ledoit-Wolf covariance (option: exponentially weighted), shrunk expected
  returns with a `--mean-shrink` dial. Selectable lookback (3/5/10 years) as tensor slices.
- Frontier plus "same risk, max return", "same return, min risk", "halfway" (min turnover)
  and per-ticker caps, carried over from the seed tool.
- Caps-first baseline: min/max allocation per option plus shrinkage. Measure whether the
  entropy layer beats caps out of sample before making it more than a display. Caps cannot
  see correlated clusters (ten tech names at 6% each is 60% in one bet); effective number
  of bets is the cluster-aware cap, which is the case for it.
- Diversification surface: for a grid of (stdev X, return Y) under the frontier, Z = max
  diversification achievable. Headline Z = effective number of bets (minimum torsion,
  not PCA). Convex proxy Z = Herfindahl of risk contributions (milliseconds, whole grid).
  Knee rule on the vertical line: Bera-Park bootstrap quantile (descend only while the
  return is statistically indistinguishable from the frontier).
- Risk ranges: 95% six-month low/mean/high per portfolio from its own mean and stdev
  (normal first, Student-t toggle later), matching the spreadsheet convention. Risk slider =
  the six-month loss floor; select the frontier point whose 2.5th percentile matches.
- Robustness score (deeper Z): bootstrap out-of-sample Sharpe shortfall per grid point,
  nightly only.
- Walk-forward evaluation mode with 1/N and inverse-vol baselines; data only up to each
  decision date; point-in-time universes via the QSE client's survivorship-free builder;
  flag short or restarted histories.
- Precomputed tensors per universe and lookback, written to R2 with hot copies in KV.
  Arbitrary universes computed on first request and cached by universe hash; rare tickers
  fetched on demand with a "give us a moment" message.

## Phase 2: free site (Cloudflare Pages/Worker + D3)

- Default view: the 2017 guide Step 2 universe and allocation; the TSP page (G/F/C/S/I + L
  funds from tsp.gov daily share prices; the G Fund has no price volatility and anchors the
  left end of the risk slider) for the NAVSEA audience.
- Risk slider and return slider (same one-dimensional frontier; trivial), allocation table
  for the current portfolio, "Diversification Optimization" toggle (the Z dial).
- Chart: frontier, current / max-return / diversified points, Z heatmap under the frontier,
  six-month 95% range graphic (the "lane"), three historical stress cards (2008, Mar 2020,
  2022).
- Themes: Light, KnowledgeSight (tokens in `ai/website`), Dark HUD.
- Plain-language layer: every technical output has a non-technical phrasing ("your money is
  really riding on about four things", "how far it could drop in a bad six months");
  technical names behind a "details" toggle.
- URL-encoded portfolios; export image; Portfolio-Visualizer-style disclaimers; generic
  CTA to the Option Spread Scanner and the AutomateIntelligence family.
- Co-marketing: TSPtalk.com, NAVSEA friends, AutomateIntelligence.ai.

## Phase 2b: FERS pension planner (same audience, same site)

- Source: `C:\Users\jeffr\Programming\Python\FERS\Ingage_Web_Apps\FERS_pension_app.py`
  (Flask, ~1,130 lines, own git repo at `Programming/Python/FERS`). Inputs: start/retirement
  ages, life expectancy, years of service, high-three salary, inflation, discount and
  investment rates, salary growth, pay-band cap; VERA option and a job-comparison mode;
  matplotlib plots rendered to base64. Companion scripts compute the optimal FERS
  retirement age by bisection/optimization, including a VERA variant.
- State: last commits (2025) say "still not working correctly"; the VERA calculation has an
  age-vector length mismatch (33 vs 32) at the equivalent-annual-investments plot.
- Work to make it public: fix the VERA vector bug; move the math into a pure function
  module with tests; replace Flask-rendered PNGs with the same D3 components and themes as
  the portfolio page; plain-language labels; disclaimers; feed its retirement balance and
  horizon into the portfolio page's defaults (the two tools share the NAVSEA/TSP user).

## Phase 3: paid tier and bridges

- Risk questionnaire (own wording, not Nitrogen's) with periodic reallocation emails
  ("still in your lane?").
- "Protect this portfolio" collar/put calculator and covered-call overlay as the bridge to
  the Option Spread Scanner.
- Programmatic pages per 401(k) provider and per fund set; "Beyond TSP" premium; charge for
  entering your own investment choices once demand is judged (default Step 2 and TSP pages
  stay free).
- Broker affiliate links at the save/share step; white-label embed for small advisory firms.

## Parked / maybe

- ML surrogate for the robustness score (regress bootstrap shortfall on cheap features).
  Not needed for ENB itself: with the torsion matrix cached per universe, exact ENB for any
  weight vector is two matrix-vector products and runs in microseconds client-side.
- Copula Monte Carlo (skfolio VineCopula) and sequential entropy pooling for views and
  stress tests.
- Tier-3 methods judged not worth it at this scale: NCO, Michaud resampling, end-to-end
  deep learning, HMM regime switching.
