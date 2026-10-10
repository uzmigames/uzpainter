# 06 — Third-party Libraries and Image I/O

Scope: every directory under `E:\UzmiGames\UzEngine\runtime\thirdparty\`, its role in the engine, and whether UzPainter can reuse it for import, export, compression or baking. Sources: directory listing, `runtime/thirdparty/README.md`, `runtime/build.zig` (which sources are compiled), `docs/engine/06-build-toolchain/02-thirdparty-catalog.md`.

**Baseline** (added after the Astra review, see `10-review-response.md`): `build.zig` line numbers refer to UzEngine `HEAD 19ffb9b` (2026-07-27); the working tree is mid-merge with `9220973`. "Vendored", "compiled", "engine API" and "validated output" are separate levels below; a vendored source file is not an integrated feature. Negative statements are scoped to the directories searched.

## 1. Image and texture libraries

| Library | Dir | Version (README) | Used for today | Compiled in `build.zig`? | UzPainter reuse |
|---|---|---|---|---|---|
| **stb** (`stb_image.h` 2.30, `stb_image_write.h` 1.16, `stb_image_resize2.h` 2.16, `stb_truetype.h`) | `stb/` | git 2025 | Fallback decode (TGA/BMP/HDR/PSD/GIF/PIC), PNG/TGA/BMP write in `CompareGrid`, HDR load | header-only (`asset/importers/stb_impl.cpp`) | Decode/encode of simple formats; **`stb_image_resize2` is vendored but no `stbir_` call exists** (**Fact**: grep empty) → available for high-quality resampling |
| **spng** 0.7.4 | `spng/` | — | Primary PNG decode (SIMD), `-DSPNG_USE_MINIZ=0 -DSPNG_STATIC` | yes | Fast PNG read |
| **libpng** 1.6.49 | `libpng/` | — | `PngCodec` 8/16-bit decode/encode, sRGB chunk detection (`engine/asset/importers/png_codec.h`) | yes (needs zlib) | **16-bit PNG export** through `EncodeMemory` (height/displacement) and metadata |
| **libjpeg-turbo** 3.1.3 | `libjpeg-turbo/` | — | JPEG decode (async decoder, FLIP loader) | yes (C fallback, no NASM) | JPEG read |
| **tinyexr** 1.0.9 (+ `miniz.c`) | `tinyexr/` | — | EXR load → RGBA16F (`texture_loader_hdr.cpp`) | header + miniz | **EXR read/write** (write API in header, no engine call site) |
| **basis_universal** | `basis_universal/` (`encoder/`, `transcoder/`, `zstd/`) | git 2025 | KTX2 (UASTC HDR/LDR, ETC1S) transcoding at load, `BASISD_SUPPORT_KTX2_ZSTD=1` | transcoder compiled (`build.zig` lines 578-582; CMake `BASIS_UNIVERSAL_SOURCES` lists only `basisu_transcoder.cpp`); the encoder directory is vendored but **not built**. It contains a BC7 encoder (`encoder/basisu_bc7enc.h`), BC6H image encoding (`pack_bc6h_image`, `encoder/basisu_astc_hdr_6x6_enc.cpp` line 3388) and a DDS reader/writer (`encoder/3rdparty/tinydds.h`, `TinyDDS_WriteImage` line 688) | KTX2 import; candidate source for KTX2/UASTC, BC6H and DDS export if the encoder is added to the build (quality/performance **not confirmed**) |
| **etcpak** | `etcpak/` | git 2025 | **BC1/BC3/BC4/BC5/BC7 CPU compression** in `TextureImporter` (`CompressBc1/3/4/5/7`, BC7 via bundled bc7enc) | yes | **Export compression** — the only BC encoder integrated in the engine build (Basis vendors another BC7 encoder, not built) |
| **astcenc** 5.3.0 | `astcenc/` | — | ASTC LDR/HDR encode/decode for mobile (22 cpp per docs) | yes | Not needed for Windows targets; could serve as a reference HDR encoder |
| **DirectXTex / Compressonator / ISPC texcomp / NVTT / OpenImageIO / libwebp / libktx** | — | — | — | — | **Absent** (**Fact**: `ls thirdparty | grep` finds none) |

**Fact** — No integrated engine BC6H export path exists: etcpak does not do BC6H and astcenc does HDR ASTC only. BC6H encoding source does exist in the vendored, unbuilt Basis Universal encoder (row above); no engine wrapper for it was found.

## 2. Mesh and geometry libraries

| Library | Dir | Used for | Compiled? | UzPainter reuse |
|---|---|---|---|---|
| **ufbx** 0.14.3 | `ufbx/` | FBX parse (meshes, skeletons, skin, animation) | yes (C11) | High-/low-poly FBX import |
| **fastgltf** | `fastgltf/` | glTF/GLB parse | yes (C++17, `build.zig` lines 381-390; the single C++20 TU at line 674 is etcpak's `bc7enc.cpp`, comment at line 659) | glTF import |
| **meshoptimizer** | `meshoptimizer/` | vertex remap/dedup, cache/fetch optimisation, `meshopt_simplify` auto-LOD | yes (`build.zig` lines 532-553) | Dedup, simplification, optional low-poly generation |
| **mikktspace** | `mikktspace/` (`mikktspace.c/.h`) | MikkTSpace tangents in cooked importers | yes | **Tangent basis for baking** |
| **xatlas** | `xatlas/` | Lightmap UV generation (`lightmap_uv_generator.h`) | yes | Auto-unwrap / UV atlas packing |
| **entt** | `entt/` | ECS `World` | header | required transitively by `SceneRenderer` |
| **DirectXMath**, **glm**, **sse_mathfun** | — | math | header | — |

## 3. GPU / shader toolchain

| Library | Dir | Role | Deployment |
|---|---|---|---|
| **DXC** 1.9.2602 | `dxc/` | HLSL → DXIL / SPIR-V at runtime (dynamic `LoadLibrary`) | `dxcompiler.dll`, `dxil.dll` next to exe |
| **FXC** | `fxc/bin/` | HLSL → DXBC SM5.0 | `d3dcompiler_47.dll` |
| **Slang** 2025.x | `slang/` | HLSL → MSL (Metal) optional | `slang.dll` loaded at runtime |
| **Agility SDK** 1.619.1 | `agility/` | D3D12 runtime (SM6.6+ on Win10) | `D3D12Core.dll`, `d3d12SDKLayers.dll` |
| **DirectX-Headers** 1.619.1, **DirectXMath** | — | headers for Clang/MinGW | — |
| **D3D12MA** 3.1.0 | `d3d12ma/` | GPU allocator | compiled |
| **VMA** 3.2.1, **volk**, **Vulkan-Headers** 1.4.342 | — | Vulkan backend | compiled / dynamic |
| **metal-cpp** | `metal-cpp/` | Metal backend | mac only |
| **SPIRV-Reflect** | `spirv-reflect/` | binding reflection | compiled (C11) |
| **AMD FidelityFX** (`amd-fidelityfx/`, `amd-fidelityfx-1.1/`) | — | FSR 1/2, CAS; Brixelizer GI via MSVC-built `uz_brixelizer.dll` wrapper | optional DLL |
| **DLSS** | `dlss/` (gitignored, downloaded) | upscaler via `_nvngx.dll` LoadLibrary | `nvngx_dlss.dll` (65 MB) |
| **RenderDoc** API | `renderdoc/` | in-app capture | runtime load |
| **SMAA** | `smaa/` | AA shaders/LUTs | — |

## 4. Core / infrastructure

| Library | Role | Notes for UzPainter |
|---|---|---|
| **nlohmann/json** 3.12 | all JSON (`.uzproject`, `.uzscene`, `.uzmat`, sidecars) | Reuse for project files and a JSON-RPC MCP server |
| **spdlog** 1.17 | `UZ_LOG` backend | reuse |
| **Tracy** 0.13.1 | profiling (`-DTRACY_ENABLE -DTRACY_ON_DEMAND` global, passed in every optimisation mode by `build.zig` lines 24, 575) | reuse |
| **xxHash** | content hashes for caches | reuse for layer/bake caches |
| **lz4** 1.10 | `.uzpak` compression (`uzpack`) | reuse for compact project save |
| **zlib**, **zstd** (via vcpkg source) | PNG, KTX2 supercompression | reuse |
| **mimalloc** 2.2.4 (primary), jemalloc, dlmalloc | allocators | — |
| **atomic_queue** | lock-free MPMC (job system) | — |
| **LuaJIT** 2.1 | scripting (`lua51.lib` prebuilt by `scripts/build_luajit.bat`, `lua51.dll` deployed) | see `07-…` |
| **FFmpeg** 7.x LGPL shared | H.264 encode for viewport streaming (`avcodec`, `avutil`, `swscale`) | optional; adds ~85 MB of DLLs |
| **freetype** 2.13.3, **msdfgen** 1.13 | UI text | not needed |
| **googletest** 1.17 | tests | reuse for UzPainter tests |
| **crashpad** (mini) | listed in README, directory **not present** in `thirdparty/` listing | **Fact**: README entry says "repo unavailable"; the engine's crash handler is `platform/windows/crash_handler.cpp` |

**Fact** — Patch policy: thirdparty sources are downloaded by `scripts/setup.ps1`; local modifications must be expressed as `runtime/thirdparty/<lib>/patches/NNNN-*.patch` (`runtime/thirdparty/README.md` "Patch system"). UzPainter should follow the same policy if it vendors the same tree.

## 5. Image I/O capability matrix for UzPainter export

| Need | Available via | Status |
|---|---|---|
| PNG 8-bit read/write | spng / libpng / stb | **Fact** |
| PNG 16-bit read/write | `PngCodec::DecodeFile` (keeps 16 bits, native byte order) / `EncodeMemory(bitDepth=16)` + explicit file write; `EncodeFile` is 8-bit only (`png_codec.cpp` line 327) | **Fact** |
| JPEG read | libjpeg-turbo | **Fact**; write: libjpeg-turbo supports it, engine has no call site (**Hypothesis** usable) |
| TGA/BMP write | `stb_image_write` | **Fact** |
| EXR read | tinyexr | **Fact** |
| EXR write (32-bit float / half) | tinyexr `SaveEXR`/`SaveEXRImageToFile` in header | **Hypothesis** (no engine call site) |
| HDR (Radiance) read | stb_image | **Fact** |
| KTX2 read (UASTC/ETC1S) | basis transcoder | **Fact** |
| KTX2 write | basis encoder sources present, not built | **not confirmed** |
| DDS read/write | no engine path; `tinydds.h` is vendored inside the unbuilt Basis encoder (`encoder/3rdparty/`) | **Fact** — not integrated; `.uztexture` is the engine's container |
| BC1/3/4/5/7 encode | etcpak (fast, CPU) | **Fact** |
| BC6H encode | no engine path; source in the unbuilt Basis encoder | **Fact** — not integrated |
| ASTC encode | astcenc | **Fact** (mobile only) |
| GPU BC7 encoder | none | **Fact** absent |
| High-quality resampling | `stb_image_resize2` (vendored, unused) | **Fact** |
| Perceptual diff | `FlipPass` (GPU), `ImageDiff` (CPU PSNR) | **Fact** |

## 6. Licensing notes relevant to a shipped `UzPainter.exe`

**Fact** (summary quoted from `runtime/thirdparty/README.md`; not a licence or distribution audit): all image/mesh libraries above are MIT/BSD/Apache/public-domain except FFmpeg (LGPL 2.1 shared build — dynamic linking required), DLSS (NVIDIA proprietary, free for commercial use), DXC (NCSA), libpng (libpng licence), freetype (FTL/GPLv2). Leaving FFmpeg and DLSS out of UzPainter removes the two licence-sensitive binaries and ~150 MB of DLLs (**Hypothesis**: sizes of the debug build in `01-…` §4).
