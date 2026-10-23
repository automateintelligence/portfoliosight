# Fixed-risk optimization experiment protocol (v2) — DRAFT for independent review

Status: draft, revision 2, 2026-10-22. Owner decisions of 2026-10-22 (two rounds) applied; see §10.
Not hash-locked. Next step: the owner runs the Codex review; findings are folded in; then the hash lock.

Supersedes the selection geometry of the
[return-optimization experiment protocol](2026-10-18-return-optimization-experiment-protocol.md) (v1)
and spec §5.5 decisions D1 (ceiling) and D2 (slider as allowed U sacrifice). Everything in v1 that
this document does not change stays in force: §3 holding convention, §4 frozen data, origins ledger
and leakage prevention, §5 steps 1, 2 and 8 (shared banks, seeds, lock before evaluate), §6
dependence-aware evidence, §8 acceptance checks, §9 evidence schema, the failure taxonomy, frozen
denominator and stop rules, and amendments R25–R33. The contingent product decisions this experiment
feeds are drafted as [ADRs 0001–0004](../adr/).

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

The owner's direction of 2026-10-22: this is research, not production development. Go fast, apply
the production speed ideas to the experiment where they make sense, include realism when it is
cost-effective, use industry practice, and ask what the best practitioners would do with this data.

## 1. Scope and hypotheses

Primary (the white line): at a fixed risk `r`, does the mix with the highest `U` on that risk line
beat the max-expected-return mix at the same risk (today's frontier) in realized outcomes? v1 could
not answer this because its `w_R` and frontier sat at different risks.

Secondary:

1. Where along the line does `U` peak? The free cell (§2) reports the diversification level `d*`
   of the line's max-`U` mix at every `(menu, origin, r)`. If `d*` is usually interior, the
   owner's reading (2026-10-21: "if the best mix at `(r, d = 0.3)` has a higher `U` than at
   `(r, d = 0)`, that is reducing downside risk") is confirmed by measurement. If the free cell
   concentrates the way v1's `w_R` did, the report says so and the interior cells show what a
   minimum-diversification band costs.
2. Which U weights hold up out of sample? Five predeclared weight triples run as arms (§2) and are
   compared under purged cross-validation (§7). Max-`Bad` runs as a sixth arm: the direct answer to
   "the safest mix at this risk".
3. Along the fixed-risk line, how do realized Bad, drawdown and return change with `d`? v1's slider
   endpoints (max-return vs MDP at the same `σ`) showed the more-diversified mix with the *worse*
   model Bad and no better realized downside at every risk level; v2 measures the interior.
4. Is today's frontier a fair comparator? The sample expected return predicted nothing in v1
   (rank correlation with realized return −0.03 to −0.6). A shrunk-expected-return frontier is
   reported beside it (§5) so the white-line question is not won against a straw man.
5. Engine dependence: the same questions under History replay and under the GARCH(1,1)-t FHS engine
   (spec §4.3), paired on the same origins, menus and grid.

Not in scope: ENB (unevaluated under D4/D7, unchanged), the copula engine (phase 10, parked), live
API or UI changes, any change to the production selection rule before the post-experiment product
decision (conductor plan checkpoint C8) reads this report.

## 2. Selection contract (replaces v1 §2 and spec §5.5 D1/D2)

In words, for one menu at one origin:

- `σ(w)` is the mix's risk, the annualized volatility from the training covariance.
- `M(w)` is the mix's **diversification measure**: the squared diversification ratio, how much
  risk the holdings would have if they moved independently, divided by the risk they actually have
  together. It is 1 for a single holding and rises as holdings offset one another.
- `F(r)` is the **set of mixes on the risk line**: every allowed mix whose risk is `r`, within a
  1% tolerance. The vertical line on the chart.
- `w_F(r)` is the mix on that line with the highest expected return (today's frontier point) and
  `w_MDP(r)` the most diversified mix on that line. They are the slider's two ends. The MDP is used
  only to set the slider's length; it is not a reference portfolio in this experiment.
- `M_d(r)` is the **diversification level the slider asks for**: slide a fraction `d` of the way
  from the frontier mix's measure to the most-diversified mix's measure.
- `F(r, d)` is the **set of mixes at that slider position**: the mixes on the risk line whose
  measure is within 2.5% of the span of `M_d(r)`. The cell the optimizer searches.
- `d(w)` is where any mix sits on the slider: 0 at the frontier mix's measure, 1 at the MDP's.

Formally, for menu bounds `min ≤ w ≤ max`, `1'w = 1`, a fixed risk `r`, a level `d ∈ [0, 1]`, an
engine `e` and the shared draw:

```
σ(w)      = sqrt(w' Σ w), Σ the origin's training covariance (v1 §2 estimator, unchanged)
M(w)      = DR²(w) = (Σ_i w_i σ_i)² / (w' Σ w)                       (v1 D5, unchanged)
F(r)      = { w : bounds, 1'w = 1,  |σ(w) − r| ≤ τ_r · r }           (a band, not a ceiling)
w_F(r)    = argmax_{w ∈ F(r)} μ_s'w                                   (frontier mix at r; slider top, d = 0)
w_MDP(r)  = argmax_{w ∈ F(r)} Σ_i σ_i w_i                             (most diversified at r; slider bottom, d = 1)
M_d(r)    = M(w_F(r)) + d · (M(w_MDP(r)) − M(w_F(r)))
F(r, d)   = { w ∈ F(r) : |M(w) − M_d(r)| ≤ τ_d · (M(w_MDP(r)) − M(w_F(r))) }
d(w)      = (M(w) − M(w_F(r))) / (M(w_MDP(r)) − M(w_F(r)))
Arms      U_k: argmax_{w ∈ F(r,d)} U_k(w), k = 1..5 (triples below);   B: argmax_{w ∈ F(r,d)} Bad(w)
Free cell every arm's argmax over F(r) itself (no d band); the winner's d(w) is reported as d*
```

Arms **[owner, 2026-10-22]**: the five U weight triples `(.60,.30,.10)` (primary, `U_1`),
`(.70,.20,.10)`, `(.50,.35,.15)`, `(.80,.15,.05)`, `(.40,.40,.20)`, and max-`Bad`. Max-Typical and
max-Good are dropped (Typical at a fixed risk tracks the frontier; Good rewards concentration).
MDP, minimum variance and equal weight are no longer evaluated as reference arms; the two
comparators are `w_F(r)` and the shrunk-μ frontier `w_F̃(r)` of §5.

Tolerances **[choice, in-the-weeds]**: `τ_r = 0.01`, `τ_d = 0.025`, recorded in the manifest and
not tuned after data. If `M(w_MDP(r)) − M(w_F(r)) ≤ 1e-6` the line collapses to one cell, labelled
as in v1 §3; the share of collapsed columns per menu is reported (it sets the product's
column-open rule, ADR 0001).

No dominance filter, admissibility guards, allowance or Stage B: each arm is one argmax on its own
objective. "Found" remains the honest label (the objective is sampled; the search is bounded, not
certified), now with the agreement check of §4.

Slider semantics served after the product decision **[owner]**: position `d` selects the max-`U`
mix in `F(r, d)`; the ends are `w_F(r)` and `w_MDP(r)`. The white line is the locus of `w_F(r)`
(today) or of the free cell's max-`U` mix, as the decision records from the primary result.

## 3. Grid, origins, menus, engines

- Risk levels **[owner, 2026-10-22: need not exceed the app's 48 columns; six for the main grid]**:
  `r ∈ {X(a) : a ∈ {.10, .25, .40, .55, .70, .85}}`, `X(a) = σ_min + a·(σ(w_top) − σ_min)` as v1
  §3, used as fixed risks. The extreme `a = 1` is omitted: its band holds only the max-return corner.
- Diversification cells: the free cell and `d ∈ {0.25, 0.50, 0.75}`; `d = 0` and `d = 1` are the
  anchors. Four searched cells per `(menu, origin, r)`, six arms each.
- **Showcase surfaces**: at six origins per menu (v1's sensitivity rule, indices
  `floor(j·(K−1)/5)`, j = 0..5), the full product surface: 48 risk columns × 19 interior slider
  positions, primary arm only. These measure the production precompute and give the UI work a
  heatmap over time; they are descriptive.
- Engines: `replay` (v1 §5 step 1, unchanged) and `garch` (spec §4.3). GARCH is fitted **once per
  fund and origin** on the training window and shared by every menu, arm and cell at that origin
  (the per-fund precompute of ADR 0002 applied to the experiment); residual pools come from the
  training window only; a non-converging fit is a named failure of that fund's cells, never a
  silent substitution of replay. Each engine has its own 2,000 × 252 bank per
  `(menu, origin, engine, replicate)` with v1's seeds.
- Optimizer replicates: primary seed `20261013` for every primary statistic; seeds `20261014..17`
  for the stability diagnostics of the `U_1` arm only.
- Lookback **[owner, 2026-10-22: 3 years primary]**: 756 union-calendar rows with the 90%
  complete-rows rule; the product's 5-year window runs as a sensitivity at the six showcase origins.
  Reason: a 3-year window puts the 2008 crash inside the realized record (§3a); covariance
  shrinkage (v1 estimator) handles the shorter sample.

### 3a. Menus, origins and data history (new)

v1 scheduled 99 monthly origins, 2018-06 to 2026-09, for both menus. The limit was not the data
providers: Tiingo serves VGSTX from 1985 and VTI from 2001; tsp.gov serves the five TSP funds from
2003-06. The limit was the Example menu's youngest fund, VWOB (first price 2013-06-04), plus the
5-year window: the first origin at which every Example fund had a full window was 2018-06, and TSP
was held to the same schedule.

**The Example menu is replaced for research by a long-history menu** **[owner, 2026-10-22]**: the
Example preset is a product menu, not a sacred research subject, and a menu of broad asset-class
ETFs with history to 2003 gives three times the realized years at half the evaluation cost. The
research menu (first prices to be confirmed from the provider at fetch; the three already in the
lake are confirmed):

| Fund | Asset class | First price |
|---|---|---|
| SPY | US large-cap equity | 1993-01 |
| IWM | US small-cap equity | 2000-05 |
| IWD | US large-cap value | 2000-05 |
| EFA | Developed ex-US equity | 2001-08 (lake) |
| EEM | Emerging-market equity | 2003-04 |
| IYR | US real estate | 2000-06 |
| TLT | Long US Treasuries | 2002-07 |
| IEF | Intermediate US Treasuries | 2002-07 |
| SHY | Short US Treasuries | 2002-07 |
| LQD | Investment-grade corporates | 2002-07 (lake) |
| TIP | US inflation-linked | 2003-12 (lake) |

Union first date 2003-12 (TIP). The eight funds not in the lake are fetched through the existing
Tiingo provider, frozen into the snapshot, and the menu is registered as a research preset
(`research2003`), not a product preset. Caps: 0–40% per fund **[choice]**, recorded in the
manifest. The owner may swap any ticker before the lock.

Schedules, each menu on its own eligible origins:

| Menu | Funds | Ledger from | First origin (3y) | Origins to 2026-09 | Disjoint realized years |
|---|---|---|---|---|---|
| research2003 | 11 | 2003-12 | 2006-12 | ≈ 238 | 20, including 2007-09, 2011, 2013, 2015-16, 2018, 2020, 2022 |
| TSP | 5 | 2003-06 | 2006-06 | ≈ 244 | 20 |

Requires the ledger start to be per menu (harness change, small). Cells per engine:
research2003 `238 × 6 r × 4` = 5,712; TSP `244 × 6 × 4` = 5,856; six arms each.

## 4. Search (replaces v1 §5 steps 3–7)

**Smooth objective with gradients** **[owner, 2026-10-22]**. v1's objective was a sampled
percentile, flat between paths, which forced a derivative-free optimizer and hundreds of calls per
start. v2 searches a smoothed objective and reports the exact one:

- For a mix `w`, the bank gives one compounded year `R_p(w)` per path. The smoothed quantile
  `Q̃_q(w)` is the kernel-weighted average of the sorted years, Gaussian kernel of bandwidth
  `h = 0.01` in rank fraction (≈ 20 of 2,000 paths) centred on `q` **[choice]**. `B̃, T̃, G̃` are
  `Q̃` at 0.025, 0.5, 0.975; `Ũ_k` the triple's combination.
- The gradient is closed form: `∂R_p/∂w = (1 + R_p) · Σ_t r_pt / (1 + r_pt'w)`, weighted by the
  kernel at the current ranks. One gradient costs about one evaluation.
- Every reported figure (`B/T/G/U`, the lock, every comparison) is the **exact** sampled quantile of
  the final mix. The smoothing is a search device only.

**Optimizer**: SLSQP (SciPy) with analytic gradients; equality `1'w = 1`; bounds; the risk band as
two smooth inequalities; the measure band as two more in the interior cells. Maximum 200 iterations,
`ftol 1e-9` **[choice]**. Starts per cell: (i) the ladder anchor nearest `M_d(r)` (the fixed-risk
ladder of `engine/ladder.py` sweeps `M` monotonically from `M(w_F)` to `M(w_MDP)`), (ii) the
neighbouring cell's solution along `d` (continuation; for the free cell, `w_F(r)`, `w_MDP(r)` and
the best Sobol point), (iii) the best of v1's 1,024 scrambled Sobol points projected onto the risk
band by bisection toward `w_min` or `w_top`. Three starts; the arm's answer is the best exact
objective among them. Fewer than 64 feasible Sobol points in a cell triggers one more block with the
seed offset recorded; still fewer is `infeasible_band` (named, counted, never silently widened).

**Agreement check, predeclared**: before the lock, 50 cells drawn by seed from the grid are solved
by both the gradient optimizer and v1's COBYLA at 768 calls on the same banks. The gradient
optimizer is accepted for the run if its exact `U_1` is within 2.5 bp of, or above, COBYLA's in at
least 95% of the cells. Otherwise COBYLA at 128 calls per start runs the experiment (the revision-1
search), and the report says so. Agreement is judged on `U`, not on weights: v1 showed the optimum
is flat in `w` (seed-to-seed L1 up to 0.8 at equal `U`), so differing weights at equal `U` are
expected.

**Recording**: starts, iteration counts, the final mix and its exact figures per arm and cell; no
per-call rows (v1 wrote every call into a 2 GB table).

**GPU** **[owner question, 2026-10-22]**: the smooth objective makes the search a batched tensor
operation, so it could run on the local GPU (RTX 2070, 8 GiB) with a batched gradient optimizer
(all cells, arms and starts of an origin in one tensor). v2 does not require it: the CPU projection
fits in a night, no tensor library is installed, and a batched constrained optimizer is one to two
days of extra engineering. The objective and gradient are written as array code with no SciPy
inside, so a `torch` backend can be added later without changing the protocol. Decision rule: if
the six-origin measurement of §8 projects more than two nights of wall time, the GPU path is built
before the run; otherwise not.

Union and rescoring per cell as v1 step 7 (every evaluated mix joins the cell's pool with exact
figures; the arm's selection is the pool's best on its objective inside the cell); lock before
evaluate as v1 step 8; independent banks `20261113..17` per engine.

## 5. Measurements (adds to v1 §6)

Per locked selection, under both engines where applicable: training and independent-bank
`B/T/G/U_1..5/mean/ES_2.5`, `σ`, `M`, `d(w)`, `μ_s'w`, weights, turnover to the previous origin;
plus:

- **Comparators**: `w_F(r)` (today's frontier, sample `μ_s`) and `w_F̃(r)`, the same program with
  Bayes–Stein shrunk expected returns (Jorion 1986, shrinkage toward the minimum-variance
  portfolio's return, intensity from the data) **[choice; realism rule]**. Both are evaluated like
  arms. `w_MDP(r)` is recorded (it defines the slider) but not evaluated.
- **Realized convention** **[choice; realism rule]**: the locked weights held with **monthly**
  rebalancing to target becomes the primary realized outcome (v1 rebalanced daily, which no
  investor does); daily rebalanced is reported for continuity. A **cost variant** charges 10 bp per
  unit of one-way turnover at each rebalance and at each origin's reallocation, reported beside the
  gross figures.
- **Multi-year realized**: compounded 3- and 5-year outcomes from the same origin with the locked
  weights, for the origins whose horizons are complete; disjoint-interval counts stated; descriptive.
- **Real returns** **[owner: include]**: 1-, 3- and 5-year outcomes deflated by CPI-U, all items,
  not seasonally adjusted (FRED `CPIAUCNS`, the series TIPS index to and the one FRED does not
  revise), fetched as FRED's public CSV and frozen into the snapshot with its vintage date;
  deflator = index of the horizon's last month over its first month; evaluation only.
- **Regime buckets**: each realized year labelled by the horizon's realized equity drawdown and
  10-year yield change (calm / equity drawdown ≥ 15% / rate shock ≥ 150 bp; fixed here); outcomes
  per bucket; descriptive.
- **Forecast calibration** as v1 (coverage and pinball per quantile), per engine, per arm.
- **Cost**: milliseconds per exact evaluation, per smoothed evaluation with gradient, iterations
  and wall per cell by menu and arm, wall per showcase surface; the bare figures the range API is
  sized from (ADR 0002).

## 6. Predeclared criteria (replaces v1 §7's R+D criteria)

All comparisons are paired within `(menu, origin, r, cell, engine)` with v1 §6's block bootstrap
over origins.

| Question | Criterion, each menu and engine separately |
|---|---|
| White line (primary) | free-cell `U_1` arm vs `w_F(r)`: pooled independent-bank mean ΔU ≥ 5 bp with ≥ 4/5 banks positive; realized guardrails of v1 (median and mean annual-return loss ≤ 25 bp, loss frequency +≤ 5 pp, mean drawdown worsening ≤ 1 pp) on the monthly-rebalanced convention; realized support as v1 (≥ 25 bp gain or ≥ 1 pp drawdown improvement with 99% lower bound > 0, ≥ 20 disjoint intervals; the disjoint count is disclosed) **[owner D: v1 thresholds kept]**. The same comparison against `w_F̃(r)` is reported beside it, not gated |
| Where U peaks | distribution of `d*` per `(menu, r)`; share of origins with `d* ≥ 0.25`; reported |
| Which weights | §7: out-of-fold realized `U_1` of each triple's locked mixes under purged CV; probability of backtest overfitting over the five triples; reported |
| Safest mix | max-`Bad` arm vs `U_1` arm: realized Bad-year outcomes and drawdown; reported |
| Line shape | sign and 95% interval of the slope of realized Bad, drawdown and return against `d` at each `r`; reported |
| Engine agreement | share of cells where the two engines select mixes within L1 ≤ .10; paired realized differences; reported |
| Stability (`U_1` only) | v1's across-seed Bad SD and L1 rules, per cell |
| Selection bias | deflated Sharpe ratio (Bailey and López de Prado) of the primary realized comparison given the number of arms and cells; reported |
| Collapsed columns | share of `(menu, origin, r)` with a collapsed line, and on the showcase surfaces the share of the 48 columns; reported for the column-open rule |
| Cost | the §5 cost figures against the production budget: one 48 × 19 surface for an 11-fund menu, and one risk column on demand; informational, never a validity gate |

Labels: **valid experiment** (v1 compliance checks), **white line: max-U supported / not
supported / inconclusive** per menu and engine, everything else descriptive. No equivalence claim.
Stage 2 / ENB stays governed by D4/D7 and is not triggered by this protocol.

## 7. Choosing the U weights (de Prado)

The five triples are arms, so each has its own locked mixes at every cell. After the run, the
realized outcomes of the five arms are compared under combinatorial purged cross-validation over
the origin index (purge = the horizon length, embargo = one month): for each train/test split the
triple with the best in-sample realized `U_1` is chosen and its out-of-sample realized `U_1`
recorded; the report gives the out-of-fold distribution per triple, the rank of the primary triple,
and the probability of backtest overfitting (Bailey, Borwein, López de Prado and Zhu) over the five
candidates. The result informs the product decision; it does not change this run's primary analysis.

Implementation note: the vendored `qse` in this repository carries only `qse.distributions`; the
purged k-fold code lives in the quant-scenario-engine repository under
`qse/experimental/tft/selection/purged_kfold.py`. v2 ports that module with its tests into
`portfoliosight/research/` rather than widening the vendored package.

## 8. Resource ceilings and cost projection

Six workers, one BLAS thread each, aggregate RSS ≤ 4 GiB, **600 s per arm, 240 CPU-hours** for both
engines together (the R33 levels, pre-authorized so an unattended run never stops on a ceiling).

Projection, to be **measured on the six showcase origins before the hash lock** (the `experiment
estimate` command, as v1 R20) and recorded in the manifest. v1's measured cost puts bank scoring
at ≈ 5 ms per evaluation for 23 funds; everything else in v1's 17 s per cell was search-harness
overhead that v2 removes. At ≈ 0.5 s per gradient search (11 funds) and ≈ 0.2 s (5 funds):

| Component, per engine | research2003 | TSP |
|---|---|---|
| Searches: cells × 6 arms × 3 starts | 5,712 × 18 ≈ 103k ≈ 14 CPU-h | 5,856 × 18 ≈ 105k ≈ 6 CPU-h |
| Stability seeds (4 × `U_1` arm) | ≈ 2.5 CPU-h | ≈ 1 CPU-h |
| Showcase surfaces (6 origins × 48 × 19) | ≈ 1 CPU-h | ≈ 0.3 CPU-h |
| GARCH fits (per fund and origin, once) | ≈ 1 CPU-h | ≈ 0.3 CPU-h |

Both engines, with anchors, comparators and independent evaluation: ≈ 55 CPU-h, ≈ 9 h wall on six
quiet workers. If the six-origin measurement projects more than 120 CPU-h, the starts per cell drop
from three to two before anything else is cut, and the report records it.

## 9. Development workflow (no Conductor)

- **Branch**: `feature/fixed-risk-experiment` from `feature/return-optimization-experiment` (v1's
  code, unmerged), in the same worktree. v1's branch is left untouched as the record of the v1 run.
- **Tests**: scoped runs only (`tests/research/`, plus the engine test module of any touched
  `engine/` file) during the build; the full suite once, before any merge to `main`.
- **Codex**: at most three read-only reviews of the diff, instructed to run no tests; no
  specification review beyond the owner's own Codex pass on this document.
- **Effort**: planning and review at high effort; implementation agents at low or medium effort
  with the protocol section they implement as the brief.
- **Build in parallel** (four independent pieces, one agent each):
  1. optimizer: smoothed quantiles with gradients, SLSQP under the bands, three starts, the
     agreement check against v1's COBYLA (`research/search.py`, `research/selection.py`);
  2. data: fetch the eight ETFs, register `research2003`, per-menu ledger start, 3-year lookback,
     CPI series, snapshot re-freeze (`research/harness.py`, `data/`, snapshot tooling);
  3. engine: `garch` through `research.evaluate.bank(engine=...)`, fits per fund and origin on the
     origin-cut window only (never the builder's full-lake panel), named convergence failures;
  4. measurements and report: comparators incl. shrunk-μ frontier, monthly rebalancing and cost
     variant, `d(w)`, multi-year, real, regime buckets, deflated Sharpe, purged CV, cost table,
     showcase surfaces.
- **Day one gate**: pieces 1 and 2 run the six-origin measurement and the agreement check; the
  owner's Codex findings are folded in; the protocol is hash-locked; the snapshot is frozen.
- **Run in two stages**: replay as soon as pieces 1, 2 and 4 pass scoped tests; GARCH when piece 3
  lands. Sensitivities: the 5-year lookback at the six showcase origins only.
- **Not on the path**: phase 3 closure, the v1 branch's phase PR, the 6.4/6.5 engine-validation
  report (the paired engine comparison here is most of it), phases 4 and 5.

Estimate: build 1.5 days with the four agents in parallel; run one night (both engines if the
projection holds); report half a day. About three days end to end.

## 10. Owner decisions (resolved 2026-10-22)

Round 1:

- **A.** Searched `d` cells: the free cell and `{0.25, 0.50, 0.75}`; `d = 0` and `d = 1` are the
  anchors.
- **B.** Multi-seed stability on the primary max-`U` arm only.
- **C.** Real returns included, CPI from FRED frozen into the snapshot (`CPIAUCNS`).
- **D.** Realized-support thresholds: v1's kept and reported with the disjoint-interval count.

Round 2:

- **E.** Example proxy backfill rejected in favour of a long-history research menu (§3a); the
  Example preset is not a research subject in v2.
- **Lookback**: 3 years primary, 5 years as a six-origin sensitivity.
- **Arms**: five U triples and max-`Bad`; Typical, Good and the MDP/min-variance/equal-weight
  references dropped; MDP kept as the slider's normalizer only.
- **Speed**: smooth objective with gradients, warm starts, no per-call recording, per-fund GARCH
  fits; GPU optional under the §4 decision rule.
- **Risk columns**: six for the main grid; the full 48-column surface at six showcase origins.
- **Records**: ADRs 0001–0004 and the spec and plan annotations are drafted now, marked contingent
  on the post-experiment product decision.
