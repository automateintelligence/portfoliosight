# Fixed-risk experiment v3 report

Protocol: `docs/plans/2026-11-07-fixed-risk-experiment-v3-protocol.md` revision 4 (SHA-256 bafbb18c253d...). Job `research2003_replay`, parent digest `5757a23c3f34...`, snapshot `b0ef68baceaa...`. analysis file SHA-256 `e16bde6d0893...`. ensemble file SHA-256 `c37c4ed5aa39...`.

## In plain words

**The question.** At a fixed risk, is there a mix with slightly lower return that is more diversified and falls less in a bad year than the frontier mix, or should the app always pick the frontier mix?

**What was tested.** One pass/fail test: the lowest-simulated-drawdown mix (arm 3) against the frontier mix (arm 1), averaged with equal weight over the six risk levels and over 234 origins with a complete realized year, under the History replay engine. It passes only if it falls clearly less (by at least 1 pp on average) and costs at most 50 bp of return a year.

**The answer.** **No.** At the same risk, the lowest-simulated-drawdown mix fell 0.17 pp more than the frontier mix on average, and it earned 235.6 bp a year less than the frontier mix; the cautious (one-sided 95%) estimate of the return difference is -326.7 bp, where the line is −50 bp. So it neither fell clearly less nor kept its return: both conditions failed.

**More diversified?** Averaged over the six risk levels, the lowest-simulated-drawdown mix had 0.54 lower ENB than the frontier mix (less diversified), and higher ENB in 36.4% of origin-and-risk-level cells.

**Lower drawdown, more diversified and at most 50 bp less return, all at once?** Averaged over the six risk levels and read from the means only (not a test): the most-loss-contributors mix (arm 5) (drawdown -0.10 pp, ENB +1.93, return -6.7 bp a year).

**The app's Optimized point (arm 6), described, not tested.** Averaged over the six risk levels, against the frontier mix: return +0.01 pp a year, drawdown +0.30 pp (negative: it fell less), ENB +3.63.

**Recommendation (decision rule, §6.4 item 5):** nothing passed, so keep the app's ENB Optimized point as it is. The other mixes below inform that recommendation but cannot change it, since none of them was tested.

**Exploratory screen.** On the same years, 0 of 126 weightings of six objectives would have met both conditions. This was a look after the fact: it cannot change the answer above, and any promising weighting would need its own new test.

## How to read this report

- **Origin**: a monthly start date. The mix is chosen with data up to that month's end and held for the next year.
- **Risk level a**: where the fixed risk sits, from the lowest-risk mix (a = 0) to the highest-return mix (a = 1). The six levels are a = 0.10, 0.25, 0.40, 0.55, 0.70 and 0.85; every mix at one level has the same model volatility.
- **Drawdown**: the realized maximum drawdown within the year, the deepest fall from a peak during the year after the origin (monthly rebalanced). Lower is better.
- **Return**: the realized annual return of the year after the origin (monthly rebalanced, before costs unless marked net).
- **ENB**: the effective number of bets, the app's diversification measure. Higher means the mix's risk is spread over more independent bets.
- **pp / bp**: percentage points (1 pp = 0.01) and basis points (1 bp = 0.0001, 100 bp = 1 pp).
- **Interval**: a 95% block-bootstrap interval over origins (blocks of 24 origins) unless stated otherwise.
- **The six mixes**: frontier mix (arm 1, the highest model return at the risk), U1 mix (arm 2), lowest-simulated-drawdown mix (arm 3, the one tested), crash-penalty mix (arm 4), most-loss-contributors mix (arm 5), and the app's Optimized point (arm 6, the ENB knee the app opens on).

## The confirmatory verdict (§6)

**Label: fail (both).**

> Fail (both): point estimate -0.17 pp; one-sided 95% lower bound of the return difference -326.7 bp.

Rows: the two conditions of §6.3. Drawdown difference = frontier mix minus lowest-simulated-drawdown mix (positive: arm 3 fell less); return difference = arm 3 minus arm 1 (negative: arm 3 earned less). Both averaged over the six risk levels, then over origins.

| Condition | Point estimate | 95% interval | One-sided 95% lower bound | Line | Holds |
|---|---|---|---|---|---|
| (A) drawdown | -0.17 pp | [-0.93, +0.61] pp |  | interval above 0 and estimate ≥ 1 pp | no |
| (B) return | -235.6 bp | [-344.7, -142.3] bp | -326.7 bp | lower bound ≥ −50 bp | no |

Origins in the test: 234 (of 246 on the schedule); paired origin-and-risk-level cells: 1404. The 1 pp line is a relevance filter on the point estimate, not a tested claim.

**Sensitivities (they do not change the verdict, §6.2).**

| Interval | Drawdown difference interval | Return lower bound | (A) | (B) | Agrees with the verdict |
|---|---|---|---|---|---|
| block of 12 origins | [-0.92, +0.53] pp | -326.4 bp | no | no | yes |
| block of 36 origins | [-0.95, +0.60] pp | -323.4 bp | no | no | yes |
| Newey-West, lag 12 | [-0.88, +0.54] pp |  | no |  | yes |

Point-estimate verdict (descriptive, not the rule): **fail** (drawdown estimate ≥ 1 pp and return estimate ≥ −50 bp).

## Per risk level (descriptive, no per-level claim)

Rows: risk level a. Columns: lowest-simulated-drawdown mix (arm 3) against the frontier mix (arm 1); unadjusted 95% intervals.

| Risk level | Origins | Drawdown difference pp (95%) | Return difference bp (95%) |
|---|---|---|---|
| a = 0.10 | 234 | +0.17 [-0.63, +0.70] | -75.4 [-152.0, -2.6] |
| a = 0.25 | 234 | +0.36 [-0.48, +1.28] | -172.7 [-296.9, -59.5] |
| a = 0.40 | 234 | +0.04 [-0.92, +1.09] | -231.7 [-363.1, -112.8] |
| a = 0.55 | 234 | -0.35 [-1.30, +0.52] | -280.9 [-418.6, -147.9] |
| a = 0.70 | 234 | -0.72 [-1.52, +0.07] | -337.4 [-468.1, -233.7] |
| a = 0.85 | 234 | -0.53 [-1.27, +0.28] | -315.6 [-467.2, -198.4] |

### Relative drawdown change (§6.1, descriptive)

Share of the frontier mix's drawdown that the lowest-simulated-drawdown mix avoided, averaged over the six risk levels and then origins: -1.1% [-6.0%, 4.6%].

### Risk difference (§5)

Model volatility of arm 3 minus that of arm 1, over every origin-and-risk-level cell (both sit in the ±0.1% band, so up to 0.2% of the risk apart): mean -0.02 pp, 5th percentile -0.05 pp, 95th percentile -0.01 pp; mean share of the frontier mix's volatility -0.2%.

## The six mixes side by side (descriptive)

This answers the owner's question directly: for each mix, the return it earned, how far it fell and how diversified it was, at each risk level. Means over origins with a complete realized year (realized figures) or over all origins (model figures).

**Averaged over the six risk levels.** Rows: the mixes. Differences are against the frontier mix (drawdown: negative means it fell less).

| Mix | Return | vs frontier pp | Drawdown | vs frontier pp | ENB | vs frontier | Realized volatility |
|---|---|---|---|---|---|---|---|
| frontier mix (arm 1) | 7.4% | +0.00 | 9.6% | +0.00 | 11.76 | +0.00 | 11.0% |
| U1 mix (arm 2) | 7.0% | -0.43 | 9.3% | -0.30 | 11.74 | -0.02 | 10.8% |
| lowest-simulated-drawdown mix (arm 3) | 5.0% | -2.36 | 9.8% | +0.17 | 11.23 | -0.54 | 11.0% |
| crash-penalty mix (arm 4) | 7.3% | -0.06 | 9.3% | -0.28 | 11.65 | -0.11 | 10.9% |
| most-loss-contributors mix (arm 5) | 7.3% | -0.07 | 9.5% | -0.10 | 13.69 | +1.93 | 11.0% |
| app's Optimized point (arm 6) | 7.4% | +0.01 | 9.9% | +0.30 | 15.40 | +3.63 | 11.3% |
| app's frontier mix (reference, exact risk line) | 7.4% | -0.00 | 9.6% | -0.01 | 11.76 | +0.00 | 11.0% |

**Realized annual return.** Rows: risk level a. Columns: the six mixes.

| Risk level | 1 frontier | 2 U1 | 3 lowest sim. drawdown | 4 crash penalty | 5 most loss contributors | 6 app's Optimized point |
|---|---|---|---|---|---|---|
| a = 0.10 | 5.0% | 4.7% | 4.3% | 5.0% | 4.9% | 5.1% |
| a = 0.25 | 6.2% | 5.5% | 4.4% | 6.0% | 6.4% | 6.7% |
| a = 0.40 | 7.2% | 6.4% | 4.9% | 6.8% | 7.0% | 7.3% |
| a = 0.55 | 8.1% | 7.7% | 5.3% | 8.0% | 8.0% | 8.0% |
| a = 0.70 | 8.8% | 8.5% | 5.4% | 8.7% | 8.6% | 8.1% |
| a = 0.85 | 9.1% | 9.0% | 5.9% | 9.5% | 9.1% | 9.3% |
| mean of the six levels | 7.4% | 7.0% | 5.0% | 7.3% | 7.3% | 7.4% |

**Realized drawdown (the deepest fall within the year).** Rows: risk level a. Columns: the six mixes.

| Risk level | 1 frontier | 2 U1 | 3 lowest sim. drawdown | 4 crash penalty | 5 most loss contributors | 6 app's Optimized point |
|---|---|---|---|---|---|---|
| a = 0.10 | 4.6% | 4.4% | 4.4% | 4.3% | 4.5% | 4.6% |
| a = 0.25 | 7.0% | 6.5% | 6.7% | 6.4% | 6.7% | 6.8% |
| a = 0.40 | 9.0% | 8.7% | 9.0% | 8.7% | 8.7% | 9.1% |
| a = 0.55 | 10.5% | 10.2% | 10.9% | 10.3% | 10.5% | 10.9% |
| a = 0.70 | 12.2% | 12.1% | 13.0% | 12.2% | 12.4% | 13.3% |
| a = 0.85 | 14.2% | 14.0% | 14.7% | 14.0% | 14.2% | 14.7% |
| mean of the six levels | 9.6% | 9.3% | 9.8% | 9.3% | 9.5% | 9.9% |

**ENB (effective number of bets) of the selected mix.** Rows: risk level a. Columns: the six mixes.

| Risk level | 1 frontier | 2 U1 | 3 lowest sim. drawdown | 4 crash penalty | 5 most loss contributors | 6 app's Optimized point |
|---|---|---|---|---|---|---|
| a = 0.10 | 12.04 | 11.90 | 10.90 | 11.64 | 15.91 | 16.86 |
| a = 0.25 | 11.87 | 11.77 | 10.96 | 11.46 | 14.33 | 16.47 |
| a = 0.40 | 11.70 | 11.56 | 11.36 | 11.62 | 13.47 | 15.64 |
| a = 0.55 | 11.59 | 11.56 | 11.19 | 11.55 | 13.04 | 14.89 |
| a = 0.70 | 11.61 | 11.71 | 11.24 | 11.76 | 12.72 | 14.49 |
| a = 0.85 | 11.77 | 11.95 | 11.71 | 11.90 | 12.70 | 14.04 |
| mean of the six levels | 11.76 | 11.74 | 11.23 | 11.65 | 13.69 | 15.40 |

### Realized volatility beside drawdown (§5.1)

Every mix at one risk level has the same model volatility, yet realized drawdowns differ: losses that come together compound into deeper troughs (order); a mix holding something that rises in a crash falls less (crash co-movement); at equal volatility a higher return lowers drawdown (drift); and mixes at the same estimated volatility realize different volatilities (estimated versus realized). Rows: risk level a. A drawdown gain with the same realized volatility points to a better path shape; one with lower realized volatility points to lower realized risk.

| Risk level | Arm 1 volatility | Arm 3 volatility | Arm 1 drawdown | Arm 3 drawdown |
|---|---|---|---|---|
| a = 0.10 | 5.0% | 4.9% | 4.6% | 4.4% |
| a = 0.25 | 7.6% | 7.4% | 7.0% | 6.7% |
| a = 0.40 | 9.9% | 9.8% | 9.0% | 9.0% |
| a = 0.55 | 12.0% | 12.2% | 10.5% | 10.9% |
| a = 0.70 | 14.4% | 14.5% | 12.2% | 13.0% |
| a = 0.85 | 17.0% | 16.9% | 14.2% | 14.7% |

## Other mixes against the frontier mix, and arm 3 against each (descriptive)

The same statistics as the test, read as a description only (no other comparison was tested). Averaged over the six risk levels, then origins. Drawdown difference: comparator minus mix (positive: the mix fell less); return difference: mix minus comparator.

| Mix | Against | Drawdown difference pp (95%) | Return difference bp (95%) | Return lower bound bp | Read against the test's lines |
|---|---|---|---|---|---|
| U1 mix (arm 2) | frontier mix (arm 1) | +0.30 [-0.10, +0.77] | -43.1 [-75.6, -7.1] | -71.8 | fail (both) |
| lowest-simulated-drawdown mix (arm 3) | U1 mix (arm 2) | -0.47 [-1.01, -0.02] | -192.5 [-282.9, -117.0] | -265.3 | fail (both) |
| crash-penalty mix (arm 4) | frontier mix (arm 1) | +0.28 [-0.26, +0.93] | -6.0 [-58.9, +53.8] | -52.3 | fail (both) |
| lowest-simulated-drawdown mix (arm 3) | crash-penalty mix (arm 4) | -0.46 [-1.00, +0.01] | -229.6 [-356.3, -124.7] | -336.8 | fail (both) |
| most-loss-contributors mix (arm 5) | frontier mix (arm 1) | +0.10 [-0.20, +0.37] | -6.7 [-55.4, +45.9] | -48.7 | fail (drawdown) |
| lowest-simulated-drawdown mix (arm 3) | most-loss-contributors mix (arm 5) | -0.27 [-0.89, +0.38] | -228.9 [-321.2, -149.9] | -304.0 | fail (both) |
| app's Optimized point (arm 6) | frontier mix (arm 1) | -0.30 [-0.93, +0.25] | +1.3 [-103.1, +102.6] | -87.2 | fail (both) |
| lowest-simulated-drawdown mix (arm 3) | app's Optimized point (arm 6) | +0.12 [-0.56, +0.92] | -237.0 [-349.9, -130.6] | -332.9 | fail (both) |

## Diversification of the selections (§5)

Lowest-simulated-drawdown mix (arm 3) minus frontier mix (arm 1), over every origin-and-risk-level cell: ENB -0.54 (arm 3 higher in 36.4% of cells), diversification ratio squared -0.08, effective number of loss contributors -0.21.

Rows: the mixes; averaged over the six risk levels.

| Mix | ENB | Diversification ratio squared | Loss contributors (ENLC) | Model return | Simulated tail drawdown |
|---|---|---|---|---|---|
| frontier mix (arm 1) | 11.76 | 2.67 | 3.72 | 11.1% | 18.5% |
| U1 mix (arm 2) | 11.74 | 2.62 | 3.95 | 10.8% | 17.3% |
| lowest-simulated-drawdown mix (arm 3) | 11.23 | 2.58 | 3.52 | 9.6% | 16.2% |
| crash-penalty mix (arm 4) | 11.65 | 2.56 | 3.90 | 10.6% | 17.2% |
| most-loss-contributors mix (arm 5) | 13.69 | 2.85 | 6.44 | 10.7% | 18.5% |
| app's Optimized point (arm 6) | 15.40 | 2.95 | 6.73 | 10.2% | 19.3% |

## Does the simulated drawdown ranking match the realized one? (§5)

At each origin and risk level, the six mixes are ranked by simulated tail drawdown and by realized drawdown; the figures are the mean rank correlation over origins. With six mixes a correlation is coarse, so read it as sign agreement: above 0 means the orderings agree more often than not. Rows: risk level a.

| Risk level | Spearman (95%) | Share above 0 | Kendall tau-b (95%) | Share above 0 |
|---|---|---|---|---|
| a = 0.10 | 0.21 [0.01, 0.40] | 60.3% | 0.19 [0.02, 0.35] | 59.8% |
| a = 0.25 | 0.15 [-0.03, 0.32] | 62.4% | 0.12 [-0.03, 0.26] | 60.3% |
| a = 0.40 | 0.05 [-0.12, 0.22] | 52.6% | 0.04 [-0.10, 0.18] | 51.3% |
| a = 0.55 | 0.04 [-0.12, 0.22] | 53.4% | 0.04 [-0.09, 0.18] | 50.9% |
| a = 0.70 | -0.02 [-0.18, 0.16] | 47.0% | -0.00 [-0.14, 0.14] | 47.4% |
| a = 0.85 | -0.01 [-0.22, 0.21] | 47.4% | 0.00 [-0.18, 0.18] | 47.4% |

## Regime buckets (descriptive)

Each origin's realized year is labelled: equity drawdown (SPY fell 15% or more inside the year), else rate shock (the 10-year Treasury yield rose 1.5 pp or more), else calm. Figures are averaged over the six risk levels, then over the origins in the bucket. Rows: regime.

| Regime | Origins | Drawdown: arm 1 | Drawdown: arm 3 | Drawdown difference pp | Return: arm 1 | Return: arm 3 | Return difference pp |
|---|---|---|---|---|---|---|---|
| equity drawdown | 95 | 14.2% | 14.6% | -0.45 | 3.5% | 0.6% | -2.93 |
| rate shock | 0 | n/a | n/a | n/a | n/a | n/a | n/a |
| calm | 139 | 6.5% | 6.5% | +0.02 | 10.0% | 8.1% | -1.96 |

Drawdown of every mix by regime. Rows: regime; columns: the mixes.

| Regime | 1 frontier | 2 U1 | 3 lowest sim. drawdown | 4 crash penalty | 5 most loss contributors | 6 app's Optimized point |
|---|---|---|---|---|---|---|
| equity drawdown | 14.2% | 13.8% | 14.6% | 13.7% | 14.3% | 15.3% |
| rate shock | n/a | n/a | n/a | n/a | n/a | n/a |
| calm | 6.5% | 6.2% | 6.5% | 6.3% | 6.2% | 6.2% |

## Longer horizons, inflation and costs (descriptive)

Compounded 2-, 3- and 5-year realized returns from the same origin where the years are complete, the real (inflation-adjusted) 1-year return, and the 1-year return net of 10 bp per unit of turnover. Rows: the mixes; averaged over the six risk levels.

| Mix | 1 year | 1 year net of costs | 1 year real | 2 years | 3 years | 5 years |
|---|---|---|---|---|---|---|
| frontier mix (arm 1) | 7.4% | 7.3% | 4.6% | 14.9% | 23.5% | 38.6% |
| U1 mix (arm 2) | 7.0% | 6.8% | 4.2% | 13.7% | 21.8% | 37.8% |
| lowest-simulated-drawdown mix (arm 3) | 5.0% | 4.9% | 2.3% | 10.5% | 17.9% | 33.6% |
| crash-penalty mix (arm 4) | 7.3% | 7.2% | 4.6% | 14.5% | 23.2% | 40.9% |
| most-loss-contributors mix (arm 5) | 7.3% | 7.2% | 4.6% | 14.5% | 23.2% | 39.3% |
| app's Optimized point (arm 6) | 7.4% | 7.3% | 4.6% | 14.7% | 23.9% | 42.1% |

## Side checks (descriptive)

**Crash-penalty weight (arm 4), showcase origins 2006-04, 2010-05, 2014-06, 2018-07, 2022-08, 2026-09.** Rows: the penalty weight (0.1 is the main setting); pooled over the six risk levels. Realized figures cover the origins with a complete year.

| Penalty weight | Cells | U1 | Worst historical fall | Sim. tail drawdown | Return | Drawdown | ENB |
|---|---|---|---|---|---|---|---|
| 0.05 | 36 | 3.4% | 29.0% | 17.7% | 10.8% | 7.8% | 11.50 |
| 0.10 | 36 | 3.3% | 27.8% | 17.7% | 10.8% | 7.8% | 11.51 |
| 0.20 | 36 | 2.9% | 24.5% | 17.5% | 10.8% | 7.6% | 11.59 |

**5-year lookback, origins 2010-05, 2014-06, 2018-07, 2022-08, 2026-09.** The app's own window. Rows: the mixes; pooled over the six risk levels; the 3-year figures are the same origins.

| Mix | Return 5y lookback | Return 3y lookback | Drawdown 5y lookback | Drawdown 3y lookback | ENB 5y lookback | ENB 3y lookback |
|---|---|---|---|---|---|---|
| frontier mix (arm 1) | 10.4% | 9.7% | 7.6% | 8.3% | 12.18 | 12.00 |
| U1 mix (arm 2) | 10.8% | 9.7% | 7.1% | 7.2% | 12.24 | 11.93 |
| lowest-simulated-drawdown mix (arm 3) | 10.2% | 8.9% | 7.3% | 6.6% | 11.22 | 10.99 |
| crash-penalty mix (arm 4) | 11.0% | 9.6% | 6.9% | 7.0% | 12.17 | 11.95 |
| most-loss-contributors mix (arm 5) | 10.2% | 9.6% | 7.5% | 7.5% | 14.03 | 14.07 |
| app's Optimized point (arm 6) | 10.1% | 9.1% | 7.7% | 7.7% | 15.48 | 15.32 |

**Independent simulation banks (§5).** The model figures of each selected mix on its training bank and averaged over five fresh banks; a gap shows how much of a simulated advantage is search noise on the training bank. Rows: the mixes; all origins and risk levels.

| Mix | Seeds | Sim. tail drawdown: training | independent | Bad year: training | independent | U1: training | independent |
|---|---|---|---|---|---|---|---|
| frontier mix (arm 1) | 5 | 18.5% | 18.5% | -8.7% | -8.7% | 1.6% | 1.5% |
| U1 mix (arm 2) | 5 | 17.3% | 17.3% | -7.3% | -7.8% | 2.1% | 1.8% |
| lowest-simulated-drawdown mix (arm 3) | 5 | 16.2% | 16.2% | -7.6% | -7.7% | 1.1% | 1.1% |
| crash-penalty mix (arm 4) | 5 | 17.2% | 17.2% | -7.5% | -7.9% | 1.9% | 1.6% |
| most-loss-contributors mix (arm 5) | 5 | 18.5% | 18.5% | -8.9% | -9.0% | 1.2% | 1.2% |
| app's Optimized point (arm 6) | 5 | 19.3% | 19.3% | -9.9% | -10.0% | 0.4% | 0.4% |

## Selection-bias diagnostics: CSCV and deflated Sharpe ratio (§7.1, §7.2)

**Purged CSCV across the six mixes** (score: mean realized drawdown over the six risk levels, lower is better; omega = k/7). Splits evaluable: 35 of 70. PBO not computable: 35 of 70 splits evaluable (minimum 50). The protocol expected about 35 of 70 splits, below the 50-split minimum; the rule is not relaxed.

| Mix | Chosen in training |
|---|---|
| frontier mix (arm 1) | 14.3% |
| U1 mix (arm 2) | 20.0% |
| lowest-simulated-drawdown mix (arm 3) | 5.7% |
| crash-penalty mix (arm 4) | 40.0% |
| most-loss-contributors mix (arm 5) | 5.7% |
| app's Optimized point (arm 6) | 14.3% |

**Deflated Sharpe ratio**, a diagnostic, never a gate: the drawdown difference of arm 3 against arm 1 on the 19 disjoint realized years, deflated for the five trials (arms 2-6 against arm 1). DSR 0.072; Sharpe ratio -0.224, benchmark 0.151, effective trials 2.40.

## Labels, failures, overrides and amendments (§4.5, §8.4)

Usable warnings (counted): ok, insufficient_starts, growth_bound_failed, knee_collapsed. Verdict-blocking failures: search_failed, anchor_failed, no_eligible (arm 5 only, not tested).

| Label | Selection rows |
|---|---|
| ok | 15204 |

Task failures recorded by the job: 0.


Owner overrides: 0.


Amendments in the parent manifest: 0.


## EXPLORATORY: post-hoc ensemble screen (§7.3)

**EXPLORATORY.** Exploratory screen (protocol v3 §7.3): computed after the confirmatory result was written and its digest recorded; it cannot change the v3 verdict or the decision rule, and a promising combination is a hypothesis for a new preregistered protocol, not a finding.

How it works: at each origin and risk level, every distinct mix that any search visited inside the ±1% risk band is ranked on six objectives (model return, U1, low simulated drawdown, low worst historical fall, loss contributors, ENB); each of the 126 weightings of those ranks (steps of 0.25) picks one mix, and its realized outcomes are compared with the frontier mix exactly as in the test. Limit: the screen can only pick among mixes the six mixes' searches visited.

Candidates per origin and risk level: median 2134, minimum 1091, maximum 3373 (1404 of 1404 cells filled); distinct mixes picked: 74092. Objectives added after seeing results: none.

**0 of 126 weightings would meet both of the test's conditions on these years.** With 126 tries on the same years, some will look good by chance; the CSCV and deflated Sharpe ratio below estimate how much.

Ten weightings with the largest drawdown improvement. Rows: weightings; averaged over the six risk levels, then origins; against the frontier mix.

| # | Weights | Drawdown difference pp (95%) | Return difference bp (95%) | Return lower bound bp | Read against the test's lines |
|---|---|---|---|---|---|
| 68 | U1 0.75, low sim. drawdown 0.25 | +0.31 [-0.12, +0.83] | -64.2 [-108.2, -17.4] | -101.7 | fail (both) |
| 103 | model return 0.25, U1 0.50, low sim. drawdown 0.25 | +0.31 [-0.07, +0.75] | -39.8 [-77.1, -1.0] | -72.3 | fail (both) |
| 69 | U1 1.00 | +0.30 [-0.10, +0.77] | -43.1 [-75.6, -7.1] | -71.8 | fail (both) |
| 67 | U1 0.75, low worst historical fall 0.25 | +0.29 [-0.20, +0.89] | -27.2 [-62.0, +8.3] | -57.4 | fail (both) |
| 102 | model return 0.25, U1 0.50, low worst historical fall 0.25 | +0.27 [-0.18, +0.80] | -16.1 [-44.9, +11.6] | -39.6 | fail (drawdown) |
| 95 | model return 0.25, U1 0.25, low worst historical fall 0.50 | +0.26 [-0.29, +0.87] | -20.1 [-62.9, +20.8] | -54.7 | fail (both) |
| 98 | model return 0.25, U1 0.25, low sim. drawdown 0.25, low worst historical fall 0.25 | +0.25 [-0.27, +0.87] | -37.4 [-79.3, +5.3] | -73.8 | fail (both) |
| 65 | U1 0.75, ENB 0.25 | +0.24 [-0.17, +0.65] | -35.9 [-81.3, +12.8] | -76.7 | fail (both) |
| 104 | model return 0.25, U1 0.75 | +0.24 [-0.09, +0.60] | -26.7 [-53.4, +1.4] | -49.7 | fail (drawdown) |
| 118 | model return 0.50, U1 0.25, low sim. drawdown 0.25 | +0.22 [-0.07, +0.56] | -33.0 [-65.7, -1.3] | -60.1 | fail (both) |

**CSCV over the 126 weightings** (score: mean realized drawdown, lower is better; omega = k/127): 35 of 70 splits evaluable; PBO not computable: 35 of 70 splits evaluable (minimum 50); mean test rank of the training choice 39.5 of 126.

**Deflated Sharpe ratio with 126 trials** on 19 disjoint years, primary trial #107 (model return 0.50, loss contributors 0.50): DSR 0.913; Sharpe ratio 0.376, benchmark 0.085.

## EXPLORATORY: region check (addendum of 2026-11-09)

Written by hand from `fr-run-v3/analysis/region_check.json` (code at commit `0a69305`); `v3-report` does not regenerate this section. Specification, with eight dated corrections made before the run: `docs/plans/2026-11-09-fixed-risk-v3-region-check.md`. It reuses the 234 start months of the confirmatory test, so nothing here is a finding.

**Question.** Drop the fixed-risk constraint. Take every recorded mix whose model return is at most 50 bp below the frontier mix's and whose volatility is at or below the risk line. Does a mix picked there by simulated drawdown, by ENB, by the worst historical fall, or by a blend of them, fall less in the following year than simply lowering the risk setting?

**Yardstick (L).** The frontier mix moved toward the frontier mix one risk setting lower, far enough to give up 50 bp of model return (on average 44% of the way; the full step in 12% of cells). The lowest risk setting has no lower neighbour, so comparisons against L use 1,170 of the 1,404 cells. Against the frontier mix, L fell 0.81 pp less and returned 33 bp less in the following year (means, no interval computed).

**Outcome: decision rule 1, closed.** The best mix of each region picked with hindsight (one of a median 636 mixes per cell, range 17 to 3,127) fell 0.77 pp less than L, 95% interval [0.40, 1.12]. The bar fixed in advance was 1 pp. No mix in the region, even picked with hindsight, beats lowering the risk setting by that much. Rules 2 and 3 were not reached; the best of the 15 rules in hindsight was the lowest-simulated-drawdown rule, and it did not beat L either.

Averages over cells. Drawdown difference is in pp, positive = the pick fell less, with its 95% interval. Return difference is in bp with its one-sided 95% lower bound in brackets.

| Pick inside the region | Drawdown vs L | Return vs L | Drawdown vs frontier | Return vs frontier | Model volatility % | ENB | Share below the risk line |
|---|---|---|---|---|---|---|---|
| Best mix in hindsight (upper bound) | +0.77 [+0.40, +1.12] | +136 [+99] | +1.48 [+1.03, +1.91] | +98 [+60] | 11.06 | 12.3 | 42% |
| Lowest simulated drawdown | -0.21 [-0.57, +0.15] | -24 [-55] | +0.57 [+0.18, +0.99] | -51 [-78] | 10.74 | 11.6 | 58% |
| Lowest worst historical fall | -0.35 [-0.86, +0.13] | +34 [-24] | +0.43 [-0.05, +0.93] | +3 [-35] | 10.88 | 11.8 | 42% |
| Half simulated drawdown, half ENB | -0.50 [-1.02, -0.11] | -3 [-58] | +0.32 [-0.01, +0.63] | -31 [-69] | 11.01 | 12.8 | 50% |
| Highest ENB | -0.78 [-1.34, -0.28] | +45 [-26] | +0.04 [-0.26, +0.35] | +11 [-37] | 11.38 | 14.4 | 4% |
| Lowest simulated drawdown, same risk line only | -0.61 [-1.20, -0.10] | -15 [-70] | +0.23 [-0.15, +0.67] | -44 [-88] | 11.43 | 11.7 | 0% |

The frontier mix's own averages: model volatility 11.48%, realized drawdown 9.60%, realized return 7.40%.

Reading it:

- The lowest-simulated-drawdown pick does fall less than the frontier mix (0.57 pp, interval above zero), but 58% of those picks sit below the risk line. It gets there by taking less risk, and it costs 51 bp of realized return. Lowering the risk setting buys more (0.81 pp) for less (33 bp).
- Held to the same risk line, the same pick shows no reliable drawdown gain over the frontier mix (0.23 pp, interval includes zero).
- The highest-ENB pick raises ENB from about 11.8 to 14.4 at the same realized return and the same realized drawdown as the frontier mix. It neither helps nor hurts.

By risk setting (descriptive, means, no intervals):

| Risk setting | Frontier drawdown % | L: drawdown saved pp | L: return given up bp | Best mix in hindsight vs L pp | Lowest simulated drawdown vs L pp | Highest ENB vs L pp |
|---|---|---|---|---|---|---|
| 0.10 | 4.60 | no L | no L | no L | no L | no L |
| 0.25 | 7.02 | 0.74 | 30 | +0.66 | -0.27 | -0.33 |
| 0.40 | 9.00 | 0.70 | 38 | +0.85 | -0.12 | -0.43 |
| 0.55 | 10.53 | 0.64 | 42 | +0.95 | -0.09 | -0.69 |
| 0.70 | 12.24 | 0.90 | 36 | +0.67 | -0.29 | -1.26 |
| 0.85 | 14.20 | 1.09 | 20 | +0.74 | -0.28 | -1.21 |

**Can the model rank mixes at all?** Among mixes on the same risk line (at least 20 per cell, 1,404 cells), the rank correlation between simulated tail drawdown and realized drawdown averaged -0.01, 95% interval [-0.14, +0.14], and was above zero in 50% of cells. Simulated drawdown did not rank same-risk mixes by how far they fell. Model return against realized return averaged +0.16 [+0.04, +0.29], above zero in 63% of cells: a weak signal, but a real one.

**Separate test of the search.** On a made-up menu with a planted crash hedge and a decoy of equal volatility, model return and covariance, the lowest-simulated-drawdown search bought the hedge and not the decoy (`tests/research/fixedrisk/test_crash_hedge.py`). So the search and the measure do see crash behaviour when the lookback holds it. The correlation above says that what they saw in the 3-year lookbacks of this history did not carry over to the following year.

Housekeeping: 128,654 main-pool rows that break a fund's bounds were left out; no allowed row lacked a model measure. A mix counts as "same risk line" when it was recorded in the wide band under that cell's own risk setting.

## Limits stated by the protocol

- **What preregistration covers (§1).** v3 reuses the frozen history of v2, and its arms were chosen after the owner saw v2's realized results. The thresholds (1 pp, 50 bp, 95%) were chosen after v2's realized intervals on these years were seen; v2's realized-support rule used a 99% lower bound.
- **Replay understates long falls (§2.3).** History replay strings together runs of about 21 days, so it keeps losses that cluster within a month and breaks a longer bear market into pieces. Simulated drawdowns therefore understate multi-month falls, which is why a replay pass must be confirmed under GARCH.
- **Short crash history before 2009 (§2.4).** The history behind the worst historical fall starts in 2003 (EEM's first price). Origins before late 2008 hold no complete major crash, so the crash penalty (arm 4) mostly reflects the milder dips of 2003-2007 there.
- **Arm 6 is the app's method on the experiment's settings (§2.7).** The menu and caps are the experiment's (research2003, 40% per fund, 10% per stock) and the lookback is 3 years where the app uses 5; the 5-year side check is where arm 6 uses the app's window. Its frontier node sits exactly on the risk line and can differ slightly from arm 1, which may sit anywhere in the ±0.1% band.
- **Daily versus monthly rebalancing (§11 item 8).** Simulated paths are rebalanced daily, realized outcomes monthly; the mismatch is assumed small next to a 1 pp line. This is an assumption, not a measured result.
- **Dependent origins (§6.2).** Neighbouring origins share up to eleven of twelve realized months and 35 of 36 lookback months; only 19 realized years are disjoint. The intervals assume this dependence dies out within about 24 origins, and the false-pass rate is nominal under that assumption.
