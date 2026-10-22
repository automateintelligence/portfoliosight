# Fixed-risk optimization experiment protocol (v2) — DRAFT for independent review

Status: draft, 2026-10-22 (owner decisions of 2026-10-22 applied; see §10). Not hash-locked.
Next step: the owner runs the Codex review; findings are folded in; then the hash lock.

Supersedes the selection geometry of the
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

Primary (the white line): at a fixed risk `r`, does the mix with the highest `U` on that risk line
beat the max-expected-return mix at the same risk (today's frontier) in realized outcomes? v1 could
not answer this because its `w_R` and frontier sat at different risks.

Secondary:

1. Where along the line does `U` peak? The free cell (§2) reports the diversification level `d*`
   of the line's max-`U` mix at every `(menu, origin, r)`. If `d*` is usually interior, the
   owner's reading (2026-10-21: "if the best mix at `(r, d = 0.3)` has a higher `U` than at
   `(r, d = 0)`, that is reducing downside risk") is confirmed by measurement.
2. How far apart are the max-`B`, max-`T`, max-`G` and max-`U` mixes at the same `(r, d)`? If they
   coincide, the U weights do not matter; if not, the realized outcomes of each tell which component
   carries out-of-sample value, and the U weights are then chosen under purged cross-validation
   (§7), not by eye.
3. Along the fixed-risk line, how do realized Bad, drawdown and return change with `d`? v1's slider
   endpoints (max-return vs MDP at the same `σ`) showed the more-diversified mix with the *worse*
   model Bad and no better realized downside at every risk level; v2 measures the interior.
4. Engine dependence: the same questions under History replay and under the GARCH(1,1)-t FHS engine
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
w_F(r)    = argmax_{w ∈ F(r)} μ_s'w                                   (frontier mix at r; slider top, d = 0)
w_MDP(r)  = argmax_{w ∈ F(r)} Σ_i σ_i w_i                             (MDP at r; slider bottom, d = 1)
M_d(r)    = M(w_F(r)) + d · (M(w_MDP(r)) − M(w_F(r)))                  (the measure level the slider asks for)
F(r, d)   = { w ∈ F(r) : |M(w) − M_d(r)| ≤ τ_d · (M(w_MDP(r)) − M(w_F(r))) }
d(w)      = (M(w) − M(w_F(r))) / (M(w_MDP(r)) − M(w_F(r)))            (where a mix sits on the slider)
Arms      U: argmax_{w ∈ F(r,d)} U(w)     B: argmax B(w)     T: argmax T(w)     G: argmax G(w)
Free cell argmax over F(r) itself (no d band); its d(w) is reported as d*
```

`d = 0` and `d = 1` are the anchors `w_F(r)` and `w_MDP(r)`: they are computed for every
`(menu, origin, r)` because they define the measure span, so the slider's ends are reported at no
search cost. The searched cells are the free cell and the interior levels of §3.

Tolerances **[choice, in-the-weeds]**: `τ_r = 0.01` (1% of `r`, so a 10% risk line admits
9.9–10.1%), `τ_d = 0.025` (2.5% of the measure span at that `r`). Both are recorded in the manifest
and are not tuned after data. If `M(w_MDP(r)) − M(w_F(r)) ≤ 1e-6` the line collapses to one `d`
cell, labelled as in v1 §3.

No dominance filter, admissibility guards, allowance or Stage B: each arm is one argmax on its own
objective. "Found" remains the honest label (v1 §5 step 6: sampled percentiles are piecewise
constant; the search is bounded, not certified).

Slider semantics served after C8 **[product decision, owner]**: position `d` selects the max-`U` mix
in `F(r, d)`; the ends are `w_F(r)` and `w_MDP(r)`. The chart's white line is the locus of `w_F(r)`
(today) or of the free cell's max-`U` mix, as C8 decides from the primary result. The label "every
step down gives up return for diversification" stays truthful only if the report confirms U falls
with `d` past `d*`; the report states the measured shape.

## 3. Grid, origins, menus, engines

- Risk levels: `r ∈ {X(.25), X(.50), X(1)}` with `X(a) = σ_min + a·(σ(w_top) − σ_min)` exactly as
  v1 §3, now used as fixed risks instead of ceilings.
- Diversification cells for the experiment **[owner, 2026-10-22]**: the free cell and
  `d ∈ {0.25, 0.50, 0.75}`; `d = 0` and `d = 1` come from the anchors. Four searched cells per
  `(menu, origin, r)`, four arms each. The product's precompute walks `d = 0 : 0.05 : 1` (§8).
- Engines: `replay` (v1 §5 step 1, unchanged) and `garch` (spec §4.3: `fit_garch_t_panel`,
  `simulate_fhs_panel`, long-run start, residual pool from the training window only). Each engine
  has its own 2,000 × 252 bank per `(menu, origin, engine, replicate)` with v1's seeds; a GARCH fit
  that fails to converge at an origin is a named failure of that engine's cells (v1 taxonomy), never
  a silent substitution of replay.
- Optimizer replicates **[owner, 2026-10-22]**: primary seed `20261013` for every primary statistic;
  seeds `20261014..17` for the stability diagnostics of the max-`U` arm only.
- Menus, lookback (5y), calendar, maturity, leakage rules, realized denominators: v1 §4 unchanged
  except the origin schedule below.

### 3a. Origins and data history (new)

v1 scheduled 99 monthly origins, 2018-06 to 2026-09, for both menus. The limit is not the data
providers: Tiingo serves VGSTX from 1985, VTI from 2001, and tsp.gov serves the five TSP funds from
2003-06. The limit is the Example menu's youngest fund, VWOB (first price 2013-06-04), plus the
5-year training window with the 90% complete-rows rule: the first origin at which every Example fund
has a full window is 2018-06. TSP was then held to the same schedule so the two menus shared origins.

v2 schedules each menu on its own eligible origins:

- **TSP**: ledger from 2003-06 (the funds' first price); first eligible origin 2008-06; ≈219 monthly
  origins through 2026-09, ≈18 disjoint realized years including 2008-09, 2011, 2013, 2015-16,
  2018 Q4, 2020 and 2022. Cost is small (TSP searches run ≈2 s per arm). Requires the ledger start to
  be per menu (harness change, small).
- **Example, proxy backfill** **[standing rule: realism when cost-effective; opt-out in §10 E]**:
  the six funds listed after 2007-10 are spliced onto an asset-class proxy for the dates before their
  own first price, total-return to total-return, with the proxy's return series scaled by nothing
  (plain splice, the industry convention):

  | Fund | First price | Proxy | Proxy first price | Note |
  |---|---|---|---|---|
  | VWOB | 2013-06 | PCY | 2007-10 | both USD EM sovereign |
  | DBJP | 2011-06 | EWJ | 1996-03 | EWJ is unhedged; the splice carries yen exposure before 2011 |
  | VTIP | 2012-10 | TIP | 2003-12 | TIP has roughly twice the duration |
  | SCHF | 2009-11 | VEA | 2007-07 | same asset class |
  | SCHO | 2010-08 | SHY | 2002-07 | same asset class |
  | LTPZ | 2009-09 | TIP | 2003-12 | TIP has roughly half the duration |

  The spliced union begins 2007-10; first eligible origin 2012-10; ≈167 origins, ≈14 disjoint
  realized years (adds 2013 taper, 2015-16, 2018 Q4). The 2008 crash is still outside the Example
  menu's realized record at a 5-year lookback. Every cell whose training window straddles a splice
  date is flagged `spliced_window` in the origins ledger and the report shows each headline with and
  without those cells. Proxies are fetched through the existing Tiingo provider into the lake and
  frozen into the snapshot; the splice rule, proxy table and the first real date of each fund are
  recorded in the manifest. If the owner opts out (§10 E), Example keeps its 99 origins.

  Not chosen: a shorter lookback for Example (v1 sensitivity (c) measured it) and deeper proxies
  (EFA for VEA, 2001) that would reach 2008; both change the estimator or the menu's meaning more
  than a plain splice and are noted for v3.

- Cells: Example `167 × 3 r × 4 cells` = 2,004 (99 origins: 1,188); TSP `219 × 3 × 4` = 2,628;
  per engine, four arms each; anchors per `(menu, origin, r)` shared across cells.

## 4. Search (amends v1 §5 steps 3–7)

1. Anchors per `(menu, origin, r)`: `w_F(r)` (cap-constrained max-`μ_s` on the risk band, the
   existing greedy/`w_top` machinery projected to the band) and `w_MDP(r)` (v1 step 3 program with
   `σ ≤ r` replaced by the band; CVXPY/Clarabel). The fixed-risk ladder of the demo design
   (`engine/ladder.py`: most diversified mix at risk `r` earning at least return `y`) sweeps `M`
   monotonically from `M(w_F)` to `M(w_MDP)` as `y` falls; its level nearest `M_d(r)` is the third
   anchor for each `d` cell, and all its levels seed the free cell.
2. Broad proposals: v1's 1,024 scrambled Sobol points, each moved onto the risk band by bisection
   along the segment toward `w_min` (below `r`) or toward `w_top` (above `r`), then kept only if
   inside `F(r, d)` (all of them for the free cell); the retained set is shared by the four arms. If
   fewer than 64 proposals land in a `(r, d)` cell, draw a second 1,024 block with the seed offset
   recorded; if still fewer than 64, the cell is `infeasible_band` (named, counted, never silently
   widened).
3. Local refinement: six starts per arm from the shared feasible pool by descending objective with
   the v1 L1 ≥ .10 spacing rule, the ladder anchor always included; COBYLA with the band constraints
   as inequalities, `rhobeg .05`, `tol 1e-5`, `catol 1e-8`; budget 128 calls per start **[choice]**,
   justified by the v1 convergence analysis (k = 120 reached within 0.5 bp of the full 384-call
   result in 95–98% of cells and within 2.5 bp in 99–100%).
4. Union and rescoring as v1 step 7, then each arm's argmax on the union restricted to its cell;
   native-search selections reported as diagnostics.
5. Lock before evaluate: v1 step 8 unchanged; independent banks `20261113..17` per engine.

## 5. Measurements (adds to v1 §6)

Per locked selection, under both engines where applicable: training and independent-bank
`B/T/G/U/mean/ES_2.5`, `σ`, `M`, `d(w)`, `μ_s'w`, weights, turnover to the previous origin; realized
one-year outcomes as v1; plus:

- **Multi-year realized**: compounded 3- and 5-year outcomes from the same origin with the locked
  weights held at constant target (daily rebalanced, as v1), for the origins whose horizons are
  complete. Reported beside the 1-year figures; disjoint-interval counts stated, so these are
  descriptive, never gated.
- **Real returns** **[owner, 2026-10-22: include]**: the 1-, 3- and 5-year outcomes deflated by
  CPI-U, all items, not seasonally adjusted (FRED `CPIAUCNS`, the series TIPS indexation uses and
  the one FRED does not revise), fetched as FRED's public CSV and frozen into the snapshot with its
  vintage date. Deflator for a horizon = index of the horizon's last month over index of its first
  month; evaluation only, so publication lag is not a leakage concern. Reported for every arm and
  reference.
- **Regime buckets**: each realized year labelled by the horizon's realized equity drawdown and
  10-year yield change (buckets: calm / equity drawdown ≥ 15% / rate shock ≥ 150 bp; thresholds
  fixed here), with each arm's outcomes reported per bucket. Descriptive.
- **Forecast calibration** as v1 (coverage and pinball per quantile), per engine, per arm.

## 6. Predeclared criteria (replaces v1 §7's R+D criteria)

All comparisons are paired within `(menu, origin, r, cell, engine)` with v1 §6's block bootstrap.

| Question | Criterion, each menu and engine separately |
|---|---|
| White line (primary) | free-cell max-`U` vs `w_F(r)`: pooled independent-bank mean ΔU ≥ 5 bp with ≥ 4/5 banks positive; realized guardrails of v1 (median and mean annual-return loss ≤ 25 bp, loss frequency +≤ 5 pp, mean drawdown worsening ≤ 1 pp); realized support as v1 (≥ 25 bp gain or ≥ 1 pp drawdown improvement with 99% lower bound > 0, ≥ 20 disjoint intervals; disclosed as unmet where the menu has fewer) **[owner D, 2026-10-22: keep v1's thresholds, report the disjoint count]** |
| Where U peaks | distribution of `d*` per `(menu, r)`; share of origins with `d* ≥ 0.25`; reported |
| Component spread | median pairwise L1 among the U/B/T/G argmaxes at the same cell; reported, no threshold |
| Line shape | sign and 95% interval of the slope of realized Bad, drawdown and return against `d` at each `r`; reported |
| Engine agreement | share of cells where the two engines select mixes within L1 ≤ .10; paired realized differences; reported |
| Stability (max-`U` only) | v1's across-seed Bad SD and L1 rules, per cell |
| Selection bias | the deflated Sharpe ratio (Bailey–López de Prado) of the primary realized comparison given the number of arms and cells compared; reported |
| Cost | warm per-cell search wall at the 128-call budget, reported against the precompute budget of §8 (p95 ≤ 25 s Example, ≤ 3 s TSP); informational, never a validity gate |

Labels: **valid experiment** (v1 compliance checks), **white line: max-U supported / not
supported / inconclusive** per menu and engine, everything else descriptive. No equivalence claim.
Stage 2 / ENB stays governed by D4/D7 and is not triggered by this protocol.

## 7. Choosing the U weights (new; de Prado)

The U weights are hyperparameters. After the run, evaluate candidate weight triples on the
**locked B/T/G argmax outcomes and the max-U outcomes already computed** (no new searches) under
combinatorial purged cross-validation over the origin index (purge = horizon length, embargo = one
month), report the distribution of out-of-fold realized U for each triple and the probability of
backtest overfitting for the number of triples tried. The triples are predeclared:
`(.60,.30,.10)`, `(.70,.20,.10)`, `(.50,.35,.15)`, `(.80,.15,.05)`, `(.40,.40,.20)`. The result
informs C8; it does not change this run's primary analysis.

Implementation note: the vendored `qse` in this repo carries only `qse.distributions`; the purged
k-fold and conformal code lives in the quant-scenario-engine repo under
`qse/experimental/tft/selection/purged_kfold.py`. v2 ports that module (≈100 lines, with its tests)
into `portfoliosight/research/` rather than widening the vendored package.

## 8. Resource ceilings, cost estimate, and the product's precompute

Six workers, one BLAS thread each, aggregate RSS ≤ 4 GiB, **600 s per arm, 240 CPU-hours** for both
engines together (the R33 levels, pre-authorized by the owner so an unattended run never stops on a
ceiling). Estimate from v1's measured search cost (Example R arm: median 26.5 s, p95 65 s at a median
1,156 calls; TSP 2.1 s / 3.6 s at 294 calls), scaled to 768 calls per arm (6 starts × 128):

| Component | Example (167 origins) | TSP (219 origins) |
|---|---|---|
| Searched cells × arms, per engine | 2,004 × 4 × ≈17 s ≈ 38 CPU-h | 2,628 × 4 × ≈2 s ≈ 6 CPU-h |
| Stability seeds (4 × max-U arm) | ≈ 9 CPU-h | ≈ 1.5 CPU-h |
| Both engines, plus anchors, unions, independent evaluation | ≈ 100 CPU-h | ≈ 16 CPU-h |

≈ 115 CPU-h in all (≈ 70 CPU-h if Example keeps 99 origins); ≈ 20 h wall on six quiet workers.
The `experiment estimate` command must be run on the frozen snapshot before the hash lock and its
projection recorded, as in v1 (R20). Stop rules and incomplete labelling as v1/R31–R33.

**The product's precompute** (owner question, 2026-10-22): the app's surface has `NX = 48` risk
columns. Walking `d = 0 : 0.05 : 1` is 19 interior searches per column (the ends are the anchors):
912 searches per menu per data refresh. At v2's budget that is ≈ 4.3 CPU-h for an Example-sized
menu (≈ 45 min on six workers) and ≈ 30 CPU-min for TSP (≈ 5 min). That is an acceptable nightly
precompute for the preset menus; it is not a 30-second interactive computation for a user-supplied
menu at any `d` step, because even three interior levels cost ≈ 40 CPU-min for Example. The
interactive case needs a different design (warm-starting along the line from neighbouring cells,
fewer starts, or a server-side queue) and belongs to phase 4's design, informed by this report's
cost table.

## 9. Development workflow (replaces the Conductor prerequisites)

The owner's direction (2026-10-22): this is research, not production development; Conductor is not
used; go fast.

- **Branch**: `feature/fixed-risk-experiment` from `feature/return-optimization-experiment` (v1's
  code, unmerged), in the same worktree. v1's branch is left untouched as the record of the v1 run.
- **Tests**: scoped runs only (`tests/research/`, plus the engine test module of any touched
  `engine/` file) during the build; the full suite once, before any merge to `main`.
- **Codex**: at most three read-only reviews of the diff, instructed to run no tests; no
  specification review beyond the owner's own Codex pass on this document.
- **Effort**: planning and review at high effort; implementation agents at low or medium effort
  with the protocol section they implement as the brief.
- **Build in parallel** (four independent pieces, one agent each):
  1. search: band constraints, free cell, four arms, ladder-seeded starts (`research/search.py`,
     `research/selection.py`);
  2. data: per-menu ledger start, proxy splice and `spliced_window` flag, CPI series in the
     snapshot (`research/harness.py`, `data/`, snapshot tooling);
  3. engine: `garch` through `research.evaluate.bank(engine=...)` with `shape.simulate_panel` and
     `engine.ranges.garch_range_model` per origin window, named convergence failures;
  4. measurements and report: `d(w)`, multi-year, real, regime buckets, deflated Sharpe, purged
     CV weight sweep, cost table.
- **Run in two stages**: the replay engine starts as soon as pieces 1, 2 and 4 pass scoped tests
  and `experiment estimate`; the GARCH engine runs when piece 3 lands. Replay results are read while
  GARCH computes. Sensitivities: budget only (the 128-call choice); coefficients are covered by §7
  and lookback by v1.
- **Lock**: the protocol's SHA-256 and the code head go into the manifest as v1 did; the snapshot is
  re-frozen once, when the proxies and CPI are in the lake.
- **Not on the path**: phase 3 closure, the v1 branch's phase PR, the 6.4/6.5 engine-validation
  report (the paired engine comparison here is most of it), phases 4 and 5.

Estimate: build 1.5 days with the four agents in parallel and the owner's Codex pass folded in;
run ≈ 1 night for replay and ≈ 1 night for GARCH; report half a day. About four days end to end.

## 10. Owner decisions (resolved 2026-10-22) and one opt-out

- **A.** Searched `d` cells: the free cell and `{0.25, 0.50, 0.75}`; `d = 0` and `d = 1` are the
  anchors (resolved: owner chose `{0.25, 0.5, 0.75}`; the ends come free, see §2).
- **B.** Multi-seed stability on the max-`U` arm only (resolved: yes).
- **C.** Real returns included, CPI from FRED frozen into the snapshot (resolved: yes; series
  `CPIAUCNS`, §5).
- **D.** Realized-support thresholds: v1's kept and reported with the disjoint-interval count
  (resolved by the standing rule: predeclared and disclosed beats descriptive-only).
- **E. Opt-out, y/n**: Example proxy backfill (§3a) is on by default under the realism rule. Say
  "no backfill" to keep the Example menu to its own 99 origins; cost of keeping it on is ≈ half a
  day of build and ≈ 30 CPU-h of run, and the backfilled years are proxy history, disclosed as such.
