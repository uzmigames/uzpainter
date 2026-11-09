# 422. R-322 confirms the Unreal preset; TGA 8 holds the PNG 8 codes; OCIO 16-bit bitmaps are admitted where R-322 records them

**Status**: accepted
**Date**: 2026-11-09
**Related Tasks**: phase3.2_unreal-ue56-packed-preset (items 2.1, 2.3, 2.5), phase1.26_gate-g1 (decision 407's xfail)

## Context

Recording R-322 (`tier0/semantics/export-presets-unreal-packed-legacy`, record
`313c261b65d68c511404e3b24a99df6f223d3110b9db6ba1d32e1f7a56f8d599`, and `-ocio`,
`fd227d2a18fec4daac9b919c4e482dc77cf2365cbce237f1f0c021c885107dc7`; Painter 12.2.0, admitted
2026-10-24) has been in the private store since section 14 of the task. Decision 322 shipped the
preset `unconfirmed` and kept TGA refused until it was read. Measured on the store (counts only):

1. **Layout.** `ResourceExportPreset.list_output_maps` of the versioned URL
   `resource://starter_assets/Unreal Engine (Packed)?version=8339356058946582545.spexp` gives, r1
   and r2, both sessions, four maps: `$mesh_$textureSet_BaseColor(_$colorSpace)(.$udim)` (R, G, B
   from baseColor, A from opacity), `..._OcclusionRoughnessMetallic(...)` (R AO_Mixed, G roughness,
   B metallic), `..._Normal(...)` (Normal_DirectX) and `..._Emissive(...)` (emissive), each PNG 8,
   dithering on the Normal only. No SpecularWeight map, although the stack has the channel. Own
   parameters raise "padding algorithm could not be resolved" (no padding in the preset).
2. **Names under OCIO.** `BaseColor_sRGB`, `Emissive_sRGB`, `OcclusionRoughnessMetallic_Raw`,
   `Normal_Raw`, at PNG 8, TGA 8 and PNG 16.
3. **TGA 8.** The explicit TGA 8 probes write the same four files as the PNG 8 probes of the same
   session; every TGA equals its PNG 8 twin in decoded values (16 pairs per session), r1 = r2.
   Painter's TGA files are uncompressed with a footer; the comparison is in decoded values.
4. **OCIO 16-bit bitmaps.** R-322's OCIO session fills one Normal fill at opacity 1 on the
   bevelled cube with RGB16 bitmaps in sRGB on BaseColor and EmissionColor (sRGB8) and 16-bit
   bitmaps in Data, DataSigned and NormalXYZLeft on the other channels. Its
   OcclusionRoughnessMetallic and Normal files, and BaseColor's alpha, are identical to the Legacy
   twin's in every probe; BaseColor's and Emissive's colour differ (PNG 8: 9 and 5 samples).
5. **The sRGB8 code of a 16-bit sRGB code under OCIO.** On the admitted control
   `ocio16-bitmap-srgb-basecolor` (field-a, whose B holds every 16-bit code once), the stored code
   is a non-decreasing function of the 16-bit code: 255 breakpoints. Through the native PNG 16
   table (`kOcioSrgbPng16`) and sRGB8 operand they reproduce every recorded file of the control
   and of its two cyclic permutations `-field-a-brg` and `-field-a-gbr` (independent recordings)
   at PNG 8, PNG 16 and OpenEXR 32f, r1 and r2: 24 of 24 files, 0 misses; and R-322's BaseColor
   and Emissive on every covered texel of every probe. They include decision 406's three tie
   codes. The float32 that decision 405's RGB32F control stores is not reproduced by any formula
   tried (IEC in float32 and double, 1D LUTs of 256 to 65 536 nodes, binary16): the stored
   sRGB8 code is identified, the float before the store is not.

## Decision

1. **The preset is confirmed.** `unreal-engine-packed.json` takes Painter's file names
   (`(_$colorSpace)(.$udim)`) and per-map dithering (Normal only); its provenance (version 2)
   names both R-322 records, layout `confirmed`, each Painter map `confirmed`, SpecularWeight
   `defined` (UzPainter's own extension: Painter writes no such file). The DDS variant repeats the
   packing, with no dithering on its canonical PNG 16 files. The alias accepts R-322's
   `?version=8339356058946582545.spexp`.
2. **TGA 8 is written** as the PNG 8 codes of the same file, through the vendored stb writer
   (`EncodeTga`), RGB and RGBA only. Refused: another depth, an L or LA layout, dithering, a
   resize, and an alpha that is 1 everywhere (a PNG drops it; R-322 records no TGA with one).
3. **`$colorSpace` under OCIO** also names, at PNG 8, TGA 8 and PNG 16 (R-322): `sRGB` for an
   RGB of an sRGB8 BaseColor with a non-sRGB8 alpha and for an RGB of an sRGB8 EmissionColor;
   `Raw` for an RGB of Normal_DirectX and for AO_Mixed in R beside non-sRGB8 document channels.
4. **EmissionColor sRGB8 under OCIO** is written sRGB-encoded like BaseColor (decision 126's
   amendment extended to Painter's OCIO configuration on R-322's evidence).
5. **OCIO bitmap uses** (sources.h `OcioBitmapUseOf`, `OcioBitmapRecorded`):
   - a 16-bit bitmap in Data, DataSigned or NormalXYZLeft on a channel that is not sRGB8, at 1:1,
     read as under Legacy (fact 4);
   - a 16-bit colour bitmap in sRGB on an sRGB8 channel at 1:1, only as the one contributing
     root layer of its channel, a fill in Normal mode at opacity 1 without mask, geometry mask or
     effects (`OcioSoleFill`): each code reads as the sRGB8 operand of its breakpoint code
     (`OcioSrgb16Code`), which the fill stores unchanged. Any other blending, opacity, layer
     above or below, or sampling stays refused: there the value before the store matters and it
     is not identified (fact 5).
6. **AO_Mixed on the Alpha-blend template** (`virtual_maps.cpp`): R-314's Legacy cube (the
   Alpha-blend template, an L16 AO channel with one fill at opacity 1, grey A as the AO mesh map)
   equals decision 411's operator on every covered texel at PNG 16 and PNG 8, r1 and r2 (decision
   418 kept it as evidence only). The Alpha-blend template is admitted with no AO layer or an AO
   fill at opacity 1; R-322's Legacy ORM then evaluates.
7. **Decision 407's xfail narrows.** With these rules the R-322 TGA diagnostic runs every Legacy
   target and the OCIO Normal and ORM; the OCIO BaseColor stops at the evaluator's
   `missing_base_value` for Opacity, which the OCIO session adds as L8 to the default project's
   channels (EmissionColor, added as sRGB8, would stop the same way): the empty base of either is
   recorded under neither OCIO nor the default template. The strict xfail now expects that exact
   refusal (`OcioAddedBaseUnrecorded`); the decision-190 refusal coming back is a failure. The
   request `tier0/semantics/ocio-added-channel-bases` (an empty plane under OCIO with both channels
   added, exported as OpenEXR 32f and PNG 16) is authored; item 2.5 removes the mark once it is
   admitted and the bases are entered in `assets/templates/channel-defaults.json`. The facade's
   OCIO replay of `source-bitmap-defaults-unreal-ocio` xfails on the same gap.

## Alternatives Considered

- **A 65 536-entry float table from the RGB32F control.** Rejected: it would rest on one
  recording, no formula reproduces it, and nothing recorded needs the float itself.
- **Keeping `(_$colorSpace)` out of the shipped names.** Rejected: Painter's names carry it, and
  under OCIO the files would not have Painter's names.

## Consequences

- Items 2.1 and 2.3 of `phase3.2_unreal-ue56-packed-preset` hold.
- The pilots' Unreal goldens (item 3.1) can be compared through the shipped preset.
- Tests: `tests/export/test_unreal_preset.py` (layout against the private R-322, the plan by every
  reference, TGA, the shipped presets in AO_Mixed's scope), `tests/export/test_ocio16_srgb_fill.py`
  (the three RGB16 controls through the production export, every sample of PNG 8, PNG 16 and
  OpenEXR 32f in r1 and r2; another opacity refused), `tests/export/test_ao_mixed_islands.py`,
  `tests/export/test_tga_capture_replay.py`, `tests/export/test_export_plan.py`,
  `tests/export/test_export_presets.py`. Breakpoints: `python -m tools.parity.fit.ocio16_srgb8_breakpoints`
  (`verify` counts, `table` the initializer).
