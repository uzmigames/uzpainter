# 46. The normal-map opacity rotation uses the recording GPU's GLSL arcsine and measured sine and cosine tables

**Status**: accepted
**Date**: 2026-10-11
**Related Tasks**: phase1.11_compositor-blend-gaps

## Context

`phase1.10_compositor-blend-kernels` left NormalMapCombine, NormalMapDetail and NormalMapInverseDetail exact at opacity 1 only. Below opacity 1 Painter rotates the upper normal toward (0, 0, 1), and the evaluator's float32 series slerp left values off:
- 176-257 RGB16 values at opacity 0.5, by one code;
- 47 693-72 463 RGB32F values at 0.25, by a few ulp.

Measurements were made on the RTX 4090 the goldens were recorded on, with D3D12 probes and an OpenGL 4.3 compute context on driver 617.14. All of it is scratch tooling only.

**The rotation.** n' = (n.x k, n.y k, cos(alpha t)), with t = float32(pi/2) - asin(z) and k = sin(alpha t) rsqrt(fma(-z, z, 1)).
- With the GPU's **GLSL** `asin`, it equals both recordings on every value. That covers `blend-component` s4-s6 (RGB16 and sRGB8 at 0.5, RGB32F at 0.25, every other format) and `blend-normal-channel` s1-s3.
- With D3D12's `acos` or `asin`, 1 000-2 000 RGB32F values stay off.
- GLSL `acos` is a low-accuracy polynomial (error 6.7e-5) and is far off.
- The slerp form `sin((1 - alpha) t) / sin t` is off on 17 000 or more values, whatever the trigonometry.

**GLSL `asin`.** It is a float32 polynomial with fused multiply-adds: for |x| <= 0.57 a polynomial P, otherwise pi/2 - 2 P(sqrt((1 - x)/2)).
- It equals the GPU on every float32 of [0, 1] (1.07e9 values). Subnormals give +0.
- The evaluator's `Fma` (exact product, one double addition) gives the same results on every normal input.

**`sin` and `cos`.** The GPU's results are the same in D3D12 and GLSL. They depend only on k = floor(2^25 trunc(x float32(1/(2 pi)))). This was checked on every float32 of [0, float32(pi/2)].

The model panel was consulted under the owner's delegation (cx/gpt-6-astra, kimi/kimi-k3, xai/grok-4.5):

| Claim | Verdicts |
|---|---|
| C1 Adopt the rotation and lift the normal-map release-gap notes | AGREE x1, PARTLY x2: scope "exact" to the recording profile (RTX 4090, its driver), state the z = 1 endpoint, add an off-grid opacity golden |
| C2 Measured tables for sin/cos, as for rcp/sqrt/log2; another GPU needs new tables and a new profile id | AGREE x1, PARTLY x2: on a new GPU spot-check the existing tables first and recapture only on mismatch; record the 192 MiB runtime cost |
| C3 The GLSL asin polynomial found by exhaustive measurement is clean-room compliant | AGREE x2, PARTLY x1: commit it with its measurement provenance (GPU, driver, API, domain); compliance is a process determination |
| C4 "Painter's blend shaders run as OpenGL GLSL" is a working hypothesis, not a fact | AGREE x3 |

## Decision

1. `arith::TowardFlat` and the HLSL kernel use the measured rotation. `hw::Asin` is the GLSL polynomial. Its constants are committed with their measurement provenance in `hwmath.h`.
2. `hw::Sin` and `hw::Cos` read two measured tables of 2^23 float32 values each, `src/evaluator/tables/hw-sin.zlib` and `hw-cos.zlib` (about 0.6 MB together).
   - `uzp-evaluator-tests trig-hardware` measures them and checks them against the embedded tables, like the existing hardware tables.
   - The GPU path reads them from the function-tables buffer that Levels already uses. That buffer is created on first use and grows to 192 MiB.
   - CPU and GPU stay bit-equal.
3. The three normal-map modes are reported exact against both recordings. Their phase1.10 release-gap notes are removed from the capability inventory.
   - The scope is the recording profile: the tables and the asin describe the RTX 4090 and its driver.
   - For a golden recorded on another GPU, the existing tables are spot-checked first. New tables and a new profile id are made only if they differ.
4. The flat normal (z = 1, where the formula would give `0 * rsqrt(0)`) keeps n. No golden covers it. The recording spec in `parity/reports/phase1/compositor-blend-gaps.md` adds a golden for it, and off-grid opacities.
5. "Painter's blend shaders run as OpenGL GLSL on the recording GPU" is recorded as a working hypothesis. It is used to rank later fits.

## Consequences

- `blend-component` s4-s6 and `blend-normal-channel` s1-s3 are exact on CPU and GPU. Item 2.2 of phase1.11 is met for the recorded opacities 0.5 and 0.25.
- The evaluator's function-tables buffer grows from 128 MiB to 192 MiB.
