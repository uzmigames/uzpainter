# 203. 16-bit sRGB bitmaps minify through the texture unit on their decoded mip chain, and 8-bit ones stay refused on the sRGB8 texture filter

**Status**: accepted
**Date**: 2026-10-13
**Related Tasks**: phase1.15_compositor-colour-fits

## Context

Decision 174 decoded each sRGB texel to float32 before the projection samples it, and kept bilinear minification of an sRGB bitmap refused (`compositor:srgb-unrecorded`, item 2.5). Decision 198 admitted the golden that item asked for, `tier0/semantics/srgb-bitmap-minification` (stable, r1 and r2):

- s0-s3: the 8-bit `srgb8-ramp` in sRGB on BaseColor;
- s4-s7: field A (16-bit) in sRGB on BaseColor;
- each source at BilinearHQ scale 2 and 4, then BilinearSharp scale 2 and 4, rotation 0, Repeat, 256 px bitmaps on 256 px sets;
- BaseColor written at PNG 16, PNG 8 and OpenEXR 32f (steps 36, 38, 40).

The axis-aligned minification path of decision 084 (texture-unit replica, float32 mip chain, Painter's float32 UV) applies to this domain. The held-out goldens `resample-uv-heldout-*` were not used.

Measured on recorded data (private store, counts only), through the plan and `WriteExport` (`uzp-export-tests export`, CPU):

- **Field A (s4-s7).** The decoded float32 image of decision 174 is level 0 of the mip chain (`BitmapChain`). The mips are built and sampled as for any bitmap. Every file is byte-identical to r1 and r2: 12 files, 24 of 24 comparisons. The texture Painter samples is a float32 texture there, as decision 174 found for magnification.
- **The 8-bit ramp (s0-s3), on the same chain.** s2 (BilinearSharp at scale 2, which samples level 0 only) is exact. The others are not. Per file, of 196 608 values at PNG 8 and OpenEXR 32f:
  - s0 misses 1 024;
  - s1 misses 73 728;
  - s3 misses 36 864.
- **Mip levels holding sRGB8 codes.** Storing every mip texel as `Srgb8Operand(Srgb8Store(filtered))` gives:
  - s1: 1 024 misses;
  - s3: 3 072 misses;
  - s0: 1 024 misses, unchanged, because s0 samples level 0 only.
  So Painter's 8-bit texture is an sRGB8 texture with sRGB8 mip levels. Level 0 still misses.

Measured on the recording GPU (RTX 4090, Vulkan) with `tools/parity/vk_sampler_probe`, using its new `flags & 8` mode, an `R8G8B8A8_SRGB` texture:

- **Painter's HQ arithmetic on hardware samples.** It was run on hardware samples of the ramp at s0's nine BilinearHQ points per texel. Every one of the 256 columns of s0's red channel equals Painter, including the one the replica misses.
  - The replica's samples, the float32 texture's filter, differ from the hardware's on 1 266 of 2 304 points.
- **The sRGB8 texture's filter is not the float32 texture's:**
  - Its results are binary16 values, rounded to nearest with ties away from zero.
  - Between non-adjacent codes it falls below the linear blend of the decoded texels. For example, the codes (5, 184) at weight 1/256 on 184 give 0.0018768, against 0.0033967 for the blend.
  - A model with the decoded texels (`Srgb8Operand`) cut to 8 bits below the largest texel's exponent, summed with the 8-bit weights and rounded to binary16, misses 611 of 12 288 random two-tap samples. The linear blend rounded to binary16 misses 6 357.
  - Within the pair of codes (47, 48) code 47 enters as 0.0283203125. Its `Srgb8Operand` is 0.0284423828, and a full-weight tap still returns it.
  - The rule is therefore not yet known exactly.

## Decision

1. **16-bit sRGB bitmaps minify through the texture unit** on their decoded float32 mip chain (`BitmapChain` takes a float32 image's stored values as level 0). The domain is decision 084's: rotations that are multiples of 90 degrees, square power-of-two bitmaps on square sets, Repeat or RepeatNone.
   - The GPU projection kernel is unchanged: it samples the chain the CPU builds.
   - The refusal in `evaluate.cpp` is lifted for these bitmaps.
2. **Bilinear minification of an 8-bit sRGB bitmap stays refused**, with `evaluator:unsupported_source` naming this decision. This covers colour and grey.
   - What it needs is a replica of the recording GPU's sRGB8 texture filter: its operand precision, its binary16 result and the code-47 entry. It also needs mip levels of sRGB8 codes and validation sample for sample against the hardware, as decision 084 did for float32 textures.
   - This needs no Painter recording: `srgb-bitmap-minification` s0-s3 is the golden.
   - The measurement runs on the owner's machine through `vk_sampler_probe` (flag 8).
   - Owner: phase1.15_compositor-colour-fits item 2.7, split from 2.5.
3. **The capability manifest.**
   - `SourceBitmap.set_color_space` `compositor` cites `srgb-bitmap-minification` for 16-bit minification.
   - `compositor:srgb-unrecorded` stays a release gap for the 8-bit case.
4. **Magnification of 8-bit sRGB bitmaps** (decision 174) is not reopened. Its goldens stay exact under the float32 filter model: `srgb-bitmap-variants-v2` s2, at quarter-texel weights, and every 1:1 golden. Item 2.7's replica must keep them exact. Until then, an 8-bit magnification at other weights is exact only as far as those goldens show.

The model panel was not consulted. Lifting the exact 16-bit case and refusing the inexact 8-bit case is the acceptance rule, not a choice between options.

## Alternatives Considered

- **Lift 8-bit sRGB minification with sRGB8 mip levels.** Rejected: up to 3 072 values per file differ.
- **Lift only s2's case (8-bit BilinearSharp at scale 2), which is exact.** Rejected: the hardware shows that the filter model is wrong for sRGB8 textures. s2 is exact because the sRGB8 store hides the differences, not because the model is right.

## Consequences

### Positive
- Minified 16-bit sRGB bitmaps (Painter's default for a colour bitmap on BaseColor) evaluate exactly on CPU and GPU in the axis-aligned domain.
- The probe can now sample sRGB8 textures, which item 2.7 needs.

### Negative
- An 8-bit sRGB bitmap larger than its set (the common case for 8-bit PNG albedo textures) is still refused until item 2.7 lands.
