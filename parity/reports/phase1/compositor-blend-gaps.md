# `phase1.11_compositor-blend-gaps`: local run, fits and recording requests

`phase1.11_compositor-blend-gaps` follows up the modes that `phase1.10_compositor-blend-kernels` left inexact. It is part of P1-COMPOSITOR (`docs/architecture/04-layer-stack-and-compositing.md` §3).

Under decision 028, the Tier 0 comparisons against the private oracle store and the GPU checks run locally on the owner's machine, and this report is their evidence. It gives numbers and hashes only; every recorded Painter output stays in the private store. Decisions 046 and 047 record the choices below and the model panel's verdicts.

**Result:**

- **NormalMapCombine, NormalMapDetail and NormalMapInverseDetail are exact at every recorded opacity.** This holds on every format, on the Normal channel, against both recordings, on the CPU and on the GPU.
  - The upper normal is rotated with the recording GPU's OpenGL (GLSL) arcsine and its sine and cosine.
  - The arcsine is a polynomial identified by exhaustive measurement. The sine and cosine come from measured tables.
- **Tint, Saturation, Color and Value now follow a fitted hue law.** It reproduces every texel to within one code: the residual fell from up to 53 100 RGB16 values off to at most 194, all by one code.
  - The grey (L16) and sRGB8 channels are exact.
  - The float32 operation order of Painter's hue is not identified, so the four modes stay release gaps.
  - §3.3 specifies a recording that would pin it down.
- **PassThrough stays a release gap (decision 047).** Its golden is reachable only through Painter's UI. `phase0.7_tier0-semantics-ui-cases` item 2.4 records it to the specification in §4.
- The GPU equals the CPU bit for bit for every mode.

## 1. Run record

| Item | Value |
|---|---|
| Hardware | NVIDIA GeForce RTX 4090, Windows 11 Pro 10.0.26200, driver 617.14 |
| Backend | DX12; kernels `cs_6_6 -Gis` through the render layer's kernel cache |
| Build | Zig 0.15.2, Debug; `zig build evaluator-tests` exit 0 with `-Wall -Wextra -Werror -ffp-contract=off` |
| Oracle | `%LOCALAPPDATA%\UzPainter\parity-store`; `blend-component` and `blend-normal-channel`, recordings `r1` (same session) and `r2` (after save and reopen), identical on every map |
| Research tooling (not committed) | a D3D12 probe of arbitrary HLSL and an OpenGL 4.3 compute context (`moderngl` in a scratch virtual environment) on the same GPU and driver |

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

### 3.2 The float32 evaluation

The fitted float32 form (`arith.cpp Hue`, `HueWeights`, `ComponentBlend` and the HLSL) has two parts.

**Hue.** h6 = fma(X - 3e, rcp(d + e), C) with the hardware reciprocal; h = h6 float32(1/6), plus 1 when negative. The weights use f = h - floor(h):

- red: |fma(f, 6, -3)| - 1;
- green: 2 - |fma(f, 6, -2)|;
- blue: 2 - |fma(f, 6, -4)|;
- each clamped to [0, 1].

**Reconstruction.** v = 2 max of the value source, lo = v (1 - s), and each component is fma(v - lo, w, lo).

These parts were identified on the extreme components, where the weight is exactly 0 or 1.

- The smallest component equals v fma(-d, rcp(max + e), 1) on every interior texel of Tint, Value and Color (58 096 in Tint). Saturation alone keeps 1 - s with two roundings; the fused form leaves 2 476 off there.
- The largest component is off by one ulp on 1 010 texels under v (1 + (w - 1) s). It is exact under the lerp fma(v - lo, w, lo) at w = 1, apart from 68 boundary texels, which are ties in B.
- For the middle component's weight, every hue evaluation tried leaves about 0.5-1 % of the RGB32F values off by one ulp. That covers the hexcone, Taylor-style and centred forms, with and without fused multiply-adds, and h or h6 as the carried value.
  - In the sector B > G > R, 11 % of the texels admit no float32 hue in [0.5, 2/3) at all. Their weight is finer than 6 h can be.
  - So Painter does not carry a [0, 1) hue through the usual hexcone weights there.
- Natural GLSL candidates run through the GPU's OpenGL compiler did not do better than the numpy fits. Those were the min-based law with Hocevar's, Taylor's and the lerp reconstruction.

| Values differing / max (r1; r2 identical) | Tint | Saturation | Color | Value |
|---|---|---|---|---|
| RGB16 at 1 (phase1.10 → now) | 32 634 → 71 / 1 | 53 100 → 194 / 1 | 46 657 → 187 / 1 | 23 312 → 160 / 1 |
| RGB16 at 0.5 | 32 454 → 33 / 1 | 53 122 → 108 / 1 | 46 624 → 61 / 1 | 23 261 → 83 / 1 |
| sRGB8 at 1 and 0.5 | 5 152, 3 333 → 0 | 19 121, 10 825 → 0 | 9 165, 5 489 → 0 | 6 581, 4 522 → 0 |
| RGB8 | 7 158 → 1 / 257 (one 8-bit code) | 20 574 → 0 | 11 343 → 0 | 6 192 → 0 |
| RGB16F | 52 147 → 5 / 1 half ulp | 78 389 → 40 | 65 526 → 16 | 77 574 → 83 |
| L16 (grey) | 0 | 0 | 0 | 0 |
| RGB32F at 0.25 | 70 939 → 8 228 / 1.2e-7 | 84 560 → 20 122 | 72 083 → 15 090 | 89 777 → 19 822 |

The four modes stay `release-gap` (status `calibrated` in `blend-kernels.json`). No exception is proposed.

### 3.3 Recording request: `blend-component-hue` (owner, or the agent that owns Painter)

`blend-component` is a coarse probe of the hue arithmetic:

- Its hue sources are two smooth fields with a chroma d of at least 64 codes on every texel but one.
- Its opacity-0.25 RGB32F map resolves r only to about 2^-22.

The middle weight must be read at full float32 precision, over every sector, tie and near-grey case.

The recording follows the Tier 0 rules of every blend sweep: `uzpainter parity record`, two recordings (the same session, then after save and reopen), PNG 16 / OpenEXR float, padding infinite, no dithering.

**Setup.**

- Mesh `grid4x2`, resolution 256, normal map format OpenGL.
- User channels:

| Channel | Format | Opacity |
|---|---|---|
| User0 | RGB32F | 1 |
| User1 | RGB16F | 1 |
| User2 | RGB16 | 1 |
| User3 | sRGB8 | 1 |
| User4 | RGB32F | 0.5 |
| User5 | RGB16 | 0.5 |
| User6 | L16 | 1 |
| User7 | RGB32F | 0.25 |

- New authored fixture `hue-grid` (256 × 256 RGB16):
  - Row group r (16 rows each) takes a grey level L_r = (r + 1)/17.
  - Within a group, the column index codes a sector (6), a chroma d from {1, 2, 3, 4, 8, 16, 32, 64, 128, 256, 1 024, 4 096} codes, and a middle position from {0, 1, d/4, d/2, 3d/4, d - 1, d} codes.
  - The remaining columns hold the 13 tie and grey cases: R = G, G = B, R = B, each as maximum and as minimum, and pure grey, at every level.
  - This covers d from 1 code up, every rising and falling sector, both tie orders, and middle weights at 0, 1 and ½.

**Texture sets.**

| Set | Mode | Lower fill | Upper fill |
|---|---|---|---|
| s0 | Tint | uniform colour (0.5, 0, 0): s = 1 - e/(0.5 + e), 2v = 1, so the output is the hue weights at amplitude 1 | `hue-grid` |
| s1 | Color | the same | `hue-grid` (hue and saturation of the grid) |
| s2 | Saturation | `hue-grid` | uniform colour (0.5, 0, 0) (its saturation applied to the grid's hue and value) |
| s3 | Value | `hue-grid` | uniform grey 0.25 (2v = 0.5) |
| s4 | Tint | `hue-grid` | `hue-grid` transposed (both sources near grey) |

**Held out.** `blend-component` s0-s3 stay the held-out validation.

**Then:** fit the hue on s0 User0 (the weights read directly), validate on s1-s4 and on `blend-component`, and implement on the CPU and the GPU (items 2.1, 2.4, 3.1).

## 4. PassThrough (item 2.3, decision 047)

Painter 12.1.0's runtime has no `BlendingMode.PassThrough` member, so the documented API cannot set the mode and no golden exists. The mode is reachable through the UI.

**Decision 047:**

- PassThrough is not `not_migratable`. It stays `release-gap`, and the hypothesis implementation stays: children composite into the enclosing list, with opacities scaled by the group's.
- The golden is recorded by `phase0.7_tier0-semantics-ui-cases` item 2.4 through UI automation (decision 029). That item was already scoped there.
- The fit stays in this task: item 2.3 is open until then.
- Any gate whose content uses a PassThrough group lists item 2.3 as a prerequisite.
- Assets checked: no stack in Assets3D `Pipeline/` uses a PassThrough group or a `blend` key (Wand v1, Belt v5 `waist-v5/stack-belt.json` and `stack-sash.json`, hat, staff). Tunic v10 has no stack file there yet.

**Recording specification for phase0.7 ui-cases item 2.4.**

- Mesh `grid4x2`, resolution 256.
- Channels: BaseColor sRGB8, Roughness L8, User0 RGB16, User1 RGB32F.
- Fixtures: field A and field B, as `blend-basic`.
- Two recordings, with the group mode set through the UI and recorded in the settings sheet with panel evidence.

| Set | Stack (bottom → top) | Purpose |
|---|---|---|
| s0 | fill A (backdrop); group G in **Normal**, opacity 0.5, containing fill B in Multiply at opacity 1 | control: the isolated group |
| s1 | the same with G in **PassThrough** | pass-through against isolation: Multiply sees the backdrop only when the group passes through |
| s2 | the same with G in PassThrough at opacity 1 | the group's opacity alone |
| s3 | G in PassThrough at opacity 0.5 with two children: fill B in Multiply at 0.7, then fill A transposed in Screen at 0.6 | per-child opacity scaling against one group-level mix |
| s4 | s1 with a group mask (`mask-codes` bitmap) | mask on the group |
| s5 | s1 with a mask on the child | mask on the child |
| s6 | s1 with both masks | mask composition |
| s7 | G in PassThrough inside a Normal group at 0.8 | nesting |

The `group-masks` golden's stack stays the reference for the mask rules.

## 5. Normal-map recordings that would widen the evidence (optional)

The fit holds at the recorded opacities 0.5 and 0.25. The panel asked for off-grid evidence, and the flat normal is not covered.

- Add to `blend-component`, or a sibling golden `blend-normal-opacity`, the normal-map sets s4-s6 at opacities 0.1, 1/3, 0.7 and 0.99, on RGB32F and RGB16.
- Add a lower and an upper uniform normal of exactly (0, 0, 1) on an RGB32F channel (colour (0.5, 0.5, 1.0)), at opacity 0.5. Today the evaluator keeps a flat normal, because the formula would give `0 · rsqrt(0)`.

## 6. Unit tests and kernels

| Case | Result |
|---|---|
| `arith` (CPU) | passed; includes `hw::Asin` against 48 measured GLSL inputs and the 2^23-entry trigonometric index |
| `trig-hardware` (DX12) | the embedded sin and cos tables equal the GPU on all 8 388 608 entries; every measured input lies at its own index; `hw::Sin` and `hw::Cos` equal the GPU on 8 edge values and 1 048 568 hashed inputs of [0, pi/2] |
| `kernel-sweep` (DX12) | every mode × 9 channel formats × coverage on and off × opacity 1 and 0.7: GPU = CPU on 149 422 080 samples (1 080 combinations) |
| `gpu-vs-cpu` (DX12) | random stacks over every mode and format: identical bytes (2 490 368 samples) |
| `blend-component`, `blend-normal-channel` against r1 and r2 | as in §2 and §3, identical on the CPU and the GPU |

## 7. Open items and owner actions

- **Item 2.1 (component modes):** one-code residuals remain; the recording of §3.3 is needed. Release gap; no exception proposed.
- **Item 2.3 (PassThrough):** waits for `phase0.7_tier0-semantics-ui-cases` item 2.4 (UI recording, decision 029). Release gap.
- **Items 3.1 and 4.1:** stay open with them. Item 3.2 (normal maps) and item 3.3 (GPU = CPU) are met.
- **Owner:** push, and record or delegate the two recordings (§3.3; §4 through phase0.7). §5 is optional.

## Reproduce

```
zig build evaluator-tests
python -m pytest tests/evaluator/test_compositor_blend_kernels.py tests/evaluator/test_compositor_blend_gaps.py
python tests/evaluator/blend_fits.py zig-out/bin/uzp-evaluator-tests.exe <work-dir>
zig-out/bin/uzp-evaluator-tests.exe trig-hardware assets/templates <work-dir>
```
