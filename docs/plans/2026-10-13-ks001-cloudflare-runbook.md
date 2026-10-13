# PortfolioSight deployment runbook (KS-001 and Cloudflare)

Spec: `docs/specs/2026-10-13-portfoliosight-demo-design.md` §9.5. Each step below records what
was run, the result with secrets removed, and the date. A step that is not done says so.

Conventions used in every command here:

- Settings and secrets come from the laptop env file: `set -a; . ~/.secrets/portfoliosight.env; set +a`.
- No secret value is written in this file. Where a rule or a command holds the gate secret,
  this file shows `<PS_GATE_SECRET>`.
- The server is named only by the setting `PS_KS001_SSH_HOST`.

## Status on 2026-10-13

Done: steps 1, 2, 3, 4, 6, the Worker part of step 7, the timer and the cron line of step 8, and
the first generation (`2026-10-12-0.1.0`, both presets, twelve tensors, served from R2).

Not done, each waiting on the owner (issue #86, details under "Remaining"):

- Step 5: `api.portfoliosight.ai` is not routed. The tunnel takes its ingress from Cloudflare
  (remotely managed), not from the file on the host, and the project's API token may not read or
  change tunnels. Until the hostname is added there, `/api/health` and `POST /api/tensors`
  answer 530 on the site; presets, symbols and tensors are read from R2 and work.
- Step 8, backup: the mirror on `/mnt/d` is populated, but the drive as mounted does not let the
  laptop account set file times, so every backup run exits 2 and a restore dry-run lists every
  file.
- Step 7: evidence that the sender alias accepts mail.

## Step 1. R2 bucket

Done 2026-10-13. The bucket `portfoliosight-data` exists (created 2026-10-13 through the
Cloudflare API). After the owner replaced the two R2 keys:

```
PS_STORE=r2 PS_R2_BUCKET=portfoliosight-data python -m portfoliosight.data.store --verify
```

answered `head_bucket ok`, `put ok`, `get ok`, `delete ok`, `list ok` and exit 0. The bucket held
one object then, `meta/provider_limits.json` (Starter, 45 per hour, 900 per day, 450 symbols per
month, `method: probe`, `measured_on: 2026-10-13`), copied from the laptop's local store. The
probe was not run again.

## Step 2. Seed from the laptop

Done 2026-10-13. The lake was only read.

```
python scripts/seed_r2_from_lake.py --adjusted-through 2026-03-27 --dry-run
python scripts/seed_r2_from_lake.py --adjusted-through 2026-03-27
```

- Dry run: 1,405 symbols checked, 1,400 to seed, 5 not seedable, 0 with `adj_close != close`
  after 2026-03-27; latest adjustment in the lake 2026-03-27. Nothing written.
- Real run: "seeded 1400 symbols (0 already in the store with the same size, 0 left to the
  provider's record)", in 6 min 50 s.
- `meta/manifest.json` then listed 1,400 symbols with `source: seed`, `status: pending`.

## Step 3. Data licensing decision

Owner decision 2026-10-13: Tiingo data under personal use for development and testing; commercial license before public opening (§9.6).

The site stays in private preview (`PS_PRIVATE_PREVIEW="1"`) until the owner buys the
commercial license. The provider tier and limits are still measured and recorded under
"Measured".

## Step 4. KS-001: clone, secrets, deploy, catch-up, first generation

Done 2026-10-13, except the lower tiers of the catch-up, which the nightly is walking.

Host before anything was changed: nine containers of other services, all healthy; 11.2 GB of
memory available; 44 GB of disk free; port 8010 free; no PortfolioSight directory, secrets file,
volume or timer.

Clone and secrets:

```
ssh "$PS_KS001_SSH_HOST" 'git clone -o github <repository> ~/portfoliosight'
scripts/ks001_secrets.sh       # "copied to the host: TIINGO_API_KEY CLOUDFLARE_ACCOUNT_ID
                               #  CLOUDFLARE_R2_ACCESS_KEY_ID CLOUDFLARE_R2_SECRET_ACCESS_KEY PS_GATE_SECRET"
```

The file on the host has those five keys and mode 600. No other file there was touched.

Deploy. The first attempt, `scripts/deploy_ks001.sh 503bf76…`, built the image but the
container restarted in a loop with `PermissionError: /app/portfoliosight/__init__.py`. Cause:
the host account's umask is 007, so the checkout's files are closed to others, `COPY` kept those
modes, and the image's `app` user could not read the code. The container was stopped
(`docker compose -f deploy/docker-compose.yml stop api`); no other service was affected. Fixed
in the image (pull request #84: the Dockerfile sets the modes itself, with a test), then:

```
scripts/deploy_ks001.sh fe38a7a122b3c706f9416ee838e775d964030e75
# portfoliosight fe38a7a… is healthy on <host>
```

Host after the deploy:

- `portfoliosight-api`: image `portfoliosight:fe38a7a…`, healthy, `127.0.0.1:8010->8000`,
  2 CPUs, 1536 MB memory limit, 256 MB reservation, restart `unless-stopped`, user `app`, one
  mount (the volume `portfoliosight_ps-cache` at `/app/cache`, 4 MB in use), 225 to 330 MB of
  memory in use.
- The nine other containers: same names, images and ports as before, all healthy, none restarted.
- 12.5 GB of memory available; 42 GB of disk free. The 2 GB are the image (940 MB), its build
  cache (830 MB) and the checkout (7 MB); the image of the failed attempt was removed. No price
  data is on the host.

Catch-up, tier 1 first. It was run from the laptop with the same env file (spec §5.4 allows
either), because the host had no working image until pull request #84 merged:

```
PS_STORE=r2 python -m portfoliosight.data.download --mode catch-up --tiers 1
PS_STORE=r2 python -m portfoliosight.data.download --mode catch-up --symbols EFA
PS_STORE=r2 python -m portfoliosight.data.download --mode catch-up --tiers 1      # names
PS_STORE=r2 python -m portfoliosight.data.download --mode catch-up --symbols EFA  # its name
```

- 48 Tiingo requests, all inside the ledger (45 in the UTC hour 18:00, then the names pass slept
  to 19:00 and spent 3): 39 for tier 1 (7 seeded tails, 16 full histories with their meta), 1 for
  the EFA tail, 8 names. 24 unique symbols.
- Tier 1 after it: the 16 TSP funds `ok` (through 2026-10-09, the last price tsp.gov had;
  2026-10-12 was a federal holiday), 22 funds `ok` through 2026-10-12, FIENX `stale` with the
  reason "converted to an ETF; no data since 2024-10-30" (by design). No `ok` symbol is named by
  its ticker.
- EFA (tier 2; it replaces FIENX in the default menu on a branch not merged yet): `ok` through
  2026-10-12, named.
- The log output of these four runs was lost: the laptop's disk was full at that moment. The
  results above are read from `meta/manifest.json` and `meta/budget.json`.

First generation. The nightly was started once by hand, through systemd so that only one can
run (the timer of step 8 was installed first):

```
ssh "$PS_KS001_SSH_HOST" 'sudo systemctl start --no-block portfoliosight-nightly.service'
```

- Started about 12:03 PDT; "published generation 2026-10-12-0.1.0" at 19:04:26 UTC.
  `meta/current.json` points at it; `tensors/2026-10-12-0.1.0/` holds 12 objects.
- `GET /api/presets` with the header: 200, `x-ps-source: r2`, `guide2017` (23 funds, FIENX
  excluded in the tensors) and `tsp` (5 funds), six lookbacks each, all `ready`.
- `GET /api/symbols` with the header: 200, 39 symbols, `tiers_served: [1, 2]`.

Where the catch-up stands, and what happens next:

- After publishing, the same run walks tier 2 (`income` first), then the tier 3 slice, at 45
  requests an hour. About 656 requests are left (61 seeded tier 2 tails, 232 tier 2 symbols with
  no record at 2 requests each, 130 tier 3 tails, FIENX): about 14.5 hours, so until about 02:40
  PDT on 2026-10-14. It will have used 447 of the 450 unique symbols of the month.
- `meta/status.json` is written when the run ends; until then `/v1/health` has no nightly
  status. The catalog is rewritten after each group, so `/api/symbols` grows in three steps.
- Do not start a second nightly or downloader while this one runs: each rewrites the whole
  catalog from its own copy. `systemctl is-active portfoliosight-nightly.service` answers
  `activating` while it runs.
- The timer's fire at 02:00 on 2026-10-14 falls inside this run, and systemd does not start a
  unit that is still running: that night's generation (`2026-10-13-0.1.0`) is not built by the
  timer. Start the service once by hand after the run has ended, or the timer builds
  `2026-10-14-0.1.0` at 02:00 on 2026-10-15.
- From then on a nightly run fetches about 447 symbols and takes about ten hours on Starter, so
  `meta/status.json` shows the day's run finished only around noon Pacific.
- Names: the nightly never spends a meta request, so the seeded symbols of tier 2 (61) and of
  the tier 3 slice (130) are listed under their ticker until one more pass is run, by hand, when
  no nightly is running (191 requests, no new unique symbol):
  `docker compose -f deploy/docker-compose.yml run --rm --no-deps nightly python -m portfoliosight.data.download --mode catch-up --tiers 2,3`
  on the host. Check afterwards that no `ok` symbol in `meta/manifest.json` has `name` equal to
  its id.
- Run the nightly right after every deploy that changes the engine version: until a generation
  for the new version is published, custom builds answer `engine_version_mismatch`. A preset
  whose fund list changes is built with the next generation, not into a published one.

## Step 5. Tunnel ingress and DNS

Not done: the hostname cannot be routed with what the run may use. Attempted 2026-10-13.

(a) Baseline, from the laptop. The ingress file on the host named three hostnames of other
services: two answered over HTTPS (200 and 404); the third gives no HTTPS answer at all (TLS
handshake failure at Cloudflare's edge; it answers 301 over plain HTTP), before and after.

(b) The reviewed script, on the host, with `PS_INGRESS_ALLOW_UNREACHABLE=1` for that third name:

```
before: <first> answers 200
before: <second> answers 404
before: <third> gives no HTTP answer; left out of the check
Validating rules from /etc/cloudflared/config.yml.new.<suffix>
OK
after: <first> answers 200
after: <second> answers 404
installed the rule for api.portfoliosight.ai; backup: /etc/cloudflared/config.yml.bak-20261013T184823Z
```

`cloudflared tunnel --config <candidate> ingress validate` is accepted by cloudflared 2026.1.2.
The loop of (a), run again from the laptop, gave the same three results as the baseline.

(c) `scripts/cloudflare_dns.py ensure-cname …` created the proxied record
(`created_this_attempt: true`).

(d) Failed: with the header `https://api.portfoliosight.ai/v1/health` answered 404 with an empty
body, and no request reached the container. Without the header it answered 403 (the edge rule).

Cause: cloudflared's running configuration (its `/config` endpoint on the host) is version 17,
received from Cloudflare, and lists only the three older hostnames. The tunnel is managed
remotely; the ingress list in the file on the host is not used. The Cloudflare API answers
"Not authorized" to this project's token for the tunnel and its configuration.

State left:

- The DNS record was removed again (`cloudflare_dns.py rollback-cname --result …`: "deleted
  record …"). The zone holds the two Worker records only.
- The rule stays in the host's file. It has no effect while the tunnel is managed remotely, and
  taking it out would have meant a second restart of a tunnel that other services use. To take
  it out: `bash scripts/cloudflared_ingress.sh rollback /etc/cloudflared/config.yml.bak-20261013T184823Z`
  in `~/portfoliosight` on the host (it restarts cloudflared).
- cloudflared is active; the other hostnames answer as in the baseline.

The owner's step is under "Remaining".

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
Worker secret again (step 7), copy the secrets to KS-001 again (`scripts/ks001_secrets.sh`) and
recreate the API container so that it reads the new file
(`docker compose -f deploy/docker-compose.yml up -d --force-recreate api` on the host; a plain
restart keeps the old value). Until all four hold the same value the page gets no data.

Not checked yet (they need the API host of step 5): the block on `api.portfoliosight.ai` with a
routed origin behind it, and the application's own limiter seeing the visitor's address.

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

With data (2026-10-13, after step 4): `GET /api/presets` and `GET /api/symbols` with the header
answer 200 with `x-ps-source: r2` and `x-ps-preview: 1`. `GET /api/health` answers 530 (Cloudflare
error 1016) until step 5 is done.

Mail alias: not shown. A `RCPT TO` probe from the laptop (no message sent) was refused by the
domain's mail host for the laptop's own address ("JunkMail rejected") before the recipient was
looked at, so it says nothing about the alias. Owner item: create
`portfoliosight@automateintelligence.ai` as an alias on the mail host, or confirm it exists.

## Step 8. Nightly timer, backup and cron

Timer: done 2026-10-13.

```
scripts/deploy_ks001.sh --install-timer fe38a7a122b3c706f9416ee838e775d964030e75
```

- `portfoliosight-nightly.timer`: `enabled`, `OnCalendar=*-*-* 02:00:00` host time
  (America/Los_Angeles), `Persistent=yes`; next fire 2026-10-14 02:00 PDT.
- `portfoliosight-nightly.service`: `Type=oneshot`, the host account as `User`, working
  directory the checkout, `ExecStart=/usr/bin/docker compose -f deploy/docker-compose.yml run --rm --no-deps nightly`.
  The job's container has the same 2 CPU and 1536 MB limits.
- First run by hand: see step 4. Its log is `docker logs` of the `portfoliosight-nightly-run-…`
  container while it runs (the host account cannot read the system journal).

Laptop backup: installed and run 2026-10-13; it mirrors, but it does not end clean on this drive.

- `aws` on the laptop is AWS CLI 1.44, installed in one pyenv Python version only; the pyenv
  shim on `PATH` could not run it ("pyenv: aws: command not found"), in a shell or under cron.
  One link makes both find it, with no change to the script, which already appends
  `~/.local/bin` to `PATH`: `ln -s ~/.pyenv/versions/3.12.8/bin/aws ~/.local/bin/aws`. To undo,
  remove the link. The spec names AWS CLI v2; v1.44 runs the same `s3 sync` against R2.
- Durable copy and the path the cron line names:

```
install -D -m 755 scripts/r2_backup.sh "$HOME/.local/share/portfoliosight/bin/r2_backup.sh"
mkdir -p "$HOME/programming/portfoliosight/scripts"
ln -s "$HOME/.local/share/portfoliosight/bin/r2_backup.sh" "$HOME/programming/portfoliosight/scripts/r2_backup.sh"
```

  `git status` in the main checkout shows `scripts/` untracked until the run branch is merged
  there; the merge then brings the real file of the same content (remove the link first).
- The exact scheduled command, once, under a minimal environment
  (`env -i HOME=… LOGNAME=… SHELL=/bin/sh PATH=/usr/bin:/bin /bin/sh -c "…r2_backup.sh >> …r2_backup.log 2>&1"`):
  `/mnt/d/portfoliosight-data/` now holds `meta/` and `prices/` (1,432 price files, 1,436 objects,
  150 MB), every one downloaded. Exit status 2, not 0.
- Why 2: `/mnt/d` is mounted so that every file belongs to root, and the laptop account may not
  set a file's time there. `aws s3 sync` downloads each object, cannot set its time, prints
  "unable to update the last modified time" for it and exits 2. Three consequences, all seen:
  the script exits 2 on every run (the status it also uses for "D: not mounted"); because the
  local files look newer than the bucket's, the next run downloads everything again (the second
  run did: 147 MB); and a restore dry-run lists all 1,436 files as uploads, where a faithful
  mirror lists none. The mirror's content is correct; its file times are not.
- Codex was consulted (read-only): no change inside `r2_backup.sh` can fix this within its
  contract (one `aws s3 sync`, its exit status trusted), and the script was left as specified.
  The owner's step is under "Remaining".
- Cron: `scripts/install_backup_cron.sh` added one line and changed no other
  (`crontab -l | grep -c r2_backup.sh` → 1):
  `30 5 * * * $HOME/programming/portfoliosight/scripts/r2_backup.sh >> $HOME/.local/state/portfoliosight/r2_backup.log 2>&1`.
  The crontab as it was before is kept in `~/.local/state/portfoliosight/crontab-before-20261013.txt`.
  Until the drive is fixed the 05:30 run downloads the whole bucket each night (150 MB now,
  about 300 MB when the catch-up is complete) and adds about 1 MB of progress lines to the log.

## Measured

- Provider tier and limits: Tiingo Starter; 45 requests per hour, 900 per day, 450 unique symbols
  per month in force (probe on 2026-10-13: the 51st meta request within two minutes answered 429).
- 23-fund build on KS-001, measured at the origin on 2026-10-13: 7.2 s from POST to the first 200, grid 48 × 32.
  Fresh key by the override `max = 0.24` on the first fund, queue idle, default preset's 23
  funds, lookback `5y`; the tensor holds 22 funds and excludes FIENX, and reports 3.4 for its
  own build time. A second fresh key (`max = 0.2399`) took 6.8 from POST to the first 200.
  "At the origin" means `POST /v1/tensors` and the polling `GET` were sent inside the API
  container to its own port, because the site cannot reach the origin until step 5 is done.
  Measure once more through `https://portfoliosight.ai/api/tensors` after step 5 and add the
  number here.
- Grid in effect: NX = 48, NY = 32. The fallback was not needed and was not applied.
- Six-lookback preset build time (target: three minutes): `guide2017` 15.8 and `tsp` 7.5, in
  seconds, as the sum of the six tensors' own `build_seconds` in generation `2026-10-12-0.1.0`.
  The whole first nightly, refresh included, published 68 seconds after it started.
  `meta/status.json.preset_build_seconds` exists only when that run has ended; compare then.

## Remaining

Owner steps (issue #86). Every block assumes the repository root and
`set -a; . ~/.secrets/portfoliosight.env; set +a`.

### 1. Route `api.portfoliosight.ai` through the tunnel (step 5)

Either of:

- Cloudflare dashboard → Zero Trust → Networks → Tunnels → the tunnel
  `222b8001-009a-47b2-8a31-3ea624ce32ca` → Public Hostname → Add: subdomain `api`, domain
  `portfoliosight.ai`, service `HTTP`, URL `localhost:8010`. The dashboard creates the proxied
  DNS record itself (none exists now, which it requires).
- Or add `Account › Cloudflare Tunnel › Edit` to the project's API token; the run then adds the
  hostname to the tunnel's configuration through the API and creates the record with
  `scripts/cloudflare_dns.py ensure-cname --name api.portfoliosight.ai --target 222b8001-009a-47b2-8a31-3ea624ce32ca.cfargotunnel.com --proxied`.

Nothing has to be restarted on the host. Then check:

```
printf 'x-ps-gate: %s\n' "$PS_GATE_SECRET" | curl -sS -o /dev/null -w '%{http_code}\n' -H @- "$(printf '%s://api.portfoliosight.ai/v1/health' https)"   # 200
curl -sS -o /dev/null -w '%{http_code}\n' "$(printf '%s://api.portfoliosight.ai/v1/health' https)"                                                    # 403, Cloudflare's block page
printf 'x-ps-gate: %s\n' "$PS_GATE_SECRET" | curl -sS -o /dev/null -w '%{http_code}\n' -H @- "$(printf '%s://portfoliosight.ai/api/health' https)"       # 200
```

and, with the origin reachable:

- 25 `POST /api/tensors` in 10 s: at least one 429 without `x-ps-source`; 25 `GET`s: none.
- `CF-Connecting-IP` through the Worker: six `POST /api/tensors` from the laptop within a minute;
  the sixth answers the application's own 429 with `x-ps-source: origin`, and from a second
  network the count starts again. If every visitor shares one address, fix the Worker's
  forwarding before going further.
- The benchmark through the site (see "Measured").
- The gate tests A-PS-55, A-PS-57, A-PS-60, A-PS-67, A-PS-68.

### 2. Let the laptop account set file times on the backup drive (step 8)

Mount `D:` so that its files belong to the laptop account, for example in `/etc/wsl.conf`:

```
[automount]
options = "metadata,uid=<the account's uid>,gid=<its gid>"
```

followed by `wsl --shutdown` from Windows. This changes how every Windows drive is mounted,
other projects' backups included, so it is the owner's decision. Check with
`touch -d 2026-01-01 /mnt/d/portfoliosight-data/meta/manifest.json` (it must succeed). Then
bring the mirror's times in line once and run the backup as scheduled:

```
# with the two R2 keys as AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY, AWS_DEFAULT_REGION=auto
endpoint="$(printf '%s://%s.r2.cloudflarestorage.com' https "$CLOUDFLARE_ACCOUNT_ID")"
aws s3 sync --endpoint-url "$endpoint" s3://portfoliosight-data /mnt/d/portfoliosight-data --delete --exact-timestamps
"$HOME/programming/portfoliosight/scripts/r2_backup.sh"; echo $?                                    # 0
aws s3 sync --endpoint-url "$endpoint" /mnt/d/portfoliosight-data s3://portfoliosight-data --dryrun  # prints no upload
```

The last line is the restore check, a dry run. `r2_backup.sh --restore` itself is only ever run
after the bucket is confirmed lost.

A-PS-58 also counts the crontab lines that name the project and wants exactly one: while the
conductor's own two lines for this repository are in the crontab it reads red for that reason
alone, and turns green when the run has ended and they are gone.

### 3. Mail alias (step 7)

Create `portfoliosight@automateintelligence.ai` as an alias on the mail host, or confirm that
the host accepts mail for it, and note it under step 7.

### 4. After the first nightly has ended

- Read `meta/status.json` (`finished`, `errors`, `refreshed_per_tier`, `preset_build_seconds`)
  and note the result under step 4.
- Start the service once by hand if the 02:00 fire of 2026-10-14 was skipped (step 4).
- Run the names pass for tiers 2 and 3 (step 4).
- A-PS-57 turns green on a day when the generation is the day's, the run has ended without an
  error and `/api/health` answers: on Starter, from about noon Pacific.
