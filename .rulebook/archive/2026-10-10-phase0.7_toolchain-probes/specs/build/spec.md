## ADDED Requirements

### Requirement: Vulkan availability probe
`selftest` MUST probe Vulkan through the system loader, create a Vulkan 1.2 instance when possible, record each physical device's API version, driver, extensions and features, and report an absent or too-old loader as `unavailable` with its reason; this probe SHALL NOT fail the G0 hardware slice.

#### Scenario: No Vulkan loader
Given a machine whose Vulkan loader is absent
When `selftest` runs
Then the Vulkan probe reports `unavailable` with the loader reason and the DX12 hardware slice result is unchanged

### Requirement: Ray-query capability probes
`selftest` MUST report inline-ray-query support on DX12 (DXR Tier 1.1 and SM 6.6) and on Vulkan (`VK_KHR_acceleration_structure`, `VK_KHR_deferred_host_operations`, `VK_KHR_ray_query`, features `accelerationStructure` and `rayQuery`), naming every missing item.

#### Scenario: Tier 1.0 adapter
Given a DX12 adapter that reports DXR Tier 1.0
When the DX12 ray-query probe runs
Then it reports inline ray queries unsupported and names the missing tier

#### Scenario: Owner's GPU recorded
Given the owner's machine
When the probes run
Then the DX12 and Vulkan ray-query results are recorded in `parity/reports/phase0/toolchain-probes.md`

### Requirement: WARP probe report
The WARP probe MUST complete and report supported capabilities, executed checks with results and an explicit reason for every unsupported item; a WARP failure SHALL leave the software path unsupported without failing G0, and only checks that passed on WARP MAY run in the hosted WARP lane.

#### Scenario: WARP check unsupported
Given a compute check that fails on the WARP adapter
When the WARP probe runs
Then the report lists that check as unsupported with its reason, the hosted WARP lane excludes it and `selftest` does not fail G0

### Requirement: Completion and qualification reported separately
Every probe result SHALL state separately whether the probe completed and whether the backend or feature is qualified.

#### Scenario: Probe completed, backend not qualified
Given a Vulkan device that lacks `VK_KHR_ray_query`
When the probes run
Then the report shows the probe as completed and the Vulkan ray-query path as not qualified
