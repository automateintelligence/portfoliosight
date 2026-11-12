# Fixed-risk experiment v3: simple and diversification-driven recipes (exploratory addendum 3)

Date: 2026-11-11. Question approved by the owner on 2026-11-11 ("4 a"). Written and committed
before any realized outcome of a new mix is computed; revised the same day after review round 1
(the review log at the end), still before any realized outcome of a new mix was computed. The
decisions at the end are open; the run starts only after the owner answers them, and an answer
that changes the design is recorded here as a dated correction before any realized outcome is
read.

## Question

On the research2003 portfolio, can a simple recipe or a diversification-driven recipe beat the
frontier mix at the same risk? Five mixes, per start month:

1. **F**, the frontier mix with the weight limits (40% per fund, 10% per stock): the reference.
2. **U**, the frontier mix with no weight limits, at the same risk as F.
3. **E**, equal weight.
4. **D**, the most-diversified mix: the highest diversification ratio (Choueifaty and Coignard
   2008, `docs/research/TOBAM-JoPM-Maximum-Div-2008.pdf`).
5. **V**, the lowest-volatility mix.

Mixes E, D and V each sit at one risk per start month. Each is compared with the frontier mix with
the weight limits at that same risk, and described on its own. U against F asks whether the weight
limits themselves are the diversification that matters. Market-value weighting is out of scope:
the repository has no market-value data.

This check needs no simulation bank: every mix is fixed by the start month's expected returns,
covariance and bounds alone. It reuses the 234 start months of the v3 confirmatory test, the
region check and the safety-measures check, so it is the fifth look at the same months: every
result is exploratory and none of it is a finding. The TSP portfolio stays held out and is not run.

Vocabulary: the code calls the weight limits "caps" (`engine/caps.py`, `menus.FUND_CAP`,
`menus.STOCK_CAP`); this document says weight limits.

## What was already known when this was written

- F's realized outcomes at the six risk settings (v3 report): one-year return 7.4% and fall 9.6%
  averaged over the settings; by setting, falls from 4.6% (0.10) to 14.2% (0.85).
- v2: at a fixed risk, moving the mix from the frontier toward the most-diversified mix *at that
  risk* (the slider bottom, `anchors.column_anchors`'s `w_MDP`) made the realized fall worse on
  both menus. D in this check is a different object: the most-diversified mix over the whole
  domain, at its own risk, compared with the frontier at that risk.
- The region check: no recorded mix picked by simulated drawdown, ENB or their blend beat the
  frontier moved to a lower risk setting (the yardstick L). The highest-ENB pick neither helped nor
  hurt.
- The safety-measures check: the app's Optimized point did not beat F on the 5-year fall, time
  under water, worst-years fall or return surprise. Only L, the frontier at lower risk, fell less.
- Nothing is known about the realized outcomes of U, E, D or V on this history. The harness uses
  equal weight and the minimum-variance mix only as solver starts (`anchors._anchor_starts`).

## Inputs, fixed

- Run `fr-run-v3`, job `research2003_replay`: the parent manifest, its schedule of 246 start months
  (2006-04 to 2026-09), the 234 eligible start months with a complete realized year, and the
  locked selections (`analysis3.locked_rows`), read only.
- Snapshot `2026-10-16-b0ef68baceaa`, read only, for the training side of each start month
  (`data.origin_context`, lookback `3y`) and the realized prices after it (the `horizon` and
  `span` callables `v3-safety` uses).
- Per start month, from the training side only: expected returns `mu_s` (the production
  `menu_beta_blend`), covariance `Sigma`, fund volatilities `sigma_i`, and the weight limits
  `lo = 0`, `hi = 0.40` for the eleven funds and `hi = 0.10` for the eight stocks
  (`menus.RESEARCH2003`). Model risk of a mix: `sigma(w) = sqrt(w' Sigma w)`.
- `sigma_min` and `sigma_top` of the limited domain (the minimum-variance risk and the risk of the
  max-`mu_s` greedy fill), as recorded in the anchors; the six settings `r = X(a)`,
  `a in {0.10, 0.25, 0.40, 0.55, 0.70, 0.85}`.
- The **risk position** of a mix, `a(w) = (sigma(w) - sigma_min) / (sigma_top - sigma_min)`,
  places it on the same axis as the six settings. Reported for every mix (mean, median, 5th and
  95th percentile over start months) with the nearest recorded setting; a start month with
  `a(w) > 1` (the mix's risk is above the frontier's top) has no nearest setting and is reported
  as "above the top", with the count of such months (the exclusion rule below).
- **Model-side check already run.** Before this revision, a model-only script (no realized
  outcome computed) read the snapshot and the recorded columns for all 246 start months:
  `sigma(E)`, the limited and unlimited tops, `a(E)`. Its results are written out in full below
  (the excluded-month lists and counts), so this document does not depend on the script. The
  script is not committed with this document (documentation only goes straight to main); the
  implementation PR adds it as `scripts/fixedrisk_geometry_check.py` with tests, and the run
  must reproduce its lists (the list gate below).

## How each mix is built, per start month

All from the 3-year lookback of the start month, as v3. The two engine functions below are the
app's: `MenuPrograms.frontier_point(x)` solves the frontier program at any risk ceiling `x`, not
only on the app's 48-column grid or the six settings (`engine/optimize.py:83-86`), and
`optimize.onto_risk` moves an answer that sits inside its ceiling onto the risk line. The v3 side
columns already used both at the six settings (`knee.side_frontier_node`, knee.py:67-76). So a
frontier mix can be built at an arbitrary risk; nothing restricts it to the six settings.

**Exact-line frontier mix with the limits, `F(s)`, at any risk `s`.** New code from those pieces:

1. `s <= sigma_min + TOL` (`optimize.TOL = 1e-6`): `F(s)` is the minimum-variance mix.
2. `s >= sigma_top - TOL`: the frontier has no node above `sigma_top` (the greedy fill's risk,
   which is not the domain's maximum risk), so no frontier mix exists at that risk; a comparison
   with the greedy fill would pair mixes of different risk. The cell is **excluded** from every
   paired statistic and test, counted and reported (the exclusion rule below).
3. Otherwise `programs.frontier_point(s)`, then `onto_risk` toward the greedy fill when the answer
   sits more than `TOL` inside the ceiling, so that `|sigma(F(s)) - s| <= TOL`. The **tolerance
   of the match is `1e-6` absolute** in annual volatility, far inside v3's narrow band
   (`0.001 r`). The achieved gap is reported (mean, maximum, count above `TOL`); a cell above
   `TOL` after one Clarabel retry ladder (`optimize.solve_with_retries`) is a failed cell: the
   mix's comparison is left out and counted, and more than 1% failed cells for any mix stops the
   run.

Reconstruction check, before any realized outcome is read: at the six settings of every start
month, `F(X(a))` must match the recorded `app_frontier` row (v3 §4.3 step 5, the exact-line
reference) in model return and risk: `|mu_s'F - mu_s'w_app| <= 1e-6` and
`|sigma(F) - sigma(w_app)| <= 1e-6`. More than 1% of cells outside that stop the run. The weight
distance is reported, not gated: the count of cells with L1 `> 1e-4`. Why not the weights:
`app_frontier` was built by `knee.side_frontier_node` (knee.py:67-76), which also applies
`optimize.frontier`'s left-node correction; on a flat frontier two mixes with the same return and
risk can differ in weights, and that is not an implementation error. Reproducing the correction
would cost one 48-column frontier per start month (about 46 extra programs each) for a check of
weights the test does not depend on.

**Mix 1, F.** At the six settings: the recorded `app_frontier` row (exact line), with the recorded
arm 1 row (narrow band, the v3 comparator) reported beside it; the v3 report shows the two agree
to 0.01 pp in realized return and fall. At any other risk: `F(s)` above.

**Mix 2, U, the frontier with no weight limits.** Bounds `lo = 0`, `hi = 1` on all 19 holdings,
`MenuPrograms(mu_s, Sigma, 0, 1)`; built by the same three steps at `s = r = X(a)` for the six
settings of the limited geometry (the cell's recorded `r`), with the unlimited minimum-variance
mix and the unlimited greedy fill (100% in the top-`mu_s` holding) as the two ends. The unlimited
top can sit **below** the limited top: it is one holding, and when the top-`mu_s` holding has low
volatility its risk is under that of the limited greedy fill, which spreads 40% slices over
several holdings. The model-side check found this in 5 of 246 start months (2008-09, 2010-08,
2010-10, 2012-09, 2014-01) and the unlimited top below `X(0.85)` in two (2008-09, 2010-08). A U
cell with `r >= sigma_top_U - TOL` is excluded and counted (the exclusion rule below). U is
long-only. Comparator: mix 1 at the same cell. Both sit on the same line within `TOL`, so the match
tolerance is `2e-6`.

**Mix 3, E, equal weight.** `w_i = 1/19` for every holding, every start month. It lies inside the
limits (5.26% is under 10%), so it is a mix of the limited domain. Risk `sigma(E)`; comparator
`F(sigma(E))`.

**Mix 4, D, the most-diversified mix.** `argmax DR(w) = (sigma' w) / sqrt(w' Sigma w)` over
`{lo <= w <= hi, 1'w = 1}`, the paper's program under the menu's weight limits. The harness only
has the fixed-risk version (`anchors.column_anchors`'s `w_MDP` on a band, v2's slider bottom);
the global one is new code, one convex program via the paper's synthetic-asset form: minimize
`y' Sigma y` subject to `sigma' y = 1`, `y >= 0` and `y_i <= hi_i (1' y)` (the limits are linear
in `y`), then `w = y / (1' y)`; Clarabel through `optimize.solve_with_retries`. Risk `sigma(D)`;
comparator `F(sigma(D))`.

Checks on D before any realized outcome is read: (a) with `lo = 0`, `hi = 1` (the paper's
long-only setting; example 2's 48.6% would break a 40% limit), on the paper's example 2 (three
holdings of equal volatility, two correlated at 0.9 and a third at 0.1 with each) the program gives
25.7%, 25.7%, 48.6% within 0.1 pp, and on example 1 (two holdings, volatilities 15% and 30%, any
correlation below 1) 66.7% and 33.3%; (b) at every start month, `DR(D)^2` is at least the largest
`DR^2` recorded for any allowed main-pool mix of that month (`region3.distinct_mixes`, the `dr2`
column v3 recorded for every evaluated mix, objectives3.py:49) minus `1e-6`. One start month
failing (b) stops the run: the optimizer is wrong, not the pool. The recorded anchors cannot
serve here: the v3 harness solved only the frontier anchor `w_F` (search3.py, `COLUMN_SCHEMA` in
driver3.py:72-99 holds no `w_MDP` or `M_MDP`). Re-solving `anchors.column_anchors` per month would
add 18 SLSQP programs from eight starts each for a weaker check than the pool's millions of
recorded mixes already give, so the anchor clause is dropped rather than recomputed.

The weight limits in D: the paper limited each security to 10% and each asset's risk contribution
to 4%. The main D uses the menu's limits, the same as every other mix, so that the comparison is
between recipes, not between limit rules (decision 2). A variant **D10** with `hi = 0.10` on all
19 holdings (feasible: the limits sum to 190%) is built and described beside D, no test. The 4%
risk-contribution limit is not reproduced.

**Mix 5, V, the lowest-volatility mix.** `programs.min_variance()` under the limits: the
minimum-variance mix, risk `sigma_min`. **Its matched comparison is an identity and is not run:**
the frontier with the limits at risk `sigma_min` is V itself (`optimize.frontier` pins its first
node to the minimum-variance mix, and the mix under that ceiling is unique for a positive-definite
covariance). Removing the limits does not help: the unlimited lowest-volatility mix is likewise the
bottom of the unlimited frontier. V is therefore described only: its own outcomes, its risk
position (`a(V) = 0` by definition), and its paired difference against F at the lowest recorded
setting `a = 0.10` (a description of what the last step down the risk axis buys, the v3
yardstick's direction). No pass/fail test.

Every mix is fixed by model quantities at the start month; no choice uses a realized outcome.

**Cells at or above a frontier's top: excluded.** For E, D and D10, every cell with
`sigma(M) >= sigma_top - TOL` (the limited top) is left out of the paired statistics and the
tests; for U, every cell with `r >= sigma_top_U - TOL` (the unlimited top). Each mix's excluded
cells are counted and listed. Expected counts, pre-registered from the model-side check:

- E: 25 of 234 eligible start months (10.7%), the full pre-registered list: 2008-11, 2008-12,
  2009-01, 2009-02, 2009-03, 2009-04, 2009-05, 2009-06, 2009-07, 2009-08, 2009-09, 2009-10,
  2009-11, 2009-12, 2010-01, 2010-02, 2010-03, 2010-04, 2010-05, 2010-06, 2010-08, 2010-09,
  2010-10, 2020-03, 2020-05. In 2008-11 to 2009-04 equal weight sits at 21.7% to 26.4% model
  risk while the limited greedy fill sits at 7.3% to 8.4% (the top-`mu_s` holdings then were XOM
  and TLT), so without this rule T4 to T6 would pair a 22%-risk mix with a 7%-risk one. All 25
  fall before 2021-09, so E keeps 161 of the 186 five-year start months (above the 120 floor).
- U: at least 2 of 1,404 cells, the pre-registered cells (2008-09, a = 0.85) and
  (2010-08, a = 0.85); the lower settings of those months are checked by the run.
- D and D10: 0 expected (low-risk mixes); reported.

**List gate.** The run's excluded months for E must equal the 25 listed, and its excluded U
cells must include the two named; otherwise the run stops and reports, because the training side
it rebuilt differs from the one this document was written against.

**The 15% share.** A mix's excluded share is counted once, over its one-year cells: 234 for E, D
and D10, 1,404 for U. A mix whose share exceeds **15%** has every one of its tests labelled
inconclusive, whatever they show (E's expected share is 10.7%; over its five-year cells alone it
would be 13.4%, which is why the base is fixed here); the described figures are still reported
on the remaining cells. The excluded months are also described on their own (the mix's outcome
and risk), with no comparator.

**Model-side gates, before any realized outcome is read.** They guard against a "no" that is
really an identity:

- at every kept U cell, `mu_s'U >= mu_s'F - 1e-6`, F the cell's `app_frontier` row: removing
  the limits cannot lower the model return at the same risk. One failure stops the run.
- at every kept U cell, a lower bound from the pool: every recorded main-pool row of the start
  month (3-year lookback, any seed or penalty weight; model `mu` and `sigma` depend on the weights
  and the month alone) with `sigma <= r + TOL` is a long-only mix at risk at most `r`, so
  `mu_s'U >= max mu` over those rows, minus `1e-6`. This holds for the rows that break an upper
  limit too: all 4,155,755 recorded rows are long-only (minimum recorded weight `-1.2e-9`, inside
  `FEASIBILITY_TOL`; checked on the run before this revision), because the harness clips
  iterates to the bounds before renormalizing (`Geometry.normalize`). Expected violations 0; one
  stops the run.
- reported: the share of kept U cells that break a limit (a fund above 40% or a stock above 10%)
  and the share with L1(U, F) `> 1e-4`. Whether rule 3 may say anything about the limits depends
  on the first share (the condition in rule 3).
- for E, D and D10 at every kept cell, `mu_s'F(sigma(M)) - mu_s'M > 1e-6`, strictly: E and D are
  interior mixes of the limited domain and the frontier at their risk earns strictly more. A
  comparator that wrongly returned M itself would pass the risk match and a `>=` gate, make every
  difference 0 and turn T4 to T9 into "no"; the strict gap closes that. Expected violations 0;
  more than 1% of kept cells stop the run. Reported beside it: L1(F(sigma(M)), M) and the count
  of cells below `1e-4`.

## Outcomes, per cell

A cell is a start month and a risk: six per start month for U and F at the settings, one per
start month for E, D, D10 and V. All outcomes use the monthly-rebalanced convention of
`realized.monthly_rebalanced` from the mix's weights, gross of costs unless named net, exactly as
`v3-analyze` and `v3-safety` compute them.

1. **One-year return** `ret_m` and **one-year fall** `dd_m` (the maximum drawdown within the year,
   peak floored at the starting value).
2. **Five-year fall**: the maximum drawdown over the first `5 * 252` sessions
   (`safety3.window_outcomes`), only for the start months that have them (186, 2006-04 to
   2021-09).
3. **Worst-years fall**: for one mix, the mean of the largest 10% (rounded up) of its one-year
   falls over the start months; for U and F per setting then averaged over the six settings
   (`safety3.tail_level_mean`); for E, D and V over their single cell per start month. Each mix is
   ranked on its own outcomes. Tail sizes after the exclusions, rounded up: 24 for U per setting
   (232 kept cells at a = 0.85, 234 elsewhere), 24 for D and D10 (234), 21 for E (209 kept start
   months), 24 for V (234).
4. **Realized volatility** `vol_m`: the annualized standard deviation of the cohort's daily
   returns over the year. Described, not tested; it shows whether "the same model risk" held out
   of sample.
5. **Turnover per rebalance**, new in this check: v3 records only the summed in-year turnover
   (`realized.monthly_rebalanced`'s `turnover`, realized.py:116-142, the sum over the eleven
   in-year rebalances of the one-way trade `1/2 sum_i |w_i - w_i,drifted|` back to target); this
   check divides that sum by eleven. The **net return** `ret_net` charges 10 bp per unit of
   one-way turnover at every rebalance and at funding (`realized.COST_BP`), as v3.
6. **Break-even trading cost** against the comparator, in bp per unit of one-way turnover:
   `c* = theta_Ret / theta_T * 1e4`, with `theta_Ret` the mean paired one-year return difference
   (mix minus comparator, gross) and `theta_T` the mean paired difference in summed in-year
   turnover (mix minus comparator), both averaged as the statistics below average them; the ratio
   is recomputed inside each bootstrap resample and is undefined in a resample where
   `|theta_T| < 1e-6`. Reading, fixed now: `theta_T > 0` and `theta_Ret > 0`: the mix wins below
   `c*` and loses above it; `theta_T < 0` and `theta_Ret < 0`: the mix loses below `c*` and wins
   above it (it trades less); `theta_T <= 0` and `theta_Ret >= 0`: the mix wins at any cost,
   reported as "any"; `theta_T >= 0` and `theta_Ret < 0`: the mix loses at any cost, "none". The
   funding trade (turnover 1.0 for every mix) cancels in the difference.
7. **Month-to-month turnover of the recipe**, new in this check, described only: for each mix,
   `1/2 sum_i |w_i(o_k+1) - w_i(o_k)|` between consecutive scheduled start months, what an
   investor re-choosing the mix each month would trade; E has zero by construction. Reported as
   the mean per mix and the annualized figure (times twelve), with a second break-even
   `c*_sel = theta_Ret / (12 * theta_sel) * 1e4` read by the same rules. It is an approximation:
   each one-year cohort holds one mix for the year, so the realized return is not that of a
   re-choosing investor. The region check already found that the frontier mix changes from month
   to month; this measures by how much against recipes that do not.

A cell enters a 5-year outcome only when all `5 * 252` sessions exist. Model figures reported per
mix beside the outcomes: `mu_s' w`, `sigma(w)`, the risk position `a(w)`, ENB (`torsion.enb` on
the start month's `Sigma`, the app's measure) and `DR^2` (`anchors.dr2`).

## Statistics

Paired differences against the mix's comparator, averaged as the region and safety checks average
them: for U, the six settings of a start month with equal weight, then the start months; for E, D,
D10 and V, over start months directly. The same moving-block bootstrap over the job's whole
schedule of 246 start months (`evidence.Bootstrap`, seed 20261201): block 24 for one-year
outcomes and the worst-years tail, block 60 for the 5-year fall, each block length drawing its
own resamples from the seed. **10,000 resamples** throughout, not the 2,000 of the earlier checks:
a 99.44% interval leaves 0.28% in each tail, about 5.6 of 2,000 resamples, too few to place its
ends; 10,000 gives 28. The seed rule is unchanged (`Bootstrap(..., resamples=10_000)`). The
worst-years difference recomputes both mixes' tail means inside each resample.

Signs: a fall difference is comparator minus mix (positive: the mix fell less). A return,
volatility or turnover difference is mix minus comparator. For every mix and outcome: the mean, the
comparator's mean on the same cells, the difference with its two-sided 95% interval, the number of
cells and start months; for returns also the one-sided 95% lower bound (the 5th percentile of the
resamples). A mix's mean and its difference use only the cells where both have the outcome.

## Pass/fail tests, fixed now

Three mixes are tested, U, E and D, each on three fall measures: nine tests. Each uses a two-sided
`1 - 0.05/9 = 99.44%` interval, the correction the safety check used for its four tests (98.75%).
V and D10 are described only.

| Tests | Outcome | Bar | Return condition |
|---|---|---|---|
| T1 (U), T4 (E), T7 (D) | one-year fall | the mix falls at least 1.0 pp less | one-year return difference, one-sided 95% lower bound at least -50 bp |
| T2 (U), T5 (E), T8 (D) | 5-year fall | at least 1.0 pp less | 5-year return difference, lower bound at least -2.5 pp |
| T3 (U), T6 (E), T9 (D) | worst-years fall | at least 1.0 pp less | same as the one-year tests |

The bars and return lines are v3's and the safety check's (1 pp, -50 bp, -2.5 pp). Each test gets
one label:

- **lead**: the difference reaches the bar, its 99.44% interval is above 0, and the return
  condition holds.
- **inconclusive**: the difference reaches the bar, but the interval includes 0 (a lower end of
  exactly 0 includes it) or the return condition fails.
- **no**: the difference is below the bar.

A 5-year test with fewer than 120 usable start months (start months with at least one cell where
both mixes have the outcome) is inconclusive whatever it shows. A test without any paired cell is
inconclusive, and so is every test of a mix whose excluded cells exceed 15% (the exclusion rule). The lower bound of a return condition is the one-sided 95% bound, not the 99.44%
interval.

**The weight-limits reading (U against F), fixed now.** The same two-sided interval answers the
other direction. On each of T1 to T3, the label **limits protect** is added when F falls at least
1.0 pp less than U (difference at or below -1.0 pp) and the 99.44% interval is below 0. If any of
the three carries it, the answer to "are the weight limits themselves the diversification that
matters" is "yes, on this history, on that measure", and the report gives U's return difference
with it (the limits' cost or gain in return). Otherwise "not shown". This reading is a description
of the sub-question; it does not enter the decision rules.

## Decision rules, fixed now

1. At least one lead among the nine: still not a finding. That one mix and measure becomes a
   candidate for one confirmation on the held-out TSP portfolio, which needs a new run and its own
   spec. The owner decides.
2. No lead and at least one inconclusive: closed as not provable with this history. No further
   experiment on these start months.
3. All nine "no": closed. At the same risk, neither the simple recipes nor the most-diversified
   mix fell less than the frontier mix with the weight limits by the bar. The clause "and
   removing the limits did not help either" is added only when U breaks a weight limit in at
   least half of its kept cells; otherwise rule 3 reads "the limits rarely bound, so the U
   comparison is uninformative". T1 to T3 still count toward rules 1 and 2 either way.

V, D10, realized volatility, turnover, the break-even costs, the model figures and the
month-to-month turnover are description. Nothing in them changes the decision.

## Limits known in advance, and what a "no" would and would not rule out

- **Where E, D and V sit.** The most-diversified and the lowest-volatility mixes are low-risk
  mixes. **Equal weight is not a low-risk mix on this portfolio**: 19 equal slices put 42% in
  single stocks, and the model-side check puts its median risk position at 0.581 over the 234
  eligible start months (0.575 over all 246), between the settings 0.55 and 0.70; its mean,
  0.752, is pulled up by the 25 months above the frontier's top. The report gives both. Their
  comparator is the frontier with the limits *at that same risk*, which is exactly the
  yardstick the v3 region and safety checks found to be the thing that reduces falls (the frontier
  at a lower risk setting). So any protection that comes from sitting at low risk is already in
  the comparator, and a "no" means the recipe did no better than the frontier mix at that risk,
  not that low risk is useless. An unmatched comparison (E or D against F at a higher setting)
  would mostly measure the risk difference; that is why it is description only, placed between the
  six recorded settings.
- **Model risk is matched, realized risk is not.** Two mixes at the same `sigma(w)` under the
  3-year covariance can realize different volatilities. Realized volatility is reported beside
  every fall so a drawdown difference can be read as lower realized risk, a better path at the
  same risk, or both.
- **V's test is degenerate** (identity), so the question "does the lowest-volatility mix beat the
  frontier at the same risk" has no content on any portfolio; the only live question for V is
  what its lower risk costs and buys, which is the v3 yardstick again.
- **The paper's setting is not reproduced**: single stocks, 250-day covariance, a 4%
  risk-contribution limit, UCITS 5/40, a market-value benchmark. D here is the paper's program
  on 19 holdings with the menu's limits and the 3-year covariance.
- **Equal weight's tests leave out the crisis.** E's kept set has no start month from 2008-11
  to 2010-06 (and none of 2010-08 to 2010-10, 2020-03, 2020-05), so T4 to T6, one-year,
  five-year and worst-years alike, say nothing about equal weight entered during the 2008-09
  crisis or its first year of recovery. A "no" for E is a "no" on the other 209 start months.
  The excluded months are described on their own, without a comparator.
- **Fifth look at the same 234 start months, one portfolio, one lookback.** Neighbouring start
  months share up to eleven of twelve realized months; the worst 10% is 24 start months per
  setting for U, 24 for D and 21 for E, and rests on few separate episodes; the five-year
  windows (186, 161 for E) overlap and hold about three or four independent periods. The
  intervals are nominal under the block bootstrap's stationarity assumption.
- **A "no" would not rule out**: a benefit on the TSP portfolio or any other; a benefit with the
  app's 5-year lookback; a benefit to an investor who re-chooses monthly and pays trading costs
  (turnover is described, not tested); a benefit of the limits for estimation error on mixes other
  than the frontier; or a benefit under a lower bar than 1 pp.
- **A "no" would rule out, for this history**: that equal weight or the most-diversified mix,
  held at the same model risk, fell at least 1 pp less than the frontier mix with the limits in
  the following year, over five years, or in the worst years; and that removing the limits did.

## Compute size, from the code

No simulation bank, no search, no sizing run. Per scheduled start month (246):

- F reconstruction check at the six settings: 6 frontier programs plus the minimum-variance
  program (which is also V) and a greedy fill: 7 conic programs.
- U: the unlimited minimum-variance program and 6 frontier programs: 7 conic programs.
- E: no optimization; its comparator `F(sigma(E))`: 1 conic program.
- D: 1 convex program; its comparator: 1 conic program. D10: the same again: 2.

At most 19 conic programs per start month (an excluded cell solves no comparator), about 4,700
in all, each on 19 holdings and of the size of one app frontier node (the app solves 46 of them
per frontier, `optimize.NX`), so roughly a hundred app frontiers' worth of solves. No anchor is
re-solved and no 48-column frontier is built (check (b) and the reconstruction check above).
Check (b) on D reads the 246 pool files once, the same read as the region check (about 4.1
million main-pool rows). Realized outcomes: wealth paths for at most 15 mixes per eligible start
month over one and five years. The bootstrap draws 10,000 resamples per block length over a
246-month index, five times the earlier checks' draw. No runtime is estimated here; the run
records its own CPU seconds as the other checks do.

## Output and code

- Code in `portfoliosight/research/fixedrisk/recipes3.py`, command `v3-recipes` in `cli.py`,
  tests in `tests/research/fixedrisk/test_recipes3.py` written first: the two paper examples for
  D; the `F(s)` construction at the three branches (below `sigma_min`, inside, at `sigma_top`)
  against `optimize.frontier` on a small menu; the identity of V and the frontier's first node;
  U feasible or flagged: on a portfolio whose max-`mu_s` holding has low volatility, the settings
  above the unlimited top are excluded and counted and the others solve on the line; the
  exclusion rule and the 15% inconclusive label; the model-side gates (a U that keeps the limits
  passes the return gate and is reported as equal to F); the break-even readings on the four sign
  cases; the paired and bootstrap code reused from `safety3` unchanged. The 10,000 resamples
  are a module constant of `recipes3.py` passed to `safety3.assemble`, not a command-line flag,
  so a smoke run cannot change them.
- Result `fr-run-v3/analysis/recipes_check.json`, written with the safety check's no-replace
  convention (a later full run writes `recipes_check_2.json`; a run restricted to some start
  months is a smoke run that writes outside the run directory and is not recorded) and recorded
  in the job's analysis record; a hand-written section in the v3 report, headed exploratory.
- The reconstruction check and check (b) on D run and are written to the result before any
  realized outcome is read; a stop is reported, not fixed in place.

## Decisions for the owner

1. **How many tests.** (a) Nine tests, three mixes by three fall measures, each at a 99.44%
   interval (recommended: one answer per mix and measure, no second look later; the cost is
   wider intervals, so a real 1 pp effect with v3's spread passes only if its estimate is
   clearly above the bar). (b) Three tests on the one-year fall only at 98.33%, with the 5-year
   and worst-years falls described (narrower intervals; the cost is that a 5-year or worst-years
   lead could not be claimed, and testing it afterwards would be a sixth look).
2. **Which weight limits for the most-diversified mix.** (a) The menu's limits, the same as every
   other mix, with the paper's flat 10% built and described beside it (recommended: compares
   recipes, not limit rules; costs one extra program per start month). (b) The paper's flat 10% as
   the tested mix (closer to the paper; the cost is that a result would mix two changes, the
   recipe and the limits, and the frontier it is compared with still uses the menu's limits).
3. **The lowest-volatility mix is described only.** y: accept that its matched comparison is an
   identity, describe it against the frontier at the lowest setting (recommended; costs nothing).
   n: drop it from the report (loses the description of what the last step down the risk axis
   buys).
4. **Month-to-month turnover.** y: add the described month-to-month turnover and its break-even
   cost (recommended: it is the only place the cost of a changing mix against a fixed recipe
   appears; the cost is a few lines of code and an approximation stated as such). n: report only
   the v3 in-year turnover.
5. **The optimizer check on D reads the whole pool.** y: check D against every recorded mix of the
   month (recommended: a free held-out check of a new optimizer; the cost is the region check's
   pool read, done once). n: the paper's two examples only (faster; the run's anchors cannot
   serve, since v3 recorded no most-diversified anchor).
6. **Exclusion share for an inconclusive label.** (a) 15% of a mix's cells (recommended: equal
   weight's expected 10.7% stays testable, and a mix that loses more than a seventh of its months
   to the rule is not being tested at matched risk). (b) 5%: stricter, which would label every
   equal-weight test inconclusive before the run.

## Review log

Round 1, 2026-11-11, reviewed commit `94d09cb` against the code and a model-side geometry check
(no realized outcome computed). Applied in this revision before any realized outcome of a new mix
was read: P0-1 equal weight above the frontier's top in 25 start months (exclusion rule, expected
counts, 15% label, median risk position, "not a low-risk mix"); P1-2 the unlimited top can sit
below the limited top (claim deleted, U cells excluded by the same rule, unit test "feasible or
flagged"); P1-3 no recorded most-diversified anchor (anchor clause of check (b) dropped, pool
half kept); P1-4 model-side gates against a U that keeps the limits; P2-5 paper checks at
`lo = 0`, `hi = 1`; P2-6 D10 in the exclusion rule and `a(w) > 1` reporting; P2-7 reconstruction
check by return and risk, weight mismatches counted; P3-8 10,000 resamples; P3-9 turnover per
rebalance named as new.

Round 2, 2026-11-11, reviewed commit `3691aec`; the round-1 counts reproduced. Applied in this
revision, still before any realized outcome of a new mix was read: P1-1 strict gap gate
`mu_s'F(sigma(M)) - mu_s'M > 1e-6` against a comparator that returns M itself; P2-2 the 15% base
fixed to one-year cells, E's five-year count 161 recorded; P2-3 tail sizes after exclusion (21
for E) and the crisis-months limit; P2-4 the excluded lists written in full, the script to come
in the implementation PR under `scripts/`, the list gate; P2-5 rule 3's limits clause made
conditional on U breaking a limit in at least half of its kept cells; P3-6 U gates on kept cells;
P3-7 resamples as a module constant; P3-8 the pool lower bound on `mu_s'U`, added after checking
that every recorded row is long-only.
