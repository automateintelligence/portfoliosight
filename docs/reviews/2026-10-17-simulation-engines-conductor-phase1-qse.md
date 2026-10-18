# Simulation engines: Conductor phase 1 QSE reconciliation

Date: 2026-10-17 (America/Los_Angeles). Phase: [#112](https://github.com/automateintelligence/portfoliosight/issues/112). PR: [#177](https://github.com/automateintelligence/portfoliosight/pull/177).

This records the selected QSE pull, the first Conductor phase in normative Phase 1. It does not establish completion of the GARCH engine, store, API, page, validation report, or normative Phase 2. The selected pull passes the configured full merge gate and its frozen source-provenance assertion.

## Preserved work and behavior

The retained `feature/qse-sync` checkpoint `a73f7d4` was reconciled by merging the run at `90441f4` into it, producing `646b275`. No retained commits were discarded. The final phase head is `c5c2b48cc0428d6b34670207972b658fa84ec7f8`; product code is unchanged from reviewed `4ecfc52`.

The copied numerical QSE package contains exactly the ten permitted source files at upstream commit `ca8c0445a56712c92dc028e68845b94963fdd590`. Independent frozen hashes and upstream Git blobs match every file. `arch==8.0.0`, namespace package discovery, lock package data, Docker inclusion and tracked agent deny rules remain in place. Vendored files were not reformatted; the upstream trailing blank line in `qse/exceptions.py` is preserved.

The sync guard now checks Git repository identity for mutable targets and all existing ancestors. It protects linked QSE worktrees even when an unrelated repository is nested inside one. It accepts Git's exact ordinary filesystem-boundary nonrepository diagnostic while rejecting malformed output, permissions errors, dubious ownership and unexpected failures. Offline `--check` still works with the private source checkout unavailable. Existing symbolic/hard-link guards remain.

## Focused verification

| Observation | Result |
| --- | --- |
| Sync guard file after linked-worktree correction | 68 passed |
| Strengthened tracked-settings and explicit missing-source cases | 3 passed |
| Mount-boundary regression | 2 expected failures before correction; 37 related cases passed after correction |
| Explicit writable/read-only lock modes at a filesystem boundary | 1 expected failure and 3 passes before correcting the ordinary test expectation; all 78 sync tests passed afterward |
| Dependency and static container-packaging files | 33 passed |
| Four pinned upstream joint/recursion files against this checkout's copied package | 85 passed, no skips |
| Frozen A-SE-01 | 1 passed; baseline intact; all 32 frozen files unchanged |
| Touched Ruff/format/Pyright | Passed; Pyright zero errors/warnings |

Upstream tests came from `git show <pin>:<test-path>` into a temporary directory. They used the phase checkout's Python 3.12.11 and copied package, not the upstream installation. The temporary directory was removed. Upstream HEAD and working-tree status were unchanged; its existing untracked graph query stamp was retained. No QSE lake/storage/provider access, backup writes, or request-budget use occurred.

The full project suite runs only inside `conductor merge` against the prospective merge ref. Two verification-command setup failures occurred before pytest: incompatible Pyright flags, then ancestor `/tmp/pyrightconfig.json` discovery. The corrected command explicitly selects the prospective checkout's `pyproject.toml` and the phase virtual environment. The first actual suite attempt exceeded the 1,800-second verification bound after the Docker image build and at 51% progress; this was a failed gate, not passing test evidence. That failure justified a retry with a 5,400-second bound and the same checks. No product tests were skipped or weakened.

The completed retry reported 971 passed, one failed, five preexisting live skips and 99.14% coverage in 1,424.21 seconds. The failed ordinary test expected a writable lock to keep its permissions, although `--check` correctly makes the lock read-only. Copying the phase checkout's already-read-only lock had masked that expectation error in the focused run. Commit `c5c2b48` makes both starting modes explicit and checks read-only lock permissions while retaining complete byte, file-membership, unrelated-mode and unchanged-source snapshots. No product code or frozen assertion changed. A fresh independent reviewer approved the committed correction; the final configured gate then passed: 974 tests, five existing live skips, 99.14% coverage, 1,100.90 seconds.

## Independent review and documentation audit

Claude's weekly quota is exhausted per the owner. Fresh independent Codex `gpt-6-astra`/high code/spec/security and architecture reviewers supplied the documented fallback. The configured marker is `Claude review`, honestly labeled UNAVAILABLE (weekly usage limit); the author filter is unset and the minimum remains two. Architecture is CLEAR for the product state; final code review APPROVE at `c5c2b48` follows the targeted lock-mode test correction. [Debt #178](https://github.com/automateintelligence/portfoliosight/issues/178) preserves the lost opposite-host independence for optional owner re-review.

The documentation audit covers the changed sync/package surface: `qse/README.md` provides reference, the sync/check how-to, source-edit policy and three read-only layers. The normative spec explains the numerical-only dependency boundary. Main README setup/test commands remain applicable. No application version or deployment change belongs to this phase. Runtime Docker and full-suite results are recorded only from the merge gate.

## Integration and remaining scope

PR #177 merged through `conductor merge` as `3b612fd1a1e6634d6796af57bdd48e0e331c4666`. Its Git tree exactly matches tested prospective ref `c3bc690`. The owner’s subsequent documentation commits were merged into the run as `4b77b71`.

The fresh full frozen run on that integration checkout reported **1/28 green**: A-SE-01 passed in 2.842 seconds; A-SE-02–28 remain red. The gate is not done. No frozen assertion, manifest, baseline or source artifact changed. The integration owns its Python environment and editable product install; actual PortfolioSight and QSE module origins were verified under that checkout, with `arch==8.0.0`.

`conductor ledger phase-done 112` verified the mapped assertion, closed #112 and its task issues #113–115, and ticked all three QSE plan items. The remaining phases were not marked complete.

The next owner-confirmed milestone is deployable normative Phase 1, Conductor phases 1–6 / A-SE-01–16, with validation and target-host evidence and a release review packet. Normative Phase 2 is subsequent work and is not a deployment prerequisite.

A-SE-02 remains owned by phase 6 because it also requires the real API and validation script. Copula stays parked. Replay and ENB remain the defaults; no production publication or rollout occurred. Worktrees and branches remain until their work is in main, per the owner's cleanup rule.
