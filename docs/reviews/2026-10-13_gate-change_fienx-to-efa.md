# Gate change: FIENX replaced by EFA in the default menu

Date: 2026-10-13. For the owner.

Owner's instruction, verbatim: "Use EFA and update any frozen tests."

This is the one sanctioned edit of the frozen done-gate in this run
(`assertions/2026-10-13-portfoliosight-demo-design/`). The gate was not re-frozen here; the
coordinator re-freezes after review. Until then `conductor gate verify` reports the three test
files and two manifest entries below as changed, and nothing else.

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
| same | A-PS-43, the mock's second menu and its tensor | Same 23 funds as the first; its tensor is the fixture with each excluded reason suffixed `[mock-7f3]` | The 23 funds plus FIENX; its tensor is the fixture with FIENX added to `excluded`, reason `converted to an ETF; no data since 2024-10-30 [mock-7f3]` | The note must come from the tensor that was served | The reason still exists only in the mock, so a constant cannot match. The tensor has the shape the service writes for a menu holding FIENX (shown by `tests/engine/test_builder.py::test_a_fund_the_catalog_does_not_serve_is_set_aside_with_its_reason` and `tests/jobs/test_build.py`). |
| same | A-PS-43, leg 3 | `fund-row-FIENX` has one `excluded-note`; its text is the tensor's reason, optionally followed by ": not used" | No fund row of the default view has an `excluded-note`; there is no `fund-row-FIENX` | A row shows a note exactly when its tensor sets that fund aside | The exact-text check moved to leg 6 unchanged. New here: a note on a fund in use now fails, which the old test never checked. |
| same | A-PS-43, leg 6 | After switching menus, the FIENX note contains the second tensor's reason | After switching: 24 rows; `fund-row-FIENX` has one note; its text contains the second tensor's reason and equals it exactly, optionally followed by ": not used"; it is the only note in any fund row | The note follows the served tensor, not a constant | Same string checks as old legs 3 and 6 together, plus the count. Checked against three hollow variants of the Funds table, each of which fails: no note rendered (fails "fund-row-FIENX must contain an excluded-note"), a hard-coded FIENX reason (fails "must show the second tensor's reason string"), a note on every row (fails "no fund row may carry an excluded-note"). |
| `tests/test_a_ps_56_presets_tensors_from_r2.py` | A-PS-56, default 5y tensor in production | Funds plus excluded are the 23 Step 2 funds; FIENX is in `excluded`, not in funds, with the exact reason | Funds plus excluded are the 23 Step 2 funds (kept); `excluded` is empty; funds are exactly the 23; FIENX is not a Step 2 fund and not in funds | The default tensor is built from the real menu and real data | Stricter for the default: any fund set aside now fails. |
| same | A-PS-56, new test `test_a_menu_holding_fienx_sets_it_aside_with_the_catalog_reason` | (the three FIENX assertions lived in the default-tensor test) | POST the 23 default funds plus FIENX at 5y; accept 200 or 202; poll the tensor URL up to 200 s; in that tensor FIENX is in `excluded`, not in funds, with the exact reason; nothing else is set aside; funds are the 23; every frontier weight vector has 23 entries | Production sets a fund the catalog does not serve aside, with the catalog's reason from real provider data | The same three FIENX assertions, word for word, on a tensor where FIENX really is in the menu, plus three more. Cost: one real build per generation (the key is the same on every run). |
| `manifest.yaml` | Claims of A-PS-43, A-PS-56 | As frozen | Reworded to say the above | Claim text matches the test | Text only. |
| `INTERFACES.md` | "Encoding decisions" | — | One entry recording this decision and the re-anchored assertions | The contract the product is built to | Addition only. |

## Left as they are, on purpose

- A-PS-24: its two `len(universe.funds) == 23` asserts were false with FIENX and are true now.
- A-PS-41, 42, 44, 45, 46: each embeds a copy of the shared helper with an unused constant
  `FIENX_REASON` and a line that suffixes excluded reasons in the mock's second tensor. The
  constant is still a true statement about the catalog; the line now has nothing to suffix. No
  assertion in those files depends on either.
- A-PS-53 (menu size is the included count or included plus excluded) and A-PS-60 (included plus
  excluded is 23): true as written.
- `.frozen`: not regenerated.

## What could not be run

A-PS-56 runs against production and was not run there. What was done instead:

- The file collects; without the gate secret each test fails naming the secret and sends nothing.
- A-PS-56: all four tests pass on the local stand-in, both when the FIENX menu has to be built
  (202, then 200 after 18 s) and when it is already stored (200 at once).

The stand-in (the real service over the fixture store, a scratch proxy in place of the Worker)
differs from production in ways this test can see: reads were marked as R2 reads by the proxy,
and the limits of the real Worker and Cloudflare rules were not in play.

## Where excluded-fund handling is still tested with built data

| Layer | Test | Case |
|---|---|---|
| Catalog | `tests/data/test_download.py::test_a_fund_whose_data_ended_is_not_served_and_the_universe_says_why` | FIENX in the real tier 2 list, data ended: not served, reason from the universe note |
| Catalog | `tests/data/test_manifest.py`, `tests/data/test_universe.py` | FIENX status and reason; FIENX is tier 2, EFA tier 1 |
| Engine | `tests/engine/test_builder.py::test_a_fund_the_catalog_does_not_serve_is_set_aside_with_its_reason` | 23 funds plus FIENX: listed with the reason, absent from every vector, numbers equal to the 23-fund build |
| Engine | `tests/engine/test_builder.py` caps tests | A cap on a set-aside fund is hashed and validated, not resolved |
| Build CLI | `tests/engine/test_build_cli.py::test_a_menu_with_the_converted_fund_sets_it_aside_in_every_view` | A returns file that marks FIENX as not served, 5y, 10y, 1y |
| Build CLI | `tests/engine/test_build_cli.py::test_an_earlier_day_sets_young_funds_aside_in_the_ten_year_view` | The fixture itself on 2020-12-31: VTIP and VWOB too young for 10y, DBJP inside the allowance |
| Service | `tests/api/test_routes.py`, `tests/jobs/test_build.py`, `tests/jobs/test_nightly.py` | The fixture store keeps FIENX as an unavailable catalog symbol; a menu holding it builds with FIENX set aside |
| Gate | A-PS-22 (unchanged), A-PS-43, A-PS-56 | As above |
