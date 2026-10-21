# 346. Tier 0 `effect-order` s0–s5 and s7 replay exactly: the content fill effect uses the layer mix, and the starter Blur at its recorded configuration equals the content rounded toward zero to binary16. This is not a Blur implementation

**Status**: accepted
**Date**: 2026-10-21
**Related Tasks**: phase3.2_proc-filter-families, phase1.11_compositor-mask-effects

## Context

Item 3.4 of `phase3.2_proc-filter-families` reads "Tier 0 `effect-order` s0–s5, s7 exact". Decision 069 moved these sets here from phase1.11 3.3. The golden is a fill layer of fields A (`field-a.png`: codes 257 x, 257 y and 256 x + y) on a 256 x 256 grid set, with RGB16 User0 and sRGB8 User1. It holds a fill effect F (uniform 0.8/0.2/0.4, Multiply, 0.7), levels L and the starter-asset Blur B (`s:starterassets u:filter n:Blur=`, default parameters, Normal 1) in six orders, plus s6 (L alone) and s7 (B alone). Both recordings are identical. Decision 069 forbids any stand-in for Blur ("identity, a box blur") used to make s0–s5 pass.

These are the measurements, made against the private golden with the evaluator's own F, L and store rules. The content was staged at the Blur's position: below it on the evaluator, then the Blur model in float32, then the rest on the evaluator.

1. **Blur.** s7 User0 equals `write16(rtz16(c / 65535))` on all 196 608 values. Here `rtz16` rounds the float32 operand toward zero to binary16, and `write16` is the evaluator's UNORM16 write rule (ties down). Rounding to nearest even misses 94 734 values. Every s7 border texel keeps its field value. At x = 0 the R code is 0, and any weight w on the neighbour at distance k would add `257 k w` codes. So the off-centre weight, weighted by distance, is below 0.5 / 257 < 0.002 in every direction, and wrapping would cost far more. Inside the texture a symmetric kernel keeps linear fields, so s7 alone cannot show a kernel. The non-linear contents of s0 (FLB) and s2 (LFB), after the gamma 1.6 levels, would show one. There the same rule misses only 2 and 1 values, and item 2 below explains all three. **On this content, at this resolution and these parameters, no blur kernel acts. The filter's whole measured effect is the binary16 rounding of its output.**
2. **Content fill effect.** After 1, every remaining miss is a fill effect F evaluated over a content. s3 LBF, where F's output is the export, misses 20 values; s4 BFL misses 32; s0, s1 and s2 miss 1 or 2. All are one 16-bit code on the B component. The evaluator blended content fill effects with the mask effect mix: `v = fl(a + fl(fl(r - a) x alpha))`, with `r = fl(a x b)`, every operation a float32 operation. On s3, the layer mix `v = fl(fl(a x fl(1 - alpha)) + fl(r x alpha))` matches all 196 608 values. The two mixes are the same function in exact arithmetic. They differ only in the float32 operations and their rounding order: one subtraction, product and sum, against one complement, two products and one sum. `fma(a, fl(1 - alpha), fl(r x alpha))` and `fma(r, alpha, fl(a x fl(1 - alpha)))` also match s3. The fused mix `fma(fl(r - a), alpha, a)` misses 10 values, and the uniform or alpha rounded to binary16 misses over 150 000. The layer mix is what the evaluator already uses for an opaque backdrop: `arith::Composite` without `effectMix`. Masks keep the effect mix: `masks-levels.json` `mask-stack-effect-mix`, where the layer mix misses 6 of 65 536.

## Decision

1. **Content fill effects take the layer mix.** `RunEffects` (evaluate.cpp) sets `effectMix` only for a mask stack (`CacheKind::Mask`). A content fill effect over an opaque backdrop is `fl(fl(a x fl(1 - alpha)) + fl(r x alpha))`, the existing non-effect branch of `arith::Composite` and of the blend kernel. Nothing else changes: masks, layer composites, the coverage-weighted paths and the W3C path over a partly covered backdrop all stay as they were. The fma variants that also match s3 are not taken. The evaluator's existing branch is the plain order, and no golden separates them.
2. **The recorded Blur, and only it.** `dag.h` `kRecordedBlurAsset` (`uzasset://filter/blur@1`) is evaluated as `DagEffect::Kind::RecordedBlur`: the content rounded toward zero to binary16 (`BlendOp::sourceHalfTowardZero`, Normal at opacity 1 over the same content, so the result is that value), stored in the channel format. CPU and GPU lanes share the rule (`kFlagSourceHalfTowardZero`). Every one of these conditions must hold, or the edit fails with `unsupported_node` naming phase3.2 item 2.5 and this decision, before anything is evaluated (`RecordedBlurRefusal`, dag.cpp):
   - the asset is the recorded Blur;
   - no parameter, preset, image input, output mapping, mask output or resolution override is set (the defaults);
   - the channel's blending is Normal at opacity 1;
   - the channel format is RGB16 or sRGB8;
   - the set is 256 x 256;
   - colour management is legacy;
   - the effect is in a content stack;
   - the content has no coverage plane (a content that can leave texels uncovered is refused at evaluation).
3. **This is not a Blur implementation.** It reproduces one recorded configuration where the measured Blur is the identity up to binary16. Any other parameter value, resolution, format or content of a different kind is unknown, and is refused as above, never approximated. The production path did not change. The capability inventory keeps filter effects as release gaps (`support.cpp` `EffectGap`, `compositor-capabilities.json`), so an edit that would add one is still refused before mutation. No asset record names the Blur, the alias tables stay empty, and no family is certified. The real Blur family (decision 069 §3: built on phase3.1's blur operators, calibrated, with a declared domain) is still phase3.2 items 2.1, 2.5 and 2.6.
4. **Evidence.**
   - `tests/evaluator/test_compositor_mask_effects.py::test_content_effect_order_equals_the_golden`: s0–s5 and s7, RGB16 and sRGB8, both recordings, on CPU and DX12.
   - `::test_blur_outside_the_recording_is_refused`: one Blur parameter, Multiply blending, 512 x 512, RGB32F and another filter asset are each refused with `unsupported_node`.
   - `masks-levels.json` entry `content-effect-order` is now fitted with residuals instead of a gap.

## Alternatives Considered

- **Keep the effect mix and record the residuals.** Rejected: it is not exact, and the layer mix explains every value.
- **Implement a Blur kernel (Gaussian, box) with a small radius.** Rejected: the s7 borders bound any kernel weight below 0.002, so no kernel is identified. Picking one would be the stand-in decision 069 forbids.
- **Evaluate any Blur request as the binary16 rounding.** Rejected: outside the recorded configuration that is exactly the identity stand-in of decision 069.
- **Change `FilterEffectReference` (decision 328 §3) to the layer mix as well.** Not done: a filter effect's own mix is observed only at Normal 1, where both mixes give the same value. It stays as decision 328 recorded it until a golden records a filter at another mode or opacity.

## Consequences

- phase3.2 item 3.4 is checked. phase1.11's order of fill and levels effects is now golden-verified, and its content fill-effect mix is corrected (decision 069's "a difference there is a bug in phase1.11's code").
- `support.cpp` still lists content fill effects as a release gap with the reason "every recorded content-effect order holds the Blur filter (decision 069)", and so does `compositor-capabilities.json`. Lifting them to supported is a capability-inventory change for the coordinator. This decision does not make it.
- Items 2.1, 2.5, 2.6, 3.1 and 4.1 are unchanged. The Blur stays uncertified.
