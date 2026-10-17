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
- 2026-10-17: the volatility model is fitted and simulated in daily log returns, and its
  `engines.garch` block gains `ruin_paths` (an integer when ready, `null` otherwise) and its
  method `returns: "log"`, `scale: "sd"`, `ruin: "absorb"` (schema, zod and the UI fixture
  accordingly). History replay's figures and every kept field are unchanged.
- `portfoliosight/engine/tensor.schema.v2.json`: the schema 2 contract, byte-identical to
  `tensor.schema.json` on `github/main` (`dddf08b`). `builder.load_schema(version)` returns the
  contract of `schema` 2 or 3 and refuses any other version; the builder still validates what it
  writes against schema 3 only.

## Every gate file changed

| Gate file | Assertion, leg | Before | After | Property it protects | Why the new form is not weaker |
|---|---|---|---|---|---|
| `tests/test_a_ps_50_stress_cards_coverage.py` | A-PS-50, Playwright leg "stress cards custom sgov vtip" | The spec's own mock custom tensor (SGOV + VTIP) copied the fixture's `schema` and had none of the schema 3 blocks, so the page refused it as a schema 3 document and never drew the chart | The same mock tensor carries the schema 3 blocks a custom menu has: `engines` (replay ready with the fixture's method, `garch` "not computed for custom menus", `copula` "not computed for this menu"), `range_default: "replay"`, `shape: null`, and History replay's own figures under `frontier.ranges.replay` and `ladder.ranges.replay` | The `gfc2008` card of a mix wholly in funds that did not exist then shows the exact sentence and no percentage | Every number the mock carried before is unchanged and every observation and must-not of the leg is untouched; the mock now passes the page's stricter schema 3 check instead of a looser one. |
| `.frozen` | A-PS-50 | test-file digest `7d17b169...` | `79a8b3f7...` | Tamper evidence | Re-frozen with `conductor gate lint` (ok) and `conductor gate freeze`; `conductor gate verify` reports the baseline intact. Only this entry moved. |
| `tests/test_a_ps_56_presets_tensors_from_r2.py` | A-PS-56, both schema checks (the `guide2017` 5y tensor and the tensor of the menu with FIENX) | Each tensor was validated against `portfoliosight/engine/tensor.schema.json`, now the schema 3 contract, so a schema 2 tensor from production's engine 0.2.0 failed | Each tensor is validated against the shipped contract its own `schema` field names, loaded by `portfoliosight.engine.tensor.load_schema(schema)`: `tensor.schema.json` for 3, `tensor.schema.v2.json` for 2; any other `schema` fails the test | Production's tensors match the repo's contract for the schema they declare, while production serves engine 0.2.0 (until the 0.3.0 switch-over) and after any rollback to it | Each check is as strict as before for its version (the same `check_schema`, "constrains something" and zero-errors assertions), and it adds one: the loaded contract's own `schema` const equals the document's. A document of schema 2 cannot pass the schema 3 contract or the reverse (`additionalProperties: false` and the `schema` const), and a version without a shipped contract fails. Every other observation and must-not is untouched. |
| `.frozen` | A-PS-56 and the assertions source | test-file digest `154e2219...`; source digest `c8dc95c0...` | `73b5b0db...`; `4c5a9a4b...` | Tamper evidence | Re-frozen with `conductor gate lint` (ok) and `conductor gate freeze`; `conductor gate verify` reports the baseline intact. Only these two entries moved. |
| `tests/test_a_ps_27_custom_build_queue.py` | A-PS-27, leg (1), the 200 body | `tensor["schema"] == 2`, false since the engine writes schema 3 | `_assert_written_contract(tensor, ...)`: `schema` is exactly 3 and the tensor validates with zero errors against `load_schema(3)` (`tensor.schema.json`), whose own `schema` const must be 3; the pinned interface in the docstring says so | The custom build serves a tensor of the contract the engine writes | It pins one exact version as before (3 for 2) and adds a full validation against that version's shipped contract, which the old check did not make. Every other observation and must-not is untouched. (2026-10-17) |
| `tests/test_a_ps_30_generation_publish_atomic.py` | A-PS-30, leg (3), each of the 12 real tensors of store B | `t["schema"] == 2`, false since the engine writes schema 3 | `t["generation"] == g` kept, and `_assert_written_contract(t, ...)`: `schema` exactly 3 and zero errors against `load_schema(3)`; the pinned interface in the docstring says so | Every preset tensor of a generation is of the contract the engine writes, with `asof = D_G` | As for A-PS-27: one exact version, plus a full validation of each of the 12 tensors. The placeholder documents the fake `build_fn` writes (`"schema": 2`, `gate_placeholder`) are not product output and are not checked; they are unchanged. (2026-10-17) |
| `tests/test_a_ps_50_stress_cards_coverage.py` | A-PS-50, Playwright leg "stress cards custom sgov vtip" | The mock custom tensor's `engines.garch` had `status`, `reason`, `method` | It also carries `ruin_paths: null`, which the page now requires of every `engines.garch` block (an unavailable model counts no lost paths) | As above | One key the schema 3 page requires; no number and no observation changed. (2026-10-17) |
| `.frozen` | A-PS-27, A-PS-30, A-PS-50 | test-file digests `4c3cbdbe...`, `dd476039...`, `79a8b3f7...` | `a7296662...`, `037f9987...`, `f1805b4f...` | Tamper evidence | Re-frozen once for the three with `conductor gate lint` (ok) and `conductor gate freeze`; `conductor gate verify` reports the baseline intact. Only these three entries moved. (2026-10-17) |

For A-PS-27 and A-PS-30 the manifest claims and the assertions file name no schema version, so
they are unchanged; `INTERFACES.md` (the engine's contract files) now says that these two require
a freshly built tensor to declare schema 3 and validate against `load_schema(3)`.

For A-PS-50, the manifest claim, `docs/specs/2026-10-13-portfoliosight-demo-design.assertions.md`
and `INTERFACES.md` say "a mock custom tensor (SGOV + VTIP)" and nothing about its schema, so they
are unchanged. For A-PS-56, the manifest claim says "schema-valid" and names no file or version,
so it is unchanged; the assertions file (claim and setup) and `INTERFACES.md` (the engine's
contract files and `tensor.load_schema(version)`) named `tensor.schema.json` alone and now name
the contract chosen by the document's `schema`.

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
- A-PS-56 (live: production's tensors validate against the repo's contract) was changed (table
  above) and is not run here: it reads production and posts a build there. It still collects
  (`pytest --collect-only`: 4 tests). The version selection it relies on is unit-tested in
  `tests/engine/test_builder.py`: a schema 2 tensor from engine 0.2.0 validates under the schema 2
  contract and is refused by schema 3's, and the UI fixture the reverse.
- `web/e2e/smoke.spec.ts` (DoD-21, the live smoke run) validated production's preset tensor
  against `tensor.schema.json` alone, so it failed the same way while production serves schema 2.
  It is not a gate file of this run; since 2026-10-17 it selects the contract by the tensor's
  `schema` the same way (`load_schema(schema)`, any other version fails). Not run here: it reads
  production.
- A-PS-24 (tensor contract) after the log-return change: passes as written (58 s); the UI fixture
  is the pinned invocation's output again.
