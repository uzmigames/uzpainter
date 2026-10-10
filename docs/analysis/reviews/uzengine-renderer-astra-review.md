# UzEngine renderer analysis — Astra technical review

## Executive summary

**Recommendation:** Do not approve the nine documents as an architecture baseline for Substance Painter output parity.
**Fact:** The module inventory is useful, and core DX12 compute, copy, format and material mechanisms exist; the 48 source checks below distinguish declarations from implementation.
**Fact:** The inspected working tree contains unresolved C++/HLSL merge conflicts, and several cited line ranges describe an older source layout (F02).
**Fact:** The cooked glTF-to-runtime conversion contains a concrete 32-byte/48-byte vertex-stride mismatch (F03).
**Fact:** Texture validation, graph baking, readback and exporter assumptions need substantial corrections (F04–F14).
**Recommendation:** Treat output parity as an independent acceptance contract covering bake algorithms, compositing, assets, color transforms and preview rendering (F01).
**Hypothesis:** A useful UzPainter can reuse selected engine infrastructure; matching Painter's output is **not confirmed** by this analysis or this review.

## Review scope and evidence rules

**Fact:** Reviewed all nine files in `E:\UzmiGames\UzPainter\docs\analysis\uzengine-renderer\`, against the current files in `E:\UzmiGames\UzEngine\` on 2026-10-10. Engine paths below are relative to that engine root; document paths are relative to the analysis directory. `HEAD` reported `19ffb9b94333f56d624eb1485192cf5c6d174bd0`, but the working tree is dirty; `git status --short` reports `UU` for `runtime/engine/renderer/passes/debug/inspector_pass_validate.cpp`. The commit identifier is therefore **not** an identifier for all inspected contents.

**Recommendation:** Read “confirmed” as confirmed by source inspection only. No compilation, engine execution, app control, GPU validation, benchmark or Painter comparison was performed. Runtime correctness and measured parity remain **not confirmed**. Negative searches are scoped to the named directories, not proof of universal absence. F02 records the snapshot limitation separately from errors in the analysis; the original author's source revision is **not confirmed**.

**Fact:** The only external technical check was Microsoft's DXR functional specification, to distinguish DXR 1.0 from inline ray tracing in F04. All engine implementation findings use local source evidence.

## Verdict by file

**Recommendation:** Severity counts refer to distinct numbered findings F01–F20 affecting each document, not to the number of failing sample rows. A finding may affect several documents. There are 3 blocker, 13 major and 4 minor findings overall. Snapshot finding F02 does not imply that the document author introduced the conflicts.

| File | Overall verdict | Findings by severity |
|---|---|---|
| `01-module-map.md` | **Recommendation:** Retain the inventory; reject blanket “reuse as-is” and outdated build ownership claims. | blocker 2 / major 5 / minor 0 |
| `02-headless-rendering.md` | **Recommendation:** Retain the mode distinction; qualify readiness, readback and determinism. | blocker 1 / major 2 / minor 2 |
| `03-rhi-capabilities-for-texturing.md` | **Recommendation:** Use as an API map, not a verified capability matrix. | blocker 1 / major 4 / minor 1 |
| `04-material-and-texture-standard.md` | **Recommendation:** ORM and normal decoding are grounded; the export contract is not ready. | blocker 0 / major 5 / minor 0 |
| `05-mesh-import.md` | **Recommendation:** Escalate the glTF conversion defect and correct high-poly processing assumptions. | blocker 1 / major 3 / minor 0 |
| `06-thirdparty-and-image-io.md` | **Recommendation:** Retain the catalog, distinguish vendored code from integrated functionality. | blocker 0 / major 2 / minor 2 |
| `07-build-and-packaging.md` | **Recommendation:** Rewrite the packaging and Python-hosting conclusions for a pinned source baseline. | blocker 1 / major 3 / minor 0 |
| `08-mcp-and-ipc-patterns.md` | **Recommendation:** Mostly usable; correct process isolation, API completion and serialization wording. | blocker 0 / major 1 / minor 1 |
| `09-gaps-and-risks.md` | **Recommendation:** Not sufficient for the stated acceptance criterion; replace estimates with parity and capacity decisions. | blocker 3 / major 12 / minor 2 |

## Source sampling ledger — 48 reviewed Fact claims

**Fact:** Each row identifies a claim explicitly presented as Fact in the reviewed documents, the current source checked, a verdict, and a correction or scope limit. Compound rows audit the specified part of the original claim. “Incorrect” means contradicted by the inspected implementation; “imprecise” means only a narrower statement is supported. English verdicts correspond to confirmed / incorrect / imprecise / not found.

| ID | Document and reviewed Fact claim | Source checked, current file:lines | Verdict and correction |
|---|---|---|---|
| C01 | 01 §2: `editor.lib` is unconditional and `-Deditor` is consumed but unused as a build gate. | `runtime/build.zig:1069–1109` | **Confirmed.** The block is unconditional; the option is discarded at line 1107. |
| C02 | 01 §2: CMake compiles `editor/screenshot` into `uzengine_runtime` itself. | `runtime/CMakeLists.txt:530–543,724–734,902–913,1065–1072` | **Incorrect.** The cited directory is an include path. Screenshot `.cpp` files belong to the separate `uzengine_editor` target; tools link both targets. F13. |
| C03 | 01 §4 / 07 §2: tools link runtime/editor, Agility exports, LuaJIT and FFmpeg import libraries. | `runtime/build.zig:1388–1412` | **Confirmed** for the inspected Windows tool recipe, not a minimal UzPainter dependency manifest. |
| C04 | 01 §5 / 02 §1: `--headless` creates a device and exits without rendering a scene. | `runtime/tools/uzengine.cpp:141–152,1500–1501` | **Confirmed.** It is a device smoke path. |
| C05 | 02 §1–2: hidden rendering creates an invisible HWND and an RGBA8 swapchain with vsync disabled. | `runtime/tools/uzengine.cpp:779–820` | **Confirmed** as implementation. Successful CI/service rendering is **not confirmed**. |
| C06 | 01 §5 / 02 §1: FLIP runs device/compute work without creating a window or swapchain. | `runtime/tools/uzengine.cpp:370–415` | **Confirmed** as a code path; “proven/tested” is stronger than the evidence in this review. |
| C07 | 02 §2: screenshot readiness can be bypassed after 120 frames. | `runtime/tools/uzengine.cpp:1233–1257` | **Incorrect for this snapshot.** The comment explicitly removes that bypass, and the condition requires readiness. F02/F18. |
| C08 | 02 §2: `SceneRenderer::RenderFrame` requires a swapchain; null behavior is unconfirmed. | `runtime/engine/renderer/scene/scene_render_frame.cpp:66–69`; `runtime/engine/renderer/scene/scene_renderer.h:239–259` | **Imprecise.** Null behavior can be determined statically: it returns immediately, rendering nothing. |
| C09 | 02 §1 / 03 §1: Null is a implemented no-op backend. | `runtime/engine/rhi/rhi_backend.h:23`; `runtime/engine/rhi/rhi_factory.cpp:36–93` | **Incorrect.** Null is an enum/comment; the factory has no Null case and returns `nullptr`. F15. |
| C10 | 02 §3: `CopyTextureToBuffer` exposes mip, offset, pitch and array slice; caller supplies CopySrc state. | `runtime/engine/rhi/rhi_command_list.h:375–393` | **Confirmed.** This does not validate the caller's pitch, size, state or completion. |
| C11 | 02 §3: DX12 buffers are persistently mapped. | `runtime/engine/rhi/dx12/dx12_device.cpp:1069–1076` | **Confirmed.** Mapping itself does not wait for the GPU. |
| C12 | 02 §3: FrameReadback has three slots/fences and assumes four bytes per pixel. | `runtime/engine/ipc/frame_readback.h:53–64,171`; `runtime/engine/ipc/frame_readback.cpp:78–107,236–270` | **Confirmed.** The implementation is not a lossless arbitrary-rate export queue. F08. |
| C13 | 02 §3: pass dump reads all registered targets regardless of format. | `runtime/engine/renderer/passes/debug/inspector_pass_dump.cpp:45–72,86–95,149–172` | **Imprecise.** Unsupported channel layouts, oversized targets and most depth targets are skipped; output is display-converted RGBA8. F08. |
| C14 | 02 §3: manual FLIP heatmap readback handles RGBA16F. | `runtime/tools/uzengine.cpp:417–445` | **Confirmed with a defect.** Pitch is `width*8`, without DX12 alignment. Arbitrary-width correctness is **not confirmed**. F08. |
| C15 | 02 §3 / 08 §2: C-API screenshot stalls then converts PNG to base64 and back to bytes. | `runtime/engine/app/runtime.cpp:1286–1328,1348–1372` | **Confirmed.** It is not a raw channel export facility. |
| C16 | 02 §4: both `PngCodec::EncodeFile/EncodeMemory` accept bit depth 8 or 16. | `runtime/engine/asset/importers/png_codec.h:68–90`; `png_codec.cpp:325–336,351–362,400–412` | **Imprecise.** Only EncodeMemory has bitDepth. EncodeFile hardcodes 8. F17. |
| C17 | 03 §2: RHI has half/float and BC1/3/4/5/7, but no color 16-bit UNORM or BC6H. | `runtime/engine/rhi/rhi_types.h:166–205` | **Confirmed.** D16Unorm is a depth format, not a height-map color format. |
| C18 | 03 §2: Vulkan maps BC4/5/7, while BC1/3 mapping was not confirmed. | `runtime/engine/rhi/vulkan/vulkan_format_helpers.h:46–53` | **Confirmed, incomplete.** BC1 and BC3 mappings are also present. Mapping is not a device format-support query. |
| C19 | 03 §3: RHITextureDesc expresses dimensions, mip count, usage and arrays/volumes. | `runtime/engine/rhi/rhi_types.h:485–499`; `dx12/dx12_texture_creation.cpp:209–221` | **Confirmed with a qualification.** Exactly six array layers become a cube SRV automatically; there is no independent cube flag. |
| C20 | 03 §3: DX12 UAVs cover mip 0 only. | `runtime/engine/rhi/dx12/dx12_texture_creation.cpp:233–258`; `runtime/engine/rhi/rhi_device.h` (`GetTextureUAVIndex`) | **Confirmed** for direct UAV views. “Compute mip generation is impossible” is too broad: scratch textures and subresource copies are an alternative. |
| C21 | 03 §3: conservative rasterization is absent and DX12 hardcodes it off. | `runtime/engine/rhi/rhi_types.h:577–585`; `runtime/engine/rhi/dx12/dx12_pso_creation.cpp:682` | **Confirmed.** Coverage equivalence to Painter is **not confirmed**. |
| C22 | 03 §3: no MSAA sample-count field is exposed by the texture descriptor. | `runtime/engine/rhi/rhi_types.h:490–499`; `runtime/engine/rhi/dx12/dx12_texture_creation.cpp:125–138` | **Confirmed.** DX12 resources hardcode sample count 1. Bake supersampling can still be implemented separately. |
| C23 | 03 §4: GPU material baker selects five outputs and creates RGBA8. | `runtime/engine/material/material_baker_gpu.h:58–64`; `material_baker_gpu.cpp:174–181` | **Confirmed** as implemented interface/format, not texture-graph usability. F06. |
| C24 | 03 §4: `mipgen_cs.hlsl` is an empty shader stub. | `runtime/shaders/runtime/compute/mipgen_cs.hlsl:1` | **Confirmed.** The file contains an empty main with 8×8 threads. |
| C25 | 03 §6: DX12 SupportsRayTracing tests Tier >= 1.0. | `runtime/engine/rhi/dx12/dx12_device.cpp:364–371` | **Confirmed.** This Boolean does not guarantee RayQuery. F04. |
| C26 | 03 §6: Vulkan has no overrides for BLAS/TLAS/RT support, so defaults apply. | Search of `runtime/engine/rhi/vulkan/`; `runtime/engine/rhi/rhi_device.h:292–323,330–361` | **Confirmed within this source scope.** Base methods return invalid handles/false. |
| C27 | 03 §8: BLAS/TLAS/DispatchRays/RayQuery all work at DXR Tier >= 1.0. | `runtime/engine/rhi/dx12/dx12_device.cpp:364–371`; `rhi_config.h:28–30`; Microsoft DXR spec, linked in F04 | **Incorrect.** Inline RayQuery needs Tier 1.1 and SM6.5; direct heap binding additionally needs the selected binding path. |
| C28 | 03 §6: BLASManager caches one BLAS per mesh from GPUMesh. | `runtime/engine/renderer/raytracing/blas_manager.cpp:14–65` | **Confirmed with limitations.** It hardcodes stride 48 and opaque geometry. Raw position-only high-poly buffers cannot use this manager unchanged. |
| C29 | 04 §2: fixed-PBR ORM reads AO=R, roughness=G, metallic=B. | `runtime/shaders/runtime/gbuffer/gbuffer_ps.hlsl:178–182,204–206` | **Confirmed.** These semantics alone do not establish render parity. |
| C30 | 04 §2/6: normal reads RG, reconstructs positive Z, and uses tangent.w in B=cross(N,T)*w. | `runtime/shaders/runtime/gbuffer/gbuffer_ps.hlsl:217–242` | **Confirmed.** Absolute +Y/-Y export convention remains **not confirmed**. |
| C31 | 04 §2: the fixed masked path samples separate opacity texture alpha. | `runtime/shaders/runtime/gbuffer/gbuffer_ps.hlsl:284–304` | **Confirmed** for this path; do not extrapolate to all material/forward paths. |
| C32 | 04 §2: `uzcook` chooses BC4 for opacity/alpha/mask. | `runtime/tools/uzcook.cpp:276–282`; `runtime/engine/asset/importers/texture_importer.cpp:172–174` | **Confirmed.** The mismatch with C31 is real. |
| C33 | 04 §4: color slots default sRGB, scalar/normal/ORM slots default linear. | `runtime/engine/renderer/material/material_interface.h:200–209` | **Confirmed as slot defaults.** Cooked file flags and cache identity affect the actual view. F09. |
| C34 | 04 §4: SetTextureSlotSRGB has no engine caller. | Search of `runtime/engine/` `.h/.cpp`; `renderer/material/material_asset.h:79–90` | **Confirmed within that scope.** The only match is the setter definition. |
| C35 | 04 §5: `.uztexture` has a 64-byte header, 24-byte mip entries, six listed format IDs, and an sRGB bit. | `runtime/engine/asset/formats/uztexture_format.h:97–101,116–142,171–183,212–219` | **Confirmed.** It has no float/array/volume payload layout; reserved cubemap wording is not implementation. |
| C36 | 04 final paragraph: loader validates mipCount against the maximum legal chain length. | `runtime/engine/asset/formats/uztexture_format.cpp:60–109`; `renderer/upload/texture_loader_ring.cpp:45–110` | **Incorrect.** Those implementations do not enforce this bound. A partial valid mip chain is also representable. F05. |
| C37 | 04 §5: texture cooker forces RGBA8 and builds box-filtered full mip chains. | `runtime/engine/asset/importers/texture_importer.cpp:254–269,352–371,58–80` | **Confirmed.** PNG decode explicitly requests SPNG_FMT_RGBA8; the cooked path does not preserve 16-bit source precision. |
| C38 | 05 §2: standard runtime Vertex is 48 bytes with one UV set and no vertex color. | `runtime/engine/renderer/mesh/vertex.h:28–46`; `runtime/shaders/runtime/gbuffer/mesh_vs.hlsl:13–25` | **Confirmed.** SimpleVertex has color, but is a different layout. |
| C39 | 05 §1/3: glTF MeshImporter serializes 32-byte VertexPosNormUV without stored tangents. | `runtime/engine/asset/importers/mesh_importer.cpp:729–744`; `asset/formats/uzmesh_format.h` (`VertexPosNormUV`) | **Confirmed.** Computing tangents earlier does not serialize them. |
| C40 | 05 §1: runtime accepts UZMS by converting it to a 48-byte UZMH Mesh. | `runtime/engine/renderer/mesh/mesh_io.cpp:120–153,168–195` | **Imprecise.** Detection/conversion exists, but the 32-byte source is copied unchanged then read with 48-byte stride. F03. |
| C41 | 04 §6 / 05 §3: standalone `uzmesh` uses Lengyel-style tangents, not MikkTSpace. | `runtime/tools/uzmesh.cpp:1092–1093`; `runtime/engine/renderer/mesh/mesh_tangents.cpp:24–58` and its UV-edge accumulation/orthogonalization body | **Confirmed.** A different tangent implementation is used from the cooked path. |
| C42 | 04 §6 / 05 §3: cooked FBX and glTF call MikkTSpace. | `runtime/engine/asset/importers/fbx_importer.cpp:1579`; `mesh_importer.cpp:558` | **Confirmed as calls.** Correct seam splitting and identical rendered bases remain **not confirmed**. |
| C43 | 05 §4: FBX SDF bake is unconditional. | `runtime/engine/asset/importers/fbx_importer.cpp:2045–2063`; `mesh_importer.cpp:754–788` | **Incorrect.** FBX skips above 50,000 indices; glTF also has an SDF bake, without that guard in this block. F11. |
| C44 | 07 §1: Zig C++17, one C++20 TU, versus CMake C++20. | `runtime/build.zig:34–35,727–732`; `runtime/CMakeLists.txt:15–17` | **Confirmed.** The C++20 TU is etcpak's `bc7enc.cpp`, not fastgltf as guessed in 06. |
| C45 | 07 §1: release disables Tracy. | `runtime/build.zig:34–35,629–633` | **Incorrect as a Zig build assertion.** TRACY_ENABLE/ON_DEMAND are passed unconditionally, including to TracyClient. F20. |
| C46 | 06 §1–2: etcpak is the only BC encoder and no BC6H encoder exists anywhere in the tree. | `runtime/thirdparty/basis_universal/encoder/basisu_bc7enc.h:79–130`; `encoder/basisu_astc_hdr_6x6_enc.cpp:3388–3436`; `transcoder/basisu_astc_hdr_core.h:179–204`; `runtime/build.zig:636–641` | **Incorrect.** Additional BC7 and BC6H encoding source exists. An integrated engine BC6H export path remains **not confirmed**. F16. |
| C47 | 07 §4: runtime scripting is LuaJIT, sandbox removes named globals, and no Python/pybind11/CPython runtime integration is present. | `runtime/engine/scripting/lua_vm.cpp:52–60,138–151,181`; searches of `runtime/build.zig`, `runtime/CMakeLists.txt`, `runtime/engine/scripting/` and thirdparty directory names | **Confirmed within this scope.** This is not a sandbox security audit or a claim that the repository has no Python scripts. |
| C48 | 08 §1: MCP registers six documentation tools and does not drive the runtime. | `mcp/src/server.ts:7–14,34–161,193–207` | **Confirmed.** All six callbacks query SearchEngine; transport is stdio. No native bake/control tools are demonstrated. |

## Numbered findings

### F01 — blocker — Acceptance is output parity, but the roadmap is feature parity

Affected document: **09**.

**Fact:** `09-gaps-and-risks.md:48–56` sequences UV rasterization, ray queries, a compositor and exports, with an AO/FLIP check; it does not define a Painter version/configuration, instruction corpus, channel comparison contract, smart-material asset equivalence or render reference. The engine has its own preview transform, including passthrough color in `runtime/shaders/runtime/postprocess/tonemap_ps.hlsl:72–98` and its own roughness modification in `runtime/shaders/runtime/gbuffer/gbuffer_ps.hlsl:251–258`.

**Hypothesis:** A conventional AO implementation, MikkTSpace and an ORM preset can deliver plausible output while still failing the owner's “same instructions, same textures and render” criterion. Equality with Painter is **not confirmed**; there is no source evidence here establishing it.

**Recommendation — correction:** Make parity the first architecture decision: pin the reference application/settings/assets, define literal equality or agreed numerical/perceptual tolerances, separate raw texture comparisons from display-render comparisons, and cover intermediate bake maps and layer operations. Generic shaders and FLIP are tools for measurement, not evidence of equivalence. No small-effort estimate should include parity unless the reference semantics are specified.

### F02 — blocker — The reviewed source baseline is unresolved and the analysis is not revision-pinned

Affected documents: **01, 02, 03, 07, 09**.

**Fact:** Conflict markers occur in executable source, including `runtime/engine/renderer/frame/frame_constants.cpp:129–140`, `runtime/engine/renderer/passes/debug/inspector_pass_validate.cpp:108–141,273–278`, and `runtime/shaders/runtime/lighting/deferred_lighting_ps.hlsl:173–201`. These are not comment-only historical references. The inspector file is an unmerged Git path. The current CLI's screenshot condition differs from the reviewed one at `runtime/tools/uzengine.cpp:1250–1255`; current build blocks are at different lines from the cited ranges.

**Hypothesis:** Building these unresolved C++/HLSL contents normally will fail; no build was run, so a compiler result is **not confirmed**. Existing binaries do not prove that these source contents built or ran. The conflicts may postdate the original analysis.

**Recommendation — correction:** Name an immutable, resolved engine baseline and distinguish its source, generated shaders and binaries. Recheck implementation claims against that baseline before authorizing integration. Remove “done”, “tested”, “proven” and “reuse as-is” wherever the evidence only establishes API/source presence. Keep this snapshot issue visible independently of the architectural defects.

### F03 — blocker — UZMS glTF conversion is a concrete layout defect, not just format ambiguity

Affected documents: **01, 05, 09**.

**Fact:** `runtime/engine/asset/importers/mesh_importer.cpp:734–739` writes `sizeof(VertexPosNormUV)` bytes per vertex. `runtime/engine/renderer/mesh/mesh_io.cpp:135–153` selects destination stride 48 but keeps the original byte vector when source stride is smaller. Lines `171–173` read vertex positions at that 48-byte spacing, and line `186` publishes that stride. No 32-to-48 expansion/tangent generation occurs in this branch.

**Hypothesis:** For ordinary multi-vertex 32-byte UZMS streams, the AABB loop can read beyond the buffer, and rendered attributes/BLAS input can be invalid. A runtime crash was not reproduced; the contradictory strides themselves are **Fact**.

**Recommendation — correction:** Escalate G18 to a correctness prerequisite. Require explicit supported layouts, stride/count validation and a real conversion that fills normals/UV/tangents correctly, or a verified importer route producing 48-byte records. Do not count the cooked glTF pipeline as reusable or tangent-compatible until this contract is fixed and checked.

### F04 — major — DXR 1.0 support is conflated with inline RayQuery support

Affected documents: **03, 09**.

**Fact:** `runtime/engine/rhi/dx12/dx12_device.cpp:364–371` exposes only Tier >= 1.0 as a Boolean. `runtime/engine/rhi/rhi_config.h:28–30` distinguishes SM6.3 DXR 1.0 and SM6.5 DXR 1.1. Inline RayQuery requires DXR Tier 1.1 and is available starting at SM6.5. [Microsoft DXR functional specification](https://microsoft.github.io/DirectX-Specs/d3d/Raytracing.html#inline-raytracing).

**Recommendation — correction:** Split pipeline ray tracing, inline ray tracing, shader-model support and descriptor-heap binding into separate capabilities. The proposed compute baker must test its exact requirements. Tier 1.0 needs a DispatchRays implementation or another fallback; it cannot be advertised as supporting the proposed RayQuery kernel merely because SupportsRayTracing returns true.

### F05 — major — `.uztexture` validation is documentation, not enforced implementation

Affected documents: **01, 04, 09**.

**Fact:** The header documents detailed validation in `runtime/engine/asset/formats/uztexture_format.h:169–178,202–207`, but `uztexture_format.cpp:60–109` checks file/header size, magic, version, descriptor table fit and `offset+size` bounds only. It does not enforce dimensions, mip-count bounds, expected per-mip dimensions/byte sizes or reserved bits. The ring loader duplicates parsing at `runtime/engine/renderer/upload/texture_loader_ring.cpp:45–110`, casts mipCount to uint16, and breaks rather than returning an error when a mip blob lies outside the file. Addition overflow is not explicitly guarded in those bounds expressions.

**Recommendation — correction:** Describe the actual checks. Use a single validated parse contract with overflow-safe arithmetic before allocations/uploads. Distinguish legal partial chains from the cooker's full-chain policy. Do not recommend the readers/writers “as-is” as the integrity boundary for compact projects or untrusted/generated assets.

### F06 — major — MaterialBakerGpu is a limited graph evaluator, not an available layer compositor

Affected documents: **01, 03, 09**.

**Fact:** `runtime/engine/material/material_baker_gpu.cpp:69–82` zeros material parameters and supplies constant world position/normal/color/time. Its dispatch binds only dimensions/output selection and the output UAV at `214–249`; it waits synchronously at `267–270`. The translator emits `getTexIndex` and `linearSampler` references at `runtime/engine/material/compiler/hlsl_material_translator.cpp:404–411` and expects texture bindings in the combined shader at `761–765`. The bake wrapper does not provide that complete binding environment. The baker's AO selector is 4 (`material_baker_gpu.h:58–64`), while graph PBROutput AO is 6 (`runtime/engine/ecs/loaders/scene_loader.cpp:644–649`).

**Hypothesis:** Unmodified translated graphs containing texture nodes will not have a valid standalone compute binding environment; compilation/dispatch success for those graphs is **not confirmed**. Copying pixel-style sampling also needs an explicit compute LOD/derivative policy.

**Recommendation — correction:** Limit reuse to a procedural prototype. Specify texture bindings, user parameters, surface inputs, compute sampling, resource transitions from actual initial states, precision, channel selectors and asynchronous completion before reusing it. Keep bake selector IDs distinct from graph pin IDs. A layer stack additionally needs channel-specific blend/mask and normal/height composition semantics, which this evaluator does not establish.

### F07 — major — Precision and mip/compression policy can defeat parity even when files load

Affected documents: **04, 06, 09**.

**Fact:** The cooker requests RGBA8 PNG data at `runtime/engine/asset/importers/texture_importer.cpp:254–269`, averages stored bytes directly at `58–80`, and builds full mip chains at `352–371`. RGBA8 graph bake and the `.uztexture` format set are limited as shown in C23/C35. BC7 parameters are default-initialized at `texture_importer.cpp:178–181`; this code does not establish equal scalar-channel error or equivalence to another encoder.

**Recommendation — correction:** Preserve canonical authored/baked data at the required precision, independently of the runtime cooked asset. Specify sRGB filtering, normal renormalization, roughness filtering, alpha coverage, padding and quantization for each channel. Measure lossy export against that canonical data. A 16-bit PNG encoder alone cannot recover precision already lost in RGBA8 or BC4; BC4 height must not be assumed equivalent to 16-bit authored height.

### F08 — major — Readback helpers are not a safe, lossless batch exporter

Affected documents: **01, 02, 03, 09**.

**Fact:** FrameReadback advances a write slot without checking slot reuse or CPU consumption at `runtime/engine/ipc/frame_readback.cpp:185–229`; readiness is checked separately at `252–270`, and MapRead does not call it at `273–285`. Signaling is a separate caller step after submission at `233–245`. The FLIP example uses unaligned `width*8` pitch at `runtime/tools/uzengine.cpp:419–438`. Pass dump skips targets and applies display conversions at `runtime/engine/renderer/passes/debug/inspector_pass_dump.cpp:45–72,149–172`. DX12 now supports an explicit 3D Z slice through arraySlice at `runtime/engine/rhi/dx12/dx12_command_list.cpp:906–939`; the statement that it can only reach Z=0 is obsolete. Vulkan still sets imageOffset.z=0 at `runtime/engine/rhi/vulkan/vulkan_command_list.cpp:1173–1176`.

**Hypothesis:** A consumer slower than the producer can lose captures or reuse a mapped/in-flight slot unless the host provides backpressure. All-format, all-backend and all-slice export correctness is **not confirmed** by the helpers' existence.

**Recommendation — correction:** Require ownership of every queued export, row/placement alignment, size checks, explicit resource states, submission-linked fence values, map-after-completion, CPU-buffer lifetime, backpressure and a final drain. Distinguish diagnostic PNGs from exact channel data. Expose raw per-mip/slice bytes and metadata; do not export bake maps via a tonemapped pass dump. Existing `SceneRenderer::GetLdrIntermediate/GetLdrIntermediateState` at `scene_renderer.h:261–269` is already useful for preview capture, although it does not make RenderFrame swapchain-free.

### F09 — major — Slot sRGB defaults do not define the actual color contract

Affected documents: **04, 09**.

**Fact:** Slot defaults exist at `runtime/engine/renderer/material/material_interface.h:200–209`, but cooked flags select the actual GPU format at `runtime/engine/renderer/upload/texture_loader_ring.cpp:70–85`. Scene texture caching uses only the path at `runtime/engine/renderer/scene/scene_texture_assets.cpp:107–118,143`; it does not include the requested isSRGB in that lookup. The per-slot setter exists but has no caller within the engine source search (C34).

**Hypothesis:** Reusing a source path across color/data slots can retain the first loaded interpretation, and a cooked companion can override the interpretation implied by the slot. The resulting numerical effect for a particular asset is **not confirmed** by execution here.

**Recommendation — correction:** Specify source encoding, working space, explicit conversion, view interpretation and output metadata separately. Resolve the precedence between slot overrides and cooked flags. Cache by content plus interpretation, or expose independently typed views where supported. sRGB versus linear alone does not specify the full reference display or HDR color pipeline.

### F10 — major — Tangent and UV guarantees are weaker than the proposed normal preset

Affected documents: **04, 05, 09**.

**Fact:** Normal Y is used without an explicit sign flip and B includes tangent.w (`runtime/shaders/runtime/gbuffer/gbuffer_ps.hlsl:217–242`). Standalone and cooked importers use different tangent implementations (C41/C42). Standard Vertex has one UV stream (`runtime/engine/renderer/mesh/vertex.h:39–46`), and the translator's TexCoord case always emits `uv` at `runtime/engine/material/compiler/hlsl_material_translator.cpp:420–422`, ignoring any UV-index choice.

**Hypothesis:** An OpenGL +Y expectation cannot be established merely from rendering a glTF sample or a MikkTSpace compatibility comment. Mirroring, V flips, axis transforms and corner splits also affect the tangent frame; final green-channel convention is **not confirmed**.

**Recommendation — correction:** Establish one import-to-bake-to-preview tangent contract, including per-corner splits, transforms, winding, mirrored UVs and tangent sign. Compare both normal conventions against controlled reference surfaces. Separate UDIM tile addressing from multiple UV sets: tiles can use a single UV stream extending beyond [0,1]; the engine still needs tile routing/storage/sampling, but UDIM does not inherently require adding UV1/UV2.

### F11 — major — High-poly processing is mischaracterized, and BLAS reuse has hidden assumptions

Affected documents: **05, 09**.

**Fact:** FBX selects the first mesh at `runtime/engine/asset/importers/fbx_importer.cpp:1233–1242`; glTF selects the first at `mesh_importer.cpp:383`. FBX SDF is guarded by `optimizedIndices.size() <= 50000` at `fbx_importer.cpp:2045–2063`. glTF also bakes an SDF at `mesh_importer.cpp:754–788`. Standalone uzmesh calls LOD generation at `runtime/tools/uzmesh.cpp:1108–1110`, but that generates extra LODs; it does not mean LOD0 is replaced by a simplified mesh. BLASManager uses fixed stride 48 and `isOpaque=true` at `runtime/engine/renderer/raytracing/blas_manager.cpp:31–49`.

**Recommendation — correction:** Correct “FBX always bakes SDF” and include the glTF SDF cost. Distinguish input mesh preservation from extra LOD work. Design a raw high-poly ingestion route with all objects, instances/transforms, material/face IDs, normals and UV data. Parameterize BLAS geometry/stride/opacity or use raw RHI; a packed position-only stream is not supported by this manager unchanged. Maximum practical high-poly size, peak parser RAM and AS build time remain **not confirmed**.

### F12 — major — Export fields are confused with reader support, and graph ORM flattening can be overwritten

Affected documents: **04, 09**.

**Fact:** Fixed Material declares opacity/thickness fields (`runtime/engine/renderer/material/material_asset.h:65,181–183`), but the scene material loader at `runtime/engine/ecs/loaders/scene_loader.cpp:835–930` parses a smaller set of fields. No inline opacity/thickness/heightmap path assignment is present in that block. Its graph ORM path is assigned at `847–849`, then overwritten unconditionally by `ReadString(comp,"orm")` at `925`, even when the inline field is absent; useORM remains true. The GBuffer/cooker opacity mismatch is confirmed in C31/C32. The cooker defaults unknown names to BC7 sRGB at `runtime/tools/uzcook.cpp:285–288`, so a height/thickness filename alone is not a BC4-linear recipe.

**Hypothesis:** A graph-only ORM binding can be lost in this loader path. A successful roundtrip through every graph/material loading path is **not confirmed**. The `.uzmaterial` schema is not evidence that the omitted inline fields are loaded.

**Recommendation — correction:** Publish separate contracts for authored project, graph, scene binding and cooked runtime outputs. Verify every exporter key through the actual chosen consumer, including material index/texture-set routing and serialization back to disk. Retain graph ORM when no inline override exists. Encode standalone opacity in the channel actually consumed, or change that consumer contract; encode height/thickness with explicit format/space settings. Require an end-to-end reader/writer example before accepting the recommended preset.

### F13 — major — Packaging ownership and Agility paths need a complete source-based recipe

Affected documents: **01, 07, 09**.

**Fact:** CMake has a separate editor target (C02), not the ownership stated in 01. `runtime/engine/rhi/dx12/dx12_agility.cpp:16–17` exports `.\\D3D12\\`, while Zig installs D3D12Core at the bin root (`runtime/build.zig:1462–1468`). There is also a programmatic path: Init calls TryLoadAgilitySdk (`dx12_device.cpp:236–239`), which uses `GetExeDir()` and CreateDeviceFactory at `448–478`. Therefore the path difference does not by itself prove startup failure. Zig now copies FFmpeg DLLs at `build.zig:1508–1536`, not only the N-API CMake step, and installs atmosphere content at `1488–1497`.

**Recommendation — correction:** Document EXE exports, programmatic device-factory activation and fallback paths separately. Record the chosen SDK/runtime and verify the distributable against that route. Define whether standalone means one file or a folder; enumerate transitive DLLs and engine data for the actual target. Removing an import library is not proof that a SceneRenderer-hosted executable can omit its dependent feature symbols. A minimal file count or footprint is **not confirmed** without the final dependency closure.

### F14 — major — `ctypes` is in-process; hosting/thread ownership is not established by the N-API example

Affected documents: **07, 08**.

**Fact:** `07-build-and-packaging.md:75` labels direct Python use of the C API DLL “out-of-process” with crash isolation. A DLL called by ctypes runs in its caller's process; actual process isolation is demonstrated instead by `extension/src/runtime-client.ts:411` using `cp.fork`. The C API requires frame rendering on the viewport-creation thread (`runtime/engine/app/runtime.h:6–11,224–225`), while N-API declares its render/encode loop on a dedicated thread (`napi/src/render_thread.h:13–19`). This pair of comments does not establish a coherent all-call ownership protocol.

**Recommendation — correction:** Distinguish in-process Python DLL bindings, a Python-owned worker process, and RPC/subprocess transport. Define one owning GPU thread, creation/destruction on that thread, queued mutations, synchronization of scene reads/writes, callback delivery and cancellation/shutdown. Treat SEH and a forked worker as different containment mechanisms. Do not claim crash isolation merely by selecting ctypes.

### F15 — minor — Null is not an implemented no-op renderer

Affected documents: **02, 03, 09**.

**Fact:** `runtime/engine/rhi/rhi_backend.h:23` declares Null, but `runtime/engine/rhi/rhi_factory.cpp:36–93` has no Null creation case. It falls through to an unsupported-backend error and `nullptr`.

**Recommendation — correction:** Mark Null as declared but not implemented in the inspected factory. CPU-only CI needs an explicit supported execution path or test doubles; it cannot rely on this enum.

### F16 — minor — Vendored encoding/container code invalidates blanket absence claims

Affected documents: **06, 09**.

**Fact:** Basis Universal contains a BC7 encoder (`runtime/thirdparty/basis_universal/encoder/basisu_bc7enc.h:79–130`), BC6H image encoding calls (`encoder/basisu_astc_hdr_6x6_enc.cpp:3388–3436`) and a fast BC6H entry point (`transcoder/basisu_astc_hdr_core.h:179–204`). Its vendored tinydds has read/write APIs at `encoder/3rdparty/tinydds.h:50,688,1336,1967`. The engine build compiles the Basis transcoder at `runtime/build.zig:636–641`; it does not establish a supported engine export wrapper for these functions.

**Recommendation — correction:** Replace “none anywhere” with “no integrated engine export path found.” Separate source presence, build integration, engine API and validated output quality. Evaluate existing vendor code before concluding another library must be acquired. Performance/quality of these paths is **not confirmed**.

### F17 — minor — The 16-bit PNG export API is narrower than stated

Affected documents: **02, 06**.

**Fact:** `runtime/engine/asset/importers/png_codec.h:68–90` exposes 8-bit EncodeFile and 8/16-bit EncodeMemory. The file encoder hardcodes an 8-bit IHDR at `png_codec.cpp:327`, while the memory encoder uses supplied bitDepth and handles native-to-PNG byte swapping at `400–412`.

**Recommendation — correction:** For current 16-bit export, encode to memory and write those PNG bytes with explicit file I/O, or extend EncodeFile. Document native pixel byte order, buffer size and color metadata; do not pass 16-bit samples to the existing 8-bit file method.

### F18 — major — CLI capture controls are not a deterministic-output contract

Affected documents: **02, 09**.

**Fact:** Main-loop dt is wall-clock time in `runtime/tools/uzengine.cpp:1177–1181`. Screenshots are requested only after readiness at `1250–1257`, after the frame has rendered, as described in `1241–1244`. FrameIndex is explicitly used for rendering/buffering (`runtime/engine/renderer/scene/scene_renderer.h:244–245`). The preview contains temporal exposure and AA shaders, e.g. `runtime/shaders/runtime/postprocess/exposure_average_cs.hlsl:1–2` and `taa_resolve_cs.hlsl`. Turning scripts off does not freeze these mechanisms.

**Recommendation — correction:** Define fixed dt, seed/sampling order, frame identity, asset-readiness completion, temporal-history initialization, warmup count, exposure, camera, IBL and postprocessing. Persist all relevant parameters in the job/result manifest. Gate export on completed operations, and report missing assets/capture failures explicitly. Bitwise repeatability across GPU vendors/drivers and equal results to Painter remain **not confirmed**.

### F19 — minor — Serialization and synchronous-API wording overstate the observed contract

Affected document: **08**.

**Fact:** `08-mcp-and-ipc-patterns.md:66` says all asset files are JSON, contradicting the binary texture writer (`runtime/engine/asset/formats/uztexture_format.cpp:13–55`) and binary mesh serializer (`asset/importers/mesh_importer.cpp:729–744`). `runtime/engine/app/runtime.h:14–15` specifies static string validity until the next call to the **same function**, not every function sharing one universal buffer. `uz_load_scene` returns after scene parsing at `runtime.cpp:827–871`, while renderer texture loading separately enqueues asynchronous work at `runtime/engine/renderer/scene/scene_texture_assets.cpp:145–147,184–196`.

**Recommendation — correction:** Say scene/project/graph metadata use JSON, while cooked payloads are binary. Specify per-function buffer lifetimes. Distinguish synchronous C call return from completion of all GPU/asset work; a future job API needs a completion definition, not only opaque IDs.

### F20 — major — Broad capability and effort claims have insufficient evidence for architectural acceptance

Affected documents: **01, 03, 05, 06, 07, 09**.

**Fact:** The nine reports mix implemented API facts with comments, README versions, old binary sizes and planned-design documents. For example 07's release/Tracy assertion conflicts with unconditional defines (`runtime/build.zig:34–35,629–633`); 06's C++20-TU guess is contradicted by the etcpak compilation block (`727–732`). GPU capacity has actual constraints: descriptors are fixed at 1,000,000 CBV/SRV/UAV, 2,048 samplers, 256 RTV and 64 DSV (`runtime/engine/rhi/dx12/dx12_device.h:44–57`), while VRAM budget can already be queried (`dx12_device.cpp:1430–1440`). Format enum/mapping tables do not constitute format+usage validation.

**Recommendation — correction:** Reclassify all-backend “done/reuse as-is”, guessed S/M/L effort, performance/quality comparisons and minimal packaging sizes as hypotheses. Inventory limits at device and engine levels and validate each required usage combination. Explain that direct per-mip UAVs are absent, but scratch UAV textures followed by CopyTextureRegion can generate mips without direct views. Pin vendor versions to actual headers/artifacts and license evidence. These estimates currently exclude output-parity discovery, testing and replacement costs.

## Claims without sources, or with sources too weak for architectural acceptance

**Recommendation W01 — blanket reuse:** Do not accept 01 §6's “reuse as-is (all backends)” for RHI, upload, graph, ray tracing or screenshots. Its evidence is largely API/file presence. C02/C28/C40 and F02/F08 show concrete reasons to qualify reuse. Require a baseline and operation-specific tests later, outside this read-only review.

**Recommendation W02 — universal negatives:** Do not accept “only windowless GPU work”, “all targets”, “no encoder anywhere”, “nothing models jobs” or “JSON everywhere” as repository-wide conclusions from a short grep or directory listing. C13/C46 and F16/F19 demonstrate false or overbroad negatives. The reviewed native renderer bake/compositor/MCP/Python APIs were not found in the examined scopes; that is the supported statement.

**Recommendation W03 — performance:** Treat the reported upload milliseconds, SDF latency, Sponza load duration, H.264 latency and debug binary sizes as attributed historical observations, not budgets for UzPainter. The review does not confirm benchmark configuration, input, source revision, GPU/driver, precision, peak memory or timing boundaries. No source-reading exercise establishes current throughput.

**Recommendation W04 — quality and compatibility:** etcpak being “lower quality than ISPC/Compressonator”, compatibility comments linking MikkTSpace to other applications, and glTF sample success do not prove the targeted channel error or normal convention. The actual encoder call/defaults are visible at `runtime/engine/asset/importers/texture_importer.cpp:178–181`; comparative quality and Painter parity are **not confirmed**.

**Recommendation W05 — deployment/legal claims:** README compiler/vendor versions, claimed build verification, blanket licensing summaries and “dynamic linking required” statements should not be accepted as a distribution audit. Actual binary configuration, component licenses/notices, transitive dependencies and the shipped target remain **not confirmed**. This review makes no legal conclusion.

**Recommendation W06 — estimates and untagged derivations:** The S/M/L/XL gap costs in 09, “Runtime only needs…”, “100-line screenshot class”, “4–6 DLLs”, the recommended normal convention and the shortcut implementation sketches are estimates/design choices. They need explicit Hypothesis/Recommendation labels, named assumptions and a parity-validation scope. Their occurrence beside sourced Facts must not confer factual status.

## Architectural gaps — determined from code versus open questions

| Item | Determined by source | Still open / required decision |
|---|---|---|
| **Recommendation G01 — exact parity oracle** | **Fact:** The analysis provides a feature roadmap, while engine postprocessing and roughness processing have independent semantics (F01). | Reference Painter build, shader/render mode, smart-material/generator content, instruction grammar, settings, tolerances and comparison stages are **not confirmed**. Establish bake-map, compositor and render reference corpora, including seams, mirrors, overlaps and failures. |
| **Recommendation G02 — texture limits and usage** | **Fact:** Texture dimensions are uint32 and mip/layer/depth counts uint16 (`runtime/engine/rhi/rhi_types.h:490–498`). Direct mip-0 UAV and no MSAA/conservative raster are confirmed (C20–C22). DX12 creation forwards dimensions/flags to the API (`dx12_texture_creation.cpp:125–138`). | No engine startup `D3D12_FEATURE_FORMAT_SUPPORT` query was found in the searched `runtime/engine/rhi/` source. Maximum supported dimensions for the chosen GPU and format/usage combinations, typed UAV loads/stores, failure handling and scheduling are **not confirmed**. Do not infer them from the enum or raw integer ranges. |
| **Recommendation G03 — arrays, cube and UDIM** | **Fact:** DX12 chooses a cube SRV whenever depthOrArraySize==6 (`runtime/engine/rhi/dx12/dx12_texture_creation.cpp:213–221`). `.uztexture` is a 2D mip payload, not a tiled project container. | A six-tile UDIM array needs an explicit array/cube distinction. Tile numbering, missing tiles, cross-tile sampling/dilation, virtual texturing and per-texture-set resolution are **not confirmed**. One UV set can address multiple tiles; multiple UV sets are a separate requirement. |
| **Recommendation G04 — GPU/CPU ownership and draining** | **Fact:** Capture, signaling, readiness, mapping and read advancement are separate calls (F08). DX12 generic CreateFence is bound to the direct queue (`runtime/engine/rhi/dx12/dx12_device.cpp:1324–1331`); copy/compute work needs its corresponding queue synchronization. | Lossless multi-channel export, tail drain, cancellation, resource lifetime and cross-queue state/ownership rules are **not confirmed**. CPU mapping is not equivalent to data visibility/completion. Format-aware 3D readback also differs between backends (F08). |
| **Recommendation G05 — memory budget** | **Fact:** QueryVideoMemoryInfo already exposes current budget/usage (`runtime/engine/rhi/dx12/dx12_device.cpp:1430–1440`). DX12 AS creation retains result and scratch allocations (`dx12_device.cpp:1652–1680,1710–1715`), and descriptor capacities are finite (F20). | Specify RAM/VRAM admission limits, preview reserve, intermediate lifetimes, tile streaming, cache eviction, scratch reuse/compaction and OOM behavior. A useful accounting model is dimensions × bytes/texel × live channels × tiles × buffering, plus mip chains, mesh/AS and staging. Actual supported texture-set/layer/high-poly counts are **not confirmed**. |
| **Recommendation G06 — mesh/texture-set identity** | **Fact:** Reviewed importers select one mesh; standard vertices lack extra UV/color; BLAS manager assumes one opaque 48-byte geometry (C28/C38 and F11). | Define traversal of nodes/instances, applied transforms/units, material-to-texture-set mapping, object/face IDs, smoothing groups, nonmanifold handling and whether multiple UV/color streams must be preserved outside the preview vertex. Complete preservation is **not confirmed**. |
| **Recommendation G07 — projection and bake semantics** | **Fact:** RHI RT primitives and existing RayQuery calls provide traversal infrastructure, not a specified high-to-low map baker. Relevant code includes `runtime/engine/renderer/raytracing/blas_manager.cpp:31–62` and `runtime/shaders/runtime/gi/ddgi_probe_update_cs.hlsl:189`. | Cage definition, frontal/rear distance, mesh-name matching, self-intersections, backfaces, hit selection, high-poly texture sampling, transparent/cutout geometry, sample sequences, AO spread, thickness behavior, curvature algorithm, antialiasing and denoising against Painter are **not confirmed**. |
| **Recommendation G08 — UV coverage and padding** | **Fact:** No conservative-raster/MSAA controls are exposed in the checked texture/rasterizer descriptors; per-mip/slice copies and compute dispatch exist. | Texel-center rules, triangle-edge inclusion, subpixel islands, overlaps, seam masks, tangent discontinuities, supersampling, dilation distance and padding at every mip require a defined algorithm. Thin-island parity is **not confirmed**. |
| **Recommendation G09 — compositor semantics** | **Fact:** Current GPU baker uses zero material params and constant surface inputs, fixed RGBA8 outputs and a blocking fence (F06). | Define per-channel blend modes, premultiplied alpha, masks, clipping, groups, anchor dependencies, smart masks/materials, normal/height blending, generators, procedural noise identity, effect ordering, precision and incremental invalidation. Equivalent results are **not confirmed**. |
| **Recommendation G10 — normal contract** | **Fact:** Shader decoding, positive Z reconstruction, tangent.w, implementation divergence and ignored UV index are established (F10). | Green-channel orientation, per-corner MikkTSpace behavior, transformed/mirrored meshes, graph normal encoding and reference baker settings require controlled comparisons. The absolute export convention is **not confirmed**. |
| **Recommendation G11 — color and preview parity** | **Fact:** Slot defaults, cooked sRGB flags, path-only caching, RGBA8 preview capture and passthrough postprocessing exist (F07/F09/F18). | Working/display transforms, HDR, IBL source/rotation/intensity, BRDF, exposure, tone mapping, AA/temporal accumulation, lighting, camera/lens and background need a pinned reference. Render equality cannot be inferred from PBR parameter names. |
| **Recommendation G12 — exports and compact saves** | **Fact:** `.uztexture` lacks high-precision/array payloads; PNG memory export supports 16 bits; metadata and cooked payload formats differ (F05/F17/F19). | Define canonical lossless channel storage versus runtime derivatives, Unreal/UzEngine preset readers, versioning, source references, cache inclusion, compression, atomic save/recovery and reproducible reopening. “Compact” has no confirmed size or data-loss contract. |
| **Recommendation G13 — headless execution/packaging** | **Fact:** CLI headless is device-only; RenderFrame returns on null swapchain; LDR intermediate access already exists (C04/C08, F08). Source conflicts and multiple Agility activation routes are present (F02/F13). | CI with/without an interactive desktop, supported adapters/drivers, fallback policy, resource/cache paths and one-file versus folder packaging require a declared support matrix. This review confirms no successful CI deployment. |
| **Recommendation G14 — automation API** | **Fact:** Lua runtime and doc-only TypeScript MCP exist; no integrated runtime Python layer was found in the examined build/scripting scopes (C47/C48). C API call completion is distinct from asset completion (F19). | Define one job/state model shared by CLI/Python/native MCP: schemas, ownership, idempotency keys, progress, cancellation, result manifests, error codes, thread routing and restart/checkpoint behavior. These are **not confirmed** by the current interface. |

## Inconsistencies across the nine documents

**Fact I01 — module ownership:** 01 §2 places screenshots inside the CMake runtime, whereas 07's tool recipe emphasizes a runtime/editor pair. Current CMake confirms the separate editor library (`runtime/CMakeLists.txt:902–913,1072`); 01's premise must be corrected (F13).

**Fact I02 — reuse versus glTF correctness:** 01 §6 marks asset formats/upload/ray tracing “reuse as-is”, while 05 §1 and 09 G18 already identify a 32/48-byte conversion risk. Source confirms the layout defect (`runtime/engine/renderer/mesh/mesh_io.cpp:135–153,171–186`); the reuse verdict must incorporate it (F03).

**Fact I03 — DXR tier:** 03 §6 calls inline tracing DXR 1.1, but §8 combines RayQuery with Tier >=1.0, and 09's bake route assumes that combined support. The source only exposes the Tier-1.0 Boolean (`runtime/engine/rhi/dx12/dx12_device.cpp:364–371`); the proposed route needs stronger capability checks (F04).

**Fact I04 — precision versus proposed exports:** 06 advertises 16-bit PNG I/O, 04 recommends 16-bit height when bypassing cooking, and 09 recommends export reuse, while 03/04 also establish RGBA8 baking/cooking and absent high-precision cooked color formats. These statements are individually reconcilable only by explicitly separating canonical authored data and runtime derivatives (`material_baker_gpu.cpp:174–181`, `texture_importer.cpp:254–269`; F07).

**Fact I05 — Python requirement becomes optional:** 07 recommends Python alternatives, while 09 §3 ends with “optional Python.” The owner's requested Python API is part of this review's acceptance context, not an optional product feature. Use a required API boundary decision; effort/implementation choice remains a Recommendation (F14/G14).

**Fact I06 — structured metadata versus binary assets:** 08 §3 calls all asset files JSON, contradicting binary formats explained in 04/05 and implemented by the writers (`runtime/engine/asset/formats/uztexture_format.cpp:13–55`; F19).

**Fact I07 — opacity/export binding:** 04 correctly identifies alpha-vs-BC4 opacity, but its proposed standalone opacity/thickness bindings are not backed by the inline scene reader, and 09 G14 treats the fix as an export rule/cooker-only adjustment. Actual consumer routing matters (`runtime/engine/ecs/loaders/scene_loader.cpp:835–930`; F12).

**Fact I08 — transport/isolation:** 07 option A conflates direct DLL calls with out-of-process execution, while 08 describes real fork-based containment. The fork is visible at `extension/src/runtime-client.ts:411`; the two architectures need distinct names and guarantees (F14).

**Fact I09 — blanket negatives versus vendor catalog:** 06 lists Basis encoder sources but concludes that no BC6H encoder exists anywhere; 09 repeats this premise when estimating a new dependency. Vendor encoding code contradicts the universal claim (F16). The missing engine integration remains a valid gap.

**Recommendation I10 — headless terminology:** 02 correctly distinguishes Application's hidden-window flag from CLI's device-only flag, but “headless v1” in 09 can erase that distinction. Define “no visible window” separately from “no HWND/swapchain/desktop dependency”; source evidence is `runtime/engine/app/application.h:243` and `runtime/tools/uzengine.cpp:141–152`.

## Questions the architect must answer before deciding

1. **Recommendation:** What immutable, resolved UzEngine revision and generated-shader/binary baseline will UzPainter consume, given the current source conflicts?
2. **Recommendation:** Which exact Painter build, render mode, assets, smart-material/generator content and settings define “same instructions, same output”? Who supplies the reference instruction/result corpus?
3. **Recommendation:** Is acceptance literal byte/pixel equality, or a documented tolerance? What are the separate pass criteria for raw maps, lossless exports, compressed runtime maps and rendered display images?
4. **Recommendation:** Will the UzEngine preview be adapted to match the reference renderer, or will acceptance use a separate reference-compatible render mode? Which BRDF, IBL, color transforms, exposure and AA define it?
5. **Recommendation:** What exact bake projection, cage, hit matching, AO/thickness/curvature and sampling semantics must be reproduced? What happens where those reference semantics are not known?
6. **Recommendation:** Is DX12 Tier 1.1/SM6.5 inline tracing mandatory, and is heap-based SM6.6 binding also required by the selected shader route? Which fallback supports Tier 1.0, non-DXR GPUs and CPU-only CI?
7. **Recommendation:** Will baking use its own raw multi-object mesh importer/BLAS builder, or a repaired engine cook path? Which route preserves all objects, material IDs, transforms and original normals/tangents?
8. **Recommendation:** What is the canonical normal/tangent convention, including green orientation, mirrored UVs, per-corner splits, axis conversion and the reference baker's tangent settings?
9. **Recommendation:** Are UDIM, multiple UV sets, vertex colors, multiple material texture sets and high-poly textured projection required at first acceptance? How are tile/texture-set identities routed?
10. **Recommendation:** What precision and working color space are required for each channel throughout baking, layers, masks, cache, save and export? Which derivative compression/mip policies may change the result?
11. **Recommendation:** What are the exact channel-specific layer/group/mask blend semantics and procedural/generator assets? How will anchor/effect dependencies and incremental invalidation preserve evaluation order?
12. **Recommendation:** Which material consumer and binary container define the UzEngine preset, and what verified roundtrip demonstrates every exported key, ORM/opacity/height/thickness channel and texture-set binding?
13. **Recommendation:** What RAM/VRAM, descriptor, resolution, tile, layer and high-poly budgets are guaranteed, and what streaming/admission policy handles larger jobs without silent truncation?
14. **Recommendation:** What lossless readback queue, backpressure, fence/state model and tail-drain protocol guarantee that every channel/mip/tile reaches the CPU exactly once?
15. **Recommendation:** Does Windows headless support include service/noninteractive sessions? Does standalone mean one executable file or a distributable directory with SDK/compiler/runtime DLLs and content?
16. **Recommendation:** Is Python an in-process API, an embedded interpreter, or an external client/worker? How do Python, CLI and native MCP share the same GPU owner, job completion, cancellation and error contracts?
17. **Recommendation:** Which fixed clock, seeds, temporal-history resets, warmup/readiness rules and device/compiler settings make jobs reproducible, and how are those recorded with each result?
18. **Recommendation:** What must compact project saving preserve, which caches are disposable, and what reopen/migration/atomic-write guarantee prevents a smaller save from changing output?

**Recommendation:** Decide these contracts before approving the reuse scope or effort estimates. This review records source findings and proposed corrections; it does not authorize or perform changes to the engine.
