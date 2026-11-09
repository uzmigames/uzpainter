# Vulkan — compute, readback, export and preview parity

## ADDED Requirements

### Requirement: Vulkan Compute Backend Behind Neutral Interfaces
The Vulkan backend SHALL implement the backend-neutral render interfaces (device, queue, resources, compute kernels, `TextureReadback`, UV raster, dilation, resampling, mip generation) so that compositor, export and preview code runs unchanged on DX12 or Vulkan, selected only by `--gpu-backend`.

#### Scenario: Same caller, other backend
Given a worker started with `--gpu-backend vulkan`
When the compositor evaluates a project and the export engine writes its maps
Then the same caller code MUST run on the Vulkan device and every receipt MUST record `backend: vulkan`

### Requirement: Vulkan Compute Deadline Waits
Every GPU wait on Vulkan MUST carry a deadline and SHALL return `signaled`, `timeout` or `device_lost`; `VK_ERROR_DEVICE_LOST` SHALL be reported as `device_removed {backend, reason}` and the job MUST fail without publishing a partial result.

#### Scenario: Injected device loss
Given a Vulkan worker running an export
When the test hook makes the device report `VK_ERROR_DEVICE_LOST`
Then the job MUST fail with `device_removed {backend: vulkan, reason}` and no export generation MUST be published

### Requirement: Vulkan Compute Capability Query
The Vulkan capability query SHALL report format and usage support, descriptor capacities and the VRAM budget (from `VK_EXT_memory_budget` when present, otherwise conservatively from heap sizes), and the tile admission budget SHALL be derived from it.

#### Scenario: No memory-budget extension
Given a Vulkan device without `VK_EXT_memory_budget`
When the worker starts
Then the reported budget MUST be derived from the heap sizes and a texture-set creation above it MUST fail explicitly

### Requirement: Vulkan Compute Selftest Slice
`UzPainter.exe selftest` SHALL run a Vulkan hardware slice (device creation, a compute kernel compiled to SPIR-V, readback, a 16-bit PNG write) and SHALL report it separately from the Vulkan availability probe.

#### Scenario: Owner's machine
Given the owner's machine with a Vulkan 1.2 capable GPU
When `selftest` runs
Then the Vulkan hardware slice MUST report pass, distinct from the probe result

### Requirement: Vulkan Compute Byte Equality With DX12
Readback drain tests and compositor kernels SHALL behave identically on both backends, and the Tier 0 subset and every exported map of Wand v1, Belt v5 and Tunic v10 MUST be byte-equal on Vulkan and DX12; a non-zero difference MUST pass only as an owner-approved exception in `parity/exceptions.json`.

#### Scenario: Tunic v10 on both backends
Given the Tunic v10 project rebuilt at the same revision
When it is exported once on DX12 and once on Vulkan
Then every decoded map MUST be equal at native depth, and any differing texel MUST fail the comparison unless an approved exception names that map and backend pair

#### Scenario: Readback drain on Vulkan
Given several readback requests in flight on the Vulkan device
When the engine thread shuts down
Then every request MUST complete or be released and the outcome MUST match the DX12 drain test

### Requirement: Vulkan Compute Preview Path
The `painter_viewport` forward pass and its captures SHALL run on Vulkan with regression goldens that are repeatable for a fixed build, adapter and driver; the viewport MUST NOT be used as parity evidence.

#### Scenario: Viewport capture on Vulkan
Given a Vulkan worker and the pilot wand project
When `capture` runs twice in `painter_viewport` mode with the same camera and size
Then both captures MUST be byte-identical and the receipt MUST record the Vulkan backend, adapter and driver
