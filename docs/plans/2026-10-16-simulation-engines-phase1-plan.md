# Simulation engines, Phase 1: the volatility model (`garch`)

**Normative spec:** docs/specs/2026-10-14-portfoliosight-simulation-engines-design.md. The spec governs this plan wherever they conflict; the plan is then corrected. The demo spec (docs/specs/2026-10-13-portfoliosight-demo-design.md) stays in force for everything the engines spec does not change.

Date: 2026-10-16. Owner: Jeff Daniels. Author: the planning session; another agent implements. Repo `github:automateintelligence/portfoliosight`, branch `main`.

This plan covers the spec's **Phase 1** only (§11): the `garch` engine behind the Settings "Simulation" control, with History replay still the default. It is cut into seven pull requests, each safe to deploy on its own. Phase 2 (measures) and Phase 3 (copula) of the spec are not planned here.

## Facts the spec does not have

1. **QSE comes in by a selected pull, not a pip install** (owner decision of 2026-10-16, recorded as spec §13 item 18 in the same commit as this plan). The QSE repository is private and its dependency list carries torch and xgboost. The ten files that `qse.distributions.joint` needs are copied byte-identical into a top-level package `qse/` of this repository by `scripts/sync_qse.py`, locked by hash, and made read-only three ways. The Dockerfile, local development, the gate and tests need no QSE install and no GitHub access. The owner accepts that this publishes those files (this repository is public).
2. **The pin is QSE merge commit `ca8c0445a56712c92dc028e68845b94963fdd590`** (PR #164, merged 2026-10-15). It is on `github/main` of the local checkout at `~/programming/quant-scenario-engine`; that checkout's own `main` is 16 commits behind the remote, which does not matter because the script reads the commit with `git show`.
3. **Verified on 2026-10-16** (scratch venv with the `.venv` versions numpy 2.5.4, pandas 3.0.6, scipy 1.18.1, plus `arch==8.0.0`, which brought statsmodels 0.15.0): the ten files import with nothing beyond numpy and pandas; `arch` loads lazily at fit time and brings scipy, statsmodels and their own dependencies (patsy, formulaic, narwhals, interface_meta, wrapt, packaging, typing_extensions). A 23-fund × 2,520-row GARCH-t panel fits in 3.5 s on the laptop and is bit-for-bit repeatable; the 2,000 × 252 × 23 simulation takes 0.8 s and 93 MB.
4. **Phase 0 is done.** Tag `dashboard-bootstrap-2026-10-15` (commit `4a17431`, image, Worker version `6a9a30c7-…`, generation `2026-10-14-0.2.0` pinned in `meta/pinned.json`); the runbook's "Rollback points" section has the three commands. Engine version goes `0.2.0 → 0.3.0`, tensor schema `2 → 3`.
5. **KS-001 is shared production.** API and nightly containers have 4 CPUs and 1,536 MB. The nightly starts at 02:00 PT; its tier 2/3 walk stops at 01:30. A nightly run can stay active for hours after 02:00; `systemctl is-active portfoliosight-nightly.service` says so.
6. There is no hosted CI (`.github/` does not exist). "CI" here means the local gates (`ruff`, `pyright`, `pytest`, `npm`) and the conductor gate under `assertions/`, which runs in the main checkout's `.venv`.

## What exists today, and what this plan changes

| Today | After Phase 1 |
|---|---|
| `portfoliosight/engine/ranges.py`: one method (stationary block bootstrap), `one_year_ranges(model, weights)` | the same entry, two model types: `RangeModel` (replay) and `GarchRangeModel`; a model knows its engine |
| tensor schema 2, `frontier.range`, `ladder.range`, `entered.range`, `range_method`, `enb_ref` | schema 3: the kept fields unchanged, plus `engines`, `range_default`, `frontier.ranges`, `ladder.ranges`, `entered.ranges`, `shape` |
| `POST /v1/range` answers replay | body may name `engine`; answer carries `engine` and `loss_sources: null` |
| nothing under `models/` in the store | `models/{G}/{shape16}/garch.json` and `pool.npy`, pruned with the generation |
| page: zod `schema: 2`, one range per node | page reads schema 2 or 3; a "Simulation" radio, `e=` in the URL, an engine tag, per-engine `s_safe`, bar scale across engines |
| no QSE code | `qse/` (ten files, read-only, locked), `scripts/sync_qse.py`, `arch==8.0.0` |

## Recipe for every phase (owner rules; they win over skill and tool defaults)

1. **Branch and PR.** One feature branch per phase, forked from `main` (`git checkout -b feature/<slug> main`), one PR, base `main`. Docs-only changes (plans, reviews, runbook, spec text) go straight to `main` with no PR.
2. **Fast iteration over gates.** The frozen gate tests under `assertions/` are ordinary tests in this pre-production period. A phase may update and re-freeze any gate test its change makes false. The PR body says which, and the phase writes a one-page note `docs/reviews/2026-10-xx_gate-change_<slug>.md` in the form of `docs/reviews/2026-10-15_gate-change_parallel-ladder.md` (table: gate file, assertion, before, after, property protected, why not weaker). Never weaken a test to pass it.
3. **Exactly one pytest pass per merge.** Either the implementer runs the suite and the Codex review prompt says "tests already run: <result>; do not run tests", or the implementer does not run it and the prompt asks Codex to. Not both. Focused tests per task are not "the suite".
4. **Codex review.** `codex exec` (codex-cli 0.162.1) reviews each PR read-only against the phase's `Spec:` sections. Re-review only while a round returns P0/P1; then fix P2 and below without another review. More than three rounds: stop and report why it does not converge.
5. **Merge** with `gh pr merge --merge`. **Deploy** with `make deploy-backend`, then `make deploy-frontend`, only where the phase says so. Do not run the production smoke suite. After the merge, clean the worktree and branch with `~/.claude/scripts/worktree-cleanup.py --apply` from the main checkout.
6. **Secrets** come only from `~/.secrets/portfoliosight.env` (loaded with `set -a; . ~/.secrets/portfoliosight.env; set +a`), never printed, never on a command line, never in a PR body or a doc.
7. **QSE.** Never touch `/tmp/qse-daily-pipeline.lock`. The QSE lake is read-only. Never edit a file under `qse/` here: a change needed in QSE is a QSE PR the implementer opens and the owner merges; then the pin moves and `scripts/sync_qse.py` is re-run. The mirror `/mnt/d/portfoliosight-data` is a backup: read it, never write to it.
8. **Commits.** Message = changed files with line numbers, then one or two bullets, ending with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. PR bodies end with `🤖 Generated with [Claude Code](https://claude.com/claude-code)`. Atomic commits.
9. **TDD.** Each task lists the focused tests to write first. Lint and typecheck touched files per task: `ruff check . && ruff format --check . && pyright .`; `cd web && npm run lint && npm run typecheck` when `web/` changes.
10. **Gates for what the phase touches** before the PR: Python → `ruff`, `pyright`, `pytest --cov=portfoliosight --cov-report=term-missing` (≥ 80% overall, 100% on `portfoliosight/engine/`); `web/` → `npm run lint && npm run typecheck && npm test`, and `npm run e2e:local` when the page's behaviour changes.
11. **Decisions.** The implementer decides technical details and records them in the PR body. Only product, money, licensing and risk questions go to the owner (see "Open questions").
12. **Copy rules** (spec §6): never "GARCH", "vine", "residual", "expected shortfall", "entropy" in default copy; "Copula" only as the control's label and the engine tag; the demo spec's forbidden words still apply.

## Phase order and deploy safety

| Phase | PR | Deploys | May deploy before a night's run? |
|---|---|---|---|
| 1 QSE pull, pins, read-only layers | `feature/qse-sync` | backend (optional, proves the image) | yes, any hour: engine stays 0.2.0 |
| 2 engine, schema 3, fixture, page tolerance | `feature/engine-garch` | frontend only (reads schema 2 and 3) | yes: the page still shows replay |
| 3 store, artifacts, nightly, dry run | `feature/engine-store` | backend 0.3.0, then a hand-started nightly | **no**: deploy in the afternoon PT when the nightly service is inactive, after the mirror dry run passes, and start the nightly by hand at once (below) |
| 4 `/v1/range` with `engine`, health | `feature/range-engine` | backend | yes: additive, nothing calls it yet |
| 5 page control, URL, tag, copy | `feature/web-engine` | frontend | yes: the backend already answers |
| 6 validation script and report | `feature/backtest-ranges` | none (report to `main`) | — |
| 7 owner analysis | none (docs) | none | — |

The staircase keeps every boundary safe: the page learns schema 3 before the backend publishes it (Phase 2 before 3); the backend answers `engine` before the page sends it (Phase 4 before 5); each nightly after a deploy builds something every deployed reader can read.

**The 0.3.0 rollout (end of Phase 3).** Until the first `…-0.3.0` generation is published, the API refuses custom menus with `engine_version_mismatch` (presets keep serving from R2). So: run `scripts/build_presets.py` against the mirror first (every preset × lookback must build); deploy only while `ssh "$PS_KS001_SSH_HOST" systemctl is-active portfoliosight-nightly.service` answers `inactive`; then `ssh "$PS_KS001_SSH_HOST" sudo systemctl start --no-block portfoliosight-nightly.service` and watch `/v1/health` until `generation` ends in `-0.3.0` (the presets build in about a minute; the tier 2/3 walk then runs to 01:30 and the 02:00 timer fires as usual). If the nightly fails to publish, `meta/current.json` stays on the 0.2.0 generation: roll the backend back with `make deploy-backend SHA=<Phase 1 merge commit>` and fix on the laptop.

---

## Phase 1 — QSE selected pull, pins and read-only layers

**Spec:** §3 item 3, §8 (install paragraph), §12 "QSE pin", §13 item 18, S9, M2. Demo spec §5.3 (build context), §9.1.

**Branch:** `feature/qse-sync`.

### Tasks

- [ ] 1.1 `scripts/sync_qse.py` (new). Arguments: `--commit <40 hex>` (required unless `--check`), `--qse-dir PATH` (default: `$PS_QSE_DIR`, else `Path.home() / "programming" / "quant-scenario-engine"`; never a literal home path in the file), `--root PATH` (default: this repo; tests point it at a temp copy), `--check`. Fixed `FILES` tuple, exactly these ten QSE paths, copied to the same path under the repo root:
  `qse/distributions/__init__.py` (empty at the pin; copied so `qse.distributions` stays a regular package), `qse/distributions/joint/__init__.py`, `qse/distributions/joint/fhs.py`, `qse/distributions/joint/panel_fit.py`, `qse/distributions/joint/portfolio.py`, `qse/distributions/fitters/garch_t_fitter.py`, `qse/distributions/garch_recursion.py`, `qse/distributions/validation/stationarity.py`, `qse/distributions/models.py`, `qse/exceptions.py`.
  Not copied on purpose: `qse/distributions/validation/__init__.py` (it imports `validation_core`, outside the closure) and QSE has no `qse/__init__.py` or `fitters/__init__.py`; those directories are namespace packages here, as in QSE. Behaviour: check the commit exists (`git -C <qse-dir> cat-file -e <sha>^{commit}`; else exit 3 with "fetch QSE's `github` remote"); read each file with `git -C <qse-dir> show <sha>:<path>` (the QSE working tree is never touched); if the target exists, `chmod u+w` it first; write the bytes; `chmod a-w` (mode 0444); write `qse/qse.lock.json` = `{"source": "automateintelligence/quant-scenario-engine", "commit": "<sha>", "files": {"<path>": "<sha256>", …}}` with sorted keys and a trailing newline. `--check`: rehash every listed file, list every `*.py` under `qse/` that the lock does not name, re-apply `chmod a-w`, print each drift, exit 1 on any. No URL in the file (A-PS-10 scans `scripts/`).
- [ ] 1.2 Run it: `.venv/bin/python scripts/sync_qse.py --commit ca8c0445a56712c92dc028e68845b94963fdd590`. Commit `qse/` and the lock. Verify the ten files are byte-identical to `git show` (the lock does this).
- [ ] 1.3 `qse/README.md` (PS-authored, hand-written once): what the directory is, the pinned commit and lock file, the rule "edit in QSE, merge there, then re-run `scripts/sync_qse.py --commit <new sha>` and merge here", and the three read-only layers: agents (`.claude/settings.json` denies `Edit` and `Write` under `qse/`), disk (`chmod a-w` by the script; `scripts/sync_qse.py --check` restores it after a fresh clone), backstop (`tests/test_qse_sync.py` fails on any drift; there is no pre-commit setup in this repo, so there is no hook).
- [ ] 1.4 `.claude/settings.json` (new, tracked; nothing exists there today): `{"permissions": {"deny": ["Edit(/qse/**)", "Write(/qse/**)"]}}`. The leading `/` is the repo root.
- [ ] 1.5 `pyproject.toml`: `dependencies` gains `"arch==8.0.0"` (exact: its optimizer decides tensor bytes); `[tool.setuptools.packages.find] include = ["portfoliosight*", "qse*"]` so `pip install -e ".[api,dev]"` installs `qse` from this project (namespace packages are found by default); `[tool.setuptools.package-data]` gains `qse = ["qse.lock.json"]`; `[tool.ruff] extend-exclude` and `[tool.pyright] exclude` gain `"qse"` (copied files are never reformatted or retyped here). statsmodels is not listed: `arch` requires it and it is not on the fit's numeric path. Re-sync `.venv`: `uv pip install --python .venv/bin/python -e ".[api,dev]"`.
- [ ] 1.6 `.dockerignore`: add `!qse` after `!data`. `deploy/Dockerfile`: build stage gains `COPY qse ./qse` before the `pip install … ".[api]"` line (which installs `qse` into `/install`; the existing `rm -rf …/portfoliosight` stays); runtime stage gains `RUN python -c "import qse.distributions.joint, arch"` before `USER app`. No `ARG`, nothing secret, the words `KEY`/`SECRET` absent (tests/deploy/test_compose.py scans for them).
- [ ] 1.7 Run QSE's own tests for the copied code once against the copy: `git -C <qse-dir> show <sha>:tests/unit/distributions/<name>` for `test_joint_fhs.py`, `test_joint_panel_fit.py`, `test_joint_portfolio.py`, `test_garch_recursion.py` into the scratchpad, run them with `.venv/bin/python -m pytest -p no:cacheprovider <dir>` (they import `qse.distributions.joint`, which resolves to the copy). Record pass/fail counts in the PR body. Do not commit them.
- [ ] 1.8 Update the tests the change makes false: `tests/deploy/test_dockerignore.py` (kept paths gain `qse`), `tests/deploy/test_compose.py::test_dockerfile_follows_the_spec` (assert `COPY qse ./qse`), A-PS-32's ignore-rule leg if it lists the kept paths, `tests/test_dependencies.py::RUNTIME_IMPORTS` gains `arch`. Gate-change note per recipe rule 2.
- [ ] 1.9 Optional deploy: `make deploy-backend` to prove the image on KS-001 (`arch` 8.0.0 ships manylinux wheels; `python:3.12-slim` needs no compiler). Safe at any hour; engine stays 0.2.0.

### Tests first

- `tests/test_qse_sync.py` (new): the lock's commit is 40 hex and equals the plan's pin; every file the lock names exists and hashes to its entry; no `*.py` under `qse/` is outside the lock; `scripts/sync_qse.py --check --root <tmp copy>` exits 0 on a faithful copy and 1 after one byte is changed, naming the file; after `--check` every listed file is mode `0444`; `qse/README.md` names the three layers; `.claude/settings.json` holds the two deny entries. The script's `--commit` path is tested against a tiny throwaway git repository made in `tmp_path` (not the real QSE checkout), so the test needs no network and no external path.
- `tests/test_dependencies.py`: `test_arch_is_pinned_exact` (`arch==8.0.0` in `dependencies`); `test_qse_import_closure`: a subprocess `python -I -c` imports `qse.distributions.joint`, fits a 300-row synthetic series through `fit_garch_t_panel` (so `arch`'s lazy import runs), and prints every third-party top-level module in `sys.modules`; the test maps each to its distribution (`importlib.metadata.packages_distributions`) and asserts the set is within the dependency closure of {numpy, scipy, pandas, statsmodels, arch} computed from `importlib.metadata.requires`, and that none of torch, xgboost, numba, sklearn, cvxpy, matplotlib, plotly, pydantic appear.

### Done when

- `python -c "import qse.distributions.joint"` works in `.venv` and in the built image; `pytest tests/test_qse_sync.py tests/test_dependencies.py` green; the QSE joint and recursion tests pass against the copy (counts in the PR); a hand edit to any file under `qse/` fails `tests/test_qse_sync.py`; `ruff`, `pyright`, the full suite and the gate run green; the README under `qse/` states the rule and the three layers.

---

## Phase 2 — Engine: shape fit, `garch` ranges, level scaling, tensor schema 3

**Spec:** §4.1, §4.3, §4.5, §7 (tensor changes, versions), §9 (memory), §10 item 5, §12 (fit library, splice guard), M5, M6, F5, F6. Demo spec §4.2, §4.3, §4.9, §4.11, §4.12, §7.

**Branch:** `feature/engine-garch`. Engine math; the implementer should be the model and effort the owner set for engine work.

### Design decisions made here

- **One entry, two model types.** `one_year_ranges(model, weights)` keeps its signature; the model carries its engine (`RangeModel.engine == "replay"`, `GarchRangeModel.engine == "garch"`). The spec's `one_year_ranges(model, weights, engine)` is satisfied by the model object naming the engine; the builder loops over engines. `simulated_years(model, weights) -> P × M` is the shared lower level (Phase 6 needs the paths).
- **Compounding stays in PortfolioSight.** §4.5 makes each mix an effective weight vector plus a per-mix constant: `v = k_w · (w ∘ a)`, `b = m_w + k_w (w·c − m_w)`, where `a_n = s_n / sd_n` (0 for a constant fund), `c_n = m_n − a_n R̄_n`. QSE's `constant_mix_horizon_returns` has no intercept, so `ranges.py` compounds `∏_t (1 + v·R_{p,t} + b) − 1` itself in path chunks (`np.log1p` summed, then `expm1`), work buffer ≤ 64 MB, never materialising `R'`. `k_w = s_w / sd(y)` with `sd(y)² = (w∘a)' Σ_R (w∘a)`, `Σ_R` the pooled (`ddof = 0`) covariance of the raw simulated panel computed once per model in chunks (no 93 MB copy). `sd(y) = 0` → `y' = m_w`. A day at or below −100% raises `ValueError`, as today (corrected below for `garch`). QSE supplies the fit, the pool, the row draw and the recursion; nothing of QSE's is copied beyond Phase 1's pull.
- **Fit → artifact → simulate, one path for build and API.** The build fits (`fit_garch_t_panel`), builds the pool (`residual_pool(fit, restandardize=True, min_rows=126)`), and freezes a `GarchArtifact`. Simulation is always from the artifact: `idx = draw_row_indices(pool_rows, 2000, 252, seed=20261013)`; `simulate_garch11(pool[idx], mu, omega, alpha, beta, sigma2_init=garch11_long_run_variance(omega, alpha, beta), out=<the shock array>)`. That is exactly what `simulate_fhs_panel(fit, …, row_indices=idx, start="long_run")` does internally, so build and `/v1/range` (Phase 4) share bytes.
- **The universe hash does not move.** `builder.universe_hash` uses `SCHEMA_VERSION` in its canonical JSON today; A-PS-29 and spec §7 pin `"schema": 2` there. Introduce `HASH_SCHEMA = 2` for the hash and bump `SCHEMA_VERSION` to 3 for the document.
- **`qse` and `arch` in the method block.** `engines.garch.method.qse` is the lock file's commit (read with `importlib.resources.files("qse").joinpath("qse.lock.json")`, the same mechanism `builder.load_schema` uses; the engine purity scan forbids `open(` and `pathlib`), `method.arch` is `arch.__version__`.
- **Splice dates come from the records.** A seeded fund's splice date is the first row whose `split_factor` is not null while the row before it is null (`portfoliosight/data/lake.py` writes seed rows with `NaN` actions; provider rows carry numbers; TSP rows carry `0`/`1` on every row, so they have no splice). The engine takes `TensorInputs.splice_dates: Mapping[str, str] | None` (ISO date per fund; a fund absent from it has no splice) and never reads a record itself. Phase 3 computes them in `jobs/build.py`; `scripts/build_tensor.py` passes none (the fixture has no splice).
- **Statuses and reasons.** `shape` is an object whenever the fit ran, `null` when `garch` was not computed for the build (`engines` not asking for it). `engines.garch.status = "unavailable"` with `reason = "not enough shared history for the volatility model"` when the pool has fewer than 126 rows (QSE's `ValueError`), and `"not computed for custom menus"` / `"not computed for this menu"` when not asked. `residual_pool`'s "constant over the common rows for non-constant assets" error fails the build (`ShapeError`), as a lockstep menu fails the torsion today (M5: nothing is filled in). `engines.copula = {"status": "unavailable", "reason": "not computed for this menu", "method": null}` so the page has one place to read every engine's reason.
- **Precision.** Builds simulate and compound in float64 (decision 14).
- **Log returns, two-space level step, ruin guard (2026-10-17, corrected to spec §4.3/§4.5).** The fit and simulation run on `log1p(r)`; step 1 levels each fund in log space by lognormal moment matching, step 2 pins each mix in simple space from the pooled moments of `R' = expm1(ℓ')` (computed per path chunk; the effective-weights-on-the-raw-panel shortcut no longer applies); scale `sd` (IQR measured and rejected); a `garch` path with a day at or below −100% is absorbed and counted (`engines.garch.ruin_paths`, `method.ruin = "absorb"`), `replay` still raises. A variance cap would need a QSE change (`simulate_garch11` has none).

### Tasks

- [ ] 2.1 `portfoliosight/engine/__init__.py`: `ENGINE_VERSION = "0.3.0"`.
- [ ] 2.2 `portfoliosight/engine/shape.py` (new, pure): constants `SHAPE_ROWS = 2520`, `MIN_POOL_ROWS = 126`, `OUTLIER_Z = 6.0`; `ShapePanel` (frame of the last 2,520 rows of the included funds' union calendar ending at `asof`, each fund on its own rows, NaN elsewhere; `start`, `end`, `rows`, `sample_sha256` via `ranges.sample_digest` with NaN replaced by the canonical quiet NaN before hashing); `shape_panel(returns, included, asof) -> ShapePanel`; `GarchArtifact` (frozen dataclass: `funds`, `rows`, `start`, `end`, `sample_sha256`, `mu`, `omega`, `alpha`, `beta`, `nu` (NaN for fallbacks), `status`, `messages`, `n_obs`, `long_run_sigma_annual`, `pool` (`T_pool × N` float64 or `None`), `pool_rows`, `pool_sha256`, `outliers` (`[{id, date, z}]`), `unavailable_reason`, `qse`, `arch`); `fit_shape(panel, splice_dates) -> GarchArtifact` (QSE `fit_garch_t_panel` with defaults; `residual_pool(min_rows=MIN_POOL_ROWS)`; splice guard on `fit.std_residuals`: `|z_n| > 6` on the fund's own splice date **and** `|z_n − median of the other included funds that day| > 6` raises `ShapeError` naming fund and date; every other `|z| > 6` is an outlier entry); `artifact_to_json(artifact) -> dict` and `artifact_from_json(doc, pool) -> GarchArtifact` (the pool travels as `.npy` bytes through `pool_bytes(artifact)` / `pool_from_bytes(data)` with `allow_pickle=False`; `io.BytesIO`, no file access); `simulate_panel(artifact, paths=2000, horizon=252, seed=20261013) -> P × H × N` as decided above; `qse_commit()` from the lock; `garch_method(artifact)` → the §7 method dict (`name: "garch_t_fhs"`, `paths`, `horizon_days`, `seed`, `start: "long_run"`, `shape_rows`, `qse`, `arch`).
- [ ] 2.3 `portfoliosight/engine/ranges.py`: `ENGINES = ("replay", "garch")`, `DEFAULT_ENGINE = "replay"`; `RangeModel` gains `engine = "replay"` and `seed`; `GarchRangeModel` (frozen: `engine`, `panel`, `mean`, `sd`, `cov_sim`, `mu_s`, `cov`, `seed`); `garch_range_model(panel, mu_s, cov, seed=SEED)` (pooled mean, sd and covariance in chunks; shape checks like `range_model`); `simulated_years(model, weights)` for both types (replay: today's count-matrix product; garch: the effective-weight compounding above); `one_year_ranges(model, weights)` = percentiles of `simulated_years` plus the normal range, as today. `bootstrap_index` keeps its seed parameter so Phase 6 can vary it.
- [ ] 2.4 `portfoliosight/engine/builder.py`: `SCHEMA_VERSION = 3`, `HASH_SCHEMA = 2` (used by `universe_hash`); `TensorInputs` gains `engines: tuple[str, ...] = ("replay", "garch")`, `splice_dates`, `garch_artifact: GarchArtifact | None` (reuse when its `sample_sha256` equals the panel's; else fit); `BuildResult(tensor, models: dict[str, RangeModel | GarchRangeModel], artifacts: dict[str, GarchArtifact])` returned by new `build_tensor_full(inputs, *, workers=None)`; `build_tensor` returns `.tensor` (signature unchanged). The tensor gains `engines`, `range_default: "replay"`, `frontier.ranges[engine] = {s_safe, bad, typical, good}`, `ladder.ranges[engine] = {bad, typical, good}`, `entered.ranges[engine] = {bad, typical, good}`, `shape` (§7: `rows`, `start`, `end`, `sample_sha256`, `pool_rows`, `funds[] = {id, status, rows, mu, omega, alpha, beta, nu, long_run_sigma_annual, margin: null}`, `outliers`, `lower_tail_5pct: null`, `tree_loglik_share: null`); the kept fields (`frontier.range`, `frontier.s_safe`, `ladder.range`, `entered.range`, `range_method`, `enb_ref`) keep the default engine's figures. `NOTES` gains one sentence per simulation engine the tensor carries. `_post_check` also checks `bad < typical < good` for every carried mix under every engine. The ew lookback: level from the weighted moments, shape from the same panel (note in `notes`).
- [ ] 2.5 `portfoliosight/engine/tensor.schema.json`: `$id` `urn:portfoliosight:tensor:3`, `schema: {const: 3}`, the new properties and `required` entries (`engines`, `range_default`, `shape` at top level; `ranges` in `frontier`, `ladder`, `entered`), `$defs` for the per-engine range blocks and `shape`; `engines.*.method` is `null` or an object with `name`; `engines.garch.method.qse` pattern `^[0-9a-f]{7,40}$`.
- [ ] 2.6 `scripts/build_tensor.py`: `--engines replay,garch` (default both). Regenerate `web/fixtures/guide2017_5y.json` with the pinned invocation that `tests/engine/test_build_cli.py::test_pinned_invocation_reproduces_the_ui_fixture` and A-PS-24 test 7 use (read them; do not guess the flags). `tests/fixtures/synthetic_23.parquet` and `scripts/make_fixtures.py` are not touched (byte-reproducibility test).
- [ ] 2.7 `web/src/api/tensor.ts`: `schema: z.union([z.literal(2), z.literal(3)])`; the new blocks as optional members of the same `strictObject`s; `superRefine`: a schema-3 document must carry them; size checks for `frontier.ranges[e]` (nx), `ladder.ranges[e]` (nx × levels), `entered.ranges[e]`, `shape.funds` (n) when present. Nothing on the page reads them yet. Keep schema 2 accepted until the Phase 0 rollback generation is retired (so a backend rollback never breaks the page).
- [ ] 2.8 Update the readers that pin schema 2 or the fixture's bytes, and re-freeze gate tests as needed (A-PS-24 reads the kept fields and the shipped schema, so it should pass unchanged once the fixture is regenerated; A-PS-34/45 read `frontier.range`, `ladder.range`, `frontier.s_safe`: unchanged). Gate-change note if anything is re-frozen.

### Tests first (`tests/engine/test_shape.py` new; `tests/engine/test_ranges.py`, `tests/engine/test_builder.py`, `web/tests/tensor-sources.test.ts` grown)

- Shape panel: the last 2,520 union-calendar rows, NaN where a fund has no return, same digest for two lookbacks with the same included set, a different digest when the 1y view admits a younger fund, canonical NaN in the digest.
- Fit and fallbacks on in-test synthetic series (seeded; a 2-asset GARCH-t panel made with QSE's `simulate_garch11` and `standardized_t_shocks`, like QSE's own tests): a fund with `status == "garch"`; a TSP-G-like constant series → `near_constant`; a 200-row series → `insufficient_history`; a synthetic series with `α + β ≥ 1 − 1e-4` → `non_stationary`; each simulated through the same recursion with its shock scaled (M5: never filled, never clipped).
- Splice guard: a fixture with a fabricated 30% ex-date drop on one fund's splice date fails the build naming fund and date; the same drop on another date is an outlier entry and fails nothing; a cross-sectional drop on the splice date (every fund) is an outlier, not a failure.
- Pool: fewer than 126 common rows → `unavailable` with the spec's reason; `pool_rows` recorded; restandardised columns have mean 0 and variance 1 (`ddof = 0`).
- Level and shape (§4.5): after step 1 every fund's pooled mean is `m_n` and sd `s_n` to 1e-12; after step 2 every mix's pooled mean is `m_w` and sd `s_w`; `k_w` agrees with the closed form from `Σ_R`; a constant fund gives `R' = m_n`; `sd(y) = 0` gives `y' = m_w`; the chunked compounding equals a one-shot compounding on a tiny panel to 1e-12.
- Invariants (§10 item 5) for every engine: `bad < typical < good`; typical within `0.25σ` of `e^{μ − σ²/2} − 1`; level 0's range is the node's; the frontier's `ranges.garch.s_safe` is the rightmost best-bad node under `garch`; identical canonical JSON from identical inputs; identical for 1, 2 and 4 workers; `−100%` day raises.
- `simulate_panel` from an artifact round-tripped through `artifact_to_json` / `pool_bytes` is byte-identical to the build's.
- Schema: the fixture validates; a document without `engines` or `shape` is refused; `universe_hash` is unchanged from the committed values (`tests/api/test_hashing.py`).
- Memory: a 30-fund synthetic build's peak RSS stays under 400 MB above baseline (`resource.getrusage`), guarding the §9 budget.
- Page: `parseTensor` accepts the old fixture bytes (schema 2, kept under `web/tests/` as a small trimmed document) and the new fixture (schema 3), and refuses a schema-3 document without `engines`.

### Done when

- The 23-fund fixture builds with `replay,garch` in ≤ 90 s on the laptop (A-PS-24 test 6) and the UI fixture is its unedited output; engine coverage 100%; determinism and fallback tests pass; `npm test` passes with the regenerated fixture. **Deploy:** `make deploy-frontend` (optional, any hour): the page accepts schema 3 while still showing replay. The backend is **not** deployed from this phase.

---

## Phase 3 — Store, artifacts, nightly and the first 0.3.0 generation

**Spec:** §7 (model artifacts; precompute or on demand), §9 (targets; "Phase 1 measures them on KS-001 and records them in the runbook"), §11 Phase 1 done-when (build time), §12 (rollback window), S11. Demo spec §5.3, §5.4, §6 (build queue), §9.1.

**Branch:** `feature/engine-store`.

### Tasks

- [ ] 3.1 `portfoliosight/api/settings.py`: `EngineSettings.from_env()` with `PS_ENGINES` (default `replay,garch`) and `PS_ENGINES_CUSTOM` (default: `PS_ENGINES` without `copula`); refuse an unknown id; `replay` always present.
- [ ] 3.2 `portfoliosight/api/presets.py`: `model_key(generation, shape16, name) -> "models/{G}/{shape16}/{name}"` next to `tensor_key`.
- [ ] 3.3 `portfoliosight/jobs/build.py`: split `build_from_store` into `inputs_from_store(store, *, funds, asof, cache_dir, universe_name, preset_id, allocation, nx, ny, levels, engines) -> TensorInputs` (everything it does today from the catalog and the records, plus `splice_dates` per the Phase 2 rule) and the generation-checked wrapper. The wrapper: compute the shape panel and its digest with the engine's `shape_panel` (only when `garch` is asked); if `models/{G}/{shape16}/garch.json` exists, fetch it and `pool.npy` through the scratch cache (`cache.fetch_into_cache`) and pass `garch_artifact`; call `build_tensor_full`; write the artifact files first (`put` only when absent; a concurrent writer wins harmlessly, the bytes are deterministic), then return the tensor for `put_tensor`. The artifact files count toward the cache cap like records (`cache.evict`).
- [ ] 3.4 `portfoliosight/api/queue.py::build_job`: read `EngineSettings.from_env()`; presets get `PS_ENGINES`, custom menus `PS_ENGINES_CUSTOM`.
- [ ] 3.5 `portfoliosight/jobs/nightly.py`: `stored_generations` scans `models/` too; `prune_generations` deletes `models/{G}/…` with the generation; `_generation_meta` records `engines`.
- [ ] 3.6 `scripts/build_presets.py` (new): `--store-dir PATH --asof YYYY-MM-DD --out DIR [--presets guide2017,tsp] [--lookbacks 1y,…] [--engines replay,garch]`. Opens a `LocalStore` read-only (it never calls `put`), builds every preset × lookback with `inputs_from_store` + `build_tensor_full`, writes the tensors and artifacts under `--out`, and prints per tensor: `build_seconds`, fit time, each fund's status, `pool_rows`, outliers, and whether the artifact was reused across lookbacks. A `ShapeError` is printed with fund and date and exits 2. Phase 6 and 7 reuse `inputs_from_store` from it.
- [ ] 3.7 Dry run on the mirror (laptop, read-only): `.venv/bin/python scripts/build_presets.py --store-dir /mnt/d/portfoliosight-data --asof <the mirror's current generation's asof> --out runs/dry-0.3.0/`. Both presets, all six lookbacks must build. Put the printed statuses (which funds fell back: expected TSP-G `near_constant`; SGOV and SHV sit near the line) and pool rows in the PR body. If the splice guard trips on a real fund, that is a data fix (re-fetch the fund's tail through the downloader on KS-001 when no nightly runs), not an engine change; stop and report.
- [ ] 3.8 Runbook (`docs/plans/2026-10-13-ks001-cloudflare-runbook.md`, straight to `main` after the deploy): under "Measured", the first 0.3.0 nightly's `preset_build_seconds` from `meta/status.json`, a 23-fund custom build's `build_seconds` through the API, and the fit statuses of both presets; under "Rollback points", a line that engine 0.3.0 generations carry `models/` and that the 0.2.0 pin stays until the owner retires it.

### Tests first (`tests/jobs/test_build.py`, `tests/jobs/test_nightly.py`, `tests/api/test_settings.py` or the existing settings tests, `tests/test_smoke_scripts.py` pattern for the new script)

- `inputs_from_store` gives the same `TensorInputs` as today's path for a fixture store (regression), plus `splice_dates` for a record with a seed head and a provider tail (`tests/data/test_splice.py` has the fixtures) and none for TSP and all-provider records.
- A build writes `models/{G}/{shape16}/garch.json` and `pool.npy` before the tensor; a second lookback with the same fund set reuses them (no second fit: assert the fit function is called once with `monkeypatch`); a lookback admitting another fund writes a second artifact; an existing artifact is never overwritten.
- A custom menu built with `PS_ENGINES_CUSTOM=replay` carries `garch` as `unavailable` with "not computed for custom menus" and no `shape`.
- Pruning removes `models/{G}/` with its generation and keeps the pinned one's.
- `scripts/build_presets.py` on the fixture store (`portfoliosight/jobs/fixture_store.py`) writes the expected files and never writes into the store directory (compare a directory digest before and after).

### Done when

- The mirror dry run builds every preset tensor with `replay,garch`; the fixture-store tests pass; the gate is green. **Deploy:** backend, per "The 0.3.0 rollout" above (afternoon PT, nightly inactive, hand-start, watch `/v1/health`). The 23-fund lookback must build in ≤ 30 s on KS-001 with `replay,garch` (`build_seconds` of a custom 23-fund POST; the fit adds about 4 s to today's 3 to 8 s); the nightly's two presets must finish well inside 10 minutes. Record both in the runbook (task 3.8). If the 30 s target is missed, apply §9 fallback 1 (float32 panel) once and re-measure; never fewer paths (M6).

---

## Phase 4 — `POST /v1/range` with `engine`, the panel cache, health

**Spec:** §7 (`POST /v1/range`, `GET /v1/health`), §9 (`/v1/range` under 1 s), §13 item 14 (float32 in the API). Demo spec §6.

**Branch:** `feature/range-engine`.

### Tasks

- [ ] 4.1 `portfoliosight/api/models.py`: `RangeRequest.engine: Literal["replay", "garch", "copula"] | None = None` (strict; an unknown string is a 422 from pydantic, as the spec asks).
- [ ] 4.2 `portfoliosight/jobs/build.py`: `garch_model_from_store(store, tensor_key, *, cache_dir, panels) -> GarchRangeModel`: load the tensor; 409 `range_unavailable` reasons as exceptions when `engines.garch.status != "ready"` ("this tensor does not carry the volatility model"), when the rebuilt shape panel's digest differs from `shape.sample_sha256` ("the price history behind this tensor changed after it was built"), or when the artifact is missing; otherwise fetch the artifact through the cache, `simulate_panel`, build the model from the float64 panel (pooled statistics), then keep the panel as float32.
- [ ] 4.3 `portfoliosight/api/ranges.py`: `RangeModels.get(generation, uhash, lookback, engine)`; replay models as today (8 kept); a separate `panels` LRU of at most 2 simulated panels keyed by `(shape16, engine)` shared across lookbacks of one fund set; `range_body(models, key, weights, engine)` resolves `engine=None` to the tensor's `range_default`, returns `{"engine", "bad", "typical", "good", "normal", "loss_sources": null}`; 409 for the reasons above; 422 for an unknown id.
- [ ] 4.4 `portfoliosight/api/app.py`: pass `engine` through; `GET /v1/health` adds `"engines": [...]` from `EngineSettings`. The Worker forwards `POST /api/range` unchanged (no Worker change).
- [ ] 4.5 Runbook "Measured": `/v1/range` with `engine: "garch"` on KS-001 for an interpolated mix, first request (artifact fetch and simulation) and later requests (must be under 1 s).

### Tests first (`tests/api/test_range.py`, `tests/api/test_routes.py`, `tests/api/test_healthcheck.py` or the health route test)

- `engine` omitted → the replay figure, response carries `"engine": "replay"` and `"loss_sources": null`; `engine: "garch"` for a ladder-level mix → within `5e-4` of the tensor's own `ladder.ranges.garch` figure (float32 panel; decision 14) and `bad < typical < good`; `engine: "garch"` twice → the artifact is read once (counting store); two lookbacks of one menu share one panel (at most two panels kept; the third fund set evicts the oldest); `engine: "copula"` → 409 with the tensor's reason; `engine: "nope"` → 422 naming `engine`; a tensor whose `garch` is `unavailable` → 409; a changed price record → 409; a missing artifact → 409; the scratch cache stays under its cap with artifacts in it; health lists the engines.

### Done when

- All of the above green; the gate green. **Deploy:** backend, any hour (additive). Measure task 4.5 and record it.

---

## Phase 5 — The page: "Simulation" control, `e=`, engine tag, per-engine ranges and copy

**Spec:** §6 (two controls — only "Simulation" in this phase; the measure control is Phase 2 of the spec), §6 "When the engine changes", "Which engine produced the numbers", the copy table (engine tag, method lines for `replay` and `garch`, fallback funds), §13 items 9 and 10, S2, S3, S4, S5, S10, F1, F3, F4. Demo spec §3.2, §3.6, §4.9, §4.11, §8.1, §9.3 (share validator).

**Branch:** `feature/web-engine`. Use the `frontend-design` skill for the control and the tag.

### Design decisions made here

- **The address names a carried engine.** `State.engine` is the visitor's choice; when the loaded tensor does not carry it, `applyTensor` sets it to the tensor's `range_default` (like `r` is clamped into the domain) and the control shows the wanted radio disabled with the tensor's reason. So `e=` always describes what is on screen.
- **`e=` is written only when not `replay`**, after `x`, in the canonical order `u f unit c lb g r d t x e`. The Worker's share validator accepts `e` with the shape `^(?:replay|garch|copula)$`.
- **Everything reads one `engine`:** `portfolioMath(tensor).yearRange(s, t, engine)` reads `ladder.ranges[engine]` (`ladder.range` when the tensor is schema 2 or `engine` is the default), `riskSliderDomain(engine)` reads `frontier.ranges[engine].s_safe` (else `frontier.s_safe`), `deriveView(tensor, math, s, t, engine)`, `tensorBounds(tensor)` spans every engine the tensor carries (bar scale, decision 10), `useExactRange(key, weights, engine)` keys its cache by engine and `postRange` sends `engine` when not the default, the entered mix reads `entered.ranges[engine]`. On an engine change `s` is clamped into the new domain and `t` returns to "auto" when the clamp moved it, exactly as `applyTensor` does today.
- **The tag** is one component, rendered twice with `data-testid="engine-tag"`: beside the strip's "Selected mix" label and beside the risk slider's readouts; muted, never a headline.

### Tasks

- [ ] 5.1 `web/src/state/url.ts`: `engine` in `UrlState` (`ENGINES = ["replay", "garch", "copula"]`), decode (unknown → `replay`), encode after `x` and only when not `replay`.
- [ ] 5.2 `web/src/state/store.ts`: `State.engine`, action `setEngine`, `toUrlState`, `createStore` from the URL, the coercion in `applyTensor`, the risk-position clamp on an engine change (no request of any kind on this action).
- [ ] 5.3 `web/src/math/portfolio.ts`, `web/src/math/view.ts`, `web/src/math/stripScale.ts`, `web/src/state/useExactRange.ts`, `web/src/api/http.ts` (`postRange(key, weights, engine, signal)`; `rangeSchema` tolerates `engine` and `loss_sources`), `web/src/App.tsx` (pass `state.engine` everywhere a range is derived; `facts` gains `engine`, the fallback funds, `pool_rows`, the method line key).
- [ ] 5.4 `web/src/sections/Settings.tsx`: the "Simulation" radio group after "Years of history", `data-testid="engine-{id}"`, the three labels and one-line descriptions from the copy table, a disabled option showing the tensor's reason, `aria-label="Simulation"`.
- [ ] 5.5 `web/src/controls/ResultStrip.tsx`, `web/src/controls/RiskSlider.tsx`: the engine tag; details gain the engine's Method line (plain or technical by the details state, as the copy table), the "Volatility held constant: …" line when the tensor names fallback funds (technical: "near-constant (daily sd < 0.03%) or fewer than 252 days"), and the pool size ("funds' shocks replayed together from N shared days"). The bell-curve figure stays as it is, labelled the same for every engine.
- [ ] 5.6 `web/src/copy.ts`: `engineNames`, `engineDescriptions`, the two method lines per engine, the fallback-fund lines, `forbiddenDefault` gains "GARCH", "vine", "residual", "expected shortfall", "entropy". `web/tests/copy.test.ts` keeps scanning `plain` for forbidden words; "Copula" is allowed only in `engineNames`.
- [ ] 5.7 `web/worker/share.ts`: the `e` key in `urlKeys`; `web/mock/server.mjs`: `/api/range` echoes `engine` and answers from the fixture's per-engine node ranges.
- [ ] 5.8 `web/e2e/local/app.spec.ts`: "the Simulation choice switches every range at once and without a request" (click `engine-garch`: `range-low/typical/high`, `risk-readout-bad/typical`, both tags, the pinned card and the bar's marks change before any network response; no `POST /api/tensors` happens; the chart canvas's sampled pixels do not change; `e=garch` appears in the address; a reload reproduces it; `engine-copula` is disabled with its reason). `web/e2e/local/screenshots.spec.ts`: `docs/reviews/2026-10-xx_engine-control_{desktop,phone}_ks-dark.png` with details on and the volatility model selected, for the owner's S3 check.
- [ ] 5.9 Re-freeze what the change makes false (A-PS-36 pins the key list `u f unit c lb g r d t x`; A-PS-38 the share validator's keys; A-PS-51 the URL reproduction) with the gate-change note.

### Tests first (`web/tests/url.test.ts`, `reducer.test.ts`, `fidelity.test.ts`, `strip-scale.test.ts`, `exact-range.test.tsx`, `sections.test.ts`, `settings-*.test.tsx`, `copy.test.ts`, `worker-share.test.ts`, `smoke.test.tsx`)

- URL: `e` round-trips, is omitted at `replay`, sits after `x`, an unknown value reads as `replay`; the Worker re-encodes `e=garch` and refuses `e=foo`.
- Store: `setEngine` writes the URL and makes no request; a tensor without `garch` coerces `engine` back to the default; an engine switch clamps `s` into the engine's domain.
- Math: `yearRange(s, t, "garch")` at a column and level equals `ladder.ranges.garch` exactly; `riskSliderDomain("garch").s_safe` is `frontier.ranges.garch.s_safe`; a schema-2 tensor answers the default for every engine; `tensorBounds` is the min Bad and max Good over every carried engine.
- Strip and slider: the tag reads "History replay" / "Volatility model"; the details' Method line switches; fallback funds and pool rows appear only when the tensor has them.
- Copy: no forbidden word in default copy; "Copula" only as the label and tag.

### Done when

- S2, S3, S5, S10 hold on the local e2e run; `npm run lint && npm run typecheck && npm test && npm run e2e:local` green; the screenshots are in `docs/reviews/`; the gate green. **Deploy:** `make deploy-frontend`, any hour. With the current generation on 0.3.0 (Phase 3), the control works on the live page; `range_default` is still `replay` (F1).

---

## Phase 6 — Validation script and the first engine-validation report

**Spec:** §10 items 1, 2, 5 (unit tests, done in Phase 2) and the Bad-year half of item 4, item 8 (the rule), F8, S8. Demo spec §4.10 (stress windows), §5.3 (the mirror).

**Branch:** `feature/backtest-ranges` for the script; the report goes straight to `main`.

### Design decisions made here

- **All on the laptop, read-only, no provider calls:** `LocalStore` over `/mnt/d/portfoliosight-data`, `inputs_from_store(..., asof=origin)` + `build_tensor_full` per (menu, origin, lookback), the fit cached per (menu, origin) across lookbacks (same digest). Served status is today's catalog (every preset fund is served); the inclusion rule is history-based and applies as it would have then; the shape window is what existed, down to the 252-row minimum (`fit_garch_t_panel` falls back below it).
- **The realized year** of a mix is the constant-mix compounding of the next 252 trading days' daily returns, `∏(1 + w'r_t) − 1`, the same convention the engines simulate. A mix with a fund that lacks a day in that year is skipped and counted.
- **Origins:** the last XNYS session of each quarter from 2015-12-31 to 2025-09-30 (40), via `exchange_calendars`; the 10 year-end origins form the non-overlapping set.
- **Mixes per origin and lookback:** frontier nodes at `s_safe`, the domain midpoint and `s_max` under the engine's own `s_safe`; the Optimized point of those columns (`t_suggested`); the entered mix; equal weight; every single fund.
- **Outputs:** raw results as JSON under `runs/backtest/` (gitignored); markdown tables written by the script into `docs/reviews/`; the prose is the implementer's.

### Tasks

- [ ] 6.1 `scripts/backtest_ranges.py` (new) with subcommands: `coverage` (item 1: predicted Bad/Typical/Good and the realized year per (origin, mix, engine, lookback); coverage of `[Bad, Good]` and breaches below Bad for the 40 and for the 10; pinball loss at 2.5/50/97.5 summed over mixes, paired engine against engine per origin; KS of the PIT on the 10 pooled over mixes — needs `simulated_years`), `compare` (item 2 on the live menus at the mirror's current `asof`: Bad under each engine at every frontier node and Optimized point; the percentile at which each stress window's buy-and-hold loss falls in each engine's one-year distribution for the Optimized point at `s_safe`, midpoint and `s_max`; also the full Bad/Typical/Good tables Phase 7 needs for every lookback), `seeds` (item 4, Bad half: seeds 20261013 to 20261017 through `range_model(..., seed)` / `garch_range_model(..., seed)`; the sd of Bad over seeds per node and Optimized point must be ≤ `0.10 σ_w`). Common options: `--store-dir`, `--menus`, `--lookbacks 5y,1y`, `--engines replay,garch`, `--out`.
- [ ] 6.2 `tests/test_backtest_ranges.py`: the quarter-end origin list (first, last, count 40, the 10 year-ends); the realized-year convention on a tiny frame; pinball loss and coverage on hand-made numbers; the PIT of a known distribution; the script runs end to end on the fixture store for two origins with `--engines replay,garch`.
- [ ] 6.3 Run it (about 160 builds; expect 30 to 60 minutes on the laptop), then write `docs/reviews/2026-10-xx_engine-validation.md`: method and what was built; item 1 tables per menu and lookback (40 origins and the 10 year-ends; the Binomial(10, 0.025) note), paired pinball losses with the sign-test count, PIT KS; item 2 tables with the 2008/2020/2022 placements and the "window shorter than a year is a lower bound" note; item 4 table; item 5 a pointer to the tests; item 8 the rule as written and the verdict for `garch` against `replay`; an honesty section on what ten years can and cannot show. No tuning of the rule (F8).
- [ ] 6.4 ROADMAP.md: the "no implementation plan yet" line points to this plan and the report. (Docs, straight to `main`.)

### Done when

- The script runs from the mirror with no network; its tests pass; the report is in `docs/reviews/` with every table and the verdict; the owner can read it and decide (§13 item 12; the default switch is not part of this plan).

---

## Phase 7 — Owner analysis: History replay against the volatility model

**Spec:** complements §10's report; §12 "Level and shape from different regimes, by design"; S4, S5. No code.

**Deliverable:** `docs/reviews/2026-10-xx_replay-vs-volatility-model.md`, straight to `main`.

- [ ] 7.1 Numbers from `scripts/backtest_ranges.py compare` on the mirror at the live `asof` for both presets (Example Portfolio, TSP) and every lookback (`1y`, `2y`, `3y`, `5y`, `10y`, `ew`): per frontier node (48) and the Optimized point of each column, Bad / Typical / Good under `replay` and `garch` and their differences in percentage points. Full tables in an appendix, one table per (menu, lookback).
- [ ] 7.2 Up front, in plain language: how different the two engines actually are (the median and largest differences per menu and lookback; which nodes and lookbacks differ most and why: a calm 1y lookback meets a ten-year shape with 2020 and 2022 in it; bond-heavy nodes where fallback funds dominate; nodes near `s_safe` where the two engines' slider domains differ); which funds were held at constant volatility and what that did; the pool size.
- [ ] 7.3 Each engine's assumptions, weaknesses and strengths: plain language first (what "replaying runs of real days" assumes, what "fitted volatility and fat tails with shocks replayed together" assumes, what each cannot see), then the technical detail second (block bootstrap with mean block 21 days and the sample's own volatility; GARCH(1,1)-t per fund, long-run start, joint residual rows, two-step level scaling, Monte Carlo error at 2,000 paths, the lookback-level versus ten-year-shape choice).
- [ ] 7.4 A closing paragraph that says what this analysis does not decide (the default switch is the owner's reading of the validation report) and links to it.

---

## Risks

- **`arch` 8.0.0 beside pandas 3.0 and numpy 2.5.** Verified importing and fitting on 2026-10-16 (fact 3). If a QSE joint test fails under PS's versions in task 1.7, report it with the failing test; do not patch `qse/`.
- **A fit that lands on a boundary** (`α + β` near 1, `ν` near 2) or does not converge on a real fund becomes a flagged constant-volatility fund (M5). The dry run (task 3.7) shows which funds fall back before anything is deployed.
- **The splice guard on real data.** A large unadjusted corporate action at a fund's splice fails the build on purpose. The mirror dry run finds it on the laptop first; the fix is a data refresh, not an engine change.
- **Determinism across machines.** A fit is deterministic on one machine with one `arch`; laptop and KS-001 may differ in the last bits (BLAS, CPU). The report's figures (laptop) and the live tensors (KS-001) can differ at the fourth decimal; the report says so. The §4.12 determinism test runs on the laptop; KS-001's builds are only checked against themselves (two nightly builds of one generation never happen, so the runbook notes this as untested there).
- **Build time on KS-001.** The fit adds about 4 s per fund set (3.5 s here for 23 funds), the simulation under 1 s, the ranges for 673 mixes about 2 s: a 23-fund custom build should land near 10 s on 4 workers. If 30 s is missed, §9 fallback 1 (float32 panel) once; never fewer paths.
- **Memory.** 93 MB float64 panel (121 MB at 30 funds) plus a ≤ 64 MB work buffer inside the build process, which already holds the fork server; the API keeps at most two float32 panels (≤ 122 MB). Inside 1,536 MB; the Phase 2 RSS test guards the panel path.
- **Schema 3 and the page.** A page that only knows schema 2 cannot read a 0.3.0 tensor (strict zod). Phase 2's frontend deploy must precede Phase 3's backend deploy; the plan's order enforces it.
- **Gate churn.** A-PS-24 (fixture freshness), A-PS-32 (`.dockerignore`, Dockerfile), A-PS-36 and A-PS-38 (URL keys), A-PS-51 (URL reproduction) will need re-freezing in the phases named; A-PS-17/18/19/21/34/45 read kept fields and should stay green. Every re-freeze gets its note.
- **The 0.3.0 outage window** for custom menus between the backend deploy and the first 0.3.0 publication: minutes when the nightly is hand-started, up to a day otherwise. Mitigated by the deploy rule above.
- **Mirror freshness.** `/mnt/d/portfoliosight-data` syncs at 05:30 daily; a dry run or backtest uses the previous day's store, which is fine for both.

## Open questions for the owner

1. **Risk:** the custom-menu outage window at the 0.3.0 deploy (above). The plan hand-starts the nightly right after the deploy, which keeps it to minutes but runs a daytime tier 2/3 walk. Accept, or prefer deploying just before 02:00 PT and taking the longer window?
2. **Risk:** when to retire the Phase 0 rollback point (`2026-10-14-0.2.0` in `meta/pinned.json`, the schema-2 tolerance in the page). Suggested: after the validation report is read and the owner has used the volatility model on the page for a week.

Everything else in this plan is a technical choice the implementer records in the PR body.
