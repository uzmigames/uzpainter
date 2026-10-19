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
| `mesh_file_path` | mesh file; the docstring lists `.fbx`, `.obj`, `.dae`, `.ply` and `.usd` | Fact | `project.html` (`create`) |
| glTF / GLB meshes | also accepted (the public `Settings.mesh_settings` takes `GltfSettings`, whose `invert_normal_maps` option applies to glTF imports); [Redacted under the clean-room policy (docs/licensing-and-clean-room.md). Source withheld: MODS\automated_tests\test_project_create.py; MODS\automated_tests\resources\cube_normal_map.glb.] | Fact (API) | `project.html` (`Settings`, `GltfSettings`) |
| `mesh_map_file_paths` | additional (pre-baked) mesh maps; a `.1001` file name loads the whole UDIM sequence | Fact | `project.html` → "Creating a project" (example) |
| `template_file_path` | `.spt` template; values given in the project settings win over the template's; 26 templates ship in `PAINTER\resources\starter_assets\templates\` (12.8–13.2 MB each), e.g. `PBR - Metallic Roughness Alpha-blend.spt`, `OpenPBR - Coat.spt`, `Unreal Engine.spt` | Fact | `project.html`; directory listing |
| Already-open project | `create` raises `ProjectError` | Fact | `project.html` |
| Color management | if `OCIO` points to a `.ocio` file → OCIO mode; else if `PAINTER_ACE_CONFIG` points to a `.json` preset → ACE mode; both set → OCIO; none → Legacy; invalid config → `ProjectError` | Fact | `project.html` (`create`) |
| Asynchrony | `create`/`open` return while loading continues; `ProjectOpened`/`ProjectCreated` may fire before the project is ready; `ProjectEditionEntered` signals "ready to work with" (bake/export/edit) | Fact | `project.html` → "Events" |

### 1.1 `project.Settings` (all fields optional; `None` = default)

| Field | Type | Meaning | Label |
|---|---|---|---|
| `default_save_path` | str | folder a save goes to by default | Fact |
| `normal_map_format` | `NormalMapFormat` | `OpenGL` (right handed) or `DirectX` (left handed) — the normal-map format choice of the New-project dialog | Fact |
| `tangent_space_mode` | `TangentSpace` | `PerVertex` or `PerFragment` — the per-fragment tangent-space checkbox | Fact |
| `project_workflow` | `ProjectWorkflow` | `Default` (no UDIM), `TextureSetPerUVTile` (legacy), `UVTile` (tiles share a Texture Set) | Fact |
| `export_path` | str | folder exported maps go to by default | Fact |
| `default_texture_resolution` | int | starting resolution given to every Texture Set (`ValueError` when invalid) | Fact |
| `import_cameras` | bool | brings in the cameras the mesh file holds | Fact |
| `mesh_unit_scale` | float | custom unit scale; "Painter unit is centimeters"; 0/None = file unit; needed for `.obj` not in cm | Fact |
| `mesh_settings` | `UsdSettings` or `GltfSettings` | format-specific import options (replaces deprecated `usd_settings`) | Fact |
| `auto_unwrap_settings` | `AutoUnwrapSettings` | automatic UV unwrap; `None` disables it; since 0.3.6 it must be passed explicitly (no longer read from user preferences) | Fact |

Source for the table: `project.html` (`Settings`, enums); changelog 0.3.6 in `PYDOC\index.html`.

| Settings class | Fields (defaults) | Label | Source |
|---|---|---|---|
| `UsdSettings` | `scope_name='/'` (absolute prim path), `variants=None` (JSON list of `{primPath, selectionName, setName}`), `subdivision_level=1`, `frame=0` | Fact | `project.html` |
| `GltfSettings` | `invert_normal_maps=None` | Fact | `project.html` |
| `AutoUnwrapSettings` | `recompute_seams=True`, `recompute_uv_islands=True`, `recompute_packing=True`, `margin_size=2.0` (clamped 0–20; typical 0, 2, 5, 10), `island_orientation=RotateFreely` (`AlignWith3DMesh`, `KeepOriginal`; `RotateFreely` unavailable when islands are recomputed → falls back to `KeepOriginal`), `uv_tiles_settings=AutoUnwrapUVTilesSettingsUVTilesCount()` (UV-tile workflow only), `avoid_elongated_uv_islands=False`, `create_fewer_seams=True` (earlier algorithm, simpler maps) | Fact | `project.html` |
| `AutoUnwrapUVTilesSettingsUVTilesCount` | `uv_tile_count_max=4` (clamped 1–1024; never below the count of Texture Sets produced) | Fact | `project.html` |
| `AutoUnwrapUVTilesSettingsTexelDensity` | `texel_density=1.0` texels/cm (clamped 0.01–1 000 000), `reference_resolution=1024` (clamped 128–4096) | Fact | `project.html` |
| FBX-specific settings | none in the public API | Fact (absence); same conclusion in `MCP\docs\PROJECT_LIFECYCLE.md` | `PYSRC\project.py` |
| "Hard Surface" unwrap mode | the MCP author reports a 12.1 UI mode with no public `AutoUnwrapSettings` field | Fact that the field is absent; UI claim not verified here | `PYSRC\project.py`; `MCP\docs\PROJECT_LIFECYCLE.md` |

### 1.2 Texture Set naming

| Rule | Label | Source |
|---|---|---|
| One Texture Set per material of the imported mesh (per tile in the legacy workflow); `TextureSet.original_name` keeps the name the set had at import. | Fact | `PYDOC\substance_painter\textureset\textureset.html`; `project.html` (`ProjectWorkflow`) |
| `TextureSet.name` and `description` are writable (since 0.3.4); names must be unique and must not contain reserved characters (the reserved set is not listed). | Fact; reserved set not confirmed | `textureset.html`; changelog 0.3.4 |
| `UVTile.name`/`description` writable; no two tiles of one set share a name. | Fact | `PYDOC\substance_painter\textureset\uvtile.html` |
| Texture Set and stack names compare case-sensitively. Case sensitivity of resource names is not documented there (**not confirmed**). | Fact | `textureset\stack.html` (`from_name`) |

## 2. Open, state and close

| Function | Behaviour | Label | Source |
|---|---|---|---|
| `open(path)` | opens a `.spp`; raises if one is already open | Fact | `project.html` |
| `close()` | closes; anything not saved is dropped | Fact | same |
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
| `save(mode=Incremental)` | overwrite the current file | Fact | `project.html`; `PYSRC\project.py` ([Redacted under the clean-room policy (docs/licensing-and-clean-room.md). Source withheld: PYSRC\project.py.]) |
| `save_as(path, mode=Incremental)` | write to a new path and relocate the project; missing folders are created | Fact | same |
| `save_as_copy(path, mode=Incremental)` | write a backup copy; the project keeps its previous location and stays dirty (the copy does not count as saving the project) | Fact | `project.html` (`save_as_copy` and module example) |
| `save_as_template(path, texture_set_name)` | write a `.spt` from one Texture Set; overwrites | Fact | same |
| `ProjectSaveMode.Full` | writes all data to a fresh file: slower, smallest result | Fact | `PYSRC\project.py` |
| `ProjectSaveMode.Incremental` | writes only data that is new or changed: faster, larger file | Fact | same |
| UI "Save and compact" | "Save the current project in place and compress it (reduce footprint on disk)" | Fact | Adobe "File menu": https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/interface/main-menu/file-menu |
| Python equivalent of "Save and compact" | `save(ProjectSaveMode.Full)`: Adobe's JS docs state that repeated Incremental saves fragment the project file and that a Full save in place removes it | Fact (fragmentation removal); equivalence with every effect of the UI command Hypothesis | the two sources above; `PAINTER\resources\javascript-doc\alg.project.html` (save example, lines 1666–1670) |
| UI "Clean" | "Remove any unused resources from the current project (will take effect after the next Save)" — no Python function | Fact | Adobe "File menu" (same URL); absence in `PYSRC\project.py` |
| Busy guard | every save raises `ProjectError` while busy | Fact | `project.html` → "Saving a project" |
| JS extras | `alg.project.saveAndClose`, `alg.project.exportMesh` | Fact | `PAINTER\resources\javascript-doc\alg.project.html` |

## 4. Reloading the mesh

`reload_mesh(mesh_file_path, settings: MeshReloadingSettings, loading_status_cb)` — asynchronous; the callback receives `ReloadMeshStatus.SUCCESS` (0) or `ERROR` (2, "see application log"); raises if no project or busy; formats `.fbx`, `.obj`, `.dae`, `.ply`, `.usd` (**Fact**, `project.html` → "Reloading a mesh"). `MeshReloadingSettings(import_cameras=True, preserve_strokes=True, mesh_settings: UsdSettings=None, auto_unwrap_settings=None)` (**Fact**, same). Adobe's own test of mesh update exists (`MODS\automated_tests\test_mesh_update.py`) (**Fact**, listing).

## 5. Metadata and settings storage

| Mechanism | Behaviour | Label | Source |
|---|---|---|---|
| `project.Metadata(context)` | `list()`, `get(key)`, `set(key, value)`; values: bool, int, float, str, lists, dicts with str keys; saved with the project; `context` should be unique per plugin | Fact | `project.html` → "Project metadata" |
| JS `alg.project.settings` | `value`, `setValue`, `contains`, `keys`, `remove`, `clear` | Fact (function names) | `PAINTER\resources\javascript-doc\alg.project.settings.html` |
| Display state (Python) | `display.get/set_environment_resource`, `get/set_color_lut_resource`, `get/set_tone_mapping` (`Linear`, `ACES`), `Camera` (position, rotation, field_of_view, focal_length, focus_distance, aperture, orthographic_height, projection_type) | Fact | `PYDOC\substance_painter\display.html` |
| Parameters of shader instances | only through the JS API (`alg.shaders.parameters`, `setParameters`, `updateShaderInstance`, `shaderInstancesToObject`) | Fact | `PAINTER\resources\javascript-doc\alg.shaders.html` |

## 6. The `.spp` container — facts vs hypotheses

| # | Statement | Label | Source |
|---|---|---|---|
| 1 | `.spp` files start with the HDF5 signature `89 48 44 46 0D 0A 1A 0A` ("\x89HDF\r\n\x1a\n"); the same signature starts `.spt`, `.spsm` and `.spmsk` files. The signature identifies the file family only: it does not establish the group hierarchy, entry sizes, compression codecs, hash algorithm, cache semantics or a writable schema. | Fact (signature) | `xxd` of `MODS\automated_tests\resources\layerstack-cube.spp`, `PAINTER\resources\samples\MeetMat.spp`, `starter_assets\templates\Unreal Engine.spt`, a `.spsm` and a `.spmsk` |
| 2 | Shipped sample sizes: FrenchRestaurantTable 248.3 MB, PreviewSphere 90.4 MB, MeetMat 65.4 MB, JadeToad 48.7 MB, TilingMaterial 44.7 MB; Adobe's minimal test project `layerstack-cube.spp` is 55 KB. | Fact | `PAINTER\resources\samples\`; `MODS\automated_tests\resources\` |
| 3 | Adobe's stated reasons for large projects: the project stores the processed source mesh, the baked mesh maps, the materials (e.g. Substance materials) and the bitmaps/resources used by layers, presets and brush strokes, so that it is self-contained; frequent incremental saves leave empty space that "Save and Compact" removes; "Clean" removes unused resources; lowering Texture Set resolution shrinks the viewport cache. | Fact | Adobe "Projects are really big": https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/technical-support/workflow-issues/project-issues/projects-are-really-big |
| 4–14 | Internal entry names, serialized settings, type names and other strings found inside `.spp` files: [Redacted under the clean-room policy (docs/licensing-and-clean-room.md). Source withheld: MODS\automated_tests\resources\layerstack-cube.spp; PAINTER\resources\samples\MeetMat.spp; PAINTER\resources\samples\FrenchRestaurantTable.spp.] What a project stores, as Adobe states publicly, is in row 3; the original mesh path is available through the public `last_imported_mesh_path()` (§2). | — | — |
| 15 | Exact HDF5 group/dataset layout, compression filters and per-entry sizes were not inspected (no HDF5 reader was used: `h5py` was absent from the Python environment checked and nothing was installed — this does not prove that no HDF5 reader exists on the machine). | not confirmed | — |
| 16 | Adobe ships a test resource named `future_binary_data.spp` (file name and existence only). [Redacted under the clean-room policy (docs/licensing-and-clean-room.md). Source withheld: MODS\automated_tests\test_project_open.py.] It says nothing about the semantics of ordinary project data. | Fact (file exists) | `MODS\automated_tests\resources\` (directory listing) |
| 17 | Projects record the Painter version that last saved them (since after 8.2.0) and a UUID. | Fact | `project.html` |

## 7. Resource scope inside a project

| Statement | Label | Source |
|---|---|---|
| Resources imported with `import_project_resource` and baked maps are embedded in the `.spp` (`ResourceLocation.PROJECT`); session resources are lost on restart; shelf resources stay on disk. | Fact | `PYSRC\resource.py` (`ResourceLocation`) |
| The MCP author notes there is no public safe delete for an arbitrary embedded project resource. | Fact (absence in `resource.py`); same note in `MCP\docs\RESOURCE_INGESTION.md` | `PYSRC\resource.py` |
| Projects reference shelf resources by URL with a version hash; `list_project_outdated_resources()` reports newer shelf versions and `replace_project_resources` swaps them atomically. | Fact | `PYDOC\substance_painter\resource.html` |
