# 01 — UzEngine Module Map and Standalone Linkability

Scope: which parts of `E:\UzmiGames\UzEngine` can be linked into a standalone, editor-less tool (UzPainter), how the modules depend on each other, and which entry points already exist for hosting the engine. Every claim is tagged **Fact** (read in source/docs), **Hypothesis** (inferred, not verified by running anything) or **Recommendation**.

Source root for all relative paths below: `E:\UzmiGames\UzEngine\`.

## 1. Repository layers

| Layer | Path | Language / build | Depends on Electron/VSCode? | Evidence |
|---|---|---|---|---|
| Runtime (engine) | `runtime/` | C++ compiled by Zig (`runtime/build.zig`), CMake mirror (`runtime/CMakeLists.txt`) | **No** — "Pure C++ with zero Node/N-API dependency" | **Fact** — `docs/engine/00-overview/03-project-structure.md` ("Why Three Layers"); `runtime/README.md` ("Standalone C++ static library. Consumed by demos, CLI tools, or the VSCode extension via N-API") |
| N-API bridge | `napi/` | C++ (MSVC via cmake-js), links `uzengine_runtime.lib` import lib of the DLL | Yes (Electron ABI) | **Fact** — `napi/CMakeLists.txt` lines 1-11, 36-44 |
| VSCode extension | `extension/` | TypeScript | Yes | **Fact** — `extension/src/runtime-client.ts` |
| MCP server | `mcp/` | TypeScript, `@modelcontextprotocol/sdk` | No, but also does not talk to the engine (see `08-mcp-and-ipc-patterns.md`) | **Fact** — `mcp/src/server.ts` |

UzPainter only needs the **Runtime** layer. The N-API and extension layers are reference material for hosting patterns only.

## 2. Engine module inventory (`runtime/engine/`)

**Fact** — directory listing of `runtime/engine/` and `runtime/engine/uzengine.h` (umbrella header). Purpose column comes from the headers read in this analysis; modules marked "not read" were only listed.

| Module | Path | Purpose | Needed by a texturing tool? |
|---|---|---|---|
| `rhi` | `engine/rhi/` (`rhi.h`, `rhi_types.h`, `rhi_device.h`, `rhi_command_list.h`, `rhi_backend.h`, `rhi_config.h`, `dx12/`, `dx11/`, `vulkan/`, `metal/`, `optimization/`) | Backend-agnostic GPU abstraction (buffers, textures, PSOs, compute, DXR, readback). | **Yes — core** |
| `shader` | `engine/shader/` (`shader_pipeline.h`, `shader_compiler.h` (DXC), `shader_compiler_fxc.h`, `shader_cache.h`, `shader_vfs.h`, `shader_reflection.h`, `slang_compiler.h`, `engine_shaders.h`) | HLSL → DXIL/DXBC/SPIR-V compilation at runtime, content-hash disk cache, embedded shader registry. | **Yes — core** (UzPainter will generate HLSL for compositing/baking) |
| `renderer` | `engine/renderer/` (`core/`, `frame/`, `scene/`, `passes/`, `render_graph/`, `mesh/`, `material/`, `upload/`, `raytracing/`, `ibl/`, `postprocess/`, `shadows/`, `gi/`, `atmosphere/`, …) | Deferred PBR scene renderer (`SceneRenderer`), render graph (`RgBuilder`), GPU mesh/texture upload, BLAS/TLAS managers, IBL, post-process, pass inspector / FLIP. | **Yes** for PBR preview and for RT infrastructure; most passes (atmosphere, GI, VFX) are dead weight for UzPainter |
| `material` | `engine/material/` (`material_graph.h`, `material_expression.h`, `compiler/hlsl_material_translator.h`, `material_baker.h`, `material_baker_gpu.h`, `material_manager.h`, `material_shader_cache.h`) | Node-graph material (`.uzmat`) → HLSL compiler, CPU/GPU bakers to RGBA8 textures. | **Yes** — closest existing analogue to a layer/procedural compositor |
| `asset` | `engine/asset/` (`vfs.h`, `asset_cache.h`, `import_sidecar.h`, `formats/` (`uztexture_format.h`, `uzmesh_format.h`, `pak_format.h`, `uzsdf_format.h`, `uzshader_format.h`), `importers/` (`texture_importer`, `mesh_importer` (glTF), `fbx_importer`, `png_codec`, `lightmap_uv_generator` (xatlas), `sdf_baker`, `shader_importer`), `mesh/` (`mikktspace_tangents`, `normal_smoother`, `packed_normal`)) | Cooked formats, importers, VFS, content-addressed cache. | **Yes** — defines the UzEngine export standard (`04-…`) and mesh import (`05-…`) |
| `app` | `engine/app/` (`runtime.h` C API, `runtime.cpp`, `application.h`, `engine_loop.h`, `project_loader.h`, `subsystem_registry.h`, `module_registry.h`, `time_manager.h`) | Lifecycle, `.uzproject` loading, extern "C" API used by N-API. | Partly — `runtime.h` is the hosting pattern to copy; `Application` not read in detail |
| `core` | `engine/core/` (`cvar.h`, `font_manager.h`, `sdf_font_atlas.h`, `lru_cache.h`, `simd_dispatch.h`) | CVars, fonts, SIMD dispatch. | CVars yes; fonts no |
| `job` | `engine/job/` (`job_system.h`: `JobSystem : ISubsystem`, lock-free `Enqueue`, `ParallelFor`) | Thread pool. | Yes (CPU-side export, compression) |
| `memory`, `containers`, `math`, `logging`, `assertions`, `profiling`, `paths`, `config`, `random`, `property`, `event` | leaf utilities | Allocators (`memory/allocators.h`), `Own<T>`/borrow checking, DirectXMath wrappers, `UZ_LOG`, Tracy profiling, exe-relative path resolution (`GetExeDir`), cascading `Config`. | Yes (transitively required) |
| `ipc` | `engine/ipc/` (`frame_readback.h`, `h264_encoder.h`) | Triple-buffered GPU→CPU readback and FFmpeg H.264 encoder. | `FrameReadback` yes; H.264 optional (human preview streaming) |
| `scripting` | `engine/scripting/` (`lua_vm.h`, `script_system.h`, `core/`, `scene/`, `renderer/`, `editor/`, `animation/`) | LuaJIT VM and `uz.*` bindings. | Optional (see `07-…` for Python discussion) |
| `ecs`, `animation`, `vfx`, `debug` | — | EnTT world, skeletal animation, GPU particles, RenderDoc capture. | `ecs` is required by `SceneRenderer` (it renders a `World`); `animation`/`vfx` not needed; `debug/renderdoc_capture.h` useful |
| `platform/` | `runtime/platform/windows/` (`platform_window.h`, `file_system.h`, `file_watcher.h`, `crash_handler.h`, `dll_loader.h`, `process.h`, `shared_memory.h`, `memory_mapped_file.h`, `native_dialogs.h`, …) | Win32 window, crash handler (minidumps), file watcher. | Window (hidden HWND for swapchain) and crash handler yes |
| `editor/` | `runtime/editor/` (`font/`, `gizmo/`, `grid/`, `input/`, `outline/`, `screenshot/`, `selection/`, `stats/`, `toolbar/`, `uzeditor.h`) | Editor overlays **and** `ScreenshotCapture` / `CompareGrid` / `ImageDiff`. | `screenshot/` yes (readback→PNG), rest no |

**Fact** — `editor.lib` is built unconditionally on Windows (`runtime/build.zig` lines ~1010-1050: `const editor_lib = blk: { … if (is_windows) { … b.addLibrary(.{ .name = "editor" …`), and the `-Deditor` option is currently consumed but unused (`_ = build_editor; // consumed: future use`). The CMake mirror compiles `editor/screenshot` into `uzengine_runtime` itself (`runtime/CMakeLists.txt` line 427).

**Fact** — `ScreenshotCapture` (readback→PNG/base64) lives in `runtime/editor/screenshot/screenshot_capture.h`, i.e. in `editor.lib`, not in `runtime.lib`. UzPainter must either link `editor.lib` or reimplement the ~100-line class on top of `IRHICommandList::CopyTextureToBuffer` + `PngCodec::EncodeMemory` (`engine/asset/importers/png_codec.h`).

## 3. Dependency rules and ordering

**Fact** — `docs/engine/00-overview/03-project-structure.md` ("Module Dependencies") and `docs/engine/03-rhi/01-overview.md` ("Rules"):

```
renderer/ → rhi, shader, math, memory
shader/   → rhi, paths, asset, logging
rhi/      → logging, assertions, paths, config
asset/    → logging, paths, config, containers
everything → logging, assertions
No circular dependencies. No d3d12.h/vulkan.h/metal.h above rhi/dx12, rhi/vulkan, rhi/metal.
```

**Fact** — Backend selection: `RHIDeviceDesc.backend` is chosen at runtime by `CreateRHIDevice(desc)` (`engine/rhi/rhi_backend.h` lines 28-64) from CLI/`.uzproject`/platform default (`engine/rhi/rhi_config.h`); the Zig build links `d3d12`, `d3d11`, `dxgi`, `dxguid` into the same library (`runtime/build.zig` lines 971-974) and Vulkan is loaded dynamically through volk (`runtime/thirdparty/README.md` "volk"). The docs' statement "compile-time selection only" (`docs/engine/03-rhi/01-overview.md` §3) refers to `UZ_BACKEND_*` compile guards; in practice one Windows binary contains DX12 + DX11 + Vulkan code paths (**Hypothesis** that all three are always compiled on Windows — `build.zig` line 106-108 in docs lists `addCppDir` for dx12, vulkan, metal(mac only); DX11 dir is linked per lines 972/1102).

## 4. How a standalone executable is built today (the UzPainter template)

**Fact** — `runtime/build.zig` lines 1300-1348: every tool in `{ "uzengine", "uzcook", "uzpack", "uzmesh" }` is built as

1. one `tools/<name>.cpp` translation unit,
2. plus `engine/rhi/dx12/dx12_agility.cpp` (Agility SDK export symbols — EXE only),
3. plus `engine/ecs/environment/*.cpp` compiled directly into the exe "to preserve static initializers for auto-registration",
4. linked against `runtime.lib` **and** `editor.lib` (`tool_exe.linkLibrary(lib); tool_exe.linkLibrary(editor_lib);`),
5. plus `luajit/src/lua51.lib`, `ffmpeg/lib/{avcodec,avutil,swscale}.lib`,
6. plus Win32 system libs `d3d12 d3d11 dxgi dxguid gdi32 user32 xinput1_4 ole32 shcore shell32 comdlg32`.

**Fact** — CMake mirror: `runtime/CMakeLists.txt` lines 676-684 globs `tools/*.cpp` and links each to `uzengine_runtime` (static).

**Fact** — Existing build artifacts on this machine (`runtime/build/bin/`, dated 2026-07-27): `uzengine.exe` (72.7 MB), `uzcook.exe` (33.1 MB), `uzmesh.exe` (20.0 MB), `uzpack.exe` (11.3 MB), `uzembed.exe`, `test_runtime.exe` (141 MB), plus DLLs `D3D12Core.dll`, `d3d12SDKLayers.dll`, `dxcompiler.dll`, `dxil.dll`, `d3dcompiler_47.dll`, `lua51.dll`, `avcodec-62.dll` (69.9 MB), `avutil-60.dll`, `swscale-9.dll`, `nvngx_dlss.dll` (65.5 MB); `runtime/build/lib/runtime.lib` (543 MB, debug) and `editor.lib` (17.6 MB). These are debug-configuration sizes (`zig build` default is `Debug`, `docs/engine/06-build-toolchain/05-build-configs.md`).

**Recommendation** — Model `UzPainter.exe` on the `uzengine.cpp` tool: one entry TU linking `runtime.lib` (+ `editor.lib` or a copied `ScreenshotCapture`), `dx12_agility.cpp`, and the system libs. Drop `ffmpeg` and DLSS linkage unless preview streaming is wanted (requires a UzPainter-owned build script, since `build.zig` hardwires them for all tools).

## 5. Existing engine entry points that matter for hosting

| Entry point | File | What it gives | Status |
|---|---|---|---|
| CLI runtime | `runtime/tools/uzengine.cpp` | Full pipeline: config → RHI → hidden/visible HWND → swapchain → `World` + `LooseFileVFS` + Lua → `SceneRenderer` → screenshot / pass-dump / diag / FLIP modes | **Fact** — implemented (1088 lines) |
| C API | `runtime/engine/app/runtime.h` / `runtime.cpp` | `uz_runtime_init`, `uz_create_viewport(parent_hwnd,w,h)`, `uz_render_frame`, `uz_load_scene`, entity/component JSON get/set, `uz_capture_screenshot` (PNG bytes), H.264 encode, input forwarding, log callback | **Fact** — implemented; used by `napi/` and by `runtime/tests/engine/app/test_runtime_api.cpp` |
| `Application` / `EngineLoop` | `runtime/engine/app/application.h`, `engine_loop.h` | Second app framework used by demos (`DemoApplication` referenced in `uzengine.cpp` comments) | Listed only; not read in detail — **not confirmed** which features it exposes |
| `SceneRenderer` | `runtime/engine/renderer/scene/scene_renderer.h` | `Init(device, PlatformWindow*, w, h)`, `RenderFrame(cmdList, swapChain, World*, IVFS*, dt, frame)`, `LoadMesh`, `LoadTexture`, `RequestScreenshot`, `GetPassInspector`, `GetDevice`, `GetShaderManager`, debug view modes | **Fact** — lines 162-815 |
| Raw RHI | `engine/rhi/*.h` | Device/command list/compute/readback without any renderer — proven by the FLIP mode in `uzengine.cpp` lines 361-482 (device + compute + readback, no window) | **Fact** |

## 6. Reuse verdict per module (for the architect)

| Verdict | Modules |
|---|---|
| Reuse as-is | `rhi` (all backends), `shader` (DXC pipeline + cache), `asset/formats` (`.uztexture`, `.uzmesh`, `.uzpak` writers/readers), `asset/importers/png_codec`, `texture_importer` (etcpak BC path), `asset/mesh/mikktspace_tangents`, `lightmap_uv_generator` (xatlas), `job`, `logging`, `paths`, `config`, `cvar`, `platform/windows` (window, crash handler, file watcher), `ipc/frame_readback`, `editor/screenshot`, `renderer/raytracing` (BLAS/TLAS/SBT), `renderer/upload` (staging ring, async decoder), `renderer/render_graph` |
| Reuse with extension | `renderer/scene/SceneRenderer` (needs an offscreen-target mode, see `02-…`), `material/*` (graph compiler + GPU baker need RGBA16F/arbitrary-pin output and texture inputs), `renderer/passes/postprocess/flip_pass` (perceptual diff for AI feedback), `renderer/mesh` (single UV set, see `05-…`) |
| Not needed | `vfx`, `animation`, `atmosphere`, `gi`, `editor/gizmo|grid|toolbar|outline|selection`, `ipc/h264_encoder` (optional), `napi/`, `extension/`, `mcp/` (docs search only) |
| Missing entirely | UV-space rasterization, baking shaders, dilation, layer compositor, noise library, GPU mip-gen, BC6H, Python, native MCP — see `09-gaps-and-risks.md` |
