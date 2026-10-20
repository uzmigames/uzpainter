## 1. Prerequisites
- [x] 1.1 Prerequisites accepted: phase2.4_supervisor-worker, phase2.5_mcp-transport-registry — accepted: both are archived as accepted, phase2.4_supervisor-worker in `.rulebook/archive/2026-10-20-phase2.4_supervisor-worker/` (e276fda2) and phase2.5_mcp-transport-registry in `.rulebook/archive/2026-10-20-phase2.5_mcp-transport-registry/` (e42cb825)

## 2. Implementation
- [x] 2.1 Status and Project groups (`status`, `capabilities`, `project_create/open/save/save_as/close/inspect/recipe/revert`)
- [x] 2.2 Texture-set and Resources groups (`set_*`, `resource_import/list/search/replace`, `assets_search`)
- [x] 2.3 Stack family (`layer_*`, `effect_*`, `mask_set`, `source_set`, `fill_set`, `procedural_set`, `anchor_list`, `smart_material_insert`, `smart_mask_insert`, `smart_export`) with explicit `(texture_set, stack)` addressing
- [x] 2.4 Recipes group: `sync_stack` (`stack_json, masks_dir, state?, resource_prefix, resource_group, keep_visible, texture_set`), `apply_smart`, `batch {calls[], stop_on_error}`
- [x] 2.5 Export group (`export` plan or receipt, dry run, `export_presets_list`) and Mesh group (`mesh_reload`, `mesh_certificate`)
- [x] 2.6 Render group (`capture` with supervisor-built downscaled PNG block, `display_get/set`, `shader_get/set`, `camera_get/set`, their setters limited to the fixed render pipeline's values by decision 038 and rejecting any other value with an explicit error, decision 042) and Diagnostics group (`snapshot_layer_tree`, `diff_snapshots`, `isolate_layer`, `material_views`, `region_stats`)
- [x] 2.7 Baking group (`bake_inspect`, `bake_configure`, `bake_set_mesh_inputs`, `bake_start`, `bake_capture_preset`, `bake_apply_preset`) and Jobs/lease group (`job_*`, `lease_*`)
- [x] 2.8 Long-job behaviour (`{job_id, status}` or `wait=true`), `busy {job_id}`, `wait_idle {timeout}`
- [x] 2.9 MCP resources (`uzpainter://capabilities`, `project/manifest`, `project/recipe`, `project/layers`, `project/resources`, `assets/parity`, `jobs/<id>`, `ledger`) and the four UzmiGames-authored prompt templates
- [x] 2.10 Capability-gap registration for every family whose native implementation is not in the build, with the gap listed in `uzpainter://capabilities`

## 3. Tests
- [x] 3.1 Per-family typed-tool tests on synthetic UzmiGames-authored project fixtures for every available family
- [x] 3.2 LAY-06 tests through MCP: ambiguous name fails before mutation listing candidate ids; repeating a named operation creates no duplicate; ids survive save/reopen
- [x] 3.3 LAY-07 tests through `sync_stack`: only the named group rebuilt; other root groups hidden, not deleted, unless `keep_visible` matches; unrelated resources survive
- [x] 3.4 `batch` stop-on-error with per-call results; long tools with and without `wait=true`; `busy` and `wait_idle` timeout
- [x] 3.5 Capability-gap tests: each unavailable family fails before mutation and appears as a gap in `uzpainter://capabilities`; the resource publishes the shipped manifest unchanged, `uzpainter.render.capture` `mode:painter_iray` among its release gaps (closes phase2.3_realtime-preview item 3.3, decision 162)
- [x] 3.6 Resource and prompt listing tests

## 4. Acceptance
- [x] 4.1 Every §3 test green; results attached to `phase2.8_mcp-server`

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [x] 5.1 Update or create documentation covering the implementation
- [x] 5.2 Write tests covering the new behavior
- [x] 5.3 Run tests and confirm they pass

## 6. Notes (scope splits and evidence)
- Recordings: none. The typed tools run the native operations the `uzpainter` API already runs (shared through `src/python/edits.h`). The MCP layer is UzPainter's own control plane, and it reproduces no new Painter behaviour.
- 1.1: left open on purpose, as phase2.5 left its own. phase2.4_supervisor-worker is merged on main but not accepted: its 4.1 waits on the Vulkan device cases (decision 121), the hosted CPU lane and G1. phase2.5_mcp-transport-registry is merged with its 1.1 open for the same reason. This task builds on their code on main.
- 1.1 (decision 200, 2026-10-13): the hosted CPU lane is removed and no longer a condition of phase2.4, which waits on the Vulkan device cases (decision 121) and G1.
- 1.1 (decision 221, 2026-10-13): the Vulkan device cases are no longer a condition of phase2.4_supervisor-worker; they are acceptance obligations of `phase3.1_vulkan-compute-parity` (items 3.4 and 4.1), which removes the acceptance cycle phase3.1 → phase2.10 → phase2.8 → phase2.4 → phase3.1. phase2.4 is held only by G1 (phase1.25_pilot-wand) through its children.
- Decisions:
  - 164: native single-transaction handlers over the API's shared edits; uid, stack-name and LAY-06 name addressing; `params` upserts; per-argument-value capability gating (`x-uzpainter-capability`, fail closed); the gap families; `project_create`'s row in the new project's first transaction; `project_save_as` a long lifecycle call; `sync_stack` without `state`; `mask_set` without mask blending.
  - 165: `status`, `capabilities` and `batch` in the supervisor; the capture image block built by the native helper `_uzpainter_image` (long edge 512, `image.built` explicit); the resources and prompts.
  - Panel: one round (GPT-6 Astra, Kimi K3, Grok 4.5). C1, C2 PARTLY ×2 and AGREE ×1, refined. C3 DISAGREE ×1 and PARTLY ×2, refined (`save_as` became a long tool). C4, C6 AGREE ×2 and PARTLY ×1. C5 DISAGREE ×1, AGREE ×1 and PARTLY ×1: the majority's explicit `image.built: false` was adopted. C7 AGREE ×2 and PARTLY ×1.
- 2.1:
  - `status` and `capabilities` are the supervisor's own tools.
  - `project_create` is long and mutating, and its row is in the new project's first transaction. Its mesh maps are bound in that transaction.
  - `project_save_as` is a long call with no commit point.
  - `project_close {discard}` refuses closing an untitled project, which would delete it.
  - `project_inspect {path}` reads a file without opening it (store inspection).
  - `project_recipe` is `DumpCurrentRecipe`. `project_revert` submits the admitted request (`Session::RevertRequest`).
- 2.2:
  - `set_list`, `set_resolution`, `set_rename` (keeps `original_name`; another set's name is refused, the same name is a no-op), `set_channels` (add, edit and remove in one transaction) and `set_mesh_maps` (a resource, or a PNG imported first; null unbinds).
  - `resource_import` (usage gated per value), `resource_list` (`used_only`) and `resource_replace` (everywhere, or one node's source with `uid`).
  - `resource_search` and `assets_search` are gaps until the asset library of phase3.3_procedural-families.
- 2.3:
  - `layer_list` (the layer-tree records of one stack), `layer_insert` (fill, group; paint gated), `layer_set`, `layer_delete`, `effect_insert` (fill, levels; paint, generator, filter, anchor, compare mask and colour selection gated on the native `uzpainter.layerstack` inserts the tool performs, decision 182), `effect_set` (with levels), `mask_set`, `source_set` (uniform, bitmap, reset; reference gated) and `fill_set` (projection modes gated per value, `source_mode: Material` gated).
  - `layer_instantiate` is a gap until phase4.1_nodes-instances-anchors, as is `anchor_list`. `procedural_set` is a gap until phase3.3_procedural-families. `smart_material_insert`, `smart_mask_insert` and `smart_export` are gaps until phase3.6_smart-presets-projections.
  - A geometry mask in `layer_set` is gated: the manifest lists `LayerNode.set_geometry_mask` as a release gap.
- 2.4:
  - `sync_stack`: the native `SyncStack` with `resource_prefix` and `resource_group` (`SyncOptions`), `stack_key`, and a file or an object. There is no `state`: resource URLs carry their content hash and survive sessions (RES-02).
  - `apply_smart` is a gap until phase3.6_smart-presets-projections.
  - `batch` is the supervisor's: per-call results, `stop_on_error`, `not_executed`, no nesting, an optional batch key.
- 2.5:
  - `export` takes `config` or `preset` (+ `output_dir`, `texture_sets`), the overrides `size_log2`, `file_format`, `bit_depth` and `padding` (one last unfiltered parameter rule), and `dry_run` (plan and files, nothing written).
  - `export_presets_list` lists the shipped presets with their aliases, maps and layout status.
  - `mesh_reload` is a long, mutating job over the API's `MeshReloadCall`. `mesh_certificate` reads the import report.
- 2.6: the phase2.5 hand-over is done. The capture's PNG is decoded by `_uzpainter_image.preview_png` (spng through `evaluator::DecodeBitmap`) and averaged down to a long edge of at most 512 px, as an 8-bit PNG block. `image {built, width, height, sha256, source_sha256}` describes it. The display, shader, camera and diagnostics tools were in place (decisions 038, 042, 132, 136).
- 2.7:
  - The six baking tools are registered with their schemas and declare `substance_painter.baking.*` or `uzpainter.baking.BakingParameters` release gaps (phase3.5_embree-bakers).
  - The job and lease tools are phase2.3's and phase2.5's.
- 2.8: the long typed tools (`project_create`, `project_save_as`, `mesh_reload`, `export`, `project_open`) take `wait`; `busy {job_id}` and `wait_idle {timeout}` are the admission's.
- 2.9: `python/uzpainter_supervisor/resources.py`. `uzpainter://project/manifest` reads the new pipe method `worker/manifest`.
- 2.10:
  - Whole gap tools declare release-gap operations, and their handlers refuse too.
  - Per-value gaps use `x-uzpainter-capability`.
  - The native release gaps a call meets (`NotYetSupported` and its kin) become `capability_gap`.
  - Two release-gap manifest entries were added: `uzpainter.assets.search` and `uzpainter.layerstack.set_procedural`.
- Tests (Vulkan workers, no device, Python disabled):
  - `tests/supervisor/test_typed_tools.py`, 13 tests: every family listed with its status; the spec's stack edit; Project and Texture sets; Resources and Stack; Export, Mesh and Render with the image block; LAY-06; LAY-07; batch; long tools; busy and `wait_idle`; gaps, also on the worker's own pipe; resources and prompts.
  - Affected existing tests: `test_supervisor_mcp.py::test_tools_are_forwarded...`, `test_supervisor_transports.py::test_roots_confine_paths...`, `test_supervisor_jobs.py::test_long_jobs_return_at_once...`, `test_settling.py::test_unavailable_backend_through_mcp`, `tests/python/test_pyapi_native.py` (the bindings now call `edits.h`), `tests/python/test_capability_conformance.py`, `tests/capabilities/test_capabilities.py`: green except `test_pyapi_native.py::test_later_phase_calls_raise_not_yet_supported_before_mutation`, which fails on main too (it still expects `uzpainter.render.capture` to be a release gap, which phase2.2 implemented; not touched here).
  - `tests/supervisor/test_registry.py`, 13 tests (pure Python): the value gate failing closed, batch keys, `status`, `capabilities`, the image block and its failures, the resources.
  - Updated: `test_supervisor_mcp.py` (the tool list) and `test_supervisor_transports.py` (the downscaled block).
- 3.5 (follow-up): `test_unavailable_families_fail_before_mutation` also checks that `uzpainter://capabilities` publishes the shipped `capabilities.json` entries and compat profile unchanged, with `uzpainter.render.capture` `mode:painter_iray` a release gap, and that `capture {mode: painter_iray}` is refused `PathTracerUnavailable` (closes phase2.3_realtime-preview item 3.3, decision 162). `tests/python/test_pyapi_native.py::test_later_phase_calls_raise_not_yet_supported_before_mutation` no longer lists `uzpainter.render.capture` as a gap (phase2.2 implemented it, decision 148); it checks that `painter_iray` raises `PathTracerUnavailable` before any work.
