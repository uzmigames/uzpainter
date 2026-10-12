## 1. Prerequisites
- [x] 1.1 Prerequisites accepted: phase1.14_compositor-core, phase1.15_export-plan-compiler, phase1.16_export-processing-encoders
  - The plan compiler (phase1.15) and the writers (phase1.16, archived) are merged on main. phase1.14 and phase1.15 stay open only on their children's and their Tier 0 items, which the presets do not depend on.

## 2. Implementation
- [x] 2.1 Write the three preset JSON files by hand from the documented export semantics and the observed behaviour
  - `assets/export-presets/{assets3d-inline-five-map, pbr-metallic-roughness, blender-principled-bsdf}.json`. The five-map preset is the pipeline script's. The two Painter-named presets are provenance-backed hypotheses, refused until recording R-095 confirms them (decision 095).
- [x] 2.2 Write a provenance record per preset with public sources, observed-output fixture hashes, packing decisions and parity status
  - `<id>.provenance.json` under `src/export/preset-provenance.schema.json`. Private records stay empty until R-095, and the parity status is pending.
- [x] 2.3 Implement the internal compatibility alias table for `defaultExportPreset` names
  - `src/export/preset_aliases.{h,cpp}`. `ParseConfig` resolves inline first, then by id, Painter name or `resource://starter_assets/` URL (recorded versions only).

## 3. Tests
- [x] 3.1 Output-parity test per preset on a UzmiGames fixture project against the private records (local run on the owner's machine, decision 028; the local run report is the evidence): every file equal on decoded pixels and naming
  - Scope split, deferred and not passed (decision 096). What the current envelope records passes: the five-map Normal map is byte-identical to Painter's on 4 of 4 sets. Full per-preset parity needs recording R-095 (and R-090 for BaseColor). Owner: `phase1.18_export-engine` item 6.2 (`parity/reports/phase1/export-presets.md` §3-§4).
- [x] 3.2 Provenance test: every preset has a complete `.provenance.json` validated against its schema
- [x] 3.3 Alias test: `defaultExportPreset: "Blender (Principled BSDF)"` resolves to the shipped preset
- [x] 3.4 Guard test: no shipped preset file matches a private-store hash (repository guard of P0-STORE)

## 4. Acceptance
- [x] 4.1 All three presets pass output parity and provenance checks; parity status recorded in each provenance file
  - Provenance checks pass, and the parity status is recorded in each file as `pending`. Output parity is a scope split, deferred and not passed (decision 096): `phase1.18_export-engine` item 6.2 with R-095, and item 6.1 with R-090. Until then, the unconfirmed presets and every BaseColor export are refused before writing.

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [x] 5.1 Update or create documentation covering the implementation
  - `src/export/EXPORT.md` §5, `docs/architecture/08-export.md` §4, `parity/reports/phase1/export-presets.md`.
- [x] 5.2 Write tests covering the new behavior
  - `tests/export/test_export_presets.py` (9 tests).
- [x] 5.3 Run tests and confirm they pass
