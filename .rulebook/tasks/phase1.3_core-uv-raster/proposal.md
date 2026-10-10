# Proposal: phase1.3_core-uv-raster

## Why
Projections, generators and bakers read the texturing mesh in UV space. `docs/architecture/12-mesh-import.md` §5 specifies a UzPainter pass that renders the mesh per texture set and tile into position, normal, tangent-frame, island-id and material-id buffers with texel-centre coverage and a conservative coverage mask computed by supersampling, because the vendored RHI has no conservative rasterisation. Requirements: PRJ-01, PRJ-07, NFR-02 (`docs/prd.md`). Implements D12 as decided by the owner (decision 021, Q8: render core vendored from a clean UzEngine commit, zero dependency on UzEngine; decision 022, Q9: Windows 10/11 x64, DX12 primary, Vulkan second backend) in `docs/architecture/13-engine-integration.md` §4.1, §6 and §7, and the evaluator substrate of D3 (decision 005) in `docs/architecture/04-layer-stack-and-compositing.md` §7. Child of `phase1.4_render-core-layer` (P1-CORE), whose gate requires unit tests on synthetic meshes.

## What Changes
- `src/render/uv_raster.{h,cpp}` and `src/render/shaders/uv_raster.hlsl`: UV-space raster pass taking backend-neutral corner buffers (positions, corner normals, `uv0`, tangent xyz + sign, material id, island id) with explicit vertex strides, producing per set and per UV tile: position, normal and tangent-frame buffers (RGBA32F), island-id and material-id buffers (R32Uint), texel-centre coverage and a supersampled conservative coverage mask.
- Buffers are UV-tile indexed (tile 1001 only in v1) so the UV-tile workflow can be added later without a data-model change (`docs/architecture/12-mesh-import.md` §6).

## Dependencies
- DAG input of the parent: `phase0.8_toolchain-slice`.
- Sibling prerequisite: `phase1.1_core-device-kernels`; its tests read results through `phase1.2_core-readback`.
- Parent: `phase1.4_render-core-layer`. The production input (the `TexturingMesh` of P1-MESH) is connected by `phase1.8_compositor-sources-projection`; this child is tested on synthetic meshes.

## Acceptance
P1-CORE gate, raster part: unit tests on synthetic meshes pass on DX12. The Tier 0 comparison of island-edge behaviour against Painter is owned by `phase1.8_compositor-sources-projection`, not by this child.

## Impact
- Affected specs: `render-core`
- Affected code: `src/render/uv_raster.*`, `src/render/shaders/uv_raster.hlsl`, `tests/render/`
- Breaking change: NO
- User benefit: Every UV-space feature reads one shared, repeatable rasterisation of the mesh with explicit coverage.
