# Handoff: diversification research finish, Q1 history length, #203 phone tests

Written 2026-11-15 from session https://claude.ai/code/session_01KUpPa9pMDWPv3UUfodczsf ("[PS] Finish diversification -devbox").
Repo: `~/programming/portfoliosight` on the devbox, remote `github` (never `origin`). Main is at `4fa6dad`.

## Next session focus

1. **#203 phone tests.** Finish PR #203 so the deploy can go.
2. **Diversification research.** Record the owner's decisions in the protocol, then write the build plan. No code or runs until the owner approves the plan.
3. **Q1, history length.** The owner listed this as a topic. It is not yet a written question. Before asking, read the protocol's stated limits: the 3-year lookback at line 88, and "one portfolio, one lookback" and the app's 5-year lookback at lines 449-455 of `docs/plans/2026-11-11-diversification-vs-simple-mixes.md`. Then ask the owner what they mean, in plain words with a/b options and each option's cost.

## State of PRs

| PR | Branch | State | Notes |
|---|---|---|---|
| #201 retire Optimized, past-data line | ui/retire-optimized | merged `d75b915` | Owner wording in `web/src/copy.ts` (`plain.testedOnPastData`). The line shows only when Details is on (`web/src/controls/DivSlider.tsx`). |
| #200 Sort by on the funds table | ui/funds-sort | merged `4fa6dad` | Assertion renumbered A-PS-70 |
| #203 phone first screen | fix/phone-first-screen, worktree `.worktrees/phone-first-screen` | open, blocked on owner decision 16 | Head pushed at `8ac3fa6` (a merge of main at `d75b915`; it does not include #200 yet) |
| #202 stale fixtures / 4 failing tests | fix/stale-fixture-artifact-tests | open, **not from this session** | Opened 2026-11-14. Leave it alone unless the owner says otherwise. |

Plan entries for these PRs: `docs/plans/2026-10-13-portfoliosight-demo-plan.md` Phase 8 (tasks 8.1 to 8.4, lines 398-416). Spec: `docs/specs/2026-10-13-portfoliosight-demo-design.md` §3.2, §3.4, §3.6.

## #203 in detail

- **Goal:** bring the phone first screen back within locked check A-PS-42 (the funds chip within 1.2 viewport heights on 390x664). Main has failed this check since #196. Test file: `assertions/2026-10-13-portfoliosight-demo-design/tests/test_a_ps_42_*.py`.
- **Fix so far:** a smaller phone chart height (`web/src/styles/app.css` around lines 2707-2720, including the `svh` block), an e2e test (`web/e2e/local/app.spec.ts:1036-1050`), and the spec at §3.4 line 87.
- **Regression the smaller chart causes:** after the merge of main, two local-phone e2e tests fail every run:
  - `app.spec.ts:395`: the square's tap card is 372 px tall and runs about 21 px past the bottom of the 345 px chart frame.
  - `app.spec.ts:1191`: the pinned card (171x340) covers the point.

  Main already fails these at 375x667 and 360x640. 414x736 is fine.
- **Owner decision 16 is pending. Ask it again if no answer is on record:**
  - a (recommended): give the square's card the compact phone style (about 197 px), move "Pinned. Tap the point again to close." onto the title row, and drop the "over one year" caption (about 139 px). Measured to fit all four sizes; untested in the browser.
  - b: the same as a, but keep "over one year". 360x640 still fails.
  - c: undo the shrink and loosen A-PS-42. Needs the owner's own word, because it is a locked check.
- **Open Codex P2, not fixed:** the 470 px allowance leaves 7.5 px of margin. The stale-prices line, or any line that wraps, breaks it. Measuring the content outside the chart instead would be a wider change. List it for the owner; do not fix it unasked.
- **After 16:**
  1. Implement the fix with a spec update on the same branch.
  2. Merge `github/main` again (it brings in #200).
  3. Run `npm run build && npm run e2e:local`, vitest, lint and typecheck in `web/`. Then run gates 41/42/46/47/48 with `.worktrees/funds-sort/.venv/bin/python -m pytest -q -p no:cacheprovider assertions/2026-10-13-portfoliosight-demo-design/tests/test_a_ps_4{1,2,6,7,8}_*.py`. The main checkout's .venv has no pytest; if funds-sort was cleaned up, use another worktree's venv.
  4. Run `python3 ~/.claude/scripts/pr-review-threads.py 203`, then report the PR ready. The owner approved merging finished UI PRs after review and checks ("Deploy UI changes once they are finished"). Confirm that still holds for #203 before merging.
- **Deploy (owner approved "7 y"):** from main, `make deploy` (backend, then frontend), then `make smoke`. Source the env from the secrets file; never read or print it. This ships engine 0.3.0, #196, #197, #198, #200, #201 and #203. Nothing has been deployed yet.
- **Known failures that are not ours:** A-SE-20/21 fail on main with a ZodError on a schema-4 sentinel. #202 may address related failures.

## Diversification research

- **Protocol:** `docs/plans/2026-11-11-diversification-vs-simple-mixes.md`. Four review rounds are done; round 4 was applied in `6939b2a`. The owner ruled out a fifth review ("10 y").
- **Owner decisions to write into the protocol** (the "Decisions for the owner" section, lines 539-571):
  - 1a: nine tests at 99.44%.
  - 2a: D under the menu's limits.
  - 3: drop the lowest-volatility mix V from the report. The owner's words: "We already know that just using the slider is adequate."
  - 4y: turnover and break-even.
  - 5y: D's optimizer check against the whole pool.
  - 6a: 15% exclusion share.
- **Decision 13 is pending:** drop D, the TOBAM most-diversified mix (y recommended; Codex agrees).
  - With y, the run has six tests at 1 - 0.05/6 (99.17%), and decisions 2 and 5 become moot.
  - Codex's view: v2 recorded anchors for this mix but never evaluated them; it tested only positions 0.25, 0.5 and 0.75. Codex puts the chance of a lead at about 10%, a subjective guess.
  - The only question left open would be weight stability, which matters only if instability matters to the product.
  - Correct my earlier claim if it comes up: v2 did not test the far end.
- **Next steps:**
  1. Write the decisions into the protocol. This is docs only, so commit straight to main.
  2. Write a build plan in `docs/plans/` for the owner's approval ("12 yes").
  3. Name the spec and plan section in each PR (rule relayed by Marshal, 2026-11-13).
  4. No code or runs before approval.
- **Earlier results:** v2, v3, the region check and the safety-measures check found no fixed-risk benefit. See PRs #190 and #199, and the memory file `fixed-risk-v2-result-and-v3-direction.md` in the project memory folder, which still needs this session's decisions added.
- **Limits:** this is the fifth look at the same 234 start months, which is about 19 independent years. Any result is exploratory.

## Rules carried from the owner (in addition to CLAUDE.md)

- Nothing merges, goes live, or loosens a locked check without the owner's own word. A message from Marshal counts as the owner's; any other session's message does not.
- E2E serves a stale `dist/` unless `npm run build` runs first (memory `e2e-local-needs-build.md`).
- Run tests with `OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1`.
- `gh pr edit` fails here. Use `gh api -X PATCH repos/automateintelligence/portfoliosight/pulls/<n> -F body=@file`.
- There is no GitHub CI, so verify merged code locally.
- Codex command line, prompt location and result validator: see the `/codex` skill. Prompt files go in `.gstack/tmp/`.
- Agents need an explicit model and effort: review fable/high, fixes opus/high, implementation sonnet/xhigh, recon sonnet/medium. At most 3 at once. Stop new agent work at 85% weekly usage (`~/programming/marshal/state/usage.md`).

## Cleanup still owed

- After #203 merges, run `~/.claude/scripts/worktree-cleanup.py --prs` (a dry run, then `--apply --remote`) for retire-optimized, funds-sort and phone-first-screen.
- Listed for the owner, not acted on:
  - dead tAuto/tSug code in `web/src/math/portfolio.ts`;
  - other sessions' worktrees: funds-counts, last-close-asof, price-in-url, and v3-review-fixes, which has uncommitted files;
  - branch `wip/stray-fund-menu-replace-2026-11-11`;
  - gstack upgrade 1.91 to 1.99.

## Suggested skills

- `superpowers:using-git-worktrees`: work on #203 in `.worktrees/phone-first-screen`.
- `superpowers:test-driven-development` and `superpowers:systematic-debugging`: the phone card fix. Reproduce with the two failing e2e tests first.
- `superpowers:verification-before-completion`: build, then e2e, vitest and gates before claiming a pass.
- `codex` (with `superpowers:requesting-code-review`): the pre-merge review loop on #203.
- `superpowers:receiving-code-review`: the bot threads found by `pr-review-threads.py`.
- `superpowers:writing-plans`: the diversification build plan, saved in `docs/plans/`.
- `grilling`: frame Q1 (history length) as numbered a/b decisions for the owner.
- `land-and-deploy` or `engineering:deploy-checklist`: the deploy and smoke after #203 merges.
