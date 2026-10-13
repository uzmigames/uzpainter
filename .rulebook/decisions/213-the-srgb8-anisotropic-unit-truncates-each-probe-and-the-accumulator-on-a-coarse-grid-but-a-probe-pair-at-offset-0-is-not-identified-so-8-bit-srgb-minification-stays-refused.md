# 213. The sRGB8 anisotropic unit truncates each probe and the accumulator on a coarse grid, but a probe pair at offset 0 is not identified, so 8-bit sRGB minification stays refused

**Status**: accepted
**Date**: 2026-10-13
**Related Tasks**: phase1.15_compositor-colour-fits

## Context

Decision 209 measured one bilinear probe of an `R8G8B8A8_SRGB` texture exactly. It left two things open for item 2.7: how the anisotropic unit (`SampleGrad`, minification) combines its probes, where 515 of 96 000 validation samples were one binary16 step high, and how Painter builds its sRGB8 mip levels.

This session continued on the owner's RTX 4090 through Vulkan (`tools/parity/vk_sampler_probe`, flag 8), on synthetic textures only. It had a two-hour cap. No Painter data was read.

The replica's probe geometry (decision 084's tables) was used unchanged. An instrumented build printed each sample's probes: level, offset, placement weight, multiplicity and taps. The hardware was then compared against models evaluated over those probes:

- decision 084's validation plan: sides 64 and 256, biases 0 and -1.5, repeat and clamp, random, near-isotropic and bin-edge footprints, 96 000 samples per seed, with seeds 0 and 1;
- every code 0-255 as a uniform texture over 8 192 random footprints;
- isotropic footprints of both gradient signs over uniform textures of codes 0-15;
- textures with one code on level 0 and another on level 1, over 16 384 low-LOD footprints of ratios 1 to 4.6. This separates each level's contribution.

## Findings

1. **Uniform textures.** For codes 8 to 255 (segment exponent -7 and above), every footprint returns the code's decode exactly. Codes 1, 2, 3 and 5 (exponent -8) come back 1 to 4 binary16 steps low on footprints of two or more probes. A probe's sum is therefore truncated on an absolute grid.
   - For exponent -8 the grid must be 2^-22 exactly: no finer grid and no coarser grid fits codes 1-3.
   - For exponents -7 and above, a grid of 2^(E-16) or finer fits every footprint.
2. **Best model found.** It differs on 52 of 96 000 samples (seed 0) and 53 of 96 000 (seed 1). On the clamp-to-edge random sets it differs on 11 of 16 000 and 14 of 16 000. The prototype differs on 515 of 96 000 for both seeds, so the model cuts the error by a factor of ten. The model:
   - Each probe's weighted sum is computed exactly. Its operands are floor(d 2^(8-E)) under the probe's own E (decision 209), and its weights are the replica's (1/1024).
   - That sum is truncated to 2^(max(Coarse(E), -6) - 16). Coarse is decision 084's: E lowered until E + 126 is a multiple of 4.
   - Before every probe after the first, the running sum is truncated to 2^(Coarse(g) - 16). Here g is the largest E of the probes whose group is at or below the current probe's group. This is the float32 unit's group rule (decision 084) with 16 bits in place of 36. Starting the accumulator truncation at the second probe gives 52; starting it at the third, as for float32, gives 60.
   - The sum is rounded once to binary16, to nearest with ties away from zero. A single live tap returns its decode.
3. **What is left: the probe pair at offset 0.** A geometry entry with p = 0 places two probes of weight w at the same position. The replica merges them into one probe. Most remaining differences sit on such entries.
   - On the level-separated textures, the two halves of such an entry act as one truncation unit in about 1 550 informative cases.
   - They act as two separately truncated probes in 101 cases. One example is level 0 with weight 157 on code 1: the hardware loses 16/2^26, which is two truncated halves.
   - Neither the gradient's sign nor the placement weight decides between the two. "Split only on a negative sign" gives 88 of 96 000 differing samples, and "always split" gives 154.
   - Five single-level cases of this kind (all with a negative sign) return a value just below an exact binary16 tie, which no tested grid on the merged probe reproduces.
4. **The mip chain is not measured.** The cap was reached before the comparison of Painter's `srgb-bitmap-minification` s0-s3 with candidate sRGB8 mip builds. Those candidates are the hardware-generated levels, and the box filter in linear re-encoded to codes with each rounding mode.

## Decision

1. **Findings 1 and 2 are recorded as measured.** The grid rule and the accumulator rule are the base for the next attempt. They are not exact, so no replica code is committed: an inexact path would be a workaround.
2. **Bilinear minification of an 8-bit sRGB bitmap stays refused.** Decision 203's refusal and its message are unchanged.
3. **Item 2.7 stays open**, with these next steps:
   - Identify when the two halves of a p = 0 entry are truncated separately. Use designed footprints that hold a single p = 0 entry on one level, over textures where only that level is non-zero, and sweep the sub-texel position (u, v), both signs and the anisotropy ratio, since position is the variable the replica does not pass into the probe structure.
   - Then run the validation plan to 0 differing samples.
   - Then measure the mip build against s0-s3.
   - Then mirror the rule in `evaluator_project.hlsl` and run DX12.
   No Painter recording is needed. The held-out `resample-uv-heldout-*` goldens must stay out of every fit.

The model panel was not consulted. Nothing here is a choice: the counts are what the hardware shows, and the refusal follows the exactness rule.

## Consequences

- 8-bit sRGB bitmaps larger than their set stay refused for now.
- The remaining gap is narrowed to one structural question, the p = 0 pair, plus the mip build. The error went from 515 to 52 of 96 000 samples, and every remaining difference is still one binary16 step.
