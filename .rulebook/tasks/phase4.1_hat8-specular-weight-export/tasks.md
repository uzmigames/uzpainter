## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: `phase3.7_fixtures-bracers-hat5`, `phase3.4_uzengine-preset` (parent inputs)

## 2. Implementation
- [ ] 2.1 SpecularWeight channel per set with the storage format measured in Tier 0 for the hat's template; template entry authored with its provenance (public source or private-observation hash)
- [ ] 2.2 Hat v8 variant of the Assets3D inline preset in `assets/export-presets/` (five maps + SpecularWeight + 16-bit AO) with a provenance record naming `painter_export_v8.py`
- [ ] 2.3 SpecularWeight export encoding for the hat v8 preset: 8-bit, weight in RGB and A, as row 3 reads it
- [ ] 2.4 Receipt consumer-gap entries for SpecularWeight in the UzEngine, Unreal Engine (Packed) and Blender row 2 deliveries; no consumer-side mapping executed by the export
- [ ] 2.5 Capability manifest: SpecularWeight channel and export `supported` with Tier 0 evidence ids

## 3. Tests
- [ ] 3.1 Tier 0: SpecularWeight uniform fills and blends exported at the template format equal the private goldens
- [ ] 3.2 Hat v8 preset plan test: the dry run lists the seven delivered files with their formats, including SpecularWeight 8-bit RGBA
- [ ] 3.3 Receipt test: SpecularWeight listed as a consumer gap for the UzEngine, UE and row 2 deliveries; other maps byte-identical with and without a SpecularWeight channel present
- [ ] 3.4 Provenance record validates against its schema on the local CPU lane (decision 200)

## 4. Acceptance
- [ ] 4.1 Child acceptance met and reported to `phase4.2_coverage-hat-v8`: SpecularWeight channel and export exact; gaps reported, never compensated

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
