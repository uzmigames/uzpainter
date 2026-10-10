# Proposal: phase3.2_unreal-ue56-packed-preset

## Why
OWN-06 and EXP-08 (`docs/prd.md`) require Unreal's ORM standard for Unreal Engine 5.6 with PNG/TGA by default and an optional DDS BC7/BC5 encoding; SpecularWeight is exported and reported as a consumer gap (owner decision 023, Q10). Presets are UzmiGames-authored from documented behaviour, confirmed against observed Painter outputs held privately, never generated from a readback, and carry a provenance record (`docs/licensing-and-clean-room.md` §6; CLR-06 for the internal alias of the Painter preset name). Child of P3-UNREAL (`phase3.3_unreal-gltf-presets`), implementing D7: `docs/architecture/08-export.md` §3 (TGA via stb, DDS: own header writer over the BC encoder adapter), §4 ("Unreal Engine (Packed)": layout stated as behaviour, shipped only once its provenance record confirms it; UE 5.6 documents DDS 2D import but not BC pass-through through cooking, so "already compressed" means compact interchange until the fixture proves otherwise), §5 (fixed-name consumers run through the delivery adapter or publication lock) and §5.1 row 8.

## What Changes
- **Preset** `assets/export-presets/unreal-engine-packed.json`, answering to `Unreal Engine (Packed)` through the compatibility alias table: `$mesh_$textureSet_BaseColor` (RGB basecolor, A opacity), `_OcclusionRoughnessMetallic` (R `AO_Mixed`, G roughness, B metallic, linear), `_Normal` (`Normal_DirectX`), `_Emissive`; `_SpecularWeight` as a separate map when the channel exists.
- **Provenance record** `assets/export-presets/unreal-engine-packed.provenance.json`: public sources (Adobe's public output-template help pages, `export.html`, Unreal Engine documentation), the SHA-256 of the private observed-output fixtures (Painter's files for that preset on a UzmiGames fixture project and the documented `list_output_maps()` result), packing decisions with their source, parity status.
- **Encodings**: PNG/TGA 8-bit default (TGA through stb); optional DDS variant with UzPainter's own DDS header writer, BC7 for BaseColor, ORM and Emissive, BC5 for Normal, through the BC encoder adapter.
- **Consumer-gap reporting**: SpecularWeight listed in the receipt; the consumer-side mapping `Specular = 0.5 × SpecularWeight` is never executed by the export.
- **UE 5.6 import fixture**: manifest `parity/manifests/consumers/unreal/wand-v1.json`; UE 5.6 imports the published generation through the generation-pinning delivery adapter or the publication lock on the self-hosted GPU runner; checks BaseColor sRGB, ORM linear, Normal as a DirectX normal map, Emissive sRGB for both the PNG/TGA and DDS variants; records whether UE re-encodes the DDS files on cook.

## Dependencies
- DAG input (through the parent): `phase2.10_pilot-tunic-recovery`.
- Child-level prerequisite for the DDS items: `phase3.1_uze-uztexture-writer` (BC encoder adapter).
- Delivered upstream and used here: `phase1.18_export-engine` (plan compiler, virtual maps `AO_Mixed` and `Normal_DirectX`, receipts, generational publication), `phase0.5_private-oracle-store` (private observed outputs, self-hosted runner).
- Parent: `phase3.3_unreal-gltf-presets`. The hat v8 run of row 8 is attached to `phase4.2_coverage-hat-v8`.

## Acceptance
Part of the P3-UNREAL gate ("fixtures load; packing confirmed"). Accepted when the provenance record confirms the layout, the preset's files equal Painter's export of the same preset on wand v1 and the pilots (or an owner-approved exception covers a difference), and the UE 5.6 fixture imports both variants with the expected colour spaces, normal-map type and ORM packing, reporting SpecularWeight as a gap.

## Impact
- Affected specs: `export` (Unreal Engine 5.6 preset)
- Affected code: Exporter component (TGA path, DDS header writer, preset, receipts); `assets/export-presets/unreal-engine-packed.json` and its provenance record; `parity/manifests/consumers/unreal/`
- Breaking change: NO
- User benefit: Unreal Engine 5.6 imports UzPainter's packed maps directly, in PNG/TGA or compact DDS
