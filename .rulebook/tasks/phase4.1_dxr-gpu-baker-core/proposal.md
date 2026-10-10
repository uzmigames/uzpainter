# Proposal: phase4.1_dxr-gpu-baker-core

## Why
The optional `GpuBaker` must run on the same `BakeRequest` and the same sample sequences as `embree` so that each backend can be compared texel for texel with the CPU reference (`docs/architecture/06-baking.md` §1: fixed per-texel Hammersley addressing by texel index and sample id, fixed reduction order, tile partitioning independent of thread count). BAK-03, BAK-04, BAK-05 and BAK-07 (`docs/prd.md`) define the settings, the miss evidence, the job model and the receipt accounting every baker honours. Acceleration structures must be built from the high-poly streams with explicit vertex strides, never through a fixed-stride path such as UzEngine's `BLASManager` (48-byte stride, opaque), which is not vendored (`docs/architecture/12-mesh-import.md` §2; `docs/architecture/13-engine-integration.md` §2.4, §4.1); the kernels are compute shaders with inline ray queries only, compiled from one HLSL source to DXIL and SPIR-V (`13-…` §2.3). Owner decision 022 (Q9) keeps CPU baking GPU-free. Child of P4-DXR (`phase4.3_dxr-baker`), implementing D5.

## What Changes
- **`GpuBaker`** implementing `IBaker` (`caps()`, `bake(BakeRequest)`): same request, same parameter model and same per-texel sample addressing and reduction order as `EmbreeBaker`; the ten `MeshMapUsage` bakers expressed as ray-query compute kernels in one HLSL source compiled to DXIL and SPIR-V through the vendored shader compiler.
- **Acceleration-structure builder for bake inputs**: bottom-level structures from the streamed high-poly positions and indices (and cage) with their real vertex strides and per-geometry opacity flags, through the raw RHI calls; rebuilt only when inputs change.
- **Capabilities**: `caps()` reports the usages, maximum resolution and determinism class per backend; a missing feature raises an explicit capability error before work, with no silent fallback to another backend.
- **Receipts and publication**: `BakeReceipt.tools {backend: dx12_rt|vulkan_rt, backend_version, isa_or_gpu, build_hash}`; the same accounting classes and conservation identity as `embree`; atomic publication per `(texture set, input revision)`; job events and cancellation as for `embree` (`06-…` §6).
- **Backend seam** that `phase4.2_dxr-dx12-rt` and `phase4.2_dxr-vulkan-rt` plug into (device features, acceleration-structure and ray-query dispatch).

## Dependencies
- Parent DAG inputs: `phase3.5_embree-bakers` (request model, sample sequences, receipts, publication), `phase3.3_vulkan-backend-ray-tracing` (Vulkan acceleration structures and ray queries in the RHI).
- Parent: `phase4.3_dxr-baker`. Next children: `phase4.2_dxr-dx12-rt`, `phase4.2_dxr-vulkan-rt`.

## Acceptance
Part of the optional P4-DXR gate. This child is accepted when `GpuBaker` accepts every `BakeRequest` `embree` accepts (or raises an explicit capability error), uses the identical sample addressing (proven by a per-texel sample-index dump compared with Embree's), builds acceleration structures with the real strides of its inputs, and writes receipts whose accounting satisfies the conservation identity on the analytic fixtures.

## Impact
- Affected specs: `baker` (GPU baker core)
- Affected code: Baker component (`GpuBaker`, bake kernels in HLSL, acceleration-structure builder for high-poly streams, capabilities, receipts)
- Breaking change: NO
- User benefit: a GPU bake path that is comparable texel for texel with the CPU reference
