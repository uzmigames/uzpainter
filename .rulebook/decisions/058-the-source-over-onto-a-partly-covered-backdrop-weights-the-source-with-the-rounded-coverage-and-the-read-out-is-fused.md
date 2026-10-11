# 58. The source-over onto a partly covered backdrop weights the source with the rounded coverage, and the read-out is fused

**Status**: accepted
**Date**: 2026-10-11
**Related Tasks**: phase1.10_compositor-float32-residual

## Context

Decision 044 left the float32 order of Painter's source-over onto a partly covered backdrop unidentified: `group-masks` s2-s3 kept 20 631 RGB32F and 57 RGB16 values one step off, `quantisation-thirds` 5 of its 16 RGB32F/L32F values. The owner answered q1 with the diagnostic recording, now on main as Tier 0 `group-coverage-order` (decision 048; r1 = r2 on all 24 maps). Measurements (`parity/reports/phase1/compositor-float32-residual.md`, section "The diagnostic golden"):

- **Exact coverage rows were already right.** With a colour-0 child, the W3C order `fl(fl(S as) Rcp_hw(ao))`, `ao = fl(0.5 + 0.5 m)`, reproduces every row whose coverage sum is exact in float32 (rounding error at most 1/8 ulp) and no other row. On those other rows no float reciprocal and no real factor or affine single rounding of S fits: the result contains a second S-dependent rounding that vanishes when the coverage sum is exact.
- **The order.** `wb = fl(ab fl(1 - as))`, `ao = fl(as + wb)`, `ws = fl(ao - ab)`, `C = fl(fma(ws, Cs, fma(ab, fl(as B), fl(wb Cb))) Rcp_hw(ao))` reproduces all RGB32F, L32F and RGB16 maps of the four sets (Normal 0.5, field-B child, Screen 0.5, Normal 0.3) bit for bit. The weight of the source alone is re-derived from the rounded coverage. Every other association of the three terms, the W3C weights `as (1 - ab)`, other coverage forms and the correctly rounded reciprocal fail.
- **Zero coverage.** With opacity 0.3 over a mask of 0 the result is `fl(fl(S as) Rcp_hw(as))`, not S: the formula also applies over a backdrop layer of coverage 0. The masked child, the first layer of the group, is copied: composited over the empty start it would differ.
- **Opaque backdrop.** With `ab = 1` the formula is exactly the fitted opacity mix `fl(fl(Cb (1 - as)) + fl(B as))`; the fitted opaque mixes (Replace, ColorBurn, effects, normal maps) are kept.
- **Confirmation.** With the order, `group-masks` s2-s3 are exact on every map and both recordings. `quantisation-thirds` RGB32F is exact only if the isolated root's read-out over the base is one fused operation, `fma(C - base, a, base)` (the two-rounding form leaves 3 of 12 values off; every UNORM, sRGB8 and 16-bit float map is exact either way). Its L32F map is exact only if a uniform colour on a grey channel is `float32((r + g + b) / 3)` of the API's double components (one value of four decides). `blend-inputs` s2 stays exact. Every other published fit is unchanged: `blend-kernels.json` residuals identical, `colour-transfer.json` and `uv-sampling.json` byte-identical, `masks-levels.json` changed only by the `group-masks` residuals dropping to 0.

## Decision

1. A layer composited onto a backdrop that is not opaque, including a backdrop layer of coverage 0, uses the coverage-weighted order above; the first layer of an isolated list is copied over the empty start. Over an opaque backdrop the fitted mixes stay.
2. The read-out of an isolated root over the channel base is `fma(C - base, a, base)`.
3. A uniform colour on a grey channel is the float32 of the mean of its components as given.
4. These change results of projects stamped `painter-12.1-isolated-half-alpha`, so they form a new profile, `painter-12.1-isolated-coverage-weights` (flags `coverageWeights`, `fusedReadout`, `uniformGreyUnrounded`, with decision 059's `srgb8HalfCoverageFromHalf`), stamped into new projects (decision 017 pinning). Earlier profiles stay registered and evaluate bit for bit as before.
5. CPU reference (`arith::Composite`) and GPU kernel (`evaluator_blend.hlsl`, flags `FLAG_COVERAGE_WEIGHTS`, `FLAG_EMPTY_BACKDROP`, `FLAG_FUSED_READOUT`) implement it operation for operation; the residual is no longer a divergence and the task closes.

## Alternatives Considered

- Keep the W3C straight-colour order and publish the residual. Rejected: the new order is exact on every map of three goldens and changes no other fit.
- Apply the weights only for `0 < ab < 1`. Rejected: the zero-coverage row needs them.
- Treat the read-out fma and the grey mean as unproven and leave the two `quantisation-thirds` deciders open. Rejected: each is the only tested form that makes its map exact; their evidence is thin (3 of 12 and 1 of 4 values) and is stated as such.

## Consequences

`quantisation-thirds` (r1), `blend-inputs` s2, `group-masks` s2-s3 and `group-coverage-order` are exact on every map, CPU and GPU (DX12). New projects are stamped `painter-12.1-isolated-coverage-weights`; the census stamps it. Model panel 2026-10-11 (cx/gpt-6-astra, kimi/kimi-k3, xai/grok-4.5): C1 (the order, the fused read-out and the grey mean as a new profile; close the task once GPU = CPU and the suite pass) agreed 1, partly 2 (the read-out and grey rules rest on few deciding values: label them measured, not explained); C4 (weights also over a zero-coverage backdrop layer, first layer copied) agreed 3-0.
