# Proposal: phase3.2_uze-uzmat-preset

## Why
OWN-06 and EXP-08 (`docs/prd.md`) require a UzEngine standard preset (`.uzmat` plus compressed `.uztexture`); EXP-10 requires explicit engine format and binding metadata per map with canonical 16-bit/float maps written beside the cooked derivatives and no filename heuristics; INT-21 and QG-03 require complete receipts and dry runs that list exactly what is written. Owner decision 023 (Q10) makes SpecularWeight a reported consumer gap; decision 021 (Q8) requires `.uzmat` to be written by UzPainter's own code from the format definition. Shipped presets need a provenance record (`docs/licensing-and-clean-room.md` §6). Child of P3-UZE (`phase3.4_uzengine-preset`), implementing D7: `docs/architecture/08-export.md` §1 (plan compiler), §4 (UzEngine preset table, provenance rule) and §5 (receipts, generational publication); `docs/architecture/13-engine-integration.md` §2.4 and §4.1.

## What Changes
- **`.uzmat` writer** (Exporter component): JSON material with `TextureSample → PBROutput` pins 0..6, plus the inline scene-material block (`08-export.md` §4).
- **Preset** `assets/export-presets/uzengine.json` implementing the UzEngine preset table: `<set>_albedo` (basecolor RGB + opacity A, PNG8, BC7 sRGB), `<set>_normal` (virtual normal in the convention proven by the Phase 0 normal fixture, PNG8/16, BC5), `<set>_orm` (`AO_Mixed`, roughness, metallic; PNG8, BC7 linear), `<set>_emissive` (PNG8, BC7 sRGB), `<set>_height` (PNG16 + sidecar, BC4, explicit format metadata), `<set>_specularweight` (PNG8/16, BC4, consumer gap), `<set>.uzmat`.
- **Canonical maps**: 16-bit/float canonical maps always written beside the cooked derivatives (EXP-10).
- **Opacity route**: opacity carried in albedo alpha for the bindless fixed-PBR path; the SM5 route is reported unsupported for opacity in the receipt.
- **Receipts and manifest blocks**: per file engine format, colour space, bit depth, binding slot, normal tag (`geometry_only`/`combined` with relief round) and consumer gaps; manifest `exportacao` fields (INT-21).
- **Provenance record** `assets/export-presets/uzengine.provenance.json` with the fields of `08-export.md` §4, citing the UzEngine format definition and `08-export.md` §4 as sources.
- **Plan integration**: the preset is selectable by name in `defaultExportPreset`; `list_project_textures` and the MCP `export` dry run list every output with its resolved format.

## Dependencies
- DAG input (through the parent): `phase2.10_pilot-tunic-recovery`.
- Previous child: `phase3.1_uze-uztexture-writer` (`.uztexture` writer, BC encoder, mips).
- Delivered upstream and used here: `phase1.18_export-engine` (plan compiler, receipts, generational publication), `phase0.9_normal-convention-fixture` (normal convention).
- Parent: `phase3.4_uzengine-preset`. Next child: `phase3.3_uze-consumer-fixture`.

## Acceptance
Part of the P3-UZE gate. This child is accepted when the preset compiles into a typed plan listing exactly the table's outputs, `.uzmat` pins 0..6 reference the right textures, canonical maps sit beside every derivative and equal the same channels exported by the already-proven PNG route, receipts carry format, binding and consumer-gap fields, the SpecularWeight and SM5-opacity gaps are reported, and the provenance record exists and validates.

## Impact
- Affected specs: `export` (`.uzmat` writer, UzEngine preset)
- Affected code: Exporter component (`.uzmat` writer, preset resolution, receipts); `assets/export-presets/uzengine.json`, `assets/export-presets/uzengine.provenance.json`; capability manifest entry for the preset
- Breaking change: NO
- User benefit: a complete UzEngine material delivery with explicit bindings and visible gaps
