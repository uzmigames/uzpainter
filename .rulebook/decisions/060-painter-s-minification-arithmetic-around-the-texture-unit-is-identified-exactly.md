# 60. Painter's minification arithmetic around the texture unit is identified exactly

**Status**: accepted
**Date**: 2026-10-11
**Related Tasks**: phase1.9_compositor-resample-gaps

## Context

Decision 056 identified the mechanism of Painter's bilinear minification: the recording GPU's anisotropic texture unit through Vulkan. With the GPU's own sampler in the loop, its model reproduced `resample-uv-minify`, `resample-uv-impulse` and the held-out `resample-uv` user 6 only to one code. It left three things on Painter's side open:

- Painter's float32 UV;
- HQ's rule for an anisotropic footprint (user 6: 41 % exact, up to 1 879 codes);
- HQ's float32 combination.

All of them were fitted this session with the GPU's sampler as the texture unit (`tools/parity/vk_sampler_probe/measure.py`; RTX 4090, driver 617.14).

1. **UV.** On `-minify` user 7 (rotation 30, offset), 1 430 Sharp values missed with the double-precision UV. Painter's UV is affine in float32: the matrix M of T(1/2) R S T(-1/2 - o), composed in double and rounded to float32, is applied as u' = fma(m00, u, m01 v) + m02 and v' = fma(m10, u, m11 v) + m12, to u = float32((i + 1/2) / W) and v = float32(1 - (j + 1/2) / H).
   - That rule leaves no miss.
   - The other orders tried miss 366 to 3 533 values: without fma, other fma placements, the offset folded, and cosine and sine in float32 with double composition.
   - Composing the elements in float32 in the same order gives the same pixels: the goldens do not separate the two.
2. **Mips.** Users 4 and 5 (LOD above 0) missed 8 and 20 values by one code, each one float32 ulp from a write boundary. Each mip level is the exact mean of the four texels above it, rounded to the nearest float32 with ties up. With that rule there is no miss. Round-to-nearest-even, float32 sums and other orders miss 8 to 252 values.
3. **HQ.** Per pixel, ddx and ddy are the fine derivatives of (u', v') in the 2 x 2 quad.
   - Nine samples are taken at (u' + DX ddx) + DY ddy, in float32 without fma, with DX and DY in {-1/3, 0, 1/3} as float32, and with the gradients divided by 3.
   - acc is their sequential float32 sum in this order: centre, (+, 0), (-, 0), (0, -), (0, +), (+, -), (-, -), (-, +), and the centre again in place of (+, +). The weights are 4, 2, 2, 2, 2, 1, 1, 1, 1 / 16. Of all 9! sequential orders, only this one (and its swap of the first two terms) fits the 10 260 values of users 3 to 5 (alpha = 1) that lie within 3 ulp of a write boundary.
   - C1 is a plain level-0 bilinear sample at (u', v'); this is what explains user 6.
   - alpha = clamp(min(|ddx|, |ddy|) w - 1, 0, 1), in float32 from the per-pixel derivatives (w is the bitmap width); the constant alpha of the scale leaves 19 383 misses (with a row-major sum).
   - The value is fma(C1, 1 - alpha, acc alpha). The other lerp forms miss 341 to 583 values.
4. **Sharp** stays one SampleGrad at LOD bias -1.5, maxAnisotropy 4.

**Result.** 64 maps x 2 recordings + the held-out maps: 13 566 120 values, 0 differing (`measure.py`).

Model panel under the owner's delegation (cx/gpt-6-astra, kimi/kimi-k3, xai/grok-4.5, 2026-10-11), on recording this as identified:

- AGREE x2, PARTLY x1;
- the PARTLY: state the scope. The result is exact on these captures with the hardware sampler as the texture unit. The order is unique within the orders searched. The way the matrix elements are computed is not separated.

On changing the evaluator's UV to the float32 rule now: AGREE x3 not to. Every magnifying golden has the same fixed-point coordinates under the double and the float32 rule (0 differences), and minification stays refused.

## Decision

1. Painter's side of bilinear minification is identified, exactly on the captures: the float32 UV, the mip rule, Sharp and HQ, with this dependency and these limits:
   - **Dependency:** the exactness holds with the recording GPU's sampler as the texture unit.
   - **Limits:** the matrix elements may be composed in double or in float32 (not separated), and the HQ order is unique among the 9! orders searched.
2. The evaluator's UV transform is not changed now. The float32 rule lands together with a minification model, with adversarial magnifying cases near coordinate rounding boundaries that separate it from the double rule.
3. `measure.py` is the executable evidence: print-only, comparing against the private goldens on the owner's machine. `vkprobe.cpp` gains a parameter buffer for designed per-sample inputs.

## Alternatives Considered

- **Keep the one-code model of decision 056.** Rejected: an exact rule exists for every map.
- **Land the float32 UV in the evaluator now.** Rejected for now: no golden separates it, and the element computation is not determined.

## Consequences

- Decision 056's open items on Painter's side are closed: the float32 UV, HQ's anisotropic rule and HQ's combination.
- No further Painter recording is needed for Painter's side on these captures.
- What remains is a software model of the texture unit itself (decision 061).
