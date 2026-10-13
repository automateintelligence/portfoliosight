# PortfolioSight deployment runbook (KS-001 and Cloudflare)

Spec: `docs/specs/2026-10-13-portfoliosight-demo-design.md` §9.5. Each step below records what
was run, the result with secrets removed, and the date. A step that is not done says so.

Conventions used in every command here:

- Settings and secrets come from the laptop env file: `set -a; . ~/.secrets/portfoliosight.env; set +a`.
- No secret value is written in this file. Where a rule or a command holds the gate secret,
  this file shows `<PS_GATE_SECRET>`.
- The server is named only by the setting `PS_KS001_SSH_HOST`.

## Status on 2026-10-13

Done: step 3, step 6, and the Worker part of step 7 (deployed in private preview, with no data
behind it yet). Not done: steps 1, 2, 4, 5 and 8, the data checks of step 7, and the benchmark.
They wait on one owner item: the two R2 keys in the laptop env file are scoped to other
buckets and are refused (403) on `portfoliosight-data` (issue #79). Everything left, in order,
is under "Remaining" at the end of this file.

## Step 1. R2 bucket

The bucket `portfoliosight-data` exists (created 2026-10-13 through the Cloudflare API).
`python -m portfoliosight.data.store --verify` is refused with 403 until the owner replaces the
two R2 keys. Not done yet; see "Remaining".

## Step 2. Seed from the laptop

Not done yet.

## Step 3. Data licensing decision

Owner decision 2026-10-13: Tiingo data under personal use for development and testing; commercial license before public opening (§9.6).

The site stays in private preview (`PS_PRIVATE_PREVIEW="1"`) until the owner buys the
commercial license. The provider tier and limits are still measured and recorded under
"Measured".

## Step 4. KS-001: clone, secrets, deploy, catch-up, first generation

Not done yet.

## Step 5. Tunnel ingress and DNS

Not done yet.

## Step 6. WAF rules and rate-limiting rule

Done 2026-10-13, from the laptop, through the API.

The gate secret was generated first, on the laptop only (48 hex characters, appended to the
laptop env file; nothing was sent to KS-001):

```
scripts/ks001_secrets.sh --ensure-gate-secret
```

State before: the zone had no DNS record and no custom or rate-limiting ruleset.

```
set -a; . ~/.secrets/portfoliosight.env; set +a
python scripts/cloudflare_rules.py --dry-run     # three rules to create, secret shown as [redacted]
python scripts/cloudflare_rules.py --apply       # three rules created
python scripts/cloudflare_rules.py --apply       # second run: three times "unchanged"
```

Rules now on the zone `portfoliosight.ai` (and nothing else was written):

| Phase | Rule | Action | Expression |
|---|---|---|---|
| `http_request_firewall_custom` | `ps-challenge-site` | Managed Challenge | `(http.host in {"portfoliosight.ai" "www.portfoliosight.ai"}) and not any(http.request.headers["x-ps-gate"][*] == "<PS_GATE_SECRET>")` |
| `http_request_firewall_custom` | `ps-block-api-direct` | Block | `(http.host eq "api.portfoliosight.ai") and not any(http.request.headers["x-ps-gate"][*] == "<PS_GATE_SECRET>")` |
| `http_ratelimit` | `ps-tensor-post` | Block | `(http.request.uri.path eq "/api/tensors")`, 20 requests per 10 s per IP (`ip.src`, `cf.colo.id`), blocked for 10 s |

Checked 2026-10-13 with `curl` from the laptop (browser-like user agent, no cookies):

- `GET /` without the header: 403, `cf-mitigated: challenge`, Cloudflare's challenge page, no
  `x-ps-source` (the Worker was not reached). The same for `GET /api/presets`.
- `GET /` with a wrong `x-ps-gate` value: 403, `cf-mitigated: challenge`.

If the gate secret is ever changed: change it in the laptop env file, run
`python scripts/cloudflare_rules.py --apply` (the two WAF rules are updated in place), set the
Worker secret again (step 7) and copy the secrets to KS-001 again (step 4).

Not checked yet (they need the API host of step 5 and data): the block on
`api.portfoliosight.ai`, and the rate limit in action.

## Step 7. Worker deploy

Worker part done 2026-10-13, from `web/` on the laptop. State before: the account had no
Worker named `portfoliosight` and no custom domain in this zone.

```
set -a; . ~/.secrets/portfoliosight.env; set +a
npm run build
npx wrangler deploy --dry-run        # bindings as in wrangler.jsonc
npx wrangler deploy                  # creates the Worker and both custom domains
for name in PS_GATE_SECRET MAILCHANNELS_API_KEY MAILCHANNELS_DKIM_PRIVATE_KEY; do
  printf '%s' "${!name}" | npx wrangler secret put "$name"    # the value goes on stdin only
done
```

The Worker was deployed before its secrets on purpose: `wrangler secret put` on a Worker that
does not exist yet creates a draft outside the reviewed configuration. In the minute between,
the site answered nobody (the edge challenges a request without the header, and the Worker
refuses every request while it has no secret).

What exists now:

- Worker `portfoliosight`, compatibility date 2026-09-01, `workers_dev: false`,
  `preview_urls: false`.
- Custom domains `portfoliosight.ai` and `www.portfoliosight.ai` (wrangler created the two
  proxied records; the zone holds no other record).
- Bindings: `DATA` → R2 bucket `portfoliosight-data`; `SHARE_LIMITER` → Durable Object class
  `ShareLimiter` (namespace `portfoliosight_ShareLimiter`, SQLite-backed, migration `v1`);
  `ASSETS`; vars `API_ORIGIN`, `SHARE_FROM`, `SHARE_REPLY_TO`, `SHARE_CAP_IP_MINUTE`,
  `SHARE_CAP_IP_DAY`, `SHARE_CAP_GLOBAL_DAY`, and `PS_PRIVATE_PREVIEW` = `"1"`.
- Secrets (names only): `PS_GATE_SECRET`, `MAILCHANNELS_API_KEY`,
  `MAILCHANNELS_DKIM_PRIVATE_KEY`. The mail key is the real one, not the `test` no-op.

Rollback: `npx wrangler rollback` from `web/`.

Checked 2026-10-13 with `curl` from the laptop and the Cloudflare API:

| Check | Result |
|---|---|
| `GET /` with the header | 200, `text/html`, title "PortfolioSight", no private-preview text, no `cf-mitigated` |
| `GET /api/presets` with the header | 503 `{"error":{"code":"unavailable",…}}` with `x-ps-preview: 1`: the Worker runs, preview is on, and the bucket has no generation yet |
| `GET /api/symbols` with the header | 503 `unavailable`, for the same reason |
| `GET https://www.portfoliosight.ai/?u=tsp` with the header | 301 to `https://portfoliosight.ai/?u=tsp` |
| Worker setting `PS_PRIVATE_PREVIEW` (API) | `"1"` |
| `workers.dev` for the script (API) | `enabled: false`, `previews_enabled: false` |
| `GET` on the account's `portfoliosight.<subdomain>.workers.dev` | 404, with and without the header |
| Durable Object namespace (API) | `portfoliosight_ShareLimiter`, class `ShareLimiter`, `use_sqlite: true` |
| `POST /api/share`, site origin, recipient `not an address` | 400 `invalid_recipient` |
| `POST /api/share`, site origin, two addresses in `to` | 400 `invalid_recipient` |
| `POST /api/share` without the site origin | 403 `forbidden_origin` |

No email was sent. Limits of these checks, stated plainly:

- The share validators answer before the limiter is asked, so the three share requests above
  never reached the `ShareLimiter` object. Its migration is applied and its namespace exists,
  but its SQL has still not run on real storage. The first valid share (the Phase 7 share test,
  one message to `PS_SHARE_TEST_RECIPIENT`) is the first real run.
- The preview page itself (403 with "PortfolioSight is in private preview") cannot be seen from
  outside without the header while the edge challenge stands in front of it; the evidence that
  preview is on is the Worker setting and the `x-ps-preview: 1` header.
- A real browser passing the Managed Challenge is the owner's check H-PS-01 (Phase 7).

Not done yet: evidence that `portfoliosight@automateintelligence.ai` accepts mail, the
`x-ps-source: r2` checks, and the Playwright page load with data. See "Remaining".

## Step 8. Nightly timer, backup and cron

Not done yet.

## Measured

- Provider tier and limits: not measured in production yet.
- 23-fund build time on KS-001: not measured yet.
- Grid in effect: not measured yet.
- Six-lookback preset build time: not measured yet.

## Remaining (part 2), in order

Nothing below has been run. It starts when the owner has replaced
`CLOUDFLARE_R2_ACCESS_KEY_ID` and `CLOUDFLARE_R2_SECRET_ACCESS_KEY` in the laptop env file with
a token that has Object Read & Write on the bucket `portfoliosight-data` only (Cloudflare
dashboard → R2 → Manage R2 API Tokens; issue #79). The Cloudflare API token is not an R2 key
and is not used as one.

Every block assumes the repository root and
`set -a; . ~/.secrets/portfoliosight.env; set +a`. `$SHA` is the head of the run branch.
Record each result here, with the date, as it completes.

### R1. Bucket verify (step 1)

```
PS_STORE=r2 PS_R2_BUCKET=portfoliosight-data python -m portfoliosight.data.store --verify   # exit 0
```

### R2. Seed and recorded limits (step 2)

```
python scripts/seed_r2_from_lake.py --adjusted-through 2026-03-27 --dry-run
python scripts/seed_r2_from_lake.py --adjusted-through 2026-03-27
```

- The date is the lake's latest adjustment (with 2026-02-27 the script refuses). If the dry-run
  prints another "latest adjustment in the lake" date, use that one. Expected on 2026-10-13:
  1,400 symbols to seed, 5 not seedable, 0 violations.
- Check: `meta/manifest.json` lists at least 1,400 symbols with `source: seed`, `status: pending`.
- Copy the recorded provider limits from the laptop's local store to the bucket. The probe is
  not run again:

```
python - <<'PY'
import os
from pathlib import Path
from portfoliosight.data.store import LocalStore, store_from_env
state = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state")
local = LocalStore(state / "portfoliosight" / "store")
os.environ["PS_STORE"] = "r2"
store_from_env().put("meta/provider_limits.json", local.get("meta/provider_limits.json"))
PY
```

### R3. KS-001: clone, secrets, deploy (step 4)

```
ssh "$PS_KS001_SSH_HOST" 'test -d ~/portfoliosight/.git && git -C ~/portfoliosight fetch github || git clone -o github "$(printf "%s://github.com/automateintelligence/portfoliosight.git" https)" ~/portfoliosight'
scripts/ks001_secrets.sh                 # prints key names only; PS_GATE_SECRET already exists
scripts/deploy_ks001.sh "$SHA"           # ends with "... is healthy on <host>"
ssh "$PS_KS001_SSH_HOST" 'docker stats --no-stream portfoliosight-api; docker ps --format "{{.Names}} {{.Ports}}"'
```

- Check the limits (2 CPUs, 1536 MB) and that no other container or port changed. Take the
  `docker ps` listing before the deploy too, to compare.
- The container needs the R2 keys, so run `scripts/ks001_secrets.sh` only after the keys are
  replaced on the laptop.

### R4. Catch-up and first generation (step 4, continued)

On KS-001, in `~/portfoliosight`, with `C="docker compose -f deploy/docker-compose.yml run --rm --no-deps nightly"`:

```
$C python -m portfoliosight.data.download --mode catch-up --tiers 1
$C python -m portfoliosight.data.download --mode catch-up --tiers 2
$C python -m portfoliosight.data.download --mode catch-up --tiers 1,2     # second pass, for names
$C                                                                        # the nightly: first preset build
```

- `--mode measure-limits` is not run again: the limits were measured once on 2026-10-13
  (Starter: 45 per hour, 900 per day, 450 symbols per month) and R2 copies that record.
- On Starter the catch-up sleeps to the next hour when the hourly budget is spent and stops
  cleanly when the daily budget is spent; it resumes where it stopped, and the nightly timer
  carries on with whatever is left.
- The second catch-up pass spends one meta request per seeded symbol whose name is still its
  ticker (about 200). Check afterwards that no `ok` symbol in `meta/manifest.json` has `name`
  equal to its id.
- After the nightly: `meta/current.json` points at a generation with 12 tensors.
- Run the nightly right after every deploy that changes the engine version: until a generation
  for the new version is published, custom builds answer `engine_version_mismatch`.
- On a failure: `docker logs portfoliosight-api` (redacted) into the PR, fix in code, redeploy.
  The container limits are never relaxed.

### R5. Tunnel ingress and DNS (step 5)

Each step's rollback covers everything before it.

```
# (a) baseline, from the laptop: every hostname already in the ingress and its HTTPS status
ssh "$PS_KS001_SSH_HOST" "sudo grep -E '^\s*-?\s*hostname:' /etc/cloudflared/config.yml"
# (b) install on the host; prints "installed ...; backup: <file>" (keep the backup name)
ssh "$PS_KS001_SSH_HOST" "cd ~/portfoliosight && PS_API_SERVICE_URL='$PS_API_SERVICE_URL' bash scripts/cloudflared_ingress.sh install"
# (c) DNS; keep the JSON line it prints
python scripts/cloudflare_dns.py ensure-cname --name api.portfoliosight.ai \
  --target 222b8001-009a-47b2-8a31-3ea624ce32ca.cfargotunnel.com --proxied | tee "$HOME/.local/state/portfoliosight/dns-result.json"
# (d) the new endpoint (allow two minutes for DNS)
printf 'x-ps-gate: %s\n' "$PS_GATE_SECRET" | curl -sS -o /dev/null -w '%{http_code}\n' -H @- "$(printf '%s://api.portfoliosight.ai/v1/health' https)"   # 200
curl -sS -o /dev/null -w '%{http_code}\n' "$(printf '%s://api.portfoliosight.ai/v1/health' https)"                                                    # 403
```

- (b) re-checks every pre-existing hostname itself and restores the previous file if one
  answers differently. Confirm from the laptop as well that each answers as in (a).
- The script validates with `cloudflared tunnel --config <candidate> ingress validate`. This
  form has not been run against the host's cloudflared (2026.1.2) yet. If cloudflared refuses
  the command line itself, the script stops before touching the live file; fix the form in the
  script, do not bypass the validation.
- Because the WAF rule `ps-block-api-direct` already exists, the 403 without the header is
  Cloudflare's block page, not the application's JSON.
- If (d) fails: `python scripts/cloudflare_dns.py rollback-cname --result "$HOME/.local/state/portfoliosight/dns-result.json"`
  (deletes the record only if this attempt created it), then
  `ssh "$PS_KS001_SSH_HOST" "cd ~/portfoliosight && bash scripts/cloudflared_ingress.sh rollback <backup>"`,
  re-check (a), record the failure here, fix, retry.
- If the token cannot edit DNS: create the proxied CNAME in the dashboard (name `api`, target as
  above), or roll back (b) and stop.

### R6. Checks that need data (steps 6 and 7)

- `GET /api/presets` with the header: 200, `x-ps-source: r2`, two presets × six lookbacks ready.
- `GET api.portfoliosight.ai/v1/health` without the header: Cloudflare's block page.
- 25 `POST /api/tensors` in 10 s: at least one 429 without `x-ps-source`; 25 `GET`s: none.
- `CF-Connecting-IP` through the Worker: send six `POST /api/tensors` from the laptop within a
  minute and confirm in `docker logs portfoliosight-api` (or by the application's own 429 with
  `x-ps-source: origin` on the sixth) that the limiter keys on the laptop's public address and
  not on one shared Cloudflare address. If every visitor shares one address, fix the Worker's
  forwarding before going further.
- Mail alias: `swaks --to portfoliosight@automateintelligence.ai --quit-after RCPT` against the
  domain's MX answering 250 (no message is sent), or the owner item "create the alias on the
  mail host". A MailChannels 202 is not evidence that the alias exists.
- Page load with data: Playwright with the header (the gate tests A-PS-54 … A-PS-56,
  A-PS-66 … A-PS-68).

### R7. Benchmark (plan task 6.8)

With `queue.depth == 0`, `POST` the default preset's funds with `max = 0.24` on the first fund
(walk down by 0.0001 until the first answer is 202), measure POST → first 200, and write the
seconds, the override and the tensor's grid on one line under "Measured". Above 30 seconds: set
`PS_GRID_NX=32` and `PS_GRID_NY=24` in the compose `environment`, redeploy, measure again with a
fresh key, record both. Then the six-lookback totals from `meta/status.json.preset_build_seconds`.

### R8. Timer, backup, cron (step 8)

```
scripts/deploy_ks001.sh --install-timer "$SHA"
ssh "$PS_KS001_SSH_HOST" 'sudo systemctl start portfoliosight-nightly.service; systemctl is-enabled portfoliosight-nightly.timer; journalctl -u portfoliosight-nightly -n 20 --no-pager'
```

Then the laptop backup, made durable before cron is enabled. `aws` on the laptop is a pyenv
shim under `$HOME/.pyenv/shims`, which neither cron's `PATH` nor the directories
`scripts/r2_backup.sh` appends cover: make the script find it (for example by appending that
directory to its `PATH` line, with a test), then:

```
install -D -m 755 scripts/r2_backup.sh "$HOME/.local/share/portfoliosight/bin/r2_backup.sh"
mkdir -p "$HOME/programming/portfoliosight/scripts"
[ -f "$HOME/programming/portfoliosight/scripts/r2_backup.sh" ] || ln -s "$HOME/.local/share/portfoliosight/bin/r2_backup.sh" "$HOME/programming/portfoliosight/scripts/r2_backup.sh"
env -i HOME="$HOME" LOGNAME="$(id -un)" SHELL=/bin/sh PATH=/usr/bin:/bin /bin/sh -c "$HOME/programming/portfoliosight/scripts/r2_backup.sh >> $HOME/.local/state/portfoliosight/r2_backup.log 2>&1"   # exit 0, D: mounted
scripts/install_backup_cron.sh
crontab -l | grep -c r2_backup.sh        # 1
```

and a restore dry-run (`aws s3 sync --dryrun` in the restore direction) that prints no upload.
The nightly gate check (A-PS-57) turns green on the first timer run at or after 08:00 Pacific
on a later day.

### R9. Before the part 2 pull request

`ruff check . && ruff format --check . && pyright . && pytest --cov=portfoliosight --cov-report=term-missing`,
then the gate with the env file loaded (`conductor assert run --level spec`), read for
A-PS-54 … A-PS-60 and A-PS-66 … A-PS-68, and a scan of the diff for the value of each of the
seven credential names (count 0, values never printed).
