## ADDED Requirements

### Requirement: GPU Baker Backends Qualified Separately
Each `GpuBaker` backend (`dx12_rt`, `vulkan_rt`) MUST be qualified on its own against the Embree outputs and the Painter goldens, and SHALL be marked `supported` only when its outputs are equal or every divergence is covered by an owner-approved exception.

#### Scenario: One backend fails qualification
Given `dx12_rt` qualifies and `vulkan_rt` differs from Embree on the AO of the bevelled cube without an approved exception
When the capability manifest is regenerated
Then `dx12_rt` is `supported` and `vulkan_rt` is listed as a gap with its report

### Requirement: GPU Baker Is Optional
The GPU baker SHALL NOT be a prerequisite for importing mesh maps, stack operations, native baking with `embree` or any gate.

#### Scenario: No ray-tracing GPU
Given a machine without DXR Tier 1.1 or Vulkan ray query
When a project imports mesh maps, edits its stack and bakes with `embree`
Then every operation succeeds and only a `GpuBaker` request fails with an explicit capability error

### Requirement: Same Bake Contract On Every Backend
All baker backends SHALL accept the same `BakeRequest` and write a `BakeReceipt` that names the backend, its version and the GPU.

#### Scenario: Receipts name the backend
Given one `BakeRequest` run on `embree`, `dx12_rt` and `vulkan_rt`
When the three receipts are compared
Then their settings hashes are equal and `tools.backend` is `embree`, `dx12_rt` and `vulkan_rt` respectively
