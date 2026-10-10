# Proposal: phase3.4_uzengine-preset

## Why
OWN-06 and EXP-08 (`docs/prd.md`) require a UzEngine export standard — `.uzmat` plus compressed `.uztexture` — and ARC-06 requires that preset to be validated by an external UzEngine consumer fixture, never by a UzEngine renderer inside UzPainter. EXP-10 requires explicit engine format and binding metadata per map, with canonical maps written beside the cooked derivatives. Owner decision 023 (Q10) fixes the target formats and makes SpecularWeight a reported consumer gap; decision 021 (Q8) requires both formats to be written by UzPainter's own code with no UzEngine library linked or called. This is DAG node P3-UZE (`docs/dag.md`), implementing D7: `docs/architecture/08-export.md` §4 ("UzEngine preset"), §5 and §5.1 row 9; `docs/architecture/13-engine-integration.md` §2.1 (format header vendored as definition only), §2.4 and §4.1; `docs/architecture/07-preview-and-render-parity.md` §1 (external consumer, not part of the no-window acceptance).

This task is the parent integration and acceptance task. The work is split into three child tasks per the DAG task decomposition rule, because the `.uztexture` writer, the `.uzmat`/preset layer and the external consumer fixture are independently testable artifacts.

## What Changes
- `phase3.1_uze-uztexture-writer`: UzPainter's own `.uztexture` writer (layout from the vendored `uztexture_format.h` only), the deterministic BC encoder adapter (etcpak; BC4/BC5/BC7 including sRGB variants) and the mip policy (sRGB-aware colour filtering, renormalised normals, alpha-coverage-preserving masked albedo).
- `phase3.2_uze-uzmat-preset`: UzPainter's own `.uzmat` writer (`TextureSample → PBROutput` pins 0..6 plus the inline scene-material block), the shipped preset `assets/export-presets/uzengine.json` with `assets/export-presets/uzengine.provenance.json`, canonical 16-bit/float maps beside every cooked derivative, receipt fields for engine format, binding and consumer gaps.
- `phase3.3_uze-consumer-fixture`: the external UzEngine consumer fixture (UzEngine's own executable loads the `.uzmat`/`.uztexture` files in a test scene in a local run on the owner's machine, decision 028), its manifest under `parity/manifests/consumers/uzengine/`, the lossy-derivative comparison and the gap report.
- Parent integration: the preset run end to end on the available pilots (wand v1 is the consumer-matrix fixture; belt v5 and tunic v10 additionally), the consolidated gap list in `parity/reports/phase3/`, and capability-manifest entries for the preset and its outputs.

## Dependencies
- DAG inputs: `phase2.10_pilot-tunic-recovery` (P2-TUNIC).
- Children (mandatory, in order): `phase3.1_uze-uztexture-writer` → `phase3.2_uze-uzmat-preset` → `phase3.3_uze-consumer-fixture`.
- Downstream: `phase3.8_gate-g3` (G3); `phase4.2_coverage-hat-v8` (P4-HAT8 runs consumer-matrix row 9 on hat v8).
- Child-level edge outside this node: `phase3.2_unreal-ue56-packed-preset` reuses the BC encoder adapter delivered by `phase3.1_uze-uztexture-writer` for its optional DDS BC7/BC5 variant.

## Acceptance
DAG gate of P3-UZE: the preset loads and renders in the external UzEngine fixture, and its gaps are listed. In substance: every child task is accepted; the external fixture loads and renders the wand v1 preset output with the bindings of the UzEngine preset table (`08-export.md` §4); decoded `.uztexture` data is compared with the canonical maps under the lossy-derivative contract (`14-parity-testing.md` §4); SpecularWeight and every other unbindable output (the SM5 opacity route) are listed as consumer gaps in the receipts and in the gap report.

## Impact
- Affected specs: `export` (UzEngine preset)
- Affected code: Exporter component (`.uztexture` and `.uzmat` writers, BC encoder adapter, mip generation, preset plan, receipts); `assets/export-presets/`; `parity/manifests/consumers/uzengine/`; `parity/reports/phase3/`; capability manifest (`capabilities.json`)
- Breaking change: NO
- User benefit: UzEngine receives materials and compressed textures straight from UzPainter with explicit format and binding metadata, validated by the engine's own executable
