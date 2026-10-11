# 44. sRGB8 coverage is written through binary16 and 32-bit float uniform colours are plain; the float32 partial-coverage residual stays a divergence

**Status**: accepted
**Date**: 2026-10-11
**Related Tasks**: phase1.10_compositor-float32-residual

## Context

`phase1.10_compositor-float32-residual` owns the float32 operation order of Painter's source-over onto a partly covered backdrop: 5 of the 16 RGB32F/L32F values of `quantisation-thirds` and the `group-masks` s2-s3 residual (20 631 RGB32F, 57 RGB16 and 3 709 sRGB8 values against r1; `parity/reports/phase1/compositor-mask-effects.md`, open items 1 and 2). Measurements of this task (`parity/reports/phase1/compositor-float32-residual.md`):

- **sRGB8 coverage.** Every sRGB8 difference of `group-masks` s2 lies on an even row y >= 32, where the group coverage (255 + y)/510 is half-way between two 8-bit codes. Per row, storing the lower code makes rows with y mod 64 < 32 exact and the upper code rows with y mod 64 >= 32; no other coverage value works. `UNORM8_write(binary16_nearest_even(coverage))`, the measured 8-bit write rule applied to the binary16 value, gives the required code on all 254 rows and makes the whole sRGB8 map of s2 and s3 exact. Rounding toward zero to binary16 fails 64 rows, `rint(255 h)` 151 values. The measured sRGB8 colour thresholds have at most 11 significant bits, consistent with the GPU passing the outputs of sRGB8 targets through binary16; the RGB8 colour rule was fitted exactly without it.
- **32-bit float uniform colours.** On `group-masks` row 0 the group colour is the fill colour itself: `float32(v)` reproduces every texel, the inherited `1 + (v - 1)` leaves 8 values off. No golden supports `1 + (v - 1)`; with `float32(v)` one more `quantisation-thirds` value is exact.
- **Float32 operation order.** Painter's renderer is Vulkan (its log: the VMA allocator). On the recording GPU, `a / b` in Vulkan (SPIR-V) and in D3D12 equals `a * RCP(b)` with the measured reciprocal table on every mantissa tested. The group composite and the stored group coverage are pinned exactly (one float32 group colour per row of the red component, 254 rows). Thousands of float32 orders of the W3C §5.1 source-over (straight and premultiplied, fma contractions, three reciprocal forms, lerp and weight forms, other coverage formulas, quantised opacities, distributed normalisation, enumerative synthesis up to 9 operations) give no exact model. In the cleanest sub-case (backdrop colour 0, result 0.45 / coverage) four rows lie where no `0.45 * RCP(x)` can land for x near the coverage. The best inexact model (an fma chain of the three premultiplied terms divided through the hardware reciprocal) leaves 12 071 RGB32F and 36 RGB16 values.

## Decision

1. The coverage plane of an sRGB8 intermediate is written as `WriteUnorm(binary16_nearest_even(a), 8)` on the CPU and GPU evaluators, bit for bit (`arith::HalfNearestEven`, `TileFormat::halfCoverage`). RGB8 and L8 coverage keep the plain 8-bit rule until a recording distinguishes them.
2. A uniform colour on a 32-bit float channel is its float32 value.
3. Both change results of projects stamped `painter-12.1-isolated-linear`, so they form a new profile, `painter-12.1-isolated-half-alpha`, stamped into new projects (decision 017 pinning). `painter-12.1-isolated-linear` stays registered and evaluates bit for bit as before.
4. The inexact float32 model is not adopted. The float32 and RGB16 partial-coverage residual stays published as a divergence in `quantisation-profile.json` and `masks-levels.json`; an exception-register entry is the owner's decision (asked through the task).
5. A diagnostic Tier 0 recording is specified for the owner (report, section "Recording request"): isolated groups over an opaque black root, a colour-0 or field-B child under the row-ramp mask, a per-texel bitmap or uniform fill at opacity 0.5 (Normal, Screen) and 0.3, on RGB32F, L32F, RGB16, sRGB8, RGB8 and L8. It separates the numerator from the division as far as one recording can, and settles the RGB8/L8 coverage rule.

## Alternatives Considered

- Apply the binary16 coverage rule to every 8-bit intermediate. Rejected: no golden distinguishes it on RGB8/L8, and the RGB8 colour path shows no binary16.
- Adopt the best inexact float32 model. Rejected: closer is not exact, and it would hide an unexplained residual (panel 3-0).
- Change `painter-12.1-isolated-linear` in place. Rejected: a profile id never changes meaning (decision 017).

## Consequences

`group-masks` s2-s3 sRGB8 becomes exact; RGB32F and RGB16 keep their residuals (20 631 and 57 values; `quantisation-thirds` keeps 5 of 16 float values). New projects are stamped `painter-12.1-isolated-half-alpha`; the census stamps it. Model panel 2026-10-11 (cx/gpt-6-astra, kimi/kimi-k3, xai/grok-4.5): C1 (binary16 sRGB8 coverage) agreed 2, partly 1 (adopted as a behavioural rule; the export does not show the physical storage path); C2 (sRGB8 only; specify RGB8 and L8) agreed 3-0; C3 (plain float32 uniform) agreed 3-0; C4 (new profile id) agreed 3-0; C5 (no inexact model, divergence, owner decides) agreed 3-0; C6 (the recording request) partly 3-0 (a diagnostic that narrows the order, not a guarantee; L8 added); C7 (no single float32 division of the W3C numerator) agreed 1, partly 1, disagreed 1, so the record states only that the literal `0.45 * RCP(x)` form is excluded.
