# 56. Painter minifies through the GPU's Vulkan anisotropic sampler; the UV offset precedes the scale; minification stays refused

**Status**: accepted
**Date**: 2026-10-11
**Related Tasks**: phase1.9_compositor-resample-gaps

## Context

Decision 043 left bilinear minification refused until a recording could determine it. Those recordings now exist, for both filters, with Repeat and RepeatNone (decision 048); r1 = r2 on every map:

- `resample-uv-minify` projects the 64 x 64 random `pattern64` at scales 5.13 to 16.6. One projection is anisotropic (13.2 x 5.13) and one is rotated 30 degrees with an offset.
- `resample-uv-impulse` projects `impulse64`.

`resample-uv` user 6 (field A at scale 3.3) is held out.

Painter 12.1.5 renders through Vulkan (its log and `substance_vk_sal.dll`). Everything below was measured on the recording GPU (RTX 4090, driver 617.14) with `tools/parity/vk_sampler_probe`. That tool is a standalone Vulkan compute probe, needed because the render layer is DX12-only until Phase 3. It stores the bitmap bottom-up as a float32 texture with a float32 box mip chain and samples it by `SampleGrad` at Painter's UV.

1. **The trilinear band depends on maxAnisotropy.** The blend factor of the anisotropic path is t = f at maxAnisotropy 1, 1.5 f at 2 and 3, 1.75 f at 4 to 7, and 2 f at 8 to 16 (f is the LOD fraction). The D3D12 path uses another band ([0.25, 0.75] at 16). It reproduces no minifying user with LOD > 0 at any bias.
2. **BilinearSharp is one anisotropic sample** (maxAnisotropy 4) at LOD bias -1.5. Both goldens give 32 Sharp maps (Repeat and RepeatNone), 32 x 65 536 x 3 values. All are exact except:
   - 8 and 20 values one code off in `-minify` users 4 and 5 with Repeat (exact with RepeatNone);
   - `-minify` user 7 (rotated): 99.27 % exact with Repeat, 99.57 % with RepeatNone.

   User 7's misses lie where the x coordinate is within 0.006 / 256 texel of a fixed-point rounding boundary, so they come from Painter's float32 UV, which is not modelled. For an isotropic gradient of 1.2825 texels the hardware takes two probes (weights summing to 510 or 511 / 512); for 1.0, 1.5, 2 and 3 texels it takes one. Painter's user 0 shows the same two probes.
3. **BilinearHQ is nine of those samples** at +-1/3 output texel, with the gradients divided by 3.
   - Weights: the tent [1 2 1]^2 / 16, with the (+1/3, +1/3) sample replaced by the centre.
   - Blend: the result is mixed with the centre sample by alpha = min(footprint - 1, 1).
   - Least-squares class weights (centre, edge, corner, x 256) match the rule: 206.28, 9.04, 4.52 at footprint 1.2825; 164.92, 16.56, 8.28 at 1.5175; 90.12, 30.16, 15.08 at 1.9425; 80, 32, 16 from 2.575.
   - With a float32 combination, 94 % to 99.9 % of the values are exact and the rest one code off. The exception is where a subsample crosses a rounding boundary: up to 28 codes off in user 1 and 86 in user 7.
   - The anisotropic user 6 of `-minify` is not explained: 41 % exact, max 1 879 codes. HQ's rule for an anisotropic footprint is unknown.
4. **Held out**, `resample-uv` user 6: Sharp is 99.98 % exact and HQ 99.84 %, max one code.
5. **The UV offset comes before the scale and the rotation:** (a, b) = ((u - 1/2 - o_u) s_u, (v - 1/2 - o_v) s_v), and u' = R (a, b) + 1/2. The evaluator applied the offset last.
   - On `-minify` user 7 the old order misses by 14 551 codes on average; the new order is 99.27 % exact.
   - `-impulse` users 6 and 7 (offsets at scales 13.2 and 7.77) are exact.
   - Every earlier golden has its offset at scale 1 without rotation, where both orders agree.

Model panel under the owner's delegation (cx/gpt-6-astra, kimi/kimi-k3, xai/grok-4.5, 2026-10-11):

| Claim | Verdicts |
|---|---|
| C1: the root cause is the GPU's own texture unit under Vulkan, not a Painter prefilter | AGREE x1, PARTLY x2. The mechanism is established. The configuration (bias, alpha, weights) is fitted, not read from the hardware. |
| C2: the refusal stays; the one-code residual is a divergence; items 2.2-2.4, 3.1, 3.2, 4.1 stay open | AGREE x3. Add that the constants were measured on driver 617.14 only. |
| C3: fix the offset order now, with a unit test | AGREE x1, PARTLY x2. Test a non-zero offset with a non-unit scale, and check both backends (`projection-gpu-vs-cpu` draws random offsets, scales and rotations). The order is verified on one rotation and two offsets. |
| C4: the next step is measurement through Vulkan, not a recording | PARTLY x3. Sweep footprints and LOD transitions, not scales alone. Fix a stop point in case the texture unit resists a bit-exact model. Validate Painter's float32 UV model on new rotated and offset projections. |
| C5: do not commit the probe | DISAGREE x1, PARTLY x1, AGREE x1. Keep it as executable evidence, outside the production code. |

## Decision

1. **Root cause.** Painter minifies through the recording GPU's texture unit under Vulkan, with the configuration above:
   - an anisotropic sampler, maxAnisotropy 4 to 7;
   - a float32 box mip chain;
   - Sharp at LOD bias -1.5;
   - HQ as the 3 x 3 supersample.

   The configuration is fitted on the goldens and was measured on driver 617.14 only.
2. **The refusal stays.** The evaluator keeps refusing bilinear minification with `evaluator:unsupported_source`.
   - To lift it, the CPU reference and the GPU kernel would have to reproduce, bit for bit: the hardware's anisotropic probe count, positions and weights from the gradient bits; its fixed-point LOD and trilinear arithmetic; and Painter's float32 UV. None of these is modelled.
   - Decision 043 rules out sampling through one GPU's sampler instead.
   - The one-code residual is a divergence, not a pass.
   - `uv-sampling.json` `uv-bilinear-minification` stays a gap and states the mechanism.
   - Items 2.2-2.4, 3.1, 3.2 and 4.1 of phase1.9 stay open.
3. **The offset order is fixed.** The offset now comes before the scale and the rotation, in `ProjectTexel` and in `evaluator_project.hlsl`, with a unit test (`sources`). Every magnifying golden stays exact.
4. **The probe is committed as evidence.** `tools/parity/vk_sampler_probe` (`vkprobe.cpp`, `measure.py`) is the executable evidence. It is not production code: it prints statistics only and runs on the owner's machine.
5. **Next step: measure the texture unit through Vulkan.** On the recording GPU, measure:
   - the anisotropic probe logic against the gradient bits;
   - the LOD fixed-point log2;
   - the per-level weight, trilinear and supersample arithmetic;
   - Painter's float32 UV.

   If no bit-exact model emerges, an exception-register proposal (decision 017) takes its place. A further Painter recording is needed for two things only:
   - HQ's anisotropic rule needs a sweep of anisotropic footprints;
   - LOD at or above 1 needs footprints from 4 to 16 texels at irregular steps.

   Both recordings should cover both filters and include rotations and offsets, which would also validate the UV model.

## Alternatives Considered

- **Evaluate minification through the GPU's hardware sampler.** Rejected by decision 043. In any case the D3D12 band differs from Vulkan's, so the DX12 render layer could not reproduce Painter.
- **Accept the one-code residual.** Rejected: decision 017 makes exact equality the acceptance rule.
- **Keep the old offset order and wait.** Rejected: the old order is wrong by thousands of codes wherever an offset meets a scale.

## Consequences

- Scaled bitmap fills that minify stay refused.
- Offsets combined with scales or rotations now follow Painter.
- The probe documents how to re-measure the texture unit after a driver or Painter update (the rolling oracle).
