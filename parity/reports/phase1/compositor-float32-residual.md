# `phase1.10_compositor-float32-residual`: search report and local run on the owner's machine

Child of `phase1.14_compositor-core` (P1-COMPOSITOR; `docs/architecture/04-layer-stack-and-compositing.md` §4). Under decision 028 the Tier 0 comparisons against the private oracle store and the GPU checks run locally on the owner's machine; this report is their evidence. Numbers only: every recorded Painter output stays in the private store. Run on 2026-10-11 on the tree of commit `58dd65f` with this task's changes (`src/evaluator/`, `src/store/census.cpp`, `tests/evaluator/`, `parity/semantics/quantisation-profile.json`, `parity/semantics/masks-levels.json`).

**Result.** Two of the three causes of the partial-coverage residual are found and ship as the new profile `painter-12.1-isolated-half-alpha` (decision 044): the coverage plane of an sRGB8 intermediate is written through binary16, and a uniform colour on a 32-bit float channel is its float32 value. With them `group-masks` s2-s3 sRGB8 is exact (3 709 values before) and one more float value of `quantisation-thirds` is exact. The float32 operation order of Painter's source-over onto a partly covered backdrop is **not** identified: `quantisation-thirds` keeps 5 of its 16 RGB32F/L32F values 2^-25 or 2^-24 from r1, `group-masks` s2-s3 keeps 20 631 RGB32F and 57 RGB16 values one export step off. The residual stays published as a divergence; the exception is the owner's decision (question q1 of the task). A diagnostic recording is specified below. `painter-12.1-isolated-linear` stays registered and evaluates bit for bit as before.

## Run record

| Item | Value |
|---|---|
| Hardware | NVIDIA GeForce RTX 4090, Windows 11 Pro 10.0.26200 |
| Backend | DX12, kernels `cs_6_6` through the render layer's kernel cache; a scratch Vulkan compute probe (SPIR-V from DXC) for the division measurement |
| Build | Zig 0.15.2; `zig build evaluator-tests`, `zig build painter`, `zig build uzp-store-inspect-tests` exit 0, no warning (`-Werror`) |
| Oracle | `C:\Users\Bolado\AppData\Local\UzPainter\parity-store`; goldens through `tools.parity.fit` (`quantisation-thirds`, `blend-inputs` from the 12.1.0 manifests as published; `group-masks` and the mask goldens through the current envelope `painter-12.1.5+js-api.1.1.20`) |

## What was found

### 1. sRGB8 coverage goes through binary16

Every sRGB8 difference of `group-masks` s2 (3 709 values, one code each, both directions) lies on an even row y >= 32, where the group coverage (255 + y)/510 is exactly half-way between two 8-bit codes; odd rows are exact. Scanning the stored coverage per row: on rows y mod 64 < 32 only the lower code makes all 256 texels exact, on rows y mod 64 >= 32 only the upper code does; a float coverage, a 16-bit coverage, the binary16 value itself or any intermediate value fail on every even row. The float32 coverage lies below the tie on every even row, so the direction is not the float32 noise of the coverage arithmetic. The rule `WriteUnorm(binary16_nearest_even(a), 8)` (the measured 8-bit write rule applied to the binary16 value) gives the required code on all 254 rows; binary16 toward zero fails 64 rows, `rint(255 h)` 151 values. The binary16 grid (2^-11 on [0.5, 1)) drifts against the 8-bit grid by 0.03 code per code, which flips the side of the tie every 16 codes: the y mod 64 pattern. The measured sRGB8 colour thresholds (`colour-transfer.json`) have at most 11 significant bits, consistent with the GPU passing sRGB8 render-target outputs through binary16; the RGB8 colour rule was fitted exactly without binary16 (binary16 would move 2.6 % of random values), so the rule is applied to sRGB8 intermediates only. Painter's log shows its renderer is Vulkan (the VMA allocator).

### 2. A 32-bit float uniform colour is its float32 value

On `group-masks` row 0 (the child's mask is 0) the group colour is the Screen fill's colour itself: `float32(v)` reproduces all texels of both recordings, the inherited `1 + (v - 1)` leaves 8 values off. No golden supports `1 + (v - 1)` (it came from the superseded over-base model); `quantisation-thirds` and `group-masks` are the only goldens with a non-trivial uniform colour on a 32-bit float channel.

### 3. The float32 source-over onto a partly covered backdrop: not identified

Pinned facts:

- The group composite of `group-masks` (`v = A (1 - al) + g al`, `al = (0.75 mA) ag`, then `1 + (v - 1)`) is exact: for the red component the child colour equals the child mask, so the group colour g is one float per row; every row has exactly one float g that reproduces all 255 texels of the row, and shifting the stored coverage ag by one ulp, or any other product order, fma form, lerp form or premultiplied form of the composite, leaves no row feasible. This gives 254 exact float32 values of Painter's inner result and pins ag = float32(0.5 + 0.5 m).
- Division on the recording GPU: `a / b` in a D3D12 and in a Vulkan compute shader equals `a * RCP(b)` with the measured reciprocal table (`hwmath.h`) on all 2^23 mantissas of b in [0.5, 1) (a = 0.45).
- Painter's inner value lies within -1.9 .. +1.8 ulp of the exact W3C §5.1 value computed from its float32 inputs, so the algebra is W3C's and only the float32 order is unknown.
- Cleanest sub-case: green at x = 255 (child colour 0, Screen(0, S) = S exactly), where the result is 0.45 / ag mathematically. On rows 1, 13, 21 and 37 Painter's value lies where no `0.45 * RCP(x)` lands for any x near ag; on odd rows (ag rounded up from its exact value) Painter's values are biased up in every component.

Searched and rejected (counts are wrong rows of the 254 red rows, or differing values of the 196 608 RGB32F / RGB16 values of s2): every left-deep and bushy fma/unfused evaluation order of the three-term W3C numerator and of the two-level form (Cs' first: five forms), times correctly rounded division, `x * RCP_correct`, `x * RCP_hw` and a Newton-refined quotient (best 46 rows); six coverage forms for the divisor; lerp forms with `t = as / ao` and `u = (1 - as) ab / ao` (best 103 rows); premultiplied Screen `cs + cb - cs cb`; premultiplied storage with unpremultiplied backdrop for the kernel; a single "general" formula for every composite; a lerp between the opaque and transparent results; quantised or binary16 opacities; directed-rounding reciprocals; the exact unrounded coverage; distributed normalisation (weights before summation); enumerative synthesis of every expression up to 9 operations over the inputs of the sub-case (best 30 of 254 rows). The best model, an fma chain of the three premultiplied terms divided through the hardware reciprocal, leaves 12 071 RGB32F and 36 RGB16 values; with a free reciprocal per row it still explains only 94 of 254 rows in all three components. It is not adopted (decision 044).

## Tier 0 comparisons (current profile `painter-12.1-isolated-half-alpha`; CPU and GPU identical)

| Golden | Maps | vs r1 | vs r2 |
|---|---|---|---|
| `quantisation-thirds` s0-s3 | sRGB8, RGB8, RGB16, RGB16F, L8, L16, L16F | exact | within `EXC-001` (unchanged) |
| `quantisation-thirds` s0-s3 | RGB32F (User4), L32F (Scattering) | 5 of 16 values off (s0 B, s1 R, s3 R, L32F s0 and s3; 2^-25 or 2^-24): divergence | within `EXC-001` bounds |
| `blend-inputs` s2 | RGB16 ×2, sRGB8 ×2, RGB8, RGB16F, L16, RGB32F | exact | as before (`EXC-002`) |
| `group-masks` s0, s1 | RGB16, sRGB8, RGB32F | exact | exact |
| `group-masks` s2, s3 | sRGB8 | exact (was 3 709 values) | exact |
| `group-masks` s2, s3 | RGB16 / RGB32F | 57 / 20 631 values off by one step (was 57 / 21 469): divergence | same |
| `mask-precision`, `levels-clamp`, `effect-order` s6, blend sweeps, sources | all | unchanged (the published fits re-derive byte for byte) | unchanged |

`parity/semantics/quantisation-profile.json` gains the entry `quantisation-isolated-half-alpha` (selected); `quantisation-isolated-root` and `quantisation-over-base` keep their residuals. `parity/semantics/masks-levels.json` entry `group-masks` carries the new residuals.

## Profile and pinning

| Check | Evidence |
|---|---|
| 2.2 / 3.3 registry | `profile.h`: `painter-12.1-layerq-linear`, `painter-12.1-isolated-linear`, `painter-12.1-isolated-half-alpha` (current; flags `srgb8HalfCoverage`, `float32UniformPlain`); `src/store/census.cpp` stamps the current id |
| 3.3 pinning | `uzp-evaluator-tests profile`: projects stamped `layerq-linear` and `isolated-linear` evaluate per their models and, after a synthetic profile is registered, bit for bit as before on the same and a fresh evaluator, served from their own tiles; a project stamped `isolated-half-alpha` evaluates per its model; the two isolated profiles differ on an sRGB8 coverage tie (a 0.5 fill over a 32/255 fill) and on 32-bit float uniform colours |
| 3.2 GPU = CPU | `gpu-vs-cpu` (random stacks on all nine formats, isolated root and groups with partial coverage, current profile: 2 490 368 samples), `kernel-sweep` (149 422 080 samples, 1 080 combinations), `masks-gpu-vs-cpu`, `projection-gpu-vs-cpu`: identical |
| binary16 rounding | `arith`: `arith::HalfNearestEven` equals a double-precision reference on every half, every midpoint between neighbours and the floats beside it, overflow from 65520 and the subnormal range; the HLSL twin (`evaluator_blend.hlsl` `HalfNearestEven`) is integer-only |

## Recording request (owner: one Painter session)

A diagnostic golden for the open order and the RGB8/L8 coverage rule, built with the existing fixtures (`grid2x2`, `field-a`, `field-b`, `grey-b`), channels User0 RGB32F, User1 L32F, User2 RGB16, User3 sRGB8, User4 RGB8, User5 L8 (EXR 32f for float, PNG 16 otherwise, both recordings r1 and r2):

- every texture set: a root fill with uniform colour (0, 0, 0) at opacity 1, above it a group (Normal, opacity 1, no mask) holding a child fill under a mask (Black background, mask fill effect with `grey-b`, the row ramp m = y/255) and a top fill;
- s0: child uniform (0, 0, 0) Normal 1; top fill bitmap `field-a` Normal 0.5 (backdrop colour 0: the result is `round(round(S as / ao) ao)`, the division isolated per texel);
- s1: child `field-b` Normal 1; top fill bitmap `field-a` Normal 0.5 (numerator with a backdrop colour);
- s2: as s1 with the top fill in Screen;
- s3: as s1 with the top opacity 0.3 (products with a non-dyadic opacity).

Over a black root the export is `g · ag` written once, lossless on the 2^-24 grid where it lies in [0.5, 1); the even rows put the group coverage on an 8-bit tie for RGB8 and L8. The panel's caution applies: one recording narrows the order (numerator against division) but may not settle it alone.

## Quality gate

| Step | Command | Result |
|---|---|---|
| Type-check | `python -m mypy` | no issues (210 files, after merging main `c3708d3`) |
| Lint | `python -m ruff check .`, `python -m ruff format --check` (touched files) | clean |
| Build | `zig build evaluator-tests`, `zig build painter`, `zig build uzp-store-inspect-tests` | exit 0, no warning |
| Unit cases | `arith`, `templates`, `order`, `cache`, `admission`, `sources`, `profile`, `masks` (CPU); `gpu-vs-cpu`, `kernel-sweep`, `masks-gpu-vs-cpu`, `projection-gpu-vs-cpu` (DX12) | all passed |
| Tests | `python -m pytest tests/evaluator`, `python -m pytest tests/parity` | 265 passed on the branch merged with main (264 before the merge), with the store and the DX12 adapter, nothing skipped; 696 passed (parity) |
| Guard | `python -m tools.parity.guard` | 0 blocked |

## Open items

- The float32 order of the partly covered source-over (RGB32F, L32F, RGB16): a divergence; owner question q1 (exception or diagnostic recording); recording request above.
- RGB8/L8 coverage at an 8-bit tie: plain 8-bit write kept, unobserved (the same recording settles it).
