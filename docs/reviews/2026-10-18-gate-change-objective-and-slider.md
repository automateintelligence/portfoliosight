# Gate change: the preference contract and the slider as allowed sacrifice

Date: 2026-10-18 (owner timezone). For the owner and the run leader. Recorded by Claude (Fable 5.1).

Instruction (the owner, 2026-10-18, later the same day as the morning's objective clarification): the
product's optimization is a two-stage preference contract (Stage A `w_R = argmax U`,
`U = 0.60 B + 0.30 T + 0.10 G`, over feasible mixes at or inside the risk ceiling; Stage B the most
diversified admissible mix found, with guards `10 / 25 / 50 bp` on Bad / Typical / Good, an allowance on
`U`, and a veto on both Bad and Typical lower); the diversification slider is the allowed `U`
sacrifice, default `w_R`, cap 2.5 bp; the white line and the Optimized point are deferred to C8; the
ENB arm is gated on DR²'s positive conditional-model evidence; `ES_2.5` is added as a details-only
diagnostic and DR²'s covariance is named; the order of work is harness → experiment → range API →
UI engine selector with the deployable Phase 1 milestone after C8. The spec records this as §3 item 7
(D1–D6), §5.5, §6, §7, §10 item 6, §13 items 19–23; the assertions source carries the changes below.

**The frozen tests under `assertions/` are unchanged by this document.** Nothing under `assertions/`
was edited, and no test was run. The frozen gate must be re-frozen through the installed Conductor
workflow (`conductor gate lint`, `conductor gate freeze`, with the PR that carries `.frozen`) by the
run leader (spec §11; plan `docs/plans/2026-10-17-simulation-engines-conductor-plan.md`, "Gate
amendment handoff"). A-SE-29 and A-SE-32 tests are linted and frozen into the run gate before
`ledger phase-done <6b-issue>`; A-SE-18, A-SE-20, A-SE-22, A-SE-23, A-SE-30 and A-SE-31 re-freeze
after C8 is recorded and before phases 7–9 are accepted. The spec,
`docs/plans/2026-10-18-return-optimization-experiment-protocol.md` and
`docs/plans/2026-10-17-simulation-engines-conductor-plan.md` record the same owner decisions of
2026-10-18; the protocol numbers them D1–D10, the spec and plan D1–D6; cross-reference by section,
never by D-number.

## What changes in the product that the gate reads

- The ladder at a risk column is no longer "mixes with risk exactly `X_j`, from the frontier mix down
  to the most diversified mix found" but "the most diversified admissible mix found at each of 14
  allowances `a_l = (l/13)·cap`, from `w_R` at `a = 0`"; every level sits at `σ ≤ X_j`.
- The ladder is per (variant, engine): `variants[m].ladders[e]`, `variants[m].grid[e]`; level 0 is
  the same `w_R` for both variants under one engine; `refs` per variant over every carried engine.
- New per-level fields: `allowance`, `sigma`, `bad/typical/good/u/es`, `sacrifice`, `guards`; new
  tensor block `objective`; new `es` in `frontier.ranges`, `entered.ranges` and `/v1/range`.
- Removed from schema 4: `on_line`, `t_balanced`, `y_balanced`, `y_suggested`, `default_point`,
  `grid.y_sug`; `t_suggested` kept and 0 everywhere; `ladder.ranges` replaced by each engine's own
  ladder figures.
- The raster cell `(j, k)` is the highest-measure level with `y ≥ Y_k`, never a blend.
- URL `d`: same key, same shape, `d=0` the default (written), legacy `auto` reads as 0.
- The engine switch now moves the selected holdings, the ladder and the map (S3 narrowed; owner to
  confirm, spec §13 item 22).

## Every assertion changed or added in the source

Source: `docs/specs/2026-10-14-portfoliosight-simulation-engines-design.assertions.md`. No ID is
renumbered; A-SE-24–28 (parked Phase 3) are untouched; A-SE-01–17, 19, 21 are untouched in text
(A-SE-10 and A-SE-12 have reconciliation notes in the source's §2, items 9 and 11, not text changes).

| Assertion | Before | After | Property preserved | Reason the new form is not weaker |
|---|---|---|---|---|
| A-SE-18 | "DR² ladders preserve feasible monotone levels and truthful risk flags": caps, sum-to-one, return floors and risk ceilings; the small case equals the SOCP optimum; each floor's point is the highest-DR² eligible pool member; successive levels never lose DR² or gain return; `on_line` agrees with measured risk; hops by the midpoint-risk rule; `z`, `grid.z`, both measures and `refs` match; two builds take their own solve path | "Sacrifice ladders are admissible at every level, monotone in the measure, and open on `w_R`": at every level and engine, caps, sum-to-one, `σ ≤ X_j + 1e-6` with `sigma` recomputed; recomputed `B/T/G/U/ES_2.5` equal the stored values; every guard, the allowance and the veto hold against `w_R`'s unrounded figures; `sacrifice ∈ [0, allowance]`; `guards` names exactly the binding constraints; level 0 = `w_R`, same in both variants under one engine; the small case equals an exhaustive oracle's Stage A and Stage B; measure non-decreasing down the ladder; `collapsed` and `hop` exactly where defined (hop = midpoint blend leaves `A(a_{l+1})`); the browser honors hops; `z`, `grid[e].z`, both measures and `refs` (max over carried engines) match; knee fields and `on_line` absent; raster cells are levels; the two measures take their own Stage B and the two engines their own Stage A; a D3 leg added at C8 | Every mix the ladder shows is real, feasible, honestly placed and monotone in what the slider promises | The feasibility, arithmetic and monotonicity oracles are kept and widened (every level under every engine, exact `B/T/G` recomputed, guards checked). "Return never rises" is dropped because the contract does not promise it; "measure never falls" and "`U` never falls below `U_R − a_l`" replace it and are both by construction. The risk-line flag is dropped because no level is required to be on the line; the ceiling check replaces it everywhere. A fabricated placement still fails (recomputed `sigma`). |
| A-SE-20 | "Measure selection changes the intended surfaces and survives sharing": details-only control; switching DR²/ENB updates map, legend, word and reference without moving mix geometry; ENLC selection leaves the map on `ladder.measure`; pending interpolated response follows the active engine/mix; share validator accepts `m`; `q = (measure−1)/(ref−1)` words at the cut points | "Measure and engine selection select actual holdings on the sacrifice ladder and survive sharing": loading without `d`, with `d=auto` or `d=0` lands on `w_R` and writes `d=0`; switching `m` at `d = 0` moves nothing and at `d > 0` changes the holdings and every holdings-derived surface from `variants[m].ladders[e]`/`grid[e]`; switching `e` changes the ladder to the engine's and moves the holdings where the engines differ, keeping `d`, clamping `r`, leaving axes/ceiling/entered mix fixed; trade-off line checked (signed differences against `w_R`, "Trade-off vs no-trade-off mix", "No trade-off" at `d = 0`, estimated while pending); slider left end "No trade-off", chosen mix "Selected mix", never "Optimized" or "best-return" for `w_R`; ENLC and pending-response legs kept; validator accepts `m`, `e`, `d`; `d` always written; words at the cut points with `ref` over carried engines; relabelling fails | A selection selects its actual holdings, every surface describes one mix, and a link reproduces it | Every earlier leg is kept (details-only control, ENLC behaviour, pending-response guard, cut points, validator, round trip). "Without moving mix geometry" is replaced because the owner's contract makes the holdings follow the measure (at `d > 0`) and the engine; the new legs check that the move is the right one and that nothing else moves. The old form would have passed a page that relabels one optimizer's holdings as another's at `d = 0`; the new form requires actual holdings at every `d` and under every `e`. |
| A-SE-22 | "The measures report compares both actual ladder methods": the script runs both optimization paths and records the Optimized and peak mix of every column; realized-risk errors/exceedances, stress/worst-year losses, concentration, return given up, stability; off-line level counts; the 100-fund DR² measurement; a tie leaves ENB | Header note "Scope reconciled after C8": the comparison points become `w_R` and the cap end of each column's sacrifice ladder; the arms are the protocol's (ENB only if D4 gates it in, else "unevaluated"); realized metrics unchanged as reporting requirements; "levels inside their ceiling by more than `1e-6`" replaces the off-line count; the default-change bar is "confirmed worthwhile benefit" (realized benefit support in both menus and no material-harm risk cell, protocol §7); not frozen as a test until C8 | The report compares distinct real selections on one scope, with disclosed aggregation, and cannot authorize a default switch | Nothing is removed from what the report must measure; the points it measures on are the ones the product now shows. Marking it "not frozen until C8" is a statement of the dependency, not a relaxation: freezing the fixed-risk version would freeze a comparison of mixes the product no longer selects. |
| A-SE-23 | "ENLC satisfies the prescribed seed check": every frontier node and Optimized point, seeds 20261013–20261017, 2,000 paths, alpha 5%, sd ≤ 0.3 | Header note "Scope reconciled after C8": the tested points are each frontier node, each column's `w_R` under each engine, and the cap end under each shipped measure; threshold, seeds, paths and alpha rule unchanged; the seed-20261013 weights are re-evaluated, never re-selected, under the other seeds | Tail-share noise is estimated on the points the page shows, with no seed dropped | Same threshold and procedure on more points. The re-evaluate-not-re-select rule closes a gap the fixed-risk version did not have (the knee did not depend on the draw; `w_R` does). |
| A-SE-29 (new) | — | "The selector obeys the owner's preference contract": the A/B example (`U(B) − U(A) = +0.01794`, B wins, strict lexicographic fails); guards compared to unrounded `w_R` figures, at/inside/outside each guard; the all-above candidate never excluded; the joint Bad-and-Typical deterioration inadmissible at every cap; Bad-only and Typical-only within guard admissible; caps 0/2.5/5/10 bp: measure non-decreasing, `U` non-increasing, nested admissible sets, `sacrifice ∈ [0, cap]`; the measure cannot change `w_R`, `U_R`, the guards or the allowance-0 selection; the cycle fixture acyclic in all six orders with Stage A ties against the global maximum `U` (B, T, G, weights); a Stage B tie set within `1e-12` of the admissible maximum measure resolves by higher `U`, then B, T, G, then weights; a candidate dominated on (B, T, G) is removed before Stage A and is never the Stage B pick at any cap however high its measure; an enumerable 3-fund menu equals an exhaustive filter, Stage A and Stage B oracle | The owner's stated preference, and nothing else, decides the selection | New property; the oracles are hand-built tables and an exhaustive enumeration, independent of production. |
| A-SE-30 (new) | — | "The default landing point is `w_R` on both presets and every lookback, its rendered figures equal `w_R`'s exact figures, and the old-default/frontier/new-landing comparison is printed": on both presets, every lookback, both engines, every column and interpolated positions, the landing weights equal level 0 (or the blend of two level 0s) and their exact Bad and Typical equal `w_R`'s; the TSP 5y fixture (saved artifact and its successor) at two positions kept separate: the default landing (`d=auto`, risk 9.1%) prints old default Bad −10.5% / Typical +7.4% against the frontier mix at that risk −7.9% / +8.2% and the new landing; the investigation position (`r=36.382658` ≈ 12.53% risk) prints `d=1` −15.4 / +7.9 / +33.7 against `d=0` −12.4 / +9.8 / +34.5, word Average → Good; landing `U ≥` frontier `U`; F11's "worse than another mix on screen" leg (a landing below the frontier mix on both Bad and Typical) is recorded as a C8 finding, not asserted and not hidden; "Selected mix" and "No trade-off" labels, never "Optimized" or "best-return" for `w_R`; reads rendered holdings, not the store's intent | The page opens on the no-trade-off mix (`w_R`) at the visitor's risk, and the 2026-10-18 TSP default cannot recur | New regression property derived from the live observation; it fails a knee, a peak, a cached position or another variant's or engine's mix. |
| A-SE-31 (new) | — | "`ES_2.5` is the mean of the worst 2.5% of years and steers nothing": equals the independent mean of the 50 lowest compounded years on the consumed draw in every block and in `/v1/range`; `≤ Bad`; equals the compounded return on a constant portfolio; single-fund identity under `replay`; perturbing every `es` changes no `w_R`, level, guard, word or headline; details-only rendering with `data-testid="details-es"`; wrong tail size, additive year or wrong engine fails | The one new figure is right, read correctly and inert | New property. |
| A-SE-32 (new) | — | "Prices after an origin cannot change that origin's selection or prediction": on a synthetic timeline in the actual `scripts/backtest_ranges.py`, an after-origin price mutation leaves byte-identical the shape, pool, moments, frontier nodes, `w_R`, each arm's selection at every allowance the harness evaluates under each engine and measure (not the 14-level product ladder), predictions and tuning inputs, while changing realized outcomes; an at-or-before mutation changes the prediction or selection; provider access blocked; one origin set and exclusion rule for validation and experiment | The harness's evidence is out-of-sample for selection as well as prediction | Extends A-SE-14's prediction leg (unchanged) to selection and to the experiment's arms; the harness is first in the owner's order, so this is the first assertion the next work must meet. |

Source §2 (deliberately not encoded) gains items 9–13: level zero versus the frontier node (D3);
guards between levels (midpoint only; C3 discloses); engine switch and chart geometry (A-SE-12 holds
for Phase 1 tensors; S3 narrowed pending §13 item 22); build cost (no budget invented); the §10.6
DR²-covariance oracle (unit tests and protocol §8's estimator check, not a gate assertion). The selection
rule is not among them: the protocol's §2 (amended 2026-10-18) and spec §5.5 state one two-stage rule
for the experiment's arm and the product; C8 decides the measure and the white line only.

## Frozen gates this amendment makes false (for the run leader; none edited here)

Two frozen gates are affected. None was edited and no test was run.

**This spec's run gate.** The frozen gate for this spec is not under the main checkout's
`assertions/`; it lives in the run worktree at
`.worktrees/run-2026-10-14-portfoliosight-simulation-engines-design-99dcbc03/assertions/2026-10-14-portfoliosight-simulation-engines-design-99dcbc03/`
(`manifest.yaml:138-185` holds A-SE-18 to A-SE-23; A-SE-29 to A-SE-32 have no frozen test yet).
Four frozen files or legs encode the meanings this amendment replaces. They stay red against
schema-4 behaviour until re-frozen on the schedule above (A-SE-18, A-SE-20, A-SE-22 and A-SE-23
re-freeze after C8 is recorded and before phases 7–9 are accepted); they are not edited to pass
in the meantime.

| Frozen file / leg | Before (frozen) | After (source) | Property preserved | Reason |
|---|---|---|---|---|
| `tests/test_a_se_18_dr2_ladders.py`; manifest A-SE-18 claim | "A DR²-selected ladder is feasible, gains no less DR² while giving up return, and truthfully marks every level and hop relative to its risk column"; the test reads `ladder.on_line` (`:323`) | the A-SE-18 row above: admissible levels at `σ ≤ X_j`, measure non-decreasing, level 0 = `w_R`, no `on_line` | every shown mix is real, feasible, honestly placed and monotone in the measure | schema 4 removes `on_line` and the fixed-risk "giving up return" order; the ceiling check and recomputed `sigma` replace them |
| `tests/test_a_se_20_measure_shared_state.py`; manifest A-SE-20 claim | "A selected measure and engine consistently determine the page's measure surfaces and survive a canonical shared-link round trip without rebuilding mixes"; legs assert unchanged mix geometry on a measure switch | the A-SE-20 row above: measure and engine select actual holdings on the sacrifice ladder | one mix behind every surface; a link reproduces it | under the contract the holdings follow the measure (`d > 0`) and the engine, so "measure surfaces" without moving holdings is no longer the behaviour |
| `tests/test_a_se_22_measures_evidence.py`; manifest A-SE-22 claim | "The measures report computes the specified paired ENB-versus-DR² comparison from distinct real ladders on the same evaluation scope"; reads the peak and `t_suggested` points and `ladder.on_line` (`:638`) | the A-SE-22 row above: the protocol's arms at `w_R` and the cap end; ENB only if D4 gates it in | distinct real selections compared on one scope; no default switch authorized by the report | the knee, the peak and `on_line` are gone from schema 4; the comparison points are the ones the product now shows |
| `tests/test_a_se_23_enlc_seed_stability.py`; manifest A-SE-23 | tested points are frontier nodes and the knee (`t_suggested`) and peak points | the A-SE-23 row above: frontier nodes, `w_R` per engine, cap end per measure; seed-20261013 weights re-evaluated, never re-selected | same threshold, seeds, paths and alpha rule | `t_suggested` is 0 everywhere in schema 4, so the knee point no longer exists |

**The demo spec's gate.** Under `assertions/` (the demo spec's gate), the following read the
fixed-risk ladder, the knee or the `d=auto` default and will fail on a schema-4 tensor or the
amended page; they are listed from the 2026-10-13 gate-change record and the spec's §12 "gate
churn" item, not from a run:

| Gate file | Leg that reads the old meaning |
|---|---|
| `tests/test_a_ps_17_mix_invariants.py` | every ladder level within `1e-6` of its risk line |
| `tests/test_a_ps_18_surface_monotone.py` | every ladder starts at the frontier mix, every level on the risk line, return never rises down a ladder, peak = best level, raster from the lowest peak |
| `tests/test_a_ps_19_suggested_point.py` | the balanced point (`balanced_level`, `t_balanced`, `t_suggested` = balanced, `default_point`) |
| `tests/test_a_ps_24_tensor_contract.py` | level 0's range is the node's |
| `tests/test_a_ps_34_browser_math_fidelity.py` | every ladder level's stats with `σ` on `X_j`; `t = 1` the interpolated peak |
| `tests/test_a_ps_38_share_validators_template_caps.py` | `encode(decode(search))` with `d=auto` in the fixture links (canonical form now `d=0`) |
| `tests/test_a_ps_41`–`_46` (`tensorFacts`) | `tSug` from `ladder.t_suggested` (now 0 everywhere; `d=auto` lands on level 0) |
| `tests/test_a_ps_45_risk_slider_readouts.py` | strip typical = the ladder's top level; the readouts' meaning under D3 |
| `tests/test_a_ps_46_div_slider_point.py` | the Optimized position as the default; `details-enb` at the bottom end ≥ at the top (still true: measure non-decreasing) |
| `tests/test_a_ps_49_heatmap_*` | painted-pixel count on a raster that now holds levels, not blends |
| `tests/test_a_ps_50_stress_cards_coverage.py` | the hand-built two-fund tensor's `ladder` fields (schema 4 adds and removes fields) |
| `manifest.yaml`, `INTERFACES.md` | claim texts and the page-math pin (`suggest.balanced_level`, `DEFAULT_POINT`) |

A-SE-10's "level zero equals its frontier node" leg and A-SE-12's "no chart-geometry change" leg are
true for Phase 1 (schema-3) tensors and are reconciled at C8 (source §2 items 9 and 11), not changed.

## Left as they are, on purpose

- A-SE-01–09, 11, 13–17, 19, 21: true as written under the amendment.
- A-SE-24–28: parked Phase 3; untouched by instruction.
- The Expectations gain S14 and F11 (spec); S13's "any separate Safer promise" is replaced by "no
  separate promise beyond the guards"; no S/F/M is removed.

## Runs

None. This document records specification and assertion-source changes only; the pinned gate commands
were not run, no tensor was built and no fixture was regenerated. The run leader's re-freeze PR carries
the runs.
