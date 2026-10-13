# 204. The PNG of an L8 material channel holds the sRGB encode in R, B and L and the linear write in G

**Status**: accepted
**Date**: 2026-10-13
**Related Tasks**: phase1.25_pilot-wand

## Context

Decision 169 refused the PNG of an L8 BaseColor, Specular or Emissive (release gap `l8-material-channel-png`, owner: the export encoder). Painter's PNG 16 of Dota 2's empty L8 Specular, `float32(10/255)`, holds `(14330, 2570, 14330)`, and one empty channel did not settle a rule. Decision 198 admitted the settling golden `tier0/semantics/export-l8-material`, stable (r1 = r2, every export step equal to its repeat). It edits BaseColor to L8 and adds Specular and Emissive as L8. It fills them with grey A (s0), the 8-bit grey ramp (s1) and a uniform 0.37 (s2), and leaves s3 empty. It exports the three maps as RGB and as L at PNG 8, PNG 16 and OpenEXR 32f.

Measured on its files (every set, map and recording):

- OpenEXR 32f holds `float32(k/255)` in every component, 183 distinct codes k.
- The RGB PNG holds the sRGB export encode of that linear value in R and B, and its linear UNORM write in G (`k` at PNG 8, `257 k` at PNG 16). The L PNG holds the sRGB encode. The encode is the existing one of an sRGB8 material channel (decisions 091 and 126), at 8 and 16 bits alike.
- The empty L8 bases equal the sRGB8 ones: BaseColor `float32(0.8)` (the default template's), Specular `float32(10/255)`, Emissive 1.0.
- In s0 and s1, Painter decodes each grey bitmap's codes close to the sRGB decode before the L8 store. It is not the IEC decode with rounding: 13 of 256 codes differ.

The rule and its domain were measured exactly, so the model panel was not consulted.

## Decision

1. **The encode** (`SrgbEncodedRead`, `src/export/plan.h`): a PNG writes the sRGB encode of the linear value of a BaseColor, Specular or Emissive stored as sRGB8 (decision 126). Stored as L8 and read through srcChannel R, B or L, it does the same. Read through G, it writes the linear value. `EvaluateFileOn` sets `FileRaster::srgbEncoded` per channel from it, and `EncodeFile` is unchanged.
2. **Lifted only where recorded** (`CheckProcessing`, `src/export/encode.cpp`): the PNG of an L8 material channel is written in an RGB file whose R, G and B, or an L file whose L, each read that letter of the one L8 channel, under Legacy. It is refused with `NotYetSupported`, naming this decision and the golden, in every other case: under OCIO, in a file whose channels read other sources or other letters, and in L+A or RGB+A files.
3. **Channel defaults** (`assets/templates/channel-defaults.json`): Specular and Emissive added as L8 get the same base as their sRGB8 entries, `observed` from `export-l8-material` s3. A channel-defaults type may now repeat with distinct formats (`templates.cpp`). Every other format still fails with `missing_base_value`, whose message names the recorded formats.
4. **Capabilities.** The context `l8-material-channel-png` is replaced by `l8-material-channel-png-unrecorded` in both packages. Its conformance case exports Dota 2's Specular at PNG 16 in an RGB file whose G and B read BaseColor, and the refusal must name decision 204.
5. **Tests.**
   - `test_l8_material_channels_equal_painter_files`: Painter's own OpenEXR 32f file of every map, as the raster of its PNG 8 and PNG 16 files, gives 96 of 96 files byte-identical (r1 and r2, RGB and L).
   - The same test, written end to end by `WriteExport` at every export step: s2 and s3 give 72 files, 144 of 144 comparisons identical.
   - s0 and s1 are refused at evaluation: their bitmaps' sRGB space on an L8 channel is refused (decision 174).
   - `test_observed_template_bases_equal_painter_files`: 106 files, 212 of 212 comparisons, Dota 2's two Specular PNG 16 files included. Nothing is refused.
   - `test_l8_material_channels_are_written_encoded` (CPU): the recorded codes at PNG 8 and 16, and the three refusals.
   - `test_base_values_equal_the_empty_project_exports` compares Dota 2's L8 Specular PNG again.

## Consequences

- Release gap `l8-material-channel-png` is closed. Dota 2's Specular PNG export is exact.
- Still refused, release gap `l8-material-channel-png-unrecorded` (owner: the export encoder): OCIO, and channel mappings other than the recorded RGB and L files. Settling it needs a recording of an L8 Specular under OCIO, and of an RGB map that mixes it with another source or reads it through another letter.
- An evaluator finding for `phase1.15_compositor-colour-fits`, not changed here: on an L8 BaseColor, Specular or Emissive, Painter reads a grey bitmap close to sRGB. Decision 174's refusal message ("Painter refuses the space there") does not hold for these channels. Fitting that decode would make s0 and s1 of `export-l8-material` exact.
