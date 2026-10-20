# 318. The UzEngine preset ships as a `consumer` layout with a `uzengine` block, PNG 16 canonical companions in `canonical/`, and receipts that report the colour space of the bytes written

Date: 2026-10-20. Status: accepted (Claude and Codex, SUP-109; routine technical choice delegated by the owner).
Related: `phase3.2_uze-uzmat-preset` (items 2.2, 2.6, 2.8, 3.6, landed in 3760add1), decisions 131, 245, 315, 316, `docs/architecture/08-export.md` §4 (UzEngine preset table), PRD EXP-10.

## Context

The 08-export §4 table lists the UzEngine preset's outputs, but it leaves four points open:
- the file depth of the normal and SpecularWeight maps ("PNG8/16");
- what the height "sidecar" is;
- how a preset that is not a Painter preset is told apart from one that is;
- where the canonical 16-bit maps of EXP-10 live.

The receipt also reported `linear` for every file, whatever encoding the file actually stored.

## Decision

1. **Consumer layout.** The provenance record `assets/export-presets/uzengine.provenance.json` declares the layout `consumer`. That is a new value of `src/export/preset-provenance.schema.json`. The preset `assets/export-presets/uzengine.json` is not a Painter preset and has no Painter alias, so it makes no claim about Painter behaviour. The record validates on the CPU lane (decision 200). Its parity stays pending R-131 (decision 131).
2. **`uzengine` block.** Only shipped presets may carry this block. An inline preset that carries it is refused as an undocumented key. Per texture, the block states:
   - the binding;
   - the `.uztexture` format (BC4, BC5 or BC7);
   - the sRGB flag and the mip class;
   - the negative-Z policy (decision 316);
   - plus the `$textureSet.uzmat` material.

   The plan checks a declared sRGB or linear flag against the encoder's own flags, luma included. A mismatch is refused, and nothing is converted.
3. **Depth.** The normal and SpecularWeight maps are PNG 16, so each is its own canonical map. This follows EXP-10 ("signed normals kept at authoring precision") and the rule that canonical 16-bit maps are always written beside the cooked derivatives. The albedo, ORM and emissive maps stay PNG 8 as the table says. Their PNG 16 canonical companions are written to `canonical/$textureSet_{albedo,orm,emissive}`. Every `.uztexture` derivative is cooked from its canonical file.
4. **Height.** The table's "PNG16 + sidecar" is read as the PNG 16 height plus its BC4 companion, with explicit format metadata in the receipt. The table says that metadata is needed because the cooker's default would make the file BC7 sRGB. The approved sources define no other engine sidecar format.
   - The binding name `heightmap` is declarative metadata only. The pinned `U-UZE-RUNTIME` a703c95 material has no Height pin, so no engine consumption is claimed. Height is reported as a consumer gap.
5. **Receipt colour space.** `colour_space` reports what each file stores (`sRGB`, `linear` or `mixed`), and each image channel gains a `transfer` field. Only sRGB-encoded PNGs change from the old uniform `linear`. `test_receipt_colour_space_follows_the_written_encoding` pins which ones.
6. **Gaps stay explicit.** Every receipt records these:
   - **Opacity (SM5 route):** unsupported.
   - **Height:** no pin.
   - **SpecularWeight:** no engine slot.
   - **Blend:** "Masked when the albedo has alpha" is an authored rule. Alpha alone does not tell cutout from translucent, so no general engine Opacity parity is claimed.

   The pinned shader reconstructs a positive normal Z, so negative-Z rendering stays open in consumer fixture 3.3.

## Consequences

- The full shipped preset still cannot export. Its `<set>_orm` reads `AO_Mixed`, which is refused before planning (decision 131). On wand v1 the normal map is also refused by the island rule (decision 245).
- So items 2.3, 2.4, 2.5, 2.7, 2.9, 3.1, 3.3, 3.4 and 3.5 stay open. Their tests pass only on authored, filtered or test-variant sets, and that does not establish shipped-preset or Wand acceptance.
- DDS integration (item 2.6 of the Unreal preset) builds on this layout. Codex owns it.
