# Fixed-risk optimization experiment protocol (v2) — DRAFT for owner and independent review

Status: draft, 2026-10-21. Not hash-locked. Supersedes the selection geometry of the
[return-optimization experiment protocol](2026-10-18-return-optimization-experiment-protocol.md) (v1)
and spec §5.5 decisions D1 (ceiling) and D2 (slider as allowed U sacrifice). Everything in v1 that
this document does not change stays in force: §3 menus and holding convention, §4 frozen data,
origins ledger and leakage prevention, §5 steps 1, 2 and 8 (shared banks, seeds, lock before
evaluate), §6 dependence-aware evidence, §8 acceptance checks, §9 evidence schema, the failure
taxonomy, frozen denominator and stop rules, and amendments R25–R33.

## 0. Why v2

v1 maximized `U = 0.60·Bad + 0.30·Typical + 0.10·Good` subject to `σ(w) ≤ X`. Because U rewards
low risk, the optimizer never used the budget: `w_R` sat at ≈4.6% risk (Example) / 3.0% (TSP)
under ceilings of 6.9–18.8%, and the x50 and x100 solutions were identical at every origin
([report](../research/2026-10-20-return-optimization-experiment-report.md); analysis in the
conversation record of 2026-10-21). The product's risk axis was therefore inert for R, and v1
answered "what is the best-U mix at any risk up to X," not the owner's question.

The owner's question (2026-10-21): on the chart the user fixes a risk `r` (the vertical line).
Moving the diversification slider along that line changes a diversification level `d`. For every
`(r, d)` there is an independent optimization: among the mixes with risk `r` and diversification
`d`, the one with the highest `U`. The slider's axis is `d` itself, not a U allowance.

v1's R+D question (does a diversification preference inside a U allowance earn its keep) is
answered and is not rerun: no gain within noise, and `D` could not move inside 2.5 bp.

## 1. Scope and hypotheses

Primary (the white line): at a fixed risk `r`, does the max-`U` mix beat the max-expected-return
mix (today's frontier) in realized outcomes? v1 could not answer this because its `w_R` and
frontier sat at different risks.

Secondary:

1. How far apart are the max-`B`, max-`T`, max-`G` and max-`U` mixes at the same `(r, d)`? If they
   coincide, the U weights do not matter; if not, the realized outcomes of each tell which component
   carries out-of-sample value, and the U weights are then chosen under purged cross-validation
   (§7), not by eye.
2. Along the fixed-risk line, how do realized Bad, drawdown and return change with `d`? v1's slider
   endpoints (max-return vs MDP at the same `σ`) showed the more-diversified mix with the *worse*
   model Bad and no better realized downside at every risk level; v2 measures the interior.
3. Engine dependence: the same questions under History replay and under the GARCH(1,1)-t FHS engine
   (spec §4.3), paired on the same origins, menus and grid.

Not in scope: ENB (unevaluated under D4/D7, unchanged), the copula engine (phase 10, parked), live
API or UI changes, any change to the production selection rule before C8 reads this report.

## 2. Selection contract (replaces v1 §2 and spec §5.5 D1/D2)

For menu bounds `min ≤ w ≤ max`, `1'w = 1`, a fixed risk `r`, a diversification level `d ∈ [0, 1]`,
an engine `e` and the shared draw:

```
σ(w)      = sqrt(w' Σ w), Σ the origin's training covariance (v1 §2 estimator, unchanged)
M(w)      = DR²(w) = (Σ_i w_i σ_i)² / (w' Σ w)                       (v1 D5, unchanged)
F(r)      = { w : bounds, 1'w = 1,  |σ(w) − r| ≤ τ_r · r }           (a band, not a ceiling)
w_F(r)    = argmax_{w ∈ F(r)} μ_s'w                                   (frontier mix at r; the top of the slider)
w_MDP(r)  = argmax_{w ∈ F(r)} Σ_i σ_i w_i                             (MDP at r; the bottom of the slider)
M_d(r)    = M(w_F(r)) + d · (M(w_MDP(r)) − M(w_F(r)))                  (the measure level the slider asks for)
F(r, d)   = { w ∈ F(r) : |M(w) − M_d(r)| ≤ τ_d · (M(w_MDP(r)) − M(w_F(r))) }
Arms      U: argmax_{w ∈ F(r,d)} U(w)     B: argmax B(w)     T: argmax T(w)     G: argmax G(w)
```

Tolerances **[choice, in-the-weeds]**: `τ_r = 0.01` (1% of `r`, so a 10% risk line admits
9.9–10.1%), `τ_d = 0.025` (2.5% of the measure span at that `r`). Both are recorded in the manifest
and are not tuned after data. If `M(w_MDP(r)) − M(w_F(r)) ≤ 1e-6` the line collapses to one `d`
cell, labelled as in v1 §3.

No dominance filter, admissibility guards, allowance or Stage B: each arm is one argmax on its own
objective. "Found" remains the honest label (v1 §5 step 6: sampled percentiles are piecewise
constant; the search is bounded, not certified).

Slider semantics served after C8 **[product decision, owner]**: position `d` selects the max-`U` mix
in `F(r, d)`. `d = 0` is the best-`U` mix at the frontier's diversification level, which need not be
the frontier mix itself; the chart's white line is the locus of the `d = 0` mix or of `w_F(r)` as C8
decides from the primary result. The label "every step down gives up return for diversification"
stays truthful only if the report confirms U falls with `d`; the report states the measured sign.

## 3. Grid, origins, menus, engines

- Risk levels: `r ∈ {X(.25), X(.50), X(1)}` with `X(a) = σ_min + a·(σ(w_top) − σ_min)` exactly as
  v1 §3, now used as fixed risks instead of ceilings.
- Diversification levels for the experiment: `d ∈ {0, 1/3, 2/3, 1}` **[choice]**. The product's
  precompute walks `d = 0 : 0.05 : 1`; the experiment samples the line.
- Origins, menus, lookback, calendar, maturity, leakage rules, realized denominators: v1 §4
  unchanged (99 scheduled origins, 87 realized at D* = 2026-10-16).
- Engines: `replay` (v1 §5 step 1, unchanged) and `garch` (spec §4.3: `fit_garch_t_panel`,
  `simulate_fhs_panel`, long-run start, residual pool from the training window only). Each engine
  has its own 2,000 × 252 bank per `(menu, origin, engine, replicate)` with v1's seeds; a GARCH fit
  that fails to converge at an origin is a named failure of that engine's cells (v1 taxonomy), never
  a silent substitution of replay.
- Optimizer replicates: primary seed `20261013` for every primary statistic; seeds `20261014..17`
  for the stability diagnostics of the max-`U` arm only **[choice: cost]**.
- Cells: `99 × 2 menus × 3 r × 4 d = 2,376` per engine, four arms each; the frontier and MDP
  anchors per `(menu, origin, r)` are shared across `d`.

## 4. Search (amends v1 §5 steps 3–7)

1. Anchors per `(menu, origin, r)`: `w_F(r)` (cap-constrained max-`μ_s` on the risk band, the
   existing greedy/`w_top` machinery projected to the band) and `w_MDP(r)` (v1 step 3 program with
   `σ ≤ r` replaced by the band; CVXPY/Clarabel). The fixed-risk ladder of the demo design
   (`engine/ladder.py`: most diversified mix at risk `r` earning at least return `y`) sweeps `M`
   monotonically from `M(w_F)` to `M(w_MDP)` as `y` falls; its level nearest `M_d(r)` is the third
   anchor for each `d` cell.
2. Broad proposals: v1's 1,024 scrambled Sobol points, each moved onto the risk band by bisection
   along the segment toward `w_min` (below `r`) or toward `w_top` (above `r`), then kept only if
   inside `F(r, d)`; the retained set is shared by the four arms. If fewer than 64 proposals land in
   a `(r, d)` cell, draw a second 1,024 block with the seed offset recorded; if still fewer than 64,
   the cell is `infeasible_band` (named, counted, never silently widened).
3. Local refinement: six starts per arm from the shared feasible pool by descending objective with
   the v1 L1 ≥ .10 spacing rule, the ladder anchor always included; COBYLA with the band constraints
   as inequalities, `rhobeg .05`, `tol 1e-5`, `catol 1e-8`; budget 128 calls per start **[choice]**,
   justified by the v1 convergence analysis (k = 120 reached within 0.5 bp of the full 384-call
   result in 95–98% of cells and within 2.5 bp in 99–100%).
4. Union and rescoring as v1 step 7, then each arm's argmax on the union restricted to `F(r, d)`;
   native-search selections reported as diagnostics.
5. Lock before evaluate: v1 step 8 unchanged; independent banks `20261113..17` per engine.

## 5. Measurements (adds to v1 §6)

Per locked selection, under both engines where applicable: training and independent-bank
`B/T/G/U/mean/ES_2.5`, `σ`, `M`, `μ_s'w`, weights, turnover to the previous origin; realized
one-year outcomes as v1; plus:

- **Multi-year realized**: compounded 3- and 5-year outcomes from the same origin with the locked
  weights held at constant target (daily rebalanced, as v1), for the origins whose horizons are
  complete (≈60 and ≈36 origins). Reported beside the 1-year figures; disjoint-interval counts
  stated (≈2 and ≈1), so these are descriptive, never gated.
- **Real returns**: the 1-, 3- and 5-year outcomes deflated by CPI-U (series and vintage frozen in
  the snapshot **[choice: source]**), reported for every arm and reference.
- **Regime buckets**: each realized year labelled by the horizon's realized equity drawdown and
  10-year yield change (buckets: calm / equity drawdown ≥ 15% / rate shock ≥ 150 bp; thresholds
  fixed here), with each arm's outcomes reported per bucket. Descriptive.
- **Forecast calibration** as v1 (coverage and pinball per quantile), per engine, per arm.

## 6. Predeclared criteria (replaces v1 §7's R+D criteria)

All comparisons are paired within `(menu, origin, r, d, engine)` with v1 §6's block bootstrap.

| Question | Criterion, each menu and engine separately |
|---|---|
| White line (primary) | max-`U` at `(r, d=0)` vs `w_F(r)`: pooled independent-bank mean ΔU ≥ 5 bp with ≥ 4/5 banks positive; realized guardrails of v1 (median and mean annual-return loss ≤ 25 bp, loss frequency +≤ 5 pp, mean drawdown worsening ≤ 1 pp); realized support as v1 (≥ 25 bp gain or ≥ 1 pp drawdown improvement with 99% lower bound > 0, ≥ 20 disjoint intervals disclosed as unmet) |
| Component spread | median pairwise L1 among the U/B/T/G argmaxes at the same cell; reported, no threshold |
| Line shape | sign and 95% interval of the slope of realized Bad, drawdown and return against `d` at each `r`; reported |
| Engine agreement | share of cells where the two engines select mixes within L1 ≤ .10; paired realized differences; reported |
| Stability (max-`U` only) | v1's across-seed Bad SD and L1 rules, per `(r, d)` |
| Cost | warm per-arm search wall p95 ≤ 20 s Example / ≤ 5 s TSP at the 128-call budget; reported against the product's precompute budget |

Labels: **valid experiment** (v1 compliance checks), **white line: max-U supported / not
supported / inconclusive** per menu and engine, everything else descriptive. No equivalence claim.
Stage 2 / ENB stays governed by D4/D7 and is not triggered by this protocol.

## 7. Choosing the U weights (new; de Prado)

The U weights are hyperparameters. After the run, evaluate candidate weight triples on the
**locked B/T/G argmax outcomes and the max-U outcomes already computed** (no new searches) under
combinatorial purged cross-validation over the origin index (purge = horizon length, embargo = one
month, qse `PurgedKFold`), report the distribution of out-of-fold realized U for each triple and the
probability of backtest overfitting for the number of triples tried. The triples are predeclared:
`(.60,.30,.10)`, `(.70,.20,.10)`, `(.50,.35,.15)`, `(.80,.15,.05)`, `(.40,.40,.20)`. The result
informs C8; it does not change this run's primary analysis.

## 8. Resource ceilings and cost estimate

Six workers, one BLAS thread each, aggregate RSS ≤ 4 GiB, 600 s per arm, **120 CPU-hours** for both
engines together **[choice, from measurement]**. Estimate at the 128-call budget from v1's measured
costs: Example ≈ 15 s per arm-search × 4 arms × 1,188 cells ≈ 20 CPU-h; TSP ≈ 1.6 CPU-h; GARCH
evaluation ≈ replay; two engines ≈ 45 CPU-h plus anchors, unions and independent evaluation. The
`experiment estimate` command must be run on the frozen snapshot before the hash lock and its
projection recorded, as in v1 (R20). Stop rules and incomplete labelling as v1/R31–R33.

## 9. Prerequisites (Conductor plan order)

1. Merge v1's branch (phase 6b) into the run through the phase PR and `ledger phase-done`.
2. Close phase 3 (#122) through the frozen gate; its product PRs #182/#185 are already in the run.
3. Phase 6 remainder: `garch` through `research.evaluate.bank(engine=...)` using
   `engine.ranges.garch_range_model` per origin window; 6.4 mirror validation and 6.5 Bad-year
   stability for both engines; the engine-validation report. 6.6 (KS-001 timing) is not a
   prerequisite of this offline experiment.
4. This protocol: independent review, hash lock, snapshot re-freeze at the final commit, run.

Phases 4 (range API) and 5 (UI) are prerequisites of the deployable milestone, not of this
experiment; they follow C8 as the plan already states.

## 10. Open decisions for the owner

- **A.** `d` grid for the experiment: (a) `{0, 1/3, 2/3, 1}` as drafted; (b) `{0, 0.5, 1}` (−25% cost).
- **B.** Multi-seed stability on the max-`U` arm only (as drafted) or on all four arms (+≈3× cost on
  the stability portion)?
- **C.** CPI source for real returns: (a) FRED CPIAUCSL frozen into the snapshot; (b) omit real
  returns from this run.
- **D.** Keep the realized-support thresholds of v1 (25 bp / 1 pp / 99%) for the white-line question,
  or relax to descriptive only given 7 disjoint years?
