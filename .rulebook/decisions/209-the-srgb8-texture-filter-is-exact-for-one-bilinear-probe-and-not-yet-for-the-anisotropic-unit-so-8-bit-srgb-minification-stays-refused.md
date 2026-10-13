# 209. The sRGB8 texture filter is exact for one bilinear probe and not yet for the anisotropic unit, so 8-bit sRGB minification stays refused

**Status**: accepted
**Date**: 2026-10-13
**Related Tasks**: phase1.15_compositor-colour-fits

## Context

Decision 203 kept bilinear minification of an 8-bit sRGB bitmap refused. Painter samples an `R8G8B8A8_SRGB` texture there, and its filter is not the float32 texture's. Item 2.7 asks for a replica of that filter, validated sample for sample against the recording GPU as decision 084 did for float32 textures, and then the fit of `srgb-bitmap-minification` s0-s3.

All measurements below ran on the owner's RTX 4090 through Vulkan, with `tools/parity/vk_sampler_probe` (flag 8, decision 203), on synthetic textures of random sRGB8 codes. No Painter data was read except the counts already published in decision 203.

**One bilinear probe (magnification, `SampleLevel` 0).** The rule below is exact on every sample measured: 12 288 two-tap samples of random code pairs at nine weights, and 49 152 random four-tap samples on a random 256 x 256 texture.

- Each texel enters as its sRGB8 decode d = `Srgb8Operand(c)`, cut to an integer below an alignment exponent E: floor(d 2^(8 - E)).
- E is the largest *segment exponent* of the taps of non-zero weight. A code's segment exponent is the binary exponent (frexp) of the decode of c | 7, the largest code of its group of eight.
  - 26 codes have a segment exponent above their own: 32, 33, 48, 49, 64-70, 96-98, 136, 184-187 and 248-254.
  - This is why code 47 enters as 0.0283203125 beside code 48: E is 48's, one above 47's, and 47's lowest bit is cut.
- The weighted sum (the replica's 8-bit weights) is rounded once to a binary16 value, to nearest with ties away from zero.
- One tap of full weight returns its decode unchanged.

**The anisotropic unit (`SampleGrad`, minification).** The replica's probe geometry (decision 084's tables) was used unchanged, with each probe filtered by the rule above. The probe sums were added and rounded once to binary16.

- Over decision 084's validation plan (sides 64 and 256, biases 0 and -1.5, repeat and clamp, random, near-isotropic and bin-edge footprints), 515 of 96 000 samples differ. On the clamp-to-edge random set alone, 102 of 8 000 differ.
- Every difference is one binary16 step, with the replica higher.
- Variants tried, each with at most 74 of those 8 000 still different:
  - one alignment exponent for the whole sample, per level, or per probe pair;
  - zero-weight taps counted in the exponent;
  - each probe's sum truncated below its exponent, below its own leading bit, or on the result's binary16 grid with guard bits;
  - each probe's sum truncated to `Coarse(E) - K`. K = 16 was best, with 74.

**The mip chain.** Decision 203 found that Painter's 8-bit mip levels hold sRGB8 codes. How Painter builds them (a hardware blit or a shader, and that filter's arithmetic) is not measured yet.

## Decision

1. **The single-probe rule above is recorded as measured.** It is exact on 61 440 of 61 440 hardware samples.
2. **Bilinear minification of an 8-bit sRGB bitmap stays refused** (decision 203's refusal and message are unchanged). The anisotropic unit's cross-probe arithmetic for sRGB8 textures is not identified: 515 of 96 000 samples differ. The mip-generation filter is not measured either. No replica code is committed: an inexact path would be a workaround, and the refusal is the correct behaviour until both are exact.
3. **Item 2.7 stays open**, with these next steps:
   - identify the cross-probe accumulation of sRGB8 probes, for example by sampling two- and four-probe footprints over designed uniform and impulse textures;
   - measure how Painter's sRGB8 mip levels are built;
   - then run the validation plan to 0 differing samples, fit s0-s3, mirror the rule in `evaluator_project.hlsl`, and run DX12.

   No Painter recording is needed.

The model panel was not consulted. Nothing here is a choice: the rule is what the hardware shows, and the refusal follows the exactness rule.

## Consequences

- The level-0 rule is the base for item 2.7's replica. Code 47's anomaly and the 26 bumped codes are explained.
- 8-bit sRGB bitmaps larger than their set stay refused for now.
