# Gate change: the Simulation control and the `e` address key

Date: 2026-10-17. For the owner and the coordinator.

Instruction (plan `docs/plans/2026-10-16-simulation-engines-phase1-plan.md`, Phase 5, relayed by
the coordinator): add the "Simulation" control, the `e` key in the address, the engine tag and
the per-engine ranges to the page; update and re-freeze any frozen gate test the change makes
false.

## What changed in the product that the gate reads

- `web/src/state/url.ts`: `UrlState` gains `engine` (`replay | garch | copula`); `decode` reads
  `e` (an unknown value reads as `replay`); `encode` writes `e` last, after `x`, and only when it
  is not `replay`. The canonical order is `u f unit c lb g r d t x e`.
- `web/worker/share.ts`: the share validator accepts `e` with the shape
  `^(?:replay|garch|copula)$` and mails the page codec's form of the link.
- `web/src/sections/Settings.tsx`, `controls/ResultStrip.tsx`, `controls/RiskSlider.tsx`: a
  Simulation radio group (`engine-replay`, `engine-garch`, `engine-copula`) and a tag
  (`engine-tag`) beside the strip's label and the risk slider's readouts.
- `web/src/math/portfolio.ts`: `yearRange(s, t, engine?)` and `riskSliderDomain(engine?)`; without
  an engine, and for the tensor's default engine, they answer exactly what they answered before.

## Every gate file changed

| Gate file | Assertion, leg | Before | After | Property it protects | Why the new form is not weaker |
|---|---|---|---|---|---|
| `tests/test_a_ps_36_url_codec_roundtrip.py` | A-PS-36, all four legs | The key set of every encoded URL is `{u, f, unit, c, lb, g, r, d, t, x}`; generated states and the spec example have no engine | The key set is `{u, f, unit, c, lb, g, r, d, t, x, e}`; every generated state carries an `engine`; the decoded spec example has `engine: "replay"`; one added example: `…&t=hud&x=1&e=garch` re-encodes to itself, `e` follows `x`, `replay` is not written, and an unknown `e` (`foo`, `GARCH`, `garch,copula`, empty) reads as `replay` and is not written back | `decode(encode(state)) == state` for every reachable state, only spec keys are written, unknown keys are dropped, `r` is clamped | Every earlier observation is kept, including the `seenKeys == ALLOWED` check (the generator must now produce `e` as well) and the exact-equality comparison of the decoded state (which is what makes the missing field in the old generator fail). The legs gain checks; none loses one. |
| `tests/test_a_ps_38_share_validators_template_caps.py` | A-PS-38, one new leg | The validator's keys and value shapes are pinned through the themes only | A new leg "a link in any of the three simulations is sent and an unknown simulation is refused": `e=replay\|garch\|copula` is sent with `e` after `x` (none for `replay`); `foo`, `GARCH`, `Garch`, `vine`, `garch,copula`, `garch%20`, empty are refused `400 invalid_url` with zero outbound calls. `EXPECTED_TITLES` names it. | The one outbound channel mails only the page's own key shapes | A leg added; the seven existing legs are untouched. |
| `tests/test_a_ps_51_url_reproduces_view.py` | A-PS-51, the one example | The full state is the two sliders, the theme, the unit and details; the allowed keys are `u f unit c lb g r d t x`; six keys are compared in the fresh context | The state also switches the Simulation to the volatility model in Settings; `e` is in the allowed keys, in the keys that must be present (`u r d t x unit e`), written last, and kept in the fresh context; the readouts also compare the `engine-tag` text; the first context shows "History replay" and no `e` before the switch | The address reproduces the view, including the simulation behind every figure | Every earlier observation is kept (the keys, their values, the six readouts, the clipboard, `share-link`); the fresh context must now also reproduce figures that depend on `e`, so a lost `e` fails it. |
| `manifest.yaml` | A-PS-36, A-PS-38, A-PS-51 claims | Claims name the ten keys, the four themes, and the six keys | Claims name `e` (the simulation, written last, only when not `replay`), the three simulations, and the simulation among the changed controls and the engine tag among the compared readouts | Claim text matches the tests | Text only. |
| `.frozen` | A-PS-36, A-PS-38, A-PS-51 | test-file digests `b08bee66...`, `71ed306d...`, `7bfe013f...` | see the commit (`conductor gate lint` ok, `freeze`, `verify` clean) | Tamper evidence | Re-frozen with `conductor gate lint` (ok) and `conductor gate freeze`; `conductor gate verify` reports the baseline intact. Only these entries moved. |

`docs/specs/2026-10-13-portfoliosight-demo-design.assertions.md` (the assertions source) carries
the same changes in the A-PS-36, A-PS-38 and A-PS-51 sections and in the index line of A-PS-38, and
`assertions/2026-10-13-portfoliosight-demo-design/INTERFACES.md` the new `yearRange` and
`riskSliderDomain` signatures, the `engine` field of `UrlState`, and the new test ids
(`engine-replay`, `engine-garch`, `engine-copula`, `engine-tag`).

## Left as they are, on purpose

- A-PS-45 (risk-slider readouts): true as written. With History replay selected, which is the
  default, the readouts, the strip and the requests are what they were; the only request while a
  slider moves is `POST /api/range` for the mix on screen, and it names no engine under History
  replay (the new web tests check the body).
- A-PS-48 (plain language): true as written. The Simulation control adds the three names and
  their one-line descriptions to the default view, none of them a forbidden word; the technical
  names stay behind details and History replay's Method line is the one the test already reads.
- A-PS-41, 42 (first screen, phone layout), A-PS-43, 46, 47, 49, 50, 53 and the vitest
  assertions A-PS-34, 37, 39, 40: they read the kept fields, the moments, the weights or the
  Worker, none of which moved.
