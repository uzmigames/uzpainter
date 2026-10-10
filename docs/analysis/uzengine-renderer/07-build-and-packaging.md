# 07 — Build System, Toolchain, Scripting Layer and Standalone Packaging

Scope: how UzEngine is built, how standalone executables are produced, what must ship next to the exe, how shaders are embedded, what the scripting layer is, and what this implies for a single-folder `UzPainter.exe`. Paths relative to `E:\UzmiGames\UzEngine\`.

**Baseline** (added after the Astra review, see `10-review-response.md`): line numbers refer to UzEngine `HEAD 19ffb9b` (2026-07-27; `build.zig` 1502 lines, `CMakeLists.txt` 732 lines). The working tree is mid-merge with `9220973` (`build.zig` 1640 lines, `CMakeLists.txt` 1132 lines) and contains unresolved C++/HLSL conflict markers, so it is not a buildable baseline as it stands. Nothing was built for this analysis.

## 1. Build systems and compilers

| Item | Finding | Tag / evidence |
|---|---|---|
| Primary build | Zig build (`runtime/build.zig`, 1502 lines); `zig build` → `runtime/build/{bin,lib,generated}`; targets `test`, `run`, `cook`, `pack` | **Fact** — `build.zig` lines 1376-1392; `.rulebook/decisions/001-zig-as-primary-build-system-with-cmake-mirror.md`; `docs/engine/06-build-toolchain/01-zig-build-system.md` |
| Mirror build | CMake ≥3.21 (`runtime/CMakeLists.txt`, 732 lines); presets `msvc-debug/release` (Visual Studio 17 2022 x64) and `clang-debug/release` (Ninja + clang-cl) | **Fact** — `runtime/CMakePresets.json` |
| Verified compilers | README badges: Zig 0.15, MSVC 17.14, Clang 21; `scripts/build.ps1 --compiler=zig|msvc|clang` | **Fact** that the project claims it (`README.md`, `scripts/build.ps1` lines 9-13); not re-verified here |
| C++ standard actually used | `build.zig` global `cpp_flags = -std=c++17 …` (line 23-24) with one `-std=c++20` TU (line 674: etcpak's `bc7enc.cpp`, which needs `<bit>`, comment at line 659); CMake `CMAKE_CXX_STANDARD 20` (line 15); README badge says C++23 | **Fact** — discrepancy; plan UzPainter code for C++17/20-compatible subsets if it compiles into the same library graph, or build UzPainter with its own flags and link `runtime.lib` |
| Global defines | `-DSPDLOG_COMPILED_LIB -DUZ_PROFILING_ENABLED -DTRACY_ENABLE -DTRACY_ON_DEMAND -DSPNG_STATIC` | **Fact** — `build.zig` line 24 |
| Optimisation levels | Zig `Debug` (default), `ReleaseSafe`, `ReleaseFast`, `ReleaseSmall`; the docs say release strips `UZ_CHECK/UZ_ENSURE` and disables the debug layer and Tracy | **Fact** that the docs say so (`docs/engine/06-build-toolchain/05-build-configs.md`). The Tracy part is **contradicted by source**: `build.zig` passes `-DTRACY_ENABLE -DTRACY_ON_DEMAND` in every mode (line 24 global flags, line 575 TracyClient). The `UZ_CHECK` and debug-layer parts were not checked in source |
| Source discovery | `addCppDir(mod, dir)` globs `.cpp` per directory — "drop a .cpp in the right directory" | **Fact** — `docs/engine/06-build-toolchain/01-zig-build-system.md` |
| Thirdparty acquisition | `scripts/setup.ps1` downloads/extracts libraries; LuaJIT is prebuilt with `scripts/build_luajit.bat` (MSVC `msvcbuild.bat`) → `thirdparty/luajit/src/lua51.lib` + `lua51.dll` | **Fact** — `build.zig` line 328 comment; `runtime/thirdparty/README.md` luajit |
| Tests | GoogleTest `test_runtime.exe` run from `build/bin` ("~3600 tests" per `runtime/README.md`); CI gates described in `AGENTS.md` | **Fact** |

## 2. Outputs and how tools are linked

**Fact** — `runtime/build.zig`:

- `runtime.lib` (static, all engine modules + compiled thirdparty) — line 921 `b.addLibrary(...)`.
- `editor.lib` (grid, fonts, stats, screenshot, compare grid, gizmos) — built unconditionally on Windows (lines ~1010-1050).
- `-Ddll=true` → `uzengine_runtime.dll` + MSVC-compatible import lib; `runtime.cpp` recompiled with `-DUZ_BUILDING_DLL=1` so `UZ_API` = `__declspec(dllexport)` on every `uz_*` function (lines 1053-1153). The DLL "carries its own libc++" so an MSVC host links only the C ABI (`docs/engine/06-build-toolchain/04-napi-bridge.md`).
- Tools (`uzengine`, `uzcook`, `uzpack`, `uzmesh`): one `.cpp` each + `dx12_agility.cpp` + `engine/ecs/environment/*.cpp` + `lua51.lib` + FFmpeg import libs, linked to `runtime.lib` + `editor.lib` + Win32 libs `d3d12 d3d11 dxgi dxguid gdi32 user32 xinput1_4 ole32 shcore shell32 comdlg32` (lines 1300-1348).
- Demos live in `runtime/demos/<name>/build.zig` and depend on `demos/common/build_common.zig`; never registered in the main build (`docs/engine/06-build-toolchain/03-tools.md` "Rules").

**Fact** — DLL/file deployment by `b.addInstallBinFile` (lines 1395-1425): `D3D12Core.dll`, `d3d12SDKLayers.dll` (installed at the `bin/` root; `dx12_agility.cpp` exports a `D3D12SDKPath` that points to a `D3D12` subfolder next to the exe (line 17), but `DX12Device::Init` also calls `TryLoadAgilitySdk()` (`dx12_device.cpp` line 185), which loads the SDK programmatically from `GetExeDir()` through `ID3D12SDKConfiguration1::CreateDeviceFactory` (lines 334-424). The path mismatch alone therefore does not prove a startup failure; which route activates on a given Windows build, and the fallback when neither does, is **not confirmed** without running it), `dxcompiler.dll`, `dxil.dll`, `d3dcompiler_47.dll`, `lua51.dll`, `nvngx_dlss.dll`; FFmpeg DLLs are copied by the N-API CMake step (`napi/CMakeLists.txt` lines 73-93) and are present in `runtime/build/bin/` on this machine (`avcodec-62.dll`, `avutil-60.dll`, `swscale-9.dll`). At HEAD `build.zig` does not install them; the incoming merge adds a Zig step that copies them (working tree `build.zig` lines 1508-1536) and installs `content/atmosphere` engine data (lines 1488-1497). Optional `uz_brixelizer.dll` when present (`build.zig` lines 833-870).

**Fact** — Runtime-created folders: shader bytecode cache under `cache/shaders/<backend>/` (`shader_pipeline.h` line 60; `docs/runtime/asset-loading.md`), `.screenshots/` for pass dumps, `native/crashes/` for minidumps in library mode (`docs/engine/32-engine-mode/05-viewport-integration.md`).

### 2.1 Minimum file set for a single-folder UzPainter distributable (derived)

| File | Required? | Why |
|---|---|---|
| `UzPainter.exe` (links `runtime.lib` + `editor.lib` or equivalent) | yes | — |
| `D3D12Core.dll`, `d3d12SDKLayers.dll` (debug only) | yes for SM6.6 on Win10 | Agility SDK export in `dx12_agility.cpp` (subfolder) and programmatic `CreateDeviceFactory` from the exe directory (`dx12_device.cpp`); verify the chosen route |
| `dxcompiler.dll`, `dxil.dll` | yes | shaders are compiled from embedded HLSL at runtime (see §3) |
| `d3dcompiler_47.dll` | only for SM5/DX11 fallback | FXC |
| `lua51.dll` | yes while LuaJIT is linked (tools link `lua51.lib` import lib) | `build.zig` line 1333 |
| `avcodec-62.dll`, `avutil-60.dll`, `swscale-9.dll` | only if H.264 preview streaming is kept | FFmpeg import libs are hard-linked for all tools today (`build.zig` lines 1335-1337) — needs a UzPainter-specific build script to drop |
| `nvngx_dlss.dll` | no (upscaler, LoadLibrary at runtime, graceful fallback) | `thirdparty/README.md` DLSS |
| `uz_brixelizer.dll` | no | GI only |
| `cache/` (created) | — | writable location needed next to exe or redirected |

**Recommendation** — Create `UzPainter/build.zig` (or a CMake target) that mirrors the tool recipe but omits FFmpeg/DLSS/Brixelizer and `ecs/environment` serializers it does not need; use `-Doptimize=ReleaseFast`; ship the Agility SDK + DXC DLLs. **Hypothesis:** exe + 4-6 DLLs plus any engine content folders. The real file set needs the final dependency closure of a `SceneRenderer`-hosting exe (dropping an import library does not prove its dependent symbols are unused), and "standalone" must be defined as one file or one folder.

## 3. Shader embedding and compilation at runtime

**Fact**:

- `uzembed.exe` (`runtime/tools/uzembed.cpp`) converts every `.hlsl` under `runtime/shaders/` into `build/generated/shaders/<name>.hlsl.gen.h` (`constexpr char kXxxVS[]`) plus `engine_shaders.gen.h` (`enum class EngineShader`, `EngineShaders::GetSource/GetName`); the runtime library build depends on this step (`build.zig` lines 191-222, 927-938 "Shader integrity check"). Decision record: `.rulebook/decisions/005-embedded-shaders-via-uzembed-build-tool.md`.
- `.hlsli` includes are embedded too (the shader VFS resolves them from the embedded set — **Hypothesis**; `shader_vfs.h`/`shader_source_manager.h` not read in detail).
- Embedded source is compiled on first use by DXC (SM6.x → DXIL, `-spirv` for Vulkan) or FXC (SM5.0 → DXBC), both dynamically loaded; results cached by content hash on disk (`docs/engine/05-shader-pipeline/03-compilation.md`, `04-cache.md`).
- Count: 124 `.hlsl` + 36 other shader files under `runtime/shaders/` (runtime + editor) — **Fact** (`find` output: 160 files, 124 `.hlsl`).
- A "Ship" mode with a sealed `shaders.uzpak` and no DXC is described in `docs/engine/05-shader-pipeline/01-overview.md`; implementation status **not confirmed** (the deployed tools ship `dxcompiler.dll`, so assume runtime compilation).

**Implication for UzPainter** — Generated compositing/baking HLSL can be fed to `ShaderPipeline::LoadBytecodeFromSource(name, source)` at runtime exactly like the material graph does; static UzPainter shaders can be added to the embed step by dropping files into a shaders directory scanned by `uzembed`.

## 4. Scripting layer today (LuaJIT) and where Python fits

**Fact** — `.rulebook/decisions/002-luajit-2-1-with-sandboxed-per-entity-scripting.md`; `engine/scripting/lua_vm.h`; `docs/engine/15-scripting/*`:

- Singleton `LuaVM` (`Init/Shutdown/LoadScript/PCall/UpdateFrameGlobals`), sandbox strips `os`, `io`, `load`, `require`, `collectgarbage`; per-entity environments with `__index = _G`.
- System pointers (World, VFS, SceneRenderer, InputSystem, editor state) are stored in `LUA_REGISTRYINDEX` and read by binding modules (`LuaSetWorld`, `LuaSetVFS`, `LuaSetSceneRenderer`, …; `uzengine.cpp` lines 638-741).
- API tables: `uz.scene`, `uz.camera`, `uz.input`, `uz.time`, `uz.math`, `uz.quat`, `uz.renderer` (render path, debug modes, screenshot, upscaler), `uz.debug`, `uz.mesh`/`uz.texture` (load from VFS), `uz.cvar`, `uz.pass_inspector`, `uz.scene.set_material/get_material`, atmosphere/fog/light/decal/vfx bindings (`engine/scripting/*/lua_*_api.h`).
- Rule: "every C++ feature MUST have a corresponding Lua binding (API parity rule)" (decision 002).
- No Python, pybind11 or CPython integration in `runtime/thirdparty/` directory names, `runtime/build.zig`, `runtime/CMakeLists.txt` or `runtime/engine/` (**Fact** within that search scope; not a claim that the repository has no Python scripts and not a sandbox security audit).

**Options for a Python layer (Recommendation, not design)**:

| Option | Mechanism already in the tree | Effort | Notes |
|---|---|---|---|
| A. Python over a C API DLL (`ctypes`/`cffi`) — **in-process** | `zig build -Ddll=true` → `uzengine_runtime.dll` with `extern "C"` `uz_*` (`runtime.h`); the N-API addon shows the DLL host pattern | Low | UzPainter would expose its own `uzp_*` C API. The DLL runs inside the Python process: a GPU/driver crash takes Python down too, so this gives **no** crash isolation |
| A2. Python client + UzPainter worker process (RPC over stdio/pipe) | the extension forks a worker for crash containment (`extension/src/runtime-client.ts` line 411, `child_process.fork`); the CLI prefixed-JSON protocol (`08-…` §2.4) | Medium | process isolation; needs a job/state protocol (`08-…` §5) |
| B. Embedded CPython inside `UzPainter.exe` | none; would be a new thirdparty (CPython + pybind11/nanobind) | Medium–High (MSVC CRT vs Zig/mingw ABI concerns like FFX 1.1.4 needed a wrapper DLL — `build.zig` lines 833-845) | Mirror the Lua registry-pointer pattern for subsystem access |
| C. Keep LuaJIT alongside | already linked | None | Useful for parity with engine scenes; not a Substance-style Python API |

## 5. Hosting pattern reference (N-API) — what to copy, what to avoid

**Fact** — `docs/engine/06-build-toolchain/04-napi-bridge.md`: runtime as DLL, C ABI only across the Zig↔MSVC boundary, `NAPI_DISABLE_CPP_EXCEPTIONS`, delay-load hook, all DLLs copied beside the addon, `uz_set_engine_dir()` to relocate DLL/shader discovery when the host exe is not the engine exe. `napi/src/render_thread.h` moves `uz_render_frame()` to a dedicated thread with resize requests queued and applied at frame start. The C API header requires `uz_runtime_init`/`uz_create_viewport` on the main thread and `uz_render_frame` on the thread that created the viewport (`runtime.h` lines 6-11, 224), while `render_thread.h` calls `uz_render_frame` only from its own thread (lines 13-19); how the addon reconciles the two was not traced, so these comments do not establish an all-call thread-ownership protocol. `extension/src/runtime-client.ts` isolates the addon in a forked worker process for crash containment.

**Recommendation** — For UzPainter's own process these translate to: one render/GPU thread owning the device and command lists, a command queue for CPU-side requests (MCP/Python), explicit `uz_set_engine_dir`-style resource root, SEH + minidump handler from `platform/windows/crash_handler.h`. SEH inside one process and a separate worker process are different containment mechanisms; only the second survives a driver crash.

## 6. Risks specific to build and packaging

| Risk | Evidence | Mitigation |
|---|---|---|
| Debug binaries are huge (`runtime.lib` 543 MB, `uzengine.exe` 72 MB, `test_runtime.exe` 141 MB) | `runtime/build/bin`, `build/lib` listings | Use `ReleaseFast`; measure |
| Tools hard-link FFmpeg and LuaJIT | `build.zig` lines 1333-1337 | UzPainter-owned build recipe |
| Windows-only tooling (`uzcook.cpp` `#ifdef _WIN32`), DX12-only DXR | `uzcook.cpp` line 29; `03-…` §6 | Accept Windows x64 target |
| C++17 vs C++23 expectation mismatch | `build.zig` line 24; README | Decide standard per target; `runtime.lib` ABI is Clang/libc++ (Zig) — mixing with MSVC-built UzPainter code requires the DLL/C-ABI route (`04-napi-bridge.md` "LNK1143") |
| LuaJIT must be prebuilt with MSVC even on the Zig path | `build.zig` line 328 | Keep `setup.ps1`/`build_luajit.bat` in the UzPainter bootstrap or drop Lua |
| Agility SDK activation: the EXE export points to `D3D12/` while Zig installs `D3D12Core.dll` at the root; a programmatic `CreateDeviceFactory` route from the exe directory also exists | `build.zig` 1398-1402; `dx12_agility.cpp` line 17; `dx12_device.cpp` lines 185, 334-424 | Document both routes and verify the distributable against the chosen one |
