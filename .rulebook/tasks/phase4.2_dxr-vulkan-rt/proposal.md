# Proposal: phase4.2_dxr-vulkan-rt

## Why
The optional `GpuBaker` has a Vulkan backend, `vulkan_rt`, using `VK_KHR_ray_query` with `VK_KHR_acceleration_structure` (and its required `VK_KHR_deferred_host_operations`), which UzPainter adds to the vendored render core because the copy has no Vulkan ray tracing (`docs/architecture/06-baking.md` §1; `docs/architecture/13-engine-integration.md` §2.3; delivered to the RHI by P3-VULKAN). The DAG requires each backend to be qualified separately against the Embree outputs and the Painter goldens — same outputs, or a divergence approved through the exception register (`docs/dag.md` P4-DXR; decision 017, Q1). BAK-03 and BAK-07 (`docs/prd.md`) define the settings and accounting; Tier 2b defines the corpus and comparison order (`docs/architecture/14-parity-testing.md` §3; `06-…` §7); qualification runs on the owner's self-hosted GPU runner (`14-…` §7; decision 022, Q9). Child of P4-DXR (`phase4.3_dxr-baker`), implementing D5.

## What Changes
- **`vulkan_rt` backend** on the `GpuBaker` seam: feature detection (Vulkan 1.2+, `accelerationStructure` and `rayQuery` features, the three extensions), acceleration structures through UzPainter's Vulkan ray-tracing addition, SPIR-V kernels compiled by DXC with `SPV_KHR_ray_query` from the same HLSL as `dx12_rt`; `VK_KHR_ray_tracing_pipeline` not required.
- **Qualification run** on the Tier 2b corpus (analytic plane, sphere, bevelled cube with highs; the wand and hat low/high/cage pairs; the ten usages): `vulkan_rt` vs `embree` texel for texel, and vs the private Painter CPU-bake goldens; repeated across runs on the same build and GPU; manifests under `parity/manifests/tier2b/gpu-vulkan-rt/`.
- **Cross-backend report**: `vulkan_rt` vs `dx12_rt` on the same fixtures, every difference reported.
- **Qualification report** in `parity/reports/phase4/` (numbers only) with exception proposals for any divergence, passing only once the owner approves them.
- **Capability-manifest status** for `vulkan_rt`: `supported` only after qualification.

## Dependencies
- Parent DAG inputs: `phase3.5_embree-bakers`, `phase3.3_vulkan-backend-ray-tracing` (Vulkan acceleration structures and ray queries).
- Previous child: `phase4.1_dxr-gpu-baker-core`.
- Parent: `phase4.3_dxr-baker`. Independent of `phase4.2_dxr-dx12-rt` (the cross-backend report runs once both exist).

## Acceptance
Part of the optional P4-DXR gate. `vulkan_rt` is qualified when, on the whole Tier 2b corpus, its outputs equal the Embree outputs and the Painter goldens, or every divergence is covered by an owner-approved exception; it is repeatable on one build and GPU; and a device without the required Vulkan features receives an explicit capability error.

## Impact
- Affected specs: `baker` (Vulkan GPU baker backend)
- Affected code: Baker component (`vulkan_rt` backend, SPIR-V bake kernels, feature detection); `parity/manifests/tier2b/gpu-vulkan-rt/`; `parity/reports/phase4/`; capability manifest
- Breaking change: NO
- User benefit: a qualified Vulkan GPU bake path on the second backend
