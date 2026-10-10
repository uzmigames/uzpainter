# Proposal: phase4.3_dxr-baker

## Why
OWN-05, BAK-03 and BAK-07 (`docs/prd.md`) are met in v1 by the Embree CPU bakers (P3-BAKER); the GPU baker is the later, optional second implementation of the same contract: `GpuBaker` with a `dx12_rt` backend (DXR Tier 1.1, SM 6.5 `RayQuery` kernels) and a `vulkan_rt` backend (`VK_KHR_ray_query` and `VK_KHR_acceleration_structure`, added by UzPainter), on the same `BakeRequest` and sample sequences as `embree`, each backend qualified separately against the Embree outputs and the Painter goldens (`docs/architecture/06-baking.md` §1). Owner decision 022 (Q9) states that CPU baking needs no GPU and that the GPU path runs on DX12 and Vulkan; decision 017 (Q1) admits a divergence only through the exception register; the GPU path is never a requirement for importing maps or stack operations. This is DAG node P4-DXR (`docs/dag.md`, kept and retargeted in round 4), implementing D5 (`06-baking.md` §1–§4 and §7; `docs/architecture/13-engine-integration.md` §2.3, §2.4, §4.1; `docs/architecture/12-mesh-import.md` §2). **Optional:** it is not a predecessor of any gate.

This task is the parent integration and acceptance task, split into a shared core and one qualification child per backend, because the DAG requires each backend to be qualified separately.

## What Changes
- `phase4.1_dxr-gpu-baker-core`: `GpuBaker` implementing `IBaker` on the shared `BakeRequest`, sample addressing and reduction order; compute kernels with inline ray queries written once in HLSL (DXIL and SPIR-V); acceleration structures built from the high-poly streams with explicit vertex strides and per-geometry opacity; capability checks; receipts naming the backend; atomic publication like `embree`.
- `phase4.2_dxr-dx12-rt`: the `dx12_rt` backend (DXR Tier 1.1 + SM 6.5 `RayQuery`) and its qualification.
- `phase4.2_dxr-vulkan-rt`: the `vulkan_rt` backend (`VK_KHR_ray_query`, `VK_KHR_acceleration_structure` with `VK_KHR_deferred_host_operations`) and its qualification.
- Parent integration: backend selection through `BakeRequest`/capabilities, capability-manifest entries per backend, and one qualification report per backend in `parity/reports/phase4/`.

## Dependencies
- DAG inputs: `phase3.5_embree-bakers` (P3-BAKER), `phase3.3_vulkan-backend-ray-tracing` (P3-VULKAN).
- Children (mandatory for this optional parent): `phase4.1_dxr-gpu-baker-core`, then `phase4.2_dxr-dx12-rt` and `phase4.2_dxr-vulkan-rt` (independent of each other).
- Downstream: none (optional; not a predecessor of G4 or G5).

## Acceptance
DAG gate of P4-DXR: each backend qualified separately against the Embree outputs and the Painter goldens — same outputs, or a divergence approved through the exception register. A backend that does not qualify stays an explicit capability gap with its report; the other backend may still qualify.

## Impact
- Affected specs: `baker` (GPU baker)
- Affected code: Baker component (`GpuBaker`, ray-query kernels, acceleration-structure builder for high-poly streams), capability manifest, `parity/manifests/tier2b/`, `parity/reports/phase4/`
- Breaking change: NO
- User benefit: faster bakes on qualified GPUs with outputs proven equal to the CPU reference
