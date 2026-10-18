# Simulation engines and measures: Conductor implementation plan

**Normative spec:** `docs/specs/2026-10-14-portfoliosight-simulation-engines-design.md`. The spec governs on conflict; workers read each phase's Spec sections before implementation. Its committed `20b292e` amendments preserve the `a77dbf7` log-return, scaling and simulated-ruin decisions.
**Assertions:** `docs/specs/2026-10-14-portfoliosight-simulation-engines-design.assertions.md`. Assertions are the mechanical floor; their §2 unresolved interpretations remain explicit checkpoints below.

> **For agentic workers:** REQUIRED SUB-SKILL: `superpowers:subagent-driven-development` under the Conductor recipe below. Reconcile existing task commits before writing code. Checkboxes describe work to verify, not a claim that preserved work is absent or complete.

**Goal:** Complete normative spec Phases 1 and 2, retaining the replay engine and ENB ladder defaults, with verifiable simulation, diversification, page and validation behavior.

**Next milestone — owner confirmed, 2026-10-17:** Make normative spec Phase 1 ready to deploy before starting normative Phase 2. Complete Conductor phases 1–6, verify A-SE-01–16, and provide the validation report, isolated KS-001 measurements, rollback evidence and a concrete release review packet. Phase 2 is not a deployment prerequisite. Present that Phase 1 checkpoint before claiming Conductor phase 7; retain phases 7–9 as the subsequent authorized implementation scope. Deployment and generation publication remain subject to the release review described below.

**Architecture:** Keep the existing pure engine, store-backed build/range paths and tensor-driven React page. Share the upstream QSE draw across mixes, add the DR² solver beside the existing ENB solver, and calculate ENLC from the same engine paths used for ranges. Select one ladder per tensor; build both ladder variants for comparison. No general plugin layer or new optimization library is needed.

**Tech stack:** Existing NumPy/Pandas/SciPy, cvxpy/Clarabel, FastAPI/Pydantic, React/TypeScript/Zod, Vitest and Playwright. The already-authorized QSE selected pull and exact `arch==8.0.0` pin are the Phase 1 dependency additions. `pyvinecopulib` belongs only to the parked Copula work.

Date: 2026-10-17. Owner: Jeff Daniels. Host: Codex. This plan replaces the old plan's direct-to-main product integration/deploy recipe for this run; it does not replace the product methods in the spec. `docs/plans/2026-10-16-simulation-engines-phase1-plan.md` remains useful historical task detail, subject to the later spec amendments and this run's topology. Its seven stages are all normative Phase 1, not normative Phases 1–7.

## Run binding and preserved work

Use the existing registered run `2026-10-14-portfoliosight-simulation-engines-design-99dcbc03`, integration branch `conductor/run-2026-10-14-portfoliosight-simulation-engines-design-99dcbc03`, and worktree `.worktrees/run-2026-10-14-portfoliosight-simulation-engines-design-99dcbc03`. Remote is `github`. Read the registered run with its explicit run key; the legacy `run-branch name` resolver currently returns an obsolete unhashed alias and must not create or select a competing branch. Do not touch the older demo run's goal, gate, schedules or ownership.

| Existing work | Retained checkpoint | Required reconciliation |
|---|---|---|
| `feature/qse-sync` | `a73f7d4` | Compare tasks with commits and focused evidence; retain its source/guard work |
| `feature/engine-garch` | `0c82e57` | Keep log-return/ruin amendments and preserved artifact-space checks |
| `feature/engine-store` | `39b5fda` | Merge the current run branch into it after engine integration; its fork predates later engine work |
| `feature/web-engine` | `fea06bc` | Retain preserved URL/share edits; merge the run into it after store and range integration |
| `exp/garch-absorb` | Separate retained experiment | Evidence only; do not substitute it for the integrated engine implementation |
| Range endpoint and validation | No preserved implementation identified | Create the bounded phase branches below from the current run |

Read `docs/reviews/2026-10-17-simulation-engines-conductor-reconciliation.md` before each resumed branch. Preserve all history: merge **from the current run branch into each retained feature branch**, resolve conflicts against the normative spec, then review the resulting PR against the run. Do not force-push, delete, reset or cherry-pick away unmerged work. A clean preserved branch is a starting point, not evidence that its gate is green.

Normative Phase 0 remains a prerequisite. Reconcile `dashboard-bootstrap-2026-10-15` and the recorded commit `4a17431`, Worker version, container image and pinned `2026-10-14-0.2.0` generation against the runbook, annotated tag, remote tag and historical ordering. The spec originally named an October 14 tag; the October 16 plan records the October 15 tag as the completed rollback point. Verify that evidence rather than creating a second tag or claiming historical ordering from today's files. Missing rollback evidence blocks product integration; report the exact missing fact.

Docs-only updates to at most five documents follow the owner's direct-main rule. After the leader commits approved setup documents to main, merge those documentation commits into the run before claiming phases. Product code and tests always use phase PRs into the run. More than five documentation files use the owner's docs PR rule. Do not claim Claude authorship for Codex work.

## Execution order and assertion ownership

Numbers below identify Conductor phases, distinct from normative spec phases. Dependencies are explicit ledger blockers; do not derive readiness only from title order. Every assertion ID has one completion owner. Earlier tasks can implement part of a later assertion, but cannot close it before its whole observation exists.

| Conductor phase | Normative phase | Depends on | Assertion completion owner |
|---|---|---|---|
| 1 QSE pull | 1 | Phase 0 evidence and setup gate | A-SE-01 |
| 2 GARCH engine | 1 | 1 | A-SE-04, A-SE-06, A-SE-08, A-SE-09 |
| 3 Store and tensor integration | 1 | 2 | A-SE-10 |
| 4 Range API | 1 | 3 | A-SE-07, A-SE-11 |
| 5 Simulation page | 1 | 4 | A-SE-03, A-SE-05, A-SE-12, A-SE-13 |
| 6 Replay/GARCH validation | 1 | 5 | A-SE-02, A-SE-14, A-SE-15, A-SE-16 |
| 7 DR² ladders and covariance measures | 2 | 6 | A-SE-17, A-SE-18 |
| 8 ENLC and measure selection | 2 | 7; decisions C1–C3 below as applicable | A-SE-19, A-SE-20, A-SE-21 |
| 9 Measures validation | 2 | 8; decision C5 | A-SE-22, A-SE-23 |
| 10 Copula | 3, PARKED | 9 and new owner scope authorization | A-SE-24, A-SE-25, A-SE-26, A-SE-27, A-SE-28 |

The dependency/data-isolation assertion A-SE-02 runs at phase 6 because it exercises the real validation script as well as build and HTTP paths. A-SE-03/A-SE-05 include rendered page observations, so their completion belongs to phase 5. A-SE-07 includes the artifact-backed API, so it belongs to phase 4. This prevents a phase from waiting on a future phase that it itself blocks.

A-SE-16 verifies the normative Phase 1 target-host workload. A-SE-22 separately requires the Phase 2 workload rerun and 100-fund measurement in phase 9. This preserves both measurements without making phase 6 wait on a dependent phase. A-SE-11's null `loss_sources` check applies to Phase 1 tensors lacking the later attribution capability, so its assertion remains valid after Phase 2.

**Scope boundary:** A-SE-24–28 remain pending and their phase `status:draft` remains PARKED. Completing phases 1–9 completes the current authorized implementation scope, not the full-spec gate. Never omit future IDs, treat disabled Copula as implemented, close the full run, or label the full-spec assertion run green while they remain unmet. Autodev must not interpret these deliberately pending assertions as a gap to fill by inventing a new ready phase, invoking build-now planning, or promoting Copula. Once phases 1–9 are complete, checkpoint the owner's scope decision and stop this run's fires without claiming full-spec completion. Hand the owner a scoped completion packet with that distinction; any final run-to-main integration PR requires owner review and is never auto-merged. Current setup ends at a supervised checkpoint: no unattended schedule is installed while the generated driver's multi-run ambiguity remains.

## Recipe required in every phase

The full recipe applies to each phase below, including the parked phase if later promoted:

1. Reconcile the phase's commits, task checkboxes, lease and assertion state. Read its **Spec** and **ADRs** first. Use the role/model/effort mapping in `~/.codex/AGENTS.md` under “Conductor runs”: planning `gpt-6-astra`/xhigh; orchestration `gpt-6.1-sol`/high; routine implementation `gpt-6.1-sol`/xhigh; engine math, concurrency and recovery `gpt-6-astra`/xhigh; independent review/Claude fallback `gpt-6-astra`/high; review fixes `gpt-6.1-sol`/high. This mapping overrides Claude aliases and the older generated model table.
2. A fresh role-specialized subagent implements on a phase branch forked **from the run branch**; retained branches first merge the run into their existing history. Use `superpowers:subagent-driven-development`. Give each task one bounded file responsibility. Write the focused failing behavior test, confirm its intended failure, implement the smallest change, rerun that focused file and touched-file lint/typecheck, then `$code-review` against the Spec and ADRs and commit the task. Reviewers reuse fresh test evidence on identical code.
3. Open one phase PR with **base = `conductor/run-2026-10-14-portfoliosight-simulation-engines-design-99dcbc03`** and `Closes #<phase-issue>` in its body. Explain preserved commits, any changed gate contract and fresh verification. Resolve behind-base conflicts by merging from the run again, preserving history.
4. Obtain **opposite-host review ×2 by `claude`**, through the preflight-verified wrapper, against the actual phase PR, Spec and ADRs. Honor a configured `CONDUCTOR_MIN_REVIEWS` above two; do not lower it. The current owner-reported weekly Claude quota exhaustion uses the installed `conductor:autodev` step 6.5 usage-limit fallback: independent same-host `$code-review`, with actual Codex provenance. Read the configured `CONDUCTOR_REVIEW_MARKER` and `CONDUCTOR_REVIEW_AUTHOR` before posting. Each fallback comment begins with the exact configured marker followed by `— UNAVAILABLE (weekly usage limit); same-host code-review fallback`. Never claim Claude reviewed it. If the configured author excludes the posting account, record the needs-human blocker rather than changing the configuration or posting uncountable reviews.
5. Apply findings with `superpowers:receiving-code-review`; re-review while P0/P1 remain, and report failure to converge after three rounds. Fix remaining P2-and-below. A changed final commit still needs the gate-required final-state review comment after it; this freshness requirement is separate from repetitive broad review. Meet the configured eligible review count, with the newest review after the newest commit. Record same-host review debt via Conductor's `escalate.file_followup`, linked to the phase/PR, naming the weekly limit and the lost opposite-host independence; carry it in handoffs and the owner packet. The plan itself receives an independent review under the same honest fallback before issue conversion.
6. Require `conductor merge-gate`, then merge **only with `conductor merge <pr>`**, which executes the gate and performs the history-preserving merge into the run. Never use raw `gh pr merge`. The full project suite runs once per phase at this merge gate against the prospective merged tree, through owner-configured `CONDUCTOR_MERGE_VERIFY`; implementers do not run it per task or once again before opening the PR. An explicit diagnostic gate invocation must not cause an unnecessary duplicate full-suite run; inspect the installed merge command's verification behavior and retain its evidence. Resolve blockers rather than bypassing them.
7. Run `$document-release`, commit/push documentation according to the owner rule, reconcile it into the run, and execute `conductor ledger phase-done <phase-issue> --plan docs/plans/2026-10-17-simulation-engines-conductor-plan.md`. This command verifies the mapped assertions, closes task issues and ticks checkboxes. Do not mark them done manually. Write a durable handoff with base/final revisions, verification, open decisions and review debt; release ownership through Conductor. Preserve phase worktrees/branches until their work is in main; the cleanup tool may remove them only after final owner integration and only when clean.

`conductor` in this document means the installed `/home/danie906/.codex/plugins/cache/automateintelligence/conductor/0.10.0/bin/conductor`, or the successor path verified by the leader. Select this run explicitly wherever supported. Workers do not modify owner-controlled merge verification, review minimum/author/marker, permission posture, goal or schedules.

**Verification scope:** focused commands below run from the phase checkout with its verified Python environment; `npm --prefix web` runs existing web scripts. The merge gate covers Python lint/format/typecheck and the project coverage suite, plus web lint/typecheck/tests and local e2e when web behavior changes. Existing deployment/provider tests retain their established fixture/isolation mechanism; do not run the production smoke suite. The frozen assertion runner is separate from the full project suite. Missing required data/host is unmet evidence, never a passing skip.

Gate changes follow the spec's explicit pre-production rule: correct a superseded contract, document assertion/before/after/property/reason in `docs/reviews/`, and re-freeze through the installed workflow. Never weaken a check to make an implementation pass, edit a frozen baseline by hand, or silently amend owner expectations. Preserve demo assertions except for explicit successor-spec changes.

## Decision checkpoints and operational limits

The assertion artifact §2 records the unresolved observations at gate authoring. Owner resolutions below supersede the corresponding open questions in that frozen source; existing frozen checks stay unchanged. Capture remaining decisions in a reviewable spec correction or owner decision before implementing the dependent behavior; independent tasks continue meanwhile.

| Checkpoint | Decision required | Blocks |
|---|---|---|
| C1 | How to select exactly `ceil(alpha P)` tail paths when too many are tied at absorbed −100%, and whether additive attribution continues after ruin | Comprehensive ruined-tail ENLC in phase 8; do not silently choose stable sorting or truncate contributions |
| C2 | ENLC word normalization: §5.5's shifted formula versus §6's `ENLC/ref`; presentation when `ref = 1`; zero-risk DR² behavior | Final measure-word/ref degeneracy behavior in phases 7–8 |
| C3 | Whether an uncached arbitrary mix may call `/v1/range` during an engine switch despite §11's universal “no request” phrase | Universal no-request claim; precomputed-mix zero-request checks can proceed |
| C4 — RESOLVED | Owner, 2026-10-17: retain and disclose a splice outlier when no peer residual is available; exactly constant portfolios have Bad = Typical = Good at their compounded return | Apply in phase 2's degenerate-case tests; no fabricated median, jitter or rejection of cash |
| C5 | §10.7 weight-distance norm, aggregation across columns/origins and the exact realized-bad-days concentration convention | The measures comparison verdict in phase 9; raw paired measurements can proceed |
| C6 | Copula technical copy contradicts empirical margins; zero-margin concordance convention | Parked phase 10 only |

The spec already settles log-space fitting, the `sd` scale and absorption for valid simulated paths; these are not reopened under M5. M5 still prohibits repairing failed fits. A test with uniquely ranked years cannot certify C1. Report every unresolved checkpoint in final phase verification; checking only its unambiguous subset is not permission to declare the whole capability complete.

No production deployment or live generation mutation is part of setup or automatic phase integration. Performance work on KS-001 must use a separately isolated execution/store path and the owner's existing operational authority; otherwise record the missing target-host evidence and leave A-SE-16 pending. Coordinate resource use with the existing nightly; never stop it, write the backup mirror or mutate QSE's lake/lock/request budget. Prepare the runbook's later rollout sequence for owner review: compatible frontend first, inactive-nightly backend window, explicit generation publication, health/version check and recorded rollback. This plan does not execute that sequence.

The installed generated unattended driver currently omits the explicit run key in an ownership check, which is ambiguous with the older demo run. Do not install an ambiguous driver or claim unattended progress. The leader records/resolves that separate operational blocker; supervised work bound to the correct run can still progress.

## Phase 1 — Reconcile the selected QSE pull (A-SE-01)

**Spec:** §3.3 QSE boundary; §8 Data dependencies; §12 QSE pin; §13.18 Selected pull; S9, M2, M4.
**ADRs:** none
**Branch:** retain `feature/qse-sync`; depends on verified normative Phase 0 and setup gate.
**Recipe:** fresh subagent → focused TDD → `$code-review` and commit per task → one run-base PR (`Closes #<phase-issue>`) → `claude` opposite-host review ×2 or the configured quota fallback → `conductor merge-gate` → `conductor merge` → `$document-release` → `conductor ledger phase-done`, exactly as above.

- [ ] 1.1 Reconcile pinned QSE source and packaging

Reconcile `scripts/sync_qse.py`, `qse/qse.lock.json`, `qse/README.md`, `.claude/settings.json`, `pyproject.toml`, `.dockerignore` and `deploy/Dockerfile` against `a73f7d4`. Verify pin `ca8c0445a56712c92dc028e68845b94963fdd590` and exact `arch==8.0.0`. Preserve the ten-file upstream closure and package discovery/data inclusion. Do not reformat vendored files or introduce a pip-installed QSE package.
- [ ] 1.2 Verify offline source attestation and sync mutation guards

Extend `tests/test_qse_sync.py` only for missing A-SE-01 observations: attest trusted source hashes once against upstream git objects and anchor them in the frozen assertion, then make ordinary gate runs compare those hashes without the private QSE checkout or GitHub. Exercise the real sync with a tiny synthetic git repository; mutate a byte and add an unlisted source file in disposable copies, verify both fail with the private checkout unavailable, re-sync from the synthetic repository and prove its working tree unchanged. Check read-only modes and tracked agent deny rules. Run `.venv/bin/python -m pytest tests/test_qse_sync.py -q`; expected: faithful sync passes and both negative mutations are rejected.
- [ ] 1.3 Verify dependency closure, container packaging and upstream tests

Reconcile `tests/test_dependencies.py`, `tests/deploy/test_compose.py` and `tests/deploy/test_dockerignore.py`; run those focused files and the pinned QSE joint/recursion tests against the copied package in a temporary directory. Record counts and package provenance, then remove temporary copied tests. These are partial dependency-boundary evidence; A-SE-02 closes only when the actual API and validation flow exist in phase 6.

**Acceptance:** source-provenance assertion green, package/import evidence captured, and retained branch integrated through the recipe. No deployment is needed to close this phase.

## Phase 2 — Reconcile GARCH shape, levels and ruin (A-SE-04, A-SE-06, A-SE-08, A-SE-09)

**Spec:** §4.1 Common frame; §4.3 GARCH; amended §4.5 Scaling and ruin; §7 Versions and tensor; §9 Memory; §10.5 Invariants; S4, F5, F6, M5, M6.
**ADRs:** none
**Branch:** retain `feature/engine-garch`; depends on phase 1; engine-math model/effort applies.
**Recipe:** fresh subagent → focused TDD → `$code-review` and task commits → run-base PR (`Closes #<phase-issue>`) → `claude` review ×2/configured quota fallback → `conductor merge-gate` → `conductor merge` → `$document-release` → `conductor ledger phase-done`.

- [ ] 2.1 Reconcile shape history, fitting and splice boundaries

Merge the run into the retained branch. Read `portfoliosight/engine/shape.py` and preserved `tests/engine/test_shape.py`; retain the simple-return shape digest with canonical NaNs and fit `log1p(panel)` only on available rows through `D_G`, at most 2,520 union-calendar rows. Reject history at/below −1 with fund/date. Verify residual common rows, 126-row floor, log-space fallback thresholds/statuses and splice/outlier boundary fixtures. Run `.venv/bin/python -m pytest tests/engine/test_shape.py -q`; apply C4's recorded owner resolution in its degenerate-case tests.
- [ ] 2.2 Verify amended log/simple-space level scaling

Verify `portfoliosight/engine/ranges.py` implements the amended two-space calculation in bounded path/mix chunks. Preserve one raw log panel; use lognormal targets for each fund, `expm1`, then pooled simple means/covariance and the mix correction. The old plan's affine transform on the raw panel is superseded. Add an asymmetric independent oracle in `tests/engine/test_ranges.py` where transformed simple mean differs from its target and `k != 1`; compare daily paths, not merely percentiles.

```python
# Independent test oracle for the nondegenerate amended formula.
daily_mean = annual_mean / 252
daily_sd = np.sqrt(np.diag(annual_cov) / 252)
log_var = np.log1p(daily_sd**2 / (1 + daily_mean)**2)
log_mean = np.log1p(daily_mean) - log_var / 2
raw_mean = raw_log.mean(axis=(0, 1))
raw_sd = raw_log.std(axis=(0, 1), ddof=0)
fund_simple = np.expm1(log_mean + (raw_log - raw_mean) * np.sqrt(log_var) / raw_sd)
mix = fund_simple @ weights
target_mean = daily_mean @ weights
target_sd = np.sqrt(weights @ annual_cov @ weights / 252)
expected_daily = target_mean + (mix - mix.mean()) * target_sd / mix.std(ddof=0)
assert abs(expected_daily.mean() - target_mean) < 1e-12
assert abs(expected_daily.std(ddof=0) - target_sd) < 1e-12
```

- [ ] 2.3 Verify constants, absorption and ruin disclosure

Test constant-fund/mix branches separately from that nonzero-spread oracle. In `tests/engine/test_ranges.py`, cover exactly −1, below −1, repeated ruin days and later gains: valid simulated paths absorb once to year −1, replay invalid days raise, nonruined paths keep exact compounding. Verify `method.returns=log`, `scale=sd`, `ruin=absorb` and maximum `ruin_paths` across all carried mixes in `tests/engine/test_builder.py`. Do not cap variance or resample/extirpate an offending simulated path.
- [ ] 2.4 Reconcile tensor version, provenance and browser compatibility

Reconcile `portfoliosight/engine/builder.py`, `portfoliosight/engine/tensor.schema.json`, `portfoliosight/engine/__init__.py`, `scripts/build_tensor.py`, `web/src/api/tensor.ts` and `web/fixtures/guide2017_5y.json`. Keep engine version 0.3.0/schema 3, unchanged universe-hash schema, default range aliases, per-engine ranges/safe endpoints and traceable shape/method metadata. Keep schema-2 rollback reader compatibility. Regenerate the fixture only through the exact existing pinned CLI test invocation; never edit generated numbers manually.
- [ ] 2.5 Verify deterministic engine output and memory bounds

Run focused `tests/engine/test_ranges.py`, `tests/engine/test_builder.py`, `tests/engine/test_build_cli.py`, `tests/engine/test_schema_sources.py` and `web/tests/tensor-sources.test.ts`. Compare deterministic builds across supported worker counts, nondegenerate quantiles and constant compounding without jitter, and record the 30-fund memory check. Preserve replay baselines for phase 5's end-to-end default assertion.

**Acceptance:** mapped engine assertions green; method metadata reflects actual arithmetic; C4 limits are resolved or explicitly block the affected behavior. Store/API/page claims remain assigned to their integration phases.

## Phase 3 — Reconcile artifacts, builds and nightly (A-SE-10)

**Spec:** §4.1 Determinism; §7 Model artifacts, tensor and engine settings; §8 Store boundary; §9 Memory; §11 Phase 1; §13.13/14 Rollback retention and precision.
**ADRs:** none
**Branch:** retain `feature/engine-store`; depends on phase 2.
**Recipe:** fresh subagent → focused TDD → `$code-review` and task commits → run-base PR (`Closes #<phase-issue>`) → `claude` review ×2/configured quota fallback → `conductor merge-gate` → `conductor merge` → `$document-release` → `conductor ledger phase-done`.

- [ ] 3.1 Integrate engine amendments into artifact-backed builds

Merge the run into `feature/engine-store` to bring in the post-fork engine updates. Reconcile `portfoliosight/jobs/build.py`, `portfoliosight/api/presets.py`, `portfoliosight/api/settings.py` and `portfoliosight/api/queue.py`: fit/artifact reuse is keyed by generation and full shape identity, shared across matching included sets/lookbacks/caps, with immutable `garch.json` and `pool.npy` written before tensor publication. Validate serialized log-return provenance instead of assuming every old artifact has current semantics.
- [ ] 3.2 Verify immutable artifact reuse and engine settings

In `tests/jobs/test_build.py`, use a counting temporary store to prove one fit for shared fund sets, a new fit for changed shape/included funds, no overwrite of existing immutable artifacts, cache accounting, unavailable configured engines and identical cold/reused canonical tensors. Keep `PS_ENGINES=replay,garch` and `PS_ENGINES_CUSTOM` excluding Copula; reject unknown settings and preserve replay.
- [ ] 3.3 Verify nightly publication and pinned-model retention

Reconcile `portfoliosight/jobs/nightly.py` and `tests/jobs/test_nightly.py`: generation discovery/pruning includes models, pinned rollback generations keep tensors and models, metadata names actual engines, incomplete builds cannot publish the current pointer. Run `.venv/bin/python -m pytest tests/jobs/test_build.py tests/jobs/test_nightly.py -q`.
- [ ] 3.4 Run read-only preset builds against the mirror

Reconcile `scripts/build_presets.py` and its focused fixture-store test in `tests/test_smoke_scripts.py`. Prove it reads `/mnt/d/portfoliosight-data` without writing by directing all outputs to `runs/dry-0.3.0/` and comparing source-store digests in the temporary-store test. Run both presets and all six lookbacks against the available mirror; record statuses, pools, outliers, artifact reuse and timing as local evidence. A splice failure remains a data finding, not permission to relax the guard.

**Acceptance:** A-SE-10 independently verifies actual percentiles, aliases, safe endpoints and canonical equality including artifact reuse. Local build results are not KS-001 performance proof. Record rollback/deployment instructions in `docs/plans/2026-10-13-ks001-cloudflare-runbook.md` without executing rollout.

## Phase 4 — Add engine-aware range requests (A-SE-07, A-SE-11)

**Spec:** §4.1 Shared draws; §4.3 Long-run start; §7 Range API, artifacts and health; §9 Request budget; §13.14 Precision; S3, S10, F4, F6, F7, M6.
**ADRs:** none
**Branch:** new `feature/range-engine` from the run; depends on phase 3.
**Recipe:** fresh subagent → focused TDD → `$code-review` and task commits → run-base PR (`Closes #<phase-issue>`) → `claude` review ×2/configured quota fallback → `conductor merge-gate` → `conductor merge` → `$document-release` → `conductor ledger phase-done`.

- [ ] 4.1 Write real-route engine selection and refusal tests

First add real-route cases in `tests/api/test_range.py` and `tests/api/test_routes.py`: omitted engine resolves the tensor default; replay/GARCH identify themselves and differ on a nonconstant fixture; unknown ID is 422; absent/unavailable engine, missing artifact and fresh shape/lookback mismatch each produce 409 `range_unavailable`. Include unseen weights and a cleared-cache corruption case so a stale model cannot hide the failure.
- [ ] 4.2 Implement verified engine dispatch and bounded caches

Update `portfoliosight/api/models.py`, `portfoliosight/api/ranges.py`, `portfoliosight/api/app.py` and the loader in `portfoliosight/jobs/build.py`. Strictly accept the three engine IDs, dispatch only a carried ready engine, reconstruct GARCH from verified artifacts and return `engine` plus `loss_sources: null` until phase 8. Keep the eight-lookback cache and a separate two-panel float32 LRU keyed by full shape digest and engine; invalidate/recheck source data as required before reuse. Do not let the truncated storage path become the sole integrity check.
- [ ] 4.3 Verify shared draw and artifact-backed restart reproduction

Capture the draw consumed by actual build and API in `tests/engine/test_ranges.py` and `tests/api/test_range.py`: 2,000 × 252, seed 20261013, whole shared rows, initial variance `omega/(1-alpha-beta)` rather than the final fitted variance. After restart, load artifacts and reproduce the same draw; reordered requests cannot redraw per mix. Quantify API float32 error separately from exact build equality.
- [ ] 4.4 Verify artifact lifecycle and cache eviction through real flows

Complete A-SE-11's lifecycle matrix through `tests/api/test_range.py` and `tests/jobs/test_build.py`: count real fits across same-shape lookbacks/caps, verify generation-scoped immutable artifacts, restart/reload, request three shapes to observe eviction from the two-panel float32 LRU, and retain the eight-lookback sample cache. Exercise pruning with a pinned and unpinned generation in `tests/jobs/test_nightly.py`; pinned models remain usable and the unpinned models are removed with their generation. Do not substitute cache declarations for observed cache behavior.
- [ ] 4.5 Verify health, Worker forwarding and range instrumentation

Add configured engine health coverage in `tests/api/test_healthcheck.py`; exercise actual Worker `/api/range` forwarding in `web/tests/worker-routing.test.ts`. Run `.venv/bin/python -m pytest tests/api/test_range.py tests/api/test_routes.py tests/api/test_healthcheck.py -q` and `npm --prefix web test -- tests/worker-routing.test.ts`. Record warm/cold timing instrumentation for phase 6, without presenting laptop timing as target-host acceptance.

**Acceptance:** mapped shared-draw and HTTP assertions green through real dispatch, with no engine substitution and with all refusal paths observable.

## Phase 5 — Reconcile simulation controls, ranges and links (A-SE-03, A-SE-05, A-SE-12, A-SE-13)

**Spec:** §4.2 Replay; §4.3 Named fallbacks; §6 Controls, copy, engine changes and URL; §7 Tensor aliases; §13.1/7/9/10 Defaults, safe endpoints and bar scale; S2–S5, S10, F1, F3, F4.
**ADRs:** none
**Branch:** retain `feature/web-engine`; depends on phase 4.
**Recipe:** fresh subagent → focused TDD → `$code-review` and task commits → run-base PR (`Closes #<phase-issue>`) → `claude` review ×2/configured quota fallback → `conductor merge-gate` → `conductor merge` → `$document-release` → `conductor ledger phase-done`.

- [ ] 5.1 Reconcile engine URL state and share validation

Merge the run into the retained branch, preserving URL/share WIP history. Reconcile `web/src/state/url.ts`, `web/src/state/store.ts`, `web/worker/share.ts`: `e=replay|garch|copula`, omitted replay, canonical position after `x`, unavailable-engine handling with visible reason and faithful address, no localStorage override. Test malformed values, fresh-page round trips and the actual share payload with inert mail transport in `web/tests/url.test.ts`, `web/tests/reducer.test.ts` and `web/tests/worker-share.test.ts`.
- [ ] 5.2 Reconcile engine range surfaces and stale-response protection

Reconcile `web/src/math/portfolio.ts`, `web/src/math/view.ts`, `web/src/math/stripScale.ts`, `web/src/state/useExactRange.ts`, `web/src/api/http.ts` and `web/src/App.tsx`. Thread one selected engine through every range/readout/card; key exact responses by tensor/weights/engine; reject stale replies; clamp risk/URL to its safe endpoint; use a fixed bar scale covering all carried engines. Resolve C3 for uncached interpolated switches; precomputed selections must remain request-free.
- [ ] 5.3 Reconcile Simulation controls, provenance and fallback copy

Reconcile `web/src/sections/Settings.tsx`, `web/src/controls/ResultStrip.tsx`, `web/src/controls/RiskSlider.tsx`, `web/src/chart/MixCard.tsx` and `web/src/copy.ts`. Show the three specified Simulation labels, muted engine tags, disabled reasons, fallback fund names/pool rows and truthful Method lines. Preserve the existing design system; leave the normal figure in details. Keep Copula unavailable until its real phase.
- [ ] 5.4 Verify atomic engine switching and baseline preservation

Run focused URL/reducer/share, fidelity, strip-scale, exact-range and copy tests. Extend `web/e2e/local/app.spec.ts` with distinct engine tensors and intercepted requests: switch each precomputed selection, verify all visible range surfaces update, no request occurs, chart coordinates/weights stay fixed, tags and clamped URL agree, then switch back and reload. Verify default replay against preserved pre-engine values and both preset fallback displays.
- [ ] 5.5 Capture desktop and phone engine-selection evidence

Capture local desktop/phone screenshots using `web/e2e/local/screenshots.spec.ts`, details off/on, each available engine. Store dated images under `docs/reviews/` and link them from the review report for owner inspection. Run the applicable visual-verdict workflow per UI iteration before the next edit. Screenshots support owner judgment; neither image existence nor a subjective score substitutes for assertions.

**Acceptance:** all four assigned assertions green, including actual rendered fallback/default behavior and canonical share validation. No mail is sent and no production frontend is deployed by this phase.

## Phase 6 — Validate replay and GARCH with measured evidence (A-SE-02, A-SE-14, A-SE-15, A-SE-16)

**Spec:** §8 Data boundary; §9 Budgets; §10.1/2/4/5/8 Validation; §11 Phase 1; §12 Risks; S8, S11, F8, M3, M4, M6.
**ADRs:** none
**Branch:** new `feature/backtest-ranges` from the run; depends on phase 5.
**Recipe:** fresh subagent → focused TDD → `$code-review` and task commits → run-base PR (`Closes #<phase-issue>`) → `claude` review ×2/configured quota fallback → `conductor merge-gate` → `conductor merge` → `$document-release` → `conductor ledger phase-done`.

- [ ] 6.1 Implement backtest commands with independent metric fixtures

Create `scripts/backtest_ranges.py` and `tests/test_backtest_ranges.py`. Implement `coverage`, `compare`, `seeds` subcommands with `--store-dir`, `--menus`, `--lookbacks`, `--engines`, `--out`; use existing store/build/path helpers. Write small hand-calculated cases first for realized constant-mix 252-day returns, coverage/breaches, pinball loss and PIT. Verify 40 quarter-end origins from 2015-12-31 through 2025-09-30 and the ten non-overlapping year-end origins using the existing calendar dependency. Log insufficient-future-history observations with their reason; never silently omit them from denominators.

```python
# Numerical fixtures for the validation tests, independent of production helpers.
error = np.array([-0.10, 0.20])
tau = 0.025
expected_pinball = np.maximum(tau * error, (tau - 1) * error)
np.testing.assert_allclose(expected_pinball, [0.0975, 0.005])
daily = np.array([[0.10, 0.00], [-0.10, 0.10]])
w = np.array([0.5, 0.5])
assert np.isclose(np.prod(1 + daily @ w) - 1, 0.05)
```

- [ ] 6.2 Verify origin isolation and paired engine comparisons

In `tests/test_backtest_ranges.py`, change observations strictly after an origin and prove predictions remain unchanged while realized returns change. Pair engine comparisons on identical origin/lookback/weights; disclose engine-specific `s_safe` selections separately rather than comparing different portfolios under one paired label. The mix set includes the three specified frontier/Optimized columns, entered/equal-weight and all single funds. Run `.venv/bin/python -m pytest tests/test_backtest_ranges.py -q` against small fixture-store timelines before the long mirror run.
- [ ] 6.3 Verify the declared dependency and data boundary end to end

Extend `tests/test_dependencies.py` and the integration fixtures to block QSE data/storage/credentials/provider access while exercising a real fit, build, HTTP range and small validation command. Prepare/attest the isolated declared-dependency environment once; ordinary gate execution does not install packages online, and its import probe excludes unrelated preloaded application modules. Check attempted access even when caught by production code. Confirm the declared runtime dependency boundary and unchanged backup mirror. This completes A-SE-02 rather than merely scanning imports.
- [ ] 6.4 Run the prescribed mirror experiment and write its report

Run the real mirror experiment for both presets and 1y/5y, save reproducible raw rows under `runs/backtest/`, and write `docs/reviews/2026-10-17_engine-validation.md` with both origin sets, paired quantile losses/sign counts, PIT diagnostic, live-menu/stress comparisons and independent invariant evidence. State overlap, weak ten-year evidence, correlated mixes and shorter stress windows. Preserve §10.8's numerical rule verbatim in meaning; unfavorable results stay visible. `range_default` remains replay.
- [ ] 6.5 Measure Bad-year stability and explain engine differences

Evaluate all frontier nodes/Optimized points with seeds 20261013–20261017 and full 2,000 × 252 draws. Record each Bad-year standard deviation versus `0.10*sigma_w`, including failures. Extend `compare` to all six lookbacks for the owner's plain-language `docs/reviews/2026-10-17_replay-vs-volatility-model.md`: median/largest differences, full node tables, regime/shape explanation, named fallback funds, pools, ruin disclosures and each model's limitations. Link to the validation decision; do not choose the default.
- [ ] 6.6 Measure the isolated KS-001 Phase 1 workloads

Measure an isolated real KS-001 four-vCPU workload with frozen inputs, actual revision and resource limits: 23-fund build including fitting ≤30 s, both presets ×six lookbacks nightly ≤10 min, warm replay/GARCH HTTP ranges <1 s. Record cold/warm conditions, path dimensions and results in `docs/plans/2026-10-13-ks001-cloudflare-runbook.md`. If target resources are unavailable, leave A-SE-16 unresolved. Apply only a named §9 fallback, remeasure and disclose it; never reduce path count. No production publication/deployment is implied.

**Acceptance:** genuine numerical/provider-boundary evidence, the complete report and target-host measurements satisfy assigned assertions. Completion establishes normative Phase 1 only. Update `ROADMAP.md` with actual delivery/report status under the docs rule.

## Phase 7 — Build DR² ladders and covariance-measure fields (A-SE-17, A-SE-18)

**Spec:** §2 Correlated-menu finding; §5.1/2/5 ENB and DR²; §6 Measure-switch geometry; §6.2 Menu sizes; §7 Fields/versions; §10.3 Bounds; §11 Phase 2; §13.1/15 Defaults and words.
**ADRs:** none
**Branch:** new `feature/engine-measures` from the run; depends on phase 6; engine-math model/effort applies.
**Recipe:** fresh subagent → focused TDD → `$code-review` and task commits → run-base PR (`Closes #<phase-issue>`) → `claude` review ×2/configured quota fallback → `conductor merge-gate` → `conductor merge` → `$document-release` → `conductor ledger phase-done`.

- [ ] 7.1 Implement and verify DR-squared in Python and TypeScript

Create `portfoliosight/engine/measures.py` for the pure covariance DR² calculation and `tests/engine/test_measures.py`; add the matching browser calculation in `web/src/math/portfolio.ts` with `web/tests/fidelity.test.ts` coverage. Use `(w @ sigma)**2 / (w @ cov @ w)` on nonzero-risk mixes. Test every single fund (tolerance 1e-9), uncorrelated inverse-volatility weights, correlation 0.95 and negative-correlation controls. Do not clip a hedged pair to its holding count. Resolve C2's zero-risk contract rather than inventing a denominator epsilon.

```python
# Independent analytic identities, including a control that must exceed its count.
def pair_score(rho):
    cov = np.array([[1.0, rho], [rho, 1.0]])
    w = np.array([0.5, 0.5])
    return (w.sum() ** 2) / (w @ cov @ w)

assert np.isclose(pair_score(0.95), 2 / 1.95)
assert np.isclose(pair_score(0.0), 2)
assert pair_score(-0.5) > 2
```

- [ ] 7.2 Implement the parametrized DR-squared conic program

Add a focused `portfoliosight/engine/ladder_dr2.py` and `tests/engine/test_ladder_dr2.py`, reusing the conic solver tolerances/Cholesky factor/retry conventions in `portfoliosight/engine/optimize.py`. Build a DPP-parametrized cvxpy/Clarabel program maximizing `sigma @ w` with risk ceiling, return floor, sum-to-one and existing min/max bounds. A small enumerable two/three-fund case independently validates its objective. Preserve binding and nonbinding solutions at actual risk; never move a DR² solution onto the line merely for appearance.

```python
# Required conic program, using the existing solver and tolerance conventions.
w = cp.Variable(len(mu))
risk_limit = cp.Parameter(nonneg=True)
return_floor = cp.Parameter()
problem = cp.Problem(cp.Maximize(sigma @ w), [
    cp.norm(factor @ w, 2) <= risk_limit,
    mu @ w >= return_floor,
    cp.sum(w) == 1,
    w >= lo,
    w <= hi,
])
```

- [ ] 7.3 Preserve feasible monotone ladders and truthful risk flags

Preserve candidate-pool selection in `portfoliosight/engine/ladder_dr2.py` and the integration in `portfoliosight/engine/surface.py`: at each floor choose the eligible candidate with greatest actual DR²; include frontier/peak/program answers; preserve collapsed columns. Test nondecreasing DR² and nonincreasing return down each ladder, caps/risk ceilings, `on_line` truth against inherited tolerance and midpoint hops below `0.99*X_j`. Adapt only the necessary shared interfaces in `portfoliosight/engine/ladder.py`; retain ENB's current solver and default behavior. Ensure multiprocessing uses serializable numerical inputs and deterministic ordering, as in `portfoliosight/engine/parallel.py`.
- [ ] 7.4 Build distinct ladder variants and covariance-measure fields

Thread `LADDER_MEASURE` (default `enb`) through `portfoliosight/engine/builder.py`, `portfoliosight/engine/surface.py` and `scripts/build_tensor.py`; build distinct `enb` and `dr2` variants for the same inputs. Each tensor carries one chosen ladder, plus `ladder.measure/z/dr2/enb/on_line`, `grid.z/dr2/enb`, `refs.dr2/enb`, `enb_ref=refs.enb` and top-level `min_pair_correlation`. Calculate references on the actual shipped ladder, not another optimizer's ladder. Raster blends carry covariance measures only. Extend `_post_check` so the risk-line equality applies only when flagged on; feasibility/risk-ceiling checks always apply.
- [ ] 7.5 Integrate versioned tensor contracts and browser hop behavior

Update `portfoliosight/engine/tensor.schema.json`, `web/src/api/tensor.ts`, `portfoliosight/engine/__init__.py` and real generated fixtures together: engine version 0.4.0; increment schema only if required-field compatibility demands it. Keep the rollback-reader policy explicit. Add dimensions and malformed/false-flag tests in `tests/engine/test_builder.py`, `tests/engine/test_schema_sources.py`, `web/tests/tensor-sources.test.ts` and `web/tests/fidelity.test.ts`; confirm the existing browser interpolation honors flagged hops for DR² arrays. Range generation runs for each variant's actual weights, not reused ENB weights.
- [ ] 7.6 Verify both solvers and prepare large-menu measurement

Run `.venv/bin/python -m pytest tests/engine/test_measures.py tests/engine/test_ladder_dr2.py tests/engine/test_surface.py tests/engine/test_builder.py -q` and `npm --prefix web test -- tests/fidelity.test.ts tests/tensor-sources.test.ts`. Repeat the targeted deterministic solver case at supported worker counts. Prepare the existing `scripts/bench_build.py` comparison for 100 funds, keeping public/admin limits and on-demand-only large menus. Do not invent a 30-second target for 100 funds or switch the default based on local solver speed.

- [ ] 7.7 Add deterministic extra ENB starts for 100-fund menus

Update `portfoliosight/engine/ladder.py`'s peak-start selection (`RANDOM_STARTS` and `_own_starts`) so 100-fund ENB searches use a bounded number of extra random starts as required by §6.2. The spec does not choose the count: the implementer selects and records a finite count with numerical/runtime evidence. Reuse the existing seeded generator and solver; keep the ≤30-fund start sequence/count and resulting baseline tensors unchanged. Add focused cases in `tests/engine/test_ladder.py` and `tests/engine/test_parallel.py` proving more starts at 100 funds, deterministic starts/results on repeated builds and supported worker counts, and unchanged small-menu behavior. Run those focused files. Include the selected count and the measured 100-fund ENB runtime beside DR² in phase 9's report; this change does not authorize a default or replay-method change.

**Acceptance:** both optimization paths exist and mapped numerical/ladder/browser assertions pass. ENB remains the default, and a user changing display measure will not swap the tensor's mixes.

## Phase 8 — Add ENLC, measure controls and sharing (A-SE-19, A-SE-20, A-SE-21)

**Spec:** amended §4.5 Attribution; §5.3/5 ENLC; §6 Controls/URL/copy; §6.1 Scores, not holdings; §7 Loss-source fields/API; §10.3 Bounds; §13.2/3/5/6; S6, S7, S10, F2, F3, F7.
**ADRs:** none
**Branch:** new `feature/loss-sources` from the run; depends on phase 7; C1–C3 must be resolved for their affected final behaviors.
**Recipe:** fresh subagent → focused TDD → `$code-review` and task commits → run-base PR (`Closes #<phase-issue>`) → `claude` review ×2/configured quota fallback → `conductor merge-gate` → `conductor merge` → `$document-release` → `conductor ledger phase-done`.

- [ ] 8.1 Implement additive loss contributions from shared engine paths

Create `portfoliosight/engine/loss_sources.py` and `tests/engine/test_loss_sources.py`; expose reusable per-path per-fund sums from `portfoliosight/engine/ranges.py` without a second simulation. For simulated engines use `C_pn = w_n * (252*m_n + k_w*(S_pn-252*Rbar_n))`; for replay derive contributions from its unchanged recentered resampled days (`k=1`, per-fund sample centering before shared bootstrap indices). Verify contributions sum to the additive mix year, and select tails by the engine's **compounded** years, not the additive sum. Cache `S` once per fund set/engine/lookback; do not store a giant per-mix contribution tensor.
- [ ] 8.2 Verify tail selection, loser shares, hedges and null outcomes

Test uniquely ranked worst-year sets, a hedge, zero holdings, single losers, all-gain/no-loss cases and more than three losers with hand-calculated oracles. Use `ceil(alpha*2000)` paths, initially alpha 0.05; positive loss shares only; `exp(-sum(s*log(s)))`; top three positive shares descending with actual IDs; negative contributions listed as hedges; no positive loss means null. Add C1's decided ruined/tied-tail tests before comprehensive acceptance, with the decision cited. Preserve an unchanged draw across neighboring weights and engines' distinct path populations.

```python
# Independent ENLC oracle: the second fund is a hedge, the fourth is unheld.
loss = np.array([3.0, -2.0, 1.0, 0.0])
positive = np.maximum(loss, 0.0)
shares = positive / positive.sum()
active = shares > 0
expected = np.exp(-(shares[active] * np.log(shares[active])).sum())
np.testing.assert_allclose(shares, [0.75, 0.0, 0.25, 0.0])
assert 1 < expected < 2
```

- [ ] 8.3 Expose actual loss sources in tensors and range responses

Update `portfoliosight/engine/builder.py` and `portfoliosight/engine/tensor.schema.json`: per-engine `ladder.loss_sources` and `entered.loss_sources` with nullable `n_eff`, `top` and `hedges`; `refs.enlc[engine]` from that engine's defined ladder values; no raster ENLC. Update `portfoliosight/api/ranges.py` to return loss sources from the very same requested model/weights/year paths as its range. Exercise novel weights and both engines through the actual endpoint in `tests/api/test_range.py`; a fixed placeholder loss block must fail the test.
- [ ] 8.4 Handle pending loss results and reject stale responses

Update `web/src/api/tensor.ts`, `web/src/api/http.ts`, `web/src/state/useExactRange.ts` and `web/src/math/view.ts` to parse loss sources, distinguish undefined/null/no-response states, and show nearer-level values while an interpolated request is pending. Key/cancel requests by tensor, weights and engine; verify a late response for the previous mix/engine cannot replace current details. Add these cases in `web/tests/exact-range.test.tsx` and `web/tests/fidelity.test.ts`.
- [ ] 8.5 Add measure selection, canonical links and truthful map state

Add `m=dr2|enb|enlc` in `web/src/state/url.ts`, `web/src/state/store.ts` and `web/worker/share.ts`. An absent measure is resolved from the loaded tensor's `ladder.measure`, not assumed in URL parsing; omit the resolved default, serialize `e` then `m` after `x`, and retain the existing key order. Add details-only measure radios in `web/src/sections/Settings.tsx`. DR²/ENB selection changes map colors/legend/word/reference, never weights or geometry; ENLC leaves the map/Optimized point on `ladder.measure` with a truthful map label. Undefined ENLC shows “no losses to share out” and the specified DR² fallback. Apply C2's recorded normalization/degenerate-reference decision consistently.
- [ ] 8.6 Verify covariance-measure normalization and word boundaries

Add an independent rendered-word oracle in `web/tests/word.test.ts` for both DR² and ENB with `ref>1`: compute `q=(measure-1)/(ref-1)` and test immediately below, at and above 0.30/0.50/0.75. Expected words are Poor/Fair/Average/Good with inclusive lower boundaries for Fair/Average/Good. Include a correlated-menu reference where legacy `measure/ref` would assign a different word; the test must reject that legacy normalization. Keep C2's disputed ENLC and `ref=1` decisions separate from this settled covariance-measure rule.
- [ ] 8.7 Render measure details without holdings-count claims

Update `web/src/chart/Heatmap.tsx`, `web/src/chart/MixCard.tsx`, `web/src/controls/DivSlider.tsx`, `web/src/controls/ResultStrip.tsx`, `web/src/math/portfolio.ts`, `web/src/math/view.ts` and `web/src/copy.ts` only where measure presentation needs it. Default copy shows word/map. Details show percentage of the best found; raw measure values appear only in named technical lines followed by “A score, not a count of funds or stocks.” Remove “equivalent of”/“independent bets” from all nontechnical served paths, including ENB cards/hover. Show actual hedge names and active engine/tail level; never label entropy as a holdings count.
- [ ] 8.8 Verify every measure/engine flow and capture map comparisons

Run focused loss-source/API, URL/reducer/share, word/copy, exact-range and card tests. Extend `web/e2e/local/app.spec.ts` to every available engine/measure combination, details visibility, no-loss fallback, delayed/reordered responses and a fresh shared URL using an inert mail transport. Inspect rendered copy across these cases, not source comments. Capture both menus' before/after ENB/DR² maps at identical risk positions/lookbacks and desktop/phone sizes with `web/e2e/local/screenshots.spec.ts`; save dated images under `docs/reviews/` and obtain visual-verdict evidence per iteration.

**Acceptance:** real loss-source math/API and served controls/copy satisfy A-SE-19–21; C1–C3 no longer hide behind narrow fixtures. No ENLC optimization/raster or default/headline promotion is introduced.

## Phase 9 — Compare measures, stability and performance (A-SE-22, A-SE-23)

**Spec:** §5.5 Recommendation; §6.1 Presentation; §6.2 Large menus; §9 Performance; §10.3/4/7/8 Validation; §11 Phase 2; §13.1/5/15; S6–S8, S11, F8, M3, M6.
**ADRs:** none
**Branch:** new `feature/validate-measures` from the run; depends on phase 8 and C5 for the final verdict.
**Recipe:** fresh subagent → focused TDD → `$code-review` and task commits → run-base PR (`Closes #<phase-issue>`) → `claude` review ×2/configured quota fallback → `conductor merge-gate` → `conductor merge` → `$document-release` → `conductor ledger phase-done`.

- [ ] 9.1 Extend validation to both actual ladder methods

Extend `scripts/backtest_ranges.py` with `measures` and the ENLC portion of `seeds`; add tests to `tests/test_backtest_ranges.py`. Build real ENB and DR² ladders on identical origins/menus/lookbacks/bounds; save the Optimized and peak weights at every column with input digests and subsequent realized prices. Verify that selecting the other optimizer actually changes the numerical solve path, not only metadata.
- [ ] 9.2 Compute paired realized-risk, loss and stability metrics

Record paired realized-risk absolute errors and exceedances above `1.25*predicted risk`, stress/worst-year losses, realized bad-days loss concentration, realized return given up relative to the same-column frontier, and weight stability across consecutive origins/lookbacks. Resolve and freeze C5's metric norms/aggregations before interpreting results; disclose choices and independent hand-calculated tests. Do not select a norm or aggregation because it makes DR² win.
- [ ] 9.3 Report single-fund identities, qualified bounds and map behavior

Run single-fund and bound checks on both presets and every lookback. Record DR²=1 to 1e-9; ENLC exactly 1 for a single losing fund and null otherwise; held-count tests at `w>1e-6`, with the `>0.5%` count alongside. Qualify DR² bounds by held-pair nonnegative correlation. Report ENB's original inflation, minimum menu correlation, off-line/hop/collapsed counts and word distribution. Recalibrate §13.15 cut points only under its stated empty/nearly-all condition, with before/after evidence and no change to default authority.
- [ ] 9.4 Measure ENLC seed stability without hiding failed runs

Recompute ENLC at every required point/engine for seeds 20261013–20261017 with 2,000 paths. Keep each numeric/null result. If alpha 5% fails standard deviation ≤0.3, retain the failed run and make the authorized complete alpha 10% rerun, updating recorded method/tail copy consistently. Numeric/null transitions and a failed final check remain unresolved results; do not replace null with zero, drop seeds or vary alpha per point. Retest Bad stability after any changed numerical pipeline.
- [ ] 9.5 Remeasure Phase 2 budgets and the 100-fund DR-squared case

Rerun the A-SE-16 KS-001 workload with Phase 2 enabled and both configured ladder builds accounted for honestly. Measure 100-fund DR² and ENB with the existing `scripts/bench_build.py`, recording the ENB extra-start count, cores, workers, wall time, peak memory and cache state; no new 100-fund numerical budget is implied. Add the expected-wait notice in `web/src/App.tsx` using measured large-menu behavior, with focused `web/tests/scale100.test.ts`/`web/tests/smoke.test.tsx` coverage. Keep >30-fund menus on demand and the existing public/admin authorization checks. No new benchmark dependency is needed.
- [ ] 9.6 Publish the measures verdict for owner review

Extend `docs/reviews/2026-10-17_engine-validation.md` with tables for each menu and a one-paragraph §10.7 verdict, all quantitative/seed/performance failures, links to identical-state before/after map screenshots, and a clear account of whether each prescribed criterion was met. The result may favor ENB; a tie preserves it. Refresh the runbook and `ROADMAP.md` with observed status. Leave `range_default=replay`, default `LADDER_MEASURE=enb` and ENLC's headline status unchanged until the owner reads the report and explicitly decides.

**Acceptance:** A-SE-22–23 green, prior A-SE-16 still verified with Phase 2, all current-scope assertions green and unresolved owner judgments clearly identified. Prepare the scoped owner review packet; do not close the full-spec run while Copula is PARKED.

## Phase 10 — Copula upstream, integration and validation (A-SE-24, A-SE-25, A-SE-26, A-SE-27, A-SE-28) [draft]

**Spec:** §4.4 Copula; amended §4.5 Shared level/ruin path; §6 Copy and controls; §7 Artifacts/API; §9 Named fallbacks; §10.1/2/4/8 Validation; §11 Phase 3; §13.11; S8, S9, S11, M2–M6.
**ADRs:** none
**Status:** PARKED, outside current owner-authorized Phases 1/2. Keep `status:draft`; do not claim, implement, install its dependencies or mark its assertions satisfied. Promotion requires further owner scope authorization and resolution of C6.
**Branch after promotion:** `feature/engine-copula` from the run; depends on phase 9 and the owner's merged upstream QSE work.
**Recipe after promotion:** fresh subagent → focused TDD → `$code-review` and task commits → run-base PR (`Closes #<phase-issue>`) → `claude` review ×2/configured quota fallback → `conductor merge-gate` → `conductor merge` → `$document-release` → `conductor ledger phase-done`.

- [ ] 10.1 Obtain separately authorized upstream Copula implementation

In the separately authorized QSE change, implement `qse.distributions.joint.copula`: rank/(T+1) pseudo-observations, empirical linear-quantile margins, zero-margin exclusion, R-vine/BIC/family/rotation settings, truncation five (three above 30 funds), fixed seed/single-thread fit, `ShockSource` and serialization. Verify the wheel/license and exact dependency pin; review upstream and obtain owner merge before selected re-sync here. No local edit to copied QSE is allowed.
- [ ] 10.2 Integrate pinned Copula artifacts through the shared engine path

After the upstream pin lands, extend `scripts/sync_qse.py`, `portfoliosight/engine/shape.py`, `portfoliosight/engine/ranges.py`, `portfoliosight/engine/builder.py`, `portfoliosight/jobs/build.py`, `portfoliosight/api/ranges.py` and schema/reader contracts. Persist vine/margins plus full float32 `copula_shocks.npy`, reuse them after restart, retain bounded cache/refusals, and run the same recursion/level/ruin/ENLC paths. Test changed dependence with unchanged margins and stored-shock reproduction; the engine must not be relabeled GARCH.
- [ ] 10.3 Expose real dependence summaries and Copula page behavior

Emit real lower-tail 5% concordance and tree likelihood shares; resolve C6's zero-margin convention and truthful empirical-margin copy. Enable the carried engine on both preset pages, preserve disabled custom-menu reason and interim node figures during a range request. Add source/artifact/numerical/API/browser tests covering A-SE-24–26.
- [ ] 10.4 Validate Copula against GARCH and measure its target workloads

Extend the actual validation report for Copula against GARCH on the same inputs and fixed decision rule, including Bad/ENLC seed checks. Measure the full three-engine KS-001 nightly ≤10 minutes and Copula request ≤10 seconds including first artifact loading; retain 2,000 ×252 paths and disclose named fallbacks. A-SE-27–28 require actual results. Any default change remains a separate owner decision and change.

## Spec coverage and handoff checks

| Spec capability | Implementation/verification destination |
|---|---|
| §1–3 Intent, baseline and QSE boundary | Run prerequisites; phases 1, 5, 6; owner-controlled default rule throughout |
| §4.1–4.3 Shared paths, replay and GARCH | Phases 2–5; independent draw and regression evidence |
| Amended §4.5 Scaling/ruin/attribution | Phase 2 and phase 8; C1/C4 checkpoints |
| §4.4 Copula | Phase 10 PARKED; no current-scope implementation claim |
| §5.1–5.2 ENB and DR² | Phase 7 and paired comparison in phase 9 |
| §5.3–5.5 ENLC, references and recommendation | Phases 8–9; C1/C2/C5; no default switch |
| §6 Simulation/measure controls, URLs and copy | Phases 5 and 8; C3; real share-validator tests |
| §6.1 Holdings wording | Phase 8 rendered-copy matrix and phase 9 screenshots |
| §6.2 Existing tiers, large-menu notice and 100-fund measurement | Preserve tier checks; phases 7 and 9; future truncation in 10 |
| §7 Tensor, versions, artifact lifecycle and HTTP contracts | Phases 2–4, 7–8; future Copula artifacts in 10 |
| §8 Dependencies and data isolation | Phase 1 source closure, phases 3/6 actual flows |
| §9 Performance/fallbacks | Phase 6 real target-host measurements, phase 9 rerun, phase 10 future budgets |
| §10.1/2/5/8 Engine validation/rule | Phase 6; Phase 10 adds Copula only after authorization |
| §10.3/4/7 Measures, seed stability and optimization comparison | Phase 9, with independent fixtures and complete raw evidence |
| §11 Phase 0 and final default decision | Historical prerequisite; owner review after reports; separate future default change |
| §12 Risks; §13 Decisions | Per-task boundaries, explicit checkpoints, runbook and final risk/debt packet |
| Expectations S1–S11, F1–F8, M1–M6 | Assertion artifact traceability plus historical and owner judgments that remain human |

Before handing the current scope to the owner, verify: phase PRs are integrated into the registered run; no product work landed directly in main; all A-SE-01–23 observations are actually met; reports contain data rather than headings; exact full-suite and focused-test evidence is retained; semantic checkpoints are resolved or clearly block acceptance; review debt is visible; rollback is retained; no default changed; A-SE-24–28 and the full-spec gate remain visibly pending until authorized. Do not describe this plan, an inventory, a lint pass or historical branch tests as fresh product verification.

Setup validation command (read-only):

```sh
/home/danie906/.codex/plugins/cache/automateintelligence/conductor/0.10.0/bin/conductor plan-lint docs/plans/2026-10-17-simulation-engines-conductor-plan.md --spec docs/specs/2026-10-14-portfoliosight-simulation-engines-design.md
```

Expected result: exit 0. The leader then obtains independent plan-against-spec review under the documented quota fallback before ledger conversion. Writing this document does not commit/push files, mutate Conductor state, run product tests, create issues or authorize deployment.
