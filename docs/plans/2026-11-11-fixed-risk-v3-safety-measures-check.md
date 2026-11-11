# Fixed-risk experiment v3: other safety measures (exploratory addendum 2)

Date: 2026-11-11. Approved by the owner on 2026-11-11 ("1. a"). Written and committed before any
of the new measures below is computed on real data.

## Question

Every test so far changed how a mix is picked and judged it the same way: the average fall and
return over the following year. The owner's question: is a more diversified mix safer than the
frontier mix on a measure of safety we have not looked at, for about the same return?

This check changes only how the outcome is measured. The mixes are the ones run `fr-run-v3` (job
`research2003_replay`) already recorded. No new simulation. It is the fourth look at the same 234
start months, so every result is exploratory and none of it is a finding.

## What was already known when this was written

One-year average return, drawdown and realized volatility of each arm; the calm and crisis split;
and the v3 report's table of 2-, 3- and 5-year compounded returns without intervals (frontier mix
38.6% over 5 years, the app's Optimized point 42.1%). None of the measures below had been computed.

## Mixes

- **F**: the frontier mix (arm 1), per cell (start month and risk setting; main settings only:
  3-year lookback, main seed, main penalty weight).
- **E**: the app's Optimized point (arm 6), the more diversified mix the app shows today. The
  pass/fail tests compare E with F.
- Described only, no pass/fail: arms 2, 3, 4 and 5; the region check's ENB pick (rule `(0, 1, 0)`,
  the highest ENB among the region's mixes); and the region check's yardstick L (the frontier
  moved 50 bp of model return toward the next lower risk setting; no L at setting 0.10).

Every mix is fixed by model quantities at the start month. No pick uses a realized outcome.

## Outcomes, per cell

All use the monthly-rebalanced convention of `realized.monthly_rebalanced` without costs, from the
mix's weights, starting at the start month.

1. **Long-horizon fall**, for H = 3 and 5 years: the maximum drawdown over the first `H * 252`
   sessions (peak floored at the starting value, as the one-year drawdown is).
2. **Longest time under water**, for H = 3 and 5 years: the longest run of consecutive sessions
   on which wealth is below its running peak (same floor), in months of 21 sessions. A run still
   open at the end of the window counts up to the end.
3. **Compounded return** over H = 3 and 5 years (already recorded; this check adds intervals).
4. **Surprise against the promise**, one year: `|realized return - mu|` and
   `|realized volatility - sigma|`, with `mu` and `sigma` the model's figures for the mix. The
   signed gaps are reported too.
5. **Worst years**: not per cell. For one mix and one risk setting, the tail fall is the mean of
   the largest 10% (rounded up) of its one-year realized drawdowns over the start months; the tail
   return is the mean of its lowest 10% of one-year realized returns. Each is then averaged over
   the six risk settings. Each mix is ranked on its own outcomes, so no mix is selected for having
   done badly.

A cell enters an H-year outcome only when all `H * 252` sessions exist for it.

## Statistics

Paired differences against F, averaged as the region check averages them, with the same
moving-block bootstrap over start months (2,000 resamples, seed 20261201). The block is 24 months
for one-year outcomes, 36 for 3-year and 60 for 5-year outcomes, because windows that overlap are
not independent. The worst-years difference recomputes both mixes' tail means inside each
resample. Signs: a positive fall, time or surprise difference means the mix did better than F
(fell less, was under water for less time, surprised less); a return difference is mix minus F.

Reported for every mix and outcome: the mean, the difference against F and its two-sided 95%
interval, and the number of start months used. For returns also the one-sided 95% lower bound.

## Pass/fail tests, fixed now (E against F only)

| Test | Outcome | Bar | Return condition |
|---|---|---|---|
| P1 | 5-year fall | E falls at least 1.0 pp less | 5-year return, lower bound at least -2.5 pp |
| P2 | 5-year longest time under water | E at least 3.0 months shorter | same as P1 |
| P3 | Worst years, tail fall | E at least 1.0 pp less | one-year return, lower bound at least -50 bp |
| P4 | Return surprise | E at least 0.5 pp smaller | same as P3 |

Four tests, so each uses a two-sided 98.75% interval. Each test gets one label:

- **lead**: the difference reaches the bar, its 98.75% interval is above 0, and the return
  condition holds.
- **inconclusive**: the difference reaches the bar, but the interval includes 0 or the return
  condition fails.
- **no**: the difference is below the bar.

A 5-year test with fewer than 120 usable start months is labelled inconclusive whatever it shows.

## Decision rules, fixed now

1. At least one lead: still not a finding. That measure alone becomes a candidate for one
   confirmation on the held-out TSP menu, which needs a new run. The owner decides.
2. No lead and at least one inconclusive: closed as not provable with this history. No further
   experiment on these start months.
3. All four "no": closed. A more diversified mix gave no protection on these measures either.

The 3-year outcomes, the volatility surprise, the tail return and every mix other than E are
description. Nothing in them changes the decision.

## Limits known in advance

- Five-year windows from monthly start months overlap almost entirely. About 20 years of history
  hold about three or four independent 5-year periods, so a 5-year interval is rough even with a
  60-month block, and a 5-year lead is weak evidence.
- One menu, one lookback, the replay engine.
- The return surprise of E is smaller than F's by construction to the extent that E's model return
  is lower and the realized returns are equal; the report says how much of any P4 difference that
  explains.

## Output

`fr-run-v3/analysis/safety_check.json` from a new command `v3-safety`, and a hand-written section
in the v3 report.
