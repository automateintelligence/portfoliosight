# Research report 6: Survey of the Quantopian lectures and the Finance/Portfolios repo scripts

Date: 2026-10-12. Produced by a file-survey agent (read-only).

## 1. Position_Concentration_Risk lecture

File: `C:\Users\jeffr\OneDrive\Documents\Python Scripts\Finance\quantopian_research\notebooks\lectures\Position_Concentration_Risk\notebook.ipynb` (Quantopian, Margenot & Granizo-Mackenzie, 2017, Python 2).

**Argument.** Concentration risk is "too few independent bets." Blackjack analogy (51% edge, binomial simulation across 1,000 universes) shows mean edge grows linearly in N while std grows as sqrt(N). Transposed to portfolios: one asset = full exposure; N assets that are all asset 1 + noise give portfolio vol ≈ mean asset vol; N independent assets give vol falling with 1/sqrt(N). Closing points: hold as many uncorrelated assets as capital allows; even 20 relatively uncorrelated names beats fewer; std is not a great risk metric for non-normal returns.

**Method.** No Herfindahl, effective-N, or max-weight rule. Only the n-asset variance identity with hand-built covariance matrices.

**Reusable code.** `var_p = w @ cov @ w.T`, the 1/sqrt(N) sweep loop, `generate_portfolio(n)` for a synthetic PSD covariance. Conceptual, not an optimizer.

## 2. Sibling lecture folders

All 49 folders listed; flagged as relevant: Estimating_Covariance_Matrices, VaR_and_CVaR, Statistical_Moments, Instability_of_Estimates, Portfolio_Analysis, Leverage, Factor_Risk_Exposure, Beta_Hedging, ARCH_GARCH_and_GMM, Why_Hedge_I/II, Long-Short_Equity. None covers copulas, Monte Carlo portfolio simulation, risk parity, HRP, Black-Litterman, or an actual optimizer (the cvxopt Markowitz material lives in `quantopian_research/research/Markowitz-blog.ipynb` and the Stanford lecture notebook).

- **Estimating_Covariance_Matrices**: sample covariance is unstable (especially T < N); demonstrates Ledoit-Wolf via `sklearn.covariance.ledoit_wolf(returns)[0]`, in- vs out-of-sample error on 6 and ~50 tickers month by month. Directly reusable: swap `returns.cov()` for Ledoit-Wolf.
- **VaR_and_CVaR**: historical VaR `np.percentile(port_rets, 100*(1-alpha))*value`, normal VaR for contrast, CVaR as the mean below VaR; argues for historical CVaR because of fat tails; checks lookback convergence (~400-600 days) and ADF stationarity. `value_at_risk()` and `cvar()` are drop-in.
- **Statistical_Moments**: skew/kurtosis, SPY leptokurtic, Jarque-Bera test.
- **Instability_of_Estimates**: rolling mean/std/Sharpe drift; a 90-day rolling Sharpe on AMZN swings by a quarter of its range. Underpins the "directional, not literal" warning.
- **Portfolio_Analysis**: pyfolio/empyrical tear sheet; `empyrical` functions reusable.

## 3. `C:\Users\jeffr\Programming\Python\Finance\Portfolios\`

- **README.md**: "code-only script for calculating portfolio rebalancing buy/sell orders."
- **example_portfolio.txt**: a 35-ticker Vanguard/Schwab ETF list (VTV ... EDV), the 401(k)-style universe.
- **asset_class_allocation.py (2019) / _v3.py (2017)**: rebalancing calculators, not optimizers. Parse broker exports (Merrill CSV, Wells Fargo XLS), read a hand-entered desired-allocation pickle (originally pasted from Excel via `win32clipboard`), pull prices via `pandas_datareader` + `fix_yahoo_finance`, compute a short-window std, iterate whole-share buy/sell orders above a $500 minimum with limit prices at price ± 1σ, net a cash distribution. The only entropy reference is a comment: `# Rather than clipboard, should import EFT + Entropy method here. (Or example from matlab!!!)` (line 167 / 134). v3 is half-refactored and would raise NameError; the 2019 version has a `pytest.set_trace()` in the price loop and dead data APIs. Not runnable without a data-layer rewrite.
- **EF_with_ME_Slider.txt (Sep 2017)**: a 5-step plan stub: (1) user enters 401(k) tickers, (2) Markowitz EF including expense ratios, (3) "Use Maximization of Entropy method to trade off some expected return for diversification", (4) slider for risk/return, (5) age/income-based suggested allocation; a note about replacing EF+ME with a neural net. Code is just the import header from the cvxopt Markowitz blog notebook. **No max-entropy math exists in Python anywhere.**
- **EWMASTD.py (2017)**: a Quantopian algorithm: Carver-style EWMAC trend system, vol targeting via `pd.ewmstd`, an instrument diversification multiplier `1/sqrt(w·floor(corr)·w)`, position inertia. Not runnable outside Quantopian.

Related outside the folder: `efficient_frontier_portfolio.py` (the working tool), `generate_efficient_frontier.py` and `efficient_frontier_data.ipynb` (earlier SLSQP sketches; the notebook's frontier loop re-solves the same unconstrained problem for each target and the notebook contains a hard-coded Tiingo API key), `portfolio_efficient_frontier_analyzer.py` (a Dash two-slider placeholder with dummy bar plots, the only slider code, unwired).

**Direct answer to the ME question:** No Python script optimizes along the risk axis with maximum entropy. The idea exists only as the 2017 plan stub and comments. The MATLAB side has Meucci's entropy pooling and minimum-torsion ENB code (see report 5).

## 4. Grep results (both trees; .venv/site-packages/node_modules/.git excluded)

1. `Finance/portfolio_risk_return_analysis_website.md`: the user's own question and the copula/Monte Carlo goals.
2. `Finance/Portfolios/EF_with_ME_Slider.txt:6`: "Step 3 - Use Maximization of Entropy method."
3. `Finance/Portfolios/asset_class_allocation.py:167` and `_v3.py:134`: the entropy TODO comments (OneDrive duplicates exist).
4. `Finance/Risk_Questionnaire_Analysis_v3/risk_tolerance_questionnaire.py:10,73,82,241,944-1093`: Student-t (df=5) fat-tail 95% CI alongside normal CI; `confidence_range_fat_tail`.
5. `.../risk_tolerance_analysis.md:12,19,324-340,372,390`: rationale and fat-tail table. `branching_logic_specification.md:11,399,561,594`: spec for the Student-t adjustment ("~1.3x wider").
6. `OneDrive/.../quantopian_research/advanced_sample_analyses/TSMOM/TS MOM.ipynb:66`: vol-scaled allocation "similar to risk budgeting or risk parity."
7. `Programming/Python/ChatGPT/Summary of uses since Dec 2022.txt:24,123`: note that a Laplacian-distribution Monte Carlo for trading-strategy testing was written with ChatGPT (file not located).
8. `OneDrive/.../quantopian_research/research/Markowitz-blog.ipynb`: cvxopt Markowitz tutorial referencing Kelly.
9. **Kelly (found late):** `OneDrive/.../quantopian_research/drafts/kelly/kelly_mv.ipynb` ("Risk Management and The Kelly Criterion", Wulfsohn, Granizo-Mackenzie, Wiecki): Kelly optimal leverage f* = mean excess return / σ² on SPY 2002-2015, then a cvxopt mean-variance frontier sweep connecting the Kelly point to the frontier. `kelly_kalman_pairs.py:66-96`: a `KellyLeverage` class, `kelly_score = mean(log returns) / var(log returns)` applied per Kalman-filter pair. Both are the continuous-Gaussian Kelly approximation, not fat-tailed or fractional Kelly.

No hits anywhere for copula code, HRP, CVaR optimization (only measurement), or Black-Litterman in Python.
