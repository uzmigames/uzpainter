# 172. Painter batch C admits the 21 remaining template bases: every one is stable and holds its code class's candidate bit for bit

**Status**: accepted
**Date**: 2026-10-12
**Related Tasks**: phase1.25_pilot-wand

## Context

Decision 168 left 21 shipped templates' sRGB8 base `inferred` and refused, and requested one `export-template-base-<template>` golden each (`recording_requests.REMAINING_BASE_TEMPLATES`). All 21 were recorded on 2026-10-12, 21:41-21:43, in one Painter `12.1.5+js-api.1.1.20` session:

- Legacy colour management (no `OCIO`, no `PAINTER_ACE_CONFIG`) and the documented API only;
- under the Assets3D Painter lock, on throwaway projects only.

Painter was open for about two minutes and closed normally, and the lock was released. No recording crashed or was refused.

## Decision

All 21 goldens recorded `r1` (same session) and `r2` (after save and reopen). They were admitted with `python -m tools.parity.store record --run` and joined `recording_requests.ADMITTED`, and their requests were deleted.

- `store verify` of the envelope's `tier0/` and `python -m tools.parity.tier0_semantics check` pass.
- In every golden `r1` equals `r2` on every output, and every same-session export repeat is identical.
- The regenerated `parity/reports/phase0/tier0-stability.md` (no fits run) classifies all 21 as stable, so each is an exact golden. The report now covers 185 goldens: 133 stable and 52 unstable.

Every OpenEXR 32f file holds one value on every texel, and it is the candidate decision 168 named for the template's PNG 16 code class. Each PNG 16 control holds that class's code.

| Templates | Map | OpenEXR 32f | PNG 16 |
|---|---|---|---|
| ASM PBR Metallic Roughness and its Anisotropy Angle, Coated, Sheen and SSS variants; Blender; Dota 2; KeyShot; Lens Studio; Maxwell Metallic Roughness; PBR - Metallic Roughness Alpha-test; Roblox MaterialVariant and SurfaceAppearance; Spark AR Studio; Unity HD Render Pipeline (Metallic Standard); VrayMtl Metallic Roughness (16) | BaseColor | `0x3EFEFEFF`, `float32(127/255)` | 48107 |
| OpenPBR - Fuzz, OpenPBR - Subsurface Scattering (2) | BaseColor | `0x3F4CCCCD`, `float32(0.8)` | 59397 |
| Maxwell, Non-PBR and VrayMtl Specular Glossiness (3) | Specular | `0x3D20A0A1`, `float32(10/255)` | 14330 |

**Dota 2 also exports Specular.** Its template stores Specular as L8, not sRGB8. The OpenEXR 32f file holds `0x3D20A0A1` in R, G and B. The PNG 16 file, with linear storage, holds `(14330, 2570, 14330)` on every texel, in both recordings and in every repeat. G is the linear code of 10/255, while R and B match the sRGB8 Specular class's code. This is recorded as observed. It is not explained here.

| Golden (`export-template-base-`) | golden-record SHA-256 (prefix) |
|---|---|
| `asm-pbr-metallic-roughness` | `3f6347837a15` |
| `asm-pbr-metallic-roughness-anisotropy-angle` | `ad68f1490ab0` |
| `asm-pbr-metallic-roughness-coated` | `2e020a65cdbb` |
| `asm-pbr-metallic-roughness-sheen` | `73d59ba738a8` |
| `asm-pbr-metallic-roughness-sss` | `dd213dbbb8c9` |
| `blender` | `b1e0a6560fa2` |
| `dota-2` | `06399ec6a82c` |
| `keyshot` | `c11a88d78a02` |
| `lens-studio` | `ea12b541d3c2` |
| `maxwell-metallic-roughness` | `3f5b665b8557` |
| `maxwell-specular-glossiness` | `69661dd98296` |
| `non-pbr-specular-glossiness` | `9949e55fd8ac` |
| `openpbr-fuzz` | `b3396a9b0e4f` |
| `openpbr-subsurface-scattering` | `d3cdb2b2f796` |
| `pbr-metallic-roughness-alpha-test` | `cb71d2af57db` |
| `roblox-materialvariant` | `d2e31497eb50` |
| `roblox-surfaceappearance` | `12d414681956` |
| `spark-ar-studio` | `4d44dc53928a` |
| `unity-hd-render-pipeline-metallic-standard` | `0420f41373e5` |
| `vraymtl-metallic-roughness` | `deba3cffba77` |
| `vraymtl-specular-glossiness` | `6f4b9c9a7bbf` |

## Consequences

### Positive
- Every shipped template's empty sRGB8 base now has an exact OpenEXR 32f golden, which is what phase1.25 item 2.6 waited on.

### Negative
- This decision only records and admits the goldens. The template entries in `assets/templates/*.json` still say `inferred`, and their refusal is not lifted yet.

## Follow-ups
- Owner of phase1.25 item 2.6: turn the 21 entries `observed` with these goldens, as decision 168 §3 describes, and extend `test_observed_template_bases_equal_painter_files`. Then close the item.
- Dota 2's Specular PNG 16 encoding, `(14330, 2570, 14330)` on an L8 channel, goes to the export encoder owner.
