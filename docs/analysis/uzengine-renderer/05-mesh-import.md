# 05 — Mesh Import: FBX / glTF / OBJ / STL, Internal Representation, Limits

Scope: how meshes enter UzEngine today, what the runtime vertex is, where tangents come from, and whether multi-million-triangle high-poly sources are viable. Paths relative to `E:\UzmiGames\UzEngine\`.

**Baseline** (added after the Astra review, see `10-review-response.md`): line numbers refer to UzEngine `HEAD 19ffb9b` (2026-07-27). The mesh files cited here (`mesh_io.cpp`, `mesh_importer.cpp`, `fbx_importer.cpp`, `blas_manager.cpp`) are identical in the mid-merge working tree; `uzmesh.cpp` shifts by 2 lines. Source reading only; no import was run.

## 1. Two cooked mesh containers exist

| Container | Magic | Header | Vertex | LODs | Submeshes | Written by | Evidence |
|---|---|---|---|---|---|---|---|
| **UZMH** (`renderer/mesh/mesh.h`) | `0x484D5A55` "UZMH" | 128 bytes, v2 | `Vertex` 48 B (pos, normal, uv, tangent.xyzw) or `SimpleVertex` 36 B | LOD0 + up to 3 extra index ranges in header | `submeshCount` + `SubMesh{startIndex,indexCount,materialIndex}` | `uzmesh.exe`, `uzfbx.exe`, `uzgltf.exe`, `FbxImporter` static path (`fbx_importer.cpp` lines 1969-1985) | **Fact** |
| **UZMS** (`asset/formats/uzmesh_format.h`) | `0x534D5A55` "UZMS" | 64 bytes, v2 | arbitrary `vertexStride`; documented layouts `VertexPosNormUV` 32 B and `SkinnedVertex` 56 B (+ skeleton path when `kUzMeshFlag_Skinned`) | `UzMeshLOD{lodLevel, submeshOffset, submeshCount, screenHeightThreshold}` table | `UzMeshSubmesh{vertexOffset, indexOffset, indexCount, materialIndex}` table; 64-byte aligned data | `MeshImporter` (glTF cook, `mesh_importer.cpp` lines 729-744), `FbxImporter` skinned path (line 1919) | **Fact** |

**Fact** — Runtime loading detects UZMS (`LoadMesh/LoadMeshFromMemory`, `renderer/mesh/mesh_io.cpp` lines 38-45, 120-200) and builds a UZMH `Mesh` from it. The vertex conversion is only defined for strides ≥ 48: when `srcStride > 48` it copies the first 48 bytes of each record and keeps the 56 B stream for GPU skinning (lines 142-150); otherwise it copies the vertex bytes unchanged (line 152).

**Fact (defect)** — The glTF cook importer writes 32 B `VertexPosNormUV` records (`mesh_importer.cpp` lines 734-739), and its own comment says the format "currently uses VertexPosNormUV (32 bytes, no tangent)", so the MikkTSpace tangents it computes are not stored (lines 71-90). `mesh_io.cpp` copies those 32 B records unchanged (line 152), reads positions at a 48-byte stride for the AABB (lines 171-173) and publishes `vertexStride = 48` (line 186). No 32→48 expansion or tangent generation happens in this branch. **Hypothesis (consequence):** for a UZMS with 3 or more 32 B vertices the AABB loop reads past the end of the vertex buffer (`(n-1)·48 + 12 > n·32` for `n ≥ 3`), and rendered attributes and BLAS input are misinterpreted; no crash was reproduced. The UZMH path (48 B with tangents) is the one every standalone tool and the static FBX cook produce; the cooked glTF route is not reusable until this is fixed.

**Fact** — The JSON `runtime/schemas/uzmesh.schema.json` (semantics `texcoord1`, `color0`, `joints0`, `import_settings.generate_tangents` "MikkTSpace", `generate_lods`) is a descriptive schema; the binary formats above are what the code reads.

## 2. Runtime vertex and GPU representation

**Fact** — `renderer/mesh/vertex.h`:

```
Vertex        48 B: Vec3 position; Vec3 normal; Vec2 texcoord; Vec4 tangent (w = handedness ±1)
VertexPacked  32 B: position; int8x4 normal; Vec2 uv; int8x4 tangent(+sign); pad   (header only)
SimpleVertex  36 B: position; Vec4 color; Vec2 uv
SkinnedVertex 56 B: Vertex + uint8 boneIndices[4] + uint8 boneWeights[4]
```

- **One UV set** and **no vertex colour** in the standard vertex (**Fact**). Multi-UV (UV1 lightmap, UV2 detail) and vertex colour are documented as *Planned (Phase 3+)* in `docs/engine/12-rendering/12-multi-material-multi-uv.md`; `TexCoord(uvIndex)` in the material graph has nothing to select from today (**Fact**: the translator ignores `uvIndex` and always emits `uv`, `hlsl_material_translator.cpp` lines 420-422).
- Vertex data is uploaded as StructuredBuffers and fetched bindlessly via `SV_VertexID` on SM6.6; Input Assembler layout on SM5 (`vertex.h` header comment; `docs/engine/03-rhi/04-pipeline-state.md`).
- `GPUMesh` (`renderer/mesh/gpu_mesh.h`) holds the buffer handles; `BLASManager::GetOrBuildBLAS(meshId, GPUMesh&, cmdList)` builds DXR BLAS from the same buffers (positions must be `RGB32Float` at a stride — `RHIRTGeometryDesc.vertexStride` allows the 48 B interleaved stride). `BLASManager` itself hardcodes `vertexStride = 48` and `isOpaque = true` (`blas_manager.cpp` lines 31-37), so a packed position-only stream or cutout geometry needs the raw RHI `CreateBLAS` or a parameterised manager.

**Fact** — Coordinate system: left-handed, X-forward, Y-right, Z-up, centimetres; index formats uint16 (<65536 vertices) or uint32 (`mesh.h`; `MeshIndexFormat`). All importers currently emit uint32 (`uzmesh.cpp`/`uzfbx.cpp`/`uzgltf.cpp` `MeshIndexFormat::UInt32`; `mesh_importer.cpp` line 735; `fbx_importer.cpp` lines 1917, 1980).

## 3. Importers

### 3.1 `uzmesh.exe` — unified standalone converter (`runtime/tools/uzmesh.cpp`, 1313 lines)

**Fact**:

- Formats: `.fbx` (ufbx), `.gltf/.glb` (fastgltf), `.obj` (built-in parser), `.stl` (binary/ASCII); `--builtin cube|sphere`.
- Pipeline: parse → axis conversion (Y-up → Z-up LH, `Engine.X = src.Z, Engine.Y = src.X, Engine.Z = src.Y`) → dedup (`meshopt_generateVertexRemap` for OBJ/STL/glTF; `ufbx_generate_indices` for FBX in `uzfbx.cpp`) → winding flip → `meshopt_optimizeVertexCache` → **Lengyel tangents** (`GenerateTangents`) → AABB → auto-LOD (`meshopt_simplify` to 50 % / 25 % / 12.5 % indices as **additional** LODs; LOD0 keeps the full index list; `renderer/mesh/auto_lod.h`, `uzmesh.cpp` lines 1106-1112) → `SaveMesh` UZMH.
- FBX: `target_unit_meters = 0.01` (cm), `UFBX_SPACE_CONVERSION_MODIFY_GEOMETRY`, `generate_missing_normals`, **first mesh only** (`scene->meshes.data[0]`), V flipped (`1 - v`), UV defaults to (0,0) when absent.
- glTF: `LoadExternalBuffers | GenerateMeshIndices`, **first mesh, all primitives** concatenated, `POSITION/NORMAL/TEXCOORD_0` only (no `TEXCOORD_1`, no `COLOR_0`, no `TANGENT` read — tangents always regenerated), flat normals if missing.
- No submesh/material table is written by `uzgltf`/`uzfbx` (`submeshCount = 0`).

### 3.2 `uzcook` importers (content-addressed cook pipeline)

| Importer | File | Version | Highlights (**Fact**) |
|---|---|---|---|
| `FbxImporter` (`.fbx`) | `engine/asset/importers/fbx_importer.cpp` | 17 (CHANGELOG v0.9.6) | first mesh (`scene->meshes.data[0]`, line 1242); per-face triangulation; **authored normals recomputed by default** (CVar `r.Mesh.NormalImportMode` = 1 "Recompute", 60° `r.Mesh.SmoothingAngle`, per-asset `.uzimport` `normalMode`/`smoothingAngle` override; lines 30-31, 1519-1541); MikkTSpace tangents by default (CVar `r.Mesh.TangentMode`, line 1579); meshopt cache/fetch optimisation; PBR material extraction into `AssetImportResult::materials`; one submesh per material; static → UZMH 48 B, skinned → UZMS 56 B + `.uzskel/.uzanim`; per-source axis convention (Maya Y-up RH vs 3ds Max Z-up RH); **SDF sidecar bake** (`BakeMeshSdf`, line 2058, CPU voxel SDF for distance-field shadows) only when the optimised index count is ≤ 50,000 (line 2047; comment: the baker "hangs on meshes with >50K indices") |
| `MeshImporter` (`.gltf/.glb`) | `engine/asset/importers/mesh_importer.cpp` | 2 | first mesh (`gltf.meshes[0]`, line 383), all primitives as submeshes; MikkTSpace tangents computed (line 558) but output is 32 B `VertexPosNormUV` (line 734); meshopt optimisation; auto-LODs with thresholds; materials extracted; smooth normals computed only when the glTF has none (lines 523-530); **SDF sidecar bake with no size guard** (lines 752-788) |
| `LightmapUVGenerator` | `engine/asset/importers/lightmap_uv_generator.h` | — | xatlas wrapper: `GenerateLightmapUVs(positions, normals, uv0, indices, {maxChartSize, padding=2, resolution=1024, bruteForce})` → UV1 + remapped positions/normals/UV0/indices, chart count, atlas size. Thread-safe. |
| `NormalSmoother` | `engine/asset/mesh/normal_smoother.h` | — | listed; not read |
| `SdfBaker` | `engine/asset/importers/sdf_baker.h` | — | CPU narrow-band SDF, spatial hash nearest-triangle, "~100 ms for 64³ on a medium-complexity mesh" |

**Fact** — `uzcook` only compiles on Windows (`#ifdef _WIN32`, `uzcook.cpp` line 29) and registers `FbxImporter`, `MeshImporter`, `ShaderImporter`, `TextureImporter` (`--textures-only` restricts to textures).

### 3.3 Runtime mesh loading

**Fact** — `SceneRenderer::LoadMesh(path, vfs, …)` / `RequestMeshAsync()`; `AsyncMeshLoader` worker pool `max(2, hw/2)` threads, GPU integration budget `r.LazyLoad.MeshesPerFrame` (default 32), stall-free staging retirement (`docs/runtime/asset-loading.md`; `renderer/upload/async_mesh_loader.h`). Reported in CHANGELOG v0.9.7 (configuration not recorded, not re-measured here): 138 Sponza meshes in 1.25 s.

## 4. Capacity for multi-million-triangle high-poly meshes

| Concern | Finding | Tag |
|---|---|---|
| Hard caps | Index/vertex counts are `uint32`; no explicit triangle limit in importers or formats | **Fact** |
| Whole-file in memory | All parsers load the entire source into RAM and build full `std::vector<Vertex>` (48 B) + index arrays; a 10 M-triangle mesh ≈ 30 M corners before dedup ≈ 1.4 GB transient in the FBX path (`uzfbx.cpp` pushes one `Vertex` per corner before `ufbx_generate_indices`) | **Hypothesis** (arithmetic on the code path) |
| Mandatory heavy steps | `uzmesh`/`uzfbx`/`uzgltf` always run `meshopt_simplify` ×3 (extra LODs; LOD0 is not replaced) and `optimizeVertexCache`; the cook importers bake a CPU SDF — `FbxImporter` only up to 50,000 indices, `MeshImporter` (glTF) with no guard; none of this is needed for a bake source | **Fact** (code paths); cost **not measured** |
| ufbx / fastgltf capability | Both libraries handle large files (claimed by their upstream docs; not verified here) | **not confirmed** |
| Validation planned | `docs/engine/08-resource-system/06-mesh-pipeline.md` ("Planned") lists "Vertex count < 65536 (16-bit index buffer check)" and "Bone count ≤ 256"; not implemented in the read code | **Fact** (doc) |

**Recommendation** — For baking, bypass `.uzmesh`/LOD/SDF entirely: load the high-poly with ufbx/fastgltf (both vendored) straight into GPU position/index buffers and a BLAS through the raw RHI `CreateBLAS` (`RHIRTGeometryDesc` needs only positions `RGB32Float` + indices; `BLASManager` assumes the 48 B opaque layout), keep normals/tangents/UVs in side buffers for sampling, and traverse all objects, instances/transforms and material/face IDs, since every current importer takes the first mesh only. Maximum practical high-poly size, peak parser RAM and AS build time are **not confirmed**. Low-poly goes through the normal path (MikkTSpace via `ComputeMikkTSpaceTangents`, `engine/asset/mesh/mikktspace_tangents.h`, which takes `VertexPosNormUV` + indices and returns 4 floats/vertex).

## 5. What the architect must decide

1. **Which container UzPainter targets**: UZMH 48 B (tangents stored, used by every runtime path) vs UZMS (submesh/LOD tables, 64 B alignment, skinned). **Recommendation:** write UZMH for static assets unless skinning is required. UZMS is not usable for static meshes until the 32→48 B conversion defect in §1 is fixed (explicit supported layouts, stride/count validation, real attribute and tangent expansion); treat that as a correctness prerequisite, not a small change.
2. **Tangent basis parity**: UzPainter must bake with the same normals and tangents the engine renders with. Cooked FBX/glTF = MikkTSpace (the glTF cook then discards them, §1); `uzmesh.exe` = Lengyel. The FBX cook also replaces authored normals by default (§3.2), so a bake from the authored normals would not match the cooked mesh unless `normalMode` = 0 (Import) is set. **Recommendation:** standardise on MikkTSpace and regenerate tangents in UzPainter with the vendored `mikktspace.c`, then write them into the 48 B `Vertex`.
3. **UV sets**: only UV0 exists. UDIM tiles can be addressed with a single UV stream extending beyond [0,1] (tile routing, storage and sampling are still missing); multiple UV sets are a separate requirement that needs the planned multi-UV vertex layout (see `09-gaps-and-risks.md`).
4. **Auto-unwrap**: xatlas is already wrapped (`GenerateLightmapUVs`) and can produce a UV layout for meshes that arrive without UVs.
