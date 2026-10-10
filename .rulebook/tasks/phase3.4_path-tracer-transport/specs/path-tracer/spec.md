# Path tracer — light transport, scene, display and capture

## ADDED Requirements

### Requirement: Transport Identical Kernels On Both Backends
`painter_iray` SHALL run as compute kernels with inline ray queries compiled from one HLSL source to DXIL (DXR Tier 1.1, SM 6.6) and SPIR-V (`VK_KHR_ray_query`), and MUST NOT use shader tables, DXR pipeline state objects or `VK_KHR_ray_tracing_pipeline`.

#### Scenario: Same fixture on DX12 and Vulkan
Given the white-furnace fixture
When it is captured once with `--gpu-backend dx12` and once with `--gpu-backend vulkan`
Then both captures MUST come from the same kernel source and every receipt MUST name its backend, adapter and driver

### Requirement: Transport Clean-Room Light Transport
The transport SHALL be unidirectional path tracing with next-event estimation, multiple importance sampling between BSDF and environment sampling, environment importance sampling from a piecewise-constant 2D distribution, Russian roulette after a fixed minimum depth, the maximum depth fitted in Phase 0 and Owen-scrambled Sobol sampling under a fixed seed, each formula traceable to an entry of the approved-source index recorded in `parity/semantics/iray.json`.

#### Scenario: White furnace with Lambert
Given a Lambert sphere of known albedo under a constant environment
When it is rendered at two sample counts
Then the mean signed error against the analytic radiance MUST be consistent with zero given its standard error at both counts

### Requirement: Transport Deterministic Accumulation
Each pixel SHALL accumulate exactly `samples` samples in a fixed order without floating-point atomics, and repeatability for a given build, adapter, driver, seed and sample count MUST be measured and reported rather than assumed.

#### Scenario: Repeat render
Given a fixture, a seed and a sample count
When it is rendered twice on the same machine and backend
Then the report MUST state whether the bytes are identical and list any differing pixels

### Requirement: Transport Explicit Unavailability
A missing ray-tracing feature MUST yield `PathTracerUnavailable{backend, missing}` before any work; there SHALL be no fallback to `painter_viewport`, no software path tracer, and WARP output MUST never count as Tier 3 evidence.

#### Scenario: Device without ray query
Given a device lacking DXR Tier 1.1 or `VK_KHR_ray_query`
When a client requests `capture` with `mode=painter_iray`
Then the call MUST fail with `PathTracerUnavailable` naming the backend and missing items, and no image MUST be written

### Requirement: Transport Headless Capture And Receipt
`display.capture` with `mode=painter_iray` SHALL wait for evaluation of the current revision and all uploads, render offscreen into an RGBA32F accumulation without a window, apply the project's display transform, read back through `TextureReadback`, write PNG and linear EXR, and write a receipt `{revision, evaluator_profile, render_state_digest, mode, backend, adapter, driver, samples, seed, camera, size, display_configuration, hashes}`.

#### Scenario: Capture with no window
Given a worker started without `--preview`
When `capture` runs with `mode=painter_iray`, a camera, a size, `samples` and `seed`
Then the PNG, the EXR and a receipt with every listed field MUST be written and no window MUST be created

### Requirement: Transport Display Configuration Preserved
The display transform SHALL preserve the project's colour-management mode: Legacy `Linear` (linear to sRGB per IEC 61966-2-1, values above 1 clamped) or `ACES`, or OCIO with the project's pinned config and recorded view; an unsupported configuration, including ACE mode until qualified, MUST fail before rendering.

#### Scenario: ACE-mode project
Given a project created in ACE colour-management mode
When a `painter_iray` capture is requested
Then it MUST fail with an explicit unsupported-configuration error before any rendering work

### Requirement: Transport Environment Identity
Environments SHALL be resolved by SHA-256 from the project with exposure, rotation and dome from the display preset, and a missing environment MUST be an explicit error, never a substitute.

#### Scenario: Missing environment bytes
Given a display preset naming an environment hash the project does not contain
When a `painter_iray` capture is requested
Then it MUST fail with an explicit missing-environment error and no other environment MUST be used
