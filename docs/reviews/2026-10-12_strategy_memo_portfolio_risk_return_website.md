# Portfolio Risk/Return Website: Research Findings and Strategy Memo

Date: 2026-10-12. Responds to the questions in `portfolio_risk_return_analysis_website.md`.
Sources: six parallel surveys (your MATLAB folders, Market Modeling PDFs, Quantopian lectures and repo scripts, literature 2016-2026, Cloudflare architecture, competitive landscape). Detailed agent reports are summarized here; claims about the literature carry the citation the agent found.

---

## 1. What you already have (and what you do not)

| Location | What it is | Status |
|---|---|---|
| `MATLAB/Dynamic Portfolio Entropy Pooling/` | Verbatim Meucci public code (BSD): Entropy Pooling / Fully Flexible Views (`EntropyProg.m`, SSRN 1213325), Minimum-Torsion Effective Number of Bets (`torsion.m`, `EffectiveBets.m`, SSRN 2276632), Dynamic Entropy Pooling with views at multiple horizons (Meucci-Nicolosi 2015, SSRN 2583612) | Complete, runnable, 2014-2016. No code of your own. |
| `MATLAB/Efficient Frontier/` | The entire *Risk and Asset Allocation* companion library (~250 scripts): long-only MV frontier, Black-Litterman, NIW Bayesian, robust SOCP, robust-Bayesian allocation, copula-opinion pooling | Complete textbook code. |
| `Financial/Market Modeling/` | Bera & Park (Econometric Reviews 2008, not 2016): cross-entropy weight shrinkage. DeMiguel et al. 2021: ML fund selection. Pola 2016 "On entropy and portfolio diversification". Deguest-Martellini-Meucci 2013 "Risk Parity and Beyond". Polakow-Gebbie 2008 breadth. Zivot matrix-algebra chapter. 300 MB of 2022 Yahoo ETF/mutual-fund price zips. | Papers only. |
| `Python Scripts/.../Position_Concentration_Risk` | Conceptual lecture: N uncorrelated bets reduce vol by 1/sqrt(N). No Herfindahl/effective-N code. Sibling lectures `Estimating_Covariance_Matrices` (Ledoit-Wolf) and `VaR_and_CVaR` (historical CVaR) have drop-in functions. | Reusable snippets. |
| `Python Scripts/.../quantopian_research/drafts/kelly/` | Two 2017 drafts: Gaussian Kelly leverage (mean excess return / variance) on SPY tied to a cvxopt frontier, and a `KellyLeverage` class for Kalman pairs. No fat-tailed or fractional Kelly. | Quantopian-API bound; formulas portable. |
| `Finance/Portfolios/` | `asset_class_allocation*.py` are broker-CSV rebalancers (dead APIs). `EF_with_ME_Slider.txt` (Sep 2017) is a 5-step plan: 401(k) tickers, EF with expense ratios, **"use Maximization of Entropy to trade off some expected return for diversification"**, a slider, an age-aware suggestion. Two TODO comments "import EFT + Entropy method here (or example from matlab!!!)". | Plan only, never implemented. |
| `Finance/efficient_frontier_portfolio.py` | The working tool built this week: total-return MV frontier, max-Sharpe, same-risk/same-return, halfway, caps, run tracking. | Working. |
| `Finance/Risk_Questionnaire_Analysis_v3/` | Prospect-theory bracketing questionnaire producing a 1-99 Risk Number with normal and Student-t (df=5) 95% six-month ranges. | Working, not wired to anything. |

**Direct answer:** no script, MATLAB or Python, optimizes "up-down along the risk axis" with maximum entropy. In Meucci's code entropy plays two unrelated roles: relative entropy of scenario probabilities (Entropy Pooling, a way to impose views) and entropy of the diversification distribution (Effective Number of Bets, a diagnostic). Every frontier is traversed by a grid of target returns. The idea in your 2017 plan file is exactly Bera-Park 2008 (shrink weights toward 1/N by minimizing KL divergence subject to a utility floor) and, more usefully, Pola 2016's "diversification curve": at each frontier volatility, maximize entropy subject to return >= frontier return minus a tolerance delta. Neither was ever coded. The ingredients are all present, so this is a small build, not research.

## 2. What the 2016-2026 evidence says is actually better

Ranked by evidence strength times transferability to a 20-100 asset long-only retail portfolio:

1. **Stop using the sample mean in max-Sharpe.** This is the single largest source of the ugly corner solutions you saw (85% DBJP in run r006, 21% GEV in r003). Shrink means toward the grand mean or CAPM-implied returns (Black-Litterman with no views), or use risk-based rules that ignore the mean. Evidence: DeMiguel-Garlappi-Uppal 2009, Kritzman-Page-Turkington 2010, Kan-Wang-Zhou 2022, Barroso-Saxena 2022. High.
2. **Ledoit-Wolf shrinkage covariance** (linear is one line in scikit-learn; nonlinear/QIS 2020-2022 is a 50-line port). Evidence: high and replicated. Note Jagannathan-Ma 2003: your long-only constraint is already a form of covariance shrinkage, so gains are real but moderate.
3. **Norm constraints on weights** (2-norm / Herfindahl cap) as a tunable shrinkage knob. DeMiguel et al. 2009 Management Science. High evidence, trivial in a QP, and this is the convex cousin of Bera-Park entropy (Renyi alpha=2 entropy is inverse Herfindahl).
4. **Time-varying volatility** (exponentially weighted covariance, 60-120 day half-life). The 2012 t-copula VaR backtests found every model, Gaussian or fat-tailed, failed in 2008 because of volatility clustering, not tail shape. High evidence for risk measurement.
5. **CVaR and conditional drawdown as objectives/constraints** (Rockafellar-Uryasev 2000; Torrente-Uberti 2025). Medium.
6. **Risk-based allocators as benchmarks**: inverse-vol, equal risk contribution, maximum diversification (Choueifaty), HRP. None dominates; all beat unshrunk max-Sharpe out of sample. HRP is the "never fails" option, not the best one (Jain & Jain 2019; a 2026 UCEMA paper finds no significant winner after multiple-testing correction). Medium.
7. **Effective Number of Bets and CVaR/sigma as displayed diagnostics.** Not predictive, but exactly the "diversification score" a user can understand.
8. **Student-t / vine-copula Monte Carlo for measurement and stress tests.** Changes measured risk a lot, changes weights only modestly. Medium for measurement, weak for allocation. Use it for the risk report, not the optimizer.
9. **Walk-forward validation with 1/N and inverse-vol baselines** before trusting any of the above.
10. **Not worth it here:** Nested Clustered Optimization beyond a toggle, Michaud resampling (superseded, Harvey-Liechty 2008), end-to-end deep learning (150-300 monthly decisions cannot support it; 2025-2026 papers report seed sensitivity), virtue-of-complexity models (Nagel 2025 rebuttal), HMM regime switching unless you accept the turnover.

Libraries (checked Oct 2026): **skfolio** (BSD-3, active, scikit-learn style; has Ledoit-Wolf, denoise/detone, CVaR/CDaR, HRP/HERC/NCO, max-diversification, Entropy Pooling, VineCopula + SyntheticData, walk-forward CV) is the one to standardize on. Riskfolio-Lib (BSD-3) is the alternative. PyPortfolioOpt is bug-fix only. `copulas` (sdv) switched to BUSL, avoid. `pyvinecopulib` MIT.

## 3. Recommendation: the new script

Name: **`diversified_frontier_portfolio.py`** (keeps `efficient_frontier_portfolio.py` as the classical baseline so runs stay comparable in the run log).

What it adds, in order of value per hour:

1. **Robust inputs.** Ledoit-Wolf covariance (option: exponentially weighted) and shrunk expected returns (James-Stein toward grand mean, with a `--mean-shrink` dial from 0 = sample to 1 = all assets equal). Everything downstream, including the existing frontier, uses these.
2. **Diversification dial along the risk axis** (Pola 2016 + Meucci ENB). For each target volatility on the frontier, solve: maximize ENB (minimum-torsion diversification distribution) subject to expected return >= frontier(sigma) - delta, long-only, caps. Sweep delta to draw a second curve, the diversification curve, and report ENB next to every portfolio ("your portfolio behaves like 4.2 independent bets out of 89"). The user's "Diversification Optimized" point is the solution at their target vol and chosen delta. This is the toggle you described, as a continuous dial.
3. **Convex proxy for the browser.** ENB is non-convex; for the website use minimize Herfindahl of risk contributions (or 2-norm of weights) with the same return floor. That is a QP, solvable in JavaScript in under a millisecond, and consistent with the Python version (Renyi-2 entropy). Validate the proxy against the Python ENB solution nightly.
4. **Risk Number integration** (see section 4) so the tool can take a Risk Number instead of a holdings file as the "where on the frontier" input.
5. **Tail-risk report** (section 5): Student-t Monte Carlo six-month range, historical CVaR, and three historical stress windows (2008, Mar 2020, 2022).
6. **Walk-forward evaluation mode**: rolling 3-year fit, 6-month hold, report realized Sharpe and realized 95% range coverage for classical, diversified, 1/N and inverse-vol. This is what lets you say "provably better" on your own data instead of citing papers.

Bera-Park cross-entropy (shrink weights toward 1/N with a resampled utility floor) is worth adding as an alternative objective behind a flag, but Pola/ENB maps more directly to a slider and to the "same risk" framing already in the tool.

## 4. Integrating the risk questionnaire

The questionnaire already outputs what the frontier needs. Mapping:

- Risk Number -> six-month sigma from the v2 table (Risk 50: mean 3.5%, sigma 5.7%; Risk 75: 11.0%). Annualize: sigma_annual = sigma_6mo * sqrt(2), so Risk 50 is about 8% annual vol and Risk 75 about 15.5%. That becomes `--target-vol`, and the tool returns the max-return and diversification-optimized portfolios at that vol, plus the user's current portfolio's implied Risk Number by inverting the same table.
- Show **two numbers, not one**: risk tolerance (questionnaire) and risk capacity (time horizon, which you already collect as Q1). Kitces' standing critique of Riskalyze is that it conflates the two; separating them answers the critique and is a differentiator.
- Replace the table's normal and Student-t(5) ranges with ranges computed from the actual portfolio's return distribution (section 5), while keeping the table as the default for anonymous users who have not entered holdings.
- Nitrogen's alignment rule (portfolio Risk Number within 5-10 points of the person's) becomes the "are you in your lane" gauge on the page.
- Default for anonymous visitors: Risk 50, as you proposed, which lands at roughly 8% annual vol. On the 2017 Step 2 universe (run r006) the current Step 2 allocation sits at 8.5% vol and 4.8% return, so the default is self-consistent.
- Caution: Nitrogen markets the Risk Number as patented. No patent number was found, only trademarks on "Risk Fingerprint" and "Risk Score", and the prospect-theory elicitation is academic prior art. Do not clone their exact gamble screens or the words "Risk Number"; "Risk Score" is also trademarked. Pick your own name.

## 5. Copulas and Monte Carlo: measurement, not optimization

Use the split you wrote, with one correction from the evidence: what breaks static models in a crash is volatility clustering, not the tail shape, so an exponentially weighted or GARCH-scaled covariance matters more than the copula family.

Tiered plan:

- **Tier 1 (ship first, browser-capable):** multivariate Student-t Monte Carlo with df 4-5 on the shrunk covariance: draw z ~ N(0, Sigma) via Cholesky, scale by sqrt(df / chi-square). Produces the 95% six-month range, CVaR, and probability of breaching the user's devastation threshold. Trivial in JS.
- **Tier 2 (Python nightly batch):** skfolio VineCopula with Student-t pair copulas and Student-t or Johnson-SU marginals, fit per ticker universe, generating scenario sets. Precompute quantiles for popular menus. Use for stress tests and for CVaR-constrained variants of the diversified frontier.
- **Tier 3 (research):** Entropy Pooling / Sequential Entropy Pooling (Vorobets 2021, fortitudo.tech GPL or skfolio's EntropyPooling) to impose views or stress scenarios on the scenario set, then re-run the frontier. This is the actual use of your MATLAB EP code.
- Historical stress windows (what did this allocation do in 2008, Mar 2020, 2022) cost nothing, need no distributional assumptions, and are the most convincing display for users.

Please point me to the spreadsheet simulations you mentioned so the Tier 1 assumptions match what you have already validated.

## 6. The website

**Architecture** (from the Cloudflare research): the QP is small, so the browser is the cheapest and fastest executor. Static front end on Cloudflare Pages with tree-shaken ECharts (under 100 KB gzipped) and the `quadprog` JS port (Goldfarb-Idnani, MIT) for the frontier, max-Sharpe via the convex transform, Herfindahl-constrained diversified portfolio, and Student-t Monte Carlo. One JS Worker serves a compact returns matrix from KV with R2 as canonical store, a Durable Object de-duplicating vendor fetches, and a nightly Cron Trigger refreshing active tickers. Python (scipy, skfolio) runs only in a nightly batch, in a Cloudflare Container or a $2-5/month Fly machine, to precompute popular menus, run the copula tier, and unit-test the JS solver against Python. Python Workers went GA in Sep 2026 but have about 1 s cold starts and 128 MB, fine for batch, wrong for interactive. Free plan covers 100k requests per day.

**Data license is the real recurring cost and the one hard blocker.** yfinance is explicitly personal-use only and Yahoo's terms forbid it; every vendor's listed price is a personal/internal license, and displaying derived figures to anonymous visitors counts as display/redistribution. Tiingo ($50/mo internal-commercial, sales quote for display; 60k funds) and EODHD (B2B plans; US mutual funds from $59.99/mo) are the two with mutual-fund coverage for 401(k) tickers like VTSAX and FXAIX. Massive (ex-Polygon) is explicit that any app showing its data needs a Business plan. Get a written quote naming "display to end users of a website" before building.

**Compliance:** keep it impersonal (Lowe v. SEC publisher exclusion; "impersonal investment advice" in SEC rules). Portfolio Visualizer's wording is the template: "educational only, not investment advice, hypothetical, not registered with the SEC". Design consequences: label outputs as mathematical results of historical data, no recommendations keyed to age or goals, no account linking, a generic CTA to the scanner rather than "based on your portfolio we suggest". Have a securities attorney review before the paid tier.

**Competitive position:** nobody on the retail side pairs an arbitrary-ticker efficient frontier with a behaviorally derived risk score and a mapping back to an allocation. Nitrogen does it only through advisors; Empower only at six asset classes with account linking; Portfolio Visualizer paywalled in May 2024 (15-asset free cap, $30-55/month) and bled users to testfol.io; PortfoliosLab is the closest free optimizer but form-submit, no risk score. Blooom, the only 401(k) menu optimizer, shut down in Nov 2022. "Paste your plan's fund list, get the best mix for your risk score" is open and searchable.

## 7. Pushback

1. **Audience mismatch is the biggest risk to the business goal.** People searching "401k fund optimizer" are Bogleheads-adjacent and often hostile to options; options-scanner buyers search "IV rank" and "credit spread screener". Keyword overlap is near zero. Portfolio Visualizer's own history shows a huge free audience that would not pay even for the same product. Expect conversion well under 1% unless the paid product is reframed. The fix is a bridge, not a better frontier: a **"protect this portfolio" calculator** (cost of a six-month protective put or zero-cost collar on the user's top holdings, shown as a floor on the left tail of their 95% range) and a **covered-call overlay** ("yield on your risk score"). Those are the only options concepts the buy-and-hold crowd already wants, no standalone tool takes a whole portfolio as input, and the scanner then becomes "find the strikes for the overlay you just saw".
2. **Do not lead with the "Max Return" point.** Unshrunk max-Sharpe on five years of data is a corner solution driven by estimation error (two positions in r006). A public tool that tells a visitor to put 85% in a hedged-Japan ETF is a credibility problem. Show it, but after shrinkage and caps, and label it as the historical frontier.
3. **What does the slider move?** "Change the portfolio allocation in real time" is one slider per asset; that is a table, not a slider. The slider that makes the page work is the risk score / target volatility: drag it and the diversification-optimized and max-return points slide along the frontier, the 95% range and the trade list update, and the current portfolio stays put as the reference. The allocation table edits the current portfolio.
4. **"Diversification Optimized could just be Current"** only if the current portfolio happens to be on the diversification curve. Better to keep it as its own point and show the gap, since the gap is the product.
5. **The questionnaire is 15 emails long.** For an anonymous free tier the Risk 50 default plus a 4-question short form (horizon, devastating loss in dollars, one percent gamble, one dollar gamble) gets within about 10 points; keep the full bracketing for the registered tier.
6. **Static five-year window.** Your results today are dominated by the 2021-2026 regime (GEV, NVDA, UNCRY). Offer 1/2/3/5/10 year windows and an exponentially weighted option, and show the frontier for each so users see how unstable the "optimal" point is. That instability is itself the argument for the diversified point.
7. **MATLAB port scope.** Everything in those folders is Meucci's BSD code, so porting is fine, but only `torsion.m`, `EffectiveBets.m` and `EntropyProg.m` (about 100 lines total) are needed. Do not port the toolbox.

## 8. Ideas worth stealing or inventing

- **One memorable number**: "Your portfolio = 4.2 independent bets" (ENB) next to the risk score. Shareable, defensible, and nobody shows it.
- **Risk lane graphic**: the screenshot's 95% line, with a second translucent band for the fat-tail range and a marker for the user's devastation threshold.
- **Halfway trade list with turnover and estimated tax drag**, already in the Python tool, as the default call to action: "move 29% of the portfolio, get half the improvement". Nobody offers the partial move.
- **URL-encoded portfolios** so every result is a link. Portfolio Visualizer's most-cited feature.
- **Programmatic SEO on 401(k) menus**: a page per plan provider and per common fund set (TSP, Fidelity BrokerageLink, Vanguard target-date lineups) precomputed nightly in the Python batch. Blooom's exit left this empty.
- **Three historical stress cards** (2008, Mar 2020, 2022) under the chart. Cheap, assumption-free, convincing.
- **Monthly "still in your lane?" email** when the portfolio's implied risk score drifts out of the 5-10 point band. List growth and the natural moment to pitch a hedge.
- **Regime slider**: 3/5/10-year windows as a visible control, with ghost frontiers, which turns estimation instability from an embarrassment into a feature.

## 9. Proposed sequence

1. Build `diversified_frontier_portfolio.py` (sections 3-5, Tier 1 tail risk) and run it on r003 and r006 so the diversified point, ENB, risk-score mapping and 95% ranges exist in Python with a walk-forward comparison against 1/N and inverse-vol.
2. Get the data-license quote (Tiingo and EODHD) and a one-page compliance checklist.
3. Then write the website spec: pages, the risk-score short form, the browser solver contract (inputs: returns matrix, caps, target vol, delta; outputs: weights, ENB, ranges), the Worker/KV/R2 data path, the hedge calculator as the bridge to the scanner.
