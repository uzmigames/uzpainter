# 43. Bilinear filtering is the recording GPU's measured linear filter; bilinear minification waits for a kernel-identifying recording

**Status**: accepted
**Date**: 2026-10-11
**Related Tasks**: phase1.9_compositor-resample-gaps

## Context

`phase1.8_compositor-sources-projection` left two `resample-uv` differences (decision 017: none is a pass until exact or owner-approved). (a) With float32 texels `float32(c / 65535)`, the 8-bit integer weights w11 = (fx fy + 127) >> 8 and one rounding of the exact sum, one value of 1 376 256 per set is one code high in s0 and s1 (User2, texel (175, 18), green): its sum lies 2^-9.7 ulp above a float32 midpoint and Painter rounded it down. (b) Bilinear minification (User6, the 256 × 256 field A at scale 3.3) is refused with `evaluator:unsupported_source`.

(a) Over the 3 867 033 magnifying and 1:1 values of s0, s1 and s3 (both recordings identical), truncating each texel to 28 absolute fractional bits fits every value (27 bits break 16, 29 to 33 keep the miss; truncating the sum or the products, round-toward-zero and float32 orders never fit), but it broke `blend-basic` user7 (514 values of a 1:1 bitmap on RGB32F, where Painter keeps the float32 texel). Measured on the recording GPU (RTX 4090, D3D12, `uzp-evaluator-tests bilinear-hardware`): a float32 texture sampled by a linear sampler at every 8-bit weight pair (16 777 216 samples, edge operands beside 1.0 and 0 included) equals, on every sample, this rule: w11 = (fx fy + 128) >> 8; E the exponent of the largest texel of non-zero weight (in [2^(E-1), 2^E)); operands floor(t 2^(28 - E)); the weighted sum times 2^(E - 36) rounded to the nearest float32, ties up. An absolute 28 bits misses 11 035 samples, 27 or 29 bits 108 770 and 41 274, ties to even 25 242, the float32 texels summed exactly 80 551. A bitmap stored bottom-up turns the GPU's ties-up w11 into the ties-down w11 of the goldens' top-down frame. With those weights the rule reproduces all 3 867 033 values and keeps a texel weighed 256 unchanged (`blend-basic` exact again). The same GPU's RGBA16_UNORM filter matches on 0.4 % of samples: Painter samples float32 textures.

(b) Field A is a linear ramp in all three channels, so the interior measures only the kernel's centroid (BilinearHQ a constant -17.65 codes, BilinearSharp 0) plus ±1-code noise, and the wrap seams are crossed at four sub-texel offsets per axis. Single-level and trilinear models on box mip chains (numerical, every 8-bit blend weight) and the GPU's own trilinear and 16× anisotropic sampling of a float32 box mip chain (bottom-up, gradients of 3.3 texels, LOD bias -1.5 to 0, explicit LOD 0 to 2 in 1/32 steps) reproduce neither filter (Sharp at best 39-51 % of the interior exact, max error ≥ 1 285 codes; HQ never).

Model panel under the owner's delegation (cx/gpt-6-astra, kimi/kimi-k3, xai/grok-4.5, 2026-10-11), three rounds. Fitted 28-bit rule: AGREE ×1, PARTLY ×2 (one deciding datum). Measured hardware rule replacing it, integer CPU and GPU implementations, status exact: AGREE ×2, PARTLY ×1 (state the validated domain: texels in [0, 1], zero operands defined). Keeping the hardware measurement as a test gated on the recording GPU: AGREE ×3. The existing golden does not determine minification: AGREE ×3; the recording request: AGREE ×2 then, refined with impulse probes, irregular scales and a held-out check, AGREE ×3; keep the refusal and the task open: AGREE ×3.

## Decision

1. `BilinearHQ` and `BilinearSharp` magnification and 1:1 evaluate `BilinearFilter` (`src/evaluator/projection_uv.h`): the recording GPU's linear filter of float32 texels in [0, 1], with the goldens' ties-down weights, in integer arithmetic on the CPU and in the projection kernel (bit for bit). `uv-sampling.json` `uv-bilinear-repeat` and `uv-bilinear-repeatnone` are exact; every golden through the projection stays exact. `uzp-evaluator-tests bilinear-hardware` keeps the measurement as a test, skipped unless the recording GPU is present. `Nearest` keeps the float32 texel.
2. Bilinear minification is not fitted on `resample-uv`: the evaluator keeps refusing it with `evaluator:unsupported_source`, and `phase1.9_compositor-resample-gaps` stays open with its minification items unchecked until the recording of `parity/reports/phase1/compositor-resample-gaps.md` §3 (random-texel, impulse and held-out probes at irregular minifying scales, both filters, Repeat and RepeatNone) is made and fitted. The manifest is authored when that recording is scheduled: every manifest of the corpus is recorded, and the oracle-envelope bookkeeping expects so.

## Alternatives Considered

- Keep the float32-texel rule and propose an exception-register entry for the near-tie (rejected: an exact rule exists).
- The fitted absolute 28-bit truncation (rejected: breaks 1:1 copies on float channels and 11 035 GPU samples).
- Sample through the hardware sampler instead of manual filtering (rejected: ties the evaluator to one GPU's filter; the integer rule is portable and checked against that GPU).
- Evaluate minification with plain bilinear or the GPU's trilinear until the recording (rejected: wrong pixels without a refusal).

## Consequences

The bilinear rule now rests on a hardware measurement and the corpus together; another GPU or driver that filters differently is irrelevant to the evaluator (manual filtering) but would show in `bilinear-hardware` on the recording machine. Scaled bitmap fills that minify stay refused until the requested recording exists.
