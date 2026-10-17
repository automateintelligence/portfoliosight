# Conductor setup: independent review evidence

Date: 2026-10-17 (America/Los_Angeles).

## Assertion specifications

Claude review — UNAVAILABLE (weekly quota); independent same-host Codex fallback.
Reviewer: fresh `gpt-6-astra` session, high effort; not the assertion author.
Scope: the simulation-engine assertion prose against its normative spec and existing
Phase 1 implementation plan. No product code approval, test execution or resolution
of the explicitly deferred owner decisions is implied.

Round 1 requested one P1 and two P2 changes:

- Preserve offline provenance checking: attest trusted upstream hashes once, pin them
  independently in the frozen test and exercise sync against a synthetic git repository.
  Ordinary guards must not require the private upstream checkout or online dependency installs.
- Extend Phase 1 observations to cover generation-scoped immutable artifacts, fit reuse,
  restart reproduction, two-panel LRU/eight-sample bounds and pinned/unpinned pruning.
- Independently check DR²/ENB normalized words at and around all three cut points.

All three findings were checked against the spec and applied. Round 2 was required
because Round 1 had P1. Its verdict: approve the revised assertion prose, with no
remaining P0/P1 and no new P2 findings. It retained the source's explicitly unresolved
product/scientific interpretations. This fallback gives up opposite-host independence;
optional Claude re-review remains debt after quota recovery.

Reviewed file: `docs/specs/2026-10-14-portfoliosight-simulation-engines-design.assertions.md`.
Reviewed SHA-256: `e067049d3fbc3abb6fab6671033cf66ca06542051763ce6372fa3eefd11fbe79`.

## Subsequent planning corrections

The plan author identified a cross-phase dependency after the bounded assertion
review: A-SE-16's Phase 1 budget observation also required its successor Phase 2.
The Phase 2 repeat workload and 100-fund measurement were moved to A-SE-22;
A-SE-16 stays owned by the Phase 1 validation phase. A-SE-11's null loss-sources
observation was qualified to Phase 1 tensors lacking attribution capability so it
does not reject the successor capability validated by A-SE-19. These changes keep
the original source IDs and product requirements; the source hash above records
the exact earlier bounded review rather than claiming these later edits were in it.
The independent plan review and runnable-gate checks assess the resulting mapping.

## Conductor execution plan

Claude review — UNAVAILABLE (weekly quota); independent same-host Codex fallback.
Reviewer: fresh `gpt-6-astra` session, high effort; not the plan author.
Verdict on the final saved plan: pass for substance, no outstanding P0/P1/P2 findings.
No product tests were run; this is plan review, not implementation approval.

The reviewer found one P2 omission: the extra ENB peak random starts required for
100-fund menus. Task 7.7 now covers bounded deterministic extra starts without
changing small-menu baselines; task 9.5 measures both large-menu solvers. The
reviewer verified the final saved update, scope coverage, preserved branches,
acyclic assertion ownership, source math, explicit unresolved-decision checkpoints,
full Conductor recipe, quota fallback, target-host evidence, one full-suite merge
verification and the parked Copula/driver boundary.

Reviewed plan: `docs/plans/2026-10-17-simulation-engines-conductor-plan.md`.
Reviewed SHA-256: `2d5c244b0098659a6c62471220f92727d5c26c364df00de03047e0582e4a2641`.
Opposite-host independence remains review debt; it was not silently substituted.
