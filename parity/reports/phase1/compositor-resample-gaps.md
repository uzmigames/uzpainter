# `phase1.9_compositor-resample-gaps` — local run and the minification recording request

Child of `phase1.14_compositor-core` (P1-COMPOSITOR; `docs/architecture/04-layer-stack-and-compositing.md` §4, §5). Decision 028: the Tier 0 comparisons against the private oracle store and the GPU checks run locally on the owner's machine, and this report is their evidence. Numbers and hashes only; every recorded Painter output stays in the private store. Decision 043 records the choices below and the model panel's verdicts.

**Result: the bilinear near-tie is fixed at its root and `resample-uv` magnification and 1:1 are exact on both backends under every filter and wrap mode (s0, s1, s3 User0-5, 7; s2 User0-7). Bilinear minification is now identified (§5, decision 056). Painter samples a minified bitmap with the recording GPU's anisotropic texture unit through Vulkan; a probe of that unit reproduces the new goldens and the held-out map to one code, but not bit for bit. The evaluator keeps refusing minification with `evaluator:unsupported_source`, and the minification items stay open. The UV offset is now applied before the scale and the rotation (§5.3), on both backends. Painter's arithmetic around the texture unit is now identified exactly (§6.1, decision 060): with the GPU's sampler in the loop, every value of every minification golden matches. The texture unit itself has no closed-form software replica (§6.2, decision 061), so the refusal stays; a tabulated replica for axis-aligned footprints is the next step.**

## 1. Run record

| Item | Value |
|---|---|
| Hardware | NVIDIA GeForce RTX 4090, Windows 11 Pro 10.0.26200 |
| Backend | DX12; kernels `cs_6_6` through the render layer's kernel cache |
| Build | Zig 0.15.2, `zig build evaluator-tests` exit 0 with `-Wall -Wextra -Werror` |
| Oracle | `%LOCALAPPDATA%\UzPainter\parity-store`, current envelope `painter-12.1.5+js-api.1.1.20` (the `resample-uv` exported maps are byte-identical to the 12.1.0 envelope's); recordings `r1` and `r2` identical on every map |

## 2. The near-tie (item 2.1)

The phase1.8 rule summed float32 texels `float32(c / 65535)` with the 8-bit integer weights exactly and rounded once. One value per set was one code high (s0 and s1 User2, scale 1.37 × 2.11, texel (175, 18), green: codes 38535, 65357, 55719, 1194 weighed 15, 52, 44, 145; the exact sum lies 2^-9.7 ulp above a float32 midpoint and rounds up to 412591 / 2^20, Painter holds 412590 / 2^20).

**Root cause: Painter's bilinear filter is the GPU's linear filter of a float32 texture, which does not sum the float texels exactly.** Measured on the recording GPU (`uzp-evaluator-tests bilinear-hardware`: a 64 × 64 float32 RGBA texture of random texels, with designed operands beside 1.0 and 0 and the near-tie quad, sampled by a linear wrap sampler at float32-exact coordinates for every 8-bit weight pair on 64 taps and 4 channels, 16 777 216 samples), the GPU equals on every sample:

- weights w11 = (fx fy + 128) >> 8, w10 = fx − w11, w01 = fy − w11, w00 = 256 − fx − fy + w11;
- E the binary exponent of the largest texel of non-zero weight (t_max in [2^(E−1), 2^E)); each operand floor(t 2^(28 − E));
- the weighted sum of the operands times 2^(E − 36), rounded to the nearest float32, ties up.

| Variant against the GPU (16 777 216 samples) | Mismatching samples |
|---|---|
| **the rule above** | **0** |
| 28 absolute fractional bits (E capped at 0) | 11 035 |
| 27 / 29 bits below E | 108 770 / 41 274 |
| ties to even instead of up | 25 242 |
| w11 rounded ties down (the goldens' frame applied to the GPU's) | 262 144 |
| float32 texels summed exactly, rounded to nearest even / ties up | 80 551 / 56 634 |
| the same probe as an RGBA16_UNORM texture | 16 709 251 (the GPU filters UNORM16 at a lower precision): Painter samples float32 textures |

A bitmap stored bottom-up (rows flipped, fy' = 256 − fy) turns the GPU's ties-up w11 into round_half_down(fx fy / 256) = (fx fy + 127) >> 8 in the goldens' top-down frame, the rounding phase0.7 fitted. With those weights the rule reproduces all 3 867 033 magnifying and 1:1 values of s0, s1 and s3, and keeps a texel weighed 256/256 unchanged (E is its own exponent). An earlier fit, 28 absolute fractional bits, also fitted `resample-uv` (27 bits break 16 values, 29 to 33 keep the miss) but broke `blend-basic` user7 (a 1:1 bitmap on RGB32F, 514 values): the exponent-relative operands of the GPU are what fits both.

Evaluator: `src/evaluator/projection_uv.{h,cpp}` `BilinearFilter` (integers, the reference) and `src/evaluator/shaders/evaluator_project.hlsl` (the same integers from the floats' bits, the sum in `uint64_t`, the rounding by shifts, the scale an exact power of two); manual filtering, so the evaluator does not depend on any GPU's sampler. Every golden through the projection was re-compared on both backends (`colour-ramps-*`, `blend-inputs`, `blend-basic` and the other blend sweeps, `blend-order`, `group-masks`, the mask goldens, `height-normal-*`, island edges and `resample-uv` s0-s3): exact. `parity/semantics/uv-sampling.json` is re-derived by `tests/evaluator/sources_fits.py` (`uv-bilinear-repeat` now `exact`, parameter `operand_bits` 28); `colour-transfer.json` is unchanged. `Nearest` keeps the float32 texel.

## 3. Bilinear minification (item 2.2) and the recording it needed

`resample-uv` User6 projects field A (256 × 256; R = 257 x, G = 257 y, B = 256 x + y) at scale 3.3. Every channel is a linear ramp, so in the interior any normalised filter returns 257 × its centroid: the golden measures the kernel's first moment, ±1-code arithmetic noise, and the step response at the wrap seams, which the sample positions x = -293.25 + 3.3 i cross at only four sub-texel offsets per axis. Measured (both recordings, all rows identical in R and all columns in G):

| | BilinearHQ (s0; s3 with RepeatNone) | BilinearSharp (s1) |
|---|---|---|
| interior against single-level bilinear | a constant -17.65 codes on every value range (a -0.0687-texel shift), deterministic per (x fraction, x parity) | mean 0.00, a ±1.35-code sawtooth depending on x mod 2 |
| weight beyond the seam at d = -0.95 / -0.45 / +0.45 / +0.95 texel | 0.120 / 0.239 / 0.702 / 0.841 | 2/256 / 35/256 / 221/256 / 254/256 (symmetric) |
| seam influence at \|d\| ≥ 2.35 | none | none |
| clamp edges (s3) | about 0.12 + 0.04 of the weight at 1.45 and 2.45 texels on one side, 0.09 + 0.03 on the other | — |

Rejected structures (interior exact rate; max error with the seams): the recording GPU's own trilinear and 16× anisotropic sampling of a float32 box mip chain (bottom-up, gradients of 3.3 texels, LOD bias −1.5 to 0, explicit LOD 0 to 2 in 1/32 steps; Sharp at best 39-51 % of the interior, max ≥ 1 285 codes; HQ never); numerically, single-level bilinear on box mip levels 0 to 3, the mip chain in float, UNORM16 rounded or truncated; trilinear between levels (0, 1), (1, 2) and (0, 2) at every 8-bit blend weight (Sharp at best 45 % of the interior, max 162 codes; HQ 0 %); an interval analysis shows no blend weight even fits the interior noise. `phase0.7_tier0-stability-fits` failed the same way (`resampling.json`). The data cannot pin a kernel of unknown support, level selection and arithmetic (panel: AGREE × 3), so the refusal stays and the fit waits for a recording that determines it.

**Recording request** (owner or the agent that owns Painter; `uzpainter parity record`, both recordings, PNG 16, padding infinite, no dithering, like every Tier 0 golden). Mesh `grid2x2` (four texture sets s0-s3), resolution 256, channels User0-7 RGB16, one fill per user channel with a UV projection in `Factors` scale mode:

| Set | Filter | Wrap |
|---|---|---|
| s0 | BilinearHQ | Repeat |
| s1 | BilinearSharp | Repeat |
| s2 | BilinearHQ | RepeatNone |
| s3 | BilinearSharp | RepeatNone |

1. `resample-uv-minify` (the fit), bitmap `pattern64` (the existing 64 × 64 pseudo-random 16-bit RGB fixture; footprint = 64 s / 256): User0 scale 5.13 (footprint 1.28), User1 6.07 (1.52), User2 7.77 (1.94), User3 10.3 (2.58), User4 13.2 (3.3), User5 16.6 (4.15), User6 13.2 × 5.13 (3.3 × 1.28), User7 7.77 with rotation 30 and offset (0.123, 0.456). The irregular scales give many sub-texel phase classes; with random texels each class is an over-determined linear system for the effective taps (check rank before reading them), across footprints for the level selection, and with RepeatNone for the clamp edges.
2. `resample-uv-impulse` (direct kernel reads), a new authored fixture `impulse64` (64 × 64 RGB16: R 65535 at the four texels (16, 16), (48, 16), (16, 48), (48, 48) on 0; G 49152 at the same texels on 16384, for linearity and offset; B 65535 for x < 32, 0 otherwise, a step): User0-5 the scales of 1. above, User6 13.2 with offset (0.001953125, 0.0009765625), User7 7.77 with offset (0.0048828125, 0).
3. Held out for validation, not fitted: `resample-uv` User6 (field A at 3.3, both filters, Repeat and RepeatNone), and the User6-7 channels of 1.

Then: fit the kernels (`tests/evaluator/sources_fits.py` and the fits module of the new goldens), implement them in `ProjectTexel` and the projection kernel, lift the `CheckSampling` refusal, and add the GPU-vs-CPU minifying stacks (items 2.2-2.4, 3.1, 3.2, 4.1).

## 4. Unit tests and kernels

| Case | Evidence |
|---|---|
| `bilinear-hardware` (RTX 4090) | `BilinearFilter` equals the GPU's linear filter of float32 texels on 16 777 216 of 16 777 216 samples; the GPU rounds the near-tie down |
| `sources` (CPU) | 1:1 copies under every filter on all nine formats (unchanged texels); the half-texel bilinear sample against an independent double-precision reference; the near-tie (412590 / 2^20, where float texels summed exactly give 412591 / 2^20), a 256/256 texel unchanged, 27 bits beside 1.0 |
| `projection-gpu-vs-cpu` | 36 random projection stacks over the nine formats: 43 581 440 samples, GPU = CPU bit for bit |
| `gpu-vs-cpu`, `masks-gpu-vs-cpu`, `order` | unchanged, bit for bit and green |

## 5. The minification recordings and what they determine (decision 056)

The recordings of §3 exist (decision 048: `resample-uv-minify`, `resample-uv-impulse`, current envelope; r1 = r2 on every map). Painter 12.1.5 renders through Vulkan (its log and `substance_vk_sal.dll`), so the measurements below use `tools/parity/vk_sampler_probe`: a standalone Vulkan compute probe, needed because the render layer is DX12-only until Phase 3. The probe samples the bitmap as a float32 texture stored bottom-up, with a float32 box mip chain, by `SampleGrad` at Painter's UV. `python -m tools.parity.vk_sampler_probe.measure <work-dir>` reruns everything below on the recording GPU (RTX 4090, driver 617.14).

### 5.1 The texture unit

The trilinear blend factor of the anisotropic path (t, in 1/256, at LOD fraction f = n/16) depends on maxAnisotropy:

| maxAnisotropy | t |
|---|---|
| 1 | f |
| 2, 3 | 1.5 f |
| 4 to 7 | 1.75 f |
| 8 to 16 | 2 f |

The same GPU through D3D12 uses another band ([0.25, 0.75] at 16, slope 2), and no bias reproduces Painter's users 4 and 5 there. An isotropic gradient of 1.2825 texels takes two probes (weights summing to 510 or 511 / 512), while 1.0, 1.5, 2 and 3 texels take one; Painter's user 0 shows the same two probes.

### 5.2 The filters

**BilinearSharp** is one sample with maxAnisotropy 4 at LOD bias -1.5. **BilinearHQ** combines nine samples, each taken at +-1/3 output texel with the gradients divided by 3:

- the tent [1 2 1]^2 / 16 weighs them, with the (+1/3, +1/3) sample replaced by the centre;
- the result is blended with the centre sample by alpha = min(footprint - 1, 1).

HQ's least-squares class weights (centre, edge, corner, x 256) are those of the rule: 206.28, 9.04, 4.52 at footprint 1.2825; 164.92, 16.56, 8.28 at 1.5175; 90.12, 30.16, 15.08 at 1.9425; 80, 32, 16 at 2.575 and above.

Exact fraction of the values (max |delta| in codes), first recording. RepeatNone compares only the covered texels.

| Golden | Sharp Repeat (s1) | Sharp RepeatNone (s3) | HQ Repeat (s0) | HQ RepeatNone (s2) |
|---|---|---|---|---|
| `-minify` users 0-3 | 1 (0) | 1 (0) | 0.964-0.999 (1, user 1: 28) | 0.969-0.999 (1) |
| `-minify` users 4, 5 | 0.99996, 0.99990 (1) | 1 (0) | 0.9986-0.9987 (1) | 0.9983-0.9987 (1) |
| `-minify` user 6 (13.2 x 5.13) | 1 (0) | 1 (0) | 0.409 (1 879) | 0.407 (1 500) |
| `-minify` user 7 (rotation 30, offset) | 0.9927 (244) | 0.9957 (170) | 0.941 (86) | 0.941 (60) |
| `-impulse` users 0-7 | 1 (0) | 1 (0) | 0.999-1 (1) | 0.994-1 (1) |
| held out: `resample-uv` user 6 | 0.99985 (1) | | 0.99841 (1) | |

### 5.3 The UV offset order

The offset precedes the scale and the rotation:

- (a, b) = ((u - 1/2 - o_u) s_u, (v - 1/2 - o_v) s_v)
- u' = (cos r a + sin r b) + 1/2
- v' = (-sin r a + cos r b) + 1/2

On `-minify` user 7 (Sharp, Repeat), the order the evaluator used, with the offset applied last, misses by 14 551 codes on average; the new order is 99.27 % exact. `-impulse` users 6 and 7 (offsets at scales 13.2 and 7.77) are exact. Every earlier golden has its offset at scale 1 without rotation, where both orders agree, so no published residual changes.

`ProjectTexel` (`src/evaluator/projection_uv.cpp`) and `evaluator_project.hlsl` now apply the offset first. The `sources` case checks that an offset of 4/W at scale 0.5 moves the bitmap by two texels, and `projection-gpu-vs-cpu` checks GPU = CPU on random offsets, scales and rotations.

### 5.4 What stays open and why

The residual is one code wherever the probe's model applies. The larger misses come from three sources:

- a subsample or sample coordinate within 0.006 / 256 texel of a fixed-point rounding boundary (users 1 and 7), which points to Painter's float32 UV;
- HQ under an anisotropic footprint (user 6), where the rule is unknown;
- the float32 combination of HQ's nine samples.

The evaluator filters manually, CPU = GPU bit for bit, and must not depend on one GPU's sampler (decision 043). Lifting the refusal therefore needs a bit-exact integer model of:

- the anisotropic unit's probe count, positions and weights against the gradient bits;
- its fixed-point LOD;
- the per-level weight, trilinear and supersample arithmetic;
- Painter's float32 UV.

These are measurement tasks on the recording GPU through Vulkan, not recordings. If no bit-exact model emerges, an exception-register proposal (decision 017) takes its place.

A further Painter recording is needed for two things only, both filters, with rotations and offsets (which would also validate the UV model):

- HQ's anisotropic rule: a sweep of anisotropic footprints, e.g. s_u in {2, ..., 16} x s_v in {1.1, ..., 4} on `pattern64`;
- LOD at or above 1: footprints from 4 to 16 texels at irregular steps.

The constants were measured on driver 617.14; the probe re-measures them after a driver or Painter update.

## 6. Painter's side exact, the texture unit measured (decisions 060 and 061)

### 6.1 Painter's arithmetic around the sampler

`python -m tools.parity.vk_sampler_probe.measure <work-dir>` uses the recording GPU's sampler as the texture unit and implements everything else as below. Against both recordings it reproduces every value of `resample-uv-minify` and `resample-uv-impulse` (both filters, both wraps) and of the held-out `resample-uv` user 6: 132 map comparisons, 13 566 120 values, 0 differing.

| Piece | Rule | What it fixed |
|---|---|---|
| UV | M = float32 of the double composition T(1/2) R S T(-1/2 - o); u' = fma(m00, u, m01 v) + m02 and v' = fma(m10, u, m11 v) + m12, with u = float32((i + 1/2)/W) and v = float32(1 - (j + 1/2)/H) | `-minify` user 7 Sharp: 1 430 misses with the double UV, 0 with this one; other orders miss 366-3 533 |
| Mips | each level is the exact mean of four texels, rounded to float32 with ties up | users 4-5 Sharp: 8 and 20 one-ulp misses become 0; ties to even or float32 sums miss 8-252 |
| Sharp | one SampleGrad, maxAnisotropy 4, LOD bias -1.5 | (decision 056) |
| HQ samples | ddx, ddy are the fine derivatives of (u', v') in the 2 x 2 quad; nine samples at (u' + DX ddx) + DY ddy in float32, with DX, DY in {-1/3, 0, 1/3} and the gradients / 3 | user 1's 28-code column and user 7's 86 codes |
| HQ sum | acc in float32, in the order centre, (+, 0), (-, 0), (0, -), (0, +), (+, -), (-, -), (-, +), centre, with weights 4, 2, 2, 2, 2, 1, 1, 1, 1 / 16 | the only one of the 9! orders that fits users 3-5 (alpha = 1) |
| HQ blend | C1 is a level-0 bilinear sample at (u', v'); alpha = clamp(min(\|ddx\|, \|ddy\|) w - 1, 0, 1) in float32; the value is fma(C1, 1 - alpha, acc alpha) | user 6 (anisotropic) goes from 41 % to exact; the per-pixel alpha turns 19 383 misses into 0 |

Two limits remain:

- Composing the matrix in float32 or in double gives the same pixels, so the goldens do not separate the two.
- Every magnifying golden has the same fixed-point coordinates under the double and the float32 UV, so the evaluator keeps its double UV until a minification model lands (decision 060).

### 6.2 The texture unit, through Vulkan

`python -m tools.parity.vk_sampler_probe.texture_unit <work-dir>` measures it on synthetic textures only (impulses, ramps, random texels). Footprints are in texels; r = major / minor.

| Quantity | Measured |
|---|---|
| Texel coordinate | X = floor(256 (u W - 1/2) + 1/2) from the float32 u: 0 of 300 000 adversarial u differ |
| Gradient input | 9-bit truncated mantissas: the two ends of each bin agree on 20 000 pairs; the 141 LOD steps over p in [1, 2) all fall on the 1/512 grid |
| Probes, r in (1, 2] | two, at +-d: d is a multiple of 1/128 texel, about 1 - 1/r with irregular one-step deviations; isotropic footprints give d > 0 for some mantissas |
| Probes, r in (2, 4] | four, at +-1/2 and +-3/2, weighted by their coverage of [-r/2, r/2] in units of 1/512 (r = 2.25: 227 and 29) |
| Probes, r > 4 | clamped to r = 4 |
| Taps | the x split is round-half-up(w fx / 256); the y split rounds half up in the far column and half down in the near one (1 920 decoded probes); equal-weight probes tie to even, so the weights carry more than 9 bits |
| Levels | the offsets follow the trilinear position (2.8 x 1.4 at LOD 0.49: 0.447 level-1 texels, not 0.5); the switch to magnification depends on the major axis |
| Accumulation | the decision-043 rule on the per-texel weights matches 6 911 of 6 912 level-0 multi-probe samples (108 790 of 108 864 with LOD-biased footprints); the rest are one ulp off |
| Rotation | the two-probe offsets at 10, 30, 45 and 60 degrees are (90, 20), (76, 48), (46, 46), (48, 76) / 256; along the axis they would be (84.7, 14.9), (74.5, 43.0), (60.8, 60.8), (43.0, 74.5) |

Over all 131 328 pairs of 9-bit mantissas of one octave, the two-probe offset d is monotone in the minor axis but has 8 834 reversals along the major one. Linear-programming feasibility (scipy HiGHS) rejects:

- every form d = G(F(a) + P(b)) with G and P monotone, which covers all separable and log-domain forms;
- d = G(log2(a - b) + F(a)).

### 6.3 The stop point and the next step

The texture unit is a fixed-point datapath for which no closed form was found: approximate ratios, weights with more than 9 bits, level-dependent offsets and a 2-D direction path. Decision 061 stops the closed-form search here.

- The refusal stays (`evaluator:unsupported_source`). Items 2.2-2.4, 3.1, 3.2 and 4.1 stay open, and no exception-register entry is proposed.
- The next step is a separate task: a tabulated replica for axis-aligned footprints (rotation a multiple of 90 degrees) at Painter's two biases. Its gates come in order:
  1. bound the domain;
  2. prove the table keys sufficient;
  3. resolve the accumulation;
  4. validate sample for sample against the hardware, before any golden.

  The tables are pinned to driver 617.14.
- Rotated minification stays refused. A Painter recording is needed only to validate such a replica beyond these captures: anisotropic HQ, LOD at or above 1, and rotations (decision 056).

## 7. The tabulated replica stops at the accumulation gate (decision 071)

`python -m tools.parity.vk_sampler_probe.replica_gates <work-dir>` measures decision 061's gates on synthetic textures (RTX 4090, driver 617.14, Vulkan).

| Gate | Measured | Result |
|---|---|---|
| 1. Arithmetic around the probes | t = min(256, floor(7 f / 4)) on the upper level; rule F splits a probe of weight w: x1 = rhu(w fx / 256), x0 = w - x1, w11 = rhu(x1 fy / 256), w01 = rhd(x0 fy / 256) | 4 325 376 tap weights, 0 differing |
| 2. Table keys | bits below the 9-bit gradient mantissas; ddx and ddy swapped (rotation 90) | 0 of 1 800 kernels differ, at both biases |
| | sign of the major-axis gradient | 82 and 56 of 1 800 differ: a table dimension |
| | geometry (probe pairs) as a function of (rho, f) with rho = lambda_major - lambda | 0 of 200 cells differ between two keys; 0 of 200 between bias 0 and bias -1.5; the sign changes 116 of 200 |
| 3. Accumulation | each probe: E of its largest weighed texel, operands floor(t 2^(28 - E)), exact integer sum | one probe per level: 400 000 of 400 000 equal; two probes, representable sums: 126 817 of 126 817 |
| | several probes summed exactly, rounded ties-up | rounded two-probe sums: 3 of 193 183 one ulp low; uniform 16-bit codes 0 of 150 000; dark 8-bit codes 2 of 150 000; dark 16-bit codes 51 of 150 000 |

The misses lie 0 to 1/16 ulp above a rounding midpoint and are rounded down. A dial experiment steps one operand unit across a float32 tie:

- the hardware sum equals the exact sum in 559 cases;
- it is lower by one or more units of the larger-exponent probe's last bit in 54 cases, all with that probe's sum odd;
- 210 odd cases show no deficit.

No truncation, rounding or alignment rule that was tried fits every dataset (decision 071). Gate 3 therefore fails:

- the replica is not built and the refusal stays;
- items 2.2-2.4, 3.1, 3.2 and 4.1 stay open;
- the next step is a focused measurement of the multi-probe accumulator;
- the validation goldens of decision 078 stay unused until a replica exists.

## Reproduce

```
zig build evaluator-tests
python -m pytest tests/evaluator/test_compositor_sources_projection.py
python tests/evaluator/sources_fits.py zig-out/bin/uzp-evaluator-tests.exe <work-dir>
python -m tools.parity.vk_sampler_probe.measure <work-dir>
python -m tools.parity.vk_sampler_probe.texture_unit <work-dir>
python -m tools.parity.vk_sampler_probe.replica_gates <work-dir>
```
