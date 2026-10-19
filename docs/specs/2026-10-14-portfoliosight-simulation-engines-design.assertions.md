# Executable assertions — PortfolioSight simulation engines

Source spec: `docs/specs/2026-10-14-portfoliosight-simulation-engines-design.md`, including
the 2026-10-17 amendments committed as `a77dbf7aa0f56986681a02f58db66b25aa2eed0f` on
`feature/engine-garch` and brought to `main` by `20b292e`. Those amendments specify log-return
fitting, log-space fund scaling followed by simple-space mix scaling, absorbed simulated ruin,
and the matching loss-attribution formula. The owner's numbered Expectations are unchanged.

Prepared with `spec-craft:expectations` and `spec-craft:executable-assertions` 0.3.0 on 2026-10-17.
Amended on 2026-10-18 (owner timezone) for the owner's preference contract, slider semantics,
measures and sequencing (spec §3 item 7, §5.5, §6, §7, §10 item 6, §13 items 19–23): A-SE-18
and A-SE-20 are rewritten to the sacrifice-ladder semantics, A-SE-22 and A-SE-23 are marked
"scope reconciled after C8", and A-SE-29 through A-SE-32 are added. The record of every change,
with before/after/property/reason, is `docs/reviews/2026-10-18-gate-change-objective-and-slider.md`.
The frozen tests under `assertions/` are not changed by this file; the run leader re-freezes them
through the installed Conductor workflow. A-SE-29 and A-SE-32 tests are linted and frozen into
the run gate before `ledger phase-done <6b-issue>`; A-SE-18, A-SE-20, A-SE-22, A-SE-23, A-SE-30
and A-SE-31 re-freeze after C8 is recorded and before phases 7–9 are accepted.
These are assertion **specifications**, not test code or permission to change either default.
Stable `A-SE-*` IDs identify the future machine checks; no ID is renumbered.

## 0. Scope and handoff

Each assertion belongs to the normative phase in §11, not to a task number in a later plan.
Phases 1 and 2 are the current execution scope. Phase 3 remains part of the full-spec done
floor and must stay visibly pending until separately executed; it must not be marked satisfied
by a disabled Copula option, a mock copula, or omission from the gate.

| Normative phase | Assertion IDs | Boundary |
|---|---|---|
| Phase 1 — Volatility model | A-SE-01 through A-SE-16, A-SE-32 | Replay/GARCH, provenance, artifacts, API, page, validation, measured budgets; the rolling-origin harness's leakage check (A-SE-32, added 2026-10-18; the harness is first in the owner's order) |
| Phase 2 — Diversification measures and the preference contract | A-SE-17 through A-SE-23, A-SE-29 through A-SE-31 | DR², the two-stage contract and sacrifice ladders, ENLC, `ES_2.5`, presentation, comparison and stability |
| Phase 3 — Copula, future scope | A-SE-24 through A-SE-28 | Actual fitted dependence, artifacts, integration, validation and measured budgets |

IDs 24–28 were assigned before 29–32 and keep their Phase 3 place; the new IDs follow the
next-free rule and are listed under the phase they check, not in numerical order.

Phase 0 is a prerequisite, not reassigned to Phase 1: retain evidence for S1/M1 from the
annotated rollback tag, remote tag, runbook and pinned generation before engine work. A test
of today's files cannot establish that these existed before the first engine change. The
leader must reconcile that historical evidence; these assertions do not waive the ordering.
Existing demo assertions remain applicable except where the successor spec explicitly changes
their behavior; update those contracts with their own provenance, rather than hiding failures.

| Runs | Meaning |
|---|---|
| `unit` | Deterministic Python or TypeScript fixtures, with independent numerical expectations |
| `api` | The public FastAPI/Worker request path with a temporary store and real engine dispatch |
| `ui` | Browser tests through the application, using actual builder tensors or deliberately distinct fixture values |
| `static` | Tracked source/package/lock inspection, including negative mutation checks where stated |
| `validation` | The real validation script against the specified local backup; no provider calls |
| `ks001` | Measurements on the specified KS-001 container, not a laptop timing proxy |

One runnable check per ID may use a fixture matrix. A downstream runner must execute the
observations, not merely check that a report, symbol, test file or tensor field exists. Unit
oracles must not call the production calculation they are checking. Production indirection
(builder, engine dispatcher, artifact loader, HTTP endpoint, browser) is explicit where it
matters. A missing required dataset or host is an unmet prerequisite, never a passing skip.
Numeric comparisons use the spec's tolerances where given; otherwise document ordinary
floating-point error tolerances independently of the observed implementation. Build canonical
JSON equality is exact. API float32 differences must be distinguished from build float64
equality, not used to relax the build checks.

### Expectations assessment

The definition-of-done candidates below were assessed before authoring assertions:

- **[COVERED]** A usable rollback precedes engine work: S1, M1, §11 Phase 0.
- **[COVERED]** Existing figures and owner control of defaults: S2, F1, M3.
- **[COVERED]** Every range follows selection, without a rebuild, and links preserve it: S3, S10, F4.
- **[COVERED]** The lookback controls level, shared long history controls shape: S4, F6.
- **[COVERED]** Weak/failed fits are named constant-volatility fallbacks: S5, M5.
- **[COVERED]** Single-fund diversification and the applicable holdings bound: S6, F2, §5.2–§5.3.
- **[COVERED]** Loss sources and shared draws: S7, F7.
- **[COVERED]** Upstream provenance and no new QSE data/storage/budget access: S9, M2, M4.
- **[COVERED]** Splice contamination is rejected: F5.
- **[COVERED]** Reproducible evidence supports an unchanged decision rule: S8, F8, M3.
- **[COVERED]** Costs remain bounded without fewer paths: S11, M6.
- **[COVERED]** Technical terms and raw scores stay within the specified presentation boundaries: F3, §6.1.

No new owner expectation was added. Deliberately did not add: duplicate determinism or
artifact-integrity expectations (verification of the existing commitments); an unconditional
DR² holdings bound (§5.2 expressly conditions it on non-negative correlations); a requirement
that a new engine wins (the report may honestly favor replay); a new 100-fund time limit
(the spec calls for a measurement, not a numerical limit); subjective visual-quality proxies.
Unresolved interpretations are listed in §2 rather than becoming invented requirements.

## 1. Load-bearing expectations selected

Each line gives the assertion, traceability, and the silent failure it prevents.

- **A-SE-01 — QSE source provenance.** S9/M2: local changes could silently alter the financial model.
- **A-SE-02 — Dependency and data isolation.** S9/M4: engine work must not reach QSE storage or spend its request budget.
- **A-SE-03 — Replay and defaults remain the baseline.** S2/F1/M3: new code must not silently change the owner's existing figures.
- **A-SE-04 — Shape history and residual-pool eligibility.** S4/F6: a lookback-specific or padded pool would misrepresent dependence.
- **A-SE-05 — Named constant-volatility fallbacks.** S5/M5: a failed fit must not masquerade as a fitted result.
- **A-SE-06 — Splice contamination rejection.** F5/M5: a fabricated crash would contaminate every mix.
- **A-SE-07 — Shared complete draws and long-run start.** F6/F7/M6: independent mix draws or fewer paths invalidate comparisons.
- **A-SE-08 — Two-space level scaling.** S4/F6: plausible percentiles can use the wrong risk or return.
- **A-SE-09 — Explicit simulated-ruin policy.** S4/M5 and amended §4.5: invalid historical data and simulated ruin must not be silently repaired or confused.
- **A-SE-10 — Deterministic tensor and range contract.** S3/S4/F1: mismatched blocks can present incompatible figures as one calculation.
- **A-SE-11 — API engine selection and artifact refusals.** S3/S10/F4: the request must not return a stale or substituted engine.
- **A-SE-12 — Atomic page engine selection.** S3/F3/F4: one stale card, tag or risk readout makes the page disagree with itself.
- **A-SE-13 — Engine URL and share round trip.** S10: a link must not silently select a different simulation.
- **A-SE-14 — Phase 1 validation evidence.** S8/F8/M3: a polished report must derive its conclusions from the prescribed experiment.
- **A-SE-15 — Bad-year seed stability.** S4/S8/F7: reported differences must not be unexamined simulation noise.
- **A-SE-16 — Phase 1 measured budgets.** S11/M6: performance success must use the full calculation on the target host.
- **A-SE-17 — DR² identities and qualified bound.** S6/F2: a correlated fund menu must not turn one holding into many risks.
- **A-SE-18 — Sacrifice-ladder semantics (rewritten 2026-10-18).** S6/S13/S14/F2/F10: a ladder that holds risk exactly, breaks a guard, or lands anywhere but `w_R` by default would reintroduce the TSP 5y default of 2026-10-18.
- **A-SE-19 — ENLC attribution and loser-only entropy.** S6/S7/F7/M5: hedges, zero holdings and undefined loss shares must not produce invented diversification.
- **A-SE-20 — Measure and engine selection and shared state (rewritten 2026-10-18).** S7/S10/S12/F4/F9: the selected word, map, holdings and loss details must obey their distinct stated meanings, and selecting a measure or engine must select its actual holdings.
- **A-SE-21 — Scores are not presented as holdings.** F3/S6/S7 and §6.1: a mathematically correct number can still make the forbidden claim to visitors.
- **A-SE-22 — Measures comparison evidence (scope reconciled after C8).** S8/F8/M3: a change of optimized measure needs comparable measured evidence.
- **A-SE-23 — ENLC seed stability (scope reconciled after C8).** S7/F7: unstable tail shares must not be accepted by dropping difficult seeds.
- **A-SE-29 — Preference-contract oracle (added 2026-10-18).** S13/F10 and §5.5/§10.6: a selector that picks A over B, penalizes an improvement, admits a double deterioration, or lets the measure reach into Stage A would silently replace the owner's preference.
- **A-SE-30 — Default-landing regression (added 2026-10-18).** S14/F11 and §6/§10.6: a default that is not `w_R` can hand the visitor a mix worse on both Bad and Typical than `w_R`. F11's "worse than another mix on screen" leg (the frontier mix) is recorded as a C8 finding, not asserted.
- **A-SE-31 — `ES_2.5` identity and single-fund checks (added 2026-10-18).** §3.7 D5, §4.1, §10.5/6: a tail average that is wrong, or that quietly steers the selection, would mislabel the one new figure.
- **A-SE-32 — Harness leakage metamorphism (added 2026-10-18).** S8/F8 and §10.1: prices after an origin must not change that origin's selection or prediction, or the experiment's evidence is not out-of-sample.
- **A-SE-24 — Real copula shocks through the upstream seam.** S4/S9/M2: a relabelled bootstrap or changed margins do not implement the chosen dependence model.
- **A-SE-25 — Copula artifact replay and refusal.** S3/S10/F7: the API must reproduce the build's dependence draw.
- **A-SE-26 — Copula reaches the preset page.** S2/S3/F4: a library implementation alone does not expose the feature.
- **A-SE-27 — Copula comparison evidence.** S8/F8/M3: the future report must compare copula with GARCH under the same rule.
- **A-SE-28 — Copula measured budgets.** S11/M6: the future full nightly and request path must meet their own budgets.

## 2. Deliberately not encoded and unresolved interpretations

**Human and historical judgments:** the owner's reading of the validation report, decision to
switch defaults, interpretation of scientific adequacy, visual comparison of maps, whether the
page is personally convincing, and historical execution order (S1/S2/S5/S8, F8, M1/M3) are not
certified by a machine checkbox. Mechanical default preservation, quantitative evidence,
presentation boundaries and rollback records are separately checkable. No assertion authorizes
a default switch, including a report that meets the proposed numerical rule.

**Deferred observations, not silently resolved:**

1. **Simulated ruin and ENLC ties.** The amended §4.5 absorbs a valid simulation's ruined path;
   M5 forbids filling, clipping or renormalizing a *failed fit*. These describe different cases:
   A-SE-05 still requires a named fallback and A-SE-09 checks the amended ruin policy without
   repairing a fit. However, §5.3 does not choose among more than `ceil(alpha P)` paths tied at
   −100%, nor specify whether its additive attribution stops at ruin. A-SE-19 covers the
   stated formula and uniquely ranked tails; tie-breaking/post-ruin attribution needs an
   explicit decision before claiming comprehensive ruined-tail ENLC coverage.
2. **Strict order on degenerate paths.** §10.5 says `Bad < Typical < Good` for every engine,
   while §4.5 explicitly allows constant daily returns, which produce equal percentiles.
   A-SE-10 checks strict ordering on nondegenerate fixtures and the actual constant-path
   compounding formula separately. It does not invent jitter or authorize rejecting cash.
3. **ENLC word normalization.** §5.5 gives `(measure − 1)/(ref − 1)` while §6 explicitly gives
   `ENLC/ref` for `m=enlc`; §10.3 also specifies a DR² fallback when ENLC is undefined.
   A-SE-20 checks the source measure and the defined fallback without choosing between those
   two ENLC normalizations. A degenerate `ref = 1` for the shifted formula is also unspecified.
4. **Copula copy and margins.** §4.4, §7 and decision 11 specify empirical margins; the §6
   technical-copy row still says Student-t margins. A-SE-24 follows the explicit model decision;
   A-SE-26 requires truthful details but does not freeze the contradictory sentence. The
   rationale in §4.4 about simple returns also predates the log-space amendment.
5. **Report comparison details.** §10.7 names concentration, return given up, stability and
   "no worse" across menus, but does not fix all aggregation/norm choices. A-SE-22 checks the
   required raw measurements, paired scope, disclosed aggregation and tie preservation; it
   does not manufacture a statistical superiority threshold or permission to switch.
6. **No-request switch versus interpolated mixes.** §11 Phase 1 says the control switches
   with no request; §7 explicitly obtains arbitrary mixes through `/v1/range` and §6 permits
   a nearer-level placeholder for ENLC. A-SE-12 uses precomputed mixes for its zero-request
   assertion; A-SE-11 covers the interpolated API. Whether an uncached arbitrary mix may
   request ranges on the switch requires reconciliation before a universal no-request claim.
7. **One-fund splice comparison.** The splice rule needs other included funds' residuals;
   the median of an empty comparison set is unspecified. A-SE-06 uses a nonempty peer set
   and does not invent acceptance or rejection for a one-fund menu.
8. **Entered allocations in validation.** The inherited preset/tensor contract makes an
   entered mix optional, and the presets carry no allocation. A-SE-14 checks an entered
   portfolio when an allocation is explicitly supplied; otherwise the report must identify
   that case as unavailable because no allocation was supplied, not fabricate holdings or
   claim to have tested an entered portfolio. The owner can supply allocations for a fuller
   comparison; these assertions do not choose them.
9. **Level zero and the white line (D3, deferred to C8; added 2026-10-18).** A-SE-10's leg
   "level zero equals its frontier node" and the demo gates that read it (A-PS-17/18/34) are
   true for schema-3 fixed-risk ladders. On a schema-4 sacrifice ladder level zero is `w_R`
   (spec §5.5, §7), which equals the frontier node only under D3 option (i). A-SE-18 checks
   level zero against `w_R`; the frontier-node leg of A-SE-10 is reconciled at C8 and is not
   silently kept or dropped here.
10. **Guards between levels (added 2026-10-18).** The hop rule verifies the midpoint blend of
   two adjacent levels only, as the risk-line hop rule did; a between-level or between-column
   position's guards are not re-verified in the browser, and its exact figures arrive through
   C3. A-SE-18 checks the hop flags at midpoints and that the trade-off line is marked
   estimated while C3 is pending; it does not invent a guarantee for every interior position.
11. **Engine switch and chart geometry (added 2026-10-18).** A-SE-12's "no chart-geometry
   change" leg holds for Phase 1 tensors, whose ENB ladder is engine-independent. Under the
   contract the ladder is the engine's, so on schema-4 tensors the selected point, ladder and
   map move with the engine (spec §6); S3 is narrowed pending the owner's confirmation (§13
   item 22). A-SE-20 checks the schema-4 behaviour; A-SE-12 is unchanged for its fixtures.
12. **Build cost (added 2026-10-18).** Spec §9 states that the sacrifice ladders' cost is
   unknown and names the levers; no assertion here fixes a budget for them. A-SE-22's repeat
   of A-SE-16's workload stands; whether the 30 s build budget survives the contract is a
   measurement for phase 7 and, if it does not fit, an owner choice (§13 item 23).
13. **DR² covariance oracle (added 2026-10-19).** Spec §10.6's DR²-covariance oracle (DR² on
   the production `estimate_moments` covariance reproduced, the applied shrinkage recorded,
   shrunk DR² at least raw-sample DR² on a non-negative-correlation fixture, the sign reported
   for a negatively correlated pair) is covered by focused unit tests (plan 6b.2a
   `tests/engine/test_stats.py`; 6b.2 and 7.1 `tests/engine/test_measures.py`) and by protocol
   §8's bit-identical estimator check, not by a gate assertion. A-SE-17's frozen identities are
   correct as frozen, and the covariance definition is an engine contract tested at unit level.

These are limitations of the currently determined boundary, not passing exceptions in a
downstream test. Keep them visible in the plan and final phase verification.

## 3. Four-part assertion specifications

### Phase 1 — Volatility model

### A-SE-01 — QSE files match an upstream pin and cannot drift unnoticed
Phase 1 · static/unit · S9, M2; §3.3, §8, §13.18

- **Claim.** The copied QSE source is exactly the permitted source at the locked upstream commit,
  and any local source drift is rejected by the guard.
- **Setup.** The selected upstream commit (Phase 1 initially
  `ca8c0445a56712c92dc028e68845b94963fdd590`), trusted source hashes independently verified once
  against its git objects and pinned in the frozen test, a tiny synthetic local git repository,
  a clean temporary destination and the actual sync entry point. Ordinary gate execution needs
  neither the private QSE checkout nor GitHub access.
- **Observation.** Independently compare every copied source byte/hash and lock entry with the
  trusted pinned hashes. Exercise the sync against the synthetic git repository and verify its
  output against that repository's git objects. The tracked package contains only selected source plus the
  specified README/lock/package support files; no unlisted implementation may hide outside the
  lock. Source files are read-only after sync, and tracked agent settings deny editing/writing
  `qse/`. In a disposable copy, change a source byte and separately add an unlisted source file;
  the real guard fails both with the private checkout unavailable. Re-sync against the synthetic
  repository restores its exact bytes without changing upstream files or working-tree state.
  Fail on any drift, an unpinned sync or a self-consistent forged local lock that disagrees with
  the trusted hashes. The frozen test anchors provenance; the ordinary product guard rehashes
  its local lock and is not required to contact upstream or perform this independent attestation.
- **Kind.** contract.

### A-SE-02 — Engine use stays inside the declared dependency and data boundary
Phase 1 · static/unit/api · S9, M4; §3.3, §8, §10

- **Claim.** Building and serving simulation results uses only the allowed QSE distribution
  surface and PortfolioSight's store, without QSE data/storage/provider access.
- **Setup.** Use an isolated environment containing PortfolioSight's declared runtime
  dependencies, prepared and attested once; ordinary gate execution does not install packages
  online. Isolate the import probe from unrelated preloaded application modules;
  provide complete temporary PortfolioSight price records; make QSE data, storage, credentials
  and provider-call routes fail if accessed. Exercise a real fit, tensor build, range request
  and a small validation run.
- **Observation.** The production paths succeed with those forbidden resources inaccessible and
  record no attempted access. PortfolioSight imports QSE only through `qse.distributions`;
  importing/running the copied joint fitter adds only the dependencies allowed by §8 and their
  declared transitive dependencies. `arch` is pinned exactly; no full QSE installation, torch or
  xgboost is introduced by this integration. The sync uses local git objects and never reads a
  lake or provider credential. Fail on any attempted forbidden read, write or request even if
  the calling code catches its error and returns a plausible result.
- **Kind.** contract.

### A-SE-03 — Enabling GARCH preserves replay and the owner-controlled defaults
Phase 1 · unit/api/ui · S2, F1, M3; §4.2, §7, §11, §13.1/7

- **Claim.** Adding an available simulation engine leaves the default replay figures and
  default optimized measure unchanged for the same inputs.
- **Setup.** Preserve replay outputs from the pre-engine implementation for several fixed price
  records, lookbacks, bounds and weight vectors; include both presets. Build the same inputs
  with replay alone and with replay/GARCH; load without `e` or `m` and request `/v1/range`
  without an engine.
- **Observation.** Every retained default range field and replay result matches the frozen
  replay computation, including its unchanged sample-volatility treatment and normal range.
  `range_default` remains `replay`, the default ladder remains `enb`, and omitted selections
  resolve to those defaults in the endpoint and page. Compare varied mixtures and lookbacks,
  not one hard-coded number. New engine fields may be added; the old calculation must not
  change or silently apply the simulation scaling to replay. Retain this check through Phase 2.
- **Kind.** property.

### A-SE-04 — Shape construction preserves each fund's history and requires a usable common pool
Phase 1 · unit/api · S4, F6, M5; §4.3, §7

- **Claim.** Shape fitting and pool availability depend on the included fund set and its
  unfilled history through `D_G`, independently of the chosen lookback's level.
- **Setup.** Dated simple-total-return fixtures with more than 2,520 calendar rows, different
  starts, internal missing days, post-`D_G` observations, different lookbacks sharing a fund
  set, and a lookback that changes the included set. Include residual-overlap cases on both
  sides of the 126-row floor and a zero-residual fund.
- **Observation.** Through the builder, inspect the actual input passed to the upstream fit:
  `log1p` of the fund's present observations in the last 2,520 union-calendar rows through
  `D_G`, with missing entries still missing. The shape digest independently hashes the simple
  panel with canonical NaNs. Identical included sets/data give identical shape inputs/digests
  across lookbacks, while modifying an included historic return changes the digest. The pool
  consists only of jointly present residual rows in panel order; each nonconstant column has
  mean zero and population variance one, while zero residuals remain zero. Fewer than 126
  common rows yields the specified unavailable status/reason and no served GARCH range;
  sufficient common history reaches the real simulation. No filling or use of future records
  may create eligibility. Constant-overlap error cases not resolved by the spec are not
  repaired into a fabricated usable pool.
- **Kind.** property.

### A-SE-05 — Every failed or weak fit becomes a disclosed constant-volatility model
Phase 1 · unit/ui · S5, M5; §4.3, §6

- **Claim.** Every specified fallback condition produces the named constant-volatility model
  and preserves the fund's inclusion in the joint simulation.
- **Setup.** TSP-G-like low-variance log returns, exactly constant data, a 200-row fit fixture,
  an included 227–251-row young fund, and controlled upstream optimizer outcomes for failed,
  non-finite/invalid and nonstationary parameters; include a valid stationary control.
- **Observation.** Exercise the real fitting adapter with each condition and independently
  check the status, `alpha = beta = 0`, sample-variance `omega`, standardized residuals and
  zero-residual behavior at the specified thresholds. The nonstationary boundary is
  `alpha + beta >= 1 − 1e-4`; the near-constant threshold uses log-series daily sd `3e-4`.
  The valid control retains its fitted recursion. The builder retains fallback fund columns,
  reports statuses, and the page names those funds as having volatility held constant. No
  failed fit may become an apparently valid GARCH fit by clipping parameters, filling values
  or renormalizing them. The young fund is not moved to the excluded list merely for falling
  below the 252-row fit minimum.
- **Kind.** property.

### A-SE-06 — The splice guard rejects isolated synthetic crashes without erasing real extremes
Phase 1 · unit · F5, M5; §4.3

- **Claim.** The build rejects a splice-day residual exactly when both specified extreme
  conditions hold and otherwise retains the extreme as a reported outlier.
- **Setup.** At least three included funds with residuals on the splice date; a fabricated 30%
  ex-date drop; controlled cases just below, at and above each absolute threshold; the same
  extreme away from the splice; and a simultaneous cross-sectional crash.
- **Observation.** Run the guard through shape construction. Only splice-day cases with both
  `abs(z) > 6` and distance from the other funds' median greater than 6 fail, naming fund and
  date. Non-splice and common-crash extremes remain in the data and appear in `shape.outliers`
  with their actual fund, date and residual. Boundary cases are not rejected by a substituted
  `>=` rule. Compare pool/data values before and after: no clipping, deletion or replacement
  may make the result pass. The isolated-drop fixture must really reach and fail the guard.
- **Kind.** property.

### A-SE-07 — Simulated mixes share a full draw from long-run volatility
Phase 1 · unit/api · F6, F7, M6; §4.1, §4.3, §7

- **Claim.** All mixes of one tensor and engine use the same complete 2,000-by-252 draw, with
  GARCH volatility initialized from its long-run variance.
- **Setup.** A nontrivial multi-fund fitted panel whose last conditional variance differs from
  its long-run variance; deterministic replay indices and GARCH pool rows; several distinct
  frontier, ladder, entered and interpolated weight vectors, with reordered requests.
- **Observation.** Capture the draw actually consumed by production build and range dispatch.
  It has all 2,000 paths and 252 days and seed `20261013`; every GARCH fund at a path/day
  consumes the same residual-row index, and its first recursion state agrees with
  `omega/(1 − alpha − beta)`, not the last fitted state. Repeated or reordered evaluations
  reuse that draw and yield identical per-mix build results. The artifact-backed API regenerates
  the same draw; a changed seed changes the nonconstant control. Neither metadata declaring
  2,000 paths nor independently drawing per mix satisfies this check.
- **Kind.** property.

### A-SE-08 — Simulation levels follow the amended two-space formula
Phase 1 · unit · S4, F6; amended §4.5

- **Claim.** Every nondegenerate simulated mix uses the chart's daily mean and volatility after
  the specified log-space fund transformation and simple-space mix transformation.
- **Setup.** Small, explicitly enumerable asymmetric log-return panels with distinct means and
  volatilities, zero-variance columns, several positive weight vectors, and two chart covariance
  matrices/mean vectors sharing the same shape. Include `ew` and mixtures for which `k != 1`.
- **Observation.** An independent formula oracle computes lognormal-matched targets, the
  fund-level log transform, `expm1`, pooled simple-space means/covariance with `ddof=0`, and
  `y' = m_w + k(y − ybar)`. Compare production daily mix values with that oracle and verify
  pooled mean `mu_w/252` and sd `sigma_w/sqrt(252)` where the spread is nonzero. Constant
  inputs produce the specified constant branch. Changing the lookback changes targets while
  preserving the raw shape; a case where the transformed simple mean differs from `m_n`
  catches centering on the obsolete formula. Reject a one-step scale on the raw panel,
  robust-scale substitution, or checking only already-produced percentiles.
- **Kind.** property.

### A-SE-09 — Ruined simulations are absorbed and disclosed; invalid history is rejected
Phase 1 · unit/api · S4, M5; amended §4.3/§4.5/§7

- **Claim.** A GARCH path whose scaled mix day reaches or crosses −100% contributes exactly
  −100% for the year and to the disclosed ruin count, while invalid historical/replay days raise.
- **Setup.** Finite daily-path fixtures containing no ruin, a day exactly −1, a day below −1,
  multiple ruin days in one path and subsequent positive days; a valid log-fit simulation where
  mix scaling creates the ruin; simple historical observations at/below −1.
- **Observation.** Reach compounding through the production engine dispatcher. Each ruined
  simulated path has year −1 irrespective of later days and is counted once; all other paths
  retain their actual compounded returns. The tensor's `engines.garch.ruin_paths` is the
  maximum absorbed-path count over its carried mixes, including a fixture where that maximum
  is away from the first mix. Metadata declares `returns=log`, `scale=sd`, `ruin=absorb`.
  The underlying fit/draw is not clipped, capped, resampled or reduced. Historical input at
  or below −1 fails with fund/date; replay still raises on such a compounding day. This
  observation does not settle the ENLC tie ambiguity in §2.
- **Kind.** property.

### A-SE-10 — Tensors expose reproducible, consistent engine results
Phase 1 · unit · S3, S4, F1; §4.1, §7, §10.5

- **Claim.** Identical inputs produce identical canonical tensors whose carried ranges equal
  the selected engine's actual compounded-path percentiles.
- **Setup.** Both preset fixtures across the supported lookbacks, the same versions/bounds/
  `D_G` and single-thread settings, with replay and GARCH; include a separate constant-path
  fixture. Build independently twice, including one artifact-reuse build.
- **Observation.** Canonical JSON is byte-identical. Independently compute linear-interpolated
  2.5/50/97.5 percentiles from consumed paths and compare frontier, ladder and entered blocks;
  level zero equals its frontier node. Normal figures are engine-independent and retained
  legacy fields equal the default engine's fields. Schema/version, shape digest, statuses and
  method/library metadata agree with what ran. Nondegenerate paths have ordered percentiles
  and Typical within the specified `0.25 sigma` bound; constant-path values match compounding
  without invented dispersion. Per-engine `s_safe` is derived by the inherited safe-node rule
  on that engine's Bad figures. A changed nonconstant input must change the corresponding
  result, preventing a serialized fixture from satisfying determinism by itself.
- **Kind.** property.

### A-SE-11 — Range requests use the requested engine or refuse the request
Phase 1 · api · S3, S10, F4; §7

- **Claim.** `/v1/range` computes a requested available engine from matching artifacts and
  refuses an unknown, missing or inconsistent engine without substituting another result.
- **Setup.** A real built tensor and temporary model store, several unseen valid weights and
  both engines. Exercise optional/explicit engine IDs, an unknown ID, an uncarried engine,
  missing artifact, changed shape records and changed lookback records. Use fresh/cache-cleared
  requests for each corruption and include the Worker `/api/range` forwarding leg. Build the
  same shape across different lookbacks and cap policies, and three distinct shapes; retain
  pinned and unpinned generations in the temporary store.
- **Observation.** Success identifies the requested engine and agrees with an independent
  calculation on its build draw within documented float32 error; changing weights or engine
  changes the nonconstant control as expected. Omission uses `range_default`. Unknown IDs
  return 422; unavailable/missing/digest-mismatch cases return 409 `range_unavailable`, with
  no plausible range from replay or a prior cached answer. For Phase 1 tensors without
  loss-attribution capability `loss_sources` is null; Phase 2 attribution is checked by A-SE-19.
  The actual route must load and verify artifacts; directly calling a numerical unit is
  insufficient. Host health reports enabled engines from the actual configuration.
  Count real fit calls to verify same-shape reuse across lookbacks/caps; artifacts remain
  generation-scoped and immutable. After restart, requests reproduce the stored model's
  results. Three distinct shapes evict the least-recently-used simulated panel so at most
  two float32 panels remain; the separate lookback cache retains its stated eight-entry bound.
  Generation pruning removes expired unpinned model artifacts and retains pinned ones.
- **Kind.** contract.

### A-SE-12 — One engine switch updates every precomputed range surface
Phase 1 · ui · S3, F3, F4; §6, §7, §11

- **Claim.** Switching an available engine at a precomputed mix updates every engine-dependent
  page surface from that tensor without a network request or a chart-geometry change.
- **Setup.** Browser-loaded tensors with deliberately distinct replay/GARCH ranges and safe
  endpoints, real chart weights, several frontier/ladder/entered selections, details both off
  and on, and a tensor with an unavailable engine. Intercept network after initial loading.
- **Observation.** Select through the actual Simulation control. After the UI event flush,
  compare the result strip, bar endpoints, frontier risk readouts, all displayed mix cards,
  tags and Method lines to the selected engine's fixture values; change selection back to
  catch cached labels. The bar's scale stays fixed across carried engines and chart mix
  coordinates/weights do not move. An out-of-domain risk position and URL `r` clamp to the
  new engine's domain. Unavailable controls show the tensor reason and cannot select a
  fallback silently. No build, range or other network request occurs for these precomputed
  cases. Arbitrary uncached mixes are the explicit §2 unresolved scope, not claimed here.
- **Kind.** contract.

### A-SE-13 — Engine selection survives the URL and share validator
Phase 1 · unit/api/ui · S10; §6

- **Claim.** Every valid nondefault engine selection round-trips through the canonical address
  and accepted shared-link payload to the same available engine.
- **Setup.** Loaded tensors with distinct engine results, default and nondefault `e` values,
  supported lookback/risk/position combinations and malformed engine values; use the real
  serializer/parser and Worker share validator with an inert mail transport.
- **Observation.** Serialize the page state, validate the share payload, and open the resulting
  address in a fresh page. Its engine and displayed range match the starting selection.
  Default `e` is omitted and nondefault `e` is in the specified position after `x`; invalid
  values cannot be accepted as a different valid selection. No engine localStorage entry
  overrides the URL. Verify the actual validator/forwarded payload, without sending mail.
- **Kind.** property.

### A-SE-14 — Phase 1 validation computes the prescribed comparison
Phase 1 · validation/unit · S8, F8, M3; §10.1/2/5/8, §11

- **Claim.** The Phase 1 report's replay/GARCH metrics are derived from the prescribed
  out-of-sample experiment and retain its stated decision rule and limitations.
- **Setup.** The actual `scripts/backtest_ranges.py`, the local backup mirror, both menus,
  1y/5y lookbacks, all 40 quarterly origins and the prescribed mix set, plus a small synthetic
  timeline with hand-computable future returns and quantile losses. Block provider calls.
- **Observation.** Run the script; inspect its evaluated inputs/results, not just Markdown.
  Every fit/build stops at its origin; changing data strictly after an origin changes realized
  outcomes without changing that origin's prediction. Independently recompute coverage,
  below-Bad breaches, three pinball losses and PIT statistics on the synthetic case and sampled
  report rows. The saved report in `docs/reviews/` covers both menus/lookbacks, separates 40
  overlapping origins from 10 year-end origins, pairs engines on identical origins/mixes,
  contains the live-menu/stress comparisons and invariant results, and states the §10.8 rule
  without changing thresholds to match a result. It acknowledges overlap, weak evidence and
  short stress-window interpretation. No assertion requires GARCH to win or changes defaults.
  Entered-mix rows follow explicitly supplied allocations; when no allocation exists, record
  that case as unavailable with its reason rather than inventing weights or silently omitting it.
- **Kind.** contract.

### A-SE-15 — Bad-year estimates meet the prescribed seed-stability check
Phase 1 · validation · S4, S8, F7; §10.4

- **Claim.** For each tested frontier node and Optimized point, Bad's standard deviation over
  the five prescribed seeds is at most `0.10 sigma_w`.
- **Setup.** Both preset menus and the validation lookbacks at one frozen `D_G`, fixed inputs,
  replay and GARCH, with seeds 20261013 through 20261017 and all 2,000 paths each.
- **Observation.** Re-run actual simulations for every seed; independently recompute the
  across-seed standard deviations and compare each point with its own chart risk. Record
  all measurements, including failures; no omitted point, substituted seed, common copied
  output or reduced-path run may pass. A failing threshold remains a failing observation,
  not a reason to rewrite the rule or approve a default switch.
- **Kind.** property.

### A-SE-16 — Phase 1 stays within the target-host budgets at full path count
Phase 1 · ks001 · S11, M6; §9, §11

- **Claim.** The specified KS-001 workload meets its build, nightly and warm range budgets
  while computing the full replay/GARCH simulations.
- **Setup.** KS-001's four-vCPU container with recorded revision/configuration and frozen stored
  inputs, an idle build queue, the real 23-fund menu/lookback, the two-preset/six-lookback nightly,
  and interpolated requests after the first request for a tensor. Include a build requiring
  its fit rather than timing only a warm artifact hit.
- **Observation.** Measure actual build execution at no more than 30 seconds, the complete
  preset nightly at no more than 10 minutes, and warm replay/GARCH range responses under
  one second. The output and consumed simulation arrays retain 2,000-by-252 paths; named
  fallbacks, host, cache conditions and timings are recorded in the runbook. A laptop
  microbenchmark, fabricated timing field or missing engine does not satisfy the claim.
  Phase 2's repeat workload and 100-fund measurement belong to A-SE-22 so Phase 1
  completion does not depend on implementing its successor phase.
- **Kind.** contract.

### Phase 2 — Diversification measures

### A-SE-17 — DR² has the specified identities and correlation-qualified bound
Phase 2 · unit · S6, F2; §5.2, §10.3

- **Claim.** DR² equals its covariance formula, is one for a single nonzero-risk fund, and
  respects the holdings bound whenever held-fund correlations are non-negative.
- **Setup.** Every single fund of both preset covariance fixtures across lookbacks; generated
  positive-semidefinite covariance matrices and long-only weights; inverse-volatility weights
  on uncorrelated funds; an equal-volatility pair at correlation 0.95; a negatively correlated
  pair as a control. Exercise Python and browser calculations and builder-emitted values.
- **Observation.** Independently evaluate `(sum(w_i sigma_i))^2/(w' cov w)`. Single-fund values
  differ from one by at most `1e-9`; `k` uncorrelated inverse-volatility funds score `k`; the
  0.95 pair scores `2/1.95`. Check the bound only when every held-pair correlation is
  non-negative, using the spec's `w > 1e-6` reporting tolerance. A negatively correlated pair
  may exceed its count and must not be clipped. Compare both runtimes and tensor values for
  varied weights so an always-one implementation fails. Zero-risk division behavior remains
  outside this nonzero-risk identity rather than being invented here.
- **Kind.** property.

### A-SE-18 — Sacrifice ladders are admissible at every level, monotone in the measure, and open on `w_R`
Phase 2 · unit/ui · S6, S13, S14, F2, F10; §5.5, §6, §7, §10.6, §11 (rewritten 2026-10-18)

- **Claim.** Every level of a variant's ladder under an engine is a feasible mix at or inside
  the column's risk ceiling that satisfies the guards and its allowance relative to that
  column's `w_R` under that engine; level zero is `w_R`; the measure never falls and the
  sacrifice never exceeds the allowance down the ladder; hops and collapses are flagged
  truthfully; and both variants' ladders hold actual, distinct selections.
- **Setup.** Build both `LADDER_MEASURE` variants under `replay` and `garch` on both presets
  and on synthetic menus: a ceiling that binds and one that does not; a menu where the best
  measure is `w_R` (collapsed); a menu where adjacent levels share a mix; a small enumerable
  menu (3 funds, a coarse weight grid, a fixed shared draw) whose `w_R`, admissible sets and
  Stage B selections at every allowance are computed by an independent oracle; and a fixture
  where the midpoint blend of two adjacent levels breaks a guard while keeping the ceiling.
  Fixtures include a column where the highest-measure feasible mix has lower `U` than `w_R`
  by more than the cap (so it must not appear) and one where it is within the cap (so it
  appears at the cap end).
- **Observation.** Through the actual builder, verify at every level and engine: caps,
  sum-to-one, `sigma <= X_j + 1e-6` with `sigma` equal to the recomputed risk (no level is
  required to sit on the line, and none is moved onto it); recomputed `B/T/G/U/ES_2.5` on the
  consumed draw equal the stored unrounded values; `B >= B_R − 10 bp`, `T >= T_R − 25 bp`,
  `G >= G_R − 50 bp`, `U >= U_R − allowance[l]`, and not both `B` and `T` below `w_R`'s by more
  than `1e-10`; `sacrifice[l] = U_R − U_l` lies in `[0, allowance[l]]`; `guards[l]` names exactly
  the constraints that hold with equality within `1e-10`. Level zero equals `w_R` with
  `sacrifice = 0` and empty guards, and is the same mix in both variants under one engine.
  The small case's `w_R` and every level agree with the oracle's Stage A and Stage B (D1's
  max-measure rule, with the §5.5 tie rule); the variant's measure is non-decreasing down
  the ladder, and no level is the highest-measure admissible pool member of a smaller
  allowance than its own. `collapsed[j]` is true exactly when the cap end equals `w_R`'s
  measure within `1e-6`. `hop[j][l]` is true exactly when the midpoint blend, evaluated on the
  shared draw, leaves `A(allowance[l+1])`; the browser's `interpolate` holds the upper level to
  the middle of a hopped step and blends elsewhere; the risk of every blend stays at or
  under the ceiling. `ladders[e].z`, `grid[e].z`, both covariance measures and `refs` match the
  variant and engine, with `enb_ref = refs.enb` and `refs` the maximum over that variant's
  ladders under every carried engine. `t_suggested` is 0 at every column; `on_line`,
  `t_balanced`, `y_balanced`, `y_suggested`, `default_point` and `grid.y_sug` are absent from
  schema 4. The raster cell `(j, k)` is the highest-measure level of column `j` with
  `y >= Y_k`, a level and never a blend. The `enb` and `dr2` builds really take their own Stage
  B: on a fixture where the two measures rank admissible candidates differently, the cap ends
  differ; changing only `ladders[e].measure` on one common ladder fails. The `replay` and
  `garch` ladders of one variant really take their own Stage A: on a fixture with
  deliberately different engine percentiles, `w_R` differs. Where D3 option (i) is chosen at
  C8, add that level zero equals the frontier node; where option (ii), that the frontier
  block is unchanged by the ladder.
- **Kind.** property.

### A-SE-19 — ENLC measures the actual losing contributions of the selected engine
Phase 2 · unit/api · S6, S7, F7, M5; amended §4.5/§5.3, §7, §10.3

- **Claim.** Each returned loss-sources block equals loser-only entropy over the specified
  worst compounded paths using the exact per-fund additive decomposition.
- **Setup.** Deterministic replay/GARCH paths with uniquely ranked worst years, positive
  losers, a hedge, zero-weight funds and more than three losers; single-fund loss and
  all-gain cases; varied weights and both presets. Include a case where compounded-year
  ranking differs from additive-year ranking and where `Rbar'_n != m_n`.
- **Observation.** Independently rank the engine's actual compounded years and take
  `ceil(alpha P)` paths. Compute contributions with
  `w_n [252 m_n + k(S_pn − 252 Rbar'_n)]` for the amended simulated path and the stated
  replay decomposition; their sum equals the additive mix year. Calculate each `ell_n`,
  positive-only shares and `exp(-sum(s log(s)))`. Check builder ladder/entered blocks and
  real `/v1/range` results, including changed weights and engines. Single losing funds
  give exactly one; no positive losses gives null and the stated no-loss presentation;
  hedges have zero share and their actual IDs, zero holdings contribute zero, `top` contains
  at most the three greatest positive shares in descending order, and ENLC is bounded by
  the number of positive contributors and held funds. No range-independent or fixed
  loss-sources block passes. Ruined-tail tie/post-ruin policy remains the explicit §2 gap.
- **Kind.** property.

### A-SE-20 — Measure and engine selection select actual holdings on the sacrifice ladder and survive sharing
Phase 2 · ui/api · S7, S10, S12, S14, F4, F9; §5.5, §6, §7, §10.3 (rewritten 2026-10-18)

- **Claim.** The selected measure, engine and allowance position consistently determine the
  page's holdings and every holdings-derived surface from `variants[m].ladders[e]`, the
  default position is `w_R`, and the state survives a canonical shared-link round trip
  without rebuilding mixes.
- **Setup.** Actual built schema-4 tensors with distinguishable `enb`/`dr2` cap-end mixes,
  distinguishable `replay`/`garch` `w_R` at the same column, distinguishable DR², ENB and
  per-engine ENLC values, defined and null ENLC, several allowance levels, a hopped step, a
  collapsed column, and an interpolated request with a controlled delayed answer. Exercise
  every available `m`/`e` combination at `d = 0`, at an interior `d`, and at `d = 1`, through
  the controls and fresh URLs, including addresses carrying `d=auto`, no `d`, and a numeric
  `d` written before 2026-10-18.
- **Observation.** The measure control is details-only. Loading without `d`, with `d=auto`
  or with `d=0` lands on `w_R` of the active variant and engine at the risk position (the
  blend of the two columns' `w_R` between columns), and the canonical address writes `d=0`.
  Switching `m` at `d = 0` moves nothing; at `d > 0` it changes the selected holdings to the
  other variant's level at the same allowance and, with them, the selected marker, holdings
  table and mix cards, score/word/reference, result-strip ranges, `ES_2.5`, trade-off line,
  ENLC and hedge IDs, stress results, trades and exported CSV, and the map's cells and legend
  from `variants[m].grid[e]`; the frontier, entered mix and chart moments do not move. Switching
  `e` changes the ladder to `variants[m].ladders[e]`: the selected holdings move wherever the
  two engines' selections differ, with every surface above, while `d` is kept, `r` is clamped
  into the new `s_safe` domain, and the axes, ceiling line and entered mix do not move; the
  readouts follow D3 as chosen at C8. The trade-off line shows the signed differences of the
  selected mix's exact figures against `w_R`'s ("Trade-off vs no-trade-off mix: …"), reads
  "No trade-off" at `d = 0`, and is marked estimated while an exact result is pending; the
  slider's left end reads "No trade-off", the chosen mix is labelled "Selected mix", and no
  slider end or trade-off line calls `w_R` "Optimized", "best-return" or "Best return". Selecting ENLC in details leaves the
  map and selected point on `ladders[e].measure`, labels that map correctly, and uses the
  selected engine's loss values and hedge IDs; undefined ENLC shows the specified no-loss
  message and the covariance-measure fallback. While an interpolated response is pending, the
  nearer-level placeholder and eventual response follow the active engine, variant and mix,
  including a selection change before a response arrives; a late reply for an earlier
  selection never replaces the current one. The real share validator accepts `m`, `e` and
  `d`; canonical URL order and omitted defaults hold (`d` always written); absent `m` resolves
  from the loaded tensor; a fresh page reproduces holdings, position and figures. No build or
  rebuild request occurs for any precomputed level. For DR² and ENB with `ref > 1`,
  independently compute `q = (measure − 1)/(ref − 1)` and check the words immediately below,
  at and above 0.30, 0.50 and 0.75: Poor, Fair, Average and Good follow the specified cut
  points; `ref` is the variant's maximum over every carried engine's ladder. Legacy
  `measure/ref` normalization or shifted boundary comparisons must fail. A page that
  relabels one variant's or one engine's holdings as another's fails. Exact disputed ENLC
  normalization and `ref = 1` presentation remain deferred in §2 rather than receiving
  invented constants.
- **Kind.** contract.

### A-SE-21 — Served copy distinguishes scores from holdings and confines technical terms
Phase 2 · ui · F3, S6, S7; §6, §6.1

- **Claim.** Served measure copy never represents a score as a number of holdings, and
  technical model vocabulary appears only in the allowed details surfaces.
- **Setup.** Both presets, all supported lookbacks, each available engine/measure, details
  off/on, mix cards, hover text, fallback/no-loss cases and responsive page states.
- **Observation.** Inspect rendered text, not source comments/specs. With details off,
  diversification is a word/map, not a raw count; `GARCH`, `vine`, `residual`, `expected
  shortfall` and `entropy` do not leak into plain copy. `Copula` is permitted only in its
  defined control label/tag. Outside technical lines, served copy contains neither
  "equivalent of" nor "independent bets". Details report shares of the best found; any raw
  score occurs only in a named technical measure line carrying "A score, not a count of
  funds or stocks." Check each runtime-selected branch so one compliant default screen
  cannot conceal forbidden wording on cards or another measure.
- **Kind.** property.

### A-SE-22 — The measures report compares both actual ladder methods
Phase 2 · validation/unit · S8, F8, M3; §10.3/7, §11

**Scope reconciled after C8 (2026-10-18).** This observation was written for the fixed-risk
comparison (Optimized point and peak of each column). Spec §10 item 7 now takes its arms,
comparison points (`w_R` and the cap end of each column's sacrifice ladder) and selection
rule from the experiment protocol and §5.5, and its default-change bar from D4. The realized
metrics below are unchanged as reporting requirements; the points they are computed on, and
whether an ENB arm exists at all, are fixed at C8. Until then this assertion is not frozen
as a test; the claim and observation are retained for the parts that do not depend on C8.

- **Claim.** The measures report computes the specified paired comparison of the evaluated
  arms from distinct real selections on the same evaluation scope.
- **Setup.** The §10.1 origin/menu/lookback dataset, both ladder selectors, independent
  hand-computable metric fixtures, and the actual validation script with provider access blocked.
- **Observation.** The script runs every evaluated arm on matching inputs and records `w_R`
  and the cap-end mix of every column under each measure the arm uses (the ENB arm only if
  D4 gated it in; otherwise the report says "unevaluated"). Independently check sampled
  realized-risk errors/exceedances against the ceiling, stress/worst-year losses, realized
  loss concentration, return given up, and weight stability. Report both menus, single-fund/
  bound results, the count of levels inside their ceiling by more than `1e-6` (replacing the
  off-line level count), word distribution, the 100-fund DR² measurement, and the required
  comparison table/verdict. Trace metric rows to the evaluated weights and future prices; a
  heading or copied table is insufficient. Aggregation choices are disclosed rather than
  secretly tuned. A tie leaves ENB as the default, and the report cannot itself authorize a
  default/headline switch; "confirmed worthwhile benefit" (realized benefit support in both
  menus and no material-harm risk cell, protocol §7) is the bar.
  Repeat A-SE-16's full target-host workload with Phase 2 enabled, retaining the same
  23-fund build, preset-nightly and warm-range budgets and full path count. Separately
  record the specified 100-fund DR² measurement without inventing a 30-second budget for it.
  Owner screenshot interpretation and unresolved metric-aggregation choices remain in §2.
- **Kind.** contract.

### A-SE-23 — ENLC satisfies the prescribed seed check without hiding failed runs
Phase 2 · validation · S7, F7; §10.4, §13.5

**Scope reconciled after C8 (2026-10-18).** "Optimized point" below meant the knee of the
fixed-risk ladder. Under spec §5.5 the tested points are each frontier node and each column's
`w_R` (the default landing) under each engine, plus the cap end of the sacrifice ladder under
each measure the C8 scope ships. The threshold, seeds, path count and alpha rule are unchanged.

- **Claim.** Defined ENLC values at each tested point have across-seed standard deviation
  at most 0.3 at the explicitly selected tail level.
- **Setup.** Both presets and validation lookbacks, replay/GARCH, every frontier node, `w_R`
  and cap-end point required by §10.4 as reconciled at C8, seeds 20261013–20261017, 2,000
  paths per run, initially alpha 5%; preserve null/no-loss outcomes separately from numeric
  samples. Because `w_R` is itself selected on the seed-20261013 draw, re-evaluate the fixed
  seed-20261013 weights under the other seeds; do not re-select.
- **Observation.** Recompute the actual tail sets and ENLC for all five seeds and compare
  every defined point with 0.3. If the specified 5% check fails, preserve that evidence and
  perform the allowed complete 10% rerun with the selected alpha consistently recorded in
  method/report/copy; no per-point alpha or omitted seed may pass. Numeric/null transitions
  are reported as unresolved outcomes, not converted to zero or dropped to manufacture a
  standard deviation. A failed final check remains failed.
- **Kind.** property.

### A-SE-29 — The selector obeys the owner's preference contract
Phase 2 · unit · S13, F10; §3.7 D1, §5.5, §10.6, §13.19 (added 2026-10-18)

- **Claim.** Stage A selects by `U = 0.60 B + 0.30 T + 0.10 G` with finite trade-offs; the
  admissible set bounds reductions only, vetoes a joint Bad-and-Typical deterioration, and is
  nested in the allowance; Stage B selects the most diversified admissible mix found without
  touching Stage A; ties and dominance are resolved against global maxima and are acyclic.
- **Setup.** Independent oracles on hand-built candidate tables of `(B, T, G, M, w)` with no
  simulation: the owner's A `[−0.0500, 0.04, 0.12]` and B `[−0.0501, 0.08, 0.18]`; candidates
  exactly at, just inside (`−1e-9`) and just outside (`+1e-9`) each guard on one quantile with
  the others above `w_R`; a candidate above `w_R` on every quantile; a candidate lower on Bad
  and Typical by `2e-10` with Good high enough to keep `U` within the allowance and a higher
  measure; candidates lower on Bad only and on Typical only within their guards; one pool
  selected at caps 0, 2.5, 5 and 10 bp; a pool whose highest-measure feasible member has a
  higher `U` than every Stage A start; the three-candidate cycle fixture `A = (0, 0, 0)`,
  `B = (1.5e, −0.75e, −0.75e)`, `C = (0.75e, 0.75e, −1.5e)`, `e = 1e-10`, in all six input
  orders; a tie set of three candidates within `1e-12` of the maximum `U` differing in
  `B`, then `T`, then `G`, then weight order; a Stage B tie set of admissible candidates whose
  measures lie within `1e-12` of the admissible maximum and which differ in `U`, with further
  members tied on `U` and differing in `B`, then `T`, then `G`, then weight order; and a
  dominated candidate (no return quantile above another pool member's, one lower by more than
  `1e-10`) carrying the highest measure of the pool and a `U` within the allowance. Then the
  same oracles on a small enumerable menu (3 funds, a coarse weight grid, one fixed shared
  `replay` draw) where every candidate's `B/T/G` is computed independently of production.
- **Observation.** Call the production selector on the tables and the menu; the oracle never
  calls it. `U(B) − U(A) = +0.01794` and B is `w_R`; a strict lexicographic rule, which picks A,
  fails. At allowance 0 the only admissible candidates are those with `U >= U_R` (so `w_R` or
  its ties); the at-guard and inside-guard candidates are admissible and the outside-guard
  ones are not, each compared to `w_R`'s unrounded figures; the all-above candidate is never
  excluded by a guard. The joint-deterioration candidate is inadmissible at every cap
  including 10 bp despite its higher Good, admissible `U` and higher measure; the Bad-only and
  Typical-only candidates are admissible. Across caps 0 → 2.5 → 5 → 10 bp the selected
  measure is non-decreasing, the selected `U` non-increasing, every selected `sacrifice` is in
  `[0, cap]`, and each cap's admissible set contains the smaller cap's. Changing every
  candidate's measure leaves `w_R`, `U_R`, the guards and the allowance-0 selection unchanged,
  and Stage A reaches the high-`U` candidate through `U` alone. The cycle fixture yields the
  same acyclic dominance relation in all six orders; the Stage A tie set is formed against the
  global maximum `U` within `1e-12`, not by pairwise comparisons, and resolves by higher `B`,
  then `T`, then `G`, then the lexicographically smaller weights. The Stage B tie set is formed
  against the admissible set's global maximum measure within `1e-12` and resolves by higher
  `U`, then `B`, then `T`, then `G`, then the lexicographically smaller weights; a selector
  that picks the lower-`U` member, or that orders Stage B ties by `B` before `U`, fails. The
  dominated candidate is removed before Stage A (it is absent from the filtered pool the
  selector reports) and is never the Stage B pick at any cap, including 10 bp, despite holding
  the pool's highest measure; the dominating member remains eligible. On the enumerable menu
  the production `w_R` and every allowance level equal the oracle's exhaustive filter, Stage A
  and Stage B (D1's max-measure rule). A selector that rounds before comparing, compares to
  displayed figures, penalizes an improvement, or lets the measure change `w_R` fails.
- **Kind.** property.

### A-SE-30 — The default landing point is `w_R` on both presets and every lookback, its rendered figures equal `w_R`'s exact figures, and the old-default/frontier/new-landing comparison is printed
Phase 2 · unit/ui · S14, F11; §5.5, §6, §10.6 (added 2026-10-18)

- **Claim.** With no explicit allowance the page lands on `w_R` of the active variant and
  engine at the selected risk, on both presets, at every lookback, at every column and at
  interpolated positions; the figures it renders there equal `w_R`'s exact figures; and on
  the TSP 5y fixture the old default's, the frontier mix's and the new landing's figures are
  printed side by side. Whether the landing is below the frontier mix on both Bad and Typical
  (F11's "worse than another mix on screen" leg) is recorded as a C8 finding, not asserted.
- **Setup.** Actual schema-4 tensors for both presets and all six lookbacks under `replay`
  and `garch`; the TSP 5y fixture of spec §5.5 (the saved artifact
  `2026-10-16-0.2.0/63643e52f0386317/5y.json` and its successor built under the contract) at
  the default landing position (the column whose ceiling is 9.1%: old default Bad −10.5% /
  Typical +7.4% against the frontier mix's −7.9% / +8.2%) and, separately, the investigation
  position `r = 36.382658` (≈ 12.53% risk: `d=1` −15.4 / +7.9 / +33.7 against `d=0`
  −12.4 / +9.8 / +34.5, word Average → Good); browser loads without `d`, with
  `d=auto` and with `d=0`; the intercepted exact-range response for the landing mix.
- **Observation.** For every preset, lookback, engine and column, the landing weights equal
  `ladders[e].w[j][0]` exactly, and between columns the blend of the two columns' level zero;
  the landing mix's exact Bad and Typical, recomputed on the consumed draw and returned by the
  real `/v1/range`, equal `w_R`'s, so neither is below it. The strip's figures at landing are
  `w_R`'s under the active engine, the chosen mix is labelled "Selected mix", the slider's
  left end reads "No trade-off" and the trade-off line reads "No trade-off" (never
  "Optimized", "best-return" or "Best return" for `w_R`). On the TSP
  5y fixture the report prints, for the same ceiling, the old default's figures
  (−10.5 / +7.4), the frontier mix's (−7.9 / +8.2) and the new landing's; the landing's `U` is
  at least the frontier mix's (the frontier mix is feasible at the ceiling). If the landing is
  below the frontier mix on both Bad and Typical at any column, the report records it with
  its figures as a C8 finding; the test does not move the default or alter the contract to
  hide it. A page that lands on a knee, the peak, a cached old position or a mix of a
  different variant or engine fails. The check reads the rendered holdings and figures, not
  the store's intended position.
- **Kind.** property.

### A-SE-31 — `ES_2.5` is the mean of the worst 2.5% of years and steers nothing
Phase 2 · unit/api/ui · §3.7 D5, §4.1, §6, §7, §10.5/6 (added 2026-10-18)

- **Claim.** Every reported `ES_2.5` equals the mean of the 50 lowest of the 2,000 compounded
  years on the consumed draw under the stated engine, sits at or below Bad, equals the
  compounded return on a constant portfolio, is shown in details only, and is read by no
  selection, guard or word.
- **Setup.** Deterministic `replay` and `garch` paths with uniquely ranked years, a
  constant-return portfolio, every single fund of both presets at the validation lookbacks,
  ladder levels, the entered mix and `/v1/range` for unseen weights; a mutation harness that
  perturbs the stored `es` of every level and the response's `es`.
- **Observation.** Independently sort the consumed compounded years and average the 50
  lowest; compare with `ladders[e].es`, `frontier.ranges[e].es`, `entered.ranges[e].es` and the
  `/v1/range` `es` to documented float error. `es <= bad` everywhere; the constant portfolio
  gives `es = bad = typical = good`; a single fund's `es` under `replay` equals the same
  computation on its own resampled years. With every `es` perturbed, `w_R`, every level, every
  guard flag, every word and every headline figure are unchanged. With details off, no
  rendered text contains the tail average or "expected shortfall"; with details on, the
  plain line and its technical line appear with `data-testid="details-es"`, and the figure
  is never in the result strip or the risk readouts. A value computed from a different tail
  size, from the additive year, or from a different engine than the one named fails.
- **Kind.** property.

### A-SE-32 — Prices after an origin cannot change that origin's selection or prediction
Phase 1 (harness) · unit/validation · S8, F8, M3; §10.1, §11 (added 2026-10-18)

- **Claim.** In the generalized rolling-origin harness, every quantity the harness predicts
  or selects at an origin depends only on records dated at or before that origin, for the
  engine validation and for every experiment arm alike.
- **Setup.** The actual `scripts/backtest_ranges.py` on a small synthetic timeline with
  several origins, both menus' shapes in miniature, `replay` and `garch`, the return baseline
  arm and the +DR² arm (the +ENB arm if gated in); a mutation harness that alters prices
  strictly after a chosen origin (a shift, a spike, a missing day) and, separately, prices at
  or before it.
- **Observation.** Run the harness before and after each mutation. For the chosen origin,
  the after-origin mutation leaves byte-identical: the fitted shape, the pool, the lookback
  moments, the frontier nodes, `w_R` and each arm's selection at every allowance the harness
  evaluates under each engine and measure (the harness produces arm selections at evaluated
  allowances, not the 14-level product ladder), the predicted Bad/Typical/Good/`ES_2.5`, and the tuning inputs
  of the preference step; it changes the realized one-year return, coverage, breaches,
  pinball losses and the realized-outcome legs of every arm. The at-or-before mutation
  changes that origin's prediction or selection. Later origins may change under either
  mutation, and the harness records which. Blocking provider access does not alter the
  result. A harness that reads a whole-history artifact, a current tensor, or a cached
  selection keyed without the origin fails; so does one whose engine validation and
  experiment legs use different origin sets or exclusion rules. This extends A-SE-14's
  prediction leg to selection and to the experiment's arms; A-SE-14 is unchanged.
- **Kind.** property.

### Phase 3 — Copula, future scope

### A-SE-24 — The copula engine draws fitted dependence through QSE's ShockSource seam
Phase 3 · unit/static · S4, S9, M2; §4.4, §13.11/18

- **Claim.** Copula simulation uses the pinned upstream fitted vine with the specified
  empirical margins through the same recursion and level pipeline as GARCH.
- **Setup.** The reviewed/merged upstream copula pin, a dependency fixture with nonzero and
  zero-residual funds, a dependence-preserving panel and a dependence-altered control with
  the same marginal samples, plus deterministic seed and single-thread fit controls.
- **Observation.** Extend A-SE-01 to the new pinned source. Independently check rank-based
  pseudo-observations and linear empirical quantiles; zero-residual funds are excluded from
  dependence fitting and receive zero shocks. Inspect the actual fitted family/BIC/truncation
  configuration and the `ShockSource` draw consumed by the engine. A changed dependence
  fixture changes fitted dependence while leaving margins fixed. Replaying captured `Z`
  through the shared recursion/level logic reproduces the copula result; fixed empirical
  rows, independent marginal draws or a relabelled GARCH path cannot pass. Record exact
  library version and the specified default or explicitly applied named fallback controls.
- **Kind.** contract.

### A-SE-25 — Copula requests reuse the build's stored shock artifact
Phase 3 · unit/api · S3, S10, F7; §4.1, §7

- **Claim.** Artifact-backed copula requests use the same stored shock draw as their tensor
  and refuse missing or mismatched source state.
- **Setup.** Real copula preset builds and serialized vine/margin/shock artifacts, more than
  two cached engine/fund-set combinations, novel weights, a missing shock artifact, and
  changed shape/lookback records; restart the service between build and API comparison.
- **Observation.** The fit/artifact key follows generation and shape digest, not lookback or
  caps; identical fund sets reuse the fit. Stored shocks are `P × H × N` float32 with all
  paths. The real `/v1/range` route reconstructs copula results from these shocks, never a
  fresh vine draw, and agrees with the build after accounting for documented float32 error.
  Missing artifacts and digest disagreements return 409 `range_unavailable`, never another
  engine. Inspect the bounded two-panel cache and eviction/reload behavior. A replay after
  restart must genuinely consume persisted artifacts, not a test's in-memory fit object.
- **Kind.** contract.

### A-SE-26 — Both preset pages expose the real copula results
Phase 3 · ui/unit · S2, S3, F3, F4; §4.4, §6, §7, §11

- **Claim.** Both ready-made menus expose the carried copula results and dependence summaries
  through the existing selection flow.
- **Setup.** Actual three-engine tensors for both presets, a custom menu whose configuration
  excludes copula, and delayed copula range responses for an interpolated selection.
- **Observation.** Enable/select Copula through the browser and extend A-SE-12/A-SE-13/A-SE-20
  to it. Displayed ranges, tags and loss details match actual tensor/request results; node
  figures remain visible while an interpolated answer is pending. Custom menus excluding
  copula show the specified unavailable reason. Independently recompute lower-tail 5%
  concordance from captured nonzero shocks and compare the tensor matrix; tree likelihood
  shares track the actual fitted trees rather than placeholders. Zero-margin conventions
  and corrected technical copy must be resolved before asserting those ambiguous values;
  the implementation must not claim parametric margins when using empirical ones.
- **Kind.** contract.

### A-SE-27 — Copula validation compares against GARCH on the prescribed evidence
Phase 3 · validation · S8, F8, M3; §10.1/2/4/8, §11

- **Claim.** The Phase 3 report adds a genuine copula-versus-GARCH comparison and prescribed
  stability results without changing the decision rule or defaults.
- **Setup.** The same frozen data/origins/mix set used by the validation protocol, all three
  actual engines and the five prescribed seeds; provider access disabled.
- **Observation.** Extend A-SE-14's independent metric checks to copula, with GARCH as its
  comparator, and A-SE-15/A-SE-23 to its Bad and ENLC stability. The report contains both
  presets/lookbacks, stress placement, all evaluated rows and the unchanged rule, including
  evidence unfavorable to copula. Comparison is by distribution/percentiles, never matched
  path IDs across different engines. No default changes because a report was generated;
  the owner's review and decision remain outside the machine gate.
- **Kind.** contract.

### A-SE-28 — Three-engine execution meets the target-host budgets
Phase 3 · ks001 · S11, M6; §9, §11

- **Claim.** KS-001 completes the full three-engine preset nightly within ten minutes and
  answers copula range requests within ten seconds without reducing path count.
- **Setup.** The configured KS-001 container, both preset menus and all six lookbacks, a new
  generation requiring its relevant fits/draws, and copula requests including the first
  artifact load; capture revision, resource limits and cache state.
- **Observation.** Time the actual nightly to completion and the actual copula HTTP response,
  checking all requested engines/tensors were produced. Confirm 2,000 paths and 252 days
  at the simulation consumer as well as in metadata. Record times and any applied named
  fallback in the runbook. A partial nightly, omitted copula, smaller path count, warm-only
  substitute for first load, or laptop timing does not satisfy the claim. The browser's
  interim node display is checked by A-SE-26.
- **Kind.** contract.
