# Fixed-risk experiment v2: final report

Date: 2026-11-07. Run: `fr-run-v2b` (four jobs: research2003 and TSP, each under history replay and
GARCH). Protocol: [v2 protocol](../plans/2026-10-21-fixed-risk-optimization-experiment-protocol.md),
revision 6 with Amendment 1. Tables are copied from the generated report
(`portfoliosight/research/fixedrisk/report.py`); numbers are unchanged, headers and some labels are
renamed to the names used in `GLOSSARY.md` and in this report.

> **GARCH results superseded.** After this run, GARCH simulations were found to explode at some
> origins, so every GARCH figure below is superseded (section 2). History-replay results are
> unaffected and carry the conclusions.

## 1. Summary for the owner

**Your question.** At a fixed risk, can stepping down from the frontier mix (the mix with the
highest expected return at that risk) toward a more diversified mix give a slightly lower return
with a lower drawdown?

**Answer: no, not in v2.**

- Stepping along the diversification-ratio slider worsened the model's and the realized bad year
  and drawdown on both menus. That is how the v2 results were read with the owner on 2026-11-04
  (v3 protocol, section 0). This report's own "Line shape" tables are less uniform: on research2003
  the realized slopes change sign across risk levels and their intervals include zero. The clear
  case is TSP under history replay at risk levels 0.55, 0.7 and 0.85, where a longer step along the
  slider meant a deeper drawdown and a lower return (at 0.85: drawdown +0.68 pp [+0.19, +1.17],
  return -1.44 pp [-2.42, -0.47], per unit of slider position).
- The U1 mix sat near the frontier mix. On research2003 under history replay its median slider
  position was 0.00 to 0.07 across the six risk levels (0 is the frontier mix's diversification
  ratio, 1 is the most diversified mix at that risk). Under GARCH (superseded) it was 0.01 to 0.08.
- On research2003 under history replay, the U1 mix beat the frontier mix in the simulation
  (U1 gain +24.5 bp, 95% interval +10.5 to +39.5) but not in realized history. The realized return
  gain was -46.8 bp (99% interval -92.1 to -0.5), the realized return guardrail failed at five of
  the six risk levels (all but 0.1), and the realized drawdown was 0.32 pp smaller.

| Menu | Engine | Verdict on the primary test | Why |
|---|---|---|---|
| research2003 | History replay | Not supported | A realized guardrail is breached |
| research2003 | GARCH (superseded) | Not supported | Model criterion not met |
| TSP | History replay | Inconclusive | The U1 gain changes sign in the narrow risk band (tolerance 0.001) |
| TSP | GARCH (superseded) | Not supported | Model criterion not met |

The primary test: at a fixed risk level, does the U1 mix found by free search (any slider
position) beat the frontier mix? (The protocol calls it the white-line test.)

**v2 did not test what the app ships.** The app's diversification measure is the effective number
of bets (ENB), not the diversification ratio the slider used here. v2 therefore says nothing about
whether the shipped method helps. v3 tests it.

**What the realized numbers rest on.** 19 disjoint annual intervals on research2003 and 18 on TSP.
The protocol asks for 200 before claiming a real-world tail benefit, so realized support was "not
attainable" and realized bad-year comparisons are underpowered.

**How to read the numbers.**

- Risk level: six levels, 0.1, 0.25, 0.4, 0.55, 0.7, 0.85. Each is a fraction of the way from the
  lowest-risk mix (0) to the risk of the highest-return mix (1). Tables with a "Risk level" column
  show one row per level. Tables titled "six risk levels pooled" average over all six.
- Slider position: 0 is the frontier mix's diversification ratio, 1 is the most diversified mix at
  that risk level. "Free search" ignores the slider and looks at every mix at that risk level.
- **U1** = 0.6 x bad-year + 0.3 x typical + 0.1 x good-year percentile of 2,000 simulated one-year
  returns. Bad, typical and good year are the 2.5th, 50th and 97.5th percentiles. The U1 mix is
  the mix with the highest U1 at a risk level.

## 2. GARCH results superseded

After the run, GARCH simulations were found to explode at some origins: research2003 at 2010-08 and
2011-01 gave simulated means of 100x or more (the U1 mix's simulated mean was 128 and 208 times the
stake, ADR 0006). The cause was near-integrated GARCH fits (persistence 0.997 to 0.999 for C, IYR
and SPY) whose simulated variance ran away on a few paths, and levelling then turned those paths
into huge simple returns. ADR 0006 caps each fund's simulated volatility at 3 times its lookback
volatility. With the cap, the U1 mean is +5.0% at 2010-08 and +8.4% at 2011-01, but the simulated
ranges widen, because levelling rescales once the runaway paths are gone: at 2011-01 the U1 mix's
97.5th percentile goes from +32% to +104%, while at 2006-06 and 2016-06 the percentiles move by at
most 1.5 points (ADR 0006).

So every v2 GARCH figure in this report is superseded, not just those two months: the selections
were made on the uncapped banks and do not carry over. GARCH paths also start each year at the
model's long-run volatility, which can sit far above a calm fund's recent volatility (IWD at
2016-06: about 3.7x the lookback variance all year in the median, even with the cap); this is
deferred and tracked in https://github.com/automateintelligence/portfoliosight/issues/189.

History-replay results are unaffected and carry the v2 conclusions. The GARCH reruns are deferred:
experiment v3 runs first, with history replay as its primary engine. Blocks and sections below that
come from GARCH are marked "superseded".

## 3. Names and method

Names used throughout (terms follow `GLOSSARY.md`):

| Name | Meaning |
|---|---|
| Frontier mix | The mix with the highest expected return at a risk level (today's choice). |
| U1 mix | The mix with the highest U1 at a risk level (U1 defined in section 1). |
| max-Bad mix | The mix with the best simulated bad year at a risk level. |
| Bayes-Stein frontier mix | The frontier mix on a shrunk expected return; a second comparison, reported only. |
| Risk level | Position between the lowest-risk mix (0) and the highest-return mix (1); see section 1. |
| Slider position | Where a mix sits between the frontier mix (0) and the most diversified mix (1) at that risk level. |
| Diversification ratio | The measure behind the slider (squared); a research measure, never shipped. |
| Effective number of bets (ENB) | The app's diversification measure; not tested in v2. |
| Bad, typical, good year | The 2.5th, 50th and 97.5th percentiles of the simulated (or realized) one-year returns. |
| Lookback | The 3-year window that sets the level of every simulated year. |

Method, in short:

- **Menus.** research2003: 19 holdings, 11 funds plus 8 stocks (GE, MSFT, XOM, PFE, C, WMT, AIG,
  INTC; the US companies in the 2004 global top ten), at most 40% per fund and 10% per stock;
  first origin 2006-04, 246 origins, 234 with a complete realized year. TSP: 5 funds; first origin
  2006-06, 244 origins, 231 with a complete realized year.
- **Search.** At each menu, monthly origin and risk level, five searches (U1, three other U
  weightings U2 to U4, and max-Bad) run in four slider cells (positions 0.25, 0.50, 0.75, and free
  search) on a bank of 2,000 simulated one-year paths. The mix with the best score is locked, then
  scored on independent banks.
- **Engines.** History replay resamples real days from the 3-year lookback. GARCH is superseded
  (section 2).
- **Realized outcomes.** The locked mix is held for the next year, rebalanced to target monthly;
  intervals come from a block bootstrap over origins. Realized support needs a 25 bp gain or a 1 pp
  drawdown improvement with a 99% lower bound above zero, on at least 20 disjoint annual intervals;
  below 20 the criterion is "not attainable".
- **Primary test pass conditions.** U1 gain of at least 5 bp with at least 4 of 5 banks positive;
  the narrow-band check agrees in sign; the realized guardrails hold (median and mean annual-return
  loss up to 25 bp, loss frequency up to +5 pp, mean drawdown worsening up to 1 pp); realized
  support.
- **Run settings.** The CPU-hour total was raised from 240 to 760. research2003 replay was resumed
  with a 300 CPU-hour budget after its 165 CPU-hour stop, because a throttled local VM inflated the
  CPU time it counted. Local runs used 10 workers, not the ceiling's 6.

Jobs and selections by kind (source: the run's job manifests):

| Kind | research2003 / history replay | research2003 / GARCH | tsp / history replay | tsp / GARCH |
|---|---|---|---|---|
| comparator | 2952 | 2952 | 2928 | 2928 |
| main | 36900 | 36900 | 36600 | 36600 |
| sens_5y | 810 | 810 | 810 | 810 |
| sens_endpoints | 144 | 144 | 144 | 144 |
| sens_tau | 972 | 972 | 972 | 972 |
| showcase | 6048 | 6048 | 6048 | 6048 |
| stability | 7440 | 7440 | 7320 | 7320 |

## 4. Caveats

- **Retrospective menu.** The 19-holding research menu and its eight stocks (the US companies in the
  2004 global top ten) are a research choice made with hindsight about which firms existed in 2004;
  one dated ranking is not a point-in-time membership history, the 10% cap limits direct
  concentration but not survivorship, and the equity ETFs hold the same issuers.
- **VIPSX idealized convention.** Weights are set from data through the origin close and returns are
  earned from the next session, frictionless except for the cost variant. A mutual fund priced at
  its own close cannot be traded at the origin's value, and VIPSX is an actively managed fund, not a
  price-history extension of TIP.
- **Host confounding.** The TSP jobs ran on KS-002 and the research jobs on the WSL laptop, so the
  host is confounded with the menu, not the engine. Across hosts, last-bit differences can change
  path ranks and a nonconvex solver's end point.
- **GARCH is not a production qualification.** Per protocol Amendment 1 and ADR 0005, each fund's
  GARCH dynamics were fitted on a 10-year window (falling back to 3 years, then to constant
  volatility); the shock pool spans the full common history; the level comes from the 3-year
  lookback. The realized convention differs from the spec's, and the spec's 6.4/6.5 validation stays
  owed. All GARCH figures are in any case superseded (section 2).
- **Tail underpower.** Realized 2.5% quantiles rest on a handful of distinct bad years; with fewer
  than 200 disjoint annual intervals a confirmed real-world tail benefit cannot be claimed. Monthly
  cohorts overlap heavily, and menus, risk levels and cells share outcomes; none of them is an
  independent historical replication.
- **Same band is not same risk.** Mixes inside one risk band can differ by up to 2% of the risk
  level in volatility; the risk difference is reported beside every U1 gain.
- **Higher U1 is not lower downside.** The bad-year change, the worst-2.5% average change and the
  drawdown are shown beside the U1 gain; no equivalence claim is made.
- **Deflated Sharpe ratio and PBO.** The deflated Sharpe ratio (DSR) is a modified, ungated
  diagnostic on about twenty annual observations with little power; it cannot account for the
  choices made across the protocol's revisions (menus, arms, tolerances). The purged adaptation of
  combinatorially symmetric cross-validation (CSCV) has unequal sides and dropped splits change the
  sampling scheme; with four candidates the probability of backtest overfitting (PBO) takes only the
  values 0.2 to 0.8 per split and is read with the per-triple distributions.

## 5. Results

How to read the tables:

- **Primary test table.** Each figure is the U1 mix minus the comparison mix, pooled over the six
  risk levels. "U1 gain" is on the simulation's own U1 score, in basis points (bp). "Bad-year
  change" and "worst-2.5% average change" are the simulated bad year and the average of the worst
  2.5% of simulated years. "Realized gain" is the realized annual return and "realized drawdown
  improvement" a smaller drawdown (positive is better for the U1 mix). "Banks positive" counts the
  independent banks on which the U1 gain is positive.
- **Guardrail table.** One row per risk level; "guardrail holds" is "NO" when a limit in section 3
  is exceeded.
- **Where the U1 mix sits.** Slider position of the free-search U1 mix across origins, per risk
  level. Below 0 is less diversified than the frontier mix; above 1 is more diversified than the
  most diversified mix found, and "anchor regret" measures by how much ("n/a" means it never
  happened). "Replaced by an interior search" is the share of origins where a mix found by a search
  at slider position 0.25, 0.50 or 0.75 scored higher and replaced the free search's own result.
- **Line shape.** The slope of a realized statistic against slider position (0.25, 0.50, 0.75),
  per risk level, with a 95% block-bootstrap interval. Positive drawdown slope means more
  diversification, deeper drawdown.

### 5.1 Menu research2003 (19 holdings)

Collapsed share of risk lines: 0.0% at each of the six risk levels (246 lines per risk level; overall 0.0%). Showcase surfaces: 324 columns, collapsed share 0.0%.

#### History replay

##### Primary test: U1 mix vs frontier mix

**Primary test (U1 mix by free search vs frontier mix): not supported** - a realized guardrail is breached.

Realized support: not attainable; disjoint annual intervals: 19 (tail adequacy needs 200; realized tails are underpowered).

| Comparator | Pairs (origin x risk level) | U1 gain, bp (95% interval) | Banks positive | Bad-year change, bp | Worst-2.5% average change, bp | Risk difference, bp | Realized gain, bp (99% interval) | Realized drawdown improvement, pp |
|---|---|---|---|---|---|---|---|---|
| Frontier mix (the test) | 1476 | +24.5 [+10.5, +39.5] | 5/5 | +100.1 | +122.3 | -17.5 | -46.8 [-92.1, -0.5] | +0.32 |
| Bayes-Stein frontier mix (reported only) | 1476 | +26.8 [+15.7, +38.1] | 5/5 | +99.8 | +120.2 | -16.0 | -37.0 [-83.8, +13.8] | +0.37 |

Narrow-band check (risk tolerance 0.1% instead of 1%) on 6 origins: U1 gain +7.6 bp in the main run, +0.5 bp in the narrow band, signs agree.

Realized guardrails by risk level (U1 mix minus frontier mix, monthly rebalancing; a positive loss is worse):

| Risk level | Origins | Median return loss, bp | Mean return loss, bp | Loss frequency change, pp | Drawdown worsening, pp | Guardrail holds |
|---|---|---|---|---|---|---|
| 0.1 | 234 | +8.7 | +18.9 | -0.85 | -0.27 | yes |
| 0.25 | 234 | +44.4 | +27.8 | +0.00 | -0.48 | NO |
| 0.4 | 234 | +121.7 | +88.7 | +1.71 | -0.33 | NO |
| 0.55 | 234 | +39.0 | +64.3 | +0.43 | -0.28 | NO |
| 0.7 | 234 | -6.1 | +32.1 | -2.14 | -0.22 | NO |
| 0.85 | 234 | +5.4 | +48.9 | -0.43 | -0.31 | NO |

##### Where the U1 mix sits on the slider

| Risk level | Origins | Undefined (collapsed line) | Position p10 | Position p50 (median) | Position p90 | Share below 0 | Share above 1 | Share at 0.25 or more | Anchor regret (mean, position above 1) | Replaced by an interior search |
|---|---|---|---|---|---|---|---|---|---|---|
| 0.1 | 246 | 0 | -0.14 | 0.00 | 0.24 | 45.5% | 0.0% | 8.1% | n/a | 79.7% |
| 0.25 | 246 | 0 | -0.29 | 0.00 | 0.24 | 47.6% | 0.0% | 9.8% | n/a | 77.6% |
| 0.4 | 246 | 0 | -0.22 | 0.02 | 0.24 | 42.7% | 0.0% | 8.5% | n/a | 75.2% |
| 0.55 | 246 | 0 | -0.25 | 0.02 | 0.23 | 41.5% | 0.0% | 6.1% | n/a | 73.6% |
| 0.7 | 246 | 0 | -0.15 | 0.04 | 0.25 | 31.3% | 0.0% | 8.5% | n/a | 75.2% |
| 0.85 | 246 | 0 | -0.11 | 0.07 | 0.25 | 27.2% | 0.0% | 9.8% | n/a | 72.4% |

##### Max-Bad mix vs U1 mix (free search)

| Risk level | Realized bad year: max-Bad mix | Realized bad year: U1 mix | Mean drawdown: max-Bad mix | Mean drawdown: U1 mix | Mean return: max-Bad mix | Mean return: U1 mix |
|---|---|---|---|---|---|---|
| 0.1 | -7.6% | -8.6% | 4.2% | 4.4% | 4.8% | 4.8% |
| 0.25 | -14.5% | -14.7% | 6.4% | 6.6% | 5.5% | 5.9% |
| 0.4 | -20.1% | -20.1% | 8.6% | 8.7% | 6.2% | 6.3% |
| 0.55 | -19.9% | -19.4% | 10.4% | 10.3% | 7.2% | 7.5% |
| 0.7 | -22.4% | -22.6% | 12.2% | 12.1% | 8.0% | 8.5% |
| 0.85 | -31.5% | -31.2% | 14.0% | 14.0% | 8.4% | 8.6% |

Realized return, max-Bad mix minus U1 mix (six risk levels pooled): -0.26 pp [-0.53, -0.03].

Realized drawdown, max-Bad mix minus U1 mix (six risk levels pooled): -0.06 pp [-0.19, +0.09].

Simulated bad-year change +17.3 bp, worst-2.5% average change +25.1 bp (independent banks, max-Bad mix minus U1 mix, six risk levels pooled).

##### Line shape: U1 mix at slider positions 0.25, 0.50, 0.75

| Risk level | Common origins | Slope per unit of slider position: realized bad year, pp | Slope: mean drawdown, pp | Slope: mean return, pp |
|---|---|---|---|---|
| 0.1 | 234 | -4.39 [-11.26, +1.36] | +0.42 [-0.22, +1.21] | -0.39 [-1.15, +0.35] |
| 0.25 | 234 | +0.65 [-4.14, +2.78] | -0.14 [-0.76, +0.52] | +0.21 [-0.81, +1.28] |
| 0.4 | 234 | -2.58 [-9.92, +3.62] | -0.26 [-1.09, +0.66] | +0.21 [-1.05, +1.34] |
| 0.55 | 234 | -1.58 [-6.48, +3.91] | +0.20 [-0.72, +1.21] | -0.14 [-1.33, +1.07] |
| 0.7 | 234 | -2.11 [-6.26, +3.32] | +0.19 [-0.69, +1.03] | -0.13 [-1.38, +1.15] |
| 0.85 | 234 | +3.55 [-3.71, +8.57] | +0.09 [-0.63, +0.86] | +0.18 [-1.84, +2.34] |

##### Realized extras

**Multi-year and real returns (U1 mix by free search and frontier mix, monthly rebalancing, six risk levels pooled; descriptive)**

| Horizon | Rows | Origins | U1 mix mean | Frontier mix mean | Difference, pp |
|---|---|---|---|---|---|
| 1y | 1404 | 234 | 7.0% | 7.4% | -0.47 |
| 3y | 1260 | 210 | 21.9% | 23.6% | -1.69 |
| 5y | 1116 | 186 | 37.8% | 38.8% | -0.98 |
| 1y real | 1392 | 232 | 4.2% | 4.7% | -0.46 |
| 3y real | 1248 | 208 | 13.2% | 14.7% | -1.56 |
| 5y real | 1104 | 184 | 22.0% | 22.7% | -0.78 |

**Cost variant (10 bp of one-way turnover, funding included; six risk levels pooled)**

|  | Gross | Net |
|---|---|---|
| U1 mix mean return |  | 6.8% |
| Frontier mix mean return |  | 7.3% |
| U1 mix minus frontier mix, pp | -0.47 | -0.47 |
| Mean rebalance turnover (U1 mix / frontier mix) |  | 0.15 / 0.14 |

**Regime buckets (U1 mix minus frontier mix, monthly rebalancing, six risk levels pooled)**

| Regime | Origins | Return difference, pp | Drawdown difference, pp | U1 mix mean | Frontier mix mean |
|---|---|---|---|---|---|
| calm | 139 | -0.41 | -0.23 | 9.7% | 10.1% |
| equity drawdown | 95 | -0.55 | -0.44 | 2.9% | 3.5% |

#### GARCH (superseded)

_Superseded: every figure in this block comes from the uncapped GARCH simulation (section 2)._

##### Primary test: U1 mix vs frontier mix

**Primary test (U1 mix by free search vs frontier mix): not supported** - model criterion not met.

Realized support: not attainable; disjoint annual intervals: 19 (tail adequacy needs 200; realized tails are underpowered).

| Comparator | Pairs (origin x risk level) | U1 gain, bp (95% interval) | Banks positive | Bad-year change, bp | Worst-2.5% average change, bp | Risk difference, bp | Realized gain, bp (99% interval) | Realized drawdown improvement, pp |
|---|---|---|---|---|---|---|---|---|
| Frontier mix (the test) | 1476 | +1.7 [-12.6, +27.6] | 3/5 | +44.7 | +63.9 | -17.1 | +4.7 [-35.5, +44.9] | +0.25 |
| Bayes-Stein frontier mix (reported only) | 1476 | +4.2 [-9.5, +28.7] | 5/5 | +45.1 | +63.9 | -15.7 | +14.5 [-30.0, +55.8] | +0.30 |

Narrow-band check (risk tolerance 0.1% instead of 1%) on 6 origins: U1 gain +23.6 bp in the main run, +21.1 bp in the narrow band, signs agree.

Realized guardrails by risk level (U1 mix minus frontier mix, monthly rebalancing; a positive loss is worse):

| Risk level | Origins | Median return loss, bp | Mean return loss, bp | Loss frequency change, pp | Drawdown worsening, pp | Guardrail holds |
|---|---|---|---|---|---|---|
| 0.1 | 234 | +30.0 | +18.8 | +0.85 | -0.09 | NO |
| 0.25 | 234 | +55.6 | +12.3 | -0.85 | -0.16 | NO |
| 0.4 | 234 | -25.9 | -10.2 | +0.00 | -0.21 | yes |
| 0.55 | 234 | -1.5 | -25.9 | -1.28 | -0.37 | yes |
| 0.7 | 234 | -19.4 | -4.3 | -2.99 | -0.29 | yes |
| 0.85 | 234 | -36.3 | -19.0 | -2.99 | -0.39 | yes |

##### Where the U1 mix sits on the slider

| Risk level | Origins | Undefined (collapsed line) | Position p10 | Position p50 (median) | Position p90 | Share below 0 | Share above 1 | Share at 0.25 or more | Anchor regret (mean, position above 1) | Replaced by an interior search |
|---|---|---|---|---|---|---|---|---|---|---|
| 0.1 | 246 | 0 | -0.08 | 0.01 | 0.21 | 41.9% | 0.0% | 3.7% | n/a | 77.6% |
| 0.25 | 246 | 0 | -0.10 | 0.02 | 0.23 | 34.6% | 0.0% | 5.7% | n/a | 79.7% |
| 0.4 | 246 | 0 | -0.13 | 0.02 | 0.24 | 35.4% | 0.0% | 8.9% | n/a | 78.5% |
| 0.55 | 246 | 0 | -0.03 | 0.04 | 0.27 | 22.0% | 0.0% | 12.6% | n/a | 76.8% |
| 0.7 | 246 | 0 | -0.07 | 0.05 | 0.39 | 26.8% | 0.0% | 16.7% | n/a | 75.2% |
| 0.85 | 246 | 0 | -0.04 | 0.08 | 0.31 | 21.1% | 0.0% | 17.5% | n/a | 78.0% |

##### Max-Bad mix vs U1 mix (free search)

| Risk level | Realized bad year: max-Bad mix | Realized bad year: U1 mix | Mean drawdown: max-Bad mix | Mean drawdown: U1 mix | Mean return: max-Bad mix | Mean return: U1 mix |
|---|---|---|---|---|---|---|
| 0.1 | -7.3% | -7.6% | 4.5% | 4.6% | 4.9% | 4.8% |
| 0.25 | -11.0% | -13.6% | 6.7% | 6.9% | 6.0% | 6.1% |
| 0.4 | -15.6% | -15.4% | 8.7% | 8.8% | 7.2% | 7.3% |
| 0.55 | -18.7% | -18.2% | 10.1% | 10.2% | 8.5% | 8.4% |
| 0.7 | -22.1% | -22.8% | 12.0% | 12.1% | 8.9% | 8.9% |
| 0.85 | -34.7% | -32.3% | 13.9% | 13.9% | 9.3% | 9.3% |

Realized return, max-Bad mix minus U1 mix (six risk levels pooled): -0.02 pp [-0.17, +0.13].

Realized drawdown, max-Bad mix minus U1 mix (six risk levels pooled): -0.10 pp [-0.19, -0.00].

Simulated bad-year change -1.7 bp, worst-2.5% average change -1.2 bp (independent banks, max-Bad mix minus U1 mix, six risk levels pooled).

##### Line shape: U1 mix at slider positions 0.25, 0.50, 0.75

| Risk level | Common origins | Slope per unit of slider position: realized bad year, pp | Slope: mean drawdown, pp | Slope: mean return, pp |
|---|---|---|---|---|
| 0.1 | 234 | -3.59 [-5.01, +1.98] | +0.28 [-0.23, +0.85] | +0.01 [-0.62, +0.68] |
| 0.25 | 234 | -1.73 [-4.30, +3.38] | -0.14 [-0.79, +0.64] | +0.50 [-0.65, +1.71] |
| 0.4 | 234 | +0.87 [-7.35, +4.92] | -0.17 [-0.96, +0.72] | +0.28 [-1.09, +1.61] |
| 0.55 | 234 | -6.37 [-13.14, +2.97] | +0.37 [-0.63, +1.52] | -0.50 [-1.90, +0.77] |
| 0.7 | 234 | -5.71 [-11.67, +7.84] | +0.02 [-0.90, +0.88] | +0.27 [-1.63, +2.18] |
| 0.85 | 234 | +2.95 [-6.77, +5.35] | -0.15 [-1.13, +0.78] | +0.68 [-1.80, +3.30] |

##### Realized extras

**Multi-year and real returns (U1 mix by free search and frontier mix, monthly rebalancing, six risk levels pooled; descriptive)**

| Horizon | Rows | Origins | U1 mix mean | Frontier mix mean | Difference, pp |
|---|---|---|---|---|---|
| 1y | 1404 | 234 | 7.5% | 7.4% | +0.05 |
| 3y | 1260 | 210 | 23.3% | 23.6% | -0.32 |
| 5y | 1116 | 186 | 39.0% | 38.8% | +0.20 |
| 1y real | 1392 | 232 | 4.7% | 4.7% | +0.04 |
| 3y real | 1248 | 208 | 14.4% | 14.7% | -0.27 |
| 5y real | 1104 | 184 | 22.9% | 22.7% | +0.20 |

**Cost variant (10 bp of one-way turnover, funding included; six risk levels pooled)**

|  | Gross | Net |
|---|---|---|
| U1 mix mean return |  | 7.4% |
| Frontier mix mean return |  | 7.3% |
| U1 mix minus frontier mix, pp | +0.05 | +0.05 |
| Mean rebalance turnover (U1 mix / frontier mix) |  | 0.15 / 0.14 |

**Regime buckets (U1 mix minus frontier mix, monthly rebalancing, six risk levels pooled)**

| Regime | Origins | Return difference, pp | Drawdown difference, pp | U1 mix mean | Frontier mix mean |
|---|---|---|---|---|---|
| calm | 139 | +0.07 | -0.21 | 10.2% | 10.1% |
| equity drawdown | 95 | +0.02 | -0.31 | 3.5% | 3.5% |

#### Engine agreement: GARCH vs history replay (superseded)

_Superseded: every figure in this block comes from the uncapped GARCH simulation (section 2)._

GARCH vs history replay: 11.1% of 29520 locked mixes within L1 <= 0.10 (median L1 0.293).

| Slider cell | Share within |
|---|---|
| d25 | 9.7% |
| d50 | 8.2% |
| d75 | 10.3% |
| free | 16.0% |

| Arm | Share within |
|---|---|
| B | 5.0% |
| U1 | 10.0% |
| U2 | 8.2% |
| U3 | 13.6% |
| U4 | 18.5% |

Realized return, GARCH minus history replay (U1 mix by free search, n=234 origins): +0.51 pp [+0.24, +0.79].

Realized drawdown, GARCH minus history replay (U1 mix by free search, n=234 origins): +0.06 pp [-0.20, +0.41].

### 5.2 Menu TSP (5 funds)

Collapsed share of risk lines: 0.0% at each of the six risk levels (244 lines per risk level; overall 0.0%). Showcase surfaces: 324 columns, collapsed share 0.3%.

#### History replay

##### Primary test: U1 mix vs frontier mix

**Primary test (U1 mix by free search vs frontier mix): inconclusive** - the pooled U1 gain changes sign at risk tolerance 0.001.

Realized support: not attainable; disjoint annual intervals: 18 (tail adequacy needs 200; realized tails are underpowered).

| Comparator | Pairs (origin x risk level) | U1 gain, bp (95% interval) | Banks positive | Bad-year change, bp | Worst-2.5% average change, bp | Risk difference, bp | Realized gain, bp (99% interval) | Realized drawdown improvement, pp |
|---|---|---|---|---|---|---|---|---|
| Frontier mix (the test) | 1464 | +9.0 [+3.5, +15.5] | 5/5 | +36.2 | +44.7 | -13.6 | +5.8 [-25.1, +56.1] | +0.28 |
| Bayes-Stein frontier mix (reported only) | 1464 | +7.9 [+3.5, +13.0] | 5/5 | +32.4 | +39.8 | -13.0 | -4.1 [-32.5, +46.5] | +0.21 |

Narrow-band check (risk tolerance 0.1% instead of 1%) on 6 origins: U1 gain +1.7 bp in the main run, -2.0 bp in the narrow band, signs DIFFER.

Realized guardrails by risk level (U1 mix minus frontier mix, monthly rebalancing; a positive loss is worse):

| Risk level | Origins | Median return loss, bp | Mean return loss, bp | Loss frequency change, pp | Drawdown worsening, pp | Guardrail holds |
|---|---|---|---|---|---|---|
| 0.1 | 231 | +6.5 | -11.8 | -0.43 | -0.18 | yes |
| 0.25 | 231 | -15.1 | -2.4 | -0.87 | -0.24 | yes |
| 0.4 | 231 | +4.9 | -8.7 | +0.00 | -0.31 | yes |
| 0.55 | 231 | -0.7 | -13.5 | -0.43 | -0.36 | yes |
| 0.7 | 231 | +3.6 | -0.3 | -0.43 | -0.32 | yes |
| 0.85 | 231 | +3.0 | +1.7 | +0.43 | -0.25 | yes |

##### Where the U1 mix sits on the slider

| Risk level | Origins | Undefined (collapsed line) | Position p10 | Position p50 (median) | Position p90 | Share below 0 | Share above 1 | Share at 0.25 or more | Anchor regret (mean, position above 1) | Replaced by an interior search |
|---|---|---|---|---|---|---|---|---|---|---|
| 0.1 | 244 | 0 | -1.04 | -0.03 | 0.11 | 61.1% | 0.0% | 4.1% | n/a | 67.2% |
| 0.25 | 244 | 0 | -1.13 | -0.05 | 0.14 | 56.6% | 0.0% | 4.1% | n/a | 54.1% |
| 0.4 | 244 | 0 | -1.45 | -0.05 | 0.16 | 54.9% | 0.0% | 4.5% | n/a | 54.9% |
| 0.55 | 244 | 0 | -1.20 | -0.01 | 0.17 | 53.3% | 0.0% | 6.1% | n/a | 50.0% |
| 0.7 | 244 | 0 | -0.84 | -0.01 | 0.19 | 56.1% | 0.0% | 6.1% | n/a | 53.7% |
| 0.85 | 244 | 0 | -0.49 | 0.02 | 0.31 | 38.9% | 0.0% | 13.9% | n/a | 59.4% |

##### Max-Bad mix vs U1 mix (free search)

| Risk level | Realized bad year: max-Bad mix | Realized bad year: U1 mix | Mean drawdown: max-Bad mix | Mean drawdown: U1 mix | Mean return: max-Bad mix | Mean return: U1 mix |
|---|---|---|---|---|---|---|
| 0.1 | -5.7% | -6.2% | 2.8% | 2.9% | 4.3% | 4.3% |
| 0.25 | -11.4% | -11.9% | 4.9% | 5.1% | 5.4% | 5.3% |
| 0.4 | -16.1% | -16.5% | 7.0% | 7.2% | 6.4% | 6.5% |
| 0.55 | -22.6% | -22.5% | 8.9% | 9.1% | 7.6% | 7.6% |
| 0.7 | -27.3% | -27.7% | 11.0% | 11.2% | 8.4% | 8.4% |
| 0.85 | -32.2% | -32.6% | 13.1% | 13.2% | 9.1% | 9.1% |

Realized return, max-Bad mix minus U1 mix (six risk levels pooled): +0.03 pp [-0.11, +0.18].

Realized drawdown, max-Bad mix minus U1 mix (six risk levels pooled): -0.18 pp [-0.30, -0.08].

Simulated bad-year change +7.3 bp, worst-2.5% average change +11.6 bp (independent banks, max-Bad mix minus U1 mix, six risk levels pooled).

##### Line shape: U1 mix at slider positions 0.25, 0.50, 0.75

| Risk level | Common origins | Slope per unit of slider position: realized bad year, pp | Slope: mean drawdown, pp | Slope: mean return, pp |
|---|---|---|---|---|
| 0.1 | 231 | -0.87 [-1.58, +0.91] | +0.18 [-0.10, +0.55] | -0.07 [-0.55, +0.36] |
| 0.25 | 231 | -0.78 [-1.96, +1.31] | +0.30 [-0.13, +0.86] | -0.29 [-1.03, +0.37] |
| 0.4 | 231 | -1.08 [-3.21, +0.39] | +0.47 [-0.06, +1.06] | -0.73 [-1.54, -0.01] |
| 0.55 | 231 | +0.66 [-4.38, +0.86] | +0.58 [+0.02, +1.13] | -0.96 [-1.72, -0.19] |
| 0.7 | 231 | +0.18 [-4.14, +1.67] | +0.66 [+0.17, +1.15] | -1.08 [-1.90, -0.26] |
| 0.85 | 231 | +0.44 [-4.52, +1.58] | +0.68 [+0.19, +1.17] | -1.44 [-2.42, -0.47] |

##### Realized extras

**Multi-year and real returns (U1 mix by free search and frontier mix, monthly rebalancing, six risk levels pooled; descriptive)**

| Horizon | Rows | Origins | U1 mix mean | Frontier mix mean | Difference, pp |
|---|---|---|---|---|---|
| 1y | 1386 | 231 | 6.9% | 6.8% | +0.06 |
| 3y | 1242 | 207 | 22.4% | 22.4% | +0.03 |
| 5y | 1098 | 183 | 38.6% | 38.3% | +0.35 |
| 1y real | 1374 | 229 | 4.0% | 3.9% | +0.05 |
| 3y real | 1230 | 205 | 13.4% | 13.3% | +0.02 |
| 5y real | 1092 | 182 | 22.5% | 22.2% | +0.25 |

**Cost variant (10 bp of one-way turnover, funding included; six risk levels pooled)**

|  | Gross | Net |
|---|---|---|
| U1 mix mean return |  | 6.7% |
| Frontier mix mean return |  | 6.7% |
| U1 mix minus frontier mix, pp | +0.06 | +0.06 |
| Mean rebalance turnover (U1 mix / frontier mix) |  | 0.08 / 0.08 |

**Regime buckets (U1 mix minus frontier mix, monthly rebalancing, six risk levels pooled)**

| Regime | Origins | Return difference, pp | Drawdown difference, pp | U1 mix mean | Frontier mix mean |
|---|---|---|---|---|---|
| calm | 136 | +0.09 | -0.19 | 10.9% | 10.8% |
| equity drawdown | 95 | +0.01 | -0.39 | 1.1% | 1.1% |

#### GARCH (superseded)

_Superseded: every figure in this block comes from the uncapped GARCH simulation (section 2)._

##### Primary test: U1 mix vs frontier mix

**Primary test (U1 mix by free search vs frontier mix): not supported** - model criterion not met.

Realized support: not attainable; disjoint annual intervals: 18 (tail adequacy needs 200; realized tails are underpowered).

| Comparator | Pairs (origin x risk level) | U1 gain, bp (95% interval) | Banks positive | Bad-year change, bp | Worst-2.5% average change, bp | Risk difference, bp | Realized gain, bp (99% interval) | Realized drawdown improvement, pp |
|---|---|---|---|---|---|---|---|---|
| Frontier mix (the test) | 1464 | -2.0 [-4.7, +0.6] | 0/5 | +15.6 | +20.7 | -13.9 | -4.0 [-30.7, +28.8] | +0.11 |
| Bayes-Stein frontier mix (reported only) | 1464 | -2.1 [-5.0, +0.6] | 0/5 | +13.9 | +19.6 | -13.3 | -14.0 [-39.8, +17.2] | +0.05 |

Narrow-band check (risk tolerance 0.1% instead of 1%) on 6 origins: U1 gain -5.2 bp in the main run, -10.2 bp in the narrow band, signs agree.

Realized guardrails by risk level (U1 mix minus frontier mix, monthly rebalancing; a positive loss is worse):

| Risk level | Origins | Median return loss, bp | Mean return loss, bp | Loss frequency change, pp | Drawdown worsening, pp | Guardrail holds |
|---|---|---|---|---|---|---|
| 0.1 | 231 | -9.2 | -6.4 | -0.43 | -0.07 | yes |
| 0.25 | 231 | -25.3 | -7.1 | -0.43 | -0.11 | yes |
| 0.4 | 231 | -24.1 | -4.1 | -0.43 | -0.11 | yes |
| 0.55 | 231 | +42.9 | +2.9 | -0.43 | -0.14 | NO |
| 0.7 | 231 | +32.5 | +11.8 | +0.43 | -0.16 | NO |
| 0.85 | 231 | +73.0 | +27.1 | +0.87 | -0.10 | NO |

##### Where the U1 mix sits on the slider

| Risk level | Origins | Undefined (collapsed line) | Position p10 | Position p50 (median) | Position p90 | Share below 0 | Share above 1 | Share at 0.25 or more | Anchor regret (mean, position above 1) | Replaced by an interior search |
|---|---|---|---|---|---|---|---|---|---|---|
| 0.1 | 244 | 0 | -0.29 | 0.06 | 0.48 | 28.3% | 0.0% | 22.5% | n/a | 75.8% |
| 0.25 | 244 | 0 | -0.23 | 0.06 | 0.48 | 27.0% | 0.0% | 25.4% | n/a | 71.3% |
| 0.4 | 244 | 0 | -0.35 | 0.06 | 0.51 | 27.9% | 0.0% | 23.0% | n/a | 69.3% |
| 0.55 | 244 | 0 | -0.29 | 0.10 | 0.52 | 25.4% | 0.0% | 25.4% | n/a | 74.2% |
| 0.7 | 244 | 0 | -0.11 | 0.13 | 0.48 | 26.6% | 0.0% | 28.3% | n/a | 75.8% |
| 0.85 | 244 | 0 | -0.10 | 0.16 | 0.49 | 20.1% | 0.0% | 33.2% | n/a | 72.5% |

##### Max-Bad mix vs U1 mix (free search)

| Risk level | Realized bad year: max-Bad mix | Realized bad year: U1 mix | Mean drawdown: max-Bad mix | Mean drawdown: U1 mix | Mean return: max-Bad mix | Mean return: U1 mix |
|---|---|---|---|---|---|---|
| 0.1 | -6.5% | -6.8% | 3.0% | 3.0% | 4.2% | 4.2% |
| 0.25 | -12.3% | -12.3% | 5.3% | 5.3% | 5.3% | 5.3% |
| 0.4 | -18.5% | -18.6% | 7.4% | 7.4% | 6.3% | 6.4% |
| 0.55 | -22.5% | -22.6% | 9.3% | 9.3% | 7.3% | 7.4% |
| 0.7 | -28.0% | -27.9% | 11.4% | 11.4% | 8.1% | 8.2% |
| 0.85 | -32.6% | -32.6% | 13.4% | 13.4% | 8.7% | 8.9% |

Realized return, max-Bad mix minus U1 mix (six risk levels pooled): -0.09 pp [-0.22, +0.03].

Realized drawdown, max-Bad mix minus U1 mix (six risk levels pooled): -0.01 pp [-0.06, +0.02].

Simulated bad-year change -2.6 bp, worst-2.5% average change -0.4 bp (independent banks, max-Bad mix minus U1 mix, six risk levels pooled).

##### Line shape: U1 mix at slider positions 0.25, 0.50, 0.75

| Risk level | Common origins | Slope per unit of slider position: realized bad year, pp | Slope: mean drawdown, pp | Slope: mean return, pp |
|---|---|---|---|---|
| 0.1 | 231 | -0.59 [-1.81, +1.43] | +0.16 [-0.13, +0.54] | -0.05 [-0.55, +0.39] |
| 0.25 | 231 | -0.02 [-1.73, +1.69] | +0.19 [-0.25, +0.77] | -0.13 [-0.79, +0.45] |
| 0.4 | 231 | -0.77 [-3.21, +0.56] | +0.38 [-0.13, +0.94] | -0.54 [-1.27, +0.11] |
| 0.55 | 231 | +0.50 [-4.17, +1.33] | +0.59 [+0.06, +1.14] | -0.88 [-1.69, -0.09] |
| 0.7 | 231 | +0.81 [-5.62, +1.33] | +0.69 [+0.20, +1.18] | -1.37 [-2.25, -0.52] |
| 0.85 | 231 | -0.01 [-6.18, +0.15] | +0.77 [+0.29, +1.28] | -1.54 [-2.45, -0.60] |

##### Realized extras

**Multi-year and real returns (U1 mix by free search and frontier mix, monthly rebalancing, six risk levels pooled; descriptive)**

| Horizon | Rows | Origins | U1 mix mean | Frontier mix mean | Difference, pp |
|---|---|---|---|---|---|
| 1y | 1386 | 231 | 6.8% | 6.8% | -0.04 |
| 3y | 1242 | 207 | 22.1% | 22.4% | -0.24 |
| 5y | 1098 | 183 | 37.7% | 38.3% | -0.53 |
| 1y real | 1374 | 229 | 3.9% | 3.9% | -0.03 |
| 3y real | 1230 | 205 | 13.1% | 13.3% | -0.24 |
| 5y real | 1092 | 182 | 21.7% | 22.2% | -0.49 |

**Cost variant (10 bp of one-way turnover, funding included; six risk levels pooled)**

|  | Gross | Net |
|---|---|---|
| U1 mix mean return |  | 6.6% |
| Frontier mix mean return |  | 6.7% |
| U1 mix minus frontier mix, pp | -0.04 | -0.04 |
| Mean rebalance turnover (U1 mix / frontier mix) |  | 0.08 / 0.08 |

**Regime buckets (U1 mix minus frontier mix, monthly rebalancing, six risk levels pooled)**

| Regime | Origins | Return difference, pp | Drawdown difference, pp | U1 mix mean | Frontier mix mean |
|---|---|---|---|---|---|
| calm | 136 | -0.13 | -0.07 | 10.7% | 10.8% |
| equity drawdown | 95 | +0.09 | -0.17 | 1.2% | 1.1% |

#### Engine agreement: GARCH vs history replay (superseded)

_Superseded: every figure in this block comes from the uncapped GARCH simulation (section 2)._

GARCH vs history replay: 39.7% of 29280 locked mixes within L1 <= 0.10 (median L1 0.140).

| Slider cell | Share within |
|---|---|
| d25 | 43.8% |
| d50 | 38.8% |
| d75 | 40.7% |
| free | 35.5% |

| Arm | Share within |
|---|---|
| B | 33.0% |
| U1 | 40.5% |
| U2 | 37.9% |
| U3 | 42.3% |
| U4 | 44.8% |

Realized return, GARCH minus history replay (U1 mix by free search, n=231 origins): -0.10 pp [-0.28, +0.08].

Realized drawdown, GARCH minus history replay (U1 mix by free search, n=231 origins): +0.16 pp [+0.06, +0.29].

## 6. Diagnostics

Descriptive checks, in the order the protocol lists them. Slider cells: d25, d50 and d75 are slider
positions 0.25, 0.50 and 0.75; free is the free search. Calibration arms: U1 to U4 are the four U
weight triples (bad, typical, good) U1 = (.60, .30, .10), U2 = (.70, .20, .10), U3 = (.50, .35,
.15), U4 = (.40, .40, .20); B is the max-Bad mix. Calibration rows pool all six risk levels and four
slider cells, one row per origin, risk level and cell.

### 6.1 Menu research2003

#### History replay

##### Stability of the U1 mix across five banks

| Slider cell | Risk level | Origins (5 banks) | Median L1 | P90 L1 | Bad SD <= 0.10 sigma | Meets v1 stability rules |
|---|---|---|---|---|---|---|
| d25 | 0.1 | 62 | 0.09 | 0.33 | 91.9% | no |
| d25 | 0.25 | 62 | 0.16 | 0.35 | 100.0% | pass |
| d25 | 0.4 | 62 | 0.21 | 0.53 | 95.2% | no |
| d25 | 0.55 | 62 | 0.22 | 0.47 | 98.4% | no |
| d25 | 0.7 | 62 | 0.25 | 0.47 | 100.0% | no |
| d25 | 0.85 | 62 | 0.27 | 0.52 | 100.0% | no |
| d50 | 0.1 | 62 | 0.09 | 0.31 | 100.0% | pass |
| d50 | 0.25 | 62 | 0.18 | 0.49 | 98.4% | no |
| d50 | 0.4 | 62 | 0.24 | 0.48 | 93.5% | no |
| d50 | 0.55 | 62 | 0.26 | 0.48 | 100.0% | no |
| d50 | 0.7 | 62 | 0.27 | 0.53 | 98.4% | no |
| d50 | 0.85 | 62 | 0.29 | 0.50 | 100.0% | no |
| d75 | 0.1 | 62 | 0.10 | 0.33 | 100.0% | pass |
| d75 | 0.25 | 62 | 0.16 | 0.44 | 100.0% | no |
| d75 | 0.4 | 62 | 0.23 | 0.40 | 96.8% | no |
| d75 | 0.55 | 62 | 0.21 | 0.37 | 100.0% | no |
| d75 | 0.7 | 62 | 0.24 | 0.43 | 100.0% | no |
| d75 | 0.85 | 62 | 0.27 | 0.51 | 98.4% | no |
| free | 0.1 | 62 | 0.06 | 0.59 | 95.2% | no |
| free | 0.25 | 62 | 0.13 | 0.79 | 95.2% | no |
| free | 0.4 | 62 | 0.20 | 0.78 | 93.5% | no |
| free | 0.55 | 62 | 0.21 | 0.72 | 98.4% | no |
| free | 0.7 | 62 | 0.23 | 0.62 | 98.4% | no |
| free | 0.85 | 62 | 0.30 | 0.68 | 98.4% | no |

##### Forecast calibration (daily-rebalanced realized year)

| Arm | Forecast | Nominal | Coverage | Pinball | Rows |
|---|---|---|---|---|---|
| U1 | training_bad | 0.025 | 9.2% | 0.01102 | 5616 |
| U1 | training_typical | 0.5 | 52.5% | 0.03939 | 5616 |
| U1 | training_good | 0.975 | 99.1% | 0.00631 | 5616 |
| U1 | independent_bad | 0.025 | 8.7% | 0.01078 | 5616 |
| U1 | independent_typical | 0.5 | 52.2% | 0.03923 | 5616 |
| U1 | independent_good | 0.975 | 99.1% | 0.00627 | 5616 |
| U2 | training_bad | 0.025 | 9.3% | 0.01111 | 5616 |
| U2 | training_typical | 0.5 | 52.4% | 0.03935 | 5616 |
| U2 | training_good | 0.975 | 99.1% | 0.00628 | 5616 |
| U2 | independent_bad | 0.025 | 8.9% | 0.01087 | 5616 |
| U2 | independent_typical | 0.5 | 52.1% | 0.03919 | 5616 |
| U2 | independent_good | 0.975 | 99.1% | 0.00624 | 5616 |
| U3 | training_bad | 0.025 | 8.8% | 0.01092 | 5616 |
| U3 | training_typical | 0.5 | 52.5% | 0.03950 | 5616 |
| U3 | training_good | 0.975 | 99.2% | 0.00643 | 5616 |
| U3 | independent_bad | 0.025 | 8.4% | 0.01071 | 5616 |
| U3 | independent_typical | 0.5 | 52.2% | 0.03934 | 5616 |
| U3 | independent_good | 0.975 | 99.2% | 0.00637 | 5616 |
| U4 | training_bad | 0.025 | 8.5% | 0.01075 | 5616 |
| U4 | training_typical | 0.5 | 52.7% | 0.03978 | 5616 |
| U4 | training_good | 0.975 | 99.2% | 0.00658 | 5616 |
| U4 | independent_bad | 0.025 | 8.1% | 0.01058 | 5616 |
| U4 | independent_typical | 0.5 | 52.4% | 0.03960 | 5616 |
| U4 | independent_good | 0.975 | 99.2% | 0.00651 | 5616 |
| B | training_bad | 0.025 | 9.8% | 0.01156 | 5616 |
| B | training_typical | 0.5 | 51.8% | 0.03943 | 5616 |
| B | training_good | 0.975 | 99.2% | 0.00615 | 5616 |
| B | independent_bad | 0.025 | 9.2% | 0.01129 | 5616 |
| B | independent_typical | 0.5 | 51.8% | 0.03928 | 5616 |
| B | independent_good | 0.975 | 99.1% | 0.00614 | 5616 |

##### Which U weights hold up: purged CSCV adaptation

Splits evaluable: 35 of 70 (35 dropped: a training block; training side); (r, cell) pairs in the common mask: 24; rows used 5616, excluded for labels 0, for collapsed columns 0, for missing triples 288. Masks: frozen in the parent manifest.

PBO: PBO not computable: 35 of 70 splits evaluable (minimum 50). Training side 31-106 origins (median 6 disjoint years), test side 116-118 (median 10).

| U weight triple | Chosen in training | Mean test U1 |
|---|---|---|
| U1 | 0.0% | -5.6% |
| U2 | 5.7% | -5.7% |
| U3 | 34.3% | -5.5% |
| U4 | 60.0% | -5.4% |

Mean test rank of the chosen triple: 3.37 of 4 (4 best); ties in training: 0.

Degradation (chosen triple): mean training U1 -2.7%, mean test U1 -5.4%.

##### Selection bias: deflated Sharpe ratio (diagnostic, not a gate)

| Years (n) | SR | SR_0 | Trial var | N_eff | Trials used | Zero-sd dropped | Skew | Kurtosis | DSR |
|---|---|---|---|---|---|---|---|---|---|
| 19 | -0.530 | 0.000 | 0.0498 | 1.58 | 20 | 0 | -0.786 | 2.825 | 0.004 |

##### Search cost

| Arm | Cells | Median s | P95 s | Median iterations |
|---|---|---|---|---|
| B | 7380 | 17.24 | 42.75 | 622 |
| U1 | 7380 | 18.24 | 44.89 | 647 |
| U2 | 7380 | 17.50 | 43.34 | 630 |
| U3 | 7380 | 18.44 | 44.17 | 664 |
| U4 | 7380 | 19.46 | 44.34 | 696 |

Total search time 288.93 h. Showcase: 13713.1 s per surface (6 surfaces). Solvers: {'cobyla768': 55266}.

#### GARCH (superseded)

_Superseded: every figure in this block comes from the uncapped GARCH simulation (section 2)._

##### Stability of the U1 mix across five banks

| Slider cell | Risk level | Origins (5 banks) | Median L1 | P90 L1 | Bad SD <= 0.10 sigma | Meets v1 stability rules |
|---|---|---|---|---|---|---|
| d25 | 0.1 | 62 | 0.09 | 0.31 | 77.4% | no |
| d25 | 0.25 | 62 | 0.17 | 0.43 | 77.4% | no |
| d25 | 0.4 | 62 | 0.20 | 0.49 | 77.4% | no |
| d25 | 0.55 | 62 | 0.25 | 0.52 | 77.4% | no |
| d25 | 0.7 | 62 | 0.28 | 0.57 | 80.6% | no |
| d25 | 0.85 | 62 | 0.31 | 0.61 | 79.0% | no |
| d50 | 0.1 | 62 | 0.12 | 0.40 | 77.4% | no |
| d50 | 0.25 | 62 | 0.19 | 0.42 | 79.0% | no |
| d50 | 0.4 | 62 | 0.24 | 0.54 | 77.4% | no |
| d50 | 0.55 | 62 | 0.30 | 0.55 | 80.6% | no |
| d50 | 0.7 | 62 | 0.32 | 0.58 | 77.4% | no |
| d50 | 0.85 | 62 | 0.33 | 0.58 | 82.3% | no |
| d75 | 0.1 | 62 | 0.14 | 0.36 | 79.0% | no |
| d75 | 0.25 | 62 | 0.19 | 0.43 | 75.8% | no |
| d75 | 0.4 | 62 | 0.26 | 0.45 | 77.4% | no |
| d75 | 0.55 | 62 | 0.29 | 0.49 | 79.0% | no |
| d75 | 0.7 | 62 | 0.28 | 0.50 | 77.4% | no |
| d75 | 0.85 | 62 | 0.29 | 0.54 | 79.0% | no |
| free | 0.1 | 62 | 0.05 | 0.54 | 72.6% | no |
| free | 0.25 | 62 | 0.09 | 0.79 | 71.0% | no |
| free | 0.4 | 62 | 0.14 | 0.85 | 72.6% | no |
| free | 0.55 | 62 | 0.20 | 0.74 | 72.6% | no |
| free | 0.7 | 62 | 0.27 | 0.72 | 74.2% | no |
| free | 0.85 | 62 | 0.31 | 0.77 | 75.8% | no |

##### Forecast calibration (daily-rebalanced realized year)

| Arm | Forecast | Nominal | Coverage | Pinball | Rows |
|---|---|---|---|---|---|
| U1 | training_bad | 0.025 | 7.0% | 0.00870 | 5616 |
| U1 | training_typical | 0.5 | 51.3% | 0.03973 | 5616 |
| U1 | training_good | 0.975 | 98.0% | 0.00754 | 5616 |
| U1 | independent_bad | 0.025 | 5.4% | 0.00859 | 5616 |
| U1 | independent_typical | 0.5 | 51.0% | 0.03980 | 5616 |
| U1 | independent_good | 0.975 | 99.7% | 0.00723 | 5616 |
| U2 | training_bad | 0.025 | 7.0% | 0.00873 | 5616 |
| U2 | training_typical | 0.5 | 51.2% | 0.03970 | 5616 |
| U2 | training_good | 0.975 | 97.8% | 0.00753 | 5616 |
| U2 | independent_bad | 0.025 | 5.3% | 0.00862 | 5616 |
| U2 | independent_typical | 0.5 | 50.9% | 0.03976 | 5616 |
| U2 | independent_good | 0.975 | 99.6% | 0.00721 | 5616 |
| U3 | training_bad | 0.025 | 6.9% | 0.00873 | 5616 |
| U3 | training_typical | 0.5 | 51.5% | 0.03982 | 5616 |
| U3 | training_good | 0.975 | 98.4% | 0.00755 | 5616 |
| U3 | independent_bad | 0.025 | 5.4% | 0.00864 | 5616 |
| U3 | independent_typical | 0.5 | 51.2% | 0.03990 | 5616 |
| U3 | independent_good | 0.975 | 99.7% | 0.00727 | 5616 |
| U4 | training_bad | 0.025 | 6.7% | 0.00878 | 5616 |
| U4 | training_typical | 0.5 | 51.4% | 0.04000 | 5616 |
| U4 | training_good | 0.975 | 98.7% | 0.00765 | 5616 |
| U4 | independent_bad | 0.025 | 5.5% | 0.00870 | 5616 |
| U4 | independent_typical | 0.5 | 51.2% | 0.04006 | 5616 |
| U4 | independent_good | 0.975 | 99.7% | 0.00733 | 5616 |
| B | training_bad | 0.025 | 6.9% | 0.00872 | 5616 |
| B | training_typical | 0.5 | 50.9% | 0.03951 | 5616 |
| B | training_good | 0.975 | 97.8% | 0.00748 | 5616 |
| B | independent_bad | 0.025 | 5.2% | 0.00863 | 5616 |
| B | independent_typical | 0.5 | 50.5% | 0.03954 | 5616 |
| B | independent_good | 0.975 | 99.6% | 0.00716 | 5616 |

##### Which U weights hold up: purged CSCV adaptation

Splits evaluable: 35 of 70 (35 dropped: a training block; training side); (r, cell) pairs in the common mask: 24; rows used 5616, excluded for labels 0, for collapsed columns 0, for missing triples 288. Masks: frozen in the parent manifest.

PBO: PBO not computable: 35 of 70 splits evaluable (minimum 50). Training side 31-106 origins (median 6 disjoint years), test side 116-118 (median 10).

| U weight triple | Chosen in training | Mean test U1 |
|---|---|---|
| U1 | 17.1% | -5.0% |
| U2 | 28.6% | -5.0% |
| U3 | 11.4% | -4.9% |
| U4 | 42.9% | -4.9% |

Mean test rank of the chosen triple: 2.40 of 4 (4 best); ties in training: 0.

Degradation (chosen triple): mean training U1 -2.4%, mean test U1 -5.0%.

##### Selection bias: deflated Sharpe ratio (diagnostic, not a gate)

| Years (n) | SR | SR_0 | Trial var | N_eff | Trials used | Zero-sd dropped | Skew | Kurtosis | DSR |
|---|---|---|---|---|---|---|---|---|---|
| 19 | -0.066 | 0.000 | 0.0135 | 1.53 | 20 | 0 | -1.289 | 6.961 | 0.386 |

##### Search cost

| Arm | Cells | Median s | P95 s | Median iterations |
|---|---|---|---|---|
| B | 7380 | 22.59 | 44.10 | 614 |
| U1 | 7380 | 25.84 | 49.14 | 652 |
| U2 | 7380 | 23.75 | 45.49 | 633 |
| U3 | 7380 | 25.72 | 47.36 | 674 |
| U4 | 7380 | 26.68 | 48.03 | 702 |

Total search time 387.69 h. Showcase: 23471.0 s per surface (6 surfaces). Solvers: {'cobyla768': 55266}.

#### Rows without a locked mix, and cell labels

The two engines give the same rows and labels.

##### Rows without a locked mix (excluded from every statistic above)

_no rows_

##### Cell labels (non-ok; none is called infeasible)

_no rows_

### 6.2 Menu TSP

#### History replay

##### Stability of the U1 mix across five banks

| Slider cell | Risk level | Origins (5 banks) | Median L1 | P90 L1 | Bad SD <= 0.10 sigma | Meets v1 stability rules |
|---|---|---|---|---|---|---|
| d25 | 0.1 | 61 | 0.05 | 0.14 | 86.9% | no |
| d25 | 0.25 | 61 | 0.06 | 0.20 | 95.1% | pass |
| d25 | 0.4 | 61 | 0.10 | 0.29 | 98.4% | pass |
| d25 | 0.55 | 61 | 0.11 | 0.34 | 96.7% | pass |
| d25 | 0.7 | 61 | 0.14 | 0.39 | 96.7% | pass |
| d25 | 0.85 | 61 | 0.11 | 0.39 | 98.4% | pass |
| d50 | 0.1 | 61 | 0.06 | 0.14 | 91.8% | no |
| d50 | 0.25 | 61 | 0.09 | 0.24 | 96.7% | pass |
| d50 | 0.4 | 61 | 0.11 | 0.32 | 96.7% | pass |
| d50 | 0.55 | 61 | 0.14 | 0.36 | 98.4% | pass |
| d50 | 0.7 | 61 | 0.16 | 0.41 | 98.4% | no |
| d50 | 0.85 | 61 | 0.15 | 0.40 | 98.4% | no |
| d75 | 0.1 | 61 | 0.05 | 0.13 | 96.7% | pass |
| d75 | 0.25 | 61 | 0.08 | 0.21 | 95.1% | pass |
| d75 | 0.4 | 61 | 0.11 | 0.28 | 98.4% | pass |
| d75 | 0.55 | 61 | 0.12 | 0.35 | 98.4% | pass |
| d75 | 0.7 | 61 | 0.14 | 0.38 | 96.7% | pass |
| d75 | 0.85 | 61 | 0.15 | 0.40 | 98.4% | pass |
| free | 0.1 | 61 | 0.04 | 0.29 | 93.4% | no |
| free | 0.25 | 61 | 0.08 | 0.44 | 95.1% | no |
| free | 0.4 | 61 | 0.10 | 0.46 | 96.7% | no |
| free | 0.55 | 61 | 0.10 | 0.59 | 96.7% | no |
| free | 0.7 | 61 | 0.11 | 0.53 | 98.4% | no |
| free | 0.85 | 61 | 0.12 | 0.48 | 96.7% | no |

##### Forecast calibration (daily-rebalanced realized year)

| Arm | Forecast | Nominal | Coverage | Pinball | Rows |
|---|---|---|---|---|---|
| U1 | training_bad | 0.025 | 10.0% | 0.01239 | 5544 |
| U1 | training_typical | 0.5 | 42.3% | 0.03659 | 5544 |
| U1 | training_good | 0.975 | 98.5% | 0.00475 | 5544 |
| U1 | independent_bad | 0.025 | 9.8% | 0.01221 | 5544 |
| U1 | independent_typical | 0.5 | 42.2% | 0.03662 | 5544 |
| U1 | independent_good | 0.975 | 98.6% | 0.00472 | 5544 |
| U2 | training_bad | 0.025 | 9.9% | 0.01237 | 5544 |
| U2 | training_typical | 0.5 | 42.1% | 0.03649 | 5544 |
| U2 | training_good | 0.975 | 98.5% | 0.00474 | 5544 |
| U2 | independent_bad | 0.025 | 9.8% | 0.01219 | 5544 |
| U2 | independent_typical | 0.5 | 41.9% | 0.03651 | 5544 |
| U2 | independent_good | 0.975 | 98.5% | 0.00470 | 5544 |
| U3 | training_bad | 0.025 | 10.0% | 0.01240 | 5544 |
| U3 | training_typical | 0.5 | 42.4% | 0.03673 | 5544 |
| U3 | training_good | 0.975 | 98.5% | 0.00481 | 5544 |
| U3 | independent_bad | 0.025 | 9.9% | 0.01223 | 5544 |
| U3 | independent_typical | 0.5 | 42.2% | 0.03676 | 5544 |
| U3 | independent_good | 0.975 | 98.6% | 0.00476 | 5544 |
| U4 | training_bad | 0.025 | 10.0% | 0.01242 | 5544 |
| U4 | training_typical | 0.5 | 42.7% | 0.03707 | 5544 |
| U4 | training_good | 0.975 | 98.6% | 0.00488 | 5544 |
| U4 | independent_bad | 0.025 | 9.9% | 0.01226 | 5544 |
| U4 | independent_typical | 0.5 | 42.5% | 0.03712 | 5544 |
| U4 | independent_good | 0.975 | 98.6% | 0.00483 | 5544 |
| B | training_bad | 0.025 | 9.9% | 0.01223 | 5544 |
| B | training_typical | 0.5 | 41.8% | 0.03621 | 5544 |
| B | training_good | 0.975 | 98.4% | 0.00470 | 5544 |
| B | independent_bad | 0.025 | 9.7% | 0.01204 | 5544 |
| B | independent_typical | 0.5 | 41.6% | 0.03621 | 5544 |
| B | independent_good | 0.975 | 98.5% | 0.00467 | 5544 |

##### Which U weights hold up: purged CSCV adaptation

Splits evaluable: 20 of 70 (50 dropped: a training block; training side); (r, cell) pairs in the common mask: 24; rows used 5498, excluded for labels 46, for collapsed columns 0, for missing triples 312. Masks: frozen in the parent manifest.

PBO: PBO not computable: 20 of 70 splits evaluable (minimum 50). Training side 27-104 origins (median 6 disjoint years), test side 115-116 (median 10).

| U weight triple | Chosen in training | Mean test U1 |
|---|---|---|
| U1 | 15.0% | -6.0% |
| U2 | 55.0% | -6.0% |
| U3 | 5.0% | -6.0% |
| U4 | 25.0% | -6.2% |

Mean test rank of the chosen triple: 2.20 of 4 (4 best); ties in training: 0.

Degradation (chosen triple): mean training U1 -0.8%, mean test U1 -6.1%.

##### Selection bias: deflated Sharpe ratio (diagnostic, not a gate)

| Years (n) | SR | SR_0 | Trial var | N_eff | Trials used | Zero-sd dropped | Skew | Kurtosis | DSR |
|---|---|---|---|---|---|---|---|---|---|
| 18 | -0.247 | 0.137 | 0.0621 | 2.06 | 20 | 0 | 0.319 | 4.943 | 0.069 |

##### Search cost

| Arm | Cells | Median s | P95 s | Median iterations |
|---|---|---|---|---|
| B | 7320 | 0.62 | 0.95 | 169 |
| U1 | 7320 | 0.64 | 0.94 | 169 |
| U2 | 7320 | 0.62 | 0.90 | 168 |
| U3 | 7320 | 0.62 | 0.88 | 170 |
| U4 | 7320 | 0.62 | 0.88 | 170 |

Total search time 9.23 h. Showcase: 565.7 s per surface (6 surfaces). Solvers: {'cobyla768': 54822}.

#### GARCH (superseded)

_Superseded: every figure in this block comes from the uncapped GARCH simulation (section 2)._

##### Stability of the U1 mix across five banks

| Slider cell | Risk level | Origins (5 banks) | Median L1 | P90 L1 | Bad SD <= 0.10 sigma | Meets v1 stability rules |
|---|---|---|---|---|---|---|
| d25 | 0.1 | 61 | 0.05 | 0.14 | 60.7% | no |
| d25 | 0.25 | 61 | 0.09 | 0.23 | 62.3% | no |
| d25 | 0.4 | 61 | 0.13 | 0.35 | 55.7% | no |
| d25 | 0.55 | 61 | 0.17 | 0.43 | 54.1% | no |
| d25 | 0.7 | 61 | 0.19 | 0.46 | 57.4% | no |
| d25 | 0.85 | 61 | 0.17 | 0.40 | 67.2% | no |
| d50 | 0.1 | 61 | 0.06 | 0.16 | 63.9% | no |
| d50 | 0.25 | 61 | 0.10 | 0.27 | 57.4% | no |
| d50 | 0.4 | 61 | 0.15 | 0.38 | 59.0% | no |
| d50 | 0.55 | 61 | 0.20 | 0.44 | 60.7% | no |
| d50 | 0.7 | 61 | 0.21 | 0.48 | 65.6% | no |
| d50 | 0.85 | 61 | 0.22 | 0.50 | 77.0% | no |
| d75 | 0.1 | 61 | 0.06 | 0.15 | 70.5% | no |
| d75 | 0.25 | 61 | 0.09 | 0.24 | 65.6% | no |
| d75 | 0.4 | 61 | 0.14 | 0.37 | 65.6% | no |
| d75 | 0.55 | 61 | 0.18 | 0.46 | 70.5% | no |
| d75 | 0.7 | 61 | 0.22 | 0.51 | 75.4% | no |
| d75 | 0.85 | 61 | 0.23 | 0.53 | 78.7% | no |
| free | 0.1 | 61 | 0.05 | 0.29 | 60.7% | no |
| free | 0.25 | 61 | 0.11 | 0.43 | 59.0% | no |
| free | 0.4 | 61 | 0.15 | 0.58 | 50.8% | no |
| free | 0.55 | 61 | 0.17 | 0.58 | 52.5% | no |
| free | 0.7 | 61 | 0.16 | 0.58 | 63.9% | no |
| free | 0.85 | 61 | 0.18 | 0.58 | 68.9% | no |

##### Forecast calibration (daily-rebalanced realized year)

| Arm | Forecast | Nominal | Coverage | Pinball | Rows |
|---|---|---|---|---|---|
| U1 | training_bad | 0.025 | 8.7% | 0.01188 | 5544 |
| U1 | training_typical | 0.5 | 41.7% | 0.03704 | 5544 |
| U1 | training_good | 0.975 | 97.3% | 0.00528 | 5544 |
| U1 | independent_bad | 0.025 | 8.5% | 0.01161 | 5544 |
| U1 | independent_typical | 0.5 | 41.6% | 0.03701 | 5544 |
| U1 | independent_good | 0.975 | 98.1% | 0.00522 | 5544 |
| U2 | training_bad | 0.025 | 8.7% | 0.01186 | 5544 |
| U2 | training_typical | 0.5 | 41.6% | 0.03702 | 5544 |
| U2 | training_good | 0.975 | 97.2% | 0.00529 | 5544 |
| U2 | independent_bad | 0.025 | 8.5% | 0.01158 | 5544 |
| U2 | independent_typical | 0.5 | 41.5% | 0.03699 | 5544 |
| U2 | independent_good | 0.975 | 98.1% | 0.00523 | 5544 |
| U3 | training_bad | 0.025 | 8.7% | 0.01191 | 5544 |
| U3 | training_typical | 0.5 | 42.0% | 0.03727 | 5544 |
| U3 | training_good | 0.975 | 97.4% | 0.00530 | 5544 |
| U3 | independent_bad | 0.025 | 8.5% | 0.01164 | 5544 |
| U3 | independent_typical | 0.5 | 41.8% | 0.03724 | 5544 |
| U3 | independent_good | 0.975 | 98.1% | 0.00524 | 5544 |
| U4 | training_bad | 0.025 | 8.7% | 0.01194 | 5544 |
| U4 | training_typical | 0.5 | 42.1% | 0.03746 | 5544 |
| U4 | training_good | 0.975 | 97.5% | 0.00531 | 5544 |
| U4 | independent_bad | 0.025 | 8.6% | 0.01169 | 5544 |
| U4 | independent_typical | 0.5 | 41.9% | 0.03743 | 5544 |
| U4 | independent_good | 0.975 | 98.2% | 0.00526 | 5544 |
| B | training_bad | 0.025 | 8.7% | 0.01180 | 5544 |
| B | training_typical | 0.5 | 41.5% | 0.03702 | 5544 |
| B | training_good | 0.975 | 97.2% | 0.00529 | 5544 |
| B | independent_bad | 0.025 | 8.5% | 0.01151 | 5544 |
| B | independent_typical | 0.5 | 41.5% | 0.03699 | 5544 |
| B | independent_good | 0.975 | 98.0% | 0.00524 | 5544 |

##### Which U weights hold up: purged CSCV adaptation

Splits evaluable: 20 of 70 (50 dropped: a training block; training side); (r, cell) pairs in the common mask: 24; rows used 5498, excluded for labels 46, for collapsed columns 0, for missing triples 312. Masks: frozen in the parent manifest.

PBO: PBO not computable: 20 of 70 splits evaluable (minimum 50). Training side 27-104 origins (median 6 disjoint years), test side 115-116 (median 10).

| U weight triple | Chosen in training | Mean test U1 |
|---|---|---|
| U1 | 25.0% | -6.0% |
| U2 | 65.0% | -6.0% |
| U3 | 0.0% | -6.1% |
| U4 | 10.0% | -6.2% |

Mean test rank of the chosen triple: 3.20 of 4 (4 best); ties in training: 0.

Degradation (chosen triple): mean training U1 -0.8%, mean test U1 -6.0%.

##### Selection bias: deflated Sharpe ratio (diagnostic, not a gate)

| Years (n) | SR | SR_0 | Trial var | N_eff | Trials used | Zero-sd dropped | Skew | Kurtosis | DSR |
|---|---|---|---|---|---|---|---|---|---|
| 18 | -0.275 | 0.000 | 0.0190 | 1.37 | 20 | 0 | -1.399 | 5.862 | 0.088 |

##### Search cost

| Arm | Cells | Median s | P95 s | Median iterations |
|---|---|---|---|---|
| B | 7320 | 1.35 | 1.87 | 157 |
| U1 | 7320 | 1.54 | 2.52 | 159 |
| U2 | 7320 | 1.35 | 1.90 | 158 |
| U3 | 7320 | 1.40 | 1.98 | 161 |
| U4 | 7320 | 1.43 | 2.00 | 163 |

Total search time 21.22 h. Showcase: 1282.8 s per surface (6 surfaces). Solvers: {'cobyla768': 54822}.

#### Rows without a locked mix, and cell labels

The two engines give the same rows and labels.

##### Rows without a locked mix (excluded from every statistic above)

| Kind | Status | Rows |
|---|---|---|
| showcase | collapsed | 19 |
| showcase | not_found | 22 |

##### Cell labels (non-ok; none is called infeasible)

| Status | Cell | Risk level | Count |
|---|---|---|---|
| insufficient_starts | d25 | 0.85 | 10 |
| insufficient_starts | d50 | 0.55 | 5 |
| insufficient_starts | d50 | 0.7 | 25 |
| insufficient_starts | d50 | 0.85 | 90 |
| insufficient_starts | d75 | 0.55 | 75 |
| insufficient_starts | d75 | 0.7 | 25 |

## 7. What v3 tests

Experiment v3 ([protocol](../plans/2026-11-07-fixed-risk-experiment-v3-protocol.md), draft) asks the
owner's question directly. At each of the six risk levels it compares six mixes: the frontier mix,
the U1 mix (the v2 control), the mix with the lowest simulated drawdown, a crash-penalty mix, the
mix with the most loss contributors, and the app's own ENB knee (its Optimized point). The only
pass/fail test is the lowest-simulated-drawdown mix against the frontier mix, on the research menu
under history replay, which is v3's primary engine: it passes if the realized drawdown within the
year is smaller (95% interval above zero) by at least 1 percentage point while giving up no more
than 50 bp of realized annual return. The other arms are reported, not tested. GARCH, rerun with
the volatility cap, and the TSP menu follow only as confirmation after a pass.
