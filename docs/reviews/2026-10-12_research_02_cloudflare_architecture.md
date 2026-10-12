# Research report 2: Architecture options for a freemium efficient-frontier web app on Cloudflare

Date: 2026-10-12. Produced by a web-research agent. Verified against official pages where the fetch succeeded; third-party figures are flagged. Prices are USD list.

Note added after the user's reply: the user already has four Contabo VPS, a paid Cloudflare account, the Cloudflare CLI, a paid EODHD API, and existing Cloudflare sites. The vendor comparison in section 2 is therefore mostly moot (EODHD is the data source); the compute and caching analysis still applies.

## 1. Where to run the numeric optimization

**Hard constraint first:** the slider must update in under 100 ms, which rules out any server round-trip for the interactive path. Once per-ticker returns are loaded, the browser must own the covariance matrix and recompute portfolio mean/variance (an O(n²) dot product) on every slider tick. Only the frontier itself (10-100-asset QP solved ~50-200 times) and the max-Sharpe / diversification solves are candidates for the server, and those can be precomputed.

**(a) Cloudflare Python Workers (Pyodide).** GA as of 21 Sep 2026. Packages: pure and PyEmscripten packages on PyPI plus anything in Pyodide, declared in `pyproject.toml`, deployed with `pywrangler`. Pyodide ships scipy (1.18.0, OpenBLAS) and numpy, so `scipy.optimize.minimize(SLSQP)` is available. Caveats: 128 MB memory per isolate; the script limit became a single 64 MiB uncompressed cap in Aug 2026. Cold start: Cloudflare's own benchmark went from ~10 s to a mean 1,027 ms with deploy-time memory snapshots (changelog 2025-12-08); no published scipy-specific number. CPU: Free plan 10 ms per request, so scipy is paid-plan-only; Paid default 30 s, raisable to 5 min. Verdict: workable for a daily batch on Paid, risky for interactive latency.

**(b) Cloudflare Containers / Durable Objects.** Containers run any image. Instance types lite (1/16 vCPU, 256 MiB) to standard-4 (4 vCPU, 12 GiB). Workers Paid includes 25 GiB-h memory, 375 vCPU-min, 200 GB-h disk per month; overage $0.0000025/GiB-s, $0.000020/vCPU-s. Cold starts 1-3 s; `sleepAfter` defaults to 10 min. A standard-1 kept warm 24×7 is roughly $25/mo (third-party estimate). Durable Objects (SQLite-backed, 30 s CPU default) are the right place to serialize per-ticker cache refreshes, not to run QPs.

**(c) Separate backend behind Cloudflare.** Fly.io shared-cpu-1x 256 MB ≈ $2/mo, 1 GB ≈ $5. Railway Hobby ~$30/mo for an always-on 1 vCPU/1 GB box. Pros: real scipy, trivial to debug. Cons: another deploy target. (The user's existing Contabo VPS fits here at zero marginal cost.)

**(d) Entirely in-browser.** Pyodide core ~6.4 MB plus numpy/scipy wheels (tens of MB); too heavy for a landing page. The JS/WASM route is cheap: `quadprog` (MIT, pure JS port of R's Goldfarb-Idnani dual method, strictly convex QPs with linear inequalities); `scs-solver` (WASM SCS conic solver) for general convex cases; `glpk.js`/`highs-js` are LP/MILP only, useful for CVaR/MAD variants. For long-only budget-constrained min-variance with n ≤ 100, a Goldfarb-Idnani solve is sub-millisecond; 100 frontier points plus a max-Sharpe search runs well under a second. Max-Sharpe reduces to a QP via the Cornuejols-Tütüncü transform (y = w/(μᵀw − rf)); "diversification-optimized" can be max-diversification-ratio (same transform) or equal-risk-contribution (projected gradient).

**Bottom line:** the QP is small enough that the browser is the cheapest and fastest place for it, and that removes per-request compute cost from the free tier. Keep scipy on the server for a daily batch that precomputes canonical frontiers for popular fund menus and validates the JS solver.

## 2. Market data (adjusted daily closes, commercial site)

| Provider | Relevant tiers | Limits | Funds / ADRs | Commercial posture |
|---|---|---|---|---|
| Tiingo | Starter $0; Power $30/mo; internal commercial $50/mo | Starter 50/hr, 1,000/day, 500 symbols/mo, 5 yr; Power 10k/hr, 100k/day | 60,717 ETFs and mutual funds | Both tiers "Internal Use Only"; display/redistribution priced via sales |
| EODHD | Free 20/day; Historian $19.99/mo; Fundamentals $59.99; All-in-One $99.99 | 100k calls/day, 1,000/min, 30+ yr | "Funds US" on $59.99+; 150k+ tickers incl. OTC/global | Separate Personal vs Commercial/B2B plans |
| Alpha Vantage | Free 25/day; $49.99 to $249.99 | per-minute caps | adjusted daily for many funds | Page silent on commercial use; third parties cite $499-2,499/mo commercial tiers |
| Massive (ex-Polygon) | Basic $0; Starter $29; Developer $79; Advanced $199 | unlimited on paid | stocks/ETFs; mutual funds not confirmed | Explicit: any app showing Massive data needs a Business subscription |
| FMP | Free 250/day; Starter $22; Premium $59; Ultimate $149 | per-minute caps | fund holdings on top tier | not stated |
| Twelve Data | Basic free; Grow $79; Pro $229; Ultra $999 | credit-based | mutual fund NAV only at Pro | Individual pricing is non-commercial |

**Yahoo/yfinance:** Yahoo's ToS bar automated access without permission; the yfinance README says the API "is intended for personal use only." Not usable for a commercial site.

**Practical read:** every vendor's listed price is a personal/internal license; displaying prices or derived figures to anonymous visitors is display/redistribution at all of them. Get a written quote naming "display to end users of a website" before launch.

## 3. Caching strategy on Cloudflare

Per-ticker 5 y of daily adjusted closes is ~1,260 floats (~10-20 KB JSON, ~5 KB Float32).

- **KV:** Free 100k reads/day, 1k writes/day, 1 GB; Paid 10M reads/mo then $0.50/M, $0.50/GB-mo. Eventually consistent, fine for daily data. Best for `prices:{TICKER}` blobs and hot per-menu covariance matrices.
- **D1:** Free 5M rows read/day, 5 GB; Paid 25B reads included. Use for ticker metadata, request logs, lead capture, popular-menu stats.
- **R2:** 10 GB and 10M Class B free; $0.015/GB-mo; zero egress. Canonical daily snapshot per ticker and precomputed frontier JSON for the top N fund menus, served straight to the browser.
- **Cron Triggers:** 5 per account Free, 250 Paid. One nightly cron after fund NAVs post refreshes only tickers seen in the last 30 days, writes R2 then KV, bumps a version key. Serialize refreshes per ticker through a Durable Object to avoid duplicate vendor calls.

## 4. Charting

- **Plotly.js**: MIT. Full bundle 1.49 MB gz; `basic` partial 401 kB gz. Richest hover, heavy for a landing page.
- **Apache ECharts**: Apache-2.0. ~153-173 KiB gz full; tree-shakeable to under 100 kB gz for scatter+line. Canvas renderer handles 10k points smoothly.
- **Observable Plot**: ISC, ~83-92 KiB gz; SVG re-render per tick fine at hundreds of points.
- **D3**: not benchmarked by the agent; the user prefers D3 and already has a D3 stock chart. D3 with a canvas layer for the frontier and SVG for the markers is the natural choice given that preference.
- **lightweight-charts**: time-axis only; not suited to a risk/return scatter.

## 5. Compliance note (US, not legal advice)

The Advisers Act targets "personalized advice attuned to a client's concerns"; in *Lowe v. SEC* (1985) the Court held impersonal publications that do not offer individualized advice fall within the §202(a)(11)(D) publisher exclusion, so long as communications "remain entirely impersonal." SEC rules define "impersonal investment advice" as services that do not purport to meet the objectives or needs of specific individuals (17 CFR 275.203A-3). The 2024 Internet Adviser Exemption amendments matter only if you register as an adviser.

Common practice: Portfolio Visualizer's FAQ states "Educational only. Not investment advice," "provided strictly for educational and illustrative purposes only," "not registered with the SEC, FINRA, FCA, ESMA, or any other regulator," "All outputs are hypothetical," and "You remain solely responsible for your investment decisions." Design rules that follow: label outputs as mathematical results of historical data; no recommendations keyed to age, goals, or risk tolerance; no account linking; no human follow-up discussing the user's portfolio; prominent hypothetical-performance and no-advice disclaimer; no compensation tied to specific securities. The lead-gen handoff should be a generic CTA, not "based on your portfolio we suggest." Have a securities attorney review before the paid tier.

## 6. Recommended architecture

1. Static front end on Cloudflare Pages/Workers Assets (TS, D3 or ECharts, ~100 kB gz). All interactive math client-side: covariance precomputed per ticker set, slider to mean/variance in under 1 ms, frontier via `quadprog` for n ≤ 100, max-Sharpe via the convex transform, ERC/max-diversification via projected gradient.
2. One JS Worker serving `GET /returns?tickers=...`: reads KV, falls back to R2, misses go through a Durable Object that de-duplicates vendor fetches, then writes R2+KV. Response is a compact Float32 returns matrix.
3. Nightly Cron Trigger refreshes active tickers from EODHD after NAV posting; canonical history in R2, hot copies in KV, metadata/leads in D1.
4. No Python in the request path. scipy/skfolio run only from the cron (Cloudflare Container or the existing VPS) to precompute frontiers for top fund menus and unit-test the JS solver nightly.
5. Reasoning: the problem is a 100×100 QP, so the browser is both fastest and cheapest; the only real recurring cost is the data license.
6. Compliance: Portfolio-Visualizer-style disclaimers, impersonal framing, generic CTA.

Items not verified directly: Massive's Business-plan price, FMP's mutual-fund price-history coverage, Pyodide's current scipy wheel size, Observable Plot's docs page.
