# `phase1.11_compositor-blend-gaps`: local run, fits and recording requests

`phase1.11_compositor-blend-gaps` follows up the modes that `phase1.10_compositor-blend-kernels` left inexact. It is part of P1-COMPOSITOR (`docs/architecture/04-layer-stack-and-compositing.md` §3).

Under decision 028, the Tier 0 comparisons against the private oracle store and the GPU checks run locally on the owner's machine, and this report is their evidence. It gives numbers and hashes only; every recorded Painter output stays in the private store. Decisions 053, 054 and 073 record the choices below and the model panel's verdicts.

**Result:**

- **NormalMapCombine, NormalMapDetail and NormalMapInverseDetail are exact at every recorded opacity.** This holds on every format, on the Normal channel, against both recordings, on the CPU and on the GPU.
  - The upper normal is rotated with the recording GPU's GLSL arcsine and its sine and cosine. They are equal through Vulkan, which Painter 12.1.5 renders with (decision 056), and through OpenGL; D3D12's arcsine differs.
  - The arcsine is a polynomial identified by exhaustive measurement. The sine and cosine come from measured tables.
- **Tint, Saturation, Color and Value are exact (§3, decision 073).** Their float32 hue was identified on the hue grid `blend-component-hue` (decision 067).
  - The weights are centred on the primaries, and the hue numerator is p - (q + 3e).
  - Every map of that golden and of the held-out `blend-component` equals both recordings, on every channel format, on the CPU and the GPU.
  - The earlier double-precision law left up to 194 RGB16 and 20 122 RGB32F values off per map.
- **PassThrough is exact (§4, decision 054).** It is fitted on the UI-set golden `semantics-ui/group-passthrough-masks`. The children composite onto a copy of the stack below the group, and the group then mixes by its opacity and mask, fma(g - a, t, a).
- The GPU equals the CPU bit for bit for every mode.

## 1. Run record

| Item | Value |
|---|---|
| Hardware | NVIDIA GeForce RTX 4090, Windows 11 Pro 10.0.26200, driver 617.14 |
| Backend | DX12; kernels `cs_6_6 -Gis` through the render layer's kernel cache |
| Build | Zig 0.15.2, Debug; `zig build evaluator-tests` exit 0 with `-Wall -Wextra -Werror -ffp-contract=off` |
| Oracle | `%LOCALAPPDATA%\UzPainter\parity-store`; `blend-component` and `blend-normal-channel` (12.1.0 manifests), `blend-component-hue` (current envelope `painter-12.1.5+js-api.1.1.20`), recordings `r1` (same session) and `r2` (after save and reopen), identical on every map |
| Research tooling (not committed) | a D3D12 probe of arbitrary HLSL and an OpenGL 4.3 compute context (`moderngl` in a scratch virtual environment) on the same GPU and driver; for the hue (§3.4), a numpy model of the evaluator's arithmetic and a native probe of `arith::BlendColour` |

## 2. Normal-map modes below opacity 1 (items 2.2, 3.2)

Phase1.10 rotated the upper normal n toward (0, 0, 1) by a float32 slerp built from fixed series. It was exact at opacity 1 and off below it:

- 202, 257 and 176 RGB16 values (opacity 0.5);
- 40 sRGB8 values (Detail and InverseDetail at 0.5);
- 72 042, 72 463 and 47 693 RGB32F values (0.25).

The rotation was located with the GPU's own transcendental functions, which the probes evaluate on the inputs Painter sees. The table gives differing values for Combine / Detail / InverseDetail, RGB16 at 0.5 and RGB32F at 0.25.

| Rotation | RGB16 at 0.5 | RGB32F at 0.25 |
|---|---|---|
| float32 series slerp (phase1.10) | 202 / 257 / 176 | 72 042 / 72 463 / 47 693 |
| slerp `n sin(a t)/sin t + (0,0,sin((1-a) t)/sin t)`, double-precision trigonometry | 205 / 234 / 160 | 72 310 / 76 990 / 30 668 |
| slerp with the D3D12 `acos`, `sin`; best of 40 orders | 122 / 247 / 169 | 16 721 / 26 305 / 21 276 |
| `(n.xy k, cos(a t))`, `k = sin(a t) rcp(sqrt(fma(-z, z, 1)))`, D3D12 `acos` | 61 / 53 / 14 | 5 252 / 5 657 / 2 165 |
| the same with `k = sin(a t) rsqrt(fma(-z, z, 1))` | 35 / 25 / 8 | 2 144 / 2 179 / 1 028 |
| the same with the GLSL `acos` (a low-accuracy polynomial, error 6.7e-5) | 43 332 / 67 454 / 21 536 | 160 532 / 159 518 / 107 457 |
| the same with t = atan2(sqrt(fma(-z, z, 1)), z), GLSL | 12 / 24 / 9 | 1 799 / 1 848 / 740 |
| **the same with t = float32(pi/2) - asin(z), GLSL `asin`** | **0 / 0 / 0** | **0 / 0 / 0** |

Nudging the D3D12 angle by +1 ulp alone fixes 1 164 of the remaining 1 350 Combine texels. The angle was the only difference, and only the GLSL arcsine is exact.

The evaluator (`arith.cpp TowardFlat`, `evaluator_blend.hlsl`) computes:

- z clamped to [0, 1];
- t = float32(pi/2) - hw::Asin(z);
- a = alpha t;
- n' = (n.x k, n.y k, hw::Cos(a)), with k = hw::Sin(a) hw::Rsqrt(fma(-z, z, 1)).

Opacity 1 and the flat normal (no golden; see §5) keep n.

**`hw::Asin`, the GPU's GLSL arcsine.** For t = |x| <= 0.57:

- s = t t;
- r = ((((c4 s + c3) s + c2) s + c1) s + c0) s, every step a fused multiply-add;
- asin = fma(r, t, t).

Above 0.57, t' = sqrt(fma(-1/2, t, 1/2)) with the hardware square root, and asin = fma(-2, P(t'), float32(pi/2)). The constants are c0..c4 = 1.666701424e-1, 7.484657646e-2, 4.675685871e-2, 1.816697683e-2, 5.175137819e-2.

How it was established:

- A least-squares fit of degree 4 in s on 200 000 GPU values reproduced them to 0.56 ulp. The constants above reproduce them exactly.
- An exhaustive comparison in GLSL found 0 differences on every float32 of [0, 1] (1 065 353 217 inputs) against the GPU's `asin`. Each fused multiply-add was tested two ways: single rounding, and the evaluator's `Fma` (exact product plus one double addition).
  - The double form differs only on the 8 388 607 subnormal inputs. The GPU flushes those to +0, and `hw::Asin` does the same.
- Values above 1 and NaN give NaN, and the sign carries.
- The D3D12 `asin` agrees with the GLSL one on only 59 % of a sample, so the D3D12 compiler cannot stand in for it. `arith` checks 48 measured GLSL inputs.

**Vulkan.** Painter 12.1.5 renders through Vulkan (decision 056), so everything this fit uses was re-measured through Vulkan on the same GPU, with `tools/parity/vk_sampler_probe/vkprobe.cpp` and HLSL compiled to SPIR-V:

- `asin` (GLSL.std.450 Asin) equals `hw::Asin` on 16 777 216 inputs spread over [0, 1];
- `sin` and `cos` equal the tables on 16 777 216 inputs over [0, pi/2];
- `rsqrt` and `sqrt` equal their tables on every float32 of [1, 4);
- `1/x` equals the reciprocal table on every float32 of [1, 2).

**`hw::Sin`, `hw::Cos`.** The GPU's sine and cosine are identical in D3D12 and GLSL. They read their argument as a fixed-point turn: u = x float32(1/(2 pi)) rounded toward zero to float32, and k = floor(u 2^25).

The candidate rules were scored on 458 752 consecutive inputs at seven points of [0, pi/2]:

| Rule | Inconsistent | Index changes with no output change |
|---|---|---|
| **u toward zero, floor(u 2^25)** | **0** | **1** |
| u to nearest, floor(u 2^25) | 69 298 | 69 298 |
| u toward zero, floor(u 2^26) | 0 | 82 976 |

The rule was then checked exhaustively: the output depends on k alone on every float32 of [0, float32(pi/2)] (1 070 141 404 inputs).

- Two tables of 2^23 entries cover that range: `src/evaluator/tables/hw-sin.zlib` (306 426 bytes) and `hw-cos.zlib` (330 637 bytes). They are stored as zlib of second differences, like the log2 and exp2 tables.
- They are measured on D3D12 by `uzp-evaluator-tests trig-hardware`, which rebuilds the stored files byte for byte.
- The GPU kernels read them from the function-tables buffer that Levels already uses. That buffer grows from 128 to 192 MiB and is created on first use.

**Result on both recordings, CPU and GPU:** `blend-component` s4-s6 differ on 0 values on every user channel: RGB16 and sRGB8 at opacity 1 and 0.5, RGB8, RGB16F, L16, RGB32F at 0.25. `blend-normal-channel` s1-s3 differ on 0 values. The three modes are `exact` in `parity/semantics/blend-kernels.json`, and their phase1.10 notes are removed from the capability inventory.

## 3. Component modes on colour channels (item 2.1)

### 3.1 The hue law

The hue the four modes take was measured on the RGB32F channel at opacity 0.25 (r = (v - 0.75 a)/0.25, resolution about 2^-22) and on RGB16F at opacity 1.

- The value doubling is exact, and the saturation is s = d / (max + e) with e = 2^-12 (fitted to 2^-12 × 1.0000 ± 0.0003).
- The hexcone weights of the smallest and largest component are exactly 0 and 1.
- The middle component's weight does not follow the hexcone hue of `blend-modes.json`. Its error times the chroma d is a constant, so it is an offset in the hue numerator, together with an epsilon in the denominator.

A per-sector regression (Tint, hue of field B) gives (T (d + e) - (mid - min)) / e = alpha - beta T:

| Sector (max, mid) | alpha | beta |
|---|---|---|
| rising: (R, G), (G, B), (B, R) | -2.000 | 1.000 |
| falling: (R, B), (G, R), (B, G) | +4.000 | 1.000 |

These offsets have a single form when the hue is measured from the smallest component:

h6 = C + (X - 3e) / (d + e)

- d = max - min.
- C is 1 when blue is smallest, 3 when red is, 5 when green is.
- X is the difference of the other two: g - r, b - g or r - b respectively.

Implemented in double, this law reproduces all four modes to within one 16-bit code. Grey inputs (field A's diagonal) take hue 0, which needs red to win the minimum on ties; a G = B tie needs green to win over blue. The order of tie-breaking is therefore red, green, blue. The form was put to the model panel (one answer; two models were unavailable). It found the same law from a shifted quotient, h6 = (C - 3) + (X + 3d) / (d + e), but no published implementation produces it.

### 3.2 The float32 evaluation (decision 073)

The float32 form is in `arith.cpp` (`Hue`, `HueWeights`, `ComponentBlend`) and in the HLSL kernel, which equals it bit for bit. It was identified on `blend-component-hue` (§3.3, §3.4) and has three parts.

**Hue.**

- p and q are the two components other than the smallest: g and r when blue is smallest, b and g when red is, r and b when green is.
- h6 = fma(p - (q + 3e), rcp(d + e), C), with the hardware reciprocal.
- h = h6 float32(1/6), plus 1 when negative.
- A hue just below 0 that rounds to 1.0 after the wrap is kept at 1. It is not reduced again.

**Weights, centred on the primaries**, each clamped to [0, 1]:

- red: fma(6, |h - 1/2|, -1);
- green: fma(-6, |h - float32(1/3)|, 2);
- blue: fma(-6, |h - float32(2/3)|, 2).

**Reconstruction.** v = 2 max of the value source, and lo = v fma(-d', rcp(max' + e), 1) with d' and max' from the saturation source. Saturation alone computes lo with two roundings, 1 - d' rcp(max' + e). Each component is fma(v - lo, w, lo).

The reconstruction is unchanged from the earlier fit. It was identified on the extreme components, where the weight is exactly 0 or 1:

- The smallest component equals v fma(-d, rcp(max + e), 1) on every interior texel of Tint, Value and Color (58 096 in Tint). Saturation keeps 1 - s with two roundings; the fused form leaves 2 476 off there.
- The largest component is off by one ulp on 1 010 texels under v (1 + (w - 1) s). It is exact under the lerp.

**Result on both recordings, CPU and GPU:** every map is exact.

- `blend-component-hue` s0-s4 differ on 0 values on all eight channels: RGB32F at 1, 0.5 and 0.25, RGB16F, RGB16 at 1 and 0.5, sRGB8, L16.
- The held-out `blend-component` s0-s3 (recorded on Painter 12.1.0) differ on 0 values on all eight channels: RGB16 and sRGB8 at 1 and 0.5, RGB8, RGB16F, L16, RGB32F at 0.25.

| Values differing (r1; r2 identical) | Tint | Saturation | Color | Value |
|---|---|---|---|---|
| `blend-component` RGB16 at 1 (phase1.10 → double-precision law → now) | 32 634 → 71 → 0 | 53 100 → 194 → 0 | 46 657 → 187 → 0 | 23 312 → 160 → 0 |
| `blend-component` RGB16 at 0.5 | 32 454 → 33 → 0 | 53 122 → 108 → 0 | 46 624 → 61 → 0 | 23 261 → 83 → 0 |
| `blend-component` RGB16F | 52 147 → 5 → 0 | 78 389 → 40 → 0 | 65 526 → 16 → 0 | 77 574 → 83 → 0 |
| `blend-component` RGB32F at 0.25 | 70 939 → 8 228 → 0 | 84 560 → 20 122 → 0 | 72 083 → 15 090 → 0 | 89 777 → 19 822 → 0 |
| `blend-component-hue` RGB32F at 1 (double-precision law → now) | s0 43 375 → 0, s4 5 443 → 0 | s2 37 211 → 0 | s1 10 200 → 0 | s3 5 291 → 0 |
| `blend-component-hue` RGB32F at 0.5 | s0 30 490 → 0, s4 2 953 → 0 | s2 26 501 → 0 | s1 5 292 → 0 | s3 2 760 → 0 |
| `blend-component-hue` RGB32F at 0.25 | s0 16 883 → 0, s4 1 659 → 0 | s2 16 847 → 0 | s1 2 684 → 0 | s3 1 322 → 0 |
| `blend-component-hue` RGB16 at 1 and 0.5, RGB16F | s0 250, 181, 290 → 0, s4 16, 7, 20 → 0 | s2 201, 101, 200 → 0 | s1 44, 22, 9 → 0 | s3 19, 5, 9 → 0 |
| sRGB8, RGB8, L16 on both goldens | 0 (RGB8 of `blend-component` Tint: 1 → 0) | 0 | 0 | 0 |

- The four modes are `exact` in `parity/semantics/blend-kernels.json`, whose entries now include the hue grid's residuals.
- Their release-gap notes are removed from the capability inventory.
- The scope is the recording profile: Painter 12.1.5 on the RTX 4090, driver 617.14, through Vulkan (decision 073). Painter 12.1.0 recorded the held-out golden on the same machine.

### 3.3 The recording `blend-component-hue` (decision 067)

`blend-component` is a coarse probe of the hue arithmetic:

- Its hue sources are two smooth fields with a chroma d of at least 64 codes on every texel but one.
- Its opacity-0.25 RGB32F map resolves r only to about 2^-22.

Decision 067 recorded the finer golden, `tier0/semantics/blend-component-hue`, on Painter 12.1.5 (r1 = r2 on all 40 maps; manifest in the current envelope).

- Mesh `grid4x2`, resolution 256.
- Channels: User0 RGB32F at opacity 1, User1 RGB16F at 1, User2 RGB16 at 1, User3 sRGB8 at 1, User4 RGB32F at 0.5, User5 RGB16 at 0.5, User6 L16 at 1, User7 RGB32F at 0.25.
- The authored fixture `hue-grid` (`fixtures.hue_grid`, 256 × 256 RGB16) has 16 row groups at levels (r + 1)/17. Each group holds:
  - every sector × 12 chromas from 1 to 4 096 codes × 7 middle positions;
  - the six tie types at every chroma;
  - grey;
  - 3 519 pseudo-random validation cases.
- Texture sets:

| Set | Mode | Lower fill | Upper fill |
|---|---|---|---|
| s0 | Tint | uniform colour (0.5, 0, 0): the output is the hue weights at amplitude 1 | `hue-grid` |
| s1 | Color | the same | `hue-grid` |
| s2 | Saturation | `hue-grid` | uniform colour (0.5, 0, 0) |
| s3 | Value | `hue-grid` | uniform grey 0.25 |
| s4 | Tint | `hue-grid` | `hue-grid` transposed |

### 3.4 How the float32 form was identified

The model reproduces the evaluator's input path:

- the grid read as float32(code/65535);
- the channel's read-out over its white base, fl(fl(C - 1) + 1).

On s0 User0 the reconstruction maps each weight to a distinct output, so every recorded value pins its weight to an interval about 2^-24 wide.

1. **The weights are not the hexcone form.** The low bits of the recorded weights depend on the hue range:
   - in hue sector [3, 4), all 5 179 weights in [0.5, 1) are odd multiples of 2^-24;
   - in [4, 6) every weight is a multiple of 2^-23;
   - in [0, 3) both kinds occur.

   2 - |fma(h, 6, -2)| can only give multiples of 2^-23 in [3, 4), because h has the ulp 2^-24 there. 2 - 6 |h - float32(1/3)| gives odd multiples, since float32(1/3) = 11 184 811 × 2^-25.

   For each texel, the float32 hues that reproduce all three components were then searched within 64 ulps of the law:

   | Weight form | Texels with no admissible hue (of 65 032) |
   |---|---|
   | hexcone fma(h, 6, -k) | 33 144 |
   | centred, product and sum rounded separately | 20 251 |
   | **centred, fused** | **6** (hues near 0, outside the search window) |

2. **The hue.** With the centred weights, the earlier hue h6 = fma(X - 3e, rcp(d + e), C), h = h6 float32(1/6) leaves 43 values off on s0 User0, all in the random cases.

   | Variant | Values off |
   |---|---|
   | h computed in turns (fma with rcp(6 (d + e)) and C/6, or similar) | about 20 000 |
   | numerator (p - q) - 3e | 43 |
   | numerator (p - 3e) - q | 40 |
   | **numerator p - (q + 3e)** | **0** |
   | reciprocal of (max + e) - min | 5 |
   | reciprocal of (max - min) + e, or of max - (min - e) | **0** |

3. **No second reduction.** The evaluator first reduced h with h - floor(h). Then 52 values of s0 were off. All of them are hues just below 0 that round to 1.0 after the wrap, where Painter keeps blue = 2 - 6 |1 - float32(2/3)| = 2^-23.
4. **Validation.** With these three changes, s1-s4 and the held-out `blend-component` became exact on every channel without further adjustment, on the CPU and on the GPU.

The form is a model equal to every observation, with this provenance; it is not a statement about Painter's source.

### 3.5 Open point: the reciprocal argument (optional recording)

(max - min) + e and max - (min - e) give the same value on every hue source of both goldens. The evaluator keeps the first, the form of the earlier fit (decision 073).

- They round the same exact value. The first rounds twice when max - min is inexact; the second rounds once whenever min - e is exact (min >= e/2).
- An exhaustive scan of the 16-bit sources finds 9 946 of the 2^31 (min, max) code pairs where the two differ: min codes 1 to 4 047, max codes 1 014 to 36 735. The hue grid holds none of them.

A recording that settles it would add one texture set like s0 (Tint of a 16-bit fixture over (0.5, 0, 0), RGB32F at opacity 1) to a sibling golden. Its fixture would hold these pairs as the smallest and largest components, with the middle component at both ends and at the midpoint. This is optional. No recorded map depends on the choice.

## 4. PassThrough (item 2.3, decision 054)

Painter 12.1.0's documented API cannot set the mode: the runtime member is `Passthrough`, not the documented `PassThrough`.

- Decision 054 kept it `release-gap`, not `not_migratable`, and handed the recording to `phase0.7_tier0-semantics-ui-cases`.
- That task recorded `tier0/semantics-ui/group-passthrough-masks` through the UI (decision 047; envelope `painter-12.1.5_js-api.1.1.20`). r1 equals r2 on all 24 maps.

The golden uses the `group-masks` stack:

- fields A at the root;
- a group at opacity 0.75 holding fields B in Multiply at 1 under a uniform (0.2, 0.9, 0.5) fill in Screen at 0.5;
- four mask placements (s0 none, s1 group, s2 child, s3 both);
- the same four in Normal mode (s4-s7);
- channels RGB16, sRGB8 and RGB32F.

**The phase1.4 hypothesis is refuted.** It composited the children directly into the stack with their opacities scaled by the group's, and it was off on 195 704 of 196 608 RGB16 values (up to 5 530 codes).

**The fit** composites the children onto a copy of the accumulator below the group. Each child is stored in the channel format with its own mode, opacity and mask. The accumulator then moves toward that result by the group's opacity times its mask: v = fma(g - a, t, a), one rounding.

| Variant (s0) | RGB32F values off | RGB16 values off |
|---|---|---|
| **the fit** | **0** | **0** |
| the same without the per-child storage in RGB16 | 0 | 57 250 |
| final mix `a + (g - a) t` (two roundings) | 4 716 | — |
| final mix `fma(g, t, a (1 - t))` | 3 988 | — |
| final mix `a (1 - t) + g t` (the layer mix) | 25 097 | 14 362 |
| uniform colour unquantised on RGB16 (the colour is stored like a channel value) | — | 14 036 |

**Result.** s0-s3 equal both recordings on every channel, on the CPU and on the GPU (`test_compositor_blend_gaps.py::test_passthrough_groups_equal_the_golden`).

- The group mask and the child mask need no rule of their own: the group mask scales t, and the child mask acts inside the copy.
- The Normal-mode controls s4 and s5 are exact. s6 and s7 keep the float32 partial-coverage divergence of decision 044 (`group-masks`: 129 and 57 RGB16 values, 1 sRGB8 value, and 38 927 and 20 631 RGB32F values off by one step).
- Over a backdrop that is neither opaque nor transparent, the evaluator uses the premultiplied lerp (no golden). Over a transparent one, the group's result at coverage t × its coverage, as a Normal group.

**Implementation.**

- `dag.cpp`: a PassThrough group's list starts from the enclosing prefix (`DagList::fromBackdrop`).
- `evaluate.cpp`: the children start from the accumulator, which stays pinned.
- `arith::Composite`, PassThrough branch, and the HLSL `PassThroughChannel`.
- The two refusals for masked PassThrough groups are removed.
- `blend-kernels.json` `kernel-passthrough` is `exact`, and the capability inventory note records the UI-only setting.

Assets3D: no stack in `Pipeline/` uses a PassThrough group or a `blend` key (Wand v1, Belt v5 `waist-v5/stack-belt.json` and `stack-sash.json`, hat, staff). Tunic v10 has no stack file there yet.

## 5. Normal-map modes off the recorded opacities and on a flat normal

The fit was made at the recorded opacities 0.5 and 0.25. The panel asked for off-grid evidence, and the flat normal was not covered. Decision 067 recorded both as `tier0/semantics/blend-normal-opacity` (current envelope; r1 = r2 on every map):

- s0-s2: NormalMapCombine, NormalMapDetail and NormalMapInverseDetail of fields B over fields A, at upper opacities 0.1, 1/3, 0.7 and 0.99, on RGB32F and RGB16.
- s3-s5: the same modes with the uniform normal (0.5, 0.5, 1.0): flat under fields B, fields A under flat, and flat under flat, at 0.5 and at 1.

**Result.** All 48 maps equal both recordings, on the CPU and on the GPU, with no change to the evaluator.

- The rotation of §2 holds off the recorded opacities.
- A flat upper normal (z = 1, where the formula would give `0 · rsqrt(0)`) is kept.

The three normal-map entries of `blend-kernels.json` include these residuals.

## 6. Unit tests and kernels

| Case | Result |
|---|---|
| `arith` (CPU) | passed; includes `hw::Asin` against 48 measured GLSL inputs, the 2^23-entry trigonometric index and the component hue's rules (a grey source is red; a hue wrapped to 1 is not reduced) |
| `trig-hardware` (DX12) | the embedded sin and cos tables equal the GPU on all 8 388 608 entries; every measured input lies at its own index; `hw::Sin` and `hw::Cos` equal the GPU on 8 edge values and 1 048 568 hashed inputs of [0, pi/2] |
| `kernel-sweep` (DX12) | every mode × 9 channel formats × coverage on and off × opacity 1 and 0.7: GPU = CPU on 149 422 080 samples (1 080 combinations) |
| `gpu-vs-cpu` (DX12) | random stacks over every mode and format: identical bytes (2 490 368 samples) |
| `blend-component`, `blend-component-hue`, `blend-normal-opacity`, `blend-normal-channel` against r1 and r2 | as in §2, §3 and §5: every map exact, identical on the CPU and the GPU |
| `semantics-ui/group-passthrough-masks` s0-s3 against r1 and r2 | 0 values differ on RGB16, sRGB8 and RGB32F, CPU and GPU |
| `order`, `masks`, `masks-gpu-vs-cpu` | the PassThrough model (an RGB16 three-layer case); a masked PassThrough group evaluates; random masked stacks with masked PassThrough groups: GPU = CPU on 2 490 368 samples |

## 7. Open items and owner actions

- **Item 2.1 (component modes):** met (§3, decision 073).
- **Item 2.3 (PassThrough):** met (§4).
- **Items 3.1 and 4.1:** met. `blend-component` s0-s6 and `blend-component-hue` s0-s4 are exact on every channel against both recordings, on the CPU and the GPU, in this local DX12 run on the owner's machine (decision 028). No exception is needed. Item 3.2 (normal maps) and item 3.3 (GPU = CPU) are met.
- **Optional recording:** §3.5 (the reciprocal argument of the hue). The normal-map extras of §5 are recorded and exact.
- **Owner:** push.

## Reproduce

```
zig build evaluator-tests
python -m pytest tests/evaluator/test_compositor_blend_kernels.py tests/evaluator/test_compositor_blend_gaps.py
python tests/evaluator/blend_fits.py zig-out/bin/uzp-evaluator-tests.exe <work-dir>
zig-out/bin/uzp-evaluator-tests.exe trig-hardware assets/templates <work-dir>
```
