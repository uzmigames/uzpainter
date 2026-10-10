## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase1.4_render-core-layer, phase2.10_pilot-tunic-recovery

## 2. Implementation
- [ ] 2.1 Implement the Vulkan device/queue wrapper behind `src/render/backend.h` on the vendored Vulkan backend (Vulkan 1.2 instance), selected only by `--gpu-backend vulkan`
- [ ] 2.2 Qualify the deadline wait on Vulkan (UZP-MOD-003): `signaled`, `timeout`, `device_lost`; map `VK_ERROR_DEVICE_LOST` to `device_removed {backend, reason}`
- [ ] 2.3 Run generated compositor kernels as SPIR-V through the shared kernel cache (cache key includes the target), within the fixed-slot descriptor subset
- [ ] 2.4 Implement `TextureReadback` on Vulkan: per-request ownership, aligned row pitch, fence-linked map, drain on shutdown and on failure
- [ ] 2.5 Port the UV raster pass, dilation (jump-flood), resampling and mip generation to Vulkan with the same HLSL sources
- [ ] 2.6 Implement the Vulkan capability query: format/usage support, descriptor capacities, VRAM budget from `VK_EXT_memory_budget` or conservatively from heap sizes; derive the tile admission budget from it
- [ ] 2.7 Run the export engine and the `painter_viewport` forward pass and capture on Vulkan; record `backend`, adapter and driver in every export and capture receipt
- [ ] 2.8 Add the Vulkan hardware slice to `selftest` (device, compute kernel from SPIR-V, readback, PNG16 write) reported separately from the availability probe
- [ ] 2.9 Write the cross-backend comparison mode of the comparison tool: same project and revision rendered on DX12 and Vulkan, decoded maps compared at native depth with the `14-parity-testing.md` §4 diagnostics
- [ ] 2.10 Add Vulkan backend entries to `capabilities.json` with their tier evidence

## 3. Tests
- [ ] 3.1 Readback drain tests on Vulkan (`tests/render/`): in-flight requests drained on shutdown, failed request releases its staging memory, pitch alignment for every supported format
- [ ] 3.2 Unit tests on synthetic meshes (plane, sphere, bevelled cube) for UV raster, dilation, resampling and mips on Vulkan, byte-equal to the DX12 results
- [ ] 3.3 Compositor kernel tests on both backends with identical outputs for every implemented node kind, blend mode and channel format
- [ ] 3.4 Device-loss and stall injection on Vulkan: `device_removed` or `timeout` reported, job fails, no partial result published
- [ ] 3.5 Tier 0 subset (compositor and export goldens implemented through `phase1.14_compositor-core` and `phase1.18_export-engine`) on Vulkan: equal to the private goldens and byte-equal to DX12
- [ ] 3.6 Tier 1 for Wand v1, Belt v5 and Tunic v10 on Vulkan: every exported map byte-equal to DX12 and to the private goldens
- [ ] 3.7 `painter_viewport` regression goldens recorded on Vulkan and repeatable across two runs
- [ ] 3.8 `selftest` Vulkan hardware slice green on the owner's machine

## 4. Acceptance
- [ ] 4.1 Acceptance: `selftest` hardware slice green on Vulkan; Tier 0 subset and the three pilot Tier 1 maps byte-equal on Vulkan and DX12; any divergence covered by an owner-approved exception

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
