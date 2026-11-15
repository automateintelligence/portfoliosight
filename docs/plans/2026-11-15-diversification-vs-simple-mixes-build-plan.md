# Simple and diversification-driven recipes check: implementation build plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and run, once, the approved check of whether a simple recipe or a
diversification-driven recipe beats the frontier mix at the same risk on the research2003
portfolio, and write its exploratory report.

**Architecture:** One new module, `portfoliosight/research/fixedrisk/recipes3.py`, in four
layers: build the mixes of a start month from its model inputs; run the model-side gates over
all start months; only then read realized outcomes and assemble the statistics, nine tests and
decision; write one result file. A command `v3-recipes` runs it against the recorded `fr-run-v3`
run. The model side takes no realized-outcome argument, so it cannot read one.

**Tech Stack:** Python 3.12, numpy, pandas, pyarrow, cvxpy with Clarabel, pytest, ruff, pyright.
No new dependency.

**Spec:** `docs/plans/2026-11-11-diversification-vs-simple-mixes.md` ("the protocol"; line
numbers below are of commit `3233583`). The protocol is fixed. This plan implements it and does
not redesign it.

Written 2026-11-15. No code, run or commit was made while writing it.

Names used throughout, as in the protocol: **F** the frontier mix with the weight limits, **U**
the frontier mix with no weight limits, **E** equal weight, **D** the most-diversified mix
under the menu's limits, **D10** the same with a flat 10% limit (described only), **V** the
lowest-volatility mix (dropped, see below). A **cell** is a start month and a risk. A
**setting** is one of the six risk settings 0.10 to 0.85. The **pool** is the run's recorded
table of every mix it evaluated.

## Global constraints

- Owner's answers (protocol lines 541-549): 1a nine tests at 99.44%; 2a D under the menu's
  limits, D10 built and described beside it; 3n V dropped from the report; 4y month-to-month
  turnover and break-even; 5y D's optimizer check against the whole recorded pool; 6a 15%
  exclusion share; D kept.
- Effect of 3n on the protocol text: V is not built as a reported mix and appears in no result
  or report. The minimum-variance program is still solved, because `F(s)` needs it (line 97).
  The protocol's test "the identity of V and the frontier's first node" (line 495) stays as
  the lowest-branch test of `F(s)` (Task A2). Lines 199-207, 293 ("24 for V"), 417, 438-440,
  521-525 (V's grid and comparator) are otherwise not implemented.
- Exploratory only: every result is labelled exploratory; the TSP portfolio is not run (lines
  28-31).
- Tolerances, from the protocol: `1e-6` in annual volatility and model return
  (`optimize.TOL`, optimize.py:25); `2e-6` for U's risk match (line 158); weight distance
  reported at `1e-4` (line 136); failed-cell allowance 1% (line 124); exclusion share 15%
  (line 232).
- Statistics, from the protocol: 10,000 resamples as a module constant, never a flag (lines
  359, 530-531); seed 20261201 (`evidence.BOOTSTRAP_SEED`, evidence.py:83); block 24 for
  one-year outcomes and the worst-years tail, block 60 for five-year outcomes (lines 357-358);
  test level `1 - 0.05/9` (line 373); bars 1.0 pp, return lines -50 bp and -2.5 pp (lines
  378-380); five-year floor 120 usable start months (line 391).
- Realized outcomes are read only after every model-side gate has passed. A stop is reported
  to the owner. It is not fixed in place and the run is not repeated without the owner's word
  (line 537).
- Read-only inputs: run `fr-run-v3`, job `research2003_replay`, snapshot
  `2026-10-16-b0ef68baceaa` (lines 54-59). Nothing in the run folder is replaced.
- Code in `portfoliosight/research/fixedrisk/recipes3.py`, command in `cli.py`, tests in
  `tests/research/fixedrisk/test_recipes3.py` written first (lines 492-493). Scripts in
  `scripts/`, the report in `docs/reviews/`.
- Tests are deterministic (fixed seeds, made-up menus, no data files) and assert on outputs,
  never on source text or timing.
- Checks, from the repository root (README.md:31-32; the repo measures coverage of
  `portfoliosight`, not `services`):
  `ruff check . && ruff format --check . && pyright .` and
  `OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 pytest --cov=portfoliosight --cov-report=term-missing`.
  New code: line coverage above 80%; the gates, labels and decision rules 100%.
- The main checkout's `.venv` has no pytest, ruff or pyright (checked 2026-11-15). Each PR's
  worktree makes its own: `uv venv --python 3.12 .venv && uv pip install --python
  .venv/bin/python -e ".[api,dev]"` (README).
- Every task runs this cycle: write the listed tests; run them and see them fail; implement;
  run them and see them pass; run the checks above; commit. Commit message: files with line
  numbers, then one or two bullets on what was done.
- Every PR: branch and worktree off `main` (remote `github`); the body names the protocol
  sections and this plan's section; the review loop, the local checks (there is no GitHub CI)
  and the bot threads are done before it is called ready; merging is the owner's call. After
  a merge, the next PR starts from a new branch and worktree off `main`.
- No time estimate is given anywhere. Every number below comes from the protocol or the code,
  cited, or is a made-up test input and is marked as one.

## Open issues for the owner

Nothing found blocks the build: every input the protocol names exists (checked 2026-11-15 on
the devbox, model side only: 246 pool files, 246 column files with 1,476 three-year rows, none
missing `w_F` or `w_app_frontier`; the `dr2` column is present and never empty in the
4,029,646 main-pool rows; the 25 equal-weight months and the two U cells of lines 216-224
reproduce from the earlier model-side table). Four decisions remain, and one list of readings.

1. **A run that a gate stops: keep its result file?** A stopped run writes its gate results
   and no outcome. y (recommended): it takes the name `recipes_check.json` and is recorded
   like a finished run, so the stop is on the record; a later run you approve writes
   `recipes_check_2.json`. Cost: the first file name is the stopped one. n: a stopped run
   writes only outside the run folder, unrecorded; the stop then lives in the report alone.
2. **When the full run happens.** a (recommended): after the four code PRs are merged, from
   `main`, so the recorded code commit is on `main` and no code changes after outcomes are
   seen; the report then goes in as a documentation-only commit. Cost: you merge code that
   has met the real data only through the model-side script and a two-month smoke run. b:
   from the last PR's branch once its review is done, with the report inside that PR, as the
   safety check did (#199). Cost: a review fix after the run would change code after outcomes
   were seen.
3. **A model-only dry run before the full run?** The gates read no realized outcome. y
   (recommended): add a `--model-only` switch to `v3-recipes` that runs every gate on all 246
   start months, writes outside the run folder, records nothing and reads no outcome. Its
   result is stated in the PR; a failing gate is reported to you before any code change. Cost:
   one switch and its test (Task D4). n: the gates first meet the real data in the full run,
   and a code error there shows up as a stopped run.
4. **Note five protocol passages that no longer match, as a dated correction?** None changes
   a test. y (recommended): one documentation-only note in the protocol. n: they stay listed
   only here.
   - V passages (lines 199-207, 293, 417, 438-440, 521-525) after answer 3n.
   - Line 90 cites `engine/optimize.py:83-86`; `frontier_point` is at 84-87.
   - Line 485 says "at most 15 mixes" per start month; this plan computes outcomes for up to
     24 weight vectors (6 U, 6 F, 6 arm 1, E, D, D10 and their three comparators).
   - Line 484 says "about 4.1 million main-pool rows"; the main-pool rows number 4,029,646 and
     all recorded rows 4,155,755 (the figure of line 253).
   - Line 488 says the run records CPU seconds "as the other checks do"; the region and
     safety results hold none. This plan records `cpu_seconds` in the result.

Readings this plan takes where the protocol leaves a choice (no decision needed unless you
object):

- `sigma_min`, `sigma_top` and `r` of the limited domain are read from the recorded column
  table (line 70) and govern the exclusion rule, the branches of `F(s)` and the risk
  position. The rebuilt ends are compared with them and the largest gap is reported, not
  gated.
- The 1% failed-cell rule counts cells of the 234 eligible start months, as its denominators
  say (lines 121-123). A failed cell in one of the 12 other scheduled months is listed and
  drops its transitions, and does not count toward the 1%.
- Check (b) is run for D and for D10; a failure of either stops the run (lines 185-187).
- U's risk gap is `|sigma(U) - sigma(w_app_frontier)|` at the cell, failed above `2e-6`.
- The five-year return uses block 60, as `safety3.OUTCOMES["return_5y"]` does (safety3.py:112).
- The break-even costs get the two-sided 95% interval of every described figure (line 366).
- In a smoke run (some start months only) the gates are judged on the chosen months: the
  excluded equal-weight months must equal the listed ones among those chosen.
- `safety3.pass_fail_label` is reused unchanged, but its reason text names 98.75%
  (safety3.py:148); `recipes3` puts its own 99.44% text in place of that one reason.
- `safety3.month_outcomes` returns no turnover or net return (safety3.py:330-343), so those
  columns come from a second call to `realized.monthly_rebalanced` on the same sessions.
- The no-replace file writer `safety3._publish` gets one keyword argument, `stem`, with its
  present value as default, rather than a second copy of that logic (Task D2).

## Review focus

Inputs the protocol implies but its test list (lines 493-504) does not name; each has a test
in the task that owns the code.

1. The recorded column table also holds five-year rows (30 of 1,506 in `fr-run-v3`): only
   the six three-year rows of a month are read; a missing setting is an error (Task A3).
2. Expected returns that tie, so the solver's answer sits inside its risk ceiling: `F(s)`
   still lands on the line within `1e-6` (Task A2).
3. A cell with no pool row at or below its risk: the pool gates pass and the cell is counted,
   no crash (Task B2).
4. A start month with a complete year but fewer than `5 * 252` sessions: its five-year
   outcomes are empty and its one-year outcomes are used (Task C1).
5. A stopped run: the realized-outcome callables are never called (Task D1).

## Files

| File | Change | Responsibility |
|---|---|---|
| `portfoliosight/research/fixedrisk/recipes3.py` | new | mixes, gates, outcomes, statistics, job, result |
| `portfoliosight/research/fixedrisk/cli.py` | modify 1-24, after 310, after 443 | command `v3-recipes` |
| `portfoliosight/research/fixedrisk/safety3.py` | modify 594-611 | `_publish(folder, text, stem=FULL_STEM)` |
| `scripts/fixedrisk_geometry_check.py` | new | model-only geometry table and the pre-registered lists |
| `tests/research/fixedrisk/test_recipes3.py` | new | all tests of `recipes3` and the command |
| `tests/research/fixedrisk/test_geometry_check.py` | new | tests of the script |
| `docs/reviews/2026-11-07-fixed-risk-experiment-v3-report.md` | modify before line 401 | the exploratory section |

Existing code reused, each line range checked against `main` at `3233583`:

| What | Where |
|---|---|
| Frontier programs, one bound per holding | `optimize.MenuPrograms`, optimize.py:57-87 (`min_variance` 81-82, `frontier_point` 84-87, `sigma` 77-79) |
| Move a mix onto a risk line | `optimize.onto_risk`, optimize.py:163-175 |
| Solver with retries, `SolveError` | optimize.py:178-192, 38-39; `cholesky_factor` 52-54 |
| The app's frontier and its last node | `optimize.frontier`, optimize.py:90-136; `caps.greedy_fill`, caps.py:100-114 |
| How `w_app_frontier` was made | `knee.side_frontier_node`, knee.py:67-76 |
| Recorded columns | `driver3.COLUMN_SCHEMA`, driver3.py:74-102; `search3._column_record`, search3.py:419-455; `analysis3.load_tables`, analysis3.py:68-88 |
| Pool file layout and test writer | pool.py:34-56, 59-156, 159-166; `objectives3.FIELDS`, objectives3.py:30-53 (`dr2` at 49) |
| Main-pool read, domain rule, distinct mixes | `region3.read_month_pool` 137-149, `POOL_COLUMNS` 94-95, `in_domain` 152-161, `distinct_mixes` 175-197, `_grid` 389-399 |
| Diversification ratio squared, ENB | `anchors.dr2`, anchors.py:62-64; `torsion.enb`, torsion.py:109-111; `torsion_basis` 70 |
| Cell outcomes | `safety3.month_outcomes` 310-354, `window_outcomes` 219-224, `CELL_COLUMNS` 89-90 |
| Paired statistics and labels | `safety3.Outcome` 96-106, `PassFail` 126-135, `paired` 396-414, `compare` 417-435, `describe` 438-442, `tail_level_mean` 249-254, `pass_fail_label` 445-467 |
| Bootstrap | `evidence.Bootstrap` 208-240, `origin_mean` 258-260, `_point` 307-308, `_count` 311-315 |
| Turnover, rebalances, 10 bp cost | `realized.monthly_rebalanced` 116-142, `rebalance_positions` 75-83, `COST_BP` 27 |
| Analysis record, digest check | `ensemble3._read_record` 71-73, `_write_record` 76-80, `_entry` 83-85, `verified_entry` 106-119 |
| Output rules, no-replace writer | `safety3.check_output` 574-591, `_publish` 594-611, `write_result` 614-632 |
| Job and command to mirror | `safety3.safety_job` 652-727; `cli.cmd_v3_safety` 288-310, parser 433-443, `_v3_inputs` 201-209 |
| Training side of a start month | `data.origin_context`, data.py:303-330; menu limits `menus.RESEARCH2003`, menus.py:19-24 |
| Test helpers | `optimizer_data.synthetic_context` 14-49; test_safety3.py `_values` 464-468, `_pool` 471-482, `_write` 504-507, `_job` 510-526, `_returns` 529-531, `_callables` 534-550, `_command` 942-953; script loading test_gates.py:15-24 |

## PRs and merge order

Four code PRs, merged in this order, then the run, then the report. All four touch
`recipes3.py` and its test file, so they are built one after another, each off `main` after
the one before is merged. Each PR's body names the protocol file with the sections of its
row, and this plan with the section of the same name ("PR A: ..." to "PR D: ...").
Branches: `research/recipes-mixes`, `research/recipes-gates`, `research/recipes-statistics`,
`research/recipes-command`.

| Order | PR | Tasks | Protocol sections covered | Agent model, effort |
|---|---|---|---|---|
| 1 | A: the mixes and the model-side script | A1-A4 | "Inputs, fixed" 52-84; "How each mix is built" 86-170, 193-197, 211-225 | sonnet, xhigh |
| 2 | B: the model-side gates | B1-B4 | failed cells 117-129; reconstruction check 131-141; checks on D 172-191; list gate 227-229; model-side gates 238-273 | opus, high |
| 3 | C: outcomes, statistics, tests, decision | C1-C4 | "Outcomes, per cell" 275-350; "Statistics" 352-368; "Pass/fail tests" 370-402; "Decision rules" 404-418; 15% share 231-236 | opus, high |
| 4 | D: the job, the result file, the command | D1-D3 (D4 if decision 3 is y) | "Output and code" 490-537; "Compute size" 469-488 | opus, high |
| 5 | The run | R1-R4 | all gates, then outcomes | this session |
| 6 | The report (documentation only, one file, straight to `main`) | P1 | line 535; "Limits known in advance" 420-467 | fable, high |

Care needed: nothing runs concurrently (one process, as the region and safety checks). Scoring
care: B2, B3 (gates must fail closed), C3, C4 (labels and decision). State care: D1 (a stopped
run reads no outcome) and D2 (no file replaced, the record updated last). These are the opus
tasks.

---

## PR A: the mixes and the model-side script

Test fixtures used from here on (made-up inputs, defined once at the top of the test file):

- `MENU12 = synthetic_context(funds=12, rows=400, cap=0.4, seed=7)`: 12 holdings, 40% limits.
  At least 11 holdings are needed, or D10's 10% limits cannot sum to 100%.
- `THREE_U`: three uncorrelated holdings, expected returns (0.10, 0.08, 0.01), volatilities
  (0.10, 0.30, 0.02), limits 40% each. Its unlimited top (100% in the first holding) has risk
  0.10; its limited range runs from 0.0726 to 0.1266, so the six settings are 0.0780, 0.0861,
  0.0942, 0.1023, 0.1104, 0.1185 (checked with `MenuPrograms`).
- `THREE_E`: three uncorrelated holdings, expected returns (0.10, 0.02, 0.01), volatilities
  (0.05, 0.30, 0.30), limits 100% each. Equal weight has risk 0.1424; the top has risk 0.05.
- `_recorded(mu_s, cov, lower, upper) -> RC.Recorded`: what the run would have recorded:
  `sigma_min` and `sigma_top` from `MenuPrograms.min_variance` and `greedy_fill`,
  `r_j = sigma_min + a_j (sigma_top - sigma_min)` over `analysis3.RFS`, and
  `w_app_j = knee.side_frontier_node(programs, optimize.frontier(programs), r_j)`, the code
  that made the real rows; `w_f_j` the same weights.

Tests import `recipes3 as RC`. Run a task's tests with
`OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 pytest tests/research/fixedrisk/test_recipes3.py -q -k <name>`.

### Task A1: the most-diversified mix

**Protocol:** "Mix 4, D", lines 164-170; check (a), lines 172-176; D10, lines 193-197.

**Produces:** `most_diversified(sigma: np.ndarray, cov: np.ndarray, hi: np.ndarray) ->
np.ndarray`, raising `optimize.SolveError`. Module constants `TOL = optimize.TOL`,
`D10_CAP = 0.10`.

- [ ] Tests, failing first:
  - `test_most_diversified_reproduces_the_papers_two_examples`: with `hi = 1`: two holdings
    of volatility 0.15 and 0.30 at correlations -0.5, 0.0, 0.5 and 0.9 give
    `np.allclose(w, [2/3, 1/3], atol=1e-3)`; three holdings of equal volatility, correlation
    0.9 between the first two and 0.1 with the third, give
    `np.allclose(w, [0.257, 0.257, 0.486], atol=1e-3)`.
  - `test_most_diversified_keeps_the_limits_and_beats_feasible_mixes`: on `MENU12` with
    `hi = 0.10` and with `hi = 0.40`: `abs(w.sum() - 1) <= 1e-8`, `(w >= -1e-8).all()`,
    `(w <= hi + 1e-8).all()`, and for 200 mixes `x` drawn with
    `np.random.default_rng(0)` and `anchors.project_box_simplex` into the same limits,
    `anchors.dr2(w, sigma, cov) >= anchors.dr2(x, sigma, cov) - 1e-6`.
  - `test_most_diversified_without_a_feasible_mix_is_a_solve_error`: five holdings with
    `hi = 0.10` raise `SolveError`.
- [ ] Implement: variable `y`; minimize `cp.norm(optimize.cholesky_factor(cov) @ y, 2)` (the
  same minimizer as `y' Sigma y`, in the cone form of optimize.py:72-74) subject to
  `sigma @ y == 1`, `y >= 0`, `y <= hi * cp.sum(y)`; solve with
  `optimize.solve_with_retries`; return `y / y.sum()`.
- [ ] Tests pass, checks pass, commit.

### Task A2: the exact-line frontier mix, the exclusion rule, the risk position

**Protocol:** "Exact-line frontier mix with the limits", lines 95-115; exclusion rule, lines
211-213; risk position, lines 72-77; the identity of lines 199-203 as the lowest-branch test.

**Produces:**
- `at_or_above_top(s: float, sigma_top: float) -> bool`: `s >= sigma_top - TOL`.
- `risk_position(s: float, sigma_min: float, sigma_top: float) -> float`.
- `frontier_exact(programs: MenuPrograms, lowest: np.ndarray, top: np.ndarray, s: float,
  sigma_min: float, sigma_top: float) -> np.ndarray | None`: `lowest` when
  `s <= sigma_min + TOL`; `None` when `at_or_above_top(s, sigma_top)`; otherwise
  `programs.frontier_point(s)`, moved with `onto_risk(mix, top, s, programs.cov)` when
  `s - programs.sigma(mix) > TOL`. No retry on the risk gap; `SolveError` propagates.

- [ ] Tests, failing first (`programs` on `MENU12` with its limits, `front =
  optimize.frontier(programs, 8)`, `smin = front.x[0]`, `stop = front.x[-1]`):
  - `test_frontier_exact_inside_matches_the_app_frontier`: for `j` in 1 to 6,
    `abs(programs.sigma(w) - front.x[j]) <= 1e-6` and `abs(programs.mu @ w - front.y[j]) <= 1e-6`.
  - `test_frontier_exact_at_the_minimum_risk_is_the_frontiers_first_node`: for `s` in
    `(smin, smin + 5e-7, smin + 1e-6)`,
    `np.array_equal(RC.frontier_exact(programs, front.w[0], top, s, smin, stop), front.w[0])`,
    and `np.array_equal(programs.min_variance(), front.w[0])`.
  - `test_frontier_exact_at_the_top_is_excluded`: for `s` in
    `(stop - 1e-6, stop - 5e-7, stop, stop + 0.01)` the result is `None` and
    `at_or_above_top` is true; at `s = stop - 2e-6` it is false and
    `abs(programs.sigma(w) - s) <= 1e-6`.
  - `test_frontier_exact_lands_on_the_line_when_expected_returns_tie` (review focus 2): three
    holdings with expected return 0.05 each, covariance `diag(0.01, 0.04, 0.09)`, limits
    100%; at the middle of that menu's own risk range, `s = (smin + stop) / 2`:
    `abs(programs.sigma(w) - s) <= 1e-6` and `abs(programs.mu @ w - 0.05) <= 1e-9`.
  - `test_risk_position`: `risk_position(0.07, 0.05, 0.09) == pytest.approx(0.5)`;
    `risk_position(0.10, 0.05, 0.09) > 1`.
- [ ] Implement, tests pass, checks pass, commit.

### Task A3: one start month's mixes

**Protocol:** "Inputs, fixed", lines 60-71; Mix 1 to Mix 4, lines 143-170; failed cells, lines
117-120 and 127-129; reconstruction check, lines 131-141.

**Produces:**
- `Recorded` (frozen dataclass): `r` (6), `sigma_min`, `sigma_top`, `w_f` (6 x N), `w_app`
  (6 x N).
- `recorded_columns(columns: pd.DataFrame, month: str) -> Recorded`: the month's rows with
  `lookback == C.LOOKBACK`, in `analysis3.RFS` order; `ValueError` unless exactly the six
  settings are there with weights.
- Names `F, F_ARM1, U, E, D, D10 = "F", "F_arm1", "U", "E", "D", "D10"`;
  `COMPARATOR = {U: F, E: "F@E", D: "F@D", D10: "F@D10"}`; `KEPT, EXCLUDED, FAILED =
  "kept", "excluded", "failed"`; `U_TOL = 2e-6`.
- `month_mixes(month: str, mu_s, cov, lower, upper, rec: Recorded) -> pd.DataFrame`, one row
  per mix and cell:

| Column | Meaning |
|---|---|
| `month`, `rf`, `mix` | `rf` is the setting, NaN for E, D, D10 and their comparators |
| `r` | F, arm 1 and U rows: the cell's recorded risk; NaN elsewhere |
| `comparator` | the name of the row it is paired with; None for F, arm 1 and comparator rows |
| `status`, `reason` | kept, excluded or failed, and why |
| `weights` | None when the mix was not built |
| `mu`, `sigma`, `a`, `enb`, `dr2` | model return, model risk, risk position on the recorded `sigma_min` and `sigma_top`, ENB (`torsion.enb`; NaN on `TorsionError`), `anchors.dr2` |
| `risk_gap` | comparator rows: `abs(sigma - sigma(M))`; U: `abs(sigma(U) - sigma(w_app))` |
| `mu_gap` | U: `mu(U) - mu(F)`; E, D, D10: `mu(comparator) - mu(M)` |
| `l1` | L1 distance between the mix and its comparator |
| `breaks_limit` | U only: `not region3.in_domain(w, lower, upper)` |
| `rebuilt_mu_gap`, `rebuilt_sigma_gap`, `rebuilt_l1` | F rows: the rebuilt `F(r)` against the recorded `w_app` |
| `ends_gap` | F rows: the larger gap between the rebuilt and the recorded `sigma_min` and `sigma_top` |

Rows and statuses:
- **F** at each setting: weights `rec.w_app`. Failed, reason "reconstruction", when the
  rebuilt `F(r)` cannot be built or either rebuilt gap is above `1e-6`.
- **F_arm1** at each setting: weights `rec.w_f`, kept (described beside F, line 144).
- **U** at each setting, programs `MenuPrograms(mu_s, cov, zeros, ones)`: excluded when
  `at_or_above_top(r, sigma_top_U)` (no solve); failed on `SolveError`, on `risk_gap >
  U_TOL`, or when the F row of that setting failed; else kept.
- **E** (`1/N` each), **D** (`most_diversified` with `upper`), **D10** (with `D10_CAP`):
  failed when the mix cannot be solved; excluded when `at_or_above_top(sigma(M),
  rec.sigma_top)` (no comparator row); otherwise the comparator `frontier_exact(...,
  sigma(M), rec.sigma_min, rec.sigma_top)` is built: `SolveError` or `risk_gap > TOL` fails
  the mix; else both rows are kept.
- If the limited minimum-variance program raises `SolveError`, every F row, U row and
  comparator of the month is failed.

- [ ] Tests, failing first:
  - `test_month_mixes_reconstructs_the_recorded_frontier_rows`: on `MENU12`, the six F rows
    are kept with `rebuilt_mu_gap <= 1e-6` and `rebuilt_sigma_gap <= 1e-6`.
  - `test_a_recorded_row_off_the_frontier_fails_its_cell_and_u_there`: with `rec.w_app[2]`
    replaced by equal weight, the F row and the U row at `RFS[2]` are failed, the other
    five F rows are kept, and E, D and D10 are kept.
  - `test_equal_weight_and_its_comparator_sit_at_the_same_risk`: on `MENU12`, E's weights
    are all `1/12`; the `F@E` row has `risk_gap <= 1e-6`; E's `mu_gap > 1e-6`; E's `a`
    equals `risk_position(sigma(E), rec.sigma_min, rec.sigma_top)`.
  - `test_a_mix_at_or_above_the_top_is_excluded_without_a_comparator`: on `THREE_E`, E is
    excluded and there is no `F@E` row.
  - `test_u_is_solved_below_the_unlimited_top_and_excluded_at_or_above_it`: on `THREE_U`,
    U's statuses by setting are kept, kept, kept, excluded, excluded, excluded; kept rows
    have `risk_gap <= 2e-6`; excluded rows have no weights.
  - `test_a_u_that_keeps_the_limits_equals_f`: on `MENU12` with limits 100%, every kept U
    row has `mu_gap >= -1e-6`, `l1 <= 1e-4` and `breaks_limit` false.
  - `test_recorded_columns_reads_the_six_three_year_rows` (review focus 1): a table with
    the six `3y` rows and six `5y` rows of another `r` returns the `3y` ones in `RFS`
    order; with one setting removed it raises `ValueError`.
- [ ] Implement, tests pass, checks pass, commit.

### Task A4: the model-side geometry script

**Protocol:** "Model-side check already run", lines 78-84; expected counts, lines 214-225;
"Where E, D and V sit", lines 423-426.

**Files:** `scripts/fixedrisk_geometry_check.py`,
`tests/research/fixedrisk/test_geometry_check.py`. An uncommitted first version from the
session that wrote the protocol may still be at
`/tmp/claude-1001/-home-jeff-programming-portfoliosight/09997f9b-8f47-496a-8fd5-6f0c45ff9a80/scratchpad/geometry_check.py`;
that folder can be cleared at any time, so the script is written from this task, not copied.

**Produces:** in `recipes3`: `E_EXCLUDED` (the 25 months of lines 216-219, in order) and
`U_EXCLUDED = (("2008-09", 0.85), ("2010-08", 0.85))` (lines 223-224). In the script:
- `geometry_row(month, mu_s, cov, lower, upper, rec) -> dict` with `sigma_E`, `a_E`,
  `sigma_top` (recorded), `sigma_top_rebuilt`, `sigma_top_U`, `e_excluded` (bool),
  `u_excluded` (the settings with `at_or_above_top(r, sigma_top_U)`). No solver is called:
  the tops are greedy fills.
- `summary(rows: pd.DataFrame, eligible: Sequence[str]) -> dict` with `e_excluded` (eligible
  months), `e_excluded_other` (other scheduled months), `u_excluded` (month, setting),
  `u_top_below_limited_top` (months), the median and mean of `a_E` over the eligible months
  and the median over all months, and the largest `abs(sigma_top - sigma_top_rebuilt)`.
- `main(argv) -> int`: `--run-dir R --snapshot S [--job research2003_replay] [--out FILE]`;
  prints the summary as JSON; returns 1 when `e_excluded != list(RC.E_EXCLUDED)` or a cell
  of `RC.U_EXCLUDED` is missing. It loads the parent manifest and the snapshot as
  `cli._v3_inputs` does (cli.py:201-209, the digest check included), the columns with
  `analysis3.load_tables`, and each month with `data.origin_context`. It computes no
  realized outcome.

- [ ] Tests, failing first (the script loaded as test_gates.py:15-24 loads its script):
  - `test_geometry_row_flags_equal_weight_above_the_top`: `THREE_E` gives `e_excluded` true.
  - `test_geometry_row_lists_the_settings_above_the_unlimited_top`: `THREE_U` gives
    `u_excluded == [0.55, 0.70, 0.85]`.
  - `test_summary_separates_eligible_months`: a made-up three-row table with an excluded
    eligible month and an excluded other month puts each in its own list.
  - `test_main_fails_when_the_lists_differ`: with the table builder replaced by one that
    returns no excluded month, `main([...]) == 1`.
- [ ] Implement, tests pass, checks pass, commit.
- [ ] **Gate on the real run (model only), stated in the PR.** From the worktree, on the
  devbox:
  `OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 .venv/bin/python scripts/fixedrisk_geometry_check.py --run-dir ~/portfoliosight-research/fr-run-v3 --snapshot ~/portfoliosight-research/snapshots/2026-10-16-b0ef68baceaa --out <scratch>/geometry_check.csv`.
  Expected: exit 0; the 25 months of lines 216-219; the U cells (2008-09, 0.85) and
  (2010-08, 0.85); the five months of line 155 with the unlimited top below the limited
  top; median `a_E` 0.581 over the 234 eligible months and 0.575 over all 246, mean 0.752
  (lines 424-426). **Stop:** any difference is reported to the owner; neither the lists nor
  the code are changed to match.

---

## PR B: the model-side gates

### Task B1: the pool reader with the diversification ratio

**Protocol:** lines 177-186; lines 243-246.

**Produces:**
- `read_month_pool_dr2(path: Path) -> pd.DataFrame`: the rows of `region3.read_month_pool`
  (the same path and the same `lookback`, `seed` and `lam` filters, region3.py:140-145) with
  the columns `(*region3.POOL_COLUMNS, "dr2")`, before any domain filter.
- `allowed_mixes(pool, lower, upper) -> pd.DataFrame`: `region3.in_domain` then
  `region3.distinct_mixes`.

- [ ] Tests, failing first (a pool file written with `PoolBuffer` and `write_pool`, as
  test_safety3.py:471-482 and 510-526 do; values made up):
  - `test_the_extended_reader_reads_the_region_checks_rows_with_dr2`: the file holds a
    main row inside the limits (`dr2` 1.5), a second row with the same weights under
    another setting, a row above an upper limit (`dr2` 9.0), a `5y` row and a row with
    `lam = 0.05`. The reader returns three rows, `"dr2"` is a column, and its `record`
    values equal those of `region3.read_month_pool(path)`.
  - `test_allowed_mixes_drops_rows_outside_the_limits_and_repeats`: `allowed_mixes`
    returns one row, with `dr2 == 1.5`.
- [ ] Implement, tests pass, checks pass, commit.

### Task B2: the pool checks of one start month

**Protocol:** check (b), lines 172-191; U's pool lower bound, lines 243-256; the strict gap
and the tie rule, lines 260-273.

**Produces:** `month_pool_checks(mixes: pd.DataFrame, pool: pd.DataFrame, lower, upper) ->
pd.DataFrame`: `mixes` with four more columns and the tie rule applied:
- `pool_dr2_max`: D rows, the largest `dr2` of `allowed_mixes(pool, lower, upper)`; D10
  rows, the same over the rows within `D10_CAP` on every holding.
- `pool_mu_bound`: kept U rows, the largest `mu` over every row of `pool` with
  `sigma <= r`, no tolerance; `-inf` when there is none.
- `pool_mu_at_risk`: kept E, D, D10 rows, the largest `mu` over the menu-allowed rows with
  `sigma <= sigma(M)`; `-inf` when there is none.
- `tie`: true for a kept E, D or D10 row with `mu_gap <= 1e-6` and
  `pool_mu_at_risk <= mu + 1e-6` (kept, "on the frontier"). With `mu_gap <= 1e-6` and
  `pool_mu_at_risk > mu + 1e-6` the row and its comparator become failed, reason
  "the comparator missed a better recorded mix".

- [ ] Tests, failing first (the `mixes` rows written by hand, values made up):
  - `test_check_b_reads_the_largest_recorded_ratio_in_the_mixes_domain`: on 12 holdings
    with 40% limits, allowed rows with `dr2` 1.2 (every weight at most 10%) and 1.4 (one
    weight 30%) give D 1.4 and D10 1.2.
  - `test_the_u_bound_uses_rows_at_or_below_the_risk_with_no_tolerance`: rows at
    `sigma = r` (`mu` 0.05) and `sigma = r + 1e-9` (`mu` 0.09) give `pool_mu_bound == 0.05`;
    the bound counts a row that breaks an upper limit.
  - `test_a_mix_on_the_frontier_is_a_kept_tie`: E kept, `mu` 0.05, `sigma` 0.10, `mu_gap`
    0.0; pool row `sigma` 0.09, `mu` 0.049: `tie` true, status kept.
  - `test_a_comparator_that_misses_a_better_pool_row_is_a_failed_cell`: the same with a
    pool row `sigma` 0.10, `mu` 0.06: status failed for E and for `F@E`.
  - `test_rows_above_the_risk_or_outside_the_limits_do_not_refute_a_tie`: the better row
    at `sigma` 0.11, or breaking a limit: `tie` true, status kept.
  - `test_a_gap_above_the_tolerance_is_no_tie`: `mu_gap = 2e-6`: `tie` false, status kept,
    whatever the pool holds.
  - `test_a_cell_with_no_pool_row_at_its_risk_passes` (review focus 3): no row with
    `sigma <= r`: `pool_mu_bound == -inf`, no error.
- [ ] Implement, tests pass, checks pass, commit.

### Task B3: the gates across start months

**Protocol:** "Failed cells, one rule", lines 117-129; reconstruction check, lines 131-141;
"List gate", lines 227-229; exclusion counts, lines 211-225 and 231-236; "Model-side gates",
lines 238-273; risk position report, lines 72-77; achieved gap report, line 111.

**Produces:** `gates(cells: pd.DataFrame, eligible: Sequence[str], *, expected=None,
scope: Sequence[str] | None = None) -> dict`. `cells` is every month's `month_pool_checks`
output. `expected` is a pair (E's months, U's cells); `None` means `(E_EXCLUDED,
U_EXCLUDED)`, read when called. Keys:

| Key | Content | Stops the run when |
|---|---|---|
| `reconstruction` | cells checked, failed, share, largest gaps, count with `rebuilt_l1 > 1e-4`, failed list | share above 0.01 |
| `exclusions` | per mix over the eligible months: cells, excluded, share, list; excluded cells of other months listed apart | never |
| `list_gate` | E's excluded eligible months, the expected ones (within `scope` when given), U's expected cells that are missing | the E sets differ, or a U cell is missing |
| `check_b` | D and D10: months checked, months with `dr2 < pool_dr2_max - 1e-6`, smallest margin | any month fails |
| `u_return` | kept U cells with `mu_gap < -1e-6` | any |
| `u_pool_bound` | kept U cells with `mu < pool_mu_bound - 1e-6`; cells without a pool row | any |
| `u_limits` | share of kept U cells with `breaks_limit`; share with `l1 > 1e-4` | never |
| `strict_gap` | E, D, D10: ties kept, ties refuted, count with `l1 < 1e-4` | never (a refuted tie is a failed cell) |
| `failed_cells` | U, E, D, D10 over the eligible months: kept-or-failed cells, failed, share, each with its reason; failures in other months listed apart | share above 0.01 for any mix |
| `risk_gap` | per mix: mean, largest, count above the tolerance | never |
| `risk_position` | E, D, D10: mean, median, 5th and 95th percentile over the eligible and over all scheduled months; months per nearest setting; months at or above the top | never |
| `geometry` | largest `ends_gap` | never |
| `flagged_months` | months with a failed F cell whose E, D, D10 comparators are kept (line 128) | never |
| `stops` | list of `{"gate": name, "detail": ...}` | |

- [ ] Tests, failing first (cells written by a helper `_model_cells(...)`, values made up):
  - `test_reconstruction_stops_above_one_percent`: 200 F cells with 2 failed: no stop;
    with 3 failed: `stops` names "reconstruction".
  - `test_list_gate`: E's excluded eligible months equal to the expected ones pass; one
    more or one fewer stops; U cells that include the expected ones and one more pass; a
    missing one stops; with `scope` set, only the expected months in scope are required.
  - `test_check_b_stops_on_one_month`: `dr2` 1.5 against `pool_dr2_max` 1.5000005 passes;
    against 1.50001 stops, for D and for D10.
  - `test_u_gates`: `mu_gap = -5e-7` passes, `-2e-6` stops; `mu = pool_mu_bound - 5e-7`
    passes, `pool_mu_bound - 2e-6` stops.
  - `test_failed_cells_use_the_kept_cells_of_the_eligible_months`: U with 600 eligible
    cells, 20 excluded: 5 failed (5/580) do not stop and are listed with reasons; 6 failed
    (6/580) stop. A failed cell in a month outside `eligible` is listed apart and does not
    count.
  - `test_a_u_that_keeps_the_limits_is_reported_as_equal_to_f`: cells from `month_mixes`
    on `MENU12` with limits 100%, passed through `month_pool_checks` with a pool of no
    rows: `u_limits == {"breaks_share": 0.0, "l1_above_share": 0.0}` and `u_return` has no
    failure.
  - `test_risk_position_counts_months_at_or_above_the_top`: a month with `a = 1.3` is in
    the "at or above the top" count and in no nearest setting.
- [ ] Implement, tests pass, checks pass, commit.

### Task B4: the model side of a job

**Protocol:** "Model-side gates, before any realized outcome is read", line 238; line 536.

**Produces:** `ModelSide` (frozen dataclass: `cells: pd.DataFrame`, `checks: dict`) and
`model_side(months: Sequence[str], context: Callable[[str], Any], columns: pd.DataFrame,
pool_path: Callable[[str], Path], lower, upper, eligible: Sequence[str], *,
expected=None, restricted: bool = False, progress=None) -> ModelSide`.
`context(month)` returns an object with `mu_s`, `cov` and `origin`. Per month:
`recorded_columns`, `month_mixes`, `read_month_pool_dr2`, `month_pool_checks`; `cells` also
gets an `origin` column from `context(month).origin`; then `gates` (with `scope=months` when
`restricted`). A month without pool rows is allowed. A `ValueError` naming the month when an
allowed pool row lacks a model measure, as safety3.py:696-701. The function has no
realized-outcome argument.

- [ ] Tests, failing first (three made-up months on `MENU12` contexts of seeds 7, 8, 9;
  each pool holds 50 mixes drawn with `project_box_simplex`, scored with their true `mu`,
  `sigma` and `anchors.dr2`):
  - `test_model_side_passes_on_a_consistent_run`: with `expected=((), ())` (these months
    exclude nothing; checked with `MenuPrograms`), `checks["stops"] == []`, and `cells` has
    rows for the three months.
  - `test_the_pre_registered_lists_are_the_default`: without `expected`, `stops` names
    "list gate" (the 25 listed months are not excluded here).
  - `test_an_inflated_recorded_ratio_stops_at_check_b`: one pool row's `dr2` set to 99.0:
    `stops` names "check (b)".
  - `test_model_side_is_deterministic`: two calls give equal `cells`
    (`pd.testing.assert_frame_equal`) and equal `checks`.
- [ ] Implement, tests pass, checks pass, commit.

---

## PR C: outcomes, statistics, tests, decision

### Task C1: the outcomes of one start month

**Protocol:** "Outcomes, per cell", items 1 to 5, lines 277-307; line 348.

**Produces:** `cell_outcomes(mixes: pd.DataFrame, *, menu: str, month: str, origin: Any,
horizon: R.HorizonFn, span: R.SpanFn) -> pd.DataFrame`: one row per row of `mixes` with
`month`, `rf`, `mix`, `comparator`, `status`, `breaks_limit`, `a`, `enb`, `dr2`,
`safety3.CELL_COLUMNS`, and `turnover`, `rebalances`, `turnover_per_rebalance`, `ret_net`.
`CELL_COLUMNS` come from `safety3.month_outcomes` unchanged. The four new columns come from
`realized.monthly_rebalanced` on the horizon's first 252 sessions (cut as realized.py:230-233
cuts them): `.turnover` without cost; `.annual` with `cost_bp=realized.COST_BP`;
`len(realized.rebalance_positions(days))`; their ratio. A row without weights has empty
outcomes.

- [ ] Tests, failing first (two holdings, the returns and days of test_safety3.py:529-550):
  - `test_cell_outcomes_against_direct_computations`: for weights `[0.5, 0.5]` and
    `[1, 0]`: `ret_1y`, `dd_1y`, `turnover` equal `R.monthly_rebalanced(...)`'s `annual`,
    `drawdown`, `turnover`; `ret_net` equals `.annual` at `cost_bp=10.0`;
    `rebalances == len(R.rebalance_positions(days))`;
    `turnover_per_rebalance == turnover / rebalances`.
  - `test_a_one_holding_mix_pays_only_the_funding_cost`: for `[1, 0]`: `turnover == 0.0`
    and `ret_net == pytest.approx((1 - 0.001) * (1 + ret_1y) - 1, abs=1e-12)`.
  - `test_five_year_outcomes_need_every_session` (review focus 4): a month with 1,000
    sessions has `fall_5y` and `ret_5y` NaN and `ret_1y` finite.
  - `test_a_month_without_a_complete_year_has_no_outcome`: 100 sessions: `ret_1y` NaN.
  - `test_a_row_without_weights_keeps_its_place`: an excluded U row comes back with NaN
    outcomes and its `status`.
- [ ] Implement, tests pass, checks pass, commit.

### Task C2: month-to-month transitions

**Protocol:** item 7, lines 326-346.

**Produces:** `transitions(cells: pd.DataFrame, schedule: Sequence[str]) -> pd.DataFrame`
with `month` (the later month), `rf`, `mix`, `t_mix`, `t_comparator`, for U, E, D and D10.
`cells` is the model-side frame (with weights). A transition exists only for two consecutive
months of `schedule` in which the mix and its comparator are both kept.
`t = 0.5 * abs(w_later - w_earlier).sum()`. U's comparator sequence is the recorded F rows.

- [ ] Tests, failing first (cells by hand):
  - `test_transitions_of_a_fixed_recipe_and_a_moving_comparator`: E kept in three
    consecutive months with comparator weights `[.5, .5]`, `[.6, .4]`, `[.6, .4]`: two
    rows, `t_mix` 0.0 and 0.0, `t_comparator` 0.1 and 0.0, on the second and third month.
  - `test_an_excluded_endpoint_drops_the_transition`: E excluded in the second month: no
    E row.
  - `test_a_failed_u_cell_drops_only_its_settings_transitions`: U failed at the second
    month, setting 0.40: the other five settings keep two rows each, 0.40 has none.
  - `test_months_that_are_not_consecutive_in_the_schedule_make_no_transition`.
- [ ] Implement, tests pass, checks pass, commit.

### Task C3: paired statistics and the nine tests

**Protocol:** "Statistics", lines 352-368; "Pass/fail tests", lines 370-402; the 15% share,
lines 231-236; the assembler, lines 517-531; outcomes 3 and 4, lines 289-297.

**Produces:**
- `RESAMPLES = 10_000`; `TEST_LEVEL = 1 - 0.05 / 9`; `EXCLUSION_SHARE = 0.15`;
  `BAR = 0.010`; `TESTED = (U, E, D)`.
- `OUTCOMES: dict[str, safety3.Outcome]`:

| Name | Column | Block | Sign | Return | Tail |
|---|---|---|---|---|---|
| `fall_1y` | `dd_1y` | 24 | comparator minus mix | | |
| `fall_5y` | `fall_5y` | 60 | comparator minus mix | | |
| `tail_fall` | `dd_1y` | 24 | comparator minus mix | | largest |
| `return_1y` | `ret_1y` | 24 | mix minus comparator | yes | |
| `return_5y` | `ret_5y` | 60 | mix minus comparator | yes | |
| `return_net_1y` | `ret_net` | 24 | mix minus comparator | yes | |
| `volatility_1y` | `vol_1y` | 24 | mix minus comparator | | |
| `turnover_1y` | `turnover` | 24 | mix minus comparator | | |
| `turnover_per_rebalance` | `turnover_per_rebalance` | 24 | mix minus comparator | | |

- `TESTS`: T1, T2, T3 for U; T4, T5, T6 for E; T7, T8, T9 for D; in each triple
  `PassFail("fall_1y", 0.010, "return_1y", -0.005, None)`,
  `PassFail("fall_5y", 0.010, "return_5y", -0.025, 120)`,
  `PassFail("tail_fall", 0.010, "return_1y", -0.005, None)`.
- `assemble(cells, transitions, months, *, resamples=RESAMPLES,
  seed=evidence.BOOTSTRAP_SEED) -> dict`. `cells` holds the `cell_outcomes` rows of the
  eligible months; `months` is the whole schedule, the bootstrap index. One
  `evidence.Bootstrap(len(months), blocks=(b,), resamples=resamples, seed=seed)` per block
  length, as safety3.py:493-494. U and F go on the six-settings grid (`region3._grid`); E,
  D, D10 and their comparators on a one-row grid. Only kept rows enter a grid used for a
  paired statistic. Output keys:
  - `cells`: per mix `all`, `kept`, `excluded`, `failed`, `excluded_share` (excluded over
    all one-year cells of the mix, lines 231-232).
  - `mixes`: per mix and outcome, `safety3.compare` against its own comparator (`mean_F`
    is the comparator's mean); for F and F_arm1, `safety3.describe`.
  - `tests`: per test the mix, outcome, bar, difference, `interval_99_44`, start months,
    cells, the return bound and line, `label`, `reason`. Label from
    `safety3.pass_fail_label`, its 98.75% reason replaced by "the 99.44% interval includes
    0". Every test of a mix with `excluded_share > EXCLUSION_SHARE` is inconclusive, reason
    "more than 15% of the mix's cells are excluded", whatever it shows. T1 to T3 also carry
    `limits_protect`: difference at or below `-BAR` and the interval's upper end below 0.
  - `limits_reading`: `answer` "yes, on this history, on that measure" when any of T1 to T3
    carries `limits_protect`, with those measures and U's return difference; else "not
    shown".
  - `excluded`: per mix, over its excluded cells that have weights, the mean `ret_1y`,
    `dd_1y`, `vol_1y`, `sigma` and `a`, and the months; no comparator.
  - `model`: per mix the mean `mu`, `sigma`, `enb`, `dr2` over its kept cells.
  - `rebalances`: minimum, maximum and mean of `rebalances` over the cells.
  - `u_breaks_limit_share`: share of kept U cells with `breaks_limit`.
  - `break_even`, `month_to_month`, `decision`: Task C4.

- [ ] Tests, failing first (cells from a helper `_cells(k, ...)` with constant made-up
  values per mix, as test_safety3.py:132-147 builds its table; `resamples=200` in these
  tests):
  - `test_signs_against_each_mixes_own_comparator`: E falls 0.15 and its comparator 0.20,
    E returns 0.08 and its comparator 0.05, in every month: `fall_1y` difference
    `approx(0.05)`, `return_1y` `approx(0.03)`, `mean_F == approx(0.20)`; U against F
    likewise on the six settings.
  - `test_the_settings_of_a_month_are_averaged_before_the_months`: U's differences set to
    `0.01 * j` by setting `j`, one setting failed in half the months: the difference equals
    the mean over months of each month's mean over its kept settings.
  - `test_excluded_and_failed_cells_enter_no_paired_statistic`: an excluded E row with
    `dd_1y = 0.99` leaves E's `fall_1y` difference unchanged and appears in `excluded`.
  - `test_the_worst_years_rank_each_mix_on_its_own_outcomes`: 30 months, E's three largest
    falls and its comparator's three largest in different months: the `tail_fall`
    difference is the comparator's top-three mean minus E's.
  - `test_the_nine_tests_and_their_bars`: `TESTS` has T1 to T9 on U, U, U, E, E, E, D, D,
    D; every bar is 0.010; the return lines are -0.005, -0.025, -0.005 and the month floors
    None, 120, None in each triple.
  - `test_labels_on_a_table`: E falling 0.02 less than its comparator in every month with
    an equal return is "lead" on T4; falling 0.005 less is "no"; falling 0.02 less with a
    return 0.01 lower is "inconclusive"; over 48 months, falling 0.10 less in the
    first 24 and 0.07 more in the last 24 (mean 0.015, above the bar, interval reaching
    below 0) is "inconclusive" with a reason that contains "99.44%"; no reason anywhere in
    the result contains "98.75". (The exact boundaries of `pass_fail_label` are already
    tested at test_safety3.py:326-353.)
  - `test_the_test_interval_is_99_44_percent`: T4's interval equals `np.percentile` of the
    difference statistic's draws at `[100 * 0.05 / 18, 100 - 100 * 0.05 / 18]`, the draws
    from `evidence.Bootstrap(k, blocks=(24,), resamples=200, seed=evidence.BOOTSTRAP_SEED)`
    (the method of test_safety3.py:401-430).
  - `test_five_year_tests_need_120_usable_start_months`: 119 months with a five-year
    outcome: T5 inconclusive whatever the difference; 120: labelled by the rule.
  - `test_more_than_fifteen_percent_excluded_makes_every_test_of_the_mix_inconclusive`: E
    with 36 of 234 cells excluded: T4, T5, T6 inconclusive with the exclusion reason though
    the differences reach the bar, and `mixes["E"]` still reports them; with 35 of 234 the
    ordinary labels apply.
  - `test_limits_protect`: U falls 0.02 more than F in every cell: T1 is "no" with
    `limits_protect` true and `limits_reading["answer"]` starts with "yes"; with U equal to
    F the answer is "not shown".
  - `test_assemble_is_deterministic`: two calls give equal results.
- [ ] Implement, tests pass, checks pass, commit.

### Task C4: break-even costs and the decision

**Protocol:** item 6, lines 308-325; item 7's second break-even, lines 339-346; "Decision
rules", lines 404-418.

**Produces:**
- `break_even_reading(theta_ret: float | None, theta_t: float | None) -> str`, in this
  order: no value: "undefined"; `abs(theta_t) < 1e-6`: "any" for `theta_ret > 0`, "none" for
  `< 0`, "tie" for `== 0`; `theta_t > 0`: "below" for `theta_ret > 0` (the mix wins below
  `c*`), else "none"; `theta_t < 0`: "above" for `theta_ret < 0` (the mix wins above `c*`),
  else "any".
- In `assemble`: `break_even[mix]` for U, E, D, D10: `theta_ret`, `theta_turnover`,
  `c_star = theta_ret / theta_turnover * 1e4` recomputed in each resample (NaN, so counted
  undefined by `Bootstrap.estimate`, when `abs(theta_turnover) < 1e-6` in that resample),
  its 95% interval, `undefined_resamples`, `reading`, block 24. `month_to_month[mix]`:
  `transitions` (kept count), `mean_mix`, `mean_comparator`, `annual_mix`,
  `annual_comparator` (the means times twelve), `theta_sel` with `interval_95`,
  `c_star_sel = theta_ret / (12 * theta_sel) * 1e4` and its `reading` with
  `12 * theta_sel` in place of `theta_turnover`; transitions indexed on the later month,
  block 24; for U the six settings of a transition averaged first. With no kept transition
  the figures are None and the reading "undefined".
- `decide(labels: Mapping[str, str], u_breaks_limit_share: float | None) -> dict` with
  `rule`, `label`, `leads`. Rule texts, fixed (lines 406-415):
  - "1": "At least one lead among the nine: still not a finding. That one mix and measure
    becomes a candidate for one confirmation on the held-out TSP portfolio, which needs a
    new run and its own spec. The owner decides."
  - "2": "No lead and at least one inconclusive: closed as not provable with this history.
    No further experiment on these start months."
  - "3": 'All nine "no": closed. At the same risk, neither the simple recipes nor the
    most-diversified mix fell less than the frontier mix with the weight limits by the
    bar.' followed by " Removing the limits did not help either." when
    `u_breaks_limit_share >= 0.5`, else by " The limits rarely bound, so the U comparison
    is uninformative."

- [ ] Tests, failing first:
  - `test_break_even_readings` (parametrized, the undefined case first):
    `(0.01, 0.0)` "any"; `(-0.01, 5e-7)` "none"; `(0.0, 0.0)` "tie"; `(0.01, 0.5)`
    "below"; `(0.0, 0.5)` "none"; `(-0.01, 0.5)` "none"; `(-0.01, -0.5)` "above";
    `(0.0, -0.5)` "any"; `(0.01, -0.5)` "any"; `(None, None)` "undefined".
  - `test_break_even_cost_in_basis_points`: E returns 0.01 more and trades 0.5 more than
    its comparator in every month: `c_star == approx(200.0)`, reading "below".
  - `test_break_even_is_undefined_when_the_mixes_trade_the_same`: equal turnover in every
    month: `c_star is None`, `undefined_resamples == resamples`, reading "any" for a
    positive return difference.
  - `test_the_month_to_month_break_even`: return difference 0.012, `theta_sel` 0.05:
    `c_star_sel == approx(200.0)`; `annual_comparator == approx(12 * mean_comparator)`.
  - `test_no_kept_transition_is_undefined_not_an_error`: an empty transitions table (a
    smoke run of two months that are not neighbours): `transitions == 0`, `c_star_sel is
    None`, reading "undefined".
  - `test_decision_rules`: one lead among nine: rule "1" with that test in `leads`; no
    lead and one inconclusive: "2"; nine "no" with share 0.5: "3" and the label contains
    "did not help either"; nine "no" with share 0.49: "3" and the label contains
    "uninformative".
- [ ] Implement, tests pass, checks pass, commit.

---

## PR D: the job, the result file, the command

### Task D1: the job

**Protocol:** "Inputs, fixed", lines 54-59; "Output and code", lines 532-537; "Compute size",
lines 487-488.

**Produces:** `recipes_job(job_dir: Path, parent: Mapping, menu: str, engine: str, horizon,
span, *, context: Callable[[str], Any], bounds, commit: str, analysis_path: Path | None =
None, months: Sequence[str] | None = None, expected=None, progress=None) -> dict`. There is
no `resamples` argument: the job always passes `RESAMPLES`. Order:
1. `ensemble3.verified_entry(job_dir, "analysis", analysis_path)`, as safety3.py:675.
2. Schedule, eligible months and the `months` check as safety3.py:676-683. Scope: the whole
   schedule, or `months` in a smoke run.
3. `columns = analysis3.load_tables(job_dir, parent["digest"])["columns"]`; pool paths from
   `driver3.base_paths` as safety3.py:690.
4. `model = model_side(...)`. If `model.checks["stops"]`: return the body with
   `"status": "stopped"` and no outcome key. `horizon` and `span` are not called.
5. `cell_outcomes` for each eligible month in scope, on that month's rows of `model.cells`
   with their `origin`; `transitions(model.cells, schedule)`;
   `assemble(cells, transitions, schedule)`.
6. Body: `label` "EXPLORATORY", `notice` (the fifth look at the same 234 start months;
   nothing here is a finding), `spec`, `job`, `code_commit`, `parent_digest`,
   `analysis_sha256`, `months`, `months_restricted`, `status` ("complete" or "stopped"),
   `model` (the gates' output), `definitions` (resamples, seed, test level, blocks,
   tolerances, bars, return lines, the expected lists), `cpu_seconds`
   (`time.process_time()` over the job), then the keys of `assemble`.

- [ ] Tests, failing first (a small recorded job in `tmp_path`: the layout of
  test_safety3.py:504-526, but each month's column file holds the six `_recorded` rows of
  a `MENU12` context and its pool the 50 scored mixes of Task B4; two-holding returns
  replaced by 12-holding ones from `np.random.default_rng(3)`):
  - `test_no_outcome_is_read_before_the_analysis_digest_is_recorded`: without the record,
    `ValueError`; the horizon was not called.
  - `test_a_stopped_run_reads_no_outcome` (review focus 5): `expected` left at its default
    (so the list gate fails), `horizon` and `span` raising `AssertionError`: no error,
    `body["status"] == "stopped"`, `body["model"]["stops"][0]["gate"] == "list gate"`,
    `"tests" not in body`.
  - `test_recipes_job_end_to_end` (this and the next three with `expected=((), ())`):
    `status == "complete"`; `body["tests"]` has exactly T1 to T9;
    `body["definitions"]["resamples"] == 10_000`;
    `body["definitions"]["test_level"] == 1 - 0.05 / 9`; `body["decision"]["rule"]` is one
    of "1", "2", "3"; `body["cpu_seconds"] >= 0`.
  - `test_recipes_job_is_deterministic`: two runs are equal once `cpu_seconds` is removed.
  - `test_a_smoke_run_judges_the_gates_on_its_months`: `months=[one month]`:
    `months_restricted` true, `status == "complete"`.
  - `test_five_year_column_rows_are_ignored`: a `5y` row added to one column file changes
    nothing in the result apart from `cpu_seconds`.
- [ ] Implement, tests pass, checks pass, commit.

### Task D2: writing and recording the result

**Protocol:** lines 532-535.

**Produces:** in `safety3`: `_publish(folder: Path, text: str, stem: str = FULL_STEM)`, the
stem used for the temporary and final names; nothing else changes and every test of
`test_safety3.py` passes unchanged. In `recipes3`: `FULL_STEM = "recipes_check"`;
`record_recipes(job_dir, path)`, which sets the `"recipes"` entry of the analysis record
(as safety3.py:564-571); `write_result(run_dir, job_dir, body, out, *, restricted) -> Path`:
`safety3.check_output`, then for a full run `safety3._publish(run_dir / "analysis", text,
stem=FULL_STEM)` and `record_recipes`; for a smoke run an exclusive create of `out`.

- [ ] Tests, failing first:
  - `test_a_full_result_is_recorded_and_never_written_over`: the first full result is
    `analysis/recipes_check.json`, recorded under `"recipes"`
    (`ensemble3.verified_entry(job, "recipes")`); a second is `recipes_check_2.json`, the
    first file's bytes unchanged, the record pointing at the second; every other entry of
    the record is unchanged.
  - `test_a_smoke_result_goes_outside_the_run_folder_unrecorded`: with `restricted=True`
    and `out` in `tmp_path`: the file exists, the record has no `"recipes"` entry; an
    `out` inside the run folder, or an existing `out`, raises `ValueError`.
  - `test_a_full_run_takes_no_output_path`: `ValueError`.
- [ ] Implement, tests pass (including `tests/research/fixedrisk/test_safety3.py`), checks
  pass, commit.

### Task D3: the command

**Protocol:** line 492; lines 530-535.

**Produces:** `cli.cmd_v3_recipes(args) -> int` and the parser entry `v3-recipes` with
`--run-dir`, `--snapshot`, `--job` (default `research2003_replay`), `--analysis`, `--out`,
`--months`, mirroring cli.py:288-310 and 433-443: `safety3.check_output` first, then
`_v3_inputs`, then `recipes3.recipes_job` with
`context=lambda month: data.origin_context(inputs, spec, month)`, `bounds=(spec.lower,
spec.upper)`, `commit=manifest.code_head()`, then `recipes3.write_result`. It prints
`{"out", "status", "stops", "recorded"}` and returns 0 for a complete run, 1 for a stopped
one. The usage block at cli.py:1-24 gains the command.

- [ ] Tests, failing first (`cli._v3_inputs` and `cli.data.origin_context` replaced as
  test_safety3.py:942-953 replaces the inputs):
  - `test_the_command_writes_and_records_a_full_run`: with `RC.E_EXCLUDED` and
    `RC.U_EXCLUDED` set to `()` for the made-up job (`monkeypatch.setattr`): returns 0;
    `recipes_check.json` exists and is the recorded `"recipes"` file.
  - `test_the_command_has_no_resamples_flag`:
    `cli.build_parser().parse_args(["v3-recipes", "--run-dir", "r", "--snapshot", "s",
    "--resamples", "50"])` raises `SystemExit`.
  - `test_a_stopped_run_returns_1_and_writes_its_gate_results`: with the lists left as
    they are (the made-up job excludes none of the 25 months): returns 1; the written file
    has `status == "stopped"`. (If decision 1 is n, this test instead asserts that nothing
    is written in the run folder.)
- [ ] Implement, tests pass, checks pass, commit.

### Task D4 (only if decision 3 is y): the model-only switch

`v3-recipes --model-only --out FILE`: `recipes_job(..., model_only=True)` returns after
step 4 with `status` "model only" and the gates' output; `horizon` and `span` are not called;
the file is written like a smoke run's, outside the run folder, unrecorded.
- [ ] Test `test_model_only_reads_no_outcome_and_records_nothing`: `horizon` and `span`
  raising `AssertionError`; the result has `"model"` and no `"tests"`; the record has no
  `"recipes"` entry. Implement, checks pass, commit.

---

## The run

**Where:** the devbox (12 cores, 47 GB), the machine that holds the run and where the project
memory says future runs go (`portfoliosight-run-locations.md`). Run folder
`~/portfoliosight-research/fr-run-v3`; snapshot
`~/portfoliosight-research/snapshots/2026-10-16-b0ef68baceaa` (the path in the run's
`parent.json`). The worktree the memory names (`.worktrees/return-optimization-experiment`)
no longer exists; the run uses the main checkout and its `.venv`, which has the run's
libraries. No file is copied to or from another machine.

**Size (protocol lines 471-488):** per scheduled start month at most 19 small conic programs
on 19 holdings, about 4,700 in all over 246 months; one read of the 246 pool files (1.2 GB
on disk); outcomes for the 234 eligible months over one and five years; 10,000 resamples per
block length over a 246-month index. One process. No runtime is estimated; the result
records its CPU seconds.

- [ ] **R1, preconditions.** PRs A to D merged by the owner (or decision 2b: PR D's review
  done). In the main checkout: `git pull github main`; `git status --porcelain` prints
  nothing; `git rev-parse HEAD` is the merged commit. Save the SHA-256 of
  `fr-run-v3/research2003_replay/analysis_record.json` and of every file in
  `fr-run-v3/analysis/`. `<run>` and `<snapshot>` below are the two paths above; `<py>` is
  `OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 .venv/bin/python`, run from
  the repository root.
- [ ] **R2, model side on the real run.** Run the geometry script as in Task A4 at this
  commit. If decision 3 is y, also
  `<py> -m portfoliosight.research.fixedrisk.cli v3-recipes --run-dir <run> --snapshot <snapshot> --model-only --out <scratch>/recipes_model.json`.
  **Stop** on exit 1 or any entry in `model.stops`: report the gate and its detail to the
  owner; change nothing.
- [ ] **R3, smoke run.** Two eligible months that exercise both exclusions:
  `<py> -m portfoliosight.research.fixedrisk.cli v3-recipes --run-dir <run> --snapshot <snapshot> --months 2008-09 2009-01 --out <scratch>/recipes_smoke.json`.
  Read only `status`, `model` and `cpu_seconds`, not the outcomes. Expected: exit 0,
  `status` "complete", U excluded at (2008-09, 0.85), E excluded at 2009-01, nothing new in
  the run folder. **Stop** otherwise and report.
- [ ] **R4, the full run.** Same command without `--months` and `--out`, started in the
  background with its output in `<scratch>/recipes_check.log`. The session that starts it
  owns it and checks its exit itself. Exit 0: `fr-run-v3/analysis/recipes_check.json`
  exists, `ensemble3.verified_entry(job_dir, "recipes")` succeeds, the SHA-256 of every
  earlier analysis file is unchanged, and the `"analysis"`, `"ensemble"`, `"region"` and
  `"safety"` record entries are unchanged. Exit 1: the run was stopped by a gate; report
  `model.stops` to the owner. **No rerun, no code change and no reading of outcomes follows a stop without the
  owner's word.** Tolerated failed cells (at or below 1%) are listed in the report.
- [ ] **Collect.** The result stays in the run folder on the devbox, as the region and
  safety results do. Note for the report: the file's SHA-256 from the record, the code
  commit in the result, `cpu_seconds`.

## The report

### Task P1: the exploratory section

**Protocol:** line 535; "Limits known in advance", lines 420-467; "Decision rules", lines
404-418.

**File:** `docs/reviews/2026-11-07-fixed-risk-experiment-v3-report.md`, a new section before
"## Limits stated by the protocol" (line 401), headed
`## EXPLORATORY: simple and diversification-driven recipes (addendum of 2026-11-11)`.
Written by hand from `recipes_check.json`, as the safety section at line 358 was; every
number is copied from the result file, none computed by hand.

- [ ] Content, in this order: the result file's SHA-256 and code commit, and that
  `v3-report` does not regenerate the section; the question in plain words; the decision
  rule that applied and its fixed text; the nine tests in one table (mix, measure,
  difference, 99.44% interval, return bound, label, reason); the weight-limits reading;
  per mix the described figures (one-year and five-year fall and return, worst-years fall,
  realized volatility, net return, turnover per rebalance and the rebalance counts, both
  break-even costs with their readings, month-to-month turnover, model return, risk, risk
  position with both medians, ENB, diversification ratio squared); D10 beside D; arm 1
  beside F; the exclusions (counts, the 25 equal-weight months described on their own, the
  15% share); the gates (reconstruction check, list gate, check (b), U gates, ties, every
  tolerated failed cell with its reason); the limits of lines 420-467, including what a "no"
  does and does not rule out. V does not appear.
- [ ] Follow the project memory `explaining-results-to-owner.md`: state the risk level and
  what each table row and column means, one name per mix throughout, lead with the owner's
  question, define each model term once.
- [ ] Documentation only, one file: commit and push straight to `main`
  (`git push github main`). Update the project memory file
  `fixed-risk-v2-result-and-v3-direction.md` with the outcome.
- [ ] Report to the owner: the decision rule that applied, the nine labels, any stop or
  tolerated failure, and, under rule 1, that a confirmation on the TSP portfolio needs a new
  spec and the owner's decision.
