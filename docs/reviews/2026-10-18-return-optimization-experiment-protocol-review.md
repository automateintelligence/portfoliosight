# Return-optimization experiment: protocol review

Date: 2026-10-18 (owner timezone). Scope: protocol drafting, read-only data inventory and independent document review only. No optimizer, experiment harness, fits or backtests were implemented or run.

**Outcome:** ready for owner/Claude feedback as a reviewed proposal. Both second-pass reviews found no remaining P0/P1 findings; their remaining P2 corrections were applied and checked against the source and document. Numerical policy settings remain proposals, and implementation/execution remain unauthorized.

Protocol: [staged return-optimization experiment](../plans/2026-10-18-return-optimization-experiment-protocol.md). Motivation: [TSP diversification/downside investigation](2026-10-18-tsp-diversification-downside-investigation.md#interpretation-and-scope).

## Authority and review provenance

The owner authorized steps 1 and 2: write a concrete protocol and independently review it. Step 3, implementation and experiment execution, remains held for later explicit owner direction; Claude feedback is expected when available. Documentation commits follow the existing direct-main rule. This review does not approve production policy, deployment, a default switch or experiment execution.

The author used `gpt-6-astra` at xhigh effort. Two fresh independent native agents used `gpt-6-astra` at high effort, with read-only statistical and execution/provenance scopes. A separate `gpt-6.1-sol` high-effort agent applies document review fixes. These are disclosed same-host Codex fallback reviews, not Claude reviews or cross-host approval.

Initial review snapshot SHA-256: `de423f49d4a1df28b4168d0630fdfafc1f752b5a435dec3a4f504b1742cd7c38`. Both reviewers verified that snapshot. The source baseline inspected was main `5989f215fdae75b0ad2f433153c16dec73cc3535`.

## Read-only data inventory

- TSP: five fixed funds, zero minimum weights and uniform 60% caps. Price dates span 2003-06-02 through 2026-10-16; the date-only inventory found 5,836 common return dates beginning 2003-06-03.
- Example Portfolio: 23 fixed funds, zero minimum weights and uniform 25% caps. VWOB limits the common start: 3,363 common return dates beginning 2013-06-05, through 2026-10-16.
- Both saved five-year tensors report 1,260 rows. Calendar-year-end coverage candidates with five years of training and a full subsequent 252-row horizon are 2008–2024 for TSP and 2018–2024 for Example. These counts are coverage evidence, not independent statistical sample sizes; 252-row horizons can extend past the next calendar year-end.
- Current membership and adjusted-price vintages are not historical point-in-time membership/vintage archives. The protocol explicitly limits the inference accordingly.
- The owner identified an existing library of 1,000+ tickers. The protocol includes a separately bounded, predefined exploratory extension. More tickers can broaden menus, but cannot manufacture independent years or extend the history of the same 23-fund menu.

This inventory read metadata and date columns only. It did not estimate new outcomes or search portfolios.

## Initial independent findings

Both reviewers returned **REVISE**, with no P0 finding. The statistical review was `/root/protocol_statistical_review`; the execution review was `/root/protocol_execution_review`.

| ID | Severity | Finding | Required correction |
| --- | --- | --- | --- |
| S1 | P1 | Primary conditional-return aggregation did not identify which optimizer replicate supplied the policy. Bank agreement and sensitivity criteria were ambiguous for the stability alternative. | Use an explicit primary seed for return-policy comparisons, all five seeds for stability, and separate branch-specific bank and sensitivity rules. |
| S2 | P1 | Failure of point-estimate thresholds could be labeled no worthwhile benefit without an operational uncertainty rule. | Label it failure to meet observed screening criteria; retain inconclusive inference rather than imply equivalence or futility. |
| E1 | P1 | Solver failure, normal budget exhaustion, invalid proposals, failed starts and failed paired cells were not distinguished. | Define each status, candidate retention, optimizer response, failure-rate denominator and resource-stop behavior. |
| S3/E2 | P2 | The tolerance-based dominance relation could cycle and remove every candidate in a near-tied group. | Use an acyclic relation with no coordinate deterioration, apply tolerance only to strict improvement, and define ties relative to a global maximum. |
| S4 | P2 | Administratively immature horizons were not explicitly separated from mature horizons with missing data. | Retain both in the ledger, but count only mature missing outcomes against completeness. |
| E3 | P2 | The timing ratio, cache state, execution order and shared-work attribution could change the cost verdict. | Specify measurement boundaries, fresh arm-local caches, balanced deterministic order, an exact paired timing statistic and total union cost. |

The parent also requested retention of immutable private raw inputs and metadata for future replay: hashes alone cannot recover a source file after the mirror changes. No input copies are made during this protocol-only task.

## Corrections and final review disposition

Both reviewers examined the revised snapshot `c1b015b7f59d858f4c414826f4d23a386812ef6be990f2b66aad6d2b432eceb2`. The statistical lane returned **READY_FOR_OWNER_CLAUDE_REVIEW**, with one nonblocking P2 clarification. The execution lane requested one narrow P2 formula correction and stated readiness after that correction. Neither lane reported a remaining P0/P1.

All initial findings were addressed:

- **S1:** primary return-policy comparisons use optimizer seed `20261013`; the five optimizer seeds measure search stability. Return and stability branches have separate bank criteria. Single-seed sensitivities cannot certify cross-seed stability and are labeled accordingly.
- **S2:** failing observed screening thresholds does not imply futility, equivalence or a negative historical effect. Inferential uncertainty remains explicit.
- **E1:** ordinary budget exhaustion, invalid proposals, failed starts, failed paired cells and resource stops have separate statuses and a frozen denominator. Unexpected errors propagate rather than becoming successful fallback results.
- **S3/E2:** dominance permits no coordinate deterioration and applies numerical tolerance only to strict improvement; tie sets are defined relative to a global maximum. The cyclic three-candidate counterexample is an acceptance fixture for later implementation.
- **S4:** calendar-based administrative maturity is separate from mature missing outcomes, with explicit denominators and a retained ledger.
- **E3:** paired wall-time statistics, fresh arm-local caches, deterministic balanced order and shared-work attribution are explicit. Union-study timing is not labeled standalone production performance.

The final P2 corrections were applied without a third review cycle, following the owner's rule to re-review only while P0/P1 findings remain:

1. The invalid-growth and minimum-variance-anchor checks now use production's exact recentered replay growth, `g_t = 1 + r_t'w − mean_s(r_s'w) + (mu_s'w)/252`, rather than raw portfolio growth. The formula was checked against `portfoliosight/engine/ranges.py:166–170`; raw-input validity remains separate.
2. The optional library extension explicitly excludes the primary monthly-index bootstrap. Its potentially irregular annual origins produce paired descriptive summaries only, with no extension bootstrap confidence intervals or confirmatory verdict.
3. A parent self-check supplied the finite origin-ledger boundary: the month containing the latest first-observed fixed-menu price through the last completed month at the snapshot cutoff, currently June 2013 through September 2026. Training eligibility remains independently enforced.

The owner also removed the ENB exception during review. ENB requires demonstrated DR² benefit under the agreed criteria; negative, inconclusive, underpowered or inactive results cannot be bypassed using another reason. This is a resource-priority policy, not a proof that the two measures are equivalent.

Final corrected protocol SHA-256: `f2bc206db9aa92553372a76406862db602401d65a530d2d41ba02bc4fd670591`. The final file includes the P2 corrections plus status/link updates; the reviewers' exact snapshots above are retained rather than misrepresented as reviews of this later hash. Document whitespace, local references and the parent Conductor plan lint were checked; no product test suite or numerical experiment was run. Claude review remains pending.

## Policy choices for owner and Claude feedback

These are explicit proposals, not defects that an implementation agent should silently decide:

- `U = 0.60 Bad + 0.30 Typical + 0.10 Good`, the DR² bonus strength, and the allowed sacrifice limits. The accepted A/B example supports finite tradeoffs but does not uniquely identify these numbers.
- The veto on simultaneously worse Bad and Typical, and return-only Pareto filtering, are stronger preferences than an unconstrained four-objective weighted sum.
- The primary comparison uses a common candidate union to isolate the effect of the preference. It does not establish the standalone performance or production cost of two independent optimizers.
- The proposed 20-disjoint-year confirmation criterion cannot be met by the frozen Example data. This study can screen candidates and expose tradeoffs; it cannot satisfy that stronger automatic progression standard. The owner subsequently removed the separate-reason exception: ENB is permitted only after demonstrable DR² benefit under the agreed criteria. With the proposed confirmation gate, the current primary data cannot qualify. This policy does not assert that ENB and DR² are mathematically equivalent.
- The ticker-library extension remains exploratory, separately bounded and subject to the same execution hold. Cross-menu correlation and survivorship remain relevant even with many symbols.

The historical-tail limitation is substantive: a large number of overlapping monthly outcomes, simulated paths or bootstrap resamples does not create additional independent market years.
