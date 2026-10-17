# Simulation engines: Conductor resume reconciliation

Date: 2026-10-17 (America/Los_Angeles).
Run: `2026-10-14-portfoliosight-simulation-engines-design-99dcbc03`.
Normative spec: `docs/specs/2026-10-14-portfoliosight-simulation-engines-design.md`.

## Scope and evidence

The owner requested normative spec Phases 1 and 2. The existing
`docs/plans/2026-10-16-simulation-engines-phase1-plan.md` divides normative Phase 1
into seven implementation/report stages. Its phase numbers do not name the spec's
Phase 2 diversification measures. Copula (normative Phase 3) remains outside the
current execution scope; changing either default remains an owner decision.

| Work | Preserved branch / checkpoint | Reconciliation |
| --- | --- | --- |
| QSE selected pull | `feature/qse-sync`, `a73f7d4` | Existing implementation and guard tests; not merged into main |
| GARCH engine | `feature/engine-garch`, `0c82e57` | Existing implementation; uncommitted artifact-space checks preserved in a WIP commit |
| Store and nightly | `feature/engine-store`, `39b5fda` | Descends from earlier engine checkpoint `7ab47c6`; needs later engine changes |
| Engine UI | `feature/web-engine`, `fea06bc` | Includes store work; uncommitted URL/share gate edits preserved in a WIP commit; needs later engine changes |
| Ruin experiment | `exp/garch-absorb` | Retained separately; not a substitute for the integrated engine/schema work |
| Range API / validation report | No matching branch found | Pending; do not mark normative Phase 1 complete |
| DR² / ENLC measures | No implementation found | Normative Phase 2 remains pending |

The existing branch-local spec corrections at `a77dbf7` were cherry-picked as the
documentation-only main commit `20b292e`. They describe log-space fitting,
lognormal per-fund scaling, simple-space mix scaling, disclosed absorption of ruined
simulated paths, and the corresponding loss-attribution centering. Original
history is retained. Downstream branches must not overwrite this newer spec with
their older versions.

The four existing feature worktrees were clean after preservation. Their branches
were pushed to the `github` remote. No phase PRs existed at reconciliation. The
engine gate-change note records an earlier A-PS-24 pass; that historical statement
is not a fresh full-suite or phase-completion result. No product test suite was run
as part of this inventory.

## Setup and operational limits

Preflight passed for host `codex` (10/10 conducted skills). The registered run has
an isolated integration branch and worktree under `.worktrees/`; no feature code
was merged as part of this reconciliation. Main has no server-side branch
protection (GitHub API returned 404); Conductor merge rules remain necessary.

The installed CLI is partly migrated to per-run state. `run show --run` and
`gate-dir --run` resolve this registered run's hashed names, while legacy
`run-branch name <spec>` returns the older unhashed spelling. Setup uses the
registered names rather than creating a competing run.

The generated Tier-B driver calls `conductor run owner-busy` without `--run`.
A direct read-only probe from the new integration worktree returned exit 2:
two active runs are registered (the older demo and this simulation run).
Rendering the driver confirmed it carries no explicit simulation run key.
No unattended driver was installed: it cannot safely disambiguate the two runs.
The other run's records, schedules, goal and branches were left intact.

Claude weekly quota is exhausted according to the owner. Independent reviews
must use the documented, honestly labeled same-host fallback, preserving the
configured review marker/count/provenance and recording review debt. Model and
effort selection follows the Conductor table in `~/.codex/AGENTS.md`.
