# PortfolioSight demo: design spec

Date: 2026-10-13, revision 2 (after Codex review round 1). Status: approved for build. Owner: Jeff Daniels. Repo: `github:automateintelligence/portfoliosight`.
Inputs: `docs/reviews/2026-10-12_strategy_memo_portfolio_risk_return_website.md`, `..._addendum_user_feedback_and_decisions.md`, the six research reports, the owner's brainstorm decisions (final). The memo and addendum are historical context; where they differ from this spec, this spec is authoritative. This spec is consumed by an Expectations section (written afterwards), executable assertions, and an autonomous multi-phase build where each phase is done by a fresh agent with no memory. Every choice here is final unless a phase proves it impossible, in which case the phase reports and stops.

Owner's framing: "This is really not that complicated of a project, so don't over-complicate it. Build it out as a demo. If you build it wrong, we will fix it later. The goal is speed balanced with good econometrics and great website design and aesthetics."

## 1. Purpose and audience

A public page at `https://portfoliosight.ai`. A visitor sees a fund menu's efficient frontier, where a current mix sits against it, drags a risk slider, and gets a better-diversified mix at the same risk ceiling. Audience: people with a 401(k)/TSP/brokerage fund menu (NAVSEA/TSP friends first, Bogleheads-adjacent generally). Educational, impersonal, not advice. No login; the only gate is Cloudflare's standard human check.

## 2. Decisions and non-goals

Decided by the owner (not revisited here): first screen is the chart and its controls, everything else collapsed; no tangency/max-Sharpe point; risk slider = six-month 95% loss estimate; a diversification control along the constant-risk-ceiling line defaulting to a suggested point; a diversification-surface heatmap under the frontier as the centerpiece; diversification in four plain words; presets (2017 guide Step 2 with allocation; TSP core funds) plus custom portfolios of up to 30 funds from the served universe; trade list; adaptive caps; lookbacks 1/2/3/5/10y + exponentially weighted with ghost frontiers; three stress cards; three themes (KnowledgeSight dark default, own light, HUD); plain-language layer; URL-encoded portfolios; Portfolio-Visualizer-style disclaimers; family footer CTA; backend precomputes, browser only interpolates; FastAPI container on KS-001 behind the existing cloudflared tunnel; Vite + React + TypeScript + D3 on Cloudflare Workers static assets; Cloudflare WAF Managed Challenge as the gate.

Data decisions (2026-10-13, owner-confirmed): the EODHD subscription does not include prices, dividends or splits, so the product uses **Tiingo** behind a small provider Protocol (one adapter; a second can be added later); no yfinance, no Schwab, no EODHD calls. The owner's QSE lake (working copy on the laptop's WSL disk at `~/tft-quantile-forecaster/data/tft/raw/eodhd/datalake_us_core/eod_history`, 1,445 symbols with back-adjusted `adj_close` through 2026-02-27; `/mnt/d/tft-quantile-forecaster` is only QSE's nightly mirror and may be unmounted) is used once as a **seed**, uploaded from the laptop; QSE's own storage layout is not changed. **Cloudflare R2 is the canonical store** (bucket `portfoliosight-data`), the laptop drive `/mnt/d/` is the backup, and the KS-001 container is stateless apart from a 300 MB cache; KS-001's disk will not be expanded. Secrets live in `~/.secrets/portfoliosight.env`. Production ingestion of provider data into R2 requires the owner's confirmation of a provider plan whose terms allow storing the data and derived outputs (§13, §9.5 step 3); writing the code does not.

Choices made in this spec where the owner left them open are marked **[choice]** with a one-line reason.

Non-goals (ROADMAP only, see Appendix B): FERS planner, risk questionnaire / risk number, hedge/collar calculator, emails, programmatic SEO pages, payments/paywall, accounts/login, copula Monte Carlo, Student-t toggle, image export, walk-forward UI, robustness score, more than 30 funds, tickers outside the served universe, exact-ENB (non-convex) optimization, a second price provider, a TSP preset with L Funds.

## 3. User experience

### 3.1 First screen

One viewport, no scrolling needed to use the product. Layout (desktop ≥ 1024 px):

```
┌ header: wordmark "PortfolioSight"  [preset ▾]  [theme ◐] ───────────────────┐
│ ┌ chart (D3; canvas heatmap+frontier, SVG markers) ───────┐ ┌ div slider ┐ │
│ │  y: expected return (yr)                                  │ │ More return│ │
│ │  heatmap Z(risk ceiling, return floor) under the frontier │ │     ●      │ │
│ │  frontier line; vertical risk-ceiling line at X; point ●  │ │            │ │
│ │  current mix ◻ (if an allocation exists); ○ most diversif.│ │ More       │ │
│ │  x: risk (yearly ups and downs)                           │ │ diversified│ │
│ └───────────────────────────────────────────────────────────┘ └────────────┘ │
│  risk slider  [Set by: Bad six months | Typical six months]                 │
│  ◄──────────────────●──────────────────────►  "In a bad six months: −9.4%"   │
│  result strip: Low −9.4%  ·  Typical +3.1%  ·  High +15.6%   Diversification: Good   [details] │
│  chips: [Funds & amounts] [Trades] [Stress tests] [Settings]  (scroll to the collapsed sections) │
└──────────────────────────────────────────────────────────────────────────────┘
```

Chart contents, in draw order: (1) heatmap of Z over the grid of (risk ceiling, return floor) cells (canvas; each cell is drawn at its grid position and colored by the ENB of the mix computed for that ceiling/floor pair); (2) ghost frontiers (thin, 40% opacity, one per toggled lookback); (3) primary frontier (2 px); (4) vertical dashed line at the selected risk ceiling X from the axis to the frontier; (5) "most diversified" marker (small hollow circle) at the actual (σ, μ) of the column's most-diversified mix; (6) current-mix marker (hollow square) at its actual (σ, μ) when an allocation exists; (7) selected-point marker (filled circle with ring) at the selected mix's **actual** (σ, μ), which lies on or to the left of the ceiling line and on or below the frontier, draggable (vertical drag = diversification slider, horizontal drag = risk slider); (8) individual fund dots with ticker labels only when details are on. **[choice]** Every mix is plotted where it really is and the line marks the ceiling (a small leftward drift is visible and explained in the tooltip), because re-parameterizing the grid on realized risk would cost a second solve pass for no product gain. No tangency point, no capital market line, no Sharpe anywhere. Tooltip on hover/tap of the selected point: Low/Typical/High, diversification word, "risk ceiling X · this mix σ", top five weights; with details on, hovering a heatmap cell shows its mix's actual σ and μ.

### 3.2 Controls

- **Preset menu** (header): "2017 guide, Step 2" (default), "TSP (G, F, C, S, I)", "Custom…" (opens the Funds section).
- **Risk slider** (horizontal, under the chart). Its parameter is the frontier risk ceiling X over the domain `[X_safe, X_max]` (§4.9). Readout label: "Best-return mix at this risk, in a bad six months: −9.4%" (or "…in a typical six months: +3.1%" under the *Set by* toggle). The readout describes the **frontier** mix at X; the result strip describes the **selected** mix, which may differ once the diversification slider moves it. Both toggle positions drive the same parameter X; the toggle changes only the label and number on the thumb. Keyboard: arrow keys move 1/200 of the domain. If the domain collapses to a single point the slider is disabled with "this menu has only one sensible risk level".
- **Diversification slider** (vertical beside the chart on desktop, horizontal under the risk slider on phone). End labels "More return" (top/left) and "More diversified" (bottom/right). No percentages, no numbers, never the word "knee". It moves the selected point along the column at ceiling X between the frontier mix (top) and the column's most-diversified mix (bottom). Default position is the suggested point (§4.8), marked with a small tick on the track; a "Reset to suggested" link appears once the user moves it.
- **Result strip**: Low / Typical / High six-month return of the selected mix (estimated central 95% range, §4.9), the diversification word (small, muted, not a headline), and a **details** toggle. Details on: the exact measure ("spreads risk over the equivalent of 3.8 independent bets; highest found on this menu: 5.1"; technical name "effective number of bets, minimum torsion"), yearly expected return and standard deviation of the selected mix, the risk ceiling, lookback dates, "prices through {asof}", fund dots on the chart, and the method footnote.
- **Theme switcher** (header): three-way segmented control, KnowledgeSight dark (default) / Light / HUD; persisted in `localStorage("ps.theme")`; the URL `t=` parameter wins over storage.
- **"Give us a moment"**: while a custom tensor builds, the chart area shows a centered notice with a progress ring and the queue position; controls are disabled; polling every 2 s. A failed build shows "We couldn't compute this menu" with a Retry button (re-POSTs the same request) and the server's error code; after three failures the notice says so and offers the presets. If any `/api/*` response carries `cf-mitigated: challenge`, the page keeps its state in the URL and performs a top-level reload so Cloudflare's interstitial can run, then resumes (builds are idempotent by generation, hash and lookback).

### 3.3 Collapsed sections (below the first screen, all collapsed by default)

Accordion sections in this order; chips on the first screen scroll to and expand the matching section. **[choice]** Sections further down the page rather than a drawer: one implementation works on every width and keeps the first screen clean.

1. **Funds & amounts**: table of the menu: ticker, name, amount entered (number; unit toggle "%" or "$"), status note (e.g. "converted to an ETF; no data since 2024-10-30: not used"). Add fund (autocomplete over `/api/symbols`, which lists only served symbols; help text "Only funds and stocks with verified current data are offered."), remove fund, "Use this menu" button (triggers tensor fetch/build). Max 30 funds; min 2. Amounts are optional; blank means no current mix. The preset "2017 guide" arrives with amounts filled from `data/holdings/holdings_guide2017_step2.csv` (Qty × Price); the TSP preset arrives blank. TSP L Funds are served and appear in the picker but are not a preset.
2. **Trades**: shown only when a current mix exists. Per fund: now %, selected %, change in percentage points, and dollars if "$" amounts were entered. Totals: one-way turnover. Copy: "Moves to get from the mix you entered to the selected mix."
3. **Stress tests**: three cards (§4.10).
4. **Settings**: lookback (radio: 1y, 2y, 3y, 5y (default), 10y, Weighted toward recent) with a list of funds excluded in that window and why; ghost frontiers (checkboxes per other lookback); caps table (min %, max % per fund, inline validation per §4.4, "Reset to default rule", one-sentence rule explanation); "Share this view" (copies the URL).

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
| y axis | "Expected return per year" | "Shrunk expected return (50/50 sample mean and menu-beta heuristic), annualized" |
| Heatmap legend | "How spread out the risk is" | "ENB (minimum torsion) of the computed mix at each risk ceiling / return floor" |
| Risk slider | "Best-return mix at this risk, in a bad / typical six months" | "2.5th percentile / mean of the frontier mix's six-month return, normal approximation" |
| Result strip | "Low / Typical / High over six months" | "Estimated central 95% range, normal, additive: μ/2 ± 1.96·σ/√2" |
| Diversification word | "Good / Average / Fair / Poor" | "ENB 3.8; highest found on this menu 5.1 (ratio 0.75)" |
| Diversification slider | "More return" ↔ "More diversified" | "Return floor along the column at risk ceiling X; bottom end = the column's highest-ENB computed mix" |
| Suggested marker | "Suggested" | "Lowest return floor whose give-up versus the frontier mix is within one standard error of the paired daily return difference (a heuristic, not a significance test)" |
| Frontier | "Best return at each level of risk" | "Long-only mean-variance efficient frontier with caps" |
| Ghost frontiers | "Same menu, different years of history" | "Frontier estimated over the 1y/2y/3y/10y/EW window" |
| Caps | "No single fund above 25% (menu of 23)" | "Editable default: max = max(0.25, 3/N)" |
| Excluded fund | "{FUND}: history starts {date}, not enough for the {window} view" (e.g. a fund launched in 2025 under the 3-year view) | — |
| Stress card | "What this mix did: −31% (2008 crisis)" | "Buy-and-hold with the selected weights, 2008-09-01 to 2009-03-09" |
| Stress gap | "2 of 18 funds (11% of the mix) didn't exist yet; result is for the rest." | — |
| Current mix | "The mix you entered" | — |
| Building | "Give us a moment: computing this menu (about 30 seconds)" | — |

Never in default copy: "bets", "knee", "Sharpe", "tangency", "covariance", "sigma", "quantile", "significant". Impersonal framing: "this mix", "the mix you entered", never "you should", "we recommend", or age/goal references.

### 3.7 Compliance copy

Under the result strip (12 px, muted): "Historical math, not investment advice." Footer disclaimer (always visible, not collapsed): "PortfolioSight is an educational tool. All figures are mathematical results computed from historical prices and are hypothetical; past performance does not predict future results. Nothing here is investment, tax or legal advice, and no output is a recommendation to buy or sell anything. PortfolioSight is not registered with the SEC, FINRA or any other regulator. You remain solely responsible for your decisions. Price data: Tiingo and tsp.gov." Footer CTA (generic, not keyed to the visitor's result): "More from the AutomateIntelligence family: Option Spread Scanner (https://option-spread-scanner.ingage-bd0.workers.dev), KnowledgeSight (https://automateintelligence.ai), SecuritySight (https://securitysight.ai)." No account linking, no human follow-up, no tracking beyond Cloudflare's own analytics.

## 4. Econometric method

All engine code lives in `portfoliosight/engine/` (pure functions over numpy arrays; no I/O). The seed `portfoliosight/frontier_cli.py` stays unchanged as the research baseline. Libraries: numpy, pandas, scipy, scikit-learn (`LedoitWolf`), cvxpy ≥ 1.5 with Clarabel. **[choice]** cvxpy+Clarabel rather than SLSQP: the risk constraint is second-order-cone, DPP-parametrized problems avoid re-canonicalization, and the surface needs about a thousand solves per lookback.

### 4.1 From prices to returns

Per fund the store holds the canonical record of §5.3: raw daily `close` and a total-return index `tr_index`; the engine's daily return is always `r_t = tr_index_t / tr_index_{t−1} − 1`. Provider rows are turned into index increments with `div_cash` (cash distribution per share on its ex-date, including fund capital-gain distributions as the provider reports them) and `split_factor` (Tiingo: new shares per old share on the split date, 1.0 otherwise):

```
r_t = (close_t · split_factor_t + div_cash_t · basis_t) / close_{t-1} − 1 ;   tr_index_t = tr_index_{t-1} · (1 + r_t)
```

where `basis_t = split_factor_t` if the provider quotes `div_cash` per post-split share on a day with both actions, else 1. The adapter fixes `basis` by reproducing the provider's `adjClose` (fetched alongside, used only for validation) on recorded fixtures: AAPL around 2020-08-31 (4:1 split), NVDA around 2024-06-10 (10:1), USO around 2020-04-29 (1:8 reverse split), VTI and VBIAX full history (dividends and fund distributions); the adjClose ratio must match the built `tr_index` ratio to within 1e-5 per day on every fixture, and an agent never guesses the direction. Seeded rows take `tr_index` from the lake's back-adjusted `adj_close` (§5.4). TSP funds: share prices are already total-return NAVs, so `tr_index` is the price itself. Splice test: for VTI, a seed-style record cut at 2025-12-31 and a provider tail spliced from there must match the all-provider `tr_index` to within 1e-5 from 2026-01-02 on. Trading-day alignment: the universe calendar is the union of all funds' dates; a fund's return is NaN on days it has no price; window statistics use the intersection of dates where every included fund has a return.

### 4.2 Lookback windows and short histories

`asof` = `D`, the most recent XNYS session (via `exchange_calendars`) whose close is at least 6 hours before the build starts; it does not depend on which funds are included. Window ids and lengths: `1y`=252, `2y`=504, `3y`=756, `5y`=1260, `10y`=2520 trading days ending at `D`; `ew` = the 5y window with exponentially decaying observation weights, half-life 252 days, applied by position. A fund is **included in a window** only if it is served (§5.2: price and corporate actions verified through `D − 3` trading days or later) and its first return date is on or before `window_start + 0.10 · window_length`. Excluded funds are listed in the tensor with a reason string and shown in the UI (§3.6). The window's sample is the intersection of included funds' dates; it must have ≥ 126 rows or the window is marked `unavailable` and the UI disables it with "not enough shared history". A current mix with weight in excluded funds is renormalized over included funds and the UI says what share was set aside.

### 4.3 Moments

- Annualization: `μ_i = 252 · mean(r_i)`, `σ_i = √252 · sd(r_i)` (sample, ddof=1). For `ew`: weights `ω_t ∝ 0.5^{(T−t)/252}` normalized to sum 1, `mean = Σ ω_t r_t`, `S = Σ ω_t (r_t − mean)(r_t − mean)ᵀ`, effective sample size `T_eff = 1/Σω_t²`.
- Covariance, fixed windows: `sklearn.covariance.LedoitWolf` on standardized returns `r_i/σ_i`; the estimate is renormalized to a correlation matrix (`R = Q / sqrt(diag Q diag Qᵀ)`) and rescaled: `Σ = D^{1/2} R D^{1/2}`, `D = diag(σ²)`. For `ew`: `R = corr(S)` shrunk with fixed intensity `R_s = 0.8 R + 0.2 I` (**[choice]** sklearn has no observation weights; a fixed intensity is adequate for a display window), then rescaled by `diag(S)`. **[choice]** Shrinking correlations rather than covariances so a near-zero-volatility fund (TSP G Fund, σ ≈ 0.3%/yr) keeps its own variance. Diagonal floor `σ_i ≥ 1e-4` (0.01%/yr) before any factorization.
- Expected returns, a **menu-beta heuristic** (**[choice]**, labelled as such): `μ_s = 0.5 · μ̂ + 0.5 · π`, `π_i = r_f + β_i · max(μ̂_eq − r_f, 0)`, `β = Σ w_eq / (w_eqᵀ Σ w_eq)`, `w_eq = 1/N`, `μ̂_eq = w_eqᵀ μ̂`. It scales each fund's premium by its beta to the equal-weighted menu, preserves the menu's average return (`w_eqᵀ π = w_eqᵀ μ̂` when the premium is positive), collapses to the cash rate when the menu's excess return is non-positive, and the 50/50 blend is an arbitrary fixed intensity. Inspired by the no-views Black-Litterman prior (He & Litterman 1999) and by Kritzman, Page & Turkington 2010 on not using the raw sample mean; it is not a calibrated posterior. A cash-like fund is pulled toward `r_f`, not toward the equity average.
- Risk-free rate: trailing-12-month total return of SGOV if served, else TSP G Fund, else 0.04. One value per build.
- Citations: Ledoit & Wolf 2004 (JMA 88(2)); Jagannathan & Ma 2003 (J. Finance 58(4)); DeMiguel, Garlappi & Uppal 2009 (RFS 22(5)).

### 4.4 Caps

Default per-fund bounds: `min = 0`, `max = clamp(3/N, 0.25, 1.0)` with N the number of funds included in the window; so a five-fund TSP menu allows 60% in one fund, a 10-fund menu 30%, any menu of 12 or more funds 25%, and two- or three-fund menus are uncapped. This is an editable demo heuristic: a weight cap `c` only bounds weight concentration (`Σ w_i² ≤ c`, the DeMiguel, Garlappi, Nogales & Uppal 2009 norm-constraint idea) and says nothing about minimum-torsion concentration; 3/N keeps small menus usable. Validation on input (422 and inline in Settings otherwise): `0 ≤ min ≤ max ≤ 1` per fund, `Σ min ≤ 1 ≤ Σ max`, N ≥ 2. Greedy endpoint portfolios (§4.5, §4.7) allocate every fund's minimum first, then fill the remainder in `μ_s` order up to each maximum. The universe hash (§6) covers the **requested** cap policy (per-fund overrides, `null` when default), not the window-resolved bounds; each tensor records the resolved `bounds` it used.

### 4.5 Frontier

Grid of `NX = 48` risk columns `X_j` uniformly from `σ_min` (risk of the minimum-variance portfolio under bounds) to `σ_max` (risk of the max-return greedy portfolio under bounds). Frontier point at `X_j`:

```
maximize μ_sᵀ w   s.t.  ‖C w‖₂ ≤ X_j,  1ᵀw = 1,  min ≤ w ≤ max,   C = cholesky(Σ)ᵀ
```

NumPy's `cholesky` returns lower `L` with `Σ = L Lᵀ`, so `C = Lᵀ` and `‖Cw‖² = wᵀΣw` (unit test on a random SPD matrix). Outputs `y_front[j]` and `w_front[j]`; for `X_j < σ_max` the risk constraint binds, so frontier mixes sit on the ceiling line. One cvxpy `Problem` with parameters `(μ, C, X)` reused for all solves.

### 4.6 Diversification measure and the four words

Measure: effective number of bets via minimum torsion (Meucci, Santangelo & Deguest 2015, "Risk budgeting and diversification based on optimized uncorrelated factors", SSRN 2276632). Port `torsion.m` (minimum-torsion, exact method, BSD) into `engine/torsion.py` as `min_torsion(Σ) -> T` (n×n, `T Σ Tᵀ` diagonal). Bet exposures, variance contributions and ENB for weights `w`:

```
b = T^{-T} w ;  Λ = diag(T Σ Tᵀ) ;  p_i = Λ_i b_i² / (wᵀ Σ w) ;  ENB(w) = exp(−Σ_i p_i ln p_i)  (p_i = 0 contributes 0)
```

`p_i ≥ 0` by construction; the builder asserts `max |offdiag(TΣTᵀ)| ≤ 1e-8 · trace` and `|Σp − 1| ≤ 1e-8` and raises otherwise (no silent clipping). Tests: diagonal Σ → `T = I`, inverse-volatility weights (`w_i ∝ 1/σ_i`) give `ENB = N`, and a single-fund portfolio gives `ENB = 1`; two uncorrelated funds with volatilities 10% and 20% at equal weight give `ENB = exp(−(0.2 ln 0.2 + 0.8 ln 0.8)) ≈ 1.649`; random SPD Σ → `TΣTᵀ` diagonal to 1e-8 and `Σp = 1`.

Words: `q = ENB(w) / enb_ref`, where `enb_ref` is the highest ENB among all mixes computed for this universe and lookback (frontier mixes and grid cells): "highest found on this menu", never "max" or "best possible". **[choice]** Good `q ≥ 0.75`, Average `0.50 ≤ q < 0.75`, Fair `0.30 ≤ q < 0.50`, Poor `q < 0.30`; relative to the menu's own reference because a five-fund TSP menu cannot reach the ENB of a 23-fund menu; the cut points are stated in the details footnote.

### 4.7 Diversification surface

Rows `NY = 32` return floors `Y_k` uniformly from `Y_min` (return of the lowest-`μ_s` greedy fill under bounds) to `Y_max = max_j y_front[j]`. Cell `(j, k)` is feasible iff `Y_k ≤ y_front[j]`. For each feasible cell, the convex proxy:

```
minimize ‖w‖₂²   s.t.  ‖C w‖₂ ≤ X_j,  μ_sᵀ w ≥ Y_k,  1ᵀw = 1,  min ≤ w ≤ max
```

gives `w[j][k]`, with `Z[j][k] = ENB(w[j][k])` evaluated exactly. Both constraints may be slack, so a cell's mix has actual `σ ≤ X_j` and `μ ≥ Y_k`; the heatmap therefore shows "ENB of the computed mix at each risk ceiling / return floor" and the chart draws every selected mix at its actual coordinates (§3.1). **[choice]** Weight Herfindahl (the DeMiguel 2-norm, Rényi-2 entropy) as the proxy: convex, a QP, and the memo's "Herfindahl of risk contributions" is not convex in `w`. Nested feasible sets make the optimized Herfindahl monotone across the grid; the exact ENB evaluated afterwards is **not** monotone and no monotonicity is promised or tested for it. Infeasible cells are `null`. Per column, the candidate set is the frontier mix plus the feasible cells; `k_div[j]` is the candidate with the highest ENB (ties → highest return), stored as `y_div[j]` (its return floor; `y_front[j]` when the frontier mix wins) and `w_div[j]`; by construction `ENB(w_div[j]) ≥ ENB(w_front[j])`. `enb_ref = max` over all candidates in all columns.

### 4.8 Suggested point on the column (standard-error heuristic)

For column `j`, walk the feasible cells downward from the frontier (`k` with `Y_k` just below `y_front[j]` down to `k_div[j]`). For each candidate `w_k`, form the paired daily return difference `d_t = (w_front[j] − w_k)ᵀ r_t` over the window's sample (weighted by `ω_t` for `ew`), its annualized standard deviation `s_k = √252 · sd(d)`, and `se_k = s_k / √(T_eff/252)` (`T_eff = T` for fixed windows). The give-up is `g_k = μ_sᵀ(w_front[j] − w_k)`. Continue while `g_k ≤ 1.0 · se_k` (`k = 1` standard error; **[choice]** one standard error reads as "within estimation noise" without claiming a test); stop at the first candidate that fails or at `k_div[j]`. `y_sug[j]` = the return floor of the last candidate that passed (`y_front[j]` if none did). Labelled everywhere as a heuristic that uses shrunk means for the give-up and the paired sample deviation for the noise; it is not a significance test. This replaces the memo's Bera-Park bootstrap (Bera & Park 2008; Pola 2016 for the hold-risk-vary-return idea) and needs no extra solves.

### 4.9 Six-month range, risk slider domain

For any weights with annual `(μ, σ)`: `μ_6 = μ/2`, `σ_6 = σ/√2`, `Low = μ_6 − 1.96 σ_6`, `Typical = μ_6`, `High = μ_6 + 1.96 σ_6`: an estimated central 95% range under an additive normal approximation (no compounding, no serial dependence, no parameter uncertainty), matching the owner's spreadsheet convention. The risk slider's parameter is the ceiling X; its readout is `Low_front(X) = y_front(X)/2 − 1.96·X/√2` (or `y_front(X)/2`) for the frontier mix, with `y_front` linearly interpolated between columns. `y_front` is concave in X (optimal value of a convex program), so `Low_front` rises then falls; the domain is `[X_safe, X_max]` with `X_safe = X_j` at the **rightmost** maximum of `Low_front(X_j)`, on which `Low_front` is non-increasing. Columns left of `X_safe` have lower volatility but both lower return and a worse estimated bad-six-months; they are drawn but not selectable. If `X_safe = X_max` the slider is disabled (§3.2). Initial X on load: the current mix's σ clamped into the domain if an allocation exists, else the domain midpoint. The selected mix's own range (result strip) is computed from its actual `(μ, σ)` and can differ from the slider readout in either direction.

TSP G Fund: handled by the correlation-space shrinkage and diagonal floor (§4.3); a 100%-G mix has `ENB = 1`, so its word follows the thresholds (Poor whenever `enb_ref > 3.33`) with the details line "there is little risk here, but all of it is in one place". No special-casing elsewhere.

### 4.10 Stress windows

Three fixed windows: `gfc2008` 2008-09-01 → 2009-03-09 ("2008 financial crisis"); `covid2020` 2020-02-19 → 2020-03-23 ("COVID crash, Feb–Mar 2020"); `rates2022` 2022-01-03 → 2022-10-12 ("2022 rate shock"). The tensor carries, per fund, the buy-and-hold total return over each window (`null` if the fund lacks a price within 3 trading days of both endpoints). The browser computes the selected mix's and the current mix's window return as `Σ_i w_i R_i / Σ_i w_i` over covered funds, shows the covered share, and, if covered weight < 50%, replaces the number with "Not enough of this mix existed then to say." Never fabricates.

### 4.11 Browser-side math and fidelity

The tensor ships `mu_s`, `sigma`, `cov`, `torsion` (T), `torsion_inv_t` (`(Tᵀ)^{-1}`) and `torsion_lambda` (Λ) so the browser computes exact `μ`, `σ`, ENB, six-month range and stress results for any weight vector. Interpolation for a slider position `(X, t)`, `t ∈ [0,1]` (0 = frontier, 1 = most diversified): for each of the two neighbouring columns `j, j+1`, the column's candidate ladder is `[w_front, cells from the top down to w_div]` with returns `[y_front, Y_k …, y_div]`; `w_j(t)` is the linear interpolation along that ladder at fraction `t` of the ladder's return span; the result is `w = (1−λ) w_j(t) + λ w_{j+1}(t)` with `λ = (X − X_j)/(X_{j+1} − X_j)`. Only feasible cells enter; `null` cells never do. No clipping and no renormalization: a convex combination of feasible weights satisfies the bounds and sums to 1, and because each ladder entry satisfies `‖Cw‖ ≤ X_j` (resp. `X_{j+1}`), the norm's convexity gives `σ(w) ≤ X`. Statistics are recomputed from the tensor moments, never interpolated. Fidelity tests: at every grid node and frontier point the TypeScript `stats(w)` equals the Python values in the tensor to 1e-6 (fixture `web/fixtures/guide2017_5y.json`); for 200 random `(X, t)`: `σ(w) ≤ X + 1e-9`, `min − 1e-9 ≤ w ≤ max + 1e-9`, `|Σw − 1| ≤ 1e-9`, `1 ≤ ENB ≤ N`; `t = 0` reproduces the interpolated frontier mix and `t = 1` the interpolated most-diversified mix.

### 4.12 Determinism and runtime

The engine has no randomness. Building the same universe and lookback twice yields identical canonical JSON after removing the telemetry fields `built_at` and `build_seconds` (test). Solve counts per lookback: 48 frontier + about 1,000 feasible cells ≈ 1,050 small conic programs. Runtime is a **benchmark, not a promise**: the target is ≤ 30 s for a 23-fund (universe, lookback) build and ≤ 3 min for a preset's six lookbacks on KS-001's 2-vCPU container, measured in Phase 4 and recorded in the runbook; the single named fallback if the target is missed is a coarser grid (`NX = 32`, `NY = 24`, about 40% fewer solves), applied once and re-measured. CI asserts only that the 23-fund fixture builds in ≤ 90 s.

## 5. Data pipeline and request budget

### 5.1 Price provider

`portfoliosight/data/providers/base.py` keeps the Protocol so a second provider can be added later; only `tiingo.py` is implemented in the demo:

```python
class PriceProvider(Protocol):
    name: str
    def fetch_daily(self, symbol: str, start: date, end: date | None) -> pd.DataFrame: ...
        # columns: date (index, tz-naive), close, adj_close, div_cash, split_factor; empty frame = no data
    def fetch_meta(self, symbol: str) -> SymbolMeta | None: ...   # name, first_date, last_date, kind
```

Tiingo adapter: `GET https://api.tiingo.com/tiingo/daily/{symbol}/prices?startDate=&endDate=&format=json&columns=date,close,adjClose,divCash,splitFactor`, header `Authorization: Token $TIINGO_API_KEY`; meta from `GET /tiingo/daily/{symbol}`; 404 = no such symbol; 429 = back off `Retry-After` or 60 s. Secrets are read from the environment only, loaded from `~/.secrets/portfoliosight.env` (holds `TIINGO_API_KEY`, `CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_R2_ACCESS_KEY_ID`, `CLOUDFLARE_R2_SECRET_ACCESS_KEY`, and after Phase 4 `PS_GATE_SECRET`), never `~/.secrets/qse.env`, and never logged (redact any `Token`/`api_token` value and the literal key in every log line, as QSE's `eodhd_client.py` does). Verified 2026-10-13: Tiingo returns 200 with `close, adjClose, divCash, splitFactor` for VTI (history from 2001-05-31), VTSAX, VBIAX (Dec-2025 distribution present), VGSTX (from 1985-03-29), SGOV; FIENX ends 2024-10-30 (converted to an ETF) and is dropped from the default menu with the note "converted to an ETF; no data since 2024-10-30", by design.

The provider fills the canonical record (§5.3) for (a) symbols not in the seed (every mutual fund, the curated ETFs the lake lacks), fetched in full; (b) the corporate-action **tail** of seeded symbols from `adjusted_through` forward; (c) nightly updates. For (b) and (c) the adapter is called with `start = adjusted_through − 7 days`, the rows are converted with §4.1 and spliced onto the stored index at `adjusted_through` (continuity `tr_index_t = tr_index_{adjusted_through} · Π(1 + r_s)`), after which `adjusted_through = last fetched date`. A seeded symbol is never served before its first tail refresh, because unknown splits in a price-only tail would fabricate crashes.

### 5.2 Universe, served symbols, and the one policy table

"Any ticker already in our universe" means a symbol whose record is **served**. Nothing is read from QSE at runtime; the lake is read once on the laptop by the seed script. Tiers (`data/universes/tiers.json` lists the files in order; one symbol per line, `#` comments, optional `,income` tag):

1. **Tier 1, presets**: the 23 Step 2 funds (`data/holdings/holdings_guide2017_step2.csv`; all 23 are also in tier 2) and the 16 TSP funds (tsp.gov).
2. **Tier 2, curated menu staples**: `data/universes/portfoliosight.txt`, 313 ETFs and mutual funds (Appendix A); `income`-tagged lines (bond and cash funds) refresh first because missing distributions distort them most.
3. **Tier 3, QSE core stocks**: `data/universes/qse_core.txt`, a copy of `~/programming/quant-scenario-engine/data/tft/raw/eodhd/universes/datalake_us_core.txt` (1,038 symbols, 4 overlapping tier 2) committed in Phase 0; history comes from the seed, corporate actions from the provider.

**Served** (manifest `status: ok`): `last_date ≥ D − 3` and `adjusted_through ≥ D − 3` trading days (`D` from §4.2); seeded symbols whose tail has not been refreshed are `pending`; 404s and symbols with no recent data are `unavailable` with a reason. `/api/symbols` lists served symbols only, with `tiers_served` = the tiers that have at least one served symbol. Provider requests are spent in this order every night: tier 1, tier 2 `income`, rest of tier 2, tier 3 slice; the downloader stops at the hour, day or monthly unique-symbol budget and resumes next run.

| Measured plan (Tiingo) | Limits assumed → config (req/h, req/day, unique symbols/month) | Kept current nightly (= served) | Catch-up |
|---|---|---|---|
| Starter: 50/h, 1,000/day, 500/month, 1 GB/month (conservative assumption until measured) | 45, 900, 450 | Tiers 1–2: 313 provider symbols + 16 TSP; tier 3 **slice**: the first 130 lines of `qse_core.txt` not already in tier 2 (443 provider symbols/night, ≈ 10 h at 45/h) | ≈ 2 nights (non-seeded symbols cost 2 requests: history + meta) |
| Power: 10,000/h, 100,000/day, 110,248 symbols, 40 GB/month | 9,000, 90,000, 100,000 | All tiers (≈ 1,350 provider symbols, under 15 min) | 1 night |

The slice is a fixed set so its symbols stay current and served; the rest of tier 3 stays `pending` on Starter and the demo says so plainly in the picker help text. The plan tier is measured, not read: Tiingo responses carry no rate-limit headers (verified), so `download --mode measure-limits` (Phase 0 gate, §12) issues up to 60 meta requests for one symbol within ten minutes; a 429 before the 60th records Starter, no 429 records "at least 60/10 min" and, with the owner's confirmation from the Tiingo account page, Power; the result is written to `meta/provider_limits.json` (`{"provider","tier","req_per_hour","req_per_day","unique_symbols_per_month","measured_on","method":"probe|documented"}`), which the downloader reads (env fallbacks `PS_PROVIDER_REQ_PER_HOUR=45`, `PS_PROVIDER_REQ_PER_DAY=900`, `PS_PROVIDER_SYMBOLS_PER_MONTH=450`).

### 5.3 Storage: Cloudflare R2 is the canonical store; KS-001 is stateless

Owner decision (final): no universe data lives on KS-001; R2 is canonical, the laptop drive `/mnt/d/` is the backup. A dedicated bucket **`portfoliosight-data`** (new; the account's existing buckets `knowledgesight-documents`, `olney-forms`, `qse-backup`, `scs-backups`, `scs-models` are not reused), accessed with the S3-compatible API (`boto3`, `endpoint_url=https://{CLOUDFLARE_ACCOUNT_ID}.r2.cloudflarestorage.com`, `region_name="auto"`, credentials `CLOUDFLARE_R2_ACCESS_KEY_ID` / `CLOUDFLARE_R2_SECRET_ACCESS_KEY`). `portfoliosight/data/store.py` wraps get/put/list/delete with retries and is the only code that touches R2; `LocalStore` with the same interface backs tests and local development (`PS_STORE=r2|local`, `PS_LOCAL_STORE_DIR`).

Key layout (a **generation** `G = {asof}-{engine_version}`, e.g. `2026-10-12-0.1.0`, is immutable once published):

```
prices/{SYMBOL}.parquet            canonical per-symbol record (below); TSP as TSP-G.parquet etc.
meta/manifest.json                 per symbol: name, kind (etf|mutual_fund|stock|tsp), tier, income, source (seed|tiingo|tsp|seed+tiingo),
                                   first_date, last_date, adjusted_through, status (ok|pending|unavailable), reason, fetched_at
meta/provider_limits.json          measured plan and limits in force (§5.2)
meta/budget.json                   provider request ledger: counts per UTC hour and day, unique symbols this month
meta/current.json                  {"generation": G, "asof", "engine_version", "published_at"}: the single pointer, switched last
meta/{G}/presets.json              exactly the body of GET /api/presets for generation G
meta/{G}/symbols.json              exactly the body of GET /api/symbols (rewritten at the end of each nightly run)
meta/status.json                   last nightly run: started, finished, D, symbols refreshed per tier, errors
tensors/{G}/{hash}/{lookback}.json preset and custom tensors of generation G, never overwritten
```

Canonical per-symbol record (**[choice]** raw close plus a total-return index: the seed has `adj_close` but no dividend records, the provider has both; one format both fill): parquet columns `date` (tz-naive), `close` (raw), `tr_index` (1.0 on the first row, dividends reinvested at the ex-date close, splits removed), `div_cash` and `split_factor` (nullable; provider rows only, for audit). Daily returns are always `tr_index.pct_change()`. Rows after `adjusted_through` are price-only and are never served (§5.2).

Repo files (committed, read-only at runtime): `data/universes/tiers.json`, `data/universes/portfoliosight.txt`, `data/universes/qse_core.txt`, `data/presets.json`, `data/holdings/holdings_guide2017_step2.csv`. Personal holdings files and research runs are gitignored and purged from history; `.dockerignore` excludes `runs/`, `data/holdings/*` except the Step 2 CSV, `.venv`, `web/node_modules`, `web/dist`, and a test asserts the built image contains none of them.

KS-001 scratch: the container keeps a size-capped LRU cache at `/app/cache` (named Docker volume `ps-cache`, owned by the image's `app` user, uid 10001; `PS_CACHE_MAX_MB=300`, evicted by last access after every build and every nightly step); it holds only the parquet files a build needs and the tensor being written. Nothing on KS-001 is authoritative.

Backup and restore (owner's laptop): `scripts/r2_backup.sh` mirrors the bucket to **`/mnt/d/portfoliosight-data/`** with the AWS CLI v2 (`aws s3 sync --endpoint-url https://{ACCOUNT}.r2.cloudflarestorage.com s3://portfoliosight-data /mnt/d/portfoliosight-data --delete`), reading the two R2 keys from `~/.secrets/portfoliosight.env`. Before syncing, the script checks `mountpoint -q /mnt/d` and that `/mnt/d/portfoliosight-data` exists or can be created; if D: is not mounted it prints "D: drive is not mounted at /mnt/d; backup not run" and exits with status 2 (never a silent skip). `scripts/r2_backup.sh --restore` runs the same sync with source and destination swapped (laptop → bucket, never `--delete` on restore), with the same mount check. The KS-001 container never sees `/mnt/d/`. Phase 4 schedules the backup in the laptop's WSL crontab next to the existing 05:00 QSE backup: `30 5 * * * $HOME/programming/portfoliosight/scripts/r2_backup.sh >> $HOME/.local/state/portfoliosight/r2_backup.log 2>&1` (added idempotently by `scripts/install_backup_cron.sh`, which leaves every other crontab line untouched). A run with D: unmounted logs the message, exits 2, and the next run catches up. Restore is only ever run after the bucket is confirmed lost or corrupted.

### 5.4 Seed, catch-up and nightly

**Seed (one-time, laptop → R2, zero provider cost).** `python scripts/seed_r2_from_lake.py [--lake PATH] --adjusted-through 2026-02-27 [--dry-run]` reads the lake's per-symbol parquet from `--lake`, which defaults to the WSL working copy `~/tft-quantile-forecaster/data/tft/raw/eodhd/datalake_us_core/eod_history` (`/mnt/d/tft-quantile-forecaster` is only QSE's nightly mirror and may be unmounted, so it is never the default); the script exits with a clear error if the path does not exist or holds fewer than 1,000 parquet files. Columns `date, open, high, low, close, adj_close, volume`; 1,445 files, 269 MB. It converts each to the canonical record (`tr_index = adj_close / adj_close.iloc[0]`, price-only after `adjusted_through`) and uploads `prices/{SYMBOL}.parquet` plus manifest entries with `source: seed`, `adjusted_through: 2026-02-27`, `status: pending` (8 concurrent uploads, resumable by skipping keys that already exist with the same size). The lake's `dividends/` and `splits/` folders are empty and ignored. Before uploading anything the script asserts that no row after `--adjusted-through` in any file has `adj_close != close` and prints the latest per-symbol adjustment date it found (expected: VTI 2025-12-19, AAPL 2026-02-06, SGOV and TLT 2026-02-27); a violation stops it.

**Downloader.** `python -m portfoliosight.data.download --mode measure-limits|catch-up|refresh [--symbols ...] [--tiers 1,2,3]`, run as a one-shot container job on KS-001 (or on the laptop with the same env file). Catch-up: for every universe symbol without a record, fetch the full history and its meta (two requests); for every `pending` seeded symbol, fetch the tail (one request) and splice. Refresh: for every served symbol, fetch from `last_date − 7 days` (one request) and splice; symbols already at `D` are skipped. Both walk the priority order of §5.2, write each symbol's parquet as they go, and rewrite the manifest atomically after each tier (the nightly job is the only manifest writer). The ledger `meta/budget.json` counts requests per UTC hour and day and unique symbols per month; the downloader sleeps to the next hour when the hourly budget is spent and exits cleanly when the daily or monthly budget is spent.

**Nightly** (host timer on KS-001, §9.1, every day at 02:00 PT; each step reads and writes R2): (1) `D` = last completed XNYS session; if `meta/current.json` already points at generation `{D}-{engine_version}` and the run's refresh found nothing new, exit; (2) refresh tier 1 (23 provider requests + the TSP CSV); (3) build the two presets × six lookbacks under `tensors/{G}/…`, write `meta/{G}/presets.json` and `meta/{G}/symbols.json`, then switch `meta/current.json` to `G` (readers never see a half-built generation); (4) refresh tier 2 `income`, rest of tier 2, tier 3 slice within budget; rewrite `meta/{G}/symbols.json`; (5) delete every generation older than the previous one (custom tensors live and die with their generation); (6) write `meta/status.json`; (7) evict the cache to its cap. Alerts: none for the demo; `/v1/health` exposes `meta/status.json` and `D`.

### 5.5 TSP

`portfoliosight/data/providers/tsp.py`: `GET https://www.tsp.gov/data/fund-price-history.csv?startdate=YYYY-MM-DD&enddate=YYYY-MM-DD&Lfunds=1&InvFunds=1&download=1` with a browser User-Agent (verified 2026-10-13: curl's default UA receives 403, a Chrome UA receives the CSV; columns `Date, L Income, L 2030, …, L 2075, G Fund, F Fund, C Fund, S Fund, I Fund`). Catch-up from 2003-06-02; refresh from `last_date − 7 days`. Symbol ids `TSP-G, TSP-F, TSP-C, TSP-S, TSP-I, TSP-LINC, TSP-L2030, TSP-L2035, TSP-L2040, TSP-L2045, TSP-L2050, TSP-L2055, TSP-L2060, TSP-L2065, TSP-L2070, TSP-L2075`; display names "G Fund", "L 2030", etc. `div_cash = 0`, `split_factor = 1`, `adjusted_through = last_date`.

### 5.6 Missing-data policy

A fund that is not served, or has too little history for a window, is dropped from that computation and listed with its reason in the tensor's `excluded` array; the UI shows the note in the Funds table and the Settings lookback list. Nothing is interpolated, back-filled or fabricated. Reason strings are fixed templates: `no data`, `converted to an ETF; no data since {date}`, `no data since {date}`, `corporate actions not yet verified after {date}`, `history starts {date}, not enough for the {window} view`.

## 6. API contract

Service: FastAPI, `portfoliosight/api/app.py`, uvicorn on container port 8000, published on KS-001 as `127.0.0.1:8010`, reached publicly as `https://api.portfoliosight.ai` (tunnel) and by the page as same-origin `https://portfoliosight.ai/api/*` (Worker, §9.3; the Worker maps `/api/x` to the service's `/v1/x`). Every `/v1/*` request must carry `x-ps-gate` equal to `PS_GATE_SECRET` (constant-time compare) or receives `403 forbidden`; this is the authentication of record because the Worker's same-zone fetch bypasses the WAF (§9.4). All responses JSON, errors as `{"error": {"code": str, "message": str, "details": object|null}}`.

Read/write split (**[choice]**, simpler and lighter on KS-001): the Worker serves every **read** straight from R2 (`GET /api/presets` ← `meta/{G}/presets.json` via `meta/current.json`, `GET /api/symbols` ← `meta/{G}/symbols.json`, `GET /api/tensors/{G}/{hash}/{lookback}` ← `tensors/{G}/{hash}/{lookback}.json`) and forwards to KS-001 only `POST /api/tensors`, `GET /api/health`, and a tensor `GET` whose key is absent in R2. Presets and every published tensor keep working when KS-001 is down.

| Method, path (service) | Request | Response | Cache-Control |
|---|---|---|---|
| `GET /v1/health` | — | `200 {"status":"ok","version":str,"generation":G,"asof":"YYYY-MM-DD","asof_trading_days_behind":int,"queue":{"depth":int,"building":bool},"nightly":{status.json}}` | `no-store` |
| `GET /v1/presets` | — | `200 {"generation":G,"asof":str,"presets":[{"id":"guide2017","name":str,"hash":str,"funds":[{"id","name"}],"allocation":{"VTI":10840,...}|null,"allocation_unit":"$"|null,"lookbacks":{"5y":{"status":"ready","url":"/api/tensors/{G}/{hash}/5y"},...}}]}` | `public, max-age=300` |
| `GET /v1/symbols` | — | `200 {"generation":G,"asof":str,"tiers_served":[1,2,3],"symbols":[{"id":"VTI","name":str,"kind":"etf"|"mutual_fund"|"stock"|"tsp","tier":1|2|3,"first_date":str}]}` (served symbols only) | `public, max-age=3600` |
| `POST /v1/tensors` | `{"funds":[{"id":"VTI","min":null,"max":0.10},...],"lookback":"5y"}`; 2–30 funds; ids uppercase; `min/max` optional (`null` = default rule); `lookback` ∈ {1y,2y,3y,5y,10y,ew} | `200 {"status":"ready","generation":G,"hash":str,"url":"/api/tensors/{G}/{hash}/5y"}` · `202 {"status":"queued"|"building","generation":G,"hash":str,"position":int,"eta_s":int}` · `409 {"status":"failed","error":str,"attempts":int,"retry":bool}` · `400 unknown_symbols {"symbols":[...]}` · `422 invalid_request` (duplicates, >30, <2, cap validation of §4.4, bad lookback) · `429 rate_limited` · `503 busy` when 20 jobs are queued | `no-store` |
| `GET /v1/tensors/{G}/{hash}/{lookback}` | `G` = `\d{4}-\d{2}-\d{2}-[0-9.]+`, `hash` = 16 hex | `200` tensor (§7) with `ETag` · `202` as above · `409` failed as above · `404 unknown_tensor` (never requested in G) | `200`: `public, max-age=86400, immutable` (keys are immutable); others `no-store` |

Universe hash: `sha256(canonical_json({"schema":2,"funds":[{"id","min","max"} sorted by id]}))[:16]` over the **requested** policy (`min/max` `null` when default). Build queue: a single worker thread inside the API process with a job table keyed by `(G, hash, lookback)`; a POST for an existing key returns its state instead of enqueuing; only the requested lookback is built (other lookbacks build on demand when selected; the page requests them as the visitor switches); a job that raises is marked `failed` and a later POST re-enqueues it up to 3 attempts; a build reads only the needed `prices/*.parquet` from R2 into the cache, writes the tensor to `tensors/{G}/…`, and never overwrites an existing key. `G` is read from `meta/current.json` at POST time, so a job started before a nightly switch completes in its own generation and the client, which holds `G`, keeps working. Abuse protection: input limits above; per-IP limiter keyed by `CF-Connecting-IP` (5 `POST /v1/tensors` per minute, 60 requests per minute on `/v1/*`, 429 otherwise); `uvicorn --limit-concurrency 32`; request body limit 16 KB; plus the Cloudflare rate-limiting rule of §9.4.

## 7. Tensor format

One JSON document per (G, hash, lookback). Floats serialized with 8 significant digits (so weights sum to 1 within 1e-6 and the fidelity tests of §4.11 hold). Sizes: N = 23 → about 350 KB raw, 90–110 KB compressed on delivery; N = 30 → about 450 KB raw.

```json
{
  "schema": 2, "engine_version": "0.1.0", "generation": "2026-10-12-0.1.0",
  "built_at": "2026-10-13T09:31:02Z", "build_seconds": 14.2, "asof": "2026-10-12",
  "universe": {"hash": "3f9c2a7e1b4d5e60", "name": "2017 guide, Step 2", "preset_id": "guide2017",
               "funds": [{"id": "AGG", "name": "iShares Core US Aggregate Bond ETF", "kind": "etf", "source": "seed+tiingo"}, ...],
               "excluded": [{"id": "FIENX", "reason": "converted to an ETF; no data since 2024-10-30"}]},
  "lookback": {"id": "5y", "start": "2021-10-13", "end": "2026-10-12", "rows": 1257, "t_eff": 1257, "ew_halflife_days": null},
  "rf": 0.0412,
  "mu_s": [...n], "mu_sample": [...n], "sigma": [...n], "cov": [[...n]...n],
  "torsion": [[...]], "torsion_inv_t": [[...]], "torsion_lambda": [...n],
  "bounds": {"requested": [{"min": null, "max": null}, ...], "min": [...n], "max": [...n], "rule": "max(0.25, 3/N)"},
  "frontier": {"x": [...48], "y": [...48], "w": [[...n]...48], "x_safe_index": 7},
  "grid": {"y": [...32], "z": [[...32]...48], "w": [[[...n]...32]...48], "k_div": [...48], "y_div": [...48], "w_div": [[...n]...48], "y_sug": [...48]},
  "enb_ref": 5.13,
  "stress": {"gfc2008": {"label": "2008 financial crisis", "start": "2008-09-01", "end": "2009-03-09", "r": [...n|null]},
             "covid2020": {...}, "rates2022": {...}},
  "notes": ["Expected returns are a 50/50 blend of the sample mean and a menu-beta heuristic.", "..."]
}
```

`grid.w[j][k]` and `grid.z[j][k]` are `null` for infeasible cells; `k_div[j] = -1` means the frontier mix is the column's most-diversified candidate. Fund order is the `universe.funds` order everywhere. A JSON Schema at `portfoliosight/engine/tensor.schema.json` is the contract; the Python builder validates on write and the TypeScript loader on read (`zod`).

## 8. Front-end architecture

`web/` (Vite 7, React 19, TypeScript 5.8, D3 modules only: `d3-scale`, `d3-shape`, `d3-selection`, `d3-drag`, `d3-interpolate`, `d3-axis`; `lucide-react` icons; no component library; plain CSS modules with the token file `web/src/theme/tokens.css`).

```
web/src/
  main.tsx, App.tsx
  state/store.ts            single reducer: universeSpec, allocation, lookback, ghosts, X, t | "auto", theme, caps, build status
  state/url.ts              encode/decode of the URL query (§8.1), replaceState debounced 250 ms
  api/client.ts             fetch /api/*, typed by tensor.schema.json; 202 polling; 409 retry; cf-mitigated reload (§3.2)
  math/portfolio.ts         stats(w): mu, sigma, enb, range6m, stress; interpolate(X, t) per §4.11; riskSliderDomain
  chart/Heatmap.tsx         canvas layer: heatmap cells + ghost/primary frontier lines; sets data-ghost-count on the chart element
  chart/Overlay.tsx         SVG layer: axes, ceiling line, markers at actual coordinates, drag handlers, tooltip
  controls/RiskSlider.tsx, DivSlider.tsx, ResultStrip.tsx, ThemeSwitch.tsx, PresetMenu.tsx
  sections/Funds.tsx, Trades.tsx, Stress.tsx, Settings.tsx
  theme/tokens.css, theme/useTheme.ts
web/worker/index.ts         Cloudflare Worker: host check, www redirect, R2 reads, API forwarding, static assets (§9.3)
web/fixtures/guide2017_5y.json   dedicated 23-fund UI fixture built by Phase 1 from tests/fixtures/synthetic_23.parquet
web/tests/ (vitest)         math fidelity, url codec, reducer
web/e2e/smoke.spec.ts       Playwright against production (§10)
```

Rendering: canvas redraws on theme change, tensor change, ghost toggle; the SVG overlay updates on every slider tick (≤ 1 ms of math). The heatmap draws filled rectangles per feasible cell with `d3-interpolate`'s `interpolateRgbBasis(heat-0..4)` on `Z / enb_ref`; infeasible cells transparent. Chart margins 48/16/40/56 px (desktop), 32/12/36/44 (phone). Axes in percent. All interactive elements carry `data-testid` (listed in §10).

### 8.1 URL encoding

Query parameters, all optional, updated on every change: `u` preset id (`guide2017|tsp`) or omitted for custom; `f` custom funds as `ID:amount` comma-separated (amount optional, e.g. `f=VTI:60,BND:40,VNQ`); `unit` `pct|usd` (default `pct`); `c` cap overrides `ID:min:max` (percent integers; blank = default); `lb` lookback id; `g` ghost ids comma-separated; `loss` risk slider value as the frontier mix's bad-six-months return (e.g. `loss=-0.094`, clamped into the domain on load); `by` `bad|typical`; `d` diversification position `auto` or a decimal in `[0,1]`; `t` theme id; `x` `1` when details are on. Example: `https://portfoliosight.ai/?u=guide2017&lb=5y&loss=-0.094&d=auto&t=hud`. Decoding never trusts the URL for anything but these fields; unknown funds are reported through the normal 400 path.

## 9. Deployment

### 9.1 Backend container, scheduler and provisioning on KS-001

- Files: `deploy/Dockerfile` (python:3.12-slim, two-stage, non-root user `app` uid 10001, `pip install .[api]`, `RUN mkdir -p /app/cache && chown app:app /app/cache`), `deploy/docker-compose.yml` (service `api`; service `nightly` under `profiles: ["jobs"]`, same image, `command: python -m portfoliosight.jobs.nightly`, no port), `deploy/systemd/portfoliosight-nightly.service` and `.timer`, `.dockerignore` (§5.3), `scripts/deploy_ks001.sh`.
- Compose `api`: `container_name: portfoliosight-api`, `restart: unless-stopped`, `ports: ["127.0.0.1:8010:8000"]`, `deploy.resources.limits: {cpus: "2", memory: 1536M}`, `reservations: {cpus: "0.5", memory: 256M}`, volume `ps-cache:/app/cache` only (no data bind mount), `env_file: ~/.secrets/portfoliosight.env` (the owner creates it on KS-001 with the same keys as the laptop copy plus `PS_GATE_SECRET`; `export` prefixes stripped because compose `env_file` takes `KEY=value`), environment `PS_STORE=r2`, `PS_R2_BUCKET=portfoliosight-data`, `PS_CACHE_DIR=/app/cache`, `PS_CACHE_MAX_MB=300`, healthcheck `GET /v1/health` every 30 s, json-file logging capped 10 MB × 3.
- Scheduler (**[choice]** a host systemd timer rather than cron inside the container: `jeff` is not allowed to use `crontab` on KS-001, a slim non-root image has no working cron daemon, and systemd gives single-instance runs and journald logs): `portfoliosight-nightly.timer` with `OnCalendar=*-*-* 02:00:00` (host time zone is America/Los_Angeles), `Persistent=true`; `portfoliosight-nightly.service` with `Type=oneshot`, `User=jeff`, `WorkingDirectory=/home/jeff/portfoliosight`, `ExecStart=/usr/bin/docker compose -f deploy/docker-compose.yml run --rm --no-deps nightly`, installed with `sudo cp deploy/systemd/* /etc/systemd/system/ && sudo systemctl enable --now portfoliosight-nightly.timer`; logs via `journalctl -u portfoliosight-nightly`.
- Provisioning: `git clone github:automateintelligence/portfoliosight ~/portfoliosight` on KS-001 as `jeff` (image build only; no datalake on the host, no disk growth). `scripts/deploy_ks001.sh` (from the laptop): `ssh KS-001-jeff "cd ~/portfoliosight && git fetch github && git checkout <sha> && GIT_SHA=<sha> docker compose -f deploy/docker-compose.yml build && docker compose -f deploy/docker-compose.yml up -d api"` then `curl -fsS -H "x-ps-gate: …" http://127.0.0.1:8010/v1/health` over ssh. Images are tagged `portfoliosight:${GIT_SHA}`; rollback is the same script with the previous SHA.
- Resource reality (2026-10-13): KS-001 has 24 GB RAM with 13 GB available, 44 GB disk free, ports 8000/8001/8002/8004/8005 in use, 8010 free; cloudflared 2026.1.2 runs as a systemd service with `/etc/cloudflared/config.yml` (root-owned); `jeff` has passwordless sudo.

### 9.2 Tunnel and DNS

Add to `/etc/cloudflared/config.yml` ingress, **above** the catch-all: `- hostname: api.portfoliosight.ai\n  service: http://localhost:8010`, then `sudo systemctl restart cloudflared`. DNS in the `portfoliosight.ai` zone (zone id `0434784c350a6fc062b2d4ae389cdd9b`, Free plan, active, no records yet): proxied CNAME `api.portfoliosight.ai → 222b8001-009a-47b2-8a31-3ea624ce32ca.cfargotunnel.com`, created with the API token from `~/.secrets/portfoliosight.env` (`POST /zones/{zone}/dns_records`; the token can list this zone's DNS, edit is untested), by `cloudflared tunnel route dns` on KS-001, or in the dashboard. The apex and `www` records are created by the Worker custom domains (§9.3).

### 9.3 Worker and static assets

`web/wrangler.jsonc`: `name: "portfoliosight"`, `main: "worker/index.ts"`, `compatibility_date: "2026-09-01"`, `workers_dev: false`, `preview_urls: false`, `assets: {directory: "./dist", binding: "ASSETS", not_found_handling: "single-page-application", run_worker_first: true}` (every request runs the Worker so the host check and redirect always execute), `r2_buckets: [{binding: "DATA", bucket_name: "portfoliosight-data"}]`, `routes: [{pattern: "portfoliosight.ai", custom_domain: true}, {pattern: "www.portfoliosight.ai", custom_domain: true}]`, `vars: {API_ORIGIN: "https://api.portfoliosight.ai"}`, secret `PS_GATE_SECRET` (`wrangler secret put`). Worker logic, in order: host `www.portfoliosight.ai` → 301 to the same path on the apex; any host other than `portfoliosight.ai` → 404; `GET /api/presets` and `GET /api/symbols` → read `meta/current.json` (in-memory per isolate for 60 s), then `meta/{G}/presets.json` / `symbols.json` from R2 (`Cache-Control: public, max-age=300`, header `x-ps-source: r2`); `GET /api/tensors/{G}/{hash}/{lookback}` → validate the three segments, `env.DATA.get(...)`, serve with `Cache-Control: public, max-age=86400, immutable`, the object's `etag`, `x-ps-source: r2`; on an R2 miss, and for `POST /api/tensors` and `GET /api/health`, forward to `fetch(API_ORIGIN + "/v1/" + rest, {method, body, headers: {"x-ps-gate": env.PS_GATE_SECRET, "content-type", accept: "application/json", "CF-Connecting-IP": request.headers.get("CF-Connecting-IP")}})` and return the upstream response with its `Cache-Control` and `x-ps-source: origin`; anything else → `env.ASSETS.fetch(request)`. Deploy: `npm run build && wrangler deploy` with `source ~/.secrets/portfoliosight.env`. Rollback: `wrangler rollback`. Workers Free plan: 100k requests/day; R2 free tier: 10 GB, 1M Class A and 10M Class B operations/month; a page load is ≤ 12 requests. No edge caching is configured or claimed; `Cache-Control` governs the browser cache only.

**[choice]** Same-origin Worker rather than a challenge cookie on the apex: one hostname carries one challenge, the page's fetches are same-origin so the clearance cookie applies to them automatically, there is no CORS, and with the R2 binding every read bypasses the tunnel and KS-001 entirely.

### 9.4 Human check, origin authentication and smoke-test exemption (standard Cloudflare only)

WAF custom rules on the `portfoliosight.ai` zone (Free plan: 5 rules; Managed Challenge and header comparison are available):

1. `ps-challenge-site`: `(http.host in {"portfoliosight.ai" "www.portfoliosight.ai"}) and not any(http.request.headers["x-ps-gate"][*] == "<PS_GATE_SECRET>")` → **Managed Challenge**.
2. `ps-block-api-direct`: `(http.host eq "api.portfoliosight.ai") and not any(http.request.headers["x-ps-gate"][*] == "<PS_GATE_SECRET>")` → **Block**.

Rate-limiting rule (Free plan: one rule, expression fields limited to path and verified bot, 10 s period, 10 s block): `ps-tensor-post`, expression `(http.request.uri.path eq "/api/tensors")`, 20 requests per 10 s per IP, action Block; it matches the exact POST path and not the `GET /api/tensors/{G}/…` polling paths; POST-specific limits are enforced in the application (§6). Routing: the `global_fetch_strictly_public` compatibility flag is **not** enabled, so the Worker's `fetch` to `api.portfoliosight.ai` (same zone) goes straight to the origin through the tunnel and is not evaluated by rule 2; rule 2 only stops outside callers, and the FastAPI header check (§6) is what authenticates the Worker. Browsers never send the header and get the Managed Challenge on first visit, after which the `cf_clearance` cookie covers the page and its same-origin `/api/*` fetches; when clearance expires mid-session a fetch receives the challenge page, which the client detects by `cf-mitigated: challenge` and recovers from with a top-level reload (§3.2). Playwright smoke tests set `extraHTTPHeaders: {"x-ps-gate": process.env.PS_GATE_SECRET}` and pass both rules; the "unexempted request is challenged" test uses a fresh, cookieless request context without the header and expects HTTP 403 with `cf-mitigated: challenge` on `/`, and HTTP 403 without that header on `https://api.portfoliosight.ai/v1/health`. The API token in `~/.secrets/portfoliosight.env` currently lacks Zone WAF permissions (rulesets listing returns "Authentication error"), so the rules are created in the dashboard or after the owner adds `Zone › Zone WAF › Edit`; the secret is generated once (`openssl rand -hex 24`), stored as `PS_GATE_SECRET` in `~/.secrets/portfoliosight.env` on the laptop and on KS-001, and never committed.

### 9.5 Deployment checklist order (Phase 4; the runbook `docs/plans/2026-10-13-ks001-cloudflare-runbook.md` records each step)

1. R2: create the bucket `portfoliosight-data` (`wrangler r2 bucket create portfoliosight-data` with the account token, or the dashboard), then `python -m portfoliosight.data.store --verify` from the laptop (`head_bucket`, put/get/delete of `meta/_probe`, list). On 403 the R2 keys are scoped to other buckets: the owner creates a new R2 API token (R2 › Manage R2 API Tokens › Object Read & Write, bucket `portfoliosight-data` only) and replaces the two keys. (Phase 0 runs the verify first; Phase 4 re-runs it.)
2. Seed from the laptop (`scripts/seed_r2_from_lake.py`); verify `meta/manifest.json` lists ≥ 1,400 symbols with `source: seed`, `status: pending`.
3. **Owner checkbox (not softened):** the owner has confirmed, in writing in the runbook, the Tiingo plan on the key and that its terms allow storing Tiingo data and derived outputs persistently in R2 and the backup mirror. Tiingo's terms of service §1.6 (app.tiingo.com/tos, read 2026-10-13) prohibit persistent storage of Tiingo Data and Derived Products on Starter and Trial plans; a Paid Plan permits storing Tiingo Data while active and retaining Derived Products that meet §1.6's conditions. No tail refresh, catch-up or nightly run starts before this box is checked.
4. KS-001: clone, `~/.secrets/portfoliosight.env` (with `PS_GATE_SECRET`), `docker compose up -d api`, `curl` health over ssh with the header; `measure-limits` (re-run; Phase 0 measured once); catch-up (`docker compose run --rm --no-deps nightly python -m portfoliosight.data.download --mode catch-up`, resumable over nights); first preset build (`… python -m portfoliosight.jobs.nightly`); record the measured 23-fund build time in the runbook (§4.12) and apply the fallback if needed.
5. Tunnel ingress + DNS CNAME; verify `curl -H "x-ps-gate: $PS_GATE_SECRET" https://api.portfoliosight.ai/v1/health` returns 200 and the same call without the header returns 403.
6. WAF rules + rate-limiting rule; verify with a cookieless request that `/` is challenged.
7. Worker deploy with secret and R2 binding; verify `GET /api/presets` carries `x-ps-source: r2`, `https://www.portfoliosight.ai/` redirects, the `workers.dev` hostname is disabled, and the page loads through the challenge in a real Chrome and via Playwright with the header.
8. Install and start the systemd timer; confirm the next `meta/status.json`; first laptop backup run (`scripts/r2_backup.sh`), `/mnt/d/portfoliosight-data/` populated, backup cron installed (`scripts/install_backup_cron.sh`; `crontab -l` shows exactly one PortfolioSight line).

## 10. Testing strategy

- Python: `ruff check . && ruff format --check . && pyright .` clean; `pytest --cov=portfoliosight --cov-report=term-missing` with ≥ 80% line coverage overall and 100% on `portfoliosight/engine/` (owner's standing rule). Tests in `tests/` mirror the package. No network except tests marked `live` (skipped unless `PS_LIVE_TESTS=1`). Fixtures: `tests/fixtures/synthetic_23.parquet` (a seeded synthetic daily return matrix for the 23 Step 2 tickers with realistic moments from a three-factor model, generated by `scripts/make_fixtures.py`), recorded provider JSON under `tests/fixtures/provider/` (VTI, VBIAX full history; AAPL 2020-08, NVDA 2024-06, USO 2020-04 windows), a TSP CSV slice, and a three-symbol fixture lake `tests/fixtures/lake/`.
- Engine tests: Cholesky identity; frontier `y` non-decreasing in `x`; frontier mixes have `σ = X_j` within 1e-6 for `X_j < σ_max`; every weight vector respects bounds and sums to 1 ± 1e-6; optimized `‖w‖²` non-increasing in `Y` within a column and non-decreasing in `X` within a row (±1e-6); `1 ≤ Z ≤ N`; `ENB(w_div[j]) ≥ ENB(w_front[j])`; `y_div[j] ≤ y_sug[j] ≤ y_front[j]`; the standard-error walk stops at the first failing candidate; ENB identities of §4.6; cap validation and minimums-first greedy fill; determinism of §4.12; schema validation; the 23-fund fixture builds in ≤ 90 s.
- API tests (`TestClient`, `LocalStore` in a temp dir): every row of §6 including 202 → 200, 409 failed → retry → 200, deduplicated POSTs, 400/422/429/503 cases, the 403 without the gate header, ETag/Cache-Control, hash stability across windows, immutable keys never overwritten, public `/api/` URLs in responses.
- Data tests: Tiingo adapter against the recorded fixtures (adjClose cross-check, split basis), budget ledger (hour/day/month stop and resume), manifest resume and `pending → ok` transitions, served rule with a fake calendar date, TSP CSV parsing with the exact header, seed conversion on the fixture lake including the `adjusted_through` assertion, splice continuity, the store interface against `moto`'s S3 mock and `LocalStore`, cache eviction at the cap, `.dockerignore` assertion (image build in CI when `docker` is available, else a unit test over the ignore rules).
- TypeScript: `npm run lint && npm run typecheck && npm test` (vitest): §4.11 fidelity and interpolation tests against the fixture tensor, URL codec round-trips, reducer transitions, word mapping thresholds, six-month range, stress aggregation with partial coverage, challenge-detection and retry logic with mocked responses, theme token presence for all three themes.
- Production smoke tests: Playwright (`web/e2e/smoke.spec.ts`), projects `chromium-desktop` (1366×900) and `chromium-phone` ("iPhone 13"), base URL `https://portfoliosight.ai`, header `x-ps-gate` from `PS_GATE_SECRET`. One test per definition-of-done item in §11, named `DoD-NN`; calendar-dependent expectations are computed at test time from `/api/symbols` and `/api/health`. Screenshots per theme and viewport are saved as artifacts. `data-testid`s: `chart` (with `data-ghost-count`), `chart-canvas`, `risk-slider`, `risk-readout`, `set-by-toggle`, `div-slider`, `div-reset`, `point-selected`, `point-current`, `point-div`, `ceiling-line`, `range-low`, `range-typical`, `range-high`, `div-word`, `details-toggle`, `details-enb`, `theme-switch`, `preset-menu`, `chip-funds`, `chip-trades`, `chip-stress`, `chip-settings`, `section-funds`, `section-trades`, `section-stress`, `section-settings`, `fund-row-{ID}`, `fund-add`, `use-menu`, `building-notice`, `build-retry`, `excluded-note`, `lookback-{id}`, `ghost-{id}`, `cap-min-{ID}`, `cap-max-{ID}`, `caps-reset`, `stress-{id}`, `share-link`, `disclaimer`, `footer-cta`.

## 11. Definitions of done (each has one smoke test unless marked unit/API/live)

1. `https://portfoliosight.ai/` loads in Chrome through Cloudflare's Managed Challenge; with the `x-ps-gate` header Playwright gets HTTP 200 and sees `chart-canvas` within 5 s.
2. Gate: a fresh, cookieless request to `/` without the header returns 403 with `cf-mitigated: challenge`; `https://api.portfoliosight.ai/v1/health` without the header returns 403 without that header and with it returns 200 JSON; `https://www.portfoliosight.ai/?u=tsp` redirects 301 to `https://portfoliosight.ai/?u=tsp`; the Worker's `workers.dev` hostname does not serve the site (connection refused or 404).
3. First screen on desktop shows chart, risk slider, diversification slider, result strip and chips with no table, trade list or stress card visible; all four sections are collapsed (`aria-expanded="false"`).
4. First screen on the phone viewport fits: no horizontal scroll (`document.documentElement.scrollWidth <= innerWidth`), chart, both sliders, result strip and chips are within the first 1.2 viewport heights, touch targets ≥ 44 px.
5. Default view is the "2017 guide, Step 2" preset with its allocation: `point-current` is visible, Funds section lists 23 rows with amounts filled for 18, and FIENX shows the note "converted to an ETF; no data since 2024-10-30".
6. No tangency/max-Sharpe point and no "Sharpe", "bets", "knee", "significant" text anywhere in the default DOM (details off).
7. The heatmap renders: sampling the canvas at 20 points inside the feasible region yields ≥ 3 distinct colors from the theme's ramp; the region above the frontier is the page background.
8. Risk slider: at five increasing positions the "bad six months" readout is non-increasing and `ceiling-line` moves right; `point-selected` never sits right of the line (x ≤ line x + 1 px); toggling `set-by-toggle` leaves the line in place and changes only the readout.
9. Diversification slider: defaults to the suggested position (`div-reset` hidden); moving toward "More diversified" moves `point-selected` down and never right of `ceiling-line`; at the top end the point coincides with the frontier at that X (within 1 px); with details on, `details-enb` at the bottom end is ≥ its value at the top end.
10. The diversification word is one of Good/Average/Fair/Poor, rendered at ≤ 14 px in the muted color, and the ENB number appears only after `details-toggle` is on (unit test for the thresholds).
11. Presets: selecting "TSP (G, F, C, S, I)" loads a five-fund tensor with max cap 60% in Settings, no `point-current` and no Trades section; typing "L 2050" in `fund-add` offers `TSP-L2050` as a custom fund.
12. Custom menu, with `/api/health` reporting an idle queue: adding `VOO, BND, VNQ, SGOV` and clicking `use-menu` shows `building-notice` (unless cached) and the chart updates within 120 s; a forced failure (unit, mocked) shows `build-retry`; adding an unknown ticker shows an inline error naming it; a 31st fund is refused with a message.
13. Trades: for the default preset, Trades lists every held fund with now/selected/change columns and a turnover total; entering "$" amounts shows dollar changes; clearing all amounts hides the section.
14. Caps: editing `cap-max-VTI` to 10 triggers a rebuild and the resulting frontier weights for VTI never exceed 10% (checked via the tensor); setting `cap-min-VTI` above `cap-max-VTI` shows an inline validation error and sends nothing; `caps-reset` restores the rule.
15. Lookbacks: switching to `10y` redraws the frontier and the Settings exclusion list equals the set computed by the test from `/api/symbols` `first_date` values and the rule of §4.2; toggling `ghost-1y` increments `data-ghost-count` on `chart` by one and changes sampled canvas pixels.
16. Stress cards show three windows with numbers for the default preset, each with a coverage note when < 100% of the mix existed; a custom mix `SGOV + VTIP` shows "Not enough of this mix existed then to say" on the 2008 card.
17. Themes: the switcher cycles ks-dark → light → hud; `html[data-theme]` changes, `--bg` computed values equal the table in §3.5, the canvas repaints (sampled pixel changes), and the choice survives reload; `t=hud` in the URL wins over storage.
18. HUD contains no film/character/trademark references (grep over `web/src`, copy and docs returns nothing beyond the word "HUD").
19. URL: after changing preset, lookback, slider and theme, the address bar contains `u`, `lb`, `loss`, `d`, `t`; opening that URL in a fresh context reproduces the same `risk-readout`, `div-word` and theme.
20. Disclaimer text of §3.7 is present and visible; the footer CTA links to the three family URLs; the result strip shows "Historical math, not investment advice."
21. API/R2: `GET /api/presets` carries `x-ps-source: r2`, a `generation`, and the two presets with all six lookbacks `ready` and `/api/…` URLs; fetching a preset's `5y` URL returns a tensor that validates against `tensor.schema.json` with `Cache-Control: public, max-age=86400, immutable` and `x-ps-source: r2`; a `POST /api/tensors` for the default preset returns 200 with a `url` that resolves to the same tensor.
22. Provider gate (live, Phase 0): the Tiingo adapter returns ≥ 250 rows with `close, adjClose, divCash, splitFactor` for VTI and VBIAX; the adjClose cross-check and the split fixtures of §4.1 pass; `measure-limits` has written `meta/provider_limits.json` (or its `LocalStore` equivalent) with tier, limits, method and date; the budget ledger stops at those limits (unit, fake clock).
23. Nightly freshness (live): `meta/current.json`'s `asof` equals the last completed XNYS session as of 12:00 PT on the day of the check, `meta/status.json` shows that run with zero errors, the generation holds the 12 preset tensors, and the KS-001 cache volume is ≤ 300 MB (`du` over ssh).
24. Engine fidelity: TypeScript `stats(w)` matches the tensor at every grid node and frontier point to 1e-6; the interpolation invariants of §4.11 hold for 200 random positions; determinism passes (unit).
25. Container hygiene: the deployed image contains no `runs/` and no `data/holdings/` file other than `holdings_guide2017_step2.csv`; no secret string from `~/.secrets/portfoliosight.env` appears in the image, the repo, or the built site bundle.
26. Quality gates: Python lint/type/coverage and TypeScript lint/typecheck/tests pass on `main`; every production smoke test passes from the laptop in Chrome against `https://portfoliosight.ai`.
27. Docs: ROADMAP.md carries Appendix B's additions; README.md describes the layout, commands, storage (R2 primary, `/mnt/d/portfoliosight-data` backup, lake working copy on the WSL disk) and deployment in ≤ 60 lines and no longer names `/mnt/d` as the lake location.
28. Store gate (live): `python -m portfoliosight.data.store --verify` succeeds against `portfoliosight-data` (Phase 0 and again in Phase 4); after Phase 4 the manifest holds ≥ 1,400 seeded symbols, `scripts/r2_backup.sh` has mirrored the bucket to `/mnt/d/portfoliosight-data/`, and a dry-run `--restore` reports zero files to upload.
29. Served-symbol policy (live): every symbol in `/api/symbols` has manifest `status: ok` with `adjusted_through ≥ D − 3` trading days (sample of 20 checked against `meta/manifest.json`); no `pending` or `unavailable` symbol appears; the runbook's owner checkbox of §9.5 step 3 is ticked and dated.
30. Build benchmark (live): the runbook records the measured 23-fund build time on KS-001; it is ≤ 30 s, or the §4.12 fallback grid is in effect and the re-measured time is ≤ 30 s.

## 12. Build phases (dependency order; each phase has its own branch and PR)

Each phase is done by a fresh agent with only this spec and the repo. Dependencies: Phase 0 and Phase 1 run in parallel; Phase 2 needs 0 and 1; Phase 3 needs Phase 1's fixture; Phase 4 needs 2 and 3; Phase 5 needs 4. Live gates are owned by exactly one phase: provider gate and R2 verify by Phase 0 (DoD 22, 28 first half); seed, catch-up, nightly, backup, benchmark and the owner checkbox by Phase 4 (DoD 23, 28 second half, 29, 30).

**Phase 0: data layer** (`feature/data-layer`). Deliver: `pyproject.toml` rewritten (core deps numpy, pandas, pyarrow, scipy, scikit-learn, cvxpy, clarabel, requests, pydantic, boto3, exchange_calendars; extras `api` = fastapi, uvicorn; `research` = yfinance, matplotlib, plotly, skfolio; `dev` = pytest, pytest-cov, ruff, pyright, responses, moto); `portfoliosight/data/` (providers base/tiingo/tsp, store with `R2Store`/`LocalStore` and `--verify`, cache, returns/splice, manifest, budget, limits, calendar, download CLI with `measure-limits|catch-up|refresh`); `scripts/seed_r2_from_lake.py`, `scripts/r2_backup.sh`, `scripts/install_backup_cron.sh`, `scripts/make_fixtures.py`; `data/universes/tiers.json`, `data/universes/portfoliosight.txt` (Appendix A with `income` tags), `data/universes/qse_core.txt` (copied from QSE, 1,038 lines), `data/presets.json`; recorded fixtures of §10; unit tests. Done when: DoD 22 passes live from the laptop against `LocalStore`, the R2 verify of DoD 28 passes, a `--dry-run` of the seed over the real lake prints its assertion report, `download --mode catch-up --symbols VTI,VBIAX,SGOV,TSP-G` against `LocalStore` writes parquet + manifest, budget stop/resume and `pending → ok` tests pass, lint/type/coverage gates pass.

**Phase 1: engine** (`feature/engine`). Deliver: `portfoliosight/engine/` (stats, torsion, optimize, surface, suggest, stress, caps, tensor builder + `tensor.schema.json`), `scripts/build_tensor.py` (CLI: returns parquet or preset → JSON), `tests/fixtures/synthetic_23.parquet` and the dedicated UI fixture `web/fixtures/guide2017_5y.json` built from it. Done when: all §4 engine tests pass with 100% engine coverage; the fixture builds in ≤ 90 s on CI; schema validates; determinism holds.

**Phase 2: API and container** (`feature/api`). Deliver: `portfoliosight/api/` (app, gate check, queue, presets, limiter), `portfoliosight/jobs/nightly.py` (generations, pointer switch, pruning), `deploy/` (Dockerfile, compose, systemd units), `.dockerignore`, `scripts/deploy_ks001.sh`. Done when: §6 tests pass against `LocalStore` and `moto`; `docker compose -f deploy/docker-compose.yml up` locally (`PS_STORE=local`, a small fixture store) serves `/v1/health` and builds a custom tensor end-to-end; a local `docker compose run --rm --no-deps nightly` publishes a generation and switches the pointer; the cache never exceeds its cap; DoD 25 passes locally.

**Phase 3: front end** (`feature/web`). Deliver: `web/` per §8 against the fixture tensor via a vite dev proxy or a static mock of `/api/*`; three themes; all controls, sections, URL state, challenge recovery, compliance copy, data-testids. Done when: `npm run lint && npm run typecheck && npm test` pass; a local Playwright run of the §11 tests that do not need production (3–10, 13, 16–20 with the mock) passes against `vite preview`.

**Phase 4: production deployment** (`feature/deploy` for code; infra steps executed over ssh and the Cloudflare API where the token allows, otherwise written as exact owner steps in `docs/plans/2026-10-13-ks001-cloudflare-runbook.md`). Deliver §9.5 in order, including the owner checkbox before any ingestion, the measured plan tier and build time. Done when: DoD 1, 2, 21, 23, 28, 29, 30 pass against production.

**Phase 5: smoke tests and docs** (`feature/smoke`). Deliver: `web/e2e/` with one test per DoD item 1–30, `scripts/smoke.sh`, README and ROADMAP updates (Appendix B), including the README Data-section fix (name the WSL working copy `~/tft-quantile-forecaster/data/tft/raw/eodhd/datalake_us_core/` as the lake, `/mnt/d` as QSE's mirror, and replace the EODHD/Schwab/yfinance guidance with this spec's provider, seed and R2 design). Done when: DoD 1–30 all pass from the laptop; worktrees and merged branches are cleaned per the owner's cleanup script.

Conventions for every phase: TDD (failing test first); no stubs, no TODOs; tests in `tests/` and `web/tests/`, scripts in `scripts/`; remote `github`; feature branch + PR for code, docs straight to `main`; secrets only via `~/.secrets/portfoliosight.env` (never `qse.env`, never committed); no network calls to any provider other than Tiingo and tsp.gov; `ruff`/`pyright`/`pytest --cov` and `npm run lint && npm run typecheck && npm test` before the PR.

## 13. Risks

- **Data license (owner's decision, not a build blocker for code)**: Tiingo's terms §1.6 prohibit persistent storage of Tiingo data and derived products on Starter and Trial plans, which the R2 store, the tensors and the backup mirror all are; a Paid Plan permits storing data while active, and public display of derived figures still needs the owner's reading of the terms or an internal-commercial/redistribution agreement. The build writes the code; production ingestion waits for the runbook checkbox (§9.5 step 3). The footer credits Tiingo and tsp.gov.
- **Provider plan limits**: the key's tier is unverified (no usage endpoint, no rate-limit headers); the policy table assumes Starter until measured. On Starter, nightly refresh takes about 10 hours and only a 130-stock slice of tier 3 is served; Power serves everything in minutes.
- **Mutual-fund coverage**: verified for VTSAX, VBIAX, VGSTX, FXAIX, SWTSX; some curated tickers may 404 and are marked unavailable; FIENX is excluded by design.
- **tsp.gov**: the CSV requires a browser-like User-Agent and may change format; the parser asserts the exact header and the nightly marks TSP stale (not failed) if the fetch breaks.
- **Proxy vs. measure**: the surface optimizes weight concentration and reports exact ENB, which is not monotone along a column; the UI promises only what §4.7 states.
- **Runtime**: about 1,050 solves per lookback; the 30 s target is measured on KS-001 with one named fallback (§4.12).
- **KS-001 memory**: 1.5 GB limit; a build loads at most 30 symbols (< 10 MB); the nightly streams one symbol at a time. Shared with production KnowledgeSight services; the nightly runs at 02:00 PT.
- **Managed Challenge on phones**: some visitors see an interstitial; accepted by the owner. If Cloudflare changes the `cf-mitigated` header, DoD 2 and the client detection are adjusted, not the gate.
- **Workers Free quota**: 100k requests/day; every request runs the Worker (`run_worker_first: true`); a demo will not approach it.
- **Cloudflare token scope**: WAF rules may have to be created in the dashboard; tunnel ingress needs sudo on KS-001; the R2 keys may be scoped to other buckets (§9.5 step 1).
- **Seed quality**: the lake's `adj_close` is trusted as EODHD's back-adjustment through 2026-02-27; the seed assertion, the VTI splice test and the first tail refresh (which revalidates corporate actions from that date) are the checks. A symbol whose seed history looks wrong is deleted from R2 and refetched in full from the provider.
- **R2 as a single point of truth**: a lost bucket is restored from `/mnt/d/portfoliosight-data/` with `scripts/r2_backup.sh --restore`; between backups, at most one night's deltas are lost and are refetched by the next refresh.

## Appendix A: served universe by tier

Tier 1 (presets): the 23 Step 2 symbols (AGG BND DBJP EDV FIENX LQD LTPZ PCY SCHF SCHO TIP VB VBIAX VBR VEA VGSTX VNQ VOE VTI VTIP VTV VWO VWOB) and the 16 TSP funds listed at the end. Tier 3: `data/universes/qse_core.txt`, the 1,038-line copy of QSE's `datalake_us_core.txt` (large-cap US stocks; not reproduced here; seeded from the lake; on Starter only the first 130 lines not in tier 2 are kept current). Tier 2 (`data/universes/portfoliosight.txt`, 313 symbols; the whole "Bond ETFs" group and the mutual funds VBTLX VBMFX VBILX VBIRX VBLAX VSIGX VSCSX VTAPX VIPSX VWEHX VWINX FXNAX FTBFX FUAMX FIPDX SWAGX SWRSX DODIX PTTAX PTTRX PONAX MWTRX BCOIX LSBDX carry the `,income` tag):

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

Presets (`data/presets.json`): `guide2017` = the 23 symbols of `data/holdings/holdings_guide2017_step2.csv` with amounts = Qty × Price (dollars; 18 held, 5 universe-only at 0); `tsp` = TSP-G, TSP-F, TSP-C, TSP-S, TSP-I, no allocation. The 11 TSP L Funds are served for custom menus only.

## Appendix B: ROADMAP additions (written in Phase 5)

- Paid tier: more than 30 funds per portfolio, and tickers outside the served universe fetched on demand, behind a small annual paywall.
- Data license and tier 3: confirm or upgrade the Tiingo plan (Power or internal-commercial) and obtain written storage/display terms before marketing the site; on a Power-class plan the nightly job serves all of tier 3 without code changes. A second price provider (EODHD if its plan gains prices) is one adapter behind the existing Protocol.
- Later product options: a TSP preset that includes the L Funds as comparison choices; an exact-ENB (non-convex) refinement of the surface.
- Out of scope for the demo and parked: FERS planner (Phase 2b), risk questionnaire / risk number, hedge/collar calculator, emails, programmatic SEO pages, payments, accounts/login, copula Monte Carlo, Student-t toggle, image export, walk-forward UI, robustness score.
