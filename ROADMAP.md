# PortfolioSight roadmap

The demo described in `docs/specs/2026-10-13-portfoliosight-demo-design.md` is built. This file
lists what shipped and what is deliberately left for later. Evidence and reasoning for the
method are in `docs/reviews/`.

## Shipped (demo)

- One screen: a frontier of best-return mixes over a map of how spread out each mix is, one risk
  slider with a bad and a typical six months, one diversification slider that starts at a
  suggested position, and a quiet Good / Average / Fair / Poor word. Technical names sit behind
  a details toggle.
- Two ready-made menus, the Example Portfolio (the default, with its allocation) and TSP
  (G, F, C, S, I), plus custom menus of 2 to 30 served funds built on request and cached by
  menu, limits and lookback.
- Funds and amounts in shares, percent or dollars; trades from the entered mix to the selected
  one; stress cards for 2008, March 2020 and 2022 that never show a number for a mix that mostly
  did not exist; per-fund limits that scale with the size of the menu; six lookbacks with faint
  overlays.
- Three looks (KnowledgeSight dark, Light, HUD), a phone layout, an address that always describes
  the view, and a share dialog that copies the link or emails a fixed message.
- Engine: shrunk returns, Ledoit-Wolf covariance, long-only frontier with caps, effective number
  of bets by minimum torsion, a precomputed tensor per menu and lookback; the browser interpolates
  computed mixes and recomputes every statistic.
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
- Later product options: a TSP preset that includes the L Funds as comparison choices; an
  exact-ENB (non-convex) refinement of the surface.

## Out of scope for the demo and parked

FERS planner (Phase 2b), risk questionnaire / risk number, hedge/collar calculator, emails,
programmatic SEO pages, payments, accounts/login, copula Monte Carlo, Student-t toggle, image
export, walk-forward UI, robustness score.
