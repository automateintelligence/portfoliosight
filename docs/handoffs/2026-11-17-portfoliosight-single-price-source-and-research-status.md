# Status note, 2026-11-17: single price source, research PR B, link setting

Session: [PS] RESEARCH: Finish diversification 2 -devbox. Parked at Marshal's wind-down (usage 68%). Every branch below is pushed; no worktree of this session has uncommitted work. Nothing was merged or deployed after the checkpoint below.

## Checkpoint merged to main today (owner's word)

#204 (smoke suite), #202 (failing tests), #207 (pyright 0 errors), #205 (research PR A), #206 (No allocation limits checkbox, wording). Main after them: `d61dc06`; docs since: `80aa189` (spec), `c89adc3` (plan). Python 2110 passed; web 648 passed; lint and pyright clean. **Not deployed.** Two locked checks fail on main: A-PS-36 (fixed by #212) and A-PS-25/A-PS-65 (suite runtime over their 1000 s / 1200 s limits, see below).

## Open PRs

| PR | Repo | What | State | Needs |
|---|---|---|---|---|
| #212 | portfoliosight | `nl` added to the link contract (spec 8.1, locked A-PS-36, A-PS-51 one token) | ready | merge; then decision 13 (`p` key) |
| #211 | portfoliosight | P1: funds.json, requested.txt (26 owner tickers), QSE fetch-list export (629 / 273 new) | ready | merge; owner glance at 26 hand-typed names in the PR body |
| #208 | portfoliosight | Retry-After on 429; page counts down and retries once | ready except the suite-time checks | merge |
| #210 | portfoliosight | Research PR B, model-side gates | stopped at 3 Codex rounds (3 P1 open) | decision 4 (fourth round with the allow-list fix) and 6 (empty comparison) |
| #209 | portfoliosight | `nl` out of the link | closed, superseded by #212 | decision 14 (delete its worktree and branch) |
| #184 | quant-scenario-engine | Q1: missing core list stops the run; 629-symbol fetch list with one allow-list reader | 3 rounds, round 3 P1s are two read-only readers | decisions 11, 12 |
| #183 | quant-scenario-engine | Q2: start or rebuild a symbol from the lake's own files; load new symbols | 3 rounds, 2 P1 open; structural fix written in the PR body, Codex design attack done (extends, does not overturn; split guard overturned) | decisions 9, 10 |
| #182 | quant-scenario-engine | G0: Schwab probe script | 3 rounds, round 3 fixes unreviewed | decision 5 (strip automatic conclusions) |
| #181 | quant-scenario-engine | Lake and EODHD archive to R2 | parked as draft by the owner | later |

Merge order when approved: #212, then #211, then #208 (portfoliosight); #184 before #183 in QSE (one-line import conflict in `scripts/daily_pipeline.py` near line 65 for whichever goes second); #182 any time after decision 5. Then deploy main (owner) and run the live smoke.

## Decisions for Jeff

1. **D3, locked checks:** may A-PS-02, 03, 04, 06, 07, 10, 14, 30, 59 be updated to the new single-price-source rules (10-trading-day served rule, nightly fetches no prices, Tiingo code removed)? Recommended y. Without it, S3, S4, S8, F1, F10, M2, M5 of the spec's expectations are not met. Plan tasks P2.9, P4, P5 are BLOCKED-D3.
2. **Deploy** main after #212 merges, then the live smoke. Recommended y.
3. **QSE Step 2 frozen copy** on the laptop (needs Jeff at the laptop). It gates the load of new funds (plan O4).
4. **#210:** a fourth Codex round using the structural fix in its PR body (validate every input row against one finite-value allow-list before any computation; explicit "no pool row" count instead of `-inf`). Recommended y.
5. **#182:** strip the automatic conclusions; the probe saves raw answers and prints tables, conclusions written by hand. Recommended y. Also: no yfinance price comparison in the probe (recommended).
6. **#210 reading 4:** check (b) with no comparable pool row: a, pass and list it, as the approved plan says (recommended); b, stop the run.
9. **#183 scope:** a, only the new load/build paths with one complete validator over every input of those paths, existing daily-path weaknesses filed as a separate QSE issue (recommended); b, rework the daily path too (touches what Step 2 reads).
10. **Missing splits:** the 40% guard is dropped (Schwab history is already split-adjusted, so it cannot see a split). a, rely on the Schwab vs yfinance price comparison at load, test it on real past splits, state the limit (recommended); b, find a second split source.
11. **#184 follow-up:** route the dataset-build loader and `refetch_eodhd_fundamentals.py` through the shared list reader. Recommended y.
12. **#184 overlap:** a ticker on both QSE lists stays allowed and fetched once (recommended), or refuses the file.
13. **`p` key:** add the file-prices key to A-PS-36 / A-PS-51 key lists with priced test states (second locked-check change). Recommended y, own PR.
14. **Delete #209's worktree and branch** (superseded). Recommended y.
15. **Suite time vs A-PS-25 / A-PS-65:** the suite takes about 1380 s on an idle devbox; the 40 slowest tests are 730 s (research 454, engine 164, nightly 94). Options: A-PS-25 runs only engine-covering tests (locked change), make the slow research tests smaller, or raise the limits (locked change). No change made.

## Owner steps on the laptop (plan `docs/plans/2026-11-17-single-price-source-plan.md`, O1-O10)

- O1, Schwab probe (after decision 5). Do not run the 06:45 snapshot at exactly 06:45: it competes with the lake job.
- O2, two healthchecks.io checks (`QSE_LAKE_HC_URL`, `PS_SYNC_HC_URL`); confirm `QSE_SCHWAB_HC_URL`.
- O4, load new funds: only after the QSE Step 2 session confirms its snapshot.

## Facts established today

- EODHD Fundamentals paused until 2027-01-16 (API 403); options (UnicornBay) still 200. EODHD dividends and splits were already refused before the pause.
- R2 holds no lake copy; the laptop and the /mnt/d USB drive are the only copies (owner: enough for now).
- FCX and TSM are `seed`/`pending` in R2 (lake check stale since 2026-10-15 and 2026-03-27); WMT is served; the other 26 requested tickers are absent.
- Live limiter enforces 5 tensor POSTs a minute per IP (6th refused, verified).

## Not this session's

`.worktrees/v3-review-fixes` (branch `fix/v3-review-fixes`) has 23 uncommitted files from an earlier session, including locked-check edits. Untouched; owner to decide.
