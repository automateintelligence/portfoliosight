# Handoff: fixed-risk optimization experiment (v2), run in progress

Written 2026-10-24 04:30 PDT. The owner is Jeff. Use plain language with him, ask questions as
a/b/c choices, and state the consequences of each choice.

## Goal
Run the v2 fixed-risk experiment to a finished results report. The protocol is
`docs/plans/2026-10-21-fixed-risk-optimization-experiment-protocol.md` on main: revision 6 plus
§11 Amendment 1, commit `5b913e1`. §11 also lists the run overrides the report must state.

## Where things are
- **Code:** branch `feature/fixed-risk-experiment`, worktree
  `/home/danie906/programming/portfoliosight/.worktrees/return-optimization-experiment`, remote
  `github`. Package `portfoliosight/research/fixedrisk/`. The CLI is
  `python -m portfoliosight.research.fixedrisk.cli {parent,run,status,estimate}`. The report is
  `portfoliosight/research/fixedrisk/report.py`. The branch is not merged to main, so do not
  delete the `fr/*` worktrees.
- **Snapshot:** `/home/danie906/portfoliosight-research/snapshots/2026-10-16-b0ef68baceaa`. A copy is
  on KS-002 at `~/fr-experiment/snapshots/` (ssh host `KS-002-jeff`; repo at `~/fr-experiment/repo`
  with a `GIT_HEAD` file; venv at `~/fr-experiment/venv`).
- **Live run:** `/home/danie906/portfoliosight-research/fr-run-v2b`. Parent digest `15ef77ea…` at
  commit `ddcfad8`. The KS-002 copy is `~/fr-experiment/runs/fr-run-v2b`.
  `/home/danie906/portfoliosight-research/fr-run-v2` is an abandoned first attempt (budget too low).
  Keep it and do not use it.
- **Gate results:** `~/portfoliosight-research/fr-gates/gates_{replay,garch}.json`. Both engines
  chose COBYLA-768.

## Job status (4 jobs, one parent)
| Job | Host | Status |
|---|---|---|
| tsp_replay | KS-002 | complete, 244/244, 0 failures, 8.0 CPU-h; pulled back locally |
| research2003_replay | local, 10 workers | running; 199/246 at 04:14 PDT, 0 failures, 204 CPU-h of the 300 h override budget; expected done about 08:00 PDT |
| tsp_garch | KS-002 | first run complete but **superseded** by Amendment 1; must rerun |
| research2003_garch | local | not started; runs under Amendment 1 after replay finishes |

The research replay hit its 164.98 CPU-h parent budget at 180/246 and was resumed with
`--cpu-hours-budget 300 --allow-changes-in <4 plumbing files> --override-reason …` (commit
`3e5342d`). The record is in `fr-run-v2b/research2003_replay/overrides.jsonl`. If it stops again,
resume it with the same flags. The command is in that file's `reason`, and the `run --help` flags
are `--cpu-hours-budget`, `--allow-changes-in` and `--override-reason`. A one-shot session cron at
08:17 PDT checks it; that cron dies with the old session.

## In flight when this was written
A background implementation agent (opus) was building Amendment 1 in the worktree:
- GARCH shape fitted on each fund's full history up to the origin;
- the residual pool taken from the fit window's common rows;
- the level still taken from the lookback;
- QSE's constant-volatility fallback accepted on a `fit_failed` fit, and labelled.

It was told not to touch running jobs, to use at most 2 processes, to run only scoped tests, and to
report the exact `git diff --name-only ddcfad8 HEAD` list plus fit-status counts and fit timings.
Check `git log github/feature/fixed-risk-experiment` for its commits. If the work is missing or
partial, redo it from §11 of the protocol.

## Next steps
1. Review the agent's commits. Run scoped tests only (`tests/research/fixedrisk/test_garch_bank.py`,
   `test_gates.py`, `test_driver.py -k "garch or fit"`). The full suite runs only when merging to
   main.
2. Run the **third and last** Codex read-only review on the Amendment 1 diff, and tell Codex not
   to run tests. Two reviews are used. The open findings from round 2, accepted as known
   limitations:
   - the arm wall alarm is per task, not per arm;
   - resume does not detect uncommitted changes.

   Use `codex exec -s read-only "<prompt>" > scratch-file` in the background.
3. **TSP GARCH rerun on KS-002:**
   - Move `~/fr-experiment/runs/fr-run-v2b/tsp_garch` (and the local pulled copy) aside to
     `tsp_garch.superseded-3y`.
   - Run `scripts/ks002_sync.sh push <snapshot>`.
   - Launch detached: `ssh -n … 'setsid nohup … cli run --run-dir ~/fr-experiment/runs/fr-run-v2b
     --menu tsp --engine garch --workers 3 --host-label ks002 --snapshot … --allow-changes-in
     <paths from step 1 plus the 4 plumbing files> --override-reason "Amendment 1 …" … & disown'`.
   - When it finishes, pull it back with `scripts/ks002_sync.sh pull <run> tsp_garch`.
   - The llama-server on KS-002 sometimes takes about 3 cores. When it is idle, 6 workers fit.
4. **research2003 GARCH**, locally after replay completes. Its budget is 537.8 CPU-h and the
   projection is about 490 CPU-h before the longer fits, so roughly 2 days on 10 workers. This
   machine's WSL VM appears host-throttled: a pure-Python loop runs 3–4 times slower than on
   KS-002, so CPU-hours overstate the real work. Watch the budget; the override flag raises it if
   needed. KS-002 can run it instead if the owner prefers.
5. **Report:** run `report.py` against `fr-run-v2b` (`--allow-partial` gives an interim report). It
   refuses foreign or incomplete jobs. State every override listed in §11. Publish the report
   (Artifact) and save it under `docs/reviews/`.
6. Close-out:
   - Update memory.
   - Run worktree cleanup from the main checkout only once the branch is merged.
   - GitHub issue #187 (add the research menu to the GUI) waits for the report.

## Gotchas learned this run
- Launch long jobs detached (`setsid nohup … & disown`; over ssh, use `ssh -n`). Pool workers
  are `multiprocessing.spawn` processes. Their command line lacks the job's text, so `pgrep -f
  fixedrisk` misses them and killing only the parent orphans them.
- A watcher that uses `pgrep -f "<job text>"` matches its own shell. Watch the job's PID or its
  `progress.log` end line (`job … complete|incomplete`) instead.
- Resume refuses any HEAD change outside the paths given in `--allow-changes-in`.
- Budgets are proportional shares of `manifest.CPU_HOURS` (now 760), not the projections
  themselves.
- Claude Code may stop background shells under memory pressure. Do not auto-restart them.

## Owner decisions this run (also in protocol §11 and memory)
- Research menu `research2003` replaces the Example Portfolio for research (2026-10-22).
- (a) Extend the budget on resume rather than rerun.
- (b) Amendment 1, the GARCH fit window and fallback.
- He wants the lookback-choice question (score the forecast distribution out of sample) kept open
  for later.

## Suggested skills
- `superpowers:receiving-code-review`: for the Codex round-3 findings and any GitHub Codex bot
  threads.
- `codex`: the last Codex review (read-only, no tests).
- `superpowers:verification-before-completion`: before reporting a job or the report as done.
- `artifact-design` (via an Artifact quickstart): when publishing the results report.
- `superpowers:finishing-a-development-branch`: when merging `feature/fixed-risk-experiment` after
  the report.
