## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase1.14_compositor-core, phase1.15_export-plan-compiler, phase1.16_export-processing-encoders

## 2. Implementation
- [ ] 2.1 Write the three preset JSON files by hand from the documented export semantics and the observed behaviour
- [ ] 2.2 Write a provenance record per preset with public sources, observed-output fixture hashes, packing decisions and parity status
- [ ] 2.3 Implement the internal compatibility alias table for `defaultExportPreset` names

## 3. Tests
- [ ] 3.1 Output-parity test per preset on a UzmiGames fixture project against the private records (self-hosted runner): every file equal on decoded pixels and naming
- [ ] 3.2 Provenance test: every preset has a complete `.provenance.json` validated against its schema
- [ ] 3.3 Alias test: `defaultExportPreset: "Blender (Principled BSDF)"` resolves to the shipped preset
- [ ] 3.4 Guard test: no shipped preset file matches a private-store hash (repository guard of P0-STORE)

## 4. Acceptance
- [ ] 4.1 All three presets pass output parity and provenance checks; parity status recorded in each provenance file

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
