# 218. A colour bitmap on a mono channel or as a mask source is the R16F texture of its mean, and P20-A's L8, L16F and mask maps are exact

**Status**: accepted
**Date**: 2026-10-13
**Related Tasks**: phase1.15_compositor-colour-fits

## Context

Item 2.9 of `phase1.15_compositor-colour-fits` (split by decision 214) fits P20-A's five exported maps (`tier0/api-probes/phase1-fill-channel-defaults`, PNG 16; r1 and r2 are byte-identical to each other).

The stack, bottom up, on a 256 x 256 plane:

1. a fill binding the 16 x 16 8-bit colour checker (cells (204, 51, 26) and (26, 128, 204)) on BaseColor (sRGB8), BaseMetalness (L8), Height (L16F), Normal (RGB16F) and SpecularRoughness (L8);
2. a fill binding the 8-bit grey `mask_left_half` on every channel, under a black mask whose fill effect binds the checker (a colour mask source);
3. a fill with the default sources, under a black mask whose fill effect binds `mask_left_half`.

Every source is magnified 16 times by the default bilinear filter, with Repeat.

Decision 214 found that the evaluator did not refuse a colour bitmap on a one-channel tile. It read the red component (41 and 23 of 255 on BaseMetalness, where Painter writes 59 and 63). That path also served 16-bit colour bitmaps, L16 and L32F channels, Nearest and minification, none of them recorded. It was silent wrong output.

Measured (counts only; every comparison against both recordings):

1. **The interior values.** The Height channel (L16F, exported as v / 2 + 1/2 at 16 bits) separates the value from the mask. The left half adds the grey 1 and the right half the grey -1 through the checker's mask. The four interior codes need:
   - a value of 2 m - 1, with m the mean (r + g + b) / 3 of the texel's float32(c / 255) components;
   - a mask of m rounded toward zero to a binary16.

   The red component, the Rec. 601 and BT.709 weights, the 8-bit rounding of the mean and the mean stored at 16 bits each miss at least one interior code.
2. **The transitions.** With the mean stored as a binary16 before the filter (value and mask), BaseMetalness and SpecularRoughness still differed on 16 and 24 texels. All of them are where both filter weights are fractional.
   - Rounding the filter's result to a binary16, to nearest with ties away from zero (the rounding decision 209 measured for the sRGB8 filter), makes them exact.
   - Ties to even also makes them exact, but leaves 104 Height texels one step off (below). Toward zero leaves 16 and 24.
3. **Height.** Taking 2 m - 1 before the binary16 store of the texel, then filtering, makes Height exact: 65 536 of 65 536 texels, both recordings. Storing m and mapping it after the filter misses the interior.
4. **BaseColor** (not a mono read) differs on 8 264 of 65 536 texels by one sRGB8 code, in the transitions of the 8-bit sRGB checker on sRGB8.
   - A CPU prototype of decision 209's single-probe sRGB8 filter rule made BaseColor exact on both recordings. In that rule each tap is cut below the largest segment exponent of the live taps, and the sum is rounded once to binary16, ties away.
   - The evaluator's float32 filter of decoded texels is exact on `srgb-bitmap-variants-v2` s2 (magnification by 2). It is not exact at 16 times.
5. **Normal.** The grey bitmap on Normal (RGB16F) stays refused by the evaluator (`evaluator:unsupported_source`: a Normal-channel bitmap must be RGB). It was not fitted within the time box.
6. **Other goldens.** A scan of every public manifest for a colour PNG bound on a one-channel channel finds three more, each 16-bit field A on Height: `export-bit-depth` s3 (1:1, opacity 0.5), `export-padding-sphere` and `export-padding-bevelled-cube`.
   - No test evaluates those Height maps today.
   - On `export-bit-depth` s3, Painter's Height follows the component mean, not red. It agrees with the mean to within 3e-4, after the constant offset of the lower layer. So the 16-bit case is recorded there, but it is not fitted exactly here.

The data does not distinguish the order of the three additions or how the division by 3 is done. Every variant of that float32 arithmetic gives the same binary16.

No model panel was consulted. The rule is read from the recordings, and the scope follows the exactness rule.

## Decision

1. **The rule.** A colour bitmap read by a one-channel tile (an L8 or L16F channel, or a mask source) is sampled as an R16F texture.
   - Each texel is m = ((r + g) + b) / 3 of its float32(c / 255) components, or 2 m - 1 (two float32 operations) on the Height channel. It is rounded toward zero to a binary16 (`evaluate.cpp` `GreyTexture`).
   - The bilinear filter (decision 084's integer filter) rounds its result to a binary16, to nearest with ties away from zero (`arith::HalfNearestAway`; `projection_uv.cpp`, and `evaluator_project.hlsl` with the image encoding `IMAGE_FLOAT16`). A full-weight tap returns its texel unchanged.
2. **Admitted** (silently wrong before, exact now): an 8-bit colour bitmap, magnified or at 1:1 by a bilinear filter, on an L8 or L16F channel or as a mask source, under legacy colour management.
3. **Refused before any mutation** with `evaluator:unsupported_source`, naming item 2.9 and this decision (`CheckGreyTexture`):
   - a colour bitmap on any other one-channel format (L16, L32F);
   - a 16-bit colour bitmap;
   - the Nearest filter;
   - minification.

   Under OCIO the existing refusals apply first (decision 190).
4. **P20-A maps.**
   - BaseMetalness, Height and SpecularRoughness are byte for byte, both recordings. Their exclusions are removed from `test_facade_fill_channel_defaults_equal_painter`. The Tier 0 trace and the evidence of the export symbols now include P20-A (decision 112).
   - BaseColor stays excluded and moves to item 2.7. The evaluator's 8-bit sRGB magnification must take decision 209's single-probe rule. That change belongs to 2.7's sRGB8 filter replica (CPU and GPU), and it must keep `srgb-bitmap-variants-v2` s2 exact.
   - Normal stays excluded and refused. The grey bitmap on Normal is still an open fit of item 2.9.
5. **Native tests.**
   - Some fixtures bound colour bitmaps on one-channel formats with no golden behind them. They now bind grey bitmaps there:
     - the 1:1 copies of `sources`;
     - the random stacks of `gpu-vs-cpu`, `projection-gpu-vs-cpu` and `masks-gpu-vs-cpu`;
     - the contribution rig of the diagnostics.
   - New checks cover the grey texture's codes on L8 and L16F, its refusals, and GPU = CPU equality, upright and rotated.

## Alternatives Considered

- **Refusing every colour bitmap on a one-channel tile.** Rejected: P20-A records the rule, and it is exact on all three mono maps.
- **The mean without the binary16 texture, or with an 8-bit grey texture.** Rejected: each misses interior or transition codes (above).
- **Implementing decision 209's sRGB8 filter for magnification here.** Deferred to item 2.7. It changes decision 174's decided 8-bit sRGB path on both stores, and it must be validated on every sRGB golden, which is beyond this item's time box.

## Consequences

- No colour bitmap is read through its red component any more. P20-A's case is exact, and every other case is refused.
- Item 2.9 stays open for two cases:
  - the grey bitmap on Normal;
  - the 16-bit colour case, which `export-bit-depth` s3 Height records at 1:1.
- Item 2.7 owns P20-A's BaseColor map. A prototype shows decision 209's rule is exact there.
