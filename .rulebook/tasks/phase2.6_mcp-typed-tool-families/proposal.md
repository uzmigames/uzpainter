# Proposal: phase2.6_mcp-typed-tool-families

## Why
Child of `phase2.8_mcp-server` (P2-MCP in `docs/dag.md`), implementing the typed tool groups, resources and prompts of D10 (`docs/architecture/11-mcp-server.md` §2, §3; owner Q12, decision 025): every required operation must be reachable through typed tools so a deployment runs with Python disabled. Requirements: INT-02, INT-05, INT-06, INT-07, LAY-06, LAY-07, QG-03, ARC-14 (`docs/prd.md`).

## What Changes
- Tool groups of `11-…` §2 with typed schemas, each handler forwarding to the worker's native operation: Status (`status`, `capabilities`); Project (`project_create {mesh, settings, mesh_maps, template}`, `project_open`, `project_save {mode}`, `project_save_as`, `project_close {discard?}`, `project_inspect {path?}`, `project_recipe`, `project_revert {revision|checkpoint}`); Texture sets (`set_list`, `set_resolution`, `set_rename`, `set_channels`, `set_mesh_maps`); Resources (`resource_import`, `resource_list`, `resource_search`, `resource_replace`, `assets_search`); Stack (`layer_list`, `layer_insert`, `layer_set`, `layer_delete`, `layer_instantiate`, `effect_insert`, `effect_set`, `mask_set`, `source_set`, `fill_set`, `procedural_set`, `anchor_list`, `smart_material_insert`, `smart_mask_insert`, `smart_export`); Recipes (`sync_stack` with the `painter_layer_stack.py sync` semantics, `apply_smart`, `batch {calls[], stop_on_error}`); Baking (`bake_inspect`, `bake_configure`, `bake_set_mesh_inputs`, `bake_start`, `bake_capture_preset`, `bake_apply_preset`); Export (`export` with dry-run plan, `export_presets_list`); Render (`capture` with receipt and a downscaled PNG image block built by the supervisor, `display_get/set`, `shader_get/set`, `camera_get/set`); Diagnostics (`snapshot_layer_tree`, `diff_snapshots`, `isolate_layer`, `material_views`, `region_stats`); Mesh (`mesh_reload`, `mesh_certificate`); Jobs and lease (`job_status`, `job_result`, `job_cancel`, `job_list`, `lease_acquire`, `lease_release`, `lease_status`). No stroke tool (owner Q5).
- Long tools (`bake_start`, `export`, `capture`, `mesh_reload`, `project_create`, `project_open`) return `{job_id, status}` or block with `wait=true`; `busy {job_id}` and `wait_idle {timeout}` as specified.
- Resources `uzpainter://capabilities`, `uzpainter://project/manifest`, `uzpainter://project/recipe`, `uzpainter://project/layers`, `uzpainter://project/resources`, `uzpainter://assets/parity`, `uzpainter://jobs/<id>`, `uzpainter://ledger`; UzmiGames-authored prompts: stack JSON template, smart JSON template, baking preset template, export config template.
- Families whose native implementation is not in the build yet (native bake until `phase3.5_embree-bakers`, procedural and smart content until `phase3.3_procedural-families`/`phase3.6_smart-presets-projections`, later node kinds until `phase4.2_remaining-nodes`, `painter_iray` until `phase3.7_path-tracer`, and capture/diagnostics until `phase2.3_realtime-preview`/`phase2.2_recipe-and-diagnostics` land) are registered with their schemas and return the capability-gap error before any mutation.

## Dependencies
- Parent: `phase2.8_mcp-server`.
- Prerequisites: `phase2.4_supervisor-worker` (DAG input of P2-MCP), `phase2.5_mcp-transport-registry`.
- Followed by `phase2.7_mcp-operation-matrix`.

## Acceptance
- Each available family passes its typed-tool tests on synthetic project fixtures, including name-addressing ambiguity and repeated operations (LAY-06), group-only `sync_stack` rebuild with unrelated roots and resources surviving (LAY-07), `batch` stop-on-error with per-call results (INT-06), and receipts with target identity (INT-07).
- Every unavailable family returns the capability-gap error before mutation and is listed as a gap in `uzpainter://capabilities`.

## Impact
- Affected specs: `mcp` (typed tool families, resources, prompts)
- Affected code: supervisor tool definitions and worker command handlers
- Breaking change: NO
- User benefit: agents operate every available capability without Python
