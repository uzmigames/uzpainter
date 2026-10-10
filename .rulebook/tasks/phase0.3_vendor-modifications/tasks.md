## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase0_owner-decisions, phase0.1_vendor-core-copy, phase0.2_vendor-thirdparty

## 2. Implementation
- [ ] 2.1 Create `thirdparty/uzengine-render-core/MODIFICATIONS.md` with the entry format of `13-engine-integration.md` §3.3 and the behaviours kept on purpose (`FatalErrorLoop`, `ShaderCompiler::Init` DLL directory) with their `path:line` at the selected commit
- [ ] 2.2 Add `build.zig.zon` pinning the Zig release and `build.zig` with a static-library target for the vendored subset (`-std=c++23 -DSPDLOG_COMPILED_LIB`, profiling defines undefined, include/library paths only inside the repository)
- [ ] 2.3 UZP-MOD-001: remove the DX11 and Metal branches and factory cases from `engine/rhi/rhi_factory.cpp`
- [ ] 2.4 UZP-MOD-002: remove `ResolveRHIConfig(const Config&)` from `engine/rhi/rhi_config.cpp` so that no `engine/config` or `engine/core/cvar` include remains; the backend is a caller-supplied parameter
- [ ] 2.5 UZP-MOD-003: deadline fence wait returning `signaled`, `timeout` or `device_lost` in `dx12_fence.*` and `vulkan_fence.*`
- [ ] 2.6 UZP-MOD-004: report the inline-ray-query capability in `dx12_device.*` only for DXR Tier 1.1 and SM 6.6
- [ ] 2.7 UZP-MOD-005: load the Agility SDK from the `D3D12\` subfolder in `dx12_device.cpp`, matching `D3D12SDKPath`
- [ ] 2.8 UZP-MOD-006: SPIR-V target environment `vulkan1.2` and the ray-query SPIR-V extension on request in `shader_compiler.cpp`
- [ ] 2.9 Add the Apache-2.0 §4(b) notice to every modified file and update `MANIFEST.json` (`status: modified`, modification ids, `vendored_sha256`)

## 3. Tests
- [ ] 3.1 Standalone build: the static-library target compiles and links under the pinned Zig on a machine without a UzEngine checkout; the build log shows no path outside the repository
- [ ] 3.2 UZP-MOD-001/002: the factory accepts only DX12 and Vulkan and rejects any other backend with an explicit error; no compiled source includes `engine/config` or `engine/core/cvar`
- [ ] 3.3 UZP-MOD-003: on each backend a never-signalled fence returns `timeout` within its deadline, a signalled fence returns `signaled`, and an injected device loss (DX12 `ID3D12Device5::RemoveDevice`; Vulkan `VK_ERROR_DEVICE_LOST` injected through the volk function table) returns `device_lost`
- [ ] 3.4 UZP-MOD-004: the capability decision reports inline ray queries for DXR Tier 1.1 + SM 6.6 and not for Tier 1.0 or SM below 6.6
- [ ] 3.5 UZP-MOD-005: with `D3D12Core.dll` in `D3D12\` beside the test executable the Agility runtime loads and reports the pinned SDK version
- [ ] 3.6 UZP-MOD-006: a compute kernel compiled to SPIR-V has the SPIR-V 1.5 header of `vulkan1.2`, and with ray queries requested it declares `SPV_KHR_ray_query` and the `RayQueryKHR` capability
- [ ] 3.7 Every modified file carries the §4(b) notice and a `MODIFICATIONS.md` entry naming its covering test

## 4. Acceptance
- [ ] 4.1 Child acceptance (contributes to P0-VENDOR): UZP-MOD-001…006 applied, noticed, logged and tested; the vendored subset builds standalone as a static library in UzPainter's own build with no UzEngine path

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
