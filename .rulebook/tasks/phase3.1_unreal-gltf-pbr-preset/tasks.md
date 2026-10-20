## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: `phase2.10_pilot-tunic-recovery` (parent input)

## 2. Implementation
- [ ] 2.1 Record the private observed outputs: Painter's files for `glTF PBR Metal Roughness` on a UzmiGames fixture project and the documented `list_output_maps()` result, hashes in `parity/manifests/`
  - Progress (decision 314; open): recording R-314 is requested, not recorded: `requests/tier0/semantics/export-presets-gltf-legacy` and `-ocio` under the current envelope (the bevelled cube with every channel the preset reads filled distinctly, the Normal and AO mesh maps bound; the preset lists, every predefined preset's output maps, `list_output_maps()` of `resource://starter_assets/glTF PBR Metal Roughness`, and the preset with its own and the pipeline's parameters). Needs an owner Painter session
- [x] 2.2 Author `assets/export-presets/gltf-pbr-metal-roughness.json` by hand, every packing decision citing the glTF 2.0 specification
- [x] 2.3 Provenance record `assets/export-presets/gltf-pbr-metal-roughness.provenance.json`
- [x] 2.4 Compatibility alias so `defaultExportPreset: "glTF PBR Metal Roughness"` resolves to the shipped preset (CLR-06)
- [x] 2.5 Consumer-gap reporting for channels without a glTF core slot (SpecularWeight)
  - Done (decision 314): the preset (six maps, each packing decision citing glTF 2.0 2.0.1 sections) and its provenance record (layout unconfirmed, pending R-314); the alias table resolves the Painter name and its starter-assets URL, and every reference is refused naming R-314 until the recording; SpecularWeight is its own map and carries the receipt consumer gap. Tests: tests/export/test_export_presets.py test_gltf_preset_packs_the_gltf_slots, test_gltf_preset_is_refused_naming_r314, test_painter_names_resolve_to_shipped_presets
- [ ] 2.6 Select and record the glTF consumer for the fixture (validator plus loader) in `parity/manifests/consumers/gltf/wand-v1.json`
- [ ] 2.7 Fixture runner that assembles a test glTF 2.0 asset from the authored fixture mesh and the published textures, validates and loads it

## 3. Tests
- [ ] 3.1 Output parity on wand v1, belt v5 and tunic v10: every preset file equals Painter's export of the same preset in decoded values
- [ ] 3.2 glTF consumer fixture on wand v1: the asset validates and loads with base colour, metallic-roughness, normal, occlusion and emissive bound as specified
- [ ] 3.3 Defect detection: a metallic-roughness texture with swapped channels fails the packing check
- [x] 3.4 Provenance record validates against its schema on the local CPU lane (decision 200)
  - Done (decision 314): tests/export/test_export_presets.py test_provenance_records_are_complete validates every shipped record, this one included, against src/export/preset-provenance.schema.json on the CPU lane

## 4. Acceptance
- [ ] 4.1 Child acceptance met and reported to `phase3.3_unreal-gltf-presets`: glTF fixture loads; packing confirmed

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
