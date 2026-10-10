## ADDED Requirements

### Requirement: DX12 GPU Baker Qualification
The `dx12_rt` backend MUST produce outputs equal to `embree` and to the private Painter goldens on the whole Tier 2b corpus, or each divergence SHALL be covered by an owner-approved exception before the backend is marked `supported`.

#### Scenario: Curvature differs without exception
Given `dx12_rt` curvature on the wand pair differs from `embree` in some texels and no approved exception exists
When the qualification report is produced
Then `dx12_rt` stays an explicit gap and the report lists the affected texel count and an exception proposal

#### Scenario: Equal on the analytic fixtures
Given the analytic plane, sphere and bevelled cube
When `dx12_rt` and `embree` bake all ten usages
Then hit/coverage evidence and maps are equal texel for texel

### Requirement: DX12 GPU Baker Feature Gate
The `dx12_rt` backend SHALL require DXR Tier 1.1 and SM 6.5 `RayQuery`, SHALL use compute kernels with inline ray queries only, and MUST raise an explicit capability error on a device without them.

#### Scenario: Tier 1.0 device
Given a device reporting DXR Tier 1.0
When a `dx12_rt` bake is requested
Then the request fails before dispatch naming DXR Tier 1.1 as missing

### Requirement: DX12 GPU Baker Repeatability
The `dx12_rt` backend SHALL produce byte-identical outputs for the same request on the same build and GPU.

#### Scenario: Two runs
Given one `BakeRequest` on the hat pair
When it runs twice on `dx12_rt` on the owner's GPU
Then the maps and receipts' map hashes are identical
