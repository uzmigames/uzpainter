# glTF consumer fixture on Wand v1 (phase3.1_unreal-gltf-pbr-preset item 3.2)

Date: 2026-11-09. Run: `tests/parity/tier1/test_gltf_pilots.py::test_wand_v1_gltf_export_equals_painter_and_loads_in_fastgltf`
(`UZP_TIER1_PRODUCTION=1`), ReleaseFast UzPainter on DX12. Every hash below is of UzPainter's own
output or of a UzmiGames input; no Painter output is published here.

## What ran

- **Export.** The Wand v1 Tier 1 rebuild (`phase3/tier1/wand-v1-gltf`: the pinned pipeline
  scripts, then the closing configuration `parity/fixtures/tier1/wand-v1-gltf/export-config.json`)
  through the production export of the authored `gltf-pbr-metal-roughness` preset, which
  `export-preset-generator://gltf` names. PNG 16, 2048 px, `infinite` padding, no dithering. The
  generation `000001` holds `11-Varinha-Madeira_baseColor`, `_occlusionRoughnessMetallic` and
  `_normal`; its receipt (SHA-256 `2ba59950c1762061513a6213046bf38c50acfbfbfa8e026ff52ebbfd6c848d18`)
  lists `$textureSet_emissive` as skipped (`absent`: the stack has no Emissive channel), with
  SpecularWeight.
- **Consumer.** fastgltf 0.9.1 with `fastgltf::validate` (`zig build gltf-consumer`), through
  `tools/consumers/gltf.py`, over the Wand's staged low-poly OBJ (one material).

## Result: pass

| Slot | Published file | SHA-256 | Size, channels, depth |
| --- | --- | --- | --- |
| baseColor | `11-Varinha-Madeira_baseColor.png` | `7af73490c2552c781769993587ee7ace99fc3743c6320c2f34230b3af9d5add6` | 2048², RGB, 16 |
| metallicRoughness | `11-Varinha-Madeira_occlusionRoughnessMetallic.png` | `435a032ab9d5c6e35c0e621f3ed1a7ad404c041c20b79fdc25c0d4947bb1d97e` | 2048², RGB, 16 |
| occlusion | the same ORM file (R) | `435a032ab9d5c6e35c0e621f3ed1a7ad404c041c20b79fdc25c0d4947bb1d97e` | 2048², RGB, 16 |
| normal | `11-Varinha-Madeira_normal.png` | `a2216cadfbadcd600ab20676ed320eb2e30356e72bba5edbb147ebfcd5b39e31` | 2048², RGB, 16 |
| emissive | none: unbound | — | consumer gap, the receipt's skipped entry |

- The asset validates and loads: 809 vertices, 1,248 triangles, normals and texture coordinates on
  every vertex, bounds as the OBJ gives them.
- Material as loaded: base colour, metallic and roughness factors 1, normal scale 1, occlusion
  strength 1, `emissiveFactor` [0, 0, 0] (glTF 2.0's default without `emissiveTexture`).
- Packing: every G texel of the ORM equals the same rebuild's independent Roughness PNG 16
  (`509f00968b0435efa9fc08689cb2ac7fd2753d84d810af2b55607bd911693d01`) and every B texel its
  Metallic PNG 16 (`2cc24170f943d397f5bd4278a37894b70fc8adc834a0134c4b80fc9676072503`):
  0 mismatches of 4,194,304 each.

## Emissive on a set without an emissive channel

The glTF 2.0 material makes `emissiveTexture` optional and gives `emissiveFactor` the default
[0, 0, 0]. The fixture binds emissive only when the preset writes an emissive file; otherwise the
material has no emissive texture, and the receipt must report the map skipped, which the consumer
report names as the slot's consumer gap. This is the specification's own behaviour, not a waiver.
Painter's own glTF export of the Wand also writes no emissive file (`phase3/tier1/wand-v1-gltf`).

## Scope

Structural validation, loaded geometry, decoded PNG resources and bindings on the CPU; no
Khronos validator, no rendering. Output parity with Painter is item 3.1
(`parity/reports/phase3/tier1-wand-v1-gltf.json`: pass under EXC-013 and EXC-014).
