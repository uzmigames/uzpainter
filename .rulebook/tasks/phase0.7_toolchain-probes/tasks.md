## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase0.5_vendor-render-core, phase0.6_toolchain-hardware-slice

## 2. Implementation
- [ ] 2.1 Probe report model: per probe `{probe, backend, adapter, driver, completed, qualified, supported[], executed_checks[], unsupported[{item, reason}]}`, written by `selftest` in machine-readable form
- [ ] 2.2 Vulkan availability probe: load the system loader through volk, create a Vulkan 1.2 instance, enumerate physical devices with API version, driver, extensions and features (buffer device address, descriptor indexing, `VK_EXT_memory_budget`); report an absent or too-old loader as `unavailable` with its reason
- [ ] 2.3 DX12 ray-query probe: `RaytracingTier ≥ D3D12_RAYTRACING_TIER_1_1` and highest shader model ≥ 6.6 through the vendored capability check, listing each missing feature by name
- [ ] 2.4 Vulkan ray-query probe: `VK_KHR_acceleration_structure`, `VK_KHR_deferred_host_operations`, `VK_KHR_ray_query` and the `accelerationStructure`/`rayQuery` features, listing each missing item by name
- [ ] 2.5 WARP probe: create the DX12 device on the WARP adapter and attempt each compute-path check of the hardware slice (DXIL compute compile and dispatch, readback, 16-bit PNG), recording supported capabilities, executed checks with results and a reason for each unsupported item; emit the list of WARP-qualified checks for the hosted WARP lane
- [ ] 2.6 Exit policy: Vulkan and WARP probe outcomes never fail the G0 hardware slice; an incomplete probe is reported as `probe not completed` with its error
- [ ] 2.7 Run the probes on the owner's machine and publish `parity/reports/phase0/toolchain-probes.md` with adapter, driver, OS build and every probe result

## 3. Tests
- [ ] 3.1 Loader-absent test: with the Vulkan loader hidden from the process, the Vulkan probe reports `unavailable` with the loader reason and `selftest` still passes the DX12 hardware slice
- [ ] 3.2 Missing-feature test: with a capability source reporting DXR Tier 1.0 (or SM 6.5), the DX12 ray-query probe reports unsupported and names the missing item
- [ ] 3.3 WARP report test: the WARP probe report contains supported capabilities, executed checks and an explicit reason for every unsupported item, and the hosted WARP lane list contains only checks that passed
- [ ] 3.4 Report separation test: the report distinguishes `completed` from `qualified` for every probe

## 4. Acceptance
- [ ] 4.1 Child acceptance (contributes to P0-TOOLCHAIN): Vulkan availability, DX12 and Vulkan ray-query and WARP probes completed and reported on the owner's machine; Vulkan/WARP failure leaves the path unsupported without failing G0

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
