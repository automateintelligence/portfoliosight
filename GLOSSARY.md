# PortfolioSight

PortfolioSight shows long-only investment mixes at a chosen level of risk, and the range of
one-year outcomes each mix could have. These are the terms used for how those ranges are
simulated.

**Mix**:
How money is split across the funds of a menu, as a weight per fund. "Your starting mix" is the
one the user entered.
_Also called_: allocation (the same thing)

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

## Diversification

**Effective number of bets (ENB)**:
How many independent bets a mix's risk is spread over: the exponential of the entropy of each
uncorrelated bet's share of the risk (minimum torsion). The app's diversification measure, so
"maximum entropy" and "maximum ENB" are the same thing.
_Avoid_: maximum entropy (as a separate method), number of holdings

**Diversification ratio**:
The risk a mix's holdings would have if they all moved together, divided by the risk they have
together (squared in the experiment). A research measure, never shipped; it credits volatile
holdings that offset one another and gives a near-riskless fund almost no credit.
_Avoid_: MDR, diversification (unqualified)

**Optimized point**:
The mix at a fixed risk where each further step toward more diversification starts buying less
diversification than the return it gives up.
_Avoid_: best mix, balanced mix
