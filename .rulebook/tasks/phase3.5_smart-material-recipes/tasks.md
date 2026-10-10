## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase3.4_smart-mask-recipes, phase3.4_smart-projections

## 2. Implementation
- [ ] 2.1 Define the smart-material recipe format in the documented layer/effect model (group, layers, effects, sources, projections, smart-mask references, parameters) with a provenance record per recipe
- [ ] 2.2 Design and author the initial UzmiGames smart-material recipes under `assets/`, using only certified P3-PROC families, shipped projections and shipped smart masks; record provenance for every family and resource used
- [ ] 2.3 Implement `insert_smart_material`: detached expansion to an editable group with `preset_ref {asset@version}`, attached in one transaction; insertion outside the hierarchy rejected as documented
- [ ] 2.4 Implement MCP `smart_material_insert` and `apply_smart {config_json, texture_set}` with the `painter_layer_stack.py smart` semantics; failure attaches nothing and lists what would have changed
- [ ] 2.5 Implement portable smart-material folders: `smart_export {uid, kind: material, path}` (recipe, resources by content hash, provenance) and insertion from such a folder
- [ ] 2.6 Add the smart-material compatibility aliases: private observed structure on the owner's machine, otherwise `UnsupportedProcedural{reason: "private preset unavailable"}`; never a UzmiGames substitute
- [ ] 2.7 Author the Tier 2a manifests for every shipped recipe under `parity/manifests/` and record the Painter rebuilds through the documented API
- [ ] 2.8 Add shipped recipes to the capability manifest with their Tier 2a evidence

## 3. Tests
- [ ] 3.1 Tier 2a for every shipped recipe: unit sphere, bevelled cube, hat v6 low × {1024, 2048, 4096} × {defaults, each recipe's recorded set, two boundary sets} × {recorded seed, one other}, exact against the Painter rebuild
- [ ] 3.2 Portable folder round trip: export from one project, insert into a fresh project, identical parameters, resource hashes and exported maps
- [ ] 3.3 Transaction test: a recipe referencing an unavailable family fails with `UnsupportedProcedural`, nothing is attached and the revision does not advance
- [ ] 3.4 Alias tests: a Painter smart-material name resolves to the private structure on the owner's machine and raises `private preset unavailable` on the hosted lane
- [ ] 3.5 Tier 0 API probes: insertion rules and readback of the expanded group (`get_root_layer_nodes`, `content_effects`, `get_source`, `get_parameters`) consistent with the recipe
- [ ] 3.6 MCP `apply_smart` fixture with Python disabled

## 4. Acceptance
- [ ] 4.1 Acceptance: every shipped smart material passes Tier 2a or is covered by an owner-approved exception; portable folder round trip identical; no substitution path

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
