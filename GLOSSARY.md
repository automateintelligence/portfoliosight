# PortfolioSight

PortfolioSight shows long-only investment mixes at a chosen level of risk, and the range of
one-year outcomes each mix could have. These are the terms used for how those ranges are
simulated.

## Simulation

**Lookback**:
The recent window of history that sets the level of every simulated year: 3 years by default,
5 as a sensitivity.
_Avoid_: training window (for the level)

**Level**:
The average return and volatility that each simulated year is scaled to, taken from the lookback.
_Avoid_: shape, scale

**Dynamics window**:
The recent window a fund's GARCH model is fitted on, which decides how its volatility clusters
and decays: 10 years, or 3 years when 10 does not fit.
_Avoid_: shape window, fit window, training window

**Shock pool**:
The days a simulation draws its shocks from: each day's returns divided by that day's estimated
volatility. It starts at the menu's youngest fund's first price and keeps every crisis since.
_Avoid_: residual pool, shape

**Constant-volatility fallback**:
A fund simulated without GARCH dynamics because its model would not fit on either dynamics
window. It still draws from the shock pool.
_Avoid_: fit failure (for a fund that is still simulated)
