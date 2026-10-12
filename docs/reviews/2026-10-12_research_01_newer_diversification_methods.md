# Research report 1: Portfolio allocation methods newer than ~2016 or with strong out-of-sample evidence

Date: 2026-10-12. Produced by a web-research agent for the portfolio risk/return website strategy. Companion to `2026-10-12_strategy_memo_portfolio_risk_return_website.md`.

Scope note: SSRN abstract pages returned HTTP 403 throughout the session, so SSRN-hosted papers (López de Prado 2016/2019, Meucci 2005/2009, Vorobets 2021, Lohre et al. 2020) were verified through journal listings, author mirrors and secondary sources rather than the SSRN page itself. Items not fully verified are flagged inline and collected at the end.

## 1. Hierarchical Risk Parity (HRP) and Nested Clustered Optimization (NCO)

**What they do.** HRP (López de Prado, *J. Portfolio Management* 42(4), 2016, DOI 10.3905/jpm.2016.42.4.059; SSRN 2708678) hierarchically clusters assets on a correlation distance, quasi-diagonalises the covariance, then recursively bisects the tree allocating inverse-variance across sub-clusters. It never inverts the covariance matrix. The original evidence is a Monte Carlo experiment (not real data) in which HRP has lower out-of-sample variance than CLA min-variance and inverse-variance. NCO (López de Prado, "A Robust Estimator of the Efficient Frontier", SSRN 3469961, 2019/2020; also in *Machine Learning for Asset Managers*, CUP 2020) clusters assets, runs an optimizer inside each cluster, then allocates across clusters, and pairs this with MCOS, a Monte Carlo procedure to pick the optimizer with lowest allocation error. The "reduces estimation error by up to 90%" figure comes from a Bloomberg seminar listing, i.e. promotional, not peer-reviewed.

**Evidence for.** Raffinot 2017 ("Hierarchical Clustering-Based Asset Allocation", *JPM* 44(2) 89-99; SSRN 2840729) found clustering-based portfolios more diversified and better risk-adjusted than traditional risk-based methods on three datasets, using a bootstrap model-confidence-set. Lohre, Rother & Schäfer 2020 (Wiley *Machine Learning for Asset Management* ch. 9) find HRP variants "navigate downside risk better, yet at the cost of high turnover." Salas-Molina et al. 2025 (*Computational Economics* 66(6):5189-5206) find HRP beats quadratic optimizers in two of three market regimes. Pfitzinger & Katzke 2019 (Stellenbosch WP14/2019) add box/group constraints.

**Evidence against / "HRP ≈ inverse-vol".** Jain & Jain 2019 (*Risks* 7(3):74): under crude covariance estimates, inverse-volatility is the most robust allocation, HRP sits between inverse-vol and min-variance/max-diversification, and the gains of HRP depend on the covariance forecast model. A 2023 simulation critique (symbolmanipulation.substack.com, "A better benchmark for hierarchical...") reruns López de Prado's Monte Carlo and shows equal-risk-contribution beats HRP (vol 24.5% vs 26.1% vs IVP 30.6%). A 2026 UCEMA working paper (dt928) finds HRP-family Sharpe ratios tightly clustered (0.69-0.75) with no statistically significant winner once multiple testing is corrected. Independent peer-reviewed NCO evaluations are thin.

**Evidence quality:** Medium for HRP as a robust, never-fails allocator; weak for HRP as superior to ERC or inverse-vol with a decent covariance estimate. NCO: low (mostly author simulations). skfolio's NCO deliberately replaces the paper's in-sample outer step with cross-validated predictions.

## 2. Covariance shrinkage and denoising

**Linear shrinkage.** Ledoit & Wolf 2004, "Honey, I Shrunk the Sample Covariance Matrix" (*JPM* 30(4):110-119) and *J. Multivariate Analysis* 88(2):365-411. Implemented in scikit-learn (`LedoitWolf`, `OAS`), PyPortfolioOpt, skfolio, Riskfolio.

**Nonlinear shrinkage.** Ledoit & Wolf 2017, "Nonlinear Shrinkage of the Covariance Matrix for Portfolio Selection: Markowitz Meets Goldilocks" (*RFS* 30(12):4349-4388): shrinks each sample eigenvalue individually; asymptotically optimal for min-variance when N/T is non-negligible. Ledoit & Wolf 2020 "Analytical nonlinear shrinkage" (*Annals of Statistics*) and 2022 "Quadratic shrinkage for large covariance matrices" (*Bernoulli* 28(3):1519-1547) give the fast closed-form QIS estimator. Their review "The Power of (Non-)Linear Shrinking" (*J. Financial Econometrics* 20(1):187-218, 2022) is the best single guide.

**Random-matrix denoising.** Bun, Bouchaud & Potters, "Cleaning large correlation matrices" (*Physics Reports* 666:1-109, 2017; arXiv 1610.08104). López de Prado 2020 popularises Marchenko-Pastur denoising and detoning; skfolio implements both.

**Why this matters more than the optimizer for ~50-100 assets × 1250 days.** N/T ≈ 0.04-0.08 is exactly the regime where sample covariance is full-rank but its smallest eigenvalues are badly underestimated, and min-variance/max-Sharpe weights load on exactly those directions. Jagannathan & Ma 2003 (*J. Finance* 58(4):1651-1684) proved the long-only constraint is itself a shrinkage of the covariance, so in a long-only tool the marginal gain from shrinkage is real but smaller than in long-short; it matters most for max-Sharpe and when caps are loose. Gerber et al. 2022 (*JPM* 48(3):87-102) report Gerber > Ledoit-Wolf on a 9-asset backtest, a tiny universe and co-author-promoted.

**Python:** linear shrinkage everywhere; nonlinear via `nonlinshrink` (PyPI v0.5); no maintained Python QIS port found (MATLAB only), so porting QIS.m (~50 lines) is the realistic path. **Evidence quality: high**, the most replicated result in the area.

## 3. Estimation-error-aware allocation

- **1/N.** DeMiguel, Garlappi & Uppal 2009 (*RFS* 22(5):1915-1953): none of 14 sample-based models consistently beats 1/N; ~3000 months of data needed for 25 assets. A 2025 Pavia thesis replication on 1990-2025 finds the puzzle persists. Rebuttals: Kritzman, Page & Turkington 2010 (*FAJ* 66(2):31-39) show the 1/N result is driven by rolling short-window mean estimates; with plausible long-run means optimization wins, and "optimization of the covariance alone adds value." Kirby & Ostdiek 2012 (*JFQA* 47(2):437-467) show volatility-timing rules with low turnover beat 1/N net of costs. **Takeaway (high quality): the problem is the sample mean, not the optimizer.**
- **Norm constraints / shrinkage of weights.** DeMiguel, Garlappi, Nogales & Uppal 2009 (*Management Science* 55(5):798-812): a bound on the 1- or 2-norm of weights nests Jagannathan-Ma, Ledoit-Wolf and 1/N and often beats them. Cheap to add to a cvxpy model.
- **Optimal combination rules.** Kan & Zhou 2007 (*JFQA* 42(3)); Tu & Zhou 2011; Kan, Wang & Zhou 2022 (*Management Science* 68(3):2047-2068); Lassance, Vanderveken & Vrins 2024 (*JBES* 42(3):875-889). Barroso & Saxena 2022 (*RFS* 35(3):1222-1278) show forecast errors of inputs are predictable from past errors. High evidence; closed-form for unconstrained MV, approximate with long-only caps.
- **Michaud resampling.** Scherer 2002 (*FAJ*) critique; Harvey, Liechty & Liechty 2008 "Bayes vs. Resampling: A Rematch" find a properly computed Bayes player always wins. Patent US 6,003,018 expired ~2019. **Medium-low; superseded.**
- **Bayesian / Black-Litterman / Meucci.** Meucci "Robust Bayesian Allocation" (SSRN 681553, 2005): NIW posterior defines self-adjusting uncertainty sets; result is shrinkage toward GMV. Feng & He, "Factor Investing: A Bayesian Hierarchical Approach" (arXiv 1902.01015) is the clearest modern hierarchical-Bayes allocation paper.
- **Sequential / fully flexible entropy pooling.** Vorobets, "Sequential Entropy Pooling Heuristics" (SSRN 3936392, 2021) and "Causal and Predictive Market Views and Stress-Testing" (SSRN 4444291, 2023). SeqEP fixes Meucci EP's failure mode when views on means and variances/CVaR interact. Methodological contribution; no out-of-sample return evidence claimed. Implementations: `fortitudo.tech` (GPL-3.0), `entropy-pooling` (BSD-3), skfolio `EntropyPooling` (three-stage sequential scheme). **Medium as engineering; none as "beats X out of sample."**

## 4. Diversification measures and optimizers

- **Effective number of bets.** Meucci, "Managing Diversification" (*Risk*, May 2009; SSRN 1358533): exp(entropy) of variance contributions across principal portfolios; extended to minimum-torsion bets by Meucci, Santangelo & Deguest (*Risk* 2015). Useful as a diagnostic; as an objective it is non-convex.
- **Maximum diversification ratio.** Choueifaty & Coignard 2008 (*JPM* 35(1):40-51); Choueifaty, Froidure & Reynier 2013 (*J. Investment Strategies*). Convex after a change of variables; in skfolio and Riskfolio.
- **Entropy/Rényi weights.** Bera & Park is *Econometric Reviews* 27(4-6):484-512, **2008**, not 2016. Lassance & Vrins, "Minimum Rényi entropy portfolios" (*Annals of Operations Research* 299:23-46, 2021) use exp(Rényi entropy) of portfolio returns as a higher-moment risk measure. Herfindahl caps are a special case of the DeMiguel 2-norm constraint.
- **Out-of-sample comparisons 2018-2026.** Torrente & Uberti 2025 (*J. Asset Management* 26(6)): long-only rolling backtests with costs across several risk measures; maximum diversification "highly competitive with, and often better than" minimum risk because min-risk weights are numerically unstable. A 2025 *Computational Management Science* paper shows MDP = volatility risk parity under equicorrelation. arXiv 2407.01550 (2024) reports MDP Sharpe 1.04-1.34 vs risk parity 0.54, low-tier journal, unverified design. Jain & Jain 2019 show max-diversification is among the most covariance-sensitive methods, so pair it with shrinkage. **Medium.** No measure consistently dominates; unconstrained min-variance and max-Sharpe are the least stable.

## 5. Tail-risk-aware optimization

- **CVaR.** Rockafellar & Uryasev 2000 (*J. Risk* 2(3):21-41): CVaR minimisation is an LP over scenarios. **CDaR.** Chekhlov, Uryasev & Zabarankin 2005 (*IJTAF* 8(1):13-58). Both in skfolio, Riskfolio, PyPortfolioOpt (CVaR only).
- **Does fat-tail modelling help out of sample?** Mixed. Shaw 2011 (arXiv 1102.5665) derives multivariate-Student-t VaR/CVaR analytically. A 2012 Student-t-copula VaR backtest on 21 assets (FH Wien WP 068) found all models, Gaussian, t-copula, historical, failed in 2008 because of volatility clustering, not tail shape. Vasiljeva et al. 2025 (*Frontiers Appl. Math. Stat.*; EURO STOXX 50, OOS 2022-2024) report a Student-t copula + eGARCH scenario set delivered lower realised CVaR than mean-variance, single period, weak-to-medium. **Honest summary:** fat tails change measured risk substantially and weights modestly; the consistent out-of-sample win comes from GARCH-type volatility dynamics, not from the copula family.
- **Libraries (status checked Oct 2026):**
  - **skfolio**: BSD-3; active (2.5k stars; paper arXiv 2507.04176, 2025). Ledoit-Wolf/OAS/denoise/detone/Gerber/EW covariance; MeanRisk over 20 risk measures incl. CVaR, EVaR, CDaR, EDaR; HRP/HERC/NCO/Schur; MaximumDiversification; DistributionallyRobustCVaR; Black-Litterman, EntropyPooling, OpinionPooling; VineCopula (R-vine, Gaussian/Student-t/Clayton/Gumbel/Joe pair copulas, Gaussian/Student-t/JohnsonSU marginals) feeding SyntheticData; CombinatorialPurgedCV and WalkForward.
  - **Riskfolio-Lib**: BSD-3; README cites v7.4 (2026). cvxpy ≥1.7.2, Clarabel/SCS. 26 convex risk measures, HRP/HERC/NCO, Black-Litterman, Entropy Pooling, worst-case MV.
  - **PyPortfolioOpt**: MIT; v1.6.0 Feb 2026; "mature, bug-fix only."
  - **cvxpy**: Apache-2.0; v1.9.3 (Sep 2026).
  - **arch** (GARCH, univariate): NCSA; v8.0.0 Oct 2025.
  - **pyvinecopulib**: MIT; v1.0.1 Oct 2026; Python ≥3.11.
  - **copulas** (sdv-dev): now **BUSL-1.1**, not MIT; no Student-t copula. Avoid.
  - **fortitudo.tech**: GPL-3.0. **entropy-pooling**: BSD-3.

## 6. Genuinely new 2022-2026 methods: what is real and what is hype

- **Theory-guided ML allocation.** Jensen, Kelly, Malamud & Pedersen, "Machine Learning and the Implementable Efficient Frontier" (SSRN 4187217; *RFS* 2025): learns weights from a net-of-cost objective, OOS 1981-2020. Credible but institutional scale (thousands of stocks), not transferable to 30-100 ETFs.
- **Virtue-of-complexity line.** Kelly, Malamud & Zhou (*J. Finance* 79(1), 2024) vs Nagel, "Seemingly Virtuous Complexity in Return Prediction" (NBER w34104, 2025) who shows the forecasts collapse to a volatility-timed momentum rule. **Hype-adjacent; unresolved.**
- **End-to-end / decision-focused deep learning.** Zhang, Zohren & Roberts 2020; Uysal, Li & Mulvey 2021; Costa & Iyengar 2023. Newer papers report seed-sensitivity, single OOS windows and survivorship bias (arXiv 2503.13544; 2605.28853), and a 2026 boosted-tree study found predict-then-optimise beat every end-to-end learner (arXiv 2608.23393). **Mostly hype for a retail universe; the sample size cannot support it.**
- **Conformal / robust.** Kato 2024 (arXiv 2410.16333); conditional robust optimisation with conformal guarantees (arXiv 2409.20534). Sound but synthetic evidence. skfolio's DistributionallyRobustCVaR gives most of the practical benefit. **Promising, unproven.**
- **Regime switching.** Nystrup et al. 2017 (*Quant. Finance* 18(1)) and Nystrup, Boyd, Lindström & Madsen 2019 (*Annals of OR*): lower risk and higher return than buy-and-hold after costs using HMM + MPC, sizeable turnover; regime-count testing is statistically fragile. **Medium for volatility reduction, weak for alpha.** EW or regime-adjusted covariance captures most of it.
- **Bayesian hierarchical.** Feng & He 2022: gains are in factor timing, not ETF allocation.

## 7. What works for a retail long-only portfolio of 30-100 stocks/ETFs

Ranked by (evidence strength × transferability) / implementation cost:

1. **Stop using the sample mean for max-Sharpe.** Shrunk means (James-Stein toward the grand mean or CAPM-implied equilibrium returns, i.e. Black-Litterman with no views) or drop μ and run min-variance / risk-based rules. High. Trivial.
2. **Ledoit-Wolf linear shrinkage, and if possible QIS nonlinear; optionally denoise/detone.** High. Low cost.
3. **Keep long-only + per-ticker caps; add a 2-norm (Herfindahl) or 1-norm constraint as a tunable shrinkage knob.** High. Trivial in cvxpy.
4. **Time-varying volatility (EW covariance, half-life 60-120 days, or GARCH scaling).** High for risk reduction. Low cost.
5. **CVaR and CDaR as alternative objectives/constraints on a scenario set.** Medium. Low with skfolio/Riskfolio.
6. **Risk-based allocators as benchmarks: inverse-vol, ERC, max-diversification, HRP.** Medium; none dominates, all beat unshrunk max-Sharpe out of sample. HRP is the "never fails" option, not the best. Low.
7. **Report effective number of bets and CVaR/σ ratio as diagnostics.** Trivial.
8. **Monte Carlo with Student-t / vine copula for "true risk" display and stress tests; optionally sequential entropy pooling for views.** Medium for measurement, weak for allocation. Medium cost.
9. **Walk-forward / combinatorial purged CV with a 1/N and inverse-vol baseline** before trusting any of the above.
10. **Not worth it at this scale:** NCO beyond a toggle, Michaud resampling, end-to-end deep learning, virtue-of-complexity models, HMM regime switching unless the turnover is acceptable.

## Could not verify

- SSRN pages (2708678, 3469961, 681553, 1358533, 3936392, 3513399) returned 403.
- Exact latest versions of skfolio and Riskfolio-Lib.
- Methodology of arXiv 2407.01550; numeric OOS tables of the Springer and Frontiers 2025 papers.
- Whether a published independent evaluation of NCO on a developed-market universe exists.
- Publication venue of Raffinot's HERC paper (SSRN 3237540, 2018).
- The user's "Bera & Park 2016" file is the 2008 *Econometric Reviews* paper.
