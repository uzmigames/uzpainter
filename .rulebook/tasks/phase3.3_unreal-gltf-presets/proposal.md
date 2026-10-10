# Proposal: phase3.3_unreal-gltf-presets

## Why
OWN-06 (`docs/prd.md`) requires PBR export like Substance plus Unreal's ORM standard; EXP-08 requires the Unreal ORM preset for Unreal Engine 5.6 (PNG/TGA by default, optional DDS BC7/BC5) and a glTF metallic-roughness preset (SHOULD), each validated by a consumer fixture, with any unbindable channel (SpecularWeight) exported and reported as a consumer gap; PRD §18 item 5 makes consumer validation a release criterion. Owner decision 023 (Q10) fixes UE 5.6 and the encodings. Shipped presets are UzmiGames-authored with provenance records and must pass output-parity tests against the private oracle before they ship (`docs/licensing-and-clean-room.md` §6, decision 002). This is DAG node P3-UNREAL (`docs/dag.md`), implementing D7: `docs/architecture/08-export.md` §3 (TGA, DDS), §4 ("Unreal Engine (Packed)", the glTF preset, provenance rule), §5 and §5.1 row 8.

This task is the parent integration and acceptance task, split into two child tasks because the UE 5.6 preset with its encodings and import fixture and the glTF preset with its consumer fixture are independently testable artifacts.

## What Changes
- `phase3.2_unreal-ue56-packed-preset`: `assets/export-presets/unreal-engine-packed.json` (answers to `Unreal Engine (Packed)` through the internal alias table) with provenance; ORM packing; PNG/TGA 8-bit default and the optional DDS BC7/BC5 variant (own DDS header writer); SpecularWeight as a separate map and consumer gap; the UE 5.6 import fixture on wand v1.
- `phase3.1_unreal-gltf-pbr-preset`: `assets/export-presets/gltf-pbr-metal-roughness.json` (answers to `glTF PBR Metal Roughness`) with provenance citing the glTF 2.0 specification; the glTF consumer fixture.
- Parent integration: both presets run on the available pilots (wand v1, belt v5, tunic v10); output parity against the private Painter exports of the same presets; capability-manifest entries; consolidated consumer-gap report in `parity/reports/phase3/`.

## Dependencies
- DAG inputs: `phase2.10_pilot-tunic-recovery` (P2-TUNIC).
- Children (mandatory, independent of each other): `phase3.2_unreal-ue56-packed-preset`, `phase3.1_unreal-gltf-pbr-preset`.
- Child-level edge: the DDS variant of `phase3.2_unreal-ue56-packed-preset` uses the BC encoder adapter of `phase3.1_uze-uztexture-writer`.
- Downstream: `phase3.8_gate-g3` (G3); the hat v8 run of consumer-matrix row 8 is attached to `phase4.2_coverage-hat-v8`.

## Acceptance
DAG gate of P3-UNREAL: fixtures load; packing confirmed. In substance: both children accepted; the UE 5.6 fixture imports the PNG/TGA and the DDS variants with BaseColor sRGB, ORM linear, Normal as a DirectX normal map and Emissive sRGB; the glTF fixture loads the glTF output with the specified metallic-roughness packing; each preset's files equal Painter's output for the same preset on the same project (decoded values, Tier 1 rules) or are covered by an owner-approved exception; SpecularWeight is reported as a consumer gap.

## Impact
- Affected specs: `export` (Unreal and glTF presets)
- Affected code: Exporter component (presets, TGA path, DDS header writer, receipts); `assets/export-presets/`; `parity/manifests/consumers/unreal/`, `parity/manifests/consumers/gltf/`; `parity/reports/phase3/`; capability manifest
- Breaking change: NO
- User benefit: Unreal Engine 5.6 and glTF consumers receive correctly packed maps validated by their own importers
