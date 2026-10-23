# PortfolioSight

A free, one-screen portfolio tool at `portfoliosight.ai`: pick a fund menu (a 401(k) menu, the
TSP funds, any served tickers), see its best mixes at each level of risk over a map of how spread
out each mix is, and move one risk slider and one diversification slider. Educational, historical
math, not investment advice. The site is in **private preview** for now. 
Spec: `docs/specs/2026-10-13-portfoliosight-demo-design.md`. What comes next: `ROADMAP.md`.

## Layout

```
portfoliosight/data/    providers (Tiingo, tsp.gov) behind one Protocol, returns, manifest, R2/local store
portfoliosight/engine/  pure math: moments, caps, frontier, diversification surface, stress, tensor builder
portfoliosight/api/     FastAPI build service (/v1/*): gate, limits, queue, presets, health
portfoliosight/jobs/    one tensor build from the store; the nightly refresh and publish
web/                    Vite + React + D3 page (src/), Cloudflare Worker (worker/), tests, e2e/
deploy/                 Dockerfile, compose files, systemd timer templates for KS-001
scripts/                seed, backup, deploy and smoke scripts, fixture builders
data/                   universes and tiers, presets, the default menu's holdings file
docs/                   specs/, plans/ (plan and deployment runbook), reviews/
assertions/             the frozen done-gate for the spec (never edited)
```

## Commands

```
uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -e ".[api,dev]"
source .venv/bin/activate        # every command below is run from the repository root
ruff check . && ruff format --check . && pyright .
pytest --cov=portfoliosight --cov-report=term-missing      # live tests need PS_LIVE_TESTS=1
(cd web && npm ci && npm run lint && npm run typecheck && npm test && npm run build && npm run e2e:local)
scripts/smoke.sh                 # one production test per definition of done, desktop and phone
scripts/smoke_preview.sh         # production: nothing is served without the gate secret
scripts/deploy_ks001.sh <sha>    # build and start the service on KS-001; same command rolls back
```

Settings, hosts and secrets are `KEY=value` lines in `~/.secrets/portfoliosight.env`, never committed.

## Storage and data

- Cloudflare R2 bucket `portfoliosight-data` is the canonical store: price records, the manifest,
  the catalog and every tensor. KS-001 keeps nothing but a 300 MB scratch cache.
- `/mnt/d/portfoliosight-data` on the laptop is the backup of the bucket (`scripts/r2_backup.sh`,
  nightly from cron; `--restore` copies it back). With the drive unmounted the backup stops and says so.
- The lake that seeds the bucket once is the WSL working copy
  `~/tft-quantile-forecaster/data/tft/raw/eodhd/datalake_us_core/` (`scripts/seed_r2_from_lake.py`);
  `/mnt/d/tft-quantile-forecaster` is only QSE's mirror of it, and nothing here writes to either.
- After the seed, prices come from Tiingo (close, dividends, splits; total return is rebuilt from
  those) and from tsp.gov for the TSP funds, each behind the provider Protocol. The nightly job on
  KS-001 refreshes within the measured request budget, rebuilds the two ready-made menus for six
  lookbacks, and publishes a new generation only when all twelve tensors exist.
- Stocks (and any fund no provider has refreshed) come from the owner's repaired QSE lake instead:
  `scripts/sync_lake.py`, a laptop cron job on weekdays, uploads each symbol the lake vouches as
  current once QSE's 06:45 PT run is complete, marks it `source: lake` in the manifest, and the
  nightly spends no Tiingo request on it. Tiingo and tsp.gov stay the source of the ready-made
  menus' funds. Entries whose recent dividends come from yfinance carry `relies_on_yfinance`;
  they are reviewed before public launch (spec §5.4).

## Deployment

- A Cloudflare Worker (`web/worker`, `web/wrangler.jsonc`) serves the page, reads tensors from R2,
  forwards builds and sends the share email. The only human check is Cloudflare's own; while
  `PS_PRIVATE_PREVIEW` is `"1"` the Worker also requires the gate secret.
- The build service runs on KS-001 in one container (`deploy/docker-compose.yml`, 4 CPUs,
  1536 MB) behind a cloudflared tunnel; a systemd timer runs the nightly job.
- Steps, measurements and owner checks: `docs/plans/2026-10-13-ks001-cloudflare-runbook.md`.
