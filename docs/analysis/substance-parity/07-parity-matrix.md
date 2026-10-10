# 07 — Substance 3D Painter capability parity matrix (as of 2026-10-10)

One row per capability: the Substance 3D Painter 12.1.0 Python API symbols that provide it, and whether the current SubstancePainterMCP 1.0.0 bridge (with the local patch) exposes it. This matrix records facts only; it does **not** decide what UzPainter will include — that is the architect's call.

## Conventions

- Symbols are relative to `substance_painter` (e.g. `layerstack.insert_fill`); full signatures in `01-python-api-inventory.md`; behaviour in files 02–05; MCP details in `06-mcp-tools-inventory.md`.
- "Exposed by current MCP?": **Yes** = a dedicated tool covers it; **Partial** = covered with limits stated in Notes; **No** = no tool (only reachable through the opt-in `execute_python`); **N/A** = Painter has no public Python API for it either.
- Every row is a **Fact** derived from the shipped Painter sources (`C:\Program Files\Adobe\Adobe Substance 3D Painter\resources\python\modules\substance_painter\*.py`, `resources\python-doc\`) and the MCP sources (`E:\UzmiGames\Assets3D\Tools\SubstancePainterMCP\src\substance_painter_mcp\operations.py`, `server.py`, `tool-schema.json`), unless the Notes say **Hypothesis** or "not confirmed".

## A. Application, scripting and events

| # | Capability | Substance API symbol(s) | Exposed by current MCP? | Notes |
|---|---|---|---|---|
| A1 | Query application / API version | `application.version`, `application.version_info`, `substance_painter.__version__` | Partial | `painter_status` uses JS `alg.version.painter` and `__version__` (reports 0.3.5 on a 12.1 build) |
| A2 | Feature detection at runtime | `hasattr` on API symbols | Yes | `get_capabilities` |
| A3 | Enable/disable engine computations (batch edits without recompute) | `application.enable_engine_computations`, `disable_engine_computations`, `engine_computations_status`; event `EngineComputationsStatusChanged` | No | |
| A4 | Close the application | `application.close` | No | |
| A5 | Write to the Painter log | `logging.log/info/warning/error` | No | |
| A6 | Plugin management | `substance_painter_plugins.*` | No | |
| A7 | Run arbitrary Python in Painter | remote scripting `/run.json` (not part of the Python API docs) | Yes | `execute_python`, disabled unless `SP_MCP_ALLOW_EXECUTE_PYTHON=1` |
| A8 | Call the legacy JavaScript API | `js.evaluate` | No | the MCP calls two JS expressions internally only |
| A9 | Subscribe to events | `event.DISPATCHER.connect/connect_strong/disconnect`, 27 event classes | Partial | used internally for bake, project-creation, mesh-reload and shelf-refresh jobs; no generic subscription tool |
| A10 | Wait until not busy | `project.is_busy`, `project.execute_when_not_busy`, event `BusyStatusChanged` | Partial | busy state reported by job/plan tools |

## B. Project lifecycle

| # | Capability | Substance API symbol(s) | Exposed by current MCP? | Notes |
|---|---|---|---|---|
| B1 | Create a project from a mesh (+ template, pre-baked mesh maps) | `project.create`, `project.Settings` | Yes | `plan_project_creation`, `create_project` (async job, backup of the current project, saves in Full mode) |
| B2 | Normal-map format, tangent space, UDIM workflow, default resolution, cameras, unit scale | `project.Settings` fields, `NormalMapFormat`, `TangentSpace`, `ProjectWorkflow` | Yes | via `settings` object |
| B3 | Auto-unwrap at creation / reload | `project.AutoUnwrapSettings`, `AutoUnwrapUVTilesSettingsUVTilesCount`, `…TexelDensity`, `AutoUnwrapUVIslandOrientation` | Yes | |
| B4 | USD / glTF import options | `project.UsdSettings`, `project.GltfSettings` | Yes | glTF only at creation (API limitation: `MeshReloadingSettings.mesh_settings` is `UsdSettings`) |
| B5 | OCIO / ACE color-management mode | environment variables `OCIO`, `PAINTER_ACE_CONFIG` read by `project.create` | No | must be set in Painter's process environment |
| B6 | Open a project | `project.open` | Yes | `open_project` (requires backup when dirty) |
| B7 | Close a project | `project.close` | Partial | only inside `create_project` / `open_project` |
| B8 | Save in place (Incremental/Full) | `project.save`, `ProjectSaveMode` | Yes | `save_project` |
| B9 | Save as (relocate) | `project.save_as` | Partial | used only inside `create_project` |
| B10 | Save a copy / backup | `project.save_as_copy` | Yes | `save_project_copy`; optional backups in recipe, bake, reload tools |
| B11 | Save as template (`.spt`) | `project.save_as_template` | No | |
| B12 | "Clean" unused resources | none (UI only) | N/A | |
| B13 | Project state (open, dirty, name, path) | `project.is_open`, `needs_saving`, `name`, `file_path`, `is_in_edition_state` | Yes | `get_project_info`, plan tools |
| B14 | Project UUID, last-saved version, scene bounding box, last imported mesh | `project.get_uuid`, `last_saved_substance_painter_version`, `get_scene_bounding_box`, `last_imported_mesh_path` | Partial | only `last_imported_mesh_path` is used (mesh-reload planning) |
| B15 | Reload the mesh | `project.reload_mesh`, `MeshReloadingSettings`, `ReloadMeshStatus` | Yes | `plan_mesh_reload`, `start_mesh_reload`, `get_mesh_reload_job` |
| B16 | Project metadata key/value store | `project.Metadata` | No | |

## C. Texture Sets, stacks, channels, UV tiles

| # | Capability | Substance API symbol(s) | Exposed by current MCP? | Notes |
|---|---|---|---|---|
| C1 | List Texture Sets | `textureset.all_texture_sets` | Yes | |
| C2 | Rename / describe Texture Sets | `TextureSet.name`, `TextureSet.description` setters | No | |
| C3 | Read Texture Set resolution | `TextureSet.get_resolution` | Yes | `audit_project` |
| C4 | Set Texture Set resolution | `TextureSet.set_resolution`, `textureset.set_resolutions` | No | |
| C5 | List UV tiles | `TextureSet.all_uv_tiles`, `has_uv_tiles`, `uv_tile` | Partial | exposed as UDIM numbers inside baking and geometry-mask tools |
| C6 | Name / describe UV tiles | `UVTile.name`, `UVTile.description` | No | |
| C7 | Per-UV-tile resolution | `TextureSet.get/set/reset_uvtiles_resolution`, `UVTile.set_resolution` | No | |
| C8 | Material-layering stacks | `TextureSet.all_stacks`, `get_stack`, `is_layered_material`, `Stack.from_name` | Partial | `audit_project` lists stacks; layer tools target the active/default stack of a Texture Set |
| C9 | Active stack | `textureset.get_active_stack`, `set_active_stack` | Partial | read only |
| C10 | List channels | `Stack.all_channels`, `Channel.type/format/label` | Yes | `audit_project` (names); `get_capabilities` (all channel types) |
| C11 | Add / remove / edit channels (format, user label) | `Stack.add_channel`, `remove_channel`, `edit_channel`, `Channel.edit`, `ChannelFormat` | No | |
| C12 | Mesh-map slots | `TextureSet.get_mesh_map_resource`, `set_mesh_map_resource`, `MeshMapUsage` | Partial | read only (`inspect_baking`, `preflight_bake`) |

## D. Layer-stack structure and editing

| # | Capability | Substance API symbol(s) | Exposed by current MCP? | Notes |
|---|---|---|---|---|
| D1 | Traverse the stack | `layerstack.get_root_layer_nodes`, `GroupLayerNode.sub_layers`, `LayerNode.content_effects`, `mask_effects`, `Node.get_parent/...` | Yes | `list_layers`, `find_layers`, `snapshot_layer_tree`, `list_anchor_points` |
| D2 | Resolve a node by uid | `layerstack.get_node_by_uid`, `Node.uid` | Yes | all mutation tools take uids |
| D3 | Insert fill / paint / group layers | `layerstack.insert_fill`, `insert_paint`, `insert_group`, `InsertPosition.from_textureset_stack`, `inside_node(…, NodeStack.Substack)` | Yes | `create_fill_layer`, `create_paint_layer`, `create_group` (top of stack), `create_layer_recipe` (nested) |
| D4 | Insert above/below a given node | `InsertPosition.above_node`, `below_node` | No | tools insert at stack top or inside a group only |
| D5 | Layer instances | `layerstack.instantiate`, `LayerNode.instances`, `InstanceLayerNode.instance_source` | No | |
| D6 | Delete a node | `layerstack.delete_node` | Yes | `delete_layer` |
| D7 | Rename, visibility | `Node.set_name`, `Node.set_visible` | Yes | `rename_layer`, `set_layer_properties` |
| D8 | Group collapse state | `GroupLayerNode.set_collapsed` | No | |
| D9 | Move / reorder / duplicate existing nodes | none | N/A | MCP `move_layer` deliberately not implemented |
| D10 | Undo grouping / single recompute | `layerstack.ScopedModification` | No | |
| D11 | Selection | `layerstack.set_selected_nodes`, `get_selected_nodes`, `get/set_selection_type`, `SelectionType` | Partial | `select_layers` (no selection type) |
| D12 | Atomic multi-node creation with rollback | (MCP-level composition of the insert APIs) | Yes | `plan_layer_recipe`, `create_layer_recipe` |
| D13 | Structural snapshot and diff | (MCP-level) | Yes | `snapshot_layer_tree`, `diff_layer_snapshots` |
| D14 | Paint strokes (read/write) | none ("Strokes are not accessible from the Python API") | N/A | |

## E. Effects

| # | Capability | Substance API symbol(s) | Exposed by current MCP? | Notes |
|---|---|---|---|---|
| E1 | Effects in a layer's content stack | `InsertPosition.inside_node(layer, NodeStack.Content)` + insert functions | No | MCP inserts effects only in mask stacks |
| E2 | Fill effect in a mask (with resource) | `insert_fill`, `FillEffectNode.set_source(None, res)`, `set_projection_mode` | Yes | `insert_mask_effect` (resource assignment added by the local patch) |
| E3 | Paint effect in a mask | `insert_paint` | Yes | `insert_mask_effect` |
| E4 | Generator effect | `insert_generator_effect`, `GeneratorEffectNode.get/set/remove_source`, `active_channels` | Partial | mask stack only; image inputs editable via `set_procedural_input`; generator parameters not editable (`set_fill_parameters` is Fill-only) |
| E5 | Filter effect | `insert_filter_effect`, `FilterEffectNode.*` | Partial | same limits as E4 |
| E6 | Levels effect | `insert_levels_effect`, `LevelsEffectNode.affected_channel`, `get/set_parameters`, `levels.LevelsParamsMono/RGB` | Partial | insertion in mask only; parameters not editable |
| E7 | Compare Mask effect | `insert_compare_mask_effect`, `CompareMaskEffectParams` | No | |
| E8 | Color Selection (ID-map) effect | `insert_color_selection_effect`, `ColorSelectionEffectParams` | No | |
| E9 | Anchor points | `insert_anchor_point_effect`, `AnchorPointEffectNode` | Partial | insert in mask (`insert_mask_effect`), list (`list_anchor_points`) |
| E10 | Reference an anchor as a source | `set_source(channel, anchor)`, `set_material_source(anchor)`, `SourceReference.channel_mapping/referenced_channel/alpha_matte/get_set_levels` | Partial | `set_fill_anchor_source` binds; mapping, alpha matte and levels not editable |

## F. Masks

| # | Capability | Substance API symbol(s) | Exposed by current MCP? | Notes |
|---|---|---|---|---|
| F1 | Add / remove / change mask background | `LayerNode.add_mask`, `remove_mask`, `set_mask_background`, `MaskBackground` | Yes | `set_layer_mask` |
| F2 | Enable / disable a mask | `LayerNode.enable_mask`, `is_mask_enabled` | Partial | only through recipe `mask.enabled` at creation |
| F3 | Apply a smart mask | `layerstack.insert_smart_mask` | Yes | `apply_smart_mask` |
| F4 | Create a smart mask into a shelf | `layerstack.create_smart_mask` | No | |
| F5 | Export a smart mask file (`.spmsk`) | `layerstack.export_as_smart_mask` | Yes | `export_smart_mask` |
| F6 | Geometry masks (mesh / UV tile, include / exclude) | `LayerNode.get/set_geometry_mask`, `GeometryMaskMeshParams`, `GeometryMaskUVTilesParams` | Yes | `get_geometry_mask`, `set_geometry_mask` (UDIM numbers converted to tiles) |

## G. Blending

| # | Capability | Substance API symbol(s) | Exposed by current MCP? | Notes |
|---|---|---|---|---|
| G1 | Per-channel blend mode | `Node.get/set_blending_mode(mode, channel)`, `BlendingMode` (32 modes) | Yes | `set_layer_properties` (channel defaults to BaseColor) |
| G2 | Per-channel opacity | `Node.get/set_opacity(value, channel)` | Yes | same |
| G3 | Mask-stack (mono) blending | same calls with `channel=None` | Partial | **Hypothesis**: `set_layer_properties` always resolves a channel, which the API rejects for mask-stack nodes; not tested |

## H. Fill sources and procedural content

| # | Capability | Substance API symbol(s) | Exposed by current MCP? | Notes |
|---|---|---|---|---|
| H1 | Uniform color per channel | `set_source(channel, colormanagement.Color)`, `SourceUniformColor` | Yes | `set_fill_base_color` (sRGB input), `set_fill_channels`, recipes (explicit color space per local patch) |
| H2 | Bitmap / resource per channel | `set_source(channel, ResourceID)` → `SourceBitmap`/`SourceSubstance`/… | Yes | `set_fill_resource` |
| H3 | Material mode (one substance → many channels) | `set_material_source`, `get_material_source`, `SourceMode` | Yes | `set_fill_resource(material_mode=true)` |
| H4 | Active channels | `active_channels` | Yes | `set_active_channels` (Fill and Paint) |
| H5 | Substance parameters | `SourceSubstance.get/set_parameters`, `get_properties`, `properties.Property` | Yes | `get_fill_parameters`, `set_fill_parameters` (Fill sources only) |
| H6 | Substance presets | `SourceSubstance.get_preset_list`, `apply_preset` | Yes | `apply_fill_preset` |
| H7 | Substance image inputs | `SourceSubstance.image_inputs`, `get/set/reset/remove_source(identifier)` | Yes | `get_procedural_inputs`, `set_procedural_input` (Fill, Fill effect, Generator, Filter) |
| H8 | Substance output mapping / active output / mask output | `SourceSubstance.output_mapping`, `active_output`, `mask_output`, `image_outputs` | No | |
| H9 | Substance resolution override | `SourceSubstance.resolution`, `ResolutionOverride`, `ResolutionMode` | No | |
| H10 | Bitmap color-space override | `SourceBitmap.get/set/reset_color_space`, `list_available_color_spaces` | Partial | color space reported by `get_procedural_inputs`; not settable |
| H11 | Vector (`.ai`/`.svg`) sources | `SourceVectorial`, `SourceVectorialParams`, `CropAreaMode` | No | |
| H12 | Text / font sources | `SourceFont`, `SourceFontParams`, alignments | No | |
| H13 | Fill presets (`.sppr`) | `set_sources_from_preset` | No | |

## I. Projections and symmetry

| # | Capability | Substance API symbol(s) | Exposed by current MCP? | Notes |
|---|---|---|---|---|
| I1 | Fill / UV / Triplanar projection | `set_projection_mode`, `UVProjectionParams`, `TriplanarProjectionParams` | Yes | `set_fill_projection`, `get_fill_projection` |
| I2 | Planar / Spherical / Cylindrical projection details (culling, crop, filtering, wrap, 3D transform) | `PlanarProjectionParams`, `SphericalProjectionParams`, `CylindricalProjectionParams`, `ProjectionCullingParams`, `Projection3DParams` | Yes | `set_fill_projection_advanced` |
| I3 | UV transform scale / rotation / offset | `UVTransformationParams` | Partial | scale, rotation, offset settable; `scale_mode` (Factors / physical size) only reported |
| I4 | Warp projection | `WarpProjectionParams` | No | warp grid points are not in the API either |
| I5 | UV-set-to-UV-set projection | `UVSetToUVSetProjectionParams` | No | |
| I6 | Mirror / radial symmetry | `set_symmetry_enabled`, `set_symmetry_parameters`, `MirrorSymmetryParams`, `RadialSymmetryParams` | No | |

## J. Smart materials

| # | Capability | Substance API symbol(s) | Exposed by current MCP? | Notes |
|---|---|---|---|---|
| J1 | Apply a smart material | `layerstack.insert_smart_material` | Yes | `insert_smart_material` (top or inside a group) |
| J2 | Create a smart material into a shelf | `layerstack.create_smart_material` | No | |
| J3 | Export a smart material file (`.spsm`) | `layerstack.export_as_smart_material` | Yes | `export_smart_material` |

## K. Resources and shelves

| # | Capability | Substance API symbol(s) | Exposed by current MCP? | Notes |
|---|---|---|---|---|
| K1 | Search resources | `resource.search`, `StandardQuery` | Yes | `search_resources` (type/usage filters) |
| K2 | Resource metadata | `Resource.identifier/type/usages/category/gui_name/tags/internal_properties/children/parent` | Partial | identifiers, type, category, usages |
| K3 | Import into project / session / shelf | `resource.import_project_resource`, `import_session_resource`, `Shelf.import_resource` | Yes | `import_project_resource`, `import_session_resource`, `import_shelf_resource` (approved roots, safe usages) |
| K4 | List resources used by the project | `resource.list_project_resources` | Yes | |
| K5 | Outdated resources and atomic replacement | `list_project_outdated_resources`, `replace_project_resources` | Yes | `find_outdated_resources`, `replace_outdated_resources` (no `allow_parameters_mismatch` input) |
| K6 | Reload modified source files | `reload_modified_resources_async`, filters, events `ReloadResources*` | No | |
| K7 | Shelves: list | `Shelves.all`, `user_shelf`, `application_shelf`, `Shelf.path/can_import_resources/is_crawling` | Yes | `list_shelves` |
| K8 | Shelves: add / remove | `Shelves.add`, `Shelves.remove` | No | |
| K9 | Shelf refresh | `Shelf.refresh`, `Shelves.refresh_all`, events `ShelfCrawlingStarted/Ended` | Yes | `start_shelf_refresh`, `get_shelf_refresh_job` |
| K10 | Custom previews, show in UI | `Resource.set_custom_preview`, `reset_preview`, `show_in_ui`, `show_resources_in_ui` | No | |

## L. Baking

| # | Capability | Substance API symbol(s) | Exposed by current MCP? | Notes |
|---|---|---|---|---|
| L1 | Inspect baking configuration | `baking.BakingParameters.common/baker`, `get_enabled_bakers`, `get_enabled_uv_tiles`, `get_curvature_method`, `is_textureset_enabled` | Yes | `inspect_baking`, `inspect_baking_parameters` (typed metadata, enum labels) |
| L2 | Configure bakers, UV tiles, curvature, any property | `set_enabled_bakers`, `set_baker_enabled`, `set_enabled_uv_tiles`, `set_curvature_method`, `set_textureset_enabled`, `BakingParameters.set` | Yes | `configure_baking` (transactional; file/resource widgets rejected) |
| L3 | High-poly meshes, cage file, low-as-high, cage mode | `common()['HipolyMesh'/'CageMesh'/'LowAsHigh'/'CageMode']` + `BakingParameters.set` | Yes | `set_baking_mesh_inputs` (approved roots) |
| L4 | Resource-typed baking inputs (e.g. `OffsetMap`) | `BakingParameters.set` on Resource widgets | Yes | `set_baking_resource_input` |
| L5 | Link / unlink Texture Sets for baking parameters | `set_linked_group`, `set_linked_group_common_parameters`, `unlink_all`, `unlink_all_common_parameters`, `get_link_group*`, `get_linked_texture_sets*` | Partial | linked sets are reported (`impacted_texture_sets`); linking itself is not editable |
| L6 | Bake one Texture Set | `baking.bake_async` | Yes | `start_bake` |
| L7 | Bake several Texture Sets | `baking.bake_selected_textures_async` | Yes | `start_batch_bake` (preflight, restore enablement, per-map manifest) |
| L8 | Cancel a bake | `async_utils.StopSource.request_stop` | Yes | `cancel_bake` |
| L9 | Bake progress and status | events `BakingProcessAboutToStart/Progress/Ended`, `BakingStatus` | Yes | `get_bake_job` |
| L10 | Portable baking presets | (MCP-level over `BakingParameters`) | Yes | `capture_baking_preset`, `apply_baking_preset` |
| L11 | Auto Rebake, Skew Painting mode | none | N/A | 12.1 UI features without public Python API |

## M. Export

| # | Capability | Substance API symbol(s) | Exposed by current MCP? | Notes |
|---|---|---|---|---|
| M1 | List export presets | `export.list_predefined_export_presets`, `list_resource_export_presets` | Yes | `list_export_presets`, `list_export_profiles` |
| M2 | Preview files to be written | `export.list_project_textures` | Yes | `inspect_export_preset`, `plan_texture_export`, `plan_profile_export` |
| M3 | Read a preset's channel packing | `PredefinedExportPreset.list_output_maps(stack)`, `ResourceExportPreset.list_output_maps()` | No | |
| M4 | Export with a named preset | `export.export_project_textures` with `defaultExportPreset` | Yes | `export_textures`, `export_with_profile` (approved roots, overwrite guard, file verification) |
| M5 | Inline / custom presets and channel packing | `exportPresets[].maps[].channels` | No | |
| M6 | Global size, format, bit depth | `exportParameters[].parameters.sizeLog2/fileFormat/bitDepth` | Yes | one global rule; formats limited to png, tga, jpg/jpeg, tif/tiff, exr, bmp |
| M7 | Padding algorithm, dilation distance, dithering | `paddingAlgorithm`, `dilationDistance`, `dithering` | Partial | fixed to `infinite` padding and dithering on; no dilation control |
| M8 | Per-Texture-Set / per-map / per-tile parameter rules | `exportParameters[].filter.dataPaths/outputMaps/uvTiles` | No | |
| M9 | Export subsets (maps, UV tiles) | `exportList[].filter.outputMaps/uvTiles` | No | Texture-Set selection only |
| M10 | Stacks of layered materials (`TextureSet/Stack` root paths) | `exportList[].rootPath` | No | root paths are Texture Set names |
| M11 | Shader-parameter JSON | `exportShaderParams` | No | always `false` |
| M12 | USD export | `exportUSD` (undocumented key) | No | |
| M13 | Mesh export | `export.export_mesh`, `MeshExportOption`, `scene_is_triangulated`, `scene_has_tessellation` | No | |
| M14 | Default export path | `export.get_default_export_path` | No | |
| M15 | Export events | `ExportTexturesAboutToStart`, `ExportTexturesEnded` | No | |
| M16 | Export a single layer node's texture | private `_substance_painter.export.export_stack_node_texture` | N/A | not public |

## N. Display, camera and UI

| # | Capability | Substance API symbol(s) | Exposed by current MCP? | Notes |
|---|---|---|---|---|
| N1 | Environment map | `display.get/set_environment_resource` | No | |
| N2 | Color LUT | `display.get/set_color_lut_resource` | No | |
| N3 | Tone mapping | `display.get/set_tone_mapping`, `ToneMappingFunction` | No | |
| N4 | Camera | `display.Camera` (position, rotation, FOV, focal length, focus distance, aperture, orthographic height, projection type), event `CameraPropertiesChanged` | No | |
| N5 | Shader / material instance parameters | JS only (`alg.shaders.*`) | No | not in the Python API |
| N6 | Viewport capture | private `_substance_painter.display.save_viewport` | N/A | not public |
| N7 | UI modes, layouts, docks, menus, toolbars | `ui.*` | No | |
| N8 | Texture update notifications | event `TextureStateEvent` (+ throttling period), `LayerStacksModelDataChanged` | No | |

## O. Color management

| # | Capability | Substance API symbol(s) | Exposed by current MCP? | Notes |
|---|---|---|---|---|
| O1 | Colors with explicit color space and conversion | `colormanagement.Color`, `GenericColorSpace`, `LegacyColorSpace`, `DataColorSpace`, `NormalColorSpace`, `Color.convert/sRGB/working` | Partial | MCP converts sRGB input for BaseColor and sets explicit spaces in recipes (local patch); no general conversion tool |
| O2 | OCIO / ACE color-space strings | `ColorColorSpace`/`ResourceColorSpace` as `str` | No | |

## Totals (computed from the rows above)

| Status | Rows |
|---|---|
| Yes | 59 |
| Partial | 24 |
| No | 51 |
| N/A | 6 |
| **Total** | **140** |

Counts computed by parsing this file's rows (**Fact**). The count measures rows, not importance; several "No" rows (e.g. M5 custom channel packing, D5 instances, C11 channel editing) and several "Yes" rows are MCP-level compositions of the same Painter calls.
