## 1. Prerequisites
- [x] 1.1 Prerequisites accepted: phase0.3_painter-oracle-recorder, phase0.5_private-oracle-store, phase0.6_tier0-semantics-goldens, phase0.6_tier0-defaults-templates, phase0.6_tier0-api-probes

## 2. Implementation
- [x] 2.1 Stability comparison tool under `tools/parity/fit/`: decode each golden's recordings at native depth, compare them, and compute max |Δ|, mean |Δ| and differing-texel count; readbacks compared for equality
- [x] 2.2 Classify each channel type by measured storage format as `stable` or `unstable`; exclude unstable goldens from exact admission and record their statistics as exception evidence
- [x] 2.3 Fit the 32 `BlendingMode` members from the sweeps (formula, clamping, colour space, public source) into `parity/semantics/blend-modes.json` with residuals
- [x] 2.4 Settle the evaluator profile from the three-1/3-opacity-fills experiment and write `parity/semantics/evaluator-profile.json` with the profile id `painter-12.1-<profile-id>`
- [x] 2.5 Fit the sRGB transfer function against IEC 61966-2-1 from the ramps into `parity/semantics/srgb-transfer.json`
- [x] 2.6 Fit the default height→normal method into `parity/semantics/height-to-normal.json` (the second method and the strength sweep moved to `phase0.7_tier0-semantics-ui-cases` by owner answer, 2026-10-10; recorded there as a `gap` entry)
- [x] 2.7 Fit the `BilinearHQ` kernel into `parity/semantics/resampling.json` and the `AO_Mixed` operator into `parity/semantics/ao-mixed.json`
- [x] 2.8 Write `parity/reports/phase0/tier0-stability.md`: per-channel-type stability, per-golden recording comparison, and the settlement table of every `04-layer-stack-and-compositing.md` §9 item with golden hashes and residual

## 3. Tests
- [x] 3.1 Schema test: every `parity/semantics/*.json` entry validates against the public schema and names a public source and a residual
- [x] 3.2 Guard test: the published fits and report pass the repository guard (no recorded value, no store-indexed hash as content)
- [x] 3.3 Reproduction test on the owner's machine: rerunning each fit against the private goldens reproduces the published residual
- [x] 3.4 Classification test: a synthetic pair of recordings differing in one texel is classified `unstable` with count 1, and an identical pair `stable`

## 4. Acceptance
- [x] 4.1 Child acceptance (contributes to P0-TIER0): stability classified for every golden and channel type; first fits published with sources and residuals; settlement table complete; guard and schema pass

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [x] 5.1 Update or create documentation covering the implementation
- [x] 5.2 Write tests covering the new behavior
- [x] 5.3 Run tests and confirm they pass

## Evidence (2026-10-10, owner's machine, oracles `12.1.0+js-api.1.1.20`)
- `python -m tools.parity.fit run` wrote the six `parity/semantics/*.json` files and `parity/reports/phase0/tier0-stability.md`; `python -m tools.parity.fit check` reproduced all six exactly.
- Stability: 59 goldens, 53 stable, 6 unstable (quantisation-thirds, blend-inputs s2, ao-mixed s1 AO_Mixed, mask-stack BaseColor, and two API probes whose readbacks depend on the save/reopen condition); unstable goldens not admitted as exact, statistics in report §4.
- Fits: 51 entries (6 exact, 43 calibrated, 2 gap); 04 §9 items settled: 0 of 11, each open item with its reasons in report §6.
- Gate: mypy (138 files) clean, ruff check clean, ruff format --check clean on tools/parity/fit and tests/parity/fit, pytest 747 passed, guard 0 blocked (store index, 722 hashes).
