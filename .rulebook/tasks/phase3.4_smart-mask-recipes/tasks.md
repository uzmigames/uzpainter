## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase3.3_procedural-families

## 2. Implementation
- [ ] 2.1 Implement `insert_smart_mask`: detached expansion into a mask-stack effect list attached in one transaction, `preset_ref {asset@version}` recorded, insertion outside a mask stack rejected
- [ ] 2.2 Author the UzmiGames smart-mask recipes for the edge-wear, cavity-dirt, edge-crack, ground-dirt, dust and occlusion roles in the documented layer/effect model, with per-recipe provenance records
- [ ] 2.3 Register the Painter smart-mask names as internal aliases resolving to the private observed structure on the owner's machine, else `UnsupportedProcedural{reason: "private preset unavailable"}`
- [x] 2.4 Extend the repository guard to reject observed preset trees, parameter collections and serialized readbacks
  - Note (2026-10-21): rule `observed-structure` in `tools/parity/guard/guard.py` (`parity/GUARD.md` §1) rejects, at any path and in ZIP members, JSON holding the recorder's shapes of observed Painter data: a layer-stack node (`name` with a documented `layerstack.NodeType` as `node_type` or `type`: preset trees, `get_root_layer_nodes`, `content_effects`, `mask_effects`), a property read (`value` with `widget_type`: `get_properties`), a substance source read (`substance_properties`, or `resource_url` with `properties`/`presets`/`image_inputs`/`image_outputs`: `get_source`), levels parameters (`class` of the documented `substance_painter.levels`: `get_parameters`); a recorded blob is also rejected by its hash in the store index (`store-hash`). Tests: `test_an_observed_preset_structure_is_blocked_by_its_content` (six shapes x two paths), `test_a_recorded_preset_readback_is_blocked_and_an_authored_recipe_passes`. Evidence: `tests/parity/test_guard.py`, 118 passed, exit 0 (log `tmp/scratch/parity-tools/pytest-guard.log`); `python -m tools.parity.guard` on the whole tree with the owner's store index: 4185 files checked, 0 blocked, exit 0 (log `tmp/scratch/parity-tools/guard-repo.log`). CPU only.
- [ ] 2.5 Author the Tier 2a manifests per recipe under `parity/manifests/`, with Painter rebuild instructions using only the documented API

## 3. Tests
- [ ] 3.1 Tier 2a: each recipe rebuilt in Painter through the documented API and in UzPainter on unit sphere, bevelled cube and hat v6 low × {1024, 2048, 4096} produces equal outputs
- [ ] 3.2 Insertion-rule test: `insert_smart_mask` into a content stack raises; a failing expansion attaches nothing
- [ ] 3.3 Alias tests: with the private structure present the alias resolves to it; without it `UnsupportedProcedural` is raised and no UzmiGames recipe is substituted
- [x] 3.4 Guard test: a recorded preset readback JSON is rejected; an authored recipe JSON passes
  - Note (2026-10-21): `test_a_recorded_preset_readback_is_blocked_and_an_authored_recipe_passes`: a stand-in smart-mask tree readback recorded into a temporary store is blocked by `store-hash` and `observed-structure`; an authored recipe JSON (lower-case `kind` nodes, UzmiGames provenance) passes. The shipped recipes of 2.2 do not exist yet; the test uses a recipe-shaped stand-in. Evidence: `tests/parity/test_guard.py`, 118 passed, exit 0 (log `tmp/scratch/parity-tools/pytest-guard.log`); `python -m tools.parity.guard` on the whole tree with the owner's store index: 4185 files checked, 0 blocked, exit 0 (log `tmp/scratch/parity-tools/guard-repo.log`). CPU only.

## 4. Acceptance
- [ ] 4.1 Acceptance: every shipped smart-mask recipe passes Tier 2a (equal or owner-approved exception); insertion, alias and guard tests pass

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
