# 110. The host behaviour Painter has not been recorded doing is a named gap with the recording that settles it

**Status**: accepted
**Date**: 2026-10-12
**Related Tasks**: phase1.21_pyapi-dispatcher-lifecycle, phase1.20_pyapi-facade, phase1.24_python-api-facade, phase1.22_pyapi-cli-capabilities, phase2.3_realtime-preview, phase3.3_procedural-families, phase3.5_embree-bakers

## Context

Decision 109 fixes the host behaviours that the Tier 0 probes record. Task phase1.21 also asks for behaviours no golden records yet, and phase1.20 handed it the `create` arguments the native project did not take.

- **Engine computations.** Nothing records them: `phase1-engine-computations` is still a request. Its runbook warns that an export with computations disabled may never return in Painter. The task requires an explicit state: not a no-op, a deferred backlog that `is_busy()` reports, and `EngineComputationsStatusChanged`.
- **Export events.** `ExportTexturesAboutToStart` and `ExportTexturesEnded` have no recorded place relative to the busy pair.
- **`create` arguments.**
  - Only two mesh-map file-name suffixes are documented, in an example. Painter's rule for binding a map file to a texture set and usage is unrecorded.
  - A UzPainter project does not record its template, so a non-default template would export with the default template's base values.
  - No recording shows what reads `Settings.default_save_path` or `export_path`.
- **Shelves.** Painter's application and user shelf names are unrecorded, and so are its crawl timing and its shelf resources. Shelf resources are procedural content.
- **`LayerStacksModelDataChanged`** is recorded only for `insert_fill`, `insert_group`, `set_name`, `delete_node` and `add_mask` (emitting), and for `active_channels`, `set_source`, `import_project_resource` and `update_layer_stack_resource` (silent).
- **`TextureStateEvent`'s throttling period**: Painter's default is unrecorded.
- **Resource reload after save and reopen.** In `phase1-reload-resources`, recording 2, Painter reports reloads of bytes the project already holds (old = new version). Recording 1 is consistent with "the file's bytes match none of the versions its name holds".
- **`MeshReloadingSettings.preserve_strokes`** is documented. Brush strokes are out of scope, and no stroke symbol may exist (decision 019).

The model panel (decision 109's round):
- **C5, the create gaps.** AGREE ×3.
- **C6, the engine computations.** DISAGREE, PARTLY, AGREE: name the whole disabled-computation behaviour as pending its recording, not only the event order.
- **C7, shelves.** PARTLY, AGREE, AGREE: name the crawl timing.
- **C8, the reload residual.** PARTLY, AGREE, PARTLY: a named residual is acceptable.
- **C9, LayerStacksModelDataChanged.** PARTLY, PARTLY, AGREE: name each unrecorded call.

## Decision

1. **Engine computations.** The state lives in the native module: `uzpainter.application.enable_engine_computations`, `engine_computations_status` and `disable_engine_computations()`.
   - While computations are disabled, the job worker starts no queued job.
   - A facade export waits, inside its busy section, so `is_busy()` reports the backlog until it drains after re-enabling.
   - Each change delivers `EngineComputationsStatusChanged(enabled)`.
   - This whole behaviour is UzPainter's implementation of the task's contract, pending recording `phase1-engine-computations`. That recording also places the export events, which the facade delivers between the busy pair.
2. **`create`.**
   - `mesh_map_file_paths` raises `NotYetSupported` naming recording **P21-A**.
   - `template_file_path` raises `NotYetSupported` naming phase1.24_python-api-facade, until projects record their template and exports read it.
   - `Settings.default_save_path` and `export_path` raise `NotYetSupported` naming recording **P21-B**.
3. **Shelves.**
   - Script-defined shelves (`Shelves.add/all/exists/remove/refresh_all`, `Shelf.name/path/refresh/is_crawling`) crawl their folder on a worker thread between `ShelfCrawlingStarted` and `ShelfCrawlingEnded`. The timing is named for recording **P21-D**.
   - `Shelves.application_shelf` and `user_shelf` raise `NotYetSupported` (P21-D).
   - `Shelf.resources`, `import_resource` and `can_import_resources` raise `NotYetSupported` (phase3.3_procedural-families).
4. **`LayerStacksModelDataChanged`** is delivered by the five recorded emitting calls only. Every other edit call emits nothing until recording **P21-E** shows otherwise: `insert_paint`, `insert_levels_effect`, `insert_compare_mask_effect`, `insert_color_selection_effect`, `insert_anchor_point_effect`, `instantiate`, `set_visible`, `set_blending_mode`, `set_opacity`, `remove_mask`, `set_mask_background`, `enable_mask`, `reset_source`, `set_projection_mode`, `set_projection_parameters`, `set_symmetry_enabled`, `set_material_source`, `affected_channel`, `LevelsEffectNode.set_parameters`, `SourceUniformColor.set_color` and the `SourceBitmap` colour-space setters.
5. **`TextureStateEvent`** reads back the throttling period a script set; before that it raises `NotYetSupported` naming recording **P21-C**. `TextureStateEvent` and `CameraPropertiesChanged` are emitted by phase2.3_realtime-preview, and the bake events by phase3.5_embree-bakers. All of them are connectable now.
6. **Resource reload.** A resource is modified when its file's bytes match none of the versions its name holds. The two outputs of recording 2 (s9, s12) are a named exclusion in `test_pyapi_lifecycle_tier0.py`, which requires them to still differ. In recording 1 the facade refuses s6's grey bitmap on BaseColor (decision 107, P20-A), so s9 and s12 are excluded by name too. `test_pyapi_dispatcher.py` tests the same reload on a bound colour bitmap.
7. **`preserve_strokes`** is accepted by `MeshReloadingSettings` and kept in a private slot. It has nothing to act on, and no stroke symbol is public.

## Recordings this decision names (not recorded; owner action)

- **`phase1-engine-computations`** (requested, R10): the engine-computation states, events and export, last in its session as its runbook says.
- **P21-A, create with mesh maps.** `project.create(plane, mesh_map_file_paths=[...])` with one file per documented `MeshMapUsage`, named `<texture set>_<suffix>` with Painter's suffixes. Read `get_mesh_map_resource` of every usage.
- **P21-B, default paths.** `create` with `Settings(default_save_path=..., export_path=...)`, then `export_project_textures` of a configuration without `exportPath`: where the files go and what it raises.
- **P21-C, texture throttling.** `TextureStateEvent.cache_key_invalidation_throttling_period()` in a fresh session.
- **P21-D, shelves.** `Shelves.all()` names and paths, `application_shelf().name()` and `user_shelf().name()`. Then `Shelves.add` and `refresh` of a folder, with `ShelfCrawlingStarted/Ended` connected and `is_crawling()` polled.
- **P21-E, layer-stack events.** Each edit call listed in §4 on a plane project, with `LayerStacksModelDataChanged` connected, both recordings.

## Alternatives Considered

- **Engine computations as a no-op.** Rejected by the task.
- **Raising when an export is requested while computations are disabled.** Rejected: the task asks for deferral, and the facade then blocks like Painter's warned hang.
- **Guessing the mesh-map suffixes or mapping templates by name only.** Rejected: a guessed binding or wrong base values would change exported textures silently.
- **Emitting `LayerStacksModelDataChanged` for every insert.** Rejected by the panel: only `insert_fill` and `insert_group` are recorded.

## Consequences

- phase1.22 marks these symbols as release gaps or named gaps with these recordings.
- phase1.24 owns the template argument.
- Each recording, when admitted, turns its gap into an exact comparison in `test_pyapi_lifecycle_tier0.py`.
