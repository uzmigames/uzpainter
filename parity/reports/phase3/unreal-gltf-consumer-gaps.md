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
| Unreal Engine 5.6 | Wand v1, PNG/TGA and DDS variants (consumer-matrix row 8) | **not run.** It needs a UE 5.6 project folder on the owner's machine (decision 028), and none has been named (`phase3.2_unreal-ue56-packed-preset` items 2.8, 3.2, 3.3, 3.5). The bindings UE 5.6 gives each map, and whether it re-encodes the DDS on cook (the `cook` gap), are unobserved. |

This report is complete for the glTF preset. The Unreal half lists the gaps the receipts report.
Its UE 5.6 observations are added when that fixture runs.
