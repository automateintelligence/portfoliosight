# Fixed-risk experiment v3: region check (exploratory addendum)

Date: 2026-11-09. Approved by the owner on 2026-11-09 ("1 y"). Written and committed before any
realized outcome of a region mix is computed.

## Question

The owner's question after the v3 result: instead of holding risk fixed, take every mix whose
model return is at most 50 bp below the frontier mix's, let risk move, and look for a mix chosen by
simulated drawdown, by ENB, or by a blend of the two. Does any such mix fall less in real history
than simply lowering the risk setting by the same return cost?

This check uses only what run `fr-run-v3` (job `research2003_replay`) already recorded. No new
simulation. It reuses the same 234 start months as the v3 confirmatory test, so every result is
exploratory and none of it is a finding.

## Definitions

- **Cell**: one start month and one risk setting (0.10, 0.25, 0.40, 0.55, 0.70, 0.85). Main pool
  only: 3-year lookback, main seed, main penalty weight (the rows `ensemble3.read_main_pool` keeps).
  234 eligible start months, 1,404 cells.
- **Frontier mix F**: the frontier arm's selection in the cell, with model return `mu_F` and risk
  target `r`.
- **Region**: recorded pool mixes of the cell with `mu >= mu_F - 0.005` and `sigma <= r + tau_wide`
  (the upper edge of the wide band, 0.01). Risk may be lower than the line, not higher.
- **Left tip L**: the yardstick. A weight blend of F and the frontier selection one risk setting
  lower in the same start month: `L = F + t * (F_lower - F)`, with
  `t = clip(0.005 / (mu_F - mu_F_lower), 0, 1)`, and `t = 1` when `mu_F <= mu_F_lower`. Its realized
  outcome is computed from the blended weights. The lowest setting (0.10) has no lower neighbour:
  its 234 cells are left out of every left-tip comparison (1,170 cells remain) and are still
  compared against F.
- **Realized outcome**: the same one-year realized return and realized maximum drawdown that
  `v3-analyze` computes for a selection, from the mix's weights.

## Picks made in advance (model quantities only)

Inside the region, each mix gets three percentile ranks within the cell: simulated tail drawdown
`tdd` (lower is better), `enb` (higher is better), worst historical fall `h` (lower is better).
A rule is a weight triple `(w_tdd, w_enb, w_h)` on the grid of step 0.25 that sums to 1: 15 rules.
The rule picks the mix with the lowest weighted rank; ties go to the higher `mu`, then to the first
recorded row.

Named rules:

| Rule | Weights (tdd, enb, h) |
|---|---|
| Fair drawdown pick | (1, 0, 0) |
| ENB pick | (0, 1, 0) |
| Owner's blend | (0.5, 0.5, 0) |
| History pick | (0, 0, 1) |

One extra pick, outside the 15: the fair drawdown pick restricted to mixes on the same risk line
(`in_wide`).

## Hindsight ceilings

- **Mix ceiling**: per cell, the region mix with the smallest realized drawdown. It is a maximum
  over hundreds of mixes, so it is biased upward by chance and is only an upper bound.
- **Rule ceiling**: the one of the 15 rules with the largest mean realized drawdown improvement
  over L. Chosen in hindsight from 15, so mildly optimistic.

## Statistics

For each pick and each ceiling: the mean paired difference against L and against F in realized
drawdown (positive = the pick fell less) and in realized return, over cells, with the v3 paired
moving-block bootstrap unchanged (block 24, 2,000 resamples, seed 20261201; two-sided 95% interval
for drawdown, one-sided 95% lower bound for return). Also the mean `sigma`, `mu` and `enb` of each
pick, and the share of picks that sit below the risk line.

Predictiveness, per cell, over all same-line (`in_wide`) main-pool mixes with at least 20 mixes:
Spearman rank correlation of `tdd` with realized drawdown, and of `mu` with realized return. Report
the mean across cells, the share of cells above zero, and a block-bootstrap 95% interval of the mean.

## Decision rules, fixed now

1. Mix ceiling beats L by less than 1 pp of drawdown: the question is closed. No mix in the region,
   even picked with hindsight, beats lowering the risk setting.
2. Otherwise, rule ceiling beats L by less than 1 pp, or its 95% interval includes 0: closed for
   these three measures. No further experiment is recommended, because no untested measure is on
   the table.
3. Otherwise (rule ceiling at least 1 pp, interval above 0, return lower bound against L at least
   -50 bp): still not a finding. That single rule becomes a candidate for one held-out confirmation
   on the TSP menu. The owner decides.

Rule 1 is the rule the owner approved. Rule 2 was added before looking because the mix ceiling is a
best-of-hundreds and will likely clear 1 pp on chance alone, which would leave rule 1 unable to
close anything.

## Separate behavioural test

A test of the lowest-simulated-drawdown search on a made-up menu with a planted crash hedge (a fund
that rises on the days the others crash, at equal volatility and lower return): the search must put
more weight on the hedge than the frontier search does, and reach a lower simulated tail drawdown.
If this test fails, stop and report; do not adjust the test or the search to make it pass.

## Output

`fr-run-v3/analysis/region_check.json` and a section appended to the v3 report.

## Corrections, 2026-11-09

Made after reading the code and before any realized outcome of a region mix was computed. Where a
correction conflicts with the text above, the correction governs.

1. **Risk ceiling.** The wide band is a fraction of `r`, not an absolute 0.01. The ceiling is the
   code's wide-band upper edge: `sigma <= r * (1 + contracts.TAU_R) + FEASIBILITY_TOL`.
2. **Region rows.** "Main pool" means the lookback, seed and penalty-weight filter only, with no
   band filter, so mixes below the line stay in. The region of a cell draws on every main-pool mix
   recorded for that start month, under any of the six risk settings, that meets the return floor
   and the risk ceiling of the cell. This holds only if a mix's `mu`, `sigma`, `tdd`, `enb` and `h`
   depend on its weights and the start month alone (one simulated bank per month). If they do not,
   the region is limited to the cell's own rows and the output says so. Rows with identical weights
   count once; row order for ties is risk setting ascending, then recorded order.
3. **Uncovered case in the decision rules.** Rule ceiling at least 1 pp with its interval above 0,
   but return lower bound against L below -50 bp: labelled "closed for these measures: fails the
   return condition". Nothing goes forward.
4. **"Below the risk line"** means below the wide band: `sigma < r * (1 - contracts.TAU_R)`.

Added the same day, still before any realized outcome of a region mix was looked at (a two-month
smoke run of the code produced a file that nobody read; it is deleted before the full run):

5. **Region mixes must be allowed mixes.** The pool also records evaluated points that break a
   fund's bounds (about 2.7% of main-pool rows). A region mix must pass the harness's own domain
   check: every weight within the menu's bounds and the weights summing to one, each within
   `FEASIBILITY_TOL` (`anchors.Geometry.in_domain`). The output reports how many rows this removes.
6. **Sharper crash-hedge test.** A hedge with negative overall correlation is bought by any
   variance-based search, so it does not show that the drawdown measure sees crash behaviour. The
   made-up menu gains a decoy: same volatility, same model return and the same full-sample
   covariance with the equity-like funds as the hedge, but its offsetting moves come on ordinary
   days and it does nothing special on crash days. Two assertions: (a) of two mixes that differ
   only by swapping the hedge and decoy weights, the hedge-heavy one has the lower simulated tail
   drawdown at equal model volatility; (b) the lowest-simulated-drawdown search holds more of the
   hedge than of the decoy and reaches a lower simulated tail drawdown than the frontier search.
   If either fails, stop and report.
