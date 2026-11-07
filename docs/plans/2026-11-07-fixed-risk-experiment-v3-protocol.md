# Fixed-risk experiment protocol (v3): does a lower-drawdown mix beat the frontier mix?

Status: draft, revision 4, 2026-11-07. Not hash-locked. The design decisions of §10 were made on
2026-11-07 by Marshal on Jeff's delegation; the choices this document had to make on its own are
listed in §11, resolved after review (§11, "Review log").

This protocol inherits the
[v2 protocol](2026-10-21-fixed-risk-optimization-experiment-protocol.md) (revision 6 with §11
Amendment 1) wherever it does not say otherwise: the research menu and frozen snapshot (v2 §3a),
the fixed-risk band and risk levels (v2 §2, §3), band projection, Sobol pool, deduplicated starts,
cell labels and union-and-rescore pooling (v2 §4), the realized conventions, real returns and
regime buckets (v2 §5), the block bootstrap over origins (v2 §6, from v1 §6), the purged CSCV
adaptation (v2 §7), the deflated Sharpe ratio (v2 §7a), stop-on-breach and the parent/job
manifests (v2 §8), and the GARCH dynamics window and shock pool (v2 §11, ADR 0005). GARCH, where it
runs, also applies the simulated-volatility cap of ADR 0006. Terms follow `GLOSSARY.md`.

## 0. Why v3

v2 asked whether the max-U mix on a fixed-risk line beats the frontier mix, and how outcomes
change along a diversification-ratio slider. Its run (`fr-run-v2b`, all four jobs complete) found:

- At fixed risk, moving along the diversification-ratio slider made both the model's bad year and
  the realized bad year and drawdown worse, on both menus.
- The U1 mix sat close to the frontier mix: on research2003 the median slider position of the
  free-cell U1 winner was 0.01 to 0.08 across the six risk levels.
- The white-line hypothesis (max-U beats the frontier mix) was not supported on any menu or engine.

Three points came out of reading those results with the owner (2026-11-04):

1. **At fixed volatility, a lower expected return is not safer by itself.** Every mix on the line
   has the same model volatility. Giving up expected return only lowers drawdown if the mix
   behaves better in a crash.
2. **Year-end percentiles are not drawdown.** v2's objectives (U, max-Bad) score where the year
   *ends*. A year can end flat after a 25% fall in the middle. Drawdown depends on the path.
3. **The app ships ENB, and v2 never tested it.** The app's diversification measure is the
   effective number of bets on return steps, with the knee as its Optimized point. v2 tested the
   diversification ratio, a research measure.

The owner's question for v3: **at a given risk, can a mix with slightly lower expected return be
both more diversified and have a lower drawdown than the frontier mix, or should the app always
pick the frontier mix?** v3 answers it with an objective built for drawdown (arm 3), tested once
against the frontier mix, with the app's own Optimized point and three other candidates reported
beside it.

## 1. Scope and hypothesis

**Primary hypothesis (the only pass/fail test).** On the research menu, under History replay,
averaged with equal weight over the six fixed risk levels and over the 234 eligible origins, the
mix that minimizes the simulated tail drawdown (arm 3, §2), compared with the frontier mix (arm 1),
has a realized maximum drawdown within the year that is smaller (95% interval above zero) and by at
least 1 percentage point in point estimate, and gives up no more than 50 bp of realized annual
return (one-sided 95% lower bound). The test is defined in §6.

**Reported, not tested:**

1. Arms 4, 5 and 6 (crash-penalty mix, most loss contributors, the app's ENB knee) against the
   frontier mix and against arm 3, on the same statistics.
2. Arm 3 against the U1 mix (arm 2), the v2 control.
3. Diversification of the lower-drawdown mix: ENB, diversification ratio squared and ENLC of arm 3
   against arm 1 (the "more diversified" half of the owner's question).
4. Whether the simulation's drawdown ranking predicts the realized one (§5).
5. The exploratory ensemble screen of §7.3.

**Not in scope:** slider cells and the `d` grid of v2; max-Bad and U2–U4 as arms (their values are
recorded in the pool, §4.4); the Bayes–Stein comparator; the stability seeds; the 48 × 19
showcase surfaces; v2's `τ_r = 0.001` sensitivity as a separate check (that band is now the
tested pair's own band, §2.1); any change to the app before the decision of §6.4.
The TSP menu runs only as a confirmation after a pass (§6.4).

**What preregistration covers here.** v3 reuses the same frozen history as v2, and its arms were
chosen after the owner saw v2's realized results. This document fixes every analysis choice from
now on; it cannot undo the fact that the arm set was shaped by a look at the same years. The
thresholds of §6.3 (1 pp, 50 bp, 95%) were chosen after v2's realized intervals on these years were
seen; v2's realized-support rule used a 99% lower bound. The report states both.

## 2. Selection contract: the six arms

### 2.1 Shared definitions

For one menu at one origin (all from the origin's training side, nothing after the origin):

```
Σ, σ_i     training covariance and fund volatilities (v2 §2; contracts.OriginContext)
μ_s        expected returns: production menu_beta_blend, 50/50 sample mean and menu-beta prior
           (engine/stats.py:88-100; used by the app at engine/builder.py:314)
σ(w)       = sqrt(w' Σ w)
X(a)       = σ_min + a (σ_top − σ_min),  a ∈ {0.10, 0.25, 0.40, 0.55, 0.70, 0.85}
           σ_min the minimum-variance risk, σ_top the risk of the max-μ_s greedy fill
           (`contracts.RISK_FRACTIONS`; anchors.py `geometry`)
F_τ(r)     = { w : lo ≤ w ≤ hi, 1'w = 1, |σ(w) − r| ≤ τ r }                    (the band of half-width τ)
F_.01(r)   the wide band, τ = 0.01 (`contracts.TAU_R`)
F_.001(r)  the narrow band, τ = 0.001 (`contracts.TAU_R_SENSITIVITY`)
```

**Which band each arm uses.** For the tested pair (arms 1 and 3) the band is `τ_r = 0.001`
(`contracts.TAU_R_SENSITIVITY`); arms 2, 4, 5 use `τ_r = 0.01`; arm 6 sits on the exact line. Why:
in the wide band the frontier mix, which maximizes return, lands near its upper edge
(`σ ≈ 1.01 r`) and the lowest-drawdown mix near its lower edge (`σ ≈ 0.99 r`), so the comparison
would build in a drawdown advantage and a return cost for arm 3 (v2 §2: "same band is not same
risk"). v2 ran the narrow band with the same solver at its six showcase origins (`sens_tau` rows).

A **mix** is a weight vector `w`. The **bank** is the engine's 2,000 simulated one-year paths of
252 days for the origin and seed (`contracts.PathBank`). For a mix, path `p` has daily gross
returns `g_{p,1..252}` and wealth `W_{p,t} = Π_{u ≤ t} g_{p,u}`, with `W_{p,0} = 1`. Its compounded
year is `Y_p = W_{p,252} − 1`. Bad, Typical and Good are the linear 2.5th, 50th and 97.5th
percentiles of the 2,000 `Y_p` (objective.py:127-136).

Objective values used by the arms and recorded in the pool:

- **U-values**: `U_k = b·Bad + t·Typical + g·Good` with `U1 = (.60,.30,.10)`, `U2 = (.70,.20,.10)`,
  `U3 = (.50,.35,.15)`, `U4 = (.40,.40,.20)` (`contracts.ARMS`). **max-Bad** is Bad itself.
- **Path maximum drawdown**: `D_p(w) = max_t (1 − W_{p,t} / max(1, max_{s ≤ t} W_{p,s}))`, the
  largest peak-to-trough fall of the path, peak counted from the starting value 1. This is the
  definition the realized outcomes use (`realized._drawdown`, realized.py:86-88). An absorbed path
  (a day at or below −100%, §2.3) has `D_p = 1`.
- **Simulated tail drawdown** `TDD(w)`: the average of the 100 largest `D_p(w)` among the 2,000
  paths (the worst 5%; decision Q1, §10). Lower is better.
- **Worst historical fall** `H(w)`: the maximum drawdown, same definition, of the mix's own daily
  history from the menu's first common day to the origin's close (§2.5).
- **ENLC(w)**: the effective number of loss contributors in bad years (§2.6).
- **ENB(w)**: the effective number of bets, minimum torsion on the origin's `Σ`
  (`torsion.torsion_basis` torsion.py:70, `torsion.enb` torsion.py:109-111), as the app computes it
  (builder.py:326).
- **M(w) = DR²(w)** = `(Σ_i w_i σ_i)² / (w'Σw)`, the diversification ratio squared (anchors.py:62-64).
- `μ_s'w` and `σ(w)`.

### 2.2 The arms

Each arm is solved at every origin and every risk level `r = X(a)`.

| # | Arm | Rule | Role |
|---|---|---|---|
| 1 | Frontier mix `w_F(r)` | `argmax_{w ∈ F_.001(r)} μ_s'w` (v2's anchor at the narrow band, anchors.py `column_anchors`) | comparator for the test |
| 2 | U1 mix | `argmax_{w ∈ F_.01(r)} U1(w)` | control (v2's primary arm) |
| 3 | **Lowest simulated drawdown** | `argmin_{w ∈ F_.001(r)} TDD(w)` | **primary, tested** |
| 4 | Crash-penalty mix | `argmax_{w ∈ F_.01(r)} U1(w) − λ H(w)`, `λ = 0.1` | reported |
| 5 | Most loss contributors | the eligible pool member with the highest ENLC (§2.6) | reported |
| 6 | The app's ENB knee | the app's Optimized point at risk `r`, on the exact line (§2.7) | reported |

Arm 1 and arm 6 use only `μ_s` and `Σ`, so they are computed once per origin and are the same under
every engine. Arms 2, 3 and 4 are searched on the bank (§4). Arm 5 is a re-rank of what the other
arms' searches visited; it is never optimized directly.

### 2.3 Arm 3, the primary arm

Arm 3 minimizes `TDD`, the average of the worst 5% of path maximum drawdowns. It has no return
constraint: the band holds risk fixed and the test (§6) limits the return given up. In plain words:
among the mixes at this risk, it picks the one whose worst simulated years have the shallowest
falls along the way.

Replay mechanics: a replay path is a chain of runs of consecutive sample days (stationary block
bootstrap, mean run 21 days; `ranges.bootstrap_index`, engine/ranges.py:71, 129). The daily growth
of a mix is `g_t = 1 + A_t w` with `A` the recentred sample plus `μ_s/252` (banks.py:85-87), the same
growth the compounded years use. The path's wealth is the cumulative product of `g` over the path's
day indices in order. The bank today keeps the count matrix and run boundaries but not the ordered
indices (banks.py:88-116); v3 keeps the `P × 252` index on the bank. Replay's per-bank growth bound
(v2 §4) covers the drawdown computation too.

GARCH mechanics (confirmation only, §6.4): the mix's daily return is `y_pt = m'w + k(w) x_pt'w` on
the bank's levelled panel (`garch_bank.GarchBank`), with ADR 0006's cap applied in simulation. The
path's wealth is the cumulative product of `1 + y_pt`.

Absorbed paths, both engines: a path with a day of `g_t ≤ 0` is absorbed: `D_p = 1`, `Y_p = −1`,
as the GARCH rule; the candidate stays in the pool.

**Limit of the replay drawdown.** Runs average 21 days, so replay keeps losses that cluster within
about a month and breaks a longer bear market in the lookback into pieces joined at random. Replay
drawdowns therefore understate multi-month falls. GARCH carries clustering through its variance
recursion, which is why a replay pass must be confirmed under GARCH.

### 2.4 Arm 4, the crash penalty

`U1(w) − 0.1 · H(w)`, both in return units (a mix whose worst historical fall is 30% loses 3
percentage points of U1). `H` is the **worst** fall in the mix's history, not an average. Side checks
at `λ = 0.05` and `λ = 0.2` run at the six showcase origins only (§3).

Limitation, stated in the report: the history starts in 2003 (EEM's first price), so for origins
before 2009 it holds no complete major crash. The 2007–09 fall bottomed in March 2009; origins
from late 2008 on hold part or all of it. Before that, `H` ranks mixes by the milder falls of
2003–2007, and the penalty mostly reflects which holdings had small dips.

### 2.5 Worst historical fall `H(w)`

The menu's daily total returns (the snapshot's `data/returns.py` index) on its common rows, the
days on which all 19 holdings have a return, from the first common day (2003-04) to the origin's
close inclusive. The mix is held at constant weights every day (daily rebalanced; §11 item 5).
Returns are the actual returns, not recentred. `H(w)` is the maximum drawdown of the resulting
wealth path, by the definition of §2.1. The history is long (from about 750 to about 5,900 rows),
but `H` for a new mix is one matrix–vector product and a running maximum.

### 2.6 Arm 5, most loss contributors (ENLC)

**Definition** (simulation engines spec §5.3, never implemented until now). On the bank, fund `n`'s
contribution to path `p`'s additive year is `C_{p,n} = w_n S_{p,n}`, with `S` the path sums of the
fund's daily terms. Replay: `S = counts · A` (`P × N`, independent of the mix, once per bank).
GARCH: `S_{p,n} = 252 m_n + k(w)(Σ_t R'_{p,t,n} − 252 R̄'_n)` as in spec §5.3. The mix's **bad
years** are its 100 paths with the lowest compounded `Y_p` (worst 5%). Fund `n`'s loss contribution
is `ℓ_n = −mean_{p ∈ bad} C_{p,n}`. Shares over losers only, `s_n = max(ℓ_n, 0) / Σ_k max(ℓ_k, 0)`,
and

```
ENLC(w) = exp(−Σ_n s_n ln s_n)        (0 ln 0 = 0)
```

A fund with `ℓ_n < 0` gained in the mix's bad years (a hedge) and takes share 0. If no fund loses,
ENLC is undefined and recorded as missing. ENLC runs from 1 (one source of loss) to the number of
funds that lose.

**Re-rank rule.** At each `(origin, r)`, after arms 1–4 and 6 have been solved and the Sobol pool
scored, the **eligible pool** is every recorded mix (§4.4) that:

1. lies in the wide band `F_.01(r)`;
2. has a defined ENLC;
3. has `μ_s'w ≥ μ_s'w_F(r) − 0.005`: gives up at most 50 bp of model expected return against the
   frontier mix (§11 item 3).

Arm 5 is the eligible member with the highest ENLC; ties go to the higher `μ_s'w`, then to the
earlier record. The return tolerance matches the 50 bp line of the test, so arm 5 is a candidate
that could pass the return condition if the model's expected return were right.

### 2.7 Arm 6, the app's ENB knee: the app's surface plus one side column per risk

The app's Optimized point (glossary) at a fixed risk comes from these pieces of the app:

1. **Expected returns**: `μ_s` from `menu_beta_blend` (stats.py:88-100; builder.py:314).
2. **Measure**: ENB with the minimum torsion of the origin's `Σ` (builder.py:326).
3. **Frontier**: the app's frontier nodes (`optimize.frontier`) sit on their risk lines within
   `1e-6` (ladder.py:34-37, optimize.py:96-131). A solver answer becomes a ladder candidate only if
   it meets its risk line, the bounds, the budget and any return floor within `1e-8`
   (`ladder.FEASIBLE`, ladder.py:63, 173-180).
4. **Peak and ladder**: `ladder.peak_pools` solves each column from its frontier node, from
   `RANDOM_STARTS` (3) seeded random starts, and from the best mix of the column before it
   (ladder.py:269-270); then the neighbour sweeps of `spread_peaks`. `ladder.column` lays 12 return
   levels between the frontier node and the peak, 14 rungs in all (ladder.py:59, 241-300, 303-356;
   `surface.surface`, surface.py:49-78).
5. **Knee**: `suggest.balanced_level` (suggest.py:23-50). The return given up and the ENB gained are
   each rescaled to run from 0 to 1 over the ladder; the knee is the rung that maximizes `e − g`
   (the rung farthest above the straight line from the frontier node to the peak); a tie goes to
   the rung that gives up less return. Two ladders have no curve to read: one that gains no ENB
   answers the frontier node (suggest.py:45-46), and one that gains ENB for no return answers the
   peak, the last rung (suggest.py:47-48).

**How arm 6 is computed at the six experiment risks.** The app grids its columns at
`linspace(σ_min, σ_top, 48)` (optimize.py:122), which does not contain the six experiment risks
(`a = 0.10` is column 4.7), and `optimize.frontier` accepts only that grid. So:

1. The app's 48-column `surface()` runs unmodified, as the builder runs it.
2. For each experiment risk `r`, one extra **side column** is solved:
   - its **frontier node** is new code built from the app's pieces: `programs.frontier_point(r)`,
     never below the app node to its left in return, moved onto the line toward the greedy fill
     with `optimize.onto_risk` when it sits more than `1e-6` inside the ceiling (the two corrections
     of optimize.py:128-131), so it lies on `σ(w) = r` within `1e-6`;
   - its pool is solved by `EnbProgram.solve` from these starts: the frontier node;
     `RANDOM_STARTS` random starts (`ladder.random_start`), the generator seeded by
     `[SEED, round(r·1e6)]`; and the best mix (peak) of each of the two adjacent app columns' pools;
   - its ladder is laid by `ladder.column` and its knee read by `suggest.balanced_level`.
3. Nothing flows back into the app's 48 columns: a side column never starts, sweeps or re-ladders
   an app column.

So the measure, the ENB program, the ladder and the knee rule are the app's functions; the side
column's frontier node and its start list are new code (§11 item 4).

**Differences from the shipped app, stated in the report.** The menu and its caps are the
experiment's (research2003, 40% per fund, 10% per stock); the lookback is the experiment's 3 years,
where the app's window is 5 years (v2 §3), so the 5-year side check (§3) is where arm 6 uses the
app's own window; the side column's frontier node (exact risk) can differ slightly from arm 1
(highest return anywhere in the ±0.1% band). Both mixes are recorded.

## 3. Grid, origins, menu, engines (v2 settings kept, decision Q5)

- **Menu**: `research2003`, 19 holdings, the eleven funds at 0–40% and the eight 2004 mega-caps at
  0–10% (menus.py:221-240; v2 §3a). TSP only as a confirmation (§6.4).
- **Snapshot**: the v2 snapshot, unchanged:
  `~/portfoliosight-research/snapshots/2026-10-16-b0ef68baceaa` (D\* 2026-10-16, manifest
  `b0ef68ba…`).
- **Origins**: v2's research2003 schedule: **246 monthly origins, 2006-04 to 2026-09**
  (`fr-run-v2b/parent.json`, `menus.research2003.schedule`). **234** of them have a complete
  realized year in the frozen ledger and enter the test (`menus.research2003.cscv.months`, 234
  entries, the eligible origins frozen with the CSCV masks). The ledger's disjoint realized
  intervals number **19** (`menus.research2003.disjoint_interval_count` and the 19 entries of
  `disjoint_intervals`).
- **Risk levels**: the six `X(a)` of §2.1; the narrow band for arms 1 and 3, the wide band for arms
  2, 4 and 5, the exact line for arm 6 (§2.1).
- **Lookback**: 3 years (756 union-calendar rows, 90% complete-rows rule) primary. **5-year side
  check** at the five showcase origins where a 5-year window meets the same rule (2010-05, 2014-06,
  2018-07, 2022-08, 2026-09; v2 §3), all six arms, descriptive.
- **Showcase origins** (v2 §3 rule, indices `floor(j(K−1)/5)`, `data.showcase_indices`
  data.py:248): 2006-04, 2010-05, 2014-06, 2018-07, 2022-08, 2026-09. They host the arm 4 side
  checks (`λ = 0.05, 0.2`), the 5-year side check and the sizing run (§8.1). 2026-09 has no complete
  realized year, so realized side-check figures cover five origins and model figures six; 2006-04's
  history for `H` is only three years long (2003-04 to 2006-04).
- **Engines**: History replay is the primary engine. GARCH(1,1)-t filtered historical simulation
  (v2 §11 and ADR 0005, with ADR 0006's cap) runs only as the confirmation of a pass (§6.4).
- **Seeds**: training bank `20261013`; independent banks `20261113..17` (model figures of the
  locked selections, descriptive); bootstrap `20261201`; Sobol and random-start seeds as v2 §4
  (functions of `(menu, origin, engine, r, arm, start)` only).
- **Realized conventions** (v2 §5): monthly rebalancing to target is primary; daily rebalancing for
  forecast calibration only; the 10 bp cost variant reported beside. Horizons: the 1-year outcome,
  plus compounded **2-, 3- and 5-year** realized returns from the same origin where complete
  (§11 item 7).

## 4. Search and pool recording

### 4.1 Solver

Arms 2, 3 and 4 are searched with the v2 harness's `cobyla768` solver (COBYLA on the exact
objective, 768 calls per start, v1 settings; optimizer.py:80-85, 338-371). It is the solver v2's
agreement gates selected on both engines (`fr-run-v2b/parent.json`, `engines`). The band is two
inequality constraints, at the arm's own band (§2.1). Iterates are clipped to the bounds and
renormalized to the budget before evaluation, as in v2 (§11 item 6).

### 4.2 Starts

**One shared Sobol pool.** Each column has one pool of 256 Sobol points, projected once onto the
narrow band `F_.001(r)` (v2 §4's projection, `Geometry.band_points` with `τ_r = 0.001`) and scored
once per `(origin, r, bank)`. The narrow band lies inside the wide band, so the same projected
points are valid starts for every arm; no arm re-projects them. The points depend only on
`(menu, origin, lookback, r)`, never on the engine or the bank.

Three deduplicated starts per searched arm and risk level, taken in this order (two within
L1 ≤ `1e-6` count once, v2 §4):

1. the frontier mix `w_F(r)` (arm 1; it lies in both bands);
2. the ENB knee mix (arm 6), projected onto the arm's band if needed (it sits on the exact line
   within `1e-6`, so it normally needs no projection);
3. the shared Sobol points ranked by the arm's own objective, best first (ties to the lower pool row
   id): the best one fills the third start, and when a start is a duplicate the next-ranked point
   replaces it (search3.py `Column.collect_starts`).

### 4.3 Pooling

Every mix visited by any arm at the same `(origin, r)` on the same bank joins that column's pool with
its exact objective values (v2 §4, "union and rescoring"; optimizer.py:622). Each searched arm's
**selection** is the pool's best member inside that arm's own band on that arm's own objective; its
own-search result is kept beside it as the **native** result. So arm 3's selection is the
lowest-`TDD` mix in `F_.001(r)` anyone visited at that column. Ties go to the lower pool row id
(the earlier record). Arms 1 and 6 are fixed by their own programs and are not re-picked from the
pool. Arm 5 is the re-rank of §2.6.

**Side-check rows never enter a main selection.** The arm 4 side-check searches at the showcase
origins (`λ = 0.05` and `λ = 0.2`, §2.4) write their rows to the pool like every other search, with
their `λ` in the row's key, but every main selection (arms 2–5, pooled) reads only the column's main
rows: rows with no `λ` or with the main `λ = 0.1` (search3.py `Column.main_ids`). A side check's own
pooled selection reads the main rows plus its own rows.

**Execution order, frozen.** Ties go to the earlier record, so the order in which a task evaluates
mixes is part of the contract. Per origin task: first arm 6's side columns for all six risks
(engine-independent, §2.7); then the risk columns in increasing order, `a = 0.10, 0.25, 0.40, 0.55,
0.70, 0.85`. Within a column:

1. arm 1's frontier anchor (its starts and end points, source `anchor`);
2. arm 6's side-column pool members (source `knee_ladder`);
3. the shared Sobol pool (source `sobol`);
4. the searched arms in the order arm 2 (U1), arm 3 (lowest `TDD`), arm 4 (crash penalty,
   `λ = 0.1`), each over its starts in the order of §4.2, each start's solver calls in order and its
   end point last (source `search`);
5. the main selections: arm 1, then arms 2–4 (pooled and native), arm 5, arm 6 and the app's
   frontier node;
6. at the showcase origins, the arm 4 side checks, `λ = 0.05` then `λ = 0.2`, after the main
   selections, so they cannot change them.

This is the order of `search3.search_origin_v3`. The pool row id is the `record` column, the order of
evaluation within the task.

**The same search opportunity under GARCH.** Arm 3's pooled selection draws on every main row of its
column, arm 4's search included. So the GARCH confirmation (§6.4) runs arms 1, 2, 3 and 4 with the
same starts, order and pooling as replay (`contracts.V3_GARCH_ARMS`); arm 4's GARCH selection is
recorded but not reported. This changes only the engine, not the search opportunity: arm 3's
candidate pool under GARCH is generated the same way as under replay.

### 4.4 Pool recording (owner requirement)

For **every** mix evaluated at a column, the run writes one row:

| Field | Content |
|---|---|
| keys | menu, origin month, engine, bank seed, lookback, `r_fraction`, `r`, `λ` (arm 4 runs, side checks included), the arm that produced it, start index, call index, source (`search`, `sobol`, `anchor`, `knee_ladder`), `record` (the pool row id, §4.3) |
| weights | all `N` weights, float64 |
| model | `σ(w)`, `μ_s'w`, in-band flags for the wide and the narrow band |
| year-end | Bad, Typical, Good, mean, `ES_2.5` (objective.py:127-136) |
| objectives | U1, U2, U3, U4, max-Bad, `TDD`, `H`, ENLC (missing when undefined), ENB, DR² |
| drawdown detail | the median and the 95th-percentile path drawdown (the Q1 alternatives, §10), for later comparison only |

Rows from searched arms are every bank evaluation the solver made. Arms 1 and 6 do not search the
bank; for them the pool receives every distinct feasible end point their programs produced (the
frontier anchor's starts and end points; every member of the side column's ENB pool, §2.7), each
then evaluated on the bank. Their internal line-search steps are not recorded.

Volume, from the schedule: at most `3 arms × 6 levels × 3 starts × 768 calls = 41,472` search
evaluations plus `6 × 256 = 1,536` Sobol points per origin, before the anchor and ladder rows; about
10.7 million rows over 246 origins, about 4 GB uncompressed at float64. One Parquet file per origin
task, written sorted by `(lookback, r_fraction, arm, start, call, record)` (pool.py).

**Distinct mixes.** The pool keeps every evaluation, so the same weight vector can appear in several
rows (a start that is also a Sobol point, a solver that revisits a point). Wherever a statistic
counts or ranks mixes rather than rows (the ensemble screen of §7.3), two rows are the same mix when
every weight agrees after rounding to `1e-9`; the mix is represented by its lowest pool row id.

### 4.5 Labels and failures

v2's labels apply per `(origin, r, arm)`: `insufficient_starts`, `search_failed`, `anchor_failed`,
`growth_bound_failed`. The ENB port adds `knee_collapsed` (the ladder gained no ENB; arm 6 is then
the app's frontier mix, which is a valid selection, counted). Arm 5 adds `no_eligible` (no pool
member met §2.6's filter). These labels fall into two classes, which the report enforces
cell by cell across every eligible `(o, a)`:

- **Usable warnings** (`contracts.V3_USABLE`): `ok`, `insufficient_starts`, `growth_bound_failed`,
  `knee_collapsed`. The selection is valid and counted; the label is reported.
- **Verdict-blocking failures**: `search_failed`, `anchor_failed`, and `no_eligible` (arm 5 only,
  which is not tested). v1's rule R25 holds for these: there is no tolerated failure rate; a
  blocking failure for arm 1 or arm 3 is resolved only by a rerun under a recorded amendment, and
  while one is unresolved the verdict is labelled inconclusive.

### 4.6 Solver check for arm 3

`TDD` is a new objective, so before the lock the sizing run (§8.1) solves arm 3 at the six showcase
origins and six risk levels (36 columns) with `cobyla768` and with 1,536 calls per start. The check
compares the **native** arm 3 result of each call budget (its own three starts and iterates only),
not the pooled selection, so mixes visited by the other arms cannot hide a solver shortfall. The
768-call solver is accepted if its native `TDD` is within 0.1 percentage point of, or below, the
1,536-call native result in at least 34 of the 36 columns. If it fails, arm 3 runs at 1,536 calls
and the projection is redone (§11 item 6).

## 5. Measurements

Per locked selection (all six arms, plus the arm 4 side checks and the 5-year side check):

- **Model, training bank**: every pool field of §4.4.
- **Model, independent banks** (seeds `20261113..17`): Bad, `ES_2.5`, U1 and `TDD`, to show how
  much of arm 3's simulated advantage is search noise on the training bank.
- **Realized, monthly-rebalanced** (`realized.monthly_rebalanced`, realized.py:116): annual
  return (`ret_m`), maximum drawdown within the year (`dd_m`, the realized worst fall), and
  **realized volatility** (annualized standard deviation of the cohort's daily returns over the
  year; new in v3, needed for §5.1). Net of the 10 bp cost variant beside them. 2-, 3- and 5-year
  compounded returns where complete. Real (CPI-deflated) 1-year return and the regime label (v2 §5).
- **Realized, daily-rebalanced**: for forecast calibration only (v2 §5).
- **Risk difference**: `σ(w_arm) − σ(w_F)` beside every paired comparison; two members of the wide
  band can differ by up to `0.02 r`, of the narrow band by up to `0.002 r` (v2 §2, "same band is
  not same risk"). For the tested pair the report gives `σ(w_3) − σ(w_1)` per risk level and pooled
  as in §6.1: mean, 5th and 95th percentiles over `(o, a)`, and its share of `r`.
- **Simulation-to-realized ranking**: at each `(origin, r)`, the Spearman rank correlation across the
  six arms between model `TDD` and realized `dd_m`, with Kendall's τ (τ-b, which handles ties)
  beside it; the mean of each over origins per risk level, with a bootstrap interval. With six arms
  per column a single correlation is coarse, so the Spearman figure is reported as a
  **sign-agreement statistic**: whether the simulated and realized drawdown orderings agree more
  often than they disagree, not how strongly the one predicts the other.
- **Diversification of the selections**: ENB, DR² and ENLC of each arm; for arm 3 against arm 1,
  the mean difference and the share of `(origin, r)` where arm 3 has the higher ENB.
- **Cost**: seconds per evaluation of the full objective set, per arm search, per origin task; pool
  rows and bytes per task.

### 5.1 Realized drawdown is not volatility restated

All arms at one `(origin, r)` have the same model volatility within the band. Their realized
drawdowns can still differ, for four reasons, and the report explains each with the data:

1. **Order.** Volatility is computed from returns without regard to their order. Drawdown is the
   deepest fall of the path, so losses that come together (consecutive days or weeks) compound into
   a deep trough, while the same losses spread out recover in between. Mixes whose holdings'
   losses cluster in time draw down more at equal volatility.
2. **Crash co-movement.** A mix whose holdings fall together in a crash has a deeper trough than one
   that holds something that rose in the same weeks (long Treasuries in 2008 and early 2020).
   Volatility averages over calm and crash days alike.
3. **Drift.** At equal volatility a higher expected return lowers the expected drawdown (for a
   Brownian motion the expected maximum drawdown rises with volatility and falls with drift;
   Magdon-Ismail, Atiya, Pratap and Abu-Mostafa 2004). Giving up return without better crash
   behaviour makes drawdown worse, which is point 1 of §0.
4. **Estimated versus realized volatility.** The band fixes volatility estimated on the lookback.
   Out of sample, mixes at the same estimated volatility realize different volatilities, for
   example when correlations rise in a crisis.

The report shows realized volatility beside realized drawdown for arm 3 and arm 1, so a drawdown gain
can be read as lower realized volatility, a better path shape at the same realized volatility, or
both.

## 6. The confirmatory test and the decision rule

### 6.1 Estimands

For each eligible origin `o` (complete realized year; 234 origins) and risk level `a`:

```
ΔDD(o, a)  = dd_m(w_1(o, a)) − dd_m(w_3(o, a))      positive: arm 3 fell less
ΔRet(o, a) = ret_m(w_3(o, a)) − ret_m(w_1(o, a))    negative: arm 3 earned less
ΔDD(o)     = (1/6) Σ_a ΔDD(o, a)                     equal weight per risk level
ΔRet(o)    = (1/6) Σ_a ΔRet(o, a)
θ_DD       = mean over eligible o of ΔDD(o)
θ_Ret      = mean over eligible o of ΔRet(o)
```

`dd_m` and `ret_m` are the monthly-rebalanced realized maximum drawdown and annual return, gross of
the cost variant (realized.py:116). Both are fractions; 0.01 is one percentage point.

**Relative drawdown change (descriptive).** Beside `θ_DD` the report gives the share of arm 1's
drawdown that arm 3 avoids, `ρ(o, a) = ΔDD(o, a) / dd_m(w_1(o, a))`, pooled the same way (equal
weight over the levels within each origin, then over origins) with its 95% interval from §6.2. A
cell with `dd_m(w_1) = 0` has no ratio and is left out of its origin's average. The verdict does
not use it.

**Across risk levels: one pooled test, no per-level tests.** The six levels are averaged with equal
weight within each origin, then over origins. This makes one test, so no multiplicity correction is
needed. Per-level estimates are reported with unadjusted 95% intervals and are labelled
descriptive; no per-level claim is made. The report adds one descriptive flag: **"pass, uneven
across risk"** if the pooled test passes while three or more levels have a point estimate of
`ΔDD(a) < 0` or `ΔRet(a) < −0.005`.

### 6.2 Intervals

v1 §6's paired circular moving-block bootstrap over the chronological monthly origin index: block
24 origins, 2,000 resamples, seed `20261201`, the same resampled origins for both arms and all six
levels, the whole statistic recomputed in each resample (measures.py:9-10). Percentile intervals.
Block lengths 12 and 36 are reported as sensitivities and do not change the verdict. A second
sensitivity, also without effect on the verdict: a Newey–West interval on `ΔDD(o)`, the mean of the
234 per-origin values in date order with a Bartlett kernel at lag 12, `θ̂_DD ± 1.96 SE_NW`.

**Assumptions the intervals rest on.** The origins are not independent, and the block bootstrap is
valid only if the dependence it leaves out is small. Three sources of dependence are known:

1. **Overlapping realized years.** Monthly origins with one-year horizons share up to eleven of
   their twelve months, so neighbouring `ΔDD(o)` and `ΔRet(o)` are strongly correlated; only 19
   realized years are disjoint (§3).
2. **Shared estimation windows.** Neighbouring origins' 3-year lookbacks share up to 35 of 36
   months, so their covariances, expected returns, banks and selected mixes are correlated too.
3. **The expanding historical-fall penalty.** `H(w)` (§2.5) reads all history from 2003 to the
   origin, so its input grows with the origin and every later origin sees every earlier crash. It
   enters arm 4's objective directly. Arms 1 and 3 do not score it, but arm 3 selects from a pool
   that includes candidates found by arm 4's `H`-driven search (§4.3), so arm 3's candidate
   generation depends indirectly on expanding history. This is not future data (every `H` stops at
   the origin), but it makes the pool's content, and so arm 3, depend on position in time.

The bootstrap treats the series as stationary and its dependence as dying out within about 24
origins (two years). A regime that lasts longer than a block, or a change in the series' behaviour
over the twenty years (one crash early, calmer years later), breaks that assumption. The 12- and
36-origin blocks and the Newey–West interval are there to show how much the answer depends on it:
**when they disagree with the primary interval about whether (A) or (B) holds, the disagreement is
reported next to the verdict, not in an appendix.**

### 6.3 Pass rule

Arm 3 **passes** against arm 1 when both conditions hold:

- **(A) Drawdown**: the lower end of the two-sided 95% interval of `θ_DD` is above 0 **and**
  `θ̂_DD ≥ 0.01` (a point estimate of at least 1 percentage point). The 1 pp line is a relevance
  filter on the point estimate, not a tested claim; the report does not state that the improvement
  is at least 1 pp.
- **(B) Return**: the 5th percentile of the bootstrap distribution of `θ_Ret` (the one-sided 95%
  lower bound) is at or above `−0.005` (−50 bp).

**Why (B) uses the interval, not the point estimate.** The claim to be made is "arm 3 costs at most
50 bp a year". A point-estimate rule would let an arm that truly costs more pass by luck in a noisy
sample, and the return given up is paid every year. Testing that the plausible cost stays inside the
line is the standard non-inferiority form. It is one-sided because only a loss matters. The price
is power: an arm that truly costs nothing still fails if its one-sided bound sits more than 50 bp
below its point estimate. v2's pooled realized-return intervals for U1 against the frontier mix on
research2003, as v2's report printed them, were **99%** two-sided intervals (v2's realized-support
level, `evidence.SUPPORT_LEVEL = 0.99`, evidence.py:84, used at measures.py:394): −46.8 bp
[−92.1, −0.5] under replay and +4.7 bp [−35.5, +44.9] under GARCH. Both were recomputed from the run
artifacts for this revision (§8.5) and match. On the 95% scale of this protocol the replay figures
are a two-sided interval of [−82.8, −11.5] bp and a one-sided lower bound 30.8 bp below the point
estimate, so a zero-cost arm with U1's spread would usually pass (B); an arm farther from the
frontier mix will likely have a wider interval (§8.5). The report also states what the
point-estimate rule would have said, labelled descriptive; the verdict follows the interval.

**Error control.** The false-pass rate below is **nominal**: it holds only to the extent that the
block bootstrap of §6.2 is valid for these dependent, overlapping origins under its stationarity
assumption. It is not an exact guarantee. A pass needs both (A) and (B). Requiring every condition
to hold (an intersection–union test) keeps the overall false-pass rate at the level of each
condition without adjustment. The argument covers only the two interval conditions: the 95%
interval of `θ_DD` above zero and the one-sided lower bound of `θ_Ret`. The 1 pp filter is not part
of it; it can only turn a pass into a fail, so it cannot raise the false-pass rate, and it carries
no error statement of its own. The confirmations of §6.4 run in a fixed sequence, each only after
the one before passes, so the claim "confirmed on every stage" is controlled at the same nominal
level.

**Labels**: **pass**, **fail (drawdown)**, **fail (return)**, **fail (both)**, or **inconclusive**
(an unresolved failed cell, §4.5). All other comparisons are descriptive, including arm 3 against U1
(arm 2) on the same statistics, and arms 4–6 against arm 1 and arm 3.

### 6.4 Decision rule

1. **Arm 3 passes under replay** → **GARCH confirmation**: arms 1, 2, 3 and 4 at all 246 origins
   under GARCH (v2 §11, ADR 0005, ADR 0006's cap), pool recorded as §4.4. Arm 4 runs so that arm 3's
   candidate pool is generated the same way as under replay (§4.3); its GARCH selection is not
   reported. This changes only the engine, not the search opportunity. Arm 1 is the same mix as
   under replay. Same estimands and the same pass rule. The GARCH job is appended to the parent
   manifest as an amendment before it starts (v2 §9 pattern).
2. **GARCH confirms** → **TSP confirmation**: all six arms on TSP under replay (244 origins, five
   funds at 0–60%; v2 §3a), same test.
3. **TSP confirms** → the report recommends that the owner consider a lowest-simulated-drawdown
   point in the app. That is a separate product decision with its own ADR; this protocol does not
   make it.
4. **Any stage fails** → the sequence stops. A replay pass that GARCH does not confirm is reported as
   engine-dependent and not confirmed.
5. **Nothing passes** (arm 3 fails under replay, or a confirmation fails) → the recommendation is
   to **keep the app's ENB Optimized point as it is**. Arms 4–6 inform that recommendation but do
   not change it, since none of them was tested.

## 7. Descriptive analyses

### 7.1 Purged CSCV across the arms (v2 §7)

The six arms are the candidates. An arm's score on a set of origins is the mean realized `dd_m`
over the set, averaged with equal weight over the six risk levels (lower is better; rank 1 is the
worst test score). With six candidates the training choice's test rank `k` runs from 1 to 6, so
`ω = k/7` (v2's `k/5` was for four candidates) and `λ = ln(ω/(1 − ω))`. Blocks, purge and
embargo masks, the 60-origin minimum per side and the 50-split minimum are v2's, frozen in the
parent manifest. Because the masks depend only on the ledger, v2's research2003 count applies:
**35 of 70 splits evaluable**, below the 50-split minimum, so PBO is expected to be "not
computable". The rule is not relaxed; the per-arm test-score distributions over
the evaluable splits are still reported.

### 7.2 Deflated Sharpe ratio (v2 §7a)

Primary series: on the 19 disjoint intervals, `ΔDD(o)` of arm 3 against arm 1. Trials: arms 2–6
against arm 1 (five series). Same formula and caveats as v2 §7a; a diagnostic of selection bias,
never a gate.

### 7.3 Post-hoc ensemble screen (exploratory only)

The pool of §4.4 makes it possible to ask, afterward, whether a weighted mix of objectives would
have picked better mixes. No ensemble arm runs in this round. The screen is defined now so it cannot
be tuned after the fact:

- **Objectives**, each oriented so higher is better: `μ_s'w`, U1, `−TDD`, `−H`, ENLC, ENB.
- **Candidates**: within each `(origin, r)`, the **distinct mixes** (§4.4: weights equal after
  rounding to `1e-9`, each represented by its lowest pool row id) among the main rows (§4.3, side
  checks excluded) that lie in the wide band `F_.01(r)` and have all six values defined.
- **Scale**: each objective is replaced by its percentile rank among those candidates, with average
  ranks for ties.
- **Weights**: every point of the simplex grid with step 0.25 over the six objectives (126
  combinations).
- **Pick**: at each `(origin, r)` the candidate with the highest weighted rank score; ties go to the
  lowest pool row id.
- **Outputs**: `θ_DD` and `θ_Ret` against arm 1 for each combination, the purged CSCV over the 126
  combinations (PBO if computable), and the deflated Sharpe ratio with 126 trials.

**Keeping it out of the confirmatory test:**

1. The confirmatory result (§6) is computed from the locked selections, written to the report and
   its digest recorded in the run directory **before** any ensemble code reads a realized outcome.
2. The screen cannot change the v3 verdict or the decision rule of §6.4.
3. Any objective, scaling or weight added after results are seen is labelled "added after seeing
   results" in the report.
4. A promising ensemble is a hypothesis. Testing it needs a new preregistered protocol whose
   evidence was not used to choose it (for example, realized years that accrue after D\*
   2026-10-16, or a menu not used in the screen).
5. Limit, stated: the pool holds only mixes the six arms' searches visited, so the screen can only
   pick among neighbourhoods of those arms.

## 8. Sizing, resources, run location, artifacts

### 8.1 Sizing run (before the full run)

On the devbox (12 cores, 47 GB), the six showcase origins, all six arms at six risk levels, pool
recording on, the arm 3 solver check of §4.6. It measures: seconds per evaluation of the full
objective set; seconds per arm search; wall seconds per origin task; pool rows and bytes per task;
peak memory per worker. **No realized outcomes are computed in the sizing run.**

**Projection, from v2's observed per-task times, not from the showcase origins alone.** Task times
vary widely from origin to origin, and six origins do not sample the long right tail. v2's
research2003 replay job (`fr-run-v2b/research2003_replay`, same menu, origins, solver and worker
count) took 255.2 CPU-h (`usage.json`); its 246 task wall times (`progress.log`) had mean 3,562 s,
median 2,752 s and maximum 34,045 s. The six largest were showcase origins (2014-06 34,045 s,
2018-07 30,650 s, 2010-05 24,727 s), which also carried v2's 48 × 19 surfaces and sensitivities;
without the six showcase origins, mean 3,163 s, 95th percentile 6,783 s, maximum 11,149 s
(2020-12). The projection:

1. The sizing run measures v3's search seconds per `(origin, r, arm)` at the six showcase origins;
   the ratio of their sum to v2's main-grid search seconds at the same origins (the `seconds` of
   the `kind = main` selection rows in v2's task files, all cells and arms; 3,507 s at 2014-06) is
   the **scale factor**.
2. Each of the 246 origins gets v2's task wall time times the scale factor; at the six showcase
   origins, whose v2 times include v2's surfaces, v2's non-showcase median (2,726 s) is used
   instead, and v3's own side checks there are added as measured.
3. Projected wall time = the larger of (sum over origins / 10 workers) and the longest single
   projected task.

Rules, applied in order and recorded in the parent manifest:

- projected wall time of the replay stage ≤ 36 h on 10 workers → run as specified;
- 36–72 h → cut starts per arm from three to two (dropping the Sobol start), rerun §4.6 on the cut
  configuration, then lock;
- > 72 h after the cut → stop and report to the owner before the lock.

The sizing run may change only these resource items. It may not change an arm, an objective, the
test or a threshold.

### 8.2 Resources

10 worker processes (v2's local setting, v2 §11), one BLAS thread each; aggregate memory ceiling
24 GiB; a CPU-hour ceiling of twice the sizing projection, recorded in the parent manifest before the
run. v2's stop-on-breach rule: the first breach stops the job, keeps every artifact and marks it
`incomplete`.

### 8.3 Run location

The devbox. Run directories under `~/portfoliosight-research/`:

- `fr-v3-sizing/`: the sizing run;
- `fr-run-v3/`: the parent manifest and the `research2003_replay` job; the confirmation jobs
  `research2003_garch` and `tsp_replay` are added to the same parent as amendments when §6.4 reaches
  them.

The parent manifest records this protocol's path and SHA-256, the snapshot digest, the schedule,
the seeds, the solver, the side-check settings, the CSCV masks and the job budgets. The report
refuses a job with a different parent digest (v2 §8).

### 8.4 Artifacts and report

Per origin task: selections (one row per `(r, arm)` plus native rows and side checks), the pool
(§4.4), the anchors and the ENB ladder per column, timings. Per job: `job.json`, `progress.log`,
`usage.json`, `failures.jsonl`, `overrides.jsonl` (v2's layout).

The report goes to `docs/reviews/` (dated on completion, named
`<date>-fixed-risk-experiment-v3-report.md`) and is published as a private page whose link is given
to the owner. It contains: the verdict and its label; the two conditions with intervals; per-level
tables; arms 4–6 and arm 3 vs U1; diversification of the selections; realized volatility beside
drawdown; the risk difference `σ(w_3) − σ(w_1)`; the relative drawdown change of §6.1; the
simulation-to-realized ranking; regime buckets; 2-, 3- and 5-year returns; the side checks; CSCV
and DSR; the ensemble screen in its own section headed exploratory; every override and amendment;
and the limits stated in §1, §2.3, §2.4 and §2.7.

**Verdict wording.** The verdict uses the words of the hypothesis (§1) and of §6.3, and no stronger
ones. On a pass: "Averaged with equal weight over the six fixed risk levels and the 234 eligible
origins, the lowest-simulated-drawdown mix had a smaller realized maximum drawdown than the frontier
mix (95% interval above zero; point estimate X pp, at least the 1 pp relevance line) and gave up no
more than 50 bp of realized annual return (one-sided 95% lower bound Y bp)." The report does not
say the improvement is at least 1 pp; 1 pp is a filter on the point estimate (§6.3). On a fail, the
label names the condition that failed and gives the same figures.

### 8.5 Pre-lock power table, from v2's realized data

What the pass rule of §6.3 demands, measured on the only realized data in hand: v2's research2003
replay job, the free-cell U1 mix (pooled selection, training seed, `τ_r = 0.01`) standing in for
arm 3 against the frontier mix. Same estimands as §6.1 (six levels equal weight, then 234 eligible
origins), same bootstrap as §6.2 (block 24, 2,000 resamples, seed `20261201`). No v3 outcome was
read.

Sources: the selections in `~/portfoliosight-research/fr-run-v2b/research2003_replay/tasks/*.parquet`
(and `research2003_garch/tasks/` for the GARCH column), parent `fr-run-v2b/parent.json`; realized
outcomes are not stored in the run directory, so they were recomputed from the frozen snapshot
`2026-10-16-b0ef68baceaa` with `realized.realized_table`, exactly as `report.run_report` does
(report.py `make_callables`, `run_report`), and paired with `measures.Study.pick` /
`Study.compare` (measures.py:278-441). The same code reproduces v2's printed figures: replay
−46.77 bp [−92.11, −0.50] and GARCH +4.71 bp [−35.47, +44.92], both 99% intervals (§6.3).

| Figure | Replay (U1 vs frontier) | GARCH, for reference |
|---|---:|---:|
| Point estimate `θ̂_Ret` | −46.8 bp | +4.7 bp |
| Point estimate `θ̂_DD` | +0.32 pp | +0.25 pp |
| SD over origins of `ΔRet(o)` (six levels pooled) | 156.8 bp | 129.6 bp |
| SD over origins of `ΔDD(o)` | 1.12 pp | 0.65 pp |
| Bootstrap SE of `θ_Ret` (block 24) | 18.4 bp | 16.4 bp |
| Bootstrap SE of `θ_DD` | 0.19 pp | 0.09 pp |
| Two-sided 95% interval of `θ_DD` | [−0.03, +0.69] pp | [+0.09, +0.44] pp |
| Its half-width | 0.36 pp | 0.18 pp |
| Two-sided 95% interval of `θ_Ret` | [−82.8, −11.5] bp | [−28.5, +35.2] bp |
| Its half-width | 35.6 bp | 31.9 bp |
| One-sided 95% lower bound of `θ_Ret` | −77.6 bp | −23.2 bp |
| Point minus that bound (one-sided half-width) | 30.8 bp | 27.9 bp |
| **Smallest `θ̂_DD` passing (A)**: interval above zero / with the 1 pp filter | 0.34 pp / **1.00 pp** | 0.16 pp / **1.00 pp** |
| **Smallest `θ̂_Ret` passing (B)** | **−19.2 bp** | **−22.1 bp** |
| Relative drawdown change `ρ` (§6.1), with 95% interval | 3.7% [0.8%, 6.6%] | n/a |

The "smallest passing" rows assume the bootstrap distribution keeps its shape and moves with the
point estimate. The i.i.d. standard errors would be 10.3 bp and 0.07 pp; overlapping years make the
block bootstrap's 1.8 to 2.5 times wider.

What it means, with a normal approximation and the bootstrap SE as the spread:

- **(A)** At U1's spread the interval condition needs only 0.34 pp, so the 1 pp filter is what
  binds: (A) passes about half the time if the true improvement is exactly 1 pp, and almost always
  (above 99%) at 1.5 pp. Doubling the spread moves the interval threshold to about 0.73 pp, still
  below the filter.
- **(B)** At U1's spread, an arm that truly costs nothing passes (B) about 86% of the time; one that
  truly costs 25 bp, about 39%. Arm 3 sits farther from the frontier mix than U1 does (U1's median
  slider position was 0.01 to 0.08, §0), so its intervals will likely be wider. If arm 3's SE is 1.5
  times U1's, a zero-cost arm needs `θ̂_Ret ≥ −4.6 bp` and passes about 57% of the time; at twice
  U1's SE it needs `θ̂_Ret ≥ +10.5 bp` and passes about 39% of the time.

So (B) is reachable at U1's spread and becomes a coin flip or worse if arm 3's realized return
differences are 1.5 to 2 times as spread out. The sizing run computes no realized outcomes (§8.1),
so arm 3's spread is not known before the lock. §11 item 1 records this.

## 9. Workflow

1. **Build** on `feature/fixed-risk-experiment`, in `portfoliosight/research/fixedrisk/`: the
   ordered day index on the replay bank and path wealth on both banks; `TDD`, `H` and ENLC; arms 3
   and 4 as COBYLA objectives; the arm 5 re-rank; the arm 6 wrapper: the app's 48-column surface
   plus one side column per experiment risk (§2.7); the pool writer; realized volatility and
   2/3/5-year horizons in `realized.py`; v3 constants beside v2's in `contracts.py`; the v3 report.
   Scoped tests in `tests/research/fixedrisk/`, written first: drawdown against an explicit daily
   loop, ENLC on the spec §5.3 single-fund and hedge cases, the knee wrapper against `suggest.balanced_level` on
   the app's own ladder, pool rows complete for every evaluation.
2. **Sizing run** (§8.1); resource decisions recorded.
3. **Lock**: this protocol's hash goes into the parent manifest.
4. **Replay run** of research2003 (§3).
5. **Confirmatory analysis** (§6), written and its digest recorded; then the descriptive analyses
   (§7), the ensemble screen last.
6. **Confirmations** per §6.4, only after a pass.
7. **Report** (§8.4).

## 10. Decision record

Decided 2026-11-07 by Marshal on Jeff's delegation; Jeff may revisit.

**Q0. GARCH explosions.** Chosen: cap each fund's simulated volatility at `k` times that fund's
realized volatility in the lookback, with `k` as ADR 0006 sets it; record every cap hit (count per
fund, path and day); report the sensitivity of the results to seeds, path counts and cap values.
Applies only to the GARCH confirmation. Why: fitted funds with persistence of about 0.997–0.999
(C, IYR, SPY) let simulated variance wander up on a few paths, and levelling turns large log returns
into huge simple returns (simulated means of 100× and more at the 2010-08 and 2011-01 origins).
Alternatives: (a) no cap, which keeps the explosions; (b) a persistence cutoff of 0.995 with
constant-volatility fallback, which would drop the clustering of SPY, C and IYR; (c) a cap tied to
the GARCH model's own long-run variance `ω/(1−α−β)`, rejected because that variance is itself
inflated when persistence nears 1 (Codex review, 2026-11-05).

**Q1. Simulated drawdown measure.** Chosen: the average of the worst 5% (100 of 2,000) of the
paths' maximum drawdowns. Why: it measures the bad tail, like expected shortfall, and averaging 100
paths is steadier to optimize than one path. Alternatives: (a) the median path's drawdown, which
ignores crashes; (b) the 95th-percentile path's drawdown, one path and noisier. Both alternatives
are recorded in the pool for later comparison.

**Q2. Pass line.** Chosen: arm 3 gives up at most **50 bp** of realized annual return and improves
the realized drawdown by **at least 1 percentage point** on average, with the 95% interval of the
improvement above zero. (After review, §6.3 applies the 1 pp to the point estimate as a relevance
filter; it is not a tested claim.) Alternatives for the return line: (a) 25 bp, stricter, harder
to pass with 19 disjoint years; (b) 100 bp, more lenient, a cost most users would notice.

**Q3. Crash-penalty weight.** Chosen: `λ = 0.1`, with side checks at 0.05 and 0.2 on the six
showcase origins. Alternatives: a larger weight, which makes arm 4 a pure "least historical crash"
mix; a smaller one, which makes it the U1 mix.

**Q4. The app's ENB knee.** Chosen: ported unchanged (same `μ_s` blend, same ENB measure, same
ladder and knee rule), evaluated at the six risk levels (through side columns, §2.7).
Alternatives: (a) retune the knee toward drawdown, which would test a new rule rather than the app;
(b) use the ENB peak instead of the knee, which is not what the app opens on.

**Q5. Keep v2 settings.** Chosen: 3-year lookback with a 5-year side check, monthly rebalancing,
the same 246 research2003 origins, 2- and 3-year realized returns beside 1-year, the same six risk
levels and the ±1% band. (After review: 5-year returns added, §11 item 7; the tested pair uses the
±0.1% band, §2.1.) Alternative: change the lookback or horizons, which would make v3's results
not comparable with v2's.

**Q6. One confirmatory test.** Chosen: only arm 3 against arm 1 is pass/fail; everything else is
reported. Alternatives: (a) test every arm with a multiplicity correction (for example Holm over
four), which spreads power over hypotheses the owner did not ask to decide on; (b) no confirmatory
test, which leaves the owner's question without a predeclared answer.

## 11. Protocol choices (resolved)

Choices this document had to make that §10 does not decide, each with the option taken. All were
reviewed before the lock (see "Review log" below).

1. **How the return condition is tested.** The one-sided 95% lower bound of `θ_Ret` at or above
   −50 bp (§6.3), with the point-estimate verdict shown beside it as descriptive. Alternative: point
   estimate only, more likely to pass, weaker claim. The power table (§8.5) shows (B) reachable at
   U1's spread (a zero-cost arm passes about 86% of the time; it needs `θ̂_Ret ≥ −19 bp`), falling to
   about 57% and 39% if arm 3's spread is 1.5 and 2 times U1's. Not practically unreachable, so the
   rule is kept unchanged; the risk is that a wide arm-3 spread fails (B) without any real cost.
   **Resolved 2026-11-07 (orchestrator, on Jeff's delegation via Marshal), after review.**
2. **Combining risk levels.** Equal weight per level within each origin, one pooled test, per-level
   results descriptive (§6.1). Alternative: per-level tests with a Holm correction, six chances to
   pass at lower power each. **Resolved 2026-11-07 (orchestrator, on Jeff's delegation via
   Marshal), after review.**
3. **ENLC re-rank filter.** In the wide band, ENLC defined, and model expected return within 50 bp
   of the frontier mix (§2.6). Alternatives: no return filter (arm 5 may pick a very low-return
   mix); 25 bp. **Resolved 2026-11-07 (orchestrator, on Jeff's delegation via Marshal), after
   review.**
4. **ENB knee at the experiment risks.** The app's 48-column `surface()` unmodified, plus one side
   column per experiment risk (frontier node from `programs.frontier_point` and `onto_risk`; starts
   from that node, `RANDOM_STARTS` seeded random starts and the two adjacent app columns' peaks;
   `ladder.column`; `balanced_level`), with nothing flowing back into the app's columns (§2.7). It
   replaces revision 1's 54-column grid, which would have changed the app's own columns'
   neighbours and sweeps. **Resolved 2026-11-07 (orchestrator, on Jeff's delegation via Marshal),
   after review.**
5. **Rebalancing in the worst historical fall.** Constant weights every day (daily rebalanced), the
   same convention as the simulated paths (§2.5). Alternative: monthly rebalanced, closer to the
   realized convention, slightly path-dependent on rebalance dates. **Resolved 2026-11-07
   (orchestrator, on Jeff's delegation via Marshal), after review.**
6. **Solver and its check.** v2's `cobyla768` for arms 2–4, three starts (frontier mix, ENB knee,
   best Sobol point), pooled rescoring, and the 768 vs 1,536 call check on 36 columns for arm 3,
   comparing native results (§4.1, §4.6). Alternative: a gradient solver for `TDD` (the path
   drawdown has piecewise gradients), faster but it would need its own finite-difference and
   agreement checks. **Resolved 2026-11-07 (orchestrator, on Jeff's delegation via Marshal), after
   review.**
7. **Multi-year horizons.** 2, 3 and 5 years: 2 and 3 as the v3 brief asks, 5 for continuity with
   v2 (realized.py:34), at almost no cost (§3, §5). **Resolved 2026-11-07 (orchestrator, on Jeff's
   delegation via Marshal), after review.**
8. **Drawdown definition details.** Peak counted from the starting value 1 (as the realized code
   does), simulated paths at constant weights (daily rebalanced, as the bank simulates), worst 100
   of 2,000 paths, absorbed paths at `D_p = 1` (§2.3). The simulated paths are daily rebalanced and
   the realized outcome monthly rebalanced; the mismatch is assumed small next to a 1 pp line (an assumption, not a measured result) and is stated.
   **Resolved 2026-11-07 (orchestrator, on Jeff's delegation via Marshal), after review.**
9. **Independent banks.** Keep v2's five independent banks for model figures of the locked
   selections (§5), to show the training-bank search bias in `TDD`. Alternative: drop them to save
   time. **Resolved 2026-11-07 (orchestrator, on Jeff's delegation via Marshal), after review.**
10. **Ensemble screen grid.** Six objectives, percentile-rank scaling with average ranks for ties,
    simplex step 0.25, 126 combinations, distinct wide-band mixes from the main rows, ties to the
    lowest pool row id (§7.3). Alternative: include U2–U4, max-Bad and DR² (many more
    combinations, more chance findings). **Resolved 2026-11-07 (orchestrator, on Jeff's delegation
    via Marshal), after review.**
11. **Scope of the GARCH confirmation.** Arms 1, 2, 3 and 4, all 246 origins (§6.4). Arm 4's
    search is kept so that arm 3's candidate pool is generated the same way as under replay; arm
    4's GARCH selection is not reported. This changes only the engine, not the search opportunity
    (round 2 of the review). Alternative: all six arms, more context at more cost. **Resolved
    2026-11-07 (orchestrator, on Jeff's delegation via Marshal), after review.**
12. **Resource settings.** 10 workers, 24 GiB memory ceiling, a CPU-hour ceiling of twice the
    sizing projection; wall-time rules of §8.1: up to 36 h runs as specified, 36–72 h cuts to two
    starts, over 72 h after the cut stops and reports; the projection scales v2's observed per-task
    times, not the showcase origins alone. **Resolved 2026-11-07 (orchestrator, on Jeff's
    delegation via Marshal), after review.**
13. **"Pass, uneven across risk" flag.** Descriptive only, raised when three or more levels go the
    wrong way (§6.1). Alternative: no flag. **Resolved 2026-11-07 (orchestrator, on Jeff's
    delegation via Marshal), after review.**

### Review log

Revision 1 was reviewed on 2026-11-07 by a Fable agent, because Codex could not run in this
sandbox (its read-only sandbox could not create a namespace, so it read no files). Findings: P0
none; P1 ×2 and P2 ×5, all applied in revision 2, with the P3 details:

- P1-1, band edges: the tested pair on the ±0.1% band (§2.1); `σ(w_3) − σ(w_1)` reported (§5).
- P1-2, hypothesis against test: the hypothesis restated as the test (§1); the 1 pp line a
  relevance filter on the point estimate (§6.3, §8.4); error control limited to the two interval
  conditions (§6.3).
- P2-1, ENB knee: the app's 48-column surface plus side columns; new code named as such; tolerance,
  previous-column start and the third `balanced_level` case stated (§2.7, §11 item 4).
- P2-2, power: the table of §8.5 from v2's realized data; v2's quoted intervals verified and
  corrected from 95% to 99% (§6.3).
- P2-3: thresholds chosen after seeing v2's intervals, stated (§1).
- P2-4: the relative drawdown change, descriptive (§6.1).
- P2-5: absorbed paths kept in the pool at `D_p = 1`, `Y_p = −1` (§2.3).
- P3: native results in the solver check (§4.6); `ω = k/7` (§7.1); Newey–West sensitivity (§6.2);
  Kendall's τ beside Spearman (§5); sources of 234 and 19 (§3); resource rules on v2's task times
  (§8.1).

Round 2, 2026-11-07: Codex reviewed revision 2 (P1 ×2, P2 ×3), all applied in revision 3, with the
wording matched to the harness code (`search3.py`, `pool.py`):

- P1: side-check rows (`λ = 0.05`, `0.2`) recorded in the pool but excluded from every main
  selection (`Column.main_ids`); the execution order of searches frozen and named (§4.3, §4.4).
- P1: one shared Sobol pool of 256 points projected onto the narrow band, valid for every arm; the
  per-arm projection wording removed (§4.2).
- P2: the GARCH confirmation keeps arm 4's search so arm 3's pool is built as under replay; arm 4's
  GARCH selection not reported (§4.3, §6.4, §11 item 11).
- P2: the ensemble screen ranks distinct mixes (weights equal after rounding to `1e-9`), average
  ranks for ties, final ties to the lowest pool row id (§4.4, §7.3).
- P2: false-pass control called nominal and conditional on the block bootstrap; dependence and
  stationarity assumptions stated; sensitivity disagreements reported next to the verdict (§6.2,
  §6.3).

Round 3, 2026-11-07: Codex reviewed revision 3 (no P0/P1; P2 ×2, P3 ×1), applied in revision 4
without a further round:

- P2: labels split into usable warnings (`contracts.V3_USABLE`) and verdict-blocking failures, the
  report enforcing the split per cell (§4.5).
- P2: arm 3's indirect dependence on expanding history through arm 4's candidates stated (§6.2).
- P3: `contracts.V3_PROTOCOL_REVISION` to be synchronized with this document before the lock; the
  daily/monthly rebalancing mismatch stated as an assumption (§11).
