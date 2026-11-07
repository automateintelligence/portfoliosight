# ADR 0005 — GARCH is fitted on a recent dynamics window; shocks come from the full history

Status: **Draft, contingent** on the fixed-risk experiment (protocol v2 §11, Amendment 1) and the
product decision that follows it. Date: 2026-10-24. Owner: Jeff Daniels. Drafted by Claude at the
owner's direction, after a grilling session. Terms are defined in `GLOSSARY.md`.

## Context

The simulation exists to show the range of outcomes a mix could have, including crashes. It is
not a price forecast. A GARCH(1,1)-t fitted on a short calm window leaves every crisis out of its
shocks and estimates thin tails. Fitting it on all of a fund's history (back to 1995 for some
holdings) does not work either. Volatility shifts level across decades: Citigroup's 3-year
volatility ranges from 0.14 to 1.00. One GARCH(1,1) can only match those shifts by making shocks
permanent, so persistence lands on 1, and on the research menu 53 of 62 origins had a fund at that
limit. The simulation engines spec (§4.3) fits on up to ten years and draws shocks from that same
window.

## Decision (contingent)

Separate the two jobs a single fit window was doing:

- **Dynamics window.** Each fund's GARCH is fitted on its last 10 years, or 3 years if 10 does not
  fit. If neither fits, the fund gets the labelled constant-volatility fallback.
- **Shock pool.** Shocks are drawn from every day on which all of the menu's funds have a return,
  from the youngest fund's first price up to the origin, weighted equally. Each day is standardized
  by running the fitted model forward over the whole pool.
- **Level.** The average return and volatility of each simulated year come from the lookback
  (3 years; 5 as a sensitivity). The dynamics window and the shock pool do not change with the
  lookback.

This is filtered historical simulation with a pool longer than the fit. In spirit it is close to
clearing-house margin rules, which keep stress periods in the sample. It is not the Basel
"stressed VaR", which adds two separate figures.

## Considered options

- **Full history for both the fit and the pool:** spurious integrated GARCH, as above.
- **Step down from full history to 10 then 3 years:** most funds end on 3 years, and calm pools come
  back.
- **A GARCH whose long-run level drifts (spline-GARCH):** the right model for level shifts, but not
  in QSE; days of work.
- **Extra weight on crisis days (a stress floor):** deferred as a product question.

## Consequences

- Origins before late 2008 have no crisis in their pool, because the pool cannot use days after the
  origin. The 2000–2002 crash is never in a shared pool, because the youngest funds (EEM, the
  TSP funds) start in 2003.
- Older shocks are standardized with recent parameters. This approximation is chosen on purpose.
- The compute cost is negligible. The extra 3-year fit runs only on failure, and filtering the pool
  is a linear pass. The simulation draws 2,000 × 252 days whatever the pool size.
- A separate QSE fix is owed. A fit at persistence 1 is labelled "fit failed" instead of
  "non-stationary". It changes labels only, not results.
