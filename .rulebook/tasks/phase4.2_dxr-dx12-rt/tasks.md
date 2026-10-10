## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: `phase3.5_embree-bakers`, `phase3.3_vulkan-backend-ray-tracing` (parent inputs), `phase4.1_dxr-gpu-baker-core`

## 2. Implementation
- [ ] 2.1 `dx12_rt` feature detection: DXR Tier 1.1 through `D3D12_FEATURE_D3D12_OPTIONS5`, SM 6.5 `RayQuery`; explicit capability error otherwise
- [ ] 2.2 BLAS/TLAS build through the vendored DXR primitives from the core's acceleration-structure builder
- [ ] 2.3 DXIL ray-query bake kernels dispatched as compute; no DXR pipeline, shader tables or `DispatchRays`
- [ ] 2.4 Tier 2b qualification manifests under `parity/manifests/tier2b/gpu-dx12-rt/` for the analytic fixtures and the wand and hat pairs, ten usages
- [ ] 2.5 Capability manifest: `dx12_rt` `supported` only after qualification, otherwise an explicit gap with the report reference

## 3. Tests
- [ ] 3.1 `dx12_rt` vs `embree` on every Tier 2b fixture and usage: hit/coverage evidence first, then maps, texel for texel
- [ ] 3.2 `dx12_rt` vs the private Painter CPU-bake goldens on the same fixtures
- [ ] 3.3 Repeatability: two runs on the same build and GPU byte-identical
- [ ] 3.4 Device without DXR Tier 1.1 (or the WARP adapter): explicit capability error, nothing published
- [ ] 3.5 Qualification report in `parity/reports/phase4/` with exception proposals for any divergence

## 4. Acceptance
- [ ] 4.1 Child acceptance met and reported to `phase4.3_dxr-baker`: `dx12_rt` qualified against Embree and the Painter goldens, or each divergence approved

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
