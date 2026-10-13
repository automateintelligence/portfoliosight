# PortfolioSight demo: design spec

Date: 2026-10-13. Status: approved for build. Owner: Jeff Daniels. Repo: `github:automateintelligence/portfoliosight`.
Inputs: `docs/reviews/2026-10-12_strategy_memo_portfolio_risk_return_website.md`, `..._addendum_user_feedback_and_decisions.md`, the six research reports, the owner's brainstorm decisions (final). This spec is consumed by an Expectations section (written afterwards), executable assertions, and an autonomous multi-phase build where each phase is done by a fresh agent with no memory. Every choice here is final unless a phase proves it impossible, in which case the phase reports and stops.

Owner's framing: "This is really not that complicated of a project, so don't over-complicate it. Build it out as a demo. If you build it wrong, we will fix it later. The goal is speed balanced with good econometrics and great website design and aesthetics."

## 1. Purpose and audience

A public page at `https://portfoliosight.ai`. A visitor sees a fund menu's efficient frontier, where a current mix sits against it, drags a risk slider, and gets a better-diversified mix at the same risk. Audience: people with a 401(k)/TSP/brokerage fund menu (NAVSEA/TSP friends first, Bogleheads-adjacent generally). Educational, impersonal, not advice. No login; the only gate is Cloudflare's standard human check.

## 2. Decisions and non-goals

Decided by the owner (not revisited here): first screen is the chart and its controls, everything else collapsed; no tangency/max-Sharpe point; risk slider = six-month 95% loss floor; a diversification control along the constant-risk line defaulting to the Bera-Park-style optimum; a diversification-surface heatmap under the frontier as the centerpiece; diversification in four plain words; presets (2017 guide Step 2 with allocation; TSP) plus custom portfolios of up to 30 funds from the downloaded universe; trade list; adaptive caps; lookbacks 1/2/3/5/10y + exponentially weighted with ghost frontiers; three stress cards; three themes (KnowledgeSight dark default, own light, HUD); plain-language layer; URL-encoded portfolios; Portfolio-Visualizer-style disclaimers; family footer CTA; backend precomputes, browser only interpolates; FastAPI container on KS-001 behind the existing cloudflared tunnel; Vite + React + TypeScript + D3 on Cloudflare Workers static assets; Cloudflare WAF Managed Challenge as the gate.

Data-source corrections (2026-10-13, owner-confirmed): the EODHD subscription does not include prices, dividends or splits (403 by plan), so the product uses a small price-provider interface with two adapters, **Tiingo (default)** and EODHD (only if explicitly selected), chosen by one config value; no yfinance, no Schwab. The owner's QSE lake (working copy on the laptop's WSL disk at `~/tft-quantile-forecaster/data/tft/raw/eodhd/datalake_us_core/eod_history`, 1,445 symbols with back-adjusted `adj_close` through 2026-02-27; `/mnt/d/tft-quantile-forecaster` is only QSE's nightly mirror and may be unmounted) is used once as a **seed**, uploaded from the laptop; QSE's own storage layout is not changed. **Cloudflare R2 is the canonical store** (bucket `portfoliosight-data`), the laptop drive `/mnt/d/` is the backup, and the KS-001 container is stateless apart from a 300 MB cache; KS-001's disk will not be expanded. Secrets live in `~/.secrets/portfoliosight.env`.

Choices made in this spec where the owner left them open are marked **[choice]** with a one-line reason.

Non-goals (ROADMAP only, see Appendix B): FERS planner, risk questionnaire / risk number, hedge/collar calculator, emails, programmatic SEO pages, payments/paywall, accounts/login, copula Monte Carlo, Student-t toggle, image export, walk-forward UI, robustness score, more than 30 funds, tickers outside the downloaded universe.

## 3. User experience

### 3.1 First screen

One viewport, no scrolling needed to use the product. Layout (desktop ≥ 1024 px):

```
┌ header: wordmark "PortfolioSight"  [preset ▾]  [theme ◐] ───────────────────┐
│ ┌ chart (D3; canvas heatmap+frontier, SVG markers) ───────┐ ┌ div slider ┐ │
│ │  y: expected return (yr)                                  │ │ More return│ │
│ │  heatmap Z(risk, return) under the frontier               │ │     ●      │ │
│ │  frontier line; vertical risk line at X; selected point ● │ │            │ │
│ │  current mix ◻ (if an allocation exists); ○ most diversif.│ │ More       │ │
│ │  x: risk (yearly ups and downs)                           │ │ diversified│ │
│ └───────────────────────────────────────────────────────────┘ └────────────┘ │
│  risk slider  [Set by: Bad six months | Typical six months]                 │
│  ◄──────────────────●──────────────────────►  "In a bad six months: −9.4%"   │
│  result strip: Low −9.4%  ·  Typical +3.1%  ·  High +15.6%   Diversification: Good   [details] │
│  chips: [Funds & amounts] [Trades] [Stress tests] [Settings]  (scroll to the collapsed sections) │
└──────────────────────────────────────────────────────────────────────────────┘
```

Chart contents, in draw order: (1) heatmap of Z over the feasible region (canvas); (2) ghost frontiers (thin, 40% opacity, one per toggled lookback); (3) primary frontier (2 px); (4) vertical dashed line at the selected risk X from the axis to the frontier; (5) marker "most diversified" (small hollow circle at the bottom end of the line); (6) current-mix marker (hollow square) when an allocation exists; (7) selected-point marker (filled circle with ring), draggable along the vertical line; (8) individual fund dots with ticker labels only when details are on. No tangency point, no capital market line, no Sharpe anywhere. Axis labels in plain words with technical names behind details (§3.6). Tooltip on hover/tap of the selected point: Low/Typical/High, diversification word, top five weights.

### 3.2 Controls

- **Preset menu** (header): "2017 guide, Step 2" (default), "TSP: G, F, C, S, I", "TSP with L Funds", "Custom…" (opens the Funds section).
- **Risk slider** (horizontal, under the chart). Its hidden parameter is the frontier risk X over the domain `[X_safe, X_max]` (§4.9). The readout depends on the "Set by" toggle: *Bad six months* (default) shows the 2.5th-percentile six-month return of the frontier point at X; *Typical six months* shows its mean six-month return. Both are the same one-dimensional frontier; the toggle changes only the label and the number the thumb reports. This is the "return slider" and costs nothing extra. Keyboard: arrow keys move 1/200 of the domain.
- **Diversification slider** (vertical beside the chart on desktop, horizontal under the risk slider on phone). End labels "More return" (top/left) and "More diversified" (bottom/right). No percentages, no numbers, never the word "knee". It moves the selected point along the vertical line between the frontier point (top) and the most-diversified point (bottom). Default position is the optimum (§4.8), marked with a small tick on the slider track; a "Reset to suggested" link appears once the user moves it. Dragging the point on the chart moves the slider and vice versa.
- **Result strip**: Low / Typical / High six-month return of the selected mix (normal, §4.9), the diversification word (small, muted, not a headline), and a **details** toggle. Details on: shows the exact measure ("spreads risk over the equivalent of 3.8 independent bets, out of a best possible 5.1 on this menu"; technical name "effective number of bets, minimum torsion"), yearly expected return and standard deviation, lookback dates, the tensor's `data_notes` (prices-through and any "distributions through …" disclosure, §5.6), fund dots on the chart, and the method footnote.
- **Theme switcher** (header): three-way segmented control, KnowledgeSight dark (default) / Light / HUD; persisted in `localStorage("ps.theme")`; the URL `t=` parameter wins over storage.
- **"Give us a moment"**: while a custom tensor builds, the chart area shows a centered notice with a progress ring and the queue position; controls are disabled; polling every 2 s.

### 3.3 Collapsed sections (below the first screen, all collapsed by default)

Accordion sections in this order; chips on the first screen scroll to and expand the matching section. **[choice]** Sections further down the page rather than a drawer: one implementation works on every width and keeps the first screen clean.

1. **Funds & amounts**: table of the menu: ticker, name, amount entered (number; unit toggle "%" or "$"), status note (e.g. "no data since 2024-10-30: not used"). Add fund (autocomplete over `/v1/symbols`), remove fund, "Use this menu" button (triggers tensor fetch/build). Max 30 funds; min 2. Amounts are optional; blank means no current mix. The preset "2017 guide" arrives with amounts filled from `data/holdings/holdings_guide2017_step2.csv` (Qty × Price); TSP presets arrive blank.
2. **Trades**: shown only when a current mix exists. Per fund: now %, selected %, change in percentage points, and dollars if "$" amounts were entered. Totals: one-way turnover. Copy: "Moves to get from the mix you entered to the selected mix."
3. **Stress tests**: three cards (§4.10).
4. **Settings**: lookback (radio: 1y, 2y, 3y, 5y (default), 10y, Weighted toward recent) with a list of funds excluded in that window and why; ghost frontiers (checkboxes per other lookback); caps table (min %, max % per fund, "Reset to default rule", one-sentence rule explanation); "Share this view" (copies the URL).

### 3.4 Phone layout (≤ 768 px)

Single column, 16 px side gutters, no horizontal scroll. Header 48 px (wordmark, preset menu as an icon button, theme as an icon button). Chart: full width, height = min(width, 60 vh). Below it: risk slider (56 px row), diversification slider (horizontal, 56 px row, labels "More return" left and "More diversified" right), result strip (two lines), chip row (horizontally scrollable). Touch targets ≥ 44 px; the selected point's hit area is 44 px even when drawn at 10 px. Sections render as full-width accordions. Patterns to copy: the KnowledgeSight landing nav (`~/programming/ai/website/src/components/landing/Nav.tsx`: compact header under 920 px, theme toggle moves into the menu) and its reduced-motion and focus-ring rules in `src/index.css`.

### 3.5 Themes and tokens

`<html data-theme="ks-dark|light|hud">`. All colors are CSS custom properties; the D3 layers read them with `getComputedStyle` on theme change and redraw. Fonts: Inter (UI), JetBrains Mono (numbers), EB Garamond (H1 wordmark in ks-dark only). Radii: 8 px controls, 16 px cards (ks-dark/hud), 4 px/8 px (light). Motion: 150–200 ms, `prefers-reduced-motion` disables all.

| Token | ks-dark (from `ai/website/src/components/knowledgesight/tokens/app-tokens.css`) | light (own; Windows/TurboTax-like, not the KnowledgeSight light theme) | hud |
|---|---|---|---|
| `--bg` | `#141417` | `#F3F3F3` | `#04070B` |
| `--surface` | `#1A1A1E` | `#FFFFFF` | `#0A1119` |
| `--elevated` | `#111114` | `#FFFFFF` | `#0E1722` |
| `--input` | `#0D0D0F` | `#FFFFFF` | `#070C12` |
| `--text` | `#EAE6E2` | `#1B1B1B` | `#D7F3FA` |
| `--text-2` | `#BEBAB6` | `#444444` | `#8FB8C6` |
| `--muted` | `#8A8784` | `#6B6B6B` | `#5C7E8C` |
| `--border` | `#2A2A2E` | `#D9D9D9` | `#163041` |
| `--accent` | `#C76346` | `#0F6CBD` | `#35C9E8` |
| `--accent-dark` | `#A54930` | `#0B5394` | `#1D8FA8` |
| `--accent-light` | `#E8907E` | `#5AA0E0` | `#8AE4F5` |
| `--success` | `#46C789` | `#107C10` | `#5EF2B0` |
| `--error` | `#EA5023` | `#C42B1C` | `#FF5C5C` |
| `--warn` | `#E8907E` | `#B85C00` | `#FFB347` |
| `--link` | `#6CB4EE` | `#0F6CBD` | `#8AE4F5` |
| `--shadow` | `0 4px 12px rgba(0,0,0,.3)` | `0 1px 3px rgba(0,0,0,.08)` | `0 0 12px rgba(53,201,232,.35)` |
| `--heat-0..4` (Z low→high) | `#1A1A1E #4A2A24 #A54930 #E8907E #F5DCC9` | `#FFFFFF #DCEBF9 #8BBDEA #2F86D1 #0B5394` | `#04070B #0B2F3F #1D8FA8 #35C9E8 #C8F7FF` |
| `--frontier` | `#EAE6E2` | `#1B1B1B` | `#C8F7FF` |
| `--mark-selected` | fill `--accent`, ring `--text` | fill `--accent`, ring `#FFFFFF` | fill `--warn`, ring `--accent` |
| `--mark-current` | `--link` | `#E07A1F` | `--error` |
| `--mark-div` | `--success` | `--success` | `--success` |
| `--risk-line` | `--text-2` dashed | `#6B6B6B` dashed | `--accent` dashed |

HUD specifics: 1 px `--border` lines with the `--shadow` glow on the chart frame and slider tracks; corner brackets (CSS pseudo-elements) on the chart frame; axis ticks and all numbers in JetBrains Mono; headings in Inter 600 uppercase with 0.08 em tracking; subtle 24 px grid lines at 6% opacity behind the heatmap. It is called "HUD" everywhere (code, copy, docs) and never references any film, character or trademark.

### 3.6 Plain-language copy table

| Where | Default (plain) | Behind details (technical) |
|---|---|---|
| x axis | "Risk: how much it bounces around in a year" | "Standard deviation of yearly return" |
| y axis | "Expected return per year" | "Shrunk expected return (50/50 sample mean and menu-beta prior), annualized" |
| Heatmap legend | "How spread out the risk is" | "Max effective number of bets (minimum torsion) at each risk/return" |
| Risk slider | "In a bad six months" / "In a typical six months" | "2.5th percentile / mean of the six-month return, normal approximation" |
| Result strip | "Low / Typical / High over six months" | "95% interval, normal, μ/2 ± 1.96·σ/√2" |
| Diversification word | "Good / Average / Fair / Poor" | "ENB 3.8 of a best possible 5.1 on this menu (ratio 0.75)" |
| Diversification slider | "More return" ↔ "More diversified" | "Return floor Y along the constant-σ line; suggested = bootstrap median (Bera-Park style)" |
| Suggested marker | "Suggested" | "Descend only while the return is statistically indistinguishable from the frontier" |
| Frontier | "Best return at each level of risk" | "Long-only mean-variance efficient frontier with caps" |
| Ghost frontiers | "Same menu, different years of history" | "Frontier estimated over the 1y/2y/3y/10y/EW window" |
| Caps | "No single fund above 25% (menu of 23)" | "cap = max(0.25, 3/N)" |
| Excluded fund | "VWOB: history starts 2013-06-04, not enough for the 10-year view" | — |
| Price-only tail | "Prices through 2026-10-12; distributions through 2026-02-27 for AAPL, MSFT" (details only) | "tr_index price-only after adjusted_through; within the 0.25 pp/yr distortion limit" |
| Stress card | "What this mix did: −31% (2008 crisis)" | "Buy-and-hold with the selected weights, 2008-09-01 to 2009-03-09" |
| Stress gap | "2 of 18 funds (11% of the mix) didn't exist yet; result is for the rest." | — |
| Current mix | "The mix you entered" | — |
| Building | "Give us a moment: computing this menu (about 30 seconds)" | — |

Never in default copy: "bets", "knee", "Sharpe", "tangency", "covariance", "sigma", "quantile", "bootstrap". Impersonal framing: "this mix", "the mix you entered", never "you should", "we recommend", or age/goal references.

### 3.7 Compliance copy

Under the result strip (12 px, muted): "Historical math, not investment advice." Footer disclaimer (always visible, not collapsed): "PortfolioSight is an educational tool. All figures are mathematical results computed from historical prices and are hypothetical; past performance does not predict future results. Nothing here is investment, tax or legal advice, and no output is a recommendation to buy or sell anything. PortfolioSight is not registered with the SEC, FINRA or any other regulator. You remain solely responsible for your decisions. Price data: Tiingo and tsp.gov." Footer CTA (generic, not keyed to the visitor's result): "More from the AutomateIntelligence family: Option Spread Scanner (https://option-spread-scanner.ingage-bd0.workers.dev), KnowledgeSight (https://automateintelligence.ai), SecuritySight (https://securitysight.ai)." No account linking, no human follow-up, no tracking beyond Cloudflare's own analytics.

## 4. Econometric method

All engine code lives in `portfoliosight/engine/` (pure functions over numpy arrays; no I/O). The seed `portfoliosight/frontier_cli.py` stays unchanged as the research baseline. Libraries: numpy, pandas, scipy, scikit-learn (`LedoitWolf`), cvxpy ≥ 1.5 with Clarabel. **[choice]** cvxpy+Clarabel rather than SLSQP: the risk constraint is second-order-cone, DPP-parametrized problems re-solve in ~2 ms, and the surface needs thousands of solves.

### 4.1 From prices to returns

Per fund the store holds the canonical record of §5.3: raw daily `close` and a total-return index `tr_index`; the engine's daily return is always `r_t = tr_index_t / tr_index_{t−1} − 1`. Provider rows are turned into index increments with `div_cash` (cash distribution per share on its ex-date, including fund capital-gain distributions as the provider reports them) and `split_factor` (ratio applied on the split date, 1.0 otherwise):

```
r_t = (close_t · split_factor_t + div_cash_t) / close_{t-1} − 1 ;   tr_index_t = tr_index_{t-1} · (1 + r_t)
```

Seeded rows take `tr_index` from the lake's back-adjusted `adj_close` (§5.4). TSP funds: share prices are already total-return NAVs, so `tr_index` is the price itself. Correctness test (Phase 0): for VTI and VBIAX the provider-built `tr_index` must match the provider's `adjClose` ratio to within 1e-5 per day over the full history; if the provider's split convention is inverted the adapter must divide instead, and this test is the arbiter. Splice test: for VTI, a seed-style record cut at 2025-12-31 and a provider tail spliced from there must match the all-provider `tr_index` to within 1e-5 from 2026-01-02 on. Trading-day alignment: the universe calendar is the union of all funds' dates; a fund's return is NaN on days it has no price; window statistics use the intersection of dates where every included fund has a return (see 4.2 for inclusion).

### 4.2 Lookback windows and short histories

Window ids and lengths: `1y`=252, `2y`=504, `3y`=756, `5y`=1260, `10y`=2520 trading days ending at the store's `asof` (last date on which every included fund has a price); `ew` = the 5y window with exponentially decaying observation weights, half-life 252 days, applied by position (used for both mean and covariance). A fund is **included in a window** only if its first return date is on or before `window_start + 0.10 · window_length`, its last price date is within 10 trading days of `asof`, and it passes the tail-gap rule of §5.6. Excluded funds are listed in the tensor with a reason string and shown in the UI (§3.6). The window's sample is then the intersection of included funds' dates; it must have ≥ 126 rows or the window is marked `unavailable` in the tensor and the UI disables it with "not enough shared history". A current mix with weight in excluded funds is renormalized over included funds and the UI says what share was set aside.

### 4.3 Moments

- Annualization: `μ_i = 252 · mean(r_i)`, `σ_i = √252 · sd(r_i)` (sample, ddof=1; weighted versions for `ew`).
- Covariance: Ledoit-Wolf linear shrinkage applied to **standardized** returns (shrinks the correlation matrix toward the identity), then rescaled by the sample standard deviations: `Σ = D^{1/2} R_LW D^{1/2}`, `D = diag(σ²)`. **[choice]** LW on correlations rather than on raw covariances so a near-zero-volatility fund (TSP G Fund, σ ≈ 0.3%/yr) keeps its own variance instead of being inflated toward the average. Diagonal floor: `σ_i ≥ 1e-4` (0.01%/yr) so Σ stays positive definite.
- Expected returns: **[choice]** `μ_s = 0.5 · μ̂ + 0.5 · π`, where `π = r_f + β · (μ̂_eq − r_f)`, `β = Σ w_eq / (w_eqᵀ Σ w_eq)`, `w_eq = 1/N`, `μ̂_eq = w_eqᵀ μ̂`. This is Black-Litterman's no-views prior with the equal-weighted menu as the reference portfolio (He-Litterman 1999), blended 50/50 with the sample mean (Kritzman-Page-Turkington 2010 for "do not use the raw sample mean"). Reason over grand-mean shrinkage: a cash-like fund is pulled toward `r_f`, not toward the equity average.
- Risk-free rate: trailing-12-month total return of SGOV if its record in the store is adjusted through `asof − 10` trading days or later, else TSP G Fund, else 0.04. One value per build.
- Citations: Ledoit & Wolf 2004 (JMA 88(2)); Jagannathan & Ma 2003 (J. Finance 58(4)); DeMiguel, Garlappi & Uppal 2009 (RFS 22(5)); Black & Litterman 1992; He & Litterman 1999.

### 4.4 Caps rule

Default per-fund bounds: `min = 0`, `max = clamp(3/N, 0.25, 1.0)` where N is the number of funds included in the window. So a 5-fund TSP core menu allows 60% in one fund, a 10-fund menu 30%, and any menu of 12 or more funds 25%. Rationale and citations: an upper bound of c guarantees `Σ w_i² ≤ c`, i.e. at least `1/c` effective positions by weight, which is the convex norm constraint of DeMiguel, Garlappi, Nogales & Uppal 2009 (Management Science 55(5)) and the shrinkage effect of Jagannathan & Ma 2003; the 25% floor echoes the single-issuer ceiling of the RIC diversification test (IRC §851(b)(3)) and is looser than the 1940 Act 75-5-10 and UCITS 5/10/40 limits because those govern single securities while every fund here is already diversified; 3/N keeps small menus usable (a flat 25% forces four of five TSP funds into every mix). Editable per fund in Settings; edits change the universe hash (§6) and trigger a rebuild. Feasibility: `Σ max ≥ 1` is enforced on input (422 otherwise); N ≥ 2.

### 4.5 Frontier

Grid of `NX = 48` risk columns `X_j` uniformly from `σ_min` (risk of the minimum-variance portfolio under caps) to `σ_max` (risk of the max-return portfolio under caps, found by greedy fill of highest-`μ_s` funds up to their caps). Frontier point at `X_j`:

```
maximize μ_sᵀ w   s.t.  ‖Σ^{1/2} w‖₂ ≤ X_j,  1ᵀw = 1,  min ≤ w ≤ max
```

Outputs `y_front[j]` and `w_front[j]`. `Σ^{1/2}` is the Cholesky factor (after the diagonal floor). One cvxpy `Problem` with parameters `(μ, L, X)` reused for all solves.

### 4.6 Diversification measure and the four words

Measure: effective number of bets via minimum torsion (Meucci, Santangelo & Deguest 2015, "Risk budgeting and diversification based on optimized uncorrelated factors", SSRN 2276632). Port `torsion.m` (minimum-torsion, exact method, BSD) into `engine/torsion.py` as `min_torsion(Σ) -> T` (n×n). Bets' variance contributions and ENB for weights `w`:

```
p = (T^{-T} w) ⊙ (T Σ w) / (wᵀ Σ w);   p_i ← max(p_i, 0);  p ← p / Σp
ENB(w) = exp(−Σ_i p_i ln p_i)   (terms with p_i = 0 contribute 0)
```

Tests: diagonal Σ → `T = I` and ENB(1/N) = N; `T Σ Tᵀ` is diagonal to 1e-8; Σ p = 1; a single-fund portfolio has ENB = 1.

Words: `q = ENB(w) / ENB_max`, where `ENB_max` is the largest ENB over all grid points of the same universe and lookback (the most diversified mix this menu can produce). **[choice]** Good `q ≥ 0.75`, Average `0.50 ≤ q < 0.75`, Fair `0.30 ≤ q < 0.50`, Poor `q < 0.30`. Relative to the menu's own best, because a five-fund TSP menu cannot reach the absolute ENB of a 23-fund menu and should not be called Poor for that; the thresholds are quartile-like cut points on the achievable range, stated in the details footnote.

### 4.7 Diversification surface

Rows `NY = 32` return levels `Y_k` uniformly from `Y_min` (return of the lowest-`μ_s` greedy fill under caps) to `Y_max = max_j y_front[j]`. Cell `(j, k)` is feasible iff `Y_k ≤ y_front[j]`. For each feasible cell, the convex proxy:

```
minimize ‖w‖₂²   s.t.  ‖Σ^{1/2} w‖₂ ≤ X_j,  μ_sᵀ w ≥ Y_k,  1ᵀw = 1,  min ≤ w ≤ max
```

gives `w[j][k]`; `Z[j][k] = ENB(w[j][k])` exact. **[choice]** Weight Herfindahl (the DeMiguel 2-norm, Rényi-2 entropy) as the proxy: it is the convex cousin of Bera-Park, is a QP, and the memo's "Herfindahl of risk contributions" is not convex in `w`. Correlation-blindness of the proxy is visible honestly because the displayed Z is the exact minimum-torsion ENB. Infeasible cells are `null`. Per column, `y_div[j] = max{Y_k : Z[j][k] ≥ 0.98 · max_k Z[j][k]}` is the "most diversified" point (highest return at which the column's diversification has plateaued); the slider's bottom end is `y_div[j]`, not `Y_min`. `ENB_max = max_{j,k} Z[j][k]`.

### 4.8 Default point on the vertical line (Bera-Park style)

Stationary block bootstrap (Politis & Romano 1994), expected block length 21 days, `B = 100` resamples, seed `20261013`. For each resample `b`: recompute `μ̂_b`, `π_b`, `μ_{s,b}`, `Σ_b` exactly as in 4.3; for each column `j` solve the frontier problem of 4.5 with `(μ_{s,b}, Σ_b, X_j)` → `w_{bj}`; evaluate `R_{bj} = μ_sᵀ w_{bj}` (the resampled optimum scored on the original moments). `y_star[j] = clamp(median_b R_{bj}, y_div[j], y_front[j])`. Interpretation shown in details: "half of the plausible re-estimates of the best mix at this risk score no better than this on today's numbers, so giving up return above this line buys diversification for free". Citation: Bera & Park 2008 (Econometric Reviews 27(4-6)) with `r = 0.5`; Pola 2016 (J. Asset Mgmt 17(4)) for the hold-risk-vary-return curve.

### 4.9 Six-month range, risk slider domain

For any weights with annual `(μ, σ)`: `μ_6 = μ/2`, `σ_6 = σ/√2`, `Low = μ_6 − 1.96 σ_6`, `Typical = μ_6`, `High = μ_6 + 1.96 σ_6` (normal; matches the owner's spreadsheet convention). Risk slider domain: `Low_front(X) = y_front(X)/2 − 1.96·X/√2` is not monotone near the minimum-variance end (the frontier is steep there), so the slider runs over `[X_safe, X_max]` where `X_safe = argmax_j Low_front(X_j)`; on that domain `Low_front` is strictly decreasing and the slider value ↔ X mapping is a bijection (linear interpolation between columns). Points left of `X_safe` are dominated (lower return and worse bad-six-months) and are drawn but not selectable. Initial X on load: the X whose frontier point has the same σ as the current mix if one exists, else the midpoint of the domain.

TSP G Fund: handled by the correlation-space shrinkage and diagonal floor (4.3); a 100%-G mix has ENB = 1 and the word "Poor" with the details line "there is little risk here, but all of it is in one place". No special-casing elsewhere.

### 4.10 Stress windows

Three fixed windows: `gfc2008` 2008-09-01 → 2009-03-09 ("2008 financial crisis"); `covid2020` 2020-02-19 → 2020-03-23 ("COVID crash, Feb–Mar 2020"); `rates2022` 2022-01-03 → 2022-10-12 ("2022 rate shock"). The tensor carries, per fund, the buy-and-hold total return over each window (`null` if the fund lacks a price within 3 trading days of both endpoints). The browser computes the selected mix's and the current mix's window return as `Σ_i w_i R_i / Σ_i w_i` over covered funds, shows the covered share, and, if covered weight < 50%, replaces the number with "Not enough of this mix existed then to say." Never fabricates.

### 4.11 Browser-side math and fidelity

The tensor ships `mu_s`, `sigma`, `cov`, `torsion` (T) and `torsion_inv_t` (`(Tᵀ)^{-1}`) so the browser computes exact `μ`, `σ`, ENB, six-month range and stress results for any weight vector. For a continuous slider position `(X, t)` with `t ∈ [0,1]` (0 = frontier, 1 = most diversified): find columns `j ≤ X < j+1`; `y_top = lerp(y_front)`, `y_bot = lerp(y_div)`, `Y = y_top − t (y_top − y_bot)`; weights = bilinear interpolation of the four surrounding grid weight vectors (frontier weights are used for the row at `y_top`), then clipped to bounds and renormalized to sum 1; statistics are recomputed from the tensor moments, never interpolated. Fidelity tests: at every grid node the TypeScript `stats(w)` equals the Python values in the tensor to 1e-6 (fixture tensor committed at `web/fixtures/guide2017_5y.json`, regenerated by the engine's test suite); for 200 random `(X, t)` pairs the recomputed σ is within 2% of X and the ENB lies within the min/max of the four neighbours ± 0.05.

### 4.12 Determinism and performance budgets

All randomness is seeded; building the same universe and lookback twice yields byte-identical JSON (test). Budgets on KS-001 (2 vCPU limit): one (universe, lookback) tensor for N ≤ 30 in ≤ 30 s; a full preset (six lookbacks) in ≤ 3 min; the three presets nightly in ≤ 10 min. Solve counts per lookback: 48 frontier + ~1,000 feasible cells + 4,800 bootstrap ≈ 5,900 small conic programs.

## 5. Data pipeline and request budget

### 5.1 Price-provider interface and adapters

`portfoliosight/data/providers/base.py`:

```python
class PriceProvider(Protocol):
    name: str
    def fetch_daily(self, symbol: str, start: date, end: date | None) -> pd.DataFrame: ...
        # columns: date (index, tz-naive), close, div_cash, split_factor; empty frame = no data
    def fetch_meta(self, symbol: str) -> SymbolMeta | None: ...   # name, first_date, last_date, kind
    def requests_cost(self, n_symbols: int) -> int: ...
```

The provider is one of three sources that fill the canonical per-symbol record (§5.3); the others are the one-time **seed** from the owner's QSE lake and **tsp.gov**. The provider is spent on: (a) symbols not in the seed (every mutual fund, the curated ETFs the lake lacks), fetched in full; (b) the dividend/split **tail** of seeded symbols from their `adjusted_through` date forward; (c) nightly updates. For (b) and (c) the adapter is called with `start = adjusted_through − 7 days`, the returned rows are converted to daily total returns with the formula of §4.1 and spliced onto the stored total-return index at `adjusted_through` (continuity: `tr_index_t = tr_index_{adjusted_through} · Π(1 + r_s)`), after which `adjusted_through = last fetched date` and `source` gains the provider's name.

Adapters: `tiingo.py` (default; `GET https://api.tiingo.com/tiingo/daily/{symbol}/prices?startDate=&endDate=&format=json&columns=date,close,divCash,splitFactor`, header `Authorization: Token $TIINGO_API_KEY`; meta from `GET /tiingo/daily/{symbol}`; 404 = no such symbol; 429 = back off `Retry-After` or 60 s) and `eodhd.py` (`eod/{S}.US`, `div/{S}.US`, `splits/{S}.US`, 1 call each; 403 = plan does not cover, mark provider unavailable and stop, following the `EntitlementDenied` pattern of `~/programming/quant-scenario-engine/qse/experimental/tft/data/eodhd_client.py`). Selected by env `PS_PRICE_PROVIDER=tiingo|eodhd`; exactly one adapter is instantiated per process, and the EODHD adapter is never imported or called unless it is the selected one (its allowance is shared with QSE's daily pipeline; a unit test asserts that with `PS_PRICE_PROVIDER=tiingo` no request to `eodhd.com` is ever issued). Secrets are read from the environment only, loaded from PortfolioSight's own file `~/.secrets/portfoliosight.env` (holds `TIINGO_API_KEY`, `EODHD_API_KEY`, `CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_R2_ACCESS_KEY_ID`, `CLOUDFLARE_R2_SECRET_ACCESS_KEY`, and after Phase 4 `PS_GATE_SECRET`), never `~/.secrets/qse.env`, and never logged (copy the `scrub_secrets` idea: redact any `Token`/`api_token` value and the literal key in every log line).

Verified 2026-10-13 with the key in `~/.secrets/portfoliosight.env`: Tiingo returns 200 with `close, adjClose, divCash, splitFactor` for VTI (history from 2001-05-31, 102 dividend rows), VTSAX, VBIAX (Dec-2025 distribution 1.627563 present), VGSTX (from 1985-03-29), SGOV; FIENX has data only to 2024-10-30 (the mutual fund was converted to an ETF) and is dropped from the default menu with the visible note "converted to an ETF; no data since 2024-10-30". This is expected behaviour, not a data bug.

### 5.2 Universe: three priority tiers

"Any ticker already in our universe" means a symbol whose canonical record exists in PortfolioSight's own store (R2, §5.3). Nothing is read from QSE at runtime; the QSE lake is read once, on the owner's laptop, by the seed script (§5.4). The served universe is defined in priority tiers:

1. **Tier 1, presets**: the 23 funds of the Step 2 default (`data/holdings/holdings_guide2017_step2.csv`) plus the 16 TSP funds (tsp.gov).
2. **Tier 2, curated menu staples**: `data/universes/portfoliosight.txt`, 313 ETFs and mutual funds (Appendix A: 401(k)/IRA staples, broad asset-class ETFs, the Step 2 funds). Lines may carry an `,income` tag (bond and cash funds), which raises their refresh priority because missing distributions distort them most.
3. **Tier 3, QSE core stocks**: `data/universes/qse_core.txt`, a copy of `~/programming/quant-scenario-engine/data/tft/raw/eodhd/universes/datalake_us_core.txt` (1,038 symbols, 4 of which overlap tier 2) committed to this repo in Phase 0; deduplicated against tier 2 at load time. Available from day one through the seed (the lake holds about 1,450 symbols, 1,445 files on 2026-10-13, so it also covers some tier 2 ETFs); only its **freshness** (the dividend tail and nightly updates) depends on the provider budget.

Files are one symbol per line with `#` comments; `data/universes/tiers.json` lists the files in order. Provider requests are spent in this priority order: tier 1, then `income`-tagged symbols of tier 2, then the rest of tier 2, then tier 3; the downloader stops when the hour, day or monthly unique-symbol budget is exhausted and resumes next run. The ticker picker (`/v1/symbols`) offers **only** symbols with `status: ok` in the manifest (a canonical record with a price within 10 trading days of `asof`). Symbols the provider does not know (404) or that have no recent data are kept in the manifest as `unavailable` with the reason. Under the conservative Starter assumption (§5.4) tier 3 symbols are served from the seed with a price-only tail until the budget reaches them; the tail-gap rule of §5.6 decides which lookbacks they may appear in, and the Funds section's add-fund help text reads "Menu funds and ETFs are kept current first; individual stocks catch up as data allows."

### 5.3 Storage: Cloudflare R2 is the canonical store; KS-001 is stateless

Owner decision (final): no universe data lives on KS-001; R2 is canonical, the laptop drive `/mnt/d/` is the backup. A dedicated bucket **`portfoliosight-data`** (new; the account's existing buckets `knowledgesight-documents`, `olney-forms`, `qse-backup`, `scs-backups`, `scs-models` are not reused), accessed with the S3-compatible API (`boto3`, `endpoint_url=https://{CLOUDFLARE_ACCOUNT_ID}.r2.cloudflarestorage.com`, `region_name="auto"`, credentials `CLOUDFLARE_R2_ACCESS_KEY_ID` / `CLOUDFLARE_R2_SECRET_ACCESS_KEY` from `~/.secrets/portfoliosight.env`). Module `portfoliosight/data/store.py` wraps get/put/list/delete with retries and is the only code that touches R2; a `LocalStore` with the same interface backs tests and local development (`PS_STORE=r2|local`, `PS_LOCAL_STORE_DIR`).

Key layout in the bucket:

```
prices/{SYMBOL}.parquet          canonical per-symbol record (below); TSP as TSP-G.parquet etc.
meta/manifest.json               per symbol: name, kind (etf|mutual_fund|stock|tsp), tier, income (bool), source
                                 (seed|tiingo|eodhd|tsp|seed+tiingo|seed+eodhd), first_date, last_date,
                                 adjusted_through, dist_yield_12m, status (ok|unavailable|pending), reason, fetched_at
meta/provider_limits.json        measured provider tier and the limits in force (§5.4), with date and method
meta/budget.json                 provider request ledger: counts per UTC hour and day, unique symbols this month
meta/presets_state.json          written nightly; exactly the body of GET /v1/presets
meta/symbols.json                written nightly; exactly the body of GET /v1/symbols
meta/status.json                 last nightly run: started, finished, symbols refreshed per tier, errors
tensors/{hash}/{lookback}.json   preset and custom tensors (plain JSON; Cloudflare compresses on delivery)
```

Canonical per-symbol record (**[choice]** raw close plus a total-return index, because the seed has `adj_close` but no dividend records while the provider has dividend records; one format both can fill): parquet columns `date` (tz-naive), `close` (raw, unadjusted), `tr_index` (total-return index, 1.0 on the first row, dividends reinvested at the ex-date close, splits removed), `div_cash` and `split_factor` (nullable; filled only for rows that came from a provider, for audit). Daily returns are always `tr_index.pct_change()`. Per-symbol provenance lives in the manifest: `source` and `adjusted_through`, the last date through which `tr_index` is known to include every distribution; rows after it are **price-only** (`tr_index` moves with `close` alone) until a provider refresh splices the tail (§5.1).

Repo files (committed, read-only at runtime): `data/universes/tiers.json`, `data/universes/portfoliosight.txt`, `data/universes/qse_core.txt`, `data/presets.json`, `data/holdings/holdings_guide2017_step2.csv`. The repo's other `data/holdings/*.csv` and the whole `runs/` tree are personal and are excluded from the image (`.dockerignore`) and from the site; a test asserts the built image contains neither.

KS-001 scratch: the container keeps a size-capped LRU cache at `/app/cache` (named Docker volume `ps-cache`; `PS_CACHE_MAX_MB=300`, evicted by last access after every build and every nightly step); it holds only the parquet files a build needs and the tensor being written. Nothing on KS-001 is authoritative; the container can be deleted and recreated at any time.

Backup and restore (owner's laptop): `scripts/r2_backup.sh` mirrors the bucket to **`/mnt/d/portfoliosight-data/`** with the AWS CLI v2 (`aws s3 sync --endpoint-url https://{ACCOUNT}.r2.cloudflarestorage.com s3://portfoliosight-data /mnt/d/portfoliosight-data --delete`), reading the two R2 keys from `~/.secrets/portfoliosight.env`. Before syncing, the script checks `mountpoint -q /mnt/d` and that `/mnt/d/portfoliosight-data` exists or can be created; if D: is not mounted it prints "D: drive is not mounted at /mnt/d; backup not run" and exits with status 2 (never a silent skip). `scripts/r2_backup.sh --restore` runs the same sync with source and destination swapped (laptop → bucket, never `--delete` on restore), with the same mount check. The owner runs it by hand or schedules it (a weekly Windows Task Scheduler entry or a WSL cron line; not part of the build). Restore is only ever run after the bucket is confirmed lost or corrupted.

### 5.4 Seed, catch-up and nightly: budget-aware and resumable

**Seed (one-time, laptop → R2, zero provider cost).** `python scripts/seed_r2_from_lake.py [--lake PATH] --adjusted-through 2026-02-27 [--dry-run]` reads the lake's per-symbol parquet from `--lake`, which defaults to the WSL working copy `~/tft-quantile-forecaster/data/tft/raw/eodhd/datalake_us_core/eod_history` (the QSE repo's `data/` folder is a symlink to it; `/mnt/d/tft-quantile-forecaster` is only QSE's nightly mirror and may be unmounted, so it is never the default); the script exits with a clear error if the path does not exist or holds fewer than 1,000 parquet files. Columns `date, open, high, low, close, adj_close, volume`; 1,445 files, 269 MB; history back to 1995–2002. It converts each to the canonical record (`tr_index = adj_close / adj_close.iloc[0]`, price-only after `adjusted_through`), computes `dist_yield_12m` (sum over the last 252 rows up to `adjusted_through` of `adj_close_t/adj_close_{t−1} − close_t/close_{t−1}`, ignoring rows where that difference exceeds 0.2 in absolute value, which are splits), and uploads `prices/{SYMBOL}.parquet` plus manifest entries with `source: seed`, `adjusted_through: 2026-02-27`, `status: ok` straight to R2 (8 concurrent uploads, resumable by skipping keys that already exist with the same size). The lake's `dividends/` and `splits/` folders are empty and are ignored. The script asserts, before uploading anything, that no row after `--adjusted-through` in any file has `adj_close != close` and prints the latest per-symbol adjustment date it found (expected: VTI 2025-12-19, AAPL 2026-02-06, SGOV and TLT 2026-02-27); a violation stops the script. QSE is not modified and not read at runtime.

**Downloader.** `python -m portfoliosight.data.download --mode measure-limits|catch-up|refresh [--symbols ...] [--tiers 1,2,3]`, run inside the KS-001 container (reads and writes R2; the laptop can run it too with the same env file). Catch-up = for every universe symbol without a record, fetch the full history (one request) and its meta (one request); for every seeded symbol, fetch the tail from `adjusted_through − 7 days` (one request) and splice. Refresh = for every symbol with `status: ok`, fetch from `last_date − 7 days` (one request) and splice; symbols already at the latest trading day are skipped. Both modes walk the priority order of §5.2 and write each symbol's parquet and manifest entry to R2 as they go (manifest is rewritten atomically after each tier; the nightly job is the only manifest writer).

Limits the design assumes, labelled: **the tier of the Tiingo key is unverified**, so the conservative assumption is Tiingo **Starter**: 50 requests/hour, 1,000 requests/day, 500 unique symbols/month, 1 GB/month; Tiingo **Power** ($30/month) is 10,000/hour, 100,000/day, 110,248 symbols, 40 GB/month (tiingo.com/about/pricing, read 2026-10-13). Tiingo responses carry no rate-limit headers (verified: only `x-frame-options`), so the limits are measured, not read. The downloader never hard-codes them: it reads `meta/provider_limits.json` (`{"provider":"tiingo","tier":"starter|power|measured","req_per_hour":45,"req_per_day":900,"unique_symbols_per_month":450,"measured_on":"YYYY-MM-DD","method":"probe|documented"}`), falling back to env `PS_PROVIDER_REQ_PER_HOUR=45`, `PS_PROVIDER_REQ_PER_DAY=900`, `PS_PROVIDER_SYMBOLS_PER_MONTH=450` (Starter minus a 10% margin) when the file is absent. `--mode measure-limits` is part of the first build gate (DoD 22): it issues up to 60 meta requests for one already-fetched symbol within ten minutes; a 429 before the 60th request records Starter, no 429 records "at least 60/10 min" and, with the owner's confirmation of the plan from the Tiingo account page, Power; either way it writes `meta/provider_limits.json` with the method and date, and the result is also recorded in `docs/plans/2026-10-13-ks001-cloudflare-runbook.md`. The ledger `meta/budget.json` is updated per request (hour, day, unique symbols this month); the downloader sleeps until the next hour when the hourly budget is spent, exits cleanly when the daily or monthly budget is spent, and the manifest records progress so a rerun continues where it stopped. One request per symbol per mode (Tiingo returns the full history in one response); meta is fetched once per symbol. Priority order as in §5.2 (tier 1, tier 2 `income`, rest of tier 2, tier 3), alphabetical within a group.

Request budget under the Starter assumption (450/day after margin, 450 unique symbols/month): tier 1 = 10 non-seeded funds (full history + meta, 20 requests) + 13 seeded ETFs (tail, 13 requests), first hour of the first night; tier 2 = roughly 280 non-seeded symbols (560 requests) + roughly 30 seeded (30 requests), about 13 hours at 45/hour over two nights; nightly refresh of tiers 1–2 = 336 requests (7.5 hours) + 1 tsp.gov request; that leaves about 110 unique symbols/month for tier 3 tails, so on Starter **tier 3 is served from the seed and its tails close at about 110 stocks per month**, income-tagged and preset symbols always first. Under Power: tier 3 tails (1,034 requests) and the nightly refresh of all tiers (≈ 1,370 requests) take under 15 minutes. With EODHD (only if selected): 3 calls per non-seeded symbol for catch-up, 1 per symbol for tails and nightly, under its own allowance.

Nightly sequence (02:00 PT Mon–Sat, inside the `nightly` container, `flock`-guarded, all reads and writes against R2): (1) refresh tier 1 (23 provider requests + the TSP CSV); (2) rebuild the three presets × six lookbacks, write `tensors/{preset_hash}/{lookback}.json`, then `meta/presets_state.json` and `meta/symbols.json` (put after all tensors exist, so readers never see a half-built preset); (3) refresh tier 2 `income`, then the rest of tier 2, then tier 3 within budget; (4) delete `tensors/` entries that are not presets and are older than 24 h (custom tensors rebuild on demand); (5) write `meta/status.json`; (6) evict the local cache to its cap. Alerts: none for the demo; `/v1/health` exposes `meta/status.json` and the age of `asof`.

### 5.5 TSP

`portfoliosight/data/providers/tsp.py`: `GET https://www.tsp.gov/data/fund-price-history.csv?startdate=YYYY-MM-DD&enddate=YYYY-MM-DD&Lfunds=1&InvFunds=1&download=1` with a browser User-Agent (verified 2026-10-13: curl's default UA receives 403, a Chrome UA receives the CSV; columns `Date, L Income, L 2030, …, L 2075, G Fund, F Fund, C Fund, S Fund, I Fund`). Catch-up from 2003-06-02; refresh from `last_date − 7 days`. Symbol ids `TSP-G, TSP-F, TSP-C, TSP-S, TSP-I, TSP-LINC, TSP-L2030, TSP-L2035, TSP-L2040, TSP-L2045, TSP-L2050, TSP-L2055, TSP-L2060, TSP-L2065, TSP-L2070, TSP-L2075`; display names "G Fund", "L 2030", etc. `div_cash = 0`, `split_factor = 1`.

### 5.6 Missing-data policy

A fund with no data, no recent data, or too little history for a window is dropped from that computation and listed with its reason in the tensor's `excluded` array; the UI shows the note in the Funds table and the Settings lookback list. Nothing is ever interpolated, back-filled or fabricated. Default-universe funds that depend on provider mutual-fund coverage: VBIAX (covered), VGSTX (covered), FIENX (converted to an ETF; data ends 2024-10-30; excluded from the default menu with the note "converted to an ETF; no data since 2024-10-30"). Reason strings are fixed templates: `no data`, `converted to an ETF; no data since {date}`, `no data since {date}`, `history starts {date}, not enough for the {window} view`, `distributions not yet loaded after {date}; would distort the {window} view`.

**Tail-gap rule (price-only tails).** For a symbol whose `adjusted_through` is before the window's end, `gap_days` = trading days from `adjusted_through` to `asof`, and the missing distributions are estimated as `missing = dist_yield_12m × gap_days / 252`. The symbol is excluded from a window when `missing / window_years > 0.0025` (it would move the window's annualized return by more than 0.25 percentage points). Examples with the seed's gap of about 157 trading days as of 2026-10-13: SGOV (yield ≈ 4.5%) is excluded from every window until its tail is refreshed (which happens on the first night, it is tier 1); a stock yielding 0.5% is excluded from the 1-year window only; a non-dividend stock is never excluded. Included symbols with `gap_days > 0` are listed in the tensor (`universe.funds[].adjusted_through`, `data_notes`) and the details view shows "Prices through 2026-10-12; distributions through 2026-02-27 for AAPL, MSFT" so the limitation is disclosed, never hidden. For the `ew` window, `window_years = 5`.

## 6. API contract

Service: FastAPI, `portfoliosight/api/app.py`, served by uvicorn on container port 8000, published on KS-001 as `127.0.0.1:8010`, reached publicly as `https://api.portfoliosight.ai` (tunnel) and by the page as same-origin `https://portfoliosight.ai/api/*` (Worker, §9.3). All responses JSON (`application/json; charset=utf-8`), errors as `{"error": {"code": str, "message": str, "details": object|null}}`. Version prefix `/v1`. CORS: none needed (same-origin via the Worker); the API still sets `Access-Control-Allow-Origin: https://portfoliosight.ai` for direct smoke tests.

Read/write split (**[choice]**, adopted because it is simpler and lighter on KS-001): the Worker serves every **read** straight from R2 through an R2 binding (`GET /api/presets` ← `meta/presets_state.json`, `GET /api/symbols` ← `meta/symbols.json`, `GET /api/tensors/{hash}/{lookback}` ← `tensors/{hash}/{lookback}.json`) and forwards to KS-001 only `POST /api/tensors`, `GET /api/health`, and a tensor `GET` whose key is absent in R2 (so the API can answer 202 building or 404). Presets and every previously built tensor therefore keep working when KS-001 is down; KS-001 only builds. The API implements the full table below so the Worker's fallback and the smoke tests have one contract.

| Method, path | Request | Response | Cache-Control |
|---|---|---|---|
| `GET /v1/health` | — | `200 {"status":"ok","version":str,"asof":"YYYY-MM-DD","asof_age_days":int,"presets_ready":bool,"nightly":{status.json}}` | `no-store` |
| `GET /v1/presets` | — | `200 {"asof":str,"presets":[{"id":"guide2017","name":str,"hash":str,"funds":[{"id","name"}],"allocation":{"VTI":10840,...}|null,"allocation_unit":"$"|null,"lookbacks":{"5y":"ready"|"building"|"unavailable",...}}]}` | `public, max-age=300` |
| `GET /v1/symbols` | — | `200 {"asof":str,"tiers_served":[1,2],"symbols":[{"id":"VTI","name":str,"kind":"etf"|"mutual_fund"|"stock"|"tsp","tier":1|2|3,"first_date":str}]}` (only `status=ok` symbols, i.e. actually downloaded) | `public, max-age=86400` |
| `POST /v1/tensors` | `{"funds":[{"id":"VTI","min":0.0,"max":0.25},...],"lookback":"5y"}`; 2–30 funds; ids uppercase; `min/max` optional (default rule applies); `lookback` ∈ {1y,2y,3y,5y,10y,ew} | `200 {"status":"ready","hash":str,"url":"/v1/tensors/{hash}/{lookback}?v={asof}"}` · `202 {"status":"building","hash":str,"position":int,"eta_s":int}` · `400 unknown_symbols {"symbols":[...]}` · `422 invalid_request` (duplicates, >30, <2, infeasible caps, bad lookback) · `503 busy` when the queue holds 20 builds | `no-store` |
| `GET /v1/tensors/{hash}/{lookback}?v=` | `hash` = 16 hex chars | `200` tensor (§7) with `ETag` · `202 {"status":"building",...}` · `404 unknown_tensor` (never requested) | `200`: `public, max-age=86400, immutable` (the `v` query is the data version); `202/404`: `no-store` |

Universe hash: `sha256(canonical_json({"schema":1,"funds":[{"id","min","max"} sorted by id]}))[:16]` where `min/max` are the effective bounds after the default rule, rounded to 4 decimals. Presets are ordinary universes whose hashes are published in `/v1/presets`. The build queue is a single worker thread (`ThreadPoolExecutor(max_workers=1)`) inside the API process; a build reads only the needed `prices/*.parquet` from R2 into the local cache, computes the requested lookback first, puts it to R2, then builds the other five lookbacks for the same hash in the background. `GET /v1/tensors` checks R2 (`head_object`) and streams the object on a hit. Non-preset tensors are deleted by the nightly job after 24 h; there is no local disk cap beyond the 300 MB cache (§5.3).

Abuse protection suited to an unauthenticated demo: input limits above; Cloudflare rate-limiting rule (Free plan, 1 rule): more than 5 `POST /api/tensors` per 10 s from one IP → block 10 s; the WAF rules of §9; `uvicorn --limit-concurrency 32`; request body limit 16 KB; per-IP in-process limiter of 60 requests/minute on `/v1/*` returning 429 (`slowapi` or a 20-line token bucket keyed by `CF-Connecting-IP`).

## 7. Tensor format

One JSON document per (hash, lookback). Floats rounded to 6 significant digits; weights to 4 decimals. Sizes: N = 23 → about 230 KB raw, 60–80 KB gzip; N = 30 → about 300 KB raw.

```json
{
  "schema": 1,
  "engine_version": "0.1.0",
  "built_at": "2026-10-13T09:31:02Z",
  "build_seconds": 14.2,
  "asof": "2026-10-12",
  "universe": {"hash": "3f9c2a7e1b4d5e60", "name": "2017 guide, Step 2", "preset_id": "guide2017",
               "funds": [{"id": "AGG", "name": "iShares Core US Aggregate Bond ETF", "kind": "etf",
                          "source": "seed+tiingo", "adjusted_through": "2026-10-12"}, ...],
               "excluded": [{"id": "FIENX", "reason": "converted to an ETF; no data since 2024-10-30"}]},
  "data_notes": ["Prices through 2026-10-12.", "Distributions through 2026-02-27 for DBJP, PCY (price-only tail, within the distortion limit)."],
  "lookback": {"id": "5y", "start": "2021-10-13", "end": "2026-10-12", "rows": 1257, "ew_halflife_days": null},
  "rf": 0.0412,
  "mu_s": [...n], "mu_sample": [...n], "sigma": [...n], "cov": [[...n]...n],
  "torsion": [[...]], "torsion_inv_t": [[...]],
  "bounds": {"min": [...n], "max": [...n], "rule": "max(0.25, 3/N)"},
  "frontier": {"x": [...48], "y": [...48], "w": [[...n]...48], "x_safe_index": 7},
  "grid": {"y": [...32], "z": [[...32]...48], "w": [[[...n]...32]...48], "y_div": [...48], "y_star": [...48]},
  "enb_max": 5.13,
  "stress": {"gfc2008": {"label": "2008 financial crisis", "start": "2008-09-01", "end": "2009-03-09", "r": [...n|null]},
             "covid2020": {...}, "rates2022": {...}},
  "notes": ["Expected returns are 50/50 sample mean and menu-beta prior.", "..."]
}
```

`grid.w[j][k]` and `grid.z[j][k]` are `null` for infeasible cells. Fund order is the `universe.funds` order everywhere. A JSON Schema at `portfoliosight/engine/tensor.schema.json` is the contract; both the Python builder (on write) and the TypeScript loader (on read, with `zod` or `ajv`) validate against it.

## 8. Front-end architecture

`web/` (Vite 7, React 19, TypeScript 5.8, D3 modules only: `d3-scale`, `d3-shape`, `d3-selection`, `d3-drag`, `d3-interpolate`, `d3-axis`; `lucide-react` icons; no component library; Tailwind not used, plain CSS modules with the token file `web/src/theme/tokens.css`).

```
web/src/
  main.tsx, App.tsx
  state/store.ts            single reducer: universeSpec, allocation, lookback, ghosts, X, t | "auto", theme, caps, status
  state/url.ts              encode/decode of the URL query (§8.1), replaceState debounced 250 ms
  api/client.ts             fetch /api/*, typed by tensor.schema.json; polling for 202
  math/portfolio.ts         stats(w): mu, sigma, enb, range6m, stress; interpolate(X, t); riskSliderDomain
  chart/Heatmap.tsx         canvas layer: heatmap cells + ghost/primary frontier lines (devicePixelRatio aware)
  chart/Overlay.tsx         SVG layer: axes, risk line, markers, drag handlers, tooltip
  controls/RiskSlider.tsx, DivSlider.tsx, ResultStrip.tsx, ThemeSwitch.tsx, PresetMenu.tsx
  sections/Funds.tsx, Trades.tsx, Stress.tsx, Settings.tsx
  theme/tokens.css, theme/useTheme.ts
web/worker/index.ts         Cloudflare Worker: /api/* proxy + static assets (§9)
web/fixtures/guide2017_5y.json
web/tests/ (vitest)         math fidelity, url codec, reducer
web/e2e/smoke.spec.ts       Playwright against production (§10)
```

Rendering: canvas redraws on theme change, tensor change, ghost toggle; the SVG overlay updates on every slider tick (≤ 1 ms of math). The heatmap is drawn as filled rectangles per cell with `d3-interpolate`'s `interpolateRgbBasis(heat-0..4)` on `Z / enb_max`, 1 px gaps none, infeasible cells transparent. Chart margins 48/16/40/56 px (desktop), 32/12/36/44 (phone). Axes in percent. All interactive elements carry `data-testid` (listed in §10).

### 8.1 URL encoding

Query parameters, all optional, updated on every change: `u` preset id (`guide2017|tsp5|tsp16`) or omitted for custom; `f` custom funds as `ID:amount` comma-separated (amount optional, e.g. `f=VTI:60,BND:40,VNQ`); `unit` `pct|usd` (default `pct`); `c` cap overrides `ID:min:max` (percent integers, comma-separated); `lb` lookback id; `g` ghost ids comma-separated; `loss` risk slider value as the bad-six-months return (e.g. `loss=-0.094`); `by` `bad|typical`; `d` diversification position `auto` or a decimal in `[0,1]`; `t` theme id; `x` `1` when details are on. Example: `https://portfoliosight.ai/?u=guide2017&lb=5y&loss=-0.094&d=auto&t=hud`. Decoding never trusts the URL for anything but these fields; unknown funds are reported through the normal 400 path.

## 9. Deployment

### 9.1 Backend container on KS-001 (mirrors `option-scanner-api`)

- Files: `deploy/Dockerfile` (python:3.12-slim, two-stage, non-root user `app`, `pip install .[api]`), `deploy/docker-compose.yml` (services `api` and `nightly`, same image), `deploy/crontab` (`CRON_TZ=America/Los_Angeles`; `0 2 * * 1-6 flock -n /var/run/ps-nightly.lock timeout -k 60 36000 python -m portfoliosight.jobs.nightly >> /proc/1/fd/1 2>&1`, so the run appears in `docker logs portfoliosight-nightly`), `.dockerignore` (excludes `runs/`, `data/holdings/` except the Step 2 CSV, `.venv`, `web/node_modules`, `web/dist`).
- Compose `api`: `container_name: portfoliosight-api`, `restart: unless-stopped`, `ports: ["127.0.0.1:8010:8000"]`, `deploy.resources.limits: {cpus: "2", memory: 1536M}`, `reservations: {cpus: "0.5", memory: 256M}`, volumes: only the named cache volume `ps-cache:/app/cache` (no data bind mount; the container is stateless), `env_file: ~/.secrets/portfoliosight.env` (the owner creates this file on KS-001 with the same keys as the laptop copy, including the two R2 keys; `export` prefixes stripped, since compose `env_file` takes `KEY=value` lines), environment `PS_PRICE_PROVIDER=tiingo`, `PS_STORE=r2`, `PS_R2_BUCKET=portfoliosight-data`, `PS_CACHE_DIR=/app/cache`, `PS_CACHE_MAX_MB=300`, healthcheck `GET /v1/health` every 30 s, json-file logging capped 10 MB × 3. `nightly`: same image, `command: ["cron","-f"]`, same volume, env and limits, healthcheck `pgrep cron`. Both on a private bridge network; only `api` publishes a port.
- Host layout: `~/portfoliosight` (git clone, branch `main`) on KS-001 as user `jeff`, used only to build the image; no datalake on the host and no plan to grow KS-001's disk. Deploy script `scripts/deploy_ks001.sh` (run from the laptop): `ssh KS-001-jeff "cd ~/portfoliosight && git pull --ff-only && docker compose -f deploy/docker-compose.yml build && docker compose -f deploy/docker-compose.yml up -d"` then `curl -fsS http://127.0.0.1:8010/v1/health` over ssh. Images are tagged with the git SHA (`image: portfoliosight:${GIT_SHA}` via `.env`); rollback = `git checkout <sha> && docker compose up -d`.
- Resource reality (2026-10-13): KS-001 has 24 GB RAM with 13 GB available, 44 GB disk free, ports 8000/8001/8002/8004/8005 in use, 8010 free; cloudflared 2026.1.2 runs as a systemd service with `/etc/cloudflared/config.yml` (root-owned); `jeff` has passwordless sudo.

### 9.2 Tunnel and DNS

Add to `/etc/cloudflared/config.yml` ingress, **above** the catch-all: `- hostname: api.portfoliosight.ai\n  service: http://localhost:8010`, then `sudo systemctl restart cloudflared`. DNS in the `portfoliosight.ai` zone (zone id `0434784c350a6fc062b2d4ae389cdd9b`, Free plan, active, no records yet): proxied CNAME `api.portfoliosight.ai → 222b8001-009a-47b2-8a31-3ea624ce32ca.cfargotunnel.com`, created with the API token from `~/.secrets/portfoliosight.env` (`POST /zones/{zone}/dns_records`; the token can list this zone's DNS, edit is untested) or by `cloudflared tunnel route dns` on KS-001, or in the dashboard. The apex and `www` are created automatically by the Worker custom domains (9.3).

### 9.3 Worker and static assets

`web/wrangler.jsonc`: `name: "portfoliosight"`, `main: "worker/index.ts"`, `compatibility_date: "2026-09-01"`, `assets: {directory: "./dist", binding: "ASSETS", not_found_handling: "single-page-application", run_worker_first: ["/api/*"]}`, `r2_buckets: [{binding: "DATA", bucket_name: "portfoliosight-data"}]`, `routes: [{pattern: "portfoliosight.ai", custom_domain: true}, {pattern: "www.portfoliosight.ai", custom_domain: true}]`, `vars: {API_ORIGIN: "https://api.portfoliosight.ai"}`, secret `PS_GATE_SECRET` (`wrangler secret put`). Worker logic: `www` → 301 to apex; `GET /api/presets` → `env.DATA.get("meta/presets_state.json")`, `GET /api/symbols` → `env.DATA.get("meta/symbols.json")` (both `Cache-Control: public, max-age=300`), `GET /api/tensors/{hash}/{lookback}` → `env.DATA.get("tensors/{hash}/{lookback}.json")` served with `Cache-Control: public, max-age=86400, immutable` and the object's `etag`; on an R2 miss, and for `POST /api/tensors` and `GET /api/health`, forward to `fetch(API_ORIGIN + "/v1/" + rest, {method, body, headers: {"x-ps-gate": env.PS_GATE_SECRET, "content-type": ..., accept: "application/json"}})` and return the upstream response with its `Cache-Control`; anything else → `env.ASSETS.fetch(request)`. `hash` and `lookback` are validated (`^[0-9a-f]{16}$`, the six ids) before any R2 key is built. Deploy: `npm run build && wrangler deploy` with `source ~/.secrets/portfoliosight.env` (wrangler reads `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID`). Rollback: `wrangler rollback`. Workers Free plan: 100k requests/day; R2 free tier: 10 GB, 1M Class A and 10M Class B operations/month; a page load is ≤ 12 requests.

**[choice]** Same-origin Worker rather than a challenge cookie on the apex: one hostname carries one challenge, the page's fetches are same-origin so the clearance cookie applies to them automatically, there is no CORS, the API hostname is never reachable without the Worker's secret header, and with the R2 binding every read bypasses the tunnel and KS-001 entirely.

### 9.4 Human check and smoke-test exemption (standard Cloudflare only)

WAF custom rules on the `portfoliosight.ai` zone (Free plan: 5 rules, Managed Challenge available, no regex needed):

1. `ps-challenge-site`: expression `(http.host in {"portfoliosight.ai" "www.portfoliosight.ai"}) and not any(http.request.headers["x-ps-gate"][*] == "<PS_GATE_SECRET>")` → action **Managed Challenge**.
2. `ps-block-api-direct`: expression `(http.host eq "api.portfoliosight.ai") and not any(http.request.headers["x-ps-gate"][*] == "<PS_GATE_SECRET>")` → action **Block**.

Rate-limiting rule (Free plan, 1 rule): `ps-tensor-post`, expression `(http.host eq "portfoliosight.ai" and http.request.method eq "POST" and starts_with(http.request.uri.path, "/api/tensors"))`, 5 requests per 10 s per IP, action Block for 10 s. The Worker's upstream subrequests carry the header and pass rule 2; browsers never send the header and get the Managed Challenge on first visit (Cloudflare's own interstitial), after which the `cf_clearance` cookie covers the page and its same-origin `/api/*` fetches. Playwright smoke tests set `extraHTTPHeaders: {"x-ps-gate": process.env.PS_GATE_SECRET}` and pass both rules; the "unexempted request is challenged" test issues a plain `GET /` without the header and expects HTTP 403 with response header `cf-mitigated: challenge`, and a plain `GET https://api.portfoliosight.ai/v1/health` without the header and expects 403 without that header (block). The API token in `~/.secrets/portfoliosight.env` currently lacks Zone WAF permissions (rulesets listing returns "Authentication error"), so the rules are created in the dashboard or after the owner adds `Zone › Zone WAF › Edit` to the token; the secret is generated once (`openssl rand -hex 24`), stored in `~/.secrets/portfoliosight.env` as `PS_GATE_SECRET` on the laptop (for smoke tests and `wrangler secret put`), and never committed. The KS-001 copy of the file does not need it.

### 9.5 Deployment checklist order

1. R2: create the bucket `portfoliosight-data` (`wrangler r2 bucket create portfoliosight-data` with the account token, or the dashboard), then run `python -m portfoliosight.data.store --verify` from the laptop: `head_bucket`, put/get/delete of `meta/_probe`, and a list of the bucket. If it fails with 403, the R2 keys in `~/.secrets/portfoliosight.env` are scoped to other buckets: the owner creates a new R2 API token in the dashboard (R2 › Manage R2 API Tokens › Object Read & Write, bucket `portfoliosight-data` only) and replaces the two keys. Nothing else proceeds until the verify passes.
2. Seed from the laptop (`scripts/seed_r2_from_lake.py`, §5.4); verify `meta/manifest.json` lists ≥ 1,400 symbols with `source: seed`.
3. KS-001: clone, `~/.secrets/portfoliosight.env`, compose up, `curl 127.0.0.1:8010/v1/health`; `measure-limits`, then catch-up (`docker compose -f deploy/docker-compose.yml run --rm api python -m portfoliosight.data.download --mode catch-up`, resumable over nights); first preset build (`python -m portfoliosight.jobs.nightly --presets-only`).
4. Tunnel ingress + DNS CNAME; verify `curl -H "x-ps-gate: $PS_GATE_SECRET" https://api.portfoliosight.ai/v1/health`.
5. WAF rules + rate limit rule; verify the direct API call is blocked without the header.
6. Worker deploy with secret and R2 binding; verify `GET /api/presets` is served from R2 (response header `x-ps-source: r2`, set by the Worker; `origin` for forwarded responses) and the page loads through the challenge in a real Chrome and via Playwright with the header.
7. Nightly cron confirmed by the next `meta/status.json`; first laptop backup run (`scripts/r2_backup.sh`) and the directory `/mnt/d/portfoliosight-data/` populated.

## 10. Testing strategy

- Python: `ruff check . && ruff format --check . && pyright .` clean; `pytest --cov=portfoliosight --cov-report=term-missing` with ≥ 80% line coverage overall and 100% on `portfoliosight/engine/` (math core). Tests in `tests/` mirror the package. All seeded; no network except tests marked `live` (skipped unless `PS_LIVE_TESTS=1`; they are the data gate). Fixtures: a synthetic 8-fund return matrix with known moments (`tests/fixtures/synthetic_returns.parquet`, generated by a seeded script in `scripts/`) and a 40-day slice of real VTI/VBIAX/SGOV/TSP data committed under `tests/fixtures/` for the returns tests.
- Engine property tests: frontier `y` non-decreasing in `x`; every weight vector respects bounds and sums to 1 ± 1e-6; `Z` non-increasing in `Y` within a column and non-decreasing in `X` within a row (±1e-6); `y_div ≤ y_star ≤ y_front`; ENB tests of §4.6; adjClose cross-check of §4.1; determinism (two builds identical); runtime budget of §4.12 on a 23-fund fixture (asserted ≤ 30 s on CI hardware, ≤ 60 s allowed).
- API tests (`TestClient`, `LocalStore` in a temp dir): every row of the table in §6 including 202 → 200 transitions, 400 unknown symbols, 422 cases, 503 queue full, ETag/Cache-Control headers, hash stability, atomic writes.
- Data tests: provider adapters against recorded JSON responses (`responses`/`respx`), budget ledger (hour/day/month stop and resume), manifest resume, TSP CSV parsing with the exact header, exclusion rules of §4.2 and §5.6 including the tail-gap rule, seed conversion on a three-symbol fixture lake (`tests/fixtures/lake/`) including the `adjusted_through` assertion and `dist_yield_12m`, splice continuity, the store interface against `moto`'s S3 mock (R2 is S3-compatible) and `LocalStore`, cache eviction at the cap, `.dockerignore` assertion (build the image in CI with `docker build` if available, else a unit test over the ignore rules).
- TypeScript: `npm run lint && npm run typecheck && npm test` (vitest): fidelity tests of §4.11 against the fixture tensor, URL codec round-trips, reducer transitions, diversification word mapping, six-month range, stress aggregation with partial coverage, theme token presence for all three themes.
- Production smoke tests: Playwright (`web/e2e/smoke.spec.ts`), `npx playwright test --config web/e2e/playwright.config.ts`, projects `chromium-desktop` (1366×900) and `chromium-phone` (Playwright "iPhone 13" descriptor), base URL `https://portfoliosight.ai`, header `x-ps-gate` from `PS_GATE_SECRET`. One test per definition-of-done item in §11, named `DoD-NN`. Screenshots of the first screen per theme and viewport are saved as artifacts. `data-testid`s: `chart`, `chart-canvas`, `risk-slider`, `risk-readout`, `set-by-toggle`, `div-slider`, `div-reset`, `point-selected`, `point-current`, `point-div`, `range-low`, `range-typical`, `range-high`, `div-word`, `details-toggle`, `details-enb`, `theme-switch`, `preset-menu`, `chip-funds`, `chip-trades`, `chip-stress`, `chip-settings`, `section-funds`, `section-trades`, `section-stress`, `section-settings`, `fund-row-{ID}`, `fund-add`, `use-menu`, `building-notice`, `excluded-note`, `lookback-{id}`, `ghost-{id}`, `cap-max-{ID}`, `caps-reset`, `stress-{id}`, `share-link`, `disclaimer`, `footer-cta`.

## 11. Definitions of done (each has one smoke test unless marked unit/API)

1. `https://portfoliosight.ai/` loads in Chrome through Cloudflare's Managed Challenge; with the `x-ps-gate` header Playwright gets HTTP 200 and sees `chart-canvas` within 5 s.
2. A plain request without the header to `/` returns 403 with `cf-mitigated: challenge`; a plain request to `https://api.portfoliosight.ai/v1/health` returns 403 without that header; the same with the header returns 200 JSON.
3. First screen on desktop shows chart, risk slider, diversification slider, result strip and chips with no table, trade list or stress card visible; all four sections are collapsed (`aria-expanded="false"`).
4. First screen on the phone viewport fits: no horizontal scroll (`document.documentElement.scrollWidth <= innerWidth`), chart, both sliders, result strip and chips are within the first 1.2 viewport heights, touch targets ≥ 44 px.
5. Default view is the "2017 guide, Step 2" preset with its allocation: `point-current` is visible, Funds section lists 23 rows with amounts filled for 18, and FIENX shows the note "converted to an ETF; no data since 2024-10-30".
6. No tangency/max-Sharpe point and no "Sharpe", "bets", "knee" text anywhere in the default DOM (details off).
7. The heatmap renders: sampling the canvas at 20 points inside the feasible region yields ≥ 3 distinct colors from the theme's ramp; infeasible region (above the frontier) is the page background.
8. Dragging `risk-slider` changes `risk-readout`, moves `point-selected` horizontally, and updates Low/Typical/High; readout under "Bad six months" is negative and under "Typical six months" is the mean; toggling `set-by-toggle` keeps X unchanged.
9. The diversification slider defaults to the suggested position (`div-reset` hidden); moving it toward "More diversified" moves `point-selected` down the vertical line, never changes its x, and does not decrease `details-enb`; moving to the top reproduces the frontier point.
10. The diversification word is one of Good/Average/Fair/Poor, rendered at ≤ 14 px in the muted color, and the ENB number appears only after `details-toggle` is on (unit test for the mapping thresholds).
11. Presets: selecting "TSP: G, F, C, S, I" loads a five-fund tensor with max cap 60% shown in Settings; "TSP with L Funds" loads 16 funds with cap 25%; TSP presets have no `point-current` and no Trades section.
12. Custom menu: adding `VOO, BND, VNQ, SGOV` and clicking `use-menu` shows `building-notice` (unless already cached), then the chart updates within 120 s; adding an unknown ticker shows an inline error naming it; a 31st fund is refused with a message.
13. Trades: for the default preset, Trades lists every held fund with now/selected/change columns and a turnover total; entering "$" amounts shows dollar changes; clearing all amounts hides the section.
14. Caps: editing `cap-max-VTI` to 10 triggers a rebuild and the resulting frontier weights for VTI never exceed 10% (checked via the API tensor); `caps-reset` restores the rule.
15. Lookbacks: switching to `10y` redraws the frontier and lists VWOB (history from 2013) as excluded; toggling `ghost-1y` draws a second thin frontier (SVG path count increases by one).
16. Stress cards show three windows with numbers for the default preset, each with a coverage note when < 100% of the mix existed; a mix of funds absent in 2008 (e.g. SGOV + VTIP) shows "Not enough of this mix existed then to say" on the 2008 card.
17. Themes: the switcher cycles ks-dark → light → hud; `html[data-theme]` changes, `--bg` computed values equal the table in §3.5, the canvas repaints (sampled pixel changes), and the choice survives reload; `t=hud` in the URL wins over storage.
18. HUD contains no film/character/trademark references (grep over `web/src`, copy and docs returns nothing beyond the word "HUD").
19. URL: after changing preset, lookback, slider and theme, the address bar contains `u`, `lb`, `loss`, `d`, `t`; opening that URL in a fresh context reproduces the same `risk-readout`, `div-word` and theme.
20. Disclaimer text of §3.7 is present and visible; the footer CTA links to the three family URLs; the result strip shows "Historical math, not investment advice."
21. API: `GET /v1/health` reports `asof_age_days ≤ 4` and `presets_ready: true`; `GET https://portfoliosight.ai/api/presets` lists the three presets with all six lookbacks `ready` and carries `x-ps-source: r2`; `GET /api/tensors/{hash}/5y` for the default preset validates against `tensor.schema.json`, carries `Cache-Control: public, max-age=86400, immutable` and `x-ps-source: r2`.
22. Data gate (live test, run before any other phase ships): the configured provider returns ≥ 250 daily rows with non-zero `div_cash` somewhere and a `split_factor` column for one ETF (VTI) and one mutual fund (VBIAX); the adjClose cross-check passes; `download --mode measure-limits` has run and `meta/provider_limits.json` records the measured tier, limits, method and date, and the downloader is observed (unit test with a fake clock) to stop at those limits; with `PS_PRICE_PROVIDER=tiingo` no request to `eodhd.com` is made (asserted by the recorded-HTTP tests).
23. Nightly: `meta/status.json` in R2 shows a run finished within the last 30 h with zero errors, and `tensors/` in R2 contains the 18 preset files with today's or yesterday's `asof`; the KS-001 cache volume is ≤ 300 MB (`du` over ssh).
24. Engine fidelity: TypeScript `stats(w)` matches the tensor at every grid node to 1e-6 (unit); determinism and budget tests pass (unit).
25. Container hygiene: the deployed image contains no `runs/` and no `data/holdings/` file other than `holdings_guide2017_step2.csv` (`docker run --rm image find /app -path '*holdings*' -o -path '*runs*'` lists only that file); no secret string from `~/.secrets/portfoliosight.env` appears in the image, the repo, or the built site bundle.
26. Quality gates: Python lint/type/coverage and TypeScript lint/typecheck/tests pass on `main`; every production smoke test passes from the laptop in Chrome against `https://portfoliosight.ai`.
27. ROADMAP.md carries Appendix B's additions; README.md describes the new layout, commands, storage (R2 primary, `/mnt/d/portfoliosight-data` backup, lake working copy on the WSL disk) and deployment in ≤ 60 lines, and no longer names `/mnt/d` as the lake location.
28. Store gate (live, run first in Phase 4): `python -m portfoliosight.data.store --verify` succeeds against `portfoliosight-data`; the seed has ≥ 1,400 `source: seed` symbols; `scripts/r2_backup.sh` mirrors the bucket to `/mnt/d/portfoliosight-data/` and a dry-run `--restore` reports zero files to upload.
29. Disclosure: for a custom menu containing a seeded stock whose tail is not yet refreshed, the details view shows the "distributions through …" line, and the 1-year lookback lists it as excluded when the tail-gap rule says so (unit test of the rule with the three examples in §5.6).

## 12. Build phases (dependency order; each phase has its own branch and PR)

Each phase is done by a fresh agent with only this spec and the repo. Phases 0 and 1 can run in parallel; Phases 2 and 3 can run in parallel once Phase 1's tensor fixture is merged; Phase 4 follows 2 and 3; Phase 5 follows 4.

**Phase 0: data layer and gate** (`feature/data-layer`). Deliver: `pyproject.toml` rewritten (core deps numpy, pandas, pyarrow, scipy, scikit-learn, cvxpy, clarabel, requests, pydantic; extras `api` = fastapi, uvicorn, slowapi; `research` = yfinance, matplotlib, plotly, skfolio; `dev` = pytest, pytest-cov, ruff, pyright, responses); `portfoliosight/data/` (providers base/tiingo/eodhd/tsp, store with `R2Store`/`LocalStore` and `--verify`, cache, returns/splice, manifest, budget, limits, download CLI with `measure-limits|catch-up|refresh`); `scripts/seed_r2_from_lake.py`, `scripts/r2_backup.sh`; `data/universes/tiers.json`, `data/universes/portfoliosight.txt` (Appendix A, with `income` tags), `data/universes/qse_core.txt` (copied from QSE, 1,038 lines), `data/presets.json`; live gate tests; unit tests. Done when: DoD 22 and 28 pass live from the laptop (including `measure-limits`, the recorded tier, the R2 verify and a `--dry-run` of the seed over the real lake); `download --mode catch-up --symbols VTI,VBIAX,SGOV,TSP-G` against `LocalStore` writes parquet + manifest; budget stop/resume tests pass (hour, day, monthly unique symbols); the priority walk stops at the budget and resumes; splice and tail-gap tests pass; lint/type/coverage gates pass.

**Phase 1: engine** (`feature/engine`). Deliver: `portfoliosight/engine/` (stats, torsion, optimize, surface, bootstrap, stress, caps, tensor builder + schema), `scripts/build_tensor.py` (CLI: universe file or preset → JSON), the fixture `web/fixtures/guide2017_5y.json` built from the synthetic fixture or, if Phase 0 data exists, real data. Done when: all §4 tests pass with 100% engine coverage; a 23-fund build runs ≤ 30 s; schema validates; byte-identical rebuild.

**Phase 2: API and container** (`feature/api`). Deliver: `portfoliosight/api/` (app, queue, presets, limiter), `portfoliosight/jobs/nightly.py`, `deploy/` (Dockerfile, compose, crontab), `.dockerignore`, `scripts/deploy_ks001.sh`. Done when: §6 table tests pass against `LocalStore` and against `moto`; `docker compose -f deploy/docker-compose.yml up` locally (with `PS_STORE=local` and a small fixture store) serves `/v1/health` and builds a custom tensor end-to-end; the cache never exceeds its cap; hygiene test (DoD 25) passes locally.

**Phase 3: front end** (`feature/web`). Deliver: `web/` per §8 against the fixture tensor via a vite dev proxy or a static mock of `/api/*`; three themes; all controls, sections, URL state, compliance copy, data-testids. Done when: `npm run lint && npm run typecheck && npm test` pass; a local Playwright run of the §11 tests that do not need production (3–10, 13, 17–20 with the mock) passes against `vite preview`.

**Phase 4: production deployment** (`feature/deploy` for code; the infra steps are executed by the agent over ssh and the Cloudflare API where the token allows, otherwise written as an exact runbook for the owner in `docs/plans/2026-10-13-ks001-cloudflare-runbook.md`). Deliver: §9.5 in order: bucket and R2 verify, seed upload, KS-001 container, limits measured, catch-up started, presets built, tunnel and DNS, WAF and rate-limit rules, Worker with R2 binding live, nightly scheduled, first backup. Done when: DoD 1, 2, 21, 23, 28 pass against production.

**Phase 5: smoke tests and docs** (`feature/smoke`). Deliver: `web/e2e/` with one test per DoD item, `scripts/smoke.sh`, README and ROADMAP updates (Appendix B). Doc fix included: README.md's Data section currently names `/mnt/d/tft-quantile-forecaster/...` as the lake location; rewrite it to name the WSL working copy `~/tft-quantile-forecaster/data/tft/raw/eodhd/datalake_us_core/` (with `/mnt/d` described as QSE's nightly mirror), and replace the EODHD/Schwab/yfinance guidance with this spec's provider, seed and R2 design. Done when: DoD 1–27 all pass from the laptop; the worktrees and merged branches are cleaned per the owner's cleanup script.

Conventions for every phase: TDD (failing test first); no stubs, no TODOs; tests in `tests/` and `web/tests/`, scripts in `scripts/`; remote `github`; feature branch + PR for code, docs straight to `main`; secrets only via `~/.secrets/portfoliosight.env` (never `qse.env`, never committed); no EODHD call unless `PS_PRICE_PROVIDER=eodhd`; `ruff`/`pyright`/`pytest --cov` and `npm run lint && npm run typecheck && npm test` before the PR.

## 13. Risks

- **Data license**: Tiingo's listed Starter/Power plans are "internal use only"; displaying derived figures publicly needs a license check (and possibly the $50/month internal-commercial or a redistribution quote) before any real launch. The demo proceeds; the footer credits Tiingo and tsp.gov.
- **Provider plan limits**: the Tiingo key's tier is unverified (no usage endpoint, no rate-limit headers); the design assumes Starter until `measure-limits` says otherwise. On Starter, tier 2 catch-up takes one to two nights, the nightly refresh about 7.5 hours, and tier 3 (QSE stocks) is served from the seed with price-only tails that close at about 110 symbols per month; a 429 stops the downloader until the next hour. Power ($30/month) serves all three tiers in minutes. Mitigation: `provider_limits.json`, budget ledger, tier ordering, resumable manifest, picker limited to downloaded symbols.
- **Mutual-fund coverage**: verified for VTSAX, VBIAX, VGSTX, FXAIX, SWTSX; some curated tickers may 404 and are simply marked unavailable. FIENX was converted to an ETF and shows as excluded in the default preset by design.
- **tsp.gov**: the CSV requires a browser-like User-Agent and may change format; the parser asserts the exact header and the nightly marks TSP stale (not failed) if the fetch breaks.
- **Proxy vs. exact measure**: the surface is built with weight Herfindahl and displayed as exact ENB, so the heatmap is a lower bound of achievable diversification; good enough for the demo, stated in details.
- **Bootstrap cost**: 4,800 solves per lookback; if a 30-fund build exceeds 30 s on KS-001, reduce `B` to 50 before touching anything else.
- **KS-001 memory**: 1.5 GB limit per container; a build loads at most 30 symbols (< 10 MB) and the nightly streams one symbol at a time; cvxpy problems are tiny. Shared with production KnowledgeSight services; the nightly runs at 02:00 PT when they are idle.
- **Managed Challenge on phones**: some visitors see an interstitial; accepted by the owner. If Cloudflare changes the `cf-mitigated` header, DoD 2 is adjusted, not the gate.
- **Workers Free quota**: 100k requests/day; a demo will not approach it; tensor responses are edge-cached for a day.
- **Cloudflare token scope**: WAF rules may have to be created in the dashboard; tunnel ingress needs sudo on KS-001 (owner's hands); the R2 keys may be scoped to other buckets (§9.5 step 1 says what the owner does).
- **Seed quality**: the lake's `adj_close` is trusted as EODHD's back-adjustment through 2026-02-27; the seed script's assertion and the VTI splice test are the only checks. Symbols whose seed history looks wrong are fixed by deleting their R2 object and letting catch-up refetch them in full from the provider (one request each).
- **R2 as a single point of truth**: a lost bucket is restored from `/mnt/d/portfoliosight-data/` with `scripts/r2_backup.sh --restore`; between backups, at most the nightly deltas since the last mirror are lost and are refetched by the next refresh.

## Appendix A: served universe by tier

Tier 1 (presets): the 23 Step 2 symbols (AGG BND DBJP EDV FIENX LQD LTPZ PCY SCHF SCHO TIP VB VBIAX VBR VEA VGSTX VNQ VOE VTI VTIP VTV VWO VWOB) and the 16 TSP funds listed at the end. Tier 3: `data/universes/qse_core.txt`, the 1,038-line copy of QSE's `datalake_us_core.txt` (large-cap US stocks; not reproduced here; seeded from the lake). Tier 2 (`data/universes/portfoliosight.txt`, 313 symbols; the whole "Bond ETFs" group and the mutual funds VBTLX VBMFX VBILX VBIRX VBLAX VSIGX VSCSX VTAPX VIPSX VWEHX VWINX FXNAX FTBFX FUAMX FIPDX SWAGX SWRSX DODIX PTTAX PTTRX PONAX MWTRX BCOIX LSBDX carry the `,income` tag):

US equity ETFs: VTI VOO SPY IVV SCHB ITOT SPTM VV SCHX IWB VUG VTV IWF IWD SCHG SCHV VO IJH MDY SCHM VOE VOT IWR VB IJR IWM SCHA VBR VBK VXF RSP QQQ QQQM DIA VIG SCHD DVY VYM HDV SDY NOBL DGRO USMV SPLV MTUM QUAL VLUE IWN IWO IWS IWP AVUV AVUS DFUS DFAC
Sector and real estate ETFs: XLK XLF XLV XLE XLI XLY XLP XLU XLB XLRE XLC VGT VHT VFH VDE VNQ SCHH IYR USRT VPU VDC GDX
International equity ETFs: VEA VXUS IXUS SCHF IEFA EFA VWO IEMG EEM SCHE VGK VPL EWJ DBJP HEDJ VSS SCZ IDV VYMI DFAX AVDV AVEM SCHC EFV EFG ACWI VT VEU IOO URTH FNDF FNDE
Bond ETFs: BND AGG SCHZ BNDX BNDW BIV BSV BLV VCIT VCSH VCLT LQD IGSB IGIB IGLB HYG JNK SHYG USHY VGSH VGIT VGLT SHV SGOV BIL SHY IEI IEF TLH TLT EDV ZROZ GOVT SCHO SCHR SCHQ SPTL SPTS TIP VTIP SCHP STIP LTPZ TIPX MUB VTEB SUB HYD EMB PCY VWOB EMLC IAGG IGOV BWX FLOT USFR TFLO MBB VMBS SRLN BKLN CWB PFF FALN ANGL
Commodity, alternative and allocation ETFs: GLD IAU SGOL SLV PDBC DBC GSG USO VNQI REET IGF AOA AOR AOM AOK NTSX SWAN
Vanguard mutual funds: VTSAX VTSMX VFIAX VFINX VIMAX VSMAX VVIAX VIGAX VTIAX VGTSX VTMGX VEMAX VBTLX VBMFX VBILX VBIRX VBLAX VSIGX VSCSX VTAPX VIPSX VWEHX VWINX VWELX VBIAX VGSTX VTINX VTTVX VTHRX VTTHX VFORX VTIVX VFIFX VFFVX VTTSX VLXVX VSVNX VGSLX VDIGX VWIAX VWIGX VWUSX VPMCX VHCAX VEXAX VMVAX VSIAX VSGAX VTMSX VFSVX VGAVX
Fidelity mutual funds: FXAIX FSKAX FZROX FNILX FSMAX FSSNX FSPSX FTIHX FZILX FPADX FXNAX FTBFX FUAMX FIPDX FBALX FPURX FFNOX FFFCX FFTWX FFFEX FFTHX FFFFX FFFGX FFFHX FDEEX FDKVX FCNTX FMAGX FLPSX FDGRX FBGRX FOCPX FSELX FSPGX FLCOX FIENX FSRNX
Schwab mutual funds: SWTSX SWPPX SWLGX SWSSX SWMCX SWISX SWAGX SWRSX
Other 401(k) staples: PRGFX PRWCX PRFDX TRBCX RPMGX AGTHX AIVSX AWSHX ANWPX AEPGX CAIBX ABALX AMECX ANCFX CWGIX SMCWX DODGX DODFX DODIX DODBX OAKMX OAKIX PTTAX PTTRX PONAX MWTRX BCOIX LSBDX FKINX
TSP (from tsp.gov, not the provider): TSP-G TSP-F TSP-C TSP-S TSP-I TSP-LINC TSP-L2030 TSP-L2035 TSP-L2040 TSP-L2045 TSP-L2050 TSP-L2055 TSP-L2060 TSP-L2065 TSP-L2070 TSP-L2075

Unknown, converted or closed symbols are tolerated in every tier: the manifest marks them `unavailable` with the reason and they are not served.

Presets (`data/presets.json`): `guide2017` = the 23 symbols of `data/holdings/holdings_guide2017_step2.csv` with amounts = Qty × Price (dollars; 18 held, 5 universe-only at 0); `tsp5` = TSP-G, TSP-F, TSP-C, TSP-S, TSP-I, no allocation; `tsp16` = all 16 TSP funds, no allocation.

## Appendix B: ROADMAP additions (written in Phase 5)

- Paid tier: more than 30 funds per portfolio, and tickers outside the downloaded universe fetched on demand, behind a small annual paywall.
- Data license and tier 3: upgrade the price provider plan (Tiingo Power or internal-commercial, or EODHD with prices) and obtain written display/redistribution terms before marketing the site; switching providers is one config value. On a Power-class plan the nightly job serves tier 3 (QSE core stocks) without code changes.
- Out of scope for the demo and parked: FERS planner (Phase 2b), risk questionnaire / risk number, hedge/collar calculator, emails, programmatic SEO pages, payments, accounts/login, copula Monte Carlo, Student-t toggle, image export, walk-forward UI, robustness score, ENB-exact (non-convex) refinement of the surface.
