# 322. The Unreal Engine (Packed) preset ships unconfirmed, refused until recording R-322; its DDS variant is the separate preset `unreal-engine-packed-dds`, PNG 16 maps with a `dds` target block; TGA stays refused

Date: 2026-10-20. Status: accepted (Claude; decision number assigned by the coordinator; routine technical choice delegated by the owner).
Related: `phase3.2_unreal-ue56-packed-preset` (items 2.2 to 2.7, 2.10, 3.6), decisions 023, 095, 131, 314 and 318, `docs/architecture/08-export.md` §4, `docs/DDS.md`.

## Context

08-export §4 states the layout of `Unreal Engine (Packed)` as behaviour: BaseColor with opacity in A, `_OcclusionRoughnessMetallic` (R `AO_Mixed`, G roughness, B metallic, linear), `_Normal` from `Normal_DirectX`, `_Emissive`, and `_SpecularWeight` when the channel exists. Owner answer Q10 (decision 023) sets PNG/TGA 8-bit as the default and an optional DDS encoding: BC7 for BaseColor, ORM and Emissive, BC5 for Normal.

Four points were open:
- no recording of Painter's output for that preset exists (item 2.1);
- Painter's JSON configuration has no field that asks for a DDS companion, and `RequestDds` (docs/DDS.md) cooks only from a planned PNG 16 file;
- no TGA writer exists: stb is not vendored, and Painter's TGA files are not recorded;
- `AO_Mixed` is still refused (decision 131).

## Decision

1. **`assets/export-presets/unreal-engine-packed.json`**, written by hand from 08-export §4, decision 023 and the Unreal Engine 5.6 texture documentation (approved source X-CONSUMERS). Five maps, named `$mesh_$textureSet_<map>`, each `fileFormat: png`, `bitDepth: 8`:
   - BaseColor: R, G, B from `basecolor`, A from `opacity`;
   - OcclusionRoughnessMetallic: R from `virtualMap AO_Mixed`, G from `roughness`, B from `metallic`;
   - Normal: R, G, B from `virtualMap Normal_DirectX`;
   - Emissive: R, G, B from `emissive`;
   - SpecularWeight: L from `specularweight`. When the stack lacks the channel, the map is absent (decision 091). The receipt reports it as a consumer gap, and the mapping `Specular = 0.5 × SpecularWeight` is not applied (decision 023).

   Padding and dithering come from `exportParameters`, as for the other hand-written presets.
2. **Alias (CLR-06).** `Unreal Engine (Packed)` and `resource://starter_assets/Unreal Engine (Packed)` resolve to `unreal-engine-packed`. An unrecorded `?version=` names R-322. Assumption: the preset is a starter-assets resource like the glTF one (decision 314). R-322 confirms or corrects the reference.
3. **Refused until R-322.** Both provenance records have layout `unconfirmed` and pending recording R-322, owned by item 2.1. Under decision 095, every reference to either preset is refused (`NotYetSupported`, naming R-322) before anything is planned. Every packing entry stays `hypothesis`.
4. **The DDS variant is its own preset, `unreal-engine-packed-dds`.** No Painter name answers to it.
   - Its maps are the same five at PNG 16. Each PNG 16 is the canonical file its DDS is cooked from (EXP-10; `RequestDds` accepts only PNG 16).
   - A preset-level `dds` block names the targets:
     - BaseColor: `BC7_SRGB` with colour mips;
     - ORM: `BC7` with linear mips;
     - Normal: `BC5` with normal mips;
     - Emissive: `BC7_SRGB` with colour mips.
   - SpecularWeight has no DDS, because decision 023 names no BC format for it.
   - The BaseColor uses colour mips, not masked-colour mips: an alpha alone does not tell a cutout from a translucent surface (decision 318 §6).
   - Like `uzengine`, only a shipped preset may carry the block, and an inline preset's `dds` key is refused as undocumented. `LoadShippedPreset` checks each target against its maps and pairs BC5 with normal mips and BC7_SRGB with colour mips.
   - `CompilePlan` attaches each target through `RequestDds`. So the variant gets the same transfer, normal-source, size and path checks as a native request, and the plan hash covers it.
   - Its packing is the default preset's, so it shares that preset's `unconfirmed` layout and R-322.
5. **Receipt.** Every DDS derivative carries a `cook` consumer gap. UE 5.6 documents DDS 2D import, but not BC pass-through through cooking (08-export §4), so the DDS is compact interchange until the Unreal consumer fixture (item 3.3) records whether the engine re-encodes it.
6. **TGA stays refused** (`NotYetSupported`, naming item 2.5 and R-322), for two reasons:
   - the writer needs stb vendored with pinned provenance through `tools/vendoring`;
   - Painter's TGA files are not recorded, so even a written TGA would not be proven exact.
7. **Recording R-322** (item 2.1) captures, on a UzmiGames fixture:
   - Painter's files and dry run for the preset, by the reference the preset lists give;
   - every channel the preset reads filled distinctly (BaseColor, Opacity, Roughness, Metallic, AO, Emissive, SpecularWeight, Normal, Height), with the AO and Normal mesh maps bound;
   - the export with the preset's own parameters and with the pipeline's, at PNG 8 and at TGA 8;
   - the preset lists and the preset's `list_output_maps()`.

   The recording request is not authored yet.

## Alternatives Considered

- **DDS as an option of `unreal-engine-packed` itself:** rejected. Painter's configuration has no field for it, and a hidden switch would make one preset id stand for two outputs.
- **DDS variant with layout `consumer`:** rejected. That layout is for presets that make no Painter claim (decision 318). This variant repeats the Painter preset's packing.
- **Writing TGA now from the PNG 8 values:** rejected. Painter's TGA files are unrecorded, and nothing unproven is written (decision 001).
- **An own TGA writer from the Truevision specification:** not taken. 08-export §3 names stb, and the format choice is not reopened here.

## Consequences

- Items 2.2 and 2.4 are done. 3.6 is done for both records.
- These items stay open:
  - 2.1, which needs R-322;
  - 2.3, whose record names no observed-output hashes until R-322 is recorded and admitted;
  - 2.5, which needs the TGA writer and R-322;
  - 2.6, 2.7 and 2.10, because the shipped presets cannot export (refused on R-322) and their ORM still reads AO_Mixed;
  - 2.8 and 3.1 to 3.5.
- The dry run, the DDS companions, the receipts and the SpecularWeight gap are evidenced only on a test-only copy, `tests/export/test_unreal_preset.py` `variant_presets`. That copy's provenance says `confirmed`, and its ORM's R reads `ambientOcclusion`. It is not shipped-preset, Painter-parity or UE 5.6 evidence.

## Native writer evidence (2026-10-23)

The missing-writer premise of section 6 is resolved by `src/export/tga_writer.{h,cpp}`.
`EncodeTga` accepts explicit, already quantized top-first L/LA/RGB/RGBA bytes and
writes RLE TGA8 through stb image_write v1.16 at pinned commit
`003501f6d7a8668ce8b6d875e34dd97ad0d5d5b5`. `tools/vendoring` records the upstream
archive hash, verbatim header and MIT licence; no upstream patch is needed.
The writer preserves alpha, validates TGA dimension and stb signed-int indexing
limits, and exposes no mutable stb settings.

This does not supersede the parity refusal: no PNG quantization, transfer, padding
or alpha-dropping rule has been promoted to TGA. Painter export configuration
still refuses TGA on R-322, and both Unreal presets remain unconfirmed. The native
writer tests use authored bytes, an independent RLE decoder and Pillow; they do
not establish Painter bytes or UE 5.6 acceptance. Item 2.5 remains open for that
integration and evidence.
