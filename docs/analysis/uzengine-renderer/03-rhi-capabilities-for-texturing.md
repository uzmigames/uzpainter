# 03 — RHI Capabilities Relevant to a Texturing Tool

Scope: what the UzEngine RHI (`E:\UzmiGames\UzEngine\runtime\engine\rhi\`) can do for UV-space rendering, compute compositing, baking and export, and where the backends diverge.

**Baseline** (added after the Astra review, see `10-review-response.md`): line numbers refer to UzEngine `HEAD 19ffb9b` (2026-07-27); the working tree is mid-merge with `9220973` and merge-changed behaviour is noted inline. This document is an API map from source reading; format/usage combinations and backend behaviour were not executed or validated on a device.

## 1. Backends and selection

| Backend | Status | Shader model / binding | Evidence |
|---|---|---|---|
| DX12 | Primary ("done" per docs) | SM6.6+ bindless (`ResourceDescriptorHeap[]`), SM6.0 bindless, SM5.x register-bound fallback; negotiated at device creation | **Fact** — `docs/engine/03-rhi/02-dx12-backend.md`; `rhi_config.h` `ShaderModel` enum SM5_0…SM6_9 |
| DX11 | "Done" per docs (SM5.0 via FXC/DXBC) | slot-based; `SetRootCBV` with CPU data, `SetDescriptorTable` maps to `CSSetUnorderedAccessViews`/SRV slots | **Fact** — `rhi/dx11/dx11_command_list.cpp` lines 363-379, 486-495 |
| Vulkan | "Done" per docs; no ray tracing (§6) | SPIR-V via DXC `-spirv`, volk dynamic loading | **Fact** — `docs/engine/03-rhi/01-overview.md` Backend Status; `thirdparty/README.md` volk |
| Metal | WIP (macOS only) | Slang → MSL | **Fact** — same docs |
| Null | **Declared, not implemented** | — | **Fact** — enum in `rhi_backend.h` line 23 and `--rhi null` parsing (`rhi_config.cpp` line 90), but `rhi_factory.cpp` lines 36-93 has no `Null` case: `CreateRHIDevice` logs "unsupported backend" and returns `nullptr`. CPU-only CI cannot rely on it. |

**Fact** — Runtime selection: `--rhi dx12|vulkan|metal|null`, `--shader-model`, `--adapter N`, `--gpu-validation`, `--gpu-breadcrumbs` (`rhi_config.h` lines 59-72). `UZ_FORCE_SM5=1` env var forces the SM5 path (`docs/engine/03-rhi/02-dx12-backend.md`).

## 2. Resource formats (`rhi_types.h` lines 175-214)

| Category | Formats in `RHIFormat` | Notes for texturing |
|---|---|---|
| 8-bit UNORM | `R8Unorm`, `RG8Unorm`, `RGBA8Unorm`, `RGBA8Srgb`, `BGRA8Unorm`, `BGRA8Srgb` | **Fact** present. No `RGB8`, no `R8Snorm`. |
| 16-bit float | `R16Float`, `RG16Float`, `RGBA16Float` | **Fact** present. |
| 32-bit float | `R32Float`, `RG32Float`, `RGB32Float` (vertex positions), `RGBA32Float` | **Fact** present. |
| 32-bit uint | `R32Uint`, `RG32Uint`, `RGBA32Uint` | **Fact** present (ID maps, atomics). |
| Block compressed | `BC1Unorm/Srgb`, `BC3Unorm/Srgb`, `BC4Unorm`, `BC5Unorm`, `BC7Unorm/Srgb` | **Fact** present; helpers `IsBlockCompressed`, `BytesPerBlock`. |
| Depth | `D16Unorm`, `D32Float`, `D24UnormS8Uint`, `D32FloatS8Uint` | **Fact**. |
| **Absent** | `R16Unorm`/`RG16Unorm`/`RGBA16Unorm` (16-bit integer normalized), `R11G11B10F`, `RGB10A2`, `BC6H`, `BC2`, any SNORM, any sRGB BC4/BC5 | **Fact** — not in the enum. 16-bit UNORM matters for 16-bit height/displacement export via GPU; BC6H matters for HDR emissive/environment compression. |

**Fact** — Backend format tables: DX12 `rhi/dx12/dx12_texture_creation.cpp` lines 32-89 (all of the above incl. BC4/5/7); DX11 `rhi/dx11/dx11_resource_creation.cpp` lines 27-82 (R8, R16F, R32F, BC1/4/5/7 confirmed); Vulkan `rhi/vulkan/vulkan_format_helpers.h` lines 26-53 (R8, R16F, R32F, BC1/BC1-sRGB, BC3/BC3-sRGB, BC4, BC5, BC7/BC7-sRGB mapped, lines 46-53). A mapping table is not a device format-support query.

## 3. Textures, views and render targets

**Fact** — `RHITextureDesc` (`rhi_types.h` lines 499-508): `width`, `height`, `depthOrArraySize` (uint16), `mipLevels` (uint16), `format`, `usage` flags `ShaderResource | RenderTarget | DepthStencil | UnorderedAccess | CopySrc | CopyDst`, `is3D`. Cubemaps and 2D arrays are expressed via `depthOrArraySize`; there is no independent cube flag, and DX12 creates a **cube SRV whenever a non-3D texture has exactly 6 layers** (`dx12_texture_creation.cpp` lines 213-215). A 6-tile UDIM array would therefore need an explicit array/cube distinction.

**Fact** — Views created automatically at creation (DX12 `dx12_texture_creation.cpp`):

- SRV covers the full mip chain (`Texture2DArray.MipLevels = desc.mipLevels`, line 220).
- **UAV is created for mip 0 only** (`Texture2D.MipSlice = 0` line 255; `Texture2DArray.MipSlice = 0` line 249; `Texture3D.MipSlice = 0` line 243). There is no API to obtain a UAV for mip N (`IRHIDevice::GetTextureUAVIndex(handle)` has no mip parameter, `rhi_device.h`). Consequence: direct per-mip UAV writes need an RHI extension; compute mip generation is still possible without one by writing each level into a scratch mip-0 UAV texture and copying it into place with `CopyTextureRegion(src, srcMip, srcSlice, dst, dstMip, dstSlice)` (`rhi_command_list.h` line 337 at HEAD).
- RTV: default RTV at creation; `BeginRenderPass` can target any `mipLevel` and `arraySlice` through `RHIRenderPassColorAttachment` (`rhi_types.h` lines 726-732; DX12 creates a transient RTV, `dx12_command_list.cpp` lines 980-990). Up to 8 colour attachments (`RHIRenderPassDesc`).

**Fact** — Rasterizer state (`RHIRasterizerDesc`, `rhi_types.h` lines 554-560): cull mode, fill mode, `frontCounterClockwise = true` default, depth bias, slope-scaled bias. **No conservative rasterization flag**; DX12 PSO creation hardcodes `D3D12_CONSERVATIVE_RASTERIZATION_MODE_OFF` (`rhi/dx12/dx12_pso_creation.cpp` line 671). No MSAA sample count field in `RHITextureDesc` or PSO desc (**Fact** — not present in `rhi_types.h`).

**Fact** — Blend: per-RT `RHIBlendDesc` with factors Zero/One/Src/InvSrc/Dst/InvDst colour & alpha and ops Add/Subtract/RevSubtract/Min/Max (`rhi_types.h` lines 384-408, 536-544). No colour write mask, no logic ops, no dual-source blend fields (**Fact** — absent). Separate alpha blend yes.

**Fact** — Depth convention is reversed-Z (`kReversedZ = true`, default `depthFunc = Greater`, `rhi_types.h` lines 41-60, 550). Irrelevant to UV-space passes (depth off) but relevant for the preview.

**Fact** — Samplers (`RHISamplerDesc`): Point/Linear/Anisotropic, Wrap/Clamp/Mirror/Border, LOD bias/min/max, compare func. No border-colour field (**Fact** — absent), so `Border` mode uses the backend default.

## 4. Compute

**Fact**:

- `IRHIDevice::CreateComputePipeline(RHIComputePipelineDesc{computeShader, cachedBlob})` (`rhi_device.h`); `IRHICommandList::Dispatch(x,y,z)` and `DispatchIndirect(argsBuffer, offset)` (`rhi_command_list.h`).
- Bindless UAV/SRV indices: `GetTextureUAVIndex`, `GetTextureSRVIndex`, `GetBufferUAVIndex`, `GetBufferSRVIndex`; pushed via `SetRootConstants(rootParam, data, count)` / `SetDescriptorIndex`. Root layout: param 0 = 4 root constants at `b0`, params 1-3 = CBVs `b1/b2/b4`, param 4 = UAV table `u0`, param 5 = SRV table `t0` (SM5) (`rhi_types.h` lines 815-834).
- UAV barrier = `ResourceBarrier` with `stateBefore == stateAfter == UnorderedAccess` (`docs/engine/03-rhi/06-barriers.md`).
- DX11 supports `Dispatch`/`DispatchIndirect` with UAV slot translation (`dx11_command_list.cpp` lines 363-379, 486-544).
- Async compute queue + copy queue fences exist (`SignalComputeQueue`, `GraphicsWaitForCompute`, `SignalCopyQueue`, `GraphicsWaitForCopy`, `rhi_device.h`), plus `rhi/optimization/rhi_async_compute_telemetry.h`.
- Existing compute shaders prove the path: `shaders/runtime/compute/{gpu_cull_cs, hiz_pyramid_cs, gpu_skinning_cs, decal_apply_cs, draw_compact_cs}.hlsl`, ~40 post-process `*_cs.hlsl`, IBL `{equirect_to_cubemap_cs, prefilter_cs, irradiance_cs, brdf_lut_cs, pmrem_to_cubemap_cs}.hlsl`, `postprocess/flip_cs.hlsl`.
- `material_baker_gpu.h`: wraps generated material HLSL in a compute kernel, creates an RGBA8 UAV+SRV texture, dispatches, transitions to SRV — a minimal "graph → texture" compute bake exists (selectors BaseColor 0 / Metallic 1 / Roughness 2 / Normal 3 / **AO 4**, `material_baker_gpu.h` lines 58-64; RGBA8 only, `.cpp` lines 176-181). Limits (`material_baker_gpu.cpp`): all 16 `materialParams` are zero and world position/normal/vertex colour/time are constants (lines 69-82); only dimensions, selector and the output UAV are bound (lines 223-249); it waits on a CPU fence (lines 269-270). The translator's texture nodes emit `ResourceDescriptorHeap[getTexIndex(slot)]` and `linearSampler` (`hlsl_material_translator.cpp` lines 404-411), which are defined only in `gbuffer_ps.hlsl` (`getTexIndex` at HEAD line 93), not in the bake wrapper, so graphs with texture nodes have no binding environment in the baker (compile success **not confirmed**). The bake selector for AO (4) differs from the `PBROutput` AO pin (6). It is a procedural prototype, not a layer compositor.

**Fact** — `shaders/runtime/compute/mipgen_cs.hlsl` is a one-line empty stub (`[numthreads(8,8,1)] void main(...){}`), and no engine code dispatches a mip-gen shader (`grep GenerateMips|mipgen` only finds a profiler counter and the CPU box filter). Mip chains are generated on the CPU (`renderer/upload/texture_loader.cpp` lines 250-275; `async_texture_decoder.cpp` lines 428-519) by 2×2 box averaging on RGBA8 with no sRGB-space handling found in those lines.

## 5. Uploads and readback

**Fact** — Upload: `RHIMemoryType::Upload` buffers + `CopyBufferToTexture` per mip/slice; `UploadContext`, `UploadRing` (`renderer/upload/upload_ring.h`), `StagingBatch`; `.uztexture` fast path uploads prebuilt BC mips through the ring at "~0.3–0.5 ms per 2K texture" (`docs/runtime/asset-loading.md`).

**Fact** — Readback: `RHIMemoryType::Readback` buffers + `CopyTextureToBuffer(tex, mip, buf, offset, rowPitch(256-aligned), arraySlice)` + `MapBuffer`. See `02-headless-rendering.md` §3 for the helpers. At HEAD, `CopyTextureToBuffer` on a 3D texture reaches only Z-slice 0 (`inspector_pass_validate.cpp` line 104 comment). The incoming merge makes DX12 select a Z slice through `arraySlice` (working tree `dx12_command_list.cpp` lines 906-939); Vulkan still copies from `imageOffset.z = 0` (`vulkan_command_list.cpp` line 1175).

## 6. Ray tracing (DXR)

**Fact** — RHI surface (`rhi_types.h` lines 836-983, `rhi_device.h`, `rhi_command_list.h`): `CreateBLAS(RHIBLASDesc{geometries[], buildFlags})`, `CreateTLAS(maxInstanceCount)`, `BuildBLAS(blas, scratch, update)`, `BuildTLAS(tlas, instanceBuffer, count, scratch, update)`, `UAVBarrierAS()`, `CreateRaytracingPipeline(RHIRTPipelineDesc{libraryShaders (lib_6_x), hitGroups, maxPayload, maxAttribute, maxRecursion})`, `GetShaderIdentifier`, `DispatchRays(pipeline, RHIDispatchRaysDesc{raygen/miss/hit tables, w,h,d})`, `GetTLASSRVIndex`, `SupportsRayTracing()`. Geometry must be `RGB32Float` positions with uint16/32 indices (`RHIRTGeometryDesc`).

**Fact** — Implementation status per backend:

| Backend | DXR implemented? | Evidence |
|---|---|---|
| DX12 | **Yes** — `CreateBLAS` (`dx12_device.cpp` line 1421), `CreateRaytracingPipeline` (line 1682), `BuildBLAS` (`dx12_command_list.cpp` line 1075), `DispatchRays` (line 1158); `SupportsRayTracing` from `D3D12_FEATURE_D3D12_OPTIONS5.RaytracingTier >= 1_0` (`dx12_device.cpp` line 307; working tree line 336); no Tier 1.1 / inline-ray-tracing capability is queried anywhere in `runtime/engine/` | **Fact** |
| Vulkan | **No** — no override of the RT virtuals found (`grep CreateBLAS|SupportsRayTracing rhi/vulkan` is empty), so the base-class defaults (`Invalid()`, `false`) apply | **Fact** |
| DX11 | No | **Fact** (no RT API in DX11) |

**Fact** — Inline ray tracing (`RayQuery<>`) is used by existing compute and pixel shaders: `shaders/runtime/gi/ddgi_probe_update_cs.hlsl`, `gi/gi_trace_common.hlsli`, `gi/gi_hit_lighting.hlsli`, `pathtracing/path_tracer_ps.hlsl`. The CHANGELOG (v0.9.1) states DDGI runs via "DXR 1.1 `RayQuery<>`" on an RTX 4090. So for baking, a compute shader with `RayQuery` against a TLAS SRV index is the existing pattern (no SBT needed). Inline `RayQuery` requires DXR Tier 1.1 and SM6.5 (Microsoft DXR functional specification, "Inline raytracing"; `rhi_config.h` lines 28-30 lists SM6.3 = DXR 1.0, SM6.5 = DXR 1.1); the engine's `SupportsRayTracing()` only reports Tier ≥ 1.0, so it does not establish `RayQuery` support.

**Fact** — Scene-level managers: `renderer/raytracing/{rt_manager, blas_manager, tlas_manager, shader_table_builder}.h`. `BLASManager::GetOrBuildBLAS(meshId, GPUMesh, cmdList)` caches one BLAS per mesh, with a hardcoded 48-byte vertex stride and `isOpaque = true` (`blas_manager.cpp` lines 31-37); `RTManager::BeginFrame` rebuilds the TLAS per frame from draw commands; `rt_uv_test_pass` + `shaders/runtime/raytracing/rt_uv_test_lib.hlsl` is a minimal raygen that writes a UV gradient to a UAV (a scaffold for a baking raygen). CVars `r.RayTracing`, `r.RayTracing.AO`, `.Shadows`, `.Reflections`, `.GI`, `.TestPass` (`rt_manager.h`).

**Hypothesis** — Baking from low-poly to high-poly can build on the existing infrastructure: build a BLAS for the high-poly mesh (positions + indices as GPU buffers, through the raw RHI `CreateBLAS` or a parameterised `BLASManager`, since the manager's stride/opacity are fixed), a one-instance TLAS, and dispatch a compute shader that reads a UV-space position/normal GBuffer and casts `RayQuery` rays. That kernel needs DX12 with DXR **Tier 1.1** and SM6.5; Tier 1.0 hardware would need a `DispatchRays` implementation or another fallback. The engine does not query Tier 1.1 today.

## 7. Shader compilation at runtime

**Fact** — `ShaderPipeline` (`engine/shader/shader_pipeline.h`): `Init({cacheDir="cache/shaders", targetBackend="dx12_sm66"})`, `LoadBytecodeFromSource(name, source)` (line 155), routes SM6.x to DXC (`dxcompiler.dll`, dynamic load) and SM5.0 to FXC (`d3dcompiler_47.dll`) (`docs/engine/05-shader-pipeline/03-compilation.md`), content-hash disk cache keyed by source + includes + defines + target + compiler version. `ShaderManager::CreateShaderWithDefines(EngineShader, stage, defines)` (`renderer/core/shader/shader_manager.h` line 109) for embedded shaders. `HlslMaterialTranslator` emits HLSL strings that are compiled at runtime and injected into `gbuffer_ps.hlsl` under `UZ_MATERIAL_GRAPH` (`shaders/runtime/gbuffer/gbuffer_ps.hlsl` lines 71-95). This is exactly the facility UzPainter needs for generated compositing kernels.

**Fact** — Dual-path HLSL rule: runtime shaders provide `#ifdef UZ_BINDLESS` (SM6.6) and register-bound (SM5) variants (`docs/engine/05-shader-pipeline/03-compilation.md` "HLSL Dual-Path Pattern"; visible in `gbuffer_ps.hlsl`). New UzPainter shaders that must run on DX11 need the same discipline.

## 8. Backend parity matrix for UzPainter features

| Capability | DX12 SM6.6 | DX12 SM5 / DX11 | Vulkan | Evidence |
|---|---|---|---|---|
| Render-to-texture with R8/RG8/RGBA8(sRGB)/R16F/RGBA16F/R32F | Yes | Yes (format tables) | Yes (format tables) | **Fact** format maps; actual RTV support per format relies on API guarantees (**Hypothesis** for exotic combos) |
| Compute + typed UAV textures | Yes (bindless) | Yes (slot `u0..`) | Yes | **Fact** |
| Per-mip UAV | No (scratch UAV + `CopyTextureRegion` is the workaround) | No | No | **Fact** (creation code) |
| Readback (any uncompressed format) | Yes | Yes (Map/Unmap transient) | Yes | **Fact** |
| BC1/4/5/7 sampling | Yes | Yes | Yes | **Fact** |
| DXR BLAS/TLAS/DispatchRays (pipeline ray tracing) | Yes (Tier ≥1.0 hardware) | No | No | **Fact** (API present; only Tier ≥1.0 is queried) |
| Inline `RayQuery` | Requires Tier 1.1 + SM6.5; **not queried** by the engine | No | No | **Fact** (shaders use it; capability check absent) |
| Conservative raster | No (hardcoded OFF) | No | No | **Fact** |
| Indirect draw/dispatch | Yes | Yes | Yes | **Fact** (`rhi_command_list.h`, DX11 `DispatchIndirect` line 528) |
| Async compute queue | Yes | not confirmed | not confirmed | — |
| PSO disk cache | Yes (`GetPipelineCachedBlob`) | — | VkPipelineCache native | **Fact** (`rhi_device.h`) |

## 9. Debug and validation facilities

**Fact** — D3D12 debug layer, GPU-based validation, DRED breadcrumbs, custom GPU breadcrumbs (`dx12_gpu_breadcrumbs.h`), live-object reporting, RenderDoc in-app capture (`engine/debug/renderdoc_capture.h`, F12 or `--renderdoc-capture N`), Tracy CPU/GPU profiling, per-pass GPU timestamps (`GpuProfilerBeginTimestamp`), `PassInspector` register/visualize/dump/validate, `PixelDebugSystem` (GPU printf at a pixel) (`runtime/thirdparty/README.md` RenderDoc section; `rhi_device.h`; `uzengine.cpp`).

## 10. Limits not confirmed

- Maximum texture dimension (D3D12 guarantees 16384; the engine imposes nothing visible, **not confirmed**). Texture dimensions are `uint32`, mip/layer counts `uint16` (`rhi_types.h` `RHITextureDesc`).
- DX12 descriptor capacity is fixed: 1,000,000 CBV/SRV/UAV, 2,048 samplers, 256 RTV, 64 DSV (`dx12_device.h` lines 47-56). Current VRAM budget/usage can be queried (`QueryVideoMemoryInfo`, `dx12_device.cpp` line 1265 at HEAD).
- Typed-UAV-load format support checks (`D3D12_FEATURE_FORMAT_SUPPORT`) — no query found in `dx12_device.cpp` greps (**not confirmed**).
- Vulkan compute/readback correctness for formats beyond those in the grep (**not confirmed**).
