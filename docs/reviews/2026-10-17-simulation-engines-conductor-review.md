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

## Runnable gate verification in progress

The first nine standalone tests collected and returned expected missing-interface
failures from the integration tree, with no collection errors. A separate positive
probe extracted the preserved `feature/engine-garch` checkpoint `0c82e57` into a
throwaway directory and copied only A-SE-04/06/08/09 into it. With that branch's
existing declared-dependency environment (including `arch==8.0.0`), all four passed
in 113.40 seconds. No feature branch, worktree or dependency environment was changed.
The earlier probe with the main environment passed A-SE-08 but stopped the other
three at missing `arch`; both logs are retained under the per-run local state.
The exact initial and corrected contexts remain distinguishable.

An independent reviewer identified API precision and URL-harness defects. Their
fixes preserve float64 build checks, use an independent float32 API oracle, correct
`u`/`lb` URL keys, and require both presets and nonempty observation sets. The three
changed tests still return expected missing-interface failures in the integration
tree. A separate real-App URL probe passed both menus across 1y/5y/ew, six cases.
These checks establish test behavior and preserved-engine evidence; they do not
attest the complete simulation feature or target-host performance.

## Future Copula gate checkpoint

A-SE-01 intentionally trusts the selected ten-file Phase 1 pin. Copula is parked
and cannot pass the initial full gate unchanged: a future owner-authorized upstream
pin change requires a new independently reviewed byte/hash attestation, review of
the actual upstream Copula API, a gate-change note and an explicitly approved
re-freeze. Provisional future API names are not claims about the current upstream
library. Do not broaden provenance checks to accept a self-reported unknown lock
or let an automatic worker weaken the frozen trust root. The current Phases 1/2
and later full-spec completion remain separate claims.

## Runnable gate review rounds

Claude review — UNAVAILABLE (weekly quota); two fresh independent Codex review
lanes used `gpt-6-astra`, high effort. Reviewers did not author the gate files.

Round 1 held freeze for concrete defects: API precision, URL parameters, vacuous
coverage, self-reported optimizer/seed evidence, historical eligibility, report
metrics detached from Markdown, mirror-write boundaries, benchmark source binding
and warm artifacts contaminating cold-nightly measurements. The authors corrected
those before the final snapshot review.

Round 2: code/spec lane APPROVE, no P0/P1; architecture lane WATCH, no P0/P1.
Both retained one P2: measures observations needed the independently derived exact
quarter-end trading-day set, rather than count/endpoints. That correction was
applied and checked by AST, Ruff and the focused expected-red test; no extra review
round was requested for this P2-only correction. The remaining WATCH is the future
Copula upstream/API/trust refresh described above. These are gate-authoring
verdicts, not product merge approval or proof that pending observations pass.

The existing repository lint/format checks passed (138 files formatted), and the
existing typecheck returned zero errors and warnings. The repository deliberately
excludes assertion files from those tools; separate gate lint, explicit fatal
Ruff/AST checks and standalone execution validate the new gate files.

## Final gate and ledger checkpoint

The assembled frozen run completed with **0/28 green, 28 red**; every standalone
pytest command returned exit 1. There were no collection errors or outer timeouts.
Aggregate assertion wall time was 371.77 seconds. Missing integration/features,
validation evidence, explicit target-host configuration and parked Copula trust
prerequisites remain visible red observations; no product phase is complete.

The initial assembled run exposed A-SE-02 importing `tomllib` under the outer system
Python 3.10 before its project-interpreter bridge. The import was moved into the
isolated Python 3.12 probe, and the exact pinned command then collected correctly
and failed on the actual missing builder interface. Its mutable fixture helper was
also replaced by the already-reviewed frozen canonical-store construction; a
standalone smoke generated 29 records with nonconstant VTI returns. The final
frozen full run verifies all commands after that correction.

Gate lint passes without bypassing any rule. Explicit fatal Ruff checks and format
checks pass on all 28 files. Eight initial formatting differences were normalized
to repository settings with parsed AST equality verified. Python-visible return
bounds/cache guards and browser result/skip/error guards satisfy the negative-clause
rule; the browser reporter was smoke-tested to accept a genuine pass and reject
skip, todo and unhandled-rejection controls. Gate freeze and subsequent verification
report the baseline intact. Runtime results are ignored rather than committed.

[Milestone 2](https://github.com/automateintelligence/portfoliosight/milestone/2)
contains ten phase issues and 53 native task sub-issues. Phase issues
112/116/122/127/133/139/146/154/163 are ready; 170 is draft. Their assertion markers
cover all 28 IDs exactly once. No issue was marked done. Next eligible phase is
[112](https://github.com/automateintelligence/portfoliosight/issues/112), not claimed.

Review fallback is retained as [debt 175](https://github.com/automateintelligence/portfoliosight/issues/175).
Unattended selection is blocked by [176](https://github.com/automateintelligence/portfoliosight/issues/176):
the generated project driver omits the explicit run key while two records coexist.
No recurring driver, permission-bypass flags, product merge or deployment was installed.
The per-run goal and handoff preserve scope, branch checkpoints, runtime contracts,
review requirements, missing prerequisites and the next safe action.
