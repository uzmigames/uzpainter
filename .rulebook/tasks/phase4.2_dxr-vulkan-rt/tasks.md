## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: `phase3.5_embree-bakers`, `phase3.3_vulkan-backend-ray-tracing` (parent inputs), `phase4.1_dxr-gpu-baker-core`

## 2. Implementation
- [ ] 2.1 `vulkan_rt` feature detection: Vulkan 1.2+, `VK_KHR_acceleration_structure`, `VK_KHR_deferred_host_operations`, `VK_KHR_ray_query`, features `accelerationStructure` and `rayQuery`; explicit capability error otherwise
- [ ] 2.2 Acceleration structures through UzPainter's Vulkan ray-tracing addition from the core's builder
- [ ] 2.3 SPIR-V ray-query bake kernels (`SPV_KHR_ray_query`) from the same HLSL as `dx12_rt`; no ray-tracing pipeline
- [ ] 2.4 Tier 2b qualification manifests under `parity/manifests/tier2b/gpu-vulkan-rt/` for the analytic fixtures and the wand and hat pairs, ten usages
- [ ] 2.5 Capability manifest: `vulkan_rt` `supported` only after qualification, otherwise an explicit gap with the report reference

## 3. Tests
- [ ] 3.1 `vulkan_rt` vs `embree` on every Tier 2b fixture and usage: hit/coverage evidence first, then maps, texel for texel
- [ ] 3.2 `vulkan_rt` vs the private Painter CPU-bake goldens on the same fixtures
- [ ] 3.3 Repeatability: two runs on the same build and GPU byte-identical
- [ ] 3.4 Cross-backend report `vulkan_rt` vs `dx12_rt` on the same fixtures, every difference reported (once `phase4.2_dxr-dx12-rt` exists)
- [ ] 3.5 Device without `rayQuery`: explicit capability error, nothing published
- [ ] 3.6 Qualification report in `parity/reports/phase4/` with exception proposals for any divergence

## 4. Acceptance
- [ ] 4.1 Child acceptance met and reported to `phase4.3_dxr-baker`: `vulkan_rt` qualified against Embree and the Painter goldens, or each divergence approved

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
