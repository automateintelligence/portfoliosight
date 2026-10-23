# ADR 0002 — Progressive compute for custom menus; presets precomputed nightly

Status: **Draft, contingent** on the post-experiment product decision (conductor plan checkpoint
C8). Date: 2026-10-22. Owner: Jeff Daniels. Drafted by Claude at the owner's direction.

## Context

The owner's budget for a user-supplied menu is a usable chart within 30 seconds. A full max-U
surface (ADR 0001) is 48 columns × 19 interior slider positions = 912 searches per menu. v1's
research search cost 17 s a cell, of which ≈ 90% was harness bookkeeping (per-call recording,
caching, hashing); the bank itself scores a mix in ≈ 5 ms. Even at the projected half-second per
cell of the gradient optimizer (ADR 0004), the full surface is minutes, not seconds.

## Decision (contingent)

1. **Presets** (and later the most-requested custom menus) get the full surface in the nightly
   build.
2. **Custom menus** compute progressively, on the range API host (not the Cloudflare Worker):
   - immediately: frontier, the two anchors per column, chart outline. The frontier under a risk
     *ceiling* is convex and fast; the band's lower edge `σ(w) ≥ 0.99 r` makes the anchor
     programs nonconvex, and the most-diversified anchor maximizes `DR²` itself, a ratio of
     quadratics (protocol v2 §2, revision 3). So: the convex ceiling solve supplies a candidate,
     the candidate is checked against the lower edge, and a short multi-start SLSQP finishes the
     anchors where the check fails. The latency of this first step is measured in the experiment's
     cost table, not assumed to be about a second;
   - then: the risk column the user has fixed, all slider positions, warm-started from neighbours;
   - then: a coarse grid (every fourth column, three slider positions), then refinement;
   - results stream to the page as they finish; the page shows what is computed and marks the
     rest pending (the C3 resolution's "estimate visible, exact pending" pattern).
3. **Per-fund precompute, keyed by sample contract**: the bootstrap draws calendar days, so a
   path-by-day return tensor can be built nightly for a fund set (≈ 30 funds × 2,000 paths × 252
   days, single precision, ≈ 60 MB) and a menu drawn from it is a column selection with no bank to
   build. But a bank's sample is the set of **complete rows for that fund set and lookback**
   (`data/returns.py`, `window_sample`): a menu that adds a young fund or one with gaps has a
   different eligible calendar, and a universe-wide intersection would shorten every other menu's
   sample. So the shared tensor serves exactly the menus whose complete-row calendar equals the
   tensor's; bank reuse is keyed by (calendar, window, data identity), the raw returns and the
   day draws are shared across all menus, and centring stays per menu. Any other menu builds its
   own bank from the shared draws (milliseconds for the tensor; the cost is in the searches). GARCH
   fits are per fund, once, on the fund's own window, and are reusable across menus because the
   fit does not depend on the fund set.
4. **Popular menus**: submitted custom menus are stored as a hash of the ticker set with a count
   (no user data); the most-requested tickers are promoted into the nightly tensors. This is a new
   plan item attached to the range API phase when this ADR is accepted.

## Consequences

- The range API gains a job queue and a streaming or polling response for partial surfaces; the
  Worker only forwards.
- Sizing comes from the experiment's bare cost table (protocol v2 §5, §6), not from the research
  harness's wall time.
- Tickers outside the supported universe still need a price fetch (seconds each) before anything
  is computed.

## Open points

- The 30-second budget applies to first use (frontier, anchors, the fixed column), not to the full
  912-cell surface, which completes progressively; both latencies are reported separately in the
  experiment's cost table.
- Streaming (server-sent events) versus polling for partial results.
- The storage location and retention for submitted-menu hashes.
