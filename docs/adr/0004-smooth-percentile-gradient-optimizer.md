# ADR 0004 — The production optimizer is a smooth-percentile gradient solver

Status: **Draft, contingent** on the post-experiment product decision (conductor plan checkpoint
C8) and on the agreement check of protocol v2 §4. Date: 2026-10-22. Owner: Jeff Daniels. Drafted
by Claude at the owner's direction.

## Context

`U` is built from sample percentiles of 2,000 compounded years. Each year is a smooth function of
the weights, so a sample percentile is **piecewise smooth**: between rank crossings its gradient is
the gradient of the path holding that rank, with kinks where two paths swap ranks. (An earlier
draft called it "flat between paths"; that was wrong.) v1 used COBYLA, a derivative-free method, at
hundreds of calls per start: ≈ 17 s per cell in the research harness, of which one recorded cell
shows ≈ 6 s of bank scoring. The owner asked for the production speed ideas to be applied to the
experiment, in particular "make the objective smooth and use gradients".

## Decision (contingent)

- The search uses analytic gradients of the percentile objective. Two variants are benchmarked in
  the experiment: the exact order-statistic gradient (cheapest; kinked) and a kernel-smoothed
  percentile (Gaussian kernel over rank fraction, bandwidth 0.01 ≈ 20 paths), whose gradient
  averages the kinks over ≈ 20 paths without removing them. Whichever passes the agreement check
  at lower cost becomes the production objective.
- The path gradient is **engine-specific** (protocol v2 §4, revision 3): replay differentiates
  through its count matrix, `∇ Σ_p a_p R_p = A'[C'(a ⊙ (1 + R)) / g]`, with no path × day × fund
  tensor; the GARCH engine's mix return carries the weight-dependent scale `k(w)` and its gradient
  includes the `(x'w) ∇k` term; absorbed paths have year −1 and zero gradient. Gradients are
  accepted only after directional finite-difference checks.
- The solver is SLSQP with analytic gradients under the risk band, the measure band, bounds and
  the budget constraint; three deduplicated starts per cell (anchor interpolation projected onto
  the band, neighbouring cell's solution, best projected Sobol point).
- **Reported figures are always the exact sample percentiles of the final mix**; the search
  objective is a search device only.
- Acceptance: on 60 cells across both engines, both the `U` and max-`Bad` objectives and narrow
  cells, the gradient solver's exact objective is within 2.5 bp of, or above, COBYLA's at 768
  calls in ≥ 95% of cell-objective pairs (protocol v2 §4). If it fails, COBYLA stays and this ADR
  is withdrawn.
- The objective and gradient are written as plain array code so a GPU backend (`torch`) can be
  added without changing the contract; not built unless the measured CPU cost requires it.

## Consequences

- Per-cell cost is projected to drop from seconds to a fraction of a second, which is what would
  let ADR 0002's progressive compute reach the 30-second first-use budget; the projection is
  measured in the experiment before it is relied on.
- "Found" remains the honest label: the smoothed optimum is a local optimum of an approximation,
  verified by rescoring; it is not a certified global optimum.
- The 5-ms-per-evaluation bank scoring becomes the floor to optimize against; the bare cost table
  in the experiment report is the sizing input.

## Open points

- Bandwidth: 0.01 is a choice; the agreement check measures its effect at the 2.5% quantile, where
  the kernel averages the tail.
