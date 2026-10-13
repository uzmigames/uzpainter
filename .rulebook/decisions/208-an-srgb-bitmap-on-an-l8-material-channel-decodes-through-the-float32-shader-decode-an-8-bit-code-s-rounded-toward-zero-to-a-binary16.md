# 208. An sRGB bitmap on an L8 material channel decodes through the float32 shader decode, an 8-bit code's rounded toward zero to a binary16

**Status**: accepted
**Date**: 2026-10-13
**Related Tasks**: phase1.15_compositor-colour-fits

## Context

Decision 204 left an evaluator finding. `tier0/semantics/export-l8-material` (admitted and stable, decision 198) puts BaseColor, Specular and Emissive in L8. Each is filled from a grey bitmap in Painter's default space: grey A (16-bit, s0) and the 8-bit grey ramp (s1), UV at 1:1. Painter reads these codes close to sRGB, while the evaluator refused them at evaluation. Its message said "Painter refuses the space there" (decision 174), but decision 174 recorded that refusal only on user channels and on a mask's source.

Measured on the private store (counts only). The L8 code k is read from the OpenEXR 32f maps, which hold float32(k / 255). Every set, map and recording agrees:

- Each bitmap code maps to one L8 code, the same on BaseColor, Specular and Emissive and in r1 and r2. Grey A holds the 256 codes 257 c, so both sets cover the 256 values x = c / 255.
- **The IEC decode rounded to nearest** stores one code above Painter's at 13 of the 8-bit ramp's codes (7, 18, 72, 82, 123, 148, 167, 170, 178, 194, 209, 220, 243). It also does so at 10 of grey A's (the same codes except 194, 209 and 243).
- **16-bit (s0).** The float32 shader decode of decision 174, stored with the L8 write rule (`WriteUnorm`), gives 256 of 256 codes.
- **8-bit (s1).**
  - The same shader decode of x = float32(c / 255), rounded toward zero to a binary16 and then stored with the L8 write rule, gives 256 of 256 codes. The binary16 rounding is the one of decision 190.
  - Without the binary16 it misses 3 codes (194, 209 and 243, where s0 and s1 differ).
  - Rounding the binary16 to nearest misses 9. The GPU's sRGB8 texel (`Srgb8Operand`, the sRGB8 channel's rule) misses 30 codes, with or without a binary16.
  - With the binary16 toward zero, the double-precision IEC decode gives the same 256 codes, so the data cannot tell it apart from the shader decode. The shader decode is kept because it is the 16-bit rule.

The model panel was not consulted. The rule is the only candidate that is exact on all 512 recorded codes, and its domain is what the golden records.

## Decision

1. **The decode** (`SrgbDecoded`, `src/evaluator/evaluate.cpp`; rule in `sources.h`).
   - On an L8 BaseColor, Specular or Emissive (`SrgbL8MaterialChannel`), an sRGB bitmap (`sRGB` or `LegacyColorSpace.sRGB`) is decoded once per resource to a float32 image. It is cached apart from the sRGB8 decode (`/l8`, image key `/srgb-l8`).
   - A 16-bit code decodes as on an sRGB8 channel.
   - An 8-bit code is `HalfToFloat(HalfTowardZero(decode(float32(c / 255))))`, where decode is the contracted float32 shader decode with `hw::Pow`.
   - The value is stored with the L8 write rule. The GPU projection samples the same float32 image, so its kernel is unchanged.
2. **Lifted only where recorded.** The refusal is lifted for a grey 8- or 16-bit bitmap at 1:1 (the image is the set's size and the projection is the identity), under Legacy. `CheckSrgbL8MaterialBitmap` checks this at evaluation.
   - A colour bitmap or any resampling there fails with `evaluator:unsupported_source`, naming `export-l8-material`, phase1.15 and this decision.
   - Under OCIO it fails as before, through the OCIO checks of decision 190.
3. **The refusal messages.**
   - Decision 174's message "Painter refuses the space there" now covers only a user channel that is not sRGB8, and a mask's source. That is what decision 174 recorded.
   - On any other channel that is not sRGB8, such as an RGB16 BaseColor, an L8 AO or Height, sRGB is "not recorded". It fails with `unsupported_source` at evaluation, and with `NotYetSupported` before any mutation (`support.cpp`), naming phase1.15 and this decision.
4. **The facade is unchanged.** Painter's default space for a grey bitmap on BaseColor, Specular or Emissive is still unrecorded (`default_bitmap_space` refuses, decision 107's probe). So is its listing on an L8 material channel.
5. **Evidence.**
   - `tests/export/test_export_encoders.py::test_l8_material_channels_equal_painter_files`: every set of `export-l8-material` is rebuilt and written by `WriteExport` at every export step (PNG 8, PNG 16 and OpenEXR 32f, RGB and L). That gives 144 files and 288 of 288 comparisons byte-identical (r1 and r2), with no refusal. Before this decision, s0 and s1 were refused (72 files).
   - The native case `sources` checks the codes above on all three channels, and the refusals.
   - `not-yet-supported` checks the refusal before mutation on Height.
   - `projection-gpu-vs-cpu` and `test_lifted_colour_fits_gpu_equals_cpu[export-l8-material-s0/s1]` check GPU = CPU.

## Consequences

- `export-l8-material` is exact end to end in every set.
- Still unrecorded, owned by phase1.15_compositor-colour-fits: a colour or resampled sRGB bitmap on an L8 material channel; sRGB on the other non-sRGB8 formats of these channels and on the other non-user channels; Painter's default bitmap space and listing there (facade). The recording that settles them is a Tier 0 set with these cases:
  - an 8-bit colour bitmap, and the 8-bit ramp magnified by BilinearHQ at scale 0.5, on an L8 BaseColor;
  - the ramp on an RGB8 and an RGB16 BaseColor and on an L8 Roughness;
  - `get_color_space` and `list_available_color_spaces` read back on each.
