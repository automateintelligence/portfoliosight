# PortfolioSight: briefing for a new agent

Date: 2026-10-21. Sources: `README.md`, `ROADMAP.md`, `docs/specs/2026-10-13-portfoliosight-demo-design.md`, `docs/specs/2026-10-14-portfoliosight-simulation-engines-design.md`, `docs/plans/2026-10-18-return-optimization-experiment-protocol.md`, `docs/reviews/2026-10-18-gate-change-objective-and-slider.md`, `docs/reviews/2026-10-20-return-optimization-experiment-report.md` (verdict, sensitivity, cost and threshold sections only). Assumes the new return-optimization method replaces ENB. It is not in code yet.

## What it is

PortfolioSight (`portfoliosight.ai`) is a free, one-screen web tool for people choosing among a fixed fund menu: a 401(k), the TSP (federal employees' retirement plan), or a brokerage list. It is educational, uses historical math, and is not advice. The site is in private preview until the owner buys the commercial Tiingo data license.

The first screen holds:
- a **chart** with the efficient frontier ("best return at each level of risk") over a colored **map of how spread out each mix is**;
- a **risk slider** that shows a Bad year and a Typical year (one year; the six-month version was replaced on 2026-10-13);
- a second **diversification slider**;
- a **result strip** with Bad / Typical / Good for the selected mix, plus a quiet Good / Average / Fair / Poor word.

Everything else is collapsed: Funds & amounts (tickers, shares, % or $), Trades, Stress tests (2008, March 2020, 2022), and Settings (lookbacks, ghost frontiers, per-fund caps). There are two ready-made menus, the Example Portfolio (23 funds, the default, with its allocation) and TSP (G, F, C, S, I). Custom menus of 2 to 30 funds are built on request, or up to 100 in owner admin mode. The page has four looks (Dark, Light, HUD, Grid), a phone layout, and a URL that always encodes the view. Share-by-email sends a fixed template.

## Why it was built

- **Business:** a free traffic driver for the owner's other products (KnowledgeSight, SecuritySight, Option Spread Scanner, later QSE). The owner expects low conversion, needs cash flow, and would welcome acquisition by an advisory firm. A paid tier (more than 30 funds, tickers outside the served universe) comes later.
- **Audience:** NAVSEA/TSP friends first, then Bogleheads-style investors. Non-technical, so default copy never says "bets", "Sharpe", "sigma" or "knee". It also never gives advice ("you should") and never uses the words "Risk Number".
- **Intellectual core:** the owner's long-standing wish for a surface with risk X, return Y, and Z as a diversification measure that is not stdev or Sharpe. The idea is to hold risk fixed and vary return to find the best-diversified point (Pola, Bera-Park, Meucci, Choueifaty). Diversification is framed as insurance against model risk, not against volatility.
- **Owner's brief:** "Build it as a demo… speed balanced with good econometrics and great design."

## How it works

**Pipeline and stack**
- **Data:** Tiingo (close, dividends, splits) and tsp.gov sit behind one provider Protocol. Total returns are rebuilt locally. The owner's QSE lake seeded the store once and now keeps stocks current through a weekday laptop sync (`sync_lake.py`). R2 bucket `portfoliosight-data` is canonical, with a laptop backup. Tiers: presets, about 317 curated ETFs and mutual funds, and QSE stocks.
- **Build service:** FastAPI in one container on KS-001 (4 CPUs, 1.5 GB) behind a cloudflared tunnel. A nightly job at 02:00 PT refreshes data, builds the two presets across six lookbacks, and publishes a new "generation" only when all 12 tensors exist. Builds are deterministic and use fixed seeds.
- **Front door:** a Cloudflare Worker serves the page, reads tensors straight from R2, forwards builds and range requests to KS-001, sends the share email, and enforces the private-preview gate and Cloudflare's Managed Challenge.
- **Browser:** React and D3. It interpolates between precomputed mixes and recomputes the statistics itself. For mixes the tensor lacks, it calls `POST /v1/range` and shows a marked estimate until the exact answer arrives.
- **Tensor (per menu and lookback):** 48 risk columns along the frontier. Each column carries a "ladder" of 14 mixes, plus a 32-row raster for the map, per-fund stress returns, and the moments the browser needs. Moments use Ledoit-Wolf shrinkage with a 50/50 blend of sample returns and a menu-beta prior.

**One-year ranges.** The default engine ("History replay") is a stationary block bootstrap: 2,000 paths of 252 days. Bad / Typical / Good are the 2.5th / 50th / 97.5th percentiles. The simulation-engines spec adds a GARCH(1,1)-t volatility model, with a fat-tailed vine copula parked as Phase 3. Level (mean and risk) follows the chosen lookback. Shape (fat tails, volatility clustering, joint bad days) comes from up to 10 years of history. QSE code arrives only via `scripts/sync_qse.py` at a pinned commit and is never edited here.

**The old diversification logic (being replaced).** The word, the map, the ladder and the "Optimized" dot all came from minimum-torsion effective number of bets (ENB). The ladder maximized ENB at exactly fixed risk, and "Optimized" was a knee (the balanced point) on that ladder. Two problems:
- ENB is inflated on correlated menus: one fund alone scores 3.5 to 14.4 bets on the Example Portfolio.
- On the TSP 5-year data the slider handed users a mix worse on Bad and Typical (−10.5 / +7.4 against −7.9 / +8.2 at the default landing), and the word still improved.

## The new method that replaces ENB (spec §5.5, protocol §2; not in code yet)

At each risk ceiling X, with Bad B, Typical T and Good G taken from the selected engine's 2,000 paths:

- **Stage A, return.** `w_R = argmax U`, where `U = 0.60·B + 0.30·T + 0.10·G`. The constraints are the fund caps, weights summing to 1, and `σ ≤ X`. The ceiling is not an equality, so the mix may sit inside it. This is a finite trade-off, not lexicographic: the owner prefers [−5.01%, 8%, 18%] to [−5.00%, 4%, 12%].
- **Stage B, diversification.** After removing candidates dominated on (B, T, G), pick the highest-measure candidate from the admissible set relative to `w_R`. Admissible means:
  - Bad is no more than 10 bp below `w_R`'s;
  - Typical is no more than 25 bp below;
  - Good is no more than 50 bp below;
  - U is no more than the allowance below (cap 2.5 bp);
  - the candidate never has both Bad and Typical lower.
  Improvements are uncapped, and `w_R` always qualifies. The tie rule uses a global maximum with a 1e-12 tie set, never pairwise tolerances.
- **Slider:** the diversification slider becomes the **allowed U sacrifice**, mapped to 14 levels from `d=0` (`w_R`, "No trade-off") to `d=1` (the cap). `w_R` is the default landing, and the chosen mix is labeled "Selected mix" (never "Optimized" or "best-return"). Details show the trade-off taken against `w_R`, plus the tail diagnostic `ES_2.5`, the mean of the worst 50 of 2,000 years, which steers nothing.
- **Engine dependence:** holdings now follow the selected engine, so switching engines moves the selected mix and map. This narrows an older "chart doesn't move" guarantee and is awaiting owner confirmation.
- **Schema 4 (spec §7):** `variants.{enb,dr2}.ladders[engine]` replaces the single ladder. The fields `on_line`, `t_balanced`, `y_balanced`, `default_point` and `grid.y_sug` are removed. The URL gains `e=` and `m=`, and `d=auto` is read as 0.

**Open decisions (C8, owner):**
- Which diversification measure drives the word, map and Stage B: DR² (spec candidate), or ENB if DR² gates it in.
- Whether the white line and "Optimized" dot become the max-U path `w_R`, or stay max-expected-return.
- Whether the ENB/DR² method control is shown.
- Confirmation that the engine switch moves the selected holdings.

## What the experiment found

The report is `docs/reviews/2026-10-20-return-optimization-experiment-report.md`.

- **Design:** a retrospective rolling-origin backtest of 2,970 cells on both menus: 87 mature monthly origins, only 7 disjoint annual intervals, hindsight-chosen menus.
- **Verdict:** valid experiment, no failed cells. Adding the DR² preference (R+D) to `w_R` was inactive or near-inactive at the 2.5 bp cap. Realized evidence is inconclusive and tail power is underpowered. There was no material harm, and "confirmed worthwhile benefit" is **False**.
- **Numbers:** pooled ΔU was about −0.03 bp (against a +5 bp bar), DR² gain was 0.03 to 0.04 (against 0.10), seed stability was weak, and R+D cost 1.4× to 2× the search time. ENB was therefore skipped as **unevaluated, not ineffective**.
- **Authority:** the report authorizes no default change, UI design, deployment or publication.
- **Not yet read:** the R-versus-reference tables (R against minimum variance, equal weight and the MDP). Confirm R's own validation there.

## Repo and process rules

- **Frozen gate:** `assertions/` is the frozen done-gate (68 assertions). Never edit it. Changes go through gate-change docs in `docs/reviews/` and the Conductor re-freeze. The 2026-10-18 amendments (A-SE-18, 20, 22, 23, 29, 30, 31, 32) are pending re-freeze. A-SE-32 (no leakage from after an origin) is the first assertion the harness must meet.
- **Order of work:**
  1. rolling-origin harness `scripts/backtest_ranges.py`;
  2. the experiment (done);
  3. range API;
  4. UI engine selector;
  5. deployable Phase 1 after C8.
  The Copula engine stays parked and the library extension is not authorized.
- **Hard rules:**
  - no default switch without the owner reading the validation report;
  - never reduce the 2,000 paths to meet a time budget;
  - never fabricate or back-fill data;
  - never present output as advice;
  - the HUD theme never names the film;
  - never put personal holdings or secrets in the repo.
- **Unmeasured cost:** each candidate costs a 2,000-path compounding (about 5 ms). A modest search budget may already exceed the 30 s build target at 23 funds and two engines. The owner decides between fewer solved columns and a longer budget.
- **Working rules:** the branch is `claude/kind-ride-lr1dik` and no PR unless asked. Plain-language copy: never "bets", "knee", "Sharpe", "tangency", "GARCH", "copula" or "utility" in the default view, and never a measure shown as a count of holdings.

## Limits of this brief

It was written from the repo docs only. The three originating conversations were not available, so anything decided only there is missing.
