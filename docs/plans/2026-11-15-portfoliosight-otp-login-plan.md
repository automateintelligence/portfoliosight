# PortfolioSight tester login: implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Put the tester login of
`docs/specs/2026-11-15-portfoliosight-otp-login-design.md` ("the spec") in front of
`https://portfoliosight.ai` without touching the live preview key until the owner's switch.

**Architecture:** One new Worker module verifies Cloudflare Access assertions and replaces
the preview gate only when the var `PS_LOGIN` is `"access"`. Cloudflare's One-time PIN does
the code, the mail and the session. The page learns the login state from `/api/tier` and gets
a sign-out link. The smoke tests authenticate with an Access service token. Four small PRs,
then the owner's own steps in the Cloudflare dashboard, then a cleanup PR.

**Tech stack:** TypeScript on Cloudflare Workers (`web/worker`), React/Vite (`web/src`),
vitest, Playwright, bash. No new dependency: the JWT check uses `crypto.subtle`, as
SecuritySight's Pages Function does.

**Spec:** sections are cited as "spec 4.5". The spec is a draft until the owner answers its
section 11; this plan is written for the recommended answers (1a, 2y, 3a, 4y, 5a, 6a, 7a).
Section "If the owner picks 1b" at the end says what changes.

Written 2026-11-15. No code, run or commit was made while writing it.

## Global constraints

- Nothing in PR 1 to PR 3 changes what a visitor sees: `PS_LOGIN` stays `"off"` in
  `web/wrangler.jsonc` until PR 4, and the unit tests of task 1.4 prove the off path is
  byte-identical to today (spec 4.5, 7).
- Never read `~/.secrets/*`. Secret names may be grepped; values never printed, logged,
  committed or quoted in a PR (spec 4.11, demo plan run rule 4).
- No tester address, domain list or Cloudflare team name in any committed file (spec 4.10).
  Tests use made-up values (`https://unit.cloudflareaccess.com`, `aud-unit-0001`,
  `tester@example.org`).
- Code in `web/worker/` must load in plain Node: no import from `cloudflare:*`
  (`web/worker/index.ts:248-249`).
- Tests assert on responses, side effects (what `ASSETS`, `DATA`, `fetch` were asked) and
  logs, never on source text. Deterministic: tokens are signed in the test with a key pair
  made in `beforeAll`; time comes from an injected `nowMs`.
- Checks before any PR is called ready, from `web/`: `npm run lint && npm run typecheck &&
  npm test` (README.md:31). PR 2 also touches `tests/test_smoke_scripts.py`, so it runs
  `ruff check . && ruff format --check . && pyright . && pytest tests/test_smoke_scripts.py -q`
  from the root; the other PRs leave Python alone.
- Every task: write the listed tests, run them and see them fail, implement, run them and see
  them pass, run the checks, commit. Commit message: files with line numbers, then one or two
  bullets.
- Every PR: branch and worktree off `main` (remote `github`); review loop (Codex, up to three
  rounds on P0/P1), local checks, bot threads resolved, then "ready"; merging is the owner's.
  The next PR starts from a fresh branch off `main` after the previous merge.
- The live site is deployed only at the steps the spec's section 7 names, by the owner or at
  the owner's word.
- No time estimates. Every number below is from the spec or the code, cited, or a test input.

## Open issues for the owner

The spec's section 11 holds the seven decisions. This plan needs 1, 4 and 6 answered before
PR 2 starts (the smoke tests depend on 4; the production check on 6); PR 1 can start on 1a
alone. If 1 is b, see the last section.

## Review focus

- PR 1: the refusal set of spec 6.1 case 3 is complete; the off path is unchanged; no log
  line can carry a claim; the certs cache cannot serve a rotated-out key past 5 minutes.
- PR 2: the service-token headers are route-scoped like the gate header (never
  `extraHTTPHeaders`), and the reporter redacts both values.
- PR 4: `PS_LOGIN` is the only line changed; the rollback command is in the runbook before
  the deploy.
- PR 5: removing `?k=` leaves `x-ps-gate` intact for the API origin and the WAF exemption.

## Files

| File | PR | Change |
|---|---|---|
| `web/worker/access.ts` | 1 | new |
| `web/worker/index.ts` | 1 | the `PS_LOGIN` branch; `Env` gains `PS_LOGIN`, `PS_ACCESS_TEAM_DOMAIN`, `PS_ACCESS_AUD` |
| `web/worker/admin.ts` | 1 | `serveTier` returns `login` |
| `web/wrangler.jsonc` | 1, 4 | `PS_LOGIN: "off"` (PR 1); `"access"` (PR 4) |
| `web/tests/worker-access.test.ts` | 1 | new |
| `web/tests/worker-admin.test.ts` | 1 | one case for `login` |
| `web/src/api/http.ts`, `web/src/state/store.ts` | 1 | `ChallengeError` on redirect or 401 `login_required`; `Tier.login` |
| `web/src/sections/Settings.tsx`, `web/src/copy.ts`, `web/src/controls/ShareDialog.tsx`, `web/src/App.tsx` | 1 | "Sign out"; share hint |
| `web/tests/http-login.test.ts`, `web/tests/copy.test.ts` | 1 | new; the copy needle |
| `web/tests/bundle-hygiene.test.ts` | 1 | three forbidden strings |
| `web/e2e/helpers.ts`, `web/e2e/smoke-lib.ts`, `web/e2e/preview.spec.ts` | 2 | token headers; redaction; production cases |
| `scripts/smoke.sh`, `scripts/smoke_preview.sh` | 2 | token names required when `PS_LOGIN` is on |
| `web/tests/smoke-lib.test.ts`, `tests/test_smoke_scripts.py` | 2 | redaction of the two new names; the scripts' token check |
| `docs/plans/2026-10-13-ks001-cloudflare-runbook.md` | 3, 4 | "Tester login" heading |
| `ROADMAP.md`, `docs/specs/2026-10-13-portfoliosight-demo-design.md` | 5 | shipped item; dated notes |
| `web/worker/preview.ts`, `web/tests/worker-preview.test.ts` | 5 | `?k=` and `ps_preview` removed |

## PRs and merge order

| Order | PR | Tasks | Spec sections | Agent model, effort |
|---|---|---|---|---|
| 1 | A: the Worker verifies Access, behind `PS_LOGIN=off` | 1.1 to 1.6 | 4.5, 4.6, 4.8, 4.10, 6.1, 6.2, 6.4, 8 | opus, high |
| 2 | B: smoke tests with the service token | 2.1 to 2.3 | 4.7, 6.3 | sonnet, xhigh |
| 3 | C: the runbook's "Tester login" steps (docs only, straight to `main`) | 3.1 | 7, 4.11 | fable, high |
| 4 | D: the switch | 4.1 | 7 step 6 | this session, at the owner's word |
| 5 | E: cleanup after the owner declares the rollout done | 5.1, 5.2 | 7 step 9, 11 q7 | sonnet, xhigh |

Branches: `login/worker-access`, `login/smoke-token`, `login/switch`, `login/cleanup`. PR C is
documentation only and goes straight to `main` (owner's git rule).

Care needed: PR A is auth code (fail closed, constant-time where a secret is compared, nothing
logged); PR D touches the live gate. Those are the opus and owner-attended steps.

---

## PR A: the Worker verifies Access, behind `PS_LOGIN=off`

Test harness, shared at the top of `web/tests/worker-access.test.ts`: the `installTimingSafeEqual`,
`makeEnv`, `loadWorker`, `get` and log-capture helpers of `web/tests/worker-preview.test.ts:12-79`,
copied (not imported: each worker test file is self-contained today), plus:

- `const { publicKey, privateKey } = generateKeyPairSync("rsa", { modulusLength: 2048 })` in
  `beforeAll`; `KID = "kid-unit-1"`; `ISSUER = "https://unit.cloudflareaccess.com"`;
  `AUD = "aud-unit-0001"`.
- `certsBody()` → `{ keys: [{ ...publicKey.export({ format: "jwk" }), kid: KID, alg: "RS256",
  use: "sig" }], public_certs: [...] }`; a second pair `OTHER` for the wrong-key case.
- `token(claims, { kid = KID, alg = "RS256", key = privateKey } = {})` builds
  `base64url(header).base64url(claims)` and signs with `node:crypto` `sign("sha256", ...)`.
- `fetch` stub: records every URL; answers the certs URL with `certsBody()` (or whatever the
  test sets with `certsResponse = () => ...`); throws for anything else.
- `loginEnv(overrides)` = `makeEnv({ PS_LOGIN: "access", PS_ACCESS_TEAM_DOMAIN: ISSUER,
  PS_ACCESS_AUD: AUD, ...overrides })`.
- `nowMs` is injected: `access.ts` exports `verifyAccess(request, env, deps)` with
  `deps = { fetchCerts, nowMs }`, and `index.ts` passes the real ones; tests call the Worker
  through `index.ts` with `vi.setSystemTime` for the cache cases.

### Task 1.1: `verifyAccess` and the refusal set

**Spec:** 4.5 (the checks), 6.1 cases 1 to 4.

**Produces:** `web/worker/access.ts` exporting `verifyAccess(request, env, deps): Promise<{ ok: true;
subject: "email" | "common_name" } | { ok: false; reason: "missing" | "invalid" | "certs" }>`,
`ACCESS_HEADER = "Cf-Access-Jwt-Assertion"`, `CERTS_PATH = "/cdn-cgi/access/certs"`,
`CERTS_TTL_MS = 5 * 60_000`.

- [ ] Tests, failing first (`describe("verifyAccess")`, calling the function directly with a
  `Request` carrying the header):
  - `passes_a_valid_person_token`: claims `{ iss: ISSUER, aud: AUD, exp: now + 60, email:
    "tester@example.org", sub: "u1" }` → `{ ok: true, subject: "email" }`; the certs URL was
    fetched exactly once and is `${ISSUER}${CERTS_PATH}`.
  - `passes_a_service_token`: claims with `common_name: "portfoliosight-smoke"` and no `email`
    → `ok: true, subject: "common_name"`.
  - `accepts_aud_as_a_list_containing_ours`: `aud: ["other", AUD]` passes; `aud: ["other"]`
    is refused `invalid`.
  - `refuses_each_bad_token` (`it.each`): no header → `missing`; `"a.b"` and `"a.b.c.d"`;
    `alg: "none"` with an empty signature; `alg: "HS256"` signed with the AUD as key;
    `alg: "RS512"`; `kid: "unknown"`; `iss: ISSUER + "/"`; `iss:
    "https://other.cloudflareaccess.com"`; `aud: "aud-unit-0002"`; `exp` missing; `exp:
    "9999999999"` (a string); `exp: now - 1`; `nbf: now + 60`; signed with `OTHER`'s private
    key; the original signature with one payload byte changed → every one `{ ok: false, reason:
    "invalid" }`. The certs URL was fetched at most twice per case (the unknown-`kid` refetch),
    and no case with a malformed token or a bad `alg` fetched it at all (reject before any
    network).
  - `refuses_when_certs_fail` (`it.each`): certs 500; body `"not json"`; `{ keys: "x" }`;
    `fetch` throws → `{ ok: false, reason: "certs" }`.
  - `refuses_when_not_configured`: `PS_ACCESS_TEAM_DOMAIN` empty, or not `https://`, or
    `PS_ACCESS_AUD` empty → `certs` (fail closed), and no fetch.
- [ ] Implement, after `~/programming/securitysight/frontend/functions/api/[[path]].js:5-74`:
  base64url decode that rejects any character outside `[A-Za-z0-9_-]`; header and claims
  parsed as JSON objects; `alg === "RS256"` and `typeof kid === "string"` before anything
  else; claims checked before the signature (cheap first), signature last with
  `crypto.subtle.importKey("jwk", key, { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" }, false,
  ["verify"])`. Nothing from the claims is interpolated into any log or error string.
- [ ] Tests pass, checks pass, commit.

### Task 1.2: the certs cache

**Spec:** 4.5 ("cached per isolate for 5 minutes; an unknown `kid` refetches once"), 6.1 case 5.

- [ ] Tests, failing first:
  - `two_requests_one_fetch`: two valid tokens in a row → one certs fetch.
  - `refetches_after_five_minutes`: `vi.setSystemTime` forward by `CERTS_TTL_MS + 1` →
    the next request fetches again.
  - `unknown_kid_refetches_once_then_refuses`: a token with `kid: "kid-unit-2"` while the
    stub still serves only `KID` → two fetches total, refused `invalid`; when the stub starts
    serving both kids, the next request passes with no extra fetch beyond the refetch.
  - `a_rotated_out_key_is_not_served_from_cache_after_ttl`: the stub drops `KID`; within the
    TTL the old token still passes (documented, Cloudflare keeps old keys 7 days); after the
    TTL it is refused.
- [ ] Implement: a module-level `{ keys: Map<string, JsonWebKey>; readAt: number; issuer: string
  }` like `currentGeneration` in `web/worker/index.ts:284-286`; a failed fetch replaces
  nothing (a stale cache beats an empty one within the TTL, but a failed fetch with an empty
  cache refuses `certs`).
- [ ] Tests pass, checks pass, commit.

### Task 1.3: the gate branch in `index.ts` and the 401 answers

**Spec:** 4.5 (placement), 4.6, 6.1 cases 6, 8, 10.

- [ ] Tests, failing first (through `loadWorker()` and `get`):
  - `login_on_page_without_assertion_is_a_401_page`: `GET /` with no header → 401,
    `content-type: text/html`, `cache-control: no-store`, `x-robots-tag: noindex`, body
    contains "Sign in to PortfolioSight", no `<script`, no `example.org`; `assetCalls` is empty.
  - `login_on_api_without_assertion_is_json_401`: `GET /api/presets` → 401
    `{"error":{"code":"login_required",...}}`, `x-ps-preview: 1`, `dataGets` empty.
  - `login_on_certs_down_is_503`: → 503 `login_unavailable` (page: an HTML page with the same
    headers; API: JSON).
  - `login_on_valid_token_serves_page_and_api`: `GET /` → the asset; `GET /api/presets` →
    `DATA.get("meta/current.json")` was asked.
  - `login_on_ignores_the_preview_credentials` (`it.each`): `?k=<SECRET>` → 401 and no
    `set-cookie`; a correct `ps_preview` cookie → 401; the `x-ps-gate` header → 401.
  - `login_on_admin_link_still_works_for_a_logged_in_browser`: valid token plus
    `?admin=<admin secret>` → 302 with the `ps_admin` cookie (the existing admin tests'
    expectations at `web/tests/worker-admin.test.ts`).
  - `host_checks_run_first`: `www` → 301 and a foreign host → 404 with no certs fetch and no
    header.
  - `login_on_forwards_no_claim_upstream`: `POST /api/tensors` with a valid token and a
    stubbed origin → the upstream headers are exactly `x-ps-gate`, `accept`, `content-type`,
    `CF-Connecting-IP` (and `x-ps-tier` only with the admin cookie); no `cf-access-*`, no
    `cookie`, no `authorization`.
  - `nothing_logged_carries_the_address`: across all the above, no captured log line contains
    `example.org`, `portfoliosight-smoke` or the token text; refusal lines are exactly
    `access: missing`, `access: invalid`, `access: certs`.
- [ ] Implement in `web/worker/index.ts:482-496`: `const login = env.PS_LOGIN === "access"`;
  if `login`, `const verdict = await verifyAccess(...)`; a refusal returns the 401/503 answer
  (page or JSON by `isApi`) and skips `previewGate`; otherwise fall through to today's code
  with `previewGate` skipped. The 401 page lives in `access.ts` beside the preview page's
  pattern (`web/worker/preview.ts:73-102`) with the copy of spec 8.
- [ ] Tests pass, checks pass, commit.

### Task 1.4: the off path is unchanged

**Spec:** 4.5 ("there is no third mode"), 6.1 case 7, 7 step 2.

- [ ] Tests, failing first: `describe("PS_LOGIN off")` with `it.each(["off", undefined, "1",
  "ACCESS", "worker"])`: `GET /` without any credential → the preview page 403 (today's
  behaviour), `?k=` → 302 with the cookie, `x-ps-gate` → the asset; the certs stub saw no
  fetch; `verifyAccess` was not called (spy on the module export).
- [ ] Run the whole suite: `web/tests/worker-preview.test.ts`, `worker-admin.test.ts`,
  `worker-routing.test.ts`, `worker-share.test.ts`, `worker-ticker-requests.test.ts` pass
  with no edit to them.
- [ ] `web/wrangler.jsonc`: add `"PS_LOGIN": "off"` under `vars` (after `PS_PRIVATE_PREVIEW`).
  Commit.

### Task 1.5: `/api/tier` tells the page; the page handles a lost session; "Sign out"

**Spec:** 4.4, 4.8, 6.2, 8.

- [ ] Tests, failing first:
  - `web/tests/worker-admin.test.ts`: `GET /api/tier` body is `{ tier, menu_max, login:
    "off" }` with `PS_LOGIN` unset and `login: "access"` with it on (and a valid token); no
    other field.
  - `web/tests/http-login.test.ts` (jsdom not needed; stub `fetch`): `fetchPresets` throws
    `ChallengeError` when the response has `redirected: true`; when `response.url` is
    `https://unit.cloudflareaccess.com/...`; when the status is 401 with body
    `{"error":{"code":"login_required"}}`; and does not throw `ChallengeError` for 401 with
    another code or for 503 (today's errors). `fetchTier` parses `login` and defaults to
    `"off"` when absent (so an older Worker answer still works).
  - `web/tests/settings-signout.test.tsx` (`@vitest-environment jsdom`, after
    `web/tests/settings-exclusions.test.tsx`): `Settings` with `login: "access"` renders a link
    with text "Sign out" and `href="/cdn-cgi/access/logout"`; with `login: "off"` it renders
    none.
  - `web/tests/copy.test.ts`: the needle set gains `signOut` and the new `sharePreview` text
    of spec 8.
- [ ] Implement: `web/worker/admin.ts:224-231` (`serveTier` takes `env.PS_LOGIN`); `web/src/api/http.ts`
  (`tierSchema` adds `login: z.enum(["off", "access"]).default("off")`; the three
  `ChallengeError` conditions in the shared response check next to `:69`);
  `web/src/state/store.ts` keeps `login` in the tier state; `web/src/sections/Settings.tsx`
  gets a `login` prop and the link; `web/src/App.tsx` passes it; `web/src/copy.ts` adds
  `signOut` and changes `sharePreview`.
- [ ] Tests pass, checks pass, commit.

### Task 1.6: bundle hygiene and PR A ready

**Spec:** 4.10, 6.4.

- [ ] Test, failing first: `web/tests/bundle-hygiene.test.ts:9` `FORBIDDEN` gains
  `"PS_ACCESS"`, `"CF-Access-Client"`, `"cloudflareaccess.com"`. (It fails first only if the
  bundle contains one of them; run it, and if it passes at once, note that in the commit: the
  guard is still wanted.)
- [ ] `npm run lint && npm run typecheck && npm test && npm run build && npm run e2e:local`
  (README.md:31; `npm run build` first, memory note "e2e needs a build first"). Local e2e
  runs with `PS_LOGIN` unset and must be unaffected.
- [ ] PR body: spec sections 4.5, 4.6, 4.8, 4.10, 6.1, 6.2, 6.4, 8 and this plan "PR A"; the
  statement "deploying this changes nothing while `PS_LOGIN` is `off`" with the task 1.4 test
  names. Review loop, bot threads, then ready. Not deployed by this PR; the owner deploys at
  spec 7 step 2 (`make deploy-frontend`), after which `scripts/smoke.sh` and
  `scripts/smoke_preview.sh` must stay green exactly as today.

---

## PR B: smoke tests with the service token

Starts after PR A merges and the owner has answered questions 4 and 6 (both recommended y/a
here).

### Task 2.1: the headers, route-scoped, and redaction

**Spec:** 4.7.

- [ ] Tests, failing first:
  - `web/tests/smoke-lib.test.ts`: `redact` replaces the values of `PS_ACCESS_CLIENT_ID` and
    `PS_ACCESS_CLIENT_SECRET` from the environment with `[redacted]` (the existing cases for
    `PS_GATE_SECRET` are the pattern).
  - A unit test of the header builder: extract from `web/e2e/helpers.ts` a pure function
    `authHeaders(env): Record<string, string>` (new, exported from `web/e2e/smoke-lib.ts` so
    vitest can import it without Playwright) that returns `{"x-ps-gate": ...}` alone when the
    token names are absent and adds `CF-Access-Client-Id` and `CF-Access-Client-Secret` when
    both are present; one present without the other throws naming the missing one.
- [ ] Implement: `web/e2e/smoke-lib.ts:9-17` gains the two names; `authHeaders`; `web/e2e/helpers.ts`
  uses it everywhere the gate header is set today (the route handler and the `Site.get/post`
  helpers), same host scoping (`siteHosts`, `helpers.ts:40-45`), never `extraHTTPHeaders`.
- [ ] Tests pass, checks pass, commit.

### Task 2.2: the production cases

**Spec:** 6.3.

- [ ] Tests, in `web/e2e/preview.spec.ts` (they run only against production with
  `scripts/smoke_preview.sh`; written now, green once the owner has done spec 7 steps 3 to 6;
  until then they must **skip with a named reason** only when `PS_LOGIN` in the committed
  `wrangler.jsonc` is `"off"`, read with the file's own `stripJsonc`, which is the one skip
  condition this plan allows, and it is removed in PR E):
  - `with the gate header and no token, the login page answers`: `site.get("/", { token:
    false })` → status 302, `location` host ends with `cloudflareaccess.com`, no
    `x-ps-source`, no `chart-canvas`; the same for `/api/presets`.
  - `with the header and the token, the site answers`: 200 and `x-ps-source` on
    `/api/presets`.
  - `the deployed PS_LOGIN equals the committed one`: the version-view walk of
    `preview.spec.ts:44-68` generalised to a `deployedVar(name)` helper and applied to both
    `PS_PRIVATE_PREVIEW` and `PS_LOGIN`.
  - `the Access app is on the apex only, with the two policies and a month's session`:
    `GET /accounts/<id>/access/apps?per_page=1000` with `CLOUDFLARE_API_TOKEN` (read scope,
    question 6a) through a small `run` of `curl` as `helpers.run` does for other commands, or
    Playwright's `request`; exactly one app whose `domain` is `portfoliosight.ai`; none whose
    domain starts with `www.` or ends with `workers.dev` or `portfoliosight.ai/`;
    `session_duration` `720h`; its policies' names are exactly `Smoke tests` (decision
    `service_auth`) and `Testers` (decision `allow`); no policy `include` has a key other than
    `email_domain`, `email`, `service_token`. Addresses in the response are never printed
    (the assertion messages name counts only, and go through `redact`).
- [ ] `Site.get/post` gain `{ token?: boolean }` beside `{ gate?: boolean }`.
- [ ] Commit.

### Task 2.3: the scripts

**Spec:** 4.7, 6.3.

- [ ] `scripts/smoke.sh:26-31` and `scripts/smoke_preview.sh:56-61`: when the committed
  `web/wrangler.jsonc` has `"PS_LOGIN": "access"` (a `grep -E '"PS_LOGIN":\s*"access"'`), the
  loop also requires `PS_ACCESS_CLIENT_ID` and `PS_ACCESS_CLIENT_SECRET`; otherwise not. Test:
  `tests/test_smoke_scripts.py` runs both scripts with a stub env file and a fake Playwright
  on PATH (`:14-30`, `:71-104`); add `test_runner_requires_the_token_only_when_login_is_on`
  there, parametrised over the two scripts and a copy of `web/wrangler.jsonc` with
  `PS_LOGIN` `"off"` and `"access"` (exit 3 and the variable's name on stderr when on and
  missing; a start when off; values never on stdout or stderr).
- [ ] `npm run lint && npm run typecheck && npm test`; from the repo root `ruff check . &&
  ruff format --check . && pyright . && pytest tests/test_smoke_scripts.py -q`. PR body: spec
  4.7, 6.3, this plan "PR B". Review loop, ready.

---

## PR C: the runbook (documentation only, straight to `main`)

### Task 3.1: "Tester login" in the runbook

**Spec:** 7, 4.11, 4.9.

- [ ] Append to `docs/plans/2026-10-13-ks001-cloudflare-runbook.md` a heading `## Tester login
  (spec 2026-11-15)` with the nine steps of spec 7 as the owner's checklist, each with the
  exact dashboard path or command, the rollback for that step, and a line to record the date
  and the result. Include: the dashboard path for the One-time PIN provider check; the app
  creation form fields (hostname `portfoliosight.ai`, no path, session `720h`, name
  "PortfolioSight", policies `Smoke tests` then `Testers`); the service-token creation and
  its expiry date line; the two `wrangler secret put` commands in the `runbook:297-299` form;
  the switch commit; the verification list of spec 7 step 7 including the global-session
  check of spec 4.3; the invite-email line naming `noreply@notify.cloudflare.com`; what a
  tester sees in each row of spec 4.9. Addresses and the team name are written as
  `<placeholders>`.
- [ ] Commit to `main` (docs only, one file) and push.

---

## PR D: the switch (at the owner's word, after spec 7 steps 1 to 5 are recorded)

### Task 4.1: `PS_LOGIN: "access"`

**Spec:** 7 step 6.

- [ ] Branch `login/switch`; the one-line change in `web/wrangler.jsonc`; the runbook's step 6
  line gets the date. The PR body quotes the rollback: `cd web && npx wrangler rollback`, or
  `PS_LOGIN: "off"` and `make deploy-frontend`, and that both leave the Access app in place.
- [ ] After the owner merges: `make deploy-frontend` from the main checkout at the merged
  SHA; then `scripts/smoke_preview.sh` (the task 2.2 cases now run) and `scripts/smoke.sh`
  (DoD-01 to DoD-31 with the token). Record both results and the deployed SHA in the runbook
  (docs commit to `main`). If either is red: rollback first, diagnose second.
- [ ] The owner's own check of spec 7 step 7 is reported as awaiting the owner, as H-PS-01 was.

---

## PR E: cleanup, after the owner declares the rollout done

### Task 5.1: retire the preview key

**Spec:** 7 step 9, 4.6.

- [ ] Tests first, in `web/tests/worker-preview.test.ts`: with `PS_LOGIN=off` and preview on,
  `?k=<secret>` now gets the preview page 403 and sets no cookie; a `ps_preview` cookie gets
  403; `x-ps-gate` still passes (the API origin and the WAF exemption keep it); the
  `withoutParam`, `cookieValues` and `secretEquals` helpers stay (admin uses them,
  `web/worker/admin.ts:148`). Delete the `?k=` and cookie cases that assert the old behaviour.
  Remove the task 2.2 skip condition.
- [ ] Implement in `web/worker/preview.ts:108-133`: drop the `?k=` branch and the cookie
  branch; `PREVIEW_COOKIE` and `previewCookieValue` go with them; `bundle-hygiene.test.ts:9`
  keeps `ps_preview` forbidden. `web/e2e/preview.spec.ts` header comment updated.
- [ ] Checks, commit.

### Task 5.2: the record

**Spec:** 11 question 7, 9.

- [ ] `ROADMAP.md:49-50`: move the item under the shipped heading with the switch date.
  `docs/specs/2026-10-13-portfoliosight-demo-design.md`: a dated note at section 9.6, at
  S19 (`:650`) and at M4 (`:681`): "Owner decision <date>: the preview key is replaced by the
  tester login of `docs/specs/2026-11-15-portfoliosight-otp-login-design.md`." The
  Appendix B strings the demo plan's task 7.5.2 names ("Paid tier", "Data license",
  "exact-ENB", "FERS planner") stay in `ROADMAP.md`.
- [ ] PR body: spec 7 step 9 and this plan "PR E". Review loop, ready. After the merge,
  `~/.claude/scripts/worktree-cleanup.py` dry run, then `--apply --remote` for the five
  `login/*` branches whose work is in `main`.

---

## If the owner picks 1b (the Worker-native code)

PR A is replaced by two PRs and PR B shrinks; PRs C, D, E keep their shape with
`PS_LOGIN="worker"` (and the transition value `"both"`, spec 5 "Gate").

- **PR A1, `login/worker-codes` (opus, high):** `web/worker/login.ts` and the `LoginCodes`
  Durable Object (spec 5 "Endpoints", "Code", "Rate limits", "Storage"), tests in
  `web/tests/worker-login.test.ts` using the sql.js-backed DO harness of
  `web/tests/worker-share.test.ts` (the `ShareLimiter` cases are the pattern). Tasks: the
  code generator (uniformity test over 60,000 draws: every digit position's chi-square
  within the 99.9% bound, fixed seed through an injected `getRandomValues`); the store (no
  clear address or code in any row: read the table back); the limits (per address, per IP,
  global, each at its boundary and one over); the verify answers (wrong, expired at 10
  minutes plus one millisecond, sixth attempt, reused, never issued: one body); the session
  cookie (sign, verify, tamper, expiry, secret rotation); logout. `wrangler.jsonc`: binding
  `LOGIN_CODES`, migration `v3`, `PS_LOGIN: "off"`; secrets `PS_SESSION_SECRET`,
  `PS_LOGIN_DOMAINS`, `PS_LOGIN_EMAILS`.
- **PR A2, `login/worker-page` (sonnet, xhigh):** `web/worker/loginPage.ts` (spec 5 "Login
  page"), the `sendMail` refactor of `web/worker/share.ts:296-330` with the fixed template
  (spec 5 "Mail"; the share tests must pass unchanged), the gate branch for `"worker"` and
  `"both"` in `index.ts` with the task 1.3 and 1.4 tests adapted (`ps_session` in place of the
  assertion), and the page work of task 1.5 with "Sign out" posting to `/api/logout`.
- **PR B:** no service token; the smoke tests keep `x-ps-gate` alone, which spec 5 "Gate"
  still honours. Task 2.2's Access-app case is replaced by "the deployed `PS_LOGIN` equals the
  committed one" and "a request with no cookie and no header gets the login page".
- **The runbook:** replaces the dashboard steps with the three `wrangler secret put`
  commands and the MailChannels sender check already recorded for share.
