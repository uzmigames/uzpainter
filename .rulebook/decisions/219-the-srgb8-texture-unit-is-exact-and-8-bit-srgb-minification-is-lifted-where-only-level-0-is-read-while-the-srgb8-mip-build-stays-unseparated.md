# 219. The sRGB8 texture unit is exact, and 8-bit sRGB minification is lifted where only level 0 is read, while the sRGB8 mip build stays unseparated

**Status**: accepted
**Date**: 2026-10-13
**Related Tasks**: phase1.15_compositor-colour-fits

## Context

Decision 213 left item 2.7 with two open questions:

- when the two halves of a probe pair at p = 0 are truncated apart (52 of 96 000 validation samples still differed);
- how Painter builds the mip levels of an 8-bit sRGB bitmap.

This session continued on the owner's RTX 4090 through Vulkan (`tools/parity/vk_sampler_probe`, flag 8), on synthetic textures only. It had a two-hour cap. The held-out `resample-uv-heldout-*` goldens were not read. The only Painter data read was `srgb-bitmap-minification` s0-s3, the golden item 2.7 names.

## Findings

1. **The p = 0 pair.** It is decided by the cell, not by the sub-texel position.
   - Every pair at p = 0 that decision 213's level-separated set decides falls into one of two kinds:
     - 105 need the pair summed apart: 101 on level 0 at rho 1-2 with a negative sign, and 4 on level 1 at a negative sign;
     - 1 282 need it as one probe.
   - The opposite sign's cell explains this. At rho 1 the geometry table holds the level-0 pair at p = 2 for a positive sign and at p = 0 for a negative one. The pair's true offset is non-zero, and the negative sign's quantisation brings it to 0.
   - Rule: a pair at p = 0 is two probes, one per weight in the table's order, when the cell of the opposite sign (same rho, f and level role) holds that pair at p != 0. Otherwise it is one probe.
2. **Two further grid rules.** The single probe-pair rule left 38 and 34 of 96 000 samples differing on the two seeds. Most of these were clamp-to-edge footprints. Two changes to decision 213's model remove them all:
   - Each probe's sum is truncated on the grid of its level's largest E, max(Coarse(L) - 16, -22), and not of its own E.
   - After the last probe, the running sum is truncated once more to 2^(Coarse(G) - 16), with G the largest E of the probes of non-zero value.

   The full rule is written in `texture_unit.h`, steps 5' and 6'.
3. **Validation** (sample for sample against the hardware; every sample is three channels):

   | Set | Samples | Differing |
   |---|---|---|
   | Decision 084's plan, seeds 0 and 1 (used while fitting) | 192 000 | 0 |
   | Same plan, seeds 2-5 (never fitted) | 384 000 | 0 |
   | `tables.py validate-srgb8`, fresh seeds | 480 000 | 0 |
   | Level-separated uniform textures, 7 code pairs, both biases and wraps (seeds 7 and 8) | 917 504 | 0 |

   - In the level-separated sets the p = 0 rule changes the prediction of 6 430 samples.
   - The C++ unit (`uzp-evaluator-tests texture-unit`, side bit 31) gives the same counts as the Python model.
   - Magnification (`SampleLevel` 0) takes the same arithmetic. On 589 812 multi-tap channel samples over codes 0-23, the truncation never changes a result, so decision 209's rule and this one agree there.
4. **The sRGB8 mip build.**
   - Painter's arithmetic was composed from hardware samples on candidate chains of sRGB8 codes. Three candidates each reproduce s0-s3, all 196 608 PNG 8 values of every set (EXR 32f holds the decode of the same codes):
     - the exact mean of the four decodes stored to the nearest sRGB8 code;
     - the float32 mean stored the same way;
     - one hardware bilinear probe at the block centre stored the same way.
   - Truncating the mean instead of rounding it misses 153 600 values of s1 and 181 248 of s3.
   - The ramp cannot separate the three candidates: it builds identical chains under all three. On random content the hardware-probe candidate differs from the exact mean on 6 382 of 49 152 level-1 values.
   - No other recording minifies an 8-bit sRGB bitmap past level 0, except the held-out goldens.
   - So the mip levels are known to be round-to-nearest sRGB8 codes, but their filter is not separated.

## Decision

1. **The sRGB8 texture unit is implemented** in `src/evaluator/texture_unit.cpp` (`Chain::codes`, `BuildSrgb8Chain`, `Srgb8Filter`) and mirrored in `evaluator_project.hlsl` (`P_TU_SRGB8`, `TuSrgb8Channel`).
   - `tables.py validate-srgb8` is its hardware gate, run after a driver change as decision 084's `validate` is.
   - It is pinned like decision 084's unit: RTX 4090, driver 617.14, Vulkan, maxAnisotropy 4.
2. **The refusal is lifted where only level 0 is read.**
   - `ReadsMipLevels` resolves the projection's axis-aligned footprint: BilinearSharp at bias -1.5, and BilinearHQ's samples at a third of the gradients and bias 0.
   - An 8-bit sRGB bitmap is now evaluated when that footprint stays on level 0. Roughly, that is BilinearSharp up to 2.8 texels per set texel and BilinearHQ up to 3, in decision 084's domain.
   - Such a bitmap's chain holds only level 0's codes.
   - `srgb-bitmap-minification` s0 and s2 (the 8-bit ramp at scale 2) are now byte-identical, r1 and r2, at PNG 16, PNG 8 and OpenEXR 32f.
3. **A footprint that reads a mip level stays refused** with `evaluator:unsupported_source`, now naming this decision. This covers s1 and s3 (the ramp at scale 4).
   - `compositor:srgb-unrecorded` stays a release gap for that remainder.
   - What settles it is one owner recording: a random-content 8-bit sRGB bitmap, minified by BilinearSharp and BilinearHQ at scale 4 on a square set.
4. **Item 2.7 is closed as a scope split** (decision 069's pattern). The unit is exact, and the level-0 domain is lifted and fitted. The mip-level remainder waits only on that recording.

The model panel was not consulted. Each step follows the exactness rule: lift what is exact, and refuse what one recording cannot separate.

## Consequences

- 8-bit sRGB colour bitmaps up to about three times their set's size evaluate exactly on CPU and GPU. One example is a 512 px albedo on a 256 px set. A grey one takes the same path by analogy; no golden records it.
- Larger 8-bit sRGB minification stays refused until the recording above exists.
- The texture unit now has two arithmetic paths: float32 (decision 084) and sRGB8 (this decision). Both share the LOD and geometry tables.
