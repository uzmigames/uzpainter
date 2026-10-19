# 305. Float (EXR) oracles in procedural certification are compared bit for bit in their stored type, and their residuals are counted in ULPs

**Status**: accepted
**Date**: 2026-10-19
**Related Tasks**: phase3.1_proc-backend-seam

## Context

Decision 303 built the procedural certification harness for `u8` and `u16` rasters only, and left float (EXR) oracles open (its risk 4). Painter writes float maps as OpenEXR half or single floats. The repository already decodes them with `tools/parity/fit/decode.py::decode_exr`, which widens every stored sample exactly to float64.

Decision 001 makes acceptance exact equality. For a float map that means the same bits, not values within a tolerance. A residual still has to be measured in a unit that means the same thing at every magnitude. An absolute float difference does not do that.

The coordinator set the approach in the task brief: use `decode_exr`, compare exactly by narrowing back to the stored float32 or float16 type and comparing bit patterns, and measure residuals as ULP distance. No model panel ran, because no design fork was left open.

## Decision

Code: `tools/parity/proc_cert/raster.py` and `batch.py`. Tests: `tests/parity/proc_cert/test_proc_cert_harness.py`.

1. **Formats and encodings.**
   - Formats: `f16` (IEEE 754 half) and `f32` (single), beside `u8` and `u16`.
   - Encodings: `exr` holds `f16` or `f32`; `png` holds `u8` or `u16`; `raw` (little-endian samples) holds any of the four.
   - A case whose blob encoding cannot hold the declared format is refused when the batch loads.
2. **Decoding an EXR oracle.**
   - The blob goes through `decode_exr`.
   - Its stored precision must be the declared one: 16 bits for `f16`, 32 for `f32`. Otherwise the blob is refused.
   - The float64 samples are narrowed back to the declared type. Widening the narrowed samples again must give the same float64 bits, so a channel stored at another precision is refused, never rounded.
   - The shape must be the declared (resolution, resolution, channels). Channels come in `decode_exr`'s order (R, G, B, A, Y, then the rest by name).
   - Without OpenEXR's binding, the case is `oracle_unavailable` and names the missing binding.
3. **Exactness.** A case is `exact` only when every sample has the oracle's bit pattern. The candidate's output must already be the declared float type. Nothing is converted, so a float64 or float16 output for `f32` fails the case.
4. **Residuals in ULPs.**
   - Each sample's bit pattern is mapped to its position in IEEE 754 total order. Non-negative patterns keep their magnitude. A negative pattern with magnitude `m` maps to `-m - 1`.
   - The residual of a sample is the distance between the two positions: the number of representable patterns between them.
   - So 0 ULPs means the same bits; -0 and +0 are 1 ULP apart; NaNs are compared by their bits and are never equal by value.
   - The per-case histogram, max, exact sum, mean, nearest-rank p99 and affected-texel count are computed as for integer formats.
5. **Units are never pooled across formats.**
   - Each residual names its unit: `code_u8`, `code_u16`, `ulp_f16` or `ulp_f32`.
   - The report's `calibrated` status has one pooled entry per unit, under `residuals`. This also stops `u8` and `u16` code values being pooled together.

## Alternatives Considered

- **Absolute or relative float difference.** Rejected. An absolute difference means different things at different magnitudes, and a relative one is undefined at zero. Neither gives 0 only for equal bits.
- **ULP distance on the magnitude alone** (-0 equal to +0). Rejected. Equal bits would no longer be the same thing as a distance of 0.
- **Comparing the widened float64 values.** Rejected. -0 equals +0 and NaN never equals itself, so neither value comparison is a bit comparison.

## Consequences and open risks

1. `decode_exr` widens through float64. Quiet NaN payloads survive the round trip. A signalling NaN may come back quieted, so its stored bits can be lost. Recorded float maps are not expected to hold signalling NaNs.
2. A channel stored as 32-bit unsigned integers decodes as `f32`, and passes when every value fits in a float32. Its stored type is not checked.
3. Real EXR batches still wait on Painter recordings, item 2.7 of `phase3.1_proc-backend-seam`. The tests write their EXR oracles with OpenEXR's binding, and skip those cases on a machine without it.
