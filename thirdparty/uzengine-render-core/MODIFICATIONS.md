# Local modifications of the vendored UzEngine render core

Log of every change UzPainter made to the files copied from UzEngine commit
`380c142e481d56fe16b045f63315b42359e86a7d` (`ORIGIN.md`), in the format of
`docs/architecture/13-engine-integration.md` §3.3. Paths are relative to this folder, which is
UzEngine's `runtime/` folder; upstream line numbers are those of the selected commit.

Each modified file starts with the Apache-2.0 §4(b) notice naming its ids, and its
`MANIFEST.json` entry has `status: modified`, the same ids and the current `vendored_sha256`.
`python -m tools.vendoring.modifications` updates those manifest entries from this log and
reports any disagreement between the log, the manifest, the notices and the covering tests;
`tests/vendoring/test_modifications.py` runs the same checks, re-verifies every `path:line`
below against the selected commit, and runs the covering tests.

## UZP-MOD-001 — Factory trimmed to DX12 and Vulkan

| Field | Value |
|---|---|
| Id | UZP-MOD-001 |
| Files | `engine/rhi/rhi_factory.cpp` |
| Reason | trim |
| Description | The DX11 and Metal includes and factory cases are removed; DX12 and Vulkan are the only backends `CreateRHIDevice` builds. Any other backend reaches the default case, which now logs `CreateRHIDevice: backend <name> is not supported (DX12 and Vulkan only)` and returns `nullptr`. |
| Upstream behaviour | `engine/rhi/rhi_factory.cpp:13-24` includes `dx11/dx11_device.h` and `metal/metal_device.h`; `engine/rhi/rhi_factory.cpp:50-59` creates a DX11 device; `engine/rhi/rhi_factory.cpp:73-87` handles Metal; `engine/rhi/rhi_factory.cpp:89-92` logs an unknown backend only as a number |
| Date | 2026-10-10 |
| Author | UzmiGames (rulebook task `phase0.3_vendor-modifications`) |
| Covering test | `tests/vendoring/test_modifications.py::test_factory_accepts_only_dx12_and_vulkan` |

## UZP-MOD-002 — No engine config or CVar resolution

| Field | Value |
|---|---|
| Id | UZP-MOD-002 |
| Files | `engine/rhi/rhi_config.cpp`, `engine/rhi/rhi_config.h` |
| Reason | trim |
| Description | `ResolveRHIConfig(const Config&)`, its declaration, the `Config` forward declaration, the parsing helpers only it used and the `config.h` and `profiler.h` includes are removed. The caller fills `RHIConfig::backend` itself (UzPainter: `--gpu-backend`, `docs/architecture/02-runtime-topology.md` §1) and converts it with `ToDeviceDesc`. No source of the subset includes `engine/config` or `engine/core/cvar`. |
| Upstream behaviour | `engine/rhi/rhi_config.cpp:8` includes `config.h`; `engine/rhi/rhi_config.cpp:139-189` resolves the backend from the command line, `.uzproject` and CVars; `engine/rhi/rhi_config.cpp:77-133` holds the parsing helpers only that function uses; `engine/rhi/rhi_config.h:15` forward-declares `Config`; `engine/rhi/rhi_config.h:67` declares `ResolveRHIConfig` |
| Date | 2026-10-10 |
| Author | UzmiGames (rulebook task `phase0.3_vendor-modifications`) |
| Covering test | `tests/vendoring/test_modifications.py::test_no_engine_config_or_cvar_include`, `tests/vendoring/test_modifications.py::test_factory_accepts_only_dx12_and_vulkan` |

## UZP-MOD-003 — Bounded, truthful fence wait

| Field | Value |
|---|---|
| Id | UZP-MOD-003 |
| Files | `engine/rhi/rhi_fence.h`, `engine/rhi/dx12/dx12_fence.h`, `engine/rhi/dx12/dx12_fence.cpp`, `engine/rhi/vulkan/vulkan_fence.h`, `engine/rhi/vulkan/vulkan_fence.cpp` |
| Reason | defect |
| Description | `IRHIFence::WaitCPU(value)` becomes `WaitCPU(value, deadline)` returning `FenceWaitResult {status, backendReason}` with status `Signaled`, `Timeout` or `DeviceLost`. DX12 checks the device-removed reason before the completed value (a removed device reports `UINT64_MAX`), waits on the event only until the deadline, polls until the deadline if the event cannot be used, and returns `DeviceLost` with `GetDeviceRemovedReason`. Vulkan waits with `vkWaitSemaphores` for the time left until the deadline, resumes a driver timeout that comes early, and returns `DeviceLost` with the `VkResult` (`VK_ERROR_DEVICE_LOST`) on an error; a wait on an uninitialised fence returns `DeviceLost` with `VK_ERROR_INITIALIZATION_FAILED`. The interface header changes because both backends share the result type. `DX12Device::WaitIdle` (`dx12_device.cpp`) keeps its own watchdog wait; it is not the fence wait. |
| Upstream behaviour | `engine/rhi/rhi_fence.h:56` declares a wait with no deadline and no result; `engine/rhi/dx12/dx12_fence.cpp:72-74` reads a removed device's `UINT64_MAX` as signalled; `engine/rhi/dx12/dx12_fence.cpp:76-81` returns silently when `SetEventOnCompletion` fails; `engine/rhi/dx12/dx12_fence.cpp:83-96` waits forever, logging every `engine/rhi/dx12/dx12_fence.h:19` period of 10 s; `engine/rhi/vulkan/vulkan_fence.cpp:85` returns silently on an uninitialised fence; `engine/rhi/vulkan/vulkan_fence.cpp:93-100` gives up after 5 s and only logs, device loss included |
| Date | 2026-10-10 |
| Author | UzmiGames (rulebook task `phase0.3_vendor-modifications`) |
| Covering test | `tests/vendoring/test_modifications.py::test_fence_wait_is_bounded_and_truthful` |

## UZP-MOD-004 — Inline ray queries need DXR Tier 1.1 and SM 6.6

| Field | Value |
|---|---|
| Id | UZP-MOD-004 |
| Files | `engine/rhi/dx12/dx12_device.h`, `engine/rhi/dx12/dx12_device.cpp` |
| Reason | defect |
| Description | New `DX12SupportsInlineRayQuery(tier, highestShaderModel)`: true only for DXR Tier 1.1 or higher and a device shader model of 6.6 or higher. `DX12Device` records the highest shader model the device reports (before negotiation or a forced override) and exposes `SupportsInlineRayQuery()`. `SupportsRayTracing()` keeps meaning DXR Tier 1.0 or higher, the level acceleration structures need. |
| Upstream behaviour | `engine/rhi/dx12/dx12_device.cpp:336` reports ray tracing for DXR Tier 1.0 or higher; `engine/rhi/dx12/dx12_device.h:183` is the only ray-tracing capability query |
| Date | 2026-10-10 |
| Author | UzmiGames (rulebook task `phase0.3_vendor-modifications`) |
| Covering test | `tests/vendoring/test_modifications.py::test_inline_ray_query_decision` |

## UZP-MOD-005 — Agility SDK from the `D3D12` subfolder

| Field | Value |
|---|---|
| Id | UZP-MOD-005 |
| Files | `engine/rhi/dx12/dx12_device.cpp` |
| Reason | defect |
| Description | `TryLoadAgilitySdk` creates the device factory for, and loads `D3D12Core.dll` from, the `D3D12` subfolder of the executable directory, the folder the exported `D3D12SDKPath` names and the distribution uses (`docs/architecture/13-engine-integration.md` §5). |
| Upstream behaviour | `engine/rhi/dx12/dx12_agility.cpp:17` exports `D3D12SDKPath = ".\\D3D12\\"`; `engine/rhi/dx12/dx12_device.cpp:419` uses the executable folder itself |
| Date | 2026-10-10 |
| Author | UzmiGames (rulebook task `phase0.3_vendor-modifications`) |
| Covering test | `tests/vendoring/test_modifications.py::test_agility_runtime_loads_from_d3d12_subfolder` |

## UZP-MOD-006 — SPIR-V for Vulkan 1.2, ray-query extension on request

| Field | Value |
|---|---|
| Id | UZP-MOD-006 |
| Files | `engine/shader/shader_compiler.h`, `engine/shader/shader_compiler.cpp` |
| Reason | defect |
| Description | SPIR-V is compiled with `-fspv-target-env=vulkan1.2` (SPIR-V 1.5), the version of the instance the Vulkan device requests. New `ShaderCompileDesc::enableRayQuery`: for SPIR-V output it passes `-fspv-extension=SPV_KHR_ray_query`, so the module declares that extension and the `RayQueryKHR` capability. |
| Upstream behaviour | `engine/shader/shader_compiler.cpp:241` targets `vulkan1.3`; `engine/shader/shader_compiler.h:10` documents that target; `engine/rhi/vulkan/vulkan_device.cpp:215` requests a Vulkan 1.2 instance |
| Date | 2026-10-10 |
| Author | UzmiGames (rulebook task `phase0.3_vendor-modifications`) |
| Covering test | `tests/vendoring/test_modifications.py::test_spirv_targets_vulkan_1_2_with_ray_query` |

## Behaviours kept on purpose

- `DX12CommandList::FatalErrorLoop` still aborts the process after repeated RHI errors
  (`engine/rhi/dx12/dx12_command_list.cpp:1068-1086`). The worker process boundary contains the
  abort (`docs/architecture/02-runtime-topology.md` §1).
- `ShaderCompiler::Init` still sets the process DLL directory to DXC's folder
  (`engine/shader/shader_compiler.cpp:122`). DXC sits beside the executable (`13-…` §5), so the
  directory is the executable's own.

UZP-MOD-007 (Vulkan acceleration structures, ray queries, descriptor-indexing bindless) is
planned for `phase3.3_vulkan-backend-ray-tracing` and not applied yet.
