# UzPainter technology options — Astra technical review

Review date: 2026-10-10. Scope: the four documents in `docs/analysis/technology-options/`, dated 2026-10-09.

## Executive summary

**Recommendation:** Do not approve the documents as architecture decision records in their current form.
**Fact:** They contain decision-changing errors in texture bitrates, Python embedding, encoder capabilities/licenses, and project-save behavior.
**Fact:** MCP revision **2026-07-28 is real** and is the current revision reached by the official specification landing page during this review.
**Fact:** Its Tasks extension, per-request capabilities, `server/discover`, `tasks/update`, and task subscriptions are also real; older MCP knowledge would misclassify them.
**Recommendation:** Define and measure Substance parity before selecting implementation and storage shortcuts.
**Recommendation:** Separate Python runtime distribution, C++ bindings, executable packaging, MCP transport, and ownership of renderer state.
**Recommendation:** Retain lossless authoritative project data; compare chunked HDF5, SQLite, and a chunked custom container against a ZIP baseline.
**Hypothesis:** UzPainter can substantially reduce the supplied `.spp` sizes through its data model and cache policy; no reduction factor is established.

## Evidence and limits

**Fact:** All four local documents were read. Primary web documentation, specifications, repositories, and selected license files were inspected. Links below identify the evidence supporting each conclusion. Mutable `main`, `stable`, and `latest` pages describe what was retrieved in this session; they are not immutable release manifests or proof of every historical release.

**Fact:** The HDF5 signatures and exact `.spp` byte counts are accepted as user-supplied local evidence already verified by Claude, not measurements independently repeated here. No applications, project binaries, encoders, installers, or benchmarks were run. UzEngine implementation details were not inspected; compatibility with its existing texture loader remains unconfirmed.

**Fact:** “Not verified online” means an assertion was assessed from own technical knowledge rather than established by the inspected online evidence. Confidence is stated where this applies. Unsupported estimates are marked **unconfirmed**, even when plausible. A vendor's feature claim is evidence of an advertised feature, not independent proof of production maturity or performance.

**Fact:** Severity means: **blocker** prevents an architecture or acceptance decision; **major** can change implementation, interoperability, fidelity, or storage outcomes; **minor** affects precision or secondary choices. Classification labels distinguish observed facts, untested hypotheses, and proposed actions.

## Verdict by file

| File | Classification and verdict | Reliable foundation | Decision-changing problems |
|---|---|---|---|
| `01-python-embedding-and-packaging.md` | **Recommendation — major revision required** | A private CPython runtime, pybind11 embedding, and process isolation are legitimate options. | Distribution and binding mechanisms are treated as alternatives; pip/site behavior, GIL claims, subinterpreter release attribution, automatic nanobind GIL release, static linking, and all footprint estimates need correction. |
| `02-texture-compression-and-containers.md` | **Recommendation — reject quantitative conclusions; revise shortlist** | DDS, KTX2/Basis, lossless source images, and the listed encoder families are relevant. | BC7/UASTC bitrates are wrong; encoder descriptions and licenses are mixed; Unreal import/cooking assumptions and glTF occlusion are misleading; size and timing promises lack measurements. |
| `03-project-container-format.md` | **Recommendation — reopen container decision** | The supplied files have HDF5 signatures; ZIP manifests, chunks, and schema evolution are useful concepts. | HDF5 is rejected for incorrect reasons; ZIP mutation is oversimplified; ratios are unsupported; the authoritative procedural project model and SQLite are missing. |
| `04-mcp-server-options.md` | **Recommendation — keep the verified revision/Tasks foundation; redesign integration** | The cited 2026 revision, standard transports, and current Tasks extension are supported by official sources. | Old and new protocol behavior are mixed; SDK APIs/licenses are inaccurate; example messages omit required fields; process topology leaves renderer ownership and external-client access undefined. |

## Numbered findings

### 1. [blocker] [Recommendation] Acceptance parity must be an explicit engineering contract

**Claim/verdict (Fact):** None of the four technology choices establishes that the same instructions produce the same Substance texture and render. Packaging, MCP, and containers do not reproduce Painter's compositing, procedural generators, baker, tangent basis, shading, lighting, or color pipeline. This is an uncovered acceptance requirement, not proof that parity is impossible.

**Evidence:** The user's 2026-10-10 acceptance premise; own technical knowledge, high confidence, not verified online for the overall equivalence claim. Adobe's [Painter 12.0 release notes](https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/release-notes/version-12-0) document both a tone-mapper change and a CPU/GPU AO difference, illustrating why even the reference environment must be pinned.

**Correction (Recommendation):** Specify whether equality means encoded-file bytes, decoded texels, or agreed visual/numeric tolerances. Pin Painter version, assets, generator implementations/seeds, mesh/UV/tangents, bake settings, resolution, working precision, color management, camera, lights/HDRI, render mode, and post-processing. Replay a canonical typed command sequence; natural-language interpretation needs a separately controlled translation step. Compare texture planes before export compression and renders separately. A tolerance cannot silently replace exact equality.

### 2. [blocker] [Fact] PNG layers plus a manifest are not yet a complete Painter-equivalent project model

**Claim/verdict:** File 03 recommends one PNG per layer without defining how a layer's multiple material channels, masks, generators, filters, strokes, fill projections, dependencies, texture sets, and UV tiles survive a save/load round trip. Flattened pixels alone cannot preserve editable procedural behavior. Calling every bake result “transient” is conditional on retaining sufficient sources and an equivalent deterministic baker.

**Evidence:** Own technical knowledge, high confidence; not verified online against UzPainter's unimplemented schema. The source document's example manifest has no defined representation for these semantics.

**Correction (Recommendation):** Define authoritative state first: versioned layer/effect graph, typed parameters, asset content hashes, seeds, source meshes/images, channel precision and color interpretation, and sparse raster/stroke payloads. Separate reproducible caches from irreplaceable inputs. A cache may be discarded only when its dependencies and evaluation implementation remain available. Document portability, source embedding, history retention, and renderer migration policies before comparing containers.

### 3. [major] [Fact] CPython, pybind11, and packaging solve different problems

**Claim/verdict:** The options in file 01 are not mutually exclusive. CPython is the interpreter; the Windows embeddable ZIP distributes it; pybind11 offers C++ binding/embedding helpers; PyInstaller freezes a Python-led application. pybind11 still needs CPython. The embeddable distribution does not require end users to launch `python.exe` or a batch file.

**Evidence:** [CPython embedding guide](https://docs.python.org/3/extending/embedding.html), [Windows embeddable distribution](https://docs.python.org/3.13/using/windows.html#the-embeddable-package), and [pybind11 embedding](https://pybind11.readthedocs.io/en/stable/advanced/embedding.html), verified online.

**Correction (Recommendation):** Compare independent axes: native C++ host versus Python host; C API versus binding helpers; in-process interpreter versus worker; private runtime layout versus a self-extracting delivery file. A native `UzPainter.exe` can initialize a bundled CPython DLL directly and expose an `uzpainter` module. This fits a C++ application without making PyInstaller its launcher.

### 4. [major] [Fact] Uncommenting `import site` does not install or make pip officially supported

**Claim/verdict:** The embeddable distribution omits pip. `python3xx._pth` controls import isolation/search paths and optionally imports `site`; it does not provide pip. The claimed pre-3.11 versus 3.11+ site policy is misleading, and `._pth` is not the ordinary site-packages `.pth` mechanism.

**Evidence:** [CPython Windows documentation](https://docs.python.org/3.13/using/windows.html#the-embeddable-package) says regular pip dependency management is unsupported for this distribution and recommends vendoring. The cited [issue 102169](https://github.com/python/cpython/issues/102169) concerns a user's modification of the compiled `site` module; its body does not establish the claimed default-policy transition.

**Correction (Recommendation):** Vendor a pinned, tested dependency set during packaging. Set an explicit private module path and initialization policy; enable `site` only if deliberately needed. Separate application dependencies from any optional user package installation workflow. Do not promise end-user pip support on the basis of uncommenting one line.

### 5. [major] [Fact] nanobind is mischaracterized, although its embedding-helper limitation is real

**Claim/verdict:** nanobind does not automatically release the GIL for arbitrary C++ functions. Its smaller/faster bindings are performance claims to evaluate on the actual API, not evidence of automatic multicore gains. The maintainer explicitly excludes interpreter embedding helpers; this does not mean nanobind-built extension modules can never be imported by an interpreter embedded through CPython's C API.

**Evidence:** [Maintainer discussion 302](https://github.com/wjakob/nanobind/discussions/302) confirms the out-of-scope embedding functionality. [nanobind function call guards](https://nanobind.readthedocs.io/en/latest/functions.html) explicitly show opt-in `nb::call_guard<nb::gil_scoped_release>()`.

**Correction (Recommendation):** Use pybind11 if a supported high-level embedding API is valuable; retain direct C API embedding plus nanobind extension bindings as a possible combination with additional integration work. Remove the unsupported “v0.7+, 2024” provenance and localized-locking scalability inference. Neither binding library makes shared renderer objects thread-safe.

### 6. [major] [Fact] GIL-free Python is neither a PyInstaller switch nor a prerequisite for parallel C++ bakes

**Claim/verdict:** `Py_NOGIL` is not the stated CPython configuration mechanism. Python 3.13 free threading is a separate optional interpreter build; extension compatibility matters and imports may re-enable the GIL. Conventional CPython can dispatch parallel native work when bindings release the GIL or enqueue work in the C++ scheduler. The GIL does not universally block C++ threads.

**Evidence:** [CPython free-threading guidance](https://docs.python.org/3.13/howto/free-threading-python.html) identifies `Py_GIL_DISABLED` and possible GIL re-enabling. [pybind11 miscellaneous/threading documentation](https://pybind11.readthedocs.io/en/stable/advanced/misc.html) explains explicit GIL release and module thread-safety obligations. The [pybind11 changelog](https://pybind11.readthedocs.io/en/stable/changelog.html#version-3-0-0-july-10-2025) places its substantial subinterpreter support in 3.0, not the cited 2.13.0 release.

**Correction (Recommendation):** Start with a pinned conventional interpreter and native job dispatch; justify free threading or isolated-GIL subinterpreters with a measured Python workload. CPython 3.12 permits separately configured interpreter GILs, but safe extension support, object isolation, interpreter lifetime, and host locks remain requirements. Catch Python exceptions at the embedding boundary; an ordinary script exception is not automatically a process crash. Native memory faults still share the host's failure domain.

### 7. [major] [Fact] Executable size and static-linking promises are unconfirmed

**Claim/verdict:** File 01 gives inconsistent ranges for embeddable Python, frozen executables, and pybind11 binaries without specifying compressed download versus installed footprint, architecture, dependencies, or build flags. The official Windows bundle supplies DLLs; adding pybind11 does not turn CPython and native `.pyd` dependencies into one statically linked executable. PyInstaller one-file extraction is real, but its stated 1–2-second cost is unconfirmed.

**Evidence:** [CPython Windows distribution layout](https://docs.python.org/3.13/using/windows.html#the-embeddable-package) and [PyInstaller operating modes](https://pyinstaller.org/en/stable/operating-mode.html), verified online. Static-linking/dependency consequences: own knowledge, high confidence; no Windows build performed.

**Correction (Recommendation):** Define whether “standalone .exe” means one entry point with bundled runtime files, one delivery file that extracts at launch, or one executable with no adjacent/extracted dependencies. Measure the same dependency inventory under each candidate. Treat custom static CPython builds and static extension registration as a separate integration project. Keep all published footprint/startup ranges unconfirmed until measured.

### 8. [minor] [Fact] Painter's Python version is correct, but the cited page does not prove its host architecture

**Claim/verdict:** Painter 12.0's update to Python 3.13 is confirmed. The cited API overview merely documents a scripting API; it does not prove the claimed executable location or C++ initialization technique. A `python.exe` path alone also cannot establish whether the application's scripting interpreter is in-process.

**Evidence:** [Adobe Painter 12.0 release notes](https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/release-notes/version-12-0) versus the cited [API overview](https://experienceleague.adobe.com/en/docs/substance-3d-dev/painter-python/api/api-overview).

**Correction (Recommendation):** Cite the release notes for the version. Mark the installation path and embedding implementation **unconfirmed** in this review. UzPainter can select a supported host design without reverse engineering Painter's binary.

### 9. [blocker] [Fact] BC7 and conventional UASTC LDR 4×4 are 8 bits per pixel

**Claim/verdict:** “BC7 @ 0.5 bpp” and “UASTC mode 4 bpp” are false for the formats being compared. BC7 uses a 128-bit block for 16 texels; conventional UASTC LDR 4×4 also uses 8 bpp before supercompression. The claimed 0.5 MB BC7 4K texture is therefore false.

**Evidence:** [Microsoft BC7 format](https://learn.microsoft.com/en-us/windows/win32/direct3d11/bc7-format), [BC format/block-size table](https://learn.microsoft.com/en-us/windows/win32/direct3d11/texture-block-compression-in-direct3d-11), and [Basis Universal format descriptions](https://github.com/BinomialLLC/basis_universal), verified online. Basis describes ETC1S as roughly 0.3–3 bpp; that is an approximate quality/content-dependent range, not a fixed GPU bitrate or a universal file-size bound. The following sizes are arithmetic, not benchmarks.

**Correction (Fact):** For **4096 × 4096**, BC7 base level is `4096 × 4096 × 8 / 8 = 16,777,216 bytes = 16 MiB`, excluding headers. A full mip chain is approximately **21.33 MiB**, with small block-rounding overhead. Raw RGBA8 base level is **64 MiB**; raw single-channel R8 is **16 MiB**. BC1/BC4 use 4 bpp; BC3/BC5/BC6H/BC7 use 8 bpp. Zstd/BasisLZ disk size is separate from the decoded GPU allocation.

### 10. [major] [Fact] bc7enc_rdo provenance, build requirements, and licensing are mixed

**Claim/verdict:** It is not described by its upstream as an AMD Compressonator fork. The cited `_devel` repository says it is an archive and points to the newer repository. ISPC is optional: upstream can build with `bc7enc.cpp` or `bc7e.ispc`; native C++ entry points do not need language bindings. The small encoder and the complete RDO suite are not both a single-header library.

**Evidence:** [Archived development repository](https://github.com/richgel999/bc7enc_rdo_devel), [current bc7enc_rdo repository](https://github.com/richgel999/bc7enc_rdo), and its [component license file](https://raw.githubusercontent.com/richgel999/bc7enc_rdo/master/LICENSE). `bc7e.ispc` is Apache-2.0; most other code offers MIT/public-domain alternatives, with separately identified dependencies.

**Correction (Recommendation):** Pin the actual upstream revision and chosen encoder backend. RDO changes lossy block choices to improve subsequent entropy compression; it does **not** reduce BC7's fixed GPU bitrate or ordinary un-supercompressed DDS payload size. Compare decoded quality and BC7-plus-Zstd size. “Fastest CPU encoder,” maintenance status, and bake acceleration are unconfirmed; texture encoding is a separate stage from geometric baking.

### 11. [major] [Fact] Encoder capabilities and licenses need a component-level audit

| Encoder | Verified correction and evidence | Implication / recommendation |
|---|---|---|
| Intel ISPC Texture Compressor | **Fact:** Its [license](https://raw.githubusercontent.com/GameTechDev/ISPCTextureCompressor/master/license.txt) is MIT, not Apache-2.0. Its [README](https://github.com/GameTechDev/ISPCTextureCompressor) lists BC1, BC3, BC4, BC5, BC6H, BC7, ETC1, and LDR ASTC; “BC1–5” overstates BC2 coverage. | **Recommendation:** Treat ISPC as a build-time CPU SIMD dependency, not GPU acceleration. Current maintenance and comparative maturity are unconfirmed. |
| AMD Compressonator | **Fact:** The core [license](https://raw.githubusercontent.com/GPUOpen-Tools/compressonator/master/license/license.txt) is MIT. [SDK documentation](https://compressonator.readthedocs.io/en/stable/developer_sdk/cmp_compressonator/) and [revision notes](https://compressonator.readthedocs.io/en/latest/revisions.html) establish BC codecs, CPU/GPU paths, and KTX2 support with backend limitations. | **Recommendation:** Check the selected SDK/library/plugin build and dependency notices. KTX2 I/O alone does not prove all Basis/UASTC modes are exposed by the chosen library API. These coverage/maturity claims are unconfirmed without a version-specific check. |
| DirectXTex | **Fact:** A compiled C++ processing library, not a header-only encoder. Its [repository](https://github.com/microsoft/DirectXTex) states MIT licensing and additional toolchains/WSL support. [Compression API](https://github.com/microsoft/DirectXTex/wiki/Compress) includes CPU codecs and D3D11 DirectCompute BC6H/BC7 encoding. | **Recommendation:** Retain it as a serious Windows candidate. GPU compression is not directly a D3D12 API path; evaluate device/resource transfer cost against UzEngine. “Only MSVC” and “only basic BC codecs” are misleading. |
| NVIDIA NVTT 3 | **Fact:** The [SDK page](https://developer.nvidia.com/gpu-accelerated-texture-compression) advertises CUDA acceleration **and CPU fallback**. The [Exporter page](https://developer.nvidia.com/texture-tools-exporter) is a different product surface; its Turing requirement concerns an optional super-resolution feature, not all BC encoding. | **Recommendation:** Do not claim NVIDIA hardware is mandatory for the library, an OpenGL encoder backend, Turing-only BC encoding, or a universal speed lead. Exact NVTT 3 redistribution/EULA terms were **not verified online** here; proprietary distribution is consistent with own knowledge, medium confidence. Obtain the license for the selected SDK artifact, not an unrelated NVIDIA EULA. |

### 12. [major] [Fact] DDS versus KTX2 is a container choice; Basis is a payload/transcoding choice

**Claim/verdict:** DDS does store BC payloads, mipmaps, arrays, and cubemaps. “Universal engine support” and BC support on “all major GPUs” are overbroad. GPU format support depends on device/API and importing a file is not the same as directly uploading its blocks. KTX2 can hold native BC7 or uncompressed pixels, as well as Basis payloads; it does not inherently require transcoding.

**Evidence:** [KTX2 specification](https://registry.khronos.org/KTX/specs/2.0/ktxspec.v2.html) and [KTX-Software](https://github.com/KhronosGroup/KTX-Software), verified online. DDS feature assessment and hardware/import distinction: own knowledge, high confidence; the document's Wikipedia citation was replaced with primary evidence where available.

**Correction (Recommendation):** Compare DDS/BC7, KTX2/native BC7 with optional per-mip Zstd, and KTX2/Basis as distinct alternatives. Per-mip supercompression retains mip-level indexed access but must be inflated before GPU upload. Runtime memory depends on the selected final format; transcoding UASTC to BC7 does not itself lower BC7 GPU memory. Select export profiles by destination loader, GPU capability, linear/sRGB interpretation, and mip requirements.

### 13. [major] [Fact] Unreal DDS support is version-dependent; precompressed pass-through is unconfirmed

**Claim/verdict:** Do not replace the original claim with the equally overbroad statement that Unreal only imports DDS cubemaps. Epic's older [4.27 import guide](https://dev.epicgames.com/documentation/en-us/unreal-engine/texture-import-guide?application_version=4.27) restricts DDS to cubemaps; the inspected [5.6 texture documentation](https://dev.epicgames.com/documentation/en-us/unreal-engine/textures-in-unreal-engine?application_version=5.6) explicitly lists **DDS cubemap or 2D**. Neither citation establishes general native KTX2 import or preservation of supplied BC7 blocks through cooking.

**Evidence:** Those versioned Epic sources, verified online. No Unreal importer or cooked output was executed/inspected.

**Correction (Recommendation):** Name the actual Unreal version and importer/plugin. Verify accepted DDS pixel formats, mip handling, source retention, and cooking behavior before promising “already compressed” exports. PNG/TGA/EXR are reasonable source interchange candidates according to channel needs; native BC exports can target UzEngine directly after its loader is checked. Keep KTX2 import and BC7 pass-through **unconfirmed** rather than extrapolating from file-extension support.

### 14. [major] [Fact] ORM requires linear data interpretation, not one mandatory Unreal compression preset

**Claim/verdict:** `sRGB = false` is correct for numeric ORM masks. `Masks (no sRGB)` is a common suitable preset, but ORM is not rejected merely because a different appropriate linear-data preset is selected. R=AO, G=roughness, B=metallic is a convention implemented by material wiring, not a universal Unreal-enforced layout. “Masks” does not automatically mean BC7.

**Evidence:** Epic's [texture compression settings](https://dev.epicgames.com/documentation/es-mx/unreal-engine/texture-compression-settings?application_version=4.27) and current [TextureCompressionSettings API](https://dev.epicgames.com/documentation/en-us/unreal-engine/python-api/class/TextureCompressionSettings) distinguish Masks from BC7; the API describes Masks as the same compression as Default. Material-wiring consequence: own knowledge, high confidence. The original third-party guide is insufficient to establish a mandatory engine requirement.

**Correction (Recommendation):** Define an automated destination preset with channel routing, sRGB flag, sampler interpretation, chosen compression, and platform cook settings. Evaluate errors per channel; roughness/metallic/AO channels are independent and should not be judged only by a perceptual RGB metric. A different packing is valid when the consumer's material agrees.

### 15. [major] [Fact] glTF occlusion is core, and glTF packaging was incompletely analyzed

**Claim/verdict:** Core glTF metallic-roughness uses G for roughness and B for metallic. Core `material.occlusionTexture` samples R; sharing the same image for both bindings does **not** require an occlusion extension. Core images need not be “inline”: URI/data-URI images and bufferView-backed images are supported. A GLB can embed image bytes in its BIN chunk.

**Evidence:** [glTF 2.0 specification](https://registry.khronos.org/glTF/specs/2.0/glTF-2.0.html), verified online.

**Correction (Recommendation):** Describe `.gltf` plus external assets versus `.glb` packaging explicitly. For Basis textures, [KHR_texture_basisu](https://github.com/KhronosGroup/glTF/tree/main/extensions/2.0/Khronos/KHR_texture_basisu) permits ETC1S/BasisLZ and UASTC with optional Zstd, rather than arbitrary native-BC KTX2 images. Decide fallback PNG/JPEG images and `extensionsRequired` behavior. The extension's recommendation to prefer UASTC for non-color textures supports the original caution about ORM/normals, but still requires fidelity testing. Neither glTF nor GLB standardizes a Painter layer/effect project or BC7 Unreal pass-through.

### 16. [major] [Fact] Lossless project preservation, image formats, and export compression are conflated

**Claim/verdict:** PNG losslessly preserves supported integer samples; BC7, ETC1S, and UASTC are lossy texture encodings. Comparing their sizes as if they offer identical archive fidelity is misleading. TIFF is not limited to LZW/PackBits, and PNG's 8/16-bit channel statement does not cover float intermediates. Wrapping PNG in Zstd is lossless, not “near-lossless,” and does not guarantee a useful second compression pass.

**Evidence:** [OpenEXR technical introduction](https://openexr.com/en/latest/TechnicalIntroduction.html) documents HALF/FLOAT/UINT and lossless versus lossy codecs; [Zstd](https://github.com/facebook/zstd) is lossless. PNG/TIFF assessment: own knowledge, high confidence, not independently verified online beyond the document's cited general PNG compression discussion.

**Correction (Recommendation):** Preserve required working precision: R16/RG16 integer where appropriate; R16F/RG16F/RGBA16F or 32-bit float for relevant height, displacement, HDR, and bake intermediates. Use raw typed tiles plus lossless compression, suitable TIFF, or lossless EXR modes. Converting a 32-bit float working buffer to half is a quantization decision, even if the EXR codec itself is lossless. Apply BC/Basis only to explicitly lossy caches or delivery exports.

### 17. [major] [Fact] The quantitative claims are not decision-grade evidence

**Claim/verdict:** No inspected cited source establishes the documents' complete size/timing claims for UzPainter. All of the following are **unconfirmed** and should not determine architecture:

| Source file | Unsupported or misleading estimates |
|---|---|
| 01 | All runtime/executable MB ranges; relative “smallest” ranking; fixed 1–2-second PyInstaller startup cost. |
| 02 | Fixed 4K PNG sizes and “10×” comparison; fixed Zstd/PNG speed ratios; sub-50-ms 4K transcoding; 50–70% disk savings; 50–200-ms CPU BC7 encoding; 100–300-MB input to 5–10-MB UASTC; blanket 50% Zstd gain and “fastest” encoder claims. |
| 03 | 4% ZIP-directory overhead; 40%, 25–35%, 20–30%, and 45% container ratios; typical 4K projects at 30–50 MB or 10–20 MB; blanket 20–30% gains from an outer Zstd wrapper. |
| 04 | Generic 1–10-ms IPC latency; relative binary-size and “production/enterprise-grade” rankings without an evaluated implementation. |

**Evidence:** Missing workload definitions and reproducible measurements in the reviewed documents; fixed-size arithmetic in finding 9. [Zpng](https://github.com/catid/Zpng) reports its own experiment, not a universal PNG-wrapper benchmark: its custom predictor/Zstd format is not simply standard PNG bytes compressed again.

**Correction (Recommendation):** Report hardware, builds, quality preset, channels/bit depth, layer/tile count, mip chain, dataset, warm/cold conditions, and quality error. Measure compressed distribution, installed files, GPU residency, save bytes written, save latency, and recovery separately. Entropy and payload design dominate container ratios; an uncompressed container has no inherent 45% reduction.

### 18. [major] [Fact] The supplied HDF5 signatures are valid evidence, but not a cause-of-bloat analysis

**Claim/verdict:** The supplied signature `89 48 44 46 0d 0a 1a 0a` matches HDF5. The accepted local observations are **879,248,615**, **1,087,438,533**, and **1,190,431,812 bytes** for v5, v6, and v6b. They support identifying these particular files as HDF5 containers; they do not establish every `.spp` variant, the application's schema, HDF5 superblock version, or why those files are large. “HDF5 v5” is the format family, not a detected library/schema version.

**Evidence:** User-supplied Claude verification, high confidence as reported, not independently repeated. Size attribution to geometry/cache/undo is explicitly an untested hypothesis in file 03.

**Correction (Recommendation):** Retain that baseline with byte units. Compare logically equivalent projects and retained inputs/history; a smaller flattened or dependency-incomplete save does not satisfy the same requirement. Inspect dataset sizes, chunk layouts, filters, duplicates, free space, and embedded assets through a permitted read-only format inspection before attributing bloat to HDF5. Cache omission and graph representation may matter more than switching the outer container.

### 19. [major] [Fact] HDF5 supports partial access and updates; checksums and crash safety are conditional

**Claim/verdict:** “Poor random access for single-layer extraction” and “rewrites structure on save” are not inherent HDF5 properties. A well-designed layer/tile dataset layout supports partial reads/writes. Checksum availability does not mean all payloads are automatically protected, nor does checksum detection provide atomic project transactions.

**Evidence:** HDF Group's [chunking guide](https://support.hdfgroup.org/documentation/hdf5-docs/advanced_topics/chunking_in_hdf5.html), [filters](https://support.hdfgroup.org/documentation/hdf5/latest/_h5_z__u_g.html), and [chunking issues](https://support.hdfgroup.org/documentation/hdf5/latest/hdf5_chunk_issues.html). Fletcher32 is a configured chunk filter; compressed chunks can require read/modify/write and create free-space holes. The current [HDF5 license](https://github.com/HDFGroup/hdf5/blob/develop/LICENSE) confirms BSD-3-Clause.

**Correction (Recommendation):** Keep HDF5 in the benchmark set. Evaluate chunk granularity, filter availability/deployment, chunk caching, fragmentation/repacking, threading, and a recoverable commit strategy. An HDF5-zstd design needs the relevant filter implementation deployed or deliberately linked. Do not equate SWMR/concurrent-reader mechanisms with SQLite-style general transactions; AI inspection is possible through an exposed schema and readers.

### 20. [major] [Fact] ZIP incremental save is possible by design, not “trivial replace one file”

**Claim/verdict:** ZIP's directory gives indexed access to members, but does not specify an atomic in-place update protocol for a mutable project. In particular, the recommended libzip writes a new temporary archive and replaces the original; unchanged members may be copied without re-encoding, yet the archive still incurs substantial I/O. Appending history can avoid rewriting existing payloads only with a deliberate append/commit implementation.

**Evidence:** [libzip's modification model](https://libzip.org/documentation/libzip/) and [ZIP APPNOTE](https://pkware.cachefly.net/webdocs/casestudies/APPNOTE.TXT), verified online.

**Correction (Recommendation):** Distinguish logical incremental edits, re-encoding avoided, bytes rewritten, and atomicity. An append scheme needs immutable generation names, explicit manifest selection, a committed directory/footer, recovery from incomplete tails, and compaction to reclaim obsolete entries. Do not rely on duplicate-name interpretation across tools. ZIP members can be located without decompressing other members; a compressed selected member still needs decoding, and subregion access within a PNG is a different issue.

### 21. [major] [Fact] ZIP CRC and JSON readability do not establish project recovery

**Claim/verdict:** Per-member CRC32 detects many accidental errors but does not repair data or preserve a consistent manifest/index. Losing the directory or authoritative manifest can affect access to many members. Versioned manifest names and ignoring orphans alone do not make a committed project recoverable. Custom chunks are not inherently less resilient than ZIP; this depends on their integrity and commit design.

**Evidence:** [ZIP specification](https://pkware.cachefly.net/webdocs/casestudies/APPNOTE.TXT) for CRC/directory structure; recovery/transaction assessment: own knowledge, high confidence, not verified online for a proposed UzPainter implementation.

**Correction (Recommendation):** Specify failure boundaries: interrupted write, missing chunk, damaged manifest, and damaged index. Use validated lengths, checksums/hashes, independently recoverable committed generations, and a complete previous commit or atomic replacement strategy. Set bounds on decoded data and reference validation. Verify crash recovery rather than rating a format “resilient” from its checksum field.

### 22. [major] [Fact] Zstd does not imply whole-project decompression or whole-archive loss

**Claim/verdict:** An ordinary single outer `.tar.zst`/`.zip.zst` frame is inconvenient for random seeks; this does not describe all Zstd layouts. A stream can be decoded until a selected early member is reached without necessarily decoding the entire archive. Independent indexed frames/chunks or a seekable format allow bounded access. Corruption loss is layout-dependent, not automatically the entire logical project.

**Evidence:** [Zstd API/manual](https://facebook.github.io/zstd/zstd_manual.html) for independent frames and streaming; [seekable format implementation/specification directory](https://github.com/facebook/zstd/tree/dev/contrib/seekable_format). [ZIP APPNOTE](https://pkware.cachefly.net/webdocs/casestudies/APPNOTE.TXT) assigns current Zstandard member compression method 93, distinct from an outer wrapper.

**Correction (Recommendation):** Compare per-tile/per-blob Zstd inside a container to outer archive compression. Use dictionaries only with stored identity/version and decoder availability. Zstd offers a BSD-3-Clause **or** GPLv2 license choice; the BSD choice is viable. The original claim that Zstd replaces compression in standard WebP is false: [Google's WebP specification](https://developers.google.com/speed/webp/docs/webp_lossless_bitstream_specification) defines VP8L coding, not Zstd.

### 23. [minor] [Fact] OpenRaster/USDZ descriptions mix correct structure with incorrect ownership and ratios

**Claim/verdict:** The [OpenRaster baseline](https://www.openraster.org/baseline/file-layout-spec.html) supports the cited ZIP/XML/PNG layout, and the [0.0.6 site](https://www.openraster.org/) confirms that specification version. ORA is useful raster interchange, not a standardized PBR procedural project. Blend-mode counts and the application license examples in file 03 are unconfirmed and should not be used as compatibility evidence; GPL is not a permissive license.

**Evidence:** [OpenUSD USDZ specification](https://openusd.org/release/spec_usdz.html) confirms uncompressed, unencrypted ZIP members and 64-byte payload alignment. It also notes that contained images can already be compressed.

**Correction (Recommendation):** USDZ belongs to OpenUSD, not Khronos. No ZIP compression does not mean no compressed image payloads. Its unsupported 45% size ratio is invalid. Keep USDZ/ORA as optional interchange concepts; neither defines UzPainter's full semantic graph. Distinguish file-format specifications, individual libraries, applications, and their licenses; a custom file format is not “typically permissive” by technical necessity.

### 24. [minor] [Fact] AI inspection depends on a stable exposed schema, not text-only storage

**Claim/verdict:** JSON/XML metadata helps inspection, but raster pixels are not “human-readable,” and a binary container is not inherently inaccessible to AI. HDF5, SQLite, and custom chunk storage can expose structured metadata and previews through a stable reader/MCP resource. USDA is a textual scene description; USDZ is not generally XML plus JSON-like USD.

**Evidence:** Own technical knowledge, high confidence; not verified online for UzPainter's eventual inspection API. [SQLite's application/container guidance](https://sqlite.org/whentouse.html) demonstrates queryable, inspectable application-file storage.

**Correction (Recommendation):** Require `inspect_project`, schema/version reporting, layer/channel enumeration, hashes, dependency provenance, and selective preview/plane extraction in every candidate. Keep an independently readable specification and diagnostic reader. This satisfies AI-only operation without choosing ZIP solely for unzip convenience.

### 25. [major] [Fact] The cited MCP revision is valid, but the document mixes protocol generations

**Claim/verdict:** [The specification landing page](https://modelcontextprotocol.io/specification) resolved to 2026-07-28; rejecting that date as invented would be incorrect. Stdio and Streamable HTTP are the standard bindings, and custom transports are allowed. However, the current revision has a per-request metadata model and disallows server-initiated JSON-RPC requests; the description of elicitation as an ordinary server request is stale.

**Evidence:** [Current transport overview](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports), [message patterns](https://modelcontextprotocol.io/specification/2026-07-28/basic/patterns), and [elicitation](https://modelcontextprotocol.io/specification/2026-07-28/client/elicitation). Server interactions now use `InputRequiredResult` with client retries/input responses. The current [stdio binding](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/stdio) does not support the document's attribution of a universal client-stdio SHOULD to this revision.

**Correction (Recommendation):** Pin protocol generation and compatible SDK release. Describe legacy initialize/session behavior only in an explicit compatibility path. Stdio still uses newline-delimited UTF-8 JSON-RPC, exclusive protocol stdout, and stderr logging; escaped newlines in JSON strings are different from literal embedded line breaks. Cancellation is `notifications/cancelled` on stdio, while current Streamable HTTP abandons a request by closing its response stream. Progress/cancellation/elicitation should not all be claimed as newly introduced in July 2026.

### 26. [major] [Fact] Current Tasks concepts are correct; example payloads and support assumptions are incomplete

**Claim/verdict:** The document correctly describes current per-request extension support, `server/discover`, `tasks/get`, `tasks/update`, terminal results in `tasks/get`, and optional `notifications/tasks` through `subscriptions/listen`. These must not be “corrected” into the older 2025 task API. Its abbreviated `CreateTaskResult` examples nevertheless omit wire-required fields.

**Evidence:** [Tasks extension overview](https://modelcontextprotocol.io/extensions/tasks/overview) and [versioned 2026-07-28 schema](https://raw.githubusercontent.com/modelcontextprotocol/ext-tasks/main/schema/2026-07-28/schema.ts), verified online. The schema defines a flat result with `resultType: "task"`, `taskId`, `status`, `createdAt`, `lastUpdatedAt`, and `ttlMs`; `pollIntervalMs` is optional. Standard task-operation replies use `resultType: "complete"`.

**Correction (Recommendation):** Generate/validate payloads against that schema and actually negotiate extension support. The server must durably create a task before replying; a protocol handle does not implement persistence or a baker scheduler. Keep ordinary job-handle tools as a valid fallback, not a deprecated mistake, for hosts without Tasks support. Exact Claude/client and selected Python SDK extension support are **unconfirmed**; check separately from core 2026 support. Honor polling guidance and distinguish transport-request cancellation from cancellation of a durable job.

### 27. [major] [Fact] SDK availability is real, but versions, provenance, APIs, and licenses are not interchangeable

| SDK/framework | Verified assessment | Consequence |
|---|---|---|
| Official Python SDK | **Fact:** Current [package metadata](https://raw.githubusercontent.com/modelcontextprotocol/python-sdk/main/pyproject.toml) requires Python **3.10+**, identifies MIT licensing, and names the MCP project organization; “3.8+” and generic “MIT/Apache” are wrong for this inspected source. The [migration guide](https://py.sdk.modelcontextprotocol.io/migration/) documents v2 `MCPServer`, replacing the SDK's v1 high-level `FastMCP`. | **Recommendation:** Pin an actual released package; current repository/docs are not a blanket release guarantee. Distinguish core protocol support from optional Tasks support. |
| Official TypeScript SDK | **Fact:** The [current repository](https://github.com/modelcontextprotocol/typescript-sdk) documents v2 packages and Node/Bun/Deno installation. Its license statement assigns Apache-2.0 to new contributions and retains MIT for existing code. | **Recommendation:** Keep the real mixed licensing description; do not incorrectly relabel it all MIT or treat the two licenses as freely interchangeable. Avoid relying on decorators as the defining API. |
| Gopher C++ SDK | **Fact:** The [repository](https://github.com/GopherSecurity/gopher-mcp) states **Apache-2.0**, not merely a commercial license. It advertises multiple transports and bindings. “Mature since 2024,” enterprise readiness, and 2026 protocol/Tasks conformance were not independently established. | **Recommendation:** Assess Windows build, dependency inventory, tests, maintenance, and protocol generation before adopting it. No evaluated binary-size comparison exists. |
| Standalone FastMCP | **Fact:** [Its documentation](https://gofastmcp.com/getting-started/welcome) distinguishes the standalone framework from the high-level API incorporated into the official SDK. The [standalone license](https://raw.githubusercontent.com/jlowin/fastmcp/main/LICENSE) is Apache-2.0. Docs explicitly track `main` and can describe unreleased features. | **Recommendation:** Choose either the official SDK's release API or the separately versioned standalone framework. Python Pydantic schemas and TypeScript/Zod schemas are different integrations, not a generic cross-language compatibility guarantee. |

**Evidence (Fact):** The [official SDK directory](https://modelcontextprotocol.io/docs/2026-07-28/sdk) also lists C#, Go, Rust, Ruby, Java, Swift, PHP, and Kotlin. C++ is absent from that inspected official list; the original lack-of-official-C++ conclusion remains supported, but “from Anthropic” is too narrow a definition of official ownership.

### 28. [major] [Fact] The Python server sketch mixes high-level decorators with the wrong class

**Claim/verdict:** `from mcp.server import Server` plus `@server.tool()` and argument-free `@server.resource()` does not form the demonstrated high-level server in the inspected SDK. The example also lacks transport startup. Its C++ sketch uses `args` where `tools/call` uses `arguments` and omits JSON-RPC envelope/version/capability details.

**Evidence:** [Official Python SDK example](https://github.com/modelcontextprotocol/python-sdk) uses `MCPServer` and URI-bearing resource decorators; its [v1-to-v2 migration guide](https://py.sdk.modelcontextprotocol.io/migration/) explicitly distinguishes high-level server decorators from low-level `Server`. [MCP tools](https://modelcontextprotocol.io/specification/2026-07-28/server/tools) defines the call shape.

**Correction (Recommendation):** Replace the sketch with an example for a pinned release, including actual stdio startup and schema-valid results. A Python SDK handles the Python endpoint; it does not eliminate protocol handling from a C++ peer manually writing JSON-RPC. Use a real C++ client implementation or define a separate internal command bridge instead of implying the handwritten pipe sketch is complete.

### 29. [blocker] [Fact] The recommended subprocess topology does not specify how the AI controls the live C++ renderer

**Claim/verdict:** In file 04 the C++ app launches a Python **MCP server** and then calls it as an MCP **client**, while the external AI is also supposed to connect to that same server. One stdio pipe pair is not a shared multi-client endpoint. A `.pyd` loaded in the worker also cannot directly access ordinary C++ objects in the parent process. “Embed CPython” and “launch bundled Python” are distinct designs.

**Evidence:** [MCP stdio binding](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/stdio) establishes client-launched subprocess streams. Process address-space/state ownership consequences: own knowledge, high confidence, not verified online for UzPainter code.

**Correction (Recommendation):** Choose an explicit state owner. One straightforward option is for the AI host to launch `UzPainter.exe --mcp`: the MCP server, C++ engine, and optional embedded Python all reside in that single process. Another is an AI-launched bridge that talks to a resident C++ process over a separately defined named-pipe/socket command API. A third is a loopback Streamable HTTP endpoint for a persistent application or multiple clients. Stdio being inter-process relative to the AI host does not require an extra Python subprocess inside UzPainter.

### 30. [major] [Fact] Isolation, concurrency, and local HTTP trade-offs are overstated

**Claim/verdict:** A worker isolates interpreter/native-worker faults, but not a renderer still running in the parent. Python exceptions can be handled; they are not inherently fatal. A Python subprocess can still have GIL contention, native races, and an async event loop blocked by a synchronous bake call. The document's “GIL not a concern” and categorical rejection of in-process embedding/local HTTP do not follow.

**Evidence:** Own knowledge, high confidence, not verified online for the proposed implementation; the GIL mechanisms are covered by finding 6. [Current transport overview](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports) supports both standardized bindings rather than restricting HTTP to geographically remote services.

**Correction (Recommendation):** Keep long native work off the protocol reader/event loop and serialize or version mutations of shared project state. Compare copy/serialization cost and worker crash recovery to direct native access. Use local HTTP when persistent lifecycle or multi-client access justifies it; use stdio when the host should own one process lifecycle. HTTP then needs the protocol's applicable Origin/authentication/endpoint rules, not merely a session-management cost borrowed from older revisions. No progress-bar UI is needed for the specified AI-only product; expose status to the client.

### 31. [major] [Fact] Tool descriptions are not validation or a complete AI-observation contract

**Claim/verdict:** JSON Schema inputs and optional outputs are correctly identified, but the example describes resolution/strength ranges without schema bounds. Its “required fields” heading incorrectly treats the description and output schema as mandatory. Output schemas and structured results already existed in 2025-06-18; they are not first introduced in 2026. A filesystem path inside `image_url` is not automatically an image observable by a remote client.

**Evidence:** [Current tools specification](https://modelcontextprotocol.io/specification/2026-07-28/server/tools) and [2025-06-18 changes](https://modelcontextprotocol.io/specification/2025-06-18/changelog), verified online; observation/accessibility consequences: own knowledge, high confidence.

**Correction (Recommendation):** Validate allowed resolutions, numeric bounds, channel enums, object references, project revisions, and cross-field constraints in both schema and native execution. Return schema-conforming `structuredContent` and the generation-appropriate standard result envelope. Provide explicit image content/resources or accessible artifact URIs for previews, with hashes and channel/color metadata. Resources can support change notifications; “passive” should not imply they cannot update. Keep inspection and mutation methods aligned across Python and MCP.

### 32. [minor] [Fact] Format licenses and implementation licenses are repeatedly conflated

**Claim/verdict:** “PNG under libpng license,” “TIFF public domain,” “ZIP public domain,” and “KTX under Khronos license” are not sufficiently precise statements about the code UzPainter would redistribute. A specification's usage terms and a library's license are different. The documents' CPython PSF, pybind11 BSD-3-Clause, nanobind BSD-3-Clause, and PyInstaller GPL-with-exception classifications are consistent with the inspected licensing sources. PyInstaller also identifies a few Apache-2.0 files; its exception permits commercial bundles subject to dependencies' licenses, rather than relicensing PyInstaller itself as permissive.

**Evidence:** [Python license history/terms](https://docs.python.org/3/license.html), [pybind11 license](https://github.com/pybind/pybind11/blob/master/LICENSE), [nanobind license](https://github.com/wjakob/nanobind/blob/master/LICENSE), and [PyInstaller licensing](https://pyinstaller.org/en/stable/license.html). [ZIP APPNOTE](https://pkware.cachefly.net/webdocs/casestudies/APPNOTE.TXT) has its own specification terms; [KTX2 specification](https://registry.khronos.org/KTX/specs/2.0/ktxspec.v2.html) and [KTX-Software licensing entry](https://github.com/KhronosGroup/KTX-Software) are separate artifacts. Encoder-specific corrections are in findings 10–11; SDK corrections are in finding 27.

**Correction (Recommendation):** Record exact redistributed library revisions, selected license branches, and bundled third-party notices. Do not infer a format's unrestricted code redistribution from adoption, nor propagate the main repository's license to every vendored component. Legal redistribution approval itself is outside this technical review.

## Relevant missing options and ignored trade-offs

### M1. [Recommendation] Direct CPython C API embedding

**Option:** Initialize a private interpreter with `PyConfig`/`Py_InitializeFromConfig`, register the native module, and add pybind11 only where its converters/lifetime helpers are useful. CPython's [embedding guide](https://docs.python.org/3/extending/embedding.html) and [initialization configuration](https://docs.python.org/3.13/c-api/init_config.html) support this route.

**Trade-off:** Fewer wrapper dependencies and explicit control versus more reference-counting, error/lifetime, ABI, path, and thread-state code. Stable-ABI feasibility depends on the API actually used. pybind11 is a convenience/maintenance choice, not a required interpreter distribution or packager. An external Python client library talking to a native process is another Python API option if in-process plugin semantics are not required.

### M2. [Recommendation] Native MCP inside the existing executable

**Option:** A C++ MCP endpoint can read the executable's inherited stdin and write stdout while dispatching to the native command/job system. Optional CPython remains an API/plugin subsystem. The AI host launches this executable as its stdio subprocess; there is no mandatory additional interpreter process.

**Trade-off:** Direct state access and simpler process ownership versus a conformance/maintenance obligation for the C++ implementation. A bridge built with an official Rust/Go/C# SDK is also worth considering; it adds a language/runtime or FFI boundary but can reduce handwritten protocol work. For an already running renderer, Windows named pipes are useful **internal IPC**, but require a compatible bridge/custom transport for an ordinary external MCP host. Evidence: official [SDK directory](https://modelcontextprotocol.io/docs/2026-07-28/sdk); design assessment from own knowledge, high confidence.

### M3. [Recommendation] GPU encoder backends and purpose-specific CPU encoders

**Option:** Benchmark DirectXTex D3D11 BC6H/BC7, Compressonator's applicable OpenCL/DirectX backends, and NVTT CUDA with CPU fallback. Keep a CPU path for unsupported devices and controlled reproducibility. Small `rgbcx`, optional `bc7e`, and the upstream-mentioned `bc7f` are additional CPU candidates; their quality/maintenance/Windows integration are unconfirmed here.

**Trade-off:** GPU throughput versus device initialization, contention with baking/rendering, readback/upload costs, driver variation, and cancellation boundaries. Fastest compression and best RDO disk size are different objectives. Evidence: [DirectXTex API](https://github.com/microsoft/DirectXTex/wiki/Compress), [Compressonator revisions](https://compressonator.readthedocs.io/en/latest/revisions.html), [NVTT SDK](https://developer.nvidia.com/gpu-accelerated-texture-compression), and [bc7enc_rdo upstream](https://github.com/richgel999/bc7enc_rdo).

### M4. [Recommendation] Precision- and channel-specific texture formats

**Option:** Consider BC4 for a scalar delivery map, BC5 for two-component tangent normals, BC7 for appropriate multi-channel LDR exports, BC6H for suitable HDR exports, and uncompressed R16/R16F/R32F or multi-channel float maps where fidelity requires them. BC5 normal use requires defined Z reconstruction, sign/orientation, and renormalization. Preserve higher-precision authoritative data independently of these exports.

**Trade-off:** Storage/VRAM/sampling bandwidth versus channel error and float range/precision. Mip generation must respect linear color, normal vectors, alpha conventions, and mask semantics. Source swizzles and DirectX versus OpenGL normal Y convention must be explicit. Evidence: [Microsoft BC format table](https://learn.microsoft.com/en-us/windows/win32/direct3d11/texture-block-compression-in-direct3d-11) and own knowledge, high confidence; not verified online against UzEngine capabilities. Lossless EXR alternatives are supported by the [OpenEXR technical introduction](https://openexr.com/en/latest/TechnicalIntroduction.html).

### M5. [Recommendation] KTX2 with native BC blocks plus Zstd

**Option:** For a compatible UzEngine Windows loader, KTX2 can carry already encoded BC blocks with lossless per-mip supercompression, avoiding Basis transcoding while reducing disk size when the block stream permits it.

**Trade-off:** Inflate cost and library/container integration versus smaller distribution and mip streaming. DDS plus application-controlled per-chunk compression can reach a similar storage objective. Neither guarantees Unreal importer pass-through. Evidence: [KTX2 specification](https://registry.khronos.org/KTX/specs/2.0/ktxspec.v2.html). Suitability for UzEngine is a **Hypothesis**, not a verified local capability.

### M6. [Recommendation] A custom indexed chunk container with per-chunk Zstd

**Option:** Use independently compressed typed tiles/blobs, an inspectable versioned manifest, stable IDs/content hashes, and an append-only committed index. Store constants/procedural parameters rather than materializing every full-resolution plane. Permit copy-on-write updates and deduplication across history.

**Trade-off:** Small incremental writes, bounded layer/tile access, explicit corruption boundaries, and predictable cache eviction versus owning the parser/specification/migrations/recovery tooling. Compression chunk size trades ratio against access latency and rewrite amplification. mmap exposes encoded bytes, not decoded compressed pixels. Unknown chunks may be skipped only when declared optional; unknown authoritative effects cannot silently be ignored while claiming parity. Evidence: own design knowledge, high confidence; benefits for the actual dataset are **Hypotheses** until measured.

### M7. [Recommendation] SQLite as the whole project or as an index

**Option:** Store the layer graph, assets, committed revisions, jobs, and independently compressed tile BLOBs in SQLite. Alternatively use SQLite for metadata/indexing and external immutable blobs. Its official [application/container guidance](https://sqlite.org/whentouse.html) explicitly supports this class of use.

**Trade-off:** Atomic transactions, incremental page updates, SQL inspection, and mature recovery versus page/journal overhead, a single writer, large-BLOB access choices, and compaction. In [WAL mode](https://sqlite.org/wal.html), active state includes companion WAL/shared-memory files; a portable single-file snapshot needs a consistent backup/checkpoint strategy. External blob files are not atomically covered by a database transaction, so define publish ordering, integrity validation, and orphan collection. SQLite itself does not compress those BLOBs or provide complete image-payload corruption recovery.

### M8. [Recommendation] Chunked HDF5 with a documented UzPainter schema

**Option:** Per-layer/per-channel/per-tile datasets, chosen lossless filters, explicit schema/version metadata, and exposed JSON inspection can preserve partial access and precision without reproducing Painter's storage policy.

**Trade-off:** Existing typed-array tooling and partial I/O versus library/filter deployment, chunk-cache tuning, possible fragmentation, and application-defined commits/history. Treat HDF5 as a candidate to measure, not a proxy for Painter's observed file sizes. Evidence: HDF Group [partial compressed I/O documentation](https://support.hdfgroup.org/documentation/hdf5/latest/improve_compressed_perf.html).

### M9. [Recommendation] Separate a mutable working store from portable snapshots

**Option:** A loose content-addressed blob directory plus a transactional index can serve the active project; a consolidated ZIP/custom/SQLite snapshot can satisfy portable saving. A single-file native store is also possible if the portability requirement includes active editing.

**Trade-off:** Easier incremental writes, deduplication, diagnostics, and selective synchronization versus file-count overhead, multi-file consistency, garbage collection, and a snapshot operation. Undo/history need retained references and retention rules; they are not synonymous with disposable cache. Evidence: own knowledge, high confidence, not verified online for UzPainter. Exact space savings remain **Hypotheses**.

### M10. [Recommendation] A durable native job/state layer independent of MCP

**Option:** Define native job IDs, project revision inputs, progress, cancellation, result publication, and persistence. Map that system to the current Tasks extension when supported and ordinary job-handle tools otherwise.

**Trade-off:** Crash/reconnect recovery and one execution model shared by Python/MCP versus persistence and coordination work. Use idempotency keys/revision preconditions to prevent an AI retry from duplicating a bake or layer mutation. Serialize commits or reject stale revisions; cancellation must not publish half-written authoritative state. Send previews and artifact references rather than encoding huge images into routine JSON responses. Evidence: [Tasks requirements](https://modelcontextprotocol.io/extensions/tasks/overview); scheduling, retry, and commit recommendations from own knowledge, high confidence.

## Questions for the architect

1. **[Recommendation]** Does “same texture and render” mean identical encoded bytes, identical decoded values, or an explicitly approved error metric? Which Painter version/render mode is the reference, and who approves any tolerance?
2. **[Recommendation]** Is the replay input natural language or a frozen typed command sequence? How are interpretation, generator versions, seeds, and asset identities recorded to make replay deterministic?
3. **[Recommendation]** Must existing `.spp`, `.sbsar`, smart materials, generators, and proprietary resources be imported/executed with equivalent semantics? What compatible runtime implementations and redistribution rights are available?
4. **[Recommendation]** Which compositing, baking, tangent-space, shader/BRDF, light, and color-management behaviors must match Painter, and which are already available in UzEngine?
5. **[Recommendation]** Which state is authoritative: procedural graph, strokes, raster tiles, source meshes/assets, imported bakes, checkpoints? Which caches can be regenerated identically after a version change?
6. **[Recommendation]** What are the required channel types, working precision, texture-set/UV-tile limits, sparse storage behavior, and normal-map conventions? Is lossy storage ever acceptable inside the project?
7. **[Recommendation]** Does standalone mean one executable entry point, one self-extracting delivery file, or no external/extracted runtime files? Must operation and dependency loading be fully offline?
8. **[Recommendation]** Does the Python API require in-process plugin execution and arbitrary native packages, or can a Python client drive a C++ process? What package, ABI, interpreter, and crash-isolation commitments follow?
9. **[Recommendation]** Who owns the live project/renderer state, who launches the MCP process, and must multiple agents or a resident application attach simultaneously?
10. **[Recommendation]** Which exact MCP hosts, protocol revisions, SDK releases, and Tasks capabilities must interoperate? What fallback behavior is required for older clients and unsupported extensions?
11. **[Recommendation]** Which Unreal version/importer and UzEngine loader consume exports? Does “already compressed” mean delivered BC blocks, preserved cooked blocks, or simply compact interchange files?
12. **[Recommendation]** What per-map encoding error, mip filtering, channel packing, color flags, and device support are acceptable? Is a deterministic CPU path required alongside GPU encoders?
13. **[Recommendation]** What are the maximum save latency, bytes rewritten, memory budget, and acceptable disk growth per edit/history checkpoint? Must active saving remain a single physical file?
14. **[Recommendation]** What committed state must survive a crash, interrupted write, damaged chunk/index, or agent retry? Which atomicity, retention, compaction, and backup guarantees are part of acceptance?
15. **[Recommendation]** Which representative projects—including the three supplied body-piece versions—define the size benchmark, and what equivalent inputs/history/caches must each candidate retain? What inspection API lets an AI verify every saved channel and dependency?

