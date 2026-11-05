# 402. Painter's 16x Height magnification at 4096 px is the evaluator's 8-bit-weight filter; the recorded scope is admitted

**Status**: accepted
**Date**: 2026-11-05
**Related Tasks**: phase3.1_height-magnification-fit, phase1.12_compositor-height-normal

## Context

Decision 400 §2 found 48,126 of the 16,777,216 s0 Height texels of `tier0/semantics/height-normal-resolution-4096` (the 256 px 16-bit height ramps magnified 16 times by the default projection onto a 4096 px set) off under "the magnification exact at 512, 1024 and 2048 px", and refused every bilinear Height magnification on a set above 2048 texels (`CheckSampling`, `src/evaluator/projection_uv.cpp`), owner `phase3.1_height-magnification-fit`. That measurement used the Python model `tools/parity/fit/normal.py` `magnified`, which applied the exact dyadic bilinear weights and rounded once to float32; its docstring said the evaluator's integer filter gives the same values, which holds at 2x to 8x only.

## Measurements

Fitted offline on the admitted golden (r1 and r2, every texel), private store, no new recording.

1. **The residual is the corner weight's rounding.** No off texel lies where the bitmap varies along one axis only: all 48,126 sit in cells where both axes vary, so the bilinear cross term carries the error. At 16x the sub-texel fractions are k/32 and the exact corner weight fx fy is a multiple of 1/1024; at 2x to 8x it is a multiple of 1/256.
2. **Candidates, s0 Height texels off (r1):** exact weights 48,126; w11 rounded to 1/256 and the other three derived (w10 = fx - w11, w01 = fy - w11, w00 = 1 - fx - fy + w11) **0**; all four weights rounded to 1/256 **0** (identical here: no tie, fx fy / 256 is an odd number of quarters); w11 floored or ceiled to 1/256, rest derived, 62,118 and 62,060; all four floored or ceiled about 16.7 M; 1/512 rounding with ties to even 0 (it rounds the same way here), ties up or down about 16.7 M; 1/1024 (exact) 48,126. Summing the four products in float32 instead of one rounding: 643 (pairwise) and 1,286 (sequential).
3. **The evaluator already does this.** `ProjectTexel` and the GPU kernel (`shaders/evaluator_project.hlsl`) compute X = floor(256 x + 1/2), fx = X & 255, w11 = (fx fy + 127) >> 8 and `BilinearFilter` (operands truncated to 28 bits below the largest texel's exponent, the sum rounded to float32 ties away from zero). Emulated in numpy on s0 it gives 0 texels off, r1 and r2. Decision 400 §2's "the evaluator's filter is not exact" was the Python model's error, not the evaluator's or a set-size effect.
4. **Every map exact.** With `magnified` mirroring the evaluator (`bilinear_filter`, `resample.bilinear_weights`), the fit's model gives Height, Normal_OpenGL, Normal_DirectX and the Normal channel of s0 to s3 equal to r1 on every texel, and r2 on every map where r2 equals r1. r2 of the virtual maps of s1 and s2 differs from r1 (decision 400): the model is 24, 24, 42 and 41 values off r2 there, one code each, not compared (decision 032; no exception covers them and none is asked). The 512, 1024, 1024-sobel and 2048 goldens stay exact under the new `magnified`.

## Decision

1. **The model:** `magnified` in `tools/parity/fit/normal.py` follows the evaluator operation for operation (8-bit fixed-point texel centres, the integer weights with w11 = (fx fy + 127) >> 8, `bilinear_filter` = `BilinearFilter`). The published fit `parity/semantics/height-to-normal.json` gains the entry `height-magnification-4096` and the golden in its corpus. No native arithmetic changes: the CPU reference and the GPU kernel already implement it.
2. **Admitted** on a set above 2048 texels, the recorded scope only: a bilinear Height magnification with BilinearHQ, Repeat, the identity projection (scale (1, 1), rotation 0, offset (0, 0)), a square 256 px bitmap (16x) on a square 4096 x 4096 set. The bitmap's bit depth is not restricted to 16: the 8-bit 16x Height magnification of P20-A (decisions 218, 224) enters the same filter.
3. **Still refused** (`evaluator:unsupported_source`, naming decision 400 and the owner `phase3.1_height-magnification-fit`): every other bilinear Height magnification on a set above 2048 texels — other factors at 4096 (2x, 4x, 8x, 32x), scaled, offset or rotated projections, BilinearSharp, the other wrap modes, non-square bitmaps or sets, and sets above 4096. The refusal stays by set size because these are not recorded there, even where the arithmetic argument (no w11 rounding at 2x to 8x) predicts them exact; decision 001 admits what a recording shows exact.
4. **Recordings that would widen the scope** (requests, not made here): the same sequence at 4096 with the ramps at 512, 1024 and 2048 px (8x, 4x, 2x) and at 128 px (32x, fractions k/64 with w11 ties); one set with a UV scale of 2 and an offset of (0.3, 0.1) on the 256 px ramps (non-dyadic fractions and ties at 4096); one set with BilinearSharp.

## Results (2026-11-05)

Model and fit 48065941 (`magnified`, `height-magnification-4096` exact). Native change: `CheckSampling` only (`src/evaluator/projection_uv.cpp`, comments in `projection_uv.h`); the filter arithmetic is unchanged. Under the native lock, one `zig build evaluator-tests` (the pytest fixture), DX12:

- `tests/evaluator/test_compositor_height_normal.py`: `test_recorded_inputs_exact[*-height-normal-resolution-4096]` on the CPU and DX12 — Height, Normal_OpenGL, Normal_DirectX and the Normal channel of s0 to s3 equal r1 on every texel and r2 wherever r2 equals r1; `test_height_magnification_at_4096_equals_painter` (the model, r1 and r2); `test_unrecorded_height_magnification_at_4096_is_refused` (the ramps tiled twice, 8x at 4096, refused naming decision 400 and the owner); `test_height_normal_on_the_cpu` (native `height-normal`: the recorded 16x at 4096 evaluates; 32x, an anisotropic scale, the 256 px bitmap tiled twice and BilinearSharp 16x at 4096 refused; 1:1 and Nearest evaluate): all passed.
- `tests/parity/fit/test_normal.py` (17, the new 8-bit corner-weight case included) and `test_published_fit_reproduces` (the republished `height-to-normal.json`): 18 passed.

## Alternatives Considered

- **Admit every magnification at 4096, as at 2048 and below.** Rejected: only 16x of an identity projection is recorded at 4096.
- **Admit 2x to 8x at 4096 on the arithmetic argument.** Rejected for now: not recorded at 4096 (decision 001); §4 names the recording.
- **Change the CPU and GPU filters.** Rejected: they already equal Painter on every recorded texel; only the Python model was wrong.

## Consequences

- A 256 px height bitmap filling a 4096 px set (the default projection) now evaluates and exports as Painter writes it, Height and both virtual normal maps.
- Other Height magnifications on 4096 px sets (tiling, other low resolutions) stay refused until §4's recordings are made.
