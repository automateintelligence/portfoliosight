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
   - immediately: frontier, the two anchors per column, chart outline (small convex problems,
     about a second);
   - then: the risk column the user has fixed, all slider positions, warm-started from neighbours;
   - then: a coarse grid (every fourth column, three slider positions), then refinement;
   - results stream to the page as they finish; the page shows what is computed and marks the
     rest pending (the C3 resolution's "estimate visible, exact pending" pattern).
3. **Per-fund precompute**: the bootstrap draws the same calendar days for every fund, so the
   path-by-day return tensor is built nightly for the whole supported universe (≈ 30 funds × 2,000
   paths × 252 days, single precision, ≈ 60 MB); a custom menu drawn from the universe is a column
   selection with no bank to build. GARCH fits are likewise per fund, once.
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

- Streaming (server-sent events) versus polling for partial results.
- The storage location and retention for submitted-menu hashes.
