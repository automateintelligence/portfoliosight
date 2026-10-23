# ADR 0003 — Risk is a fixed band, and the slider's axis is diversification level

Status: **Draft, contingent** on the post-experiment product decision (conductor plan checkpoint
C8). Date: 2026-10-22. Owner: Jeff Daniels. Drafted by Claude at the owner's direction.

## Context

Spec §5.5 D1 made the risk slider a ceiling (`σ(w) ≤ X`, "never an equality") and D2 made the
diversification slider an allowed sacrifice of `U`. v1 showed the ceiling never binds for a max-U
objective: the optimizer sat at 3–5% risk under ceilings of 7–19%, so the risk axis did nothing
for the optimized mix. The owner's intent (2026-10-21): the user fixes a risk; every slider
position at that risk is its own optimization.

## Decision (contingent)

- **Risk is a band**: the admissible mixes at slider position `r` have `|σ(w) − r| ≤ 1%·r`.
- **The slider's axis is diversification level `d ∈ [0, 1]`**, measured by the squared
  diversification ratio: 0 at the frontier mix's measure, 1 at the most-diversified mix's measure
  at that risk. Each position selects the max-U mix among the mixes at that risk and that level
  (protocol v2 §2).
- The slider's ends are the frontier mix and the most-diversified mix at that risk; the
  most-diversified mix is computed only to set the slider's length.
- The label "every step down gives up return for diversification" is used only if the experiment
  confirms U falls with `d` past its peak; otherwise the label states the measured shape.

## Consequences

- Supersedes spec §5.5 D1 and D2 and §3 item 7's "ceiling, never an equality"; the allowance cap,
  guards, dominance filter and Stage B are retired from the product rule.
- The selected mix is drawn on the risk line (`σ(w) = r` within the band) rather than inside the
  ceiling; the chart's "inside the ceiling" drawing rule goes.
- Low-risk columns where the two ends coincide are closed (ADR 0001).

## Open points

- The default slider landing: `d = 0`, or the `d*` where U peaks on that line (from the
  experiment's `d*` distribution).
