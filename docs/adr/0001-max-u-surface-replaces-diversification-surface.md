# ADR 0001 — The max-U surface replaces the diversification (ENB ladder) surface

Status: **Draft, contingent** on the post-experiment product decision (conductor plan checkpoint
C8: measure, white line, delivery scope) reading the
[fixed-risk experiment](../plans/2026-10-21-fixed-risk-optimization-experiment-protocol.md) report.
Date: 2026-10-22. Owner: Jeff Daniels. Drafted by Claude at the owner's direction.

## Context

Today's surface (`engine/surface.py`, `engine/ladder.py`) is 48 risk columns, each a 12-level
ladder of the most-diversified-by-ENB mix earning at least a return floor, plus a 32-row
interpolation grid of ENB. The v1 experiment found no out-of-sample value in a diversification
preference inside a U allowance, and its slider endpoints (max-return vs MDP at the same risk) put
the more-diversified mix at a worse model Bad with no better realized downside. The owner's
position (2026-10-22): "No point in keeping what we know isn't serving us."

## Decision (contingent)

The product surface becomes the **max-U surface**: for each risk column `r` and slider position
`d`, the mix with the highest `U` among the mixes at risk `r` and diversification level `d`
(protocol v2 §2). What stays and what goes:

| Today | Under the max-U surface |
|---|---|
| Covariance, expected returns, the frontier over 48 columns | Stays; draws the chart |
| Per-column frontier mix and most-diversified mix | Stays; they are the slider's two ends |
| 12-level ENB ladder per column | Goes; replaced by the max-U cells |
| ENB interpolation grid and hop logic | Goes; the heatmap colour is U or Bad per cell |

A column is **open** when the diversification gap between its two ends exceeds a threshold set
from the experiment's collapsed-column share (protocol v2 §6); closed columns show the frontier mix
only. The ENLC diagnostic (spec §5.3) is unaffected.

## Consequences

- The heatmap's third axis changes meaning from ENB to U (or Bad); the diversification words of
  spec §6.1 attach to `d(w)` instead of ENB.
- Spec §5.5 D1/D2 (ceiling, allowance slider), the 14-level allowance ladder, hop and collapse
  mechanics, and the A-SE-18/A-SE-20 observations written against them are superseded when this
  ADR is accepted; the gate-change workflow applies.
- Build cost moves from the ENB ladder to the max-U searches; see ADR 0002 for how the budget is
  met.

## Open points

- The white line: the frontier mix or the free-cell max-U mix (spec §5.5 D3), decided from the
  experiment's primary result.
- Whether the heatmap colour is U or Bad.
