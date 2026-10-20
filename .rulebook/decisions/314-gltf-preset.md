# 314. The glTF PBR Metal Roughness preset is written by hand from the glTF 2.0 specification, answers to its Painter name, and is refused until recording R-314 confirms its layout

**Status**: accepted
**Date**: 2026-10-19
**Related Tasks**: phase3.1_unreal-gltf-pbr-preset

## Context

Task `phase3.1_unreal-gltf-pbr-preset` ships a preset that answers to Painter's `glTF PBR Metal Roughness` (EXP-08, `docs/architecture/08-export.md` §4). The clean-room rule (decision 002, `docs/licensing-and-clean-room.md` §6) says the preset is written by hand from public sources and only confirmed against Painter's observed output. No recording of that preset exists yet. Its source is the Khronos glTF 2.0 Specification, version 2.0.1: §3.9.2 Metallic-Roughness Material, §3.9.3 Additional Textures, §3.9.4 Alpha Coverage, §3.8.3 Images, §2.6 File Extensions and Media Types, and the property reference §5.19 Material and §5.22 Material PBR Metallic Roughness.

The specification fixes the channels and transfer functions of each slot. It leaves these open:
- which UzPainter source feeds occlusion;
- what goes into the metallic-roughness texture's R;
- whether SpecularWeight, which has no core slot, gets a file;
- the file format, bit depth and names.

## Decision

1. **`assets/export-presets/gltf-pbr-metal-roughness.json`**, six maps:
   - `$textureSet_BaseColor`: RGB from `basecolor`, A from `opacity`. glTF reads A as linear alpha coverage (§3.9.4, §5.22). Without an opacity channel the file is RGB (probe P7).
   - `$textureSet_MetallicRoughness`: R from `defaultMap white`, G from `roughness`, B from `metallic` (§3.9.2, §5.22: roughness in G, metalness in B, R and A ignored). R holds 1.0, full indirect lighting. So a consumer that also binds this texture as occlusion (R, §5.19) sees no occlusion.
   - `$textureSet_Normal`: RGB from `virtualMap Normal_OpenGL`. §5.19 states +X right and +Y up, which is the OpenGL convention.
   - `$textureSet_Occlusion`: L from `virtualMap AO_Mixed`, the AO mesh map combined with the AO channel. That is the indirect-light occlusion §3.9.3 describes. A greyscale PNG decodes to R = G = B = L, and glTF samples R. `AO_Mixed` stays refused until it is fitted (decision 131), so this map is refused with it.
   - `$textureSet_Emissive`: RGB from `emissive` (§5.19).
   - `$textureSet_SpecularWeight`: L from `specularweight`. It is written when the stack has the channel. glTF 2.0 core has no specular input, so the receipt reports the file as a consumer gap. That follows decision 023: SpecularWeight is exported and reported, never dropped silently.
2. **Parameters.** Every map sets `fileFormat: png`: the core media types are PNG and JPEG (§2.6, §3.8.3), and JPEG is lossy with no alpha. Bit depth, padding and dithering come from `exportParameters`, as for the other hand-written presets, until the recording shows what the preset itself sets.
3. **Colour encoding.** Base colour and emissive are written in their channels' encoding. An sRGB8 channel is written sRGB-encoded (decision 126), which is what §5.22 and §5.19 require.
4. **No Height map.** glTF 2.0 core has no height or displacement slot.
5. **Names.** Files are named `$textureSet_<glTF texture>`.
6. **Alias (CLR-06).** `glTF PBR Metal Roughness` and `resource://starter_assets/glTF PBR Metal Roughness` resolve to the shipped id `gltf-pbr-metal-roughness`. Each alias now names the recording that settles an unrecorded `?version=` query: R-095 for the two phase1 presets, R-314 for this one. Assumption: the preset is a starter-assets resource, like `PBR Metallic Roughness`. The recording confirms or corrects that.
7. **Refused until R-314.** The provenance record has layout `unconfirmed` and pending recording R-314, owned by item 2.1. Under decision 095, every reference to the preset is refused (`NotYetSupported`, naming R-314) before anything is planned.
8. **Recording R-314.** Two requests under the current envelope's `requests/tier0/semantics/`, `export-presets-gltf-legacy` and `export-presets-gltf-ocio`, both pending. Each one fills, with a distinct source, every channel the preset reads: BaseColor, roughness, metalness, Height, Normal, Opacity, EmissionColor, AO and SpecularWeight. Each binds the Normal and AO mesh maps. Each captures:
   - the predefined and resource preset lists;
   - every predefined preset's output maps;
   - `ResourceExportPreset.list_output_maps()` of the preset's URL;
   - the preset, exported with its own parameters and with the pipeline's.

   The OCIO request is there because the wand v1 golden runs under OCIO.

## Alternatives Considered

- **Occlusion from `documentMap ambientOcclusion`:** rejected. It drops the baked AO mesh map, which is the main part of the indirect-light occlusion glTF means.
- **Occlusion packed into the metallic-roughness texture's R (ORM), with no separate file:** rejected. The R channel would then depend on `AO_Mixed`, so the refused map would block metallic-roughness too.
- **No SpecularWeight file:** rejected by decision 023.
- **Fixed bit depths (8-bit for base colour and emissive):** rejected. glTF 2.0.1 sets no bit depth for PNG, and the preset's own parameters are the recording's to show.

## Consequences

- Items 2.2, 2.3, 2.4 and 2.5 of the task are done. Item 2.1 waits on recording R-314.
- Items 2.6 and 2.7 (the glTF consumer and the fixture runner) need a validator and a loader that the machine does not have. Their published textures come through this preset, which stays refused until R-314. So 2.6 and 2.7 stay open, with 3.1 to 3.3.
- After R-314, the packing entries of the provenance record move from `hypothesis` to `confirmed` or are corrected. Its layout then becomes `confirmed`.
- Tests: `tests/export/test_export_presets.py` (`test_gltf_preset_packs_the_gltf_slots`, `test_gltf_preset_is_refused_naming_r314`, `test_painter_names_resolve_to_shipped_presets`, `test_provenance_records_are_complete`, `test_shipped_presets_pass_the_guard`); `tests/parity/test_recording_requests.py` and `tests/parity/test_tier0_semantics.py` for the requests.
