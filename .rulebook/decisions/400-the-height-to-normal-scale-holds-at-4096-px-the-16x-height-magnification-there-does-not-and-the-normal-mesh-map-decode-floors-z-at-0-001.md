# 400. The height-to-normal scale holds at 4096 px, the 16x Height magnification there does not, and the Normal mesh map's decode floors z at 0.001

**Status**: accepted
**Date**: 2026-11-03
**Related Tasks**: phase2.10_pilot-tunic-recovery, phase2.9_pilot-belt, phase1.12_compositor-height-normal, phase3.1_height-magnification-fit

## Context

Decision 079 lifted the height-to-normal scale z = 100 / W (Sharp) and 800 / W (Sobel) on the recorded square sets of 256 to 2048 px. The Tunic's set is 4096 px, so every Tunic export, the measure mode included, was refused before writing (decision 398, Result; `phase2.10_pilot-tunic-recovery` items 2.5, 3.1, 3.4, 3.5).

The request `tier0/semantics/height-normal-resolution-4096` (16f956e6) is decision 077's resolution golden with only the document resolution changed to 4096: the 256 px 16-bit height ramps on four texture sets, magnified 16 times by the default UV projection (BilinearHQ, Repeat), s0 at opacity 1, s1 at 0.5, s2 at 0.25, s3 doubled in LinearDodge, Sharp. It was recorded and admitted (dff6765f): r1 and r2 after save and reopen, a second Painter process reproducing all 32 maps byte for byte. r2 differs from r1 only on the virtual maps of s1 and s2.

Separately, decision 399's second Result traced the Sash v5's 196 interior Normal values to the Normal mesh map's decode: they are exactly the covered texels whose mesh map has z <= 0.

## Measurements

Counts are of values (components) unless they say texels. The model is `tools/parity/fit/normal.py`, which the evaluator follows operation for operation.

1. **The scale at 4096 is exact.** Painter's own recorded s0 Height (opacity 1) and s3 Height (two copies in LinearDodge), whose exported half equals the float32 read-out, through `normal_maps` with z = 100 / 4096: Normal_OpenGL and Normal_DirectX differ from Painter in 0 values, r1 and r2.
2. **The 16x magnification of the 256 px bitmap is not exact.** The magnification that is exact at 512, 1024 and 2048 px (`magnified`, the evaluator's `BilinearFilter` on the signed values, then the half write) gives 48,126 of the 16,777,216 s0 Height texels off (0.29 %): 38,847 by one binary16 step, the largest difference 2^-10, 6 of them on the other side of zero. The 2048 px Height (8x) is exact (`test_recorded_inputs_exact`).
3. **What the recordings cannot separate.** The only inexact magnification is 16x on a 4096 px set. P20-A (`phase1-fill-channel-defaults`) records a 16x Height magnification exact, but of a 16 px 8-bit two-valued checker on a 256 px set (decisions 218, 224). So the evidence does not say whether the set size or the factor is what breaks; it says only that no Height magnification on a set above 2048 px is recorded exact.
4. **The Tunic's Height sources** (the admitted current round `phase2/tier1/tunic-v10-current`, its stack working copy `a5bc5613…`): 22 fill layers in two groups. Ten give a Height value, each a uniform colour: C01 and F01 0 (unmasked), and under masks C02 -0.035, C06 0.012, C07 0.04, C08b 0.01, C08c -0.05, C08d 0.03, C10 -0.01, F02 -0.02; the other twelve give none. The group `Forro` sits under `M_lining` and replaces the Height (`replace_height`). All 17 mask bitmaps are 16-bit grey 4096 x 4096 PNGs (checked in the private store), so every mask is sampled 1:1. No Height source is a bitmap, so nothing on Height is magnified. The Normal mesh map is a 16-bit RGB 4096 px PNG at the set resolution.
5. **The mesh map's z floor** (decision 399, Result 2): Painter decodes the Normal mesh map as normalise(2c - 1) with z floored at float32(0.001) before the normalise; UzPainter floored it at 0 (`arith::DecodeNormal`). With 0.001 the model matches Painter on all 126 interior texels and 114 of the 115 edge texels of the Sash and changes no other interior texel. Floors of 2^-10, 5e-4 and 2e-3 miss, and so do a clamp after the normalise, no clamp, |z| and an unnormalised decode. Every recorded `height-normal-mesh-map` golden's map has z codes of 57,680 and above, where both floors agree.

## Decision

1. **Admitted:** the Sharp scale z = 100 / W on square 4096 px sets (`RecordedResolution` in `src/evaluator/height_to_normal.cpp`). Sobel at 4096, non-square sets and other sizes stay refused: no recording.
2. **Refused:** a bilinear (BilinearHQ or BilinearSharp) magnification of a bitmap on the Height channel of a set wider or taller than 2048 texels, along any axis (the smaller singular value of the UV Jacobian below 1; `CheckSampling` in `src/evaluator/projection_uv.cpp`), with `evaluator:unsupported_source` naming this decision and the owner `phase3.1_height-magnification-fit`. 1:1, Nearest, and magnification on sets of 2048 px and less are unchanged. The refusal is by set size, not by factor, because §3's evidence cannot be read as "16x is inexact" (P20-A's 16x is exact) and decision 001 admits only what a recording shows exact.
3. **The owner** of the magnification is a new Phase 3 level-1 task, `phase3.1_height-magnification-fit`. It is not `phase3.1_export-island-padding`: that task owns padding and the island-edge Normal on UV islands, an export problem, while this one is the compositor's bilinear filter on a fully covered set. No pilot needs it (§4).
4. **The Normal mesh map's decode** floors z at float32(0.001) before the normalise, in the combined virtual texel and on the padded normal (`MeshDecode` in `height_to_normal.cpp`, the `V_FLAG_MESH_TILE` decode in `shaders/evaluator_blend.hlsl`, `mesh_decode` in `tools/parity/fit/normal.py`). The Normal channel's decode and the normal-map blends keep `arith::DecodeNormal` (z floored at 0), which their own goldens fit; the geometry-only pass-through still copies the codes.

## Results (2026-11-03)

Native change 7d35eb99, under the native lock, one `zig build evaluator-tests` and one `zig build painter -Doptimize=ReleaseFast` (`UzPainter.exe` `4900af06…`), DX12.

- **Evaluator** (`tests/evaluator/test_compositor_height_normal.py`, `tests/parity/fit/test_normal.py`): 63 passed. Every earlier height-normal golden stays exact on the CPU and DX12, the mesh-map goldens included; the published `height-to-normal.json` still reproduces. New: the 4096 golden's scale (§1), its refused magnification (§2), a 1:1 4096 px Height evaluated on the CPU and DX12 with normals equal to the model's, and the native `height-normal` checks (Sharp 4096 admitted; Sobel at 4096, 4096 x 2048 and 8192 refused; 16x, 32x and an anisotropic scale at 4096 refused; 1:1 and Nearest at 4096 and 16x on a 256 set admitted; mesh operands with z <= 0 in both conventions, on the CPU and, through `height-normal-gpu-vs-cpu`, on DX12).
- **The Sash** (`tests/parity/tier1/sash_v5`): 4 passed, 1 xfailed (the production round's expected islanded refusal). Tier 1 is now **`pass` under EXC-012**: the Normal's covered interior differs in 0 values (was 196), its island edge in 880 (was 1,059), its padding in 66,753; every other map's covered texels are equal (f1c2b21a).
- **The Wand** (`tests/parity/tier1/wand_v1/test_wand_v1.py`): 2 passed, its report unchanged but for the build hash. Its mesh map has no covered texel with z <= 0.
- **The Tunic** (`test_mcp_round.py`, its three real-run tests): the height-to-normal refusal is gone, and no magnification refusal is met (§4). The exports now stop on the GPU request deadline instead: `timeout {backend: dx12, reason: the GPU did not complete the submitted work before the deadline (request deadline 60000 ms)}`, raised by `uzpainter.export.export_project_textures` in the rebuild's `run` process, before any file is written. Both Tier 1 rebuilds failed so in the module fixture (the two Tier 1 tests error at setup, no report written); the measure-mode recipe test failed with `RecipeFailed`, whose private diagnostic was not kept (pytest's `tmp_path` retention of 1 removed it before it was read), so its cause is not confirmed to be the same deadline. The `run` verb's export engine uses the default `EngineOptions::requestDeadline` of 60 s (`src/render/engine_thread.h`) and has no `--gpu-deadline-ms` option, unlike `--mcp` and `--worker`. No map was compared; items 2.5, 3.1, 3.4 and 3.5 stay open on this new blocker.

## Alternatives Considered

- **Refuse magnification by factor (above 8) instead of set size.** Rejected: it would refuse P20-A's recorded-exact 16x Height and still admit an unrecorded 2x magnification at 4096.
- **Admit 4096 for both methods, as decision 079 extended Sobel to 512 and 2048.** Rejected: this recording is Sharp only.
- **Wait for the magnification fit before admitting the scale.** Rejected: the scale is proven independently of the magnification (§1), and the Tunic needs only the scale.
- **Change `arith::DecodeNormal` for everyone.** Rejected: the Normal channel and the normal-map blends are fitted with the floor at 0 on their own goldens, and no recording shows them with the 0.001 floor.

## Consequences

- The Tunic's 4096 px export is no longer refused by the height-to-normal scale; it now stops on the 60 s GPU request deadline of the `run` export (Results).
- A Height bitmap magnified onto a 4096 px set (a tiling or low-resolution height map) is refused until `phase3.1_height-magnification-fit` fits it.
- Normal mesh maps with texels of z <= 0 now combine as Painter does; the Sash's 196 interior values were their only recorded instance.
