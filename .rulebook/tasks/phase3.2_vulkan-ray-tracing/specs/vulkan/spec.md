# Vulkan — ray tracing (UZP-MOD-007)

## ADDED Requirements

### Requirement: Vulkan Ray Tracing Acceleration Structures
The Vulkan backend SHALL create and build bottom- and top-level acceleration structures through `VK_KHR_acceleration_structure` and `VK_KHR_deferred_host_operations` behind the same RHI calls the DX12 backend implements, and SHALL bind a top-level structure to a compute kernel through an acceleration-structure descriptor.

#### Scenario: Build and bind on Vulkan
Given a Vulkan 1.2 device exposing the acceleration-structure and ray-query extensions
When UzPainter builds a BLAS and a TLAS for the sphere ray-cast fixture and binds the TLAS to a compute kernel
Then the RHI MUST return valid handles and the kernel MUST read the structure without validation errors

### Requirement: Vulkan Ray Tracing Inline Ray Queries
Kernels that use inline ray queries SHALL be compiled from the same HLSL to DXIL and to SPIR-V with `SPV_KHR_ray_query`, and SHALL run as compute shaders on both backends without any ray-tracing pipeline, shader table or `VK_KHR_ray_tracing_pipeline`.

#### Scenario: Same kernel on both backends
Given the ray-cast kernel source
When it is compiled for DX12 and for Vulkan
Then both builds MUST come from the same HLSL file and neither MUST require a ray-tracing pipeline object

### Requirement: Vulkan Ray Tracing Capability Reporting
The capability query SHALL report inline ray-query support per backend (DX12: DXR Tier 1.1 and SM 6.6; Vulkan: `VK_KHR_acceleration_structure`, `VK_KHR_deferred_host_operations`, `VK_KHR_ray_query` with features `accelerationStructure` and `rayQuery`) together with every missing item, and a missing item MUST yield an explicit unavailable result before any work, never a fallback.

#### Scenario: Missing ray-query extension
Given a Vulkan device without `VK_KHR_ray_query`
When a ray-query workload is requested
Then the request MUST fail before dispatch with the backend and the missing extension named, and no software or viewport fallback MUST run

### Requirement: Vulkan Ray Tracing Mesh Acceleration Structures
UzPainter's acceleration-structure builder SHALL use the real vertex stride of its own vertex buffers and a per-geometry opacity flag, and MUST NOT use the vendored scene-level ray-tracing managers.

#### Scenario: Non-default stride and non-opaque geometry
Given a mesh whose vertex stride differs from 48 bytes and a geometry marked non-opaque
When the builder creates its BLAS on either backend
Then the BLAS MUST be built with that stride and that opacity flag, and ray queries MUST hit the triangles at their authored positions

### Requirement: Vulkan Ray Tracing Cross-Backend Ray-Cast Report
The ray-cast fixtures SHALL run with the same kernel on DXR and on Vulkan, every per-ray difference (hit flag, instance id, primitive id, barycentrics, hit distance) SHALL be reported, and a non-zero difference MUST pass only as an owner-approved exception in `parity/exceptions.json`.

#### Scenario: Differing ray record
Given the bevelled-cube ray-cast fixture run on DXR and on Vulkan
When one ray's primitive id differs between the backends
Then the report MUST list that ray and field, and the fixture MUST fail unless an approved exception names it

### Requirement: Vulkan Ray Tracing Selftest Slice
`UzPainter.exe selftest` SHALL include a Vulkan ray-query qualification slice that builds an acceleration structure, traces an inline query and reads back the hit, reported separately from the Vulkan availability probe.

#### Scenario: Owner's GPU
Given the owner's machine with a GPU and driver exposing Vulkan ray query
When `selftest` runs on that machine
Then the ray-query slice MUST report pass, and the availability probe result MUST be reported as a separate line
