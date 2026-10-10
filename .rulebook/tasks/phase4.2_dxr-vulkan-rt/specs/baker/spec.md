## ADDED Requirements

### Requirement: Vulkan GPU Baker Qualification
The `vulkan_rt` backend MUST produce outputs equal to `embree` and to the private Painter goldens on the whole Tier 2b corpus, or each divergence SHALL be covered by an owner-approved exception before the backend is marked `supported`.

#### Scenario: Equal AO on the hat pair
Given the hat low/high/cage pair
When `vulkan_rt` and `embree` bake AO with the same request
Then hit/coverage evidence and the AO map are equal texel for texel

### Requirement: Vulkan GPU Baker Feature Gate
The `vulkan_rt` backend SHALL require Vulkan 1.2 or later with `VK_KHR_acceleration_structure`, `VK_KHR_deferred_host_operations` and `VK_KHR_ray_query` enabled, SHALL use compute kernels with inline ray queries only, and MUST raise an explicit capability error when any is missing.

#### Scenario: No ray query extension
Given a Vulkan device without `VK_KHR_ray_query`
When a `vulkan_rt` bake is requested
Then the request fails before dispatch naming the missing extension

### Requirement: Vulkan And DX12 GPU Bakes Compared
Every difference between `vulkan_rt` and `dx12_rt` outputs on the same fixtures SHALL be reported; a cross-backend difference passes only as an owner-approved exception.

#### Scenario: Cross-backend difference reported
Given `vulkan_rt` and `dx12_rt` normal bakes of the bevelled cube that differ in some texels
When the cross-backend report runs
Then it lists the differing texel count and max difference, and neither backend is marked qualified for that usage without an approved exception
