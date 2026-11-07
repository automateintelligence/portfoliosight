# ADR 0006 — A fund's simulated GARCH volatility is capped at 3 times its lookback volatility

Status: **Accepted for the fixed-risk experiment.** Date: 2026-11-07. Owner: Jeff Daniels.
Decided 2026-11-07 by Marshal on Jeff's delegation (option b of Q0, after a Codex second opinion);
Jeff may revisit. Terms are defined in `GLOSSARY.md`. Builds on ADR 0005.

## Context

On the research menu, the GARCH engine's simulated one-year mean returns at the 2010-08 and
2011-01 origins were in the hundreds of times the stake: the U1 mix's means were 128 and 208 (that
is, +12,800% and +20,800%), and the equal-weight mix's mean at 2010-08 was 314. The medians and
percentiles looked normal. A handful of the 2,000 paths carried the whole mean.

The cause is the variance recursion, not the shocks. Several funds' GARCH(1,1)-t fits are close to
integrated in those years: Citigroup's 3-year fit has alpha about 0.20 and beta about 0.80, IYR's
10-year fit has persistence 0.999, and SPY's 0.997 to 0.999. With persistence that close to 1, a
run of large shocks can push the simulated variance up with almost nothing pulling it back. On a
few paths it climbed without bound and gave daily log returns of +7 to +11. The levelling step
(`engine/ranges.py`, `_levelled`: `R' = expm1(c + a l)`) then turned those into simple daily gains
of about 80 times. The shocks are bounded: each is a real day from the shock pool. Dropping C from
the equal-weight mix at 2010-08 brought its mean from 314 to +1.8%.

## Decision

- **Rule.** Each fund's simulated conditional variance is held at or below `k^2` times that
  fund's realized daily variance over the lookback. Simulated daily volatility is therefore at
  most `k` times the lookback's.
- **Where.** Inside the variance recursion: `sigma2_t <- min(sigma2_t, cap)` before day t's shock,
  day 1 included, so a capped variance is also what feeds the next day. Returns are not clipped
  afterwards.
- **Anchor.** The lookback (3 years; 5 years in that sensitivity), the window the bank already
  uses for the level. The variance is that of the fund's daily log returns, matching the space the
  recursion runs in. It is not the fit's long-run variance `omega / (1 - alpha - beta)`: with
  persistence near 1 that figure divides by a number close to 0 and is unreliable. At 2016-06 IWD
  (persistence 0.9993) has a long-run volatility 5.5 times its lookback volatility.
- **k = 3.** A sensitivity check at k = 2, 3 and 5 (two seeds, 2,000 and 8,000 paths, origins
  2006-06, 2010-08, 2011-01 and 2016-06) gave means within 1.5 percentage points of each other
  across k for the same seed and path count, and calm origins' means were unchanged against the
  uncapped bank. Nothing argued for another value.
- **Scope.** Only the research GARCH bank (`research/fixedrisk/garch_bank.py`) is capped. The app's
  GARCH range model and the pinned QSE copy are unchanged: QSE's recursion takes no cap, so the
  bank runs its own copy of it, which matches `shape.simulate_panel` byte for byte when the cap
  is infinite. A constant-volatility fallback has no recursion and is never capped.
- **Record.** `k` is a run setting in the parent manifest (`garch_vol_cap`), so a run started
  without the cap cannot be resumed with it. Each task file records, per training bank and fund,
  the simulated path-days on which the cap bound, as a count and as a share.

## Considered options

- **Persistence cutoff (switch a fund with alpha + beta above 0.995 to constant volatility):**
  would put SPY, C and IYR on constant volatility in 2008 to 2011. That removes the volatility
  clustering a drawdown experiment needs, in exactly the years where it matters most.
- **Clipping extreme simulated days:** treats the symptom. The variance behind the day stays
  inflated and keeps producing large days after the clipped one.
- **Skipping GARCH at the affected origins:** drops the engine where the comparison with History
  replay is most informative.
- **Anchoring the cap on the long-run variance:** unreliable near persistence 1, as above.

## Consequences

- At 2010-08 the U1 mix's simulated mean goes from 128 to +5.0% and the equal-weight mix's from
  314 to +0.9%. At 2011-01 U1 goes from 208 to +8.4% and equal weight from 2.44 to +4.2%. At
  2006-06 and 2016-06 the means move by at most 0.02 percentage points and the 2.5th and 97.5th
  percentiles by at most 1.5 points.
- The cap binds on a small share of path-days: at k = 3, at most 1.4% for any fund at the
  troubled origins (C at 2011-01) and up to 2.4% at 2016-06 (IWD, whose long-run variance starts
  every path above the cap).
- The spread of the levelled years can widen. Levelling rescales each fund to the chart's
  volatility. Once the exploding paths are gone, the scale factor rises and the ordinary paths
  spread more: at 2011-01 the U1 mix's 97.5th percentile goes from +32% to +104%. That is the
  shape the fitted dynamics imply once the runaway paths are removed. Selections made on the
  uncapped bank (fr-run-v2b) do not carry over.
- Banks are rebuilt, not reused: the setting is part of the parent manifest's digest.
