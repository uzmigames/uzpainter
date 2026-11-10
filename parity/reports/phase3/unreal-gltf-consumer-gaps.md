# Consumer gaps of the Unreal and glTF presets (phase3.3_unreal-gltf-presets item 3.3)

Date: 2026-11-10. Consolidates the consumer gaps the export receipts report for the three shipped
presets of P3-UNREAL. No Painter output is published here. Sources are the native receipt writer
(`src/export/receipt.cpp`, the gap texts in `src/export/receipt.h`), the presets' provenance
records and the tests named in each row.

## Gaps by preset

| Preset | Map | Gap (receipt `consumer_gaps[].channel`) | When | Evidence |
| --- | --- | --- | --- | --- |
| `unreal-engine-packed` | `$mesh_$textureSet_SpecularWeight` (PNG 8, L) | `SpecularWeight`: no slot in the consumer's material; the consumer applies the mapping (Specular = 0.5 x SpecularWeight), not the export | the stack has a SpecularWeight channel | `tests/export/test_unreal_preset.py::test_specularweight_is_a_separate_map_and_a_consumer_gap`, `::test_shipped_preset_publishes_in_ao_mixed_scope` |
| `unreal-engine-packed-dds` | `$mesh_$textureSet_SpecularWeight` (PNG 16, L, no DDS) | `SpecularWeight`, as above | the stack has a SpecularWeight channel | provenance record; `test_shipped_preset_publishes_in_ao_mixed_scope` |
| `unreal-engine-packed-dds` | every `.dds` (BaseColor and Emissive `BC7_SRGB`, ORM `BC7`, Normal `BC5`) | `cook`: whether UE 5.6 passes BC data through cooking is undocumented | always | `tests/export/test_unreal_preset.py::test_dds_variant_publishes_receipts_with_the_cook_gap` |
| `gltf-pbr-metal-roughness` | `$textureSet_SpecularWeight` (UzPainter extension, PNG 8, L) | `SpecularWeight`: no glTF 2.0 core slot | the stack has a SpecularWeight channel | provenance record ("SpecularWeight as a consumer gap") |
| `gltf-pbr-metal-roughness` | `$textureSet_emissive` | not written; the receipt lists it under `skipped` (`absent`) and the consumer binds no `emissiveTexture` (glTF 2.0 default `emissiveFactor` [0, 0, 0]) | the stack has no Emissive channel | `parity/reports/phase3/gltf-consumer-wand-v1.md` |

Painter's own presets write no SpecularWeight file (R-322 for Unreal Engine (Packed), R-314 for
glTF PBR Metal Roughness). Each SpecularWeight map is a UzPainter extension. Neither the map nor
its gap is a Painter parity claim.

## On the pilots

No pilot (Wand v1, Sash v5, Tunic v10) has a SpecularWeight, Emissive or Opacity channel. Their
production exports therefore write no SpecularWeight map and report no SpecularWeight gap. Each
glTF export lists the emissive map as skipped:

- Unreal Engine (Packed): BaseColor, ORM and Normal per pilot (`tests/parity/tier1/test_unreal_pilots.py`, 3 passed, 2026-11-10).
- glTF: baseColor, occlusionRoughnessMetallic and normal per pilot (`tests/parity/tier1/test_gltf_pilots.py`, 3 passed, 2026-11-09).

## Consumer observations

| Consumer | Fixture | Status |
| --- | --- | --- |
| fastgltf 0.9.1 (`fastgltf::validate`) | Wand v1 production glTF export | passed (`parity/manifests/consumers/gltf/wand-v1.json` `real-fixture-passed`, `parity/reports/phase3/gltf-consumer-wand-v1.md`): four core bindings, emissive unbound as above, ORM packing confirmed on all 4,194,304 texels |
| Unreal Engine 5.6.1 (`UnrealEditor-Cmd -run=pythonscript`, `AssetImportTask`) | Wand v1, Sash v5, Tunic v10 production PNG 16; Wand v1 TGA 8 and DDS (consumer-matrix row 8) | **PNG/TGA passed, DDS refused** (`parity/manifests/consumers/unreal/wand-v1.json` `partial`, `parity/reports/phase3/unreal-consumer-wand-v1.md`): through the generation-pinning adapter every PNG 16 and TGA 8 file imports with BaseColor sRGB, ORM linear (`TC_Masks`; UE's importer marks it sRGB by default, the consumer clears it), Normal `TC_Normalmap` with green not flipped (DirectX), UE's stored source equal to each file in decoded values; the material binds ORM R/G/B to AO/Roughness/Metallic and compiles in the Windows cook (BaseColor and ORM `PF_DXT1`, Normal `PF_BC5`). UE 5.6 imports no block-compressed DDS (`DDS DXGIFormat not supported` for BC5, BC7 and BC7_SRGB, and for BC1/BC3) |

## The `cook` gap, answered

UE 5.6 imports only uncompressed sources and encodes the platform format itself on cook, so no
BC data of the DDS variant reaches UE, let alone passes through its cook. The DDS files are valid
(Pillow decodes them) and stay compact interchange for other consumers; for UE 5.6 the DDS variant
is not consumable. Item 3.3 of `phase3.2_unreal-ue56-packed-preset` and its acceptance 4.1 ("loads
both variants") therefore do not hold as written; the choice that follows (another DDS encoding,
or the variant's UE requirement) is left to a decision, and nothing is relaxed here.

This report is complete for both presets: the gaps the receipts report, and the observations of
both consumer fixtures.
