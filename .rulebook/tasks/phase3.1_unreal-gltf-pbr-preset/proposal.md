# Proposal: phase3.1_unreal-gltf-pbr-preset

## Why
EXP-08 (`docs/prd.md`) lists a Painter-equivalent glTF metallic-roughness preset (SHOULD) validated by a glTF consumer fixture; OWN-06 asks for PBR export like Substance; PRD §18 item 5 requires export presets validated by their consumers, glTF included. Presets are UzmiGames-authored, each packing decision citing a public source — for this preset the glTF 2.0 specification — and confirmed against Painter's observed output for its `glTF PBR Metal Roughness` preset, which stays private (`docs/licensing-and-clean-room.md` §6; decision 002; CLR-06 for the internal alias). Child of P3-UNREAL (`phase3.3_unreal-gltf-presets`), implementing D7: `docs/architecture/08-export.md` §4 (preset list and provenance rule) and §5 (receipts, generational publication).

## What Changes
- **Preset** `assets/export-presets/gltf-pbr-metal-roughness.json`, answering to `glTF PBR Metal Roughness` through the compatibility alias table, with base colour, packed metallic-roughness, normal, occlusion and emissive outputs whose channel packing and colour spaces follow the glTF 2.0 metallic-roughness material.
- **Provenance record** `assets/export-presets/gltf-pbr-metal-roughness.provenance.json`: glTF 2.0 specification sections for every packing decision, the SHA-256 of the private observed outputs (Painter's files for this preset on a UzmiGames fixture project and the documented `list_output_maps()` result), parity status.
- **glTF consumer fixture**: manifest `parity/manifests/consumers/gltf/wand-v1.json`; the fixture assembles a test glTF 2.0 asset from the UzmiGames-authored fixture mesh and the published textures, validates it and loads it in a recorded glTF consumer; the consumer choice is recorded in the manifest because the DAG names none.
- **Consumer gaps**: channels with no glTF core slot (SpecularWeight) are reported in the receipt.

## Dependencies
- DAG input (through the parent): `phase2.10_pilot-tunic-recovery`.
- Delivered upstream and used here: `phase1.18_export-engine` (plan compiler, virtual maps, receipts, generational publication), `phase0.5_private-oracle-store` (private observations, self-hosted runner).
- Parent: `phase3.3_unreal-gltf-presets`. Independent of `phase3.2_unreal-ue56-packed-preset`.

## Acceptance
Part of the P3-UNREAL gate ("fixtures load; packing confirmed"). Accepted when the preset's files equal Painter's export of the same preset on wand v1 and the pilots in decoded values (or an owner-approved exception covers a difference), the provenance record cites the glTF 2.0 specification for every packing decision, and the glTF consumer fixture loads the test asset with the specified bindings.

## Impact
- Affected specs: `export` (glTF preset)
- Affected code: Exporter component (preset, receipts); `assets/export-presets/gltf-pbr-metal-roughness.json` and its provenance record; `parity/manifests/consumers/gltf/`
- Breaking change: NO
- User benefit: maps that drop straight into glTF metallic-roughness materials
