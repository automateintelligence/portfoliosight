# Gate change: tensor schema 3 (volatility model, engine 0.3.0)

Date: 2026-10-16. For the owner and the coordinator.

Instruction (plan `docs/plans/2026-10-16-simulation-engines-phase1-plan.md`, Phase 2, relayed by
the coordinator): build the volatility model (`garch`) beside History replay, bump the engine to
0.3.0 and the tensor to schema 3, regenerate the UI fixture, teach the page to read schema 2 and
3; update and re-freeze any frozen gate test the change makes false.

## What changed in the product that the gate reads

- `portfoliosight/engine/tensor.schema.json`: schema 3. `schema` is `3`; new required blocks
  `engines`, `range_default`, `shape` and per-engine `ranges` in `frontier`, `ladder` and
  `entered`. Every kept field (`frontier.range`, `frontier.s_safe`, `ladder.range`,
  `entered.range`, `range_method`, `enb_ref`, ...) keeps its name and History replay's figures.
- `web/fixtures/guide2017_5y.json`: rebuilt with the pinned invocation. Apart from `schema`,
  `engine_version`, `generation` and one added note, every kept field is byte-identical to the
  0.2.0 fixture; the universe hash is unchanged (`HASH_SCHEMA = 2`).
- `web/src/api/tensor.ts`: the page reads schema 2 or 3. A schema 3 document must carry the new
  blocks, a schema 2 document must not.

## Every gate file changed

| Gate file | Assertion, leg | Before | After | Property it protects | Why the new form is not weaker |
|---|---|---|---|---|---|
| `tests/test_a_ps_50_stress_cards_coverage.py` | A-PS-50, Playwright leg "stress cards custom sgov vtip" | The spec's own mock custom tensor (SGOV + VTIP) copied the fixture's `schema` and had none of the schema 3 blocks, so the page refused it as a schema 3 document and never drew the chart | The same mock tensor carries the schema 3 blocks a custom menu has: `engines` (replay ready with the fixture's method, `garch` "not computed for custom menus", `copula` "not computed for this menu"), `range_default: "replay"`, `shape: null`, and History replay's own figures under `frontier.ranges.replay` and `ladder.ranges.replay` | The `gfc2008` card of a mix wholly in funds that did not exist then shows the exact sentence and no percentage | Every number the mock carried before is unchanged and every observation and must-not of the leg is untouched; the mock now passes the page's stricter schema 3 check instead of a looser one. |
| `.frozen` | A-PS-50 | test-file digest `7d17b169...` | `79a8b3f7...` | Tamper evidence | Re-frozen with `conductor gate lint` (ok) and `conductor gate freeze`; `conductor gate verify` reports the baseline intact. Only this entry moved. |

The manifest claim, `docs/specs/2026-10-13-portfoliosight-demo-design.assertions.md` and
`INTERFACES.md` say "a mock custom tensor (SGOV + VTIP)" and nothing about its schema, so they
are unchanged.

## Left as they are, on purpose

- A-PS-24 (tensor contract): true as written. It reads the kept fields and the shipped schema;
  `range_method` is still the stationary block bootstrap, the UI fixture is the fresh build's
  output, and the schema still refuses a tensor without `grid.z`. Its 90 s build bound now
  includes the volatility model's fit and simulation: it passed at load average 15 (one pinned
  build there takes 64 s wall), and failed only at load averages above 50 on the shared laptop,
  where the 0.2.0 engine slows several-fold too.
- A-PS-29 (universe hash): true as written; the hash keeps `{"schema": 2, ...}` through
  `HASH_SCHEMA`, separate from the tensor's `SCHEMA_VERSION = 3`.
- A-PS-17, 18, 19, 21, 34, 35, 36, 37, 41-49, 51, 53: they read the kept fields, the moments or
  the weights, which did not move; all pass (A-PS-45 and A-PS-47 each lost one leg to a
  page-load timeout at load average 50 and passed on re-run).
- A-PS-25 (engine pure and fully covered): true as written. The new module `shape.py` imports
  nothing the scan forbids and reads the QSE lock with `importlib.resources`; the engine stays
  at 100% line coverage.
- A-PS-56 (live: production's tensor validates against the repo's schema): not run here (it
  posts a build to production). Production serves engine 0.2.0 (schema 2) until Phase 3 deploys
  0.3.0, so it fails against the schema 3 file in that window, and again after any rollback to
  0.2.0. Left for the coordinator to decide (accept the window, or validate a schema 2 tensor
  against the schema 2 contract).
