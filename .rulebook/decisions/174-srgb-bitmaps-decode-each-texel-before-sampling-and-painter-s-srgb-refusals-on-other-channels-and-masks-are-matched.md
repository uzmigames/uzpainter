# 174. sRGB bitmaps decode each texel before sampling, and Painter's sRGB refusals on other channels and masks are matched

**Status**: accepted
**Date**: 2026-10-12
**Related Tasks**: phase1.15_compositor-colour-fits, phase1.25_pilot-wand

## Context

Decision 145 fitted an sRGB bitmap sampled 1:1 onto an sRGB8 channel for a 16-bit colour or grey and an 8-bit colour image. It kept five uses refused until `tier0/semantics/srgb-bitmap-variants-v2` was recorded:

- an 8-bit grey sRGB bitmap;
- a resampled sRGB bitmap;
- an sRGB bitmap on a channel that is not sRGB8, or as a mask source;
- the Working and Linear bitmap colour spaces.

The golden was recorded and admitted on 2026-10-12 (decision 167; 3x3 grid, decision 156). Painter refused `set_color_space(sRGB)` on the six user channel formats (RGB8, L8, RGB16, L16, RGB16F, RGB32F) and on the mask source, with `ValueError: Invalid colorspace 'standard sRGB'`. Those bitmaps stayed Data, and Painter listed only Raw, Data and DataSigned for them. Only s5's masked BaseColor differs between r1 and r2.

Measured on recorded data (private store, counts only; PNG 8 unless stated):

- **s0, 8-bit grey ramp at 1:1.** Each code c is stored as c on the three channels: 0 of 196 608 values differ, r1 and r2.
- **s6 Working and s7 Legacy Linear.** Both equal the Raw reading c / 65535. The sRGB reading misses 195 333 values.
- **s8 Legacy sRGB.** It equals the sRGB reading. The Raw reading misses 195 343 values.
- **s3, Nearest at scale 2.** Every texel lies on a tie. Painter takes the texel floor(x + 1/2) across and ceil(y + 1/2) - 1 down the rows (the upper row). This is the GPU's point sample of the bitmap stored bottom-up.
  - With that addressing, the decoded texel's code is exact for field A and for the 8-bit ramp.
  - The evaluator's earlier floor(y + 1/2) missed 65 828 and 65 536 values.
  - No earlier golden hit a row tie: `resample-uv` s2's offsets tie across only.
- **s2, BilinearHQ magnification (scale 0.5).** Painter decodes each texel to a float32 linear value and then filters it with the GPU's linear filter (`BilinearFilter`). Tested against s2:
  - **8-bit ramp.** The texel is the GPU's sRGB8 decode (`Srgb8Operand`, an sRGB8 texture), which gives 0 misses. A float32 shader decode misses 1 536 values, and filtering the codes before decoding also misses 1 536.
  - **16-bit field A.** The texel is the GPU's float32 shader decode x float32(1 / 12.92) up to 0.04045. Above that it is pow(fma(x, r, float32(0.055) r), 2.4), with r = float32(1 / 1.055) and the GPU's pow (`hw::Pow`). This is the compiler's contraction of (x + 0.055) r.
    - One texel of s2 filters to exactly an sRGB8 threshold, and one field-A code at 1:1 (s8) decodes to exactly another threshold. Together they separate the candidates.
    - The fitted form is exact on both.
    - The uncontracted product and the double-precision decode miss that s2 texel. A correctly rounded pow misses the s8 code. A division misses both.
    - Filtering the codes and then decoding misses 67 values. A half-float texture misses 489, and a 16-bit unorm one 40.
- **s1, BilinearHQ minification at 30 degrees.** It is refused for every bitmap: rotated minification footprints are not modelled (decisions 061, 084). The golden holds no axis-aligned minification of an sRGB bitmap.

End to end, through the plan and `WriteExport` (`uzp-export-tests export`, CPU), each set was rebuilt and written at PNG 16, PNG 8 and OpenEXR 32f (steps 78, 80 and 82), with every map of each step:

- s0, s2, s3, s4, s5, s6, s7 and s8 give 192 files.
- 381 of 381 comparisons are byte-identical: r1 everywhere, and r2 wherever r2 equals r1.
- The three r2 files left out are s5's BaseColor, where Painter is unstable (decision 032). r1 is that file's exact target, and it is met without the exception register.
- s1 is refused.

## Decision

1. **The decode.** An sRGB bitmap (`sRGB` or `LegacyColorSpace.sRGB`) is decoded once per resource to a float32 image of linear values with the bitmap's size and channel count (`SrgbDecoded`, `src/evaluator/evaluate.cpp`; rule in `sources.h`).
   - An 8-bit code becomes `Srgb8Operand(c)`.
   - A 16-bit code becomes the contracted float32 shader decode above.
   - The image is projected like any bitmap, through the CPU `ProjectTexel` and the GPU projection kernel: its float32 texels replace float32(c / M). The value is stored with the sRGB8 channel's write rule. A grey image feeds the three channels.
   - At 1:1 every decode stores the same code as before. The native `sources` case asserts this for all 65 536 16-bit codes and all 256 8-bit codes.
   - The 1:1 upload path of decision 145 is removed.
2. **The Nearest tie rule.** Nearest takes ceil(y + 1/2) - 1 down the rows, for every bitmap, on the CPU and in `evaluator_project.hlsl`. Point sampling does not depend on the texel format.
3. **The colour spaces.** Working and `LegacyColorSpace.Linear` read codes as Raw does (`BitmapColourSpaceOf`).
4. **Painter's refusal, matched.** The facade's `SourceBitmap.list_available_color_spaces` returns Raw, Data and DataSigned on a user channel that is not sRGB8, as it already did for a mask source.
   - `set_color_space(sRGB)` there raises `ValueError("Invalid colorspace 'standard sRGB'")` before any change. The bitmap keeps Data.
   - The evaluator still refuses an sRGB tag on such a channel or mask, which only the native API can produce. It fails with `unsupported_source` naming this decision as the reason, not a task.
5. **Legacy members in the facade.** The facade stores a `LegacyColorSpace` member under its qualified tag (`LegacyColorSpace.Linear`, `LegacyColorSpace.sRGB`, decision 156 §5). `get_color_space` returns the Legacy member that was set.
6. **Still refused** (`compositor:srgb-unrecorded`, phase1.15_compositor-colour-fits item 2.5, split from 2.2): bilinear minification of an sRGB bitmap. Its mip chain and the texture unit's handling of decoded texels are unmeasured.
   - Recording that settles it: a Tier 0 set of the 8-bit ramp and field A in sRGB on BaseColor at BilinearHQ and BilinearSharp scales 2 and 4, rotation 0, Repeat.
   - Wrap modes, rotations and offsets under magnification and Nearest follow the projection rules every bitmap uses. The decode is per texel and comes before addressing.

The model panel was not consulted. Each rule is what the recording shows, and the only candidate exact on every set.

## Alternatives Considered

- **Decode after filtering (sample the codes, then decode).** Rejected: 67 values of s2 field A and 1 536 values of the 8-bit ramp miss.
- **Keep the Nearest change for sRGB bitmaps only.** Rejected. The sampler addresses texels the same way whatever they hold, and two rules would make the evaluator disagree with itself on linear bitmaps at a row tie.
- **Judge s5's r2 through the exception register.** Not needed. r1 is the exact target (decision 032) and is met, and r2 is reported as unstable.

## Consequences

### Positive
- Every sRGB bitmap use Painter allows under Legacy is exact except bilinear minification: 8- and 16-bit, colour and grey, at 1:1, magnified, and under Nearest at any scale, in sRGB, Legacy sRGB, Working and Legacy Linear.
- The facade refuses exactly where Painter refuses.

### Negative
- The GPU projection kernel changed. Its DX12 run of the affected cases (`projection-gpu-vs-cpu`, the projection goldens on dx12) is the evidence for the GPU path.
- s1 (rotated minification) stays refused, owned by the texture-unit gap of decisions 061 and 084.
