# PortfolioSight tester login: design spec

Date: 2026-11-15. Status: draft for the owner's decisions (section 11). Owner: Jeff Daniels.
Repo: `github:automateintelligence/portfoliosight`.

Source of the request: `ROADMAP.md:49-50` ("Tester access: a SecuritySight-style login
(authorized email domains, one-time code, 30-day session) replaces the private-preview link
when testers are invited"), restating run rule 10 of
`docs/plans/2026-10-13-portfoliosight-demo-plan.md:26` and task 7.5.2 at `:390`.

Plain words for the three names used throughout: **the preview key** is today's `?k=` link and
its 30-day `ps_preview` cookie; **the login** is what this spec adds; **the admin cookie** is
the separate `?admin=` cookie that unlocks the 100-fund menu and the ticker-request list, and
it is not changed by this spec.

Line numbers below are of commit `8e69742` for this repo and of the SecuritySight checkout at
`~/programming/securitysight` as read on 2026-11-15.

## 1. Purpose and scope

Invited testers open `https://portfoliosight.ai`, type their email address, receive a one-time
code, enter it, and use the site for 30 days without logging in again. Anyone else gets no
page and no data, exactly as today. The owner decides who may log in by email domain and by
individual address. The preview key stops being the way in once the owner switches.

Out of scope: accounts, profiles, saved portfolios, passwords, roles beyond the existing admin
cookie, a public sign-up, and any change to the backend on KS-001. The API container never
learns who is logged in (section 4.10).

## 2. What exists today

Read from the code; the plan cites these lines.

- **Preview key** (`web/worker/preview.ts`, spec 9.6 of the demo design). While the Worker var
  `PS_PRIVATE_PREVIEW` is not `"0"`, every page and `/api/*` request must carry one of: the
  `x-ps-gate` header equal to `PS_GATE_SECRET` (smoke tests, `:123`), the `ps_preview` cookie
  holding `hex(HMAC-SHA256(key = secret, message = "ps_preview"))` (`:34-44`, `:125-131`), or
  `?k=<secret>` once, which sets that cookie for 30 days and redirects to the URL without the
  key (`:113-122`). Everything else gets the static "PortfolioSight is in private preview"
  page, HTTP 403 (`:73-102`). Comparisons hash both sides and use `timingSafeEqual` (`:25-32`).
- **Admin cookie** (`web/worker/admin.ts`). `?admin=<PS_ADMIN_SECRET>` sets `ps_admin`
  (HttpOnly, Secure, SameSite=Strict, 180 days, `:165-168`, `:210-222`); `?admin=off` clears
  it; a wrong value gets the same redirect and no hint. The Worker forwards `x-ps-tier: admin`
  to the API only for a verified cookie (`web/worker/index.ts:370-371`).
- **Order of checks** (`web/worker/index.ts:474-500`): host check (www → 301, foreign host →
  404), then the preview gate, then `/api/*` or the admin link, then static assets. The preview
  gate runs before the admin link, so the admin cookie cannot be set without the preview key.
- **Edge rules before the Worker** (`scripts/cloudflare_rules.py:46-63`, demo spec 9.4): the
  WAF rule `ps-challenge-site` gives every request to the apex or www a Managed Challenge
  unless it carries the `x-ps-gate` header; `ps-block-api-direct` blocks direct calls to
  `api.portfoliosight.ai` without it. A browser passes the challenge once and then carries
  `cf_clearance`.
- **Forwarding to KS-001** (`web/worker/index.ts:362-390`): the upstream request is built from
  nothing; no visitor cookie or header goes up except `CF-Connecting-IP` and `content-type`.
- **Outbound mail** (`web/worker/share.ts:296-330`): MailChannels,
  `POST https://api.mailchannels.net/tx/v1/send`, `X-API-Key: MAILCHANNELS_API_KEY`, BYO DKIM
  for `automateintelligence.ai`, sender `SHARE_FROM` = `portfoliosight@automateintelligence.ai`,
  caps in the `ShareLimiter` Durable Object (`:239-289`).
- **Secrets**: Worker secrets `PS_GATE_SECRET`, `PS_ADMIN_SECRET`, `MAILCHANNELS_API_KEY`,
  `MAILCHANNELS_DKIM_PRIVATE_KEY` (`docs/plans/2026-10-13-ks001-cloudflare-runbook.md:297-299`,
  `:513`); the laptop file `~/.secrets/portfoliosight.env` holds them and the smoke settings
  (`scripts/smoke.sh:8-11`); `scripts/ks001_secrets.sh:20-22` names which go to KS-001 and
  which stay on the laptop. The redacting reporter knows the names in
  `web/e2e/smoke-lib.ts:9-17`. The repo is public: no secret, tester name or address may be
  committed (demo plan run rule 4).
- **The page's view of the gate**: every `/api/*` answer carries `x-ps-preview: 1|0`
  (`web/worker/index.ts:497-498`); the page reads it (`web/src/api/http.ts:83-91`) and the
  share dialog shows "the link opens for invited testers only" while it is 1
  (`web/src/copy.ts:70`, `web/src/controls/ShareDialog.tsx:113`). A response with
  `cf-mitigated: challenge` throws `ChallengeError` and the page reloads
  (`web/src/api/http.ts:7-13`, `:69`).

## 3. What SecuritySight does (the reference)

SecuritySight does not implement a one-time code itself. Its login is **Cloudflare Access
with the One-time PIN identity provider**; Cloudflare generates, mails, stores, expires and
rate-limits the code, sets the session cookie and serves the login page. The application only
verifies Cloudflare's signed assertion. Specifically:

- The Access application is created per facility hostname by `deploy/onboard.sh:325-342`:
  `type: self_hosted`, `session_duration: "24h"`, one Allow policy whose include rules are
  individual addresses `{"email": {"email": "<address>"}}` (`:349-358`). An earlier version
  used a domain rule, `email_domain: automateintelligence.ai`
  (`deploy/tests/test_onboard_access_policy.py:48-53`). The app's audience tag and the team's
  issuer are read from the Access API (`:78-104`) and stored as Pages secrets `CF_ACCESS_AUD`
  and `CF_ACCESS_TEAM_DOMAIN` (`:398-399`).
- The Pages Function in front of the API verifies the assertion on every request
  (`frontend/functions/api/[[path]].js:1-74`, `:82-104`): header `Cf-Access-Jwt-Assertion`,
  RS256 only, `kid` looked up in `<issuer>/cdn-cgi/access/certs` (cached 5 minutes), `iss`
  equal to the team domain, `aud` containing the app's tag, `exp` in the future, `nbf` not in
  the future; anything else is 401 and nothing is forwarded. It strips every credential header
  before forwarding (`:92`).
- The backend verifies the same assertion again with PyJWT (`backend/app/auth.py:113-159`)
  and exchanges it for its own 15-minute in-memory API session
  (`backend/app/auth.py:162-166`, `backend/app/config.py:130-132`,
  `backend/tests/test_auth_sessions.py:23-41`). That second layer exists because the
  SecuritySight API is a separate origin; PortfolioSight's page and API share one Worker, so
  it is not needed here.
- Known failure, recorded at `deploy/onboard.sh:370-376`: Access sends no PIN to an address
  the policy does not permit, and the login page still says a code was emailed. An app created
  on the wrong hostname took over a facility's domain on 2026-08-05 and locked everyone out
  for 33 hours. This spec creates the app on exactly one hostname and makes the Worker refuse
  rather than serve when the assertion is missing (section 4.5).
- Mail: the OTP mail is Cloudflare's (`noreply@notify.cloudflare.com`), not MailChannels.
  SecuritySight's own MailChannels sending (`landing/functions/api/contact.ts:406`) is the
  landing-page contact form only.

What differs here: PortfolioSight has one Worker on the apex (no Pages, no separate API
origin for the browser), a WAF challenge in front, a preview key to retire, a public repo, and
a MailChannels sender already configured. Those differences shape sections 4 and 5.

## 4. The design: Cloudflare Access with a one-time code (recommended, question 1a)

### 4.1 Who may log in

One Access application on the hostname `portfoliosight.ai` only (never `www`, never a
wildcard, never a `workers.dev` host; `www` is a Worker 301 to the apex and carries no
content). Its policies, in evaluation order:

1. `Smoke tests`, action **Service Auth**, include rule **Service Token** = the token of 4.7.
2. `Testers`, action **Allow**, include rules **Emails ending in** `@<domain>` for each
   allowed domain and **Emails** `<address>` for each individually invited address
   (question 2). No other rule.

Nothing else is allowed: Access denies by default. The identity provider is One-time PIN
only; no Google, GitHub or other provider is attached to the app. The list of domains and
addresses lives in the Access policy and in the owner's private notes, never in this repo.

Expected scale: a few dozen testers. Cloudflare's free Zero Trust plan has a seat limit the
owner confirms in the dashboard before inviting (section 7, step 1); the same team already
serves SecuritySight's facilities, which use seats too.

### 4.2 The code

Cloudflare's, as documented on 2026-11-15: a PIN mailed from `noreply@notify.cloudflare.com`,
valid for 10 minutes from the request, single use; requesting a new one voids the previous;
a wrong PIN is refused on Cloudflare's page; a PIN that a mail scanner "opened" shows as
already used and the tester requests a new one. Cloudflare does not publish its attempt and
rate limits for the PIN; they are not ours to set, and the WAF challenge in front of the
hostname already limits automation. The invite email the owner sends testers names the
sender address so it can be allow-listed (section 7).

### 4.3 Session

Access **Session Duration** for the app: one month (`720h`), the maximum Cloudflare offers,
which is the owner's 30 days. The session is the `CF_Authorization` cookie that Cloudflare
sets for the hostname; the Worker never sets, reads or renews it. The team's **global
session** is left as it is; the rollout step 7 checks that a tester is not asked to log in
again before 30 days, and raises the global session to one month if so (builder's call,
recorded in the runbook).

### 4.4 Logout

A "Sign out" link in the page's Settings section (`web/src/sections/Settings.tsx`) pointing
at `/cdn-cgi/access/logout`, which Cloudflare serves at the edge; it ends the session on this
hostname and sends the browser back to the login page. The Worker never sees that path. The
link is shown only when the page knows the login is on (4.8).

### 4.5 The Worker verifies every request (fail closed)

New module `web/worker/access.ts`, modelled on
`~/programming/securitysight/frontend/functions/api/[[path]].js:1-74` and written in the
style of `preview.ts` (plain Node loadable, nothing from `cloudflare:*`):

- Settings: Worker var `PS_LOGIN` = `"off"` (default, and the value in `wrangler.jsonc` until
  the switch) or `"access"`; Worker secrets `PS_ACCESS_TEAM_DOMAIN`
  (`https://<team>.cloudflareaccess.com`, the issuer) and `PS_ACCESS_AUD` (the app's audience
  tag). Both are kept out of the public repo as secrets, as SecuritySight does, though neither
  unlocks anything by itself.
- `verifyAccess(request, env, fetchCerts, nowMs)` reads `Cf-Access-Jwt-Assertion`; refuses
  (returns a reason, never throws to the caller) when the header is absent, the token is not
  three base64url parts, `alg` is not `RS256`, `kid` is missing or unknown, `iss` is not the
  team domain, `aud` (string or list) does not contain `PS_ACCESS_AUD`, `exp` is missing or
  not after now, `nbf` is present and after now, or the signature does not verify with
  `crypto.subtle` (`RSASSA-PKCS1-v1_5`, SHA-256) under the key whose `kid` matches in
  `<issuer>/cdn-cgi/access/certs` (`public_certs`, never the single `public_cert`). Keys are
  cached per isolate for 5 minutes; an unknown `kid` refetches once, then refuses. A certs
  fetch that fails or is not JSON refuses the request (503 `login_unavailable`), never passes.
- Who passed: the claim `email` (a person) or `common_name` (the service token of 4.7). The
  Worker uses neither for anything but the pass decision (4.10).
- Placement in `web/worker/index.ts:474-500`: after the host check and before everything
  else. When `PS_LOGIN` is `"access"`, `verifyAccess` replaces the preview gate: a refusal
  answers pages with a 401 HTML page in the style of the preview page ("Sign in to
  PortfolioSight", one link to `/`, which Cloudflare turns into its login page, `no-store`,
  `noindex`) and `/api/*` with 401 `{"error": {"code": "login_required", ...}}`; `?k=`,
  `ps_preview` and the `x-ps-gate` header are not credentials any more on the apex. When
  `PS_LOGIN` is `"off"` (or unset or any other value), nothing changes: the preview gate of
  today runs and `access.ts` is not consulted. There is no third mode.
- Why verify at all when Access already enforces at the edge: so that the hostname is not
  served if the app is deleted, moved, overridden by another app (the 2026-08-05 pattern) or
  its policy loosened by mistake, and so that a request that somehow reaches the Worker
  without Cloudflare's decision gets nothing. The check costs one cached key lookup per
  request.

### 4.6 How the login, the preview key, the admin cookie and the edge rules coexist

- **Edge order.** For a browser: WAF Managed Challenge (unchanged), then Cloudflare's login
  page, then the Worker. The `x-ps-gate` header still exempts automation from the challenge;
  it no longer opens the Worker while the login is on.
- **Preview key.** Retired by the switch (`PS_LOGIN=access`): no `?k=` link opens the site,
  existing `ps_preview` cookies are ignored, and the `preview.ts` code stays for rollback. Once
  the owner declares the rollout done, the plan removes the `?k=` path and the cookie
  (section 7, step 9). `PS_PRIVATE_PREVIEW` keeps its meaning (the site is not public) and
  stays `"1"`; `x-ps-preview` keeps telling the page so.
- **Admin cookie.** Unchanged: `?admin=` works for a logged-in browser exactly as it does for a
  keyed one today, and admin is still a secret, not an email (question 5).
- **Share by email.** A recipient who is not a tester reaches Cloudflare's login page and
  gets no code (section 3). The dialog's existing "invited testers only" line already says
  this; its wording is updated to say "sign in" (section 8).
- **Public opening later.** `PS_LOGIN=off` plus `PS_PRIVATE_PREVIEW=0` and the deletion of
  the Access app; the login code stays in the Worker for the next private phase.

### 4.7 Smoke tests, e2e and the service token

Automation cannot receive a mailed code. The owner creates one Access **service token** named
`portfoliosight-smoke` (one year), and the `Smoke tests` policy of 4.1 admits it. Its two
values go into `~/.secrets/portfoliosight.env` as `PS_ACCESS_CLIENT_ID` and
`PS_ACCESS_CLIENT_SECRET`; they are sent as the headers `CF-Access-Client-Id` and
`CF-Access-Client-Secret` beside `x-ps-gate`, route-scoped to the site's own hosts exactly as
`web/e2e/helpers.ts:26` scopes the gate header, never context-wide. Cloudflare answers such a
request with an assertion whose subject is the token's `common_name`, so the Worker's check of
4.5 passes it too. Both names join `web/e2e/smoke-lib.ts:9-17` so the reporter redacts them,
and `scripts/smoke.sh:26` requires them when `PS_LOGIN` is on. The token is not needed by
KS-001 and never goes there (`scripts/ks001_secrets.sh` unchanged). Rotation: a new token in
the dashboard, the two values replaced in the env file, the old token revoked.

### 4.8 The page

- `GET /api/tier` (`web/worker/admin.ts:224-231`) gains one field, `login: "off" | "access"`,
  so the page knows whether to show "Sign out". No email is returned.
- Session end mid-use: when the `CF_Authorization` cookie expires, a same-origin fetch gets
  Cloudflare's 302 to the login page; `fetch` follows it to another origin and fails. In
  `web/src/api/http.ts`, a response whose `redirected` is true, whose `url` is not
  same-origin, or whose status is 401 with `login_required` is treated like a challenge:
  `ChallengeError`, and the page reloads at the top level so Cloudflare can show its login.
- Copy: "Sign out" and the share hint of section 8. The login page itself is Cloudflare's;
  the owner can set the app's display name "PortfolioSight" and a logo in the app's settings
  (builder's call: name yes, logo if the owner provides one).

### 4.9 Failure modes

| What happens | What the tester sees | What we do |
|---|---|---|
| Address not on the list | Cloudflare's "a code has been emailed", no mail | Nothing; the invite email tells testers to reply to the owner if no code arrives in two minutes |
| Cloudflare's mail delayed or filtered | No code | The invite names `noreply@notify.cloudflare.com` to allow-list; "Request new code" on the page |
| Wrong code | Cloudflare's error, retry | Nothing |
| Expired code (10 minutes) | Cloudflare's error, request a new one | Nothing |
| Code consumed by a mail scanner | "already used" | Request a new code (Cloudflare's own advice) |
| Session expired while the page is open | A reload, then the login page | 4.8 |
| Access app deleted, moved or policy broken | Nothing served: 401 page | 4.5; the runbook's rollback restores the app |
| Access certs endpoint unreachable | 503 `login_unavailable` for the minutes it lasts | Fail closed; nothing cached longer than 5 minutes |
| `PS_LOGIN=access` deployed before the app exists | Nobody gets in (no assertion) | Rollout order of section 7 forbids it; the smoke test of 6.3 catches it |
| Service token expired | Smoke tests fail with 302/401 | Rotate per 4.7; the token's expiry date is in the runbook |

### 4.10 Privacy and logging

- Cloudflare keeps the Access audit log (address, IP, time, decision) in the Zero Trust
  dashboard under Cloudflare's retention; that is the only record of who logged in. The
  owner can read it there.
- The Worker never logs, stores or forwards the `email` or `common_name` claim, the
  assertion or the cookie. `forward()` keeps building upstream headers from nothing
  (`web/worker/index.ts:367-375`), so KS-001 never learns a tester's address. Refusal logs
  say only the reason class ("access: missing", "access: invalid", "access: certs"), as
  `share.ts` logs only "mail service unreachable".
- The tester list is in the Access policy, not in git, the bundle, the Worker config or the
  runbook (the runbook records the domain rule by name only if the owner agrees; addresses
  never).
- The bundle hygiene test (`web/tests/bundle-hygiene.test.ts:9`) adds `PS_ACCESS`,
  `CF-Access-Client` and `cloudflareaccess.com` to the forbidden strings: the page bundle
  carries no login configuration.

### 4.11 Configuration and secrets (names only)

| Where | Name | Kind | Value |
|---|---|---|---|
| `web/wrangler.jsonc` vars | `PS_LOGIN` | var | `"off"` until the switch; `"access"` after |
| Worker secret | `PS_ACCESS_TEAM_DOMAIN` | secret | the team's `https://<team>.cloudflareaccess.com` |
| Worker secret | `PS_ACCESS_AUD` | secret | the app's audience tag |
| `~/.secrets/portfoliosight.env` | `PS_ACCESS_CLIENT_ID`, `PS_ACCESS_CLIENT_SECRET` | laptop only | the smoke service token |
| `~/.secrets/portfoliosight.env` | `PS_ACCESS_TEAM_DOMAIN`, `PS_ACCESS_AUD` | laptop only | the same two values, for `wrangler secret put` and the production test |
| Cloudflare dashboard | the Access app, its two policies, the OTP provider, the service token | owner's hands | section 7 |

No new secret goes to KS-001. The Cloudflare API token needs no new permission under
question 6a.

## 5. The alternative: a one-time code built into the Worker (question 1b)

Written so the plan can build it if the owner prefers a site-styled login with no Cloudflare
login page. Everything in section 4 that is about the Worker's order of checks, the page, the
admin cookie, smoke tests and privacy holds, with these replacements.

- **Allow list.** Worker secrets `PS_LOGIN_DOMAINS` and `PS_LOGIN_EMAILS`, comma-separated,
  compared case-insensitively against the typed address after it passes `isBareAddress`
  (`web/worker/share.ts:93-99`). An address that is not allowed gets the same 202 as one that
  is, and no mail (no oracle about the list).
- **Endpoints** (`web/worker/login.ts`; same-origin `Origin` check, JSON only, 2 KB limit,
  as `handleShare`): `POST /api/login/code {"email"}` → 202 always, or 429 `rate_limited`;
  `POST /api/login/verify {"email", "code"}` → 204 with the session cookie, 401 `bad_code`
  (wrong, expired, used up, or never issued: one answer), 429; `POST /api/logout` → 204 and
  the cookie cleared.
- **Code.** Six decimal digits from `crypto.getRandomValues` with rejection sampling (no
  modulo bias); valid 10 minutes; single use; at most 5 wrong attempts, after which the code is
  void; a new request voids the previous code.
- **Rate limits.** Per address 3 codes per hour; per `CF-Connecting-IP` 10 codes and 30
  verify attempts per hour; everyone together 100 codes per UTC day (the MailChannels budget
  of the share feature is 50 a day; the login gets its own counter). Over a limit: 429, nothing
  sent, nothing counted.
- **Storage.** A SQLite-backed Durable Object `LoginCodes` (one instance, name "global",
  binding `LOGIN_CODES`, migration `v3`), after `ShareLimiter` (`web/worker/share.ts:239-289`):
  table `codes(address_mac PRIMARY KEY, code_mac, expires_ms, attempts)` and tables of hourly
  and daily counters. The address is stored only as `HMAC-SHA256(key = PS_SESSION_SECRET,
  message = "login:" + address)` and the code only as `HMAC-SHA256(key, address + ":" + code)`;
  rows older than their window are deleted on every call; the check-and-write runs without an
  `await`.
- **Session cookie.** `ps_session` = `v1.<base64url(payload)>.<base64url(HMAC-SHA256(key =
  PS_SESSION_SECRET, message = "v1." + payload))>` with payload `{"sub": address, "iat",
  "exp": iat + 30 days, "jti": 18 random bytes}`; HttpOnly, Secure, SameSite=Lax, Path=/,
  Max-Age 30 days; verified with `timingSafeEqual` on the two digests; the Worker keeps no
  session table, so rotating `PS_SESSION_SECRET` (32 bytes, `openssl rand -hex 32`) logs
  everyone out and logout only clears the browser's cookie (a copied cookie lives until `exp`;
  acceptable for testers, stated here).
- **Mail.** MailChannels through the same code path as `sendShareMail`
  (`web/worker/share.ts:296-330`), refactored into one `sendMail(env, to, subject, text,
  html)`; sender `SHARE_FROM`; subject "Your PortfolioSight sign-in code"; body: the code, "It
  expires in 10 minutes.", "If you did not ask for it, ignore this message."; fixed template,
  nothing visitor-supplied but the code's destination.
- **Login page.** Served by the Worker like the preview page (`web/worker/loginPage.ts`,
  static HTML and a few lines of inline script, no bundle dependency): an address field, then
  a code field, then a reload of the page the tester asked for. The WAF challenge still runs
  before it.
- **Gate.** `PS_LOGIN="worker"`: the `ps_session` cookie or the `x-ps-gate` header passes; a
  transition value `PS_LOGIN="both"` additionally keeps `?k=` and `ps_preview` valid, which
  this design can offer and section 4 cannot (the edge decides there).
- **Tests.** The unit tests of 6.1 plus: uniform six-digit codes; a wrong, expired, reused,
  over-attempted or never-issued code all answer 401 in the same way; limits per address, per
  IP and global; a disallowed address gets 202 and no mail; the DO stores no address and no
  code in clear (read the table); cookie tampering (payload, signature, expired, wrong secret
  version) fails; logout clears; nothing is logged but counts.

Cost of 1b against 1a: about 600 to 900 lines of security-sensitive code and tests to own,
MailChannels deliverability for codes (a code that lands in spam is a locked-out tester),
and our own rate limiting. Gain: a login page in the site's own look and no Cloudflare login
page, no seat limit, and the transition mode.

## 6. Security tests

### 6.1 Unit (`web/tests/worker-access.test.ts`, vitest, plain Node, no network)

A test key pair is generated with `node:crypto` (`generateKeyPairSync("rsa", 2048)`); `fetch`
is stubbed to serve a `public_certs` list from it; tokens are signed in the test. Each case
asserts on the response status and body and on what the Worker did not do (no `ASSETS`
fetch, no `DATA` read, no origin `fetch`, no log line containing the address):

1. A valid token (`RS256`, known `kid`, right `iss` and `aud`, `exp` ahead) passes a page and
   an `/api/presets` request; the `email` claim appears in no log and in no upstream header.
2. A token with `common_name` and no `email` passes (service token).
3. Each of these is refused with 401 and nothing served: missing header; two or four parts;
   `alg` `none`, `HS256`, `RS512`; unknown `kid` after one refetch; `iss` with a trailing
   slash difference or another team; `aud` another tag, or a list without ours; `exp` missing,
   a string, or in the past; `nbf` ahead; a signature from another key; a tampered payload with
   the original signature.
4. Certs endpoint 500, non-JSON, or `keys` not a list → 503 `login_unavailable`.
5. The certs cache: two requests make one certs fetch; after 5 minutes a second; an unknown
   `kid` makes one refetch and then refuses.
6. With `PS_LOGIN=access`: `?k=<secret>` sets no cookie and gets 401; a valid `ps_preview`
   cookie gets 401; the `x-ps-gate` header alone gets 401.
7. With `PS_LOGIN=off`, unset, or `"1"`: `access.ts` is never consulted (the certs stub sees no
   call) and every existing `worker-preview.test.ts`, `worker-admin.test.ts` and
   `worker-routing.test.ts` case passes unchanged.
8. `www` → 301 before any check; a foreign host → 404 before any check (no certs fetch).
9. `GET /api/tier` reports `login` and never an address.
10. The 401 page carries `cache-control: no-store`, `x-robots-tag: noindex`, no script, and
    no address.

### 6.2 Page (`web/tests/http-login.test.ts`)

A redirected response, a cross-origin `url`, and a 401 `login_required` each throw
`ChallengeError`; a 401 of another code does not. "Sign out" renders only when `login` is
`access`.

### 6.3 Production (`web/e2e/preview.spec.ts`, extended; `scripts/smoke_preview.sh`)

With the login on: a keyless, cookieless request still gets the challenge (unchanged); a
request with `x-ps-gate` and no service token gets Cloudflare's 302 to the login page and no
`x-ps-source`, no JSON, no `chart-canvas`; a request with the header and the token gets 200
and `x-ps-source`. The deployed Worker's active version has `PS_LOGIN` equal to the committed
value (the existing version-view pattern at `preview.spec.ts:44-68`). The Access app for the
hostname is listed once by the API with the policy names of 4.1 and `session_duration`
`720h`, read with the account token (read-only `Access: Apps and Policies: Read`, question
6). No test enters a code or opens a keyed link.

### 6.4 Static

`web/tests/bundle-hygiene.test.ts` forbids `PS_ACCESS`, `CF-Access-Client`,
`cloudflareaccess.com`. The existing public-repo grep of the demo plan (task 7.5.3) is re-run
over the new files.

## 7. Rollout, in order, with rollback at every step

The current preview key keeps working until step 6. Each step is recorded in
`docs/plans/2026-10-13-ks001-cloudflare-runbook.md` under a new heading "Tester login".

1. **Readiness (owner, dashboard, no change to the site).** Confirm the Zero Trust team's
   plan and seat count cover the testers; confirm One-time PIN is an enabled identity
   provider on the team (it is, for SecuritySight); note the team domain.
2. **Code (PR, merged, deployed with `PS_LOGIN=off`).** `access.ts`, the index wiring, the
   page changes, the tests. Deploying changes nothing for visitors: the 6.1 case 7 tests prove
   it, and the deployed smoke tests of today pass.
3. **Service token (owner, dashboard).** Create `portfoliosight-smoke`; put its two values
   in the env file. Nothing changes on the site.
4. **Access app (owner, dashboard, question 6).** Create the self-hosted app on
   `portfoliosight.ai` with the two policies of 4.1, One-time PIN as the only provider,
   session `720h`, name "PortfolioSight". **From this moment Cloudflare's login page is in
   front of the site** and the `?k=` link no longer reaches the Worker without a login; the
   owner does this step when the first tester is ready. Rollback: delete the app; the site is
   back on the preview key within a minute.
5. **Secrets (laptop).** `PS_ACCESS_TEAM_DOMAIN` and `PS_ACCESS_AUD` into the env file and
   `wrangler secret put` for both (values on stdin only, as `runbook:297-299`).
6. **The switch (laptop).** `PS_LOGIN: "access"` in `wrangler.jsonc`, commit on a branch,
   `make deploy-frontend`. Rollback: `npx wrangler rollback` from `web/`, or `PS_LOGIN: "off"`
   and deploy; both leave the Access app in place (delete it too to restore the key fully).
7. **Verify (laptop and owner).** `scripts/smoke_preview.sh` (6.3) and `scripts/smoke.sh`
   green with the token; the owner logs in from a fresh browser with a tester address, sees
   the chart, reopens the next day without logging in, signs out and sees the login page
   again; a non-listed address receives no code. Session check of 4.3.
8. **Invite.** The owner mails testers the link and the sender address to allow-list.
9. **Cleanup (PR, after the owner says the rollout is done).** Remove the `?k=` path and the
   `ps_preview` cookie from `preview.ts` and its tests; `x-ps-gate` stays for the API origin
   and the WAF exemption. Update the demo spec's section 9.6 and Expectations S19 and M4 with
   a dated note (question 7).

## 8. Copy

| Key (`web/src/copy.ts`) | Text |
|---|---|
| `signOut` | Sign out |
| `sharePreview` (changed) | PortfolioSight is in private testing: the link opens for invited testers after they sign in. |
| Worker 401 page title | Sign in to PortfolioSight |
| Worker 401 page line | This site is open to invited testers. Open the home page to sign in with your email address. |

## 9. Files

| File | Change |
|---|---|
| `web/worker/access.ts` | new: `verifyAccess`, certs cache, the 401 page, the JSON refusal |
| `web/worker/index.ts` | the `PS_LOGIN` branch at the gate step; `Env` gains the three names |
| `web/worker/admin.ts` | `serveTier` adds `login` |
| `web/wrangler.jsonc` | `PS_LOGIN: "off"` |
| `web/src/api/http.ts` | redirect and 401 `login_required` → `ChallengeError`; `Tier` gains `login` |
| `web/src/sections/Settings.tsx`, `web/src/copy.ts` | "Sign out" link; share hint |
| `web/src/controls/ShareDialog.tsx` | the new hint text (same prop) |
| `web/tests/worker-access.test.ts`, `web/tests/http-login.test.ts` | new |
| `web/tests/bundle-hygiene.test.ts` | three forbidden strings |
| `web/e2e/helpers.ts`, `web/e2e/smoke-lib.ts`, `web/e2e/preview.spec.ts` | service-token headers, redaction names, the three production cases |
| `scripts/smoke.sh`, `scripts/smoke_preview.sh` | require the token names when `PS_LOGIN` is on |
| `docs/plans/2026-10-13-ks001-cloudflare-runbook.md` | "Tester login" heading, steps 1 to 9 |
| `ROADMAP.md` | the item moves to "Shipped" at step 9 |
| `docs/specs/2026-10-13-portfoliosight-demo-design.md` | dated notes at 9.6, S19, M4 (question 7) |

Under 1b, add `web/worker/login.ts`, `web/worker/loginPage.ts`, `web/tests/worker-login.test.ts`,
the `LOGIN_CODES` binding and migration `v3` in `wrangler.jsonc`, and the `sendMail` refactor
of `share.ts`.

## 10. Expectations

Written in the owner's voice. **[J]** is taken from what the owner wrote; **[+]** is added for
build quality. These define done; the sections above say how.

### Success scenarios

- **S1 [J]** A tester opens portfoliosight.ai, types their email, gets a code, types it, and
  is in. The next day, and for a month, they are in without doing it again.
- **S2 [J]** I decide who can log in by email domain, and I can add a single address that is
  not on one of those domains.
- **S3 [J]** It works like the SecuritySight login I already use.
- **S4 [J]** Until I say switch, the `?k=` link keeps working and nothing changes for anyone.
- **S5 [+]** The switch is one step I can undo in a minute.
- **S6 [+]** My admin link still works after I log in, and nobody else's login makes them
  admin.
- **S7 [+]** The smoke tests still run from my laptop without a mailbox.
- **S8 [+]** A tester can sign out, and a tester whose session has run out is sent to log in
  again, not left staring at a broken page.

### Failure scenarios (looks right, is wrong)

- **F1 [+]** Someone who is not on the list gets a page or any data, with or without a key.
- **F2 [+]** The login is on but a `?k=` link, an old preview cookie or the smoke header still
  opens the site.
- **F3 [+]** The Access app is deleted or moved and the site opens to everyone.
- **F4 [+]** A tester's address shows up in a Worker log, a KS-001 log, the bundle, the repo
  or a PR.
- **F5 [+]** The site is switched before the app exists, and nobody can get in.
- **F6 [+]** A tester is asked to log in again every day because of a session setting I did
  not know about.

### Must-nots

- **M1 [J]** Never put a tester's name or address in the repo.
- **M2 [J]** Never put secrets in the repo, the image or the bundle.
- **M3 [+]** Never touch the live login (the preview key) until the owner's switch.
- **M4 [+]** Never let the login decide admin.
- **M5 [+]** Never build accounts, profiles or saved state behind the login.

## 11. Open questions for the owner

1. **Which login?** a (recommended): Cloudflare Access with One-time PIN, as SecuritySight
   runs it, because Cloudflare owns the code, the mail, the limits and the login page, and
   the Worker only verifies a signature; cost: Cloudflare's login page with the team name,
   the team's seat limit, and a service token for the smoke tests. b: a code built into the
   Worker (section 5), mailed by MailChannels, with a login page in the site's own look and a
   transition mode where `?k=` and the login both work; cost: 600 to 900 lines of security
   code to own, our own rate limiting, and codes that may land in spam.
2. **Individual addresses beside the domains?** y (recommended): the policy lists domains and
   also named addresses, so a friend on gmail can be invited; cost: one more rule to keep up.
   n: domains only.
3. **Session length?** a (recommended): one month, Cloudflare's maximum, which is your "30
   days". b: shorter (say a week) if you want testers to see the login more often; cost: more
   codes mailed.
4. **Service token for the smoke tests?** y (recommended): one Access service token admitted
   by its own policy; the smoke and preview tests keep running from the laptop; cost: two
   more values in the env file and a yearly rotation. n: the smoke tests stop running while
   the login is on, and the production checks are the owner's browser only.
5. **Admin stays a secret link?** a (recommended): `?admin=` unchanged; cost: none. b: admin
   decided by a list of admin addresses in the login; cost: a new var, a page that knows the
   address, and a bigger change than the roadmap item asks for.
6. **Who creates the Access app?** a (recommended): you, in the Zero Trust dashboard,
   following the runbook's steps; the production test only reads it back, which needs
   `Access: Apps and Policies: Read` on the API token; cost: ten minutes of clicking and the
   same again to rebuild it after a rollback. b: a script like `scripts/cloudflare_rules.py`
   creates and updates it; cost: the token gets `Access: Apps and Policies: Edit` and the
   tester list has to be fed to the script from the env file.
7. **The demo spec says no login.** Its Expectations S19 ("No login", line 650) and M4
   ("never add a login", line 681) and section 9.6 contradict the roadmap item. a
   (recommended): the cleanup PR adds a dated note at each of the three places saying the
   owner replaced the preview key with the tester login on the date of the switch; cost:
   none. b: leave the demo spec as it is and let this spec supersede it; cost: the next reader
   of the demo spec is misled.

Settled as builder's call: the 401 page's look (the preview page's style), the app display
name "PortfolioSight", the 5-minute certs cache, the `login` field on `/api/tier`, the sign-out
link's place (Settings), the global session check in step 7, and which runbook heading records
the steps.
