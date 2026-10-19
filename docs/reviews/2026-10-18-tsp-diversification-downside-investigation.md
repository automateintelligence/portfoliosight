# TSP diversification slider and downside returns

Date: 2026-10-18 (owner timezone). Status: targeted read-only investigation complete; no product fix applied.

## Finding

The reported worsening Bad return is reproduced and consistent with the current objective. No sign, percentile-label or compounding error was found in the targeted check. The diversification slider maximizes minimum-torsion ENB at approximately fixed chart volatility while accepting lower expected return. It does not minimize loss probability or tail-loss severity. Both the lower return center and the changed historical distribution contribute in this example.

Owner view: <https://portfoliosight.ai/?u=tsp&lb=5y&r=36.382658&d=0&t=hud>. Here `r` is risk-grid position, and `d=0` is the frontier end of the diversification slider. Moving down increases `d` toward one without changing the risk-slider position.

## Evidence and limits

Source: main commit `a3bb4d142d1b1f4605b236c8fb39fa9009eb7418`. Artifact: `/mnt/d/portfoliosight-data/tensors/2026-10-16-0.2.0/63643e52f0386317/5y.json`, TSP five-year view, built `2026-10-17T09:02:49Z`.

The live hosts returned Cloudflare challenges to automated requests; the browser helper also failed to start within its startup deadline. The mirror's current pointer is stale. Consequently these results establish behavior on the identified real saved artifact, not current production identity or the exact response the owner received.

Reconstructing the 1,260 × 5 daily sample from the five mirrored TSP price files reproduced its recorded SHA-256 exactly: `d6f782a9947c0fad3a8b85f0ff6906160eff4b1e7a9c2de8e270ccd4eeeba24e`.

An independent day-by-day bootstrap-index recurrence matched the production indices. Direct multiplication of 252 daily growth factors matched production's count-matrix/log compounding within `1.33e-14`. Recomputed stored ranges in both adjacent columns 36 and 37 had maximum discrepancy zero. These were bounded numerical probes, not a full test suite or rebuild. No mirror or provider writes occurred.

## Exact replay results at the requested risk position

The following recomputes the replay distribution for the actual interpolated portfolio weights at `r=36.382658`. Percentages are annual returns except chart volatility.

| Slider d | Bad | Typical | Good | Chart expected return | Chart volatility | ENB |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0: frontier | −12.4479% | 9.8229% | 34.5429% | 9.4679% | 12.5342% | 2.8520 |
| 0.25 | −13.4755% | 9.4007% | 35.4039% | 8.9893% | 12.5336% | 3.1446 |
| 0.50 | −14.5085% | 8.8968% | 35.0408% | 8.5107% | 12.5332% | 3.3398 |
| 0.75 | −15.1824% | 8.3420% | 34.2959% | 8.0321% | 12.5336% | 3.4495 |
| 1: maximum ENB found | −15.3683% | 7.9122% | 33.7381% | 7.5536% | 12.5342% | 3.4833 |

Typical is the median; Bad and Good are the 2.5th and 97.5th percentiles. Bad is neither loss probability nor maximum possible loss. Good is not monotonic across these samples.

The browser's initial interpolated endpoint Bad estimates are −12.4582% and −15.3845%. The exact recomputation preserves the direction. Across all five sampled positions and three percentiles, the largest interpolation discrepancy is 0.06131 percentage points, far smaller than the 2.92-point downside change.

## Why the result occurs

At unchanged chart volatility, lowering the return center can worsen the lower tail. A simple normal approximation illustrates this: Bad is approximately mean minus 1.96 times volatility. The actual dashboard uses compounded block replay rather than that approximation, so distribution shape also matters.

Holding only the diversified portfolio's daily mean at the frontier portfolio's mean raises its Bad from −15.3683% to −13.7315%. It remains worse than the frontier's −12.4479%. This counterfactual assigns about 1.64 percentage points of the deterioration to the lower center and 1.28 points to the changed historical shape; that decomposition depends on the counterfactual order.

| Replay diagnostic | Frontier | Maximum ENB |
| --- | ---: | ---: |
| Annualized raw daily sample standard deviation | 12.5600% | 12.5891% |
| Standard deviation of compounded annual replay returns | 11.7606% | 12.3809% |
| Mean compounded annual replay return | 10.1474% | 8.1738% |
| Frequency of annual losses among 2,000 paths | 19.3% | 25.9% |
| Frequency of annual losses exceeding 20% | 0.45% | 0.90% |

Those frequencies are model outputs, not independently validated real-world probabilities. Chart risk uses a shrunk covariance matrix; replay retains the historical distribution, including blocks and compounding. Equal chart volatility therefore does not imply equal terminal replay dispersion or equal tail shape.

The portfolio changes are substantial: G falls from 21.60% to essentially zero; C from 60.00% to 18.56%; F rises from zero to 29.98%; S from zero to 25.14%; I from 18.40% to 26.32%. The ENB objective distributes variance contributions more evenly while keeping their aggregate volatility approximately fixed. It does not promise fewer or smaller losses.

## Dashboard trace

- `web/src/state/url.ts:26`: URL risk/diversification positions.
- `web/src/controls/DivSlider.tsx:38`, `web/src/state/store.ts:620`: down changes diversification while preserving risk position.
- `web/src/math/view.ts:96`: selected weights and ranges use the same slider positions.
- `web/src/math/portfolio.ts:130`: displayed percentile interpolation.
- `web/src/state/useExactRange.ts:28`: exact requests identify tensor and weights; aborted/stale requests cannot replace a different selection's result.
- `web/src/api/http.ts:166`: response bad/typical/good map to low/typical/high without sign reversal.
- `web/src/App.tsx:407`: the separate risk-slider readout intentionally describes the frontier portfolio. The Selected mix strip describes the selected portfolio.
- `portfoliosight/engine/ladder.py:152`, `:173`, `:303`: fixed-risk constraints and progressively lower return floors.
- `portfoliosight/engine/torsion.py:95`: ENB measures entropy of variance shares, with no downside objective.
- `portfoliosight/engine/ranges.py:164`: daily recentering, compounding and percentile calculation.
- `portfoliosight/engine/stats.py:46`: shrunk chart covariance.

## Interpretation and scope

Moving right along the frontier generally takes more volatility for higher expected return. Moving down at a fixed horizontal position is a different operation: it gives up expected return for a higher diversification score while keeping volatility roughly fixed. A frontier point is not inherently the worst downside portfolio among all portfolios at that same volatility.

The numerical check supports the current calculation, not a claim that the existing optimization objective matches every owner's notion of safety. Neither an ENB nor a DR² score alone guarantees improved lower-tail returns. Phase 2's validation must report actual downside outcomes rather than imply that a higher diversification score guarantees them.

Owner separately authorized Phase 2 on 2026-10-18 and clarified that selecting ENB or DR² must select its actual optimized portfolio and consistent dashboard displays. That requirement is being reconciled in the design spec and plan; it is not a finding that changes the arithmetic in this investigation.
