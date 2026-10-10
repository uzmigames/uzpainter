# 04 — Substance 3D Painter export (as of 2026-10-10)

How Painter 12.1.0 exports textures and meshes from Python: the JSON export configuration, presets (output templates) and their channel packing, formats and bit depths, padding/dilation, size overrides, UDIM naming, events and mesh export. Input for the UzPainter architect; it documents Substance, it does not decide what UzPainter replicates.

## Conventions

- `PAINTER` = `C:\Program Files\Adobe\Adobe Substance 3D Painter`; `PYDOC` = `PAINTER\resources\python-doc`; `PYSRC` = `PAINTER\resources\python\modules\substance_painter`; `MODS` = `PAINTER\resources\python\modules`; `PRESETS` = `PAINTER\resources\starter_assets\export-presets`; `MCP` = `E:\UzmiGames\Assets3D\Tools\SubstancePainterMCP`.
- Labels: **Fact**, **Hypothesis**, **Recommendation**; "not confirmed" marks gaps.
- Main source: the "Full json_config dict possibilities" block and examples in `PYDOC\substance_painter\export.html` (= docstrings of `PYSRC\export.py`).

## 1. Entry points

| Symbol | Behaviour | Label | Source |
|---|---|---|---|
| `export.list_project_textures(json_config) -> {(texture_set, stack): [paths]}` | Dry run: files that would be written | Fact | `PYDOC\substance_painter\export.html` |
| `export.export_project_textures(json_config) -> TextureExportResult(status, message, textures)` | Writes files. Status is never `Error` — failures raise (`ProjectError`, `ValueError` with a readable message); a user cancel returns `Cancelled` plus the files already written | Fact | same |
| `ExportStatus` | `Success`, `Cancelled`, `Warning`, `Error` | Fact | `PYSRC\export.py` |
| Events | `event.ExportTexturesAboutToStart(textures)`, `event.ExportTexturesEnded(status, message, textures)` (also fired for UI-initiated exports; the event receives `Error` on failure) | Fact | `export.html` → "Events" |
| `export.get_default_export_path()` | Application default export path (not project-specific) | Fact | `export.html` |
| `export.list_predefined_export_presets() -> [PredefinedExportPreset(name, url)]` | Presets embedded in the application: "dynamic list of maps exported depending on the project", may have pre/post processes "that generates custom data (e.g. glTF)", not editable; `list_output_maps(stack)` needs an open project | Fact | `export.html` (`PredefinedExportPreset`) |
| `export.list_resource_export_presets() -> [ResourceExportPreset(resource_id)]` | Shelf presets (resource `Type.EXPORT`), user-editable; `list_output_maps()` returns the `maps` list in JSON-config format | Fact | `export.html` (`ResourceExportPreset`) |
| Mesh export | `export.export_mesh(file_path, MeshExportOption) -> MeshExportResult(status, message)`; helpers `scene_is_triangulated()`, `scene_has_tessellation()` — see §9 | Fact | `export.html` → "Export Mesh" |

## 2. JSON configuration

| Key | Type | Meaning | Label | Source |
|---|---|---|---|---|
| `exportPath` | str | Root output folder | Fact | `export.html` |
| `exportShaderParams` | bool | "Whether to export shader instances to a JSON file" | Fact | same |
| `defaultExportPreset` | str | Name of a preset in `exportPresets`, or a preset URL (`resource://starter_assets/PBR Metallic Roughness…` or a predefined preset URL) | Fact | same |
| `exportPresets` | list | Inline presets `{name, maps: [...]}` | Fact | same |
| `exportPresets[].maps[].fileName` | str | Output file name with wildcards (§5); may contain `/` sub-folders | Fact | same; folder use in `PRESETS\PBR Metallic Roughness (folders or PSD groups).spexp`, `KeyShot 9+.spexp` |
| `exportPresets[].maps[].channels[]` | list | `{destChannel, srcChannel, srcMapType, srcMapName}`; Adobe's own configs also pass `srcPath: ''` | Fact (keys); `srcPath` semantics not documented | `export.html`; `MODS\automated_tests\test_export_fileformats_bitdepth.py` |
| `destChannel` / `srcChannel` | `L`, `R`, `G`, `B`, `A` | "In addition to alpha channel, either R+G+B must be specified, or either L only"; `L` read from a color map "will generate a mix of R+G+B" | Fact | `export.html` |
| `srcMapType` | `documentMap`, `meshMap`, `virtualMap`, `defaultMap` | channel of the document, baked mesh map, generated (converted) map, constant | Fact | same |
| `srcMapName` (documentMap) | `basecolor, height, specular, opacity, emissive, displacement, glossiness, roughness, anisotropylevel, anisotropyangle, transmissive, scattering, reflection, ior, metallic, normal, ambientOcclusion, diffuse, specularlevel, blendingmask, user0`…`user7` | doc list (does not mention OpenPBR names or `user8`–`user31`) | Fact (list); OpenPBR naming in export not confirmed | same |
| `srcMapName` (meshMap) | str | `ambient_occlusion, id, curvature, normal_base, world_space_normals, position, thickness` (doc list); Adobe's "Mesh Maps" preset additionally outputs bent normals, height and opacity ([Redacted under the clean-room policy (docs/licensing-and-clean-room.md). Source withheld: PAINTER\resources\python\modules\engine_tests\test_baking.py.]) | Fact | `export.html`; `MODS\engine_tests\test_baking.py` |
| `srcMapName` (virtualMap) | str | `Normal_OpenGL, Normal_DirectX, AO_Mixed, Diffuse, Specular, Glossiness, Unity4Diff, Unity4Gloss, reflection, 1/ior, Glossiness2, f0, View_2D` | Fact | `export.html` |
| `srcMapName` (defaultMap) | str | `black`, `white` | Fact | same |
| `exportPresets[].maps[].parameters` | dict | Per-map defaults: `fileFormat`, `bitDepth`, `dithering`, `sizeLog2`, `paddingAlgorithm`, `dilationDistance` | Fact | same |
| `exportList[]` | list | `{rootPath, filter?, exportPreset?}`; `rootPath` = Texture Set name, or `TextureSet/Stack` for layered materials | Fact | same |
| `exportList[].filter` | dict | `outputMaps` (file-name patterns incl. wildcards), `uvTiles` (`[[u, v], …]`) | Fact | same |
| `exportParameters[]` | list | Ordered override rules `{filter?, parameters?}`; `filter` keys `dataPaths`, `outputMaps`, `uvTiles`; `{}` matches all, `{"dataPaths": []}` matches nothing | Fact | same |
| Undocumented keys and stored exporter values | — | [Redacted under the clean-room policy (docs/licensing-and-clean-room.md). Source withheld: PAINTER\resources\python\modules\automated_tests\; PAINTER\resources\python\modules\engine_tests\; PAINTER\resources\python\modules\automated_tests\resources\layerstack-cube.spp; PAINTER\resources\starter_assets\templates\*.spt.] A project created from the `Unreal Engine` template is expected to default to the `Unreal Engine (Packed)` export preset. | Hypothesis (to confirm in the export window) | — |

### 2.1 Parameter resolution rules

| Rule | Label | Source |
|---|---|---|
| Each texture's parameters start from the preset map's `parameters`, then every `exportParameters` rule whose filter matches overrides the parameters it defines, in list order. | Fact | `export.html` (comments on `exportParameters`) |
| After all rules, every parameter of every file must be defined, otherwise the configuration is invalid; Adobe advises a global rule with defaults. | Fact | same |
| `sizeLog2`: int = largest side, aspect ratio kept (10 → a 2048×4096 map exports as 512×1024); `[w, h]` ignores the aspect ratio; absent = project/Texture Set size. | Fact | same |
| `paddingAlgorithm`: `passthrough`, `color`, `transparent`, `diffusion`, `infinite`; `dilationDistance` (pixels) is needed for `transparent`, `color`, `diffusion`. | Fact | same |
| `bitDepth` must be supported by `fileFormat`. | Fact | same |

## 3. File formats and bit depths

`bitDepth` must be supported by `fileFormat`, and float depths are named `16f`/`32f` (**Fact**, `export.html`; changelog below). [Redacted under the clean-room policy (docs/licensing-and-clean-room.md). Source withheld: PAINTER\resources\python\modules\automated_tests\test_export_fileformats_bitdepth.py.] The supported format / bit-depth / dithering combinations are **not confirmed**; take them from Painter's export window and Adobe's public export documentation and confirm by export (§11).

API 0.2.10 fixed EXR `32f` being saved as `16f` (**Fact**, changelog in `PYDOC\index.html`). `sbsar` export is not confirmed. The MCP bridge only accepts `png, tga, jpg, jpeg, tif, tiff, exr, bmp` and bit depths `8, 16, 32` (**Fact**, `MCP\src\substance_painter_mcp\operations.py` → `plan_texture_export`).

## 4. Built-in presets

### 4.1 Shelf presets (`.spexp`, editable)

34 files in `PRESETS` (**Fact**, listing): Amazon Lumberyard; Arnold (AiStandard); Arnold UDIM Legacy (AiStandard); Blender (Principled BSDF); Corona; CryEngine; Dota 2; KeyShot 9+; KeyShot; Lens Studio; Maxwell (Metallic Roughness); Maxwell (Specular Glossiness); Mesh Maps; Non-PBR Specular Glossiness; PBR Metallic Roughness (folders or PSD groups); PBR Metallic Roughness; PBR Specular Glossiness (converted from Metallic Roughness); PBR Specular Glossiness; Redshift (rsMaterial); Renderman (pxrDisney); Renderman (pxrSurface); Roblox (MaterialVariant); Roblox (SurfaceAppearance); Shade 3D; Spark AR Studio; Unity HD Render Pipeline (Metallic Standard); Unity HD Render Pipeline (Specular); Unity Universal Render Pipeline (Metallic Standard); Unity Universal Render Pipeline (Specular); Unreal Engine (Packed); Unreal Engine SSS (Packed); Vray Next (Metallic Roughness); Vray Next (Specular Glossiness); Vray Next UDIM Legacy (Metallic Roughness). Their resource URLs look like `resource://starter_assets/<name>?version=<number>.spexp` (**Fact**, strings in shipped templates/samples). Adobe's descriptions of each preset: https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/export/output-templates/default-output-templates/default-presets (**Fact**; the page has no channel detail).

### 4.2 Predefined presets (embedded, not editable)

| Adobe name | Generator URL found in the executable | Label | Source |
|---|---|---|---|
| 2D View | `export-preset-generator://viewport2d` | pairing Hypothesis | names: Adobe "Predefined Output templates" https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/export/output-templates/default-output-templates/predefined-presets ; URLs: strings in `PAINTER\Adobe Substance 3D Painter.exe` |
| Document channels + Normal + AO (No Alpha) | `export-preset-generator://doc-channel-normal-no-alpha` ([Redacted under the clean-room policy (docs/licensing-and-clean-room.md). Source withheld: PAINTER\resources\python\modules\automated_tests\resources\layerstack-cube.spp; PAINTER\resources\python\modules\engine_tests\test_usd_openpbr_roundtrip.py.]) | pairing Hypothesis | same |
| Document channels + Normal + AO (With Alpha) | `export-preset-generator://doc-channel-normal-with-alpha` | pairing Hypothesis | same |
| Sketchfab | `export-preset-generator://sketchfab` | pairing Hypothesis | same |
| Substance 3D Stager | `export-preset-generator://adobe-standard-material` | pairing Hypothesis | same |
| USDz (Apple AR) | `export-preset-generator://usd` | pairing Hypothesis | same |
| glTF PBR Metal Roughness | `export-preset-generator://gltf` | pairing Hypothesis | same |
| glTF PBR Metal Roughness + Displacement texture (experimental) | `export-preset-generator://gltf-displacement` | pairing Hypothesis | same |

glTF preset composition: the executable contains, next to the glTF exporter messages ("An error occurred while exporting glTF file", "…GLB file"), the suffixes `_baseColor`, `_normal`, `_occlusionRoughnessMetallic`, `_emissive`, `_displacement` and the strings `KHR_materials_displacement`, `_opacity_alpha_threshold`, `_double_sided`, `metallicRoughnessTexture` (**Fact**, strings in `PAINTER\Adobe Substance 3D Painter.exe`). The per-channel packing of `_occlusionRoughnessMetallic` is **not confirmed** (predefined presets are generated at run time and not stored as files). Validate with `PredefinedExportPreset.list_output_maps(stack)` on an open project.

## 5. File-name wildcards and UDIM naming

| Token | Meaning | Label | Source |
|---|---|---|---|
| `$colorSpace` | current color space | Fact | `export.html` |
| `$mesh` | file name of the imported mesh | Fact | same |
| `$project` | project name | Fact | same |
| `$sceneMaterial` | material name in the imported mesh | Fact | same |
| `$textureSet` | Texture Set name | Fact | same |
| `$udim` | current UV tile, e.g. `1001` | Fact | same |
| `$uvTileName` | UV-tile name | Fact | same |
| `( … )` groups | Shipped presets wrap optional parts: `$mesh_$textureSet_BaseColor(_$colorSpace)(.$udim)` | Fact (pattern); "dropped when the token is empty" Hypothesis | `PRESETS\*.spexp` |
| Legacy UDIM naming | `Arnold UDIM Legacy` / `Vray Next UDIM Legacy` use `$mesh_BaseColor(_$colorSpace).$textureSet` (Texture Set name as the tile suffix in the TextureSetPerUVTile workflow) | Fact (pattern); intent Hypothesis | `PRESETS\Arnold UDIM Legacy (AiStandard).spexp`, `Vray Next UDIM Legacy (Metallic Roughness).spexp` |
| Tile filter | `exportList[].filter.uvTiles` / `exportParameters[].filter.uvTiles` = `[[u, v], …]` | Fact | `export.html` |

## 6. Converted (virtual) maps

| Virtual map | Adobe definition | Label |
|---|---|---|
| Normal OpenGL / Normal DirectX | baked normal combined with the Texture Set normal channel, in OpenGL / DirectX convention | Fact |
| Mixed AO (`AO_Mixed`) | baked ambient occlusion combined with the ambient-occlusion channel | Fact |
| Diffuse | from Base Color and Metallic (metallic areas black) | Fact |
| Specular | from Base Color and Metallic | Fact |
| Glossiness | inverse of roughness | Fact |
| Glossiness2 | glossiness squared | Fact |
| Unity4 Diffuse / Unity4 Gloss | deprecated, Unity 4 shaders | Fact |
| Reflection | white = dielectric, other colors = metallic | Fact |
| 1/ior | 1 divided by IOR (1.4 dielectrics, 100 metals) | Fact |
| f0 | reflectance at 0° (0.04 dielectric, 1.0 metallic) | Fact |
| View_2D | 2D-view map (used in Adobe's example of a custom map) | Fact (name); content Hypothesis |

Source: Adobe "Output templates", https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/export/export-window/output-templates ; names from `export.html`.

## 7. Channel packing of the requested presets

### 7.1 How the packing was obtained

`.spexp` files are binary (file signature `DD 2F 7C 1B`), not JSON (**Fact**, `xxd` of `PRESETS\Unreal Engine (Packed).spexp`). [Redacted under the clean-room policy (docs/licensing-and-clean-room.md). Source withheld: PAINTER\resources\starter_assets\export-presets\*.spexp.] The tables in §7.2–7.6 state the resulting output layouts as behaviour — which file each preset writes and which channel feeds its R, G, B and A — and are **Hypothesis** until confirmed through the documented `list_output_maps()` calls (§11). The shelf presets write PNG files.

**Recommendation**: confirm this table once inside Painter with `ResourceExportPreset.list_output_maps()` for each preset (it returns the documented JSON form) before relying on it.

Labels for §7.2–7.6 and the Appendix (**Hypothesis**): the channel names are an interpretation of decoded preset data ([Redacted under the clean-room policy (docs/licensing-and-clean-room.md). Source withheld: PRESETS\Unreal Engine (Packed).spexp; PRESETS\Unreal Engine SSS (Packed).spexp.]). Agreement of record boundaries validates the field layout only; it does not establish colour conversion, normal/AO derivation, alpha handling, quantization, padding or file naming — see §11.

### 7.2 PBR Metallic Roughness

| Output file | R | G | B | A | Notes |
|---|---|---|---|---|---|
| `$mesh_$textureSet_BaseColor(_$colorSpace)(.$udim)` | basecolor.R | basecolor.G | basecolor.B | opacity (L) | |
| `$mesh_$textureSet_Roughness(_$colorSpace)(.$udim)` | roughness (single L channel) | | | | grayscale file |
| `$mesh_$textureSet_Metallic(_$colorSpace)(.$udim)` | metallic (L) | | | | grayscale file |
| `$mesh_$textureSet_Normal(_$colorSpace)(.$udim)` | Normal_DirectX.R | Normal_DirectX.G | Normal_DirectX.B | — | bit depth may differ from the other maps (not confirmed, §11; [Redacted under the clean-room policy (docs/licensing-and-clean-room.md). Source withheld: PRESETS\PBR Metallic Roughness.spexp.]) |
| `$mesh_$textureSet_Height(_$colorSpace)(.$udim)` | height (L) | | | | bit depth may differ from the other maps (not confirmed, §11) |
| `$mesh_$textureSet_Emissive(_$colorSpace)(.$udim)` | emissive.R | emissive.G | emissive.B | — | |

### 7.3 Unreal Engine (Packed) — "Unreal Engine 4 (Packed)" / ORM

| Output file | R | G | B | A | Notes |
|---|---|---|---|---|---|
| `$mesh_$textureSet_BaseColor(_$colorSpace)(.$udim)` | basecolor.R | basecolor.G | basecolor.B | opacity (L) | |
| `$mesh_$textureSet_OcclusionRoughnessMetallic(_$colorSpace)(.$udim)` | **Mixed AO** (`AO_Mixed`, L) | **roughness** (L) | **metallic** (L) | — | the ORM texture |
| `$mesh_$textureSet_Normal(_$colorSpace)(.$udim)` | Normal_DirectX.R | Normal_DirectX.G | Normal_DirectX.B | — | dithering on |
| `$mesh_$textureSet_Emissive(_$colorSpace)(.$udim)` | emissive.R | emissive.G | emissive.B | — | |

`Unreal Engine SSS (Packed)` is identical except that BaseColor alpha carries scattering instead of opacity (**Hypothesis**; matches Adobe's description "replacing opacity map with subsurface scattering"; [Redacted under the clean-room policy (docs/licensing-and-clean-room.md). Source withheld: PRESETS\Unreal Engine SSS (Packed).spexp.]). The shipped preset is named "Unreal Engine (Packed)" (no "4") in 12.1.0 (**Fact**, `PRESETS`).

### 7.4 Unity

| Preset | Output file | R | G | B | A |
|---|---|---|---|---|---|
| Unity HD Render Pipeline (Metallic Standard) | `…_BaseMap…` | basecolor.R | basecolor.G | basecolor.B | opacity |
| | `…_MaskMap…` | metallic | Mixed AO | (empty) | Glossiness ("inverse of roughness"; `1 − roughness` is a Hypothesis) |
| | `…_Normal…` | Normal_OpenGL.R | Normal_OpenGL.G | Normal_OpenGL.B | — (dithering on) |
| | `…_Emissive…` | emissive.R | emissive.G | emissive.B | — |
| Unity Universal Render Pipeline (Metallic Standard) | `…_AlbedoTransparency…` | basecolor.R | basecolor.G | basecolor.B | opacity |
| | `…_MetallicSmoothness…` | metallic | metallic | metallic | Glossiness |
| | `…_Normal…` | Normal_OpenGL.R | Normal_OpenGL.G | Normal_OpenGL.B | — (dithering on) |
| | `…_Emission…` | emissive.R | emissive.G | emissive.B | — |

The specular variants are in the appendix.

### 7.5 glTF PBR Metal Roughness

Predefined (embedded) preset; output suffixes `_baseColor`, `_normal`, `_occlusionRoughnessMetallic`, `_emissive` (+ `_displacement` for the displacement variant) are present in the executable (**Fact**); exact packing **not confirmed** (see §4.2).

### 7.6 Mesh Maps

| Output file | Composition |
|---|---|
| `$textureSet_normal_base(_$colorSpace)(.$udim)` | RGB ← mesh normal_base RGB |
| `$textureSet_world_space_normals(...)` | RGB ← mesh world_space_normals RGB |
| `$textureSet_id(...)` | RGB ← mesh id RGB |
| `$textureSet_position(...)` | RGB ← mesh position RGB |
| `$textureSet_bent_normals_base(...)` | RGB ← mesh bent_normals RGB |
| `$textureSet_ambient_occlusion(...)` | L ← mesh ambient_occlusion |
| `$textureSet_curvature(...)` | L ← mesh curvature |
| `$textureSet_thickness(...)` | L ← mesh thickness |
| `$textureSet_height_base(...)` | L ← mesh height |
| `$textureSet_opacity_base(...)` | L ← mesh opacity |

Per-map bit depth of this preset: [Redacted under the clean-room policy (docs/licensing-and-clean-room.md). Source withheld: PRESETS\Mesh Maps.spexp.] Confirm by export (§11).

[Redacted under the clean-room policy (docs/licensing-and-clean-room.md). Source withheld: PAINTER\resources\python\modules\engine_tests\test_baking.py.] Whether `list_output_maps()` returns a grayscale map as a single `L` channel or as `L` copied to `R`, `G` and `B` is **not confirmed** (first §11 check); the grayscale/RGB form of a written file matters for output comparison.

## 8. Padding, dithering, size defaults in practice

| Statement | Label | Source |
|---|---|---|
| Adobe's examples use `{"dithering": True, "paddingAlgorithm": "infinite"}` as global parameters and `sizeLog2` overrides per Texture Set. | Fact | `export.html` example |
| Export defaults of a new 12.1 project are not confirmed (§11). [Redacted under the clean-room policy (docs/licensing-and-clean-room.md). Source withheld: PAINTER\resources\python\modules\automated_tests\resources\layerstack-cube.spp.] | not confirmed | — |
| The MCP bridge always sends `dithering: True`, `paddingAlgorithm: "infinite"`, plus optional scalar `sizeLog2` (5–14; no `[w, h]` pair), `fileFormat`, `bitDepth` (`8`, `16` or `32` only: Adobe's test names float depths `16f`/`32f`, which the bridge rejects; whether Painter accepts `32` is not confirmed); it never sends per-root `exportPreset`, inline presets, `dilationDistance`, UV-tile filters or per-map rules. | Fact | `MCP\src\substance_painter_mcp\operations.py` → `plan_texture_export` |

## 9. Mesh export

| Item | Behaviour | Label | Source |
|---|---|---|---|
| Call | `export_mesh(file_path, option)`; format from the extension: `.usd`, `.obj`, `.fbx`, `.dae`, `.ply`, `.gltf` | Fact | `export.html` |
| `MeshExportOption` | `BaseMesh` (no displacement/tessellation), `TriangulatedMesh` (triangulate polygons with >3 sides; only if the mesh has them), `TessellationNormalsBaseMesh` (with displacement/tessellation; only if used by the shader), `TessellationRecomputeNormals` (same, recompute vertex normals) | Fact | `PYSRC\export.py` |
| Result | `MeshExportResult(status, message)`; raises `ProjectError`/`ValueError` on invalid input | Fact | `export.html` |
| Combined export | glTF/GLB export with textures through the predefined glTF preset; USD export route: [Redacted under the clean-room policy (docs/licensing-and-clean-room.md). Source withheld: PAINTER\resources\python\modules\engine_tests\test_usd_openpbr_roundtrip.py.] | glTF Fact (strings); full behaviour not confirmed | §4.2 |

## 10. Other export paths

| Path | Status | Label | Source |
|---|---|---|---|
| Export one layer/effect node's texture | no public equivalent; [Redacted under the clean-room policy (docs/licensing-and-clean-room.md). Source withheld: PAINTER\resources\python\modules\engine_tests\test_export_layerstack_nodes.py.] | Fact (absence in the public API) | `PYDOC\substance_painter\export.html` |
| Export with dependency list | no public equivalent; [Redacted under the clean-room policy (docs/licensing-and-clean-room.md). Source withheld: PAINTER\resources\python\modules\automated_tests\test_export_texture_deps.py.] | Fact (absence in the public API) | `PYDOC\substance_painter\export.html` |
| JS map export | `alg.mapexport.save`, `saveChannelMap`, `saveMeshMap`, `saveConvertedMap`, `exportDocumentMaps`, `getPathsExportDocumentMaps`, `channelIdentifiers`, `meshMapIdentifiers`, `convertedMapIdentifiers` (reachable via `js.evaluate`) | Fact | `PAINTER\resources\javascript-doc\alg.mapexport.html` |

## 11. Validation needed inside Painter (not run)

Each line states what a run inside Painter 12.1 must observe before the current label can be raised to **Fact**. **Recommendation**: record the inputs (project, mesh, Texture Set sizes, colour configuration, preset version) with each capture.

| Item | Current label | What an in-Painter run must confirm |
|---|---|---|
| Shelf preset packing (§7, Appendix) | Hypothesis (decoded) | `ResourceExportPreset.list_output_maps()` for each `.spexp` returns the documented JSON form; compare destination, `srcMapType`, `srcMapName`, `srcChannel` with the decoded tables. |
| Predefined presets (glTF, Document channels + Normal + AO, USDz, …) | not confirmed | `PredefinedExportPreset.list_output_maps(stack)` per preset on an open project, including the `_occlusionRoughnessMetallic` packing. |
| Bit depth written by each shelf preset | not confirmed | export each preset's maps without a `bitDepth` override and read the written files' bit depth. |
| Export defaults of a new project (dilation distance, padding algorithm, default preset) | not confirmed | create a new project from each template and read the defaults in the export window or from an export without overrides; [Redacted under the clean-room policy (docs/licensing-and-clean-room.md). Source withheld: PAINTER\resources\python\modules\automated_tests\resources\layerstack-cube.spp.] |
| Virtual-map formulas (`Normal_OpenGL`/`Normal_DirectX`, `AO_Mixed`, `Glossiness`, `Glossiness2`, `Diffuse`, `Specular`, `reflection`, `1/ior`, `f0`) | Adobe prose; exact formulas not confirmed | export from a fixture with known uniform channel values and known baked maps, then compare texel values with candidate formulas. |
| Dithering | not observed | export an 8-bit gradient with `dithering` True and False and compare; check whether True is accepted at 16-bit and float depths. |
| `sizeLog2` scalar versus `[w, h]`; padding algorithms and `dilationDistance` | Fact (docs); output not observed | export a non-square Texture Set with both forms; export with each `paddingAlgorithm` and compare texels outside the UV islands. |
| Optional `( … )` file-name groups; `$colorSpace`, `$udim`, `$uvTileName` | pattern Fact; behaviour Hypothesis | `list_project_textures` with and without UV tiles and colour management; compare the names. |
| Undocumented export keys | [Redacted under the clean-room policy (docs/licensing-and-clean-room.md). Source withheld: PAINTER\resources\python\modules\automated_tests\; PAINTER\resources\python\modules\engine_tests\.] | — |
| MCP `bitDepth` `"32"` | not confirmed | `list_project_textures` / export with `"32"` and with `"32f"` for `exr`, `tiff`, `hdr`. |

## Appendix — composition of the shipped `.spexp` presets

[Redacted under the clean-room policy (docs/licensing-and-clean-room.md). Source withheld: PAINTER\resources\starter_assets\export-presets\*.spexp.] The output layouts needed by the current pipeline are stated as behaviour in §7.2–7.6 and below. The layout of any other preset is to be captured from Painter through the documented `ResourceExportPreset.list_output_maps()` (§11) or taken from Adobe's public output-template descriptions, never from the preset files.

- **Blender (Principled BSDF)** — used by the Assets3D pipeline (`docs/analysis/assets3d-pipeline/05-export-and-consumers.md` §1): one file per map, named `$textureSet_<Map>(_$colorSpace)(.$udim)`: `BaseColor` (base colour RGB), `Normal` (OpenGL normal RGB), `Metallic`, `Roughness`, `Alpha` (opacity) and `Displacement` (height) as one grey value written to R, G and B, and `Emission` (emissive RGB). **Hypothesis** until confirmed by export.
