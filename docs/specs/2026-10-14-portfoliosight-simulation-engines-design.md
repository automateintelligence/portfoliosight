# PortfolioSight simulation engines and diversification measures: design spec

Date: 2026-10-14. Status: draft for the owner's review; no code until approved. Owner: Jeff Daniels. Repo: `github:automateintelligence/portfoliosight`, branch `main`.

Successor to §4.6, §4.7 and §4.9 of `docs/specs/2026-10-13-portfoliosight-demo-design.md` (the demo spec). Everything the demo spec says that this document does not change stays in force. Inputs: the demo spec; `ROADMAP.md`; `portfoliosight/engine/ranges.py`, `torsion.py`, `ladder.py`, `builder.py`; `docs/reviews/2026-10-13_gate-change_engine-2.md`; `docs/plans/2026-10-13-qse-lake-total-return-repair-prompt.md`; QSE pull request `automateintelligence/quant-scenario-engine#164` (branch `feature/joint-fhs`, head `37cc6932f8`, open); the owner's decisions of 2026-10-14 (§3). Choices made here where the owner left them open are marked **[choice]** with a one-line reason; what the owner must decide is in §13.

## 1. Purpose

The page shows, for every mix, a one-year Bad / Typical / Good range and a diversification word. Both numbers come from one place each: the range from `portfoliosight.engine.ranges.one_year_ranges`, the word from the minimum-torsion effective number of bets (ENB). This spec replaces the single range method with three selectable engines, fixes a measurement problem in the diversification number, and sets out how we decide when a new engine is good enough to become the default.

The owner's goal is a copula simulation that measures the cross-dependence of the whole portfolio, especially in bad years. The GARCH-t filtered historical simulation (FHS) is the prudent first step toward it: it builds the volatility model and the shock pool that the copula then replaces through one seam.

## 2. The finding: minimum-torsion bets are inflated on a correlated menu

Measured on 2026-10-14 on the live 5-year tensors:

- Example Portfolio (23 funds): holding ONE fund alone scores 3.5 to 14.4 bets (median 10.0; VBIAX alone 14.4). Every one of the 672 ladder mixes scores above the number of funds it holds (weights above 0.5%); mixes holding 4 funds score 9 to 12.6.
- TSP (5 funds): single funds score 1.0 to 2.5.

Cause. The torsion is computed from the return covariance alone, with no look-through to holdings. On a menu of highly correlated funds the minimum-torsion factors sit far from the funds themselves, so one fund's risk spreads over many factors and a one-fund portfolio looks like many bets. The measure is a valid decomposition of variance (the shares sum to 1), but it does not answer the visitor's question "how many separate things am I betting on". The ladder optimizer (demo spec §4.7) maximizes this inflated number, so the map, the word and the Optimized point inherit the problem.

Holdings look-through (counting the stocks and bonds behind the funds) would answer the question directly, but none of the current data sources provides fund holdings; it is parked on the roadmap.

## 3. Owner decisions (requirements) and non-goals

1. Three engines, selectable in Settings: History replay (the current stationary block bootstrap), Volatility model (GARCH(1,1)-t FHS), Copula (fitted dependence replacing the resampled shock rows through QSE's `ShockSource` seam). The setting governs the one-year ranges everywhere they appear: the risk-slider readouts, the result strip and its bar, the mix cards, `POST /v1/range`. It can also govern the diversification measure (§5). Default: History replay until the others are validated (§10).
2. Level and shape: a mix's simulated mean and volatility are scaled to the chart's expected return and risk for the selected lookback (level follows the lookback); the shape (fat tails, volatility persistence, cross-fund dependence) is fitted on the longest history held per fund, up to ten years, and is the same for every lookback. Volatility starts from the long-run variance, not today's.
3. QSE is installed at a pinned commit with `--no-deps`; PortfolioSight imports `qse.distributions` only. No forks, no ports: improvements go back to QSE as pull requests.
4. Step 0 of the phase: tag the deployed dashboard (commit, Cloudflare Worker version, KS-001 image) so it can be rolled back.

Non-goals: holdings look-through; intraday or multi-year horizons; views or stress scenarios fed into the simulation (entropy pooling); regime switching; a Student-t toggle on the normal figure; per-visitor engine persistence beyond the URL.

## 4. Engines

### 4.1 Common frame

Every engine produces, for a mix `w`, `P = 2,000` one-year paths of `H = 252` daily simple returns, compounds each path (`Y_p = ∏_t (1 + y_{p,t}) − 1`) and reports the 2.5th, 50th and 97.5th percentiles (linear interpolation) as Bad, Typical, Good, plus the engine-independent normal range `μ ± 1.96σ` (details only, "textbook bell-curve figure"). Output shape and names are those of `one_year_ranges` today, with the additions of §7.

| id | Settings label | shocks | volatility | dependence between funds |
|---|---|---|---|---|
| `replay` | History replay | runs of real days from the lookback sample | the sample's own | the sample's own days |
| `garch` | Volatility model | real standardized residual rows, resampled one day at a time | fitted GARCH(1,1)-t per fund, long-run start | the residual rows (empirical) |
| `copula` | Copula | drawn from a fitted vine copula with fat-tailed margins | same as `garch` | fitted pair copulas (tail dependence beyond the history) |

Shared draws, so mixes are comparable. Within a build, every mix (frontier nodes, ladder levels, the entered mix, and later any mix asked through `/v1/range`) uses one draw per engine: `replay` the existing day-index matrix (`bootstrap_index`, seed `20261013`); `garch` one pool-row matrix `I_pool` (`P × H`, QSE `draw_row_indices`, seed `20261013`); `copula` one shock tensor `Z` (`P × H × N`, seed `20261013`). Two mixes under one engine differ by their weights alone. Across engines the paths are different objects (different mechanisms), so engines are compared on their percentiles, never path by path.

Determinism. BLAS on one thread during a build (as today); the GARCH fit is deterministic given the series and the pinned `arch` version; the vine fit is deterministic given the data, the family set and the pinned `pyvinecopulib` version when run single-threaded (`FitControls(num_threads=1)`); all seeds fixed. Building twice from the same price records, `D_G`, bounds and versions gives identical canonical JSON (the demo spec's §4.12 test, extended to every engine). Each engine's parameters and library versions are recorded in the tensor (§7) so a figure can always be traced to its method.

### 4.2 History replay (unchanged)

The stationary block bootstrap of demo spec §4.9: the mix's daily returns over the lookback sample, recentred on `μ_s'w / 252`, resampled in runs of mean length 21 days, 2,000 paths. Its volatility is not rescaled (the sample's own, which is the lookback's up to the correlation shrinkage). **[choice]** It keeps its exact current definition so the default engine's figures do not move under the owner while the others are validated; whether it should also take the §4.5 volatility step is decision 7, §13.

### 4.3 Volatility model: GARCH(1,1)-t filtered historical simulation

**Shape panel.** For the funds included in the window (demo spec §4.2 rule; a fund set aside for the lookback is not in the panel), the last `S = 2,520` rows of the calendar ending at `D_G` (the union of the included funds' trading days): each fund's daily total returns on its own available rows, `NaN` elsewhere. A fund with less than ten years contributes what it has. The panel is the same for every lookback whose included fund set is the same; its digest (`shape.sample_sha256`, the §4.9 `sample_digest` with `NaN` encoded as the canonical quiet NaN) is stored.

**Fit.** `qse.distributions.joint.fit_garch_t_panel(panel)`: per fund, by maximum likelihood on its non-missing rows,

```
r_t = μ + ε_t,   ε_t = σ_t z_t,   σ²_t = ω + α ε²_{t−1} + β σ²_{t−1},   z_t ~ t_ν scaled to unit variance
```

returning `(μ, ω, α, β, ν)` in the units of the returns (QSE's fitter lets `arch` rescale the series for its optimizer and converts the parameters back; nothing is scaled here), the conditional volatility `σ_t`, the standardized residuals `z_t = ε_t / σ_t` on the fund's rows, and a status. The fund's own full history fits its volatility persistence and tail; only the cross-fund dependence is limited to the overlap.

**Fallbacks** (QSE's rules, adopted as they are; the tensor records the status of every fund):

| status | rule | simulated as |
|---|---|---|
| `garch` | fit converged, parameters valid | the recursion above |
| `insufficient_history` | fewer than 252 rows | constant volatility: `α = β = 0`, `ω` = sample variance, `z = (r − mean) / sd` |
| `near_constant` | daily sd below `3e-4` (about 0.5%/yr): TSP G (0.3%/yr) always; SGOV, BIL and SHV sit near the line and fall on either side by window, so the rule decides and the tensor names them | constant volatility as above; sd at or below `1e-12` means zero residuals |
| `fit_failed` | optimizer failed, parameters invalid or non-finite | constant volatility |
| `non_stationary` | `α + β ≥ 1 − 1e-4` (no long-run variance) | constant volatility |

A fallback fund goes through the same recursion with its shock merely scaled, so every fund takes part in the joint rows. A fund so young that it has only 227 to 251 rows of history (the §4.2 start rule lets it into the 1-year view) is a constant-volatility fund; the Settings excluded-fund list is not involved, but the details view names fallback funds ("volatility held constant: TSP G, SGOV").

**Residual pool.** The rows on which every included fund has a residual (QSE's "common rows"), in panel order; each column re-standardized to mean 0 and variance 1 (`ddof = 0`; QSE `restandardize=True`), which leaves ranks, correlations and the empirical copula of the rows unchanged and makes the simulated unconditional mean and variance the model's in expectation (§4.5 then pins every mix's exactly). The pool contains the lookback sample's rows (the panel spans the window and residuals exist wherever returns do), so it has at least the window's 126 rows; a pool below 126 rows marks the engine `unavailable` for that tensor with the reason "not enough shared history for the volatility model" and the page disables it. QSE's own floor of 60 rows is never relied on. A short pool (a menu holding a young fund) identifies joint tails poorly; the tensor's `shape.pool_rows` says how many rows there are and the details view shows it.

**Splice guard.** The store's total-return index of a seeded fund is the lake's back-adjusted history spliced with the provider's tail at `adjusted_through` (demo spec §5.1). A missing corporate action is fund-specific; a crash is cross-sectional. So a fund whose standardized residual on its own splice date has `|z_n| > 6` **and** sits more than 6 away from the median residual of the other included funds that day (`|z_n − median_m z_m| > 6`) fails the build with the fund and date named (nothing is clipped). `|z| > 6` on any other date, or on the splice date with the rest of the menu moving too, is recorded in `shape.outliers` (fund, date, `z`) for the validation report and fails nothing. A missing small dividend (a 1% drop on a fund with 1% daily volatility is `z ≈ −1`) passes this guard; the provider cross-check of demo spec §4.1 is the defence there.

**Simulation.** `simulate_fhs_panel(fit, P, H, row_indices=I_pool, start="long_run")` gives `R` of shape `P × H × N`: at every (path, day) one pool row is drawn and that whole row is the day's shock for every fund, so funds keep moving together as they did on real days; each fund runs its own recursion from its long-run variance `ω / (1 − α − β)`. Memory: `2,000 × 252 × 23 × 8` bytes is 93 MB (30 funds: 121 MB); QSE measured a 126 MB peak at 30 funds on 2 CPUs in 0.14 to 0.22 s. The fitted drift `μ` and the long-run variance are replaced by the level step (§4.5), so the simulation supplies shape only.

### 4.4 Copula

The same fit, pool and recursion as §4.3; only the source of the shock rows changes, through `simulate_fhs_panel(..., shock_source=...)`.

**Margins.** For fund `n` the margin of its shock is the empirical distribution of its pool column (the quantile function by linear interpolation between order statistics), which is fat-tailed because the column is the fund's GARCH-t standardized residuals **[choice]**: with the same margins as `garch`, the two engines differ in the dependence model and nothing else, so the validation isolates what the copula adds; and a parametric Student-t margin with the fitted `ν` would, over the `P·H = 504,000` draws of a build, produce a largest shock of about 75 standard deviations at `ν = 2.5` and still 25 at `ν = 4`, a day at or below −100% on a single-fund mix, which raises. A Student-t margin with `ν` floored at 4 is decision 11, §13, as a later option. A zero-residual fund (status `near_constant` with zero variance) keeps a zero shock and is left out of the dependence fit. Pseudo-observations for the dependence fit: `u_{t,n} = rank(z_{t,n}) / (T_pool + 1)`. The margin type per fund is recorded (`shape.funds[].margin`: `empirical` or `zero`).

**Dependence.** A regular vine copula (R-vine) fitted on the pseudo-observations: structure by Dissmann's algorithm, pair-copula family per edge chosen by BIC from {Gaussian, Student-t, Clayton, Gumbel, Frank, Joe, BB1, BB7, each with its rotations}, truncated after tree 5 **[choice]** (on a 23- to 30-fund menu the deeper trees are close to independence and cost most of the fit time). The share of the fitted log-likelihood carried by each of the five trees is recorded (`shape.tree_loglik_share`) so the truncation level can be judged from data. Library: `pyvinecopulib` (C++ core, MIT licence; Phase 3 verifies a Python 3.12 Linux wheel and pins the version). The copula code lives in QSE (proposed module `qse.distributions.joint.copula`, a `ShockSource` factory plus the margin transforms), reviewed and merged there, then pinned here (owner decision 3).

**Simulation.** Draw `U` (`P·H` rows × `N`) from the vine with the fixed seed, map each column through its margin's quantile function to `Z` (`P × H × N`), and hand `Z` to the recursion as the shock source. Everything after that (recursion, level step, compounding, percentiles) is identical to §4.3, so the difference between the two engines is exactly the dependence model.

What the copula adds over the row bootstrap: joint bad days the history does not contain (a 2,520-row pool holds at most 126 rows in its worst 5%; the tail-dependent families extrapolate beyond them); a smoother tail for the loss-contribution measure (§5.3); and a dependence summary the owner asked for: for every pair of funds the lower-tail concordance of the simulated shocks at 5% (the probability that one fund is in its worst 5% of days given the other is; a finite-level figure, not the limit tail-dependence coefficient), stored as `shape.lower_tail_5pct` (N × N; `null` unless the tensor carries `copula`) for the validation report.

### 4.5 Level and shape: the scaling formulas

Chart moments for the selected lookback (demo spec §4.3): per fund the blended expected return `μ_{s,i}` and volatility `σ_i`; for a mix `μ_w = μ_s'w`, `σ_w = √(w'Σw)`. Daily targets invert the chart's annualization: `m_i = μ_{s,i} / 252`, `s_i = σ_i / √252`, `m_w = μ_w / 252`, `s_w = σ_w / √252`.

Step 1, per fund (level of each fund): with `R̄_n` and `sd_n` the mean and population standard deviation of fund `n` over all paths and days of the simulated panel,

```
R'_{p,t,n} = m_n + (R_{p,t,n} − R̄_n) · s_n / sd_n        (a constant fund, sd_n ≤ rounding: R' = m_n)
```

Step 2, per mix (level of the mix): `y_{p,t} = Σ_n w_n R'_{p,t,n}` has pooled mean exactly `m_w`; with `sd(y)` its pooled standard deviation,

```
y'_{p,t} = m_w + k_w (y_{p,t} − m_w),   k_w = s_w / sd(y)        (sd(y) = 0: y' = m_w)
```

`sd(y)² = w' Σ_sim w` exactly, with `Σ_sim` the pooled (`ddof = 0`) covariance of the `R'` panel over all paths and days, computed once per (fund set, engine, lookback); so `k_w` needs no pass over the paths. `k_w ≠ 1` because the simulated correlations are the shape window's and the chart's risk uses the lookback's shrunk ones. The year is `Y_p = ∏_t (1 + y'_{p,t}) − 1`; a day at or below −100% raises, as today, and no such mix enters a tensor. Implementation note: both steps are affine, so `y'` is the raw panel times the effective weights `k_w w_n s_n / sd_n` plus one constant per mix; the raw simulated panel is the only large array, and the 673 mixes of a tensor are compounded in blocks of `B` mixes over path chunks with a work buffer of at most 64 MB (`B · P · H · 8` bytes, `B ≈ 16`), never all at once (which would be 2.7 GB). Typical sits near `e^{μ_w − σ_w²/2} − 1`, and the existing check (Typical within `0.25σ` of that figure) applies to every engine.

**[choice]** Two steps rather than QSE's one-step `rescale_to_targets` on the mix series: the one-step map weights funds by their ten-year volatilities inside the mix; step 1 gives each fund the lookback's own volatility before mixing (a bond fund in a 1-year view carries the weight the chart gives it) and step 2 pins the mix's risk to the chart's. The two-step form also decomposes exactly by fund, which §5.3 needs: `y'_{p,t} = Σ_n w_n [m_n + k_w (R'_{p,t,n} − m_n)]`.

For `ew` the level is the weighted `μ_s`, `σ` and the shape is the same ten-year fit (the tensor's note says so). For `replay`, `R'` is the resampled sample row recentred per fund (`sample_{t,n} − mean_n + m_n`) and `k_w = 1`, which is what the engine does today.

## 5. Diversification measures

Three candidates, each stated with its definition, its value for a single fund, its bound, how it is computed from each engine, and whether the fixed-risk ladder program (demo spec §4.7) can optimize it.

### 5.1 Minimum-torsion ENB (today's measure; kept as a baseline)

`ENB(w) = exp(−Σ_i p_i ln p_i)`, `p_i = Λ_i b_i² / (w'Σw)`, `b = T^{−T} w` (demo spec §4.6). Single fund: not 1 (3.5 to 14.4 on the Example Portfolio, §2). Bound: `ENB ≤ N`, the menu size, not the number of funds held. Computed from `Σ` alone: identical under every engine. Optimization: non-convex; SLSQP from several starts, about 2,000 programs per lookback (most of the 4 seconds of a 23-fund build); "the most diversified mix found". The browser computes it for any `w` from the shipped torsion.

### 5.2 Diversification ratio squared, DR²

`DR(w) = (Σ_i w_i σ_i) / √(w'Σw)` (Choueifaty & Coignard 2008, *J. Portfolio Management* 35(1)); the measure is `DR²`. Single fund: exactly 1. Bound: when every pairwise correlation among the funds held is non-negative, `DR² ≤` the number of funds held (Cauchy–Schwarz: `w'Σw ≥ Σ w_i²σ_i² ≥ (Σ w_iσ_i)² / k`); `k` uncorrelated funds at inverse-volatility weights score exactly `k`. With a negative correlation it can exceed `k` (a hedged pair is less than two risks, not more); the §10 check therefore uses the correlations among the funds each mix holds, and the tensor records the menu's lowest pairwise correlation (`min_pair_correlation`) for the report. Two funds at correlation 0.95, equal weights, equal volatility: `DR² = 1.03`, which is the behaviour the finding calls for. Computed from `Σ` alone: identical under every engine; the browser computes it from the `sigma` and `cov` it already has. Optimization at fixed risk `X_j` and return floor `Y`:

```
maximize Σ_i σ_i w_i   s.t.  ‖C w‖₂ ≤ X_j,  μ_s'w ≥ Y,  1'w = 1,  min ≤ w ≤ max
```

a second-order cone program, the frontier's own program with another linear objective (cvxpy + Clarabel, DPP-parametrized, about 1 ms a solve): 48 columns × 13 floors ≈ 624 solves per lookback, each a global optimum of its program. The risk constraint binds, generically and per level, whenever `X_j` is below the risk of the floor-constrained greedy mix that maximizes `Σ σ_i w_i` (the frontier's argument, demo spec §4.5). Where it does not bind the level sits left of its column with `σ(w) < X_j`; the tensor flags it (`ladder.on_line[j][l] = false`), the builder's risk-line check (demo spec §4.11) applies only to flagged-on levels, and the page already draws every mix at its actual `(σ, μ)`. On a menu with gold, long Treasuries and emerging markets the no-floor maximizer can sit well below `σ_max`, so off-line levels may be common on the right of the map rather than rare; the report counts them. Because the objective is `Σ σ_i w_i` and not DR² itself, DR² is not monotone in `Y` by itself once a level is off its line; the demo spec's pool rule (§4.7) is kept: every program's answer joins the column's pool, and the level at floor `Y` is the pool's highest-DR² mix earning at least `Y`, so down a ladder DR² never falls and return never rises by construction, and the collapsed-column rule is unchanged. Convexity keeps a blend of two levels feasible (`σ ≤ X_j`) but not near the line, so the hop rule (midpoint blend losing more than 1% of `X_j`) stays and hops, if any, are flagged and honoured as today. Known behaviour to watch (demo spec F3): the ratio favours the least-correlated, higher-volatility funds (gold, long Treasuries, emerging markets); the caps and the return floors bound it, and the single-fund and bound checks of §10 are the test.

### 5.3 Effective number of loss contributors in bad years, ENLC

From the selected engine's paths of a mix, using the exact decomposition of §4.5. The contribution of fund `n` to path `p`'s additive year is

```
C_{p,n} = Σ_t w_n [ m_n + k_w (R'_{p,t,n} − m_n) ] = w_n [ 252 m_n + k_w (S_{p,n} − 252 m_n) ],   S_{p,n} = Σ_t R'_{p,t,n}
```

so that `Σ_n C_{p,n} = Σ_t y'_{p,t}`. `S` (`P × N`) does not depend on the mix and is computed once per (fund set, engine, lookback); a mix's contributions are then a `P × N` product, and only the bad-year set below needs the mix's own paths, which the range computation already produces.

The mix's bad years are the `⌈αP⌉ = 100` paths with the lowest compounded return `Y_p`, `α = 5%` **[choice]** (the worst 100 of 2,000, the tail the Bad year sits in; the conditional average over them is the mix's expected shortfall at 5%). Fund `n`'s loss contribution is `ℓ_n = −mean_{p ∈ bad} C_{p,n}`, positive when the fund loses in the mix's bad years. Shares over the losers only, `s_n = max(ℓ_n, 0) / Σ_k max(ℓ_k, 0)`, and

```
ENLC(w) = exp(−Σ_n s_n ln s_n)        (0 ln 0 = 0)
```

Rule for negative contributions: a fund with `ℓ_n < 0` gained in the mix's bad years; it is a hedge, takes share 0, and is listed by name ("gained in this mix's bad years: TSP G"). Its gain already shows in the Bad-year figure; the count measures how many separate sources the losses come from. A fund with `w_n = 0` has `C = 0`. If no fund loses (`Σ max(ℓ, 0) = 0`: a cash-only mix, or TSP G or SGOV held alone, whose worst years are still gains), ENLC is undefined: the tensor stores `null` and the page says "no losses to share out" and falls back to the covariance measure for the word. The three largest shares, descending, with their fund ids are stored as `top`. Single fund: exactly 1 whenever its bad years lose, `null` otherwise. Bound: the number of funds with a positive loss contribution, at most the number held. Engine-dependent by construction: it is the only candidate that sees joint tails, which is what the owner wants measured; under `copula` it reflects fitted tail dependence, under `garch` the history's joint residual days, under `replay` the lookback's joint days. **[choice]** exp(entropy) rather than `1 / Σ s²` so the three measures are all Hill numbers of order 1 and compare like for like. Monte Carlo error: 100 tail paths give noisy shares; the shared draw makes neighbouring mixes comparable (their bad-year sets overlap almost entirely) and the seed-stability test of §10 bounds the error on the figure itself. Cost: negligible beyond the ranges (the bad-year set comes from the mix's compounded years, the rest is a `P × N` product). Optimization: not tractable directly. The function is sampled and piecewise (the bad-year set changes discretely with `w`); selecting a candidate's bad set needs its `2,000 × 252` series, about 5 ms, and 2,000 programs with numerical gradients in 23 dimensions would run for hours. It is measured on optimized mixes, never optimized, in this spec; re-ranking a pool of optimized candidates by ENLC (a few thousand evaluations, 10 to 20 s per lookback) is the later option in decision 2, §13.

### 5.4 Side by side

| | ENB (min. torsion) | DR² | ENLC |
|---|---|---|---|
| Single fund | 3.5 to 14.4 on the Example Portfolio | 1 | 1 |
| Bound | menu size `N` | funds held (correlations ≥ 0) | funds held that lose |
| Sees tail dependence | no | no | yes |
| Differs by engine | no | no | yes |
| Ladder program | non-convex, SLSQP, ≈ 2,000 solves, "found" | convex SOCP, ≈ 624 solves, global | not optimizable; measured |
| Browser computes for any `w` | yes (torsion shipped) | yes (`sigma`, `cov`) | no: tensor and `/v1/range` |
| Cost per lookback | most of the 4 s | ≈ 1 s | negligible beyond the ranges |

### 5.5 Recommendation

1. **Both ladders are built and the backtest picks the optimized measure** (owner, 2026-10-14: "willing to try it, if it *actually* produces a better optimization"). Phase 2 builds the ENB and the DR² ladders side by side (`LADDER_MEASURE` selects which one the page shows) and the validation report compares them on the same rolling backtest (§10 item 7). DR² becomes the default only if it wins there; otherwise ENB stays and DR² remains selectable. The case for DR² on paper: it answers the finding (a single fund is one; a mix of near-duplicates is barely more), it is convex (a global optimum per level, no hops, a third of the solver time), it is consistent with the chart's own covariance and risk axis, and the browser can compute it for any mix. A build-time constant `LADDER_MEASURE` (`"dr2"` or `"enb"`) selects the objective so both can be built and compared during validation; the tensor records which (`ladder.measure`). The word (Good / Average / Fair / Poor) keeps its cut points on `q = (measure − 1) / (ref − 1)` **[choice]**, with `ref` the highest value of the optimized measure over every ladder level ("highest found on this menu"): DR² and ENLC start at 1 for a single fund, which should read Poor, not the Fair that `measure / ref` would give on a correlated menu where `ref` is 3 or 4 (decision 15, §13 is whether the cut points themselves need recalibrating). Note that `refs.enb` under `LADDER_MEASURE = "dr2"` is the highest ENB over DR²-ladder levels, a lower number than today's `enb_ref`; the reference moves with the ladder it is read from.
2. **ENB stays computed** at every level (`ladder.enb`) and remains selectable (`m=enb`) for comparison; it is shown on the page only when selected.
3. **ENLC is the figure that tells the cross-dependence in bad years.** It is computed under every engine for every ladder level, the entered mix and, through `/v1/range`, the selected mix, and shown with the engine's name in the result strip's details and on the mix cards as a word and a share of the best on the menu, never as a count (§6.1): "Losses in this mix's worst years: spread (78% of the best spread on this menu); TSP G gained." It is not the map or the word in this spec. Promoting it to the headline for the `copula` engine (map, word and Optimized point from ENLC-re-ranked ladders per engine) is decision 2, §13; it costs a per-engine ladder block in the tensor and 10 to 20 s per lookback.

Headline per engine, as proposed: `replay`, `garch`, `copula` all show the DR² word and map; the simulation engines add the ENLC figure under details. The cross-dependence the owner wants is then on the page from Phase 2 under both `replay` and `garch`, and the copula sharpens it in Phase 3 without another page change.

## 6. Settings UI, URL and what changes on screen

**Two controls** in the Settings section, after "Years of history" **[choice]** (one control would make 3 × 3 combinations unreadable, and the engine question is a visitor's while the measure question is the owner's during validation):

- **Simulation** (radio group, `data-testid="engine-{id}"`): "History replay (default): replays runs of real days from this history window" · "Volatility model: fitted volatility clustering and fat tails; funds' shocks replayed together from up to ten years" · "Copula: fitted dependence between funds, including joint bad days the history does not contain". An engine the tensor does not carry is disabled with the tensor's reason ("not computed for this menu", "not enough shared history for the volatility model").
- **Diversification measure** (radio group, `data-testid="measure-{id}"`, shown only while details are on in this phase; decision 3, §13): "Diversification ratio" · "Minimum torsion (the current measure)" · "Losses in bad years (from the simulation; measured, not optimized)".

Defaults: `replay` and the build's `LADDER_MEASURE`. URL (demo spec §8.1): `e=replay|garch|copula` and `m=dr2|enb|enlc`, both omitted at their defaults, written in the canonical order after `x`; an absent `m` means the loaded tensor's `ladder.measure` (the page learns it from the tensor, not the address); the Worker's share validator accepts the two keys; a mailed link opens the engine it was sent in. No `localStorage`: the address is the state, as for the lookback.

**When the engine changes:** the risk-slider readouts (the frontier mix's Bad and Typical year), the result strip's three figures and bar, the mix cards' ranges, the slider's left end (`s_safe` is per engine, §7; the position `s`, URL `r`, is clamped into the new domain), the Method line and the ENLC figure. Nothing in the chart moves. **[choice]** The bar's fixed scale spans every engine the loaded tensors carry, so switching engines moves the band, not the scale. **When the measure changes** between `dr2` and `enb`: the map's colours and legend, the word, the details' measure line and `ref`; the mixes themselves do not move (one ladder per tensor). Under `enlc` the map, its legend and the Optimized point stay on the optimized measure (raster cells carry no ENLC, §7) and the legend says "map: diversification ratio"; the word and the figure use the selected mix's ENLC under the selected engine, from the tensor at a level and from `/v1/range` elsewhere (the nearer level's value until it answers), with `q = ENLC / refs.enlc[engine]`. **[choice]** No rebuild on either switch: everything is in the tensor.

**Which engine produced the numbers.** A small muted tag beside the strip's "Selected mix" label and beside the risk slider's readouts: "History replay" / "Volatility model" / "Copula" (`data-testid="engine-tag"`), always visible, never a headline. Details add one technical line per engine (copy table). The textbook bell-curve figure stays in details only, unchanged, labelled as the same for every engine.

Copy (plain / behind details):

| Where | Plain | Technical |
|---|---|---|
| Engine tag | "History replay" · "Volatility model" · "Copula" | — |
| Method line, `replay` | as today | as today (demo spec §3.6) |
| Method line, `garch` | "Fitted volatility and fat tails per fund; funds' shocks replayed together from up to ten years; centred and scaled to this view's expected return and risk" | "GARCH(1,1)-t per fund on up to 2,520 days, joint filtered historical simulation (whole residual rows), long-run variance start, 2,000 × 252-day paths; mean and volatility rescaled to the lookback's `μ`, `σ`; constant volatility for: {funds}" |
| Method line, `copula` | "As the volatility model, with the funds' co-movement fitted, including joint bad days beyond those in the history" | "R-vine copula on the residuals' pseudo-observations (BIC family selection, truncated at tree 5), Student-t margins with the fitted `ν` (empirical where `ν < 2.5`); shocks drawn from the copula into the same GARCH recursion" |
| Measure, `dr2` | "How spread out the risk is" (legend unchanged); details: "N% of the best spread found on this menu" | "Diversification ratio squared: (weighted average volatility ÷ portfolio volatility)²; 1 for a single fund; highest found on this menu: M. A score, not a count of funds or stocks." |
| Measure, `enb` | as today | as today |
| Measure, `enlc` | "Losses in this mix's worst years: {word} (N% of the best spread on this menu)" · "gained in this mix's bad years: {funds}" · "no losses to share out" | "Effective number of loss contributors: exp(entropy) of each fund's share of the mix's expected shortfall at 5% over 2,000 simulated years ({engine}); hedges (negative contributions) take share 0. A score, not a count of funds or stocks." |
| Fallback funds | "Volatility held constant: TSP G, SGOV" | "near-constant (daily sd < 0.03%) or fewer than 252 days" |

Never in default copy: "GARCH", "vine", "residual", "expected shortfall", "entropy"; "Copula" appears only as the control's label and the engine tag.

### 6.1 No measure reads as a number of holdings

Owner direction (2026-10-14): whichever measure is used, a visitor must not read the number as "the equivalent number of stocks or investments". So, for ENB, DR² and ENLC alike:

- The default view shows only the word (Good / Average / Fair / Poor) and the map.
- Details show a score as a share of the best found on this menu ("82% of the best spread found on this menu"), never "the equivalent of N" anything. The demo spec's current details sentence ("spreads risk over the equivalent of N independent bets") is replaced by this in Phase 2, for ENB too.
- The raw value appears only in the technical line, named by its measure ("diversification ratio squared 3.4", "effective number of bets 11.8"), followed by "A score, not a count of funds or stocks."
- Mix cards and hover text follow the same rule. A test scans the served copy for "equivalent of" and "independent bets" outside the technical lines.

### 6.2 Menu size by access tier: 30 public, 100 admin

Owner direction (2026-10-14): design for 100 funds now, so a paid tier can be added later, and let the owner use 100 as admin today.

- The menu limit is a per-tier setting, not a constant: `PS_MENU_MAX_PUBLIC=30`, `PS_MENU_MAX_ADMIN=100`. The API and the Worker both enforce the caller's tier; a later paid tier is one more setting.
- **Built 2026-10-15** (owner decision "I am good with 30 and 100"): the API settings, the Worker's admin link, cookie and `GET /api/tier`, and the page's limit are specified in the demo spec §3.3 and §6 (menu limit by access tier); the runbook says how the owner turns admin on and how to rotate the secret. Menus over 30 funds are built on demand as before (the nightly builds presets only); the wait notice and the 100-fund engine settings above are not built yet.
- **Admin today, without accounts:** a separate admin secret (`PS_ADMIN_SECRET`, its own value, never the preview gate's), opened once as `?admin=<secret>`; the Worker sets an HttpOnly, Secure, SameSite=Strict cookie and forwards `x-ps-tier: admin` to the API only when the cookie verifies (an HMAC of the secret, like the preview gate). The API trusts the header only from the Worker (same mechanism as `x-ps-gate`). When accounts exist, the account's tier replaces the cookie.
- **Cost, measured 2026-10-14** (one lookback, ENB ladders, synthetic factor-model menus, 2 CPUs under load average 6 to 7): 23 funds 18 s, 40 funds 40 s, 60 funds 76 s, 100 funds 230 s (about N^1.5). A quiet machine is about 4 times faster (the 23-fund fixture builds in 3.7 s). **Measured 2026-10-15 with the risk columns on worker processes** (demo spec §4.12; `scripts/bench_build.py`, six-factor synthetic menus, seed 7, one 5y lookback, each run pinned to as many cores as workers, load average 6 to 14): 23 funds 24 / 21 / 10.5 / 9.3 s on 1 / 2 / 4 / 8 workers, 60 funds 74 / 39 / 27 / 19 s, 100 funds 184 / 142 / 80 / 50 s. KS-001's API and nightly containers now have 4 CPUs, so a build there uses 4 workers.
- Consequences: menus over 30 funds are built on demand only, never in the nightly; the page's "Give us a moment" notice shows the expected wait for large menus; at 100 funds the ENB peak search uses extra random starts (local optima grow with N), and the copula is truncated at tree 3 (§9 fallback 2). A paid tier, when it comes, is capped at 50 funds unless DR² ladders (convex) become the default, which should make 100 funds fast; Phase 2 measures DR² at 100 funds and records it here.

## 7. Tensor, model artifacts and API

**Versions.** `ENGINE_VERSION` `0.3.0` (Phase 1), `0.4.0` (Phase 2), `0.5.0` (Phase 3); `schema` `3` from Phase 1 and incremented again only when a required field changes. The generation id carries the engine version, so the first nightly after each deploy publishes a new generation; until it does, custom builds answer `engine_version_mismatch` (runbook rule, unchanged). The universe hash and the tensor key are unchanged: engines live inside the tensor.

**Tensor changes** (everything else as demo spec §7):

```json
"engines": {"replay": {"status": "ready", "method": {...as range_method today...}},
            "garch":  {"status": "ready"|"unavailable", "reason": null|str,
                       "method": {"name": "garch_t_fhs", "paths": 2000, "horizon_days": 252, "seed": 20261013,
                                  "start": "long_run", "shape_rows": 2520, "qse": "37cc6932f8", "arch": "8.0.0"}},
            "copula": {"status": ..., "method": {"name": "vine_copula_fhs", "families": [...], "truncation": 5,
                                                 "margins": "empirical", "pyvinecopulib": "x.y.z", ...}}},
"range_default": "replay",
"frontier": {"x", "y", "w", "s_safe": int, "range": {...default engine...},
             "ranges": {"replay": {"s_safe": int, "bad": [48], "typical": [48], "good": [48]}, "garch": {...}, "copula": {...}}},
"ladder": {"y", "w", "hop", "collapsed", "t_balanced", ..., "range": {...default engine...},
           "measure": "dr2"|"enb", "z": [[14]...48] (the optimized measure), "dr2": [[14]...48], "enb": [[14]...48],
           "on_line": [[14]...48],
           "ranges": {engine: {"bad": [[14]...48], "typical": ..., "good": ...}},
           "loss_sources": {engine: {"n_eff": [[14]...48] (null where undefined),
                                     "top": [[[{"id", "share"} × 3]...14]...48], "hedges": [[[ids]...14]...48]}}},
"grid": {..., "z": the optimized measure, "dr2": [[32]...48], "enb": [[32]...48]},
"entered": {"w", "set_aside", "range": {...}, "ranges": {engine: {...}}, "loss_sources": {engine: {...}}},
"refs": {"dr2": float, "enb": float, "enlc": {engine: float|null}},   "enb_ref": float (kept, equals refs.enb),
"min_pair_correlation": float,
"shape": {"rows": 2520, "start": str, "end": str, "sample_sha256": str, "pool_rows": int,
          "funds": [{"id", "status", "rows", "mu", "omega", "alpha", "beta", "nu", "long_run_sigma_annual", "margin": "empirical"|"zero"|null}],
          "outliers": [{"id", "date", "z"}], "lower_tail_5pct": [[N]...N]|null, "tree_loglik_share": [5]|null},
"range_method": {...kept: the default engine's method, for older readers...}
```

`frontier.range`, `ladder.range`, `entered.range` and `range_method` keep their names and hold the default engine's figures; `ladder.z` and `grid.z` hold the optimized measure; `enb_ref` keeps its meaning (ENB's reference) and the page's word and map read `refs[ladder.measure]` from Phase 2. With `LADDER_MEASURE = "enb"` every kept field means exactly what it does today, so today's readers keep working while the page learns the new blocks. The per-engine `ranges` blocks carry `bad`, `typical`, `good` only: the normal range is engine-independent and lives in the kept `range` blocks. `loss_sources.top` is the three largest shares (§5.3). `min_pair_correlation` is a lookback quantity (the chart's `cov`) and sits at the top level, not under `shape`. Raster cells (`grid`) carry the two covariance measures only; ENLC is never computed for raster cells (they are blends drawn for colour, and the map does not colour by ENLC in this spec). Size: about +300 KB raw for 23 funds with two simulation engines (two range blocks of 70 KB, loss sources about 75 KB an engine with `top` and `hedges`, the rest small): about 1.05 MB raw, 400 KB gzip.

**Model artifacts.** The fit is per (included fund set, `D_G`, engine), not per lookback or per cap policy, and is stored once under the generation, immutable, pruned with it, keyed by the shape digest (which identifies the fund set and its data): `models/{G}/{shape_sha256[:16]}/garch.json` (parameters, statuses, pool digest) with `pool.npy` (the re-standardized residual pool, `T_pool × N` float64, under 1 MB); `.../copula.json` (the vine as `pyvinecopulib` serializes it, plus the margins) with `copula_shocks.npy` (the shared shock tensor `Z` as float32, 46 MB at 23 funds and 61 MB at 30, stored because the vine draw costs seconds and `/v1/range` must not pay it). The builder checks the key before fitting, so a preset's lookbacks share one fit when their fund sets agree (the 1-year view can admit a younger fund, so a preset may need up to one fit per distinct fund set), and the API's one-lookback-at-a-time queue does too. Simulated panels are never stored; `garch` is re-simulated from the artifact and the shared draw, `copula` from the stored shocks, both in about 0.2 s.

**`POST /v1/range`.** Body gains `"engine": "replay"|"garch"|"copula"` (optional; default `range_default`). Response gains `"engine"` and `"loss_sources": {"n_eff": float|null, "top": [...], "hedges": [...]}` (the whole block `null` until Phase 2). Refusals: `422` for an unknown engine id; `409 range_unavailable` when the tensor does not carry the engine, the artifact is missing, the rebuilt shape panel's digest differs from `shape.sample_sha256`, or the lookback sample's digest differs (as today). The service loads the artifact into the cache directory (the first request for a copula tensor also fetches its 46 to 61 MB shock file from R2; the page shows node figures until the answer arrives, as it does now), re-simulates in about 0.2 s, and keeps the two most recently used simulated panels in memory as float32 (at most 2 × 61 MB) keyed by (shape digest, engine); the lookback samples cache of 8 stays. `GET /v1/health` adds `"engines": [...]` enabled on the host. The Worker forwards `POST /api/range` unchanged.

**Precompute or on demand.** Env `PS_ENGINES` (default `replay,garch` from Phase 1; `replay,garch,copula` once Phase 3 is measured) names the engines every build computes; `PS_ENGINES_CUSTOM` (default: `PS_ENGINES` without `copula` until measured; decision 4, §13) applies to custom menus. An engine a tensor does not carry is `unavailable` with the reason "not computed for custom menus" and the control says so; nothing is computed on demand outside `/v1/range`.

## 8. Data dependencies

- The shape fit needs up to ten years of daily total returns per fund. For every served fund the store already has them: the seed's `tr_index` is the lake's back-adjusted history through `2026-03-27` and the provider's tail is spliced onto it from there (demo spec §5.1, §5.4); a seeded fund is served only after its tail refresh. So the volatility model and the copula do not wait for the lake repair.
- The lake's `adj_close` stops being adjusted after `2026-03-27` (`docs/plans/2026-10-13-qse-lake-total-return-repair-prompt.md`). PortfolioSight reads the lake once, as a seed, and never at runtime; the repair matters only for a future re-seed and for tier-3 symbols still `pending`. When it lands, the re-seed is a data step (demo spec §5.4) with no engine change; the shape digests change and the next generation's figures move slightly, which the validation report records.
- A menu with a `pending` or set-aside fund excludes it from the window as today; the engines see only included funds.
- The splice guard (§4.3) catches a large unadjusted corporate action at the splice; a missing small dividend passes it, and the provider cross-check of demo spec §4.1 is the defence there.
- `qse` at the pinned commit is installed with `--no-deps` (QSE's own dependency list carries torch and xgboost, which PortfolioSight must not pull). `pip` cannot install one dependency without its dependencies, so `qse` is not in `pyproject.toml`'s list: it is one pinned line (`pip install --no-deps "qse @ git+https://github.com/automateintelligence/quant-scenario-engine@<commit>"`) in the Dockerfile and in the README's setup commands, and `tests/test_dependencies.py` grows a test that the pinned commit is installed and that importing `qse.distributions.joint` pulls in nothing beyond numpy, scipy, pandas, statsmodels and `arch`. PortfolioSight declares what it uses itself: `arch` (pinned exact; `8.0.0` at writing), `statsmodels` (arch's dependency), later `pyvinecopulib`.

## 9. Performance budget and fallbacks

Target (unchanged): at most 30 s per 23-fund (menu, lookback) build on KS-001's container (4 vCPUs since 2026-10-15, 2 before); nightly presets (2 menus × 6 lookbacks) at most 10 min; `/v1/range` under 1 s for `replay` and `garch`. Estimates; Phase 1 and Phase 3 measure them on KS-001 and record them in the runbook.

| Work | Once per | Today | Estimate after |
|---|---|---|---|
| GARCH-t panel fit, 23 funds × 2,520 rows (`arch`) | fund set and generation | — | ≈ 7 s (≈ 0.3 s a fund) |
| FHS simulation, 2,000 × 252 × 23 | fund set, generation, engine | — | 0.2 s (QSE, 2 CPUs) |
| Vine fit, 23 funds, truncated at tree 5 | fund set and generation | — | 10 to 60 s (estimate) |
| Copula draw, 504,000 rows × 23 | fund set, generation | — | 5 to 20 s (estimate) |
| Mix series for 673 mixes (QSE: 200 mixes in 0.35 s) + level step + compounding + percentiles | lookback and engine | — | ≈ 2 s |
| ENLC (bad-set selection from the ranges' own years, then a `P × N` product) | lookback and engine | — | < 0.1 s |
| Ladders | lookback | ENB, ≈ 2,000 SLSQP, most of the 4 s | DR², 624 SOCPs, ≈ 1 s |
| 23-fund lookback, `replay,garch`, Phase 1 (ENB ladders) | lookback | ≈ 4 s | ≈ 7 s, plus the fit once per fund set |
| The same after Phase 2 (DR² ladders, ENLC) | lookback | | ≈ 6 s |
| With `copula` (Phase 3) | lookback | | ≈ 9 s, plus fit and draw once per fund set |
| Nightly, both presets, three engines | night | ≈ 1 min | ≈ 5 min |
| Memory: simulated panel float64 (30 funds) plus the mix work buffer (§4.5, blocks of 16 mixes) | | | 121 MB + 64 MB; QSE measured 126 MB peak for the panel |
| Copula shock artifact (float32) stored and cached | fund set, generation | — | 46 MB at 23 funds, 61 MB at 30 |

Fallbacks, named now so a phase applies one and re-measures rather than inventing: (1) float32 simulated panel (half the memory, QSE measured 0.09 to 0.12 s; percentiles move at the fourth decimal); (2) copula truncation 5 → 3 and the family set reduced to {Gaussian, Student-t, Clayton, Gumbel} (the BB1 and BB7 inverse h-functions are numerical, so this fallback speeds the draw as much as the fit); (3) `PS_ENGINES_CUSTOM` without `copula`; (4) ENLC on ladder levels and the entered mix only (it already is; never raster cells). Not a fallback: fewer than 2,000 paths, because the 2.5th percentile's Monte Carlo error (about `0.06σ` at 2,000) grows as `1/√P`.

## 10. Validation plan: when does a new engine become the default?

All of it runs on the laptop against the backup mirror (`LocalStore` over `/mnt/d/portfoliosight-data`), with no provider calls, by `scripts/backtest_ranges.py`, and is written up in `docs/reviews/2026-10-xx_engine-validation.md` with its tables. The owner reads it and decides (§13, decision 12).

1. **Rolling out-of-sample coverage.** Menus: Example Portfolio (23 funds) and TSP (5). Origins: the last trading day of each quarter from 2015-12-31 to 2025-09-30 (40 origins; the realized year of the last ends by 2026-09-30). At each origin the engine builds with `D_G` = origin, applying its own window and inclusion rules as they would have applied then (the shape window is what existed, down to the 252-row minimum). Mixes: frontier nodes at `s_safe`, the domain midpoint and `s_max`; the Optimized point of those columns; the entered mix; equal weight; every single fund. Lookbacks `5y` (the default) and `1y` (where level and shape differ most). For each (origin, mix, engine): predicted Bad / Typical / Good; realized one-year total return over the next 252 trading days. Metrics: coverage of `[Bad, Good]` (target 95%) and the breach count below Bad (target 2.5%), reported descriptively for the 40 quarterly origins (they overlap and cluster) and for the 10 non-overlapping year-end origins, with the note that `Binomial(10, 0.025)` puts 90% of its mass on 0 or 1 breaches, so a count cannot discriminate engines on its own; pinball loss at 2.5 / 50 / 97.5, summed over the mixes of an origin and paired engine against engine origin by origin; a Kolmogorov–Smirnov statistic of the PIT (the realized return's percentile under the engine's simulated distribution) on the 10 non-overlapping origins pooled over mixes, as a diagnostic. Because the level (`μ_s`, `σ`) is common to every engine, differences between engines are shape differences, while the absolute coverage also tests the menu-beta level. Honesty note: ten independent years is a weak test; the report says what it can and cannot distinguish, and the mixes of one origin are not independent evidence.
2. **Engine comparison on the live menus** (current `D_G`): the Bad-year figures of the three engines at every frontier node and Optimized point of both menus, side by side; and the percentile at which each stress window's buy-and-hold loss (the three windows of the demo spec §4.10) falls in each engine's one-year distribution for the Optimized point at `s_safe`, the midpoint and `s_max`. A window shorter than a year is a lower bound on how bad that year could have been, and the report says so. An engine that places the 2008 outcome of an equity-heavy mix far below its 0.5th percentile is too thin in the tail; one that places 2022's loss of a 60/40 mix above its 5th percentile is too fat. Both the lookback and the ten-year shape window end after 2016, so the 2008 placement tests extrapolation beyond the fitted history, which is the point.
3. **Single-fund and bound checks of every measure**, both menus, every lookback: single-fund mixes give `DR² = 1` (1e-9) and `ENLC = 1` exactly for every fund whose bad years lose (`null` with the "no losses to share out" reason otherwise, when the word falls back to DR², which is 1), and ENB is reported as the finding; every ladder level's `DR²` is at most the number of funds it holds (`w > 1e-6`, the §4.11 tolerance; the > 0.5% count is reported beside it) whenever the correlations among those funds are all ≥ 0, and every level's `ENLC` is at most the funds it holds.
4. **Seed stability.** The same build with five seeds (`20261013` to `20261017`): across seeds, for every frontier node and Optimized point, the standard deviation of Bad is at most `0.10 · σ_w` (the 2.5th percentile's Monte Carlo error is about `0.06 σ_w` at 2,000 paths, §9, so this allows for fatter simulated tails) and the standard deviation of ENLC is at most 0.3; these are estimates of the error, not bounds. If the ENLC half fails, `α` moves to 10% (decision 5) and the test is rerun.
5. **Invariants and determinism** (unit tests): every engine's Bad < Typical < Good; Typical within `0.25σ` of `e^{μ − σ²/2} − 1`; level 0's range is the node's; identical tensors from identical inputs; fallbacks exercised on a TSP-G-like constant series, a 200-row series and a non-stationary synthetic series; the splice guard on a fixture with a fabricated 30% ex-date drop.
7. **Which measure optimizes better: ENB ladders against DR² ladders.** Same origins, menus and lookbacks as item 1. For the Optimized point and the peak of each column under each measure: realized one-year volatility against the predicted risk (absolute error, and the share of years realized risk exceeded prediction by more than a quarter); the realized loss in each stress window and in the worst realized year; the realized loss concentration (ENLC computed on the realized bad days, the same definition as §5.3); the realized return given up against the frontier mix of the same column; and stability (the weight distance between the same column's mixes at consecutive origins, and between lookbacks at one origin). DR² becomes the default measure when it is no worse on realized risk and stress losses and better on at least two of concentration, return given up and stability, on both menus; a tie keeps ENB. The report shows a table per menu and a one-paragraph verdict.
8. **Decision rule proposed to the owner.** An engine may become the default when, on both menus and both lookbacks tested: its paired pinball loss at 2.5% (summed over mixes) is lower than `replay`'s in at least 8 of the 10 non-overlapping years (a sign test at about 5%) and its total pinball loss at the 50th and 97.5th percentiles is no worse; its breach count on the 10 years is 0 or 1 where `replay`'s is not better; it places no stress outcome (item 2) below its 0.5th percentile where `replay` did not; items 3 to 5 pass; and the owner's own check of the page (Expectations) passes. Ten years can only show large differences; a tie on evidence leaves the default where it is unless the owner decides on the method's merits. `copula` is judged against `garch` the same way. The default switch itself is one constant (`range_default`) and one engine-version bump.

## 11. Phases

Each phase: its own branch and pull request, TDD, the gates for what it touches (`ruff`, `pyright`, `pytest --cov`; `npm run lint && npm run typecheck && npm test` when `web/` changes), docs straight to `main`. The done-gate tests under `assertions/` are ordinary tests in this pre-production period: a phase updates or re-freezes those its change makes false and says so in its PR (owner direction 2026-10-13).

**Phase 0: tag the deployed dashboard.** Before any engine code. From the laptop: read the deployed commit from KS-001 (`deploy/.env` `GIT_SHA` over ssh; it is the argument of the last `scripts/deploy_ks001.sh`), the running image id (`docker image inspect portfoliosight:<sha> --format '{{.Id}}'` over ssh), the live Worker version (`npx wrangler versions list` in `web/`, the deployed version id), and the generation in `meta/current.json`. Create the annotated tag `dashboard-bootstrap-2026-10-14` on that commit with those four facts and the date in its message, push it to `github`, and record the same four lines in the runbook under a "Rollback points" heading with the three rollback commands: `make deploy-backend SHA=<sha>`, `npx wrangler rollback <version-id>` (from `web/`), and the pointer switch of `meta/current.json` back to the tagged generation. The nightly prunes generations older than the previous one, so the tagged generation would be gone two nights after the first `0.3.0` nightly; to keep the rollback possible, the nightly keeps any generation named in `meta/pinned.json`. That is a one-line change to the pruning, made in its own small pull request and deployed right after the tag; it touches neither the page nor the tensor, so the tagged commit, Worker version and image stay the rollback points (the alternative is decision 13, §13). Done when: `git tag -n9 dashboard-bootstrap-2026-10-14` shows all four facts, `git ls-remote github` lists the tag, the runbook has the section, and `meta/pinned.json` names the generation.

**Phase 1: Volatility model behind the setting** (`feature/engine-garch`). Deliver: `qse` pinned at the PR #164 head (or its merge commit) by the `--no-deps` line in the Dockerfile and the README (§8), `arch` and `statsmodels` pinned in `pyproject.toml`; `engine/shape.py` (panel, fit, pool, splice guard, digest), `engine/ranges.py` grown to `one_year_ranges(model, weights, engine)` with the `garch` model and the two-step level scaling; model artifacts in the store; `engines`, `frontier.ranges`, `ladder.ranges`, `entered.ranges`, `shape` in the tensor and schema 3; `/v1/range` with `engine`; `PS_ENGINES` and `PS_ENGINES_CUSTOM`; the Settings "Simulation" control, `e=` in the URL and the share validator, the engine tag, the per-engine `s_safe`, the Method lines; the validation script and the first report (items 1, 2 and 5 of §10 and the Bad-year half of item 4, for `replay` and `garch`). Done when: the control switches every range on the page with no request; `/v1/range` answers the `garch` engine for an interpolated mix in under 1 s on KS-001 after the first request for a tensor; the 23-fund lookback builds in at most 30 s on KS-001 with `replay,garch`; determinism and fallback tests pass; the report is in `docs/reviews/`; `range_default` is still `replay`.

**Phase 2: Diversification measures** (`feature/engine-measures`). Deliver: DR² and its SOCP ladders behind `LADDER_MEASURE` (default `enb`; both ladders built; `dr2` becomes the default only if it wins §10 item 7); `ladder.measure`, `ladder.dr2`, `ladder.enb`, `ladder.on_line`, `grid.dr2`, `grid.enb`, `refs`; ENLC under every engine for ladder levels, the entered mix and `/v1/range` (`loss_sources`); the "Diversification measure" control (details-only), `m=` in the URL; the single-fund and bound tests and the ENLC half of the seed-stability test (§10 items 3, 4); the measures section of the validation report (both menus: single-fund values, bound checks, the map's before/after screenshots for the owner). Done when: the §10 item 7 comparison is in the report with its verdict; the copy passes the §6.1 scan; single-fund mixes score 1 on DR² on both menus and 1 on ENLC wherever their bad years lose; every DR² ladder is monotone in DR² and in return, every level is on its line or flagged, and hops, if any, are flagged and honoured; the ENLC figure and the hedge list appear in details for the selected mix under `garch` and `replay`; build time within budget.

**Phase 3: Copula** (`feature/engine-copula`; QSE first). Deliver: in QSE, `qse.distributions.joint.copula` (margins, vine fit, `ShockSource` factory, serialization) with its tests and a Codex review, merged by the owner; here, `pyvinecopulib` pinned, the `copula` engine, its artifact and stored shocks, `shape.lower_tail_5pct` and `shape.tree_loglik_share`, the control's third option enabled, `PS_ENGINES` with `copula` for presets, the copula section of the validation report (items 1, 2, 4 of §10 for `copula` against `garch`). Done when: the copula engine's figures appear on the page for both presets; the nightly with three engines finishes in at most 10 min on KS-001; `/v1/range` answers `copula` within 10 s and the page shows node figures meanwhile; the report is in `docs/reviews/`.

Default switch (`range_default`, and the ENLC headline if chosen): a separate, small change after the owner's reading of the report; not part of any phase above.

## 12. Risks

- **The fit library.** `arch` fits can land on boundary values (`α + β` near 1, `ν` near 2) or fail to converge on short or odd series; the fallback is constant volatility, flagged, never silent. `arch` is pinned exactly because its optimizer's results decide the tensor's bytes.
- **Short overlap pools.** A menu holding a young fund has a pool as short as the window; joint tails are then poorly identified and the copula fit is unstable. The tensor states the pool length; the details show it; the report checks the Example Portfolio's and TSP's pools (both long).
- **Level and shape from different regimes, by design.** A 1-year view takes a fund's level from a calm year and its shape from ten years including 2020 and 2022. That is the owner's intent (the shape is the fund's character); the bar and the readouts will be wider than `replay`'s in calm years, and the report shows by how much.
- **DR² preferences.** The ratio rewards the least-correlated higher-volatility funds; with caps and return floors it stays within the demo's limits, and F3 (one fund dominating) is checked by the owner on the page.
- **ENLC noise.** 100 tail paths; the seed-stability test estimates it; if it fails, `α` goes to 10%.
- **Copula cost and library.** The vine fit at 23 to 30 funds may take a minute; the truncation and family fallbacks are named; `pyvinecopulib`'s wheel and licence are verified before Phase 3 starts.
- **Tensor growth** (about +40%) and **KS-001 memory** (a 121 MB panel plus a 64 MB work buffer inside the 1,536 MB limit; two float32 panels in the API).
- **QSE pin.** PR #164 is open; the pin is a branch commit until the owner merges, then the merge commit. Its CI did not run (billing); its focused tests ran locally. Phase 1 runs QSE's `tests/unit/distributions` in PortfolioSight's environment once before pinning.
- **Rollback window.** Without `meta/pinned.json` the tagged generation is pruned on the second night after the first 0.3.0 nightly; Phase 0 adds the pin.
- **Gate churn.** A-PS-17, 18, 19, 21, 24, 34, 45 and the `tensorFacts` helper read `ladder.z`, `enb_ref`, `frontier.s_safe` and `range_method`; the kept names limit the churn, and each phase lists the tests it changed.

## 13. Decisions

Recorded 2026-10-14. Items 1 and 16 are the owner's; the rest are technical and were decided by the coordinating session on the recommended option (owner direction: decide in-the-weeds choices rather than ask). The owner may override any of them.

1. **The optimized measure** (owner): build both ladders; the backtest of §10 item 7 decides; ENB stays the default until DR² wins there.
2. **ENLC's place:** a details figure under every engine for Phases 2 and 3, not the headline. Promoting it for `copula` is revisited after the Phase 3 report.
3. **Diversification measure control:** details-only.
4. **Engines precomputed:** nightly presets `replay,garch` from Phase 1 and `replay,garch,copula` from Phase 3; custom menus without `copula` until measured.
5. **ENLC tail level:** 5%, moving to 10% only if the seed-stability test fails (§10 item 4).
6. **ENLC definition:** additive contributions over the worst 5% of compounded years, hedges at share 0, exp(entropy).
7. **Replay's volatility:** unchanged.
8. **Shape window:** up to ten years, the longest held per fund, pool at least 126 rows.
9. **`s_safe` follows the engine.**
10. **Result bar scale:** spans every engine carried.
11. **Copula:** `qse.distributions.joint.copula` with `pyvinecopulib`, empirical margins, truncation at tree 5 (tree 3 above 30 funds, §6.2). Coordinated with the QSE session before any QSE change.
12. **Default-switch rule:** §10 item 8 as written; `copula` must beat `garch`.
13. **Rollback retention:** `meta/pinned.json`.
14. **Simulated panel precision:** float64 in builds; float32 in the API's in-memory panels and stored copula shocks.
15. **Word cut points:** Good ≥ 0.75, Average ≥ 0.50, Fair ≥ 0.30 on `q = (measure − 1) / (ref − 1)`; the Phase 2 report shows how the two menus' ladders fall across the words, and the cut points are recalibrated there only if one word is empty or holds nearly every level.
16. **Menu size** (owner): 30 public, 100 admin (§6.2); a paid tier later, capped at 50 unless DR² is the default.
17. **Wording** (owner): no measure is shown as a count of holdings (§6.1).

## Expectations

Written in the owner's voice. **[J]** marks an expectation taken from what the owner said; **[+]** marks one added for build quality. These define done for this phase; the sections above say how.

**What this is for.** The ranges on the page should come from a model I'd defend to a quant, and the diversification number should mean what a visitor thinks it means: one fund is one thing. I want to switch between the old way and the new ways on the page and see for myself, and I want a known-good page to go back to if the new ones disappoint.

### Success scenarios

- **S1 [J]** Before any engine code lands, the live page is tagged and I can see, in the tag and the runbook, exactly which commit, which Worker version and which container image it was, and the three commands that put them back.
- **S2 [J]** In Settings there is a "Simulation" choice with three plain names: History replay, Volatility model, Copula. History replay is selected by default and the page looks exactly as it does today until I change it.
- **S3 [J]** When I pick the Volatility model, the Bad / Typical / Good figures, the little bar, the risk-slider readouts and the mix cards all change together and at once, and a small tag tells me which simulation produced them. The chart itself does not move.
- **S4 [J]** The Typical year stays close to the chart's expected return for every engine, and the risk I selected is the risk the simulation used: the level follows the years of history I chose, the shape does not.
- **S5 [J]** A fund that barely moves (TSP G, a T-bill fund) gets a sensible treatment under every engine and the details say its volatility was held constant; nothing errors and nothing looks absurd.
- **S6 [J]** Holding a single fund shows a diversification number of one under the new measure, on both ready-made menus, and a mix of four funds never scores more than four.
- **S7 [J]** With the details on, I can read, for the selected mix, how many of its funds the losses come from in its bad years and which funds gained in those years, and that figure changes when I change the simulation.
- **S8 [J]** A report in `docs/reviews/` shows, for both ready-made menus, how often each engine's Bad-to-Good range covered what actually happened over the last ten years, with the 2.5% breaches counted, and compares the three engines' Bad years and their reading of 2008, 2020 and 2022 side by side, so the default choice is mine and evidence-based.
- **S9 [J]** The copula work lives in QSE and is pinned here; nothing is forked or copied, and PortfolioSight installs only what it imports.
- **S10 [+]** A shared link opens with the same simulation and the same measure I was looking at.
- **S11 [+]** Custom menus still build inside the time budget with the new engines on, and the nightly finishes its two menus with every engine well within the night.

### Failure scenarios (looks right, is wrong)

- **F1 [J]** The default figures move when the new engines are added, before I have decided anything.
- **F2 [J]** A fund alone still scores many "bets", or the heat map still rewards piling into near-duplicates.
- **F3 [J]** The page says "copula" or "GARCH" in the default copy, or technical lines leak out of details.
- **F4 [J]** The engine switch rebuilds something, waits on the server, or leaves one number (the readout, the card, the bar) on the old engine.
- **F5 [+]** A fake crash from an unadjusted dividend or split finds its way into the shock pool and widens every range on the menu.
- **F6 [+]** The simulated volatility uses today's level, or the shape silently changes with the lookback.
- **F7 [+]** The loss-sources figure jumps around between neighbouring mixes because each was simulated with its own draw.
- **F8 [+]** The validation report is a table with no decision rule, or the rule is tuned until the new engine wins.

### Must-nots

- **M1 [J]** Never start engine code before the dashboard is tagged and the rollback commands are written down.
- **M2 [J]** Never fork, vendor or port QSE code into this repo; import the pinned commit and send improvements back as QSE pull requests.
- **M3 [J]** Never switch the default engine or the headline measure without my reading of the validation report.
- **M4 [J]** Never touch QSE's data, storage or request budget; the lake remains a read-once seed.
- **M5 [+]** Never fill, clip or renormalize a failed fit into a result: a fund that cannot be fitted is held at constant volatility and named.
- **M6 [+]** Never reduce the number of paths to meet a time budget.
