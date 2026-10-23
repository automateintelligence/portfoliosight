# ADR 0004 — The production optimizer is a smooth-percentile gradient solver

Status: **Draft, contingent** on the post-experiment product decision (conductor plan checkpoint
C8) and on the agreement check of protocol v2 §4. Date: 2026-10-22. Owner: Jeff Daniels. Drafted
by Claude at the owner's direction.

## Context

`U` is built from sample percentiles of 2,000 compounded years, a function that is flat between
paths. v1 therefore used COBYLA, a derivative-free method, at hundreds of calls per start: ≈ 17 s
per cell in the research harness, ≈ 4 s with the bookkeeping removed. The owner asked for the
production speed ideas to be applied to the experiment, in particular "make the objective smooth
and use gradients".

## Decision (contingent)

- The search objective replaces each sample percentile with a kernel-smoothed percentile
  (Gaussian kernel over rank fraction, bandwidth 0.01 ≈ 20 paths), which is differentiable; the
  gradient of a path's compounded year is closed form and costs about one evaluation.
- The solver is SLSQP with analytic gradients under the risk band, the measure band, bounds and
  the budget constraint; three starts per cell (ladder anchor, neighbouring cell's solution, best
  projected Sobol point).
- **Reported figures are always the exact sample percentiles of the final mix**; smoothing is a
  search device only.
- Acceptance: on 50 cells the gradient solver's exact `U` is within 2.5 bp of, or above, COBYLA's
  in ≥ 95% of cells (protocol v2 §4). If it fails, COBYLA stays and this ADR is withdrawn.
- The objective and gradient are written as plain array code so a GPU backend (`torch`) can be
  added without changing the contract; not built unless the measured CPU cost requires it.

## Consequences

- Per-cell cost drops from seconds to a projected fraction of a second, which is what makes ADR
  0002's progressive compute reach the 30-second budget.
- "Found" remains the honest label: the smoothed optimum is a local optimum of an approximation,
  verified by rescoring; it is not a certified global optimum.
- The 5-ms-per-evaluation bank scoring becomes the floor to optimize against; the bare cost table
  in the experiment report is the sizing input.

## Open points

- Bandwidth: 0.01 is a choice; the agreement check measures its effect at the 2.5% quantile, where
  the kernel averages the tail.
