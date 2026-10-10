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
| `srcMapName` (meshMap) | str | `ambient_occlusion, id, curvature, normal_base, world_space_normals, position, thickness` (doc list); Adobe's "Mesh Maps" preset additionally outputs bent normals, height and opacity (`bent_normals`, `height`, `opacity` in Adobe's test map) | Fact | `export.html`; `MODS\engine_tests\test_baking.py` |
| `srcMapName` (virtualMap) | str | `Normal_OpenGL, Normal_DirectX, AO_Mixed, Diffuse, Specular, Glossiness, Unity4Diff, Unity4Gloss, reflection, 1/ior, Glossiness2, f0, View_2D` | Fact | `export.html` |
| `srcMapName` (defaultMap) | str | `black`, `white` | Fact | same |
| `exportPresets[].maps[].parameters` | dict | Per-map defaults: `fileFormat`, `bitDepth`, `dithering`, `sizeLog2`, `paddingAlgorithm`, `dilationDistance` | Fact | same |
| `exportList[]` | list | `{rootPath, filter?, exportPreset?}`; `rootPath` = Texture Set name, or `TextureSet/Stack` for layered materials | Fact | same |
| `exportList[].filter` | dict | `outputMaps` (file-name patterns incl. wildcards), `uvTiles` (`[[u, v], …]`) | Fact | same |
| `exportParameters[]` | list | Ordered override rules `{filter?, parameters?}`; `filter` keys `dataPaths`, `outputMaps`, `uvTiles`; `{}` matches all, `{"dataPaths": []}` matches nothing | Fact | same |
| `exportMeshTessellation` | bool | Present in Adobe configs and in project-stored exporter settings; not documented | Fact (presence); meaning Hypothesis (export tessellated mesh with textures) | `MODS\automated_tests\test_export_texture_deps.py`; `engine_tests\test_usd_openpbr_roundtrip.py`; strings of `exporterv2.json` in `MODS\automated_tests\resources\layerstack-cube.spp` |
| `exportUSD` | bool | Not documented; Adobe's round-trip test sets it to `True` and then looks for `<project>.usd` / `<project>.sbspt.usd` (skipping `*.geo.usd`) in the export folder | Fact (test behaviour); full semantics not confirmed | `MODS\engine_tests\test_usd_openpbr_roundtrip.py` |
| `keepAlpha` (parameter) | bool | Used by Adobe's per-node export test; not documented | Fact (presence) | `MODS\engine_tests\test_export_layerstack_nodes.py` |
| Stored project defaults | — | Projects store an exporter config (`exporterv2.json`, `"version": 3`) e.g. `"defaultExportPreset": "export-preset-generator://doc-channel-normal-no-alpha"`, `"dilationDistance": 16`, `"paddingAlgorithm": "infinite"`, `"exportShaderParams": false`, `"exportUSD": false`, `"exportMeshTessellation": false` | Fact (strings) | `MODS\automated_tests\resources\layerstack-cube.spp`; templates in `PAINTER\resources\starter_assets\templates\*.spt` store their own `defaultExportPreset` (e.g. `Unreal Engine.spt` → `resource://starter_assets/Unreal Engine (Packed)?version=8339356058946582545.spexp`) |

### 2.1 Parameter resolution rules

| Rule | Label | Source |
|---|---|---|
| Each texture's parameters start from the preset map's `parameters`, then every `exportParameters` rule whose filter matches overrides the parameters it defines, in list order. | Fact | `export.html` (comments on `exportParameters`) |
| After all rules, every parameter of every file must be defined, otherwise the configuration is invalid; Adobe advises a global rule with defaults. | Fact | same |
| `sizeLog2`: int = largest side, aspect ratio kept (10 → a 2048×4096 map exports as 512×1024); `[w, h]` ignores the aspect ratio; absent = project/Texture Set size. | Fact | same |
| `paddingAlgorithm`: `passthrough`, `color`, `transparent`, `diffusion`, `infinite`; `dilationDistance` (pixels) is needed for `transparent`, `color`, `diffusion`. | Fact | same |
| `bitDepth` must be supported by `fileFormat`. | Fact | same |

## 3. File formats and bit depths

Adobe's export test enumerates these combinations (all expected to succeed) — **Fact**, `MODS\automated_tests\test_export_fileformats_bitdepth.py` (`parameters` list):

| `fileFormat` | `bitDepth` values tested | Dithering tested |
|---|---|---|
| `png` | `8`, `16` | yes |
| `tga` | `8` | yes |
| `bmp` | `8` | yes |
| `jpeg` | `8` | yes |
| `jng` | `8` | yes |
| `webp` | `8` | yes |
| `pgm` | `16` | yes |
| `j2k` | `8`, `16` | yes |
| `jp2` | `8`, `16` | yes |
| `psd` | `8`, `16` | yes (exported into a sub-folder in the test) |
| `tiff` | `8`, `16`, `32f` | yes |
| `exr` | `16f`, `32f` | yes |
| `hdr` | `32f` | yes |

API 0.2.10 fixed EXR `32f` being saved as `16f` (**Fact**, changelog in `PYDOC\index.html`). The test code also special-cases a `sbsar` format folder, but no `sbsar` row is in its parameter list (**Fact**; `sbsar` export not confirmed). The MCP bridge only accepts `png, tga, jpg, jpeg, tif, tiff, exr, bmp` and bit depths `8, 16, 32` (**Fact**, `MCP\src\substance_painter_mcp\operations.py` → `plan_texture_export`).

## 4. Built-in presets

### 4.1 Shelf presets (`.spexp`, editable)

34 files in `PRESETS` (**Fact**, listing): Amazon Lumberyard; Arnold (AiStandard); Arnold UDIM Legacy (AiStandard); Blender (Principled BSDF); Corona; CryEngine; Dota 2; KeyShot 9+; KeyShot; Lens Studio; Maxwell (Metallic Roughness); Maxwell (Specular Glossiness); Mesh Maps; Non-PBR Specular Glossiness; PBR Metallic Roughness (folders or PSD groups); PBR Metallic Roughness; PBR Specular Glossiness (converted from Metallic Roughness); PBR Specular Glossiness; Redshift (rsMaterial); Renderman (pxrDisney); Renderman (pxrSurface); Roblox (MaterialVariant); Roblox (SurfaceAppearance); Shade 3D; Spark AR Studio; Unity HD Render Pipeline (Metallic Standard); Unity HD Render Pipeline (Specular); Unity Universal Render Pipeline (Metallic Standard); Unity Universal Render Pipeline (Specular); Unreal Engine (Packed); Unreal Engine SSS (Packed); Vray Next (Metallic Roughness); Vray Next (Specular Glossiness); Vray Next UDIM Legacy (Metallic Roughness). Their resource URLs look like `resource://starter_assets/<name>?version=<number>.spexp` (**Fact**, strings in shipped templates/samples). Adobe's descriptions of each preset: https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/export/output-templates/default-output-templates/default-presets (**Fact**; the page has no channel detail).

### 4.2 Predefined presets (embedded, not editable)

| Adobe name | Generator URL found in the executable | Label | Source |
|---|---|---|---|
| 2D View | `export-preset-generator://viewport2d` | pairing Hypothesis | names: Adobe "Predefined Output templates" https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/export/output-templates/default-output-templates/predefined-presets ; URLs: strings in `PAINTER\Adobe Substance 3D Painter.exe` |
| Document channels + Normal + AO (No Alpha) | `export-preset-generator://doc-channel-normal-no-alpha` (also the default stored in projects; Adobe test uses the name verbatim) | Fact (default string, test name); pairing Hypothesis | same; `MODS\engine_tests\test_usd_openpbr_roundtrip.py` |
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

`.spexp` files are binary (magic `DD 2F 7C 1B`), not JSON (**Fact**, `xxd` of `PRESETS\Unreal Engine (Packed).spexp`). They embed their own schema: type `DataExportPreset {maps, uid}`, `DataExportMap {bitdepth, channels, dithering, fileformat, path, uid}`, `DataExportChannel {channelSrc, mapId, mapIdType}` (**Fact**, readable type and field names in every file). A throw-away reader was written this session (kept only in the session scratchpad, not in the repository); its layout, enough to re-implement it, is: per map it reads `bitdepth` (int32), the channel list, `dithering` (1 byte), `fileformat` and `path` (length-prefixed strings) and `uid`; each channel is `channelSrc` (int32), `mapId` (Qt-serialized variant: string for virtual maps, unsigned int otherwise) and `mapIdType` (int32). Every map record of all 34 files ended exactly at the byte offset stored in its header, which validates the field layout (**Fact**, computed). The meaning of the decoded numbers is inferred (**Hypothesis**):

| Decoded value | Interpretation | Evidence |
|---|---|---|
| Position of a channel record | destination: 1 record = `L`; 3 = `R,G,B`; 4 = `R,G,B,A` | matches the JSON rule "R+G+B or L only, plus alpha"; the 4th record of every 4-record map is a grayscale or opacity/glossiness source (e.g. Unity HDRP `MaskMap` decodes to metallic, AO, empty, glossiness; CryEngine `ddna` to normal RGB + glossiness) |
| `channelSrc` | 0=R, 1=G, 2=B, 3=A, 4=L | grayscale sources always use 4; normal maps use 0/1/2 (3 for alpha in Arnold) |
| `mapIdType` | 0=empty, 1=documentMap, 2=virtualMap, 3=meshMap | virtual maps carry their string names (`Normal_DirectX`, `AO_Mixed`, `Glossiness`…); "Mesh Maps" preset uses only type 3 |
| documentMap ids | 0=basecolor, 1=height, 2=specular, 3=opacity, 4=emissive, 6=glossiness, 7=roughness, 8=anisotropylevel, 9=anisotropyangle, 10=transmissive, 13=metallic, 24=diffuse, 25=specularlevel, 27=scattering, 64–67=user0–user3 | consistent with the output file names across all 34 presets (e.g. every "Metallic"/"Metalness" file uses 13; Unreal SSS replaces the opacity id 3 by 27 in BaseColor alpha, matching Adobe's description "replacing opacity map with subsurface scattering") |
| meshMap ids | 0=id, 1=ambient_occlusion, 2=curvature, 3=world_space_normals, 4=position, 5=thickness, 6=normal_base, 7=height, 8=bent_normals, 9=opacity | from the "Mesh Maps" file names |
| `bitdepth` field | 0 or 1; normals/height maps mostly 1 | meaning (e.g. 8-bit vs 16-bit) not confirmed |
| `fileformat` | `png` in every shipped preset | Fact (plain string) |

**Recommendation**: confirm this table once inside Painter with `ResourceExportPreset.list_output_maps()` for each preset (it returns the documented JSON form) before relying on it.

### 7.2 PBR Metallic Roughness

| Output file | R | G | B | A | Notes |
|---|---|---|---|---|---|
| `$mesh_$textureSet_BaseColor(_$colorSpace)(.$udim)` | basecolor.R | basecolor.G | basecolor.B | opacity (L) | |
| `$mesh_$textureSet_Roughness(_$colorSpace)(.$udim)` | roughness (single L channel) | | | | grayscale file |
| `$mesh_$textureSet_Metallic(_$colorSpace)(.$udim)` | metallic (L) | | | | grayscale file |
| `$mesh_$textureSet_Normal(_$colorSpace)(.$udim)` | Normal_DirectX.R | Normal_DirectX.G | Normal_DirectX.B | — | bitdepth flag 1 |
| `$mesh_$textureSet_Height(_$colorSpace)(.$udim)` | height (L) | | | | bitdepth flag 1 |
| `$mesh_$textureSet_Emissive(_$colorSpace)(.$udim)` | emissive.R | emissive.G | emissive.B | — | |

### 7.3 Unreal Engine (Packed) — "Unreal Engine 4 (Packed)" / ORM

| Output file | R | G | B | A | Notes |
|---|---|---|---|---|---|
| `$mesh_$textureSet_BaseColor(_$colorSpace)(.$udim)` | basecolor.R | basecolor.G | basecolor.B | opacity (L) | |
| `$mesh_$textureSet_OcclusionRoughnessMetallic(_$colorSpace)(.$udim)` | **Mixed AO** (`AO_Mixed`, L) | **roughness** (L) | **metallic** (L) | — | the ORM texture |
| `$mesh_$textureSet_Normal(_$colorSpace)(.$udim)` | Normal_DirectX.R | Normal_DirectX.G | Normal_DirectX.B | — | dithering on |
| `$mesh_$textureSet_Emissive(_$colorSpace)(.$udim)` | emissive.R | emissive.G | emissive.B | — | |

`Unreal Engine SSS (Packed)` is identical except BaseColor alpha = document id 27 (scattering, **Hypothesis**). The shipped preset is named "Unreal Engine (Packed)" (no "4") in 12.1.0 (**Fact**, `PRESETS`).

### 7.4 Unity

| Preset | Output file | R | G | B | A |
|---|---|---|---|---|---|
| Unity HD Render Pipeline (Metallic Standard) | `…_BaseMap…` | basecolor.R | basecolor.G | basecolor.B | opacity |
| | `…_MaskMap…` | metallic | Mixed AO | (empty) | Glossiness (= 1 − roughness) |
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

| Output file | Composition | bitdepth flag |
|---|---|---|
| `$textureSet_normal_base(_$colorSpace)(.$udim)` | RGB ← mesh normal_base RGB | 1 |
| `$textureSet_world_space_normals(...)` | RGB ← mesh world_space_normals RGB | 1 |
| `$textureSet_id(...)` | RGB ← mesh id RGB | 1 |
| `$textureSet_position(...)` | RGB ← mesh position RGB | 1 |
| `$textureSet_bent_normals_base(...)` | RGB ← mesh bent_normals RGB | 1 |
| `$textureSet_ambient_occlusion(...)` | L ← mesh ambient_occlusion | 0 |
| `$textureSet_curvature(...)` | L ← mesh curvature | 0 |
| `$textureSet_thickness(...)` | L ← mesh thickness | 0 |
| `$textureSet_height_base(...)` | L ← mesh height | 0 |
| `$textureSet_opacity_base(...)` | L ← mesh opacity | 0 |

Adobe's baking test exports this preset per Texture Set with `fileFormat: bmp`, `bitDepth: 8`, `dithering: False`, `paddingAlgorithm: passthrough`, filtering `outputMaps` to the slots that hold a mesh map (**Fact**, `MODS\engine_tests\test_baking.py` → `_export_mesh_maps`).

## 8. Padding, dithering, size defaults in practice

| Statement | Label | Source |
|---|---|---|
| Adobe's examples use `{"dithering": True, "paddingAlgorithm": "infinite"}` as global parameters and `sizeLog2` overrides per Texture Set. | Fact | `export.html` example |
| Projects store `dilationDistance: 16`, `paddingAlgorithm: "infinite"` as exporter defaults. | Fact (strings) | `MODS\automated_tests\resources\layerstack-cube.spp` |
| The MCP bridge always sends `dithering: True`, `paddingAlgorithm: "infinite"`, plus optional `sizeLog2` (5–14), `fileFormat`, `bitDepth`; it never sends inline presets, `dilationDistance`, UV-tile filters or per-map rules. | Fact | `MCP\src\substance_painter_mcp\operations.py` → `plan_texture_export` |

## 9. Mesh export

| Item | Behaviour | Label | Source |
|---|---|---|---|
| Call | `export_mesh(file_path, option)`; format from the extension: `.usd`, `.obj`, `.fbx`, `.dae`, `.ply`, `.gltf` | Fact | `export.html` |
| `MeshExportOption` | `BaseMesh` (no displacement/tessellation), `TriangulatedMesh` (triangulate polygons with >3 sides; only if the mesh has them), `TessellationNormalsBaseMesh` (with displacement/tessellation; only if used by the shader), `TessellationRecomputeNormals` (same, recompute vertex normals) | Fact | `PYSRC\export.py` |
| Result | `MeshExportResult(status, message)`; raises `ProjectError`/`ValueError` on invalid input | Fact | `export.html` |
| Combined export | glTF/GLB export with textures through the predefined glTF preset; USD through `exportUSD: true` | Fact (strings/test); full behaviour not confirmed | §4.2; §2 |

## 10. Other export paths

| Path | Status | Label | Source |
|---|---|---|---|
| Export one layer/effect node's texture | private `_substance_painter.export.export_stack_node_texture(node_uid, channel, path, json_params)` used by Adobe tests; no public equivalent | Fact | `MODS\engine_tests\test_export_layerstack_nodes.py` |
| Export with dependency list | private `_substance_painter.export.export_project_textures_with_deps(json)` (test currently skipped by Adobe because of a cycle bug) | Fact | `MODS\automated_tests\test_export_texture_deps.py` |
| JS map export | `alg.mapexport.save`, `saveChannelMap`, `saveMeshMap`, `saveConvertedMap`, `exportDocumentMaps`, `getPathsExportDocumentMaps`, `channelIdentifiers`, `meshMapIdentifiers`, `convertedMapIdentifiers` (reachable via `js.evaluate`) | Fact | `PAINTER\resources\javascript-doc\alg.mapexport.html` |

## Appendix — decoded composition of all 34 shipped `.spexp` presets

Decoded with the reader described in §7.1; destination/source naming follows the **Hypothesis** table of §7.1 (`doc:` = documentMap, `virtual:` = virtualMap, `mesh:` = meshMap; suffix = source channel). Source files: `PRESETS\<name>.spexp`.

| Preset (`.spexp`) | Output file name pattern | Composition (destination ← source) | fmt | bitdepth flag | dithering |
|---|---|---|---|---|---|
| Amazon Lumberyard | `$mesh_$textureSet_diff(_$colorSpace)(.$udim)` | R←doc:diffuse.R, G←doc:diffuse.G, B←doc:diffuse.B, A←doc:opacity.L | png | 0 | off |
| Amazon Lumberyard | `$mesh_$textureSet_spec(_$colorSpace)(.$udim)` | R←doc:specular.R, G←doc:specular.G, B←doc:specular.B | png | 0 | off |
| Amazon Lumberyard | `$mesh_$textureSet_ddna(_$colorSpace)(.$udim)` | R←virtual:Normal_DirectX.R, G←virtual:Normal_DirectX.G, B←virtual:Normal_DirectX.B, A←doc:glossiness.L | png | 0 | on |
| Arnold (AiStandard) | `$mesh_$textureSet_BaseColor(_$colorSpace)(.$udim)` | R←doc:basecolor.R, G←doc:basecolor.G, B←doc:basecolor.B | png | 0 | off |
| Arnold (AiStandard) | `$mesh_$textureSet_Metalness(_$colorSpace)(.$udim)` | L←doc:metallic.L | png | 0 | off |
| Arnold (AiStandard) | `$mesh_$textureSet_Roughness(_$colorSpace)(.$udim)` | L←doc:roughness.L | png | 0 | off |
| Arnold (AiStandard) | `$mesh_$textureSet_Normal(_$colorSpace)(.$udim)` | R←virtual:Normal_OpenGL.R, G←virtual:Normal_OpenGL.G, B←virtual:Normal_OpenGL.B, A←virtual:Normal_OpenGL.A | png | 1 | off |
| Arnold (AiStandard) | `$mesh_$textureSet_Height(_$colorSpace)(.$udim)` | L←doc:height.L | png | 1 | off |
| Arnold (AiStandard) | `$mesh_$textureSet_Emissive(_$colorSpace)(.$udim)` | R←doc:emissive.R, G←doc:emissive.G, B←doc:emissive.B, A←doc:emissive.A | png | 0 | off |
| Arnold UDIM Legacy (AiStandard) | `$mesh_BaseColor(_$colorSpace).$textureSet` | R←doc:basecolor.R, G←doc:basecolor.G, B←doc:basecolor.B | png | 0 | off |
| Arnold UDIM Legacy (AiStandard) | `$mesh_Metalness(_$colorSpace).$textureSet` | L←doc:metallic.L | png | 0 | off |
| Arnold UDIM Legacy (AiStandard) | `$mesh_Roughness(_$colorSpace).$textureSet` | L←doc:roughness.L | png | 0 | off |
| Arnold UDIM Legacy (AiStandard) | `$mesh_Normal(_$colorSpace).$textureSet` | R←virtual:Normal_OpenGL.R, G←virtual:Normal_OpenGL.G, B←virtual:Normal_OpenGL.B, A←virtual:Normal_OpenGL.A | png | 1 | off |
| Arnold UDIM Legacy (AiStandard) | `$mesh_Height(_$colorSpace).$textureSet` | L←doc:height.L | png | 1 | off |
| Arnold UDIM Legacy (AiStandard) | `$mesh_Emissive(_$colorSpace).$textureSet` | R←doc:emissive.R, G←doc:emissive.G, B←doc:emissive.B, A←doc:emissive.A | png | 0 | off |
| Blender (Principled BSDF) | `$textureSet_BaseColor(_$colorSpace)(.$udim)` | R←doc:basecolor.R, G←doc:basecolor.G, B←doc:basecolor.B | png | 0 | off |
| Blender (Principled BSDF) | `$textureSet_Normal(_$colorSpace)(.$udim)` | R←virtual:Normal_OpenGL.R, G←virtual:Normal_OpenGL.G, B←virtual:Normal_OpenGL.B | png | 1 | off |
| Blender (Principled BSDF) | `$textureSet_Metallic(_$colorSpace)(.$udim)` | R←doc:metallic.L, G←doc:metallic.L, B←doc:metallic.L | png | 0 | off |
| Blender (Principled BSDF) | `$textureSet_Roughness(_$colorSpace)(.$udim)` | R←doc:roughness.L, G←doc:roughness.L, B←doc:roughness.L | png | 0 | off |
| Blender (Principled BSDF) | `$textureSet_Emission(_$colorSpace)(.$udim)` | R←doc:emissive.R, G←doc:emissive.G, B←doc:emissive.B | png | 0 | off |
| Blender (Principled BSDF) | `$textureSet_Alpha(_$colorSpace)(.$udim)` | R←doc:opacity.L, G←doc:opacity.L, B←doc:opacity.L | png | 0 | off |
| Blender (Principled BSDF) | `$textureSet_Displacement(_$colorSpace)(.$udim)` | R←doc:height.L, G←doc:height.L, B←doc:height.L | png | 0 | off |
| Corona | `$mesh_$textureSet_Diffuse(_$colorSpace)(.$udim)` | R←virtual:Diffuse.R, G←virtual:Diffuse.G, B←virtual:Diffuse.B | png | 0 | off |
| Corona | `$mesh_$textureSet_Reflection(_$colorSpace)(.$udim)` | R←virtual:reflection.R, G←virtual:reflection.G, B←virtual:reflection.B | png | 0 | off |
| Corona | `$mesh_$textureSet_Glossiness(_$colorSpace)(.$udim)` | L←virtual:Glossiness2.L | png | 0 | off |
| Corona | `$mesh_$textureSet_IOR(_$colorSpace)(.$udim)` | L←virtual:1/ior.L | png | 1 | off |
| Corona | `$mesh_$textureSet_Normal(_$colorSpace)(.$udim)` | R←virtual:Normal_DirectX.R, G←virtual:Normal_DirectX.G, B←virtual:Normal_DirectX.B, A←virtual:Normal_DirectX.A | png | 1 | off |
| Corona | `$mesh_$textureSet_Height(_$colorSpace)(.$udim)` | L←doc:height.L | png | 1 | off |
| Corona | `$mesh_$textureSet_Emissive(_$colorSpace)(.$udim)` | R←doc:emissive.R, G←doc:emissive.G, B←doc:emissive.B, A←doc:emissive.A | png | 0 | off |
| CryEngine | `$mesh_$textureSet_diff(_$colorSpace)(.$udim)` | R←doc:diffuse.R, G←doc:diffuse.G, B←doc:diffuse.B, A←doc:opacity.L | png | 0 | off |
| CryEngine | `$mesh_$textureSet_spec(_$colorSpace)(.$udim)` | R←doc:specular.R, G←doc:specular.G, B←doc:specular.B | png | 0 | off |
| CryEngine | `$mesh_$textureSet_ddna(_$colorSpace)(.$udim)` | R←virtual:Normal_DirectX.R, G←virtual:Normal_DirectX.G, B←virtual:Normal_DirectX.B, A←doc:glossiness.L | png | 0 | on |
| Dota 2 | `$mesh_$textureSet_color(_$colorSpace)(.$udim)` | R←doc:basecolor.R, G←doc:basecolor.G, B←doc:basecolor.B | png | 0 | off |
| Dota 2 | `$mesh_$textureSet_transparency(_$colorSpace)(.$udim)` | L←doc:opacity.L | png | 0 | off |
| Dota 2 | `$mesh_$textureSet_normal(_$colorSpace)(.$udim)` | R←virtual:Normal_DirectX.R, G←virtual:Normal_DirectX.G, B←virtual:Normal_DirectX.B | png | 0 | on |
| Dota 2 | `$mesh_$textureSet_detailmask(_$colorSpace)(.$udim)` | L←doc:user0.L | png | 0 | off |
| Dota 2 | `$mesh_$textureSet_diffusemask(_$colorSpace)(.$udim)` | L←doc:user1.L | png | 0 | off |
| Dota 2 | `$mesh_$textureSet_metalnessmask(_$colorSpace)(.$udim)` | L←doc:metallic.L | png | 0 | off |
| Dota 2 | `$mesh_$textureSet_selfillummask(_$colorSpace)(.$udim)` | L←doc:emissive.L | png | 0 | off |
| Dota 2 | `$mesh_$textureSet_specmask(_$colorSpace)(.$udim)` | L←doc:specular.L | png | 0 | off |
| Dota 2 | `$mesh_$textureSet_rimmask(_$colorSpace)(.$udim)` | L←doc:user2.L | png | 0 | off |
| Dota 2 | `$mesh_$textureSet_basetintmask(_$colorSpace)(.$udim)` | L←doc:user3.L | png | 0 | off |
| Dota 2 | `$mesh_$textureSet_specexp(_$colorSpace)(.$udim)` | L←doc:glossiness.L | png | 0 | off |
| KeyShot 9+ | `$project.sp/$textureSet.ts/base_color(_$colorSpace)(.$udim)` | R←doc:basecolor.R, G←doc:basecolor.G, B←doc:basecolor.B | png | 0 | off |
| KeyShot 9+ | `$project.sp/$textureSet.ts/metallic(_$colorSpace)(.$udim)` | L←doc:metallic.L | png | 0 | off |
| KeyShot 9+ | `$project.sp/$textureSet.ts/roughness(_$colorSpace)(.$udim)` | L←doc:roughness.L | png | 0 | off |
| KeyShot 9+ | `$project.sp/$textureSet.ts/specular(_$colorSpace)(.$udim)` | L←doc:specularlevel.L | png | 0 | off |
| KeyShot 9+ | `$project.sp/$textureSet.ts/anisotropic(_$colorSpace)(.$udim)` | L←doc:anisotropylevel.L | png | 0 | off |
| KeyShot 9+ | `$project.sp/$textureSet.ts/anisotropic_angle(_$colorSpace)(.$udim)` | L←doc:anisotropyangle.L | png | 1 | off |
| KeyShot 9+ | `$project.sp/$textureSet.ts/normal(_$colorSpace)(.$udim)` | R←virtual:Normal_OpenGL.R, G←virtual:Normal_OpenGL.G, B←virtual:Normal_OpenGL.B | png | 1 | off |
| KeyShot 9+ | `$project.sp/$textureSet.ts/opacity(_$colorSpace)(.$udim)` | L←doc:opacity.L | png | 0 | off |
| KeyShot 9+ | `$project.sp/$textureSet.ts/height(_$colorSpace)(.$udim)` | L←doc:height.L | png | 1 | off |
| KeyShot 9+ | `$project.sp/$textureSet.ts/emissive(_$colorSpace)(.$udim)` | R←doc:emissive.R, G←doc:emissive.G, B←doc:emissive.B | png | 0 | off |
| KeyShot | `$mesh_$textureSet_Diffuse(_$colorSpace)(.$udim)` | R←virtual:Diffuse.R, G←virtual:Diffuse.G, B←virtual:Diffuse.B | png | 0 | off |
| KeyShot | `$mesh_$textureSet_Normal(_$colorSpace)(.$udim)` | R←virtual:Normal_DirectX.R, G←virtual:Normal_DirectX.G, B←virtual:Normal_DirectX.B | png | 1 | off |
| KeyShot | `$mesh_$textureSet_Reflection(_$colorSpace)(.$udim)` | R←virtual:reflection.R, G←virtual:reflection.G, B←virtual:reflection.B | png | 0 | off |
| KeyShot | `$mesh_$textureSet_Roughness(_$colorSpace)(.$udim)` | L←doc:roughness.L | png | 0 | off |
| KeyShot | `$mesh_$textureSet_Metallic(_$colorSpace)(.$udim)` | L←doc:metallic.L | png | 0 | off |
| Lens Studio | `$mesh_$textureSet_base(_$colorSpace)(.$udim)` | R←doc:basecolor.R, G←doc:basecolor.G, B←doc:basecolor.B, A←doc:opacity.L | png | 0 | off |
| Lens Studio | `$mesh_$textureSet_normal(_$colorSpace)(.$udim)` | R←virtual:Normal_OpenGL.R, G←virtual:Normal_OpenGL.G, B←virtual:Normal_OpenGL.B | png | 0 | on |
| Lens Studio | `$mesh_$textureSet_materialParams(_$colorSpace)(.$udim)` | R←doc:metallic.L, G←doc:roughness.L, B←virtual:AO_Mixed.L | png | 0 | off |
| Maxwell (Metallic Roughness) | `$mesh_$textureSet_BaseColor(_$colorSpace)(.$udim)` | R←doc:basecolor.R, G←doc:basecolor.G, B←doc:basecolor.B | png | 0 | off |
| Maxwell (Metallic Roughness) | `$mesh_$textureSet_Roughness(_$colorSpace)(.$udim)` | L←doc:roughness.L | png | 0 | off |
| Maxwell (Metallic Roughness) | `$mesh_$textureSet_Metallic(_$colorSpace)(.$udim)` | L←doc:metallic.L | png | 0 | off |
| Maxwell (Metallic Roughness) | `$mesh_$textureSet_Normal(_$colorSpace)(.$udim)` | R←virtual:Normal_OpenGL.R, G←virtual:Normal_OpenGL.G, B←virtual:Normal_OpenGL.B | png | 1 | off |
| Maxwell (Metallic Roughness) | `$mesh_$textureSet_Height(_$colorSpace)(.$udim)` | L←doc:height.L | png | 1 | off |
| Maxwell (Metallic Roughness) | `$mesh_$textureSet_AnisoLevel(_$colorSpace)(.$udim)` | L←doc:anisotropylevel.L | png | 0 | off |
| Maxwell (Metallic Roughness) | `$mesh_$textureSet_AnisoAngle(_$colorSpace)(.$udim)` | L←doc:anisotropyangle.L | png | 1 | off |
| Maxwell (Metallic Roughness) | `$mesh_$textureSet_AO(_$colorSpace)(.$udim)` | L←virtual:AO_Mixed.L | png | 0 | off |
| Maxwell (Metallic Roughness) | `$mesh_$textureSet_Opacity(_$colorSpace)(.$udim)` | L←doc:opacity.L | png | 0 | off |
| Maxwell (Metallic Roughness) | `$mesh_$textureSet_SSS(_$colorSpace)(.$udim)` | L←doc:scattering.L | png | 0 | off |
| Maxwell (Metallic Roughness) | `$mesh_$textureSet_Emission(_$colorSpace)(.$udim)` | R←doc:emissive.R, G←doc:emissive.G, B←doc:emissive.B | png | 0 | off |
| Maxwell (Specular Glossiness) | `$mesh_$textureSet_Diffuse(_$colorSpace)(.$udim)` | R←doc:diffuse.R, G←doc:diffuse.G, B←doc:diffuse.B | png | 0 | off |
| Maxwell (Specular Glossiness) | `$mesh_$textureSet_Specular(_$colorSpace)(.$udim)` | R←doc:specular.R, G←doc:specular.G, B←doc:specular.B | png | 0 | off |
| Maxwell (Specular Glossiness) | `$mesh_$textureSet_Glossiness(_$colorSpace)(.$udim)` | L←doc:glossiness.L | png | 0 | off |
| Maxwell (Specular Glossiness) | `$mesh_$textureSet_Normal(_$colorSpace)(.$udim)` | R←virtual:Normal_OpenGL.R, G←virtual:Normal_OpenGL.G, B←virtual:Normal_OpenGL.B | png | 1 | off |
| Maxwell (Specular Glossiness) | `$mesh_$textureSet_Height(_$colorSpace)(.$udim)` | L←doc:height.L | png | 1 | off |
| Maxwell (Specular Glossiness) | `$mesh_$textureSet_AnisoLevel(_$colorSpace)(.$udim)` | L←doc:anisotropylevel.L | png | 0 | off |
| Maxwell (Specular Glossiness) | `$mesh_$textureSet_AnisoAngle(_$colorSpace)(.$udim)` | L←doc:anisotropyangle.L | png | 1 | off |
| Maxwell (Specular Glossiness) | `$mesh_$textureSet_AO(_$colorSpace)(.$udim)` | L←virtual:AO_Mixed.L | png | 0 | off |
| Maxwell (Specular Glossiness) | `$mesh_$textureSet_Opacity(_$colorSpace)(.$udim)` | L←doc:opacity.L | png | 0 | off |
| Maxwell (Specular Glossiness) | `$mesh_$textureSet_SSS(_$colorSpace)(.$udim)` | L←doc:scattering.L | png | 0 | off |
| Maxwell (Specular Glossiness) | `$mesh_$textureSet_Emission(_$colorSpace)(.$udim)` | R←doc:emissive.R, G←doc:emissive.G, B←doc:emissive.B | png | 0 | off |
| Mesh Maps | `$textureSet_normal_base(_$colorSpace)(.$udim)` | R←mesh:normal_base.R, G←mesh:normal_base.G, B←mesh:normal_base.B | png | 1 | off |
| Mesh Maps | `$textureSet_world_space_normals(_$colorSpace)(.$udim)` | R←mesh:world_space_normals.R, G←mesh:world_space_normals.G, B←mesh:world_space_normals.B | png | 1 | off |
| Mesh Maps | `$textureSet_id(_$colorSpace)(.$udim)` | R←mesh:id.R, G←mesh:id.G, B←mesh:id.B | png | 1 | off |
| Mesh Maps | `$textureSet_position(_$colorSpace)(.$udim)` | R←mesh:position.R, G←mesh:position.G, B←mesh:position.B | png | 1 | off |
| Mesh Maps | `$textureSet_bent_normals_base(_$colorSpace)(.$udim)` | R←mesh:bent_normals.R, G←mesh:bent_normals.G, B←mesh:bent_normals.B | png | 1 | off |
| Mesh Maps | `$textureSet_ambient_occlusion(_$colorSpace)(.$udim)` | L←mesh:ambient_occlusion.L | png | 0 | off |
| Mesh Maps | `$textureSet_curvature(_$colorSpace)(.$udim)` | L←mesh:curvature.L | png | 0 | off |
| Mesh Maps | `$textureSet_thickness(_$colorSpace)(.$udim)` | L←mesh:thickness.L | png | 0 | off |
| Mesh Maps | `$textureSet_height_base(_$colorSpace)(.$udim)` | L←mesh:height.L | png | 0 | off |
| Mesh Maps | `$textureSet_opacity_base(_$colorSpace)(.$udim)` | L←mesh:opacity.L | png | 0 | off |
| Non-PBR Specular Glossiness | `$mesh_$textureSet_Diffuse(_$colorSpace)(.$udim)` | R←doc:diffuse.R, G←doc:diffuse.G, B←doc:diffuse.B, A←doc:opacity.L | png | 0 | off |
| Non-PBR Specular Glossiness | `$mesh_$textureSet_Normal(_$colorSpace)(.$udim)` | R←virtual:Normal_DirectX.R, G←virtual:Normal_DirectX.G, B←virtual:Normal_DirectX.B | png | 0 | on |
| Non-PBR Specular Glossiness | `$mesh_$textureSet_SpecularGlossiness(_$colorSpace)(.$udim)` | R←doc:specular.R, G←doc:specular.G, B←doc:specular.B, A←doc:glossiness.L | png | 0 | off |
| Non-PBR Specular Glossiness | `$mesh_$textureSet_Emissive(_$colorSpace)(.$udim)` | R←doc:emissive.R, G←doc:emissive.G, B←doc:emissive.B | png | 0 | off |
| PBR Metallic Roughness (folders or PSD groups) | `BaseColor/$textureSet_BaseColor(_$colorSpace)(.$udim)` | R←doc:basecolor.R, G←doc:basecolor.G, B←doc:basecolor.B | png | 0 | off |
| PBR Metallic Roughness (folders or PSD groups) | `Roughness/$textureSet_Roughness(_$colorSpace)(.$udim)` | R←doc:roughness.L, G←doc:roughness.L, B←doc:roughness.L | png | 0 | off |
| PBR Metallic Roughness (folders or PSD groups) | `Metallic/$textureSet_Metallic(_$colorSpace)(.$udim)` | R←doc:metallic.L, G←doc:metallic.L, B←doc:metallic.L | png | 0 | off |
| PBR Metallic Roughness (folders or PSD groups) | `Normal/$textureSet_Normal(_$colorSpace)(.$udim)` | R←virtual:Normal_DirectX.R, G←virtual:Normal_DirectX.G, B←virtual:Normal_DirectX.B | png | 1 | off |
| PBR Metallic Roughness (folders or PSD groups) | `Height/$textureSet_Height(_$colorSpace)(_$colorSpace)(_$colorSpace)(_$colorSpace)(.$udim)` | R←doc:height.L, G←doc:height.L, B←doc:height.L | png | 1 | off |
| PBR Metallic Roughness (folders or PSD groups) | `Emissive/$textureSet_Emissive(_$colorSpace)(.$udim)` | R←doc:emissive.R, G←doc:emissive.G, B←doc:emissive.B | png | 0 | off |
| PBR Metallic Roughness | `$mesh_$textureSet_BaseColor(_$colorSpace)(.$udim)` | R←doc:basecolor.R, G←doc:basecolor.G, B←doc:basecolor.B, A←doc:opacity.L | png | 0 | off |
| PBR Metallic Roughness | `$mesh_$textureSet_Roughness(_$colorSpace)(.$udim)` | L←doc:roughness.L | png | 0 | off |
| PBR Metallic Roughness | `$mesh_$textureSet_Metallic(_$colorSpace)(.$udim)` | L←doc:metallic.L | png | 0 | off |
| PBR Metallic Roughness | `$mesh_$textureSet_Normal(_$colorSpace)(.$udim)` | R←virtual:Normal_DirectX.R, G←virtual:Normal_DirectX.G, B←virtual:Normal_DirectX.B | png | 1 | off |
| PBR Metallic Roughness | `$mesh_$textureSet_Height(_$colorSpace)(.$udim)` | L←doc:height.L | png | 1 | off |
| PBR Metallic Roughness | `$mesh_$textureSet_Emissive(_$colorSpace)(.$udim)` | R←doc:emissive.R, G←doc:emissive.G, B←doc:emissive.B | png | 0 | off |
| PBR Specular Glossiness (converted from Metallic Roughness) | `$mesh_$textureSet_Diffuse(_$colorSpace)(.$udim)` | R←virtual:Diffuse.R, G←virtual:Diffuse.G, B←virtual:Diffuse.B, A←doc:opacity.L | png | 0 | off |
| PBR Specular Glossiness (converted from Metallic Roughness) | `$mesh_$textureSet_Specular(_$colorSpace)(.$udim)` | R←virtual:Specular.R, G←virtual:Specular.G, B←virtual:Specular.B | png | 0 | off |
| PBR Specular Glossiness (converted from Metallic Roughness) | `$mesh_$textureSet_Glossiness(_$colorSpace)(.$udim)` | L←virtual:Glossiness.L | png | 0 | off |
| PBR Specular Glossiness (converted from Metallic Roughness) | `$mesh_$textureSet_Normal(_$colorSpace)(.$udim)` | R←virtual:Normal_DirectX.R, G←virtual:Normal_DirectX.G, B←virtual:Normal_DirectX.B | png | 1 | off |
| PBR Specular Glossiness (converted from Metallic Roughness) | `$mesh_$textureSet_Height(_$colorSpace)(.$udim)` | L←doc:height.L | png | 1 | off |
| PBR Specular Glossiness (converted from Metallic Roughness) | `$mesh_$textureSet_Emissive(_$colorSpace)(.$udim)` | R←doc:emissive.R, G←doc:emissive.G, B←doc:emissive.B | png | 0 | off |
| PBR Specular Glossiness | `$mesh_$textureSet_Diffuse(_$colorSpace)(.$udim)` | R←doc:diffuse.R, G←doc:diffuse.G, B←doc:diffuse.B, A←doc:opacity.L | png | 0 | off |
| PBR Specular Glossiness | `$mesh_$textureSet_Specular(_$colorSpace)(.$udim)` | R←doc:specular.R, G←doc:specular.G, B←doc:specular.B | png | 0 | off |
| PBR Specular Glossiness | `$mesh_$textureSet_Glossiness(_$colorSpace)(.$udim)` | L←doc:glossiness.L | png | 0 | off |
| PBR Specular Glossiness | `$mesh_$textureSet_Normal(_$colorSpace)(.$udim)` | R←virtual:Normal_DirectX.R, G←virtual:Normal_DirectX.G, B←virtual:Normal_DirectX.B | png | 1 | off |
| PBR Specular Glossiness | `$mesh_$textureSet_Height(_$colorSpace)(.$udim)` | L←doc:height.L | png | 1 | off |
| PBR Specular Glossiness | `$mesh_$textureSet_Emissive(_$colorSpace)(.$udim)` | R←doc:emissive.R, G←doc:emissive.G, B←doc:emissive.B | png | 0 | off |
| Redshift (rsMaterial) | `$mesh_$textureSet_Color(_$colorSpace)(.$udim)` | R←doc:basecolor.R, G←doc:basecolor.G, B←doc:basecolor.B, A←doc:opacity.L | png | 0 | off |
| Redshift (rsMaterial) | `$mesh_$textureSet_Roughness(_$colorSpace)(.$udim)` | L←doc:roughness.L | png | 0 | off |
| Redshift (rsMaterial) | `$mesh_$textureSet_Metalness(_$colorSpace)(.$udim)` | L←doc:metallic.L | png | 0 | off |
| Redshift (rsMaterial) | `$mesh_$textureSet_Normal(_$colorSpace)(.$udim)` | R←virtual:Normal_OpenGL.R, G←virtual:Normal_OpenGL.G, B←virtual:Normal_OpenGL.B | png | 1 | off |
| Redshift (rsMaterial) | `$mesh_$textureSet_DisplaceHeightField(_$colorSpace)(.$udim)` | L←doc:height.L | png | 1 | off |
| Redshift (rsMaterial) | `$mesh_$textureSet_EmissionColor(_$colorSpace)(.$udim)` | R←doc:emissive.R, G←doc:emissive.G, B←doc:emissive.B | png | 0 | off |
| Renderman (pxrDisney) | `$mesh_$textureSet_BaseColor(_$colorSpace)(.$udim)` | R←doc:basecolor.R, G←doc:basecolor.G, B←doc:basecolor.B | png | 0 | off |
| Renderman (pxrDisney) | `$mesh_$textureSet_Roughness(_$colorSpace)(.$udim)` | L←doc:roughness.L | png | 0 | off |
| Renderman (pxrDisney) | `$mesh_$textureSet_Metallic(_$colorSpace)(.$udim)` | L←doc:metallic.L | png | 0 | off |
| Renderman (pxrDisney) | `$mesh_$textureSet_Normal(_$colorSpace)(.$udim)` | R←virtual:Normal_OpenGL.R, G←virtual:Normal_OpenGL.G, B←virtual:Normal_OpenGL.B | png | 1 | off |
| Renderman (pxrDisney) | `$mesh_$textureSet_Displacement(_$colorSpace)(.$udim)` | L←doc:height.L | png | 1 | off |
| Renderman (pxrDisney) | `$mesh_$textureSet_Emissive(_$colorSpace)(.$udim)` | R←doc:emissive.R, G←doc:emissive.G, B←doc:emissive.B | png | 0 | off |
| Renderman (pxrDisney) | `$mesh_$textureSet_Presence(_$colorSpace)(.$udim)` | L←doc:opacity.L | png | 0 | off |
| Renderman (pxrSurface) | `$mesh_$textureSet_DiffuseColor(_$colorSpace)(.$udim)` | R←virtual:Diffuse.R, G←virtual:Diffuse.G, B←virtual:Diffuse.B | png | 0 | off |
| Renderman (pxrSurface) | `$mesh_$textureSet_SpecularFaceColor(_$colorSpace)(.$udim)` | R←virtual:Specular.R, G←virtual:Specular.G, B←virtual:Specular.B | png | 0 | off |
| Renderman (pxrSurface) | `$mesh_$textureSet_Normal(_$colorSpace)(.$udim)` | R←virtual:Normal_OpenGL.R, G←virtual:Normal_OpenGL.G, B←virtual:Normal_OpenGL.B | png | 1 | off |
| Renderman (pxrSurface) | `$mesh_$textureSet_SpecularRoughness(_$colorSpace)(.$udim)` | L←doc:roughness.L | png | 0 | off |
| Renderman (pxrSurface) | `$mesh_$textureSet_GlowColor(_$colorSpace)(.$udim)` | R←doc:emissive.R, G←doc:emissive.G, B←doc:emissive.B | png | 0 | off |
| Renderman (pxrSurface) | `$mesh_$textureSet_Presence(_$colorSpace)(.$udim)` | L←doc:opacity.L | png | 0 | off |
| Renderman (pxrSurface) | `$mesh_$textureSet_Displacement(_$colorSpace)(.$udim)` | L←doc:height.L | png | 1 | off |
| Roblox (MaterialVariant) | `$textureSet_ALB` | R←doc:basecolor.R, G←doc:basecolor.G, B←doc:basecolor.B | png | 0 | off |
| Roblox (MaterialVariant) | `$textureSet_NRM` | R←virtual:Normal_OpenGL.R, G←virtual:Normal_OpenGL.G, B←virtual:Normal_OpenGL.B | png | 1 | off |
| Roblox (MaterialVariant) | `$textureSet_MET` | R←doc:metallic.L, G←doc:metallic.L, B←doc:metallic.L | png | 0 | off |
| Roblox (MaterialVariant) | `$textureSet_RGH` | R←doc:roughness.L, G←doc:roughness.L, B←doc:roughness.L | png | 0 | off |
| Roblox (SurfaceAppearance) | `$textureSet_ColorMap` | R←doc:basecolor.R, G←doc:basecolor.G, B←doc:basecolor.B, A←doc:opacity.L | png | 0 | off |
| Roblox (SurfaceAppearance) | `$textureSet_NormalMap` | R←virtual:Normal_OpenGL.R, G←virtual:Normal_OpenGL.G, B←virtual:Normal_OpenGL.B | png | 1 | off |
| Roblox (SurfaceAppearance) | `$textureSet_MetalnessMap` | R←doc:metallic.L, G←doc:metallic.L, B←doc:metallic.L | png | 0 | off |
| Roblox (SurfaceAppearance) | `$textureSet_RoughnessMap` | R←doc:roughness.L, G←doc:roughness.L, B←doc:roughness.L | png | 0 | off |
| Shade 3D | `$project_$textureSet_Diffuse(_$colorSpace)(.$udim)` | R←virtual:Unity4Diff.R, G←virtual:Unity4Diff.G, B←virtual:Unity4Diff.B | png | 0 | off |
| Shade 3D | `$project_$textureSet_Normal(_$colorSpace)(.$udim)` | R←virtual:Normal_OpenGL.R, G←virtual:Normal_OpenGL.G, B←virtual:Normal_OpenGL.B | png | 1 | off |
| Shade 3D | `$project_$textureSet_Roughness(_$colorSpace)(.$udim)` | L←doc:roughness.L | png | 0 | off |
| Shade 3D | `$project_$textureSet_Specular(_$colorSpace)(.$udim)` | L←virtual:Specular.L | png | 0 | off |
| Spark AR Studio | `$textureSet_Color(_$colorSpace)(.$udim)` | R←doc:basecolor.R, G←doc:basecolor.G, B←doc:basecolor.B, A←doc:opacity.L | png | 0 | off |
| Spark AR Studio | `$textureSet_ORM(_$colorSpace)(.$udim)` | R←virtual:AO_Mixed.L, G←doc:roughness.L, B←doc:metallic.L | png | 0 | off |
| Spark AR Studio | `$textureSet_Emissive(_$colorSpace)(.$udim)` | R←doc:emissive.R, G←doc:emissive.G, B←doc:emissive.B | png | 0 | off |
| Spark AR Studio | `$textureSet_Normal(_$colorSpace)(.$udim)` | R←virtual:Normal_OpenGL.R, G←virtual:Normal_OpenGL.G, B←virtual:Normal_OpenGL.B | png | 0 | on |
| Unity HD Render Pipeline (Metallic Standard) | `$mesh_$textureSet_BaseMap(_$colorSpace)(.$udim)` | R←doc:basecolor.R, G←doc:basecolor.G, B←doc:basecolor.B, A←doc:opacity.L | png | 0 | off |
| Unity HD Render Pipeline (Metallic Standard) | `$mesh_$textureSet_MaskMap(_$colorSpace)(.$udim)` | R←doc:metallic.L, G←virtual:AO_Mixed.L, B←(empty), A←virtual:Glossiness.L | png | 0 | off |
| Unity HD Render Pipeline (Metallic Standard) | `$mesh_$textureSet_Normal(_$colorSpace)(.$udim)` | R←virtual:Normal_OpenGL.R, G←virtual:Normal_OpenGL.G, B←virtual:Normal_OpenGL.B | png | 0 | on |
| Unity HD Render Pipeline (Metallic Standard) | `$mesh_$textureSet_Emissive(_$colorSpace)(.$udim)` | R←doc:emissive.R, G←doc:emissive.G, B←doc:emissive.B | png | 0 | off |
| Unity HD Render Pipeline (Specular) | `$mesh_$textureSet_BaseMap(_$colorSpace)(.$udim)` | R←virtual:Diffuse.R, G←virtual:Diffuse.G, B←virtual:Diffuse.B, A←doc:opacity.L | png | 0 | off |
| Unity HD Render Pipeline (Specular) | `$mesh_$textureSet_Specular(_$colorSpace)(.$udim)` | R←virtual:Specular.R, G←virtual:Specular.G, B←virtual:Specular.B | png | 0 | off |
| Unity HD Render Pipeline (Specular) | `$mesh_$textureSet_MaskMap(_$colorSpace)(.$udim)` | R←doc:metallic.L, G←virtual:AO_Mixed.L, B←(empty), A←virtual:Glossiness.L | png | 0 | off |
| Unity HD Render Pipeline (Specular) | `$mesh_$textureSet_Normal(_$colorSpace)(.$udim)` | R←virtual:Normal_OpenGL.R, G←virtual:Normal_OpenGL.G, B←virtual:Normal_OpenGL.B | png | 0 | on |
| Unity HD Render Pipeline (Specular) | `$mesh_$textureSet_Emissive(_$colorSpace)(.$udim)` | R←doc:emissive.R, G←doc:emissive.G, B←doc:emissive.B | png | 0 | off |
| Unity Universal Render Pipeline (Metallic Standard) | `$mesh_$textureSet_AlbedoTransparency(_$colorSpace)(.$udim)` | R←doc:basecolor.R, G←doc:basecolor.G, B←doc:basecolor.B, A←doc:opacity.L | png | 0 | off |
| Unity Universal Render Pipeline (Metallic Standard) | `$mesh_$textureSet_MetallicSmoothness(_$colorSpace)(.$udim)` | R←doc:metallic.L, G←doc:metallic.L, B←doc:metallic.L, A←virtual:Glossiness.L | png | 0 | off |
| Unity Universal Render Pipeline (Metallic Standard) | `$mesh_$textureSet_Normal(_$colorSpace)(.$udim)` | R←virtual:Normal_OpenGL.R, G←virtual:Normal_OpenGL.G, B←virtual:Normal_OpenGL.B | png | 0 | on |
| Unity Universal Render Pipeline (Metallic Standard) | `$mesh_$textureSet_Emission(_$colorSpace)(.$udim)` | R←doc:emissive.R, G←doc:emissive.G, B←doc:emissive.B | png | 0 | off |
| Unity Universal Render Pipeline (Specular) | `$mesh_$textureSet_AlbedoTransparency(_$colorSpace)(.$udim)` | R←virtual:Diffuse.R, G←virtual:Diffuse.G, B←virtual:Diffuse.B, A←doc:opacity.L | png | 0 | off |
| Unity Universal Render Pipeline (Specular) | `$mesh_$textureSet_SpecularSmoothness(_$colorSpace)(.$udim)` | R←virtual:Specular.R, G←virtual:Specular.G, B←virtual:Specular.B, A←virtual:Glossiness.L | png | 0 | off |
| Unity Universal Render Pipeline (Specular) | `$mesh_$textureSet_Normal(_$colorSpace)(.$udim)` | R←virtual:Normal_OpenGL.R, G←virtual:Normal_OpenGL.G, B←virtual:Normal_OpenGL.B | png | 0 | on |
| Unity Universal Render Pipeline (Specular) | `$mesh_$textureSet_Emission(_$colorSpace)(.$udim)` | R←doc:emissive.R, G←doc:emissive.G, B←doc:emissive.B | png | 0 | off |
| Unreal Engine (Packed) | `$mesh_$textureSet_BaseColor(_$colorSpace)(.$udim)` | R←doc:basecolor.R, G←doc:basecolor.G, B←doc:basecolor.B, A←doc:opacity.L | png | 0 | off |
| Unreal Engine (Packed) | `$mesh_$textureSet_OcclusionRoughnessMetallic(_$colorSpace)(.$udim)` | R←virtual:AO_Mixed.L, G←doc:roughness.L, B←doc:metallic.L | png | 0 | off |
| Unreal Engine (Packed) | `$mesh_$textureSet_Normal(_$colorSpace)(.$udim)` | R←virtual:Normal_DirectX.R, G←virtual:Normal_DirectX.G, B←virtual:Normal_DirectX.B | png | 0 | on |
| Unreal Engine (Packed) | `$mesh_$textureSet_Emissive(_$colorSpace)(.$udim)` | R←doc:emissive.R, G←doc:emissive.G, B←doc:emissive.B | png | 0 | off |
| Unreal Engine SSS (Packed) | `$mesh_$textureSet_BaseColor(_$colorSpace)(.$udim)` | R←doc:basecolor.R, G←doc:basecolor.G, B←doc:basecolor.B, A←doc:scattering.L | png | 0 | off |
| Unreal Engine SSS (Packed) | `$mesh_$textureSet_OcclusionRoughnessMetallic(_$colorSpace)(.$udim)` | R←virtual:AO_Mixed.L, G←doc:roughness.L, B←doc:metallic.L | png | 0 | off |
| Unreal Engine SSS (Packed) | `$mesh_$textureSet_Normal(_$colorSpace)(.$udim)` | R←virtual:Normal_DirectX.R, G←virtual:Normal_DirectX.G, B←virtual:Normal_DirectX.B | png | 0 | on |
| Unreal Engine SSS (Packed) | `$mesh_$textureSet_Emissive(_$colorSpace)(.$udim)` | R←doc:emissive.R, G←doc:emissive.G, B←doc:emissive.B | png | 0 | off |
| Vray Next (Metallic Roughness) | `$mesh_$textureSet_BaseColor(_$colorSpace)(.$udim)` | R←doc:basecolor.R, G←doc:basecolor.G, B←doc:basecolor.B | png | 0 | off |
| Vray Next (Metallic Roughness) | `$mesh_$textureSet_Roughness(_$colorSpace)(.$udim)` | L←doc:roughness.L | png | 0 | off |
| Vray Next (Metallic Roughness) | `$mesh_$textureSet_Metallic(_$colorSpace)(.$udim)` | L←doc:metallic.L | png | 0 | off |
| Vray Next (Metallic Roughness) | `$mesh_$textureSet_Height(_$colorSpace)(.$udim)` | L←doc:height.L | png | 1 | off |
| Vray Next (Metallic Roughness) | `$mesh_$textureSet_Normal(_$colorSpace)(.$udim)` | R←virtual:Normal_OpenGL.R, G←virtual:Normal_OpenGL.G, B←virtual:Normal_OpenGL.B | png | 1 | off |
| Vray Next (Metallic Roughness) | `$mesh_$textureSet_Emissive(_$colorSpace)(.$udim)` | R←doc:emissive.R, G←doc:emissive.G, B←doc:emissive.B | png | 0 | off |
| Vray Next (Metallic Roughness) | `$mesh_$textureSet_Transmissive(_$colorSpace)(.$udim)` | R←doc:transmissive.R, G←doc:transmissive.G, B←doc:transmissive.B | png | 0 | off |
| Vray Next (Metallic Roughness) | `$mesh_$textureSet_AnisotropyAngle(_$colorSpace)(.$udim)` | L←doc:anisotropyangle.L | png | 1 | off |
| Vray Next (Metallic Roughness) | `$mesh_$textureSet_AnisotropyLevel(_$colorSpace)(.$udim)` | L←doc:anisotropylevel.L | png | 0 | off |
| Vray Next (Specular Glossiness) | `$mesh_$textureSet_Diffuse(_$colorSpace)(.$udim)` | R←doc:diffuse.R, G←doc:diffuse.G, B←doc:diffuse.B | png | 0 | off |
| Vray Next (Specular Glossiness) | `$mesh_$textureSet_Specular(_$colorSpace)(.$udim)` | R←doc:specular.R, G←doc:specular.G, B←doc:specular.B | png | 0 | off |
| Vray Next (Specular Glossiness) | `$mesh_$textureSet_Glossiness(_$colorSpace)(.$udim)` | L←doc:glossiness.L | png | 0 | off |
| Vray Next (Specular Glossiness) | `$mesh_$textureSet_Height(_$colorSpace)(.$udim)` | L←doc:height.L | png | 1 | off |
| Vray Next (Specular Glossiness) | `$mesh_$textureSet_Normal(_$colorSpace)(.$udim)` | R←virtual:Normal_OpenGL.R, G←virtual:Normal_OpenGL.G, B←virtual:Normal_OpenGL.B | png | 1 | off |
| Vray Next (Specular Glossiness) | `$mesh_$textureSet_Emissive(_$colorSpace)(.$udim)` | R←doc:emissive.R, G←doc:emissive.G, B←doc:emissive.B | png | 0 | off |
| Vray Next (Specular Glossiness) | `$mesh_$textureSet_Transmissive(_$colorSpace)(.$udim)` | R←doc:transmissive.R, G←doc:transmissive.G, B←doc:transmissive.B | png | 0 | off |
| Vray Next (Specular Glossiness) | `$mesh_$textureSet_AnisotropyAngle(_$colorSpace)(.$udim)` | L←doc:anisotropyangle.L | png | 1 | off |
| Vray Next (Specular Glossiness) | `$mesh_$textureSet_AnisotropyLevel(_$colorSpace)(.$udim)` | L←doc:anisotropylevel.L | png | 0 | off |
| Vray Next UDIM Legacy (Metallic Roughness) | `$mesh_BaseColor(_$colorSpace).$textureSet` | R←doc:basecolor.R, G←doc:basecolor.G, B←doc:basecolor.B | png | 0 | off |
| Vray Next UDIM Legacy (Metallic Roughness) | `$mesh_Roughness(_$colorSpace).$textureSet` | L←doc:roughness.L | png | 0 | off |
| Vray Next UDIM Legacy (Metallic Roughness) | `$mesh_Metallic(_$colorSpace).$textureSet` | L←doc:metallic.L | png | 0 | off |
| Vray Next UDIM Legacy (Metallic Roughness) | `$mesh_Height(_$colorSpace).$textureSet` | L←doc:height.L | png | 1 | off |
| Vray Next UDIM Legacy (Metallic Roughness) | `$mesh_Normal(_$colorSpace).$textureSet` | R←virtual:Normal_OpenGL.R, G←virtual:Normal_OpenGL.G, B←virtual:Normal_OpenGL.B | png | 1 | off |
| Vray Next UDIM Legacy (Metallic Roughness) | `$mesh_Emissive(_$colorSpace).$textureSet` | R←doc:emissive.R, G←doc:emissive.G, B←doc:emissive.B | png | 0 | off |
| Vray Next UDIM Legacy (Metallic Roughness) | `$mesh_Transmissive(_$colorSpace).$textureSet` | R←doc:transmissive.R, G←doc:transmissive.G, B←doc:transmissive.B | png | 0 | off |
| Vray Next UDIM Legacy (Metallic Roughness) | `$mesh_AnisotropyAngle(_$colorSpace).$textureSet` | L←doc:anisotropyangle.L | png | 1 | off |
| Vray Next UDIM Legacy (Metallic Roughness) | `$mesh_AnisotropyLevel(_$colorSpace).$textureSet` | L←doc:anisotropylevel.L | png | 0 | off |
