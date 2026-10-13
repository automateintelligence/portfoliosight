# Gate change: FIENX replaced by EFA in the default menu

Date: 2026-10-13. For the owner.

Owner's instruction, verbatim: "Use EFA and update any frozen tests."

This is the one sanctioned edit of the frozen done-gate in this run
(`assertions/2026-10-13-portfoliosight-demo-design/`). The gate was not re-frozen here; the
coordinator re-freezes after review. Until then `conductor gate verify` reports the four test
files and three manifest entries below as changed, and nothing else.

## What changed in the product

- `data/holdings/holdings_guide2017_step2.csv` and `data/presets.json`: the "universe only" row
  FIENX is now EFA (iShares MSCI EAFE ETF), quantity 0. The default menu is 23 funds, all usable.
- FIENX stays in the tier 2 list (`data/universes/portfoliosight.txt`) with its note in
  `data/universes/tiers.json`. It is in the catalog, not served, with the reason
  "converted to an ETF; no data since 2024-10-30".
- Fixtures were regenerated, not edited: `tests/fixtures/synthetic_23.parquet` by
  `scripts/make_fixtures.py` (EFA takes FIENX's column position with the same model parameters
  and runs to the last session; the other 22 columns are byte-identical to before) and
  `web/fixtures/guide2017_5y.json` by the pinned build command. The default 5-year tensor now has
  23 funds and an empty `excluded` list.

## Every gate file changed

Ids, commands and timeouts in `manifest.yaml` are unchanged. Only claim texts changed.

| Gate file | Assertion, leg | Before | After | Property it protects | Why the new form is not weaker |
|---|---|---|---|---|---|
| `tests/test_a_ps_29_universe_hash_canonical.py` | A-PS-29, extra tickers added to the menu pool | `"EFA"` among 11 tickers assumed to be outside the guide menu | `"FIENX"` in its place | Random menus are sets of distinct funds; the hash is checked on 61 distinct menus | EFA is now a guide fund, so the old list put EFA in the pool twice and 19 of the 60 random menus held it twice. The pool is again the same 40 distinct ids as before the swap. Every assertion is unchanged. |
| `tests/test_a_ps_43_default_view_presets.py` | A-PS-43, preconditions on the fixture | Fixture `excluded` must contain FIENX with the reason; funds plus excluded are the 23 Step 2 funds | Funds plus excluded are the 23 Step 2 funds (kept); `excluded` is empty; 23 funds in use; FIENX is not in the default menu | The UI test runs on the real default tensor, not a doctored one | Stricter: the fixture must use every Step 2 fund. |
| same | A-PS-43, the mock's second menu and its tensor | Same 23 funds as the first; its tensor is the fixture with each excluded reason suffixed `[mock-7f3]` | The 23 funds plus FIENX; its tensor is the fixture with FIENX added to `excluded`, reason `converted to an ETF; no data since 2024-10-30 [mock-7f3]`, with ` [10y]` appended in that menu's 10y tensor | The note must come from the tensor that was served | The reason still exists only in the mock, so a constant cannot match. The tensor has the shape the service writes for a menu holding FIENX (shown by `tests/engine/test_builder.py::test_a_fund_the_catalog_does_not_serve_is_set_aside_with_its_reason` and `tests/jobs/test_build.py`). |
| same | A-PS-43, leg 3 | `fund-row-FIENX` has one `excluded-note`; its text is the tensor's reason, optionally followed by ": not used" | No fund row of the default view has an `excluded-note`; there is no `fund-row-FIENX` | A row shows a note exactly when its tensor sets that fund aside | The exact-text check moved to leg 6 unchanged. New here: a note on a fund in use now fails, which the old test never checked. |
| same | A-PS-43, leg 6 | After switching menus, the FIENX note contains the second tensor's reason | After switching: 24 rows; `fund-row-FIENX` has one note; its text contains the second tensor's reason and equals it exactly, optionally followed by ": not used"; it is the only note in any fund row | The note follows the served tensor, not a constant | Same string checks as old legs 3 and 6 together, plus the count. Checked against three hollow variants of the Funds table, each of which fails: no note rendered (fails "fund-row-FIENX must contain an excluded-note"), a hard-coded FIENX reason (fails "must show the second tensor's reason string"), a note on every row (fails "no fund row may carry an excluded-note"). |
| same | A-PS-43, leg 7 (added) | (the old test saw the FIENX row with two reasons in turn: the default tensor's, then the second tensor's) | With the second menu shown, `lookback-10y` loads its declared 10y tensor; the FIENX note changes to that tensor's reason, exactly; still 24 rows and one note | A row's note is read again from every served tensor, not remembered | Restores the two-reasons-on-one-row check, which the first form of this change had lost (Codex review, round 1). A fourth hollow variant, a note remembered from the first tensor seen for a ticker, passes legs 1 to 6 and fails here. Uses `chip-settings` and `lookback-10y`, both already pinned by A-PS-53 and A-PS-63. |
| `tests/test_a_ps_56_presets_tensors_from_r2.py` | A-PS-56, default 5y tensor in production | Funds plus excluded are the 23 Step 2 funds; FIENX is in `excluded`, not in funds, with the exact reason | Funds plus excluded are the 23 Step 2 funds (kept); `excluded` is empty; funds are exactly the 23; FIENX is not a Step 2 fund and not in funds | The default tensor is built from the real menu and real data | Stricter for the default: any fund set aside now fails. |
| same | A-PS-56, new test `test_a_menu_holding_fienx_sets_it_aside_with_the_catalog_reason` | (the three FIENX assertions lived in the default-tensor test) | POST the 23 default funds plus FIENX at 5y; accept 200 or 202; poll the tensor URL up to 150 s; that tensor is schema-valid; FIENX is in `excluded`, not in funds, with the exact reason; nothing else is set aside; funds are the 23; every frontier weight vector has 23 entries | Production sets a fund the catalog does not serve aside, with the catalog's reason from real provider data | The same three FIENX assertions, word for word, on a tensor where FIENX really is in the menu, plus three more. The schema check is repeated on this tensor because the default tensor no longer has a populated `excluded` entry for the schema to check (Codex review, round 1). Cost: one real build per generation (the key is the same on every run). |
| `tests/test_a_ps_63_lookbacks_ghosts_caps_prod.py` | A-PS-63, 10y exclusion list, added leg | Exclusion list of the default menu equals the set computed from `/api/symbols` and the spec 4.2 rule | All of that, unchanged; then a custom menu loaded with `/?f=…&lb=10y` (two of BND, VTI, AGG, VNQ older than the window, a served fund whose history starts after the threshold, SGOV when it qualifies, and FIENX, which is not served): the POST is accepted (a refusal fails at once, naming the status); the tensor has the test's own hash, sets exactly the young fund and FIENX aside, no weight vector carries them, and Settings lists exactly those two, the young fund with the "history starts …, not enough for the … view" text | The Settings exclusion list is real, for both kinds of exclusion the rule has: too little history, and not served | Nothing was removed. FIENX is in the menu because the not-served case is the one the default menu used to supply (Codex review, round 1). Without the added leg the computed set for the default menu is now empty in production (all 23 funds are served and older than the window), so the list check would pass with no list at all. See "A-PS-63" below. The first test's time limit went from 120 s to 300 s to allow one build; the manifest timeout (1800 s) is unchanged. |
| `manifest.yaml` | Claims of A-PS-43, A-PS-56, A-PS-63 | As frozen | Reworded to say the above | Claim text matches the test | Text only. |
| `INTERFACES.md` | "Encoding decisions" | — | One entry recording this decision and the three re-anchored assertions | The contract the product is built to | Addition only. |

## Left as they are, on purpose

- A-PS-24: its two `len(universe.funds) == 23` asserts were false with FIENX and are true now.
- A-PS-41, 42, 44, 45, 46: each embeds a copy of the shared helper with an unused constant
  `FIENX_REASON` and a line that suffixes excluded reasons in the mock's second tensor. The
  constant is still a true statement about the catalog; the line now has nothing to suffix. No
  assertion in those files depends on either.
- A-PS-53 (menu size is the included count or included plus excluded) and A-PS-60 (included plus
  excluded is 23): true as written.
- `.frozen`: not regenerated.

## A-PS-63: why a test that was not false was changed

A-PS-63 never names FIENX, and nothing in it became false. It was changed because the swap
emptied it. Its exclusion check computes the expected set from live data; with FIENX in the
default menu that set held at least FIENX. With EFA it is empty, and an empty expected set is
matched by a page that shows no exclusion list.

This was measured on a local stand-in for production (the real service over the fixture store,
the real page, a scratch proxy in place of the Worker; production was not contacted). The young
fund of the dry run was TSP-S, whose record was shortened for it.

| Page under test | Unedited A-PS-63 | Edited A-PS-63 |
|---|---|---|
| Settings list without the `excluded-note` test id (the run branch before PR #83) | passes | fails: nothing listed (measured with the first form of the edit: expected "TSP-S", received "") |
| Settings list that shows young funds and hides funds that are not served | not run; its expected set is empty | fails: expected "FIENX,TSP-S", received "TSP-S" |
| Settings list as on the run branch now | passes | passes |

The Settings fix (PR #83) has since been merged into the run branch, so the first row is no
longer an open defect; it is kept here as the reason for the change. The change is its own
commit, so it can be reverted alone if the owner prefers the narrower reading of "change only
what the swap makes false".

## What could not be run

A-PS-56 and A-PS-63 run against production and were not run there. What was done instead:

- Both files collect; without the gate secret each fails naming the secret and sends nothing.
- The embedded A-PS-63 Playwright spec lists its three tests and type-checks under `tsc --strict`.
- A-PS-56: all four tests pass on the local stand-in, both when the FIENX menu has to be built
  (202, then 200 after 18 s) and when it is already stored (200 at once).
- A-PS-63: all three tests pass on the local stand-in.

The stand-in differs from production in ways these tests can see: the fixture catalog has no fund
younger than the 10y threshold (hence the shortened TSP-S record), reads were marked as R2 reads
by the proxy, and the limits of the real Worker and Cloudflare rules were not in play. In
production both tests need FIENX to be in the catalog (it is a tier 2 symbol, so the nightly
keeps an entry for it) and A-PS-56 needs its reason to read exactly as the old test required.

## Where excluded-fund handling is still tested with built data

| Layer | Test | Case |
|---|---|---|
| Catalog | `tests/data/test_download.py::test_a_fund_whose_data_ended_is_not_served_and_the_universe_says_why` | FIENX in the real tier 2 list, data ended: not served, reason from the universe note |
| Catalog | `tests/data/test_manifest.py`, `tests/data/test_universe.py` | FIENX status and reason; FIENX is tier 2, EFA tier 1 |
| Engine | `tests/engine/test_builder.py::test_a_fund_the_catalog_does_not_serve_is_set_aside_with_its_reason` | 23 funds plus FIENX: listed with the reason, absent from every vector, numbers equal to the 23-fund build |
| Engine | `tests/engine/test_builder.py` caps tests | A cap on a set-aside fund is hashed and validated, not resolved |
| Build CLI | `tests/engine/test_build_cli.py::test_a_menu_with_the_converted_fund_sets_it_aside_in_every_view` | A returns file that marks FIENX as not served: 5y, recent-weighted, 10y, 1y |
| Build CLI | `tests/engine/test_build_cli.py::test_an_earlier_day_sets_young_funds_aside_in_the_ten_year_view` | The fixture itself on 2020-12-31: VTIP and VWOB too young for 10y, DBJP inside the allowance |
| Service | `tests/api/test_routes.py`, `tests/jobs/test_build.py`, `tests/jobs/test_nightly.py` | The fixture store keeps FIENX as an unavailable catalog symbol; a menu holding it builds with FIENX set aside |
| Gate | A-PS-22 (unchanged), A-PS-43, A-PS-56, A-PS-63 | As above |

## Preset display name

Date: 2026-10-13. Owner's instruction, verbatim: "We must change the default portfolio name to
'Example Portfolio'".

A second sanctioned edit of the frozen gate. The default preset is displayed as
`Example Portfolio`; before, it was `The 2017 guide portfolio`. The preset id `guide2017`, the
holdings file `data/holdings/holdings_guide2017_step2.csv`, the fixture file name
`web/fixtures/guide2017_5y.json`, the URL value `u=guide2017` and the universe hash are unchanged.
The gate was not re-frozen here.

Product: `data/presets.json` (the `name` of `guide2017`) and `scripts/make_fixtures.py` (the
universe name written into the fixture's metadata). Both fixtures were regenerated with the pinned
commands, not edited. In `tests/fixtures/synthetic_23.parquet` the returns are equal to before and
only the metadata name differs. In `web/fixtures/guide2017_5y.json` only `universe.name`,
`built_at` and `build_seconds` differ.

Ids, commands, timeouts and claim texts in `manifest.yaml` are unchanged: no claim names the
preset.

| Gate file | Assertion, leg | Before | After | Why the new form is not weaker |
|---|---|---|---|---|
| `tests/test_a_ps_31_presets_health_bodies.py` line 571 | A-PS-31, first preset of `GET /v1/presets` | `assert first["name"] == "The 2017 guide portfolio"` | `assert first["name"] == "Example Portfolio"` | Exact string equality before and after. The neighbouring legs (ids in order, names equal to `data/presets.json`, 23 funds, allocation) are untouched. |
| `tests/test_a_ps_43_default_view_presets.py` line 1 | A-PS-43, module docstring (title) | "the default view is the 2017 guide portfolio with its allocation" | "the default view is the Example Portfolio with its allocation" | Text only; no assertion changed. Kept equal to the title in the assertions file. |
| `INTERFACES.md` "Encoding decisions" | The EFA entry | "the one sanctioned change of the frozen gate in this run" | "the first sanctioned change of the frozen gate in this run" | Text only. |
| `INTERFACES.md` "Encoding decisions" | New entry | (none) | One entry recording this decision and the A-PS-31 leg | Addition only. |
| `docs/specs/2026-10-13-portfoliosight-demo-design.assertions.md` | A-PS-31, Observation | name `"The 2017 guide portfolio"` | name `"Example Portfolio"` | Same exact-name observation. |
| same | A-PS-43, title (index and section heading) | "the default view is the 2017 guide portfolio with its allocation" | "the default view is the Example Portfolio with its allocation" | Text only. |

### Left as they are, on purpose

- A-PS-39 and A-PS-40: their mock presets body names the first preset
  `PRESETS-MARKER The 2017 guide portfolio`. The tests look for the marker, not the name. Nothing
  in them became false.
- A-PS-41, 42, 43, 44, 45, 46: the mock uses `tensor.universe.name` and falls back to the old
  name only if the fixture has none. The regenerated fixture carries `Example Portfolio`, so the
  mock serves the new name and the fallback is not reached.
- A-PS-47, 48, 49, 50, 51, 53: the mock presets body names the first preset
  `The 2017 guide portfolio`. These tests compare the page with their own mock and assert nothing
  about the name's wording. Nothing in them became false.
- A-PS-43 line 451, the message "the 2017 guide Step 2 holdings file lists 23 funds": it names
  the holdings file's origin, which is unchanged.
- Every `guide2017` in the gate (ids, file names, URL values): unchanged.
- `.frozen`: not regenerated.

Production-only assertions were not run against production. A-PS-56 reads `/api/presets` there
and does not assert the display name.
