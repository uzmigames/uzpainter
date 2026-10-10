# GPU Texture Compression and Container Formats for Export

Research compiled 2026-10-09.

## GPU Compression Encoders (C++ Integration)

| Encoder | What It Is | Pros | Cons | License | Key Source |
|---------|-----------|------|------|---------|-----------|
| **bc7enc_rdo** | Fork of AMD Compressonator; replaces CPU BC7 codec with bc7e.ispc (SIMD-accelerated Intel ISPC); includes Rate-Distortion Optimization. Single header/source, modern, maintained as of 2024. | Fastest BC7 on CPU (SIMD via ISPC); RDO for near-optimal compression ratios; compiles on Windows/MSVC; MIT or Public Domain license. | Requires ISPC compiler in build chain (adds complexity); no GPU acceleration; bindings needed for C++ integration (not a library, more a tool suite). | **Fact**: MIT or Public Domain. [Source](https://github.com/richgel999/bc7enc_rdo_devel) | [bc7enc_rdo GitHub](https://github.com/richgel999/bc7enc_rdo_devel) |
| **Intel ISPC Texture Compressor** | ISPC-based encoder for BC1-5, BC6, BC7, ETC, ASTC formats; integrated into Compressonator or standalone. | High speed SIMD; open-source; active ecosystem. | Requires ISPC toolchain; steeper build integration than single-header libraries; **Hypothesis**: less battle-tested in game engines than Compressonator. | **Fact**: Apache 2.0. [Source](https://github.com/GameTechDev/ISPCTextureCompressor) | [Intel ISPC TC GitHub](https://github.com/GameTechDev/ISPCTextureCompressor) |
| **AMD Compressonator** | Full suite: CLI tool + lib; supports BC1-7, ASTC, ETC, ETC2, DXT, BasisU, KTX2; compiles on Windows/MSVC; codec selection via compile-time #ifdef. | Mature; widely used in game studios; KTX2 + Basis Universal support; command-line useful for batch export. | Large codebase (harder to embed as library); Windows-centric build documentation; newer UASTC/BasisU mode less matured than BC codecs. | **Fact**: MIT License. [Source](https://github.com/GPUOpen-Tools/compressonator) | [AMD Compressonator GitHub](https://github.com/GPUOpen-Tools/compressonator) |
| **DirectXTex** | Microsoft's texture library (used in DirectX SDK); C++ library for BC1-7 encoding/decoding, DDS I/O, mipmap generation. | Microsoft-backed, battle-tested in Xbox/Windows pipelines; header-only option available; straightforward C++ integration. | No advanced compression algorithms (basic BC codec); Windows/MSVC only; limited platform support outside DirectX ecosystem. | **Fact**: MIT License. [Source](https://github.com/Microsoft/DirectXTex) | [DirectXTex GitHub](https://github.com/Microsoft/DirectXTex) |
| **NVTT 3 (NVIDIA Texture Tools)** | GPU-accelerated BC6/7, DXT encoding; CUDA or OpenGL backend; Turing+ GPUs. | Fastest for large batch jobs; production-grade; NVIDIA SDK quality. | Requires NVIDIA GPU + CUDA; licensing tied to NVIDIA (proprietary EULA); overkill for single textures; large runtime footprint. | **Fact**: Proprietary; NVIDIA EULA. [Source](https://developer.nvidia.com/nvidia-texture-tools-exporter) | [NVIDIA Texture Tools](https://developer.nvidia.com/nvidia-texture-tools-exporter) |

## Container and Lossless Format Options

| Format | What It Is | Pros (Docs Export) | Cons | License | Key Source |
|--------|-----------|-------------------|------|---------|-----------|
| **DDS (DirectDraw Surface)** | Microsoft container; stores uncompressed or BC1-7 compressed (DXTn) textures; supports mipmaps, cubemaps, texture arrays. | Universal game engine support; small disk footprint (BC7 @ 0.5 bpp); DirectX ecosystem standard; DXT compression hardware-accelerated on all major GPUs. | Dated format (2000s-era); limited compression options vs KTX2; no built-in supercompression or transcoding hints; Windows-centric perception (though cross-platform). | **Fact**: Microsoft format, no official license restriction (widely used). [Source](https://en.wikipedia.org/wiki/DirectDraw_Surface) | [Wikipedia: DirectDraw Surface](https://en.wikipedia.org/wiki/DirectDraw_Surface) |
| **KTX2 + Basis Universal** | Khronos container (KTX v2); pairs with Basis Universal supercompression (ETC1S for low bpp, UASTC for high quality); transcodes to BC/ASTC/ETC2 at runtime. | **Fact**: ETC1S mode 0.3-3 bpp (tunable quality like JPEG); UASTC mode 4bpp (excellent for hero assets, normal maps). **Fact**: Transcoding UASTC to BC7 fast and simple (UASTC is ASTC subset). **Fact**: Zstandard supercompression on KTX2 further reduces file size 1-2x. [Source](https://github.com/BinomialLLC/basis_universal/wiki/Release-Notes) | Transcoding on load adds CPU cost (typically <50ms for 4K); Basis Universal optimization (esp. ETC1S) can degrade fine detail; platform support patchy (glTF viewers ready, game engines rolling out). | **Fact**: Basis Universal under Apache 2.0; KTX under Khronos license (permissive). [Source](https://github.com/BinomialLLC/basis_universal) | [Basis Universal GitHub](https://github.com/BinomialLLC/basis_universal) |
| **PNG + TIFF (Lossless)** | PNG: DEFLATE compression. TIFF: LZW or PackBits. For source/undo-free archive of uncompressed or lightly compressed layers. | Universal tool support; editable in any image editor; lossless; PNG 8-bit or 16-bit per channel; TIFF flexible. | **Fact**: PNG compresses normal maps / masks ~10x less than specialized BC7 (PNG 2-4 MB vs BC7 0.5 MB per 4K texture). Large on disk for uncompressed channels. | **Fact**: PNG under libpng license (permissive). TIFF public domain. [Source](http://www.libpng.org/pub/png/book/chapter09.html) | [PNG Book: Compression](http://www.libpng.org/pub/png/book/chapter09.html) |
| **Zstandard (lossless compression wrapper)** | Modern LZ77-derivative (2015); replaces DEFLATE in modern stacks (KTX2, WebP, tar). Compresses binary image data, not an image format itself. | **Fact**: Zpng (Zstandard-compressed PNG) 66% of PNG size, <6% PNG compression time. Zstandard Zstd decompression via libzstd, 1-2x PNG speed. | Requires Zstandard decoder library; not natively supported in older image viewers; less standard than DEFLATE for general tools. | **Fact**: BSD 3-Clause License. [Source](https://github.com/facebook/zstd) | [Zstandard GitHub](https://github.com/facebook/zstd) |

## Unreal Engine 5 ORM Import Requirements

**Fact** (from research): Unreal Engine 5 ORM (Occlusion-Roughness-Metallic packed texture) **requires**:
- **Texture Compression Setting**: "Masks" (no sRGB) — this ensures linear interpretation, not gamma-corrected.
- **sRGB Unchecked**: Critical; ORM is linear data (masks), not color data. If sRGB applied, every value is gamma-curved, breaking the material.
- **Channel Layout**: Red=AO, Green=Roughness, Blue=Metallic (standard).
- **Engine decompresses from**: DXT1/DXT5 (legacy) or BC7 (modern); import format can be PNG or TGA with manual compression override, or pre-compressed DDS/KTX.

**Import Path in UE5**: Content Browser → import texture → set Compression to "Masks (no sRGB)" → confirm sRGB = false in Details panel.

[Source](https://www.strayspark.studio/learn/tutorials/import-strayspark-pbr-materials-unreal-engine-5)

## glTF 2.0 Texture Format (metallicRoughness)

**Fact**: glTF 2.0 core format stores metallicRoughness as:
- **G channel**: Roughness (0 = mirror, 1 = matte)
- **B channel**: Metallic (0 = dielectric, 1 = fully metallic)
- **Optional R channel** (via extension): Occlusion

**Fact**: glTF KHR_texture_basisu extension allows metallicRoughness to reference KTX2 + Basis Universal instead of inline PNG/JPEG. Reduces download size + GPU memory footprint; transcodes to native format on load.

**Caveat**: Basis Universal optimized for correlated color data (natural images), NOT independent-channel masks. Normal maps + ORM + raw masks in ETC1S suffer detail loss; use UASTC mode for high-quality exports.

[Source](https://registry.khronos.org/glTF/specs/2.0/glTF-2.0.html)

## Trade-Off Summary

**For UzPainter PBR Separate Maps Export:**
1. **Fastest turnaround, widest engine support**: Export to DDS (BC7-compressed) or PNG source → user can import into Unreal, UE4, Godot, custom engines. Standard workflow, zero supercompression latency.
2. **Smallest files, best for web/mobile**: KTX2 + Basis Universal UASTC (hero assets) or ETC1S (mass content); requires user/engine with transcoder. Adds ~50ms load-time, saves 50-70% disk space vs BC7 DDS.
3. **Lossless archive (UzPainter project internal)**: PNG per layer + Zstandard wrapper for project save; no transcoding overhead, editable with standard tools, compression near-lossless for masks.

**Encoder Choice (for UzPainter core):**
- **Tightest integration, fastest bakes**: bc7enc_rdo (SIMD, single-file, MIT license).
- **Production-ready, full format coverage**: AMD Compressonator (CLI + lib; Basis/KTX2 built-in).
- **Minimal dependencies**: DirectXTex (header-only BC option, Microsoft-backed).

**Compression Quality vs Speed:**
- BC7 + RDO: best perceptual quality for game use; ~50-200ms per 4K texture on CPU.
- ETC1S (KTX2): best file size; artifacts visible on specular maps.
- UASTC (KTX2): near-BC7 quality; ~100-300MB source → 5-10MB UASTC; further ~50% reduction with Zstd.

## Sources
- [bc7enc_rdo GitHub](https://github.com/richgel999/bc7enc_rdo_devel)
- [Intel ISPC Texture Compressor](https://github.com/GameTechDev/ISPCTextureCompressor)
- [AMD Compressonator](https://github.com/GPUOpen-Tools/compressonator)
- [DirectXTex](https://github.com/Microsoft/DirectXTex)
- [NVIDIA Texture Tools](https://developer.nvidia.com/nvidia-texture-tools-exporter)
- [DirectDraw Surface Wikipedia](https://en.wikipedia.org/wiki/DirectDraw_Surface)
- [Basis Universal](https://github.com/BinomialLLC/basis_universal)
- [KTX Specification](https://www.khronos.org/ktx/)
- [Zstandard](https://github.com/facebook/zstd)
- [Unreal Engine ORM Import Guide](https://www.strayspark.studio/learn/tutorials/import-strayspark-pbr-materials-unreal-engine-5)
- [glTF 2.0 Spec](https://registry.khronos.org/glTF/specs/2.0/glTF-2.0.html)
- [KHR_texture_basisu Extension](https://github.com/KhronosGroup/glTF/tree/main/extensions/2.0/Khronos/KHR_texture_basisu)
- [PNG Book: Compression](http://www.libpng.org/pub/png/book/chapter09.html)
