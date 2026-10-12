# Research report 4: Survey of the "Market Modeling" folder and the two core papers

Date: 2026-10-12. Produced by a file-survey agent (read-only). Path: `C:\Users\jeffr\OneDrive\Documents\Financial\Market Modeling\`.

## 1. File inventory

| File | Size | Date | Description |
|---|---|---|---|
| Optimal Portfolio Diversification Using the Maximum Entropy Principle - Bera Park 2016.pdf | 1.05 MB | 2017-07-21 | Bera & Park, *Econometric Reviews* 27 (2008) 484-512 (file name says 2016; paper is 2008). Cross-entropy portfolio selection. |
| Can Machine Learning Help to Select Portfolios of Mutual Funds 1245_0.pdf | 691 KB | 2022-08-23 | DeMiguel, Gil-Bazo, Nogales, Santos, Barcelona GSE WP 1245, Mar 2021 (later *JFE* 2023). |
| On Entropy.pdf | 605 KB | 2017-10-06 | Pola, "On entropy and portfolio diversification", *J. Asset Mgmt* 17(4) 2016, 218-228. Highly relevant. |
| Risk_Parity_and_Beyond - Deguest Martinellini Meucci 2013.pdf | 546 KB | 2017-07-30 | Deguest, Martellini, Meucci (EDHEC) 2013. Effective number of bets via entropy of PCA factor exposures. |
| How Many Independent Bets Are There - Polakow Gebbie 2008.pdf | 261 KB | 2017-07-30 | Breadth = effective dimensionality of the correlation matrix via SVD/Kaiser-Guttman. |
| Robust portfolio allocation under discrete asset choice constraints - Gulpinar Katata Pachamanova 2011.pdf | 485 KB | 2017-07-30 | Robust MV under estimation error with cardinality/discrete constraints. |
| Construction of an efficient portfolio of power purchase decisions... Contreras 2017.pdf | 1.23 MB | 2017-07-30 | Risk vs entropy-diversification frontier for electricity purchasing, *Energy Economics* 64. |
| The long and active existentialist - Polakow 2011.pdf | 121 KB | 2017-07-30 | Editorial on risk budgeting; non-mathematical. |
| portfolioTheoryMatrix.pdf | 268 KB | 2016-07-28 | Zivot-style "Portfolio Theory with Matrix Algebra" (2013): matrix forms of mean/variance, min-var and frontier formulas. Directly reusable. |
| 1708.07567.pdf | 333 KB | 2017-11-08 | Tee et al. (SigOpt), "Active Preference Learning for Personalized Portfolio Construction", ICML 2017 workshop. Tangential. |
| Comparative Analyses of Stock Returns Properties...pdf | 4.7 KB | 2016-12-22 | Truncated/corrupt download. Unusable. |
| Housing Starts Forecast of Retail Sales...pdf | 486 KB | 2016-12-22 | Not diversification. |
| A Probability Model for Verifying Deterministic Forecasts of Extreme Events - Ferro 2007.pdf | 1.02 MB | 2016-07-27 | Weather-forecast verification via EVT. Tail-risk adjacent only. |
| A novel forecasting method based on multi-order fuzzy time series 2015.pdf | 1.05 MB | 2016-07-27 | Fuzzy time series + GA for index forecasting. |
| Chaos and Deterministic versus Stochastic Nonlinear Modeling - Casdagli 1991.pdf | 1.75 MB | 2016-07-27 | SFI working paper. |
| Suppression of deterministic and stochastic extreme desynchronization events 2013.pdf | 690 KB | 2016-07-27 | Physics; not finance. |
| Best Data Service Analysis 20260130.docx | 100 KB | 2026-01-30 | Claude-generated comparison of market-data APIs (EODHD, FMP, Massive/Polygon, Tradier, Tiingo, FRED) for the options scanner; recommends Tradier + EODHD All-in-One + FRED (~$100-130/mo). |
| Reinvested Dividends Calcs.xlsx | 12 KB | 2015-05-11 | Share/market-value reconciliation of a personal ETF/fund list. |
| Inverse EFTs.csv | 4.8 KB | 2015-04-24 | Google Finance export of ProShares inverse ETFs. |
| S&P500_SPX_20160107.JPG | 149 KB | 2016-01-07 | Chart screenshot. |
| Yahoo Finance Data/ETFs.csv.zip | 0.9 MB | 2022-08-23 | Kaggle-style ETF metadata (category, expense ratio, sector weights, returns, holdings). |
| Yahoo Finance Data/ETF prices.csv.zip | 51.8 MB | 2022-08-23 | Daily OHLC/adj_close/volume per ETF symbol. |
| Yahoo Finance Data/MutualFunds.csv.zip | 19.5 MB | 2022-08-23 | Mutual fund metadata. |
| Yahoo Finance Data/MutualFund prices - A-E / F-K / L-P / Q-Z.csv.zip | 62.6 / 80.0 / 83.1 / 72.5 MB | 2022-08-23 | Daily mutual fund NAV histories. Same date as the DeMiguel paper download, likely intended for replication. |

## 2. The two core papers

### 2a. Bera & Park, "Optimal Portfolio Diversification Using the Maximum Entropy Principle" (*Econometric Reviews* 27(4-6):484-512, 2008)

**Problem.** Mean-variance with sample moments gives concentrated, unstable weights and poor out-of-sample performance (Jobson-Korkie, Michaud's "error maximization"). Shrinkage fixes the inputs; Bera-Park shrink the weights directly.

**Core idea.** Long-only weights are formally a probability distribution. Shannon entropy SE(w) = −Σ wᵢ ln wᵢ is maximal (ln N) at 1/N and zero for a single asset, so it is a diversification measure. The general objective is cross-entropy / KL divergence to a prior portfolio q: CE(w, q) = Σ wᵢ ln(wᵢ/qᵢ). With q = 1/N, minimizing CE is identical to maximizing Shannon entropy. The approximation CE ≈ ½ Σ (wᵢ−qᵢ)²/qᵢ shows it is a weighted squared distance that penalizes deviations in small prior weights most.

**Preliminary (Jaynes) formulation.** Max SE(w) s.t. Σ wᵢ m̂ᵢ = μ₀ and Σ wᵢ = 1 gives closed form wᵢ = exp(−λ m̂ᵢ)/Ω(λ), automatically non-negative. Adding a variance cap makes it non-differentiable, so they generalize.

**General approach (eqs. 14-22).** Objective: min CE(w | q). Constraints: Σw = 1, w ≥ 0, and a utility floor U(w) ≥ τ where U = w'm̂ − (γ/2) w'Σ̂w. The floor τ is chosen from the resampled distribution of maximized utility: bootstrap B samples, solve MV on each, evaluate each on the original moments, take the r-th quantile. r is the investor's "strength of belief" in the sample moments: small r = heavy shrinkage toward q; r → 1 reproduces MV. Solved with gradient-based nonlinear optimization.

**Risk/return trade-off.** The solution is the portfolio closest to q (KL sense) that still achieves at least the r-quantile of plausible MV utilities. In the Michaud 8-country example (γ = 0.06, r = 0.2): MV (σ, μ) = (2.60, 1.13), CE (3.01, 1.15), equal-weight (3.46, 1.17), monthly %. The CE solution slides along the segment between MV and 1/N in mean-sd space. Choosing q = min-variance (CE2) shrinks toward MinV.

**GCE extension for shorting.** Each weight is a discrete-support expectation with its own probability vector; same utility floor.

**Data and evaluation.** 8 MSCI country indexes, monthly USD, Dec 1969-Jul 2005. Rolling windows 24, 48, 60, 120 months. Models: MV, Bayes diffuse, Jorion EB, MinV, 1/N, Michaud RS, CE1 (q = 1/N), CE2 (q = MinV). Metrics: Sharpe and CEQ = m − γ/2 σ².

**Results (OOS, γ = 0.10).** W = 24: 1/N beats MV; CE1 (r = 0.5) CEQ 0.0722, second-best; CE1 weights far more stable than MV. W = 60: CE2 (r = 0.5) best. W = 120: CE2 (r = 0.2) best; the gap narrows as estimation error falls. With short sales, unconstrained MV is uniformly the worst; GCE stays near 1/N. Michaud RS good at small W, deteriorates at large W.

**Claimed advantages.** Shrink weights toward any target; non-negativity automatic; uncertainty captured non-parametrically; one tuning parameter r; extensible to higher-moment utilities.

**Limitations.** Quadratic utility assumed; r must be chosen; depends on q; i.i.d. bootstrap ignores time dependence; only 8 assets; OOS ordering across r not monotone.

### 2b. DeMiguel, Gil-Bazo, Nogales, Santos, "Can Machine Learning Help to Select Portfolios of Mutual Funds?" (Barcelona GSE WP 1245, 2021; *JFE* 2023)

**Method.** Cross-sectional prediction, not weight optimization. Target: fund's next-year realized alpha (36-month rolling FF5+momentum). 17 predictors (lagged alpha, factor-beta t-stats, R², TNA, expense ratio, age, flows, flow volatility, tenure, turnover, value added). Models: OLS, elastic net, random forest, gradient boosting, NN1-NN3. 5-fold CV. Expanding window from 1980-1989, predict 1991, top-decile equal-weighted, hold 12 months, roll through 2018.

**Data.** CRSP survivor-bias-free, US domestic equity, actively managed, no-load share classes: 6,216 share classes, 1980-2018.

**Results.** GB top-decile alpha 29.4-34.8 bp/month (3.5-4.2%/yr), significant; RF 20.3-25 bp; EN and OLS ~7-11 bp, insignificant. GB Sharpe 0.184 vs EW 0.166, OLS 0.150. No single predictor dominates. Rolling 5-year alphas decline; all portfolios converge to negative alpha after 2015.

**Limitations.** Alpha decays; equal weighting within decile; annual rebalancing; no-load only; CRSP not freely available.

## 3. Other relevant documents

- **Pola 2016, "On entropy and portfolio diversification".** Defines "available diversification" and diversification curves: exp(entropy) ("average number of relevant assets") plotted against portfolio volatility for the efficient frontier, in weights, asset-volatility, risk-contribution, PCA and diversification-ratio spaces. Findings: Markowitz portfolios reach at most 5.8 effective assets vs 12 available; diversification and risk are not monotonically related and should be budgeted separately; constraining return to within 10 bp of the frontier at equal volatility and maximizing entropy gives a huge diversification gain at negligible cost; a tunable return penalty δ interpolates between a high-conviction portfolio (8.4% return, entropy-in-risk 3.3) and a risk-parity-like portfolio (6.0%, 11.5). Directly complementary to Bera-Park.
- **Deguest, Martellini, Meucci 2013, "Risk Parity and Beyond".** ENB = exp(entropy of variance contributions across uncorrelated PCA factors). MV with an ENB floor improves OOS risk-adjusted performance and is equivalent to shrinkage toward a minimal-factor-exposure portfolio. Points to minimum-torsion bets.
- **Polakow & Gebbie 2008.** Breadth = number of correlation-matrix eigenvalues ≥ 1.
- **Gulpinar, Katata, Pachamanova 2011.** Robust MV with cardinality and discrete-lot constraints via MIP.
- **Contreras et al. 2017.** Risk-diversification frontier (entropy on PCA factors and on risk contributions) for electricity purchasing.
- No copula, fat-tail-specific, or HRP documents are present.

## 4. Directly reusable in a Python tool

1. Matrix formulas: min-var weights Σ⁻¹1/(1'Σ⁻¹1); frontier via A = 1'Σ⁻¹m, B = m'Σ⁻¹m, C = 1'Σ⁻¹1, D = BC − A²; σ² = (C/D)(μ − A/C)² + 1/C.
2. Cross-entropy allocator (Bera-Park eqs. 21-22) with SLSQP: objective Σ wᵢ ln(wᵢ/qᵢ); constraints Σw = 1, w ≥ 0, w'm̂ − (γ/2)w'Σ̂w ≥ G⁻¹(r); bootstrap loop (B ≈ 500) for the threshold; r as the user slider; q the target.
3. Diversification diagnostics: exp(entropy) of weights, of risk contributions, and of PCA variance contributions (ENB); Kaiser-Guttman eigenvalue count; diversification ratio. Pola's diversification curve as a second panel.
4. Return-penalty diversification sweep (Pola): for each frontier σ, maximize an entropy measure subject to return ≥ frontier return − δ.
5. Evaluation harness: rolling-window OOS backtest with Sharpe and CEQ, Newey-West SEs, 1/N / MinV / resampled baselines.
6. Data: the Yahoo Finance zips give daily ETF/mutual-fund adj_close histories plus metadata.
