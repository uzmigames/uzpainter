# 224. 8-bit sRGB magnification is one probe of the sRGB8 texture unit, and P20-A's BaseColor is exact

**Status**: accepted
**Date**: 2026-10-13
**Related Tasks**: phase1.15_compositor-colour-fits

## Context

Decision 218 found that the evaluator's 8-bit sRGB magnification was wrong and was not refused. The evaluator filtered the float32 decodes of an 8-bit sRGB bitmap with the float32 texture's filter (decision 174), and P20-A's BaseColor (`tier0/api-probes/phase1-fill-channel-defaults`: the 8-bit sRGB checker magnified 16 times, Repeat) missed 8 264 of 65 536 texels by one sRGB8 code. Decision 174 had the same path exact on `srgb-bitmap-variants-v2` s2 (magnified 2 times).

Decision 209 measured the hardware's single-probe sRGB8 rule exactly (61 440 of 61 440 samples). Decision 219 implemented the whole sRGB8 texture unit (`texture_unit.cpp` `Srgb8Filter`, steps 5' and 6'; HLSL `TuSrgb8Channel`), but used it only for minification.

## Findings

1. **The two rules agree on one probe.** For one probe, step 6' adds a truncation to max(coarse(E), -6) - 16 that decision 209's rule does not have. It never changes the binary16 result:
   - every two-tap probe, that is all 65 536 code pairs at weights 1-255 (16 711 680 probes);
   - 8 000 000 random four-tap probes with the projection's 8-bit weights (codes 0-255, and codes 0-23 where the truncation can act).

   The comparison script is in the scratchpad (`mag/cmp.py`). The native `sources` case keeps a check of it.
2. **The weights stay the projection's.** The unit's magnifying probe splits its weight with rule F (w11 rounded half up). The evaluator's magnifying path rounds w11 half down (decision 060, measured on every magnifying golden). Only the summing arithmetic is shared: the four taps and weights of `ProjectTexel` go to the unit as one probe (`tu::Srgb8Probe`).
3. **Goldens** (CPU store, counts against both recordings). Every test below ran with the prototype of decision 209's rule. P20-A, `srgb-bitmap-variants-v2` and the native `sources` case ran again through the unit, and all passed. The others are covered by finding 1.
   - P20-A BaseColor: exact on 65 536 of 65 536 texels, r1 and r2. `test_facade_fill_channel_defaults_equal_painter` passes with the BaseColor exclusion removed.
   - Still exact: `srgb-bitmap-variants-v2` s0-s8 (`test_srgb_variants_equal_painter_files`, s2's 8-bit ramp magnified 2 times included), `export-ocio-encode-legacy` s3 and s5 (`test_srgb8_bitmap_equals_painter_files`), `export-ocio-encode` (`test_ocio_encode_equals_painter_files`), `export-bit-depth` (`test_srgb8_material_channels_equal_painter_files`) and `export-l8-material` (`test_l8_material_channels_equal_painter_files`, which does not use this path).
   - At 1:1 the identity projection gives one tap of weight 256, which returns its decode. The 1:1 cases, the Wand's included, cannot change.

## Decision

1. **An 8-bit sRGB bitmap magnified or at 1:1 by a bilinear filter** (`DecodedImage::srgb8`) is filtered as one probe of the sRGB8 texture unit's sums. The probe gets `ProjectTexel`'s four taps and 8-bit weights, and the codes behind the decodes (`Srgb8Code`).
   - CPU: `projection_uv.cpp` calls `tu::Srgb8Probe`, which runs `Srgb8Filter` on the taps of non-zero weight.
   - GPU: `evaluator_project.hlsl` calls `Srgb8Probe`, which runs `TuSrgb8Channel` on the same taps. `P_TU_SRGB8` is now set for every sRGB8 image, not only for a minified one.
   - There is a single implementation of the sRGB8 arithmetic. A separate prototype of decision 209's rule (`Srgb8BilinearFilter`), also exact on every golden above, was removed in favour of the unit.
2. **No new refusal.** Every 8-bit sRGB magnification is now Painter's sRGB8 filter, so no output of this kind is silently inexact any more. Minification stays as decision 219 left it.
3. **P20-A's BaseColor exclusion is removed.** Of the five P20-A maps, only Normal stays excluded (item 2.9, the grey bitmap on Normal).

The model panel was not consulted. The rule is the hardware's (decisions 209 and 219), and the choice of implementation was the coordinator's: one unit, not two.

## Consequences

- Item 2.9's BaseColor case is done. Its remaining open cases are Normal and the 16-bit colour case.
- The GPU projection kernel changed for 8-bit sRGB magnification. Its DX12 evidence is `test_projection_kernel_equals_cpu` (`projection-gpu-vs-cpu`, random 8-bit sRGB magnifying stacks) and `test_lifted_colour_fits_gpu_equals_cpu`.
