# PortfolioSight roadmap

The demo described in `docs/specs/2026-10-13-portfoliosight-demo-design.md` is built. This file
lists what shipped and what is deliberately left for later. Evidence and reasoning for the
method are in `docs/reviews/`.

## Shipped (demo)

- One screen: a frontier of best-return mixes over a map of how spread out each mix is, one risk
  slider with a bad and a typical year, one diversification slider that starts at a suggested
  position, and a quiet Good / Average / Fair / Poor word. Technical names sit behind a details
  toggle.
- Two ready-made menus, the Example Portfolio (the default, with its allocation) and TSP
  (G, F, C, S, I), plus custom menus of 2 to 30 served funds built on request and cached by
  menu, limits and lookback.
- Funds and amounts in shares, percent or dollars; trades from the entered mix to the selected
  one; stress cards for 2008, March 2020 and 2022 that never show a number for a mix that mostly
  did not exist; per-fund limits that scale with the size of the menu; six lookbacks with faint
  overlays.
- Four looks (KnowledgeSight dark, Light, HUD, Grid), a phone layout, an address that always describes
  the view, and a share dialog that copies the link or emails a fixed message.
- Engine: shrunk returns, Ledoit-Wolf covariance, long-only frontier with caps (and the uncapped
  frontier for reference), effective number of bets by minimum torsion; at every risk level a
  ladder of mixes that hold that risk and trade return for the exact measure, from the frontier
  mix to the most diversified mix found, with a balanced point at the knee; one-year ranges from
  a stationary block bootstrap of the menu's own history; a precomputed tensor per menu and
  lookback; the browser interpolates computed mixes and recomputes every statistic, and asks the
  service for the range of any other mix.
- Data: Tiingo and tsp.gov behind one provider Protocol, R2 as the canonical store with a laptop
  backup, a nightly refresh on KS-001 inside the measured request budget.
- Front door: a Cloudflare Worker, Cloudflare's own human check, and a private-preview gate that
  stays on until the commercial data license is bought.
- A frozen done-gate of 68 machine assertions and one production smoke test per definition of
  done.

## Next

- Tester access: a SecuritySight-style login (authorized email domains, one-time code, 30-day
  session) replaces the private-preview link when testers are invited.
- Paid tier: more than 30 funds per portfolio, and tickers outside the served universe fetched on
  demand, behind a small annual paywall.
- Data license and tier 3: confirm or upgrade the Tiingo plan (Power or internal-commercial) and
  obtain written storage/display terms before marketing the site; on a Power-class plan the
  nightly job serves all of tier 3 without code changes. A second price provider (EODHD if its
  plan gains prices) is one adapter behind the existing Protocol.
- One-year range, in two steps, each behind the one engine function the page already calls
  (`portfoliosight.engine.ranges.one_year_ranges`), so neither step changes page code:
  1. Filtered historical simulation, replacing the block bootstrap in the next engine batch. Fit
     GARCH(1,1) with Student-t errors per fund (the pattern of the owner's QSE distribution
     fitters, ported with the `arch` library, not imported), standardize each fund's history by
     its fitted volatility, resample whole cross-sectional rows of standardized shocks so funds
     keep moving together, and re-inflate with simulated volatility started from the long-run
     variance (not today's), vectorized. The level is tied to the selected lookback: each mix's
     simulated mean and volatility are scaled to the chart's expected return and risk for that
     lookback. The shape (tail fatness, volatility persistence, co-movement of shocks) is fitted
     on the longest history held per fund, up to ten years, and is the same for every lookback.
     Near-constant funds (TSP G, SGOV) need a fallback when GARCH does not fit.
  2. Copula simulation: replace the resampled shock rows of step 1 with a fitted copula (vine
     copula, fat-tailed margins) for tail dependence beyond what history contains.
- Later product options: a TSP preset that includes the L Funds as comparison choices.

## Out of scope for the demo and parked

FERS planner (Phase 2b), risk questionnaire / risk number, hedge/collar calculator, emails,
programmatic SEO pages, payments, accounts/login, Student-t toggle, image
export, walk-forward UI, robustness score.
