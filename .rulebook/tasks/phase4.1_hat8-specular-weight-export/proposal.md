# Proposal: phase4.1_hat8-specular-weight-export

## Why
PRJ-06 (`docs/prd.md`) requires a SpecularWeight channel per set with its storage format recorded, accepted by hat v8 Tier 1; EXP-01 lists SpecularWeight and AO among the per-set exports; OWN-06 and EXP-08 require a channel the consumer cannot bind to be exported and reported as a consumer gap, never compensated (owner decision 023, Q10); INT-11 names the hat consumers that read it (`deliver_v8.py` loads SpecularWeight with its Blender link commented out; `glb_add_specular.py` reads it as 8-bit with the weight in RGB and A). Channel formats per template are measured in Tier 0 and shipped templates are authored with provenance (`docs/architecture/03-project-model.md` §2). The hat v8 export is the Assets3D inline five-map preset plus SpecularWeight, whose provenance is the pipeline script `painter_export_v8.py` (`docs/architecture/08-export.md` §4). Child of P4-HAT8 (`phase4.2_coverage-hat-v8`), implementing D14 with D7 (`08-export.md` §4, §5, §5.1 rows 2, 3, 5, 8, 9).

## What Changes
- **SpecularWeight channel**: per-set channel with the storage format measured in Tier 0 for the template the hat uses; fills, blends and exports like any channel; recorded explicitly in the project.
- **Hat v8 export preset**: the hat v8 variant of the Assets3D inline preset in `assets/export-presets/` (five maps + SpecularWeight + 16-bit AO), with a provenance record naming `painter_export_v8.py` as its source; SpecularWeight written as 8-bit with the weight in RGB and A as delivered today (row 3).
- **Consumer-gap reporting across presets**: every receipt lists SpecularWeight as a consumer gap where the consumer has no binding — the UzEngine preset (BC4, no slot), the Unreal Engine (Packed) preset (separate `_SpecularWeight`), Blender row 2 (loaded, link commented out); the consumer-side mappings (`Specular = 0.5 × SpecularWeight` in UE, Specular IOR Level = 0.5 × SpecularWeight in row 5) are never executed by the export.
- **Capability manifest**: SpecularWeight channel and export `supported` with their Tier 0 evidence ids.

## Dependencies
- Parent DAG inputs: `phase3.7_fixtures-bracers-hat5`, `phase3.4_uzengine-preset` (UzEngine preset gap reporting).
- Upstream used here: `phase1.18_export-engine` (plan compiler, receipts, inline presets), `phase0.8_tier0-goldens` (template channel formats).
- Parent: `phase4.2_coverage-hat-v8`. Independent of `phase4.1_hat8-sharpen-filter`.

## Acceptance
Part of the P4-HAT8 gate (equal maps). This child is accepted when the SpecularWeight channel's storage format and exported values equal the Tier 0 goldens, the hat v8 preset exports SpecularWeight in the encoding row 3 reads, and every preset receipt lists SpecularWeight as a consumer gap where the consumer cannot bind it, with no compensation in any exported map.

## Impact
- Affected specs: `export` (SpecularWeight channel and hat v8 preset)
- Affected code: channel registry and templates (SpecularWeight format), Exporter receipts (consumer gaps), `assets/export-presets/` hat v8 variant and its provenance record, capability manifest
- Breaking change: NO
- User benefit: hat v8's SpecularWeight reaches every consumer that reads it, and every consumer that cannot is told so explicitly
