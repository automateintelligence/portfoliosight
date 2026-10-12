# Research report 3: Competitive landscape for a free efficient-frontier / risk-score tool as a funnel

Date: 2026-10-12. Produced by a web-research agent.

## 1. Existing tools: free vs paid

| Tool | What it does | Free tier | Paid price | Source |
|---|---|---|---|---|
| Portfolio Visualizer | Backtest, Monte Carlo, efficient frontier, optimization, factor regression. The incumbent. | Up to 15 assets, limited history, no login. | Basic $30/mo, Pro $55/mo billed annually; paywall introduced May 2024. | portfoliovisualizer.com/pricing; MFO forum May 2024 |
| testfol.io | Free PV alternative that absorbed the post-2024 defection. | Anonymous free. | From ~$15/mo. | findmymoat |
| Nitrogen (Riskalyze) | Advisor-only B2B. Risk Number 1-99, 95% Historical Range, GPA, stress tests. | None for retail. | Per-advisor SaaS, not published. | nitrogenwealth.com |
| Morningstar Investor / X-Ray | Asset-class, sector, style-box, overlap. No frontier. | Free Instant X-Ray being retired. | $34.95/mo or $249/yr. | morningstar.com |
| Kwanti | Advisor-only analytics, model comparison, proposals. | 14-day trial. | $224/user/mo annual. | kwanti.com/pricing |
| Empower (Personal Capital) | Links accounts; allocation vs target on a six-asset-class frontier; fee analyzer. | Entirely free (lead-gen for $100k+ advisory). | Advisory fee on AUM. | financialsamurai.com |
| Schwab / Vanguard / Fidelity | Portfolio Checkup / Portfolio Watch / Planning & Guidance. Asset-class level only. | Free for account holders. | n/a | provider sites |
| Snowball Analytics | Dividend tracker; rebalancing tool on paid tiers. | 1 portfolio, 10 holdings. | $79.99 to $249.99/yr. | snowball-analytics.com/pricing |
| PortfoliosLab | Free-first optimizer (max Sharpe, min vol, risk parity), frontier, correlation. Closest free competitor. | Most tools free with ads/limits. | Premium from ~$8.33/mo. | findmymoat |
| Koyfin | Research terminal; risk on Premium. | 1 portfolio. | $39 to $299/mo. | koyfin.com |
| Stock Rover | Screener + portfolio analytics. | Limited free. | $7.99 to $27.99/mo. | stockrover.com |
| Tickeron | AI trading signals; not portfolio construction. | Limited. | ~$60-250/mo. | softwarefinder |
| Composer | No-code strategy automation + brokerage. | Starter $0. | $10 to $32/mo. | composer.trade/pricing |
| PortfolioPilot | AI advisor: links accounts, scores, Monte Carlo. | Free tier. | $20 to $99/mo. | portfoliopilot.com |
| Sharesight | Performance/tax tracker. | 1 portfolio, 10 holdings. | $7 to $23.25/mo. | sharesight.com |
| 2024-26 AI entrants | Insightfol, Guardfolio, PieFolio, Betterment AI insights, Vanguard Expert Insights (advisor-only). None publishes a frontier + risk-score combo. | varies | varies | G2; Vanguard PR Apr 2026 |

## 2. Gaps a free tool could fill

Nobody on the retail side pairs (a) an arbitrary-ticker efficient frontier with (b) a behaviorally derived risk score and (c) a translation from that score into a concrete allocation.

- **Risk-score-to-allocation mapping for retail.** Nitrogen does it only through an advisor; Empower only at six asset classes with account linking.
- **401(k) fund-menu optimization.** Blooom was the only consumer product doing this; it shut its D2C service in Nov 2022 and sold the tech to Morgan Stanley (RIABiz Dec 2022; PlanAdviser). "Paste your plan's fund list, get the best mix for your risk level" is open and highly searchable: the search phrases "401k fund optimizer", "best allocation for my 401k funds", and plan-provider names have real volume and, since Blooom's exit, no dedicated free tool ranks for them.
- **Fat-tail / non-normal six-month ranges.** Nitrogen concedes "5% we can never quantify" and validated on 2014-2016 only, a low-vol period. A Student-t or bootstrapped range with an explicit tail panel is a differentiator.
- **Diversification score with "halfway" rebalancing and turnover cost.** Absent everywhere.
- **Real-time slider.** PV and PortfoliosLab are form-submit. Nobody offers drag-the-risk, watch-the-allocation-update.
- **Holdings-level scoring.** Only Nitrogen and Kwanti (both B2B) score at the security level.

## 3. Funnel examples and what the free tool needs

- **Portfolio Visualizer**: ~615k visits/mo (Semrush, Mar 2025, 11.5-min avg session) built on a free tool before paywalling in May 2024. The paywall triggered a visible exodus, which argues for keeping the core free and monetizing adjacent.
- **NerdWallet**: calculator pages are the SEO front door; the compound-interest calculator alone drew ~289k organic visits/mo (Ahrefs). Its 2025 10-K attributes a 24% credit-card revenue drop to organic-search pressure.
- **Option Alpha**: free 30-day trial, permanently free with a funded Tradier ($5k) or TradeStation ($10k) account; Pro $99/mo annual. Broker revenue share subsidizes "free."
- **Market Chameleon**: free Starter, $39-99/mo tiers. **Unusual Whales**: delayed flow free, ~$48-50/mo paid; free tools + free course as top of funnel.
- **Empower**: the free Investment Checkup frontier is the lead magnet for a $100k+ advisory call; the most direct precedent.

What the free tool must include to rank and get shared: no login for the first result; a URL that encodes the portfolio so results are linkable; programmatic landing pages ("VTI VXUS BND efficient frontier", "Fidelity 401k fund optimizer"); exportable image/PDF; a single memorable number that people post on Reddit/Bogleheads; a cap generous enough not to annoy (PV's 15-asset cap is tolerable; 10-holding caps get complained about).

## 4. Nitrogen / Riskalyze specifics

- **Definition.** Risk Number is a 1-99 score of "what percentage of potential downside risk a client is comfortable with" over six months. Published mapping: 0% → 1, −9.5% → 50, −55% or worse → 99.
- **Questionnaire.** A series of 50-50 gambles anchored to the investor's actual portfolio size, a self-specified "disastrous" loss and a "content" gain; explicitly based on Kahneman-Tversky prospect theory (ThinkAdvisor, Jul 2015). Structurally the same as the user's bracketing questionnaire.
- **95% Historical Range.** Computed per holding from price history including dividends and expense ratios, rolled up to the portfolio; explicitly historical, not a forecast. Self-reported validation: 0.63% of 100k+ portfolios breached the lower bound, sample 2014-Nov 2016. Exact distribution and lookback are not disclosed.
- **Alignment rule.** Client and portfolio numbers "acceptable" when within 5-10 points.
- **GPA.** Separate 1.0-4.3 risk-adjusted efficiency metric; >3.5 = "efficient."
- **IP.** Nitrogen markets the Risk Number as "patented," but no patent number was located; Justia shows trademarks RISK FINGERPRINT and RISK SCORE. Check USPTO assignee "Riskalyze, Inc." before cloning the gamble presentation; the prospect-theory elicitation is academic prior art.
- **Criticisms.** (a) Conflates tolerance with capacity; Kitces argues the two must be assessed separately. (b) Historical range understates tails; validated only in a calm period. (c) Competitors (HiddenLevers, RiXtrema) attacked the single-number approach. (d) Answers drift with mood and market regime. Reporting tolerance and capacity as two numbers, showing the tail panel, and stating the lookback explicitly answers every published critique.

## 5. Honest pushback and bridges

**Why it may not convert.** The audience that searches "efficient frontier calculator" or "401k fund optimizer" is Bogleheads-adjacent: low-turnover, fee-averse, often hostile to options. Options-scanner buyers search for "options flow," "IV rank," "credit spread screener." Near-zero keyword overlap. PV's history is a warning: a huge free audience did not translate into willingness to pay even for the same product. Expect conversion well below generic SaaS freemium (2-5%), likely under 1%, unless the paid product is reframed.

**Bridges.**
1. **"Protect this portfolio" hedge calculator.** Cost of a 6-month protective put or zero-cost collar on the user's actual top holdings, shown as a floor on the left tail of the 95% range. Existing standalones are thin (Apex Volatility collar calculator, Barchart per-option pages, iVolatility paid worksheets); none takes a whole portfolio as input.
2. **Covered-call overlay as "yield on your risk level."** Income from monthly covered calls on the user's holdings and how it lowers six-month downside; the scanner becomes "find the best strikes for the overlay you just saw."
3. **Risk-level-gated spread suggestions.** Map risk bands to defined-risk strategies (low: collars/put spreads; mid: covered calls; high: credit spreads).
4. **Segment the funnel.** Capture email at "save/share your frontier," route by risk level and by hedge-calculator use; market the scanner only to the hedge/overlay cohort; sell the rest a $5-10/mo "pro" tier or an affiliate broker link.
5. **Programmatic SEO on the 401(k) menu.** Pages per plan provider ("Fidelity BrokerageLink optimizer," "TSP fund allocation by risk level") are low-competition since Blooom's exit.

Net: build the free tool for its own SEO value and list growth, but put the hedge/overlay calculator, not the frontier, on the path to the scanner.
