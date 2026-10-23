# Fixed-risk optimization experiment protocol (v2) — DRAFT for independent review

Status: draft, revision 5, 2026-10-23. Owner decisions of 2026-10-22/23 (five rounds), the owner's
Codex review of revision 2 (seven findings, three interpretation notes, two ADR findings) and of
revision 3 (eight findings) applied; see §10. Not hash-locked. Open before the lock: the third Codex
pass (this revision) and the six-origin measurement (§8).

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
   owner's reading (2026-10-21: the best mix at `(r, d = 0.3)` beating the best at `(r, d = 0)`
   on `U`) is confirmed by measurement. A higher `U` does not by itself mean a lower downside: a
   10 bp worse Bad and a 30 bp better Typical raise `U_1` by 3 bp. The report therefore shows
   ΔBad, ΔES and drawdown beside ΔU wherever `U` is compared **[Codex, 2026-10-22]**. If the free
   cell concentrates the way v1's `w_R` did, the report says so and the interior cells show what a
   minimum-diversification band costs.
2. Which U weights hold up out of sample? Four predeclared weight triples run as arms (§2) and are
   compared under combinatorially symmetric cross-validation (§7). Max-`Bad` runs as a sixth arm:
   the mix that maximizes the 2.5th percentile year at this risk (not "the safest" in any wider
   sense; its drawdown and ES are measured, not assumed).
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
  `w_MDP(r)` the mix on that line with the highest measure `M`. They are the slider's two ends. The
  MDP is used only to set the slider's length; it is not a reference portfolio in this experiment.
- `M(r, d)` is the **diversification level the slider asks for**: slide a fraction `d` of the way
  from the frontier mix's measure to the most-diversified mix's measure. (Written `M_d(r)` in
  revision 2; same quantity.)
- `F(r, d)` is the **set of mixes at that slider position**: the mixes on the risk line whose
  measure is within 2.5% of the span of `M(r, d)`. The cell the optimizer searches.
- `d(w)` is where any mix sits on the slider: 0 at the frontier mix's measure, 1 at the MDP's.

How many mixes are in these sets: they are continuous regions, so infinitely many. With `n` funds
the allowed mixes form an `(n−1)`-dimensional region; the risk band is a thin slab of dimension
`n−2`, and `F(r, d)` a slab of dimension `n−3` inside it. On a 5%-step weight grid the 11-fund menu
has ≈ 30 million mixes; a mid-table risk band holds on the order of 1% of them and the slider band
a few percent of those. Both counts collapse toward zero at the lowest and highest attainable
risks, which is why collapsed columns are counted (§2 end) and starts are labelled, never
inferred as infeasibility (§4).

Formally, for menu bounds `min ≤ w ≤ max`, `1'w = 1`, a fixed risk `r`, a level `d ∈ [0, 1]`, an
engine `e` and the shared draw:

```
σ(w)      = sqrt(w' Σ w), Σ the origin's training covariance (v1 §2 estimator, unchanged)
M(w)      = DR²(w) = (Σ_i w_i σ_i)² / (w' Σ w)                       (v1 D5, unchanged)
F(r)      = { w : bounds, 1'w = 1,  |σ(w) − r| ≤ τ_r · r }           (a band, not a ceiling)
w_F(r)    = argmax_{w ∈ F(r)} μ_s'w                                   (frontier mix at r; slider top, d = 0)
w_MDP(r)  = argmax_{w ∈ F(r)} M(w)                                    (most diversified at r; slider bottom, d = 1)
M(r, d)   = M(w_F(r)) + d · (M(w_MDP(r)) − M(w_F(r)))
F(r, d)   = { w ∈ F(r) : |M(w) − M(r, d)| ≤ τ_d · (M(w_MDP(r)) − M(w_F(r))) }
d(w)      = (M(w) − M(w_F(r))) / (M(w_MDP(r)) − M(w_F(r)))
Arms      U_k: argmax_{w ∈ F(r,d)} U_k(w), k = 1..4 (triples below);   B: argmax_{w ∈ F(r,d)} Bad(w)
Free cell every arm's argmax over F(r) itself (no d band); the winner's d(w) is reported as d*
```

Arms **[owner, 2026-10-22; reduced to five arms 2026-10-23]**: the four U weight triples
`(.60,.30,.10)` (primary, `U_1`), `(.70,.20,.10)`, `(.50,.35,.15)`, `(.40,.40,.20)`, and max-`Bad`.
The `(.80,.15,.05)` triple of revisions 2–4 is dropped: at 80% on the bad year it behaves like
max-`Bad`, which stays. Max-Typical and max-Good are dropped (Typical at a fixed risk tracks the
frontier; Good rewards concentration).
MDP, minimum variance and equal weight are no longer evaluated as reference arms; the two
comparators are `w_F(r)` and the shrunk-μ frontier `w_F̃(r)` of §5.

`w_MDP(r)` maximizes `M` itself, not its numerator `Σ_i σ_i w_i` **[Codex, 2026-10-22]**: the
two agree only at an exact risk, and inside a band the denominator moves (two uncorrelated funds at
10% and 30% volatility, band 19.8–20.2%: the numerator's maximum sits at the upper edge with
`DR² = 1.328`, the lower edge has `1.348`). `M` is a ratio of quadratics, so both anchors are
nonconvex programs under the band's lower edge; each is solved by SLSQP from eight starts (the
bound corners nearest the band, the equal-weight mix projected onto the band, and five Sobol points
projected by bisection) and the best feasible answer is kept. The anchor search is recorded like an
arm (starts, iterations, final mix) and "found" applies to it too.

Tolerances **[choice, in-the-weeds]**: `τ_r = 0.01`, `τ_d = 0.025`, recorded in the manifest and
not tuned after data. If `M(w_MDP(r)) − M(w_F(r)) ≤ 1e-6` the line collapses to one cell, labelled
as in v1 §3; the share of collapsed columns per menu is reported (it sets the product's
column-open rule, ADR 0001).

**Same band is not same risk** **[Codex]**: two mixes in `F(r)` can differ in volatility by up to
`0.02 r`, which at `r = 10%` is 20 bp of risk against a 5 bp utility threshold. Every selection's
`σ(w)` is recorded; every paired comparison reports the risk difference between the two mixes beside
ΔU; and at the six showcase origins the primary comparison is repeated with `τ_r = 0.001` (exact
risk to within 1 bp at `r = 10%`) as a predeclared sensitivity. If the sign of the pooled ΔU differs
between the two tolerances the white-line label is "inconclusive" for that menu and engine.

No dominance filter, admissibility guards, allowance or Stage B: each arm is one argmax on its own
objective. "Found" remains the honest label (the objective is sampled; the search is bounded, not
certified), now with the agreement check of §4.

Slider semantics served after the product decision **[owner]**: position `d` selects the max-`U`
mix in `F(r, d)`; the ends are `w_F(r)` and `w_MDP(r)` **as anchor exceptions**, by definition and
not by maximization **[Codex, revision 3 finding 8]**: a band around an anchor's measure can hold
a mix with a higher `U`, since equal diversification does not mean equal weights. At the six
showcase origins the max-`U` mix of the `d = 0` and `d = 1` bands is also searched and the `U` gap
to each anchor is reported, so the product decision knows what the exception costs. The white line
is the locus of `w_F(r)` (today) or of the free cell's max-`U` mix, as the decision records from
the primary result. `d(w)` is unbounded: the frontier mix is not the least-diversified mix on the
line, so a free-cell winner can have `d* < 0` (or `> 1`); such values are reported as they are, with
the share of free-cell winners outside `[0, 1]` per menu and `r`.

## 3. Grid, origins, menus, engines

- Risk levels **[owner, 2026-10-22: need not exceed the app's 48 columns; six for the main grid]**:
  `r ∈ {X(a) : a ∈ {.10, .25, .40, .55, .70, .85}}`, `X(a) = σ_min + a·(σ(w_top) − σ_min)` as v1
  §3, used as fixed risks. The extreme `a = 1` is omitted: its band holds only the max-return corner.
- Diversification cells: the free cell and `d ∈ {0.25, 0.50, 0.75}`; `d = 0` and `d = 1` are the
  anchors. Four searched cells per `(menu, origin, r)`, five arms each.
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
  for the stability diagnostics of the `U_1` arm only, run on **every fourth scheduled origin**
  (indices `0, 4, 8, …`; ≈ 62 per menu) **[owner, 2026-10-23]**: five banks per cell there, the
  same across-seed Bad SD and L1 rules as v1, a quarter of the cost of every origin. Stability is a
  diagnostic, never a gate.
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
Example preset is a product menu, not a sacred research subject, and a menu with history to 2003
gives three times the realized years. The manifest (R2, read 2026-10-22) holds 1,668 symbols, 783
of them with prices from before 2004 (656 individual stocks). The owner asked for 15–20 tickers
including individual stocks and chose **option a** (round 3, §10): the eleven funds plus nine
stocks, 10% cap per stock.

**Survivorship** **[realism rule]**: stocks picked today from the set that has traded since 2003
are the survivors, which flatters every arm's realized return. The nine stocks are therefore chosen
as a 2003 investor would have, by end-2003 US market capitalization, and the list keeps the ones
that later did badly (GE, C, PFE, INTC). WMT, the one top-ten name missing, is not in the manifest.

| Ticker | Role | First price (manifest) |
|---|---|---|
| SPY | US large-cap equity | 1995-01 |
| IWM | US small-cap equity | 2000-05 |
| IWD | US large-cap value | 2000-05 |
| EFA | Developed ex-US equity | 2001-08 |
| EEM | Emerging-market equity | 2003-04 |
| IYR | US real estate | 2000-06 |
| TLT | Long US Treasuries | 2002-07 |
| IEF | Intermediate US Treasuries | 2002-07 |
| SHY | Short US Treasuries | 2002-07 |
| LQD | Investment-grade corporates | 2002-07 |
| VIPSX | US inflation-linked (Vanguard fund, replaces TIP; see below) | 2000-06 |
| MSFT, XOM, GE, PFE, C, INTC, IBM, JNJ, PG | 2003 US mega-caps | 1995-01 each |

**TIP → VIPSX** **[Codex finding 6; owner confirmed 2026-10-23, for the whole history, no
splice]**: TIP's first price is 2003-12, so
the first 3-year origin would be 2006-12 and only 19 disjoint realized years fit before the data
end (2026-09); the 20-interval realized-support gate the owner kept (decision D) would be
unreachable by construction. VIPSX tracks the same asset class from 2000-06. With it the youngest
ticker is EEM (2003-04), the first origin 2006-04, and twenty disjoint years end 2026-04. The
exact count is computed from the frozen ledger before the lock and recorded in the manifest; if it
is below 20 for either menu, the report says the realized-support criterion was not attainable
rather than failed.

The tickers not in the lake are fetched through the existing Tiingo provider, frozen into the
snapshot, and the menu is registered as a research preset (`research2003`), not a product preset.
Caps **[owner, option a]**: 0–40% per fund, 0–10% per stock, recorded in the manifest. The
gradient objective is linear in the number of holdings, so 20 tickers roughly doubles the
per-evaluation cost of the 11-fund projection in §8; the six-origin measurement is made on the
final menu.

Schedules, each menu on its own eligible origins:

| Menu | Holdings | Ledger from | First origin (3y) | Origins to 2026-09 | Disjoint realized years |
|---|---|---|---|---|---|
| research2003 | 20 | 2003-04 | 2006-04 | ≈ 246 | 20 if the ledger confirms (2006-04 … 2026-04), including 2007-09, 2011, 2013, 2015-16, 2018, 2020, 2022 |
| TSP | 5 | 2003-06 | 2006-06 | ≈ 244 | 20 if the ledger confirms (2006-06 … 2026-06) |

Requires the ledger start to be per menu (harness change, small). Cells per engine:
research2003 `246 × 6 r × 4` = 5,904; TSP `244 × 6 × 4` = 5,856; five arms each.

## 4. Search (replaces v1 §5 steps 3–7)

**Gradient objective** **[owner, 2026-10-22; corrected per Codex]**. For a mix `w` the bank gives
one compounded year `R_p(w)` per path, and each `R_p` is a smooth function of `w`. A sample
quantile of the 2,000 years is therefore **piecewise smooth, not flat**: between rank crossings its
gradient is the gradient of the one path holding that rank, and it has kinks where two paths swap
ranks. (Revision 2 and ADR 0004 called it "flat between paths"; that was wrong and is withdrawn.)
v1's derivative-free search did not use these gradients; v2 does. Two search objectives are
carried to the agreement check and the better one runs the experiment:

- **Exact-quantile gradient**: `Q_q(w)` is the evaluator's own estimator, NumPy's linear
  interpolation (`engine/ranges.py` records `percentile_method: "linear"`): with the years sorted
  `R_(1) ≤ … ≤ R_(P)`, `j = ⌊q (P − 1)⌋` and `f = q (P − 1) − j`, `Q_q = (1 − f) R_(j+1) + f R_(j+2)`;
  for `P = 2,000` and `q = 0.025` that is `0.025 R_(50) + 0.975 R_(51)`. Its gradient is the same
  two-weight combination of the two paths' `∂R_p/∂w` (at a tie, the mean gradient of the tied
  paths). Two path gradients per quantile; cheapest; kinked. The search objective and the reported
  figure are the **same estimator** **[Codex, revision 3 finding 1]**; an order-statistic shortcut
  (`R_(⌈qP⌉)`) is not used anywhere.
- **Kernel-smoothed quantile**: `Q̃_q(w)` is the Gaussian-kernel-weighted average of the sorted
  years, bandwidth `h = 0.01` in rank fraction (≈ 20 of 2,000 paths), centred on `q` **[choice]**;
  its gradient is the same kernel weighting of the paths' gradients at their current ranks. This
  averages the kinks over ≈ 20 paths; it does not remove them (rank crossings still move the
  weights), so it is a smoother objective, not a globally smooth one.

`B, T, G` are the quantiles at 0.025, 0.5, 0.975; `U_k` the triple's combination. Every reported
figure (`B/T/G/U`, the lock, every comparison) is the **exact** sampled quantile of the final mix;
the search objective is a search device only.

**Engine-specific path gradients** **[Codex finding 1]**. A path's year is
`R_p = exp(Σ_t ln g_pt) − 1` with `g_pt` the day's gross return, and `∂R_p/∂w = (1 + R_p) Σ_t
(∂g_pt/∂w) / g_pt`. What differs is `∂g_pt/∂w`:

- *Replay* (`engine/ranges.py`, count-matrix form): with `A` the sample's recentred daily returns
  (`T × N`), `C` the path-by-day counts (`P × T`) and `g = 1 + A w` (`T`), `R = exp(C ln g) − 1` and,
  for order-statistic (or kernel) weights `a` over paths,
  `∇_w Σ_p a_p R_p = A' [ C' (a ⊙ (1 + R)) / g ]`. No `P × T × N` tensor is formed; the cost is two
  matrix-vector products on the existing `C`.
- *GARCH FHS* (spec §4.3, `_garch_terms`): the mix's day is `y_pt = m'w + k(w) · x_pt'w` with
  `x = R' − R̄'` the centred levelled panel and the weight-dependent scale
  `k(w) = sqrt(w'(Σ/252)w / w'Σ_R' w)`. Then `∂y_pt/∂w = m + k x_pt + (x_pt'w) ∇k`, with
  `∇k = k · ( Σw / (w'Σw) − Σ_R' w / (w'Σ_R' w) )`. The third term is not optional; dropping it is
  the error Codex found in revision 2.
- *Absorbed paths* (GARCH; a day at or below −100%, spec §4.3 `RUIN`): the absorption mask is
  computed from the proposed mix's daily returns **before** any logarithm or division; the path's
  year is exactly −1 and its gradient is defined as zero; it keeps rank −1 in every exact quantile
  and in the kernel average.
- *Invalid replay proposals*: replay has no absorption; a proposed mix with a non-positive
  recentred daily growth on any sample day (`_replay_years` raises `ValueError` today) is returned
  to the optimizer as a named `invalid_proposal` with the constraint violation `min_t g_t` so the
  line search backs off; it is counted per cell and never silently clipped. The check is
  candidate-dependent and stays inside the loop (see speed item 3).

**Gradient verification, predeclared**: before either optimizer is accepted, directional
finite-difference checks on 20 random directions at 10 random feasible mixes per engine and menu,
central differences with step `1e-6`, relative error ≤ `1e-4` on every direction whose
finite-difference magnitude exceeds `1e-8`. A failure blocks the lock for that engine.

**Optimizer**: SLSQP (SciPy) with analytic gradients; equality `1'w = 1`; bounds; the risk band as
two smooth inequalities; the measure band as two more in the interior cells. Maximum 200 iterations,
`ftol 1e-9` **[choice]**. Starts per cell, three, each **deduplicated** (two starts within L1 ≤
`1e-6` count once and a replacement is drawn) **[Codex finding 3]**: (i) the anchor mix nearest
`M(r, d)` moved along the straight line between `w_F(r)` and `w_MDP(r)` and projected back onto the
risk band by bisection (the `engine/ladder.py` ladder is monotone in ENB, not in `M`, so it is
not used as a start source); (ii) the neighbouring cell's solution along `d` (continuation; for the
free cell, `w_F(r)`, `w_MDP(r)` and the best Sobol point); (iii) the best of v1's 1,024 scrambled
Sobol points projected onto the risk band by bisection toward `w_min` or `w_top`, scored once per
`(menu, origin, r)` column and reused by every cell and arm of the column. The arm's answer is the
best exact objective among the starts.

**Cell labels** **[Codex finding 3]**. A sparse Sobol hit count says nothing about feasibility, so
the labels are: `insufficient_starts` (fewer than three distinct feasible starts after one extra
Sobol block with the seed offset recorded; the cell still runs with what it has), `search_failed`
(every start ended outside the bands by more than the solver tolerance), and `not_found` (the
feasibility program `min_{w ∈ F(r)} |M(w) − M(r, d)|` from eight starts never came within
`τ_d · span`). None is called "infeasible": the programs are nonconvex and a search proves nothing
about mixes it did not visit. All three are counted per menu, `r` and `d` and reported.

**Agreement check, predeclared, one per engine** **[widened per Codex finding 5; made per engine
per revision 3 finding 4]**: before each engine's lock (§9), 30 cells of that engine are drawn by
seed from the grid, stratified so that 10 are narrow cells (`d ∈ {0.25, 0.75}`), 15 are
research2003 and 15 TSP. Each is solved on the same banks by (a) the exact-quantile gradient
optimizer, (b) the kernel-smoothed gradient optimizer, (c) v1's COBYLA at 768 calls per start and
(d) COBYLA at 128 calls per start, for both the `U_1` and the max-`Bad` objectives: **60
cell-objective pairs per engine** is the denominator. A gradient optimizer is accepted for that
engine if its exact objective is within 2.5 bp of, or above, (c)'s in at least 57 of the 60 pairs
(95%); if both pass, the cheaper in median wall time runs that engine. If neither passes, (d) runs
that engine only if it meets the same 57-of-60 rule against (c); otherwise (c) itself runs at the
revision-1 cost and the ceilings of §8 govern. The two engines may end with different solvers; the
report states each. Agreement is judged on the objective, not on weights: v1 showed the optimum is
flat in `w` (seed-to-seed L1 up to 0.8 at equal `U`), so differing weights at equal `U` are
expected.

**CPU speed items, in order** **[Codex]**, each measured against the v1 harness on the same cells
before the lock and recorded in the manifest: (1) the replay gradient through the count matrix
above; (2) the GARCH levelled panel `R'` computed once per bank and cached (≈ 44 MB for 11 funds,
≈ 80 MB for 20, float64) instead of re-exponentiated on every call; (3) the optimizer's hot path
separated from reporting: the immutable inputs (bank, moments, bounds) are validated once, digests
and unused summary statistics leave the loop, and the **candidate-dependent checks stay**: each
proposal's daily growth is computed once and reused for the validity check, the compounding and
the gradient (replay's `invalid_proposal`, GARCH's absorption mask) **[Codex, revision 3 finding
2]**; (4) one exact `B/T/G` evaluation per visited mix feeds every `U_k` and the
max-`Bad` objective, and the compact deterministic archive of visited mixes replaces per-call
persistence. v1's one recorded cell (solver 62.9 s against 6.1 s of bank scoring over 1,151 calls)
shows the overhead is large; it does not show that all of it disappears, which is why the items are
measured, not assumed.

**Recording**: starts, iteration counts, the final mix and its exact figures per arm and cell; no
per-call rows (v1 wrote every call into a 2 GB table).

**GPU** **[owner question, 2026-10-22]**: the gradient objective makes the search a batched tensor
operation, so it could run on the local GPU (RTX 2070, 8 GiB) or a rented one (Nscale or Nebius:
RTX 6000, H100, H200, B200 class) with a batched gradient optimizer (all cells, arms and starts of
an origin in one tensor). v2 does not require it: no tensor library is installed and a batched
constrained optimizer is one to two days of extra engineering. The objective and gradient are
written as array code with no SciPy inside, so a `torch` backend can be added later without
changing the protocol. Decision rule **[owner, round 3]**: project on CPU first (§8); if the
measurement projects more than two nights of wall time for the two engines, the GPU path is built
before the run; otherwise not.

Union and rescoring per cell as v1 step 7 (every evaluated mix joins the cell's pool with exact
figures; the arm's selection is the pool's best on its objective inside the cell), with one
addition **[Codex, revision 3 finding 3]**: because every interior cell of a column lies inside
`F(r)`, every mix visited by any interior cell's search on the same bank also joins the **free
cell's** pool before the lock, so the free cell's selection is by construction at least as good on
each arm's objective as every interior winner of its column. The free cell's own-search result is
kept separately as `free_native` so the report can show how often the pooled peak came from an
interior search. Lock before evaluate as v1 step 8; independent banks `20261113..17` per engine.

## 5. Measurements (adds to v1 §6)

Per locked selection, under both engines where applicable: training and independent-bank
`B/T/G/U_1..4/mean/ES_2.5`, `σ`, `M`, `d(w)`, `μ_s'w`, weights, turnover to the previous origin;
plus:

- **Comparators**: `w_F(r)` is today's frontier on the product's `μ_s`, which is **already shrunk**:
  spec §4.3's 50/50 blend of the sample mean `μ̂` and the menu-beta prior (`engine/stats.py`,
  `menu_beta_blend`) **[Codex]**. `w_F̃(r)` is the same program on a Bayes–Stein estimate (Jorion
  1986: `μ̂` shrunk toward the minimum-variance portfolio's return with data-driven intensity)
  applied to `μ̂` **in place of** the blend, not on top of it, so the two comparators are two
  shrinkage rules on the same sample mean **[choice; realism rule]**. Both are evaluated like arms.
  `w_MDP(r)` is recorded (it defines the slider) but not evaluated.
- **Realized convention** **[choice; realism rule]**: the locked weights held with **monthly**
  rebalancing to target becomes the primary realized outcome for the guardrails and the realized
  support (v1 rebalanced daily, which no investor does); daily rebalanced is reported for
  continuity. A **cost variant** charges 10 bp per unit of one-way turnover at each rebalance and
  at each origin's reallocation, reported beside the gross figures. **Forecast calibration uses the
  daily-rebalanced realized year** because that is the strategy the banks simulate; comparing a
  daily-rebalanced forecast with a monthly-rebalanced outcome would mix forecasting error with
  strategy mismatch **[Codex]**.
- **This experiment is not a qualification of the production engine** **[Codex]**: GARCH here is
  fitted on the 3-year training window (§3), where spec §4.3 fits the shape on up to ten years
  independent of the lookback; and the realized convention above differs from the spec's. The
  report labels both differences in its engine section, and the spec's 6.4/6.5 validation stays
  owed.
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
| White line (primary) | free-cell `U_1` arm vs `w_F(r)`: pooled independent-bank mean ΔU ≥ 5 bp with ≥ 4/5 banks positive, with ΔBad, ΔES and the risk difference `σ(w_U) − σ(w_F)` reported beside it and the `τ_r = 0.001` sensitivity of §2 agreeing in sign; realized guardrails of v1 (median and mean annual-return loss ≤ 25 bp, loss frequency +≤ 5 pp, mean drawdown worsening ≤ 1 pp) on the monthly-rebalanced convention; realized support as v1 (≥ 25 bp gain or ≥ 1 pp drawdown improvement with 99% lower bound > 0, ≥ 20 disjoint intervals; the attainable disjoint count is computed from the frozen ledger before the lock and disclosed; if below 20 the criterion is "not attainable", not "failed") **[owner D: v1 thresholds kept; Codex finding 6]**. The same comparison against `w_F̃(r)` is reported beside it, not gated |
| Where U peaks | distribution of `d*` per `(menu, r)`; share of origins with `d* ≥ 0.25`; reported |
| Which weights | §7: out-of-sample realized `U_1` of each triple's locked mixes over the 70 symmetric splits; probability of backtest overfitting over the four triples; reported |
| Safest mix | max-`Bad` arm vs `U_1` arm: realized Bad-year outcomes and drawdown; reported |
| Line shape | sign and 95% interval of the slope of realized Bad, drawdown and return against `d` at each `r`; reported |
| Engine agreement | share of cells where the two engines select mixes within L1 ≤ .10; paired realized differences; reported |
| Stability (`U_1` only) | v1's across-seed Bad SD and L1 rules, per cell |
| Selection bias | deflated Sharpe ratio (Bailey and López de Prado 2014) of the primary realized comparison, **reported as a diagnostic, not a gate**. Trials are the arm × cell realized-difference series per menu and engine. The expected maximum uses their Sharpe variance and an effective trial count, the participation ratio `(Σλ)² / Σλ²` of the eigenvalues of the trials' correlation matrix: a **chosen approximation** for dependence across trials, not the paper's exact correction **[Codex finding 7; revision 3 finding 6]**. Dependence **through time** (overlapping annual returns at monthly origins) is handled by replacing the i.i.d. Sharpe standard error with the block-bootstrap standard error over origins of v1 §6 (block length 12 months); skew and kurtosis of the realized series enter as in the paper. The standard i.i.d. DSR is shown beside it, labelled uncalibrated |
| Collapsed columns | share of `(menu, origin, r)` with a collapsed line, and on the showcase surfaces the share of the 48 columns; reported for the column-open rule |
| Cost | the §5 cost figures against the production budget: one 48 × 19 surface for an 11-fund menu, and one risk column on demand; informational, never a validity gate |

Labels: **valid experiment** (v1 compliance checks), **white line: max-U supported / not
supported / inconclusive** per menu and engine, everything else descriptive. No equivalence claim.
Stage 2 / ENB stays governed by D4/D7 and is not triggered by this protocol.

## 7. Choosing the U weights (de Prado)

The four triples are arms, so each has its own locked mixes at every cell. After the run their
realized outcomes are compared with the **combinatorially symmetric cross-validation (CSCV)** of
Bailey, Borwein, López de Prado and Zhu (2017), fully specified here **[Codex finding 7]**:

- *Observation*: one realized annual return per `(origin, r, cell)` of an arm's locked mix,
  monthly-rebalanced convention, per menu and engine separately. An arm's **realized `U_1` on a set
  of origins** is `0.6·q_2.5 + 0.3·q_50 + 0.1·q_97.5` of its observations pooled over that set's
  origins and the 24 cells (6 `r` × 4 cells). Cells of one origin are dependent; pooling them is a
  variance-reducing device, not 24 independent draws, and the report says so.
- *Eligible origins*: only origins whose realized year is complete in the frozen ledger (the
  horizon end at or before the data end) are scored; immature or missing horizons are excluded
  before any block is formed **[Codex, revision 3 finding 5]**.
- *Blocks*: the eligible origin index is cut into `S = 8` contiguous blocks of ≈ 29 origins.
  Overlap is handled with the ledger's actual horizon endpoints, not calendar-day approximations:
  an origin is **purged** from a training side whenever its realized year overlaps any origin of
  the test side, and a one-month **embargo** follows each test block. With a 12-month horizon that
  removes up to 11 origins at each boundary.
- *Minimum size*: a side must keep at least **160 observation rows** (origin × cell rows, so that
  ≥ 4 rows sit behind `q_2.5`) **and at least 7 distinct origins per block it contains**; otherwise
  the split is dropped and counted. Rows from one origin are 24 portfolios on one historical year,
  not 24 tail events: the report states, for each side, the number of distinct origins and of
  disjoint realized years beside the row count, and the inherited tail-power limitation (few
  distinct bad years in 20) stays explicit however many rows pass.
- *Splits and ranks*: all `C(8, 4) = 70` ways of taking four blocks in sample and four out. On
  each evaluable split the triple with the best in-sample realized `U_1` is chosen (ties broken
  toward the primary triple, recorded). Its out-of-sample rank `k` among the four is 1 for the
  worst and 4 for the best out-of-sample `U_1`, ties taking the average rank; the relative rank is
  `ω = k / 5` and the logit `λ = ln(ω / (1 − ω))`, so `λ < 0` means the in-sample choice ranked
  below the median out of sample. Every triple's out-of-sample `U_1` is recorded as well. With four
  candidates PBO is coarse (`ω ∈ {.2, .4, .6, .8}`); it is read with the per-triple distributions,
  not alone.
- *Outputs*: **PBO** = share of **evaluable** splits with `λ < 0`; it is reported only if at least
  50 of the 70 splits are evaluable, otherwise "PBO not computable" with the count. Also the
  out-of-sample `U_1` distribution per triple over the evaluable splits; the rank of the primary
  triple; the in-sample vs out-of-sample `U_1` scatter (performance degradation line). All
  descriptive; they inform the product decision and do not change this run's primary analysis.

Implementation note: the quant-scenario-engine module `qse/experimental/tft/selection/purged_kfold.py`
is an ordinary contiguous purged k-fold with calendar-day purging; it does not implement CSCV and
is not ported. CSCV as specified is ≈ 100 lines in `portfoliosight/research/cscv.py` with its own
tests (block cutting, overlap purging on ledger endpoints, the 70 splits, the logit); the vendored
`qse` package is not widened.

## 8. Resource ceilings and cost projection

Six workers per host, one BLAS thread each, aggregate RSS ≤ 4 GiB per host, **600 s per arm, 240
CPU-hours** for both engines together across hosts (the R33 levels, pre-authorized so an unattended
run never stops on a ceiling).

**Two hosts** **[owner, 2026-10-23]**: the local machine (12 CPUs, 15 GB) and KS-002 over Tailscale
(8 cores, 23 GB, one resident container; probed 2026-10-23: load ≈ 1.3, Python 3.12). The unit of
distribution is one `(menu, engine)` job, selected with the run command's `--menu` and `--engine`
filters (needed anyway for the staged run); each job writes its own artifacts and manifest, with
the host name, CPU model and library versions recorded, and the report reads the job directories
together. Jobs are assigned greedily by projected CPU-hours. KS-002 setup is an rsync of the
worktree and frozen snapshot and a virtual environment from the locked requirements; results are
rsynced back. A job never spans hosts: outputs are byte-reproducible on the host that produced them
and may differ in the last bits between hosts, which the report notes. The experiment does not use
the product API or its container.

Projection, generated from the §3 schedule **[recomputed per Codex finding 4; revision 2
undercounted stability and showcase work and omitted Sobol scoring, anchors and sensitivities]**.
The per-search times are assumptions: ≈ 0.9 s per gradient search for the 20-holding research menu
(≈ 0.5 s at 11 funds, scaled by holdings), ≈ 0.2 s for TSP, ≈ 5 ms per exact bank evaluation (v1
measured 5 ms at 23 funds). They are **superseded by the measurement on the six showcase origins
before each engine's lock** (the `experiment estimate` command, as v1 R20), recorded in the
manifest. v1's one recorded cell shows most of its 17 s was harness overhead; how much of it v2
removes is measured (§4 speed items), not assumed.

| Component, per engine | research2003 (20 holdings, 5,904 cells) | TSP (5 funds, 5,856 cells) |
|---|---|---|
| Main searches: cells × 5 arms × 3 starts | 89k searches ≈ 22.1 CPU-h | 88k ≈ 4.9 CPU-h |
| Stability seeds: 4 seeds × (every fourth origin, ≈ 1,488 cells) × 3 starts, `U_1` arm | 18k ≈ 4.5 CPU-h | 18k ≈ 1.0 CPU-h |
| Showcase surfaces: 6 origins × 48 × 19 × 3 starts | 16k ≈ 4.1 CPU-h | 16k ≈ 0.9 CPU-h |
| Sobol scoring, primary bank: 1,024 exact evaluations per `(origin, r)` column | 1,476 columns ≈ 2.1 CPU-h | 1,464 ≈ 0.8 CPU-h |
| Sobol rescoring, stability banks: the stability origins' columns rescored on each of the 4 replicate banks **[Codex, revision 3 finding 7]** | ≈ 372 columns × 4 ≈ 2.1 CPU-h | ≈ 0.8 CPU-h |
| Anchors: 2 per column × 8 starts | ≈ 2 CPU-h | ≈ 0.5 CPU-h |
| Sensitivities at showcase origins (`τ_r = 0.001`, 5-year lookback, `d = 0`/`d = 1` band search) | ≈ 1.5 CPU-h | ≈ 0.4 CPU-h |
| Independent evaluation: 5 banks × 7 selections × cells | ≈ 0.3 CPU-h | ≈ 0.1 CPU-h |
| GARCH fits (per holding and origin, once; GARCH engine only) | ≈ 1.4 CPU-h | ≈ 0.3 CPU-h |
| **Per engine** | **≈ 39 CPU-h (40 with GARCH fits)** | **≈ 9.4 CPU-h (9.7)** |

Both engines: **≈ 98 CPU-h**. On the local six workers alone ≈ 16.5 h wall; with KS-002 taking the
research2003 GARCH job (≈ 40 CPU-h, ≈ 6.7 h on its six workers) and the local host the other three
(≈ 58 CPU-h, ≈ 9.7 h), **≈ 10 h wall, one night**. Within the 240 CPU-h ceiling and under the §4
GPU rule. The workload model in the `experiment estimate` command counts every dimension (menu ×
origin × `r` × cell × arm × start × engine × replicate × host) from the schedule; this table is its
hand check, and the measured gate supersedes both. Predeclared cut order if the measurement projects
more than 120 CPU-h, applied in this order and recorded in the report: (1) starts per cell drop
from three to two; (2) the stability seeds run on every eighth origin. Cuts apply to **stages not
yet started**; a running stage finishes under the plan it started with **[Codex, revision 3
finding 4]**. If the measurement projects more than two nights after both cuts, the GPU path is
built first (§4). Nothing else in the schedule is cut without a new owner decision.

Reconciliation of the projection across revisions, both engines: revision 2 as written 55 CPU-h
(arithmetic undercount); the same plan counted correctly 87; 20 holdings instead of 11, 135; Sobol
rescoring per replicate bank counted, 158; five arms and stability on every fourth origin (owner,
2026-10-23), 98. Per search the projected cost is ≈ 2.7 s for three starts on the 20-holding menu
against 17–26 s per cell in v1; the total is larger than v1's 14 CPU-h because the grid is ≈ 100×
larger (2.5× the origins, 24 cells instead of 2, five arms, two engines, five seeds on the primary
arm at a quarter of the origins).

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
  1. optimizer: exact-quantile and kernel-smoothed gradient objectives, engine-specific path
     gradients (replay count-matrix form; GARCH with the `∇k` term; absorbed paths), the
     finite-difference check, the `M`-maximizing anchors, SLSQP under the bands, deduplicated
     starts and cell labels, the agreement check against v1's COBYLA (`research/search.py`,
     `research/selection.py`);
  2. data and distribution: fetch the tickers not in the lake, register `research2003` with its
     per-holding caps, per-menu ledger start, 3-year lookback, the disjoint-year count from the
     ledger, CPI series, snapshot re-freeze; the `--menu` / `--engine` job filters, host metadata
     in the manifest, the report's multi-directory read, and the KS-002 rsync-and-venv script
     (`research/harness.py`, `data/`, snapshot tooling, `scripts/`);
  3. engine: `garch` through `research.evaluate.bank(engine=...)`, fits per holding and origin on
     the origin-cut window only (never the builder's full-lake panel), the cached levelled panel,
     the GARCH gradient terms exposed to piece 1, named convergence failures;
  4. measurements and report: comparators incl. the Bayes–Stein frontier, monthly rebalancing and
     cost variant, `d(w)`, multi-year, real, regime buckets, deflated Sharpe with the effective trial
     count, CSCV (`research/cscv.py`), cost table, showcase surfaces.
- **Gates, one per engine** **[Codex finding 4: the combined projection cannot be validated before
  GARCH exists]**: the **replay gate** (day one) is pieces 1 and 2 running the finite-difference
  check, replay's own 30-cell agreement check (its solver choice is final for replay) and the
  six-origin measurement on replay; the protocol is hash-locked with the replay figures and the
  snapshot frozen; the replay stage may start. The **GARCH gate** is piece 3 with piece 1 running
  the same three checks on GARCH before the GARCH stage starts; GARCH's solver choice and budget are
  its own and are appended to the manifest (an amendment, not a re-lock of the selection contract).
  Nothing found at the GARCH gate changes the replay stage. The owner's Codex findings on this
  document are folded in before either gate.
- **Run in two stages, on two hosts**: replay as soon as pieces 1, 2 and 4 pass scoped tests; GARCH
  when piece 3 passes its gate. Job placement per §8: KS-002 takes the research2003 GARCH job, the
  local host the other three; if the GARCH gate lands later than the replay stage, KS-002 starts
  with TSP replay instead and the placement is recomputed. Sensitivities: the 5-year lookback and
  the `τ_r = 0.001` check at the six showcase origins only.
- **Not on the path**: phase 3 closure, the v1 branch's phase PR, the 6.4/6.5 engine-validation
  report (the paired engine comparison here is most of it), phases 4 and 5.

Estimate: build two days with the four agents in parallel (the engine-specific gradients, anchors
and the widened agreement check added half a day); run two nights per §8; report half a day. About
four days end to end.

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

Round 3 (the owner's Codex review of revision 2, and the owner's menu choice):

- **Menu**: option a, the eleven funds plus nine 2003 mega-caps (MSFT, XOM, GE, PFE, C, INTC, IBM,
  JNJ, PG), 10% cap per stock, 40% per fund (§3a). Stocks chosen by end-2003 market capitalization
  to limit survivorship bias.
- **TIP → VIPSX** proposed so that twenty disjoint realized years fit (§3a); owner to confirm or
  veto before the lock.
- **GPU**: project on CPU first; Nscale or Nebius rental noted as the alternative to the local card
  if the §4 rule triggers.
- **Notation**: `M_d(r)` is written `M(r, d)`.
- **Codex findings folded in**: (1) engine-specific gradients, the GARCH `∇k` term, absorbed paths,
  finite-difference verification (§4); (2) `w_MDP(r)` maximizes `M` itself; same-band-is-not-
  same-risk reporting and the `τ_r = 0.001` sensitivity (§2, §6); (3) the ladder is not an `M`
  sweep; deduplicated starts; `insufficient_starts` / `search_failed` / `not_found` labels in
  place of "infeasible" (§4); (4) the resource table regenerated from the schedule, ≈ 135 CPU-h,
  two nights, with a predeclared cut order and one gate per engine (§8, §9); (5) the "flat between
  paths" rationale withdrawn; exact-quantile and kernel objectives both benchmarked; the agreement
  check widened to 60 cells, both engines, both objectives, narrow cells, and the 128-call fallback
  validated against 768 (§4); (6) the attainable disjoint-year count computed from the ledger and
  "not attainable" distinguished from "failed" (§3a, §6); (7) CSCV fully specified with ledger-
  endpoint purging, `S = 8`, 70 splits, PBO, and an effective trial count for the deflated Sharpe
  ratio (§6, §7). Interpretation notes: higher `U` is not lower downside, ΔBad/ΔES/drawdown
  reported beside ΔU and max-`Bad` described as maximizing `q_2.5` (§1); `μ_s` is already the
  50/50 blend and Bayes–Stein replaces it rather than stacking (§5); calibration on the
  daily-rebalanced convention, and the experiment labelled as not a qualification of the production
  engine (§5).
- **Not adopted**: none of the findings was rejected. The CPU speed items Codex listed are adopted
  as measured items in §4 rather than as assumed savings.

Round 4 (the owner's Codex review of revision 3, 2026-10-23; eight findings, all adopted):

1. The exact quantile is the evaluator's linear-interpolation estimator, in value and gradient
   (§4); the order-statistic shortcut is gone.
2. Candidate-dependent checks (replay's non-positive growth, GARCH's absorption mask) stay in the
   loop on a single growth computation; only duplicate work and unused summaries leave it (§4).
3. Interior-cell candidates join the free cell's pool, so the reported peak is never below an
   interior winner; the native free-cell result is kept beside it (§4).
4. Solver selection, pass denominator (57 of 60) and lock are per engine; cuts apply to unstarted
   stages only (§4, §8, §9).
5. CSCV: eligible origins, PBO over evaluable splits with a 50-split minimum, rank orientation and
   ties, row and distinct-origin minimums, tail-power limitation stated (§7).
6. DSR is a diagnostic; block-bootstrap Sharpe error over origins for serial dependence; the
   participation ratio labelled an approximation (§6).
7. Sobol rescoring per replicate bank counted; totals ≈ 158 CPU-h; the estimate command counts
   every dimension (§8).
8. Slider endpoints are anchor exceptions by definition, with their `U` gap measured at the
   showcase origins; `d*` outside `[0, 1]` reported as such (§2).

Round 5 (owner, 2026-10-23, after the cost reconciliation):

- **TIP → VIPSX confirmed**, for the whole history; the research menu never holds TIP.
- **Five arms**: the `(.80,.15,.05)` triple dropped; max-`Bad` kept (§2).
- **Stability** on every fourth origin with five banks (§3).
- **Two hosts**: KS-002 over Tailscale takes whole `(menu, engine)` jobs; no API, no container
  (§8, §9). Projection ≈ 98 CPU-h, ≈ 10 h wall across the two hosts.
