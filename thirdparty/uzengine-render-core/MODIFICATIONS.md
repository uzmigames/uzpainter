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

## UZP-MOD-008 — IEEE-strict arithmetic on request

| Field | Value |
|---|---|
| Id | UZP-MOD-008 |
| Files | `engine/shader/shader_compiler.h`, `engine/shader/shader_compiler.cpp` |
| Reason | capability |
| Description | New `ShaderCompileDesc::ieeeStrict`: DXC is passed `-Gis`, so DXIL floating-point instructions carry no fast-math flags and SPIR-V arithmetic is decorated `NoContraction`. UzPainter's generated kernels are compiled with it (`src/render/kernel_cache.cpp`): their outputs must be byte-identical on DX12 and Vulkan (`docs/architecture/04-layer-stack-and-compositing.md` §7), and without `-Gis` DXC marks every DXIL float operation `fast` and leaves SPIR-V contraction to the driver. |
| Upstream behaviour | `engine/shader/shader_compiler.h:84-95` has no request for IEEE-strict arithmetic; `engine/shader/shader_compiler.cpp:261-263` is the last code-generation flag `BuildArguments` passes, and `-Gis` is never passed |
| Date | 2026-10-10 |
| Author | UzmiGames (rulebook task `phase1.1_core-device-kernels`) |
| Covering test | `tests/vendoring/test_modifications.py::test_ieee_strict_arithmetic` |

## UZP-MOD-009 — 16-bit unorm color formats

| Field | Value |
|---|---|
| Id | UZP-MOD-009 |
| Files | `engine/rhi/rhi_types.h`, `engine/rhi/dx12/dx12_texture_creation.cpp`, `engine/rhi/dx12/dx12_command_list.cpp`, `engine/rhi/vulkan/vulkan_format_helpers.h` |
| Reason | capability |
| Description | New `RHIFormat` values `R16Unorm`, `RG16Unorm` and `RGBA16Unorm`, appended after `D32FloatS8Uint` so the values of the existing formats are unchanged. `BytesPerTexel` gives 2, 4 and 8 bytes; textures are created as, and copy footprints use, `DXGI_FORMAT_R16_UNORM`, `DXGI_FORMAT_R16G16_UNORM` and `DXGI_FORMAT_R16G16B16A16_UNORM` on DX12 and `VK_FORMAT_R16_UNORM`, `VK_FORMAT_R16G16_UNORM` and `VK_FORMAT_R16G16B16A16_UNORM` on Vulkan. UzPainter holds `L16`/`RGB16` channels and 16-bit mesh maps natively on the GPU and reads them back without conversion (`src/render/texture_readback.*`); FP16 is never a substitute for 16-bit unorm storage (`docs/architecture/04-layer-stack-and-compositing.md` §7). |
| Upstream behaviour | `engine/rhi/rhi_types.h:166-205` declares no 16-bit unorm color format (`D16Unorm` is depth only); `engine/rhi/rhi_types.h:262-263` sizes no such format; `engine/rhi/dx12/dx12_texture_creation.cpp:59-60` and `engine/rhi/dx12/dx12_command_list.cpp:882-883` map every format after `BC7Srgb` to `DXGI_FORMAT_UNKNOWN`; `engine/rhi/vulkan/vulkan_format_helpers.h:53-54` maps it to `VK_FORMAT_UNDEFINED` |
| Date | 2026-10-10 |
| Author | UzmiGames (rulebook task `phase1.2_core-readback`) |
| Covering test | `tests/render/test_core_readback.py::test_exact_native_formats` |

## UZP-MOD-010 — Crash reports and the log file at any path

| Field | Value |
|---|---|
| Id | UZP-MOD-010 |
| Files | `platform/windows/crash_handler.cpp`, `platform/windows/crash_handler.h`, `engine/logging/log.cpp`, `engine/logging/log.h` |
| Reason | defect |
| Description | The path arguments of `CrashHandler_SetCrashDir` and `LogInit` are UTF-8, and both open their files through the UTF-16 form, so a folder outside the ANSI code page works. The crash handler keeps the directory as UTF-16 (`MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS)`; a directory that is not UTF-8 or does not fit in `MAX_PATH` UTF-16 units is refused with an error log and the executable folder stays the default, instead of being truncated) and builds and creates the report folder and the `crash.dmp`, `crash.txt` and `crash.json` files with `swprintf`, `GetModuleFileNameW`, `CreateDirectoryW` and `CreateFileW`, still on stack buffers only. `LogInit` hands the rotating file sink the native (UTF-16) form of the UTF-8 path; spdlog takes UTF-16 file names only with `SPDLOG_WCHAR_FILENAMES`, which UzPainter's `build.zig` defines for every C++ unit, and `log.cpp` refuses to compile on Windows without it. The default log path is read with `_wgetenv` and returned as UTF-8, and `LogGetFilePath` returns UTF-8. Before, UzPainter had to narrow its paths with `std::filesystem::path::string()`, which throws `filesystem_error` for a character outside the ANSI code page, so a worker whose `--crash-dir`, or a `selftest` whose `--out-dir` or `%LOCALAPPDATA%`, lay outside it ended in an uncaught exception (`parity/reports/phase2/practical-e2e.md` B2 review). |
| Upstream behaviour | `platform/windows/crash_handler.cpp:59` keeps the directory in a `char` buffer; `platform/windows/crash_handler.cpp:579-587` copies the ANSI path into it, truncated at `MAX_PATH`; `platform/windows/crash_handler.cpp:416-452` builds the report folder in `char` buffers and creates it with `CreateDirectoryA` (the default with `GetModuleFileNameA`); `platform/windows/crash_handler.cpp:110-113`, `platform/windows/crash_handler.cpp:143-146` and `platform/windows/crash_handler.cpp:263-266` create the three files with `CreateFileA`; `engine/logging/log.cpp:133-134` opens the file sink with the narrow path (spdlog `_fsopen`, ANSI); `engine/logging/log.cpp:63` reads the default folder with `std::getenv`; `engine/logging/log.cpp:99` narrows the default path with `path::string()` |
| Date | 2026-10-13 |
| Author | UzmiGames (practical end-to-end fixes, group cli-unicode, branch `wt/e2e-cli`) |
| Covering test | `tests/supervisor/test_worker_pipe.py::test_crash_reports_go_to_a_crash_dir_outside_the_code_page`, `tests/toolchain/test_selftest.py::test_out_dir_outside_the_code_page` |

## UZP-MOD-011 — Vulkan submission results readable

| Field | Value |
|---|---|
| Id | UZP-MOD-011 |
| Files | `engine/rhi/vulkan/vulkan_command_list.h`, `engine/rhi/vulkan/vulkan_command_list.cpp`, `engine/rhi/vulkan/vulkan_fence.h`, `engine/rhi/vulkan/vulkan_fence.cpp` |
| Reason | defect |
| Description | `VulkanCommandList::Execute` and `VulkanFence::Signal` keep the `VkResult` of their `vkQueueSubmit`, read back through the new `VulkanCommandList::LastSubmitResult()` and `VulkanFence::LastSignalResult()` (`VK_SUCCESS` before the first call); a `Signal` on an uninitialised fence records `VK_ERROR_INITIALIZATION_FAILED`. The log lines stay. The `IRHICommandList` and `IRHIFence` interfaces are unchanged: UzPainter's Vulkan queue (`src/render/vulkan_backend.cpp`, decision 310) reads the results after each submission and fails the submission with `device_removed` (`VK_ERROR_DEVICE_LOST`) or `request_failed` (any other error) instead of reporting it later as a timeout, or as a success when the fence signal went through after the command buffer was refused. |
| Upstream behaviour | `engine/rhi/vulkan/vulkan_command_list.cpp:270-273` only logs a failed `vkQueueSubmit`; `engine/rhi/vulkan/vulkan_fence.cpp:77-80` only logs a failed signal submission; `engine/rhi/vulkan/vulkan_fence.cpp:63` returns silently from a signal on an uninitialised fence |
| Date | 2026-10-19 |
| Author | UzmiGames (rulebook task `phase3.1_vulkan-compute-parity`, decision 310, branch `wt/vk-qual`) |
| Covering test | `tests/vendoring/test_modifications.py::test_vulkan_submission_results_are_readable` |

## UZP-MOD-012 — Vulkan 1.2 entry points, extended storage-image formats

| Field | Value |
|---|---|
| Id | UZP-MOD-012 |
| Files | `engine/rhi/vulkan/vulkan_command_list.cpp`, `engine/rhi/vulkan/vulkan_device.cpp` |
| Reason | defect |
| Description | The command list records its barriers with `vkCmdPipelineBarrier2KHR` and its render passes with `vkCmdBeginRenderingKHR` / `vkCmdEndRenderingKHR`, the entry points of the `VK_KHR_synchronization2` and `VK_KHR_dynamic_rendering` extensions the device enables. The instance asks for Vulkan 1.2, so the core 1.3 names (`vkCmdPipelineBarrier2`, `vkCmdBeginRendering`, `vkCmdEndRendering`) are outside the effective API version and `vkGetDeviceProcAddr` need not resolve them; volk loads the core and the KHR names separately, without aliasing. `vkCreateDevice` also enables `shaderStorageImageExtendedFormats` when the device supports it, so a shader may declare an extended storage-image format such as `R16f` (SPIR-V capability `StorageImageExtendedFormats`). UzPainter's qualification (`src/render/vulkan_qualification.cpp`, decision 310) requires the feature and checks that the KHR entry points resolve on the created device before anything is submitted. |
| Upstream behaviour | `engine/rhi/vulkan/vulkan_command_list.cpp:860` records barriers with the core 1.3 `vkCmdPipelineBarrier2`; `engine/rhi/vulkan/vulkan_command_list.cpp:1333` begins rendering with the core 1.3 `vkCmdBeginRendering`; `engine/rhi/vulkan/vulkan_device.cpp:499-501` enables only `fillModeNonSolid` and `samplerAnisotropy` |
| Date | 2026-10-19 |
| Author | UzmiGames (rulebook task `phase3.1_vulkan-compute-parity`, decision 310, branch `wt/vk-qual`) |
| Covering test | `tests/vendoring/test_modifications.py::test_vulkan_entry_points_match_the_enabled_extensions` |

## Behaviours kept on purpose

- `DX12CommandList::FatalErrorLoop` still aborts the process after repeated RHI errors
  (`engine/rhi/dx12/dx12_command_list.cpp:1068-1086`). The worker process boundary contains the
  abort (`docs/architecture/02-runtime-topology.md` §1).
- `ShaderCompiler::Init` still sets the process DLL directory to DXC's folder
  (`engine/shader/shader_compiler.cpp:122`). DXC sits beside the executable (`13-…` §5), so the
  directory is the executable's own.

UZP-MOD-007 (Vulkan acceleration structures, ray queries, descriptor-indexing bindless) is
planned for `phase3.3_vulkan-backend-ray-tracing` and not applied yet.
