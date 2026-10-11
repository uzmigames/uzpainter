# `phase1.10_compositor-float32-residual`: search report and local run on the owner's machine

Child of `phase1.14_compositor-core` (P1-COMPOSITOR; `docs/architecture/04-layer-stack-and-compositing.md` §4). Under decision 028 the Tier 0 comparisons against the private oracle store and the GPU checks run locally on the owner's machine; this report is their evidence. Numbers only: every recorded Painter output stays in the private store. Second round run on 2026-10-11 on the tree of commit `d086d44` with this task's changes (`src/evaluator/`, `src/store/census.cpp`, `tests/evaluator/`, `parity/semantics/quantisation-profile.json`, `parity/semantics/masks-levels.json`).

**Result.** The float32 operation order of Painter's source-over onto a partly covered backdrop is identified on the diagnostic golden `group-coverage-order` (decision 048) and ships as the new profile `painter-12.1-isolated-coverage-weights` (decisions 058, 059): the weight of the source alone is re-derived from the rounded coverage, `ws = ao - ab`. With it, a fused read-out over the base, the grey of a uniform colour taken from its unrounded components and the sRGB8 coverage passing through binary16 only from 1/2 up, every map of `quantisation-thirds` (r1), `blend-inputs` s2, `group-masks` s2-s3 and `group-coverage-order` s0-s3 equals the recordings, on the CPU and on the GPU (DX12). No other published fit moves. The residual is no longer a divergence. The first round (decision 044) found the binary16 sRGB8 coverage and the plain 32-bit float uniform colour (profile `painter-12.1-isolated-half-alpha`); both earlier isolated profiles stay registered and evaluate bit for bit as before.

## Run record

| Item | Value |
|---|---|
| Hardware | NVIDIA GeForce RTX 4090, Windows 11 Pro 10.0.26200 |
| Backend | DX12, kernels `cs_6_6` through the render layer's kernel cache |
| Build | Zig 0.15.2; `zig build evaluator-tests` exit 0, no warning (`-Werror`) |
| Oracle | `C:\Users\Bolado\AppData\Local\UzPainter\parity-store`; `quantisation-thirds` and `blend-inputs` from the 12.1.0 manifests as published, `group-masks` and `group-coverage-order` through the current envelope `painter-12.1.5+js-api.1.1.20` |

## The diagnostic golden

`group-coverage-order` (recorded on main, commit `09a5bbb`; r1 = r2 on all 24 maps): per texture set a root fill of 0 at opacity 1, above it an isolated group (Normal, 1, no mask) holding a child fill under a mask whose value is the row ramp m = y/255 and a fill of fields A above it; s0 child 0 and the top fill Normal 0.5, s1 child fields B, s2 as s1 with the top in Screen, s3 as s1 with the top at 0.3; channels RGB32F, L32F, RGB16, sRGB8, RGB8, L8 (the L channels take grey A and grey B, decision 048). Over the opaque black root the export is `R(fl(g ag))`, g the group's float32 colour, ag its stored coverage and `R(v) = fl(fl(v - 1) + 1)` the read-out.

### 1. Rows whose coverage sum is exact were already right

In s0 (child colour 0) the W3C order gives `g = fl(fl(S as) Rcp_hw(ao))`, `ao = fl(0.5 + 0.5 m)`. It reproduces all 768 values of every row whose coverage sum is exact or nearly so in float32 (rounding error e of `0.5 + 0.5 m` at most 1/8 ulp: rows y even < 64 and y odd > 128) and of no other row (e = ±1/4 to ±1/2). A correctly rounded division fails the exact rows (the GPU reciprocal is evidenced). On the other rows no float reciprocal r makes `g = fl(S/2 r)` consistent with every texel, even with any real final multiplier, and no affine single rounding `fl(alpha S + beta)` fits (LP infeasible): the result holds a second S-dependent rounding that vanishes when the coverage sum is exact, biased in the direction of e.

### 2. The order

Over a backdrop of colour Cb and coverage ab < 1, with source colour Cs, layer alpha as and blend result B:

    wb = fl(ab fl(1 - as)),  ao = fl(as + wb),  ws = fl(ao - ab)
    C  = fl( fma(ws, Cs, fma(ab, fl(as B), fl(wb Cb))) x Rcp_hw(ao) ),  coverage ao

It reproduces every RGB32F, L32F and RGB16 map of the four sets. With ab = 1 it is exactly the fitted opacity mix `fl(fl(Cb (1 - as)) + fl(B as))` (the fitted opaque mixes stay). Rejected on the same data: every other association of the three terms (six forms, three orders each; the nearest leaves 10 734 values of s3), the W3C weight `as (1 - ab)` in place of `ao - ab` (22 989 values of s0), other derivations of wb, ao and `as ab`, the correctly rounded reciprocal (4 148 to 8 598 values per set), and the 'opaque mix times ab' form `fma(ws, Cs, fl(ab fl(fl(Cb (1 - as)) + fl(B as))))` (19 320 values of s1).

- **Zero coverage.** On row 0 of s3 (m = 0) the result is `fl(fl(S as) Rcp_hw(as))`, not S: the formula applies over a backdrop layer of coverage 0. The masked child, the first layer of the group, is copied: composited over the empty start it would leave 6 467 values of s1 off.
- **RGB8 and L8 coverage.** The even rows of s0-s2 put the group coverage on an 8-bit tie; the RGB8 and L8 maps are exact with the plain 8-bit rule (ties down). Settled; no profile change.
- **sRGB8 coverage below 1/2.** In s3 eight coverages in [0.3, 0.5) lie on 8-bit ties (rows 0, 10, ..., 70); the sRGB8 map stores all eight down, while binary16 sends five up (1 863 values off). Binary16 only from 1/2 up makes all 24 maps exact and keeps `group-masks` exact; binary16 toward zero, fixed-point rounding to 2^-11, `1 - binary16(1 - a)`, binary16 of `255 a` or of `2a - 1` and half-precision code arithmetic each fail one side. The mechanism is not identified (decision 059).

### 3. Confirmation on the earlier goldens

- `group-masks` s2-s3: every map exact on both recordings (was 20 631 RGB32F and 57 RGB16 values).
- `quantisation-thirds`: with the order, the RGB32F maps are exact only if the read-out over the base is one fused operation, `fma(C - base, a, base)` (the two-rounding read-out leaves 3 of 12 values off); the L32F map is exact only if a uniform colour on a grey channel is `float32((r + g + b) / 3)` of the API's double components (the mean of their float32 values leaves s2 off). Every UNORM, sRGB8 and 16-bit float map is exact either way; these two rules rest on three and one deciding values and are recorded as measured (decision 058).
- Hardware: the order uses the reciprocal table measured on D3D12; the first round showed `a / b` in a Vulkan compute shader (Painter 12.1.5 renders through Vulkan, decision 056) equals `a * RCP(b)` with the same table on every mantissa tested, and on this golden the correctly rounded reciprocal fails. The fused multiply-adds and the binary16 step are fitted from the recordings and emulated exactly on both backends; they do not depend on the evaluating GPU.
- The first round's "cleanest sub-case" of `group-masks` (result 0.45 / coverage, four rows where no `0.45 Rcp(x)` lands) is explained: the numerator weight `ws = ao - ab` carries the coverage's rounding error.

## Tier 0 comparisons (current profile `painter-12.1-isolated-coverage-weights`; CPU and GPU identical)

| Golden | Maps | vs r1 | vs r2 |
|---|---|---|---|
| `quantisation-thirds` s0-s3 | all 9 formats, RGB32F and L32F included | exact (was 5 of 16 float values off) | within `EXC-001` (unchanged) |
| `blend-inputs` s2 | RGB16 x2, sRGB8 x2, RGB8, RGB16F, L16, RGB32F | exact | as before (`EXC-002`) |
| `group-masks` s0-s3 | RGB16, sRGB8, RGB32F | exact (was 57 RGB16 and 20 631 RGB32F values off in s2-s3) | exact |
| `group-coverage-order` s0-s3 | RGB32F, L32F, RGB16, sRGB8, RGB8, L8 | exact | exact |
| `coverage-srgb8-ties` s0-s7 (confirmation, 2026-10-11) | sRGB8 x9, RGB32F | exact | exact |
| `mask-precision`, `levels-clamp`, `effect-order` s6, blend sweeps, sources, UV sampling | all | unchanged (`blend-kernels.json` residuals identical; `colour-transfer.json`, `uv-sampling.json` byte-identical; `masks-levels.json` changed only by `group-masks` and the new entry) | unchanged |

`parity/semantics/quantisation-profile.json` gains the selected entry `quantisation-isolated-coverage-weights` (exact against r1; r2 within the register entries); `quantisation-isolated-half-alpha`, `quantisation-isolated-root` and `quantisation-over-base` keep their residuals. `parity/semantics/masks-levels.json`: `group-masks` exact, new entry `group-coverage-order` (48 residuals, all 0).

## Profile and pinning

| Check | Evidence |
|---|---|
| Registry | `profile.h`: `layerq-linear`, `isolated-linear`, `isolated-half-alpha`, `isolated-coverage-weights` (current; flags `coverageWeights`, `fusedReadout`, `uniformGreyUnrounded`, `srgb8HalfCoverageFromHalf` on top of `srgb8HalfCoverage`, `float32UniformPlain`); `src/store/census.cpp` stamps the current id |
| Pinning | `uzp-evaluator-tests profile`: projects stamped `layerq-linear`, `isolated-linear` and `isolated-half-alpha` evaluate per their models and, after a synthetic profile is registered, bit for bit as before on the same and a fresh evaluator, served from their own tiles; a project stamped `isolated-coverage-weights` evaluates per its model; `isolated-half-alpha` and `isolated-coverage-weights` differ on the three 1/3 fills in 32-bit float and on an sRGB8 coverage tie below 1/2 (a 0.3 fill over a fill at opacity 0) |
| Arithmetic | `uzp-evaluator-tests arith`: the weighted composite equals its formula over a partly covered backdrop, gives `fl(fl(Cs as) Rcp_hw(as)) != Cs` over a backdrop of coverage 0, copies over the empty start; the fused read-out is `fma(C - base, a, base)` |
| GPU = CPU | the kernel mirrors `arith::Composite` operation for operation (`FLAG_COVERAGE_WEIGHTS`, `FLAG_EMPTY_BACKDROP`, `FLAG_FUSED_READOUT`, `UZP_HALF_COVERAGE=2`); `gpu-vs-cpu` and `masks-gpu-vs-cpu` (2 490 368 samples each, random stacks with partial coverage on all nine formats, current profile) identical; `group-coverage-order` evaluated on both backends: identical bytes |

## Quality gate

| Step | Command | Result |
|---|---|---|
| Type-check | `python -m mypy` | no issues (235 files after merging main) |
| Lint | `python -m ruff check .`, `python -m ruff format --check` (touched files) | clean |
| Build | `zig build evaluator-tests` | exit 0, no warning |
| Unit cases | `arith`, `order`, `profile`, `templates`, `cache`, `admission`, `sources`, `masks` (CPU); `gpu-vs-cpu`, `masks-gpu-vs-cpu` (DX12) | all passed |
| Tests | `python -m pytest tests/evaluator`, `python -m pytest tests/parity` | 273 passed before and after merging main (store and DX12 adapter present, nothing skipped); parity 830 passed, 1 failure outside this task (`iray.json` entry `display-encoding` without residuals, main commit `592da3f`) |

## Open items

- **The sRGB8 coverage rule below 1/2 is confirmed.** The rule was first measured on eight tie rows of one golden. Decision 067 recorded `coverage-srgb8-ties`: the `group-coverage-order` s1 stack, with the top opacity of set i and channel j < 8 at (2k + 1)/510, k = 64 + 8i + j.
  - Row 0 therefore puts the group coverage on the 8-bit tie (k + 1/2)/255: 63 ties in [0.25, 0.5) and the boundary 1/2.
  - User8 adds eight opacities with several tied rows (0.3, the earlier golden's, among them). User9 is an RGB32F control.
  - Under the current profile `painter-12.1-isolated-coverage-weights`, all 80 maps equal both recordings, on the CPU and on the GPU (`test_compositor_mask_effects.py::test_coverage_srgb8_ties_equal_the_golden`).
  - On 31 of the 63 ties below 1/2, binary16 to nearest would store the code above the plain rule. The recording takes the plain rule on all of them, so the rule of decision 059 holds and the profile is unchanged.
  - The mechanism is still not identified (why binary16 shows only from 1/2 up). Below 1/2, binary16 toward zero and the plain 8-bit rule are identical (both keep 12 fractional bits), so this golden cannot separate them.
- The fused read-out and the unrounded grey mean are each decided by few values (3 of 12 RGB32F values, 1 of 4 L32F values of `quantisation-thirds`); further 32-bit float goldens over the base would confirm them.
