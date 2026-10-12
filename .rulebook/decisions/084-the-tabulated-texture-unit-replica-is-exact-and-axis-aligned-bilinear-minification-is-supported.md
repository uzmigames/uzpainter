# 84. The tabulated texture-unit replica is exact and axis-aligned bilinear minification is supported

**Status**: accepted
**Date**: 2026-10-12
**Related Tasks**: phase1.9_compositor-resample-gaps

## Context

Decision 083 identified how the recording GPU's texture unit sums its probes (gate 3). Decision 061's gate 4 remained:
1. acquire the tables;
2. build the replica;
3. validate it sample for sample against the hardware before any golden;
4. lift the refusal only for the validated domain.

All measurements below ran on the RTX 4090 with driver 617.14 through Vulkan, on synthetic textures, with `tools/parity/vk_sampler_probe`.

**The tables.** `tables.py measure` writes `src/evaluator/tables/tu-lod.zlib` and `tu-geometry.zlib`. It takes about 25 minutes and reproduces both files byte for byte.
- The LOD table holds lambda (1/256) over the 9-bit major mantissa, the 9-bit minor mantissa and an exponent difference of 0-2, plus lambda_major.
- The geometry table holds the probe pairs of both levels for 69 169 cells (rho, f < 147, sign) and the full-weight upper level per (rho, sign).
- Three corrections to the column-weight decoder were measured:
  - 12 cells whose last probe has weight 0;
  - 407 cells where a pair at +-p with p w = 64 is really one merged probe (row weights decide, checked on all 276 860 level geometries);
  - 92 rho values reached only with a clamped LOD.
- Three rules were found while validating:
  - the minor-axis LOD is clamped at 0 before rho is taken;
  - the major axis is the gradient with the larger exponent and 9-bit mantissa, ddx on a tie;
  - clamp-to-edge clamps the fixed-point probe position.

**Gate 4.** The C++ replica (`src/evaluator/texture_unit.h`, through `uzp-evaluator-tests texture-unit`) equals the GPU on 960 000 of 960 000 samples (`tables.py validate`). The 48 sets vary:
- texture sides from 32 to 1024, and uniform 16-bit, dark 16-bit and 8-bit texels;
- biases 0 and -1.5 (Painter's two), repeat and clamp;
- random, near-isotropic and 9-bit-bin-edge footprints from a quarter texel to twice the texture, ratios 1 to 11;
- both signs and axes, and ddx and ddy swapped.

Gradient cross terms up to 1e-5 of the major component change nothing on the hardware.

**Painter's arithmetic, refined.** Decision 060's model was found on footprints below LOD 1. The decision-078 recordings were planned as validation data, and they separated four further rules. Running the GPU's sampler with these rules reproduces every value of the seven minifying goldens, except 9 one-code values of BilinearHQ at 7.3 degrees, which stay refused.
- **The rotation** is applied as S R. The angle float32(degrees) float32(pi/180), its cosine and its sine are float32.
- **The translation** is m02 = (m00 t_u + m01 t_v) + 1/2, in float32 operations from t = -1/2 - o.
- **The v gradient** has the sign of +v: ddy = (m01, m11)/W.
- **Each mip texel** is the GPU's linear filter at the centre of its 2 x 2 block, with the operands truncated below the largest texel's exponent.

Not separated: the rounding of the angle (three variants fit) and the order of the elements' products.

**Results, evaluator, CPU and GPU.** Every axis-aligned user of `resample-uv-minify`, `-impulse`, `-anisotropic`, `-anisotropic-impulse`, `-lod`, `-lod-boundaries` and `-rotation` equals both recordings value for value, in all four sets. `-rotation` covers 90, 180, 270 degrees and the rotation-0 controls. So does the never-fitted `resample-uv` user 6, under both filters and both wraps. That is 64 golden tests. Random minifying stacks are equal on GPU and CPU (`projection-gpu-vs-cpu`).

Model panel under the owner's delegation (cx/gpt-6-astra, kimi/kimi-k3, xai/grok-4.5, 2026-10-12):

| Claim | Verdicts |
|---|---|
| C1: gate 4 passes; pin to RTX 4090, driver 617.14 and the sampler state; a driver change re-runs the validation | AGREE x1, PARTLY x2. It is a tested-domain result, not a proof over every cell. Report table coverage and an exponent sweep. Biases other than 0 and -1.5 are untested, and Painter uses only those two. |
| C2: adopt the refined arithmetic and disclose that the 078 goldens were fitted | PARTLY x3. For that arithmetic the 078 goldens are now regression evidence. User 6 is a thin held-out. Add a fresh recording that is never fitted. |
| C3: lift the refusal only for rotations by multiples of 90 degrees, square power-of-two bitmaps, square sets, Repeat and RepeatNone; magnification unchanged | AGREE x1, PARTLY x2. The predicate must be exact and enforced at run time, with refusal tests. |
| C4: no exception entry; manifest supported for that context, release gap for the rest | AGREE x2, PARTLY x1. The manifest notes must state the exact predicate and the pin. |

## Decision

1. **Gate 4 passes on the tested domain.** The replica, its tables and the rules above are the recording GPU's texture unit for axis-aligned gradients. They are pinned to the RTX 4090, driver 617.14, Vulkan, a float32 texture with linear filters and mips, and maxAnisotropy 4. After a driver or GPU change, `tables.py validate` must pass before the support is used, and `tables.py measure` re-acquires the tables if it does not.
2. **Painter's arithmetic around the unit is the refined model above.** It refines decision 060. For that arithmetic the decision-078 goldens are fitted regression evidence. The held-out evidence is `resample-uv` user 6 and the hardware validation of the unit.
3. **The refusal is lifted for one domain only:** bilinear minification at a rotation that is a multiple of 90 degrees, of a square power-of-two bitmap on a square set, with Repeat or RepeatNone. `CheckSampling` refuses every other minifying case with `evaluator:unsupported_source`, and the `sources` case tests those refusals. The magnifying path keeps its double UV.
4. **The capability manifest records the split.** `compositor:minification` is supported with the eight goldens. `compositor:minification-rotated` is a release gap. No exception entry is proposed.
5. **Follow-ups that do not block this decision:**
   - a per-cell coverage report of the validation;
   - one fresh recording, never fitted, of axis-aligned minification at new scales, offsets and bitmap sizes. This is an owner action at Painter.

## Alternatives Considered

- **Keep refusing until a fresh recording exists.** Rejected: the unit is validated directly against the hardware, and every recorded axis-aligned value is exact on both backends.
- **Lift rotated minification too.** Rejected: the replica has no 2-D probe direction path.

## Consequences

- Fill and UV projections that minify an axis-aligned square power-of-two bitmap evaluate exactly. This covers the common case of a large bitmap on a smaller set.
- `uv-sampling.json` `uv-bilinear-minification` describes the model and stays a gap for the rotated remainder.
- The evaluator embeds about 0.4 MB of tables. The GPU path uploads the tables and each minified bitmap's mip chain into the bitmap cache.
