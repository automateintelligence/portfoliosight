# Gate change: engine 2 (fixed-risk ladders, balanced point, one-year ranges)

Date: 2026-10-13. For the owner and the coordinator.

Instruction (the owner, relayed by the coordinator): get the math right, move quickly, and update
any test, including the frozen gate tests under `assertions/`, that the approved change makes
false. The approved change: hold risk fixed and maximize the exact ENB (ladders from the frontier
mix to the peak), the balanced point as the default, one-year ranges everywhere, a stationary
block bootstrap for them, `POST /v1/range`, and the uncapped reference frontier.

The engine batch did not re-freeze the gate. The page batch (last section) did, on the
coordinator's instruction, after both batches' changes were in: `.frozen` now holds every file
below.

## What changed in the product that the gate reads

- Tensor: new `ladder`, `frontier.range`, `frontier_uncapped`, `entered`, `range_method`,
  `lookback.sample_sha256`;
  `frontier.s_safe` is now the rightmost frontier node with the best bad year (an integer);
  `grid` is the heatmap raster resampled from the ladders (same field names and types as before;
  `grid.w_div` is the peak). `ENGINE_VERSION` 0.2.0; the schema number stays 2 (it already was).
- Engine: the weight-Herfindahl proxy, `optimize.cell`, `suggest.suggested_floor`,
  `suggest.standard_error` and `stats.range6m` are gone.
- API: a sixth route, `POST /v1/range`.
- Page math (`web/src/math/portfolio.ts`): `interpolate` walks `ladder.w` with `ladder.hop`,
  `tSug` reads `ladder.t_suggested`, `riskSliderDomain` reads `frontier.s_safe`.
- Fixtures regenerated, not edited: `tests/fixtures/synthetic_23.parquet` by
  `scripts/make_fixtures.py` (the frame is byte-identical; its metadata now carries the Step 2
  allocation so the fixture tensor holds the entered mix) and `web/fixtures/guide2017_5y.json`
  by the pinned build command.

## Every gate file changed

Ids, commands and timeouts in `manifest.yaml` are unchanged. Claim texts changed for A-PS-17,
18, 19, 21, 24, 33 and 34.

| Gate file | Assertion, leg | Before | After | Property it protects | Why the new form is not weaker |
|---|---|---|---|---|---|
| `tests/test_a_ps_17_mix_invariants.py` | A-PS-17, every vector in the fixture tensor | frontier, raster cells, `w_div`; at least 500 non-null cells | the same plus every `ladder.w[j][l]` and `entered.w`; every ladder level within 1e-6 of its risk line; at least 8 interior levels; at least one cell per column | Every mix shown is real | More vectors (672 ladder mixes) and a new invariant (the risk line). The 500-cell floor counted proxy cells that no longer exist; the vacuity guard is now the level count. |
| `tests/test_a_ps_18_surface_monotone.py` | A-PS-18, the surface | Herfindahl of the proxy monotone along rows and columns; null iff `Y_k > y_front`; `k_div`, `y_div`, `w_div`, `enb_ref` = highest-ENB candidate; exact ENB explicitly not asserted monotone | Every ladder starts at the frontier mix, every level on the risk line, return never rises and exact ENB never falls down a ladder, peak = best level ≥ frontier ENB, collapsed iff gain ≤ 1e-6, levels at or above their floors, hop flags agree with the midpoint risk, `enb_ref` = best level; raster uniform from the lowest peak, null iff `Y_k > y_front`, peak at and below the peak's row, `k_div`, `y_div`, `w_div` name the peak | The "More diversified" end is honest | The old test checked a proxy that is gone. The new one checks the exact measure, which the old spec could not promise, on the same three menus, every level and every cell. |
| `tests/test_a_ps_19_suggested_point.py` | A-PS-19, all three tests | Standard-error walk: bracketing, stop at the first failure, `T_eff` for `ew` | The balanced point: the test's own knee equals `balanced_level` and the stored `t_balanced`/`y_balanced` on all 48 columns (at least half strictly inside the ladder); `t_suggested` = balanced, `default_point` = balanced; bracketing; constructed ladders (concave, convex, exact tie, no gain, gain without return, rescaling); `suggested_level(..., "peak")`; refusals | The default position of the second slider | The owner replaced the rule. The rule is checked exactly on every fixture column and on constructed edge cases, as the old one was. |
| `tests/test_a_ps_21_caps.py` | A-PS-21, fixture weights | frontier, `w_div`, raster cells; at least 500 cells | the same plus every ladder level; at least 480 ladder mixes and one cell per column; new leg: the uncapped frontier starts no higher, tops out no lower, and reaches every capped node's return by its risk | No 23-fund mix above 25%; the caps' cost is shown honestly | More vectors; one added leg. |
| `tests/test_a_ps_24_tensor_contract.py` | A-PS-24, leg 5 | `s_safe` = rightmost maximum of `μ/2 − 1.96σ/√2` over the 377-point curve | `range_method` is the documented bootstrap; for every frontier node, ladder level and the entered mix: bad < typical < good, normal range exactly `μ ∓ 1.96σ`, typical within `0.25σ` of `e^{μ−σ²/2} − 1` (a one-year figure); level 0's range is the node's; `s_safe` = rightmost node with the best bad year | The ranges and the slider's left end are right | The six-month rule is gone by decision. The new leg checks every range in the tensor, not only the slider's end. An unused `import math` was removed. |
| `tests/test_a_ps_33_api_surface_exact.py` | A-PS-33, route set; malformed requests | exactly five routes; 16 malformed tensor paths never reach the store | exactly six routes (`POST /v1/range` added); `GET`/`PUT /v1/range` refused; five malformed range bodies (bad G, bad hash, upper-case hash, unknown lookback, weights summing to 1.1) refused without touching the store | No extra surface; cheap refusals | One route added by decision; the exact-set check is kept and the store-read check now also covers the new route's body. |
| `tests/test_a_ps_34_browser_math_fidelity.py` | A-PS-34, independent ladder; stats leg; `s_safe` leg | The test's own walk of the grid cells by return; `riskSliderDomain().s_safe` = six-month maximum recomputed from the curve | The test's own walk of `ladder.w` with hops (spec 4.11); every ladder level's stats equal `ladder.y`/`ladder.z` with σ on `X_j`; the domain's left end is `frontier.s_safe`, equals the last maximum of `frontier.range.bad`, and moves when the tensor's does | The browser reproduces the engine | Same 200 positions and the same tolerances against a test-owned reference; 672 more nodes in the stats leg; the `s_safe` leg now also proves the page reads the tensor (a patched value moves the domain). Two titles changed accordingly. |
| `tests/test_a_ps_41_first_screen.py`, `_42_phone_layout.py`, `_43_default_view_presets.py`, `_44_heatmap_theme_ramp.py`, `_45_risk_slider_readouts.py`, `_46_div_slider_point.py` | the shared helper `tensorFacts` | `sSafe` recomputed from the six-month rule and required to equal `frontier.s_safe`; `tSug` from `grid.y_sug`, `grid.y_div`, `grid.k_div` | `sSafe` = last maximum of `frontier.range.bad`, required to equal `frontier.s_safe`; `tSug` = `ladder.t_suggested` (0 when `ladder.collapsed`) | The UI tests read the tensor the way the spec says | Field reads only; every UI assertion is unchanged. |
| `tests/test_a_ps_50_stress_cards_coverage.py` | the hand-built two-fund tensor | spec 7 fields of engine 0.1 | the same plus `frontier_uncapped`, `frontier.range`, `ladder` (two levels: frontier mix and most diversified cell), `entered: null`, `range_method`; `s_safe` by the new rule | The page accepts a custom menu's tensor | The page's parser requires every schema key; with two funds the two-level ladder walks exactly the mixes the old return walk did. |
| `manifest.yaml` | claims of A-PS-17, 18, 19, 21, 24, 33, 34 | as frozen | reworded to say the above | Claim text matches the test | Text only. |
| `INTERFACES.md` | page math pin; engine names | `suggest.suggested_floor`; `interpolate`, `riskSliderDomain`, `tAuto` without their sources | `suggest.balanced_level`, `suggested_level`, `DEFAULT_POINT`; the page math's sources named | The contract the product is built to | Names follow the code. |

`docs/specs/2026-10-13-portfoliosight-demo-design.assertions.md` carries the same changes for the
seven reworded ids (summary bullets and detailed sections).

## Left as they are, on purpose

- A-PS-15, 16, 20, 22, 23, 25 to 32, 35 to 40, 47, 48, 51, 53: true as written on the new tensor
  (run below).
- A-PS-45 and the other UI tests still checked the six-month readouts here; the page batch
  below moved them to one year.
- `.frozen`: not regenerated in this batch (see the page batch).

## Runs

Pinned commands from `manifest.yaml`, run from this worktree on 2026-10-13 (project virtualenv;
`web/node_modules` from `npm ci`):

| Ids | Result |
|---|---|
| A-PS-15 to A-PS-31, A-PS-33 to A-PS-51, A-PS-53 | pass |
| A-PS-65 | pass after `ROADMAP.md` kept naming the exact-ENB item (now shipped); the first run failed on that leg alone |
| A-PS-32, A-PS-52, A-PS-60 | not run to completion: they need the secret env (`~/.secrets/portfoliosight.env`); A-PS-60 also builds on production, and A-PS-32's image leg needs a Docker image, neither of which this batch may touch |
| A-PS-54 to A-PS-59, A-PS-61 to A-PS-64, A-PS-66 to A-PS-68 | production legs; not run |

`conductor gate lint`: ok.

One more front-end leg moved because of the engine rather than a field name: A-PS-49 counts
painted pixels on a fixed 10 x 5 grid of canvas samples and needs at least 10. A raster that
painted only each ladder's band (the first form of this batch) left 6 of 50 painted and failed.
The raster now holds the peak in every cell at or below the peak's return, which is what the
ladder program answers there (the return floor no longer binds), and A-PS-49 passes unchanged.

## Page batch: the page reads Engine 2

Instruction (the coordinator, for the owner): the page shows one-year Bad / Typical / Good
everywhere, asks `POST /api/range` for exact weights and falls back to the node ranges, names
the open circle "Optimized" (no separate Suggested tick), draws the uncapped frontier as a
"No limits" ghost, adds the "No limits" / "Reset limits" buttons, forwards `POST /api/range` in
the Worker, accepts `t=grid` and `t=hud` in mailed links, and updates the gate tests that pin
six-month figures or the old marker wording.

| Gate file | Assertion, leg | Before | After | Property it protects | Why the new form is not weaker |
|---|---|---|---|---|---|
| `tests/test_a_ps_34_browser_math_fidelity.py` | A-PS-34, range leg; docstring; `EXPECTED_TITLES` | `range6m(μ, σ)` = `μ/2 ∓ 1.96σ/√2` on random `(μ, σ)` | `yearRange(j, l/(L−1))` equals `ladder.range` at all 48 × 14 nodes and `frontier.range` at level 0 (1e-12); at the same 200 random positions it equals the test's own blend with the hop rule (1e-12) and is ordered; `normalRange(μ, σ)` = `μ ∓ 1.96σ` on 50 random pairs; `range6m` must be gone | The browser's ranges are the engine's | Every node checked exactly, plus the in-between positions against a test-owned reference; the old leg checked one formula on random inputs. One title changed. |
| `tests/test_a_ps_41` to `_46` (shared `tensorFacts`) | `frontAt(s)` bad and typical | `100·(μ/2 − 1.96σ/√2)` and `100·μ/2` at the curve point | `100·lerp(frontier.range.bad, s)` and `100·lerp(frontier.range.typical, s)` | The readouts are the frontier mix's | Same tolerance (0.1 pp), the engine's figures instead of a formula the spec dropped. |
| `tests/test_a_ps_45_risk_slider_readouts.py` | A-PS-45, request check | no `/api/` request of any kind during the moves | the only request allowed is `POST /api/range`, and each one must name the tensor on screen (generation, hash, lookback) with one weight per fund; anything else fails | The sliders never wait on the network | The page now asks for the exact range of the mix on screen once it rests (spec 4.9); the readouts are still checked while the gate's mock refuses it (404), so they cannot depend on it. |
| same | A-PS-45, strip leg | column with the largest mean-return gap between `frontier.w` and `grid.w_div`; strip typical = `μ_div/2`, readout = `μ_front/2` | column with the largest typical-year gap between `frontier.range` and the ladder's top level; strip typical = `ladder.range.typical[j][L−1]`, readout = `frontier.range.typical[j]` | The strip follows the selected mix, the readouts the frontier | Same 0.4 pp gap floor, same tolerance, same "differs" and "Selected mix" checks; one-year figures. Title and docstring now name the one allowed request. |
| `tests/test_a_ps_48_plain_language_disclaimer.py` | A-PS-48, plain labels | "Suggested" | "Optimized" | The open circle has a plain name | The owner renamed the marker; the label is still required on every viewport, theme and preset. The technical name "Estimated central 95% range" is unchanged: the strip's details text keeps it. |
| `tests/test_a_ps_53_caps_inline_validation.py` | A-PS-53, invalid input | no POST of any kind | no POST other than `POST /api/range` | Invalid limits are never sent | A range request carries weights only, never limits; every POST to `/api/tensors` is still counted, and the valid and reset legs are unchanged. |
| `tests/test_a_ps_38_share_validators_template_caps.py` | A-PS-38, new leg; `EXPECTED_TITLES` 6 → 7 | no leg covered `t` beyond `hud`/`light`; no check refused an unknown theme | each of ks-dark, light, hud, grid returns 202 with one mail whose link equals `encode(decode(search))`; seven unknown values (neon, dark, HUD, Grid, grid2, `hud,grid`, empty) return 400 `invalid_url` with no outbound call | A shared link opens the theme it was sent in | Checks only added; every earlier leg unchanged. |
| `tests/test_a_ps_40_worker_routing_surface.py` | A-PS-40, new leg; route lists; gate-header leg; `EXPECTED_TITLES` 8 → 9 | three forwarded routes | `POST /api/range` forwarded with exactly the four headers (the Worker's own `x-ps-gate`), body byte-equal, upstream status and body (409 too) passed back, 413 over 16 KB with no origin call; `POST /api/range/extra` and `/api/v1/range` 404; `GET`/`DELETE`/`PUT /api/range` refused and not forwarded; the gate-header leg sends a range request carrying a client `x-ps-gate` and requires the secret upstream | The Worker exposes no more than the spec | One route added by decision and held to the same checks as `POST /api/tensors`, plus a size cap the tensors route was never tested for. |
| `manifest.yaml` | claims of A-PS-34, 38, 40, 45, 53 | as frozen | reworded to say the above | Claim text matches the test | Text only. |
| `INTERFACES.md` | page math pin; share themes; copy; test ids | `range6m`; three themes in mailed links | `yearRange`, `normalRange`; four themes (the page's codec decides); "Optimized"; `details-bell`, `key-nolimits`, `caps-none` | The contract the product is built to | Names follow the code. |

`docs/specs/2026-10-13-portfoliosight-demo-design.assertions.md` carries the same changes for
A-PS-34, 38, 40, 45, 46 (summary wording only), 48 and 53.

Left as they are: A-PS-49 passes unchanged; the "No limits" curve is clipped to the chart's own
extent so the heatmap keeps its size and painted area. The legacy `grid.y_sug` and `grid.w_div`
stay in the tensor: `web/e2e/smoke.spec.ts` and several gates read them.

Runs (pinned commands, this worktree, 2026-10-13): A-PS-34 and A-PS-38 to A-PS-53 pass (A-PS-52
with the secret env loaded in a subshell). `conductor gate lint` and `conductor gate freeze`:
see the commit that carries `.frozen`.
