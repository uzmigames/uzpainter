# 10 — Response to the Astra Review of the UzEngine Renderer Analysis

Scope: finding-by-finding response to `docs/analysis/reviews/uzengine-renderer-astra-review.md` (20 findings F01–F20, 48 ledger claims, W01–W06, I01–I10, 18 questions). Every finding was re-checked against the UzEngine source at `E:\UzmiGames\UzEngine` (read-only, 2026-10-10). A finding is **accepted** when the source confirms it, **partially accepted** when the source confirms part of it and contradicts or snapshot-limits another part, **rejected** when the source contradicts it, and **forwarded** when it is architecture work rather than an analysis defect (forwarded to `phase2_docs-architecture`). Nothing was built or run.

## 1. Which source the analysis and the review each read

**Fact** — The analysis (files 01–09, written 2026-10-09 23:56 – 2026-10-10 00:02) matches UzEngine `HEAD 19ffb9b` (commit dated 2026-07-27): its line counts are those of HEAD (`uzengine.cpp` 1088, `build.zig` 1502, `CMakeLists.txt` 732; working tree: 1527, 1640, 1132).

**Fact** — At 2026-10-10 00:05:29 a merge of `9220973` ("Merge pull request #10 … feat/sponza-gi-parity", 2026-10-09) started in the UzEngine checkout (`.git/MERGE_HEAD`); it touches 58 files in the areas the analysis cites (`git diff --stat HEAD`). The review read this mid-merge working tree. Its conflicts therefore **postdate** the analysis, and the tree is still changing (files resolved at 00:18, 00:23, 00:28 and 00:30 while this response was written).

**Consequence** — Where a review "incorrect" verdict comes only from merge changes (C07, part of F08, part of F13), the original text was correct for its baseline; it is kept and annotated with the merge change rather than replaced. Every analysis file now opens with a **Baseline** line naming `HEAD 19ffb9b` and the mid-merge state.

## 2. Verdict summary

| Verdict | Count | Findings |
|---|---|---|
| Accepted | 16 | F03, F04, F05, F06, F07, F09, F10, F11, F12, F14, F15, F16, F17, F18, F19, F20 |
| Partially accepted | 3 | F02, F08, F13 |
| Rejected | 0 | — |
| Forwarded to architecture (`phase2_docs-architecture`) | 1 | F01 (plus the decision parts of F02, F07, F18, F20, noted per row) |

## 3. Finding-by-finding response

Engine paths are relative to `E:\UzmiGames\UzEngine\`; "HEAD" = `19ffb9b`, "WT" = mid-merge working tree.

| Finding | Severity | Verdict | Evidence (file:lines) | What changed and where |
|---|---|---|---|---|
| F01 — acceptance is output parity, roadmap is feature parity | blocker | **Forwarded** to architecture | `09` §1/§3 (feature list only); `runtime/shaders/runtime/postprocess/tonemap_ps.hlsl` HEAD 74-84 (passthrough mode); `gbuffer_ps.hlsl` HEAD 241-250 (specular-AA roughness change); owner decision `.rulebook/decisions/001-acceptance-criterion-output-parity-with-substance-painter.md` | Parity oracle, tolerances and reference corpus are architecture work. `09` gained a scope-limit paragraph stating the table is feature-level, excludes parity costs, and that parity is forwarded; `09` §3 step 3 now calls FLIP a measurement tool, not parity evidence. |
| F02 — source baseline unresolved, analysis not revision-pinned | blocker | **Partially accepted** | Conflict markers in 8 `runtime/` files (§4.1); `.git/MERGE_HEAD` = `9220973`, written 00:05:29; analysis files written 23:56-00:02 | Accepted: the analysis was not revision-pinned, and "done/tested/proven/reuse as-is" overstated source presence. Added a Baseline line to all nine files; replaced "proven"/"tested"/"already works"/"Reuse as-is" wording in `01` §5-§6, `02` §1/§6, `03` §1/§6, `09` G1. Snapshot-limited: `inspector_pass_validate.cpp`, cited by the review, has no markers and is no longer unmerged (resolved 00:18:11); the conflict set has changed since the review (§4.1). Pinning an immutable resolved baseline is forwarded (Q1). |
| F03 — UZMS glTF conversion is a concrete 32/48-byte defect | blocker | **Accepted** | `mesh_importer.cpp` 734-739 (writes `sizeof(VertexPosNormUV)` = 32 B); `mesh_io.cpp` 135-153 (copies unchanged when `srcStride ≤ 48`), 171-173 (reads at 48 B), 186 (publishes 48); identical in HEAD and WT | `05` §1: the "Hypothesis (risk)" became **Fact (defect)** with the out-of-bounds arithmetic as Hypothesis; `05` §5 item 1 no longer calls it a small change; `09` G18 rewritten as a correctness prerequisite; `01` §6 moves `asset/formats` to "fixes". |
| F04 — DXR 1.0 conflated with inline RayQuery | major | **Accepted** | `dx12_device.cpp` HEAD 307 / WT 336 (`RaytracingTier >= 1_0` only); `rhi_config.h` 28-30; no `RAYTRACING_TIER_1_1` query anywhere in `runtime/engine/` (grep); Microsoft DXR spec (inline ray tracing = Tier 1.1, SM6.5) | `03` §6: Tier 1.1/SM6.5 requirement and missing capability check; §8 split into pipeline RT and inline `RayQuery` rows; `09` G5, risk register and §3 step 3. |
| F05 — `.uztexture` validation documented, not enforced | major | **Accepted** | `uztexture_format.cpp` 60-110; `uztexture_format.h` 50-59, 163-179, 202-207; `texture_loader_ring.cpp` 45-110 (uint16 cast line 84, `break` line 110); unchanged HEAD→WT | `04` §5.2 new "Validation actually enforced" paragraph; Mip-data row distinguishes format vs cooker policy; `04` §8 final paragraph no longer claims the loader validates `mipCount`; new `09` G26; `01` §6. |
| F06 — MaterialBakerGpu is a limited evaluator, not a compositor | major | **Accepted** | `material_baker_gpu.h` 58-64 (AO = 4); `material_baker_gpu.cpp` 30-52 (wrapper declares only `BakeParams` + `outputTex`), 69-82, 176-181, 223-249, 269-270; `hlsl_material_translator.cpp` 404-411; `getTexIndex` defined only in `gbuffer_ps.hlsl` (HEAD 93); `scene_loader.cpp` HEAD 566-573 (graph AO pin = 6) | `03` §4 bullet rewritten with the limits; `09` G8 and §3 step 4; `01` §6. |
| F07 — precision and mip/compression policy can defeat parity | major | **Accepted** (policy forwarded) | `texture_importer.cpp` 54-80 (byte box filter), 178-181 (BC7 defaults), 260-262 (`SPNG_FMT_RGBA8`), 352-371 | `04` §5.3: 16-bit truncation upgraded from Hypothesis to Fact; `04` §8 rows for height/thickness and final paragraph state BC4 ≠ 16-bit and require canonical full-precision data; `09` §3 step 5. Per-channel precision/filter policy forwarded (Q10). |
| F08 — readback helpers are not a safe lossless exporter | major | **Partially accepted** | `frame_readback.cpp` 94, 185-230, 236-246, 252-286; `uzengine.cpp` HEAD 411 (`refW * 8`); `inspector_pass_dump.cpp` 45-100, 149-172; DX12 Z-slice: `dx12_command_list.cpp` diff HEAD→WT (WT 906-939); `vulkan_command_list.cpp` 1175 | Accepted: no slot-reuse/backpressure, `MapRead` without readiness check, unaligned FLIP pitch, pass dump skips targets and display-converts — `02` §3.2 rows, §3 summary, §6; `09` G12. Not accepted as an analysis error: "3D readback reaches only Z-slice 0" was **correct at HEAD**; only the incoming merge adds DX12 Z-slice selection. Kept and annotated in `02` §3.2 and `03` §5. `GetLdrIntermediate` added to `02` §2 and `09` G1. |
| F09 — slot sRGB defaults do not define the colour contract | major | **Accepted** | `material_interface.h` 200-209; `texture_loader_ring.cpp` 70-72 (format from file flag); `scene_texture_assets.cpp` 108-143 (cache keyed by path), 158-196 (cooked companion first), 575-577 (ring call without the slot's `isSRGB`) | `04` §4 paragraph on the two overrides; `09` G16. Colour pipeline beyond sRGB/linear forwarded (Q10). |
| F10 — tangent and UV guarantees weaker than the normal preset | major | **Accepted** | `gbuffer_ps.hlsl` HEAD 209-236; `mesh_tangents.cpp` 149-158; `fbx_importer.cpp` 32, 1446-1447, 1478, 1574-1584; `mikktspace_tangents.cpp` 63-73; `hlsl_material_translator.cpp` 420-422 | `04` §6 green-channel row: Hypothesis "+Y" withdrawn, now **not confirmed** with the code facts (§4.5); tangent rows restructured; `04` §7 and `05` §2 (`uvIndex` ignored = Fact); `05` §5 item 3 and `09` G17 separate UDIM from multi-UV; `09` G15. |
| F11 — high-poly processing mischaracterised; BLAS assumptions hidden | major | **Accepted** | `fbx_importer.cpp` 1242 (first mesh), 2047 (≤ 50,000-index SDF guard); `mesh_importer.cpp` 383 (first mesh), 752-788 (unguarded SDF); `uzmesh.cpp` HEAD 1106-1112 (extra LODs); `blas_manager.cpp` 31-37 (stride 48, opaque) | `05` §2, §3.1, §3.2 (both rows), §4 table and Recommendation; `09` G5, G7; `03` §6. |
| F12 — export fields confused with reader support; graph ORM overwritten | major | **Accepted** | `scene_loader.cpp` HEAD 756-856 (inline block, identical in WT 833-933), 770-777 (graph ORM), 848 (`ReadString(comp, "orm")`), 199-205 (`ReadString` returns empty); `uzcook.cpp` 201-288 (exact substrings, default BC7 sRGB) | `04` §2, §2.1, §3 table (non-inline keys marked) + defect paragraph, §5.3 table (exact substrings; `height`/`thickness` fall to BC7 sRGB), §8 rows for height/opacity/thickness; new `09` G27; `09` G14. |
| F13 — packaging ownership and Agility paths need a source-based recipe | major | **Partially accepted** | `CMakeLists.txt` HEAD 427 (include dir only), no HEAD target compiles screenshot `.cpp`; WT 902-913, 1072 (`uzengine_editor`); `dx12_agility.cpp` 17; `dx12_device.cpp` HEAD 185, 334-424 (`TryLoadAgilitySdk`, `CreateDeviceFactory`, `GetExeDir`); `build.zig` HEAD 1398-1427 (no FFmpeg DLL install), WT 1488-1536 | Accepted: `01` §2 CMake claim was wrong at HEAD too; Agility has two activation routes; footprint is a Hypothesis — `01` §2/§4, `07` §2, §2.1, §6. Not an analysis error: "FFmpeg DLLs are copied by the N-API CMake step" was **correct at HEAD**; the Zig copy step exists only in the merge — annotated in `07` §2. One-file vs folder decision forwarded (Q15). |
| F14 — `ctypes` is in-process; thread ownership not established | major | **Accepted** | `runtime.h` 6-11, 224; `napi/src/render_thread.h` 13-19; `extension/src/runtime-client.ts` 411 (`cp.fork`) | `07` §4 option A relabelled in-process with no crash isolation, new option A2 (worker process); `07` §5 thread-rule note and SEH vs worker distinction; `08` §5. One-owner-thread protocol forwarded (Q16). |
| F15 — Null is not an implemented no-op renderer | minor | **Accepted** | `rhi_backend.h` 23; `rhi_config.cpp` HEAD 45, 90; `rhi_factory.cpp` 36-93 (no `Null` case → `nullptr`) | `02` §1 row, `03` §1 row, `09` risk register, `01` §6. |
| F16 — vendored encoders invalidate blanket absence claims | minor | **Accepted** | `thirdparty/basis_universal/encoder/basisu_bc7enc.h`; `encoder/basisu_astc_hdr_6x6_enc.cpp` 3388 (`pack_bc6h_image`); `transcoder/basisu_astc_hdr_core.h` 72-76; `encoder/3rdparty/tinydds.h` 43, 688; `build.zig` HEAD 578-582 and HEAD `CMakeLists.txt` 219-220 build only the transcoder | `06` §1 Basis and etcpak rows, BC6H Fact, §5 DDS/BC6H rows; `09` G13, G22; `01` §6. |
| F17 — 16-bit PNG export API narrower than stated | minor | **Accepted** | `png_codec.h` 68-90; `png_codec.cpp` 327 (8-bit IHDR), 353-416 (`EncodeMemory` 8/16, byte swap) | `02` §4 and §6; `06` §1 libpng row, §5; `04` §8; `09` §3 step 5. |
| F18 — CLI capture controls are not a determinism contract | major | **Accepted** (contract forwarded) | `uzengine.cpp` HEAD 835-837 (wall-clock `dt`); HEAD 877-882 (120-frame bypass; removed in WT 1250-1255); `postprocess/exposure_average_cs.hlsl`, `taa_resolve_cs.hlsl` | `02` §5 now says these are capture aids, not a determinism contract; `02` §2 step 10 notes the merge removes the bypass. Fixed-clock/seed/warmup contract forwarded (Q17). |
| F19 — serialization and synchronous-API wording overstated | minor | **Accepted** | `uztexture_format.cpp` 13-55; `mesh_importer.cpp` 729-744; `runtime.h` 13-16 ("until the next call to the same function"); `scene_texture_assets.cpp` 182-215 (async texture submission) | `08` §2.1 intro and Scene row, §3 JSON bullet, §4 last row, §5 jobs row. |
| F20 — broad capability/effort claims lack evidence | major | **Accepted** (capacity inventory forwarded) | `build.zig` HEAD 24, 575 (Tracy always on), 659-674 (C++20 TU = `bc7enc.cpp`), 381-390 (fastgltf C++17); `dx12_device.h` 47-56 (descriptor caps); `dx12_device.cpp` HEAD 1265 (`QueryVideoMemoryInfo`) | `07` §1 Tracy row and C++20 TU; `06` §2 fastgltf row; `03` §10 descriptor/VRAM facts; `03` §3 per-mip workaround; footprint and DLL savings relabelled Hypothesis (`07` §2.1, `06` §6); `09` scope says effort excludes parity work. |

## 4. Items settled with code evidence

### 4.1 Merge-conflict markers under `runtime/`

**Fact** — Snapshot 2026-10-10 00:30:30 -0300; search for lines starting with `<<<<<<< `, `=======` (alone on the line) and `>>>>>>> ` under `E:\UzmiGames\UzEngine\runtime\`. Each file has matching counts of the three markers.

| File | Conflict blocks | `<<<<<<<` lines |
|---|---|---|
| `runtime/shaders/runtime/lighting/deferred_lighting_ps.hlsl` | 8 | 173, 724, 858, 886, 1003, 1342, 1393, 1535 |
| `runtime/engine/renderer/frame/frame_constants.cpp` | 3 | 129, 813, 897 |
| `runtime/engine/renderer/scene/scene_renderer_init.cpp` | 2 | 179, 803 |
| `runtime/engine/renderer/core/params/constant_buffers.h` | 1 | 283 |
| `runtime/engine/renderer/core/params/per_frame_params.h` | 1 | 284 |
| `runtime/engine/renderer/frame/frame_setup.cpp` | 1 | 367 |
| `runtime/engine/renderer/scene/scene_renderer.h` | 1 | 64 |
| `runtime/tests/engine/renderer/test_gi_gpu.cpp` | 1 | 774 |
| **Total** | **18 blocks (54 marker lines) in 8 files** | all `>>>>>>> 9220973318f1e94f4cfd276a0a4a2d3162401ac3` |

- Two further `=======` matches (`thirdparty/fastgltf/docs/api.rst`, `thirdparty/slang/share/doc/slang/cuda-target.md`) are documentation heading underlines, not conflicts.
- `git ls-files -u` lists 11 unmerged paths: the 8 files above, `runtime/engine/renderer/frame/frame_gi_passes.cpp` and `runtime/engine/renderer/scene/scene_renderer_impl.h` (no markers left, not yet staged), and `sample/content/scenes/sponza.uzscene` (outside `runtime/`, 1 block).
- The set is moving: a scan started minutes earlier also found markers in `renderer/gi/ddgi_system.{cpp,h}` and `shaders/runtime/gi/{ddgi_probe_update_cs, global_sdf_composite_cs, mesh_sdf_bake_cs, radiance_cache_trace_cs}.hlsl` (resolved by 00:28), and the review's `inspector_pass_validate.cpp` was resolved at 00:18.
- None of the conflicted files carries a behaviour the analysis states as Fact; `scene_renderer.h`'s block (WT 64-68) is outside the declarations cited in `02`/`09`.

### 4.2 glTF 32-byte vs 48-byte stride

**Fact** — `MeshImporter` (glTF cook) serialises `std::vector<VertexPosNormUV>` with `header.vertexStride = sizeof(VertexPosNormUV)` = 32 (`mesh_importer.cpp` 611, 734-739; `uzmesh_format.h` 244-251 `static_assert` 32). `mesh_io.cpp` converts UZMS to UZMH: for `srcStride > 48` it copies 48 of every 56 bytes (142-150); otherwise it assigns `uz.vertexData` unchanged (152), then reads positions at `i * 48` (171-173) and writes `vertexStride = 48` (186). **Hypothesis (consequence):** for `n ≥ 3` vertices the AABB loop reads past `n·32` bytes; rendered attributes and any BLAS built from the mesh are misinterpreted. No run reproduced a crash. Identical in HEAD and WT.

### 4.3 `.uztexture` reader validations

**Fact** — `ReadUzTexture` enforces: data ≥ 64-byte header; magic `UZTX`; version 1; `64 + mipCount·24 ≤ size`; per mip `offset + size ≤ size` (`uztexture_format.cpp` 60-110). Not enforced, though documented as MUST (`uztexture_format.h` 50-59, 163-179, 202-207): `mipCount` range, base/per-mip dimensions, per-mip byte sizes, flags/reserved bits zero. `LoadUzTexViaRing` duplicates the header checks, casts `mipCount` to `uint16` (`texture_loader_ring.cpp` 84), stops silently with `break` on an out-of-file mip (110), and takes the GPU format from the file's own sRGB flag (70-72). The `offset + size` sums are unguarded `uint64` additions.

### 4.4 What `MaterialBakerGpu` supports

**Fact** — One compute dispatch per call evaluating `ComputeMaterialOutputs` at texel-centre UVs; output RGBA8 UNORM, UAV+SRV (`material_baker_gpu.cpp` 176-181); selectors BaseColor 0, Metallic 1, Roughness 2, Normal 3 (encoded `n·0.5+0.5`), AO 4 (`.h` 58-64; `.cpp` 92-97); `materialParams[16]` zeroed, world position/normal/vertex colour/camera/light/time constant (69-82); bound resources: root constants (width, height, selector) and the output UAV only (223-249); Graphics-queue command list, CPU wait on a new fence (194-213, 269-270). **Not supported:** texture inputs (the translator's `getTexIndex`/`linearSampler` are not declared in the wrapper), user parameters, mesh surface data, emissive/opacity outputs, formats other than RGBA8, asynchronous completion. Compile success for graphs with `TextureSample` nodes is **not confirmed** (nothing compiled).

### 4.5 Normal-map green channel

**Fact (what the code shows):**

1. The GBuffer decodes `xy = rg·2 − 1`, scales by `normalIntensity`, reconstructs `z = sqrt(1 − x² − y²)` and outputs `x·T + y·B + z·N` with `B = cross(N, T)·tangent.w`; there is no sign flip of green in either binding path (`gbuffer_ps.hlsl` HEAD 209-236, WT 217-243).
2. `tangent.w` comes from MikkTSpace in the FBX cook (default of CVar `r.Mesh.TangentMode`, `fbx_importer.cpp` 32, 1574-1584), or from the Lengyel sign `sign(dot(cross(N, T), B))` in standalone tools (`mesh_tangents.cpp` 149-158; `uzmesh.cpp` HEAD 1091). The glTF cook computes MikkTSpace tangents but does not store them (§4.2).
3. FBX importers flip V (`fbx_importer.cpp` 1478; `uzfbx.cpp` 150-153); glTF importers keep `TEXCOORD_0` unchanged; axis remaps and winding flips differ per importer (`fbx_importer.cpp` 368-382, 1425, 1508).
4. No engine source, doc or test in the UzEngine repository states an expected green-channel convention (case-insensitive grep for green-channel/OpenGL/DirectX normal-map terms outside `thirdparty/`).

**Not confirmed:** whether green maps to +V or −V of the texture for each import path, and therefore whether OpenGL (+Y) or DirectX (−Y) maps render correctly; per-corner tangent behaviour for indexed inputs other than the FBX cook; the effect of mirrored UVs. The earlier "+Y" Hypothesis in `04` §6 was withdrawn because its only support (a glTF sample rendering) cannot have used stored glTF-cook tangents.

## 5. Unsourced claims (W) and cross-document inconsistencies (I)

| Item | Verdict | What changed and where |
|---|---|---|
| W01 — blanket "reuse as-is" | Accepted | `01` §6 split into "reuse candidates (presence only, test required)" and "reuse with fixes", with the concrete limits. |
| W02 — universal negatives | Accepted | Scoped: `02` §1 key fact, `06` BC6H/DDS/etcpak, `07` §4 Python, `08` §3 JSON and §5 job model. |
| W03 — performance figures as budgets | Accepted | `05` §3.3 Sponza figure marked "reported, not re-measured"; `03` §5 upload figure and `02` §3 H.264 latencies were already attributed to their docs. |
| W04 — quality/compatibility claims | Accepted | `09` G22 BC7 quality comparison → not confirmed; `04` §6 MikkTSpace compatibility comment → "a comment, not evidence". |
| W05 — deployment/legal claims | Accepted | `06` §6 marked as README summary, not a licence audit; DLL savings → Hypothesis; `07` §1 compiler badges were already "claimed, not re-verified". |
| W06 — estimates and untagged derivations | Accepted | `01` §1 "only needs Runtime" → Recommendation; `01` §2 "~100-line class" replaced by the measured 287 + 144 lines; `07` "4-6 DLLs" → Hypothesis; `04` normal convention → not confirmed; `09` effort letters already labelled Recommendation/Hypothesis, scope now excludes parity costs. |
| I01 — module ownership | Accepted | `01` §2 corrected (see F13). |
| I02 — reuse vs glTF correctness | Accepted | `01` §6 and `09` G18 (see F03). |
| I03 — DXR tier | Accepted | `03` §6/§8, `09` G5 (see F04). |
| I04 — precision vs proposed exports | Accepted | `04` §8 and `09` §3 step 5 require canonical full-precision data separate from runtime derivatives (see F07). |
| I05 — Python required, not optional | Accepted | `README.md` lines 9, 52 state the Python API requirement; `09` G19 and §3 step 7, `08` §5 updated. |
| I06 — JSON vs binary assets | Accepted | `08` §3 (see F19). |
| I07 — opacity/export binding | Accepted | `04` §2.1, §8 and `09` G14, G27 (see F12). |
| I08 — transport/isolation | Accepted | `07` §4 options A/A2 (see F14). |
| I09 — BC6H blanket negative | Accepted | `06` §1, `09` G13 (see F16). |
| I10 — headless terminology | Accepted | `02` §6 and `09` G1 now distinguish "no visible window" from "no HWND/swapchain/desktop dependency". |

## 6. Additional corrections found during verification

| Id | Finding | Evidence | Change |
|---|---|---|---|
| A01 | `04` §1 said no loader exists for `.uzmaterial`. The scene loader has a minimal `.uzmaterial` branch (`"asset"` field) reading six texture keys and three properties, and it routes `metallic_roughness_map` into the ORM slot, so that map's R channel is read as AO. | `scene_loader.cpp` HEAD 659-704 (WT 736-781) | `04` §1 row corrected. |
| A02 | `04` §5.3 filename substrings were approximate (`col`, `orm`, `ao`, `mask` are really `_col_`/`_col.`, `_orm`/`orm_`, `_ao`, `_mask`). | `uzcook.cpp` 201-288 | `04` §5.3 table corrected. |
| A03 | `04` §3 listed `twoSided`, `alphaTest`, `alphaClipThreshold`, UV transform and extended-model fields as scene-loader JSON keys; none is read inline (`twoSided` and `alphaClipThreshold` come only from `.uzmat` metadata). | `scene_loader.cpp` HEAD 756-856; WT 592, 612 | Marked "not inline keys" in `04` §3; `09` G27. |
| A04 | Several `04` §6 rows had three cells in a four-column table. | `04` §6 | Rows restructured to four cells (no content loss). |

## 7. Cross-review items

Raised by the pipeline-analysis correction agent (relayed by the coordinator) and verified here against UzEngine source.

| Claim | Verdict | Evidence (file:lines) | What changed and where |
|---|---|---|---|
| Height, Thickness and SpecularWeight maps fall to `uzcook`'s default rule (BC7 sRGB) because no name rule matches them | **Accepted** | `runtime/tools/uzcook.cpp` 201-283 (all name rules; none contains `height`, `thickness`, `disp` or `specular`), 285-288 (default BC7, `outSRGB = true`) | `04` §5.3 last row names them; `04` §8 Height/Thickness rows already require direct `WriteUzTexture` (F12). |
| Opacity is cooked to BC4 while `gbuffer_ps.hlsl` reads opacity from the albedo alpha | **Partially accepted** | `uzcook.cpp` 276-283 (BC4); `gbuffer_ps.hlsl` HEAD 272-294: on the SM6.6 bindless path the shader reads the **opacity texture's `.a`** when one is bound and falls back to albedo alpha; on the SM5 path it always reads the opacity texture's `.a` (`t6`) and never albedo alpha; the graph path uses the graph's Opacity output | `04` §2.1 Opacity row rewritten per path; §2.1 recommendation and §8 base-colour row now say base-colour alpha works as a mask on the bindless path only; `09` G14 evidence lines updated. |
| The cooker decodes every input to 8 bits | **Accepted** | `texture_importer.cpp` 215 (inputs `.png/.jpg/.jpeg/.tga` only), 260-262 (`SPNG_FMT_RGBA8`), 320 (`stbi_load_from_memory`, 8-bit) | `04` §5.3 states the accepted extensions; 16-bit truncation already a Fact (F07). |
| The FBX importer recomputes normals by default | **Accepted** | `fbx_importer.cpp` 30-31 (`r.Mesh.NormalImportMode` default 1 = Recompute; `r.Mesh.SmoothingAngle` 60°), 1519-1541 (per-asset `.uzimport` `normalMode`/`smoothingAngle` override); glTF cook recomputes only when normals are missing (`mesh_importer.cpp` 523-530) | `05` §3.2 FBX and glTF rows; `05` §5 item 2 now covers normal parity for bakes. |
| Normal-map +Y convention | **Not confirmed** (unchanged) | §4.5 | No change: the code does not settle it. |

## 8. Ledger rows whose verdict depends on the snapshot

Re-checked against HEAD and WT: C01-C04, C07-C09, C12-C14, C16, C18-C21, C23, C25, C27-C30, C32, C35-C37, C39-C46. The other rows the review marks Confirmed needed no text change and were not re-opened.

| Row | Review verdict (WT) | At HEAD `19ffb9b` | Result |
|---|---|---|---|
| C02 CMake screenshot ownership | Incorrect; files belong to `uzengine_editor` | Also incorrect, but differently: `editor/screenshot` is an include directory and **no** HEAD CMake target compiles it; `uzengine_editor` exists only in the merge | Corrected with both facts (`01` §2). |
| C07 120-frame bypass | Incorrect for this snapshot | Correct: bypass at HEAD 877-882 | Kept; merge removal noted (`02` §2). |
| F08 3D Z-slice | Statement obsolete | Correct at HEAD (`dx12_command_list.cpp` diff) | Kept; merge change noted (`02` §3.2, `03` §5). |
| F13 FFmpeg DLL copy | Zig now copies them | Correct at HEAD: only the N-API CMake step copies them | Kept; merge change noted (`07` §2). |
| C45 Tracy in release | Incorrect | Also incorrect at HEAD (line 24, 575) | Corrected (`07` §1). |

## 9. Questions for the architect, with what the code answers

| # | Question (short) | What the UzEngine code establishes | Still open |
|---|---|---|---|
| Q1 | Immutable resolved engine baseline | HEAD `19ffb9b` (2026-07-27) is clean; the checkout is mid-merge with `9220973` (PR #10, 2026-10-09) with 18 conflict blocks in 8 `runtime/` files (§4.1). No resolved commit containing the merge exists yet. | Which commit to pin, and whether generated shaders/binaries are rebuilt from it. |
| Q2 | Painter build, settings and reference corpus | Nothing in UzEngine. | Entirely open. |
| Q3 | Literal equality vs tolerance | FLIP pass/threshold output exists (`uzengine.cpp` `FLIP_JSON`); it is a metric, not a criterion. | Criteria per stage. |
| Q4 | Adapt preview vs separate reference mode | Engine has its own tonemap (passthrough mode, HEAD `tonemap_ps.hlsl` 74-84), specular-AA roughness change (`gbuffer_ps.hlsl` HEAD 241-250), TAA and auto-exposure. | Reference renderer definition. |
| Q5 | Bake projection semantics | No bake kernels, cage or hit-selection code exists; only RT primitives and `RayQuery` shaders for GI. | Entirely open. |
| Q6 | Tier 1.1/SM6.5 mandatory; fallbacks | Engine queries only Tier ≥ 1.0; `RayQuery` shaders need Tier 1.1/SM6.5; Vulkan and DX11 have no RT; `Null` is not implemented, so CPU-only CI has no engine device. | Mandatory tier and fallback policy. |
| Q7 | Raw bake importer vs repaired cook path | Every importer takes the first mesh only; the glTF cook path is defective (§4.2); `BLASManager` is fixed to stride 48/opaque, while raw `CreateBLAS` accepts any `RGB32Float` stride. | Route choice. |
| Q8 | Canonical normal/tangent convention | §4.5. | Convention and calibration. |
| Q9 | UDIM, multi-UV, vertex colour, texture sets | One UV, no vertex colour, `uvIndex` ignored; a 6-layer array becomes a cube SRV on DX12; importers emit one submesh per material (FBX) or none (`uzgltf`/`uzfbx`). | Scope for first acceptance. |
| Q10 | Precision and colour space per channel | RHI has R16F/RGBA16F/R32F but no 16-bit UNORM or BC6H; cooker and GPU baker are RGBA8; `.uztexture` has no float/16-bit formats; `PngCodec` decodes 16-bit and encodes 16-bit to memory. | Policy per channel. |
| Q11 | Layer/mask blend semantics | None in the engine beyond fixed-function RT blend states. | Entirely open. |
| Q12 | UzEngine preset consumer and round trip | Inline scene keys and the `.uzmaterial` branch are listed in `04` §1/§3; ORM overwrite defect (F12); no inline opacity/thickness/height keys. | Which consumer, and loader fixes. |
| Q13 | RAM/VRAM/descriptor budgets | Descriptor caps 1,000,000 / 2,048 / 256 / 64; VRAM budget query exists; texture dims `uint32`, mips/layers `uint16`; no admission policy found. | Budgets and streaming policy. |
| Q14 | Lossless readback protocol | Only `FrameReadback` is non-stalling and it has no backpressure (F08). | Protocol design. |
| Q15 | Service-session headless; one file vs folder | CLI `--headless` is device-only; scene rendering needs an HWND + swapchain; Agility has export and programmatic routes (F13). Service-session behaviour not confirmed. | Support matrix and packaging form. |
| Q16 | Python hosting model and thread ownership | C API: init/viewport on main thread, render on viewport thread; `ctypes` would be in-process; the extension isolates the engine in a forked worker. | Model choice. |
| Q17 | Reproducibility controls | `dt` is wall-clock; `frameIndex` drives rendering; temporal exposure/TAA exist; `--editor` only stops scripts. | Fixed clock, seeds, warmup, manifest. |
| Q18 | Compact save guarantees | `lz4`/`.uzpak` and xxHash content caches exist; no project format exists. | Entirely open. |

## 10. Not verified

- No build, run, GPU validation or Painter comparison; all consequences of defects (F03, F05, F06, F09, F12) remain Hypotheses about runtime effect.
- The DXR Tier 1.1 / SM6.5 requirement for inline ray tracing is taken from the Microsoft DXR specification as cited by the review; not re-fetched here.
- Ledger rows not listed in §7 were accepted as the review states them without re-opening the source.
- The conflict list in §4.1 is a snapshot of a tree that someone is actively resolving; re-run the search before relying on it.
