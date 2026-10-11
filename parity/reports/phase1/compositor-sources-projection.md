# `phase1.8_compositor-sources-projection` — acceptance run on the owner's machine

Child of `phase1.14_compositor-core` (P1-COMPOSITOR; `docs/architecture/04-layer-stack-and-compositing.md` §1, §4, §5). Decision 028: the Tier 0 comparisons against the private oracle store and the GPU checks run locally on the owner's machine, and this report is their evidence. Numbers and hashes only; every recorded Painter output stays in the private store. Run on 2026-10-11 on the tree of commit `f33eab8` with this task's working-tree changes (`src/evaluator/`, `tests/evaluator/`, `assets/templates/`, `build.zig`, `parity/semantics/colour-transfer.json`, `parity/semantics/uv-sampling.json`).

**Result: every Tier 0 set owned by this child is exact on both backends, except one value of `resample-uv` (one code, a near-tie, both recordings) and the bilinear minification case. By the answer to this task's q1 (Split, 2026-10-11) both moved to `phase1.9_compositor-resample-gaps`, which stays open until they match exactly or the owner approves an exception; nothing here is accepted as a pass for them.** Unit tests green; the projection kernel equals the CPU reference bit for bit.

## Run record

| Item | Value |
|---|---|
| Hardware | NVIDIA GeForce RTX 4090, Windows 11 Pro 10.0.26200 |
| Backend | DX12; kernels `cs_6_6 -Gis` through the render layer's kernel cache |
| Build | Zig 0.15.2, Debug; `zig build painter evaluator-tests` exit 0 with `-Wall -Wextra -Werror -ffp-contract=off` on `src/evaluator/` and `tests/evaluator/` |
| Oracle | `C:\Users\Bolado\AppData\Local\UzPainter\parity-store` (735 hashes), Painter build `12.1.0+js-api.1.1.20`; comparisons through `tools.parity.fit` (`Golden.map`), recordings `r1` and `r2` |

## Tier 0 comparisons

Residual statistics: `parity/semantics/colour-transfer.json` and `parity/semantics/uv-sampling.json` (re-derived from the evaluator's output by `tests/evaluator/sources_fits.py`; `test_published_fits_reproduce` requires them byte for byte). Every row was compared on the CPU store and on the GPU store.

| Item | Goldens | Compared | Result |
|---|---|---|---|
| 3.1 uniform colour spaces | `colour-ramps-srgb`, `-working`, `-raw` | 288 colours × 3 spaces on RGB16 (User0-3) and sRGB8 (User4-7), s0-s23, as 16-bit exports | exact (0 of 18 874 368 values per group and recording) |
| 3.2 sRGB ramps, encode/decode | the same ramps (store) and `blend-inputs` s0-s1 User2-3 (every sRGB8 code exported) | the store through the recording GPU's float-to-sRGB8 thresholds, the export through its decode | exact; the IEC rounding of `srgb-transfer.json` was 1 code off on 12 ramp values and the 8-bit IEC decode up to 256 export codes off |
| 2.3 bitmap import | `blend-inputs` s0, s1 (fields A, B: every 16-bit code) | RGB16 (User0-1), sRGB8 (User2-3), RGB8 (User4), L16 (User6) | exact (2 097 152 values per recording) |
| 3.2 sRGB8 stacks | `blend-order` s0-s3 User1, `group-masks` s0-s1 User1 | the sRGB8 channels phase1.5 could not compare | exact |
| Height bitmaps | `height-normal-plane-amplitudes` s0-s3 | Height (OpenEXR 32f): t ↦ 2t − 1, half toward zero, over the signed base 0; opacity 1, 0.5, 0.25; LinearDodge doubling | exact |
| 3.3 Nearest | `resample-uv` s2 User0-7 | scales 1, 0.73, 1.37×2.11, 3.3, rotation 30°, offsets | exact |
| 3.3 BilinearHQ/Sharp, Repeat | `resample-uv` s0, s1 User0-5, 7 | same transforms | 1 value of 1 376 256 per set and recording, |Δ| 1 (s0/s1 User2, texel (175, 18), green: the exact weighted sum lies 2^-34.7 above a float32 midpoint and Painter rounds it down) |
| 3.3 BilinearHQ, RepeatNone | `resample-uv` s3 User0-5, 7 | clamp inside the UV square, the value below outside | exact |
| 3.3 minification | `resample-uv` s0, s1, s3 User6 (scale 3.3) | — | refused with `evaluator:unsupported_source` (Painter prefilters; not fitted, `resampling.json`); moved with the near-tie to `phase1.9_compositor-resample-gaps` |
| 3.4 island edges | `height-normal-sphere`, `height-normal-bevelled-cube` | Height on every texel whose centre a triangle covers (the fixture imported by `src/mesh/` and rasterised by `src/render/uv_raster.h`: 61 440 and 53 336 texels) | exact; the texels outside the islands are export padding (`padding: infinite`), not stack values |

Findings, each fixed at the root: (a) Painter's sRGB8 store and decode are the GPU's `R8G8B8A8_UNORM_SRGB` conversions, not the IEC formula: the store thresholds (smallest float32 of each code) and the decode of each code were measured on the recording GPU (`uzp-evaluator-tests srgb8-hardware`, which re-checks them against 198 393 values) and replace the IEC tables in `arith.cpp`; (b) bilinear filtering sums float32 texels `float32(c / M)` with the 8-bit weights exactly and rounds once (the integer 20-bit rule of `resampling.json` left about 280 values per map one code off); (c) the Height channel stores bitmaps as 2t − 1 over a zero backdrop.

(d) The Height channel is signed with base 0 (`height-normal-plane-amplitudes` s1, s2 store 0.5 (2t − 1) and 0.25 (2t − 1)); the 26 templates carried base 0.5, read from the PNG export of an empty channel. They now carry 0 with the 16-bit PNG export (h + 1)/2, which reproduces the empty-channel code 32767 (every `base-values-*` golden still exact) and makes s1 and s2 exact. The PNG export of a non-zero Height and the EXR export of an empty one are not recorded.

## Unit tests and kernels

| Case | Evidence |
|---|---|
| `sources` (CPU) | 1:1 copies of 16-bit colour, 8-bit colour and 16-bit grey bitmaps under every filter on all nine channel formats; `Fill` projection; whole-texel offsets (Nearest, BilinearHQ), magnification by two, a half-texel bilinear sample, `RepeatNone`, `RepeatHorizontally`, a 90° rotation; explicit failures (minification, physical-size scale, OCIO, non-power-of-two set, non-PNG bytes, bytes not matching their hash); LAY-13 (two fills binding different bytes under the alias `M_piping` read their own); a resolution change on the same evaluator re-evaluates every tile at the new size |
| `projection-gpu-vs-cpu` | 36 random projection stacks over the 9 formats (filters, wrap modes, transforms, 8/16-bit grey and colour bitmaps, Height, a 2048 × 1024 two-tile set): 43 581 440 samples, GPU = CPU bit for bit; GPU resolution change |
| `srgb8-hardware` | the decode of 256 codes, the 255 thresholds and 198 393 encodes equal the tables |
| `gpu-vs-cpu`, `kernel-sweep` (phase1.5) | still bit for bit with the new sRGB8 tables |

Cache keys (coordinator's finding): every subtree hash is now seeded with the set resolution (`dag.cpp` `ContentStartHash`); before, a resized set reused tiles of the old size.

## Reproduce

```
zig build evaluator-tests
python -m pytest tests/evaluator
python tests/evaluator/sources_fits.py zig-out/bin/uzp-evaluator-tests.exe <work-dir>
```
