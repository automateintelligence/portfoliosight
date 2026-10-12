# Addendum to the strategy memo: user feedback, facts established, and open decisions

Date: 2026-10-12, after the user's first read of the memo overview.

## Facts established in this round

- **Infrastructure already in place:** four Contabo VPS; paid Cloudflare account with CLI; multiple live Cloudflare sites (option-spread-scanner, trading-dashboard, automateintelligence-website, securitysight, olney); credentials via `source ~/.secrets/qse.env`; paid EODHD API with a cached client at `qse/experimental/tft/data/eodhd_client.py`; price datalake at `/mnt/d/tft-quantile-forecaster/data/tft/raw/eodhd/datalake_us_core/` (stocks well covered, only a handful of ETFs). The data-vendor comparison in research report 2 is therefore moot.
- **QSE already lists this product.** `~/programming/quant-scenario-engine/docs/plans/project_goals.md` names product #1 as "portfolio asset allocation optimizer based on efficient frontier and entropy maximization." `docs/plans/2026-01-21_oss_to_saas_transformation.md` has free/professional/business tiers and a `portfolios` table that can be reused.
- **Empty folder `~/programming/finance/`** was created 2026-10-12 12:26, presumably as the new home.
- **The prior attempt** is `Finance/Portfolios/EF_with_ME_Slider.txt` (Sep 2017) plus 2022-2023 fragments (`Web Apps/interactive_page.html`, a D3 line chart with two range sliders; the Dash skeleton; the D3 stock chart). No HUD-styled page exists anywhere; the user said not to spend more energy on it.
- **2017 origin of the attempt (found last):** `OneDrive\Documents\Python Scripts\Finance\quantopian_research\research\Step1-Calculate-EF-for-given-portfolio-choices.py` and `.ipynb` (Sep-Oct 2017, "adapted by Jeff Daniels" from the Starke/Edwards/Wiecki cvxopt blog) hold the only earlier working frontier math; they read `Portfolios/example_Portfolio.txt` with the comment "This is eventually be replaced with data from web page user interface." `Setup_Website_Django.ipynb` (Sep 24 2017) contains one cell, `django-admin startproject advisor`, and the Django project was never created. Lineage: 2017 plan + EF script + unbuilt "advisor" site, then 2022-2023 ChatGPT fragments, then the Oct 2026 tool. No version ever wired a risk slider to a frontier.
- **KnowledgeSight style guide:** `~/programming/ai/website/docs/plans/phases/phase-5-design-system.md` (landing), `.../docs/plans/app/phase-4-design-dna.md` (app, dark default), tokens in `ai/website/src/index.css` and `src/components/knowledgesight/tokens/app-tokens.css`. Palette: Terracotta Clay #C76346, Fired Earth #A54930, Coral #E8907E, Ink #1A1A1A, Parchment #FAFAFA, Synthesis Indigo #464FC7, Jade #46C789; dark landing bg #161210, app dark surfaces #1A1A1E/#141417/#111114. Fonts EB Garamond (display/body), Inter (UI), JetBrains Mono (data). Light and dark both implemented. The ai/website already uses d3-force/zoom, so D3 is consistent with the family.
- **The user's spreadsheet Monte Carlo** (`IRA_Planning_Tool_Jeff_2026_v5.xlsx`): each six-month return is drawn Normal(mean = (High+Low)/2, sd = (High−Low)/(2·1.96)) from the "Estimated 6-month Low/High Return" inputs (−10, +19 by default), two draws compounded per year, 501 trials, 5th/50th/95th percentiles of balances; the "6 mo 95% Confidence Risk Ranges" table on Step 2 uses gain = 1.65 × loss and a near-linear Risk Number (−4% → 31, −9% → 49, −15% → 72; consistent with Nitrogen's −9.5% → 50). The simulation is normal, not long-tailed, so the Student-t layer is new work, not a port.

## Decisions taken by the user

1. Free tier: **no questionnaire and no Risk Number.** A risk slider plus the statistical 95% six-month win/loss range (as in the spreadsheet and the screenshot). The questionnaire becomes a paid-tier feature with periodic reallocation emails.
2. D3 for charts. Three selectable themes: Light (Windows/TurboTax-like), KnowledgeSight, Dark (Iron Man HUD).
3. Backend precomputes the risk/return tensor; nothing heavy computed on demand in the page. Rare tickers fetched on demand with a "please give us a moment" message.
4. Co-marketing with AutomateIntelligence.ai (KnowledgeSight, SecuritySight, Option Spread Scanner, later QSE). Low conversion expectations; one customer is a win. Monetize soon for cash flow; affiliate links welcome; being acquired by an advisory firm is a possible goal.
5. Return slider: evaluate; roadmap if not trivial.

## Round 2: research-section feedback and the diversification surface

User points: selectable lookback period; copula papers exist elsewhere but only matter beyond Tier 1; beware leakage from back-adjusted prices in forward-looking calculations; dislikes PCA (linear, oversimplifies); and the core construct: a surface over risk X and return Y with Z = a diversification measure that is not stdev or Sharpe, and an optimum on the vertical line at fixed stdev ("hold X, vary Y"); exact-stdev equality not required if it slows the calculation.

Answers recorded:
- Lookback: precompute 3/5/10-year and exponentially weighted slices; show ghost frontiers.
- Adjusted prices: back-adjustment rewrites history after each dividend/split, so store raw closes plus dividend and split records and compute total returns locally. Returns from adjusted closes are not look-ahead (each ex-date adjustment uses information known then). Real leakage risks for a "provably better" claim: survivorship in the user's universe and full-sample estimates in walk-forward tests; the evaluation mode must use data only up to each decision date.
- PCA: minimum torsion avoids PCA's instability but is still linear; nonlinear dependence is the copula / lower-tail-dependence layer.
- What diversification protects against: model risk, not volatility: estimation error in means and covariances, regime change (correlations to one), and single-name events absent from a five-year history. Volatility is risk inside the model; diversification is insurance against the model.
- Surface mapping: feasible region is everything under the frontier; Z at (X, Y) = max diversification achievable there; Z rises as Y falls from the frontier. Pola 2016 = hold X, vary Y, maximize entropy with tolerance delta. Bera-Park 2008 = the knee rule: descend only until return is statistically indistinguishable from the frontier (bootstrap quantile r). Deguest-Martellini-Meucci 2013 = the dual (ENB floor, maximize Y). Choueifaty MDP and DeMiguel norm constraints = single points / convex proxies.
- Z measures: headline = effective number of bets via minimum torsion; deeper = a robustness score (bootstrap out-of-sample Sharpe shortfall per grid point), precomputed nightly.
- Tractability: use stdev <= X and return >= Y, maximize Z. Herfindahl Z is a convex QP (milliseconds, whole grid precomputable); entropy Z is nonconvex but fine offline. Display: Z heatmap under the frontier with the user's vertical line and the knee point.

## Recommendations made in reply (see chat for detail)

- Develop the product in WSL at `~/programming/finance/` (renamed to the product name), as its own repo with a Python engine package plus a Cloudflare Worker, importing the EODHD client pattern from QSE. Keep `Programming/Python/Finance` as the research scratchpad.
- Risk slider = the 95% six-month loss floor; pick the frontier point whose 2.5th-percentile six-month return matches it; show Low/Mean/High from that point's own distribution (normal first, Student-t toggle later), not the fixed 1.65 ratio.
- Return slider is a re-parameterization of the same one-dimensional frontier: trivial, same tensor.
- Name shortlist with domain checks is in the chat reply.
