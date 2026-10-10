## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase3.1_vulkan-compute-parity

## 2. Implementation
- [ ] 2.1 Enable `VK_KHR_acceleration_structure`, `VK_KHR_deferred_host_operations` and `VK_KHR_ray_query` with the `accelerationStructure` and `rayQuery` features at device creation when present; record their absence otherwise
- [ ] 2.2 Implement the RHI BLAS/TLAS create and build calls on Vulkan (build-size query, scratch buffers, build commands) behind the existing interface, replacing the invalid-handle defaults
- [ ] 2.3 Add acceleration-structure descriptors to the Vulkan descriptor layout so a compute kernel can bind a TLAS
- [ ] 2.4 Add descriptor-indexing bindless on Vulkan for sampled textures, keeping Phase 1 kernels on the fixed-slot subset
- [ ] 2.5 Make `SupportsRayTracing()` and the capability query report inline ray queries per backend with the list of missing extensions, features or tiers
- [ ] 2.6 Emit SPIR-V with `SPV_KHR_ray_query` from DXC for kernels that request ray queries (UZP-MOD-006 option, `vulkan1.2` target)
- [ ] 2.7 Write the backend-neutral acceleration-structure builder for UzPainter meshes: real vertex stride, per-geometry opacity flag, raw RHI `CreateBLAS`, same calls on DXR and Vulkan
- [ ] 2.8 Log UZP-MOD-007 in `MODIFICATIONS.md` with modification markers in every touched vendored file; keep Apache-2.0 headers
- [ ] 2.9 Extend `selftest` with the Vulkan ray-query qualification slice (build a BLAS/TLAS, trace one inline query, read back the hit) reported separately from the availability probe
- [ ] 2.10 Author the ray-cast fixtures under `parity/manifests/`: plane, sphere and bevelled cube meshes, an opaque/non-opaque geometry pair and a fixed ray set (hits, misses, grazing rays, edge and vertex hits)
- [ ] 2.11 Write the ray-cast kernel (inline `RayQuery`, identical HLSL for DXIL and SPIR-V) writing one record per ray: hit flag, instance id, primitive id, barycentrics, hit distance
- [ ] 2.12 Write the cross-backend ray-cast comparison: per-fixture counts of differing records by field, max |Δ| of distance and barycentrics, list of every differing ray
- [ ] 2.13 Add Vulkan ray-query entries to the capability manifest (`capabilities.json`) with their tier evidence

## 3. Tests
- [ ] 3.1 Unit tests: BLAS/TLAS build on Vulkan for each ray-cast fixture mesh; rebuild after a vertex change; invalid input rejected
- [ ] 3.2 Capability tests: a device without `VK_KHR_ray_query` reports unavailable with the missing list and no work is dispatched
- [ ] 3.3 Repeatability: the ray-cast kernel run twice on each backend gives byte-identical records
- [ ] 3.4 Cross-backend run of every ray-cast fixture on DXR and Vulkan on the owner's GPU; report every difference
- [ ] 3.5 `selftest` Vulkan ray-query slice green on the owner's machine

## 4. Acceptance
- [ ] 4.1 Acceptance: ray-cast fixtures compared with DXR and every difference reported; any divergence covered by an owner-approved exception; Vulkan ray-query slice green

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
