# Fixed-risk optimization experiment protocol (v2) — DRAFT for independent review

Status: draft, revision 6, 2026-10-23, with Amendment 1 of 2026-10-24 (§11: GARCH fit window and
fit-failure fallback). Owner decisions of 2026-10-22/23 (five rounds) and three
Codex reviews (of revisions 2, 3 and 5) applied; see §10. Not hash-locked. Open before the lock:
the replay gate of §9 (six-origin measurement on both hosts, finite-difference and agreement
checks), the corporate-action check and the published disjoint-interval endpoints (§3a).

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
   compared under a purged adaptation of combinatorially symmetric cross-validation (§7). Max-`Bad`
   runs as the fifth arm:
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
- `M(w)` is the mix's **diversification measure**: the squared diversification ratio, the risk the
  holdings would have if they all moved perfectly together (the weighted sum of their own
  volatilities), divided by the risk they actually have together, squared. It is 1 for a single
  holding and rises as holdings offset one another.
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
the allowed mixes form an `(n−1)`-dimensional region; the risk band and `F(r, d)` are thin slabs of
the same dimension `n−1` around the exact surfaces `σ(w) = r` (dimension `n−2`) and
`σ(w) = r, M(w) = M(r, d)` (dimension `n−3`). On a 5%-step weight grid the 11-fund menu
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
nonconvex programs under the band's lower edge; each is solved by SLSQP from eight starts and the
best feasible answer is kept. The starts, in this order: the convex risk-*ceiling* solution of the
same objective's convex surrogate (`w_F` under `σ ≤ r`; for the MDP anchor, max `Σ σ_i w_i` under
`σ ≤ r`), the minimum-variance mix `w_min`, the max-`μ_s` corner `w_top`, the equal-weight mix, and
the first four points of the column's Sobol sequence; each start is projected onto the band (below).
The anchor search is recorded like an arm (starts, iterations, final mix) and "found" applies to it
too. Anchors and the Bayes–Stein comparator use only `μ` and `Σ`, so they are computed once per
`(menu, origin, r)` and shared by both engines.

**Projection onto the band**, used for every start: a mix `v` with `σ(v) > r(1 + τ_r)` moves along
the segment toward `w_min`, one with `σ(v) < r(1 − τ_r)` along the segment toward `w_top`, by
bisection on the segment parameter until `|σ − r| ≤ τ_r r / 2`, at most 60 halvings; a mix that
cannot reach the band on its segment is discarded and the next start is drawn. Segments keep the
bounds and the budget because both ends satisfy them.

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
the primary result. `d(w)` is unbounded and the two sides mean different things: `d* < 0` is
ordinary geometry (the frontier mix is not the least-diversified mix on the line); `d* > 1` means
the found MDP anchor was beaten, and the report gives that anchor regret `M(w) − M(w_MDP)`. The
share of free-cell winners on each side is reported per menu and `r`. On a collapsed column `d*` is
undefined and reported as missing.

## 3. Grid, origins, menus, engines

- Risk levels **[owner, 2026-10-22: need not exceed the app's 48 columns; six for the main grid]**:
  `r ∈ {X(a) : a ∈ {.10, .25, .40, .55, .70, .85}}`, `X(a) = σ_min + a·(σ(w_top) − σ_min)` as v1
  §3, used as fixed risks. The extreme `a = 1` is omitted: its band is a thin sliver around the
  max-return corner where every arm and comparator would nearly coincide.
- Diversification cells: the free cell and `d ∈ {0.25, 0.50, 0.75}`; `d = 0` and `d = 1` are the
  anchors. Four searched cells per `(menu, origin, r)`, five arms each.
- **Showcase surfaces**: at six origins per menu (v1's sensitivity rule, indices
  `floor(j·(K−1)/5)`, j = 0..5), the full product surface: 48 risk columns × 19 interior slider
  positions, primary arm only. These measure the production precompute and give the UI work a
  heatmap over time; they are descriptive.
- Engines: `replay` (v1 §5 step 1, unchanged) and `garch` (spec §4.3). GARCH is fitted **once per
  fund and origin** and shared by every menu, arm and cell at that origin (the per-fund precompute
  of ADR 0002 applied to the experiment). *Superseded by Amendment 1 (§11):* the fit window is all
  of the fund's history up to the origin, not the training window; a fit that fails falls back to
  constant volatility for that fund, labelled, instead of failing the origin's cells. Each engine has its own 2,000 × 252 bank per
  `(menu, origin, engine, replicate)` with v1's seeds.
- Optimizer replicates: primary seed `20261013` for every primary statistic; seeds `20261014..17`
  for the stability diagnostics of the `U_1` arm only, run on **every fourth scheduled origin**
  (indices `0, 4, 8, …`; ≈ 62 per menu) **[owner, 2026-10-23]**: five banks per cell there, the
  same across-seed Bad SD and L1 rules as v1, a quarter of the cost of every origin. Stability is a
  diagnostic, never a gate. **Like for like** **[Codex, revision 5 finding 9]**: the stability
  statistics compare the `U_1` arm's **native** search result (its own starts and iterates only, no
  candidates pooled from other arms or cells) on all five banks, the primary bank included; the
  primary seed's pooled selection is reported separately and is not part of the stability
  comparison. The Sobol scramble seed and the start rules are the same on every bank, so only the
  bank varies.
- Lookback **[owner, 2026-10-22: 3 years primary]**: 756 union-calendar rows with the 90%
  complete-rows rule; the product's 5-year window runs as a sensitivity at the showcase origins
  where a 5-year window meets the same rule. The first showcase origin of each menu (2006) does not
  (EEM and the TSP funds start in 2003), so the 5-year sensitivity has five origins per menu, and the
  report states that denominator **[Codex, revision 5 finding 12]**.
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
including individual stocks and chose **option a** (round 3, §10): the eleven funds plus the
largest US companies of early 2004, 10% cap per stock.

**Stock selection rule, dated** **[Codex, revision 5 finding 1]**: the stocks are the US-domiciled
companies among the ten largest listed companies worldwide by market value in the FT Global 500 of
2004 (market values at 2004-03-31), as tabulated in Wikipedia's "List of public corporations by
market capitalization" (read 2026-10-23; a dated copy of the table is frozen into the snapshot).
That gives eight: **GE, MSFT, XOM, PFE, C, WMT, AIG, INTC**. The rule uses only information from
2004-03, two years before the first origin (2006-04), so the selection has no look-ahead relative to
any origin. It replaces the revision-5 list, which was picked from memory and did not follow its own
stated rule (it held IBM, JNJ and PG and missed WMT and AIG, the latter the period's largest
large-cap failure). Limits, stated in the report: the menu as a whole is still a retrospective
research choice; one dated ranking is not a point-in-time index membership history; the 10% cap
limits direct concentration (eight stocks can still hold 80%), not survivorship; and the equity ETFs
hold the same issuers. WMT is `pending` in the manifest and AIG is in the lake; both are fetched or
confirmed through the existing provider like the other tickers.

**Corporate actions, checked before the freeze**: for every stock and for VIPSX, the pipeline's
total-return index (`data/returns.py`: close, cash distributions and split factors) is compared year
by year with the provider's adjusted close. A year differing by more than 50 bp is reconciled
before the snapshot is frozen (known cases: AIG's 2009 and C's 2011 reverse splits, GE's 2023 and
2024 spin-offs, which a cash-distribution field does not carry) and the reconciliation is recorded
in the manifest. For VIPSX the same check confirms that income **and capital-gain** distributions
are reinvested.

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
| GE, MSFT, XOM, PFE, C, WMT, AIG, INTC | US companies in the 2004 global top ten | 1995-01 each |

**TIP → VIPSX** **[Codex finding 6; owner confirmed 2026-10-23, for the whole history, no
splice]**: TIP's first price is 2003-12, so
the first 3-year origin would be 2006-12 and only 19 disjoint realized years fit before the data
end (2026-09); the 20-interval realized-support gate the owner kept (decision D) would be
unreachable by construction. VIPSX tracks the same asset class from 2000-06. With it the youngest
ticker is EEM (2003-04) and the first origin 2006-04. Twenty disjoint realized years are
**plausible, not established** **[Codex, revision 5 finding 3]**: the ledger's intervals are 252
union-calendar returns from month-end origins, and the next disjoint origin must be strictly later
than the previous horizon end (`research/harness.py`, `_assign_intervals`), so each interval can
cost a little more than a calendar year. The retained interval endpoints are computed from the
frozen ledger and published in the manifest before the lock; the interval rule is not changed
afterward. If the count is below 20 for either menu, the report says the realized-support criterion
was not attainable rather than failed.

VIPSX is an actively managed mutual fund priced at net asset value, not a price-history extension
of TIP: its expenses and holdings differ, and an order must be placed before the close to receive
that day's value. The experiment keeps v1 §3's **idealized convention** for every holding (weights
set from data through the origin's close, returns earned from the next session, frictionless
except for the §5 cost variant); for VIPSX that is not executable at the origin's own value, and
the report says so.

The tickers not in the lake are fetched through the existing Tiingo provider, frozen into the
snapshot, and the menu is registered as a research preset (`research2003`), not a product preset.
Caps **[owner, option a]**: 0–40% per fund, 0–10% per stock, recorded in the manifest. The menu has
**19 holdings**. The six-origin measurement is made on the final menu.

Schedules, each menu on its own eligible origins:

| Menu | Holdings | Ledger from | First origin (3y) | Origins to 2026-09 | Disjoint realized years |
|---|---|---|---|---|---|
| research2003 | 19 | 2003-04 | 2006-04 | ≈ 246 | plausibly 20, from the frozen ledger before the lock; spans 2007-09, 2011, 2013, 2015-16, 2018, 2020, 2022 |
| TSP | 5 | 2003-06 | 2006-06 | ≈ 244 | plausibly 20, from the frozen ledger before the lock |

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
- **Kernel-smoothed quantile**: `Q̃_q(w) = Σ_i κ_i R_(i)` over the sorted years, with rank
  coordinate `u_i = (i − 1)/(P − 1)` (the coordinate of the linear estimator, so `Q̃` centres on the
  same point), raw weights `φ((u_i − q)/h)` for `|u_i − q| ≤ 4h` and zero beyond, normalized so
  `Σ κ_i = 1`; bandwidth `h = 0.01` (≈ 20 of 2,000 paths) **[choice]**. Its gradient is the same
  `κ`-weighting of the paths' gradients at their current ranks. This averages the kinks over ≈ 20
  paths; it does not remove them (rank crossings still move the weights), so it is a smoother
  objective, not a globally smooth one.

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
  the error Codex found in revision 2. Zero-variance branch, matching production (`_garch_terms`
  sets `k = 0` when `sd(y) = 0`): if `w'Σ_R' w ≤ 1e-14` then `k := 0` and `∇k := 0`, so the day is the
  constant `m'w` with gradient `m`. Under the menus' caps (no holding above 60%) no feasible mix
  reaches this branch; it is defined for completeness.
- *Absorbed paths* (GARCH; a day at or below −100%, spec §4.3 `RUIN`): the absorption mask is
  computed from the proposed mix's daily returns **before** any logarithm or division; the path's
  year is exactly −1 and its gradient is defined as zero; it keeps rank −1 in every exact quantile
  and in the kernel average.
- *Replay growth, a per-bank bound* **[Codex, revision 3 finding 2; revision 5 finding 11]**: for a
  mix with `1'w = 1`, the recentred daily growth is `g_t = Σ_i w_i b_ti` with
  `b_ti = 1 + a_ti − ā_i + μ_s,i/252` (`_replay_years`). If `min_{t,i} b_ti > 0`, every mix with
  `w ≥ 0` and `1'w = 1` has `g > 0` on every sample day, so the bound is checked **once per bank**
  and covers the whole search domain; SLSQP iterates are clipped to the bounds and renormalized to
  `1'w = 1` before evaluation, so they stay in that domain. The largest single-day losses among the
  19 holdings (AIG in September 2008, roughly −60%) should leave `b > 0`; the bound is checked, not
  assumed. A bank that fails the bound is named
  `growth_bound_failed`, its cells are searched with v1's derivative-free solver, which keeps the
  existing per-candidate `ValueError`, and the count is reported.

**Gradient verification, predeclared**: before either optimizer is accepted, directional
finite-difference checks on 20 random directions at 10 random feasible mixes per engine and menu,
central differences with step `1e-6`, relative error ≤ `1e-4` on every direction whose
finite-difference magnitude exceeds `1e-8`. A direction is skipped, and the skip counted, when the
step changes the rank order of the paths that carry the quantile's weight (the derivative does not
exist at a rank crossing) or moves any path across the GARCH absorption boundary; a test mix with
more than 5 of 20 directions skipped is redrawn. A failure blocks the lock for that engine.

**Optimizer**: SLSQP (SciPy) with analytic gradients; equality `1'w = 1`; bounds; the risk band as
two smooth inequalities; the measure band as two more in the interior cells. Maximum 200 iterations,
`ftol 1e-9` **[choice]**. A point counts as feasible when every band and the budget hold to `1e-8`
absolute; a solver end point outside that tolerance is projected (§2) and, if still outside, the
start's best feasible iterate from the archive is used. Starts per cell, three, each
**deduplicated** (two starts within L1 ≤ `1e-6` count once and a replacement is drawn) **[Codex
finding 3]**: (i) the point at fraction `d` along the straight line from `w_F(r)` to `w_MDP(r)`,
projected onto the risk band (the `engine/ladder.py` ladder is monotone in ENB, not in `M`, so it
is not used as a start source); (ii) continuation: interior cells run in the fixed order
`d = 0.25, 0.50, 0.75` and each starts from the previous cell's `U_1` solution (`d = 0.25` from
`w_F(r)`); the free cell runs last and starts from `w_F(r)`, `w_MDP(r)` and the best Sobol point;
(iii) the best of **256** scrambled Sobol points (v1's generator and seed, first 256 of its
sequence) projected onto the risk band, scored once per `(menu, origin, r, bank)` column and reused
by every cell and arm of that column. 256 replaces v1's 1,024 because the pool now supplies one
start, not the search **[speed, 2026-10-23]**. The arm's answer is the best exact objective among
the starts. Seeds for every random draw are functions of `(menu, origin, engine, replicate, r, cell,
arm, start)` only, never of host, worker count or completion order; the archive is written sorted
by `(r, cell, arm, start, iteration)`.

**Cell labels** **[Codex finding 3; reconciled with v1's archive rule per revision 5 finding 11]**.
A sparse Sobol hit count says nothing about feasibility, so the labels are: `insufficient_starts`
(fewer than three distinct feasible starts after one extra block of 256 Sobol points with the seed
offset recorded; the cell still runs with what it has), `search_failed` (no feasible point was
visited in the cell by any start; as in v1, any feasible archived point survives an unsuccessful
solver end and is a usable selection), and `not_found` (the feasibility program
`min_{w ∈ F(r)} |M(w) − M(r, d)|` from eight starts never came within `τ_d · span`). None is called
"infeasible": the programs are nonconvex and a search proves nothing about mixes it did not visit.
All three are counted per menu, `r` and `d` and reported.

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
expected. **The check runs on the configuration that will run** **[Codex, revision 5 finding 7]**:
the cost measurement and any §8 cut (starts per cell, stability origins) are decided first, the
agreement check then runs with exactly those settings, and the engine locks after it. A cut made
later for a stage not yet started reruns that engine's agreement check on the new settings before
the stage starts. A GPU optimizer, if built, is a new solver: it passes its own finite-difference
and agreement checks before it runs anything.

**CPU speed items, in order** **[Codex]**, each measured against the v1 harness on the same cells
before the lock and recorded in the manifest: (1) the replay gradient through the count matrix
above; (2) the GARCH levelled panel `R'` computed once per bank and cached (≈ 44 MB for 11 funds,
≈ 77 MB for 19, float64) instead of re-exponentiated on every call; (3) the optimizer's hot path
separated from reporting: the immutable inputs (bank, moments, bounds) are validated once, digests
and unused summary statistics leave the loop, and the **candidate-dependent checks stay**: each
proposal's daily growth is computed once and reused for the compounding and the gradient, with
GARCH's absorption mask taken from it before any logarithm; replay's growth validity is covered by
the per-bank bound above **[Codex, revision 3 finding 2]**; (4) one exact `B/T/G` evaluation per
visited mix feeds every `U_k` and the
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
  `menu_beta_blend`) **[Codex]**. `w_F̃(r)` is the same program on a Bayes–Stein estimate applied
  to `μ̂` **in place of** the blend, not on top of it, so the two comparators are two shrinkage rules
  on the same sample mean **[choice; realism rule]**. The estimate (Jorion 1986), on the training
  window's `T` daily rows and `N` holdings: `S` the sample covariance scaled by `(T − 1)/(T − N − 2)`;
  `μ_0 = μ̂'S⁻¹1 / 1'S⁻¹1`, the return of the unconstrained minimum-variance portfolio;
  `φ = (N + 2) / ((N + 2) + T (μ̂ − μ_0 1)' S⁻¹ (μ̂ − μ_0 1))`; `μ_BS = (1 − φ) μ̂ + φ μ_0 1`,
  annualized by 252. The frontier program keeps v1's covariance `Σ`; only the expected return
  changes. Both comparators are evaluated like arms; being per column, each is evaluated once per
  `(menu, origin, r)` and reused across the column's cells. `w_MDP(r)` is recorded (it defines the
  slider) but not evaluated.
- **Realized convention** **[choice; realism rule]**: the locked weights held with **monthly**
  rebalancing to target becomes the primary realized outcome for the guardrails and the realized
  support (v1 rebalanced daily, which no investor does); daily rebalanced is reported for
  continuity. Each origin is a separate one-year cohort, as in v1 §3; cohorts do not form one
  traded portfolio. Within a cohort: funded at target weights from cash at the origin's close;
  rebalanced to target at the close of the last session of each calendar month strictly inside the
  horizon; fully invested, no cash holding; no liquidation at the horizon end.
- **Cost variant** **[defined per Codex, revision 5 finding 10]**: at each rebalance, one-way
  turnover is `½ Σ_i |w_i^target − w_i^drifted|`, with `w^drifted` the pre-trade holdings after the
  month's returns; the cost `10 bp × turnover` is deducted from the cohort's value at that close.
  The initial funding is charged at the same rate (one-way turnover 1.0), which is equal across
  arms and so cancels in paired differences; it is included so the net levels are honest. Turnover
  from the previous origin's target is reported only as a descriptive stability statistic, never
  charged. Gross and net figures are reported side by side.
- **Forecast calibration uses the daily-rebalanced realized year** because that is the strategy
  the banks simulate; comparing a daily-rebalanced forecast with a monthly-rebalanced outcome would
  mix forecasting error with strategy mismatch **[Codex]**.
- **This experiment is not a qualification of the production engine** **[Codex]**: GARCH here
  fits the shape on all history up to the origin (Amendment 1, §11), where spec §4.3 caps it at ten
  years; and the realized convention above differs from the spec's. The
  report labels both differences in its engine section, and the spec's 6.4/6.5 validation stays
  owed.
- **Multi-year realized**: compounded 3- and 5-year outcomes from the same origin with the locked
  weights, for the origins whose horizons are complete; disjoint-interval counts stated; descriptive.
- **Real returns** **[owner: include]**: 1-, 3- and 5-year outcomes deflated by CPI-U, all items,
  not seasonally adjusted (FRED `CPIAUCNS`, the series TIPS index to and the one FRED does not
  revise), fetched as FRED's public CSV and frozen into the snapshot with its vintage date;
  deflator = CPI of the calendar month containing the horizon's end date over CPI of the calendar
  month containing the **origin** date (the wealth start), so no month of inflation is skipped;
  evaluation only.
- **Regime buckets**: each realized year labelled from two series frozen into the snapshot: the
  equity drawdown, the largest peak-to-trough fall of SPY's total-return index inside the horizon;
  and the 10-year yield change, FRED `DGS10` at the horizon end minus at the origin (last value on
  or before each date). Labels by priority: "equity drawdown" if the drawdown is ≥ 15%, otherwise
  "rate shock" if the yield rose ≥ 150 bp, otherwise "calm"; fixed here; outcomes per bucket;
  descriptive.
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
| Line shape | per `(menu, engine, r)` and for the `U_1` arm at `d ∈ {0.25, 0.50, 0.75}`: three statistics over the eligible origins, realized Bad (the linear 2.5th percentile of the realized annual returns across origins), mean realized drawdown and mean realized annual return; for each, the OLS slope of the statistic on `d` across the three positions, with a 95% percentile interval from v1 §6's block bootstrap over origins (block 24, the same resampled origins for all three positions). Realized Bad across ≈ 240 origins rests on about six of them; stated. Reported |
| Engine agreement | share of cells where the two engines select mixes within L1 ≤ .10; paired realized differences; reported |
| Stability (`U_1` only) | v1's across-seed Bad SD and L1 rules, per cell |
| Selection bias | deflated Sharpe ratio (Bailey and López de Prado 2014), **a diagnostic, not a gate**, per menu and engine, defined in §7a **[Codex, revision 5 finding 4]** |
| Collapsed columns | share of `(menu, origin, r)` with a collapsed line, and on the showcase surfaces the share of the 48 columns; reported for the column-open rule |
| Cost | the §5 cost figures against the production budget: one 48 × 19 surface for the 19-holding menu, and one risk column on demand; informational, never a validity gate |

Labels: **valid experiment** (v1 compliance checks), **white line: max-U supported / not
supported / inconclusive** per menu and engine, everything else descriptive. No equivalence claim.
Stage 2 / ENB stays governed by D4/D7 and is not triggered by this protocol.

## 7. Choosing the U weights (de Prado)

The four triples are arms, so each has its own locked mixes at every cell. After the run their
realized outcomes are compared with a **purged adaptation** of the combinatorially symmetric
cross-validation (CSCV) of Bailey, Borwein, López de Prado and Zhu (2017). Purging makes the two
sides unequal in size and dropped splits change the sampling scheme, so the original procedure's
symmetry does not survive unchanged; the report uses the adaptation's name **[Codex, revision 5
finding 5]**.

- *Observation*: one realized annual return per `(origin, r, cell)` of an arm's locked mix,
  monthly-rebalanced convention, per menu and engine separately.
- *Common mask*: a row `(origin, r, cell)` enters only if all four triples have a locked selection
  there with a complete realized year; collapsed columns and cells with any of the §4 labels for
  any triple are excluded and counted.
- *Estimand* (per fixed-risk cell, not a pooled mixture): an arm's **realized `U_1` on a set of
  origins** is computed **per `(r, cell)`** as `0.6·q_2.5 + 0.3·q_50 + 0.1·q_97.5` (linear
  percentiles) of that cell's realized annual returns over the set's origins, then averaged with
  equal weight over the `(r, cell)` pairs present in the common mask. Pooling rows across cells
  before taking quantiles would measure a mixture of risk settings, so it is not done.
- *Eligible origins*: only origins whose realized year is complete in the frozen ledger (the
  horizon end at or before the data end) are scored; immature or missing horizons are excluded
  before any block is formed **[Codex, revision 3 finding 5]**.
- *Blocks*: the eligible origins, in date order, are cut into `S = 8` contiguous blocks with
  `numpy.array_split` (the first `K mod 8` blocks carry one extra origin).
- *Purge and embargo*, on the ledger's actual horizon endpoints, never calendar-day
  approximations: for a split, a training origin `o` is **purged** if its closed interval
  `[origin(o), end(o)]` intersects `[origin(t), end(t)]` for any test origin `t`; then a training
  origin is **embargoed** if its origin date falls within one calendar month after the latest
  `end(t)` of a test block that precedes it. Test origins are never removed.
- *Minimum size*: within each `(r, cell)`, each side must keep at least **60 distinct origins**
  (so `q_2.5` interpolates between the 2nd and 3rd lowest), and every training block must keep at
  least 5 origins after purge and embargo; otherwise the split is dropped and counted. The report
  states, for each side, the number of distinct origins and of disjoint realized years; the
  inherited tail-power limitation (few distinct bad years in 20) stays explicit however many
  origins pass.
- *Splits and ranks*: all `C(8, 4) = 70` ways of taking four blocks as training and four as test.
  On each evaluable split the triple with the best training realized `U_1` is chosen; ties are
  broken by the fixed order `(.60,.30,.10)`, `(.70,.20,.10)`, `(.50,.35,.15)`, `(.40,.40,.20)`, and
  recorded. Its test rank `k` among the four is 1 for the worst and 4 for the best test `U_1`, ties
  taking the average rank; `ω = k / 5`, `λ = ln(ω / (1 − ω))`, so `λ < 0` means the training choice
  ranked below the median on test. Every triple's test `U_1` is recorded as well. With four
  candidates PBO is coarse (`ω ∈ {.2, .4, .6, .8}`); it is read with the per-triple distributions,
  not alone.
- *Outputs*: **PBO** = share of **evaluable** splits with `λ < 0`; it is reported only if at least
  50 of the 70 splits are evaluable, otherwise "PBO not computable" with the count. Also the test
  `U_1` distribution per triple over the evaluable splits; the rank of the primary triple; the
  training vs test `U_1` scatter (performance degradation line). All descriptive; they inform the
  product decision and do not change this run's primary analysis.
- *Frozen before the lock*: the blocks, all seventy purge-and-embargo masks and their evaluability
  depend only on the frozen ledger, so they are computed and written to the manifest before the
  lock; the analysis reads them, it does not recompute them.

Implementation note: the quant-scenario-engine module `qse/experimental/tft/selection/purged_kfold.py`
is an ordinary contiguous purged k-fold with calendar-day purging; it does not implement CSCV and
is not ported. The adaptation as specified is ≈ 100 lines in `portfoliosight/research/cscv.py` with
its own tests (block cutting, purge and embargo on ledger endpoints, the 70 splits, the logit); the
vendored `qse` package is not widened.

### 7a. Deflated Sharpe ratio, as computed here

A diagnostic of selection bias, not a gate, per menu and engine **[Codex, revision 5 finding 4]**.
It is a **modified** application of Bailey and López de Prado (2014) and is labelled so.

- *Primary series*: for each origin on the ledger's **disjoint** intervals only (≈ 20 annual
  observations), the mean over the six risk levels of the free cell's realized annual-return
  difference, `U_1` arm minus `w_F(r)`, monthly-rebalanced convention. Restricting to disjoint
  intervals removes the overlap between annual returns at monthly origins instead of correcting
  for it. `n` is the number of such observations.
- *Sharpe ratio*: `SR = mean / sd` of the primary series (`sd` with `ddof = 1`), in **annual
  units, not annualized further**.
- *Trials*: the same construction for every arm (five) and every cell (free and three interior),
  20 trial series on the same disjoint origins; a trial with zero standard deviation is dropped and
  counted. `V` is the variance of the trials' `SR`. `N_eff` is the participation ratio
  `(Σλ)² / Σλ²` of the eigenvalues of the trials' correlation matrix, clipped to `[1, 20]`: a
  **chosen approximation** for dependence across trials, not the paper's correction.
- *Benchmark*: `SR_0 = sqrt(V) · ((1 − γ) Φ⁻¹(1 − 1/N_eff) + γ Φ⁻¹(1 − 1/(N_eff · e)))`, `γ` the
  Euler–Mascheroni constant; `SR_0 = 0` when `N_eff < 2`.
- *Statistic*: `DSR = Φ( (SR − SR_0) · sqrt(n − 1) / sqrt(1 − γ_3 SR + ((γ_4 − 1)/4) SR²) )` with
  `γ_3` the skewness and `γ_4` the (non-excess) kurtosis of the primary series. No bootstrap
  standard error is mixed in.
- *Reading*: with `n ≈ 20` the statistic has little power, and it cannot account for the choices
  made across this protocol's revisions (menus, arms, tolerances); the report says both.

## 8. Resource ceilings and cost projection

Six workers per host, one BLAS thread each, aggregate RSS ≤ 4 GiB per host, **600 s per arm, 240
CPU-hours** for both engines together across hosts (the R33 levels). The ceilings sit well above the
projection; v1's stop-on-breach rule is kept: the first breach stops that job, keeps every artifact
and marks its manifest `incomplete`.

**Two hosts** **[owner, 2026-10-23; controls per Codex, revision 5 finding 6]**: the local machine
(12 CPUs, 15 GB) and KS-002 over Tailscale (8 cores, 23 GB, one resident container; probed
2026-10-23: load ≈ 1.3, Python 3.12). The experiment does not use the product API or its container.

- *Unit*: one `(menu, engine)` job, four in all, selected with the run command's `--menu` and
  `--engine` filters (needed anyway for the staged run). A job never spans hosts, and the jobs on
  one host run **one at a time**, so the v1 runner's six-worker and 4 GiB limits, which are scoped
  to one process tree, hold per host.
- *Parent manifest*, written before any job starts: the protocol hash, the snapshot digest, each
  menu's schedule, each engine's solver choice and settings, the seeds, the four expected job keys,
  each job's CPU budget and host, and the CSCV masks of §7. Each job's own manifest carries the
  parent's digest plus its host name, CPU model and library versions. The report refuses to run if
  a job is missing, duplicated or carries a different parent digest.
- *Budgets*: each job's CPU ceiling is `240 × (its projection / the total projection)`, recorded in
  the parent manifest; retries and reruns count against the job that incurred them; the four
  budgets sum to 240.
- *Placement*: minimizes the larger of the two hosts' projected wall times using each host's
  **measured** rate (the six-origin measurement runs on both hosts), and is recorded in the parent
  manifest before the jobs start. With the assumptions below that puts both GARCH jobs on KS-002
  and both replay jobs on the local machine.
- *Reproducibility*: random streams depend only on `(menu, origin, engine, replicate, r, cell, arm,
  start)` (§4), so a job is byte-reproducible on its own host. Across hosts, last-bit differences
  can change path ranks, active constraints and a nonconvex solver's end point, not just decimals.
  So one origin of each KS-002 job is rerun on the local machine and the report gives the share of
  identical selections and the largest `|ΔU|`; the host is otherwise confounded with the engine and
  the report says so.
- *Setup*: an rsync of the worktree and frozen snapshot to KS-002 and a virtual environment from
  the locked requirements; job directories are rsynced back.

Projection **[regenerated per Codex, revision 5 finding 8]**. Per-unit costs are assumptions until
measured: the replay engine's cost is dominated by the `P × T` count-matrix product (`T = 756`
training rows), so it barely depends on the number of holdings: ≈ 5 ms per exact evaluation and
≈ 0.5 s per gradient search (one start) for either menu. The GARCH engine's cost scales with
holdings: ≈ 9 ms and 0.9 s for the 19-holding menu, ≈ 2.5 ms and 0.25 s for TSP. All are
**superseded by the measurement on the six showcase origins on both hosts before each engine's
lock** (the `experiment estimate` command, as v1 R20). v1's one recorded cell shows most of its
17 s was harness overhead; how much of it v2 removes is measured (§4 speed items), not assumed.

Counts per engine (exact, from the schedule):

| Work | research2003 | TSP |
|---|---:|---:|
| Main searches: cells × 5 arms × 3 starts | 88,560 | 87,840 |
| Stability searches: 4 seeds × ≈ 1,488 / 1,464 cells × 3 starts | 17,856 | 17,568 |
| Showcase searches: 6 origins × 48 × 19 × 3 starts | 16,416 | 16,416 |
| Sobol columns × 256 points: main 1,476 / 1,464, stability 4 × 372 / 366, showcase 288 | 3,252 | 3,216 |
| Sensitivity searches at showcase origins (`τ_r = 0.001`, 5-year on five origins, `d = 0`/`1` bands) | ≈ 4,200 | ≈ 4,200 |
| Selections evaluated on the 5 independent banks | ≈ 43,900 | ≈ 43,500 |
| Banks built (training, stability, independent) | ≈ 1,724 | ≈ 1,710 |

CPU-hours under the stated assumptions:

| Job | Searches | Sobol | Sensitivities | Independent evaluation | Banks and GARCH fits | Total |
|---|---:|---:|---:|---:|---:|---:|
| research2003 replay | 17.1 | 1.2 | 0.6 | 0.3 | ≈ 0 | **19.2** |
| TSP replay | 16.9 | 1.1 | 0.6 | 0.3 | ≈ 0 | **18.9** |
| research2003 GARCH | 30.7 | 2.1 | 1.0 | 0.5 | 2.3 | **36.6** |
| TSP GARCH | 8.5 | 0.6 | 0.3 | 0.2 | 0.6 | **10.2** |
| Shared: anchors and the Bayes–Stein comparator (once per column, both engines), gates (finite differences, agreement checks, six-origin measurement on both hosts) | | | | | | **3.2** |
| Contingency, 10%: extra Sobol blocks, `not_found` feasibility programs, reruns | | | | | | **8.8** |
| **Total** | | | | | | **≈ 97** |

Wall time on six workers per host, under the placement rule: local machine (both replay jobs)
≈ 38 CPU-h, **≈ 6.5 h**; KS-002 (both GARCH jobs) ≈ 47 CPU-h, **≈ 8 h** if its cores match the
local ones, longer if slower, which the measurement settles. Replay runs as soon as the replay gate
passes, GARCH when its gate passes; one night if the GARCH gate is ready by the evening. Within the
240 CPU-h ceiling and under the §4 GPU rule.

Predeclared cut order if the measurement projects more than 120 CPU-h, applied in this order and
recorded in the report: (1) starts per cell drop from three to two; (2) the stability seeds run on
every eighth origin. Cuts are decided **before** the agreement check, which then runs on the cut
configuration (§4); a cut for a stage not yet started reruns that engine's agreement check; a
running stage finishes under the plan it started with **[Codex, revision 3 finding 4; revision 5
finding 7]**. If the measurement projects more than two nights after both cuts, the GPU path is
built first (§4). Nothing else in the schedule is cut without a new owner decision.

Reconciliation of the projection across revisions, both engines: revision 2 as written 55 CPU-h
(arithmetic undercount); the same plan counted correctly 87; 20 holdings instead of 11, 135; Sobol
rescoring per replicate bank counted, 158; five arms and stability on every fourth origin (owner,
2026-10-23), 98; revision 6 (replay cost not scaled by holdings, Sobol pool 256, Bayes–Stein and
showcase columns, gates, banks and a 10% contingency counted), ≈ 97. The total is larger than v1's
14 CPU-h because the grid is ≈ 100× larger (2.5× the origins, 24 cells instead of 2, five arms, two
engines, five seeds on the primary arm at a quarter of the origins); per search the projected cost
is about a tenth of v1's.

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
  2. data and distribution: fetch the tickers not in the lake, the corporate-action check against
     adjusted close, register `research2003` with its per-holding caps, per-menu ledger start,
     3-year lookback, the published disjoint-interval endpoints, CPI and 10-year-yield series and the
     dated market-cap table, snapshot re-freeze; the `--menu` / `--engine` job filters, the parent
     manifest and per-job budgets, host metadata, the report's multi-directory read with its
     completeness check, and the KS-002 rsync-and-venv script (`research/harness.py`, `data/`,
     snapshot tooling, `scripts/`);
  3. engine: `garch` through `research.evaluate.bank(engine=...)`, fits per holding and origin on
     the origin-cut window only (never the builder's full-lake panel), the cached levelled panel,
     the GARCH gradient terms exposed to piece 1, named convergence failures;
  4. measurements and report: comparators incl. the Bayes–Stein frontier, monthly rebalancing and
     cost variant, `d(w)`, multi-year, real, regime buckets, the deflated Sharpe ratio of §7a, the
     purged CSCV adaptation with its frozen masks (`research/cscv.py`), cost table, showcase
     surfaces, the cross-host rerun check.
- **Gates, one per engine** **[Codex finding 4: the combined projection cannot be validated before
  GARCH exists]**: the **replay gate** (day one) is pieces 1 and 2 running, in this order, the
  six-origin measurement on replay on both hosts, any §8 cut, the finite-difference check, and
  replay's own 30-cell agreement check on the resulting configuration (its solver choice is final
  for replay); the parent manifest is written, the protocol is hash-locked with the replay figures
  and the snapshot frozen; the replay stage may start. The **GARCH gate** is piece 3 with piece 1
  running the same steps on GARCH before the GARCH stage starts; GARCH's solver choice and budget
  are its own and are appended to the parent manifest (an amendment, not a re-lock of the selection
  contract). Nothing found at the GARCH gate changes the replay stage. The owner's Codex findings on
  this document are folded in before either gate.
- **Run in two stages, on two hosts**: replay as soon as pieces 1, 2 and 4 pass scoped tests; GARCH
  when piece 3 passes its gate. Job placement per §8 (by default both replay jobs local, both GARCH
  jobs on KS-002). Sensitivities: the 5-year lookback (five origins per menu) and the
  `τ_r = 0.001` check at the showcase origins only.
- **Not on the path**: phase 3 closure, the v1 branch's phase PR, the 6.4/6.5 engine-validation
  report (the paired engine comparison here is most of it), phases 4 and 5.

Estimate: build two days with the four agents in parallel; run one night on two hosts per §8, two
if the GARCH gate is late or KS-002 is slower than the local machine; report half a day. About
three and a half days end to end.

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
  JNJ, PG; list superseded in round 6), 10% cap per stock, 40% per fund (§3a). Stocks chosen by end-2003 market capitalization
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

Round 6 (Codex review of revision 5, 2026-10-23, run by Claude at the owner's request; seven High,
five Medium, five Low findings, all adopted):

1. Stocks follow a dated, sourced rule (US companies in the FT Global 500 top ten of March 2004):
   GE, MSFT, XOM, PFE, C, WMT, AIG, INTC. IBM, JNJ and PG leave; WMT and AIG enter. 19 holdings.
   Corporate-action check against adjusted close before the freeze (§3a).
2. VIPSX: distributions verified by the same check; v1's idealized close-to-close convention kept
   and named as not executable at a mutual fund's own close (§3a).
3. Twenty disjoint years called plausible, not established; endpoints published before the lock
   (§3a).
4. Deflated Sharpe ratio written out as a formula on disjoint intervals only (§7a).
5. CSCV renamed a purged adaptation; per-cell estimand; common mask; blocks, purge, embargo, ties
   and minimum sizes pinned; masks frozen before the lock (§7).
6. Two hosts: parent manifest, per-job budgets summing to 240, one job at a time per host,
   host-independent seeds, a cross-host rerun check; stop-on-breach kept (§8).
7. Cuts decided before the agreement check, which runs on the configuration that will run; a GPU
   solver passes its own gates (§4, §8, §9).
8. Resource model regenerated: replay cost no longer scaled by holdings; Bayes–Stein, showcase
   Sobol, gates, banks and a 10% contingency counted; Sobol pool cut from 1,024 to 256 (one start);
   ≈ 97 CPU-h (§8).
9. Stability compares like with like: native `U_1` search on all five banks (§3).
10. Cost variant defined from drifted pre-trade holdings; no cross-cohort charge (§5).
11. Numerical recipes pinned: kernel, anchor starts, projection, continuation order, feasibility
    tolerance, per-bank growth bound, zero-variance GARCH branch, finite-difference skips,
    Bayes–Stein formula, v1's archive rule (§2, §4, §5).
12. Sensitivities and secondary measures defined: 5-year denominator of five, CPI from the origin
    month, regime series and priority, line-shape estimator (§3, §5, §6).
13. Low: `M(w)` wording (perfect correlation, not independence), slab dimensions, `d* > 1` as anchor
    regret, `a = 1` wording, max-`Bad` as the fifth arm.

Convergence: this was the third Codex round on the protocol. Its findings were specification gaps
and the new menu, data and host choices of revision 5, not errors in the selection contract, the
gradients or the estimator, which it confirmed resolved. No fourth protocol round is planned; the
build's code reviews (at most three, §9) check the implementation against this text.

## 11. Amendment 1 (owner, 2026-10-24): GARCH fit window and fit-failure fallback

Made during the run (parent `fr-run-v2b`, commit `ddcfad8`). Replay results are not affected. The
GARCH jobs run under it.

- **Revised 2026-10-24 (owner, grilling session; ADR 0005, terms in `GLOSSARY.md`).** The first
  bullet below is superseded. Fitting on all history put persistence at 1 for most research2003
  funds (53 of 62 origins), because volatility shifts level across decades. The rule is now:
  - **Dynamics window:** each fund's GARCH is fitted on its last 10 years, or 3 if 10 does not fit,
    and falls back to constant volatility otherwise.
  - **Shock pool:** every common day from the youngest fund's first price to the origin, weighted
    equally, standardized by running the fitted model over the whole pool.
  - **Level:** from the lookback. The 5-year sensitivity changes only the level.

  The compute cost is negligible.
- *(Superseded)* **Shape from all history, level from the lookback.** Each fund's GARCH(1,1)-t fit uses all of the
  fund's daily returns from its first price in the snapshot up to the origin (an expanding window),
  not the 3-year training window. The residual pool is the fit window's common rows. The level
  (mean and covariance of the simulated year) still comes from the origin's lookback, as in
  production (spec §4.3). The reason: the bank is a range of possibilities, not a forecast. A
  3-year fit in a calm period has no crisis in its shock pool and estimates thin tails, so it
  understates the black swans the optimizer must be robust to. Longer samples also converge more
  often.
- **Fit-failure fallback.** When a fund's fit fails (the optimizer does not converge, or invalid or
  non-finite parameters), that fund is simulated at constant volatility on its own standardized
  returns. This is QSE's and production's existing rule, already applied to near-constant,
  non-stationary and short-history funds. The other funds keep GARCH. The bank records each fallback
  fund, the task summary counts them, and the report labels them. An origin is now dropped
  (`garch_fit_failed`) only for unusable input (non-finite returns, or a day at or below −100%).
- **What reruns.** TSP GARCH reruns in full. Its first run (3-year fits, 9 origins dropped) is kept
  aside as superseded. research2003 GARCH runs only under this amendment. Both run in the same
  parent through the recorded resume override (`overrides.jsonl`: reason, commit, changed paths).
- **Run overrides already recorded, for the report.**
  - The CPU-hour total was raised from 240 to 760, because both engines' gates chose COBYLA-768.
  - research2003 replay was resumed with a 300 CPU-hour budget after its 165 CPU-hour stop. The
    local VM was throttled, which inflated the CPU time it counted.
  - Local runs used 10 workers, not the ceiling's 6.
- **Open question, not decided here.** The lookback itself could be chosen out of sample by a proper
  scoring rule (log score or CRPS of realized outcomes, with probability-integral-transform and
  tail-coverage checks, on monthly horizons). That choice would sit inside §7's overfitting check.
  Blending a recent-window model with a full-history model is the alternative to choosing one.
