## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: `phase3.5_embree-bakers`, `phase3.3_vulkan-backend-ray-tracing` (parent inputs)

## 2. Implementation
- [ ] 2.1 `GpuBaker` implementing `IBaker` on the shared `BakeRequest` and parameter model
- [ ] 2.2 Shared sample addressing (Hammersley by texel index and sample id) and fixed reduction order in the kernels, matching `EmbreeBaker`
- [ ] 2.3 Ray-query compute kernels for the ten `MeshMapUsage` bakers in one HLSL source, compiled to DXIL and SPIR-V
- [ ] 2.4 Acceleration-structure builder for high-poly (and cage) streams with explicit vertex strides and per-geometry opacity through the raw RHI calls
- [ ] 2.5 `caps()` per backend and explicit capability errors before work; no silent fallback
- [ ] 2.6 Receipts with backend fields, the same accounting classes and conservation identity; atomic publication; job events and cancellation
- [ ] 2.7 Backend seam for device features and ray-query dispatch used by the two backend children

## 3. Tests
- [ ] 3.1 Sample-addressing test: per-texel sample indices and directions dumped by `GpuBaker` equal Embree's for the same request
- [ ] 3.2 Stride test: a high-poly stream with a non-default vertex stride builds and intersects correctly (analytic plane and sphere)
- [ ] 3.3 Receipt accounting on the analytic fixtures (plane, sphere, bevelled cube with highs, part with a buried face): exact expected counts per class and conservation identity
- [ ] 3.4 Capability test: a request needing a missing feature fails before work with the missing feature named
- [ ] 3.5 Cancellation during a GPU bake: the receipt states whether work stopped before or after publication; no partial authoritative bake

## 4. Acceptance
- [ ] 4.1 Child acceptance met and reported to `phase4.3_dxr-baker`: shared contract, identical sample addressing, correct strides, conserved accounting

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
