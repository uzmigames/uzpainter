# Proposal: phase1.4_render-core-layer

## Why
Every GPU feature of UzPainter (compositor, export padding, later preview, path tracer and GPU baker) needs a UzPainter-owned layer on top of the render core that P0-VENDOR copies into `thirdparty/uzengine-render-core/`. Without it the compositor (P1-COMPOSITOR) has no device wrapper, kernel cache, readback or UV raster to run on. Requirements: OWN-02, OWN-08, ARC-07, ARC-08, NFR-01, NFR-03 (`docs/prd.md`). Implements D12 as decided by the owner (decision 021, Q8: render core vendored from a clean UzEngine commit, zero dependency on UzEngine; decision 022, Q9: Windows 10/11 x64, DX12 primary, Vulkan second backend) in `docs/architecture/13-engine-integration.md` §4.1, §6 and §7, and the evaluator substrate of D3 (decision 005) in `docs/architecture/04-layer-stack-and-compositing.md` §7. Phase 1 qualifies the layer on DX12 behind backend-neutral interfaces so that P3-VULKAN adds Vulkan without changing callers (`docs/roadmap.md` Phase 1; DAG node P1-CORE in `docs/dag.md`).

This is the parent integration and acceptance task; the work is split per the `docs/dag.md` task decomposition rule into four independently reviewable children.

## What Changes
Integration of the four children into the UzPainter-owned render-core layer (DAG Outputs of P1-CORE):
- `phase1.1_core-device-kernels`: device/queue wrapper on the vendored RHI, engine thread, kernel compile + cache (DXIL and SPIR-V), capability query (`src/render/`).
- `phase1.2_core-readback`: `TextureReadback` (`src/render/texture_readback.*`).
- `phase1.3_core-uv-raster`: UV-space raster pass (`src/render/uv_raster.*`, `src/render/shaders/uv_raster.hlsl`).
- `phase1.3_core-image-passes`: dilation (jump-flood), resampling, mip generation (`src/render/dilation.*`, `src/render/resample.*`, `src/render/mips.*`).

All of it is qualified on DX12 behind backend-neutral interfaces (`src/render/backend.h`); tests live in `tests/render/`. Files under `thirdparty/uzengine-render-core/` change only through P0-VENDOR's modification log (`docs/architecture/13-engine-integration.md` §3.3).

## Dependencies
- DAG input: `phase0.8_toolchain-slice` (P0-TOOLCHAIN: `build.zig`, `UzPainter.exe selftest` hardware slice on DX12, vendored render core building standalone).
- Children (all mandatory): `phase1.1_core-device-kernels`, `phase1.2_core-readback`, `phase1.3_core-uv-raster`, `phase1.3_core-image-passes`.
- Downstream: `phase1.14_compositor-core` (P1-COMPOSITOR) and, in Phase 3, `phase3.3_vulkan-backend-ray-tracing` and `phase3.7_path-tracer`.

## Acceptance
DAG gate of P1-CORE: unit tests on synthetic meshes pass and readback drain tests pass on DX12 (`docs/architecture/13-engine-integration.md` §7, Phase 1: "readback drain tests and compositor kernels on DX12, behind backend-neutral interfaces"). The parent closes only when all four children are accepted.

## Impact
- Affected specs: `render-core`
- Affected code: `src/render/`, `src/render/shaders/`, `tests/render/`, `build.zig` (render-layer targets)
- Breaking change: NO
- User benefit: The compositor and exporter get a qualified, deadline-bounded DX12 compute, readback and UV-raster substrate that Vulkan can later slot under without API changes.
