# Simulation engine reconciliation — Conductor phase #116

Completed engine subphase #116 on 2026-10-18. The full prospective-merge gate passed, PR #179 merged into the run branch, all four mapped assertions passed on the integrated code, and mechanical phase closure closed #116 and task issues #117–121 and ticked all five plan tasks. Normative spec Phase 1 remains incomplete.

This is the engine subphase of normative spec Phase 1. It retains the existing implementation on `feature/engine-garch` and reconciles it against the amended log/simple-return scaling contract. Store, API, Simulation controls and target-host validation remain subsequent subphases. The next milestone remains deployable normative Phase 1; notify the owner before normative Phase 2 begins.

## Changes and review scope

The final reviewed head is `0ccccd89a9c52b5ec0f76fbb42e41da2f15b85e6`, compared with integrated QSE baseline `6505571`. The retained implementation fits the shared full-history log-return panel, simulates joint residual rows, applies fund and portfolio moment matching, and absorbs ruined simulated paths at exactly −100%. Tensors retain replay defaults and aliases, engine provenance and schema 3; the browser continues to read schema-2 rollback tensors.

The new reconciliation commits add regression coverage: `a09a042` independently computes asymmetric daily-path scaling; `5bee868` covers constants, singular zero-variance portfolios and ruin; `d30095e` verifies fresh-fit worker equality and full-build memory. Production mathematics was preserved during this reconciliation. This run’s frozen checks and trusted vendor files were unchanged.

## Verified focused evidence

| Work | Recorded evidence |
| --- | --- |
| Shape/history/splice | 19 tests passed; scoped static checks and task reviews passed |
| Scaling | 24 range tests and A-SE-08 passed; independent full daily-path oracle |
| Constants/ruin | 82 range/builder tests, one later stochastic constant-mix case and A-SE-09 passed |
| Version/provenance/compatibility | 20 CLI/schema tests and 12 browser parser tests passed; fixture reproduced through its pinned CLI invocation |
| Fresh worker builds and memory | Six resource tests passed in 298.35s; Ruff/format and Pyright passed |

The resource cases independently refit the 23-fund fixture for workers 1, 2, 3, 4 and 8. Canonical tensor JSON (excluding only build telemetry), artifact JSON, residual pool and full simulated panel match exactly. Canonical SHA-256 is `460c05a89dc9a574704731d787515da7d8a7f9491c2872eda605ed08f5596929`; committed resource-test SHA-256 is `80908ac0e0a4dfafcd20e99fda041c9b0a94775988c8ee001057a40cc5fed638`.

A fresh-process, cold-cache 30-fund replay+GARCH build used full 2,000×252 paths, a 48×32 grid, 48×14 ladder levels and an entered mix: 673 carried mixes. Traced peak was 213.37 MiB. Linux resident baseline was 220.94 MiB, peak 454.98 MiB and rise 234.04 MiB. The checks enforce the existing 400 MiB incremental allowance and 1,536 MiB container envelope. One worker keeps the whole measured build in one process. These measurements do not certify concurrent-container memory or KS-001 timing.

## A-SE-04 numerical context

The initial independent pool comparison failed because the builder limited BLAS to one thread while the reference fit used the host’s ambient twelve. Alternating fits at 1/12/1/12 threads produced byte-identical repeats within each setting and exactly reproduced the cross-setting difference: 4,959 values, maximum absolute difference 0.0013099314907845105. The residual-pool formula agreed with its independent oracle for the same fit to about 1e-15.

Starting validation with `OPENBLAS_NUM_THREADS=1`, matching spec §4.1, made the unchanged A-SE-04 pass in 30.40s. The builder’s existing limit remains. No tolerance, frozen observation, vendor or product change was used to resolve this comparison. This does not establish thread-independent QSE fitting.

## Merge gate and review provenance

PR #179 targets the exact registered run branch. Independent isolated Codex reviewers using the owner’s `gpt-6-astra`/high mapping returned architecture CLEAR and code/spec/security APPROVE at the final head. Claude weekly quota was exhausted per owner; comments disclose the same-host fallback and debt #180 retains the loss of opposite-host independence. No Claude review was claimed.

The first full merge attempt passed static checks, 335 web tests, the production build and 83 local desktop/phone checks. A read-only build-history diagnostic issued by the orchestrator triggered a Docker 28.4.0 BuildKit daemon panic during the image fixture. The invalid attempt was interrupted cleanly after its actual five setup errors, preserving its traceback and 579 completed passes/five existing live skips. The existing local daemon was restored without a package/configuration/data-root change. The complete unchanged gate was then restarted; its Docker stage has passed after an actual image build and runs. A later complete run exposed one unstable synthetic IGARCH draw: under one BLAS thread its optimizer failed convergence, correctly producing `fit_failed` instead of the test’s intended `non_stationary`. Commit `0ccccd8` replaces only the draw seed and explanation; model parameters and strict assertions remain. The replacement converges in both observed BLAS contexts; the failing case and all 19 focused shape tests passed, and both reviewers cleared the final commit. The unchanged complete merge gate then passed: 1,038 Python tests, five existing live skips, 99.22% coverage (all engine modules 100% line coverage), Ruff/format/Pyright, 335 web tests, production build and 83 local browser checks. PR #179 merged as `4b776f9bda24603c6c4bb21dafc5acac60931e94`; its tree exactly matches tested prospective ref `155ae47`. Python suite duration was 999.99 seconds.

## Release inputs and remaining work

The actual preserved rollback tag is `dashboard-bootstrap-2026-10-15`, resolving locally and remotely to `4a17431c6a9a8c466057af3e741d1bef2fc8963a`. The runbook records its image, Worker version, generation and rollback commands. A read-only R2 refresh at 2026-10-18T07:10:25Z confirmed `meta/pinned.json` retains `2026-10-14-0.2.0`; it made no production writes.

Inherited web toolchain advisories are tracked in #181: nine affected development package nodes (one low, two moderate, four high, two critical), with unchanged package/lock files across the baseline, phase and prospective merge. The bounded review did not establish an application exploit or approve unresolved findings. The release packet must carry the dependency debt for owner disposition; no automatic package updates were made.

Next work is #122 store/build/nightly, #127 range API, #133 Simulation UI and #139 validation/isolated KS-001 measurements. C3 is resolved: an uncached custom mix may fetch the selected engine’s exact result while showing a visibly estimated/pending result. Cached/precomputed results remain request-free. Replay and ENB remain defaults. No production deployment, generation publication or standing unattended driver was installed by this work.

## Integrated acceptance and closure

After integrating the owner’s latest documentation, run head `385a743` produced a fresh acceptance result: A-SE-01/04/06/08/09 passed; the remaining 23 IDs are red. Phase #116 maps exactly to A-SE-04/06/08/09, all green. `conductor ledger phase-done 116` returned success, closed task issues #117–121 and checked tasks 2.1–2.5; the phase is CLOSED/status:done with no assignee or lease.

A-SE-15 reached its frozen 900-second limit while independently recalculating seed statistics. It has no passing numerical verdict and remains validation work for #139. Its observation, claim and limit were not changed. Later API/UI/backtest/target-host and diversification/Copula checks also remain outstanding; 5/28 is not full-spec completion. Full raw results and merge/closure receipts are retained under the explicit run directory.

Owner direction of 2026-10-18 is a hard boundary: finish deployable normative Phase 1, notify the owner, then pause before normative Phase 2. Issues #146/#154/#163 are blocked with owner-pause markers and require an explicit resume instruction. The original objective remains intact; no Phase 2 implementation or claim is authorized while paused.
