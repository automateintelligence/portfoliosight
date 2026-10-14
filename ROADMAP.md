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
  mix to the most diversified mix found, with a balanced point at the knee (this is the exact-ENB
  refinement of the surface, formerly listed as a later option); one-year ranges from
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
- Simulation engines and diversification measures, specified in
  `docs/specs/2026-10-14-portfoliosight-simulation-engines-design.md` (awaiting the owner's
  approval; no implementation plan yet). Three engines selectable in Settings behind the one
  engine function the page already calls (`portfoliosight.engine.ranges.one_year_ranges`), with
  History replay (the block bootstrap) staying the default until the others are validated by a
  rolling out-of-sample backtest on both ready-made menus. The level (mean and volatility) of
  every mix follows the selected lookback; the shape is fitted once on up to ten years per fund.
  The minimum-torsion effective number of bets was found to be inflated on correlated menus (one
  fund alone scores 3.5 to 14.4 bets on the Example Portfolio), so the spec also replaces the
  optimized measure. Phases, each with a done condition in the spec:
  0. Tag the deployed dashboard (commit, Cloudflare Worker version, KS-001 image, generation) so
     the page, the service and the data pointer can all be rolled back.
  1. Volatility model: GARCH(1,1)-t per fund with joint filtered historical simulation (whole
     residual rows resampled so funds keep moving together; long-run variance start), imported
     from the owner's QSE library at a pinned commit (`qse.distributions.joint`, QSE pull request
     #164), not ported; constant-volatility fallbacks for near-constant funds (TSP G, SGOV).
  2. Diversification measures: the diversification ratio squared as the ladders' objective
     (convex; one fund scores exactly one), and an effective number of loss contributors in each
     mix's simulated bad years, measured under the selected engine and shown in the details.
  3. Copula: a fitted vine copula with fat-tailed margins replaces the resampled shock rows
     through QSE's `ShockSource` seam, for joint bad days beyond what the history contains.
- Later product options: a TSP preset that includes the L Funds as comparison choices.

## Out of scope for the demo and parked

FERS planner (Phase 2b), risk questionnaire / risk number, hedge/collar calculator, emails,
programmatic SEO pages, payments, accounts/login, Student-t toggle, image
export, walk-forward UI, robustness score.

Holdings look-through diversification (counting the stocks and bonds behind the funds, so a
menu of near-duplicate funds is measured by what it holds): needs fund holdings data, and none of
the current sources (Tiingo, tsp.gov, the QSE lake) provides it.
