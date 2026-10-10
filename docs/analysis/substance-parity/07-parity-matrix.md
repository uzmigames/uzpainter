# 07 — Substance 3D Painter capability parity matrix (as of 2026-10-10)

One row per capability: the Substance 3D Painter 12.1.0 Python API symbols that provide it, and whether the current SubstancePainterMCP 1.0.0 bridge (with the local patch) exposes it. This matrix records facts only; it does **not** decide what UzPainter will include — that is the architect's call.

## Conventions

- Symbols are relative to `substance_painter` (e.g. `layerstack.insert_fill`); full signatures in `01-python-api-inventory.md`; behaviour in files 02–05; MCP details in `06-mcp-tools-inventory.md`.
- "Exposed by current MCP?": **Yes** = a dedicated tool covers it; **Partial** = covered with limits stated in Notes ("composed" = reached by chaining named tools); **No** = no named tool for the stated operation (reachable only through the opt-in `execute_python`, where the public API allows it); **N/A** = Painter has no public Python API for it either.
- Scope of a status (revised after the technical review, `08-review-response.md`): it describes the *named* MCP route for the operation stated in the row, from static reading of the sources — not a live run and not Painter's product capability (a **No** or **N/A** never means Painter cannot do it). Public Python API, raw `execute_python`, raw JavaScript, private APIs and composed named operations are different surfaces. Rows overlap (application/jobs; project creation/settings; Texture Set read/write/tiles; channel listing/editing; layer insertion/recipes; effect location/kind; uniform colours/colour management; projections; import/shelves; baking configuration/presets; export presets/packing/rules) and some bundle several operations, so the totals count rows, not independent features.
- Every row is a **Fact** derived from the shipped Painter sources (`C:\Program Files\Adobe\Adobe Substance 3D Painter\resources\python\modules\substance_painter\*.py`, `resources\python-doc\`) and the MCP sources (`E:\UzmiGames\Assets3D\Tools\SubstancePainterMCP\src\substance_painter_mcp\operations.py`, `server.py`, `tool-schema.json`), unless the Notes say **Hypothesis** or "not confirmed". In Notes, `OPS:n` / `SRV:n` = line n of `operations.py` / `server.py`; `layerstack.py`, `textureset.py` = Painter's shipped wrappers; `06` §9 = the known-bridge-defects table.

## A. Application, scripting and events

| # | Capability | Substance API symbol(s) | Exposed by current MCP? | Notes |
|---|---|---|---|---|
| A1 | Query application / API version | `application.version`, `application.version_info`, `substance_painter.__version__` | Partial | `painter_status` uses JS `alg.version.painter` and `__version__`; `_version.py` declares 0.3.5 (static); the MCP author reports the runtime returning 0.3.5 on 12.1.1 (second-hand); the installed build is 12.1.0 |
| A2 | Feature detection at runtime | `hasattr` on API symbols | Partial | `get_capabilities` reports `hasattr` presence, not verified behaviour; its `baking_presets` flag is a false negative (`OPS:604`; `BakingParameters` has no `get`) |
| A3 | Enable/disable engine computations (batch edits without recompute) | `application.enable_engine_computations`, `disable_engine_computations`, `engine_computations_status`; event `EngineComputationsStatusChanged` | No | |
| A4 | Close the application | `application.close` | No | |
| A5 | Write to the Painter log | `logging.log/info/warning/error` | No | |
| A6 | Plugin management | `substance_painter_plugins.*` | No | |
| A7 | Run arbitrary Python in Painter | remote scripting `/run.json` (not part of the Python API docs) | Yes | `execute_python`: always registered, refused at invocation unless `SP_MCP_ALLOW_EXECUTE_PYTHON=1` (`SRV:814–822`); the pipeline client passes an inherited `1` through to `batch` mode |
| A8 | Call the legacy JavaScript API | `js.evaluate` | No | no named JS tool; the MCP calls two JS expressions internally only; an enabled `execute_python` can call `js.evaluate` (raw route) |
| A9 | Subscribe to events | `event.DISPATCHER.connect/connect_strong/disconnect`, 27 event classes | Partial | used internally for bake, project-creation and shelf-refresh jobs (mesh reload uses a `reload_mesh` completion callback instead); no generic subscription tool |
| A10 | Wait until not busy | `project.is_busy`, `project.execute_when_not_busy`, event `BusyStatusChanged` | Partial | busy state is read and polled by job/plan tools; no named wait or `execute_when_not_busy` route |

## B. Project lifecycle

| # | Capability | Substance API symbol(s) | Exposed by current MCP? | Notes |
|---|---|---|---|---|
| B1 | Create a project from a mesh (+ template, pre-baked mesh maps) | `project.create`, `project.Settings` | Yes | `plan_project_creation`, `create_project` (async job, backup of the current project, saves in Full mode) |
| B2 | Normal-map format, tangent space, UDIM workflow, default resolution, cameras, unit scale | `project.Settings` fields, `NormalMapFormat`, `TangentSpace`, `ProjectWorkflow` | Yes | via the `settings` object of `create_project`: creation-time settings; editing them on an existing project is a different operation, not exposed |
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
| B13 | Project state (open, dirty, name, path) | `project.is_open`, `needs_saving`, `name`, `file_path`, `is_in_edition_state` | Partial | `get_project_info` returns open/name/path/Texture Sets; dirty state (`needs_saving`) only through plan tools; `is_in_edition_state` is not used |
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
| C8 | Material-layering stacks | `TextureSet.all_stacks`, `get_stack`, `is_layered_material`, `Stack.from_name` | Partial | `audit_project` lists stacks; layer tools address the UI active stack or `TextureSet.get_stack()` with the empty name (`OPS:2011–2012`), which raises `ValueError` when no stack is unnamed (`textureset.py:1026–1030`); no explicit stack argument |
| C9 | Active stack | `textureset.get_active_stack`, `set_active_stack` | Partial | read only |
| C10 | List channels | `Stack.all_channels`, `Channel.type/format/label` | Partial | `audit_project` returns channel type names only (`OPS:643`), not `Channel.format`/`label`; `get_capabilities` lists all channel types |
| C11 | Add / remove / edit channels (format, user label) | `Stack.add_channel`, `remove_channel`, `edit_channel`, `Channel.edit`, `ChannelFormat` | No | |
| C12 | Mesh-map slots | `TextureSet.get_mesh_map_resource`, `set_mesh_map_resource`, `MeshMapUsage` | Partial | read only (`inspect_baking`, `preflight_bake`) |

## D. Layer-stack structure and editing

| # | Capability | Substance API symbol(s) | Exposed by current MCP? | Notes |
|---|---|---|---|---|
| D1 | Traverse the stack | `layerstack.get_root_layer_nodes`, `GroupLayerNode.sub_layers`, `LayerNode.content_effects`, `mask_effects`, `Node.get_parent/...` | Yes | `list_layers`, `find_layers`, `snapshot_layer_tree`, `list_anchor_points`; one stack per call (UI active or empty-name stack); no parent/sibling queries |
| D2 | Resolve a node by uid | `layerstack.get_node_by_uid`, `Node.uid` | Yes | edits of existing nodes take uids; creation tools take names plus a Texture Set or parent context |
| D3 | Insert fill / paint / group layers | `layerstack.insert_fill`, `insert_paint`, `insert_group`, `InsertPosition.from_textureset_stack`, `inside_node(…, NodeStack.Substack)` | Yes | `create_fill_layer`, `create_paint_layer`, `create_group` (top of stack), `create_layer_recipe` (nested) |
| D4 | Insert above/below a given node | `InsertPosition.above_node`, `below_node` | No | tools insert at stack top or inside a group only |
| D5 | Layer instances | `layerstack.instantiate`, `LayerNode.instances`, `InstanceLayerNode.instance_source` | No | |
| D6 | Delete a node | `layerstack.delete_node` | Yes | `delete_layer` |
| D7 | Rename, visibility | `Node.set_name`, `Node.set_visible` | Yes | `rename_layer`, `set_layer_properties`; on a mask-stack node `set_layer_properties` applies `visible` and then fails on its blend readback (`OPS:3718–3731`) |
| D8 | Group collapse state | `GroupLayerNode.set_collapsed` | No | collapse state is read (`snapshot_layer_tree`), never written |
| D9 | Move / reorder / duplicate existing nodes | none | N/A | MCP `move_layer` deliberately not implemented |
| D10 | Undo grouping / single recompute | `layerstack.ScopedModification` | No | |
| D11 | Selection | `layerstack.set_selected_nodes`, `get_selected_nodes`, `get/set_selection_type`, `SelectionType` | Partial | `select_layers` (no selection type) |
| D12 | Multi-node creation with rollback on failure | (MCP-level composition of the insert APIs) | Partial | `plan_layer_recipe`, `create_layer_recipe`: best-effort cleanup that suppresses deletion errors, no native transaction, optional backup not restored automatically (`OPS:2425–2433`); not atomic |
| D13 | Structural snapshot and diff | (MCP-level) | Yes | `snapshot_layer_tree`, `diff_layer_snapshots`: structure only (names, types, visibility, masks, effect lists, geometry masks, Fill-layer active channels, collapse); sources, parameters, per-channel blend/opacity, projections and Paint-layer channels are not captured, so equal snapshots do not prove equal material output |
| D14 | Paint strokes (read/write) | none ("Strokes are not accessible from the Python API") | N/A | N/A for the public Python surface only; painting output stays relevant to product parity |
| D15 | Material-output (semantic) snapshot: sources, parameters, per-channel blending, projections, masks, colour spaces | (MCP-level) | No | D13 is structural only; no route captures the material-producing values needed for output comparison |

## E. Effects

| # | Capability | Substance API symbol(s) | Exposed by current MCP? | Notes |
|---|---|---|---|---|
| E1 | Effects in a layer's content stack | `InsertPosition.inside_node(layer, NodeStack.Content)` + insert functions | Partial | no named insertion into `NodeStack.Content`; existing content effects are listed (`snapshot_layer_tree`) and the procedural image inputs of content Fill/Generator/Filter effects are editable by uid (`get/set_procedural_input`) |
| E2 | Fill effect in a mask (with resource) | `insert_fill`, `FillEffectNode.set_source(None, res)`, `set_projection_mode` | Yes | `insert_mask_effect` (resource assignment and UV projection added by the local patch); insertion only — an existing mask Fill cannot be edited afterwards (`get/set_procedural_input` fail, `06` §9) |
| E3 | Paint effect in a mask | `insert_paint` | Yes | `insert_mask_effect` |
| E4 | Generator effect | `insert_generator_effect`, `GeneratorEffectNode.get/set/remove_source`, `active_channels` | Partial | insertion in a mask stack only (optional resource at insertion); image inputs of an existing effect editable by uid via `set_procedural_input`; main-graph replacement/removal on an existing effect and graph parameters not exposed (`set_fill_parameters` is Fill-layer only) |
| E5 | Filter effect | `insert_filter_effect`, `FilterEffectNode.*` | Partial | same limits as E4 |
| E6 | Levels effect | `insert_levels_effect`, `LevelsEffectNode.affected_channel`, `get/set_parameters`, `levels.LevelsParamsMono/RGB` | Partial | insertion in mask only; parameters not editable |
| E7 | Compare Mask effect | `insert_compare_mask_effect`, `CompareMaskEffectParams` | No | |
| E8 | Color Selection (ID-map) effect | `insert_color_selection_effect`, `ColorSelectionEffectParams` | No | |
| E9 | Anchor points | `insert_anchor_point_effect`, `AnchorPointEffectNode` | Partial | insert in mask (`insert_mask_effect`), list (`list_anchor_points`) |
| E10 | Reference an anchor as a source | `set_source(channel, anchor)`, `set_material_source(anchor)`, `SourceReference.channel_mapping/referenced_channel/alpha_matte/get_levels/set_levels` | Partial | `set_fill_anchor_source` binds (Fill layers only); mapping, referenced channel, alpha matte and levels not editable |
| E11 | Replace or remove the main graph of an existing Generator/Filter effect | `GeneratorEffectNode.set_source(res)`, `remove_source`; `FilterEffectNode.set_source(res)`, `remove_source` | No | the resource is set only at insertion (`OPS:2495`, `2497`) |
| E12 | Edit existing Fill effects (sources, parameters, projection, symmetry) | `FillEffectNode` mixin members (`set_source`, `set_material_source`, `set_projection_mode/parameters`, `set_symmetry_*`) | Partial | content Fill effects: procedural image inputs only (`set_procedural_input`); mask Fill effects: none (route broken, `06` §9); projection and parameter tools reject `FillEffectNode` (`OPS:2665`, `2734`, `2800`, `3261`) |

## F. Masks

| # | Capability | Substance API symbol(s) | Exposed by current MCP? | Notes |
|---|---|---|---|---|
| F1 | Add / remove / change mask background | `LayerNode.add_mask`, `remove_mask`, `set_mask_background`, `MaskBackground` | Yes | `set_layer_mask`: `enabled=false` removes the mask with its effects (`remove_mask`); it does not disable it |
| F2 | Enable / disable a mask | `LayerNode.enable_mask`, `is_mask_enabled` | Partial | only through recipe `mask.enabled` at creation (`enable_mask(False)`, `OPS:2414`); `set_layer_mask(enabled=false)` removes the mask instead |
| F3 | Apply a smart mask | `layerstack.insert_smart_mask` | Yes | `apply_smart_mask` (local patch hunk 4 does not apply to it) |
| F4 | Create a smart mask into a shelf | `layerstack.create_smart_mask` | Partial | composed: `export_smart_mask` writes an `.spmsk`, then `import_shelf_resource` (usage `SMART_MASK`, approved roots) adds it to a shelf; no direct `create_smart_mask` wrapper |
| F5 | Export a smart mask file (`.spmsk`) | `layerstack.export_as_smart_mask` | Yes | `export_smart_mask` |
| F6 | Geometry masks (mesh / UV tile, include / exclude) | `LayerNode.get/set_geometry_mask`, `GeometryMaskMeshParams`, `GeometryMaskUVTilesParams` | Yes | `get_geometry_mask`, `set_geometry_mask` (UDIM numbers converted to tiles) |

## G. Blending

| # | Capability | Substance API symbol(s) | Exposed by current MCP? | Notes |
|---|---|---|---|---|
| G1 | Per-channel blend mode | `Node.get/set_blending_mode(mode, channel)`, `BlendingMode` (32 modes) | Yes | `set_layer_properties` (channel defaults to BaseColor); only for nodes outside a mask stack that carry blending |
| G2 | Per-channel opacity | `Node.get/set_opacity(value, channel)` | Yes | same as G1 |
| G3 | Mask-stack (mono) blending | same calls with `channel=None` | No | `set_layer_properties` always passes a `ChannelType` (`OPS:3714–3731`) while the API requires `None` in a mask stack (`layerstack.py:726–798`): every call fails (static analysis, `06` §9); reachable only through `execute_python` |

## H. Fill sources and procedural content

| # | Capability | Substance API symbol(s) | Exposed by current MCP? | Notes |
|---|---|---|---|---|
| H1 | Uniform color per channel | `set_source(channel, colormanagement.Color)`, `SourceUniformColor` | Yes | `set_fill_base_color` (sRGB input), `set_fill_channels`, recipes (explicit color space per local patch); components limited to 0..1 (`OPS:5060`), so normalized colors only |
| H2 | Bitmap / resource per channel | `set_source(channel, ResourceID)` → `SourceBitmap`/`SourceSubstance`/… | Yes | `set_fill_resource` (Fill layers only) |
| H3 | Material mode (one substance → many channels) | `set_material_source`, `get_material_source`, `SourceMode` | Yes | `set_fill_resource(material_mode=true)` (Fill layers only) |
| H4 | Active channels | `active_channels` | Partial | `set_active_channels` works on Fill layers; on Paint layers it reports success without native effect (`06` §9); Fill/Generator/Filter effects rejected; an empty set is rejected |
| H5 | Substance parameters | `SourceSubstance.get/set_parameters`, `get_properties`, `properties.Property` | Partial | `get_fill_parameters`, `set_fill_parameters`: sources of Fill layers only — not Fill effects, Generator or Filter effects |
| H6 | Substance presets | `SourceSubstance.get_preset_list`, `apply_preset` | Partial | `apply_fill_preset`: Fill layers only |
| H7 | Substance image inputs | `SourceSubstance.image_inputs`, `get/set/reset/remove_source(identifier)` | Partial | `get_procedural_inputs`, `set_procedural_input`: resource assignment and reset on Fill layers, content Fill effects, Generator and Filter effects; broken on mask-stack Fill effects (`OPS:2945`, `3041`); no Color/anchor input binding; no `remove_source` |
| H8 | Substance output mapping / active output / mask output | `SourceSubstance.output_mapping`, `active_output`, `mask_output`, `image_outputs` | No | |
| H9 | Substance resolution override | `SourceSubstance.resolution`, `ResolutionOverride`, `ResolutionMode` | No | |
| H10 | Bitmap color-space override | `SourceBitmap.get/set/reset_color_space`, `list_available_color_spaces` | No | no call to `get/set/reset_color_space` or `list_available_color_spaces`; `get_procedural_inputs` reports a color space only for uniform-color sources |
| H11 | Vector (`.ai`/`.svg`) sources | `SourceVectorial`, `SourceVectorialParams`, `CropAreaMode` | No | `set_fill_resource` does not restrict the resource type (`OPS:3151–3191`), so binding a vector resource is not blocked (not confirmed); `SourceVectorialParams` editing absent |
| H12 | Text / font sources | `SourceFont`, `SourceFontParams`, alignments | No | same as H11 for fonts (FONT import is allowed); `SourceFontParams` editing absent |
| H13 | Fill presets (`.sppr`) | `set_sources_from_preset` | No | |
| H14 | Reset / remove sources; source-mode transitions | `reset_source(channel)`, `reset_material_source`, `SourceSubstance.reset_source/remove_source(identifier)`, `SourceMode` | Partial | only `SourceSubstance.reset_source(identifier)` via `set_procedural_input(reset=true)`; Fill channel reset, material-source reset and input removal absent; Split→Material only implicitly through `set_fill_resource(material_mode=true)` |

## I. Projections and symmetry

| # | Capability | Substance API symbol(s) | Exposed by current MCP? | Notes |
|---|---|---|---|---|
| I1 | Fill / UV / Triplanar projection | `set_projection_mode`, `UVProjectionParams`, `TriplanarProjectionParams` | Yes | `set_fill_projection`, `get_fill_projection` (Fill layers only; Fill effects rejected, `OPS:2665`, `2734`) |
| I2 | Planar / Spherical / Cylindrical projection details (culling, crop, filtering, wrap, 3D transform) | `PlanarProjectionParams`, `SphericalProjectionParams`, `CylindricalProjectionParams`, `ProjectionCullingParams`, `Projection3DParams` | Yes | `set_fill_projection_advanced` (Fill layers only, `OPS:2800`) |
| I3 | UV transform scale / rotation / offset | `UVTransformationParams` | Partial | scale, rotation, offset settable; `scale_mode` (Factors / physical size) only reported |
| I4 | Warp projection | `WarpProjectionParams` | No | warp grid points are not in the API either |
| I5 | UV-set-to-UV-set projection | `UVSetToUVSetProjectionParams` | No | |
| I6 | Mirror / radial symmetry | `set_symmetry_enabled`, `set_symmetry_parameters`, `MirrorSymmetryParams`, `RadialSymmetryParams` | No | |

## J. Smart materials

| # | Capability | Substance API symbol(s) | Exposed by current MCP? | Notes |
|---|---|---|---|---|
| J1 | Apply a smart material | `layerstack.insert_smart_material` | Yes | `insert_smart_material` (top or inside a group) |
| J2 | Create a smart material into a shelf | `layerstack.create_smart_material` | Partial | composed: `export_smart_material` writes an `.spsm`, then `import_shelf_resource` (usage `SMART_MATERIAL`, approved roots) adds it to a shelf; no direct `create_smart_material` wrapper |
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
| K9 | Shelf refresh | `Shelf.refresh`, `Shelves.refresh_all`, events `ShelfCrawlingStarted/Ended` | Partial | `start_shelf_refresh`, `get_shelf_refresh_job` call `Shelf.refresh` for one shelf; `Shelves.refresh_all` is not wrapped |
| K10 | Custom previews, show in UI | `Resource.set_custom_preview`, `reset_preview`, `show_in_ui`, `show_resources_in_ui` | No | |

## L. Baking

| # | Capability | Substance API symbol(s) | Exposed by current MCP? | Notes |
|---|---|---|---|---|
| L1 | Inspect baking configuration | `baking.BakingParameters.common/baker`, `get_enabled_bakers`, `get_enabled_uv_tiles`, `get_curvature_method`, `is_textureset_enabled` | Yes | `inspect_baking`, `inspect_baking_parameters` (typed metadata, enum labels) |
| L2 | Configure bakers, UV tiles, curvature, any property | `set_enabled_bakers`, `set_baker_enabled`, `set_enabled_uv_tiles`, `set_curvature_method`, `set_textureset_enabled`, `BakingParameters.set` | Yes | `configure_baking` (best-effort rollback, `OPS:989–1001`; File/FileList/Resource widgets rejected here and covered by L3/L4) |
| L3 | High-poly meshes, cage file, low-as-high, cage mode | `common()['HipolyMesh'/'CageMesh'/'LowAsHigh'/'CageMode']` + `BakingParameters.set` | Yes | `set_baking_mesh_inputs` (approved roots) |
| L4 | Resource-typed baking inputs (e.g. `OffsetMap`) | `BakingParameters.set` on Resource widgets | Yes | `set_baking_resource_input` |
| L5 | Link / unlink Texture Sets for baking parameters | `set_linked_group`, `set_linked_group_common_parameters`, `unlink_all`, `unlink_all_common_parameters`, `get_link_group*`, `get_linked_texture_sets*` | Partial | linked sets are reported (`impacted_texture_sets`); linking itself is not editable |
| L6 | Bake one Texture Set | `baking.bake_async` | Yes | `start_bake` |
| L7 | Bake several Texture Sets | `baking.bake_selected_textures_async` | Yes | `start_batch_bake` (preflight, restore enablement, per-map manifest) |
| L8 | Cancel a bake | `async_utils.StopSource.request_stop` | Yes | `cancel_bake` |
| L9 | Bake progress and status | events `BakingProcessAboutToStart/Progress/Ended`, `BakingStatus` | Yes | `get_bake_job` |
| L10 | Portable baking presets | (MCP-level over `BakingParameters`) | Yes | `capture_baking_preset`, `apply_baking_preset` (they work although `get_capabilities` reports `baking_presets` false) |
| L11 | Auto Rebake, Skew Painting mode | none | N/A | 12.1 UI features without public Python API (N/A for the API surface only) |

## M. Export

| # | Capability | Substance API symbol(s) | Exposed by current MCP? | Notes |
|---|---|---|---|---|
| M1 | List export presets | `export.list_predefined_export_presets`, `list_resource_export_presets` | Yes | `list_export_presets`, `list_export_profiles` |
| M2 | Preview files to be written | `export.list_project_textures` | Yes | `inspect_export_preset`, `plan_texture_export`, `plan_profile_export` |
| M3 | Read a preset's channel packing | `PredefinedExportPreset.list_output_maps(stack)`, `ResourceExportPreset.list_output_maps()` | No | |
| M4 | Export with a named preset | `export.export_project_textures` with `defaultExportPreset` | Yes | `export_textures`, `export_with_profile`: predefined or shelf preset by name or URL, one global parameter rule (`OPS:3816–3839`); approved roots, overwrite guard, file verification |
| M5 | Inline / custom presets and channel packing | `exportPresets[].maps[].channels` | No | no inline preset definition or packing editor; existing resource/URL presets are accepted (M4) |
| M6 | Global size, format, bit depth | `exportParameters[].parameters.sizeLog2/fileFormat/bitDepth` | Partial | one global rule: scalar `sizeLog2` 5..14 (no `[w, h]`); formats png, tga, jpg/jpeg, tif/tiff, exr, bmp; bit depths `8`/`16`/`32` only — Adobe's float names `16f`/`32f` are rejected (`OPS:3791–3798`) |
| M7 | Padding algorithm, dilation distance, dithering | `paddingAlgorithm`, `dilationDistance`, `dithering` | Partial | fixed by the bridge to `infinite` padding and dithering on (bridge choices, not user controls); no dilation control |
| M8 | Per-Texture-Set / per-map / per-tile parameter rules | `exportParameters[].filter.dataPaths/outputMaps/uvTiles` | No | |
| M9 | Export subsets (maps, UV tiles) | `exportList[].filter.outputMaps/uvTiles` | No | Texture-Set selection only |
| M10 | Stacks of layered materials (`TextureSet/Stack` root paths) | `exportList[].rootPath` | Partial | `texture_sets` strings are passed unchanged as `rootPath` (`OPS:3836`), so a `TextureSet/Stack` path is not blocked, but there is no stack picker or validation (not run) |
| M11 | Shader-parameter JSON | `exportShaderParams` | No | always `false` |
| M12 | USD export | undocumented key ([Redacted under the clean-room policy (docs/licensing-and-clean-room.md). Source withheld: C:\Program Files\Adobe\Adobe Substance 3D Painter\resources\python\modules\engine_tests\test_usd_openpbr_roundtrip.py.]) | No | undocumented; not a supported contract |
| M13 | Mesh export | `export.export_mesh`, `MeshExportOption`, `scene_is_triangulated`, `scene_has_tessellation` | No | |
| M14 | Default export path | `export.get_default_export_path` | No | |
| M15 | Export events | `ExportTexturesAboutToStart`, `ExportTexturesEnded` | No | |
| M16 | Export a single layer node's texture | private API ([Redacted under the clean-room policy (docs/licensing-and-clean-room.md). Source withheld: C:\Program Files\Adobe\Adobe Substance 3D Painter\resources\python\modules\engine_tests\test_export_layerstack_nodes.py.]) | N/A | not public |
| M17 | File-name tokens (`$project`, `$mesh`, `$textureSet`, `$sceneMaterial`, `$udim`, `$uvTileName`, `$colorSpace`) | `exportPresets[].maps[].fileName` | Partial | only as defined by the chosen preset; no file-name template input |
| M18 | Derived map sources and normal convention (virtual, mesh, constant maps; `Normal_OpenGL`/`Normal_DirectX`, `AO_Mixed`, `Glossiness`, `f0`) | `srcMapType` `virtualMap`/`meshMap`/`defaultMap`, `srcMapName` | Partial | only as defined by the chosen preset; the preset's normal convention is a separate setting from the project's `NormalMapFormat` (B2) |
| M19 | Per-root export preset | `exportList[].exportPreset` | No | one `defaultExportPreset` for every root (`OPS:3832–3837`) |

## N. Display, camera and UI

| # | Capability | Substance API symbol(s) | Exposed by current MCP? | Notes |
|---|---|---|---|---|
| N1 | Environment map | `display.get/set_environment_resource` | No | |
| N2 | Color LUT | `display.get/set_color_lut_resource` | No | |
| N3 | Tone mapping | `display.get/set_tone_mapping`, `ToneMappingFunction` | No | |
| N4 | Camera | `display.Camera` (position, rotation, FOV, focal length, focus distance, aperture, orthographic height, projection type), event `CameraPropertiesChanged` | No | |
| N5 | Shader / material instance parameters | JS only (`alg.shaders.*`) | No | JS only (`alg.shaders.*`), not in the Python API; reachable from Python through `js.evaluate` |
| N6 | Viewport capture | private `_substance_painter.display.save_viewport` | N/A | not public |
| N7 | UI modes, layouts, docks, menus, toolbars | `ui.*` | No | |
| N8 | Texture update notifications | event `TextureStateEvent` (+ throttling period), `LayerStacksModelDataChanged` | No | |

## O. Color management

| # | Capability | Substance API symbol(s) | Exposed by current MCP? | Notes |
|---|---|---|---|---|
| O1 | Colors with explicit color space and conversion | `colormanagement.Color`, `GenericColorSpace`, `LegacyColorSpace`, `DataColorSpace`, `NormalColorSpace`, `Color.convert/sRGB/working` | Partial | route-specific: `set_fill_base_color` converts sRGB input for BaseColor, recipes set explicit spaces (local patch), other setters keep the implicit color-space behaviour; no general conversion tool |
| O2 | OCIO / ACE color-space strings | `ColorColorSpace`/`ResourceColorSpace` as `str` | No | reporting a `Color`'s space string is not selection or conversion |

## Totals (computed from the rows above)

| Status | Rows |
|---|---|
| Yes | 49 |
| Partial | 40 |
| No | 52 |
| N/A | 6 |
| **Total** | **147** |

Counts computed by parsing this file's rows (**Fact**); before the review the matrix had 140 rows (59 Yes, 24 Partial, 51 No, 6 N/A); rows D15, E11, E12, H14, M17, M18, M19 were added and 16 rows were reclassified (see `08-review-response.md`). The count measures rows, not importance; several "No" rows (e.g. M5 custom channel packing, D5 instances, C11 channel editing) and several "Yes" rows are MCP-level compositions of the same Painter calls.
