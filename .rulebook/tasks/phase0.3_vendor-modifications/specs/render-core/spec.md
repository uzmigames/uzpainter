## ADDED Requirements

### Requirement: Marked and logged local modifications
Every vendored file changed by UzPainter MUST carry the Apache-2.0 §4(b) notice naming its `MODIFICATIONS.md` id, original UzEngine path and commit, and MUST have a `MODIFICATIONS.md` entry citing the upstream behaviour as `path:line` with a covering test.

#### Scenario: Modified fence file is marked
Given UZP-MOD-003 changes `engine/rhi/dx12/dx12_fence.cpp`
When the file is inspected
Then its first lines carry the notice with id UZP-MOD-003 and the original path and commit, and `MANIFEST.json` lists it as `modified` with that id

### Requirement: Bounded and truthful GPU waits
The vendored fence wait on DX12 and Vulkan SHALL return `signaled`, `timeout` or `device_lost` within the caller's deadline and MUST NOT wait forever or give up silently.

#### Scenario: Unsignalled fence times out
Given a fence that is never signalled and a deadline of one second
When the worker waits on it
Then the wait returns `timeout` within the deadline on both backends

#### Scenario: Device loss reported
Given a device removed through `ID3D12Device5::RemoveDevice` on DX12 or a `VK_ERROR_DEVICE_LOST` result on Vulkan
When the wait runs
Then it returns `device_lost` with the backend's reason

### Requirement: Correct capability and target reporting
The DX12 device MUST report the inline-ray-query capability only for DXR Tier 1.1 with SM 6.6, the Agility SDK SHALL load from the `D3D12\` subfolder only, and SPIR-V SHALL target `vulkan1.2`.

#### Scenario: Tier 1.0 device has no ray queries
Given a DX12 adapter that reports DXR Tier 1.0
When UzPainter queries the capability
Then inline ray queries are reported unsupported

#### Scenario: SPIR-V matches the Vulkan 1.2 instance
Given a compute kernel compiled to SPIR-V with ray queries requested
When its module header and extensions are read
Then the version is the SPIR-V 1.5 of `vulkan1.2` and `SPV_KHR_ray_query` is declared

### Requirement: Standalone static library in UzPainter's build
The vendored subset MUST compile as a static library from UzPainter's own `build.zig` under the pinned Zig release, with no `runtime.lib`, submodule, or include or library path outside the UzPainter repository, and without the DX11, Metal, engine-config or CVar code.

#### Scenario: Build without a UzEngine checkout
Given a machine with the UzPainter repository and no UzEngine checkout
When the static-library target is built
Then the build succeeds and its log contains no path outside the repository
