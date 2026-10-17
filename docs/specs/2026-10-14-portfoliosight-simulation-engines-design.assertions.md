# Executable assertions — PortfolioSight simulation engines

Source spec: `docs/specs/2026-10-14-portfoliosight-simulation-engines-design.md`, including
the 2026-10-17 amendments committed as `a77dbf7aa0f56986681a02f58db66b25aa2eed0f` on
`feature/engine-garch` and brought to `main` by `20b292e`. Those amendments specify log-return
fitting, log-space fund scaling followed by simple-space mix scaling, absorbed simulated ruin,
and the matching loss-attribution formula. The owner's numbered Expectations are unchanged.

Prepared with `spec-craft:expectations` and `spec-craft:executable-assertions` 0.3.0 on 2026-10-17.
These are assertion **specifications**, not test code or permission to change either default.
Stable `A-SE-*` IDs identify the future machine checks.

## 0. Scope and handoff

Each assertion belongs to the normative phase in §11, not to a task number in a later plan.
Phases 1 and 2 are the current execution scope. Phase 3 remains part of the full-spec done
floor and must stay visibly pending until separately executed; it must not be marked satisfied
by a disabled Copula option, a mock copula, or omission from the gate.

| Normative phase | Assertion IDs | Boundary |
|---|---|---|
| Phase 1 — Volatility model | A-SE-01 through A-SE-16 | Replay/GARCH, provenance, artifacts, API, page, validation, measured budgets |
| Phase 2 — Diversification measures | A-SE-17 through A-SE-23 | DR² ladders, ENLC, presentation, comparison and stability |
| Phase 3 — Copula, future scope | A-SE-24 through A-SE-28 | Actual fitted dependence, artifacts, integration, validation and measured budgets |

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
- **A-SE-18 — DR² ladder semantics.** S6/F2: optimizing the numerator alone must not break diversification ordering or risk-line honesty.
- **A-SE-19 — ENLC attribution and loser-only entropy.** S6/S7/F7/M5: hedges, zero holdings and undefined loss shares must not produce invented diversification.
- **A-SE-20 — Measure selection and shared state.** S7/S10/F4: the selected word, map and loss details must obey their distinct stated meanings.
- **A-SE-21 — Scores are not presented as holdings.** F3/S6/S7 and §6.1: a mathematically correct number can still make the forbidden claim to visitors.
- **A-SE-22 — Measures comparison evidence.** S8/F8/M3: a change of optimized measure needs comparable measured evidence.
- **A-SE-23 — ENLC seed stability.** S7/F7: unstable tail shares must not be accepted by dropping difficult seeds.
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

### A-SE-18 — DR² ladders preserve feasible monotone levels and truthful risk flags
Phase 2 · unit/ui · S6, F2; §5.2, §5.5, §7, §11

- **Claim.** A DR²-selected ladder is feasible, gains no less DR² while giving up return,
  and truthfully marks every level and hop relative to its risk column.
- **Setup.** Build both `LADDER_MEASURE` variants on both presets and synthetic menus with
  binding and nonbinding risk constraints; include a small enumerable optimization case,
  collapsed columns and a midpoint that loses more than 1% of its column risk.
- **Observation.** Through the actual builder, verify caps, sum-to-one, return floors and risk
  ceilings under inherited tolerances. The small case agrees with an independent constrained
  optimum for the SOCP objective. Every floor's selected point is the highest-DR² eligible
  candidate in that column's pool; successive levels never lose DR² or gain return.
  `on_line` agrees with measured risk; off-line levels are not moved onto the line by
  fabricated coordinates. Hops obey the midpoint rule and the browser honors flagged hops.
  `ladder.z`, `grid.z`, both covariance measures and `refs` match the chosen ladder, with
  `enb_ref = refs.enb`. The two builds really select their respective optimization paths;
  changing only `ladder.measure` on one common ladder fails.
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

### A-SE-20 — Measure selection changes the intended surfaces and survives sharing
Phase 2 · ui/api · S7, S10, F4; §6, §7, §10.3

- **Claim.** A selected measure and engine consistently determine the page's measure
  surfaces and survive a canonical shared-link round trip without rebuilding mixes.
- **Setup.** Actual built tensors with distinguishable DR², ENB and per-engine ENLC values,
  defined and null ENLC, several levels, and an interpolated request with a controlled delayed
  answer. Exercise every available `m`/`e` combination through controls and fresh URLs.
- **Observation.** The measure control is details-only. Switching DR²/ENB updates map colors,
  legend, word and reference from the requested tensor fields without moving mix geometry or
  requesting a rebuild. Selecting ENLC leaves the map/Optimized point on `ladder.measure`,
  labels that map correctly, and uses the selected engine's loss values and hedge IDs in
  details; undefined ENLC shows the specified no-loss message and DR² fallback. While an
  interpolated response is pending, the nearer-level placeholder and eventual response follow
  the active engine/mix, including a selection change before a response arrives. The real
  share validator accepts `m`, canonical URL order/omitted defaults hold, absent `m` resolves
  from the loaded tensor, and a fresh page reproduces state. For DR² and ENB with `ref > 1`,
  independently compute `q = (measure - 1)/(ref - 1)` and check the words immediately below,
  at and above 0.30, 0.50 and 0.75: Poor, Fair, Average and Good follow the specified cut points.
  Legacy `measure/ref` normalization or shifted boundary comparisons must fail.
  Exact disputed ENLC normalization
  and `ref=1` presentation remain deferred in §2 rather than receiving invented constants.
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

- **Claim.** The measures report computes the specified paired ENB-versus-DR² comparison
  from distinct real ladders on the same evaluation scope.
- **Setup.** The §10.1 origin/menu/lookback dataset, both ladder selectors, independent
  hand-computable metric fixtures, and the actual validation script with provider access blocked.
- **Observation.** The script runs both optimization paths on matching inputs and records
  the Optimized and peak mix of every column. Independently check sampled realized-risk
  errors/exceedances, stress/worst-year losses, realized loss concentration, return given up,
  and weight stability. Report both menus, single-fund/bound results, off-line level counts,
  word distribution, the 100-fund DR² measurement, and the required comparison table/verdict.
  Trace metric rows to the evaluated weights and future prices; a heading or copied table
  is insufficient. Aggregation choices are disclosed rather than secretly tuned. A tie leaves
  ENB as the default, and the report cannot itself authorize a default/headline switch.
  Repeat A-SE-16's full target-host workload with Phase 2 enabled, retaining the same
  23-fund build, preset-nightly and warm-range budgets and full path count. Separately
  record the specified 100-fund DR² measurement without inventing a 30-second budget for it.
  Owner screenshot interpretation and unresolved metric-aggregation choices remain in §2.
- **Kind.** contract.

### A-SE-23 — ENLC satisfies the prescribed seed check without hiding failed runs
Phase 2 · validation · S7, F7; §10.4, §13.5

- **Claim.** Defined ENLC values at each tested point have across-seed standard deviation
  at most 0.3 at the explicitly selected tail level.
- **Setup.** Both presets and validation lookbacks, replay/GARCH, every frontier node and
  Optimized point required by §10.4, seeds 20261013–20261017, 2,000 paths per run, initially
  alpha 5%; preserve null/no-loss outcomes separately from numeric samples.
- **Observation.** Recompute the actual tail sets and ENLC for all five seeds and compare
  every defined point with 0.3. If the specified 5% check fails, preserve that evidence and
  perform the allowed complete 10% rerun with the selected alpha consistently recorded in
  method/report/copy; no per-point alpha or omitted seed may pass. Numeric/null transitions
  are reported as unresolved outcomes, not converted to zero or dropped to manufacture a
  standard deviation. A failed final check remains failed.
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
