// What a ticker may look like on its way to `/api/ticker-requests`, shared by the page (which
// sends only such tickers) and the Worker (which keeps only such tickers). No imports: it loads
// in the page and in the Worker alike.

export const TICKER_SHAPE = /^[A-Z0-9.-]{1,10}$/;
export const MAX_TICKERS_PER_REQUEST = 100;
/** Where the ticker came from: a CSV upload, or a ticker typed into the fund picker. */
export type TickerSource = "csv" | "picker";
export const TICKER_SOURCES: readonly TickerSource[] = ["csv", "picker"];
