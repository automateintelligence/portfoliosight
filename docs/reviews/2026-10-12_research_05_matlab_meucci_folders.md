# Research report 5: Survey of the MATLAB "Dynamic Portfolio Entropy Pooling" and "Efficient Frontier" folders

Date: 2026-10-12. Produced by a file-survey agent (read-only).

Headline: both folders are almost entirely Attilio Meucci's published reference code (symmys.com / MATLAB File Exchange, BSD-licensed, dated 2006-2015), not the user's own scripts. No file was modified by the user (the Oct 2025 dates are OneDrive sync). No script implements "move along the frontier by maximum entropy."

## Folder 1: `C:\Users\jeffr\OneDrive\Documents\MATLAB\Dynamic Portfolio Entropy Pooling\`

Contents: three Meucci code bundles + three SSRN PDFs + a `.mltbx` toolbox file.

### 1a. `EntropyPooling\EntropyPooling\` (Meucci 2008, "Fully Flexible Views", Risk Oct 2008; SSRN 1213325)

- **`EntropyProg.m`** (core, identical in all three case-study dirs): the Entropy Pooling change of measure. Given prior scenario probabilities `p` (J×1), inequality views `A*p_ ≤ b`, equality views `Aeq*p_ = beq`, it minimizes relative entropy `Σ p_ (ln p_ − ln p)` subject to the view constraints. Solved in the dual with `fminunc`/`fmincon`, analytic gradient and Hessian. Posterior: `p_ = exp(ln p − 1 − A'l − Aeq'v)`. Directly portable to scipy.
- `AnalyticalVsNumerical\S_MAIN.m` + `Prior2Posterior.m`: validates numerical EP against the closed-form normal case (views on mean and covariance), a Black-Litterman-like update without BL's uncertainty parameters.
- `RankingInformation\S_MAIN.m`: ordinal views `E[X_lower] ≤ E[X_upper]` via `ViewRanking.m`; confidence blend `p_ = (1−c)p + c p_`; `EfficientFrontier.m` builds a scenario-based long-only MV frontier via `quadprog` before and after the view. `RobustEfficientFrontier.m` is a CVX SOCP (max μ'w s.t. ‖LE·w‖ ≤ t, ‖GF·w‖ ≤ σ_target), present but not called. `ImpliedExpRets.m` reverse-engineers equilibrium returns. Data: `ReturnsDistribution.mat` (7.7 MB).
- `ButterflyTrading\S_MAIN.m`: options case study (MSFT/YHOO/GOOG butterflies), Black-Scholes repricing, views on implied vol, realized vol (a view on a median via an indicator-expectation constraint), curve slope; opinion pooling with weights [.35 .2 .25 .2]. `LongShortMeanCVaRFrontier.m` + `ComputeCVaR.m`: long/short delta-neutral zero-budget frontier; CVaR is reported, not optimized. `PriceFly.m` has an acknowledged bug comment (`VP=VC; this is incorrect`).

### 1b. `Meucci - Minimum Torsion Bets\` (companion to SSRN 2276632)

- **`torsion.m`**: `'pca'` (eigenvectors) or `'minimum-torsion'` with `'approximate'` (`t = diag(σ)·C^{-1/2}·diag(1/σ)`, Procrustes) or `'exact'` (iterative recursion: init d=I; u = (d c² d)^½; q = u⁻¹ d c; d = diag(diag(q c)); π = d q; stop when Frobenius change < 1e-8; then `t = diag(σ)(π/c)diag(1/σ)`).
- **`EffectiveBets.m`**: diversification distribution `p = (t'\b) .* (tΣb) / (b'Σb)` and Effective Number of Bets `ENB = exp(−Σ p ln p)`.
- `S_MainDiversification.m`: equal-weight S&P 500 (`LinRet.mat`, 2 MB, no tickers), ENB under PCA vs minimum-torsion, plus Euler marginal risk contributions.

### 1c. `Meucci Nicolosi _ Dynamic Portfolio Management - Matlab Code\` (SSRN 2583612, 2015)

"Dynamic Entropy Pooling": risk drivers follow a multivariate Ornstein-Uhlenbeck process; views at future horizons; optimal exposure under mean-variance utility with market impact, solved by dynamic programming.

- `MVOU_Prior.m`: closed-form joint mean/cov at monitoring times. `MVOU_Posterior.m`: conditional Gaussian posterior given linear views (the normal special case of EP). `BellmanEq_CS1.m`/`CS2.m`: backward Bellman recursion with quadratic market impact η, risk aversion γ, discount λ. `QuadraticMat_Vc.m`: calculus-of-variations alternative.
- `S_CaseStudy1.m` (10y rate, view −50 bp in 1 year), `S_CaseStudy2.m` (10y rate + TIPS spread, two non-synchronous views). Data: `CalibratedParameters.mat`, simulated daily paths, saved results. All complete.

### 1d. The PDFs

- **`SSRN-id2276632.pdf`** (18 pp): Meucci, Santangelo & Deguest, *Risk Budgeting and Diversification Based on Optimized Uncorrelated Factors* (rev. Nov 2015; Risk 2015). **Not an Entropy Pooling paper**; it is the Minimum-Torsion paper matching folder 1b. Core: portfolio return R = b'F on k correlated factors; find a torsion t so F̃ = tF are uncorrelated; diversification distribution p_k = Var(b̃_k F̃_k)/Var(R) (non-negative, sums to 1); **ENB = exp(−Σ p_k ln p_k)** from 1 (concentrated) to k (uniform); generalization (Σ p^α)^{1/(1−α)}, α=2 is inverse Herfindahl. Minimum-Torsion t_MT = argmin NTE(tF ‖ F) s.t. Corr(tF)=I: the uncorrelated factors closest to the originals. Solution via Riccati root of the correlation matrix and an alternating Procrustes recursion (~a dozen iterations). Claimed advantages over PCA bets: scale-invariant, unique, interpretable, stable; equal-weight homogeneous market gives ENB = n (PCA gives 1). Advantages over Euler contributions: always non-negative, no spurious cross-correlation term. Case studies: 392 S&P 500 stocks; five Fama-French factors + residual 2003-2015.
- `SSRN-id1213325.pdf`: "Fully Flexible Views: Theory and Practice", Meucci, Dec 2010 rev. Behind folder 1a.
- `SSRN-id2583612.pdf`: "Dynamic Portfolio Management with Views at Multiple Horizons", Meucci & Nicolosi, Apr 2015. Behind folder 1c.

## Folder 2: `C:\Users\jeffr\OneDrive\Documents\MATLAB\Efficient Frontier\`

### 2a. `AMeucciRiskandAssetAllocationRoutines\`: the full companion library to *Risk and Asset Allocation* (Springer 2005), ~250 scripts, Feb 2014 snapshot

Ch1-5, 7, 8 are pedagogical (distributions, copulas, invariance tests, PCA/factor reduction, horizon projection, shrinkage/robust/EM estimators, stochastic dominance, utility, VaR/ES contributions, NIW Bayesian estimation, MCMC). Allocation-relevant parts:

- **Ch6_OptimizingAllocations**: `EfficientFrontier.m` (several near-identical copies): long-only MV frontier, `quadprog` min-variance for NumPortf equally spaced target returns. `ComputeFrontier.m`/`ChoiceOptimal.m`: closed-form two-fund frontier; `Satisfaction.m`: CE of exponential utility. `S_DiversificationCorrelation.m`, `S_DiversificationNumAssets.m`: textbook diversification plots. `Log2Lin.m`/`MktProjection.m`: compounded-to-linear moments. `C_TotalReturnVsBenchmark`: tracking-error frontier. `D_CaseStudy\S_CaseStudy.m`: two-step allocation, MV frontier then pick by Monte Carlo power-utility satisfaction (γ=−9, 100k scenarios).
- **Ch9_OptimEstimationRisk**: `B_BlackLittAllocation\S_BlackLitterman.m`: standard BL posterior; `S_AssessNModifyViews.m`: Mahalanobis/χ² view test. `A_BayesAllocation`: NIW conjugate posterior. `C_RobustAllocation\RobSocpMVPortf.m`: robust MV as SOCP in SeDuMi. `D_RobustBayesAllocation\S_RobustBayesSnP.m`: robust Bayesian allocation, pick max μ₁'w − γ_m √(w'Σ₁w) s.t. w'Σ₁w ≤ γ_s with χ² radii; rolling 52-week backtest on `SectorsSnP500.mat`.
- **Extras\COP\S_COP.m**: *Beyond Black-Litterman* (2006) copula-opinion pooling on a Treasury curve; t-copula prior via `FitT.m`/`EMforT.m`; views as marginal CDFs blended with confidence c.

### 2b. `Meucci_RobustBayesian\`: standalone (2006/2011) version of the robust-Bayesian code. Complete.

## Does anything move a portfolio "up/down the risk axis" by maximum entropy?

**No.** Every frontier is traced by `quadprog` minimum variance over a grid of target returns (or target vols in `RobustEfficientFrontier.m`). The risk position is chosen by a fixed index, a utility certainty-equivalent, or a robust-Bayesian worst-case objective. Entropy appears in exactly two places: (1) `EntropyProg`, relative entropy minimized over scenario probabilities (views), which shifts the whole frontier rather than selecting a point on it; (2) `EffectiveBets`, entropy of risk contributions as a diversification score, computed for a given b but never used as an objective. A "max-ENB along the frontier" rule would be a new combination; the ingredients are all present.

## Reusable in Python

`EntropyProg` (dual with analytic gradient/Hessian, ~40 lines in scipy), `torsion` + `EffectiveBets` (pure numpy with `sqrtm`, ~15 lines), the BL and NIW posterior formulas, `RobustEfficientFrontier` SOCP (cvxpy), `ComputeCVaR`, `Log2Lin`/`MktProjection`, `MVOU_Prior/Posterior`. Data `.mat` files load with `scipy.io.loadmat`; only `SectorsSnP500.mat` has dates.

## Notable

- The folder named "Dynamic Portfolio Entropy Pooling" contains the Minimum-Torsion PDF as its largest paper, and the "Efficient Frontier" folder is the entire textbook code base; naming is by download session, not topic.
- `EfficientFrontier.m` exists in ~8 slightly different versions; one in `D_RobustBayesAllocation` has an off-by-one target grid.
- All timestamps are 2014-2016; no Python port of this material exists.
