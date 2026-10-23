# Return-optimization experiment report: run main

Protocol `docs/plans/2026-10-18-return-optimization-experiment-protocol.md` SHA-256 `d41e4e48ba4984a23814c055707de73fcf015b5663eff4ee4aa5351b746298fc`. Stage 1, state `complete`, code `f63a1e2f5c69ec4a316e3815dce93b0ec4af84be`. Written by `portfoliosight.research.report` from this run directory alone; the numbers are in `summary.json`.

## Read this first

- **Design.** retrospective fixed-menu, as-of-truncated backtest (protocol 4): today's menus and adjusted histories are hindsight choices; not point-in-time investability or a prospective blind trial.
- **Overlapping cohorts.** one realized annual return per origin; monthly cohorts overlap heavily, and risk cells and menus share outcomes; neither cells nor simulated paths are independent historical replications.
- **Tail power.** below 200 disjoint annual intervals, realized q(.025) superiority and calibration are underpowered; no confirmed real-world tail-benefit claim.
- **Intervals.** paired circular moving-block bootstrap over the monthly origin index, block 24 (12 and 36 as sensitivity), 2,000 resamples, seed 20261201; percentile intervals, 99% for the four realized-support endpoints and 95% elsewhere; exploratory below 20 disjoint annual intervals; block resampling cannot create missing regimes or independence. Origin index: 100 origins on the index.
- **Allowance sweep.** the {0, 5, 10} bp allowance sweep is selection-only from pools searched under the 2.5 bp R+D guard (ruling R23), so it understates a search targeted at those caps.
- **Process model.** 1 coordinator (serial preparation, no concurrent compute) + <=6 compute workers.
- **Forecast-error diagnostic.** forecast error = realized annual return of w_R minus its forecast mu_s'w_R; correlated with the paired realized difference R+D - R; a negative sign (R+D helps most where mu_s overshot) is mechanism (a) of protocol 1; a diagnostic, not a gate.
- **Stage 2 and the stability branch.** Stage 2 runs iff the experiment is valid, both menus reach positive conditional-model evidence and no sensitivity disclosure blocks progression (controller ruling 1). A menu that qualifies only through the stability branch therefore cannot authorize Stage 2 under the protocol as written: its cross-seed stability sensitivity is unavailable.
- **Scope of this report.** this report assesses Stage 1 and its sensitivities only; Stage 2 artifacts, if any, are not summarized here and cannot change this Stage 1 verdict; artifact digests come from each manifest.json, which is itself not hashed.
- **Review and authority.** this report claims no review; the manifest records reviews ['Codex (gpt-6-astra, high, read-only) whole-branch review of 6f01f1d..HEAD, 2026-10-19: FIX_FIRST, 6 findings fixed in 980a446..fc74d93', 'Codex (gpt-6-astra, high, read-only) scoped re-review of 980a446..7be4fe1, 2026-10-19: FIX_FIRST, no P0/P1, 4 P2 fixed in bb20c6c..8eba7ac without further review', 'Run 1 stopped at 1322/2970 cells on the 120 s arm ceiling (machine load); amended to 300 s (R31) and restarted from scratch at 57837ad', 'Run 2 (300 s arm ceiling) stopped manually at ~250/2970 cells: host contention inflated CPU 2.7x so the 36 CPU-h ceiling would trip; ceiling amended to 120 CPU-h (R32), restarted from scratch', 'Run 3 stopped by owner request at ~100/2970 cells: ceilings raised again to 240 CPU-h and 600 s per arm (R33) so an unattended run cannot stop; restarted from scratch']. It authorizes no default change, UI design, deployment or publication.
- **Settings.** Deviations from the protocol: none; CPU-hour amendment: False.

Definitions:

- `annual_return`: prod_t(1 + sum_i w_i r_it) - 1 over the 252 horizon days, constant weights
- `max_drawdown`: max_t 1 - W_t / max(1, max_{s<=t} W_s), W_t the wealth after day t
- `volatility`: sqrt(252) * std(ddof=1) of the 252 daily portfolio returns
- `es_25`: mean of the worst ceil(0.025 P) of P annual outcomes (50 of 2,000; 250 of 10,000)
- `utility`: U = k_B B + k_T T + k_G G, k = (0.60, 0.30, 0.10) unless a profile says otherwise
- `dr2`: (sum_i w_i sigma_i)^2 / (w' Sigma w), production estimate_moments, fixed window
- `forecast_error`: realized annual return minus mu_s'w
- `turnover_prev`: 0.5 * L1(w_t - w_previous scheduled origin), same role, ceiling and seed

## Verdict

Experiment: **valid experiment**.

| menu | conditional model | branch | score change | realized | tail power | intervals | sensitivities |
|---|---|---|---|---|---|---|---|
| example | did not meet observed conditional screening criteria | none | inactive/near-inactive at the 2.5 bp primary cap | inconclusive historical evidence | underpowered | exploratory | not assessed: no qualifying branch |
| tsp | did not meet observed conditional screening criteria | none | inactive/near-inactive at the 2.5 bp primary cap | inconclusive historical evidence | underpowered | exploratory | not assessed: no qualifying branch |

Material harm: none.

Confirmed worthwhile benefit (the production-default bar, not the Stage 2 gate): **False**.

**Stage 2 (ENB): skip.** Stage 2 (R+E, ENB) is skipped under the owner's stopping policy (D7): positive conditional-model evidence is not reached in both menus. ENB unevaluated, not ineffective.

- example: Independent replay return gain: pooled mean paired ΔU >= 5 bp (value -2.7779e-05)
- example: Independent replay return gain: test banks with positive mean ΔU >= 4 of 5 (value 1)
- example: Stable gain alternative: median pairwise L1 reduction >= 20% (R+D vs R) (value 0.0425549)
- example: Stable gain alternative: median pairwise L1 reduction >= .02 (value 0.00750508)
- example: Meaningful score change: mean raw DR² gain >= .10 (value 0.0291651)
- example: General stability: share of origins with seed SD of Bad <= .10 x primary volatility >= 95% in x25 (value 0.727273)
- example: General stability: 90th-percentile pairwise weight L1 <= .40 in x25 (value 0.726547)
- example: General stability: share of origins with seed SD of Bad <= .10 x primary volatility >= 95% in x50 (value 0.69697)
- example: General stability: 90th-percentile pairwise weight L1 <= .40 in x50 (value 0.774403)
- example: General stability: share of origins with seed SD of Bad <= .10 x primary volatility >= 95% in x100 (value 0.69697)
- example: General stability: 90th-percentile pairwise weight L1 <= .40 in x100 (value 0.735051)
- example: Cost: p95 warm R arm-search wall <= 30 s per cell (value 65.4169)
- example: Cost: p95 of paired wall(R+D)/wall(R) <= 1.25 (value 1.38166)
- tsp: Independent replay return gain: pooled mean paired ΔU >= 5 bp (value -2.09331e-05)
- tsp: Independent replay return gain: test banks with positive mean ΔU >= 4 of 5 (value 2)
- tsp: Stable gain alternative: median pairwise L1 reduction >= 20% (R+D vs R) (value -0.00302159)
- tsp: Stable gain alternative: median pairwise L1 reduction >= .02 (value -0.000207961)
- tsp: Meaningful score change: mean raw DR² gain >= .10 (value 0.0385576)
- tsp: Meaningful score change: share of cells with L1(R+D, R) >= .02 >= 20% (value 0.175084)
- tsp: General stability: share of origins with seed SD of Bad <= .10 x primary volatility >= 95% in x25 (value 0.444444)
- tsp: General stability: share of origins with seed SD of Bad <= .10 x primary volatility >= 95% in x50 (value 0.434343)
- tsp: General stability: share of origins with seed SD of Bad <= .10 x primary volatility >= 95% in x100 (value 0.434343)
- tsp: Cost: p95 of paired wall(R+D)/wall(R) <= 1.25 (value 2.05814)

## Protocol compliance (separate from scientific support)

| check | result | detail |
|---|---|---|
| stage_1_complete | met | Stage 1 state complete |
| sensitivity_coefficients_complete | met | state complete |
| sensitivity_coefficients_cells | met | every frozen cell completed with its paired arms and exact-weight invariance |
| sensitivity_lookback_complete | met | state complete |
| sensitivity_lookback_cells | met | every frozen cell completed with its paired arms and exact-weight invariance |
| sensitivity_budget_complete | met | state complete |
| sensitivity_budget_cells | met | every frozen cell completed with its paired arms and exact-weight invariance |
| frozen_schedule | met | 0 frozen cells without a row, 0 rows outside the frozen schedule |
| no_incomplete_cells | met | 0 unattempted, interrupted or resource-breach cells |
| no_failed_cells | met | 0 failed of 2970 (training-ineligible excluded: 0); rate 0.0000, 1% line recorded as information; any unresolved failure prevents a valid completed verdict (R25) |
| denominator_agrees_with_manifest | met | the report counts the cells as the runner recorded them |
| coverage_gate | met | every protocol 4 gate met |
| investigation_digest | met | reproduced d6f782a9947c0fad3a8b85f0ff6906160eff4b1e7a9c2de8e270ccd4eeeba24e, expected d6f782a9947c0fad3a8b85f0ff6906160eff4b1e7a9c2de8e270ccd4eeeba24e |
| investigation_ranges | met | the investigation tensor's recorded ranges reproduced within 3.885780586188048e-16 (tolerance 1e-12) over 30 mixes in columns [36, 37] |
| sensitivity_coefficients_provenance | met | same run id, code, settings and snapshot as Stage 1 |
| sensitivity_lookback_provenance | met | same run id, code, settings and snapshot as Stage 1 |
| sensitivity_budget_provenance | met | same run id, code, settings and snapshot as Stage 1 |
| invariance | met | 0 cells break exact-weight invariance |
| paired_arms | met | 0 completed cells lack a paired arm |
| protocol_settings | met | every setting is the protocol's |

Artifacts re-hashed against the manifest: locked.parquet, origins.parquet, outcomes.parquet, resources.jsonl, search.parquet.

Denominator (Stage 1 cells, frozen before any search): 2970; statuses {'ok': 2970}; missing 0; training-ineligible excluded 0; failed 0 of 2970 = 0.0000 (the 0.01 line is information: any unresolved failure prevents a valid completed verdict, R25).

## Panel, coverage and missingness

Origin index: 100 months (2018-06 to 2026-09), 99 scheduled; realized panel (complete in both menus): 87. Ledger month statuses: {'administratively_immature': 12, 'mature': 87, 'origin_price_missing': 1, 'training_ineligible': 60}.

| menu | mature | complete | missing | unexplained | immature | disjoint (own) | disjoint (realized panel) | calendar span |
|---|---|---|---|---|---|---|---|---|
| example | 87 | 87 | 0 | 0 | 12 | 7 | 7 | 2018-06-29 to 2026-10-01 |
| tsp | 87 | 87 | 0 | 0 | 12 | 7 | 7 | 2018-06-29 to 2026-10-05 |

| gate | value | rule | met |
|---|---|---|---|
| scheduled_origins | 99 | <= 120 | True |
| mature_origins | 87 | >= 60 | True |
| example_completeness | 1.0 | >= 95% | True |
| example_unexplained_missing | 0 | = 0 | True |
| example_disjoint_intervals | 7 | >= 5 | True |
| tsp_completeness | 1.0 | >= 95% | True |
| tsp_unexplained_missing | 0 | = 0 | True |
| tsp_disjoint_intervals | 7 | >= 5 | True |

## R against the return-agnostic references (before R+D versus R)

No predeclared threshold applies; R is validated descriptively against each reference first (protocol 6, D3).

### R vs mdp: R minus mdp

Pooled independent test banks (10,000 outcomes), bp, 95% interval at block 24:

ΔU:

| menu | risk cell | mean paired difference |
|---|---|---|
| example | x25 | +210.78 [+115.37, +299.90] (L12 [+137.59, +282.71]; L36 [+110.30, +305.18]; n 99) |
| example | x50 | +436.73 [+284.01, +584.79] (L12 [+321.47, +551.45]; L36 [+282.44, +593.99]; n 99) |
| example | x100 | +860.08 [+603.36, +1114.20] (L12 [+655.98, +1057.75]; L36 [+594.89, +1115.67]; n 99) |
| example | **menu** | +502.53 [+349.84, +660.03] (L12 [+383.48, +622.21]; L36 [+342.77, +666.57]; n 99) |
| tsp | x25 | +284.48 [+209.48, +364.46] (L12 [+220.33, +349.14]; L36 [+209.19, +371.22]; n 99) |
| tsp | x50 | +497.25 [+391.78, +624.78] (L12 [+394.43, +601.18]; L36 [+398.97, +623.18]; n 99) |
| tsp | x100 | +800.42 [+603.60, +1041.24] (L12 [+599.00, +1002.98]; L36 [+621.93, +1029.40]; n 99) |
| tsp | **menu** | +527.38 [+404.48, +677.13] (L12 [+405.29, +650.28]; L36 [+411.42, +676.26]; n 99) |
| 50/50 | aggregate (never decides) | +514.96 [+381.98, +664.50] (L12 [+404.44, +632.56]; L36 [+380.39, +670.30]; n 99) |

ΔB:

| menu | risk cell | mean paired difference |
|---|---|---|
| example | x25 | +443.59 [+299.14, +604.78] (L12 [+315.51, +568.76]; L36 [+304.48, +606.09]; n 99) |
| example | x50 | +1045.71 [+808.51, +1316.23] (L12 [+853.28, +1256.44]; L36 [+797.46, +1319.63]; n 99) |
| example | x100 | +2119.47 [+1520.35, +2677.46] (L12 [+1670.59, +2572.74]; L36 [+1490.78, +2707.71]; n 99) |
| example | **menu** | +1202.93 [+905.08, +1511.82] (L12 [+971.97, +1448.35]; L36 [+883.60, +1527.83]; n 99) |
| tsp | x25 | +663.05 [+517.30, +829.30] (L12 [+533.37, +796.81]; L36 [+518.42, +826.90]; n 99) |
| tsp | x50 | +1297.02 [+1041.53, +1567.86] (L12 [+1074.79, +1516.44]; L36 [+1041.75, +1559.98]; n 99) |
| tsp | x100 | +2397.91 [+1927.28, +2875.83] (L12 [+2011.39, +2786.59]; L36 [+1915.20, +2880.44]; n 99) |
| tsp | **menu** | +1452.66 [+1163.40, +1758.97] (L12 [+1205.10, +1700.04]; L36 [+1159.87, +1753.68]; n 99) |
| 50/50 | aggregate (never decides) | +1327.79 [+1037.70, +1631.30] (L12 [+1092.49, +1567.58]; L36 [+1023.67, +1641.25]; n 99) |

ΔT:

| menu | risk cell | mean paired difference |
|---|---|---|
| example | x25 | -15.81 [-97.90, +82.21] (L12 [-87.59, +65.94]; L36 [-92.95, +74.44]; n 99) |
| example | x50 | -156.61 [-309.62, +2.59] (L12 [-269.87, -25.50]; L36 [-319.93, +12.27]; n 99) |
| example | x100 | -361.27 [-651.52, -98.50] (L12 [-580.52, -141.44]; L36 [-672.46, -80.33]; n 99) |
| example | **menu** | -177.90 [-346.62, -9.07] (L12 [-302.48, -36.60]; L36 [-357.70, +2.47]; n 99) |
| tsp | x25 | -95.59 [-177.02, -8.87] (L12 [-157.22, -21.12]; L36 [-181.27, -4.59]; n 99) |
| tsp | x50 | -291.34 [-438.74, -162.73] (L12 [-401.70, -182.77]; L36 [-437.69, -156.97]; n 99) |
| tsp | x100 | -684.69 [-985.87, -461.51] (L12 [-928.37, -484.72]; L36 [-981.20, -456.50]; n 99) |
| tsp | **menu** | -357.21 [-533.16, -213.43] (L12 [-491.97, -234.64]; L36 [-532.90, -207.08]; n 99) |
| 50/50 | aggregate (never decides) | -267.55 [-437.66, -114.82] (L12 [-391.05, -138.24]; L36 [-445.82, -104.67]; n 99) |

ΔG:

| menu | risk cell | mean paired difference |
|---|---|---|
| example | x25 | -506.28 [-748.76, -270.31] (L12 [-712.14, -282.81]; L36 [-724.31, -303.18]; n 99) |
| example | x50 | -1437.10 [-1806.09, -1023.42] (L12 [-1744.30, -1117.86]; L36 [-1815.53, -1035.45]; n 99) |
| example | x100 | -3032.27 [-3860.72, -2183.67] (L12 [-3696.95, -2364.15]; L36 [-3919.95, -2093.55]; n 99) |
| example | **menu** | -1658.55 [-2112.78, -1172.73] (L12 [-2018.02, -1292.22]; L36 [-2134.24, -1157.99]; n 99) |
| tsp | x25 | -846.72 [-1073.03, -599.88] (L12 [-1031.17, -652.26]; L36 [-1070.16, -604.05]; n 99) |
| tsp | x50 | -1935.60 [-2340.27, -1494.28] (L12 [-2267.35, -1587.56]; L36 [-2359.32, -1466.52]; n 99) |
| tsp | x100 | -4329.16 [-5149.17, -3392.15] (L12 [-4997.96, -3589.55]; L36 [-5198.28, -3333.20]; n 99) |
| tsp | **menu** | -2370.49 [-2845.56, -1847.10] (L12 [-2759.30, -1959.98]; L36 [-2871.87, -1806.82]; n 99) |
| 50/50 | aggregate (never decides) | -2014.52 [-2480.01, -1520.02] (L12 [-2388.28, -1629.59]; L36 [-2502.06, -1486.05]; n 99) |

ΔES_2.5:

| menu | risk cell | mean paired difference |
|---|---|---|
| example | x25 | +518.87 [+358.32, +703.16] (L12 [+368.59, +661.40]; L36 [+369.39, +701.38]; n 99) |
| example | x50 | +1258.08 [+984.31, +1561.30] (L12 [+1034.60, +1503.34]; L36 [+974.05, +1569.65]; n 99) |
| example | x100 | +2523.78 [+1822.81, +3194.90] (L12 [+1979.79, +3065.15]; L36 [+1760.82, +3228.53]; n 99) |
| example | **menu** | +1433.58 [+1084.85, +1795.46] (L12 [+1161.55, +1725.98]; L36 [+1059.24, +1808.53]; n 99) |
| tsp | x25 | +814.07 [+632.04, +1013.86] (L12 [+652.72, +975.65]; L36 [+630.57, +1008.06]; n 99) |
| tsp | x50 | +1594.47 [+1271.08, +1921.21] (L12 [+1323.18, +1861.33]; L36 [+1266.47, +1921.35]; n 99) |
| tsp | x100 | +2899.56 [+2327.21, +3450.04] (L12 [+2439.20, +3349.33]; L36 [+2317.77, +3466.49]; n 99) |
| tsp | **menu** | +1769.36 [+1410.91, +2130.63] (L12 [+1473.82, +2062.53]; L36 [+1405.38, +2132.01]; n 99) |
| 50/50 | aggregate (never decides) | +1601.47 [+1247.49, +1954.89] (L12 [+1322.06, +1890.07]; L36 [+1233.03, +1970.09]; n 99) |

Realized (one annual return per origin, realized mask):

annual return (bp):

| menu | risk cell | mean paired difference |
|---|---|---|
| example | x25 | -46.61 [-231.23, +117.05] (L12 [-204.69, +124.96]; L36 [-221.53, +91.69]; n 87) |
| example | x50 | -209.92 [-613.11, +121.93] (L12 [-543.18, +140.33]; L36 [-621.35, +94.00]; n 87) |
| example | x100 | -520.28 [-1161.31, +42.21] (L12 [-1178.23, +25.12]; L36 [-1142.48, +39.45]; n 87) |
| example | **menu** | -258.94 [-630.29, +72.52] (L12 [-618.29, +70.65]; L36 [-642.73, +27.20]; n 87) |
| tsp | x25 | -191.87 [-416.07, +69.60] (L12 [-452.03, +111.81]; L36 [-399.04, +9.63]; n 87) |
| tsp | x50 | -458.94 [-804.69, -65.15] (L12 [-930.24, +23.92]; L36 [-708.29, -177.57]; n 87) |
| tsp | x100 | -1026.38 [-1731.43, -271.52] (L12 [-2012.93, -99.69]; L36 [-1487.62, -491.51]; n 87) |
| tsp | **menu** | -559.06 [-972.15, -108.67] (L12 [-1117.55, +2.53]; L36 [-856.36, -236.48]; n 87) |
| 50/50 | aggregate (never decides) | -409.00 [-789.51, -64.44] (L12 [-852.73, +0.62]; L36 [-725.99, -143.38]; n 87) |

max-drawdown improvement (bp):

| menu | risk cell | mean paired difference |
|---|---|---|
| example | x25 | +302.04 [+151.79, +445.77] (L12 [+177.33, +438.87]; L36 [+147.10, +436.09]; n 87) |
| example | x50 | +686.68 [+466.60, +879.31] (L12 [+466.64, +896.90]; L36 [+478.59, +857.73]; n 87) |
| example | x100 | +900.75 [+655.19, +1087.01] (L12 [+628.99, +1135.47]; L36 [+725.83, +1082.79]; n 87) |
| example | **menu** | +629.82 [+439.68, +787.78] (L12 [+441.05, +805.25]; L36 [+473.84, +775.32]; n 87) |
| tsp | x25 | +455.61 [+311.58, +580.07] (L12 [+311.93, +603.42]; L36 [+309.30, +568.90]; n 87) |
| tsp | x50 | +842.46 [+647.18, +1039.80] (L12 [+620.13, +1094.57]; L36 [+663.37, +1036.82]; n 87) |
| tsp | x100 | +1529.24 [+1226.23, +1907.81] (L12 [+1168.96, +1945.99]; L36 [+1272.84, +1890.15]; n 87) |
| tsp | **menu** | +942.44 [+740.30, +1161.47] (L12 [+707.66, +1204.98]; L36 [+758.51, +1156.58]; n 87) |
| 50/50 | aggregate (never decides) | +786.13 [+635.45, +904.20] (L12 [+606.43, +969.14]; L36 [+663.10, +875.24]; n 87) |

loss rate (share):

| menu | risk cell | mean paired difference |
|---|---|---|
| example | x25 | -0.0230 [-0.0619, 0.0000] (L12 [-0.0741, 0.0000]; L36 [-0.0515, 0.0000]; n 87) |
| example | x50 | -0.0575 [-0.1546, 0.0000] (L12 [-0.1739, 0.0000]; L36 [-0.1327, 0.0000]; n 87) |
| example | x100 | -0.0460 [-0.0741, -0.0152] (L12 [-0.0889, -0.0112]; L36 [-0.0690, -0.0235]; n 87) |
| example | **menu** | -0.0421 [-0.0941, -0.0052] (L12 [-0.1085, -0.0040]; L36 [-0.0790, -0.0084]; n 87) |
| tsp | x25 | -0.0460 [-0.0920, -0.0101] (L12 [-0.0930, 0.0000]; L36 [-0.0909, 0.0000]; n 87) |
| tsp | x50 | -0.0690 [-0.1294, -0.0105] (L12 [-0.1370, 0.0000]; L36 [-0.1313, 0.0000]; n 87) |
| tsp | x100 | -0.1034 [-0.2025, -0.0421] (L12 [-0.2046, -0.0316]; L36 [-0.1757, -0.0505]; n 87) |
| tsp | **menu** | -0.0728 [-0.1255, -0.0256] (L12 [-0.1315, -0.0202]; L36 [-0.1156, -0.0238]; n 87) |
| 50/50 | aggregate (never decides) | -0.0575 [-0.0955, -0.0250] (L12 [-0.1008, -0.0201]; L36 [-0.0876, -0.0258]; n 87) |

below -20% rate (share):

| menu | risk cell | mean paired difference |
|---|---|---|
| example | x25 | 0.0000 [0.0000, 0.0000] (L12 [0.0000, 0.0000]; L36 [0.0000, 0.0000]; n 87) |
| example | x50 | -0.0345 [-0.0941, 0.0000] (L12 [-0.1035, 0.0000]; L36 [-0.0816, 0.0000]; n 87) |
| example | x100 | 0.0000 [0.0000, 0.0000] (L12 [0.0000, 0.0000]; L36 [0.0000, 0.0000]; n 87) |
| example | **menu** | -0.0115 [-0.0314, 0.0000] (L12 [-0.0345, 0.0000]; L36 [-0.0272, 0.0000]; n 87) |
| tsp | x25 | 0.0000 [0.0000, 0.0000] (L12 [0.0000, 0.0000]; L36 [0.0000, 0.0000]; n 87) |
| tsp | x50 | 0.0000 [0.0000, 0.0000] (L12 [0.0000, 0.0000]; L36 [0.0000, 0.0000]; n 87) |
| tsp | x100 | -0.0345 [-0.0714, 0.0000] (L12 [-0.0864, 0.0000]; L36 [-0.0612, 0.0000]; n 87) |
| tsp | **menu** | -0.0115 [-0.0238, 0.0000] (L12 [-0.0288, 0.0000]; L36 [-0.0204, 0.0000]; n 87) |
| 50/50 | aggregate (never decides) | -0.0115 [-0.0272, 0.0000] (L12 [-0.0312, 0.0000]; L36 [-0.0238, 0.0000]; n 87) |

worst day (bp):

| menu | risk cell | mean paired difference |
|---|---|---|
| example | x25 | +58.10 [+32.81, +80.13] (L12 [+36.45, +77.56]; L36 [+35.01, +79.86]; n 87) |
| example | x50 | +160.05 [+123.93, +184.14] (L12 [+118.08, +196.45]; L36 [+132.51, +178.48]; n 87) |
| example | x100 | +252.78 [+196.87, +311.90] (L12 [+193.93, +318.10]; L36 [+206.77, +302.27]; n 87) |
| example | **menu** | +156.98 [+122.57, +182.22] (L12 [+117.72, +190.53]; L36 [+129.33, +175.02]; n 87) |
| tsp | x25 | +103.49 [+69.08, +147.01] (L12 [+68.46, +147.06]; L36 [+73.22, +144.33]; n 87) |
| tsp | x50 | +206.97 [+144.38, +293.79] (L12 [+139.24, +294.46]; L36 [+150.80, +288.28]; n 87) |
| tsp | x100 | +430.21 [+286.46, +629.90] (L12 [+279.99, +626.27]; L36 [+294.13, +622.84]; n 87) |
| tsp | **menu** | +246.89 [+168.50, +357.23] (L12 [+164.05, +356.09]; L36 [+174.34, +352.12]; n 87) |
| 50/50 | aggregate (never decides) | +201.93 [+150.35, +268.34] (L12 [+144.63, +271.01]; L36 [+159.28, +260.61]; n 87) |

realized volatility (bp):

| menu | risk cell | mean paired difference |
|---|---|---|
| example | x25 | -277.05 [-382.36, -161.70] (L12 [-371.91, -175.87]; L36 [-377.60, -166.01]; n 87) |
| example | x50 | -652.14 [-777.29, -483.50] (L12 [-778.74, -495.97]; L36 [-773.04, -505.17]; n 87) |
| example | x100 | -1103.56 [-1243.22, -882.40] (L12 [-1249.85, -920.96]; L36 [-1242.12, -887.70]; n 87) |
| example | **menu** | -677.58 [-788.05, -512.92] (L12 [-788.23, -536.76]; L36 [-781.87, -523.65]; n 87) |
| tsp | x25 | -375.86 [-450.62, -283.88] (L12 [-465.72, -284.67]; L36 [-434.23, -290.36]; n 87) |
| tsp | x50 | -799.05 [-963.66, -641.54] (L12 [-980.32, -641.95]; L36 [-946.22, -665.99]; n 87) |
| tsp | x100 | -1698.48 [-2040.43, -1386.28] (L12 [-2061.78, -1387.06]; L36 [-2043.36, -1415.32]; n 87) |
| tsp | **menu** | -957.80 [-1148.39, -783.55] (L12 [-1164.61, -781.61]; L36 [-1138.59, -797.78]; n 87) |
| 50/50 | aggregate (never decides) | -817.69 [-925.48, -670.15] (L12 [-952.73, -672.36]; L36 [-903.60, -688.56]; n 87) |

### R vs min_variance: R minus min_variance

Pooled independent test banks (10,000 outcomes), bp, 95% interval at block 24:

ΔU:

| menu | risk cell | mean paired difference |
|---|---|---|
| example | x25 | +54.18 [+21.73, +95.44] (L12 [+25.34, +90.13]; L36 [+25.13, +92.63]; n 99) |
| example | x50 | +54.39 [+22.01, +96.10] (L12 [+25.18, +90.12]; L36 [+24.81, +93.65]; n 99) |
| example | x100 | +54.49 [+22.03, +96.23] (L12 [+25.28, +90.13]; L36 [+24.82, +93.91]; n 99) |
| example | **menu** | +54.35 [+22.01, +95.78] (L12 [+25.17, +89.90]; L36 [+24.96, +93.31]; n 99) |
| tsp | x25 | +34.79 [+22.98, +46.39] (L12 [+23.89, +47.86]; L36 [+25.35, +42.89]; n 99) |
| tsp | x50 | +34.91 [+23.03, +46.48] (L12 [+24.00, +48.01]; L36 [+25.39, +43.11]; n 99) |
| tsp | x100 | +34.85 [+23.03, +46.44] (L12 [+23.98, +47.85]; L36 [+25.36, +43.01]; n 99) |
| tsp | **menu** | +34.85 [+22.98, +46.42] (L12 [+23.99, +47.92]; L36 [+25.37, +43.01]; n 99) |
| 50/50 | aggregate (never decides) | +44.60 [+23.55, +69.66] (L12 [+26.56, +67.64]; L36 [+27.07, +66.59]; n 99) |

ΔB:

| menu | risk cell | mean paired difference |
|---|---|---|
| example | x25 | -75.70 [-149.14, -25.79] (L12 [-142.96, -25.37]; L36 [-143.89, -25.87]; n 99) |
| example | x50 | -92.46 [-172.26, -33.49] (L12 [-171.68, -32.10]; L36 [-163.65, -36.60]; n 99) |
| example | x100 | -92.19 [-172.12, -33.15] (L12 [-171.13, -31.73]; L36 [-163.60, -36.31]; n 99) |
| example | **menu** | -86.78 [-164.42, -31.23] (L12 [-161.12, -29.62]; L36 [-157.77, -32.93]; n 99) |
| tsp | x25 | -73.77 [-109.71, -38.24] (L12 [-114.98, -40.50]; L36 [-98.26, -45.63]; n 99) |
| tsp | x50 | -90.29 [-138.76, -44.91] (L12 [-145.04, -46.16]; L36 [-124.37, -54.68]; n 99) |
| tsp | x100 | -91.44 [-141.25, -45.06] (L12 [-147.95, -46.16]; L36 [-126.58, -55.05]; n 99) |
| tsp | **menu** | -85.16 [-129.75, -41.67] (L12 [-135.73, -44.08]; L36 [-116.20, -52.20]; n 99) |
| 50/50 | aggregate (never decides) | -85.97 [-142.12, -41.38] (L12 [-147.71, -41.05]; L36 [-130.21, -46.31]; n 99) |

ΔT:

| menu | risk cell | mean paired difference |
|---|---|---|
| example | x25 | +185.94 [+101.44, +272.36] (L12 [+105.41, +278.11]; L36 [+121.35, +244.59]; n 99) |
| example | x50 | +203.50 [+110.71, +298.69] (L12 [+113.01, +304.54]; L36 [+130.69, +269.46]; n 99) |
| example | x100 | +203.47 [+110.68, +298.52] (L12 [+113.03, +304.63]; L36 [+130.54, +269.16]; n 99) |
| example | **menu** | +197.63 [+108.60, +290.88] (L12 [+111.36, +296.39]; L36 [+126.93, +260.91]; n 99) |
| tsp | x25 | +151.70 [+89.79, +214.39] (L12 [+94.38, +221.22]; L36 [+103.55, +194.12]; n 99) |
| tsp | x50 | +168.87 [+97.48, +243.33] (L12 [+99.79, +251.79]; L36 [+112.49, +220.87]; n 99) |
| tsp | x100 | +169.97 [+97.48, +245.25] (L12 [+100.24, +254.76]; L36 [+112.83, +222.86]; n 99) |
| tsp | **menu** | +163.51 [+95.07, +233.71] (L12 [+98.04, +241.41]; L36 [+109.90, +212.34]; n 99) |
| 50/50 | aggregate (never decides) | +180.57 [+101.21, +261.48] (L12 [+106.26, +267.59]; L36 [+119.52, +236.22]; n 99) |

ΔG:

| menu | risk cell | mean paired difference |
|---|---|---|
| example | x25 | +438.16 [+233.07, +652.67] (L12 [+239.55, +667.79]; L36 [+277.35, +586.05]; n 99) |
| example | x50 | +488.15 [+256.14, +726.63] (L12 [+265.42, +742.67]; L36 [+304.21, +652.84]; n 99) |
| example | x100 | +487.69 [+255.88, +725.56] (L12 [+265.89, +742.86]; L36 [+303.93, +652.38]; n 99) |
| example | **menu** | +471.33 [+251.65, +701.97] (L12 [+256.28, +717.16]; L36 [+295.68, +630.27]; n 99) |
| tsp | x25 | +335.45 [+193.24, +478.60] (L12 [+203.62, +496.93]; L36 [+224.05, +433.12]; n 99) |
| tsp | x50 | +384.20 [+211.27, +560.07] (L12 [+222.26, +581.43]; L36 [+249.45, +509.57]; n 99) |
| tsp | x100 | +387.25 [+212.90, +568.52] (L12 [+222.26, +589.35]; L36 [+250.23, +515.20]; n 99) |
| tsp | **menu** | +368.97 [+208.13, +535.06] (L12 [+214.91, +551.48]; L36 [+241.69, +485.34]; n 99) |
| 50/50 | aggregate (never decides) | +420.15 [+227.78, +616.52] (L12 [+238.23, +632.30]; L36 [+268.89, +557.74]; n 99) |

ΔES_2.5:

| menu | risk cell | mean paired difference |
|---|---|---|
| example | x25 | -131.81 [-235.53, -59.88] (L12 [-230.43, -58.96]; L36 [-223.30, -63.01]; n 99) |
| example | x50 | -153.77 [-264.13, -69.33] (L12 [-268.12, -67.60]; L36 [-248.16, -76.12]; n 99) |
| example | x100 | -153.61 [-263.97, -69.12] (L12 [-268.24, -67.23]; L36 [-248.16, -75.96]; n 99) |
| example | **menu** | -146.40 [-254.04, -65.45] (L12 [-255.95, -65.65]; L36 [-240.67, -71.91]; n 99) |
| tsp | x25 | -124.54 [-185.62, -66.21] (L12 [-192.94, -69.12]; L36 [-165.80, -78.18]; n 99) |
| tsp | x50 | -148.06 [-227.66, -75.45] (L12 [-236.34, -76.89]; L36 [-204.91, -90.61]; n 99) |
| tsp | x100 | -149.59 [-231.55, -76.39] (L12 [-239.44, -76.95]; L36 [-208.10, -90.69]; n 99) |
| tsp | **menu** | -140.73 [-214.26, -72.07] (L12 [-222.88, -74.37]; L36 [-192.57, -86.91]; n 99) |
| 50/50 | aggregate (never decides) | -143.56 [-230.70, -73.43] (L12 [-238.64, -73.30]; L36 [-210.67, -83.85]; n 99) |

Realized (one annual return per origin, realized mask):

annual return (bp):

| menu | risk cell | mean paired difference |
|---|---|---|
| example | x25 | +149.30 [-20.49, +390.07] (L12 [-24.16, +372.01]; L36 [-16.32, +387.68]; n 87) |
| example | x50 | +161.68 [-11.85, +418.20] (L12 [-19.18, +396.67]; L36 [-6.68, +407.06]; n 87) |
| example | x100 | +160.69 [-12.02, +415.37] (L12 [-19.23, +393.93]; L36 [-6.68, +403.90]; n 87) |
| example | **menu** | +157.22 [-13.98, +407.12] (L12 [-20.34, +387.00]; L36 [-9.63, +399.56]; n 87) |
| tsp | x25 | +111.74 [+32.96, +208.84] (L12 [+23.06, +215.24]; L36 [+45.30, +200.94]; n 87) |
| tsp | x50 | +108.13 [+12.49, +215.79] (L12 [-0.04, +221.12]; L36 [+25.76, +210.78]; n 87) |
| tsp | x100 | +107.28 [+10.48, +214.84] (L12 [-2.95, +221.12]; L36 [+23.73, +210.78]; n 87) |
| tsp | **menu** | +109.05 [+18.75, +212.83] (L12 [+6.87, +219.59]; L36 [+31.80, +207.61]; n 87) |
| 50/50 | aggregate (never decides) | +133.14 [+5.46, +311.49] (L12 [-5.20, +303.66]; L36 [+11.72, +299.89]; n 87) |

max-drawdown improvement (bp):

| menu | risk cell | mean paired difference |
|---|---|---|
| example | x25 | -185.10 [-304.10, -82.83] (L12 [-331.25, -78.71]; L36 [-268.18, -97.80]; n 87) |
| example | x50 | -209.77 [-346.52, -92.69] (L12 [-373.34, -89.19]; L36 [-298.54, -111.49]; n 87) |
| example | x100 | -210.05 [-347.91, -92.54] (L12 [-373.65, -89.43]; L36 [-298.95, -111.48]; n 87) |
| example | **menu** | -201.64 [-333.40, -90.56] (L12 [-357.54, -86.88]; L36 [-287.79, -106.86]; n 87) |
| tsp | x25 | -119.39 [-183.36, -56.03] (L12 [-196.04, -56.85]; L36 [-169.37, -64.27]; n 87) |
| tsp | x50 | -147.35 [-239.69, -62.96] (L12 [-256.32, -64.66]; L36 [-212.28, -74.51]; n 87) |
| tsp | x100 | -148.44 [-241.29, -62.96] (L12 [-260.23, -64.66]; L36 [-214.00, -74.51]; n 87) |
| tsp | **menu** | -138.39 [-221.38, -61.34] (L12 [-237.24, -62.24]; L36 [-198.16, -71.14]; n 87) |
| 50/50 | aggregate (never decides) | -170.01 [-275.37, -75.55] (L12 [-296.23, -75.89]; L36 [-241.28, -88.15]; n 87) |

loss rate (share):

| menu | risk cell | mean paired difference |
|---|---|---|
| example | x25 | -0.0230 [-0.0515, 0.0000] (L12 [-0.0538, 0.0000]; L36 [-0.0510, 0.0000]; n 87) |
| example | x50 | -0.0230 [-0.0515, 0.0000] (L12 [-0.0538, 0.0000]; L36 [-0.0510, 0.0000]; n 87) |
| example | x100 | -0.0230 [-0.0515, 0.0000] (L12 [-0.0538, 0.0000]; L36 [-0.0510, 0.0000]; n 87) |
| example | **menu** | -0.0230 [-0.0515, 0.0000] (L12 [-0.0538, 0.0000]; L36 [-0.0510, 0.0000]; n 87) |
| tsp | x25 | -0.0230 [-0.0632, 0.0000] (L12 [-0.0690, 0.0000]; L36 [-0.0606, 0.0000]; n 87) |
| tsp | x50 | -0.0230 [-0.0632, 0.0000] (L12 [-0.0690, 0.0000]; L36 [-0.0606, 0.0000]; n 87) |
| tsp | x100 | -0.0230 [-0.0632, 0.0000] (L12 [-0.0690, 0.0000]; L36 [-0.0606, 0.0000]; n 87) |
| tsp | **menu** | -0.0230 [-0.0632, 0.0000] (L12 [-0.0690, 0.0000]; L36 [-0.0606, 0.0000]; n 87) |
| 50/50 | aggregate (never decides) | -0.0230 [-0.0561, 0.0000] (L12 [-0.0562, 0.0000]; L36 [-0.0505, 0.0000]; n 87) |

below -20% rate (share):

| menu | risk cell | mean paired difference |
|---|---|---|
| example | x25 | 0.0000 [0.0000, 0.0000] (L12 [0.0000, 0.0000]; L36 [0.0000, 0.0000]; n 87) |
| example | x50 | 0.0000 [0.0000, 0.0000] (L12 [0.0000, 0.0000]; L36 [0.0000, 0.0000]; n 87) |
| example | x100 | 0.0000 [0.0000, 0.0000] (L12 [0.0000, 0.0000]; L36 [0.0000, 0.0000]; n 87) |
| example | **menu** | 0.0000 [0.0000, 0.0000] (L12 [0.0000, 0.0000]; L36 [0.0000, 0.0000]; n 87) |
| tsp | x25 | 0.0000 [0.0000, 0.0000] (L12 [0.0000, 0.0000]; L36 [0.0000, 0.0000]; n 87) |
| tsp | x50 | 0.0000 [0.0000, 0.0000] (L12 [0.0000, 0.0000]; L36 [0.0000, 0.0000]; n 87) |
| tsp | x100 | 0.0000 [0.0000, 0.0000] (L12 [0.0000, 0.0000]; L36 [0.0000, 0.0000]; n 87) |
| tsp | **menu** | 0.0000 [0.0000, 0.0000] (L12 [0.0000, 0.0000]; L36 [0.0000, 0.0000]; n 87) |
| 50/50 | aggregate (never decides) | 0.0000 [0.0000, 0.0000] (L12 [0.0000, 0.0000]; L36 [0.0000, 0.0000]; n 87) |

worst day (bp):

| menu | risk cell | mean paired difference |
|---|---|---|
| example | x25 | -46.19 [-68.00, -25.43] (L12 [-71.15, -24.72]; L36 [-61.86, -30.06]; n 87) |
| example | x50 | -51.06 [-75.93, -28.09] (L12 [-78.84, -27.98]; L36 [-69.90, -32.75]; n 87) |
| example | x100 | -51.03 [-75.81, -28.06] (L12 [-78.76, -28.00]; L36 [-69.83, -32.81]; n 87) |
| example | **menu** | -49.43 [-72.91, -27.04] (L12 [-76.43, -27.04]; L36 [-66.97, -32.15]; n 87) |
| tsp | x25 | -27.98 [-40.47, -15.35] (L12 [-42.18, -15.94]; L36 [-38.28, -16.75]; n 87) |
| tsp | x50 | -32.43 [-48.56, -16.35] (L12 [-50.28, -17.08]; L36 [-44.98, -18.22]; n 87) |
| tsp | x100 | -32.63 [-48.90, -16.47] (L12 [-50.88, -17.08]; L36 [-45.20, -18.22]; n 87) |
| tsp | **menu** | -31.01 [-45.88, -16.00] (L12 [-47.69, -16.72]; L36 [-42.88, -17.70]; n 87) |
| 50/50 | aggregate (never decides) | -40.22 [-58.72, -22.18] (L12 [-61.54, -22.23]; L36 [-54.55, -25.35]; n 87) |

realized volatility (bp):

| menu | risk cell | mean paired difference |
|---|---|---|
| example | x25 | +170.19 [+91.82, +256.76] (L12 [+90.32, +267.90]; L36 [+111.00, +231.48]; n 87) |
| example | x50 | +191.98 [+103.76, +294.23] (L12 [+103.38, +305.93]; L36 [+122.07, +267.82]; n 87) |
| example | x100 | +191.91 [+103.77, +294.40] (L12 [+103.15, +304.91]; L36 [+122.28, +267.85]; n 87) |
| example | **menu** | +184.69 [+101.15, +279.68] (L12 [+100.11, +294.00]; L36 [+118.51, +255.31]; n 87) |
| tsp | x25 | +123.64 [+64.15, +178.79] (L12 [+66.19, +188.05]; L36 [+68.98, +173.62]; n 87) |
| tsp | x50 | +145.89 [+70.12, +220.59] (L12 [+74.57, +228.53]; L36 [+77.10, +206.71]; n 87) |
| tsp | x100 | +147.34 [+71.70, +223.40] (L12 [+74.58, +232.74]; L36 [+77.29, +208.96]; n 87) |
| tsp | **menu** | +138.95 [+67.44, +207.22] (L12 [+72.40, +216.63]; L36 [+75.09, +196.51]; n 87) |
| 50/50 | aggregate (never decides) | +161.82 [+85.88, +239.63] (L12 [+89.19, +251.19]; L36 [+98.84, +222.00]; n 87) |

### R vs equal_weight: R minus equal_weight

Pooled independent test banks (10,000 outcomes), bp, 95% interval at block 24:

ΔU:

| menu | risk cell | mean paired difference |
|---|---|---|
| example | x25 | +467.04 [+340.00, +601.27] (L12 [+359.61, +574.00]; L36 [+340.75, +608.28]; n 99) |
| example | x50 | +467.25 [+340.74, +601.43] (L12 [+360.28, +573.92]; L36 [+342.03, +608.08]; n 99) |
| example | x100 | +467.36 [+341.10, +601.34] (L12 [+360.49, +573.97]; L36 [+342.20, +608.08]; n 99) |
| example | **menu** | +467.22 [+340.41, +601.35] (L12 [+360.13, +573.92]; L36 [+341.83, +607.92]; n 99) |
| tsp | x25 | +432.95 [+330.96, +557.96] (L12 [+331.34, +537.42]; L36 [+339.42, +548.88]; n 99) |
| tsp | x50 | +433.07 [+331.23, +557.97] (L12 [+331.76, +537.39]; L36 [+339.68, +548.89]; n 99) |
| tsp | x100 | +433.01 [+331.20, +557.91] (L12 [+331.71, +537.34]; L36 [+339.67, +548.83]; n 99) |
| tsp | **menu** | +433.01 [+331.12, +557.98] (L12 [+331.61, +537.38]; L36 [+339.59, +548.87]; n 99) |
| 50/50 | aggregate (never decides) | +450.11 [+340.88, +576.90] (L12 [+351.31, +551.73]; L36 [+344.50, +578.39]; n 99) |

ΔB:

| menu | risk cell | mean paired difference |
|---|---|---|
| example | x25 | +1099.50 [+854.67, +1361.81] (L12 [+898.38, +1305.94]; L36 [+853.02, +1357.79]; n 99) |
| example | x50 | +1082.74 [+828.50, +1356.08] (L12 [+866.24, +1299.06]; L36 [+826.18, +1350.46]; n 99) |
| example | x100 | +1083.01 [+828.77, +1356.36] (L12 [+866.51, +1299.59]; L36 [+826.49, +1350.72]; n 99) |
| example | **menu** | +1088.41 [+837.65, +1358.05] (L12 [+875.04, +1301.16]; L36 [+834.14, +1353.37]; n 99) |
| tsp | x25 | +1224.31 [+973.82, +1487.89] (L12 [+1015.08, +1438.19]; L36 [+968.25, +1483.60]; n 99) |
| tsp | x50 | +1207.79 [+955.56, +1478.75] (L12 [+983.88, +1428.21]; L36 [+954.28, +1468.19]; n 99) |
| tsp | x100 | +1206.64 [+955.01, +1478.26] (L12 [+982.50, +1427.72]; L36 [+954.00, +1465.88]; n 99) |
| tsp | **menu** | +1212.91 [+961.12, +1480.38] (L12 [+994.23, +1431.04]; L36 [+958.22, +1473.28]; n 99) |
| 50/50 | aggregate (never decides) | +1150.66 [+903.66, +1416.19] (L12 [+936.60, +1363.97]; L36 [+899.78, +1411.70]; n 99) |

ΔT:

| menu | risk cell | mean paired difference |
|---|---|---|
| example | x25 | -177.27 [-297.90, -56.15] (L12 [-262.67, -74.51]; L36 [-305.68, -47.96]; n 99) |
| example | x50 | -159.71 [-281.99, -32.29] (L12 [-250.13, -57.21]; L36 [-287.29, -26.30]; n 99) |
| example | x100 | -159.75 [-281.99, -32.19] (L12 [-250.29, -57.27]; L36 [-287.29, -26.53]; n 99) |
| example | **menu** | -165.58 [-287.18, -40.39] (L12 [-253.57, -63.63]; L36 [-293.19, -34.70]; n 99) |
| tsp | x25 | -360.35 [-482.00, -261.29] (L12 [-456.52, -274.25]; L36 [-479.70, -255.23]; n 99) |
| tsp | x50 | -343.18 [-452.01, -248.54] (L12 [-427.61, -264.99]; L36 [-450.91, -243.52]; n 99) |
| tsp | x100 | -342.08 [-448.74, -248.54] (L12 [-425.43, -264.38]; L36 [-448.30, -243.52]; n 99) |
| tsp | **menu** | -348.53 [-461.98, -252.11] (L12 [-436.28, -267.55]; L36 [-459.60, -247.50]; n 99) |
| 50/50 | aggregate (never decides) | -257.06 [-368.81, -148.30] (L12 [-340.18, -167.42]; L36 [-375.30, -144.69]; n 99) |

ΔG:

| menu | risk cell | mean paired difference |
|---|---|---|
| example | x25 | -1394.77 [-1707.58, -1080.77] (L12 [-1647.62, -1136.10]; L36 [-1704.42, -1088.87]; n 99) |
| example | x50 | -1344.78 [-1688.71, -994.41] (L12 [-1634.18, -1049.69]; L36 [-1682.73, -1003.50]; n 99) |
| example | x100 | -1345.24 [-1689.47, -994.07] (L12 [-1635.34, -1049.65]; L36 [-1683.24, -1003.81]; n 99) |
| example | **menu** | -1361.60 [-1694.32, -1023.65] (L12 [-1639.03, -1077.96]; L36 [-1691.33, -1033.67]; n 99) |
| tsp | x25 | -1935.28 [-2288.22, -1559.93] (L12 [-2228.42, -1634.35]; L36 [-2307.59, -1525.93]; n 99) |
| tsp | x50 | -1886.52 [-2250.89, -1512.51] (L12 [-2188.00, -1582.05]; L36 [-2259.03, -1478.88]; n 99) |
| tsp | x100 | -1883.47 [-2247.80, -1510.53] (L12 [-2184.30, -1579.86]; L36 [-2252.87, -1478.88]; n 99) |
| tsp | **menu** | -1901.75 [-2258.99, -1528.33] (L12 [-2199.75, -1598.13]; L36 [-2271.07, -1494.24]; n 99) |
| 50/50 | aggregate (never decides) | -1631.68 [-1973.00, -1280.94] (L12 [-1907.62, -1354.22]; L36 [-1979.34, -1267.29]; n 99) |

ΔES_2.5:

| menu | risk cell | mean paired difference |
|---|---|---|
| example | x25 | +1341.49 [+1043.15, +1652.22] (L12 [+1089.41, +1593.96]; L36 [+1035.43, +1652.91]; n 99) |
| example | x50 | +1319.53 [+1005.38, +1644.27] (L12 [+1051.83, +1582.99]; L36 [+1003.88, +1643.43]; n 99) |
| example | x100 | +1319.69 [+1005.51, +1644.45] (L12 [+1051.78, +1583.36]; L36 [+1004.20, +1643.43]; n 99) |
| example | **menu** | +1326.90 [+1017.83, +1647.87] (L12 [+1064.32, +1585.73]; L36 [+1014.82, +1646.16]; n 99) |
| tsp | x25 | +1527.85 [+1207.06, +1853.13] (L12 [+1263.62, +1789.31]; L36 [+1199.14, +1845.86]; n 99) |
| tsp | x50 | +1504.33 [+1179.93, +1835.80] (L12 [+1231.31, +1774.03]; L36 [+1178.14, +1830.13]; n 99) |
| tsp | x100 | +1502.80 [+1179.58, +1834.25] (L12 [+1229.08, +1773.91]; L36 [+1178.14, +1828.61]; n 99) |
| tsp | **menu** | +1511.66 [+1186.97, +1839.29] (L12 [+1242.47, +1779.33]; L36 [+1185.88, +1835.37]; n 99) |
| 50/50 | aggregate (never decides) | +1419.28 [+1110.13, +1739.70] (L12 [+1155.70, +1679.15]; L36 [+1103.01, +1737.74]; n 99) |

Realized (one annual return per origin, realized mask):

annual return (bp):

| menu | risk cell | mean paired difference |
|---|---|---|
| example | x25 | -296.82 [-555.23, -45.63] (L12 [-628.34, -27.25]; L36 [-506.47, -82.96]; n 87) |
| example | x50 | -284.44 [-541.77, -24.93] (L12 [-617.49, -13.51]; L36 [-494.10, -63.08]; n 87) |
| example | x100 | -285.43 [-541.77, -26.39] (L12 [-618.95, -15.85]; L36 [-494.29, -64.49]; n 87) |
| example | **menu** | -288.90 [-547.49, -32.33] (L12 [-619.82, -18.06]; L36 [-497.78, -69.02]; n 87) |
| tsp | x25 | -548.39 [-845.58, -200.09] (L12 [-982.76, -106.97]; L36 [-750.39, -304.82]; n 87) |
| tsp | x50 | -551.99 [-843.80, -210.90] (L12 [-980.69, -127.77]; L36 [-743.59, -315.05]; n 87) |
| tsp | x100 | -552.85 [-843.80, -212.17] (L12 [-980.69, -129.55]; L36 [-744.35, -316.01]; n 87) |
| tsp | **menu** | -551.08 [-844.63, -206.66] (L12 [-982.44, -118.95]; L36 [-746.48, -312.00]; n 87) |
| 50/50 | aggregate (never decides) | -419.99 [-691.36, -135.88] (L12 [-794.57, -75.40]; L36 [-611.24, -210.77]; n 87) |

max-drawdown improvement (bp):

| menu | risk cell | mean paired difference |
|---|---|---|
| example | x25 | +559.76 [+384.71, +773.55] (L12 [+363.74, +797.31]; L36 [+417.95, +746.47]; n 87) |
| example | x50 | +535.09 [+351.20, +740.23] (L12 [+327.28, +779.57]; L36 [+392.85, +700.88]; n 87) |
| example | x100 | +534.81 [+350.82, +739.80] (L12 [+327.55, +779.05]; L36 [+392.87, +700.29]; n 87) |
| example | **menu** | +543.22 [+362.17, +749.72] (L12 [+337.40, +786.96]; L36 [+400.55, +714.79]; n 87) |
| tsp | x25 | +783.95 [+615.33, +997.52] (L12 [+589.00, +1024.19]; L36 [+633.35, +987.89]; n 87) |
| tsp | x50 | +755.99 [+587.79, +971.37] (L12 [+562.52, +1001.46]; L36 [+617.59, +957.09]; n 87) |
| tsp | x100 | +754.90 [+586.69, +970.25] (L12 [+562.07, +1000.33]; L36 [+616.42, +956.11]; n 87) |
| tsp | **menu** | +764.95 [+595.42, +983.35] (L12 [+573.05, +1006.90]; L36 [+623.07, +966.88]; n 87) |
| 50/50 | aggregate (never decides) | +654.08 [+488.18, +862.37] (L12 [+467.89, +895.84]; L36 [+518.02, +841.64]; n 87) |

loss rate (share):

| menu | risk cell | mean paired difference |
|---|---|---|
| example | x25 | -0.0230 [-0.0471, 0.0000] (L12 [-0.0538, 0.0000]; L36 [-0.0395, 0.0000]; n 87) |
| example | x50 | -0.0230 [-0.0471, 0.0000] (L12 [-0.0538, 0.0000]; L36 [-0.0395, 0.0000]; n 87) |
| example | x100 | -0.0230 [-0.0471, 0.0000] (L12 [-0.0538, 0.0000]; L36 [-0.0395, 0.0000]; n 87) |
| example | **menu** | -0.0230 [-0.0471, 0.0000] (L12 [-0.0538, 0.0000]; L36 [-0.0395, 0.0000]; n 87) |
| tsp | x25 | -0.0460 [-0.0870, -0.0101] (L12 [-0.0930, 0.0000]; L36 [-0.0808, 0.0000]; n 87) |
| tsp | x50 | -0.0460 [-0.0870, -0.0101] (L12 [-0.0930, 0.0000]; L36 [-0.0808, 0.0000]; n 87) |
| tsp | x100 | -0.0460 [-0.0870, -0.0101] (L12 [-0.0930, 0.0000]; L36 [-0.0808, 0.0000]; n 87) |
| tsp | **menu** | -0.0460 [-0.0870, -0.0101] (L12 [-0.0930, 0.0000]; L36 [-0.0808, 0.0000]; n 87) |
| 50/50 | aggregate (never decides) | -0.0345 [-0.0671, -0.0057] (L12 [-0.0714, 0.0000]; L36 [-0.0592, -0.0050]; n 87) |

below -20% rate (share):

| menu | risk cell | mean paired difference |
|---|---|---|
| example | x25 | 0.0000 [0.0000, 0.0000] (L12 [0.0000, 0.0000]; L36 [0.0000, 0.0000]; n 87) |
| example | x50 | 0.0000 [0.0000, 0.0000] (L12 [0.0000, 0.0000]; L36 [0.0000, 0.0000]; n 87) |
| example | x100 | 0.0000 [0.0000, 0.0000] (L12 [0.0000, 0.0000]; L36 [0.0000, 0.0000]; n 87) |
| example | **menu** | 0.0000 [0.0000, 0.0000] (L12 [0.0000, 0.0000]; L36 [0.0000, 0.0000]; n 87) |
| tsp | x25 | 0.0000 [0.0000, 0.0000] (L12 [0.0000, 0.0000]; L36 [0.0000, 0.0000]; n 87) |
| tsp | x50 | 0.0000 [0.0000, 0.0000] (L12 [0.0000, 0.0000]; L36 [0.0000, 0.0000]; n 87) |
| tsp | x100 | 0.0000 [0.0000, 0.0000] (L12 [0.0000, 0.0000]; L36 [0.0000, 0.0000]; n 87) |
| tsp | **menu** | 0.0000 [0.0000, 0.0000] (L12 [0.0000, 0.0000]; L36 [0.0000, 0.0000]; n 87) |
| 50/50 | aggregate (never decides) | 0.0000 [0.0000, 0.0000] (L12 [0.0000, 0.0000]; L36 [0.0000, 0.0000]; n 87) |

worst day (bp):

| menu | risk cell | mean paired difference |
|---|---|---|
| example | x25 | +136.30 [+86.34, +202.17] (L12 [+81.96, +201.06]; L36 [+91.43, +195.75]; n 87) |
| example | x50 | +131.43 [+79.04, +197.79] (L12 [+73.88, +196.65]; L36 [+87.13, +188.67]; n 87) |
| example | x100 | +131.46 [+79.01, +197.73] (L12 [+73.81, +196.65]; L36 [+87.16, +188.57]; n 87) |
| example | **menu** | +133.06 [+81.58, +198.62] (L12 [+76.50, +197.89]; L36 [+88.56, +191.50]; n 87) |
| tsp | x25 | +211.54 [+140.34, +303.89] (L12 [+136.18, +304.57]; L36 [+145.80, +299.15]; n 87) |
| tsp | x50 | +207.09 [+134.60, +301.97] (L12 [+130.51, +301.30]; L36 [+140.10, +294.36]; n 87) |
| tsp | x100 | +206.89 [+133.92, +301.97] (L12 [+130.27, +301.09]; L36 [+139.76, +294.36]; n 87) |
| tsp | **menu** | +208.51 [+136.10, +302.35] (L12 [+132.32, +301.70]; L36 [+141.63, +295.92]; n 87) |
| 50/50 | aggregate (never decides) | +170.78 [+109.09, +251.24] (L12 [+104.90, +248.72]; L36 [+115.74, +244.37]; n 87) |

realized volatility (bp):

| menu | risk cell | mean paired difference |
|---|---|---|
| example | x25 | -553.52 [-748.01, -403.23] (L12 [-745.40, -390.15]; L36 [-721.72, -422.07]; n 87) |
| example | x50 | -531.73 [-726.72, -363.90] (L12 [-730.26, -352.68]; L36 [-693.61, -393.23]; n 87) |
| example | x100 | -531.80 [-725.97, -364.41] (L12 [-730.26, -352.58]; L36 [-693.16, -393.99]; n 87) |
| example | **menu** | -539.01 [-734.14, -380.09] (L12 [-732.84, -366.98]; L36 [-701.03, -403.38]; n 87) |
| tsp | x25 | -793.81 [-976.73, -649.19] (L12 [-979.06, -643.41]; L36 [-967.64, -660.74]; n 87) |
| tsp | x50 | -771.56 [-957.78, -625.46] (L12 [-962.03, -615.52]; L36 [-945.26, -644.54]; n 87) |
| tsp | x100 | -770.11 [-956.51, -625.46] (L12 [-960.18, -613.57]; L36 [-944.37, -644.16]; n 87) |
| tsp | **menu** | -778.49 [-963.67, -633.53] (L12 [-967.83, -624.79]; L36 [-952.23, -652.66]; n 87) |
| 50/50 | aggregate (never decides) | -658.75 [-847.70, -507.05] (L12 [-853.13, -498.47]; L36 [-827.27, -529.29]; n 87) |

Equal weight within the cell's ceiling (share of cells): {'example': 0.5959595959595959, 'tsp': 0.4377104377104377}. An equal-weight reference above its ceiling keeps its locked status `infeasible`; its evaluated figures here are flagged `reference_infeasible` in outcomes.parquet.

## White-line candidates: max-U w_R and the max-mu_s frontier

Per origin and ceiling the two candidates, with risk, B/T/G, U, ES_2.5 and DR² on the training and independent banks, are in Appendix A; C8 decides.

### w_R vs frontier: R minus frontier

Pooled independent test banks (10,000 outcomes), bp, 95% interval at block 24:

ΔU:

| menu | risk cell | mean paired difference |
|---|---|---|
| example | x25 | +76.24 [+28.70, +134.90] (L12 [+35.00, +124.07]; L36 [+30.53, +132.07]; n 99) |
| example | x50 | +218.73 [+116.70, +344.72] (L12 [+130.30, +317.97]; L36 [+114.26, +342.79]; n 99) |
| example | x100 | +698.88 [+477.43, +923.86] (L12 [+521.99, +880.74]; L36 [+470.34, +929.57]; n 99) |
| example | **menu** | +331.28 [+208.00, +467.58] (L12 [+231.12, +439.61]; L36 [+205.80, +466.79]; n 99) |
| tsp | x25 | +82.15 [+45.44, +118.73] (L12 [+47.57, +114.40]; L36 [+48.77, +113.35]; n 99) |
| tsp | x50 | +226.96 [+153.52, +316.40] (L12 [+152.44, +303.07]; L36 [+161.60, +306.51]; n 99) |
| tsp | x100 | +666.07 [+481.81, +883.87] (L12 [+486.66, +849.78]; L36 [+498.96, +871.43]; n 99) |
| tsp | **menu** | +325.06 [+228.76, +438.11] (L12 [+230.80, +421.58]; L36 [+239.17, +428.23]; n 99) |
| 50/50 | aggregate (never decides) | +328.17 [+222.14, +451.93] (L12 [+233.82, +428.47]; L36 [+223.97, +446.63]; n 99) |

ΔB:

| menu | risk cell | mean paired difference |
|---|---|---|
| example | x25 | +314.40 [+167.07, +462.15] (L12 [+185.59, +437.21]; L36 [+178.51, +452.21]; n 99) |
| example | x50 | +805.59 [+539.83, +1064.47] (L12 [+592.86, +1022.02]; L36 [+536.49, +1066.60]; n 99) |
| example | x100 | +2025.94 [+1484.40, +2531.44] (L12 [+1604.39, +2434.00]; L36 [+1457.50, +2570.43]; n 99) |
| example | **menu** | +1048.64 [+730.82, +1350.62] (L12 [+805.73, +1287.23]; L36 [+725.32, +1362.22]; n 99) |
| tsp | x25 | +354.39 [+236.75, +453.87] (L12 [+252.55, +443.12]; L36 [+246.15, +446.42]; n 99) |
| tsp | x50 | +877.34 [+670.37, +1075.49] (L12 [+703.19, +1046.29]; L36 [+678.40, +1067.01]; n 99) |
| tsp | x100 | +2207.33 [+1737.85, +2645.85] (L12 [+1826.87, +2564.36]; L36 [+1728.86, +2657.44]; n 99) |
| tsp | **menu** | +1146.35 [+886.23, +1392.48] (L12 [+939.47, +1350.03]; L36 [+892.87, +1388.95]; n 99) |
| 50/50 | aggregate (never decides) | +1097.50 [+811.34, +1367.18] (L12 [+873.36, +1317.16]; L36 [+808.03, +1369.85]; n 99) |

ΔT:

| menu | risk cell | mean paired difference |
|---|---|---|
| example | x25 | -166.02 [-217.71, -100.87] (L12 [-213.58, -109.24]; L36 [-212.43, -109.02]; n 99) |
| example | x50 | -371.39 [-469.98, -267.01] (L12 [-446.95, -285.86]; L36 [-478.23, -268.95]; n 99) |
| example | x100 | -587.99 [-780.60, -435.09] (L12 [-738.22, -454.91]; L36 [-782.37, -429.02]; n 99) |
| example | **menu** | -375.13 [-482.65, -269.78] (L12 [-456.53, -288.62]; L36 [-487.95, -269.63]; n 99) |
| tsp | x25 | -199.54 [-239.61, -149.64] (L12 [-236.36, -158.93]; L36 [-239.56, -149.85]; n 99) |
| tsp | x50 | -434.15 [-525.64, -346.40] (L12 [-507.87, -361.88]; L36 [-523.99, -343.45]; n 99) |
| tsp | x100 | -789.47 [-1040.57, -612.65] (L12 [-996.94, -625.67]; L36 [-1028.95, -609.83]; n 99) |
| tsp | **menu** | -474.39 [-599.25, -372.92] (L12 [-572.46, -387.16]; L36 [-593.22, -367.72]; n 99) |
| 50/50 | aggregate (never decides) | -424.76 [-540.16, -321.92] (L12 [-513.89, -340.32]; L36 [-540.86, -319.78]; n 99) |

ΔG:

| menu | risk cell | mean paired difference |
|---|---|---|
| example | x25 | -625.98 [-844.13, -374.33] (L12 [-812.89, -396.48]; L36 [-826.02, -394.66]; n 99) |
| example | x50 | -1532.04 [-1867.21, -1118.09] (L12 [-1810.63, -1199.86]; L36 [-1883.27, -1117.97]; n 99) |
| example | x100 | -3402.92 [-4109.97, -2648.08] (L12 [-3976.18, -2827.57]; L36 [-4144.00, -2599.42]; n 99) |
| example | **menu** | -1853.65 [-2253.95, -1396.46] (L12 [-2180.15, -1499.18]; L36 [-2274.32, -1381.52]; n 99) |
| tsp | x25 | -706.17 [-854.10, -519.87] (L12 [-839.08, -552.80]; L36 [-851.81, -526.45]; n 99) |
| tsp | x50 | -1692.02 [-1953.42, -1372.73] (L12 [-1921.00, -1439.39]; L36 [-1969.21, -1366.32]; n 99) |
| tsp | x100 | -4214.89 [-4949.06, -3377.41] (L12 [-4831.76, -3557.59]; L36 [-4980.67, -3328.56]; n 99) |
| tsp | **menu** | -2204.36 [-2581.44, -1776.02] (L12 [-2514.56, -1866.02]; L36 [-2602.75, -1745.97]; n 99) |
| 50/50 | aggregate (never decides) | -2029.00 [-2409.49, -1593.05] (L12 [-2339.29, -1695.78]; L36 [-2437.70, -1578.89]; n 99) |

ΔES_2.5:

| menu | risk cell | mean paired difference |
|---|---|---|
| example | x25 | +410.93 [+219.68, +601.87] (L12 [+242.98, +569.58]; L36 [+234.30, +591.04]; n 99) |
| example | x50 | +1033.46 [+692.00, +1357.20] (L12 [+766.44, +1299.38]; L36 [+690.15, +1364.19]; n 99) |
| example | x100 | +2461.56 [+1812.04, +3064.34] (L12 [+1954.15, +2951.48]; L36 [+1772.77, +3112.95]; n 99) |
| example | **menu** | +1301.98 [+907.77, +1672.78] (L12 [+999.02, +1593.21]; L36 [+900.54, +1684.89]; n 99) |
| tsp | x25 | +476.97 [+317.60, +609.64] (L12 [+340.17, +594.41]; L36 [+328.81, +601.97]; n 99) |
| tsp | x50 | +1139.97 [+869.30, +1389.92] (L12 [+914.12, +1353.37]; L36 [+875.39, +1385.38]; n 99) |
| tsp | x100 | +2706.06 [+2140.16, +3222.05] (L12 [+2257.85, +3130.27]; L36 [+2129.43, +3234.58]; n 99) |
| tsp | **menu** | +1441.00 [+1116.60, +1739.14] (L12 [+1179.95, +1689.87]; L36 [+1120.65, +1735.23]; n 99) |
| 50/50 | aggregate (never decides) | +1371.49 [+1014.32, +1700.86] (L12 [+1093.87, +1639.72]; L36 [+1006.85, +1707.70]; n 99) |

Realized (one annual return per origin, realized mask):

annual return (bp):

| menu | risk cell | mean paired difference |
|---|---|---|
| example | x25 | -237.32 [-380.74, -74.56] (L12 [-369.47, -63.45]; L36 [-364.97, -114.47]; n 87) |
| example | x50 | -498.64 [-748.25, -184.17] (L12 [-762.47, -150.60]; L36 [-717.38, -271.27]; n 87) |
| example | x100 | -732.82 [-1113.22, -214.03] (L12 [-1309.35, -201.42]; L36 [-995.31, -335.70]; n 87) |
| example | **menu** | -489.59 [-695.52, -240.61] (L12 [-789.96, -187.12]; L36 [-624.91, -326.87]; n 87) |
| tsp | x25 | -300.24 [-489.24, -73.68] (L12 [-504.04, -36.64]; L36 [-464.07, -143.24]; n 87) |
| tsp | x50 | -631.61 [-916.22, -278.74] (L12 [-994.28, -212.53]; L36 [-851.72, -392.01]; n 87) |
| tsp | x100 | -1090.22 [-1734.52, -373.69] (L12 [-1995.46, -194.96]; L36 [-1518.34, -597.38]; n 87) |
| tsp | **menu** | -674.02 [-1026.35, -257.86] (L12 [-1161.53, -152.60]; L36 [-931.13, -392.78]; n 87) |
| 50/50 | aggregate (never decides) | -581.81 [-860.74, -254.78] (L12 [-967.27, -169.86]; L36 [-778.55, -367.10]; n 87) |

max-drawdown improvement (bp):

| menu | risk cell | mean paired difference |
|---|---|---|
| example | x25 | +342.32 [+210.74, +497.30] (L12 [+211.15, +505.47]; L36 [+231.90, +482.06]; n 87) |
| example | x50 | +638.11 [+486.74, +767.29] (L12 [+473.42, +806.76]; L36 [+508.60, +760.05]; n 87) |
| example | x100 | +1115.72 [+760.51, +1517.50] (L12 [+747.63, +1542.37]; L36 [+816.71, +1498.36]; n 87) |
| example | **menu** | +698.72 [+514.46, +912.51] (L12 [+496.88, +942.14]; L36 [+548.08, +891.71]; n 87) |
| tsp | x25 | +345.22 [+231.55, +447.13] (L12 [+220.56, +462.28]; L36 [+252.32, +452.45]; n 87) |
| tsp | x50 | +705.69 [+524.23, +907.28] (L12 [+501.82, +925.86]; L36 [+555.12, +905.89]; n 87) |
| tsp | x100 | +1510.55 [+1201.63, +1888.48] (L12 [+1149.47, +1922.10]; L36 [+1248.31, +1873.17]; n 87) |
| tsp | **menu** | +853.82 [+653.52, +1078.83] (L12 [+628.68, +1101.80]; L36 [+686.86, +1078.03]; n 87) |
| 50/50 | aggregate (never decides) | +776.27 [+603.48, +994.69] (L12 [+574.32, +1014.93]; L36 [+636.42, +982.93]; n 87) |

loss rate (share):

| menu | risk cell | mean paired difference |
|---|---|---|
| example | x25 | -0.0115 [-0.0323, 0.0000] (L12 [-0.0380, 0.0000]; L36 [-0.0309, 0.0000]; n 87) |
| example | x50 | -0.0115 [-0.0323, 0.0000] (L12 [-0.0380, 0.0000]; L36 [-0.0309, 0.0000]; n 87) |
| example | x100 | -0.0920 [-0.2286, -0.0103] (L12 [-0.2125, -0.0106]; L36 [-0.2237, -0.0106]; n 87) |
| example | **menu** | -0.0383 [-0.0821, -0.0070] (L12 [-0.0806, -0.0041]; L36 [-0.0756, -0.0105]; n 87) |
| tsp | x25 | -0.0345 [-0.0825, 0.0000] (L12 [-0.0833, 0.0000]; L36 [-0.0800, 0.0000]; n 87) |
| tsp | x50 | -0.0460 [-0.0909, -0.0101] (L12 [-0.0920, 0.0000]; L36 [-0.0900, 0.0000]; n 87) |
| tsp | x100 | -0.0920 [-0.1980, -0.0208] (L12 [-0.1951, -0.0202]; L36 [-0.1733, -0.0227]; n 87) |
| tsp | **menu** | -0.0575 [-0.1039, -0.0145] (L12 [-0.1084, -0.0127]; L36 [-0.0930, -0.0136]; n 87) |
| 50/50 | aggregate (never decides) | -0.0479 [-0.0891, -0.0123] (L12 [-0.0907, -0.0128]; L36 [-0.0802, -0.0125]; n 87) |

below -20% rate (share):

| menu | risk cell | mean paired difference |
|---|---|---|
| example | x25 | 0.0000 [0.0000, 0.0000] (L12 [0.0000, 0.0000]; L36 [0.0000, 0.0000]; n 87) |
| example | x50 | -0.0345 [-0.0941, 0.0000] (L12 [-0.1035, 0.0000]; L36 [-0.0816, 0.0000]; n 87) |
| example | x100 | 0.0000 [0.0000, 0.0000] (L12 [0.0000, 0.0000]; L36 [0.0000, 0.0000]; n 87) |
| example | **menu** | -0.0115 [-0.0314, 0.0000] (L12 [-0.0345, 0.0000]; L36 [-0.0272, 0.0000]; n 87) |
| tsp | x25 | 0.0000 [0.0000, 0.0000] (L12 [0.0000, 0.0000]; L36 [0.0000, 0.0000]; n 87) |
| tsp | x50 | 0.0000 [0.0000, 0.0000] (L12 [0.0000, 0.0000]; L36 [0.0000, 0.0000]; n 87) |
| tsp | x100 | -0.0230 [-0.0625, 0.0000] (L12 [-0.0707, 0.0000]; L36 [-0.0518, 0.0000]; n 87) |
| tsp | **menu** | -0.0077 [-0.0208, 0.0000] (L12 [-0.0236, 0.0000]; L36 [-0.0173, 0.0000]; n 87) |
| 50/50 | aggregate (never decides) | -0.0096 [-0.0260, 0.0000] (L12 [-0.0292, 0.0000]; L36 [-0.0222, 0.0000]; n 87) |

worst day (bp):

| menu | risk cell | mean paired difference |
|---|---|---|
| example | x25 | +80.82 [+44.45, +121.63] (L12 [+40.78, +124.03]; L36 [+49.93, +117.22]; n 87) |
| example | x50 | +163.70 [+117.75, +212.15] (L12 [+111.92, +219.56]; L36 [+126.79, +205.37]; n 87) |
| example | x100 | +336.41 [+228.56, +464.39] (L12 [+223.88, +466.76]; L36 [+238.73, +457.16]; n 87) |
| example | **menu** | +193.64 [+130.68, +265.97] (L12 [+126.75, +269.01]; L36 [+139.34, +259.25]; n 87) |
| tsp | x25 | +92.28 [+60.37, +127.50] (L12 [+59.22, +128.26]; L36 [+65.30, +125.55]; n 87) |
| tsp | x50 | +202.65 [+134.24, +285.77] (L12 [+130.07, +287.20]; L36 [+140.29, +282.35]; n 87) |
| tsp | x100 | +433.77 [+287.98, +632.25] (L12 [+281.75, +626.40]; L36 [+297.05, +623.77]; n 87) |
| tsp | **menu** | +242.90 [+161.40, +348.84] (L12 [+156.38, +346.91]; L36 [+167.74, +343.28]; n 87) |
| 50/50 | aggregate (never decides) | +218.27 [+146.86, +306.85] (L12 [+141.73, +308.80]; L36 [+153.70, +300.11]; n 87) |

realized volatility (bp):

| menu | risk cell | mean paired difference |
|---|---|---|
| example | x25 | -304.85 [-437.00, -197.88] (L12 [-432.00, -188.07]; L36 [-421.59, -215.70]; n 87) |
| example | x50 | -642.96 [-800.23, -493.14] (L12 [-813.00, -488.02]; L36 [-793.16, -517.53]; n 87) |
| example | x100 | -1363.29 [-1686.33, -1105.17] (L12 [-1698.01, -1094.16]; L36 [-1676.13, -1136.86]; n 87) |
| example | **menu** | -770.37 [-973.22, -602.19] (L12 [-979.89, -592.44]; L36 [-965.24, -627.26]; n 87) |
| tsp | x25 | -321.93 [-425.16, -234.66] (L12 [-420.53, -233.64]; L36 [-424.05, -248.75]; n 87) |
| tsp | x50 | -744.34 [-942.52, -583.47] (L12 [-942.57, -576.26]; L36 [-938.12, -607.23]; n 87) |
| tsp | x100 | -1697.11 [-2056.18, -1381.41] (L12 [-2070.64, -1382.79]; L36 [-2057.35, -1417.34]; n 87) |
| tsp | **menu** | -921.13 [-1140.39, -732.10] (L12 [-1141.45, -735.16]; L36 [-1138.99, -760.76]; n 87) |
| 50/50 | aggregate (never decides) | -845.75 [-1057.06, -671.62] (L12 [-1062.31, -663.97]; L36 [-1051.90, -694.38]; n 87) |

## R+D against R at the 2.5 bp primary cap

On the optimization bank ΔU lies in [-2.5 bp, 0] by construction; the independent banks ask whether the Stage B selection recovers more than its sacrifice.

### Primary: R+D@2.5bp minus R

Pooled independent test banks (10,000 outcomes), bp, 95% interval at block 24:

ΔU:

| menu | risk cell | mean paired difference |
|---|---|---|
| example | x25 | -0.36 [-0.87, +0.29] (L12 [-0.85, +0.24]; L36 [-0.85, +0.20]; n 99) |
| example | x50 | -0.28 [-0.74, +0.29] (L12 [-0.73, +0.27]; L36 [-0.73, +0.25]; n 99) |
| example | x100 | -0.19 [-0.58, +0.32] (L12 [-0.62, +0.33]; L36 [-0.54, +0.26]; n 99) |
| example | **menu** | -0.28 [-0.71, +0.30] (L12 [-0.71, +0.27]; L36 [-0.70, +0.24]; n 99) |
| tsp | x25 | -0.22 [-0.51, +0.08] (L12 [-0.49, +0.05]; L36 [-0.52, +0.08]; n 99) |
| tsp | x50 | -0.21 [-0.49, +0.06] (L12 [-0.47, +0.04]; L36 [-0.49, +0.06]; n 99) |
| tsp | x100 | -0.20 [-0.48, +0.07] (L12 [-0.46, +0.05]; L36 [-0.48, +0.06]; n 99) |
| tsp | **menu** | -0.21 [-0.49, +0.07] (L12 [-0.47, +0.04]; L36 [-0.49, +0.07]; n 99) |
| 50/50 | aggregate (never decides) | -0.24 [-0.42, -0.05] (L12 [-0.46, -0.00]; L36 [-0.40, -0.07]; n 99) |

ΔB:

| menu | risk cell | mean paired difference |
|---|---|---|
| example | x25 | +0.69 [+0.01, +1.54] (L12 [-0.11, +1.62]; L36 [+0.10, +1.42]; n 99) |
| example | x50 | +1.02 [+0.13, +1.86] (L12 [-0.07, +2.13]; L36 [+0.12, +1.86]; n 99) |
| example | x100 | +1.06 [+0.17, +1.89] (L12 [+0.01, +2.14]; L36 [+0.14, +1.87]; n 99) |
| example | **menu** | +0.93 [+0.20, +1.67] (L12 [-0.00, +1.91]; L36 [+0.17, +1.66]; n 99) |
| tsp | x25 | +2.76 [+0.06, +5.33] (L12 [+0.47, +5.09]; L36 [-0.04, +5.41]; n 99) |
| tsp | x50 | +2.59 [+0.20, +4.65] (L12 [+0.53, +4.73]; L36 [+0.20, +4.78]; n 99) |
| tsp | x100 | +2.56 [+0.17, +4.63] (L12 [+0.51, +4.70]; L36 [+0.18, +4.77]; n 99) |
| tsp | **menu** | +2.64 [+0.17, +4.81] (L12 [+0.55, +4.82]; L36 [+0.14, +4.97]; n 99) |
| 50/50 | aggregate (never decides) | +1.78 [+0.81, +2.68] (L12 [+0.82, +2.78]; L36 [+0.78, +2.69]; n 99) |

ΔT:

| menu | risk cell | mean paired difference |
|---|---|---|
| example | x25 | -1.13 [-1.60, -0.63] (L12 [-1.74, -0.46]; L36 [-1.54, -0.69]; n 99) |
| example | x50 | -1.30 [-2.37, -0.47] (L12 [-2.45, -0.32]; L36 [-2.35, -0.42]; n 99) |
| example | x100 | -1.19 [-2.18, -0.44] (L12 [-2.32, -0.21]; L36 [-2.13, -0.38]; n 99) |
| example | **menu** | -1.21 [-2.01, -0.54] (L12 [-2.11, -0.36]; L36 [-1.98, -0.52]; n 99) |
| tsp | x25 | -3.33 [-5.41, -1.08] (L12 [-5.39, -1.33]; L36 [-5.49, -1.00]; n 99) |
| tsp | x50 | -3.18 [-4.98, -1.09] (L12 [-5.10, -1.33]; L36 [-4.98, -1.20]; n 99) |
| tsp | x100 | -3.14 [-4.92, -1.08] (L12 [-5.06, -1.31]; L36 [-4.96, -1.17]; n 99) |
| tsp | **menu** | -3.21 [-5.07, -1.11] (L12 [-5.15, -1.36]; L36 [-5.11, -1.15]; n 99) |
| 50/50 | aggregate (never decides) | -2.21 [-3.14, -1.02] (L12 [-3.29, -1.13]; L36 [-3.18, -1.12]; n 99) |

ΔG:

| menu | risk cell | mean paired difference |
|---|---|---|
| example | x25 | -4.38 [-6.03, -2.77] (L12 [-6.43, -2.16]; L36 [-6.00, -2.78]; n 99) |
| example | x50 | -5.03 [-7.40, -2.96] (L12 [-8.25, -2.19]; L36 [-7.34, -2.79]; n 99) |
| example | x100 | -4.72 [-6.90, -2.85] (L12 [-7.90, -1.84]; L36 [-6.79, -2.67]; n 99) |
| example | **menu** | -4.71 [-6.62, -2.96] (L12 [-7.41, -2.22]; L36 [-6.65, -2.81]; n 99) |
| tsp | x25 | -8.77 [-15.20, -2.04] (L12 [-14.61, -3.12]; L36 [-15.46, -1.79]; n 99) |
| tsp | x50 | -8.11 [-13.31, -2.26] (L12 [-13.32, -3.14]; L36 [-13.49, -2.42]; n 99) |
| tsp | x100 | -7.98 [-13.20, -2.19] (L12 [-13.23, -3.00]; L36 [-13.40, -2.32]; n 99) |
| tsp | **menu** | -8.29 [-13.73, -2.23] (L12 [-13.50, -3.17]; L36 [-14.07, -2.26]; n 99) |
| 50/50 | aggregate (never decides) | -6.50 [-9.51, -3.15] (L12 [-9.45, -3.53]; L36 [-9.63, -3.17]; n 99) |

ΔES_2.5:

| menu | risk cell | mean paired difference |
|---|---|---|
| example | x25 | +1.66 [+0.93, +2.42] (L12 [+0.60, +2.73]; L36 [+0.92, +2.51]; n 99) |
| example | x50 | +1.84 [+0.94, +2.69] (L12 [+0.55, +3.00]; L36 [+0.88, +2.75]; n 99) |
| example | x100 | +1.80 [+0.94, +2.66] (L12 [+0.53, +2.95]; L36 [+0.84, +2.70]; n 99) |
| example | **menu** | +1.77 [+0.99, +2.55] (L12 [+0.64, +2.85]; L36 [+0.93, +2.60]; n 99) |
| tsp | x25 | +4.30 [+0.85, +7.54] (L12 [+1.23, +7.36]; L36 [+0.68, +7.73]; n 99) |
| tsp | x50 | +4.00 [+0.86, +6.82] (L12 [+1.20, +6.90]; L36 [+0.90, +6.92]; n 99) |
| tsp | x100 | +3.95 [+0.80, +6.75] (L12 [+1.14, +6.84]; L36 [+0.85, +6.89]; n 99) |
| tsp | **menu** | +4.08 [+0.83, +6.98] (L12 [+1.25, +7.03]; L36 [+0.83, +7.16]; n 99) |
| 50/50 | aggregate (never decides) | +2.92 [+1.52, +4.18] (L12 [+1.52, +4.44]; L36 [+1.49, +4.19]; n 99) |

Realized (one annual return per origin, realized mask):

annual return (bp):

| menu | risk cell | mean paired difference |
|---|---|---|
| example | x25 | -3.72 [-6.64, -0.96] (L12 [-7.14, -0.33]; L36 [-6.44, -0.99]; n 87) |
| example | x50 | -3.37 [-6.60, -0.50] (L12 [-6.80, -0.06]; L36 [-6.45, -0.39]; n 87) |
| example | x100 | -3.41 [-6.70, -0.54] (L12 [-6.78, -0.08]; L36 [-6.49, -0.36]; n 87) |
| example | **menu** | -3.50 [-6.59, -0.71] (L12 [-6.86, -0.16]; L36 [-6.41, -0.59]; n 87) |
| tsp | x25 | -0.31 [-2.91, +1.58] (L12 [-3.33, +2.11]; L36 [-2.34, +1.53]; n 87) |
| tsp | x50 | -0.60 [-3.16, +1.50] (L12 [-3.63, +2.04]; L36 [-2.65, +1.20]; n 87) |
| tsp | x100 | -0.56 [-3.10, +1.56] (L12 [-3.60, +2.08]; L36 [-2.63, +1.25]; n 87) |
| tsp | **menu** | -0.49 [-2.95, +1.51] (L12 [-3.41, +2.03]; L36 [-2.44, +1.27]; n 87) |
| 50/50 | aggregate (never decides) | -2.00 [-3.93, -0.14] (L12 [-4.05, +0.12]; L36 [-3.96, -0.31]; n 87) |

max-drawdown improvement (bp):

| menu | risk cell | mean paired difference |
|---|---|---|
| example | x25 | +2.02 [-0.35, +4.60] (L12 [-0.60, +4.76]; L36 [+0.13, +4.47]; n 87) |
| example | x50 | +2.70 [+0.43, +5.55] (L12 [+0.34, +5.43]; L36 [+0.80, +5.36]; n 87) |
| example | x100 | +2.26 [+0.23, +4.47] (L12 [+0.04, +4.87]; L36 [+0.70, +4.24]; n 87) |
| example | **menu** | +2.33 [+0.12, +4.88] (L12 [-0.07, +4.96]; L36 [+0.56, +4.65]; n 87) |
| tsp | x25 | +5.68 [+0.82, +13.36] (L12 [+1.02, +12.10]; L36 [+0.77, +13.39]; n 87) |
| tsp | x50 | +5.62 [+1.18, +12.59] (L12 [+1.38, +11.44]; L36 [+1.14, +12.61]; n 87) |
| tsp | x100 | +5.67 [+1.26, +12.60] (L12 [+1.40, +11.48]; L36 [+1.22, +12.61]; n 87) |
| tsp | **menu** | +5.66 [+1.09, +12.86] (L12 [+1.32, +11.63]; L36 [+1.04, +12.92]; n 87) |
| 50/50 | aggregate (never decides) | +3.99 [+1.11, +8.64] (L12 [+1.06, +7.78]; L36 [+1.06, +8.57]; n 87) |

loss rate (share):

| menu | risk cell | mean paired difference |
|---|---|---|
| example | x25 | 0.0115 [0.0000, 0.0326] (L12 [0.0000, 0.0370]; L36 [0.0000, 0.0306]; n 87) |
| example | x50 | 0.0115 [0.0000, 0.0326] (L12 [0.0000, 0.0370]; L36 [0.0000, 0.0306]; n 87) |
| example | x100 | 0.0115 [0.0000, 0.0326] (L12 [0.0000, 0.0370]; L36 [0.0000, 0.0306]; n 87) |
| example | **menu** | 0.0115 [0.0000, 0.0326] (L12 [0.0000, 0.0370]; L36 [0.0000, 0.0306]; n 87) |
| tsp | x25 | 0.0000 [0.0000, 0.0000] (L12 [0.0000, 0.0000]; L36 [0.0000, 0.0000]; n 87) |
| tsp | x50 | 0.0000 [0.0000, 0.0000] (L12 [0.0000, 0.0000]; L36 [0.0000, 0.0000]; n 87) |
| tsp | x100 | 0.0000 [0.0000, 0.0000] (L12 [0.0000, 0.0000]; L36 [0.0000, 0.0000]; n 87) |
| tsp | **menu** | 0.0000 [0.0000, 0.0000] (L12 [0.0000, 0.0000]; L36 [0.0000, 0.0000]; n 87) |
| 50/50 | aggregate (never decides) | 0.0057 [0.0000, 0.0163] (L12 [0.0000, 0.0185]; L36 [0.0000, 0.0153]; n 87) |

below -20% rate (share):

| menu | risk cell | mean paired difference |
|---|---|---|
| example | x25 | 0.0000 [0.0000, 0.0000] (L12 [0.0000, 0.0000]; L36 [0.0000, 0.0000]; n 87) |
| example | x50 | 0.0000 [0.0000, 0.0000] (L12 [0.0000, 0.0000]; L36 [0.0000, 0.0000]; n 87) |
| example | x100 | 0.0000 [0.0000, 0.0000] (L12 [0.0000, 0.0000]; L36 [0.0000, 0.0000]; n 87) |
| example | **menu** | 0.0000 [0.0000, 0.0000] (L12 [0.0000, 0.0000]; L36 [0.0000, 0.0000]; n 87) |
| tsp | x25 | 0.0000 [0.0000, 0.0000] (L12 [0.0000, 0.0000]; L36 [0.0000, 0.0000]; n 87) |
| tsp | x50 | 0.0000 [0.0000, 0.0000] (L12 [0.0000, 0.0000]; L36 [0.0000, 0.0000]; n 87) |
| tsp | x100 | 0.0000 [0.0000, 0.0000] (L12 [0.0000, 0.0000]; L36 [0.0000, 0.0000]; n 87) |
| tsp | **menu** | 0.0000 [0.0000, 0.0000] (L12 [0.0000, 0.0000]; L36 [0.0000, 0.0000]; n 87) |
| 50/50 | aggregate (never decides) | 0.0000 [0.0000, 0.0000] (L12 [0.0000, 0.0000]; L36 [0.0000, 0.0000]; n 87) |

worst day (bp):

| menu | risk cell | mean paired difference |
|---|---|---|
| example | x25 | +0.45 [+0.08, +0.86] (L12 [+0.04, +0.94]; L36 [+0.12, +0.83]; n 87) |
| example | x50 | +0.54 [+0.18, +0.96] (L12 [+0.17, +1.02]; L36 [+0.20, +0.94]; n 87) |
| example | x100 | +0.49 [+0.15, +0.85] (L12 [+0.10, +0.97]; L36 [+0.19, +0.81]; n 87) |
| example | **menu** | +0.49 [+0.14, +0.89] (L12 [+0.11, +0.97]; L36 [+0.17, +0.86]; n 87) |
| tsp | x25 | +1.51 [+0.35, +3.32] (L12 [+0.40, +3.11]; L36 [+0.34, +3.32]; n 87) |
| tsp | x50 | +1.51 [+0.42, +3.18] (L12 [+0.45, +3.06]; L36 [+0.42, +3.20]; n 87) |
| tsp | x100 | +1.51 [+0.42, +3.18] (L12 [+0.45, +3.07]; L36 [+0.42, +3.20]; n 87) |
| tsp | **menu** | +1.51 [+0.40, +3.21] (L12 [+0.45, +3.07]; L36 [+0.39, +3.24]; n 87) |
| 50/50 | aggregate (never decides) | +1.00 [+0.33, +2.00] (L12 [+0.37, +1.86]; L36 [+0.32, +1.99]; n 87) |

realized volatility (bp):

| menu | risk cell | mean paired difference |
|---|---|---|
| example | x25 | -2.19 [-4.00, -0.70] (L12 [-4.21, -0.57]; L36 [-4.03, -0.83]; n 87) |
| example | x50 | -2.54 [-4.49, -1.06] (L12 [-4.48, -0.96]; L36 [-4.45, -1.13]; n 87) |
| example | x100 | -2.21 [-3.73, -0.93] (L12 [-4.14, -0.74]; L36 [-3.61, -1.07]; n 87) |
| example | **menu** | -2.31 [-4.06, -0.92] (L12 [-4.26, -0.80]; L36 [-4.04, -1.01]; n 87) |
| tsp | x25 | -5.61 [-12.20, -1.37] (L12 [-11.42, -1.65]; L36 [-12.20, -1.26]; n 87) |
| tsp | x50 | -5.66 [-11.51, -1.70] (L12 [-10.98, -1.90]; L36 [-11.58, -1.70]; n 87) |
| tsp | x100 | -5.62 [-11.48, -1.66] (L12 [-10.95, -1.87]; L36 [-11.58, -1.64]; n 87) |
| tsp | **menu** | -5.63 [-11.73, -1.60] (L12 [-11.09, -1.81]; L36 [-11.76, -1.54]; n 87) |
| 50/50 | aggregate (never decides) | -3.97 [-7.80, -1.55] (L12 [-7.18, -1.62]; L36 [-7.74, -1.50]; n 87) |

Optimization-bank (training) ΔU, bp:

| menu | risk cell | mean paired difference |
|---|---|---|
| example | x25 | -1.02 [-1.27, -0.82] (L12 [-1.26, -0.81]; L36 [-1.22, -0.82]; n 99) |
| example | x50 | -1.09 [-1.35, -0.88] (L12 [-1.33, -0.87]; L36 [-1.31, -0.89]; n 99) |
| example | x100 | -1.08 [-1.35, -0.86] (L12 [-1.33, -0.87]; L36 [-1.31, -0.87]; n 99) |
| example | **menu** | -1.07 [-1.32, -0.86] (L12 [-1.30, -0.85]; L36 [-1.28, -0.86]; n 99) |
| tsp | x25 | -1.13 [-1.26, -0.98] (L12 [-1.27, -0.97]; L36 [-1.27, -0.99]; n 99) |
| tsp | x50 | -1.10 [-1.22, -0.97] (L12 [-1.23, -0.95]; L36 [-1.22, -0.98]; n 99) |
| tsp | x100 | -1.10 [-1.22, -0.96] (L12 [-1.23, -0.94]; L36 [-1.22, -0.97]; n 99) |
| tsp | **menu** | -1.11 [-1.23, -0.97] (L12 [-1.24, -0.96]; L36 [-1.24, -0.98]; n 99) |
| 50/50 | aggregate (never decides) | -1.09 [-1.21, -0.99] (L12 [-1.21, -0.96]; L36 [-1.21, -0.99]; n 99) |

Raw DR² gain (R+D minus R):

| menu | risk cell | mean |
|---|---|---|
| example | x25 | 0.0297 [0.0135, 0.0510] (L12 [0.0150, 0.0486]; L36 [0.0129, 0.0499]; n 99) |
| example | x50 | 0.0297 [0.0141, 0.0519] (L12 [0.0149, 0.0494]; L36 [0.0141, 0.0509]; n 99) |
| example | x100 | 0.0281 [0.0134, 0.0491] (L12 [0.0139, 0.0470]; L36 [0.0134, 0.0482]; n 99) |
| example | **menu** | 0.0292 [0.0138, 0.0505] (L12 [0.0150, 0.0483]; L36 [0.0135, 0.0495]; n 99) |
| tsp | x25 | 0.0391 [0.0128, 0.0770] (L12 [0.0137, 0.0706]; L36 [0.0130, 0.0758]; n 99) |
| tsp | x50 | 0.0383 [0.0125, 0.0757] (L12 [0.0133, 0.0695]; L36 [0.0127, 0.0748]; n 99) |
| tsp | x100 | 0.0383 [0.0124, 0.0757] (L12 [0.0131, 0.0695]; L36 [0.0126, 0.0748]; n 99) |
| tsp | **menu** | 0.0386 [0.0125, 0.0762] (L12 [0.0134, 0.0699]; L36 [0.0128, 0.0751]; n 99) |
| 50/50 | aggregate (never decides) | 0.0339 [0.0137, 0.0630] (L12 [0.0145, 0.0588]; L36 [0.0135, 0.0623]; n 99) |

| menu | ΔU per test bank (bp) | L1 >= .02 | all three improve | all four improve | mean sacrifice (bp) | max sacrifice (bp) | at cap | binding guards |
|---|---|---|---|---|---|---|---|---|
| example | +0.04, -0.23, -0.04, -0.18, -0.16 | 31.3% | 8.8% | 8.8% | +1.07 | +2.50 | 0.0% | bad 0.0%, typical 0.0%, good 0.0%, u 0.0%, veto 0.0% |
| tsp | -0.19, +0.04, -0.30, -0.47, +0.06 | 17.5% | 1.0% | 1.0% | +1.11 | +2.47 | 0.0% | bad 0.0%, typical 0.0%, good 0.0%, u 0.0%, veto 0.0% |

## Realized outcomes

q(.025) and ES_2.5 superiority across origins are underpowered below 200 disjoint annual intervals.

| menu | arm | risk cell | q(.025) (underpowered) | q(.50) | q(.975) | U of the quantiles | ES_2.5 across origins (underpowered) |
|---|---|---|---|---|---|---|---|
| example | R+D@2.5bp | x25 | -14.0% | 5.9% | 17.4% | -4.9% | -14.3% |
| example | R+D@2.5bp | x50 | -13.6% | 6.1% | 19.1% | -4.4% | -14.6% |
| example | R+D@2.5bp | x100 | -13.6% | 6.1% | 18.6% | -4.5% | -14.6% |
| example | R | x25 | -14.0% | 6.1% | 17.4% | -4.9% | -14.4% |
| example | R | x50 | -13.5% | 6.1% | 19.1% | -4.3% | -14.5% |
| example | R | x100 | -13.5% | 6.1% | 18.7% | -4.4% | -14.5% |
| tsp | R+D@2.5bp | x25 | -8.1% | 5.0% | 10.5% | -2.3% | -10.1% |
| tsp | R+D@2.5bp | x50 | -9.6% | 5.0% | 10.5% | -3.2% | -12.9% |
| tsp | R+D@2.5bp | x100 | -9.6% | 5.0% | 10.5% | -3.2% | -13.1% |
| tsp | R | x25 | -8.1% | 5.0% | 10.7% | -2.3% | -10.1% |
| tsp | R | x50 | -9.7% | 5.0% | 10.7% | -3.2% | -12.9% |
| tsp | R | x100 | -9.7% | 5.0% | 10.7% | -3.2% | -13.1% |

R+D minus R, q(.025) (Bad) across origins (bp):

| menu | risk cell | contrast |
|---|---|---|
| example | x25 | -0.88 [-25.10, +15.00] (L12 [-20.10, +14.66]; L36 [-23.54, +15.47]; n 87) |
| example | x50 | -15.15 [-27.12, +15.04] (L12 [-21.73, +15.18]; L36 [-26.85, +15.47]; n 87) |
| example | x100 | -15.15 [-27.12, +15.04] (L12 [-21.73, +15.18]; L36 [-26.85, +15.47]; n 87) |
| example | **menu** | -10.40 [-26.25, +14.99] (L12 [-19.57, +14.31]; L36 [-24.96, +15.47]; n 87) |
| tsp | x25 | -0.20 [-1.36, +41.93] (L12 [-3.69, +38.74]; L36 [-1.28, +33.42]; n 87) |
| tsp | x50 | +3.60 [-3.77, +41.93] (L12 [-3.77, +38.74]; L36 [-3.77, +33.42]; n 87) |
| tsp | x100 | +3.60 [-1.35, +41.93] (L12 [-3.69, +38.74]; L36 [-1.28, +33.42]; n 87) |
| tsp | **menu** | +2.34 [-1.29, +41.93] (L12 [-3.69, +38.74]; L36 [-1.13, +33.42]; n 87) |
| 50/50 | aggregate (never decides) | -4.03 [-7.32, +18.80] (L12 [-7.30, +20.63]; L36 [-6.45, +18.31]; n 87) |

R+D minus R, q(.50) (Typical) across origins (bp):

| menu | risk cell | contrast |
|---|---|---|
| example | x25 | -12.44 [-25.75, +16.22] (L12 [-31.77, +17.98]; L36 [-24.89, +14.74]; n 87) |
| example | x50 | +0.43 [-25.13, +16.92] (L12 [-29.81, +17.99]; L36 [-25.13, +14.73]; n 87) |
| example | x100 | +0.43 [-25.13, +15.24] (L12 [-29.81, +16.00]; L36 [-25.13, +14.73]; n 87) |
| example | **menu** | -3.86 [-24.45, +15.02] (L12 [-28.62, +15.51]; L36 [-24.37, +14.73]; n 87) |
| tsp | x25 | -1.27 [-9.97, +7.58] (L12 [-9.86, +7.58]; L36 [-9.63, +7.15]; n 87) |
| tsp | x50 | +0.19 [-11.46, +7.58] (L12 [-11.69, +7.58]; L36 [-11.70, +7.58]; n 87) |
| tsp | x100 | +0.19 [-11.46, +7.58] (L12 [-11.69, +7.58]; L36 [-11.70, +7.58]; n 87) |
| tsp | **menu** | -0.30 [-10.49, +6.37] (L12 [-10.53, +6.61]; L36 [-10.75, +6.31]; n 87) |
| 50/50 | aggregate (never decides) | -2.08 [-14.28, +8.71] (L12 [-16.21, +9.15]; L36 [-14.64, +8.06]; n 87) |

R+D minus R, q(.975) (Good) across origins (bp):

| menu | risk cell | contrast |
|---|---|---|
| example | x25 | -1.56 [-38.32, +5.36] (L12 [-50.99, +5.36]; L36 [-42.77, +5.26]; n 87) |
| example | x50 | -1.71 [-31.80, +8.02] (L12 [-37.99, +8.02]; L36 [-38.06, +7.62]; n 87) |
| example | x100 | -4.61 [-32.60, +5.91] (L12 [-37.99, +4.01]; L36 [-38.06, +4.72]; n 87) |
| example | **menu** | -2.63 [-32.29, +4.80] (L12 [-42.08, +4.08]; L36 [-41.93, +4.25]; n 87) |
| tsp | x25 | -13.02 [-30.02, +24.37] (L12 [-28.06, +24.37]; L36 [-26.79, +20.11]; n 87) |
| tsp | x50 | -12.19 [-35.05, +15.05] (L12 [-35.05, +15.05]; L36 [-28.83, +15.05]; n 87) |
| tsp | x100 | -12.19 [-35.05, +15.05] (L12 [-35.05, +15.05]; L36 [-28.83, +15.05]; n 87) |
| tsp | **menu** | -12.47 [-15.24, +15.05] (L12 [-15.24, +15.05]; L36 [-15.24, +15.05]; n 87) |
| 50/50 | aggregate (never decides) | -7.55 [-18.94, +6.86] (L12 [-19.72, +7.14]; L36 [-19.22, +5.18]; n 87) |

R+D minus R, U of the quantiles across origins (bp):

| menu | risk cell | contrast |
|---|---|---|
| example | x25 | -4.42 [-15.78, +8.54] (L12 [-13.99, +8.79]; L36 [-15.55, +8.75]; n 87) |
| example | x50 | -9.13 [-17.77, +10.69] (L12 [-17.81, +10.69]; L36 [-17.83, +10.39]; n 87) |
| example | x100 | -9.42 [-17.75, +10.98] (L12 [-17.47, +10.90]; L36 [-17.73, +10.59]; n 87) |
| example | **menu** | -7.66 [-16.33, +9.71] (L12 [-15.59, +9.65]; L36 [-16.25, +9.57]; n 87) |
| tsp | x25 | -1.80 [-4.39, +23.12] (L12 [-5.15, +22.65]; L36 [-3.90, +19.85]; n 87) |
| tsp | x50 | +1.00 [-5.18, +22.11] (L12 [-6.08, +22.75]; L36 [-5.10, +18.83]; n 87) |
| tsp | x100 | +1.00 [-4.12, +22.11] (L12 [-5.43, +22.75]; L36 [-4.07, +18.83]; n 87) |
| tsp | **menu** | +0.06 [-3.84, +22.40] (L12 [-4.98, +22.68]; L36 [-3.54, +19.28]; n 87) |
| 50/50 | aggregate (never decides) | -3.80 [-7.14, +9.59] (L12 [-7.84, +12.06]; L36 [-7.38, +10.45]; n 87) |

R+D minus R, ES_2.5 across origins (bp):

| menu | risk cell | contrast |
|---|---|---|
| example | x25 | +1.06 [-25.25, +6.84] (L12 [-11.60, +7.24]; L36 [-25.50, +7.24]; n 87) |
| example | x50 | -2.23 [-25.25, +7.61] (L12 [-11.69, +7.61]; L36 [-25.50, +7.61]; n 87) |
| example | x100 | -2.23 [-25.25, +7.61] (L12 [-11.69, +7.61]; L36 [-25.50, +7.61]; n 87) |
| example | **menu** | -1.13 [-25.25, +6.72] (L12 [-11.66, +7.24]; L36 [-25.50, +7.24]; n 87) |
| tsp | x25 | +0.12 [-0.61, +45.59] (L12 [-1.41, +41.27]; L36 [-0.59, +48.12]; n 87) |
| tsp | x50 | +1.52 [-1.55, +45.59] (L12 [-2.23, +41.27]; L36 [-1.19, +48.12]; n 87) |
| tsp | x100 | +2.81 [-0.85, +45.59] (L12 [-1.45, +41.27]; L36 [-0.59, +48.12]; n 87) |
| tsp | **menu** | +1.48 [-0.93, +45.59] (L12 [-1.45, +41.27]; L36 [-0.59, +48.12]; n 87) |
| 50/50 | aggregate (never decides) | +0.17 [-1.74, +17.89] (L12 [-3.51, +21.12]; L36 [-1.06, +17.02]; n 87) |

Realized guardrails and benefit support (99% intervals at block 24):

| menu | location | test | value | threshold | result |
|---|---|---|---|---|---|
| example | x25 | annual-return median loss <= 25 bp | 0.0012440413065808453 | 0.0025 | pass |
| example | x25 | mean annual-return loss <= 25 bp | 0.00037240098849748634 | 0.0025 | pass |
| example | x25 | loss-frequency increase <= 5 pp | 0.011494252873563232 | 0.05 | pass |
| example | x25 | mean maximum-drawdown worsening <= 1 pp | -0.00020235580029417336 | 0.01 | pass |
| example | x50 | annual-return median loss <= 25 bp | -4.2927309989337914e-05 | 0.0025 | pass |
| example | x50 | mean annual-return loss <= 25 bp | 0.000337307058959412 | 0.0025 | pass |
| example | x50 | loss-frequency increase <= 5 pp | 0.011494252873563232 | 0.05 | pass |
| example | x50 | mean maximum-drawdown worsening <= 1 pp | -0.00026980370797230545 | 0.01 | pass |
| example | x100 | annual-return median loss <= 25 bp | -4.2927309989337914e-05 | 0.0025 | pass |
| example | x100 | mean annual-return loss <= 25 bp | 0.00034075211682909977 | 0.0025 | pass |
| example | x100 | loss-frequency increase <= 5 pp | 0.011494252873563232 | 0.05 | pass |
| example | x100 | mean maximum-drawdown worsening <= 1 pp | -0.00022556907132168628 | 0.01 | pass |
| example | menu | mean paired realized annual-return gain >= 25 bp | -0.00035015338809533275 | 0.0025 | FAIL |
| example | menu | its 99% interval lower bound > 0 | -0.0007543324223550058 | 0.0 | FAIL |
| example | menu | mean maximum-drawdown improvement >= 1 pp | 0.000232576193196055 | 0.01 | FAIL |
| example | menu | its 99% improvement lower bound > 0 | -4.745444316192855e-05 | 0.0 | FAIL |
| example | menu | mean annual-return loss <= 25 bp (drawdown route) | 0.00035015338809533275 | 0.0025 | pass |
| example | menu | disjoint annual intervals >= 20 | 7.0 | 20 | FAIL |
| example | menu | every realized guardrail holds (risk cells breaching) | 0.0 | 0.0 | pass |
| tsp | x25 | annual-return median loss <= 25 bp | 0.0001265638749619047 | 0.0025 | pass |
| tsp | x25 | mean annual-return loss <= 25 bp | 3.071940945878386e-05 | 0.0025 | pass |
| tsp | x25 | loss-frequency increase <= 5 pp | 0.0 | 0.05 | pass |
| tsp | x25 | mean maximum-drawdown worsening <= 1 pp | -0.0005678214076998358 | 0.01 | pass |
| tsp | x50 | annual-return median loss <= 25 bp | -1.8502106381212968e-05 | 0.0025 | pass |
| tsp | x50 | mean annual-return loss <= 25 bp | 6.032116372968737e-05 | 0.0025 | pass |
| tsp | x50 | loss-frequency increase <= 5 pp | 0.0 | 0.05 | pass |
| tsp | x50 | mean maximum-drawdown worsening <= 1 pp | -0.000561503630989836 | 0.01 | pass |
| tsp | x100 | annual-return median loss <= 25 bp | -1.8502106381212968e-05 | 0.0025 | pass |
| tsp | x100 | mean annual-return loss <= 25 bp | 5.5880594076596836e-05 | 0.0025 | pass |
| tsp | x100 | loss-frequency increase <= 5 pp | 0.0 | 0.05 | pass |
| tsp | x100 | mean maximum-drawdown worsening <= 1 pp | -0.000567457655642311 | 0.01 | pass |
| tsp | menu | mean paired realized annual-return gain >= 25 bp | -4.897372242168935e-05 | 0.0025 | FAIL |
| tsp | menu | its 99% interval lower bound > 0 | -0.0003735905185334425 | 0.0 | FAIL |
| tsp | menu | mean maximum-drawdown improvement >= 1 pp | 0.0005655942314439943 | 0.01 | FAIL |
| tsp | menu | its 99% improvement lower bound > 0 | 6.923143006991653e-05 | 0.0 | pass |
| tsp | menu | mean annual-return loss <= 25 bp (drawdown route) | 4.897372242168935e-05 | 0.0025 | pass |
| tsp | menu | disjoint annual intervals >= 20 | 7.0 | 20 | FAIL |
| tsp | menu | every realized guardrail holds (risk cells breaching) | 0.0 | 0.0 | pass |

## Forecast-error diagnostic (mechanism (a); not a gate)

| menu | risk cell | correlation | sign | 95% interval | n |
|---|---|---|---|---|---|
| example | x25 | -0.0765 | -1 | [-0.1854, -0.0156] | 87 |
| example | x50 | -0.0767 | -1 | [-0.1957, 0.0105] | 87 |
| example | x100 | -0.0730 | -1 | [-0.1754, 0.0080] | 87 |
| tsp | x25 | -0.0278 | -1 | [-0.3467, 0.1980] | 87 |
| tsp | x50 | -0.0808 | -1 | [-0.5437, 0.0308] | 87 |
| tsp | x100 | -0.0909 | -1 | [-0.5437, 0.0055] | 87 |

## Calibration (forecast honesty; never used to select)

Lower pinball loss for a near-cash allocation does not establish a better portfolio. q(.025) calibration is underpowered below 200 disjoint intervals.

| menu | arm | forecast | q | coverage | pinball | n |
|---|---|---|---|---|---|---|
| example | R | train | B q(0.025) | 0.103 | 0.00755 | 87 |
| example | R | train | T q(0.5) | 0.245 | 0.02539 | 87 |
| example | R | train | G q(0.975) | 0.931 | 0.00268 | 87 |
| example | R | test | B q(0.025) | 0.103 | 0.00716 | 87 |
| example | R | test | T q(0.5) | 0.234 | 0.02550 | 87 |
| example | R | test | G q(0.975) | 0.943 | 0.00267 | 87 |
| example | R+D@2.5bp | train | B q(0.025) | 0.103 | 0.00759 | 87 |
| example | R+D@2.5bp | train | T q(0.5) | 0.245 | 0.02530 | 87 |
| example | R+D@2.5bp | train | G q(0.975) | 0.931 | 0.00266 | 87 |
| example | R+D@2.5bp | test | B q(0.025) | 0.103 | 0.00719 | 87 |
| example | R+D@2.5bp | test | T q(0.5) | 0.245 | 0.02541 | 87 |
| example | R+D@2.5bp | test | G q(0.975) | 0.943 | 0.00264 | 87 |
| example | frontier | train | B q(0.025) | 0.054 | 0.00940 | 87 |
| example | frontier | train | T q(0.5) | 0.356 | 0.05011 | 87 |
| example | frontier | train | G q(0.975) | 0.969 | 0.00636 | 87 |
| example | frontier | test | B q(0.025) | 0.057 | 0.00940 | 87 |
| example | frontier | test | T q(0.5) | 0.345 | 0.05016 | 87 |
| example | frontier | test | G q(0.975) | 0.969 | 0.00631 | 87 |
| example | mdp | train | B q(0.025) | 0.054 | 0.00950 | 87 |
| example | mdp | train | T q(0.5) | 0.398 | 0.04511 | 87 |
| example | mdp | train | G q(0.975) | 0.973 | 0.00605 | 87 |
| example | mdp | test | B q(0.025) | 0.057 | 0.00930 | 87 |
| example | mdp | test | T q(0.5) | 0.395 | 0.04498 | 87 |
| example | mdp | test | G q(0.975) | 0.973 | 0.00610 | 87 |
| example | min_variance | train | B q(0.025) | 0.126 | 0.00582 | 87 |
| example | min_variance | train | T q(0.5) | 0.299 | 0.01569 | 87 |
| example | min_variance | train | G q(0.975) | 0.874 | 0.00273 | 87 |
| example | min_variance | test | B q(0.025) | 0.126 | 0.00567 | 87 |
| example | min_variance | test | T q(0.5) | 0.287 | 0.01576 | 87 |
| example | min_variance | test | G q(0.975) | 0.874 | 0.00276 | 87 |
| example | equal_weight | train | B q(0.025) | 0.034 | 0.00690 | 87 |
| example | equal_weight | train | T q(0.5) | 0.333 | 0.04109 | 87 |
| example | equal_weight | train | G q(0.975) | 0.954 | 0.00678 | 87 |
| example | equal_weight | test | B q(0.025) | 0.034 | 0.00662 | 87 |
| example | equal_weight | test | T q(0.5) | 0.322 | 0.04105 | 87 |
| example | equal_weight | test | G q(0.975) | 0.966 | 0.00663 | 87 |
| tsp | R | train | B q(0.025) | 0.069 | 0.00441 | 87 |
| tsp | R | train | T q(0.5) | 0.287 | 0.01438 | 87 |
| tsp | R | train | G q(0.975) | 0.954 | 0.00165 | 87 |
| tsp | R | test | B q(0.025) | 0.069 | 0.00416 | 87 |
| tsp | R | test | T q(0.5) | 0.299 | 0.01439 | 87 |
| tsp | R | test | G q(0.975) | 0.954 | 0.00164 | 87 |
| tsp | R+D@2.5bp | train | B q(0.025) | 0.069 | 0.00442 | 87 |
| tsp | R+D@2.5bp | train | T q(0.5) | 0.264 | 0.01431 | 87 |
| tsp | R+D@2.5bp | train | G q(0.975) | 0.954 | 0.00165 | 87 |
| tsp | R+D@2.5bp | test | B q(0.025) | 0.069 | 0.00418 | 87 |
| tsp | R+D@2.5bp | test | T q(0.5) | 0.276 | 0.01432 | 87 |
| tsp | R+D@2.5bp | test | G q(0.975) | 0.954 | 0.00164 | 87 |
| tsp | frontier | train | B q(0.025) | 0.065 | 0.00842 | 87 |
| tsp | frontier | train | T q(0.5) | 0.280 | 0.05251 | 87 |
| tsp | frontier | train | G q(0.975) | 0.958 | 0.00860 | 87 |
| tsp | frontier | test | B q(0.025) | 0.073 | 0.00839 | 87 |
| tsp | frontier | test | T q(0.5) | 0.276 | 0.05235 | 87 |
| tsp | frontier | test | G q(0.975) | 0.954 | 0.00874 | 87 |
| tsp | mdp | train | B q(0.025) | 0.054 | 0.00864 | 87 |
| tsp | mdp | train | T q(0.5) | 0.326 | 0.05566 | 87 |
| tsp | mdp | train | G q(0.975) | 0.950 | 0.01052 | 87 |
| tsp | mdp | test | B q(0.025) | 0.065 | 0.00881 | 87 |
| tsp | mdp | test | T q(0.5) | 0.307 | 0.05553 | 87 |
| tsp | mdp | test | G q(0.975) | 0.946 | 0.01073 | 87 |
| tsp | min_variance | train | B q(0.025) | 0.126 | 0.00329 | 87 |
| tsp | min_variance | train | T q(0.5) | 0.345 | 0.00952 | 87 |
| tsp | min_variance | train | G q(0.975) | 0.885 | 0.00141 | 87 |
| tsp | min_variance | test | B q(0.025) | 0.126 | 0.00326 | 87 |
| tsp | min_variance | test | T q(0.5) | 0.345 | 0.00951 | 87 |
| tsp | min_variance | test | G q(0.975) | 0.885 | 0.00137 | 87 |
| tsp | equal_weight | train | B q(0.025) | 0.034 | 0.00646 | 87 |
| tsp | equal_weight | train | T q(0.5) | 0.310 | 0.04646 | 87 |
| tsp | equal_weight | train | G q(0.975) | 0.943 | 0.00795 | 87 |
| tsp | equal_weight | test | B q(0.025) | 0.046 | 0.00646 | 87 |
| tsp | equal_weight | test | T q(0.5) | 0.322 | 0.04643 | 87 |
| tsp | equal_weight | test | G q(0.975) | 0.943 | 0.00804 | 87 |

## Stability across the optimizer seeds

| menu | arm | risk cell | median L1 | p90 L1 | Bad SD <= .1 vol | turnover (all seeds) | turnover (primary) | median seed SD (bp) | median SD across the 5 banks (bp, primary seed's fixed weights) |
|---|---|---|---|---|---|---|---|---|---|
| example | R | x25 | 0.1775 | 0.7333 | 72.7% | 0.0767 | 0.0771 | B +18.21, T +19.77, G +60.40, U +5.36, ES_2.5 +27.59 | B +25.52, T +10.89, G +24.50, U +17.16, ES_2.5 +29.12 |
| example | R | x50 | 0.1765 | 0.7954 | 69.7% | 0.0889 | 0.1014 | B +22.57, T +21.52, G +62.85, U +5.46, ES_2.5 +30.42 | B +23.51, T +11.37, G +25.60, U +16.02, ES_2.5 +28.96 |
| example | R | x100 | 0.1750 | 0.7464 | 69.7% | 0.0884 | 0.0992 | B +22.57, T +21.52, G +62.85, U +5.36, ES_2.5 +30.74 | B +23.56, T +11.37, G +25.60, U +16.02, ES_2.5 +28.96 |
| example | R+D | x25 | 0.1683 | 0.7265 | 72.7% | 0.0750 | 0.0694 | B +18.53, T +18.98, G +59.42, U +5.87, ES_2.5 +26.08 | B +25.99, T +11.41, G +25.37, U +17.59, ES_2.5 +29.00 |
| example | R+D | x50 | 0.1701 | 0.7744 | 69.7% | 0.0846 | 0.0846 | B +23.02, T +21.30, G +59.74, U +5.68, ES_2.5 +31.58 | B +23.69, T +11.71, G +26.57, U +16.42, ES_2.5 +29.11 |
| example | R+D | x100 | 0.1683 | 0.7351 | 69.7% | 0.0847 | 0.0849 | B +23.02, T +21.30, G +59.74, U +5.68, ES_2.5 +31.58 | B +23.69, T +11.41, G +26.57, U +16.42, ES_2.5 +29.11 |
| tsp | R | x25 | 0.0683 | 0.2694 | 46.5% | 0.0416 | 0.0438 | B +27.52, T +27.83, G +72.71, U +2.74, ES_2.5 +39.86 | B +16.95, T +6.50, G +14.39, U +11.36, ES_2.5 +21.03 |
| tsp | R | x50 | 0.0690 | 0.3377 | 46.5% | 0.0424 | 0.0438 | B +28.43, T +28.35, G +73.09, U +2.90, ES_2.5 +40.62 | B +17.11, T +6.51, G +14.39, U +11.11, ES_2.5 +21.24 |
| tsp | R | x100 | 0.0692 | 0.3377 | 46.5% | 0.0424 | 0.0438 | B +28.43, T +28.35, G +73.09, U +2.90, ES_2.5 +40.62 | B +17.11, T +6.51, G +14.39, U +11.11, ES_2.5 +21.24 |
| tsp | R+D | x25 | 0.0678 | 0.2723 | 44.4% | 0.0391 | 0.0406 | B +26.31, T +27.04, G +68.56, U +2.65, ES_2.5 +37.07 | B +16.91, T +6.45, G +14.48, U +11.05, ES_2.5 +20.88 |
| tsp | R+D | x50 | 0.0697 | 0.3357 | 43.4% | 0.0393 | 0.0408 | B +27.41, T +28.86, G +68.56, U +2.94, ES_2.5 +40.35 | B +16.93, T +6.46, G +14.68, U +10.95, ES_2.5 +21.62 |
| tsp | R+D | x100 | 0.0697 | 0.3357 | 43.4% | 0.0393 | 0.0408 | B +27.41, T +28.86, G +68.56, U +2.94, ES_2.5 +40.35 | B +16.93, T +6.46, G +14.68, U +10.95, ES_2.5 +21.62 |

Selection and guard frequencies of R+D at 2.5 bp, every optimizer seed:

| menu | risk cell | cells | R+D = w_R | binding guards |
|---|---|---|---|---|
| example | x25 | 495 | 9.3% | bad 0.0%, typical 0.0%, good 0.0%, u 0.0%, veto 0.0% |
| example | x50 | 495 | 7.7% | bad 0.0%, typical 0.0%, good 0.0%, u 0.0%, veto 0.0% |
| example | x100 | 495 | 7.7% | bad 0.0%, typical 0.0%, good 0.0%, u 0.0%, veto 0.0% |
| tsp | x25 | 495 | 3.2% | bad 0.0%, typical 0.0%, good 0.0%, u 0.0%, veto 0.0% |
| tsp | x50 | 495 | 3.0% | bad 0.0%, typical 0.0%, good 0.0%, u 0.0%, veto 0.0% |
| tsp | x100 | 495 | 3.2% | bad 0.0%, typical 0.0%, good 0.0%, u 0.0%, veto 0.0% |

## Native-search selections (diagnostic; the union selections are primary)

ΔU (R+D:native minus R:native, bp):

| menu | risk cell | mean |
|---|---|---|
| example | x25 | -1.31 [-3.05, +0.20] (L12 [-3.20, +0.26]; L36 [-3.04, +0.23]; n 99) |
| example | x50 | -1.31 [-3.80, +0.61] (L12 [-4.09, +0.86]; L36 [-3.64, +0.60]; n 99) |
| example | x100 | -1.23 [-3.69, +0.69] (L12 [-3.99, +0.90]; L36 [-3.57, +0.62]; n 99) |
| example | **menu** | -1.28 [-3.48, +0.43] (L12 [-3.71, +0.58]; L36 [-3.42, +0.42]; n 99) |
| tsp | x25 | -2.07 [-2.71, -1.42] (L12 [-2.83, -1.31]; L36 [-2.51, -1.66]; n 99) |
| tsp | x50 | -1.92 [-2.64, -1.20] (L12 [-2.77, -1.03]; L36 [-2.46, -1.36]; n 99) |
| tsp | x100 | -1.87 [-2.59, -1.14] (L12 [-2.75, -0.96]; L36 [-2.40, -1.32]; n 99) |
| tsp | **menu** | -1.95 [-2.64, -1.28] (L12 [-2.78, -1.13]; L36 [-2.44, -1.47]; n 99) |
| 50/50 | aggregate (never decides) | -1.62 [-2.75, -0.64] (L12 [-2.82, -0.53]; L36 [-2.70, -0.74]; n 99) |

ΔB (R+D:native minus R:native, bp):

| menu | risk cell | mean |
|---|---|---|
| example | x25 | +3.40 [-1.63, +8.71] (L12 [-1.96, +9.06]; L36 [-1.50, +8.56]; n 99) |
| example | x50 | +9.94 [+0.30, +23.37] (L12 [+0.47, +22.83]; L36 [+0.21, +21.64]; n 99) |
| example | x100 | +7.34 [-5.73, +22.39] (L12 [-4.82, +21.84]; L36 [-6.11, +21.64]; n 99) |
| example | **menu** | +6.89 [-2.09, +17.73] (L12 [-1.62, +17.59]; L36 [-2.40, +17.27]; n 99) |
| tsp | x25 | -1.12 [-6.70, +5.12] (L12 [-6.56, +4.52]; L36 [-6.59, +5.03]; n 99) |
| tsp | x50 | -0.98 [-11.61, +8.98] (L12 [-10.41, +7.42]; L36 [-11.73, +9.61]; n 99) |
| tsp | x100 | +0.17 [-9.10, +8.98] (L12 [-8.43, +7.97]; L36 [-9.19, +9.61]; n 99) |
| tsp | **menu** | -0.64 [-8.82, +7.40] (L12 [-8.14, +6.35]; L36 [-8.76, +7.74]; n 99) |
| 50/50 | aggregate (never decides) | +3.13 [+1.10, +5.50] (L12 [+0.44, +6.49]; L36 [+1.34, +4.82]; n 99) |

ΔT (R+D:native minus R:native, bp):

| menu | risk cell | mean |
|---|---|---|
| example | x25 | -5.96 [-11.04, -0.45] (L12 [-11.58, -0.66]; L36 [-10.64, -0.41]; n 99) |
| example | x50 | -12.88 [-25.66, -1.81] (L12 [-25.43, -2.41]; L36 [-23.68, -1.94]; n 99) |
| example | x100 | -10.17 [-25.08, +4.54] (L12 [-24.62, +2.89]; L36 [-23.65, +4.65]; n 99) |
| example | **menu** | -9.67 [-20.40, +0.51] (L12 [-20.24, -0.27]; L36 [-19.08, +0.72]; n 99) |
| tsp | x25 | -3.06 [-9.78, +3.13] (L12 [-9.01, +3.19]; L36 [-9.53, +2.91]; n 99) |
| tsp | x50 | -2.56 [-12.37, +8.82] (L12 [-10.95, +7.57]; L36 [-12.70, +8.67]; n 99) |
| tsp | x100 | -3.66 [-12.70, +6.48] (L12 [-11.37, +5.85]; L36 [-12.84, +6.29]; n 99) |
| tsp | **menu** | -3.09 [-11.30, +6.06] (L12 [-10.07, +5.12]; L36 [-11.68, +5.70]; n 99) |
| 50/50 | aggregate (never decides) | -6.38 [-8.76, -4.15] (L12 [-9.80, -3.43]; L36 [-8.15, -4.48]; n 99) |

ΔG (R+D:native minus R:native, bp):

| menu | risk cell | mean |
|---|---|---|
| example | x25 | -15.55 [-27.78, -2.30] (L12 [-30.11, -1.81]; L36 [-27.71, -2.03]; n 99) |
| example | x50 | -34.10 [-62.78, -7.45] (L12 [-64.49, -8.18]; L36 [-58.71, -7.57]; n 99) |
| example | x100 | -25.90 [-61.92, +11.57] (L12 [-62.12, +8.39]; L36 [-58.67, +11.75]; n 99) |
| example | **menu** | -25.19 [-49.97, +0.03] (L12 [-51.05, -2.00]; L36 [-47.44, +0.80]; n 99) |
| tsp | x25 | -4.81 [-23.11, +10.87] (L12 [-20.75, +12.09]; L36 [-22.09, +10.35]; n 99) |
| tsp | x50 | -5.67 [-32.44, +23.37] (L12 [-27.98, +20.49]; L36 [-33.65, +23.73]; n 99) |
| tsp | x100 | -8.72 [-32.63, +17.02] (L12 [-29.56, +15.34]; L36 [-33.65, +16.72]; n 99) |
| tsp | **menu** | -6.40 [-28.15, +16.75] (L12 [-25.19, +14.37]; L36 [-29.44, +15.63]; n 99) |
| 50/50 | aggregate (never decides) | -15.79 [-21.96, -9.96] (L12 [-24.62, -7.76]; L36 [-20.65, -10.83]; n 99) |

ΔES_2.5 (R+D:native minus R:native, bp):

| menu | risk cell | mean |
|---|---|---|
| example | x25 | +6.59 [-1.33, +15.14] (L12 [-1.84, +15.38]; L36 [-1.78, +15.02]; n 99) |
| example | x50 | +15.55 [+1.09, +34.63] (L12 [+1.59, +34.11]; L36 [+0.81, +32.97]; n 99) |
| example | x100 | +11.97 [-7.24, +33.93] (L12 [-5.34, +32.61]; L36 [-8.29, +32.97]; n 99) |
| example | **menu** | +11.37 [-2.32, +27.47] (L12 [-1.33, +26.83]; L36 [-2.92, +26.86]; n 99) |
| tsp | x25 | -0.64 [-8.41, +7.66] (L12 [-8.48, +7.01]; L36 [-8.29, +7.56]; n 99) |
| tsp | x50 | -0.48 [-15.42, +13.24] (L12 [-13.59, +11.15]; L36 [-15.93, +14.07]; n 99) |
| tsp | x100 | +1.05 [-12.19, +13.37] (L12 [-10.98, +11.73]; L36 [-12.36, +14.07]; n 99) |
| tsp | **menu** | -0.02 [-11.76, +11.12] (L12 [-10.43, +9.63]; L36 [-11.69, +11.56]; n 99) |
| 50/50 | aggregate (never decides) | +5.67 [+2.64, +9.29] (L12 [+1.80, +10.55]; L36 [+3.11, +8.47]; n 99) |

## Sensitivities (side by side; none is a headline)

Six origins 2018-06, 2020-01, 2021-09, 2023-05, 2025-01, 2026-09; primary only; cross-seed stability is unavailable for every setting. Each setting is assessed with the replay criteria on these origins, its sign against the Stage 1 row (Stage 1 on the same six origins, R27); a disclosure blocks Stage 2 progression, never the 0 bp diagnostic control (R26).

| menu | setting | ΔU | ΔB | ΔT | ΔG | ΔES | banks ΔU > 0 | Stage 2 | disclosure |
|---|---|---|---|---|---|---|---|---|---|
| example | Stage 1 (2.5 bp) | +0.77 | +1.49 | +0.08 | -1.49 | +1.47 |  |  |  |
| example | cap-0bp | +0.00 | +0.00 | +0.00 | +0.00 | +0.00 | 0 | not assessed: no qualifying branch | a diagnostic control, inert by construction (R+D = w_R or a 1e-12 U tie): never blocks Stage 2 (protocol amendment R26) |
| example | cap-5bp | -0.92 | +1.37 | -2.32 | -10.43 | +3.10 | 1 | not assessed: no qualifying branch |  |
| example | cap-10bp | -1.87 | +0.11 | -3.12 | -9.98 | +1.80 | 0 | not assessed: no qualifying branch |  |
| example | coefficients-70-20-10 | +1.05 | +0.75 | +1.18 | +2.94 | -1.67 | 0 | not assessed: no qualifying branch |  |
| example | coefficients-50-35-15 | -1.03 | +0.04 | -1.72 | -3.01 | +0.48 | 1 | not assessed: no qualifying branch |  |
| example | lookback-252 | -0.34 | +0.54 | -1.25 | -2.83 | +0.79 | 0 | not assessed: no qualifying branch |  |
| example | budget-x2 | -0.19 | +0.65 | -0.59 | -3.96 | +1.09 | 3 | not assessed: no qualifying branch |  |
| tsp | Stage 1 (2.5 bp) | +0.52 | +5.78 | -5.48 | -13.05 | +7.62 |  |  |  |
| tsp | cap-0bp | +0.00 | +0.00 | +0.00 | +0.00 | +0.00 | 0 | not assessed: no qualifying branch | a diagnostic control, inert by construction (R+D = w_R or a 1e-12 U tie): never blocks Stage 2 (protocol amendment R26) |
| tsp | cap-5bp | -0.19 | +7.76 | -9.32 | -20.50 | +10.82 | 1 | not assessed: no qualifying branch |  |
| tsp | cap-10bp | -2.03 | +7.56 | -13.63 | -24.81 | +10.02 | 0 | not assessed: no qualifying branch |  |
| tsp | coefficients-70-20-10 | -1.80 | +0.68 | -5.60 | -11.57 | +2.71 | 0 | not assessed: no qualifying branch |  |
| tsp | coefficients-50-35-15 | -2.30 | +7.09 | -8.13 | -19.96 | +10.29 | 0 | not assessed: no qualifying branch |  |
| tsp | lookback-252 | -2.78 | -1.36 | -4.05 | -7.48 | +0.20 | 0 | not assessed: no qualifying branch |  |
| tsp | budget-x2 | +0.97 | +7.83 | -6.68 | -17.26 | +9.90 | 2 | not assessed: no qualifying branch |  |

## Cost

search cost = an arm's warm wall time from its fresh cache to its native selection (replay scoring 'return_evaluation', measure scoring 'score', the native selection on its own archive 'native_selection' net of its scoring, solver and overhead 'solver'); shared preprocessing and broad search, union rescoring and independent evaluation are charged separately; failed calls are inside the arm wall and counted under 'invalid'; an arm stopped at the time ceiling counts what it did.

| menu | arm | wall median (s) | wall p95 (s) | replay scoring (s) | measure scoring (s) | native selection (s) | solver (s) | invalid calls | failed starts |
|---|---|---|---|---|---|---|---|---|---|
| example | R | 26.54 | 65.42 | 4932.4 | 0.0 | 64.2 | 44551.7 | 637951 | 0 |
| example | R+D | 26.60 | 65.50 | 5890.3 | 262.8 | 778.5 | 42791.3 | 691604 | 0 |
| tsp | R | 2.05 | 3.57 | 1430.0 | 0.0 | 24.2 | 1859.6 | 93351 | 0 |
| tsp | R+D | 2.77 | 4.88 | 1724.9 | 88.1 | 289.5 | 2360.6 | 104666 | 0 |

| menu | cells | R+D/R ratio median | ratio p95 | shared (s) | union (s) | failed cells (s) |
|---|---|---|---|---|---|---|
| example | 1485 | 1.000 | 1.382 | 8147.6 | 365.6 | 0.0 |
| tsp | 1485 | 1.324 | 2.058 | 6820.1 | 127.9 | 0.0 |

CPU hours: Stage 1 35.420, sensitivities {'coefficients': 0.6305666666666666, 'lookback': 0.25108055555555553, 'budget': 0.3442694444444444}, total 36.646 against the 240.0 h ceiling (amended: False). Independent evaluation: {'groups': 198, 'mixes': 35640, 'wall': 1000.2207869461272, 'cpu': 999.1374437999875}. Every paired ratio is in summary.json (cost.stage_1.<menu>.paired_wall_ratios).

## Every threshold result (protocol 7)

| menu | dimension | location | test | value | threshold | result | reason |
|---|---|---|---|---|---|---|---|
| example | Independent replay return gain | menu | pooled mean paired ΔU >= 5 bp | -2.7778969422340675e-05 | 0.0005 | FAIL |  |
| example | Independent replay return gain | menu | mean paired ΔB >= -5 bp | 9.251714876305048e-05 | -0.0005 | pass |  |
| example | Independent replay return gain | menu | mean paired ΔT >= -10 bp | -0.00012063730858555781 | -0.001 | pass |  |
| example | Independent replay return gain | menu | mean paired ΔG >= -20 bp | -0.00047098066104503644 | -0.002 | pass |  |
| example | Independent replay return gain | x25 | risk-cell mean ΔU >= -2.5 bp | -3.616294282410852e-05 | -0.00025 | pass |  |
| example | Independent replay return gain | x50 | risk-cell mean ΔU >= -2.5 bp | -2.8131555372820797e-05 | -0.00025 | pass |  |
| example | Independent replay return gain | x100 | risk-cell mean ΔU >= -2.5 bp | -1.9042410070092715e-05 | -0.00025 | pass |  |
| example | Independent replay return gain | menu | test banks with positive mean ΔU >= 4 of 5 | 1.0 | 4 | FAIL |  |
| example | Stable gain alternative | menu | pooled mean paired ΔU >= -2.5 bp | -2.7778969422340675e-05 | -0.00025 | pass |  |
| example | Stable gain alternative | menu | mean paired ΔB >= -5 bp | 9.251714876305048e-05 | -0.0005 | pass |  |
| example | Stable gain alternative | menu | mean paired ΔT >= -10 bp | -0.00012063730858555781 | -0.001 | pass |  |
| example | Stable gain alternative | menu | mean paired ΔG >= -20 bp | -0.00047098066104503644 | -0.002 | pass |  |
| example | Stable gain alternative | x25 | risk-cell mean ΔU >= -2.5 bp | -3.616294282410852e-05 | -0.00025 | pass |  |
| example | Stable gain alternative | x50 | risk-cell mean ΔU >= -2.5 bp | -2.8131555372820797e-05 | -0.00025 | pass |  |
| example | Stable gain alternative | x100 | risk-cell mean ΔU >= -2.5 bp | -1.9042410070092715e-05 | -0.00025 | pass |  |
| example | Stable gain alternative | menu | test banks meeting every floor >= 4 of 5 | 5.0 | 4 | pass |  |
| example | Stable gain alternative | menu | median pairwise L1 reduction >= 20% (R+D vs R) | 0.04255494667782066 | 0.2 | FAIL |  |
| example | Stable gain alternative | menu | median pairwise L1 reduction >= .02 | 0.0075050813162789165 | 0.02 | FAIL |  |
| example | Stable gain alternative | menu | 90th-percentile pairwise L1 not worse (R+D - R <= 0) | -0.013044213244757241 | 0.0 | pass |  |
| example | Meaningful score change | menu | mean raw DR² gain >= .10 | 0.029165116589195534 | 0.1 | FAIL |  |
| example | Meaningful score change | menu | share of cells with L1(R+D, R) >= .02 >= 20% | 0.31313131313131315 | 0.2 | pass |  |
| example | General stability | x25 | share of origins with seed SD of Bad <= .10 x primary volatility >= 95% | 0.7272727272727273 | 0.95 | FAIL |  |
| example | General stability | x25 | median pairwise weight L1 <= .20 | 0.16825672408240683 | 0.2 | pass |  |
| example | General stability | x25 | 90th-percentile pairwise weight L1 <= .40 | 0.7265468927379884 | 0.4 | FAIL |  |
| example | General stability | x25 | median adjacent-origin turnover <= R's + .05 | 0.075048364462039 | 0.12668936401107392 | pass |  |
| example | General stability | x50 | share of origins with seed SD of Bad <= .10 x primary volatility >= 95% | 0.696969696969697 | 0.95 | FAIL |  |
| example | General stability | x50 | median pairwise weight L1 <= .20 | 0.1700577174945548 | 0.2 | pass |  |
| example | General stability | x50 | 90th-percentile pairwise weight L1 <= .40 | 0.7744030310370523 | 0.4 | FAIL |  |
| example | General stability | x50 | median adjacent-origin turnover <= R's + .05 | 0.08460316300201186 | 0.13893116019530202 | pass |  |
| example | General stability | x100 | share of origins with seed SD of Bad <= .10 x primary volatility >= 95% | 0.696969696969697 | 0.95 | FAIL |  |
| example | General stability | x100 | median pairwise weight L1 <= .20 | 0.16825672408240683 | 0.2 | pass |  |
| example | General stability | x100 | 90th-percentile pairwise weight L1 <= .40 | 0.7350512458626935 | 0.4 | FAIL |  |
| example | General stability | x100 | median adjacent-origin turnover <= R's + .05 | 0.08465869058690756 | 0.13838018943493363 | pass |  |
| example | Cost | menu | p95 warm R arm-search wall <= 30 s per cell | 65.4169347540941 | 30.0 | FAIL |  |
| example | Cost | menu | p95 of paired wall(R+D)/wall(R) <= 1.25 | 1.381660133376246 | 1.25 | FAIL |  |
| example | Independent replay return floors | menu | pooled mean paired ΔU >= -2.5 bp | -2.7778969422340675e-05 | -0.00025 | pass |  |
| example | Realized guardrails | x25 | annual-return median loss <= 25 bp | 0.0012440413065808453 | 0.0025 | pass |  |
| example | Realized guardrails | x25 | mean annual-return loss <= 25 bp | 0.00037240098849748634 | 0.0025 | pass |  |
| example | Realized guardrails | x25 | loss-frequency increase <= 5 pp | 0.011494252873563232 | 0.05 | pass |  |
| example | Realized guardrails | x25 | mean maximum-drawdown worsening <= 1 pp | -0.00020235580029417336 | 0.01 | pass |  |
| example | Realized guardrails | x50 | annual-return median loss <= 25 bp | -4.2927309989337914e-05 | 0.0025 | pass |  |
| example | Realized guardrails | x50 | mean annual-return loss <= 25 bp | 0.000337307058959412 | 0.0025 | pass |  |
| example | Realized guardrails | x50 | loss-frequency increase <= 5 pp | 0.011494252873563232 | 0.05 | pass |  |
| example | Realized guardrails | x50 | mean maximum-drawdown worsening <= 1 pp | -0.00026980370797230545 | 0.01 | pass |  |
| example | Realized guardrails | x100 | annual-return median loss <= 25 bp | -4.2927309989337914e-05 | 0.0025 | pass |  |
| example | Realized guardrails | x100 | mean annual-return loss <= 25 bp | 0.00034075211682909977 | 0.0025 | pass |  |
| example | Realized guardrails | x100 | loss-frequency increase <= 5 pp | 0.011494252873563232 | 0.05 | pass |  |
| example | Realized guardrails | x100 | mean maximum-drawdown worsening <= 1 pp | -0.00022556907132168628 | 0.01 | pass |  |
| example | Realized benefit support | menu | mean paired realized annual-return gain >= 25 bp | -0.00035015338809533275 | 0.0025 | FAIL |  |
| example | Realized benefit support | menu | its 99% interval lower bound > 0 | -0.0007543324223550058 | 0.0 | FAIL |  |
| example | Realized benefit support | menu | mean maximum-drawdown improvement >= 1 pp | 0.000232576193196055 | 0.01 | FAIL |  |
| example | Realized benefit support | menu | its 99% improvement lower bound > 0 | -4.745444316192855e-05 | 0.0 | FAIL |  |
| example | Realized benefit support | menu | mean annual-return loss <= 25 bp (drawdown route) | 0.00035015338809533275 | 0.0025 | pass |  |
| example | Realized benefit support | menu | disjoint annual intervals >= 20 | 7.0 | 20 | FAIL |  |
| example | Realized benefit support | menu | every realized guardrail holds (risk cells breaching) | 0.0 | 0.0 | pass |  |
| tsp | Independent replay return gain | menu | pooled mean paired ΔU >= 5 bp | -2.0933133843882034e-05 | 0.0005 | FAIL |  |
| tsp | Independent replay return gain | menu | mean paired ΔB >= -5 bp | 0.00026394427439787135 | -0.0005 | pass |  |
| tsp | Independent replay return gain | menu | mean paired ΔT >= -10 bp | -0.00032148536480932255 | -0.001 | pass |  |
| tsp | Independent replay return gain | menu | mean paired ΔG >= -20 bp | -0.0008285408903980779 | -0.002 | pass |  |
| tsp | Independent replay return gain | x25 | risk-cell mean ΔU >= -2.5 bp | -2.1947506298642387e-05 | -0.00025 | pass |  |
| tsp | Independent replay return gain | x50 | risk-cell mean ΔU >= -2.5 bp | -2.0858559198624908e-05 | -0.00025 | pass |  |
| tsp | Independent replay return gain | x100 | risk-cell mean ΔU >= -2.5 bp | -1.9993336034378806e-05 | -0.00025 | pass |  |
| tsp | Independent replay return gain | menu | test banks with positive mean ΔU >= 4 of 5 | 2.0 | 4 | FAIL |  |
| tsp | Stable gain alternative | menu | pooled mean paired ΔU >= -2.5 bp | -2.0933133843882034e-05 | -0.00025 | pass |  |
| tsp | Stable gain alternative | menu | mean paired ΔB >= -5 bp | 0.00026394427439787135 | -0.0005 | pass |  |
| tsp | Stable gain alternative | menu | mean paired ΔT >= -10 bp | -0.00032148536480932255 | -0.001 | pass |  |
| tsp | Stable gain alternative | menu | mean paired ΔG >= -20 bp | -0.0008285408903980779 | -0.002 | pass |  |
| tsp | Stable gain alternative | x25 | risk-cell mean ΔU >= -2.5 bp | -2.1947506298642387e-05 | -0.00025 | pass |  |
| tsp | Stable gain alternative | x50 | risk-cell mean ΔU >= -2.5 bp | -2.0858559198624908e-05 | -0.00025 | pass |  |
| tsp | Stable gain alternative | x100 | risk-cell mean ΔU >= -2.5 bp | -1.9993336034378806e-05 | -0.00025 | pass |  |
| tsp | Stable gain alternative | menu | test banks meeting every floor >= 4 of 5 | 5.0 | 4 | pass |  |
| tsp | Stable gain alternative | menu | median pairwise L1 reduction >= 20% (R+D vs R) | -0.00302158578334896 | 0.2 | FAIL |  |
| tsp | Stable gain alternative | menu | median pairwise L1 reduction >= .02 | -0.0002079605762705522 | 0.02 | FAIL |  |
| tsp | Stable gain alternative | menu | 90th-percentile pairwise L1 not worse (R+D - R <= 0) | -0.0003895106001515214 | 0.0 | pass |  |
| tsp | Meaningful score change | menu | mean raw DR² gain >= .10 | 0.03855764041201351 | 0.1 | FAIL |  |
| tsp | Meaningful score change | menu | share of cells with L1(R+D, R) >= .02 >= 20% | 0.17508417508417512 | 0.2 | FAIL |  |
| tsp | General stability | x25 | share of origins with seed SD of Bad <= .10 x primary volatility >= 95% | 0.4444444444444444 | 0.95 | FAIL |  |
| tsp | General stability | x25 | median pairwise weight L1 <= .20 | 0.06778881329493991 | 0.2 | pass |  |
| tsp | General stability | x25 | 90th-percentile pairwise weight L1 <= .40 | 0.2722674198481332 | 0.4 | pass |  |
| tsp | General stability | x25 | median adjacent-origin turnover <= R's + .05 | 0.039052818049921445 | 0.09161618492742937 | pass |  |
| tsp | General stability | x50 | share of origins with seed SD of Bad <= .10 x primary volatility >= 95% | 0.43434343434343436 | 0.95 | FAIL |  |
| tsp | General stability | x50 | median pairwise weight L1 <= .20 | 0.06965500181585016 | 0.2 | pass |  |
| tsp | General stability | x50 | 90th-percentile pairwise weight L1 <= .40 | 0.33568690760866704 | 0.4 | pass |  |
| tsp | General stability | x50 | median adjacent-origin turnover <= R's + .05 | 0.03928073361746121 | 0.09241838508225683 | pass |  |
| tsp | General stability | x100 | share of origins with seed SD of Bad <= .10 x primary volatility >= 95% | 0.43434343434343436 | 0.95 | FAIL |  |
| tsp | General stability | x100 | median pairwise weight L1 <= .20 | 0.06965500181585016 | 0.2 | pass |  |
| tsp | General stability | x100 | 90th-percentile pairwise weight L1 <= .40 | 0.33568690760866704 | 0.4 | pass |  |
| tsp | General stability | x100 | median adjacent-origin turnover <= R's + .05 | 0.03928073361746121 | 0.09241838508225683 | pass |  |
| tsp | Cost | menu | p95 warm R arm-search wall <= 10 s per cell | 3.572927191201597 | 10.0 | pass |  |
| tsp | Cost | menu | p95 of paired wall(R+D)/wall(R) <= 1.25 | 2.058135110333795 | 1.25 | FAIL |  |
| tsp | Independent replay return floors | menu | pooled mean paired ΔU >= -2.5 bp | -2.0933133843882034e-05 | -0.00025 | pass |  |
| tsp | Realized guardrails | x25 | annual-return median loss <= 25 bp | 0.0001265638749619047 | 0.0025 | pass |  |
| tsp | Realized guardrails | x25 | mean annual-return loss <= 25 bp | 3.071940945878386e-05 | 0.0025 | pass |  |
| tsp | Realized guardrails | x25 | loss-frequency increase <= 5 pp | 0.0 | 0.05 | pass |  |
| tsp | Realized guardrails | x25 | mean maximum-drawdown worsening <= 1 pp | -0.0005678214076998358 | 0.01 | pass |  |
| tsp | Realized guardrails | x50 | annual-return median loss <= 25 bp | -1.8502106381212968e-05 | 0.0025 | pass |  |
| tsp | Realized guardrails | x50 | mean annual-return loss <= 25 bp | 6.032116372968737e-05 | 0.0025 | pass |  |
| tsp | Realized guardrails | x50 | loss-frequency increase <= 5 pp | 0.0 | 0.05 | pass |  |
| tsp | Realized guardrails | x50 | mean maximum-drawdown worsening <= 1 pp | -0.000561503630989836 | 0.01 | pass |  |
| tsp | Realized guardrails | x100 | annual-return median loss <= 25 bp | -1.8502106381212968e-05 | 0.0025 | pass |  |
| tsp | Realized guardrails | x100 | mean annual-return loss <= 25 bp | 5.5880594076596836e-05 | 0.0025 | pass |  |
| tsp | Realized guardrails | x100 | loss-frequency increase <= 5 pp | 0.0 | 0.05 | pass |  |
| tsp | Realized guardrails | x100 | mean maximum-drawdown worsening <= 1 pp | -0.000567457655642311 | 0.01 | pass |  |
| tsp | Realized benefit support | menu | mean paired realized annual-return gain >= 25 bp | -4.897372242168935e-05 | 0.0025 | FAIL |  |
| tsp | Realized benefit support | menu | its 99% interval lower bound > 0 | -0.0003735905185334425 | 0.0 | FAIL |  |
| tsp | Realized benefit support | menu | mean maximum-drawdown improvement >= 1 pp | 0.0005655942314439943 | 0.01 | FAIL |  |
| tsp | Realized benefit support | menu | its 99% improvement lower bound > 0 | 6.923143006991653e-05 | 0.0 | pass |  |
| tsp | Realized benefit support | menu | mean annual-return loss <= 25 bp (drawdown route) | 4.897372242168935e-05 | 0.0025 | pass |  |
| tsp | Realized benefit support | menu | disjoint annual intervals >= 20 | 7.0 | 20 | FAIL |  |
| tsp | Realized benefit support | menu | every realized guardrail holds (risk cells breaching) | 0.0 | 0.0 | pass |  |

## Protocol readings

1. Stage 2 runs iff the experiment is valid, both menus reach positive conditional-model evidence and no sensitivity disclosure blocks progression (controller ruling 1). A menu that qualifies only through the stability branch therefore cannot authorize Stage 2 under the protocol as written: its cross-seed stability sensitivity is unavailable.
2. The 0 bp allowance is a diagnostic control, inert by construction (R+D = w_R or a 1e-12 U tie): it never blocks Stage 2, including when it is unavailable or tied (protocol amendment R26, superseding R24-2). 5 and 10 bp and the coefficient, lookback and budget settings block on a sign reversal of the pooled six-origin ΔU, a failed return floor, fewer than 4/5 banks with positive ΔU or an unavailable setting; a positive gain under 5 bp is reported but does not block alone.
3. A setting's sign reversal is judged against Stage 1 on the same six indexed origins (R+D at 2.5 bp minus R, primary seed, pooled test ΔU), not the full-panel ΔU (protocol amendment R27); without that baseline a reversal cannot be ruled out and the setting blocks.
4. The stability branch is evaluated only when the primary pooled mean paired ΔU is under 5 bp (ruling 3); its bank rule counts banks meeting every floor, not banks with a gain.
5. training_ineligible is not a failure (recorded, excluded from numerator and denominator); failed arms and named computational errors are failures, and a valid completed verdict requires zero unresolved failures in Stage 1 and in each sensitivity profile (ruling R25, superseding R24-4): the failed cells stay in the denominator and are listed with their reasons, statistics over the remaining cells are descriptive and labeled as such, and no protocol 7 label or Stage 2 run derives from them; the failure rate and its 1% line are recorded as information. An unattempted, interrupted, resource-breach or missing cell makes the run incomplete. A sensitivity profile with any such cell is unavailable and blocks.
6. General stability is assessed on R+D at the 2.5 bp cap per risk cell: the across-seed SD uses ddof 1; 'primary portfolio chart volatility' is the model risk sqrt(w'Σw) of the primary-seed R+D selection at that origin and ceiling; median and 90th-percentile pairwise L1 pool all seed pairs over every origin; turnover pools every optimizer seed. The stable-gain L1 comparison is made at menu level, as the mean over the three risk cells of each arm's per-cell median and 90th percentile (ruling 5).
7. The realized mask is the intersection across both menus and arms: an origin enters the realized statistics only when its horizon is complete in both menus (ruling 6).
8. The realized 'annual-return median loss' is median(R) - median(R+D) across origins within a risk cell (ruling 7).
9. The 12- and 36-origin bootstrap sensitivities reuse seed 20261201; the origin index is every ledger month from the first to the last scheduled origin, unscheduled months masked.
10. Independent-replay return floors for material harm: pooled ΔU >= -2.5 bp, ΔB >= -5 bp, ΔT >= -10 bp, ΔG >= -20 bp and every risk-cell ΔU >= -2.5 bp (primary seed, pooled test).
11. Realized-support disjoint intervals are counted greedily on the realized panel (the intersection mask) per menu; the protocol 4 coverage gate counts them on each menu's own complete outcomes.

## Appendix A: white-line candidates per origin and ceiling (primary seed)

Test = pooled independent banks; train = optimization bank; weights in summary.json.

| menu | month | ceiling | candidate | risk | train B | train T | train G | train U | train ES | test B | test T | test G | test U | test ES | DR² |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| example | 2018-06 | x25 | w_R | 4.8% | -2.4% | 6.5% | 15.9% | 2.1% | -4.0% | -3.0% | 6.4% | 15.4% | 1.6% | -4.6% | 2.364 |
| example | 2018-06 | x25 | frontier | 4.9% | -2.5% | 6.5% | 16.0% | 2.1% | -4.0% | -3.0% | 6.4% | 15.5% | 1.7% | -4.6% | 2.328 |
| example | 2018-06 | x50 | w_R | 8.0% | -5.0% | 9.6% | 25.2% | 2.4% | -7.2% | -5.7% | 9.4% | 24.0% | 1.8% | -8.1% | 2.450 |
| example | 2018-06 | x50 | frontier | 8.0% | -5.0% | 9.6% | 25.3% | 2.4% | -7.2% | -5.8% | 9.4% | 24.1% | 1.8% | -8.2% | 2.454 |
| example | 2018-06 | x100 | w_R | 8.0% | -5.0% | 9.7% | 25.4% | 2.5% | -7.3% | -5.8% | 9.4% | 24.2% | 1.8% | -8.2% | 2.404 |
| example | 2018-06 | x100 | frontier | 14.1% | -12.5% | 11.3% | 38.7% | -0.2% | -16.9% | -13.0% | 11.6% | 37.5% | -0.5% | -17.3% | 1.221 |
| example | 2018-07 | x25 | w_R | 4.7% | -2.2% | 5.9% | 14.0% | 1.8% | -4.3% | -2.3% | 5.9% | 13.5% | 1.7% | -4.0% | 2.981 |
| example | 2018-07 | x25 | frontier | 4.9% | -3.3% | 6.3% | 15.8% | 1.5% | -5.0% | -2.9% | 6.3% | 15.4% | 1.7% | -4.7% | 2.407 |
| example | 2018-07 | x50 | w_R | 6.4% | -3.5% | 7.5% | 18.7% | 2.0% | -6.3% | -3.8% | 7.5% | 18.0% | 1.7% | -6.1% | 2.744 |
| example | 2018-07 | x50 | frontier | 7.9% | -5.8% | 9.2% | 24.7% | 1.7% | -8.5% | -5.4% | 9.2% | 23.7% | 1.9% | -8.1% | 2.661 |
| example | 2018-07 | x100 | w_R | 6.3% | -3.5% | 7.5% | 18.6% | 2.0% | -6.2% | -3.8% | 7.4% | 18.0% | 1.7% | -6.0% | 2.740 |
| example | 2018-07 | x100 | frontier | 14.1% | -11.9% | 11.3% | 37.2% | -0.0% | -16.2% | -13.3% | 11.2% | 37.2% | -0.9% | -17.7% | 1.220 |
| example | 2018-08 | x25 | w_R | 4.8% | -2.4% | 7.1% | 15.8% | 2.2% | -4.0% | -2.4% | 6.8% | 15.8% | 2.2% | -4.0% | 2.388 |
| example | 2018-08 | x25 | frontier | 4.8% | -2.4% | 7.1% | 15.8% | 2.2% | -4.0% | -2.4% | 6.8% | 15.8% | 2.2% | -4.0% | 2.383 |
| example | 2018-08 | x50 | w_R | 7.7% | -4.8% | 10.1% | 24.1% | 2.6% | -7.1% | -4.6% | 9.9% | 24.2% | 2.6% | -7.2% | 2.572 |
| example | 2018-08 | x50 | frontier | 7.9% | -5.0% | 10.2% | 24.4% | 2.5% | -7.3% | -4.6% | 10.0% | 24.5% | 2.7% | -7.4% | 2.536 |
| example | 2018-08 | x100 | w_R | 7.8% | -4.8% | 10.2% | 24.2% | 2.6% | -7.2% | -4.6% | 10.0% | 24.4% | 2.7% | -7.3% | 2.609 |
| example | 2018-08 | x100 | frontier | 14.0% | -13.8% | 12.1% | 38.7% | -0.8% | -18.9% | -12.4% | 12.5% | 38.3% | 0.1% | -17.0% | 1.221 |
| example | 2018-09 | x25 | w_R | 4.7% | -2.1% | 6.2% | 15.0% | 2.1% | -4.2% | -2.8% | 6.1% | 14.7% | 1.7% | -4.5% | 2.441 |
| example | 2018-09 | x25 | frontier | 4.7% | -2.2% | 6.2% | 15.0% | 2.1% | -4.2% | -2.7% | 6.1% | 14.7% | 1.7% | -4.5% | 2.448 |
| example | 2018-09 | x50 | w_R | 7.6% | -4.4% | 9.1% | 22.9% | 2.4% | -7.6% | -5.1% | 8.8% | 22.7% | 1.8% | -7.7% | 2.561 |
| example | 2018-09 | x50 | frontier | 7.7% | -4.4% | 9.1% | 23.2% | 2.4% | -7.6% | -5.0% | 8.9% | 22.7% | 1.9% | -7.7% | 2.491 |
| example | 2018-09 | x100 | w_R | 7.6% | -4.3% | 9.1% | 23.0% | 2.4% | -7.6% | -5.1% | 8.8% | 22.7% | 1.9% | -7.7% | 2.624 |
| example | 2018-09 | x100 | frontier | 13.6% | -11.7% | 10.3% | 34.2% | -0.5% | -15.4% | -12.3% | 11.0% | 34.8% | -0.6% | -16.4% | 1.210 |
| example | 2018-10 | x25 | w_R | 2.2% | -0.9% | 3.0% | 7.0% | 1.1% | -1.7% | -1.1% | 3.0% | 6.8% | 0.9% | -2.0% | 3.296 |
| example | 2018-10 | x25 | frontier | 4.7% | -4.0% | 5.2% | 14.9% | 0.6% | -5.6% | -4.3% | 5.1% | 14.3% | 0.4% | -6.3% | 2.558 |
| example | 2018-10 | x50 | w_R | 2.2% | -0.9% | 3.0% | 7.0% | 1.1% | -1.7% | -1.1% | 3.0% | 6.8% | 0.9% | -2.0% | 3.296 |
| example | 2018-10 | x50 | frontier | 7.8% | -7.4% | 7.3% | 22.6% | 0.0% | -9.9% | -7.8% | 7.2% | 22.0% | -0.3% | -10.8% | 2.545 |
| example | 2018-10 | x100 | w_R | 2.2% | -0.9% | 3.0% | 7.0% | 1.1% | -1.7% | -1.1% | 3.0% | 6.8% | 0.9% | -2.0% | 3.296 |
| example | 2018-10 | x100 | frontier | 13.8% | -14.7% | 8.4% | 33.4% | -3.0% | -19.0% | -15.5% | 8.1% | 32.9% | -3.6% | -19.7% | 1.203 |
| example | 2018-11 | x25 | w_R | 2.2% | -0.8% | 3.0% | 7.0% | 1.2% | -1.6% | -0.9% | 3.2% | 7.1% | 1.1% | -1.7% | 3.027 |
| example | 2018-11 | x25 | frontier | 4.8% | -3.6% | 5.3% | 14.4% | 0.9% | -5.2% | -4.0% | 5.5% | 14.5% | 0.7% | -5.7% | 2.815 |
| example | 2018-11 | x50 | w_R | 2.2% | -0.8% | 3.0% | 7.0% | 1.2% | -1.6% | -0.9% | 3.2% | 7.1% | 1.1% | -1.7% | 3.027 |
| example | 2018-11 | x50 | frontier | 7.8% | -6.3% | 7.4% | 22.2% | 0.7% | -8.8% | -7.3% | 7.8% | 22.8% | 0.2% | -10.1% | 2.627 |
| example | 2018-11 | x100 | w_R | 2.2% | -0.8% | 3.0% | 7.0% | 1.2% | -1.6% | -0.9% | 3.2% | 7.1% | 1.1% | -1.7% | 3.027 |
| example | 2018-11 | x100 | frontier | 13.9% | -14.2% | 8.4% | 32.5% | -2.8% | -17.9% | -14.5% | 8.8% | 32.8% | -2.8% | -18.5% | 1.203 |
| example | 2018-12 | x25 | w_R | 1.8% | -0.4% | 2.8% | 6.0% | 1.2% | -1.2% | -0.6% | 2.7% | 5.8% | 1.0% | -1.3% | 3.325 |
| example | 2018-12 | x25 | frontier | 3.5% | -2.6% | 4.2% | 11.0% | 0.8% | -4.1% | -3.0% | 4.1% | 11.0% | 0.5% | -4.3% | 3.021 |
| example | 2018-12 | x50 | w_R | 1.8% | -0.4% | 2.8% | 6.0% | 1.2% | -1.2% | -0.6% | 2.7% | 5.8% | 1.0% | -1.3% | 3.325 |
| example | 2018-12 | x50 | frontier | 5.4% | -4.7% | 5.4% | 15.7% | 0.3% | -6.9% | -5.4% | 5.3% | 15.9% | -0.0% | -7.4% | 3.152 |
| example | 2018-12 | x100 | w_R | 1.8% | -0.4% | 2.8% | 6.0% | 1.2% | -1.2% | -0.6% | 2.7% | 5.8% | 1.0% | -1.3% | 3.325 |
| example | 2018-12 | x100 | frontier | 9.1% | -9.6% | 6.9% | 25.0% | -1.2% | -12.3% | -10.5% | 6.7% | 25.2% | -1.8% | -13.5% | 2.525 |
| example | 2019-01 | x25 | w_R | 2.1% | -0.6% | 3.3% | 7.5% | 1.4% | -1.5% | -0.8% | 3.3% | 7.6% | 1.3% | -1.6% | 3.191 |
| example | 2019-01 | x25 | frontier | 4.9% | -4.0% | 5.7% | 15.8% | 0.9% | -5.7% | -4.2% | 5.7% | 16.0% | 0.8% | -5.9% | 2.748 |
| example | 2019-01 | x50 | w_R | 2.1% | -0.6% | 3.3% | 7.5% | 1.4% | -1.5% | -0.8% | 3.3% | 7.6% | 1.3% | -1.6% | 3.191 |
| example | 2019-01 | x50 | frontier | 8.0% | -7.8% | 7.6% | 23.7% | -0.0% | -10.6% | -7.8% | 7.8% | 24.5% | 0.2% | -10.5% | 2.734 |
| example | 2019-01 | x100 | w_R | 2.1% | -0.6% | 3.3% | 7.5% | 1.4% | -1.5% | -0.8% | 3.3% | 7.6% | 1.3% | -1.6% | 3.191 |
| example | 2019-01 | x100 | frontier | 14.3% | -16.5% | 8.6% | 36.4% | -3.7% | -20.9% | -15.9% | 9.0% | 35.3% | -3.3% | -19.8% | 1.194 |
| example | 2019-02 | x25 | w_R | 2.0% | -0.6% | 3.1% | 6.9% | 1.3% | -1.4% | -0.8% | 3.1% | 7.0% | 1.2% | -1.6% | 3.275 |
| example | 2019-02 | x25 | frontier | 4.8% | -4.5% | 5.5% | 15.6% | 0.5% | -5.9% | -4.3% | 5.5% | 15.3% | 0.6% | -6.4% | 2.694 |
| example | 2019-02 | x50 | w_R | 2.0% | -0.6% | 3.1% | 6.9% | 1.3% | -1.4% | -0.8% | 3.1% | 7.0% | 1.2% | -1.6% | 3.275 |
| example | 2019-02 | x50 | frontier | 8.0% | -8.2% | 7.5% | 23.2% | -0.3% | -10.5% | -8.0% | 7.5% | 23.3% | -0.2% | -11.1% | 2.704 |
| example | 2019-02 | x100 | w_R | 2.0% | -0.6% | 3.1% | 6.9% | 1.3% | -1.4% | -0.8% | 3.1% | 7.0% | 1.2% | -1.6% | 3.275 |
| example | 2019-02 | x100 | frontier | 14.3% | -15.4% | 9.0% | 35.4% | -3.0% | -19.6% | -16.0% | 8.7% | 35.0% | -3.5% | -20.8% | 1.194 |
| example | 2019-03 | x25 | w_R | 2.3% | -0.8% | 3.6% | 7.5% | 1.3% | -2.0% | -0.9% | 3.4% | 7.6% | 1.3% | -1.7% | 3.214 |
| example | 2019-03 | x25 | frontier | 4.8% | -4.6% | 5.9% | 15.9% | 0.6% | -6.6% | -4.2% | 5.7% | 15.8% | 0.8% | -6.1% | 2.620 |
| example | 2019-03 | x50 | w_R | 2.3% | -0.8% | 3.6% | 7.5% | 1.3% | -2.0% | -0.9% | 3.4% | 7.6% | 1.3% | -1.7% | 3.214 |
| example | 2019-03 | x50 | frontier | 8.0% | -7.9% | 8.0% | 24.2% | 0.1% | -11.3% | -7.6% | 7.8% | 23.8% | 0.1% | -10.8% | 2.683 |
| example | 2019-03 | x100 | w_R | 2.3% | -0.8% | 3.6% | 7.5% | 1.3% | -2.0% | -0.9% | 3.4% | 7.6% | 1.3% | -1.7% | 3.214 |
| example | 2019-03 | x100 | frontier | 14.3% | -17.0% | 9.4% | 36.3% | -3.7% | -21.3% | -15.6% | 9.0% | 35.4% | -3.1% | -20.0% | 1.190 |
| example | 2019-04 | x25 | w_R | 2.0% | -0.9% | 3.4% | 7.8% | 1.3% | -1.7% | -0.9% | 3.2% | 7.6% | 1.2% | -1.6% | 3.168 |
| example | 2019-04 | x25 | frontier | 4.8% | -4.3% | 5.9% | 16.1% | 0.8% | -6.4% | -4.1% | 5.6% | 16.1% | 0.8% | -6.0% | 2.449 |
| example | 2019-04 | x50 | w_R | 2.0% | -0.9% | 3.4% | 7.8% | 1.3% | -1.7% | -0.9% | 3.2% | 7.6% | 1.2% | -1.6% | 3.168 |
| example | 2019-04 | x50 | frontier | 7.9% | -7.6% | 8.2% | 24.2% | 0.3% | -11.0% | -7.6% | 7.7% | 23.7% | 0.1% | -10.1% | 2.535 |
| example | 2019-04 | x100 | w_R | 2.0% | -0.9% | 3.4% | 7.8% | 1.3% | -1.7% | -0.9% | 3.2% | 7.6% | 1.2% | -1.6% | 3.168 |
| example | 2019-04 | x100 | frontier | 14.2% | -15.4% | 9.8% | 36.0% | -2.7% | -20.1% | -15.5% | 9.3% | 36.3% | -2.9% | -19.4% | 1.189 |
| example | 2019-05 | x25 | w_R | 2.1% | -0.9% | 2.9% | 7.1% | 1.1% | -1.7% | -0.9% | 3.0% | 7.1% | 1.1% | -1.6% | 3.185 |
| example | 2019-05 | x25 | frontier | 4.9% | -5.0% | 4.8% | 15.2% | -0.0% | -6.7% | -4.8% | 5.0% | 15.1% | 0.1% | -6.5% | 2.650 |
| example | 2019-05 | x50 | w_R | 2.1% | -0.9% | 2.9% | 7.1% | 1.1% | -1.7% | -0.9% | 3.0% | 7.1% | 1.1% | -1.6% | 3.185 |
| example | 2019-05 | x50 | frontier | 8.0% | -8.4% | 6.5% | 22.8% | -0.8% | -11.3% | -8.4% | 6.8% | 22.8% | -0.7% | -11.0% | 2.527 |
| example | 2019-05 | x100 | w_R | 2.1% | -0.9% | 2.9% | 7.1% | 1.1% | -1.7% | -0.9% | 3.0% | 7.1% | 1.1% | -1.6% | 3.185 |
| example | 2019-05 | x100 | frontier | 14.3% | -17.5% | 7.7% | 35.0% | -4.7% | -22.5% | -17.0% | 7.3% | 33.8% | -4.6% | -21.4% | 1.186 |
| example | 2019-06 | x25 | w_R | 2.2% | -0.8% | 3.3% | 7.9% | 1.3% | -1.8% | -0.9% | 3.4% | 7.7% | 1.2% | -1.7% | 3.127 |
| example | 2019-06 | x25 | frontier | 4.9% | -4.1% | 5.3% | 15.6% | 0.7% | -6.2% | -4.4% | 5.5% | 15.6% | 0.6% | -6.0% | 2.609 |
| example | 2019-06 | x50 | w_R | 2.2% | -0.8% | 3.3% | 7.9% | 1.3% | -1.8% | -0.9% | 3.4% | 7.7% | 1.2% | -1.7% | 3.127 |
| example | 2019-06 | x50 | frontier | 8.0% | -7.1% | 7.3% | 22.5% | 0.2% | -10.1% | -7.8% | 7.5% | 23.2% | -0.1% | -10.5% | 2.493 |
| example | 2019-06 | x100 | w_R | 2.2% | -0.8% | 3.3% | 7.9% | 1.3% | -1.8% | -0.9% | 3.4% | 7.7% | 1.2% | -1.7% | 3.127 |
| example | 2019-06 | x100 | frontier | 14.3% | -16.0% | 7.6% | 32.6% | -4.1% | -20.3% | -16.4% | 8.1% | 34.2% | -4.0% | -20.9% | 1.185 |
| example | 2019-07 | x25 | w_R | 1.8% | -0.8% | 2.9% | 6.5% | 1.0% | -1.6% | -0.7% | 2.9% | 6.5% | 1.1% | -1.3% | 3.239 |
| example | 2019-07 | x25 | frontier | 4.9% | -5.1% | 5.5% | 15.2% | 0.1% | -7.1% | -4.4% | 5.4% | 15.7% | 0.6% | -6.2% | 2.495 |
| example | 2019-07 | x50 | w_R | 1.8% | -0.8% | 2.9% | 6.5% | 1.0% | -1.6% | -0.7% | 2.9% | 6.5% | 1.1% | -1.3% | 3.239 |
| example | 2019-07 | x50 | frontier | 8.0% | -8.3% | 7.2% | 22.7% | -0.6% | -11.6% | -7.8% | 7.4% | 23.0% | -0.2% | -10.7% | 2.479 |
| example | 2019-07 | x100 | w_R | 1.8% | -0.8% | 2.9% | 6.5% | 1.0% | -1.6% | -0.7% | 2.9% | 6.5% | 1.1% | -1.3% | 3.239 |
| example | 2019-07 | x100 | frontier | 14.3% | -15.9% | 8.2% | 35.6% | -3.5% | -21.1% | -16.3% | 8.1% | 35.1% | -3.9% | -20.4% | 1.187 |
| example | 2019-08 | x25 | w_R | 2.2% | -0.9% | 3.3% | 7.4% | 1.2% | -1.7% | -1.0% | 3.3% | 7.4% | 1.1% | -1.8% | 3.381 |
| example | 2019-08 | x25 | frontier | 4.5% | -4.4% | 5.2% | 14.7% | 0.4% | -6.1% | -4.2% | 5.2% | 14.8% | 0.5% | -6.0% | 2.642 |
| example | 2019-08 | x50 | w_R | 2.2% | -0.9% | 3.3% | 7.4% | 1.2% | -1.7% | -1.0% | 3.3% | 7.4% | 1.1% | -1.8% | 3.381 |
| example | 2019-08 | x50 | frontier | 7.2% | -7.5% | 7.1% | 21.8% | -0.2% | -10.0% | -7.4% | 7.1% | 21.6% | -0.2% | -9.8% | 2.715 |
| example | 2019-08 | x100 | w_R | 2.2% | -0.9% | 3.3% | 7.4% | 1.2% | -1.7% | -1.0% | 3.3% | 7.4% | 1.1% | -1.8% | 3.381 |
| example | 2019-08 | x100 | frontier | 12.7% | -14.5% | 7.9% | 32.4% | -3.1% | -18.5% | -13.7% | 7.7% | 32.3% | -2.7% | -17.4% | 1.244 |
| example | 2019-09 | x25 | w_R | 2.2% | -0.9% | 3.5% | 7.9% | 1.3% | -2.0% | -0.8% | 3.4% | 7.9% | 1.3% | -1.7% | 3.285 |
| example | 2019-09 | x25 | frontier | 4.5% | -4.3% | 5.6% | 14.8% | 0.6% | -6.0% | -3.7% | 5.5% | 15.2% | 0.9% | -5.2% | 2.580 |
| example | 2019-09 | x50 | w_R | 2.2% | -0.9% | 3.5% | 7.9% | 1.3% | -2.0% | -0.8% | 3.4% | 7.9% | 1.3% | -1.7% | 3.285 |
| example | 2019-09 | x50 | frontier | 7.2% | -7.6% | 7.7% | 22.0% | -0.1% | -10.0% | -6.6% | 7.5% | 22.7% | 0.6% | -8.9% | 2.845 |
| example | 2019-09 | x100 | w_R | 2.2% | -0.9% | 3.5% | 7.9% | 1.3% | -2.0% | -0.8% | 3.4% | 7.9% | 1.3% | -1.7% | 3.285 |
| example | 2019-09 | x100 | frontier | 12.7% | -14.0% | 9.0% | 33.6% | -2.4% | -17.8% | -12.9% | 8.9% | 33.7% | -1.7% | -16.7% | 1.246 |
| example | 2019-10 | x25 | w_R | 2.1% | -0.9% | 3.3% | 7.4% | 1.2% | -1.8% | -0.8% | 3.4% | 7.4% | 1.3% | -1.6% | 3.330 |
| example | 2019-10 | x25 | frontier | 4.9% | -4.4% | 5.6% | 15.9% | 0.6% | -6.3% | -4.2% | 5.9% | 16.0% | 0.8% | -6.2% | 2.481 |
| example | 2019-10 | x50 | w_R | 2.1% | -0.9% | 3.3% | 7.4% | 1.2% | -1.8% | -0.8% | 3.4% | 7.4% | 1.3% | -1.6% | 3.330 |
| example | 2019-10 | x50 | frontier | 8.1% | -8.0% | 7.8% | 23.8% | -0.1% | -10.5% | -7.5% | 8.2% | 23.7% | 0.3% | -10.5% | 2.536 |
| example | 2019-10 | x100 | w_R | 2.1% | -0.9% | 3.3% | 7.4% | 1.2% | -1.8% | -0.8% | 3.4% | 7.4% | 1.3% | -1.6% | 3.330 |
| example | 2019-10 | x100 | frontier | 14.4% | -16.5% | 9.2% | 34.2% | -3.7% | -21.5% | -15.4% | 9.3% | 36.3% | -2.8% | -20.1% | 1.169 |
| example | 2019-11 | x25 | w_R | 2.2% | -0.6% | 3.2% | 7.3% | 1.3% | -1.4% | -1.0% | 3.2% | 7.4% | 1.1% | -1.8% | 3.318 |
| example | 2019-11 | x25 | frontier | 4.9% | -4.0% | 5.6% | 16.2% | 0.9% | -5.6% | -4.5% | 5.6% | 16.2% | 0.6% | -6.4% | 2.335 |
| example | 2019-11 | x50 | w_R | 2.2% | -0.6% | 3.2% | 7.3% | 1.3% | -1.4% | -1.0% | 3.2% | 7.4% | 1.1% | -1.8% | 3.318 |
| example | 2019-11 | x50 | frontier | 8.1% | -6.6% | 7.7% | 22.8% | 0.6% | -9.2% | -8.0% | 7.8% | 23.3% | -0.1% | -10.7% | 2.525 |
| example | 2019-11 | x100 | w_R | 2.2% | -0.6% | 3.2% | 7.3% | 1.3% | -1.4% | -1.0% | 3.2% | 7.4% | 1.1% | -1.8% | 3.318 |
| example | 2019-11 | x100 | frontier | 14.3% | -14.5% | 8.8% | 33.6% | -2.7% | -18.9% | -15.4% | 8.9% | 35.2% | -3.1% | -19.9% | 1.162 |
| example | 2019-12 | x25 | w_R | 2.1% | -0.9% | 3.4% | 7.5% | 1.2% | -1.7% | -0.9% | 3.3% | 7.6% | 1.2% | -1.7% | 3.330 |
| example | 2019-12 | x25 | frontier | 4.9% | -4.3% | 6.0% | 16.1% | 0.8% | -6.3% | -4.4% | 5.9% | 16.5% | 0.8% | -6.2% | 1.995 |
| example | 2019-12 | x50 | w_R | 2.1% | -0.9% | 3.4% | 7.5% | 1.2% | -1.7% | -0.9% | 3.3% | 7.6% | 1.2% | -1.7% | 3.330 |
| example | 2019-12 | x50 | frontier | 8.0% | -7.4% | 7.9% | 22.2% | 0.2% | -10.1% | -7.3% | 7.9% | 22.7% | 0.2% | -10.0% | 2.131 |
| example | 2019-12 | x100 | w_R | 2.1% | -0.9% | 3.4% | 7.5% | 1.2% | -1.7% | -0.9% | 3.3% | 7.6% | 1.2% | -1.7% | 3.330 |
| example | 2019-12 | x100 | frontier | 14.2% | -15.7% | 9.2% | 36.9% | -2.9% | -20.2% | -15.8% | 9.5% | 35.4% | -3.1% | -20.3% | 1.163 |
| example | 2020-01 | x25 | w_R | 2.1% | -1.1% | 3.3% | 7.7% | 1.1% | -2.1% | -1.2% | 3.2% | 7.6% | 1.0% | -1.9% | 3.291 |
| example | 2020-01 | x25 | frontier | 4.6% | -4.4% | 5.8% | 16.5% | 0.8% | -6.6% | -4.2% | 5.7% | 16.0% | 0.8% | -5.9% | 1.909 |
| example | 2020-01 | x50 | w_R | 2.1% | -1.1% | 3.3% | 7.7% | 1.1% | -2.1% | -1.2% | 3.2% | 7.6% | 1.0% | -1.9% | 3.291 |
| example | 2020-01 | x50 | frontier | 7.5% | -7.3% | 7.7% | 22.8% | 0.2% | -10.7% | -6.7% | 7.6% | 22.2% | 0.5% | -9.4% | 2.149 |
| example | 2020-01 | x100 | w_R | 2.1% | -1.1% | 3.3% | 7.7% | 1.1% | -2.1% | -1.2% | 3.2% | 7.6% | 1.0% | -1.9% | 3.291 |
| example | 2020-01 | x100 | frontier | 13.3% | -15.0% | 8.9% | 35.4% | -2.8% | -20.7% | -14.8% | 9.3% | 34.8% | -2.6% | -19.1% | 1.050 |
| example | 2020-02 | x25 | w_R | 1.8% | -0.8% | 2.8% | 6.5% | 1.0% | -1.5% | -0.9% | 2.8% | 6.3% | 0.9% | -1.5% | 3.504 |
| example | 2020-02 | x25 | frontier | 4.7% | -5.1% | 5.2% | 15.8% | 0.1% | -6.9% | -5.1% | 5.0% | 15.8% | 0.0% | -6.8% | 2.252 |
| example | 2020-02 | x50 | w_R | 1.8% | -0.8% | 2.8% | 6.5% | 1.0% | -1.5% | -0.9% | 2.8% | 6.3% | 0.9% | -1.5% | 3.504 |
| example | 2020-02 | x50 | frontier | 7.6% | -8.0% | 6.7% | 22.2% | -0.6% | -11.2% | -8.7% | 6.6% | 22.0% | -1.0% | -11.6% | 2.575 |
| example | 2020-02 | x100 | w_R | 1.8% | -0.8% | 2.8% | 6.5% | 1.0% | -1.5% | -0.9% | 2.8% | 6.3% | 0.9% | -1.5% | 3.504 |
| example | 2020-02 | x100 | frontier | 13.5% | -18.1% | 7.3% | 34.4% | -5.3% | -23.6% | -19.4% | 7.3% | 34.4% | -6.0% | -24.1% | 1.050 |
| example | 2020-03 | x25 | w_R | 2.8% | -2.2% | 2.4% | 7.2% | 0.2% | -3.6% | -2.7% | 2.4% | 7.2% | -0.2% | -4.0% | 2.415 |
| example | 2020-03 | x25 | frontier | 4.7% | -5.4% | 3.6% | 11.8% | -1.0% | -7.4% | -5.7% | 3.6% | 12.2% | -1.1% | -7.8% | 2.775 |
| example | 2020-03 | x50 | w_R | 2.8% | -2.2% | 2.4% | 7.2% | 0.2% | -3.6% | -2.7% | 2.4% | 7.2% | -0.2% | -4.0% | 2.415 |
| example | 2020-03 | x50 | frontier | 6.7% | -8.7% | 4.5% | 16.5% | -2.2% | -11.2% | -8.8% | 4.5% | 16.8% | -2.3% | -11.8% | 2.925 |
| example | 2020-03 | x100 | w_R | 2.8% | -2.2% | 2.4% | 7.2% | 0.2% | -3.6% | -2.7% | 2.4% | 7.2% | -0.2% | -4.0% | 2.415 |
| example | 2020-03 | x100 | frontier | 10.7% | -16.9% | 5.5% | 23.9% | -6.1% | -20.4% | -17.3% | 5.8% | 23.6% | -6.3% | -22.1% | 2.307 |
| example | 2020-04 | x25 | w_R | 2.8% | -2.4% | 2.5% | 7.2% | 0.0% | -3.9% | -2.4% | 2.5% | 7.5% | 0.1% | -3.9% | 2.445 |
| example | 2020-04 | x25 | frontier | 5.3% | -5.8% | 4.5% | 14.8% | -0.6% | -7.8% | -5.6% | 4.5% | 14.7% | -0.5% | -7.8% | 2.893 |
| example | 2020-04 | x50 | w_R | 2.8% | -2.4% | 2.5% | 7.2% | 0.0% | -3.9% | -2.4% | 2.5% | 7.5% | 0.1% | -3.9% | 2.445 |
| example | 2020-04 | x50 | frontier | 8.0% | -9.7% | 6.0% | 21.8% | -1.8% | -12.3% | -8.9% | 5.9% | 21.5% | -1.4% | -12.5% | 2.848 |
| example | 2020-04 | x100 | w_R | 2.8% | -2.4% | 2.5% | 7.2% | 0.0% | -3.9% | -2.4% | 2.5% | 7.5% | 0.1% | -3.9% | 2.445 |
| example | 2020-04 | x100 | frontier | 13.2% | -20.5% | 7.0% | 30.7% | -7.1% | -25.0% | -19.0% | 7.2% | 31.3% | -6.1% | -25.1% | 2.127 |
| example | 2020-05 | x25 | w_R | 3.3% | -2.7% | 3.1% | 9.5% | 0.2% | -4.8% | -2.9% | 3.1% | 9.4% | 0.1% | -4.6% | 3.165 |
| example | 2020-05 | x25 | frontier | 6.8% | -7.5% | 5.5% | 18.6% | -1.0% | -10.4% | -7.2% | 5.7% | 18.8% | -0.7% | -10.0% | 2.965 |
| example | 2020-05 | x50 | w_R | 3.3% | -2.7% | 3.1% | 9.5% | 0.2% | -4.8% | -2.9% | 3.1% | 9.4% | 0.1% | -4.6% | 3.165 |
| example | 2020-05 | x50 | frontier | 10.8% | -13.3% | 7.2% | 27.3% | -3.1% | -18.2% | -13.4% | 7.5% | 27.4% | -3.1% | -17.9% | 2.404 |
| example | 2020-05 | x100 | w_R | 3.3% | -2.7% | 3.1% | 9.5% | 0.2% | -4.8% | -2.9% | 3.1% | 9.4% | 0.1% | -4.6% | 3.165 |
| example | 2020-05 | x100 | frontier | 18.8% | -29.9% | 8.1% | 40.8% | -11.5% | -36.5% | -30.2% | 8.6% | 41.5% | -11.4% | -37.0% | 1.157 |
| example | 2020-06 | x25 | w_R | 2.9% | -2.3% | 2.9% | 8.2% | 0.3% | -4.0% | -2.4% | 2.9% | 8.3% | 0.2% | -3.9% | 2.572 |
| example | 2020-06 | x25 | frontier | 6.9% | -6.9% | 6.4% | 20.2% | -0.2% | -9.3% | -6.8% | 6.3% | 19.6% | -0.3% | -9.6% | 2.964 |
| example | 2020-06 | x50 | w_R | 2.9% | -2.3% | 2.9% | 8.2% | 0.3% | -4.0% | -2.4% | 2.9% | 8.3% | 0.2% | -3.9% | 2.572 |
| example | 2020-06 | x50 | frontier | 11.0% | -12.8% | 8.5% | 30.6% | -2.1% | -17.4% | -13.2% | 8.3% | 28.8% | -2.5% | -17.8% | 2.372 |
| example | 2020-06 | x100 | w_R | 2.9% | -2.3% | 2.9% | 8.2% | 0.3% | -4.0% | -2.4% | 2.9% | 8.3% | 0.2% | -3.9% | 2.572 |
| example | 2020-06 | x100 | frontier | 19.3% | -29.5% | 9.9% | 48.2% | -9.9% | -36.3% | -30.2% | 9.5% | 45.1% | -10.8% | -37.3% | 1.150 |
| example | 2020-07 | x25 | w_R | 2.7% | -1.6% | 2.8% | 7.4% | 0.6% | -3.6% | -2.2% | 2.7% | 8.0% | 0.3% | -3.4% | 2.149 |
| example | 2020-07 | x25 | frontier | 6.9% | -6.4% | 6.6% | 19.7% | 0.1% | -9.3% | -7.2% | 6.6% | 21.0% | -0.2% | -9.9% | 2.946 |
| example | 2020-07 | x50 | w_R | 2.7% | -1.6% | 2.8% | 7.4% | 0.6% | -3.6% | -2.2% | 2.7% | 8.0% | 0.3% | -3.4% | 2.149 |
| example | 2020-07 | x50 | frontier | 11.0% | -12.3% | 9.0% | 29.1% | -1.7% | -16.6% | -13.6% | 9.0% | 31.4% | -2.3% | -18.0% | 2.435 |
| example | 2020-07 | x100 | w_R | 2.7% | -1.6% | 2.8% | 7.4% | 0.6% | -3.6% | -2.2% | 2.7% | 8.0% | 0.3% | -3.4% | 2.149 |
| example | 2020-07 | x100 | frontier | 19.3% | -27.6% | 11.1% | 45.7% | -8.6% | -33.1% | -28.1% | 10.1% | 46.7% | -9.1% | -34.5% | 1.145 |
| example | 2020-08 | x25 | w_R | 3.3% | -3.3% | 3.7% | 9.9% | 0.1% | -5.4% | -2.5% | 3.7% | 10.0% | 0.6% | -4.1% | 3.091 |
| example | 2020-08 | x25 | frontier | 6.8% | -7.7% | 7.3% | 20.8% | -0.3% | -11.7% | -6.3% | 7.2% | 20.8% | 0.4% | -9.7% | 2.826 |
| example | 2020-08 | x50 | w_R | 3.3% | -3.3% | 3.7% | 9.9% | 0.1% | -5.4% | -2.5% | 3.7% | 10.0% | 0.6% | -4.1% | 3.091 |
| example | 2020-08 | x50 | frontier | 10.9% | -13.8% | 10.2% | 32.1% | -2.0% | -19.7% | -12.0% | 10.1% | 31.4% | -1.0% | -17.3% | 2.318 |
| example | 2020-08 | x100 | w_R | 3.3% | -3.3% | 3.7% | 9.9% | 0.1% | -5.4% | -2.5% | 3.7% | 10.0% | 0.6% | -4.1% | 3.091 |
| example | 2020-08 | x100 | frontier | 19.0% | -28.8% | 12.3% | 51.2% | -8.5% | -37.7% | -26.6% | 12.9% | 49.7% | -7.1% | -34.2% | 1.148 |
| example | 2020-09 | x25 | w_R | 6.6% | -4.9% | 6.8% | 19.1% | 1.0% | -8.4% | -5.8% | 6.6% | 18.6% | 0.4% | -8.7% | 3.017 |
| example | 2020-09 | x25 | frontier | 6.8% | -5.8% | 7.3% | 21.5% | 0.9% | -9.3% | -6.5% | 7.1% | 20.8% | 0.3% | -9.7% | 2.713 |
| example | 2020-09 | x50 | w_R | 6.4% | -4.8% | 6.7% | 18.8% | 1.0% | -8.2% | -5.7% | 6.5% | 18.2% | 0.4% | -8.6% | 3.040 |
| example | 2020-09 | x50 | frontier | 10.8% | -10.3% | 10.4% | 32.5% | 0.2% | -16.4% | -12.0% | 10.1% | 32.1% | -1.0% | -16.7% | 2.366 |
| example | 2020-09 | x100 | w_R | 6.4% | -4.8% | 6.7% | 18.8% | 1.0% | -8.2% | -5.7% | 6.5% | 18.2% | 0.4% | -8.6% | 3.040 |
| example | 2020-09 | x100 | frontier | 19.0% | -26.8% | 12.9% | 50.2% | -7.2% | -32.7% | -26.8% | 12.8% | 50.4% | -7.2% | -33.6% | 1.151 |
| example | 2020-10 | x25 | w_R | 3.5% | -2.3% | 3.5% | 10.1% | 0.7% | -3.7% | -3.0% | 3.4% | 10.1% | 0.2% | -4.6% | 3.328 |
| example | 2020-10 | x25 | frontier | 6.8% | -6.2% | 6.3% | 21.4% | 0.3% | -8.7% | -7.8% | 6.3% | 20.4% | -0.8% | -10.6% | 2.759 |
| example | 2020-10 | x50 | w_R | 3.5% | -2.3% | 3.5% | 10.1% | 0.7% | -3.7% | -3.0% | 3.4% | 10.1% | 0.2% | -4.6% | 3.328 |
| example | 2020-10 | x50 | frontier | 10.8% | -12.1% | 9.1% | 33.3% | -1.2% | -15.8% | -13.9% | 8.8% | 31.8% | -2.5% | -18.2% | 2.571 |
| example | 2020-10 | x100 | w_R | 3.5% | -2.3% | 3.5% | 10.1% | 0.7% | -3.7% | -3.0% | 3.4% | 10.1% | 0.2% | -4.6% | 3.328 |
| example | 2020-10 | x100 | frontier | 19.0% | -25.3% | 11.5% | 48.3% | -6.9% | -31.9% | -27.1% | 11.0% | 46.9% | -8.3% | -34.3% | 1.150 |
| example | 2020-11 | x25 | w_R | 3.4% | -2.7% | 3.9% | 9.7% | 0.5% | -4.4% | -2.5% | 3.8% | 10.2% | 0.7% | -4.1% | 3.222 |
| example | 2020-11 | x25 | frontier | 7.0% | -8.0% | 7.9% | 21.6% | -0.3% | -11.1% | -6.9% | 7.5% | 22.1% | 0.3% | -10.0% | 2.600 |
| example | 2020-11 | x50 | w_R | 3.4% | -2.7% | 3.9% | 9.7% | 0.5% | -4.4% | -2.5% | 3.8% | 10.2% | 0.7% | -4.1% | 3.222 |
| example | 2020-11 | x50 | frontier | 11.3% | -13.8% | 11.1% | 34.8% | -1.5% | -19.5% | -13.1% | 11.0% | 34.5% | -1.1% | -17.9% | 2.369 |
| example | 2020-11 | x100 | w_R | 3.4% | -2.7% | 3.9% | 9.7% | 0.5% | -4.4% | -2.5% | 3.8% | 10.2% | 0.7% | -4.1% | 3.222 |
| example | 2020-11 | x100 | frontier | 20.0% | -29.8% | 14.2% | 55.9% | -8.1% | -37.5% | -28.7% | 14.2% | 55.2% | -7.4% | -36.7% | 1.156 |
| example | 2020-12 | x25 | w_R | 3.2% | -2.5% | 3.8% | 9.7% | 0.6% | -4.1% | -2.1% | 3.9% | 9.7% | 0.9% | -3.6% | 3.133 |
| example | 2020-12 | x25 | frontier | 7.0% | -8.0% | 8.0% | 22.0% | -0.2% | -11.3% | -6.6% | 8.3% | 22.6% | 0.8% | -9.6% | 2.525 |
| example | 2020-12 | x50 | w_R | 3.2% | -2.5% | 3.8% | 9.7% | 0.6% | -4.1% | -2.1% | 3.9% | 9.7% | 0.9% | -3.6% | 3.133 |
| example | 2020-12 | x50 | frontier | 11.3% | -14.4% | 11.4% | 33.8% | -1.8% | -19.2% | -11.8% | 12.2% | 35.7% | 0.2% | -16.8% | 2.469 |
| example | 2020-12 | x100 | w_R | 3.2% | -2.5% | 3.8% | 9.7% | 0.6% | -4.1% | -2.1% | 3.9% | 9.7% | 0.9% | -3.6% | 3.133 |
| example | 2020-12 | x100 | frontier | 19.9% | -29.7% | 15.5% | 58.5% | -7.3% | -36.9% | -27.1% | 16.4% | 58.7% | -5.4% | -35.6% | 1.157 |
| example | 2021-01 | x25 | w_R | 6.7% | -4.5% | 7.7% | 19.4% | 1.6% | -8.5% | -5.8% | 7.7% | 19.9% | 0.8% | -9.0% | 2.468 |
| example | 2021-01 | x25 | frontier | 7.0% | -6.0% | 8.5% | 22.2% | 1.2% | -9.7% | -6.5% | 8.6% | 22.7% | 0.9% | -10.0% | 2.335 |
| example | 2021-01 | x50 | w_R | 7.2% | -4.9% | 8.1% | 19.8% | 1.5% | -8.7% | -5.6% | 8.1% | 20.6% | 1.1% | -8.7% | 2.828 |
| example | 2021-01 | x50 | frontier | 11.2% | -10.3% | 13.0% | 35.4% | 1.3% | -17.0% | -11.6% | 13.1% | 36.6% | 0.6% | -17.1% | 2.253 |
| example | 2021-01 | x100 | w_R | 7.2% | -4.9% | 8.1% | 19.8% | 1.5% | -8.7% | -5.6% | 8.1% | 20.6% | 1.1% | -8.7% | 2.828 |
| example | 2021-01 | x100 | frontier | 19.8% | -26.9% | 18.2% | 59.6% | -4.7% | -35.4% | -26.8% | 18.4% | 61.0% | -4.5% | -34.0% | 1.161 |
| example | 2021-02 | x25 | w_R | 6.5% | -4.6% | 7.0% | 19.3% | 1.3% | -8.3% | -5.3% | 7.1% | 18.8% | 0.8% | -8.3% | 3.062 |
| example | 2021-02 | x25 | frontier | 6.9% | -6.6% | 8.2% | 22.3% | 0.7% | -10.4% | -7.1% | 8.2% | 22.3% | 0.4% | -10.8% | 2.123 |
| example | 2021-02 | x50 | w_R | 6.6% | -4.5% | 7.1% | 19.6% | 1.4% | -8.4% | -5.4% | 7.3% | 19.0% | 0.8% | -8.4% | 3.123 |
| example | 2021-02 | x50 | frontier | 11.2% | -11.8% | 12.4% | 36.3% | 0.3% | -17.3% | -12.7% | 12.5% | 35.7% | -0.3% | -18.1% | 2.079 |
| example | 2021-02 | x100 | w_R | 6.6% | -4.5% | 7.1% | 19.6% | 1.4% | -8.4% | -5.4% | 7.3% | 19.0% | 0.8% | -8.4% | 3.123 |
| example | 2021-02 | x100 | frontier | 19.7% | -27.1% | 18.6% | 61.8% | -4.5% | -33.7% | -27.1% | 18.3% | 60.4% | -4.7% | -35.1% | 1.163 |
| example | 2021-03 | x25 | w_R | 6.6% | -5.2% | 6.9% | 19.8% | 0.9% | -9.0% | -5.5% | 6.9% | 19.0% | 0.7% | -8.6% | 3.022 |
| example | 2021-03 | x25 | frontier | 7.2% | -7.0% | 7.9% | 23.0% | 0.5% | -11.9% | -7.6% | 7.9% | 22.1% | 0.0% | -11.1% | 2.100 |
| example | 2021-03 | x50 | w_R | 7.2% | -5.5% | 7.5% | 21.1% | 1.0% | -10.0% | -6.3% | 7.5% | 20.1% | 0.5% | -9.5% | 2.799 |
| example | 2021-03 | x50 | frontier | 11.7% | -12.9% | 12.0% | 37.2% | -0.4% | -20.5% | -13.6% | 12.0% | 35.5% | -1.0% | -19.2% | 1.894 |
| example | 2021-03 | x100 | w_R | 7.2% | -5.5% | 7.5% | 21.1% | 1.0% | -10.0% | -6.3% | 7.5% | 20.1% | 0.5% | -9.5% | 2.799 |
| example | 2021-03 | x100 | frontier | 20.7% | -29.8% | 17.9% | 62.5% | -6.3% | -39.6% | -29.5% | 17.3% | 62.0% | -6.3% | -38.2% | 1.077 |
| example | 2021-04 | x25 | w_R | 6.9% | -5.5% | 7.8% | 19.4% | 1.0% | -8.9% | -5.7% | 7.5% | 19.5% | 0.8% | -8.9% | 2.807 |
| example | 2021-04 | x25 | frontier | 7.2% | -7.7% | 8.6% | 22.7% | 0.2% | -10.8% | -7.1% | 8.2% | 22.6% | 0.4% | -10.9% | 2.115 |
| example | 2021-04 | x50 | w_R | 7.0% | -5.5% | 7.8% | 19.4% | 1.0% | -8.9% | -5.7% | 7.5% | 19.6% | 0.8% | -8.9% | 2.842 |
| example | 2021-04 | x50 | frontier | 11.7% | -13.4% | 13.1% | 36.9% | -0.4% | -18.4% | -13.1% | 12.4% | 36.2% | -0.5% | -18.8% | 1.877 |
| example | 2021-04 | x100 | w_R | 7.0% | -5.5% | 7.8% | 19.4% | 1.0% | -8.9% | -5.7% | 7.5% | 19.6% | 0.8% | -8.9% | 2.842 |
| example | 2021-04 | x100 | frontier | 20.7% | -29.0% | 17.8% | 64.1% | -5.6% | -36.7% | -29.9% | 17.8% | 62.0% | -6.4% | -38.2% | 1.078 |
| example | 2021-05 | x25 | w_R | 7.2% | -5.2% | 7.7% | 20.4% | 1.2% | -9.1% | -6.2% | 7.4% | 20.3% | 0.5% | -9.6% | 2.649 |
| example | 2021-05 | x25 | frontier | 7.2% | -6.9% | 8.3% | 22.4% | 0.6% | -10.9% | -7.8% | 8.0% | 23.0% | 0.0% | -11.6% | 1.999 |
| example | 2021-05 | x50 | w_R | 8.2% | -6.0% | 8.7% | 22.7% | 1.3% | -10.0% | -7.2% | 8.4% | 22.4% | 0.4% | -10.8% | 2.519 |
| example | 2021-05 | x50 | frontier | 11.7% | -11.9% | 12.7% | 37.1% | 0.4% | -18.1% | -13.5% | 12.4% | 37.3% | -0.6% | -19.4% | 1.805 |
| example | 2021-05 | x100 | w_R | 8.2% | -6.0% | 8.7% | 22.7% | 1.3% | -10.0% | -7.2% | 8.4% | 22.4% | 0.4% | -10.8% | 2.519 |
| example | 2021-05 | x100 | frontier | 20.7% | -26.9% | 18.4% | 65.7% | -4.1% | -36.2% | -29.2% | 19.0% | 64.0% | -5.5% | -38.0% | 1.078 |
| example | 2021-06 | x25 | w_R | 7.1% | -6.3% | 7.5% | 21.3% | 0.6% | -9.6% | -6.2% | 7.7% | 20.7% | 0.7% | -9.3% | 2.674 |
| example | 2021-06 | x25 | frontier | 7.2% | -7.7% | 8.1% | 24.3% | 0.2% | -11.8% | -7.5% | 8.4% | 23.2% | 0.3% | -11.2% | 1.995 |
| example | 2021-06 | x50 | w_R | 9.1% | -7.9% | 9.5% | 26.5% | 0.7% | -12.3% | -8.4% | 9.8% | 26.3% | 0.6% | -12.1% | 2.391 |
| example | 2021-06 | x50 | frontier | 11.6% | -13.2% | 13.0% | 38.8% | -0.2% | -19.4% | -13.2% | 13.0% | 38.2% | -0.2% | -19.0% | 1.744 |
| example | 2021-06 | x100 | w_R | 9.1% | -7.9% | 9.5% | 26.5% | 0.7% | -12.3% | -8.4% | 9.8% | 26.3% | 0.6% | -12.1% | 2.391 |
| example | 2021-06 | x100 | frontier | 20.6% | -30.8% | 18.9% | 65.0% | -6.3% | -37.8% | -28.7% | 19.2% | 65.4% | -4.9% | -37.5% | 1.080 |
| example | 2021-07 | x25 | w_R | 6.6% | -5.2% | 6.6% | 18.5% | 0.7% | -8.0% | -6.0% | 6.8% | 18.7% | 0.3% | -8.8% | 2.878 |
| example | 2021-07 | x25 | frontier | 7.2% | -7.8% | 7.9% | 22.5% | -0.1% | -10.9% | -7.9% | 8.0% | 22.9% | -0.1% | -11.4% | 1.988 |
| example | 2021-07 | x50 | w_R | 6.6% | -5.2% | 6.5% | 18.5% | 0.7% | -8.0% | -6.0% | 6.7% | 18.6% | 0.3% | -8.7% | 2.950 |
| example | 2021-07 | x50 | frontier | 11.7% | -13.7% | 11.9% | 36.3% | -1.0% | -18.5% | -13.7% | 12.2% | 36.6% | -0.9% | -19.0% | 1.621 |
| example | 2021-07 | x100 | w_R | 6.6% | -5.2% | 6.5% | 18.5% | 0.7% | -8.0% | -6.0% | 6.7% | 18.6% | 0.3% | -8.7% | 2.950 |
| example | 2021-07 | x100 | frontier | 20.6% | -29.6% | 17.3% | 63.9% | -6.2% | -37.7% | -29.0% | 17.1% | 64.3% | -5.8% | -36.7% | 1.081 |
| example | 2021-08 | x25 | w_R | 3.8% | -3.4% | 4.0% | 11.4% | 0.3% | -5.7% | -3.4% | 4.1% | 10.8% | 0.2% | -5.2% | 3.029 |
| example | 2021-08 | x25 | frontier | 7.2% | -9.1% | 8.1% | 22.9% | -0.7% | -12.9% | -7.7% | 8.0% | 22.6% | 0.0% | -11.5% | 2.034 |
| example | 2021-08 | x50 | w_R | 3.8% | -3.4% | 4.0% | 11.4% | 0.3% | -5.7% | -3.4% | 4.1% | 10.8% | 0.2% | -5.2% | 3.029 |
| example | 2021-08 | x50 | frontier | 11.7% | -15.8% | 12.4% | 36.8% | -2.1% | -21.8% | -13.6% | 12.4% | 36.7% | -0.8% | -19.4% | 1.599 |
| example | 2021-08 | x100 | w_R | 3.8% | -3.4% | 4.0% | 11.4% | 0.3% | -5.7% | -3.4% | 4.1% | 10.8% | 0.2% | -5.2% | 3.029 |
| example | 2021-08 | x100 | frontier | 20.7% | -33.5% | 17.9% | 62.0% | -8.5% | -41.9% | -29.1% | 17.5% | 63.1% | -5.9% | -38.1% | 1.081 |
| example | 2021-09 | x25 | w_R | 6.6% | -5.0% | 7.0% | 18.8% | 0.9% | -8.4% | -6.0% | 6.8% | 18.8% | 0.3% | -9.1% | 2.929 |
| example | 2021-09 | x25 | frontier | 7.2% | -7.2% | 7.8% | 22.2% | 0.2% | -10.6% | -7.9% | 7.7% | 22.3% | -0.2% | -11.4% | 2.160 |
| example | 2021-09 | x50 | w_R | 7.5% | -6.0% | 7.7% | 20.6% | 0.8% | -9.3% | -6.8% | 7.5% | 20.6% | 0.2% | -10.0% | 2.677 |
| example | 2021-09 | x50 | frontier | 11.7% | -14.0% | 12.0% | 35.5% | -1.2% | -17.8% | -13.8% | 11.6% | 35.7% | -1.2% | -19.0% | 1.717 |
| example | 2021-09 | x100 | w_R | 7.5% | -6.0% | 7.7% | 20.6% | 0.8% | -9.3% | -6.8% | 7.5% | 20.6% | 0.2% | -10.0% | 2.677 |
| example | 2021-09 | x100 | frontier | 20.7% | -28.1% | 16.8% | 59.8% | -5.9% | -37.4% | -30.5% | 16.5% | 61.9% | -7.1% | -37.9% | 1.082 |
| example | 2021-10 | x25 | w_R | 7.0% | -5.3% | 7.4% | 20.4% | 1.1% | -8.5% | -5.5% | 7.8% | 19.9% | 1.0% | -9.1% | 2.814 |
| example | 2021-10 | x25 | frontier | 7.2% | -6.8% | 8.2% | 23.9% | 0.8% | -10.5% | -7.2% | 8.6% | 23.0% | 0.6% | -11.2% | 2.177 |
| example | 2021-10 | x50 | w_R | 6.7% | -5.1% | 7.2% | 19.8% | 1.1% | -8.0% | -5.2% | 7.5% | 19.4% | 1.0% | -8.7% | 2.824 |
| example | 2021-10 | x50 | frontier | 11.7% | -12.9% | 12.7% | 37.7% | -0.2% | -18.5% | -13.4% | 13.2% | 37.3% | -0.3% | -19.3% | 1.853 |
| example | 2021-10 | x100 | w_R | 6.7% | -5.1% | 7.2% | 19.8% | 1.1% | -8.0% | -5.2% | 7.5% | 19.4% | 1.0% | -8.7% | 2.824 |
| example | 2021-10 | x100 | frontier | 20.7% | -28.7% | 18.6% | 64.2% | -5.2% | -38.0% | -29.0% | 18.9% | 63.7% | -5.4% | -38.5% | 1.082 |
| example | 2021-11 | x25 | w_R | 7.1% | -5.9% | 8.3% | 21.5% | 1.1% | -9.4% | -6.2% | 8.1% | 21.4% | 0.8% | -9.3% | 2.788 |
| example | 2021-11 | x25 | frontier | 7.2% | -7.1% | 8.6% | 22.7% | 0.6% | -10.6% | -6.9% | 8.6% | 23.3% | 0.8% | -10.5% | 2.336 |
| example | 2021-11 | x50 | w_R | 7.0% | -5.9% | 8.1% | 21.0% | 1.0% | -9.4% | -6.1% | 8.0% | 21.2% | 0.8% | -9.2% | 2.784 |
| example | 2021-11 | x50 | frontier | 11.7% | -13.2% | 12.6% | 36.4% | -0.5% | -18.9% | -13.1% | 12.9% | 37.3% | -0.3% | -18.5% | 1.911 |
| example | 2021-11 | x100 | w_R | 7.0% | -5.9% | 8.1% | 21.0% | 1.0% | -9.4% | -6.1% | 8.0% | 21.2% | 0.8% | -9.2% | 2.784 |
| example | 2021-11 | x100 | frontier | 20.7% | -30.9% | 16.8% | 60.0% | -7.5% | -38.6% | -29.4% | 17.1% | 62.7% | -6.2% | -37.7% | 1.082 |
| example | 2021-12 | x25 | w_R | 7.1% | -5.2% | 8.2% | 21.1% | 1.4% | -8.3% | -5.6% | 8.0% | 20.1% | 1.0% | -8.5% | 2.735 |
| example | 2021-12 | x25 | frontier | 7.2% | -6.8% | 8.9% | 23.7% | 1.0% | -9.8% | -6.7% | 8.6% | 22.8% | 0.9% | -10.1% | 2.343 |
| example | 2021-12 | x50 | w_R | 8.3% | -6.6% | 9.6% | 25.0% | 1.4% | -10.5% | -7.3% | 9.4% | 23.8% | 0.8% | -10.9% | 2.500 |
| example | 2021-12 | x50 | frontier | 11.8% | -11.7% | 13.4% | 38.6% | 0.9% | -17.5% | -13.0% | 13.2% | 36.7% | -0.2% | -18.3% | 1.968 |
| example | 2021-12 | x100 | w_R | 8.3% | -6.6% | 9.6% | 25.0% | 1.4% | -10.5% | -7.3% | 9.4% | 23.8% | 0.8% | -10.9% | 2.500 |
| example | 2021-12 | x100 | frontier | 20.8% | -27.4% | 19.7% | 65.0% | -4.0% | -36.2% | -29.3% | 18.1% | 62.4% | -5.9% | -37.9% | 1.082 |
| example | 2022-01 | x25 | w_R | 6.9% | -5.9% | 7.2% | 18.9% | 0.5% | -8.7% | -6.1% | 6.9% | 19.1% | 0.3% | -9.2% | 2.878 |
| example | 2022-01 | x25 | frontier | 7.3% | -7.5% | 7.9% | 22.2% | 0.1% | -10.5% | -7.6% | 7.6% | 22.0% | -0.1% | -11.2% | 2.384 |
| example | 2022-01 | x50 | w_R | 7.2% | -5.9% | 7.4% | 19.5% | 0.7% | -9.0% | -6.3% | 7.1% | 19.8% | 0.3% | -9.7% | 3.090 |
| example | 2022-01 | x50 | frontier | 11.8% | -13.3% | 12.2% | 34.4% | -0.9% | -18.0% | -13.2% | 11.6% | 34.3% | -1.0% | -18.5% | 2.086 |
| example | 2022-01 | x100 | w_R | 7.2% | -5.9% | 7.4% | 19.5% | 0.7% | -9.0% | -6.3% | 7.1% | 19.8% | 0.3% | -9.7% | 3.090 |
| example | 2022-01 | x100 | frontier | 20.9% | -28.0% | 17.3% | 60.8% | -5.5% | -38.9% | -30.5% | 15.7% | 61.2% | -7.5% | -38.8% | 1.082 |
| example | 2022-02 | x25 | w_R | 6.6% | -5.9% | 6.1% | 18.4% | 0.1% | -8.9% | -6.4% | 6.1% | 18.3% | -0.2% | -9.3% | 2.976 |
| example | 2022-02 | x25 | frontier | 7.3% | -7.7% | 7.1% | 21.9% | -0.3% | -11.1% | -8.1% | 7.1% | 21.8% | -0.5% | -11.7% | 2.398 |
| example | 2022-02 | x50 | w_R | 6.6% | -5.9% | 6.1% | 18.1% | 0.1% | -8.8% | -6.5% | 6.1% | 18.4% | -0.2% | -9.4% | 3.154 |
| example | 2022-02 | x50 | frontier | 11.9% | -13.9% | 10.9% | 34.0% | -1.7% | -19.4% | -14.3% | 10.7% | 34.3% | -2.0% | -19.3% | 2.127 |
| example | 2022-02 | x100 | w_R | 6.6% | -5.9% | 6.1% | 18.1% | 0.1% | -8.8% | -6.5% | 6.1% | 18.4% | -0.2% | -9.4% | 3.154 |
| example | 2022-02 | x100 | frontier | 21.1% | -32.1% | 14.7% | 60.4% | -8.8% | -39.9% | -30.8% | 14.7% | 59.5% | -8.1% | -38.1% | 1.081 |
| example | 2022-03 | x25 | w_R | 4.0% | -4.3% | 3.6% | 11.2% | -0.4% | -6.3% | -4.3% | 3.6% | 11.1% | -0.4% | -6.1% | 3.097 |
| example | 2022-03 | x25 | frontier | 7.4% | -9.1% | 7.5% | 21.5% | -1.1% | -12.7% | -8.4% | 7.2% | 21.8% | -0.7% | -11.9% | 2.394 |
| example | 2022-03 | x50 | w_R | 4.0% | -4.3% | 3.6% | 11.2% | -0.4% | -6.3% | -4.3% | 3.6% | 11.1% | -0.4% | -6.1% | 3.097 |
| example | 2022-03 | x50 | frontier | 12.0% | -16.0% | 11.5% | 34.4% | -2.7% | -21.2% | -14.4% | 11.1% | 34.3% | -1.9% | -19.9% | 2.056 |
| example | 2022-03 | x100 | w_R | 4.0% | -4.3% | 3.6% | 11.2% | -0.4% | -6.3% | -4.3% | 3.6% | 11.1% | -0.4% | -6.1% | 3.097 |
| example | 2022-03 | x100 | frontier | 21.3% | -32.3% | 15.9% | 58.4% | -8.8% | -41.6% | -30.9% | 15.3% | 61.5% | -7.8% | -39.6% | 1.080 |
| example | 2022-04 | x25 | w_R | 3.6% | -4.6% | 2.8% | 9.9% | -0.9% | -6.4% | -4.8% | 2.8% | 9.6% | -1.1% | -6.7% | 2.506 |
| example | 2022-04 | x25 | frontier | 7.5% | -9.7% | 6.1% | 20.6% | -1.9% | -13.7% | -9.4% | 6.0% | 20.6% | -1.8% | -13.1% | 2.293 |
| example | 2022-04 | x50 | w_R | 3.6% | -4.6% | 2.8% | 9.9% | -0.9% | -6.4% | -4.8% | 2.8% | 9.6% | -1.1% | -6.7% | 2.506 |
| example | 2022-04 | x50 | frontier | 12.2% | -16.4% | 9.0% | 32.5% | -3.9% | -22.3% | -15.6% | 8.9% | 32.7% | -3.4% | -20.7% | 1.955 |
| example | 2022-04 | x100 | w_R | 3.6% | -4.6% | 2.8% | 9.9% | -0.9% | -6.4% | -4.8% | 2.8% | 9.6% | -1.1% | -6.7% | 2.506 |
| example | 2022-04 | x100 | frontier | 21.4% | -33.5% | 11.6% | 57.8% | -10.8% | -42.5% | -32.0% | 12.0% | 57.8% | -9.9% | -39.2% | 1.079 |
| example | 2022-06 | x25 | w_R | 3.5% | -4.9% | 2.2% | 9.0% | -1.4% | -6.8% | -5.0% | 2.2% | 8.6% | -1.5% | -6.6% | 2.561 |
| example | 2022-06 | x25 | frontier | 7.6% | -11.5% | 4.8% | 19.8% | -3.5% | -15.1% | -11.2% | 4.9% | 19.2% | -3.4% | -14.4% | 2.112 |
| example | 2022-06 | x50 | w_R | 3.5% | -4.9% | 2.2% | 9.0% | -1.4% | -6.8% | -5.0% | 2.2% | 8.6% | -1.5% | -6.6% | 2.561 |
| example | 2022-06 | x50 | frontier | 12.2% | -19.4% | 6.9% | 31.4% | -6.4% | -23.7% | -18.1% | 6.9% | 30.9% | -5.7% | -23.0% | 1.729 |
| example | 2022-06 | x100 | w_R | 3.5% | -4.9% | 2.2% | 9.0% | -1.4% | -6.8% | -5.0% | 2.2% | 8.6% | -1.5% | -6.6% | 2.561 |
| example | 2022-06 | x100 | frontier | 21.4% | -33.6% | 9.4% | 54.5% | -11.9% | -40.6% | -32.8% | 9.4% | 54.7% | -11.4% | -40.3% | 1.085 |
| example | 2022-07 | x25 | w_R | 3.5% | -5.0% | 2.5% | 9.3% | -1.3% | -7.1% | -5.0% | 2.4% | 8.9% | -1.4% | -6.9% | 2.472 |
| example | 2022-07 | x25 | frontier | 7.9% | -11.4% | 5.8% | 22.1% | -2.9% | -15.1% | -11.1% | 5.8% | 21.0% | -2.8% | -15.2% | 2.127 |
| example | 2022-07 | x50 | w_R | 3.5% | -5.0% | 2.5% | 9.3% | -1.3% | -7.1% | -5.0% | 2.4% | 8.9% | -1.4% | -6.9% | 2.472 |
| example | 2022-07 | x50 | frontier | 12.7% | -18.4% | 8.5% | 34.3% | -5.1% | -23.0% | -17.7% | 8.4% | 33.1% | -4.8% | -23.7% | 1.821 |
| example | 2022-07 | x100 | w_R | 3.5% | -5.0% | 2.5% | 9.3% | -1.3% | -7.1% | -5.0% | 2.4% | 8.9% | -1.4% | -6.9% | 2.472 |
| example | 2022-07 | x100 | frontier | 22.2% | -34.0% | 11.7% | 61.2% | -10.8% | -40.4% | -33.5% | 11.0% | 58.9% | -10.9% | -41.7% | 1.073 |
| example | 2022-08 | x25 | w_R | 3.6% | -4.5% | 2.5% | 8.8% | -1.1% | -5.8% | -4.9% | 2.2% | 8.6% | -1.4% | -6.6% | 2.475 |
| example | 2022-08 | x25 | frontier | 8.0% | -11.6% | 5.7% | 20.0% | -3.2% | -14.6% | -11.7% | 5.1% | 20.3% | -3.4% | -15.5% | 1.956 |
| example | 2022-08 | x50 | w_R | 3.6% | -4.5% | 2.5% | 8.8% | -1.1% | -5.8% | -4.9% | 2.2% | 8.6% | -1.4% | -6.6% | 2.475 |
| example | 2022-08 | x50 | frontier | 12.8% | -18.7% | 8.2% | 32.0% | -5.5% | -23.2% | -18.9% | 7.2% | 32.3% | -5.9% | -24.2% | 1.862 |
| example | 2022-08 | x100 | w_R | 3.6% | -4.5% | 2.5% | 8.8% | -1.1% | -5.8% | -4.9% | 2.2% | 8.6% | -1.4% | -6.6% | 2.475 |
| example | 2022-08 | x100 | frontier | 22.4% | -35.2% | 11.7% | 56.5% | -12.0% | -42.3% | -35.0% | 9.9% | 56.9% | -12.3% | -43.2% | 1.072 |
| example | 2022-09 | x25 | w_R | 3.3% | -5.5% | 1.5% | 7.2% | -2.2% | -7.1% | -5.9% | 1.4% | 7.6% | -2.3% | -7.4% | 2.152 |
| example | 2022-09 | x25 | frontier | 7.9% | -11.8% | 3.8% | 18.0% | -4.2% | -15.3% | -12.6% | 3.8% | 18.8% | -4.5% | -16.1% | 1.672 |
| example | 2022-09 | x50 | w_R | 3.3% | -5.5% | 1.5% | 7.2% | -2.2% | -7.1% | -5.9% | 1.4% | 7.6% | -2.3% | -7.4% | 2.152 |
| example | 2022-09 | x50 | frontier | 12.6% | -18.3% | 5.0% | 27.1% | -6.7% | -23.3% | -19.3% | 5.1% | 28.3% | -7.2% | -24.4% | 1.351 |
| example | 2022-09 | x100 | w_R | 3.3% | -5.5% | 1.5% | 7.2% | -2.2% | -7.1% | -5.9% | 1.4% | 7.6% | -2.3% | -7.4% | 2.152 |
| example | 2022-09 | x100 | frontier | 21.9% | -34.3% | 6.1% | 50.8% | -13.7% | -41.4% | -34.4% | 6.3% | 51.1% | -13.6% | -42.2% | 1.081 |
| example | 2022-10 | x25 | w_R | 3.5% | -5.8% | 1.6% | 8.0% | -2.2% | -7.3% | -5.8% | 1.7% | 8.1% | -2.2% | -7.4% | 2.342 |
| example | 2022-10 | x25 | frontier | 8.0% | -12.5% | 4.4% | 19.1% | -4.3% | -16.2% | -12.3% | 4.3% | 19.0% | -4.2% | -15.8% | 1.642 |
| example | 2022-10 | x50 | w_R | 3.5% | -5.8% | 1.6% | 8.0% | -2.2% | -7.3% | -5.8% | 1.7% | 8.1% | -2.2% | -7.4% | 2.342 |
| example | 2022-10 | x50 | frontier | 12.7% | -19.3% | 5.9% | 30.1% | -6.8% | -25.0% | -19.2% | 5.8% | 29.2% | -6.8% | -24.3% | 1.352 |
| example | 2022-10 | x100 | w_R | 3.5% | -5.8% | 1.6% | 8.0% | -2.2% | -7.3% | -5.8% | 1.7% | 8.1% | -2.2% | -7.4% | 2.342 |
| example | 2022-10 | x100 | frontier | 22.2% | -36.6% | 7.5% | 53.1% | -14.4% | -43.7% | -34.4% | 7.5% | 51.6% | -13.3% | -42.7% | 1.079 |
| example | 2022-11 | x25 | w_R | 3.6% | -5.2% | 2.1% | 8.9% | -1.6% | -6.8% | -5.3% | 2.2% | 8.9% | -1.6% | -6.9% | 2.330 |
| example | 2022-11 | x25 | frontier | 8.2% | -12.5% | 4.7% | 20.9% | -4.0% | -16.3% | -11.9% | 4.9% | 20.3% | -3.6% | -15.5% | 1.662 |
| example | 2022-11 | x50 | w_R | 3.6% | -5.2% | 2.1% | 8.9% | -1.6% | -6.8% | -5.3% | 2.2% | 8.9% | -1.6% | -6.9% | 2.330 |
| example | 2022-11 | x50 | frontier | 12.9% | -19.8% | 6.4% | 32.2% | -6.7% | -25.0% | -18.8% | 6.6% | 31.7% | -6.1% | -24.0% | 1.431 |
| example | 2022-11 | x100 | w_R | 3.6% | -5.2% | 2.1% | 8.9% | -1.6% | -6.8% | -5.3% | 2.2% | 8.9% | -1.6% | -6.9% | 2.330 |
| example | 2022-11 | x100 | frontier | 22.4% | -35.7% | 8.1% | 57.0% | -13.3% | -43.1% | -34.4% | 8.8% | 55.1% | -12.5% | -41.6% | 1.078 |
| example | 2022-12 | x25 | w_R | 3.5% | -5.4% | 2.0% | 8.5% | -1.8% | -7.0% | -5.6% | 1.8% | 8.5% | -1.9% | -7.0% | 2.034 |
| example | 2022-12 | x25 | frontier | 8.2% | -13.1% | 4.3% | 20.0% | -4.6% | -16.5% | -12.0% | 4.3% | 18.7% | -4.0% | -15.7% | 1.601 |
| example | 2022-12 | x50 | w_R | 3.5% | -5.4% | 2.0% | 8.5% | -1.8% | -7.0% | -5.6% | 1.8% | 8.5% | -1.9% | -7.0% | 2.034 |
| example | 2022-12 | x50 | frontier | 13.0% | -20.1% | 5.4% | 29.9% | -7.5% | -25.3% | -18.8% | 5.7% | 28.0% | -6.8% | -24.1% | 1.213 |
| example | 2022-12 | x100 | w_R | 3.5% | -5.4% | 2.0% | 8.5% | -1.8% | -7.0% | -5.6% | 1.8% | 8.5% | -1.9% | -7.0% | 2.034 |
| example | 2022-12 | x100 | frontier | 22.5% | -36.8% | 6.3% | 54.3% | -14.7% | -44.0% | -34.7% | 6.8% | 51.4% | -13.6% | -42.1% | 1.076 |
| example | 2023-01 | x25 | w_R | 3.6% | -4.6% | 2.6% | 9.2% | -1.0% | -6.4% | -5.3% | 2.4% | 9.2% | -1.5% | -6.9% | 2.144 |
| example | 2023-01 | x25 | frontier | 8.4% | -10.9% | 5.2% | 21.0% | -2.9% | -14.4% | -12.1% | 4.6% | 20.2% | -3.9% | -15.6% | 1.768 |
| example | 2023-01 | x50 | w_R | 3.6% | -4.6% | 2.6% | 9.2% | -1.0% | -6.4% | -5.3% | 2.4% | 9.2% | -1.5% | -6.9% | 2.144 |
| example | 2023-01 | x50 | frontier | 13.3% | -17.6% | 6.9% | 32.2% | -5.3% | -22.9% | -19.6% | 6.1% | 30.8% | -6.8% | -24.7% | 1.457 |
| example | 2023-01 | x100 | w_R | 3.6% | -4.6% | 2.6% | 9.2% | -1.0% | -6.4% | -5.3% | 2.4% | 9.2% | -1.5% | -6.9% | 2.144 |
| example | 2023-01 | x100 | frontier | 23.0% | -33.6% | 8.8% | 55.8% | -12.0% | -40.2% | -34.9% | 7.8% | 54.7% | -13.1% | -42.5% | 1.127 |
| example | 2023-02 | x25 | w_R | 3.6% | -5.2% | 2.6% | 9.3% | -1.4% | -7.0% | -5.2% | 2.6% | 9.4% | -1.4% | -6.8% | 2.056 |
| example | 2023-02 | x25 | frontier | 8.4% | -13.4% | 5.0% | 20.3% | -4.5% | -15.6% | -11.8% | 4.9% | 20.7% | -3.5% | -15.3% | 1.798 |
| example | 2023-02 | x50 | w_R | 3.6% | -5.2% | 2.6% | 9.3% | -1.4% | -7.0% | -5.2% | 2.6% | 9.4% | -1.4% | -6.8% | 2.056 |
| example | 2023-02 | x50 | frontier | 13.2% | -20.2% | 6.4% | 30.2% | -7.2% | -24.4% | -18.9% | 6.4% | 31.1% | -6.3% | -23.9% | 1.664 |
| example | 2023-02 | x100 | w_R | 3.6% | -5.2% | 2.6% | 9.3% | -1.4% | -7.0% | -5.2% | 2.6% | 9.4% | -1.4% | -6.8% | 2.056 |
| example | 2023-02 | x100 | frontier | 22.9% | -36.4% | 8.2% | 53.3% | -14.0% | -43.2% | -35.1% | 8.2% | 54.2% | -13.2% | -41.8% | 1.126 |
| example | 2023-03 | x25 | w_R | 3.7% | -4.9% | 3.1% | 10.1% | -1.0% | -7.0% | -4.9% | 3.1% | 9.9% | -1.0% | -6.6% | 2.239 |
| example | 2023-03 | x25 | frontier | 8.4% | -11.4% | 5.7% | 20.3% | -3.1% | -15.2% | -11.5% | 5.5% | 20.8% | -3.2% | -14.7% | 1.810 |
| example | 2023-03 | x50 | w_R | 3.7% | -4.9% | 3.1% | 10.1% | -1.0% | -7.0% | -4.9% | 3.1% | 9.9% | -1.0% | -6.6% | 2.239 |
| example | 2023-03 | x50 | frontier | 13.1% | -18.5% | 7.1% | 30.8% | -5.8% | -23.4% | -18.2% | 6.9% | 31.3% | -5.7% | -23.3% | 1.599 |
| example | 2023-03 | x100 | w_R | 3.7% | -4.9% | 3.1% | 10.1% | -1.0% | -7.0% | -4.9% | 3.1% | 9.9% | -1.0% | -6.6% | 2.239 |
| example | 2023-03 | x100 | frontier | 22.5% | -34.7% | 9.0% | 54.3% | -12.7% | -41.2% | -33.3% | 8.1% | 55.3% | -12.0% | -40.6% | 1.076 |
| example | 2023-04 | x25 | w_R | 3.7% | -3.9% | 3.2% | 9.8% | -0.4% | -5.8% | -4.8% | 3.3% | 10.0% | -0.9% | -6.4% | 2.212 |
| example | 2023-04 | x25 | frontier | 8.4% | -10.5% | 5.8% | 21.8% | -2.4% | -14.3% | -11.9% | 5.6% | 21.1% | -3.3% | -15.4% | 1.958 |
| example | 2023-04 | x50 | w_R | 3.7% | -3.9% | 3.2% | 9.8% | -0.4% | -5.8% | -4.8% | 3.3% | 10.0% | -0.9% | -6.4% | 2.212 |
| example | 2023-04 | x50 | frontier | 13.1% | -18.1% | 7.3% | 32.5% | -5.4% | -23.0% | -19.1% | 7.1% | 31.5% | -6.2% | -24.0% | 1.680 |
| example | 2023-04 | x100 | w_R | 3.7% | -3.9% | 3.2% | 9.8% | -0.4% | -5.8% | -4.8% | 3.3% | 10.0% | -0.9% | -6.4% | 2.212 |
| example | 2023-04 | x100 | frontier | 22.5% | -33.4% | 8.9% | 55.9% | -11.8% | -41.1% | -34.4% | 8.1% | 54.8% | -12.7% | -42.4% | 1.076 |
| example | 2023-05 | x25 | w_R | 4.2% | -4.3% | 3.7% | 11.0% | -0.3% | -6.5% | -4.7% | 3.5% | 10.8% | -0.7% | -6.4% | 2.390 |
| example | 2023-05 | x25 | frontier | 7.9% | -9.8% | 5.5% | 19.2% | -2.3% | -13.0% | -10.0% | 5.2% | 18.9% | -2.6% | -13.5% | 1.773 |
| example | 2023-05 | x50 | w_R | 4.2% | -4.3% | 3.7% | 11.0% | -0.3% | -6.5% | -4.7% | 3.5% | 10.8% | -0.7% | -6.4% | 2.390 |
| example | 2023-05 | x50 | frontier | 12.1% | -15.4% | 6.9% | 27.6% | -4.4% | -20.0% | -16.1% | 6.4% | 27.3% | -5.0% | -21.0% | 1.590 |
| example | 2023-05 | x100 | w_R | 4.2% | -4.3% | 3.7% | 11.0% | -0.3% | -6.5% | -4.7% | 3.5% | 10.8% | -0.7% | -6.4% | 2.390 |
| example | 2023-05 | x100 | frontier | 20.5% | -28.2% | 8.6% | 45.4% | -9.8% | -34.9% | -28.4% | 7.4% | 46.0% | -10.2% | -35.9% | 1.140 |
| example | 2023-06 | x25 | w_R | 4.7% | -4.8% | 4.1% | 12.2% | -0.4% | -6.9% | -5.4% | 4.2% | 12.8% | -0.7% | -7.6% | 2.291 |
| example | 2023-06 | x25 | frontier | 7.9% | -9.1% | 5.6% | 19.1% | -1.8% | -13.0% | -10.5% | 5.8% | 20.3% | -2.5% | -14.0% | 1.872 |
| example | 2023-06 | x50 | w_R | 4.7% | -4.8% | 4.1% | 12.2% | -0.4% | -6.9% | -5.4% | 4.2% | 12.8% | -0.7% | -7.6% | 2.291 |
| example | 2023-06 | x50 | frontier | 12.1% | -15.3% | 7.2% | 28.6% | -4.1% | -20.3% | -17.0% | 7.3% | 29.4% | -5.1% | -21.9% | 1.576 |
| example | 2023-06 | x100 | w_R | 4.7% | -4.8% | 4.1% | 12.2% | -0.4% | -6.9% | -5.4% | 4.2% | 12.8% | -0.7% | -7.6% | 2.291 |
| example | 2023-06 | x100 | frontier | 20.5% | -27.5% | 8.8% | 48.4% | -9.0% | -35.1% | -30.3% | 8.9% | 48.5% | -10.6% | -37.6% | 1.142 |
| example | 2023-07 | x25 | w_R | 4.0% | -4.6% | 3.9% | 10.9% | -0.5% | -6.5% | -4.3% | 4.0% | 11.2% | -0.3% | -6.1% | 2.359 |
| example | 2023-07 | x25 | frontier | 8.0% | -11.7% | 5.6% | 20.1% | -3.3% | -14.7% | -9.9% | 5.9% | 20.2% | -2.1% | -13.2% | 1.786 |
| example | 2023-07 | x50 | w_R | 4.0% | -4.6% | 3.9% | 10.9% | -0.5% | -6.5% | -4.3% | 4.0% | 11.2% | -0.3% | -6.1% | 2.359 |
| example | 2023-07 | x50 | frontier | 12.2% | -18.1% | 6.9% | 29.1% | -5.9% | -23.2% | -16.0% | 7.3% | 29.3% | -4.4% | -20.9% | 1.523 |
| example | 2023-07 | x100 | w_R | 4.0% | -4.6% | 3.9% | 10.9% | -0.5% | -6.5% | -4.3% | 4.0% | 11.2% | -0.3% | -6.1% | 2.359 |
| example | 2023-07 | x100 | frontier | 20.7% | -32.1% | 8.5% | 46.1% | -12.1% | -40.2% | -30.0% | 8.9% | 48.3% | -10.5% | -36.9% | 1.150 |
| example | 2023-08 | x25 | w_R | 4.1% | -3.6% | 4.0% | 11.3% | 0.2% | -5.3% | -4.3% | 3.9% | 11.1% | -0.3% | -6.0% | 2.334 |
| example | 2023-08 | x25 | frontier | 8.0% | -9.7% | 5.8% | 19.4% | -2.2% | -13.1% | -10.1% | 5.6% | 19.7% | -2.4% | -13.3% | 1.784 |
| example | 2023-08 | x50 | w_R | 4.1% | -3.6% | 4.0% | 11.3% | 0.2% | -5.3% | -4.3% | 3.9% | 11.1% | -0.3% | -6.0% | 2.334 |
| example | 2023-08 | x50 | frontier | 12.2% | -16.9% | 6.7% | 27.8% | -5.3% | -21.4% | -16.5% | 6.7% | 28.2% | -5.1% | -21.2% | 1.387 |
| example | 2023-08 | x100 | w_R | 4.1% | -3.6% | 4.0% | 11.3% | 0.2% | -5.3% | -4.3% | 3.9% | 11.1% | -0.3% | -6.0% | 2.334 |
| example | 2023-08 | x100 | frontier | 20.7% | -31.4% | 7.6% | 46.4% | -11.9% | -38.5% | -30.6% | 7.6% | 46.6% | -11.4% | -37.6% | 1.150 |
| example | 2023-09 | x25 | w_R | 4.0% | -4.3% | 3.8% | 11.3% | -0.3% | -6.1% | -4.5% | 3.7% | 11.1% | -0.5% | -6.6% | 2.316 |
| example | 2023-09 | x25 | frontier | 8.0% | -10.2% | 5.4% | 20.2% | -2.5% | -13.8% | -10.9% | 5.4% | 19.9% | -2.9% | -14.5% | 1.782 |
| example | 2023-09 | x50 | w_R | 4.0% | -4.3% | 3.8% | 11.3% | -0.3% | -6.1% | -4.5% | 3.7% | 11.1% | -0.5% | -6.6% | 2.316 |
| example | 2023-09 | x50 | frontier | 12.2% | -17.1% | 6.3% | 29.0% | -5.5% | -22.1% | -17.5% | 6.4% | 28.5% | -5.7% | -22.8% | 1.416 |
| example | 2023-09 | x100 | w_R | 4.0% | -4.3% | 3.8% | 11.3% | -0.3% | -6.1% | -4.5% | 3.7% | 11.1% | -0.5% | -6.6% | 2.316 |
| example | 2023-09 | x100 | frontier | 20.7% | -31.2% | 6.8% | 48.2% | -11.9% | -38.7% | -32.1% | 6.8% | 47.1% | -12.5% | -39.3% | 1.150 |
| example | 2023-10 | x25 | w_R | 4.5% | -4.4% | 4.4% | 12.7% | -0.1% | -6.7% | -4.9% | 4.3% | 12.2% | -0.4% | -6.8% | 2.372 |
| example | 2023-10 | x25 | frontier | 8.0% | -9.5% | 6.2% | 20.6% | -1.8% | -12.7% | -10.0% | 5.8% | 19.9% | -2.2% | -13.2% | 1.771 |
| example | 2023-10 | x50 | w_R | 4.5% | -4.4% | 4.4% | 12.7% | -0.1% | -6.7% | -4.9% | 4.3% | 12.2% | -0.4% | -6.8% | 2.372 |
| example | 2023-10 | x50 | frontier | 12.2% | -15.6% | 7.3% | 29.0% | -4.3% | -20.5% | -16.7% | 6.7% | 28.3% | -5.2% | -21.5% | 1.419 |
| example | 2023-10 | x100 | w_R | 4.5% | -4.4% | 4.4% | 12.7% | -0.1% | -6.7% | -4.9% | 4.3% | 12.2% | -0.4% | -6.8% | 2.372 |
| example | 2023-10 | x100 | frontier | 20.6% | -30.4% | 8.2% | 47.7% | -11.0% | -36.7% | -31.4% | 7.5% | 46.6% | -11.9% | -38.4% | 1.152 |
| example | 2023-11 | x25 | w_R | 4.2% | -3.8% | 4.5% | 12.5% | 0.3% | -5.6% | -4.1% | 4.7% | 12.1% | 0.1% | -5.9% | 2.300 |
| example | 2023-11 | x25 | frontier | 8.4% | -10.3% | 6.9% | 22.2% | -1.9% | -13.2% | -9.9% | 6.8% | 21.2% | -1.8% | -13.7% | 1.750 |
| example | 2023-11 | x50 | w_R | 4.2% | -3.8% | 4.5% | 12.5% | 0.3% | -5.6% | -4.1% | 4.7% | 12.1% | 0.1% | -5.9% | 2.300 |
| example | 2023-11 | x50 | frontier | 12.9% | -17.2% | 8.3% | 32.2% | -4.6% | -21.9% | -16.7% | 8.2% | 30.9% | -4.5% | -21.7% | 1.287 |
| example | 2023-11 | x100 | w_R | 4.2% | -3.8% | 4.5% | 12.5% | 0.3% | -5.6% | -4.1% | 4.7% | 12.1% | 0.1% | -5.9% | 2.300 |
| example | 2023-11 | x100 | frontier | 21.9% | -32.7% | 9.0% | 55.1% | -11.4% | -40.2% | -32.0% | 8.9% | 53.0% | -11.2% | -39.6% | 1.138 |
| example | 2023-12 | x25 | w_R | 4.4% | -3.5% | 5.3% | 13.5% | 0.8% | -5.4% | -3.9% | 5.3% | 13.4% | 0.6% | -5.7% | 2.360 |
| example | 2023-12 | x25 | frontier | 8.4% | -8.8% | 7.9% | 22.6% | -0.7% | -12.1% | -9.0% | 7.9% | 22.5% | -0.8% | -12.5% | 1.755 |
| example | 2023-12 | x50 | w_R | 4.4% | -3.5% | 5.3% | 13.5% | 0.8% | -5.4% | -3.9% | 5.3% | 13.4% | 0.6% | -5.7% | 2.360 |
| example | 2023-12 | x50 | frontier | 12.8% | -15.7% | 9.9% | 33.3% | -3.1% | -19.7% | -15.6% | 10.0% | 33.5% | -3.0% | -20.5% | 1.448 |
| example | 2023-12 | x100 | w_R | 4.4% | -3.5% | 5.3% | 13.5% | 0.8% | -5.4% | -3.9% | 5.3% | 13.4% | 0.6% | -5.7% | 2.360 |
| example | 2023-12 | x100 | frontier | 21.7% | -31.1% | 12.2% | 57.0% | -9.3% | -36.7% | -30.5% | 12.1% | 57.4% | -8.9% | -37.9% | 1.143 |
| example | 2024-01 | x25 | w_R | 4.4% | -4.1% | 5.2% | 13.3% | 0.4% | -6.0% | -3.8% | 5.1% | 13.6% | 0.6% | -5.8% | 2.307 |
| example | 2024-01 | x25 | frontier | 8.3% | -9.8% | 7.4% | 21.8% | -1.5% | -13.5% | -9.6% | 7.3% | 22.7% | -1.3% | -13.0% | 1.755 |
| example | 2024-01 | x50 | w_R | 4.4% | -4.1% | 5.2% | 13.3% | 0.4% | -6.0% | -3.8% | 5.1% | 13.6% | 0.6% | -5.8% | 2.307 |
| example | 2024-01 | x50 | frontier | 12.8% | -17.3% | 8.9% | 32.3% | -4.5% | -21.9% | -16.1% | 8.8% | 32.9% | -3.7% | -21.1% | 1.388 |
| example | 2024-01 | x100 | w_R | 4.4% | -4.1% | 5.2% | 13.3% | 0.4% | -6.0% | -3.8% | 5.1% | 13.6% | 0.6% | -5.8% | 2.307 |
| example | 2024-01 | x100 | frontier | 21.6% | -32.5% | 10.4% | 55.6% | -10.8% | -39.7% | -31.6% | 10.0% | 53.2% | -10.6% | -38.4% | 1.144 |
| example | 2024-02 | x25 | w_R | 4.7% | -4.4% | 5.2% | 14.0% | 0.3% | -6.6% | -4.0% | 5.2% | 13.9% | 0.6% | -6.0% | 2.262 |
| example | 2024-02 | x25 | frontier | 8.4% | -10.2% | 7.5% | 23.2% | -1.5% | -14.3% | -9.3% | 7.3% | 22.6% | -1.1% | -12.8% | 1.756 |
| example | 2024-02 | x50 | w_R | 4.7% | -4.4% | 5.2% | 14.0% | 0.3% | -6.6% | -4.0% | 5.2% | 13.9% | 0.6% | -6.0% | 2.262 |
| example | 2024-02 | x50 | frontier | 12.8% | -17.4% | 9.1% | 33.3% | -4.4% | -22.4% | -15.7% | 8.9% | 32.6% | -3.5% | -20.6% | 1.276 |
| example | 2024-02 | x100 | w_R | 4.7% | -4.4% | 5.2% | 14.0% | 0.3% | -6.6% | -4.0% | 5.2% | 13.9% | 0.6% | -6.0% | 2.262 |
| example | 2024-02 | x100 | frontier | 21.6% | -34.0% | 10.0% | 55.0% | -11.9% | -39.9% | -30.7% | 10.0% | 54.0% | -10.0% | -38.1% | 1.145 |
| example | 2024-03 | x25 | w_R | 4.2% | -3.8% | 5.1% | 12.9% | 0.5% | -5.8% | -3.7% | 4.9% | 12.7% | 0.5% | -5.5% | 2.263 |
| example | 2024-03 | x25 | frontier | 8.4% | -9.3% | 7.8% | 23.0% | -0.9% | -13.0% | -9.2% | 7.6% | 22.7% | -1.0% | -13.1% | 1.710 |
| example | 2024-03 | x50 | w_R | 4.2% | -3.8% | 5.1% | 12.9% | 0.5% | -5.8% | -3.7% | 4.9% | 12.7% | 0.5% | -5.5% | 2.263 |
| example | 2024-03 | x50 | frontier | 12.8% | -15.3% | 9.8% | 32.7% | -3.0% | -20.9% | -16.3% | 9.3% | 32.5% | -3.8% | -21.6% | 1.328 |
| example | 2024-03 | x100 | w_R | 4.2% | -3.8% | 5.1% | 12.9% | 0.5% | -5.8% | -3.7% | 4.9% | 12.7% | 0.5% | -5.5% | 2.263 |
| example | 2024-03 | x100 | frontier | 21.6% | -31.1% | 11.2% | 55.7% | -9.7% | -37.9% | -32.4% | 10.9% | 56.0% | -10.6% | -39.5% | 1.148 |
| example | 2024-04 | x25 | w_R | 4.5% | -3.9% | 5.0% | 12.6% | 0.4% | -6.2% | -4.0% | 5.0% | 13.3% | 0.4% | -5.9% | 2.274 |
| example | 2024-04 | x25 | frontier | 8.1% | -9.0% | 6.9% | 20.1% | -1.3% | -12.0% | -8.6% | 6.9% | 21.4% | -0.9% | -11.8% | 1.670 |
| example | 2024-04 | x50 | w_R | 4.5% | -3.9% | 5.0% | 12.6% | 0.4% | -6.2% | -4.0% | 5.0% | 13.3% | 0.4% | -5.9% | 2.274 |
| example | 2024-04 | x50 | frontier | 12.1% | -14.8% | 8.6% | 29.0% | -3.4% | -19.4% | -15.3% | 8.3% | 30.2% | -3.7% | -19.7% | 1.424 |
| example | 2024-04 | x100 | w_R | 4.5% | -3.9% | 5.0% | 12.6% | 0.4% | -6.2% | -4.0% | 5.0% | 13.3% | 0.4% | -5.9% | 2.274 |
| example | 2024-04 | x100 | frontier | 20.3% | -27.9% | 9.8% | 47.5% | -9.1% | -34.8% | -29.4% | 9.6% | 49.2% | -9.8% | -35.8% | 1.163 |
| example | 2024-05 | x25 | w_R | 4.6% | -4.0% | 5.2% | 14.0% | 0.5% | -6.6% | -3.9% | 5.2% | 13.6% | 0.6% | -5.9% | 2.284 |
| example | 2024-05 | x25 | frontier | 8.4% | -8.9% | 7.8% | 22.5% | -0.8% | -13.1% | -8.7% | 7.8% | 22.5% | -0.6% | -12.3% | 1.636 |
| example | 2024-05 | x50 | w_R | 4.6% | -4.0% | 5.2% | 14.0% | 0.5% | -6.6% | -3.9% | 5.2% | 13.6% | 0.6% | -5.9% | 2.284 |
| example | 2024-05 | x50 | frontier | 12.8% | -15.9% | 9.4% | 32.1% | -3.5% | -21.6% | -15.3% | 9.6% | 32.5% | -3.1% | -20.5% | 1.334 |
| example | 2024-05 | x100 | w_R | 4.6% | -4.0% | 5.2% | 14.0% | 0.5% | -6.6% | -3.9% | 5.2% | 13.6% | 0.6% | -5.9% | 2.284 |
| example | 2024-05 | x100 | frontier | 21.6% | -30.5% | 10.5% | 54.2% | -9.7% | -38.9% | -30.4% | 11.1% | 55.6% | -9.4% | -37.8% | 1.149 |
| example | 2024-06 | x25 | w_R | 4.6% | -3.9% | 5.5% | 13.4% | 0.6% | -6.2% | -3.8% | 5.3% | 13.6% | 0.7% | -6.0% | 2.274 |
| example | 2024-06 | x25 | frontier | 8.1% | -8.8% | 7.9% | 21.6% | -0.7% | -11.7% | -8.0% | 7.7% | 21.4% | -0.3% | -11.5% | 1.630 |
| example | 2024-06 | x50 | w_R | 4.6% | -3.9% | 5.5% | 13.4% | 0.6% | -6.2% | -3.8% | 5.3% | 13.6% | 0.7% | -6.0% | 2.274 |
| example | 2024-06 | x50 | frontier | 12.1% | -15.2% | 9.9% | 31.1% | -3.1% | -19.6% | -14.3% | 9.4% | 31.3% | -2.6% | -19.3% | 1.341 |
| example | 2024-06 | x100 | w_R | 4.6% | -3.9% | 5.5% | 13.4% | 0.6% | -6.2% | -3.8% | 5.3% | 13.6% | 0.7% | -6.0% | 2.274 |
| example | 2024-06 | x100 | frontier | 20.2% | -29.9% | 12.2% | 49.4% | -9.3% | -36.8% | -27.3% | 11.5% | 49.9% | -8.0% | -35.2% | 1.166 |
| example | 2024-07 | x25 | w_R | 5.7% | -3.9% | 6.4% | 16.8% | 1.2% | -6.1% | -4.7% | 6.4% | 16.2% | 0.7% | -7.1% | 2.007 |
| example | 2024-07 | x25 | frontier | 8.4% | -7.8% | 7.8% | 23.5% | 0.0% | -11.1% | -8.8% | 7.8% | 22.3% | -0.7% | -12.6% | 1.649 |
| example | 2024-07 | x50 | w_R | 5.7% | -3.9% | 6.4% | 16.8% | 1.2% | -6.1% | -4.7% | 6.4% | 16.2% | 0.7% | -7.1% | 2.007 |
| example | 2024-07 | x50 | frontier | 12.8% | -14.7% | 9.3% | 33.3% | -2.7% | -19.2% | -15.5% | 9.5% | 32.0% | -3.3% | -21.2% | 1.337 |
| example | 2024-07 | x100 | w_R | 5.7% | -3.9% | 6.4% | 16.8% | 1.2% | -6.1% | -4.7% | 6.4% | 16.2% | 0.7% | -7.1% | 2.007 |
| example | 2024-07 | x100 | frontier | 21.6% | -28.9% | 10.2% | 56.5% | -8.6% | -36.1% | -30.6% | 11.0% | 54.5% | -9.6% | -38.5% | 1.153 |
| example | 2024-08 | x25 | w_R | 4.7% | -4.2% | 5.5% | 13.8% | 0.5% | -6.7% | -4.0% | 5.4% | 13.9% | 0.6% | -5.9% | 2.277 |
| example | 2024-08 | x25 | frontier | 8.4% | -9.0% | 8.1% | 22.7% | -0.7% | -13.4% | -8.9% | 7.8% | 22.7% | -0.7% | -12.2% | 1.578 |
| example | 2024-08 | x50 | w_R | 4.7% | -4.2% | 5.5% | 13.8% | 0.5% | -6.7% | -4.0% | 5.4% | 13.9% | 0.6% | -5.9% | 2.277 |
| example | 2024-08 | x50 | frontier | 12.8% | -15.3% | 9.8% | 32.9% | -2.9% | -22.5% | -15.8% | 9.8% | 32.9% | -3.2% | -20.8% | 1.377 |
| example | 2024-08 | x100 | w_R | 4.7% | -4.2% | 5.5% | 13.8% | 0.5% | -6.7% | -4.0% | 5.4% | 13.9% | 0.6% | -5.9% | 2.277 |
| example | 2024-08 | x100 | frontier | 21.6% | -30.7% | 11.9% | 55.7% | -9.3% | -39.4% | -31.0% | 11.7% | 56.1% | -9.5% | -38.0% | 1.157 |
| example | 2024-09 | x25 | w_R | 4.9% | -3.8% | 5.6% | 14.6% | 0.9% | -5.9% | -4.2% | 5.6% | 14.9% | 0.7% | -6.3% | 2.286 |
| example | 2024-09 | x25 | frontier | 8.4% | -8.1% | 8.1% | 22.4% | -0.2% | -11.1% | -8.2% | 7.9% | 22.9% | -0.3% | -12.0% | 1.624 |
| example | 2024-09 | x50 | w_R | 4.9% | -3.8% | 5.6% | 14.6% | 0.9% | -5.9% | -4.2% | 5.6% | 14.9% | 0.7% | -6.3% | 2.286 |
| example | 2024-09 | x50 | frontier | 12.9% | -14.6% | 10.2% | 32.4% | -2.4% | -18.7% | -14.9% | 9.9% | 33.3% | -2.6% | -20.6% | 1.368 |
| example | 2024-09 | x100 | w_R | 4.9% | -3.8% | 5.6% | 14.6% | 0.9% | -5.9% | -4.2% | 5.6% | 14.9% | 0.7% | -6.3% | 2.286 |
| example | 2024-09 | x100 | frontier | 21.7% | -28.7% | 12.8% | 56.2% | -7.7% | -35.5% | -30.2% | 12.1% | 56.0% | -8.9% | -37.7% | 1.162 |
| example | 2024-10 | x25 | w_R | 4.5% | -3.9% | 5.0% | 13.1% | 0.5% | -5.7% | -3.9% | 4.9% | 13.3% | 0.4% | -5.8% | 2.298 |
| example | 2024-10 | x25 | frontier | 8.5% | -9.1% | 7.6% | 21.9% | -1.0% | -12.4% | -9.0% | 7.3% | 22.0% | -1.0% | -12.6% | 1.604 |
| example | 2024-10 | x50 | w_R | 4.5% | -3.9% | 5.0% | 13.1% | 0.5% | -5.7% | -3.9% | 4.9% | 13.3% | 0.4% | -5.8% | 2.298 |
| example | 2024-10 | x50 | frontier | 12.9% | -15.8% | 9.4% | 32.3% | -3.4% | -20.9% | -16.1% | 9.2% | 31.8% | -3.7% | -21.4% | 1.363 |
| example | 2024-10 | x100 | w_R | 4.5% | -3.9% | 5.0% | 13.1% | 0.5% | -5.7% | -3.9% | 4.9% | 13.3% | 0.4% | -5.8% | 2.298 |
| example | 2024-10 | x100 | frontier | 21.7% | -30.4% | 11.2% | 54.4% | -9.5% | -38.1% | -31.2% | 10.6% | 54.9% | -10.1% | -38.9% | 1.163 |
| example | 2024-11 | x25 | w_R | 4.6% | -3.9% | 5.1% | 13.4% | 0.5% | -5.4% | -4.1% | 5.0% | 13.5% | 0.4% | -5.8% | 2.288 |
| example | 2024-11 | x25 | frontier | 8.5% | -8.2% | 7.5% | 21.5% | -0.5% | -11.6% | -9.2% | 7.4% | 22.0% | -1.1% | -12.3% | 1.590 |
| example | 2024-11 | x50 | w_R | 4.6% | -3.9% | 5.1% | 13.4% | 0.5% | -5.4% | -4.1% | 5.0% | 13.5% | 0.4% | -5.8% | 2.288 |
| example | 2024-11 | x50 | frontier | 12.9% | -14.6% | 9.3% | 31.4% | -2.8% | -19.9% | -16.2% | 9.1% | 32.3% | -3.8% | -20.9% | 1.339 |
| example | 2024-11 | x100 | w_R | 4.6% | -3.9% | 5.1% | 13.4% | 0.5% | -5.4% | -4.1% | 5.0% | 13.5% | 0.4% | -5.8% | 2.288 |
| example | 2024-11 | x100 | frontier | 21.7% | -30.7% | 11.4% | 53.9% | -9.6% | -37.6% | -31.5% | 11.1% | 55.1% | -10.1% | -38.4% | 1.164 |
| example | 2024-12 | x25 | w_R | 4.7% | -4.8% | 4.6% | 13.0% | -0.2% | -7.2% | -4.5% | 4.7% | 13.3% | 0.0% | -6.5% | 2.310 |
| example | 2024-12 | x25 | frontier | 8.5% | -10.0% | 6.5% | 21.3% | -1.9% | -13.2% | -9.4% | 6.9% | 21.4% | -1.4% | -12.8% | 1.589 |
| example | 2024-12 | x50 | w_R | 4.7% | -4.8% | 4.6% | 13.0% | -0.2% | -7.2% | -4.5% | 4.7% | 13.3% | 0.0% | -6.5% | 2.310 |
| example | 2024-12 | x50 | frontier | 12.9% | -17.1% | 7.7% | 31.0% | -4.9% | -21.7% | -16.7% | 8.3% | 31.3% | -4.4% | -21.5% | 1.273 |
| example | 2024-12 | x100 | w_R | 4.7% | -4.8% | 4.6% | 13.0% | -0.2% | -7.2% | -4.5% | 4.7% | 13.3% | 0.0% | -6.5% | 2.310 |
| example | 2024-12 | x100 | frontier | 21.8% | -32.4% | 8.6% | 52.8% | -11.6% | -38.9% | -32.7% | 9.2% | 53.3% | -11.5% | -39.6% | 1.165 |
| example | 2025-01 | x25 | w_R | 5.4% | -4.7% | 5.4% | 15.2% | 0.3% | -7.0% | -4.9% | 5.5% | 15.0% | 0.2% | -6.9% | 2.146 |
| example | 2025-01 | x25 | frontier | 8.5% | -8.7% | 7.4% | 22.1% | -0.8% | -12.8% | -8.6% | 7.3% | 21.7% | -0.8% | -11.9% | 1.588 |
| example | 2025-01 | x50 | w_R | 5.4% | -4.7% | 5.4% | 15.2% | 0.3% | -7.0% | -4.9% | 5.5% | 15.0% | 0.2% | -6.9% | 2.146 |
| example | 2025-01 | x50 | frontier | 12.9% | -16.3% | 9.3% | 31.0% | -3.9% | -21.6% | -15.6% | 9.0% | 31.7% | -3.5% | -20.5% | 1.324 |
| example | 2025-01 | x100 | w_R | 5.4% | -4.7% | 5.4% | 15.2% | 0.3% | -7.0% | -4.9% | 5.5% | 15.0% | 0.2% | -6.9% | 2.146 |
| example | 2025-01 | x100 | frontier | 21.8% | -33.1% | 11.2% | 54.1% | -11.1% | -39.1% | -30.9% | 10.6% | 54.9% | -9.9% | -38.0% | 1.166 |
| example | 2025-02 | x25 | w_R | 5.9% | -3.9% | 5.8% | 15.5% | 1.0% | -6.0% | -4.8% | 6.0% | 16.1% | 0.5% | -6.8% | 1.989 |
| example | 2025-02 | x25 | frontier | 8.1% | -6.3% | 7.0% | 20.5% | 0.4% | -9.2% | -7.2% | 7.3% | 21.3% | 0.0% | -10.3% | 1.635 |
| example | 2025-02 | x50 | w_R | 5.9% | -3.9% | 5.8% | 15.5% | 1.0% | -6.0% | -4.8% | 6.0% | 16.1% | 0.5% | -6.8% | 1.989 |
| example | 2025-02 | x50 | frontier | 12.2% | -11.6% | 8.7% | 29.6% | -1.4% | -16.2% | -12.7% | 8.9% | 30.4% | -1.9% | -17.3% | 1.390 |
| example | 2025-02 | x100 | w_R | 5.9% | -3.9% | 5.8% | 15.5% | 1.0% | -6.0% | -4.8% | 6.0% | 16.1% | 0.5% | -6.8% | 1.989 |
| example | 2025-02 | x100 | frontier | 20.3% | -25.1% | 10.5% | 48.3% | -7.1% | -31.4% | -25.9% | 11.2% | 50.3% | -7.1% | -32.6% | 1.185 |
| example | 2025-03 | x25 | w_R | 7.6% | -3.8% | 9.1% | 22.4% | 2.7% | -5.8% | -2.8% | 9.1% | 22.4% | 3.3% | -5.1% | 1.579 |
| example | 2025-03 | x25 | frontier | 7.6% | -4.5% | 9.4% | 22.8% | 2.4% | -6.5% | -3.3% | 9.2% | 22.9% | 3.1% | -5.7% | 1.640 |
| example | 2025-03 | x50 | w_R | 7.7% | -3.8% | 9.3% | 22.8% | 2.8% | -5.9% | -2.9% | 9.1% | 22.8% | 3.3% | -5.2% | 1.562 |
| example | 2025-03 | x50 | frontier | 11.8% | -8.1% | 12.4% | 33.7% | 2.2% | -11.5% | -6.9% | 11.9% | 34.2% | 2.9% | -10.3% | 1.352 |
| example | 2025-03 | x100 | w_R | 7.7% | -3.8% | 9.3% | 22.8% | 2.8% | -5.9% | -2.9% | 9.1% | 22.8% | 3.3% | -5.2% | 1.562 |
| example | 2025-03 | x100 | frontier | 20.0% | -18.5% | 15.3% | 57.8% | -0.7% | -23.7% | -17.8% | 14.2% | 58.8% | -0.5% | -22.8% | 1.073 |
| example | 2025-04 | x25 | w_R | 7.3% | -3.8% | 8.2% | 20.5% | 2.3% | -5.5% | -4.0% | 7.9% | 20.8% | 2.1% | -6.2% | 1.624 |
| example | 2025-04 | x25 | frontier | 7.3% | -3.8% | 8.2% | 20.5% | 2.3% | -5.5% | -4.0% | 7.9% | 20.8% | 2.1% | -6.2% | 1.624 |
| example | 2025-04 | x50 | w_R | 7.7% | -4.0% | 8.5% | 21.6% | 2.3% | -5.9% | -4.3% | 8.2% | 21.9% | 2.0% | -6.6% | 1.555 |
| example | 2025-04 | x50 | frontier | 11.1% | -7.9% | 10.5% | 30.3% | 1.4% | -10.4% | -8.3% | 10.0% | 30.3% | 1.0% | -11.4% | 1.366 |
| example | 2025-04 | x100 | w_R | 7.7% | -4.0% | 8.5% | 21.6% | 2.3% | -5.9% | -4.3% | 8.2% | 21.9% | 2.0% | -6.6% | 1.555 |
| example | 2025-04 | x100 | frontier | 18.7% | -17.1% | 12.4% | 52.1% | -1.3% | -21.4% | -17.9% | 11.9% | 51.7% | -2.0% | -22.7% | 1.190 |
| example | 2025-05 | x25 | w_R | 6.8% | -3.9% | 7.4% | 19.0% | 1.8% | -6.0% | -4.1% | 7.4% | 19.2% | 1.7% | -6.2% | 1.768 |
| example | 2025-05 | x25 | frontier | 7.0% | -4.1% | 7.6% | 19.5% | 1.7% | -6.0% | -4.1% | 7.5% | 19.7% | 1.8% | -6.2% | 1.680 |
| example | 2025-05 | x50 | w_R | 7.1% | -4.0% | 7.7% | 19.9% | 1.9% | -6.2% | -4.2% | 7.6% | 20.1% | 1.8% | -6.4% | 1.673 |
| example | 2025-05 | x50 | frontier | 10.4% | -7.5% | 9.6% | 28.0% | 1.1% | -10.3% | -8.0% | 9.4% | 28.3% | 0.9% | -10.9% | 1.399 |
| example | 2025-05 | x100 | w_R | 6.9% | -3.8% | 7.5% | 19.3% | 1.9% | -6.0% | -4.1% | 7.5% | 19.5% | 1.7% | -6.2% | 1.732 |
| example | 2025-05 | x100 | frontier | 17.3% | -16.2% | 11.7% | 46.4% | -1.6% | -20.0% | -16.4% | 11.6% | 46.5% | -1.7% | -21.0% | 1.212 |
| example | 2025-06 | x25 | w_R | 6.9% | -3.6% | 7.6% | 19.2% | 2.0% | -6.3% | -4.0% | 7.6% | 19.3% | 1.8% | -6.1% | 1.674 |
| example | 2025-06 | x25 | frontier | 6.9% | -3.7% | 7.6% | 19.1% | 2.0% | -6.2% | -4.0% | 7.6% | 19.4% | 1.8% | -6.0% | 1.675 |
| example | 2025-06 | x50 | w_R | 7.5% | -3.6% | 8.0% | 20.2% | 2.3% | -6.6% | -4.2% | 7.8% | 20.6% | 1.9% | -6.5% | 1.577 |
| example | 2025-06 | x50 | frontier | 10.2% | -6.4% | 9.6% | 27.3% | 1.8% | -10.4% | -7.4% | 9.3% | 27.4% | 1.1% | -10.5% | 1.408 |
| example | 2025-06 | x100 | w_R | 7.5% | -3.6% | 8.0% | 20.2% | 2.3% | -6.6% | -4.2% | 7.8% | 20.6% | 1.9% | -6.5% | 1.577 |
| example | 2025-06 | x100 | frontier | 16.9% | -15.1% | 11.1% | 44.7% | -1.3% | -20.5% | -15.8% | 11.3% | 45.0% | -1.6% | -20.3% | 1.217 |
| example | 2025-07 | x25 | w_R | 6.7% | -3.7% | 7.4% | 19.3% | 1.9% | -5.8% | -3.9% | 7.3% | 18.9% | 1.7% | -6.1% | 1.740 |
| example | 2025-07 | x25 | frontier | 7.1% | -4.1% | 7.8% | 20.2% | 1.9% | -6.3% | -4.3% | 7.5% | 19.9% | 1.7% | -6.6% | 1.642 |
| example | 2025-07 | x50 | w_R | 7.5% | -4.2% | 8.0% | 21.1% | 2.0% | -6.6% | -4.6% | 7.7% | 20.8% | 1.7% | -6.9% | 1.579 |
| example | 2025-07 | x50 | frontier | 10.7% | -8.1% | 9.8% | 29.6% | 1.0% | -11.6% | -8.4% | 9.5% | 29.1% | 0.7% | -11.9% | 1.386 |
| example | 2025-07 | x100 | w_R | 7.5% | -4.2% | 8.0% | 21.1% | 2.0% | -6.6% | -4.6% | 7.7% | 20.8% | 1.7% | -6.9% | 1.579 |
| example | 2025-07 | x100 | frontier | 17.9% | -17.3% | 11.4% | 50.6% | -1.9% | -22.0% | -18.3% | 11.0% | 48.1% | -2.8% | -23.2% | 1.197 |
| example | 2025-08 | x25 | w_R | 6.5% | -4.3% | 7.4% | 18.8% | 1.5% | -6.5% | -3.7% | 7.1% | 18.4% | 1.8% | -5.8% | 1.801 |
| example | 2025-08 | x25 | frontier | 6.9% | -4.8% | 7.6% | 19.7% | 1.4% | -6.8% | -3.9% | 7.4% | 19.2% | 1.8% | -6.1% | 1.697 |
| example | 2025-08 | x50 | w_R | 6.2% | -4.2% | 7.2% | 18.2% | 1.5% | -6.3% | -3.7% | 7.0% | 17.8% | 1.7% | -5.7% | 1.836 |
| example | 2025-08 | x50 | frontier | 10.2% | -8.6% | 9.5% | 28.3% | 0.5% | -11.7% | -7.5% | 9.1% | 27.0% | 0.9% | -10.6% | 1.413 |
| example | 2025-08 | x100 | w_R | 6.2% | -4.2% | 7.2% | 18.2% | 1.5% | -6.3% | -3.7% | 7.0% | 17.8% | 1.7% | -5.7% | 1.836 |
| example | 2025-08 | x100 | frontier | 16.7% | -16.9% | 11.7% | 46.1% | -2.0% | -21.5% | -15.9% | 10.9% | 44.3% | -1.9% | -20.5% | 1.219 |
| example | 2025-09 | x25 | w_R | 7.1% | -3.3% | 7.9% | 19.9% | 2.4% | -5.8% | -4.0% | 8.1% | 20.6% | 2.1% | -6.4% | 1.659 |
| example | 2025-09 | x25 | frontier | 7.1% | -3.5% | 7.9% | 20.1% | 2.3% | -5.8% | -4.0% | 8.2% | 20.7% | 2.1% | -6.4% | 1.635 |
| example | 2025-09 | x50 | w_R | 7.4% | -3.4% | 8.1% | 20.8% | 2.5% | -6.1% | -4.2% | 8.4% | 21.5% | 2.2% | -6.7% | 1.583 |
| example | 2025-09 | x50 | frontier | 10.7% | -7.4% | 10.0% | 29.5% | 1.5% | -10.6% | -8.2% | 10.5% | 30.3% | 1.3% | -11.7% | 1.385 |
| example | 2025-09 | x100 | w_R | 7.4% | -3.4% | 8.1% | 20.8% | 2.5% | -6.1% | -4.2% | 8.4% | 21.5% | 2.2% | -6.7% | 1.583 |
| example | 2025-09 | x100 | frontier | 17.8% | -16.7% | 11.8% | 48.8% | -1.6% | -20.7% | -17.5% | 12.6% | 51.5% | -1.6% | -22.6% | 1.196 |
| example | 2025-10 | x25 | w_R | 6.7% | -3.7% | 7.8% | 20.0% | 2.1% | -5.7% | -3.8% | 7.8% | 19.9% | 2.0% | -6.2% | 1.744 |
| example | 2025-10 | x25 | frontier | 6.7% | -3.8% | 7.8% | 20.0% | 2.1% | -5.7% | -3.8% | 7.8% | 19.9% | 2.1% | -6.2% | 1.741 |
| example | 2025-10 | x50 | w_R | 7.4% | -4.1% | 8.3% | 21.6% | 2.2% | -6.5% | -4.3% | 8.3% | 21.7% | 2.1% | -6.9% | 1.590 |
| example | 2025-10 | x50 | frontier | 9.8% | -7.6% | 9.8% | 27.2% | 1.1% | -10.2% | -7.2% | 9.8% | 28.0% | 1.4% | -10.5% | 1.432 |
| example | 2025-10 | x100 | w_R | 7.4% | -4.1% | 8.3% | 21.6% | 2.2% | -6.5% | -4.3% | 8.3% | 21.7% | 2.1% | -6.9% | 1.590 |
| example | 2025-10 | x100 | frontier | 16.0% | -14.7% | 12.2% | 44.0% | -0.8% | -19.4% | -14.9% | 12.3% | 45.3% | -0.7% | -19.4% | 1.228 |
| example | 2025-11 | x25 | w_R | 6.2% | -3.9% | 6.9% | 17.5% | 1.5% | -6.1% | -3.8% | 7.1% | 17.5% | 1.6% | -5.7% | 1.860 |
| example | 2025-11 | x25 | frontier | 6.7% | -4.4% | 7.3% | 18.3% | 1.4% | -6.4% | -3.9% | 7.4% | 18.4% | 1.7% | -5.9% | 1.743 |
| example | 2025-11 | x50 | w_R | 6.0% | -3.6% | 6.8% | 16.8% | 1.6% | -5.7% | -3.5% | 6.9% | 17.0% | 1.7% | -5.4% | 1.902 |
| example | 2025-11 | x50 | frontier | 9.7% | -7.7% | 8.8% | 26.4% | 0.7% | -10.7% | -7.2% | 9.1% | 25.5% | 0.9% | -10.3% | 1.436 |
| example | 2025-11 | x100 | w_R | 6.0% | -3.6% | 6.8% | 16.8% | 1.6% | -5.7% | -3.5% | 6.9% | 17.0% | 1.7% | -5.4% | 1.902 |
| example | 2025-11 | x100 | frontier | 15.8% | -15.7% | 10.3% | 40.2% | -2.3% | -19.5% | -14.9% | 11.3% | 39.9% | -1.5% | -19.4% | 1.229 |
| example | 2025-12 | x25 | w_R | 6.3% | -3.8% | 6.7% | 17.6% | 1.5% | -6.0% | -4.0% | 6.8% | 17.1% | 1.4% | -5.8% | 1.830 |
| example | 2025-12 | x25 | frontier | 6.6% | -4.0% | 6.9% | 18.3% | 1.5% | -6.3% | -4.2% | 7.0% | 17.8% | 1.4% | -6.1% | 1.747 |
| example | 2025-12 | x50 | w_R | 5.6% | -3.3% | 6.2% | 16.2% | 1.5% | -5.3% | -3.5% | 6.3% | 15.6% | 1.4% | -5.2% | 2.010 |
| example | 2025-12 | x50 | frontier | 9.7% | -7.5% | 8.4% | 26.0% | 0.6% | -10.7% | -7.6% | 8.6% | 24.6% | 0.5% | -10.4% | 1.437 |
| example | 2025-12 | x100 | w_R | 5.6% | -3.3% | 6.2% | 16.2% | 1.5% | -5.3% | -3.5% | 6.3% | 15.6% | 1.4% | -5.2% | 2.010 |
| example | 2025-12 | x100 | frontier | 15.8% | -15.6% | 10.1% | 39.6% | -2.4% | -20.0% | -15.4% | 10.2% | 38.0% | -2.4% | -19.5% | 1.230 |
| example | 2026-01 | x25 | w_R | 6.6% | -3.8% | 7.0% | 17.8% | 1.6% | -6.0% | -4.0% | 6.9% | 17.8% | 1.4% | -6.2% | 1.745 |
| example | 2026-01 | x25 | frontier | 6.6% | -3.9% | 6.9% | 17.8% | 1.5% | -5.9% | -4.0% | 7.0% | 18.0% | 1.5% | -6.1% | 1.745 |
| example | 2026-01 | x50 | w_R | 6.6% | -3.8% | 7.0% | 17.8% | 1.6% | -6.0% | -4.1% | 6.9% | 17.9% | 1.4% | -6.2% | 1.744 |
| example | 2026-01 | x50 | frontier | 9.7% | -7.0% | 8.4% | 24.6% | 0.8% | -10.0% | -7.5% | 8.4% | 24.7% | 0.5% | -10.3% | 1.438 |
| example | 2026-01 | x100 | w_R | 6.6% | -3.8% | 7.0% | 17.8% | 1.6% | -6.0% | -4.1% | 6.9% | 17.9% | 1.4% | -6.2% | 1.744 |
| example | 2026-01 | x100 | frontier | 15.8% | -14.5% | 10.1% | 38.8% | -1.8% | -18.7% | -14.7% | 9.9% | 37.9% | -2.1% | -19.3% | 1.230 |
| example | 2026-02 | x25 | w_R | 6.6% | -4.0% | 7.3% | 18.7% | 1.7% | -6.1% | -3.9% | 7.1% | 18.6% | 1.6% | -6.1% | 1.773 |
| example | 2026-02 | x25 | frontier | 6.6% | -4.1% | 7.3% | 18.8% | 1.6% | -6.1% | -3.9% | 7.2% | 18.7% | 1.7% | -6.1% | 1.751 |
| example | 2026-02 | x50 | w_R | 5.5% | -3.2% | 6.6% | 16.2% | 1.7% | -5.0% | -3.4% | 6.4% | 16.1% | 1.5% | -5.2% | 2.047 |
| example | 2026-02 | x50 | frontier | 9.7% | -7.5% | 8.8% | 25.5% | 0.7% | -10.6% | -7.3% | 8.7% | 25.8% | 0.8% | -10.3% | 1.451 |
| example | 2026-02 | x100 | w_R | 5.5% | -3.2% | 6.6% | 16.2% | 1.7% | -5.0% | -3.4% | 6.4% | 16.1% | 1.5% | -5.2% | 2.047 |
| example | 2026-02 | x100 | frontier | 15.8% | -15.0% | 10.8% | 38.9% | -1.9% | -19.6% | -14.8% | 10.2% | 39.0% | -1.9% | -19.1% | 1.232 |
| example | 2026-03 | x25 | w_R | 6.3% | -4.5% | 6.3% | 17.4% | 0.9% | -6.8% | -4.6% | 6.3% | 17.2% | 0.9% | -6.3% | 1.842 |
| example | 2026-03 | x25 | frontier | 6.7% | -4.8% | 6.6% | 18.1% | 0.9% | -7.1% | -4.7% | 6.6% | 18.0% | 0.9% | -6.6% | 1.745 |
| example | 2026-03 | x50 | w_R | 5.9% | -4.3% | 6.2% | 16.5% | 0.9% | -6.5% | -4.2% | 6.1% | 16.2% | 0.9% | -6.1% | 1.920 |
| example | 2026-03 | x50 | frontier | 9.7% | -8.5% | 7.8% | 24.5% | -0.3% | -11.6% | -8.3% | 7.8% | 24.8% | -0.2% | -11.1% | 1.437 |
| example | 2026-03 | x100 | w_R | 5.9% | -4.3% | 6.2% | 16.5% | 0.9% | -6.5% | -4.2% | 6.1% | 16.2% | 0.9% | -6.1% | 1.920 |
| example | 2026-03 | x100 | frontier | 15.8% | -16.2% | 9.2% | 38.2% | -3.2% | -21.1% | -16.1% | 8.9% | 38.0% | -3.2% | -20.3% | 1.229 |
| example | 2026-04 | x25 | w_R | 6.4% | -4.3% | 6.6% | 17.6% | 1.2% | -6.5% | -4.2% | 6.8% | 17.7% | 1.3% | -6.6% | 1.804 |
| example | 2026-04 | x25 | frontier | 6.4% | -4.3% | 6.7% | 17.5% | 1.2% | -6.5% | -4.2% | 6.8% | 17.8% | 1.3% | -6.6% | 1.797 |
| example | 2026-04 | x50 | w_R | 7.5% | -4.9% | 7.3% | 19.7% | 1.2% | -7.5% | -5.1% | 7.4% | 20.0% | 1.1% | -7.8% | 1.585 |
| example | 2026-04 | x50 | frontier | 9.3% | -7.6% | 7.9% | 23.2% | 0.2% | -10.5% | -7.6% | 8.1% | 24.1% | 0.3% | -10.8% | 1.464 |
| example | 2026-04 | x100 | w_R | 7.5% | -4.9% | 7.3% | 19.7% | 1.2% | -7.5% | -5.1% | 7.4% | 20.0% | 1.1% | -7.8% | 1.585 |
| example | 2026-04 | x100 | frontier | 14.9% | -14.3% | 9.3% | 36.5% | -2.1% | -19.2% | -14.8% | 9.8% | 37.4% | -2.2% | -19.7% | 1.245 |
| example | 2026-05 | x25 | w_R | 6.4% | -3.6% | 6.8% | 18.4% | 1.7% | -6.2% | -4.1% | 7.0% | 17.8% | 1.4% | -6.3% | 1.798 |
| example | 2026-05 | x25 | frontier | 6.4% | -3.6% | 6.8% | 18.4% | 1.7% | -6.2% | -4.1% | 7.0% | 17.8% | 1.5% | -6.3% | 1.794 |
| example | 2026-05 | x50 | w_R | 6.6% | -3.6% | 6.9% | 18.6% | 1.7% | -6.4% | -4.2% | 7.1% | 18.0% | 1.4% | -6.4% | 1.772 |
| example | 2026-05 | x50 | frontier | 9.3% | -6.9% | 8.3% | 24.9% | 0.8% | -10.3% | -7.2% | 8.5% | 24.2% | 0.6% | -10.2% | 1.463 |
| example | 2026-05 | x100 | w_R | 6.6% | -3.6% | 6.9% | 18.6% | 1.7% | -6.4% | -4.2% | 7.1% | 18.0% | 1.4% | -6.4% | 1.772 |
| example | 2026-05 | x100 | frontier | 14.9% | -15.0% | 10.2% | 38.4% | -2.1% | -19.1% | -14.8% | 10.3% | 37.6% | -2.0% | -19.1% | 1.245 |
| example | 2026-06 | x25 | w_R | 6.7% | -3.8% | 7.1% | 17.7% | 1.6% | -6.1% | -4.3% | 7.1% | 18.2% | 1.4% | -6.5% | 1.746 |
| example | 2026-06 | x25 | frontier | 6.7% | -3.8% | 7.1% | 17.7% | 1.6% | -6.1% | -4.3% | 7.1% | 18.2% | 1.4% | -6.5% | 1.746 |
| example | 2026-06 | x50 | w_R | 6.1% | -3.2% | 6.6% | 16.5% | 1.7% | -5.6% | -4.0% | 6.7% | 16.9% | 1.3% | -6.0% | 1.870 |
| example | 2026-06 | x50 | frontier | 9.7% | -7.2% | 8.6% | 24.4% | 0.7% | -10.6% | -7.7% | 8.5% | 25.1% | 0.5% | -10.9% | 1.438 |
| example | 2026-06 | x100 | w_R | 6.0% | -3.2% | 6.6% | 16.3% | 1.7% | -5.5% | -3.9% | 6.7% | 16.7% | 1.3% | -5.9% | 1.895 |
| example | 2026-06 | x100 | frontier | 15.8% | -15.2% | 10.2% | 37.6% | -2.3% | -20.2% | -15.5% | 10.0% | 38.5% | -2.5% | -20.2% | 1.231 |
| example | 2026-07 | x25 | w_R | 6.4% | -4.4% | 6.7% | 17.7% | 1.1% | -6.6% | -4.4% | 6.7% | 17.6% | 1.2% | -6.5% | 1.793 |
| example | 2026-07 | x25 | frontier | 6.7% | -4.7% | 6.8% | 17.8% | 1.0% | -6.7% | -4.5% | 6.8% | 18.3% | 1.2% | -6.5% | 1.754 |
| example | 2026-07 | x50 | w_R | 6.4% | -4.4% | 6.7% | 17.6% | 1.1% | -6.6% | -4.3% | 6.7% | 17.6% | 1.1% | -6.5% | 1.794 |
| example | 2026-07 | x50 | frontier | 9.7% | -8.0% | 8.2% | 24.8% | 0.1% | -11.2% | -7.7% | 8.3% | 25.1% | 0.4% | -10.8% | 1.452 |
| example | 2026-07 | x100 | w_R | 6.4% | -4.4% | 6.7% | 17.6% | 1.1% | -6.6% | -4.3% | 6.7% | 17.6% | 1.1% | -6.5% | 1.794 |
| example | 2026-07 | x100 | frontier | 15.7% | -15.9% | 10.0% | 38.3% | -2.7% | -20.6% | -15.3% | 9.8% | 38.6% | -2.3% | -20.0% | 1.237 |
| example | 2026-08 | x25 | w_R | 6.6% | -4.3% | 7.1% | 18.0% | 1.4% | -6.7% | -4.3% | 7.1% | 18.3% | 1.4% | -6.5% | 1.773 |
| example | 2026-08 | x25 | frontier | 6.7% | -4.3% | 7.2% | 18.2% | 1.4% | -6.8% | -4.3% | 7.1% | 18.5% | 1.4% | -6.6% | 1.756 |
| example | 2026-08 | x50 | w_R | 6.4% | -4.0% | 6.9% | 17.8% | 1.4% | -6.7% | -4.2% | 6.9% | 18.0% | 1.3% | -6.4% | 1.812 |
| example | 2026-08 | x50 | frontier | 9.7% | -7.9% | 8.5% | 25.3% | 0.4% | -11.4% | -7.6% | 8.5% | 25.5% | 0.6% | -10.7% | 1.452 |
| example | 2026-08 | x100 | w_R | 6.4% | -4.0% | 6.9% | 17.8% | 1.4% | -6.7% | -4.2% | 6.9% | 18.0% | 1.3% | -6.4% | 1.812 |
| example | 2026-08 | x100 | frontier | 15.7% | -16.4% | 10.1% | 39.0% | -2.9% | -21.3% | -15.0% | 10.2% | 39.6% | -2.0% | -19.7% | 1.238 |
| example | 2026-09 | x25 | w_R | 5.6% | -4.0% | 5.7% | 15.5% | 0.8% | -6.0% | -4.2% | 5.8% | 15.1% | 0.7% | -6.1% | 1.989 |
| example | 2026-09 | x25 | frontier | 6.5% | -5.0% | 6.4% | 17.8% | 0.7% | -6.9% | -4.8% | 6.6% | 17.5% | 0.9% | -7.0% | 1.783 |
| example | 2026-09 | x50 | w_R | 6.3% | -4.5% | 6.3% | 17.2% | 0.9% | -6.6% | -4.6% | 6.4% | 16.9% | 0.9% | -6.7% | 1.841 |
| example | 2026-09 | x50 | frontier | 9.4% | -8.3% | 7.8% | 24.2% | -0.2% | -11.0% | -8.0% | 8.0% | 24.0% | 0.0% | -10.9% | 1.465 |
| example | 2026-09 | x100 | w_R | 6.3% | -4.5% | 6.3% | 17.2% | 0.9% | -6.6% | -4.6% | 6.4% | 16.9% | 0.9% | -6.7% | 1.841 |
| example | 2026-09 | x100 | frontier | 15.0% | -15.9% | 9.4% | 38.0% | -2.9% | -20.1% | -15.4% | 9.6% | 37.4% | -2.6% | -19.7% | 1.249 |
| tsp | 2018-06 | x25 | w_R | 3.3% | -0.2% | 5.1% | 9.9% | 2.4% | -1.1% | -0.6% | 5.1% | 10.2% | 2.2% | -1.7% | 1.379 |
| tsp | 2018-06 | x25 | frontier | 4.2% | -1.1% | 5.8% | 12.3% | 2.3% | -2.3% | -1.6% | 5.8% | 12.7% | 2.0% | -3.1% | 1.654 |
| tsp | 2018-06 | x50 | w_R | 4.9% | -1.4% | 6.3% | 13.6% | 2.4% | -2.8% | -2.0% | 6.3% | 14.0% | 2.1% | -3.6% | 1.241 |
| tsp | 2018-06 | x50 | frontier | 7.2% | -3.7% | 8.2% | 19.8% | 2.2% | -5.6% | -4.4% | 8.2% | 20.5% | 1.9% | -6.8% | 1.499 |
| tsp | 2018-06 | x100 | w_R | 4.9% | -1.4% | 6.3% | 13.6% | 2.4% | -2.8% | -2.0% | 6.3% | 14.0% | 2.1% | -3.6% | 1.241 |
| tsp | 2018-06 | x100 | frontier | 13.2% | -9.9% | 12.6% | 35.6% | 1.4% | -13.8% | -10.7% | 12.3% | 36.5% | 0.9% | -15.3% | 1.051 |
| tsp | 2018-07 | x25 | w_R | 2.8% | 0.0% | 4.8% | 8.9% | 2.3% | -1.1% | 0.0% | 4.7% | 8.9% | 2.3% | -0.9% | 1.596 |
| tsp | 2018-07 | x25 | frontier | 4.1% | -1.4% | 5.8% | 12.3% | 2.1% | -2.8% | -1.2% | 5.9% | 12.4% | 2.3% | -2.5% | 1.760 |
| tsp | 2018-07 | x50 | w_R | 2.8% | 0.0% | 4.8% | 8.9% | 2.3% | -1.1% | 0.0% | 4.7% | 8.9% | 2.3% | -0.9% | 1.596 |
| tsp | 2018-07 | x50 | frontier | 7.1% | -3.9% | 8.4% | 19.7% | 2.2% | -6.5% | -3.8% | 8.3% | 19.8% | 2.2% | -6.0% | 1.471 |
| tsp | 2018-07 | x100 | w_R | 2.8% | 0.0% | 4.8% | 8.9% | 2.3% | -1.1% | 0.0% | 4.7% | 8.9% | 2.3% | -0.9% | 1.596 |
| tsp | 2018-07 | x100 | frontier | 13.1% | -11.5% | 12.4% | 36.8% | 0.5% | -16.1% | -10.8% | 12.1% | 36.1% | 0.7% | -15.2% | 1.052 |
| tsp | 2018-08 | x25 | w_R | 3.0% | -0.1% | 5.2% | 9.9% | 2.5% | -1.1% | 0.2% | 5.3% | 10.0% | 2.7% | -1.0% | 1.589 |
| tsp | 2018-08 | x25 | frontier | 4.1% | -1.4% | 6.2% | 13.0% | 2.3% | -2.6% | -0.9% | 6.3% | 13.1% | 2.7% | -2.4% | 1.968 |
| tsp | 2018-08 | x50 | w_R | 6.4% | -3.0% | 8.2% | 18.6% | 2.5% | -5.1% | -2.5% | 8.3% | 18.8% | 2.9% | -4.7% | 1.545 |
| tsp | 2018-08 | x50 | frontier | 7.1% | -3.8% | 8.8% | 20.7% | 2.4% | -6.0% | -3.1% | 9.0% | 20.8% | 2.9% | -5.6% | 1.474 |
| tsp | 2018-08 | x100 | w_R | 6.4% | -3.0% | 8.2% | 18.6% | 2.5% | -5.1% | -2.5% | 8.3% | 18.8% | 2.9% | -4.7% | 1.545 |
| tsp | 2018-08 | x100 | frontier | 13.1% | -10.5% | 12.8% | 36.5% | 1.2% | -15.0% | -10.1% | 13.2% | 37.5% | 1.7% | -14.4% | 1.053 |
| tsp | 2018-09 | x25 | w_R | 2.6% | 0.3% | 4.8% | 8.8% | 2.5% | -0.6% | 0.3% | 4.8% | 8.7% | 2.5% | -0.7% | 1.618 |
| tsp | 2018-09 | x25 | frontier | 4.0% | -1.1% | 6.0% | 12.5% | 2.4% | -2.3% | -0.9% | 6.0% | 12.3% | 2.5% | -2.5% | 1.875 |
| tsp | 2018-09 | x50 | w_R | 2.6% | 0.3% | 4.8% | 8.8% | 2.5% | -0.6% | 0.3% | 4.8% | 8.7% | 2.5% | -0.7% | 1.618 |
| tsp | 2018-09 | x50 | frontier | 6.9% | -3.5% | 8.4% | 19.9% | 2.4% | -5.7% | -3.4% | 8.5% | 19.3% | 2.4% | -5.9% | 1.500 |
| tsp | 2018-09 | x100 | w_R | 2.6% | 0.3% | 4.8% | 8.8% | 2.5% | -0.6% | 0.3% | 4.8% | 8.7% | 2.5% | -0.7% | 1.618 |
| tsp | 2018-09 | x100 | frontier | 12.7% | -9.8% | 12.0% | 34.7% | 1.2% | -13.9% | -10.1% | 12.3% | 34.3% | 1.1% | -14.3% | 1.056 |
| tsp | 2018-10 | x25 | w_R | 2.2% | 0.4% | 4.0% | 7.2% | 2.2% | -0.5% | 0.1% | 3.9% | 7.3% | 1.9% | -0.7% | 1.940 |
| tsp | 2018-10 | x25 | frontier | 4.0% | -1.5% | 5.3% | 11.5% | 1.9% | -3.1% | -1.9% | 5.2% | 11.5% | 1.5% | -3.4% | 1.640 |
| tsp | 2018-10 | x50 | w_R | 2.2% | 0.4% | 4.0% | 7.2% | 2.2% | -0.5% | 0.1% | 3.9% | 7.3% | 1.9% | -0.7% | 1.940 |
| tsp | 2018-10 | x50 | frontier | 7.0% | -4.5% | 7.2% | 18.1% | 1.3% | -7.2% | -5.2% | 6.9% | 18.2% | 0.8% | -7.6% | 1.496 |
| tsp | 2018-10 | x100 | w_R | 2.2% | 0.4% | 4.0% | 7.2% | 2.2% | -0.5% | 0.1% | 3.9% | 7.3% | 1.9% | -0.7% | 1.940 |
| tsp | 2018-10 | x100 | frontier | 12.9% | -12.0% | 9.8% | 32.4% | -1.0% | -16.8% | -12.9% | 9.5% | 32.9% | -1.6% | -17.1% | 1.055 |
| tsp | 2018-11 | x25 | w_R | 1.6% | 0.7% | 3.5% | 6.3% | 2.1% | 0.0% | 0.6% | 3.6% | 6.2% | 2.1% | -0.1% | 2.444 |
| tsp | 2018-11 | x25 | frontier | 4.1% | -1.9% | 5.0% | 11.6% | 1.5% | -3.5% | -2.1% | 5.1% | 11.7% | 1.5% | -3.6% | 1.715 |
| tsp | 2018-11 | x50 | w_R | 1.6% | 0.7% | 3.5% | 6.3% | 2.1% | 0.0% | 0.6% | 3.6% | 6.2% | 2.1% | -0.1% | 2.444 |
| tsp | 2018-11 | x50 | frontier | 7.1% | -5.0% | 6.6% | 18.2% | 0.8% | -7.8% | -5.4% | 6.9% | 18.6% | 0.7% | -7.9% | 1.487 |
| tsp | 2018-11 | x100 | w_R | 1.6% | 0.7% | 3.5% | 6.3% | 2.1% | 0.0% | 0.6% | 3.6% | 6.2% | 2.1% | -0.1% | 2.444 |
| tsp | 2018-11 | x100 | frontier | 13.1% | -12.7% | 9.0% | 33.0% | -1.6% | -17.0% | -13.1% | 9.6% | 32.8% | -1.7% | -17.5% | 1.055 |
| tsp | 2018-12 | x25 | w_R | 1.6% | 0.7% | 3.5% | 6.1% | 2.1% | 0.1% | 0.4% | 3.5% | 6.1% | 1.9% | -0.2% | 2.512 |
| tsp | 2018-12 | x25 | frontier | 4.2% | -2.3% | 4.9% | 11.7% | 1.3% | -3.9% | -3.0% | 4.8% | 11.8% | 0.8% | -4.5% | 2.139 |
| tsp | 2018-12 | x50 | w_R | 1.6% | 0.7% | 3.5% | 6.1% | 2.1% | 0.1% | 0.4% | 3.5% | 6.1% | 1.9% | -0.2% | 2.512 |
| tsp | 2018-12 | x50 | frontier | 7.3% | -6.2% | 6.3% | 18.2% | 0.0% | -8.6% | -6.9% | 6.1% | 18.2% | -0.5% | -9.4% | 1.477 |
| tsp | 2018-12 | x100 | w_R | 1.6% | 0.7% | 3.5% | 6.1% | 2.1% | 0.1% | 0.4% | 3.5% | 6.1% | 1.9% | -0.2% | 2.512 |
| tsp | 2018-12 | x100 | frontier | 13.6% | -15.9% | 8.0% | 33.2% | -3.8% | -20.0% | -16.6% | 7.7% | 32.5% | -4.4% | -20.9% | 1.052 |
| tsp | 2019-01 | x25 | w_R | 1.5% | 0.7% | 3.5% | 6.0% | 2.0% | 0.3% | 0.7% | 3.4% | 6.0% | 2.0% | 0.2% | 2.692 |
| tsp | 2019-01 | x25 | frontier | 4.2% | -2.8% | 4.9% | 12.5% | 1.0% | -4.0% | -2.7% | 5.0% | 12.3% | 1.1% | -4.1% | 2.170 |
| tsp | 2019-01 | x50 | w_R | 1.5% | 0.7% | 3.5% | 6.0% | 2.0% | 0.3% | 0.7% | 3.4% | 6.0% | 2.0% | 0.2% | 2.692 |
| tsp | 2019-01 | x50 | frontier | 7.4% | -6.5% | 6.3% | 18.3% | -0.2% | -8.7% | -6.0% | 6.6% | 18.6% | 0.3% | -8.5% | 1.476 |
| tsp | 2019-01 | x100 | w_R | 1.5% | 0.7% | 3.5% | 6.0% | 2.0% | 0.3% | 0.7% | 3.4% | 6.0% | 2.0% | 0.2% | 2.692 |
| tsp | 2019-01 | x100 | frontier | 13.7% | -16.1% | 8.4% | 32.9% | -3.8% | -19.8% | -15.1% | 8.7% | 33.6% | -3.1% | -19.2% | 1.051 |
| tsp | 2019-02 | x25 | w_R | 1.7% | 0.6% | 3.7% | 6.5% | 2.1% | 0.0% | 0.5% | 3.7% | 6.7% | 2.1% | -0.1% | 2.402 |
| tsp | 2019-02 | x25 | frontier | 4.2% | -2.3% | 5.3% | 12.2% | 1.4% | -3.7% | -2.6% | 5.2% | 12.7% | 1.3% | -4.2% | 1.996 |
| tsp | 2019-02 | x50 | w_R | 1.7% | 0.6% | 3.7% | 6.5% | 2.1% | 0.0% | 0.5% | 3.7% | 6.7% | 2.1% | -0.1% | 2.402 |
| tsp | 2019-02 | x50 | frontier | 7.3% | -5.8% | 7.0% | 19.2% | 0.5% | -8.2% | -6.1% | 7.0% | 19.7% | 0.4% | -8.9% | 1.478 |
| tsp | 2019-02 | x100 | w_R | 1.7% | 0.6% | 3.7% | 6.5% | 2.1% | 0.0% | 0.5% | 3.7% | 6.7% | 2.1% | -0.1% | 2.402 |
| tsp | 2019-02 | x100 | frontier | 13.6% | -15.1% | 10.0% | 35.4% | -2.5% | -19.4% | -15.0% | 9.7% | 36.1% | -2.5% | -19.9% | 1.052 |
| tsp | 2019-03 | x25 | w_R | 1.7% | 0.6% | 3.8% | 6.6% | 2.1% | -0.1% | 0.5% | 3.7% | 6.7% | 2.1% | -0.0% | 2.402 |
| tsp | 2019-03 | x25 | frontier | 4.2% | -2.6% | 5.4% | 12.7% | 1.3% | -4.0% | -2.6% | 5.3% | 12.8% | 1.3% | -4.0% | 2.137 |
| tsp | 2019-03 | x50 | w_R | 1.7% | 0.6% | 3.8% | 6.6% | 2.1% | -0.1% | 0.5% | 3.7% | 6.7% | 2.1% | -0.0% | 2.402 |
| tsp | 2019-03 | x50 | frontier | 7.4% | -5.8% | 7.3% | 19.6% | 0.6% | -8.2% | -6.0% | 7.0% | 19.6% | 0.5% | -8.3% | 1.477 |
| tsp | 2019-03 | x100 | w_R | 1.7% | 0.6% | 3.8% | 6.6% | 2.1% | -0.1% | 0.5% | 3.7% | 6.7% | 2.1% | -0.0% | 2.402 |
| tsp | 2019-03 | x100 | frontier | 13.7% | -14.7% | 9.9% | 36.6% | -2.2% | -18.7% | -14.7% | 9.3% | 34.8% | -2.6% | -18.9% | 1.052 |
| tsp | 2019-04 | x25 | w_R | 1.7% | 0.6% | 3.8% | 6.9% | 2.2% | -0.0% | 0.6% | 3.7% | 7.0% | 2.2% | -0.0% | 2.410 |
| tsp | 2019-04 | x25 | frontier | 4.2% | -2.2% | 5.6% | 13.4% | 1.7% | -3.7% | -2.2% | 5.4% | 13.3% | 1.6% | -3.8% | 2.005 |
| tsp | 2019-04 | x50 | w_R | 1.7% | 0.6% | 3.8% | 6.9% | 2.2% | -0.0% | 0.6% | 3.7% | 7.0% | 2.2% | -0.0% | 2.410 |
| tsp | 2019-04 | x50 | frontier | 7.3% | -5.1% | 7.6% | 20.8% | 1.3% | -7.8% | -5.5% | 7.5% | 21.1% | 1.1% | -8.0% | 1.478 |
| tsp | 2019-04 | x100 | w_R | 1.7% | 0.6% | 3.8% | 6.9% | 2.2% | -0.0% | 0.6% | 3.7% | 7.0% | 2.2% | -0.0% | 2.410 |
| tsp | 2019-04 | x100 | frontier | 13.6% | -13.0% | 10.6% | 37.8% | -0.8% | -17.6% | -13.8% | 10.5% | 37.6% | -1.4% | -18.3% | 1.052 |
| tsp | 2019-05 | x25 | w_R | 1.3% | 0.7% | 3.3% | 5.9% | 2.0% | 0.2% | 0.7% | 3.3% | 5.8% | 2.0% | 0.2% | 2.928 |
| tsp | 2019-05 | x25 | frontier | 4.2% | -3.0% | 4.9% | 12.7% | 1.0% | -4.5% | -2.9% | 5.0% | 12.5% | 1.0% | -4.4% | 2.171 |
| tsp | 2019-05 | x50 | w_R | 1.3% | 0.7% | 3.3% | 5.9% | 2.0% | 0.2% | 0.7% | 3.3% | 5.8% | 2.0% | 0.2% | 2.928 |
| tsp | 2019-05 | x50 | frontier | 7.4% | -6.5% | 6.4% | 19.8% | 0.0% | -9.4% | -6.4% | 6.5% | 19.2% | 0.0% | -9.0% | 1.478 |
| tsp | 2019-05 | x100 | w_R | 1.3% | 0.7% | 3.3% | 5.9% | 2.0% | 0.2% | 0.7% | 3.3% | 5.8% | 2.0% | 0.2% | 2.928 |
| tsp | 2019-05 | x100 | frontier | 13.7% | -15.6% | 8.9% | 35.7% | -3.1% | -20.6% | -15.5% | 8.7% | 34.5% | -3.3% | -20.0% | 1.051 |
| tsp | 2019-06 | x25 | w_R | 1.7% | 0.6% | 3.6% | 6.8% | 2.1% | -0.2% | 0.4% | 3.7% | 6.8% | 2.0% | -0.2% | 2.380 |
| tsp | 2019-06 | x25 | frontier | 4.2% | -2.5% | 5.0% | 12.8% | 1.3% | -4.3% | -2.9% | 5.3% | 13.1% | 1.1% | -4.3% | 2.162 |
| tsp | 2019-06 | x50 | w_R | 1.7% | 0.6% | 3.6% | 6.8% | 2.1% | -0.2% | 0.4% | 3.7% | 6.8% | 2.0% | -0.2% | 2.380 |
| tsp | 2019-06 | x50 | frontier | 7.4% | -5.9% | 6.6% | 19.2% | 0.3% | -8.9% | -6.3% | 7.0% | 19.9% | 0.3% | -8.9% | 1.476 |
| tsp | 2019-06 | x100 | w_R | 1.7% | 0.6% | 3.6% | 6.8% | 2.1% | -0.2% | 0.4% | 3.7% | 6.8% | 2.0% | -0.2% | 2.380 |
| tsp | 2019-06 | x100 | frontier | 13.7% | -15.0% | 8.8% | 34.2% | -2.9% | -19.9% | -15.0% | 9.5% | 35.3% | -2.6% | -19.8% | 1.051 |
| tsp | 2019-07 | x25 | w_R | 1.6% | 0.4% | 3.5% | 6.6% | 2.0% | -0.4% | 0.5% | 3.6% | 6.6% | 2.0% | -0.1% | 2.488 |
| tsp | 2019-07 | x25 | frontier | 4.2% | -3.0% | 5.0% | 13.1% | 1.0% | -4.8% | -2.6% | 5.2% | 13.2% | 1.3% | -4.2% | 2.159 |
| tsp | 2019-07 | x50 | w_R | 1.6% | 0.4% | 3.5% | 6.6% | 2.0% | -0.4% | 0.5% | 3.6% | 6.6% | 2.0% | -0.1% | 2.488 |
| tsp | 2019-07 | x50 | frontier | 7.4% | -6.1% | 6.5% | 19.4% | 0.2% | -9.4% | -6.1% | 6.9% | 20.1% | 0.5% | -8.7% | 1.475 |
| tsp | 2019-07 | x100 | w_R | 1.6% | 0.4% | 3.5% | 6.6% | 2.0% | -0.4% | 0.5% | 3.6% | 6.6% | 2.0% | -0.1% | 2.488 |
| tsp | 2019-07 | x100 | frontier | 13.7% | -15.3% | 9.0% | 34.5% | -3.0% | -20.4% | -14.9% | 9.5% | 36.0% | -2.5% | -19.5% | 1.051 |
| tsp | 2019-08 | x25 | w_R | 1.5% | 0.7% | 3.5% | 6.2% | 2.1% | 0.1% | 0.5% | 3.5% | 6.3% | 2.0% | -0.1% | 2.709 |
| tsp | 2019-08 | x25 | frontier | 4.3% | -2.8% | 5.4% | 12.8% | 1.2% | -4.1% | -2.8% | 5.2% | 13.2% | 1.2% | -4.5% | 2.184 |
| tsp | 2019-08 | x50 | w_R | 1.5% | 0.7% | 3.5% | 6.2% | 2.1% | 0.1% | 0.5% | 3.5% | 6.3% | 2.0% | -0.1% | 2.709 |
| tsp | 2019-08 | x50 | frontier | 7.5% | -6.6% | 7.2% | 19.7% | 0.2% | -8.6% | -6.3% | 7.0% | 20.0% | 0.3% | -9.0% | 1.481 |
| tsp | 2019-08 | x100 | w_R | 1.5% | 0.7% | 3.5% | 6.2% | 2.1% | 0.1% | 0.5% | 3.5% | 6.3% | 2.0% | -0.1% | 2.709 |
| tsp | 2019-08 | x100 | frontier | 14.0% | -15.6% | 9.7% | 34.3% | -3.0% | -19.3% | -15.5% | 9.2% | 35.2% | -3.0% | -20.0% | 1.050 |
| tsp | 2019-09 | x25 | w_R | 1.5% | 0.6% | 3.5% | 6.3% | 2.0% | -0.2% | 0.6% | 3.4% | 6.3% | 2.0% | 0.0% | 2.740 |
| tsp | 2019-09 | x25 | frontier | 4.3% | -3.1% | 5.3% | 13.6% | 1.1% | -4.6% | -2.7% | 5.2% | 13.3% | 1.3% | -4.2% | 2.200 |
| tsp | 2019-09 | x50 | w_R | 1.5% | 0.6% | 3.5% | 6.3% | 2.0% | -0.2% | 0.6% | 3.4% | 6.3% | 2.0% | 0.0% | 2.740 |
| tsp | 2019-09 | x50 | frontier | 7.5% | -6.3% | 7.1% | 20.9% | 0.5% | -8.6% | -6.3% | 7.0% | 20.1% | 0.3% | -8.7% | 1.487 |
| tsp | 2019-09 | x100 | w_R | 1.5% | 0.6% | 3.5% | 6.3% | 2.0% | -0.2% | 0.6% | 3.4% | 6.3% | 2.0% | 0.0% | 2.740 |
| tsp | 2019-09 | x100 | frontier | 14.0% | -14.7% | 9.7% | 37.5% | -2.2% | -18.8% | -15.6% | 9.3% | 35.7% | -3.0% | -19.5% | 1.050 |
| tsp | 2019-10 | x25 | w_R | 2.1% | 0.1% | 4.0% | 7.8% | 2.0% | -0.7% | 0.1% | 4.0% | 7.6% | 2.0% | -0.6% | 2.094 |
| tsp | 2019-10 | x25 | frontier | 4.3% | -2.9% | 5.6% | 14.1% | 1.3% | -4.3% | -2.6% | 5.7% | 13.9% | 1.6% | -4.1% | 2.196 |
| tsp | 2019-10 | x50 | w_R | 2.1% | 0.1% | 4.0% | 7.8% | 2.0% | -0.7% | 0.1% | 4.0% | 7.6% | 2.0% | -0.6% | 2.094 |
| tsp | 2019-10 | x50 | frontier | 7.5% | -6.1% | 7.9% | 22.2% | 0.9% | -8.5% | -5.9% | 8.0% | 21.8% | 1.0% | -8.5% | 1.486 |
| tsp | 2019-10 | x100 | w_R | 2.1% | 0.1% | 4.0% | 7.8% | 2.0% | -0.7% | 0.1% | 4.0% | 7.6% | 2.0% | -0.6% | 2.094 |
| tsp | 2019-10 | x100 | frontier | 13.9% | -14.5% | 11.3% | 39.5% | -1.4% | -18.9% | -14.2% | 11.4% | 39.1% | -1.2% | -18.9% | 1.049 |
| tsp | 2019-11 | x25 | w_R | 2.0% | 0.3% | 3.8% | 7.4% | 2.0% | -0.5% | 0.1% | 3.8% | 7.2% | 1.9% | -0.7% | 2.161 |
| tsp | 2019-11 | x25 | frontier | 4.3% | -2.3% | 5.4% | 13.6% | 1.6% | -4.0% | -2.6% | 5.4% | 13.2% | 1.4% | -4.3% | 2.203 |
| tsp | 2019-11 | x50 | w_R | 2.0% | 0.3% | 3.8% | 7.4% | 2.0% | -0.5% | 0.1% | 3.8% | 7.2% | 1.9% | -0.7% | 2.161 |
| tsp | 2019-11 | x50 | frontier | 7.5% | -5.6% | 7.3% | 21.3% | 0.9% | -8.0% | -5.7% | 7.4% | 20.3% | 0.8% | -8.5% | 1.490 |
| tsp | 2019-11 | x100 | w_R | 2.0% | 0.3% | 3.8% | 7.4% | 2.0% | -0.5% | 0.1% | 3.8% | 7.2% | 1.9% | -0.7% | 2.161 |
| tsp | 2019-11 | x100 | frontier | 13.9% | -14.1% | 10.1% | 37.7% | -1.7% | -18.6% | -14.1% | 10.4% | 36.2% | -1.7% | -18.9% | 1.050 |
| tsp | 2019-12 | x25 | w_R | 1.8% | 0.5% | 3.8% | 6.9% | 2.1% | -0.4% | 0.3% | 3.8% | 7.0% | 2.0% | -0.4% | 2.339 |
| tsp | 2019-12 | x25 | frontier | 4.3% | -2.1% | 5.7% | 13.4% | 1.8% | -4.1% | -2.5% | 5.8% | 13.6% | 1.6% | -4.1% | 2.128 |
| tsp | 2019-12 | x50 | w_R | 1.8% | 0.5% | 3.8% | 6.9% | 2.1% | -0.4% | 0.3% | 3.8% | 7.0% | 2.0% | -0.4% | 2.339 |
| tsp | 2019-12 | x50 | frontier | 7.5% | -4.9% | 8.1% | 21.2% | 1.6% | -8.3% | -5.5% | 8.1% | 21.5% | 1.3% | -8.3% | 1.494 |
| tsp | 2019-12 | x100 | w_R | 1.8% | 0.5% | 3.8% | 6.9% | 2.1% | -0.4% | 0.3% | 3.8% | 7.0% | 2.0% | -0.4% | 2.339 |
| tsp | 2019-12 | x100 | frontier | 13.8% | -13.3% | 11.1% | 38.7% | -0.8% | -18.3% | -13.7% | 11.8% | 39.2% | -0.8% | -18.7% | 1.049 |
| tsp | 2020-01 | x25 | w_R | 2.2% | -0.1% | 4.1% | 7.9% | 2.0% | -1.2% | -0.2% | 4.0% | 7.9% | 1.9% | -1.0% | 1.964 |
| tsp | 2020-01 | x25 | frontier | 4.3% | -2.6% | 5.7% | 13.7% | 1.5% | -4.5% | -2.6% | 5.7% | 13.7% | 1.5% | -4.2% | 2.142 |
| tsp | 2020-01 | x50 | w_R | 2.2% | -0.1% | 4.1% | 7.9% | 2.0% | -1.2% | -0.2% | 4.0% | 7.9% | 1.9% | -1.0% | 1.964 |
| tsp | 2020-01 | x50 | frontier | 7.4% | -6.0% | 8.0% | 21.6% | 1.0% | -9.0% | -5.8% | 8.1% | 21.3% | 1.0% | -8.4% | 1.495 |
| tsp | 2020-01 | x100 | w_R | 2.2% | -0.1% | 4.1% | 7.9% | 2.0% | -1.2% | -0.2% | 4.0% | 7.9% | 1.9% | -1.0% | 1.964 |
| tsp | 2020-01 | x100 | frontier | 13.7% | -14.9% | 11.8% | 39.0% | -1.5% | -19.4% | -14.7% | 11.8% | 38.5% | -1.5% | -18.8% | 1.050 |
| tsp | 2020-02 | x25 | w_R | 1.5% | 0.3% | 3.2% | 6.3% | 1.8% | -0.4% | 0.1% | 3.2% | 6.1% | 1.6% | -0.5% | 2.663 |
| tsp | 2020-02 | x25 | frontier | 4.3% | -3.5% | 5.0% | 13.6% | 0.8% | -5.1% | -3.6% | 4.9% | 13.1% | 0.6% | -5.3% | 2.194 |
| tsp | 2020-02 | x50 | w_R | 1.5% | 0.3% | 3.2% | 6.3% | 1.8% | -0.4% | 0.1% | 3.2% | 6.1% | 1.6% | -0.5% | 2.663 |
| tsp | 2020-02 | x50 | frontier | 7.5% | -7.4% | 6.7% | 21.3% | -0.3% | -10.5% | -7.9% | 6.4% | 20.5% | -0.8% | -10.8% | 1.490 |
| tsp | 2020-02 | x100 | w_R | 1.5% | 0.3% | 3.2% | 6.3% | 1.8% | -0.4% | 0.1% | 3.2% | 6.1% | 1.6% | -0.5% | 2.663 |
| tsp | 2020-02 | x100 | frontier | 13.9% | -16.7% | 8.9% | 37.9% | -3.6% | -21.4% | -18.2% | 8.5% | 36.6% | -4.7% | -22.7% | 1.049 |
| tsp | 2020-03 | x25 | w_R | 1.3% | -0.1% | 2.6% | 5.0% | 1.2% | -0.7% | -0.3% | 2.5% | 5.0% | 1.1% | -0.8% | 1.929 |
| tsp | 2020-03 | x25 | frontier | 5.6% | -7.1% | 4.3% | 13.4% | -1.6% | -9.9% | -7.8% | 4.4% | 13.1% | -2.0% | -10.7% | 1.969 |
| tsp | 2020-03 | x50 | w_R | 1.3% | -0.1% | 2.6% | 5.0% | 1.2% | -0.7% | -0.3% | 2.5% | 5.0% | 1.1% | -0.8% | 1.929 |
| tsp | 2020-03 | x50 | frontier | 9.9% | -13.5% | 5.5% | 20.1% | -4.4% | -18.2% | -15.0% | 5.8% | 20.2% | -5.2% | -19.5% | 1.409 |
| tsp | 2020-03 | x100 | w_R | 1.3% | -0.1% | 2.6% | 5.0% | 1.2% | -0.7% | -0.3% | 2.5% | 5.0% | 1.1% | -0.8% | 1.929 |
| tsp | 2020-03 | x100 | frontier | 18.4% | -30.2% | 6.5% | 36.3% | -12.5% | -37.7% | -32.5% | 7.2% | 37.2% | -13.6% | -39.6% | 1.059 |
| tsp | 2020-04 | x25 | w_R | 1.4% | -0.4% | 2.7% | 5.3% | 1.1% | -1.0% | -0.3% | 2.7% | 5.5% | 1.2% | -1.1% | 2.682 |
| tsp | 2020-04 | x25 | frontier | 5.8% | -6.5% | 4.7% | 14.5% | -1.1% | -9.2% | -6.8% | 4.9% | 14.9% | -1.1% | -9.9% | 1.939 |
| tsp | 2020-04 | x50 | w_R | 1.4% | -0.4% | 2.7% | 5.3% | 1.1% | -1.0% | -0.3% | 2.7% | 5.5% | 1.2% | -1.1% | 2.682 |
| tsp | 2020-04 | x50 | frontier | 10.3% | -12.9% | 6.4% | 23.3% | -3.5% | -17.3% | -13.3% | 6.6% | 23.4% | -3.7% | -17.8% | 1.390 |
| tsp | 2020-04 | x100 | w_R | 1.4% | -0.4% | 2.7% | 5.3% | 1.1% | -1.0% | -0.3% | 2.7% | 5.5% | 1.2% | -1.1% | 2.682 |
| tsp | 2020-04 | x100 | frontier | 19.3% | -29.2% | 8.6% | 43.6% | -10.6% | -36.1% | -29.9% | 8.5% | 42.5% | -11.1% | -36.7% | 1.056 |
| tsp | 2020-05 | x25 | w_R | 1.6% | -0.4% | 2.8% | 6.0% | 1.2% | -1.5% | -0.5% | 2.9% | 6.0% | 1.2% | -1.3% | 2.703 |
| tsp | 2020-05 | x25 | frontier | 5.9% | -6.1% | 4.9% | 16.1% | -0.6% | -9.3% | -6.7% | 5.2% | 15.9% | -0.8% | -9.3% | 1.932 |
| tsp | 2020-05 | x50 | w_R | 1.6% | -0.4% | 2.8% | 6.0% | 1.2% | -1.5% | -0.5% | 2.9% | 6.0% | 1.2% | -1.3% | 2.703 |
| tsp | 2020-05 | x50 | frontier | 10.4% | -12.2% | 6.7% | 25.4% | -2.7% | -16.6% | -12.8% | 7.2% | 25.1% | -3.0% | -17.3% | 1.384 |
| tsp | 2020-05 | x100 | w_R | 1.6% | -0.4% | 2.8% | 6.0% | 1.2% | -1.5% | -0.5% | 2.9% | 6.0% | 1.2% | -1.3% | 2.703 |
| tsp | 2020-05 | x100 | frontier | 19.5% | -28.0% | 9.2% | 47.6% | -9.3% | -34.7% | -28.5% | 10.1% | 46.9% | -9.4% | -35.9% | 1.055 |
| tsp | 2020-06 | x25 | w_R | 1.6% | -0.4% | 3.0% | 6.1% | 1.2% | -1.3% | -0.5% | 2.9% | 6.1% | 1.2% | -1.3% | 2.673 |
| tsp | 2020-06 | x25 | frontier | 6.0% | -6.4% | 5.5% | 17.2% | -0.5% | -9.1% | -6.4% | 5.4% | 16.2% | -0.6% | -9.2% | 1.911 |
| tsp | 2020-06 | x50 | w_R | 1.6% | -0.4% | 3.0% | 6.1% | 1.2% | -1.3% | -0.5% | 2.9% | 6.1% | 1.2% | -1.3% | 2.673 |
| tsp | 2020-06 | x50 | frontier | 10.6% | -13.4% | 7.7% | 27.3% | -3.0% | -17.2% | -12.7% | 7.4% | 26.0% | -2.8% | -17.0% | 1.374 |
| tsp | 2020-06 | x100 | w_R | 1.6% | -0.4% | 3.0% | 6.1% | 1.2% | -1.3% | -0.5% | 2.9% | 6.1% | 1.2% | -1.3% | 2.673 |
| tsp | 2020-06 | x100 | frontier | 19.9% | -29.7% | 10.9% | 53.1% | -9.3% | -36.1% | -28.9% | 10.0% | 49.3% | -9.4% | -35.7% | 1.054 |
| tsp | 2020-07 | x25 | w_R | 1.5% | -0.2% | 2.9% | 5.7% | 1.3% | -1.1% | -0.4% | 2.9% | 6.0% | 1.2% | -1.2% | 2.707 |
| tsp | 2020-07 | x25 | frontier | 6.0% | -5.7% | 5.8% | 15.4% | -0.2% | -8.4% | -6.3% | 5.6% | 17.0% | -0.4% | -8.9% | 1.895 |
| tsp | 2020-07 | x50 | w_R | 1.5% | -0.2% | 2.9% | 5.7% | 1.3% | -1.1% | -0.4% | 2.9% | 6.0% | 1.2% | -1.2% | 2.707 |
| tsp | 2020-07 | x50 | frontier | 10.6% | -11.6% | 8.3% | 24.9% | -2.0% | -15.6% | -12.3% | 7.9% | 26.9% | -2.3% | -16.5% | 1.367 |
| tsp | 2020-07 | x100 | w_R | 1.5% | -0.2% | 2.9% | 5.7% | 1.3% | -1.1% | -0.4% | 2.9% | 6.0% | 1.2% | -1.2% | 2.707 |
| tsp | 2020-07 | x100 | frontier | 20.0% | -27.5% | 12.1% | 48.9% | -8.0% | -33.3% | -27.7% | 11.1% | 50.8% | -8.2% | -34.9% | 1.055 |
| tsp | 2020-08 | x25 | w_R | 1.7% | -0.9% | 3.0% | 6.2% | 1.0% | -1.8% | -0.5% | 3.0% | 6.2% | 1.2% | -1.5% | 2.624 |
| tsp | 2020-08 | x25 | frontier | 6.0% | -7.1% | 6.3% | 17.3% | -0.6% | -9.9% | -6.0% | 6.2% | 17.2% | -0.0% | -9.1% | 1.889 |
| tsp | 2020-08 | x50 | w_R | 1.7% | -0.9% | 3.0% | 6.2% | 1.0% | -1.8% | -0.5% | 3.0% | 6.2% | 1.2% | -1.5% | 2.624 |
| tsp | 2020-08 | x50 | frontier | 10.6% | -12.7% | 9.1% | 28.0% | -2.1% | -18.1% | -11.8% | 9.0% | 27.8% | -1.6% | -16.7% | 1.365 |
| tsp | 2020-08 | x100 | w_R | 1.7% | -0.9% | 3.0% | 6.2% | 1.0% | -1.8% | -0.5% | 3.0% | 6.2% | 1.2% | -1.5% | 2.624 |
| tsp | 2020-08 | x100 | frontier | 20.0% | -28.5% | 13.9% | 54.0% | -7.5% | -37.4% | -27.1% | 13.7% | 54.6% | -6.7% | -34.8% | 1.055 |
| tsp | 2020-09 | x25 | w_R | 1.7% | -0.2% | 3.0% | 6.2% | 1.4% | -1.2% | -0.5% | 3.0% | 6.1% | 1.2% | -1.5% | 2.605 |
| tsp | 2020-09 | x25 | frontier | 5.9% | -4.8% | 6.3% | 17.7% | 0.8% | -7.6% | -5.8% | 6.2% | 17.0% | 0.1% | -8.6% | 1.883 |
| tsp | 2020-09 | x50 | w_R | 1.7% | -0.2% | 3.0% | 6.2% | 1.4% | -1.2% | -0.5% | 3.0% | 6.1% | 1.2% | -1.5% | 2.605 |
| tsp | 2020-09 | x50 | frontier | 10.6% | -10.1% | 9.2% | 28.2% | -0.5% | -14.3% | -11.4% | 9.0% | 27.7% | -1.3% | -16.0% | 1.362 |
| tsp | 2020-09 | x100 | w_R | 1.7% | -0.2% | 3.0% | 6.2% | 1.4% | -1.2% | -0.5% | 3.0% | 6.1% | 1.2% | -1.5% | 2.605 |
| tsp | 2020-09 | x100 | frontier | 19.9% | -24.7% | 13.7% | 56.9% | -5.0% | -31.9% | -26.6% | 13.5% | 54.4% | -6.5% | -34.0% | 1.056 |
| tsp | 2020-10 | x25 | w_R | 1.4% | -0.4% | 2.6% | 5.6% | 1.1% | -1.2% | -0.6% | 2.6% | 5.4% | 0.9% | -1.4% | 2.659 |
| tsp | 2020-10 | x25 | frontier | 6.1% | -5.8% | 5.9% | 17.5% | 0.1% | -8.5% | -6.5% | 5.8% | 17.0% | -0.4% | -9.6% | 1.851 |
| tsp | 2020-10 | x50 | w_R | 1.4% | -0.4% | 2.6% | 5.6% | 1.1% | -1.2% | -0.6% | 2.6% | 5.4% | 0.9% | -1.4% | 2.659 |
| tsp | 2020-10 | x50 | frontier | 10.9% | -11.0% | 8.7% | 27.9% | -1.2% | -16.1% | -12.7% | 8.7% | 27.7% | -2.3% | -17.4% | 1.336 |
| tsp | 2020-10 | x100 | w_R | 1.4% | -0.4% | 2.6% | 5.6% | 1.1% | -1.2% | -0.6% | 2.6% | 5.4% | 0.9% | -1.4% | 2.659 |
| tsp | 2020-10 | x100 | frontier | 20.5% | -29.0% | 13.0% | 56.8% | -7.8% | -35.3% | -29.7% | 13.3% | 55.9% | -8.3% | -37.3% | 1.053 |
| tsp | 2020-11 | x25 | w_R | 2.4% | -1.2% | 3.8% | 7.9% | 1.2% | -2.6% | -1.2% | 3.7% | 8.1% | 1.2% | -2.4% | 2.015 |
| tsp | 2020-11 | x25 | frontier | 6.1% | -6.4% | 7.0% | 18.7% | 0.2% | -9.5% | -6.1% | 6.9% | 19.0% | 0.3% | -9.1% | 1.905 |
| tsp | 2020-11 | x50 | w_R | 2.4% | -1.2% | 3.8% | 7.9% | 1.2% | -2.6% | -1.2% | 3.7% | 8.1% | 1.2% | -2.4% | 2.015 |
| tsp | 2020-11 | x50 | frontier | 10.9% | -13.3% | 10.7% | 30.6% | -1.7% | -17.7% | -12.1% | 10.5% | 32.0% | -0.9% | -17.3% | 1.399 |
| tsp | 2020-11 | x100 | w_R | 2.4% | -1.2% | 3.8% | 7.9% | 1.2% | -2.6% | -1.2% | 3.7% | 8.1% | 1.2% | -2.4% | 2.015 |
| tsp | 2020-11 | x100 | frontier | 20.5% | -28.4% | 17.6% | 63.4% | -5.4% | -35.9% | -27.4% | 16.7% | 62.8% | -5.1% | -35.0% | 1.053 |
| tsp | 2020-12 | x25 | w_R | 1.8% | -0.6% | 3.2% | 6.7% | 1.3% | -1.5% | -0.6% | 3.3% | 6.7% | 1.3% | -1.6% | 2.508 |
| tsp | 2020-12 | x25 | frontier | 6.1% | -6.5% | 7.1% | 19.1% | 0.1% | -9.4% | -6.0% | 7.4% | 19.1% | 0.5% | -9.2% | 1.923 |
| tsp | 2020-12 | x50 | w_R | 1.8% | -0.6% | 3.2% | 6.7% | 1.3% | -1.5% | -0.6% | 3.3% | 6.7% | 1.3% | -1.6% | 2.508 |
| tsp | 2020-12 | x50 | frontier | 10.9% | -13.7% | 10.9% | 31.8% | -1.8% | -17.7% | -12.3% | 11.4% | 32.8% | -0.7% | -17.5% | 1.418 |
| tsp | 2020-12 | x100 | w_R | 1.8% | -0.6% | 3.2% | 6.7% | 1.3% | -1.5% | -0.6% | 3.3% | 6.7% | 1.3% | -1.6% | 2.508 |
| tsp | 2020-12 | x100 | frontier | 20.5% | -28.5% | 18.1% | 62.6% | -5.4% | -34.2% | -26.2% | 18.6% | 63.3% | -3.8% | -34.1% | 1.055 |
| tsp | 2021-01 | x25 | w_R | 2.7% | -1.3% | 4.1% | 8.4% | 1.3% | -3.0% | -1.3% | 4.1% | 8.6% | 1.3% | -2.6% | 1.895 |
| tsp | 2021-01 | x25 | frontier | 6.1% | -6.0% | 7.7% | 19.1% | 0.6% | -10.3% | -6.0% | 7.8% | 19.5% | 0.7% | -9.1% | 1.922 |
| tsp | 2021-01 | x50 | w_R | 2.7% | -1.3% | 4.1% | 8.4% | 1.3% | -3.0% | -1.3% | 4.1% | 8.6% | 1.3% | -2.6% | 1.895 |
| tsp | 2021-01 | x50 | frontier | 10.9% | -12.7% | 12.4% | 32.5% | -0.7% | -18.7% | -12.1% | 12.3% | 33.8% | -0.2% | -17.1% | 1.425 |
| tsp | 2021-01 | x100 | w_R | 2.7% | -1.3% | 4.1% | 8.4% | 1.3% | -3.0% | -1.3% | 4.1% | 8.6% | 1.3% | -2.6% | 1.895 |
| tsp | 2021-01 | x100 | frontier | 20.4% | -25.0% | 21.0% | 62.2% | -2.5% | -34.3% | -24.4% | 20.8% | 65.9% | -1.8% | -32.2% | 1.056 |
| tsp | 2021-02 | x25 | w_R | 5.3% | -3.2% | 6.9% | 16.4% | 1.8% | -5.6% | -4.0% | 7.0% | 16.6% | 1.4% | -6.6% | 1.852 |
| tsp | 2021-02 | x25 | frontier | 6.1% | -5.1% | 8.0% | 20.9% | 1.4% | -7.9% | -6.1% | 8.1% | 20.5% | 0.8% | -9.4% | 1.916 |
| tsp | 2021-02 | x50 | w_R | 8.6% | -6.2% | 10.2% | 25.0% | 1.9% | -9.5% | -7.0% | 10.2% | 25.2% | 1.4% | -10.9% | 1.406 |
| tsp | 2021-02 | x50 | frontier | 10.8% | -10.9% | 13.1% | 36.5% | 1.1% | -15.3% | -12.1% | 13.2% | 36.1% | 0.3% | -17.3% | 1.427 |
| tsp | 2021-02 | x100 | w_R | 8.6% | -6.2% | 10.2% | 25.0% | 1.9% | -9.5% | -7.0% | 10.2% | 25.2% | 1.4% | -10.9% | 1.406 |
| tsp | 2021-02 | x100 | frontier | 20.4% | -23.4% | 22.8% | 70.6% | -0.1% | -29.8% | -24.3% | 22.7% | 70.3% | -0.7% | -32.2% | 1.057 |
| tsp | 2021-03 | x25 | w_R | 3.2% | -1.7% | 4.5% | 9.8% | 1.3% | -3.6% | -2.0% | 4.6% | 9.6% | 1.1% | -3.5% | 1.656 |
| tsp | 2021-03 | x25 | frontier | 6.1% | -5.7% | 7.4% | 19.0% | 0.7% | -9.6% | -6.2% | 7.5% | 19.3% | 0.5% | -9.3% | 1.909 |
| tsp | 2021-03 | x50 | w_R | 3.2% | -1.7% | 4.5% | 9.8% | 1.3% | -3.6% | -2.0% | 4.6% | 9.6% | 1.1% | -3.5% | 1.656 |
| tsp | 2021-03 | x50 | frontier | 10.9% | -12.0% | 12.1% | 33.0% | -0.3% | -17.9% | -12.2% | 12.1% | 33.4% | -0.3% | -17.3% | 1.420 |
| tsp | 2021-03 | x100 | w_R | 3.2% | -1.7% | 4.5% | 9.8% | 1.3% | -3.6% | -2.0% | 4.6% | 9.6% | 1.1% | -3.5% | 1.656 |
| tsp | 2021-03 | x100 | frontier | 20.4% | -24.7% | 21.1% | 64.9% | -2.0% | -33.9% | -25.3% | 20.7% | 66.3% | -2.4% | -33.3% | 1.059 |
| tsp | 2021-04 | x25 | w_R | 4.7% | -2.7% | 6.0% | 12.9% | 1.5% | -4.8% | -3.1% | 5.9% | 13.1% | 1.2% | -5.3% | 1.309 |
| tsp | 2021-04 | x25 | frontier | 6.1% | -5.6% | 7.6% | 18.9% | 0.8% | -8.9% | -5.8% | 7.4% | 19.2% | 0.7% | -9.0% | 1.884 |
| tsp | 2021-04 | x50 | w_R | 4.7% | -2.7% | 6.0% | 12.9% | 1.5% | -4.8% | -3.1% | 5.9% | 13.1% | 1.2% | -5.3% | 1.309 |
| tsp | 2021-04 | x50 | frontier | 10.9% | -11.2% | 12.3% | 33.0% | 0.3% | -16.0% | -11.8% | 12.1% | 33.1% | -0.1% | -16.6% | 1.414 |
| tsp | 2021-04 | x100 | w_R | 4.7% | -2.7% | 6.0% | 12.9% | 1.5% | -4.8% | -3.1% | 5.9% | 13.1% | 1.2% | -5.3% | 1.309 |
| tsp | 2021-04 | x100 | frontier | 20.4% | -24.3% | 20.8% | 67.7% | -1.6% | -31.9% | -25.3% | 20.7% | 66.0% | -2.4% | -32.6% | 1.060 |
| tsp | 2021-05 | x25 | w_R | 5.6% | -3.8% | 6.8% | 16.5% | 1.4% | -6.6% | -4.4% | 6.7% | 16.1% | 0.9% | -7.2% | 1.591 |
| tsp | 2021-05 | x25 | frontier | 6.1% | -5.5% | 7.4% | 19.3% | 0.8% | -8.5% | -5.9% | 7.3% | 19.0% | 0.5% | -9.3% | 1.841 |
| tsp | 2021-05 | x50 | w_R | 7.6% | -5.7% | 8.7% | 22.4% | 1.4% | -9.3% | -6.5% | 8.6% | 22.1% | 0.9% | -10.1% | 1.654 |
| tsp | 2021-05 | x50 | frontier | 10.9% | -10.6% | 12.5% | 33.9% | 0.8% | -15.7% | -11.5% | 12.2% | 33.1% | 0.1% | -16.8% | 1.412 |
| tsp | 2021-05 | x100 | w_R | 7.6% | -5.7% | 8.7% | 22.4% | 1.4% | -9.3% | -6.5% | 8.6% | 22.1% | 0.9% | -10.1% | 1.654 |
| tsp | 2021-05 | x100 | frontier | 20.5% | -23.4% | 21.9% | 68.9% | -0.5% | -31.4% | -24.5% | 21.4% | 66.7% | -1.6% | -32.9% | 1.060 |
| tsp | 2021-06 | x25 | w_R | 2.5% | -1.5% | 3.5% | 8.0% | 1.0% | -2.7% | -1.6% | 3.5% | 7.8% | 0.9% | -2.9% | 2.067 |
| tsp | 2021-06 | x25 | frontier | 6.1% | -6.9% | 7.5% | 19.2% | 0.0% | -9.4% | -6.2% | 7.5% | 19.1% | 0.4% | -9.3% | 1.841 |
| tsp | 2021-06 | x50 | w_R | 2.5% | -1.5% | 3.5% | 8.0% | 1.0% | -2.7% | -1.6% | 3.5% | 7.8% | 0.9% | -2.9% | 2.067 |
| tsp | 2021-06 | x50 | frontier | 10.9% | -12.8% | 12.6% | 34.6% | -0.4% | -17.0% | -11.8% | 12.3% | 33.5% | -0.0% | -16.8% | 1.413 |
| tsp | 2021-06 | x100 | w_R | 2.5% | -1.5% | 3.5% | 8.0% | 1.0% | -2.7% | -1.6% | 3.5% | 7.8% | 0.9% | -2.9% | 2.067 |
| tsp | 2021-06 | x100 | frontier | 20.5% | -26.2% | 22.1% | 70.2% | -2.0% | -33.5% | -24.4% | 21.5% | 68.4% | -1.3% | -32.8% | 1.061 |
| tsp | 2021-07 | x25 | w_R | 3.5% | -2.2% | 4.5% | 9.7% | 1.0% | -3.7% | -2.2% | 4.5% | 10.1% | 1.0% | -3.9% | 1.564 |
| tsp | 2021-07 | x25 | frontier | 6.1% | -5.9% | 7.1% | 18.0% | 0.4% | -8.4% | -5.8% | 7.1% | 19.0% | 0.5% | -8.9% | 1.862 |
| tsp | 2021-07 | x50 | w_R | 3.5% | -2.2% | 4.5% | 9.7% | 1.0% | -3.7% | -2.2% | 4.5% | 10.1% | 1.0% | -3.9% | 1.564 |
| tsp | 2021-07 | x50 | frontier | 10.8% | -11.4% | 12.1% | 31.5% | -0.0% | -15.4% | -11.0% | 11.8% | 33.1% | 0.3% | -16.0% | 1.400 |
| tsp | 2021-07 | x100 | w_R | 3.5% | -2.2% | 4.5% | 9.7% | 1.0% | -3.7% | -2.2% | 4.5% | 10.1% | 1.0% | -3.9% | 1.564 |
| tsp | 2021-07 | x100 | frontier | 20.4% | -25.7% | 20.7% | 66.1% | -2.6% | -31.6% | -24.4% | 20.2% | 68.7% | -1.7% | -32.1% | 1.063 |
| tsp | 2021-08 | x25 | w_R | 2.6% | -2.0% | 3.6% | 8.2% | 0.7% | -3.7% | -1.6% | 3.7% | 8.1% | 1.0% | -2.9% | 1.880 |
| tsp | 2021-08 | x25 | frontier | 6.1% | -6.9% | 7.3% | 19.1% | -0.0% | -10.6% | -5.6% | 7.2% | 18.7% | 0.7% | -8.9% | 1.823 |
| tsp | 2021-08 | x50 | w_R | 2.6% | -2.0% | 3.6% | 8.2% | 0.7% | -3.7% | -1.6% | 3.7% | 8.1% | 1.0% | -2.9% | 1.880 |
| tsp | 2021-08 | x50 | frontier | 10.9% | -13.8% | 11.8% | 33.4% | -1.4% | -19.1% | -11.0% | 12.2% | 32.7% | 0.3% | -16.2% | 1.393 |
| tsp | 2021-08 | x100 | w_R | 2.6% | -2.0% | 3.6% | 8.2% | 0.7% | -3.7% | -1.6% | 3.7% | 8.1% | 1.0% | -2.9% | 1.880 |
| tsp | 2021-08 | x100 | frontier | 20.4% | -29.1% | 20.3% | 67.2% | -4.7% | -37.4% | -24.3% | 21.1% | 66.8% | -1.6% | -32.8% | 1.063 |
| tsp | 2021-09 | x25 | w_R | 2.6% | -1.5% | 3.6% | 7.9% | 1.0% | -2.9% | -1.7% | 3.5% | 8.0% | 0.8% | -3.0% | 2.018 |
| tsp | 2021-09 | x25 | frontier | 6.1% | -5.7% | 7.1% | 18.0% | 0.5% | -8.7% | -5.8% | 7.0% | 18.6% | 0.4% | -8.9% | 1.820 |
| tsp | 2021-09 | x50 | w_R | 2.6% | -1.5% | 3.6% | 7.9% | 1.0% | -2.9% | -1.7% | 3.5% | 8.0% | 0.8% | -3.0% | 2.018 |
| tsp | 2021-09 | x50 | frontier | 10.9% | -11.4% | 11.6% | 31.7% | -0.2% | -16.0% | -11.3% | 11.6% | 32.4% | -0.1% | -16.2% | 1.396 |
| tsp | 2021-09 | x100 | w_R | 2.6% | -1.5% | 3.6% | 7.9% | 1.0% | -2.9% | -1.7% | 3.5% | 8.0% | 0.8% | -3.0% | 2.018 |
| tsp | 2021-09 | x100 | frontier | 20.4% | -24.4% | 19.8% | 65.8% | -2.1% | -32.4% | -25.0% | 19.7% | 67.4% | -2.3% | -32.8% | 1.063 |
| tsp | 2021-10 | x25 | w_R | 5.5% | -3.7% | 6.8% | 16.2% | 1.4% | -6.4% | -4.2% | 6.7% | 16.1% | 1.1% | -6.9% | 1.709 |
| tsp | 2021-10 | x25 | frontier | 6.1% | -5.1% | 7.4% | 18.6% | 1.0% | -8.1% | -5.4% | 7.5% | 18.8% | 0.9% | -8.6% | 1.792 |
| tsp | 2021-10 | x50 | w_R | 7.5% | -5.5% | 8.9% | 22.1% | 1.6% | -9.1% | -6.2% | 8.9% | 22.1% | 1.1% | -9.8% | 1.656 |
| tsp | 2021-10 | x50 | frontier | 10.9% | -10.5% | 12.3% | 32.7% | 0.7% | -14.9% | -10.7% | 12.6% | 33.3% | 0.7% | -15.8% | 1.392 |
| tsp | 2021-10 | x100 | w_R | 7.5% | -5.5% | 8.9% | 22.1% | 1.6% | -9.1% | -6.2% | 8.9% | 22.1% | 1.1% | -9.8% | 1.656 |
| tsp | 2021-10 | x100 | frontier | 20.4% | -24.4% | 21.3% | 66.8% | -1.6% | -32.0% | -24.1% | 21.7% | 70.2% | -0.9% | -32.6% | 1.064 |
| tsp | 2021-11 | x25 | w_R | 6.1% | -4.3% | 7.4% | 18.7% | 1.5% | -7.4% | -4.9% | 7.3% | 18.3% | 1.1% | -8.1% | 1.820 |
| tsp | 2021-11 | x25 | frontier | 6.1% | -4.7% | 7.4% | 18.9% | 1.3% | -7.8% | -5.2% | 7.3% | 18.6% | 0.9% | -8.4% | 1.850 |
| tsp | 2021-11 | x50 | w_R | 6.4% | -4.6% | 7.8% | 19.6% | 1.5% | -7.8% | -5.1% | 7.7% | 19.1% | 1.1% | -8.5% | 1.783 |
| tsp | 2021-11 | x50 | frontier | 10.9% | -9.6% | 12.3% | 32.1% | 1.1% | -14.7% | -10.1% | 12.2% | 31.7% | 0.7% | -15.2% | 1.360 |
| tsp | 2021-11 | x100 | w_R | 6.4% | -4.6% | 7.8% | 19.6% | 1.5% | -7.8% | -5.1% | 7.7% | 19.1% | 1.1% | -8.5% | 1.783 |
| tsp | 2021-11 | x100 | frontier | 20.5% | -24.9% | 20.0% | 67.2% | -2.2% | -32.6% | -25.0% | 20.2% | 66.2% | -2.3% | -33.1% | 1.063 |
| tsp | 2021-12 | x25 | w_R | 6.1% | -3.8% | 7.5% | 17.6% | 1.7% | -6.9% | -4.8% | 7.2% | 17.6% | 1.0% | -7.7% | 1.557 |
| tsp | 2021-12 | x25 | frontier | 6.1% | -4.4% | 7.5% | 18.1% | 1.4% | -7.3% | -5.2% | 7.3% | 18.5% | 0.9% | -8.2% | 1.845 |
| tsp | 2021-12 | x50 | w_R | 10.2% | -7.3% | 11.8% | 29.1% | 2.1% | -12.3% | -8.9% | 11.3% | 29.0% | 0.9% | -13.5% | 1.332 |
| tsp | 2021-12 | x50 | frontier | 11.0% | -8.3% | 12.6% | 31.4% | 1.9% | -13.5% | -9.9% | 12.1% | 31.2% | 0.8% | -14.7% | 1.337 |
| tsp | 2021-12 | x100 | w_R | 11.4% | -8.3% | 13.0% | 32.3% | 2.1% | -13.7% | -10.1% | 12.4% | 32.0% | 0.9% | -15.0% | 1.274 |
| tsp | 2021-12 | x100 | frontier | 20.6% | -22.8% | 20.4% | 67.3% | -0.8% | -31.3% | -24.7% | 19.7% | 66.2% | -2.3% | -33.3% | 1.064 |
| tsp | 2022-01 | x25 | w_R | 3.6% | -2.4% | 4.4% | 10.3% | 0.9% | -4.1% | -2.7% | 4.2% | 10.1% | 0.6% | -4.4% | 1.548 |
| tsp | 2022-01 | x25 | frontier | 6.2% | -5.6% | 6.7% | 18.1% | 0.5% | -8.1% | -5.7% | 6.4% | 17.9% | 0.3% | -8.6% | 1.767 |
| tsp | 2022-01 | x50 | w_R | 3.6% | -2.4% | 4.4% | 10.3% | 0.9% | -4.1% | -2.7% | 4.2% | 10.1% | 0.6% | -4.4% | 1.548 |
| tsp | 2022-01 | x50 | frontier | 11.1% | -10.5% | 11.3% | 31.4% | 0.2% | -14.7% | -10.8% | 10.6% | 30.6% | -0.3% | -15.4% | 1.321 |
| tsp | 2022-01 | x100 | w_R | 3.6% | -2.4% | 4.4% | 10.3% | 0.9% | -4.1% | -2.7% | 4.2% | 10.1% | 0.6% | -4.4% | 1.548 |
| tsp | 2022-01 | x100 | frontier | 20.8% | -25.9% | 18.5% | 64.0% | -3.6% | -34.1% | -26.8% | 16.8% | 65.6% | -4.5% | -34.4% | 1.063 |
| tsp | 2022-02 | x25 | w_R | 4.0% | -2.8% | 4.4% | 10.9% | 0.7% | -4.7% | -3.4% | 4.4% | 10.7% | 0.3% | -5.4% | 1.437 |
| tsp | 2022-02 | x25 | frontier | 6.3% | -5.6% | 6.4% | 17.7% | 0.3% | -8.2% | -6.3% | 6.2% | 17.3% | -0.2% | -9.4% | 1.713 |
| tsp | 2022-02 | x50 | w_R | 4.0% | -2.8% | 4.4% | 10.9% | 0.7% | -4.7% | -3.4% | 4.4% | 10.7% | 0.3% | -5.4% | 1.437 |
| tsp | 2022-02 | x50 | frontier | 11.2% | -10.1% | 10.2% | 30.0% | 0.0% | -14.7% | -11.3% | 10.2% | 29.8% | -0.8% | -16.4% | 1.319 |
| tsp | 2022-02 | x100 | w_R | 4.0% | -2.8% | 4.4% | 10.9% | 0.7% | -4.7% | -3.4% | 4.4% | 10.7% | 0.3% | -5.4% | 1.437 |
| tsp | 2022-02 | x100 | frontier | 21.1% | -24.6% | 16.7% | 63.9% | -3.4% | -34.2% | -27.8% | 16.1% | 63.7% | -5.5% | -35.2% | 1.062 |
| tsp | 2022-03 | x25 | w_R | 2.0% | -2.0% | 2.6% | 6.0% | 0.2% | -3.1% | -1.9% | 2.5% | 6.2% | 0.2% | -2.9% | 2.335 |
| tsp | 2022-03 | x25 | frontier | 6.4% | -7.2% | 6.5% | 16.9% | -0.7% | -10.4% | -6.4% | 6.2% | 17.5% | -0.2% | -9.5% | 1.514 |
| tsp | 2022-03 | x50 | w_R | 2.0% | -2.0% | 2.6% | 6.0% | 0.2% | -3.1% | -1.9% | 2.5% | 6.2% | 0.2% | -2.9% | 2.335 |
| tsp | 2022-03 | x50 | frontier | 11.4% | -13.0% | 10.7% | 30.0% | -1.6% | -18.6% | -11.9% | 10.3% | 31.0% | -1.0% | -17.1% | 1.323 |
| tsp | 2022-03 | x100 | w_R | 2.0% | -2.0% | 2.6% | 6.0% | 0.2% | -3.1% | -1.9% | 2.5% | 6.2% | 0.2% | -2.9% | 2.335 |
| tsp | 2022-03 | x100 | frontier | 21.4% | -29.7% | 17.2% | 65.1% | -6.2% | -38.6% | -27.9% | 16.7% | 65.3% | -5.2% | -36.6% | 1.061 |
| tsp | 2022-04 | x25 | w_R | 2.1% | -2.5% | 2.4% | 6.1% | -0.2% | -3.6% | -2.6% | 2.3% | 6.3% | -0.2% | -3.5% | 2.246 |
| tsp | 2022-04 | x25 | frontier | 6.3% | -7.3% | 5.5% | 15.0% | -1.2% | -10.0% | -6.3% | 5.3% | 15.2% | -0.7% | -8.7% | 1.137 |
| tsp | 2022-04 | x50 | w_R | 2.1% | -2.5% | 2.4% | 6.1% | -0.2% | -3.6% | -2.6% | 2.3% | 6.3% | -0.2% | -3.5% | 2.246 |
| tsp | 2022-04 | x50 | frontier | 11.1% | -13.6% | 8.9% | 27.0% | -2.8% | -18.0% | -11.8% | 8.5% | 26.8% | -1.8% | -15.8% | 1.008 |
| tsp | 2022-04 | x100 | w_R | 2.1% | -2.5% | 2.4% | 6.1% | -0.2% | -3.6% | -2.6% | 2.3% | 6.3% | -0.2% | -3.5% | 2.246 |
| tsp | 2022-04 | x100 | frontier | 20.8% | -29.6% | 14.4% | 56.5% | -7.8% | -37.7% | -26.7% | 13.8% | 58.2% | -6.1% | -33.6% | 1.065 |
| tsp | 2022-06 | x25 | w_R | 1.8% | -2.9% | 1.7% | 5.5% | -0.7% | -3.8% | -2.8% | 1.8% | 5.4% | -0.6% | -3.8% | 2.369 |
| tsp | 2022-06 | x25 | frontier | 6.6% | -7.5% | 4.5% | 14.6% | -1.7% | -10.8% | -7.6% | 4.6% | 15.1% | -1.7% | -10.4% | 1.132 |
| tsp | 2022-06 | x50 | w_R | 1.8% | -2.9% | 1.7% | 5.5% | -0.7% | -3.8% | -2.8% | 1.8% | 5.4% | -0.6% | -3.8% | 2.369 |
| tsp | 2022-06 | x50 | frontier | 11.6% | -13.9% | 7.0% | 25.5% | -3.7% | -19.1% | -13.8% | 7.1% | 26.5% | -3.5% | -18.5% | 1.008 |
| tsp | 2022-06 | x100 | w_R | 1.8% | -2.9% | 1.7% | 5.5% | -0.7% | -3.8% | -2.8% | 1.8% | 5.4% | -0.6% | -3.8% | 2.369 |
| tsp | 2022-06 | x100 | frontier | 21.6% | -30.7% | 10.4% | 54.2% | -9.9% | -39.0% | -30.2% | 10.8% | 57.1% | -9.2% | -37.6% | 1.062 |
| tsp | 2022-07 | x25 | w_R | 3.0% | -3.6% | 2.9% | 8.6% | -0.4% | -5.0% | -3.5% | 2.9% | 8.3% | -0.4% | -5.0% | 1.825 |
| tsp | 2022-07 | x25 | frontier | 6.6% | -6.9% | 5.1% | 16.3% | -1.0% | -10.1% | -7.2% | 5.1% | 15.7% | -1.2% | -10.0% | 1.132 |
| tsp | 2022-07 | x50 | w_R | 3.0% | -3.6% | 2.9% | 8.6% | -0.4% | -5.0% | -3.5% | 2.9% | 8.3% | -0.4% | -5.0% | 1.825 |
| tsp | 2022-07 | x50 | frontier | 11.7% | -13.3% | 8.0% | 28.6% | -2.7% | -18.2% | -13.4% | 7.9% | 27.7% | -2.9% | -17.8% | 1.025 |
| tsp | 2022-07 | x100 | w_R | 3.0% | -3.6% | 2.9% | 8.6% | -0.4% | -5.0% | -3.5% | 2.9% | 8.3% | -0.4% | -5.0% | 1.825 |
| tsp | 2022-07 | x100 | frontier | 21.7% | -29.0% | 13.1% | 61.6% | -7.3% | -37.2% | -29.1% | 12.4% | 59.0% | -7.9% | -36.5% | 1.061 |
| tsp | 2022-08 | x25 | w_R | 2.2% | -2.9% | 2.3% | 6.6% | -0.4% | -4.0% | -3.0% | 2.1% | 6.4% | -0.5% | -4.0% | 2.208 |
| tsp | 2022-08 | x25 | frontier | 6.7% | -7.6% | 5.2% | 15.9% | -1.4% | -10.0% | -7.4% | 4.7% | 15.2% | -1.5% | -10.1% | 1.130 |
| tsp | 2022-08 | x50 | w_R | 2.2% | -2.9% | 2.3% | 6.6% | -0.4% | -4.0% | -3.0% | 2.1% | 6.4% | -0.5% | -4.0% | 2.208 |
| tsp | 2022-08 | x50 | frontier | 11.8% | -13.5% | 8.2% | 27.5% | -2.9% | -17.8% | -13.6% | 7.2% | 26.6% | -3.4% | -18.1% | 1.008 |
| tsp | 2022-08 | x100 | w_R | 2.2% | -2.9% | 2.3% | 6.6% | -0.4% | -4.0% | -3.0% | 2.1% | 6.4% | -0.5% | -4.0% | 2.208 |
| tsp | 2022-08 | x100 | frontier | 21.9% | -29.1% | 12.3% | 60.3% | -7.8% | -36.5% | -29.7% | 11.1% | 56.3% | -8.8% | -36.7% | 1.060 |
| tsp | 2022-09 | x25 | w_R | 2.3% | -3.5% | 1.8% | 6.5% | -0.9% | -4.8% | -3.7% | 1.9% | 6.5% | -1.0% | -4.9% | 2.173 |
| tsp | 2022-09 | x25 | frontier | 6.8% | -8.6% | 4.0% | 15.4% | -2.4% | -11.4% | -8.9% | 4.0% | 15.5% | -2.6% | -11.6% | 1.127 |
| tsp | 2022-09 | x50 | w_R | 2.3% | -3.5% | 1.8% | 6.5% | -0.9% | -4.8% | -3.7% | 1.9% | 6.5% | -1.0% | -4.9% | 2.173 |
| tsp | 2022-09 | x50 | frontier | 11.9% | -15.5% | 5.9% | 26.3% | -4.9% | -20.0% | -15.9% | 5.8% | 26.7% | -5.1% | -20.2% | 1.008 |
| tsp | 2022-09 | x100 | w_R | 2.3% | -3.5% | 1.8% | 6.5% | -0.9% | -4.8% | -3.7% | 1.9% | 6.5% | -1.0% | -4.9% | 2.173 |
| tsp | 2022-09 | x100 | frontier | 22.1% | -32.9% | 8.2% | 55.3% | -11.8% | -40.1% | -32.8% | 7.9% | 56.0% | -11.7% | -39.3% | 1.060 |
| tsp | 2022-10 | x25 | w_R | 2.0% | -3.1% | 1.7% | 6.0% | -0.8% | -4.1% | -3.1% | 1.8% | 6.0% | -0.7% | -4.2% | 2.203 |
| tsp | 2022-10 | x25 | frontier | 6.9% | -8.7% | 4.4% | 14.9% | -2.4% | -10.9% | -8.0% | 4.5% | 15.6% | -1.9% | -10.9% | 1.125 |
| tsp | 2022-10 | x50 | w_R | 2.0% | -3.1% | 1.7% | 6.0% | -0.8% | -4.1% | -3.1% | 1.8% | 6.0% | -0.7% | -4.2% | 2.203 |
| tsp | 2022-10 | x50 | frontier | 12.1% | -15.8% | 6.4% | 25.7% | -5.0% | -19.1% | -14.7% | 6.7% | 26.8% | -4.1% | -19.2% | 1.008 |
| tsp | 2022-10 | x100 | w_R | 2.0% | -3.1% | 1.7% | 6.0% | -0.8% | -4.1% | -3.1% | 1.8% | 6.0% | -0.7% | -4.2% | 2.203 |
| tsp | 2022-10 | x100 | frontier | 22.4% | -31.4% | 8.7% | 55.3% | -10.7% | -37.9% | -31.9% | 9.4% | 56.1% | -10.7% | -38.6% | 1.059 |
| tsp | 2022-11 | x25 | w_R | 2.1% | -2.6% | 2.1% | 6.7% | -0.3% | -4.0% | -3.0% | 2.2% | 6.6% | -0.5% | -4.0% | 2.134 |
| tsp | 2022-11 | x25 | frontier | 7.0% | -9.0% | 4.9% | 16.7% | -2.3% | -11.9% | -7.8% | 4.9% | 16.8% | -1.5% | -10.9% | 1.122 |
| tsp | 2022-11 | x50 | w_R | 2.1% | -2.6% | 2.1% | 6.7% | -0.3% | -4.0% | -3.0% | 2.2% | 6.6% | -0.5% | -4.0% | 2.134 |
| tsp | 2022-11 | x50 | frontier | 12.3% | -16.1% | 7.0% | 28.2% | -4.7% | -20.8% | -14.4% | 7.2% | 28.5% | -3.6% | -19.3% | 1.008 |
| tsp | 2022-11 | x100 | w_R | 2.1% | -2.6% | 2.1% | 6.7% | -0.3% | -4.0% | -3.0% | 2.2% | 6.6% | -0.5% | -4.0% | 2.134 |
| tsp | 2022-11 | x100 | frontier | 22.7% | -32.2% | 9.9% | 58.6% | -10.5% | -40.9% | -31.1% | 9.9% | 59.8% | -9.7% | -38.5% | 1.058 |
| tsp | 2022-12 | x25 | w_R | 2.1% | -2.8% | 2.3% | 6.9% | -0.3% | -4.0% | -3.0% | 2.2% | 6.8% | -0.5% | -4.1% | 2.145 |
| tsp | 2022-12 | x25 | frontier | 7.1% | -8.4% | 4.6% | 15.7% | -2.1% | -11.4% | -8.7% | 4.5% | 15.8% | -2.3% | -11.5% | 1.121 |
| tsp | 2022-12 | x50 | w_R | 2.1% | -2.8% | 2.3% | 6.9% | -0.3% | -4.0% | -3.0% | 2.2% | 6.8% | -0.5% | -4.1% | 2.145 |
| tsp | 2022-12 | x50 | frontier | 12.4% | -15.1% | 6.6% | 26.5% | -4.4% | -20.3% | -15.9% | 6.3% | 26.7% | -5.0% | -20.3% | 1.008 |
| tsp | 2022-12 | x100 | w_R | 2.1% | -2.8% | 2.3% | 6.9% | -0.3% | -4.0% | -3.0% | 2.2% | 6.8% | -0.5% | -4.1% | 2.145 |
| tsp | 2022-12 | x100 | frontier | 22.9% | -32.3% | 8.6% | 54.1% | -11.4% | -40.5% | -33.2% | 8.0% | 53.9% | -12.1% | -40.1% | 1.057 |
| tsp | 2023-01 | x25 | w_R | 2.1% | -2.7% | 2.6% | 7.0% | -0.1% | -3.8% | -2.8% | 2.5% | 6.9% | -0.2% | -3.9% | 2.120 |
| tsp | 2023-01 | x25 | frontier | 7.2% | -8.6% | 5.2% | 16.1% | -2.0% | -11.0% | -8.2% | 4.8% | 16.5% | -1.8% | -11.1% | 1.121 |
| tsp | 2023-01 | x50 | w_R | 2.1% | -2.7% | 2.6% | 7.0% | -0.1% | -3.8% | -2.8% | 2.5% | 6.9% | -0.2% | -3.9% | 2.120 |
| tsp | 2023-01 | x50 | frontier | 12.4% | -15.9% | 7.3% | 27.1% | -4.6% | -19.8% | -15.4% | 6.7% | 27.7% | -4.5% | -19.9% | 1.008 |
| tsp | 2023-01 | x100 | w_R | 2.1% | -2.7% | 2.6% | 7.0% | -0.1% | -3.8% | -2.8% | 2.5% | 6.9% | -0.2% | -3.9% | 2.120 |
| tsp | 2023-01 | x100 | frontier | 23.0% | -33.6% | 9.9% | 55.6% | -11.6% | -39.7% | -32.1% | 9.0% | 57.3% | -10.8% | -39.6% | 1.056 |
| tsp | 2023-02 | x25 | w_R | 2.1% | -2.3% | 2.6% | 6.8% | 0.1% | -3.4% | -2.5% | 2.6% | 7.1% | -0.0% | -3.6% | 2.047 |
| tsp | 2023-02 | x25 | frontier | 7.2% | -8.3% | 5.0% | 16.6% | -1.8% | -10.9% | -7.9% | 5.1% | 16.4% | -1.6% | -10.3% | 1.119 |
| tsp | 2023-02 | x50 | w_R | 2.1% | -2.3% | 2.6% | 6.8% | 0.1% | -3.4% | -2.5% | 2.6% | 7.1% | -0.0% | -3.6% | 2.047 |
| tsp | 2023-02 | x50 | frontier | 12.4% | -15.2% | 7.0% | 27.8% | -4.2% | -19.6% | -14.7% | 7.1% | 27.0% | -4.0% | -18.7% | 1.008 |
| tsp | 2023-02 | x100 | w_R | 2.1% | -2.3% | 2.6% | 6.8% | 0.1% | -3.4% | -2.5% | 2.6% | 7.1% | -0.0% | -3.6% | 2.047 |
| tsp | 2023-02 | x100 | frontier | 22.9% | -31.1% | 9.9% | 55.8% | -10.1% | -39.0% | -31.3% | 9.6% | 56.2% | -10.3% | -37.6% | 1.056 |
| tsp | 2023-03 | x25 | w_R | 2.3% | -2.3% | 2.9% | 7.7% | 0.3% | -3.6% | -2.5% | 3.1% | 7.8% | 0.2% | -3.7% | 2.120 |
| tsp | 2023-03 | x25 | frontier | 7.2% | -7.8% | 5.1% | 16.4% | -1.5% | -10.7% | -7.7% | 5.2% | 16.6% | -1.4% | -10.5% | 1.119 |
| tsp | 2023-03 | x50 | w_R | 2.3% | -2.3% | 2.9% | 7.7% | 0.3% | -3.6% | -2.5% | 3.1% | 7.8% | 0.2% | -3.7% | 2.120 |
| tsp | 2023-03 | x50 | frontier | 12.5% | -14.7% | 6.6% | 27.0% | -4.1% | -19.3% | -14.9% | 7.1% | 27.5% | -4.1% | -19.0% | 1.008 |
| tsp | 2023-03 | x100 | w_R | 2.3% | -2.3% | 2.9% | 7.7% | 0.3% | -3.6% | -2.5% | 3.1% | 7.8% | 0.2% | -3.7% | 2.120 |
| tsp | 2023-03 | x100 | frontier | 23.0% | -31.8% | 8.2% | 53.9% | -11.2% | -38.9% | -31.9% | 8.9% | 55.6% | -10.9% | -38.4% | 1.056 |
| tsp | 2023-04 | x25 | w_R | 2.9% | -2.4% | 3.6% | 9.0% | 0.5% | -3.9% | -2.9% | 3.7% | 9.3% | 0.3% | -4.3% | 1.947 |
| tsp | 2023-04 | x25 | frontier | 7.2% | -7.4% | 5.6% | 17.0% | -1.1% | -9.8% | -8.0% | 5.5% | 17.2% | -1.4% | -10.7% | 1.119 |
| tsp | 2023-04 | x50 | w_R | 2.9% | -2.4% | 3.6% | 9.0% | 0.5% | -3.9% | -2.9% | 3.7% | 9.3% | 0.3% | -4.3% | 1.947 |
| tsp | 2023-04 | x50 | frontier | 12.4% | -14.4% | 7.7% | 27.8% | -3.5% | -18.1% | -15.1% | 7.4% | 28.2% | -4.0% | -19.4% | 1.008 |
| tsp | 2023-04 | x100 | w_R | 2.9% | -2.4% | 3.6% | 9.0% | 0.5% | -3.9% | -2.9% | 3.7% | 9.3% | 0.3% | -4.3% | 1.947 |
| tsp | 2023-04 | x100 | frontier | 22.9% | -31.0% | 9.6% | 57.2% | -10.0% | -36.8% | -32.0% | 9.3% | 57.4% | -10.7% | -39.1% | 1.057 |
| tsp | 2023-05 | x25 | w_R | 2.2% | -2.0% | 3.3% | 7.9% | 0.6% | -3.0% | -2.1% | 3.3% | 7.8% | 0.5% | -3.1% | 2.086 |
| tsp | 2023-05 | x25 | frontier | 7.2% | -7.8% | 5.7% | 17.3% | -1.2% | -10.8% | -7.6% | 5.6% | 17.2% | -1.2% | -10.4% | 1.119 |
| tsp | 2023-05 | x50 | w_R | 2.2% | -2.0% | 3.3% | 7.9% | 0.6% | -3.0% | -2.1% | 3.3% | 7.8% | 0.5% | -3.1% | 2.086 |
| tsp | 2023-05 | x50 | frontier | 12.4% | -15.1% | 7.6% | 28.0% | -3.9% | -19.8% | -14.7% | 7.3% | 28.1% | -3.8% | -19.1% | 1.008 |
| tsp | 2023-05 | x100 | w_R | 2.2% | -2.0% | 3.3% | 7.9% | 0.6% | -3.0% | -2.1% | 3.3% | 7.8% | 0.5% | -3.1% | 2.086 |
| tsp | 2023-05 | x100 | frontier | 22.9% | -32.5% | 9.6% | 54.6% | -11.2% | -39.6% | -32.1% | 8.7% | 56.3% | -11.0% | -38.7% | 1.057 |
| tsp | 2023-06 | x25 | w_R | 2.9% | -2.1% | 3.8% | 10.0% | 0.9% | -3.6% | -2.6% | 4.0% | 9.6% | 0.6% | -3.9% | 1.979 |
| tsp | 2023-06 | x25 | frontier | 7.2% | -6.5% | 5.7% | 18.0% | -0.4% | -9.0% | -7.3% | 5.8% | 17.6% | -0.9% | -10.4% | 1.118 |
| tsp | 2023-06 | x50 | w_R | 2.9% | -2.1% | 3.8% | 10.0% | 0.9% | -3.6% | -2.6% | 4.0% | 9.6% | 0.6% | -3.9% | 1.979 |
| tsp | 2023-06 | x50 | frontier | 12.5% | -12.8% | 7.3% | 29.1% | -2.6% | -16.9% | -14.3% | 7.6% | 28.4% | -3.5% | -19.3% | 1.008 |
| tsp | 2023-06 | x100 | w_R | 2.9% | -2.1% | 3.8% | 10.0% | 0.9% | -3.6% | -2.6% | 4.0% | 9.6% | 0.6% | -3.9% | 1.979 |
| tsp | 2023-06 | x100 | frontier | 22.9% | -27.9% | 8.5% | 57.0% | -8.5% | -35.2% | -31.4% | 9.1% | 57.3% | -10.4% | -39.1% | 1.057 |
| tsp | 2023-07 | x25 | w_R | 2.6% | -2.1% | 3.9% | 9.0% | 0.8% | -3.3% | -2.1% | 4.0% | 9.1% | 0.9% | -3.2% | 2.080 |
| tsp | 2023-07 | x25 | frontier | 7.3% | -7.1% | 6.0% | 17.8% | -0.7% | -10.2% | -7.2% | 6.3% | 18.2% | -0.6% | -10.2% | 1.117 |
| tsp | 2023-07 | x50 | w_R | 2.6% | -2.1% | 3.9% | 9.0% | 0.8% | -3.3% | -2.1% | 4.0% | 9.1% | 0.9% | -3.2% | 2.080 |
| tsp | 2023-07 | x50 | frontier | 12.5% | -14.3% | 7.9% | 29.1% | -3.3% | -19.0% | -14.2% | 8.2% | 29.5% | -3.1% | -19.0% | 1.008 |
| tsp | 2023-07 | x100 | w_R | 2.6% | -2.1% | 3.9% | 9.0% | 0.8% | -3.3% | -2.1% | 4.0% | 9.1% | 0.9% | -3.2% | 2.080 |
| tsp | 2023-07 | x100 | frontier | 22.9% | -30.8% | 9.4% | 57.2% | -9.9% | -38.9% | -31.6% | 10.0% | 58.1% | -10.1% | -38.6% | 1.057 |
| tsp | 2023-08 | x25 | w_R | 2.1% | -1.4% | 3.5% | 7.8% | 1.0% | -2.3% | -1.7% | 3.5% | 8.0% | 0.8% | -2.7% | 1.917 |
| tsp | 2023-08 | x25 | frontier | 7.3% | -7.3% | 5.9% | 17.7% | -0.8% | -10.5% | -7.6% | 5.9% | 17.9% | -1.0% | -10.8% | 1.116 |
| tsp | 2023-08 | x50 | w_R | 2.1% | -1.4% | 3.5% | 7.8% | 1.0% | -2.3% | -1.7% | 3.5% | 8.0% | 0.8% | -2.7% | 1.917 |
| tsp | 2023-08 | x50 | frontier | 12.5% | -14.6% | 7.4% | 28.7% | -3.6% | -19.7% | -14.9% | 7.6% | 28.8% | -3.8% | -19.9% | 1.009 |
| tsp | 2023-08 | x100 | w_R | 2.1% | -1.4% | 3.5% | 7.8% | 1.0% | -2.3% | -1.7% | 3.5% | 8.0% | 0.8% | -2.7% | 1.917 |
| tsp | 2023-08 | x100 | frontier | 23.0% | -32.2% | 8.2% | 58.3% | -11.0% | -39.7% | -32.2% | 8.7% | 57.0% | -11.0% | -40.0% | 1.056 |
| tsp | 2023-09 | x25 | w_R | 2.1% | -1.6% | 3.5% | 7.7% | 0.9% | -2.7% | -1.5% | 3.4% | 7.8% | 0.9% | -2.5% | 1.606 |
| tsp | 2023-09 | x25 | frontier | 7.3% | -8.4% | 5.5% | 18.0% | -1.6% | -11.2% | -7.7% | 5.5% | 17.6% | -1.2% | -10.9% | 1.116 |
| tsp | 2023-09 | x50 | w_R | 2.1% | -1.6% | 3.5% | 7.7% | 0.9% | -2.7% | -1.5% | 3.4% | 7.8% | 0.9% | -2.5% | 1.606 |
| tsp | 2023-09 | x50 | frontier | 12.5% | -16.4% | 6.7% | 29.3% | -4.9% | -20.7% | -15.4% | 6.8% | 28.2% | -4.4% | -20.2% | 1.009 |
| tsp | 2023-09 | x100 | w_R | 2.1% | -1.6% | 3.5% | 7.7% | 0.9% | -2.7% | -1.5% | 3.4% | 7.8% | 0.9% | -2.5% | 1.606 |
| tsp | 2023-09 | x100 | frontier | 23.0% | -34.8% | 6.9% | 60.9% | -12.7% | -41.1% | -33.7% | 7.1% | 55.9% | -12.5% | -40.7% | 1.056 |
| tsp | 2023-10 | x25 | w_R | 2.2% | -1.6% | 3.7% | 8.5% | 1.0% | -3.1% | -1.7% | 3.7% | 8.5% | 1.0% | -2.8% | 2.015 |
| tsp | 2023-10 | x25 | frontier | 7.3% | -8.4% | 5.6% | 17.7% | -1.6% | -11.5% | -7.7% | 5.7% | 18.0% | -1.1% | -10.4% | 1.115 |
| tsp | 2023-10 | x50 | w_R | 2.2% | -1.6% | 3.7% | 8.5% | 1.0% | -3.1% | -1.7% | 3.7% | 8.5% | 1.0% | -2.8% | 2.015 |
| tsp | 2023-10 | x50 | frontier | 12.6% | -16.3% | 6.9% | 28.2% | -4.9% | -21.0% | -15.2% | 7.0% | 28.6% | -4.2% | -19.4% | 1.009 |
| tsp | 2023-10 | x100 | w_R | 2.2% | -1.6% | 3.7% | 8.5% | 1.0% | -3.1% | -1.7% | 3.7% | 8.5% | 1.0% | -2.8% | 2.015 |
| tsp | 2023-10 | x100 | frontier | 23.0% | -34.4% | 7.8% | 56.6% | -12.6% | -41.8% | -32.9% | 7.5% | 55.8% | -11.9% | -39.5% | 1.056 |
| tsp | 2023-11 | x25 | w_R | 2.3% | -1.5% | 4.2% | 9.2% | 1.3% | -2.6% | -1.6% | 4.2% | 9.2% | 1.2% | -2.8% | 2.026 |
| tsp | 2023-11 | x25 | frontier | 7.4% | -6.5% | 6.4% | 17.7% | -0.2% | -9.7% | -7.3% | 6.5% | 18.4% | -0.6% | -10.3% | 1.113 |
| tsp | 2023-11 | x50 | w_R | 2.3% | -1.5% | 4.2% | 9.2% | 1.3% | -2.6% | -1.6% | 4.2% | 9.2% | 1.2% | -2.8% | 2.026 |
| tsp | 2023-11 | x50 | frontier | 12.6% | -13.4% | 8.1% | 28.3% | -2.8% | -18.2% | -14.7% | 8.2% | 29.4% | -3.5% | -19.4% | 1.009 |
| tsp | 2023-11 | x100 | w_R | 2.3% | -1.5% | 4.2% | 9.2% | 1.3% | -2.6% | -1.6% | 4.2% | 9.2% | 1.2% | -2.8% | 2.026 |
| tsp | 2023-11 | x100 | frontier | 22.9% | -29.6% | 8.9% | 54.7% | -9.6% | -37.3% | -32.1% | 9.6% | 57.4% | -10.7% | -39.4% | 1.057 |
| tsp | 2023-12 | x25 | w_R | 2.6% | -1.3% | 4.7% | 10.3% | 1.7% | -2.8% | -1.6% | 4.7% | 10.5% | 1.5% | -2.9% | 2.043 |
| tsp | 2023-12 | x25 | frontier | 7.3% | -6.2% | 7.4% | 18.7% | 0.4% | -9.3% | -6.5% | 7.5% | 19.5% | 0.3% | -9.5% | 1.111 |
| tsp | 2023-12 | x50 | w_R | 2.6% | -1.3% | 4.7% | 10.3% | 1.7% | -2.8% | -1.6% | 4.7% | 10.5% | 1.5% | -2.9% | 2.043 |
| tsp | 2023-12 | x50 | frontier | 12.5% | -13.3% | 9.6% | 29.8% | -2.1% | -17.6% | -13.1% | 9.9% | 31.3% | -1.8% | -18.0% | 1.009 |
| tsp | 2023-12 | x100 | w_R | 2.6% | -1.3% | 4.7% | 10.3% | 1.7% | -2.8% | -1.6% | 4.7% | 10.5% | 1.5% | -2.9% | 2.043 |
| tsp | 2023-12 | x100 | frontier | 22.8% | -29.1% | 12.6% | 61.6% | -7.5% | -36.7% | -30.2% | 13.0% | 61.6% | -8.1% | -37.6% | 1.059 |
| tsp | 2024-01 | x25 | w_R | 2.4% | -1.5% | 4.5% | 9.8% | 1.5% | -2.7% | -1.2% | 4.5% | 10.0% | 1.6% | -2.4% | 2.019 |
| tsp | 2024-01 | x25 | frontier | 7.3% | -7.0% | 7.3% | 18.7% | -0.1% | -10.0% | -6.3% | 7.5% | 19.3% | 0.4% | -9.1% | 1.109 |
| tsp | 2024-01 | x50 | w_R | 2.4% | -1.5% | 4.5% | 9.8% | 1.5% | -2.7% | -1.2% | 4.5% | 10.0% | 1.6% | -2.4% | 2.019 |
| tsp | 2024-01 | x50 | frontier | 12.4% | -14.0% | 9.6% | 30.2% | -2.5% | -18.6% | -12.9% | 9.7% | 30.4% | -1.8% | -17.4% | 1.009 |
| tsp | 2024-01 | x100 | w_R | 2.4% | -1.5% | 4.5% | 9.8% | 1.5% | -2.7% | -1.2% | 4.5% | 10.0% | 1.6% | -2.4% | 2.019 |
| tsp | 2024-01 | x100 | frontier | 22.6% | -30.2% | 11.8% | 59.4% | -8.6% | -38.3% | -29.1% | 12.4% | 59.0% | -7.9% | -36.5% | 1.060 |
| tsp | 2024-02 | x25 | w_R | 2.7% | -1.6% | 4.8% | 10.5% | 1.5% | -3.0% | -1.7% | 4.8% | 10.7% | 1.5% | -2.9% | 2.005 |
| tsp | 2024-02 | x25 | frontier | 7.3% | -7.0% | 7.5% | 19.9% | 0.0% | -10.3% | -6.6% | 7.4% | 19.8% | 0.3% | -9.7% | 1.108 |
| tsp | 2024-02 | x50 | w_R | 2.7% | -1.6% | 4.8% | 10.5% | 1.5% | -3.0% | -1.7% | 4.8% | 10.7% | 1.5% | -2.9% | 2.005 |
| tsp | 2024-02 | x50 | frontier | 12.4% | -14.2% | 9.9% | 31.7% | -2.4% | -19.1% | -13.4% | 9.7% | 31.5% | -2.0% | -18.3% | 1.009 |
| tsp | 2024-02 | x100 | w_R | 2.7% | -1.6% | 4.8% | 10.5% | 1.5% | -3.0% | -1.7% | 4.8% | 10.7% | 1.5% | -2.9% | 2.005 |
| tsp | 2024-02 | x100 | frontier | 22.6% | -31.3% | 12.2% | 62.0% | -9.0% | -39.2% | -30.3% | 12.2% | 60.6% | -8.5% | -37.6% | 1.060 |
| tsp | 2024-03 | x25 | w_R | 2.7% | -1.8% | 4.8% | 10.5% | 1.4% | -3.1% | -1.4% | 4.8% | 10.6% | 1.6% | -2.7% | 2.020 |
| tsp | 2024-03 | x25 | frontier | 7.3% | -7.1% | 7.5% | 20.1% | 0.0% | -10.3% | -6.6% | 7.6% | 19.6% | 0.3% | -9.6% | 1.108 |
| tsp | 2024-03 | x50 | w_R | 2.7% | -1.8% | 4.8% | 10.5% | 1.4% | -3.1% | -1.4% | 4.8% | 10.6% | 1.6% | -2.7% | 2.020 |
| tsp | 2024-03 | x50 | frontier | 12.4% | -14.3% | 9.9% | 31.9% | -2.4% | -19.1% | -13.3% | 9.9% | 31.3% | -1.8% | -18.2% | 1.009 |
| tsp | 2024-03 | x100 | w_R | 2.7% | -1.8% | 4.8% | 10.5% | 1.4% | -3.1% | -1.4% | 4.8% | 10.6% | 1.6% | -2.7% | 2.020 |
| tsp | 2024-03 | x100 | frontier | 22.6% | -32.6% | 13.0% | 61.8% | -9.5% | -39.4% | -30.6% | 12.5% | 60.6% | -8.5% | -37.7% | 1.061 |
| tsp | 2024-04 | x25 | w_R | 3.1% | -1.8% | 4.9% | 11.1% | 1.5% | -3.2% | -2.1% | 4.8% | 11.2% | 1.3% | -3.4% | 1.905 |
| tsp | 2024-04 | x25 | frontier | 7.3% | -6.5% | 7.3% | 19.3% | 0.2% | -9.6% | -7.0% | 7.0% | 19.2% | -0.2% | -9.9% | 1.107 |
| tsp | 2024-04 | x50 | w_R | 3.1% | -1.8% | 4.9% | 11.1% | 1.5% | -3.2% | -2.1% | 4.8% | 11.2% | 1.3% | -3.4% | 1.905 |
| tsp | 2024-04 | x50 | frontier | 12.4% | -13.4% | 9.3% | 30.1% | -2.2% | -18.2% | -14.2% | 8.9% | 30.2% | -2.8% | -18.7% | 1.009 |
| tsp | 2024-04 | x100 | w_R | 3.1% | -1.8% | 4.9% | 11.1% | 1.5% | -3.2% | -2.1% | 4.8% | 11.2% | 1.3% | -3.4% | 1.905 |
| tsp | 2024-04 | x100 | frontier | 22.6% | -30.1% | 11.6% | 57.5% | -8.8% | -37.9% | -31.0% | 10.6% | 58.4% | -9.6% | -38.4% | 1.060 |
| tsp | 2024-05 | x25 | w_R | 2.5% | -1.3% | 4.4% | 10.2% | 1.6% | -2.5% | -1.5% | 4.5% | 9.9% | 1.5% | -2.7% | 1.992 |
| tsp | 2024-05 | x25 | frontier | 7.3% | -6.1% | 7.3% | 19.7% | 0.5% | -9.5% | -6.6% | 7.5% | 19.6% | 0.2% | -9.7% | 1.107 |
| tsp | 2024-05 | x50 | w_R | 2.5% | -1.3% | 4.4% | 10.2% | 1.6% | -2.5% | -1.5% | 4.5% | 9.9% | 1.5% | -2.7% | 1.992 |
| tsp | 2024-05 | x50 | frontier | 12.4% | -12.7% | 9.3% | 31.0% | -1.7% | -17.9% | -13.6% | 9.8% | 30.9% | -2.1% | -18.2% | 1.010 |
| tsp | 2024-05 | x100 | w_R | 2.5% | -1.3% | 4.4% | 10.2% | 1.6% | -2.5% | -1.5% | 4.5% | 9.9% | 1.5% | -2.7% | 1.992 |
| tsp | 2024-05 | x100 | frontier | 22.6% | -29.5% | 11.9% | 60.3% | -8.1% | -37.1% | -30.6% | 12.1% | 60.1% | -8.7% | -37.7% | 1.061 |
| tsp | 2024-06 | x25 | w_R | 2.7% | -1.3% | 4.7% | 10.5% | 1.6% | -2.9% | -1.5% | 4.7% | 10.6% | 1.6% | -2.7% | 1.993 |
| tsp | 2024-06 | x25 | frontier | 7.3% | -6.6% | 7.4% | 20.0% | 0.3% | -10.1% | -6.3% | 7.5% | 19.9% | 0.5% | -9.3% | 1.106 |
| tsp | 2024-06 | x50 | w_R | 2.7% | -1.3% | 4.7% | 10.5% | 1.6% | -2.9% | -1.5% | 4.7% | 10.6% | 1.6% | -2.7% | 1.993 |
| tsp | 2024-06 | x50 | frontier | 12.4% | -13.4% | 9.5% | 31.5% | -2.0% | -19.0% | -13.0% | 9.9% | 31.5% | -1.7% | -17.6% | 1.010 |
| tsp | 2024-06 | x100 | w_R | 2.7% | -1.3% | 4.7% | 10.5% | 1.6% | -2.9% | -1.5% | 4.7% | 10.6% | 1.6% | -2.7% | 1.993 |
| tsp | 2024-06 | x100 | frontier | 22.5% | -31.4% | 12.3% | 58.8% | -9.3% | -39.2% | -29.4% | 12.1% | 60.4% | -8.0% | -36.9% | 1.061 |
| tsp | 2024-07 | x25 | w_R | 2.7% | -1.2% | 4.7% | 10.3% | 1.7% | -2.6% | -1.4% | 4.7% | 10.6% | 1.6% | -2.6% | 1.999 |
| tsp | 2024-07 | x25 | frontier | 7.4% | -6.8% | 7.4% | 19.7% | 0.1% | -9.5% | -6.2% | 7.6% | 19.8% | 0.6% | -9.0% | 1.106 |
| tsp | 2024-07 | x50 | w_R | 2.7% | -1.2% | 4.7% | 10.3% | 1.7% | -2.6% | -1.4% | 4.7% | 10.6% | 1.6% | -2.6% | 1.999 |
| tsp | 2024-07 | x50 | frontier | 12.4% | -13.8% | 9.6% | 30.9% | -2.3% | -18.0% | -12.8% | 9.9% | 31.2% | -1.6% | -17.3% | 1.010 |
| tsp | 2024-07 | x100 | w_R | 2.7% | -1.2% | 4.7% | 10.3% | 1.7% | -2.6% | -1.4% | 4.7% | 10.6% | 1.6% | -2.6% | 1.999 |
| tsp | 2024-07 | x100 | frontier | 22.6% | -29.9% | 11.9% | 61.4% | -8.2% | -37.0% | -28.9% | 12.6% | 60.6% | -7.5% | -36.1% | 1.063 |
| tsp | 2024-08 | x25 | w_R | 2.7% | -1.1% | 4.9% | 10.6% | 1.8% | -2.2% | -1.6% | 4.8% | 10.7% | 1.6% | -2.7% | 1.993 |
| tsp | 2024-08 | x25 | frontier | 7.4% | -6.0% | 8.0% | 20.0% | 0.8% | -9.1% | -6.3% | 7.9% | 20.1% | 0.6% | -9.5% | 1.106 |
| tsp | 2024-08 | x50 | w_R | 2.7% | -1.1% | 4.9% | 10.6% | 1.8% | -2.2% | -1.6% | 4.8% | 10.7% | 1.6% | -2.7% | 1.993 |
| tsp | 2024-08 | x50 | frontier | 12.5% | -12.7% | 10.7% | 31.4% | -1.3% | -17.6% | -13.0% | 10.3% | 31.8% | -1.5% | -18.0% | 1.010 |
| tsp | 2024-08 | x100 | w_R | 2.7% | -1.1% | 4.9% | 10.6% | 1.8% | -2.2% | -1.6% | 4.8% | 10.7% | 1.6% | -2.7% | 1.993 |
| tsp | 2024-08 | x100 | frontier | 22.7% | -29.5% | 13.8% | 61.3% | -7.4% | -36.9% | -29.5% | 13.3% | 61.4% | -7.6% | -37.3% | 1.062 |
| tsp | 2024-09 | x25 | w_R | 3.2% | -1.4% | 5.2% | 11.4% | 1.8% | -3.1% | -1.9% | 5.2% | 11.8% | 1.6% | -3.2% | 1.881 |
| tsp | 2024-09 | x25 | frontier | 7.4% | -5.9% | 7.9% | 19.6% | 0.8% | -8.9% | -6.2% | 7.9% | 20.1% | 0.7% | -9.0% | 1.105 |
| tsp | 2024-09 | x50 | w_R | 3.2% | -1.4% | 5.2% | 11.4% | 1.8% | -3.1% | -1.9% | 5.2% | 11.8% | 1.6% | -3.2% | 1.881 |
| tsp | 2024-09 | x50 | frontier | 12.5% | -12.7% | 10.5% | 30.7% | -1.4% | -17.0% | -12.8% | 10.3% | 31.6% | -1.4% | -17.2% | 1.010 |
| tsp | 2024-09 | x100 | w_R | 3.2% | -1.4% | 5.2% | 11.4% | 1.8% | -3.1% | -1.9% | 5.2% | 11.8% | 1.6% | -3.2% | 1.881 |
| tsp | 2024-09 | x100 | frontier | 22.6% | -27.5% | 13.6% | 59.9% | -6.4% | -36.1% | -29.5% | 13.0% | 61.2% | -7.7% | -36.1% | 1.063 |
| tsp | 2024-10 | x25 | w_R | 3.0% | -1.7% | 5.1% | 11.4% | 1.6% | -2.9% | -1.8% | 4.9% | 11.4% | 1.6% | -3.3% | 1.921 |
| tsp | 2024-10 | x25 | frontier | 7.4% | -6.0% | 8.0% | 20.0% | 0.8% | -8.5% | -6.0% | 7.8% | 20.2% | 0.8% | -9.4% | 1.105 |
| tsp | 2024-10 | x50 | w_R | 3.0% | -1.7% | 5.1% | 11.4% | 1.6% | -2.9% | -1.8% | 4.9% | 11.4% | 1.6% | -3.3% | 1.921 |
| tsp | 2024-10 | x50 | frontier | 12.4% | -12.3% | 10.5% | 31.6% | -1.1% | -16.4% | -12.4% | 10.2% | 32.0% | -1.2% | -17.7% | 1.010 |
| tsp | 2024-10 | x100 | w_R | 3.0% | -1.7% | 5.1% | 11.4% | 1.6% | -2.9% | -1.8% | 4.9% | 11.4% | 1.6% | -3.3% | 1.921 |
| tsp | 2024-10 | x100 | frontier | 22.6% | -28.3% | 14.1% | 61.8% | -6.6% | -34.4% | -28.7% | 13.0% | 62.2% | -7.1% | -36.5% | 1.063 |
| tsp | 2024-11 | x25 | w_R | 2.6% | -1.4% | 4.7% | 10.5% | 1.6% | -2.7% | -1.4% | 4.6% | 10.4% | 1.6% | -2.6% | 1.981 |
| tsp | 2024-11 | x25 | frontier | 7.4% | -6.2% | 7.9% | 20.0% | 0.6% | -9.5% | -6.2% | 7.8% | 20.0% | 0.6% | -9.1% | 1.104 |
| tsp | 2024-11 | x50 | w_R | 2.6% | -1.4% | 4.7% | 10.5% | 1.6% | -2.7% | -1.4% | 4.6% | 10.4% | 1.6% | -2.6% | 1.981 |
| tsp | 2024-11 | x50 | frontier | 12.5% | -12.8% | 10.3% | 31.6% | -1.4% | -17.8% | -12.7% | 10.3% | 31.4% | -1.4% | -17.4% | 1.010 |
| tsp | 2024-11 | x100 | w_R | 2.6% | -1.4% | 4.7% | 10.5% | 1.6% | -2.7% | -1.4% | 4.6% | 10.4% | 1.6% | -2.6% | 1.981 |
| tsp | 2024-11 | x100 | frontier | 22.7% | -28.3% | 13.4% | 60.6% | -6.9% | -36.8% | -28.6% | 13.5% | 61.7% | -6.9% | -36.1% | 1.063 |
| tsp | 2024-12 | x25 | w_R | 3.3% | -2.2% | 5.0% | 11.6% | 1.3% | -3.8% | -2.3% | 5.0% | 11.8% | 1.3% | -3.8% | 1.828 |
| tsp | 2024-12 | x25 | frontier | 7.4% | -6.6% | 7.2% | 19.4% | 0.1% | -9.6% | -6.9% | 7.4% | 19.6% | 0.1% | -9.8% | 1.104 |
| tsp | 2024-12 | x50 | w_R | 3.3% | -2.2% | 5.0% | 11.6% | 1.3% | -3.8% | -2.3% | 5.0% | 11.8% | 1.3% | -3.8% | 1.828 |
| tsp | 2024-12 | x50 | frontier | 12.5% | -13.3% | 9.3% | 30.7% | -2.1% | -18.2% | -13.8% | 9.7% | 30.9% | -2.3% | -18.4% | 1.010 |
| tsp | 2024-12 | x100 | w_R | 3.3% | -2.2% | 5.0% | 11.6% | 1.3% | -3.8% | -2.3% | 5.0% | 11.8% | 1.3% | -3.8% | 1.828 |
| tsp | 2024-12 | x100 | frontier | 22.7% | -29.7% | 11.1% | 59.0% | -8.6% | -37.0% | -30.4% | 12.3% | 60.4% | -8.5% | -37.4% | 1.063 |
| tsp | 2025-01 | x25 | w_R | 3.1% | -1.8% | 4.7% | 11.3% | 1.5% | -3.3% | -2.3% | 4.8% | 11.3% | 1.2% | -3.6% | 1.898 |
| tsp | 2025-01 | x25 | frontier | 7.4% | -6.5% | 7.4% | 19.6% | 0.3% | -9.2% | -7.1% | 7.5% | 20.1% | 0.0% | -10.2% | 1.104 |
| tsp | 2025-01 | x50 | w_R | 3.1% | -1.8% | 4.7% | 11.3% | 1.5% | -3.3% | -2.3% | 4.8% | 11.3% | 1.2% | -3.6% | 1.898 |
| tsp | 2025-01 | x50 | frontier | 12.6% | -13.3% | 9.5% | 31.4% | -2.0% | -17.5% | -14.1% | 9.8% | 31.6% | -2.4% | -19.0% | 1.010 |
| tsp | 2025-01 | x100 | w_R | 3.1% | -1.8% | 4.7% | 11.3% | 1.5% | -3.3% | -2.3% | 4.8% | 11.3% | 1.2% | -3.6% | 1.898 |
| tsp | 2025-01 | x100 | frontier | 22.8% | -29.8% | 11.6% | 59.4% | -8.5% | -35.8% | -31.0% | 12.4% | 60.8% | -8.8% | -38.6% | 1.063 |
| tsp | 2025-02 | x25 | w_R | 2.5% | -1.7% | 4.2% | 10.0% | 1.2% | -2.8% | -1.6% | 4.2% | 10.0% | 1.3% | -2.8% | 1.924 |
| tsp | 2025-02 | x25 | frontier | 7.5% | -7.4% | 7.2% | 19.7% | -0.3% | -10.2% | -6.9% | 7.4% | 19.9% | 0.0% | -10.0% | 1.103 |
| tsp | 2025-02 | x50 | w_R | 2.5% | -1.7% | 4.2% | 10.0% | 1.2% | -2.8% | -1.6% | 4.2% | 10.0% | 1.3% | -2.8% | 1.924 |
| tsp | 2025-02 | x50 | frontier | 12.6% | -14.9% | 9.3% | 30.6% | -3.1% | -19.2% | -14.1% | 9.6% | 31.3% | -2.4% | -18.7% | 1.010 |
| tsp | 2025-02 | x100 | w_R | 2.5% | -1.7% | 4.2% | 10.0% | 1.2% | -2.8% | -1.6% | 4.2% | 10.0% | 1.3% | -2.8% | 1.924 |
| tsp | 2025-02 | x100 | frontier | 22.8% | -31.5% | 12.3% | 60.2% | -9.2% | -38.8% | -31.3% | 11.9% | 61.3% | -9.1% | -38.2% | 1.063 |
| tsp | 2025-03 | x25 | w_R | 5.3% | -3.2% | 6.9% | 16.4% | 1.8% | -5.1% | -3.7% | 6.6% | 16.1% | 1.4% | -5.8% | 1.355 |
| tsp | 2025-03 | x25 | frontier | 7.3% | -4.9% | 8.1% | 20.1% | 1.5% | -7.1% | -5.2% | 7.8% | 20.1% | 1.2% | -7.9% | 1.097 |
| tsp | 2025-03 | x50 | w_R | 5.3% | -3.2% | 6.9% | 16.4% | 1.8% | -5.1% | -3.7% | 6.6% | 16.1% | 1.4% | -5.8% | 1.355 |
| tsp | 2025-03 | x50 | frontier | 12.3% | -10.3% | 10.9% | 32.3% | 0.3% | -14.0% | -11.0% | 10.2% | 31.6% | -0.4% | -15.2% | 1.011 |
| tsp | 2025-03 | x100 | w_R | 5.3% | -3.2% | 6.9% | 16.4% | 1.8% | -5.1% | -3.7% | 6.6% | 16.1% | 1.4% | -5.8% | 1.355 |
| tsp | 2025-03 | x100 | frontier | 22.2% | -25.7% | 14.2% | 61.9% | -4.9% | -31.0% | -26.1% | 13.2% | 61.2% | -5.6% | -32.3% | 1.064 |
| tsp | 2025-04 | x25 | w_R | 6.8% | -3.2% | 8.4% | 20.1% | 2.6% | -5.3% | -3.8% | 8.3% | 20.0% | 2.2% | -6.3% | 1.071 |
| tsp | 2025-04 | x25 | frontier | 6.9% | -3.5% | 8.5% | 20.4% | 2.5% | -5.6% | -4.1% | 8.4% | 20.8% | 2.2% | -6.5% | 1.099 |
| tsp | 2025-04 | x50 | w_R | 7.2% | -3.5% | 8.7% | 21.0% | 2.6% | -5.7% | -4.1% | 8.6% | 21.0% | 2.2% | -6.7% | 1.027 |
| tsp | 2025-04 | x50 | frontier | 11.6% | -8.5% | 11.3% | 32.7% | 1.5% | -11.8% | -9.4% | 11.2% | 33.5% | 1.0% | -13.4% | 1.079 |
| tsp | 2025-04 | x100 | w_R | 7.2% | -3.5% | 8.7% | 21.0% | 2.6% | -5.7% | -4.1% | 8.6% | 21.0% | 2.2% | -6.7% | 1.027 |
| tsp | 2025-04 | x100 | frontier | 21.0% | -21.5% | 14.6% | 63.2% | -2.2% | -26.6% | -21.7% | 14.1% | 63.9% | -2.4% | -28.2% | 1.056 |
| tsp | 2025-05 | x25 | w_R | 4.8% | -2.6% | 6.9% | 15.5% | 2.0% | -4.5% | -2.5% | 6.8% | 15.3% | 2.1% | -4.4% | 1.337 |
| tsp | 2025-05 | x25 | frontier | 6.6% | -4.4% | 8.1% | 20.3% | 1.8% | -6.6% | -4.1% | 8.3% | 20.2% | 2.0% | -6.4% | 1.136 |
| tsp | 2025-05 | x50 | w_R | 4.8% | -2.6% | 6.9% | 15.5% | 2.0% | -4.5% | -2.5% | 6.8% | 15.3% | 2.1% | -4.4% | 1.337 |
| tsp | 2025-05 | x50 | frontier | 10.9% | -9.7% | 10.8% | 32.1% | 0.6% | -13.0% | -9.2% | 11.0% | 31.5% | 0.9% | -12.8% | 1.090 |
| tsp | 2025-05 | x100 | w_R | 4.8% | -2.6% | 6.9% | 15.5% | 2.0% | -4.5% | -2.5% | 6.8% | 15.3% | 2.1% | -4.4% | 1.337 |
| tsp | 2025-05 | x100 | frontier | 19.5% | -20.7% | 14.3% | 58.9% | -2.3% | -25.9% | -20.2% | 14.6% | 55.9% | -2.2% | -25.9% | 1.063 |
| tsp | 2025-06 | x25 | w_R | 5.8% | -2.4% | 7.2% | 17.0% | 2.4% | -5.0% | -3.8% | 7.1% | 16.9% | 1.6% | -5.7% | 1.178 |
| tsp | 2025-06 | x25 | frontier | 6.5% | -3.3% | 7.6% | 18.9% | 2.2% | -5.9% | -4.6% | 7.6% | 18.8% | 1.4% | -6.7% | 1.120 |
| tsp | 2025-06 | x50 | w_R | 5.7% | -2.4% | 7.2% | 16.8% | 2.4% | -4.9% | -3.7% | 7.1% | 16.7% | 1.6% | -5.7% | 1.187 |
| tsp | 2025-06 | x50 | frontier | 10.8% | -7.9% | 10.0% | 29.1% | 1.2% | -11.7% | -9.6% | 10.0% | 28.8% | 0.1% | -12.9% | 1.026 |
| tsp | 2025-06 | x100 | w_R | 5.7% | -2.4% | 7.2% | 16.8% | 2.4% | -4.9% | -3.7% | 7.1% | 16.7% | 1.6% | -5.7% | 1.187 |
| tsp | 2025-06 | x100 | frontier | 19.3% | -19.0% | 12.0% | 52.0% | -2.6% | -24.3% | -21.1% | 12.5% | 52.2% | -3.7% | -26.6% | 1.064 |
| tsp | 2025-07 | x25 | w_R | 6.2% | -3.7% | 8.2% | 18.7% | 2.1% | -6.1% | -3.9% | 7.8% | 19.0% | 1.9% | -6.4% | 1.172 |
| tsp | 2025-07 | x25 | frontier | 6.4% | -4.0% | 8.3% | 19.1% | 2.0% | -6.2% | -4.0% | 8.0% | 19.5% | 2.0% | -6.4% | 1.116 |
| tsp | 2025-07 | x50 | w_R | 6.4% | -3.7% | 8.3% | 19.2% | 2.2% | -6.2% | -3.9% | 7.9% | 19.4% | 2.0% | -6.5% | 1.138 |
| tsp | 2025-07 | x50 | frontier | 10.6% | -8.7% | 11.0% | 29.2% | 1.0% | -12.0% | -8.6% | 10.7% | 30.0% | 1.0% | -12.4% | 1.024 |
| tsp | 2025-07 | x100 | w_R | 6.4% | -3.7% | 8.3% | 19.2% | 2.2% | -6.2% | -3.9% | 7.9% | 19.4% | 2.0% | -6.5% | 1.138 |
| tsp | 2025-07 | x100 | frontier | 18.9% | -20.1% | 14.3% | 52.9% | -2.5% | -24.8% | -19.5% | 13.8% | 54.2% | -2.2% | -25.6% | 1.066 |
| tsp | 2025-08 | x25 | w_R | 4.7% | -2.5% | 6.5% | 15.0% | 2.0% | -4.4% | -2.8% | 6.5% | 15.1% | 1.8% | -4.6% | 1.366 |
| tsp | 2025-08 | x25 | frontier | 6.4% | -4.0% | 7.7% | 18.9% | 1.8% | -6.1% | -4.1% | 7.8% | 19.1% | 1.8% | -6.5% | 1.123 |
| tsp | 2025-08 | x50 | w_R | 4.7% | -2.5% | 6.5% | 15.0% | 2.0% | -4.4% | -2.8% | 6.5% | 15.1% | 1.8% | -4.6% | 1.366 |
| tsp | 2025-08 | x50 | frontier | 10.6% | -8.8% | 10.0% | 29.0% | 0.6% | -12.0% | -8.8% | 10.1% | 29.1% | 0.6% | -12.4% | 1.058 |
| tsp | 2025-08 | x100 | w_R | 4.7% | -2.5% | 6.5% | 15.0% | 2.0% | -4.4% | -2.8% | 6.5% | 15.1% | 1.8% | -4.6% | 1.366 |
| tsp | 2025-08 | x100 | frontier | 18.9% | -20.9% | 13.0% | 52.7% | -3.4% | -25.4% | -20.3% | 12.9% | 52.4% | -3.1% | -25.4% | 1.066 |
| tsp | 2025-09 | x25 | w_R | 5.9% | -3.8% | 7.9% | 18.2% | 1.9% | -5.7% | -3.4% | 7.9% | 18.0% | 2.1% | -5.9% | 1.145 |
| tsp | 2025-09 | x25 | frontier | 6.4% | -4.4% | 8.2% | 19.8% | 1.8% | -6.6% | -4.0% | 8.3% | 19.7% | 2.1% | -6.6% | 1.119 |
| tsp | 2025-09 | x50 | w_R | 5.9% | -3.8% | 7.9% | 18.2% | 1.9% | -5.7% | -3.4% | 7.9% | 18.0% | 2.1% | -5.9% | 1.145 |
| tsp | 2025-09 | x50 | frontier | 10.5% | -9.2% | 10.9% | 30.6% | 0.8% | -12.5% | -8.5% | 10.9% | 30.1% | 1.2% | -12.6% | 1.059 |
| tsp | 2025-09 | x100 | w_R | 5.9% | -3.8% | 7.9% | 18.2% | 1.9% | -5.7% | -3.4% | 7.9% | 18.0% | 2.1% | -5.9% | 1.145 |
| tsp | 2025-09 | x100 | frontier | 18.8% | -20.6% | 14.1% | 55.2% | -2.6% | -25.1% | -19.6% | 14.2% | 55.4% | -2.0% | -25.5% | 1.067 |
| tsp | 2025-10 | x25 | w_R | 3.6% | -1.8% | 5.8% | 12.7% | 1.9% | -3.3% | -2.0% | 5.8% | 12.6% | 1.8% | -3.5% | 1.600 |
| tsp | 2025-10 | x25 | frontier | 6.4% | -4.6% | 7.8% | 19.1% | 1.5% | -6.4% | -4.2% | 8.0% | 19.3% | 1.8% | -6.3% | 1.115 |
| tsp | 2025-10 | x50 | w_R | 3.6% | -1.8% | 5.8% | 12.7% | 1.9% | -3.3% | -2.0% | 5.8% | 12.6% | 1.8% | -3.5% | 1.600 |
| tsp | 2025-10 | x50 | frontier | 10.5% | -9.6% | 10.2% | 29.1% | 0.2% | -12.4% | -9.0% | 10.5% | 29.7% | 0.7% | -12.2% | 1.061 |
| tsp | 2025-10 | x100 | w_R | 3.6% | -1.8% | 5.8% | 12.7% | 1.9% | -3.3% | -2.0% | 5.8% | 12.6% | 1.8% | -3.5% | 1.600 |
| tsp | 2025-10 | x100 | frontier | 18.7% | -20.6% | 13.1% | 52.6% | -3.2% | -25.2% | -20.3% | 13.3% | 53.0% | -2.9% | -25.3% | 1.067 |
| tsp | 2025-11 | x25 | w_R | 6.4% | -3.6% | 8.1% | 19.6% | 2.2% | -6.1% | -4.0% | 8.1% | 19.3% | 1.9% | -6.3% | 1.110 |
| tsp | 2025-11 | x25 | frontier | 6.4% | -3.6% | 8.1% | 19.6% | 2.2% | -6.1% | -4.0% | 8.1% | 19.3% | 1.9% | -6.3% | 1.110 |
| tsp | 2025-11 | x50 | w_R | 6.7% | -3.7% | 8.3% | 19.9% | 2.3% | -6.5% | -4.2% | 8.3% | 19.8% | 1.9% | -6.6% | 1.041 |
| tsp | 2025-11 | x50 | frontier | 10.5% | -8.4% | 10.5% | 30.4% | 1.2% | -12.1% | -8.9% | 10.6% | 29.7% | 0.8% | -12.4% | 1.074 |
| tsp | 2025-11 | x100 | w_R | 6.7% | -3.7% | 8.3% | 19.9% | 2.3% | -6.5% | -4.2% | 8.3% | 19.8% | 1.9% | -6.6% | 1.041 |
| tsp | 2025-11 | x100 | frontier | 18.6% | -19.3% | 13.4% | 52.3% | -2.3% | -25.1% | -19.9% | 13.7% | 52.9% | -2.6% | -25.2% | 1.067 |
| tsp | 2025-12 | x25 | w_R | 3.3% | -1.9% | 5.0% | 12.0% | 1.6% | -3.4% | -2.1% | 5.2% | 11.6% | 1.4% | -3.6% | 1.678 |
| tsp | 2025-12 | x25 | frontier | 6.4% | -4.6% | 6.9% | 18.4% | 1.1% | -7.1% | -4.4% | 7.4% | 18.2% | 1.4% | -6.9% | 1.107 |
| tsp | 2025-12 | x50 | w_R | 3.3% | -1.9% | 5.0% | 12.0% | 1.6% | -3.4% | -2.1% | 5.2% | 11.6% | 1.4% | -3.6% | 1.678 |
| tsp | 2025-12 | x50 | frontier | 10.4% | -9.8% | 9.0% | 28.3% | -0.4% | -13.3% | -8.9% | 9.4% | 27.5% | 0.2% | -13.0% | 1.029 |
| tsp | 2025-12 | x100 | w_R | 3.3% | -1.9% | 5.0% | 12.0% | 1.6% | -3.4% | -2.1% | 5.2% | 11.6% | 1.4% | -3.6% | 1.678 |
| tsp | 2025-12 | x100 | frontier | 18.6% | -21.0% | 10.7% | 48.0% | -4.6% | -26.5% | -20.7% | 11.1% | 47.6% | -4.3% | -26.2% | 1.066 |
| tsp | 2026-01 | x25 | w_R | 5.0% | -3.0% | 6.5% | 15.4% | 1.7% | -5.1% | -3.3% | 6.4% | 15.3% | 1.4% | -5.3% | 1.288 |
| tsp | 2026-01 | x25 | frontier | 6.4% | -4.1% | 7.3% | 18.5% | 1.6% | -6.5% | -4.4% | 7.2% | 18.1% | 1.3% | -6.7% | 1.106 |
| tsp | 2026-01 | x50 | w_R | 5.0% | -3.0% | 6.5% | 15.4% | 1.7% | -5.1% | -3.3% | 6.4% | 15.3% | 1.4% | -5.3% | 1.288 |
| tsp | 2026-01 | x50 | frontier | 10.4% | -8.7% | 9.3% | 28.0% | 0.4% | -12.6% | -9.4% | 9.1% | 27.5% | -0.2% | -12.8% | 1.046 |
| tsp | 2026-01 | x100 | w_R | 5.0% | -3.0% | 6.5% | 15.4% | 1.7% | -5.1% | -3.3% | 6.4% | 15.3% | 1.4% | -5.3% | 1.288 |
| tsp | 2026-01 | x100 | frontier | 18.6% | -20.6% | 10.6% | 47.0% | -4.4% | -25.2% | -20.7% | 10.3% | 46.6% | -4.7% | -25.8% | 1.065 |
| tsp | 2026-02 | x25 | w_R | 5.0% | -2.9% | 6.4% | 15.5% | 1.7% | -4.9% | -3.4% | 6.2% | 15.2% | 1.3% | -5.2% | 1.302 |
| tsp | 2026-02 | x25 | frontier | 5.5% | -3.6% | 6.7% | 16.7% | 1.5% | -5.7% | -4.0% | 6.6% | 16.7% | 1.2% | -6.0% | 1.233 |
| tsp | 2026-02 | x50 | w_R | 5.1% | -3.0% | 6.5% | 15.7% | 1.7% | -5.1% | -3.5% | 6.3% | 15.4% | 1.3% | -5.4% | 1.289 |
| tsp | 2026-02 | x50 | frontier | 8.7% | -7.3% | 8.4% | 24.1% | 0.5% | -10.3% | -7.9% | 8.2% | 24.2% | 0.1% | -10.8% | 1.138 |
| tsp | 2026-02 | x100 | w_R | 5.1% | -3.0% | 6.5% | 15.7% | 1.7% | -5.1% | -3.5% | 6.3% | 15.4% | 1.3% | -5.4% | 1.289 |
| tsp | 2026-02 | x100 | frontier | 15.1% | -15.4% | 11.2% | 40.7% | -1.8% | -19.9% | -16.2% | 10.9% | 41.0% | -2.4% | -20.7% | 1.125 |
| tsp | 2026-03 | x25 | w_R | 2.9% | -1.8% | 4.4% | 10.4% | 1.3% | -3.1% | -2.1% | 4.5% | 10.5% | 1.1% | -3.5% | 1.799 |
| tsp | 2026-03 | x25 | frontier | 5.5% | -4.1% | 6.1% | 16.0% | 1.0% | -6.1% | -4.4% | 6.2% | 16.4% | 0.9% | -6.7% | 1.223 |
| tsp | 2026-03 | x50 | w_R | 2.9% | -1.8% | 4.4% | 10.4% | 1.3% | -3.1% | -2.1% | 4.5% | 10.5% | 1.1% | -3.5% | 1.799 |
| tsp | 2026-03 | x50 | frontier | 8.8% | -7.7% | 7.5% | 22.9% | -0.1% | -10.6% | -8.4% | 7.6% | 23.3% | -0.4% | -11.5% | 1.056 |
| tsp | 2026-03 | x100 | w_R | 2.9% | -1.8% | 4.4% | 10.4% | 1.3% | -3.1% | -2.1% | 4.5% | 10.5% | 1.1% | -3.5% | 1.799 |
| tsp | 2026-03 | x100 | frontier | 15.2% | -16.8% | 9.4% | 39.1% | -3.4% | -21.7% | -17.5% | 9.7% | 40.8% | -3.5% | -22.6% | 1.125 |
| tsp | 2026-04 | x25 | w_R | 3.9% | -2.8% | 5.4% | 13.0% | 1.3% | -4.6% | -2.8% | 5.5% | 12.9% | 1.3% | -4.2% | 1.542 |
| tsp | 2026-04 | x25 | frontier | 5.6% | -4.5% | 6.4% | 16.3% | 0.9% | -6.3% | -4.2% | 6.6% | 16.8% | 1.1% | -6.1% | 1.228 |
| tsp | 2026-04 | x50 | w_R | 3.9% | -2.8% | 5.4% | 13.0% | 1.3% | -4.6% | -2.8% | 5.5% | 12.9% | 1.3% | -4.2% | 1.542 |
| tsp | 2026-04 | x50 | frontier | 8.8% | -8.4% | 8.0% | 23.3% | -0.3% | -11.1% | -8.0% | 8.2% | 24.3% | 0.1% | -10.8% | 1.088 |
| tsp | 2026-04 | x100 | w_R | 3.9% | -2.8% | 5.4% | 13.0% | 1.3% | -4.6% | -2.8% | 5.5% | 12.9% | 1.3% | -4.2% | 1.542 |
| tsp | 2026-04 | x100 | frontier | 15.3% | -17.5% | 10.4% | 40.9% | -3.3% | -21.7% | -16.8% | 10.9% | 42.2% | -2.6% | -21.2% | 1.125 |
| tsp | 2026-05 | x25 | w_R | 4.7% | -2.8% | 6.1% | 14.9% | 1.6% | -4.7% | -3.4% | 6.2% | 15.1% | 1.3% | -5.3% | 1.339 |
| tsp | 2026-05 | x25 | frontier | 6.4% | -4.1% | 7.2% | 18.6% | 1.5% | -6.4% | -5.0% | 7.3% | 18.9% | 1.1% | -7.3% | 1.113 |
| tsp | 2026-05 | x50 | w_R | 4.7% | -2.8% | 6.1% | 14.9% | 1.6% | -4.7% | -3.4% | 6.2% | 15.1% | 1.3% | -5.3% | 1.339 |
| tsp | 2026-05 | x50 | frontier | 10.4% | -9.0% | 9.1% | 28.7% | 0.2% | -12.5% | -10.3% | 9.3% | 29.2% | -0.5% | -13.9% | 1.092 |
| tsp | 2026-05 | x100 | w_R | 4.7% | -2.8% | 6.1% | 14.9% | 1.6% | -4.7% | -3.4% | 6.2% | 15.1% | 1.3% | -5.3% | 1.339 |
| tsp | 2026-05 | x100 | frontier | 18.5% | -19.9% | 10.7% | 48.6% | -3.8% | -24.5% | -21.7% | 11.0% | 49.4% | -4.8% | -27.0% | 1.062 |
| tsp | 2026-06 | x25 | w_R | 4.6% | -3.0% | 5.8% | 14.3% | 1.4% | -4.9% | -3.2% | 5.9% | 14.4% | 1.3% | -5.0% | 1.347 |
| tsp | 2026-06 | x25 | frontier | 6.4% | -4.7% | 6.9% | 18.6% | 1.1% | -6.9% | -4.7% | 7.0% | 18.7% | 1.2% | -7.1% | 1.116 |
| tsp | 2026-06 | x50 | w_R | 4.6% | -3.0% | 5.8% | 14.3% | 1.4% | -4.9% | -3.2% | 5.9% | 14.4% | 1.3% | -5.0% | 1.347 |
| tsp | 2026-06 | x50 | frontier | 10.4% | -9.7% | 8.7% | 28.6% | -0.3% | -13.0% | -9.9% | 8.9% | 28.5% | -0.4% | -13.4% | 1.065 |
| tsp | 2026-06 | x100 | w_R | 4.6% | -3.0% | 5.8% | 14.3% | 1.4% | -4.9% | -3.2% | 5.9% | 14.4% | 1.3% | -5.0% | 1.347 |
| tsp | 2026-06 | x100 | frontier | 18.6% | -20.9% | 9.9% | 47.7% | -4.8% | -25.7% | -21.1% | 10.6% | 48.0% | -4.7% | -26.4% | 1.061 |
| tsp | 2026-07 | x25 | w_R | 4.5% | -2.9% | 5.6% | 14.4% | 1.4% | -4.8% | -3.4% | 5.8% | 14.1% | 1.1% | -5.1% | 1.352 |
| tsp | 2026-07 | x25 | frontier | 5.6% | -3.8% | 6.3% | 17.2% | 1.3% | -6.2% | -4.5% | 6.6% | 16.9% | 1.0% | -6.4% | 1.229 |
| tsp | 2026-07 | x50 | w_R | 5.0% | -3.2% | 5.9% | 15.4% | 1.4% | -5.3% | -3.8% | 6.1% | 15.2% | 1.1% | -5.6% | 1.286 |
| tsp | 2026-07 | x50 | frontier | 8.9% | -7.7% | 7.9% | 25.1% | 0.3% | -10.9% | -8.5% | 8.1% | 24.5% | -0.2% | -11.4% | 1.105 |
| tsp | 2026-07 | x100 | w_R | 5.0% | -3.2% | 5.9% | 15.4% | 1.4% | -5.3% | -3.8% | 6.1% | 15.2% | 1.1% | -5.6% | 1.286 |
| tsp | 2026-07 | x100 | frontier | 15.5% | -16.0% | 10.1% | 43.6% | -2.2% | -21.3% | -17.5% | 10.8% | 42.0% | -3.1% | -21.9% | 1.123 |
| tsp | 2026-08 | x25 | w_R | 3.3% | -2.1% | 4.9% | 11.6% | 1.4% | -3.8% | -2.3% | 5.0% | 11.6% | 1.3% | -3.6% | 1.666 |
| tsp | 2026-08 | x25 | frontier | 5.6% | -4.5% | 6.6% | 17.5% | 1.0% | -6.9% | -4.3% | 6.6% | 17.2% | 1.1% | -6.2% | 1.230 |
| tsp | 2026-08 | x50 | w_R | 3.3% | -2.1% | 4.9% | 11.6% | 1.4% | -3.8% | -2.3% | 5.0% | 11.6% | 1.3% | -3.6% | 1.666 |
| tsp | 2026-08 | x50 | frontier | 8.9% | -8.5% | 8.0% | 25.2% | -0.2% | -11.9% | -8.4% | 8.3% | 25.1% | -0.0% | -11.0% | 1.116 |
| tsp | 2026-08 | x100 | w_R | 3.3% | -2.1% | 4.9% | 11.6% | 1.4% | -3.8% | -2.3% | 5.0% | 11.6% | 1.3% | -3.6% | 1.666 |
| tsp | 2026-08 | x100 | frontier | 15.5% | -17.5% | 10.9% | 43.4% | -2.9% | -22.8% | -17.1% | 11.0% | 43.1% | -2.6% | -21.3% | 1.124 |
| tsp | 2026-09 | x25 | w_R | 5.0% | -3.8% | 5.8% | 15.9% | 1.0% | -6.0% | -4.0% | 6.0% | 15.2% | 0.9% | -5.9% | 1.316 |
| tsp | 2026-09 | x25 | frontier | 5.6% | -4.5% | 6.1% | 17.3% | 0.9% | -6.7% | -4.5% | 6.4% | 16.6% | 0.9% | -6.6% | 1.224 |
| tsp | 2026-09 | x50 | w_R | 5.0% | -3.8% | 5.7% | 15.7% | 1.0% | -5.9% | -4.0% | 6.0% | 15.0% | 0.9% | -5.8% | 1.329 |
| tsp | 2026-09 | x50 | frontier | 8.9% | -8.8% | 7.5% | 24.9% | -0.5% | -11.6% | -8.4% | 7.9% | 23.9% | -0.3% | -11.5% | 1.081 |
| tsp | 2026-09 | x100 | w_R | 5.0% | -3.8% | 5.7% | 15.7% | 1.0% | -5.9% | -4.0% | 6.0% | 15.0% | 0.9% | -5.8% | 1.329 |
| tsp | 2026-09 | x100 | frontier | 15.5% | -17.6% | 9.4% | 43.8% | -3.4% | -22.6% | -17.5% | 10.2% | 41.7% | -3.2% | -22.2% | 1.123 |

## Appendix B: R+D selections per origin and ceiling (primary seed)

| menu | month | ceiling | U sacrifice (bp) | binding guards | DR² w_R | DR² R+D | DR² pool max | DR² MDP |
|---|---|---|---|---|---|---|---|---|
| example | 2018-06 | x25 | +0.29 | none | 2.364 | 2.366 | 3.315 | 3.854 |
| example | 2018-06 | x50 | +1.90 | none | 2.450 | 2.499 | 3.315 | 3.603 |
| example | 2018-06 | x100 | +0.91 | none | 2.404 | 2.410 | 3.315 | 2.637 |
| example | 2018-07 | x25 | +0.36 | none | 2.981 | 2.987 | 3.369 | 3.871 |
| example | 2018-07 | x50 | +2.17 | none | 2.744 | 2.761 | 3.369 | 3.613 |
| example | 2018-07 | x100 | +0.06 | none | 2.740 | 2.740 | 3.369 | 2.634 |
| example | 2018-08 | x25 | +1.26 | none | 2.388 | 2.411 | 3.335 | 3.910 |
| example | 2018-08 | x50 | +1.03 | none | 2.572 | 2.656 | 3.335 | 3.642 |
| example | 2018-08 | x100 | +1.95 | none | 2.609 | 2.624 | 3.335 | 2.640 |
| example | 2018-09 | x25 | +0.00 | none | 2.441 | 2.441 | 3.781 | 3.916 |
| example | 2018-09 | x50 | +0.53 | none | 2.561 | 2.583 | 3.781 | 3.650 |
| example | 2018-09 | x100 | +1.96 | none | 2.624 | 2.627 | 3.781 | 2.643 |
| example | 2018-10 | x25 | +0.89 | none | 3.296 | 3.391 | 3.749 | 3.926 |
| example | 2018-10 | x50 | +0.89 | none | 3.296 | 3.391 | 3.749 | 3.645 |
| example | 2018-10 | x100 | +0.89 | none | 3.296 | 3.391 | 3.749 | 2.618 |
| example | 2018-11 | x25 | +1.42 | none | 3.027 | 3.356 | 3.391 | 3.945 |
| example | 2018-11 | x50 | +1.42 | none | 3.027 | 3.356 | 3.391 | 3.653 |
| example | 2018-11 | x100 | +1.42 | none | 3.027 | 3.356 | 3.391 | 2.610 |
| example | 2018-12 | x25 | +2.14 | none | 3.325 | 3.397 | 3.842 | 4.070 |
| example | 2018-12 | x50 | +2.14 | none | 3.325 | 3.397 | 3.842 | 3.939 |
| example | 2018-12 | x100 | +2.14 | none | 3.325 | 3.397 | 3.842 | 3.474 |
| example | 2019-01 | x25 | +1.71 | none | 3.191 | 3.231 | 3.526 | 4.000 |
| example | 2019-01 | x50 | +1.71 | none | 3.191 | 3.231 | 3.526 | 3.670 |
| example | 2019-01 | x100 | +1.71 | none | 3.191 | 3.231 | 3.526 | 2.606 |
| example | 2019-02 | x25 | +0.12 | none | 3.275 | 3.276 | 3.779 | 3.982 |
| example | 2019-02 | x50 | +0.12 | none | 3.275 | 3.276 | 3.779 | 3.657 |
| example | 2019-02 | x100 | +0.12 | none | 3.275 | 3.276 | 3.779 | 2.604 |
| example | 2019-03 | x25 | +1.23 | none | 3.214 | 3.356 | 3.569 | 3.961 |
| example | 2019-03 | x50 | +1.23 | none | 3.214 | 3.356 | 3.569 | 3.637 |
| example | 2019-03 | x100 | +1.23 | none | 3.214 | 3.356 | 3.569 | 2.591 |
| example | 2019-04 | x25 | +1.42 | none | 3.168 | 3.237 | 3.371 | 3.941 |
| example | 2019-04 | x50 | +1.42 | none | 3.168 | 3.237 | 3.371 | 3.622 |
| example | 2019-04 | x100 | +1.42 | none | 3.168 | 3.237 | 3.371 | 2.582 |
| example | 2019-05 | x25 | +2.45 | none | 3.185 | 3.329 | 3.822 | 3.961 |
| example | 2019-05 | x50 | +2.45 | none | 3.185 | 3.329 | 3.822 | 3.625 |
| example | 2019-05 | x100 | +2.45 | none | 3.185 | 3.329 | 3.822 | 2.568 |
| example | 2019-06 | x25 | +2.39 | none | 3.127 | 3.264 | 3.806 | 3.951 |
| example | 2019-06 | x50 | +2.39 | none | 3.127 | 3.264 | 3.806 | 3.611 |
| example | 2019-06 | x100 | +2.39 | none | 3.127 | 3.264 | 3.806 | 2.561 |
| example | 2019-07 | x25 | +1.44 | none | 3.239 | 3.293 | 3.795 | 3.937 |
| example | 2019-07 | x50 | +1.44 | none | 3.239 | 3.293 | 3.795 | 3.600 |
| example | 2019-07 | x100 | +1.44 | none | 3.239 | 3.293 | 3.795 | 2.556 |
| example | 2019-08 | x25 | +1.23 | none | 3.381 | 3.410 | 3.484 | 4.037 |
| example | 2019-08 | x50 | +1.23 | none | 3.381 | 3.410 | 4.037 | 3.725 |
| example | 2019-08 | x100 | +1.23 | none | 3.381 | 3.410 | 4.037 | 2.554 |
| example | 2019-09 | x25 | +2.09 | none | 3.285 | 3.331 | 3.572 | 4.050 |
| example | 2019-09 | x50 | +2.09 | none | 3.285 | 3.331 | 3.572 | 3.741 |
| example | 2019-09 | x100 | +2.09 | none | 3.285 | 3.331 | 3.572 | 2.562 |
| example | 2019-10 | x25 | +1.58 | none | 3.330 | 3.344 | 3.794 | 4.009 |
| example | 2019-10 | x50 | +1.58 | none | 3.330 | 3.344 | 3.794 | 3.645 |
| example | 2019-10 | x100 | +1.58 | none | 3.330 | 3.344 | 3.794 | 2.561 |
| example | 2019-11 | x25 | +1.72 | none | 3.318 | 3.445 | 3.816 | 4.026 |
| example | 2019-11 | x50 | +1.72 | none | 3.318 | 3.445 | 3.816 | 3.656 |
| example | 2019-11 | x100 | +1.72 | none | 3.318 | 3.445 | 3.816 | 2.567 |
| example | 2019-12 | x25 | +2.50 | none | 3.330 | 3.532 | 3.592 | 4.002 |
| example | 2019-12 | x50 | +2.50 | none | 3.330 | 3.532 | 3.592 | 3.636 |
| example | 2019-12 | x100 | +2.50 | none | 3.330 | 3.532 | 3.592 | 2.571 |
| example | 2020-01 | x25 | +2.08 | none | 3.291 | 3.360 | 3.513 | 3.992 |
| example | 2020-01 | x50 | +2.08 | none | 3.291 | 3.360 | 3.513 | 3.653 |
| example | 2020-01 | x100 | +2.08 | none | 3.291 | 3.360 | 3.513 | 2.552 |
| example | 2020-02 | x25 | +1.32 | none | 3.504 | 3.519 | 3.852 | 4.040 |
| example | 2020-02 | x50 | +1.32 | none | 3.504 | 3.519 | 3.852 | 3.667 |
| example | 2020-02 | x100 | +1.32 | none | 3.504 | 3.519 | 3.852 | 2.539 |
| example | 2020-03 | x25 | +0.03 | none | 2.415 | 2.416 | 3.398 | 3.845 |
| example | 2020-03 | x50 | +0.03 | none | 2.415 | 2.416 | 3.398 | 3.792 |
| example | 2020-03 | x100 | +0.03 | none | 2.415 | 2.416 | 3.398 | 3.283 |
| example | 2020-04 | x25 | +0.00 | none | 2.445 | 2.445 | 3.362 | 3.875 |
| example | 2020-04 | x50 | +0.00 | none | 2.445 | 2.445 | 3.362 | 3.660 |
| example | 2020-04 | x100 | +0.00 | none | 2.445 | 2.445 | 3.362 | 2.546 |
| example | 2020-05 | x25 | +2.06 | none | 3.165 | 3.220 | 3.845 | 3.845 |
| example | 2020-05 | x50 | +2.06 | none | 3.165 | 3.220 | 3.845 | 3.344 |
| example | 2020-05 | x100 | +2.06 | none | 3.165 | 3.220 | 3.845 | 1.378 |
| example | 2020-06 | x25 | +2.39 | none | 2.572 | 2.601 | 3.402 | 3.873 |
| example | 2020-06 | x50 | +2.39 | none | 2.572 | 2.601 | 3.402 | 3.291 |
| example | 2020-06 | x100 | +2.39 | none | 2.572 | 2.601 | 3.402 | 1.358 |
| example | 2020-07 | x25 | +1.75 | none | 2.149 | 2.203 | 3.361 | 3.865 |
| example | 2020-07 | x50 | +1.75 | none | 2.149 | 2.203 | 3.361 | 3.280 |
| example | 2020-07 | x100 | +1.75 | none | 2.149 | 2.203 | 3.361 | 1.364 |
| example | 2020-08 | x25 | +2.41 | none | 3.091 | 3.104 | 3.406 | 3.883 |
| example | 2020-08 | x50 | +2.41 | none | 3.091 | 3.104 | 3.406 | 3.302 |
| example | 2020-08 | x100 | +2.41 | none | 3.091 | 3.104 | 3.406 | 1.370 |
| example | 2020-09 | x25 | +0.00 | none | 3.017 | 3.017 | 3.377 | 3.833 |
| example | 2020-09 | x50 | +2.36 | none | 3.040 | 3.066 | 3.377 | 3.263 |
| example | 2020-09 | x100 | +2.36 | none | 3.040 | 3.066 | 3.377 | 1.364 |
| example | 2020-10 | x25 | +1.47 | none | 3.328 | 3.331 | 3.385 | 3.842 |
| example | 2020-10 | x50 | +1.47 | none | 3.328 | 3.331 | 3.385 | 3.258 |
| example | 2020-10 | x100 | +1.47 | none | 3.328 | 3.331 | 3.385 | 1.361 |
| example | 2020-11 | x25 | +0.15 | none | 3.222 | 3.222 | 3.391 | 3.821 |
| example | 2020-11 | x50 | +0.15 | none | 3.222 | 3.222 | 3.391 | 3.115 |
| example | 2020-11 | x100 | +0.15 | none | 3.222 | 3.222 | 3.391 | 1.261 |
| example | 2020-12 | x25 | +0.12 | none | 3.133 | 3.158 | 3.852 | 3.852 |
| example | 2020-12 | x50 | +0.12 | none | 3.133 | 3.158 | 3.852 | 3.115 |
| example | 2020-12 | x100 | +0.12 | none | 3.133 | 3.158 | 3.852 | 1.263 |
| example | 2021-01 | x25 | +1.99 | none | 2.468 | 2.479 | 3.400 | 3.837 |
| example | 2021-01 | x50 | +0.15 | none | 2.828 | 2.830 | 3.400 | 3.111 |
| example | 2021-01 | x100 | +0.15 | none | 2.828 | 2.830 | 3.400 | 1.262 |
| example | 2021-02 | x25 | +0.00 | none | 3.062 | 3.062 | 3.385 | 3.810 |
| example | 2021-02 | x50 | +0.00 | none | 3.123 | 3.123 | 3.385 | 3.106 |
| example | 2021-02 | x100 | +0.00 | none | 3.123 | 3.123 | 3.385 | 1.258 |
| example | 2021-03 | x25 | +1.94 | none | 3.022 | 3.268 | 3.407 | 3.773 |
| example | 2021-03 | x50 | +0.83 | none | 2.799 | 2.806 | 3.407 | 2.954 |
| example | 2021-03 | x100 | +0.83 | none | 2.799 | 2.806 | 3.407 | 1.161 |
| example | 2021-04 | x25 | +0.01 | none | 2.807 | 2.807 | 3.738 | 3.738 |
| example | 2021-04 | x50 | +1.76 | none | 2.842 | 2.859 | 3.738 | 2.924 |
| example | 2021-04 | x100 | +1.76 | none | 2.842 | 2.859 | 3.738 | 1.161 |
| example | 2021-05 | x25 | +0.95 | none | 2.649 | 2.665 | 3.327 | 3.689 |
| example | 2021-05 | x50 | +2.18 | none | 2.519 | 2.552 | 3.327 | 2.902 |
| example | 2021-05 | x100 | +2.18 | none | 2.519 | 2.552 | 3.327 | 1.160 |
| example | 2021-06 | x25 | +1.23 | none | 2.674 | 2.682 | 3.247 | 3.653 |
| example | 2021-06 | x50 | +0.09 | none | 2.391 | 2.391 | 3.247 | 2.889 |
| example | 2021-06 | x100 | +0.09 | none | 2.391 | 2.391 | 3.247 | 1.165 |
| example | 2021-07 | x25 | +0.00 | none | 2.878 | 2.878 | 3.247 | 3.658 |
| example | 2021-07 | x50 | +0.00 | none | 2.950 | 2.950 | 3.247 | 2.887 |
| example | 2021-07 | x100 | +0.00 | none | 2.950 | 2.950 | 3.247 | 1.165 |
| example | 2021-08 | x25 | +1.96 | none | 3.029 | 3.141 | 3.679 | 3.679 |
| example | 2021-08 | x50 | +1.96 | none | 3.029 | 3.141 | 3.679 | 2.885 |
| example | 2021-08 | x100 | +1.96 | none | 3.029 | 3.141 | 3.679 | 1.165 |
| example | 2021-09 | x25 | +0.71 | none | 2.929 | 2.932 | 3.339 | 3.723 |
| example | 2021-09 | x50 | +0.06 | none | 2.677 | 2.677 | 3.339 | 2.899 |
| example | 2021-09 | x100 | +0.06 | none | 2.677 | 2.677 | 3.339 | 1.164 |
| example | 2021-10 | x25 | +1.18 | none | 2.814 | 2.819 | 3.344 | 3.735 |
| example | 2021-10 | x50 | +1.81 | none | 2.824 | 2.829 | 3.344 | 2.905 |
| example | 2021-10 | x100 | +1.81 | none | 2.824 | 2.829 | 3.344 | 1.162 |
| example | 2021-11 | x25 | +0.01 | none | 2.788 | 2.788 | 3.309 | 3.757 |
| example | 2021-11 | x50 | +1.18 | none | 2.784 | 2.801 | 3.309 | 2.903 |
| example | 2021-11 | x100 | +1.18 | none | 2.784 | 2.801 | 3.309 | 1.159 |
| example | 2021-12 | x25 | +0.39 | none | 2.735 | 2.738 | 3.366 | 3.768 |
| example | 2021-12 | x50 | +0.47 | none | 2.500 | 2.501 | 3.621 | 2.893 |
| example | 2021-12 | x100 | +0.47 | none | 2.500 | 2.501 | 3.621 | 1.157 |
| example | 2022-01 | x25 | +0.02 | none | 2.878 | 2.879 | 3.268 | 3.746 |
| example | 2022-01 | x50 | +1.95 | none | 3.090 | 3.092 | 3.268 | 2.884 |
| example | 2022-01 | x100 | +1.95 | none | 3.090 | 3.092 | 3.268 | 1.155 |
| example | 2022-02 | x25 | +2.50 | none | 2.976 | 3.019 | 3.032 | 3.710 |
| example | 2022-02 | x50 | +0.00 | none | 3.154 | 3.154 | 3.154 | 2.870 |
| example | 2022-02 | x100 | +0.00 | none | 3.154 | 3.154 | 3.154 | 1.152 |
| example | 2022-03 | x25 | +1.23 | none | 3.097 | 3.113 | 3.719 | 3.719 |
| example | 2022-03 | x50 | +1.23 | none | 3.097 | 3.113 | 3.719 | 2.881 |
| example | 2022-03 | x100 | +1.23 | none | 3.097 | 3.113 | 3.719 | 1.147 |
| example | 2022-04 | x25 | +0.22 | none | 2.506 | 2.508 | 3.266 | 3.640 |
| example | 2022-04 | x50 | +0.22 | none | 2.506 | 2.508 | 3.266 | 2.859 |
| example | 2022-04 | x100 | +0.22 | none | 2.506 | 2.508 | 3.266 | 1.145 |
| example | 2022-06 | x25 | +2.11 | none | 2.561 | 2.565 | 3.173 | 3.551 |
| example | 2022-06 | x50 | +2.11 | none | 2.561 | 2.565 | 3.173 | 2.905 |
| example | 2022-06 | x100 | +2.11 | none | 2.561 | 2.565 | 3.173 | 1.199 |
| example | 2022-07 | x25 | +0.24 | none | 2.472 | 2.561 | 2.835 | 3.532 |
| example | 2022-07 | x50 | +0.24 | none | 2.472 | 2.561 | 2.835 | 2.795 |
| example | 2022-07 | x100 | +0.24 | none | 2.472 | 2.561 | 2.835 | 1.130 |
| example | 2022-08 | x25 | +0.00 | none | 2.475 | 2.475 | 2.862 | 3.481 |
| example | 2022-08 | x50 | +0.00 | none | 2.475 | 2.475 | 3.481 | 2.782 |
| example | 2022-08 | x100 | +0.00 | none | 2.475 | 2.475 | 3.481 | 1.128 |
| example | 2022-09 | x25 | +1.52 | none | 2.152 | 2.193 | 3.016 | 3.394 |
| example | 2022-09 | x50 | +1.52 | none | 2.152 | 2.193 | 3.016 | 2.847 |
| example | 2022-09 | x100 | +1.52 | none | 2.152 | 2.193 | 3.016 | 1.191 |
| example | 2022-10 | x25 | +1.37 | none | 2.342 | 2.345 | 2.977 | 3.353 |
| example | 2022-10 | x50 | +1.37 | none | 2.342 | 2.345 | 2.977 | 2.824 |
| example | 2022-10 | x100 | +1.37 | none | 2.342 | 2.345 | 2.977 | 1.189 |
| example | 2022-11 | x25 | +1.60 | none | 2.330 | 2.343 | 2.478 | 3.287 |
| example | 2022-11 | x50 | +1.60 | none | 2.330 | 2.343 | 2.794 | 2.794 |
| example | 2022-11 | x100 | +1.60 | none | 2.330 | 2.343 | 2.794 | 1.189 |
| example | 2022-12 | x25 | +0.05 | none | 2.034 | 2.035 | 2.522 | 3.254 |
| example | 2022-12 | x50 | +0.05 | none | 2.034 | 2.035 | 2.522 | 2.789 |
| example | 2022-12 | x100 | +0.05 | none | 2.034 | 2.035 | 2.522 | 1.187 |
| example | 2023-01 | x25 | +1.53 | none | 2.144 | 2.178 | 2.609 | 3.230 |
| example | 2023-01 | x50 | +1.53 | none | 2.144 | 2.178 | 2.738 | 2.738 |
| example | 2023-01 | x100 | +1.53 | none | 2.144 | 2.178 | 2.738 | 1.149 |
| example | 2023-02 | x25 | +1.50 | none | 2.056 | 2.118 | 2.601 | 3.233 |
| example | 2023-02 | x50 | +1.50 | none | 2.056 | 2.118 | 2.734 | 2.734 |
| example | 2023-02 | x100 | +1.50 | none | 2.056 | 2.118 | 2.734 | 1.149 |
| example | 2023-03 | x25 | +1.32 | none | 2.239 | 2.256 | 3.269 | 3.269 |
| example | 2023-03 | x50 | +1.32 | none | 2.239 | 2.256 | 3.269 | 2.799 |
| example | 2023-03 | x100 | +1.32 | none | 2.239 | 2.256 | 3.269 | 1.200 |
| example | 2023-04 | x25 | +1.79 | none | 2.212 | 2.248 | 2.641 | 3.274 |
| example | 2023-04 | x50 | +1.79 | none | 2.212 | 2.248 | 2.805 | 2.805 |
| example | 2023-04 | x100 | +1.79 | none | 2.212 | 2.248 | 2.805 | 1.203 |
| example | 2023-05 | x25 | +1.59 | none | 2.390 | 2.391 | 2.929 | 3.305 |
| example | 2023-05 | x50 | +1.59 | none | 2.390 | 2.391 | 2.929 | 3.020 |
| example | 2023-05 | x100 | +1.59 | none | 2.390 | 2.391 | 2.929 | 1.443 |
| example | 2023-06 | x25 | +1.72 | none | 2.291 | 2.396 | 2.668 | 3.292 |
| example | 2023-06 | x50 | +1.72 | none | 2.291 | 2.396 | 2.668 | 3.016 |
| example | 2023-06 | x100 | +1.72 | none | 2.291 | 2.396 | 2.668 | 1.446 |
| example | 2023-07 | x25 | +0.65 | none | 2.359 | 2.360 | 2.903 | 3.263 |
| example | 2023-07 | x50 | +0.65 | none | 2.359 | 2.360 | 3.263 | 2.989 |
| example | 2023-07 | x100 | +0.65 | none | 2.359 | 2.360 | 3.263 | 1.428 |
| example | 2023-08 | x25 | +1.78 | none | 2.334 | 2.334 | 2.635 | 3.230 |
| example | 2023-08 | x50 | +1.78 | none | 2.334 | 2.334 | 3.230 | 2.970 |
| example | 2023-08 | x100 | +1.78 | none | 2.334 | 2.334 | 3.230 | 1.430 |
| example | 2023-09 | x25 | +2.17 | none | 2.316 | 2.338 | 2.383 | 3.213 |
| example | 2023-09 | x50 | +2.17 | none | 2.316 | 2.338 | 2.405 | 2.961 |
| example | 2023-09 | x100 | +2.17 | none | 2.316 | 2.338 | 2.405 | 1.432 |
| example | 2023-10 | x25 | +2.48 | none | 2.372 | 2.377 | 2.481 | 3.183 |
| example | 2023-10 | x50 | +2.48 | none | 2.372 | 2.377 | 2.949 | 2.949 |
| example | 2023-10 | x100 | +2.48 | none | 2.372 | 2.377 | 2.481 | 1.450 |
| example | 2023-11 | x25 | +1.24 | none | 2.300 | 2.304 | 2.822 | 3.125 |
| example | 2023-11 | x50 | +1.24 | none | 2.300 | 2.304 | 2.840 | 2.840 |
| example | 2023-11 | x100 | +1.24 | none | 2.300 | 2.304 | 2.840 | 1.300 |
| example | 2023-12 | x25 | +0.00 | none | 2.360 | 2.360 | 2.803 | 3.097 |
| example | 2023-12 | x50 | +0.00 | none | 2.360 | 2.360 | 3.097 | 2.839 |
| example | 2023-12 | x100 | +0.00 | none | 2.360 | 2.360 | 3.097 | 1.317 |
| example | 2024-01 | x25 | +0.00 | none | 2.307 | 2.307 | 3.082 | 3.082 |
| example | 2024-01 | x50 | +0.00 | none | 2.307 | 2.307 | 3.082 | 2.835 |
| example | 2024-01 | x100 | +0.00 | none | 2.307 | 2.307 | 3.082 | 1.325 |
| example | 2024-02 | x25 | +0.43 | none | 2.262 | 2.288 | 2.778 | 3.067 |
| example | 2024-02 | x50 | +0.43 | none | 2.262 | 2.288 | 2.828 | 2.828 |
| example | 2024-02 | x100 | +0.43 | none | 2.262 | 2.288 | 2.828 | 1.330 |
| example | 2024-03 | x25 | +0.43 | none | 2.263 | 2.265 | 2.536 | 3.051 |
| example | 2024-03 | x50 | +0.43 | none | 2.263 | 2.265 | 2.821 | 2.821 |
| example | 2024-03 | x100 | +0.43 | none | 2.263 | 2.265 | 2.821 | 1.332 |
| example | 2024-04 | x25 | +0.04 | none | 2.274 | 2.274 | 3.039 | 3.039 |
| example | 2024-04 | x50 | +0.04 | none | 2.274 | 2.274 | 3.039 | 2.865 |
| example | 2024-04 | x100 | +0.04 | none | 2.274 | 2.274 | 3.039 | 1.515 |
| example | 2024-05 | x25 | +0.89 | none | 2.284 | 2.285 | 2.459 | 3.006 |
| example | 2024-05 | x50 | +0.89 | none | 2.284 | 2.285 | 3.006 | 2.797 |
| example | 2024-05 | x100 | +0.89 | none | 2.284 | 2.285 | 3.006 | 1.340 |
| example | 2024-06 | x25 | +0.06 | none | 2.274 | 2.274 | 2.728 | 3.013 |
| example | 2024-06 | x50 | +0.06 | none | 2.274 | 2.274 | 2.728 | 2.851 |
| example | 2024-06 | x100 | +0.06 | none | 2.274 | 2.274 | 2.728 | 1.802 |
| example | 2024-07 | x25 | +1.45 | none | 2.007 | 2.067 | 2.328 | 2.981 |
| example | 2024-07 | x50 | +1.45 | none | 2.007 | 2.067 | 2.786 | 2.786 |
| example | 2024-07 | x100 | +1.45 | none | 2.007 | 2.067 | 2.786 | 1.795 |
| example | 2024-08 | x25 | +0.00 | none | 2.277 | 2.277 | 2.337 | 2.986 |
| example | 2024-08 | x50 | +0.00 | none | 2.277 | 2.277 | 2.381 | 2.789 |
| example | 2024-08 | x100 | +0.00 | none | 2.277 | 2.277 | 2.381 | 1.790 |
| example | 2024-09 | x25 | +0.15 | none | 2.286 | 2.287 | 2.458 | 2.986 |
| example | 2024-09 | x50 | +0.15 | none | 2.286 | 2.287 | 2.423 | 2.788 |
| example | 2024-09 | x100 | +0.15 | none | 2.286 | 2.287 | 2.788 | 1.785 |
| example | 2024-10 | x25 | +1.69 | none | 2.298 | 2.301 | 2.459 | 2.985 |
| example | 2024-10 | x50 | +1.69 | none | 2.298 | 2.301 | 2.423 | 2.789 |
| example | 2024-10 | x100 | +1.69 | none | 2.298 | 2.301 | 2.423 | 1.781 |
| example | 2024-11 | x25 | +0.30 | none | 2.288 | 2.297 | 2.307 | 2.981 |
| example | 2024-11 | x50 | +0.30 | none | 2.288 | 2.297 | 2.384 | 2.787 |
| example | 2024-11 | x100 | +0.30 | none | 2.288 | 2.297 | 2.787 | 1.784 |
| example | 2024-12 | x25 | +0.01 | none | 2.310 | 2.310 | 2.310 | 2.977 |
| example | 2024-12 | x50 | +0.01 | none | 2.310 | 2.310 | 2.380 | 2.783 |
| example | 2024-12 | x100 | +0.01 | none | 2.310 | 2.310 | 2.380 | 1.776 |
| example | 2025-01 | x25 | +0.82 | none | 2.146 | 2.147 | 2.448 | 2.958 |
| example | 2025-01 | x50 | +0.82 | none | 2.146 | 2.147 | 2.958 | 2.767 |
| example | 2025-01 | x100 | +0.82 | none | 2.146 | 2.147 | 2.958 | 1.769 |
| example | 2025-02 | x25 | +0.54 | none | 1.989 | 1.992 | 2.453 | 2.939 |
| example | 2025-02 | x50 | +0.54 | none | 1.989 | 1.992 | 2.273 | 2.788 |
| example | 2025-02 | x100 | +0.54 | none | 1.989 | 1.992 | 2.264 | 1.765 |
| example | 2025-03 | x25 | +1.17 | none | 1.579 | 1.580 | 2.452 | 2.885 |
| example | 2025-03 | x50 | +2.48 | none | 1.562 | 1.579 | 2.395 | 2.707 |
| example | 2025-03 | x100 | +2.48 | none | 1.562 | 1.579 | 2.395 | 1.757 |
| example | 2025-04 | x25 | +2.30 | none | 1.624 | 1.627 | 2.302 | 2.781 |
| example | 2025-04 | x50 | +0.18 | none | 1.555 | 1.556 | 2.019 | 2.614 |
| example | 2025-04 | x100 | +0.18 | none | 1.555 | 1.556 | 2.019 | 1.735 |
| example | 2025-05 | x25 | +0.00 | none | 1.768 | 1.768 | 1.971 | 2.777 |
| example | 2025-05 | x50 | +2.39 | none | 1.673 | 1.699 | 1.948 | 2.620 |
| example | 2025-05 | x100 | +1.45 | none | 1.732 | 1.737 | 2.022 | 1.730 |
| example | 2025-06 | x25 | +1.25 | none | 1.674 | 1.675 | 2.315 | 2.756 |
| example | 2025-06 | x50 | +0.14 | none | 1.577 | 1.582 | 1.897 | 2.600 |
| example | 2025-06 | x100 | +0.14 | none | 1.577 | 1.582 | 1.897 | 1.723 |
| example | 2025-07 | x25 | +0.00 | none | 1.740 | 1.740 | 2.079 | 2.725 |
| example | 2025-07 | x50 | +0.32 | none | 1.579 | 1.581 | 1.873 | 2.560 |
| example | 2025-07 | x100 | +0.32 | none | 1.579 | 1.581 | 1.873 | 1.712 |
| example | 2025-08 | x25 | +2.47 | none | 1.801 | 1.834 | 2.395 | 2.735 |
| example | 2025-08 | x50 | +1.70 | none | 1.836 | 1.838 | 2.395 | 2.576 |
| example | 2025-08 | x100 | +1.70 | none | 1.836 | 1.838 | 2.395 | 1.705 |
| example | 2025-09 | x25 | +0.15 | none | 1.659 | 1.671 | 2.321 | 2.706 |
| example | 2025-09 | x50 | +0.58 | none | 1.583 | 1.629 | 2.321 | 2.541 |
| example | 2025-09 | x100 | +0.58 | none | 1.583 | 1.629 | 2.321 | 1.704 |
| example | 2025-10 | x25 | +2.11 | none | 1.744 | 1.759 | 1.936 | 2.738 |
| example | 2025-10 | x50 | +1.10 | none | 1.590 | 1.651 | 2.232 | 2.584 |
| example | 2025-10 | x100 | +1.10 | none | 1.590 | 1.651 | 1.915 | 1.704 |
| example | 2025-11 | x25 | +0.00 | none | 1.860 | 1.860 | 2.388 | 2.726 |
| example | 2025-11 | x50 | +0.79 | none | 1.902 | 1.936 | 2.081 | 2.572 |
| example | 2025-11 | x100 | +0.79 | none | 1.902 | 1.936 | 2.081 | 1.697 |
| example | 2025-12 | x25 | +0.00 | none | 1.830 | 1.830 | 2.009 | 2.716 |
| example | 2025-12 | x50 | +0.94 | none | 2.010 | 2.013 | 2.178 | 2.563 |
| example | 2025-12 | x100 | +0.94 | none | 2.010 | 2.013 | 2.178 | 1.690 |
| example | 2026-01 | x25 | +0.72 | none | 1.745 | 1.753 | 2.367 | 2.698 |
| example | 2026-01 | x50 | +0.32 | none | 1.744 | 1.747 | 2.202 | 2.546 |
| example | 2026-01 | x100 | +0.32 | none | 1.744 | 1.747 | 1.927 | 1.680 |
| example | 2026-02 | x25 | +0.01 | none | 1.773 | 1.773 | 2.311 | 2.701 |
| example | 2026-02 | x50 | +0.28 | none | 2.047 | 2.048 | 2.204 | 2.549 |
| example | 2026-02 | x100 | +0.28 | none | 2.047 | 2.048 | 2.141 | 1.681 |
| example | 2026-03 | x25 | +0.01 | none | 1.842 | 1.842 | 2.227 | 2.649 |
| example | 2026-03 | x50 | +0.06 | none | 1.920 | 1.921 | 2.227 | 2.500 |
| example | 2026-03 | x100 | +0.06 | none | 1.920 | 1.921 | 2.227 | 1.893 |
| example | 2026-04 | x25 | +1.83 | none | 1.804 | 1.810 | 1.999 | 2.651 |
| example | 2026-04 | x50 | +2.07 | none | 1.585 | 1.589 | 1.978 | 2.510 |
| example | 2026-04 | x100 | +2.07 | none | 1.585 | 1.589 | 1.978 | 1.890 |
| example | 2026-05 | x25 | +0.53 | none | 1.798 | 1.801 | 1.974 | 2.641 |
| example | 2026-05 | x50 | +0.00 | none | 1.772 | 1.772 | 2.066 | 2.502 |
| example | 2026-05 | x100 | +0.00 | none | 1.772 | 1.772 | 2.066 | 1.888 |
| example | 2026-06 | x25 | +1.59 | none | 1.746 | 1.790 | 2.317 | 2.607 |
| example | 2026-06 | x50 | +1.20 | none | 1.870 | 1.872 | 2.138 | 2.467 |
| example | 2026-06 | x100 | +1.96 | none | 1.895 | 1.909 | 2.028 | 1.876 |
| example | 2026-07 | x25 | +0.02 | none | 1.793 | 1.793 | 1.973 | 2.587 |
| example | 2026-07 | x50 | +0.30 | none | 1.794 | 1.794 | 1.973 | 2.448 |
| example | 2026-07 | x100 | +0.30 | none | 1.794 | 1.794 | 1.973 | 1.864 |
| example | 2026-08 | x25 | +0.43 | none | 1.773 | 1.777 | 2.033 | 2.580 |
| example | 2026-08 | x50 | +0.30 | none | 1.812 | 1.817 | 1.973 | 2.443 |
| example | 2026-08 | x100 | +0.30 | none | 1.812 | 1.817 | 1.973 | 1.861 |
| example | 2026-09 | x25 | +0.60 | none | 1.989 | 1.989 | 2.016 | 2.563 |
| example | 2026-09 | x50 | +1.56 | none | 1.841 | 1.842 | 2.016 | 2.432 |
| example | 2026-09 | x100 | +1.56 | none | 1.841 | 1.842 | 2.016 | 1.852 |
| tsp | 2018-06 | x25 | +0.99 | none | 1.379 | 1.394 | 2.809 | 2.449 |
| tsp | 2018-06 | x50 | +0.14 | none | 1.241 | 1.247 | 2.809 | 1.727 |
| tsp | 2018-06 | x100 | +0.14 | none | 1.241 | 1.247 | 2.809 | 1.202 |
| tsp | 2018-07 | x25 | +1.46 | none | 1.596 | 1.608 | 2.917 | 2.498 |
| tsp | 2018-07 | x50 | +1.46 | none | 1.596 | 1.608 | 2.917 | 1.739 |
| tsp | 2018-07 | x100 | +1.46 | none | 1.596 | 1.608 | 2.917 | 1.209 |
| tsp | 2018-08 | x25 | +1.16 | none | 1.589 | 1.650 | 2.980 | 2.504 |
| tsp | 2018-08 | x50 | +1.59 | none | 1.545 | 1.580 | 2.980 | 1.740 |
| tsp | 2018-08 | x100 | +1.59 | none | 1.545 | 1.580 | 2.980 | 1.209 |
| tsp | 2018-09 | x25 | +2.24 | none | 1.618 | 1.670 | 2.987 | 2.526 |
| tsp | 2018-09 | x50 | +2.24 | none | 1.618 | 1.670 | 2.987 | 1.772 |
| tsp | 2018-09 | x100 | +2.24 | none | 1.618 | 1.670 | 2.987 | 1.211 |
| tsp | 2018-10 | x25 | +1.06 | none | 1.940 | 2.040 | 3.024 | 2.524 |
| tsp | 2018-10 | x50 | +1.06 | none | 1.940 | 2.040 | 3.024 | 1.758 |
| tsp | 2018-10 | x100 | +1.06 | none | 1.940 | 2.040 | 3.024 | 1.206 |
| tsp | 2018-11 | x25 | +0.67 | none | 2.444 | 2.564 | 2.962 | 2.503 |
| tsp | 2018-11 | x50 | +0.67 | none | 2.444 | 2.564 | 2.962 | 1.745 |
| tsp | 2018-11 | x100 | +0.67 | none | 2.444 | 2.564 | 2.962 | 1.204 |
| tsp | 2018-12 | x25 | +1.95 | none | 2.512 | 2.694 | 3.005 | 2.480 |
| tsp | 2018-12 | x50 | +1.95 | none | 2.512 | 2.694 | 3.005 | 1.719 |
| tsp | 2018-12 | x100 | +1.95 | none | 2.512 | 2.694 | 3.005 | 1.198 |
| tsp | 2019-01 | x25 | +1.64 | none | 2.692 | 2.966 | 3.094 | 2.480 |
| tsp | 2019-01 | x50 | +1.64 | none | 2.692 | 2.966 | 3.094 | 1.712 |
| tsp | 2019-01 | x100 | +1.64 | none | 2.692 | 2.966 | 3.094 | 1.194 |
| tsp | 2019-02 | x25 | +0.12 | none | 2.402 | 2.411 | 2.897 | 2.483 |
| tsp | 2019-02 | x50 | +0.12 | none | 2.402 | 2.411 | 2.897 | 1.717 |
| tsp | 2019-02 | x100 | +0.12 | none | 2.402 | 2.411 | 2.897 | 1.198 |
| tsp | 2019-03 | x25 | +1.52 | none | 2.402 | 2.738 | 3.023 | 2.485 |
| tsp | 2019-03 | x50 | +1.52 | none | 2.402 | 2.738 | 3.023 | 1.715 |
| tsp | 2019-03 | x100 | +1.52 | none | 2.402 | 2.738 | 3.023 | 1.103 |
| tsp | 2019-04 | x25 | +2.08 | none | 2.410 | 2.751 | 3.079 | 2.487 |
| tsp | 2019-04 | x50 | +2.08 | none | 2.410 | 2.751 | 3.079 | 1.717 |
| tsp | 2019-04 | x100 | +2.08 | none | 2.410 | 2.751 | 3.079 | 1.196 |
| tsp | 2019-05 | x25 | +0.02 | none | 2.928 | 2.928 | 3.034 | 2.484 |
| tsp | 2019-05 | x50 | +0.02 | none | 2.928 | 2.928 | 3.034 | 1.711 |
| tsp | 2019-05 | x100 | +0.02 | none | 2.928 | 2.928 | 3.034 | 1.100 |
| tsp | 2019-06 | x25 | +2.45 | none | 2.380 | 2.463 | 2.952 | 2.472 |
| tsp | 2019-06 | x50 | +2.45 | none | 2.380 | 2.463 | 2.952 | 1.708 |
| tsp | 2019-06 | x100 | +2.45 | none | 2.380 | 2.463 | 2.952 | 1.101 |
| tsp | 2019-07 | x25 | +1.77 | none | 2.488 | 2.592 | 2.999 | 2.467 |
| tsp | 2019-07 | x50 | +1.77 | none | 2.488 | 2.592 | 2.999 | 1.707 |
| tsp | 2019-07 | x100 | +1.77 | none | 2.488 | 2.592 | 2.999 | 1.100 |
| tsp | 2019-08 | x25 | +1.00 | none | 2.709 | 2.756 | 2.774 | 2.486 |
| tsp | 2019-08 | x50 | +1.00 | none | 2.709 | 2.756 | 2.774 | 1.704 |
| tsp | 2019-08 | x100 | +1.00 | none | 2.709 | 2.756 | 2.774 | 1.095 |
| tsp | 2019-09 | x25 | +1.42 | none | 2.740 | 2.844 | 3.029 | 2.507 |
| tsp | 2019-09 | x50 | +1.42 | none | 2.740 | 2.844 | 3.029 | 1.713 |
| tsp | 2019-09 | x100 | +1.42 | none | 2.740 | 2.844 | 3.029 | 1.095 |
| tsp | 2019-10 | x25 | +1.31 | none | 2.094 | 2.182 | 3.158 | 2.509 |
| tsp | 2019-10 | x50 | +1.31 | none | 2.094 | 2.182 | 3.158 | 1.712 |
| tsp | 2019-10 | x100 | +1.31 | none | 2.094 | 2.182 | 3.158 | 1.094 |
| tsp | 2019-11 | x25 | +0.54 | none | 2.161 | 2.203 | 2.953 | 2.517 |
| tsp | 2019-11 | x50 | +0.54 | none | 2.161 | 2.203 | 2.953 | 1.717 |
| tsp | 2019-11 | x100 | +0.54 | none | 2.161 | 2.203 | 2.953 | 1.095 |
| tsp | 2019-12 | x25 | +0.02 | none | 2.339 | 2.339 | 2.648 | 2.526 |
| tsp | 2019-12 | x50 | +0.02 | none | 2.339 | 2.339 | 2.648 | 1.720 |
| tsp | 2019-12 | x100 | +0.02 | none | 2.339 | 2.339 | 2.648 | 1.093 |
| tsp | 2020-01 | x25 | +0.58 | none | 1.964 | 1.996 | 3.134 | 2.525 |
| tsp | 2020-01 | x50 | +0.58 | none | 1.964 | 1.996 | 3.134 | 1.722 |
| tsp | 2020-01 | x100 | +0.58 | none | 1.964 | 1.996 | 3.134 | 1.094 |
| tsp | 2020-02 | x25 | +0.14 | none | 2.663 | 2.670 | 3.116 | 2.507 |
| tsp | 2020-02 | x50 | +0.14 | none | 2.663 | 2.670 | 3.116 | 1.711 |
| tsp | 2020-02 | x100 | +0.14 | none | 2.663 | 2.670 | 3.116 | 1.091 |
| tsp | 2020-03 | x25 | +0.09 | none | 1.929 | 2.581 | 2.734 | 2.160 |
| tsp | 2020-03 | x50 | +0.09 | none | 1.929 | 2.581 | 2.734 | 1.552 |
| tsp | 2020-03 | x100 | +0.09 | none | 1.929 | 2.581 | 2.734 | 1.085 |
| tsp | 2020-04 | x25 | +1.85 | none | 2.682 | 2.708 | 2.724 | 2.121 |
| tsp | 2020-04 | x50 | +1.85 | none | 2.682 | 2.708 | 2.724 | 1.526 |
| tsp | 2020-04 | x100 | +1.85 | none | 2.682 | 2.708 | 2.724 | 1.083 |
| tsp | 2020-05 | x25 | +0.06 | none | 2.703 | 2.704 | 2.742 | 2.114 |
| tsp | 2020-05 | x50 | +0.06 | none | 2.703 | 2.704 | 2.742 | 1.523 |
| tsp | 2020-05 | x100 | +0.06 | none | 2.703 | 2.704 | 2.742 | 1.086 |
| tsp | 2020-06 | x25 | +2.28 | none | 2.673 | 2.730 | 2.732 | 2.089 |
| tsp | 2020-06 | x50 | +2.28 | none | 2.673 | 2.730 | 2.732 | 1.509 |
| tsp | 2020-06 | x100 | +2.28 | none | 2.673 | 2.730 | 2.732 | 1.084 |
| tsp | 2020-07 | x25 | +0.94 | none | 2.707 | 2.722 | 2.730 | 2.069 |
| tsp | 2020-07 | x50 | +0.94 | none | 2.707 | 2.722 | 2.730 | 1.502 |
| tsp | 2020-07 | x100 | +0.94 | none | 2.707 | 2.722 | 2.730 | 1.085 |
| tsp | 2020-08 | x25 | +1.82 | none | 2.624 | 2.702 | 2.738 | 2.065 |
| tsp | 2020-08 | x50 | +1.82 | none | 2.624 | 2.702 | 2.738 | 1.501 |
| tsp | 2020-08 | x100 | +1.82 | none | 2.624 | 2.702 | 2.738 | 1.086 |
| tsp | 2020-09 | x25 | +0.45 | none | 2.605 | 2.622 | 2.721 | 2.060 |
| tsp | 2020-09 | x50 | +0.45 | none | 2.605 | 2.622 | 2.721 | 1.502 |
| tsp | 2020-09 | x100 | +0.45 | none | 2.605 | 2.622 | 2.721 | 1.089 |
| tsp | 2020-10 | x25 | +0.68 | none | 2.659 | 2.662 | 2.739 | 2.029 |
| tsp | 2020-10 | x50 | +0.68 | none | 2.659 | 2.662 | 2.739 | 1.475 |
| tsp | 2020-10 | x100 | +0.68 | none | 2.659 | 2.662 | 2.739 | 1.053 |
| tsp | 2020-11 | x25 | +0.00 | none | 2.015 | 2.015 | 2.685 | 2.025 |
| tsp | 2020-11 | x50 | +0.00 | none | 2.015 | 2.015 | 2.685 | 1.474 |
| tsp | 2020-11 | x100 | +0.00 | none | 2.015 | 2.015 | 2.685 | 1.053 |
| tsp | 2020-12 | x25 | +1.17 | none | 2.508 | 2.596 | 2.702 | 2.031 |
| tsp | 2020-12 | x50 | +1.17 | none | 2.508 | 2.596 | 2.702 | 1.478 |
| tsp | 2020-12 | x100 | +1.17 | none | 2.508 | 2.596 | 2.702 | 1.055 |
| tsp | 2021-01 | x25 | +2.11 | none | 1.895 | 1.936 | 2.683 | 2.031 |
| tsp | 2021-01 | x50 | +2.11 | none | 1.895 | 1.936 | 2.683 | 1.480 |
| tsp | 2021-01 | x100 | +2.11 | none | 1.895 | 1.936 | 2.683 | 1.056 |
| tsp | 2021-02 | x25 | +1.79 | none | 1.852 | 1.859 | 2.659 | 2.034 |
| tsp | 2021-02 | x50 | +0.52 | none | 1.406 | 1.407 | 2.659 | 1.482 |
| tsp | 2021-02 | x100 | +0.52 | none | 1.406 | 1.407 | 2.659 | 1.057 |
| tsp | 2021-03 | x25 | +1.30 | none | 1.656 | 1.717 | 2.628 | 2.023 |
| tsp | 2021-03 | x50 | +1.30 | none | 1.656 | 1.717 | 2.628 | 1.479 |
| tsp | 2021-03 | x100 | +1.30 | none | 1.656 | 1.717 | 2.628 | 1.059 |
| tsp | 2021-04 | x25 | +2.11 | none | 1.309 | 1.322 | 2.565 | 2.018 |
| tsp | 2021-04 | x50 | +2.11 | none | 1.309 | 1.322 | 2.565 | 1.477 |
| tsp | 2021-04 | x100 | +2.11 | none | 1.309 | 1.322 | 2.565 | 1.060 |
| tsp | 2021-05 | x25 | +0.54 | none | 1.591 | 1.591 | 2.590 | 2.007 |
| tsp | 2021-05 | x50 | +0.07 | none | 1.654 | 1.654 | 2.590 | 1.474 |
| tsp | 2021-05 | x100 | +0.07 | none | 1.654 | 1.654 | 2.590 | 1.060 |
| tsp | 2021-06 | x25 | +0.88 | none | 2.067 | 2.082 | 2.580 | 2.007 |
| tsp | 2021-06 | x50 | +0.88 | none | 2.067 | 2.082 | 2.580 | 1.473 |
| tsp | 2021-06 | x100 | +0.88 | none | 2.067 | 2.082 | 2.580 | 1.061 |
| tsp | 2021-07 | x25 | +1.83 | none | 1.564 | 1.577 | 2.559 | 1.996 |
| tsp | 2021-07 | x50 | +1.83 | none | 1.564 | 1.577 | 2.559 | 1.466 |
| tsp | 2021-07 | x100 | +1.83 | none | 1.564 | 1.577 | 2.559 | 1.063 |
| tsp | 2021-08 | x25 | +2.47 | none | 1.880 | 1.909 | 2.557 | 1.994 |
| tsp | 2021-08 | x50 | +2.47 | none | 1.880 | 1.909 | 2.557 | 1.464 |
| tsp | 2021-08 | x100 | +2.47 | none | 1.880 | 1.909 | 2.557 | 1.063 |
| tsp | 2021-09 | x25 | +1.36 | none | 2.018 | 2.042 | 2.575 | 2.002 |
| tsp | 2021-09 | x50 | +1.36 | none | 2.018 | 2.042 | 2.575 | 1.466 |
| tsp | 2021-09 | x100 | +1.36 | none | 2.018 | 2.042 | 2.575 | 1.063 |
| tsp | 2021-10 | x25 | +0.08 | none | 1.709 | 1.712 | 2.540 | 2.006 |
| tsp | 2021-10 | x50 | +1.68 | none | 1.656 | 1.677 | 2.540 | 1.468 |
| tsp | 2021-10 | x100 | +1.68 | none | 1.656 | 1.677 | 2.540 | 1.064 |
| tsp | 2021-11 | x25 | +0.06 | none | 1.820 | 1.821 | 2.588 | 2.006 |
| tsp | 2021-11 | x50 | +0.26 | none | 1.783 | 1.790 | 2.588 | 1.466 |
| tsp | 2021-11 | x100 | +0.26 | none | 1.783 | 1.790 | 2.588 | 1.063 |
| tsp | 2021-12 | x25 | +1.22 | none | 1.557 | 1.561 | 2.624 | 2.011 |
| tsp | 2021-12 | x50 | +0.53 | none | 1.332 | 1.340 | 2.624 | 1.466 |
| tsp | 2021-12 | x100 | +0.04 | none | 1.274 | 1.274 | 2.624 | 1.064 |
| tsp | 2022-01 | x25 | +0.29 | none | 1.548 | 1.558 | 2.555 | 2.004 |
| tsp | 2022-01 | x50 | +0.29 | none | 1.548 | 1.558 | 2.555 | 1.463 |
| tsp | 2022-01 | x100 | +0.29 | none | 1.548 | 1.558 | 2.555 | 1.063 |
| tsp | 2022-02 | x25 | +0.47 | none | 1.437 | 1.447 | 2.581 | 2.000 |
| tsp | 2022-02 | x50 | +0.47 | none | 1.437 | 1.447 | 2.581 | 1.463 |
| tsp | 2022-02 | x100 | +0.47 | none | 1.437 | 1.447 | 2.581 | 1.062 |
| tsp | 2022-03 | x25 | +0.01 | none | 2.335 | 2.339 | 2.550 | 2.010 |
| tsp | 2022-03 | x50 | +0.01 | none | 2.335 | 2.339 | 2.550 | 1.468 |
| tsp | 2022-03 | x100 | +0.01 | none | 2.335 | 2.339 | 2.550 | 1.061 |
| tsp | 2022-04 | x25 | +0.03 | none | 2.246 | 2.247 | 2.481 | 2.021 |
| tsp | 2022-04 | x50 | +0.03 | none | 2.246 | 2.247 | 2.481 | 1.492 |
| tsp | 2022-04 | x100 | +0.03 | none | 2.246 | 2.247 | 2.481 | 1.095 |
| tsp | 2022-06 | x25 | +0.13 | none | 2.369 | 2.369 | 2.369 | 1.988 |
| tsp | 2022-06 | x50 | +0.13 | none | 2.369 | 2.369 | 2.369 | 1.481 |
| tsp | 2022-06 | x100 | +0.13 | none | 2.369 | 2.369 | 2.369 | 1.091 |
| tsp | 2022-07 | x25 | +2.46 | none | 1.825 | 1.828 | 2.412 | 1.990 |
| tsp | 2022-07 | x50 | +2.46 | none | 1.825 | 1.828 | 2.412 | 1.482 |
| tsp | 2022-07 | x100 | +2.46 | none | 1.825 | 1.828 | 2.412 | 1.091 |
| tsp | 2022-08 | x25 | +0.62 | none | 2.208 | 2.210 | 2.367 | 1.976 |
| tsp | 2022-08 | x50 | +0.62 | none | 2.208 | 2.210 | 2.367 | 1.480 |
| tsp | 2022-08 | x100 | +0.62 | none | 2.208 | 2.210 | 2.367 | 1.089 |
| tsp | 2022-09 | x25 | +0.20 | none | 2.173 | 2.178 | 2.246 | 1.950 |
| tsp | 2022-09 | x50 | +0.20 | none | 2.173 | 2.178 | 2.246 | 1.475 |
| tsp | 2022-09 | x100 | +0.20 | none | 2.173 | 2.178 | 2.246 | 1.089 |
| tsp | 2022-10 | x25 | +0.19 | none | 2.203 | 2.204 | 2.239 | 1.924 |
| tsp | 2022-10 | x50 | +0.19 | none | 2.203 | 2.204 | 2.239 | 1.467 |
| tsp | 2022-10 | x100 | +0.19 | none | 2.203 | 2.204 | 2.239 | 1.087 |
| tsp | 2022-11 | x25 | +2.10 | none | 2.134 | 2.140 | 2.167 | 1.891 |
| tsp | 2022-11 | x50 | +2.10 | none | 2.134 | 2.140 | 2.167 | 1.459 |
| tsp | 2022-11 | x100 | +2.10 | none | 2.134 | 2.140 | 2.167 | 1.087 |
| tsp | 2022-12 | x25 | +0.00 | none | 2.145 | 2.145 | 2.187 | 1.887 |
| tsp | 2022-12 | x50 | +0.00 | none | 2.145 | 2.145 | 2.187 | 1.459 |
| tsp | 2022-12 | x100 | +0.00 | none | 2.145 | 2.145 | 2.187 | 1.086 |
| tsp | 2023-01 | x25 | +2.20 | none | 2.120 | 2.127 | 2.174 | 1.884 |
| tsp | 2023-01 | x50 | +2.20 | none | 2.120 | 2.127 | 2.174 | 1.460 |
| tsp | 2023-01 | x100 | +2.20 | none | 2.120 | 2.127 | 2.174 | 1.085 |
| tsp | 2023-02 | x25 | +1.86 | none | 2.047 | 2.074 | 2.150 | 1.879 |
| tsp | 2023-02 | x50 | +1.86 | none | 2.047 | 2.074 | 2.150 | 1.460 |
| tsp | 2023-02 | x100 | +1.86 | none | 2.047 | 2.074 | 2.150 | 1.086 |
| tsp | 2023-03 | x25 | +1.67 | none | 2.120 | 2.127 | 2.127 | 1.913 |
| tsp | 2023-03 | x50 | +1.67 | none | 2.120 | 2.127 | 2.127 | 1.476 |
| tsp | 2023-03 | x100 | +1.67 | none | 2.120 | 2.127 | 2.127 | 1.087 |
| tsp | 2023-04 | x25 | +0.65 | none | 1.947 | 1.948 | 2.165 | 1.921 |
| tsp | 2023-04 | x50 | +0.65 | none | 1.947 | 1.948 | 2.165 | 1.483 |
| tsp | 2023-04 | x100 | +0.65 | none | 1.947 | 1.948 | 2.165 | 1.089 |
| tsp | 2023-05 | x25 | +1.71 | none | 2.086 | 2.090 | 2.187 | 1.933 |
| tsp | 2023-05 | x50 | +1.71 | none | 2.086 | 2.090 | 2.187 | 1.489 |
| tsp | 2023-05 | x100 | +1.71 | none | 2.086 | 2.090 | 2.187 | 1.089 |
| tsp | 2023-06 | x25 | +0.03 | none | 1.979 | 1.979 | 2.146 | 1.928 |
| tsp | 2023-06 | x50 | +0.03 | none | 1.979 | 1.979 | 2.146 | 1.488 |
| tsp | 2023-06 | x100 | +0.03 | none | 1.979 | 1.979 | 2.146 | 1.089 |
| tsp | 2023-07 | x25 | +0.00 | none | 2.080 | 2.080 | 2.137 | 1.920 |
| tsp | 2023-07 | x50 | +0.00 | none | 2.080 | 2.080 | 2.137 | 1.487 |
| tsp | 2023-07 | x100 | +0.00 | none | 2.080 | 2.080 | 2.137 | 1.090 |
| tsp | 2023-08 | x25 | +1.41 | none | 1.917 | 1.929 | 2.139 | 1.914 |
| tsp | 2023-08 | x50 | +1.41 | none | 1.917 | 1.929 | 2.139 | 1.486 |
| tsp | 2023-08 | x100 | +1.41 | none | 1.917 | 1.929 | 2.139 | 1.088 |
| tsp | 2023-09 | x25 | +0.23 | none | 1.606 | 1.734 | 2.152 | 1.912 |
| tsp | 2023-09 | x50 | +0.23 | none | 1.606 | 1.734 | 2.152 | 1.486 |
| tsp | 2023-09 | x100 | +0.23 | none | 1.606 | 1.734 | 2.152 | 1.088 |
| tsp | 2023-10 | x25 | +1.11 | none | 2.015 | 2.040 | 2.122 | 1.911 |
| tsp | 2023-10 | x50 | +1.11 | none | 2.015 | 2.040 | 2.122 | 1.488 |
| tsp | 2023-10 | x100 | +1.11 | none | 2.015 | 2.040 | 2.122 | 1.088 |
| tsp | 2023-11 | x25 | +1.57 | none | 2.026 | 2.031 | 2.062 | 1.903 |
| tsp | 2023-11 | x50 | +1.57 | none | 2.026 | 2.031 | 2.062 | 1.490 |
| tsp | 2023-11 | x100 | +1.57 | none | 2.026 | 2.031 | 2.062 | 1.090 |
| tsp | 2023-12 | x25 | +0.11 | none | 2.043 | 2.043 | 2.071 | 1.900 |
| tsp | 2023-12 | x50 | +0.11 | none | 2.043 | 2.043 | 2.071 | 1.493 |
| tsp | 2023-12 | x100 | +0.11 | none | 2.043 | 2.043 | 2.071 | 1.092 |
| tsp | 2024-01 | x25 | +2.30 | none | 2.019 | 2.033 | 2.063 | 1.894 |
| tsp | 2024-01 | x50 | +2.30 | none | 2.019 | 2.033 | 2.063 | 1.496 |
| tsp | 2024-01 | x100 | +2.30 | none | 2.019 | 2.033 | 2.063 | 1.095 |
| tsp | 2024-02 | x25 | +1.25 | none | 2.005 | 2.016 | 2.059 | 1.890 |
| tsp | 2024-02 | x50 | +1.25 | none | 2.005 | 2.016 | 2.059 | 1.496 |
| tsp | 2024-02 | x100 | +1.25 | none | 2.005 | 2.016 | 2.059 | 1.095 |
| tsp | 2024-03 | x25 | +1.70 | none | 2.020 | 2.028 | 2.041 | 1.888 |
| tsp | 2024-03 | x50 | +1.70 | none | 2.020 | 2.028 | 2.041 | 1.496 |
| tsp | 2024-03 | x100 | +1.70 | none | 2.020 | 2.028 | 2.041 | 1.096 |
| tsp | 2024-04 | x25 | +2.29 | none | 1.905 | 1.948 | 2.027 | 1.881 |
| tsp | 2024-04 | x50 | +2.29 | none | 1.905 | 1.948 | 2.027 | 1.494 |
| tsp | 2024-04 | x100 | +2.29 | none | 1.905 | 1.948 | 2.027 | 1.095 |
| tsp | 2024-05 | x25 | +1.25 | none | 1.992 | 2.012 | 2.037 | 1.875 |
| tsp | 2024-05 | x50 | +1.25 | none | 1.992 | 2.012 | 2.037 | 1.494 |
| tsp | 2024-05 | x100 | +1.25 | none | 1.992 | 2.012 | 2.037 | 1.095 |
| tsp | 2024-06 | x25 | +0.82 | none | 1.993 | 1.995 | 1.999 | 1.874 |
| tsp | 2024-06 | x50 | +0.82 | none | 1.993 | 1.995 | 1.999 | 1.496 |
| tsp | 2024-06 | x100 | +0.82 | none | 1.993 | 1.995 | 1.999 | 1.096 |
| tsp | 2024-07 | x25 | +0.72 | none | 1.999 | 2.007 | 2.036 | 1.871 |
| tsp | 2024-07 | x50 | +0.72 | none | 1.999 | 2.007 | 2.036 | 1.496 |
| tsp | 2024-07 | x100 | +0.72 | none | 1.999 | 2.007 | 2.036 | 1.097 |
| tsp | 2024-08 | x25 | +2.41 | none | 1.993 | 2.006 | 2.032 | 1.872 |
| tsp | 2024-08 | x50 | +2.41 | none | 1.993 | 2.006 | 2.032 | 1.496 |
| tsp | 2024-08 | x100 | +2.41 | none | 1.993 | 2.006 | 2.032 | 1.097 |
| tsp | 2024-09 | x25 | +0.07 | none | 1.881 | 1.882 | 1.992 | 1.867 |
| tsp | 2024-09 | x50 | +0.07 | none | 1.881 | 1.882 | 1.992 | 1.496 |
| tsp | 2024-09 | x100 | +0.07 | none | 1.881 | 1.882 | 1.992 | 1.098 |
| tsp | 2024-10 | x25 | +0.52 | none | 1.921 | 1.927 | 2.003 | 1.862 |
| tsp | 2024-10 | x50 | +0.52 | none | 1.921 | 1.927 | 2.003 | 1.494 |
| tsp | 2024-10 | x100 | +0.52 | none | 1.921 | 1.927 | 2.003 | 1.098 |
| tsp | 2024-11 | x25 | +0.08 | none | 1.981 | 1.982 | 2.007 | 1.864 |
| tsp | 2024-11 | x50 | +0.08 | none | 1.981 | 1.982 | 2.007 | 1.497 |
| tsp | 2024-11 | x100 | +0.08 | none | 1.981 | 1.982 | 2.007 | 1.100 |
| tsp | 2024-12 | x25 | +1.21 | none | 1.828 | 1.839 | 1.984 | 1.858 |
| tsp | 2024-12 | x50 | +1.21 | none | 1.828 | 1.839 | 1.984 | 1.494 |
| tsp | 2024-12 | x100 | +1.21 | none | 1.828 | 1.839 | 1.984 | 1.100 |
| tsp | 2025-01 | x25 | +1.94 | none | 1.898 | 1.951 | 1.979 | 1.852 |
| tsp | 2025-01 | x50 | +1.94 | none | 1.898 | 1.951 | 1.979 | 1.492 |
| tsp | 2025-01 | x100 | +1.94 | none | 1.898 | 1.951 | 1.979 | 1.099 |
| tsp | 2025-02 | x25 | +1.44 | none | 1.924 | 1.942 | 1.999 | 1.848 |
| tsp | 2025-02 | x50 | +1.44 | none | 1.924 | 1.942 | 1.999 | 1.491 |
| tsp | 2025-02 | x100 | +1.44 | none | 1.924 | 1.942 | 1.999 | 1.099 |
| tsp | 2025-03 | x25 | +0.09 | none | 1.355 | 1.356 | 1.960 | 1.833 |
| tsp | 2025-03 | x50 | +0.09 | none | 1.355 | 1.356 | 1.960 | 1.495 |
| tsp | 2025-03 | x100 | +0.09 | none | 1.355 | 1.356 | 1.960 | 1.106 |
| tsp | 2025-04 | x25 | +2.12 | none | 1.071 | 1.091 | 1.911 | 1.835 |
| tsp | 2025-04 | x50 | +2.03 | none | 1.027 | 1.047 | 1.911 | 1.489 |
| tsp | 2025-04 | x100 | +2.03 | none | 1.027 | 1.047 | 1.911 | 1.056 |
| tsp | 2025-05 | x25 | +1.25 | none | 1.337 | 1.366 | 1.904 | 1.851 |
| tsp | 2025-05 | x50 | +1.25 | none | 1.337 | 1.366 | 1.904 | 1.540 |
| tsp | 2025-05 | x100 | +1.25 | none | 1.337 | 1.366 | 1.904 | 1.122 |
| tsp | 2025-06 | x25 | +2.08 | none | 1.178 | 1.192 | 1.894 | 1.842 |
| tsp | 2025-06 | x50 | +1.02 | none | 1.187 | 1.192 | 1.894 | 1.539 |
| tsp | 2025-06 | x100 | +1.02 | none | 1.187 | 1.192 | 1.894 | 1.120 |
| tsp | 2025-07 | x25 | +0.00 | none | 1.172 | 1.172 | 1.890 | 1.837 |
| tsp | 2025-07 | x50 | +0.87 | none | 1.138 | 1.138 | 1.890 | 1.544 |
| tsp | 2025-07 | x100 | +0.87 | none | 1.138 | 1.138 | 1.890 | 1.124 |
| tsp | 2025-08 | x25 | +1.47 | none | 1.366 | 1.369 | 1.882 | 1.835 |
| tsp | 2025-08 | x50 | +1.47 | none | 1.366 | 1.369 | 1.882 | 1.543 |
| tsp | 2025-08 | x100 | +1.47 | none | 1.366 | 1.369 | 1.882 | 1.123 |
| tsp | 2025-09 | x25 | +1.44 | none | 1.145 | 1.150 | 1.905 | 1.832 |
| tsp | 2025-09 | x50 | +1.44 | none | 1.145 | 1.150 | 1.905 | 1.544 |
| tsp | 2025-09 | x100 | +1.44 | none | 1.145 | 1.150 | 1.905 | 1.125 |
| tsp | 2025-10 | x25 | +2.22 | none | 1.600 | 1.621 | 1.877 | 1.830 |
| tsp | 2025-10 | x50 | +2.22 | none | 1.600 | 1.621 | 1.877 | 1.546 |
| tsp | 2025-10 | x100 | +2.22 | none | 1.600 | 1.621 | 1.877 | 1.125 |
| tsp | 2025-11 | x25 | +2.44 | none | 1.110 | 1.142 | 1.874 | 1.830 |
| tsp | 2025-11 | x50 | +2.28 | none | 1.041 | 1.041 | 1.874 | 1.546 |
| tsp | 2025-11 | x100 | +2.28 | none | 1.041 | 1.041 | 1.874 | 1.126 |
| tsp | 2025-12 | x25 | +1.63 | none | 1.678 | 1.679 | 1.901 | 1.822 |
| tsp | 2025-12 | x50 | +1.63 | none | 1.678 | 1.679 | 1.901 | 1.543 |
| tsp | 2025-12 | x100 | +1.63 | none | 1.678 | 1.679 | 1.901 | 1.124 |
| tsp | 2026-01 | x25 | +2.04 | none | 1.288 | 1.292 | 1.853 | 1.814 |
| tsp | 2026-01 | x50 | +2.04 | none | 1.288 | 1.292 | 1.853 | 1.537 |
| tsp | 2026-01 | x100 | +2.04 | none | 1.288 | 1.292 | 1.853 | 1.121 |
| tsp | 2026-02 | x25 | +0.11 | none | 1.302 | 1.302 | 1.864 | 1.835 |
| tsp | 2026-02 | x50 | +0.06 | none | 1.289 | 1.290 | 1.864 | 1.690 |
| tsp | 2026-02 | x100 | +0.06 | none | 1.289 | 1.290 | 1.864 | 1.251 |
| tsp | 2026-03 | x25 | +0.00 | none | 1.799 | 1.799 | 1.811 | 1.822 |
| tsp | 2026-03 | x50 | +0.00 | none | 1.799 | 1.799 | 1.811 | 1.680 |
| tsp | 2026-03 | x100 | +0.00 | none | 1.799 | 1.799 | 1.811 | 1.247 |
| tsp | 2026-04 | x25 | +0.70 | none | 1.542 | 1.569 | 1.876 | 1.815 |
| tsp | 2026-04 | x50 | +0.70 | none | 1.542 | 1.569 | 1.876 | 1.673 |
| tsp | 2026-04 | x100 | +0.70 | none | 1.542 | 1.569 | 1.876 | 1.243 |
| tsp | 2026-05 | x25 | +2.08 | none | 1.339 | 1.375 | 1.869 | 1.788 |
| tsp | 2026-05 | x50 | +2.08 | none | 1.339 | 1.375 | 1.869 | 1.531 |
| tsp | 2026-05 | x100 | +2.08 | none | 1.339 | 1.375 | 1.869 | 1.124 |
| tsp | 2026-06 | x25 | +0.21 | none | 1.347 | 1.349 | 1.872 | 1.786 |
| tsp | 2026-06 | x50 | +0.21 | none | 1.347 | 1.349 | 1.872 | 1.531 |
| tsp | 2026-06 | x100 | +0.21 | none | 1.347 | 1.349 | 1.872 | 1.124 |
| tsp | 2026-07 | x25 | +1.76 | none | 1.352 | 1.364 | 1.856 | 1.793 |
| tsp | 2026-07 | x50 | +0.88 | none | 1.286 | 1.287 | 1.856 | 1.655 |
| tsp | 2026-07 | x100 | +0.88 | none | 1.286 | 1.287 | 1.856 | 1.236 |
| tsp | 2026-08 | x25 | +2.05 | none | 1.666 | 1.683 | 1.807 | 1.780 |
| tsp | 2026-08 | x50 | +2.05 | none | 1.666 | 1.683 | 1.807 | 1.648 |
| tsp | 2026-08 | x100 | +2.05 | none | 1.666 | 1.683 | 1.807 | 1.235 |
| tsp | 2026-09 | x25 | +1.58 | none | 1.316 | 1.334 | 1.821 | 1.772 |
| tsp | 2026-09 | x50 | +1.37 | none | 1.329 | 1.338 | 1.821 | 1.643 |
| tsp | 2026-09 | x100 | +1.37 | none | 1.329 | 1.338 | 1.821 | 1.233 |

