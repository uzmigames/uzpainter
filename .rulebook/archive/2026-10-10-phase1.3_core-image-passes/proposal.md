# Proposal: phase1.3_core-image-passes

## Why
Export padding, resizing and later the UzEngine/Unreal mip chains need GPU image passes that UzPainter owns on the vendored RHI: dilation by jump flooding, resampling, and mip generation that is sRGB-aware, renormalises normals and preserves alpha coverage (`docs/architecture/13-engine-integration.md` §4.1; `docs/architecture/04-layer-stack-and-compositing.md` §7; `docs/architecture/08-export.md` §3). Requirements: EXP-02, EXP-05, NFR-02 (`docs/prd.md`). Implements D12 as decided by the owner (decision 021, Q8: render core vendored from a clean UzEngine commit, zero dependency on UzEngine; decision 022, Q9: Windows 10/11 x64, DX12 primary, Vulkan second backend) in `docs/architecture/13-engine-integration.md` §4.1, §6 and §7, and the evaluator substrate of D3 (decision 005) in `docs/architecture/04-layer-stack-and-compositing.md` §7. Child of `phase1.4_render-core-layer` (P1-CORE).

## What Changes
- `src/render/dilation.{h,cpp}` + `src/render/shaders/dilation_jfa.hlsl`: jump-flood dilation over a coverage mask with a distance limit (the Painter-fitted padding modes are built on it by `phase1.16_export-processing-encoders`).
- `src/render/resample.{h,cpp}` + shader: resampling with the filter kernel as a parameter (the Painter-fitted filters are supplied by the compositor and the exporter).
- `src/render/mips.{h,cpp}` + shader: mip generation in three modes: sRGB-aware (decode, filter, encode), normal (renormalised), alpha-coverage preserving.
- CPU reference implementations of the same arithmetic in `tests/render/reference/` for exact comparison.

## Dependencies
- DAG input of the parent: `phase0.8_toolchain-slice`.
- Sibling prerequisites: `phase1.1_core-device-kernels`, `phase1.2_core-readback`.
- Parent: `phase1.4_render-core-layer`. Consumers: `phase1.16_export-processing-encoders` (padding, resize); the Phase 3 export presets (mips).

## Acceptance
P1-CORE gate, image-pass part: unit tests on synthetic masks and images pass on DX12, each pass equal to its CPU reference and repeatable byte for byte.

## Impact
- Affected specs: `render-core`
- Affected code: `src/render/dilation.*`, `src/render/resample.*`, `src/render/mips.*`, `src/render/shaders/`, `tests/render/`
- Breaking change: NO
- User benefit: Deterministic padding, resizing and mip chains shared by export, preview and presets.
