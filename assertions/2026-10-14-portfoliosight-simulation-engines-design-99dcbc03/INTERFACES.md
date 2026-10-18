# Simulation-engine gate interfaces

Worker reference, 2026-10-17. The [design spec](../../docs/specs/2026-10-14-portfoliosight-simulation-engines-design.md)
is normative; the [assertion specifications](../../docs/specs/2026-10-14-portfoliosight-simulation-engines-design.assertions.md)
and [28-entry manifest](manifest.yaml) define the mechanical floor. Passing tests does not
approve the product, resolve the spec's open interpretations, or authorize changing defaults.
The linked frozen tests are the exact schema/call reference; this file does not replace them.

## Scope and execution

| IDs | Normative scope | Stop condition |
|---|---|---|
| A-SE-01–16 | Phase 1: replay/GARCH | All assigned claims and required phase checks verified |
| A-SE-17–23 | Phase 2: diversification | All assigned claims and required phase checks verified |
| A-SE-24–28 | Phase 3: Copula, **PARKED** | Requires a separate owner-approved unpark |

The current request ends with verified Phases 1/2 and a durable checkpoint. Keep Phase 3
pending in the full-spec gate; do not expand scope to make every manifest entry green or
claim full-spec completion. Human report review and default switches remain separate.

The main project root is `/home/danie906/programming/portfoliosight`. For this registered run:

```sh
PS_RUN_KEY=2026-10-14-portfoliosight-simulation-engines-design-99dcbc03
PS_PROJECT_ROOT=/home/danie906/programming/portfoliosight
PS_RUN_WORKTREE="$PS_PROJECT_ROOT/.worktrees/run-$PS_RUN_KEY"
PS_CONDUCTOR_BIN=/home/danie906/.codex/plugins/cache/automateintelligence/conductor/0.10.0/bin/conductor
cd "$PS_RUN_WORKTREE"
export CONDUCTOR_HOME="$PS_RUN_WORKTREE"
export CONDUCTOR_GATE_SLUG="$PS_RUN_KEY"
# After preparing this checkout's own Python environment:
export PATH="$PS_RUN_WORKTREE/.venv/bin:$PATH"
"$PS_CONDUCTOR_BIN" assert run --level spec
```

That command runs the whole floor, including parked prerequisites. The installed assertion
runner lacks `--run`; the two environment variables select its checkout and gate. Every
run-state operation must instead carry the explicit run key via its supported `--run` form.
The executable above matches this setup's installed skill; after a plugin upgrade resolve
the CLI from the newly installed `conductor:start` skill instead of assuming it is on PATH.
Use registered `run show --run` / `gate-dir --run` names: legacy `run-branch name <spec>`
returns an unhashed name. Never infer authority or another run's state from the current folder.

Each manifest command pins one file with `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`, `--noconftest`
and `-p no:cacheprovider`. Run that exact command for a focused check; no passing skips or
ancestor `conftest.py` helpers. Missing dependencies/data/host context are unmet prerequisites.

At this checkpoint the main-root `.venv` lacks `arch`; `.worktrees/engine-garch/.venv` contains
`arch==8.0.0`; the integration worktree has no `.venv`. Prepare each phase checkout's own
environment from its own `pyproject.toml` and declared API/dev extras. Do not borrow another
branch's editable installation. Frozen helpers check that product imports resolve inside the
checkout containing the tests; their fallback interpreter discovery does not install packages.
UI checks require local Vitest/jsdom dependencies. Node discovery accepts `PS_GATE_NODE`,
then `NODE`, then PATH and optional nvm candidates, checking the installed tool engine ranges.

The [reconciliation record](../../docs/reviews/2026-10-17-simulation-engines-conductor-reconciliation.md)
records an unattended-driver blocker: generated `owner-busy` omits the run key with two active
runs and returns exit 2. No driver was installed; do not describe this checkpoint as scheduled.

## Product calls pinned by the tests

Names below are **required interfaces**, not evidence that they are implemented in this run.
The integration checkout still has the baseline builder. `feature/engine-garch` contains the
full builder, shape and log-range interfaces; its API cache still has the old interface.
Engine-aware service integration, measures and structured reports remain implementation work.

| Surface | Call/data contract | Exact checks |
|---|---|---|
| Builder | `build_tensor_full(TensorInputs(...), workers=1)` → `BuildResult.tensor`, `.models[engine]`, `.artifacts[engine]`; `TensorInputs.engines=("replay", "garch")`, `.garch_artifact` for reuse | [04](tests/test_a_se_04_shape_history.py), [10](tests/test_a_se_10_tensor_contract.py) |
| Shape | `shape_panel(returns, included, asof)` → panel with `.frame`/digest; `fit_shape(panel, splice_dates=None)` → artifact; `simulate_panel(artifact, paths=2000, horizon=252, seed=...)` → log-return panel | [04](tests/test_a_se_04_shape_history.py), [07](tests/test_a_se_07_shared_draws.py) |
| Shape artifact | Fund order, parameters/statuses, `.sample_sha256`, `.pool`, `.pool_rows`, `.outliers`, `.unavailable_reason`; pool is absent when unavailable | [04](tests/test_a_se_04_shape_history.py), [06](tests/test_a_se_06_splice_guard.py) |
| Ranges | `range_model(sample, mu_s, cov, seed=...)`; `garch_range_model(log_panel, mu_s, cov, seed=...)`; `simulated_years(model, weights)` and `one_year_ranges(model, weights)` dispatch by model | [07](tests/test_a_se_07_shared_draws.py), [08](tests/test_a_se_08_two_space_scaling.py), [09](tests/test_a_se_09_absorbed_ruin.py) |
| Numerical intermediates | GARCH model `.panel`, `.mean`, `.sd`, `.level_mean`, `.level_cov`, `.mu_s`, `.cov`; `_step_one`, `_levelled`, `_garch_terms` are inspected by the frozen oracle | [08](tests/test_a_se_08_two_space_scaling.py) |
| Service | `RangeModels(store).get(generation, universe_hash, lookback, engine="garch")`; actual `jobs.build_from_store` / `TestClient(create_app)` / `/v1/range`; optional request `engine`, response `engine` and `loss_sources` | [11](tests/test_a_se_11_api_artifact_contract.py) |
| Service caches | `_models`: eight lookback models; at most two retained float32 simulated panels, keyed by shape/engine; future copula test observes `_panels` LRU | [11](tests/test_a_se_11_api_artifact_contract.py), [25](tests/test_a_se_25_copula_artifacts.py) |
| DR² | `engine.measures.dr2(w, cov)` and `portfolioMath(tensor).stats(w).dr2` | [17](tests/test_a_se_17_dr2_identities.py) |
| DR² ladders | `ladder.Dr2Program(mu, cov, lo, hi)`; `.solve(risk, floor, start)` / `.candidate(w)`; `builder.LADDER_MEASURE` selects real `enb` or `dr2` optimization | [18](tests/test_a_se_18_dr2_ladders.py) |
| ENLC | `engine.loss_sources.loss_sources(model, weights, fund_ids=ids, alpha=.05)` → `{n_eff, top, hedges}` for one weight vector | [19](tests/test_a_se_19_enlc_attribution.py) |

All simulated consumers retain **2,000 × 252** paths. Shape is fitted on `log1p` of present
simple-return observations, while the shape digest covers the simple-return panel. Level
scaling is the amended log-fund/simple-mix calculation. Ruined simulated years are absorbed
and counted; replay still raises. Loss attribution uses the amended pooled simple mean.
The frozen files retain their own numerical tolerances and negative controls.

`/v1/range` must return 422 for an unknown engine and 409 `range_unavailable` for missing,
uncarried or mismatched artifact/source state. It must not silently substitute replay.
Phase 1 returns `loss_sources: null`; Phase 2 provides the actual selected-engine block.
UI gates render the real App using embedded TypeScript with controlled local transport;
numeric integration gates consume real builder/API results. They are not production deployment.

## Structured validation CLI and exported evidence

Entrypoint: `scripts/backtest_ranges.py`; `--out` is a directory. The common Phase 1/2 arguments
are `--store-dir PATH --menus guide2017,tsp --lookbacks 5y,1y --engines replay,garch --out DIR`.
`coverage` and `compare` share this argument set; `measures` adds `--measures enb,dr2`;
`seeds` adds `--alpha 0.05` (a complete `0.10` rerun is allowed only after preserving 5% failure).
Synthetic controls also use `--origins YYYY-MM-DD`. Future A-SE-27 adds `copula` to engines.
These are frozen audit-export requirements, not a claim that the CLI is already implemented.

| Command | Artifact and top-level contract | Full schema |
|---|---|---|
| `coverage` | `coverage.json`: `rows`, `metrics`, `decision_rule`, `unavailable_cases`; Phase 3 also `comparator: "garch"` | [14](tests/test_a_se_14_validation_evidence.py), [27](tests/test_a_se_27_copula_validation.py) |
| `compare` | `compare.json`: `rows`, `stress_rows`, `invariants` | [14](tests/test_a_se_14_validation_evidence.py), [27](tests/test_a_se_27_copula_validation.py) |
| `measures` | `measures.json`: `rows`, `aggregation`, `default_measure`, `range_default`, `single_fund_checks`, `bound_checks`, `off_line_counts`, `word_distribution`, `dr2_100_fund_measurement`, `tie_default`, `owner_review_required` | [22](tests/test_a_se_22_measures_evidence.py) |
| `seeds` | `seeds.json`: `rows`, `alpha`, `null_transitions`, successful `selected_alpha`, `method.loss_alpha`; successful 10% rerun also preserves `prior_5pct_failure` | [23](tests/test_a_se_23_enlc_seed_stability.py), [27](tests/test_a_se_27_copula_validation.py) |
| Reports | `report.md`; engine report has one fenced `engine_validation_summary` JSON object bound to verified metrics/rules/comparisons/invariants; measures report includes fenced JSON binding actual `rows` and `aggregation` | [14](tests/test_a_se_14_validation_evidence.py), [22](tests/test_a_se_22_measures_evidence.py), [27](tests/test_a_se_27_copula_validation.py) |

Coverage rows expose source-record keys/hashes, weights, 2,000 `simulated_years`, predicted
quantiles and realized returns; the tests recompute them independently. Seed rows identify
menu/lookback/engine/seed/column/point and model inputs, with `simulation` artifact descriptors
(`path`, `sha256`, documented `kind`); exported arrays must equal actual reconstructed draws.
Do not substitute summaries, self-reported success, fabricated histories or smaller runs.

Follow assertion-spec §2 item 8: an entered portfolio exists only when its allocation was
supplied. Never fabricate TSP or other preset weights to fill the experiment. A-SE-14/27 require
`unavailable_cases` records for each missing entered case with `menu`, `lookback`, `origin`,
`engine`, `mix: "entered"`, `status: "unavailable"`, `reason: "no_allocation"`; such cases do
not become numeric observations. When supplied, evaluated weights must follow the allocation.

The full experiment reads the real backup at `/mnt/d/portfoliosight-data`. A-SE-14 and the
target-host comparison legs allow `PS_ENGINE_VALIDATION_STORE`; A-SE-22/23's report legs
currently require the default path. Do not assume the override applies to every test.
Validation wrappers deny provider/network access, subprocess escape and writes outside their
temporary output area, and check the source mirror for mutation. A-SE-14/27 use internally
set `PS_VALIDATION_SCRATCH`. Missing historical records require a checkpoint, not provider
fallback, changing the backup, or a passing skip.

## Operator-only KS-001 measurements

[A-SE-16](tests/test_a_se_16_measured_budgets.py), [A-SE-22](tests/test_a_se_22_measures_evidence.py)
and future [A-SE-28](tests/test_a_se_28_copula_budgets.py) require these explicit environment names:
`PS_KS001_SSH_HOST`, `PS_KS001_BENCH_CONTAINER`, `PS_KS001_REPO_DIR`, `PS_KS001_INPUT_STORE`.
They identify an isolated benchmark container, checkout and read-only full real input store;
do not invent values, reuse a production write target, or automatically deploy to satisfy them.
The frozen transport checks host, source hashes, input hashes and four-CPU/1,536-MiB limits.
Mutations occur in temporary copied stores; the complete 12-tensor nightly starts without
models/tensors, so a warm cache cannot replace cold fit/draw evidence.

Phase 1/2 measure the ≤30-second 23-fund cold build, ≤600-second nightly and <1-second warm
replay/GARCH requests. A-SE-22 also measures 100-fund DR² without inventing a 30-second limit.
Future Phase 3 measures the full nightly and ≤10-second first-load/warm copula requests.
Source-bound runbook evidence is required. Harness outputs include `ks001_measured_budget.json`
(16/22) and `copula_target_budget.json` (28); the full recorded schema stays in those tests.

## Future copula prerequisites and frozen trust

[A-SE-01](tests/test_a_se_01_qse_provenance.py) independently trusts the initial **ten-file**
QSE pin `ca8c0445a56712c92dc028e68845b94963fdd590`, including exact bytes and lock closure.
Ordinary runs exercise sync with a disposable git fixture; no private checkout is required.
[A-SE-24](tests/test_a_se_24_upstream_copula.py) intentionally has an empty
`approved_copula_pins` registry. Copula cannot currently satisfy that trust prerequisite.

Its **proposed, unapproved upstream API** is `fit_copula(pool, seed, num_threads=1, truncation=5)`
returning `vine`, `pseudo_observations`, `active_columns`, `margins`, `controls`, and
`shock_source()`. The proposed source is callable as `(paths, horizon, rng)`; margin objects
have `quantile(u)`. Future tests expect genuine `pyvinecopulib.Vinecop` / `FitControlsVinecop`,
empirical margins, stored `copula_shocks.npy` and actual QSE `ShockSource` integration.
These fields are a future proposal, not a statement about the current upstream package.

An owner-approved unpark requires review of the actual upstream API and merged source,
independent trusted-byte attestation, a documented gate-change note, and an approved refreeze
that reconciles both the old A-SE-01 pin and the new A-SE-24 registry. A self-reported lock
file is not trust. A phase worker must not populate the registry, weaken/remove checks, or
mock copula to make the parked floor pass. Preserve the Phase 1/2 checkpoint meanwhile.
