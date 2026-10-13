# Product interfaces the gate tests assume

The tests under `tests/` are the done-gate for `docs/specs/2026-10-13-portfoliosight-demo-design.md`.
They were written before the product, so they fix some names the spec leaves open. Build to these.
Each test's docstring lists, under "Pinned interface", anything further that the test alone needs;
the docstring is authoritative for that test.

## How the tests run

- Every manifest command is
  `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest -q --noconftest -p no:cacheprovider <one test file>`.
  Each test file is self-contained (no `conftest.py`, no shared helper) and is frozen with the gate.
- **Virtualenv re-exec rule.** `python3` in that command is whatever is on `PATH`, not the project
  environment. A Python-side test therefore re-runs itself inside `<repo>/.venv/bin/python` (in a
  linked worktree: the main checkout's `.venv`), with the repo root first on `sys.path`. That
  environment must hold `.[api,dev]` (pytest included). With no `.venv` the test runs in the
  calling interpreter.
- Front-end unit assertions write an embedded vitest file to `web/tests/__gate__/` and run
  `web/node_modules/.bin/vitest run tests/__gate__/<name>.test.ts` in vitest's plain node
  environment (no jsdom, no Cloudflare pool). The vitest config must include `tests/**/*.test.ts`.
  `web/worker/index.ts` and `web/worker/share.ts` must import cleanly there.
- UI assertions run `npm run build` in `web/`, serve `web/dist` with `vite preview`, write an
  embedded Playwright spec and its own config to `web/e2e/__gate__/`, and run
  `web/node_modules/.bin/playwright` (projects: chromium 1366x900, and chromium with the
  "iPhone 13" profile). The spec mocks `/api/*` itself with `page.route`; no product mock server
  is used. `web/` needs `@playwright/test`, `vitest` and `vite` installed, with a chromium build.
- Live and production assertions read secrets from the environment only. Load
  `~/.secrets/portfoliosight.env` before `conductor assert run`. Names: `PS_GATE_SECRET`,
  `TIINGO_API_KEY`, `CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_API_TOKEN`,
  `CLOUDFLARE_R2_ACCESS_KEY_ID`, `CLOUDFLARE_R2_SECRET_ACCESS_KEY`, `PS_SHARE_TEST_RECIPIENT`.
  A-PS-32 and A-PS-52 also need them, to scan for leaked values. The ssh host is
  `PS_KS001_SSH_HOST` (default `KS-001-jeff`).
- A missing tool, secret, fixture or permission is a failure, never a skip. Messages that start
  with `BLOCKED:` mean an outside dependency, not a product defect; the gate still reads red.
- **ruff and pyright must exclude `assertions/`.** A-PS-01 and A-PS-65 run `ruff check .`,
  `ruff format --check .` and `pyright .` over the whole repo, which contains these frozen tests.
  Exclude `assertions/` in the `ruff` and `pyright` configuration in `pyproject.toml`.

## Python

- **Store** (`portfoliosight/data/store.py`): `LocalStore(root)` with `get(key) -> bytes` (raises
  `KeyError` when absent), `put(key, data: bytes) -> None`, `exists(key) -> bool`,
  `list(prefix="") -> list[str]` (full keys, sorted), `delete(key) -> None`. Key layout as spec
  §5.3. Tests use only these five methods and may wrap the store in a recording proxy.
- **Canonical record** at `prices/{SYMBOL}.parquet`: a parquet frame with columns `date`
  (datetime64[ns], tz-naive), `close`, `tr_index`, `div_cash`, `split_factor`. `tr_index` is 1.0
  on the first row and NaN on price-only rows after `adjusted_through`.
- **Manifest** `meta/manifest.json`: `{"symbols": {"<ID>": {"name", "kind", "tier", "income",
  "source", "first_date", "last_date", "adjusted_through", "status", "reason", "fetched_at"}}}`,
  dates as ISO strings. `meta/symbols.json` is the body of `GET /api/symbols` (spec §6).
  `meta/current.json` is `{"generation": G, "published_at": iso}`. `meta/{G}/generation.json`
  has at least `generation`, `asof`, `engine_version`.
- **Calendar** (`portfoliosight/data/calendar.py`): `generation_date(run_at: datetime) -> date`
  (`run_at` timezone-aware; the rule uses the scheduled start 02:00 America/Los_Angeles on
  `run_at`'s Los Angeles date) and `generation_id(d_g: date, engine_version: str) -> str`.
  The engine version is `portfoliosight.engine.ENGINE_VERSION` (str).
- **Providers**: `portfoliosight.data.providers.tiingo.TiingoProvider()` (reads `TIINGO_API_KEY`
  from the environment; HTTP through `requests`, so `responses` can replay it) and
  `portfoliosight.data.providers.tsp.TspProvider()`. Both follow the Protocol of spec §5.1:
  `name`, `fetch_daily(symbol, start, end) -> DataFrame` (tz-naive `DatetimeIndex` named `date`,
  columns `close, adj_close, div_cash, split_factor`; an empty frame means no data),
  `fetch_meta(symbol)`. Fake providers in tests implement the same three members.
- **Recorded fixtures** (spec §10): provider JSON under `tests/fixtures/provider/` (raw Tiingo
  rows; a ticker's file is the first `*.json` whose stem starts with the ticker, case-insensitive),
  a TSP CSV slice (a `*.csv` under `tests/fixtures/` whose name contains `tsp`), the fixture lake
  `tests/fixtures/lake/*.parquet`, `tests/fixtures/synthetic_23.parquet`, and the UI fixture
  `web/fixtures/guide2017_5y.json` (a spec §7 tensor).
- **Tensor build CLI**: `python scripts/build_tensor.py --returns <parquet> --lookback <id>
  --asof YYYY-MM-DD --out <json> [--caps <json file>]`, run from the repo root; exit 0 and a spec
  §7 tensor at `--out`. Returns parquet: `DatetimeIndex` named `date`, one float column per fund id
  of daily simple returns, NaN where the fund has no return. `--caps` file: a JSON list of
  `{"id", "min", "max"}` with `null` for the default rule. "The fixture tensor" in an engine
  assertion is a fresh build from `tests/fixtures/synthetic_23.parquet`, lookback `5y`, `--asof`
  the last date of that parquet's index. N is always `len(tensor["universe"]["funds"])`.
- **API app**: `portfoliosight.api.app.create_app(*, store=None, clock=None, build_fn=None,
  start_worker=True) -> FastAPI`. With all defaults it configures itself from the environment
  (`PS_STORE`, `PS_LOCAL_STORE_DIR`, `PS_GATE_SECRET`). `clock` returns epoch seconds; `build_fn`
  is the callable the queue worker uses to build one tensor; `start_worker=False` pauses the worker.
- When the gate shells out to the product's own `pytest`, it drops
  `PYTEST_DISABLE_PLUGIN_AUTOLOAD`, passes its own empty coverage config, and rejects
  `pragma: no cover` in `portfoliosight/engine/`.

## TypeScript and the page

- **Math** (`web/src/math/portfolio.ts`): `portfolioMath(tensor)` returns an object with
  `stats(w) -> {mu, sigma, enb}`, `range6m(mu, sigma) -> {low, typical, high}`,
  `interpolate(s, t) -> number[]`, `frontierCurve() -> {sigma: number[], mu: number[]}`,
  `riskSliderDomain() -> {s_safe, s_max}`, `tAuto(s) -> number`.
- **Tensor loader**: `parseTensor(json: unknown)` exported from `web/src/api/client.ts` (zod;
  throws on a bad tensor; importing the module has no side effects and needs no DOM).
- **Worker**: `web/worker/index.ts` is the standard module shape, `export default { fetch(request,
  env, ctx) }`, and compares secrets with `crypto.subtle.timingSafeEqual`.
- **DOM**: only the `data-testid`s of spec §10, the copy of spec §3.6 and §3.7,
  `html[data-theme]`, the URL keys of spec §8.1 and standard ARIA. `chart-canvas` is the
  `<canvas>` element. Axes are d3-axis ticks (`g.tick` with a `line` and a percent `text`); the
  UI tests derive the chart scales from them.

## Names pinned by single tests (see each docstring for signatures)

- Data: `portfoliosight.data.returns.build_tr_index`, `build_returns`, `window_sample`;
  `portfoliosight.data.download.run(mode, *, store, providers, clock, sleep, symbols=None,
  tiers=None)` and `plan_refresh`; `portfoliosight.data.manifest.status_for`;
  `portfoliosight.data.providers.base.RateLimited` and `SymbolMeta`;
  `portfoliosight.data.providers.tsp.parse_tsp_csv`; `portfoliosight.data.cache.fetch_into_cache`
  and `evict`; the `meta/budget.json` shape; `scripts/r2_backup.sh` and
  `scripts/install_backup_cron.sh` read `PS_ENV_FILE`, else `~/.secrets/portfoliosight.env`.
- Engine: `torsion.min_torsion`, `torsion.effective_number_of_bets`, `optimize.cholesky_factor`,
  `tensor.check_weights`, `tensor.InvariantError`, `tensor.select_window`,
  `tensor.renormalize_allocation`, `suggest.suggested_floor`, `stats.estimate_moments`,
  `stats.ew_weights`, `stats.menu_beta_blend`, `stats.risk_free_rate`, `caps.resolve_bounds`,
  `caps.greedy_fill`, `caps.CapsError`, `stress.stress_returns`; `scripts/make_fixtures.py --out`;
  `portfoliosight/engine/tensor.schema.json`. Engine modules counted by A-PS-25: at least six of
  `stats, torsion, optimize, surface, suggest, stress, caps, builder`.
- API and nightly: `portfoliosight.api.queue.build_job` (the default `build_fn`; it writes the
  tensor key itself and never over an existing key), `portfoliosight.api.hashing.universe_hash`,
  `portfoliosight.jobs.nightly.run(*, store, now, providers, build_fn=None)`. The gate decision
  is the return value of `hmac.compare_digest`, called on every `/v1/` request. Switch off the
  FastAPI docs routes (`/docs/oauth2-redirect` contains `auth`).
- Front end: `web/src/math/amounts.ts` (`amountsToWeights`, `percentTotal`, `tradeDeltas`);
  `web/src/state/url.ts` (`encode`, `decode`, the `UrlState` shape); `web/src/state/store.ts`
  (`createStore`); `web/worker/share.ts` (`handleShare`, `shareLimit`); `ShareDialog` props
  `{open, url, privatePreview, onClose}`; `diversificationWord` and `stressReturn` in
  `web/src/math/portfolio.ts` (see A-PS-47 and A-PS-50). `web/package.json` scripts `build`,
  `lint`, `typecheck`, `test`. `web/e2e/smoke.spec.ts` declares `test("DoD-NN ...")` with static
  titles.
- Configuration: `[tool.ruff] extend-exclude = ["assertions"]` and `[tool.pyright]
  ignore = ["assertions"]` (pyright `exclude` alone is not enough; the gate runs
  `pyright -p <root> .`). `testpaths = ["tests"]` for pytest. The gate interpreter needs PyYAML
  (A-PS-32). The page must load nothing from third-party origins: the production Playwright
  runs send `x-ps-gate` on every request the page makes.

## Encoding decisions (accepted by the coordinator)

- The gate holds 68 machine assertions, A-PS-01 to A-PS-68. The real-browser check through
  Cloudflare's human check is not in the gate; it is the owner's manual check H-PS-01 in the
  assertions file.
- A-PS-10 has no exception for deployment or smoke scripts. Every `http(s)://` literal in a
  `*.py`, `*.sh` or shebang file under `portfoliosight/data|engine|api|jobs` and `scripts/` must
  be on one of the four allowed hosts, comments included. Deployment scripts take API base URLs
  from environment variables or arguments, never from literals.
- Share caps (A-PS-38, A-PS-64): a request carrying a valid `x-ps-gate` header is exempt from the
  per-IP share caps (1 per minute, 3 per day); the global daily cap still applies to it. Per-IP
  caps are asserted for requests without the header. The production send uses the header and
  goes only to `PS_SHARE_TEST_RECIPIENT`.
- A-PS-65: "on main" is read as "on the checked-out revision the gate runs on" (the run branch
  head during a conductor run). The test never looks at the branch name.
- A-PS-64: an absent `PS_SHARE_TEST_RECIPIENT` is a failure, not a skip.
- Repeat safety (the worker runs the whole gate many times a day):
  - A-PS-14 spends two Tiingo price requests per run (VTI, VBIAX) and READS the recorded
    `meta/provider_limits.json` (from the R2 bucket, or from `PS_LOCAL_STORE_DIR` when
    `PS_STORE=local`); it never re-runs `measure-limits`. Run `download --mode measure-limits`
    once against the store the gate reads.
  - A-PS-58 runs `scripts/r2_backup.sh` itself before comparing, and ignores objects written
    since that backup started, so the nightly refresh cannot turn it red.
  - A-PS-60 takes its cap override from the second of the UTC day (`0.24 - k * 1e-6`), so each
    run has a fresh key. Each green run is one real build on KS-001 and one tensor in R2.
  - A-PS-64 sends one real email per UTC day; later runs that day do everything except click
    Send. The marker is `${XDG_STATE_HOME:-~/.local/state}/portfoliosight/gate-share-sent-<date>`.
  - A-PS-68 sends 25 GETs and 25 POSTs, then waits 61 s so the limiters are clear.
- A-PS-66, 67, 68: a withdrawn `Zone WAF Edit` permission fails with a `BLOCKED:` message.
- A-PS-53: "menu of N" accepts N as the included fund count or included plus excluded.
- Owner decision 2026-10-13 (the one sanctioned change of the frozen gate in this run): EFA holds
  FIENX's place in the default menu, so the default 5y tensor (and `web/fixtures/guide2017_5y.json`)
  has 23 included funds and an empty `universe.excluded`. FIENX stays a tier 2 catalog symbol that
  is not served, reason `converted to an ETF; no data since 2024-10-30`; `POST /v1/tensors`
  accepts a menu holding it and the tensor lists it in `universe.excluded`. Excluded-fund handling
  is asserted where a fund is really set aside:
  - A-PS-43: the mock's second menu is the 23 funds plus FIENX and its tensors set FIENX aside,
    with a different reason at 5y and at 10y (reached with `chip-settings` and `lookback-10y`);
    the default view must show no `excluded-note` on any fund row.
  - A-PS-56: production; the default tensor sets nothing aside, and the 23 default funds plus
    FIENX at 5y resolve to a schema-valid tensor that sets exactly FIENX aside with its reason.
    Same key on every run: one real build per generation, then served as stored.
  - A-PS-63: production; besides the default menu, a custom menu loaded with `/?f=…&lb=10y` (two
    of BND, VTI, AGG, VNQ plus a served fund too young for the 10y view, SGOV when it qualifies)
    must list the young fund in Settings. Same key on every run: one real build per generation.
  - A-PS-29: the extra tickers outside the guide menu list FIENX where they listed EFA.
  The record of every changed leg is `docs/reviews/2026-10-13_gate-change_fienx-to-efa.md`.
- A-PS-13: the 403 "names the missing scope" leg cannot be forced against the live bucket.
