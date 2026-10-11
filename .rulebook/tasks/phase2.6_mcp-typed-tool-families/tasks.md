## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase2.4_supervisor-worker, phase2.5_mcp-transport-registry

## 2. Implementation
- [ ] 2.1 Status and Project groups (`status`, `capabilities`, `project_create/open/save/save_as/close/inspect/recipe/revert`)
- [ ] 2.2 Texture-set and Resources groups (`set_*`, `resource_import/list/search/replace`, `assets_search`)
- [ ] 2.3 Stack family (`layer_*`, `effect_*`, `mask_set`, `source_set`, `fill_set`, `procedural_set`, `anchor_list`, `smart_material_insert`, `smart_mask_insert`, `smart_export`) with explicit `(texture_set, stack)` addressing
- [ ] 2.4 Recipes group: `sync_stack` (`stack_json, masks_dir, state?, resource_prefix, resource_group, keep_visible, texture_set`), `apply_smart`, `batch {calls[], stop_on_error}`
- [ ] 2.5 Export group (`export` plan or receipt, dry run, `export_presets_list`) and Mesh group (`mesh_reload`, `mesh_certificate`)
- [ ] 2.6 Render group (`capture` with supervisor-built downscaled PNG block, `display_get/set`, `shader_get/set`, `camera_get/set`, their setters limited to the fixed render pipeline's values by decision 038 and rejecting any other value with an explicit error, decision 042) and Diagnostics group (`snapshot_layer_tree`, `diff_snapshots`, `isolate_layer`, `material_views`, `region_stats`)
- [ ] 2.7 Baking group (`bake_inspect`, `bake_configure`, `bake_set_mesh_inputs`, `bake_start`, `bake_capture_preset`, `bake_apply_preset`) and Jobs/lease group (`job_*`, `lease_*`)
- [ ] 2.8 Long-job behaviour (`{job_id, status}` or `wait=true`), `busy {job_id}`, `wait_idle {timeout}`
- [ ] 2.9 MCP resources (`uzpainter://capabilities`, `project/manifest`, `project/recipe`, `project/layers`, `project/resources`, `assets/parity`, `jobs/<id>`, `ledger`) and the four UzmiGames-authored prompt templates
- [ ] 2.10 Capability-gap registration for every family whose native implementation is not in the build, with the gap listed in `uzpainter://capabilities`

## 3. Tests
- [ ] 3.1 Per-family typed-tool tests on synthetic UzmiGames-authored project fixtures for every available family
- [ ] 3.2 LAY-06 tests through MCP: ambiguous name fails before mutation listing candidate ids; repeating a named operation creates no duplicate; ids survive save/reopen
- [ ] 3.3 LAY-07 tests through `sync_stack`: only the named group rebuilt; other root groups hidden, not deleted, unless `keep_visible` matches; unrelated resources survive
- [ ] 3.4 `batch` stop-on-error with per-call results; long tools with and without `wait=true`; `busy` and `wait_idle` timeout
- [ ] 3.5 Capability-gap tests: each unavailable family fails before mutation and appears as a gap in `uzpainter://capabilities`
- [ ] 3.6 Resource and prompt listing tests

## 4. Acceptance
- [ ] 4.1 Every §3 test green; results attached to `phase2.8_mcp-server`

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
