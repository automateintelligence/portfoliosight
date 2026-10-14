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
  riskBad: "Bad year",
  riskTypical: "Typical year",
  riskDisabled: "this menu has only one sensible risk level",
  resultStrip: "Selected mix",
  resultStripSuffix: "over one year",
  rangeLow: "Bad",
  rangeTypical: "Typical",
  rangeHigh: "Good",
  diversification: "Diversification",
  words: ["Good", "Average", "Fair", "Poor"] as const,
  divMoreReturn: "More return",
  divMoreDiversified: "More diversified",
  divDisabled: "At this risk, the best-return mix is already the most diversified one found.",
  optimized: "Optimized",
  resetOptimized: "Back to Optimized",
  frontier: "Best return at each level of risk",
  ghosts: "Same menu, different years of history",
  noLimits: "No limits",
  noLimitsLine: "Same funds, no limit on any one fund",
  resetLimits: "Reset limits",
  currentMix: "The mix you entered",
  selectedMix: "Selected mix",
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
  fundsNone: "No amounts entered: tickers only.",
  fundsClear: "Clear all",
  fundsClearHint: "Clear every amount; the funds stay in the list",
  fundsScale: "Scale to 100%",
  fundsScaleHint: "Scale the amounts in proportion so they add up to exactly 100%",
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
  heatLegend: "ENB (minimum torsion) of the most diversified mix found at each risk that earns at least each return",
  riskSlider:
    "2.5th percentile and median of the frontier mix's one-year return over 2,000 one-year paths resampled in blocks from this window's own daily history (stationary block bootstrap, mean block 21 days)",
  resultStrip:
    "Estimated central 95% range of the one-year return: its 2.5th, 50th and 97.5th percentiles over 2,000 one-year paths resampled in blocks from this window's own daily history, at constant weights, compounded (stationary block bootstrap, mean block 21 days)",
  /** The normal figure, shown in the details only. */
  bellCurve: (low: string, mid: string, high: string) => `Textbook bell-curve figure (normal, μ ± 1.96σ): ${low} to ${high} around ${mid}`,
  enbName: "effective number of bets, minimum torsion",
  divSlider:
    "Walks the mixes that keep the risk at X: every step down gives up return for diversification; the bottom end is the most diversified mix found at that risk",
  // The "Optimized" rule, kept in these strings only (the tensor says which one applies).
  optimized: {
    balanced:
      "Optimized is the balanced point: going from the best-return mix toward the most diversified mix at this risk, it is where each further step starts buying less diversification than the return it gives up.",
    peak: "Optimized is the most diversified mix found at this risk.",
  },
  optimizedMethod: {
    balanced:
      "the knee of diversification (ENB) gained against return given up along the mixes at this risk, both scaled to run from 0 to 1 (the level farthest above the straight line from the best-return mix to the most diversified one)",
    peak: "the highest ENB found among mixes with exactly this risk",
  },
  noLimits: "The same frontier with every fund allowed from 0% to 100%",
  rangePending: "The one-year range of this mix comes from the service and is not available right now.",
  frontier:
    "Long-only mean-variance efficient frontier with caps; drawn as the locus of interpolated frontier mixes' actual risk and return",
  ghosts: "Frontier estimated over the 1y/2y/3y/10y/EW window",
  caps: "Editable default: max = max(0.25, 3/N)",
  cutPoints:
    "The word tells you how evenly this mix's risk is shared out. We look at how many truly different kinds of investment are carrying the risk, and compare that with the most spread-out mix these funds can make. Good: at least three-quarters as spread out as that best mix. Average: at least half. Fair: at least 30%. Poor: less than that, so one or two holdings carry most of the risk.",
  cellPlace: (ceiling: string, floor: string) => `At risk ${ceiling}, earning at least ${floor}`,
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
  // not a history window: the same menu with every fund allowed 0% to 100% (owner's wording)
  nolimits: "No limits",
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
/** The running total of percentages while it is not exactly 100%: "Total: 92%, 8% to go". */
export const fundsTotal = (total: string, gap: string, over: boolean) => `Total: ${total}%, ${gap}% ${over ? "over" : "to go"}`;
export const staleLine = (asof: string) => `Prices through ${asof}; the nightly refresh has not run since then.`;
// Behind the details toggle only (it names the technical measure).
export const enbLine = (n: string, m: string) =>
  `spreads risk over the equivalent of ${n} independent bets; highest found on this menu: ${m}`;
