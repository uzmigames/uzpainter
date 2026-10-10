# Origin of the vendored UzEngine render core

| Field | Value |
|---|---|
| Repository | UzEngine (UzmiGames), local clone `E:\UzmiGames\UzEngine`, branch `main` |
| Commit | `380c142e481d56fe16b045f63315b42359e86a7d` |
| Commit date | 2026-10-10T01:44:55-03:00 ("docs: add three reference images (WhatsApp, 2026-03-06/07)") |
| Upstream root | `runtime/` (paths in this folder are relative to it) |
| Files | 97 files, 28,128 lines, copied verbatim (`MANIFEST.json`); 12 of them since changed by the local modifications UZP-MOD-001…006 (`MODIFICATIONS.md`) |
| Licence | Apache-2.0, "Copyright 2026 Uzmi Games" (`LICENSE` = UzEngine root `LICENSE`, blob `57ff3b22d0e71b46b74de4e5b2e0bbb57a75c633`; `runtime/LICENSE` is the same blob) |
| Import date | 2026-10-10 |
| Importer | Rulebook task `phase0.1_vendor-core-copy`, run with `python -m tools.vendoring.import_core` for UzmiGames |

The commit is recorded for attribution and provenance only; it is not a dependency pin
(`docs/architecture/13-engine-integration.md` §1).

## How the files were taken

The files come from the commit object, never from a working tree (the UzEngine checkout had
uncommitted edits on the import date). `import_core` exports `LICENSE`, `runtime/engine` and
`runtime/platform` with `git -c core.autocrlf=false archive <commit>` into a staging folder outside
both repositories, checks that the git blob id of every exported subset file equals the commit's
tree entry (`git ls-tree`), runs the selection checks below, and copies the subset of §2.1 with
its upstream relative paths. The root `.gitattributes` marks this folder `-text` so checkouts keep
the bytes, and therefore the manifest hashes, unchanged.

## Selection (§3.1)

Candidates are the commits of `main`, newest first. The newest, `380c142e`, passed checks (a),
(b) and (d), so no older commit was needed. The subset files are unchanged from the PR #10 merge
`77b83813` to `380c142e` (the commits in between touch documentation and repository layout only).

| Check | Result at `380c142e` |
|---|---|
| Exported bytes = commit blobs | Pass: 97 of 97 blob ids equal the `git ls-tree` entries |
| (a) No conflict markers in the subset | Pass: none in the 97 files |
| (b) Include closure equals the subset | Pass, see below |
| (c) UzPainter build of the subset and hardware `selftest` | Build: pass on 2026-10-10 (`phase0.3_vendor-modifications`: the subset with UZP-MOD-001…006 compiles as the static library `uzrendercore` from UzPainter's `build.zig` under Zig 0.15.2 with `-std=c++23`, `tests/vendoring/test_modifications.py`). Hardware `selftest`: pending, confirmed by `phase0.6_toolchain-hardware-slice` |
| (d) Cited behaviours re-verified | Pass: all 31 citations hold at the line numbers below |
| UzEngine's own build and tests at the commit | Information only, not a gate: not run by this import (UzEngine is read-only for UzPainter and building it writes into its checkout) |

### Check (b): include closure

Computed by `tools/vendoring/closure.py`: every `#include` is followed textually (all
preprocessor branches) through the include directories of UzEngine's Windows build
(`runtime/build.zig`: the runtime root, `engine_include_dirs`, `windows_engine_include_dirs`,
`engine/rhi/dx12`, `engine/rhi/dx11`, `engine/rhi/vulkan`), adding the `.cpp` beside every reached
header, to a fixed point. `engine/asset/formats/uztexture_format.h` is header only (its `.cpp`, the
`.uztexture` writer, is not vendored, §2.4).

- Reached files: exactly the 97 files of `MANIFEST.json`.
- Includes not followed, because a planned local modification removes them (§2.2, §3.4):
  `engine/rhi/rhi_config.cpp` → `"config.h"` (UZP-MOD-002; would reach `engine/config/config.*`
  and `engine/core/cvar.*`); `engine/rhi/rhi_factory.cpp` → `"dx11/dx11_device.h"` and
  `"metal/metal_device.h"` (UZP-MOD-001; would reach `engine/rhi/dx11/*` and `engine/rhi/metal/*`).
  At the commit these three includes do not resolve in this folder; the modifications removed
  them, so the vendored files no longer contain them (`MODIFICATIONS.md`).
- Unresolved includes, all with an allowed origin:

| Origin | Headers |
|---|---|
| C/C++ standard library | algorithm, array, atomic, cassert, cctype, chrono, climits, cmath, cstddef, cstdint, cstdio, cstdlib, cstring, ctime, filesystem, functional, iomanip, memory, mutex, optional, sstream, string, string_view, thread, unordered_map, vector |
| Windows SDK | DbgHelp.h, dxgi1_6.h, dxgidebug.h, hidusage.h, shellapi.h, shellscalingapi.h, ShlObj.h, timeapi.h, unknwn.h, windows.h / Windows.h, windowsx.h, wrl/client.h, xinput.h |
| D3D12MA | D3D12MemAlloc.h, D3D12MemAlloc.cpp (included as a source by `engine/rhi/dx12/dx12_d3d12ma.cpp`) |
| DirectX-Headers / Agility SDK | d3d12.h, d3d12sdklayers.h, d3dx12.h |
| DXC | dxcapi.h |
| DirectXMath | DirectXMath.h |
| SPIRV-Reflect | spirv_reflect.h |
| spdlog | spdlog/spdlog.h, spdlog/sinks/rotating_file_sink.h, spdlog/sinks/stdout_color_sinks.h |
| Tracy (public headers) | tracy/Tracy.hpp, tracy/TracyD3D12.hpp, tracy/TracyVulkan.hpp |
| volk, VMA, Vulkan-Headers | volk.h, vk_mem_alloc.h, vulkan/vulkan.h |
| Linux/macOS system headers in `#elif defined(__linux__)` / `__APPLE__` branches, not built on Windows | unistd.h (`engine/paths/paths.cpp`), mach-o/dyld.h (`engine/paths/paths.cpp`), X11/Xlib.h (`engine/rhi/vulkan/vulkan_swapchain.cpp`) |

`wrl/client.h`, `hidusage.h`, `shellapi.h`, `unknwn.h` and `windowsx.h` are Windows SDK headers
not named in §2.2's list; they ship with the same SDK and need no DLL beyond the system ones.

### Check (d): re-verified behaviours

Paths relative to `runtime/` at `380c142e`. Each row is checked by
`tools/vendoring/citations.py` (line range plus a pattern that must occur in it). All line numbers
cited in `13-engine-integration.md` hold unchanged at this commit.

| § | Location | Behaviour |
|---|---|---|
| 2.2 | `engine/rhi/rhi_config.cpp:139` | `ResolveRHIConfig(const Config&)` pulls in engine config |
| 2.2 | `engine/rhi/rhi_factory.cpp:13-24` | Factory includes the DX11 and Metal backends |
| 2.2 | `engine/rhi/dx12/dx12_device.h:31` | Tracy D3D12 header included unconditionally |
| 2.2 | `engine/rhi/dx12/dx12_swapchain.cpp:15` | Tracy D3D12 header included unconditionally |
| 2.2 | `engine/profiling/profiler.h:49` | Profiling macros are stubs without `UZ_PROFILING_ENABLED` |
| 2.3 | `engine/rhi/dx12/dx12_command_list.cpp:887` | DX12 `CopyTextureToBuffer` |
| 2.3 | `engine/rhi/rhi_command_list.h:386-387` | Readback row pitch 256-byte aligned on DX12 |
| 2.3 | `engine/rhi/dx12/dx12_device.cpp:1036` | DX12 `MapBuffer` |
| 2.3 | `engine/rhi/vulkan/vulkan_command_list.cpp:1141` | Vulkan `CopyTextureToBuffer` |
| 2.3 | `engine/rhi/vulkan/vulkan_resources.cpp:157` | Vulkan `MapBuffer` |
| 2.3 | `engine/rhi/dx12/dx12_device.cpp:1558` | DX12 `CreateBLAS` |
| 2.3 | `engine/rhi/dx12/dx12_device.cpp:1691` | DX12 `CreateTLAS` |
| 2.3 | `engine/rhi/dx12/dx12_command_list.cpp:1093` | DX12 `BuildBLAS` |
| 2.3 | `engine/rhi/dx12/dx12_command_list.cpp:1131` | DX12 `BuildTLAS` |
| 2.3 | `engine/rhi/rhi_device.h:292-361` | RHI defaults return invalid handles; `SupportsRayTracing()` returns false |
| 2.3 | `engine/rhi/dx12/dx12_device.cpp:336` | Ray tracing reported for DXR Tier ≥ 1.0 only |
| 2.3 | `engine/rhi/dx12/dx12_device.cpp:1819` | DX12 `CreateRaytracingPipeline` (unused by UzPainter) |
| 2.3 | `engine/rhi/dx12/dx12_command_list.cpp:1176` | DX12 `DispatchRays` (unused by UzPainter) |
| 2.3 | `engine/rhi/dx12/dx12_pso_creation.cpp:172` | SM 6.6 bindless root signature |
| 2.3 | `engine/rhi/vulkan/vulkan_device.cpp:748-756` | Vulkan fixed layout, 16 slots per register class |
| 2.3 | `engine/rhi/vulkan/vulkan_device.cpp:532-562` | Vulkan descriptor indexing queried and logged only |
| 2.3 | `engine/shader/shader_reflection.h:3-5` | DXIL reflection not wired |
| 2.3 | `engine/rhi/dx12/dx12_fence.cpp:83-96` | DX12 fence waits forever, logging each watchdog period |
| 2.3 | `engine/rhi/dx12/dx12_fence.h:19` | Watchdog period 10 s |
| 2.3 | `engine/rhi/vulkan/vulkan_fence.cpp:93-100` | Vulkan fence gives up after 5 s and only logs |
| 3.4 | `engine/rhi/dx12/dx12_agility.cpp:17` | Exported `D3D12SDKPath = ".\\D3D12\\"` |
| 3.4 | `engine/rhi/dx12/dx12_device.cpp:419` | `TryLoadAgilitySdk` uses the executable folder itself |
| 3.4 | `engine/rhi/vulkan/vulkan_device.cpp:215` | Vulkan 1.2 instance requested |
| 3.4 | `engine/shader/shader_compiler.cpp:241` | SPIR-V target `vulkan1.3` |
| 3.4 | `engine/rhi/dx12/dx12_command_list.cpp:1068-1086` | `FatalErrorLoop` aborts after repeated RHI errors |
| 3.4 | `engine/shader/shader_compiler.cpp:122` | `ShaderCompiler::Init` sets the DLL directory to DXC's folder |

### Information outside checks (a)–(d)

At this commit `runtime/build.zig:35` compiles with `-std=c++17` plus the profiling defines
(`-DUZ_PROFILING_ENABLED -DTRACY_ENABLE -DTRACY_ON_DEMAND`), and `runtime/build.zig.zon` declares
`minimum_zig_version = "0.14.0"`. UzPainter's own build compiles the vendored subset with
`-std=c++23` under Zig 0.15.2, pinned exactly (`build.zig`, `build.zig.zon`; set by
`phase0.3_vendor-modifications`, which found the subset compiling and linking cleanly at that
level); `13-engine-integration.md` §4.2 records both.

## Licence and notices (§3.3)

- `LICENSE` is UzEngine's root `LICENSE` at the commit, byte for byte.
- No `NOTICE` file exists at the commit in the repository root, `runtime/`, `runtime/engine` or
  `runtime/platform`, so Apache-2.0 §4(d) adds no text. UzPainter's root `NOTICE` names this code,
  its copyright line and the commit.
- None of the 97 files carries a per-file licence or copyright header at the commit.
