# 05 — Substance 3D Painter projects and the `.spp` file (as of 2026-10-10)

Project creation settings, open/save/close behaviour, mesh reload, metadata, display state, and what can and cannot be said about the `.spp` container. Input for the UzPainter architect; it documents Substance, it does not decide what UzPainter replicates.

## Conventions

- `PAINTER` = `C:\Program Files\Adobe\Adobe Substance 3D Painter`; `PYDOC` = `PAINTER\resources\python-doc`; `PYSRC` = `PAINTER\resources\python\modules\substance_painter`; `MODS` = `PAINTER\resources\python\modules`; `MCP` = `E:\UzmiGames\Assets3D\Tools\SubstancePainterMCP`.
- Labels: **Fact**, **Hypothesis**, **Recommendation**; "not confirmed" marks gaps.
- Main source: `PYDOC\substance_painter\project.html` (= docstrings of `PYSRC\project.py`).

## 1. Creating a project

`project.create(mesh_file_path, mesh_map_file_paths=None, template_file_path=None, settings=Settings())` (**Fact**, `project.html`).

| Input | Rule | Label | Source |
|---|---|---|---|
| `mesh_file_path` | "Supported file formats: fbx, obj, dae, ply, usd" (docstring) | Fact | `project.html` (`create`) |
| glTF / GLB meshes | also accepted: Adobe's test creates a project from `cube_normal_map.glb` with `GltfSettings`; the glTF material's textures arrive as a root fill layer whose Normal source colour space is `NormalXYZRight` (default) or `NormalXYZLeft` (`invert_normal_maps=True`) | Fact | `MODS\automated_tests\test_project_create.py`; test resource `MODS\automated_tests\resources\cube_normal_map.glb` |
| `mesh_map_file_paths` | additional (pre-baked) mesh maps; a `.1001` file name loads the whole UDIM sequence | Fact | `project.html` → "Creating a project" (example) |
| `template_file_path` | `.spt` template; "Project settings override the template parameters"; 26 templates ship in `PAINTER\resources\starter_assets\templates\` (12.8–13.2 MB each), e.g. `PBR - Metallic Roughness Alpha-blend.spt`, `OpenPBR - Coat.spt`, `Unreal Engine.spt` | Fact | `project.html`; directory listing |
| Already-open project | `create` raises `ProjectError` | Fact | `project.html` |
| Color management | if `OCIO` points to a `.ocio` file → OCIO mode; else if `PAINTER_ACE_CONFIG` points to a `.json` preset → ACE mode; both set → OCIO; none → Legacy; invalid config → `ProjectError` | Fact | `project.html` (`create`) |
| Asynchrony | `create`/`open` return while loading continues; `ProjectOpened`/`ProjectCreated` may fire before the project is ready; `ProjectEditionEntered` signals "ready to work with" (bake/export/edit) | Fact | `project.html` → "Events" |

### 1.1 `project.Settings` (all fields optional; `None` = default)

| Field | Type | Meaning (Adobe wording, condensed) | Label |
|---|---|---|---|
| `default_save_path` | str | default save path | Fact |
| `normal_map_format` | `NormalMapFormat` | `OpenGL` (right handed) or `DirectX` (left handed) — "Normal Map Format" in the New-project dialog | Fact |
| `tangent_space_mode` | `TangentSpace` | `PerVertex` or `PerFragment` — "Compute Tangent Space Per Fragment" checkbox | Fact |
| `project_workflow` | `ProjectWorkflow` | `Default` (no UDIM), `TextureSetPerUVTile` (legacy), `UVTile` (tiles share a Texture Set) | Fact |
| `export_path` | str | default map export path | Fact |
| `default_texture_resolution` | int | default resolution of all Texture Sets (`ValueError` if invalid) | Fact |
| `import_cameras` | bool | import cameras from the mesh file | Fact |
| `mesh_unit_scale` | float | custom unit scale; "Painter unit is centimeters"; 0/None = file unit; needed for `.obj` not in cm | Fact |
| `mesh_settings` | `UsdSettings` or `GltfSettings` | format-specific import options (replaces deprecated `usd_settings`) | Fact |
| `auto_unwrap_settings` | `AutoUnwrapSettings` | automatic UV unwrap; `None` disables it; since 0.3.6 it must be passed explicitly (no longer read from user preferences) | Fact |

Source for the table: `project.html` (`Settings`, enums); changelog 0.3.6 in `PYDOC\index.html`.

| Settings class | Fields (defaults) | Label | Source |
|---|---|---|---|
| `UsdSettings` | `scope_name='/'` (absolute prim path), `variants=None` (JSON list of `{primPath, selectionName, setName}`), `subdivision_level=1`, `frame=0` | Fact | `project.html` |
| `GltfSettings` | `invert_normal_maps=None` | Fact | `project.html` |
| `AutoUnwrapSettings` | `recompute_seams=True`, `recompute_uv_islands=True`, `recompute_packing=True`, `margin_size=2.0` (clamped 0–20; typical 0, 2, 5, 10), `island_orientation=RotateFreely` (`AlignWith3DMesh`, `KeepOriginal`; `RotateFreely` unavailable when islands are recomputed → falls back to `KeepOriginal`), `uv_tiles_settings=AutoUnwrapUVTilesSettingsUVTilesCount()` (UV-tile workflow only), `avoid_elongated_uv_islands=False`, `create_fewer_seams=True` (earlier algorithm, simpler maps) | Fact | `project.html` |
| `AutoUnwrapUVTilesSettingsUVTilesCount` | `uv_tile_count_max=4` (clamped 1–1024; at least the number of resulting Texture Sets) | Fact | `project.html` |
| `AutoUnwrapUVTilesSettingsTexelDensity` | `texel_density=1.0` texels/cm (clamped 0.01–1 000 000), `reference_resolution=1024` (clamped 128–4096) | Fact | `project.html` |
| FBX-specific settings | none in the public API | Fact (absence); same conclusion in `MCP\docs\PROJECT_LIFECYCLE.md` | `PYSRC\project.py` |
| "Hard Surface" unwrap mode | the MCP author reports a 12.1 UI mode with no public `AutoUnwrapSettings` field | Fact that the field is absent; UI claim not verified here | `PYSRC\project.py`; `MCP\docs\PROJECT_LIFECYCLE.md` |

### 1.2 Texture Set naming

| Rule | Label | Source |
|---|---|---|
| One Texture Set per material of the imported mesh (per tile in the legacy workflow); `TextureSet.original_name` is "the original name … as it was when it was imported". | Fact | `PYDOC\substance_painter\textureset\textureset.html`; `project.html` (`ProjectWorkflow`) |
| `TextureSet.name` and `description` are writable (since 0.3.4); names must be unique and must not contain reserved characters (the reserved set is not listed). | Fact; reserved set not confirmed | `textureset.html`; changelog 0.3.4 |
| `UVTile.name`/`description` writable; tile names unique within a Texture Set. | Fact | `PYDOC\substance_painter\textureset\uvtile.html` |
| Texture Set, stack and resource names are case sensitive. | Fact | `textureset\stack.html` (`from_name`) |

## 2. Open, state and close

| Function | Behaviour | Label | Source |
|---|---|---|---|
| `open(path)` | opens a `.spp`; raises if one is already open | Fact | `project.html` |
| `close()` | closes; "Any unsaved data will be lost" | Fact | same |
| `is_open()`, `is_in_edition_state()` | project present / ready to work with | Fact | same |
| `is_busy()`, `execute_when_not_busy(cb)`, event `BusyStatusChanged(busy)` | busy during loading, baking, export, unwrap; saving is refused while busy | Fact | same |
| `needs_saving()` | dirty flag | Fact | same |
| `name()`, `file_path()` | `None` until first save | Fact | same |
| `get_uuid()` | project UUID | Fact | same |
| `last_saved_substance_painter_version()` | `(major, minor, patch)` or `None` if unsaved or saved with ≤ 8.2.0 | Fact | same |
| `last_imported_mesh_path()` | path of the last imported mesh | Fact | same |
| `get_scene_bounding_box()` | `BoundingBox(dimensions, center, radius)` | Fact | same |
| `application.close()` | closes Painter; unsaved data lost | Fact | `PYDOC\substance_painter\application.html` |
| Events | `ProjectOpened`, `ProjectCreated`, `ProjectAboutToClose`, `ProjectClosed`, `ProjectAboutToSave(file_path)`, `ProjectSaved`, `ProjectEditionEntered`, `ProjectEditionLeft` | Fact | `project.html` → "Events"; `PYSRC\event.py` |

## 3. Saving

| Function | Behaviour | Label | Source |
|---|---|---|---|
| `save(mode=Incremental)` | overwrite the current file | Fact | `project.html`; `PYSRC\project.py` (`_DEFAULT_SAVE_MODE = ProjectSaveMode.Incremental`) |
| `save_as(path, mode=Incremental)` | write to a new path and relocate the project; missing folders are created | Fact | same |
| `save_as_copy(path, mode=Incremental)` | write a backup copy; the project keeps its previous location and stays dirty ("Even though a back copy was made, the project still has to be saved") | Fact | `project.html` (`save_as_copy` and module example) |
| `save_as_template(path, texture_set_name)` | write a `.spt` from one Texture Set; overwrites | Fact | same |
| `ProjectSaveMode.Full` | "Save everything in a new file. Slow but creates the smallest possible file." | Fact | `PYSRC\project.py` |
| `ProjectSaveMode.Incremental` | "Save only new or modified data. Fast but the file size is not optimal." | Fact | same |
| UI "Save and compact" | "Save the current project in place and compress it (reduce footprint on disk)" | Fact | Adobe "File menu": https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/interface/main-menu/file-menu |
| Python equivalent of "Save and compact" | `save(ProjectSaveMode.Full)` | Hypothesis (both described as rewriting the whole file) | the two sources above |
| UI "Clean" | "Remove any unused resources from the current project (will take effect after the next Save)" — no Python function | Fact | Adobe "File menu" (same URL); absence in `PYSRC\project.py` |
| Busy guard | every save raises `ProjectError` while busy | Fact | `project.html` → "Saving a project" |
| JS extras | `alg.project.saveAndClose`, `alg.project.exportMesh` | Fact | `PAINTER\resources\javascript-doc\alg.project.html` |

## 4. Reloading the mesh

`reload_mesh(mesh_file_path, settings: MeshReloadingSettings, loading_status_cb)` — asynchronous; the callback receives `ReloadMeshStatus.SUCCESS` (0) or `ERROR` (2, "see application log"); raises if no project or busy; formats fbx, obj, dae, ply, usd (**Fact**, `project.html` → "Reloading a mesh"). `MeshReloadingSettings(import_cameras=True, preserve_strokes=True, mesh_settings: UsdSettings=None, auto_unwrap_settings=None)` (**Fact**, same). Adobe's own test of mesh update exists (`MODS\automated_tests\test_mesh_update.py`) (**Fact**, listing).

## 5. Metadata and settings storage

| Mechanism | Behaviour | Label | Source |
|---|---|---|---|
| `project.Metadata(context)` | `list()`, `get(key)`, `set(key, value)`; values: bool, int, float, str, lists, dicts with str keys; saved with the project; `context` should be unique per plugin | Fact | `project.html` → "Project metadata" |
| JS `alg.project.settings` | `value`, `setValue`, `contains`, `keys`, `remove`, `clear` | Fact (function names) | `PAINTER\resources\javascript-doc\alg.project.settings.html` |
| Display state (Python) | `display.get/set_environment_resource`, `get/set_color_lut_resource`, `get/set_tone_mapping` (`Linear`, `ACES`), `Camera` (position, rotation, field_of_view, focal_length, focus_distance, aperture, orthographic_height, projection_type) | Fact | `PYDOC\substance_painter\display.html` |
| Shader instance parameters | only through the JS API (`alg.shaders.parameters`, `setParameters`, `updateShaderInstance`, `shaderInstancesToObject`) | Fact | `PAINTER\resources\javascript-doc\alg.shaders.html` |

## 6. The `.spp` container — facts vs hypotheses

| # | Statement | Label | Source |
|---|---|---|---|
| 1 | `.spp` files start with the HDF5 signature `89 48 44 46 0D 0A 1A 0A` ("\x89HDF\r\n\x1a\n"); the same signature starts `.spt`, `.spsm` and `.spmsk` files. | Fact | `xxd` of `MODS\automated_tests\resources\layerstack-cube.spp`, `PAINTER\resources\samples\MeetMat.spp`, `starter_assets\templates\Unreal Engine.spt`, a `.spsm` and a `.spmsk` |
| 2 | Shipped sample sizes: FrenchRestaurantTable 248.3 MB, PreviewSphere 90.4 MB, MeetMat 65.4 MB, JadeToad 48.7 MB, TilingMaterial 44.7 MB; Adobe's minimal test project `layerstack-cube.spp` is 55 KB. | Fact | `PAINTER\resources\samples\`; `MODS\automated_tests\resources\` |
| 3 | Adobe's stated reasons for large projects: the project stores the processed source mesh, the baked mesh maps, the materials (e.g. Substance materials) and the bitmaps/resources used by layers, presets and brush strokes, so that it is self-contained; frequent incremental saves leave empty space that "Save and Compact" removes; "Clean" removes unused resources; lowering Texture Set resolution shrinks the viewport cache. | Fact | Adobe "Projects are really big": https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/technical-support/workflow-issues/project-issues/projects-are-really-big |
| 4 | Entry names visible inside `.spp` files: `header`, `resources.toc`, `plugins.toc`, `projectsettings.ini`, `editor`, `paint`, `plugins`, `resources`, `texture-cache`, `baking`, `metadata`, `document.bin`, `default_material.bin`, `layersstackstate2.bin`, `scene.assbin`, `.alg_meta`, `posteffects.ini`, `colorprofile.ini`, `camera.ini`, `viewersettings2.ini`, `iraysettings2.ini`, `exporter.ini`, `exporterv2.json`, `vep_settings.ini`, `baking.ini`, `sanity_flags`, and resource entries named `<40-hex>.image` / `<40-hex>.shader`. | Fact (strings) | Python byte scan of `layerstack-cube.spp` and `MeetMat.spp` this session |
| 5 | The processed mesh is stored as an ASSIMP binary dump (`scene.assbin`, header "ASSIMP.binary-dump", custom keys `ALG_PRE_PTV_TRANSFORM`, `ALG_PTV_TOTAL_TRANSFORM`, `ALG_PRE_NORMALIZATION_CENTER`, `ALG_PRE_NORMALIZATION_RADIUS`). | Fact | strings in `layerstack-cube.spp` |
| 6 | The original mesh path is kept as a file URL (`file:///C:/tmp/cube1.fbx`); a path ending in `.spp.tmpsave/paint/scene.assbin` also appears. | Fact (strings); "saves go through a `.tmpsave` folder" Hypothesis | same |
| 7 | The project's GLSL shader source is embedded (the `asm-metal-rough` shader text, referenced as `resource://viewer/asm-metal-rough?version=<hash>.shader`). | Fact | same |
| 8 | Serialized settings blocks: auto-unwrap JSON (`createFewerSeamsEnabled`, `enabled`, `keepIslandOrientationsEnabled`, `loadUVsFromMesh: 7`, `maxNbUVTiles: 4`, `minTexelDensity`, `nbIslandRotations: 8`, `referenceTextureResolution: 1024`, `segmentElongatedChartsEnabled`, `useTexelDensityEnabled`, `uvIslandsMargin: 0.002…`, `version: 6`); exporter JSON (`version: 3`); post effects (`DataPostEffectsParameters` with color correction, tone mapping, DOF, glare, lens distortion, SSS, TAA, vignette); viewer (`ViewerSettingsData`, `ShaderData`, `DisplacementTessellationData`); Iray (`IraySettingsData`, `MdlData` with `mdl::alg::materials::painter::standard`); camera (`CameraSettingsData`). | Fact (strings) | `layerstack-cube.spp` |
| 9 | Document model type names: `DataDocument {colorManagementACE, colorManagementOCIO, colorManagementWorkflow, materials, meshSystemSizeOverride, normalMapSyscoord, projectWorkflow, tangentSpaceMode, usePhysicalSizeAsDefault}`, `DataMaterial {additionalAmbientOcclusionMapBlending, additionalMaps, additionalNormalMapBlending, description, height2NormalMethod, normalMapBitmap, paddingMode, resolutionLog2, sceneMaterialName, sceneMaterialUID, shaderId, stacks, useUVTiles, uvTiles}`, `DataMaterialStack {channels, label, selections, stack}`, `DataChannel {format, userIsColorManaged, userName}`, `DataLayerGroup`/`DataLayerColor {actions, colorTag, enabled, enabledGeometryMask, enabledMeshDefault, enabledMeshList, enabledUVTileDefault, enabledUVTileList, explicitPersistentCachePin, gammaCompensation, geometryMaskType, label, maskActions, maskEnabled, maskInitial, perChannelBlending[, subStack, GUIcollapsedState]}`, `DataActionGroup {channelTypes, enabled, label, perChannelBlending, selection, subStack}`, `DataBlending {blendingMode, channelTypes, opacity}`. | Fact (strings) | `layerstack-cube.spp` |
| 10 | Further type names in the large samples: `DataActionFill`, `DataActionDecal`, `DataActionFilterLevels`, `DataActionFilterProcedural`, `DataActionAnchor`, `DataSourceUniform`, `DataSourceBitmap`, `DataSourceProcedural`, `DataSourceReference`, `DataProcedural`, `DataProceduralInput`, `DataProceduralInputsSource`, `DataProceduralOutput`, `DataReference`, `DataReferenceBinding`, `DataLevels`, `DataGridDeformation`, `DataGridVertex`, `DataDecalHitPunctual`, `DataDecalHitRect`, `DataSymmetry`, `DataResolutionOverride`, `DataUVTile`, `DataAdditionalMap`, `DataStackState(s)`, `DataLayerState`, `DataTweak{Bool,Int,Int2,Float,Float2,Float3,Float4,ByteArray}`, `BakingMaterial(s)`, `BakingDefinition`, `BakingCommonParameters`, `BakingTweakList`, `BakingSkewParameters`, `BakingSkewmapMaterialData`, `BakingVisualizationData`, `BakingNeutralMaterialData`, `DataColorManagementOCIO`, post-effect `…ParametersV2` types. | Fact (strings) | `PAINTER\resources\samples\MeetMat.spp`, `FrenchRestaurantTable.spp` |
| 11 | Mapping of those types to features: `DataLayerColor` = paint/fill layer, `DataActionFill` = fill effect, `DataActionDecal` = projected fill (planar/spherical/…), `DataGridDeformation` = warp grid, `DataTweak*` = engine properties exposed as `properties.Property`. | Hypothesis | names only |
| 12 | `m3_x64_128` appears next to every embedded entry. | Fact (string) | `layerstack-cube.spp` |
| 13 | `m3_x64_128` names the hash used for entry versions (MurmurHash3 x64 128-bit). | Hypothesis | name only |
| 14 | Painter keeps a `texture-cache` entry in the file; its contents (cached layer/channel textures) and its share of the file size are not confirmed. | Fact (entry name); content Hypothesis | strings in `MeetMat.spp` |
| 15 | Exact HDF5 group/dataset layout, compression filters and per-entry sizes were not inspected (no HDF5 library is available outside Painter on this machine; nothing was installed). | not confirmed | — |
| 16 | Adobe ships `future_binary_data.spp` among its test resources, suggesting tests for opening files containing data from a newer version. | Fact (file); purpose Hypothesis | `MODS\automated_tests\resources\future_binary_data.spp` |
| 17 | Projects record the Painter version that last saved them (since after 8.2.0) and a UUID. | Fact | `project.html` |

## 7. Resource scope inside a project

| Statement | Label | Source |
|---|---|---|
| Resources imported with `import_project_resource` and baked maps are embedded in the `.spp` (`ResourceLocation.PROJECT`); session resources are lost on restart; shelf resources stay on disk. | Fact | `PYSRC\resource.py` (`ResourceLocation`) |
| The MCP author notes there is no public safe delete for an arbitrary embedded project resource. | Fact (absence in `resource.py`); same note in `MCP\docs\RESOURCE_INGESTION.md` | `PYSRC\resource.py` |
| Projects reference shelf resources by URL with a version hash; `list_project_outdated_resources()` reports newer shelf versions and `replace_project_resources` swaps them atomically. | Fact | `PYDOC\substance_painter\resource.html` |
