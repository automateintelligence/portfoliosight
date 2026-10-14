// Every user-facing string of spec 3.6 and 3.7. `plain` is what the page shows by default;
// `technical` appears only behind the details toggle. Formatting helpers live in format.ts.

export const plain = {
  wordmark: "PortfolioSight",
  xAxis: "Risk: how much it bounces around in a year",
  yAxis: "Expected return per year",
  heatLegend: "How spread out the risk is",
  heatLess: "Less",
  heatMore: "More",
  riskSlider: "Best-return mix at this risk",
  riskBad: "Bad six months",
  riskTypical: "Typical six months",
  riskDisabled: "this menu has only one sensible risk level",
  resultStrip: "Selected mix",
  resultStripSuffix: "over six months",
  rangeLow: "Low",
  rangeTypical: "Typical",
  rangeHigh: "High",
  diversification: "Diversification",
  words: ["Good", "Average", "Fair", "Poor"] as const,
  divMoreReturn: "More return",
  divMoreDiversified: "More diversified",
  divDisabled: "At this risk, the best-return mix is already the most diversified one found.",
  suggested: "Suggested",
  resetSuggested: "Reset to suggested",
  frontier: "Best return at each level of risk",
  ghosts: "Same menu, different years of history",
  currentMix: "The mix you entered",
  selectedMix: "Selected mix",
  mostDiversified: "Most diversified at this risk",
  cellMix: "The mix at this spot",
  cardRisk: "Risk",
  cardReturn: "Expected return",
  cardPerYear: "Risk and expected return are per year.",
  cardHoldings: "Largest holdings",
  details: "Details",
  advice: "Historical math, not investment advice.",
  building: "Give us a moment: computing this menu (about 30 seconds)",
  buildFailed: "We couldn't compute this menu",
  buildFailedFinal: "We couldn't compute this menu after three tries. The ready-made portfolios still work:",
  retry: "Retry",
  shareCopy: "Copy link",
  shareEmail: "Send this view by email",
  shareSend: "Send",
  shareSent: "Sent",
  shareBadAddress: "That address doesn't look right",
  shareTooMany: "Too many shares for today",
  shareTooLong: "This view is too long to email; copy the link instead",
  shareFailed: "The message could not be sent. Copy the link instead.",
  sharePreview: "PortfolioSight is in private preview: the link opens for invited testers only until the site is public.",
  custom: "Custom…",
  symbolsHelp: "Only funds and stocks with verified current data are offered.",
  trades: "Moves to get from the mix you entered to the selected mix.",
  tradesExport: "Export CSV",
  fundsRecalculate: "Recalculate with these funds",
  fundsAsYouType: "Amounts apply as you type.",
  fundsChanged: "The fund list has changed: recalculate to see it on the chart.",
  fundsOpen: "Show funds & amounts",
  fundsClose: "Hide funds & amounts",
  colEntered: "Mix entered %",
  colSelected: "Selected mix %",
  stressSentinel: "Not enough of this mix existed then to say.",
  notEnoughHistory: "not enough shared history",
  allSetAside: "The mix you entered uses only funds set aside in this view",
  lowRisk: "there is little risk here, but it may all be in one place",
  chips: { funds: "Funds & amounts", trades: "Trades", stress: "Stress tests", settings: "Settings" },
} as const;

export const technical = {
  xAxis: "Standard deviation of yearly return",
  yAxis: "Shrunk expected return (50/50 sample mean and menu-beta heuristic), annualized",
  heatLegend: "ENB (minimum torsion) of the computed mix at each risk ceiling / return floor",
  riskSlider: "2.5th percentile and mean of the frontier mix's six-month return, normal approximation",
  resultStrip: "Estimated central 95% range, normal, additive: μ/2 ± 1.96·σ/√2",
  enbName: "effective number of bets, minimum torsion",
  divSlider: "Return floor along the column at risk ceiling X; bottom end = the column's highest-ENB computed mix",
  // The "Suggested" rule, kept in these two strings only (the rule may change).
  suggested:
    "Suggested is the most diversified mix at this risk that still earns about as much as the best-return mix: what it gives up in return is too small to tell apart from the ordinary day-to-day noise in the two mixes' returns.",
  suggestedMethod:
    "Lowest return floor whose give-up versus the frontier mix is within one standard error of the paired daily return difference (a heuristic, not a significance test)",
  frontier:
    "Long-only mean-variance efficient frontier with caps; drawn as the locus of interpolated frontier mixes' actual risk and return",
  ghosts: "Frontier estimated over the 1y/2y/3y/10y/EW window",
  caps: "Editable default: max = max(0.25, 3/N)",
  cutPoints:
    "The word tells you how evenly this mix's risk is shared out. We look at how many truly different kinds of investment are carrying the risk, and compare that with the most spread-out mix these funds can make. Good: at least three-quarters as spread out as that best mix. Average: at least half. Fair: at least 30%. Poor: less than that, so one or two holdings carry most of the risk.",
  cellPlace: (ceiling: string, floor: string) => `Computed for risk ceiling ${ceiling} and return floor ${floor}`,
} as const;

export const disclaimer =
  "PortfolioSight is an educational tool. All figures are mathematical results computed from historical prices and are hypothetical; past performance does not predict future results. Nothing here is investment, tax or legal advice, and no output is a recommendation to buy or sell anything. PortfolioSight is not registered with the SEC, FINRA or any other regulator. You remain solely responsible for your decisions. Price data: Tiingo and tsp.gov.";

export const family = {
  lead: "More from the AutomateIntelligence family",
  links: [
    { name: "Option Spread Scanner", href: "https://option-spread-scanner.ingage-bd0.workers.dev" },
    { name: "KnowledgeSight", href: "https://automateintelligence.ai" },
    { name: "SecuritySight", href: "https://securitysight.ai" },
  ],
} as const;

export const lookbackNames: Record<string, string> = {
  "1y": "1 year",
  "2y": "2 years",
  "3y": "3 years",
  "5y": "5 years",
  "10y": "10 years",
  ew: "Weighted toward recent",
};

/** Names of the history windows as they label the frontier lines on the chart. */
export const lookbackLine: Record<string, string> = {
  "1y": "1 year",
  "2y": "2 years",
  "3y": "3 years",
  "5y": "5 years",
  "10y": "10 years",
  ew: "Weighted recent",
};

export const lookbackShort: Record<string, string> = {
  "1y": "1y",
  "2y": "2y",
  "3y": "3y",
  "5y": "5y",
  "10y": "10y",
  ew: "Recent-weighted",
};

/** Words that must never appear in the default (details off) copy. */
export const forbiddenDefault = [
  "bets", "knee", "Sharpe", "tangency", "covariance", "sigma", "quantile", "significant",
  "you should", "we recommend", "Risk Number", "Risk Score",
] as const;

// ── Sentence builders (all default copy) ─────────────────────────────────────
export const capsRule = (maxPct: string, n: number) => `No single fund above ${maxPct}% (menu of ${n})`;
export const excludedFund = (fund: string, date: string, window: string) =>
  `${fund}: history starts ${date}, not enough for the ${window} view`;
export const stressLine = (pct: string) => `What this mix did: ${pct} (${plain.selectedMix})`;
export const stressGap = (n: number, m: number, pct: string) =>
  `${n} of ${m} funds (${pct}% of the mix) didn't exist yet; result is for the rest.`;
export const staleLine = (asof: string) => `Prices through ${asof}; the nightly refresh has not run since then.`;
// Behind the details toggle only (it names the technical measure).
export const enbLine = (n: string, m: string) =>
  `spreads risk over the equivalent of ${n} independent bets; highest found on this menu: ${m}`;
