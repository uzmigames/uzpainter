## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: `phase2.10_pilot-tunic-recovery` (parent input)

## 2. Implementation
- [ ] 2.1 Record the private observed outputs: Painter's files for `glTF PBR Metal Roughness` on a UzmiGames fixture project and the documented `list_output_maps()` result, hashes in `parity/manifests/`
- [ ] 2.2 Author `assets/export-presets/gltf-pbr-metal-roughness.json` by hand, every packing decision citing the glTF 2.0 specification
- [ ] 2.3 Provenance record `assets/export-presets/gltf-pbr-metal-roughness.provenance.json`
- [ ] 2.4 Compatibility alias so `defaultExportPreset: "glTF PBR Metal Roughness"` resolves to the shipped preset (CLR-06)
- [ ] 2.5 Consumer-gap reporting for channels without a glTF core slot (SpecularWeight)
- [ ] 2.6 Select and record the glTF consumer for the fixture (validator plus loader) in `parity/manifests/consumers/gltf/wand-v1.json`
- [ ] 2.7 Fixture runner that assembles a test glTF 2.0 asset from the authored fixture mesh and the published textures, validates and loads it

## 3. Tests
- [ ] 3.1 Output parity on wand v1, belt v5 and tunic v10: every preset file equals Painter's export of the same preset in decoded values
- [ ] 3.2 glTF consumer fixture on wand v1: the asset validates and loads with base colour, metallic-roughness, normal, occlusion and emissive bound as specified
- [ ] 3.3 Defect detection: a metallic-roughness texture with swapped channels fails the packing check
- [ ] 3.4 Provenance record validates against its schema on the local CPU lane (decision 200)

## 4. Acceptance
- [ ] 4.1 Child acceptance met and reported to `phase3.3_unreal-gltf-presets`: glTF fixture loads; packing confirmed

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
