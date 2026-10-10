# Proposal: phase1.8_compositor-sources-projection

## Why
Wand v1, Belt v5 and Tunic v10 are built from fill layers with uniform values per channel and bitmap BaseColor fills in final-UV space (sRGB, UV projection, scale 1, no repeat, BilinearHQ); these sources and the `Fill`/`UV` projections must reproduce Painter exactly, including colour-space handling and in-kernel filtering (LAY-01, LAY-02, LAY-13, PRJ-05, RES-01). Implements D3 (decision 005: Painter-semantic document with a tile/channel evaluator and a measured quantisation profile) with owner answer Q1 (decision 017: exact equality, a divergence passes only through an owner-approved exception) in `docs/architecture/04-layer-stack-and-compositing.md`; formulas are written from public literature and fitted to Tier 0 goldens recorded through Painter's documented API (`docs/architecture/14-parity-testing.md` §2, §3; CLR-01, CLR-02; `docs/licensing-and-clean-room.md`). Child of `phase1.14_compositor-core` (P1-COMPOSITOR), covering `docs/architecture/04-layer-stack-and-compositing.md` §1 (fill and source model), §4 (colour transfer and sampling) and §5 (`Fill` and `UV` projections only).

## What Changes
- `src/evaluator/fill.{h,cpp}`: fill layers and fill effects in `Split` source mode with `active_channels` (the native API never resets values when a channel is toggled, LAY-01; `Material` source mode is a release gap until P3-PROC).
- `src/evaluator/sources.{h,cpp}`: `uniform_color {rgb, color_space}` (sRGB on colour-managed channels, Raw otherwise; explicit IEC 61966-2-1 transfer with any Painter deviation fitted from Tier 0 ramps, no hardware sRGB formats); `bitmap {sha256, color_space}` decoded from resources (16-bit grayscale masks, 8/16-bit sRGB textures) into a RAM/VRAM cache keyed by `(hash, format)`; per-node resource bindings by content hash plus optional alias (LAY-13).
- `src/evaluator/projection_uv.{h,cpp}` + kernels: `Fill` (UV, match per tile) and `UV` (filters `BilinearHQ`, `BilinearSharp`, `Nearest`; the four documented wrap modes; transform with scale mode, scale, rotation, offset), manual in-kernel filtering with kernels fitted to Tier 0 resampling goldens; exact copy at 1:1 texel resolution.
- Connection of the P1-MESH `TexturingMesh` to the UV raster pass of `phase1.3_core-uv-raster`; island-edge behaviour compared with Painter.
- Fits: `parity/semantics/colour-transfer.json`, `parity/semantics/uv-sampling.json`.

## Dependencies
- DAG inputs of the parent: `phase1.4_render-core-layer` (UV raster, resampling), `phase1.7_mesh-loader` (texturing mesh), `phase1.3_document-model`, `phase0.8_tier0-goldens`.
- Sibling prerequisite: `phase1.5_compositor-tile-dag`.
- Parent: `phase1.14_compositor-core`.

## Acceptance
Tier 0 goldens owned by this child are exact: uniform colour spaces, sRGB ramps, UV filters/wrap/transform, `BilinearHQ` resampling, island-edge behaviour of the UV raster. Only the fitted formula, its public source and its residual are published under `parity/semantics/`; the goldens stay in the private oracle store and are compared on the self-hosted GPU runner (`docs/architecture/14-parity-testing.md` §6).

## Impact
- Affected specs: `compositor`
- Affected code: `src/evaluator/fill.*`, `src/evaluator/sources.*`, `src/evaluator/projection_uv.*`, `src/evaluator/kernels/`, `parity/semantics/colour-transfer.json`, `parity/semantics/uv-sampling.json`, `tests/evaluator/`
- Breaking change: NO
- User benefit: Uniform and bitmap fills — the bulk of the pilot stacks — evaluate exactly as in Painter.
