# 02 — Headless / Offscreen Rendering and CPU Readback Today

Scope: how a frame gets rendered without a visible window in UzEngine as it exists, how pixels get back to the CPU, and what "headless" actually means in each code path. Paths are relative to `E:\UzmiGames\UzEngine\`.

**Baseline** (added after the Astra review, see `10-review-response.md`): line numbers refer to UzEngine `HEAD 19ffb9b` (2026-07-27). The working tree is mid-merge with `9220973` (PR #10, conflict markers present since 2026-10-10 00:05); behaviour that the merge changes is noted inline. Source reading only; no mode below was executed for this analysis.

## 1. Summary table

| Mode | Window? | Swapchain? | Renders a scene? | Output | Evidence |
|---|---|---|---|---|---|
| `uzengine.exe --headless` | No | No | **No** — creates the RHI device, logs, exits | exit code only | **Fact** — `runtime/tools/uzengine.cpp` lines 133-145 (`RunHeadless`) and 1061-1062 |
| `uzengine.exe --hidden --screenshot out.png --screenshot-frame N --frames M` | Yes, HWND created but never shown | Yes (RGBA8, triple-buffered, vsync off) | Yes, full `SceneRenderer` | PNG file (or `SCREENSHOT_BASE64:` on stdout) | **Fact** — `uzengine.cpp` lines 512-555 (`--hidden`), 870-882 (screenshot trigger), `renderer/scene/scene_render_frame.cpp` lines 319-377 |
| `uzengine.exe --pass-dump` | hidden or visible | Yes | Yes | every registered render target as PNG + `INDEX.html` under `.screenshots/pass-dump-f{frame}/` | **Fact** — `uzengine.cpp` lines 901-905; `renderer/passes/debug/inspector_pass.h` lines 430-454; `inspector_pass_dump.cpp` lines 47, 86 |
| `uzengine.exe --diag` / `--pixel-debug` | hidden or visible | Yes | Yes | `DIAG_JSON:{…}` / `PIXEL_DEBUG_JSON:{…}` lines on stdout | **Fact** — `uzengine.cpp` lines 907-922 |
| `uzengine.exe --flip-ref a.png --flip-test b.png [--flip-output heat.png]` | **No** | **No** | No scene; GPU compute FLIP on two images | `FLIP_JSON:{mean_flip,max_flip,pass,…}` + optional heatmap PNG | **Fact** — `uzengine.cpp` lines 361-482 |
| C API `uz_create_viewport(NULL, w, h)` + `uz_render_frame()` + `uz_capture_screenshot()` | Yes, standalone top-level HWND (library mode) | Yes | Yes | PNG bytes in memory | **Fact** — `runtime/engine/app/runtime.h` lines 180-205, 430-445; `runtime.cpp` lines 301-383, 1279-1372 |
| `RHIBackend::Null` | — | — | — | `CreateRHIDevice` logs "unsupported backend" and returns `nullptr` | **Fact** — declared in `engine/rhi/rhi_backend.h` line 23 and parsed from `--rhi null` (`rhi_config.cpp` line 90), but `engine/rhi/rhi_factory.cpp` lines 36-93 has no `Null` case. The docs' "Backend Status" and the enum comment ("all operations are no-ops") describe an implementation that does not exist. |

**Key fact for the architect:** the only path that renders a *scene* today requires a Win32 `PlatformWindow` and an `IRHISwapChain`. Among the CLI modes inspected, the window-less GPU work is the FLIP compare mode; it shows that a source path for device, textures, compute PSO and readback exists with no window (not executed here). Other window-less compute exists outside the CLI (for example `MaterialBakerGpu`, `03-…` §4); this is not an exhaustive search.

## 2. The windowed/hidden frame loop (what UzPainter would inherit)

**Fact** — `runtime/tools/uzengine.cpp` `RunWindowed` (lines 485-954):

1. `PlatformWindow window; window.Create(desc)`; `--hidden` skips `window.Show()` (lines 513-530). The comment states "swapchain still works".
2. `CreateRHIDevice(deviceDesc)` (line 533).
3. `RHISwapChainDesc{ windowHandle, width, height, bufferCount=3, format=RGBA8Unorm, vsync=false }` → `device->CreateSwapChain` (lines 541-550).
4. One graphics `IRHICommandList`, three `IRHIFence` for frames-in-flight (lines 556-572).
5. `World world; LooseFileVFS vfs(contentRoot); LoadScene(world, bytes, name, &vfs)` (lines 574-590).
6. Optional `--camera-pos x,y,z` / `--camera-look x,y,z` applied to the first active `CameraComponent` for repeatable captures (lines 592-634).
7. `LuaVM::Init()`, `ScriptSystem::SetPlayMode(!editorMode)` — `--editor` keeps scripts dormant for deterministic captures (lines 636-652).
8. `SceneRenderer sceneRenderer; sceneRenderer.Init(device, &window, width, height)` (lines 663-676) — signature `bool Init(IRHIDevice*, PlatformWindow*, uint32_t, uint32_t)` in `renderer/scene/scene_renderer.h` line 195.
9. Pre-load: one `RenderFrame` to trigger lazy texture loads, then `DrainPendingTextureLoads` + `WaitIdle` (lines 775-797).
10. Loop: fence wait for frame N-3 → `RenderFrame(cmdList, swapChain, &world, &vfs, dt, frameIndex)` → `swapChain->Present(false)` → fence signal (lines 808-891). Screenshot is requested only when `IsSceneFullyLoaded()` or 120 frames after `--screenshot-frame` (lines 877-882). The incoming merge removes this 120-frame bypass and requires readiness (working tree lines 1250-1255).
11. Teardown with `WaitIdle`, pass dump, diag JSON (lines 893-953).

**Fact** — `SceneRenderer::RenderFrame` takes an `IRHISwapChain*` (`scene_renderer.h` lines 232-249); the render graph imports the backbuffer via `RgBuilder::ImportTexture("Backbuffer", bbHandle, RHIResourceState::Present)` (`renderer/render_graph/render_graph_builder.h` line 16, 98-111). With a null swapchain `RenderFrame` returns immediately and renders nothing (`if (!m_device || !cmdList || !swapChain) return;`, `scene_render_frame.cpp` line 57; working tree line 69). `SceneRenderer::GetLdrIntermediate()` / `GetLdrIntermediateState()` already expose the final LDR texture (`scene_renderer.h` lines 250, 255), which is a starting point for preview capture but does not make `RenderFrame` swapchain-free.

**Fact** — The "Engine Mode" documents under `docs/engine/32-engine-mode/` describe a VSCode layout feature, not a headless engine mode. Do not rely on that name.

**Fact** — A second application framework, `uz::Application` (`runtime/engine/app/application.h`), has its own `ParseArgs` with `m_headless` documented as "--headless: create window but keep it hidden (no GUI)" (line 243), `--screenshot-stdout` (base64 PNG to stdout, line 242) and a FLIP headless mode (line 289). So "headless" in `Application` means hidden-window rendering, whereas in `uzengine.cpp` it means device-only. Which executable uses `Application` was not traced (demos reference `DemoApplication`); treat `uzengine.cpp` as the reference CLI.

## 3. CPU readback primitives

### 3.1 RHI level

**Fact** — `engine/rhi/rhi_command_list.h`:

- `CopyTextureToBuffer(srcTexture, mipLevel, dstBuffer, dstOffset, dstRowPitch, arraySlice=0)` — "Used for reading back rendered frames to CPU memory. The destination buffer must have CopyDst usage and Readback memory. The source texture must be in CopySrc state". Row pitch must meet backend alignment (256 bytes on DX12).
- `CopyBufferToTexture(srcBuffer, srcOffset, srcRowPitch, dstTexture, mipLevel, arraySlice)` — upload direction, per mip/slice.
- `CopyBuffer`, `CopyTexture` (all subresources), `CopyTextureRegion(src, mip, slice, dst, mip, slice)`.

**Fact** — `engine/rhi/rhi_device.h`: `MapBuffer(handle)` returns a persistently mapped pointer on DX12/Vulkan; on DX11 the pointer is transient and `UnmapBuffer` is mandatory. `RHIMemoryType::{Default, Upload, Readback}` in `rhi_types.h` lines 464-468.

### 3.2 Engine-level helpers

| Helper | File | Behaviour | Formats |
|---|---|---|---|
| `ScreenshotCapture` | `runtime/editor/screenshot/screenshot_capture.h` | One readback buffer, 256-byte aligned pitch; `CaptureBackBuffer` (RT state) or `CaptureFromPresent` (Present→CopySrc→Present); `SaveToPNG`, `ToBase64PNG`, `MapReadback/UnmapReadback`; tracks swapchain format and swizzles BGRA (`m_captureFormat`, line 812) | swapchain RGBA8/BGRA8 only |
| `FrameReadback` | `runtime/engine/ipc/frame_readback.h/.cpp` | **Triple-buffered**, one fence per slot, read of the oldest slot; `CaptureFrame(cmdList, swapChain)` or `CaptureFromTexture(cmdList, tex)` ("preferred path — avoids reading from the swapchain backbuffer"); `rowPitch = AlignUp(width*4, 256)` (`.cpp` line 94). Capture advances the write slot without checking that the slot was consumed (lines 190-229); fence signalling is a separate caller step after `Execute` (lines 236-246); `MapRead` does not check `IsReadReady` (lines 273-286). No backpressure: a slow consumer can lose captures or map an in-flight slot (**Hypothesis** from the code path) | assumes 4 bytes/texel (RGBA8) |
| `PassInspector::ExecuteDump` | `renderer/passes/debug/inspector_pass_dump.cpp` | Reads back registered targets using `BytesPerTexel(format)` (line 47) and `CopyTextureToBuffer` (line 86), writes PNGs + `INDEX.html`. It **skips** formats with no texel size or channel count, depth targets other than `gbuffer.depth`, and targets larger than the shared readback buffer (lines 51-73), and converts for display (Reinhard tonemap for full-colour views, lines 149-172). At HEAD a 3D volume readback reaches only Z-slice 0 (`inspector_pass_validate.cpp` line 104 comment); the incoming merge adds DX12 Z-slice selection through `arraySlice` (working tree `dx12_command_list.cpp` lines 906-939), while Vulkan still copies from `imageOffset.z = 0` (`vulkan_command_list.cpp` line 1175) | display-converted RGBA8 PNG; diagnostic only, not exact channel data |
| FLIP heatmap readback | `uzengine.cpp` lines 409-458 | Manual example of reading an `RGBA16F` texture: readback buffer of `w*8*h` bytes, `CopyTextureToBuffer`, `WaitIdle`, `MapBuffer`, half→float→uint8 conversion inline, `PngCodec::EncodeFile`. Row pitch is `refW * 8` (line 411) with no 256-byte alignment, which the DX12 placed-footprint copy requires (see §3.1); correctness for widths that are not a multiple of 32 is **not confirmed** | RGBA16F |
| `uz_capture_screenshot` | `runtime/engine/app/runtime.cpp` lines 1279-1372 | `CaptureFromPresent` + `WaitIdle` + `ToBase64PNG` + **base64 decode back to bytes** (the code comments admit this roundtrip is a workaround) | RGBA8 PNG |

**Fact** — All helpers except `FrameReadback` synchronise with `device->WaitIdle()` (full pipeline stall). `FrameReadback` is the only stall-free design; it is sized for a single RGBA8 target and has no slot-ownership or backpressure protocol, so it is not a lossless batch exporter.

**Fact** — Readback throughput numbers are **not documented** anywhere read in this analysis; the only measured numbers are H.264 *encode* latencies (2-4 ms) in `docs/engine/32-engine-mode/05-viewport-integration.md`, which are not readback measurements.

## 4. Image encoders available for the readback → file step

**Fact**:

- `PngCodec::EncodeFile(path, pixels, w, h, channels 1-4)` is **8-bit only** (IHDR depth hardcoded to 8, `png_codec.cpp` line 327); `PngCodec::EncodeMemory(pixels, w, h, channels, bitDepth 8|16)` accepts 16-bit native little-endian samples and byte-swaps them for PNG (`png_codec.h` lines 68-90; `png_codec.cpp` lines 353-416). 16-bit PNG output therefore means `EncodeMemory` plus an explicit file write.
- `stb_image_write.h` (PNG/TGA/BMP) used by `CompareGrid` (`editor/screenshot/compare_grid.h`).
- `tinyexr.h` is vendored (`runtime/thirdparty/tinyexr/`) and used for **loading** EXR (`renderer/upload/texture_loader_hdr.cpp`); its save API is available in the header but no engine call site was found (**Fact: no `SaveEXR` call located in grep; Hypothesis: usable as-is**).
- `WriteUzTexture(header, mips)` for the engine's own cooked format (`engine/asset/formats/uztexture_format.h`).

## 5. Determinism and CI aids already present

**Fact** — these are capture aids, not a determinism contract: the main loop's `dt` is wall-clock time (`uzengine.cpp` lines 835-837), the renderer uses `frameIndex`, and the preview has temporal passes (`postprocess/exposure_average_cs.hlsl`, `taa_resolve_cs.hlsl`) that `--editor` does not freeze. `uzengine.cpp`: `--frames N` hard frame limit; diagnostic modes auto-limit to 120 frames; `--screenshot` without `--frames` limits to 500; `IsSceneFullyLoaded()` gate before capture; `--camera-pos/--camera-look`; `--editor` disables scripts; `--cvar name=value` and `.uzproject` `"cvars"` flushed before `SceneRenderer::Init` (lines 654-661); exit codes 0/1/2/3 (success / RHI / shader / device lost). `--renderdoc-capture N` is documented in `runtime/thirdparty/README.md` ("RenderDoc").

**Fact** — Agility SDK and DXC are resolved relative to the executable via `uz::GetExeDir()` (`docs/engine/06-build-toolchain/05-build-configs.md`), and `uz_set_engine_dir()` exists to redirect that when hosted in another process (`runtime.h` lines 128-145).

## 6. What this means for UzPainter

| Need | Available today | Gap / recommendation |
|---|---|---|
| Render PBR preview offscreen in CI | **Hidden HWND + swapchain** path (source path `--hidden --screenshot`; successful CI or service-session rendering **not confirmed**) | **Recommendation:** accept a hidden HWND for v1; it is the existing path. "No visible window" (hidden HWND) and "no HWND/swapchain/desktop dependency" are different requirements. Adding a true swapchain-less `SceneRenderer` target mode means importing an engine-owned RGBA8/RGBA16F texture instead of the backbuffer in `scene_render_frame.cpp` and skipping `Present` — medium effort (`09-gaps-and-risks.md` G1). |
| Run compute-only jobs (compositing, baking) with no window | Source path exists — the FLIP mode does device + compute + readback with no window | Reuse after a test on the pinned baseline. |
| Read back arbitrary formats (R8, R16F, RGBA16F, R32F) | RHI primitives yes; helpers are RGBA8-centric except pass dump | **Recommendation:** write a small `TextureReadback` utility generalising `FrameReadback` (N slots, any `BytesPerTexel` format, per-mip/slice). |
| Get PNG/EXR files out | PNG 8-bit via `EncodeFile`, 16-bit via `EncodeMemory` + file write; EXR save needs a tinyexr call | Small. Exact channel export must not go through the display-converted pass dump. |
| Perceptual diff for AI iteration | `FlipPass` (GPU) + `ImageDiff`/`CompareGrid` (CPU PSNR, heatmap, labelled grids) | Reuse directly. |
