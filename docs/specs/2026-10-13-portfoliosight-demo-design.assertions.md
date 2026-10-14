# Executable assertions — PortfolioSight demo

Source spec: `docs/specs/2026-10-13-portfoliosight-demo-design.md` (revision 2 plus §9.6 of 2026-10-13).
Written by `/spec-craft:executable-assertions` (spec-craft 0.3.0) on 2026-10-13.

These are 4-part assertion **specs**, not test code. A downstream `/conductor:assertions-to-tests`
step turns each into one runnable test wired into the run's gate manifest by id. The ids below are
stable; a red result names the violated claim.

---

## 0. How this gate is organized

**One assertion, one phase.** The spec's §12 builds in seven steps (Step P, Phases 0–5). Each
assertion is tagged with the phase that naturally turns it green and with where it runs. No
assertion needs a later phase than its tag; several stay green from their phase onward and must
not regress.

| Runs | Meaning |
|---|---|
| `unit` | Python (`pytest`) or TypeScript (`vitest`) over fixtures; no network, no browser. |
| `api` | FastAPI `TestClient` with `LocalStore` in a temp dir (and `moto` for the S3 interface). |
| `ui` | Playwright against `vite preview` with the fixture tensor `web/fixtures/guide2017_5y.json` served by a static mock of `/api/*`. |
| `static` | A check over the repository tree, the built image or the built bundle. |
| `live` | Needs `~/.secrets/portfoliosight.env` on the laptop and the network; Phase 0 owns two of these by the spec's own assignment (§12 "Live gates are owned by exactly one phase"). |
| `prod` | Against `https://portfoliosight.ai` / `https://api.portfoliosight.ai` with the `x-ps-gate` header, from the laptop. |

**Phase map** (every phase has at least one assertion only it can turn green):

| Phase | Ids |
|---|---|
| Step P | A-PS-01 |
| Phase 0 (data) | A-PS-02 … A-PS-14 |
| Phase 1 (engine) | A-PS-15 … A-PS-25 |
| Phase 2 (API, nightly, container) | A-PS-26 … A-PS-33 |
| Phase 3 (front end) | A-PS-34 … A-PS-53 |
| Phase 4 (production deployment) | A-PS-54 … A-PS-60, A-PS-66, A-PS-67, A-PS-68 |
| Phase 5 (smoke tests and docs) | A-PS-61 … A-PS-65 |

**No owner-gated group.** Two things were owner-gated while this file was drafted and both cleared
on 2026-10-13: §9.6 approves loading Tiingo-sourced data into R2 for development and testing, and
the owner added `Zone › Zone WAF › Edit` to the Cloudflare token (listing the zone's rulesets now
succeeds), so the build can create the two WAF custom rules and the rate-limiting rule of §9.4
itself. The WAF assertions (A-PS-66…68) therefore sit in the normal Phase 4 group. If
either permission is withdrawn, the affected assertions state their dependency in the setup and
should be reported as blocked, not failed, without being weakened.

**Private preview (§9.6) under the WAF ordering.** The Managed Challenge rule (`ps-challenge-site`)
runs at the edge before the Worker, and both the rule's exemption and the Worker's preview gate key
on the same `x-ps-gate` secret. So in production a headerless, cookieless request gets Cloudflare's
challenge (A-PS-66), never the Worker's preview page; a request that passes the WAF but lacks the
preview key is **not constructible without weakening the rule** (the only way through the challenge
without the header is a real browser's `cf_clearance` cookie, which automation cannot obtain
reliably). The preview page is therefore asserted at the unit level (A-PS-39), the deployed
`PS_PRIVATE_PREVIEW` var and the absence of data on any keyless path are asserted in production
(A-PS-61), and the preview page's appearance after a cleared challenge is the owner's own browser
check (H-PS-01, human verification, not in the machine gate: the Managed Challenge is built not to
clear for automation). Production assertions send the `x-ps-gate` header, as the spec's smoke tests
do.

**Taste is not encoded.** "Fantastic visuals", "looks designed on purpose", "a visitor can tell what
the colors mean without instructions" go to the owner as screenshots (§Expectations, "Open"). The
mechanical proxies kept here are the honest ones: no table on the first screen, no jargon in the
default DOM, four themes with distinct computed tokens and a repainted canvas, no horizontal
scroll on a phone.

---

## 1. Load-bearing expectations — encoded

Grouped by the phase that turns them green. Each line: id — what it proves (expectations covered) —
why it is load-bearing.

**Step P**
- **A-PS-01 — the shared dependency set installs, imports and lints.** (§12 Step P) Everything
  downstream branches from it; a broken `pyproject` fails both parallel phases silently late.

**Phase 0 — data layer**
- **A-PS-02 — the total-return index is rebuilt from close, dividends and splits, not copied from
  adjClose.** (F10, M7, §4.1) "A stock split shown as a crash" and "missing dividends making a bond
  fund look flat" are the two silent data lies the owner named.
- **A-PS-03 — a provider tail splices onto a seeded record without a seam.** (F10, §4.1, §5.1) A seam
  at `adjusted_through` is an invented one-day return in every window that spans it.
- **A-PS-04 — the seed converts the lake faithfully, refuses post-adjustment drift, and never writes
  to the lake.** (M2, §5.4) The one-time seed is the base of 1,400 histories; QSE's files must stay
  untouched.
- **A-PS-05 — missing prices stay missing.** (M7, §4.1, §5.6) Nothing is interpolated, back-filled or
  carried forward; windows use only the shared dates.
- **A-PS-06 — the provider budget ledger stops, sleeps and resumes at the configured limits.** (§5.2,
  §5.4) Overrunning the plan is a billing/terms problem that looks like success.
- **A-PS-07 — served means current.** (S24, F13, §5.2) A `pending` or `stale` symbol must never reach
  `/api/symbols`; a `stale` one recovers on the next successful fetch.
- **A-PS-08 — `D_G` follows the §4.2 calendar rule.** (F13, §4.2) Every freshness claim downstream is
  measured against this value.
- **A-PS-09 — tsp.gov rows are parsed only under the exact header.** (F10, §5.5) A silently changed
  column order would put the wrong fund's prices under a TSP id.
- **A-PS-10 — runtime code reaches only Tiingo, tsp.gov, R2 and MailChannels, never yfinance or
  `qse.env`, and redacts tokens from logs.** (M2, M3, §5.1) Static hygiene that is cheap to check and
  expensive to discover late.
- **A-PS-11 — the backup refuses loudly when D: is unmounted, mirrors with `--delete`, restores
  without it, and the cron installer is idempotent.** (S21, §5.3) A silent skip is the stated failure.
- **A-PS-12 — the KS-001 cache never exceeds its cap.** (M5, §5.3) Disk growth on KS-001 is a must-not.
- **A-PS-13 — the R2 store verify passes against `portfoliosight-data`.** (DoD 28 first half; live)
  Owned by Phase 0 per §12.
- **A-PS-14 — the Tiingo adapter returns the four fields live and `measure-limits` records the
  tier.** (DoD 22; live) Owned by Phase 0 per §12.

**Phase 1 — engine**
- **A-PS-15 — minimum-torsion ENB identities hold and violations raise.** (§4.6) The diversification
  measure behind every word, color and slider end.
- **A-PS-16 — frontier nodes sit on their ceiling and returns do not decrease.** (S23, §4.5) The
  curve the risk slider walks.
- **A-PS-17 — every computed mix is real: sums to one, inside bounds, under its ceiling, ENB in
  range; a bad vector raises.** (S23, §4.11) Checked through the builder, not the solver alone.
- **A-PS-18 — the surface proxy is monotone and the bottom end is at least as diversified as the
  top.** (F9, §4.7) Otherwise the "More diversified" end lies.
- **A-PS-19 — the suggested point is bracketed and the standard-error walk stops at the first
  failure.** (S4, §4.8) The default position of the second slider.
- **A-PS-20 — moments are estimated as specified.** (§4.3) Wrong shrinkage reproduces exactly the
  "85% in one fund" failure (F3).
- **A-PS-21 — caps scale with the menu and are validated; no 23-fund mix exceeds 25%.** (S12, F3,
  §4.4) The concentration guard.
- **A-PS-22 — window inclusion, the 126-row floor and the fixed exclusion templates.** (S24, §4.2,
  §5.6) "Says so in one sentence and carries on."
- **A-PS-23 — stress returns are never fabricated.** (M7, F10, §4.10) `null` when a fund lacks prices
  at a window edge.
- **A-PS-24 — a tensor is deterministic, schema-valid, full-precision, carries a correct
  `frontier_curve` and `s_safe`, builds in ≤ 90 s, and the UI fixture is its unedited output.**
  (§4.12, §7, §12 Phase 1) The contract between engine, API and browser.
- **A-PS-25 — the engine is pure and fully covered.** (§4, §10) 100% line coverage on
  `portfoliosight/engine/`; no I/O imports.

**Phase 2 — API, nightly, container**
- **A-PS-26 — every `/v1/*` request without the gate secret is refused, in constant time.** (S19,
  §6) The authentication of record.
- **A-PS-27 — a custom build runs to `ready`, is deduplicated, retries a failure at most three
  times, and never overwrites a key.** (S11, F14, §6, §4.12) "Spins forever" and "errors" are the
  named failures.
- **A-PS-28 — bad requests are refused with the specified codes and nothing is enqueued.** (§6,
  §4.4) Input limits are the abuse boundary.
- **A-PS-29 — the universe hash is canonical.** (§6) A non-canonical hash means duplicate builds or
  a shared key for different menus.
- **A-PS-30 — a generation is published only when complete, and never half-visible.** (F13, §5.4)
  Readers must never see a half-built generation.
- **A-PS-31 — presets and health bodies match `data/presets.json` and the holdings CSV.** (S2, §6,
  Appendix A) The default view's source of truth.
- **A-PS-32 — the image, the repository and the compose file hold no holdings, no secrets, no data
  mount, and cap resources.** (M1, M2, M5, DoD 25) Must-nots with irreversible consequences.
- **A-PS-33 — the API surface is exactly the §6 table.** (M4, M10) No login, no payments, no extra
  routes.

**Phase 3 — front end**
- **A-PS-34 — browser math reproduces the tensor and interpolation keeps every invariant.** (S22,
  S23, DoD 24, §4.11) The browser only interpolates; this is the proof it does so faithfully.
- **A-PS-35 — amounts become weights in all three units, the 100% rule gates, and trades are
  computed per unit.** (S9, S10, DoD 13)
- **A-PS-36 — the URL codec round-trips every state.** (S17, S22, §8.1)
- **A-PS-37 — the client never waits on the server during a drag, recovers from an expired
  challenge by reloading, and stops after three failed builds.** (F8, F12, F14, §3.2)
- **A-PS-38 — share validators, the fixed template and the caps.** (S18, F15, §9.3) The one outbound
  channel.
- **A-PS-39 — the private-preview gate.** (M3 as reworded, §9.6) No key → 403 page without data;
  header passes; `?k=` sets the cookie and redirects; wrong key refused; preview off passes
  through; the secret is never echoed.
- **A-PS-40 — the Worker's routing surface is exactly §9.3.** (M4, M10, §9.3) Host check, R2 reads,
  origin forwarding with the gate header, share, assets, nothing else.
- **A-PS-41 — the first screen is the chart and its controls; sections are collapsed; no tangency
  marker.** (S1, S8, F1, F2, DoD 3)
- **A-PS-42 — the phone layout fits and works with a thumb.** (S16, F6, DoD 4)
- **A-PS-43 — the default view is the Example Portfolio with its allocation and no fund set
  aside; a menu holding a fund its tensor sets aside shows the excluded-fund note; the preset menu
  is driven by `/api/presets`.** (S2, S24, DoD 5)
- **A-PS-44 — the heatmap renders from the theme ramp under the frontier only.** (S5, DoD 7)
- **A-PS-45 — the risk slider's readouts are the frontier mix's truth and move together without a
  request.** (S3, F7, F8, DoD 8)
- **A-PS-46 — the diversification slider starts at the suggested spot, moves the point down and
  never right, and the point is drawn where its mix sits.** (S4, F9, S23, DoD 9)
- **A-PS-47 — the diversification word is quiet, one of four, with thresholds as specified.** (S6,
  F4, DoD 10)
- **A-PS-48 — the default DOM is plain language, impersonal, with the disclaimer always visible.**
  (S7, F2, F11, M6, M8, DoD 6, DoD 20)
- **A-PS-49 — four themes with distinct computed tokens and a repainted canvas; the choice is
  remembered; HUD references nothing.** (S15, F5, M6, DoD 17, DoD 18)
- **A-PS-50 — stress cards show real history with coverage, or say they cannot.** (S14, M7, DoD 16)
- **A-PS-51 — the address reproduces the view in a fresh context.** (S17, S22, DoD 19)
- **A-PS-52 — the bundle carries no secret, no gate header and no origin host.** (M2, §9.4)
- **A-PS-53 — cap edits are validated inline and sent only when valid.** (S12, DoD 14 local part)

**Phase 4 — production deployment**
- **A-PS-54 — the page loads with the header on both viewports.** (S20, DoD 1 header part)
- **A-PS-55 — the origin gate, the www redirect and the disabled `workers.dev` host.** (S19, DoD 2
  application part)
- **A-PS-56 — presets and tensors are served from R2 and a POST for the default preset resolves to
  the same tensor.** (DoD 21)
- **A-PS-57 — the nightly is fresh: `asof` equals `D_G`, the run finished clean, twelve tensors
  exist, the cache is under its cap, and the page says which date it shows.** (S20, F13, M5, DoD 23)
- **A-PS-58 — the store is verified, seeded, mirrored, and the cron is installed once.** (S21,
  DoD 28 second half)
- **A-PS-59 — every served symbol is current and the runbook records the licensing decision.**
  (DoD 29 as superseded by §9.6)
- **A-PS-60 — a 23-fund build completes within the benchmark on KS-001.** (DoD 30, §4.12)
- **A-PS-66 — a headerless, cookieless request to `/` is Managed-Challenged at the edge.** (S19,
  DoD 2, §9.4) The only gate the spec allows, and the one that must sit in front of everything.
- **A-PS-67 — a headerless request to `api.portfoliosight.ai` is blocked at the edge, before the
  origin.** (S19, DoD 2, §9.4) Without it the tunnel origin is one secret away from the public.
- **A-PS-68 — the edge rate-limits `POST /api/tensors` and leaves polling alone.** (§9.4) The
  abuse boundary for the one expensive endpoint.

**Phase 5 — smoke tests and docs**
- **A-PS-61 — private preview is on in production and no keyless path yields data.** (M3 as
  reworded, §9.6)
- **A-PS-62 — TSP loads in one click and a custom menu builds end to end in production.** (S2,
  S11, S12, F14, DoD 11, DoD 12)
- **A-PS-63 — lookbacks, ghosts and cap rebuilds work in production.** (S13, S12, DoD 14, DoD 15)
- **A-PS-64 — share by email sends the fixed message to the test recipient only.** (S18, F15,
  DoD 31)
- **A-PS-65 — quality gates, one smoke test per DoD item, no skipped tests, docs updated.** (M9,
  DoD 26, DoD 27)

## 2. Deliberately NOT encoded

**Taste, judged by the owner from screenshots:**
- "Fantastic visuals", "each look is designed on purpose", "striking chart" (S1, S15, §Open). No
  Boolean. The proxies kept are A-PS-41, A-PS-44, A-PS-49.
- "A visitor can tell what the colors mean without instructions" (S5). The legend's presence is
  checked in A-PS-44; comprehension is not.
- "Every label can be read by an average 401(k) holder" (S7). The forbidden-word and must-contain
  lists of A-PS-48 are the mechanical residue; readability itself is not.

**Not machine-provable in the run's environment:**
- **Challenge expiry mid-session in production** (F12 second half). Cloudflare's clearance lifetime
  cannot be forced from a test. The client's recovery is proven with mocked responses in A-PS-37;
  the live path is the owner's own browsing.
- **"Refreshes itself nightly without me" as a trend** (S20). A-PS-57 proves freshness on the day
  it runs; it cannot prove the next night. The systemd timer's `enable --now` state is part of
  A-PS-57's setup, not a separate claim.
- **The email actually arrives** (S18). MailChannels' 202 and the sender address in the request
  body are what A-PS-38 and A-PS-64 can see; delivery is outside the gate.

**Not load-bearing, or already enforced elsewhere:**
- **F16 ("tests pass by checking that things exist").** This is the red-team rule applied to every
  observation below, not a product assertion. The conductor's gate freeze and the per-phase review
  are the enforcement.
- **M9 ("never disable, skip or weaken a test").** The conductor's `.frozen` baseline is the
  mechanism; A-PS-65 adds the one mechanical residue (no unconditional skip markers in the
  project's own tests).
- **M10 ("never build past the demo").** A grep for "FERS", "payments" and so on is brittle and
  self-referencing. The sharp form is the exact-surface check: A-PS-33 (API routes) and A-PS-40
  (Worker routes) refuse any route beyond the spec's tables.
- **The runtime target as a promise** (§4.12). The spec itself says benchmark, not promise; A-PS-60
  checks the DoD 30 wording (≤ 30 s, or the named fallback grid and ≤ 30 s re-measured).
- **Tiingo plan tier (Starter vs Power).** Measured and recorded (A-PS-14), not asserted: either
  tier is acceptable to the spec.
- **DoD 29's "owner checkbox ticked".** Superseded by §9.6; A-PS-59 checks the replacement (the
  dated licensing decision in the runbook) as a prose leg, and A-PS-61 checks the real protection
  (private preview on).

**Folded into another assertion rather than duplicated:**
- F1, F2 (dashboard look, jargon leak, tangency point) → A-PS-41 and A-PS-48.
- F3 (one or two funds) → A-PS-21 (caps) and A-PS-20 (shrinkage); the specific "85% in a hedged
  Japan fund" cannot occur under a 25% cap and is not separately asserted.
- F7 (drifting sliders) → A-PS-45 (one parameter `s`; both readouts change on every move).
- S22 (figures agree) → A-PS-34 (same math), A-PS-45/46 (chart vs strip), A-PS-51 (shared link).
- M4 (no own human check, no login) → A-PS-33, A-PS-40 (exact surfaces) and A-PS-48 (no login
  vocabulary in the DOM).
- M6 ("Risk Number", "Risk Score", the film) → A-PS-48 and A-PS-49.
- M8 (never advice, never hide the disclaimer) → A-PS-48.

**Flags raised while writing (gaps the spec should settle; none quietly added):**
- **How the page learns that preview is on.** §9.6 says the share dialog "says so while preview is
  on", but no field or header carries the preview state to the browser. A-PS-38 asserts the dialog
  behaviour against a client-side flag and leaves the transport to the build; the plan should name
  it (a response header on `/api/*` or a field in `/api/health` are the obvious choices).
- **The `ps_preview` cookie value.** §9.6 says the key is "never logged or echoed". A-PS-39 reads
  that as: the raw secret must not appear in any response header or body, so the cookie value must
  be derived (for example an HMAC of the secret), not the secret itself. If the owner intended the
  cookie to carry the secret, loosen A-PS-39's must-not-contain for the `Set-Cookie` header only.
- **DoD 12's four tickers.** `VOO, BND, VNQ, SGOV` are only buildable once served. A-PS-62 picks
  four served symbols from `/api/symbols` (preferring those four) so the check tracks the real
  catalog rather than a constant.
- **DoD 30's "measured on KS-001".** A-PS-60 measures from the laptop as POST-to-ready time with an
  idle queue, which is the build time plus tunnel latency; that is the number a visitor waits for
  and the one worth recording.

## 3. The 4-part specs

Each spec carries a `Phase · runs` line (see §0), then the four parts.

### Step P

### A-PS-01 — the shared dependency set installs, imports and lints
Step P · unit/static
- **Claim.** A fresh virtual environment built from the committed `pyproject.toml` with
  `uv pip install -e ".[api,dev]"` imports every runtime and dev dependency the spec names, passes
  the committed `ruff` and `pyright` configuration, collects tests without error, and confines
  `yfinance` to the `research` extra.
- **Setup.** A clean temporary venv (no site-packages inherited); the repository at HEAD; network
  access for the install only.
- **Observation.** (1) The install exits 0. (2) `python -c "import numpy, pandas, pyarrow, scipy,
  sklearn, cvxpy, clarabel, requests, pydantic, boto3, exchange_calendars, fastapi, uvicorn, pytest,
  pytest_cov, responses, moto, httpx"` exits 0 in that venv. (3) `ruff check . && ruff format
  --check . && pyright .` exit 0. (4) `pytest --collect-only -q` exits 0 or 5 (nothing collected
  yet) and prints no `ERROR` line. (5) Parsing `pyproject.toml`: `yfinance`, `matplotlib`, `plotly`
  and `skfolio` appear only under `[project.optional-dependencies].research`; **must not** appear
  in `dependencies`, `api` or `dev`. (6) `python -c "import yfinance"` in the `[api,dev]` venv
  **fails** (proves the extra is really separate, not merely labelled). Fail = any of (1)–(6)
  otherwise.
- **Kind.** contract.

### Phase 0 — data layer

### A-PS-02 — the total-return index is rebuilt from close, dividends and splits, not copied from adjClose
Phase 0 · unit
- **Claim.** For every recorded provider fixture, the `tr_index` the adapter builds from `close`,
  `divCash` and `splitFactor` alone reproduces the provider's `adjClose` ratio day by day within
  1e-5, and the adapter does not read `adjClose` to build it.
- **Setup.** The five recorded Tiingo JSON fixtures of §10: AAPL around 2020-08-31 (4:1 split),
  NVDA around 2024-06-10 (10:1), USO around 2020-04-29 (1:8 reverse split), VTI full history and
  VBIAX full history (dividends and the Dec-2025 fund distribution). The adapter's conversion
  entry point (§4.1 formula with the `basis` rule) and the `tiingo` provider's `fetch_daily` wired
  to `responses` replaying the fixtures.
- **Observation.** For each fixture, for every consecutive pair of days `(t−1, t)`:
  `|tr_index_t / tr_index_{t−1} − adjClose_t / adjClose_{t−1}| ≤ 1e-5`. **Must-contain:** a
  non-trivial check on each fixture, i.e. at least one day with `splitFactor ≠ 1` in each of the
  three split fixtures and at least one day with `divCash > 0` in each of VTI and VBIAX, and on
  those days the raw `close` ratio differs from the `tr_index` ratio (otherwise the adjustment
  did nothing). **Must-not-contain:** a dependency on `adjClose`: re-running the conversion on the
  same fixture with the `adjClose` column removed yields a byte-identical `tr_index`. Fail = any
  day outside tolerance on any fixture, a fixture with no action day, or a different result when
  `adjClose` is withheld.
- **Kind.** property (holds across all five fixtures and every day in each).

### A-PS-03 — a provider tail splices onto a seeded record without a seam
Phase 0 · unit
- **Claim.** Splicing a provider tail fetched from `adjusted_through − 7 days` onto a seed-style
  record at `adjusted_through` yields a `tr_index` within 1e-5 of the all-provider index from the
  first spliced day on, updates `adjusted_through` to the last fetched date, and the refresh
  logic skips a symbol only when both its prices and its adjustments reach `D_G`.
- **Setup.** The VTI fixture; a seed-style record derived from it and cut at 2025-12-31 (price-only
  after that date, `adjusted_through = 2025-12-31`); the splice routine of §5.1; a refresh
  planner given a manifest with four symbols: (a) `last_date ≥ D_G` and `adjusted_through ≥ D_G`;
  (b) `last_date ≥ D_G`, `adjusted_through < D_G`; (c) `last_date < D_G`, `adjusted_through ≥ D_G`;
  (d) both behind.
- **Observation.** (1) For every date from 2026-01-02 on, `|tr_spliced / tr_full − 1| ≤ 1e-5` where
  both indices are rebased to 2025-12-31; the day 2026-01-02 itself must be checked (the seam).
  (2) The splice is called with `start = adjusted_through − 7 days` (inspect the request the
  adapter received, not the function's own argument). (3) After the splice `adjusted_through`
  equals the tail's last date and rows after it are absent. (4) The planner skips only (a) and
  refetches (b), (c), (d), each from `adjusted_through − 7 days`. **Must-not-contain:** a
  spliced index whose seam-day return differs from the all-provider return by more than 1e-5
  (an invented crash or jump). Fail = any of (1)–(4).
- **Kind.** property (every post-seam day; all four manifest states).

### A-PS-04 — the seed converts the lake faithfully, refuses post-adjustment drift, and never writes to the lake
Phase 0 · unit
- **Claim.** `scripts/seed_r2_from_lake.py` converts each lake parquet to the canonical record with
  `tr_index = adj_close / adj_close[0]`, refuses to upload anything when any row after
  `--adjusted-through` has `adj_close ≠ close`, writes manifest entries `source: seed`,
  `status: pending`, `adjusted_through` as given, exits non-zero with a clear message when the
  lake path is missing or holds fewer than 1,000 files, and leaves every lake file byte-identical.
- **Setup.** The three-symbol fixture lake `tests/fixtures/lake/` (columns `date, open, high, low,
  close, adj_close, volume`), a `LocalStore` target, and a second copy of the lake in which one
  row dated after `--adjusted-through` has `adj_close ≠ close`. The file-count floor is lowered
  by a test-only flag or by pointing at a lake of ≥ 1,000 tiny files; the test must exercise the
  floor either way.
- **Observation.** (1) Clean lake: every uploaded `prices/{SYMBOL}.parquet` has `tr_index[0] == 1.0`
  and `tr_index_t / tr_index_{t−1} == adj_close_t / adj_close_{t−1}` within 1e-12 for all days;
  rows after `--adjusted-through` are price-only (no `tr_index` beyond that date, or flagged as
  such per the store's convention); manifest entries carry exactly `source: seed`,
  `status: pending`, the given `adjusted_through`. (2) Drifted lake: exit non-zero, the message
  names the symbol and date, and the store holds **zero** `prices/` keys afterwards (not "some").
  (3) `--dry-run`: the assertion report and the latest per-symbol adjustment dates are printed,
  zero keys written. (4) Missing path and under-1,000 files: non-zero exit, message names the
  path. (5) SHA-256 of every lake file before == after in all runs. **Must-not-contain:** any
  write under the lake path (also assert no new files appear there). Fail = any leg.
- **Kind.** property (every symbol and day of the fixture lake; both lake variants).

### A-PS-05 — missing prices stay missing
Phase 0 · unit
- **Claim.** The returns builder leaves a fund's return `NaN` on every day it has no price, uses
  the union of all funds' dates as the calendar, and a window's sample is exactly the intersection
  of included funds' return dates; no value is forward-filled, interpolated or back-filled.
- **Setup.** Three synthetic canonical records: A with all days, B missing a block of 5 interior
  days, C starting 60 days later than A and B. The §4.1 returns builder and the window sampler.
- **Observation.** (1) The calendar equals `dates(A) ∪ dates(B) ∪ dates(C)`. (2) B's returns are
  `NaN` on the 5 missing days **and** on the first day after the gap (no price at `t−1`); C's are
  `NaN` before its first day. (3) The sample for a window containing the gap has exactly
  `|dates(A) ∩ dates(B) ∩ dates(C)| − 1` rows (minus the first return day) and none of the
  gap days. (4) **Must-not-contain:** a finite return on any day listed in (2); a sample row on a
  gap day; a call to `ffill`, `bfill` or `interpolate` reachable from the builder (assert by
  monkeypatching those pandas methods to raise during the run). Fail = any leg.
- **Kind.** property (every day of the three synthetic records).

### A-PS-06 — the provider budget ledger stops, sleeps and resumes at the configured limits
Phase 0 · unit
- **Claim.** The downloader reads limits from `meta/provider_limits.json` (else the env fallbacks
  45/900/450), counts requests per UTC hour and day and unique symbols per month in
  `meta/budget.json`, sleeps to the next hour when the hourly budget is spent, exits cleanly when
  the daily or monthly budget is spent, and resumes on the next run from where it stopped.
- **Setup.** `LocalStore`; a fake clock injected into the downloader; a fake provider that records
  every call; a configured nightly set of 100 symbols; limits file with `req_per_hour = 10`,
  `req_per_day = 25`, `unique_symbols_per_month = 30`; a second scenario with no limits file and
  env fallbacks; a `measure-limits` scenario with a fake provider returning 429 on the 37th call.
- **Observation.** (1) After 10 calls in one clock-hour the next call is preceded by a sleep to
  the top of the next hour (fake clock advanced, no provider call in between). (2) At 25 calls in
  a day the run exits 0 with a "daily budget spent" message and the ledger shows 25. (3) A rerun
  the same day makes zero provider calls; a rerun the next day continues with the 26th symbol of
  the priority order, not the 1st. (4) At 30 unique symbols in a month, a 31st new symbol is not
  fetched; a previously fetched symbol still is. (5) With no limits file, the first run uses
  45/900/450 (assert via the ledger's recorded limits). (6) `measure-limits` writes
  `meta/provider_limits.json` with keys `provider, tier, req_per_hour, req_per_day,
  unique_symbols_per_month, measured_on, method` and `tier = "starter"`, `method = "probe"`
  when the 429 arrives before the 60th probe; with no 429, `tier` records "at least 60/10 min"
  semantics as the spec states and `method = "probe"`. **Must-not-contain:** a provider call
  beyond any limit in any scenario (count the fake provider's calls). Fail = any leg.
- **Kind.** property (hour, day, month limits; file and env sources; both probe outcomes).

### A-PS-07 — served means current
Phase 0 · unit
- **Claim.** A symbol's manifest status is `ok` exactly when `last_date ≥ D − 3` and
  `adjusted_through ≥ D − 3` trading days; seeded symbols are `pending` until their first tail
  refresh; a served symbol that falls behind becomes `stale` and recovers to `ok` on the next
  successful refresh; `meta/symbols.json` lists `ok` symbols only with `tiers_served` derived from
  them; `unavailable` symbols are retried on the first run of each month.
- **Setup.** `LocalStore`, a fixed `D_G`, the XNYS calendar, a fake provider; manifest with symbols
  in each state plus one seeded symbol never refreshed and one 404 symbol.
- **Observation.** Drive the status rule and the refresh over a sequence of fake days:
  `pending → ok` after the tail refresh; `ok → stale` after `D_G` advances 4 trading days with no
  fetch; `stale → ok` after one successful fetch (refresh visits it although it is `stale`);
  `unavailable` stays so and is re-requested only on a run dated the 1st of a month. Boundary:
  `adjusted_through = D − 3` is `ok`, `D − 4` is not. `meta/symbols.json` after each rewrite
  contains exactly the `ok` ids (set equality, not subset) and `tiers_served` equals the tiers
  of those ids. **Must-not-contain:** a `pending`, `stale` or `unavailable` id in
  `symbols.json`; the never-refreshed seeded symbol in `symbols.json` even when its
  `last_date` is recent. Fail = any transition or listing differs.
- **Kind.** property (all four statuses, both boundary days, both tier-list sides).

### A-PS-08 — `D_G` follows the §4.2 calendar rule
Phase 0 · unit
- **Claim.** `D_G` is the most recent XNYS session whose close is at least 6 hours before the
  nightly's scheduled start (02:00 America/Los_Angeles on the run date), computed with
  `exchange_calendars`, independent of which funds are included.
- **Setup.** The calendar module; fixed run instants: a Wednesday run (expect Tuesday), a Monday
  run (expect the prior Friday), the day after a US market holiday (expect the session before the
  holiday), a run on a day following an early-close session (1 p.m. ET close; expect that
  session), and a run instant moved to 10:00 PT the same day (expect the same `D_G` as the 02:00
  run, since the rule uses the scheduled start).
- **Observation.** Each instant yields the expected session date; the function takes no fund
  list; the generation string is `{D_G}-{engine_version}` with `D_G` ISO-formatted.
  **Must-not-contain:** a session whose close is less than 6 hours before 02:00 PT (for example
  the same-day session for an early-morning run). Fail = any instant off.
- **Kind.** property (five calendar situations).

### A-PS-09 — tsp.gov rows are parsed only under the exact header
Phase 0 · unit
- **Claim.** The TSP provider parses the CSV only when its header is exactly the §5.5 column set
  and order, maps each fund column to its `TSP-*` id with `tr_index = price`, `div_cash = 0`,
  `split_factor = 1`, `adjusted_through = last_date`, and rejects any other header.
- **Setup.** The recorded TSP CSV slice of §10; a variant with two columns swapped; a variant with
  a renamed column; the provider's parser and `fetch_daily` wired to `responses` that also records
  the request's `User-Agent`.
- **Observation.** Exact header: 16 symbols produced with display names "G Fund", "L 2030", …;
  for a known date, `TSP-C`'s `tr_index` equals the "C Fund" cell; `div_cash` all 0,
  `split_factor` all 1; `adjusted_through == last_date`. Swapped and renamed headers: the parser
  raises a header error naming the first mismatching column and produces **no** rows. The
  recorded request carries a browser-like `User-Agent` (not `python-requests/*` or `curl/*`) and
  the `Lfunds=1&InvFunds=1&download=1` query. **Must-not-contain:** rows produced from a
  non-exact header. Fail = any leg.
- **Kind.** property (exact header plus two malformed variants; all 16 ids).

### A-PS-10 — runtime code reaches only Tiingo, tsp.gov, R2 and MailChannels, never yfinance or `qse.env`, and redacts tokens from logs
Phase 0 · static + unit
- **Claim.** No module under `portfoliosight/data/`, `portfoliosight/engine/`,
  `portfoliosight/api/`, `portfoliosight/jobs/` or `scripts/` (excluding `portfoliosight/
  frontier_cli.py` and `scripts/make_fixtures.py`) imports `yfinance`, references `qse.env`, or
  contains a URL host other than `api.tiingo.com`, `www.tsp.gov`, `*.r2.cloudflarestorage.com`
  and `api.mailchannels.net`; and no log line emitted by the Tiingo adapter contains the API key.
- **Setup.** The repository tree at HEAD; the Tiingo adapter run against `responses` with
  `TIINGO_API_KEY=ZZ-SENTINEL-KEY-ZZ` and logging captured at DEBUG, including a forced 404 and a
  forced 429 so error paths log too.
- **Observation.** (1) A grep over the scoped paths for `\byfinance\b`, `qse\.env` and
  `https?://[^\s"']+` finds no hit outside the allowed hosts; the allowed-host list is declared in
  the test and the grep must find at least one hit for `api.tiingo.com` and one for `www.tsp.gov`
  (proves the scan is reading the real code, not an empty tree). (2) The captured log text
  contains no occurrence of `ZZ-SENTINEL-KEY-ZZ` and no `Token ` followed by anything but a
  redaction marker; it **must contain** at least one line for the 404 and one for the 429 (so the
  redaction is proven on the lines that would carry the header). Fail = any forbidden hit, any
  key leak, or a missing allowed-host hit.
- **Kind.** property (every file in scope; success, 404 and 429 log paths).

### A-PS-11 — the backup refuses loudly when D: is unmounted, mirrors with `--delete`, restores without it, and the cron installer is idempotent
Phase 0 · unit (shell, fake PATH)
- **Claim.** `scripts/r2_backup.sh` exits 2 with the exact message "D: drive is not mounted at
  /mnt/d; backup not run" and calls nothing else when `mountpoint -q /mnt/d` fails; when mounted
  it runs `aws s3 sync` bucket → `/mnt/d/portfoliosight-data` with `--delete` and the R2 endpoint;
  `--restore` runs the reverse sync without `--delete`; `scripts/install_backup_cron.sh` run
  twice leaves exactly one PortfolioSight line and every other crontab line unchanged.
- **Setup.** A temp `PATH` with fake `mountpoint` (exit 1 or 0 by env), fake `aws` that records its
  argv and exits 0, fake `crontab` that stores and lists a seeded crontab with two unrelated lines
  including the existing 05:00 QSE line; a temp env file with the two R2 keys; `HOME` pointed at a
  temp dir.
- **Observation.** Unmounted: exit status 2, stdout/stderr contains the exact message, the fake
  `aws` log is empty. Mounted: one `aws s3 sync` call whose argv contains
  `--endpoint-url https://<account>.r2.cloudflarestorage.com`, source `s3://portfoliosight-data`,
  destination `/mnt/d/portfoliosight-data`, and `--delete`. `--restore`: source and destination
  swapped and **no** `--delete` in argv. Cron: after two installer runs the stored crontab has
  exactly one line containing `r2_backup.sh`, it equals the §5.3 line
  (`30 5 * * * $HOME/programming/portfoliosight/scripts/r2_backup.sh >> …`), and the two seeded
  lines are present verbatim in their original order. **Must-not-contain:** an `aws` call on the
  unmounted path; `--delete` on restore; a second PortfolioSight line. Fail = any leg.
- **Kind.** property (mounted/unmounted × backup/restore; installer run twice).

### A-PS-12 — the KS-001 cache never exceeds its cap
Phase 0 · unit
- **Claim.** After any build or nightly step the cache directory's total size is at most
  `PS_CACHE_MAX_MB`, eviction is by least-recent access, and a file needed by the current build
  is never evicted during that build.
- **Setup.** `PS_CACHE_MAX_MB=2` with synthetic parquet files of 0.6 MB each; the cache module's
  fetch-into-cache and evict entry points; access times controlled by the test.
- **Observation.** Fetch five files in order, touching the first again before the fifth: after
  eviction the directory holds ≤ 2 MB, the file evicted is the second (least recently accessed),
  and the first (recently touched) survives. During a build that declares files {3, 4, 5} as
  needed, forcing eviction never removes any of them even if they are the least recent.
  **Must-not-contain:** a directory size above the cap after `evict()`; a needed file missing
  mid-build. Fail = either.
- **Kind.** property (ordering of accesses; needed-set protection).

### A-PS-13 — the R2 store verify passes against `portfoliosight-data`
Phase 0 · live (laptop; `~/.secrets/portfoliosight.env`)
- **Claim.** `python -m portfoliosight.data.store --verify` against the real bucket performs
  `head_bucket`, put/get/delete of `meta/_probe`, and a list, and exits 0.
- **Setup.** The bucket exists (created by the build with the account token, §9.5 step 1); the two
  R2 keys in the env file are scoped to it. The same code path is also exercised against `moto`
  and `LocalStore` in A-PS-27's fixtures; this assertion is the live leg the spec assigns to
  Phase 0.
- **Observation.** Exit 0; the verify's output names the bucket and the four operations as
  passed; afterwards `meta/_probe` does **not** exist (the delete happened). On a 403 the output
  must name the missing scope (§9.5 step 1) and exit non-zero. **Must-not-contain:** a verify
  that exits 0 without having deleted the probe. Fail = non-zero exit or a lingering probe.
- **Kind.** example.

### A-PS-14 — the Tiingo adapter returns the four fields live and `measure-limits` records the tier
Phase 0 · live (laptop; `~/.secrets/portfoliosight.env`)
- **Claim.** Against the real API the adapter returns ≥ 250 rows with `close, adjClose, divCash,
  splitFactor` for VTI and for VBIAX, and `download --mode measure-limits` writes
  `meta/provider_limits.json` with `provider, tier, req_per_hour, req_per_day,
  unique_symbols_per_month, measured_on, method`.
- **Setup.** `PS_LIVE_TESTS=1`, `PS_STORE=local` with a temp `PS_LOCAL_STORE_DIR`; the real
  `TIINGO_API_KEY`.
- **Observation.** Both frames have ≥ 250 rows, all four columns non-null on every row, dates
  tz-naive and strictly increasing, VBIAX has at least one `divCash > 0` row dated 2025-12;
  the limits file exists with the seven keys, `measured_on` is today's date, `method` is
  `probe` or `documented`, and the three numeric limits are positive integers. **Must-not-
  contain:** a frame missing any of the four columns; a limits file with `tier` empty. Fail =
  any leg.
- **Kind.** example.

### Phase 1 — engine

### A-PS-15 — minimum-torsion ENB identities hold and violations raise
Phase 1 · unit
- **Claim.** `min_torsion(Σ)` returns `T` with `TΣTᵀ` diagonal, and `ENB(w)` computed from
  `b = T^{-T} w`, `Λ = diag(TΣTᵀ)`, `p_i = Λ_i b_i² / (wᵀΣw)` satisfies the §4.6 identities; the
  builder raises, never clips, when the diagonality or `Σp = 1` checks fail.
- **Setup.** (a) Diagonal Σ, N ∈ {2, 5, 23}; (b) inverse-volatility weights on diagonal Σ; (c) a
  single-fund weight vector on a random SPD Σ; (d) the two-fund case σ = (10%, 20%), ρ = 0, equal
  weights; (e) 25 random SPD matrices with N drawn from 2..30 and random long-only weights; (f) a
  deliberately perturbed `T` (one off-diagonal of `TΣTᵀ` set to `1e-6 · trace`) fed to the
  builder's ENB check.
- **Observation.** (a) `T = I` within 1e-10. (b) `ENB = N` within 1e-8. (c) `ENB = 1` within 1e-8.
  (d) `ENB = exp(−(0.2 ln 0.2 + 0.8 ln 0.8))` within 1e-3 (≈ 1.649). (e) For every matrix:
  `max|offdiag(TΣTᵀ)| ≤ 1e-8 · trace`, `|Σp − 1| ≤ 1e-8`, all `p_i ≥ 0`, `1 − 1e-6 ≤ ENB ≤ N + 1e-6`.
  (f) The check raises an exception naming the violated bound. **Must-not-contain:** an ENB
  returned from (f) (silent clipping); any `p_i < 0`. Fail = any identity off, or (f) returning.
- **Kind.** property (25 random matrices across N = 2..30, plus the four closed-form cases).

### A-PS-16 — frontier nodes sit on their ceiling and returns do not decrease
Phase 1 · unit
- **Claim.** Through the builder's public entry point, every frontier node `j` with `X_j < σ_max`
  has `σ(w_front[j]) = X_j` within 1e-6, `y_front` is non-decreasing in `j`, `X_0 = σ_min` (the
  minimum-variance portfolio under bounds) and `X_{47} = σ_max` (the max-return greedy fill),
  and `‖Cw‖² = wᵀΣw` for `C = cholesky(Σ)ᵀ`.
- **Setup.** `build_tensor` over `tests/fixtures/synthetic_23.parquet` at lookback `5y` with a
  fixed `--asof`; additionally 5 random SPD menus with N ∈ {2, 5, 12, 23, 30} and random bounds
  satisfying §4.4 validation; a random SPD matrix and 100 random `w` for the Cholesky identity.
- **Observation.** `NX = 48`; for every `j` with `X_j < σ_max − 1e-9`: `|√(w_front[j]ᵀ Σ w_front[j])
  − X_j| ≤ 1e-6`; `y_front[j+1] ≥ y_front[j] − 1e-9`; `X_0` equals the minimum-variance σ solved
  independently within 1e-6; the last node's weights equal the greedy fill within 1e-6; the
  Cholesky identity holds within 1e-12 for all 100 vectors. **Must-not-contain:** a node strictly
  inside its ceiling by more than 1e-6 while `X_j < σ_max` (the constraint must bind); any node
  with `σ > X_j + 1e-6`. Fail = any leg on any menu.
- **Kind.** property (fixture plus five random menus; every node).

### A-PS-17 — every computed mix is real: sums to one, inside bounds, under its ceiling, ENB in range; a bad vector raises
Phase 1 · unit
- **Claim.** Every weight vector the builder writes (`frontier.w[j]`, every non-null `grid.w[j][k]`,
  every `grid.w_div[j]`) satisfies `|Σw − 1| ≤ 1e-6`, `min − 1e-6 ≤ w ≤ max + 1e-6` against the
  tensor's resolved `bounds`, `σ(w) ≤ X_j + 1e-6`, `1 − 1e-6 ≤ ENB(w) ≤ N + 1e-6`; and the
  builder's post-check raises when handed a vector violating any one of them.
- **Setup.** The fixture tensor of A-PS-16; the builder's post-check function; four corrupted
  vectors each violating exactly one invariant by 1e-4.
- **Observation.** Count every vector checked (must be `48 + 48 + number of non-null cells`, with
  non-null cells ≥ 500 on the 23-fund fixture so the check is not vacuous); all four invariants
  hold for each; each corrupted vector raises with the invariant's name. **Must-not-contain:** a
  weight below `min − 1e-6` or above `max + 1e-6`; a cell whose `σ > X_j + 1e-6`; a post-check
  that returns normally on any corrupted vector. Fail = any leg.
- **Kind.** property (every vector in the tensor; each invariant's negative case).

### A-PS-18 — the surface proxy is monotone and the bottom end is at least as diversified as the top
Phase 1 · unit
- **Claim.** In the fixture tensor the optimized Herfindahl `‖w[j][k]‖²` is non-decreasing in
  ascending `Y_k` within each column and non-increasing in ascending `X_j` within each row
  (±1e-6); a cell is `null` exactly when `Y_k > y_front[j]`; `1 ≤ Z ≤ N` on every feasible cell;
  `ENB(w_div[j]) ≥ ENB(w_front[j]) − 1e-9` for every `j`; `y_div[j]` is the return floor of the
  highest-ENB candidate (ties → highest return) and `enb_ref` equals the maximum over all
  candidates in all columns.
- **Setup.** The fixture tensor plus two random menus (N = 5 and N = 12) built the same way.
- **Observation.** For every column/row the monotonicity inequalities hold; the null pattern
  equals the predicate `Y_k > y_front[j]` cell for cell (set equality over all 48 × 32 cells);
  recomputing ENB for every candidate from the tensor's moments reproduces `k_div`, `y_div`,
  `w_div` and `enb_ref` exactly (`enb_ref` within 1e-9); `k_div[j] = −1` exactly when the
  frontier mix wins. **Must-not-contain:** a feasible `null` or an infeasible non-null cell; a
  column where `ENB(w_div) < ENB(w_front)`; an `enb_ref` smaller than any `Z` or any
  `ENB(w_front[j])`. Fail = any leg on any menu. (Exact ENB is **not** asserted monotone; §4.7.)
- **Kind.** property (every cell, every column, three menus).

### A-PS-19 — the suggested point is bracketed and the standard-error walk stops at the first failure
Phase 1 · unit
- **Claim.** For every column `y_div[j] ≤ y_sug[j] ≤ y_front[j]`; on a collapsed ladder
  (`k_div[j] = −1`) `y_sug[j] = y_front[j]`; the walk uses `g_k = μ_sᵀ(w_front − w_k)` and
  `se_k = √252·sd(d) / √(T_eff/252)` with `d_t = (w_front − w_k)ᵀ r_t` (ω-weighted for `ew`), and
  stops at the first candidate with `g_k > se_k` even if a lower candidate would pass.
- **Setup.** The fixture tensor; a constructed column (synthetic returns and three candidates)
  where candidate 1 passes, candidate 2 fails and candidate 3 would pass; an `ew` window where
  `T_eff` differs from `T`.
- **Observation.** Bracketing holds for all 48 columns of the fixture; every collapsed column has
  `y_sug = y_front`; the constructed column yields `y_sug` = candidate 1's floor (not 3's);
  recomputing `g_k` and `se_k` independently for the fixture's chosen candidate and its successor
  shows `g ≤ se` for the chosen and `g > se` for the successor (or the successor is `k_div`); in
  the `ew` case the `se` uses `T_eff` (changing `T_eff` changes the stop). **Must-not-contain:**
  a `y_sug` below `y_div` or above `y_front`; a walk that skips a failing candidate. Fail = any.
- **Kind.** property (all columns of the fixture; the constructed stop case; `ew`).

### A-PS-20 — moments are estimated as specified
Phase 1 · unit
- **Claim.** Fixed windows use `μ_i = 252·mean`, `σ_i = √252·sd(ddof=1)`, LedoitWolf on
  standardized returns renormalized to a correlation matrix and rescaled with annual variances;
  `ew` uses half-life 252 weights, the weighted sample correction, and `R_s = 0.8R + 0.2I`; the
  diagonal floor `σ_i ≥ 1e-4` applies before factorization in both paths; the menu-beta blend is
  `μ_s = 0.5μ̂ + 0.5π` with `π_i = r_f + β_i·max(μ̂_eq − r_f, 0)`; `r_f` is SGOV's trailing-12-month
  total return if served, else TSP-G's, else 0.04.
- **Setup.** A synthetic return matrix with one near-constant column (σ ≈ 0.3%/yr, a G-Fund
  stand-in) and one exactly constant column; the same matrix under `ew` with uniform weights
  forced (`ω_t = 1/T`); two menus with positive and with non-positive `μ̂_eq − r_f`; three
  served-symbol sets (with SGOV; without SGOV but with TSP-G; neither).
- **Observation.** (1) `ew` with uniform weights reproduces the fixed-window `σ_i` within 1e-12 for
  every `i`. (2) The constant column's `σ_i` equals exactly 1e-4 after the floor and the near-
  constant column keeps its own variance (within 1e-12 of `√252·sd`) rather than being pulled
  toward the menu's average variance (the correlation-space shrinkage choice). (3) `R` has unit
  diagonal (±1e-12) and `Σ_ii = σ_i²` (±1e-12). (4) Positive-premium menu:
  `w_eqᵀπ = w_eqᵀμ̂` within 1e-12; non-positive menu: every `π_i = r_f` and
  `μ_s = 0.5μ̂ + 0.5r_f`. (5) `r_f` equals SGOV's TR over the trailing 252 rows when SGOV is
  served, TSP-G's otherwise, 0.04 when neither. **Must-not-contain:** a `σ_i` below 1e-4
  anywhere; a `π_i ≠ r_f` in the non-positive case. Fail = any leg.
- **Kind.** property (both paths; both premium signs; three `r_f` sources).

### A-PS-21 — caps scale with the menu and are validated; no 23-fund mix exceeds 25%
Phase 1 · unit
- **Claim.** The default bound is `max = clamp(3/N, 0.25, 1.0)`, `min = 0`, with N the funds
  included in the window; validation rejects `min > max`, any bound outside `[0, 1]`,
  `Σmin > 1`, `Σmax < 1`, and `N < 2`; the greedy endpoint fill allocates every minimum first;
  and on the 23-fund fixture no computed weight exceeds 0.25 + 1e-6.
- **Setup.** The caps module; the fixture tensor; a 4-fund menu with `min = (0.3, 0.3, 0, 0)` and
  `max = (0.3, 0.3, 0.4, 0.4)`; the five invalid inputs.
- **Observation.** `max(N)` for N = 2..30 equals the closed form (spot values: N = 2, 3 → 1.0;
  5 → 0.6; 10 → 0.3; 12 → 0.25; 23 → 0.25; 30 → 0.25); each invalid input raises the validation
  error that the API maps to 422, with a message naming the fund or the sum; the greedy fill on
  the 4-fund menu gives exactly 0.3, 0.3 to the first two before any remainder is placed; every
  weight in the fixture tensor (same set as A-PS-17) is ≤ 0.25 + 1e-6; the tensor's
  `bounds.rule` string is `"max(0.25, 3/N)"` and `bounds.requested` holds `null` for defaults
  while `bounds.min/max` hold the resolved numbers. **Must-not-contain:** a resolved `max`
  below 0.25 or above 1.0; a valid-looking result from any invalid input. Fail = any leg.
- **Kind.** property (N = 2..30; five invalid inputs; every fixture weight).

### A-PS-22 — window inclusion, the 126-row floor and the fixed exclusion templates
Phase 1 · unit
- **Claim.** A fund is included in a window only if it is served and its first return date is on
  or before `window_start + 0.10 · window_length`; a window whose intersection sample has fewer
  than 126 rows is `unavailable`; every excluded fund appears in the tensor's `excluded` array
  with a reason that is exactly one of the five §5.6 templates; a current mix with weight in
  excluded funds is renormalized and the set-aside share is reported.
- **Setup.** The fixture returns with three modified funds: one whose history starts at
  `window_start + 0.09·len` (include), one at `+0.11·len` (exclude), one marked not served with
  `adjusted_through` behind `D_G`; a second window where only 100 shared rows exist; an
  allocation giving 20% to the excluded fund.
- **Observation.** The `+0.09` fund is in `universe.funds`, the `+0.11` fund is in `excluded` with
  reason `"{ID}: history starts {date}, not enough for the {window} view"` filled exactly, the
  unserved fund with `"corporate actions not yet verified after {date}"`; the 100-row window
  builds no tensor and reports `unavailable` with "not enough shared history"; the renormalized
  allocation sums to 1 over included funds and the reported set-aside share is 0.20 (±1e-12).
  **Must-not-contain:** a reason string outside the template set (regex over the five
  templates); an excluded fund in any weight vector; a window with < 126 rows marked ready.
  Fail = any leg.
- **Kind.** property (both sides of the inclusion boundary; the row floor; the renormalization).

### A-PS-23 — stress returns are never fabricated
Phase 1 · unit
- **Claim.** For each of `gfc2008`, `covid2020`, `rates2022` with the exact §4.10 dates, the
  tensor's per-fund `r` is the buy-and-hold total return from the last price on or before the
  start to the last price on or before the end, and is `null` whenever the fund lacks a price
  within 3 trading days of either endpoint.
- **Setup.** Synthetic records: one fund with full history, one starting 2010-01-04 (no 2008
  data), one with a 10-day gap covering 2020-02-19, one whose last price is 2022-10-07 (within
  3 trading days of 2022-10-12) and one ending 2022-09-30 (outside).
- **Observation.** Full-history fund: `r` equals `tr_index[end]/tr_index[start] − 1` within
  1e-12 for all three windows; the 2010 fund has `null` for `gfc2008` and numbers for the other
  two; the gap fund has `null` for `covid2020`; the 2022-10-07 fund has a number for
  `rates2022`, the 2022-09-30 fund has `null`; window `start`, `end`, `label` strings equal §4.10
  exactly. **Must-not-contain:** a non-null `r` for any fund lacking an endpoint price; a value
  computed from a neighbouring date more than 3 trading days away. Fail = any leg.
- **Kind.** property (three windows × five coverage situations).

### A-PS-24 — a tensor is deterministic, schema-valid, full-precision, carries a correct `frontier_curve` and `s_safe`, builds in ≤ 90 s, and the UI fixture is its unedited output
Phase 1 · unit
- **Claim.** Building the 23-fund fixture twice from the same inputs yields identical canonical
  JSON after removing `built_at` and `build_seconds`; the output validates against
  `portfoliosight/engine/tensor.schema.json`; floats round-trip exactly; `frontier_curve` equals
  the actual `(σ, μ)` of `w_front(s)` at 8 sub-steps per gap (377 points) within 1e-9 relative;
  `frontier.s_safe` is the rightmost maximum of `Low_front` over that curve; the build takes
  ≤ 90 s; and `web/fixtures/guide2017_5y.json` equals a fresh build from
  `tests/fixtures/synthetic_23.parquet` with the recorded `--asof` (minus telemetry fields).
- **Setup.** `scripts/build_tensor.py` with `--asof` fixed; `tests/fixtures/synthetic_23.parquet`
  as produced by `scripts/make_fixtures.py` with its seed; the JSON Schema; `jsonschema`.
- **Observation.** (1) Two builds' canonical dumps are byte-equal after dropping the two
  telemetry fields. (2) Schema validation passes, and a copy with `grid.z` removed **fails**
  validation (proves the schema is not permissive). (3) For 50 sampled floats,
  `json.loads(json.dumps(x)) == x` and the file's text for `mu_s[0]` equals `repr(mu_s[0])`.
  (4) Recomputing the locus from `frontier.w` and the moments reproduces `frontier_curve.sigma`
  and `.mu` within 1e-9 relative at all 377 points. (5) `s_safe` equals the index of the last
  (rightmost) maximum of `μ/2 − 1.96·σ/√2` over the curve, expressed in `s` units. (6) Wall
  time ≤ 90 s. (7) `make_fixtures.py` re-run with its seed reproduces `synthetic_23.parquet`
  byte-for-byte, and the UI fixture equals the fresh build. **Must-not-contain:** a second
  build that differs; a float printed with fewer digits than `repr`. Fail = any leg.
- **Kind.** contract (build pre/postconditions) with property legs (every curve point; sampled
  floats).

### A-PS-25 — the engine is pure and fully covered
Phase 1 · static + unit
- **Claim.** `pytest --cov=portfoliosight/engine` reports 100% line coverage for every module
  under `portfoliosight/engine/`, and no module there imports `requests`, `boto3`, `urllib`,
  `socket`, `pathlib`/`open` for I/O, or anything from `portfoliosight.data`.
- **Setup.** The repository at HEAD; the engine test suite.
- **Observation.** Parse the coverage report: every `portfoliosight/engine/*.py` row shows
  `100%` and the `Missing` column is empty; the report lists at least six engine modules (stats,
  torsion, optimize, surface, suggest, stress, caps, builder — proves the package is real). AST
  scan of each engine module: no `import`/`from` of the forbidden names; no `open(` call.
  **Must-not-contain:** a module below 100%; an I/O import. Fail = either.
- **Kind.** property (every engine module).

### Phase 2 — API, nightly, container

### A-PS-26 — every `/v1/*` request without the gate secret is refused, in constant time
Phase 2 · api
- **Claim.** Every route under `/v1/` returns `403` with the error envelope
  `{"error": {"code": "forbidden", ...}}` when `x-ps-gate` is absent or wrong, serves normally
  when it equals `PS_GATE_SECRET`, and the comparison is `hmac.compare_digest`.
- **Setup.** `TestClient` with `PS_GATE_SECRET` set; `LocalStore` seeded with a published
  generation; `hmac.compare_digest` wrapped by the test to count calls.
- **Observation.** For each of the five §6 routes (`GET /v1/health`, `GET /v1/presets`,
  `GET /v1/symbols`, `POST /v1/tensors`, `GET /v1/tensors/{G}/{hash}/{lookback}`): no header →
  403 envelope; wrong value → 403 envelope; right value → the route's normal status. The
  compare-digest counter increased by at least one per request. **Must-not-contain:** a 2xx on
  any route without the header; a response body for the 403 that includes the expected secret or
  the request's value; a plain `==` path (the counter must be non-zero on every request).
  Fail = any route, any leg.
- **Kind.** property (every route × absent/wrong/right).

### A-PS-27 — a custom build runs to `ready`, is deduplicated, retries a failure at most three times, and never overwrites a key
Phase 2 · api
- **Claim.** `POST /v1/tensors` for a new key returns 202 `queued` with a position, polling
  `GET /v1/tensors/{G}/{hash}/{lookback}` returns 202 then 200 with the tensor, `ETag` and
  `Cache-Control: public, max-age=86400, immutable`; a second POST for the same key returns its
  state without a second job; a job that raises yields 409 `failed` with `attempts`, is
  re-enqueued by a later POST up to 3 attempts, and the third failure returns `retry: false`;
  a tensor key once written is never overwritten; URLs in responses are public `/api/…` paths.
- **Setup.** `TestClient` with the gate header; `LocalStore` with a small fixture store (the
  three-symbol fixture lake converted to canonical records plus a published generation);
  the build worker thread running; a fault injector that makes the builder raise for one
  specific key; a monkeypatched store that records every `put` call.
- **Observation.** (1) First POST: 202, `status` ∈ {queued, building}, `position` int,
  `generation` = current G, `hash` 16 hex; polling reaches 200 within the test timeout; the 200
  carries `ETag` and the immutable `Cache-Control`; `url` matches `^/api/tensors/`. (2) Second
  identical POST while building: 202 with the same `hash`; the job table has exactly one entry
  for the key. After ready: POST returns 200 with the same `url`. (3) Faulty key: 409
  `{"status":"failed","attempts":1,"retry":true}`; two more POSTs → attempts 2, 3; the third
  carries `retry: false`, and a fourth POST does **not** enqueue (job count unchanged). (4) The
  store's `put` log shows exactly one write for the ready key; a forced second build attempt for
  that key performs **no** `put` and the served body is byte-identical to the first. (5) A GET
  for a never-requested hash in G returns 404 `unknown_tensor`. **Must-not-contain:** two jobs
  for one key; a second `put` on an existing key; a `url` starting with `/v1/`. Fail = any leg.
- **Kind.** contract (queue pre/postconditions) with property legs (dedupe, attempts).

### A-PS-28 — bad requests are refused with the specified codes and nothing is enqueued
Phase 2 · api
- **Claim.** `POST /v1/tensors` returns 400 `unknown_symbols` listing every unknown id; 422
  `invalid_request` for duplicates, more than 30 funds, fewer than 2, a bad lookback, or a cap
  policy failing §4.4; 429 for the 6th POST from one IP within a minute and for the 61st `/v1/*`
  request within a minute; 503 `busy` when 20 jobs are queued; 413 (or 422) for a body over
  16 KB; and in every refused case the job table is unchanged.
- **Setup.** As A-PS-27, with the worker thread **paused** so queued jobs accumulate; requests
  carrying distinct `CF-Connecting-IP` values; a fake clock for the limiter.
- **Observation.** Each listed input yields the listed status and `error.code`; the 400 body's
  `details.symbols` equals exactly the set of unknown ids sent (two unknowns → both named);
  the 422 for caps names the offending fund or sum; the per-IP POST limiter admits 5 and refuses
  the 6th, while a different IP is admitted; 20 queued jobs → the 21st POST is 503 and the
  queue depth in `/v1/health` reads 20; a 17 KB body is refused before parsing. Job table size
  before == after for every refused request. **Must-not-contain:** a 202 for any invalid input;
  a 429 keyed on anything but `CF-Connecting-IP` (two IPs must be independent). Fail = any.
- **Kind.** property (every refusal class; two IPs).

### A-PS-29 — the universe hash is canonical
Phase 2 · unit
- **Claim.** The hash is `sha256(canonical_json({"schema": 2, "funds": [{"id","min","max"} sorted
  by id]}))[:16]` over the requested policy with `null` for defaults, so it is independent of
  input order and of the lookback, and changes with any cap override.
- **Setup.** The hash function; menus differing only in fund order; the same menu with
  `lookback` 1y vs 5y; the same menu with one `max` set to 0.10; the §7 example (`guide2017`
  funds, all defaults).
- **Observation.** Permuted menus hash equal; lookbacks hash equal; the cap override hashes
  differ; the function's output is 16 lowercase hex; the canonical JSON fed to sha256 (captured)
  has sorted keys, no whitespace, `null` (not `0`/`1`) for defaults, and `"schema":2`.
  **Must-not-contain:** a hash that varies with order or lookback; a hash equal across a cap
  change. Fail = any.
- **Kind.** property (order, lookback, override).

### A-PS-30 — a generation is published only when complete, and never half-visible
Phase 2 · api/unit
- **Claim.** The nightly writes `meta/{G}/generation.json` once, builds each missing preset
  tensor with `D_G` passed in, switches `meta/current.json` only after all 12 keys exist,
  resumes an interrupted run without rewriting anything under `meta/{G}/`, skips to the
  post-publication steps when `current.json` already points at G, deletes generations older
  than the previous one, and marks TSP `stale` (not failed) when the tsp.gov fetch breaks.
- **Setup.** `LocalStore` with canonical records for the 23 + 5 preset funds (synthetic) and a
  fake clock fixing `D_G`; the nightly entry point; a fault injector that aborts after the 5th
  preset tensor; a store wrapper recording every `put`; a fake TSP provider that raises.
- **Observation.** (1) Interrupted run: `current.json` still points at the previous G (or is
  absent on a first run); `meta/{G}/generation.json` exists; 5 tensor keys exist; no
  `presets.json`. (2) Rerun: 7 more tensors built, `presets.json` written once, `current.json`
  switched to G; the `put` log shows `generation.json` written exactly once across both runs
  and `presets.json` once. (3) Every tensor's `asof` equals the generation's `asof` and no price
  row after `D_G` influenced it (a record with an extra row dated `D_G + 1` that would change
  `mu_sample` yields the same tensor as without it). (4) A third run with `current.json`
  already at G performs zero builds. (5) With three generations present, the oldest is deleted
  and the previous kept. (6) TSP fetch failure: the run finishes, TSP symbols are `stale`,
  `meta/status.json` records the error, and `current.json` is still switched when the 12 keys
  exist. **Must-not-contain:** a `current.json` switch before the 12th key; any rewrite of a
  `meta/{G}/` key; a tensor with `asof ≠ D_G`. Fail = any leg.
- **Kind.** property (interrupt/resume/skip/prune/TSP-failure paths).

### A-PS-31 — presets and health bodies match `data/presets.json` and the holdings CSV
Phase 2 · api
- **Claim.** `GET /v1/presets` returns the two presets of `data/presets.json` with the §6 shape,
  where `guide2017.allocation` is `Qty × Price` per symbol from
  `data/holdings/holdings_guide2017_step2.csv` in `"$"` with 18 non-zero of 23 entries and
  `tsp.allocation` is `null`; `GET /v1/health` returns the §6 fields.
- **Setup.** `TestClient`, `LocalStore` with a published generation whose 12 tensors exist
  (A-PS-30's result); the CSV read independently by the test.
- **Observation.** `presets[0].id == "guide2017"`, name `"Example Portfolio"`, 23 fund ids
  equal to the CSV's symbols, `allocation_unit == "$"`, `allocation[s] == round(Qty × Price, 2)`
  for every held symbol (18 non-zero, 5 zero), six `lookbacks` each `{"status":"ready",
  "url":"/api/tensors/{G}/{hash}/{id}"}`; `presets[1].id == "tsp"`, name `"TSP (G, F, C, S, I)"`,
  funds exactly `TSP-G, TSP-F, TSP-C, TSP-S, TSP-I`, `allocation: null`; `Cache-Control:
  public, max-age=300`. `/v1/health`: `status`, `version`, `generation`, `asof` (ISO date),
  `asof_trading_days_behind` (int ≥ 0), `queue.depth`, `queue.building`, `nightly`; `Cache-
  Control: no-store`. **Must-not-contain:** an allocation value for TSP; a lookback `url`
  under `/v1/`; a preset not in `data/presets.json`. Fail = any leg.
- **Kind.** contract.

### A-PS-32 — the image, the repository and the compose file hold no holdings, no secrets, no data mount, and cap resources
Phase 2 · static (image build when `docker` is available, else the ignore-rule unit test the spec allows)
- **Claim.** The built image contains no `runs/`, no `data/holdings/*` other than
  `holdings_guide2017_step2.csv`, no `.venv`, `web/node_modules` or `web/dist`; neither the
  image nor any git-tracked file contains any secret value from `~/.secrets/portfoliosight.env`
  or the string `qse.env`; `deploy/docker-compose.yml` mounts only the named volume `ps-cache`
  at `/app/cache`, publishes only `127.0.0.1:8010:8000`, sets `cpus: "2"`, `memory: 1536M`,
  `PS_CACHE_MAX_MB=300`, `PS_STORE=r2`; and the image runs as uid 10001.
- **Setup.** The repository at HEAD; `docker build -f deploy/Dockerfile .` when available; the
  env file's values read by the test (never printed); a planted file `data/holdings/
  personal_test.csv` and a planted `runs/x` in a temp copy of the tree for the ignore-rule leg.
- **Observation.** Image (or ignore-rule) leg: listing the image filesystem (`docker run --rm
  <img> find /app`) shows the Step 2 CSV and **no** other path under `data/holdings/`, no
  `runs/`, no `.venv`, no `node_modules`, no `dist`; `id -u` inside the container prints 10001;
  the planted files are excluded. Repo leg: `git ls-files` contains no `data/holdings/` path
  other than the CSV and no `runs/` path; a grep of every tracked file and of the image's
  `/app` for each secret value finds nothing (the test must confirm the env file has ≥ 5
  non-empty values so the scan is not vacuous). Compose leg: parsed YAML shows exactly one
  volume mapping for `api` (`ps-cache:/app/cache`), no `bind` sources, the port, the limits and
  reservations, `env_file` pointing at `~/.secrets/portfoliosight.env`, `restart:
  unless-stopped`, and the `nightly` service under `profiles: ["jobs"]` with no ports. **Must-
  not-contain:** any secret value; any bind mount; a second published port. Fail = any leg.
- **Kind.** property (every tracked file; every image path; every compose service).

### A-PS-33 — the API surface is exactly the §6 table
Phase 2 · api
- **Claim.** The FastAPI application's routes under `/v1/` are exactly `GET /v1/health`,
  `GET /v1/presets`, `GET /v1/symbols`, `POST /v1/tensors`, `GET /v1/tensors/{G}/{hash}/{lookback}`,
  with the path constraints `G = \d{4}-\d{2}-\d{2}-[0-9.]+` and `hash = [0-9a-f]{16}` enforced,
  and the application registers no other route whose path contains `login`, `auth`, `account`,
  `signup`, `pay` or `checkout`.
- **Setup.** The app object; `TestClient` with the gate header.
- **Observation.** `{(m, r.path) for r in app.routes for m in r.methods}` filtered to `/v1/`
  equals exactly the five-element set; a GET to `/v1/tensors/2026-10-12-0.1.0/zz/5y` (bad hash)
  and `/v1/tensors/bad/0123456789abcdef/5y` (bad G) return 4xx without touching the store (store
  `get` counter unchanged); no route path matches the forbidden tokens (case-insensitive).
  **Must-not-contain:** any sixth `/v1/` route; a store read on a malformed key. Fail = any.
- **Kind.** contract.

### Phase 3 — front end

### A-PS-34 — browser math reproduces the tensor and interpolation keeps every invariant
Phase 3 · unit (vitest)
- **Claim.** `stats(w)` in `web/src/math/portfolio.ts` equals the tensor's own values at every
  grid node and frontier node within 1e-9 relative; `interpolate(s, t)` satisfies the §4.11
  invariants for 200 random `(s, t)`; `t = 0` reproduces `w_front(s)` and `t = 1` the
  interpolated most-diversified mix; a pair of collapsed ladders is constant in `t`; the
  recomputed `frontier_curve` and `riskSliderDomain().s_safe` equal the tensor's.
- **Setup.** `web/fixtures/guide2017_5y.json` loaded through the `zod` loader; a seeded PRNG for
  the 200 positions; a synthetic mini-tensor with two adjacent collapsed columns.
- **Observation.** For every `j` and every non-null `(j, k)`: `stats(w).mu`, `.sigma`, `.enb` match
  `frontier.y[j]`/`X_j`/`Z[j][k]` (and the frontier mix's ENB recomputed in Python) within 1e-9
  relative; for the 200 positions: `|Σw − 1| ≤ 1e-6`, bounds ±1e-6, `σ(w) ≤ X(s) + 1e-6`,
  `1 − 1e-6 ≤ ENB ≤ N + 1e-6`; `interpolate(s, 0)` equals `(1−λ)w_front[j] + λw_front[j+1]`
  exactly; `interpolate(s, 1)` equals the same combination of `w_div`; the collapsed pair gives
  identical vectors for `t ∈ {0, 0.3, 1}`; the recomputed curve matches all 377 points within
  1e-9; `s_safe` matches. `range6m` on `(μ, σ)` yields `μ/2 ∓ 1.96σ/√2`. **Must-not-contain:**
  a `null` cell entering any ladder (assert ladders are built only from non-null cells); any
  renormalization (`Σw` must equal exactly the convex combination, not a rescaled value).
  Fail = any leg.
- **Kind.** property (every node; 200 random positions; collapsed case).

### A-PS-35 — amounts become weights in all three units, the 100% rule gates, and trades are computed per unit
Phase 3 · unit (vitest)
- **Claim.** `web/src/math/amounts.ts` converts shares (`w ∝ shares × last_close`), percent and
  dollars to weights that sum to 1; percent input is accepted only when the total is within
  100 ± 0.05; tickers-only yields no allocation; trade deltas per fund are `Δpp = w_sel − w_now`,
  `Δ$ = Δpp · V`, `Δshares = round((w_sel − w_now) · V / last_close)` with `V = Σ shares ·
  last_close`; one-way turnover is `Σ max(Δpp, 0)`.
- **Setup.** The fixture tensor's `universe.funds[].last_close`; generated amount vectors in each
  unit; totals 99.9, 99.96, 100.0, 100.04, 100.1; a fund with `last_close: null`.
- **Observation.** Weights sum to 1 (±1e-12) for 100 random vectors per unit; shares weights
  equal `shares·last_close / Σ` fund by fund; 99.9 and 100.1 are rejected and 99.96, 100.0,
  100.04 accepted, with the running-total message reading the actual total (e.g. "Adds up to
  92%: 8% to go" for 92); all-blank amounts produce `allocation = null`; for a random selected
  mix the deltas match the formulas within 1e-9 and `Σ Δshares · last_close` is within one
  share's price of `Σ Δ$`; a `null` `last_close` fund yields no share conversion and an explicit
  "unknown price" state rather than a number. **Must-not-contain:** an accepted total outside
  the band; a weight vector not summing to 1; a share delta computed with a `null` price.
  Fail = any.
- **Kind.** property (three units × 100 vectors; five totals).

### A-PS-36 — the URL codec round-trips every state
Phase 3 · unit (vitest)
- **Claim.** `decode(encode(state)) == state` for every reachable state of `web/src/state/url.ts`
  (preset or custom funds with optional amounts, `unit` including `shares`, cap overrides,
  lookback, ghosts, `r` decimal, `d` auto or decimal, theme, details), unknown keys are ignored,
  `r` is clamped into the domain on load, and `encode` emits only the §8.1 keys.
- **Setup.** A generator over the state space (≥ 500 cases) with fund ids drawn from the fixture
  universe; a URL with an unknown key `zz=1` and a `k=` key; an `r` outside `[s_safe, NX−1]`.
- **Observation.** Round-trip equality for all cases; the key set of every encoded URL ⊆
  `{u, f, unit, c, lb, g, r, d, t, x}`; `?u=guide2017&lb=5y&r=19.25&d=auto&t=hud` decodes to the
  obvious state and re-encodes to the same string; `zz` and `k` are dropped and do not appear
  in re-encoded output; out-of-domain `r` decodes to the clamped value. **Must-not-contain:**
  any non-§8.1 key in `encode` output; a `k` value surviving a re-encode. Fail = any.
- **Kind.** property (≥ 500 generated states).

### A-PS-37 — the client never waits on the server during a drag, recovers from an expired challenge by reloading, and stops after three failed builds
Phase 3 · unit (vitest, mocked `fetch`, reducer)
- **Claim.** Slider actions dispatch no network request; a `202` response is polled every 2 s
  until `200`; a `409 failed` puts the store in `build-retry` state and a Retry re-POSTs the
  identical body; after three `409`s the store shows the "three failures" state, offers the
  presets and stops polling; a response carrying `cf-mitigated: challenge` makes the client write
  the current state to the URL (`replaceState`) and perform a top-level reload, with no retry
  loop; on load the client resumes the same build key.
- **Setup.** The reducer and `api/client.ts` with `fetch`, `history.replaceState` and
  `location.reload` mocked; fake timers.
- **Observation.** (1) 50 `riskSlider`/`divSlider` actions: `fetch` call count unchanged.
  (2) 202 → 202 → 200 sequence: exactly three polls at 0, 2, 4 s; state ends `ready`. (3) 409:
  state `build-retry` with the server's error code; Retry sends a body byte-equal to the first.
  (4) Three 409s: state `build-failed-final`, polling timer cleared, no fourth POST on a further
  Retry. (5) Challenge header on any `/api/*` response: `replaceState` called once with a URL
  that decodes to the current state, `reload` called once, `fetch` not called again before
  reload; after a simulated reload with that URL the client POSTs the same `(G, hash, lookback)`.
  **Must-not-contain:** a fetch during a drag; a fourth attempt; a retry without reload on the
  challenge path. Fail = any.
- **Kind.** property (50 slider actions; the three server paths).

### A-PS-38 — share validators, the fixed template and the caps
Phase 3 · unit (vitest over `web/worker/share.ts`)
- **Claim.** `POST /api/share` accepts only `{"to", "url"}` JSON ≤ 2 KB with `Origin:
  https://portfoliosight.ai`, one bare RFC 5322 addr-spec ≤ 254 chars, and a `url` that parses to
  `https://portfoliosight.ai/` with only §8.1 keys and ≤ 2,048 chars; the MailChannels request
  carries the **re-encoded** URL, `from.email = SHARE_FROM`, `name = "PortfolioSight"`, the fixed
  subject and body, `Reply-To = SHARE_REPLY_TO`, the DKIM fields; the `ShareLimiter` logic refuses
  the 2nd per IP per minute, the 4th per IP per day and the 51st global per day; with
  `MAILCHANNELS_API_KEY = "test"` nothing is sent; and the dialog shows the preview notice while
  preview is on.
- **Setup.** The handler with a mocked `fetch` capturing the MailChannels request; a pure counts
  record for the limiter; inputs: valid; display-name recipient `"Jeff <a@b.c>"`; two addresses;
  255-char address; `url` on `https://example.com/`; `url` with a `javascript:` scheme; `url` with
  an extra key `zz=1`; `url` with `k=…`; a 3 KB body; a non-JSON body; a request with a foreign
  `Origin`; the React dialog rendered with the client's preview flag on and off.
- **Observation.** Valid → 202 `{"ok": true}` and exactly one MailChannels call whose JSON has
  `personalizations[0].to[0].email` equal to the input, `from.email == SHARE_FROM`, subject
  `"Someone shared a PortfolioSight view with you"`, text body consisting of the one fixed line,
  the re-encoded link and the disclaimer line, `dkim_domain`, `dkim_selector`, `dkim_private_key`
  present, and the link equal to `encode(decode(url))` with `zz` and `k` absent. Each invalid
  input → the §9.3 code (400 `invalid_recipient`/`invalid_url`, 413, 415, 403 or 400 for the
  foreign origin) and **zero** MailChannels calls. Limiter: sequences crossing each cap return
  429 exactly at the cap, two IPs independent, the global cap shared. `"test"` key: 202, zero
  outbound calls, one log line. Dialog: preview on → a notice that recipients cannot open the
  link until preview is off; preview off → notice absent. **Must-not-contain:** the raw
  submitted `url` string in the message when it differs from the re-encoded one; any visitor-
  supplied text outside the `to` address and the link; a send on any invalid input. Fail = any.
- **Kind.** property (every invalid class; three caps; both preview states).

### A-PS-39 — the private-preview gate
Phase 3 · unit (vitest over `web/worker/index.ts` with mocked bindings)
- **Claim.** With `PS_PRIVATE_PREVIEW = "1"`: a request with neither the `x-ps-gate` header nor a
  valid `ps_preview` cookie receives `403` and the static preview page for every path, including
  `/api/*`, with no data; the header equal to the secret passes through; `GET /?k=<secret>`
  responds `302` to the same URL without `k`, setting `ps_preview` with `HttpOnly; Secure;
  SameSite=Lax; Max-Age=2592000`; a wrong `k` or wrong header gets `403` with no cookie; a valid
  cookie passes; the comparison uses a constant-time primitive; the secret appears in no response
  header, body or log line. With `PS_PRIVATE_PREVIEW = "0"` every request passes through.
- **Setup.** Mocked `env` (`PS_GATE_SECRET = "ZZ-SENTINEL-ZZ"`, `DATA` with `meta/current.json`
  and a presets body, `ASSETS` returning a marker page, `API_ORIGIN` fetch mocked); the Worker's
  timing-safe compare wrapped by a counter; console captured.
- **Observation.** Preview on: `/`, `/?u=tsp`, `/api/presets`, `/api/tensors/…`, `/assets/x.js`
  without key → 403, body contains "private preview", `content-type: text/html`, **no**
  `x-ps-source` header, no presets JSON, `ASSETS`/`DATA`/origin fetch not called;
  `/?k=ZZ-SENTINEL-ZZ&u=tsp` → 302, `Location` is `/?u=tsp`, `Set-Cookie` has the four
  attributes and a name `ps_preview`; the cookie's value is **not** the secret and the response
  contains no `ZZ-SENTINEL-ZZ` anywhere; `/?k=wrong` → 403, no `Set-Cookie`; a request with the
  issued cookie → the marker page; with the header → the marker page and `/api/presets` returns
  the presets JSON with `x-ps-source: r2`; the compare counter > 0 on every keyed request. Preview
  off: `/` without anything → the marker page; `/api/presets` → the JSON. Captured console output
  never contains the secret. **Must-not-contain:** data on any keyless path while preview is on;
  the secret in any header, body or log; a cookie issued for a wrong key. Fail = any.
- **Kind.** property (five paths × four credentials × two modes).

### A-PS-40 — the Worker's routing surface is exactly §9.3
Phase 3 · unit (vitest with mocked bindings; requests carry the gate header)
- **Claim.** Host `www.portfoliosight.ai` → 301 to the same path and query on the apex; any other
  host → 404; `GET /api/presets` → `meta/current.json` then `meta/{G}/presets.json` from R2 with
  `Cache-Control: public, max-age=300` and `x-ps-source: r2`; `GET /api/symbols` → `meta/
  symbols.json` likewise; `GET /api/tensors/{G}/{hash}/{lookback}` validates the three segments,
  serves an R2 hit with `public, max-age=86400, immutable`, the object's etag and `x-ps-source:
  r2`, and on a miss forwards to `API_ORIGIN + "/v1/…"`; `POST /api/tensors` and `GET /api/health`
  forward with `x-ps-gate`, `content-type`, `accept` and `CF-Connecting-IP` and return the upstream
  `Cache-Control` with `x-ps-source: origin`; `POST /api/share` is handled in the Worker; every
  other path goes to `ASSETS`; no other `/api/` path exists.
- **Setup.** Mocked `env` as in A-PS-39 with `PS_PRIVATE_PREVIEW = "0"`; recorded `fetch` for the
  origin; `DATA.get` recorded.
- **Observation.** Each listed route yields the listed status, headers and binding calls (exact
  `DATA` keys read; exact origin URL and the four forwarded headers); a `/api/tensors/x/y/z` with
  malformed segments returns 4xx with **no** `DATA.get` and no origin fetch; `/api/anything-else`
  and `/api/login` return 404 (not forwarded, not assets); `/` and `/some/deep/link` call
  `ASSETS.fetch`; the www redirect preserves `?u=tsp&lb=5y`. **Must-not-contain:** an origin
  fetch without `x-ps-gate`; a forwarded request for a path outside the three forwarded ones; a
  `DATA` read on a malformed key. Fail = any.
- **Kind.** contract.

### A-PS-41 — the first screen is the chart and its controls; sections are collapsed; no tangency marker
Phase 3 · ui (desktop 1366×900; all four themes)
- **Claim.** On load with the fixture preset, the first viewport contains `chart-canvas`,
  `risk-slider`, `div-slider`, the result strip (`range-low`, `range-typical`, `range-high`,
  `div-word`) and the four chips, no `<table>`, no trade row and no stress card is visible, all
  four sections have `aria-expanded="false"`, each chip expands its matching section, and the
  SVG overlay's markers are exactly `point-selected`, `point-div` and `point-current`.
- **Setup.** `vite preview` with the static `/api/*` mock serving the fixture as `guide2017`'s 5y
  tensor and the presets body with its allocation; theme set via `?t=`.
- **Observation.** For each theme: every named test id is within the viewport
  (`getBoundingClientRect` inside 0..900 px) without scrolling; `document.querySelectorAll
  ("table, [data-testid^=fund-row-], [data-testid^=stress-]")` has no element whose rect
  intersects the viewport and is visible; the four `section-*` elements carry
  `aria-expanded="false"`; clicking `chip-stress` makes `section-stress` `aria-expanded="true"`
  and scrolls it into view; the overlay contains exactly three marker elements (`[data-testid^=
  point-]`), no element whose text or `aria-label` matches `/sharpe|tangency|capital market/i`,
  and no line element other than `ceiling-line`, the axes and the frontier. **Must-not-
  contain:** a fourth marker; a visible table in the first viewport; a section expanded on
  load. Fail = any theme, any leg.
- **Kind.** property (four themes).

### A-PS-42 — the phone layout fits and works with a thumb
Phase 3 · ui ("iPhone 13" device profile; all four themes)
- **Claim.** `document.documentElement.scrollWidth ≤ window.innerWidth`; the chart, both sliders,
  the result strip and the chip row are within the first 1.2 viewport heights; every interactive
  element's hit area is ≥ 44 × 44 px; the diversification slider is horizontal (width > height)
  with "More return" at the left and "More diversified" at the right; the header is 48 px; and a
  touch drag on `point-selected` changes the risk position.
- **Setup.** As A-PS-41 on the phone project.
- **Observation.** Scroll-width inequality holds after load and after opening each section; the
  bottom of `chip-*` row ≤ 1.2 × `innerHeight`; for every element matching
  `button, [role=slider], a, input, [data-testid=point-selected]` the hit rect (element or its
  declared hit area) is ≥ 44 px on both axes; `div-slider` rect has width > height and its two
  labels are ordered left→right as stated; header height 48 ± 1 px; a `touchstart/touchmove/
  touchend` sequence of +60 px on `point-selected` increases the `r` query value and moves
  `ceiling-line` right. **Must-not-contain:** horizontal overflow in any state; a touch target
  under 44 px; a vertical `div-slider` at this width. Fail = any theme, any leg.
- **Kind.** property (four themes; every interactive element).

### A-PS-43 — the default view is the Example Portfolio with its allocation and no fund set aside; a menu holding a fund its tensor sets aside shows the excluded-fund note; the preset menu is driven by `/api/presets`
Phase 3 · ui
- **Claim.** With no query, the page loads the first preset from `/api/presets`, shows
  `point-current`, lists 23 `fund-row-*` in `"$"` mode with amounts equal to the presets body's
  allocation (18 non-zero) and no `excluded-note` on any of them (the default tensor uses all 23
  funds; owner decision 2026-10-13, spec §2), and `preset-menu` lists the presets' names from the
  body and loads the second one in one click (fetching the tensor URL the body declares and
  setting `u=`). That second menu holds FIENX, which its tensor sets aside: the FIENX row, and no
  other, shows an `excluded-note` with that tensor's exact reason string, and the note changes
  to the 10y tensor's reason when `lookback-10y` is chosen.
- **Setup.** The mock presets body with the fixture allocation and a deliberately distinctive
  second-preset name (e.g. `"TSP (G, F, C, S, I) [mock-7f3]"`) and a distinctive tensor URL for
  it that the mock serves; the fixture tensor with 23 funds and an empty `excluded` array; the
  second preset's funds are the same 23 plus FIENX, and its tensor is the fixture tensor with
  FIENX added to `excluded` with a reason that exists only in the mock (`"converted to an ETF; no
  data since 2024-10-30 [mock-7f3]"`, with `" [10y]"` appended in the 10y tensor), as the service
  lists any fund of a menu it cannot use.
- **Observation.** `point-current` visible; 23 rows; `unit-toggle` reads `$`; each row's amount
  equals the body's allocation for that id (string-compare after formatting), exactly 18 are
  non-zero; no fund row contains an `excluded-note` and there is no `fund-row-FIENX`;
  `preset-menu` entries' texts equal the body's names in order (so the distinctive suffix
  appears); choosing the second entry issues exactly one `GET` to the body's declared URL and
  the address gains `u=<second id>`; then 24 rows, `fund-row-FIENX` contains an `excluded-note`
  whose text equals the second tensor's reason, and it is the only `excluded-note` in a fund row;
  after `lookback-10y` (one `GET` to the declared 10y URL) the same row's note equals the 10y
  tensor's reason.
  **Must-not-contain:** a hard-coded preset name that differs from the body (the suffix must
  show); a request to any tensor URL other than the declared one; an `excluded-note` on a fund
  the tensor uses; a note text that is not the served tensor's reason. Fail = any.
- **Kind.** example (anchored to the mock body as source of truth).

### A-PS-44 — the heatmap renders from the theme ramp under the frontier only
Phase 3 · ui (all four themes)
- **Claim.** Sampling the canvas at 20 points inside feasible cells yields ≥ 3 distinct colors,
  every sampled color lies on the theme's `--heat-0..4` ramp, points above the frontier equal the
  page background, and the plain legend text is present.
- **Setup.** As A-PS-41; the test computes cell centers from the tensor's `frontier.x`,
  `grid.y` and the chart's margins/scales (read from the overlay's axis ticks), picking 20
  feasible cells spread over `Z/enb_ref` and 5 points above the curve.
- **Observation.** For each theme: `getImageData` at the 20 cell centers gives ≥ 3 distinct RGB
  triples; each triple is within ΔE-like distance 12 (per-channel ≤ 12/255) of some point on
  `interpolateRgbBasis(heat-0..4)` evaluated from the theme's computed custom properties; the 5
  above-frontier samples equal the computed `--bg` (±2/255); the legend text "How spread out the
  risk is" is visible. **Must-not-contain:** a sampled cell color off the ramp (for instance a
  stale ramp from another theme); a colored pixel above the frontier. Fail = any theme.
- **Kind.** property (four themes; 25 samples each).

### A-PS-45 — the risk slider's readouts are the frontier mix's truth and move together without a request
Phase 3 · ui
- **Claim.** At five increasing slider positions `ceiling-line` moves right, `risk-readout-bad`
  and `risk-readout-typical` equal `Low_front(s)` and `Typical_front(s)` computed by the test
  from `frontier_curve` (±0.1 pp), both change on every move, `point-selected` never sits right
  of the line, no `/api/*` request fires during the moves, arrow keys step 1/200 of the domain,
  and after moving the diversification slider down the result strip differs from the readouts and
  is labelled "Selected mix".
- **Setup.** As A-PS-41; the test reads `frontier_curve` and `s_safe` from the fixture; positions
  `s_safe + i·(NX−1−s_safe)/6` for `i = 1..5`, set by keyboard/drag on `risk-slider`; the
  network log recorded.
- **Observation.** `ceiling-line` x strictly increases; at each position the two readouts parse to
  numbers within 0.1 pp of the test's `μ/2 − 1.96σ/√2` and `μ/2` at the interpolated curve
  point; both readouts' text differs from the previous position's on every step; `point-selected`
  center x ≤ line x + 1 px; the network log has zero `/api/` entries between the first and last
  move; one ArrowRight changes `r` by `(NX−1−s_safe)/200` (±1e-6); after `div-slider` is moved to
  the bottom, `range-typical` ≠ `risk-readout-typical` and the strip's label text includes
  "Selected mix". **Must-not-contain:** a step where only one readout changes; a request during
  the drag; the point right of the line. Fail = any.
- **Kind.** property (five positions; keyboard and drag).

### A-PS-46 — the diversification slider starts at the suggested spot, moves the point down and never right, and the point is drawn where its mix sits
Phase 3 · ui
- **Claim.** On load `div-reset` is hidden and the slider's `t` equals `t_auto(s)` from the
  tensor; moving toward "More diversified" moves `point-selected` down and never right of
  `ceiling-line`; at `t = 0` the point lies on the drawn frontier within 1 px; with details on and
  `r` an integer, `details-enb` at `t = 1` is ≥ its value at `t = 0`; at every tested `(s, t)` the
  point's pixel position equals the chart scales applied to the test's own `stats(interpolate(s,
  t))` within 1 px; where both neighbouring ladders are collapsed the slider is disabled with
  the §3.2 note (skipped only if the fixture has no such pair).
- **Setup.** As A-PS-41; the test reuses the TypeScript math (A-PS-34) to compute expected
  positions; `r` set to an integer column for the ENB leg.
- **Observation.** `div-reset` absent/hidden on load and present after one move; initial `d`
  decodes to `t_auto(s)` (±1e-6); over five downward steps the point's y increases monotonically
  and x ≤ line x + 1 px; at the top the point's center is within 1 px of the canvas-drawn curve
  (sampled by locating the frontier stroke color in the column); `details-enb(t=1) ≥
  details-enb(t=0)`; the drawn position matches the computed `(σ, μ)` through the axis scales
  within 1 px at `t ∈ {0, 0.5, 1}` and three `s` values; collapsed pair → `div-slider` has
  `disabled` and the note "At this risk, the best-return mix is already the most diversified one
  found." **Must-not-contain:** a visible reset link before any move; a point drawn at the
  ceiling rather than at its actual σ when they differ by more than 1 px. Fail = any.
- **Kind.** property (three `s` × three `t`; the collapsed case).

### A-PS-47 — the diversification word is quiet, one of four, with thresholds as specified
Phase 3 · ui + unit
- **Claim.** `div-word` is one of Good/Average/Fair/Poor, rendered at ≤ 14 px in the theme's
  `--muted` color, the ENB number is absent until `details-toggle` is on and then reads "spreads
  risk over the equivalent of N independent bets; highest found on this menu: M" with the ratio
  matching the word, and the pure mapping uses `q ≥ 0.75` Good, `0.50 ≤ q < 0.75` Average,
  `0.30 ≤ q < 0.50` Fair, `q < 0.30` Poor.
- **Setup.** As A-PS-41 for the UI legs; the word function for the unit leg with `q ∈ {0.299,
  0.30, 0.499, 0.50, 0.749, 0.75, 1.0}`.
- **Observation.** UI: `div-word` text ∈ the four words; computed `font-size ≤ 14px`; computed
  `color` equals the computed `--muted` of the active theme; before details, no element's text
  matches `/\d\.\d+ (independent )?bets|ENB/`; after details, `details-enb` matches the template,
  its `N / M` ratio falls in the band of the shown word, and the technical name "effective number
  of bets, minimum torsion" appears. Unit: the seven `q` values map to Poor, Fair, Fair, Average,
  Average, Good, Good. **Must-not-contain:** a numeric score next to the word in the default
  view; a font size above 14 px; a word outside the four. Fail = any.
- **Kind.** property (threshold boundaries; four themes for the style legs).

### A-PS-48 — the default DOM is plain language, impersonal, with the disclaimer always visible
Phase 3 · ui (desktop and phone; four themes; both presets of the mock)
- **Claim.** With details off and every section expanded, the visible text contains none of
  `bets`, `knee`, `Sharpe`, `tangency`, `covariance`, `sigma`, `quantile`, `significant`,
  `you should`, `we recommend`, `Risk Number`, `Risk Score`, `login`, `sign in`, `password`
  (case-insensitive, word-bounded), contains every plain label of the §3.6 "Default" column
  that applies to the view, and with details on contains the technical names; the §3.7 footer
  disclaimer is visible outside any collapsed section, "Historical math, not investment advice."
  sits under the result strip, and `footer-cta` links to the three family URLs.
- **Setup.** As A-PS-41 and A-PS-42; sections expanded by clicking the four chips; details
  toggled per leg.
- **Observation.** `document.body.innerText` (details off) matches none of the forbidden
  patterns and contains: "Risk: how much it bounces around in a year", "Expected return per
  year", "How spread out the risk is", "Best-return mix at this risk", "Selected mix", "More
  return", "More diversified", "Suggested", "Same menu, different years of history", "The mix you
  entered", "Historical math, not investment advice."; the `disclaimer` element's text equals
  the §3.7 paragraph verbatim and its rect is visible with no `aria-expanded="false"` ancestor;
  `footer-cta` contains anchors whose `href`s are exactly the three URLs. Details on:
  `innerText` contains "Standard deviation of yearly return", "effective number of bets, minimum
  torsion", "minimum torsion", "Estimated central 95% range". **Must-not-contain:** any
  forbidden pattern with details off; a disclaimer inside a collapsed section; a CTA keyed to
  the visitor's result (the CTA text must be identical across the two presets and all slider
  positions). Fail = any viewport, theme or preset.
- **Kind.** property (2 viewports × 3 themes × 2 presets).

### A-PS-49 — four themes with distinct computed tokens and a repainted canvas; the choice is remembered; HUD references nothing
Phase 3 · ui + static
- **Claim.** `theme-switch` cycles `ks-dark → light → hud` on `html[data-theme]`; for each theme
  the computed `--bg`, `--surface`, `--text`, `--accent`, `--frontier` and `--heat-0..4` equal the
  §3.5 table; a canvas pixel sample differs between every pair of themes; the frontier stroke
  color equals `--frontier`; the choice survives reload via `localStorage("ps.theme")`; `?t=hud`
  wins over storage; `prefers-reduced-motion: reduce` yields no CSS transitions; and the
  repository contains no reference to the film, its characters or trademarks behind the HUD
  look.
- **Setup.** As A-PS-41; the §3.5 table embedded in the test as the declared set; a needle list
  (the film title, character names and trademarked terms named in the owner's inputs
  `docs/plans/2026-10-12_original_prompt.md` line 33 and `docs/reviews/…addendum…` line 18) kept
  only in the test file; grep scope `web/src`, `web/worker`, `data/`, `README.md`, `ROADMAP.md`,
  `docs/specs`, `docs/plans/*runbook*`, excluding the test file, `docs/reviews/`, the original
  prompt and this assertions file.
- **Observation.** Three clicks produce the three `data-theme` values in order and return to the
  first; for each theme every listed token's computed value equals the table (hex compared
  case-insensitively after normalisation); the mean RGB of 50 fixed canvas samples differs by
  > 20/255 on at least one channel between each pair of themes; `localStorage.getItem
  ("ps.theme")` equals the chosen id and a reload without `t=` restores it; with `light` stored,
  loading `?t=hud` renders `hud`; under reduced motion no element has a non-zero computed
  `transition-duration`; the grep over the scope finds zero needle hits and at least 20 hits for
  the word `HUD` (proves the scope is populated). **Must-not-contain:** two themes whose
  canvas samples are indistinguishable; a token value from the wrong column; a needle hit.
  Fail = any.
- **Kind.** property (four themes; every token; every scoped file).

### A-PS-50 — stress cards show real history with coverage, or say they cannot
Phase 3 · ui + unit
- **Claim.** `section-stress` shows three cards (`stress-gfc2008`, `stress-covid2020`,
  `stress-rates2022`) with the selected mix's window return `Σ wᵢRᵢ / Σ wᵢ` over covered funds, a
  coverage note whenever covered weight < 100%, and the sentence "Not enough of this mix existed
  then to say." instead of a number whenever covered weight < 50%; the pure aggregation function
  behaves the same for generated inputs.
- **Setup.** The fixture tensor whose `stress` block has at least one `null` fund in `gfc2008`;
  a mock custom tensor (SGOV + VTIP) with 100% of weight in funds `null` for `gfc2008`; 200
  generated `(w, R)` pairs with random null patterns for the unit leg.
- **Observation.** Default: three cards with numbers; the `gfc2008` card's number equals the
  test's own aggregation of the tensor's `r` and the current weights (±0.01 pp), and the card
  shows "N of M funds (P% of the mix) didn't exist yet" with N, M, P matching the null pattern;
  the SGOV + VTIP mock: the `gfc2008` card shows the exact sentence and no percentage. Unit:
  for all 200 pairs the function returns the formula's value when covered ≥ 0.5 and the sentinel
  otherwise; the boundary 0.5 returns a number and 0.4999 the sentinel. **Must-not-contain:**
  a number computed with a `null` fund treated as 0; a number when covered < 50%. Fail = any.
- **Kind.** property (200 generated inputs; both UI fixtures).

### A-PS-51 — the address reproduces the view in a fresh context
Phase 3 · ui
- **Claim.** After changing the risk slider, the diversification slider, the theme, the unit
  and details, the address bar contains `u`, `r`, `d`, `t`, `x`, `unit` (and `lb`), opening that
  URL in a fresh browser context reproduces the same `risk-readout-bad`, `range-low`, `div-word`,
  `data-theme`, unit and details state, and `share-copy` places that exact URL on the clipboard.
- **Setup.** As A-PS-41; clipboard permission granted; a second `browser.newContext()` with
  empty storage.
- **Observation.** The URL after the changes parses to the expected keys; the fresh context's
  five readouts equal the first context's text exactly; `navigator.clipboard.readText()` after
  `share-copy` equals `location.href`; `share-link` shows the same string. **Must-not-contain:**
  a key outside §8.1; a readout that differs between contexts; a URL that depends on
  `localStorage` (the fresh context has none). Fail = any.
- **Kind.** example (one full state; checked on two viewports).

### A-PS-52 — the bundle carries no secret, no gate header and no origin host
Phase 3 · static
- **Claim.** `web/dist` after `npm run build` contains none of the secret values from
  `~/.secrets/portfoliosight.env`, neither the string `x-ps-gate` nor `PS_GATE_SECRET`, nor the
  host `api.portfoliosight.ai`; every API call in the bundle targets a same-origin `/api/` path.
- **Setup.** A fresh `npm run build`; the env file's values read by the test (never printed, ≥ 5
  non-empty values confirmed).
- **Observation.** A scan of every file under `web/dist` finds zero occurrences of each secret
  value, of `x-ps-gate`, `PS_GATE_SECRET`, `api.portfoliosight.ai`, `MAILCHANNELS`; it finds ≥ 1
  occurrence of `/api/presets` (proves the scan reads the real bundle). **Must-not-contain:**
  any of the listed strings. Fail = any hit or a missing `/api/presets` hit.
- **Kind.** property (every bundle file).

### A-PS-53 — cap edits are validated inline and sent only when valid
Phase 3 · ui
- **Claim.** Setting `cap-min-VTI` above `cap-max-VTI` shows an inline error and sends no
  request; a valid `cap-max-VTI = 10` sends one `POST /api/tensors` whose body carries
  `{"id":"VTI","min":null,"max":0.10}` with every other fund `null/null`; `caps-reset` restores
  every field to the rule values `max(0.25, 3/N)` and sends a POST with all-`null` policy; the
  Settings copy states the rule in one sentence with the current N.
- **Setup.** As A-PS-41 with the mock accepting POSTs (returning 200 with the fixture URL) and
  recording bodies.
- **Observation.** Invalid: an error element adjacent to the field, the mock's POST log
  unchanged; valid: exactly one POST, body as stated, `use-menu`/rebuild flow proceeds; reset:
  fields read the rule values (25% for N = 23), one POST with all-`null`, the sentence "No single
  fund above 25% (menu of 23)" visible. **Must-not-contain:** a POST on invalid input; a
  non-`null` entry for an unedited fund. Fail = any.
- **Kind.** example (invalid, valid, reset).

### Phase 4 — production deployment

### A-PS-54 — the page loads with the header on both viewports
Phase 4 · prod
- **Claim.** With `x-ps-gate: $PS_GATE_SECRET`, `GET https://portfoliosight.ai/` returns 200 and
  `chart-canvas` is visible within 5 s on `chromium-desktop` (1366×900) and `chromium-phone`
  ("iPhone 13"), and the page's `/api/presets` response carries `x-ps-source: r2`.
- **Setup.** Playwright with `extraHTTPHeaders: {"x-ps-gate": …}`; a fresh context per project;
  the network log recorded.
- **Observation.** Navigation response status 200; `chart-canvas` visible ≤ 5 s; the logged
  `/api/presets` response has status 200 and `x-ps-source: r2`; the canvas is non-blank (≥ 3
  distinct colors over 20 samples as in A-PS-44). **Must-not-contain:** a 403 preview page or
  challenge with the header present; a blank canvas. Fail = any viewport.
- **Kind.** example (two viewports).

### A-PS-55 — the origin gate, the www redirect and the disabled `workers.dev` host
Phase 4 · prod
- **Claim.** `GET https://api.portfoliosight.ai/v1/health` without the header returns 403 and
  with it returns 200 JSON with `generation` and `asof`; `GET https://www.portfoliosight.ai/?u=tsp`
  (with the header) returns 301 to `https://portfoliosight.ai/?u=tsp`; the Worker's `workers.dev`
  hostname does not serve the site.
- **Setup.** Plain HTTP client; the Worker name `portfoliosight` and the account's `workers.dev`
  subdomain read from `wrangler whoami`/`wrangler.jsonc`.
- **Observation.** Without header: 403 (any body; the edge-vs-origin distinction is A-PS-67).
  With header: 200, `content-type: application/json`, body has `status == "ok"`, `generation`
  matching `^\d{4}-\d{2}-\d{2}-[0-9.]+$`, `asof` an ISO date, `queue.depth` int. www: 301 with
  `Location` exactly `https://portfoliosight.ai/?u=tsp`. `https://portfoliosight.<subdomain>.
  workers.dev/` → connection error or 404, never 200 with the page. **Must-not-contain:** a 200
  from the health route without the header; a www response that serves the page directly.
  Fail = any.
- **Kind.** example.

### A-PS-56 — presets and tensors are served from R2 and a POST for the default preset resolves to the same tensor
Phase 4 · prod
- **Claim.** `GET /api/presets` carries `x-ps-source: r2`, a `generation`, and both presets with
  all six lookbacks `ready` and `/api/…` URLs; the `guide2017` 5y URL returns a tensor that
  validates against `portfoliosight/engine/tensor.schema.json` with `Cache-Control: public,
  max-age=86400, immutable`, an `ETag` and `x-ps-source: r2`; a `POST /api/tensors` with the
  default preset's funds and all-`null` caps returns 200 with a `url` whose body is byte-identical
  to that tensor. The default tensor uses all 23 Step 2 funds and sets none aside; a `POST` for
  those 23 funds plus FIENX (the catalog's converted fund, not served) resolves to a tensor that
  sets exactly FIENX aside with the §5.1 reason (owner decision 2026-10-13, spec §2).
- **Setup.** Header-bearing client; the schema file from the repo at the deployed SHA.
- **Observation.** Presets: headers and shape as stated; `presets[*].lookbacks` has exactly the
  six ids, each `status == "ready"`, each `url` starting `/api/tensors/{generation}/`. Tensor:
  schema-valid; `generation` and `asof` equal the presets body's; `universe.preset_id ==
  "guide2017"`; `funds` are the 23 Step 2 funds and `excluded` is empty.
  POST: 200, `hash` equals the preset's `hash`, and `GET url` body bytes equal the preset
  tensor's bytes (same `ETag`). POST for the 23 funds plus FIENX: 200 or 202, then
  `GET /api/tensors/{G}/{hash}/5y` returns the tensor within 150 s; it is schema-valid, its
  `funds` are the 23 Step 2 funds and its `excluded` is exactly FIENX with the §5.1 reason (one
  real build per generation: the key is the same on every run). **Must-not-contain:** a lookback not `ready`; `x-ps-source:
  origin` on either preset GET; a POST that enqueues (202) for the preset key; FIENX among the
  funds in use; a fund set aside in the default tensor. Fail = any.
- **Kind.** example.

### A-PS-57 — the nightly is fresh: `asof` equals `D_G`, the run finished clean, twelve tensors exist, the cache is under its cap, and the page says which date it shows
Phase 4 · prod (run at or after 08:00 PT)
- **Claim.** The current generation's `asof` equals the test's own `D_G` for the check day
  (A-PS-08's rule with the scheduled start 02:00 PT), `meta/status.json` as exposed by
  `/api/health.nightly` shows that run finished with zero errors, the generation holds the 12
  preset tensors, the KS-001 cache volume is ≤ 300 MB, the timer is enabled, and the page's
  details line "prices through {asof}" shows the same date.
- **Setup.** Header-bearing client; `exchange_calendars` locally; ssh to `$PS_KS001_SSH_HOST`; Playwright
  with details toggled on.
- **Observation.** `health.asof == D_G(today)`; `health.asof_trading_days_behind == 0`;
  `health.nightly.finished` is today's date in PT, `errors` is empty or 0, and its `D_G` equals
  `asof`; `/api/presets` lists 12 `ready` URLs and `HEAD` on each returns 200; over ssh
  `docker exec portfoliosight-api du -sm /app/cache` ≤ 300 and `systemctl is-enabled
  portfoliosight-nightly.timer` prints `enabled`; the details text contains `prices through
  {asof}` with the same date. **Must-not-contain:** a stale `asof` (any earlier session); a
  non-empty error list; a cache over the cap; a page date that differs from the API's.
  Fail = any.
- **Kind.** example (calendar-dependent, computed at run time).

### A-PS-58 — the store is verified, seeded, mirrored, and the cron is installed once
Phase 4 · live (laptop)
- **Claim.** `python -m portfoliosight.data.store --verify` passes against the bucket;
  `meta/manifest.json` holds ≥ 1,400 symbols with `source` containing `seed`; `scripts/
  r2_backup.sh` has mirrored the bucket to `/mnt/d/portfoliosight-data/`; a dry-run `--restore`
  reports zero files to upload; `crontab -l` shows exactly one PortfolioSight line.
- **Setup.** `/mnt/d` mounted on the laptop; the env file; the backup already run once by the
  deployment step.
- **Observation.** Verify exits 0 (A-PS-13 semantics); manifest count ≥ 1,400 with `seed` in
  `source` and every such entry has `adjusted_through` present; for a random sample of 20 `prices/`
  keys, the mirrored file exists at `/mnt/d/portfoliosight-data/prices/…` with the same byte size;
  `aws s3 sync --dryrun` in the restore direction prints no `upload:` lines; `crontab -l | grep -c
  r2_backup.sh` equals 1 and the line equals §5.3's. **Must-not-contain:** a mirrored file whose
  size differs; a second cron line; a restore dry-run that would upload. Fail = any.
- **Kind.** example (sample of 20 keys).

### A-PS-59 — every served symbol is current and the runbook records the licensing decision
Phase 4 · prod + static
- **Claim.** Every symbol in `/api/symbols` has manifest `status: ok` with `adjusted_through ≥
  D_G − 3` trading days and `last_date ≥ D_G − 3`, no `pending` or `unavailable` symbol appears,
  `tiers_served` equals the tiers present, and `docs/plans/2026-10-13-ks001-cloudflare-runbook.md`
  records the §9.6 personal-use decision with a date in place of the superseded owner checkbox.
- **Setup.** Header-bearing client; `meta/manifest.json` read from R2 with the laptop keys; `D_G`
  from `/api/presets`'s generation; the XNYS calendar.
- **Observation.** For a random sample of 20 symbols (and all 16 TSP ids) the manifest entry
  is `ok` with both dates within 3 trading days of `D_G`; the set of `/api/symbols` ids equals
  the set of manifest ids with `status == "ok"` (set equality, both directions); `tiers_served`
  equals `{tier of s for s in symbols}`; the runbook contains a line matching
  `personal use.*2026-\d{2}-\d{2}` or `2026-\d{2}-\d{2}.*personal use` under §9.5 step 3's
  heading. **Must-not-contain:** a listed symbol whose manifest status is not `ok`; an `ok`
  symbol missing from the listing. Fail = any.
- **Kind.** property (set equality over the whole catalog; sample of 20 for dates).

### A-PS-60 — a 23-fund build completes within the benchmark on KS-001
Phase 4 · prod
- **Claim.** With an idle queue, a `POST /api/tensors` for a fresh 23-fund key (the default
  preset's funds with one cap override so the key is new) reaches `ready` within 30 s, or the
  §4.12 fallback grid is in effect (`NX = 32`, `NY = 24` in the resulting tensor) and the build
  still reaches `ready` within 30 s; the runbook records the measured time.
- **Setup.** `/api/health.queue.depth == 0` and `building == false` before the POST; the cap
  override chosen as `max = 0.24` on the first fund (not previously requested in this
  generation; the test verifies the first response is 202, not 200).
- **Observation.** Wall time from the POST to the first 200 ≤ 30 s; the tensor's
  `frontier.x.length` is 48 and `grid.y.length` 32, or 32 and 24 respectively; the runbook
  contains a line with the measured seconds and the grid in effect. **Must-not-contain:** a
  first response of 200 (cached key: the measurement would be void); a tensor with any other
  grid size. Fail = over 30 s, a cached key, or a missing runbook line.
- **Kind.** example.

### A-PS-66 — a headerless, cookieless request to `/` is Managed-Challenged at the edge
Phase 4 · prod (depends on the WAF rule `ps-challenge-site`, which the build creates with the widened token; report blocked, not failed, if the token's `Zone WAF Edit` is withdrawn)
- **Claim.** A fresh request to `https://portfoliosight.ai/` with no cookies and no `x-ps-gate`
  header receives HTTP 403 with `cf-mitigated: challenge`, and the same request with the header
  receives neither the challenge nor the preview page.
- **Setup.** A cookieless HTTP client (no Playwright context reuse); the zone's rulesets listed
  through the Cloudflare API with the token to confirm the rule exists and is enabled (this is
  the dependency check, recorded in the test output).
- **Observation.** Headerless: status 403, header `cf-mitigated: challenge`, body is Cloudflare's
  challenge page (contains `cf-chl` or `challenge-platform`), **no** `x-ps-source` and no
  "private preview" text (the Worker was never reached). With header: status 200 and the page's
  `<title>` or `chart-canvas` marker present; no `cf-mitigated` header. Same for
  `https://portfoliosight.ai/api/presets`: headerless → 403 challenge, no JSON. **Must-not-
  contain:** a 200 for a headerless request; a Worker-served page (preview or app) without the
  header. Fail = any.
- **Kind.** example (two paths × two credentials).

### A-PS-67 — a headerless request to `api.portfoliosight.ai` is blocked at the edge, before the origin
Phase 4 · prod (depends on the WAF rule `ps-block-api-direct`; same dependency note as A-PS-66)
- **Claim.** `GET https://api.portfoliosight.ai/v1/health` without the header is refused by
  Cloudflare's block action and never reaches FastAPI; with the header it returns the origin's
  200.
- **Setup.** Plain HTTP client; the rule confirmed present and enabled via the rulesets API.
- **Observation.** Headerless: status 403, `content-type` is `text/html` and the body is
  Cloudflare's block page (contains `cf-ray` reference text or the `1020`/`Access denied`
  marker), **not** the application's JSON envelope `{"error":{"code":"forbidden"…}}`; `server:
  cloudflare` present. With header: 200 JSON as A-PS-55. **Must-not-contain:** the
  application's envelope on the headerless request (would prove the origin was reached and only
  the application refused). Fail = any.
- **Kind.** example.

### A-PS-68 — the edge rate-limits `POST /api/tensors` and leaves polling alone
Phase 4 · prod (depends on the rate-limiting rule `ps-tensor-post`; same dependency note as A-PS-66)
- **Claim.** 25 `POST /api/tensors` within 10 s from one IP (with the header) produce at least
  one 429 that lacks `x-ps-source` (edge, not application), and 25 `GET /api/tensors/{G}/{hash}/5y`
  within 10 s produce no edge 429.
- **Setup.** Header-bearing client; a valid preset key for the GETs; the POST body is the
  default preset's (so no job is created and the application's own 5-per-minute limiter also
  fires, which is distinguished by `x-ps-source: origin`).
- **Observation.** Among the 25 POST responses: ≥ 1 with status 429 and **no** `x-ps-source`
  header; among the 25 GET responses: zero responses that are 429 without `x-ps-source` (200s
  and application 429s are allowed). The rule confirmed present via the rulesets API.
  **Must-not-contain:** 25 POSTs all reaching the origin (every response carrying
  `x-ps-source`). Fail = either leg.
- **Kind.** example (two bursts).

### Phase 5 — smoke tests and docs

### A-PS-61 — private preview is on in production and no keyless path yields data
Phase 5 · prod + static
- **Claim.** The deployed Worker's `PS_PRIVATE_PREVIEW` var is `"1"`, the committed
  `web/wrangler.jsonc` at the deployed SHA says the same, and no request lacking the gate secret
  (without the header, without a `ps_preview` cookie) receives data from `/`, `/api/presets`,
  `/api/symbols` or a tensor URL.
- **Setup.** `wrangler versions view <active version id>` (from `wrangler deployments list`) run
  from `web/` with the account token; the repo at the SHA the Worker reports (or the deploy
  log's SHA); a cookieless client. Note from §0: with the WAF rule in front, a headerless
  request gets the challenge, so the preview page itself is observed at the unit level
  (A-PS-39) and by the owner in H-PS-01; this assertion checks the var and the absence of data.
- **Observation.** The versions output lists `PS_PRIVATE_PREVIEW` with value `1`;
  `wrangler.jsonc` `vars.PS_PRIVATE_PREVIEW == "1"`; each of the four keyless requests returns
  403 with either `cf-mitigated: challenge` or a body containing "private preview", and in every
  case **no** `x-ps-source` header, no JSON body, no `<canvas` or `chart-canvas` marker.
  **Must-not-contain:** a 200 or any data on a keyless path; a deployed var of `0` while the
  commercial license is not recorded in the runbook. Fail = any.
- **Kind.** property (four paths; config and live legs).

### A-PS-62 — TSP loads in one click and a custom menu builds end to end in production
Phase 5 · prod
- **Claim.** Selecting "TSP (G, F, C, S, I)" in `preset-menu` loads a five-fund tensor whose
  Settings show `max` 60% per fund, with no `point-current` and no `section-trades`; typing
  "L 2050" in `fund-add` offers `TSP-L2050`; with an idle queue, a custom menu of four served
  symbols (preferring `VOO, BND, VNQ, SGOV`, otherwise the first four `ok` symbols of
  `/api/symbols`) and `use-menu` shows `building-notice` (unless the key is cached) and the chart
  updates within 120 s with `universe.funds` equal to the four; an unknown ticker shows an inline
  error naming it; a 31st fund is refused with a message.
- **Setup.** Header-bearing Playwright; `/api/health.queue.depth == 0`; the catalog from
  `/api/symbols`.
- **Observation.** After the TSP click: exactly one tensor GET whose `universe.funds` ids are
  `TSP-G, TSP-F, TSP-C, TSP-S, TSP-I`, `cap-max-*` fields read 60, `point-current` absent,
  `section-trades` absent, address has `u=tsp`. `fund-add` with "L 2050" lists an option whose id
  is `TSP-L2050`. Custom: `building-notice` visible (or the first tensor GET is a 200 within 2 s
  for a cached key, which the test records), `chart-canvas` repaints (pixel sample changes) within
  120 s, the loaded tensor's `universe.funds` equal the four ids and `universe.hash` equals the
  test's own A-PS-29 hash of them. Unknown ticker `ZZZZ`: an inline error containing `ZZZZ`, no
  POST. 31 funds: `use-menu` disabled or a message containing "30", no POST. **Must-not-
  contain:** a trades section for the TSP preset; a build that never resolves (120 s cap); a
  POST for the invalid menus. Fail = any.
- **Kind.** example (TSP, custom, two refusals).

### A-PS-63 — lookbacks, ghosts and cap rebuilds work in production
Phase 5 · prod
- **Claim.** On the default preset, choosing `lookback-10y` loads the 10y tensor and redraws the
  frontier, the Settings exclusion list equals the set the test computes from `/api/symbols`
  `first_date` values and the §4.2 rule for that window, the same holds for a custom menu that
  holds a served fund too young for the 10y view (which is listed with its reason) and FIENX as
  a fund that is not served (which is listed too), toggling
  `ghost-1y` increments `data-ghost-count` on `chart` by one and changes sampled canvas pixels,
  toggling it off restores both, and editing `cap-max-VTI` to 10 triggers a rebuild whose tensor
  has every `frontier.w[j][VTI] ≤ 0.10 + 1e-6`.
- **Setup.** Header-bearing Playwright; the 10y window bounds from the 5y tensor's `asof`
  (`D_G − 2520` trading days) and `first_date` per fund from `/api/symbols`. Since the owner
  decision of 2026-10-13 (spec §2) the default menu may have no excluded fund, so the test also
  loads `/?f=…&lb=10y` with two default funds older than the window, one served fund whose
  `first_date` is after the threshold (SGOV when it qualifies) and FIENX, which is not served:
  one real build per generation.
- **Observation.** After `lookback-10y`: one GET to the preset's 10y URL, the frontier's sampled
  pixels differ from the 5y drawing, `lb=10y` in the address; the texts of `excluded-note` in
  Settings equal (as a set of ids) `{f : first_date(f) > start_10y + 252}` filled with the §5.6
  template; for the custom menu, the loaded 10y tensor carries the test's own universe hash, its
  `excluded` is exactly the young fund and FIENX, no weight vector carries them, and Settings
  lists exactly those two, the young fund with the "history starts …, not enough for the … view"
  reason;
  `data-ghost-count` goes 0 → 1 → 0 and the 50-sample canvas mean differs at 1 from
  both 0 states, which equal each other; cap edit: one POST with `VTI max 0.10`, 202 then 200,
  the loaded tensor's VTI column of `frontier.w` and of every non-null `grid.w` is ≤ 0.10 + 1e-6
  and `bounds.requested` shows the override. **Must-not-contain:** an exclusion list that
  differs from the computed set; a ghost count that fails to return to 0; a VTI weight above
  the cap. Fail = any.
- **Kind.** example (anchored to the live catalog).

### A-PS-64 — share by email sends the fixed message to the test recipient only
Phase 5 · prod
- **Claim.** With `PS_SHARE_TEST_RECIPIENT` set, opening `share-open`, entering that address only,
  and clicking `share-send` makes `POST /api/share` return 202 and `share-status` read "Sent";
  a malformed address returns 400 without sending; a `url` on another host returns 400; while
  preview is on the dialog shows the preview notice.
- **Setup.** Header-bearing Playwright; the env var present (the test **skips with a named
  reason** only if it is absent, and that skip is the one sanctioned by A-PS-65); a direct HTTP
  client for the two invalid cases with `Origin: https://portfoliosight.ai`.
- **Observation.** Dialog flow: the request body's `to` equals the env value exactly, response
  202, `share-status` text "Sent"; the dialog contains the preview notice (A-PS-38's text) while
  A-PS-61 holds. Direct: `{"to":"not-an-address","url":<current>}` → 400 `invalid_recipient`;
  `{"to":<env>,"url":"https://example.com/"}` → 400 `invalid_url`. **Must-not-contain:** any
  recipient other than the env value in any request the test issues; a 202 for either invalid
  case. Fail = any.
- **Kind.** example.

### A-PS-65 — quality gates, one smoke test per DoD item, no skipped tests, docs updated
Phase 5 · static + unit
- **Claim.** On `main`: `ruff check . && ruff format --check . && pyright .` exit 0; `pytest
  --cov=portfoliosight --cov-report=term-missing` passes with ≥ 80% total line coverage and 100%
  on `portfoliosight/engine/`; `npm run lint && npm run typecheck && npm test` exit 0 in `web/`;
  `web/e2e/smoke.spec.ts` defines exactly one test per DoD item 1–31 named `DoD-NN`; no test in
  `tests/`, `web/tests/` or `web/e2e/` carries an unconditional `skip`, `xfail`, `only` or `todo`
  marker; `README.md` is ≤ 60 lines, names the WSL working copy as the lake and
  `/mnt/d/portfoliosight-data` as the backup, and does not name `/mnt/d` as the lake; `ROADMAP.md`
  contains the Appendix B items.
- **Setup.** The repository at the merged `main`; the commands run in the project venv and in
  `web/`.
- **Observation.** Exit codes 0; the coverage total line ≥ 80% and every `portfoliosight/engine/`
  row 100%; parsing `smoke.spec.ts` yields test titles matching `^DoD-(0[1-9]|[12]\d|3[01])\b`,
  each number exactly once, 31 in all; a grep over the three test trees for
  `pytest\.mark\.skip\(|pytest\.mark\.xfail|\.skip\(|\.only\(|\.todo\(|test\.fixme` finds hits
  only where the same line (or the decorator's condition) references `PS_LIVE_TESTS`,
  `PS_SHARE_TEST_RECIPIENT` or the DoD 9 collapsed-ladder absence; `wc -l README.md ≤ 60`;
  README contains `~/tft-quantile-forecaster/data/tft/raw/eodhd/datalake_us_core` and
  `/mnt/d/portfoliosight-data`, and no line names `/mnt/d` as the lake (`/mnt/d/tft-quantile-
  forecaster` may appear only described as QSE's mirror); ROADMAP contains "Paid tier",
  "Data license", "exact-ENB", "FERS planner". **Must-not-contain:** an unconditional skip; a
  missing or duplicated `DoD-NN`; a coverage row under the thresholds. Fail = any.
- **Kind.** contract (gates) with property legs (every test file; all 31 names).

---

End of machine assertions. 68 specs: A-PS-01 … A-PS-68. Owner-gated group: none (see §0).

## 4. Human verification (not in the gate)

Not a machine assertion: no manifest entry, no gate test. The owner does this by hand and records
the result and its date in the runbook.

### H-PS-01 — the owner's own browser gets through the human check, sees the private-preview page without the key, and the chart with the preview link
Phase 5 · the owner's own Chrome (S20, F12, DoD 1, §9.6)
- **Why it is not in the gate.** Cloudflare's Managed Challenge is built not to clear for
  automation, so a gate id for it could never go green. The parts a machine can see are asserted
  elsewhere: the challenge at the edge (A-PS-66), the preview gate's logic (A-PS-39), and the
  deployed preview var with no data on any keyless path (A-PS-61).
- **What the owner checks.** In a Chrome profile with no `ps_preview` cookie: (1) opening
  `https://portfoliosight.ai/` shows Cloudflare's human check, and after passing it the
  "private preview" page with no chart and no data; (2) opening the preview link
  `https://portfoliosight.ai/?k=<PS_GATE_SECRET>` once lands on `/` with the key gone from the
  address bar and the chart showing; (3) on a later visit in the same profile the chart loads
  without the key.
- **Must not see.** The key in the final address or anywhere on the page; any data on the first
  visit.

