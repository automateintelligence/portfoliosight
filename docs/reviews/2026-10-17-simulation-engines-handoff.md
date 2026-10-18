# Simulation engines: resume prompt

This records the October 17, 2026 (America/Los_Angeles) wrap-up and subsequent authorized resume updates, including the A-SE-04 diagnosis and C3 decision. No production deployment occurred.

Copy the following into the next session:

```text
$conductor:start --auto-assert docs/specs/2026-10-14-portfoliosight-simulation-engines-design.md

Read docs/reviews/2026-10-17-simulation-engines-handoff.md first. Resume phase #116 from the preserved work; reconcile before implementing anything. Make deployable normative spec Phase 1 the next milestone, before normative Phase 2. Preserve all existing branches, worktrees, commits and frozen assertions.

Read ~/.codex/AGENTS.md for the Conductor model/effort mapping and ~/.claude/CLAUDE.md for working rules. Claude's weekly quota is exhausted; use the documented independent review fallback honestly. Several Codex agents also reached a usage limit at the last stop, so check current capacity before dispatching. Do not count the interrupted code review as approval.

Use the documented single-thread numerical launch environment for A-SE-04 and finish task 2.5's supported-worker determinism and actual 30-fund replay+GARCH memory evidence. Complete independent final reviews, the configured merge gate and mechanical phase closure before advancing. Apply the owner's 2026-10-17 C3 choice: fetch an uncached custom mix's exact selected-engine result while showing the available estimate as estimated/pending; cached results switch immediately without a request. This decision does not authorize deployment or a standing full-access driver.
```

## Authoritative run and checkpoints

- Repository: `/home/danie906/programming/portfoliosight`; remote **`github`**.
- Run key: `2026-10-14-portfoliosight-simulation-engines-design-99dcbc03`.
- Integration branch: `conductor/run-2026-10-14-portfoliosight-simulation-engines-design-99dcbc03`.
- Integration checkout: `.worktrees/run-2026-10-14-portfoliosight-simulation-engines-design-99dcbc03`.
- Active implementation: phase **#116**, `feature/engine-garch`, `.worktrees/engine-garch`.
- Numerical/test checkpoint **`5bee868bb831730e2795e578fea11ca3e2f6dfbc`** is committed, clean and pushed. This handoff's documentation may add a later merge commit; inspect current Git state rather than assuming HEAD still equals that checkpoint.
- Integration product baseline before this handoff's documentation: **`6505571`**.
- Plan: `docs/plans/2026-10-17-simulation-engines-conductor-plan.md`.
- Local resume state: `.conductor/runs/<run-key>/{run.json,goal.md,handoff.md,monitor-progress.json}`.
- Two run records coexist. Always select this run explicitly. The main checkout's flat `.conductor/goal.md` and `run_branch` belong to the older demo; leave them alone.

Normative Phase 1 is Conductor phases **1–6**, not just QSE phase #112. Its remaining sequence is #116 engine, #122 store/build/nightly, #127 range API, #133 UI and #139 validation/target-host measurements. Normative Phase 2 is subsequent authorized scope (#146/#154/#163). Copula #170 stays DRAFT/PARKED; do not promote it or call the full spec complete.

## Completed QSE subphase

- PR [#177](https://github.com/automateintelligence/portfoliosight/pull/177) merged through `conductor merge` as `3b612fd`; its tree matched tested prospective ref `c3bc690`.
- Final gate: **974 passed, five existing live skips, 99.14% coverage**, 1,100.90 seconds; Ruff/format/Pyright clean.
- Fresh frozen run on integration `4b77b71`: **A-SE-01 green; 27 later IDs red**. That result was not full-spec completion.
- `ledger phase-done 112` closed #112 and #113–115 and ticked its three plan items. Report and plan committed on main as `71c0fa3`, then merged into the run.
- Evidence: `docs/reviews/2026-10-17-simulation-engines-conductor-phase1-qse.md`. Archived local frozen result: `.conductor/runs/<run-key>/gate-post-qse-results.json`.
- Same-host fallback debt #175 (setup) and #178 (QSE) remains open. No Claude review was claimed.

## Phase #116: completed evidence and remaining checks

The existing numerical implementation was retained. New commits add meaningful ordinary regression tests; production math was unchanged at wrap-up.

| Task | Evidence |
| --- | --- |
| 2.1 Shape/history/splice | Retained files unchanged; 19 tests passed in 6.77 s; scoped static checks clean; independent spec PASS and quality APPROVE |
| 2.2 Two-space scaling | `a09a042`: full 2,000×252 independent daily-path oracle and uneven chunks; 24 range tests passed in 6.61 s; frozen A-SE-08 passed; both reviews passed |
| 2.3 Constants/ruin | `5bee868`: exact constant-fund mixes, stochastic funds with singular zero chart mix variance but positive transformed spread, exact/below−100% and repeated ruin, later gains, replay rejection, builder allocation; 82 range/builder tests passed, then the added stochastic constant-mix test passed separately; A-SE-09 and scoped static checks passed; both reviews passed |
| 2.4 Version/provenance/browser | Retained engine 0.3.0, schema 3, hash schema 2, replay aliases and schema-2 rollback reader; 20 CLI/schema tests and 12 browser tests passed; scoped checks and both reviews passed; pinned CLI fixture reproduced without changes |
| 2.5 Workers/memory | **Incomplete.** No completed worker-equality or full replay+GARCH 30-fund memory receipt was produced before quota interruption |

**Historical A-SE-04 failure, preserved.** The wrap-up probe reported A-SE-06 PASS and A-SE-04 FAIL in 12.87 seconds. In `test_a_se_04_shape_history.py:184`, `artifact.pool` differed from the independently re-fitted QSE pool: 4,959/7,446 elements, maximum absolute difference **0.00130993**. Captured fit inputs, digest and full draw dimensions passed before that comparison.

**Resolved by controlled diagnosis, 2026-10-17.** On engine checkout `d946e58`, its own `.venv` and product/module origins were verified. The builder fits under one BLAS thread; its context ends before the frozen oracle refits under the host's ambient 12 threads. Alternating fits of the identical panel at 1/12/1/12 threads reproduced the exact 4,959 mismatches and maximum difference `0.0013099314907845105`; repeats within each setting were byte-identical. From the same fit, pool versus independent transformation differed by at most `4.45e-15`. The ambient focused assertion failed in 19.58 s; adding only `OPENBLAS_NUM_THREADS=1` at process startup passed the entire unchanged A-SE-04 in **30.40 s**. Use that numerical launch environment to match spec §4.1. No product, frozen assertion, tolerance, vendor or lock changes were made. Evidence: engine checkout `.conductor/runs/<run-key>/diagnostics/shape04-20261017/README.md` and accompanying logs/JSON. The ambient command remains red; this proves focused A-SE-04, not completion of phase #116. Historical `gate-oracle-probe*.log` files include older wrong-environment probes and are not this controlled evidence.

The early independent whole-phase architecture review at `5bee868` found no actionable P0/P1/P2 code defect but returned **WATCH**, pending final validation/head. It is not final clearance. The independent code/spec/security lane stopped on usage limit and supplied **no approval**. Obtain the required final-state reviews after completing task 2.5.

## Resume order and verification rules

1. Inspect current Git state, phase #116's existing assignment/lease, quota availability and run ownership. Preserve/reconcile the existing claim instead of blindly claiming a second phase. Reacquire ownership through Conductor; never delete or force-clear a live owner.
2. Reconcile current run documentation into the preserved engine branch if needed. Confirm its own interpreter and actual module origins before numerical checks.
3. Launch numerical validation with `OPENBLAS_NUM_THREADS=1`, including the unchanged A-SE-04. Finish task 2.5: actual supported-worker canonical equality and traced/RSS memory for **30 funds, replay+GARCH, full 2,000×252 paths**. Replay-only legacy memory checks and raw-panel size are insufficient.
4. Reuse unchanged author evidence. Run focused tests for changed behavior and scoped lint/type checks. **Do not run the full project or web suite in task workers.** The full suite runs through `conductor merge` against the prospective merge.
5. Open one phase PR into the exact registered run branch, `Closes #116`. Read the actual review marker/author/minimum configuration. Previously it was `Claude review`, author unset, minimum two; recheck rather than assume. Label quota fallback honestly, retain review debt, and never post an unavailable review as approval.
6. Merge only with `conductor merge`; never raw `gh pr merge`. After integration, run the fresh frozen gate from the integration checkout and use `ledger phase-done` to close mapped work and tick the plan. Do not mark tasks done manually. Final default-branch integration belongs to the owner.

All 32 frozen files and the assertion source artifact remain unchanged. The installed legacy gate lacks `--run` and uses `CONDUCTOR_HOME=<checkout>` plus `CONDUCTOR_GATE_SLUG=<run-key>`. The reviewed source CLI below supports explicit selection: `assert run --run 2026-10-14-portfoliosight-simulation-engines-design-99dcbc03 --level spec`, with `CONDUCTOR_HOME` set to the checkout under test. With two active records its no-key invocation was verified to fail with exit 6 before writing; environment-only selection is insufficient there. Never handwrite `results.json` or export a stale `CONDUCTOR_RUN_BRANCH`.

## Tooling and environment

- Installed CLI: `/home/danie906/.codex/plugins/cache/automateintelligence/conductor/0.10.0/bin/conductor`.
- Reviewed source CLI for owned registration: `/home/danie906/programming/conductor/.worktrees/run-keyed-driver/bin/conductor`, clean `fix/run-keyed-driver` at **`37aa2e2`**. It is unpublished and uninstalled. Host preflight and guarded `phase-clear`, `integration-register`, `phase-register` succeeded from the integration checkout; main's `main` branch was correctly refused for these operations. Cache files were not edited.
- The source CLI's `resume` refuses a live owner by design. In-session owned `autodev` works; continue through the current owner rather than spawning a second owner or forcing a transition.
- Private compatible GitHub CLI: `/home/danie906/.local/lib/portfoliosight-conductor-tools/gh-2.102.0/bin/gh`. System `gh` 2.4.0 lacks the merge gate's head-match functionality; prefix the private bin for Conductor merge operations.
- Existing configured Node runtime: `/home/danie906/.nvm/versions/node/v20.19.5/bin`. The default noninteractive PATH lacks `node`/`npm`; prefix that directory. Node 20.19.5/npm 11.16.0 satisfy installed project engine requirements. Playwright 1.64.0 and Chromium 1248 are present; full local browser execution still belongs to the merge gate.
- Engine and integration checkouts own Python 3.12.11 environments with `arch==8.0.0`. Integration dependencies, editable product and module origins were verified. Do not borrow a sibling editable product install; main's older environment lacks arch.
- Prepared next merge verifier: `/tmp/portfoliosight-phase116-verify.py`, also archived in the local run directory as `phase116-merge-verify.py`. It has **not been executed as this phase's gate**. It includes Python provenance/static checks, fresh prospective-checkout web dependencies/lint/typecheck/tests/build/local desktop+phone e2e, then Python coverage. Local preview/mock use loopback ports, not production smoke.
- No simulation cron or standing unattended driver was installed. Tooling issue #176 remains open. A future full-access standing driver still needs generated/runtime verification and the explicit owner acknowledgment required by `conductor:start`; no such consent was given here.

## Owner decisions

- C4 resolved: with no available peer residual, retain and disclose an ordinary splice outlier. For an exactly constant simulated portfolio, Bad = Typical = Good at its compounded return. The approximate Typical bound applies only to nondegenerate cases.
- Four diversification grades are separate from the three return estimates.
- C3 resolved, owner 2026-10-17: **"Fetch the exact result while showing the available estimate (recommended)."** Precomputed or already-cached results switch immediately without a request. An uncached custom mix fetches the selected engine's exact result while retaining the available estimate visibly as estimated/pending; deduplicate matching requests and reject replies for an earlier selection. Spec §6 and plan checkpoint C3 record the decision. No deployment or standing-driver authorization follows.
- Keep replay and ENB defaults. Do not publish a generation, deploy, change defaults, write the backup mirror or QSE lake/lock, or spend QSE's provider budget.

## Later Phase 1 handoffs

- Preserve `feature/engine-store` / `.worktrees/engine-store` at `39b5fda` until #116 closes. Merge the then-current run into it before work. Its old simple-return artifact format lacks the new returns-space marker; preserve the newer log-space parser guard and test rejection of stale/missing/`simple` markers plus canonical cold/reused equality. `nu` null/NaN is an intentional fallback representation; blanket finiteness rejection would be wrong.
- API #127: current range model construction converts float32 input to float64. Implement the two-panel float32 cache without retaining a full float64 copy per lookback.
- Preserve `feature/web-engine` at `fea06bc` and `exp/garch-absorb`; no unmerged cleanup.
- Validation #139 still needs the real backtest program, raw receipts, reports, seed stability and isolated four-CPU KS-001 measurements. The read-only mirror exists at `/mnt/d/portfoliosight-data`; never write it. Example Portfolio has checked-in entered allocations; TSP has none and must be disclosed unavailable. A read-only SSH/Docker availability check was successful, but it is not performance proof and must be rechecked before future target-host work.
